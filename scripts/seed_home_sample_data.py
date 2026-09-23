#!/usr/bin/env python3
"""Write truthful Home-page representative evidence in Databricks.

The data writer creates real Unity Catalog views in a dedicated `datapact`
schema. Each view is derived from an existing Cotality source table and
receives complete UC comments/tags. It also writes app-owned governance-store
rows with a stable prefix so product metrics can be validated without frontend
fake values.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


DEFAULT_PROFILE = os.getenv("ATLAS_PROFILE", "DEFAULT")
DEFAULT_WAREHOUSE_ID = os.getenv("BUNDLE_VAR_warehouse_id") or os.getenv("DATABRICKS_WAREHOUSE_ID") or ""
DEFAULT_CATALOG = "datapact"
DEFAULT_DEMO_SCHEMA = "enterprise_metadata_ops"
DEFAULT_STORE_SCHEMA = "atlas"
SOURCE_SCHEMA = "cotality_mortgage_data.corelogic"
SEED_PREFIX = "GOV-HOME-EVIDENCE"
LEGACY_SEED_PREFIX = "ga-home-evidence"
SEED_SOURCE = "home-evidence-plane"
LEGACY_SEED_SOURCE = "home-northstar-seed"
SEED_ACTOR = os.getenv("GOVAT_SEED_ACTOR", "atlas.seed@example.com")


@dataclass(frozen=True)
class DemoAsset:
    name: str
    domain: str
    source_table: str
    data_product: str
    comment: str
    tier: str = "Tier 1"
    certification: str = "Certified"
    sensitivity: str = "Confidential"
    criticality: str = "Critical"


SOURCE_TABLES = {
    "property": "entrada_eval_property_domain_v3",
    "mortgage": "entrada_eval_mortgage_domain_v1",
    "market": "entrada_eval_mortgage_market_analytics_domain_v1",
    "transfer": "entrada_eval_owner_transfer_domain_v1",
    "lien": "entrada_eval_voluntary_lien_status_marketing_v2",
}


ASSETS: tuple[DemoAsset, ...] = (
    DemoAsset(
        "customer_profile_coverage",
        "Customer",
        SOURCE_TABLES["property"],
        "Customer 360",
        "Aggregated property coverage signal derived from Cotality property records.",
    ),
    DemoAsset(
        "customer_identity_quality",
        "Customer",
        SOURCE_TABLES["property"],
        "Customer 360",
        "Aggregated owner and property identity quality signal derived from Cotality property records.",
        sensitivity="Restricted",
    ),
    DemoAsset(
        "customer_stewardship_queue",
        "Customer",
        SOURCE_TABLES["transfer"],
        "Customer 360",
        "Aggregated owner-transfer stewardship signal derived from Cotality transfer records.",
        certification="Trusted",
    ),
    DemoAsset(
        "finance_lien_risk_summary",
        "Finance",
        SOURCE_TABLES["lien"],
        "Lien Intelligence",
        "Aggregated lien-risk signal derived from Cotality voluntary lien status records.",
    ),
    DemoAsset(
        "finance_portfolio_exposure",
        "Finance",
        SOURCE_TABLES["mortgage"],
        "Mortgage Portfolio",
        "Aggregated mortgage exposure signal derived from Cotality mortgage records.",
    ),
    DemoAsset(
        "finance_exception_review",
        "Finance",
        SOURCE_TABLES["lien"],
        "Lien Intelligence",
        "Aggregated policy-exception review signal derived from Cotality lien records.",
        certification="Draft",
        criticality="High",
    ),
    DemoAsset(
        "product_mortgage_signal",
        "Product",
        SOURCE_TABLES["mortgage"],
        "Mortgage Portfolio",
        "Aggregated mortgage-product signal derived from Cotality mortgage records.",
    ),
    DemoAsset(
        "product_property_feature_health",
        "Product",
        SOURCE_TABLES["property"],
        "Property Intelligence",
        "Aggregated property-feature health signal derived from Cotality property records.",
    ),
    DemoAsset(
        "product_market_fit_signal",
        "Product",
        SOURCE_TABLES["market"],
        "Market Analytics",
        "Aggregated market-fit signal derived from Cotality market analytics records.",
        certification="Trusted",
    ),
    DemoAsset(
        "operations_transfer_activity",
        "Operations",
        SOURCE_TABLES["transfer"],
        "Transfer Operations",
        "Aggregated transfer-activity signal derived from Cotality owner-transfer records.",
    ),
    DemoAsset(
        "operations_pipeline_readiness",
        "Operations",
        SOURCE_TABLES["property"],
        "Transfer Operations",
        "Aggregated readiness signal for operational property and transfer workflows.",
    ),
    DemoAsset(
        "operations_certification_backlog",
        "Operations",
        SOURCE_TABLES["transfer"],
        "Transfer Operations",
        "Aggregated certification backlog signal derived from Cotality transfer records.",
        certification="Draft",
        criticality="High",
    ),
    DemoAsset(
        "marketing_market_analytics",
        "Marketing",
        SOURCE_TABLES["market"],
        "Market Analytics",
        "Aggregated market analytics signal derived from Cotality market records.",
        tier="Tier 2",
    ),
    DemoAsset(
        "marketing_segment_signal",
        "Marketing",
        SOURCE_TABLES["property"],
        "Market Analytics",
        "Aggregated segment signal derived from Cotality property records.",
        tier="Tier 2",
        sensitivity="Internal",
    ),
    DemoAsset(
        "marketing_lien_outreach_signal",
        "Marketing",
        SOURCE_TABLES["lien"],
        "Market Analytics",
        "Aggregated outreach eligibility signal derived from Cotality lien records.",
        tier="Tier 2",
        certification="Trusted",
    ),
    DemoAsset(
        "risk_policy_exception_register",
        "Risk",
        SOURCE_TABLES["lien"],
        "Risk Controls",
        "Aggregated policy-exception register derived from Cotality lien records.",
        sensitivity="Restricted",
    ),
    DemoAsset(
        "risk_critical_asset_monitor",
        "Risk",
        SOURCE_TABLES["mortgage"],
        "Risk Controls",
        "Aggregated critical-asset monitor derived from Cotality mortgage records.",
        sensitivity="Restricted",
    ),
    DemoAsset(
        "risk_data_quality_review",
        "Risk",
        SOURCE_TABLES["market"],
        "Risk Controls",
        "Aggregated data-quality review signal derived from Cotality market records.",
        certification="Draft",
        sensitivity="Restricted",
        criticality="High",
    ),
)

TAG_OMISSIONS: dict[str, set[str]] = {
    # Real representative incompleteness for the development workspace. These
    # omissions are written to Unity Catalog, then the app computes coverage
    # from the resulting metadata instead of rendering a target percentage.
    "customer_stewardship_queue": {"certification"},
    "finance_exception_review": {"data_product", "criticality"},
    "operations_certification_backlog": {"certification", "criticality"},
    "marketing_lien_outreach_signal": {"sensitivity"},
    "risk_policy_exception_register": {"data_product"},
    "risk_data_quality_review": {"certification", "sensitivity"},
    "product_market_fit_signal": {"tier"},
    "operations_pipeline_readiness": {"domain"},
    "marketing_segment_signal": {"criticality"},
}

OWNER_OMISSIONS: dict[str, set[str]] = {
    "customer_stewardship_queue": {"business", "technical"},
    "finance_exception_review": {"business", "technical"},
    "operations_certification_backlog": {"business", "technical"},
    "risk_policy_exception_register": {"business", "technical"},
    "risk_data_quality_review": {"business", "technical"},
    "product_market_fit_signal": {"business", "technical"},
}


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
    result = subprocess.run(args, check=False, capture_output=True, text=True)
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
    timeout_s: int = 120,
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


def scalar_int(response: dict[str, Any]) -> int:
    rows = result_rows(response)
    if not rows or not rows[0]:
        return 0
    try:
        return int(rows[0][0])
    except (TypeError, ValueError):
        return 0


def batched(values: Iterable[str], size: int = 20) -> Iterable[list[str]]:
    batch: list[str] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def create_schema_sql(catalog: str, schema: str) -> str:
    return (
        f"CREATE SCHEMA IF NOT EXISTS {fq_name(catalog, schema)} "
        "COMMENT 'Governance Atlas representative enterprise assets derived from Cotality source tables.'"
    )


def create_view_sql(asset: DemoAsset, catalog: str, schema: str) -> str:
    source = f"{SOURCE_SCHEMA}.{asset.source_table}"
    return f"""
