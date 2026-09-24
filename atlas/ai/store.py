"""Store methods for the AI governance tables (DESIGN.md 3.3 and 4).

``AiStore`` wraps whichever governance store the caller holds (the Delta
``GovernanceStore`` or the Lakebase ``DualWriteGovernanceStore``) instead of
being a mixin on ``GovernanceStore``: registry and alias writes must go
through the wrapper so the Lakebase mirror stays consistent (DESIGN.md D2,
revised in Phase 1).

Fail-closed audit, stronger than "audit after write": every mutation first
writes its ``metadata_audit_log`` row and ``change_events`` row. If that
fails, the mutation never runs. If the mutation then fails, a second
audit/event pair with status ``failed`` records it. No mutation can land
without an audit record.

All SQL uses ``sql_literal`` / ``quote_ident`` via ``_lit`` and ``_fq``.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from atlas.ai.models import (
    ControlResult,
    Finding,
    IntakeRecord,
    Observation,
    canonical_json,
)
from atlas.util import error_text, sql_literal

BATCH_SIZE = 200
SYSTEM_ACTOR_ROLE = "system"

# Steward actions on a finding (DESIGN.md 5.4).
FINDING_ACTIONS = ("acknowledge", "assign", "resolve", "suppress", "reopen")


def _ts(value: Optional[datetime]) -> str:
    if value is None:
        return "NULL"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"timestamp({sql_literal(value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f'))})"


def _lit(value: Any) -> str:
    """One SQL literal for any Python value; JSON-encodes containers."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "NULL" if math.isnan(value) or math.isinf(value) else repr(value)
    if isinstance(value, datetime):
        return _ts(value)
    if isinstance(value, (dict, list, tuple)):
        return sql_literal(canonical_json(value))
    return sql_literal(str(value))


def _s(value: Any) -> str:
    """String literal typed for MERGE sources: an all-NULL column in a UNION
    ALL source would otherwise be Spark's void type and fail the insert."""
    return f"CAST({_lit(value)} AS STRING)"


