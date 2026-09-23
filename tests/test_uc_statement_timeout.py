"""query_df must cancel a statement that outlives its budget, so abandoned
queries stop consuming warehouse compute (and timed-out writes can't commit
after the caller has already seen an error)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from atlas import uc as uc_module


def _running(statement_id: str = "st-1") -> SimpleNamespace:
    return SimpleNamespace(statement_id=statement_id, status=SimpleNamespace(state="RUNNING"))


class QueryTimeoutCancelsTests(unittest.TestCase):
    def _client(self) -> uc_module.UCSQLClient:
        client = uc_module.UCSQLClient.__new__(uc_module.UCSQLClient)
        client.warehouse_id = "wh"
        client.w = MagicMock()
        client.w.statement_execution.execute_statement.return_value = _running()
        client.w.statement_execution.get_statement.return_value = _running()
        return client

    def test_timeout_cancels_statement(self) -> None:
        client = self._client()
        with patch.object(uc_module.time, "sleep"), patch.object(
            uc_module.time, "monotonic", side_effect=[0.0, 0.0, 1.0, 100.0, 100.0, 100.0]
        ):
            with self.assertRaisesRegex(TimeoutError, "cancelled"):
                client.query_df("SELECT 1", timeout_s=5)
        client.w.statement_execution.cancel_execution.assert_called_once_with("st-1")

    def test_wait_timeout_is_clamped_to_api_range(self) -> None:
        client = self._client()
        done = SimpleNamespace(statement_id="st-1", status=SimpleNamespace(state="SUCCEEDED"), manifest=None, result=None)
        client.w.statement_execution.execute_statement.return_value = done
        client.query_df("SELECT 1", timeout_s=120)
        kwargs = client.w.statement_execution.execute_statement.call_args.kwargs
        self.assertEqual(kwargs["wait_timeout"], "50s")
        client.w.statement_execution.cancel_execution.assert_not_called()


if __name__ == "__main__":
    unittest.main()
