from __future__ import annotations

import unittest
from typing import Dict, List

from axiom.services import lineage as lineage_service


def _graph_from_edges(edges: Dict[str, List[Dict[str, str]]]):
    """Build a fetcher from a literal adjacency map keyed as
    'asset#column' -> list of {assetFqn, column}."""

    def _fetch(asset_fqn: str, column: str) -> List[Dict[str, str]]:
        return list(edges.get(f"{asset_fqn}#{column}", []))

    return _fetch


class MultiHopUpstreamTests(unittest.TestCase):
    def test_single_hop_upstream(self) -> None:
        fetcher = _graph_from_edges(
            {
                "main.silver.orders#customer_id": [
                    {"assetFqn": "main.bronze.raw_orders", "column": "cust_id"},
                ]
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="main.silver.orders",
            column_name="customer_id",
            direction="upstream",
            depth=1,
            fetch_neighbors=fetcher,
        )
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(len(result["edges"]), 1)
        edge = result["edges"][0]
        # Upstream direction: neighbor -> current
        self.assertEqual(edge["source"], "main.bronze.raw_orders#cust_id")
        self.assertEqual(edge["target"], "main.silver.orders#customer_id")

    def test_three_hop_upstream_walk(self) -> None:
        fetcher = _graph_from_edges(
            {
                "main.gold.dim_customer#id": [
                    {"assetFqn": "main.silver.customers", "column": "customer_id"},
                ],
                "main.silver.customers#customer_id": [
                    {"assetFqn": "main.bronze.raw_customers", "column": "cust_id"},
                ],
                "main.bronze.raw_customers#cust_id": [
                    {"assetFqn": "main.raw.landing", "column": "cust"},
                ],
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="main.gold.dim_customer",
            column_name="id",
            direction="upstream",
            depth=3,
            fetch_neighbors=fetcher,
        )
        asset_fqns = sorted({n["assetFqn"] for n in result["nodes"]})
        self.assertEqual(
            asset_fqns,
            [
                "main.bronze.raw_customers",
                "main.gold.dim_customer",
                "main.raw.landing",
                "main.silver.customers",
            ],
        )
        self.assertEqual(len(result["edges"]), 3)

    def test_fanout_capped_and_flagged(self) -> None:
        fetcher = _graph_from_edges(
            {
                "main.gold.orders#id": [
                    {"assetFqn": f"main.s.src{i}", "column": "id"} for i in range(20)
                ]
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="main.gold.orders",
            column_name="id",
            direction="upstream",
            depth=1,
            fetch_neighbors=fetcher,
            per_hop_fanout=5,
        )
        self.assertEqual(len(result["edges"]), 5)
        self.assertTrue(result["meta"]["truncated"])
        self.assertEqual(result["meta"]["reason"], "per-hop fanout cap")

    def test_node_budget_caps_total(self) -> None:
        fetcher = _graph_from_edges(
            {
                "a.b.c#x": [{"assetFqn": f"a.b.c{i}", "column": "x"} for i in range(5)],
                "a.b.c0#x": [{"assetFqn": f"a.b.d{i}", "column": "x"} for i in range(5)],
                "a.b.c1#x": [{"assetFqn": f"a.b.e{i}", "column": "x"} for i in range(5)],
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="a.b.c",
            column_name="x",
            direction="upstream",
            depth=2,
            fetch_neighbors=fetcher,
            max_nodes=6,
            per_hop_fanout=8,
        )
        self.assertLessEqual(len(result["nodes"]), 6)
        self.assertTrue(result["meta"]["truncated"])

    def test_cycle_is_tolerated(self) -> None:
        fetcher = _graph_from_edges(
            {
                "a.b.c#x": [{"assetFqn": "a.b.d", "column": "x"}],
                "a.b.d#x": [{"assetFqn": "a.b.c", "column": "x"}],
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="a.b.c",
            column_name="x",
            direction="upstream",
            depth=4,
            fetch_neighbors=fetcher,
        )
        # Two nodes, two edges (one per direction). Cycle doesn't blow up.
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual(len(result["edges"]), 2)


class MultiHopDownstreamTests(unittest.TestCase):
    def test_downstream_edges_point_away_from_root(self) -> None:
        fetcher = _graph_from_edges(
            {
                "main.silver.x#y": [
                    {"assetFqn": "main.gold.x", "column": "y"},
                ]
            }
        )
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="main.silver.x",
            column_name="y",
            direction="downstream",
            depth=1,
            fetch_neighbors=fetcher,
        )
        edge = result["edges"][0]
        self.assertEqual(edge["source"], "main.silver.x#y")
        self.assertEqual(edge["target"], "main.gold.x#y")


class ValidationTests(unittest.TestCase):
    def test_rejects_unknown_direction(self) -> None:
        with self.assertRaises(ValueError):
            lineage_service.trace_multi_hop_column_lineage(
                asset_fqn="a.b.c",
                column_name="x",
                direction="sideways",
                depth=1,
                fetch_neighbors=lambda a, c: [],
            )

    def test_depth_clamped_to_hop_limit(self) -> None:
        result = lineage_service.trace_multi_hop_column_lineage(
            asset_fqn="a.b.c",
            column_name="x",
            direction="upstream",
            depth=999,
            fetch_neighbors=lambda a, c: [],
            hop_limit=2,
        )
        self.assertEqual(result["meta"]["depthLimit"], 2)


if __name__ == "__main__":
    unittest.main()
