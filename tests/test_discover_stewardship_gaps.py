"""Regression tests for the Discover + Stewardship "incomplete product" gap
fixes.

Covers:
- base_asset_payload no longer bakes literal em-dash placeholders or a
  server-side "No description..." sentence (the client owns placeholders).
- Discovery search payloads carry `updatedAt` when the inventory row has
  `last_altered` (information_schema freshness enrichment).
- Governance workbench request records synthesize meaningful titles, derive a
  default 7-day SLA from created_at, and read stashed fields from
  new_uc_tags_json.
- Workbench metrics: overdueItems and slaPerformance are computed from real
  request timestamps (median reviewed_at - created_at).
- Request detail comments are backed by review_note + request-linked audit
  events.
"""

from __future__ import annotations

import datetime as dt
import unittest

import pandas as pd

from axiom.services import assets
from axiom.services import axiom_metrics


def _inventory_row(**overrides) -> pd.Series:
    base = {
        "fqn": "main.finance.orders",
        "table_name": "orders",
        "table_catalog": "main",
        "table_schema": "finance",
        "table_type": "MANAGED",
        "data_source_format": "delta",
        "comment": "",
        "governance_score": 55,
        "tags": {},
    }
    base.update(overrides)
    return pd.Series(base)


def _inventory_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "main.finance.orders",
                "table_name": "orders",
                "table_catalog": "main",
                "table_schema": "finance",
                "table_type": "MANAGED",
                "data_source_format": "delta",
                "comment": "Orders fact table",
                "governance_score": 91,
                "domain": "Finance",
                "tags": {},
                "last_altered": "2026-07-01T10:20:30+00:00",
            },
        ]
    )


class BaseAssetPayloadGapTests(unittest.TestCase):
    def test_no_placeholder_dashes_or_description_sentence(self) -> None:
        payload = assets.base_asset_payload(_inventory_row())

        # Description is emitted empty — the CLIENT renders the placeholder.
        self.assertEqual(payload["description"], "")
        # No literal em-dash placeholders in unknown numeric/format fields.
        for key in ("rows", "size", "files"):
            self.assertEqual(payload[key], "", key)
        self.assertNotEqual(payload["format"], "—")
        self.assertNotEqual(payload["storageFormat"], "—")
        self.assertNotEqual(payload["managementType"], "—")

    def test_real_description_and_management_type_pass_through(self) -> None:
        payload = assets.base_asset_payload(
            _inventory_row(comment="Curated orders", table_type="MANAGED")
        )
        self.assertEqual(payload["description"], "Curated orders")
        self.assertEqual(payload["managementType"], "Managed")

    def test_updated_at_emitted_from_last_altered(self) -> None:
        payload = assets.base_asset_payload(
            _inventory_row(last_altered=pd.Timestamp("2026-07-01T10:20:30Z"))
        )
        self.assertTrue(payload["updatedAt"].startswith("2026-07-01T10:20:30"))

    def test_updated_at_empty_when_last_altered_missing(self) -> None:
        payload = assets.base_asset_payload(_inventory_row())
        self.assertEqual(payload["updatedAt"], "")


class DiscoverySearchGapTests(unittest.TestCase):
    def test_search_payload_carries_updated_at(self) -> None:
        payload = assets.discovery_search_payload(
            _inventory_df(),
            query="orders",
            sort_by="Best match",
        )
        self.assertEqual(payload["count"], 1)
        asset = payload["assets"][0]
        self.assertTrue(str(asset.get("updatedAt", "")).startswith("2026-07-01"))
        # The placeholder sentence must never come from the API.
        self.assertNotIn("No description has been captured", str(asset.get("description")))


class _WorkbenchStoreBase:
    """Minimal governance store for workbench payload tests."""

    def __init__(self, rows):
        self._rows = rows

    def list_change_requests(self, status=None, limit=200):
        df = pd.DataFrame(self._rows)
        if status and not df.empty:
            return df[df["status"].eq(status)].copy()
        return df

    def list_metadata_audit(self, **_):
        return pd.DataFrame()


class RequestRecordGapTests(unittest.TestCase):
    def test_placeholder_title_synthesized_from_tag_diff(self) -> None:
        record = axiom_metrics._request_record(
            {
                "request_id": "REQ-TAGS",
                "created_at": "2026-07-18 01:00:00",
                "created_by": "abarreto@shorecp.com",
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "Governance request",
                "new_uc_tags_json": '{"domain": "Finance"}',
            }
        )
        self.assertEqual(record["title"], "Tag change: orders")

    def test_placeholder_title_with_description_content(self) -> None:
        record = axiom_metrics._request_record(
            {
                "request_id": "REQ-DESC",
                "created_at": "2026-07-18 01:00:00",
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "",
                "new_uc_tags_json": "{}",
                "title": "Governance request",
            }
        )
        self.assertEqual(record["title"], "Governance review: orders")

    def test_title_priority_due_assignee_read_from_new_uc_tags(self) -> None:
        record = axiom_metrics._request_record(
            {
                "request_id": "REQ-META",
                "created_at": "2026-07-18 01:00:00",
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "Governance request",
                "new_uc_tags_json": (
                    '{"title": "Review PII exposure", "priority": "P1",'
                    ' "assignedTo": "governance-team", "dueAt": "2026-08-01T00:00:00Z"}'
                ),
            }
        )
        self.assertEqual(record["title"], "Review PII exposure")
        self.assertEqual(record["priority"], "P1")
        self.assertEqual(record["assignedTo"], "governance-team")
        self.assertEqual(record["dueAt"], "2026-08-01T00:00:00Z")
        # An explicit due date means no derived default-policy SLA.
        self.assertEqual(record["slaPolicy"], "")

    def test_default_7d_sla_derived_from_created_at(self) -> None:
        old_created = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        ).strftime("%Y-%m-%d %H:%M:%S")
        record = axiom_metrics._request_record(
            {
                "request_id": "REQ-OLD",
                "created_at": old_created,
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "Assign owner: needs review",
            }
        )
        self.assertEqual(record["slaPolicy"], "default_7d")
        self.assertTrue(record["dueAt"])
        self.assertEqual(record["slaState"], "overdue")
        self.assertIn("7d default", record["sla"])

    def test_no_sla_fabricated_without_created_at(self) -> None:
        record = axiom_metrics._request_record(
            {
                "request_id": "REQ-NOTS",
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "Assign owner: needs review",
            }
        )
        self.assertEqual(record["dueAt"], "")
        self.assertEqual(record["sla"], "")
        self.assertEqual(record["slaState"], "")


