from __future__ import annotations

import logging
import json
from typing import Any, Dict, Iterable, Mapping, Sequence

import pandas as pd
from psycopg.types.json import Jsonb

from axiom.config import AppConfig
from axiom.services import lakebase
from axiom.util import sql_literal


ACTIVE_LAKEBASE_MIRROR_TABLES: tuple[str, ...] = (
    "user_roles",
    "identity_directory_entries",
    "entity_registry",
    "entity_aliases",
    "data_owners",
    "threads",
    "thread_posts",
    "tasks",
    "activity_events",
    "notifications",
    "notification_receipts",
    "custom_property_definitions",
    "custom_property_assignments",
    "classification_recommendations",
)

DEFERRED_LAKEBASE_OPERATIONAL_TABLES: tuple[str, ...] = tuple(
    table
    for table in lakebase.LAKEBASE_OPERATIONAL_TABLES
    if table not in ACTIVE_LAKEBASE_MIRROR_TABLES
)

_KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "user_roles": ("email",),
    "identity_directory_entries": ("entry_id",),
    "entity_registry": ("entity_id",),
    "entity_aliases": ("alias_id",),
    "data_owners": ("uc_full_name", "owner_email"),
    "threads": ("thread_id",),
    "thread_posts": ("post_id",),
    "tasks": ("task_id",),
    "activity_events": ("event_id",),
    "notifications": ("notification_id",),
    "notification_receipts": ("notification_id", "recipient_entry_id"),
    "custom_property_definitions": ("definition_id",),
    "custom_property_assignments": ("assignment_id",),
    "classification_recommendations": ("recommendation_id",),
}

