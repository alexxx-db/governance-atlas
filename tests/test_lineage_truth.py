"""Regression tests for the lineage-truth audit fixes.

Covers (audit findings, feature/persona-audit-fixes campaign):
  1. P0 — the batched lineage SQL must never mix GROUP BY ALL with a
     window function in the same SELECT (Spark rejects it with
     UNSUPPORTED_EXPR_FOR_OPERATOR; the failure was silently swallowed
     and every asset rendered 0 upstream edges). The window functions
     must rank an already-aggregated CTE, and query failures must
     PROPAGATE instead of degrading into an empty frame.
  2. P0 — failed/degraded builds must not be cached for the full 300s
     TTL nor served as authoritative; they expire after ~15s.
  3. P1 — payload meta distinguishes true-empty vs degraded builds and
     surfaces exact truncation counts (graphs.data.meta.truncation).
  7. P2 — a payload whose columnLineage has upstream entries can never
     claim an authoritative 0-upstream table graph: either the graph has
     upstream nodes or the build carries a degraded/truncation marker.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from axiom.services import lineage as lineage_service
from axiom.uc import UCSQLClient


class _SQLCapture:
    """Duck-typed stand-in for UCSQLClient's query_df — captures SQL."""

    def __init__(self, frame: pd.DataFrame | None = None, raise_error: bool = False):
        self.queries: list[str] = []
        self.frame = frame if frame is not None else pd.DataFrame()
        self.raise_error = raise_error

    def query_df(self, q: str) -> pd.DataFrame:
        self.queries.append(q)
        if self.raise_error:
            raise RuntimeError("UNSUPPORTED_EXPR_FOR_OPERATOR")
        return self.frame


class BatchLineageSQLShapeTests(unittest.TestCase):
    """Finding 1 — the SQL must be Spark-legal and failures must raise."""

    def _generated_sql(self) -> str:
        capture = _SQLCapture()
        UCSQLClient.get_table_lineage_edges_batch(
            capture,
            ["main.emet.run_history"],
            directions=("upstream", "downstream"),
            per_seed_limit=40,
        )
        self.assertEqual(len(capture.queries), 1)
        return capture.queries[0]

    def test_window_function_is_hoisted_out_of_the_group_by_all_select(self) -> None:
        sql = self._generated_sql()
        # The aggregation CTE ends at GROUP BY ALL; every window function
        # must appear AFTER it (in the ranking CTE over the aggregated
        # result). If a future edit moves ROW_NUMBER back beside
        # GROUP BY ALL, Spark rejects the query on every call.
        group_by_pos = sql.index("GROUP BY ALL")
        self.assertIn("ROW_NUMBER() OVER", sql)
        self.assertGreater(sql.index("ROW_NUMBER() OVER"), group_by_pos)
        self.assertGreater(sql.index("seed_total_edges"), group_by_pos)
        # The pre-window segment (base scan + aggregation) must contain no
        # window function at all.
        self.assertNotIn("OVER (", sql[:group_by_pos])

    def test_batch_sql_selects_honest_truncation_totals(self) -> None:
        sql = self._generated_sql()
        # seed_total_edges powers meta.truncation "showing N of M"; it must
        # ride on every returned row despite the per-seed cap.
        self.assertIn("COUNT(*) OVER", sql)
        self.assertIn("seed_rank <= 40", sql)
        # Ranked by activity so the most-active partners survive the cap.
        self.assertIn("ORDER BY edge_event_count DESC", sql)

    def test_batch_sql_collapses_entity_type_churn_out_of_the_dedup_key(self) -> None:
        # Adversarial verify P1 (false truncation flags): grouping on
        # source_type/target_type let a partner recorded under multiple
        # entity types (TABLE vs STREAMING_TABLE churn) occupy several
        # deduped rows — inflating seed_total_edges past the real distinct
        # partner count (mip.silver.property_master: 21 reported vs 12
        # actual) and raising downstreamTruncated while every real edge was
        # already drawn. The type columns must be aggregated (MAX) so the
        # dedup key is the (source, target) table-name pair only, making
        # COUNT(*) OVER the honest distinct-partner total per direction.
        sql = self._generated_sql()
        self.assertIn("MAX(source_type) AS source_type", sql)
        self.assertIn("MAX(target_type) AS target_type", sql)
        group_by_pos = sql.index("GROUP BY ALL")
        # Bare (un-aggregated) type columns must not appear in the dedup
        # CTE's select list before GROUP BY ALL.
        dedup_segment = sql[: group_by_pos]
        self.assertNotIn("\n        source_type,", dedup_segment)
        self.assertNotIn("\n        target_type,", dedup_segment)

    def test_query_failure_propagates_instead_of_silent_empty_frame(self) -> None:
        # The old `except Exception: return pd.DataFrame()` swallowed the
        # invalid-SQL failure for months. Callers now depend on the raise
        # to distinguish degraded builds from true-empty lineage.
        capture = _SQLCapture(raise_error=True)
        with self.assertRaises(RuntimeError):
            UCSQLClient.get_table_lineage_edges_batch(
                capture,
                ["main.emet.run_history"],
                directions=("upstream",),
                per_seed_limit=40,
            )


