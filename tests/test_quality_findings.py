"""Wave A4 — contract tests for GET /api/quality/findings and its service.

Follows the tests/test_axiom_api.py patterns: SimpleNamespace requests,
runtime_app patch.multiple, honest-envelope assertions.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.api import catalog as catalog_api
from axiom.services import quality as quality_service


def _request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, state=SimpleNamespace())


def _response_json(response) -> dict:
    if hasattr(response, "body"):
        return json.loads(response.body.decode("utf-8"))
    return response.content


def _visible_assets() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"fqn": "main.customer.customer_dim"},
            {"fqn": "finance_prod.curated.revenue_daily"},
        ]
    )


_RESULT_ROWS = [
    {
        "result_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "run_id": "run-1",
        "case_id": "GOV-QUALITY-EVIDENCE-case-customer-profile-minimum-rows",
        "entity_fqn": "main.customer.customer_dim",
        "column_name": "customer_id",
        "outcome": "failed",
        "severity": "critical",
        "metric_value": 0.0,
        "threshold_value": 1.0,
        "evidence_json": None,
        "statement_id": None,
        "row_bytes_scanned": None,
        "executed_at": "2026-07-20 10:00:00",
        "detail": "row count 0 below minimum 1",
    },
    {
        "result_id": "ffe2c3d4e5f60718293a4b5c6d7e8f91",
        "run_id": "run-1",
        "case_id": "case-two",
        "entity_fqn": "main.customer.customer_dim",
        "column_name": None,
        "outcome": "passed",
        "severity": "info",
        "metric_value": 5.0,
        "threshold_value": 1.0,
        "evidence_json": None,
        "statement_id": None,
        "row_bytes_scanned": None,
        "executed_at": "2026-07-20 10:00:05",
        "detail": "",
    },
    {
        # Row about an asset OUTSIDE the visible scope — must be withheld.
        "result_id": "0102030405060708090a0b0c0d0e0f10",
        "run_id": "run-2",
        "case_id": "case-hidden",
        "entity_fqn": "restricted.payroll.salary_raw",
        "column_name": None,
        "outcome": "failed",
        "severity": "warn",
        "metric_value": None,
        "threshold_value": None,
        "evidence_json": None,
        "statement_id": None,
        "row_bytes_scanned": None,
        "executed_at": "2026-07-19 09:00:00",
        "detail": "hidden asset failure",
    },
]


class FindingsStore:
    def list_quality_run_results(
        self, *, entity_fqn: str | None = None, run_id: str | None = None, limit: int = 200
    ) -> pd.DataFrame:
        rows = _RESULT_ROWS
        if entity_fqn:
            rows = [row for row in rows if row["entity_fqn"] == entity_fqn]
        return pd.DataFrame(rows[: int(limit)])

    def list_quality_runs(
        self, *, entity_fqn: str | None = None, suite_id: str | None = None, limit: int = 50
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "run_id": "run-1",
                    "suite_id": "suite-1",
                    "trigger": "manual",
                    "status": "partial",
                    "started_at": "2026-07-20 09:59:00",
                    "finished_at": "2026-07-20 10:00:10",
                    "row_budget": None,
                    "summary_json": json.dumps({"passed": 1, "failed": 1}),
                }
            ]
        )

    def list_quality_check_names(self, *, case_ids) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "case_id": "GOV-QUALITY-EVIDENCE-case-customer-profile-minimum-rows",
                    "display_name": "Customer profile coverage has source records",
                    "test_key": "row_count",
                }
            ]
        )


class EmptyStore(FindingsStore):
    def list_quality_run_results(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame()


class QualityFindingsServiceTests(unittest.TestCase):
    def test_findings_join_run_metadata_and_check_names(self) -> None:
        payload = quality_service.quality_findings(
            FindingsStore(),
            visible_asset_fqns=["main.customer.customer_dim"],
        )
        self.assertEqual(payload["state"], "available")
        self.assertEqual(len(payload["findings"]), 2)
        first = payload["findings"][0]
        # UTC Z timestamps, never naive strings.
        self.assertTrue(first["executedAt"].endswith("Z"))
        self.assertEqual(first["runId"], "run-1")
        self.assertEqual(first["run"]["trigger"], "manual")
        self.assertEqual(first["run"]["status"], "partial")
        # Curated definition name when the join has one.
        named = next(
            f for f in payload["findings"]
            if f["caseId"] == "GOV-QUALITY-EVIDENCE-case-customer-profile-minimum-rows"
        )
        self.assertEqual(named["checkName"], "Customer profile coverage has source records")
        self.assertEqual(named["checkNameSource"], "definition")
        self.assertEqual(named["severityLevel"], "high")
        self.assertEqual(named["message"], "row count 0 below minimum 1")
        # Fallback name derives from the case id and says so.
        fallback = next(f for f in payload["findings"] if f["caseId"] == "case-two")
        self.assertEqual(fallback["checkNameSource"], "case-id")
        self.assertEqual(fallback["checkName"], "Case Two")

    def test_finding_ids_are_stable_and_never_positional(self) -> None:
        first = quality_service.quality_findings(
            FindingsStore(), visible_asset_fqns=["main.customer.customer_dim"]
        )
        # Same finding keeps the same id when the filter window changes.
        second = quality_service.quality_findings(
            FindingsStore(),
            outcome="failed",
            visible_asset_fqns=["main.customer.customer_dim"],
        )
        target_case = "GOV-QUALITY-EVIDENCE-case-customer-profile-minimum-rows"
        id_first = next(f["findingId"] for f in first["findings"] if f["caseId"] == target_case)
        id_second = next(f["findingId"] for f in second["findings"] if f["caseId"] == target_case)
        self.assertEqual(id_first, id_second)
        self.assertTrue(id_first.startswith("QF-"))
        self.assertEqual(id_first, "QF-A1B2C3D4")

    def test_visibility_scoping_withholds_and_counts_hidden_rows(self) -> None:
        payload = quality_service.quality_findings(
            FindingsStore(),
            visible_asset_fqns=["main.customer.customer_dim"],
        )
        self.assertEqual(payload["visibilityScopedRowsExcluded"], 1)
        self.assertNotIn("restricted.payroll.salary_raw", json.dumps(payload))

    def test_severity_filter_accepts_raw_and_bucket_forms(self) -> None:
        raw = quality_service.quality_findings(
            FindingsStore(),
            severity="critical",
            visible_asset_fqns=["main.customer.customer_dim"],
        )
        bucket = quality_service.quality_findings(
            FindingsStore(),
            severity="high",
            visible_asset_fqns=["main.customer.customer_dim"],
        )
        self.assertEqual(len(raw["findings"]), 1)
        self.assertEqual(len(bucket["findings"]), 1)
        self.assertEqual(
            raw["findings"][0]["findingId"], bucket["findings"][0]["findingId"]
        )

    def test_failing_outcome_filter_matches_failed_and_errored(self) -> None:
        # The risk-drill deep link uses outcome=failing so the Evidence total
        # reconciles with the Command Center severity tiles, which count
        # failed+errored. A local ledger with one of each outcome proves the
        # filter keeps failed AND errored while dropping passed/skipped.
        rows = [
            {**_RESULT_ROWS[0], "result_id": "aa" * 16, "outcome": "failed"},
            {**_RESULT_ROWS[0], "result_id": "bb" * 16, "outcome": "errored"},
            {**_RESULT_ROWS[0], "result_id": "cc" * 16, "outcome": "passed"},
            {**_RESULT_ROWS[0], "result_id": "dd" * 16, "outcome": "skipped"},
        ]

        class MixedStore(FindingsStore):
            def list_quality_run_results(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(rows)

        failing = quality_service.quality_findings(
            MixedStore(), outcome="failing", visible_asset_fqns=None
        )
        outcomes = sorted(f["outcome"] for f in failing["findings"])
        self.assertEqual(outcomes, ["errored", "failed"])
        self.assertEqual(failing["summary"]["total"], 2)

    def test_since_until_window_filters_on_executed_at(self) -> None:
        payload = quality_service.quality_findings(
            FindingsStore(),
            since="2026-07-20T00:00:00Z",
            until="2026-07-20T10:00:02Z",
            visible_asset_fqns=None,
        )
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(payload["findings"][0]["outcome"], "failed")

    def test_empty_ledger_is_honest_unavailable_not_zero_rows(self) -> None:
        payload = quality_service.quality_findings(EmptyStore())
        self.assertEqual(payload["state"], "unavailable")
        self.assertIn("No quality checks have run yet", payload["reason"])
        self.assertEqual(payload["findings"], [])

    def test_store_without_ledger_method_degrades_honestly(self) -> None:
        payload = quality_service.quality_findings(SimpleNamespace())
        self.assertEqual(payload["state"], "unavailable")
        self.assertIn("not available", payload["reason"])

    def test_severity_buckets_match_quality_sla_signal(self) -> None:
        # One number per concept: the findings buckets and the SLA risk
        # breakdown must classify a severity identically.
        self.assertEqual(quality_service.normalize_severity_level("critical"), "high")
        self.assertEqual(quality_service.normalize_severity_level("error"), "high")
        self.assertEqual(quality_service.normalize_severity_level("blocker"), "high")
        self.assertEqual(quality_service.normalize_severity_level("info"), "informational")
        self.assertEqual(quality_service.normalize_severity_level("low"), "informational")
        self.assertEqual(quality_service.normalize_severity_level("warn"), "medium")
        self.assertEqual(quality_service.normalize_severity_level(""), "medium")

    def test_opaque_uuid_case_ids_are_not_prettified(self) -> None:
        # Fabricating a sentence out of hex noise would be fake data.
        self.assertEqual(
            quality_service._humanize_case_id("a1b2c3d4e5f60718293a4b5c"),
            "a1b2c3d4e5f60718293a4b5c",
        )


class QualityFindingsEndpointTests(unittest.TestCase):
    def _mocks(self, visible_assets_fn, store_fn):
        import runtime_app

        return patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _visible_assets=visible_assets_fn,
            _store_for_read=store_fn,
        )

    def test_route_registered_on_catalog_router(self) -> None:
        router = catalog_api.build_catalog_router()
        paths = {route.path for route in router.routes}
        self.assertIn("/api/quality/findings", paths)

    def test_findings_envelope_carries_meta_and_visibility_capabilities(self) -> None:
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["source"], "quality-runner+governance-store")
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertEqual(
            payload["meta"]["capabilities"]["rowLevelSecurity"], "visible-assets-only"
        )
        self.assertEqual(payload["meta"]["capabilities"]["visibleAssetCount"], 2)
        self.assertEqual(len(payload["findings"]), 2)
        self.assertEqual(payload["visibilityScopedRowsExcluded"], 1)
        self.assertNotIn("restricted.payroll.salary_raw", json.dumps(payload))

    def test_fails_closed_when_visibility_scope_unavailable(self) -> None:
        def _raise(request):
            raise RuntimeError("inventory unavailable")

        with self._mocks(_raise, lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(_request())

        self.assertEqual(response.status_code, 503)
        payload = _response_json(response)
        self.assertFalse(payload["authoritative"])
        self.assertEqual(
            payload["meta"]["capabilities"]["rowLevelSecurity"],
            "fail-closed-visible-assets",
        )
        self.assertIn("unavailable rather than exposing", payload["detail"])

    def test_out_of_scope_asset_filter_returns_honest_unavailable_200(self) -> None:
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(
                _request(), asset="restricted.payroll.salary_raw"
            )

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["state"], "unavailable")
        self.assertEqual(payload["findings"], [])
        self.assertIn("not visible", payload["reason"])

    def test_invalid_outcome_is_rejected(self) -> None:
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            with self.assertRaises(catalog_api.HTTPException) as ctx:
                catalog_api.api_quality_findings(_request(), outcome="exploded")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_failing_outcome_is_accepted_at_the_api_boundary(self) -> None:
        # Regression: the API allow-list rejected "failing" with 400 before the
        # service filter ran, so the risk-drill deep link (?outcome=failing)
        # 400'd instead of landing on the failed/errored findings.
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(_request(), outcome="failing")
        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertTrue(all(f["outcome"] in {"failed", "errored"} for f in payload["findings"]))

    def test_asset_and_outcome_filters_apply(self) -> None:
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(
                _request(),
                asset="main.customer.customer_dim",
                outcome="failed",
            )
        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(payload["findings"][0]["outcome"], "failed")
        self.assertEqual(payload["findings"][0]["assetFqn"], "main.customer.customer_dim")

    def test_limit_is_capped_at_500(self) -> None:
        with self._mocks(lambda request: _visible_assets(), lambda: FindingsStore()):
            response = catalog_api.api_quality_findings(_request(), limit=99999)
        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["meta"]["capabilities"]["maxLimit"], 500)


if __name__ == "__main__":
    unittest.main()
