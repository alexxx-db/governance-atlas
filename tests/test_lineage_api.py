from __future__ import annotations

import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import runtime_app
from axiom.api import lineage as lineage_api


def _response_json(response) -> dict[str, object]:
    return json.loads(response.body.decode("utf-8"))


class LineageApiTests(unittest.TestCase):
    def test_initial_profile_skips_visibility_probe_for_fast_first_paint(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-email": "analyst@example.com"},
            query_params={"profile": "initial"},
        )
        lineage_payload = {
            "fqn": "main.sales.orders",
            "profile": "initial",
            "graphs": {"data": {"nodes": [{"id": "focus", "assetFqn": "main.sales.orders"}], "edges": []}},
            "stats": {"progressive": {"fullProfileAvailable": True}},
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _lineage_payload=lambda asset_fqn, request=None: lineage_payload,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="test"),
            _request_cache_scope=lambda request: "analyst@example.com",
            _asset_visibility_record=lambda asset_fqn, request=None: (_ for _ in ()).throw(
                AssertionError("initial lineage shell must not block first paint on visibility probes")
            ),
        ):
            lineage_api.lineage_service._TTL_CACHE.clear()
            response = lineage_api.api_lineage("main.sales.orders", request)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        # Poll-termination fix: the shell reports "hydrating" (a genuine
        # in-progress state), never a hard-coded "loading", and is never
        # HTTP-cached — a cached loading body froze the poll loop forever.
        self.assertEqual(payload["meta"]["state"], "hydrating")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(payload["meta"]["capabilities"]["visibilityState"], "unverified")
        self.assertEqual(payload["meta"]["capabilities"]["lineageProfile"], "initial")

    def test_initial_profile_returns_warm_full_payload_with_terminal_state(self) -> None:
        # Poll-termination fix (audited P1): once the full build finished
        # warming, the initial-profile poll must observe a TERMINAL state
        # (available/degraded) with the full topology — not the shell.
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "token",
            },
            query_params={"profile": "initial"},
        )
        full_payload = {
            "fqn": "main.sales.orders",
            "profile": "full",
            "buildState": "ok",
            "buildWarnings": [],
            "graphs": {
                "data": {
                    "nodes": [
                        {"id": "source", "assetFqn": "main.sales.customers"},
                        {"id": "focus", "assetFqn": "main.sales.orders"},
                    ],
                    "edges": [{"source": "source", "target": "focus"}],
                    "meta": {},
                },
                "operational": {"nodes": [], "edges": [], "meta": {}},
            },
            "stats": {"progressive": {}},
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="test"),
            _request_cache_scope=lambda request: "analyst@example.com",
            _lineage_payload=lambda asset_fqn, request=None: (_ for _ in ()).throw(
                AssertionError("warm full cache must short-circuit the shell build")
            ),
        ):
            with patch.object(
                lineage_api.lineage_service,
                "cached_lineage_payload",
                return_value=full_payload,
            ):
                response = lineage_api.api_lineage("main.sales.orders", request)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertTrue(payload["meta"]["authoritative"])
        self.assertEqual(payload["meta"]["capabilities"]["lineageProfile"], "full")
        self.assertEqual(
            payload["meta"]["capabilities"]["requestedLineageProfile"], "initial"
        )
        self.assertEqual(len(payload["graphs"]["data"]["edges"]), 1)

    def test_app_principal_lineage_fails_closed_for_hidden_focus_asset(self) -> None:
        request = SimpleNamespace(headers={"x-forwarded-email": "analyst@example.com"})
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _lineage_payload=lambda asset_fqn, request=None: (_ for _ in ()).throw(
                AssertionError("hidden focus asset must not hydrate lineage payload")
            ),
            _asset_visibility_record=lambda asset_fqn, request=None: {
                "openable": False,
                "visibilityState": "hidden",
            },
        ):
            response = lineage_api.api_lineage("main.sales.orders", request)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(payload["meta"]["capabilities"]["visibilityState"], "hidden")

    def test_app_principal_lineage_for_open_asset_uses_degraded_envelope(self) -> None:
        request = SimpleNamespace(headers={"x-forwarded-email": "analyst@example.com"})
        lineage_payload = {
            "fqn": "main.sales.orders",
            "graphs": {
                "data": {
                    "nodes": [
                        {"id": "source", "assetFqn": "main.sales.customers"},
                        {"id": "focus", "assetFqn": "main.sales.orders"},
                    ],
                    "edges": [{"id": "source-focus", "source": "source", "target": "focus"}],
                    "meta": {},
                },
                "operational": {"nodes": [], "edges": [], "meta": {}},
            },
            "columnLineage": {"upstream": [], "downstream": [], "meta": {}},
            "stats": {"upstreamCount": 1, "downstreamCount": 0},
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _lineage_payload=lambda asset_fqn, request=None: lineage_payload,
            _asset_visibility_record=lambda asset_fqn, request=None: {
                "openable": True,
                "visibilityState": "visible",
            },
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="test"),
            _uc=lambda: SimpleNamespace(warehouse_id="test"),
            _request_cache_scope=lambda request: "test-scope",
        ):
            with patch.object(
                lineage_api.lineage_service,
                "cached_lineage_payload",
                return_value=lineage_payload,
            ):
                response = lineage_api.api_lineage("main.sales.orders", request)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["graphs"]["data"]["nodes"][0]["assetFqn"], "main.sales.customers")
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertFalse(payload["meta"]["authoritative"])
        self.assertEqual(payload["meta"]["visibilityScope"], "workspace-app-principal")
        self.assertTrue(
            any("workspace-scoped app-principal" in item for item in payload["meta"]["warnings"])
        )

    def test_visible_inventory_lineage_capability_opens_even_without_observed_edges(self) -> None:
        from axiom.services import capabilities as capability_service

        payload = capability_service.bootstrap_capabilities(
            actor_role="reader",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=12,
            available_catalog_count=2,
            observed_catalog_count=0,
        )

        self.assertEqual(payload["tableLineage"]["state"], "available")
        self.assertTrue(payload["tableLineage"]["available"])
        self.assertIn("empty graph", payload["tableLineage"]["reason"])
        self.assertEqual(payload["columnLineage"]["state"], "available")
        self.assertTrue(payload["columnLineage"]["available"])

    def test_lineage_recommendations_wrap_live_uc_evidence_metadata(self) -> None:
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "token",
            },
            query_params={},
        )
        recommendation_payload = {
            "items": [
                {
                    "fqn": "main.gold.mortgage_signal",
                    "name": "mortgage_signal",
                    "edgeCount": 5,
                    "source": "system.access.table_lineage",
                }
            ],
            "meta": {
                "source": "system.access.table_lineage",
                "visibleAssetCount": 42,
                "scannedAssetCount": 42,
                "recommendationLimit": 1,
            },
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="actor-wh"),
            _uc=lambda: SimpleNamespace(warehouse_id="app-wh"),
            _store_for_read=lambda: object(),
            _request_cache_scope=lambda request: "analyst@example.com",
        ):
            lineage_api.lineage_service._TTL_CACHE.clear()
            # Cache-key normalization (audited P1): the key excludes the
            # requested limit so every ?limit= shares one warm payload.
            cache_key = "lineage_recommendations:actor-wh:analyst@example.com:actor-wh"
            lineage_api.lineage_service._TTL_CACHE[cache_key] = (time.time(), recommendation_payload)
            response = lineage_api.api_lineage_recommendations(request, limit=1)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["items"][0]["fqn"], "main.gold.mortgage_signal")
        self.assertEqual(payload["recommendationMeta"]["source"], "system.access.table_lineage")
        self.assertEqual(payload["meta"]["source"], "unity-catalog-lineage")
        self.assertTrue(payload["meta"]["authoritative"])
        self.assertEqual(
            payload["meta"]["capabilities"]["evidenceSource"],
            "system.access.table_lineage",
        )

    def test_lineage_recommendations_return_loading_envelope_while_cache_warms(self) -> None:
        request = SimpleNamespace(
            headers={"x-forwarded-email": "reader@example.com"},
            query_params={},
        )

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="actor-wh"),
            _uc=lambda: SimpleNamespace(warehouse_id="app-wh"),
            _store_for_read=lambda: object(),
            _request_cache_scope=lambda request: "reader@example.com",
        ):
            lineage_api.lineage_service._TTL_CACHE.clear()
            lineage_api._LINEAGE_RECOMMENDATIONS_WARMING.clear()
            with patch.object(
                lineage_api.threading,
                "Thread",
                autospec=True,
            ) as thread_cls:
                response = lineage_api.api_lineage_recommendations(request, limit=2)
            lineage_api._LINEAGE_RECOMMENDATIONS_WARMING.clear()

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["meta"]["state"], "loading")
        self.assertFalse(payload["meta"]["authoritative"])
        self.assertTrue(payload["recommendationMeta"]["hydrating"])
        # Loading envelopes are never HTTP-cached — a browser-cached
        # loading body froze the panel's poll loop (audited P1).
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        thread_cls.assert_called_once()

    def test_lineage_recommendations_aggregate_fallback_is_degraded_not_authoritative(self) -> None:
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "token",
            },
            query_params={},
        )
        recommendation_payload = {
            "items": [
                {
                    "fqn": "main.emet.run_history",
                    "edgeCount": 626,
                    "upstreamCount": 622,
                    "downstreamCount": 4,
                    "source": "system.access.table_lineage",
                }
            ],
            "meta": {
                "source": "system.access.table_lineage",
                "rankingSource": "system.access.table_lineage.aggregate-fallback",
                "visibleAssetCount": 22,
                "scannedAssetCount": 32,
                "recommendationLimit": 1,
            },
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="actor-wh"),
            _uc=lambda: SimpleNamespace(warehouse_id="app-wh"),
            _store_for_read=lambda: object(),
            _request_cache_scope=lambda request: "analyst@example.com",
        ):
            lineage_api.lineage_service._TTL_CACHE.clear()
            cache_key = "lineage_recommendations:actor-wh:analyst@example.com:actor-wh"
            lineage_api.lineage_service._TTL_CACHE[cache_key] = (time.time(), recommendation_payload)
            response = lineage_api.api_lineage_recommendations(request, limit=1)

        payload = _response_json(response)
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertFalse(payload["meta"]["authoritative"])
        self.assertEqual(
            payload["meta"]["capabilities"]["relationshipVisibilityScope"],
            "actor-openable-candidate-aggregate",
        )
        self.assertTrue(payload["meta"]["warnings"])


if __name__ == "__main__":
    unittest.main()
