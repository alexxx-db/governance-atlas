from __future__ import annotations

import unittest

from scripts import benchmark_axiom_genie_space as benchmark


class GenieBenchmarkTests(unittest.TestCase):
    def test_evaluate_fails_sentinel_fallback_sql(self) -> None:
        payload = {
            "answer": "No data quality issues found for critical assets.",
            "confidence": "genie-grounded",
            "evidence": [
                {
                    "type": "genie_query",
                    "metric": "generatedSql",
                    "rowCount": 0,
                    "totalRowCount": 0,
                    "sql": (
                        "SELECT quality.asset_fqn FROM emet.axiom_ai.axiom_ai_quality_latest quality "
                        "UNION ALL SELECT 'unavailable'"
                    ),
                }
            ],
        }

        result = benchmark._evaluate(
            payload,
            ["quality"],
            question="Show me data quality issues impacting critical assets.",
            catalog="emet",
            store_schema="axiom",
            ai_schema="axiom_ai",
        )

        self.assertFalse(result["passed"])
        self.assertIn("synthetic_no_result_sql_returned", result["failures"])

    def test_evaluate_fails_sentinel_result_rows(self) -> None:
        payload = {
            "answer": "No data quality issues found for critical assets.",
            "confidence": "genie-grounded",
            "warnings": ["Removed Genie sentinel no-result row for stmt-1; no governed result row was counted."],
            "evidence": [
                {
                    "type": "genie_query",
                    "metric": "generatedSql",
                    "rowCount": 0,
                    "totalRowCount": 0,
                    "sql": "SELECT asset_fqn FROM emet.axiom_ai.axiom_ai_quality_latest",
                    "resultRows": [
                        {
                            "asset_fqn": "unavailable",
                            "column_name": None,
                            "detail": "No data quality issues found for critical assets.",
                        }
                    ],
                }
            ],
        }

        result = benchmark._evaluate(
            payload,
            ["quality"],
            question="Show me data quality issues impacting critical assets.",
            catalog="emet",
            store_schema="axiom",
            ai_schema="axiom_ai",
        )

        self.assertFalse(result["passed"])
        self.assertIn("synthetic_no_result_row_returned", result["failures"])


if __name__ == "__main__":
    unittest.main()
