from __future__ import annotations

import uuid
import threading
import time
from typing import Any, Dict, List, Optional

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from axiom.api.cache import _TTL_CACHE, _invalidate_cache_prefix, _ttl_value
from axiom.services import axiom_metrics
from axiom.services import governance as governance_service
from axiom.services import input_safety
from axiom.services.assets import normalize_str as _normalize_str


_GOVERNANCE_SUMMARY_WARMING: set[str] = set()
_GOVERNANCE_SUMMARY_WARMING_LOCK = threading.Lock()


class GovernanceRequestStatusPatch(BaseModel):
    status: str
    reviewNote: str = ""
    # Triage fields for the Stewardship Workbench: both optional and both
    # sanitized like status. Empty string means "leave unchanged" so a plain
    # status PATCH never clears an existing assignment or priority.
    assignee: str = ""
    priority: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _sanitize_status(cls, value: Any) -> str:
        return input_safety.sanitize_allowed(
            value,
            field="status",
            allowed=("pending", "approved", "rejected", "resolved", "closed"),
        )

    @field_validator("reviewNote", mode="before")
    @classmethod
    def _sanitize_review_note(cls, value: Any) -> str:
        return input_safety.sanitize_markdown(value, field="reviewNote", max_length=4000)

    @field_validator("assignee", mode="before")
    @classmethod
    def _sanitize_assignee(cls, value: Any) -> str:
        return input_safety.sanitize_email(value, field="assignee")

    @field_validator("priority", mode="before")
    @classmethod
    def _sanitize_priority(cls, value: Any) -> str:
        # Allowed set mirrors the workbench picker; "" passes through as a
        # deliberate no-op rather than clearing a recorded priority.
        return input_safety.sanitize_allowed(
            value,
            field="priority",
            allowed=("p0", "p1", "p2", "p3", ""),
        )


class GovernanceNotificationPatch(BaseModel):
    action: str

    @field_validator("action", mode="before")
    @classmethod
    def _sanitize_action(cls, value: Any) -> str:
        return input_safety.sanitize_allowed(
            value,
            field="action",
            allowed=("seen", "read", "dismiss"),
        )


def _summary_sections_from_request(request: Request) -> list[str]:
    raw_values: list[str] = []
    for key in ("section", "sections"):
        try:
            raw_values.extend(request.query_params.getlist(key))
        except Exception:
            value = request.query_params.get(key) if request else ""
            if value:
                raw_values.append(value)
    sections: list[str] = []
    for value in raw_values:
        for part in _normalize_str(value).split(","):
            normalized = _normalize_str(part).lower()
            if normalized == "inbox" and normalized not in sections:
                sections.append(normalized)
    return sections


def _governance_summary_cache_key(request: Request, sections: list[str]) -> str:
    actor = _normalize_str(
        request.headers.get("x-forwarded-email")
        or request.headers.get("x-forwarded-preferred-username")
        or request.headers.get("x-forwarded-user")
        or "unknown"
    ).lower()
    return f"governance_summary_payload:{actor}:{','.join(sorted(sections)) or 'full'}"


def _cached_governance_summary(cache_key: str, ttl_s: int = 300) -> dict[str, Any] | None:
    cached = _TTL_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < ttl_s:
        value = cached[1]
        return value if isinstance(value, dict) else None
    return None


def _warm_governance_summary(request: Request, sections: list[str], cache_key: str) -> None:
    with _GOVERNANCE_SUMMARY_WARMING_LOCK:
        if cache_key in _GOVERNANCE_SUMMARY_WARMING:
            return
        _GOVERNANCE_SUMMARY_WARMING.add(cache_key)

    def warm() -> None:
        try:
            from runtime_app import (
                _ensure_governance_store,
                _ensure_live_runtime,
                _governance_summary,
            )

            _ensure_live_runtime()
            _ensure_governance_store()
            _ttl_value(
                cache_key,
                300,
                lambda: _governance_summary(request, sections=sections or None),
            )
        except Exception:
            pass
        finally:
            with _GOVERNANCE_SUMMARY_WARMING_LOCK:
                _GOVERNANCE_SUMMARY_WARMING.discard(cache_key)

    threading.Thread(
        target=warm,
        name=f"axiom-governance-summary-warm-{cache_key[:24]}",
        daemon=True,
    ).start()


