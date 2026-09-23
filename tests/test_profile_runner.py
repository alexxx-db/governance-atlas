from __future__ import annotations

import unittest
from typing import Any, Dict, List


class FakeFrame:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        for i, row in enumerate(self._rows):
            yield i, row

    @property
    def iloc(self):
        rows = self._rows

        class _Indexer:
            def __getitem__(self, idx):
                return rows[idx]

        return _Indexer()


class FakeUC:
    """Scripts responses per-query-substring so the test can specify
    exactly what UC returns for each column-metric query."""

    def __init__(self, responses: Dict[str, List[Dict[str, Any]]]):
        self._responses = responses

    def query_df(self, sql: str):
        text = " ".join(sql.split()).lower()
        for key, rows in self._responses.items():
            if key.lower() in text:
                return FakeFrame(rows)
        return FakeFrame([])


class FakeStore:
    def __init__(self) -> None:
        self.runs: List[Dict[str, Any]] = []
        self.table_metrics: List[Dict[str, Any]] = []
        self.col_metrics: List[Dict[str, Any]] = []
        self.finalized: List[Dict[str, Any]] = []

    def insert_profile_run(self, **kwargs) -> None:
        self.runs.append(kwargs)

    def insert_profile_table_metric(self, **kwargs) -> None:
        self.table_metrics.append(kwargs)

    def insert_profile_column_metric(self, **kwargs) -> None:
        self.col_metrics.append(kwargs)

    def finalize_profile_run(self, **kwargs) -> None:
        self.finalized.append(kwargs)


class RunProfileTests(unittest.TestCase):
    def test_happy_path_writes_run_table_and_column_metrics(self) -> None:
        from atlas.services.profile_runner import run_profile

        uc = FakeUC(
            {
                "select count(*) as row_count": [{"row_count": 1000}],
                # One aggregate row for all columns, aliased by column index.
                "approx_count_distinct": [{
                    "sampled_rows": 1000,
                    "n0": 0, "d0": 999, "mn0": 1, "mx0": 999, "av0": 500, "sd0": 100,
                    "n1": 50, "d1": 200, "mn1": 1.5, "mx1": 99.5, "av1": 42.7, "sd1": 5.0,
                    "n2": 0, "d2": 4,
                }],
            }
        )
        store = FakeStore()
        columns = [
            {"name": "customer_id", "type": "bigint"},
            {"name": "amount", "type": "double"},
            {"name": "region", "type": "string"},
        ]
        result = run_profile(
            store=store,
            uc_client=uc,
            asset_fqn="main.sales.orders",
            columns=columns,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(store.runs), 1)
        self.assertEqual(len(store.table_metrics), 1)
        self.assertEqual(store.table_metrics[0]["row_count"], 1000)
        # One metric per column
        self.assertEqual(result.column_metrics_written, 3)
        self.assertEqual(len(store.col_metrics), 3)
        amount = next(m for m in store.col_metrics if m["column_name"] == "amount")
        self.assertAlmostEqual(amount["mean_value"], 42.7)
        self.assertAlmostEqual(amount["null_fraction"], 0.05)
        region = next(m for m in store.col_metrics if m["column_name"] == "region")
        self.assertIsNone(region["mean_value"])  # no numeric metric for string
        self.assertEqual(len(store.finalized), 1)
        self.assertEqual(store.finalized[0]["status"], "succeeded")

    def test_column_query_failures_still_write_row(self) -> None:
        from atlas.services.profile_runner import run_profile

        class FlakyUC:
            def __init__(self):
                self.calls = 0

            def query_df(self, sql: str):
                self.calls += 1
                if "count(*)" in sql.lower():
                    return FakeFrame([{"row_count": 10}])
                if self.calls % 2 == 0:
                    raise RuntimeError("transient")
                return FakeFrame([{"nulls": 0, "distinct_count": 5}])

        store = FakeStore()
        result = run_profile(
            store=store,
            uc_client=FlakyUC(),
            asset_fqn="main.gov.things",
            columns=[{"name": "a", "type": "string"}, {"name": "b", "type": "string"}],
        )
        # Both columns should have rows written even when some
        # metric sub-queries fail.
        self.assertEqual(result.column_metrics_written, 2)
        self.assertEqual(result.status, "succeeded")

    def test_single_bounded_query_with_quoted_identifiers(self) -> None:
        from atlas.services import profile_runner

        seen: List[str] = []

        class RecordingUC:
            def query_df(self, sql: str):
                seen.append(sql)
                if "as row_count" in sql.lower():
                    return FakeFrame([{"row_count": profile_runner.PROFILE_SAMPLE_ROWS * 10}])
                return FakeFrame([{"sampled_rows": 1}])

        profile_runner.run_profile(
            store=FakeStore(),
            uc_client=RecordingUC(),
            asset_fqn="main.sales.orders",
            columns=[{"name": "a`b", "type": "int"}, {"name": "c", "type": "string"}],
        )
        # count(*) + one aggregate for all columns (was up to 3 per column).
        self.assertEqual(len(seen), 2)
        self.assertIn("`main`.`sales`.`orders`", seen[0])
        self.assertIn(f"LIMIT {profile_runner.PROFILE_SAMPLE_ROWS}", seen[1])
        self.assertIn("`a``b`", seen[1])

    def test_respects_max_columns_cap(self) -> None:
        from atlas.services.profile_runner import run_profile

        uc = FakeUC({"count(*)": [{"row_count": 5}]})
        store = FakeStore()
        columns = [{"name": f"c{i}", "type": "int"} for i in range(50)]
        run_profile(
            store=store,
            uc_client=uc,
            asset_fqn="main.t.t",
            columns=columns,
            max_columns=4,
        )
        self.assertEqual(len(store.col_metrics), 4)

    def test_run_insert_failure_short_circuits(self) -> None:
        from atlas.services.profile_runner import run_profile

        class FailingStore(FakeStore):
            def insert_profile_run(self, **kwargs):
                raise RuntimeError("boom")

        result = run_profile(
            store=FailingStore(),
            uc_client=FakeUC({}),
            asset_fqn="main.x.y",
            columns=[{"name": "a", "type": "int"}],
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("profile_runs insert failed", result.error)


if __name__ == "__main__":
    unittest.main()
