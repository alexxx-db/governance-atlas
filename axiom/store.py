from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

import pandas as pd

from . import migrations
from .uc import UCSQLClient, write_generation
from .util import quote_ident, sql_literal

_LOGGER = logging.getLogger(__name__)

_WRITE_BATCH = threading.local()
_SCRIPT_BATCHING = {
    "enabled": os.getenv("AXIOM_SQL_SCRIPT_BATCHING", "1").strip().lower() not in {"0", "false", "no", "off"}
}


def _scripting_unsupported(exc: Exception) -> bool:
    text = str(exc).upper()
    return "SQL_SCRIPTING" in text or ("PARSE_SYNTAX_ERROR" in text and "BEGIN" in text)


def _norm_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_future_ts(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return json.dumps(str(value), default=str)


def _json_load(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = str(value).strip()
    return text or None


def _int_value(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return int(value)
    except Exception:
        return default


def _request_status_from_task(task_status: Any, resolution_code: Any = None) -> str:
    normalized_status = str(task_status or "").strip().lower()
    normalized_resolution = str(resolution_code or "").strip().lower()
    if normalized_status in {"rejected"} or normalized_resolution == "rejected":
        return "rejected"
    if normalized_status in {"resolved", "closed"} or normalized_resolution == "approved":
        return "approved"
    return "pending"


def _task_status_from_request_status(request_status: str) -> tuple[str, str | None]:
    normalized = str(request_status or "").strip().lower()
    if normalized in {"approved", "resolved", "closed"}:
        return "resolved", "approved"
    if normalized == "rejected":
        return "rejected", "rejected"
    return "open", None


def _thread_status_from_task_status(task_status: str) -> str:
    normalized = str(task_status or "").strip().lower()
    if normalized == "rejected":
        return "rejected"
    if normalized in {"resolved", "closed"}:
        return "resolved"
    return "open"


def _governance_lane_from_request_record(record: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(record.get("title") or "").strip(),
            str(record.get("new_comment") or "").strip(),
            str(record.get("detail") or "").strip(),
            str(record.get("uc_full_name") or "").strip(),
            str(record.get("status") or "").strip(),
        ]
    ).lower()
    if "owner" in text:
        return "ownership"
    if any(token in text for token in ("cert", "classif", "sensit", "privacy")):
        return "classification"
    if any(token in text for token in ("domain", "tier", "trust")):
        return "trust"
    return "open-work"


def _request_status_label(request_status: Any) -> str:
    normalized = str(request_status or "").strip().lower()
    if normalized == "approved":
        return "Approved"
    if normalized == "rejected":
        return "Rejected"
    return "Pending"


@dataclass(frozen=True)
class ChangeRequest:
    request_id: str
    created_at: str
    created_by: str
    status: str
    uc_full_name: str | None = None
    new_comment: str | None = None
    new_uc_tags: Dict[str, str] | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None


GLOSSARY_TERM_COLUMNS = (
    "term_id, glossary_id, name, definition, parent_term_id, domain, owner_email, "
    "status, is_mutually_exclusive, created_at, created_by, updated_at, updated_by"
)
CHANGE_REQUEST_COLUMNS = (
    "request_id, created_at, created_by, status, uc_full_name, new_comment, "
    "new_uc_tags_json, reviewed_at, reviewed_by, review_note"
)


def _read_cache_ttl_s() -> float:
    try:
        return float(os.getenv("AXIOM_STORE_READ_CACHE_TTL_S", "10"))
    except ValueError:
        return 10.0


def _task_request_status_predicate(status: str) -> str:
    """SQL twin of _request_status_from_task for the tasks alias `t`."""
    task_status = "lower(trim(COALESCE(t.status, '')))"
    resolution = "lower(trim(COALESCE(t.resolution_code, '')))"
    rejected = f"({task_status} = 'rejected' OR {resolution} = 'rejected')"
    approved = f"({task_status} IN ('resolved', 'closed') OR {resolution} = 'approved')"
    normalized = str(status or "").strip().lower()
    if normalized == "rejected":
        return rejected
    if normalized == "approved":
        return f"(NOT {rejected} AND {approved})"
    if normalized == "pending":
        return f"(NOT {rejected} AND NOT {approved})"
    return "FALSE"


class GovernanceStore:
    """Stores all governance state in Unity Catalog Delta tables."""

    def __init__(self, uc: UCSQLClient, catalog: str, schema: str):
        self.uc = uc
        self.catalog = catalog
        self.schema = schema
        self._read_cache: Dict[tuple, tuple] = {}
        self._read_cache_lock = threading.RLock()

    def _cached_list_read(
        self,
        name: str,
        status: str | None,
        limit: int,
        loader,
        status_matches,
    ) -> pd.DataFrame:
        """Short-lived cache for list reads; any write clears it.

        A cached result also serves smaller limits, and a complete
        unfiltered result (fewer rows than its limit) serves any status.
        Only clients that report their writes (tracks_writes) are cached.
        """
        ttl = _read_cache_ttl_s()
        if ttl <= 0 or not getattr(self.uc, "tracks_writes", False):
            return loader()
        limit = int(limit)
        status_key = str(status).strip().lower() if status else None

        def _lookup() -> Optional[pd.DataFrame]:
            now = time.monotonic()
            generation = write_generation()
            for key in ((name, status_key), (name, None)):
                entry = self._read_cache.get(key)
                if not entry:
                    continue
                stored_at, stored_generation, stored_limit, frame = entry
                if now - stored_at > ttl or stored_generation != generation:
                    continue
                complete = len(frame) < stored_limit
                if key[1] == status_key and (complete or stored_limit >= limit):
                    return frame.head(limit).copy()
                if key[1] is None and status_key and complete:
                    if frame.empty:
                        return frame.copy()
                    return frame[status_matches(frame, status_key)].head(limit).reset_index(drop=True)
            return None

        with self._read_cache_lock:
            hit = _lookup()
            if hit is not None:
                return hit
            generation = write_generation()
            frame = loader()
            if frame is None:
                return frame
            if generation == write_generation():
                self._read_cache[(name, status_key)] = (
                    time.monotonic(),
                    generation,
                    limit,
                    frame,
                )
            return frame.copy()

    def invalidate_read_cache(self) -> None:
        with self._read_cache_lock:
            self._read_cache.clear()

    @property
    def fq_schema(self) -> str:
        return f"{quote_ident(self.catalog)}.{quote_ident(self.schema)}"

    def _fq(self, table: str) -> str:
        return f"{self.fq_schema}.{quote_ident(table)}"

    def append_metadata_audit(
        self,
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
        source: str = "store",
        status: str = "success",
        detail: str | None = None,
    ) -> str:
        audit_id = uuid.uuid4().hex
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq("metadata_audit_log")} (
    audit_id, entity_type, entity_id, entity_fqn, column_name,
    action, source, status, before_json, after_json, request_id,
    actor_email, actor_role, detail,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(audit_id)},
    {sql_literal(entity_type)},
    {sql_literal(entity_id)},
    {sql_literal(entity_fqn)},
    {sql_literal(column_name)},
    {sql_literal(action)},
    {sql_literal(source)},
    {sql_literal(status)},
    {sql_literal(_json_text(before)) if before is not None else "NULL"},
    {sql_literal(_json_text(after)) if after is not None else "NULL"},
    {sql_literal(request_id)},
    {sql_literal(actor_email)},
    {sql_literal(actor_role)},
    {sql_literal(detail)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)}
)"""
        )
        return audit_id

    def append_entity_version(
        self,
        *,
        entity_kind: str,
        snapshot: Any,
        entity_id: str | None = None,
        entity_fqn: str | None = None,
        change_event_id: str | None = None,
        recorded_by: str | None = None,
    ) -> str:
        """Phase 5 Tranche A — append a point-in-time entity snapshot so
        the audit surface can answer 'what did this record look like on
        <date>?' without replaying the full change_events stream."""
        version_id = uuid.uuid4().hex
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('entity_versions')} (
    version_id, entity_kind, entity_id, entity_fqn, version_number,
    snapshot_json, change_event_id, recorded_by, recorded_at
) VALUES (
    {sql_literal(version_id)},
    {sql_literal(entity_kind)},
    {sql_literal(entity_id)},
    {sql_literal(entity_fqn)},
    NULL,
    {sql_literal(_json_text(snapshot)) if snapshot is not None else 'NULL'},
    {sql_literal(change_event_id)},
    {sql_literal(recorded_by)},
    timestamp({sql_literal(ts)})
)"""
        )
        return version_id

    def append_change_event(
        self,
        *,
        event_type: str,
        entity_kind: str,
        actor_email: str,
        actor_role: str,
        entity_fqn: str | None = None,
        entity_id: str | None = None,
        column_name: str | None = None,
        request_id: str | None = None,
        before: Any = None,
        after: Any = None,
        detail: str | None = None,
        source: str = "api",
        status: str = "emitted",
    ) -> str:
        """Phase 5 Tranche A hook — append-only governance event stream.

        Writes to change_events which the Phase 13 audit surface and
        projection builders consume. Migration v8 owns the schema.
        Raises only at the SQL layer — callers that treat this as
        best-effort should wrap in try/except.
        """
        event_id = uuid.uuid4().hex
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq("change_events")} (
    event_id, event_type, entity_kind, entity_id, entity_fqn, column_name,
    actor_email, actor_role, before_json, after_json, detail, source, status,
    request_id, occurred_at, recorded_at
) VALUES (
    {sql_literal(event_id)},
    {sql_literal(event_type)},
    {sql_literal(entity_kind)},
    {sql_literal(entity_id)},
    {sql_literal(entity_fqn)},
    {sql_literal(column_name)},
    {sql_literal(actor_email)},
    {sql_literal(actor_role)},
    {sql_literal(_json_text(before)) if before is not None else "NULL"},
    {sql_literal(_json_text(after)) if after is not None else "NULL"},
    {sql_literal(detail)},
    {sql_literal(source)},
    {sql_literal(status)},
    {sql_literal(request_id)},
    timestamp({sql_literal(ts)}),
    timestamp({sql_literal(ts)})
)"""
        )
        return event_id

    def list_change_events(
        self,
        *,
        entity_fqn: str | None = None,
        entity_id: str | None = None,
        entity_kind: str | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_fqn:
            clauses.append(f"entity_fqn = {sql_literal(entity_fqn)}")
        if entity_id:
            clauses.append(f"entity_id = {sql_literal(entity_id)}")
        if entity_kind:
            clauses.append(f"entity_kind = {sql_literal(entity_kind)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT event_id, event_type, entity_kind, entity_id, entity_fqn,
    column_name, actor_email, actor_role, before_json, after_json,
    detail, source, status, request_id, occurred_at, recorded_at
FROM {self._fq("change_events")} {where}
ORDER BY occurred_at DESC, event_id DESC
LIMIT {int(limit)}"""
        )

    def get_export_job(self, job_id: str) -> dict | None:
        if not job_id:
            return None
        frame = self.uc.query_df(
            f"""SELECT job_id, actor_email, actor_role, asset_fqns, filter_snapshot_json,
    format, mode, status, requested_at, token_captured_at, materialized_at,
    expires_at, download_url, row_count, byte_count, checksum, error_detail,
    created_at, created_by, updated_at, updated_by
FROM {self._fq('export_jobs')}
WHERE job_id = {sql_literal(job_id)}
LIMIT 1"""
        )
        if frame is None or frame.empty:
            return None
        row = frame.iloc[0].to_dict()
        return row

    def list_export_jobs(
        self,
        *,
        actor_email: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if actor_email:
            clauses.append(f"actor_email = {sql_literal(actor_email)}")
        if status:
            clauses.append(f"status = {sql_literal(status)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT job_id, actor_email, actor_role, status, mode, format,
    requested_at, materialized_at, expires_at, row_count, byte_count,
    token_captured_at, error_detail
FROM {self._fq('export_jobs')} {where}
ORDER BY requested_at DESC, job_id DESC
LIMIT {int(limit)}"""
        )

    # Internal bookkeeping rows (identity mirroring, registry/alias upkeep,
    # notifications, projections) are excluded in SQL when callers ask for the
    # customer-visible feed. The `%`-separated tokens match `-`, `_`, and space
    # spellings (e.g. `identity-directory-upserted` and
    # `identity_directory_entry`). Static constants only — never interpolate
    # user input here.
    _INTERNAL_AUDIT_LIKE_TOKENS = (
        "identity%directory",
        "entity%registry",
        "entity%alias",
        "notification",
        "projection",
        "mirror",
    )

    def list_metadata_audit(
        self,
        *,
        entity_fqn: str | None = None,
        entity_id: str | None = None,
        entity_type: str | None = None,
        column_name: str | None = None,
        exclude_internal: bool = False,
        limit: int = 50,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_fqn:
            clauses.append(f"entity_fqn = {sql_literal(entity_fqn)}")
        if entity_id:
            clauses.append(f"entity_id = {sql_literal(entity_id)}")
        if entity_type:
            clauses.append(f"entity_type = {sql_literal(entity_type)}")
        if column_name is not None:
            clauses.append(f"COALESCE(column_name, '') = {sql_literal(column_name)}")
        if exclude_internal:
            # Push the exclusion into the WHERE clause so LIMIT applies to
            # customer-visible rows. Filtering after LIMIT let hundreds of
            # identity-directory-upserted rows dominate the newest N rows and
            # starve the audit evidence feed down to a handful of events.
            for column in ("action", "entity_type"):
                expression = f"LOWER(COALESCE({column}, ''))"
                for token in self._INTERNAL_AUDIT_LIKE_TOKENS:
                    clauses.append(f"{expression} NOT LIKE '%{token}%'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT audit_id, entity_type, entity_id, entity_fqn, column_name,
    action, source, status, before_json, after_json, request_id,
    actor_email, actor_role, detail, created_at, created_by, updated_at, updated_by
FROM {self._fq('metadata_audit_log')} {where}
ORDER BY created_at DESC, audit_id DESC
LIMIT {int(limit)}"""
        )

    # Governance DECISION actions — the audit rows that evidence a control being
    # exercised (a steward/admin approving or rejecting a change). NOT access
    # enforcement (GA never touches the access path); this is review activity.
    _DECISION_ACTIONS = (
        "change-request-status-updated",
        "change-request-approved",
    )

    def list_governance_decisions(self, *, limit: int = 100) -> pd.DataFrame:
        """G4 — real governance decisions from the audit log: who approved/
        rejected which change request, when, with the before/after status diff
        and review note. Row-level asset visibility is applied by the caller."""
        actions = ", ".join(sql_literal(action) for action in self._DECISION_ACTIONS)
        return self.uc.query_df(
            f"""SELECT audit_id, entity_type, entity_id, entity_fqn, action, status,
    before_json, after_json, actor_email, actor_role, detail, created_at
FROM {self._fq('metadata_audit_log')}
WHERE action IN ({actions})
ORDER BY created_at DESC, audit_id DESC
LIMIT {int(limit)}"""
        )

    def list_metadata_audit_log(
        self,
        *,
        entity_fqn: str | None = None,
        entity_id: str | None = None,
        entity_type: str | None = None,
        column_name: str | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        return self.list_metadata_audit(
            entity_fqn=entity_fqn,
            entity_id=entity_id,
            entity_type=entity_type,
            column_name=column_name,
            limit=limit,
        )

    def append_metadata_audit_log(
        self,
        *,
        entity_type: str,
        action: str = "updated",
        actor_email: str,
        actor_role: str,
        entity_fqn: str | None = None,
        entity_id: str | None = None,
        column_name: str | None = None,
        request_id: str | None = None,
        before_json: Any = None,
        after_json: Any = None,
        source: str = "api",
        status: str = "success",
        detail: str | None = None,
    ) -> str:
        return self.append_metadata_audit(
            entity_type=entity_type,
            action=action,
            actor_email=actor_email,
            actor_role=actor_role,
            entity_fqn=entity_fqn,
            entity_id=entity_id,
            column_name=column_name,
            request_id=request_id,
            before=before_json,
            after=after_json,
            source=source,
            status=status,
            detail=detail,
        )

    def list_metadata_audit_for_requests(
        self,
        request_ids: Sequence[str],
        *,
        limit: int = 500,
    ) -> pd.DataFrame:
        """Audit-log rows keyed by request/task id, oldest first.

        Task mutations write metadata_audit_log rows with request_id set to
        the workflow task_id (see create_change_request /
        update_workflow_task_status), which is the same id activity_events
        carries as task_id and the workbench exposes as requestId. This is
        the reverse index the governance summary and workbench use to attach
        AUD evidence ids to activity/comment rows — an exact equality join,
        never a timestamp guess.
        """
        ids = sorted(
            {str(value or "").strip() for value in request_ids if str(value or "").strip()}
        )
        if not ids:
            return pd.DataFrame()
        # Bound the IN-list so a pathological caller cannot build an
        # unbounded statement; 200 matches the activity-event fetch ceiling.
        ids = ids[:200]
        in_list = ", ".join(sql_literal(value) for value in ids)
        return self.uc.query_df(
            f"""SELECT audit_id, entity_type, entity_id, entity_fqn, column_name,
    action, source, status, before_json, after_json, request_id,
    actor_email, actor_role, detail, created_at
FROM {self._fq('metadata_audit_log')}
WHERE request_id IN ({in_list})
ORDER BY created_at ASC, audit_id ASC
LIMIT {int(limit)}"""
        )

    # ── Schema bootstrap ────────────────────────────────────

    SCHEMA_BOOTSTRAP_MODES = ("auto", "verify", "off")
    _SCHEMA_FINGERPRINT_KEY = "axiom.schema_fingerprint"

    @staticmethod
    def schema_fingerprint() -> str:
        """Hash of the DDL this build expects; changes whenever ensure_tables
        or the migration list changes."""
        digest = hashlib.sha256()
        try:
            digest.update(inspect.getsource(GovernanceStore.ensure_tables).encode("utf-8"))
        except (OSError, TypeError):
            digest.update(b"ensure_tables:source-unavailable")
        for migration in migrations.DEFAULT_MIGRATIONS:
            digest.update(f"{migration.version}:{migration.name}".encode("utf-8"))
            for statement in migration.statements:
                digest.update(statement.encode("utf-8"))
        return digest.hexdigest()[:24]

    def schema_is_current(self) -> bool:
        try:
            frame = self.uc.query_df(
                f"SHOW TBLPROPERTIES {self._fq('schema_migrations')} "
                f"({sql_literal(self._SCHEMA_FINGERPRINT_KEY)})"
            )
        except Exception:
            return False
        if frame is None or getattr(frame, "empty", True) or "value" not in frame.columns:
            return False
        return str(frame.iloc[0]["value"]).strip() == self.schema_fingerprint()

    def mark_schema_current(self) -> None:
        self.uc.execute(
            f"ALTER TABLE {self._fq('schema_migrations')} SET TBLPROPERTIES "
            f"({sql_literal(self._SCHEMA_FINGERPRINT_KEY)} = {sql_literal(self.schema_fingerprint())})"
        )

    def bootstrap_schema(self, mode: str = "auto") -> str:
        """Bring the governance schema up to date according to ``mode``.

        Returns ``current``, ``migrated``, ``outdated`` (verify mode, DDL
        needed but not run) or ``skipped``.
        """
        mode = (mode or "auto").strip().lower()
        if mode not in self.SCHEMA_BOOTSTRAP_MODES:
            mode = "auto"
        if mode == "off":
            return "skipped"
        if self.schema_is_current():
            return "current"
        if mode == "verify":
            _LOGGER.error(
                "Governance schema %s is not at the expected version; run the "
                "axiom_schema_migrate job.",
                self.fq_schema,
            )
            return "outdated"
        self.ensure_tables()
        self.mark_schema_current()
        return "migrated"

    # ── Bootstrap DDL ───────────────────────────────────────

    def ensure_tables(self) -> None:
        self.uc.execute(f"CREATE SCHEMA IF NOT EXISTS {self.fq_schema}")
        migrations.apply_migrations(self.uc, self.catalog, self.schema)

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("user_roles")} (
            email      STRING NOT NULL,
            role       STRING NOT NULL COMMENT 'reader | writer | admin',
            updated_at TIMESTAMP,
            updated_by STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossaries")} (
            glossary_id  STRING NOT NULL,
            name         STRING NOT NULL,
            description  STRING,
            status       STRING COMMENT 'draft | approved | deprecated',
            created_at   TIMESTAMP,
            created_by   STRING,
            updated_at   TIMESTAMP,
            updated_by   STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossary_terms")} (
            term_id     STRING NOT NULL,
            glossary_id STRING,
            parent_term_id STRING,
            name        STRING NOT NULL,
            definition  STRING,
            domain      STRING,
            owner_email STRING,
            status      STRING COMMENT 'draft | approved | deprecated',
            is_mutually_exclusive BOOLEAN,
            created_at  TIMESTAMP,
            created_by  STRING,
            updated_at  TIMESTAMP,
            updated_by  STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossary_term_reviewers")} (
            term_id        STRING NOT NULL,
            reviewer_email STRING NOT NULL,
            reviewer_role  STRING COMMENT 'reviewer | approver | steward | owner',
            created_at     TIMESTAMP,
            created_by     STRING,
            updated_at     TIMESTAMP,
            updated_by     STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossary_term_versions")} (
            version_id           STRING NOT NULL,
            term_id              STRING NOT NULL,
            version_number       BIGINT,
            action               STRING COMMENT 'created | updated | reviewers-updated',
            change_note          STRING,
            name                 STRING NOT NULL,
            definition           STRING,
            domain               STRING,
            owner_email          STRING,
            status               STRING COMMENT 'draft | approved | deprecated',
            reviewer_snapshot_json STRING,
            created_at           TIMESTAMP,
            created_by           STRING,
            updated_at           TIMESTAMP,
            updated_by           STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossary_term_links")} (
            link_id          STRING NOT NULL,
            term_id          STRING NOT NULL,
            subject_type     STRING NOT NULL COMMENT 'asset | column',
            subject_fqn      STRING NOT NULL,
            column_name      STRING,
            is_primary       BOOLEAN,
            source           STRING COMMENT 'manual | uc_tag | migration',
            source_value     STRING,
            resolution_state STRING COMMENT 'linked | unresolved | retired',
            created_at       TIMESTAMP,
            created_by       STRING,
            updated_at       TIMESTAMP,
            updated_by       STRING,
            removed_at       TIMESTAMP,
            removed_by       STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("data_owners")} (
            uc_full_name STRING NOT NULL COMMENT 'catalog.schema.table',
            owner_email  STRING NOT NULL,
            owner_type   STRING COMMENT 'technical | business | steward',
            updated_at   TIMESTAMP,
            updated_by   STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("change_requests")} (
            request_id  STRING NOT NULL,
            created_at  TIMESTAMP,
            created_by  STRING,
            status      STRING COMMENT 'pending | approved | rejected',
            uc_full_name STRING,
            new_comment  STRING,
            new_uc_tags_json STRING,
            reviewed_at TIMESTAMP,
            reviewed_by STRING,
            review_note STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("governance_queue_projection")} (
            scope_key        STRING NOT NULL,
            lane_counts_json STRING,
            open_task_count  BIGINT,
            observed_at      TIMESTAMP,
            stale_after      TIMESTAMP,
            created_at       TIMESTAMP,
            created_by       STRING,
            updated_at       TIMESTAMP,
            updated_by       STRING
        ) USING DELTA""")

        self.uc.execute(f"""CREATE TABLE IF NOT EXISTS {self._fq("glossary_summary_projection")} (
            term_id         STRING NOT NULL,
            asset_count     BIGINT,
            child_count     BIGINT,
            reviewer_count  BIGINT,
            observed_at     TIMESTAMP,
            stale_after     TIMESTAMP,
            created_at      TIMESTAMP,
            created_by      STRING,
            updated_at      TIMESTAMP,
            updated_by      STRING
        ) USING DELTA""")

    # ── Roles ───────────────────────────────────────────────

    def get_role(self, email: str, admin_emails: List[str] | None = None) -> str:
        admin_emails = admin_emails or []
        e = email.strip().lower()
        if e and any(e == a.strip().lower() for a in admin_emails):
            return "admin"
        df = self.uc.query_df(
            f"SELECT role FROM {self._fq('user_roles')} "
            f"WHERE lower(email) = {sql_literal(e)} LIMIT 1"
        )
        if not df.empty and df.iloc[0].get("role"):
            return str(df.iloc[0]["role"]).lower()
        return "reader"

    def list_roles(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"SELECT email, role, updated_at, updated_by "
            f"FROM {self._fq('user_roles')} ORDER BY lower(email)"
        )

    def upsert_role(self, email: str, role: str, updated_by: str) -> None:
        e, r, u, ts = (
            email.strip().lower(),
            role.strip().lower(),
            updated_by.strip().lower(),
            _utc_now_ts(),
        )
        self.uc.execute(f"""MERGE INTO {self._fq("user_roles")} t
USING (SELECT {sql_literal(e)} AS email, {sql_literal(r)} AS role,
              timestamp({sql_literal(ts)}) AS updated_at,
              {sql_literal(u)} AS updated_by) s
ON lower(t.email) = lower(s.email)
WHEN MATCHED THEN UPDATE SET role=s.role, updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT * """)

    # ── Tenant branding (F7 white-label palette) ───────────

    def get_tenant_branding(self) -> Dict[str, Any]:
        """Return the single-row branding config. Absent row yields an
        empty dict so callers can fall back to hard-coded defaults."""
        try:
            df = self.uc.query_df(
                f"SELECT primary_color, accent_color, logo_url, "
                f"org_display_name, updated_at, updated_by "
                f"FROM {self._fq('tenant_branding')} "
                f"WHERE singleton_id = 'default' LIMIT 1"
            )
        except Exception:
            return {}
        if df is None or df.empty:
            return {}
        row = df.iloc[0].to_dict()
        return {
            "primaryColor": str(row.get("primary_color") or "").strip(),
            "accentColor": str(row.get("accent_color") or "").strip(),
            "logoUrl": str(row.get("logo_url") or "").strip(),
            "orgDisplayName": str(row.get("org_display_name") or "").strip(),
            "updatedAt": str(row.get("updated_at") or ""),
            "updatedBy": str(row.get("updated_by") or ""),
        }

    def upsert_tenant_branding(
        self,
        *,
        primary_color: str = "",
        accent_color: str = "",
        logo_url: str = "",
        org_display_name: str = "",
        updated_by: str = "",
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""MERGE INTO {self._fq("tenant_branding")} t
USING (
    SELECT 'default' AS singleton_id,
           {sql_literal(primary_color or "")} AS primary_color,
           {sql_literal(accent_color or "")} AS accent_color,
           {sql_literal(logo_url or "")} AS logo_url,
           {sql_literal(org_display_name or "")} AS org_display_name,
           timestamp({sql_literal(ts)}) AS updated_at,
           {sql_literal(updated_by or "")} AS updated_by
) s
ON t.singleton_id = s.singleton_id
WHEN MATCHED THEN UPDATE SET
    primary_color = s.primary_color,
    accent_color = s.accent_color,
    logo_url = s.logo_url,
    org_display_name = s.org_display_name,
    updated_at = s.updated_at,
    updated_by = s.updated_by
WHEN NOT MATCHED THEN INSERT (
    singleton_id, primary_color, accent_color, logo_url, org_display_name,
    created_at, created_by, updated_at, updated_by
) VALUES (
    s.singleton_id, s.primary_color, s.accent_color, s.logo_url, s.org_display_name,
    s.updated_at, s.updated_by, s.updated_at, s.updated_by
)"""
        )

    # ── Identity directory / entity registry ───────────────

    def list_identity_directory_entries(
        self,
        principal_type: str | None = None,
        *,
        active_only: bool = False,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if principal_type:
            clauses.append(f"lower(principal_type) = {sql_literal(principal_type.strip().lower())}")
        if active_only:
            clauses.append("COALESCE(is_active, TRUE) = TRUE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""
SELECT entry_id, external_key, principal_type, display_name, email, is_active,
       source, attributes_json, synced_at, created_at, created_by, updated_at, updated_by
FROM {self._fq('identity_directory_entries')}
{where}
ORDER BY lower(COALESCE(display_name, external_key)), lower(external_key)
"""
        )

    def upsert_identity_directory_entry(
        self,
        *,
        external_key: str,
        principal_type: str,
        display_name: str | None = None,
        email: str | None = None,
        is_active: bool = True,
        source: str = "databricks",
        attributes: Any = None,
        synced_at: str | None = None,
        updated_by: str,
        actor_role: str = "reader",
    ) -> Dict[str, Any]:
        normalized_external_key = str(external_key or "").strip()
        if not normalized_external_key:
            raise ValueError("external_key is required.")
        normalized_principal_type = str(principal_type or "").strip().lower() or "user"
        normalized_source = str(source or "").strip().lower() or "databricks"
        ts = _utc_now_ts()
        synced_value = str(synced_at or ts).strip() or ts
        attributes_json = _json_text(attributes) if attributes is not None else None
        existing_df = self.uc.query_df(
            f"""SELECT entry_id
FROM {self._fq('identity_directory_entries')}
WHERE lower(external_key) = {sql_literal(normalized_external_key.lower())}
  AND lower(COALESCE(source, '')) = {sql_literal(normalized_source)}
LIMIT 1"""
        )
        entry_id = (
            str(existing_df.iloc[0].get("entry_id") or "").strip()
            if existing_df is not None and not existing_df.empty
            else ""
        )
        if not entry_id:
            entry_id = uuid.uuid4().hex
        self.uc.execute(
            f"""MERGE INTO {self._fq("identity_directory_entries")} t
USING (SELECT {sql_literal(entry_id)} AS entry_id,
              {sql_literal(normalized_external_key)} AS external_key,
              {sql_literal(normalized_principal_type)} AS principal_type,
              {sql_literal(display_name)} AS display_name,
              {sql_literal(email)} AS email,
              {'TRUE' if is_active else 'FALSE'} AS is_active,
              {sql_literal(normalized_source)} AS source,
              {sql_literal(attributes_json)} AS attributes_json,
              timestamp({sql_literal(synced_value)}) AS synced_at,
              timestamp({sql_literal(ts)}) AS created_at,
              {sql_literal(updated_by)} AS created_by,
              timestamp({sql_literal(ts)}) AS updated_at,
              {sql_literal(updated_by)} AS updated_by) s
ON lower(t.external_key) = lower(s.external_key) AND lower(COALESCE(t.source, '')) = lower(COALESCE(s.source, ''))
WHEN MATCHED THEN UPDATE SET
    principal_type=s.principal_type,
    display_name=s.display_name,
    email=s.email,
    is_active=s.is_active,
    attributes_json=s.attributes_json,
    synced_at=s.synced_at,
    updated_at=s.updated_at,
    updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT *"""
        )
        self.append_metadata_audit(
            entity_type="identity_directory_entry",
            entity_id=normalized_external_key,
            action="identity-directory-upserted",
            actor_email=updated_by,
            actor_role=actor_role,
            after={
                "entryId": entry_id,
                "externalKey": normalized_external_key,
                "principalType": normalized_principal_type,
                "displayName": display_name or "",
                "email": email or "",
                "isActive": bool(is_active),
                "source": normalized_source,
                "attributes": attributes,
                "syncedAt": synced_value,
            },
        )
        return {
            "entryId": entry_id,
            "externalKey": normalized_external_key,
            "principalType": normalized_principal_type,
            "displayName": display_name or "",
            "email": email or "",
            "isActive": bool(is_active),
            "source": normalized_source,
            "attributes": attributes,
            "syncedAt": synced_value,
        }

    def list_entity_registry(
        self,
        entity_kind: str | None = None,
    ) -> pd.DataFrame:
        where = f"WHERE lower(entity_kind) = {sql_literal(entity_kind.strip().lower())}" if entity_kind else ""
        return self.uc.query_df(
            f"""
SELECT entity_id, entity_kind, entity_fqn, source_system, source_entity_id,
       reconciliation_state, reconciliation_confidence, observed_at,
       created_at, created_by, updated_at, updated_by
FROM {self._fq('entity_registry')}
{where}
ORDER BY lower(entity_kind), lower(COALESCE(entity_fqn, entity_id))
"""
        )

    def upsert_entity_registry(
        self,
        *,
        entity_id: str,
        entity_kind: str,
        entity_fqn: str | None = None,
        source_system: str = "databricks",
        source_entity_id: str | None = None,
        reconciliation_state: str = "matched",
        reconciliation_confidence: float | None = None,
        observed_at: str | None = None,
        updated_by: str,
        actor_role: str = "reader",
    ) -> Dict[str, Any]:
        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            raise ValueError("entity_id is required.")
        normalized_kind = str(entity_kind or "").strip().lower() or "asset"
        normalized_system = str(source_system or "").strip().lower() or "databricks"
        normalized_state = str(reconciliation_state or "").strip().lower() or "matched"
        ts = _utc_now_ts()
        observed_value = str(observed_at or ts).strip() or ts
        confidence_value = None
        if reconciliation_confidence is not None:
            try:
                confidence_value = float(reconciliation_confidence)
            except Exception:
                confidence_value = None
        self.uc.execute(
            f"""MERGE INTO {self._fq("entity_registry")} t
USING (SELECT {sql_literal(normalized_entity_id)} AS entity_id,
              {sql_literal(normalized_kind)} AS entity_kind,
              {sql_literal(entity_fqn)} AS entity_fqn,
              {sql_literal(normalized_system)} AS source_system,
              {sql_literal(source_entity_id)} AS source_entity_id,
              {sql_literal(normalized_state)} AS reconciliation_state,
              {confidence_value if confidence_value is not None else 'NULL'} AS reconciliation_confidence,
              timestamp({sql_literal(observed_value)}) AS observed_at,
              timestamp({sql_literal(ts)}) AS created_at,
              {sql_literal(updated_by)} AS created_by,
              timestamp({sql_literal(ts)}) AS updated_at,
              {sql_literal(updated_by)} AS updated_by) s
ON t.entity_id = s.entity_id
WHEN MATCHED THEN UPDATE SET
    entity_kind=s.entity_kind,
    entity_fqn=s.entity_fqn,
    source_system=s.source_system,
    source_entity_id=s.source_entity_id,
    reconciliation_state=s.reconciliation_state,
    reconciliation_confidence=s.reconciliation_confidence,
    observed_at=s.observed_at,
    updated_at=s.updated_at,
    updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT *"""
        )
        self.append_metadata_audit(
            entity_type="entity_registry",
            entity_id=normalized_entity_id,
            entity_fqn=entity_fqn,
            action="entity-registry-upserted",
            actor_email=updated_by,
            actor_role=actor_role,
            after={
                "entityId": normalized_entity_id,
                "entityKind": normalized_kind,
                "entityFqn": entity_fqn or "",
                "sourceSystem": normalized_system,
                "sourceEntityId": source_entity_id or "",
                "reconciliationState": normalized_state,
                "reconciliationConfidence": confidence_value,
                "observedAt": observed_value,
            },
        )
        return {
            "entityId": normalized_entity_id,
            "entityKind": normalized_kind,
            "entityFqn": entity_fqn or "",
            "sourceSystem": normalized_system,
            "sourceEntityId": source_entity_id or "",
            "reconciliationState": normalized_state,
            "reconciliationConfidence": confidence_value,
            "observedAt": observed_value,
        }

    def list_entity_aliases(
        self,
        entity_id: str | None = None,
        alias_type: str | None = None,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_id:
            clauses.append(f"entity_id = {sql_literal(entity_id)}")
        if alias_type:
            clauses.append(f"lower(alias_type) = {sql_literal(alias_type.strip().lower())}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""
SELECT alias_id, entity_id, alias_type, alias_value, source,
       created_at, created_by, updated_at, updated_by
FROM {self._fq('entity_aliases')}
{where}
ORDER BY lower(alias_type), lower(alias_value)
"""
        )

    def upsert_entity_alias(
        self,
        *,
        entity_id: str,
        alias_value: str,
        alias_type: str = "fqn",
        source: str = "reconciliation",
        updated_by: str,
        actor_role: str = "reader",
    ) -> Dict[str, Any]:
        normalized_entity_id = str(entity_id or "").strip()
        normalized_alias_value = str(alias_value or "").strip()
        if not normalized_entity_id or not normalized_alias_value:
            raise ValueError("entity_id and alias_value are required.")
        normalized_alias_type = str(alias_type or "").strip().lower() or "fqn"
        normalized_source = str(source or "").strip().lower() or "reconciliation"
        alias_id = uuid.uuid4().hex
        ts = _utc_now_ts()
        self.uc.execute(
            f"""DELETE FROM {self._fq("entity_aliases")}
WHERE entity_id = {sql_literal(normalized_entity_id)}
  AND lower(alias_type) = {sql_literal(normalized_alias_type)}
  AND lower(alias_value) = {sql_literal(normalized_alias_value.lower())}"""
        )
        self.uc.execute(
            f"""INSERT INTO {self._fq("entity_aliases")} (
    alias_id, entity_id, alias_type, alias_value, source,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(alias_id)},
    {sql_literal(normalized_entity_id)},
    {sql_literal(normalized_alias_type)},
    {sql_literal(normalized_alias_value)},
    {sql_literal(normalized_source)},
    timestamp({sql_literal(ts)}),
    {sql_literal(updated_by)},
    timestamp({sql_literal(ts)}),
    {sql_literal(updated_by)}
)"""
        )
        self.append_metadata_audit(
            entity_type="entity_alias",
            entity_id=normalized_entity_id,
            action="entity-alias-upserted",
            actor_email=updated_by,
            actor_role=actor_role,
            after={
                "aliasId": alias_id,
                "entityId": normalized_entity_id,
                "aliasType": normalized_alias_type,
                "aliasValue": normalized_alias_value,
                "source": normalized_source,
            },
        )
        return {
            "aliasId": alias_id,
            "entityId": normalized_entity_id,
            "aliasType": normalized_alias_type,
            "aliasValue": normalized_alias_value,
            "source": normalized_source,
        }

    # ── Workflow kernel ────────────────────────────────────

    def _ensure_actor_identity_entry(
        self,
        actor_email: str,
        *,
        actor_role: str = "reader",
    ) -> Dict[str, Any]:
        normalized_email = str(actor_email or "").strip().lower()
        if not normalized_email:
            raise ValueError("actor_email is required.")
        existing_df = self.uc.query_df(
            f"""SELECT entry_id, external_key, principal_type, display_name, email, is_active,
       source, attributes_json, synced_at
FROM {self._fq('identity_directory_entries')}
WHERE lower(external_key) = {sql_literal(normalized_email)}
  AND lower(COALESCE(source, '')) = 'runtime_actor'
LIMIT 1"""
        )
        if existing_df is not None and not existing_df.empty:
            row = existing_df.iloc[0]
            return {
                "entryId": str(row.get("entry_id") or "").strip(),
                "externalKey": str(row.get("external_key") or normalized_email).strip(),
                "principalType": str(row.get("principal_type") or "user").strip() or "user",
                "displayName": str(row.get("display_name") or normalized_email).strip(),
                "email": str(row.get("email") or normalized_email).strip(),
                "isActive": bool(row.get("is_active", True)),
                "source": str(row.get("source") or "runtime_actor").strip(),
                "attributes": _json_load(row.get("attributes_json")),
                "syncedAt": str(row.get("synced_at") or "").strip(),
            }
        return self.upsert_identity_directory_entry(
            external_key=normalized_email,
            principal_type="user",
            display_name=normalized_email,
            email=normalized_email,
            is_active=True,
            source="runtime_actor",
            updated_by=normalized_email,
            actor_role=actor_role,
        )

    def _ensure_identity_email_entry(
        self,
        email: str,
        *,
        source: str = "governance_recipient",
        updated_by: str | None = None,
        actor_role: str = "reader",
    ) -> Dict[str, Any]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            raise ValueError("email is required.")
        return self.upsert_identity_directory_entry(
            external_key=normalized_email,
            principal_type="user",
            display_name=normalized_email,
            email=normalized_email,
            is_active=True,
            source=source,
            updated_by=(updated_by or normalized_email).strip().lower(),
            actor_role=actor_role,
        )

    def _ensure_entity_registry_reference(
        self,
        entity_fqn: str,
        *,
        updated_by: str,
        actor_role: str = "reader",
        entity_kind: str = "asset",
    ) -> Dict[str, Any]:
        normalized_fqn = str(entity_fqn or "").strip()
        if not normalized_fqn:
            raise ValueError("entity_fqn is required.")
        existing_df = self.uc.query_df(
            f"""SELECT entity_id, entity_kind, entity_fqn
FROM {self._fq('entity_registry')}
WHERE lower(COALESCE(entity_fqn, '')) = {sql_literal(normalized_fqn.lower())}
LIMIT 1"""
        )
        if existing_df is not None and not existing_df.empty:
            row = existing_df.iloc[0]
            entity_id = str(row.get("entity_id") or "").strip()
            alias_df = self.uc.query_df(
                f"""SELECT alias_id
FROM {self._fq('entity_aliases')}
WHERE entity_id = {sql_literal(entity_id)}
  AND lower(alias_type) = 'fqn'
  AND lower(alias_value) = {sql_literal(normalized_fqn.lower())}
LIMIT 1"""
            )
            if alias_df is not None and not alias_df.empty:
                return {
                    "entityId": entity_id,
                    "entityKind": str(row.get("entity_kind") or entity_kind).strip() or entity_kind,
                    "entityFqn": str(row.get("entity_fqn") or normalized_fqn).strip(),
                    "sourceSystem": "uc",
                    "sourceEntityId": "",
                    "reconciliationState": "matched",
                    "reconciliationConfidence": 1.0,
                    "observedAt": "",
                }
        else:
            entity_id = uuid.uuid4().hex
        record = self.upsert_entity_registry(
            entity_id=entity_id,
            entity_kind=entity_kind,
            entity_fqn=normalized_fqn,
            source_system="uc",
            source_entity_id=None,
            reconciliation_state="matched",
            reconciliation_confidence=1.0,
            updated_by=updated_by,
            actor_role=actor_role,
        )
        self.upsert_entity_alias(
            entity_id=entity_id,
            alias_value=normalized_fqn,
            alias_type="fqn",
            source="live_fqn",
            updated_by=updated_by,
            actor_role=actor_role,
        )
        return record

    # ── batched writes ──────────────────────────────────────
    # A workflow action is several INSERT/UPDATEs; each is a full Statement
    # Execution round trip. Inside ``_batched_writes`` they are queued and sent
    # as one SQL-scripting ``BEGIN ... END`` call. The block is NOT atomic
    # (``BEGIN ATOMIC`` needs catalog-managed tables), but nothing is sent if
    # Python fails before the flush, so a half-built request no longer lands.

    def _exec_write(self, statement: str) -> None:
        pending = getattr(_WRITE_BATCH, "statements", None)
        if pending is not None and getattr(_WRITE_BATCH, "owner", None) is self:
            pending.append(statement)
            return
        self.uc.execute(statement)

    @contextmanager
    def _batched_writes(self) -> Iterator[None]:
        if not _SCRIPT_BATCHING["enabled"] or getattr(_WRITE_BATCH, "statements", None) is not None:
            yield
            return
        _WRITE_BATCH.statements, _WRITE_BATCH.owner = [], self
        try:
            yield
            statements = list(_WRITE_BATCH.statements)
        finally:
            _WRITE_BATCH.statements, _WRITE_BATCH.owner = None, None
        self._run_write_script(statements)

    def _flush_pending_writes(self) -> None:
        pending = getattr(_WRITE_BATCH, "statements", None)
        if pending and getattr(_WRITE_BATCH, "owner", None) is self:
            statements = list(pending)
            pending.clear()
            self._run_write_script(statements)

    def _run_write_script(self, statements: List[str]) -> None:
        if not statements:
            return
        if len(statements) == 1 or not _SCRIPT_BATCHING["enabled"]:
            for statement in statements:
                self.uc.execute(statement)
            return
        body = ";\n".join(statement.strip().rstrip(";") for statement in statements)
        try:
            self.uc.execute(f"BEGIN\n{body};\nEND")
        except Exception as exc:
            if not _scripting_unsupported(exc):
                raise
            # Rejected at parse time, so nothing ran: replay one by one.
            _SCRIPT_BATCHING["enabled"] = False
            _LOGGER.warning(
                "SQL scripting unavailable on this warehouse; writes fall back to one statement per call: %s",
                str(exc)[:200],
            )
            for statement in statements:
                self.uc.execute(statement)

    def _append_activity_event(
        self,
        *,
        event_type: str,
        actor_entry_id: str,
        entity_id: str | None,
        entity_fqn_snapshot: str | None,
        thread_id: str | None = None,
        task_id: str | None = None,
        column_name: str | None = None,
        payload: Any = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        ts = _utc_now_ts()
        self._exec_write(
            f"""INSERT INTO {self._fq("activity_events")} (
    event_id, event_type, entity_id, entity_fqn_snapshot, column_name,
    actor_entry_id, thread_id, task_id, payload_json, created_at
) VALUES (
    {sql_literal(event_id)},
    {sql_literal(event_type)},
    {sql_literal(entity_id)},
    {sql_literal(entity_fqn_snapshot)},
    {sql_literal(column_name)},
    {sql_literal(actor_entry_id)},
    {sql_literal(thread_id)},
    {sql_literal(task_id)},
    {sql_literal(_json_text(payload)) if payload is not None else "NULL"},
    timestamp({sql_literal(ts)})
)"""
        )
        return event_id

    def _workflow_notification_recipients(
        self,
        *,
        entity_fqn: str,
        thread_id: str,
        actor_email: str,
        actor_role: str = "reader",
        task_row: pd.Series | None = None,
        include_owners: bool = True,
        include_thread_participants: bool = True,
        include_assignee: bool = True,
        include_reviewer: bool = True,
        exclude_actor: bool = True,
    ) -> List[Dict[str, Any]]:
        recipient_emails: set[str] = set()
        normalized_actor = str(actor_email or "").strip().lower()

        if include_owners and entity_fqn:
            try:
                owners_df = self.get_owners(entity_fqn)
            except Exception:
                owners_df = pd.DataFrame()
            if owners_df is not None and not owners_df.empty:
                for owner_email in owners_df["owner_email"].dropna().astype(str).tolist():
                    normalized_owner = owner_email.strip().lower()
                    if normalized_owner:
                        recipient_emails.add(normalized_owner)

        if task_row is not None:
            if include_thread_participants:
                created_by_email = str(task_row.get("created_by_email") or "").strip().lower()
                if created_by_email:
                    recipient_emails.add(created_by_email)
            if include_assignee:
                assignee_email = str(task_row.get("assignee_email") or "").strip().lower()
                if assignee_email:
                    recipient_emails.add(assignee_email)
            if include_reviewer:
                reviewer_email = str(task_row.get("reviewer_email") or "").strip().lower()
                if reviewer_email:
                    recipient_emails.add(reviewer_email)

        if include_thread_participants and thread_id:
            try:
                posts_df = self.list_thread_posts(thread_id, limit=500)
            except Exception:
                posts_df = pd.DataFrame()
            if posts_df is not None and not posts_df.empty:
                for participant_email in posts_df["created_by_email"].dropna().astype(str).tolist():
                    normalized_participant = participant_email.strip().lower()
                    if normalized_participant:
                        recipient_emails.add(normalized_participant)

        if exclude_actor and normalized_actor:
            recipient_emails.discard(normalized_actor)

        recipients: List[Dict[str, Any]] = []
        for recipient_email in sorted(recipient_emails):
            recipients.append(
                self._ensure_identity_email_entry(
                    recipient_email,
                    source="governance_recipient",
                    updated_by=normalized_actor or recipient_email,
                    actor_role=actor_role,
                )
            )
        return recipients

    def _fanout_in_app_notification(
        self,
        *,
        event_id: str,
        event_type: str,
        entity_id: str | None,
        entity_fqn_snapshot: str | None,
        thread_id: str | None,
        task_id: str | None,
        actor_email: str,
        title: str,
        detail: str,
        status: str = "",
        recipients: Sequence[Dict[str, Any]],
    ) -> str | None:
        if not recipients:
            return None
        ts = _utc_now_ts()
        notification_id = hashlib.sha1(f"{event_id}:in_app".encode("utf-8")).hexdigest()[:24]
        payload = {
            "eventType": str(event_type or "").strip().lower(),
            "title": str(title or "").strip() or "Governance notification",
            "detail": str(detail or "").strip(),
            "status": str(status or "").strip(),
            "assetFqn": str(entity_fqn_snapshot or "").strip(),
            "assetLabel": str(entity_fqn_snapshot or "").strip(),
            "entityId": str(entity_id or "").strip(),
            "taskId": str(task_id or "").strip(),
            "threadId": str(thread_id or "").strip(),
            "createdBy": str(actor_email or "").strip().lower(),
            "createdAt": ts,
        }
        self.uc.execute(
            f"""MERGE INTO {self._fq("notifications")} t
USING (SELECT
         {sql_literal(notification_id)} AS notification_id,
         {sql_literal(event_id)} AS event_id,
         'in_app' AS channel,
         'delivered' AS delivery_state,
         {sql_literal(_json_text(payload))} AS payload_json,
         timestamp({sql_literal(ts)}) AS created_at,
         timestamp({sql_literal(ts)}) AS sent_at,
         CAST(NULL AS TIMESTAMP) AS failed_at,
         0 AS retry_count
      ) s
ON t.notification_id = s.notification_id
WHEN MATCHED THEN UPDATE SET
  event_id=s.event_id,
  channel=s.channel,
  delivery_state=s.delivery_state,
  payload_json=s.payload_json,
  sent_at=COALESCE(t.sent_at, s.sent_at),
  retry_count=COALESCE(t.retry_count, s.retry_count)
WHEN NOT MATCHED THEN INSERT (
  notification_id, event_id, channel, delivery_state, payload_json,
  created_at, sent_at, failed_at, retry_count
) VALUES (
  s.notification_id, s.event_id, s.channel, s.delivery_state, s.payload_json,
  s.created_at, s.sent_at, s.failed_at, s.retry_count
)"""
        )
        for recipient in recipients:
            recipient_entry_id = str(recipient.get("entryId") or "").strip()
            if not recipient_entry_id:
                continue
            self.uc.execute(
                f"""MERGE INTO {self._fq("notification_receipts")} t
USING (SELECT
         {sql_literal(notification_id)} AS notification_id,
         {sql_literal(recipient_entry_id)} AS recipient_entry_id,
         'new' AS inbox_state,
         CAST(NULL AS TIMESTAMP) AS seen_at,
         CAST(NULL AS TIMESTAMP) AS read_at,
         CAST(NULL AS TIMESTAMP) AS dismissed_at,
         timestamp({sql_literal(ts)}) AS delivered_at
      ) s
ON t.notification_id = s.notification_id
 AND t.recipient_entry_id = s.recipient_entry_id
WHEN MATCHED THEN UPDATE SET
  delivered_at=COALESCE(t.delivered_at, s.delivered_at)
WHEN NOT MATCHED THEN INSERT (
  notification_id, recipient_entry_id, inbox_state, seen_at, read_at,
  dismissed_at, delivered_at
) VALUES (
  s.notification_id, s.recipient_entry_id, s.inbox_state, s.seen_at, s.read_at,
  s.dismissed_at, s.delivered_at
)"""
            )
        return notification_id

    def list_threads(
        self,
        *,
        entity_fqn: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_fqn:
            clauses.append(
                f"lower(COALESCE(t.entity_fqn_snapshot, '')) = {sql_literal(str(entity_fqn).strip().lower())}"
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""
SELECT t.thread_id, t.entity_id, t.entity_fqn_snapshot, t.column_name, t.thread_type,
       t.status, t.created_by_entry_id, creator.email AS created_by_email,
       t.created_at, t.updated_at
FROM {self._fq('threads')} t
LEFT JOIN {self._fq('identity_directory_entries')} creator
  ON creator.entry_id = t.created_by_entry_id
{where}
ORDER BY t.updated_at DESC, t.thread_id DESC
LIMIT {int(limit)}
"""
        )

    def list_thread_posts(self, thread_id: str, limit: int = 200) -> pd.DataFrame:
        return self.uc.query_df(
            f"""
SELECT p.post_id, p.thread_id, p.body_markdown, p.diff_json,
       p.created_by_entry_id, creator.email AS created_by_email,
       p.created_at, p.edited_at
FROM {self._fq('thread_posts')} p
LEFT JOIN {self._fq('identity_directory_entries')} creator
  ON creator.entry_id = p.created_by_entry_id
WHERE p.thread_id = {sql_literal(thread_id)}
ORDER BY p.created_at ASC, p.post_id ASC
LIMIT {int(limit)}
"""
        )

    def _list_workflow_task_rows(
        self,
        *,
        task_id: str | None = None,
        entity_fqn: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if task_id:
            clauses.append(f"t.task_id = {sql_literal(task_id)}")
        if status:
            clauses.append(_task_request_status_predicate(status))
        if entity_fqn:
            clauses.append(
                f"lower(COALESCE(t.entity_fqn_snapshot, '')) = {sql_literal(str(entity_fqn).strip().lower())}"
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""
SELECT t.task_id, t.thread_id, t.entity_id, t.entity_fqn_snapshot, t.column_name,
       t.task_type, t.diff_before_json, t.diff_after_json, t.requested_payload_json,
       t.assignee_entry_id, assignee.email AS assignee_email,
       t.reviewer_entry_id, reviewer.email AS reviewer_email,
       t.due_at, t.status AS task_status, t.resolution_code,
       t.resolved_payload_json, t.expected_version, t.created_at, t.updated_at,
       th.thread_type, th.status AS thread_status,
       th.created_by_entry_id, creator.email AS created_by_email
FROM {self._fq('tasks')} t
LEFT JOIN {self._fq('threads')} th
  ON th.thread_id = t.thread_id
LEFT JOIN {self._fq('identity_directory_entries')} creator
  ON creator.entry_id = th.created_by_entry_id
LEFT JOIN {self._fq('identity_directory_entries')} assignee
  ON assignee.entry_id = t.assignee_entry_id
LEFT JOIN {self._fq('identity_directory_entries')} reviewer
  ON reviewer.entry_id = t.reviewer_entry_id
{where}
ORDER BY t.created_at DESC, t.task_id DESC
LIMIT {int(limit)}
"""
        )

    def _workflow_rows_to_legacy_requests(self, workflow_df: pd.DataFrame) -> pd.DataFrame:
        if workflow_df is None or workflow_df.empty:
            return pd.DataFrame(
                columns=[
                    "request_id",
                    "created_at",
                    "created_by",
                    "status",
                    "uc_full_name",
                    "new_comment",
                    "new_uc_tags_json",
                    "reviewed_at",
                    "reviewed_by",
                    "review_note",
                ]
            )
        rows: List[Dict[str, Any]] = []
        for _, row in workflow_df.iterrows():
            requested_payload = _json_load(row.get("requested_payload_json")) or {}
            resolved_payload = _json_load(row.get("resolved_payload_json")) or {}
            title = str(requested_payload.get("title") or "").strip()
            note = str(requested_payload.get("note") or "").strip()
            full_comment = str(requested_payload.get("fullComment") or "").strip()
            if not full_comment:
                full_comment = f"{title}: {note}".strip(": ").strip()
            request_status = _request_status_from_task(
                row.get("task_status"),
                row.get("resolution_code"),
            )
            reviewed_at = str(row.get("updated_at") or "").strip() if request_status != "pending" else ""
            rows.append(
                {
                    "request_id": str(row.get("task_id") or "").strip(),
                    "created_at": row.get("created_at"),
                    "created_by": str(row.get("created_by_email") or "").strip(),
                    "status": request_status,
                    "uc_full_name": str(row.get("entity_fqn_snapshot") or "").strip(),
                    "new_comment": full_comment or title or "Governance request",
                    "new_uc_tags_json": _json_text(requested_payload.get("requestedTags") or {}),
                    "reviewed_at": reviewed_at or None,
                    "reviewed_by": str(row.get("reviewer_email") or row.get("assignee_email") or "").strip() or None,
                    "review_note": str(resolved_payload.get("reviewNote") or "").strip() or None,
                    # Real task assignment (tasks.assignee_entry_id joined to
                    # the identity directory). _request_record surfaces this as
                    # assignedTo, which backs the workbench "Assigned to me"
                    # filter — previously always empty for workflow rows.
                    "assigned_to": str(row.get("assignee_email") or "").strip() or None,
                }
            )
        return pd.DataFrame(rows)

    def list_tasks(
        self,
        *,
        status: str | None = None,
        entity_fqn: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        workflow_df = self._list_workflow_task_rows(entity_fqn=entity_fqn, limit=limit)
        if workflow_df is None or workflow_df.empty:
            return pd.DataFrame()
        if not status:
            return workflow_df
        allowed = str(status or "").strip().lower()
        filtered = workflow_df[
            workflow_df.apply(
                lambda row: _request_status_from_task(
                    row.get("task_status"),
                    row.get("resolution_code"),
                )
                == allowed,
                axis=1,
            )
        ]
        return filtered.reset_index(drop=True)

    def list_activity_events(
        self,
        *,
        entity_fqn: str | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_fqn:
            clauses.append(
                f"lower(COALESCE(e.entity_fqn_snapshot, '')) = {sql_literal(str(entity_fqn).strip().lower())}"
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""
SELECT e.event_id, e.event_type, e.entity_id, e.entity_fqn_snapshot, e.column_name,
       e.actor_entry_id, actor.email AS actor_email, actor.display_name AS actor_display_name,
       e.thread_id, e.task_id, e.payload_json, e.created_at
FROM {self._fq('activity_events')} e
LEFT JOIN {self._fq('identity_directory_entries')} actor
  ON actor.entry_id = e.actor_entry_id
{where}
ORDER BY e.created_at DESC, e.event_id DESC
LIMIT {int(limit)}
"""
        )

    def list_notifications(
        self,
        *,
        recipient_email: str,
        unread_only: bool = False,
        limit: int = 25,
    ) -> pd.DataFrame:
        recipient_entry = self._ensure_identity_email_entry(
            recipient_email,
            source="governance_recipient",
            updated_by=recipient_email,
            actor_role="reader",
        )
        clauses = [f"r.recipient_entry_id = {sql_literal(str(recipient_entry.get('entryId') or ''))}"]
        clauses.append("lower(COALESCE(r.inbox_state, 'new')) <> 'dismissed'")
        if unread_only:
            clauses.append("lower(COALESCE(r.inbox_state, 'new')) NOT IN ('read', 'dismissed')")
        where = f"WHERE {' AND '.join(clauses)}"
        return self.uc.query_df(
            f"""
SELECT n.notification_id, n.event_id, n.channel, n.delivery_state, n.payload_json,
       n.created_at, n.sent_at, n.failed_at, n.retry_count,
       r.recipient_entry_id, r.inbox_state, r.seen_at, r.read_at, r.dismissed_at,
       r.delivered_at
FROM {self._fq('notifications')} n
INNER JOIN {self._fq('notification_receipts')} r
  ON r.notification_id = n.notification_id
{where}
ORDER BY n.created_at DESC, n.notification_id DESC
LIMIT {int(limit)}
"""
        )

    def count_unread_notifications(
        self,
        *,
        recipient_email: str,
    ) -> int:
        recipient_entry = self._ensure_identity_email_entry(
            recipient_email,
            source="governance_recipient",
            updated_by=recipient_email,
            actor_role="reader",
        )
        frame = self.uc.query_df(
            f"""
SELECT COUNT(*) AS unread_count
FROM {self._fq('notification_receipts')}
WHERE recipient_entry_id = {sql_literal(str(recipient_entry.get('entryId') or ''))}
  AND lower(COALESCE(inbox_state, 'new')) NOT IN ('read', 'dismissed')
"""
        )
        if frame is None or frame.empty:
            return 0
        try:
            return int(frame.iloc[0].get("unread_count") or 0)
        except Exception:
            return 0

    def update_notification_receipt(
        self,
        *,
        notification_id: str,
        recipient_email: str,
        action: str,
    ) -> Dict[str, Any]:
        normalized_notification_id = str(notification_id or "").strip()
        normalized_action = str(action or "").strip().lower()
        if not normalized_notification_id:
            raise ValueError("notification_id is required.")
        if normalized_action not in {"seen", "read", "dismiss"}:
            raise ValueError("action must be one of seen, read, dismiss.")
        recipient_entry = self._ensure_identity_email_entry(
            recipient_email,
            source="governance_recipient",
            updated_by=recipient_email,
            actor_role="reader",
        )
        recipient_entry_id = str(recipient_entry.get("entryId") or "").strip()
        current_df = self.uc.query_df(
            f"""
SELECT notification_id, inbox_state, seen_at, read_at, dismissed_at
FROM {self._fq('notification_receipts')}
WHERE notification_id = {sql_literal(normalized_notification_id)}
  AND recipient_entry_id = {sql_literal(recipient_entry_id)}
LIMIT 1
"""
        )
        if current_df is None or current_df.empty:
            raise ValueError("notification receipt was not found.")
        before = current_df.iloc[0].to_dict()
        ts = _utc_now_ts()
        set_clauses = [
            f"seen_at = COALESCE(seen_at, timestamp({sql_literal(ts)}))",
        ]
        if normalized_action == "seen":
            set_clauses.insert(
                0,
                "inbox_state = CASE WHEN lower(COALESCE(inbox_state, 'new')) = 'new' THEN 'seen' ELSE inbox_state END",
            )
        elif normalized_action == "read":
            set_clauses.insert(0, "inbox_state = 'read'")
            set_clauses.append(f"read_at = COALESCE(read_at, timestamp({sql_literal(ts)}))")
        else:
            set_clauses.insert(0, "inbox_state = 'dismissed'")
            set_clauses.append(f"dismissed_at = COALESCE(dismissed_at, timestamp({sql_literal(ts)}))")
        self.uc.execute(
            f"""UPDATE {self._fq("notification_receipts")}
SET {", ".join(set_clauses)}
WHERE notification_id = {sql_literal(normalized_notification_id)}
  AND recipient_entry_id = {sql_literal(recipient_entry_id)}"""
        )
        after_state = "dismissed" if normalized_action == "dismiss" else normalized_action
        self.append_metadata_audit(
            entity_type="notification_receipt",
            entity_id=f"{normalized_notification_id}:{recipient_entry_id}",
            action="notification-receipt-updated",
            actor_email=recipient_email,
            actor_role="reader",
            before=before,
            after={"notificationId": normalized_notification_id, "inboxState": after_state, "updatedAt": ts},
            source="store",
            detail=normalized_action,
        )
        return {
            "notificationId": normalized_notification_id,
            "recipientEntryId": recipient_entry_id,
            "inboxState": after_state,
        }

    # ── Summary projections ────────────────────────────────

    def list_governance_queue_projections(self, scope_key: str | None = None) -> pd.DataFrame:
        clauses: List[str] = []
        if scope_key is not None:
            clauses.append(f"scope_key = {sql_literal(scope_key)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            return self.uc.query_df(
                f"""
SELECT scope_key, lane_counts_json, open_task_count, observed_at, stale_after,
       created_at, created_by, updated_at, updated_by
FROM {self._fq('governance_queue_projection')}
{where}
ORDER BY updated_at DESC, scope_key
"""
            )
        except Exception:
            return pd.DataFrame()

    def get_governance_queue_projection(self, scope_key: str) -> Dict[str, Any] | None:
        frame = self.list_governance_queue_projections(scope_key=scope_key)
        if frame is None or frame.empty:
            return None
        row = frame.iloc[0]
        return {
            "scopeKey": _text_value(row.get("scope_key")) or "",
            "laneCounts": _json_load(row.get("lane_counts_json")) or {},
            "openTaskCount": _int_value(row.get("open_task_count")),
            "observedAt": _text_value(row.get("observed_at")),
            "staleAfter": _text_value(row.get("stale_after")),
            "createdAt": _text_value(row.get("created_at")),
            "createdBy": _text_value(row.get("created_by")),
            "updatedAt": _text_value(row.get("updated_at")),
            "updatedBy": _text_value(row.get("updated_by")),
        }

    def upsert_governance_queue_projection(
        self,
        *,
        scope_key: str,
        lane_counts: Dict[str, Any] | None = None,
        open_task_count: int = 0,
        observed_at: str | None = None,
        stale_after: str | None = None,
        updated_by: str = "system",
    ) -> Dict[str, Any]:
        normalized_scope_key = str(scope_key or "").strip()
        if not normalized_scope_key:
            raise ValueError("scope_key is required.")
        normalized_updated_by = str(updated_by or "system").strip().lower() or "system"
        observed_ts = str(observed_at or _utc_now_ts()).strip()
        stale_ts = str(stale_after or "").strip()
        lane_counts_json = _json_text(lane_counts or {})
        self.uc.execute(
            f"""MERGE INTO {self._fq("governance_queue_projection")} t
USING (SELECT
         {sql_literal(normalized_scope_key)} AS scope_key,
         {sql_literal(lane_counts_json)} AS lane_counts_json,
         {int(open_task_count)} AS open_task_count,
         timestamp({sql_literal(observed_ts)}) AS observed_at,
         {'timestamp(' + sql_literal(stale_ts) + ')' if stale_ts else 'CAST(NULL AS TIMESTAMP)'} AS stale_after,
         timestamp({sql_literal(observed_ts)}) AS created_at,
         {sql_literal(normalized_updated_by)} AS created_by,
         timestamp({sql_literal(observed_ts)}) AS updated_at,
         {sql_literal(normalized_updated_by)} AS updated_by
      ) s
ON t.scope_key = s.scope_key
WHEN MATCHED THEN UPDATE SET
  lane_counts_json=s.lane_counts_json,
  open_task_count=s.open_task_count,
  observed_at=s.observed_at,
  stale_after=s.stale_after,
  updated_at=s.updated_at,
  updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  scope_key, lane_counts_json, open_task_count, observed_at, stale_after,
  created_at, created_by, updated_at, updated_by
) VALUES (
  s.scope_key, s.lane_counts_json, s.open_task_count, s.observed_at, s.stale_after,
  s.created_at, s.created_by, s.updated_at, s.updated_by
)"""
        )
        return {
            "scopeKey": normalized_scope_key,
            "laneCounts": lane_counts or {},
            "openTaskCount": int(open_task_count or 0),
            "observedAt": observed_ts,
            "staleAfter": stale_ts or None,
            "updatedBy": normalized_updated_by,
        }

    def list_glossary_summary_projections(self, term_id: str | None = None) -> pd.DataFrame:
        clauses: List[str] = []
        if term_id is not None:
            clauses.append(f"term_id = {sql_literal(term_id)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            return self.uc.query_df(
                f"""
SELECT term_id, asset_count, child_count, reviewer_count, observed_at, stale_after,
       created_at, created_by, updated_at, updated_by
FROM {self._fq('glossary_summary_projection')}
{where}
ORDER BY updated_at DESC, term_id
"""
            )
        except Exception:
            return pd.DataFrame()

    def get_glossary_summary_projection(self, term_id: str) -> Dict[str, Any] | None:
        frame = self.list_glossary_summary_projections(term_id=term_id)
        if frame is None or frame.empty:
            return None
        row = frame.iloc[0]
        return {
            "termId": _text_value(row.get("term_id")) or "",
            "assetCount": _int_value(row.get("asset_count")),
            "childCount": _int_value(row.get("child_count")),
            "reviewerCount": _int_value(row.get("reviewer_count")),
            "observedAt": _text_value(row.get("observed_at")),
            "staleAfter": _text_value(row.get("stale_after")),
            "createdAt": _text_value(row.get("created_at")),
            "createdBy": _text_value(row.get("created_by")),
            "updatedAt": _text_value(row.get("updated_at")),
            "updatedBy": _text_value(row.get("updated_by")),
        }

    def upsert_glossary_summary_projection(
        self,
        *,
        term_id: str,
        asset_count: int = 0,
        child_count: int = 0,
        reviewer_count: int = 0,
        observed_at: str | None = None,
        stale_after: str | None = None,
        updated_by: str = "system",
    ) -> Dict[str, Any]:
        normalized_term_id = str(term_id or "").strip()
        if not normalized_term_id:
            raise ValueError("term_id is required.")
        normalized_updated_by = str(updated_by or "system").strip().lower() or "system"
        observed_ts = str(observed_at or _utc_now_ts()).strip()
        stale_ts = str(stale_after or "").strip()
        self.uc.execute(
            f"""MERGE INTO {self._fq("glossary_summary_projection")} t
USING (SELECT
         {sql_literal(normalized_term_id)} AS term_id,
         {int(asset_count)} AS asset_count,
         {int(child_count)} AS child_count,
         {int(reviewer_count)} AS reviewer_count,
         timestamp({sql_literal(observed_ts)}) AS observed_at,
         {'timestamp(' + sql_literal(stale_ts) + ')' if stale_ts else 'CAST(NULL AS TIMESTAMP)'} AS stale_after,
         timestamp({sql_literal(observed_ts)}) AS created_at,
         {sql_literal(normalized_updated_by)} AS created_by,
         timestamp({sql_literal(observed_ts)}) AS updated_at,
         {sql_literal(normalized_updated_by)} AS updated_by
      ) s
ON t.term_id = s.term_id
WHEN MATCHED THEN UPDATE SET
  asset_count=s.asset_count,
  child_count=s.child_count,
  reviewer_count=s.reviewer_count,
  observed_at=s.observed_at,
  stale_after=s.stale_after,
  updated_at=s.updated_at,
  updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  term_id, asset_count, child_count, reviewer_count, observed_at, stale_after,
  created_at, created_by, updated_at, updated_by
) VALUES (
  s.term_id, s.asset_count, s.child_count, s.reviewer_count, s.observed_at, s.stale_after,
  s.created_at, s.created_by, s.updated_at, s.updated_by
)"""
        )
        return {
            "termId": normalized_term_id,
            "assetCount": int(asset_count or 0),
            "childCount": int(child_count or 0),
            "reviewerCount": int(reviewer_count or 0),
            "observedAt": observed_ts,
            "staleAfter": stale_ts or None,
            "updatedBy": normalized_updated_by,
        }

    def refresh_governance_queue_projection(
        self,
        *,
        scope_key: str = "workspace:default",
        updated_by: str = "system",
    ) -> Dict[str, Any] | None:
        try:
            requests_df = self.list_change_requests(limit=100000)
        except Exception:
            requests_df = pd.DataFrame()
        pending_records: List[Dict[str, Any]] = []
        if requests_df is not None and not requests_df.empty:
            for _, row in requests_df.iterrows():
                status = str(row.get("status") or "").strip().lower()
                if status != "pending":
                    continue
                pending_records.append(
                    {
                        "title": str(row.get("new_comment") or "").strip(),
                        "new_comment": str(row.get("new_comment") or "").strip(),
                        "detail": str(row.get("new_comment") or "").strip(),
                        "uc_full_name": str(row.get("uc_full_name") or "").strip(),
                        "status": status,
                    }
                )
        lane_counts = {
            "open-work": 0,
            "ownership": 0,
            "classification": 0,
            "trust": 0,
        }
        for record in pending_records:
            lane_counts[_governance_lane_from_request_record(record)] += 1
        try:
            return self.upsert_governance_queue_projection(
                scope_key=scope_key,
                lane_counts=lane_counts,
                open_task_count=len(pending_records),
                observed_at=_utc_now_ts(),
                stale_after=_utc_future_ts(300),
                updated_by=updated_by,
            )
        except Exception:
            return None

    def refresh_glossary_summary_projection(
        self,
        *,
        term_id: str,
        updated_by: str = "system",
    ) -> Dict[str, Any] | None:
        normalized_term_id = str(term_id or "").strip()
        if not normalized_term_id:
            return None
        term_row = self.get_glossary_term(normalized_term_id)
        if term_row is None or term_row.empty:
            return None
        try:
            reviewers_df = self.list_glossary_reviewers(normalized_term_id)
        except Exception:
            reviewers_df = pd.DataFrame()
        try:
            terms_df = self.list_glossary_terms(limit=5000)
        except Exception:
            terms_df = pd.DataFrame()
        try:
            links_df = self.list_glossary_term_links(term_id=normalized_term_id, include_removed=False)
        except Exception:
            links_df = pd.DataFrame()

        child_count = 0
        if terms_df is not None and not terms_df.empty and "parent_term_id" in terms_df.columns:
            child_count = int(
                terms_df["parent_term_id"].fillna("").astype(str).str.strip().eq(normalized_term_id).sum()
            )

        asset_count = 0
        if links_df is not None and not links_df.empty:
            active_links = links_df.copy()
            if "resolution_state" in active_links.columns:
                active_links = active_links[
                    active_links["resolution_state"]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                    .isin({"", "linked", "unresolved"})
                ].copy()
            if "subject_type" in active_links.columns:
                active_links = active_links[
                    active_links["subject_type"].fillna("").astype(str).str.lower().eq("asset")
                ].copy()
            if not active_links.empty and "subject_fqn" in active_links.columns:
                asset_count = len(
                    {
                        str(value).strip()
                        for value in active_links["subject_fqn"].dropna().astype(str).tolist()
                        if str(value).strip()
                    }
                )

        reviewer_count = 0 if reviewers_df is None or reviewers_df.empty else int(len(reviewers_df.index))
        try:
            return self.upsert_glossary_summary_projection(
                term_id=normalized_term_id,
                asset_count=asset_count,
                child_count=child_count,
                reviewer_count=reviewer_count,
                observed_at=_utc_now_ts(),
                stale_after=_utc_future_ts(300),
                updated_by=updated_by,
            )
        except Exception:
            return None

    def create_workflow_request(
        self,
        *,
        created_by: str,
        entity_fqn: str,
        title: str,
        note: str = "",
        requested_tags: Dict[str, str] | None = None,
        actor_role: str = "reader",
        column_name: str | None = None,
    ) -> Dict[str, Any]:
        actor_entry = self._ensure_actor_identity_entry(created_by, actor_role=actor_role)
        entity_record = self._ensure_entity_registry_reference(
            entity_fqn,
            updated_by=created_by,
            actor_role=actor_role,
        )
        ts = _utc_now_ts()
        thread_id = uuid.uuid4().hex
        post_id = uuid.uuid4().hex
        task_id = uuid.uuid4().hex
        task_type = "tag_change" if requested_tags else "description_change"
        requested_payload = {
            "title": str(title or "").strip() or "Governance request",
            "note": str(note or "").strip(),
            "fullComment": f"{str(title or '').strip()}: {str(note or '').strip()}".strip(": ").strip(),
            "requestedTags": requested_tags or {},
        }
        with self._batched_writes():
            self._exec_write(
                f"""INSERT INTO {self._fq("threads")} (
        thread_id, entity_id, entity_fqn_snapshot, column_name, thread_type, status,
        created_by_entry_id, created_at, updated_at
    ) VALUES (
        {sql_literal(thread_id)},
        {sql_literal(entity_record.get("entityId"))},
        {sql_literal(entity_fqn)},
        {sql_literal(column_name)},
        'task_request',
        'open',
        {sql_literal(actor_entry.get("entryId"))},
        timestamp({sql_literal(ts)}),
        timestamp({sql_literal(ts)})
    )"""
            )
            self._exec_write(
                f"""INSERT INTO {self._fq("thread_posts")} (
        post_id, thread_id, body_markdown, diff_json, created_by_entry_id, created_at, edited_at
    ) VALUES (
        {sql_literal(post_id)},
        {sql_literal(thread_id)},
        {sql_literal(note or title)},
        {sql_literal(_json_text(requested_payload))},
        {sql_literal(actor_entry.get("entryId"))},
        timestamp({sql_literal(ts)}),
        NULL
    )"""
            )
            self._exec_write(
                f"""INSERT INTO {self._fq("tasks")} (
        task_id, thread_id, entity_id, entity_fqn_snapshot, column_name, task_type,
        diff_before_json, diff_after_json, requested_payload_json,
        assignee_entry_id, reviewer_entry_id, due_at, status, resolution_code,
        resolved_payload_json, expected_version, created_at, updated_at
    ) VALUES (
        {sql_literal(task_id)},
        {sql_literal(thread_id)},
        {sql_literal(entity_record.get("entityId"))},
        {sql_literal(entity_fqn)},
        {sql_literal(column_name)},
        {sql_literal(task_type)},
        NULL,
        {sql_literal(_json_text(requested_payload))},
        {sql_literal(_json_text(requested_payload))},
        NULL,
        NULL,
        NULL,
        'open',
        NULL,
        NULL,
        1,
        timestamp({sql_literal(ts)}),
        timestamp({sql_literal(ts)})
    )"""
            )
            comment_event_id = self._append_activity_event(
                event_type="comment_created",
                actor_entry_id=str(actor_entry.get("entryId") or ""),
                entity_id=str(entity_record.get("entityId") or ""),
                entity_fqn_snapshot=entity_fqn,
                column_name=column_name,
                thread_id=thread_id,
                task_id=task_id,
                payload={"body": note or title},
            )
            task_event_id = self._append_activity_event(
                event_type="task_created",
                actor_entry_id=str(actor_entry.get("entryId") or ""),
                entity_id=str(entity_record.get("entityId") or ""),
                entity_fqn_snapshot=entity_fqn,
                column_name=column_name,
                thread_id=thread_id,
                task_id=task_id,
                payload={"title": requested_payload.get("title"), "taskType": task_type},
            )
        task_recipients = self._workflow_notification_recipients(
            entity_fqn=entity_fqn,
            thread_id=thread_id,
            actor_email=created_by,
            actor_role=actor_role,
            include_owners=True,
            include_thread_participants=False,
            include_assignee=False,
            include_reviewer=False,
        )
        self._fanout_in_app_notification(
            event_id=task_event_id,
            event_type="task_created",
            entity_id=str(entity_record.get("entityId") or ""),
            entity_fqn_snapshot=entity_fqn,
            thread_id=thread_id,
            task_id=task_id,
            actor_email=created_by,
            title="Task created",
            detail=str(requested_payload.get("title") or title or note or "Governance request"),
            status=_request_status_label("pending"),
            recipients=task_recipients,
        )
        self.append_metadata_audit(
            entity_type="task",
            entity_id=task_id,
            entity_fqn=entity_fqn,
            column_name=column_name,
            request_id=task_id,
            action="task-created",
            actor_email=created_by,
            actor_role=actor_role,
            source="store",
            after={
                "threadId": thread_id,
                "taskId": task_id,
                "taskType": task_type,
                "requestedPayload": requested_payload,
            },
        )
        self.refresh_governance_queue_projection(updated_by=created_by)
        return {
            "threadId": thread_id,
            "taskId": task_id,
            "entityId": entity_record.get("entityId"),
            "entityFqn": entity_fqn,
            "taskType": task_type,
            "requestedPayload": requested_payload,
        }

    def update_workflow_task_status(
        self,
        *,
        task_id: str,
        status: str,
        reviewed_by: str,
        review_note: str | None = None,
        actor_role: str = "reader",
        refresh_projection: bool = True,
        assignee: str | None = None,
        priority: str | None = None,
    ) -> None:
        workflow_df = self._list_workflow_task_rows(task_id=task_id, limit=1)
        if workflow_df is None or workflow_df.empty:
            raise ValueError("task_id was not found.")
        row = workflow_df.iloc[0]
        fast_mode = not refresh_projection
        task_status, resolution_code = _task_status_from_request_status(status)
        thread_status = _thread_status_from_task_status(task_status)
        reviewer_entry = None
        if fast_mode:
            normalized_reviewed_by = str(reviewed_by or "").strip().lower()
            for entry_id_key, email_key in (
                ("reviewer_entry_id", "reviewer_email"),
                ("assignee_entry_id", "assignee_email"),
                ("created_by_entry_id", "created_by_email"),
            ):
                entry_id = str(row.get(entry_id_key) or "").strip()
                email = str(row.get(email_key) or "").strip().lower()
                if entry_id and email and email == normalized_reviewed_by:
                    reviewer_entry = {"entryId": entry_id, "email": email}
                    break
        if reviewer_entry is None:
            reviewer_entry = self._ensure_actor_identity_entry(reviewed_by, actor_role=actor_role)
        ts = _utc_now_ts()
        resolved_payload = {
            "reviewNote": str(review_note or "").strip(),
            "requestStatus": str(status or "").strip().lower(),
        }
        request_status = _request_status_from_task(task_status, resolution_code)
        request_status_label = _request_status_label(request_status)
        requested_payload = _json_load(row.get("requested_payload_json")) or {}
        current_task_status = str(row.get("task_status") or "").strip().lower()
        current_resolution_code = str(row.get("resolution_code") or "").strip().lower()
        next_resolution_code = str(resolution_code or "").strip().lower()
        status_changed = (
            current_task_status != str(task_status or "").strip().lower()
            or current_resolution_code != next_resolution_code
        )
        # Triage riders (Stewardship Workbench "Assign to me" / priority
        # picker). Both are no-ops when None/empty so a plain status update
        # never clears recorded triage state.
        normalized_assignee = str(assignee or "").strip().lower()
        current_assignee = str(row.get("assignee_email") or "").strip().lower()
        assignee_changed = bool(normalized_assignee) and normalized_assignee != current_assignee
        assignee_entry: Dict[str, Any] | None = None
        if assignee_changed:
            assignee_entry = self._ensure_identity_email_entry(
                normalized_assignee,
                source="governance_assignee",
                updated_by=reviewed_by,
                actor_role=actor_role,
            )
        normalized_priority = str(priority or "").strip().lower()
        requested_tags = requested_payload.get("requestedTags")
        if not isinstance(requested_tags, dict):
            requested_tags = {}
            requested_payload["requestedTags"] = requested_tags
        current_priority = str(requested_tags.get("priority") or "").strip().lower()
        priority_changed = bool(normalized_priority) and normalized_priority != current_priority
        if priority_changed:
            # The tasks table has no priority column; requestedTags inside
            # requested_payload_json is the migration-free stash the workbench
            # payload already reads priority from (_request_record).
            requested_tags["priority"] = normalized_priority
        triage_changed = assignee_changed or priority_changed
        with self._batched_writes():
            if status_changed or triage_changed or not fast_mode:
                triage_sets = ""
                if assignee_changed and assignee_entry is not None:
                    triage_sets += f",\n    assignee_entry_id = {sql_literal(assignee_entry.get('entryId'))}"
                if priority_changed:
                    triage_sets += f",\n    requested_payload_json = {sql_literal(_json_text(requested_payload))}"
                self._exec_write(
                    f"""UPDATE {self._fq("tasks")}
    SET status = {sql_literal(task_status)},
        resolution_code = {sql_literal(resolution_code)},
        reviewer_entry_id = {sql_literal(reviewer_entry.get("entryId"))},
        resolved_payload_json = {sql_literal(_json_text(resolved_payload))},
        expected_version = COALESCE(expected_version, 0) + 1,
        updated_at = timestamp({sql_literal(ts)}){triage_sets}
    WHERE task_id = {sql_literal(task_id)}"""
                )
                self._exec_write(
                    f"""UPDATE {self._fq("threads")}
    SET status = {sql_literal(thread_status)},
        updated_at = timestamp({sql_literal(ts)})
    WHERE thread_id = {sql_literal(str(row.get("thread_id") or ""))}"""
                )
            if review_note:
                comment_event_id = None
                self._exec_write(
                    f"""INSERT INTO {self._fq("thread_posts")} (
        post_id, thread_id, body_markdown, diff_json, created_by_entry_id, created_at, edited_at
    ) VALUES (
        {sql_literal(uuid.uuid4().hex)},
        {sql_literal(str(row.get("thread_id") or ""))},
        {sql_literal(review_note)},
        {sql_literal(_json_text(resolved_payload))},
        {sql_literal(reviewer_entry.get("entryId"))},
        timestamp({sql_literal(ts)}),
        NULL
    )"""
                )
                comment_event_id = self._append_activity_event(
                    event_type="comment_created",
                    actor_entry_id=str(reviewer_entry.get("entryId") or ""),
                    entity_id=str(row.get("entity_id") or ""),
                    entity_fqn_snapshot=str(row.get("entity_fqn_snapshot") or ""),
                    column_name=str(row.get("column_name") or "") or None,
                    thread_id=str(row.get("thread_id") or ""),
                    task_id=task_id,
                    payload={"body": review_note},
                )
                if comment_event_id and not fast_mode:
                    self._flush_pending_writes()
                    comment_recipients = self._workflow_notification_recipients(
                        entity_fqn=str(row.get("entity_fqn_snapshot") or ""),
                        thread_id=str(row.get("thread_id") or ""),
                        actor_email=reviewed_by,
                        actor_role=actor_role,
                        task_row=row,
                        include_owners=False,
                        include_thread_participants=True,
                        include_assignee=True,
                        include_reviewer=True,
                    )
                    self._fanout_in_app_notification(
                        event_id=comment_event_id,
                        event_type="comment_created",
                        entity_id=str(row.get("entity_id") or ""),
                        entity_fqn_snapshot=str(row.get("entity_fqn_snapshot") or ""),
                        thread_id=str(row.get("thread_id") or ""),
                        task_id=task_id,
                        actor_email=reviewed_by,
                        title="Comment added",
                        detail=review_note,
                        status=request_status_label,
                        recipients=comment_recipients,
                    )
            task_event_id = None
            if status_changed or triage_changed or not fast_mode:
                activity_payload: Dict[str, Any] = {
                    "status": task_status,
                    "resolutionCode": resolution_code,
                    "reviewNote": review_note or "",
                }
                # Triage changes ride the same activity event so assignment and
                # priority updates are visible in the asset activity stream.
                if assignee_changed:
                    activity_payload["assignedTo"] = normalized_assignee
                if priority_changed:
                    activity_payload["priority"] = normalized_priority
                task_event_id = self._append_activity_event(
                    event_type="task_state_changed",
                    actor_entry_id=str(reviewer_entry.get("entryId") or ""),
                    entity_id=str(row.get("entity_id") or ""),
                    entity_fqn_snapshot=str(row.get("entity_fqn_snapshot") or ""),
                    column_name=str(row.get("column_name") or "") or None,
                    thread_id=str(row.get("thread_id") or ""),
                    task_id=task_id,
                    payload=activity_payload,
                )
        if task_event_id and not fast_mode:
            state_recipients = self._workflow_notification_recipients(
                entity_fqn=str(row.get("entity_fqn_snapshot") or ""),
                thread_id=str(row.get("thread_id") or ""),
                actor_email=reviewed_by,
                actor_role=actor_role,
                task_row=row,
                include_owners=True,
                include_thread_participants=True,
                include_assignee=True,
                include_reviewer=True,
            )
            self._fanout_in_app_notification(
                event_id=task_event_id,
                event_type="task_state_changed",
                entity_id=str(row.get("entity_id") or ""),
                entity_fqn_snapshot=str(row.get("entity_fqn_snapshot") or ""),
                thread_id=str(row.get("thread_id") or ""),
                task_id=task_id,
                actor_email=reviewed_by,
                title="Task updated",
                detail=(
                    str(review_note or "").strip()
                    or str(requested_payload.get("title") or "").strip()
                    or request_status_label
                ),
                status=request_status_label,
                recipients=state_recipients,
            )
        # Audit contract: triage-only updates (assign/priority with no status
        # transition) still land an audit row, labeled distinctly so evidence
        # reviews can tell "assigned" apart from "status changed".
        audit_after: Dict[str, Any] = {
            "status": task_status,
            "resolutionCode": resolution_code,
            "reviewNote": review_note or "",
            "updatedAt": ts,
        }
        if assignee_changed:
            audit_after["assignedTo"] = normalized_assignee
        if priority_changed:
            audit_after["priority"] = normalized_priority
        self.append_metadata_audit(
            entity_type="task",
            entity_id=task_id,
            entity_fqn=str(row.get("entity_fqn_snapshot") or ""),
            column_name=str(row.get("column_name") or "") or None,
            request_id=task_id,
            action=(
                "task-status-updated"
                if status_changed
                else ("task-triage-updated" if triage_changed else "task-comment-added")
            ),
            actor_email=reviewed_by,
            actor_role=actor_role,
            before=self._workflow_rows_to_legacy_requests(workflow_df).iloc[0].to_dict(),
            after=audit_after,
            detail=review_note,
        )
        if refresh_projection:
            self.refresh_governance_queue_projection(updated_by=reviewed_by)

    # ── Glossary (UC-native) ────────────────────────────────

    def list_glossary_terms(
        self, status: str | None = None, limit: int = 200
    ) -> pd.DataFrame:
        where = f"WHERE status = {sql_literal(status)}" if status else ""
        return self._cached_list_read(
            "glossary_terms",
            status,
            limit,
            lambda: self.uc.query_df(
                f"SELECT {GLOSSARY_TERM_COLUMNS} FROM {self._fq('glossary_terms')} {where} "
                f"ORDER BY lower(name) LIMIT {int(limit)}"
            ),
            lambda frame, wanted: frame["status"].fillna("").astype(str).str.lower().eq(wanted),
        )

    def get_glossary_term(self, term_id: str) -> Optional[pd.Series]:
        df = self.uc.query_df(
            f"SELECT {GLOSSARY_TERM_COLUMNS} FROM {self._fq('glossary_terms')} "
            f"WHERE term_id = {sql_literal(term_id)} LIMIT 1"
        )
        return df.iloc[0] if not df.empty else None

    def find_glossary_term_id_by_name(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        if not normalized:
            return ""
        df = self.uc.query_df(
            f"SELECT term_id FROM {self._fq('glossary_terms')} "
            f"WHERE lower(name) = {sql_literal(normalized)} LIMIT 1"
        )
        if df.empty:
            return ""
        return str(df.iloc[0].get("term_id") or "").strip()

    def list_glossary_term_links(
        self,
        term_id: str | None = None,
        subject_type: str | None = None,
        subject_fqn: str | None = None,
        column_name: str | None = None,
        resolution_state: str | None = None,
        include_removed: bool = False,
    ) -> pd.DataFrame:
        where: List[str] = []
        if term_id:
            where.append(f"l.term_id = {sql_literal(term_id)}")
        if subject_type:
            where.append(f"lower(l.subject_type) = {sql_literal(subject_type.strip().lower())}")
        if subject_fqn:
            where.append(f"l.subject_fqn = {sql_literal(subject_fqn)}")
        if column_name is not None:
            where.append(f"COALESCE(l.column_name, '') = {sql_literal(column_name)}")
        if resolution_state:
            where.append(
                f"lower(COALESCE(l.resolution_state, '')) = {sql_literal(resolution_state.strip().lower())}"
            )
        if not include_removed:
            where.append("l.removed_at IS NULL")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return self.uc.query_df(
            f"""
SELECT
    l.link_id,
    l.term_id,
    COALESCE(t.name, l.source_value) AS term_name,
    l.subject_type,
    l.subject_fqn,
    l.column_name,
    l.is_primary,
    l.source,
    l.source_value,
    l.resolution_state,
    l.created_at,
    l.created_by,
    l.updated_at,
    l.updated_by,
    l.removed_at,
    l.removed_by
FROM {self._fq('glossary_term_links')} l
LEFT JOIN {self._fq('glossary_terms')} t
  ON l.term_id = t.term_id
{where_sql}
ORDER BY l.subject_type, l.subject_fqn, COALESCE(l.column_name, ''), l.is_primary DESC, lower(COALESCE(t.name, l.source_value))
"""
        )

    def _resolve_glossary_term_reference(self, reference: Any) -> Dict[str, Any]:
        if isinstance(reference, dict):
            source_value = str(
                reference.get("sourceValue")
                or reference.get("termName")
                or reference.get("name")
                or reference.get("value")
                or reference.get("termId")
                or ""
            ).strip()
            term_id = str(reference.get("termId") or reference.get("term_id") or "").strip()
            is_primary = bool(reference.get("isPrimary", True))
            source = str(reference.get("source") or "manual").strip().lower() or "manual"
        else:
            source_value = str(reference or "").strip()
            term_id = ""
            is_primary = True
            source = "manual"

        if term_id:
            existing = self.get_glossary_term(term_id)
            if existing is not None and not existing.empty:
                return {
                    "termId": term_id,
                    "termName": str(existing.get("name") or source_value).strip(),
                    "sourceValue": source_value or str(existing.get("name") or "").strip(),
                    "resolutionState": "linked",
                    "isPrimary": is_primary,
                    "source": source,
                }

        resolved_term_id = self.find_glossary_term_id_by_name(source_value)
        if resolved_term_id:
            term = self.get_glossary_term(resolved_term_id)
            term_name = str(term.get("name") if term is not None else source_value).strip() if term is not None else source_value
            return {
                "termId": resolved_term_id,
                "termName": term_name or source_value,
                "sourceValue": source_value or term_name,
                "resolutionState": "linked",
                "isPrimary": is_primary,
                "source": source,
            }

        unresolved_id = hashlib.sha1(source_value.lower().encode("utf-8")).hexdigest()[:16] if source_value else uuid.uuid4().hex[:16]
        return {
            "termId": f"unresolved:{unresolved_id}",
            "termName": source_value,
            "sourceValue": source_value,
            "resolutionState": "unresolved",
            "isPrimary": is_primary,
            "source": source,
        }

    def replace_glossary_term_links(
        self,
        *,
        subject_type: str,
        subject_fqn: str,
        term_refs: Sequence[Any] | None = None,
        links: Sequence[Any] | None = None,
        updated_by: str,
        column_name: str | None = None,
        source: str = "manual",
        refresh_projection: bool = True,
    ) -> List[Dict[str, Any]]:
        normalized_subject_type = str(subject_type or "").strip().lower()
        normalized_subject_fqn = str(subject_fqn or "").strip()
        normalized_column_name = str(column_name or "").strip()
        if not normalized_subject_type or not normalized_subject_fqn:
            return []
        existing_links = self.list_glossary_term_links(
            subject_type=normalized_subject_type,
            subject_fqn=normalized_subject_fqn,
            column_name=normalized_column_name,
            include_removed=False,
        )
        ts = _utc_now_ts()
        self.uc.execute(
            f"""UPDATE {self._fq("glossary_term_links")}
SET resolution_state = 'retired',
    removed_at = timestamp({sql_literal(ts)}),
    removed_by = {sql_literal(updated_by)},
    updated_at = timestamp({sql_literal(ts)}),
    updated_by = {sql_literal(updated_by)}
WHERE lower(subject_type) = {sql_literal(normalized_subject_type)}
  AND subject_fqn = {sql_literal(normalized_subject_fqn)}
  AND COALESCE(column_name, '') = {sql_literal(normalized_column_name)}
  AND removed_at IS NULL"""
        )

        references = term_refs if term_refs is not None else links
        normalized_links: List[Dict[str, Any]] = []
        for index, reference in enumerate(references or []):
            link = self._resolve_glossary_term_reference(reference)
            source_value = str(link.get("sourceValue") or "").strip()
            term_id = str(link.get("termId") or "").strip()
            if not source_value and not term_id:
                continue
            normalized_links.append(
                {
                    "linkId": uuid.uuid4().hex,
                    "termId": term_id,
                    "termName": str(link.get("termName") or source_value).strip(),
                    "subjectType": normalized_subject_type,
                    "subjectFqn": normalized_subject_fqn,
                    "columnName": normalized_column_name or None,
                    "isPrimary": bool(reference.get("isPrimary") if isinstance(reference, dict) else index == 0),
                    "source": str(reference.get("source") if isinstance(reference, dict) else source).strip().lower()
                    or source,
                    "sourceValue": source_value,
                    "resolutionState": str(link.get("resolutionState") or "unresolved").strip().lower(),
                    "createdBy": updated_by,
                }
            )

        if not normalized_links:
            return []

        rows = ", ".join(
            (
                "("
                f"{sql_literal(entry['linkId'])}, "
                f"{sql_literal(entry['termId'])}, "
                f"{sql_literal(entry['subjectType'])}, "
                f"{sql_literal(entry['subjectFqn'])}, "
                f"{sql_literal(entry['columnName']) if entry['columnName'] else 'NULL'}, "
                f"{'TRUE' if entry['isPrimary'] else 'FALSE'}, "
                f"{sql_literal(entry['source'])}, "
                f"{sql_literal(entry['sourceValue'])}, "
                f"{sql_literal(entry['resolutionState'])}, "
                f"timestamp({sql_literal(ts)}), "
                f"{sql_literal(updated_by)}, "
                f"timestamp({sql_literal(ts)}), "
                f"{sql_literal(updated_by)}, "
                "NULL, NULL"
                ")"
            )
            for entry in normalized_links
        )
        self.uc.execute(
            f"""INSERT INTO {self._fq("glossary_term_links")} (
    link_id, term_id, subject_type, subject_fqn, column_name, is_primary,
    source, source_value, resolution_state,
    created_at, created_by, updated_at, updated_by, removed_at, removed_by
) VALUES {rows}"""
        )
        affected_term_ids = {
            str(term_id).strip()
            for term_id in (
                []
                if existing_links is None or existing_links.empty
                else existing_links["term_id"].dropna().astype(str).tolist()
            )
            if str(term_id).strip() and not str(term_id).strip().startswith("unresolved:")
        }
        affected_term_ids.update(
            {
                str(entry.get("termId") or "").strip()
                for entry in normalized_links
                if str(entry.get("termId") or "").strip()
                and not str(entry.get("termId") or "").strip().startswith("unresolved:")
            }
        )
        if refresh_projection:
            for affected_term_id in sorted(affected_term_ids):
                self.refresh_glossary_summary_projection(term_id=affected_term_id, updated_by=updated_by)
        return normalized_links

    def subject_glossary_term_links(
        self,
        subject_type: str,
        subject_fqn: str,
        *,
        column_name: str | None = None,
        include_removed: bool = False,
    ) -> pd.DataFrame:
        return self.list_glossary_term_links(
            subject_type=subject_type,
            subject_fqn=subject_fqn,
            column_name=column_name,
            include_removed=include_removed,
        )

    def list_glossary_reviewers(self, term_id: str | None = None) -> pd.DataFrame:
        where = f"WHERE term_id = {sql_literal(term_id)}" if term_id else ""
        return self.uc.query_df(
            f"SELECT term_id, reviewer_email, reviewer_role, created_at, created_by, updated_at, updated_by "
            f"FROM {self._fq('glossary_term_reviewers')} {where} "
            f"ORDER BY term_id, lower(reviewer_email)"
        )

    def upsert_glossary_reviewers(
        self,
        term_id: str,
        reviewers: List[Dict[str, Any]] | None,
        updated_by: str,
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        seen: set[str] = set()
        for entry in reviewers or []:
            reviewer_email = str(entry.get("reviewerEmail") or entry.get("email") or "").strip().lower()
            if not reviewer_email or reviewer_email in seen:
                continue
            seen.add(reviewer_email)
            reviewer_role = str(entry.get("reviewerRole") or entry.get("role") or "reviewer").strip().lower()
            if not reviewer_role:
                reviewer_role = "reviewer"
            normalized.append(
                {
                    "reviewerEmail": reviewer_email,
                    "reviewerRole": reviewer_role,
                }
            )

        self.uc.execute(
            f"DELETE FROM {self._fq('glossary_term_reviewers')} "
            f"WHERE term_id = {sql_literal(term_id)}"
        )

        if not normalized:
            return []

        ts = _utc_now_ts()
        rows = ", ".join(
            (
                "("
                f"{sql_literal(term_id)}, "
                f"{sql_literal(entry['reviewerEmail'])}, "
                f"{sql_literal(entry['reviewerRole'])}, "
                f"timestamp({sql_literal(ts)}), "
                f"{sql_literal(updated_by)}, "
                f"timestamp({sql_literal(ts)}), "
                f"{sql_literal(updated_by)}"
                ")"
            )
            for entry in normalized
        )
        self.uc.execute(
            f"""INSERT INTO {self._fq("glossary_term_reviewers")} (
    term_id, reviewer_email, reviewer_role,
    created_at, created_by, updated_at, updated_by
) VALUES {rows}"""
        )
        return normalized

    def list_glossary_versions(self, term_id: str | None = None) -> pd.DataFrame:
        where = f"WHERE term_id = {sql_literal(term_id)}" if term_id else ""
        return self.uc.query_df(
            f"SELECT version_id, term_id, version_number, action, change_note, name, definition, domain, owner_email, status, "
            f"reviewer_snapshot_json, created_at, created_by, updated_at, updated_by "
            f"FROM {self._fq('glossary_term_versions')} {where} "
            f"ORDER BY term_id, version_number DESC, created_at DESC"
        )

    def append_glossary_version(
        self,
        term_id: str,
        action: str,
        change_note: str | None,
        updated_by: str,
    ) -> Dict[str, Any]:
        term_df = self.uc.query_df(
            f"SELECT {GLOSSARY_TERM_COLUMNS} FROM {self._fq('glossary_terms')} "
            f"WHERE term_id = {sql_literal(term_id)} LIMIT 1"
        )
        if term_df.empty:
            raise ValueError(f"Glossary term {term_id!r} not found.")
        reviewers_df = self.list_glossary_reviewers(term_id)
        max_df = self.uc.query_df(
            f"SELECT COALESCE(MAX(version_number), 0) AS max_version "
            f"FROM {self._fq('glossary_term_versions')} "
            f"WHERE term_id = {sql_literal(term_id)}"
        )
        max_version = 0
        if not max_df.empty:
            raw_max = max_df.iloc[0].get("max_version")
            if raw_max is not None and not pd.isna(raw_max):
                try:
                    max_version = int(raw_max)
                except Exception:
                    max_version = 0
        version_number = max_version + 1
        row = term_df.iloc[0]
        ts = _utc_now_ts()
        reviewer_snapshot = []
        if reviewers_df is not None and not reviewers_df.empty:
            reviewer_snapshot = [
                {
                    "reviewerEmail": str(record.get("reviewer_email") or "").strip().lower(),
                    "reviewerRole": str(record.get("reviewer_role") or "reviewer").strip().lower() or "reviewer",
                    "updatedAt": str(record.get("updated_at")) if record.get("updated_at") else None,
                    "updatedBy": str(record.get("updated_by")) if record.get("updated_by") else None,
                }
                for record in reviewers_df.to_dict(orient="records")
                if str(record.get("reviewer_email") or "").strip()
            ]
        version_id = uuid.uuid4().hex
        self.uc.execute(
            f"""INSERT INTO {self._fq("glossary_term_versions")} (
    version_id, term_id, version_number, action, change_note,
    name, definition, domain, owner_email, status, reviewer_snapshot_json,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(version_id)},
    {sql_literal(term_id)},
    {int(version_number)},
    {sql_literal(action)},
    {sql_literal(change_note)},
    {sql_literal(row.get("name"))},
    {sql_literal(row.get("definition"))},
    {sql_literal(row.get("domain"))},
    {sql_literal(row.get("owner_email"))},
    {sql_literal(row.get("status"))},
    {sql_literal(json.dumps(reviewer_snapshot)) if reviewer_snapshot else "NULL"},
    timestamp({sql_literal(ts)}),
    {sql_literal(updated_by)},
    timestamp({sql_literal(ts)}),
    {sql_literal(updated_by)}
)"""
        )
        return {
            "versionId": version_id,
            "termId": term_id,
            "versionNumber": version_number,
            "action": action,
            "changeNote": change_note or "",
            "reviewerSnapshot": reviewer_snapshot,
        }

    def upsert_glossary_term(
        self,
        term_id: str,
        name: str,
        definition: str | None = None,
        domain: str | None = None,
        owner_email: str | None = None,
        status: str = "draft",
        updated_by: str = "",
        reviewers: List[Dict[str, Any]] | None = None,
        change_note: str | None = None,
        actor_role: str = "reader",
        refresh_projection: bool = True,
    ) -> Dict[str, Any]:
        ts = _utc_now_ts()
        existing = self.get_glossary_term(term_id)
        existing_reviewers = self.list_glossary_reviewers(term_id)
        action = "created" if existing is None or existing.empty else "updated"
        self.uc.execute(f"""MERGE INTO {self._fq("glossary_terms")} t
USING (SELECT {sql_literal(term_id)} AS term_id,
              {sql_literal(name)} AS name,
              {sql_literal(definition)} AS definition,
              {sql_literal(domain)} AS domain,
              {sql_literal(owner_email)} AS owner_email,
              {sql_literal(status)} AS status,
              timestamp({sql_literal(ts)}) AS updated_at,
              {sql_literal(updated_by)} AS updated_by) s
ON t.term_id = s.term_id
WHEN MATCHED THEN UPDATE SET
    name=s.name, definition=s.definition, domain=s.domain,
    owner_email=s.owner_email, status=s.status,
    updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
    term_id, name, definition, domain, owner_email, status,
    created_at, created_by, updated_at, updated_by
) VALUES (
    s.term_id, s.name, s.definition, s.domain, s.owner_email, s.status,
    s.updated_at, s.updated_by, s.updated_at, s.updated_by
)""")
        if reviewers is not None:
            self.upsert_glossary_reviewers(term_id, reviewers, updated_by)
            if action == "updated":
                action = "reviewers-updated" if not change_note else action
        version = self.append_glossary_version(
            term_id=term_id,
            action=action,
            change_note=change_note,
            updated_by=updated_by,
        )
        updated_term = self.get_glossary_term(term_id)
        updated_reviewers = self.list_glossary_reviewers(term_id)
        self.append_metadata_audit(
            entity_type="glossary_term",
            entity_id=term_id,
            action=action,
            actor_email=updated_by,
            actor_role=actor_role,
            before={
                "term": None if existing is None or existing.empty else existing.to_dict(),
                "reviewers": []
                if existing_reviewers is None or existing_reviewers.empty
                else existing_reviewers.to_dict(orient="records"),
            },
            after={
                "term": None if updated_term is None or updated_term.empty else updated_term.to_dict(),
                "reviewers": []
                if updated_reviewers is None or updated_reviewers.empty
                else updated_reviewers.to_dict(orient="records"),
                "version": version,
            },
            detail=change_note,
        )
        if refresh_projection:
            self.refresh_glossary_summary_projection(term_id=term_id, updated_by=updated_by)
        return version

    def search_glossary(self, query: str, limit: int = 25) -> pd.DataFrame:
        q = query.strip().lower()
        return self.uc.query_df(
            f"SELECT {GLOSSARY_TERM_COLUMNS} FROM {self._fq('glossary_terms')} "
            f"WHERE lower(name) LIKE {sql_literal(f'%{q}%')} "
            f"   OR lower(definition) LIKE {sql_literal(f'%{q}%')} "
            f"ORDER BY lower(name) LIMIT {int(limit)}"
        )

    # ── Data owners ─────────────────────────────────────────

    def get_owners(self, uc_full_name: str) -> pd.DataFrame:
        return self.uc.query_df(
            f"SELECT owner_email, owner_type, updated_at, updated_by "
            f"FROM {self._fq('data_owners')} "
            f"WHERE uc_full_name = {sql_literal(uc_full_name)} "
            f"ORDER BY owner_type"
        )

    def list_owner_assignments(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"SELECT uc_full_name, owner_email, owner_type, updated_at, updated_by "
            f"FROM {self._fq('data_owners')} "
            f"ORDER BY uc_full_name, owner_type, owner_email"
        )

    def upsert_owner(
        self,
        uc_full_name: str,
        owner_email: str,
        owner_type: str,
        updated_by: str,
        actor_role: str = "reader",
        request_id: str | None = None,
    ) -> None:
        before_df = self.uc.query_df(
            f"SELECT owner_email, owner_type, updated_at, updated_by "
            f"FROM {self._fq('data_owners')} "
            f"WHERE uc_full_name = {sql_literal(uc_full_name)} "
            f"AND lower(owner_email) = {sql_literal(owner_email.strip().lower())} "
            f"LIMIT 1"
        )
        ts = _utc_now_ts()
        self.uc.execute(f"""MERGE INTO {self._fq("data_owners")} t
USING (SELECT {sql_literal(uc_full_name)} AS uc_full_name,
              {sql_literal(owner_email)} AS owner_email,
              {sql_literal(owner_type)} AS owner_type,
              timestamp({sql_literal(ts)}) AS updated_at,
              {sql_literal(updated_by)} AS updated_by) s
ON t.uc_full_name = s.uc_full_name AND lower(t.owner_email) = lower(s.owner_email)
WHEN MATCHED THEN UPDATE SET owner_type=s.owner_type, updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT * """)
        after_df = self.get_owners(uc_full_name)
        self.append_metadata_audit(
            entity_type="owner_assignment",
            entity_fqn=uc_full_name,
            entity_id=owner_email.strip().lower(),
            action="owner-upserted",
            actor_email=updated_by,
            actor_role=actor_role,
            request_id=request_id,
            before=[]
            if before_df is None or before_df.empty
            else before_df.to_dict(orient="records"),
            after=[]
            if after_df is None or after_df.empty
            else after_df.to_dict(orient="records"),
        )

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
    ) -> None:
        before_df = self.uc.query_df(
            f"SELECT owner_email, owner_type, updated_at, updated_by "
            f"FROM {self._fq('data_owners')} "
            f"WHERE uc_full_name = {sql_literal(uc_full_name)} "
            f"AND lower(owner_email) = {sql_literal(owner_email.strip().lower())} "
            f"LIMIT 1"
        )
        self.uc.execute(
            f"DELETE FROM {self._fq('data_owners')} "
            f"WHERE uc_full_name = {sql_literal(uc_full_name)} "
            f"AND lower(owner_email) = {sql_literal(owner_email.strip().lower())}"
        )
        # The `before` snapshot below is the reversibility record: it captures
        # the exact owner_email/owner_type that was cleared so the assignment can
        # be reconstructed from the audit log. `note`/`action` let the identity
        # integrity cleanup label its removals distinctly from user-driven ones.
        self.append_metadata_audit(
            entity_type="owner_assignment",
            entity_fqn=uc_full_name,
            entity_id=owner_email.strip().lower(),
            action=action,
            actor_email=actor_email or owner_email.strip().lower(),
            actor_role=actor_role,
            request_id=request_id,
            before=[]
            if before_df is None or before_df.empty
            else before_df.to_dict(orient="records"),
            after=[],
            detail=note,
        )

    # ── Change requests ─────────────────────────────────────

    def create_change_request(
        self,
        created_by: str,
        uc_full_name: str | None = None,
        new_comment: str | None = None,
        new_uc_tags: Dict[str, str] | None = None,
        actor_role: str = "reader",
    ) -> str:
        comment = str(new_comment or "").strip()
        title = comment.split(":", 1)[0].strip() if ":" in comment else comment
        note = comment.split(":", 1)[1].strip() if ":" in comment else comment
        payload = self.create_workflow_request(
            created_by=created_by,
            entity_fqn=str(uc_full_name or "").strip(),
            title=title or "Governance request",
            note=note or comment or "Governance request",
            requested_tags=new_uc_tags,
            actor_role=actor_role,
        )
        return str(payload.get("taskId") or "")

    def list_change_requests(
        self, status: str | None = None, limit: int = 200
    ) -> pd.DataFrame:
        return self._cached_list_read(
            "change_requests",
            status,
            limit,
            lambda: self._list_change_requests_uncached(status=status, limit=limit),
            lambda frame, wanted: frame["status"].fillna("").astype(str).str.lower().eq(wanted),
        )

    def _list_change_requests_uncached(
        self, status: str | None = None, limit: int = 200
    ) -> pd.DataFrame:
        workflow_rows = self._workflow_rows_to_legacy_requests(
            self._list_workflow_task_rows(status=status, limit=int(limit))
        )
        legacy_where = f"WHERE status = {sql_literal(status)}" if status else ""
        legacy_rows = self.uc.query_df(
            f"SELECT {CHANGE_REQUEST_COLUMNS} FROM {self._fq('change_requests')} {legacy_where} "
            f"ORDER BY created_at DESC LIMIT {int(limit)}"
        )
        combined = pd.concat(
            [
                workflow_rows,
                legacy_rows if legacy_rows is not None else pd.DataFrame(),
            ],
            ignore_index=True,
        )
        if combined.empty:
            return combined
        if status:
            combined = combined[
                combined["status"].fillna("").astype(str).str.lower().eq(str(status).strip().lower())
            ]
        combined = combined.sort_values(
            by=["created_at", "request_id"],
            ascending=[False, False],
            na_position="last",
        )
        request_id_series = combined["request_id"].fillna("").astype(str).str.strip()
        with_ids = combined[request_id_series.ne("")].copy()
        if not with_ids.empty:
            with_ids = with_ids.assign(_request_id_norm=request_id_series[request_id_series.ne("")].values)
            with_ids = with_ids.drop_duplicates(subset=["_request_id_norm"], keep="first").drop(
                columns=["_request_id_norm"]
            )
        without_ids = combined[request_id_series.eq("")].copy()
        combined = pd.concat([with_ids, without_ids], ignore_index=True)
        combined = combined.sort_values(
            by=["created_at", "request_id"],
            ascending=[False, False],
            na_position="last",
        )
        return combined.head(int(limit)).reset_index(drop=True)

    def get_change_request(self, request_id: str) -> Optional[ChangeRequest]:
        workflow_rows = self._workflow_rows_to_legacy_requests(
            self._list_workflow_task_rows(task_id=request_id, limit=1)
        )
        if workflow_rows is not None and not workflow_rows.empty:
            row = workflow_rows.iloc[0].to_dict()
        else:
            df = self.uc.query_df(
                f"SELECT {CHANGE_REQUEST_COLUMNS} FROM {self._fq('change_requests')} "
                f"WHERE request_id = {sql_literal(request_id)} LIMIT 1"
            )
            if df.empty:
                return None
            row = df.iloc[0].to_dict()
        return ChangeRequest(
            request_id=str(row.get("request_id") or ""),
            created_at=str(row.get("created_at") or ""),
            created_by=str(row.get("created_by") or ""),
            status=str(row.get("status") or ""),
            uc_full_name=row.get("uc_full_name"),
            new_comment=row.get("new_comment"),
            new_uc_tags=_json_load(row.get("new_uc_tags_json")),
            reviewed_at=str(row.get("reviewed_at")) if row.get("reviewed_at") else None,
            reviewed_by=row.get("reviewed_by"),
            review_note=row.get("review_note"),
        )

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
    ) -> None:
        workflow_df = self._list_workflow_task_rows(task_id=request_id, limit=1)
        if workflow_df is not None and not workflow_df.empty:
            self.update_workflow_task_status(
                task_id=request_id,
                status=status,
                reviewed_by=reviewed_by,
                review_note=review_note,
                actor_role=actor_role,
                refresh_projection=refresh_projection,
                assignee=assignee,
                priority=priority,
            )
            return
        before = self.get_change_request(request_id)
        ts = _utc_now_ts()
        # Legacy change_requests rows have no assignee/priority columns; the
        # migration-free stash for such fields is new_uc_tags_json (the
        # workbench payload reads assignedTo/priority back out of it via
        # _request_record). Merge rather than overwrite so tag-change payloads
        # survive a triage update.
        triage_set = ""
        if (assignee or priority) and before is not None:
            stashed_tags = dict(before.new_uc_tags or {})
            if assignee:
                stashed_tags["assignedTo"] = str(assignee).strip().lower()
            if priority:
                stashed_tags["priority"] = str(priority).strip().lower()
            triage_set = f",\n    new_uc_tags_json = {sql_literal(_json_text(stashed_tags))}"
        self.uc.execute(f"""UPDATE {self._fq("change_requests")}
SET status      = {sql_literal(status)},
    reviewed_at = timestamp({sql_literal(ts)}),
    reviewed_by = {sql_literal(reviewed_by)},
    review_note = {sql_literal(review_note) if review_note else "NULL"}{triage_set}
WHERE request_id = {sql_literal(request_id)}""")
        after = self.get_change_request(request_id)
        self.append_metadata_audit(
            entity_type="change_request",
            entity_id=request_id,
            entity_fqn=getattr(before, "uc_full_name", None) if before is not None else None,
            request_id=request_id,
            action="change-request-status-updated",
            actor_email=reviewed_by,
            actor_role=actor_role,
            before=None if before is None else before.__dict__,
            after=None if after is None else after.__dict__,
            detail=review_note,
        )
        if refresh_projection:
            self.refresh_governance_queue_projection(updated_by=reviewed_by)

    # ------------------------------------------------------------------
    # Phase 8 — custom properties
    # ------------------------------------------------------------------
    def insert_custom_property_definition(
        self,
        *,
        definition_id: str,
        entity_kind: str,
        property_key: str,
        display_name: str,
        description: str | None,
        data_type: str,
        enum_values: list[str] | None,
        is_required: bool,
        is_multi: bool,
        scope: dict | None,
        created_by: str,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('custom_property_definitions')} (
    definition_id, entity_kind, property_key, display_name, description,
    data_type, enum_values_json, is_required, is_multi, scope_json, state,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(definition_id)},
    {sql_literal(entity_kind)},
    {sql_literal(property_key)},
    {sql_literal(display_name)},
    {sql_literal(description)},
    {sql_literal(data_type)},
    {sql_literal(_json_text(enum_values)) if enum_values else 'NULL'},
    {'TRUE' if is_required else 'FALSE'},
    {'TRUE' if is_multi else 'FALSE'},
    {sql_literal(_json_text(scope)) if scope else 'NULL'},
    {sql_literal('active')},
    timestamp({sql_literal(ts)}),
    {sql_literal(created_by)},
    timestamp({sql_literal(ts)}),
    {sql_literal(created_by)}
)"""
        )

    def insert_custom_property_definition_version(
        self,
        *,
        version_id: str,
        definition_id: str,
        version_number: int,
        snapshot_json: str,
        change_summary: str | None,
        recorded_by: str,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('custom_property_definition_versions')} (
    version_id, definition_id, version_number, snapshot_json,
    change_summary, recorded_by, recorded_at
) VALUES (
    {sql_literal(version_id)},
    {sql_literal(definition_id)},
    {int(version_number)},
    {sql_literal(snapshot_json)},
    {sql_literal(change_summary)},
    {sql_literal(recorded_by)},
    timestamp({sql_literal(ts)})
)"""
        )

    def list_custom_property_definitions(
        self,
        *,
        entity_kind: str | None = None,
        state: str | None = "active",
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if entity_kind:
            clauses.append(f"entity_kind = {sql_literal(entity_kind)}")
        if state:
            clauses.append(f"state = {sql_literal(state)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT definition_id, entity_kind, property_key, display_name, description,
    data_type, enum_values_json, is_required, is_multi, scope_json, state,
    created_at, created_by, updated_at, updated_by
FROM {self._fq('custom_property_definitions')} {where}
ORDER BY display_name ASC, definition_id ASC"""
        )

    def upsert_custom_property_assignment(
        self,
        *,
        assignment_id: str,
        definition_id: str,
        definition_version: int,
        entity_kind: str,
        entity_fqn: str | None,
        column_name: str | None,
        value: Any,
        actor_email: str,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""DELETE FROM {self._fq('custom_property_assignments')}
WHERE definition_id = {sql_literal(definition_id)}
  AND entity_kind = {sql_literal(entity_kind)}
  AND COALESCE(entity_fqn, '') = {sql_literal(entity_fqn or '')}
  AND COALESCE(column_name, '') = {sql_literal(column_name or '')}"""
        )
        self.uc.execute(
            f"""INSERT INTO {self._fq('custom_property_assignments')} (
    assignment_id, definition_id, definition_version, entity_kind,
    entity_id, entity_fqn, column_name, value_json, source,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(assignment_id)},
    {sql_literal(definition_id)},
    {int(definition_version)},
    {sql_literal(entity_kind)},
    NULL,
    {sql_literal(entity_fqn)},
    {sql_literal(column_name)},
    {sql_literal(_json_text(value))},
    {sql_literal('manual')},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor_email)}
)"""
        )

    def list_custom_property_assignments(
        self,
        *,
        entity_fqn: str | None = None,
        column_name: str | None = None,
    ) -> pd.DataFrame:
        clauses: List[str] = ["(a.removed_at IS NULL)"]
        if entity_fqn:
            clauses.append(f"a.entity_fqn = {sql_literal(entity_fqn)}")
        if column_name is not None:
            clauses.append(f"COALESCE(a.column_name, '') = {sql_literal(column_name)}")
        where = f"WHERE {' AND '.join(clauses)}"
        return self.uc.query_df(
            f"""SELECT a.assignment_id, a.definition_id, a.definition_version,
    a.entity_kind, a.entity_fqn, a.column_name, a.value_json,
    a.created_at, a.created_by, a.updated_at, a.updated_by,
    d.property_key, d.display_name, d.data_type, d.is_multi
FROM {self._fq('custom_property_assignments')} a
LEFT JOIN {self._fq('custom_property_definitions')} d
    ON d.definition_id = a.definition_id
{where}
ORDER BY d.display_name ASC"""
        )

    # ------------------------------------------------------------------
    # Phase 8 — profile runs and metrics
    # ------------------------------------------------------------------
    def insert_profile_run(
        self,
        *,
        profile_run_id: str,
        entity_kind: str,
        entity_fqn: str,
        trigger: str,
        status: str,
        sample_strategy: str | None,
        sample_rows: int | None,
        created_by: str,
        notes: str | None = None,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('profile_runs')} (
    profile_run_id, entity_kind, entity_id, entity_fqn, trigger, status,
    sample_strategy, sample_rows, started_at, finished_at, error_detail,
    notes, created_at, created_by
) VALUES (
    {sql_literal(profile_run_id)},
    {sql_literal(entity_kind)},
    NULL,
    {sql_literal(entity_fqn)},
    {sql_literal(trigger)},
    {sql_literal(status)},
    {sql_literal(sample_strategy)},
    {'NULL' if sample_rows is None else int(sample_rows)},
    timestamp({sql_literal(ts)}),
    NULL,
    NULL,
    {sql_literal(notes)},
    timestamp({sql_literal(ts)}),
    {sql_literal(created_by)}
)"""
        )

    def finalize_profile_run(
        self,
        *,
        profile_run_id: str,
        status: str,
        error_detail: str | None = None,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""UPDATE {self._fq('profile_runs')}
SET status = {sql_literal(status)},
    finished_at = timestamp({sql_literal(ts)}),
    error_detail = {sql_literal(error_detail)}
WHERE profile_run_id = {sql_literal(profile_run_id)}"""
        )

    def insert_profile_table_metric(
        self,
        *,
        profile_run_id: str,
        entity_fqn: str,
        row_count: int | None,
        size_bytes: int | None,
        partition_count: int | None,
        distinct_keys: int | None,
        detail: dict | None,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('profile_table_metrics')} (
    metric_id, profile_run_id, entity_fqn, row_count, size_bytes,
    partition_count, distinct_keys, observed_at, detail_json
) VALUES (
    {sql_literal(uuid.uuid4().hex)},
    {sql_literal(profile_run_id)},
    {sql_literal(entity_fqn)},
    {'NULL' if row_count is None else int(row_count)},
    {'NULL' if size_bytes is None else int(size_bytes)},
    {'NULL' if partition_count is None else int(partition_count)},
    {'NULL' if distinct_keys is None else int(distinct_keys)},
    timestamp({sql_literal(ts)}),
    {sql_literal(_json_text(detail)) if detail is not None else 'NULL'}
)"""
        )

    def insert_profile_column_metric(
        self,
        *,
        profile_run_id: str,
        entity_fqn: str,
        column_name: str,
        data_type: str | None,
        null_count: int | None,
        null_fraction: float | None,
        distinct_count: int | None,
        distinct_fraction: float | None,
        min_value: str | None,
        max_value: str | None,
        mean_value: float | None,
        stddev_value: float | None,
        quantiles: list | None,
        top_values: list | None,
        detail: dict | None,
    ) -> None:
        def _num(val):
            return 'NULL' if val is None else str(float(val))
        def _int(val):
            return 'NULL' if val is None else str(int(val))
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('profile_column_metrics')} (
    metric_id, profile_run_id, entity_fqn, column_name, data_type,
    null_count, null_fraction, distinct_count, distinct_fraction,
    min_value, max_value, mean_value, stddev_value,
    quantiles_json, top_values_json, observed_at, detail_json
) VALUES (
    {sql_literal(uuid.uuid4().hex)},
    {sql_literal(profile_run_id)},
    {sql_literal(entity_fqn)},
    {sql_literal(column_name)},
    {sql_literal(data_type)},
    {_int(null_count)},
    {_num(null_fraction)},
    {_int(distinct_count)},
    {_num(distinct_fraction)},
    {sql_literal(min_value)},
    {sql_literal(max_value)},
    {_num(mean_value)},
    {_num(stddev_value)},
    {sql_literal(_json_text(quantiles)) if quantiles is not None else 'NULL'},
    {sql_literal(_json_text(top_values)) if top_values is not None else 'NULL'},
    timestamp({sql_literal(ts)}),
    {sql_literal(_json_text(detail)) if detail is not None else 'NULL'}
)"""
        )

    def latest_profile_run_for_entity(self, entity_fqn: str) -> dict | None:
        frame = self.uc.query_df(
            f"""SELECT profile_run_id, entity_kind, entity_fqn, trigger, status,
    sample_strategy, sample_rows, started_at, finished_at, error_detail,
    notes, created_by
FROM {self._fq('profile_runs')}
WHERE entity_fqn = {sql_literal(entity_fqn)}
ORDER BY started_at DESC, profile_run_id DESC
LIMIT 1"""
        )
        if frame is None or frame.empty:
            return None
        return frame.iloc[0].to_dict()

    def profile_table_metrics_for_run(self, profile_run_id: str) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT metric_id, profile_run_id, entity_fqn, row_count, size_bytes,
    partition_count, distinct_keys, observed_at, detail_json
