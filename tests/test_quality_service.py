from __future__ import annotations

import unittest

from axiom.services import quality as quality_service


class ValidateCustomSqlTests(unittest.TestCase):
    def _target(self) -> str:
        return "main.gov.orders"

    def test_rejects_empty(self) -> None:
        self.assertFalse(quality_service.validate_custom_sql("   ", target_entity_fqn=self._target()).ok)

    def test_rejects_chained_statements(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT 1 FROM main.gov.orders; SELECT 2",
            target_entity_fqn=self._target(),
        )
        self.assertFalse(r.ok)
        self.assertIn("single statement", r.reason)

    def test_rejects_non_select(self) -> None:
        r = quality_service.validate_custom_sql(
            "UPDATE main.gov.orders SET x = 1",
            target_entity_fqn=self._target(),
        )
        self.assertFalse(r.ok)

    def test_rejects_dml_tokens(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT 1 FROM main.gov.orders; DROP TABLE main.gov.orders",
            target_entity_fqn=self._target(),
        )
        self.assertFalse(r.ok)

    def test_rejects_missing_target_reference(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT count(*) FROM main.gov.customers",
            target_entity_fqn=self._target(),
        )
        self.assertFalse(r.ok)
        self.assertIn("must reference the target entity", r.reason)

    def test_accepts_valid_select_against_target(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT count(*) FROM main.gov.orders WHERE customer_id IS NULL",
            target_entity_fqn=self._target(),
        )
        self.assertTrue(r.ok)
        self.assertTrue(r.normalized.upper().startswith("SELECT"))

    def test_accepts_with_cte(self) -> None:
        r = quality_service.validate_custom_sql(
            "WITH x AS (SELECT * FROM main.gov.orders) SELECT count(*) FROM x",
            target_entity_fqn=self._target(),
        )
        self.assertTrue(r.ok)

    def test_accepts_last_two_segment_reference(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT count(*) FROM gov.orders",
            target_entity_fqn=self._target(),
        )
        self.assertTrue(r.ok)

    def test_accepts_comparison_entity(self) -> None:
        r = quality_service.validate_custom_sql(
            "SELECT a.id FROM main.gov.orders a JOIN main.gov.customers c ON a.cust_id = c.id",
            target_entity_fqn=self._target(),
            allowed_comparisons=["main.gov.customers"],
        )
        self.assertTrue(r.ok)

    def test_strips_comments_before_guard(self) -> None:
        # Comment-out of DROP shouldn't let it sneak past — we strip
        # comments before checking, so this SHOULD pass (DROP is inside a
        # comment and gets removed).
        r = quality_service.validate_custom_sql(
            "SELECT 1 FROM main.gov.orders /* DROP TABLE x */",
            target_entity_fqn=self._target(),
        )
        self.assertTrue(r.ok)

    def test_hidden_dml_inside_select_is_blocked(self) -> None:
        # A SELECT with DROP embedded as an identifier — unlikely real
        # case but the guard should still reject it.
        r = quality_service.validate_custom_sql(
            "SELECT 1 FROM main.gov.orders WHERE DROP = 'x'",
            target_entity_fqn=self._target(),
        )
        self.assertFalse(r.ok)


class BudgetCheckTests(unittest.TestCase):
    def test_rejects_over_cap(self) -> None:
        self.assertFalse(
            quality_service.check_budgets(
                row_budget=quality_service.MAX_ROW_BUDGET + 1,
                byte_budget=None,
                time_budget_ms=None,
            ).ok
        )

    def test_defaults_fill_in(self) -> None:
        budget = quality_service.check_budgets(
            row_budget=None, byte_budget=None, time_budget_ms=None
        )
        self.assertTrue(budget.ok)
        self.assertEqual(budget.row_budget, quality_service.MAX_ROW_BUDGET)


class SummarizeTests(unittest.TestCase):
    def test_counts_outcomes(self) -> None:
        summary = quality_service.summarize_run_results([
            {"outcome": "passed"},
            {"outcome": "passed"},
            {"outcome": "failed"},
            {"outcome": "ERRORED"},
            {"outcome": None},
        ])
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["errored"], 1)


if __name__ == "__main__":
    unittest.main()
