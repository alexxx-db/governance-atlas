from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_synthetic_stress_validation.py"
SPEC = importlib.util.spec_from_file_location("run_synthetic_stress_validation", SCRIPT_PATH)
stress = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = stress
SPEC.loader.exec_module(stress)


class SyntheticStressContractTests(unittest.TestCase):
    def test_run_id_shape_uses_ax_stress_timestamp_and_short_sha(self) -> None:
        run_id = stress.build_run_id(
            now=datetime(2026, 4, 27, 14, 15, 16, tzinfo=timezone.utc),
            short_sha="abc1234",
        )

        self.assertEqual(run_id, "ax-stress-20260427141516-abc1234")
        self.assertRegex(run_id, stress.RUN_ID_RE)

    def test_scenario_list_covers_required_workflow_domains(self) -> None:
        domains = {scenario.domain for scenario in stress.SCENARIOS}

        self.assertTrue(
            {
                "Discovery",
                "Governance",
                "Lakebase",
                "Quality",
                "Lineage",
                "Taxonomy",
                "Genie",
                "cleanup",
            }.issubset(domains)
        )
        self.assertEqual(len(stress.SCENARIOS), len({scenario.id for scenario in stress.SCENARIOS}))

    def test_plan_uses_app_owned_test_scoped_schema_and_row_markers(self) -> None:
        plan = stress.build_plan(
            catalog="emet",
            schema_prefix="axiom_ax_stress",
            run_id="ax-stress-20260427141516-abc1234",
            rows_per_scenario=2,
            cleanup=True,
        )

        self.assertEqual(plan["schema"], "axiom_ax_stress_20260427141516_abc1234")
        self.assertEqual(plan["expectedRowCount"], len(stress.SCENARIOS) * 2)
        self.assertEqual(plan["expectedWorkflowCount"], 2)
        self.assertEqual(plan["expectedAuditEventCount"], 2 * stress.AUDIT_EVENTS_PER_WORKFLOW)
        self.assertIn(stress.APP_OWNED_MARKER, plan["setupStatements"][0])
        self.assertIn(stress.TEST_SCOPED_MARKER, plan["setupStatements"][0])
        self.assertIn(stress.CLEANUP_SAFE_MARKER, plan["setupStatements"][0])
        self.assertIn(stress.EXCLUDE_ORGANIC_MARKER, plan["setupStatements"][0])
        self.assertIn("'axiom.app_owned' = 'true'", plan["setupStatements"][1])
        self.assertIn("'axiom.test_scoped' = 'true'", plan["setupStatements"][1])
        self.assertIn("'axiom.cleanup_safe' = 'true'", plan["setupStatements"][1])
        self.assertIn("'axiom.exclude_from_organic_evidence' = 'true'", plan["setupStatements"][1])
        self.assertEqual(
            plan["tables"],
            [
                stress.VALIDATION_EVENTS_TABLE,
                stress.WORKFLOW_ENTITIES_TABLE,
                stress.WORKFLOW_AUDIT_TABLE,
            ],
        )

        for statement in plan["insertStatements"]:
            self.assertIn("`emet`.`axiom_ax_stress_20260427141516_abc1234`.`validation_events`", statement)
            self.assertIn("'ax-stress-20260427141516-abc1234'", statement)
            self.assertIn(f"'{stress.ROW_MARKER}'", statement)
            self.assertIn("true, true, true, true", statement)

    def test_plan_creates_and_mutates_customer_workflows(self) -> None:
        plan = stress.build_plan(
            catalog="emet",
            schema_prefix="axiom_ax_stress",
            run_id="ax-stress-20260427141516-abc1234",
            rows_per_scenario=1,
            cleanup=True,
        )
        workflow_sql = "\n".join(plan["workflowStatements"])

        self.assertIn("workflow_entities", workflow_sql)
        self.assertIn("workflow_audit_events", workflow_sql)
        self.assertIn("entity_kind, workflow_domain", workflow_sql)
        self.assertIn("'asset'", workflow_sql)
        self.assertIn("'governance_request'", workflow_sql)
        self.assertIn("'taxonomy_association'", workflow_sql)
        self.assertIn("'lineage_case'", workflow_sql)
        self.assertIn("'quality_run'", workflow_sql)
        self.assertIn("'genie_question'", workflow_sql)
        self.assertIn("'lakebase_mirror'", workflow_sql)
        self.assertIn("UPDATE `emet`.`axiom_ax_stress_20260427141516_abc1234`.`workflow_entities`", workflow_sql)
        self.assertIn("'request_approved'", workflow_sql)
        self.assertIn("'request_rejected'", workflow_sql)
        self.assertIn("'taxonomy_association_approved'", workflow_sql)
        self.assertIn("'lineage_degraded_asserted'", workflow_sql)
        self.assertIn("'lineage_unavailable_asserted'", workflow_sql)
        self.assertIn("'quality_run_completed'", workflow_sql)
        self.assertIn("'genie_answer_grounded'", workflow_sql)
        self.assertIn("'lakebase_mirror_succeeded'", workflow_sql)
        self.assertIn('"excludeFromOrganicEvidence":true', workflow_sql)

    def test_workflow_validation_asserts_required_customer_paths(self) -> None:
        plan = stress.build_plan(
            catalog="emet",
            schema_prefix="axiom_ax_stress",
            run_id="ax-stress-20260427141516-abc1234",
            rows_per_scenario=1,
            cleanup=True,
        )
        validation_sql = "\n".join(plan["validationStatements"])

        for metric in (
            "discovery_assets",
            "governance_approved_requests",
            "governance_rejected_requests",
            "taxonomy_approved_associations",
            "degraded_lineage_cases",
            "unavailable_lineage_cases",
            "quality_completed_runs",
            "genie_grounded_answers",
            "genie_sentinel_fallbacks",
            "lakebase_mirror_success_records",
            "lakebase_failed_writes",
            "audit_event_count",
            "distinct_audit_event_ids",
            "organic_evidence_leaks",
        ):
            self.assertIn(metric, validation_sql)
        self.assertIn("get_json_object(evidence_json, '$.sentinelFallback')", validation_sql)
        self.assertIn("workflow_audit_events", validation_sql)
        self.assertIn("ORDER BY workflow_id, event_order, event_type", validation_sql)

    def test_cleanup_has_no_unscoped_deletes_or_unscoped_schema_drop(self) -> None:
        plan = stress.build_plan(
            catalog="emet",
            schema_prefix="axiom_ax_stress",
            run_id="ax-stress-20260427141516-abc1234",
            rows_per_scenario=1,
            cleanup=True,
        )
        all_sql = "\n".join(plan["statements"]).upper()

        self.assertNotIn("DELETE FROM", all_sql)
        self.assertNotRegex(all_sql, r"\bTRUNCATE\s+(TABLE\s+)?`")
        self.assertNotIn("DROP TABLE", all_sql)
        self.assertEqual(
            plan["cleanupStatements"],
            ["DROP SCHEMA IF EXISTS `emet`.`axiom_ax_stress_20260427141516_abc1234` CASCADE"],
        )
        self.assertEqual(
            plan["cleanupVerificationStatements"],
            ["SHOW SCHEMAS IN `emet` LIKE 'axiom_ax_stress_20260427141516_abc1234'"],
        )
        with self.assertRaises(ValueError):
            stress.cleanup_statement(
                catalog="emet",
                schema="axiom",
                schema_prefix="axiom_ax_stress",
                run_id="ax-stress-20260427141516-abc1234",
            )

    def test_live_mutations_require_explicit_default_profile_and_warehouse(self) -> None:
        stress.validate_runtime_safety(
            argparse.Namespace(live=False, profile=None, warehouse_id="", catalog="emet")
        )

        with self.assertRaisesRegex(ValueError, "explicit --profile DEFAULT"):
            stress.validate_runtime_safety(
                argparse.Namespace(live=True, profile=None, warehouse_id="abc", catalog="emet")
            )
        with self.assertRaisesRegex(ValueError, "explicit --profile DEFAULT"):
            stress.validate_runtime_safety(
                argparse.Namespace(live=True, profile="DEV", warehouse_id="abc", catalog="emet")
            )
        with self.assertRaisesRegex(ValueError, "--warehouse-id"):
            stress.validate_runtime_safety(
                argparse.Namespace(live=True, profile="DEFAULT", warehouse_id="", catalog="emet")
            )

        stress.validate_runtime_safety(
            argparse.Namespace(live=True, profile="DEFAULT", warehouse_id="abc", catalog="emet")
        )

    def test_dry_run_does_not_require_databricks_or_emit_live_mode(self) -> None:
        args = stress.parse_args(
            [
                "--run-id",
                "ax-stress-20260427141516-abc1234",
                "--rows-per-scenario",
                "1",
            ]
        )
        payload = stress.run_validation(args)

        self.assertEqual(payload["mode"], "dry-run")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["profile"], "DEFAULT")
        self.assertTrue(payload["syntheticProvenance"]["excludeFromOrganicEvidence"])
        self.assertEqual(payload["plan"]["expectedRowCount"], len(stress.SCENARIOS))
        self.assertEqual(payload["plan"]["expectedWorkflowCount"], 1)
        self.assertEqual(payload["plan"]["expectedAuditEventCount"], stress.AUDIT_EVENTS_PER_WORKFLOW)
        self.assertEqual(len(payload["plan"]["cleanupStatements"]), 1)
        self.assertEqual(len(payload["plan"]["cleanupVerificationStatements"]), 1)
        self.assertTrue(payload["evaluation"]["workflow"]["passed"])
        self.assertFalse(re.search(r"\bDELETE\s+FROM\b", "\n".join(payload["plan"]["statements"]), re.I))

    def test_workflow_evaluator_rejects_missing_paths_and_synthetic_leaks(self) -> None:
        plan = stress.build_plan(
            catalog="emet",
            schema_prefix="axiom_ax_stress",
            run_id="ax-stress-20260427141516-abc1234",
            rows_per_scenario=1,
            cleanup=True,
        )
        evaluation = stress._evaluate_workflows(
            plan,
            [
                {
                    "discovery_assets": "1",
                    "governance_approved_requests": "1",
                    "governance_rejected_requests": "0",
                    "taxonomy_approved_associations": "1",
                    "degraded_lineage_cases": "1",
                    "unavailable_lineage_cases": "1",
                    "quality_completed_runs": "1",
                    "genie_grounded_answers": "1",
                    "genie_sentinel_fallbacks": "1",
                    "lakebase_mirror_success_records": "1",
                    "lakebase_succeeded_writes": "1",
                    "lakebase_failed_writes": "0",
                    "audit_event_count": str(stress.AUDIT_EVENTS_PER_WORKFLOW),
                    "distinct_audit_event_ids": str(stress.AUDIT_EVENTS_PER_WORKFLOW),
                    "audit_approved_events": "1",
                    "audit_rejected_events": "0",
                    "marker_event_count": str(len(stress.SCENARIOS)),
                    "all_entity_provenance": "1",
                    "all_audit_provenance": "1",
                    "organic_evidence_leaks": "1",
                }
            ],
        )

        self.assertFalse(evaluation["passed"])
        self.assertIn("governanceRejectedRequests_mismatch", evaluation["failures"])
        self.assertIn("genie_sentinel_fallback_detected", evaluation["failures"])
        self.assertIn("organic_evidence_leak", evaluation["failures"])


if __name__ == "__main__":
    unittest.main()