class _GraphUC:
    """Fake UC whose batch lineage either fails or returns fixed edges."""

    warehouse_id = "truth-wh"

    def __init__(self, *, raise_error: bool = False, upstream_rows=None):
        self.raise_error = raise_error
        self.upstream_rows = upstream_rows or []

    def get_table_lineage_edges_batch(
        self, fqns, *, directions=("upstream", "downstream"), per_seed_limit=50
    ) -> pd.DataFrame:
        if self.raise_error:
            raise RuntimeError("warehouse down")
        rows = []
        if "upstream" in directions:
            rows = list(self.upstream_rows)
        return pd.DataFrame(rows)

    def get_table_lineage_upstream(self, *_a, **_k) -> pd.DataFrame:
        return pd.DataFrame()

    def get_table_lineage_downstream(self, *_a, **_k) -> pd.DataFrame:
        return pd.DataFrame()

    def query_df(self, *_a, **_k) -> pd.DataFrame:
        return pd.DataFrame()


def _fake_node(_uc, _store, asset_fqn, role, _x, _y, **kwargs):
    return {
        "id": f"{role}-{asset_fqn}",
        "assetFqn": asset_fqn,
        "role": role,
        "depth": kwargs.get("depth", 1),
        "label": asset_fqn.rsplit(".", 1)[-1],
        "kind": "Table",
        "details": {"isOpenable": True},
    }


class BuildHonestyTests(unittest.TestCase):
    """Findings 2 + 3 — degraded builds are marked and short-cached."""

    def setUp(self) -> None:
        lineage_service._TTL_CACHE.clear()

    def test_failed_query_marks_branch_and_graph_degraded(self) -> None:
        with patch("axiom.services.lineage.graph_node_for_asset", side_effect=_fake_node):
            graph = lineage_service.build_data_graph(
                _GraphUC(raise_error=True), object(), "main.emet.run_history"
            )
        meta = graph["meta"]
        self.assertTrue(meta["lineageQueryFailed"])
        # A failed build must NEVER claim Unity Catalog returned nothing.
        self.assertEqual(meta["emptyReason"], "lineage-query-failed")

    def test_true_empty_graph_reports_no_lineage_rows(self) -> None:
        with patch("axiom.services.lineage.graph_node_for_asset", side_effect=_fake_node):
            graph = lineage_service.build_data_graph(
                _GraphUC(raise_error=False), object(), "main.empty.asset"
            )
        meta = graph["meta"]
        self.assertFalse(meta["lineageQueryFailed"])
        self.assertEqual(meta["emptyReason"], "no-lineage-rows")
        self.assertEqual(
            meta["truncation"],
            {"nodesShown": 1, "nodesTotal": 1, "edgesShown": 0, "edgesTotal": 0},
        )

    def test_truncation_meta_surfaces_totals_past_the_per_seed_cap(self) -> None:
        # 20 candidate upstream partners with SQL-reported total 655; per
        # hop limit trims to LINEAGE_GRAPH_PER_HOP_LIMIT (16) shown.
        rows = [
            {
                "target_table_full_name": "main.emet.run_history",
                "source_table_full_name": f"main.demo.partner_{idx:03d}",
                "seed_total_edges": 655,
            }
            for idx in range(20)
        ]
        with patch("axiom.services.lineage.graph_node_for_asset", side_effect=_fake_node):
            graph = lineage_service.build_data_graph(
                _GraphUC(upstream_rows=rows), object(), "main.emet.run_history"
            )
        truncation = graph["meta"]["truncation"]
        shown = lineage_service.LINEAGE_GRAPH_PER_HOP_LIMIT
        self.assertEqual(truncation["edgesShown"], shown)
        self.assertEqual(truncation["edgesTotal"], 655)
        self.assertEqual(truncation["nodesShown"], 1 + shown)
        self.assertEqual(truncation["nodesTotal"], 1 + 655)
        self.assertTrue(graph["meta"]["upstreamTruncated"])

    def test_degraded_payload_expires_after_short_ttl_not_300s(self) -> None:
        uc = _GraphUC()
        calls: list[int] = []

        def fake_build(*_a, **_k):
            calls.append(1)
            return {
                "fqn": "main.a.b",
                "buildState": "degraded" if len(calls) == 1 else "ok",
            }

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            first = lineage_service.lineage_payload(uc, object(), "main.a.b")
            self.assertEqual(first["buildState"], "degraded")
            # Within the 15s degraded TTL the cached failure is reused
            # (avoids hammering a struggling warehouse)...
            again = lineage_service.lineage_payload(uc, object(), "main.a.b")
            self.assertEqual(again["buildState"], "degraded")
            self.assertEqual(len(calls), 1)
            # ...but once the short TTL lapses the build RETRIES — the old
            # behavior pinned the failure for the full 300s TTL.
            key = lineage_service.lineage_cache_key(uc, "main.a.b")
            fetched_at, value = lineage_service._TTL_CACHE[key]
            lineage_service._TTL_CACHE[key] = (
                fetched_at - lineage_service.LINEAGE_DEGRADED_CACHE_TTL_S - 1,
                value,
            )
            retried = lineage_service.lineage_payload(uc, object(), "main.a.b")
            self.assertEqual(retried["buildState"], "ok")
            self.assertEqual(len(calls), 2)

    def test_successful_payload_keeps_the_long_ttl(self) -> None:
        uc = _GraphUC()
        calls: list[int] = []

        def fake_build(*_a, **_k):
            calls.append(1)
            return {"fqn": "main.a.b", "buildState": "ok"}

        with patch("axiom.services.lineage._build_lineage_payload", side_effect=fake_build):
            lineage_service.lineage_payload(uc, object(), "main.a.b")
            key = lineage_service.lineage_cache_key(uc, "main.a.b")
            fetched_at, value = lineage_service._TTL_CACHE[key]
            # Age it past the degraded TTL but inside the 300s success TTL.
            lineage_service._TTL_CACHE[key] = (fetched_at - 60, value)
            lineage_service.lineage_payload(uc, object(), "main.a.b")
        self.assertEqual(len(calls), 1)

    def test_cached_lineage_payload_peek_honors_degraded_ttl(self) -> None:
        uc = _GraphUC()
        key = lineage_service.lineage_cache_key(uc, "main.a.b")
        import time as _time

        lineage_service._TTL_CACHE[key] = (
            _time.time() - lineage_service.LINEAGE_DEGRADED_CACHE_TTL_S - 1,
            {"fqn": "main.a.b", "buildState": "degraded"},
        )
        self.assertIsNone(lineage_service.cached_lineage_payload(uc, "main.a.b"))


