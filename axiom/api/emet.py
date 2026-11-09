"""emet Control Center API.

Read + command surface over the emet control plane (see
``axiom.services.emet``):

  GET  /api/emet/status                     detection + health
  GET  /api/emet/overview                   portfolio (jobs + rollup + fix-first)
  GET  /api/emet/runs/{run_id}              one run: summary + validations + checks
  GET  /api/emet/runs/{run_id}/live         live Databricks job-run status (polled)
  POST /api/emet/jobs/{job_id}/run          trigger a run (steward/admin, confirm)
  POST /api/emet/genie/start                start a Signal-Room Genie turn
  POST /api/emet/genie/poll                 poll a Signal-Room Genie turn

Reads run under the request's OBO client so results reflect the actor's Unity
Catalog grants; the trigger runs under the actor too, so a launched run is
attributed to the steward who pressed the button.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from axiom.util import error_text
from fastapi.responses import JSONResponse

from axiom.api.cache import _ttl_value
from axiom.api.response import _error_response, _with_meta
from axiom.services import emet as emet_service
from axiom.services import genie as genie_service
from axiom.services.assets import normalize_str as _normalize_str
from axiom.services.capabilities import APPROVAL_ROLES

SOURCE = emet_service.SOURCE


def _ensure_can_trigger(request: Request) -> str:
    """Gate the run trigger to stewards + admins (the 'open to all stewards'
    policy). Not a governance-store mutation, so we check the role directly
    instead of routing through the store-liveness mutation gate."""

    from runtime_app import _require_actor_email, _user_role_slug

    actor = _require_actor_email(request)
    role = _user_role_slug(request)
    if role not in APPROVAL_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Triggering a emet validation run requires steward or admin permissions.",
        )
    return actor


def api_emet_status(request: Request) -> JSONResponse:
    """Authoritative (OBO) emet detection + health for the surface header."""

    from runtime_app import _config, _request_cache_scope, _uc_for_request

    cfg = _config()
    if not bool(getattr(cfg, "emet_enabled", True)):
        return JSONResponse(
            _with_meta(
                {"detected": False, "status": emet_service._disabled_status()},
                request,
                source=SOURCE,
                state="unavailable",
                authoritative=False,
            )
        )

    uc = _uc_for_request(request)
    scope = _request_cache_scope(request)

    def _load() -> Dict[str, Any]:
        return emet_service.status(cfg, uc)

    try:
        status = _ttl_value(f"emet_status:{scope}", 30, _load)
    except Exception as exc:  # detection itself never raises, but be safe
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail=f"emet detection failed: {error_text(exc)}",
            state="unavailable",
        )

    detected = bool(status.get("detected"))
    state = "available" if detected and status.get("state") == "available" else (
        "degraded" if detected else "unavailable"
    )
    return JSONResponse(
        _with_meta(
            {"detected": detected, "status": status},
            request,
            source=SOURCE,
            state=state,
            authoritative=detected,
            capabilities={"emet": status.get("state", "unknown")},
        )
    )


def api_emet_overview(request: Request) -> JSONResponse:
    """Portfolio payload for the Overview + Jobs tabs."""

    from runtime_app import _config, _ensure_live_runtime, _request_cache_scope, _uc_for_request

    _ensure_live_runtime()
    cfg = _config()
    uc = _uc_for_request(request)
    scope = _request_cache_scope(request)

    def _load() -> Dict[str, Any]:
        return emet_service.overview(cfg, uc)

    try:
        overview = _ttl_value(f"emet_overview:{scope}", 30, _load)
    except Exception as exc:
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail=f"emet portfolio is unavailable: {error_text(exc)}",
            state="unavailable",
        )

    if not overview.get("detected"):
        return JSONResponse(
            _with_meta(
                overview,
                request,
                source=SOURCE,
                state="unavailable",
                authoritative=False,
                warnings=["emet was not detected on this workspace."],
            )
        )
    rollup = overview.get("rollup") or {}
    state = "degraded" if int(rollup.get("failingJobCount") or 0) > 0 else "available"
    return JSONResponse(
        _with_meta(overview, request, source=SOURCE, state=state, authoritative=True)
    )


def api_emet_run_detail(request: Request, run_id: int) -> JSONResponse:
    from runtime_app import _config, _ensure_live_runtime, _request_cache_scope, _uc_for_request

    _ensure_live_runtime()
    cfg = _config()
    uc = _uc_for_request(request)
    scope = _request_cache_scope(request)

    def _load() -> Dict[str, Any]:
        return emet_service.run_detail(cfg, uc, run_id)

    try:
        detail = _ttl_value(f"emet_run:{scope}:{int(run_id)}", 30, _load)
    except Exception as exc:
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail=f"emet run {run_id} is unavailable: {error_text(exc)}",
            state="unavailable",
        )
    if not detail.get("detected"):
        return _error_response(
            request,
            status_code=404,
            source=SOURCE,
            detail="emet is not detected on this workspace.",
            state="unavailable",
        )
    has_header = bool(detail.get("header"))
    return JSONResponse(
        _with_meta(
            detail,
            request,
            source=SOURCE,
            state="available" if has_header else "degraded",
            authoritative=True,
            warnings=None if has_header else [f"No run summary found for run {run_id}."],
        )
    )


def api_emet_run_live(request: Request, run_id: int) -> JSONResponse:
    """Live Databricks job-run status — never cached (the surface polls it)."""

    from runtime_app import _config, _ensure_live_runtime, _uc_for_request

    _ensure_live_runtime()
    cfg = _config()
    uc = _uc_for_request(request)
    try:
        live = emet_service.run_live_status(cfg, uc, run_id)
    except Exception as exc:
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail=f"Could not read run {run_id}: {error_text(exc)}",
            state="unavailable",
        )
    return JSONResponse(
        _with_meta(live, request, source=SOURCE, state="available", authoritative=True)
    )


def api_emet_trigger(
    request: Request,
    job_id: int,
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> JSONResponse:
    """Trigger a emet validation run (Jobs run-now). Steward/admin only;
    requires an explicit ``confirm: true`` so the click is deliberate."""

    from runtime_app import _config, _ensure_live_runtime, _request_cache_scope, _uc_for_request
    from axiom.api.cache import _ttl_cache_pop

    _ensure_live_runtime()
    actor = _ensure_can_trigger(request)

    payload = body or {}
    if not bool(payload.get("confirm")):
        raise HTTPException(
            status_code=422,
            detail="Confirmation is required to trigger a validation run.",
        )
    idempotency_token = _normalize_str(payload.get("idempotencyToken"))

    cfg = _config()
    uc = _uc_for_request(request)
    try:
        result = emet_service.trigger_run(
            cfg,
            uc,
            execution_job_id=job_id,
            idempotency_token=idempotency_token,
        )
    except Exception as exc:
        return _error_response(
            request,
            status_code=502,
            source=SOURCE,
            detail=f"Could not trigger the emet run: {error_text(exc)}",
            state="unavailable",
        )

    # The freshly launched run makes the cached portfolio stale — evict it so the
    # next overview poll reflects the in-flight run.
    try:
        _ttl_cache_pop(f"emet_overview:{_request_cache_scope(request)}")
    except Exception:
        pass

    result["triggeredBy"] = actor
    return JSONResponse(
        _with_meta(result, request, source=SOURCE, state="available", authoritative=True)
    )


def _emet_genie_space(cfg, uc) -> str:
    return _ttl_value(
        "emet_genie_space_id",
        300,
        lambda: emet_service.genie_space_id(cfg, uc),
    )


def api_emet_genie_start(
    request: Request,
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> JSONResponse:
    from runtime_app import _config, _ensure_live_runtime, _request_obo_token, _uc_for_request

    _ensure_live_runtime()
    question = _normalize_str((body or {}).get("question"))
    if not question:
        raise HTTPException(status_code=422, detail="question is required.")

    cfg = _config()
    token = _request_obo_token(request)
    if not token:
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail="The emet Signal Room requires the forwarded Databricks user token.",
            state="unavailable",
        )
    uc = _uc_for_request(request)
    space_id = _emet_genie_space(cfg, uc)
    if not space_id:
        return _error_response(
            request,
            status_code=404,
            source=SOURCE,
            detail="No emet Genie Signal Room is registered on this workspace.",
            state="unavailable",
        )
    try:
        started = genie_service.start_genie(
            config=cfg, question=question, user_access_token=token, space_id=space_id
        )
    except Exception as exc:
        return _error_response(
            request,
            status_code=502,
            source=SOURCE,
            detail=f"Could not reach the emet Signal Room: {error_text(exc)}",
            state="unavailable",
        )
    return JSONResponse(
        _with_meta(
            {**started, "spaceId": space_id, "question": question},
            request,
            source=SOURCE,
            state="pending",
            authoritative=False,
        )
    )


def api_emet_genie_poll(
    request: Request,
    body: Optional[Dict[str, Any]] = Body(default=None),
) -> JSONResponse:
    from runtime_app import _config, _ensure_live_runtime, _request_obo_token, _uc_for_request

    _ensure_live_runtime()
    payload = body or {}
    conversation_id = _normalize_str(payload.get("conversationId"))
    message_id = _normalize_str(payload.get("messageId"))
    if not conversation_id or not message_id:
        raise HTTPException(status_code=422, detail="conversationId and messageId are required.")

    cfg = _config()
    token = _request_obo_token(request)
    if not token:
        return _error_response(
            request,
            status_code=503,
            source=SOURCE,
            detail="The emet Signal Room requires the forwarded Databricks user token.",
            state="unavailable",
        )
    uc = _uc_for_request(request)
    space_id = _emet_genie_space(cfg, uc)
    try:
        result = genie_service.poll_genie(
            config=cfg,
            conversation_id=conversation_id,
            message_id=message_id,
            user_access_token=token,
            space_id=space_id,
        )
    except Exception as exc:
        return _error_response(
            request,
            status_code=502,
            source=SOURCE,
            detail=f"emet Signal Room did not complete: {error_text(exc)}",
            state="unavailable",
        )
    done = bool(result.get("done"))
    return JSONResponse(
        _with_meta(
            result,
            request,
            source=SOURCE,
            state="available" if done else "pending",
            authoritative=False,
        )
    )


def build_emet_router() -> APIRouter:
    router = APIRouter(tags=["emet"])
    router.add_api_route(
        "/api/emet/status", api_emet_status, methods=["GET"],
        response_class=JSONResponse, name="api_emet_status",
    )
    router.add_api_route(
        "/api/emet/overview", api_emet_overview, methods=["GET"],
        response_class=JSONResponse, name="api_emet_overview",
    )
    router.add_api_route(
        "/api/emet/runs/{run_id}", api_emet_run_detail, methods=["GET"],
        response_class=JSONResponse, name="api_emet_run_detail",
    )
    router.add_api_route(
        "/api/emet/runs/{run_id}/live", api_emet_run_live, methods=["GET"],
        response_class=JSONResponse, name="api_emet_run_live",
    )
    router.add_api_route(
        "/api/emet/jobs/{job_id}/run", api_emet_trigger, methods=["POST"],
        response_class=JSONResponse, name="api_emet_trigger",
    )
    router.add_api_route(
        "/api/emet/genie/start", api_emet_genie_start, methods=["POST"],
        response_class=JSONResponse, name="api_emet_genie_start",
    )
    router.add_api_route(
        "/api/emet/genie/poll", api_emet_genie_poll, methods=["POST"],
        response_class=JSONResponse, name="api_emet_genie_poll",
    )
    return router


__all__ = ["build_emet_router"]
