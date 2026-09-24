"""API-level tests for `/api/insights/gap-analysis`.

Verifies the endpoint returns the documented envelope: tiles block,
lanes block keyed by the four lane names, `lanesOrder` meta, and a
`meta.state` of either `available` (quality ledger present) or
`degraded` (ledger unavailable).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from atlas.api import insights as insights_api


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={}, state=SimpleNamespace())


def _inv_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "main.sales.alpha",
                "table_catalog": "main",
                "table_schema": "sales",
                "table_name": "alpha",
                "table_type": "TABLE",
                "data_source_format": "DELTA",
                "sensitivity": "Internal",
                "certification": "Gold",
                "domain": "Sales",
                "tier": "T1",
                "business_owner": "",
                "technical_owner": "",
                "steward": "",
                "last_observed_at": NOW.isoformat().replace("+00:00", "Z"),
            },
            {
                "fqn": "main.sales.beta",
                "table_catalog": "main",
                "table_schema": "sales",
                "table_name": "beta",
                "table_type": "TABLE",
                "data_source_format": "DELTA",
                "sensitivity": "",
                "certification": "",
                "domain": "",
                "tier": "",
                "business_owner": "eng@example.com",
                "technical_owner": "",
                "steward": "",
                "last_observed_at": (NOW - timedelta(days=30)).isoformat().replace(
                    "+00:00", "Z"
                ),
            },
        ]
    )


def _quality_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "result_id": "r1",
                "run_id": "run-1",
                "case_id": "row_count_minimum",
                "entity_fqn": "main.sales.alpha",
                "outcome": "failed",
                "severity": "warn",
                "detail": "row count 0 below minimum 1000",
                "executed_at": (NOW - timedelta(days=1)).isoformat().replace(
                    "+00:00", "Z"
                ),
            }
        ]
    )


class FakeStore:
    def __init__(self, quality_df: pd.DataFrame | None) -> None:
        self._quality_df = quality_df

    def list_quality_run_results(self, *, limit: int = 200) -> pd.DataFrame:
        if self._quality_df is None:
            raise RuntimeError("quality ledger unavailable")
        return self._quality_df


def _response_json(response) -> dict:
    body = getattr(response, "body", None)
    if body is None:
        return response.content
    return json.loads(body.decode("utf-8"))


class InsightsGapAnalysisApiTests(unittest.TestCase):
    def test_envelope_shape_when_quality_available(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _visible_assets=lambda request: _inv_frame(),
            _store_for_read=lambda: FakeStore(_quality_frame()),
            _uc_for_request=lambda request: SimpleNamespace(
                runtime_context=lambda: {}
            ),
            _request_cache_scope=lambda request: "test-actor|obo-available",
        ):
            response = insights_api.api_insights_gap_analysis(_request(), limit=50)
        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)

        # Tile shape
        self.assertIn("tiles", payload)
        tiles = payload["tiles"]
        for key in (
            "ownershipGaps",
            "policyGaps",
            "freshnessGaps",
            "qualityIncidents",
            "totalAssets",
        ):
            self.assertIn(key, tiles)
            self.assertIsInstance(tiles[key], int)

        # Lane shape
        self.assertIn("lanes", payload)
        lanes = payload["lanes"]
        self.assertEqual(
            set(lanes.keys()),
            {"ownership", "policy", "freshness", "quality"},
        )

        # Quality incident landed on main.sales.alpha
        quality_rows = lanes["quality"]
        self.assertEqual(len(quality_rows), 1)
        self.assertEqual(quality_rows[0]["assetFqn"], "main.sales.alpha")
        self.assertEqual(quality_rows[0]["remediation"]["label"], "View quality incident")
        self.assertTrue(
            quality_rows[0]["remediation"]["href"].startswith(
                "/governance?lane=quality&asset="
            )
        )

        # Envelope meta — quality ledger present yields a non-unavailable
        # state. (_response_meta downgrades unity-catalog sources to
        # "degraded" when the request isn't OBO-authenticated, which is
        # expected for a bare SimpleNamespace request in tests.)
        self.assertIn("meta", payload)
        self.assertIn(payload["meta"]["state"], {"available", "degraded"})
        self.assertNotEqual(payload["meta"]["state"], "unavailable")
        self.assertEqual(
            payload["meta"]["capabilities"].get("qualityLedger"), True
        )
        self.assertIn(
            "lanesOrder",
            payload,
            msg="envelope must expose lane order for stable UI tabs",
        )
        self.assertEqual(
            payload["lanesOrder"], ["ownership", "policy", "freshness", "quality"]
        )

    def test_envelope_degrades_when_quality_ledger_unavailable(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _visible_assets=lambda request: _inv_frame(),
            _store_for_read=lambda: FakeStore(None),
            _uc_for_request=lambda request: SimpleNamespace(
                runtime_context=lambda: {}
            ),
            _request_cache_scope=lambda request: "test-actor|obo-available",
        ):
            response = insights_api.api_insights_gap_analysis(_request(), limit=25)
        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        # When the quality ledger fails, the envelope must flag the
        # degraded contract via `qualityLedger=False` and a
        # non-available state. Actual state may be "degraded" either
        # from our explicit signal or from the non-OBO scope warning.
        self.assertNotEqual(payload["meta"]["state"], "available")
        self.assertEqual(
            payload["meta"]["capabilities"].get("qualityLedger"), False
        )
        # Quality lane is empty because the ledger couldn't be read
        self.assertEqual(payload["lanes"]["quality"], [])
        # But ownership / policy / freshness still evaluate
        self.assertEqual(payload["tiles"]["policyGaps"], 1)

    def test_envelope_never_reports_app_principal_fallback(self) -> None:
        """Per-user reads can no longer fall back to the app principal, so the
        envelope carries no fallback markers and stays authoritative."""

        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _visible_assets=lambda request: _inv_frame(),
            _store_for_read=lambda: FakeStore(_quality_frame()),
            _request_cache_scope=lambda request: "test-actor|obo-available",
        ):
            response = insights_api.api_insights_gap_analysis(_request(), limit=25)
        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertNotIn("oboScopeFallback", payload["meta"])
        self.assertNotIn("oboFallbackReason", payload["meta"])

    def test_router_registers_expected_route(self) -> None:
        router = insights_api.build_insights_router()
        paths = {route.path for route in router.routes}
        self.assertIn("/api/insights/gap-analysis", paths)


if __name__ == "__main__":
    unittest.main()