CREATE OR REPLACE VIEW {fq_name(catalog, schema, asset.name)}
COMMENT {sql_string(asset.comment)}
AS
SELECT
  {sql_string(asset.name)} AS asset_key,
  {sql_string(asset.domain)} AS governance_domain,
  {sql_string(asset.data_product)} AS data_product,
  COUNT(*) AS source_record_count,
  current_timestamp() AS refreshed_at
FROM {source}
""".strip()


def glossary_term_for_asset(asset: DemoAsset) -> str:
    explicit_terms = {
        "customer_profile_coverage": "Customer Identifier",
        "customer_identity_quality": "Customer Identifier",
        "customer_stewardship_queue": "Customer Identifier",
        "marketing_segment_signal": "Customer Segment",
        "operations_transfer_activity": "Customer Identifier",
        "operations_pipeline_readiness": "Customer Identifier",
        "operations_certification_backlog": "Customer Identifier",
        "product_property_feature_health": "Customer Identifier",
        "risk_policy_exception_register": "Net Revenue",
        "risk_data_quality_review": "Average Revenue",
    }
    if asset.name in explicit_terms:
        return explicit_terms[asset.name]
    if asset.domain in {"Finance", "Marketing", "Risk"}:
        return "Net Revenue"
    if asset.domain == "Product":
        return "Product Revenue"
    return "Customer Identifier"


def tag_sql(asset: DemoAsset, catalog: str, schema: str) -> str:
    tags = {
        "domain": asset.domain,
        "tier": asset.tier,
        "certification": asset.certification,
        "sensitivity": asset.sensitivity,
        "criticality": asset.criticality,
        "data_product": asset.data_product,
        "glossary_term": glossary_term_for_asset(asset),
        "governance_atlas_evidence_source": SEED_SOURCE,
    }
    for key in TAG_OMISSIONS.get(asset.name, set()):
        tags.pop(key, None)
    tag_items = ", ".join(f"{sql_string(key)} = {sql_string(value)}" for key, value in tags.items())
    return f"ALTER VIEW {fq_name(catalog, schema, asset.name)} SET TAGS ({tag_items})"


def clear_tag_sql(asset: DemoAsset, catalog: str, schema: str) -> str:
    tag_items = ", ".join(
        sql_string(key)
        for key in (
            "domain",
            "tier",
            "certification",
            "sensitivity",
            "criticality",
            "data_product",
            "glossary_term",
            "governance_atlas_evidence_source",
            "governance_atlas_seed",
        )
    )
    return f"ALTER VIEW {fq_name(catalog, schema, asset.name)} UNSET TAGS ({tag_items})"


def seeded_fqns(catalog: str, schema: str) -> list[str]:
    return [f"{catalog}.{schema}.{asset.name}" for asset in ASSETS]


def expected_seed_counts() -> dict[str, int]:
    verified_tag_names = {"domain", "certification", "criticality", "data_product", "governance_atlas_evidence_source"}
    tag_count = 0
    owner_count = 0
    for asset in ASSETS:
        omitted_tags = TAG_OMISSIONS.get(asset.name, set())
        tag_count += len(verified_tag_names - omitted_tags)
        owner_count += 2 - len(OWNER_OMISSIONS.get(asset.name, set()))
    return {
        "views": len(ASSETS),
        "tags": tag_count,
        "owners": owner_count,
        "requests": 5,
        "audit": 6,
        "tag_variance": 1,
        "owner_variance": 1,
    }


def delete_seed_rows_sql(store_catalog: str, store_schema: str, table: str, predicate: str) -> str:
    return f"DELETE FROM {fq_name(store_catalog, store_schema, table)} WHERE {predicate}"


def owner_insert_sql(catalog: str, schema: str, store_catalog: str, store_schema: str) -> str:
    rows: list[str] = []
    for asset in ASSETS:
        fqn = f"{catalog}.{schema}.{asset.name}"
        omitted = OWNER_OMISSIONS.get(asset.name, set())
        owner_templates = [
            ("business", asset.domain.lower().replace(" ", "-") + "-steward@entrada.ai"),
            ("technical", "metadata-platform@entrada.ai"),
        ]
        for owner_type, owner_email in owner_templates:
            if owner_type in omitted:
                continue
            rows.append(
                "("
                f"{sql_string(fqn)}, "
                f"{sql_string(owner_email)}, "
                f"{sql_string(owner_type)}, "
                "current_timestamp(), "
                f"{sql_string(SEED_ACTOR)}"
                ")"
            )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "data_owners")}
  (uc_full_name, owner_email, owner_type, updated_at, updated_by)
VALUES
  {", ".join(rows)}
""".strip()