def _invalidate_axiom_composite_caches() -> None:
    for prefix in (
        "axiom_command_center_payload:",
        "axiom_governance_workbench_payload:",
        "axiom_governance_request_detail_payload:",
        "axiom_insights_dashboard_payload:",
        "axiom_cde_dashboard_payload:",
        "axiom_cde_detail_payload:",
        "axiom_audit_evidence_payload:",
        "axiom_taxonomy_overview:",
        "axiom_admin_control_center_payload:",
        "governance_summary_payload:",
    ):
        _invalidate_cache_prefix(prefix)


class GlossaryTermUpsert(BaseModel):
    termId: str = ""
    name: str
    definition: str = ""
    domain: str = ""
    ownerEmail: str = ""
    status: str = "draft"
    reviewers: Optional[List[Dict[str, Any]]] = None
    changeNote: str = ""

    @field_validator("reviewers", mode="before")
    @classmethod
    def _coerce_reviewers(cls, value: Any) -> Any:
        if value is None:
            return None
        return input_safety.sanitize_reviewer_entries(value)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        return governance_service.normalize_glossary_term_status(
            input_safety.sanitize_plain_text(value, field="status", max_length=64)
        )

    @field_validator("termId", "name", "domain", mode="before")
    @classmethod
    def _sanitize_short_text(cls, value: Any, info) -> str:
        return input_safety.sanitize_plain_text(
            value,
            field=info.field_name,
            max_length=256,
            allow_empty=info.field_name != "name",
        )

    @field_validator("definition", "changeNote", mode="before")
    @classmethod
    def _sanitize_markdown_text(cls, value: Any, info) -> str:
        return input_safety.sanitize_markdown(
            value,
            field=info.field_name,
            max_length=4000,
        )

    @field_validator("ownerEmail", mode="before")
    @classmethod
    def _sanitize_owner_email(cls, value: Any) -> str:
        return input_safety.sanitize_email(value, field="ownerEmail")


def api_governance_summary(request: Request) -> JSONResponse:
    from runtime_app import (
        _ensure_governance_store,
        _ensure_live_runtime,
        _governance_summary,
        _store_status_fast,
        _uc_runtime_status_fast,
    )

    sections = _summary_sections_from_request(request)
    if sections and set(sections) <= {"inbox"}:
        cache_key = _governance_summary_cache_key(request, sections)
        cached = _cached_governance_summary(cache_key)
        if cached is not None:
            return JSONResponse(cached)
        runtime_status = _uc_runtime_status_fast(background=True)
        store_status = _store_status_fast(background=True)
        blocking_messages = [
            _normalize_str(runtime_status.get("message"))
            for status in (runtime_status,)
            if _normalize_str(status.get("state")).lower() != "live"
        ]
        blocking_messages.extend(
            _normalize_str(store_status.get("message"))
            for status in (store_status,)
            if _normalize_str(status.get("state")).lower() != "live"
        )
        blocking_messages = [message for message in blocking_messages if message]
        _warm_governance_summary(request, sections, cache_key)
        message = " ".join(blocking_messages) or "Governance inbox is hydrating from the live control plane."
        return JSONResponse(
            {
                "metrics": [],
                "backlog": [],
                "queue": {
                    "scopeKey": "workspace:default",
                    "source": "not-requested",
                    "laneCounts": {},
                    "openTaskCount": 0,
                    "observedAt": "",
                    "staleAfter": "",
                },
                "glossary": [],
                "activity": [],
                "inbox": {
                    "state": "loading",
                    "message": message,
                    "unreadCount": 0,
                    "items": [],
                },
                "sections": ["inbox"],
                "authoritative": False,
                "provenance": {
                    "source": "delta_control_plane",
                    "authoritative": False,
                    "state": "loading",
                    "warnings": [message],
                },
            }
        )

    _ensure_live_runtime()
    _ensure_governance_store()
    return JSONResponse(
        _governance_summary(
            request,
            sections=sections or None,
        )
    )