LAKEBASE_ACTIVE_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "user_roles": ("email", "role", "updated_at", "updated_by"),
    "identity_directory_entries": (
        "entry_id",
        "external_key",
        "principal_type",
        "display_name",
        "email",
        "is_active",
        "source",
        "attributes_json",
        "synced_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    ),
    "entity_registry": (
        "entity_id",
        "entity_kind",
        "entity_fqn",
        "source_system",
        "source_entity_id",
        "reconciliation_state",
        "reconciliation_confidence",
        "observed_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    ),
    "entity_aliases": (
        "alias_id",
        "entity_id",
        "alias_type",
        "alias_value",
        "source",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    ),
    "data_owners": ("uc_full_name", "owner_email", "owner_type", "updated_at", "updated_by"),
    "threads": (
        "thread_id",
        "entity_id",
        "entity_fqn_snapshot",
        "column_name",
        "thread_type",
        "status",
        "created_by_entry_id",
        "created_at",
        "updated_at",
    ),
    "thread_posts": (
        "post_id",
        "thread_id",
        "body_markdown",
        "diff_json",
        "created_by_entry_id",
        "created_at",
        "edited_at",
    ),
    "tasks": (
        "task_id",
        "thread_id",
        "entity_id",
        "entity_fqn_snapshot",
        "column_name",
        "task_type",
        "diff_before_json",
        "diff_after_json",
        "requested_payload_json",
        "assignee_entry_id",
        "reviewer_entry_id",
        "due_at",
        "status",
        "resolution_code",
        "resolved_payload_json",
        "expected_version",
        "created_at",
        "updated_at",
    ),
    "activity_events": (
        "event_id",
        "event_type",
        "entity_id",
        "entity_fqn_snapshot",
        "column_name",
        "actor_entry_id",
        "thread_id",
        "task_id",
        "payload_json",
        "created_at",
    ),
    "notifications": (
        "notification_id",
        "event_id",
        "channel",
        "delivery_state",
        "payload_json",
        "created_at",
        "sent_at",
        "failed_at",
        "retry_count",
    ),
    "notification_receipts": (
        "notification_id",
        "recipient_entry_id",
        "inbox_state",
        "seen_at",
        "read_at",
        "dismissed_at",
        "delivered_at",
    ),
    "custom_property_definitions": (
        "definition_id",
        "entity_kind",
        "property_key",
        "display_name",
        "description",
        "data_type",
        "enum_values_json",
        "is_required",
        "is_multi",
        "scope_json",
        "state",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "retired_at",
    ),
    "custom_property_assignments": (
        "assignment_id",
        "definition_id",
        "definition_version",
        "entity_kind",
        "entity_id",
        "entity_fqn",
        "column_name",
        "value_json",
        "source",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "removed_at",
        "removed_by",
    ),
    "classification_recommendations": (
        "recommendation_id",
        "asset_fqn",
        "column_name",
        "suggested_sensitivity",
        "suggested_tier",
        "suggested_certification",
        "evidence_json",
        "sample_redacted",
        "sample_values_json",
        "status",
        "remediation_suggestions_json",
        "review_note",
        "reviewed_by",
        "reviewed_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    ),
}

_JSONB_COLUMNS: set[tuple[str, str]] = {
    ("identity_directory_entries", "attributes_json"),
    ("thread_posts", "diff_json"),
    ("tasks", "diff_before_json"),
    ("tasks", "diff_after_json"),
    ("tasks", "requested_payload_json"),
    ("tasks", "resolved_payload_json"),
    ("activity_events", "payload_json"),
    ("notifications", "payload_json"),
    ("classification_recommendations", "evidence_json"),
    ("classification_recommendations", "sample_values_json"),
    ("classification_recommendations", "remediation_suggestions_json"),
    ("custom_property_definitions", "enum_values_json"),
    ("custom_property_definitions", "scope_json"),
    ("custom_property_assignments", "value_json"),
}

_EMPTY_ARRAY_JSONB_COLUMNS: set[tuple[str, str]] = {
    ("classification_recommendations", "sample_values_json"),
}

_LOGGER = logging.getLogger(__name__)
_LAST_INACTIVE_STATUS: dict[str, Any] = {
    "enabled": False,
    "mode": "delta-primary",
    "state": "disabled",
    "message": "Lakebase dual-write mirror is not enabled.",
}


def record_inactive_status(message: str, *, state: str = "inactive") -> None:
    global _LAST_INACTIVE_STATUS
    _LAST_INACTIVE_STATUS = {
        "enabled": False,
        "mode": "delta-primary",
        "state": state,
        "message": message,
        "activeTables": list(ACTIVE_LAKEBASE_MIRROR_TABLES),
        "deferredTables": list(DEFERRED_LAKEBASE_OPERATIONAL_TABLES),
    }


def _coerce_jsonb_value(table: str, column: str, value: Any) -> Any:
    if value is None:
        return Jsonb([]) if (table, column) in _EMPTY_ARRAY_JSONB_COLUMNS else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return Jsonb([]) if (table, column) in _EMPTY_ARRAY_JSONB_COLUMNS else None
        try:
            return Jsonb(json.loads(stripped))
        except json.JSONDecodeError:
            return Jsonb(stripped)
    return Jsonb(value)


def _clean_value(value: Any, *, table: str | None = None, column: str | None = None) -> Any:
    if table and column and (table, column) in _JSONB_COLUMNS:
        return _coerce_jsonb_value(table, column, value)
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime()
        except Exception:
            return value
    return value


def _rows_from_frame(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        rows.append({str(key): _clean_value(value) for key, value in record.items()})
    return rows


def _where_in(column: str, values: Iterable[str]) -> str:
    cleaned = sorted({str(value or "").strip() for value in values if str(value or "").strip()})
    if not cleaned:
        return "1 = 0"
    return f"{column} IN ({', '.join(sql_literal(value) for value in cleaned)})"


class LakebaseOperationalMirror:
    def __init__(self, *, config: AppConfig, delta_store: Any) -> None:
        self.config = config
        self.delta_store = delta_store
        self.schema = getattr(config, "lakebase_schema", "") or "axiom_app"
        self.attempted = 0
        self.succeeded = 0
        self.failed = 0
        self.last_error = ""
        self.last_operation = ""
        self.last_table = ""

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "mode": "delta-primary-lakebase-shadow",
            "state": "degraded" if self.failed else "active",
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "lastError": self.last_error,
            "lastOperation": self.last_operation,
            "lastTable": self.last_table,
            "schema": self.schema,
            "activeTables": list(ACTIVE_LAKEBASE_MIRROR_TABLES),
            "deferredTables": list(DEFERRED_LAKEBASE_OPERATIONAL_TABLES),
            "deltaRetainedTables": list(lakebase.DELTA_RETAINED_TABLES),
        }

    def _record_success(self, operation: str, table: str) -> None:
        self.attempted += 1
        self.succeeded += 1
        self.last_operation = operation
        self.last_table = table
        self.last_error = ""

    def _record_failure(self, operation: str, table: str, exc: Exception) -> None:
        self.attempted += 1
        self.failed += 1
        self.last_operation = operation
        self.last_table = table
        self.last_error = f"{exc.__class__.__name__}: {exc}"
        _LOGGER.warning("Lakebase mirror failed for %s/%s: %s", operation, table, exc)

    def _query_delta(self, table: str, where: str) -> pd.DataFrame:
        return self.delta_store.uc.query_df(
            f"SELECT * FROM {self.delta_store._fq(table)} WHERE {where}"
        )

    def _upsert_rows_in_transaction(self, conn: Any, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        keys = _KEY_COLUMNS[table]
        allowed_columns = LAKEBASE_ACTIVE_TABLE_COLUMNS.get(table)
        for row in rows:
            if allowed_columns:
                columns = [column for column in allowed_columns if column in row]
            else:
                columns = [str(column) for column in row.keys()]
            if not all(key in columns for key in keys):
                continue
            non_keys = [column for column in columns if column not in keys]
            quoted_columns = ", ".join(lakebase._pg_ident(column) for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            conflict = ", ".join(lakebase._pg_ident(key) for key in keys)
            if non_keys:
                update_set = ", ".join(
                    f"{lakebase._pg_ident(column)} = EXCLUDED.{lakebase._pg_ident(column)}"
                    for column in non_keys
                )
            else:
                update_set = ", ".join(
                    f"{lakebase._pg_ident(key)} = EXCLUDED.{lakebase._pg_ident(key)}"
                    for key in keys
                )
            values = [_clean_value(row.get(column), table=table, column=column) for column in columns]
            with conn.cursor() as cur:
                cur.execute(
                    (
                        f"INSERT INTO {lakebase._pg_ident(self.schema)}.{lakebase._pg_ident(table)} "
                        f"({quoted_columns}) VALUES ({placeholders}) "
                        f"ON CONFLICT ({conflict}) DO UPDATE SET {update_set}"
                    ),
                    values,
                )

    def _delete_where_in_transaction(self, conn: Any, table: str, criteria: Mapping[str, Any]) -> None:
        clauses = []
        params = []
        for column, value in criteria.items():
            clauses.append(f"{lakebase._pg_ident(column)} = %s")
            params.append(_clean_value(value))
        if not clauses:
            return
        with conn.cursor() as cur:
            cur.execute(
                (
                    f"DELETE FROM {lakebase._pg_ident(self.schema)}.{lakebase._pg_ident(table)} "
                    f"WHERE {' AND '.join(clauses)}"
                ),
                params,
            )

    def _mirror_frames(self, operation: str, frames: Mapping[str, pd.DataFrame | None]) -> None:
        try:
            with lakebase.connect(self.config) as conn:
                last_table = ""
                for table, frame in frames.items():
                    if table not in ACTIVE_LAKEBASE_MIRROR_TABLES:
                        continue
                    rows = _rows_from_frame(frame)
                    if not rows:
                        continue
                    last_table = table
                    self._upsert_rows_in_transaction(conn, table, rows)
                conn.commit()
            self._record_success(operation, last_table or "none")
        except Exception as exc:
            self._record_failure(operation, "multiple", exc)

    def mirror_row_by_id(self, operation: str, table: str, column: str, value: str) -> None:
        if table not in ACTIVE_LAKEBASE_MIRROR_TABLES:
            return
        frame = self._query_delta(table, f"{column} = {sql_literal(value)}")
        self._mirror_frames(operation, {table: frame})

    def delete_row(self, operation: str, table: str, criteria: Mapping[str, Any]) -> None:
        if table not in ACTIVE_LAKEBASE_MIRROR_TABLES:
            return
        try:
            with lakebase.connect(self.config) as conn:
                self._delete_where_in_transaction(conn, table, criteria)
                conn.commit()
            self._record_success(operation, table)
        except Exception as exc:
            self._record_failure(operation, table, exc)

    def mirror_role(self, email: str) -> None:
        self.mirror_row_by_id("upsert_role", "user_roles", "lower(email)", str(email or "").strip().lower())

    def mirror_identity_entry(self, entry_id: str) -> None:
        self.mirror_row_by_id("identity_directory_entry", "identity_directory_entries", "entry_id", entry_id)

    def mirror_entity_registry(self, entity_id: str) -> None:
        self.mirror_row_by_id("entity_registry", "entity_registry", "entity_id", entity_id)

    def mirror_entity_alias(self, alias_id: str) -> None:
        self.mirror_row_by_id("entity_alias", "entity_aliases", "alias_id", alias_id)

    def mirror_owner(self, uc_full_name: str, owner_email: str) -> None:
        frame = self._query_delta(
            "data_owners",
            (
                f"uc_full_name = {sql_literal(uc_full_name)} "
                f"AND lower(owner_email) = {sql_literal(str(owner_email or '').strip().lower())}"
            ),
        )
        self._mirror_frames("owner_upsert", {"data_owners": frame})

    def delete_owner(self, uc_full_name: str, owner_email: str) -> None:
        self.delete_row(
            "owner_remove",
            "data_owners",
            {"uc_full_name": uc_full_name, "owner_email": str(owner_email or "").strip().lower()},
        )

    def mirror_workflow(self, task_id: str) -> None:
        task_id = str(task_id or "").strip()
        if not task_id:
            return
        tasks = self._query_delta("tasks", f"task_id = {sql_literal(task_id)}")
        if tasks is None or tasks.empty:
            return
        task_row = tasks.iloc[0].to_dict()
        thread_id = str(task_row.get("thread_id") or "").strip()
        entity_id = str(task_row.get("entity_id") or "").strip()
        threads = self._query_delta("threads", f"thread_id = {sql_literal(thread_id)}")
        posts = self._query_delta("thread_posts", f"thread_id = {sql_literal(thread_id)}")
        activity = self._query_delta(
            "activity_events",
            f"thread_id = {sql_literal(thread_id)} OR task_id = {sql_literal(task_id)}",
        )
        event_ids = []
        if activity is not None and not activity.empty and "event_id" in activity.columns:
            event_ids = [str(value) for value in activity["event_id"].dropna().tolist()]
        notifications = self._query_delta("notifications", _where_in("event_id", event_ids))
        notification_ids = []
        if notifications is not None and not notifications.empty and "notification_id" in notifications.columns:
            notification_ids = [str(value) for value in notifications["notification_id"].dropna().tolist()]
        receipts = self._query_delta("notification_receipts", _where_in("notification_id", notification_ids))
        entity_registry = (
            self._query_delta("entity_registry", f"entity_id = {sql_literal(entity_id)}")
            if entity_id
            else pd.DataFrame()
        )
        aliases = (
            self._query_delta("entity_aliases", f"entity_id = {sql_literal(entity_id)}")
            if entity_id
            else pd.DataFrame()
        )
        entry_ids: set[str] = set()
        for frame, columns in (
            (threads, ("created_by_entry_id",)),
            (posts, ("created_by_entry_id",)),
            (tasks, ("assignee_entry_id", "reviewer_entry_id")),
            (activity, ("actor_entry_id",)),
            (receipts, ("recipient_entry_id",)),
        ):
            if frame is None or frame.empty:
                continue
            for column in columns:
                if column in frame.columns:
                    entry_ids.update(str(value) for value in frame[column].dropna().tolist() if str(value).strip())
        identities = self._query_delta("identity_directory_entries", _where_in("entry_id", entry_ids))
        self._mirror_frames(
            "workflow",
            {
                "identity_directory_entries": identities,
                "entity_registry": entity_registry,
                "entity_aliases": aliases,
                "threads": threads,
                "thread_posts": posts,
                "tasks": tasks,
                "activity_events": activity,
                "notifications": notifications,
                "notification_receipts": receipts,
            },
        )

    def mirror_notification_receipt(self, notification_id: str, recipient_email: str) -> None:
        identity = self._query_delta(
            "identity_directory_entries",
            f"lower(COALESCE(email, external_key, '')) = {sql_literal(str(recipient_email or '').strip().lower())}",
        )
        entry_id = ""
        if identity is not None and not identity.empty:
            entry_id = str(identity.iloc[0].get("entry_id") or "").strip()
        receipt = self._query_delta(
            "notification_receipts",
            (
                f"notification_id = {sql_literal(notification_id)} "
                f"AND recipient_entry_id = {sql_literal(entry_id)}"
            ),
        )
        self._mirror_frames("notification_receipt", {"identity_directory_entries": identity, "notification_receipts": receipt})

    def mirror_custom_property_definition(self, definition_id: str) -> None:
        self.mirror_row_by_id("custom_property_definition", "custom_property_definitions", "definition_id", definition_id)

    def mirror_custom_property_assignment(
        self,
        *,
        assignment_id: str,
        definition_id: str,
        entity_kind: str,
        entity_fqn: str | None,
        column_name: str | None,
    ) -> None:
        try:
            frame = self._query_delta(
                "custom_property_assignments",
                f"assignment_id = {sql_literal(assignment_id)}",
            )
            with lakebase.connect(self.config) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        (
                            f"DELETE FROM {lakebase._pg_ident(self.schema)}."
                            f"{lakebase._pg_ident('custom_property_assignments')} "
                            "WHERE definition_id = %s "
                            "AND entity_kind = %s "
                            "AND COALESCE(entity_fqn, '') = %s "
                            "AND COALESCE(column_name, '') = %s"
                        ),
                        [definition_id, entity_kind, entity_fqn or "", column_name or ""],
                    )
                self._upsert_rows_in_transaction(
                    conn,
                    "custom_property_assignments",
                    _rows_from_frame(frame),
                )
                conn.commit()
            self._record_success("custom_property_assignment", "custom_property_assignments")
        except Exception as exc:
            self._record_failure("custom_property_assignment", "custom_property_assignments", exc)

    def mirror_classification_recommendation(self, recommendation_id: str) -> None:
        self.mirror_row_by_id(
            "classification_recommendation",
            "classification_recommendations",
            "recommendation_id",
            recommendation_id,
        )


class DualWriteGovernanceStore:
    """Delta-authoritative governance store with Lakebase shadow writes."""

    def __init__(self, delta_store: Any, mirror: LakebaseOperationalMirror) -> None:
        self._delta_store = delta_store
        self._mirror = mirror

    @property
    def uc(self) -> Any:
        return self._delta_store.uc

    @property
    def catalog(self) -> str:
        return self._delta_store.catalog

    @property
    def schema(self) -> str:
        return self._delta_store.schema

    @property
    def fq_schema(self) -> str:
        return self._delta_store.fq_schema

    def _fq(self, table: str) -> str:
        return self._delta_store._fq(table)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delta_store, name)

    def lakebase_dual_write_status(self) -> Dict[str, Any]:
        return self._mirror.status()

    def get_role(self, email: str, admin_emails: list[str] | None = None) -> str:
        result = self._delta_store.get_role(email, admin_emails=admin_emails)
        self._mirror.mirror_role(email)
        return result

    def upsert_role(self, email: str, role: str, updated_by: str) -> Any:
        result = self._delta_store.upsert_role(email=email, role=role, updated_by=updated_by)
        self._mirror.mirror_role(email)
        return result

    def upsert_identity_directory_entry(self, **kwargs: Any) -> Dict[str, Any]:
        result = self._delta_store.upsert_identity_directory_entry(**kwargs)
        self._mirror.mirror_identity_entry(str(result.get("entryId") or ""))
        return result

    def upsert_entity_registry(self, **kwargs: Any) -> Dict[str, Any]:
        result = self._delta_store.upsert_entity_registry(**kwargs)
        self._mirror.mirror_entity_registry(str(result.get("entityId") or ""))
        return result

    def upsert_entity_alias(self, **kwargs: Any) -> Dict[str, Any]:
        result = self._delta_store.upsert_entity_alias(**kwargs)
        self._mirror.mirror_entity_alias(str(result.get("aliasId") or ""))
        return result

    def upsert_owner(
        self,
        uc_full_name: str,
        owner_email: str,
        owner_type: str,
        updated_by: str,
        actor_role: str = "reader",
        request_id: str | None = None,
    ) -> Any:
        result = self._delta_store.upsert_owner(
            uc_full_name=uc_full_name,
            owner_email=owner_email,
            owner_type=owner_type,
            updated_by=updated_by,
            actor_role=actor_role,
            request_id=request_id,
        )
        self._mirror.mirror_owner(uc_full_name, owner_email)
        return result

    def remove_owner(
        self,
        uc_full_name: str,
        owner_email: str,
        *,
        actor_email: str = "",
        actor_role: str = "reader",
        request_id: str | None = None,
        note: str | None = None,
        action: str = "owner-removed",
    ) -> Any:
        result = self._delta_store.remove_owner(
            uc_full_name,
            owner_email,
            actor_email=actor_email,
            actor_role=actor_role,
            request_id=request_id,
            note=note,
            action=action,
        )
        self._mirror.delete_owner(uc_full_name, owner_email)
        return result

    def create_workflow_request(self, **kwargs: Any) -> Dict[str, Any]:
        result = self._delta_store.create_workflow_request(**kwargs)
        self._mirror.mirror_workflow(str(result.get("taskId") or ""))
        return result

    def create_change_request(self, *args: Any, **kwargs: Any) -> str:
        request_id = self._delta_store.create_change_request(*args, **kwargs)
        self._mirror.mirror_workflow(request_id)
        return request_id

    def update_workflow_task_status(self, **kwargs: Any) -> Any:
        task_id = str(kwargs.get("task_id") or "").strip()
        result = self._delta_store.update_workflow_task_status(**kwargs)
        self._mirror.mirror_workflow(task_id)
        return result

    def set_request_status(
        self,
        request_id: str,
        status: str,
        reviewed_by: str,
        review_note: str | None = None,
        actor_role: str = "reader",
        refresh_projection: bool = True,
        assignee: str | None = None,
        priority: str | None = None,
    ) -> Any:
        # Keep this signature in lockstep with GovernanceStore.set_request_status.
        # assignee/priority were added to the base store for triage PATCHes; the
        # wrapper previously dropped them, so PATCH /api/governance/requests/<id>
        # 500'd with an unexpected-keyword TypeError when the Lakebase mirror was
        # active. Pass every kwarg through so the Delta primary write is identical
        # to the non-mirrored path, then shadow-mirror as usual.
        result = self._delta_store.set_request_status(
            request_id=request_id,
            status=status,
            reviewed_by=reviewed_by,
            review_note=review_note,
            actor_role=actor_role,
            refresh_projection=refresh_projection,
            assignee=assignee,
            priority=priority,
        )
        if refresh_projection:
            self._mirror.mirror_workflow(request_id)
        return result

    def update_notification_receipt(self, **kwargs: Any) -> Dict[str, Any]:
        result = self._delta_store.update_notification_receipt(**kwargs)
        self._mirror.mirror_notification_receipt(
            str(kwargs.get("notification_id") or ""),
            str(kwargs.get("recipient_email") or ""),
        )
        return result

    def insert_custom_property_definition(self, **kwargs: Any) -> Any:
        result = self._delta_store.insert_custom_property_definition(**kwargs)
        self._mirror.mirror_custom_property_definition(str(kwargs.get("definition_id") or ""))
        return result

    def upsert_custom_property_assignment(self, **kwargs: Any) -> Any:
        result = self._delta_store.upsert_custom_property_assignment(**kwargs)
        self._mirror.mirror_custom_property_assignment(
            assignment_id=str(kwargs.get("assignment_id") or ""),
            definition_id=str(kwargs.get("definition_id") or ""),
            entity_kind=str(kwargs.get("entity_kind") or ""),
            entity_fqn=kwargs.get("entity_fqn"),
            column_name=kwargs.get("column_name"),
        )
        return result

    def upsert_classification_recommendation(self, record: Dict[str, Any], *, actor_email: str | None = None) -> str:
        recommendation_id = self._delta_store.upsert_classification_recommendation(
            record,
            actor_email=actor_email,
        )
        self._mirror.mirror_classification_recommendation(recommendation_id)
        return recommendation_id

    def set_classification_recommendation_status(self, recommendation_id: str, *, status: str, reviewer: str, review_note: str | None = None) -> Any:
        result = self._delta_store.set_classification_recommendation_status(
            recommendation_id,
            status=status,
            reviewer=reviewer,
            review_note=review_note,
        )
        self._mirror.mirror_classification_recommendation(recommendation_id)
        return result


def dual_write_status(store: Any | None = None) -> Dict[str, Any]:
    if store is not None and hasattr(store, "lakebase_dual_write_status"):
        return store.lakebase_dual_write_status()
    return dict(_LAST_INACTIVE_STATUS)
