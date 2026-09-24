"""Composite Governance Atlas view-model APIs."""

from __future__ import annotations

import hashlib
import datetime as dt
import re
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import APIRouter, Body, HTTPException, Query, Request
from atlas.util import error_text
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import pandas as pd

from atlas.api.cache import _ttl_cache_pop, _ttl_fresh_value, _ttl_stale_value, _ttl_value
from atlas.api.identity import _request_auth_mode, _user_email
from atlas.api.response import _error_response, _with_meta
from atlas.services import atlas_metrics
from atlas.services import assets as asset_service
from atlas.services import capabilities as capability_service
from atlas.services import genie as genie_service
from atlas.services import governance as governance_service
from atlas.services import input_safety
from atlas.services.assets import normalize_str as _normalize_str

_ASSET_360_WARMING: set[str] = set()
_ASSET_360_WARMING_LOCK = threading.Lock()
_TAXONOMY_OVERVIEW_WARMING: set[str] = set()
_TAXONOMY_OVERVIEW_WARMING_LOCK = threading.Lock()
_ADMIN_CONTROL_WARMING: set[str] = set()
_ADMIN_CONTROL_WARMING_LOCK = threading.Lock()
_CDE_DASHBOARD_WARMING: set[str] = set()
_CDE_DASHBOARD_WARMING_LOCK = threading.Lock()
_COMMAND_CENTER_WARMING: set[str] = set()
_COMMAND_CENTER_WARMING_LOCK = threading.Lock()
_AUDIT_EVIDENCE_WARMING: set[str] = set()
_AUDIT_EVIDENCE_WARMING_LOCK = threading.Lock()


