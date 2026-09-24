"""A9.4 Classification Recommendation API.

Read/list endpoints are available to anyone who can see the asset; the
review + scan endpoints require write permission. Mirrors the
governance.py ``build_*_router`` pattern.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from atlas.util import error_text
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import field_validator

from atlas.services import input_safety
from atlas.services import classification as classification_service
from atlas.services.assets import normalize_str as _normalize_str


class ClassificationReviewPayload(BaseModel):
    decision: str
    note: str = ""

    @field_validator("decision", mode="before")
    @classmethod
    def _sanitize_decision(cls, value: Any) -> str:
        try:
            return input_safety.sanitize_plain_text(
                value,
                field="decision",
                max_length=64,
                allow_empty=True,
            )
        except ValueError:
            return ""

    @field_validator("note", mode="before")
    @classmethod
    def _sanitize_note(cls, value: Any) -> str:
        return input_safety.sanitize_markdown(value, field="note", max_length=4000)


def _resolve_runtime():
    from runtime_app import (
        _ensure_governance_store,
        _ensure_live_runtime,
        _store,
    )

    _ensure_live_runtime()
    _ensure_governance_store()
    return _store()


def _runtime_asset_openable(asset_fqn: str | None, request: Request) -> bool:
    if not asset_fqn:
        return False
    from runtime_app import _asset_is_openable

    return bool(_asset_is_openable(asset_fqn, request))


def _require_open_asset(asset_fqn: str | None, request: Request) -> None:
    if not _runtime_asset_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")


def _safe_query_string(value: Any) -> str:
    """Normalize a FastAPI ``Query`` argument into a plain string.

    When the endpoint is invoked directly from tests (without FastAPI
    routing), the ``Query`` default sentinel object can leak through. This
    helper collapses that sentinel (and any ``None``) to an empty string so
    downstream filtering treats it as "no filter applied".
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    # Detect FastAPI/Pydantic ``Query`` sentinel objects.
    if value.__class__.__name__ in {"Query", "FieldInfo"}:
        return ""
    return _normalize_str(value)


def api_list_classification_recommendations(
    request: Request,
    status: str = Query(default="pending"),
    asset_fqn: Optional[str] = Query(default=None, alias="assetFqn"),
) -> JSONResponse:
    store = _resolve_runtime()
    normalized_status = _safe_query_string(status).lower() or None
    if normalized_status == "all":
        normalized_status = None
    normalized_asset_fqn = _safe_query_string(asset_fqn) or None
    if normalized_asset_fqn:
        _require_open_asset(normalized_asset_fqn, request)
    records = classification_service.list_recommendations(
        store,
        status=normalized_status,
        asset_fqn=normalized_asset_fqn,
    )
    if not normalized_asset_fqn:
        records = [
            record
            for record in records
            if _runtime_asset_openable(record.get("assetFqn") or record.get("asset_fqn"), request)
        ]
    return JSONResponse(
        {
            "recommendations": records,
            "count": len(records),
            "pendingCount": sum(1 for rec in records if rec.get("status") == "pending"),
        }
    )