def api_governance_glossary(request: Request) -> JSONResponse:
    from runtime_app import (
        _ensure_governance_store,
        _ensure_live_runtime,
        _store,
        _uc_for_request,
        _user_email,
    )

    _ensure_live_runtime()
    _ensure_governance_store()
    store = _store()
    actor_email = _user_email(request)
    return JSONResponse(
        {
            "glossary": governance_service.glossary_terms(
                _uc_for_request(request),
                store,
                actor_email=actor_email,
            )
        }
    )


def api_governance_audit_timeline(asset_fqn: str, request: Request) -> JSONResponse:
    """Return a reverse-chronological audit timeline for a single asset.

    Backs the AuditTimelineDrawer on the Governance page. Purely a read over
    the existing metadata_audit_log table — no new schema is required. Entries
    include before/after JSON so the UI can diff changes inline.
    """
    from runtime_app import (
        _asset_is_openable,
        _ensure_governance_store,
        _ensure_live_runtime,
        _store,
    )

    _ensure_live_runtime()
    _ensure_governance_store()

    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")

    store = _store()
    df = store.list_metadata_audit(entity_fqn=asset_fqn, limit=100)

    entries: list[dict[str, object]] = []
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            actor = _normalize_str(row.get("actor_email"))
            entries.append(
                {
                    "auditId": _normalize_str(row.get("audit_id")),
                    # Stable customer-facing AUD id — same derivation as
                    # Audit Evidence, so timeline rows deep-link to
                    # /evidence?event=AUD-… (Wave A4 / teardown P1-7).
                    "displayAuditId": axiom_metrics.audit_display_id(
                        row.get("audit_id"), row=row
                    ),
                    "entityType": _normalize_str(row.get("entity_type")),
                    "entityFqn": _normalize_str(row.get("entity_fqn")),
                    "entityId": _normalize_str(row.get("entity_id")),
                    "columnName": _normalize_str(row.get("column_name")) or None,
                    "action": _normalize_str(row.get("action")),
                    # Humanized server-side so raw slugs ("task-status-updated")
                    # never reach the timeline as display text.
                    "title": axiom_metrics._event_title(
                        _normalize_str(row.get("action"))
                    ),
                    "source": _normalize_str(row.get("source")),
                    "status": _normalize_str(row.get("status")) or "success",
                    "beforeJson": row.get("before_json"),
                    "afterJson": row.get("after_json"),
                    # Both actor names on purpose: renderers variously read
                    # actorEmail or createdBy (teardown P1-7 mismatch).
                    "actorEmail": actor,
                    "createdBy": actor,
                    "actorRole": _normalize_str(row.get("actor_role")),
                    "detail": _normalize_str(row.get("detail")),
                    "createdAt": _normalize_str(row.get("created_at")),
                }
            )

    return JSONResponse(
        {
            "fqn": asset_fqn,
            "entries": entries,
            "total": len(entries),
        }
    )


def api_governance_glossary_term(term_id: str, request: Request) -> JSONResponse:
    from runtime_app import (
        _ensure_governance_store,
        _ensure_live_runtime,
        _store,
        _uc_for_request,
        _user_email,
    )

    _ensure_live_runtime()
    _ensure_governance_store()
    store = _store()
    actor_email = _user_email(request)
    term = governance_service.glossary_term_detail(
        _uc_for_request(request),
        store,
        term_id=_normalize_str(term_id),
        actor_email=actor_email,
    )
    if not term:
        raise HTTPException(status_code=404, detail="Glossary term not found.")
    return JSONResponse({"term": term})