def _sdk_get(obj: Any, *path: str) -> Any:
    cur = obj
    for part in path:
        if cur is None:
            return None
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def _enum_text(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return _normalize_str(raw).replace("_", " ")


def _job_timestamp_label(value: Any) -> str:
    # Empty means "no timestamp": the frontend renders its own honest
    # fallback ("Not yet run"); baking placeholder sentences server-side
    # defeated that. The year is included because Databricks job created /
    # run times routinely cross year boundaries — "Aug 25, 23:47" read as
    # current-year data when the source epoch was 2025.
    try:
        if value is None or value == "":
            return ""
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric = numeric / 1000.0
        return dt.datetime.fromtimestamp(numeric, tz=dt.timezone.utc).strftime(
            "%b %-d, %Y %H:%M UTC"
        )
    except Exception:
        return _normalize_str(value)


def _job_schedule_label(settings: Any) -> str:
    schedule = _sdk_get(settings, "schedule")
    if not schedule:
        return "Manual"
    cron = _normalize_str(_sdk_get(schedule, "quartz_cron_expression"))
    timezone = _normalize_str(_sdk_get(schedule, "timezone_id"))
    pause_status = _normalize_str(_sdk_get(schedule, "pause_status")).upper()
    label = cron or "Scheduled"
    if timezone:
        label = f"{label} · {timezone}"
    if pause_status == "PAUSED":
        label = f"Paused · {label}"
    return label


def _job_status_label(job: Any, latest_run: Any | None = None) -> str:
    state = _sdk_get(latest_run, "state")
    result = _enum_text(_sdk_get(state, "result_state"))
    lifecycle = _enum_text(_sdk_get(state, "life_cycle_state"))
    if result:
        return result.title()
    if lifecycle:
        return lifecycle.title()
    # No run history: derive the status from the job's ACTUAL trigger
    # configuration instead of defaulting to "Scheduled" — manual jobs
    # (no schedule/trigger/continuous config) were mislabeled as scheduled.
    settings = _sdk_get(job, "settings")
    schedule = _sdk_get(settings, "schedule")
    if schedule is not None:
        pause_status = _normalize_str(_sdk_get(schedule, "pause_status")).upper()
        return "Paused" if pause_status == "PAUSED" else "Scheduled"
    if _sdk_get(settings, "continuous") is not None:
        return "Continuous"
    if _sdk_get(settings, "trigger") is not None:
        # File-arrival / table-update triggers: event-driven, not cron.
        return "Triggered"
    return "Manual"


def _databricks_job_inventory(
    uc_client: Any,
    *,
    limit: int = 6,
    include_latest_runs: bool = False,
    workspace_host: str = "",
) -> list[dict[str, Any]]:
    # Callers may pass None when the app-principal client could not be
    # constructed; degrade to an empty inventory instead of raising.
    jobs_api = getattr(getattr(uc_client, "w", None), "jobs", None)
    list_jobs = getattr(jobs_api, "list", None)
    if not callable(list_jobs):
        return []
    try:
        job_iter = list_jobs(limit=max(limit, 12))
    except TypeError:
        job_iter = list_jobs()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    list_runs = getattr(jobs_api, "list_runs", None) if include_latest_runs else None
    host = _normalize_str(workspace_host) or _normalize_str(
        _sdk_get(uc_client, "_client_context", "host")
    )
    host = host.rstrip("/")
    # The SDK returns a lazy pager: the actual list API call (and any scope
    # error like "token does not have required scopes: jobs") fires during
    # iteration, NOT at list_jobs(). Guard the loop so a missing jobs scope
    # degrades job inventory to empty instead of raising through the whole
    # control-center warm loader (which left the endpoint stuck loading).
    try:
        job_iter = list(job_iter)
    except Exception:
        return []
    for job in job_iter:
        job_id = _sdk_get(job, "job_id") or _sdk_get(job, "job_id".upper())
        settings = _sdk_get(job, "settings") or {}
        name = _normalize_str(_sdk_get(settings, "name") or _sdk_get(settings, "job_name"))
        if not job_id or not name:
            continue
        latest_run = None
        if callable(list_runs):
            try:
                run_iter = list_runs(job_id=job_id, limit=1)
                latest_run = next(iter(run_iter), None)
            except Exception:
                latest_run = None
        rows.append(
            {
                "id": str(job_id),
                "name": name,
                "schedule": _job_schedule_label(settings),
                # lastRun comes ONLY from a real run. The old created_time
                # fallback rendered a job's CREATION timestamp under "Last
                # run" for never-run jobs; empty lets the UI show its honest
                # "Not yet run" state instead.
                "lastRun": _job_timestamp_label(
                    _sdk_get(latest_run, "start_time")
                    or _sdk_get(latest_run, "end_time")
                ),
                # The Jobs list API exposes the cron config but not the next
                # fire time, and we never fabricate timestamps — nextRun is
                # therefore only populated when a future scheduled run is
                # actually known (empty until then; the UI renders a dash).
                "nextRun": "",
                "status": _job_status_label(job, latest_run),
                "url": f"{host}/jobs/{job_id}" if host else "",
                "source": "databricks-jobs-api",
            }
        )
        if len(rows) >= limit:
            break
    return rows


class AtlasAiContext(BaseModel):
    """Page-awareness context the dock sends with each question.

    ``surface`` is the current left-nav surface id; ``assetFqn`` is the asset
    the user is looking at (route asset or peek drawer). Both feed the Genie
    prompt preamble so "this asset" / "on this page" questions resolve to the
    concrete surface the user is on.
    """

    surface: str = Field(default="", max_length=64)
    assetFqn: str = Field(default="", max_length=512)
    # Active facet filters from the Discover URL (domain/criticality/tier/…),
    # so "here"/"this page" resolves to the actual scope. Sanitized + capped.
    scope: dict | None = None

    @field_validator("surface", "assetFqn", mode="before")
    @classmethod
    def _sanitize_context(cls, value):
        return input_safety.sanitize_plain_text(
            value,
            field="context",
            max_length=512,
            allow_empty=True,
        )

    @field_validator("scope", mode="before")
    @classmethod
    def _sanitize_scope(cls, value):
        if not isinstance(value, Mapping):
            return None

        def _clean(raw, limit):
            # Pre-truncate BEFORE sanitizing: sanitize_plain_text RAISES on
            # overflow, so a long search box (scope.query) would 422 the whole
            # AI request. Truncating first turns that into a safe, dropped value.
            try:
                text = str(raw) if raw is not None else ""
                return input_safety.sanitize_plain_text(
                    text[:limit], field="scope", max_length=limit, allow_empty=True
                )
            except Exception:
                return ""

        cleaned: dict[str, Any] = {}
        for raw_key, raw_val in list(value.items())[:12]:  # cap keys
            key = _clean(raw_key, 32)
            if not key:
                continue
            if isinstance(raw_val, (list, tuple)):
                items = [item for item in (_clean(item, 128) for item in list(raw_val)[:24]) if item]
                if items:
                    cleaned[key] = items
            else:
                item = _clean(raw_val, 128)
                if item:
                    cleaned[key] = item
        return cleaned or None


class AtlasAiQuestion(BaseModel):
    question: str = Field(default="", max_length=2000)
    context: AtlasAiContext | None = None

    @field_validator("question", mode="before")
    @classmethod
    def _sanitize_question(cls, value):
        return input_safety.sanitize_plain_text(
            value,
            field="question",
            max_length=2000,
            allow_empty=True,
        )


class AtlasAiAutofill(BaseModel):
    """Body for POST /atlas-ai/autofill — draft freeform field values from
    context (e.g. a glossary term name) using the generative endpoint."""

    kind: str = Field(default="", max_length=64)
    context: dict | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _sanitize_kind(cls, value):
        return input_safety.sanitize_plain_text(value, field="kind", max_length=64, allow_empty=True)

    @field_validator("context", mode="before")
    @classmethod
    def _sanitize_ctx(cls, value):
        if not isinstance(value, Mapping):
            return None
        cleaned: dict[str, Any] = {}
        for raw_key, raw_val in list(value.items())[:12]:
            key = input_safety.sanitize_plain_text(raw_key, field="ctx", max_length=48, allow_empty=True)
            if not key:
                continue
            cleaned[key] = input_safety.sanitize_plain_text(
                str(raw_val)[:500] if raw_val is not None else "", field="ctx", max_length=500, allow_empty=True
            )
        return cleaned or None


class AtlasAiPoll(BaseModel):
    """Body for POST /atlas-ai/message — polls a running Genie conversation for
    its progress stage and, when complete, the finalized answer."""

    conversationId: str = Field(default="", max_length=256)
    messageId: str = Field(default="", max_length=256)
    question: str = Field(default="", max_length=2000)
    context: AtlasAiContext | None = None

    @field_validator("conversationId", "messageId", mode="before")
    @classmethod
    def _sanitize_id(cls, value):
        return input_safety.sanitize_plain_text(value, field="genieId", max_length=256, allow_empty=True)

    @field_validator("question", mode="before")
    @classmethod
    def _sanitize_poll_question(cls, value):
        return input_safety.sanitize_plain_text(value, field="question", max_length=2000, allow_empty=True)


def _steward_or_admin(request: Request) -> str:
    from runtime_app import _user_role_slug

    role = _user_role_slug(request)
    if role not in ("admin", "steward"):
        raise HTTPException(status_code=403, detail="Steward or admin role required.")
    return role


def _admin_required(request: Request) -> str:
    from runtime_app import _user_role_slug

    role = _user_role_slug(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return role


def _wrap(
    payload: dict,
    request: Request,
    *,
    source: str,
    state: str = "available",
    authoritative: bool = True,
    entity_fqn: str | None = None,
    entity_id: str | None = None,
    warnings: list[str] | None = None,
    capabilities: dict | None = None,
) -> JSONResponse:
    envelope = _with_meta(
        payload,
        request,
        source=source,
        state=state,
        authoritative=authoritative,
        entity_fqn=entity_fqn,
        entity_id=entity_id,
        warnings=warnings,
        capabilities=capabilities,
    )
    return JSONResponse(envelope)


def _route_cache_key(prefix: str, *parts: Any) -> str:
    raw = "\0".join(_normalize_str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _request_scope_key(request: Request) -> str:
    try:
        from runtime_app import _request_cache_scope

        return _normalize_str(_request_cache_scope(request)) or "shared"
    except Exception:
        auth_mode = _normalize_str(_request_auth_mode(request)) or "unknown-auth"
        actor = _normalize_str(_user_email(request)) or "unknown-actor"
        return f"{auth_mode}:{actor}"


def _genie_row_value(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        text = _normalize_str(value)
        if text:
            return text
    return ""


def _recommendations_from_genie_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Derive clickable recommendation cards from Genie-returned SQL rows.

    This is not a local fallback: the only source is Databricks Genie query
    evidence already returned for this actor and question.
    """

    recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evidence or []:
        rows = item.get("resultRows") if isinstance(item.get("resultRows"), list) else []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            asset_fqn = _genie_row_value(
                row,
                "asset_fqn",
                "assetFqn",
                "fqn",
                "entity_fqn",
                "table_full_name",
            )
            if not asset_fqn or asset_fqn in seen:
                continue
            seen.add(asset_fqn)
            domain = _genie_row_value(row, "domain", "governance_domain")
            data_product = _genie_row_value(row, "data_product", "dataProduct")
            owner_count = _genie_row_value(row, "owner_count", "owners", "ownerCount")
            open_work_count = _genie_row_value(row, "open_work_count", "openWorkCount", "request_count")
            criticality = _genie_row_value(row, "criticality", "tier")
            certification = _genie_row_value(row, "certification", "certification_status")
            signals = [
                f"domain {domain}" if domain else "",
                f"product {data_product}" if data_product else "",
                f"{owner_count} owners" if owner_count else "",
                f"{open_work_count} open work items" if open_work_count else "",
                f"criticality {criticality}" if criticality else "",
                f"certification {certification}" if certification else "",
            ]
            detail = "; ".join(part for part in signals if part)
            recommendations.append(
                {
                    "title": f"Review {asset_fqn.rsplit('.', 1)[-1]}",
                    "detail": detail or "Genie returned this actor-visible asset as governed priority evidence.",
                    "provider": "databricks-genie",
                    "evidence": [
                        {
                            "type": "asset",
                            "id": asset_fqn,
                            "metric": "genieQueryEvidence",
                            "statementId": _normalize_str(item.get("statementId")),
                        }
                    ],
                    "suggestedActions": [
                        {"label": "Open Discovery", "surface": "discovery"},
                        {"label": "Review Governance", "surface": "governance"},
                    ],
                }
            )
            if len(recommendations) >= 3:
                return recommendations
    return recommendations


def _row_text(row: Mapping[str, Any], key: str) -> str:
    try:
        return _normalize_str(row.get(key))
    except Exception:
        return ""


def _live_metadata_atlas_ai_payload(
    question: str,
    request: Request,
    *,
    genie_status: Mapping[str, Any],
    warnings: Sequence[str],
) -> dict[str, Any] | None:
    """Answer with backed workspace metadata when Genie cannot run for this actor.

    This is deliberately not a local recommendation substitute for an empty Genie
    result. It only runs before Genie when no forwarded OBO token is available,
    and every returned row is sourced from the live Unity Catalog inventory plus
    Governance Atlas control-plane metadata.
    """

    from runtime_app import _visible_assets

    try:
        visible_assets = _visible_assets(request)
    except Exception:
        return None
    if visible_assets is None or getattr(visible_assets, "empty", True):
        return None

    rows: list[dict[str, str]] = []
    iterrows = getattr(visible_assets, "iterrows", None)
    if not callable(iterrows):
        return None
    for _, row in iterrows():
        fqn = _row_text(row, "fqn")
        if not fqn:
            continue
        certification = _row_text(row, "certification") or "Uncertified"
        criticality = _row_text(row, "criticality") or _row_text(row, "tier") or "Unspecified"
        governance_status = _row_text(row, "governance_status")
        rows.append(
            {
                "asset_fqn": fqn,
                "asset_name": fqn.rsplit(".", 1)[-1],
                "domain": _row_text(row, "domain") or "Unassigned",
                "certification": certification,
                "criticality": criticality,
                "tier": _row_text(row, "tier") or "Unassigned",
                "owner": _row_text(row, "owners_summary")
                or _row_text(row, "business_owner")
                or _row_text(row, "technical_owner")
                or "Unassigned",
                "governance_status": governance_status or "Unspecified",
            }
        )

    if not rows:
        return None

    question_text = _normalize_str(question).lower()
    if "certif" in question_text:
        selected = [
            row
            for row in rows
            if row["certification"].lower() != "certified"
            and (
                "critical" in row["criticality"].lower()
                or "tier 1" in row["tier"].lower()
            )
        ]
        subject = "critical assets that are not Certified"
    elif "owner" in question_text or "steward" in question_text:
        selected = [row for row in rows if row["owner"].lower() == "unassigned"]
        subject = "assets missing owner evidence"
    else:
        selected = [
            row
            for row in rows
            if row["governance_status"].lower() != "enterprise ready"
            or row["certification"].lower() not in {"certified", "trusted"}
        ]
        subject = "priority governed metadata assets"
    if not selected:
        selected = rows[:3]
        subject = "priority governed metadata assets"
    selected = selected[:4]

    evidence = [
        {
            "type": "asset",
            "id": row["asset_fqn"],
            "assetFqn": row["asset_fqn"],
            "label": row["asset_fqn"],
            "metric": "workspaceScopedLiveMetadata",
            "domain": row["domain"],
            "certification": row["certification"],
            "criticality": row["criticality"],
            "owner": row["owner"],
            "source": "unity-catalog-inventory+governance-store",
        }
        for row in selected
    ]
    recommendations = [
        {
            "title": f"Review {row['asset_name']}",
            "detail": (
                f"{row['domain']} domain; {row['certification']} certification; "
                f"{row['criticality']} criticality; owner {row['owner']}."
            ),
            "provider": "governance-atlas-live-metadata",
            "evidence": [evidence[index]],
            "suggestedActions": [
                {"label": "Open asset", "surface": "entity", "assetFqn": row["asset_fqn"]},
                {"label": "Review governance", "surface": "governance"},
            ],
        }
        for index, row in enumerate(selected)
    ]
    bullets = "\n".join(
        f"- `{row['asset_fqn']}` - {row['domain']} / {row['certification']} / {row['owner']}"
        for row in selected
    )
    answer = (
        f"**Workspace-scoped governed evidence** found {len(selected)} {subject}.\n\n"
        f"{bullets}\n\n"
        "Genie cannot run for this actor until Databricks OBO is available, so this answer uses only live Unity Catalog "
        "inventory and Governance Atlas control-plane metadata."
    )
    return {
        "question": question,
        "intent": "live_metadata",
        "answer": answer,
        "recommendations": recommendations,
        "evidence": evidence,
        "suggestedActions": [
            action
            for recommendation in recommendations
            for action in recommendation.get("suggestedActions", [])
        ][:4],
        "confidence": "workspace-scoped-live-metadata",
        "provider": "governance-atlas-live-metadata",
        "providerState": dict(genie_status or {}),
        "warnings": list(warnings or []),
    }


def _hidden_asset_error(asset_fqn: str, request: Request, visibility: dict, *, source: str) -> JSONResponse:
    if visibility.get("visibilityState") == "hidden":
        return _error_response(
            request,
            status_code=404,
            source=source,
            detail="Asset exists but is not visible in the current workspace scope.",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={"visibilityState": "hidden"},
        )
    if visibility.get("visibilityState") == "unknown":
        detail = (
            visibility.get("reason")
            or "Asset visibility could not be verified in the current workspace scope."
        )
        return _error_response(
            request,
            status_code=503,
            source=source,
            detail=detail,
            state="unknown",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={"visibilityState": "unknown"},
            warnings=[detail],
        )
    return _error_response(
        request,
        status_code=404,
        source=source,
        detail="Asset not found.",
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        capabilities={"visibilityState": visibility.get("visibilityState") or "missing"},
    )


def _extract_visible_asset_fqns(frame) -> list[str]:
    try:
        if frame is None or frame.empty or "fqn" not in frame.columns:
            return []
        return [
            _normalize_str(value)
            for value in frame["fqn"].dropna().astype(str).tolist()
            if _normalize_str(value)
        ]
    except Exception:
        return []


def api_command_center(
    request: Request,
    refresh: Optional[str] = Query(default=None),
) -> JSONResponse:
    from runtime_app import (
        _fast_bootstrap_inventory_summary,
        _request_cache_scope,
        _store_for_read,
        _uc_runtime_status_fast,
        _uc_for_request,
        _visible_assets,
    )
    from atlas.api.cache import _ttl_cache_pop

    runtime_status = _uc_runtime_status_fast()
    if runtime_status.get("state") != "live":
        message = (
            _normalize_str(runtime_status.get("message"))
            or "Command-center metrics are waiting on the live Databricks runtime."
        )
        return _wrap(
            atlas_metrics.empty_command_center_payload(),
            request,
            source="unity-catalog-inventory+governance-store",
            state="loading",
            authoritative=False,
            warnings=[message],
            capabilities={"runtimeState": runtime_status.get("state") or "loading"},
        )
    refresh_flag = _normalize_str(refresh).lower() in {"1", "true", "yes"}
    cache_scope = _normalize_str(_request_cache_scope(request)) or _request_scope_key(request)
    runtime_inventory_cache_key = f"runtime_inventory:{cache_scope}"
    if refresh_flag:
        _ttl_cache_pop(runtime_inventory_cache_key)
    cached_inventory = _ttl_fresh_value(runtime_inventory_cache_key, 300)
    summary = _fast_bootstrap_inventory_summary(cache_scope, start_background=True)
    if cached_inventory is None and summary.get("summaryState") == "loading":
        loading_payload = atlas_metrics.empty_command_center_payload()
        loading_payload["meta"] = {
            "warnings": [
                "Command-center metrics are still loading from live Databricks metadata."
            ]
        }
        return _wrap(
            loading_payload,
            request,
            source="unity-catalog-inventory+governance-store",
            state="loading",
            authoritative=False,
            warnings=loading_payload["meta"]["warnings"],
            capabilities={"refresh": True},
        )
    uc_client = _uc_for_request(request)
    payload_cache_key = _route_cache_key("atlas_command_center_payload", cache_scope)
    if refresh_flag:
        _ttl_cache_pop(payload_cache_key)

    def load_command_center_payload() -> dict[str, Any]:
        visible_assets = cached_inventory if cached_inventory is not None else _visible_assets(request)
        return atlas_metrics.command_center_payload(
            visible_assets=visible_assets,
            store=_store_for_read(),
            # Snapshot history and lineage coverage are partitioned by the
            # same scope as the payload cache so trends always match the
            # numbers the viewer actually sees.
            scope_key=cache_scope,
            system_uc=uc_client,
        )

    # Stale-while-revalidate: when the TTL lapses, serve the last good payload
    # while the background warm rebuilds it. Returning the empty loading
    # envelope here made the home page flip available -> loading -> available
    # on every cache expiry, blanking all KPIs for live users.
    stale_payload: Optional[dict] = None
    if not refresh_flag and _ttl_fresh_value(payload_cache_key, 45) is None:
        with _COMMAND_CENTER_WARMING_LOCK:
            should_warm = payload_cache_key not in _COMMAND_CENTER_WARMING
            if should_warm:
                _COMMAND_CENTER_WARMING.add(payload_cache_key)

        if should_warm:
            def warm_command_center_payload() -> None:
                try:
                    try:
                        _ttl_value(payload_cache_key, 45, load_command_center_payload)
                    except Exception:
                        pass
                finally:
                    with _COMMAND_CENTER_WARMING_LOCK:
                        _COMMAND_CENTER_WARMING.discard(payload_cache_key)

            threading.Thread(
                target=warm_command_center_payload,
                name="atlas-command-center-warm",
                daemon=True,
            ).start()

        stale_payload = _ttl_stale_value(payload_cache_key)
        if stale_payload is None:
            loading_payload = atlas_metrics.empty_command_center_payload()
            loading_payload["meta"] = {
                "warnings": [
                    "Command-center metrics are still loading from live Databricks metadata."
                ]
            }
            return _wrap(
                loading_payload,
                request,
                source="unity-catalog-inventory+governance-store",
                state="loading",
                authoritative=False,
                warnings=loading_payload["meta"]["warnings"],
                capabilities={"refresh": True, "hydrating": True},
            )

    if stale_payload is not None:
        payload = stale_payload
    else:
        try:
            payload = _ttl_value(payload_cache_key, 45, load_command_center_payload)
        except Exception as exc:
            return _error_response(
                request,
                status_code=503,
                source="unity-catalog-inventory+governance-store",
                detail=_normalize_str(exc) or "Command center metrics are unavailable.",
                state="unavailable",
            )

    payload_meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    payload_warnings = [
        _normalize_str(warning)
        for warning in (payload_meta.get("warnings") or [])
        if _normalize_str(warning)
    ]
    warnings = payload_warnings
    degraded = bool(payload_warnings)
    response = _with_meta(
        payload,
        request,
        source="unity-catalog-inventory+governance-store",
        state="degraded" if degraded else "available",
        authoritative=not degraded,
        warnings=warnings or None,
        capabilities={"refresh": True},
    )
    return JSONResponse(response)


def api_asset_360(asset_fqn: str, request: Request) -> JSONResponse:
    from runtime_app import (
        HIDDEN_CATALOGS,
        _asset_detail_payload,
        _asset_visibility_record,
        _direct_uc_metadata_writes_enabled,
        _ensure_live_runtime,
        _request_cache_scope,
        _store_for_read,
        _uc_for_request,
    )

    _ensure_live_runtime()
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    visibility = _asset_visibility_record(asset_fqn, request)
    if visibility.get("visibilityState") == "loading":
        detail = asset_service.asset_loading_payload(asset_fqn)
        # hydrating=True: visibility is unverified, so no store/access joins
        # run here and the composite blocks present as loading, not
        # unavailable (cohesion law 3 — loading is never terminal absence).
        payload = atlas_metrics.asset_360_payload(
            detail=detail,
            hydrating=True,
            operational_included=actor_scoped,
        )
        reason = (
            visibility.get("reason")
            or "The asset record is still loading from live Unity Catalog inventory."
        )
        return _wrap(
            payload,
            request,
            source="unity-catalog-detail+governance-store+quality-runner+lineage",
            state="loading",
            authoritative=False,
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            warnings=[reason],
            capabilities={
                "visibilityState": "loading",
                "requestedSections": [],
                "loadedSections": [],
                "deferredSections": detail.get("deferredSections") or [],
                "hydrating": True,
            },
        )
    if not visibility.get("openable"):
        return _hidden_asset_error(
            asset_fqn,
            request,
            visibility,
            source="unity-catalog-detail+governance-store+quality-runner+lineage",
        )

    sections = ["header", "activity", "schema", "properties", "profiler"]
    if actor_scoped:
        sections.append("operational")
    uc_client = _uc_for_request(request)
    store = _store_for_read()
    cache_scope = _request_cache_scope(request)
    allow_direct_metadata_write = _direct_uc_metadata_writes_enabled(request)
    full_detail = asset_service.cached_asset_detail_payload(
        uc_client,
        asset_fqn,
        cache_scope=cache_scope,
        sections=sections,
    )
    hydrating = full_detail is None

    if hydrating:
        warm_key = f"{cache_scope}:{asset_fqn}:{','.join(sections)}"
        with _ASSET_360_WARMING_LOCK:
            should_warm = warm_key not in _ASSET_360_WARMING
            if should_warm:
                _ASSET_360_WARMING.add(warm_key)

        if should_warm:
            def warm_asset_360() -> None:
                try:
                    try:
                        asset_service.asset_detail_payload(
                            uc_client,
                            store,
                            asset_fqn,
                            cache_scope=cache_scope,
                            hidden_catalogs=HIDDEN_CATALOGS,
                            sections=sections,
                            allow_direct_metadata_write=allow_direct_metadata_write,
                        )
                    except Exception:
                        pass
                finally:
                    with _ASSET_360_WARMING_LOCK:
                        _ASSET_360_WARMING.discard(warm_key)

            threading.Thread(
                target=warm_asset_360,
                name=f"atlas-asset360-warm-{asset_fqn}",
                daemon=True,
            ).start()

        cached_header = asset_service.cached_asset_detail_payload(
            uc_client,
            asset_fqn,
            cache_scope=cache_scope,
            sections=["header", "activity"],
        )
        detail = cached_header or asset_service.asset_loading_payload(asset_fqn)
    else:
        detail = full_detail
    # Real composite joins (teardown P0-3): store-backed quality summary,
    # access-explain core, and split freshness fields ride the same payload
    # instead of hard-coded "unavailable" constants.
    payload = atlas_metrics.asset_360_payload(
        detail=detail,
        store=store,
        asset_fqn=asset_fqn,
        auth_mode=_request_auth_mode(request),
        actor_email=_user_email(request) or "",
        operational_included=actor_scoped,
        hydrating=hydrating,
    )
    warnings = []
    if not actor_scoped:
        warnings.append(
            "Operational usage and protected lineage context are degraded until Databricks per-user authorization / OBO is available for actor-scoped reads."
        )
    if hydrating:
        warnings.append(
            "Asset 360 is hydrating schema, properties, profiler, and operational context from live Databricks metadata."
        )
    return _wrap(
        payload,
        request,
        source="unity-catalog-detail+governance-store+quality-runner+lineage",
        state="loading" if hydrating else ("available" if actor_scoped else "degraded"),
        authoritative=actor_scoped and not hydrating,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        warnings=warnings or None,
        capabilities={
            "visibilityState": visibility.get("visibilityState"),
            "requestedSections": sections,
            "loadedSections": detail.get("loadedSections") or [],
            "deferredSections": detail.get("deferredSections") or [],
            "hydrating": hydrating,
        },
    )


def api_governance_workbench(request: Request) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _store_for_read, _visible_assets

    _ensure_live_runtime()
    cache_key = _route_cache_key("atlas_governance_workbench_payload", _request_scope_key(request))

    def load_workbench_payload() -> dict[str, Any]:
        # Visible-asset scope powers the honest "N target assets outside the
        # visible estate" caption. If the inventory read fails, the payload
        # simply omits the scope split (never fabricates a count of 0).
        try:
            visible_asset_fqns = _extract_visible_asset_fqns(_visible_assets(request)) or None
        except Exception:
            visible_asset_fqns = None
        return atlas_metrics.governance_workbench_payload(
            store=_store_for_read(),
            visible_asset_fqns=visible_asset_fqns,
        )

    payload = _ttl_value(cache_key, 30, load_workbench_payload)
    payload_meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    source_available = payload_meta.get("sourceAvailable") is not False
    source_reason = _normalize_str(payload_meta.get("sourceReason")) or "Governance store requests are unavailable."
    return _wrap(
        payload,
        request,
        source="governance-store",
        state="available" if source_available else "unavailable",
        authoritative=source_available,
        warnings=None if source_available else [source_reason],
    )


def api_governance_request_detail(request_id: str, request: Request) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _store_for_read

    _ensure_live_runtime()
    cache_key = _route_cache_key(
        "atlas_governance_request_detail_payload",
        _request_scope_key(request),
        request_id,
    )
    payload = _ttl_value(
        cache_key,
        30,
        lambda: atlas_metrics.governance_request_detail_payload(
            store=_store_for_read(),
            request_id=request_id,
        ),
    )
    if payload is None:
        return _error_response(
            request,
            status_code=404,
            source="governance-store",
            detail="Governance request not found.",
            entity_id=request_id,
        )
    return _wrap(
        payload,
        request,
        source="governance-store",
        state="available",
        authoritative=True,
        entity_id=request_id,
    )


def api_insights_dashboard(request: Request) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _store_for_read, _visible_assets

    _ensure_live_runtime()
    cache_key = _route_cache_key("atlas_insights_dashboard_payload", _request_scope_key(request))
    payload = _ttl_value(
        cache_key,
        45,
        lambda: atlas_metrics.insights_dashboard_payload(
            visible_assets=_visible_assets(request),
            store=_store_for_read(),
        ),
    )
    capabilities = payload.get("signalAvailability") or {}
    warnings = []
    if not capabilities.get("quality"):
        warnings.append("Quality health score is unavailable; maturity score excludes quality health.")
    if not capabilities.get("policyCompliance"):
        warnings.append("Policy compliance is unavailable until an authoritative policy evaluation source is configured.")
    if not capabilities.get("auditReadiness"):
        warnings.append("Audit readiness is unavailable until a readiness formula/source is configured.")
    if capabilities.get("policyExceptions") == "degraded":
        warnings.append("Critical policy exceptions are text-derived from governance requests and audit records.")
    state = "degraded" if warnings else "available"
    return _wrap(
        payload,
        request,
        source="unity-catalog-inventory+quality-runner",
        state=state,
        authoritative=not warnings,
        warnings=warnings or None,
        capabilities=capabilities,
    )


def api_taxonomy_overview(
    request: Request,
    refresh: Optional[str] = Query(default=None),
) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _store_for_read, _uc_for_request

    _ensure_live_runtime()
    refresh_flag = _normalize_str(refresh).lower() in {"1", "true", "yes"}
    cache_key = _route_cache_key(
        "atlas_taxonomy_overview",
        _request_auth_mode(request),
        _user_email(request),
    )
    if refresh_flag:
        _ttl_cache_pop(cache_key)

    def load_taxonomy_overview() -> dict[str, Any]:
        store = _store_for_read()
        warnings: list[str] = []
        enriched_glossary = None
        try:
            enriched_glossary = governance_service.glossary_terms(
                _uc_for_request(request),
                store,
                actor_email=_user_email(request),
                limit=120,
            )
        except Exception as exc:
            warnings.append(
                _normalize_str(exc)
                or "Glossary enrichment is unavailable; taxonomy overview is using raw glossary rows."
            )
        payload = atlas_metrics.taxonomy_overview_payload(
            store=store,
            glossary_terms=enriched_glossary,
        )
        return {
            "payload": payload,
            "warnings": warnings,
            "capabilities": {
                "glossaryEnriched": enriched_glossary is not None,
                "classificationTree": bool(payload.get("classifications")),
                "domainTree": bool(payload.get("domains")),
                "dataProducts": bool(payload.get("dataProducts")),
                "columnGroups": bool(payload.get("columnGroups")),
            },
        }

    cached_entry = _ttl_fresh_value(cache_key, 90)
    # Stale-while-revalidate: keep serving the last good overview while the
    # background warm refreshes it; only first-ever loads see the loading state.
    stale_entry = None
    if not refresh_flag and cached_entry is None:
        with _TAXONOMY_OVERVIEW_WARMING_LOCK:
            should_warm = cache_key not in _TAXONOMY_OVERVIEW_WARMING
            if should_warm:
                _TAXONOMY_OVERVIEW_WARMING.add(cache_key)

        if should_warm:
            def warm_taxonomy_overview() -> None:
                try:
                    try:
                        _ttl_value(cache_key, 90, load_taxonomy_overview)
                    except Exception:
                        pass
                finally:
                    with _TAXONOMY_OVERVIEW_WARMING_LOCK:
                        _TAXONOMY_OVERVIEW_WARMING.discard(cache_key)

            threading.Thread(
                target=warm_taxonomy_overview,
                name="atlas-taxonomy-overview-warm",
                daemon=True,
            ).start()

        stale_entry = _ttl_stale_value(cache_key)
        if stale_entry is None:
            payload = atlas_metrics.taxonomy_overview_payload(store=None, glossary_terms=[])
            return _wrap(
                payload,
                request,
                source="governance-store+unity-catalog-inventory",
                state="loading",
                authoritative=False,
                warnings=["Taxonomy overview is hydrating from the governance store and Unity Catalog metadata."],
                capabilities={
                    "glossaryEnriched": False,
                    "classificationTree": False,
                    "domainTree": False,
                    "dataProducts": False,
                    "columnGroups": False,
                    "hydrating": True,
                },
            )

    cached = stale_entry if stale_entry is not None else _ttl_value(cache_key, 90, load_taxonomy_overview)
    payload = cached.get("payload") if isinstance(cached, dict) else {}
    warnings = cached.get("warnings") if isinstance(cached, dict) else []
    capabilities = cached.get("capabilities") if isinstance(cached, dict) else {}
    return _wrap(
        payload,
        request,
        source="governance-store+unity-catalog-inventory",
        state="degraded" if warnings else "available",
        authoritative=not warnings,
        warnings=warnings or None,
        capabilities=capabilities,
    )


def api_cde_dashboard(
    request: Request,
    refresh: Optional[str] = Query(default=None),
) -> JSONResponse:
    from runtime_app import (
        _cached_visible_assets,
        _ensure_live_runtime,
        _fast_bootstrap_inventory_summary,
        _request_cache_scope,
        _visible_assets,
    )

    _ensure_live_runtime()
    cache_key = _route_cache_key("atlas_cde_dashboard_payload", _request_scope_key(request))
    refresh_flag = _normalize_str(refresh).lower() in {"1", "true", "yes"}
    if refresh_flag:
        _ttl_cache_pop(cache_key)
    cached_entry = _ttl_fresh_value(cache_key, 60)
    if cached_entry is None and _cached_visible_assets(request) is None and not refresh_flag:
        _fast_bootstrap_inventory_summary(_request_cache_scope(request), start_background=True)
        with _CDE_DASHBOARD_WARMING_LOCK:
            should_warm = cache_key not in _CDE_DASHBOARD_WARMING
            if should_warm:
                _CDE_DASHBOARD_WARMING.add(cache_key)

        if should_warm:
            def warm_cde_dashboard() -> None:
                try:
                    try:
                        _ttl_value(
                            cache_key,
                            60,
                            lambda: atlas_metrics.cde_dashboard_payload(
                                visible_assets=_visible_assets(request)
                            ),
                        )
                    except Exception:
                        pass
                finally:
                    with _CDE_DASHBOARD_WARMING_LOCK:
                        _CDE_DASHBOARD_WARMING.discard(cache_key)

            threading.Thread(
                target=warm_cde_dashboard,
                name="atlas-cde-dashboard-warm",
                daemon=True,
            ).start()

        payload = atlas_metrics.cde_dashboard_payload(visible_assets=pd.DataFrame())
        return _wrap(
            payload,
            request,
            source="unity-catalog-inventory+governance-store",
            state="loading",
            authoritative=False,
            warnings=[
                "CDE dashboard is hydrating from actor-visible Unity Catalog inventory."
            ],
            capabilities={"controlCoverage": False, "hydrating": True},
        )
    payload = _ttl_value(
        cache_key,
        60,
        lambda: atlas_metrics.cde_dashboard_payload(visible_assets=_visible_assets(request)),
    )
    # The route used to wrap EVERY response as state=degraded, so /atlas/cde
    # looked permanently broken even when items were fully backed by
    # actor-visible inventory. Now: degraded only when the registry has no
    # backed rows; otherwise available, with warnings listing which signals
    # are still partial.
    items_backed = bool(isinstance(payload, dict) and payload.get("items"))
    summary = payload.get("summary") if isinstance(payload, dict) else None
    warnings = [
        "Dedicated CDE control coverage is unavailable; controls are marked unavailable rather than inferred."
    ]
    if items_backed and isinstance(summary, dict) and summary.get("overdueReviews") is None:
        warnings.append(
            "Overdue-review counts require both a recert window tag and a last-review timestamp; no visible CDE row carries both yet."
        )
    return _wrap(
        payload,
        request,
        source="unity-catalog-inventory+governance-store",
        state="available" if items_backed else "degraded",
        authoritative=items_backed,
        warnings=warnings,
        capabilities={"controlCoverage": False},
    )


def api_cde_detail(cde_id: str, request: Request) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _visible_assets

    _ensure_live_runtime()
    cache_key = _route_cache_key("atlas_cde_detail_payload", _request_scope_key(request), cde_id)
    payload = _ttl_value(
        cache_key,
        60,
        lambda: atlas_metrics.cde_detail_payload(
            visible_assets=_visible_assets(request),
            cde_id=cde_id,
        ),
    )
    if payload is None:
        return _error_response(
            request,
            status_code=404,
            source="unity-catalog-inventory+governance-store",
            detail="Critical data element not found in visible metadata.",
            entity_id=cde_id,
        )
    return _wrap(
        payload,
        request,
        source="unity-catalog-inventory+governance-store",
        state="degraded",
        authoritative=False,
        entity_id=cde_id,
        warnings=[
            "Dedicated CDE control coverage is unavailable; controls are marked unavailable rather than inferred."
        ],
        capabilities={"controlCoverage": False},
    )


def api_audit_evidence(
    request: Request,
    audit_id: Optional[str] = Query(default=None),
    date_range: Optional[str] = Query(default=None),
    # Default matches AUDIT_EVIDENCE_DEFAULT_LIMIT: visibility scoping drops
    # rows about out-of-scope assets, so a 200-row fetch starved the feed.
    limit: int = Query(default=500, ge=1, le=500),
    refresh: Optional[str] = Query(default=None),
) -> JSONResponse:
    from runtime_app import _ensure_live_runtime, _store_for_read, _visible_assets

    _ensure_live_runtime()
    actor_role = _steward_or_admin(request)
    audit_id_value = audit_id if isinstance(audit_id, str) else None
    date_range_value = date_range if isinstance(date_range, str) else None
    limit_value = int(limit) if isinstance(limit, int) else 200
    refresh_flag = _normalize_str(refresh).lower() in {"1", "true", "yes"}

    def load_audit_payload() -> dict[str, Any]:
        try:
            visible_asset_fqns = _extract_visible_asset_fqns(_visible_assets(request))
        except Exception as exc:
            detail = (
                _normalize_str(exc)
                or "Audit visibility scope could not be verified."
            )
            return {
                "visibilityError": detail,
                "visibleAssetFqns": [],
                "payload": {},
            }
        return {
            "visibleAssetFqns": visible_asset_fqns,
            "payload": atlas_metrics.audit_evidence_payload(
                store=_store_for_read(),
                audit_id=audit_id_value,
                date_range=date_range_value,
                limit=limit_value,
                visible_asset_fqns=visible_asset_fqns,
            ),
        }

    cache_key = _route_cache_key(
        "atlas_audit_evidence_payload",
        _request_scope_key(request),
        audit_id_value,
        date_range_value,
        limit_value,
    )
    if refresh_flag:
        _ttl_cache_pop(cache_key)
    # Stale-while-revalidate: serve the last good audit payload while the
    # background warm refreshes it; only first-ever loads see the loading state.
    stale_audit = None
    if not refresh_flag and _ttl_fresh_value(cache_key, 30) is None and audit_id_value is None:
        with _AUDIT_EVIDENCE_WARMING_LOCK:
            should_warm = cache_key not in _AUDIT_EVIDENCE_WARMING
            if should_warm:
                _AUDIT_EVIDENCE_WARMING.add(cache_key)

        if should_warm:
            def warm_audit_payload() -> None:
                try:
                    try:
                        _ttl_value(cache_key, 30, load_audit_payload)
                    except Exception:
                        pass
                finally:
                    with _AUDIT_EVIDENCE_WARMING_LOCK:
                        _AUDIT_EVIDENCE_WARMING.discard(cache_key)

            threading.Thread(
                target=warm_audit_payload,
                name="atlas-audit-evidence-warm",
                daemon=True,
            ).start()

        stale_audit = _ttl_stale_value(cache_key)
        if stale_audit is None:
            payload = atlas_metrics.audit_evidence_payload(
                store=None,
                audit_id=audit_id_value,
                date_range=date_range_value,
                limit=limit_value,
                visible_asset_fqns=[],
            )
            return _wrap(
                payload,
                request,
                source="governance-store+metadata-audit-log",
                state="loading",
                authoritative=False,
                entity_id=audit_id_value,
                warnings=["Audit evidence is hydrating from visible assets and the metadata audit log."],
                capabilities={
                    "requiredRole": "steward-or-admin",
                    "actorRole": actor_role,
                    "rowLevelSecurity": "visible-assets-only",
                    "actorIdentityExposure": "steward-admin-gated",
                    "visibleAssetCount": 0,
                    "hydrating": True,
                },
            )
    audit_payload = stale_audit if stale_audit is not None else _ttl_value(cache_key, 30, load_audit_payload)
    detail = (
        _normalize_str(audit_payload.get("visibilityError"))
        if isinstance(audit_payload, dict)
        else ""
    )
    if detail:
        return _error_response(
            request,
            status_code=503,
            source="governance-store+metadata-audit-log",
            detail=(
                "Audit visibility scope could not be verified; audit evidence is unavailable "
                "rather than exposing unscoped actor identities."
            ),
            state="unavailable",
            entity_id=audit_id_value,
            capabilities={
                "requiredRole": "steward-or-admin",
                "actorRole": actor_role,
                "rowLevelSecurity": "fail-closed-visible-assets",
                "actorIdentityExposure": "steward-admin-gated",
            },
            warnings=[detail],
        )
    visible_asset_fqns = (
        audit_payload.get("visibleAssetFqns")
        if isinstance(audit_payload, dict) and isinstance(audit_payload.get("visibleAssetFqns"), list)
        else []
    )
    payload = (
        audit_payload.get("payload")
        if isinstance(audit_payload, dict) and isinstance(audit_payload.get("payload"), dict)
        else {}
    )
    has_events = bool(payload.get("events"))
    return _wrap(
        payload,
        request,
        source="governance-store+metadata-audit-log",
        state="available" if has_events else "degraded",
        authoritative=has_events,
        entity_id=audit_id_value,
        warnings=None if has_events else ["No metadata audit rows were returned; audit evidence is unavailable rather than inferred."],
        capabilities={
            "requiredRole": "steward-or-admin",
            "actorRole": actor_role,
            "rowLevelSecurity": "visible-assets-only",
            "actorIdentityExposure": "steward-admin-gated",
            "visibleAssetCount": len(visible_asset_fqns),
        },
    )


def api_admin_control_center(
    request: Request,
    refresh: Optional[str] = Query(default=None),
) -> JSONResponse:
    from runtime_app import (
        _config,
        _ensure_live_runtime,
        _fast_bootstrap_inventory_summary,
        _request_cache_scope,
        _store_for_read,
        _uc,
        _uc_runtime_status_fast,
        _visible_assets,
    )

    _ensure_live_runtime()
    role = _admin_required(request)
    cfg = _config()
    target_label = _normalize_str(cfg.deploy_target) or (
        _normalize_str(cfg.environment_label).split("-", 1)[0].strip()
        if _normalize_str(cfg.environment_label)
        else ""
    )
    namespace = ".".join(part for part in [cfg.gov_catalog, cfg.gov_schema] if _normalize_str(part))
    environment_display = (
        f"{target_label} · {namespace}"
        if target_label and namespace
        else namespace
        or _normalize_str(cfg.environment_label)
        or "Workspace"
    )
    cache_key = _route_cache_key(
        "atlas_admin_control_center_payload",
        _request_scope_key(request),
        cfg.environment_label,
        cfg.gov_catalog,
        cfg.gov_schema,
    )
    refresh_flag = _normalize_str(refresh).lower() in {"1", "true", "yes"}
    if refresh_flag:
        _ttl_cache_pop(cache_key)
    def load_admin_payload() -> dict[str, Any]:
        try:
            ai_status = genie_service.provider_status(cfg)
        except Exception as exc:
            ai_status = {
                "state": "unavailable",
                "provider": "genie",
                "message": f"{error_text(exc)}",
            }
        # Jobs inventory MUST use the app-principal client: the per-request
        # OBO token frequently lacks the `jobs` scope, so the SDK pager
        # raised and the Scheduled-jobs table rendered empty even though 10+
        # real jobs exist. Jobs inventory is read-only workspace metadata —
        # the same app-principal pattern as `system_uc` reads elsewhere.
        try:
            jobs_uc = _uc()
        except Exception:
            # _databricks_job_inventory degrades None to an empty inventory.
            jobs_uc = None
        return atlas_metrics.admin_control_center_payload(
            visible_assets=_visible_assets(request),
            store=_store_for_read(),
            runtime=_uc_runtime_status_fast(background=True),
            environment={
                "label": cfg.environment_label or environment_display,
                "displayLabel": environment_display,
                "target": target_label,
                "catalog": cfg.gov_catalog,
                "schema": cfg.gov_schema,
                "warehouseId": cfg.warehouse_id,
                "workspaceHost": cfg.workspace_host,
            },
            actor_role=role,
            ai_status=ai_status,
            jobs=_databricks_job_inventory(
                jobs_uc,
                limit=12,
                include_latest_runs=True,
                workspace_host=cfg.workspace_host,
            ),
        )

    cached_entry = _ttl_fresh_value(cache_key, 45)
    # Stale-while-revalidate: serve the last good control-center payload while
    # the background warm refreshes it; only first-ever loads see loading.
    stale_admin = None
    if cached_entry is None and not refresh_flag:
        _fast_bootstrap_inventory_summary(_request_cache_scope(request), start_background=True)
        with _ADMIN_CONTROL_WARMING_LOCK:
            should_warm = cache_key not in _ADMIN_CONTROL_WARMING
            if should_warm:
                _ADMIN_CONTROL_WARMING.add(cache_key)

        if should_warm:
            def warm_admin_payload() -> None:
                try:
                    try:
                        _ttl_value(cache_key, 45, load_admin_payload)
                    except Exception:
                        pass
                finally:
                    with _ADMIN_CONTROL_WARMING_LOCK:
                        _ADMIN_CONTROL_WARMING.discard(cache_key)

            threading.Thread(
                target=warm_admin_payload,
                name="atlas-admin-control-warm",
                daemon=True,
            ).start()

        stale_admin = _ttl_stale_value(cache_key)
        if stale_admin is not None:
            return _wrap(
                stale_admin,
                request,
                source="runtime-diagnostics+governance-store",
                state="available",
                authoritative=True,
                capabilities={"refreshing": True},
            )
        try:
            ai_status = genie_service.provider_status(cfg)
        except Exception as exc:
            ai_status = {
                "state": "unavailable",
                "provider": "genie",
                "message": f"{error_text(exc)}",
            }
        payload = atlas_metrics.admin_control_center_payload(
            visible_assets=pd.DataFrame(),
            store=None,
            runtime=_uc_runtime_status_fast(background=True),
            environment={
                "label": cfg.environment_label or environment_display,
                "displayLabel": environment_display,
                "target": target_label,
                "catalog": cfg.gov_catalog,
                "schema": cfg.gov_schema,
                "warehouseId": cfg.warehouse_id,
                "workspaceHost": cfg.workspace_host,
            },
            actor_role=role,
            ai_status=ai_status,
            jobs=[],
        )
        return _wrap(
            payload,
            request,
            source="runtime-diagnostics+governance-store",
            state="loading",
            authoritative=False,
            warnings=["Control Center is hydrating visible assets, governance store, and Databricks job inventory."],
            capabilities={"hydrating": True},
        )

    payload = _ttl_value(cache_key, 45, load_admin_payload)
    return _wrap(
        payload,
        request,
        source="runtime-diagnostics+governance-store",
        state="available",
        authoritative=True,
    )


# Surface ids (nav/routes.js) -> human phrase used in the Genie prompt preamble.
_AI_SURFACE_LABELS = {
    "home": "the executive Command Center",
    "discovery": "the Discovery search surface",
    "stewardship": "the Stewardship queue",
    "glossary": "the Glossary / CDE registry",
    "lineage": "the Lineage workspace",
    "evidence": "the Audit Evidence surface",
    "admin": "the Admin control center",
    "assets": "an asset detail page",
}


def _ai_context_preamble(context: "AtlasAiContext | None") -> str:
    """Build a grounding preamble so Genie resolves 'this asset'/'this page'.

    The preamble names the concrete surface and asset FQN the user is viewing so
    deictic questions ("who owns this asset?", "what feeds this table?") bind to
    a real entity instead of being answered blind. Empty context yields "".
    """

    if context is None:
        return ""
    surface = _normalize_str(getattr(context, "surface", ""))
    asset_fqn = _normalize_str(getattr(context, "assetFqn", ""))
    parts: list[str] = []
    if asset_fqn:
        parts.append(
            f"The user is currently viewing the asset `{asset_fqn}`. Interpret "
            f"'this asset', 'this table', 'this dataset', 'it', and 'here' as `{asset_fqn}`."
        )
    if surface:
        label = _AI_SURFACE_LABELS.get(surface.lower(), f"the {surface} surface")
        parts.append(f"The user is on {label}.")
    scope_line = _scope_summary(getattr(context, "scope", None))
    if scope_line:
        parts.append(
            f"They are filtering the view to {scope_line}. Interpret 'here', 'this page', "
            "'these assets', and 'the current view' as that filtered scope."
        )
    if not parts:
        return ""
    return "Context: " + " ".join(parts) + "\n\n"


_SCOPE_LABELS = {
    "domain": "domain", "criticality": "criticality", "tier": "tier",
    "certification": "certification", "sensitivity": "sensitivity",
    "view": "saved view", "owner": "owner", "query": "search",
}


def _scope_summary(scope) -> str:
    """Human-readable one-liner for the active facet scope (or "")."""
    if not isinstance(scope, Mapping):
        return ""
    pieces: list[str] = []
    for key, label in _SCOPE_LABELS.items():
        value = scope.get(key)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            joined = ", ".join(_normalize_str(item) for item in value if _normalize_str(item))
            if joined:
                pieces.append(f"{label} {joined}")
        else:
            text = _normalize_str(value)
            if text:
                if key == "owner" and text == "__unassigned__":
                    text = "unassigned"
                pieces.append(f"{label} {text}")
    return "; ".join(pieces)


def _scope_domain(scope) -> str:
    """The single domain the user is filtered to, if exactly one — else ""."""
    if not isinstance(scope, Mapping):
        return ""
    value = scope.get("domain")
    if isinstance(value, (list, tuple)):
        domains = [_normalize_str(item) for item in value if _normalize_str(item)]
        return domains[0] if len(domains) == 1 else ""
    text = _normalize_str(value)
    return text


# Canonical estate-metric grounding. The Genie curated view is a single-catalog
# snapshot that drifts from the UI (48/31/35 vs canonical 50/44/49). For these
# estate-level aggregate questions we ground the answer on the SAME numbers the
# Command Center tiles show, so Atlas AI can never contradict the UI.
_ESTATE_METRIC_RULES = (
    # (metric_key, singular_noun, plural_noun, [required_all], [any_of], [none_of])
    ("cdeCount", "critical data element", "critical data elements",
     [], ["cde", "critical data element"], []),
    ("openRequests", "open governance request", "open governance requests",
     ["open"], ["request", "governance request", "change request"], []),
    ("certifiedAssets", "certified asset", "certified assets",
     ["certif"], ["asset", "table", "dataset", "have", "many"], []),
    ("criticalAssets", "business-critical asset", "business-critical assets",
     ["critical"], ["asset", "table", "dataset"], ["cde", "data element"]),
    ("metadataCoverage", "metadata coverage", "metadata coverage",
     [], ["coverage", "documented", "metadata complete"], []),
    ("totalAssets", "asset", "assets",
     [], ["how many asset", "total asset", "data estate", "assets do we", "number of asset", "assets in our"], ["certif", "critical", "cde"]),
)


def _detect_estate_metric(question: str) -> tuple[str, str, str] | None:
    text = _normalize_str(question).lower()
    if not text:
        return None
    # Aggregate intent only — never override per-asset or list questions.
    if not any(token in text for token in ("how many", "how much", "number of", "count", "total", "percentage", "do we have", "are there", "what are our")):
        return None
    for metric_key, singular, plural, required_all, any_of, none_of in _ESTATE_METRIC_RULES:
        if none_of and any(token in text for token in none_of):
            continue
        if required_all and not all(token in text for token in required_all):
            continue
        if any_of and not any(token in text for token in any_of):
            continue
        return metric_key, singular, plural
    return None


def _canonical_estate_grounding(
    question: str,
    request: Request,
    payload: dict,
    *,
    visible_assets_fn,
    store_fn,
) -> dict | None:
    """Return a canonical-grounded answer dict when the question is an estate count.

    Computes the metric from the same visible-asset frame + governance store the
    Command Center uses, replaces the answer's number with the canonical one, and
    warns when the Genie snapshot diverged. Returns None when not applicable.
    """

    detected = _detect_estate_metric(question)
    if not detected:
        return None
    metric_key, singular, plural = detected
    try:
        visible_assets = visible_assets_fn(request)
    except Exception:
        return None
    if visible_assets is None or getattr(visible_assets, "empty", True):
        return None
    # Fix #1: estate metrics are ESTATE-WIDE. If the question is scoped to a
    # subset this metric can't compute — a specific domain, or an
    # owner-gap qualifier — returning the global number as "canonical" is a
    # confidently-wrong answer (e.g. "how many Finance assets have no owner?"
    # used to return the total estate count 50). Decline so the ownership
    # grounding or Genie handles it honestly instead.
    qlower = _normalize_str(question).lower()
    if _mentions_owner_gap(qlower):
        return None
    if any(noun in qlower for noun in _FACET_SCOPE_NOUNS):
        return None
    try:
        # A named domain/tier/sensitivity VALUE also scopes the question (e.g.
        # "how many Finance assets", "how many Confidential assets"). Criticality
        # and certification values are excluded — those ARE the concepts the
        # criticalAssets / certifiedAssets metrics represent.
        if _find_domain_in_text(qlower, atlas_metrics.known_scope_values(visible_assets)):
            return None
    except Exception:
        pass
    try:
        store = store_fn(request)
    except Exception:
        store = None
    try:
        metrics = atlas_metrics.canonical_estate_metrics(visible_assets=visible_assets, store=store)
    except Exception:
        return None
    canonical_value = metrics.get(metric_key)
    if canonical_value is None:
        return None
    if metric_key == "metadataCoverage":
        answer = (
            f"Metadata coverage across the estate is **{canonical_value}%** — the same "
            "canonical figure shown on the Command Center. Coverage weights owners, "
            "certification, domain, description, and classification, so it is not a "
            "simple has-a-comment check."
        )
    elif metric_key == "openRequests":
        noun = singular if canonical_value == 1 else plural
        answer = (
            f"You have **{canonical_value} {noun}** open across the estate. "
            "This is the same count shown on the Command Center and Stewardship queue."
        )
    else:
        noun = singular if canonical_value == 1 else plural
        answer = (
            f"There are **{canonical_value:,} {noun}** in the current estate — the same "
            "canonical figure shown on the Command Center tiles."
        )
    canonical_evidence = {
        "type": "metric",
        "id": metric_key,
        "label": f"{canonical_value} {plural}",
        "metric": metric_key,
        "value": canonical_value,
        "source": "unity-catalog-inventory+governance-store (canonical semantics)",
    }
    warnings: list[str] = []
    # Detect divergence from the Genie snapshot to surface honestly.
    genie_number = _first_evidence_number(payload.get("evidence"))
    if genie_number is not None and genie_number != canonical_value:
        warnings.append(
            f"The Genie metadata snapshot reported {genie_number}; Atlas AI grounded the answer on the "
            f"canonical estate figure ({canonical_value}) so it matches the UI."
        )
    return {"answer": answer, "evidence": canonical_evidence, "warnings": warnings}


# --- Ownership grounding -----------------------------------------------------
# Ownership questions ("who owns this?", "which domain has the most assets
# without an owner?", "how many Finance assets have no owner?") are NOT estate
# aggregates and were previously answered by the drifting Genie curated view —
# which contradicted the Command Center (Genie said Customer/10; the dashboard
# says Finance/17) and the asset page (Genie said "no owner" for an asset whose
# UC owner is shown on screen). These ground on the SAME inventory + predicate
# the dashboard uses, so the AI agrees with the rest of the app.

# Owner/steward terms and gap indicators. A question is an "owner-gap" question
# when it names an owner/steward AND a gap indicator — this is broader and more
# robust than an explicit phrase list (which missed "missing a steward", "need a
# steward", "don't have a business owner", … and let those fall through to the
# WRONG global estate count).
_OWNER_TERMS = ("owner", "owns", "owned", "ownership", "steward", "stewardship", "stewarded")
_GAP_INDICATORS = (
    "without", "missing", "lack", "lacking", "unowned", "ownerless", "unassigned",
    "no owner", "no assigned owner", "no steward", "no business owner", "no governance owner",
    "have no", "has no", "with no", "need an", "needs an", "need a", "needs a",
    "need owner", "needs owner", "need owners", "don't have", "do not have", "does not have",
    "assign an owner", "assign owners",
    # Negation phrasings ("how many assets are NOT owned?", "aren't assigned an
    # owner"). Combined with an owner/steward term in _mentions_owner_gap, so
    # these don't over-trigger on unrelated negations. Without them these
    # slipped both gates and returned the global estate total (review F1).
    "not owned", "not assigned", "not have an owner", "not have a steward",
    "aren't owned", "arent owned", "aren't assigned", "arent assigned",
    "isn't owned", "isnt owned", "isn't assigned", "isnt assigned",
    "no one owns", "no-one owns", "nobody owns", "not stewarded", "not been assigned",
)
_OWNER_INTENT_TOKENS = ("owner", "owns", "owned", "ownership", "steward", "stewardship")
_PER_ASSET_OWNER_PHRASES = (
    "who owns", "who is the owner", "who are the owners", "who's the owner",
    "owner of", "owned by", "does this asset have an owner", "is this owned",
    "who stewards", "who is the steward", "ownership of",
)
_SUPERLATIVE_MOST = ("most", "highest", "greatest", "largest", "top", "worst")
_SUPERLATIVE_LEAST = ("fewest", "least", "lowest", "smallest", "best")
_AGGREGATE_TOKENS = ("how many", "how much", "number of", "count", "total", "are there", "do we have")
# Facet nouns that scope a question to a subset no estate metric can compute.
# Their presence makes estate-count grounding decline (so it never answers a
# subset question with the estate-wide number).
_FACET_SCOPE_NOUNS = (
    "domain", "tier", "catalog", "schema", "sensitivity", "classification",
    "data product", "dataproduct", "sensitive", "pii", "gdpr", "phi",
    "personally identifiable",
)
# Collection/plural signals that mean a question is NOT about one focused asset
# (so per-asset ownership grounding must not hijack it to the current page).
_COLLECTION_TOKENS = (
    "which ", "most ", "least ", "fewest", "all ", "every ", "list ", "each ",
    "tables", "assets", "datasets", "domains", "these", "them", "top ",
)
_FQN_RE = re.compile(r"\b([A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+)\b")


def _mentions_owner_gap(text: str) -> bool:
    if not any(term in text for term in _OWNER_TERMS):
        return False
    return any(indicator in text for indicator in _GAP_INDICATORS)


def _find_domain_in_text(text: str, domains) -> str:
    """Return the original-cased domain whose name appears as a word in text."""
    for domain in domains:
        name = _normalize_str(domain)
        if not name:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(name.lower())}(?![A-Za-z0-9])", text):
            return domain
    return ""


def _extract_question_fqn(question: str) -> str:
    match = _FQN_RE.search(_normalize_str(question))
    return match.group(1) if match else ""


def _asset_ownership_answer(own: dict) -> dict:
    fqn = own.get("fqn") or "this asset"
    if not own.get("found"):
        return {
            "answer": (
                f"`{fqn}` is not in your visible asset inventory, so its ownership is "
                "unavailable. It may be outside your permission scope or not yet inventoried."
            ),
            "evidence": {
                "type": "asset", "id": fqn, "label": fqn,
                "source": "unity-catalog-inventory+governance-store (canonical semantics)",
            },
            "warnings": [],
        }
    uc = _normalize_str(own.get("ucOwner"))
    business = [p for p in (own.get("businessOwners") or []) if _normalize_str(p)]
    stewards = [p for p in (own.get("stewards") or []) if _normalize_str(p)]
    technical = [p for p in (own.get("technicalOwners") or []) if _normalize_str(p)]
    sentences: list[str] = []
    if uc:
        sentences.append(f"In Unity Catalog, `{fqn}` is owned by **{uc}**.")
    if business:
        label = "business owner" if len(business) == 1 else "business owners"
        sentences.append(f"Its {label} {'is' if len(business) == 1 else 'are'} {', '.join(business)}.")
    if stewards:
        label = "steward" if len(stewards) == 1 else "stewards"
        sentences.append(f"Its {label} {'is' if len(stewards) == 1 else 'are'} {', '.join(stewards)}.")
    if technical:
        label = "technical owner" if len(technical) == 1 else "technical owners"
        sentences.append(f"Its {label} {'is' if len(technical) == 1 else 'are'} {', '.join(technical)}.")
    # "Governance owner" is business owner OR steward OR technical owner — the
    # SAME predicate the Command Center's ownerless count uses. Only claim "no
    # owner" when ALL of them are absent, or the AI contradicts the dashboard
    # (which counts a technical-owner-only asset as owned).
    if not business and not stewards and not technical:
        if uc:
            sentences.append(
                "It has no assigned governance owner (business owner, steward, or technical owner), "
                "so it still needs one even though it has a Unity Catalog owner."
            )
        else:
            sentences.append(
                f"No owner is recorded for `{fqn}` — neither a Unity Catalog owner nor a governance "
                "owner (business owner, steward, or technical owner). It needs an owner assigned."
            )
    return {
        "answer": " ".join(sentences),
        "evidence": {
            "type": "asset", "id": fqn, "label": fqn,
            "source": "unity-catalog-inventory+governance-store (canonical semantics)",
        },
        "warnings": [],
    }


def _ownership_gap_evidence(value: int) -> dict:
    return {
        "type": "metric", "id": "assetsWithoutOwner", "metric": "assetsWithoutOwner",
        "value": value, "label": f"{value} assets without an owner",
        "source": "unity-catalog-inventory+governance-store (canonical semantics)",
    }


def _has_nonowner_facet_qualifier(text: str) -> bool:
    """True when the question carries a certification/criticality/tier/
    sensitivity/CDE qualifier beyond owner+domain — i.e. a compound question the
    ownerless-count branches would answer while silently dropping that facet."""
    if "certif" in text:  # certified / uncertified / certification
        return True
    if "critical data element" in text or _value_in_text(text, "cde"):
        return True
    if _value_in_text(text, "critical"):
        return True
    return any(w in text for w in ("tier", "sensitivity", "classification", "classified", "pii", "confidential"))


def _ownership_grounding(question: str, request, ai_context, *, visible_assets_fn) -> dict | None:
    text = _normalize_str(question).lower()
    if not text or not any(token in text for token in _OWNER_INTENT_TOKENS):
        return None
    try:
        visible = visible_assets_fn(request)
    except Exception:
        return None
    if visible is None or getattr(visible, "empty", True):
        return None

    gap = _mentions_owner_gap(text)
    # A compound owner+facet question ("how many CERTIFIED assets without an
    # owner in Finance?") can't be answered by the ownerless-count branches
    # without ignoring the facet (→ over-count). `compound_facet` suppresses the
    # gap branches (B/C/D) so it declines to Genie instead of answering wrong
    # (review F4). Per-asset ownership (branch A) is unaffected.
    compound_facet = _has_nonowner_facet_qualifier(text)
    mentions_domain_word = "domain" in text
    superlative_most = any(w in text for w in _SUPERLATIVE_MOST)
    superlative_least = any(w in text for w in _SUPERLATIVE_LEAST)
    superlative = superlative_most or superlative_least
    domains = atlas_metrics.known_domains(visible)
    named_domain = _find_domain_in_text(text, domains)
    # "here"/"this page"/"these" → the domain the user is filtered to (context
    # scope), so page-aware ownership questions resolve without naming a domain.
    if not named_domain and any(p in text for p in ("here", "this page", "these", "current view", "on this page")):
        scope_domain = _scope_domain(getattr(ai_context, "scope", None))
        if scope_domain and scope_domain.lower() in {d.lower() for d in domains}:
            named_domain = next(d for d in domains if d.lower() == scope_domain.lower())

    # (B) Superlative across domains: "which domain has the most/fewest assets
    #     without an owner?"
    if mentions_domain_word and superlative and not compound_facet and (gap or "owner" in text or "steward" in text):
        metrics = atlas_metrics.ownership_gap_metrics(visible_assets=visible)
        candidates = [
            (name, vals["ownerless"], vals["total"])
            for name, vals in metrics["byDomain"].items()
            if vals["ownerless"] > 0
        ]
        if not candidates:
            return {
                "answer": "Every domain in the visible estate has assigned owners — no domain has assets without an owner.",
                "evidence": _ownership_gap_evidence(0), "warnings": [],
            }
        # Tie-break MUST match the Command Center's stewardship ranking
        # (-count, then name ascending), or the AI names a different top domain
        # than the dashboard's top stewardship card on a tie.
        if superlative_least:
            ordered = sorted(candidates, key=lambda item: (item[1], item[0].lower()))
            lead_word = "fewest (but non-zero)"
        else:
            ordered = sorted(candidates, key=lambda item: (-item[1], item[0].lower()))
            lead_word = "most"
        pick = ordered[0]
        rest = ordered[1:3]
        answer = (
            f"The **{pick[0]}** domain has the {lead_word} assets without an assigned owner — "
            f"**{pick[1]}** of its {pick[2]} visible assets."
        )
        if rest:
            answer += " Next: " + ", ".join(f"{name} ({owner_gap})" for name, owner_gap, _total in rest) + "."
        answer += " Owner here means a business owner, steward, or technical owner, matching the Command Center."
        return {"answer": answer, "evidence": _ownership_gap_evidence(pick[1]), "warnings": []}

    # (C) Domain-scoped ownerless count: "how many Finance assets have no owner?"
    if named_domain and not compound_facet and (gap or ("owner" in text and any(a in text for a in _AGGREGATE_TOKENS))):
        metrics = atlas_metrics.ownership_gap_metrics(visible_assets=visible)
        bucket = metrics["byDomain"].get(named_domain, {"total": 0, "ownerless": 0})
        if bucket["ownerless"] == 0:
            answer = (
                f"All {bucket['total']} visible assets in the **{named_domain}** domain have an assigned owner."
            )
        else:
            answer = (
                f"**{bucket['ownerless']}** of the **{bucket['total']}** visible assets in the "
                f"**{named_domain}** domain have no assigned owner (business owner, steward, or technical "
                "owner). This matches the Command Center stewardship recommendation."
            )
        return {"answer": answer, "evidence": _ownership_gap_evidence(bucket["ownerless"]), "warnings": []}

    # (D) Global ownerless count: "how many assets have no owner?"
    if gap and not compound_facet and any(a in text for a in _AGGREGATE_TOKENS):
        metrics = atlas_metrics.ownership_gap_metrics(visible_assets=visible)
        total_gap = metrics["totalOwnerless"]
        answer = (
            f"**{total_gap}** of the **{metrics['totalAssets']}** visible assets have no assigned owner "
            "(business owner, steward, or technical owner). Assets can still have a Unity Catalog owner "
            "while needing a governance owner assigned."
        )
        return {"answer": answer, "evidence": _ownership_gap_evidence(total_gap), "warnings": []}

    # (A) Per-asset ownership: "who owns this asset / who owns <fqn>?"
    # A collection/superlative/plural question ("who owns our most critical
    # tables?", "which assets have no owner?") is NOT about the current page,
    # even when an asset FQN is in context — don't answer it about that one asset.
    asset_fqn = _normalize_str(getattr(ai_context, "assetFqn", "")) if ai_context else ""
    question_fqn = _extract_question_fqn(question)
    is_collection = superlative or mentions_domain_word or any(tok in text for tok in _COLLECTION_TOKENS)
    # A specific FQN written in the question always wins (it names one asset);
    # otherwise the context asset only answers a clearly-singular question.
    if question_fqn:
        target_fqn = question_fqn
    elif is_collection:
        target_fqn = ""
    else:
        target_fqn = asset_fqn
    per_asset = any(p in text for p in _PER_ASSET_OWNER_PHRASES) or (
        target_fqn and ("this asset" in text or "this table" in text or "this dataset" in text)
    )
    if target_fqn and per_asset:
        own = atlas_metrics.asset_ownership(visible_assets=visible, fqn=target_fqn)
        return _asset_ownership_answer(own)
    return None


# --- Scoped-count grounding ---------------------------------------------------
# Facet-scoped count questions ("how many certified assets in Finance?", "how
# many PII assets?", "how many assets in the Tier 1 tier?") are NOT estate-wide
# aggregates, so estate grounding declines them and they used to drift through
# Genie. This computes them from the same inventory + predicates the dashboard
# uses. It fires only when a real domain/tier/sensitivity VALUE is named (the
# subset dimensions estate can't express), and the answer states exactly which
# filters it applied so the number is never a mislabelled global count.
_UNCERTIFIED_PHRASES = (
    "uncertified", "un-certified", "not certified", "not yet certified",
    "without certification", "aren't certified", "arent certified",
    "isn't certified", "isnt certified", "lacking certification", "no certification",
    "not been certified", "decertified", "de-certified", "pending certification",
    "awaiting certification", "need certification", "needs certification",
    "needing certification", "require certification", "requires certification",
    "requiring certification", "recertification", "re-certification", "needs to be certified",
)


# Classification concepts users ask about that may NOT exist as a literal
# sensitivity value in a given estate (which might tag Confidential/Restricted).
_CLASSIFICATION_TOKENS = ("pii", "gdpr", "phi", "personally identifiable", "sensitive", "classified")


def _value_in_text(text: str, value: str) -> bool:
    name = _normalize_str(value)
    if not name:
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(name.lower())}(?![A-Za-z0-9])", text))


def _scoped_count_grounding(question: str, request, ai_context, *, visible_assets_fn) -> dict | None:
    text = _normalize_str(question).lower()
    if not any(a in text for a in _AGGREGATE_TOKENS):
        return None
    # Owner-gap counts belong to ownership grounding (which runs first); don't
    # answer them here with a non-owner scope.
    if _mentions_owner_gap(text):
        return None
    try:
        visible = visible_assets_fn(request)
    except Exception:
        return None
    if visible is None or getattr(visible, "empty", True):
        return None
    facets = atlas_metrics.known_facet_values(visible)
    domains = [d for d in facets["domains"] if _value_in_text(text, d)]
    tiers = [t for t in facets["tiers"] if _value_in_text(text, t)]
    sensitivities = [s for s in facets["sensitivities"] if _value_in_text(text, s)]
    # A classification qualifier we can't map to a real sensitivity value in this
    # estate (e.g. "PII" when the estate tags Confidential/Restricted) must NOT be
    # silently dropped from the count — decline so Genie answers it honestly,
    # rather than returning "N Finance assets" (ignoring PII) or the estate total.
    if not sensitivities and any(t in text for t in _CLASSIFICATION_TOKENS):
        return None
    # Trigger only on a real subset scope estate metrics can't express.
    if not (domains or tiers or sensitivities):
        return None
    cde = _value_in_text(text, "cde") or ("critical data element" in text)
    certified: bool | None = None
    # Check the negation/pending phrasings FIRST; only then the positive. The
    # word-boundary match for "certified" won't fire on "uncertified"/
    # "decertified" (preceded by letters), so an uncertified question can never
    # fall through to the certified count (review F1).
    if any(p in text for p in _UNCERTIFIED_PHRASES):
        certified = False
    elif _value_in_text(text, "certified"):
        certified = True
    critical: bool | None = None
    # Word-boundary so "criticality"/"critically" don't set the is_critical
    # filter on unrelated questions (review F3).
    if not cde and (_value_in_text(text, "critical") or "business critical" in text or "business-critical" in text):
        critical = True
    matched = atlas_metrics.scoped_asset_count(
        visible_assets=visible, domains=domains, tiers=tiers, sensitivities=sensitivities,
        certified=certified, critical=critical, cde=cde or None,
    )
    adjectives: list[str] = []
    if certified is True:
        adjectives.append("certified")
    if certified is False:
        adjectives.append("uncertified")
    if critical:
        adjectives.append("business-critical")
    if cde:
        adjectives.append("CDE")
    adjectives.extend(sensitivities)  # e.g. PII / Confidential as a classifier
    noun = (" ".join(adjectives) + " assets") if adjectives else "assets"
    scopes: list[str] = []
    if domains:
        scopes.append(f"the {', '.join(domains)} domain{'s' if len(domains) > 1 else ''}")
    if tiers:
        scopes.append(f"the {', '.join(tiers)} tier{'s' if len(tiers) > 1 else ''}")
    scope_str = (" in " + " and ".join(scopes)) if scopes else ""
    answer = (
        f"There are **{matched:,}** {noun}{scope_str}, computed from the same canonical "
        "inventory the Command Center uses."
    )
    return {
        "answer": answer,
        "evidence": {
            "type": "metric", "id": "scopedAssetCount", "metric": "scopedAssetCount",
            "value": matched, "label": f"{matched} {noun}{scope_str}".strip(),
            "source": "unity-catalog-inventory+governance-store (canonical semantics)",
        },
        "warnings": [],
    }


# Direction detection is phrase-based, not bare-token: "what feeds X" is
# upstream but "what does X feed" / "X feeds into" is DOWNSTREAM. The bare
# "feed" token used to classify both as upstream, so "what does this feed?"
# returned the sources instead of the consumers (verifier BLOCK).
_LINEAGE_Q_DOWN = (
    "downstream", "feeds into", "feed into", "does this feed", "does it feed",
    "what does this feed", "what does it feed", "consume", "consumer", "consumed by",
    "uses this", "used by", "depend on this", "depends on this", "affected by",
    "who uses", "what uses", "impact of", "impacted",
)
_LINEAGE_Q_UP = (
    "what feeds", "feeds this", "feeding this", "upstream", "source of", "sources for",
    "sources of", "come from", "comes from", "derived from", "depends on", "depend on",
    "built from", "populate", "fed by", "feed this",
)


def _lineage_grounding(question: str, context_fqn: str, uc: Any) -> dict | None:
    """Answer 'what feeds / what depends on <asset>' from REAL Unity Catalog
    lineage, not the Genie snapshot (which has no lineage and answered
    "nothing feeds it" while the lineage UI rendered upstream sources —
    verifier BLOCK). Only fires with an asset context and a lineage-shaped
    question; returns None otherwise so estate/other questions are untouched.
    """
    text = _normalize_str(question).lower()
    fqn = _normalize_str(context_fqn)
    if not fqn or fqn.count(".") < 2:
        return None
    # Downstream wins ties: "what does this feed into and depend on" reads as
    # a downstream-impact question. Bare "feed"/"feeds" with no directional
    # phrase defaults to upstream ("what feeds X" is the common ask).
    wants_down = any(tok in text for tok in _LINEAGE_Q_DOWN)
    wants_up = any(tok in text for tok in _LINEAGE_Q_UP)
    if not wants_up and not wants_down and ("feed" in text or "feeds" in text):
        wants_up = True  # bare mention → upstream default
    if not (wants_up or wants_down):
        return None
    # A pure downstream question must NOT also fetch upstream.
    if wants_down and not any(tok in text for tok in _LINEAGE_Q_UP):
        wants_up = False
    catalog, schema, table = fqn.split(".", 2)
    # Read as the requesting user only: an app-SP fallback would reveal lineage
    # neighbours the user cannot see. Track whether the read SUCCEEDED so we never assert
    # "no lineage" off a permission failure — that would contradict the graph.
    read_ok = False
    up = down = None
    for client in [c for c in uc if c is not None] if isinstance(uc, (list, tuple)) else [uc]:
        try:
            if wants_up or not wants_down:
                up = client.get_table_lineage_upstream(catalog, schema, table, limit=50)
            if wants_down:
                down = client.get_table_lineage_downstream(catalog, schema, table, limit=50)
            read_ok = True
            if (up is not None and not up.empty) or (down is not None and not down.empty):
                break  # got real neighbors; stop
        except Exception:
            continue
    if not read_ok:
        # Couldn't read lineage — deflect honestly instead of letting Genie
        # claim "nothing feeds it" (verifier BLOCK). Never a false negative.
        return {
            "answer": (f"I couldn't read the governed lineage for **{table}** just now. "
                       f"Open it in **Lineage Atlas** to see its upstream sources and downstream consumers."),
            "evidence": [], "warnings": [],
        }
    up_names = sorted({str(v) for v in (up["source_table_full_name"].tolist() if up is not None and not up.empty else [])})
    down_names = sorted({str(v) for v in (down["target_table_full_name"].tolist() if down is not None and not down.empty else [])})

    def _sentence(direction, names):
        short = table
        if not names:
            return (f"Unity Catalog shows no {direction} lineage for **{short}** — no observed "
                    f"table-lineage edges in that direction.")
        head = ", ".join(f"`{n}`" for n in names[:8])
        more = f" and {len(names) - 8} more" if len(names) > 8 else ""
        verb = "feed into" if direction == "upstream" else "are fed by"
        return f"**{len(names)}** {direction} asset{'s' if len(names)!=1 else ''} {verb} **{short}**: {head}{more}."

    parts = []
    evidence = []
    if wants_up or not wants_down:
        parts.append(_sentence("upstream", up_names))
        evidence += [{"id": n, "label": n, "assetFqn": n, "source": "system.access.table_lineage"} for n in up_names[:8]]
    if wants_down:
        parts.append(_sentence("downstream", down_names))
        evidence += [{"id": n, "label": n, "assetFqn": n, "source": "system.access.table_lineage"} for n in down_names[:8]]
    answer = " ".join(parts) + " Open the asset in Lineage Atlas to explore the full graph."
    return {"answer": answer, "evidence": evidence, "warnings": []}


def _first_evidence_number(evidence: Any) -> int | None:
    if not isinstance(evidence, list):
        return None
    for item in evidence:
        rows = item.get("resultRows") if isinstance(item, Mapping) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            for value in row.values():
                try:
                    text = str(value).strip().replace(",", "")
                    if text and text.replace(".", "", 1).isdigit():
                        return int(float(text))
                except Exception:
                    continue
    return None


def _finalize_genie_payload(raw_payload, *, question, request, ai_context, genie_status) -> JSONResponse:
    """Post-process a completed Genie payload — canonical/lineage grounding
    override, clickable recommendations from SQL rows — and wrap it. Shared by
    the instant cache-hit path and the poll-complete path so a streamed answer
    is identical to a blocking one."""
    from runtime_app import _store, _uc, _uc_for_request, _visible_assets

    payload = dict(raw_payload or {})
    payload["question"] = question
    payload_warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    lineage_ground = None
    _ctx_fqn = _normalize_str(getattr(ai_context, "assetFqn", "")) if ai_context else ""
    if _ctx_fqn:
        try:
            lineage_ground = _lineage_grounding(question, _ctx_fqn, [_uc_for_request(request)])
        except Exception:
            lineage_ground = None
    grounding = lineage_ground or _canonical_estate_grounding(
        question, request, payload, visible_assets_fn=_visible_assets, store_fn=lambda _req=None: _store()
    )
    if grounding:
        payload["answer"] = grounding["answer"]
        existing_evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        payload["evidence"] = [grounding["evidence"], *existing_evidence]
        payload["confidence"] = "canonical-grounded"
        payload_warnings = [*payload_warnings, *grounding["warnings"]]
    has_evidence = bool(payload.get("evidence"))
    if not payload.get("recommendations") and has_evidence:
        recommendations = _recommendations_from_genie_evidence(payload.get("evidence") or [])
        if recommendations:
            payload = {
                **payload,
                "recommendations": recommendations,
                "suggestedActions": [
                    action
                    for recommendation in recommendations
                    for action in recommendation.get("suggestedActions", [])
                ][:4],
            }
    if not payload.get("recommendations"):
        payload_warnings = [
            *payload_warnings,
            "Genie returned no evidence-backed recommendations; local governance-store recommendations were not substituted.",
        ]
    return _wrap(
        payload,
        request,
        source="databricks-genie",
        state="available" if has_evidence else "degraded",
        authoritative=has_evidence,
        capabilities={
            "provider": "genie",
            "spaceId": genie_status.get("spaceId", ""),
            "benchmarkState": genie_status.get("benchmarkState", ""),
            "sampleValuesIncluded": False,
            "piiValuesIncluded": False,
        },
        warnings=payload_warnings or None,
    )


def _genie_cache_key(genie_status: dict, forwarded_token: str, genie_question: str) -> str:
    token_fragment = hashlib.sha256(forwarded_token.encode("utf-8")).hexdigest()[:12]
    return _route_cache_key(
        "atlas_ai_recommendations", genie_status.get("spaceId", ""), token_fragment,
        genie_question or "__default__",
    )


def api_atlas_ai_recommendations(
    request: Request,
    body: AtlasAiQuestion | None = Body(default=None),
) -> JSONResponse:
    from runtime_app import _config, _ensure_live_runtime, _request_obo_token, _store, _store_for_read, _uc, _uc_for_request, _visible_assets

    _ensure_live_runtime()
    question = _normalize_str(body.question if body else "")
    ai_context = getattr(body, "context", None) if body else None

    # Authoritative local grounding runs BEFORE (and independent of) Genie:
    # estate counts and lineage come from the same canonical data the UI
    # renders, so the AI must answer them correctly even when Genie is
    # degraded/unavailable (previously these were trapped inside the
    # Genie-available branch and returned an empty answer — verifier BLOCK).
    _early_ctx_fqn = _normalize_str(getattr(ai_context, "assetFqn", "")) if ai_context else ""
    _early_ground = None
    if _early_ctx_fqn:
        try:
            _early_ground = _lineage_grounding(question, _early_ctx_fqn, [_uc_for_request(request)])
        except Exception:
            _early_ground = None
    # Ownership grounding (per-asset owner, domain ownerless counts, superlatives)
    # runs before estate grounding so "who owns this?" / "which domain has the
    # most assets without an owner?" agree with the dashboard instead of drifting
    # through Genie.
    if _early_ground is None:
        try:
            _early_ground = _ownership_grounding(
                question, request, ai_context, visible_assets_fn=_visible_assets,
            )
        except Exception:
            _early_ground = None
    # Facet-scoped counts ("how many certified assets in Finance?") — computed
    # from canonical inventory, before estate grounding declines them to Genie.
    if _early_ground is None:
        try:
            _early_ground = _scoped_count_grounding(
                question, request, ai_context, visible_assets_fn=_visible_assets,
            )
        except Exception:
            _early_ground = None
    if _early_ground is None:
        try:
            _early_ground = _canonical_estate_grounding(
                question, request, {}, visible_assets_fn=_visible_assets,
                store_fn=lambda _req=None: _store(),
            )
        except Exception:
            _early_ground = None
    if _early_ground:
        _ev = _early_ground.get("evidence")
        _ev_list = _ev if isinstance(_ev, list) else ([_ev] if _ev else [])
        return _wrap(
            {
                "question": question,
                "intent": "governed-grounding",
                "answer": _early_ground["answer"],
                "evidence": _ev_list,
                "recommendations": [],
                "suggestedActions": [],
                "confidence": "canonical-grounded",
                "warnings": _early_ground.get("warnings", []),
            },
            request,
            source="unity-catalog+governance-store (canonical)",
            state="available",
            authoritative=True,
            capabilities={"provider": "canonical-grounding"},
        )

    genie_warning = ""
    genie_status: dict = {"state": "degraded", "provider": "local"}
    try:
        cfg = _config()
        genie_status = genie_service.provider_status(cfg)
        if genie_status.get("provider") == "genie" and genie_status.get("state") == "available":
            forwarded_token = _request_obo_token(request)
            if not forwarded_token:
                genie_warning = (
                    "Genie-backed Atlas AI requires the forwarded Databricks user token; "
                    "recommendations are unavailable for this actor until OBO is available."
                )
                metadata_payload = _live_metadata_atlas_ai_payload(
                    question,
                    request,
                    genie_status=genie_status,
                    warnings=[
                        genie_warning,
                        (
                            "Atlas AI response is backed by workspace-scoped Unity Catalog and Governance Atlas "
                            "metadata only; it is not a Databricks Genie/OBO answer."
                        ),
                    ],
                )
                if metadata_payload:
                    return _wrap(
                        metadata_payload,
                        request,
                        source="unity-catalog-inventory+governance-store+databricks-genie-status",
                        state="degraded",
                        authoritative=False,
                        capabilities={
                            "provider": "governance-atlas-live-metadata",
                            "genie": genie_status,
                            "evidenceBacked": True,
                            "sampleValuesIncluded": False,
                            "piiValuesIncluded": False,
                        },
                        warnings=metadata_payload.get("warnings") or None,
                    )
            else:
                context_preamble = _ai_context_preamble(ai_context)
                genie_question = f"{context_preamble}{question}" if context_preamble else question
                genie_cache_key = _genie_cache_key(genie_status, forwarded_token, genie_question)
                # Instant repeat: a finalized answer is still cached → return it
                # directly, no round-trip through Genie or the poll loop.
                cached_final = _ttl_fresh_value(genie_cache_key, 120)
                if isinstance(cached_final, dict):
                    return _finalize_genie_payload(
                        cached_final, question=question, request=request,
                        ai_context=ai_context, genie_status=genie_status,
                    )
                # Otherwise start the Genie conversation WITHOUT blocking and
                # return a "pending" envelope with the ids + initial stage. The
                # frontend polls POST /atlas-ai/message for real progress stages
                # and the final answer, instead of hanging on one long request.
                started = genie_service.start_genie(
                    config=cfg, question=genie_question, user_access_token=forwarded_token,
                )
                return _wrap(
                    {
                        "question": question,
                        "intent": "genie-pending",
                        "answer": "",
                        "recommendations": [],
                        "evidence": [],
                        "confidence": "pending",
                        "provider": "genie",
                        "providerState": genie_status,
                        "conversationId": started["conversationId"],
                        "messageId": started["messageId"],
                        "status": started["status"],
                        "stage": started["stage"],
                        "warnings": [],
                    },
                    request,
                    source="databricks-genie",
                    state="pending",
                    authoritative=False,
                    capabilities={
                        "provider": "genie",
                        "genieStreaming": True,
                        "spaceId": genie_status.get("spaceId", ""),
                    },
                )
        elif genie_status.get("provider") == "genie":
            genie_warning = _normalize_str(genie_status.get("message"))
    except Exception as exc:
        genie_warning = f"Genie-backed Atlas AI unavailable: {error_text(exc)}"

    warnings = []
    if genie_warning:
        warnings.append(genie_warning)
    if genie_status.get("provider") != "genie":
        warnings.append("Atlas AI recommendations require a configured Databricks Genie space.")
    if not warnings:
        warnings.append("Atlas AI recommendations are unavailable until Databricks Genie returns evidence.")
    payload = {
        "question": question,
        "intent": "unavailable",
        "answer": "",
        "recommendations": [],
        "evidence": [],
        "suggestedActions": [],
        "confidence": "unavailable",
        "provider": "unavailable",
        "providerState": genie_status,
        "warnings": warnings,
    }
    return _wrap(
        payload,
        request,
        source="runtime-configuration+databricks-genie",
        state="unavailable",
        authoritative=False,
        capabilities={
            "provider": "genie",
            "genie": genie_status,
            "evidenceBacked": False,
            "sampleValuesIncluded": False,
            "piiValuesIncluded": False,
        },
        warnings=warnings,
    )


def api_atlas_ai_message(request: Request, body: AtlasAiPoll | None = Body(default=None)) -> JSONResponse:
    """Poll a running Genie conversation started by /atlas-ai/recommendations.
    Returns {intent: "genie-pending", stage} while in flight; the finalized
    answer envelope (identical to the blocking path) once COMPLETED."""
    from runtime_app import _config, _ensure_live_runtime, _request_obo_token

    _ensure_live_runtime()
    conversation_id = _normalize_str(getattr(body, "conversationId", "")) if body else ""
    message_id = _normalize_str(getattr(body, "messageId", "")) if body else ""
    question = _normalize_str(getattr(body, "question", "")) if body else ""
    ai_context = getattr(body, "context", None) if body else None
    if not conversation_id or not message_id:
        raise HTTPException(status_code=422, detail="conversationId and messageId are required.")

    cfg = _config()
    genie_status = genie_service.provider_status(cfg)
    unavailable = lambda note: _wrap(  # noqa: E731
        {
            "question": question, "intent": "unavailable", "answer": "", "recommendations": [],
            "evidence": [], "suggestedActions": [], "confidence": "unavailable", "provider": "genie",
            "providerState": genie_status, "warnings": [note],
        },
        request, source="databricks-genie", state="unavailable", authoritative=False,
        capabilities={"provider": "genie", "genie": genie_status},
    )
    if not (genie_status.get("provider") == "genie" and genie_status.get("state") == "available"):
        return unavailable("Atlas AI recommendations require a configured Databricks Genie space.")
    forwarded_token = _request_obo_token(request)
    if not forwarded_token:
        return unavailable("Genie-backed Atlas AI requires the forwarded Databricks user token.")

    try:
        result = genie_service.poll_genie(
            config=cfg, conversation_id=conversation_id, message_id=message_id,
            user_access_token=forwarded_token,
        )
    except Exception as exc:
        return unavailable(f"Atlas AI could not complete the request: {error_text(exc)}")

    if not result.get("done"):
        return _wrap(
            {
                "question": question, "intent": "genie-pending", "answer": "", "recommendations": [],
                "evidence": [], "suggestedActions": [], "confidence": "pending", "provider": "genie",
                "providerState": genie_status, "conversationId": conversation_id, "messageId": message_id,
                "status": result.get("status", ""), "stage": result.get("stage", "Working"), "warnings": [],
            },
            request, source="databricks-genie", state="pending", authoritative=False,
            capabilities={"provider": "genie", "genieStreaming": True, "spaceId": genie_status.get("spaceId", "")},
        )

    # COMPLETED: finalize (grounding override + recommendations) and cache the
    # raw payload so an identical repeat question is instant.
    raw = result.get("payload") or {}
    context_preamble = _ai_context_preamble(ai_context)
    genie_question = f"{context_preamble}{question}" if context_preamble else question
    try:
        _ttl_value(_genie_cache_key(genie_status, forwarded_token, genie_question), 120, lambda: raw)
    except Exception:
        pass
    return _finalize_genie_payload(
        raw, question=question, request=request, ai_context=ai_context, genie_status=genie_status,
    )


_AUTOFILL_WINDOW_S = 60
_AUTOFILL_MAX_CALLS = 20
_AUTOFILL_CALLS: Dict[str, List[float]] = {}
_AUTOFILL_LOCK = threading.Lock()


def _enforce_autofill_rate_limit(actor_email: str) -> None:
    # ponytail: per-process sliding window; move to Lakebase if the app scales out.
    now = time.monotonic()
    with _AUTOFILL_LOCK:
        recent = [t for t in _AUTOFILL_CALLS.get(actor_email, []) if now - t < _AUTOFILL_WINDOW_S]
        if len(recent) >= _AUTOFILL_MAX_CALLS:
            _AUTOFILL_CALLS[actor_email] = recent
            raise HTTPException(
                status_code=429,
                detail=f"AI autofill is limited to {_AUTOFILL_MAX_CALLS} drafts per minute. Try again shortly.",
            )
        recent.append(now)
        _AUTOFILL_CALLS[actor_email] = recent


def api_atlas_ai_autofill(request: Request, body: AtlasAiAutofill | None = Body(default=None)) -> JSONResponse:
    """Draft freeform field values (e.g. a glossary definition + domain from a
    term name) with the generative endpoint. Returns {fields, model, warnings};
    everything is a draft the user reviews before saving — this never writes."""
    from atlas.services import ai_generation
    from runtime_app import _config, _ensure_can_mutate, _ensure_live_runtime, _request_obo_token

    _ensure_live_runtime()
    # Drafts are for editors, and every call is billed to the app's serving
    # endpoint: require a writer+ identity and cap calls per user.
    actor_email = _ensure_can_mutate(request)
    _enforce_autofill_rate_limit(actor_email)
    kind = _normalize_str(getattr(body, "kind", "")) if body else ""
    context = getattr(body, "context", None) if body else None
    if not kind:
        raise HTTPException(status_code=422, detail="kind is required.")

    cfg = _config()
    status = ai_generation.provider_status(cfg)
    unavailable = lambda note: _wrap(  # noqa: E731
        {"kind": kind, "fields": {}, "model": status.get("endpoint", ""), "warnings": [note]},
        request, source="databricks-foundation-model", state="unavailable", authoritative=False,
        capabilities={"provider": "ai-generation", "endpoint": status.get("endpoint", "")},
    )
    if status["state"] != "available":
        return unavailable(status["message"])
    # Call the serving endpoint with the app's service principal, NOT OBO: the
    # forwarded user token doesn't carry the `model-serving` scope, and drafting
    # a definition from a foundation model touches no user-specific governed
    # data (unlike Genie, which must stay OBO). Fall back to OBO if present.
    forwarded_token = _request_obo_token(request)
    try:
        # Prefer the app service principal (holds the serving CAN_QUERY grant).
        # Only fall back to OBO on an AUTH error, and surface the SP error so a
        # scope/permission misconfig is diagnosable instead of masked.
        try:
            result = ai_generation.generate_fields(config=cfg, kind=kind, context=context or {})
        except ValueError:
            raise
        except Exception as sp_error:
            if not forwarded_token:
                raise
            try:
                result = ai_generation.generate_fields(
                    config=cfg, kind=kind, context=context or {}, user_access_token=forwarded_token,
                )
            except Exception:
                # Re-raise the SP error (the primary path) for diagnosis.
                raise sp_error
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        return unavailable(f"AI autofill is unavailable right now: {error_text(exc)}")
    return _wrap(
        {"kind": kind, "fields": result.get("fields", {}), "model": result.get("model", ""),
         "warnings": result.get("warnings", [])},
        request, source="databricks-foundation-model",
        state="available" if result.get("fields") else "degraded",
        authoritative=False,
        capabilities={"provider": "ai-generation", "endpoint": result.get("model", "")},
        warnings=result.get("warnings") or None,
    )


def api_atlas_ai_chat(
    request: Request,
    body: AtlasAiQuestion,
) -> JSONResponse:
    question = _normalize_str(body.question)
    if not question:
        raise HTTPException(status_code=422, detail="Question is required.")
    return api_atlas_ai_recommendations(request, AtlasAiQuestion(question=question))


def build_atlas_router() -> APIRouter:
    router = APIRouter(prefix="/api/atlas", tags=["atlas"])
    router.add_api_route("/command-center", api_command_center, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/assets/{asset_fqn:path}/360", api_asset_360, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/governance/workbench", api_governance_workbench, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/governance/requests/{request_id}", api_governance_request_detail, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/insights", api_insights_dashboard, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/taxonomy/overview", api_taxonomy_overview, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/cde", api_cde_dashboard, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/cde/{cde_id:path}", api_cde_detail, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/audit/evidence", api_audit_evidence, methods=["GET"], response_class=JSONResponse)
    router.add_api_route("/admin/control-center", api_admin_control_center, methods=["GET"], response_class=JSONResponse)
    return router


def build_atlas_ai_router() -> APIRouter:
    router = APIRouter(prefix="/api/atlas-ai", tags=["atlas-ai"])
    router.add_api_route("/recommendations", api_atlas_ai_recommendations, methods=["POST"], response_class=JSONResponse)
    router.add_api_route("/message", api_atlas_ai_message, methods=["POST"], response_class=JSONResponse)
    router.add_api_route("/autofill", api_atlas_ai_autofill, methods=["POST"], response_class=JSONResponse)
    router.add_api_route("/chat", api_atlas_ai_chat, methods=["POST"], response_class=JSONResponse)
    return router


__all__ = [
    "build_atlas_router",
    "build_atlas_ai_router",
    "api_command_center",
    "api_asset_360",
    "api_governance_workbench",
    "api_governance_request_detail",
    "api_insights_dashboard",
    "api_taxonomy_overview",
    "api_cde_dashboard",
    "api_cde_detail",
    "api_audit_evidence",
    "api_admin_control_center",
    "api_atlas_ai_recommendations",
    "api_atlas_ai_message",
    "api_atlas_ai_autofill",
    "api_atlas_ai_chat",
]