def _t(value: Optional[datetime]) -> str:
    return "CAST(NULL AS TIMESTAMP)" if value is None else _ts(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_load(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _records(frame: Any, json_columns: Sequence[str] = ()) -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    rows = []
    for raw in frame.to_dict(orient="records"):
        row = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in raw.items()}
        for column in json_columns:
            if column in row:
                row[column] = _json_load(row[column], {} if not column.startswith("relationships") else [])
        rows.append(row)
    return rows


def relationship_id_for(relationship_kind: str, source_entity_id: str, target_entity_id: str) -> str:
    import hashlib

    return hashlib.sha256(f"{relationship_kind}|{source_entity_id}|{target_entity_id}".encode("utf-8")).hexdigest()[:32]


def _stable_evidence(evidence: Any) -> str:
    """Evidence minus its provenance block, whose run id and observed-at change
    every run: otherwise every re-run would emit an ai.finding.updated event
    for every unchanged finding."""
    body = dict(evidence) if isinstance(evidence, Mapping) else {}
    body.pop("provenance", None)
    return canonical_json(body)


def _chunks(items: Sequence[Any], size: int = BATCH_SIZE) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass(frozen=True)
class AuditEntry:
    event_type: str
    entity_kind: str
    entity_id: Optional[str]
    actor_email: str
    actor_role: str
    before: Any = None
    after: Any = None
    source: str = "system"
    request_id: Optional[str] = None
    detail: Optional[str] = None
    status: str = "success"
    entity_fqn: Optional[str] = None


class AiStore:
    def __init__(self, store: Any) -> None:
        self.store = store

    @property
    def uc(self) -> Any:
        return self.store.uc

    def _fq(self, table: str) -> str:
        return self.store._fq(table)

    # ------------------------------------------------------------------ audit
    def audit_batch(self, entries: Sequence[AuditEntry]) -> None:
        """Multi-row audit + change-event insert with the same columns as
        GovernanceStore.append_metadata_audit / append_change_event (audit
        rows are not mirrored to Lakebase, so a direct batch is equivalent).
        Raises on failure: callers run it before their mutation."""
        if not entries:
            return
        ts = _now()
        for chunk in _chunks(list(entries)):
            audit_rows = []
            event_rows = []
            for entry in chunk:
                audit_rows.append(
                    "("
                    + ", ".join(
                        [
                            _lit(uuid.uuid4().hex),
                            _lit(entry.entity_kind),
                            _lit(entry.entity_id),
                            _lit(entry.entity_fqn),
                            "NULL",
                            _lit(entry.event_type),
                            _lit(entry.source),
                            _lit(entry.status),
                            _lit(entry.before),
                            _lit(entry.after),
                            _lit(entry.request_id),
                            _lit(entry.actor_email),
                            _lit(entry.actor_role),
                            _lit(entry.detail),
                            _ts(ts),
                            _lit(entry.actor_email),
                            _ts(ts),
                            _lit(entry.actor_email),
                        ]
                    )
                    + ")"
                )
                event_rows.append(
                    "("
                    + ", ".join(
                        [
                            _lit(uuid.uuid4().hex),
                            _lit(entry.event_type),
                            _lit(entry.entity_kind),
                            _lit(entry.entity_id),
                            _lit(entry.entity_fqn),
                            "NULL",
                            _lit(entry.actor_email),
                            _lit(entry.actor_role),
                            _lit(entry.before),
                            _lit(entry.after),
                            _lit(entry.detail),
                            _lit(entry.source),
                            _lit("emitted" if entry.status == "success" else "failed"),
                            _lit(entry.request_id),
                            _ts(ts),
                            _ts(ts),
                        ]
                    )
                    + ")"
                )
            self.uc.execute(
                f"""INSERT INTO {self._fq("metadata_audit_log")} (
    audit_id, entity_type, entity_id, entity_fqn, column_name,
    action, source, status, before_json, after_json, request_id,
    actor_email, actor_role, detail,
    created_at, created_by, updated_at, updated_by
) VALUES {", ".join(audit_rows)}"""
            )
            self.uc.execute(
                f"""INSERT INTO {self._fq("change_events")} (
    event_id, event_type, entity_kind, entity_id, entity_fqn, column_name,
    actor_email, actor_role, before_json, after_json, detail, source, status,
    request_id, occurred_at, recorded_at
) VALUES {", ".join(event_rows)}"""
            )

    def audited(self, entries: Sequence[AuditEntry], mutation: Callable[[], Any]) -> Any:
        """Audit first (fail closed), then mutate; record a failed mutation."""
        self.audit_batch(entries)
        try:
            return mutation()
        except Exception as exc:
            failed = [
                AuditEntry(**{**entry.__dict__, "status": "failed", "detail": error_text(exc)[:500]})
                for entry in entries[:BATCH_SIZE]
            ]
            try:
                self.audit_batch(failed)
            except Exception:  # noqa: BLE001 - the original error is what matters
                pass
            raise

    # ----------------------------------------------------------- observations
    def append_observations(
        self, observations: Sequence[Observation], *, run_id: str, actor_email: str, actor_role: str = SYSTEM_ACTOR_ROLE
    ) -> int:
        """Append-only (collectors are the only writer). One audit/event per
        batch: per-row events would be one event per observed object per run."""
        if not observations:
            return 0
        recorded = _now()
        entry = AuditEntry(
            event_type="ai.observation.appended",
            entity_kind="ai_observation_batch",
            entity_id=run_id,
            actor_email=actor_email,
            actor_role=actor_role,
            after={"count": len(observations), "byKind": dict(Counter(o.entity_kind for o in observations))},
        )

        def _insert() -> int:
            for chunk in _chunks(list(observations)):
                values = ", ".join(
                    "("
                    + ", ".join(
                        [
                            _lit(uuid.uuid4().hex),
                            _lit(o.run_id),
                            _lit(o.source_system),
                            _lit(o.collector),
                            _lit(o.collector_version),
                            _lit(o.entity_kind),
                            _lit(o.source_entity_id),
                            _lit(o.parent_source_entity_id),
                            _lit(o.display_name),
                            _lit(o.platform),
                            _lit(o.provider),
                            _lit(o.model_family),
                            _lit(o.owner),
                            _lit(o.tags or {}),
                            _lit(o.config or {}),
                            _lit(o.relationships or []),
                            _lit(o.content_hash),
                            _lit(o.probe_state),
                            _lit(o.provenance_class),
                            _lit(o.sample_run_id),
                            _ts(o.observed_at),
                            _ts(recorded),
                        ]
                    )
                    + ")"
                    for o in chunk
                )
                self.uc.execute(
                    f"""INSERT INTO {self._fq("ai_asset_observations")} (
    observation_id, run_id, source_system, collector, collector_version,
    entity_kind, source_entity_id, parent_source_entity_id, display_name,
    platform, provider, model_family, owner, tags_json, config_json,
    relationships_json, content_hash, probe_state, provenance_class,
    sample_run_id, observed_at, recorded_at
) VALUES {values}"""
                )
            return len(observations)

        return self.audited([entry], _insert)

    _OBS_COLUMNS = """observation_id, run_id, source_system, collector, collector_version,
       entity_kind, source_entity_id, parent_source_entity_id, display_name,
       platform, provider, model_family, owner, tags_json, config_json,
       relationships_json, content_hash, probe_state, provenance_class,
       sample_run_id, observed_at, recorded_at"""

    def observations_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        frame = self.uc.query_df(
            f"""SELECT {self._OBS_COLUMNS}
FROM {self._fq("ai_asset_observations")}
WHERE run_id = {sql_literal(run_id)}"""
        )
        return _records(frame, ("tags_json", "config_json", "relationships_json"))

    def latest_observations(self, source_system: Optional[str] = None) -> List[Dict[str, Any]]:
        """Latest row per (source_system, entity_kind, source_entity_id)."""
        where = f"WHERE source_system = {sql_literal(source_system)}" if source_system else ""
        frame = self.uc.query_df(
            f"""SELECT {self._OBS_COLUMNS} FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY source_system, entity_kind, source_entity_id
    ORDER BY observed_at DESC, recorded_at DESC
  ) AS rn
  FROM {self._fq("ai_asset_observations")}
  {where}
) WHERE rn = 1"""
        )
        return _records(frame, ("tags_json", "config_json", "relationships_json"))

    # ----------------------------------------------------------------- intake
    _INTAKE_COLUMNS = """intake_id, title, state, owner_email, business_unit, risk_tier,
       platform, provider, model_family, intended_use, approved_at,
       review_due_at, source_system, source_record_id, ingest_source,
       ingest_run_id, attributes_json, content_hash, provenance_class,
       sample_run_id, created_at, created_by, updated_at, updated_by"""

    def list_intake_records(self) -> List[Dict[str, Any]]:
        frame = self.uc.query_df(
            f"SELECT {self._INTAKE_COLUMNS} FROM {self._fq('intake_records')} ORDER BY intake_id"
        )
        return _records(frame, ("attributes_json",))

    def _intake_hashes(self, intake_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        if not intake_ids:
            return {}
        found: Dict[str, Dict[str, Any]] = {}
        for chunk in _chunks(list(intake_ids)):
            frame = self.uc.query_df(
                f"""SELECT {self._INTAKE_COLUMNS} FROM {self._fq('intake_records')}
WHERE intake_id IN ({", ".join(_lit(i) for i in chunk)})"""
            )
            for row in _records(frame, ("attributes_json",)):
                found[str(row["intake_id"])] = row
        return found

    def upsert_intake_records(
        self,
        records: Sequence[IntakeRecord],
        *,
        actor_email: str,
        actor_role: str,
        request_id: Optional[str] = None,
        source: str = "import",
    ) -> Dict[str, int]:
        """MERGE intake rows + append history, one ai.intake.ingested audit
        event per row, all audited before any write."""
        if not records:
            return {"created": 0, "updated": 0, "unchanged": 0}
        existing = self._intake_hashes([r.intake_id for r in records])
        now = _now()
        kinds: Dict[str, str] = {}
        entries: List[AuditEntry] = []
        for record in records:
            prior = existing.get(record.intake_id)
            if prior is None:
                kind = "created"
            elif prior.get("content_hash") == record.content_hash:
                kind = "unchanged"
            else:
                kind = "updated"
            kinds[record.intake_id] = kind
            entries.append(
                AuditEntry(
                    event_type="ai.intake.ingested",
                    entity_kind="intake_record",
                    entity_id=record.intake_id,
                    actor_email=actor_email,
                    actor_role=actor_role,
                    before=None if prior is None else {k: prior.get(k) for k in ("title", "state", "owner_email", "risk_tier", "provider")},
                    after={**record.hash_fields(), "changeKind": kind, "ingestSource": record.ingest_source},
                    source=source,
                    request_id=request_id,
                )
            )

        def _write() -> Dict[str, int]:
            for chunk in _chunks(list(records)):
                source_rows = " UNION ALL ".join(
                    "SELECT "
                    + ", ".join(
                        [
                            f"{_s(r.intake_id)} AS intake_id",
                            f"{_s(r.title)} AS title",
                            f"{_s(r.state)} AS state",
                            f"{_s(r.owner_email)} AS owner_email",
                            f"{_s(r.business_unit)} AS business_unit",
                            f"{_s(r.risk_tier)} AS risk_tier",
                            f"{_s(r.platform)} AS platform",
                            f"{_s(r.provider)} AS provider",
                            f"{_s(r.model_family)} AS model_family",
                            f"{_s(r.intended_use)} AS intended_use",
                            f"{_t(r.approved_at)} AS approved_at",
                            f"{_t(r.review_due_at)} AS review_due_at",
                            f"{_s(r.source_system)} AS source_system",
                            f"{_s(r.source_record_id)} AS source_record_id",
                            f"{_s(r.ingest_source)} AS ingest_source",
                            f"{_s(r.ingest_run_id)} AS ingest_run_id",
                            f"{_s(r.attributes or {})} AS attributes_json",
                            f"{_s(r.content_hash)} AS content_hash",
                            f"{_s(r.provenance_class)} AS provenance_class",
                            f"{_s(r.sample_run_id)} AS sample_run_id",
                            f"{_ts(now)} AS created_at",
                            f"{_s(actor_email)} AS created_by",
                            f"{_ts(now)} AS updated_at",
                            f"{_s(actor_email)} AS updated_by",
                        ]
                    )
                    for r in chunk
                )
                self.uc.execute(
                    f"""MERGE INTO {self._fq("intake_records")} t
USING ({source_rows}) s
ON t.intake_id = s.intake_id
WHEN MATCHED AND t.content_hash <> s.content_hash THEN UPDATE SET
    title=s.title, state=s.state, owner_email=s.owner_email,
    business_unit=s.business_unit, risk_tier=s.risk_tier, platform=s.platform,
    provider=s.provider, model_family=s.model_family, intended_use=s.intended_use,
    approved_at=s.approved_at, review_due_at=s.review_due_at,
    source_system=s.source_system, source_record_id=s.source_record_id,
    ingest_source=s.ingest_source, ingest_run_id=s.ingest_run_id,
    attributes_json=s.attributes_json, content_hash=s.content_hash,
    provenance_class=s.provenance_class, sample_run_id=s.sample_run_id,
    updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT *"""
                )
                history = ", ".join(
                    "("
                    + ", ".join(
                        [
                            _lit(uuid.uuid4().hex),
                            _lit(r.intake_id),
                            _lit(kinds[r.intake_id]),
                            _lit(None if existing.get(r.intake_id) is None else {k: existing[r.intake_id].get(k) for k in ("title", "state", "owner_email", "risk_tier", "provider", "content_hash")}),
                            _lit({**r.hash_fields(), "content_hash": r.content_hash}),
                            _lit(r.ingest_source),
                            _lit(r.ingest_run_id),
                            _ts(now),
                            _lit(actor_email),
                        ]
                    )
                    + ")"
                    for r in chunk
                )
                self.uc.execute(
                    f"""INSERT INTO {self._fq("intake_records_history")} (
    history_id, intake_id, change_kind, before_json, after_json,
    ingest_source, ingest_run_id, recorded_at, recorded_by
) VALUES {history}"""
                )
            counts = Counter(kinds.values())
            return {"created": counts["created"], "updated": counts["updated"], "unchanged": counts["unchanged"]}

        return self.audited(entries, _write)

    # ------------------------------------------------------------------- runs
    def start_reconciliation_run(
        self, *, run_id: str, triggered_by: str, job_run_id: Optional[str] = None, rule_set_version: str = ""
    ) -> None:
        entry = AuditEntry(
            event_type="ai.run.started",
            entity_kind="reconciliation_run",
            entity_id=run_id,
            actor_email=triggered_by,
            actor_role=SYSTEM_ACTOR_ROLE,
            after={"runId": run_id, "jobRunId": job_run_id, "status": "collecting"},
        )
        self.audited(
            [entry],
            lambda: self.uc.execute(
                f"""INSERT INTO {self._fq("reconciliation_runs")} (
    run_id, job_run_id, status, rule_set_version, sources_json, counts_json,
    failure_reason, triggered_by, started_at, finished_at
) VALUES ({_lit(run_id)}, {_lit(job_run_id)}, 'collecting', {_lit(rule_set_version)},
  NULL, NULL, NULL, {_lit(triggered_by)}, {_ts(_now())}, NULL)"""
            ),
        )

    def update_reconciliation_run(
        self,
        *,
        run_id: str,
        actor_email: str,
        status: Optional[str] = None,
        sources: Optional[Mapping[str, Any]] = None,
        counts: Optional[Mapping[str, Any]] = None,
        failure_reason: Optional[str] = None,
        finished: bool = False,
    ) -> None:
        sets = []
        if status:
            sets.append(f"status = {_lit(status)}")
        if sources is not None:
            sets.append(f"sources_json = {_lit(dict(sources))}")
        if counts is not None:
            sets.append(f"counts_json = {_lit(dict(counts))}")
        if failure_reason is not None:
            sets.append(f"failure_reason = {_lit(failure_reason[:1000])}")
        if finished:
            sets.append(f"finished_at = {_ts(_now())}")
        if not sets:
            return
        entry = AuditEntry(
            event_type="ai.run.finished" if finished else "ai.run.updated",
            entity_kind="reconciliation_run",
            entity_id=run_id,
            actor_email=actor_email,
            actor_role=SYSTEM_ACTOR_ROLE,
            after={"status": status, "counts": dict(counts) if counts else None, "failureReason": failure_reason},
        )
        self.audited(
            [entry],
            lambda: self.uc.execute(
                f"UPDATE {self._fq('reconciliation_runs')} SET {', '.join(sets)} WHERE run_id = {_lit(run_id)}"
            ),
        )

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        frame = self.uc.query_df(
            f"""SELECT run_id, job_run_id, status, rule_set_version, sources_json, counts_json,
       failure_reason, triggered_by, started_at, finished_at
FROM {self._fq("reconciliation_runs")}
ORDER BY started_at DESC
LIMIT {max(1, min(int(limit), 200))}"""
        )
        return _records(frame, ("sources_json", "counts_json"))

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        frame = self.uc.query_df(
            f"""SELECT run_id, job_run_id, status, rule_set_version, sources_json, counts_json,
       failure_reason, triggered_by, started_at, finished_at
FROM {self._fq("reconciliation_runs")}
WHERE run_id = {_lit(run_id)}
LIMIT 1"""
        )
        rows = _records(frame, ("sources_json", "counts_json"))
        return rows[0] if rows else None

    def latest_succeeded_run(self) -> Optional[Dict[str, Any]]:
        frame = self.uc.query_df(
            f"""SELECT run_id, job_run_id, status, rule_set_version, sources_json, counts_json,
       failure_reason, triggered_by, started_at, finished_at
FROM {self._fq("reconciliation_runs")}
WHERE status = 'succeeded'
ORDER BY finished_at DESC
LIMIT 1"""
        )
        rows = _records(frame, ("sources_json", "counts_json"))
        return rows[0] if rows else None

    # --------------------------------------------------------------- findings
    _FINDING_COLUMNS = """finding_id, finding_type, rule_id, severity, state, entity_id, entity_kind,
       intake_id, match_rule, match_score, evidence_json, first_seen_run_id,
       last_run_id, first_seen_at, last_seen_at, assignee_email, task_id,
       resolution_note, suppression_reason, resolved_by, resolved_at,
       state_changed_by, state_changed_at, provenance_class, sample_run_id"""

    def findings_by_id(self, finding_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}
        for chunk in _chunks(list(finding_ids)):
            frame = self.uc.query_df(
                f"""SELECT {self._FINDING_COLUMNS} FROM {self._fq("reconciliation_findings")}
WHERE finding_id IN ({", ".join(_lit(i) for i in chunk)})"""
            )
            for row in _records(frame, ("evidence_json",)):
                found[str(row["finding_id"])] = row
        return found

    def active_findings(self) -> List[Dict[str, Any]]:
        """Open and acknowledged findings: the set reconciliation may auto-resolve."""
        frame = self.uc.query_df(
            f"""SELECT {self._FINDING_COLUMNS} FROM {self._fq("reconciliation_findings")}
WHERE state IN ('open', 'acknowledged')"""
        )
        return _records(frame, ("evidence_json",))

    def upsert_findings(
        self, findings: Sequence[Finding], *, run_id: str, actor_email: str, observed_at: Optional[datetime] = None
    ) -> Dict[str, int]:
        """Job-side MERGE on finding_id (DESIGN.md 5.4).

        Updates only derived fields (severity, evidence, match, last_seen).
        Steward fields and suppressed/acknowledged states are never
        overwritten; a resolved finding whose condition returns reopens.
        """
        if not findings:
            return {"opened": 0, "reopened": 0, "updated": 0, "unchanged": 0}
        now = observed_at or _now()
        existing = self.findings_by_id([f.finding_id for f in findings])
        entries: List[AuditEntry] = []
        counts: Counter = Counter()
        for finding in findings:
            prior = existing.get(finding.finding_id)
            after = {
                "findingType": finding.finding_type,
                "severity": finding.severity,
                "entityId": finding.entity_id,
                "intakeId": finding.intake_id,
                "matchRule": finding.match_rule,
                "matchScore": finding.match_score,
                "runId": run_id,
            }
            if prior is None:
                counts["opened"] += 1
                event = "ai.finding.opened"
            elif prior.get("state") == "resolved" and prior.get("resolved_by") == "system":
                # Only system-resolved findings reopen when their condition
                # returns. A steward resolution stands; "accept as-is" is what
                # suppress is for, and suppression is never overridden.
                counts["reopened"] += 1
                event = "ai.finding.opened"
            elif prior.get("severity") != finding.severity or _stable_evidence(prior.get("evidence_json")) != _stable_evidence(finding.evidence):
                counts["updated"] += 1
                event = "ai.finding.updated"
            else:
                counts["unchanged"] += 1
                continue  # last_seen advances without an event: no information changed
            entries.append(
                AuditEntry(
                    event_type=event,
                    entity_kind="ai_finding",
                    entity_id=finding.finding_id,
                    actor_email=actor_email,
                    actor_role=SYSTEM_ACTOR_ROLE,
                    before=None if prior is None else {"state": prior.get("state"), "severity": prior.get("severity")},
                    after=after,
                )
            )

        # Every MERGE advances last_seen_at even for unchanged findings, which
        # is still a mutation: one batch-level entry keeps it audited.
        entries.insert(
            0,
            AuditEntry(
                event_type="ai.findings.merged",
                entity_kind="ai_findings",
                entity_id=run_id,
                actor_email=actor_email,
                actor_role=SYSTEM_ACTOR_ROLE,
                after={"count": len(findings), **dict(counts)},
            ),
        )

        def _merge() -> Dict[str, int]:
            for chunk in _chunks(list(findings)):
                source_rows = " UNION ALL ".join(
                    "SELECT "
                    + ", ".join(
                        [
                            f"{_s(f.finding_id)} AS finding_id",
                            f"{_s(f.finding_type)} AS finding_type",
                            f"{_s(f.rule_id)} AS rule_id",
                            f"{_s(f.severity)} AS severity",
                            "'open' AS state",
                            f"{_s(f.entity_id)} AS entity_id",
                            f"{_s(f.entity_kind)} AS entity_kind",
                            f"{_s(f.intake_id)} AS intake_id",
                            f"{_s(f.match_rule)} AS match_rule",
                            f"CAST({_lit(f.match_score)} AS DOUBLE) AS match_score",
                            f"{_s(f.evidence)} AS evidence_json",
                            f"{_s(run_id)} AS first_seen_run_id",
                            f"{_s(run_id)} AS last_run_id",
                            f"{_ts(now)} AS first_seen_at",
                            f"{_ts(now)} AS last_seen_at",
                            "CAST(NULL AS STRING) AS assignee_email",
                            "CAST(NULL AS STRING) AS task_id",
                            "CAST(NULL AS STRING) AS resolution_note",
                            "CAST(NULL AS STRING) AS suppression_reason",
                            "CAST(NULL AS STRING) AS resolved_by",
                            "CAST(NULL AS TIMESTAMP) AS resolved_at",
                            f"{_s(actor_email)} AS state_changed_by",
                            f"{_ts(now)} AS state_changed_at",
                            f"{_s(f.provenance_class)} AS provenance_class",
                            f"{_s(f.sample_run_id)} AS sample_run_id",
                        ]
                    )
                    for f in chunk
                )
                self.uc.execute(
                    f"""MERGE INTO {self._fq("reconciliation_findings")} t
USING ({source_rows}) s
ON t.finding_id = s.finding_id
WHEN MATCHED AND t.state = 'resolved' AND t.resolved_by = 'system' THEN UPDATE SET
    state = 'open', severity = s.severity, evidence_json = s.evidence_json,
    match_rule = s.match_rule, match_score = s.match_score,
    last_run_id = s.last_run_id, last_seen_at = s.last_seen_at,
    resolved_by = NULL, resolved_at = NULL,
    state_changed_by = s.state_changed_by, state_changed_at = s.state_changed_at
WHEN MATCHED THEN UPDATE SET
    severity = s.severity, evidence_json = s.evidence_json,
    match_rule = s.match_rule, match_score = s.match_score,
    last_run_id = s.last_run_id, last_seen_at = s.last_seen_at
WHEN NOT MATCHED THEN INSERT *"""
                )
            return dict(counts)

        return self.audited(entries, _merge)

    def auto_resolve_findings(self, finding_ids: Sequence[str], *, run_id: str, actor_email: str) -> int:
        """Resolve conditions that no longer hold. Suppressed findings are
        excluded by the WHERE clause, so they stay suppressed."""
        if not finding_ids:
            return 0
        entries = [
            AuditEntry(
                event_type="ai.finding.resolved",
                entity_kind="ai_finding",
                entity_id=finding_id,
                actor_email=actor_email,
                actor_role=SYSTEM_ACTOR_ROLE,
                after={"state": "resolved", "resolvedBy": "system", "runId": run_id},
                detail="condition no longer holds",
            )
            for finding_id in finding_ids
        ]
        now = _now()

        def _resolve() -> int:
            for chunk in _chunks(list(finding_ids)):
                self.uc.execute(
                    f"""UPDATE {self._fq("reconciliation_findings")}
SET state = 'resolved', resolved_by = 'system', resolved_at = {_ts(now)},
    last_run_id = {_lit(run_id)}, state_changed_by = {_lit(actor_email)}, state_changed_at = {_ts(now)}
WHERE finding_id IN ({", ".join(_lit(i) for i in chunk)})
  AND state IN ('open', 'acknowledged')"""
                )
            return len(finding_ids)

        return self.audited(entries, _resolve)

    def list_findings(
        self,
        *,
        states: Sequence[str] = (),
        finding_types: Sequence[str] = (),
        severities: Sequence[str] = (),
        entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses = []
        if states:
            clauses.append(f"state IN ({', '.join(_lit(s) for s in states)})")
        if finding_types:
            clauses.append(f"finding_type IN ({', '.join(_lit(t) for t in finding_types)})")
        if severities:
            clauses.append(f"severity IN ({', '.join(_lit(s) for s in severities)})")
        if entity_id:
            clauses.append(f"entity_id = {_lit(entity_id)}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.uc.query_df(
            f"""SELECT {self._FINDING_COLUMNS} FROM {self._fq("reconciliation_findings")}
{where}
ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
         last_seen_at DESC, finding_id
LIMIT {max(1, min(int(limit), 500))} OFFSET {max(0, int(offset))}"""
        )
        return _records(frame, ("evidence_json",))

    def finding_counts(self) -> List[Dict[str, Any]]:
        """Counts by (finding_type, severity, state) across all findings."""
        frame = self.uc.query_df(
            f"""SELECT finding_type, severity, state, COUNT(*) AS n
FROM {self._fq("reconciliation_findings")}
GROUP BY finding_type, severity, state"""
        )
        return _records(frame)

    def open_findings_by_entity(self) -> Dict[str, int]:
        frame = self.uc.query_df(
            f"""SELECT entity_id, COUNT(*) AS n FROM {self._fq("reconciliation_findings")}
WHERE state IN ('open', 'acknowledged') AND entity_id IS NOT NULL
GROUP BY entity_id"""
        )
        return {str(r["entity_id"]): int(r["n"]) for r in _records(frame)}

    def count_findings(self, *, states: Sequence[str] = (), finding_types: Sequence[str] = (), severities: Sequence[str] = ()) -> int:
        clauses = []
        if states:
            clauses.append(f"state IN ({', '.join(_lit(s) for s in states)})")
        if finding_types:
            clauses.append(f"finding_type IN ({', '.join(_lit(t) for t in finding_types)})")
        if severities:
            clauses.append(f"severity IN ({', '.join(_lit(s) for s in severities)})")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        frame = self.uc.query_df(f"SELECT COUNT(*) AS n FROM {self._fq('reconciliation_findings')} {where}")
        rows = _records(frame)
        return int(rows[0]["n"]) if rows else 0

    def ai_registry_rows(self) -> Dict[str, Dict[str, Any]]:
        frame = self.uc.query_df(
            f"""SELECT entity_id, entity_kind, reconciliation_state, reconciliation_confidence, observed_at, updated_at
FROM {self._fq("entity_registry")}
WHERE entity_kind IN ('ai_model', 'ai_model_version', 'serving_endpoint', 'external_model', 'agent', 'mcp_server', 'uc_function_tool')"""
        )
        return {str(r["entity_id"]): r for r in _records(frame)}

    def list_entity_events(self, entity_ids: Sequence[str], limit: int = 50) -> List[Dict[str, Any]]:
        if not entity_ids:
            return []
        frame = self.uc.query_df(
            f"""SELECT event_id, event_type, entity_kind, entity_id, actor_email, actor_role,
       before_json, after_json, detail, source, status, request_id, occurred_at
FROM {self._fq("change_events")}
WHERE entity_id IN ({", ".join(_lit(i) for i in entity_ids)})
ORDER BY occurred_at DESC, event_id DESC
LIMIT {max(1, min(int(limit), 200))}"""
        )
        return _records(frame, ("before_json", "after_json"))

    def update_finding_state(
        self,
        *,
        finding_id: str,
        action: str,
        actor_email: str,
        actor_role: str,
        request_id: Optional[str] = None,
        assignee_email: Optional[str] = None,
        note: Optional[str] = None,
        reason: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Steward action (app). Validates required inputs, audits, then updates."""
        if action not in FINDING_ACTIONS:
            raise ValueError(f"Unsupported action {action!r}.")
        prior = self.findings_by_id([finding_id]).get(finding_id)
        if prior is None:
            raise LookupError("Finding not found.")
        now = _now()
        sets = [f"state_changed_by = {_lit(actor_email)}", f"state_changed_at = {_ts(now)}"]
        new_state = prior.get("state")
        if action == "acknowledge":
            new_state = "acknowledged"
        elif action == "assign":
            if not assignee_email:
                raise ValueError("assignee_email is required to assign.")
            sets.append(f"assignee_email = {_lit(assignee_email)}")
            if task_id:
                sets.append(f"task_id = {_lit(task_id)}")
        elif action == "resolve":
            if not (note or "").strip():
                raise ValueError("A resolution note is required.")
            new_state = "resolved"
            sets += [f"resolution_note = {_lit(note)}", f"resolved_by = {_lit(actor_email)}", f"resolved_at = {_ts(now)}"]
        elif action == "suppress":
            if not (reason or "").strip():
                raise ValueError("A suppression reason is required.")
            new_state = "suppressed"
            sets.append(f"suppression_reason = {_lit(reason)}")
        elif action == "reopen":
            new_state = "open"
            sets += ["resolved_by = NULL", "resolved_at = NULL", "suppression_reason = NULL"]
        sets.append(f"state = {_lit(new_state)}")
        before = {k: prior.get(k) for k in ("state", "assignee_email", "resolution_note", "suppression_reason")}
        after = {
            "state": new_state,
            "assignee_email": assignee_email if action == "assign" else prior.get("assignee_email"),
            "resolution_note": note if action == "resolve" else prior.get("resolution_note"),
            "suppression_reason": reason if action == "suppress" else prior.get("suppression_reason"),
            "action": action,
        }
        entry = AuditEntry(
            event_type="ai.finding.resolved" if new_state == "resolved" else "ai.finding.updated",
            entity_kind="ai_finding",
            entity_id=finding_id,
            actor_email=actor_email,
            actor_role=actor_role,
            before=before,
            after=after,
            source="api",
            request_id=request_id,
        )
        self.audited(
            [entry],
            lambda: self.uc.execute(
                f"UPDATE {self._fq('reconciliation_findings')} SET {', '.join(sets)} WHERE finding_id = {_lit(finding_id)}"
            ),
        )
        return {**prior, **{k: v for k, v in after.items() if k != "action"}}

    # ----------------------------------------------------------- registry/rel
    def upsert_ai_registry(
        self,
        *,
        entity_id: str,
        entity_kind: str,
        source_system: str,
        source_entity_id: str,
        reconciliation_state: str,
        confidence: Optional[float],
        observed_at: Optional[datetime],
        actor_email: str,
        prior_state: Optional[str] = None,
        entity_fqn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Registry rows go through the wrapped store so the Lakebase mirror
        runs; ai.registry.state_changed is emitted (first) only when the
        reconciliation state actually changes."""
        entries = []
        if prior_state != reconciliation_state:
            entries.append(
                AuditEntry(
                    event_type="ai.registry.state_changed",
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    actor_email=actor_email,
                    actor_role=SYSTEM_ACTOR_ROLE,
                    before={"reconciliationState": prior_state},
                    after={"reconciliationState": reconciliation_state, "confidence": confidence},
                    entity_fqn=entity_fqn,
                )
            )
        observed = observed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if observed_at else None

        def _upsert() -> Dict[str, Any]:
            return self.store.upsert_entity_registry(
                entity_id=entity_id,
                entity_kind=entity_kind,
                entity_fqn=entity_fqn,
                source_system=source_system,
                source_entity_id=source_entity_id,
                reconciliation_state=reconciliation_state,
                reconciliation_confidence=confidence,
                observed_at=observed,
                updated_by=actor_email,
                actor_role=SYSTEM_ACTOR_ROLE,
            )

        return self.audited(entries, _upsert) if entries else _upsert()

    def ai_registry_states(self) -> Dict[str, str]:
        frame = self.uc.query_df(
            f"""SELECT entity_id, reconciliation_state FROM {self._fq("entity_registry")}
WHERE entity_kind IN ('ai_model', 'ai_model_version', 'serving_endpoint', 'external_model', 'agent', 'mcp_server', 'uc_function_tool')"""
        )
        return {str(r["entity_id"]): str(r.get("reconciliation_state") or "") for r in _records(frame)}

    def upsert_relationship(
        self,
        *,
        relationship_kind: str,
        source_entity_id: str,
        source_entity_kind: str,
        target_entity_id: str,
        target_entity_kind: str,
        authority_source: str,
        evidence: Mapping[str, Any],
        actor_email: str,
        actor_role: str = SYSTEM_ACTOR_ROLE,
        request_id: Optional[str] = None,
        source: str = "system",
    ) -> str:
        """Deterministic relationship_id; an existing override is never
        downgraded to a derived authority by the job."""
        relationship_id = relationship_id_for(relationship_kind, source_entity_id, target_entity_id)
        now = _now()
        entry = AuditEntry(
            event_type="ai.registry.relationship_upserted",
            entity_kind="entity_relationship",
            entity_id=relationship_id,
            actor_email=actor_email,
            actor_role=actor_role,
            after={
                "kind": relationship_kind,
                "source": source_entity_id,
                "target": target_entity_id,
                "authority": authority_source,
            },
            source=source,
            request_id=request_id,
        )
        self.audited(
            [entry],
            lambda: self.uc.execute(
                f"""MERGE INTO {self._fq("entity_relationships")} t
USING (SELECT {_s(relationship_id)} AS relationship_id, {_s(relationship_kind)} AS relationship_kind,
              {_s(source_entity_id)} AS source_entity_id, {_s(source_entity_kind)} AS source_entity_kind,
              {_s(target_entity_id)} AS target_entity_id, {_s(target_entity_kind)} AS target_entity_kind,
              {_s(authority_source)} AS authority_source, {_s(dict(evidence))} AS evidence_json,
              'active' AS state, {_ts(now)} AS created_at, {_lit(actor_email)} AS created_by,
              {_ts(now)} AS updated_at, {_lit(actor_email)} AS updated_by,
              CAST(NULL AS TIMESTAMP) AS superseded_at, CAST(NULL AS STRING) AS superseded_by) s
ON t.relationship_id = s.relationship_id
WHEN MATCHED AND NOT (t.authority_source = 'override' AND s.authority_source <> 'override') THEN UPDATE SET
    authority_source = s.authority_source, evidence_json = s.evidence_json, state = 'active',
    updated_at = s.updated_at, updated_by = s.updated_by
WHEN NOT MATCHED THEN INSERT *"""
            ),
        )
        return relationship_id

    def list_relationships(self, entity_id: Optional[str] = None, kinds: Sequence[str] = ()) -> List[Dict[str, Any]]:
        clauses = ["state = 'active'"]
        if entity_id:
            clauses.append(f"(source_entity_id = {_lit(entity_id)} OR target_entity_id = {_lit(entity_id)})")
        if kinds:
            clauses.append(f"relationship_kind IN ({', '.join(_lit(k) for k in kinds)})")
        frame = self.uc.query_df(
            f"""SELECT relationship_id, relationship_kind, source_entity_id, source_entity_kind,
       target_entity_id, target_entity_kind, authority_source, evidence_json, state,
       created_at, created_by, updated_at, updated_by
FROM {self._fq("entity_relationships")}
WHERE {' AND '.join(clauses)}"""
        )
        return _records(frame, ("evidence_json",))

    def intake_aliases(self) -> Dict[str, str]:
        """entity_id -> intake_id from steward-confirmed aliases (match rule M2)."""
        frame = self.uc.query_df(
            f"""SELECT entity_id, alias_value FROM {self._fq("entity_aliases")}
WHERE lower(alias_type) = 'external_id' AND lower(source) IN ('intake_id', 'servicenow_sys_id')"""
        )
        return {str(r["entity_id"]): str(r["alias_value"]) for r in _records(frame)}

    def confirm_match(
        self,
        *,
        finding_id: str,
        entity_id: str,
        entity_kind: str,
        intake_id: str,
        actor_email: str,
        actor_role: str,
        request_id: Optional[str] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        """Steward confirmation: override `declares` relationship + intake
        alias, then resolve the finding. The next run matches it as M2."""
        entry = AuditEntry(
            event_type="ai.finding.match_confirmed",
            entity_kind="ai_finding",
            entity_id=finding_id,
            actor_email=actor_email,
            actor_role=actor_role,
            after={"entityId": entity_id, "intakeId": intake_id, "note": note},
            source="api",
            request_id=request_id,
        )
        self.audit_batch([entry])
        self.upsert_relationship(
            relationship_kind="declares",
            source_entity_id=f"intake:{intake_id}",
            source_entity_kind="intake_record",
            target_entity_id=entity_id,
            target_entity_kind=entity_kind,
            authority_source="override",
            evidence={"findingId": finding_id, "confirmedBy": actor_email, "note": note},
            actor_email=actor_email,
            actor_role=actor_role,
            request_id=request_id,
            source="api",
        )
        self.store.upsert_entity_alias(
            entity_id=entity_id,
            alias_value=intake_id,
            alias_type="external_id",
            source="intake_id",
            updated_by=actor_email,
            actor_role=actor_role,
        )
        return self.update_finding_state(
            finding_id=finding_id,
            action="resolve",
            actor_email=actor_email,
            actor_role=actor_role,
            request_id=request_id,
            note=note or f"Match confirmed to intake {intake_id}.",
        )

    # --------------------------------------------------------------- controls
    def replace_control_results_for_run(self, results: Sequence[ControlResult], *, run_id: str, actor_email: str) -> int:
        """Idempotent per run: re-running a failed run replaces its rows."""
        now = _now()
        entry = AuditEntry(
            event_type="ai.controls.results_recorded",
            entity_kind="ai_control_results",
            entity_id=run_id,
            actor_email=actor_email,
            actor_role=SYSTEM_ACTOR_ROLE,
            after={"count": len(results), "byStatus": dict(Counter(r.status for r in results))},
        )

        def _replace() -> int:
            self.uc.execute(f"DELETE FROM {self._fq('ai_control_results')} WHERE run_id = {_lit(run_id)}")
            for chunk in _chunks(list(results)):
                values = ", ".join(
                    "("
                    + ", ".join(
                        [
                            _lit(uuid.uuid4().hex),
                            _lit(run_id),
                            _lit(r.entity_id),
                            _lit(r.entity_kind),
                            _lit(r.control_id),
                            _lit(r.control_version),
                            _lit(r.status),
                            _lit(r.signal_source),
                            _lit(r.evidence),
                            _ts(now),
                            _lit(r.provenance_class),
                            _lit(r.sample_run_id),
                        ]
                    )
                    + ")"
                    for r in chunk
                )
                self.uc.execute(
                    f"""INSERT INTO {self._fq("ai_control_results")} (
    result_id, run_id, entity_id, entity_kind, control_id, control_version,
    status, signal_source, evidence_json, observed_at, provenance_class, sample_run_id
) VALUES {values}"""
                )
            return len(results)

        return self.audited([entry], _replace)

    def list_control_results(self, *, run_id: str, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        clauses = [f"run_id = {_lit(run_id)}"]
        if entity_id:
            clauses.append(f"entity_id = {_lit(entity_id)}")
        frame = self.uc.query_df(
            f"""SELECT result_id, run_id, entity_id, entity_kind, control_id, control_version,
       status, signal_source, evidence_json, observed_at, provenance_class, sample_run_id
FROM {self._fq("ai_control_results")}
WHERE {' AND '.join(clauses)}
ORDER BY entity_id, control_id"""
        )
        return _records(frame, ("evidence_json",))

    def purge_sample(self, sample_run_id: str, *, actor_email: str) -> Dict[str, int]:
        """Remove one sample run's rows (seed --cleanup). Scoped strictly by
        sample_run_id; registry, relationship, and alias rows are removed only
        for entities that sample run observed. Audited before deleting."""
        run = str(sample_run_id or "").strip()
        if not run:
            raise ValueError("sample_run_id is required")
        frame = self.uc.query_df(
            f"""SELECT DISTINCT entity_kind, source_system, source_entity_id FROM {self._fq("ai_asset_observations")}
WHERE provenance_class = 'sample' AND sample_run_id = {_lit(run)}"""
        )
        from atlas.ai.models import ai_entity_id

        entity_ids = sorted(
            {ai_entity_id(str(r["entity_kind"]), str(r["source_system"]), str(r["source_entity_id"])) for r in _records(frame)}
        )
        intake_frame = self.uc.query_df(
            f"""SELECT intake_id FROM {self._fq("intake_records")}
WHERE provenance_class = 'sample' AND sample_run_id = {_lit(run)}"""
        )
        intake_ids = sorted({str(r["intake_id"]) for r in _records(intake_frame)})
        entry = AuditEntry(
            event_type="ai.sample.purged",
            entity_kind="ai_sample_run",
            entity_id=run,
            actor_email=actor_email,
            actor_role=SYSTEM_ACTOR_ROLE,
            after={"entities": len(entity_ids), "intakes": len(intake_ids)},
        )

        def _purge() -> Dict[str, int]:
            scoped = f"provenance_class = 'sample' AND sample_run_id = {_lit(run)}"
            for table in ("ai_control_results", "reconciliation_findings", "ai_asset_observations", "intake_records"):
                self.uc.execute(f"DELETE FROM {self._fq(table)} WHERE {scoped}")
            for chunk in _chunks(intake_ids):
                ids = ", ".join(_lit(i) for i in chunk)
                self.uc.execute(f"DELETE FROM {self._fq('intake_records_history')} WHERE intake_id IN ({ids})")
                sources = ", ".join(_lit(f"intake:{i}") for i in chunk)
                self.uc.execute(f"DELETE FROM {self._fq('entity_relationships')} WHERE source_entity_id IN ({sources})")
            for chunk in _chunks(entity_ids):
                ids = ", ".join(_lit(i) for i in chunk)
                self.uc.execute(f"DELETE FROM {self._fq('entity_registry')} WHERE entity_id IN ({ids})")
                self.uc.execute(f"DELETE FROM {self._fq('entity_aliases')} WHERE entity_id IN ({ids})")
                self.uc.execute(
                    f"DELETE FROM {self._fq('entity_relationships')} WHERE source_entity_id IN ({ids}) OR target_entity_id IN ({ids})"
                )
            return {"entities": len(entity_ids), "intakes": len(intake_ids)}

        return self.audited([entry], _purge)

    def emit_events(self, entries: Sequence[AuditEntry]) -> None:
        """Audit-only events that accompany no single-table mutation (for
        example ai.controls.posture_changed computed by reconciliation)."""
        self.audit_batch(entries)
