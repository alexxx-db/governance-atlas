from __future__ import annotations

import ast
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from axiom.services import lineage as lineage_service


class FakeUC:
    def __init__(self, warehouse_id: str = "warehouse-1") -> None:
        self.warehouse_id = warehouse_id


class LineageCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        lineage_service._TTL_CACHE.clear()

    def test_lineage_payload_cache_keys_include_request_scope(self) -> None:
        uc = FakeUC()
        store = object()
        load_calls: list[str] = []

        def fake_build(_uc, _store, asset_fqn: str, **_kwargs):
            load_calls.append(asset_fqn)
            return {
                "fqn": asset_fqn,
                "sequence": len(load_calls),
            }

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            alice_first = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="alice@example.com",
            )
            alice_second = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="alice@example.com",
            )
            bob_first = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="bob@example.com",
            )

        self.assertEqual(alice_first["sequence"], 1)
        self.assertEqual(alice_second["sequence"], 1)
        self.assertEqual(bob_first["sequence"], 2)
        self.assertEqual(len(load_calls), 2)
        # Cache keys include the request scope so actor-visible payloads
        # cannot bleed across users.
        self.assertIn(
            "lineage:warehouse-1:alice@example.com:main.sales.orders",
            lineage_service._TTL_CACHE,
        )
        self.assertIn(
            "lineage:warehouse-1:bob@example.com:main.sales.orders",
            lineage_service._TTL_CACHE,
        )

    def test_lineage_recommendations_rank_visible_assets_from_uc_edges(self) -> None:
        class RecommendationUC(FakeUC):
            def get_table_lineage_edges_batch(
                self,
                _asset_fqns,
                *,
                directions=("upstream", "downstream"),
                per_seed_limit=80,
            ) -> pd.DataFrame:
                self.directions = directions
                self.per_seed_limit = per_seed_limit
                return pd.DataFrame(
                    [
                        {
                            "source_table_full_name": "main.raw.loans",
                            "target_table_full_name": "main.silver.mortgage_events",
                        },
                        {
                            "source_table_full_name": "main.silver.mortgage_events",
                            "target_table_full_name": "main.gold.mortgage_signal",
                        },
                        {
                            "source_table_full_name": "main.gold.mortgage_signal",
                            "target_table_full_name": "main.analytics.executive_dashboard",
                        },
                        {
                            "source_table_full_name": "main.external.hidden_source",
                            "target_table_full_name": "main.gold.mortgage_signal",
                        },
                    ]
                )

        visible = pd.DataFrame(
            [
                {
                    "fqn": "main.raw.loans",
                    "table_catalog": "main",
                    "table_schema": "raw",
                    "table_name": "loans",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "domain": "Mortgage",
                },
                {
                    "fqn": "main.silver.mortgage_events",
                    "table_catalog": "main",
                    "table_schema": "silver",
                    "table_name": "mortgage_events",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "certification": "Certified",
                },
                {
                    "fqn": "main.gold.mortgage_signal",
                    "table_catalog": "main",
                    "table_schema": "gold",
                    "table_name": "mortgage_signal",
                    "table_type": "VIEW",
                    "data_source_format": "",
                    "sensitivity": "Confidential",
                    "business_criticality": "Critical",
                },
                {
                    "fqn": "main.analytics.executive_dashboard",
                    "table_catalog": "main",
                    "table_schema": "analytics",
                    "table_name": "executive_dashboard",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                },
            ]
        )
        uc = RecommendationUC()

        with patch("axiom.services.lineage.asset_service.visible_assets", return_value=visible):
            payload = lineage_service.lineage_recommendations_payload(uc, object(), limit=2)

        self.assertEqual([item["fqn"] for item in payload["items"]], [
            "main.gold.mortgage_signal",
            "main.silver.mortgage_events",
        ])
        self.assertEqual(payload["items"][0]["upstreamCount"], 2)
        self.assertEqual(payload["items"][0]["downstreamCount"], 1)
        self.assertEqual(payload["items"][0]["source"], "system.access.table_lineage")
        self.assertEqual(payload["meta"]["visibleAssetCount"], 4)
        self.assertEqual(payload["meta"]["recommendationLimit"], 2)
        self.assertEqual(uc.directions, ("upstream", "downstream"))
        self.assertEqual(uc.per_seed_limit, lineage_service.LINEAGE_RECOMMENDATION_PER_SEED_LIMIT)

    def test_lineage_recommendations_rank_only_visible_scoped_edges_without_global_scan(self) -> None:
        class DensityUC(FakeUC):
            def __init__(self) -> None:
                super().__init__()
                self.identity_calls: list[str] = []
                self.scanned_batches: list[list[str]] = []

            def query_df(self, _query: str) -> pd.DataFrame:
                raise AssertionError("recommendations must not cold-scan the global lineage aggregate")

            def get_table_lineage_edges_batch(
                self,
                asset_fqns,
                *,
                directions=("upstream", "downstream"),
                per_seed_limit=40,
            ) -> pd.DataFrame:
                self.scanned_batches.append(list(asset_fqns))
                return pd.DataFrame(
                    [
                        {
                            "source_table_full_name": "main.visible.seed",
                            "target_table_full_name": "main.gold.mortgage_signal",
                        },
                        {
                            "source_table_full_name": "main.gold.mortgage_signal",
                            "target_table_full_name": "main.analytics.executive_dashboard",
                        },
                        {
                            "source_table_full_name": "system.hidden.internal_lineage",
                            "target_table_full_name": "main.gold.mortgage_signal",
                        },
                    ]
                )

            def get_table_identity(self, catalog: str, schema: str, table: str) -> pd.DataFrame:
                fqn = f"{catalog}.{schema}.{table}"
                self.identity_calls.append(fqn)
                return pd.DataFrame(
                    [
                        {
                            "table_catalog": catalog,
                            "table_schema": schema,
                            "table_name": table,
                            "table_type": "TABLE",
                            "data_source_format": "DELTA",
                            "comment": "",
                        }
                    ]
                )

            def get_table_tags(self, catalog: str, schema: str, table: str) -> pd.DataFrame:
                if table == "mortgage_signal":
                    return pd.DataFrame(
                        [
                            {"tag_name": "sensitivity", "tag_value": "Confidential"},
                            {"tag_name": "criticality", "tag_value": "Critical"},
                        ]
                    )
                return pd.DataFrame()

        visible = pd.DataFrame(
            [
                {
                    "fqn": "main.visible.seed",
                    "table_catalog": "main",
                    "table_schema": "visible",
                    "table_name": "seed",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                },
                {
                    "fqn": "main.gold.mortgage_signal",
                    "table_catalog": "main",
                    "table_schema": "gold",
                    "table_name": "mortgage_signal",
                    "table_type": "VIEW",
                    "data_source_format": "",
                    "sensitivity": "Confidential",
                    "business_criticality": "Critical",
                },
                {
                    "fqn": "main.analytics.executive_dashboard",
                    "table_catalog": "main",
                    "table_schema": "analytics",
                    "table_name": "executive_dashboard",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                },
            ]
        )
        uc = DensityUC()

        with patch("axiom.services.lineage.asset_service.visible_assets", return_value=visible):
            payload = lineage_service.lineage_recommendations_payload(uc, object(), limit=2)

        self.assertEqual([item["fqn"] for item in payload["items"]], [
            "main.gold.mortgage_signal",
            "main.visible.seed",
        ])
        self.assertEqual(payload["items"][0]["edgeCount"], 3)
        self.assertEqual(payload["items"][0]["sensitivity"], "Confidential")
        self.assertEqual(payload["items"][0]["criticality"], "Critical")
        self.assertEqual(payload["meta"]["rankingSource"], "visible-inventory-batched-lineage")
        self.assertTrue(payload["meta"]["bounded"])
        self.assertEqual(uc.identity_calls, [])
        self.assertEqual(
            uc.scanned_batches,
            [[
                "main.visible.seed",
                "main.gold.mortgage_signal",
                "main.analytics.executive_dashboard",
            ]],
        )

    def test_lineage_recommendations_use_density_fallback_when_visible_batches_are_empty(self) -> None:
        class DensityFallbackUC(FakeUC):
            def __init__(self) -> None:
                super().__init__()
                self.identity_calls: list[str] = []

            def get_table_lineage_edges_batch(
                self,
                _asset_fqns,
                *,
                directions=("upstream", "downstream"),
                per_seed_limit=40,
            ) -> pd.DataFrame:
                return pd.DataFrame()

            def query_df(self, _query: str) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "asset_fqn": "main.emet.run_history",
                            "upstreamCount": 3,
                            "downstreamCount": 7,
                            "edgeCount": 10,
                        },
                    ]
                )

            def get_table_identity(self, catalog: str, schema: str, table: str) -> pd.DataFrame:
                fqn = f"{catalog}.{schema}.{table}"
                self.identity_calls.append(fqn)
                return pd.DataFrame(
                    [
                        {
                            "table_catalog": catalog,
                            "table_schema": schema,
                            "table_name": table,
                            "table_type": "TABLE",
                            "data_source_format": "DELTA",
                            "comment": "Backed run history",
                        }
                    ]
                )

        visible = pd.DataFrame(
            [
                {
                    "fqn": "emet.visible.seed",
                    "table_catalog": "emet",
                    "table_schema": "visible",
                    "table_name": "seed",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                },
            ]
        )
        uc = DensityFallbackUC()

        with patch("axiom.services.lineage.asset_service.visible_assets", return_value=visible):
            payload = lineage_service.lineage_recommendations_payload(uc, object(), limit=1)

        self.assertEqual([item["fqn"] for item in payload["items"]], ["main.emet.run_history"])
        self.assertEqual(payload["items"][0]["edgeCount"], 10)
        self.assertEqual(payload["meta"]["rankingSource"], "system.access.table_lineage.aggregate-fallback")
        self.assertEqual(uc.identity_calls, ["main.emet.run_history"])

    def test_invalidate_lineage_caches_clears_all_scoped_variants_for_asset(self) -> None:
        uc = FakeUC()
        store = object()
        load_calls: list[str] = []

        def fake_build(_uc, _store, asset_fqn: str, **_kwargs):
            load_calls.append(asset_fqn)
            return {
                "fqn": asset_fqn,
                "sequence": len(load_calls),
            }

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="alice@example.com",
            )
            lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="bob@example.com",
            )

            self.assertEqual(len(load_calls), 2)
            self.assertEqual(len(lineage_service._TTL_CACHE), 2)

            lineage_service.invalidate_lineage_caches("main.sales.orders")

        self.assertEqual(lineage_service._TTL_CACHE, {})

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                cache_scope="alice@example.com",
            )

        self.assertEqual(len(load_calls), 3)

    def test_lineage_payload_cache_keys_separate_initial_and_full_profiles(self) -> None:
        uc = FakeUC()
        store = object()
        load_calls: list[tuple[str, str]] = []

        def fake_build(_uc, _store, asset_fqn: str, **kwargs):
            profile = kwargs.get("profile") or "full"
            load_calls.append((asset_fqn, profile))
            return {
                "fqn": asset_fqn,
                "profile": profile,
                "sequence": len(load_calls),
            }

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            initial = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                profile="initial",
            )
            full = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                profile="full",
            )
            initial_again = lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.orders",
                profile="initial",
            )

        self.assertEqual(initial["sequence"], 1)
        self.assertEqual(full["sequence"], 2)
        self.assertEqual(initial_again["sequence"], 1)
        self.assertEqual(load_calls, [("main.sales.orders", "initial"), ("main.sales.orders", "full")])
        self.assertIn(
            "lineage:initial:warehouse-1:shared:main.sales.orders",
            lineage_service._TTL_CACHE,
        )
        self.assertIn(
            "lineage:warehouse-1:shared:main.sales.orders",
            lineage_service._TTL_CACHE,
        )

    def test_initial_profile_defers_table_lineage_scans(self) -> None:
        class InitialOnlyUC(FakeUC):
            def __init__(self) -> None:
                super().__init__()
                self.table_lineage_calls = 0

            def get_table_identity(self, catalog: str, schema: str, table: str) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "table_catalog": catalog,
                            "table_schema": schema,
                            "table_name": table,
                            "table_type": "MANAGED",
                            "data_source_format": "DELTA",
                            "comment": "Orders table",
                        }
                    ]
                )

            def get_table_tags(self, *_args, **_kwargs) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {"tag_name": "certification", "tag_value": "Trusted"},
                    ]
                )

            def get_table_lineage_upstream(self, *_args, **_kwargs) -> pd.DataFrame:
                self.table_lineage_calls += 1
                raise AssertionError("initial profile must not scan upstream table lineage")

            def get_table_lineage_downstream(self, *_args, **_kwargs) -> pd.DataFrame:
                self.table_lineage_calls += 1
                raise AssertionError("initial profile must not scan downstream table lineage")

        uc = InitialOnlyUC()
        payload = lineage_service._build_lineage_payload(
            uc,
            object(),
            "main.sales.orders",
            profile="initial",
        )

        self.assertEqual(payload["profile"], "initial")
        self.assertEqual(uc.table_lineage_calls, 0)
        self.assertEqual(len(payload["graphs"]["data"]["nodes"]), 1)
        self.assertEqual(payload["graphs"]["data"]["edges"], [])
        self.assertTrue(payload["graphs"]["data"]["meta"]["tableLineageDeferred"])
        self.assertTrue(payload["stats"]["progressive"]["tableLineageDeferred"])

    def test_invalidate_lineage_caches_does_not_match_superstring_fqns(
        self,
    ) -> None:
        """Invalidating `main.sales.ap` must NOT evict
        `main.sales.ap_invoices` from the cache. The old
        `endswith(":main.sales.ap")` logic was safe; the new
        middle-substring match `:main.sales.ap:` must be too.
        """
        lineage_service._TTL_CACHE.clear()
        uc = FakeUC()
        store = object()

        def fake_build(_uc, _store, asset_fqn: str, **_kwargs):
            return {"fqn": asset_fqn}

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            lineage_service.lineage_payload(
                uc, store, "main.sales.ap", cache_scope="alice@example.com"
            )
            lineage_service.lineage_payload(
                uc,
                store,
                "main.sales.ap_invoices",
                cache_scope="alice@example.com",
            )

        self.assertEqual(len(lineage_service._TTL_CACHE), 2)
        lineage_service.invalidate_lineage_caches("main.sales.ap")
        # The prefix-sharing asset should survive.
        surviving_keys = list(lineage_service._TTL_CACHE)
        self.assertEqual(len(surviving_keys), 1)
        self.assertIn("main.sales.ap_invoices", surviving_keys[0])

    def test_runtime_app_lineage_helper_threads_request_cache_scope(self) -> None:
        source = Path("runtime_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="runtime_app.py")
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_lineage_payload"
        )

        self.assertEqual(
            [arg.arg for arg in helper.args.args],
            ["asset_fqn", "request"],
        )
        self.assertIsNotNone(helper.args.defaults)
        self.assertEqual(len(helper.args.defaults), 1)
        self.assertIsInstance(helper.args.defaults[0], ast.Constant)
        self.assertIsNone(helper.args.defaults[0].value)

        lineage_calls = [
            node
            for node in ast.walk(helper)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "lineage_service"
            and node.func.attr == "lineage_payload"
        ]
        self.assertEqual(len(lineage_calls), 1)

        keywords = {keyword.arg: keyword.value for keyword in lineage_calls[0].keywords}
        self.assertIn("cache_scope", keywords)
        self.assertIsInstance(keywords["cache_scope"], ast.Call)
        self.assertIsInstance(keywords["cache_scope"].func, ast.Name)
        self.assertEqual(keywords["cache_scope"].func.id, "_request_cache_scope")
        self.assertEqual(
            [arg.id for arg in keywords["cache_scope"].args if isinstance(arg, ast.Name)],
            ["request"],
        )

    def test_graph_node_uses_visible_inventory_for_openability(self) -> None:
        row = pd.Series(
            {
                "fqn": "main.sales.hidden_orders",
                "table_catalog": "main",
                "table_schema": "sales",
                "table_name": "hidden_orders",
                "table_type": "TABLE",
                "data_source_format": "DELTA",
                "comment": "Sensitive table",
            }
        )
        visible_inventory = pd.DataFrame(columns=["fqn"])

        with patch("axiom.services.lineage.asset_service.inventory_row", return_value=row):
            node = lineage_service.graph_node_for_asset(
                FakeUC(),
                object(),
                "main.sales.hidden_orders",
                "source",
                0,
                0,
                kicker="Upstream",
                visible_inventory=visible_inventory,
            )

        self.assertFalse(node["details"]["isOpenable"])
        self.assertEqual(node["details"]["resolutionState"], "lineage-only")
        # L9: non-openable nodes now emit ONE clear permission-honest foot
        # line instead of stacking two "Metadata … unavailable" variants.
        self.assertEqual(node["foot"], ["Not visible to your account"])
        self.assertEqual(node["details"]["governanceStatus"], "Unavailable")
        self.assertEqual(node["details"]["domain"], "Unavailable")

    def test_table_lineage_graph_walks_real_second_hop_branch(self) -> None:
        class LineageUC(FakeUC):
            upstream_map = {
                "main.gold.revenue": ["main.silver.payments"],
                "main.silver.payments": ["main.bronze.charges", "main.bronze.orders"],
            }

            def get_table_lineage_upstream(self, catalog: str, schema: str, table: str, limit: int = 50) -> pd.DataFrame:
                fqn = f"{catalog}.{schema}.{table}"
                return pd.DataFrame(
                    {"source_table_full_name": self.upstream_map.get(fqn, [])}
                )

            def get_table_lineage_edges_batch(
                self,
                fqns,
                *,
                directions=("upstream", "downstream"),
                per_seed_limit: int = 50,
            ) -> pd.DataFrame:
                # Batched implementation that mirrors the per-node
                # upstream_map for the directions the test exercises.
                # Returns one row per (source_fqn, target_fqn) pair.
                rows = []
                if "upstream" in directions:
                    for target_fqn in fqns:
                        for source_fqn in self.upstream_map.get(target_fqn, []):
                            rows.append({
                                "source_table_full_name": source_fqn,
                                "source_table_catalog": source_fqn.split(".")[0],
                                "source_table_schema": source_fqn.split(".")[1],
                                "source_table_name": source_fqn.split(".")[2],
                                "source_type": "TABLE",
                                "target_table_full_name": target_fqn,
                                "target_table_catalog": target_fqn.split(".")[0],
                                "target_table_schema": target_fqn.split(".")[1],
                                "target_table_name": target_fqn.split(".")[2],
                                "target_type": "TABLE",
                            })
                return pd.DataFrame(rows)

        def fake_node(_uc, _store, asset_fqn, role, _x, _y, **kwargs):
            return {
                "id": f"{role}-{asset_fqn}",
                "assetFqn": asset_fqn,
                "role": role,
                "depth": kwargs.get("depth", 1),
                "label": asset_fqn.rsplit(".", 1)[-1],
                "kind": "Table",
            }

        with patch("axiom.services.lineage.graph_node_for_asset", side_effect=fake_node):
            branch = lineage_service._recursive_branch_graph(
                LineageUC(),
                object(),
                "main.gold.revenue",
                direction="upstream",
                depth_limit=2,
                node_limit=12,
                per_hop_limit=6,
            )

        node_fqns = {node["assetFqn"] for node in branch["nodes"]}
        self.assertEqual(
            node_fqns,
            {"main.silver.payments", "main.bronze.charges", "main.bronze.orders"},
        )
        self.assertEqual(len(branch["edges"]), 3)
        self.assertEqual(branch["depthLimit"], 2)

        data_graph = {
            "nodes": [
                {"id": "focus-main.gold.revenue", "assetFqn": "main.gold.revenue", "role": "focus"},
                *branch["nodes"],
            ],
            "edges": branch["edges"],
        }
        counts = lineage_service._lineage_graph_direction_counts(data_graph)
        self.assertEqual(counts["directUpstream"], 1)
        self.assertEqual(counts["upstream"], 3)


if __name__ == "__main__":
    unittest.main()
