"""Allowlist serializers for AI asset configuration (DESIGN.md section 8).

Two lines of defense, both always applied:

1. ``redact(object_type, data)`` keeps only fields named in that type's
   allowlist. Anything not listed is dropped, never masked.
2. ``scrub`` then walks what survived and drops any key whose name looks like
   a credential, and any string value shaped like one (``sk-...``,
   ``dapi...``, JWTs, ``Bearer ...``, cloud access keys).

Provider credential configs (``openai_config``, ``anthropic_config``, ...) and
``environment_vars`` are never passed through ``redact``. The SDK exposes
``*_plaintext`` key fields on them (PHASE0_FINDINGS V2);
``summarize_credentials`` records only *which* fields held a secret reference
or a plaintext value, never the values. A value in Databricks secret reference
syntax is kept only as ``{"secret_ref": "<scope>/<key>"}``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

# Allowlist specs: a field maps to True (keep scalar), a nested spec (dict),
# or a one-element list holding the spec for each list item.
Spec = Dict[str, Any]

ALLOWLISTS: Dict[str, Spec] = {
    "serving_endpoint": {
        "name": True,
        "task": True,
        "route_optimized": True,
        "state": {"ready": True, "config_update": True},
        "ai_gateway": {
            "usage_tracking_config": {"enabled": True},
            "inference_table_config": {
                "enabled": True,
                "catalog_name": True,
                "schema_name": True,
                "table_name_prefix": True,
            },
            # Rate limits are normalized by the collector with `key` renamed
            # to `scope` (the credential scrubber drops any key named `key`).
            "rate_limits": [{"calls": True, "tokens": True, "renewal_period": True, "scope": True, "principal": True}],
            # Presence and behaviors only: keyword/topic lists are dropped.
            "guardrails": {
                "input": {"safety": True, "pii": {"behavior": True}},
                "output": {"safety": True, "pii": {"behavior": True}},
            },
            "fallback_config": {"enabled": True},
        },
    },
    "served_entity": {
        "name": True,
        "entity_name": True,
        "entity_version": True,
        "workload_size": True,
        "workload_type": True,
        "scale_to_zero_enabled": True,
        "foundation_model": {"name": True, "display_name": True},
        "external_model": {"provider": True, "name": True, "task": True},
    },
    "registered_model": {
        "full_name": True,
        "name": True,
        "catalog_name": True,
        "schema_name": True,
        "owner": True,
        "comment": True,
        "aliases": [{"alias_name": True, "version_num": True}],
    },
    "model_version": {
        "model_name": True,
        "version": True,
        "status": True,
        "run_id": True,
        "aliases": [{"alias_name": True, "version_num": True}],
    },
    # `url` is excluded: it can carry userinfo or query-string tokens. Host and
    # base path come from the allowlisted options instead.
    "connection": {
        "name": True,
        "full_name": True,
        "connection_type": True,
        "owner": True,
        "comment": True,
        "options": {"host": True, "base_path": True, "port": True, "is_mcp_connection": True, "auth_scheme": True},
    },
    # routine_definition is excluded: function bodies can embed secrets.
    "uc_function": {
        "full_name": True,
        "name": True,
        "catalog_name": True,
        "schema_name": True,
        "owner": True,
        "comment": True,
        "data_type": True,
        "routine_body": True,
        "security_type": True,
        "input_params": {"parameters": [{"name": True, "type_text": True}]},
    },
}

# Key segments that mark a credential. Keys are split on `_`, `-`, and `.` and
# compared case-insensitively, so `tokens` (a rate-limit count) survives while
# `api_key`, `client_secret`, `auth_token`, and `Authorization` do not.
_CREDENTIAL_SEGMENTS = frozenset(
    {"key", "apikey", "token", "secret", "password", "passwd", "credential", "credentials", "private", "bearer", "authorization"}
)

_SECRET_REF_VALUE_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
_SECRET_REF_RE = re.compile(r"^\{\{\s*secrets/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)\s*\}\}$")
# Searched anywhere in a value (not anchored): a key pasted into a comment or
# description must not survive. Boundaries keep ordinary words ("task-...")
# from matching.
_CREDENTIAL_VALUE_RES = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI/Anthropic-style keys
    re.compile(r"(?<![A-Za-z0-9])dapi[0-9a-f]{20,}", re.IGNORECASE),  # Databricks PAT
    re.compile(r"(?<![A-Za-z0-9])dose[0-9a-f]{20,}", re.IGNORECASE),  # Databricks OAuth secret
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]*"),  # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    # HTTP Basic credentials: base64 with at least one digit, +, / or =, so
    # prose like "Basic sentiment classifier" survives.
    re.compile(r"\b[Bb]asic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{16,}={0,2}"),
    re.compile(r"(^|[^A-Z0-9])(AKIA|ASIA)[0-9A-Z]{16}([^A-Z0-9]|$)"),  # AWS access key id
    re.compile(r"\b(ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{10,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def secret_ref(value: Any) -> Optional[str]:
    """``"<scope>/<key>"`` for a Databricks secret reference string, else None."""
    if not isinstance(value, str):
        return None
    match = _SECRET_REF_RE.match(value.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def is_credential_key(name: Any) -> bool:
    # Split camelCase first so clientSecret / accessToken are caught too.
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    segments = re.split(r"[_\-.\s]+", text.lower())
    return any(segment in _CREDENTIAL_SEGMENTS for segment in segments if segment)


def looks_like_credential(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return any(pattern.search(text) for pattern in _CREDENTIAL_VALUE_RES)


def scrub(value: Any) -> Any:
    """Recursively drop credential-named keys and credential-shaped values.

    Secret references survive as ``{"secret_ref": ...}`` even under a
    credential-named key, because the reference names a vault entry, not the
    secret. Returns ``None`` for a dropped scalar so callers can omit it.
    """
    if isinstance(value, Mapping):
        # Pass through only a well-formed "<scope>/<key>" reference; anything
        # else under a secret_ref key is scrubbed like any other value.
        if set(value.keys()) == {"secret_ref"} and isinstance(value.get("secret_ref"), str) and _SECRET_REF_VALUE_RE.match(value["secret_ref"]):
            return {"secret_ref": value["secret_ref"]}
        cleaned: Dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            ref = secret_ref(raw_val)
            if ref:
                cleaned[str(raw_key)] = {"secret_ref": ref}
                continue
            if is_credential_key(raw_key):
                continue
            item = scrub(raw_val)
            if item is None and raw_val is not None:
                continue
            cleaned[str(raw_key)] = item
        return cleaned
    if isinstance(value, (list, tuple)):
        items = []
        for raw_item in value:
            ref = secret_ref(raw_item)
            if ref:
                items.append({"secret_ref": ref})
                continue
            item = scrub(raw_item)
            if item is None and raw_item is not None:
                continue
            items.append(item)
        return items
    if looks_like_credential(value):
        return None
    return value


def _apply(spec: Any, value: Any) -> Any:
    if spec is True:
        # Scalars only: an unexpected nested object under a scalar slot is
        # dropped rather than passed through unreviewed.
        return value if not isinstance(value, (Mapping, list, tuple)) else None
    if isinstance(spec, list):
        if not isinstance(value, (list, tuple)):
            return None
        return [item for item in (_apply(spec[0], v) for v in value) if item not in (None, {}, [])]
    if isinstance(spec, dict):
        if not isinstance(value, Mapping):
            return None
        out: Dict[str, Any] = {}
        for name, sub_spec in spec.items():
            if name in value and value[name] is not None:
                item = _apply(sub_spec, value[name])
                if item not in (None, {}, []):
                    out[name] = item
        return out
    return None


_USERINFO_RE = re.compile(r"^((?:[A-Za-z][A-Za-z0-9+.\-]*:)?//)?[^/@\s]*@")


def strip_userinfo(host: Any) -> Any:
    """Drop ``user:password@`` from a host or URL value."""
    return _USERINFO_RE.sub(lambda m: m.group(1) or "", host) if isinstance(host, str) else host


def redact(object_type: str, data: Mapping[str, Any]) -> Dict[str, Any]:
    """Allowlist, then scrub. Unknown object types yield ``{}`` (fail closed)."""
    spec = ALLOWLISTS.get(object_type)
    if spec is None or not isinstance(data, Mapping):
        return {}
    out = scrub(_apply(spec, data)) or {}
    options = out.get("options")
    if object_type == "connection" and isinstance(options, dict):
        if "host" in options:
            options["host"] = strip_userinfo(options["host"])
        if isinstance(options.get("base_path"), str):
            # Query strings can carry tokens (?api_key=...); keep the path only.
            options["base_path"] = options["base_path"].split("?", 1)[0].split("#", 1)[0]
    return out


def summarize_credentials(provider_config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Credential posture of an external-model provider config, values omitted.

    Returns ``{"observable": bool, "secret_refs": [{"field", "secret_ref"}],
    "plaintext_fields": [field names]}``. ``observable`` is False when the API
    returned no credential fields at all (the dev workspace behavior, even for
    CAN_MANAGE callers), which makes AIC-09 evaluate ``unknown``.
    """
    refs = []
    plaintext = []
    populated = False
    for name, raw in sorted((provider_config or {}).items()):
        if raw in (None, ""):
            continue
        if not is_credential_key(name):
            continue
        populated = True
        ref = secret_ref(raw)
        if ref:
            refs.append({"field": str(name), "secret_ref": ref})
        elif str(name).endswith("_plaintext") or isinstance(raw, str):
            plaintext.append(str(name))
    return {"observable": populated, "secret_refs": refs, "plaintext_fields": plaintext}
