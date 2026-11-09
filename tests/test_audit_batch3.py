"""Unit tests for the batch-3 features: G9 per-category trends, G8 board report,
G10 evidence-pack checksum/manifest."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

import pandas as pd

from axiom.services import axiom_metrics
from axiom.services import export as export_service


class CategoryTrendTests(unittest.TestCase):
    def test_snapshot_rows_from_domains_and_tiers(self):
        rows = axiom_metrics._category_snapshot_rows(
            [{"domain": "Risk", "label": "Risk", "score": 41.0, "assetCount": 5}],
            [{"tier": "critical", "label": "Critical", "value": 75.0, "total": 8}],
        )
        self.assertEqual(len(rows), 2)
        domain = next(r for r in rows if r["category_kind"] == "domain")
        tier = next(r for r in rows if r["category_kind"] == "tier")
        self.assertEqual(domain["category_key"], "Risk")
        self.assertEqual(domain["score"], 41.0)
        self.assertEqual(tier["certification_pct"], 75.0)
        self.assertIsNone(tier["coverage"])

    def test_trend_series_marks_young_history_collecting(self):
        class FakeStore:
            def list_governance_category_snapshots(self, *, scope_key, category_kind, limit=400):
                return pd.DataFrame(
                    [
                        {"snapshot_date": "2026-07-22", "category_kind": "domain", "category_key": "Risk", "category_label": "Risk", "asset_count": 5, "coverage": 38.0, "certification_pct": None, "score": 38.0},
                        {"snapshot_date": "2026-07-23", "category_kind": "domain", "category_key": "Risk", "category_label": "Risk", "asset_count": 5, "coverage": 41.0, "certification_pct": None, "score": 41.0},
                        {"snapshot_date": "2026-07-23", "category_kind": "domain", "category_key": "Finance", "category_label": "Finance", "asset_count": 12, "coverage": 88.0, "certification_pct": None, "score": 88.0},
                    ]
                )

        series = axiom_metrics._category_trend_series(FakeStore(), "app", "domain", "score")
        self.assertEqual(len(series), 2)
        risk = next(s for s in series if s["key"] == "Risk")
        finance = next(s for s in series if s["key"] == "Finance")
        # Worst-first ordering: Risk (41) before Finance (88).
        self.assertEqual(series[0]["key"], "Risk")
        self.assertTrue(risk["collecting"])  # only 2 points
        self.assertEqual(len(risk["points"]), 2)
        self.assertEqual(risk["delta"], 3.0)
        self.assertEqual(finance["latest"], 88.0)

    def test_trend_series_empty_when_no_snapshots(self):
        class EmptyStore:
            def list_governance_category_snapshots(self, **_kw):
                return pd.DataFrame()

        self.assertEqual(axiom_metrics._category_trend_series(EmptyStore(), "app", "domain", "score"), [])


class EvidencePackTests(unittest.TestCase):
    def test_content_sha256_is_deterministic(self):
        a = export_service.content_sha256("fqn,name\na,b\n")
        b = export_service.content_sha256("fqn,name\na,b\n")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, export_service.content_sha256("different"))

    def test_manifest_carries_hash_and_is_honestly_not_signed(self):
        manifest = export_service.build_provenance_manifest(
            job_id="j1", actor_email="a@b.ai", actor_role="admin",
            generated_at=datetime.now(timezone.utc), filter_snapshot='{"assetFqns":["x"]}',
            row_count=1, byte_count=10, sha256="deadbeef", data_filename="d.csv",
        )
        parsed = json.loads(manifest)
        self.assertEqual(parsed["integrity"]["contentSha256"], "deadbeef")
        self.assertEqual(parsed["integrity"]["algorithm"], "SHA-256")
        self.assertEqual(parsed["export"]["actorEmail"], "a@b.ai")
        # Must NOT overclaim cryptographic signing.
        self.assertIn("not cryptographically signed", manifest.lower())


class BoardReportTests(unittest.TestCase):
    def _report(self):
        cc = {
            "estate": {"estateLabel": "Data estate"},
            "posture": {"overall": 72, "state": "available", "reason": "weighted", "byDomain": [{"domain": "Risk", "label": "Risk", "score": 41, "assetCount": 5}]},
            "kpis": [
                {"key": "governedAssets", "label": "Governed assets", "value": 120},
                {"key": "policyExceptions", "label": "Policy exceptions", "value": None, "state": "unavailable", "reason": "No source configured."},
            ],
        }
        ins = {"certificationCoverageByTier": [{"tier": "critical", "label": "Critical", "value": 75, "certified": 6, "total": 8}], "recommendations": [{"title": "Certify 2 critical assets"}]}
        return export_service.build_board_report_html(
            command_center=cc, insights=ins, actor_email="a@b.ai",
            generated_at=datetime.now(timezone.utc), org_name="Shore Capital Partners",
        )

    def test_report_is_self_contained_html_with_real_values(self):
        html = self._report()
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("Shore Capital Partners", html)
        self.assertIn("Risk", html)
        self.assertIn("120", html)  # governed assets

    def test_report_carries_unavailable_labels_honestly(self):
        html = self._report()
        # policyExceptions is unavailable -> must be labeled, not shown as 0/blank.
        self.assertIn("Unavailable", html)
        self.assertIn("No source configured.", html)


if __name__ == "__main__":
    unittest.main()


class ExportRowConcurrencyTests(unittest.TestCase):
    """Follow-up: _build_rows fans per-asset detail across a thread pool. It must
    preserve selection order AND stay fail-closed (drop unopenable assets)."""

    def _run(self, fqns):
        import sys
        import types

        rt = types.ModuleType("runtime_app")
        rt._asset_is_openable = lambda fqn, request: "hidden" not in fqn
        rt._asset_detail_payload = lambda fqn, request=None, sections=None: {"fqn": fqn, "name": fqn.split(".")[-1]}
        saved = sys.modules.get("runtime_app")
        sys.modules["runtime_app"] = rt
        try:
            from axiom.api import export as export_api

            return [row["fqn"] for row in export_api._build_rows(fqns, request=None)]
        finally:
            if saved is not None:
                sys.modules["runtime_app"] = saved
            else:
                sys.modules.pop("runtime_app", None)

    def test_preserves_order_and_fails_closed_parallel(self):
        # >1 asset triggers the ThreadPoolExecutor path.
        fqns = [f"c.s.a{i}" for i in range(20)]
        fqns.insert(5, "c.s.hidden_secret")
        result = self._run(fqns)
        self.assertNotIn("c.s.hidden_secret", result)  # fail-closed
        self.assertEqual(result, [f"c.s.a{i}" for i in range(20)])  # order preserved

    def test_single_asset_serial_path(self):
        self.assertEqual(self._run(["c.s.only"]), ["c.s.only"])
        self.assertEqual(self._run(["c.s.hidden"]), [])
