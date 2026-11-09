from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from axiom.api.identity import (
    _request_auth_mode,
    _request_read_visibility_scope,
    _user_display_name,
    _user_email,
)
from axiom.services.assets import normalize_str as _normalize_str


def _api_bootstrap_response(request: Request) -> JSONResponse:
    # Lazy-imported to avoid a circular import with runtime_app, which mounts
    # this router during its own module-load phase.
    from runtime_app import (
        _bootstrap_unavailable_payload,
        _shell_payload,
        _uc_runtime_status_fast,
    )

    try:
        runtime_status = _uc_runtime_status_fast()
        state = (
            "live"
            if runtime_status.get("state") == "live"
            else str(runtime_status.get("state") or "degraded")
        )
        message = (
            ""
            if state == "live"
            else runtime_status.get("message")
            or "Live Databricks metadata runtime is unavailable. Fix the warehouse access or runtime configuration, then retry."
        )
        return JSONResponse(
            _shell_payload(
                request,
                mode="route-bootstrap",
                state=state,
                message=message,
                runtime_status=runtime_status,
            )
        )
    except Exception as exc:
        return JSONResponse(
            _bootstrap_unavailable_payload(
                request,
                f"Workspace bootstrap failed: {_normalize_str(exc) or 'unknown error'}.",
                state="error",
            )
        )


def _api_runtime_status_response(request: Request) -> JSONResponse:
    # Non-blocking probe: on cold-start the serverless warehouse takes 60-120s
    # to return live, during which the UI used to show *no* diagnostics banner
    # at all. The auth-mode / workspaceAccess / identity payload is derived from
    # request headers and is available instantly, so returning "loading" runtime
    # state immediately lets the OBO / degraded banner surface within seconds.
    from runtime_app import (
        IDENTITY_SOURCE,
        _capabilities_payload,
        _config,
        _empty_inventory_boot_message,
        _fast_bootstrap_inventory_summary,
        _request_cache_scope,
        _runtime_diagnostics_payload,
        _store_status_fast,
        _uc_runtime_status_fast,
        _lightweight_user_role,
        _user_role,
    )

    runtime_status = _uc_runtime_status_fast()
    store_status = (
        _store_status_fast()
        if runtime_status.get("state") == "live"
        else {
            "state": "skipped",
            "message": "Governance store check skipped until the SQL runtime recovers.",
        }
    )
    summary = (
        _fast_bootstrap_inventory_summary(_request_cache_scope(request))
        if runtime_status.get("state") == "live"
        else {"visibleAssets": 0, "availableCatalogCount": 0, "observedCatalogCount": 0}
    )
    boot_message = ""
    if runtime_status.get("state") == "live":
        if store_status.get("state") != "live":
            boot_message = _normalize_str(store_status.get("message"))
        elif int(summary.get("visibleAssets") or 0) <= 0:
            boot_message = _empty_inventory_boot_message(summary)
    capabilities = _capabilities_payload(
        request,
        runtime_status=runtime_status,
        store_status=store_status,
        summary=summary,
        boot_message=boot_message,
    )
    actor_role = (
        _user_role(request)
        if store_status.get("state") == "live"
        else _lightweight_user_role(request)
    )
    payload = {
        "runtime": runtime_status,
        "store": store_status,
        "capabilities": capabilities,
        "config": {
            "warehouseId": _normalize_str(_config().warehouse_id),
            "govCatalog": _normalize_str(_config().gov_catalog),
            "govSchema": _normalize_str(_config().gov_schema),
            "adminEmailsConfigured": bool(_config().admin_emails),
        },
        "identity": {
            "actorEmail": _user_email(request),
            "actorName": _user_display_name(request),
            "actorRole": actor_role,
            "actorRoleProvisional": False,
            "authenticatedUserPresent": _user_email(request) != "unknown",
            "authMode": _request_auth_mode(request),
            "visibilityScope": _request_read_visibility_scope(request),
            "source": IDENTITY_SOURCE,
        },
        "diagnostics": _runtime_diagnostics_payload(
            request,
            runtime_status=runtime_status,
            store_status=store_status,
            summary=summary,
            capabilities=capabilities,
            boot_message=boot_message,
        ),
    }
    return JSONResponse(payload)


def build_runtime_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["runtime"])

    @router.get("/bootstrap")
    def api_bootstrap(request: Request) -> JSONResponse:
        return _api_bootstrap_response(request)

    @router.get("/runtime/status")
    def api_runtime_status(request: Request) -> JSONResponse:
        return _api_runtime_status_response(request)

    return router
