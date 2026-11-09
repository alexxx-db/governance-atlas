from __future__ import annotations

import json
import unittest
from typing import Any, Dict, List, Optional

import pandas as pd

from axiom.services import classification as classification_service


class FakeUC:
    """Minimal UC double that exposes just the methods the service touches."""

    def __init__(self, *, column_tags: Optional[Dict[str, List[Dict[str, str]]]] = None):
        self.column_tag_writes: List[Dict[str, Any]] = []
        self._column_tags = column_tags or {}

    def get_column_tags(
        self, catalog: str, schema: str, table: str, column: str
    ) -> pd.DataFrame:
        key = f"{catalog}.{schema}.{table}.{column}"
        rows = self._column_tags.get(key, [])
        return pd.DataFrame(rows, columns=["tag_name", "tag_value"]) if rows else pd.DataFrame()

    def set_column_tags(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        tags: Dict[str, str],
        *,
        table_type: Optional[str] = None,
    ) -> None:
        self.column_tag_writes.append(
            {
                "catalog": catalog,
                "schema": schema,
                "table": table,
                "column": column,
                "tags": dict(tags),
            }
        )


class FakeStore:
    """In-memory stand-in for GovernanceStore."""

    def __init__(self) -> None:
        self.records: Dict[str, Dict[str, Any]] = {}
        self.audit_events: List[Dict[str, Any]] = []

    def upsert_classification_recommendation(
        self,
        record: Dict[str, Any],
        *,
        actor_email: Optional[str] = None,
    ) -> str:
        rec_id = record.get("recommendation_id") or f"auto-{len(self.records)}"
        snapshot = dict(record)
        snapshot.setdefault("status", "pending")
        snapshot["recommendation_id"] = rec_id
        snapshot.setdefault("created_by", actor_email or "system")
        snapshot.setdefault("updated_by", actor_email or "system")
        self.records[rec_id] = snapshot
        return rec_id

    def list_classification_recommendations(
        self,
        *,
        status: Optional[str] = None,
        asset_fqn: Optional[str] = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        rows = []
        for rec in self.records.values():
            if status and str(rec.get("status") or "").lower() != status.lower():
                continue
            if asset_fqn and rec.get("asset_fqn") != asset_fqn:
                continue
            rows.append(rec)
        return pd.DataFrame(rows)

    def get_classification_recommendation(
        self, recommendation_id: str
    ) -> Optional[Dict[str, Any]]:
        rec = self.records.get(recommendation_id)
        return dict(rec) if rec else None

    def set_classification_recommendation_status(
        self,
        recommendation_id: str,
        *,
        status: str,
        reviewer: str,
        review_note: Optional[str] = None,
    ) -> None:
        rec = self.records.get(recommendation_id)
        if not rec:
            return
        rec["status"] = status
        rec["reviewed_by"] = reviewer
        rec["reviewed_at"] = "2026-04-20 00:00:00"
        rec["review_note"] = review_note
        rec["updated_by"] = reviewer

    def append_metadata_audit(
        self,
        *,
        entity_type: str,
        action: str,
        actor_email: str,
        actor_role: str,
        entity_fqn: Optional[str] = None,
        entity_id: Optional[str] = None,
        column_name: Optional[str] = None,
        request_id: Optional[str] = None,
        before: Any = None,
        after: Any = None,
        source: str = "store",
        status: str = "success",
        detail: Optional[str] = None,
    ) -> str:
        event = {
            "entity_type": entity_type,
            "action": action,
            "actor_email": actor_email,
            "entity_fqn": entity_fqn,
            "column_name": column_name,
            "before": before,
            "after": after,
            "source": source,
            "status": status,
            "detail": detail,
        }
        self.audit_events.append(event)
        return f"audit-{len(self.audit_events)}"


class RedactSampleValuesTests(unittest.TestCase):
    def test_redacts_when_hint_matches_pii(self) -> None:
        out = classification_service.redact_sample_values(
            ["alice@example.com", "bob@example.com"], "pii"
        )
        self.assertEqual(out, ["***", "***"])

    def test_redacts_on_restricted_hint(self) -> None:
        out = classification_service.redact_sample_values([1, 2, 3], "restricted")
        self.assertEqual(out, ["***", "***", "***"])

    def test_untouched_on_internal_hint(self) -> None:
        out = classification_service.redact_sample_values(["a", "b"], "internal")
        self.assertEqual(out, ["a", "b"])

    def test_untouched_on_missing_hint(self) -> None:
        out = classification_service.redact_sample_values(["a"], None)
        self.assertEqual(out, ["a"])


class GenerateRecommendationsTests(unittest.TestCase):
    def test_name_pattern_ssn(self) -> None:
        uc = FakeUC()
        recs = classification_service.generate_recommendations(
            uc,
            "main.sales.customers",
            [{"column_name": "ssn", "comment": ""}],
        )
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["column_name"], "ssn")
        self.assertEqual(rec["suggested_sensitivity"], "restricted")
        self.assertEqual(rec["suggested_tier"], "pii")
        self.assertTrue(rec["sample_redacted"])
        self.assertEqual(rec["status"], "pending")
        evidence = json.loads(rec["evidence_json"])
        self.assertTrue(any(ev["source"] == "name_pattern" for ev in evidence))

    def test_name_pattern_email(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [{"column_name": "contact_email", "comment": ""}],
        )
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["suggested_tier"], "pii")

    def test_tag_evidence_without_pattern(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [
                {
                    "column_name": "opaque_thing",
                    "comment": "",
                    "tags": {"sensitivity": "confidential"},
                }
            ],
        )
        self.assertEqual(len(recs), 1)
        evidence = json.loads(recs[0]["evidence_json"])
        self.assertTrue(any(ev["source"] == "uc_tag" for ev in evidence))
        self.assertEqual(recs[0]["suggested_sensitivity"], "confidential")

    def test_comment_evidence(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [
                {
                    "column_name": "mystery",
                    "comment": "This field contains PII per GDPR.",
                }
            ],
        )
        self.assertEqual(len(recs), 1)
        evidence = json.loads(recs[0]["evidence_json"])
        comment_hits = [ev for ev in evidence if ev["source"] == "column_comment"]
        self.assertTrue(comment_hits)

    def test_glossary_match(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [{"column_name": "customer_id", "comment": ""}],
            glossary_terms=[{"term_id": "t1", "name": "customer_id"}],
        )
        self.assertEqual(len(recs), 1)
        evidence = json.loads(recs[0]["evidence_json"])
        self.assertTrue(any(ev["source"] == "glossary_match" for ev in evidence))

    def test_no_evidence_returns_empty(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [{"column_name": "totally_normal", "comment": ""}],
        )
        self.assertEqual(recs, [])

    def test_empty_tags_does_not_trigger_per_column_uc_fetch(self) -> None:
        """Round 17 regression: columns passed with ``tags=[]`` (explicit
        empty list) must not re-trigger a per-column ``get_column_tags``
        UC call. Previously the service used ``tags or tagEntries`` which
        collapsed empty lists back to ``None`` and issued one UC round-
        trip per column — the 50-column-table classification scan then
        exceeded the 60-second Databricks edge-proxy timeout."""

        class CountingUC(FakeUC):
            def __init__(self) -> None:
                super().__init__()
                self.get_column_tags_calls = 0

            def get_column_tags(self, *args, **kwargs):
                self.get_column_tags_calls += 1
                return super().get_column_tags(*args, **kwargs)

        uc = CountingUC()
        columns = [
            {"column_name": "ssn", "tags": []},
            {"column_name": "email_address", "tags": []},
            {"column_name": "plain_text_col", "tags": []},
        ]
        classification_service.generate_recommendations(
            uc, "main.sales.customers", columns
        )
        self.assertEqual(
            uc.get_column_tags_calls,
            0,
            msg=(
                "Per-column UC fallback must not fire when column already "
                "carries an (empty) tags list."
            ),
        )

    def test_rejects_non_three_part_fqn(self) -> None:
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "not_a_real_fqn",
            [{"column_name": "ssn"}],
        )
        self.assertEqual(recs, [])


