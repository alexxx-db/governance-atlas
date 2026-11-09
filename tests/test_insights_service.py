"""Unit tests for `axiom.services.insights.compute_gap_analysis`.

These tests pin the four-lane contract the A9.5 insights surface depends
on. The service must:
  - Count ownership gaps (zero entries from asset_service.owner_entries).
  - Count policy gaps (all four policy fields blank/Unassigned).
  - Count freshness gaps (no recent last_observed_at AND no recent
    freshness quality-run pass).
  - Count quality incidents (failed/errored quality_run_result rows in
    the last 7 days).
  - Honor the `limit` cap on per-lane row output while still reporting
    true tile totals.
  - Produce deep-link remediation hrefs to /governance?lane=...&asset=...
  - Degrade gracefully on empty / None inputs.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import pandas as pd

from axiom.services import insights as insights_service


NOW = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)


def _make_inv_row(
    *,
    fqn: str,
    name: str = "",
    catalog: str = "main",
    schema: str = "sales",
    table_type: str = "TABLE",
    data_source_format: str = "DELTA",
    sensitivity: str = "",
    certification: str = "",
    domain: str = "",
    tier: str = "",
    business_owner: str = "",
    technical_owner: str = "",
    steward: str = "",
    last_observed_at: object = None,
) -> dict:
    parts = fqn.split(".")
    table_name = name or (parts[-1] if parts else fqn)
    return {
        "fqn": fqn,
        "table_catalog": catalog,
        "table_schema": schema,
        "table_name": table_name,
        "table_type": table_type,
        "data_source_format": data_source_format,
        "sensitivity": sensitivity,
        "certification": certification,
        "domain": domain,
        "tier": tier,
        "business_owner": business_owner,
        "technical_owner": technical_owner,
        "steward": steward,
        "last_observed_at": last_observed_at,
    }


def _make_inv_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _make_quality_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class ComputeGapAnalysisTests(unittest.TestCase):
    def test_empty_inventory_returns_zero_tiles_and_empty_lanes(self) -> None:
        result = insights_service.compute_gap_analysis(None, None, now=NOW)
        self.assertEqual(
            result["tiles"],
            {
                "ownershipGaps": 0,
                "policyGaps": 0,
                "freshnessGaps": 0,
                "qualityIncidents": 0,
                "totalAssets": 0,
            },
        )
        self.assertEqual(
            set(result["lanes"].keys()),
            {"ownership", "policy", "freshness", "quality"},
        )
        for lane_rows in result["lanes"].values():
            self.assertEqual(lane_rows, [])

    def test_ownership_gap_detected_when_no_owner_entries(self) -> None:
        rows = [
            _make_inv_row(
                fqn="main.sales.orders",
                sensitivity="Internal",
                certification="Gold",
                domain="Sales",
                tier="T1",
                business_owner="alice@example.com",
                last_observed_at=NOW.isoformat().replace("+00:00", "Z"),
            ),
            _make_inv_row(
                fqn="main.sales.returns",
                sensitivity="Internal",
                certification="Gold",
                domain="Sales",
                tier="T2",
                last_observed_at=NOW.isoformat().replace("+00:00", "Z"),
            ),
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(rows), None, now=NOW
        )
        self.assertEqual(result["tiles"]["ownershipGaps"], 1)
        self.assertEqual(result["tiles"]["totalAssets"], 2)
        ownership_rows = result["lanes"]["ownership"]
        self.assertEqual(len(ownership_rows), 1)
        gap = ownership_rows[0]
        self.assertEqual(gap["assetFqn"], "main.sales.returns")
        self.assertEqual(gap["gapKind"], "ownership")
        self.assertIn("owner", gap["gapReason"].lower())
        self.assertEqual(gap["remediation"]["label"], "Assign owner")
        self.assertEqual(
            gap["remediation"]["href"],
            "/governance?lane=ownership&asset=main.sales.returns",
        )

    def test_policy_gap_requires_all_four_fields_blank(self) -> None:
        rows = [
            # All four blank → policy gap
            _make_inv_row(
                fqn="main.raw.bronze_sessions",
                business_owner="eng@example.com",
            ),
            # Only three blank (tier set) → NOT a policy gap
            _make_inv_row(
                fqn="main.raw.bronze_events",
                tier="T3",
                business_owner="eng@example.com",
            ),
            # Unassigned literal counts as blank
            _make_inv_row(
                fqn="main.raw.bronze_clicks",
                sensitivity="Unassigned",
                certification="Unassigned",
                domain="Unassigned",
                tier="Unassigned",
                business_owner="eng@example.com",
            ),
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(rows), None, now=NOW
        )
        self.assertEqual(result["tiles"]["policyGaps"], 2)
        fqns = {r["assetFqn"] for r in result["lanes"]["policy"]}
        self.assertEqual(
            fqns, {"main.raw.bronze_sessions", "main.raw.bronze_clicks"}
        )
        # Reason must enumerate the missing fields
        reasons = [r["gapReason"] for r in result["lanes"]["policy"]]
        for reason in reasons:
            self.assertIn("sensitivity", reason)
            self.assertIn("domain", reason)

    def test_freshness_gap_reported_when_no_last_observed_at(self) -> None:
        rows = [
            _make_inv_row(
                fqn="main.sales.daily_roll",
                sensitivity="Internal",
                certification="Gold",
                domain="Sales",
                tier="T1",
                business_owner="alice@example.com",
                last_observed_at=None,
            ),
            _make_inv_row(
                fqn="main.sales.recent_roll",
                sensitivity="Internal",
                certification="Gold",
                domain="Sales",
                tier="T1",
                business_owner="alice@example.com",
                last_observed_at=(NOW - timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
            ),
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(rows), None, now=NOW
        )
        self.assertEqual(result["tiles"]["freshnessGaps"], 1)
        freshness_rows = result["lanes"]["freshness"]
        self.assertEqual(len(freshness_rows), 1)
        self.assertEqual(freshness_rows[0]["assetFqn"], "main.sales.daily_roll")
        self.assertEqual(freshness_rows[0]["gapKind"], "freshness")

    def test_freshness_fallback_uses_recent_quality_pass(self) -> None:
        # Row has no last_observed_at, but the quality ledger has a
        # passed freshness run inside the window → not a gap.
        inv_row = _make_inv_row(
            fqn="main.sales.kept_fresh",
            sensitivity="Internal",
            certification="Gold",
            domain="Sales",
            tier="T1",
            business_owner="alice@example.com",
            last_observed_at=None,
        )
        # Drop the column entirely so the frame has no freshness hint
        inv_row.pop("last_observed_at")
        quality_rows = [
            {
                "result_id": "r1",
                "run_id": "run-1",
                "case_id": "daily_freshness_watermark",
                "entity_fqn": "main.sales.kept_fresh",
                "outcome": "passed",
                "severity": "warn",
                "detail": "",
                "executed_at": (NOW - timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df([inv_row]),
            _make_quality_df(quality_rows),
            now=NOW,
        )
        self.assertEqual(result["tiles"]["freshnessGaps"], 0)
        self.assertEqual(result["lanes"]["freshness"], [])

    def test_quality_incident_counts_failed_and_errored_in_window(self) -> None:
        inv_rows = [
            _make_inv_row(
                fqn="main.sales.nightly_job",
                sensitivity="Internal",
                certification="Gold",
                domain="Sales",
                tier="T1",
                business_owner="alice@example.com",
                last_observed_at=(NOW - timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
            )
        ]
        quality_rows = [
            {
                "result_id": "r-fail",
                "run_id": "run-1",
                "case_id": "row_count_minimum",
                "entity_fqn": "main.sales.nightly_job",
                "outcome": "failed",
                "severity": "warn",
                "detail": "row count 0 below minimum 1000",
                "executed_at": (NOW - timedelta(days=2)).isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            {
                "result_id": "r-err",
                "run_id": "run-2",
                "case_id": "null_count_check",
                "entity_fqn": "main.sales.nightly_job",
                "outcome": "errored",
                "severity": "block",
                "detail": "connection refused",
                "executed_at": (NOW - timedelta(days=3)).isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            # out-of-window — must be ignored
            {
                "result_id": "r-old",
                "run_id": "run-3",
                "case_id": "old_case",
                "entity_fqn": "main.sales.nightly_job",
                "outcome": "failed",
                "severity": "warn",
                "detail": "old",
                "executed_at": (NOW - timedelta(days=90)).isoformat().replace(
                    "+00:00", "Z"
                ),
            },
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(inv_rows),
            _make_quality_df(quality_rows),
            now=NOW,
        )
        self.assertEqual(result["tiles"]["qualityIncidents"], 1)
        quality_rows_out = result["lanes"]["quality"]
        self.assertEqual(len(quality_rows_out), 1)
        gap = quality_rows_out[0]
        self.assertEqual(gap["assetFqn"], "main.sales.nightly_job")
        self.assertEqual(gap["gapKind"], "quality")
        self.assertEqual(gap["remediation"]["label"], "View quality incident")
        self.assertEqual(len(gap["evidence"]), 2)

    def test_limit_caps_rows_but_not_tile_counts(self) -> None:
        rows = [
            _make_inv_row(
                fqn=f"main.raw.asset_{i:03d}",
                business_owner="",
            )
            for i in range(25)
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(rows),
            None,
            limit=5,
            now=NOW,
        )
        # all 25 are both ownership gaps AND policy gaps
        self.assertEqual(result["tiles"]["ownershipGaps"], 25)
        self.assertEqual(result["tiles"]["policyGaps"], 25)
        self.assertLessEqual(len(result["lanes"]["ownership"]), 5)
        self.assertLessEqual(len(result["lanes"]["policy"]), 5)

    def test_remediation_href_encodes_special_chars(self) -> None:
        inv_row = _make_inv_row(
            fqn="main.sales.orders with space",
            business_owner="",
        )
        result = insights_service.compute_gap_analysis(
            _make_inv_df([inv_row]),
            None,
            now=NOW,
        )
        gap = result["lanes"]["ownership"][0]
        href = gap["remediation"]["href"]
        self.assertTrue(href.startswith("/governance?lane=ownership&asset="))
        # The asset segment should URL-encode the space
        self.assertIn("orders%20with%20space", href)
        # Sanity: decoding restores the original FQN
        _, _, encoded = href.partition("asset=")
        self.assertEqual(unquote(encoded), "main.sales.orders with space")

    def test_three_asset_fixture_reports_every_lane_once(self) -> None:
        # Asset A: ownership gap only.
        # Asset B: policy gap + freshness gap.
        # Asset C: quality incident only.
        inv_rows = [
            _make_inv_row(
                fqn="main.demo.alpha",
                sensitivity="Internal",
                certification="Gold",
                domain="Demo",
                tier="T1",
                business_owner="",
                last_observed_at=NOW.isoformat().replace("+00:00", "Z"),
            ),
            _make_inv_row(
                fqn="main.demo.beta",
                sensitivity="",
                certification="",
                domain="",
                tier="",
                business_owner="eng@example.com",
                last_observed_at=(NOW - timedelta(days=30)).isoformat().replace(
                    "+00:00", "Z"
                ),
            ),
            _make_inv_row(
                fqn="main.demo.gamma",
                sensitivity="Public",
                certification="Silver",
                domain="Demo",
                tier="T2",
                business_owner="eng@example.com",
                last_observed_at=(NOW - timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
            ),
        ]
        quality_rows = [
            {
                "result_id": "r1",
                "run_id": "run-1",
                "case_id": "row_count_minimum",
                "entity_fqn": "main.demo.gamma",
                "outcome": "failed",
                "severity": "warn",
                "detail": "row count 0 below minimum 1000",
                "executed_at": (NOW - timedelta(days=2)).isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        ]
        result = insights_service.compute_gap_analysis(
            _make_inv_df(inv_rows),
            _make_quality_df(quality_rows),
            now=NOW,
        )
        self.assertEqual(result["tiles"]["totalAssets"], 3)
        self.assertEqual(result["tiles"]["ownershipGaps"], 1)
        self.assertEqual(result["tiles"]["policyGaps"], 1)
        self.assertEqual(result["tiles"]["freshnessGaps"], 1)
        self.assertEqual(result["tiles"]["qualityIncidents"], 1)
        self.assertEqual(result["lanes"]["ownership"][0]["assetFqn"], "main.demo.alpha")
        self.assertEqual(result["lanes"]["policy"][0]["assetFqn"], "main.demo.beta")
        self.assertEqual(result["lanes"]["freshness"][0]["assetFqn"], "main.demo.beta")
        self.assertEqual(result["lanes"]["quality"][0]["assetFqn"], "main.demo.gamma")


if __name__ == "__main__":
    unittest.main()