FROM {self._fq('profile_table_metrics')}
WHERE profile_run_id = {sql_literal(profile_run_id)}
ORDER BY observed_at DESC"""
        )

    def profile_column_metrics_for_run(self, profile_run_id: str) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT metric_id, profile_run_id, entity_fqn, column_name, data_type,
    null_count, null_fraction, distinct_count, distinct_fraction,
    min_value, max_value, mean_value, stddev_value,
    quantiles_json, top_values_json, observed_at, detail_json
FROM {self._fq('profile_column_metrics')}
WHERE profile_run_id = {sql_literal(profile_run_id)}
ORDER BY column_name ASC"""
        )

    # ------------------------------------------------------------------
    # Phase 10 — quality core
    # ------------------------------------------------------------------
    def insert_quality_run(
        self,
        *,
        run_id: str,
        suite_id: str | None,
        trigger: str,
        status: str,
        row_budget: int | None,
        byte_budget: int | None,
        time_budget_ms: int | None,
        summary: dict | None,
        created_by: str,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('quality_runs')} (
    run_id, suite_id, trigger, status, started_at, finished_at,
    row_budget, byte_budget, time_budget_ms, error_detail, summary_json,
    created_at, created_by
) VALUES (
    {sql_literal(run_id)},
    {sql_literal(suite_id)},
    {sql_literal(trigger)},
    {sql_literal(status)},
    timestamp({sql_literal(ts)}),
    NULL,
    {'NULL' if row_budget is None else int(row_budget)},
    {'NULL' if byte_budget is None else int(byte_budget)},
    {'NULL' if time_budget_ms is None else int(time_budget_ms)},
    NULL,
    {sql_literal(_json_text(summary)) if summary else 'NULL'},
    timestamp({sql_literal(ts)}),
    {sql_literal(created_by)}
)"""
        )

    def insert_quality_run_result(
        self,
        *,
        result_id: str,
        run_id: str,
        case_id: str,
        entity_fqn: str | None,
        column_name: str | None,
        outcome: str,
        severity: str | None,
        metric_value: float | None,
        threshold_value: float | None,
        evidence: dict | None,
        statement_id: str | None,
        row_bytes_scanned: int | None,
        detail: str | None,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""INSERT INTO {self._fq('quality_run_results')} (
    result_id, run_id, case_id, entity_fqn, column_name, outcome, severity,
    metric_value, threshold_value, evidence_json, statement_id,
    row_bytes_scanned, executed_at, detail
) VALUES (
    {sql_literal(result_id)},
    {sql_literal(run_id)},
    {sql_literal(case_id)},
    {sql_literal(entity_fqn)},
    {sql_literal(column_name)},
    {sql_literal(outcome)},
    {sql_literal(severity)},
    {'NULL' if metric_value is None else str(float(metric_value))},
    {'NULL' if threshold_value is None else str(float(threshold_value))},
    {sql_literal(_json_text(evidence)) if evidence else 'NULL'},
    {sql_literal(statement_id)},
    {'NULL' if row_bytes_scanned is None else int(row_bytes_scanned)},
    timestamp({sql_literal(ts)}),
    {sql_literal(detail)}
)"""
        )

    def finalize_quality_run(
        self,
        *,
        run_id: str,
        status: str,
        summary: dict | None,
        error_detail: str | None = None,
    ) -> None:
        ts = _utc_now_ts()
        self.uc.execute(
            f"""UPDATE {self._fq('quality_runs')}
SET status = {sql_literal(status)},
    finished_at = timestamp({sql_literal(ts)}),
    error_detail = {sql_literal(error_detail)},
    summary_json = {sql_literal(_json_text(summary)) if summary else 'NULL'}
WHERE run_id = {sql_literal(run_id)}"""
        )

    def list_quality_runs(
        self,
        *,
        entity_fqn: str | None = None,
        suite_id: str | None = None,
        limit: int = 50,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if suite_id:
            clauses.append(f"r.suite_id = {sql_literal(suite_id)}")
        select_from = (
            f"SELECT r.run_id, r.suite_id, r.trigger, r.status, r.started_at, "
            f"r.finished_at, r.row_budget, r.summary_json FROM {self._fq('quality_runs')} r"
        )
        if entity_fqn:
            select_from += (
                f" WHERE EXISTS (SELECT 1 FROM {self._fq('quality_run_results')} rr "
                f"WHERE rr.run_id = r.run_id AND rr.entity_fqn = {sql_literal(entity_fqn)})"
            )
            if clauses:
                select_from += " AND " + " AND ".join(clauses)
        elif clauses:
            select_from += " WHERE " + " AND ".join(clauses)
        return self.uc.query_df(
            f"{select_from} ORDER BY r.started_at DESC, r.run_id DESC LIMIT {int(limit)}"
        )

    def list_quality_run_results(
        self,
        *,
        entity_fqn: str | None = None,
        run_id: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if run_id:
            clauses.append(f"run_id = {sql_literal(run_id)}")
        if entity_fqn:
            clauses.append(f"entity_fqn = {sql_literal(entity_fqn)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT result_id, run_id, case_id, entity_fqn, column_name,
    outcome, severity, metric_value, threshold_value, evidence_json,
    statement_id, row_bytes_scanned, executed_at, detail
FROM {self._fq('quality_run_results')} {where}
ORDER BY executed_at DESC, result_id ASC
LIMIT {int(limit)}"""
        )

    def list_quality_check_names(self, *, case_ids: Sequence[str]) -> pd.DataFrame:
        """case_id -> curated display name / test key, for findings payloads.

        Joins quality_test_cases to quality_test_definitions so browse
        surfaces can show the definition's human display_name instead of a
        raw case id. Bounded to 500 ids per call (the findings page cap)."""
        unique_ids = sorted(
            {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
        )[:500]
        if not unique_ids:
            return pd.DataFrame(columns=["case_id", "display_name", "test_key"])
        id_list = ", ".join(sql_literal(case_id) for case_id in unique_ids)
        return self.uc.query_df(
            f"""SELECT c.case_id, d.display_name, d.test_key
FROM {self._fq('quality_test_cases')} c
LEFT JOIN {self._fq('quality_test_definitions')} d
  ON d.definition_id = c.definition_id
WHERE c.case_id IN ({id_list})"""
        )

    # ------------------------------------------------------------------
    # Governance metrics snapshots (trend history)
    # ------------------------------------------------------------------
    def upsert_governance_metrics_snapshot(
        self,
        *,
        scope_key: str,
        snapshot_date: str,
        metrics: Mapping[str, Any],
        created_by: str = "axiom-metrics",
    ) -> None:
        """Record (or replace) the daily governance-posture snapshot for a scope.

        One row per (scope_key, snapshot_date) — Delta has no uniqueness
        constraint, so this deletes today's row before inserting. The
        command-center payload builder is the only writer and throttles
        to one write per scope per day.
        """
        numeric_columns = (
            "governed_assets",
            "certified_assets",
            "critical_assets",
            "certified_critical_assets",
            "metadata_coverage",
            "posture_score",
            "audit_readiness",
            "open_requests",
            "policy_exceptions",
            "quality_sla",
            "lineage_coverage",
            "cde_count",
        )

        def _num(key: str) -> str:
            value = metrics.get(key)
            if value is None:
                return "NULL"
            try:
                return repr(float(value)) if isinstance(value, float) else repr(int(value))
            except (TypeError, ValueError):
                return "NULL"

        ts = _utc_now_ts()
        table = self._fq("governance_metrics_snapshots")
        self.uc.execute(
            f"DELETE FROM {table} WHERE scope_key = {sql_literal(scope_key)} "
            f"AND snapshot_date = date({sql_literal(snapshot_date)})"
        )
        self.uc.execute(
            f"""INSERT INTO {table} (
    snapshot_id, scope_key, snapshot_date,
    {', '.join(numeric_columns)},
    created_at, created_by
) VALUES (
    {sql_literal(f"{scope_key}:{snapshot_date}")},
    {sql_literal(scope_key)},
    date({sql_literal(snapshot_date)}),
    {', '.join(_num(column) for column in numeric_columns)},
    timestamp({sql_literal(ts)}),
    {sql_literal(created_by)}
)"""
        )

    def list_governance_metrics_snapshots(
        self,
        *,
        scope_key: str,
        limit: int = 120,
    ) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT snapshot_date, governed_assets, certified_assets, critical_assets,
    certified_critical_assets, metadata_coverage, posture_score, audit_readiness,
    open_requests, policy_exceptions, quality_sla, lineage_coverage, cde_count
FROM {self._fq('governance_metrics_snapshots')}
WHERE scope_key = {sql_literal(scope_key)}
ORDER BY snapshot_date DESC
LIMIT {int(limit)}"""
        )

    def upsert_governance_category_snapshots(
        self,
        *,
        scope_key: str,
        snapshot_date: str,
        rows: Sequence[Mapping[str, Any]],
        created_by: str = "axiom-metrics",
    ) -> None:
        """Record (or replace) today's per-category governance snapshots (G9).

        One row per (scope_key, snapshot_date, category_kind, category_key).
        Delete-then-insert for the whole (scope, day) set — same idempotency as
        the aggregate snapshot. Rows carry: category_kind (domain|tier),
        category_key, category_label, asset_count, coverage, certification_pct,
        score. Absent values persist as NULL, never fabricated.
        """
        table = self._fq("governance_category_metrics_snapshots")
        self.uc.execute(
            f"DELETE FROM {table} WHERE scope_key = {sql_literal(scope_key)} "
            f"AND snapshot_date = date({sql_literal(snapshot_date)})"
        )
        materialized = [row for row in rows if _norm_str(row.get("category_key"))]
        if not materialized:
            return

        def _num(value: Any) -> str:
            if value is None:
                return "NULL"
            try:
                return repr(float(value)) if isinstance(value, float) else repr(int(value))
            except (TypeError, ValueError):
                return "NULL"

        ts = _utc_now_ts()
        values = []
        for row in materialized:
            kind = _norm_str(row.get("category_kind"))
            key = _norm_str(row.get("category_key"))
            label = _norm_str(row.get("category_label")) or key
            values.append(
                "("
                + ", ".join(
                    [
                        sql_literal(f"{scope_key}:{snapshot_date}:{kind}:{key}"),
                        sql_literal(scope_key),
                        f"date({sql_literal(snapshot_date)})",
                        sql_literal(kind),
                        sql_literal(key),
                        sql_literal(label),
                        _num(row.get("asset_count")),
                        _num(row.get("coverage")),
                        _num(row.get("certification_pct")),
                        _num(row.get("score")),
                        f"timestamp({sql_literal(ts)})",
                        sql_literal(created_by),
                    ]
                )
                + ")"
            )
        self.uc.execute(
            f"""INSERT INTO {table} (
    snapshot_id, scope_key, snapshot_date, category_kind, category_key,
    category_label, asset_count, coverage, certification_pct, score,
    created_at, created_by
) VALUES {', '.join(values)}"""
        )

    def list_governance_category_snapshots(
        self,
        *,
        scope_key: str,
        category_kind: str,
        limit: int = 400,
    ) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT snapshot_date, category_kind, category_key, category_label,
    asset_count, coverage, certification_pct, score
FROM {self._fq('governance_category_metrics_snapshots')}
WHERE scope_key = {sql_literal(scope_key)}
    AND category_kind = {sql_literal(category_kind)}
ORDER BY snapshot_date DESC
LIMIT {int(limit)}"""
        )

    # ------------------------------------------------------------------
    # Phase 11 — classifications / domains / data products / column groups
    # ------------------------------------------------------------------
    def list_classifications(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT c.classification_id, c.display_name, c.description, c.color,
    c.is_system, c.state, c.created_at, c.updated_at,
    (SELECT count(*) FROM {self._fq('classification_terms')} t
        WHERE t.classification_id = c.classification_id AND COALESCE(t.state, 'active') = 'active') AS term_count
FROM {self._fq('classifications')} c
WHERE COALESCE(c.state, 'active') = 'active'
ORDER BY c.display_name ASC"""
        )

    def list_classification_terms(self, classification_id: str) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT term_id, classification_id, parent_term_id, display_name,
    description, sensitivity_level, is_system, state, created_at, updated_at
FROM {self._fq('classification_terms')}
WHERE classification_id = {sql_literal(classification_id)}
  AND COALESCE(state, 'active') = 'active'
ORDER BY display_name ASC"""
        )

    def list_domains(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT domain_id, display_name, description, parent_domain_id,
    owner_entry_id, color, state, created_at, updated_at
FROM {self._fq('domains')}
WHERE COALESCE(state, 'active') = 'active'
ORDER BY display_name ASC"""
        )

    def list_data_products(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT dp.data_product_id, dp.display_name, dp.description, dp.domain_id,
    dp.owner_entry_id, dp.contact_email, dp.slo_description, dp.state,
    dp.created_at, dp.updated_at,
    (SELECT count(*) FROM {self._fq('data_product_members')} m
        WHERE m.data_product_id = dp.data_product_id) AS member_count
FROM {self._fq('data_products')} dp
WHERE dp.state IS NULL OR dp.state != 'retired'
ORDER BY dp.display_name ASC"""
        )

    def list_logical_column_groups(self) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT g.group_id, g.display_name, g.description, g.match_rule_json,
    g.confidence, g.last_reviewed_at, g.last_reviewed_by, g.state,
    (SELECT count(*) FROM {self._fq('logical_column_group_members')} m
        WHERE m.group_id = g.group_id) AS member_count
FROM {self._fq('logical_column_groups')} g
WHERE COALESCE(g.state, 'active') = 'active'
ORDER BY g.display_name ASC"""
        )

    def get_logical_column_group(self, group_id: str) -> pd.DataFrame:
        return self.uc.query_df(
            f"""SELECT g.group_id, g.display_name, g.description, g.match_rule_json,
    g.confidence, g.last_reviewed_at, g.last_reviewed_by, g.state,
    m.membership_id, m.entity_fqn, m.column_name, m.column_data_type,
    m.current_description, m.current_tags_json, m.current_glossary_term_id,
    m.match_confidence, m.last_seen_at
FROM {self._fq('logical_column_groups')} g
LEFT JOIN {self._fq('logical_column_group_members')} m
    ON m.group_id = g.group_id
WHERE g.group_id = {sql_literal(group_id)}
ORDER BY m.entity_fqn ASC, m.column_name ASC"""
        )

    # ------------------------------------------------------------------
    # Phase 13 — cross-entity audit browser
    # ------------------------------------------------------------------
    def list_audit_events(
        self,
        *,
        actor_email: str | None = None,
        entity_fqn: str | None = None,
        entity_kind: str | None = None,
        action: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if actor_email:
            clauses.append(f"actor_email = {sql_literal(actor_email)}")
        if entity_fqn:
            clauses.append(f"entity_fqn = {sql_literal(entity_fqn)}")
        if entity_kind:
            clauses.append(f"entity_type = {sql_literal(entity_kind)}")
        if action:
            clauses.append(f"action = {sql_literal(action)}")
        if since:
            clauses.append(f"created_at >= timestamp({sql_literal(since)})")
        if until:
            clauses.append(f"created_at <= timestamp({sql_literal(until)})")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT audit_id, entity_type, entity_id, entity_fqn, column_name,
    action, source, status, before_json, after_json, actor_email, actor_role,
    detail, created_at
FROM {self._fq('metadata_audit_log')} {where}
ORDER BY created_at DESC, audit_id DESC
LIMIT {int(limit)}"""
        )

    # ── A9.4 classification recommendations ─────────────────

    def upsert_classification_recommendation(
        self,
        record: Dict[str, Any],
        *,
        actor_email: str | None = None,
    ) -> str:
        """Insert or update a classification recommendation keyed by recommendation_id.

        The Delta-style upsert is done as a DELETE-then-INSERT to keep the SQL
        portable across workspace permissions (MERGE requires DELETE privs that
        aren't universally granted). The call is idempotent on recommendation_id.
        """
        rec_id = str(record.get("recommendation_id") or "").strip()
        if not rec_id:
            rec_id = uuid.uuid4().hex
        asset_fqn = str(record.get("asset_fqn") or "").strip()
        column_name = str(record.get("column_name") or "").strip()
        if not asset_fqn or not column_name:
            raise ValueError("asset_fqn and column_name are required.")
        ts = _utc_now_ts()
        actor = str(actor_email or record.get("created_by") or "system").strip() or "system"
        status = str(record.get("status") or "pending").strip().lower() or "pending"
        # Delete any existing row with this recommendation_id so the insert is
        # effectively an upsert. No-op when the row does not yet exist.
        try:
            self.uc.execute(
                f"DELETE FROM {self._fq('classification_recommendations')} "
                f"WHERE recommendation_id = {sql_literal(rec_id)}"
            )
        except Exception:
            # First-run races: the table may exist but the row may not; we
            # still want the INSERT below to land.
            pass
        sample_redacted = bool(record.get("sample_redacted", True))
        sample_values_json = record.get("sample_values_json")
        if sample_values_json is None:
            sample_values_json = ""
        self.uc.execute(
            f"""INSERT INTO {self._fq('classification_recommendations')} (
    recommendation_id, asset_fqn, column_name,
    suggested_sensitivity, suggested_tier, suggested_certification,
    evidence_json, sample_redacted, sample_values_json,
    status, remediation_suggestions_json,
    review_note, reviewed_by, reviewed_at,
    created_at, created_by, updated_at, updated_by
) VALUES (
    {sql_literal(rec_id)},
    {sql_literal(asset_fqn)},
    {sql_literal(column_name)},
    {sql_literal(_text_value(record.get("suggested_sensitivity")))},
    {sql_literal(_text_value(record.get("suggested_tier")))},
    {sql_literal(_text_value(record.get("suggested_certification")))},
    {sql_literal(record.get("evidence_json") or "[]")},
    {'TRUE' if sample_redacted else 'FALSE'},
    {sql_literal(str(sample_values_json))},
    {sql_literal(status)},
    {sql_literal(record.get("remediation_suggestions_json") or "[]")},
    {sql_literal(_text_value(record.get("review_note")))},
    {sql_literal(_text_value(record.get("reviewed_by")))},
    {'NULL' if not record.get("reviewed_at") else f"timestamp({sql_literal(str(record.get('reviewed_at')))})"},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor)},
    timestamp({sql_literal(ts)}),
    {sql_literal(actor)}
)"""
        )
        return rec_id

    def list_classification_recommendations(
        self,
        *,
        status: str | None = None,
        asset_fqn: str | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        clauses: List[str] = []
        if status:
            clauses.append(f"lower(status) = {sql_literal(status.strip().lower())}")
        if asset_fqn:
            clauses.append(f"asset_fqn = {sql_literal(asset_fqn)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.uc.query_df(
            f"""SELECT recommendation_id, asset_fqn, column_name,
    suggested_sensitivity, suggested_tier, suggested_certification,
    evidence_json, sample_redacted, sample_values_json,
    status, remediation_suggestions_json,
    review_note, reviewed_by, reviewed_at,
    created_at, created_by, updated_at, updated_by
