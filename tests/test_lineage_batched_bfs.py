from __future__ import annotations

import unittest

import pandas as pd

from axiom.services import lineage as lineage_service


class _FakeSystemClient:
    def __init__(self, rows=None, raise_error: bool = False):
        self.rows = rows or []
        self.raise_error = raise_error
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []

    def get_table_lineage_edges_batch(
        self,
        fqns,
        *,
        directions=("upstream", "downstream"),
        per_seed_limit=50,
    ):
        self.calls.append((tuple(fqns), tuple(directions), per_seed_limit))
        if self.raise_error:
            raise RuntimeError("warehouse down")
        return pd.DataFrame(self.rows)


class LineageNeighborRecordsBatchTests(unittest.TestCase):
    def test_empty_frontier_returns_empty_dict(self) -> None:
        client = _FakeSystemClient()
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client, [], direction="upstream", per_seed_limit=50
        )
        self.assertEqual(out, {})
        self.assertFalse(meta["queryFailed"])
        self.assertEqual(client.calls, [])

    def test_upstream_records_group_by_target_seed(self) -> None:
        client = _FakeSystemClient(
            [
                {
                    "target_table_full_name": "prod.silver.orders",
                    "source_table_full_name": "bronze.raw.orders_stream",
                },
                {
                    "target_table_full_name": "prod.silver.orders",
                    "source_table_full_name": "bronze.raw.orders_stream",
                },
            ]
        )
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client,
            ["prod.silver.orders"],
            direction="upstream",
            per_seed_limit=50,
        )
        self.assertEqual(client.calls, [(("prod.silver.orders",), ("upstream",), 50)])
        self.assertEqual(
            out["prod.silver.orders"],
            [{"assetFqn": "bronze.raw.orders_stream", "provenance": "system.access.table_lineage"}],
        )
        self.assertFalse(meta["queryFailed"])

    def test_downstream_records_group_by_source_seed(self) -> None:
        client = _FakeSystemClient(
            [
                {
                    "source_table_full_name": "prod.silver.orders",
                    "target_table_full_name": "prod.gold.order_facts",
                }
            ]
        )
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client,
            ["prod.silver.orders"],
            direction="downstream",
            per_seed_limit=25,
        )
        self.assertEqual(client.calls, [(("prod.silver.orders",), ("downstream",), 25)])
        self.assertEqual(
            out["prod.silver.orders"],
            [{"assetFqn": "prod.gold.order_facts", "provenance": "system.access.table_lineage"}],
        )
        self.assertFalse(meta["queryFailed"])

    def test_seed_totals_survive_per_seed_truncation(self) -> None:
        # seed_total_edges rides on every SQL row so truncation copy can
        # honestly say "showing N of M" even when the per-seed cap trimmed
        # the result (e.g. 40 of 655 for main.emet.run_history).
        client = _FakeSystemClient(
            [
                {
                    "target_table_full_name": "main.emet.run_history",
                    "source_table_full_name": "main.demo.users",
                    "seed_total_edges": 655,
                },
                {
                    "target_table_full_name": "main.emet.run_history",
                    "source_table_full_name": "main.demo.transactions",
                    "seed_total_edges": 655,
                },
            ]
        )
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client,
            ["main.emet.run_history"],
            direction="upstream",
            per_seed_limit=2,
        )
        self.assertEqual(len(out["main.emet.run_history"]), 2)
        self.assertEqual(meta["totalsBySeed"], {"main.emet.run_history": 655})

    def test_empty_sql_result_yields_empty_map(self) -> None:
        client = _FakeSystemClient()
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client,
            ["prod.silver.foo", "prod.silver.bar"],
            direction="upstream",
            per_seed_limit=50,
        )
        self.assertEqual(out, {"prod.silver.foo": [], "prod.silver.bar": []})
        # An empty result from a SUCCESSFUL query is a true empty, not a
        # failure — the graph build must not mark it degraded.
        self.assertFalse(meta["queryFailed"])

    def test_exception_path_flags_query_failed_not_silent_empty(self) -> None:
        # Honesty regression (audited P0): a failed warehouse query must be
        # DISTINGUISHABLE from "Unity Catalog has no rows". The old
        # behavior returned an indistinguishable empty map, which let a
        # permanently-broken batch query render 0 upstream edges as an
        # authoritative empty graph for every asset in the product.
        client = _FakeSystemClient(raise_error=True)
        out, meta = lineage_service._lineage_neighbor_records_batch(
            client,
            ["prod.silver.foo"],
            direction="upstream",
            per_seed_limit=50,
        )
        self.assertEqual(out, {"prod.silver.foo": []})
        self.assertTrue(meta["queryFailed"])


if __name__ == "__main__":
    unittest.main()
