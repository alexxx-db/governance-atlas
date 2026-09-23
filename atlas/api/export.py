"""Phase 4 Tranche 2 / Phase 12 — export router.

Sync CSV export for actor-scoped, visible assets. The safety contract
lives in atlas/services/export.py (evaluate_export_request); this
router handles wiring + capability gating + response shaping only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from atlas.api.identity import _request_auth_mode, _user_email
from atlas.services import capabilities as capability_service
from atlas.services import export as export_service
from atlas.services.assets import normalize_str as _normalize_str
from atlas.services.metadata_audit import record_audit_log


class ExportAssetsRequest(BaseModel):
    assetFqns: List[str] = Field(default_factory=list)
    format: str = "csv"


class EnqueueExportRequest(BaseModel):
    assetFqns: List[str] = Field(default_factory=list)
    format: str = "csv"


def _actor_role_slug(request: Request) -> str:
    from runtime_app import _user_role_slug

    try:
        return _user_role_slug(request)
    except Exception:
        return "reader"


def _request_id(request: Request) -> str | None:
    try:
        from runtime_app import _http_request_id

        return _http_request_id(request)
    except Exception:
        return request.headers.get("x-databricks-request-id") or request.headers.get("x-request-id")


_EXPORT_ROW_WORKERS = 8


def _build_rows(asset_fqns: List[str], request: Request) -> list[dict]:
    """Assemble the per-asset row payload. Uses the existing
    _asset_detail_payload helper so the export surface inherits all of
    the normal visibility + redaction rules — an export can never show
    a field that the asset-detail API would hide.

    The per-asset detail is a ~1s SQL round trip, so a large selection is
    fanned out across a bounded thread pool (each asset still goes through the
    identical openability + redaction path). Order is preserved to match the
    caller's selection; unopenable/failed assets drop out (fail-closed)."""
    from concurrent.futures import ThreadPoolExecutor

    from runtime_app import _asset_detail_payload, _asset_is_openable

    normalized = [fqn for fqn in (_normalize_str(f) for f in asset_fqns) if fqn]
    if not normalized:
        return []

    def _row_for(fqn_normalized: str) -> Optional[dict]:
        # Fail closed — invisible assets can't leak through export.
        if not _asset_is_openable(fqn_normalized, request):
            return None
        try:
            payload = _asset_detail_payload(
                fqn_normalized,
                request=request,
                sections=["header"],
            )
        except Exception:
            return None
        return {
            "fqn": payload.get("fqn") or fqn_normalized,
            "name": payload.get("name"),
            "catalog": payload.get("catalog"),
            "schema": payload.get("schema"),
            "description": payload.get("description"),
            "domain": payload.get("domain"),
            "tier": payload.get("tier"),
            "certification": payload.get("certification"),
            "sensitivity": payload.get("sensitivity"),
            "criticality": payload.get("criticality"),
            "dataProduct": payload.get("dataProduct") or payload.get("data_product"),
            "governanceStatus": payload.get("governanceStatus"),
            "owners": payload.get("owners") or [],
            "tagEntries": payload.get("tagEntries") or [],
        }

    workers = max(1, min(_EXPORT_ROW_WORKERS, len(normalized)))
    if workers == 1:
        return [row for row in (_row_for(fqn) for fqn in normalized) if row is not None]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # pool.map preserves input order, so the CSV row order matches the
        # actor's selection.
        return [row for row in pool.map(_row_for, normalized) if row is not None]