class WorkbenchMetricsGapTests(unittest.TestCase):
    def _store(self):
        now = dt.datetime.now(dt.timezone.utc)
        old = (now - dt.timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        fresh = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        resolved_created = (now - dt.timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        resolved_reviewed = (now - dt.timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        return _WorkbenchStoreBase(
            [
                {
                    "request_id": "REQ-OVERDUE",
                    "created_at": old,
                    "created_by": "abarreto@shorecp.com",
                    "status": "pending",
                    "uc_full_name": "main.finance.orders",
                    "new_comment": "Assign owner: needs review",
                },
                {
                    "request_id": "REQ-FRESH",
                    "created_at": fresh,
                    "created_by": "abarreto@shorecp.com",
                    "status": "pending",
                    "uc_full_name": "main.finance.invoices",
                    "new_comment": "Certify: ready for review",
                },
                {
                    "request_id": "REQ-DONE",
                    "created_at": resolved_created,
                    "created_by": "abarreto@shorecp.com",
                    "status": "approved",
                    "uc_full_name": "main.finance.orders",
                    "new_comment": "Update description: done",
                    "reviewed_at": resolved_reviewed,
                    "reviewed_by": "steward@shorecp.com",
                },
            ]
        )

    def test_overdue_items_metric_computed_from_default_sla(self) -> None:
        payload = axiom_metrics.governance_workbench_payload(store=self._store())
        overdue = next(m for m in payload["metrics"] if m["key"] == "overdueItems")
        self.assertEqual(overdue["state"], "available")
        self.assertEqual(overdue["value"], 1)
        self.assertIn("7-day", overdue["reason"])

    def test_sla_performance_metric_median_resolution(self) -> None:
        payload = axiom_metrics.governance_workbench_payload(store=self._store())
        sla = next(m for m in payload["metrics"] if m["key"] == "slaPerformance")
        self.assertEqual(sla["state"], "available")
        # 10d -> 8d ago is a 48h resolution window.
        self.assertAlmostEqual(sla["medianResolutionHours"], 48.0, delta=1.0)
        self.assertIn("reviewed_at", sla["reason"])

    def test_sla_performance_unavailable_without_resolved_requests(self) -> None:
        store = _WorkbenchStoreBase(
            [
                {
                    "request_id": "REQ-1",
                    "created_at": "2026-07-18 01:00:00",
                    "status": "pending",
                    "uc_full_name": "main.finance.orders",
                    "new_comment": "Assign owner: needs review",
                }
            ]
        )
        payload = axiom_metrics.governance_workbench_payload(store=store)
        sla = next(m for m in payload["metrics"] if m["key"] == "slaPerformance")
        self.assertEqual(sla["state"], "unavailable")
        self.assertIsNone(sla["value"])


class RequestDetailCommentGapTests(unittest.TestCase):
    class _DetailStore(_WorkbenchStoreBase):
        def get_change_request(self, request_id):
            if request_id != "REQ-COMMENTED":
                return None
            return {
                "request_id": "REQ-COMMENTED",
                "created_at": "2026-07-10 01:00:00",
                "created_by": "abarreto@shorecp.com",
                "status": "pending",
                "uc_full_name": "main.finance.orders",
                "new_comment": "description: Curated orders",
                "new_uc_tags": {"domain": "Finance"},
                "reviewed_at": "2026-07-11 02:00:00",
                "reviewed_by": "steward@shorecp.com",
                "review_note": "Looks good, expanding scope.",
            }

        def list_metadata_audit(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "audit_id": "AUD-REQ",
                        "entity_fqn": "main.finance.orders",
                        "action": "request_commented",
                        "detail": "Comment recorded on REQ-COMMENTED",
                        "created_at": "2026-07-12 03:00:00",
                        "actor_email": "steward@shorecp.com",
                    },
                    {
                        "audit_id": "AUD-OTHER",
                        "entity_fqn": "main.finance.orders",
                        "action": "metadata updated",
                        "detail": "Unrelated owner change",
                        "created_at": "2026-07-12 04:00:00",
                        "actor_email": "someone@shorecp.com",
                    },
                ]
            )

    def test_comments_backed_by_review_note_and_request_audit_events(self) -> None:
        store = self._DetailStore([])
        payload = axiom_metrics.governance_request_detail_payload(
            store=store,
            request_id="REQ-COMMENTED",
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["commentsState"], "available")
        texts = [comment["text"] for comment in payload["comments"]]
        self.assertIn("Looks good, expanding scope.", texts)
        self.assertIn("Comment recorded on REQ-COMMENTED", texts)
        # Audit rows that never reference the request stay out.
        self.assertNotIn("Unrelated owner change", texts)
        # Diff rows still present for the opening-evidence rendering.
        fields = {row["field"] for row in payload["diff"]["rows"]}
        self.assertIn("domain", fields)


if __name__ == "__main__":
    unittest.main()
