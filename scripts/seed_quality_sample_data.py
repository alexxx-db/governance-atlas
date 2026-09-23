#!/usr/bin/env python3
"""Write backed Governance Atlas quality evidence in Databricks.

This script computes metrics from real Unity Catalog representative enterprise views and writes the
resulting quality suite, cases, run, result, alert, and audit rows to the app
control-plane tables. It is deliberately separate from frontend fixtures: every
quality result is tied to an executed Databricks SQL statement id.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_PROFILE = os.getenv("ATLAS_PROFILE", "DEFAULT")
DEFAULT_WAREHOUSE_ID = os.getenv("BUNDLE_VAR_warehouse_id") or os.getenv("DATABRICKS_WAREHOUSE_ID") or ""
DEFAULT_CATALOG = "datapact"
DEFAULT_STORE_SCHEMA = "atlas"
DEFAULT_DEMO_SCHEMA = "enterprise_metadata_ops"
SEED_PREFIX = "GOV-QUALITY-EVIDENCE"
LEGACY_SEED_PREFIX = "ga-quality-evidence"
SEED_ACTOR = "metadata.quality@entrada.ai"
SEED_SOURCE = "quality-control-plane"
LEGACY_SEED_SOURCE = "quality-northstar-seed"
RUN_ID = f"{SEED_PREFIX}-run-current"
SUITE_ID = f"{SEED_PREFIX}-suite-enterprise"


@dataclass(frozen=True)
class QualitySeedCase:
    case_id: str
    definition_id: str
    test_key: str
    display_name: str
    description: str
    entity_fqn: str
    column_name: str | None
    severity: str
    metric_sql: str
    threshold_value: float
    comparison: str
    alert_detail: str | None = None


def sql_string(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def quote_name(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def fq_name(catalog: str, schema: str, table: str | None = None) -> str:
    parts = [quote_name(catalog), quote_name(schema)]
    if table:
        parts.append(quote_name(table))
    return ".".join(parts)


def run_cli_json(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "databricks command failed").strip())
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"databricks command returned non-JSON output: {result.stdout}") from exc


def execute_sql(
    statement: str,
    *,
    profile: str,
    warehouse_id: str,
    timeout_s: int = 180,
) -> dict[str, Any]:
    payload = {
        "warehouse_id": warehouse_id,
        "statement": statement,
        "wait_timeout": "20s",
    }
    response = run_cli_json(
        [
            "databricks",
            "api",
            "post",
            "/api/2.0/sql/statements",
            "--profile",
            profile,
            "--json",
            json.dumps(payload),
            "-o",
            "json",
        ]
    )
    statement_id = response.get("statement_id")
    deadline = time.time() + timeout_s
    while response.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
        if not statement_id or time.time() > deadline:
            raise TimeoutError(f"SQL statement timed out: {statement[:160]}")
        time.sleep(2)
        response = run_cli_json(
            [
                "databricks",
                "api",
                "get",
                f"/api/2.0/sql/statements/{statement_id}",
                "--profile",
                profile,
                "-o",
                "json",
            ]
        )
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        error = status.get("error") or {}
        raise RuntimeError(error.get("message") or f"SQL statement failed: {statement[:160]}")
    return response


def result_rows(response: dict[str, Any]) -> list[list[Any]]:
    return response.get("result", {}).get("data_array") or []


def scalar_float(response: dict[str, Any]) -> float:
    rows = result_rows(response)
    if not rows or not rows[0]:
        return 0.0
    try:
        return float(rows[0][0])
    except (TypeError, ValueError):
        return 0.0


def seeded_fqn(catalog: str, demo_schema: str, table: str) -> str:
    return f"{catalog}.{demo_schema}.{table}"


def source_record_metric(catalog: str, demo_schema: str, table: str) -> str:
    return f"SELECT CAST(MAX(source_record_count) AS DOUBLE) FROM {fq_name(catalog, demo_schema, table)}"


def owner_count_metric(store_catalog: str, store_schema: str, fqn: str) -> str:
    return (
        f"SELECT CAST(COUNT(*) AS DOUBLE) FROM {fq_name(store_catalog, store_schema, 'data_owners')} "
        f"WHERE uc_full_name = {sql_string(fqn)}"
    )


def quality_cases(args: argparse.Namespace) -> tuple[QualitySeedCase, ...]:
    catalog = args.catalog
    demo_schema = args.demo_schema
    store_catalog = args.store_catalog
    store_schema = args.store_schema
    customer_profile = seeded_fqn(catalog, demo_schema, "customer_profile_coverage")
    risk_policy = seeded_fqn(catalog, demo_schema, "risk_policy_exception_register")
    return (
        QualitySeedCase(
            case_id=f"{SEED_PREFIX}-case-customer-profile-minimum-rows",
            definition_id=f"{SEED_PREFIX}-definition-row-count-minimum",
            test_key="row_count",
            display_name="Customer profile coverage has source records",
            description="Verifies that the Customer 360 coverage view is populated from UC source data.",
            entity_fqn=customer_profile,
            column_name="source_record_count",
            severity="info",
            metric_sql=source_record_metric(catalog, demo_schema, "customer_profile_coverage"),
            threshold_value=1.0,
            comparison="gte",
        ),
        QualitySeedCase(
            case_id=f"{SEED_PREFIX}-case-risk-policy-owner-count",
            definition_id=f"{SEED_PREFIX}-definition-owner-minimum",
            test_key="owner_count",
            display_name="Risk policy exception register has assigned owners",
            description="Verifies that the governed risk register has app control-plane owner assignments.",
            entity_fqn=risk_policy,
            column_name=None,
            severity="info",
            metric_sql=owner_count_metric(store_catalog, store_schema, risk_policy),
            threshold_value=2.0,
            comparison="gte",
        ),
        QualitySeedCase(
            case_id=f"{SEED_PREFIX}-case-finance-exception-zero",
            definition_id=f"{SEED_PREFIX}-definition-exception-count-zero",
            test_key="exception_count",
            display_name="Finance exception review has no open source exceptions",
            description="Flags the current finance exception population as a quality issue until reviewed.",
            entity_fqn=seeded_fqn(catalog, demo_schema, "finance_exception_review"),
            column_name="source_record_count",
            severity="error",
            metric_sql=source_record_metric(catalog, demo_schema, "finance_exception_review"),
            threshold_value=0.0,
            comparison="lte",
            alert_detail="Finance exception review contains source-backed exception rows that need steward review.",
        ),
        QualitySeedCase(
            case_id=f"{SEED_PREFIX}-case-operations-certification-backlog-zero",
            definition_id=f"{SEED_PREFIX}-definition-backlog-count-zero",
            test_key="backlog_count",
            display_name="Operations certification backlog is empty",
            description="Flags source-backed certification backlog rows that need operations stewardship.",
            entity_fqn=seeded_fqn(catalog, demo_schema, "operations_certification_backlog"),
            column_name="source_record_count",
            severity="warn",
            metric_sql=source_record_metric(catalog, demo_schema, "operations_certification_backlog"),
            threshold_value=0.0,
            comparison="lte",
            alert_detail="Operations certification backlog contains source-backed rows requiring recertification.",
        ),
        QualitySeedCase(
            case_id=f"{SEED_PREFIX}-case-risk-quality-review-zero",
            definition_id=f"{SEED_PREFIX}-definition-risk-review-count-zero",
            test_key="risk_review_count",
            display_name="Risk data quality review queue is empty",
            description="Flags source-backed risk quality review rows that need steward review.",
            entity_fqn=seeded_fqn(catalog, demo_schema, "risk_data_quality_review"),
            column_name="source_record_count",
            severity="critical",
            metric_sql=source_record_metric(catalog, demo_schema, "risk_data_quality_review"),
            threshold_value=0.0,
            comparison="lte",
            alert_detail="Risk data quality review contains source-backed rows requiring steward review.",
        ),
    )


def outcome_for(metric_value: float, threshold_value: float, comparison: str) -> str:
    if comparison == "gte":
        return "passed" if metric_value >= threshold_value else "failed"
    if comparison == "lte":
        return "passed" if metric_value <= threshold_value else "failed"
    raise ValueError(f"Unsupported comparison: {comparison}")


def computed_results(args: argparse.Namespace) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in quality_cases(args):
        response = execute_sql(case.metric_sql, profile=args.profile, warehouse_id=args.warehouse_id)
        metric_value = scalar_float(response)
        outcome = outcome_for(metric_value, case.threshold_value, case.comparison)
        statement_id = str(response.get("statement_id") or "")
        evidence = {
            "source": "databricks-sql",
            "statementId": statement_id,
            "metricSql": case.metric_sql,
            "comparison": case.comparison,
            "threshold": case.threshold_value,
            "evidenceSource": SEED_SOURCE,
        }
        rows.append(
            {
                "case": case,
                "outcome": outcome,
                "metric_value": metric_value,
                "statement_id": statement_id,
                "evidence": evidence,
                "detail": (
                    f"{case.display_name}: metric {metric_value:g} "
                    f"{case.comparison} threshold {case.threshold_value:g} => {outcome}."
                ),
            }
        )
    return rows


def definition_insert_sql(cases: Iterable[QualitySeedCase], store_catalog: str, store_schema: str) -> str:
    seen: dict[str, QualitySeedCase] = {}
    for case in cases:
        seen.setdefault(case.definition_id, case)
    rows = []
    for definition_id, case in seen.items():
        schema = json.dumps(
            {
                "metricSql": case.metric_sql,
                "comparison": case.comparison,
                "thresholdValue": case.threshold_value,
            },
            sort_keys=True,
        )
        rows.append(
            "("
            f"{sql_string(definition_id)}, "
            f"{sql_string(case.test_key)}, "
            f"{sql_string(case.display_name)}, "
            f"{sql_string(case.description)}, "
            f"{sql_string(schema)}, "
            f"{sql_string(case.severity)}, "
            "'active', current_timestamp(), "
            f"{sql_string(SEED_ACTOR)}, current_timestamp(), {sql_string(SEED_ACTOR)}, NULL"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_test_definitions")}
  (definition_id, test_key, display_name, description, parameters_schema_json,
   severity_default, state, created_at, created_by, updated_at, updated_by, retired_at)
VALUES
  {", ".join(rows)}
""".strip()