def change_request_insert_sql(catalog: str, schema: str, store_catalog: str, store_schema: str) -> str:
    request_templates = [
        (
            ASSETS[2],
            "Review transfer stewardship queue",
            "Owner-transfer stewardship volume needs business review before the next certification cycle.",
            "P1 critical",
            "breach",
            -6,
            "customer-steward@entrada.ai",
        ),
        (
            ASSETS[5],
            "Resolve policy exception",
            "Finance exception review includes restricted lien attributes that need risk approval.",
            "P1 critical",
            "breach",
            -3,
            "finance-steward@entrada.ai",
        ),
        (
            ASSETS[11],
            "Review certification renewal",
            "Operations certification backlog needs renewal before quarter close.",
            "P2 high",
            "warning",
            10,
            "operations-steward@entrada.ai",
        ),
        (
            ASSETS[15],
            "Access review",
            "Risk policy exception register requires quarterly access review for finance analysts.",
            "P1 critical",
            "breach",
            -1,
            "risk-steward@entrada.ai",
        ),
        (
            ASSETS[17],
            "Review data quality exception",
            "Risk data quality review needs steward validation before downstream reporting.",
            "P2 high",
            "warning",
            20,
            "risk-steward@entrada.ai",
        ),
    ]
    rows: list[str] = []
    now = datetime.now(timezone.utc)
    for index, (asset, title, note, priority, sla_state, due_offset_hours, assignee) in enumerate(request_templates, start=1):
        fqn = f"{catalog}.{schema}.{asset.name}"
        request_id = f"{SEED_PREFIX}-request-{index:02d}"
        comment = f"{title}: {note}"
        due_at = (now + timedelta(hours=due_offset_hours)).isoformat().replace("+00:00", "Z")
        tags = json.dumps(
            {
                "domain": asset.domain,
                "data_product": asset.data_product,
                "certification": asset.certification,
                "priority": priority,
                "slaState": sla_state,
                "dueAt": due_at,
                "assignedTo": assignee,
            },
            sort_keys=True,
        )
        rows.append(
            "("
            f"{sql_string(request_id)}, "
            f"current_timestamp() - INTERVAL {index} HOURS, "
            f"{sql_string(SEED_ACTOR)}, "
            "'pending', "
            f"{sql_string(fqn)}, "
            f"{sql_string(comment)}, "
            f"{sql_string(tags)}, "
            "NULL, NULL, NULL"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "change_requests")}
  (request_id, created_at, created_by, status, uc_full_name, new_comment,
   new_uc_tags_json, reviewed_at, reviewed_by, review_note)
