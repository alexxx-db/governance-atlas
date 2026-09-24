"""Operator-facing admin endpoints.

Currently exposes:

- /api/admin/background/status: a minimal snapshot of the background
  drainer state so the /capabilities dashboard can render a truthful
  "background work health" row without synthesizing metrics.
- /api/admin/truth-check: a metastore truth check that runs authoritative
  COUNT(*) queries against system.information_schema and compares the
  result against the inventory + visible-asset counts that drive the
  Governance Atlas UI. Lets admins detect drift between Unity Catalog
  ground truth and what the surfaced product reports.

Additional admin endpoints can land here as long as they remain
read-only and do not duplicate capability derivation already performed
by /api/runtime/status.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from atlas.util import error_text, sql_literal


class BrandingPatch(BaseModel):
    primaryColor: str = ""
    accentColor: str = ""
    logoUrl: str = ""
    orgDisplayName: str = ""


class RolePatch(BaseModel):
    email: str = ""
    role: str = ""


# Roles a workspace admin may assign (G3). Matches the store's role vocabulary
# (MUTATION_ROLES/APPROVAL_ROLES ⊂ this set); "reader" is the floor.
ASSIGNABLE_ROLES = ("reader", "writer", "steward", "admin")


def _background_status_payload() -> Dict[str, Any]:
    # Lazy import to avoid circular dependency with runtime_app, which
    # mounts this router during its own module-load phase.
    from runtime_app import _background_drainer_snapshot

    snapshot = _background_drainer_snapshot()
    running = bool(snapshot.get("running", False))
    last_error = snapshot.get("lastError") or ""
    last_drain_at = snapshot.get("lastDrainAt")
    state = "available" if running and not last_error else "degraded"
    reason = ""
    if not running:
        reason = "Background drainer thread is not currently running."
    elif last_error:
        reason = f"Background drainer reported an error on its last tick: {last_error}"
    return {
        "data": {
            "drainer": {
                "running": running,
                "lastDrainAt": last_drain_at,
                "processedTotal": int(snapshot.get("processedTotal") or 0),
                "lastError": last_error or None,
            },
            "queue": {
                # Depth hint intentionally null — a follow-up tranche
                # will query the background_queue table. Reporting a
                # hard-coded 0 here would be a lie; null is the
                # honest "not observed" signal.
                "depthHint": None,
            },
        },
        "meta": {
            "state": state,
            "reason": reason,
        },
    }


def _visible_fqns(request: Request) -> set[str]:
    try:
        from runtime_app import _visible_assets
    except Exception:
        return set()
    try:
        frame = _visible_assets(request)
    except Exception:
        return set()
    if frame is None:
        return set()
    try:
        column = frame.get("fqn")
        if column is None:
            return set()
        return {str(entry).strip() for entry in column if str(entry).strip()}
    except Exception:
        return set()


# ─────────────────────────────────────────────────────────────────────
# Truth check
# ─────────────────────────────────────────────────────────────────────
#
# The truth-check endpoint runs authoritative COUNT(*) queries against
# system.information_schema (catalogs, schemata, tables) and compares
# the result with what asset_service.inventory() / visible_assets() —
# the engines that feed the discovery surface — actually report.
#
# The result is cached in-process for a short window so the Control
# Center "Metastore truth check" tab can be re-opened cheaply, and so
# multiple admins inspecting it don't trigger redundant warehouse work.
#
# All queries here run under the app-principal UC client (system
# information schema reads typically require a metastore-admin grant
# anyway). The endpoint itself is gated to the admin role above.

logger = logging.getLogger(__name__)

_TRUTH_CACHE_TTL_SECONDS = 60.0
_TRUTH_CACHE_LOCK = threading.Lock()
_TRUTH_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sql_literal(value: str) -> str:
    return sql_literal(str(value))


def _discovery_catalogs() -> List[str]:
    raw = os.getenv("GOVAT_DISCOVERY_CATALOGS", "") or ""
    return [
        item.strip()
        for item in raw.split(",")
        if item and item.strip()
    ]


def _hidden_catalogs() -> List[str]:
    # Mirrors atlas.services.assets.HIDDEN_CATALOGS so that the truth
    # check applies the same filter the UI applies. Imported lazily to
    # avoid a circular import via runtime_app.
    try:
        from atlas.services.assets import HIDDEN_CATALOGS

        return [str(value) for value in HIDDEN_CATALOGS]
    except Exception:
        return ["system", "samples", "__databricks_internal", "information_schema"]


def _catalog_clause(column: str, catalogs: List[str]) -> str:
    if not catalogs:
        return "1=1"
    in_clause = ", ".join(_sql_literal(c) for c in catalogs)
    return f"LOWER({column}) IN ({in_clause})"


def _safe_query(uc, sql: str, *, timeout_s: int = 30) -> Tuple[pd.DataFrame, str, int]:
    """Run a SQL statement and return (dataframe, error_text, elapsed_ms).

    Errors are caught so a single failing query doesn't kill the entire
    truth-check response. The error text is surfaced in the payload so
    the operator can act on it.
    """
    started = time.time()
    try:
        df = uc.query_df(sql, timeout_s=timeout_s)
        elapsed_ms = int((time.time() - started) * 1000)
        return df, "", elapsed_ms
    except Exception as exc:  # pragma: no cover — network / auth fault paths
        elapsed_ms = int((time.time() - started) * 1000)
        logger.warning("truth-check query failed: %s", exc)
        return pd.DataFrame(), str(exc) or exc.__class__.__name__, elapsed_ms


def _coerce_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _per_catalog_table_counts(uc, catalogs: List[str]) -> Tuple[Dict[str, int], str, int]:
    if not catalogs:
        return {}, "", 0
    where_clause = _catalog_clause("table_catalog", [c.lower() for c in catalogs])
    sql = (
        "SELECT LOWER(table_catalog) AS catalog, COUNT(*) AS table_count "
        "FROM system.information_schema.tables "
        f"WHERE {where_clause} "
        "GROUP BY LOWER(table_catalog)"
    )
    df, err, elapsed_ms = _safe_query(uc, sql)
    counts: Dict[str, int] = {}
    if not df.empty and "catalog" in df.columns and "table_count" in df.columns:
        for _, row in df.iterrows():
            counts[str(row["catalog"]).lower()] = _coerce_int(row["table_count"])
    return counts, err, elapsed_ms


def _per_catalog_schema_counts(uc, catalogs: List[str]) -> Tuple[Dict[str, int], str, int]:
    if not catalogs:
        return {}, "", 0
    where_clause = _catalog_clause("catalog_name", [c.lower() for c in catalogs])
    # information_schema.schemata is the SQL standard spelling; on
    # Databricks Unity Catalog the relation is named "schemata".
    sql = (
        "SELECT LOWER(catalog_name) AS catalog, COUNT(*) AS schema_count "
        "FROM system.information_schema.schemata "
        f"WHERE {where_clause} "
        "GROUP BY LOWER(catalog_name)"
    )
    df, err, elapsed_ms = _safe_query(uc, sql)
    counts: Dict[str, int] = {}
    if not df.empty and "catalog" in df.columns and "schema_count" in df.columns:
        for _, row in df.iterrows():
            counts[str(row["catalog"]).lower()] = _coerce_int(row["schema_count"])
    return counts, err, elapsed_ms


def _ui_inventory_counts() -> Tuple[Dict[str, int], Dict[str, int], int, int, str]:
    """Compute per-catalog inventory + visible-asset counts the UI sees.

    Returns (inventory_per_catalog, visible_per_catalog, inventory_total,
    visible_total, error_text).
    """
    try:
        from runtime_app import _store, _uc
        from atlas.services import assets as asset_service
    except Exception as exc:  # pragma: no cover — import-time fault path
        return {}, {}, 0, 0, str(exc)

    try:
        inventory_df = asset_service.inventory(_uc(), _store())
    except Exception as exc:
        return {}, {}, 0, 0, f"inventory() failed: {exc}"

    inventory_per_catalog: Dict[str, int] = {}
    if (
        inventory_df is not None
        and not inventory_df.empty
        and "table_catalog" in inventory_df.columns
    ):
        for catalog, group in inventory_df.groupby(
            inventory_df["table_catalog"].fillna("").astype(str).str.lower()
        ):
            inventory_per_catalog[catalog] = int(len(group))
    inventory_total = sum(inventory_per_catalog.values())

    try:
        visible_df = asset_service.visible_assets(inventory_df)
    except Exception as exc:
        return inventory_per_catalog, {}, inventory_total, 0, f"visible_assets() failed: {exc}"

    visible_per_catalog: Dict[str, int] = {}
    if (
        visible_df is not None
        and not visible_df.empty
        and "table_catalog" in visible_df.columns
    ):
        for catalog, group in visible_df.groupby(
            visible_df["table_catalog"].fillna("").astype(str).str.lower()
        ):
            visible_per_catalog[catalog] = int(len(group))
    visible_total = sum(visible_per_catalog.values())

    return (
        inventory_per_catalog,
        visible_per_catalog,
        inventory_total,
        visible_total,
        "",
    )


def _build_truth_check_payload() -> Dict[str, Any]:
    from runtime_app import _uc

    uc = _uc()
    discovery_catalogs = _discovery_catalogs()
    hidden_catalogs = _hidden_catalogs()
    queries: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Total catalogs in the metastore (excluding configured hidden roots).
    if hidden_catalogs:
        catalog_where = (
            "LOWER(catalog_name) NOT IN ("
            + ", ".join(_sql_literal(c.lower()) for c in hidden_catalogs)
            + ")"
        )
    else:
        catalog_where = "1=1"
    catalog_sql = (
        "SELECT COUNT(*) AS catalog_count "
        "FROM system.information_schema.catalogs "
        f"WHERE {catalog_where}"
    )
    catalog_df, catalog_err, catalog_ms = _safe_query(uc, catalog_sql)
    catalog_total = (
        _coerce_int(catalog_df.iloc[0, 0]) if not catalog_df.empty else 0
    )
    if catalog_err:
        warnings.append(f"catalog count query failed: {catalog_err}")
    queries.append(
        {
            "label": "system.information_schema.catalogs",
            "sql": catalog_sql,
            "rowCount": catalog_total,
            "elapsedMs": catalog_ms,
            "error": catalog_err or None,
        }
    )

    # Per-discovery-catalog schema + table counts.
    per_schema_counts, schema_err, schema_ms = _per_catalog_schema_counts(
        uc, discovery_catalogs
    )
    schema_total = sum(per_schema_counts.values())
    if schema_err:
        warnings.append(f"schema count query failed: {schema_err}")
    queries.append(
        {
            "label": "system.information_schema.schemata",
            "sql": (
                "SELECT LOWER(catalog_name) AS catalog, COUNT(*) AS schema_count "
                "FROM system.information_schema.schemata "
                f"WHERE {_catalog_clause('catalog_name', [c.lower() for c in discovery_catalogs])} "
                "GROUP BY LOWER(catalog_name)"
            ),
            "rowCount": schema_total,
            "elapsedMs": schema_ms,
            "error": schema_err or None,
        }
    )

    per_table_counts, table_err, table_ms = _per_catalog_table_counts(
        uc, discovery_catalogs
    )
    table_total = sum(per_table_counts.values())
    if table_err:
        warnings.append(f"table count query failed: {table_err}")
    queries.append(
        {
            "label": "system.information_schema.tables",
            "sql": (
                "SELECT LOWER(table_catalog) AS catalog, COUNT(*) AS table_count "
                "FROM system.information_schema.tables "
                f"WHERE {_catalog_clause('table_catalog', [c.lower() for c in discovery_catalogs])} "
                "GROUP BY LOWER(table_catalog)"
            ),
            "rowCount": table_total,
            "elapsedMs": table_ms,
            "error": table_err or None,
        }
    )

    # UI counts.
    (
        ui_inventory_per_catalog,
        ui_visible_per_catalog,
        ui_inventory_total,
        ui_visible_total,
        ui_err,
    ) = _ui_inventory_counts()
    if ui_err:
        warnings.append(f"ui inventory derivation failed: {ui_err}")

    # Per-catalog breakdown — drift is the difference between metastore
    # truth and what the UI reports as inventory. A negative drift means
    # the UI surfaced more rows than the metastore acknowledges
    # (likely a stale cache); a positive drift means the metastore has
    # tables the UI didn't surface (likely actor-visibility filters or
    # hidden-schema rules).
    per_catalog: List[Dict[str, Any]] = []
    catalog_keys = set()
    catalog_keys.update(per_table_counts.keys())
    catalog_keys.update(per_schema_counts.keys())
    catalog_keys.update(ui_inventory_per_catalog.keys())
    catalog_keys.update(ui_visible_per_catalog.keys())
    catalog_keys.update(c.lower() for c in discovery_catalogs)

    discovery_set = {c.lower() for c in discovery_catalogs}
    for catalog in sorted(catalog_keys):
        metastore_tables = int(per_table_counts.get(catalog, 0))
        metastore_schemas = int(per_schema_counts.get(catalog, 0))
        ui_inventory_tables = int(ui_inventory_per_catalog.get(catalog, 0))
        ui_visible_tables = int(ui_visible_per_catalog.get(catalog, 0))
        # An all-zero row is indistinguishable (from these probes alone)
        # between "catalog is genuinely empty" and "app principal lacks
        # information_schema/SELECT grants on it". Flag it explicitly so the
        # UI can badge the row instead of rendering a wall of bare zeros
        # that reads as a broken product.
        all_zero = not any(
            (metastore_tables, metastore_schemas, ui_inventory_tables, ui_visible_tables)
        )
        per_catalog.append(
            {
                "catalog": catalog,
                "configured": catalog in discovery_set,
                "state": "empty-or-unauthorized" if all_zero else "populated",
                "stateReason": (
                    "No schemas or tables are visible to the app principal in this catalog — "
                    "it is either empty or the principal lacks information_schema grants."
                    if all_zero
                    else ""
                ),
                "metastore": {
                    "schemaCount": metastore_schemas,
                    "tableCount": metastore_tables,
                },
                "ui": {
                    "inventoryAssetCount": ui_inventory_tables,
                    "visibleAssetCount": ui_visible_tables,
                },
                "drift": {
                    # Positive = metastore knows about MORE than UI inventory.
                    "inventoryDelta": metastore_tables - ui_inventory_tables,
                    # Positive = inventory has MORE than the visible surface.
                    "hiddenByVisibility": ui_inventory_tables - ui_visible_tables,
                },
            }
        )

    state = "available"
    reason = ""
    if warnings:
        state = "degraded"
        reason = warnings[0]

    # Explain non-zero drift instead of leaving the operator staring at a
    # bare delta. Only emitted when the underlying probes succeeded — a
    # failed table/inventory query would make the delta itself meaningless.
    inventory_delta = table_total - ui_inventory_total
    drift_warnings = list(warnings)
    if inventory_delta and not table_err and not ui_err:
        if inventory_delta > 0:
            drift_warnings.append(
                f"{inventory_delta} metastore table(s) are not in the surfaced inventory — "
                "likely a stale inventory cache or hidden-schema rules."
            )
        else:
            drift_warnings.append(
                f"The surfaced inventory reports {abs(inventory_delta)} more table(s) than "
                "the metastore — likely a stale inventory cache holding dropped tables."
            )

    return {
        "data": {
            "discoveryCatalogs": discovery_catalogs,
            "hiddenCatalogs": hidden_catalogs,
            "metastore": {
                "catalogTotal": catalog_total,
                "schemaTotalForDiscovery": schema_total,
                "tableTotalForDiscovery": table_total,
                "perCatalog": per_catalog,
            },
            "ui": {
                "inventoryTotal": ui_inventory_total,
                "visibleTotal": ui_visible_total,
            },
            "drift": {
                "inventoryDelta": inventory_delta,
                "hiddenByVisibility": ui_inventory_total - ui_visible_total,
                "warnings": drift_warnings,
            },
            "queries": queries,
            "observedAt": _now_iso(),
        },
        "meta": {
            "state": state,
            "reason": reason,
        },
    }


def _truth_check_payload(force_refresh: bool = False) -> Dict[str, Any]:
    cache_key = "default"
    now = time.time()
    if not force_refresh:
        with _TRUTH_CACHE_LOCK:
            cached = _TRUTH_CACHE.get(cache_key)
            if cached and now - cached[0] < _TRUTH_CACHE_TTL_SECONDS:
                return cached[1]
    payload = _build_truth_check_payload()
    with _TRUTH_CACHE_LOCK:
        _TRUTH_CACHE[cache_key] = (now, payload)
    return payload


def build_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/background/status")
    def api_background_status() -> JSONResponse:
        return JSONResponse(_background_status_payload())

    @router.get("/truth-check")
    def api_truth_check(request: Request) -> JSONResponse:
        # Lazy import to keep the admin router importable at module load
        # time without dragging the FastAPI runtime app along.
        from runtime_app import _user_role_slug

        role = _user_role_slug(request)
        if role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Admin role required to view metastore truth check.",
            )
        force_refresh = (
            (request.query_params.get("refresh") or "").strip().lower()
            in {"1", "true", "yes"}
        )
        payload = _truth_check_payload(force_refresh=force_refresh)
        return JSONResponse(payload)

    @router.post("/bulk-import/dry-run")
    async def api_bulk_import_dry_run(request: Request) -> JSONResponse:
        from runtime_app import _ensure_can_mutate, _ensure_live_runtime, _user_role_slug
        from atlas.services import approvals as approval_service
        from atlas.services import bulk_import as bulk_import_service

        _ensure_live_runtime()
        _ensure_can_mutate(request)
        if not approval_service.role_can_decide(_user_role_slug(request)):
            raise HTTPException(
                status_code=403,
                detail="Bulk import is restricted to stewards and admins.",
            )
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Body must be valid JSON.")
        parsed = bulk_import_service.parse_csv(str(body.get("csvText") or ""))
        if parsed.get("errors") and not parsed.get("rows"):
            return JSONResponse(
                {
                    "ok": False,
                    "headers": parsed.get("headers", []),
                    "rowCount": 0,
                    "results": [],
                    "summary": {"total": 0, "valid": 0, "invalid": 0, "empty": 0},
                    "parseErrors": parsed.get("errors", []),
                }
            )
        visible = _visible_fqns(request)
        validation = bulk_import_service.validate_rows(
            parsed.get("rows", []),
            asset_exists=(lambda fqn: fqn in visible) if visible else None,
        )
        return JSONResponse(
            {
                "ok": True,
                "headers": parsed.get("headers", []),
                "rowCount": len(parsed.get("rows", [])),
                "results": validation["results"],
                "summary": validation["summary"],
                "parseErrors": parsed.get("errors", []),
            }
        )

    @router.post("/bulk-import/commit")
    async def api_bulk_import_commit(request: Request) -> JSONResponse:
        from runtime_app import (
            _apply_asset_metadata,
            _asset_is_openable,
            _ensure_can_mutate,
            _ensure_live_runtime,
            _metadata_audit_asset_snapshot,
            _record_metadata_audit,
            _user_role_slug,
        )
        from atlas.api.assets import AssetMetadataPatch
        from atlas.services import approvals as approval_service
        from atlas.services import bulk_import as bulk_import_service

        _ensure_live_runtime()
        actor_email = _ensure_can_mutate(request)
        actor_role = _user_role_slug(request)
        if not approval_service.role_can_decide(actor_role):
            raise HTTPException(
                status_code=403,
                detail="Bulk import is restricted to stewards and admins.",
            )
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Body must be valid JSON.")
        incoming_rows = body.get("rows") if isinstance(body.get("rows"), list) else []
        normalized_rows: List[Dict[str, Any]] = []
        for entry in incoming_rows:
            if not isinstance(entry, dict):
                continue
            raw = entry.get("raw") if isinstance(entry.get("raw"), dict) else entry
            normalized_rows.append({key: value for key, value in raw.items() if isinstance(key, str)})
        visible = _visible_fqns(request)
        validation = bulk_import_service.validate_rows(
            normalized_rows,
            asset_exists=(lambda fqn: fqn in visible) if visible else None,
        )

        def apply_one(fqn: str, patch: Dict[str, Any]) -> Dict[str, Any]:
            try:
                payload_model = AssetMetadataPatch(**patch)
            except Exception as exc:
                raise ValueError(f"Invalid patch: {exc}") from exc
            if not _asset_is_openable(fqn, request):
                raise RuntimeError("Asset not openable for current actor.")
            before = _metadata_audit_asset_snapshot(fqn, request)
            asset, warning = _apply_asset_metadata(fqn, payload_model, request=request)
            approval = asset.get("approval") if isinstance(asset, dict) else None
            if isinstance(approval, dict) and approval.get("status") == "pending":
                try:
                    _record_metadata_audit(
                        entity_type="change_request",
                        action="asset-metadata-proposed",
                        actor_email=actor_email,
                        actor_role=actor_role,
                        entity_fqn=fqn,
                        entity_id=approval.get("requestId") or fqn,
                        before=before,
                        after={"approval": approval},
                        detail="bulk-import",
                    )
                except Exception:
                    pass
                return {"approval": approval, "warning": warning}
            after = _metadata_audit_asset_snapshot(fqn, request)
            try:
                _record_metadata_audit(
                    entity_type="asset",
                    action="asset-metadata-updated",
                    actor_email=actor_email,
                    actor_role=actor_role,
                    entity_fqn=fqn,
                    entity_id=fqn,
                    before=before,
                    after=after,
                    detail="bulk-import",
                )
            except Exception:
                pass
            return {"asset": asset, "warning": warning}

        commit = bulk_import_service.apply_rows(validation["results"], apply_one=apply_one)
        return JSONResponse({"ok": True, "results": commit["outcomes"], "summary": commit["summary"]})

    @router.get("/coverage")
    def api_admin_coverage(
        request: Request,
        required_fields: Optional[List[str]] = Query(default=None, alias="requiredFields"),
    ) -> JSONResponse:
        from runtime_app import (
            HIDDEN_CATALOGS,
            _ensure_can_mutate,
            _ensure_live_runtime,
            _user_role_slug,
            _visible_assets,
        )
        from atlas.services import approvals as approval_service
        from atlas.services import coverage as coverage_service

        _ensure_live_runtime()
        _ensure_can_mutate(request)
        if not approval_service.role_can_decide(_user_role_slug(request)):
            raise HTTPException(
                status_code=403,
                detail="Coverage dashboard is restricted to stewards and admins.",
            )
        payload = coverage_service.coverage_aggregate(
            _visible_assets(request),
            required_fields=required_fields,
            hidden_catalogs=HIDDEN_CATALOGS,
        )
        return JSONResponse(payload)

    @router.get("/coverage/drilldown")
    def api_admin_coverage_drilldown(
        request: Request,
        required_fields: Optional[List[str]] = Query(default=None, alias="requiredFields"),
        tier: Optional[str] = Query(default=None),
        domain: Optional[str] = Query(default=None),
        missing_field: Optional[str] = Query(default=None, alias="missingField"),
        limit: int = Query(default=200),
    ) -> JSONResponse:
        from runtime_app import (
            HIDDEN_CATALOGS,
            _ensure_can_mutate,
            _ensure_live_runtime,
            _user_role_slug,
            _visible_assets,
        )
        from atlas.services import approvals as approval_service
        from atlas.services import coverage as coverage_service
        from atlas.services.assets import normalize_str

        _ensure_live_runtime()
        _ensure_can_mutate(request)
        if not approval_service.role_can_decide(_user_role_slug(request)):
            raise HTTPException(
                status_code=403,
                detail="Coverage dashboard is restricted to stewards and admins.",
            )
        payload = coverage_service.coverage_drilldown(
            _visible_assets(request),
            required_fields=required_fields,
            tier=normalize_str(tier) or None,
            domain=normalize_str(domain) or None,
            missing_field=normalize_str(missing_field) or None,
            limit=limit,
            hidden_catalogs=HIDDEN_CATALOGS,
        )
        return JSONResponse(payload)

    @router.get("/branding")
    def api_admin_branding_get(request: Request) -> JSONResponse:
        from runtime_app import (
            _ensure_can_mutate,
            _ensure_governance_store,
            _ensure_live_runtime,
            _store,
            _user_role_slug,
        )
        from atlas.services import branding as branding_service

        _ensure_live_runtime()
        _ensure_can_mutate(request)
        if _user_role_slug(request) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required.")
        _ensure_governance_store()
        return JSONResponse({"ok": True, "branding": branding_service.get_branding(_store())})

    @router.put("/branding")
    def api_admin_branding_put(payload: BrandingPatch, request: Request) -> JSONResponse:
        from runtime_app import (
            _ensure_can_mutate,
            _ensure_governance_store,
            _ensure_live_runtime,
            _store,
            _user_role_slug,
        )
        from atlas.services import branding as branding_service

        _ensure_live_runtime()
        actor_email = _ensure_can_mutate(request)
        if _user_role_slug(request) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required.")
        _ensure_governance_store()
        try:
            branding = branding_service.set_branding(
                _store(),
                primary_color=payload.primaryColor,
                accent_color=payload.accentColor,
                logo_url=payload.logoUrl,
                org_display_name=payload.orgDisplayName,
                updated_by=actor_email,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "branding": branding})

    @router.get("/roles")
    def api_admin_roles_get(request: Request) -> JSONResponse:
        """List every explicitly-assigned workspace role (G3). Admin only."""
        from runtime_app import (
            _config,
            _ensure_can_mutate,
            _ensure_governance_store,
            _ensure_live_runtime,
            _store,
            _user_role_slug,
        )
        from atlas.services.assets import normalize_str as _normalize_str

        _ensure_live_runtime()
        _ensure_can_mutate(request)
        if _user_role_slug(request) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required.")
        _ensure_governance_store()
        try:
            roles_df = _store().list_roles()
        except Exception:
            roles_df = pd.DataFrame()
        roles: List[Dict[str, Any]] = []
        if roles_df is not None and not roles_df.empty:
            for _, row in roles_df.iterrows():
                email = _normalize_str(row.get("email")).lower()
                if not email:
                    continue
                roles.append(
                    {
                        "email": email,
                        "role": _normalize_str(row.get("role")).lower() or "reader",
                        "updatedAt": _normalize_str(row.get("updated_at")),
                        "updatedBy": _normalize_str(row.get("updated_by")),
                    }
                )
        # Bootstrap admins (from env) are admins even without an explicit row —
        # surface them so the roster is truthful, not silently missing them.
        bootstrap_admins = {
            item.strip().lower() for item in _config().admin_emails if item and item.strip()
        }
        known = {entry["email"] for entry in roles}
        for admin_email in sorted(bootstrap_admins - known):
            roles.append(
                {"email": admin_email, "role": "admin", "updatedAt": "", "updatedBy": "bootstrap"}
            )
        return JSONResponse(
            {"ok": True, "roles": roles, "assignableRoles": list(ASSIGNABLE_ROLES)}
        )

    @router.put("/roles")
    def api_admin_roles_put(payload: RolePatch, request: Request) -> JSONResponse:
        """Assign a workspace user a role (G3). Admin only."""
        from runtime_app import (
            _ensure_can_mutate,
            _ensure_governance_store,
            _ensure_live_runtime,
            _store,
            _user_role_slug,
        )
        from atlas.services.assets import normalize_str as _normalize_str

        _ensure_live_runtime()
        actor_email = _ensure_can_mutate(request)
        if _user_role_slug(request) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required.")
        email = _normalize_str(payload.email).lower()
        role = _normalize_str(payload.role).lower()
        if not email or "@" not in email:
            raise HTTPException(status_code=400, detail="A valid user email is required.")
        if role not in ASSIGNABLE_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Role must be one of: {', '.join(ASSIGNABLE_ROLES)}.",
            )
        _ensure_governance_store()
        try:
            _store().upsert_role(email=email, role=role, updated_by=actor_email)
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Could not assign the role: {error_text(exc)}"
            ) from exc
        # Apply now, not after the 60s role-cache TTL: a demoted user must
        # lose their old permissions immediately.
        from atlas.api.cache import _ttl_cache_pop

        _ttl_cache_pop(f"runtime_user_role:{email.lower()}")
        return JSONResponse({"ok": True, "email": email, "role": role})

    return router
