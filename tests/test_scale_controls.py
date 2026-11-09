from __future__ import annotations

import re
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from axiom import uc as uc_module
from axiom import store as store_module
from axiom.services import assets as asset_service
from axiom.services import live_metadata

ROOT = Path(__file__).resolve().parents[1]


def _bare_client() -> uc_module.UCSQLClient:
    client = object.__new__(uc_module.UCSQLClient)
    client.warehouse_id = "wh-test"
    return client


class StatementConcurrencyTests(unittest.TestCase):
    def test_cap_bounds_in_flight_statements(self):
        client = _bare_client()
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def fake_run(self, statement, catalog=None, schema=None, timeout_s=30):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1
            return pd.DataFrame()

        with mock.patch.object(uc_module, "_STATEMENT_SLOTS", threading.BoundedSemaphore(2)), \
                mock.patch.object(uc_module.UCSQLClient, "_query_df_unbounded", fake_run):
            threads = [threading.Thread(target=client.query_df, args=("SELECT 1",)) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(state["peak"], 2)

    def test_slot_released_when_statement_fails(self):
        client = _bare_client()
        slots = threading.BoundedSemaphore(1)

        def failing(self, *args, **kwargs):
            raise TimeoutError("boom")

        with mock.patch.object(uc_module, "_STATEMENT_SLOTS", slots), \
                mock.patch.object(uc_module.UCSQLClient, "_query_df_unbounded", failing):
            for _ in range(3):
                with self.assertRaises(TimeoutError):
                    client.query_df("SELECT 1", timeout_s=1)
        self.assertTrue(slots.acquire(blocking=False))
        slots.release()

    def test_waiting_for_a_slot_times_out(self):
        client = _bare_client()
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        with mock.patch.object(uc_module, "_STATEMENT_SLOTS", slots):
            with self.assertRaises(TimeoutError):
                client.query_df("SELECT 1", timeout_s=1)
        slots.release()

    def test_only_writes_bump_generation(self):
        client = _bare_client()
        with mock.patch.object(
            uc_module.UCSQLClient, "_query_df_unbounded", lambda self, *a, **k: pd.DataFrame()
        ):
            before = uc_module.write_generation()
            client.query_df("  SELECT 1")
            client.query_df("WITH x AS (SELECT 1) SELECT * FROM x")
            client.query_df("SHOW CATALOGS")
            self.assertEqual(uc_module.write_generation(), before)
            client.query_df("MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN DELETE")
            self.assertGreater(uc_module.write_generation(), before)


class TaskStatusPredicateTests(unittest.TestCase):
    CASES = [
        ("open", None),
        ("in_progress", ""),
        ("", None),
        ("resolved", None),
        ("Closed", None),
        ("open", "approved"),
        ("rejected", None),
        ("resolved", "rejected"),
        (" REJECTED ", "approved"),
        ("open", "rejected"),
    ]

    def _sql_eval(self, predicate: str, task_status, resolution) -> bool:
        def norm(value):
            return repr(str(value or "").strip().lower())

        expr = predicate
        expr = expr.replace("lower(trim(COALESCE(t.status, '')))", norm(task_status))
        expr = expr.replace("lower(trim(COALESCE(t.resolution_code, '')))", norm(resolution))
        expr = re.sub(r"IN \(([^)]*)\)", r"in (\1)", expr)
        expr = expr.replace(" = ", " == ").replace("NOT ", "not ").replace(" OR ", " or ")
        expr = expr.replace(" AND ", " and ").replace("FALSE", "False")
        return bool(eval(expr))  # noqa: S307 - test-only evaluation of generated SQL

    def test_sql_predicate_matches_python_mapping(self):
        for status in ("pending", "approved", "rejected", "unknown"):
            predicate = store_module._task_request_status_predicate(status)
            for task_status, resolution in self.CASES:
                expected = store_module._request_status_from_task(task_status, resolution) == status
                self.assertEqual(
                    self._sql_eval(predicate, task_status, resolution),
                    expected,
                    (status, task_status, resolution),
                )


class _RecordingUC:
    tracks_writes = True

    def __init__(self):
        self.statements: list[str] = []
        self.frames: dict[str, pd.DataFrame] = {}

    def query_df(self, statement, **kwargs):
        self.statements.append(statement)
        if not uc_module.is_read_only_statement(statement):
            uc_module._bump_write_generation()
            return pd.DataFrame()
        for marker, frame in self.frames.items():
            if marker in statement:
                return frame
        return pd.DataFrame()

    def execute(self, statement, **kwargs):
        self.query_df(statement, **kwargs)


class StoreReadCacheTests(unittest.TestCase):
    def setUp(self):
        self.uc = _RecordingUC()
        self.uc.frames["glossary_terms"] = pd.DataFrame(
            [
                {"term_id": "a", "name": "A", "status": "approved"},
                {"term_id": "b", "name": "B", "status": "draft"},
            ]
        )
        self.store = store_module.GovernanceStore(self.uc, "main", "axiom")

    def _glossary_reads(self) -> int:
        return sum("glossary_terms" in s and s.lstrip().startswith("SELECT") for s in self.uc.statements)

    def test_complete_result_serves_other_limits_and_statuses(self):
        first = self.store.list_glossary_terms(limit=500)
        again = self.store.list_glossary_terms(limit=5000)
        drafts = self.store.list_glossary_terms(status="draft", limit=50)
        self.assertEqual(self._glossary_reads(), 1)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(again), 2)
        self.assertEqual(drafts["term_id"].tolist(), ["b"])

    def test_truncated_result_does_not_serve_larger_limit(self):
        self.store.list_glossary_terms(limit=2)
        self.store.list_glossary_terms(limit=1)
        self.assertEqual(self._glossary_reads(), 1)
        self.store.list_glossary_terms(limit=10)
        self.assertEqual(self._glossary_reads(), 2)

    def test_write_invalidates_cache(self):
        self.store.list_glossary_terms(limit=500)
        self.uc.execute("UPDATE `main`.`axiom`.`glossary_terms` SET status = 'approved'")
        self.store.list_glossary_terms(limit=500)
        self.assertEqual(self._glossary_reads(), 2)

    def test_returned_frames_are_copies(self):
        frame = self.store.list_glossary_terms(limit=500)
        frame.loc[0, "name"] = "mutated"
        self.assertEqual(self.store.list_glossary_terms(limit=500).loc[0, "name"], "A")

    def test_clients_without_write_tracking_are_not_cached(self):
        self.uc.tracks_writes = False
        self.store.list_glossary_terms(limit=500)
        self.store.list_glossary_terms(limit=500)
        self.assertEqual(self._glossary_reads(), 2)

    def test_ttl_zero_disables_cache(self):
        with mock.patch.dict("os.environ", {"AXIOM_STORE_READ_CACHE_TTL_S": "0"}):
            self.store.list_glossary_terms(limit=500)
            self.store.list_glossary_terms(limit=500)
        self.assertEqual(self._glossary_reads(), 2)

    def test_status_is_pushed_into_task_query(self):
        self.store.list_change_requests(status="pending", limit=25)
        task_sql = next(s for s in self.uc.statements if "`tasks` t" in s)
        self.assertIn("NOT (lower(trim(COALESCE(t.status, ''))) = 'rejected'", task_sql)
        self.assertIn("LIMIT 25", task_sql)
        legacy_sql = next(s for s in self.uc.statements if "`change_requests`" in s)
        self.assertIn("WHERE status = 'pending'", legacy_sql)
        self.assertNotIn("SELECT *", legacy_sql)