VALUES
  {", ".join(rows)}
""".strip()


def audit_insert_sql(catalog: str, schema: str, store_catalog: str, store_schema: str) -> str:
    events = [
        (ASSETS[15], "policy-exception-detected", "failed", "Risk policy exception from governed Databricks evidence.", "15 MINUTES"),
        (ASSETS[17], "critical-metadata-review-opened", "flagged", "Risk metadata review needs steward action.", "45 MINUTES"),
        (ASSETS[11], "certification-review-opened", "success", "Operations certification review opened.", "90 MINUTES"),
        (ASSETS[2], "owner-stewardship-updated", "success", "Customer stewardship owners assigned.", "2 HOURS"),
        (ASSETS[5], "policy-exception-review-opened", "success", "Finance policy exception review opened.", "3 HOURS"),
        (ASSETS[0], "metadata-curated", "success", "Customer metadata curated from Cotality source.", "4 HOURS"),
    ]
    rows: list[str] = []
    for index, (asset, action, status, detail, age) in enumerate(events, start=1):
        fqn = f"{catalog}.{schema}.{asset.name}"
        after = json.dumps(
            {
                "domain": asset.domain,
                "dataProduct": asset.data_product,
                "certification": asset.certification,
                "criticality": asset.criticality,
            },
            sort_keys=True,
        )
        rows.append(
            "("
            f"{sql_string(f'{SEED_PREFIX}-audit-{index:02d}')}, "
            "'asset', "
            f"{sql_string(fqn)}, "
            f"{sql_string(fqn)}, "
            "NULL, "
            f"{sql_string(action)}, "
            f"{sql_string(SEED_SOURCE)}, "
            f"{sql_string(status)}, "
            "NULL, "
            f"{sql_string(after)}, "
            f"{sql_string(f'{SEED_PREFIX}-request-{min(index, 5):02d}')}, "
            f"{sql_string(SEED_ACTOR)}, "
            "'admin', "
            f"{sql_string(detail)}, "
            f"current_timestamp() - INTERVAL {age}, "
            f"{sql_string(SEED_ACTOR)}, "
            f"current_timestamp() - INTERVAL {age}, "
            f"{sql_string(SEED_ACTOR)}"
            ")"
        )
    return f"""
INSERT INTO {fq_name(store_catalog, store_schema, "metadata_audit_log")}
  (audit_id, entity_type, entity_id, entity_fqn, column_name, action, source,
   status, before_json, after_json, request_id, actor_email, actor_role, detail,
   created_at, created_by, updated_at, updated_by)
VALUES
  {", ".join(rows)}
