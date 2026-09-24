"""AI governance API (DESIGN.md section 9).

Registered by runtime_app._register_ai_router only when ai_features_enabled
is on. Reads come from the governance tables written by the jobs; the only
writes are steward decisions and intake imports, all through AiStore, which
audits before mutating. Routes are plain ``def`` so blocking warehouse calls
run in the threadpool, not on the event loop.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from atlas.api.response import _request_id, _with_meta
from atlas.services import input_safety

# "governance-store" marks these envelopes as a trusted live source for the
# frontend provenance filter, so a degraded AI view renders as degraded
# rather than being hidden as mock evidence.
AI_SOURCE = "governance-store:ai"
MAX_CSV_CHARS = 5_000_000
ENTITY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
FINDING_ID_RE = re.compile(r"^[0-9a-f]{64}$")
STEWARD_ROLES = {"steward", "admin"}


class IntakeImportRequest(BaseModel):
    csvText: str = Field(default="", max_length=MAX_CSV_CHARS)


def _ai_store() -> Any:
    from atlas.ai.store import AiStore
    from runtime_app import _ensure_governance_store, _store

    _ensure_governance_store()
    return AiStore(_store())


class FindingPatch(BaseModel):
    action: str = Field(default="", max_length=32)
    assigneeEmail: str = Field(default="", max_length=254)
    note: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=2000)


class ConfirmMatchRequest(BaseModel):
    intakeId: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=2000)


def _tier_key() -> str:
    from runtime_app import _config

    return str(getattr(_config(), "ai_tier_tag_key", "ai_risk_tier") or "ai_risk_tier")


def _envelope(payload: Dict[str, Any], request: Request, avail: Dict[str, Any]) -> JSONResponse:
    """Availability from the run record drives the envelope state: an empty
    result with a failed source is 'degraded', never an authoritative empty."""
    body = {**payload, "availability": avail}
    return JSONResponse(
        _with_meta(
            body,
            request,
            source=AI_SOURCE,
            state=avail["state"],
            warnings=list(avail.get("warnings") or []),
            unavailable_reason=avail.get("reason") or "",
        )
    )


def _is_steward(request: Request) -> bool:
    from runtime_app import _user_role_slug

    return _user_role_slug(request) in STEWARD_ROLES


def _clean_text(value: str, field: str, max_length: int = 2000) -> str:
    try:
        return input_safety.sanitize_plain_text(value, field=field, max_length=max_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def api_ai_summary(request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    ai = _ai_store()
    avail = views.availability(ai)
    return _envelope({"summary": views.summary(ai, avail, _tier_key())}, request, avail)


def api_ai_inventory(
    request: Request,
    kind: str = Query(default="", max_length=32),
    provider: str = Query(default="", max_length=128),
    platform: str = Query(default="", max_length=32),
    tier: str = Query(default="", max_length=64),
    state: str = Query(default="", max_length=32),
    hasOpenFindings: Optional[bool] = Query(default=None),
    q: str = Query(default="", max_length=200),
    sort: str = Query(default="findings"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    if sort not in views.SORT_KEYS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {sorted(views.SORT_KEYS)}.")
    ai = _ai_store()
    avail = views.availability(ai)
    rows = views.filter_rows(
        views.inventory_rows(ai, avail, _tier_key()),
        {"kind": kind, "provider": provider, "platform": platform, "tier": tier, "state": state, "hasOpenFindings": hasOpenFindings, "q": q},
    )
    rows.sort(key=views.SORT_KEYS[sort])
    return _envelope(
        {"items": rows[offset : offset + limit], "total": len(rows) if avail.get("run") else None, "limit": limit, "offset": offset},
        request,
        avail,
    )


def _entity_id(entity_id: str) -> str:
    value = str(entity_id or "").strip().lower()
    if not ENTITY_ID_RE.match(value):
        raise HTTPException(status_code=400, detail="entity_id must be a 32-character hexadecimal AI asset id.")
    return value


def _finding_id(finding_id: str) -> str:
    value = str(finding_id or "").strip().lower()
    if not FINDING_ID_RE.match(value):
        raise HTTPException(status_code=400, detail="finding_id must be a 64-character hexadecimal id.")
    return value


def api_ai_asset(entity_id: str, request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    entity_id = _entity_id(entity_id)
    ai = _ai_store()
    avail = views.availability(ai)
    detail = views.asset_detail(ai, avail, entity_id, tier_key=_tier_key(), include_config=_is_steward(request))
    if detail is None:
        if not avail.get("run"):
            return _envelope({"asset": None}, request, avail)
        raise HTTPException(status_code=404, detail="AI asset not found in the latest completed run.")
    return _envelope({"asset": detail}, request, avail)


def api_ai_asset_controls(entity_id: str, request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    entity_id = _entity_id(entity_id)
    ai = _ai_store()
    avail = views.availability(ai)
    rows = ai.list_control_results(run_id=str(avail["run"]["runId"]), entity_id=entity_id) if avail.get("run") else []
    return _envelope({"entityId": entity_id, "controls": [views.control_view(r) for r in rows]}, request, avail)


def api_ai_findings(
    request: Request,
    state: str = Query(default="open,acknowledged", max_length=128),
    findingType: str = Query(default="", max_length=256),
    severity: str = Query(default="", max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    from atlas.ai import views
    from atlas.ai.models import FINDING_STATES, SEVERITIES
    from runtime_app import _ensure_can_approve, _ensure_live_runtime

    _ensure_live_runtime()
    _ensure_can_approve(request)
    states = [s for s in (x.strip() for x in state.split(",")) if s]
    types = [t for t in (x.strip() for x in findingType.split(",")) if t]
    severities = [s for s in (x.strip() for x in severity.split(",")) if s]
    if any(s not in FINDING_STATES for s in states) or any(s not in SEVERITIES for s in severities):
        raise HTTPException(status_code=400, detail="Unknown state or severity filter.")
    if any(not re.match(r"^[a-z_]{1,64}$", t) for t in types):
        raise HTTPException(status_code=400, detail="Unknown findingType filter.")
    ai = _ai_store()
    avail = views.availability(ai)
    rows = ai.list_findings(states=states, finding_types=types, severities=severities, limit=limit, offset=offset)
    total = ai.count_findings(states=states, finding_types=types, severities=severities)
    return _envelope({"items": [views.finding_view(r) for r in rows], "total": total, "limit": limit, "offset": offset}, request, avail)


def api_ai_finding_patch(finding_id: str, payload: FindingPatch, request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_can_approve, _ensure_live_runtime, _user_role_slug

    _ensure_live_runtime()
    actor = _ensure_can_approve(request)
    finding_id = _finding_id(finding_id)
    action = payload.action.strip().lower()
    if action not in {"acknowledge", "assign", "resolve", "suppress", "reopen"}:
        raise HTTPException(status_code=400, detail="action must be acknowledge, assign, resolve, suppress, or reopen.")
    assignee = payload.assigneeEmail.strip().lower()
    if action == "assign" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", assignee):
        raise HTTPException(status_code=400, detail="assigneeEmail must be an email address.")
    try:
        updated = _ai_store().update_finding_state(
            finding_id=finding_id,
            action=action,
            actor_email=actor,
            actor_role=_user_role_slug(request),
            request_id=_request_id(request) or None,
            assignee_email=assignee or None,
            note=_clean_text(payload.note, "note") or None,
            reason=_clean_text(payload.reason, "reason") or None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(_with_meta({"finding": views.finding_view(updated)}, request, source=AI_SOURCE))


def api_ai_finding_confirm_match(finding_id: str, payload: ConfirmMatchRequest, request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_can_approve, _ensure_live_runtime, _user_role_slug

    _ensure_live_runtime()
    actor = _ensure_can_approve(request)
    finding_id = _finding_id(finding_id)
    ai = _ai_store()
    finding = ai.findings_by_id([finding_id]).get(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    if finding.get("finding_type") not in {"ambiguous_match", "found_not_registered"} or not finding.get("entity_id"):
        raise HTTPException(status_code=409, detail="Only ambiguous or unregistered asset findings can be confirmed to an intake.")
    intake_id = _clean_text(payload.intakeId, "intakeId", 128)
    if not intake_id or intake_id not in {str(r["intake_id"]) for r in ai.list_intake_records()}:
        raise HTTPException(status_code=400, detail="intakeId must name an existing intake record.")
    updated = ai.confirm_match(
        finding_id=finding_id,
        entity_id=str(finding["entity_id"]),
        entity_kind=str(finding.get("entity_kind") or ""),
        intake_id=intake_id,
        actor_email=actor,
        actor_role=_user_role_slug(request),
        request_id=_request_id(request) or None,
        note=_clean_text(payload.note, "note"),
    )
    return JSONResponse(_with_meta({"finding": views.finding_view(updated)}, request, source=AI_SOURCE))


def api_ai_intake(request: Request) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    ai = _ai_store()
    avail = views.availability(ai)
    rows = views.intake_rows(ai)
    # Intake is declared data, readable even before any run completes; the
    # link status still reflects run availability via the envelope.
    return _envelope({"items": rows, "total": len(rows)}, request, {**avail, "state": "degraded" if avail["state"] == "unavailable" else avail["state"]})


def api_ai_runs(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> JSONResponse:
    from atlas.ai import views
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()
    ai = _ai_store()
    runs = [views._run_summary(r) | {"sources": r.get("sources_json") or {}} for r in ai.list_runs(limit=limit)]
    return JSONResponse(_with_meta({"items": runs}, request, source=AI_SOURCE))


def api_ai_intake_import(
    payload: IntakeImportRequest,
    request: Request,
    mode: str = Query(default="dry_run"),
) -> JSONResponse:
    """Dry run validates only (no writes). Commit is all-or-nothing: any
    invalid row rejects the whole file with the same per-row report, so a
    register is never half-imported."""
    from atlas.ai import intake as intake_service
    from runtime_app import _ensure_can_approve, _ensure_live_runtime, _user_role_slug

    _ensure_live_runtime()
    actor_email = _ensure_can_approve(request)  # steward or admin
    if mode not in {"dry_run", "commit"}:
        raise HTTPException(status_code=400, detail="mode must be dry_run or commit.")
    ingest_run_id = f"csv-{uuid.uuid4().hex[:12]}"
    report = intake_service.validate_csv(payload.csvText, ingest_run_id=ingest_run_id)
    records = report.pop("records")
    body: Dict[str, Any] = {**report, "mode": mode, "ingestRunId": ingest_run_id, "committed": None}
    if mode == "dry_run":
        return JSONResponse(_with_meta(body, request, source=AI_SOURCE))
    if not report["ok"]:
        body["detail"] = "Import rejected: fix the invalid rows and run the dry run again. Nothing was written."
        return JSONResponse(status_code=422, content=_with_meta(body, request, source=AI_SOURCE, state="degraded"))
    body["committed"] = _ai_store().upsert_intake_records(
        records,
        actor_email=actor_email,
        actor_role=_user_role_slug(request),
        request_id=_request_id(request) or None,
        source="import",
    )
    return JSONResponse(_with_meta(body, request, source=AI_SOURCE))


def build_ai_router() -> APIRouter:
    router = APIRouter(tags=["ai-governance"])
    router.add_api_route("/api/ai/summary", api_ai_summary, methods=["GET"])
    router.add_api_route("/api/ai/inventory", api_ai_inventory, methods=["GET"])
    router.add_api_route("/api/ai/assets/{entity_id}", api_ai_asset, methods=["GET"])
    router.add_api_route("/api/ai/assets/{entity_id}/controls", api_ai_asset_controls, methods=["GET"])
    router.add_api_route("/api/ai/findings", api_ai_findings, methods=["GET"])
    router.add_api_route("/api/ai/findings/{finding_id}", api_ai_finding_patch, methods=["PATCH"])
    router.add_api_route("/api/ai/findings/{finding_id}/confirm-match", api_ai_finding_confirm_match, methods=["POST"])
    router.add_api_route("/api/ai/intake", api_ai_intake, methods=["GET"])
    router.add_api_route("/api/ai/intake/import", api_ai_intake_import, methods=["POST"])
    router.add_api_route("/api/ai/reconciliation/runs", api_ai_runs, methods=["GET"])
    return router
