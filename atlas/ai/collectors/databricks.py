"""Databricks AI asset collector (dbx_ai_collector), DESIGN.md 7.1.

Runs inside a job as the job identity. Each adapter runs behind a probe, so an
unreadable source becomes a recorded ``unavailable`` / ``degraded`` state
instead of silently missing rows. All config passes ``redaction.redact``;
provider credential configs only ever reach ``summarize_credentials``.

Stable source_entity_id per kind (DESIGN.md 4.1):
- serving_endpoint / agent: endpoint ``id`` (fallback ``name``)
- external_model: ``<endpoint id>/<served entity name>``
- ai_model: model ``full_name``; ai_model_version: ``<full_name>@<version>``
- mcp_server: connection ``full_name`` (fallback ``name``)
- uc_function_tool: function ``full_name``

Sample provenance (decision D1: real, labeled sample objects only): the seed
script marks what it creates with ``SAMPLE_TAG_KEY`` (endpoint tag) or
``[atlas-sample:<run>]`` in the comment (models, functions, connections, whose
tags are not observable). Such observations get ``provenance_class='sample'``.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from atlas.ai import models
from atlas.ai.models import Observation, ProbeResult, RunContext
from atlas.ai.probes import Degraded, not_configured, not_supported, probe
from atlas.ai.redaction import redact, scrub, summarize_credentials

COLLECTOR = "dbx_ai_collector"
COLLECTOR_VERSION = "1.0.0"
SOURCE_SYSTEM = "databricks"

SAMPLE_TAG_KEY = "atlas_sample_run_id"
_SAMPLE_COMMENT_RE = re.compile(r"\[atlas-sample:([A-Za-z0-9_.\-]+)\]")

MAX_MODELS = 500
MAX_VERSIONS_PER_MODEL = 20
AGENT_TASK_PREFIX = "agent/"

SOURCES = ("serving_endpoints", "registered_models", "mcp_connections", "uc_function_tools", "ai_asset_registry")


def _as_dict(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return dict(obj)
    as_dict = getattr(obj, "as_dict", None)
    return as_dict() if callable(as_dict) else {}


def _enum_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def sample_marker(tags: Mapping[str, str] | None = None, comment: Optional[str] = None) -> Optional[str]:
    if tags and tags.get(SAMPLE_TAG_KEY):
        return str(tags[SAMPLE_TAG_KEY])
    match = _SAMPLE_COMMENT_RE.search(comment or "")
    return match.group(1) if match else None


def _observation(
    ctx: RunContext,
    *,
    kind: str,
    source_entity_id: str,
    sample_run_id: Optional[str],
    **fields: Any,
) -> Observation:
    return Observation(
        run_id=ctx.run_id,
        source_system=SOURCE_SYSTEM,
        collector=COLLECTOR,
        collector_version=COLLECTOR_VERSION,
        entity_kind=kind,
        source_entity_id=source_entity_id,
        observed_at=models.utc_now(),
        provenance_class=models.PROVENANCE_SAMPLE if sample_run_id else models.PROVENANCE_ORGANIC,
        sample_run_id=sample_run_id,
        **fields,
    )


# --------------------------------------------------------------- endpoints
def _normalize_endpoint(raw: Mapping[str, Any]) -> Dict[str, Any]:
    endpoint = dict(raw)
    gateway = dict(endpoint.get("ai_gateway") or {})
    # `key` would be scrubbed as credential-shaped; it is the rate-limit scope.
    gateway["rate_limits"] = [
        {**{k: v for k, v in dict(limit).items() if k != "key"}, "scope": dict(limit).get("key")}
        for limit in gateway.get("rate_limits") or []
    ]
    endpoint["ai_gateway"] = gateway
    return endpoint


def _provider_config(external_model: Mapping[str, Any]) -> Dict[str, Any]:
    for name, value in external_model.items():
        if name.endswith("_config") and isinstance(value, Mapping):
            return dict(value)
    return {}


def collect_serving_endpoints(
    w: Any, ctx: RunContext, *, fetch_detail: Optional[Callable[[str], Any]] = None
) -> List[Observation]:
    """Endpoints (or agents, for task agent/v1/*) plus one external_model
    observation per external served entity. ``list()`` omits provider configs
    (PHASE0 V2), so ``get()`` runs only for endpoints with external models, and
    only to summarize credential posture for AIC-09."""
    fetch = fetch_detail or (lambda name: w.serving_endpoints.get(name))
    observations: List[Observation] = []
    detail_failures: List[str] = []
    for endpoint in w.serving_endpoints.list():
        raw = _as_dict(endpoint)
        endpoint_id = str(raw.get("id") or raw.get("name") or "")
        if not endpoint_id:
            continue
        # Tags are free text returned to readers: scrub credential-shaped
        # keys/values like any other config.
        tags = scrub({str(t.get("key")): str(t.get("value") or "") for t in raw.get("tags") or [] if t.get("key")}) or {}
        task = str(raw.get("task") or "")
        kind = models.AGENT if task.startswith(AGENT_TASK_PREFIX) else models.SERVING_ENDPOINT
        marker = sample_marker(tags)
        served = list((raw.get("config") or {}).get("served_entities") or [])
        external = [se for se in served if se.get("external_model")]

        credentials: Dict[str, Dict[str, Any]] = {}
        if external:
            try:
                detail = _as_dict(fetch(str(raw.get("name"))))
                for se in (detail.get("config") or {}).get("served_entities") or []:
                    if se.get("external_model"):
                        credentials[str(se.get("name"))] = summarize_credentials(_provider_config(se["external_model"]))
            except Exception as exc:  # noqa: BLE001 - recorded as degraded below
                detail_failures.append(f"{raw.get('name')}: {type(exc).__name__}")

        relationships = []
        for se in served:
            if se.get("external_model"):
                relationships.append(
                    {"kind": "serves", "target_kind": models.EXTERNAL_MODEL, "target_source_entity_id": f"{endpoint_id}/{se.get('name')}"}
                )
            elif se.get("entity_name") and se.get("entity_version") and str(se.get("entity_name")).count(".") == 2:
                relationships.append(
                    {
                        "kind": "serves",
                        "target_kind": models.AI_MODEL_VERSION,
                        "target_source_entity_id": f"{se['entity_name']}@{se['entity_version']}",
                    }
                )
        config = redact("serving_endpoint", _normalize_endpoint(raw))
        config["served_entities"] = [redact("served_entity", se) for se in served]
        observations.append(
            _observation(
                ctx,
                kind=kind,
                source_entity_id=endpoint_id,
                sample_run_id=marker,
                display_name=raw.get("name"),
                platform="external" if served and len(external) == len(served) else "databricks",
                provider=_enum_value((external[0]["external_model"] or {}).get("provider")) if external else None,
                owner=raw.get("creator"),
                tags=tags,
                config=config,
                relationships=relationships,
            )
        )
        for se in external:
            em = se["external_model"]
            se_config = redact("served_entity", se)
            se_config["credentials"] = credentials.get(
                str(se.get("name")), {"observable": False, "secret_refs": [], "plaintext_fields": []}
            )
            observations.append(
                _observation(
                    ctx,
                    kind=models.EXTERNAL_MODEL,
                    source_entity_id=f"{endpoint_id}/{se.get('name')}",
                    sample_run_id=marker,
                    parent_source_entity_id=endpoint_id,
                    display_name=f"{raw.get('name')} / {se.get('name')}",
                    platform="external",
                    provider=_enum_value(em.get("provider")),
                    model_family=em.get("name"),
                    owner=raw.get("creator"),
                    # Governed tags live on the endpoint; the served entity
                    # inherits them so M1 matching works for either.
                    tags=tags,
                    config=se_config,
                    relationships=[{"kind": "served_by", "target_kind": kind, "target_source_entity_id": endpoint_id}],
                )
            )
    if detail_failures:
        raise Degraded(
            f"credential posture unreadable for {len(detail_failures)} endpoint(s): {', '.join(detail_failures[:5])}",
            value=observations,
        )
    return observations


# ------------------------------------------------------------------ models
def collect_registered_models(w: Any, ctx: RunContext, *, catalogs: Sequence[str]) -> List[Observation]:
    """Models and versions with aliases. Aliases need a per-model get()
    (PHASE0 V1); models the job identity cannot read degrade the source
    instead of vanishing. Model tags are not observable in SDK 0.95."""
    listings: List[Any] = []
    if catalogs:
        # The API rejects catalog_name without schema_name ("Cannot have an
        # empty schema if the catalog is set"), so enumerate schemas.
        for catalog in catalogs:
            for schema in w.schemas.list(catalog_name=catalog):
                name = getattr(schema, "name", None)
                if name and name != "information_schema":
                    listings.extend(w.registered_models.list(catalog_name=catalog, schema_name=name))
    else:
        listings.extend(w.registered_models.list())
    observations: List[Observation] = []
    denied: List[str] = []
    for listed in listings[:MAX_MODELS]:
        full_name = str(getattr(listed, "full_name", "") or "")
        if not full_name or getattr(listed, "browse_only", False):
            continue
        try:
            model = _as_dict(w.registered_models.get(full_name, include_aliases=True))
            versions = [_as_dict(v) for v in list(w.model_versions.list(full_name, max_results=MAX_VERSIONS_PER_MODEL))]
        except Exception as exc:  # noqa: BLE001 - per-model permission failures degrade
            denied.append(f"{full_name}: {type(exc).__name__}")
            continue
        marker = sample_marker(comment=model.get("comment"))
        aliases = model.get("aliases") or []
        observations.append(
            _observation(
                ctx,
                kind=models.AI_MODEL,
                source_entity_id=full_name,
                sample_run_id=marker,
                display_name=full_name,
                platform="databricks",
                owner=model.get("owner"),
                config=redact("registered_model", model),
            )
        )
        for version in versions[:MAX_VERSIONS_PER_MODEL]:
            number = version.get("version")
            if number is None:
                continue
            version_aliases = [a for a in aliases if str(a.get("version_num")) == str(number)]
            observations.append(
                _observation(
                    ctx,
                    kind=models.AI_MODEL_VERSION,
                    source_entity_id=f"{full_name}@{number}",
                    sample_run_id=marker,
                    parent_source_entity_id=full_name,
                    display_name=f"{full_name} v{number}",
                    platform="databricks",
                    owner=version.get("created_by") or model.get("owner"),
                    config=redact("model_version", {**version, "model_name": full_name, "aliases": version_aliases}),
                    relationships=[{"kind": "version_of", "target_kind": models.AI_MODEL, "target_source_entity_id": full_name}],
                )
            )
    problems = []
    if denied:
        problems.append(f"{len(denied)} model(s) unreadable: {', '.join(denied[:5])}")
    if len(listings) > MAX_MODELS:
        # A silent cap would read as "the rest are gone" and auto-resolve
        # their findings; report the source as degraded instead.
        problems.append(f"only the first {MAX_MODELS} of {len(listings)} models were collected; narrow ai_catalog_allowlist")
    if problems:
        raise Degraded("; ".join(problems), value=observations)
    return observations


# ------------------------------------------------------------- connections
def _list_connections_raw(w: Any) -> Iterable[Dict[str, Any]]:
    """Raw REST so connection_type stays a string: newer types (for example
    MANAGED_POSTGRESQL) deserialize to None in SDK 0.95 (PHASE0 V4)."""
    token: Optional[str] = None
    while True:
        query = {"page_token": token} if token else None
        page = w.api_client.do("GET", "/api/2.1/unity-catalog/connections", query=query) or {}
        yield from page.get("connections") or []
        token = page.get("next_page_token")
        if not token:
            return


def is_mcp_connection(connection: Mapping[str, Any]) -> bool:
    options = connection.get("options") or {}
    return str(connection.get("connection_type") or "").upper() == "HTTP" and str(options.get("is_mcp_connection", "")).lower() == "true"


def collect_mcp_connections(w: Any, ctx: RunContext) -> List[Observation]:
    observations = []
    for connection in _list_connections_raw(w):
        if not is_mcp_connection(connection):
            continue
        source_id = str(connection.get("full_name") or connection.get("name") or "")
        if not source_id:
            continue
        observations.append(
            _observation(
                ctx,
                kind=models.MCP_SERVER,
                source_entity_id=source_id,
                sample_run_id=sample_marker(comment=connection.get("comment")),
                display_name=connection.get("name"),
                platform="databricks",
                owner=connection.get("owner"),
                config=redact("connection", connection),
            )
        )
    return observations


# --------------------------------------------------------------- functions
def collect_uc_function_tools(w: Any, ctx: RunContext, *, schemas: Sequence[str]) -> List[Observation]:
    """UC functions in allowlisted ``catalog.schema`` entries (V7). Function
    tags are not observable: information_schema.routine_tags is rejected as
    unsupported (verified live, Phase 1), so tools carry no tags and match by
    M3 or a steward confirmation."""
    observations = []
    for entry in schemas:
        parts = [p for p in str(entry).split(".") if p]
        if len(parts) != 2:
            continue
        catalog, schema = parts
        for function in w.functions.list(catalog, schema):
            raw = _as_dict(function)
            full_name = str(raw.get("full_name") or "")
            if not full_name:
                continue
            observations.append(
                _observation(
                    ctx,
                    kind=models.UC_FUNCTION_TOOL,
                    source_entity_id=full_name,
                    sample_run_id=sample_marker(comment=raw.get("comment")),
                    display_name=full_name,
                    platform="databricks",
                    owner=raw.get("owner"),
                    config=redact("uc_function", raw),
                )
            )
    return observations


# --------------------------------------------------------------- orchestrate
def collect(
    w: Any,
    ctx: RunContext,
    *,
    catalogs: Sequence[str],
    tool_schemas: Sequence[str],
) -> Tuple[List[Observation], Dict[str, ProbeResult]]:
    """Run every adapter behind a probe. Returns observations plus one
    ProbeResult per source for reconciliation_runs.sources_json."""
    results: Dict[str, ProbeResult] = {}
    observations: List[Observation] = []

    def run(source: str, fn: Callable[[], List[Observation]]) -> None:
        result, value = probe(source, fn)
        results[source] = result
        observations.extend(value or [])

    run("serving_endpoints", lambda: collect_serving_endpoints(w, ctx))
    run("registered_models", lambda: collect_registered_models(w, ctx, catalogs=catalogs))
    run("mcp_connections", lambda: collect_mcp_connections(w, ctx))
    if tool_schemas:
        run("uc_function_tools", lambda: collect_uc_function_tools(w, ctx, schemas=tool_schemas))
    else:
        results["uc_function_tools"] = not_configured("uc_function_tools", "No tool schemas configured (ai_tool_schema_allowlist is empty).")
    results["ai_asset_registry"] = not_supported(
        "ai_asset_registry", "No AI asset registry API exists in databricks-sdk 0.95 (agents are observed from agent/* serving endpoints)."
    )
    return observations, results
