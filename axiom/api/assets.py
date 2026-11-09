from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from axiom.api.identity import _request_auth_mode
from axiom.api.response import (
    _cacheable_json_response,
    _error_response,
    _with_meta,
)
from axiom.services import capabilities as capability_service
from axiom.services import assets as asset_service
from axiom.services import governance as governance_service
from axiom.services import input_safety
from axiom.services.assets import normalize_str as _normalize_str


class AssetDescriptionPatch(BaseModel):
    description: str = ""

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, value):
        return input_safety.sanitize_markdown(value, field="description", max_length=8000)


class OwnerAssignment(BaseModel):
    ownerEmail: str
    ownerType: str = "steward"

    @field_validator("ownerEmail", mode="before")
    @classmethod
    def _sanitize_owner_email(cls, value):
        return input_safety.sanitize_email(value, field="ownerEmail", allow_empty=False)

    @field_validator("ownerType", mode="before")
    @classmethod
    def _sanitize_owner_type(cls, value):
        return input_safety.sanitize_allowed(
            value or "steward",
            field="ownerType",
            allowed=("business", "technical", "steward"),
            default="steward",
        )


class AssetOwnersPatch(BaseModel):
    owners: List[OwnerAssignment] = Field(default_factory=list)


BUSINESS_CRITICALITY_VALUES = (
    "Mission Critical",
    "Business Critical",
    "Operational",
    "Low Impact",
    "Not Assessed",
)


class AssetMetadataPatch(BaseModel):
    description: str = ""
    domain: Optional[str] = None
    tier: Optional[str] = None
    certification: Optional[str] = None
    sensitivity: Optional[str] = None
    criticality: Optional[str] = None
    # Business Criticality is orthogonal to tier/criticality (SLA).
    # Demo feedback: stewards want a business-impact axis with fixed
    # enum values, round-tripped to UC tag `business_criticality`.
    businessCriticality: Optional[str] = None
    dataProduct: Optional[str] = None
    # Critical Data Element marker. When set, rides as UC tag
    # `cde=true` (absent tag means "not a CDE"). The rationale text
    # rides alongside as tag `cde_rationale`.
    isCde: Optional[bool] = None
    cdeRationale: Optional[str] = None
    freeformTags: Optional[Dict[str, str]] = None

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, value):
        return input_safety.sanitize_markdown(value, field="description", max_length=8000)

    @field_validator(
        "domain",
        "tier",
        "certification",
        "sensitivity",
        "criticality",
        "dataProduct",
        "cdeRationale",
        mode="before",
    )
    @classmethod
    def _sanitize_optional_short_text(cls, value, info):
        if value is None:
            return None
        return input_safety.sanitize_plain_text(value, field=info.field_name, max_length=512)

    @field_validator("freeformTags", mode="before")
    @classmethod
    def _sanitize_freeform_tags(cls, value):
        return input_safety.sanitize_tag_map(value, field="freeformTags") if value is not None else None

    @field_validator("businessCriticality")
    @classmethod
    def _validate_business_criticality(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return ""
        if normalized not in BUSINESS_CRITICALITY_VALUES:
            allowed = ", ".join(BUSINESS_CRITICALITY_VALUES)
            raise ValueError(f"businessCriticality must be one of: {allowed}")
        return normalized


class AssetTagsPatch(BaseModel):
    tags: Dict[str, str] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def _sanitize_tags(cls, value):
        return input_safety.sanitize_tag_map(value, field="tags")


class AssetAvailabilityRequest(BaseModel):
    assets: List[str] = Field(default_factory=list)


class AssetHeadersRequest(BaseModel):
    assets: List[str] = Field(default_factory=list)

    @field_validator("assets", mode="before")
    @classmethod
    def _sanitize_assets(cls, value):
        if value is None:
            return []
        raw_values = value if isinstance(value, list) else [value]
        cleaned: List[str] = []
        for raw_value in raw_values:
            text = input_safety.sanitize_plain_text(
                raw_value,
                field="assets",
                max_length=512,
            )
            if text:
                cleaned.append(text)
        return cleaned[:64]


class ColumnDescriptionPatch(BaseModel):
    description: str = ""

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, value):
        return input_safety.sanitize_markdown(value, field="description", max_length=8000)


class ColumnTagsPatch(BaseModel):
    tags: Dict[str, str] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def _sanitize_tags(cls, value):
        return input_safety.sanitize_tag_map(value, field="tags")


class ColumnMetadataPatch(BaseModel):
    description: str = ""
    tags: Dict[str, str] = Field(default_factory=dict)

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, value):
        return input_safety.sanitize_markdown(value, field="description", max_length=8000)

    @field_validator("tags", mode="before")
    @classmethod
    def _sanitize_tags(cls, value):
        return input_safety.sanitize_tag_map(value, field="tags")