def _api_governance_create_request_sync(
    request: Request,
    fast: bool = Query(
        default=False,
        description="Return a minimal response for UI flows that already carry the selected asset context.",
    ), _payload: Any = None) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _direct_actor_identity_visible,
        _ensure_can_mutate,
        _ensure_live_runtime,
        _governance_summary,
        _http_request_id,
        _store,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request)
    store = _store()
    payload = _payload
    try:
        asset_fqn = input_safety.sanitize_plain_text(
            payload.get("assetFqn"), field="assetFqn", max_length=512, allow_empty=False
        )
        title = input_safety.sanitize_plain_text(
            payload.get("title"), field="title", max_length=256, allow_empty=False
        )
        note = input_safety.sanitize_markdown(payload.get("note"), field="note", max_length=4000)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not asset_fqn or not title:
        raise HTTPException(status_code=400, detail="assetFqn and title are required.")
    if not (
        _asset_is_openable(asset_fqn, request) or
        _direct_actor_identity_visible(asset_fqn, request)
    ):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    request_id = governance_service.create_change_request(
        store,
        created_by=actor_email,
        asset_fqn=asset_fqn,
        title=title,
        note=note,
        actor_role=actor_role,
    )
    if fast is True:
        return JSONResponse({"ok": True, "requestId": request_id, "assetFqn": asset_fqn})
    return JSONResponse(
        {
            "ok": True,
            "requestId": request_id,
            "asset": _asset_detail_payload(asset_fqn, request=request),
            "governance": _governance_summary(request),
        }
    )


async def api_governance_create_request(
    request: Request,
    fast: bool = Query(
        default=False,
        description="Return a minimal response for UI flows that already carry the selected asset context.",
    ),
) -> JSONResponse:
    payload = await request.json()
    return await run_in_threadpool(_api_governance_create_request_sync, request=request, fast=fast, _payload=payload)