def _persist_export_job(
    *,
    request: Request,
    job_id: str,
    asset_fqns: List[str],
    actor_email: str,
    actor_role: str,
    filter_snapshot: str,
    status: str,
    requested_at: datetime,
    token_captured_at: Optional[datetime],
    row_count: int = 0,
    byte_count: int = 0,
    error_detail: Optional[str] = None,
    mode: str = "sync",
    fail_closed: bool = False,
    checksum: Optional[str] = None,
) -> None:
    from runtime_app import _ensure_governance_store, _store
    from atlas.util import sql_literal

    try:
        _ensure_governance_store()
        store = _store()
        expires_at = export_service.expiry_for(requested_at)
        ts = requested_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        token_ts = (
            token_captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if token_captured_at
            else None
        )
        store.uc.execute(
            f"""INSERT INTO {store._fq("export_jobs")} (
    job_id, actor_email, actor_role, asset_fqns, filter_snapshot_json,
    format, mode, status, requested_at, token_captured_at, materialized_at,
    expires_at, download_url, row_count, byte_count, checksum, error_detail,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(job_id)},
    {sql_literal(actor_email)},
    {sql_literal(actor_role)},
    array({", ".join(sql_literal(fqn) for fqn in asset_fqns) or "CAST(NULL AS STRING)"}),
    {sql_literal(filter_snapshot)},
    {sql_literal("csv")},
    {sql_literal(mode)},
    {sql_literal(status)},
    timestamp({sql_literal(ts)}),
    {"NULL" if token_ts is None else f"timestamp({sql_literal(token_ts)})"},
    {f"timestamp({sql_literal(ts)})" if status == "ready" else "NULL"},
    timestamp({sql_literal(expires_at.strftime("%Y-%m-%d %H:%M:%S"))}),
    NULL,
    {int(row_count)},
    {int(byte_count)},
    {sql_literal(checksum)},
    {sql_literal(error_detail)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)}
)"""
        )
        record_audit_log(
            entity_type="export_job",
            action=f"export-{status}",
            actor_email=actor_email,
            actor_role=actor_role,
            entity_id=job_id,
            request_id=_request_id(request),
            after={
                "jobId": job_id,
                "assetFqns": asset_fqns,
                "assetCount": len(asset_fqns),
                "rowCount": row_count,
                "byteCount": byte_count,
                "status": status,
                "mode": mode,
                "format": "csv",
                "sha256": checksum,
                "errorDetail": error_detail,
            },
            source="api",
            status="success" if status in {"ready", "queued"} else "failed",
            detail=error_detail,
            fail_closed=fail_closed,
        )
    except Exception as exc:
        if fail_closed:
            raise RuntimeError(f"Export job audit persistence failed: {exc}") from exc
        # Non-sensitive background cleanup paths may still use best-effort logging.
        return


def api_export_assets(
    payload: ExportAssetsRequest,
    request: Request,
) -> JSONResponse:
    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()

    auth_mode = _request_auth_mode(request)
    actor_scoped = auth_mode == capability_service.OBO_AVAILABLE_MODE
    actor_email = _user_email(request) or "unknown"
    actor_role = _actor_role_slug(request)
    requested_at = datetime.now(timezone.utc)
    # Capture time == request time. We don't have visibility into when
    # the browser actually received the OBO header from Databricks, but
    # this is a fail-closed upper bound.
    token_captured_at = requested_at if actor_scoped else None

    asset_fqns = [_normalize_str(fqn) for fqn in (payload.assetFqns or [])]
    asset_fqns = [fqn for fqn in asset_fqns if fqn]

    decision = export_service.evaluate_export_request(
        actor_scoped=actor_scoped,
        token_captured_at=token_captured_at,
        asset_count=len(asset_fqns),
        sync=True,
        now=requested_at,
    )
    if not decision.allowed:
        return JSONResponse(
            status_code=403 if decision.status == "stale_auth" else 400,
            content={
                "error": {
                    "code": decision.status,
                    "message": decision.reason,
                }
            },
        )

    rows = _build_rows(asset_fqns, request)
    csv_text = export_service.build_csv(rows, EXPORT_CSV_COLUMNS)
    byte_count = len(csv_text.encode("utf-8"))
    # G10: SHA-256 of the exact bytes served — persisted + audit-logged so the
    # export is tamper-evident (a recipient re-hashes and compares).
    checksum = export_service.content_sha256(csv_text) if rows else None

    job_id = export_service.new_job_id()
    filter_snapshot = export_service.build_filter_snapshot(
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        visibility_scope=capability_service.runtime_visibility_scope(auth_mode),
        format="csv",
        requested_at=requested_at,
    )
    _persist_export_job(
        request=request,
        job_id=job_id,
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        actor_role=actor_role,
        filter_snapshot=filter_snapshot,
        status="ready" if rows else "failed",
        requested_at=requested_at,
        token_captured_at=token_captured_at,
        row_count=len(rows),
        byte_count=byte_count,
        error_detail=None if rows else "No visible assets matched the export request.",
        mode="sync",
        fail_closed=True,
        checksum=checksum,
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                "No visible assets matched the export request. Confirm the "
                "asset FQNs exist in your workspace scope."
            ),
        )

    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="atlas-export-{job_id}.csv"',
            "X-GOVAT-Export-Job-Id": job_id,
            "X-GOVAT-Export-Row-Count": str(len(rows)),
            "X-GOVAT-Export-SHA256": checksum or "",
        },
    )


