"""Generative AI for agentic in-app helpers (AI autofill of freeform fields).

Distinct from Genie (which is NL2SQL over governed metadata): this calls a
Databricks foundation-model serving endpoint (a reasoning model by default) to
DRAFT text — a glossary definition, a suggested domain, etc. Everything it
returns is a draft the user reviews and edits before saving; it never writes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping

from axiom.config import AppConfig
from axiom.services.assets import normalize_str
from axiom.services.workspace_clients import cached_workspace_client


def _env_seconds(name: str, default: int) -> int:
    import os

    try:
        return max(5, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _timeout_kwargs() -> Dict[str, int]:
    """Per-attempt HTTP timeout and total SDK retry budget for the serving
    call. SDK defaults (60 s per attempt, 300 s of retries on 429/503) outlast
    the 120 s Databricks Apps request limit."""
    return {
        "http_timeout_seconds": _env_seconds("AXIOM_AI_HTTP_TIMEOUT_S", 30),
        "retry_timeout_seconds": _env_seconds("AXIOM_AI_RETRY_TIMEOUT_S", 60),
    }


def _cfg(config: AppConfig, name: str, default: Any = "") -> Any:
    return getattr(config, name, default)


def provider_status(config: AppConfig) -> Dict[str, Any]:
    endpoint = normalize_str(_cfg(config, "ai_generation_endpoint"))
    if not endpoint:
        return {"state": "unavailable", "endpoint": "", "message": "AI autofill endpoint is not configured."}
    return {"state": "available", "endpoint": endpoint, "message": "AI autofill is configured."}


def _workspace_client(config: AppConfig | None = None, user_access_token: str = ""):
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.config import Config
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("databricks-sdk is required for AI autofill.") from exc
    import os

    def _client(**kwargs: Any):
        return WorkspaceClient(config=Config(**kwargs, **_timeout_kwargs()))

    token = normalize_str(user_access_token)
    host = normalize_str(_cfg(config, "workspace_host")) if config is not None else ""
    if not host:
        # In the Databricks App runtime config.workspace_host can be empty; the
        # SDK env still carries the host. Without it the M2M branch below was
        # skipped and we fell back to the app's PAT (no model-serving scope).
        host = os.environ.get("DATABRICKS_HOST", "").strip()
        if host and not host.startswith("http"):
            host = "https://" + host
    if token and host:
        return cached_workspace_client(
            f"ai-obo:{host}",
            token,
            WorkspaceClient,
            lambda: _client(
                host=host, token=token, auth_type="pat",
                product="axiom", product_version="axiom-ai-generation-obo",
            ),
        )
    # App service principal: the serving-endpoint CAN_QUERY grant is on the SP,
    # so force OAuth M2M (client_id/secret). The app's default DATABRICKS_TOKEN
    # is a PAT that lacks the model-serving scope, so we must NOT fall through to
    # the default WorkspaceClient() (which would pick up that PAT).
    client_id = os.environ.get("DATABRICKS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        kwargs = dict(
            client_id=client_id, client_secret=client_secret, auth_type="oauth-m2m",
            product="axiom", product_version="axiom-ai-generation-m2m",
        )
        if host:
            kwargs["host"] = host
        return cached_workspace_client(
            f"ai-m2m:{host}:{client_id}", "", WorkspaceClient, lambda: _client(**kwargs)
        )
    return cached_workspace_client("ai-default", "", WorkspaceClient, _client)


# ---------------------------------------------------------------- prompt specs
# Each "kind" maps a context dict → (system prompt, user prompt, allowed fields).
# The model is instructed to return STRICT JSON with only the allowed fields, so
# the frontend can drop the values straight into the form. Definitions stay
# short and plain — these seed a draft, not a final artifact.

def _glossary_term_prompt(context: Mapping[str, Any]) -> tuple[str, str, List[str]]:
    term = normalize_str(context.get("termName") or context.get("name"))
    domain = normalize_str(context.get("domain"))
    system = (
        "You are a data-governance glossary assistant for an enterprise data catalog. "
        "You write concise, plain-language business definitions that analysts and stewards "
        "can trust. You never invent company-specific facts; if a term is ambiguous you give "
        "the common business meaning. Respond ONLY with strict minified JSON."
    )
    user = (
        f"Draft a glossary entry for the business term: \"{term}\".\n"
        f"{('The term is in the ' + domain + ' domain. ') if domain else ''}"
        "Return JSON with exactly these keys:\n"
        '  "definition": a 1-2 sentence plain-language business definition (no restating the term verbatim),\n'
        '  "domain": the single most likely business domain (e.g. Finance, Customer, Marketing, Risk, Operations, Product),\n'
        '  "acronymExpansion": the expansion if the term is an acronym, else "".\n'
        "Do not include any prose outside the JSON."
    )
    return system, user, ["definition", "domain", "acronymExpansion"]


_PROMPT_BUILDERS = {
    "glossaryTerm": _glossary_term_prompt,
}


def _extract_json(text: str) -> Dict[str, Any]:
    raw = normalize_str(text)
    if not raw:
        return {}
    # Models sometimes wrap JSON in prose or ```json fences — pull the first {...}.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        brace = re.search(r"\{.*\}", raw, re.DOTALL)
        candidate = brace.group(0) if brace else raw
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or (response.get("choices") if isinstance(response, dict) else None)
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None) or (first.get("message") if isinstance(first, dict) else None)
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return normalize_str(content)


def generate_fields(
    *,
    config: AppConfig,
    kind: str,
    context: Mapping[str, Any],
    client: Any | None = None,
    user_access_token: str = "",
) -> Dict[str, Any]:
    """Draft form-field values for `kind` from `context`. Returns
    {fields: {...}, model, warnings}. Raises on a misconfigured provider."""
    status = provider_status(config)
    if status["state"] != "available":
        raise RuntimeError(status["message"])
    builder = _PROMPT_BUILDERS.get(normalize_str(kind))
    if builder is None:
        raise ValueError(f"Unsupported AI autofill kind: {kind!r}")
    system, user, allowed = builder(context or {})

    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

    w = client or _workspace_client(config, user_access_token=user_access_token)
    # NB: some models (e.g. Claude Opus 4.8 on Databricks) reject `temperature`,
    # so it is intentionally omitted — the strict-JSON prompt is deterministic
    # enough without it.
    response = w.serving_endpoints.query(
        name=status["endpoint"],
        messages=[
            ChatMessage(role=ChatMessageRole.SYSTEM, content=system),
            ChatMessage(role=ChatMessageRole.USER, content=user),
        ],
        max_tokens=400,
    )
    parsed = _extract_json(_message_content(response))
    # Only surface allowed keys, trimmed; drop empties so the UI fills selectively.
    fields = {}
    for key in allowed:
        value = normalize_str(parsed.get(key))
        if value:
            fields[key] = value
    warnings = [] if fields else ["The model did not return usable draft values; try a more specific name."]
    return {"fields": fields, "model": status["endpoint"], "warnings": warnings}