def api_governance_patch_request(
    request_id: str,
    payload: GovernanceRequestStatusPatch,
    request: Request,
    fast: bool = Query(
        default=False,
        description="Return a minimal response for row-level status updates that already update local UI state.",
    ),
) -> JSONResponse:
    from runtime_app import (
        _apply_asset_metadata,
        _asset_detail_payload,
        _asset_visibility_record,
        _ensure_can_approve,
        _ensure_live_runtime,
        _governance_summary,
        _invalidate_asset_caches,
        _record_metadata_audit,
        _store,
        _uc,
        _uc_for_request,
        _user_role_slug,
    )
    from axiom.api.assets import AssetMetadataPatch
    from axiom.services import approvals as approval_service
    from axiom.services import identity_roster

    _ensure_live_runtime()
    actor_email = _ensure_can_approve(request)
    actor_role = _user_role_slug(request)
    store = _store()
    raw_request_id = axiom_metrics.resolve_customer_safe_request_id(store, request_id)
    change_request = store.get_change_request(request_id)
    if change_request is None and raw_request_id != request_id:
        change_request = store.get_change_request(raw_request_id)
    if change_request is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    visibility = None
    if change_request.uc_full_name:
        visibility = _asset_visibility_record(change_request.uc_full_name, request)
        if not visibility.get("openable") and visibility.get("visibilityState") != "loading":
            raise HTTPException(
                status_code=404, detail="Asset not found or not visible."
            )
    status = _normalize_str(payload.status).lower()
    if status not in {"pending", "approved", "rejected", "resolved", "closed"}:
        raise HTTPException(
            status_code=400,
            detail="status must be pending, approved, rejected, resolved, or closed.",
        )
    # Identity integrity: a triage assignee must be a real workspace member.
    # "" means "leave unchanged" and is never validated. Fail-open on degraded
    # roster (see identity_roster.validate_principal).
    assignee_value = _normalize_str(payload.assignee).lower()
    if assignee_value:
        try:
            identity_roster.validate_principal(
                _uc_for_request(request), assignee_value, field="assignee",
                fallback_uc=_uc(), actor_email=actor_email,
            )
        except identity_roster.PrincipalNotInWorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Approve/reject is steward/admin-only. Pending-status updates stay
    # open to the proposer so a writer can withdraw their own request.
    if status in {"approved", "rejected"} and not approval_service.role_can_decide(
        actor_role
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Only stewards or admins can approve or reject metadata change"
                " requests."
            ),
        )
    store.set_request_status(
        request_id=raw_request_id,
        status=status,
        reviewed_by=actor_email,
        review_note=_normalize_str(payload.reviewNote) or None,
        actor_role=actor_role,
        refresh_projection=not fast,
        # Triage riders: None (not "") signals "no change" to the store so a
        # status-only PATCH never clears an existing assignment or priority.
        assignee=_normalize_str(payload.assignee).lower() or None,
        priority=_normalize_str(payload.priority).lower() or None,
    )
    apply_warning = ""
    if status == "approved":
        # Re-read the stashed patch and replay the real metadata write
        # with bypass_approval=True so the same helper runs but skips
        # the gate this time. Guard against an empty payload — a
        # corrupt stash must NOT wipe the asset description.
        kind, stash = approval_service.load_pending_patch(store, raw_request_id)
        if kind == approval_service.CHANGE_REQUEST_KIND_ASSET_METADATA:
            stored_patch = stash.get("patch") if isinstance(stash, dict) else {}
            asset_fqn = (
                _normalize_str(stash.get("assetFqn"))
                or change_request.uc_full_name
            )
            if asset_fqn and isinstance(stored_patch, dict) and stored_patch:
                try:
                    applied_model = AssetMetadataPatch(**stored_patch)
                except Exception:
                    applied_model = None
                if applied_model is not None:
                    before = {"approval": {"requestId": raw_request_id}}
                    _, apply_warning = _apply_asset_metadata(
                        asset_fqn,
                        applied_model,
                        request=request,
                        bypass_approval=True,
                    )
                    # Audit the consumed approval so the change request
                    # has a traceable "applied" breadcrumb separate
                    # from the original "proposed" audit row.
                    try:
                        _record_metadata_audit(
                            entity_type="change_request",
                            action="change-request-approved",
                            actor_email=actor_email,
                            actor_role=actor_role,
                            entity_fqn=asset_fqn,
                            entity_id=raw_request_id,
                            before=before,
                            after={"applied": stored_patch},
                            detail="",
                        )
                    except Exception:
                        # Audit is best-effort here — never block the
                        # approval response on a logging hiccup.
                        pass
    if change_request.uc_full_name:
        _invalidate_asset_caches(change_request.uc_full_name)
    else:
        governance_service.invalidate_governance_caches()
        _invalidate_axiom_composite_caches()
    asset_payload = None
    if change_request.uc_full_name and visibility and visibility.get("openable"):
        asset_payload = _asset_detail_payload(
            change_request.uc_full_name,
            request=request,
            sections=("header",) if fast else None,
        )
    governance_payload = None if fast else _governance_summary(request)
    return JSONResponse(
        {
            "ok": True,
            "requestId": axiom_metrics._customer_safe_text(raw_request_id),
            "status": status,
            # Echo applied triage fields ("" when unchanged) so the workbench
            # can update its local row without a full workbench refetch.
            "assignee": _normalize_str(payload.assignee).lower(),
            "priority": _normalize_str(payload.priority).lower(),
            "asset": asset_payload,
            "applyWarning": apply_warning,
            "governance": governance_payload,
            "refreshDeferred": bool(fast),
        }
    )


