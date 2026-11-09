from __future__ import annotations

import json
import sys
import types
import unittest

import pandas as pd

from axiom.api import assets as assets_api
from axiom.services import assets as asset_service


class AssetDetailSectionTests(unittest.TestCase):
    def test_explicit_empty_sections_do_not_expand_to_full_payload(self) -> None:
        self.assertEqual(
            asset_service.normalize_asset_detail_sections([]),
            ("header",),
        )

    def test_profiler_sections_do_not_auto_include_preview_or_operational(self) -> None:
        self.assertEqual(
            asset_service.normalize_asset_detail_sections(["profiler"]),
            ("header", "activity", "schema", "profiler"),
        )

    def test_profiler_payload_omits_blocked_preview_and_operational_cards(self) -> None:
        payload = asset_service.profiler_payload(
            {"governanceStatus": "Needs Work"},
            [],
            [{"order_id": "1"}],
            ["main.sales.customers"],
            [],
            {
                "producers": [{"key": "job-1"}],
                "consumers": [{"key": "dashboard-1"}],
            },
            include_preview=False,
            include_operational=False,
        )

        titles = [card["title"] for card in payload["cards"]]
        self.assertNotIn("Sample Data", titles)
        self.assertNotIn("Operational Usage", titles)
        self.assertIn("Lineage Context", titles)

    def test_fast_header_payload_uses_visible_inventory_without_detail_sections(self) -> None:
        payload = asset_service.asset_header_payload_from_inventory(
            pd.DataFrame(
                [
                    {
                        "fqn": "main.sales.orders",
                        "table_catalog": "main",
                        "table_schema": "sales",
                        "table_name": "orders",
                        "table_type": "MANAGED",
                        "data_source_format": "DELTA",
                        "comment": "Backed order table",
                        "domain": "Sales",
                        "certification": "Certified",
                        "sensitivity": "Internal",
                        "criticality": "High",
                        "business_owner": "sales-owner@example.com",
                    }
                ]
            ),
            "main.sales.orders",
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["fqn"], "main.sales.orders")
        self.assertEqual(payload["loadedSections"], ["header"])
        self.assertIn("schema", payload["deferredSections"])
        self.assertEqual(payload["headerSource"], "visible-unity-catalog-inventory")
        self.assertEqual(payload["columns"], [])

    def test_fast_header_payload_fails_closed_when_asset_not_visible(self) -> None:
        payload = asset_service.asset_header_payload_from_inventory(
            pd.DataFrame(
                [
                    {
                        "fqn": "main.sales.orders",
                        "table_catalog": "main",
                        "table_schema": "sales",
                        "table_name": "orders",
                    }
                ]
            ),
            "main.sales.hidden_orders",
        )

        self.assertIsNone(payload)


class AssetDetailLoadingEnvelopeCacheTests(unittest.TestCase):
    def test_loading_envelope_is_never_http_cacheable(self) -> None:
        # P4 perf fix: a hydrating envelope served with max-age let the
        # browser re-serve stale "loading" bodies for up to 30s after the
        # server was warm. The loading branch must send no-store.
        previous = sys.modules.get("runtime_app")
        module = types.ModuleType("runtime_app")
        module._ensure_live_runtime = lambda: None
        module._asset_visibility_record = lambda *_a, **_k: {
            "exists": False,
            "visible": False,
            "openable": False,
            "visibilityState": "loading",
            "reason": "hydrating",
        }
        module._asset_detail_payload = lambda *_a, **_k: {}
        sys.modules["runtime_app"] = module
        try:
            request = types.SimpleNamespace(
                headers={}, state=types.SimpleNamespace()
            )
            response = assets_api.api_asset_detail(
                "main.sales.orders", request, sections=["header"]
            )
        finally:
            if previous is None:
                sys.modules.pop("runtime_app", None)
            else:
                sys.modules["runtime_app"] = previous

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["meta"]["state"], "loading")


class ExactIdentityRowMemoTests(unittest.TestCase):
    def test_identity_and_tag_queries_run_once_within_ttl(self) -> None:
        # P0 perf fix: the visibility gate calls exact_identity_row on every
        # asset-detail/lineage request; the raw identity+tags lookups must be
        # memoized per (warehouse|scope, fqn) so the second call is free.
        calls = {"identity": 0, "tags": 0}

        class FakeUC:
            warehouse_id = "wh-memo-test"
            cache_scope = "memo-user@example.com|obo"

            def get_table_identity(self, catalog, schema, table):
                calls["identity"] += 1
                return pd.DataFrame(
                    [
                        {
                            "table_catalog": catalog,
                            "table_schema": schema,
                            "table_name": table,
                            "table_type": "MANAGED",
                            "data_source_format": "DELTA",
                            "comment": "memoized",
                        }
                    ]
                )

            def get_table_tags(self, catalog, schema, table):
                calls["tags"] += 1
                return pd.DataFrame(
                    [{"tag_name": "domain", "tag_value": "Finance"}]
                )

        uc = FakeUC()
        first = asset_service.exact_identity_row(uc, "memo_cat.s.t")
        second = asset_service.exact_identity_row(uc, "memo_cat.s.t")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(calls, {"identity": 1, "tags": 1})
        # Differing inventory_columns shapes still resolve from the memo.
        shaped = asset_service.exact_identity_row(
            uc, "memo_cat.s.t", inventory_columns=["fqn", "extra_col"]
        )
        self.assertIsNotNone(shaped)
        self.assertIn("extra_col", shaped.index)
        self.assertEqual(calls, {"identity": 1, "tags": 1})


class AssetDetailMalformedFqnTests(unittest.TestCase):
    def test_two_part_fqn_returns_400_not_503(self) -> None:
        previous = sys.modules.get("runtime_app")
        module = types.ModuleType("runtime_app")
        module._ensure_live_runtime = lambda: None
        # If the guard works, the visibility record is never consulted.
        module._asset_visibility_record = lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("visibility should not be checked for a malformed FQN")
        )
        module._asset_detail_payload = lambda *_a, **_k: {}
        sys.modules["runtime_app"] = module
        try:
            request = types.SimpleNamespace(headers={}, state=types.SimpleNamespace())
            response = assets_api.api_asset_detail("emet.enterprise_metadata_ops", request)
        finally:
            if previous is None:
                sys.modules.pop("runtime_app", None)
            else:
                sys.modules["runtime_app"] = previous

        self.assertEqual(response.status_code, 400)
        body = json.loads(response.body.decode("utf-8"))
        self.assertIn("three-part", body["detail"])


if __name__ == "__main__":
    unittest.main()
