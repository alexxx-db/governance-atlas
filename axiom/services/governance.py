from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
import uuid
import json
from typing import Any, Callable, Dict, List, Sequence, Tuple

import pandas as pd

from axiom.bounded_cache import BoundedTTLCache
from axiom.uc import UCSQLClient

from axiom.services import assets as asset_service
# Same AUD-XXXXXXXX derivation the Evidence page uses; importing it (rather
# than re-implementing) keeps activity-row chips joinable to Evidence rows.
from axiom.services.axiom_metrics import audit_display_id


_TTL_CACHE: Dict[str, Tuple[float, Any]] = BoundedTTLCache()
_TTL_REFRESHING: set[str] = set()
_TTL_REFRESH_LOCK = threading.Lock()
_OWNER_TYPES = {"business", "technical", "steward"}
_ASSET_CLASSIFICATION_TAG_KEYS = {"domain", "tier", "certification", "sensitivity"}
_GLOSSARY_TERM_STATUSES = {"draft", "in_review", "approved", "rejected", "deprecated"}


def _ttl_value(key: str, ttl_s: int, loader: Callable[[], Any]) -> Any:
    """TTL cache with stale-while-revalidate.

    The governance summary loader chains ~8 serial warehouse SQL statements
    (inventory + change requests + activity + glossary frames), which is a
    20-33s rebuild on the live warehouse. Blocking the request thread on that
    rebuild every time the TTL lapsed is exactly the 20-33s "warm" latency
    the perf audit measured on /api/governance/summary. On expiry we now
    serve the last good value immediately and rebuild in a background thread;
    only the first-ever call (no stale value) pays the full build cost.
    """
    now = time.time()
    cached = _TTL_CACHE.get(key)
    if cached and now - cached[0] < ttl_s:
        return cached[1]
    if cached is not None:
        # Stale value exists: kick off (at most one) background refresh and
        # serve stale. Failures leave the stale value in place — governance
        # reads must degrade to slightly-old data, never to an error page.
        with _TTL_REFRESH_LOCK:
            should_refresh = key not in _TTL_REFRESHING
            if should_refresh:
                _TTL_REFRESHING.add(key)
        if should_refresh:
            def _refresh() -> None:
                try:
                    try:
                        _TTL_CACHE[key] = (time.time(), loader())
                    except Exception:
                        pass
                finally:
                    with _TTL_REFRESH_LOCK:
                        _TTL_REFRESHING.discard(key)

            threading.Thread(
                target=_refresh,
                name=f"governance-ttl-refresh-{key[:40]}",
                daemon=True,
            ).start()
        return cached[1]
    value = loader()
    _TTL_CACHE[key] = (now, value)
    return value


def _warehouse_key(uc: UCSQLClient) -> str:
    return asset_service.normalize_str(getattr(uc, "warehouse_id", "")) or "default"


def invalidate_governance_caches() -> None:
    _TTL_CACHE.clear()


def _invalidate_asset_dependent_caches(asset_fqn: str | None = None) -> None:
    asset_service.invalidate_asset_caches(asset_fqn)
    invalidate_governance_caches()


def _lookup_key(value: Any) -> str:
    return asset_service.normalize_str(value).lower()


def _visible_asset_keys(inventory: pd.DataFrame | None) -> set[str]:
    if inventory is None or inventory.empty or "fqn" not in inventory.columns:
        return set()
    return {
        _lookup_key(value)
        for value in inventory["fqn"].dropna().astype(str).tolist()
        if _lookup_key(value)
    }


def _filter_request_records_to_visible_assets(
    request_records: Sequence[Dict[str, Any]],
    visible_asset_keys: set[str],
) -> List[Dict[str, Any]]:
    return _filter_records_to_visible_assets(
        request_records,
        visible_asset_keys,
        asset_key="assetFqn",
        keep_orphans=False,
    )


def _filter_records_to_visible_assets(
    records: Sequence[Dict[str, Any]],
    visible_asset_keys: set[str],
    *,
    asset_key: str = "assetFqn",
    keep_orphans: bool = True,
) -> List[Dict[str, Any]]:
    if not records:
        return []
    filtered: List[Dict[str, Any]] = []
    for record in records:
        asset_fqn = asset_service.normalize_str(record.get(asset_key))
        if not asset_fqn:
            if keep_orphans:
                filtered.append(record)
            continue
        if _lookup_key(asset_fqn) not in visible_asset_keys:
            continue
        filtered.append(record)
    return filtered


def _request_title(new_comment: Any) -> str:
    text = asset_service.normalize_str(new_comment)
    if not text:
        return "Governance request"
    if ":" in text:
        return text.split(":", 1)[0].strip() or "Governance request"
    return text


