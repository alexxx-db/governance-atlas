from __future__ import annotations

import unittest
from unittest.mock import patch

from axiom import store as store_module
from axiom.store import GovernanceStore
from tests.test_governance_workflow import FakeUC


class _FailingScriptUC(FakeUC):
    def execute(self, sql: str) -> None:
        if sql.startswith("BEGIN"):
            raise RuntimeError("[PARSE_SYNTAX_ERROR] Syntax error at or near 'BEGIN'")
        super().execute(sql)


class WriteBatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._enabled = patch.dict(store_module._SCRIPT_BATCHING, {"enabled": True})
        self._enabled.start()

    def tearDown(self) -> None:
        self._enabled.stop()

    def test_workflow_request_writes_are_one_script_call(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")
        store.create_change_request(
            created_by="writer@example.com",
            uc_full_name="main.sales.orders",
            new_comment="Update description: Add owner context",
            actor_role="writer",
        )
        scripts = [sql for sql in uc.executed if sql.startswith("BEGIN")]
        self.assertEqual(len(scripts), 1)
        script = scripts[0]
        for table in ("threads", "thread_posts", "tasks"):
            self.assertIn(f"INSERT INTO `main`.`axiom`.`{table}`", script)
        self.assertEqual(script.count("INSERT INTO `main`.`axiom`.`activity_events`"), 2)
        self.assertTrue(script.rstrip().endswith("END"))

    def test_nothing_is_sent_if_python_fails_inside_the_batch(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")
        with self.assertRaises(ValueError):
            with store._batched_writes():
                store._exec_write("INSERT INTO t VALUES (1)")
                store._exec_write("INSERT INTO t VALUES (2)")
                raise ValueError("boom")
        self.assertEqual(uc.executed, [])
        store._exec_write("INSERT INTO t VALUES (3)")
        self.assertEqual(uc.executed, ["INSERT INTO t VALUES (3)"])

    def test_single_statement_is_sent_unwrapped(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")
        with store._batched_writes():
            store._exec_write("UPDATE t SET a = 1")
        self.assertEqual(uc.executed, ["UPDATE t SET a = 1"])

    def test_flush_sends_pending_and_keeps_batching(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")
        with store._batched_writes():
            store._exec_write("INSERT INTO t VALUES (1)")
            store._exec_write("INSERT INTO t VALUES (2)")
            store._flush_pending_writes()
            self.assertEqual(len(uc.executed), 1)
            store._exec_write("INSERT INTO t VALUES (3)")
        self.assertEqual(uc.executed[-1], "INSERT INTO t VALUES (3)")

    def test_falls_back_to_single_statements_when_scripting_unsupported(self) -> None:
        uc = _FailingScriptUC()
        store = GovernanceStore(uc, "main", "axiom")
        with store._batched_writes():
            store._exec_write("INSERT INTO t VALUES (1)")
            store._exec_write("INSERT INTO t VALUES (2)")
        self.assertEqual(uc.executed, ["INSERT INTO t VALUES (1)", "INSERT INTO t VALUES (2)"])
        self.assertFalse(store_module._SCRIPT_BATCHING["enabled"])

    def test_other_script_errors_are_raised_not_replayed(self) -> None:
        class _Boom(FakeUC):
            def execute(self, sql: str) -> None:
                raise RuntimeError("DELTA_CONCURRENT_APPEND")

        store = GovernanceStore(_Boom(), "main", "axiom")
        with self.assertRaises(RuntimeError):
            with store._batched_writes():
                store._exec_write("INSERT INTO t VALUES (1)")
                store._exec_write("INSERT INTO t VALUES (2)")
        self.assertTrue(store_module._SCRIPT_BATCHING["enabled"])


if __name__ == "__main__":
    unittest.main()
