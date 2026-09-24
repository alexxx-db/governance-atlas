"""AiStore: SQL shape, escaping, fail-closed audit ordering, and preservation
of steward decisions across reconciliation re-runs."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

from atlas.ai import models
from atlas.ai.store import AiStore, AuditEntry


class FakeUC:
    def __init__(self, frames: Dict[str, pd.DataFrame] | None = None, fail_on: str | None = None) -> None:
        self.executed: List[str] = []
        self.frames = frames or {}
        self.fail_on = fail_on

    def execute(self, sql: str) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("simulated statement failure")
        self.executed.append(sql)

    def query_df(self, sql: str) -> pd.DataFrame:
        for needle, frame in self.frames.items():
            if needle in sql:
                return frame
        return pd.DataFrame()


class FakeGovernanceStore:
    def __init__(self, uc: FakeUC) -> None:
        self.uc = uc
        self.registry_calls: List[Dict[str, Any]] = []
        self.alias_calls: List[Dict[str, Any]] = []

    def _fq(self, table: str) -> str:
        return f"`main`.`atlas`.`{table}`"

    def upsert_entity_registry(self, **kwargs: Any) -> Dict[str, Any]:
        self.registry_calls.append(kwargs)
        return {"entityId": kwargs["entity_id"]}

    def upsert_entity_alias(self, **kwargs: Any) -> Dict[str, Any]:
        self.alias_calls.append(kwargs)
        return {"aliasId": "a1"}


def _store(**kwargs: Any) -> tuple[AiStore, FakeUC, FakeGovernanceStore]:
    uc = FakeUC(**kwargs)
    gov = FakeGovernanceStore(uc)
    return AiStore(gov), uc, gov


def _finding(**overrides: Any) -> models.Finding:
    base = dict(
        finding_id="f1",
        finding_type="found_not_registered",
        rule_id="R-FNR-01",
        severity="high",
        entity_id="e1",
        entity_kind="external_model",
        intake_id=None,
        match_rule=None,
        match_score=None,
        evidence={"reason": "no intake match"},
    )
    base.update(overrides)
    return models.Finding(**base)


def _intake(**overrides: Any) -> models.IntakeRecord:
    base = dict(
        intake_id="INT-1",
        title="O'Brien \\ chatbot",
        state="approved",
        owner_email="a@b.com",
        source_system="csv",
        ingest_source="csv",
        ingest_run_id="imp-1",
    )
    base.update(overrides)
    return models.IntakeRecord(**base)


class AuditOrderingTests(unittest.TestCase):
    def test_audit_failure_blocks_mutation(self) -> None:
        store, uc, _ = _store(fail_on="metadata_audit_log")
        with self.assertRaises(RuntimeError):
            store.upsert_intake_records([_intake()], actor_email="s@b.com", actor_role="steward")
        self.assertFalse([sql for sql in uc.executed if "intake_records" in sql])

    def test_mutation_failure_records_failed_audit(self) -> None:
        store, uc, _ = _store(fail_on="MERGE INTO `main`.`atlas`.`intake_records`")
        with self.assertRaises(RuntimeError):
            store.upsert_intake_records([_intake()], actor_email="s@b.com", actor_role="steward")
        audits = [sql for sql in uc.executed if "INSERT INTO `main`.`atlas`.`metadata_audit_log`" in sql]
        self.assertEqual(len(audits), 2)
        self.assertIn("'success'", audits[0])
        self.assertIn("'failed'", audits[1])
        events = [sql for sql in uc.executed if "INSERT INTO `main`.`atlas`.`change_events`" in sql]
        self.assertIn("'emitted'", events[0])
        self.assertIn("'failed'", events[1])

    def test_every_audit_has_a_change_event(self) -> None:
        store, uc, _ = _store()
        store.audit_batch([AuditEntry("ai.x", "k", "id", "a@b.com", "system") for _ in range(3)])
        self.assertEqual(sum("metadata_audit_log" in sql for sql in uc.executed), 1)
        self.assertEqual(sum("change_events" in sql for sql in uc.executed), 1)
        self.assertEqual(uc.executed[1].count("'ai.x'"), 3)


class IntakeTests(unittest.TestCase):
    def test_escaping_and_history(self) -> None:
        store, uc, _ = _store()
        counts = store.upsert_intake_records([_intake()], actor_email="s@b.com", actor_role="steward", request_id="r1")
        self.assertEqual(counts, {"created": 1, "updated": 0, "unchanged": 0})
        merge = next(sql for sql in uc.executed if sql.startswith("MERGE INTO `main`.`atlas`.`intake_records`"))
        self.assertIn("'O''Brien \\\\ chatbot'", merge)
        self.assertIn("CAST(NULL AS STRING) AS business_unit", merge)
        self.assertIn("CAST(NULL AS TIMESTAMP) AS approved_at", merge)
        self.assertTrue(any("intake_records_history" in sql and "'created'" in sql for sql in uc.executed))
        self.assertTrue(any("'ai.intake.ingested'" in sql and "'import'" in sql for sql in uc.executed))

    def test_unchanged_row_detected_by_hash(self) -> None:
        record = _intake()
        existing = pd.DataFrame([{"intake_id": "INT-1", "content_hash": record.content_hash, "title": record.title}])
        store, _, _ = _store(frames={"WHERE intake_id IN": existing})
        self.assertEqual(
            store.upsert_intake_records([record], actor_email="s@b.com", actor_role="steward"),
            {"created": 0, "updated": 0, "unchanged": 1},
        )


class FindingTests(unittest.TestCase):
    def test_merge_preserves_steward_fields_and_only_reopens_system_resolved(self) -> None:
        store, uc, _ = _store()
        counts = store.upsert_findings([_finding()], run_id="run-1", actor_email="collector")
        self.assertEqual(counts["opened"], 1)
        merge = next(sql for sql in uc.executed if sql.startswith("MERGE INTO `main`.`atlas`.`reconciliation_findings`"))
        update_clauses = merge.split("WHEN NOT MATCHED")[0]
        for steward_field in ("assignee_email =", "task_id =", "resolution_note =", "suppression_reason ="):
            self.assertNotIn(steward_field, update_clauses)
        self.assertIn("t.state = 'resolved' AND t.resolved_by = 'system'", merge)
        # The unconditional WHEN MATCHED clause never touches state, so
        # suppressed and acknowledged findings stay as the steward left them.
        generic = merge.split("WHEN MATCHED THEN UPDATE SET")[1].split("WHEN NOT MATCHED")[0]
        self.assertNotIn("state =", generic.replace("state_changed", ""))

    def test_rerun_unchanged_still_audited(self) -> None:
        finding = _finding()
        existing = pd.DataFrame(
            [{"finding_id": "f1", "state": "suppressed", "severity": "high", "evidence_json": '{"reason":"no intake match"}', "resolved_by": None}]
        )
        store, uc, _ = _store(frames={"WHERE finding_id IN": existing})
        counts = store.upsert_findings([finding], run_id="run-2", actor_email="collector")
        self.assertEqual(counts["unchanged"], 1)
        self.assertTrue(any("'ai.findings.merged'" in sql for sql in uc.executed))
        self.assertFalse(any("'ai.finding.opened'" in sql for sql in uc.executed))

    def test_steward_resolved_is_not_counted_as_reopened(self) -> None:
        existing = pd.DataFrame(
            [{"finding_id": "f1", "state": "resolved", "severity": "high", "evidence_json": '{"reason":"no intake match"}', "resolved_by": "s@b.com"}]
        )
        store, _, _ = _store(frames={"WHERE finding_id IN": existing})
        counts = store.upsert_findings([_finding()], run_id="run-2", actor_email="collector")
        self.assertEqual(counts.get("reopened", 0), 0)

    def test_auto_resolve_never_touches_suppressed(self) -> None:
        store, uc, _ = _store()
        store.auto_resolve_findings(["f1", "f2"], run_id="run-3", actor_email="collector")
        update = next(sql for sql in uc.executed if sql.startswith("UPDATE `main`.`atlas`.`reconciliation_findings`"))
        self.assertIn("AND state IN ('open', 'acknowledged')", update)
        self.assertIn("resolved_by = 'system'", update)

    def test_steward_actions_require_reasons(self) -> None:
        existing = pd.DataFrame([{"finding_id": "f1", "state": "open"}])
        store, uc, _ = _store(frames={"WHERE finding_id IN": existing})
        with self.assertRaises(ValueError):
            store.update_finding_state(finding_id="f1", action="resolve", actor_email="s@b.com", actor_role="steward")
        with self.assertRaises(ValueError):
            store.update_finding_state(finding_id="f1", action="suppress", actor_email="s@b.com", actor_role="steward", reason="  ")
        with self.assertRaises(ValueError):
            store.update_finding_state(finding_id="f1", action="delete", actor_email="s@b.com", actor_role="steward")
        self.assertFalse(uc.executed)  # nothing written for invalid requests
        store.update_finding_state(
            finding_id="f1", action="suppress", actor_email="s@b.com", actor_role="steward", reason="known pilot", request_id="r9"
        )
        self.assertTrue(any("suppression_reason = 'known pilot'" in sql for sql in uc.executed))
        self.assertTrue(any("'ai.finding.updated'" in sql and "'r9'" in sql for sql in uc.executed))

    def test_missing_finding_raises_lookup(self) -> None:
        store, _, _ = _store()
        with self.assertRaises(LookupError):
            store.update_finding_state(finding_id="nope", action="acknowledge", actor_email="s@b.com", actor_role="steward")


class RegistryAndControlsTests(unittest.TestCase):
    def test_registry_goes_through_wrapped_store_and_events_on_change_only(self) -> None:
        store, uc, gov = _store()
        kwargs = dict(
            entity_id="e1",
            entity_kind="external_model",
            source_system="databricks",
            source_entity_id="ep/claude",
            reconciliation_state="orphaned",
            confidence=None,
            observed_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            actor_email="collector",
        )
        store.upsert_ai_registry(**kwargs, prior_state="orphaned")
        self.assertEqual(len(gov.registry_calls), 1)
        self.assertFalse(any("ai.registry.state_changed" in sql for sql in uc.executed))
        store.upsert_ai_registry(**{**kwargs, "reconciliation_state": "matched"}, prior_state="orphaned")
        self.assertTrue(any("'ai.registry.state_changed'" in sql for sql in uc.executed))

    def test_confirm_match_writes_override_alias_and_resolves(self) -> None:
        existing = pd.DataFrame([{"finding_id": "f1", "state": "open"}])
        store, uc, gov = _store(frames={"WHERE finding_id IN": existing})
        store.confirm_match(
            finding_id="f1", entity_id="e1", entity_kind="serving_endpoint", intake_id="INT-7",
            actor_email="s@b.com", actor_role="steward", request_id="r1",
        )
        self.assertTrue(any("'ai.finding.match_confirmed'" in sql for sql in uc.executed))
        self.assertTrue(any("MERGE INTO `main`.`atlas`.`entity_relationships`" in sql and "'override'" in sql for sql in uc.executed))
        self.assertEqual(gov.alias_calls[0]["alias_value"], "INT-7")
        self.assertEqual(gov.alias_calls[0]["source"], "intake_id")
        self.assertTrue(any("state = 'resolved'" in sql for sql in uc.executed))

    def test_relationship_merge_never_downgrades_override(self) -> None:
        store, uc, _ = _store()
        store.upsert_relationship(
            relationship_kind="declares", source_entity_id="intake:INT-1", source_entity_kind="intake_record",
            target_entity_id="e1", target_entity_kind="serving_endpoint", authority_source="registry",
            evidence={"rule": "M1"}, actor_email="collector",
        )
        merge = next(sql for sql in uc.executed if "entity_relationships" in sql and sql.startswith("MERGE"))
        self.assertIn("NOT (t.authority_source = 'override' AND s.authority_source <> 'override')", merge)

    def test_control_results_replace_per_run(self) -> None:
        store, uc, _ = _store()
        store.replace_control_results_for_run(
            [models.ControlResult("e1", "serving_endpoint", "AIC-04", "1", "unknown", "serving_endpoints")],
            run_id="run-1", actor_email="collector",
        )
        mutations = [sql for sql in uc.executed if "ai_control_results" in sql and "metadata_audit" not in sql and "change_events" not in sql]
        self.assertTrue(mutations[0].startswith("DELETE FROM `main`.`atlas`.`ai_control_results` WHERE run_id = 'run-1'"))
        self.assertIn("'unknown'", mutations[1])

    def test_observations_batch_single_audit(self) -> None:
        store, uc, _ = _store()
        obs = [
            models.Observation(
                run_id="run-1", source_system="databricks", collector="dbx_ai_collector", collector_version="1",
                entity_kind="serving_endpoint", source_entity_id=f"ep-{i}", observed_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            )
            for i in range(450)
        ]
        self.assertEqual(store.append_observations(obs, run_id="run-1", actor_email="collector"), 450)
        inserts = [sql for sql in uc.executed if sql.startswith("INSERT INTO `main`.`atlas`.`ai_asset_observations`")]
        self.assertEqual(len(inserts), 3)  # batches of 200
        # One audit row + one change event for the whole batch.
        self.assertEqual(sum("'ai.observation.appended'" in sql for sql in uc.executed), 2)


if __name__ == "__main__":
    unittest.main()


class ProvenanceRegressionTests(unittest.TestCase):
    def test_rerun_with_new_provenance_only_is_unchanged(self) -> None:
        existing = pd.DataFrame([{
            "finding_id": "f1", "state": "open", "severity": "high", "resolved_by": None,
            "evidence_json": '{"reason":"no intake match","provenance":{"runId":"run-1","observedAt":"t1"}}',
        }])
        store, uc, _ = _store(frames={"WHERE finding_id IN": existing})
        finding = _finding(evidence={"reason": "no intake match", "provenance": {"runId": "run-2", "observedAt": "t2"}})
        counts = store.upsert_findings([finding], run_id="run-2", actor_email="collector")
        self.assertEqual(counts.get("unchanged"), 1)
        self.assertFalse(any("'ai.finding.updated'" in sql for sql in uc.executed))

    def test_control_results_keep_sample_provenance(self) -> None:
        store, uc, _ = _store()
        store.replace_control_results_for_run(
            [models.ControlResult("e1", "serving_endpoint", "AIC-04", "1", "pass", "s", provenance_class="sample", sample_run_id="ga-ai-1")],
            run_id="run-1", actor_email="collector",
        )
        insert = next(sql for sql in uc.executed if sql.startswith("INSERT INTO `main`.`atlas`.`ai_control_results`"))
        self.assertIn("'sample', 'ga-ai-1'", insert)