def api_get_classification_recommendation(
    recommendation_id: str,
    request: Request,
) -> JSONResponse:
    store = _resolve_runtime()
    record = classification_service.get_recommendation(store, recommendation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    _require_open_asset(record.get("assetFqn") or record.get("asset_fqn"), request)
    return JSONResponse({"recommendation": record})


async def api_review_classification_recommendation(
    recommendation_id: str,
    payload: ClassificationReviewPayload,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _ensure_can_approve,
        _ensure_live_runtime,
        _http_request_id,
        _store,
        _uc_for_request,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_approve(request)
    actor_role = _user_role_slug(request)
    store = _store()
    record = classification_service.get_recommendation(store, recommendation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    _require_open_asset(record.get("assetFqn") or record.get("asset_fqn"), request)
    decision = _normalize_str(payload.decision).lower()
    if decision not in {"approved", "rejected", "deferred"}:
        raise HTTPException(
            status_code=400,
            detail="decision must be one of approved, rejected, deferred.",
        )
    try:
        updated = classification_service.review_recommendation(
            store,
            recommendation_id,
            decision=decision,
            reviewer=actor_email,
            reviewer_role=actor_role,
            note=_normalize_str(payload.note) or None,
            uc=_uc_for_request(request),
            request_id=_http_request_id(request),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "recommendation": updated})


async def api_scan_classification_recommendations(
    asset_fqn: str,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _ensure_can_mutate,
        _ensure_live_runtime,
        _http_request_id,
        _store,
        _uc_for_request,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request) or "steward"
    store = _store()
    uc = _uc_for_request(request)
    normalized_fqn = _normalize_str(asset_fqn)
    if not normalized_fqn:
        raise HTTPException(status_code=400, detail="asset_fqn is required.")
    parts = [part for part in normalized_fqn.split(".") if part]
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="asset_fqn must be a 3-part UC name.")
    _require_open_asset(normalized_fqn, request)

    # Pull column records + their UC tags via two bulk queries (one for
    # column metadata, one for the column-tag table). This replaces the
    # previous pattern of one `get_column_tags` call per column — which
    # on a 50-column table meant 50+ serialized warehouse queries and
    # pushed us past the Databricks edge-proxy 60s timeout (504 upstream
    # request timeout). Bulk fetch collapses the scan to two queries and
    # ~2s on a warm warehouse.
    columns: List[Dict[str, Any]] = []
    try:
        catalog, schema, table = parts
        df = uc.get_table_columns(catalog, schema, table)
        # Pre-fetch all column tags in a single query.
        tags_by_column: Dict[str, List[Dict[str, Any]]] = {}
        if hasattr(uc, "get_table_column_tags"):
            try:
                tag_df = uc.get_table_column_tags(catalog, schema, table)
                if tag_df is not None and not getattr(tag_df, "empty", True):
                    for _, tag_row in tag_df.iterrows():
                        col_name = str(tag_row.get("column_name") or "").strip()
                        if not col_name:
                            continue
                        tags_by_column.setdefault(col_name, []).append(
                            {
                                "tag_name": str(tag_row.get("tag_name") or "").strip(),
                                "tag_value": str(tag_row.get("tag_value") or "").strip(),
                            }
                        )
            except Exception:
                # Missing `column_tags` system view is expected on some
                # clusters — fall through to the pattern + comment path.
                tags_by_column = {}
        if df is not None and not getattr(df, "empty", True):
            for _, row in df.iterrows():
                col_name = str(row.get("column_name") or "").strip()
                columns.append(
                    {
                        "column_name": col_name,
                        "comment": str(row.get("comment") or "").strip(),
                        "tags": tags_by_column.get(col_name, []),
                    }
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to enumerate columns for classification scan. "
                f"{error_text(exc)}"
            ),
        ) from exc

    recommendations = classification_service.generate_recommendations(
        uc, normalized_fqn, columns
    )
    ids = classification_service.persist_recommendations(
        store,
        recommendations,
        actor_email=actor_email,
        actor_role=actor_role,
        request_id=_http_request_id(request),
    )
    return JSONResponse(
        {
            "ok": True,
            "assetFqn": normalized_fqn,
            "scanned": len(columns),
            "generated": len(recommendations),
            "recommendationIds": ids,
            "recommendations": [
                classification_service.get_recommendation(store, rid) or {} for rid in ids
            ],
        }
    )


def build_classification_router() -> APIRouter:
    router = APIRouter(tags=["classification"])
    router.add_api_route(
        "/api/classification-recommendations",
        api_list_classification_recommendations,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_list_classification_recommendations",
    )
    router.add_api_route(
        "/api/classification-recommendations/scan/{asset_fqn:path}",
        api_scan_classification_recommendations,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_scan_classification_recommendations",
    )
    router.add_api_route(
        "/api/classification-recommendations/{recommendation_id}",
        api_get_classification_recommendation,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_get_classification_recommendation",
    )
    router.add_api_route(
        "/api/classification-recommendations/{recommendation_id}/review",
        api_review_classification_recommendation,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_review_classification_recommendation",
    )
    return router
