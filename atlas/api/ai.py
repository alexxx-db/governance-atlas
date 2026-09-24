"""AI governance API (DESIGN.md section 9).

Registered by runtime_app._register_ai_router only when ai_features_enabled
is on. Reads come from the governance tables written by the jobs; the only
writes are steward decisions and intake imports, all through AiStore, which
audits before mutating. Routes are plain ``def`` so blocking warehouse calls
run in the threadpool, not on the event loop.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from atlas.api.response import _request_id, _with_meta

AI_SOURCE = "ai-governance"
MAX_CSV_CHARS = 5_000_000


class IntakeImportRequest(BaseModel):
    csvText: str = Field(default="", max_length=MAX_CSV_CHARS)


def _ai_store() -> Any:
    from atlas.ai.store import AiStore
    from runtime_app import _ensure_governance_store, _store

    _ensure_governance_store()
    return AiStore(_store())


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
    router.add_api_route("/api/ai/intake/import", api_ai_intake_import, methods=["POST"])
    return router
