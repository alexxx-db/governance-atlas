"""Regression tests for the Glossary & CDE "incomplete product" gap fixes.

Covers the backend halves of:
- G4/G13: `_cde_item` derives lastReview from real row timestamps, reports the
  real certification as status, and splits source-backing into its own signal.
- G5: `cde_dashboard_payload` computes sensitivityLabeledCdes/overdueReviews, and
  `api_cde_dashboard` only reports degraded when signals are genuinely missing.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.api import axiom as axiom_api
from axiom.api.cache import _invalidate_cache_prefix
from axiom.services import axiom_metrics


def _request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, state=SimpleNamespace())


def _response_json(response) -> dict:
    if hasattr(response, "body"):
        return json.loads(response.body.decode("utf-8"))
    return response.content


def _cde_row(**overrides) -> dict:
    row = {
        "fqn": "main.finance.revenue_daily",
        "table_catalog": "main",
        "table_schema": "finance",
        "table_name": "revenue_daily",
        "comment": "Critical data element",
        "domain": "Finance",
        "certification": "Certified",
        "sensitivity": "Confidential",
        "criticality": "Critical",
        "business_owner": "abarreto@shorecp.com",
        "tags": {"cde_source_column": "net_revenue_usd", "cde_recert_window": "90d"},
        "updated_at": "2026-07-01T00:00:00Z",
    }
    row.update(overrides)
    return row


class CdeItemTests(unittest.TestCase):
    def test_last_review_derives_from_updated_at(self) -> None:
        item = axiom_metrics._cde_item(_cde_row())
        self.assertEqual(item["lastReview"], "2026-07-01T00:00:00Z")
        self.assertEqual(item["lastReviewSource"], "asset-metadata")

    def test_last_review_unavailable_when_no_timestamp(self) -> None:
        item = axiom_metrics._cde_item(_cde_row(updated_at=""))
        self.assertEqual(item["lastReview"], "Unavailable")
        self.assertEqual(item["lastReviewSource"], "unavailable")

    def test_status_is_real_certification_not_source_backing(self) -> None:
        item = axiom_metrics._cde_item(_cde_row())
        self.assertEqual(item["status"], "Certified")
        self.assertTrue(item["sourceBacked"])
        self.assertEqual(item["sourceStatus"], "tagged")

    def test_unassigned_certification_reads_as_pending(self) -> None:
        item = axiom_metrics._cde_item(_cde_row(certification=""))
        self.assertEqual(item["status"], "Certification pending")

    def test_untagged_source_gets_actionable_copy(self) -> None:
        item = axiom_metrics._cde_item(_cde_row(tags={}))
        self.assertFalse(item["sourceBacked"])
        self.assertEqual(item["sourceStatus"], "untagged")
        self.assertIn("cde_source_column", item["healthEvidence"])

    def test_recert_window_parser_is_conservative(self) -> None:
        self.assertEqual(axiom_metrics._recert_window_days("90d"), 90)
        self.assertEqual(axiom_metrics._recert_window_days("180"), 180)
        self.assertEqual(axiom_metrics._recert_window_days("6m"), 180)
        self.assertEqual(axiom_metrics._recert_window_days("1y"), 365)
        self.assertIsNone(axiom_metrics._recert_window_days("quarterly-ish"))
        self.assertIsNone(axiom_metrics._recert_window_days(""))


class CdeDashboardPayloadTests(unittest.TestCase):
    def test_protected_cdes_is_computed_not_none(self) -> None:
        payload = axiom_metrics.cde_dashboard_payload(
            visible_assets=pd.DataFrame([_cde_row()])
        )
        self.assertEqual(payload["summary"]["totalCdes"], 1)
        # Honest rename (persona audit): the old `protectedCdes` claimed
        # protection from a sensitivity label while every control category
        # was unavailable. The same count now ships as sensitivityLabeledCdes.
        self.assertEqual(payload["summary"]["sensitivityLabeledCdes"], 1)
        self.assertNotIn("protectedCdes", payload["summary"])
        self.assertEqual(
            payload["summary"]["sensitivityLabeledCdes"],
            payload["summary"]["sensitiveCandidates"],
        )

    def test_internal_sensitivity_is_not_protected(self) -> None:
        payload = axiom_metrics.cde_dashboard_payload(
            visible_assets=pd.DataFrame([_cde_row(sensitivity="Internal")])
        )
        self.assertEqual(payload["summary"]["sensitivityLabeledCdes"], 0)

    def test_overdue_reviews_counts_rows_with_both_signals(self) -> None:
        stale = _cde_row(updated_at="2020-01-01T00:00:00Z")
        payload = axiom_metrics.cde_dashboard_payload(visible_assets=pd.DataFrame([stale]))
        self.assertEqual(payload["summary"]["reviewsEvaluated"], 1)
        self.assertEqual(payload["summary"]["overdueReviews"], 1)

    def test_overdue_reviews_none_when_signals_missing(self) -> None:
        # No recert window tag and no timestamp: the signal is genuinely
        # missing and must be None, never a fabricated 0.
        row = _cde_row(tags={"cde_source_column": "net_revenue_usd"}, updated_at="")
        payload = axiom_metrics.cde_dashboard_payload(visible_assets=pd.DataFrame([row]))
        self.assertIsNone(payload["summary"]["overdueReviews"])
        self.assertEqual(payload["summary"]["reviewsEvaluated"], 0)

    def test_fresh_review_is_not_overdue(self) -> None:
        fresh = _cde_row(updated_at=pd.Timestamp.now(tz="UTC").isoformat())
        payload = axiom_metrics.cde_dashboard_payload(visible_assets=pd.DataFrame([fresh]))
        self.assertEqual(payload["summary"]["overdueReviews"], 0)


class CdeDashboardRouteStateTests(unittest.TestCase):
    def setUp(self) -> None:
        _invalidate_cache_prefix("axiom_cde_dashboard_payload:")

    def _dashboard(self, assets: pd.DataFrame) -> dict:
        import runtime_app

        # Present actor-scoped OBO headers so the envelope layer's global
        # "app-principal metadata" downgrade doesn't mask the route's own
        # state decision (which is what these tests assert).
        request = _request(
            {
                "x-forwarded-email": "abarreto@shorecp.com",
                "x-forwarded-access-token": "obo-token",
            }
        )
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _cached_visible_assets=lambda request: assets,
            _visible_assets=lambda request: assets,
        ):
            response = axiom_api.api_cde_dashboard(request)
        self.assertEqual(response.status_code, 200)
        return _response_json(response)

    def test_backed_items_report_available_with_partial_warnings(self) -> None:
        dashboard = self._dashboard(pd.DataFrame([_cde_row()]))
        self.assertEqual(dashboard["meta"]["state"], "available")
        self.assertTrue(dashboard["meta"]["authoritative"])
        # Control coverage is still genuinely partial and must stay declared.
        self.assertFalse(dashboard["meta"]["capabilities"]["controlCoverage"])
        self.assertTrue(
            any("control coverage" in warning.lower() for warning in dashboard["meta"]["warnings"])
        )
        self.assertEqual(dashboard["summary"]["sensitivityLabeledCdes"], 1)

    def test_empty_registry_stays_degraded(self) -> None:
        dashboard = self._dashboard(pd.DataFrame())
        self.assertEqual(dashboard["meta"]["state"], "degraded")
        self.assertFalse(dashboard["meta"]["authoritative"])

    def test_missing_overdue_signal_is_named_in_warnings(self) -> None:
        row = _cde_row(tags={"cde_source_column": "net_revenue_usd"}, updated_at="")
        dashboard = self._dashboard(pd.DataFrame([row]))
        self.assertEqual(dashboard["meta"]["state"], "available")
        self.assertTrue(
            any("overdue-review" in warning.lower() for warning in dashboard["meta"]["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