def api_governance_patch_notification(
    notification_id: str,
    payload: GovernanceNotificationPatch,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _ensure_governance_store,
        _ensure_live_runtime,
        _governance_summary,
        _require_actor_email,
        _store,
    )

    _ensure_live_runtime()
    _ensure_governance_store()
    actor_email = _require_actor_email(request)
    action = _normalize_str(payload.action).lower()
    if action not in {"seen", "read", "dismiss"}:
        raise HTTPException(
            status_code=400, detail="action must be seen, read, or dismiss."
        )
    try:
        _store().update_notification_receipt(
            notification_id=notification_id,
            recipient_email=actor_email,
            action=action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    governance_service.invalidate_governance_caches()
    _invalidate_axiom_composite_caches()
    return JSONResponse(
        {
            "ok": True,
            "notificationId": _normalize_str(notification_id),
            "governance": _governance_summary(request, sections=["inbox"]),
        }
    )


def _api_governance_upsert_owner_sync(request: Request, _payload: Any = None) -> JSONResponse:
    from runtime_app import (
        _asset_detail_payload,
        _asset_is_openable,
        _ensure_can_mutate,
        _ensure_live_runtime,
        _governance_summary,
        _http_request_id,
        _store,
        _uc,
        _uc_for_request,
        _user_role_slug,
    )
    from axiom.services import identity_roster

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request)
    store = _store()
    payload = _payload
    try:
        asset_fqn = input_safety.sanitize_plain_text(
            payload.get("assetFqn"), field="assetFqn", max_length=512, allow_empty=False
        )
        owner_email = input_safety.sanitize_email(
            payload.get("ownerEmail"), field="ownerEmail", allow_empty=False
        )
        owner_type = input_safety.sanitize_allowed(
            payload.get("ownerType") or "steward",
            field="ownerType",
            allowed=("business", "technical", "steward"),
            default="steward",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not asset_fqn or not owner_email:
        raise HTTPException(
            status_code=400, detail="assetFqn and ownerEmail are required."
        )
    # Identity integrity: only real workspace members can be linked as owners /
    # stewards. Fail-open when the roster API is degraded.
    try:
        identity_roster.validate_principal(_uc_for_request(request), owner_email, field="ownerEmail", fallback_uc=_uc(), actor_email=actor_email)
    except identity_roster.PrincipalNotInWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not _asset_is_openable(asset_fqn, request):
        raise HTTPException(status_code=404, detail="Asset not found or not visible.")
    governance_service.add_owner(
        store,
        asset_fqn=asset_fqn,
        owner_email=owner_email,
        owner_type=owner_type,
        updated_by=actor_email,
        actor_role=actor_role,
        request_id=_http_request_id(request),
    )
    return JSONResponse(
        {
            "ok": True,
            "asset": _asset_detail_payload(asset_fqn, request=request),
            "governance": _governance_summary(request),
        }
    )


async def api_governance_upsert_owner(request: Request) -> JSONResponse:
    payload = await request.json()
    return await run_in_threadpool(_api_governance_upsert_owner_sync, request=request, _payload=payload)


def api_identity_workspace_roster(request: Request) -> JSONResponse:
    """Ground-truth roster of real workspace members for owner/steward pickers.

    Steward/admin gated — it enumerates account principals. Returns the cached
    roster snapshot (``available: false`` when the SCIM API is degraded so the
    caller can fall back to free-text without pretending the list is complete).
    """
    from runtime_app import (
        _ensure_can_approve,
        _ensure_live_runtime,
        _uc,
        _uc_for_request,
    )
    from axiom.services import identity_roster

    _ensure_live_runtime()
    _ensure_can_approve(request)
    return JSONResponse(identity_roster.roster_payload(_uc_for_request(request), fallback_uc=_uc()))


def _validate_glossary_principals(
    payload: GlossaryTermUpsert, request: Request, actor_email: str
) -> None:
    """Reject a glossary owner / reviewer roster that references fabricated
    principals. Fail-open on a degraded roster. Called by both the create and
    patch glossary paths so the identity-integrity rule holds on every write.

    ``request`` (for the on-behalf-of UC client) and ``actor_email`` (the
    authenticated writer, always allowed) MUST be threaded from the caller —
    referencing request-scoped globals here was a NameError that 500'd every
    glossary write that carried an owner or reviewer.
    """
    from runtime_app import _uc, _uc_for_request
    from axiom.services import identity_roster

    owner_email = _normalize_str(payload.ownerEmail).lower()
    if owner_email:
        try:
            identity_roster.validate_principal(
                _uc_for_request(request), owner_email, field="ownerEmail",
                fallback_uc=_uc(), actor_email=actor_email,
            )
        except identity_roster.PrincipalNotInWorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for entry in payload.reviewers or []:
        reviewer_email = _normalize_str(
            entry.get("reviewerEmail") if isinstance(entry, dict) else ""
        ).lower()
        if not reviewer_email:
            continue
        try:
            identity_roster.validate_principal(
                _uc_for_request(request), reviewer_email, field="reviewer",
                fallback_uc=_uc(), actor_email=actor_email,
            )
        except identity_roster.PrincipalNotInWorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def api_governance_upsert_glossary(
    payload: GlossaryTermUpsert,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _ensure_can_mutate,
        _ensure_live_runtime,
        _governance_summary,
        _store,
        _uc_for_request,
        _user_email,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request)
    store = _store()
    term_id = _normalize_str(payload.termId) or uuid.uuid4().hex[:12]
    name = _normalize_str(payload.name)
    definition = _normalize_str(payload.definition)
    domain = _normalize_str(payload.domain)
    owner_email = _normalize_str(payload.ownerEmail).lower()
    status = governance_service.normalize_glossary_term_status(payload.status)
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    _validate_glossary_principals(payload, request, actor_email)
    version = governance_service.upsert_glossary_term(
        term_id=term_id,
        name=name,
        definition=definition,
        domain=domain,
        owner_email=owner_email,
        status=status,
        store=store,
        updated_by=actor_email,
        reviewers=payload.reviewers,
        change_note=_normalize_str(payload.changeNote) or None,
        actor_role=actor_role,
    )
    # The /axiom/taxonomy/overview endpoint (which the glossary surface reads)
    # caches its payload in the shared api cache — a separate cache from the
    # governance service's own. Clear it too so a term write (e.g. Approve)
    # reflects immediately on the surface instead of after the 90s TTL.
    _invalidate_cache_prefix("axiom_taxonomy_overview")
    return JSONResponse(
        {
            "ok": True,
            "termId": term_id,
            "term": governance_service.glossary_term_detail(
                _uc_for_request(request),
                store,
                term_id=term_id,
                actor_email=_user_email(request),
            ),
            "version": version,
            "governance": _governance_summary(request),
        }
    )


def api_governance_patch_glossary(
    term_id: str,
    payload: GlossaryTermUpsert,
    request: Request,
) -> JSONResponse:
    from runtime_app import (
        _ensure_can_mutate,
        _ensure_live_runtime,
        _governance_summary,
        _store,
        _uc_for_request,
        _user_email,
        _user_role_slug,
    )

    _ensure_live_runtime()
    actor_email = _ensure_can_mutate(request)
    actor_role = _user_role_slug(request)
    store = _store()
    normalized_term_id = _normalize_str(term_id)
    name = _normalize_str(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    _validate_glossary_principals(payload, request, actor_email)
    version = governance_service.upsert_glossary_term(
        term_id=normalized_term_id,
        name=name,
        definition=_normalize_str(payload.definition),
        domain=_normalize_str(payload.domain),
        owner_email=_normalize_str(payload.ownerEmail).lower(),
        status=governance_service.normalize_glossary_term_status(payload.status),
        store=store,
        updated_by=actor_email,
        reviewers=payload.reviewers,
        change_note=_normalize_str(payload.changeNote) or None,
        actor_role=actor_role,
    )
    _invalidate_cache_prefix("axiom_taxonomy_overview")
    return JSONResponse(
        {
            "ok": True,
            "termId": normalized_term_id,
            "term": governance_service.glossary_term_detail(
                _uc_for_request(request),
                store,
                term_id=normalized_term_id,
                actor_email=_user_email(request),
            ),
            "version": version,
            "governance": _governance_summary(request),
        }
    )


def api_governance_control_decisions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> JSONResponse:
    """G4 — "Controls in action": real governance decisions from the audit log
    (change requests approved/rejected by stewards/admins, with before/after
    status + note). Steward/admin gated. This evidences governance REVIEW
    ACTIVITY, not access enforcement — GA never blocks queries/access, and the
    payload says so plainly."""
    import json as _json

    from runtime_app import _ensure_can_approve, _ensure_live_runtime, _store

    _ensure_live_runtime()
    _ensure_can_approve(request)  # steward/admin only
    store = _store()
    try:
        df = store.list_governance_decisions(limit=int(limit))
    except Exception:
        df = None

    def _parse(value: Any) -> Dict[str, Any]:
        try:
            parsed = _json.loads(value) if value else {}
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}

    decisions: List[Dict[str, Any]] = []
    approved = rejected = 0
    by_outcome: Dict[str, int] = {}
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            after = _parse(row.get("after_json"))
            before = _parse(row.get("before_json"))
            after_status = _normalize_str(after.get("status")).lower()
            action = _normalize_str(row.get("action"))
            decision = after_status or ("approved" if "approved" in action else "updated")
            if decision == "approved":
                approved += 1
            elif decision == "rejected":
                rejected += 1
            # Real outcome distribution — the audit log holds resolutions,
            # approvals, rejections, triage, etc.; count them honestly rather
            # than only approve/reject (which read 0 when the log is mostly
            # workbench resolutions).
            by_outcome[decision] = by_outcome.get(decision, 0) + 1
            decisions.append(
                {
                    "auditId": _normalize_str(row.get("audit_id")),
                    "action": action,
                    "decision": decision,
                    "entityFqn": _normalize_str(row.get("entity_fqn")),
                    "entityId": _normalize_str(row.get("entity_id")),
                    "actor": _normalize_str(row.get("actor_email")),
                    "actorRole": _normalize_str(row.get("actor_role")),
                    "beforeStatus": _normalize_str(before.get("status")),
                    "afterStatus": after_status,
                    "note": _normalize_str(row.get("detail")),
                    "at": _normalize_str(row.get("created_at")),
                }
            )

    return JSONResponse(
        {
            "ok": True,
            "decisions": decisions,
            "summary": {
                "total": len(decisions),
                "approved": approved,
                "rejected": rejected,
                # [{outcome, count}] sorted by count desc for an honest,
                # informative breakdown of what stewards actually did.
                "byOutcome": [
                    {"outcome": outcome, "count": count}
                    for outcome, count in sorted(
                        by_outcome.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
            },
            "scope": "governance-review-activity",
            # Honesty gate (CLAUDE.md): never claim access enforcement.
            "enforcementNote": (
                "These are governance controls in action — change requests approved or rejected by "
                "stewards and admins, with actor, timestamp, and status change. This evidences "
                "governance REVIEW activity, not access enforcement: Axiom does not block "
                "queries, deny logins, or mask rows/columns."
            ),
        }
    )


def build_governance_router() -> APIRouter:
    router = APIRouter(tags=["governance"])
    router.add_api_route(
        "/api/governance/summary",
        api_governance_summary,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_governance_summary",
    )
    router.add_api_route(
        "/api/governance/audit-timeline/{asset_fqn:path}",
        api_governance_audit_timeline,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_governance_audit_timeline",
    )
    router.add_api_route(
        "/api/governance/glossary",
        api_governance_glossary,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_governance_glossary",
    )
    router.add_api_route(
        "/api/governance/glossary/{term_id}",
        api_governance_glossary_term,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_governance_glossary_term",
    )
    router.add_api_route(
        "/api/governance/control-decisions",
        api_governance_control_decisions,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_governance_control_decisions",
    )
    router.add_api_route(
        "/api/governance/requests",
        api_governance_create_request,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_governance_create_request",
    )
    router.add_api_route(
        "/api/governance/requests/{request_id}",
        api_governance_patch_request,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_governance_patch_request",
    )
    router.add_api_route(
        "/api/governance/notifications/{notification_id}",
        api_governance_patch_notification,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_governance_patch_notification",
    )
    router.add_api_route(
        "/api/governance/owners",
        api_governance_upsert_owner,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_governance_upsert_owner",
    )
    router.add_api_route(
        "/api/governance/glossary",
        api_governance_upsert_glossary,
        methods=["POST"],
        response_class=JSONResponse,
        name="api_governance_upsert_glossary",
    )
    router.add_api_route(
        "/api/governance/glossary/{term_id}",
        api_governance_patch_glossary,
        methods=["PATCH"],
        response_class=JSONResponse,
        name="api_governance_patch_glossary",
    )
    router.add_api_route(
        "/api/identity/workspace-roster",
        api_identity_workspace_roster,
        methods=["GET"],
        response_class=JSONResponse,
        name="api_identity_workspace_roster",
    )
    return router