def api_asset_availability(
    payload: AssetAvailabilityRequest,
    request: Request,
) -> JSONResponse:
    from runtime_app import _asset_availability_payload, _ensure_live_runtime

    _ensure_live_runtime()
    return JSONResponse(_asset_availability_payload(payload.assets, request))


def api_asset_headers(
    payload: AssetHeadersRequest,
    request: Request,
) -> JSONResponse:
    from runtime_app import _asset_headers_payload, _ensure_live_runtime

    _ensure_live_runtime()
    return JSONResponse(_asset_headers_payload(payload.assets, request))


def api_asset_detail(
    asset_fqn: str,
    request: Request,
    sections: List[str] = Query(default=[]),
) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_visibility_record,
        _ensure_live_runtime,
    )

    _ensure_live_runtime()
    # A malformed FQN is a client error (400), not a service outage (503).
    # Returning 503 for a two-part name made monitoring and the frontend treat
    # a bad request as a backend failure and inflated 5xx rates.
    if len([part for part in str(asset_fqn or "").split(".") if part.strip()]) != 3:
        return _error_response(
            request,
            status_code=400,
            source="unity-catalog-detail",
            detail="Expected a three-part Unity Catalog name (catalog.schema.table).",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={"visibilityState": "invalid-fqn"},
        )
    visibility = _asset_visibility_record(asset_fqn, request)
    if visibility.get("visibilityState") == "loading":
        payload = asset_service.asset_loading_payload(asset_fqn)
        reason = (
            visibility.get("reason")
            or "Asset metadata is hydrating from live Unity Catalog inventory."
        )
        # P4 perf fix: loading envelopes must NEVER be HTTP-cacheable. The
        # previous max-age=5 + stale-while-revalidate=30 headers let the
        # browser keep re-serving this stale "loading" body for up to 30s
        # after the server had already hydrated, so client polls never saw
        # real data. no-store forces every poll to hit the server.
        response = JSONResponse(
            _with_meta(
                payload,
                request,
                source="unity-catalog-detail",
                state="loading",
                authoritative=False,
                entity_fqn=asset_fqn,
                entity_id=asset_fqn,
                capabilities={
                    "visibilityState": "loading",
                    "requestedSections": list(sections or []),
                    "resolvedSections": [],
                    "hydrating": True,
                },
                warnings=[reason],
            )
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    if not visibility.get("openable"):
        if visibility.get("visibilityState") == "hidden":
            return _error_response(
                request,
                status_code=404,
                source="unity-catalog-detail",
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
                source="unity-catalog-detail",
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
            source="unity-catalog-detail",
            detail="Asset not found.",
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={
                "visibilityState": visibility.get("visibilityState") or "missing"
            },
        )
    actor_scoped = _request_auth_mode(request) == capability_service.OBO_AVAILABLE_MODE
    protected_sections = {"preview", "operational"}
    requested_sections = list(sections or [])
    resolved_sections = requested_sections
    warnings: List[str] = []
    if not actor_scoped:
        resolved_sections = [
            section
            for section in requested_sections
            if section not in protected_sections
        ]
        if not requested_sections:
            resolved_sections = ["header", "activity", "schema", "properties"]
        elif not resolved_sections:
            resolved_sections = ["header"]
        if set(requested_sections) - set(resolved_sections):
            warnings.append(
                "Protected preview and operational sections were removed because Databricks per-user authorization / OBO is not available."
            )
    payload = _asset_detail_payload(
        asset_fqn, request=request, sections=resolved_sections
    )
    if warnings:
        payload["restrictedSections"] = sorted(
            set(requested_sections) - set(resolved_sections)
        )
    return _cacheable_json_response(
        _with_meta(
            payload,
            request,
            source="unity-catalog-detail",
            state="available" if actor_scoped else "degraded",
            authoritative=actor_scoped,
            entity_fqn=asset_fqn,
            entity_id=asset_fqn,
            capabilities={
                "requestedSections": requested_sections,
                "resolvedSections": resolved_sections,
                "visibilityState": visibility.get("visibilityState"),
            },
            warnings=warnings,
        ),
        request,
        max_age=30,
        stale_while_revalidate=180,
    )


def api_patch_column_description(
    asset_fqn: str,
    column_name: str,
    payload: ColumnDescriptionPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _ensure_asset_column_exists,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _http_request_id,
        _metadata_audit_column_snapshot,
        _record_metadata_audit,
        _uc_for_request,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    _ensure_asset_column_exists(asset_fqn, column_name, request)
    before = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    governance_service.patch_column_description(
        _uc_for_request(request),
        asset_fqn=asset_fqn,
        column_name=column_name,
        description=payload.description or "",
    )
    after = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    _record_metadata_audit(
        entity_type="column",
        action="column-description-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        column_name=column_name,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=payload.description or "",
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "column": column_name,
            "description": payload.description or "",
            "asset": _asset_detail_payload(
                asset_fqn, request=request, sections=["header", "schema"]
            ),
        }
    )


def api_patch_column_tags(
    asset_fqn: str,
    column_name: str,
    payload: ColumnTagsPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _apply_column_tags,
        _asset_detail_payload,
        _asset_is_openable,
        _asset_table_type,
        _ensure_asset_column_exists,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _http_request_id,
        _invalidate_asset_caches,
        _metadata_audit_column_snapshot,
        _record_metadata_audit,
        _tag_write_warning,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    _ensure_asset_column_exists(asset_fqn, column_name, request)
    before = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    requested = {
        _normalize_str(key): _normalize_str(value)
        for key, value in (payload.tags or {}).items()
        if _normalize_str(key) and _normalize_str(value)
    }
    applied = _apply_column_tags(
        asset_fqn,
        column_name,
        payload.tags,
        table_type=_asset_table_type(asset_fqn, request=request),
        updated_by=actor_email,
        request=request,
    )
    _invalidate_asset_caches(asset_fqn)
    after = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    _record_metadata_audit(
        entity_type="column",
        action="column-tags-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        column_name=column_name,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=", ".join(f"{key}={value}" for key, value in requested.items()),
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "column": column_name,
            "tags": applied,
            "asset": _asset_detail_payload(
                asset_fqn, request=request, sections=["header", "schema"]
            ),
            "warning": _tag_write_warning(requested, applied, scope_label="Column"),
        }
    )


def api_patch_column_metadata(
    asset_fqn: str,
    column_name: str,
    payload: ColumnMetadataPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _ensure_asset_column_exists,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _http_request_id,
        _metadata_audit_column_snapshot,
        _record_metadata_audit,
        _uc_for_request,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    _ensure_asset_column_exists(asset_fqn, column_name, request)
    before = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    applied = governance_service.patch_column_metadata(
        _uc_for_request(request),
        asset_fqn=asset_fqn,
        column_name=column_name,
        description=payload.description or "",
        tags=payload.tags,
    )
    after = _metadata_audit_column_snapshot(asset_fqn, column_name, request)
    _record_metadata_audit(
        entity_type="column",
        action="column-metadata-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        column_name=column_name,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=payload.description or "",
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "column": column_name,
            "description": applied["description"],
            "tags": applied["tags"],
            "asset": _asset_detail_payload(
                asset_fqn, request=request, sections=["header", "schema"]
            ),
            "warning": applied.get("warning") or "",
        }
    )


def api_patch_asset_description(
    asset_fqn: str,
    payload: AssetDescriptionPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _governance_summary,
        _http_request_id,
        _metadata_audit_asset_snapshot,
        _record_metadata_audit,
        _uc_for_request,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    before = _metadata_audit_asset_snapshot(asset_fqn, request)
    governance_service.patch_asset_description(
        _uc_for_request(request),
        asset_fqn=asset_fqn,
        description=payload.description or "",
    )
    after = _metadata_audit_asset_snapshot(asset_fqn, request)
    _record_metadata_audit(
        entity_type="asset",
        action="asset-description-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=payload.description or "",
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "description": payload.description or "",
            "asset": _asset_detail_payload(asset_fqn, request=request),
            "governance": _governance_summary(request),
        }
    )


def api_patch_asset_metadata(
    asset_fqn: str,
    payload: AssetMetadataPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _apply_asset_metadata,
        _asset_is_openable,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _governance_summary,
        _http_request_id,
        _metadata_audit_asset_snapshot,
        _record_metadata_audit,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    before = _metadata_audit_asset_snapshot(asset_fqn, request)
    asset, warning = _apply_asset_metadata(asset_fqn, payload, request=request)
    approval_info = asset.get("approval") if isinstance(asset, dict) else None
    if isinstance(approval_info, dict) and approval_info.get("status") == "pending":
        # Write was queued for approval. Skip the "asset-metadata-updated"
        # audit (no UC write happened) and emit a separate "proposed"
        # audit row so the change has a breadcrumb. Return the queued
        # envelope so the frontend can flip to a "pending approval"
        # toast instead of pretending the change applied.
        try:
            _record_metadata_audit(
                entity_type="change_request",
                action="asset-metadata-proposed",
                actor_email=actor_email,
                actor_role=actor_role,
                entity_fqn=asset_fqn,
                entity_id=approval_info.get("requestId") or asset_fqn,
                before=before,
                after={"approval": approval_info},
                detail=payload.description or "",
            )
        except Exception:
            pass
        return JSONResponse(
            {
                "ok": True,
                "fqn": asset_fqn,
                "approval": approval_info,
                "asset": asset,
                "governance": _governance_summary(request),
                "warning": "",
            }
        )
    after = _metadata_audit_asset_snapshot(asset_fqn, request)
    _record_metadata_audit(
        entity_type="asset",
        action="asset-metadata-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=payload.description or "",
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "asset": asset,
            "governance": _governance_summary(request),
            "warning": warning,
        }
    )


def api_patch_asset_owners(
    asset_fqn: str,
    payload: AssetOwnersPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _ensure_can_mutate,
        _ensure_live_runtime,
        _governance_summary,
        _http_request_id,
        _store,
        _uc,
        _user_role_slug,
    )
    from axiom.services import identity_roster

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request)
    store = _store()
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    # Identity integrity: every steward/owner must be a real workspace member.
    # Reject fabricated principals before they reach the store (fail-open when
    # the roster API is unavailable — see identity_roster.validate_principal).
    for owner in payload.owners:
        try:
            identity_roster.validate_principal(
                _uc(), owner.ownerEmail, field="ownerEmail"
            )
        except identity_roster.PrincipalNotInWorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    governance_service.patch_asset_owners(
        store,
        asset_fqn=asset_fqn,
        owner_assignments=[owner.model_dump() for owner in payload.owners],
        updated_by=actor_email,
        replace=True,
        actor_role=actor_role,
        request_id=_http_request_id(request),
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "asset": _asset_detail_payload(asset_fqn, request=request),
            "governance": _governance_summary(request),
        }
    )


