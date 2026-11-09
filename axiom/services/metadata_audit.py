from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request

from axiom.services.assets import normalize_str as _normalize_str


def audit_asset_snapshot(
    asset_fqn: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    from runtime_app import _asset_detail_payload

    try:
        payload = _asset_detail_payload(asset_fqn, request=request, sections=["header"])
    except Exception:
        return {"fqn": asset_fqn}
    return {
        "fqn": payload.get("fqn") or asset_fqn,
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


def audit_column_snapshot(
    asset_fqn: str,
    column_name: str,
    request: Optional[Request] = None,
) -> Dict[str, Any]:
    from runtime_app import _asset_detail_payload

    try:
        payload = _asset_detail_payload(asset_fqn, request=request, sections=["schema"])
    except Exception:
        return {"assetFqn": asset_fqn, "columnName": column_name}
    column_records = payload.get("columns") or []
    column = next(
        (
            record
            for record in column_records
            if _normalize_str(record.get("name")).lower()
            == _normalize_str(column_name).lower()
        ),
        None,
    )
    if not column:
        return {"assetFqn": asset_fqn, "columnName": column_name}
    return {
        "assetFqn": asset_fqn,
        "columnName": column_name,
        "description": column.get("description"),
        "dataType": column.get("type"),
        "tags": column.get("tags") or [],
        "glossaryTerm": column.get("glossaryTerm"),
    }


def record_audit_log(
    *,
    entity_type: str,
    action: str,
    actor_email: str,
    actor_role: str,
    entity_fqn: str | None = None,
    entity_id: str | None = None,
    column_name: str | None = None,
    request_id: str | None = None,
    before: Any = None,
    after: Any = None,
    source: str = "api",
    status: str = "success",
    detail: str | None = None,
    fail_closed: bool = False,
) -> None:
    from runtime_app import _store

    try:
        store = _store()
    except Exception as exc:
        if fail_closed:
            raise RuntimeError(f"metadata audit store unavailable: {exc}") from exc
        return

    audit_error: Exception | None = None
    try:
        if hasattr(store, "append_metadata_audit_log"):
            store.append_metadata_audit_log(
                entity_type=entity_type,
                action=action,
                actor_email=actor_email,
                actor_role=actor_role,
                entity_fqn=entity_fqn,
                entity_id=entity_id,
                column_name=column_name,
                request_id=request_id,
                before_json=before,
                after_json=after,
                source=source,
                status=status,
                detail=detail,
            )
        else:
            store.append_metadata_audit(
                entity_type=entity_type,
                action=action,
                actor_email=actor_email,
                actor_role=actor_role,
                entity_fqn=entity_fqn,
                entity_id=entity_id,
                column_name=column_name,
                request_id=request_id,
                before=before,
                after=after,
                source=source,
                status=status,
                detail=detail,
            )
    except Exception as exc:
        audit_error = exc
        # Keep calling into change_events even if the audit row failed —
        # audit_log is the primary record but change_events powers the
        # Phase 13 audit browser and projection builders, so emitting
        # both is useful for observability.
        pass

    change_event_id: str | None = None
    if hasattr(store, "append_change_event"):
        try:
            change_event_id = store.append_change_event(
                event_type=f"{entity_type}.{action}",
                entity_kind=entity_type,
                actor_email=actor_email,
                actor_role=actor_role,
                entity_fqn=entity_fqn,
                entity_id=entity_id,
                column_name=column_name,
                request_id=request_id,
                before=before,
                after=after,
                detail=detail,
                source=source,
                status="emitted",
            )
        except Exception:
            change_event_id = None

    # Phase 5 Tranche A — also snapshot the "after" state into
    # entity_versions so the history tab can answer point-in-time
    # questions without replaying the change_events stream.
    if after is not None and hasattr(store, "append_entity_version"):
        try:
            store.append_entity_version(
                entity_kind=entity_type,
                entity_id=entity_id,
                entity_fqn=entity_fqn,
                snapshot=after,
                change_event_id=change_event_id,
                recorded_by=actor_email,
            )
        except Exception:
            return

    if fail_closed and audit_error is not None:
        raise RuntimeError(f"metadata audit write failed: {audit_error}") from audit_error
