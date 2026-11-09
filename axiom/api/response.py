"""Response envelope helpers for the Axiom API.

Builds the `meta` block that every read endpoint attaches to its payload, along
with `_error_response` for failure shapes. Pure formatting — depends only on
identity helpers and capability metadata.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from axiom.api.identity import _request_auth_mode
from axiom.services import capabilities as capability_service
from axiom.services.assets import normalize_str as _normalize_str


REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_REQUEST_ID_HEADER = "X-AXIOM-Client-Request-ID"


def _compute_etag(payload: Dict[str, Any]) -> str:
    # Hash only the business payload (strip meta.observedAt, which changes
    # every call) so an unchanged lineage graph produces a stable ETag and
    # the browser can serve from its HTTP cache via 304.
    try:
        stripped = dict(payload or {})
        if isinstance(stripped.get("meta"), dict):
            stripped_meta = dict(stripped["meta"])
            stripped_meta.pop("observedAt", None)
            stripped_meta.pop("staleAfter", None)
            stripped["meta"] = stripped_meta
        body = json.dumps(stripped, default=str, sort_keys=True).encode("utf-8")
    except Exception:
        body = json.dumps({"fqn": payload.get("fqn")}, default=str).encode("utf-8")
    digest = hashlib.sha1(body).hexdigest()[:20]
    return f'W/"{digest}"'


def _cacheable_json_response(
    payload: Dict[str, Any],
    request: Optional[Request],
    *,
    max_age: int = 60,
    stale_while_revalidate: int = 240,
) -> Response:
    etag = _compute_etag(payload)
    if_none_match = ""
    try:
        if request is not None:
            if_none_match = (request.headers.get("if-none-match") or "").strip()
    except Exception:
        if_none_match = ""
    cache_control = (
        f"private, max-age={max_age}, stale-while-revalidate={stale_while_revalidate}"
    )
    if if_none_match and if_none_match == etag:
        return Response(
            status_code=304,
            headers={"Cache-Control": cache_control, "ETag": etag},
        )
    response = JSONResponse(payload)
    response.headers["Cache-Control"] = cache_control
    response.headers["ETag"] = etag
    response.headers["Vary"] = "Accept-Encoding, X-Forwarded-User"
    return response


def _utc_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


def _future_iso(seconds: int) -> str:
    return _utc_iso(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def _request_scope_warning(request: Optional[Request], source: str) -> str:
    auth_mode = _request_auth_mode(request)
    normalized_source = _normalize_str(source).lower()
    if auth_mode == capability_service.OBO_AVAILABLE_MODE:
        return ""
    if normalized_source.startswith("unity-catalog"):
        return (
            "This response is sourced from workspace-scoped app-principal metadata. "
            "Do not treat it as actor-scoped proof until Databricks per-user authorization / OBO is available."
        )
    return ""


def _request_id(request: Optional[Request]) -> str:
    if request is None:
        return ""
    state = getattr(request, "state", None)
    request_id = _normalize_str(getattr(state, "http_request_id", ""))
    if request_id:
        return request_id
    try:
        return _normalize_str(
            request.headers.get(CLIENT_REQUEST_ID_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
        )
    except Exception:
        return ""


def _response_meta(
    request: Optional[Request],
    *,
    source: str,
    state: str = "available",
    authoritative: bool = True,
    entity_fqn: str | None = None,
    entity_id: str | None = None,
    capabilities: Dict[str, Any] | None = None,
    allowed_actions: Dict[str, Any] | None = None,
    warnings: List[str] | None = None,
    unavailable_reason: str = "",
) -> Dict[str, Any]:
    scope_warning = _request_scope_warning(request, source)
    warning_list = [*(warnings or [])]
    if scope_warning and scope_warning not in warning_list:
        warning_list.append(scope_warning)
    auth_mode = _request_auth_mode(request)
    read_scope = capability_service.runtime_visibility_scope(auth_mode)
    normalized_state = _normalize_str(state) or "unknown"
    resolved_authoritative = bool(authoritative) and not bool(scope_warning)
    if not resolved_authoritative and normalized_state == "available":
        normalized_state = "degraded"
    return {
        "requestId": _request_id(request),
        "httpRequestId": _request_id(request),
        "state": normalized_state,
        "entityId": entity_id,
        "entityFqn": entity_fqn,
        "source": source,
        "authoritative": resolved_authoritative,
        "observedAt": _now_iso(),
        "staleAfter": _future_iso(60),
        "capabilities": capabilities or {},
        "allowedActions": allowed_actions or {},
        "warnings": warning_list,
        "degraded": normalized_state in {"degraded", "unknown"} or bool(warning_list),
        "visibilityScope": read_scope,
        "readScope": read_scope,
        "authMode": auth_mode,
        "productMode": auth_mode,
        "unavailableReason": _normalize_str(unavailable_reason),
    }


def _with_meta(
    payload: Dict[str, Any],
    request: Optional[Request],
    *,
    source: str,
    state: str = "available",
    authoritative: bool = True,
    entity_fqn: str | None = None,
    entity_id: str | None = None,
    capabilities: Dict[str, Any] | None = None,
    allowed_actions: Dict[str, Any] | None = None,
    warnings: List[str] | None = None,
    unavailable_reason: str = "",
) -> Dict[str, Any]:
    next_payload = dict(payload or {})
    resolved_meta = _response_meta(
        request,
        source=source,
        state=state,
        authoritative=authoritative,
        entity_fqn=entity_fqn,
        entity_id=entity_id,
        capabilities=capabilities,
        allowed_actions=allowed_actions,
        warnings=warnings,
        unavailable_reason=unavailable_reason,
    )
    next_payload["authoritative"] = bool(resolved_meta.get("authoritative"))
    next_payload["meta"] = resolved_meta
    next_payload["errors"] = list(next_payload.get("errors") or [])
    return next_payload


def _error_response(
    request: Optional[Request],
    *,
    status_code: int,
    source: str,
    detail: str,
    state: str = "unavailable",
    entity_fqn: str | None = None,
    entity_id: str | None = None,
    capabilities: Dict[str, Any] | None = None,
    warnings: List[str] | None = None,
    extra: Dict[str, Any] | None = None,
) -> JSONResponse:
    payload = dict(extra or {})
    payload["detail"] = detail
    payload["errors"] = list(payload.get("errors") or [{"message": detail}])
    request_id = _request_id(request)
    if request_id:
        payload["requestId"] = request_id
        payload["httpRequestId"] = request_id
    payload["meta"] = _response_meta(
        request,
        source=source,
        state=state,
        authoritative=False,
        entity_fqn=entity_fqn,
        entity_id=entity_id,
        capabilities=capabilities,
        warnings=warnings,
        unavailable_reason=detail,
    )
    payload["authoritative"] = False
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(status_code=status_code, content=payload, headers=headers)