FROM {self._fq('classification_recommendations')} {where}
ORDER BY created_at DESC, recommendation_id
LIMIT {int(limit)}"""
        )

    def get_classification_recommendation(
        self, recommendation_id: str
    ) -> Optional[Dict[str, Any]]:
        rec_id = str(recommendation_id or "").strip()
        if not rec_id:
            return None
        df = self.uc.query_df(
            f"""SELECT recommendation_id, asset_fqn, column_name,
    suggested_sensitivity, suggested_tier, suggested_certification,
    evidence_json, sample_redacted, sample_values_json,
    status, remediation_suggestions_json,
    review_note, reviewed_by, reviewed_at,
    created_at, created_by, updated_at, updated_by
FROM {self._fq('classification_recommendations')}
WHERE recommendation_id = {sql_literal(rec_id)} LIMIT 1"""
        )
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        return {col: row.get(col) for col in df.columns}

    def set_classification_recommendation_status(
        self,
        recommendation_id: str,
        *,
        status: str,
        reviewer: str,
        review_note: str | None = None,
    ) -> None:
        rec_id = str(recommendation_id or "").strip()
        if not rec_id:
            raise ValueError("recommendation_id is required.")
        ts = _utc_now_ts()
        normalized_status = str(status or "").strip().lower()
        self.uc.execute(
            f"""UPDATE {self._fq('classification_recommendations')} SET
    status = {sql_literal(normalized_status)},
    review_note = {sql_literal(_text_value(review_note))},
    reviewed_by = {sql_literal(reviewer)},
    reviewed_at = timestamp({sql_literal(ts)}),
    updated_at = timestamp({sql_literal(ts)}),
    updated_by = {sql_literal(reviewer)}
WHERE recommendation_id = {sql_literal(rec_id)}"""
        )
