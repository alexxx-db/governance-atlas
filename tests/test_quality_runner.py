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


class ScriptedUC:
    cache_scope = "obo-test"  # per-user client (custom SQL requires it)

    def __init__(self, table):
        # table: list of (substring, rows) in registration order.
        self._table = table

    def query_df(self, sql: str, **_kwargs):
        lower = " ".join(sql.split()).lower()
        for needle, rows in self._table:
            if needle.lower() in lower:
                return FakeFrame(rows)
        return FakeFrame([])


class FakeStore:
    def __init__(self) -> None:
        self.runs: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []
        self.finalized: List[Dict[str, Any]] = []

    def insert_quality_run(self, **kwargs) -> None:
        self.runs.append(kwargs)

    def insert_quality_run_result(self, **kwargs) -> None:
        self.results.append(kwargs)

    def finalize_quality_run(self, **kwargs) -> None:
        self.finalized.append(kwargs)


def _spec(**kwargs):
    from atlas.services.quality_runner import TestCaseSpec
    return TestCaseSpec(**kwargs)


class RunQualitySuiteTests(unittest.TestCase):
    def test_row_count_passes_within_range(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([("count(*)", [{"c": 500}])])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="c1",
                test_key="row_count",
                entity_fqn="main.t.t",
                parameters={"minRows": 100, "maxRows": 1000},
            )],
        )
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(store.finalized[0]["status"], "succeeded")
        self.assertEqual(store.finalized[0]["summary"]["passed"], 1)
        self.assertEqual(store.results[0]["outcome"], "passed")
        self.assertEqual(store.results[0]["metric_value"], 500)

    def test_row_count_fails_below_minimum(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([("count(*)", [{"c": 50}])])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="c1",
                test_key="row_count",
                entity_fqn="main.t.t",
                parameters={"minRows": 100},
            )],
        )
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.status, "partial")
        self.assertEqual(store.finalized[0]["status"], "partial")
        self.assertEqual(store.results[0]["outcome"], "failed")

    def test_null_fraction_passes_under_threshold(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([
            ("sum(case when", [{"nulls": 2, "total": 100}]),
        ])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="cn",
                test_key="null_fraction",
                entity_fqn="main.t.t",
                column_name="email",
                parameters={"threshold": 0.05},
            )],
        )
        self.assertEqual(result.passed, 1)
        self.assertAlmostEqual(store.results[0]["metric_value"], 0.02)

    def test_unique_fails_on_duplicates(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([("count(distinct", [{"total": 100, "distinct_count": 95}])])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="cu",
                test_key="unique",
                entity_fqn="main.t.t",
                column_name="id",
                parameters={},
            )],
        )
        self.assertEqual(result.failed, 1)
        self.assertEqual(store.results[0]["metric_value"], 5)

    def test_accepted_values_catches_violations(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([("not in", [{"violating": 3}])])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="cav",
                test_key="accepted_values",
                entity_fqn="main.t.t",
                column_name="region",
                parameters={"accepted": ["us", "eu", "apac"]},
            )],
        )
        self.assertEqual(result.failed, 1)

    def test_regex_catches_bad_emails(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([("not rlike", [{"violating": 1}])])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="cr",
                test_key="regex",
                entity_fqn="main.t.t",
                column_name="email",
                parameters={"pattern": r"^.+@.+$"},
            )],
        )
        self.assertEqual(result.failed, 1)

    def test_custom_sql_guard_rejects_non_select(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=ScriptedUC([]),
            cases=[_spec(
                case_id="cs",
                test_key="custom_sql",
                entity_fqn="main.t.t",
                parameters={"sql": "UPDATE main.t.t SET x = 1", "threshold": 0},
            )],
        )
        self.assertEqual(result.errored, 1)
        self.assertIn("guard rejected", store.results[0]["detail"])

    def test_custom_sql_passes_threshold_check(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        uc = ScriptedUC([
            ("select count", [{"c": 3}]),  # the normalized custom SQL
        ])
        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=uc,
            cases=[_spec(
                case_id="cs",
                test_key="custom_sql",
                entity_fqn="main.t.t",
                parameters={
                    "sql": "SELECT count(*) FROM main.t.t WHERE status = 'x'",
                    "op": "<=",
                    "threshold": 10,
                },
            )],
        )
        self.assertEqual(result.passed, 1)

    def test_custom_sql_refused_on_app_principal_and_limited(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        seen: List[str] = []

        class AppPrincipalUC(ScriptedUC):
            cache_scope = "app"

        spec = _spec(
            case_id="cs",
            test_key="custom_sql",
            entity_fqn="main.t.t",
            parameters={"sql": "SELECT count(*) FROM main.t.t", "threshold": 10},
        )
        store = FakeStore()
        result = run_quality_suite(store=store, uc_client=AppPrincipalUC([]), cases=[spec])
        self.assertEqual(result.errored, 1)
        self.assertIn("per-user", store.results[0]["detail"])

        class RecordingUC(ScriptedUC):
            def query_df(self, sql: str, **_kwargs):
                seen.append(sql)
                return FakeFrame([{"c": 1}])

        run_quality_suite(store=FakeStore(), uc_client=RecordingUC([]), cases=[spec])
        self.assertTrue(seen[0].rstrip().endswith("LIMIT 1"))

    def test_unknown_test_key_skipped(self) -> None:
        from atlas.services.quality_runner import run_quality_suite

        store = FakeStore()
        result = run_quality_suite(
            store=store,
            uc_client=ScriptedUC([]),
            cases=[_spec(case_id="c", test_key="nope", entity_fqn="x", parameters={})],
        )
        self.assertEqual(result.skipped, 1)
        self.assertEqual(store.results[0]["outcome"], "skipped")


class IdentifierEscapingTests(unittest.TestCase):
    def test_safe_table_quotes_three_part_fqn(self) -> None:
        from atlas.services.quality_runner import _safe_table

        self.assertEqual(_safe_table("cat.sch.tbl"), "`cat`.`sch`.`tbl`")

    def test_safe_col_escapes_backticks(self) -> None:
        from atlas.services.quality_runner import _safe_col

        # A malicious column name cannot break out of the backtick quoting.
        self.assertEqual(_safe_col("x`) AS a, (SELECT 1"), "`x``) AS a, (SELECT 1`")

    def test_null_count_query_quotes_identifiers(self) -> None:
        from atlas.services.quality_runner import _eval_null_count
        from atlas.services.quality_runner import TestCaseSpec

        captured = {}

        class CapturingUC:
            def query_df(self, sql: str, **_kwargs):
                captured["sql"] = sql
                return FakeFrame([{"nulls": 0, "total": 10}])

        _eval_null_count(
            CapturingUC(),
            TestCaseSpec(
                case_id="c",
                test_key="null_count",
                entity_fqn="cat.sch.tbl",
                parameters={"threshold": 0},
                column_name="email",
            ),
        )
        self.assertIn("`cat`.`sch`.`tbl`", captured["sql"])
        self.assertIn("`email`", captured["sql"])
        self.assertNotIn("FROM cat.sch.tbl", captured["sql"])


if __name__ == "__main__":
    unittest.main()