class ColumnTableContradictionTests(unittest.TestCase):
    """Finding 7 — columnLineage upstream entries can never coexist with an
    authoritative 0-upstream table graph."""

    def setUp(self) -> None:
        lineage_service._TTL_CACHE.clear()

    def _payload_with(self, *, batch_fails: bool, upstream_rows=None):
        uc = _GraphUC(raise_error=batch_fails, upstream_rows=upstream_rows or [])
        column_payload = {
            "upstream": [
                {
                    "column": "run_id",
                    "sources": [{"assetFqn": "main.demo.users", "column": "id"}],
                }
            ],
            "downstream": [],
            "meta": {"limit": 250, "truncated": False},
        }
        operational_payload = {"nodes": [], "edges": [], "meta": {}}
        with patch(
            "axiom.services.lineage.graph_node_for_asset", side_effect=_fake_node
        ), patch(
            "axiom.services.lineage._column_lineage_payload",
            return_value=column_payload,
        ), patch(
            "axiom.services.lineage.build_operational_graph",
            return_value=operational_payload,
        ):
            return lineage_service._build_lineage_payload(
                uc, object(), "main.emet.run_history"
            )

    def test_failed_table_graph_with_column_upstream_is_marked_degraded(self) -> None:
        payload = self._payload_with(batch_fails=True)
        self.assertTrue(payload["columnLineage"]["upstream"])
        upstream_nodes = [
            node
            for node in payload["graphs"]["data"]["nodes"]
            if node.get("role") == "source"
        ]
        # The contradiction (column upstream present, table upstream empty)
        # must carry the degraded marker — never an authoritative empty.
        self.assertTrue(
            upstream_nodes
            or payload["buildState"] == "degraded"
            or payload["graphs"]["data"]["meta"]["truncation"]["edgesTotal"] > 0
        )
        self.assertEqual(payload["buildState"], "degraded")
        self.assertIn(
            "Lineage query failed; showing cached/partial data.",
            payload["buildWarnings"],
        )

    def test_healthy_build_with_column_upstream_has_upstream_nodes(self) -> None:
        payload = self._payload_with(
            batch_fails=False,
            upstream_rows=[
                {
                    "target_table_full_name": "main.emet.run_history",
                    "source_table_full_name": "main.demo.users",
                    "seed_total_edges": 1,
                }
            ],
        )
        self.assertTrue(payload["columnLineage"]["upstream"])
        upstream_nodes = [
            node
            for node in payload["graphs"]["data"]["nodes"]
            if node.get("role") == "source"
        ]
        self.assertGreaterEqual(len(upstream_nodes), 1)
        self.assertEqual(payload["buildState"], "ok")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