def _request_records(requests_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if requests_df is None or requests_df.empty:
        return []
    records: List[Dict[str, Any]] = []
    for _, row in requests_df.iterrows():
        request_id = asset_service.normalize_str(row.get("request_id"))
        asset_fqn = asset_service.normalize_str(row.get("uc_full_name"))
        status = asset_service.normalize_str(row.get("status")).title() or "Pending"
        created_at = asset_service.normalize_str(row.get("created_at"))
        reviewed_at = asset_service.normalize_str(row.get("reviewed_at"))
        records.append(
            {
                "requestId": request_id,
                "assetFqn": asset_fqn,
                "status": status,
                "title": _request_title(row.get("new_comment")),
                "detail": asset_service.normalize_str(row.get("new_comment")) or "Governance request",
                "createdAt": created_at,
                "createdBy": asset_service.normalize_str(row.get("created_by")),
                "reviewedAt": reviewed_at,
                "reviewedBy": asset_service.normalize_str(row.get("reviewed_by")),
                "reviewNote": asset_service.normalize_str(row.get("review_note")),
            }
        )
    records.sort(
        key=lambda item: (
            asset_service.normalize_str(item.get("createdAt")),
            asset_service.normalize_str(item.get("requestId")),
        ),
        reverse=True,
    )
    return records


# Activity-event type → audit-log actions the SAME store mutation can write.
# create_change_request emits comment_created + task_created events and ONE
# audit row (action task-created); update_workflow_task_status emits an
# optional comment_created + task_state_changed event and ONE audit row
# (task-status-updated | task-triage-updated | task-comment-added). The sets
# below mirror those writers exactly (axiom/store.py) so an activity row can
# only ever bind to an audit row its own mutation path could have produced.
_ACTIVITY_AUDIT_ACTIONS: Dict[str, Tuple[str, ...]] = {
    "task_created": ("task-created",),
    "task_state_changed": (
        "task-status-updated",
        "task-triage-updated",
        "task-comment-added",
    ),
    "comment_created": (
        "task-created",
        "task-status-updated",
        "task-triage-updated",
        "task-comment-added",
    ),
}


def _activity_audit_frame(store: Any, events_df: pd.DataFrame) -> pd.DataFrame:
    """Fetch the audit-log rows backing a batch of activity events.

    Join key: activity_events.task_id == metadata_audit_log.request_id.
    Every task mutation writes its audit row with request_id set to the
    workflow task_id (see create_change_request / update_workflow_task_status
    in axiom/store.py), and every activity event from those same mutations
    carries that task_id — a deterministic equality join, verified against
    the live warehouse (task 59635759… ↔ audit rows fe36d39c…, 45b263d7…).
    """
    if events_df is None or events_df.empty or "task_id" not in events_df.columns:
        return pd.DataFrame()
    if not hasattr(store, "list_metadata_audit_for_requests"):
        return pd.DataFrame()
    task_ids = [
        asset_service.normalize_str(value)
        for value in events_df["task_id"].tolist()
        if asset_service.normalize_str(value)
    ]
    if not task_ids:
        return pd.DataFrame()
    try:
        return store.list_metadata_audit_for_requests(task_ids)
    except Exception:
        # Audit linkage is an enrichment; a failed fetch must never take the
        # whole governance summary down. Rows simply render without AUD ids.
        return pd.DataFrame()


def _audit_rows_by_request(audit_df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}
    if audit_df is None or audit_df.empty:
        return index
    for _, row in audit_df.iterrows():
        request_id = asset_service.normalize_str(row.get("request_id"))
        audit_id = asset_service.normalize_str(row.get("audit_id"))
        if not request_id or not audit_id:
            continue
        index.setdefault(request_id, []).append(
            {
                "auditId": audit_id,
                "action": asset_service.normalize_str(row.get("action")).lower(),
                "createdAt": _parse_utc_timestamp(row.get("created_at")),
            }
        )
    for rows in index.values():
        rows.sort(key=lambda item: (item["createdAt"] or datetime.min.replace(tzinfo=timezone.utc), item["auditId"]))
    return index


def _backing_audit_id(
    event_type: str,
    task_id: str,
    created_at: Any,
    audit_index: Dict[str, List[Dict[str, Any]]],
) -> str:
    """Resolve the audit-log row recorded by the same mutation as an activity event.

    Selection rule — deterministic ordering, NOT a fuzzy timestamp window:
    within one mutation the activity event is inserted BEFORE its single
    audit row (same synchronous Python call, timestamps generated at insert
    time), and any later mutation's audit row is later still. So among the
    audit rows sharing this task_id whose action the event's mutation path
    could have written (_ACTIVITY_AUDIT_ACTIONS), the FIRST row at-or-after
    the event's timestamp is the same mutation's record. Verified live:
    task_state_changed@14:59:35 → task-triage-updated@14:59:37, never the
    later 00:02:29 row. No candidate → "" (never fabricate).
    """
    if not task_id:
        return ""
    actions = _ACTIVITY_AUDIT_ACTIONS.get(asset_service.normalize_str(event_type).lower())
    if not actions:
        return ""
    event_ts = _parse_utc_timestamp(created_at)
    if event_ts is None:
        return ""
    for candidate in audit_index.get(task_id, []):
        if candidate["action"] not in actions:
            continue
        candidate_ts = candidate["createdAt"]
        if candidate_ts is None or candidate_ts < event_ts:
            continue
        return candidate["auditId"]
    return ""


def _activity_records(
    events_df: pd.DataFrame,
    audit_index: Dict[str, List[Dict[str, Any]]] | None = None,
) -> List[Dict[str, Any]]:
    if events_df is None or events_df.empty:
        return []
    title_map = {
        "comment_created": "Comment added",
        "task_created": "Task created",
        "task_state_changed": "Task updated",
    }
    records: List[Dict[str, Any]] = []
    for _, row in events_df.iterrows():
        event_type = asset_service.normalize_str(row.get("event_type")).lower()
        payload = {}
        raw_payload = row.get("payload_json")
        if asset_service.normalize_str(raw_payload):
            try:
                parsed = json.loads(str(raw_payload))
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                payload = {}
        resolution_code = asset_service.normalize_str(payload.get("resolutionCode")).lower()
        task_status = asset_service.normalize_str(payload.get("status")).lower()
        status = "Pending"
        if resolution_code == "approved" or task_status in {"resolved", "closed"}:
            status = "Approved"
        elif resolution_code == "rejected" or task_status == "rejected":
            status = "Rejected"
        detail = (
            asset_service.normalize_str(payload.get("body"))
            or asset_service.normalize_str(payload.get("title"))
            or asset_service.normalize_str(payload.get("reviewNote"))
            or asset_service.normalize_str(payload.get("status"))
            or title_map.get(event_type)
            or "Governance activity"
        )
        # Evidence linkage: activity event_ids live in a different id space
        # from metadata_audit_log audit_ids, so the summary joins each row to
        # its backing audit event (task_id == request_id, see
        # _backing_audit_id) and emits the same AUD-XXXXXXXX display id the
        # Evidence page uses. Empty strings when no backing event exists.
        audit_event_id = _backing_audit_id(
            event_type,
            asset_service.normalize_str(row.get("task_id")),
            row.get("created_at"),
            audit_index or {},
        )
        # "AUD-" + first 8 hex chars of the audit event id — identical to the
        # Evidence page derivation so the chip deep-links to the same row.
        display_audit_id = audit_display_id(audit_event_id) if audit_event_id else ""
        records.append(
            {
                "eventId": asset_service.normalize_str(row.get("event_id")),
                "eventType": event_type,
                "assetFqn": asset_service.normalize_str(row.get("entity_fqn_snapshot")),
                "status": status,
                "title": title_map.get(event_type, "Governance activity"),
                "detail": detail,
                "createdAt": asset_service.normalize_str(row.get("created_at")),
                "createdBy": asset_service.normalize_str(row.get("actor_email"))
                or asset_service.normalize_str(row.get("actor_display_name")),
                "displayAuditId": display_audit_id,
                "auditEventId": audit_event_id,
            }
        )
    records.sort(
        key=lambda item: (
            asset_service.normalize_str(item.get("createdAt")),
            asset_service.normalize_str(item.get("eventId")),
        ),
        reverse=True,
    )
    return records


def _inbox_records(notifications_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if notifications_df is None or notifications_df.empty:
        return []
    records: List[Dict[str, Any]] = []
    for _, row in notifications_df.iterrows():
        payload = {}
        raw_payload = row.get("payload_json")
        if asset_service.normalize_str(raw_payload):
            try:
                parsed = json.loads(str(raw_payload))
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                payload = {}
        records.append(
            {
                "notificationId": asset_service.normalize_str(row.get("notification_id")),
                "eventId": asset_service.normalize_str(row.get("event_id")),
                "eventType": asset_service.normalize_str(payload.get("eventType")),
                "title": asset_service.normalize_str(payload.get("title")) or "Governance notification",
                "detail": asset_service.normalize_str(payload.get("detail")),
                "status": asset_service.normalize_str(payload.get("status")),
                "assetFqn": asset_service.normalize_str(payload.get("assetFqn")),
                "assetLabel": asset_service.normalize_str(payload.get("assetLabel"))
                or asset_service.normalize_str(payload.get("assetFqn")),
                "taskId": asset_service.normalize_str(payload.get("taskId")),
                "threadId": asset_service.normalize_str(payload.get("threadId")),
                "createdAt": asset_service.normalize_str(row.get("created_at"))
                or asset_service.normalize_str(payload.get("createdAt")),
                "createdBy": asset_service.normalize_str(payload.get("createdBy")),
                "inboxState": asset_service.normalize_str(row.get("inbox_state")).lower() or "new",
            }
        )
    records.sort(
        key=lambda item: (
            asset_service.normalize_str(item.get("createdAt")),
            asset_service.normalize_str(item.get("notificationId")),
        ),
        reverse=True,
    )
    return records


def _json_string_list(value: Any) -> List[str]:
    raw = asset_service.normalize_str(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [asset_service.normalize_str(item) for item in parsed if asset_service.normalize_str(item)]


def _sorted_recent_requests(requests: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    if not requests:
        return []
    return requests[:limit]


def _request_lane(request_record: Dict[str, Any]) -> str:
    text = " ".join(
        [
            asset_service.normalize_str(request_record.get("title")),
            asset_service.normalize_str(request_record.get("detail")),
            asset_service.normalize_str(request_record.get("assetFqn")),
            asset_service.normalize_str(request_record.get("status")),
        ]
    ).lower()
    if "owner" in text:
        return "ownership"
    if any(token in text for token in ("cert", "classif", "sensit", "privacy")):
        return "classification"
    if any(token in text for token in ("domain", "tier", "trust")):
        return "trust"
    return "open-work"


def _queue_summary_from_live_requests(request_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    lane_counts = {
        "open-work": 0,
        "ownership": 0,
        "classification": 0,
        "trust": 0,
    }
    for request_record in request_records:
        lane_counts[_request_lane(request_record)] += 1
    return {
        "scopeKey": "workspace:default",
        "source": "live",
        "laneCounts": lane_counts,
        "openTaskCount": len(request_records),
        # The queue is built from visible-estate-scoped request records; ship
        # the scope with the data so the UI captions it correctly.
        "scope": "visible-estate",
        "scopeCaption": "Open requests on assets in the visible estate",
        "observedAt": "",
        "staleAfter": "",
    }


def _parse_utc_timestamp(value: Any) -> datetime | None:
    text = asset_service.normalize_str(value)
    if not text:
        return None
    for candidate in (text.replace("Z", "+00:00"), text):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _projection_is_fresh(summary: Dict[str, Any]) -> bool:
    stale_after = _parse_utc_timestamp(summary.get("staleAfter"))
    if stale_after is None:
        return True
    return stale_after >= datetime.now(timezone.utc)


def _glossary_summary_projection_map(projections_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if projections_df is None or projections_df.empty:
        return {}
    projection_map: Dict[str, Dict[str, Any]] = {}
    for _, row in projections_df.iterrows():
        term_id = asset_service.normalize_str(row.get("term_id")) or asset_service.normalize_str(
            row.get("termId")
        )
        if not term_id:
            continue
        projection_map[_lookup_key(term_id)] = {
            "termId": term_id,
            "assetCount": int(row.get("asset_count") or row.get("assetCount") or 0),
            "childCount": int(row.get("child_count") or row.get("childCount") or 0),
            "reviewerCount": int(row.get("reviewer_count") or row.get("reviewerCount") or 0),
            "observedAt": asset_service.normalize_str(row.get("observed_at"))
            or asset_service.normalize_str(row.get("observedAt")),
            "staleAfter": asset_service.normalize_str(row.get("stale_after"))
            or asset_service.normalize_str(row.get("staleAfter")),
            "source": "projection",
        }
    return projection_map


def _reviewer_records(reviewers_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if reviewers_df is None or reviewers_df.empty:
        return []
    records: List[Dict[str, Any]] = []
    for _, row in reviewers_df.iterrows():
        term_id = asset_service.normalize_str(row.get("term_id"))
        reviewer_email = asset_service.normalize_str(row.get("reviewer_email")).lower()
        if not term_id or not reviewer_email:
            continue
        records.append(
            {
                "termId": term_id,
                "reviewerEmail": reviewer_email,
                "reviewerRole": asset_service.normalize_str(row.get("reviewer_role")).lower()
                or "reviewer",
                "createdAt": asset_service.normalize_str(row.get("created_at")),
                "createdBy": asset_service.normalize_str(row.get("created_by")),
                "updatedAt": asset_service.normalize_str(row.get("updated_at")),
                "updatedBy": asset_service.normalize_str(row.get("updated_by")),
            }
        )
    records.sort(
        key=lambda item: (
            asset_service.normalize_str(item.get("termId")),
            asset_service.normalize_str(item.get("reviewerRole")),
            asset_service.normalize_str(item.get("reviewerEmail")),
        )
    )
    return records


def _version_records(versions_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if versions_df is None or versions_df.empty:
        return []
    records: List[Dict[str, Any]] = []
    for _, row in versions_df.iterrows():
        term_id = asset_service.normalize_str(row.get("term_id"))
        if not term_id:
            continue
        reviewer_snapshot: List[Dict[str, Any]] = []
        raw_snapshot = row.get("reviewer_snapshot_json")
        if asset_service.normalize_str(raw_snapshot):
            try:
                parsed = json.loads(str(raw_snapshot))
                if isinstance(parsed, list):
                    reviewer_snapshot = [
                        item
                        for item in parsed
                        if isinstance(item, dict)
                    ]
            except Exception:
                reviewer_snapshot = []
        records.append(
            {
                "versionId": asset_service.normalize_str(row.get("version_id")),
                "termId": term_id,
                "versionNumber": int(row.get("version_number") or 0),
                "action": asset_service.normalize_str(row.get("action")) or "updated",
                "changeNote": asset_service.normalize_str(row.get("change_note")),
                "name": asset_service.normalize_str(row.get("name")),
                "definition": asset_service.normalize_str(row.get("definition")),
                "domain": asset_service.normalize_str(row.get("domain")),
                "ownerEmail": asset_service.normalize_str(row.get("owner_email")),
                "status": asset_service.normalize_str(row.get("status")),
                "reviewerSnapshot": reviewer_snapshot,
                "createdAt": asset_service.normalize_str(row.get("created_at")),
                "createdBy": asset_service.normalize_str(row.get("created_by")),
                "updatedAt": asset_service.normalize_str(row.get("updated_at")),
                "updatedBy": asset_service.normalize_str(row.get("updated_by")),
            }
        )
    records.sort(
        key=lambda item: (
            asset_service.normalize_str(item.get("termId")),
            -int(item.get("versionNumber") or 0),
            asset_service.normalize_str(item.get("createdAt")),
        )
    )
    return records


def _asset_preview_record(row: pd.Series) -> Dict[str, Any]:
    payload = asset_service.base_asset_payload(row)
    return {
        "fqn": payload.get("fqn"),
        "name": payload.get("name"),
        "catalog": payload.get("catalog"),
        "schema": payload.get("schema"),
        "domain": payload.get("domain"),
        "tier": payload.get("tier"),
        "certification": payload.get("certification"),
        "openRequests": payload.get("openRequests"),
        "coverageScore": payload.get("coverageScore"),
        "owners": payload.get("owners"),
        "governanceStatus": payload.get("governanceStatus"),
    }


def _normalized_tag_map(df: pd.DataFrame) -> Dict[str, str]:
    if df is None or df.empty:
        return {}
    tags: Dict[str, str] = {}
    for _, row in df.iterrows():
        key = asset_service.normalize_str(row.get("tag_name"))
        value = asset_service.normalize_str(row.get("tag_value"))
        if key:
            tags[key] = value
    return tags


def normalized_tag_values(tags: Dict[str, str] | None) -> Dict[str, str]:
    return {
        asset_service.normalize_str(key): asset_service.normalize_str(value)
        for key, value in (tags or {}).items()
        if asset_service.normalize_str(key) and asset_service.normalize_str(value)
    }


def tag_write_warning(
    requested_tags: Dict[str, str],
    applied_tags: Dict[str, str],
    *,
    scope_label: str,
) -> str:
    if normalized_tag_values(requested_tags) == normalized_tag_values(applied_tags):
        return ""
    return (
        f"{scope_label} tags did not round-trip through Unity Catalog in this workspace. "
        "The record description was saved, but tag updates were not visible after write verification."
    )


def _relation_table_type(
    uc: UCSQLClient,
    *,
    catalog: str,
    schema: str,
    table: str,
) -> str:
    try:
        identity_df = uc.get_table_identity(catalog, schema, table)
    except Exception:
        return ""
    if identity_df is None or identity_df.empty:
        return ""
    return asset_service.normalize_str(identity_df.iloc[0].get("table_type"))


def normalize_glossary_term_status(value: Any) -> str:
    normalized = asset_service.normalize_str(value).lower() or "draft"
    if normalized not in _GLOSSARY_TERM_STATUSES:
        allowed = ", ".join(sorted(_GLOSSARY_TERM_STATUSES))
        raise ValueError(f"Glossary status must be one of: {allowed}.")
    return normalized


def _glossary_rows_from_frames(
    store: Any,
    *,
    inventory: pd.DataFrame,
    glossary_df: pd.DataFrame,
    reviewers_df: pd.DataFrame,
    versions_df: pd.DataFrame,
    requests_df: pd.DataFrame,
    glossary_summary_df: pd.DataFrame | None = None,
) -> List[Dict[str, Any]]:
    if glossary_df is None or glossary_df.empty:
        return []

    visible_asset_keys = _visible_asset_keys(inventory)
    request_records = _request_records(requests_df)
    requests_by_asset: Dict[str, List[Dict[str, Any]]] = {}
    for request_record in request_records:
        asset_fqn = _lookup_key(request_record.get("assetFqn"))
        if not asset_fqn:
            continue
        requests_by_asset.setdefault(asset_fqn, []).append(request_record)

    glossary_asset_map: Dict[str, List[str]] = {}
    glossary_asset_preview_map: Dict[str, List[Dict[str, Any]]] = {}
    glossary_link_source_by_term: Dict[str, str] = {}
    reviewer_roster_by_term: Dict[str, List[Dict[str, Any]]] = {}
    version_history_by_term: Dict[str, List[Dict[str, Any]]] = {}
    child_count_by_term: Dict[str, int] = {}
    glossary_summary_by_term = _glossary_summary_projection_map(
        glossary_summary_df if glossary_summary_df is not None else pd.DataFrame()
    )

    if "parent_term_id" in glossary_df.columns:
        for parent_term_id, child_rows in glossary_df.groupby("parent_term_id", dropna=False):
            parent_key = _lookup_key(parent_term_id)
            if parent_key:
                child_count_by_term[parent_key] = int(len(child_rows.index))

    for reviewer_record in _reviewer_records(reviewers_df):
        reviewer_roster_by_term.setdefault(_lookup_key(reviewer_record.get("termId")), []).append(
            reviewer_record
        )
    for version_record in _version_records(versions_df):
        version_history_by_term.setdefault(_lookup_key(version_record.get("termId")), []).append(
            version_record
        )

    glossary_links_df = pd.DataFrame()
    try:
        glossary_links_df = (
            store.list_glossary_term_links()
            if hasattr(store, "list_glossary_term_links")
            else pd.DataFrame()
        )
    except Exception:
        glossary_links_df = pd.DataFrame()
    if glossary_links_df is not None and not glossary_links_df.empty:
        active_links = glossary_links_df.copy()
        if "removed_at" in active_links.columns:
            active_links = active_links[active_links["removed_at"].isna()].copy()
        if "resolution_state" in active_links.columns:
            active_links = active_links[
                active_links["resolution_state"]
                .fillna("")
                .astype(str)
                .str.lower()
                .isin({"", "linked", "unresolved"})
            ].copy()
        if not active_links.empty:
            active_links["term_key"] = active_links["term_id"].map(_lookup_key)
            asset_term_links = active_links[
                active_links["subject_type"].fillna("").astype(str).str.lower().eq("asset")
            ].copy()
            if not asset_term_links.empty:
                glossary_link_source_by_term.update(
                    {
                        str(term_key): "links"
                        for term_key in asset_term_links["term_key"].dropna().astype(str).tolist()
                    }
                )
                glossary_asset_map = (
                    asset_term_links.groupby("term_key")["subject_fqn"]
                    .apply(
                        lambda series: [
                            str(item)
                            for item in series.tolist()
                            if str(item)
                        ]
                    )
                    .to_dict()
                )
                glossary_asset_preview_map = {
                    str(term_key): [
                        _asset_preview_record(row)
                        for _, row in inventory[inventory["fqn"].isin(group)].head(8).iterrows()
                    ]
                    for term_key, group in glossary_asset_map.items()
                    if inventory is not None and not inventory.empty
                }

    if inventory is not None and not inventory.empty and "glossary_term" in inventory.columns:
        glossary_inventory = inventory[
            inventory["glossary_term"].fillna("").astype(str).ne("")
        ].copy()
        if not glossary_inventory.empty:
            glossary_inventory = glossary_inventory.assign(
                _glossary_term_key=glossary_inventory["glossary_term"].map(_lookup_key)
            )
            for term_key, series in glossary_inventory.groupby("_glossary_term_key")["fqn"]:
                term_key_str = str(term_key)
                if term_key_str in glossary_asset_map:
                    continue
                glossary_link_source_by_term[term_key_str] = "tags"
                glossary_asset_map[term_key_str] = [
                    str(item)
                    for item in series.tolist()
                    if str(item)
                ]
                glossary_asset_preview_map[term_key_str] = [
                    _asset_preview_record(row)
                    for _, row in glossary_inventory[
                        glossary_inventory["_glossary_term_key"] == term_key
                    ].head(8).iterrows()
                ]

    glossary_rows: List[Dict[str, Any]] = []
    for _, row in glossary_df.iterrows():
        term_name = asset_service.normalize_str(row.get("name"))
        term_key = _lookup_key(term_name)
        term_id = asset_service.normalize_str(row.get("term_id"))
        term_id_key = _lookup_key(term_id)
        related_assets_all = (
            glossary_asset_map.get(_lookup_key(term_id), [])
            or glossary_asset_map.get(term_key, [])
        )
        related_assets = [
            asset_fqn for asset_fqn in related_assets_all if _lookup_key(asset_fqn) in visible_asset_keys
        ]
        related_requests: List[Dict[str, Any]] = []
        seen_requests: set[str] = set()
        for asset_fqn in related_assets:
            for request_record in requests_by_asset.get(_lookup_key(asset_fqn), []):
                request_id = asset_service.normalize_str(request_record.get("requestId"))
                if request_id and request_id in seen_requests:
                    continue
                if request_id:
                    seen_requests.add(request_id)
                related_requests.append(request_record)
        related_requests.sort(
            key=lambda item: (
                asset_service.normalize_str(item.get("createdAt")),
                asset_service.normalize_str(item.get("requestId")),
            ),
            reverse=True,
        )
        reviewer_roster = reviewer_roster_by_term.get(_lookup_key(term_id), [])
        version_history = version_history_by_term.get(_lookup_key(term_id), [])
        association_source = glossary_link_source_by_term.get(term_id_key, "tags")
        glossary_projection = glossary_summary_by_term.get(term_id_key, {})
        projection_fresh = bool(glossary_projection) and _projection_is_fresh(glossary_projection)
        asset_count = len(related_assets)
        if (
            projection_fresh
            and association_source == "links"
            and len(related_assets_all) == len(related_assets)
        ):
            asset_count = int(glossary_projection.get("assetCount") or 0)
        reviewer_count = (
            int(glossary_projection.get("reviewerCount") or 0)
            if projection_fresh
            else len(reviewer_roster)
        )
        child_count = (
            int(glossary_projection.get("childCount") or 0)
            if projection_fresh
            else int(child_count_by_term.get(term_id_key, 0))
        )
        glossary_rows.append(
            {
                "termId": term_id,
                "parentTermId": asset_service.normalize_str(row.get("parent_term_id")) or None,
                "term": term_name,
                "definition": asset_service.normalize_str(row.get("definition")) or "No definition",
                "synonyms": _json_string_list(row.get("synonyms_json")),
                "synonyms_json": asset_service.normalize_str(row.get("synonyms_json")),
                "domain": asset_service.normalize_str(row.get("domain")) or "Unassigned",
                "ownerEmail": asset_service.normalize_str(row.get("owner_email")) or "Unassigned",
                "status": asset_service.normalize_str(row.get("status")).title() or "Draft",
                "assetCount": asset_count,
                "childCount": child_count,
                "reviewerCount": reviewer_count,
                "assets": related_assets,
                "assetPreview": glossary_asset_preview_map.get(_lookup_key(term_id), [])
                or glossary_asset_preview_map.get(term_key, []),
                "associationSource": association_source,
                "summarySource": glossary_projection.get("source") if projection_fresh else "live",
                "summaryObservedAt": asset_service.normalize_str(glossary_projection.get("observedAt")),
                "summaryStaleAfter": asset_service.normalize_str(glossary_projection.get("staleAfter")),
                "createdAt": asset_service.normalize_str(row.get("created_at")),
                "createdBy": asset_service.normalize_str(row.get("created_by")),
                "updatedAt": asset_service.normalize_str(row.get("updated_at")),
                "updatedBy": asset_service.normalize_str(row.get("updated_by")),
                "reviewerRoster": reviewer_roster,
                "reviewers": [
                    entry.get("reviewerEmail")
                    for entry in reviewer_roster
                    if entry.get("reviewerEmail")
                ],
                "reviewState": asset_service.normalize_str(row.get("status")).title() or "Draft",
                "currentVersion": (
                    f"v{version_history[0].get('versionNumber')}"
                    if version_history and version_history[0].get("versionNumber")
                    else ""
                ),
                "termHistory": version_history,
                "versionHistory": version_history,
                "versions": version_history,
                "versionCount": len(version_history),
                "latestVersion": version_history[0] if version_history else None,
                "requestCount": len(related_requests),
                "pendingRequestCount": sum(
                    1
                    for request_record in related_requests
                    if asset_service.normalize_str(request_record.get("status")).lower()
                    == "pending"
                ),
                "approvedRequestCount": sum(
                    1
                    for request_record in related_requests
                    if asset_service.normalize_str(request_record.get("status")).lower()
                    == "approved"
                ),
                "rejectedRequestCount": sum(
                    1
                    for request_record in related_requests
                    if asset_service.normalize_str(request_record.get("status")).lower()
                    == "rejected"
                ),
                "recentRequests": _sorted_recent_requests(related_requests, 4),
            }
        )
    return glossary_rows


def glossary_terms(
    uc: UCSQLClient,
    store: Any,
    *,
    actor_email: str | None = None,
    hidden_catalogs: set[str] = asset_service.HIDDEN_CATALOGS,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    def _loader() -> List[Dict[str, Any]]:
        inventory = asset_service.visible_assets(
            uc,
            store,
            hidden_catalogs=hidden_catalogs,
        )
        try:
            glossary_df = store.list_glossary_terms(limit=limit)
        except Exception:
            glossary_df = pd.DataFrame()
        try:
            reviewers_df = store.list_glossary_reviewers()
        except Exception:
            reviewers_df = pd.DataFrame()
        try:
            versions_df = store.list_glossary_versions()
        except Exception:
            versions_df = pd.DataFrame()
        try:
            requests_df = store.list_change_requests(limit=5000)
        except Exception:
            requests_df = pd.DataFrame()
        try:
            glossary_summary_df = (
                store.list_glossary_summary_projections()
                if hasattr(store, "list_glossary_summary_projections")
                else pd.DataFrame()
            )
        except Exception:
            glossary_summary_df = pd.DataFrame()
        return _glossary_rows_from_frames(
            store,
            inventory=inventory,
            glossary_df=glossary_df,
            reviewers_df=reviewers_df,
            versions_df=versions_df,
            requests_df=requests_df,
            glossary_summary_df=glossary_summary_df,
        )

    actor_key = _lookup_key(actor_email) or "anonymous"
    return _ttl_value(f"governance-glossary:{_warehouse_key(uc)}:{actor_key}", 300, _loader)


def glossary_term_detail(
    uc: UCSQLClient,
    store: Any,
    *,
    term_id: str,
    actor_email: str | None = None,
    hidden_catalogs: set[str] = asset_service.HIDDEN_CATALOGS,
) -> Dict[str, Any] | None:
    normalized_term_id = asset_service.normalize_str(term_id)
    if not normalized_term_id:
        return None

    def _loader() -> Dict[str, Any] | None:
        term_row: pd.Series | None = None
        if hasattr(store, "get_glossary_term"):
            try:
                term_row = store.get_glossary_term(normalized_term_id)
            except Exception:
                term_row = None
        if (term_row is None or term_row.empty) and hasattr(store, "list_glossary_terms"):
            try:
                glossary_candidates = store.list_glossary_terms(limit=5000)
            except Exception:
                glossary_candidates = pd.DataFrame()
            if (
                glossary_candidates is not None
                and not glossary_candidates.empty
                and "term_id" in glossary_candidates.columns
            ):
                matches = glossary_candidates[
                    glossary_candidates["term_id"].fillna("").astype(str).eq(normalized_term_id)
                ]
                if not matches.empty:
                    term_row = matches.iloc[0]
        if term_row is None or term_row.empty:
            return None
        glossary_df = pd.DataFrame([term_row.to_dict()])
        inventory = asset_service.visible_assets(
            uc,
            store,
            hidden_catalogs=hidden_catalogs,
        )
        try:
            reviewers_df = (
                store.list_glossary_reviewers(term_id=normalized_term_id)
                if hasattr(store, "list_glossary_reviewers")
                else pd.DataFrame()
            )
        except Exception:
            reviewers_df = pd.DataFrame()
        try:
            versions_df = (
                store.list_glossary_versions(term_id=normalized_term_id)
                if hasattr(store, "list_glossary_versions")
                else pd.DataFrame()
            )
        except Exception:
            versions_df = pd.DataFrame()
        try:
            requests_df = store.list_change_requests(limit=5000)
        except Exception:
            requests_df = pd.DataFrame()
        try:
            glossary_summary = (
                store.get_glossary_summary_projection(normalized_term_id)
                if hasattr(store, "get_glossary_summary_projection")
                else None
            )
            glossary_summary_df = pd.DataFrame([glossary_summary]) if glossary_summary else pd.DataFrame()
        except Exception:
            glossary_summary_df = pd.DataFrame()
        rows = _glossary_rows_from_frames(
            store,
            inventory=inventory,
            glossary_df=glossary_df,
            reviewers_df=reviewers_df,
            versions_df=versions_df,
            requests_df=requests_df,
            glossary_summary_df=glossary_summary_df,
        )
        return rows[0] if rows else None

    actor_key = _lookup_key(actor_email) or "anonymous"
    return _ttl_value(
        f"governance-glossary-term:{_warehouse_key(uc)}:{actor_key}:{normalized_term_id}",
        300,
        _loader,
    )


def governance_summary(
    uc: UCSQLClient,
    store: Any,
    *,
    actor_email: str | None = None,
    hidden_catalogs: set[str] = asset_service.HIDDEN_CATALOGS,
    sections: Sequence[str] | None = None,
) -> Dict[str, Any]:
    requested_sections = {
        asset_service.normalize_str(section).lower()
        for section in (sections or [])
        if asset_service.normalize_str(section)
    }
    inbox_only = bool(requested_sections) and requested_sections <= {"inbox"}

    def _loader() -> Dict[str, Any]:
        normalized_actor = asset_service.normalize_str(actor_email).lower()
        if inbox_only:
            inbox = {
                "state": "unavailable",
                "message": "A forwarded Databricks user identity is required for a personal governance inbox.",
                "unreadCount": 0,
                "items": [],
            }
            if normalized_actor and normalized_actor != "unknown":
                if hasattr(store, "list_notifications") and hasattr(store, "count_unread_notifications"):
                    try:
                        inbox_items = _inbox_records(
                            store.list_notifications(recipient_email=normalized_actor, limit=12)
                        )
                        unread_count = int(store.count_unread_notifications(recipient_email=normalized_actor))
                        filtered_inbox_items = inbox_items
                        if inbox_items:
                            inventory = asset_service.visible_assets(
                                uc,
                                store,
                                hidden_catalogs=hidden_catalogs,
                            )
                            visible_asset_keys = _visible_asset_keys(inventory)
                            filtered_inbox_items = _filter_records_to_visible_assets(
                                inbox_items,
                                visible_asset_keys,
                                asset_key="assetFqn",
                            )
                            if len(filtered_inbox_items) != len(inbox_items):
                                unread_count = min(unread_count, len(filtered_inbox_items))
                        inbox = {
                            "state": "live",
                            "message": "",
                            "unreadCount": unread_count,
                            "items": filtered_inbox_items,
                        }
                    except Exception:
                        inbox = {
                            "state": "degraded",
                            "message": "Governance inbox is temporarily unavailable.",
                            "unreadCount": 0,
                            "items": [],
                        }
            return {
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
                "inbox": inbox,
                "sections": ["inbox"],
            }

        # These store reads don't depend on the inventory, so start them first
        # and let their warehouse round-trips overlap the catalog scan.
        from concurrent.futures import ThreadPoolExecutor

        prefetch = ThreadPoolExecutor(max_workers=3, thread_name_prefix="axiom-summary-prefetch")
        pending_future = prefetch.submit(store.list_change_requests, status="pending", limit=5000)
        activity_future = prefetch.submit(store.list_activity_events, limit=200)
        projection_future = (
            prefetch.submit(store.get_governance_queue_projection, "workspace:default")
            if hasattr(store, "get_governance_queue_projection")
            else None
        )
        prefetch.shutdown(wait=False)

        inventory = asset_service.visible_assets(
            uc,
            store,
            hidden_catalogs=hidden_catalogs,
        )
        visible_asset_keys = _visible_asset_keys(inventory)
        inbox = {
            "state": "unavailable",
            "message": "A forwarded Databricks user identity is required for a personal governance inbox.",
            "unreadCount": 0,
            "items": [],
        }
        if normalized_actor and normalized_actor != "unknown":
            if hasattr(store, "list_notifications") and hasattr(store, "count_unread_notifications"):
                try:
                    inbox_items = _inbox_records(
                        store.list_notifications(recipient_email=normalized_actor, limit=12)
                    )
                    filtered_inbox_items = _filter_records_to_visible_assets(
                        inbox_items,
                        visible_asset_keys,
                        asset_key="assetFqn",
                    )
                    unread_count = int(store.count_unread_notifications(recipient_email=normalized_actor))
                    if len(filtered_inbox_items) != len(inbox_items):
                        unread_count = min(unread_count, len(filtered_inbox_items))
                    inbox = {
                        "state": "live",
                        "message": "",
                        "unreadCount": unread_count,
                        "items": filtered_inbox_items,
                    }
                except Exception:
                    inbox = {
                        "state": "degraded",
                        "message": "Governance inbox is temporarily unavailable.",
                        "unreadCount": 0,
                        "items": [],
                    }

        try:
            pending = pending_future.result()
        except Exception:
            pending = pd.DataFrame()
        raw_pending_request_records = _request_records(pending)
        pending_request_records = _filter_request_records_to_visible_assets(
            raw_pending_request_records,
            visible_asset_keys,
        )
        pending_request_scope_safe = len(raw_pending_request_records) == len(pending_request_records)
        # NOTE (perf): a second unfiltered list_change_requests(limit=5000)
        # fetch used to run here and was never read — one whole warehouse
        # round-trip per cold build for nothing. Removed.
        try:
            activity_events = activity_future.result()
        except Exception:
            activity_events = pd.DataFrame()
        activity_audit_index = _audit_rows_by_request(
            _activity_audit_frame(store, activity_events)
        )
        activity_records = _filter_records_to_visible_assets(
            _activity_records(activity_events, activity_audit_index),
            visible_asset_keys,
            asset_key="assetFqn",
        )
        queue_summary = _queue_summary_from_live_requests(pending_request_records)
        if projection_future is not None:
            try:
                queue_projection = projection_future.result()
            except Exception:
                queue_projection = None
            if queue_projection and _projection_is_fresh(queue_projection) and pending_request_scope_safe:
                queue_summary = {
                    "scopeKey": asset_service.normalize_str(queue_projection.get("scopeKey"))
                    or "workspace:default",
                    "source": "projection",
                    "laneCounts": queue_projection.get("laneCounts") or queue_summary.get("laneCounts") or {},
                    "openTaskCount": int(
                        queue_projection.get("openTaskCount")
                        if queue_projection.get("openTaskCount") is not None
                        else queue_summary.get("openTaskCount") or 0
                    ),
                    "observedAt": asset_service.normalize_str(queue_projection.get("observedAt")),
                    "staleAfter": asset_service.normalize_str(queue_projection.get("staleAfter")),
                }
        if asset_service.normalize_str(queue_summary.get("source")).lower() != "projection":
            queue_summary["openTaskCount"] = len(pending_request_records)

        metrics = [
            {"label": "Assets", "value": int(len(inventory.index))},
            {
                "label": "Needs attention",
                # Audit F5: deduplicated OR (an asset that is BOTH "Needs Work"
                # AND has pending requests is ONE needs-attention asset, not
                # two). The old `eq(...).sum() + gt(...).sum()` double-counted
                # the overlap and could exceed the "Assets" total. Matches the
                # discovery view_matches("Needs attention") predicate.
                "value": int(
                    (
                        inventory["governance_status"].eq("Needs Work")
                        | inventory["pending_requests"].gt(0)
                    ).sum()
                ),
            },
            {
                "label": "Certified",
                "value": int(
                    inventory["certification"]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                    .eq("certified")
                    .sum()
                ),
            },
            {
                "label": "With stewards",
                "value": int(
                    inventory["steward"].fillna("").astype(str).ne("").sum()
                ),
            },
            {
                "label": "Sensitive assets",
                "value": int(
                    inventory["sensitivity"].fillna("").astype(str).ne("").sum()
                ),
            },
            {
                "label": "Open requests",
                "value": int(queue_summary.get("openTaskCount") or 0),
                # Scope caption: this KPI counts only requests targeting
                # assets in the actor-visible estate. The workbench counts
                # ALL open requests — both are correct, and each surface now
                # says which population it counts (the audit found 21 vs 40
                # with no caption on either side).
                "scope": "visible-estate",
                "caption": "in visible estate",
                "outOfScopeOpenCount": max(
                    0, len(raw_pending_request_records) - len(pending_request_records)
                ),
            },
        ]

        backlog: List[Dict[str, str]] = []
        for request_record in pending_request_records[:8]:
            backlog.append(
                {
                    "requestId": asset_service.normalize_str(request_record.get("requestId")),
                    "title": asset_service.normalize_str(request_record.get("detail"))
                    or "Open governance request",
                    "asset": asset_service.normalize_str(request_record.get("assetFqn")),
                    "assetFqn": asset_service.normalize_str(request_record.get("assetFqn")),
                    "status": asset_service.normalize_str(request_record.get("status")).title()
                    or "Pending",
                    "note": asset_service.normalize_str(request_record.get("reviewNote"))
                    or "Awaiting governance review.",
                    "createdAt": asset_service.normalize_str(request_record.get("createdAt")),
                    "createdBy": asset_service.normalize_str(request_record.get("createdBy")),
                    "reviewedAt": asset_service.normalize_str(request_record.get("reviewedAt")),
                    "reviewedBy": asset_service.normalize_str(request_record.get("reviewedBy")),
                    "reviewNote": asset_service.normalize_str(request_record.get("reviewNote")),
                }
            )

        glossary_rows = glossary_terms(
            uc,
            store,
            actor_email=actor_email,
            hidden_catalogs=hidden_catalogs,
            limit=50,
        )

        return {
            "metrics": metrics,
            "backlog": backlog,
            "queue": queue_summary,
            "glossary": glossary_rows,
            "activity": activity_records[:12],
            "inbox": inbox,
        }

    actor_key = _lookup_key(actor_email) or "anonymous"
    section_key = ",".join(sorted(requested_sections)) or "full"
    return _ttl_value(f"governance:{_warehouse_key(uc)}:{actor_key}:{section_key}", 300, _loader)


def create_change_request(
    store: Any,
    *,
    created_by: str,
    asset_fqn: str,
    title: str,
    note: str,
    actor_role: str = "reader",
) -> str:
    request_id = store.create_change_request(
        created_by=created_by,
        uc_full_name=asset_fqn,
        new_comment=f"{title}: {note}".strip(": "),
        actor_role=actor_role,
    )
    _invalidate_asset_dependent_caches(asset_fqn)
    return request_id


def patch_asset_description(
    uc: UCSQLClient,
    *,
    asset_fqn: str,
    description: str,
) -> None:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    table_type = _relation_table_type(uc, catalog=catalog, schema=schema, table=table)
    uc.set_table_comment(catalog, schema, table, description, table_type=table_type)
    _invalidate_asset_dependent_caches(asset_fqn)


def _normalize_owner_assignments(
    owner_assignments: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    for entry in owner_assignments:
        owner_email = asset_service.normalize_str(entry.get("ownerEmail")).lower()
        if not owner_email or owner_email in seen:
            continue
        seen.add(owner_email)
        owner_type = asset_service.normalize_str(entry.get("ownerType")).lower()
        if owner_type not in _OWNER_TYPES:
            owner_type = "steward"
        normalized.append(
            {
                "ownerEmail": owner_email,
                "ownerType": owner_type,
            }
        )
    return normalized


def patch_asset_owners(
    store: Any,
    *,
    asset_fqn: str,
    owner_assignments: Sequence[Dict[str, Any]],
    updated_by: str,
    replace: bool = True,
    actor_role: str = "reader",
    request_id: str | None = None,
) -> List[Dict[str, str]]:
    normalized = _normalize_owner_assignments(owner_assignments)
    if replace:
        existing_df = store.get_owners(asset_fqn)
        if existing_df is not None and not existing_df.empty:
            desired_emails = {entry["ownerEmail"] for entry in normalized}
            for owner_email in existing_df["owner_email"].dropna().astype(str).tolist():
                email_n = asset_service.normalize_str(owner_email).lower()
                if email_n and email_n not in desired_emails:
                    store.remove_owner(
                        asset_fqn,
                        owner_email,
                        actor_email=updated_by,
                        actor_role=actor_role,
                        request_id=request_id,
                    )
    for entry in normalized:
        store.upsert_owner(
            asset_fqn,
            entry["ownerEmail"],
            entry["ownerType"],
            updated_by,
            actor_role=actor_role,
            request_id=request_id,
        )
    _invalidate_asset_dependent_caches(asset_fqn)
    return normalized


def add_owner(
    store: Any,
    *,
    asset_fqn: str,
    owner_email: str,
    owner_type: str,
    updated_by: str,
    actor_role: str = "reader",
    request_id: str | None = None,
) -> List[Dict[str, str]]:
    return patch_asset_owners(
        store,
        asset_fqn=asset_fqn,
        owner_assignments=[
            {
                "ownerEmail": owner_email,
                "ownerType": owner_type,
            }
        ],
        updated_by=updated_by,
        replace=False,
        actor_role=actor_role,
        request_id=request_id,
    )


def patch_column_description(
    uc: UCSQLClient,
    *,
    asset_fqn: str,
    column_name: str,
    description: str,
) -> None:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    table_type = _relation_table_type(uc, catalog=catalog, schema=schema, table=table)
    uc.set_column_comment(
        catalog,
        schema,
        table,
        column_name,
        description,
        table_type=table_type,
    )
    asset_service.invalidate_asset_caches(asset_fqn)


def patch_column_metadata(
    uc: UCSQLClient,
    *,
    asset_fqn: str,
    column_name: str,
    description: str,
    tags: Dict[str, str],
) -> Dict[str, Any]:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    table_type = _relation_table_type(uc, catalog=catalog, schema=schema, table=table)
    uc.set_column_comment(
        catalog,
        schema,
        table,
        column_name,
        description,
        table_type=table_type,
    )
    normalized_tags = {
        asset_service.normalize_str(key): asset_service.normalize_str(value)
        for key, value in (tags or {}).items()
        if asset_service.normalize_str(key) and asset_service.normalize_str(value)
    }
    current_tags = _normalized_tag_map(uc.get_column_tags(catalog, schema, table, column_name))
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
    applied_tags = _normalized_tag_map(uc.get_column_tags(catalog, schema, table, column_name))
    _invalidate_asset_dependent_caches(asset_fqn)
    return {
        "description": description,
        "tags": applied_tags,
        "warning": tag_write_warning(
            normalized_tags,
            applied_tags,
            scope_label="Column",
        ),
    }


def upsert_glossary_term(
    store: Any,
    *,
    term_id: str,
    name: str,
    definition: str,
    domain: str,
    owner_email: str,
    status: str,
    updated_by: str,
    reviewers: Sequence[Dict[str, Any]] | None = None,
    change_note: str | None = None,
    actor_role: str = "reader",
) -> Dict[str, Any]:
    version = store.upsert_glossary_term(
        term_id=term_id or uuid.uuid4().hex[:12],
        name=name,
        definition=definition,
        domain=domain,
        owner_email=owner_email or None,
        status=status,
        updated_by=updated_by,
        reviewers=list(reviewers) if reviewers is not None else None,
        change_note=change_note,
        actor_role=actor_role,
    )
    invalidate_governance_caches()
    return version