def definition_version_insert_sql(cases: Iterable[QualitySeedCase], store_catalog: str, store_schema: str) -> str:
    seen: dict[str, QualitySeedCase] = {}
    for case in cases:
        seen.setdefault(case.definition_id, case)
    rows = []
    for definition_id, case in seen.items():
        snapshot = json.dumps(
            {
                "definitionId": definition_id,
                "testKey": case.test_key,
                "displayName": case.display_name,
                "description": case.description,
                "parameters": {
                    "metricSql": case.metric_sql,
                    "comparison": case.comparison,
                    "thresholdValue": case.threshold_value,
                },
            },
            sort_keys=True,
        )
        rows.append(
            "("
            f"{sql_string(f'{definition_id}-v1')}, "
            f"{sql_string(definition_id)}, 1, {sql_string(snapshot)}, "
            f"{sql_string('Recorded from Databricks-backed quality evidence.')}, "
            f"{sql_string(SEED_ACTOR)}, current_timestamp()"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_test_definition_versions")}
  (version_id, definition_id, version_number, snapshot_json, change_summary, recorded_by, recorded_at)
VALUES
  {", ".join(rows)}
""".strip()


def suite_insert_sql(store_catalog: str, store_schema: str) -> str:
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_suites")}
  (suite_id, display_name, description, owner_entry_id, state, created_at, created_by, updated_at, updated_by)
VALUES (
  {sql_string(SUITE_ID)},
  'Enterprise metadata quality evidence',
  'Databricks-backed quality cases for the Governance Atlas development workspace.',
  NULL,
  'active',
  current_timestamp(),
  {sql_string(SEED_ACTOR)},
  current_timestamp(),
  {sql_string(SEED_ACTOR)}
)
""".strip()


def case_insert_sql(cases: Iterable[QualitySeedCase], store_catalog: str, store_schema: str) -> str:
    rows = []
    for case in cases:
        parameters = json.dumps(
            {
                "metricSql": case.metric_sql,
                "comparison": case.comparison,
                "thresholdValue": case.threshold_value,
                "evidenceSource": SEED_SOURCE,
            },
            sort_keys=True,
        )
        rows.append(
            "("
            f"{sql_string(case.case_id)}, "
            f"{sql_string(SUITE_ID)}, "
            f"{sql_string(case.definition_id)}, "
            "1, 'table', "
            f"{sql_string(case.entity_fqn)}, "
            f"{sql_string(case.column_name)}, "
            f"{sql_string(parameters)}, "
            f"{sql_string(case.severity)}, "
            "true, current_timestamp(), "
            f"{sql_string(SEED_ACTOR)}, current_timestamp(), {sql_string(SEED_ACTOR)}"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_test_cases")}
  (case_id, suite_id, definition_id, definition_version, entity_kind, entity_fqn,
   column_name, parameters_json, severity, is_enabled, created_at, created_by, updated_at, updated_by)
VALUES
  {", ".join(rows)}
""".strip()


def run_insert_sql(results: list[dict[str, Any]], store_catalog: str, store_schema: str) -> str:
    summary = {
        "passed": sum(1 for row in results if row["outcome"] == "passed"),
        "failed": sum(1 for row in results if row["outcome"] == "failed"),
        "errored": sum(1 for row in results if row["outcome"] == "errored"),
        "skipped": sum(1 for row in results if row["outcome"] == "skipped"),
        "evidenceSource": SEED_SOURCE,
    }
    status = "succeeded" if summary["failed"] == 0 and summary["errored"] == 0 else "partial"
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_runs")}
  (run_id, suite_id, trigger, status, started_at, finished_at, row_budget,
   byte_budget, time_budget_ms, error_detail, summary_json, created_at, created_by)
VALUES (
  {sql_string(RUN_ID)},
  {sql_string(SUITE_ID)},
  'manual',
  {sql_string(status)},
  current_timestamp() - INTERVAL 2 MINUTES,
  current_timestamp() - INTERVAL 1 MINUTE,
  NULL,
  NULL,
  NULL,
  NULL,
  {sql_string(json.dumps(summary, sort_keys=True))},
  current_timestamp(),
  {sql_string(SEED_ACTOR)}
)
""".strip()


def result_insert_sql(results: list[dict[str, Any]], store_catalog: str, store_schema: str) -> str:
    rows = []
    for index, row in enumerate(results, start=1):
        case: QualitySeedCase = row["case"]
        rows.append(
            "("
            f"{sql_string(f'{SEED_PREFIX}-result-{index:02d}')}, "
            f"{sql_string(RUN_ID)}, "
            f"{sql_string(case.case_id)}, "
            f"{sql_string(case.entity_fqn)}, "
            f"{sql_string(case.column_name)}, "
            f"{sql_string(row['outcome'])}, "
            f"{sql_string(case.severity)}, "
            f"{float(row['metric_value'])}, "
            f"{float(case.threshold_value)}, "
            f"{sql_string(json.dumps(row['evidence'], sort_keys=True))}, "
            f"{sql_string(row['statement_id'])}, "
            "NULL, current_timestamp() - INTERVAL 1 MINUTE, "
            f"{sql_string(row['detail'])}"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_run_results")}
  (result_id, run_id, case_id, entity_fqn, column_name, outcome, severity,
   metric_value, threshold_value, evidence_json, statement_id, row_bytes_scanned,
   executed_at, detail)
VALUES
  {", ".join(rows)}
""".strip()


def alert_insert_sql(results: list[dict[str, Any]], store_catalog: str, store_schema: str) -> str | None:
    rows = []
    alert_index = 0
    for row in results:
        if row["outcome"] == "passed":
            continue
        alert_index += 1
        case: QualitySeedCase = row["case"]
        detail = case.alert_detail or row["detail"]
        rows.append(
            "("
            f"{sql_string(f'{SEED_PREFIX}-alert-{alert_index:02d}')}, "
            f"{sql_string(RUN_ID)}, "
            f"{sql_string(case.case_id)}, "
            f"{sql_string(case.entity_fqn)}, "
            f"{sql_string(case.column_name)}, "
            f"{sql_string(case.severity)}, "
            "'new', NULL, NULL, NULL, NULL, "
            f"{sql_string(detail)}, "
            "current_timestamp(), current_timestamp()"
            ")"
        )
    if not rows:
        return None
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "quality_alerts")}
  (alert_id, run_id, case_id, entity_fqn, column_name, severity, state,
   acknowledged_by, acknowledged_at, resolved_by, resolved_at, detail, created_at, updated_at)
VALUES
  {", ".join(rows)}
""".strip()


def audit_insert_sql(results: list[dict[str, Any]], store_catalog: str, store_schema: str) -> str:
    target = next((row for row in results if row["outcome"] == "failed"), results[0] if results else {})
    target_case: QualitySeedCase | None = target.get("case") if isinstance(target.get("case"), QualitySeedCase) else None
    summary = {
        "resultCount": len(results),
        "failedCount": sum(1 for row in results if row["outcome"] == "failed"),
        "statementIds": [row["statement_id"] for row in results],
    }
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "metadata_audit_log")}
  (audit_id, entity_type, entity_id, entity_fqn, column_name, action, source,
   status, before_json, after_json, request_id, actor_email, actor_role, detail,
   created_at, created_by, updated_at, updated_by)
VALUES (
  {sql_string(f'{SEED_PREFIX}-audit-current')},
  'quality_run',
  {sql_string(RUN_ID)},
  {sql_string(target_case.entity_fqn if target_case else None)},
  {sql_string(target_case.column_name if target_case else None)},
  'quality-run-completed',
  {sql_string(SEED_SOURCE)},
  'success',
  NULL,
  {sql_string(json.dumps(summary, sort_keys=True))},
  'QA-20260502',
  {sql_string(SEED_ACTOR)},
  'admin',
  'Databricks-backed quality run evidence recorded for Governance Atlas quality monitoring.',
  current_timestamp(),
  {sql_string(SEED_ACTOR)},
  current_timestamp(),
  {sql_string(SEED_ACTOR)}
)
""".strip()


def delete_sql(store_catalog: str, store_schema: str, table: str, predicate: str) -> str:
    return f"DELETE FROM {fq_name(store_catalog, store_schema, table)} WHERE {predicate}"


def seed_statements(results: list[dict[str, Any]], args: argparse.Namespace) -> list[str]:
    cases = [row["case"] for row in results]
    store_catalog = args.store_catalog
    store_schema = args.store_schema
    statements = [
        delete_sql(store_catalog, store_schema, "quality_alerts", f"alert_id LIKE {sql_string(SEED_PREFIX + '-alert-%')} OR alert_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-alert-%')}"),
        delete_sql(
            store_catalog,
            store_schema,
            "quality_run_results",
            (
                f"run_id IN ({sql_string(RUN_ID)}, {sql_string(LEGACY_SEED_PREFIX + '-run-current')}) "
                f"OR result_id LIKE {sql_string(SEED_PREFIX + '-result-%')} "
                f"OR result_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-result-%')} "
                f"OR case_id LIKE {sql_string(SEED_PREFIX + '-case-%')} "
                f"OR case_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-case-%')}"
            ),
        ),
        delete_sql(store_catalog, store_schema, "quality_runs", f"run_id IN ({sql_string(RUN_ID)}, {sql_string(LEGACY_SEED_PREFIX + '-run-current')})"),
        delete_sql(store_catalog, store_schema, "quality_test_cases", f"case_id LIKE {sql_string(SEED_PREFIX + '-case-%')} OR case_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-case-%')}"),
        delete_sql(store_catalog, store_schema, "quality_suites", f"suite_id IN ({sql_string(SUITE_ID)}, {sql_string(LEGACY_SEED_PREFIX + '-suite-enterprise')})"),
        delete_sql(store_catalog, store_schema, "quality_test_definition_versions", f"version_id LIKE {sql_string(SEED_PREFIX + '-definition-%')} OR version_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-definition-%')}"),
        delete_sql(store_catalog, store_schema, "quality_test_definitions", f"definition_id LIKE {sql_string(SEED_PREFIX + '-definition-%')} OR definition_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-definition-%')}"),
        delete_sql(
            store_catalog,
            store_schema,
            "metadata_audit_log",
            (
                f"audit_id = {sql_string(SEED_PREFIX + '-audit-current')} "
                f"OR audit_id = {sql_string(LEGACY_SEED_PREFIX + '-audit-current')} "
                f"OR source IN ({sql_string(SEED_SOURCE)}, {sql_string(LEGACY_SEED_SOURCE)}) "
                f"OR actor_email IN ({sql_string(SEED_ACTOR)}, {sql_string('quality-northstar-seed@entrada.ai')})"
            ),
        ),
        definition_insert_sql(cases, store_catalog, store_schema),
        definition_version_insert_sql(cases, store_catalog, store_schema),
        suite_insert_sql(store_catalog, store_schema),
        case_insert_sql(cases, store_catalog, store_schema),
        run_insert_sql(results, store_catalog, store_schema),
        result_insert_sql(results, store_catalog, store_schema),
    ]
    alert_sql = alert_insert_sql(results, store_catalog, store_schema)
    if alert_sql:
        statements.append(alert_sql)
    statements.append(audit_insert_sql(results, store_catalog, store_schema))
    return statements


def verification_sql(store_catalog: str, store_schema: str) -> dict[str, str]:
    return {
        "definitions": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_test_definitions')} "
            f"WHERE definition_id LIKE {sql_string(SEED_PREFIX + '-definition-%')}"
        ),
        "cases": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_test_cases')} "
            f"WHERE case_id LIKE {sql_string(SEED_PREFIX + '-case-%')}"
        ),
        "runs": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_runs')} "
            f"WHERE run_id = {sql_string(RUN_ID)}"
        ),
        "results": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_run_results')} "
            f"WHERE run_id = {sql_string(RUN_ID)}"
        ),
        "alerts": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_alerts')} "
            f"WHERE alert_id LIKE {sql_string(SEED_PREFIX + '-alert-%')}"
        ),
        "audits": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'metadata_audit_log')} "
            f"WHERE audit_id = {sql_string(SEED_PREFIX + '-audit-current')} AND source = {sql_string(SEED_SOURCE)}"
        ),
        "statement_backed_results": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'quality_run_results')} "
            f"WHERE run_id = {sql_string(RUN_ID)} AND statement_id IS NOT NULL AND statement_id <> '' "
        ),
    }


def verify(args: argparse.Namespace) -> dict[str, int]:
    results: dict[str, int] = {}
    for key, statement in verification_sql(args.store_catalog, args.store_schema).items():
        response = execute_sql(statement, profile=args.profile, warehouse_id=args.warehouse_id)
        results[key] = int(scalar_float(response))
    return results


def expected_seed_counts() -> dict[str, int]:
    return {
        "definitions": 5,
        "cases": 5,
        "runs": 1,
        "results": 5,
        "alerts": 3,
        "audits": 1,
        "statement_backed_results": 5,
    }


def run_seed(args: argparse.Namespace) -> dict[str, int]:
    results = computed_results(args)
    statements = seed_statements(results, args)
    if args.dry_run:
        for index, statement in enumerate(statements, start=1):
            print(f"-- statement {index}")
            print(statement)
            print()
        return {}
    for index, statement in enumerate(statements, start=1):
        print(f"[{index}/{len(statements)}] executing", file=sys.stderr)
        execute_sql(statement, profile=args.profile, warehouse_id=args.warehouse_id)
    return verify(args)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--warehouse-id", default=DEFAULT_WAREHOUSE_ID, required=not DEFAULT_WAREHOUSE_ID)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--demo-schema", default=DEFAULT_DEMO_SCHEMA)
    parser.add_argument("--store-catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--store-schema", default=DEFAULT_STORE_SCHEMA)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    summary = verify(args) if args.verify_only else run_seed(args)
    if summary:
        expected = expected_seed_counts()
        print(json.dumps({"summary": summary, "expectedMinimums": expected}, indent=2, sort_keys=True))
        failed = [key for key, minimum in expected.items() if summary.get(key, 0) < minimum]
        if failed:
            raise RuntimeError(f"Seed verification failed minimums for: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