class LineageCatalogDiscoveryTests(unittest.TestCase):
    def setUp(self):
        live_metadata._TTL_CACHE.clear()

    def tearDown(self):
        live_metadata._TTL_CACHE.clear()

    def test_show_catalogs_and_lineage_scan_run_concurrently(self):
        barrier = threading.Barrier(2, timeout=2)

        class FakeUC:
            warehouse_id = "wh-concurrent"

            def list_catalogs(self):
                barrier.wait()
                return pd.DataFrame({"catalog": ["ops_governance"]})

            def list_lineage_catalogs(self):
                barrier.wait()
                return pd.DataFrame({"catalog": ["lineage_only"]})

        with mock.patch.dict("os.environ", {"AXIOM_DISCOVERY_SKIP_CATALOG_TYPES": ""}):
            catalogs = live_metadata.cached_catalogs(FakeUC())
        self.assertIn("ops_governance", catalogs)
        self.assertIn("lineage_only", catalogs)

    def test_lineage_scan_is_shared_and_cached(self):
        calls = {"n": 0}

        class FakeUC:
            warehouse_id = "wh-shared"

            def list_catalogs(self):
                return pd.DataFrame({"catalog": ["main"]})

            def list_lineage_catalogs(self):
                calls["n"] += 1
                return pd.DataFrame({"catalog": ["main", "system"]})

        fake = FakeUC()
        with mock.patch.dict("os.environ", {"AXIOM_DISCOVERY_SKIP_CATALOG_TYPES": ""}):
            live_metadata.cached_catalogs(fake)
        observed = asset_service.lineage_observed_catalogs(fake, hidden_catalogs=["system"])
        self.assertEqual(observed, ["main"])
        self.assertEqual(calls["n"], 1)

    def test_empty_lineage_result_retries_quickly(self):
        calls = {"n": 0}

        class FakeUC:
            warehouse_id = "wh-empty"

            def list_lineage_catalogs(self):
                calls["n"] += 1
                return pd.DataFrame()

        fake = FakeUC()
        self.assertEqual(live_metadata.cached_lineage_catalogs(fake), [])
        key = "lineage_catalogs:" + live_metadata._warehouse_key(fake)
        stamped, value = live_metadata._TTL_CACHE[key]
        live_metadata._TTL_CACHE[key] = (stamped - 20, value)
        live_metadata.cached_lineage_catalogs(fake)
        self.assertEqual(calls["n"], 2)


class DeploymentConfigTests(unittest.TestCase):
    def test_job_environment_pins_match_requirements(self):
        pins = {}
        for line in (ROOT / "requirements.txt").read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if "==" in line:
                name, version = line.split("==", 1)
                pins[re.sub(r"\[.*\]", "", name).lower()] = version
        bundle = (ROOT / "databricks.yml").read_text()
        job_deps = re.findall(r"^\s+- ([A-Za-z0-9_.\-\[\],]+)([<>=!~]=?)([^\s]+)\s*$", bundle, re.M)
        self.assertTrue(job_deps)
        for name, operator, version in job_deps:
            base = re.sub(r"\[.*\]", "", name).lower()
            if base not in pins:
                continue
            self.assertEqual((operator, version), ("==", pins[base]), name)

    def test_runtime_runs_a_single_uvicorn_worker(self):
        source = (ROOT / "run_app.py").read_text()
        self.assertRegex(source, r'"--workers",\s*"1"')


if __name__ == "__main__":
    unittest.main()