def api_patch_asset_tags(
    asset_fqn: str,
    payload: AssetTagsPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _apply_table_tags,
        _asset_detail_payload,
        _asset_is_openable,
        _asset_table_type,
        _ensure_can_mutate_uc_metadata,
        _ensure_live_runtime,
        _http_request_id,
        _invalidate_asset_caches,
        _metadata_audit_asset_snapshot,
        _record_metadata_audit,
        _tag_write_warning,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate_uc_metadata(request)
    actor_role = _user_role_slug(request)
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    before = _metadata_audit_asset_snapshot(asset_fqn, request)
    requested = {
        _normalize_str(key): _normalize_str(value)
        for key, value in (payload.tags or {}).items()
        if _normalize_str(key) and _normalize_str(value)
    }
    applied = _apply_table_tags(
        asset_fqn,
        payload.tags,
        table_type=_asset_table_type(asset_fqn, request=request),
        request=request,
    )
    _invalidate_asset_caches(asset_fqn)
    after = _metadata_audit_asset_snapshot(asset_fqn, request)
    _record_metadata_audit(
        entity_type="asset",
        action="asset-tags-updated",
        actor_email=actor_email,
        actor_role=actor_role,
        entity_fqn=asset_fqn,
        entity_id=asset_fqn,
        request_id=_http_request_id(request),
        before=before,
        after=after,
        detail=", ".join(f"{key}={value}" for key, value in requested.items()),
        fail_closed=True,
    )
    return JSONResponse(
        {
            "ok": True,
            "fqn": asset_fqn,
            "tags": applied,
            "asset": _asset_detail_payload(asset_fqn, request=request),
            "warning": _tag_write_warning(requested, applied, scope_label="Asset"),
        }
    )


def build_assets_router() -> APIRouter:
    router = APIRouter(tags=["assets"])
    router.add_api_route(
        "/api/assets/availability",
        api_asset_availability,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_asset_availability",
    )
    router.add_api_route(
        "/api/assets/headers",
        api_asset_headers,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_asset_headers",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}",
        api_asset_detail,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_asset_detail",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/columns/{column_name}/description",
        api_patch_column_description,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_column_description",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/columns/{column_name}/tags",
        api_patch_column_tags,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_column_tags",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/columns/{column_name}/metadata",
        api_patch_column_metadata,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_column_metadata",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/description",
        api_patch_asset_description,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_asset_description",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/metadata",
        api_patch_asset_metadata,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_asset_metadata",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/owners",
        api_patch_asset_owners,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_asset_owners",
    )
    router.add_api_route(
        "/api/assets/{asset_fqn:path}/tags",
        api_patch_asset_tags,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_patch_asset_tags",
    )
    return router