""".strip()


def verification_sql(catalog: str, schema: str, store_catalog: str, store_schema: str) -> dict[str, str]:
    fqn_literals = ", ".join(sql_string(fqn) for fqn in seeded_fqns(catalog, schema))
    return {
        "views": (
            f"SELECT COUNT(*) FROM {quote_name(catalog)}.information_schema.tables "
            f"WHERE table_schema = {sql_string(schema)} AND table_name IN "
            f"({', '.join(sql_string(asset.name) for asset in ASSETS)})"
        ),
        "tags": (
            f"SELECT COUNT(*) FROM {quote_name(catalog)}.information_schema.table_tags "
            f"WHERE schema_name = {sql_string(schema)} AND table_name IN "
            f"({', '.join(sql_string(asset.name) for asset in ASSETS)}) "
            "AND tag_name IN ('domain', 'certification', 'criticality', 'data_product', 'governance_atlas_evidence_source')"
        ),
        "owners": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'data_owners')} "
            f"WHERE uc_full_name IN ({fqn_literals})"
        ),
        "requests": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'change_requests')} "
            f"WHERE request_id LIKE {sql_string(SEED_PREFIX + '-request-%')}"
        ),
        "audit": (
            f"SELECT COUNT(*) FROM {fq_name(store_catalog, store_schema, 'metadata_audit_log')} "
            f"WHERE audit_id LIKE {sql_string(SEED_PREFIX + '-audit-%')} "
            f"AND source = {sql_string(SEED_SOURCE)}"
        ),
        "tag_variance": (
            "WITH tag_counts AS ("
            f"SELECT table_name, COUNT(DISTINCT tag_name) AS tag_count "
            f"FROM {quote_name(catalog)}.information_schema.table_tags "
            f"WHERE schema_name = {sql_string(schema)} AND table_name IN "
            f"({', '.join(sql_string(asset.name) for asset in ASSETS)}) "
            "AND tag_name IN ('domain', 'certification', 'criticality', 'data_product') "
            "GROUP BY table_name"
            ") SELECT COUNT(DISTINCT tag_count) FROM tag_counts"
        ),
        "owner_variance": (
            "WITH owner_counts AS ("
            f"SELECT uc_full_name, COUNT(DISTINCT owner_email) AS owner_count "
            f"FROM {fq_name(store_catalog, store_schema, 'data_owners')} "
            f"WHERE uc_full_name IN ({fqn_literals}) "
            "GROUP BY uc_full_name"
            ") SELECT COUNT(DISTINCT owner_count) FROM owner_counts"
        ),
    }


def run_seed(args: argparse.Namespace) -> dict[str, int]:
    statements: list[str] = [create_schema_sql(args.catalog, args.demo_schema)]
    for asset in ASSETS:
        statements.append(create_view_sql(asset, args.catalog, args.demo_schema))
        statements.append(clear_tag_sql(asset, args.catalog, args.demo_schema))
        statements.append(tag_sql(asset, args.catalog, args.demo_schema))

    fqn_literals = ", ".join(sql_string(fqn) for fqn in seeded_fqns(args.catalog, args.demo_schema))
    statements.extend(
        [
            delete_seed_rows_sql(
                args.store_catalog,
                args.store_schema,
                "data_owners",
                f"uc_full_name IN ({fqn_literals})",
            ),
            delete_seed_rows_sql(
                args.store_catalog,
                args.store_schema,
                "change_requests",
                f"request_id LIKE {sql_string(SEED_PREFIX + '-request-%')} OR request_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-request-%')}",
            ),
            delete_seed_rows_sql(
                args.store_catalog,
                args.store_schema,
                "metadata_audit_log",
                (
                    f"audit_id LIKE {sql_string(SEED_PREFIX + '-audit-%')} "
                    f"OR audit_id LIKE {sql_string(LEGACY_SEED_PREFIX + '-audit-%')} "
                    f"OR source IN ({sql_string(SEED_SOURCE)}, {sql_string(LEGACY_SEED_SOURCE)})"
                ),
            ),
            owner_insert_sql(args.catalog, args.demo_schema, args.store_catalog, args.store_schema),
            change_request_insert_sql(args.catalog, args.demo_schema, args.store_catalog, args.store_schema),
            audit_insert_sql(args.catalog, args.demo_schema, args.store_catalog, args.store_schema),
        ]
    )

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


def verify(args: argparse.Namespace) -> dict[str, int]:
    results: dict[str, int] = {}
    for key, statement in verification_sql(
        args.catalog,
        args.demo_schema,
        args.store_catalog,
        args.store_schema,
    ).items():
        response = execute_sql(statement, profile=args.profile, warehouse_id=args.warehouse_id)
        results[key] = scalar_int(response)
    return results


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
