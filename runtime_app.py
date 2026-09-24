"""Governance Atlas application runtime."""

from __future__ import annotations

import html
import json
import logging
import math
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from atlas.util import error_text, redact_error_text
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from atlas.api import (
    build_admin_router,
    build_atlas_ai_router,
    build_atlas_router,
    build_assets_router,
    build_catalog_router,
    build_cde_router,
    build_classification_router,
    build_datapact_router,
    build_discovery_router,
    build_export_router,
    build_governance_router,
    build_insights_router,
    build_lineage_router,
    build_runtime_router,
)
from atlas.api.cache import (
    _CACHE_LOCK,
    _OBO_CLIENT_CACHE,
    _OBO_CLIENT_MAX_ENTRIES,
    _OBO_CLIENT_TTL_SECONDS,
    _TTL_CACHE,
    _invalidate_cache_prefix,
    _obo_token_key,
    _ttl_cache_pop,
    _ttl_value,
)
from atlas.api.identity import (
    _request_auth_mode,
    _request_obo_token,
    _request_read_visibility_scope,
    _user_display_name,
    _user_email,
)
from atlas.api.response import (
    _error_response,
    _future_iso,
    _now_iso,
    _request_scope_warning,
    _response_meta,
    _with_meta,
)
from atlas.config import AppConfig
from atlas.runtime_contract import validate_frontend_bundle
from atlas.services import approvals as approval_service
from atlas.services import assets as asset_service
from atlas.services import capabilities as capability_service
from atlas.services import datapact as datapact_service
from atlas.services import genie as genie_service
from atlas.services import governance as governance_service
from atlas.services import lakebase as lakebase_service
from atlas.services import lakebase_store as lakebase_store_service
from atlas.services import lineage as lineage_service
from atlas.services import runtime_setup as runtime_setup_service
from atlas.store import GovernanceStore
from atlas.uc import UCSQLClient, _is_skippable_metadata_error, is_missing_sql_scope_error


ROOT = Path(__file__).resolve().parent
REACT_DIST_DIR = ROOT / "frontend" / "dist"
HIDDEN_CATALOGS = {"hive_metastore", "samples", "system", "__databricks_internal"}
KNOWN_SURFACES = {
    "admin",
    "audit",
    "capabilities",
    "cde",
    "discovery",
    "entity",
    "governance",
    "help",
    "home",
    "inbox",
    "insights",
    "lineage",
    "taxonomy",
}
CLIENT_ROUTE_PREFIXES = {
    "admin",
    "audit",
    "audit-evidence",
    "capabilities",
    "cde",
    "cdes",
    "command-center",
    "control-center",
    "discover",
    "discovery",
    "entity",
    "governance",
    "glossary",
    "glossary-cdes",
    "help",
    "home",
    "inbox",
    "insights",
    "lineage",
    "lineage-atlas",
    "stewardship",
    "taxonomy",
    # Cohesion-rebuild canonical routes (Wave B): the SPA shell must serve
    # these with HTTP 200 — /assets/<fqn> 404'd at the document level while
    # the client still rendered, breaking crawlability/deep-link semantics.
    "asset",
    "assets",
    "evidence",
    "exec",
    "sk",
    # DataPact Control Center (nav/routes.js surface "datapact") + its aliases,
    # so hard-loads / deep links to the surface get the SPA shell, not a 404.
    "datapact",
    "data-pact",
    "data-quality",
    "quality-gate",
}
MUTATION_ROLES = {"writer", "steward", "admin"}
APPROVAL_ROLES = {"steward", "admin"}
APP_VERSION = "atlas-runtime-6"
REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_REQUEST_ID_HEADER = "X-GOVAT-Client-Request-ID"
BUILD_ID_HEADER = "X-GOVAT-Build-ID"
DURATION_HEADER = "X-GOVAT-Request-Duration-Ms"

LOGGER = logging.getLogger("atlas.runtime")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(
    getattr(
        logging,
        (os.getenv("GOVAT_LOG_LEVEL") or "INFO").strip().upper(),
        logging.INFO,
    )
)
LOGGER.propagate = False


@lru_cache(maxsize=1)
def _frontend_bundle_metadata() -> Dict[str, Any]:
    return validate_frontend_bundle(ROOT)


HELP_ITEMS = [
    {
        "title": "Discovery",
        "body": "Search, facet, and open the most relevant asset directly from the result rail.",
    },
    {
        "title": "Lineage",
        "body": "Inspect real upstream and downstream dependencies through a graph workspace instead of static cards.",
    },
    {
        "title": "Governance",
        "body": "Keep ownership, glossary, certification, and request state close to the metadata itself.",
    },
]

DISCOVERY_VIEWS = [
    "All assets",
    "Needs attention",
    "Needs owner",
    "Needs certification",
    "Certified",
    "High coverage",
]
DISCOVERY_SORTS = [
    "Best match",
    # D9: honest label — this sort orders by the 35/20/15/15/15 governance
    # metadata formula (coverageScore), which is not a trust measure. The
    # backend still accepts the legacy "Trust score" value for old clients.
    "Governance score",
    "Recently updated",
    "Name (A-Z)",
    "Open requests",
]
IDENTITY_SOURCE = "x-forwarded-email | x-forwarded-preferred-username"
SHELL_API_CONTRACT = {
    "bootstrap": "/api/bootstrap",
    "discoverySearch": "/api/discovery/search",
    "assetDetail": "/api/assets/:fqn",
    "assetAvailability": "/api/assets/availability",
    "assetHeaders": "/api/assets/headers",
    "assetMetadataUpdate": "/api/assets/:fqn/metadata",
    "assetColumnMetadataUpdate": "/api/assets/:fqn/columns/:column/metadata",
    "lineage": "/api/lineage/:fqn",
    "glossary": "/api/governance/glossary",
    "governanceRequest": "/api/governance/requests/:id",
    "governanceNotification": "/api/governance/notifications/:id",
    "governanceGlossaryTerm": "/api/governance/glossary/:id",
    "runtimeStatus": "/api/runtime/status",
    "adminBackgroundStatus": "/api/admin/background/status",
    "commandCenter": "/api/atlas/command-center",
    "asset360": "/api/atlas/assets/{asset_fqn}/360",
    "governanceWorkbench": "/api/atlas/governance/workbench",
    "governanceRequestDetail": "/api/atlas/governance/requests/{request_id}",
    "insightsDashboard": "/api/atlas/insights",
    "taxonomyOverview": "/api/atlas/taxonomy/overview",
    "cdeDashboard": "/api/atlas/cde",
    "cdeDetail": "/api/atlas/cde/{cde_id}",
    "auditEvidence": "/api/atlas/audit/evidence",
    "adminControlCenter": "/api/atlas/admin/control-center",
    "atlasAiRecommendations": "/api/atlas-ai/recommendations",
    "atlasAiMessage": "/api/atlas-ai/message",
    "atlasAiAutofill": "/api/atlas-ai/autofill",
    "atlasAiChat": "/api/atlas-ai/chat",
    "cdeRegistry": "/api/cde",
    "bulkImportDryRun": "/api/admin/bulk-import/dry-run",
    "bulkImportCommit": "/api/admin/bulk-import/commit",
    "adminCoverage": "/api/admin/coverage",
    "adminCoverageDrilldown": "/api/admin/coverage/drilldown",
    "adminBranding": "/api/admin/branding",
}


@asynccontextmanager
async def _runtime_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _warmup_live_runtime()
    _start_background_drainer()
    try:
        yield
    finally:
        _stop_background_drainer()


app = FastAPI(title="Governance Atlas Runtime", lifespan=_runtime_lifespan)
# Static assets shipped 464kB where 151kB gzip would; the bundle is served by
# this process directly (no CDN in Databricks Apps), so compress here.
app.add_middleware(GZipMiddleware, minimum_size=1024)