class PersistAndListTests(unittest.TestCase):
    def test_persist_emits_audit_and_upserts(self) -> None:
        store = FakeStore()
        recs = classification_service.generate_recommendations(
            FakeUC(),
            "main.sales.customers",
            [{"column_name": "ssn"}],
        )
        ids = classification_service.persist_recommendations(store, recs, actor_email="alice@test.co")
        self.assertEqual(len(ids), 1)
        self.assertEqual(len(store.audit_events), 1)
        self.assertEqual(store.audit_events[0]["action"], "classification_recommended")

    def test_list_filters_by_status(self) -> None:
        store = FakeStore()
        store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.a.b",
                "column_name": "x",
                "status": "pending",
                "sample_redacted": True,
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
            }
        )
        store.upsert_classification_recommendation(
            {
                "recommendation_id": "r2",
                "asset_fqn": "main.a.b",
                "column_name": "y",
                "status": "approved",
                "sample_redacted": True,
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
            }
        )
        pending = classification_service.list_recommendations(store, status="pending")
        approved = classification_service.list_recommendations(store, status="approved")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["recommendationId"], "r1")
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["recommendationId"], "r2")


class ReviewTransitionTests(unittest.TestCase):
    def _seed(self, store: FakeStore) -> str:
        return store.upsert_classification_recommendation(
            {
                "recommendation_id": "rec-1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "suggested_sensitivity": "restricted",
                "suggested_tier": "pii",
                "suggested_certification": "classified",
                "status": "pending",
                "sample_redacted": True,
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
            }
        )

    def test_approve_writes_column_tag(self) -> None:
        store = FakeStore()
        rec_id = self._seed(store)
        uc = FakeUC()
        updated = classification_service.review_recommendation(
            store,
            rec_id,
            decision="approved",
            reviewer="alice@test.co",
            note="looks good",
            uc=uc,
        )
        self.assertEqual(updated["status"], "approved")
        self.assertTrue(uc.column_tag_writes)
        write = uc.column_tag_writes[0]
        self.assertEqual(write["tags"].get("sensitivity"), "restricted")
        self.assertEqual(store.audit_events[-1]["action"], "classification_approved")

    def test_reject_does_not_write_tag(self) -> None:
        store = FakeStore()
        rec_id = self._seed(store)
        uc = FakeUC()
        updated = classification_service.review_recommendation(
            store,
            rec_id,
            decision="rejected",
            reviewer="alice@test.co",
            note="false positive",
            uc=uc,
        )
        self.assertEqual(updated["status"], "rejected")
        self.assertEqual(uc.column_tag_writes, [])
        self.assertEqual(store.audit_events[-1]["action"], "classification_rejected")

    def test_defer_state_transition(self) -> None:
        store = FakeStore()
        rec_id = self._seed(store)
        updated = classification_service.review_recommendation(
            store,
            rec_id,
            decision="deferred",
            reviewer="alice@test.co",
        )
        self.assertEqual(updated["status"], "deferred")
        self.assertEqual(store.audit_events[-1]["action"], "classification_deferred")

    def test_invalid_decision_raises(self) -> None:
        store = FakeStore()
        rec_id = self._seed(store)
        with self.assertRaises(ValueError):
            classification_service.review_recommendation(
                store,
                rec_id,
                decision="yolo",
                reviewer="alice@test.co",
            )

    def test_missing_recommendation_raises(self) -> None:
        store = FakeStore()
        with self.assertRaises(LookupError):
            classification_service.review_recommendation(
                store,
                "does-not-exist",
                decision="approved",
                reviewer="alice@test.co",
            )

    def test_approve_without_uc_records_apply_todo(self) -> None:
        store = FakeStore()
        rec_id = self._seed(store)
        updated = classification_service.review_recommendation(
            store,
            rec_id,
            decision="approved",
            reviewer="alice@test.co",
            uc=None,
        )
        self.assertEqual(updated["status"], "approved")
        # tagApply entry carries a non-null error so the surface can flag
        # "apply classification tag manually".
        self.assertIn("tagApply", updated)
        self.assertFalse(updated["tagApply"]["applied"])
        self.assertTrue(updated["tagApply"]["error"])


class EvidencePatternsShapeTests(unittest.TestCase):
    def test_pattern_table_is_small_and_structured(self) -> None:
        self.assertLess(len(classification_service.EVIDENCE_PATTERNS), 20)
        for pattern in classification_service.EVIDENCE_PATTERNS:
            self.assertIn("key", pattern)
            self.assertIn("regex", pattern)
            self.assertIn("sensitivity", pattern)


if __name__ == "__main__":
    unittest.main()