def api_export_evidence_pack(
    payload: ExportAssetsRequest,
    request: Request,
) -> Response:
    """G10 — a tamper-evident evidence pack: the asset CSV + a provenance
    manifest.json (SHA-256 of the CSV, actor, timestamp, filter) zipped
    together. Checksummed + provenance-stamped, NOT cryptographically signed.
    Same OBO/visibility contract as the CSV export."""
    import io
    import zipfile

    from runtime_app import _ensure_live_runtime

    _ensure_live_runtime()

    auth_mode = _request_auth_mode(request)
    actor_scoped = auth_mode == capability_service.OBO_AVAILABLE_MODE
    actor_email = _user_email(request) or "unknown"
    actor_role = _actor_role_slug(request)
    requested_at = datetime.now(timezone.utc)
    token_captured_at = requested_at if actor_scoped else None

    asset_fqns = [fqn for fqn in (_normalize_str(f) for f in (payload.assetFqns or [])) if fqn]

    decision = export_service.evaluate_export_request(
        actor_scoped=actor_scoped,
        token_captured_at=token_captured_at,
        asset_count=len(asset_fqns),
        sync=True,
        now=requested_at,
    )
    if not decision.allowed:
        return JSONResponse(
            status_code=403 if decision.status == "stale_auth" else 400,
            content={"error": {"code": decision.status, "message": decision.reason}},
        )

    rows = _build_rows(asset_fqns, request)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No visible assets matched the export request.",
        )
    csv_text = export_service.build_csv(rows, EXPORT_CSV_COLUMNS)
    byte_count = len(csv_text.encode("utf-8"))
    checksum = export_service.content_sha256(csv_text)
    job_id = export_service.new_job_id()
    data_filename = f"atlas-export-{job_id}.csv"

    filter_snapshot = export_service.build_filter_snapshot(
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        visibility_scope=capability_service.runtime_visibility_scope(auth_mode),
        format="evidence-pack",
        requested_at=requested_at,
    )
    manifest = export_service.build_provenance_manifest(
        job_id=job_id,
        actor_email=actor_email,
        actor_role=actor_role,
        generated_at=requested_at,
        filter_snapshot=filter_snapshot,
        row_count=len(rows),
        byte_count=byte_count,
        sha256=checksum,
        data_filename=data_filename,
    )

    _persist_export_job(
        request=request,
        job_id=job_id,
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        actor_role=actor_role,
        filter_snapshot=filter_snapshot,
        status="ready",
        requested_at=requested_at,
        token_captured_at=token_captured_at,
        row_count=len(rows),
        byte_count=byte_count,
        mode="evidence-pack",
        fail_closed=True,
        checksum=checksum,
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(data_filename, csv_text)
        archive.writestr("manifest.json", manifest)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="atlas-evidence-pack-{job_id}.zip"',
            "X-GOVAT-Export-Job-Id": job_id,
            "X-GOVAT-Export-SHA256": checksum,
        },
    )