class _HashedAssetStaticFiles(StaticFiles):
    """Vite content-hashes every filename under /assets, so responses are
    immutable — without this header every navigation revalidates each chunk.

    The mount path also collides with the SPA's canonical asset-hub route
    (/assets/<fqn>): StaticFiles matches before the catch-all, so hub deep
    links 404'd at the document level. An extensionless miss is a page
    navigation, never a chunk request — serve the SPA shell for those.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    async def get_response(self, path: str, scope):  # type: ignore[override]
        # Starlette RAISES HTTPException(404) on a miss (it does not return a
        # 404 response), so the fall-through must catch, not status-check —
        # and it raises STARLETTE's HTTPException, which fastapi.HTTPException
        # (a subclass) does not catch.
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Asset FQNs are dotted (catalog.schema.table), so "has a dot"
            # cannot distinguish a page from a chunk — only misses that end
            # in a real static-file extension stay 404.
            static_ext = (".js", ".css", ".map", ".png", ".svg", ".ico", ".woff", ".woff2", ".txt", ".json")
            if exc.status_code == 404 and not path.lower().endswith(static_ext):
                return HTMLResponse(_render_index())
            raise


app.mount(
    "/assets",
    _HashedAssetStaticFiles(directory=str(REACT_DIST_DIR / "assets"), check_dir=False),
    name="react-assets",
)


_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@app.middleware("http")
async def cross_site_write_guard(request: Request, call_next):
    """CSRF guard: refuse state-changing API calls a browser marks as coming
    from another site. Sec-Fetch-Site is set by the browser and can't be forged
    by page script. Other *.databricksapps.com apps are "same-site", so that is
    refused too. Non-browser clients (no header) are unaffected."""
    if request.method in _STATE_CHANGING_METHODS and request.url.path.startswith("/api/"):
        if request.headers.get("sec-fetch-site", "").lower() in {"cross-site", "same-site"}:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "cross_site_request", "message": "Cross-site requests are not allowed."}},
            )
    return await call_next(request)


@app.middleware("http")
async def request_diagnostics_middleware(request: Request, call_next):
    request_id = (
        request.headers.get(CLIENT_REQUEST_ID_HEADER)
        or request.headers.get(REQUEST_ID_HEADER)
        or uuid.uuid4().hex
    ).strip() or uuid.uuid4().hex
    request.state.http_request_id = request_id
    request.state.request_started_at = time.time()
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        _log_request_event(
            request,
            status_code=500,
            duration_ms=duration_ms,
            outcome="unhandled_exception",
            error_type=exc.__class__.__name__,
            error_detail=str(exc)[:500],
        )
        raise
    duration_ms = (time.perf_counter() - started_at) * 1000.0
    _set_response_diagnostics_headers(response, request_id, duration_ms)
    _log_request_event(
        request,
        status_code=response.status_code,
        duration_ms=duration_ms,
        outcome=(
            "server_error"
            if response.status_code >= 500
            else "client_error"
            if response.status_code >= 400
            else "success"
        ),
    )
    return response


class _NullGovernanceStore:
    def list_owner_assignments(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "uc_full_name",
                "owner_email",
                "owner_type",
                "updated_at",
                "updated_by",
            ]
        )

    def list_change_requests(
        self, status: Optional[str] = None, limit: int = 200
    ) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "request_id",
                "created_at",
                "created_by",
                "status",
                "uc_full_name",
                "new_comment",
                "review_note",
            ]
        )

    def list_glossary_terms(self, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame(columns=["term_id", "name", "definition"])

    def list_glossary_reviewers(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "term_id",
                "reviewer_email",
                "reviewer_role",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by",
            ]
        )

    def list_glossary_versions(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "version_id",
                "term_id",
                "version_number",
                "action",
                "change_note",
                "name",
                "definition",
                "domain",
                "owner_email",
                "status",
                "reviewer_snapshot_json",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by",
            ]
        )

    def list_glossary_term_links(self, **_: Any) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "link_id",
                "term_id",
                "term_name",
                "subject_type",
                "subject_fqn",
                "column_name",
                "is_primary",
                "source",
                "source_value",
                "resolution_state",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by",
                "removed_at",
                "removed_by",
            ]
        )

    def list_metadata_audit(self, **_: Any) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "audit_id",
                "entity_type",
                "entity_id",
                "entity_fqn",
                "column_name",
                "action",
                "source",
                "status",
                "before_json",
                "after_json",
                "request_id",
                "actor_email",
                "actor_role",
                "detail",
                "created_at",
                "created_by",
                "updated_at",
                "updated_by",
            ]
        )

    def list_metadata_audit_log(self, **_: Any) -> pd.DataFrame:
        return self.list_metadata_audit(**_)

    def get_role(self, email: str, admin_emails: Optional[List[str]] = None) -> str:
        normalized = str(email or "").strip().lower()
        configured_admins = {str(item or "").strip().lower() for item in (admin_emails or []) if str(item or "").strip()}
        if normalized and normalized in configured_admins:
            LOGGER.warning(
                "admin_emails_fallback_promotion store=null email=%s "
                "(honoring GOVAT_ADMIN_EMAILS while governance store is unreachable)",
                normalized,
            )
            return "admin"
        return "reader"


_normalize_str = asset_service.normalize_str
_split_uc_name = asset_service.split_uc_name
_catalog_filter_options = asset_service.catalog_filter_options


@lru_cache(maxsize=1)
def _config() -> AppConfig:
    return AppConfig.from_env()


@lru_cache(maxsize=1)
def _uc() -> UCSQLClient:
    return UCSQLClient(warehouse_id=_config().warehouse_id)


def _uc_for_token(user_access_token: str) -> UCSQLClient:
    token = (user_access_token or "").strip()
    if not token:
        return _uc()
    key = _obo_token_key(token)
    now = time.time()
    cached = _OBO_CLIENT_CACHE.get(key)
    if cached and now - cached[0] < _OBO_CLIENT_TTL_SECONDS:
        return cached[1]
    client = UCSQLClient(
        warehouse_id=_config().warehouse_id,
        user_access_token=token,
    )
    with _CACHE_LOCK:
        _OBO_CLIENT_CACHE[key] = (now, client)
        if len(_OBO_CLIENT_CACHE) > _OBO_CLIENT_MAX_ENTRIES:
            cutoff = now - _OBO_CLIENT_TTL_SECONDS
            for stale_key in [k for k, v in _OBO_CLIENT_CACHE.items() if v[0] < cutoff]:
                _OBO_CLIENT_CACHE.pop(stale_key, None)
    return client


_REAUTH_DETAIL = (
    "Your Databricks sign-in for this app predates a permission it now needs. "
    "Sign out of the app and sign back in, then retry."
)


class _UserScopedUC:
    """Per-user (OBO) UC client that never falls back to the app principal.

    Users who signed in before an OBO scope (e.g. ``sql``) was granted carry
    tokens without it; the warehouse rejects them with ``403 Invalid scope,
    required scopes: sql`` and the SDK surfaces that as an opaque parse error.
    We used to retry such calls on the app service principal, which served
    one principal's view of Unity Catalog to every user (confused deputy).
    Now the error becomes an explicit re-authorize 403 instead.
    """

    __slots__ = ("_client",)

    def __init__(self, client: UCSQLClient) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return attr(*args, **kwargs)
            except Exception as exc:
                if is_missing_sql_scope_error(exc):
                    raise HTTPException(status_code=403, detail=_REAUTH_DETAIL) from exc
                raise

        return _wrapped


def _uc_for_request(request: Optional[Request]) -> UCSQLClient:
    """UC client for this request: the signed-in user's when a forwarded
    token is present, else the app principal (apps deployed without OBO)."""
    token = _request_obo_token(request)
    if not token:
        return _uc()
    try:
        obo_client = _uc_for_token(token)
    except Exception as exc:
        logging.getLogger(__name__).warning("OBO client construction failed: %s", type(exc).__name__)
        raise HTTPException(status_code=403, detail=_REAUTH_DETAIL) from exc
    return _UserScopedUC(obo_client)  # type: ignore[return-value]


@lru_cache(maxsize=1)
def _store() -> GovernanceStore:
    cfg = _config()
    store = GovernanceStore(uc=_uc(), catalog=cfg.gov_catalog, schema=cfg.gov_schema)
    store.ensure_tables()
    if getattr(cfg, "lakebase_enabled", False):
        try:
            lakebase_service.ensure_schema(cfg, include_upgrades=False)
            mirror = lakebase_store_service.LakebaseOperationalMirror(
                config=cfg,
                delta_store=store,
            )
            return lakebase_store_service.DualWriteGovernanceStore(store, mirror)  # type: ignore[return-value]
        except Exception as exc:
            message = f"{error_text(exc)}"
            lakebase_store_service.record_inactive_status(
                f"Lakebase dual-write mirror is inactive: {message}",
                state="degraded",
            )
            logging.getLogger(__name__).warning("Lakebase dual-write mirror inactive: %s", exc)
    return store


def _format_runtime_message(exc: Exception) -> str:
    return error_text(exc)


def _uc_runtime_status() -> Dict[str, Any]:
    def _loader() -> Dict[str, Any]:
        try:
            uc = _uc()
            catalogs = uc.list_catalogs()
            return {
                "state": "live",
                "message": "",
                "catalogCount": int(len(catalogs.index))
                if isinstance(catalogs, pd.DataFrame)
                else 0,
                "client": uc.runtime_context(),
            }
        except Exception as exc:
            return {
                "state": "unavailable",
                "message": _format_runtime_message(exc)
                or "Live Databricks metadata runtime is unavailable.",
                "errorType": exc.__class__.__name__,
                "client": _uc().runtime_context() if _uc.cache_info().currsize else {},
            }

    return _ttl_value("runtime_uc_status", 300, _loader)


_UC_STATUS_WARMING = False


def _uc_runtime_status_fast(background: bool = True) -> Dict[str, Any]:
    """Non-blocking variant for bootstrap: return cached value if fresh, else an
    optimistic "warming" payload and kick the real probe off in the background.

    Serverless SQL warehouses can take 60–120 seconds to cold start. Blocking the
    shell bootstrap on that probe makes the entire UI appear unresponsive for
    minutes on first load. The honest per-surface status is still delivered via
    /api/runtime/status, so we never lie to the user about actual capabilities.
    """
    cached = _TTL_CACHE.get("runtime_uc_status")
    now = time.time()
    if cached and now - cached[0] < 300:
        return cached[1]
    if background:
        global _UC_STATUS_WARMING
        should_start = False
        with _CACHE_LOCK:
            if not _UC_STATUS_WARMING:
                _UC_STATUS_WARMING = True
                should_start = True
        if should_start:
            def warm_runtime_status() -> None:
                global _UC_STATUS_WARMING
                try:
                    _uc_runtime_status()
                finally:
                    with _CACHE_LOCK:
                        _UC_STATUS_WARMING = False

            thread = threading.Thread(target=warm_runtime_status, daemon=True)
            thread.daemon = True
            thread.start()
    return {
        "state": "loading",
        "message": (
            "Warming the Databricks SQL warehouse. Serverless warehouses take 30–90 "
            "seconds to start after idle; capabilities will hydrate automatically."
        ),
        "catalogCount": 0,
        "client": _uc().runtime_context() if _uc.cache_info().currsize else {},
    }


def _store_status() -> Dict[str, str]:
    def _loader() -> Dict[str, str]:
        try:
            store = _store()
            payload: Dict[str, Any] = {"state": "live", "message": ""}
            if hasattr(store, "lakebase_dual_write_status"):
                payload["lakebaseDualWrite"] = store.lakebase_dual_write_status()
            return payload
        except Exception as exc:
            return {
                "state": "degraded",
                "message": _normalize_str(exc)
                or "Governance control plane is unavailable; falling back to read-only metadata.",
            }

    return _ttl_value("runtime_store_status", 60, _loader)


_STORE_STATUS_WARMING = False


def _store_status_fast(background: bool = True) -> Dict[str, str]:
    cached = _TTL_CACHE.get("runtime_store_status")
    now = time.time()
    if cached and now - cached[0] < 60:
        return cached[1]
    if background:
        global _STORE_STATUS_WARMING
        should_start = False
        with _CACHE_LOCK:
            if not _STORE_STATUS_WARMING:
                _STORE_STATUS_WARMING = True
                should_start = True

        if should_start:
            def warm_store_status() -> None:
                global _STORE_STATUS_WARMING
                try:
                    _store_status()
                finally:
                    with _CACHE_LOCK:
                        _STORE_STATUS_WARMING = False

            threading.Thread(
                target=warm_store_status,
                name="atlas-store-status-warmup",
                daemon=True,
            ).start()
    return {
        "state": "loading",
        "message": "Governance store health is warming; status will hydrate automatically.",
    }


def _store_for_read() -> GovernanceStore | _NullGovernanceStore:
    status = _store_status()
    if status["state"] == "live":
        return _store()
    return _NullGovernanceStore()


def _safe_unquote(value: str) -> str:
    try:
        return unquote(value)
    except Exception:
        return value


def _route_context(request: Request) -> Dict[str, str]:
    params = request.query_params
    requested_asset = _normalize_str(params.get("asset"))
    requested_surface = _normalize_str(params.get("surface"))
    requested_module = _normalize_str(params.get("module"))
    discovery_query = _normalize_str(params.get("q"))
    segments = [segment for segment in request.url.path.split("/") if segment]
    if segments:
        root = _normalize_str(segments[0]).lower()
        remainder = _safe_unquote("/".join(segments[1:]))
        if root == "discovery":
            requested_surface = "discovery"
            requested_asset = ""
        elif root == "entity" and remainder:
            requested_surface = "entity"
            requested_asset = remainder
        elif root == "lineage" and remainder:
            requested_surface = "lineage"
            requested_asset = remainder
        elif root in {"governance", "glossary"}:
            requested_surface = "governance"
        elif root in {"admin", "audit", "capabilities", "cde", "cdes", "help", "home", "inbox", "insights", "taxonomy"}:
            requested_surface = "cde" if root == "cdes" else root
            requested_asset = ""
    if requested_surface not in KNOWN_SURFACES:
        requested_surface = (
            requested_module if requested_module in KNOWN_SURFACES else ""
        )
    if requested_surface == "discovery":
        requested_asset = ""
    return {
        "surface": requested_surface or "discovery",
        "asset": requested_asset,
        "query": discovery_query,
    }


def _user_role_slug(request: Optional[Request]) -> str:
    email = _user_email(request)
    if email == "unknown":
        return "reader"

    def load_role() -> str:
        store = _store_for_read()
        admin_emails = _config().admin_emails
        try:
            role = store.get_role(email, admin_emails=admin_emails)
        except Exception:
            normalized = email.strip().lower()
            if normalized and any(
                normalized == (admin_email or "").strip().lower()
                for admin_email in admin_emails
            ):
                return "admin"
            return "reader"
        return (role or "reader").strip().lower() or "reader"

    return _ttl_value(f"runtime_user_role:{email.lower()}", 60, load_role)


def _user_role(request: Optional[Request]) -> str:
    return _user_role_slug(request).title()


def _lightweight_user_role_slug(request: Optional[Request]) -> str:
    email = _user_email(request)
    if email == "unknown":
        return "reader"
    admin_emails = {item.strip().lower() for item in _config().admin_emails if item}
    if email in admin_emails:
        return "admin"
    return "reader"


def _lightweight_user_role(request: Optional[Request]) -> str:
    return _lightweight_user_role_slug(request).title()


def _http_request_id(request: Optional[Request]) -> str:
    if request is None:
        return ""
    request_id = getattr(getattr(request, "state", None), "http_request_id", "")
    if request_id:
        return str(request_id).strip()
    return (
        request.headers.get(CLIENT_REQUEST_ID_HEADER)
        or request.headers.get(REQUEST_ID_HEADER)
        or ""
    ).strip()


def _build_id() -> str:
    return _config().build_id or str(
        _frontend_bundle_metadata().get("buildId") or APP_VERSION
    )


def _set_response_diagnostics_headers(
    response, request_id: str, duration_ms: float
) -> None:
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[BUILD_ID_HEADER] = _build_id()
    response.headers[DURATION_HEADER] = f"{duration_ms:.1f}"
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"


def _log_request_event(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    outcome: str,
    error_type: str = "",
    error_detail: str = "",
) -> None:
    if not _config().diagnostics_enabled:
        return
    path = str(request.url.path)
    if path.startswith("/assets/"):
        return
    route = _route_context(request)
    payload = {
        "event": "http_request",
        "httpRequestId": _http_request_id(request),
        "clientRequestId": (request.headers.get(CLIENT_REQUEST_ID_HEADER) or "").strip(),
        "buildId": _build_id(),
        "method": request.method,
        "path": path,
        "surface": route.get("surface") or "",
        "asset": route.get("asset") or "",
        "actorEmail": _user_email(request),
        "statusCode": int(status_code),
        "durationMs": round(float(duration_ms), 1),
        "outcome": outcome,
        "slow": bool(duration_ms >= max(0, _config().slow_request_ms)),
    }
    if error_type:
        payload["errorType"] = error_type
    if error_detail:
        payload["errorDetail"] = error_detail
    LOGGER.info(json.dumps(payload, sort_keys=True))


def _require_actor_email(request: Request) -> str:
    actor_email = _user_email(request)
    if actor_email == "unknown":
        raise HTTPException(
            status_code=401,
            detail="A forwarded Databricks user identity is required for metadata mutations.",
        )
    return actor_email


def _ensure_can_mutate(request: Request) -> str:
    _ensure_governance_store()
    actor_email = _require_actor_email(request)
    actor_role = _user_role_slug(request)
    if actor_role not in MUTATION_ROLES:
        raise HTTPException(
            status_code=403,
            detail="This action requires writer, steward, or admin permissions.",
        )
    return actor_email


def _ensure_can_approve(request: Request) -> str:
    _ensure_governance_store()
    actor_email = _require_actor_email(request)
    actor_role = _user_role_slug(request)
    if actor_role not in APPROVAL_ROLES:
        raise HTTPException(
            status_code=403,
            detail="This action requires steward or admin permissions.",
        )
    return actor_email


def _direct_uc_metadata_writes_enabled(request: Optional[Request]) -> bool:
    return _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE


def _ensure_can_mutate_uc_metadata(request: Request) -> str:
    actor_email = _ensure_can_mutate(request)
    if not _direct_uc_metadata_writes_enabled(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "Direct Unity Catalog metadata writes stay disabled until Databricks per-user authorization / "
                "OBO is implemented and verified for the current actor."
            ),
        )
    return actor_email


def _request_cache_scope(request: Optional[Request]) -> str:
    email = _normalize_str(_user_email(request))
    base = email if email and email != "unknown" else "anonymous"
    # Separate cache buckets per auth mode so OBO-scoped reads never share storage
    # with app-principal-scoped reads — they return materially different row sets
    # for the same actor, and cross-pollution would silently widen user-visible data.
    mode = (
        _request_auth_mode(request)
        if request is not None
        else capability_service.NO_IDENTITY_MODE
    )
    return f"{base}|{mode}"


def _capabilities_payload(
    request: Optional[Request],
    *,
    runtime_status: Optional[Dict[str, Any]] = None,
    store_status: Optional[Dict[str, Any]] = None,
    summary: Optional[Dict[str, Any]] = None,
    boot_message: str = "",
) -> Dict[str, Dict[str, Any]]:
    resolved_runtime_status = runtime_status or _uc_runtime_status()
    resolved_store_status = store_status or (
        _store_status()
        if resolved_runtime_status.get("state") == "live"
        else {
            "state": "skipped",
            "message": "Governance store check skipped until the SQL runtime recovers.",
        }
    )
    resolved_summary = summary or {}
    actor_role_slug = (
        _lightweight_user_role_slug(request)
        if request is not None and _normalize_str(resolved_store_status.get("state")) != "live"
        else (_user_role_slug(request) if request is not None else "reader")
    )
    return capability_service.bootstrap_capabilities(
        actor_role=actor_role_slug,
        authenticated=_user_email(request) != "unknown"
        if request is not None
        else False,
        runtime_state=_normalize_str(resolved_runtime_status.get("state"))
        or "unavailable",
        runtime_message=_normalize_str(resolved_runtime_status.get("message")),
        store_state=_normalize_str(resolved_store_status.get("state")) or "unknown",
        store_message=_normalize_str(resolved_store_status.get("message")),
        visible_asset_count=int(resolved_summary.get("visibleAssets") or 0),
        available_catalog_count=int(resolved_summary.get("availableCatalogCount") or 0),
        observed_catalog_count=int(resolved_summary.get("observedCatalogCount") or 0),
        boot_message=boot_message,
        per_user_authorization=bool(_request_obo_token(request)),
    )


def _runtime_setup_checks_payload(
    setup: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return list(setup.get("checks") or [])


def _runtime_diagnostics_payload(
    request: Optional[Request],
    *,
    runtime_status: Dict[str, Any],
    store_status: Dict[str, Any],
    summary: Dict[str, Any],
    capabilities: Dict[str, Dict[str, Any]],
    boot_message: str = "",
) -> Dict[str, Any]:
    actor_role_slug = (
        _lightweight_user_role_slug(request)
        if request is not None and _normalize_str(store_status.get("state")) != "live"
        else _user_role_slug(request)
    )
    setup = runtime_setup_service.setup_payload(
        runtime_status=runtime_status,
        store_status=store_status,
        capabilities=capabilities,
        warehouse_id=_config().warehouse_id,
        gov_catalog=_config().gov_catalog,
        gov_schema=_config().gov_schema,
        authenticated=_user_email(request) != "unknown",
        actor_role=actor_role_slug,
        diagnostics_enabled=_config().diagnostics_enabled,
        per_user_authorization=bool(_request_obo_token(request)),
    )
    return {
        "buildId": _build_id(),
        "diagnosticsEnabled": _config().diagnostics_enabled,
        "slowRequestMs": _config().slow_request_ms,
        "httpRequestId": _http_request_id(request),
        "headers": {
            "requestId": REQUEST_ID_HEADER,
            "clientRequestId": CLIENT_REQUEST_ID_HEADER,
            "buildId": BUILD_ID_HEADER,
            "durationMs": DURATION_HEADER,
            "serverTiming": "Server-Timing",
        },
        "observedAt": setup.get("observedAt", ""),
        "staleAfter": setup.get("staleAfter", ""),
        "setupSummary": setup.get("summary", {}),
        "setupReadiness": setup.get("readiness", {}),
        "setupSequence": list(setup.get("setupSequence") or []),
        "workspaceAccess": setup.get("workspaceAccess", {}),
        "setupChecks": _runtime_setup_checks_payload(setup),
        "featureFlags": list(setup.get("featureFlags") or []),
        "auth": setup.get("auth", {}),
        "bootMessage": boot_message,
    }


from atlas.services.inventory import (
    asset_exists as _asset_exists,
    asset_is_openable as _asset_is_openable,
    asset_is_visible as _asset_is_visible,
    cached_visible_assets as _cached_visible_assets,
    inventory as _inventory,
    inventory_catalogs as _inventory_catalogs,
    inventory_row as _inventory_row,
    lineage_observed_catalogs as _lineage_observed_catalogs,
    visible_assets as _visible_assets,
)


def _direct_actor_identity_visible(
    asset_fqn: str,
    request: Optional[Request] = None,
) -> bool:
    """Allow deep-linked read routes when actor-scoped identity resolves exactly.

    Bulk inventory can omit a table even when the forwarded actor can resolve
    that exact table through Unity Catalog information_schema. Treat that direct
    identity proof as openable only for real OBO requests, and reject it if the
    OBO SQL client fell back to the app principal so app-principal visibility
    cannot widen what the user can open.
    """
    if request is None:
        return False
    if _request_auth_mode(request) != capability_service.OBO_AVAILABLE_MODE:
        return False
    try:
        catalog, _, _ = asset_service.split_uc_name(asset_fqn)
    except Exception:
        return False
    hidden = {str(value).lower() for value in HIDDEN_CATALOGS}
    if catalog.lower() in hidden:
        return False
    if asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
        return False
    try:
        uc_client = _uc_for_request(request)
        exact_row = asset_service.exact_identity_row(uc_client, asset_fqn)
    except Exception:
        return False
    return exact_row is not None


def _direct_workspace_identity_visible(asset_fqn: str) -> bool:
    """Resolve exact UC identity for workspace-scoped app-principal reads.

    This is intentionally not actor-scoped proof. It only prevents a stale or
    still-hydrating bulk inventory cache from hiding a real table in the
    degraded app-principal product mode.
    """
    if asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
        return False
    try:
        exact_row = asset_service.exact_identity_row(_uc(), asset_fqn)
    except Exception:
        return False
    return exact_row is not None


def _asset_visibility_record(
    asset_fqn: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    try:
        actor_scoped = (
            _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
        )
        # P0 perf fix: consult the WARM inventory FIRST. Membership in the
        # actor-visible inventory IS the visibility answer, and it's a pure
        # in-memory frame scan. The previous order ran the per-asset
        # exact-identity probe (two information_schema queries) before ever
        # looking at the cache, taxing every asset-detail/lineage request
        # ~1.6s warm / 7.5s cold even for assets the inventory already
        # proved visible.
        cached_inventory = _cached_visible_assets(request)
        if cached_inventory is not None and asset_service.asset_is_visible(
            cached_inventory, asset_fqn
        ):
            return {
                "exists": True,
                "visible": True,
                "openable": True,
                "visibilityState": "visible",
                "visibilityMethod": "inventory",
            }
        # Not (or not yet) in the cached inventory: fall back to the direct
        # exact-identity probe (now TTL-cached + concurrent inside
        # exact_identity_row) so deep links to real-but-uninventoried tables
        # still open for actor-scoped requests.
        direct_visible = False
        if actor_scoped and not asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
            try:
                uc_client = _uc_for_request(request)
                exact_row = asset_service.exact_identity_row(uc_client, asset_fqn)
                direct_visible = exact_row is not None
            except Exception:
                direct_visible = False
        if direct_visible:
            return {
                "exists": True,
                "visible": True,
                "openable": True,
                "visibilityState": "visible",
                "visibilityMethod": "direct-identity",
            }
        if cached_inventory is None:
            _fast_bootstrap_inventory_summary(
                _request_cache_scope(request),
                start_background=True,
            )
            if not actor_scoped:
                if asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
                    return {
                        "exists": False,
                        "visible": False,
                        "openable": False,
                        "visibilityState": "missing",
                        "visibilityMethod": "inventory-loading",
                    }
                return {
                    "exists": False,
                    "visible": False,
                    "openable": False,
                    "visibilityState": "loading",
                    "visibilityMethod": "inventory-loading",
                    "reason": "Actor-visible inventory is hydrating from live Unity Catalog metadata.",
                }
            if not asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
                try:
                    fast_header = asset_service.asset_header_payload_from_exact_identity(
                        _uc_for_request(request),
                        _store_for_read(),
                        asset_fqn,
                        hidden_catalogs=HIDDEN_CATALOGS,
                    )
                except Exception:
                    fast_header = None
                if fast_header is not None:
                    return {
                        "exists": True,
                        "visible": True,
                        "openable": True,
                        "visibilityState": "visible",
                        "visibilityMethod": "direct-identity",
                    }
            if actor_scoped:
                exists = _asset_exists(asset_fqn, request)
                return {
                    "exists": exists,
                    "visible": False,
                    "openable": False,
                    "visibilityState": "hidden" if exists else "missing",
                    "visibilityMethod": "inventory",
                }
            return {
                "exists": False,
                "visible": False,
                "openable": False,
                "visibilityState": "missing",
                "visibilityMethod": "inventory-loading",
            }
        # Cached inventory exists but does NOT contain the asset, and the
        # actor-scoped direct probe above (if applicable) already failed.
        # Only the workspace-scoped direct-identity fallback remains for
        # non-OBO requests; re-running the actor probe here would repeat
        # the two identity queries the reorder above just eliminated.
        direct_visible = (
            False if actor_scoped else _direct_workspace_identity_visible(asset_fqn)
        )
        visible = direct_visible
        exists = visible or (actor_scoped and _asset_exists(asset_fqn, request))
        if visible:
            visibility_state = "visible"
        elif exists and actor_scoped:
            visibility_state = "hidden"
        else:
            visibility_state = "missing"
        return {
            "exists": exists,
            "visible": visible,
            "openable": visible,
            "visibilityState": visibility_state,
            "visibilityMethod": (
                "direct-identity"
                if direct_visible and actor_scoped
                else "workspace-direct-identity"
                if direct_visible
                else "inventory"
            ),
        }
    except Exception as exc:
        return {
            "exists": False,
            "visible": False,
            "openable": False,
            "visibilityState": "unknown",
            "reason": _normalize_str(exc)
            or "Asset visibility could not be determined.",
        }


def _invalidate_asset_caches(asset_fqn: str) -> None:
    asset_service.invalidate_asset_caches(asset_fqn)
    lineage_service.invalidate_lineage_caches(asset_fqn)
    governance_service.invalidate_governance_caches()
    _ttl_cache_pop(f"runtime_asset:{asset_fqn}")
    _ttl_cache_pop(f"runtime_lineage:{asset_fqn}")
    _invalidate_cache_prefix("runtime_inventory:")
    _invalidate_cache_prefix("runtime_bootstrap_inventory_summary:")
    _invalidate_cache_prefix("atlas_command_center_payload:")
    _invalidate_cache_prefix("atlas_governance_workbench_payload:")
    _invalidate_cache_prefix("atlas_governance_request_detail_payload:")
    _invalidate_cache_prefix("atlas_insights_dashboard_payload:")
    _invalidate_cache_prefix("atlas_cde_dashboard_payload:")
    _invalidate_cache_prefix("atlas_cde_detail_payload:")
    _invalidate_cache_prefix("atlas_audit_evidence_payload:")
    _ttl_cache_pop("runtime_governance")


def _safe_int(value: Any) -> int:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return 0
        return int(float(str(value).replace(",", "")))
    except Exception:
        return 0


from atlas.services.inventory import (
    inventory_option_counts as _inventory_option_counts,
)


def _discovery_search_payload(
    request: Optional[Request] = None,
    *,
    query: str = "",
    query_mode: str = "plain",
    views: Optional[List[str]] = None,
    asset_types: Optional[List[str]] = None,
    catalogs: Optional[List[str]] = None,
    domains: Optional[List[str]] = None,
    tiers: Optional[List[str]] = None,
    certifications: Optional[List[str]] = None,
    sensitivities: Optional[List[str]] = None,
    business_criticalities: Optional[List[str]] = None,
    cde_only: bool = False,
    sort_by: str = "Best match",
    limit: int = 60,
    offset: int = 0,
) -> Dict[str, Any]:
    return asset_service.discovery_search_payload(
        _visible_assets(request),
        query=query,
        query_mode=query_mode,
        views=views,
        asset_types=asset_types,
        catalogs=catalogs,
        domains=domains,
        tiers=tiers,
        certifications=certifications,
        sensitivities=sensitivities,
        business_criticalities=business_criticalities,
        cde_only=cde_only,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
        hidden_catalogs=HIDDEN_CATALOGS,
    )


def _asset_detail_payload(
    asset_fqn: str,
    request: Optional[Request] = None,
    *,
    sections: Optional[List[str]] = None,
) -> Dict[str, Any]:
    requested_sections = asset_service.normalize_asset_detail_sections(sections)
    # Fast-path: when the caller only wants `activity` (no header), serve from
    # cached inventory to avoid the DESCRIBE DETAIL / DESCRIBE HISTORY round
    # trips. We DO NOT take the fast-path when "header" is in the requested
    # sections — that path returns rows="—" / size="—" / no updatedAt and
    # never invokes the live UC enrichment that the full asset_detail_payload
    # adds (Delta history → updatedAt, DESCRIBE DETAIL → rows/size/files,
    # information_schema.tables → UC owner). Taking the fast-path for header
    # was the root cause of "everything Unavailable" for assets the user
    # could see populated in UC Catalog Explorer.
    if (
        set(requested_sections).issubset({"header", "activity"})
        and "header" not in requested_sections
    ):
        cached_inventory = _cached_visible_assets(request)
        fast_header = None
        if cached_inventory is not None:
            fast_header = asset_service.asset_header_payload_from_inventory(
                cached_inventory,
                asset_fqn,
            )
        if fast_header is None:
            fast_header = asset_service.asset_header_payload_from_exact_identity(
                _uc_for_request(request),
                _store_for_read(),
                asset_fqn,
                hidden_catalogs=HIDDEN_CATALOGS,
            )
        if fast_header is not None:
            _fast_bootstrap_inventory_summary(
                _request_cache_scope(request),
                start_background=True,
            )
            payload = dict(fast_header)
            if "activity" in requested_sections:
                store = _store_for_read()
                payload["ownerAssignments"] = asset_service.owner_assignment_records(
                    store,
                    asset_fqn,
                )
                payload["activity"] = asset_service.activity_records(store, asset_fqn)
                payload["metadataAudit"] = asset_service.metadata_audit_records(
                    store,
                    asset_fqn,
                )
            payload["loadedSections"] = list(requested_sections)
            payload["deferredSections"] = [
                section
                for section in asset_service.ASSET_DETAIL_SECTIONS
                if section not in requested_sections
            ]
            return payload
    return asset_service.asset_detail_payload(
        _uc_for_request(request),
        _store_for_read(),
        asset_fqn,
        cache_scope=_request_cache_scope(request),
        hidden_catalogs=HIDDEN_CATALOGS,
        sections=sections,
        allow_direct_metadata_write=_direct_uc_metadata_writes_enabled(request),
    )


from atlas.services.metadata_audit import (
    audit_asset_snapshot as _metadata_audit_asset_snapshot,
    audit_column_snapshot as _metadata_audit_column_snapshot,
    record_audit_log as _record_metadata_audit,
)


def _lineage_payload(
    asset_fqn: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    request_uc = _uc_for_request(request)
    profile = "full"
    try:
        profile = str(request.query_params.get("profile") or "full") if request else "full"
    except Exception:
        profile = "full"
    return lineage_service.lineage_payload(
        request_uc,
        _store_for_read(),
        asset_fqn,
        cache_scope=_request_cache_scope(request),
        system_uc=request_uc if actor_scoped else _uc(),
        profile=profile,
    )


def _governance_summary(
    request: Optional[Request] = None,
    *,
    sections: Sequence[str] | None = None,
) -> Dict[str, Any]:
    payload = governance_service.governance_summary(
        _uc_for_request(request),
        _store(),
        actor_email=_user_email(request),
        hidden_catalogs=HIDDEN_CATALOGS,
        sections=sections,
    )
    payload["authoritative"] = True
    payload["provenance"] = {
        "source": "delta_control_plane",
        "authoritative": True,
        "state": "live",
        "warnings": [],
    }
    return payload


from atlas.services.inventory import (
    bootstrap_inventory_summary as _bootstrap_inventory_summary,
    fast_bootstrap_inventory_summary as _fast_bootstrap_inventory_summary,
)


def _empty_inventory_boot_message(summary: Dict[str, Any]) -> str:
    if int(summary.get("visibleAssets") or 0) > 0:
        return ""
    available_catalog_count = int(summary.get("availableCatalogCount") or 0)
    observed_catalog_count = int(summary.get("observedCatalogCount") or 0)
    if available_catalog_count:
        return (
            f"The workspace can enumerate {available_catalog_count} catalog(s), but no visible tables or views "
            "were surfaced after filtering. Confirm the current principal can query Unity Catalog information_schema "
            "inventory for those catalogs."
        )
    if observed_catalog_count:
        return (
            f"Lineage system tables show activity in {observed_catalog_count} catalog(s), but direct catalog "
            "inventory could not be enumerated. Confirm SHOW CATALOGS and information_schema access for the current principal."
        )
    return (
        "The workspace connected successfully, but no visible metadata assets were returned yet. "
        "Confirm the current principal can enumerate Unity Catalog objects in the selected workspace."
    )


from atlas.services.inventory import (
    inventory_option_values as _inventory_option_values,
)


def _ensure_live_runtime() -> None:
    status = _uc_runtime_status()
    if status.get("state") != "live":
        raise HTTPException(
            status_code=503,
            detail=status.get("message") or "Live Databricks runtime is not available.",
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if str(request.url.path).startswith("/api/"):
        request_id = _http_request_id(request)
        # Many handlers build detail from str(exc); redact SDK config
        # identifiers here once instead of at every raise site.
        detail = redact_error_text(exc.detail) if isinstance(exc.detail, str) else exc.detail
        return JSONResponse(
            {
                "detail": detail,
                "requestId": request_id,
                "httpRequestId": request_id,
                "errorClass": "HTTPException",
            },
            status_code=exc.status_code,
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )
    return HTMLResponse(html.escape(redact_error_text(str(exc.detail))), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    if str(request.url.path).startswith("/api/"):
        request_id = _http_request_id(request)
        errors = [
            {
                "loc": list(error.get("loc") or []),
                "msg": str(error.get("msg") or ""),
                "type": str(error.get("type") or ""),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            {
                "detail": "Request validation failed.",
                "errors": errors,
                "requestId": request_id,
                "httpRequestId": request_id,
                "errorClass": "RequestValidationError",
            },
            status_code=422,
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )
    return HTMLResponse("Request validation failed.", status_code=422)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the root cause so operators can debug 500s. The response body
    # surfaces the exception class + first line of the message (no
    # traceback) so a FE developer can see why the call failed without
    # needing workspace log access.
    import logging
    import traceback
    logger = logging.getLogger("atlas")
    logger.error("Unhandled %s on %s: %s", exc.__class__.__name__, request.url.path, exc)
    logger.debug("Traceback:\n%s", traceback.format_exc())

    # Map UC + SQL permission errors into a clean 403 so the FE can
    # surface "you don't have MODIFY on this asset" rather than an
    # opaque 500. The trigger phrase lives in the message.
    message = str(exc) if exc else ""
    lowered = message.lower()
    path_is_api = str(request.url.path).startswith("/api/")
    request_method = str(getattr(request, "method", "")).upper()
    is_write_method = request_method in {"POST", "PUT", "PATCH", "DELETE"}
    # Sanitize the raw echo: the SDK's PermissionDenied str includes a
    # "Config: host=..., workspace_id=..., client_id=..." suffix. Never leak
    # workspace/client identifiers to the browser.
    raw_first_line = message.splitlines()[0] if message else ""
    for marker in (" Config:", ". Config:", "Config:"):
        idx = raw_first_line.find(marker)
        if idx != -1:
            raw_first_line = raw_first_line[:idx].rstrip(" .")
            break
    raw_first_line = raw_first_line[:400]
    is_scope_error = "required scopes" in lowered or "invalid scope" in lowered
    is_asset_write_denial = "permission_denied" in lowered or (
        "does not have" in lowered
        and ("modify" in lowered or "select" in lowered or "use" in lowered)
    )
    if is_scope_error or is_asset_write_denial:
        if path_is_api:
            request_id = _http_request_id(request)
            if is_scope_error:
                detail = (
                    "This action needs a Databricks permission the app's token "
                    "wasn't granted. The affected section is unavailable; other "
                    "data is unaffected."
                )
            elif is_write_method:
                detail = (
                    "You don't have write access to this asset. Ask a steward "
                    "with MODIFY on this table to make the change."
                )
            else:
                detail = (
                    "You don't have permission to view this resource in Unity "
                    "Catalog."
                )
            return JSONResponse(
                {
                    "detail": detail,
                    "errorClass": "PermissionDenied",
                    "raw": raw_first_line,
                    "requestId": request_id,
                    "httpRequestId": request_id,
                },
                status_code=403,
                headers={REQUEST_ID_HEADER: request_id} if request_id else None,
            )
        return HTMLResponse("Permission denied.", status_code=403)
    if path_is_api:
        request_id = _http_request_id(request)
        detail = error_text(exc)
        return JSONResponse(
            {
                "detail": detail,
                "requestId": request_id,
                "httpRequestId": request_id,
                "errorClass": exc.__class__.__name__,
            },
            status_code=500,
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )
    return HTMLResponse("Internal server error.", status_code=500)


def _ensure_governance_store() -> GovernanceStore:
    status = _store_status()
    if status["state"] != "live":
        raise HTTPException(
            status_code=503,
            detail=status["message"] or "Governance control plane is unavailable.",
        )
    return _store()


from atlas.api.assets import (
    AssetAvailabilityRequest,
    AssetDescriptionPatch,
    AssetMetadataPatch,
    AssetOwnersPatch,
    AssetTagsPatch,
    ColumnDescriptionPatch,
    ColumnMetadataPatch,
    ColumnTagsPatch,
    OwnerAssignment,
)


from atlas.api.governance import (
    GlossaryTermUpsert,
    GovernanceNotificationPatch,
    GovernanceRequestStatusPatch,
)


def _normalized_tag_map(df: pd.DataFrame) -> Dict[str, str]:
    if df is None or df.empty:
        return {}
    tags: Dict[str, str] = {}
    for _, row in df.iterrows():
        key = _normalize_str(row.get("tag_name"))
        value = _normalize_str(row.get("tag_value"))
        if key:
            tags[key] = value
    return tags


def _asset_table_type(asset_fqn: str, *, request: Optional[Request] = None) -> str:
    catalog, schema, table = _split_uc_name(asset_fqn)
    uc = _uc_for_request(request)
    try:
        identity_df = uc.get_table_identity(catalog, schema, table)
    except Exception:
        return ""
    if identity_df is None or identity_df.empty:
        return ""
    return _normalize_str(identity_df.iloc[0].get("table_type"))


def _apply_table_tags(
    asset_fqn: str,
    tags: Dict[str, str],
    *,
    table_type: str = "",
    request: Optional[Request] = None,
) -> Dict[str, str]:
    catalog, schema, table = _split_uc_name(asset_fqn)
    uc = _uc_for_request(request)
    normalized_tags = {
        _normalize_str(key): _normalize_str(value)
        for key, value in tags.items()
        if _normalize_str(key) and _normalize_str(value)
    }
    current_tags = _normalized_tag_map(uc.get_table_tags(catalog, schema, table))
    to_unset = [key for key in current_tags if key not in normalized_tags]
    to_set = {
        key: value
        for key, value in normalized_tags.items()
        if current_tags.get(key) != value
    }
    if to_unset:
        uc.unset_table_tags(
            catalog,
            schema,
            table,
            to_unset,
            table_type=table_type,
        )
    if to_set:
        uc.set_table_tags(
            catalog,
            schema,
            table,
            to_set,
            table_type=table_type,
        )
    return _normalized_tag_map(uc.get_table_tags(catalog, schema, table))


def _tag_write_warning(
    requested_tags: Dict[str, str],
    applied_tags: Dict[str, str],
    *,
    scope_label: str,
) -> str:
    return governance_service.tag_write_warning(
        requested_tags,
        applied_tags,
        scope_label=scope_label,
    )


def _apply_asset_metadata(
    asset_fqn: str,
    payload: AssetMetadataPatch,
    *,
    request: Optional[Request] = None,
    bypass_approval: bool = False,
) -> Tuple[Dict[str, Any], str]:
    # Approval gate: writer-role users propose; stewards/admins bypass.
    # A queued write writes NOTHING to Unity Catalog — the payload is
    # stashed on a pending change_request and returned as an envelope
    # so the frontend can show "pending approval" without pretending
    # the change took effect. See atlas/services/approvals.py.
    if not bypass_approval and request is not None:
        actor_email = _user_email(request)
        actor_role = _user_role_slug(request)
        if not approval_service.role_bypasses_gate(actor_role):
            gate = approval_service.gate_asset_metadata_patch(
                _store(),
                actor_email=actor_email,
                actor_role=actor_role,
                asset_fqn=asset_fqn,
                payload=payload.model_dump(exclude_none=True),
            )
            if gate.get("kind") == "queued":
                return (
                    {
                        "fqn": asset_fqn,
                        "approval": {
                            "status": "pending",
                            "requestId": gate.get("requestId", ""),
                            "message": (
                                "Saved as a pending metadata change request. A "
                                "steward or admin needs to approve before it "
                                "applies to Unity Catalog."
                            ),
                        },
                    },
                    "",
                )

    catalog, schema, table = _split_uc_name(asset_fqn)
    table_type = _asset_table_type(asset_fqn, request=request)
    uc = _uc_for_request(request)
    uc.set_table_comment(
        catalog,
        schema,
        table,
        payload.description or "",
        table_type=table_type,
    )
    current_tags = _normalized_tag_map(uc.get_table_tags(catalog, schema, table))
    next_tags = dict(current_tags)
    structured = {
        "domain": payload.domain,
        "tier": payload.tier,
        "certification": payload.certification,
        "sensitivity": payload.sensitivity,
        "criticality": payload.criticality,
        "business_criticality": payload.businessCriticality,
        "data_product": payload.dataProduct,
    }
    for key, raw_value in structured.items():
        if raw_value is None:
            continue
        value = _normalize_str(raw_value)
        if value:
            next_tags[key] = value
        else:
            next_tags.pop(key, None)
    # CDE is a scalar boolean-ish tag round-tripped as the string "true".
    # Absent tag means "not a CDE" so False removes the tag rather than
    # writing "false". cdeRationale is a free-form sidecar string.
    cde_keys = {"cde", "cde_rationale"}
    if payload.isCde is not None:
        if payload.isCde:
            next_tags["cde"] = "true"
            rationale = _normalize_str(payload.cdeRationale or "")
            if rationale:
                next_tags["cde_rationale"] = rationale
            elif payload.cdeRationale == "":
                next_tags.pop("cde_rationale", None)
        else:
            next_tags.pop("cde", None)
            next_tags.pop("cde_rationale", None)
    if payload.freeformTags is not None:
        structured_keys = set(structured) | cde_keys
        normalized_freeform_tags = {
            _normalize_str(key): _normalize_str(value)
            for key, value in (payload.freeformTags or {}).items()
            if _normalize_str(key) and _normalize_str(value)
        }
        for key in list(next_tags):
            if key in structured_keys:
                continue
            if key not in normalized_freeform_tags:
                next_tags.pop(key, None)
        for key, value in normalized_freeform_tags.items():
            next_tags[key] = value
    applied_tags = _apply_table_tags(
        asset_fqn, next_tags, table_type=table_type, request=request
    )
    _invalidate_asset_caches(asset_fqn)
    return (
        _asset_detail_payload(asset_fqn, request=request),
        _tag_write_warning(next_tags, applied_tags, scope_label="Classification"),
    )


def _apply_column_tags(
    asset_fqn: str,
    column_name: str,
    tags: Dict[str, str],
    *,
    table_type: str = "",
    updated_by: str = "unknown",
    request: Optional[Request] = None,
) -> Dict[str, str]:
    catalog, schema, table = _split_uc_name(asset_fqn)
    uc = _uc_for_request(request)
    normalized_tags = {
        _normalize_str(key): _normalize_str(value)
        for key, value in tags.items()
        if _normalize_str(key) and _normalize_str(value)
    }
    current_tags = _normalized_tag_map(
        uc.get_column_tags(catalog, schema, table, column_name)
    )
    to_unset = [key for key in current_tags if key not in normalized_tags]
    to_set = {
        key: value
        for key, value in normalized_tags.items()
        if current_tags.get(key) != value
    }
    if to_unset:
        uc.unset_column_tags(
            catalog,
            schema,
            table,
            column_name,
            to_unset,
            table_type=table_type,
        )
    if to_set:
        uc.set_column_tags(
            catalog,
            schema,
            table,
            column_name,
            to_set,
            table_type=table_type,
        )
    applied_tags = _normalized_tag_map(
        uc.get_column_tags(catalog, schema, table, column_name)
    )
    store = _store()
    linked_terms = store.replace_glossary_term_links(
        subject_type="column",
        subject_fqn=asset_fqn,
        column_name=column_name,
        links=[normalized_tags["glossary_term"]]
        if normalized_tags.get("glossary_term")
        else [],
        updated_by=updated_by,
        source="uc_tag",
    )
    if normalized_tags.get("glossary_term") and not any(
        link.get("resolutionState") == "linked" for link in linked_terms
    ):
        applied_tags["glossary_term_resolution"] = "unresolved"
    return applied_tags


def _ensure_asset_column_exists(
    asset_fqn: str,
    column_name: str,
    request: Optional[Request] = None,
) -> None:
    columns_df = asset_service.asset_columns_df(_uc_for_request(request), asset_fqn)
    column_names = set(columns_df["column_name"].dropna().astype(str).tolist())
    if column_name not in column_names:
        raise HTTPException(status_code=404, detail="Column not found.")


def _asset_availability_payload(
    asset_fqns: List[str],
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    unique_assets = [
        asset_fqn
        for asset_fqn in dict.fromkeys(asset_fqns or [])
        if _normalize_str(asset_fqn)
    ]
    availability: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    if len(unique_assets) > 5:
        try:
            visible_inventory = _visible_assets(request)
        except Exception as exc:
            visible_inventory = None
            warnings.append(
                _normalize_str(exc)
                or "Bulk asset visibility could not be determined from inventory."
            )
        for asset_fqn in unique_assets[:200]:
            try:
                hidden = asset_service.asset_fqn_is_hidden(
                    asset_fqn,
                    hidden_catalogs=HIDDEN_CATALOGS,
                )
                visible = False if hidden else (
                    visible_inventory is not None
                    and asset_service.asset_is_visible(visible_inventory, asset_fqn)
                )
                exists = visible
                visibility_state = "visible" if visible else (
                    "hidden" if actor_scoped and exists else "missing"
                )
                availability[asset_fqn] = {
                    "exists": exists,
                    "visible": visible,
                    "openable": visible,
                    "visibilityState": visibility_state,
                    "visibilityMethod": "bulk-inventory",
                }
            except Exception as exc:
                availability[asset_fqn] = {
                    "exists": False,
                    "visible": False,
                    "openable": False,
                    "visibilityState": "unknown",
                    "reason": _normalize_str(exc)
                    or "Asset visibility could not be determined.",
                }
                warnings.append(str(availability[asset_fqn]["reason"]))
    else:
        for asset_fqn in unique_assets[:200]:
            record = _asset_visibility_record(asset_fqn, request)
            if (
                not actor_scoped
                and record.get("visibilityState") == "loading"
                and not record.get("openable")
            ):
                record = {
                    **record,
                    "exists": False,
                    "visible": False,
                    "openable": False,
                    "visibilityState": "missing",
                    "visibilityMethod": "availability-fail-closed",
                }
            availability[asset_fqn] = record
            if record.get("visibilityState") == "unknown" and record.get("reason"):
                warnings.append(str(record["reason"]))
    return {
        "assets": availability,
        "meta": _response_meta(
            request,
            source="unity-catalog-inventory",
            state="available" if actor_scoped and not warnings else "degraded",
            authoritative=actor_scoped and not warnings,
            capabilities={
                "separatesExistsFromVisible": actor_scoped,
            },
            allowed_actions={},
            warnings=[*dict.fromkeys(warnings)],
            unavailable_reason=warnings[0] if warnings else "",
        ),
        "errors": [],
    }


def _asset_headers_payload(
    asset_fqns: List[str],
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    unique_assets = [
        asset_fqn
        for asset_fqn in dict.fromkeys(asset_fqns or [])
        if _normalize_str(asset_fqn)
    ][:64]
    headers: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    cached_inventory = _cached_visible_assets(request)
    if cached_inventory is None:
        _fast_bootstrap_inventory_summary(
            _request_cache_scope(request),
            start_background=True,
        )
        message = "Actor-visible asset inventory is hydrating; lineage card headers are deferred."
        warnings.append(message)
        for asset_fqn in unique_assets:
            payload = asset_service.asset_loading_payload(asset_fqn)
            payload["headerSource"] = "inventory-loading"
            payload["loadedSections"] = []
            payload["deferredSections"] = ["header"]
            headers[asset_fqn] = payload
        return {
            "assets": headers,
            "meta": _response_meta(
                request,
                source="unity-catalog-visible-inventory",
                state="loading",
                authoritative=False,
                capabilities={
                    "hydrating": True,
                    "requestedCount": len(unique_assets),
                    "returnedCount": len(headers),
                    "visibilityScope": (
                        capability_service.ACTOR_SCOPED_VISIBILITY
                        if actor_scoped
                        else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                    ),
                },
                warnings=warnings,
                unavailable_reason=message,
            ),
            "errors": [],
        }

    for asset_fqn in unique_assets:
        try:
            if asset_service.asset_fqn_is_hidden(asset_fqn, hidden_catalogs=HIDDEN_CATALOGS):
                headers[asset_fqn] = {
                    "fqn": asset_fqn,
                    "name": asset_fqn.split(".")[-1],
                    "error": "Asset is hidden by catalog filtering.",
                    "headerSource": "hidden-catalog-filter",
                }
                continue
            header = asset_service.asset_header_payload_from_inventory(
                cached_inventory,
                asset_fqn,
            )
            if header is None:
                headers[asset_fqn] = {
                    "fqn": asset_fqn,
                    "name": asset_fqn.split(".")[-1],
                    "error": "Asset is not present in the current visible inventory.",
                    "headerSource": "visible-inventory-miss",
                }
                continue
            headers[asset_fqn] = header
        except Exception as exc:
            headers[asset_fqn] = {
                "fqn": asset_fqn,
                "name": asset_fqn.split(".")[-1],
                "error": _normalize_str(exc) or "Asset header unavailable.",
                "headerSource": "visible-inventory-error",
            }
    return {
        "assets": headers,
        "meta": _response_meta(
            request,
            source="unity-catalog-visible-inventory",
            state="available" if actor_scoped else "degraded",
            authoritative=actor_scoped,
            capabilities={
                "requestedCount": len(unique_assets),
                "returnedCount": len(headers),
                "visibilityScope": (
                    capability_service.ACTOR_SCOPED_VISIBILITY
                    if actor_scoped
                    else capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY
                ),
            },
            warnings=[] if actor_scoped else [
                "Lineage card headers are hydrated from workspace-scoped visible inventory; per-user authorization is not available."
            ],
        ),
        "errors": [],
    }


def _shell_discovery_payload() -> Dict[str, Any]:
    return {
        "catalogs": ["All catalogs"],
        "domains": ["All domains"],
        "tiers": ["All tiers"],
        "certifications": ["All certifications"],
        "sensitivities": ["All sensitivities"],
        "assetTypes": ["All types"],
        "views": DISCOVERY_VIEWS,
        "sortOptions": DISCOVERY_SORTS,
        "defaultQuery": "",
    }


def _api_contract_payload() -> Dict[str, str]:
    return dict(SHELL_API_CONTRACT)


def _route_hints_payload(request: Optional[Request]) -> Dict[str, str]:
    if request is None:
        return {"surface": "discovery", "asset": "", "query": ""}
    return _route_context(request)


def _bootstrap_contract_payload(mode: str = "route-bootstrap") -> Dict[str, Any]:
    return {
        "version": "bootstrap-v3",
        "class": "shell-capability",
        "mode": mode,
        "warnings": [],
    }


def _shell_feature_flags_payload(
    capabilities: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    diagnostics_enabled = _config().diagnostics_enabled
    table_lineage = capabilities.get("tableLineage") or {}
    workload_visibility = capabilities.get("workloadVisibility") or {}

    def _flag(
        key: str,
        *,
        enabled: bool,
        state: str,
        reason: str = "",
        summary: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "key": key,
            "enabled": bool(enabled),
            "state": state,
        }
        resolved_reason = reason or summary
        if summary:
            payload["summary"] = summary
        if resolved_reason:
            payload["reason"] = resolved_reason
        if not enabled or state == "unavailable":
            payload["disabledReason"] = (
                resolved_reason or "This capability is unavailable."
            )
            payload["unavailableReason"] = (
                resolved_reason or "This capability is unavailable."
            )
        return payload

    diagnostics_reason = (
        "Workspace setup diagnostics are available from the runtime status endpoint."
        if diagnostics_enabled
        else "Workspace setup diagnostics are disabled for this deployment."
    )
    return [
        _flag(
            "workspace_setup_diagnostics",
            enabled=diagnostics_enabled,
            state="available" if diagnostics_enabled else "unavailable",
            reason=diagnostics_reason,
            summary="Operator diagnostics stay off the initial shell payload.",
        ),
        _flag(
            "table_lineage_surface",
            enabled=table_lineage.get("state") == "available",
            state=str(table_lineage.get("state") or "unavailable"),
            reason=_normalize_str(table_lineage.get("reason"))
            or "Live table lineage is not available in this workspace right now.",
            summary="Lineage surfaces hydrate after shell render.",
        ),
        _flag(
            "query_history_surface",
            enabled=workload_visibility.get("available") is True,
            state=str(workload_visibility.get("state") or "unavailable"),
            reason=_normalize_str(workload_visibility.get("reason"))
            or "Operational query and workload visibility is not available in this workspace right now.",
            summary="Usage and workload surfaces hydrate after shell render.",
        ),
    ]


def _shell_branding_payload() -> Dict[str, Any]:
    """Return the tenant branding dict for the shell payload. Silently
    yields an empty dict when the store is unavailable so bootstrap
    never fails on branding absence — the frontend falls back to
    hard-coded defaults.

    P5 perf: TTL-cached 60s. /api/bootstrap is refetched by the frontend on
    every tab switch (?surface=...) even though the payload does not vary by
    surface (only routeHints echoes it, and no server cache keys on it), so
    the store read here must not be paid per navigation.
    """

    def _load() -> Dict[str, Any]:
        try:
            store = _store()
        except Exception:
            return {}
        if store is None:
            return {}
        try:
            from atlas.services import branding as branding_service

            return branding_service.get_branding(store)
        except Exception:
            return {}

    return _ttl_value("runtime_shell_branding", 60, _load)


def _shell_payload(
    request: Optional[Request],
    *,
    mode: str,
    state: str,
    message: str = "",
    runtime_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_runtime_status = runtime_status or {
        "state": "loading" if state == "loading" else state,
        "message": message,
    }
    # Keep bootstrap on the fast path. Full inventory searches are allowed to
    # hydrate after the shell is interactive; blocking here is what made a cold
    # Databricks warehouse feel like the entire app was frozen.
    discovery_shell = _shell_discovery_payload()
    bootstrap_summary = (
        _fast_bootstrap_inventory_summary(_request_cache_scope(request), start_background=True)
        if request is not None
        else {}
    )
    preloaded_visible_asset_count = (
        int(bootstrap_summary.get("visibleAssets") or 0)
        if state == "live"
        else 0
    )

    # DataPact detection is a best-effort app-principal probe, run only once the
    # runtime is live (never on cold boot) and cached 60s so it can't slow the
    # bootstrap hot path. It decorates the nav + rail tile; the Control Center
    # surface performs the authoritative OBO detection on load.
    def _load_datapact_status() -> Dict[str, Any]:
        try:
            return datapact_service.shell_integration_status(_config(), _uc())
        except Exception as exc:
            return {
                "state": "unknown",
                "detected": False,
                "message": f"{error_text(exc)}",
                "surface": "datapact",
            }

    if state == "live":
        datapact_status = _ttl_value(
            "runtime_shell_datapact_status", 60, _load_datapact_status
        )
    else:
        datapact_status = {
            "state": "unknown",
            "detected": False,
            "message": "DataPact detection runs once the runtime is live.",
            "surface": "datapact",
        }

    capabilities = capability_service.bootstrap_capabilities(
        actor_role=_lightweight_user_role_slug(request),
        authenticated=_user_email(request) != "unknown"
        if request is not None
        else False,
        runtime_state=_normalize_str(resolved_runtime_status.get("state")) or state,
        runtime_message=_normalize_str(resolved_runtime_status.get("message"))
        or message,
        store_state="skipped",
        store_message="Governance control-plane checks load after the shell becomes interactive.",
        visible_asset_count=preloaded_visible_asset_count,
        available_catalog_count=int(bootstrap_summary.get("availableCatalogCount") or 0),
        observed_catalog_count=int(bootstrap_summary.get("observedCatalogCount") or 0),
        boot_message=message,
        per_user_authorization=bool(_request_obo_token(request)),
        datapact_state=_normalize_str(datapact_status.get("state")),
        datapact_reason=_normalize_str(datapact_status.get("message")),
    )

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
    # P5 perf: both statuses are workspace-level (identical for every user
    # and every ?surface=), yet /api/bootstrap is refetched on each tab
    # switch. Cache 60s so navigation-driven bootstraps stay in-memory.
    def _load_atlas_ai_status() -> Dict[str, Any]:
        try:
            return genie_service.provider_status(cfg)
        except Exception as exc:
            return {
                "state": "unavailable",
                "provider": "genie",
                "message": f"{error_text(exc)}",
            }

    def _load_lakebase_status() -> Dict[str, Any]:
        try:
            lakebase_status = lakebase_service.status(cfg)
            if _store.cache_info().currsize:
                lakebase_status = {
                    **lakebase_status,
                    "writeMirror": lakebase_store_service.dual_write_status(_store()),
                }
            elif lakebase_status.get("enabled"):
                lakebase_status = {
                    **lakebase_status,
                    "writeMirror": {
                        "enabled": False,
                        "mode": "delta-primary",
                        "state": "pending",
                        "message": "Governance store has not initialized the Lakebase dual-write mirror yet.",
                        "activeTables": list(lakebase_store_service.ACTIVE_LAKEBASE_MIRROR_TABLES),
                        "deferredTables": list(lakebase_store_service.DEFERRED_LAKEBASE_OPERATIONAL_TABLES),
                    },
                }
            return lakebase_status
        except Exception as exc:
            return {
                "state": "unavailable",
                "message": f"{error_text(exc)}",
                "enabled": False,
            }

    atlas_ai_status = _ttl_value("runtime_shell_ai_status", 60, _load_atlas_ai_status)
    lakebase_status = _ttl_value(
        "runtime_shell_lakebase_status", 60, _load_lakebase_status
    )

    payload = {
        "version": APP_VERSION,
        "bootState": state,
        "bootMessage": message,
        "apiBase": "/api",
        "discovery": discovery_shell,
        "capabilities": capabilities,
        "featureFlags": _shell_feature_flags_payload(capabilities),
        "bootstrapContract": _bootstrap_contract_payload(mode),
        "shell": {
            "metrics": [],
            "role": _lightweight_user_role(request),
            "roleProvisional": True,
            "userName": _user_display_name(request),
            "userEmail": _user_email(request),
            "buildId": _build_id(),
            "diagnosticsEnabled": cfg.diagnostics_enabled,
            "environment": {
                "label": cfg.environment_label or environment_display,
                "displayLabel": environment_display,
                "target": target_label,
                "catalog": cfg.gov_catalog,
                "schema": cfg.gov_schema,
                "warehouseId": cfg.warehouse_id,
                "workspaceHost": cfg.workspace_host,
            },
            "ai": atlas_ai_status,
            "storage": {
                "lakebase": lakebase_status,
            },
            "integrations": {
                "datapact": datapact_status,
            },
            "workspaceHost": cfg.workspace_host,
            "product": {
                "companyName": "Entrada",
                "productName": "Governance Atlas",
                "shortName": "Atlas",
                "aiName": "Atlas AI",
            },
            "branding": _shell_branding_payload(),
        },
        "identity": {
            "actorEmail": _user_email(request),
            "actorRole": _lightweight_user_role(request),
            "actorRoleProvisional": True,
            "authenticatedUserPresent": _user_email(request) != "unknown",
            "authMode": _request_auth_mode(request),
            "visibilityScope": _request_read_visibility_scope(request),
            "source": IDENTITY_SOURCE,
        },
        "routeHints": _route_hints_payload(request),
        "apiContract": _api_contract_payload(),
        "help": [],
    }
    return _with_meta(
        payload,
        request,
        source="runtime-shell",
        state=state,
        authoritative=state == "live",
        capabilities={
            "shellOnly": True,
        },
        warnings=[message] if _normalize_str(message) and state != "live" else [],
        unavailable_reason=message if state in {"unavailable", "error"} else "",
    )


def _bootstrap_unavailable_payload(
    request: Optional[Request], message: str, *, state: str = "unavailable"
) -> Dict[str, Any]:
    return _shell_payload(
        request,
        mode="bootstrap-unavailable",
        state=state,
        message=message,
        runtime_status={"state": state, "message": message},
    )


def _ensure_react_bundle() -> Path:
    _frontend_bundle_metadata()
    index_path = REACT_DIST_DIR / "index.html"
    assets_dir = REACT_DIST_DIR / "assets"
    if index_path.exists() and assets_dir.exists():
        return index_path
    raise RuntimeError(
        "The packaged React workspace bundle is missing. Build the frontend and deploy from a packaged directory."
    )


@lru_cache(maxsize=1)
def _compiled_react_index() -> str:
    return _ensure_react_bundle().read_text(encoding="utf-8")


def _inject_bootstrap(html_text: str, payload: Optional[Dict[str, Any]]) -> str:
    if payload is None:
        return html_text
    bootstrap = json.dumps(payload, default=str).replace("</", "<\\/")
    inline_bootstrap = f"<script>window.__GOVAT_BOOTSTRAP__ = {bootstrap};</script>"
    return html_text.replace("</head>", f"{inline_bootstrap}\n  </head>")


def _render_index(live_payload: Optional[Dict[str, Any]] = None) -> str:
    return _inject_bootstrap(_compiled_react_index(), live_payload)


def _spa_shell_response(request: Request) -> HTMLResponse:
    return HTMLResponse(
        _render_index(
            _shell_payload(
                request,
                mode="inline-shell",
                state="loading",
                message="Preparing the live metadata workspace.",
            )
        ),
        status_code=200,
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _spa_shell_response(request)


from atlas.api.runtime import (  # noqa: E402
    _api_bootstrap_response,
    _api_runtime_status_response,
)

app.include_router(build_runtime_router())


def _warmup_live_runtime() -> None:
    """Kick off Databricks warehouse + governance-store probes in the background
    the moment the app container starts, so the first user request doesn't have
    to absorb the cold-start latency.
    """

    def _warm() -> None:
        try:
            _uc_runtime_status()
        except Exception:
            pass
        try:
            _store_status()
        except Exception:
            pass
        try:
            _bootstrap_inventory_summary("anonymous")
        except Exception:
            pass

    thread = threading.Thread(target=_warm, name="atlas-warmup", daemon=True)
    thread.start()


_BACKGROUND_DRAINER_STOPPED = False
# The drainer sleeps until woken (enqueue or shutdown) instead of polling:
# a SELECT every 30s kept the SQL warehouse from ever auto-stopping, billing
# it 24x7 on every target for a queue that is almost always empty.
_BACKGROUND_DRAINER_WAKE = threading.Event()


def _wake_background_drainer() -> None:
    """Ask the drainer to run one drain pass now (called after enqueue)."""
    _BACKGROUND_DRAINER_WAKE.set()
# Minimal truth snapshot for the background drainer so operators can see
# whether it is alive, how many items it has drained, when it last ran,
# and any latched error without having to read app logs. Updated in
# place by the drainer loop; read by GET /api/admin/background/status.
_DRAINER_STATE: Dict[str, Any] = {
    "running": False,
    "lastDrainAt": None,
    "processedTotal": 0,
    "lastError": None,
}


def _background_drainer_snapshot() -> Dict[str, Any]:
    """Return a defensive copy of the drainer state for external consumers."""
    return {
        "running": bool(_DRAINER_STATE.get("running", False)),
        "lastDrainAt": _DRAINER_STATE.get("lastDrainAt"),
        "processedTotal": int(_DRAINER_STATE.get("processedTotal") or 0),
        "lastError": _DRAINER_STATE.get("lastError"),
    }


def _start_background_drainer() -> None:
    """Phase 12 — background work runner.

    Drains once at startup (items left by a restart), then only when
    woken by _wake_background_drainer(). Same drain_queued_batch contract as
    the admin-triggered batch endpoint; running inside the app lets
    async exports complete without any external cron wiring.

    Runs as a daemon thread so it doesn't block interpreter shutdown.
    Gracefully stops when `_BACKGROUND_DRAINER_STOPPED` is set during
    teardown.
    """
    global _BACKGROUND_DRAINER_STOPPED

    _BACKGROUND_DRAINER_STOPPED = False

    from atlas.services.background_runner import drain_queued_batch
    from atlas.api.export import _handle_export_work

    def _drain_loop() -> None:
        _DRAINER_STATE["running"] = True
        _BACKGROUND_DRAINER_WAKE.set()  # one startup pass
        while not _BACKGROUND_DRAINER_STOPPED:
            _BACKGROUND_DRAINER_WAKE.wait()
            _BACKGROUND_DRAINER_WAKE.clear()
            if _BACKGROUND_DRAINER_STOPPED:
                break
            try:
                _ensure_governance_store()
                store = _store()
                results = drain_queued_batch(
                    store=store, handler=_handle_export_work, max_items=5
                )
                # _utc_iso(value) needs a timestamp — the drainer was calling it
                # with no args, raising TypeError every tick and flipping the
                # background-work envelope to Degraded. _now_iso() is the no-arg
                # helper meant for exactly this.
                _DRAINER_STATE["lastDrainAt"] = _now_iso()
                _DRAINER_STATE["processedTotal"] = int(
                    _DRAINER_STATE.get("processedTotal") or 0
                ) + len(results or [])
                _DRAINER_STATE["lastError"] = None
            except Exception as exc:
                # Don't let a transient store failure kill the drainer —
                # we want it to keep retrying on the next tick.
                _DRAINER_STATE["lastError"] = _format_runtime_message(exc)
        _DRAINER_STATE["running"] = False

    thread = threading.Thread(target=_drain_loop, name="atlas-bg-drainer", daemon=True)
    thread.start()


def _stop_background_drainer() -> None:
    global _BACKGROUND_DRAINER_STOPPED
    _BACKGROUND_DRAINER_STOPPED = True
    _BACKGROUND_DRAINER_WAKE.set()


from atlas.api.assets import (  # noqa: E402
    api_asset_availability,
    api_asset_detail,
    api_patch_asset_description,
    api_patch_asset_metadata,
    api_patch_asset_owners,
    api_patch_asset_tags,
    api_patch_column_description,
    api_patch_column_metadata,
    api_patch_column_tags,
)
from atlas.api.discovery import api_discovery_search  # noqa: E402


from atlas.api.lineage import api_lineage  # noqa: E402


from atlas.api.governance import (  # noqa: E402
    api_governance_create_request,
    api_governance_glossary,
    api_governance_glossary_term,
    api_governance_patch_glossary,
    api_governance_patch_notification,
    api_governance_patch_request,
    api_governance_summary,
    api_governance_upsert_glossary,
    api_governance_upsert_owner,
)

app.include_router(build_discovery_router())
# catalog MUST register before assets so the more-specific
# /api/assets/{asset_fqn:path}/(profile|quality|custom-properties|access-explain)
# routes win over the generic /api/assets/{asset_fqn:path} catch-all.
app.include_router(build_catalog_router())
app.include_router(build_assets_router())
app.include_router(build_lineage_router())
app.include_router(build_governance_router())
app.include_router(build_classification_router())
app.include_router(build_export_router())
app.include_router(build_admin_router())
app.include_router(build_insights_router())
app.include_router(build_atlas_router())
app.include_router(build_atlas_ai_router())
app.include_router(build_cde_router())
app.include_router(build_datapact_router())


@app.get("/{client_path:path}", response_class=HTMLResponse, include_in_schema=False)
def client_route_shell(client_path: str, request: Request) -> HTMLResponse:
    normalized = _normalize_str(client_path)
    if not normalized:
        return _spa_shell_response(request)
    root = normalized.split("?", 1)[0].split("#", 1)[0].split("/", 1)[0].lower()
    if root in CLIENT_ROUTE_PREFIXES:
        return _spa_shell_response(request)
    raise HTTPException(status_code=404, detail="Not found.")
