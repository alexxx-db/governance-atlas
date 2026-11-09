from __future__ import annotations

import json
import re
import unittest
from typing import Any, Dict, List


class FakeFrame:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        for i, row in enumerate(self._rows):
            yield i, row


class FakeUC:
    """Tiny SQL capture double that also lets us script query_df responses."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self._initial_rows = list(rows)
        self.executed: List[str] = []
        self.queries: List[str] = []

    def query_df(self, sql: str):
        self.queries.append(sql)
        # Only serve the initial batch once (simulate drain).
        rows = self._initial_rows
        self._initial_rows = []
        return FakeFrame(rows)

    def execute(self, sql: str) -> None:
        self.executed.append(sql)


class FakeStore:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.uc = FakeUC(rows)

    def _fq(self, table: str) -> str:
        return f"`main`.`gov`.`{table}`"


class DrainQueuedBatchTests(unittest.TestCase):
    def test_drains_item_and_marks_succeeded(self) -> None:
        from axiom.services.background_runner import drain_queued_batch, WorkItemResult

        store = FakeStore(
            [
                {
                    "work_id": "w1",
                    "work_kind": "export",
                    "payload_json": json.dumps({"jobId": "j1", "assetFqns": ["a.b.c"]}),
                    "actor_email": "alice@b",
                    "actor_role": "steward",
                    "token_captured_at": None,
                    "attempt_count": 0,
                    "max_attempts": 3,
                }
            ]
        )

        def handler(item):
            return WorkItemResult(work_id=item["work_id"], status="succeeded", result={"ok": True})

        results = drain_queued_batch(store=store, handler=handler, max_items=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "succeeded")
        # We should see a claim UPDATE, a started INSERT, and final UPDATEs.
        kinds = [re.match(r"\s*(\w+)", sql).group(1).upper() for sql in store.uc.executed]
        self.assertIn("UPDATE", kinds)
        self.assertIn("INSERT", kinds)

    def test_failed_item_with_retries_goes_back_to_queued(self) -> None:
        from axiom.services.background_runner import drain_queued_batch, WorkItemResult

        store = FakeStore(
            [
                {
                    "work_id": "w1",
                    "work_kind": "export",
                    "payload_json": "{}",
                    "actor_email": "a",
                    "actor_role": "reader",
                    "token_captured_at": None,
                    "attempt_count": 0,
                    "max_attempts": 2,
                }
            ]
        )

        def handler(_):
            return WorkItemResult(work_id="w1", status="failed", detail="boom")

        results = drain_queued_batch(store=store, handler=handler, max_items=5)
        self.assertEqual(len(results), 1)
        # On retry the final UPDATE should mention status = 'queued' and
        # NOT route to dead_letters.
        sqls = "\n".join(store.uc.executed)
        self.assertIn("status = 'queued'", sqls)
        self.assertNotIn("background_dead_letters", sqls)

    def test_failed_item_at_max_attempts_routes_to_dead_letters(self) -> None:
        from axiom.services.background_runner import drain_queued_batch, WorkItemResult

        store = FakeStore(
            [
                {
                    "work_id": "w1",
                    "work_kind": "export",
                    "payload_json": "{}",
                    "actor_email": "a",
                    "actor_role": "reader",
                    "token_captured_at": None,
                    "attempt_count": 2,  # one more attempt = max
                    "max_attempts": 3,
                }
            ]
        )

        def handler(_):
            return WorkItemResult(work_id="w1", status="failed", detail="permanent")

        drain_queued_batch(store=store, handler=handler, max_items=5)
        sqls = "\n".join(store.uc.executed)
        self.assertIn("background_dead_letters", sqls)

    def test_handler_exception_maps_to_failed(self) -> None:
        from axiom.services.background_runner import drain_queued_batch

        store = FakeStore(
            [
                {
                    "work_id": "w1",
                    "work_kind": "export",
                    "payload_json": "{}",
                    "actor_email": "a",
                    "actor_role": "reader",
                    "token_captured_at": None,
                    "attempt_count": 2,
                    "max_attempts": 3,
                }
            ]
        )

        def handler(_):
            raise RuntimeError("kaboom")

        results = drain_queued_batch(store=store, handler=handler, max_items=5)
        self.assertEqual(results[0].status, "failed")
        self.assertIn("kaboom", results[0].detail)

    def test_empty_queue_returns_empty_list(self) -> None:
        from axiom.services.background_runner import drain_queued_batch

        store = FakeStore([])
        results = drain_queued_batch(store=store, handler=lambda _: None, max_items=5)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