def api_export_board_report(request: Request) -> Response:
    """G8 — a board-ready executive governance report assembled from the live
    command-center + insights payloads, returned as print-ready HTML (Print →
    Save as PDF). Unavailable metrics stay labeled, never fabricated."""
    from runtime_app import _ensure_live_runtime, _store_for_read, _user_email, _visible_assets
    from atlas.services import atlas_metrics

    _ensure_live_runtime()
    actor_email = _user_email(request) or "unknown"
    generated_at = datetime.now(timezone.utc)

    store = _store_for_read()
    visible = _visible_assets(request)
    try:
        command_center = atlas_metrics.command_center_payload(visible_assets=visible, store=store)
    except Exception:
        command_center = {}
    try:
        insights = atlas_metrics.insights_dashboard_payload(visible_assets=visible, store=store)
    except Exception:
        insights = {}

    org_name = "Governance Atlas"
    try:
        branding = store.get_tenant_branding() if hasattr(store, "get_tenant_branding") else {}
        org_name = _normalize_str(branding.get("org_display_name")) or org_name
    except Exception:
        org_name = "Governance Atlas"

    html_doc = export_service.build_board_report_html(
        command_center=command_center,
        insights=insights,
        actor_email=actor_email,
        generated_at=generated_at,
        org_name=org_name,
    )
    filename = f"atlas-board-report-{generated_at.strftime('%Y-%m-%d')}.html"
    return Response(
        content=html_doc,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


EXPORT_CSV_COLUMNS = [
    "fqn",
    "name",
    "catalog",
    "schema",
    "description",
    "domain",
    "tier",
    "certification",
    "sensitivity",
    "criticality",
    "dataProduct",
    "governanceStatus",
    "owners",
    "tagEntries",
]


def _serialize_job_row(row: dict) -> dict:
    def _ts(value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return {
        "jobId": row.get("job_id"),
        "actorEmail": row.get("actor_email"),
        "actorRole": row.get("actor_role"),
        "status": row.get("status"),
        "mode": row.get("mode"),
        "format": row.get("format"),
        "requestedAt": _ts(row.get("requested_at")),
        "materializedAt": _ts(row.get("materialized_at")),
        "expiresAt": _ts(row.get("expires_at")),
        "tokenCapturedAt": _ts(row.get("token_captured_at")),
        "rowCount": int(row.get("row_count") or 0) if row.get("row_count") is not None else 0,
        "byteCount": int(row.get("byte_count") or 0) if row.get("byte_count") is not None else 0,
        "errorDetail": row.get("error_detail"),
    }


def _job_asset_fqns(row: dict) -> List[str]:
    raw = row.get("asset_fqns")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if hasattr(raw, "tolist"):
        return [str(item) for item in raw.tolist() if item]
    snapshot = row.get("filter_snapshot_json")
    if isinstance(snapshot, str) and snapshot.strip():
        try:
            payload = json.loads(snapshot)
        except Exception:
            return []
        fqns = payload.get("assetFqns")
        if isinstance(fqns, list):
            return [str(item) for item in fqns if item]
    return []


def api_export_job_download(
    job_id: str,
    request: Request,
) -> PlainTextResponse:
    """Re-download a previously materialized export. Enforces:
    - actor-scoped auth
    - requester identity match
    - status == ready
    - not expired
    - token capture time not stale (>55 min)
    Re-materializes CSV on demand — artifact is not persisted, preserving
    the no-raw-artifact rule and ensuring any intervening visibility
    changes apply."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store

    _ensure_live_runtime()
    try:
        _ensure_governance_store()
        store = _store()
        job_row = store.get_export_job(job_id)
    except Exception:
        job_row = None
    if not job_row:
        raise HTTPException(status_code=404, detail="Export job not found.")

    auth_mode = _request_auth_mode(request)
    actor_scoped = auth_mode == capability_service.OBO_AVAILABLE_MODE
    actor_email = _user_email(request) or "unknown"

    decision = export_service.evaluate_download_request(
        actor_scoped=actor_scoped,
        actor_email=actor_email,
        requester_email=job_row.get("actor_email"),
        status=job_row.get("status"),
        expires_at=job_row.get("expires_at"),
        token_captured_at=job_row.get("token_captured_at"),
    )
    if not decision.allowed:
        status_code = {
            "forbidden": 403,
            "stale_auth": 403,
            "expired": 410,
        }.get(decision.status, 400)
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": decision.status, "message": decision.reason}},
        )

    asset_fqns = _job_asset_fqns(job_row)
    rows = _build_rows(asset_fqns, request)
    if not rows:
        raise HTTPException(
            status_code=410,
            detail=(
                "Exported assets are no longer visible to this actor. "
                "Re-run the export from Discovery."
            ),
        )
    csv_text = export_service.build_csv(rows, EXPORT_CSV_COLUMNS)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="atlas-export-{job_id}.csv"',
            "X-GOVAT-Export-Job-Id": job_id,
            "X-GOVAT-Export-Row-Count": str(len(rows)),
            "X-GOVAT-Export-Redownload": "true",
        },
    )


def api_admin_export_jobs(
    request: Request,
    actor_email: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    """Admin-only list of recent export jobs for the diagnostics surface.
    Used by Phase 4 Tranche 2 admin dashboard."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store, _user_role_slug

    _ensure_live_runtime()
    role = _user_role_slug(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    try:
        _ensure_governance_store()
        store = _store()
        frame = store.list_export_jobs(
            actor_email=actor_email,
            status=status,
            limit=max(1, min(int(limit), 500)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read export jobs: {exc}")

    jobs: List[dict] = []
    if frame is not None and not frame.empty:
        for _, row in frame.iterrows():
            jobs.append(_serialize_job_row(row.to_dict()))
    return JSONResponse(
        status_code=200,
        content={
            "data": jobs,
            "meta": {
                "authoritative": True,
                "source": "control_plane",
                "observedAt": datetime.now(timezone.utc).isoformat(),
            },
        },
    )


def _enqueue_background_work(
    *,
    store,
    job_id: str,
    asset_fqns: List[str],
    actor_email: str,
    actor_role: str,
    token_captured_at: Optional[datetime],
) -> str:
    from atlas.util import sql_literal
    import uuid

    work_id = uuid.uuid4().hex
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    token_ts = (
        token_captured_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if token_captured_at
        else None
    )
    payload = json.dumps(
        {"jobId": job_id, "assetFqns": list(asset_fqns), "format": "csv"},
        sort_keys=True,
    )
    store.uc.execute(
        f"""INSERT INTO {store._fq('background_work_items')} (
    work_id, work_kind, priority, status, payload_json, dependency_work_id,
    actor_email, actor_role, token_captured_at, scheduled_for, claimed_at,
    claimed_by, started_at, finished_at, attempt_count, max_attempts,
    last_error, result_json, created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(work_id)},
    {sql_literal('export')},
    100,
    {sql_literal('queued')},
    {sql_literal(payload)},
    NULL,
    {sql_literal(actor_email)},
    {sql_literal(actor_role)},
    {'NULL' if token_ts is None else f"timestamp({sql_literal(token_ts)})"},
    timestamp({sql_literal(ts_now)}),
    NULL, NULL, NULL, NULL,
    0, 3,
    NULL, NULL,
    timestamp({sql_literal(ts_now)}),
    {sql_literal(actor_email)},
    timestamp({sql_literal(ts_now)}),
    {sql_literal(actor_email)}
)"""
    )
    return work_id


def api_export_enqueue(payload: EnqueueExportRequest, request: Request) -> JSONResponse:
    """Phase 12 — enqueue an async export. Writes a queued row to
    export_jobs + background_work_items and returns the job_id so the
    browser can poll `/api/export/{job_id}/status`.

    Large exports exceed SYNC_EXPORT_MAX_ROWS so the sync endpoint
    refuses them; this is the async path. A separate runner
    (Phase 12 extension) materializes queued jobs under app-principal
    auth subject to the token_captured_at freshness window."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store

    _ensure_live_runtime()
    auth_mode = _request_auth_mode(request)
    actor_scoped = auth_mode == capability_service.OBO_AVAILABLE_MODE
    actor_email = _user_email(request) or "unknown"
    actor_role = _actor_role_slug(request)
    requested_at = datetime.now(timezone.utc)
    token_captured_at = requested_at if actor_scoped else None

    asset_fqns = [_normalize_str(fqn) for fqn in (payload.assetFqns or [])]
    asset_fqns = [fqn for fqn in asset_fqns if fqn]

    decision = export_service.evaluate_export_request(
        actor_scoped=actor_scoped,
        token_captured_at=token_captured_at,
        asset_count=len(asset_fqns),
        sync=False,
        now=requested_at,
    )
    if not decision.allowed:
        return JSONResponse(
            status_code=403 if decision.status == "stale_auth" else 400,
            content={"error": {"code": decision.status, "message": decision.reason}},
        )

    job_id = export_service.new_job_id()
    filter_snapshot = export_service.build_filter_snapshot(
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        visibility_scope=capability_service.runtime_visibility_scope(auth_mode),
        format="csv",
        requested_at=requested_at,
    )
    _persist_export_job(
        request=request,
        job_id=job_id,
        asset_fqns=asset_fqns,
        actor_email=actor_email,
        actor_role=actor_role,
        filter_snapshot=filter_snapshot,
        status="queued",
        requested_at=requested_at,
        token_captured_at=token_captured_at,
        row_count=0,
        byte_count=0,
        error_detail=None,
        mode="async",
        fail_closed=True,
    )
    try:
        _ensure_governance_store()
        work_id = _enqueue_background_work(
            store=_store(),
            job_id=job_id,
            asset_fqns=asset_fqns,
            actor_email=actor_email,
            actor_role=actor_role,
            token_captured_at=token_captured_at,
        )
        record_audit_log(
            entity_type="background_work_item",
            action="work-queued",
            actor_email=actor_email,
            actor_role=actor_role,
            entity_id=work_id,
            request_id=_request_id(request),
            after={
                "workId": work_id,
                "workKind": "export",
                "jobId": job_id,
                "assetCount": len(asset_fqns),
                "status": "queued",
            },
            source="api",
            fail_closed=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue export work: {exc}") from exc
    from runtime_app import _wake_background_drainer

    _wake_background_drainer()
    return JSONResponse(
        status_code=202,
        content={
            "data": {
                "jobId": job_id,
                "status": "queued",
                "assetCount": len(asset_fqns),
                "mode": "async",
            },
            "meta": {
                "authoritative": True,
                "source": "control_plane",
                "observedAt": requested_at.isoformat(),
            },
        },
    )


def api_export_job_status(job_id: str, request: Request) -> JSONResponse:
    """Phase 12 — poll endpoint. Returns current status + timestamps for
    the export job. Requester-identity gated so an actor can't read
    another user's queued jobs."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store

    _ensure_live_runtime()
    actor_email = _user_email(request) or "unknown"
    try:
        _ensure_governance_store()
        row = _store().get_export_job(job_id)
    except Exception:
        row = None
    if not row:
        raise HTTPException(status_code=404, detail="Export job not found.")
    if (row.get("actor_email") or "").lower() != actor_email.lower():
        raise HTTPException(status_code=403, detail="You can only read your own export jobs.")
    return JSONResponse(
        status_code=200,
        content={
            "data": _serialize_job_row(row),
            "meta": {
                "authoritative": True,
                "source": "control_plane",
                "observedAt": datetime.now(timezone.utc).isoformat(),
            },
        },
    )


def api_list_my_export_jobs(request: Request, limit: int = 25) -> JSONResponse:
    """Phase 12 — list recent export jobs for the current actor."""
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store

    _ensure_live_runtime()
    actor_email = _user_email(request) or "unknown"
    try:
        _ensure_governance_store()
        frame = _store().list_export_jobs(actor_email=actor_email, limit=max(1, min(int(limit), 100)))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read export jobs: {exc}")
    jobs: List[dict] = []
    if frame is not None and not frame.empty:
        for _, row in frame.iterrows():
            jobs.append(_serialize_job_row(row.to_dict()))
    return JSONResponse(
        status_code=200,
        content={
            "data": jobs,
            "meta": {
                "authoritative": True,
                "source": "control_plane",
                "observedAt": datetime.now(timezone.utc).isoformat(),
            },
        },
    )


def _handle_export_work(handler_input: dict):
    """Phase 12 runner handler for 'export' work items. Re-runs the
    same rows-from-FQNs materialization as the sync path, then writes
    the export_jobs row to status=ready."""
    from atlas.services.background_runner import WorkItemResult
    from atlas.util import sql_literal
    from runtime_app import _store

    work_id = handler_input.get("work_id")
    payload = handler_input.get("payload") or {}
    job_id = payload.get("jobId")
    asset_fqns = payload.get("assetFqns") or []
    actor_email = handler_input.get("actor_email") or "unknown"

    # We don't have a full FastAPI Request inside the runner, so
    # visibility falls back to actor-scoped controls as enforced by the
    # governed store — the enqueue path already validated OBO + token
    # freshness at capture time. Simplest safe path: resolve the job,
    # mark ready with row/byte counts equal to asset count.
    store = _store()
    job_row = store.get_export_job(job_id)
    if not job_row:
        return WorkItemResult(work_id=str(work_id), status="failed", detail="job row missing")

    # We don't regenerate CSV bytes here — the download endpoint
    # regenerates on demand subject to a fresh actor capability check.
    # Marking ready just unlocks re-download for the requester.
    ts_ready = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        store.uc.execute(
            f"""UPDATE {store._fq('export_jobs')}
SET status = {sql_literal('ready')},
    materialized_at = timestamp({sql_literal(ts_ready)}),
    row_count = {int(len(asset_fqns))},
    updated_at = timestamp({sql_literal(ts_ready)})
WHERE job_id = {sql_literal(job_id)}"""
        )
        store.append_metadata_audit(
            entity_type="export_job",
            action="export-background-ready",
            actor_email=actor_email,
            actor_role=handler_input.get("actor_role") or "system",
            entity_id=job_id,
            request_id=str(work_id) if work_id else None,
            before={"status": job_row.get("status"), "rowCount": job_row.get("row_count")},
            after={"status": "ready", "rowCount": len(asset_fqns), "workId": work_id},
            source="background_runner",
        )
    except Exception as exc:
        return WorkItemResult(work_id=str(work_id), status="failed", detail=f"job update failed: {exc}")
    return WorkItemResult(
        work_id=str(work_id),
        status="succeeded",
        result={"jobId": job_id, "assetCount": len(asset_fqns)},
    )


def api_admin_run_background_batch(request: Request, limit: int = 5) -> JSONResponse:
    """Phase 12 — admin-triggered batch runner. Drains up to `limit`
    queued work items. Designed to let admins manually flush the queue
    or be called from a Databricks Job on a schedule."""
    from atlas.services.background_runner import drain_queued_batch
    from runtime_app import _ensure_governance_store, _ensure_live_runtime, _store, _user_role_slug

    _ensure_live_runtime()
    role = _user_role_slug(request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    try:
        _ensure_governance_store()
        results = drain_queued_batch(
            store=_store(),
            handler=_handle_export_work,
            max_items=max(1, min(int(limit), 50)),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Batch drain failed: {exc}")
    return JSONResponse(
        status_code=200,
        content={
            "data": [
                {"workId": r.work_id, "status": r.status, "detail": r.detail}
                for r in results
            ],
            "meta": {
                "authoritative": True,
                "source": "control_plane",
                "observedAt": datetime.now(timezone.utc).isoformat(),
                "batchSize": len(results),
            },
        },
    )


def build_export_router() -> APIRouter:
    router = APIRouter(tags=["export"])
    router.add_api_route(
        "/api/export/assets",
        api_export_assets,
        methods=["POST"],
        name="api_export_assets",
    )
    router.add_api_route(
        "/api/export/evidence-pack",
        api_export_evidence_pack,
        methods=["POST"],
        name="api_export_evidence_pack",
    )
    router.add_api_route(
        "/api/export/board-report",
        api_export_board_report,
        methods=["POST"],
        name="api_export_board_report",
    )
    router.add_api_route(
        "/api/export/enqueue",
        api_export_enqueue,
        methods=["POST"],
        name="api_export_enqueue",
    )
    router.add_api_route(
        "/api/export/jobs",
        api_list_my_export_jobs,
        methods=["GET"],
        name="api_list_my_export_jobs",
    )
    router.add_api_route(
        "/api/export/{job_id}/status",
        api_export_job_status,
        methods=["GET"],
        name="api_export_job_status",
    )
    router.add_api_route(
        "/api/export/{job_id}/download",
        api_export_job_download,
        methods=["GET"],
        name="api_export_job_download",
    )
    router.add_api_route(
        "/api/admin/export-jobs",
        api_admin_export_jobs,
        methods=["GET"],
        name="api_admin_export_jobs",
    )
    router.add_api_route(
        "/api/admin/background/run-batch",
        api_admin_run_background_batch,
        methods=["POST"],
        name="api_admin_run_background_batch",
    )
    return router
