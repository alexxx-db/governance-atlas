"""Critical Data Element (CDE) registry endpoint.

Read-only: lists assets tagged as CDEs grouped by owning domain.
Write-back happens through the normal asset-metadata PATCH path
(AssetMetadataPatch.isCde / cdeRationale), not here.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from axiom.services import assets as asset_service


def build_cde_router() -> APIRouter:
    router = APIRouter(prefix="/api/cde", tags=["cde"])

    @router.get("")
    def api_cde_registry(
        request: Request,
        domains: Optional[List[str]] = Query(default=None),
    ) -> JSONResponse:
        """Return CDE-flagged assets grouped by domain.

        Visibility follows discovery's actor-scoping — a user only sees
        CDE rows for assets they can read. No separate role gate.
        """
        # Lazy import to avoid circular dependency with runtime_app.
        from runtime_app import _ensure_live_runtime, _visible_assets, HIDDEN_CATALOGS

        _ensure_live_runtime()
        payload = asset_service.cde_registry_payload(
            _visible_assets(request),
            domains=domains,
            hidden_catalogs=HIDDEN_CATALOGS,
        )
        return JSONResponse(payload)

    return router
