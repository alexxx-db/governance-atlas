"""Wave A4 — the /360 composite joins REAL signals (teardown P0-3, P1-7,
P2-10, P2-11) and the freshness field split (cohesion law 4).

Covers:
- asset_360_payload freshness/quality/access blocks backed by real sources,
  honest states only when the source truly has nothing;
- activity rows carrying actorEmail + createdBy, humanized titles, priority,
  taskId/threadId, and stable AUD display ids;
- usage per-source availability truth (no fabricated window framing);
- distinct owner roles (ucOwner / businessOwner / steward);
- base_asset_payload + detail-path dataUpdatedAt / lastAltered split.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import pandas as pd

from axiom.services import assets as asset_service
from axiom.services import axiom_metrics


class QualityLedgerStore:
    def list_quality_run_results(
        self, *, entity_fqn: str | None = None, run_id: str | None = None, limit: int = 200
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "result_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                    "run_id": "run-1",
                    "case_id": "case-a",
                    "entity_fqn": entity_fqn or "main.customer.customer_dim",
                    "outcome": "failed",
                    "severity": "critical",
                    "metric_value": 0.0,
                    "threshold_value": 1.0,
                    "executed_at": "2026-07-20 10:00:00",
                    "detail": "row count below minimum",
                },
                {
                    "result_id": "b2b2c3d4e5f60718293a4b5c6d7e8f90",
                    "run_id": "run-1",
                    "case_id": "case-b",
                    "entity_fqn": entity_fqn or "main.customer.customer_dim",
                    "outcome": "passed",
                    "severity": "info",
                    "metric_value": 5.0,
                    "threshold_value": 1.0,
                    "executed_at": "2026-07-20 10:00:05",
                    "detail": "",
                },
                {
                    # Older run — must NOT be the latestRun.
                    "result_id": "c3b2c3d4e5f60718293a4b5c6d7e8f90",
                    "run_id": "run-0",
                    "case_id": "case-a",
                    "entity_fqn": entity_fqn or "main.customer.customer_dim",
                    "outcome": "passed",
                    "severity": "critical",
                    "metric_value": 2.0,
                    "threshold_value": 1.0,
                    "executed_at": "2026-07-01 08:00:00",
                    "detail": "",
                },
            ]
        )


class EmptyLedgerStore:
    def list_quality_run_results(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame()


def _detail(**overrides) -> dict:
    base = {
        "fqn": "main.customer.customer_dim",
        "name": "customer_dim",
        "owners": [
            {
                "name": "abarreto@shorecp.com",
                "displayName": "abarreto@shorecp.com",
                "title": "Unity Catalog owner",
            },
            {"name": "product-steward@shorecp.com", "title": "Business Owner"},
            {"name": "finance-steward@shorecp.com", "title": "Steward"},
        ],
        "columns": [{"name": "customer_id"}],
        "activity": [
            {
                "id": "evt-1",
                "title": "Task updated",
                "detail": "open",
                "status": "Pending",
                "createdAt": "2026-07-21T15:04:19.000Z",
                "createdBy": "abarreto@shorecp.com",
                "actorEmail": "abarreto@shorecp.com",
                "taskId": "task-9",
                "threadId": "thread-4",
                "priority": "p1",
            }
        ],
        "metadataAudit": [
            {
                "id": "0f0e0d0c0b0a09080706050403020100",
                "action": "task-triage-updated",
                "detail": "priority changed",
                "status": "Success",
                "createdAt": "2026-07-21T15:00:00.000Z",
                "createdBy": "abarreto@shorecp.com",
                "actorEmail": "abarreto@shorecp.com",
                "entityId": "main.customer.customer_dim",
            }
        ],
        "relatedAssets": [{"fqn": "main.customer.customer_gold"}],
        "operationalContext": {"producers": [], "consumers": []},
        "queries": [],
        "usage": {},
        "loadedSections": ["header", "activity", "schema"],
        "dataUpdatedAt": "2026-05-03T19:51:25Z",
        "lastAltered": "2026-06-01T00:00:00Z",
        "updatedAt": "2026-05-03T19:51:25Z",
    }
    base.update(overrides)
    return base


class Asset360CompositeTests(unittest.TestCase):
    def test_freshness_block_carries_split_labeled_signals(self) -> None:
        payload = axiom_metrics.asset_360_payload(detail=_detail())
        freshness = payload["freshness"]
        self.assertEqual(freshness["state"], "available")
        self.assertEqual(freshness["dataUpdatedAt"], "2026-05-03T19:51:25Z")
        self.assertEqual(freshness["lastAltered"], "2026-06-01T00:00:00Z")
        # Payload-provided labels so no surface can re-mislabel the semantics.
        self.assertEqual(freshness["labels"]["dataUpdatedAt"], "Data updated")
        self.assertEqual(freshness["labels"]["lastAltered"], "Metadata changed")

    def test_freshness_unavailable_only_when_source_has_nothing(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(dataUpdatedAt="", lastAltered="", updatedAt="")
        )
        freshness = payload["freshness"]
        self.assertEqual(freshness["state"], "unavailable")
        self.assertIn("no freshness timestamps", freshness["message"].lower())

    def test_legacy_conflated_timestamp_presents_as_degraded(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(dataUpdatedAt="", lastAltered="")
        )
        self.assertEqual(payload["freshness"]["state"], "degraded")

    def test_quality_block_joins_latest_run_from_ledger(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(), store=QualityLedgerStore()
        )
        quality = payload["quality"]
        self.assertEqual(quality["state"], "available")
        self.assertEqual(quality["latestRun"]["runId"], "run-1")
        self.assertEqual(quality["latestRun"]["outcomes"]["failed"], 1)
        self.assertEqual(quality["latestRun"]["outcomes"]["passed"], 1)
        self.assertEqual(quality["latestRun"]["failedBySeverityLevel"]["high"], 1)
        self.assertTrue(quality["evidenceAt"].endswith("Z"))
        self.assertEqual(quality["checksEvaluated"], 3)

    def test_quality_block_honest_unavailable_for_empty_ledger(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(), store=EmptyLedgerStore()
        )
        self.assertEqual(payload["quality"]["state"], "unavailable")
        self.assertIn("No quality checks have run", payload["quality"]["message"])
        # The old apology constant must be gone.
        self.assertNotIn("not included in this composite payload", json.dumps(payload))

    def test_access_block_uses_access_explain_core(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(),
            auth_mode="app-principal-only",
            actor_email="abarreto@shorecp.com",
        )
        access = payload["access"]
        self.assertEqual(access["state"], "available")
        self.assertEqual(access["authMode"], "app-principal-only")
        self.assertEqual(access["visibilityScope"], "workspace-app-principal")
        self.assertTrue(
            any("per-user authorization" in item["label"].lower() for item in access["remediation"])
        )
        self.assertEqual(
            access["deepLinks"]["catalogExplorer"],
            "/explore/data/main/customer/customer_dim",
        )
        # Grant availability is stated honestly, never an empty table.
        self.assertEqual(access["grants"]["state"], "unavailable")

    def test_activity_rows_carry_actor_priority_and_stable_aud_ids(self) -> None:
        payload = axiom_metrics.asset_360_payload(detail=_detail())
        activity = payload["activity"]
        task_row = next(row for row in activity if row.get("taskId") == "task-9")
        self.assertEqual(task_row["actorEmail"], "abarreto@shorecp.com")
        self.assertEqual(task_row["createdBy"], "abarreto@shorecp.com")
        self.assertEqual(task_row["priority"], "p1")
        self.assertEqual(task_row["threadId"], "thread-4")
        audit_row = next(row for row in activity if row.get("displayAuditId"))
        # Humanized title — never the raw slug.
        self.assertEqual(audit_row["title"], "Task Triage Updated")
        self.assertEqual(audit_row["displayAuditId"], "AUD-0F0E0D0C")
        self.assertEqual(audit_row["actorEmail"], "abarreto@shorecp.com")

    def test_usage_sources_state_never_fetched_operational_as_unavailable(self) -> None:
        payload = axiom_metrics.asset_360_payload(
            detail=_detail(), operational_included=False
        )
        sources = payload["usage"]["sources"]
        self.assertEqual(sources["downstreamAssets"]["state"], "available")
        self.assertEqual(sources["downstreamAssets"]["count"], 1)
        self.assertEqual(sources["consumers"]["state"], "unavailable")
        self.assertIn("OBO", sources["consumers"]["reason"])
        self.assertIsNone(sources["consumers"]["count"])
        self.assertEqual(sources["queries"]["state"], "unavailable")
        # No fabricated window framing anywhere.
        self.assertEqual(payload["usage"]["window"]["state"], "unavailable")
        self.assertEqual(payload["usage"]["window"]["label"], "")
        self.assertNotIn("Last 30 days", json.dumps(payload))

    def test_usage_sources_available_when_operational_loaded(self) -> None:
        detail = _detail(
            loadedSections=["header", "activity", "schema", "operational"],
            operationalContext={"producers": [], "consumers": [{"entityLabel": "Dashboard"}]},
        )
        payload = axiom_metrics.asset_360_payload(detail=detail, operational_included=True)
        sources = payload["usage"]["sources"]
        self.assertEqual(sources["consumers"]["state"], "available")
        self.assertEqual(sources["consumers"]["count"], 1)
        self.assertEqual(sources["queries"]["state"], "available")
        self.assertEqual(sources["queries"]["count"], 0)

    def test_ownership_roles_are_distinct_and_uc_owner_never_shadows(self) -> None:
        payload = axiom_metrics.asset_360_payload(detail=_detail())
        ownership = payload["ownership"]
        self.assertEqual(ownership["ucOwner"]["name"], "abarreto@shorecp.com")
        self.assertEqual(ownership["businessOwner"]["name"], "product-steward@shorecp.com")
        self.assertEqual(ownership["steward"]["name"], "finance-steward@shorecp.com")
        # Compatibility: legacy lists unchanged.
        self.assertEqual(len(payload["owners"]), 3)

    def test_hydrating_blocks_present_as_loading_not_unavailable(self) -> None:
        loading_detail = asset_service.asset_loading_payload("main.customer.customer_dim")
        payload = axiom_metrics.asset_360_payload(detail=loading_detail, hydrating=True)
        self.assertEqual(payload["freshness"]["state"], "loading")
        self.assertEqual(payload["quality"]["state"], "loading")
        self.assertEqual(payload["access"]["state"], "loading")


class FreshnessFieldSplitTests(unittest.TestCase):
    def test_base_asset_payload_emits_split_fields(self) -> None:
        row = pd.Series(
            {
                "fqn": "main.customer.customer_dim",
                "table_catalog": "main",
                "table_schema": "customer",
                "table_name": "customer_dim",
                "last_altered": "2026-06-01 00:00:00",
                "business_owner": "product-steward@shorecp.com",
                "technical_owner": "platform@shorecp.com",
                "steward": "finance-steward@shorecp.com",
            }
        )
        payload = asset_service.base_asset_payload(row)
        # updatedAt keeps its legacy value (frontend still reads it) ...
        self.assertTrue(payload["updatedAt"])
        # ... and lastAltered names the same information_schema signal
        # honestly, while dataUpdatedAt stays empty (unknown at inventory
        # scope — never conflated).
        self.assertEqual(payload["lastAltered"], payload["updatedAt"])
        self.assertEqual(payload["dataUpdatedAt"], "")

    def test_base_asset_payload_emits_distinct_owner_roles(self) -> None:
        row = pd.Series(
            {
                "fqn": "main.customer.customer_dim",
                "table_catalog": "main",
                "table_schema": "customer",
                "table_name": "customer_dim",
                "business_owner": "product-steward@shorecp.com",
                "technical_owner": "platform@shorecp.com",
                "steward": "finance-steward@shorecp.com",
                "uc_owner": "abarreto@shorecp.com",
            }
        )
        payload = asset_service.base_asset_payload(row)
        self.assertEqual(payload["businessOwner"], "product-steward@shorecp.com")
        self.assertEqual(payload["technicalOwner"], "platform@shorecp.com")
        self.assertEqual(payload["steward"], "finance-steward@shorecp.com")
        self.assertEqual(payload["ucOwner"], "abarreto@shorecp.com")


class ActivityRecordRichnessTests(unittest.TestCase):
    def test_activity_records_emit_actor_task_thread_priority(self) -> None:
        class EventsStore:
            def list_activity_events(self, *, entity_fqn: str, limit: int = 20) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "event_id": "evt-1",
                            "event_type": "task_state_changed",
                            "entity_id": "task-9",
                            "entity_fqn_snapshot": entity_fqn,
                            "column_name": None,
                            "actor_entry_id": "u1",
                            "actor_email": "abarreto@shorecp.com",
                            "actor_display_name": "Skyler",
                            "thread_id": "thread-4",
                            "task_id": "task-9",
                            "payload_json": json.dumps({"status": "open", "priority": "p1"}),
                            "created_at": "2026-07-21 15:04:19",
                        },
                        {
                            "event_id": "evt-2",
                            "event_type": "task-triage-updated",
                            "entity_id": "task-9",
                            "entity_fqn_snapshot": entity_fqn,
                            "column_name": None,
                            "actor_entry_id": "u1",
                            "actor_email": "abarreto@shorecp.com",
                            "actor_display_name": "Skyler",
                            "thread_id": None,
                            "task_id": None,
                            "payload_json": None,
                            "created_at": "2026-07-21 15:05:00",
                        },
                    ]
                )

        rows = asset_service.activity_records(EventsStore(), "main.customer.customer_dim")
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["actorEmail"], "abarreto@shorecp.com")
        self.assertEqual(first["createdBy"], "abarreto@shorecp.com")
        self.assertEqual(first["taskId"], "task-9")
        self.assertEqual(first["threadId"], "thread-4")
        self.assertEqual(first["priority"], "p1")
        self.assertEqual(first["title"], "Task updated")
        # Unknown slugs are humanized, never emitted raw.
        self.assertEqual(rows[1]["title"], "Task Triage Updated")
        self.assertEqual(rows[1]["priority"], "")

    def test_metadata_audit_records_carry_stable_display_ids(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "0f0e0d0c0b0a09080706050403020100",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": "2026-07-21 15:00:00",
                            "actor_email": "abarreto@shorecp.com",
                        }
                    ]
                )

        rows = asset_service.metadata_audit_records(AuditStore(), "main.customer.customer_dim")
        self.assertEqual(rows[0]["displayAuditId"], "AUD-0F0E0D0C")
        self.assertEqual(rows[0]["actorEmail"], "abarreto@shorecp.com")


if __name__ == "__main__":
    unittest.main()
