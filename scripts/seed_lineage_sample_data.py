#!/usr/bin/env python3
"""Write backed Governance Atlas lineage evidence in Databricks.

The visual and functional lineage workspace needs representative downstream
consumers to exercise impact analysis. This script creates Databricks-managed
UC tables from the existing representative enterprise views, then verifies Databricks system lineage
sees the resulting downstream paths. It does not write frontend fixtures or
non-authoritative runtime payloads.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from seed_quality_sample_data import execute_sql, fq_name, result_rows, sql_string


DEFAULT_PROFILE = os.getenv("ATLAS_PROFILE", "DEFAULT")
DEFAULT_WAREHOUSE_ID = os.getenv("BUNDLE_VAR_warehouse_id") or os.getenv("DATABRICKS_WAREHOUSE_ID") or ""
DEFAULT_CATALOG = "datapact"
DEFAULT_DEMO_SCHEMA = "enterprise_metadata_ops"
DEFAULT_STORE_CATALOG = "datapact"
DEFAULT_STORE_SCHEMA = "atlas"
SOURCE_VIEW = "customer_stewardship_queue"
SEED_SOURCE = "lineage-evidence-plane"
FINANCE_FOCUS_ASSET = "finance_prod.curated.revenue_daily"
ENTERPRISE_SEED_SOURCE = "enterprise-workspace-evidence-plane"
ENTERPRISE_SEED_ACTOR = "metadata.enterprise@entrada.ai"


def seeded_fqn(args: argparse.Namespace, table: str) -> str:
    return f"{args.catalog}.{args.demo_schema}.{table}"


def fqn_parts(fqn: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in str(fqn or "").split(".")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"expected catalog.schema.table FQN, got {fqn!r}")
    return parts[0], parts[1], parts[2]


def source_column_lookup_sql(profile: dict[str, str]) -> str:
    catalog, schema, table = fqn_parts(profile["fqn"])
    return f"""
SELECT column_name
FROM {fq_name(catalog, "information_schema", "columns")}
WHERE table_schema = {sql_string(schema)}
  AND table_name = {sql_string(table)}
  AND column_name IS NOT NULL
  AND LEFT(column_name, 1) <> '_'
ORDER BY
  CASE
    WHEN lower(coalesce(comment, '')) LIKE '%critical data element%' THEN 0
    WHEN lower(column_name) LIKE '%net_revenue%' THEN 1
    WHEN lower(column_name) LIKE '%customer%' THEN 2
    WHEN lower(column_name) LIKE '%source_record%' THEN 3
    WHEN lower(column_name) LIKE '%revenue%' THEN 4
    ELSE 5
  END,
  ordinal_position
LIMIT 1
""".strip()


def source_column_for_profile(args: argparse.Namespace, profile: dict[str, str]) -> str:
    try:
        response = execute_sql(
            source_column_lookup_sql(profile),
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
    except Exception:
        return ""
    rows = result_rows(response)
    if not rows or not rows[0]:
        return ""
    return str(rows[0][0] or "").strip()


def enterprise_asset_profiles(args: argparse.Namespace) -> list[dict[str, str]]:
    """Representative real UC assets that should carry backed governance context."""
    customer_term = "Customer Identifier"
    revenue_term = "Net Revenue"
    product_term = "Product Revenue"
    profiles = [
        # Datapact lineage consumer tables produced by this script.
        (seeded_fqn(args, "customer_stewardship_priority_workbench_table"), "Customer", "Customer 360", customer_term),
        (seeded_fqn(args, "customer_stewardship_executive_feed_table"), "Customer", "Customer 360", customer_term),
        (seeded_fqn(args, "customer_stewardship_remediation_portfolio_table"), "Customer", "Customer 360", customer_term),
        (seeded_fqn(args, "customer_stewardship_lineage_dashboard_feed_table"), "Customer", "Customer 360", customer_term),
        # Revenue lineage estate.
        ("finance_prod.raw.stripe_charges", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.raw.netsuite_invoices", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.raw.salesforce_orders", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.bronze.charges_raw", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.bronze.invoices_raw", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.bronze.orders_raw", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.silver.payments", "Finance", "Revenue Operations", revenue_term),
        (FINANCE_FOCUS_ASSET, "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.gold.revenue_recognition", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.gold.revenue_margin_daily", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.gold.revenue_anomaly_monitor", "Finance", "Revenue Operations", revenue_term),
        ("finance_prod.gold.cfo_revenue_board_pack", "Finance", "Revenue Operations", "Revenue Forecast"),
        ("finance_prod.gold.revenue_forecast_features", "Finance", "Revenue Operations", "Revenue Forecast"),
        ("finance_prod.gold.revenue_close_control", "Finance", "Revenue Operations", revenue_term),
        ("sales_prod.silver.orders", "Sales", "Revenue Operations", revenue_term),
        ("sales_prod.silver.revenue_booking_bridge", "Sales", "Revenue Operations", revenue_term),
        ("sales_prod.silver.sales_pipeline_revenue", "Sales", "Revenue Operations", revenue_term),
        ("marketing_mart.gold.attribution_daily", "Marketing", "Revenue Operations", revenue_term),
        ("marketing_mart.gold.revenue_attribution_snapshot", "Marketing", "Revenue Operations", revenue_term),
        ("marketing_mart.gold.campaign_roi_revenue", "Marketing", "Revenue Operations", revenue_term),
        ("customer_360.gold.customer_profile", "Customer", "Customer 360", customer_term),
        ("customer_360.gold.customer_revenue_ltv", "Customer", "Customer 360", customer_term),
        ("customer_360.gold.customer_value_segments", "Customer", "Customer 360", customer_term),
        ("customer_360.ml.churn_propensity_v3", "Customer", "Customer 360", customer_term),
        ("product_events.bronze.clickstream_events", "Product", "Product Telemetry", product_term),
        ("product_events.bronze.revenue_product_signal", "Product", "Product Telemetry", product_term),
        ("product_events.bronze.product_revenue_experiment_feed", "Product", "Product Telemetry", product_term),
        ("hr_secure.confidential.compensation_band", "People", "Workforce Analytics", "Compensation Band"),
    ]
    owner_by_domain = {
        "Customer": "customer-steward@entrada.ai",
        "Finance": "finance-steward@entrada.ai",
        "Marketing": "marketing-steward@entrada.ai",
        "People": "people-steward@entrada.ai",
        "Product": "product-steward@entrada.ai",
        "Sales": "sales-steward@entrada.ai",
    }
    return [
        {
            "fqn": fqn,
            "domain": domain,
            "dataProduct": data_product,
            "glossaryTerm": glossary_term,
            "businessOwner": owner_by_domain.get(domain, "metadata-steward@entrada.ai"),
            "technicalOwner": "metadata-platform@entrada.ai",
        }
        for fqn, domain, data_product, glossary_term in profiles
    ]


def create_table_sql(args: argparse.Namespace, table: str, select_sql: str, comment: str) -> str:
    return f"""
CREATE OR REPLACE TABLE {fq_name(args.catalog, args.demo_schema, table)}
COMMENT {sql_string(comment)}
TBLPROPERTIES (
  'governance_atlas.evidence.source' = {sql_string(SEED_SOURCE)},
  'governance_atlas.evidence.focus_asset' = {sql_string(seeded_fqn(args, SOURCE_VIEW))}
)
AS
{select_sql}
""".strip()


def create_uc_table_sql(
    catalog: str,
    schema: str,
    table: str,
    select_sql: str,
    comment: str,
    focus_asset: str,
) -> str:
    return f"""
CREATE OR REPLACE TABLE {fq_name(catalog, schema, table)}
COMMENT {sql_string(comment)}
TBLPROPERTIES (
  'governance_atlas.evidence.source' = {sql_string(SEED_SOURCE)},
  'governance_atlas.evidence.focus_asset' = {sql_string(focus_asset)}
)
AS
{select_sql}
""".strip()


def table_statements(args: argparse.Namespace) -> list[tuple[str, str]]:
    focus = fq_name(args.catalog, args.demo_schema, SOURCE_VIEW)
    identity = fq_name(args.catalog, args.demo_schema, "customer_identity_quality")
    exceptions = fq_name(args.catalog, args.demo_schema, "risk_policy_exception_register")
    priority = fq_name(args.catalog, args.demo_schema, "customer_stewardship_priority_workbench_table")
    exec_feed = fq_name(args.catalog, args.demo_schema, "customer_stewardship_executive_feed_table")
    remediation = fq_name(args.catalog, args.demo_schema, "customer_stewardship_remediation_portfolio_table")

    return [
        (
            "customer_stewardship_priority_workbench_table",
            create_table_sql(
                args,
                "customer_stewardship_priority_workbench_table",
                f"""
SELECT
  q.asset_key,
  q.governance_domain,
  q.data_product,
  q.source_record_count,
  i.source_record_count AS identity_quality_record_count,
  CASE
    WHEN q.source_record_count >= i.source_record_count THEN 'owner-transfer review'
    ELSE 'identity-quality review'
  END AS stewardship_priority,
  greatest(q.refreshed_at, i.refreshed_at) AS refreshed_at
FROM {focus} q
LEFT JOIN {identity} i
  ON q.asset_key = i.asset_key
""".strip(),
                "Backed owner-transfer stewardship workbench derived from enterprise metadata operations signals.",
            ),
        ),
        (
            "customer_stewardship_executive_feed_table",
            create_table_sql(
                args,
                "customer_stewardship_executive_feed_table",
                f"""
SELECT
  asset_key,
  governance_domain,
  data_product,
  source_record_count,
  stewardship_priority,
  refreshed_at
FROM {priority}
WHERE source_record_count >= 0
""".strip(),
                "Executive consumer feed derived from the customer stewardship priority workbench.",
            ),
        ),
        (
            "customer_stewardship_remediation_portfolio_table",
            create_table_sql(
                args,
                "customer_stewardship_remediation_portfolio_table",
                f"""
SELECT
  p.asset_key,
  p.governance_domain,
  p.data_product,
  p.source_record_count,
  e.source_record_count AS policy_exception_record_count,
  p.stewardship_priority,
  greatest(p.refreshed_at, e.refreshed_at) AS refreshed_at
FROM {priority} p
CROSS JOIN {exceptions} e
""".strip(),
                "Risk and stewardship remediation portfolio derived from backed enterprise UC views.",
            ),
        ),
        (
            "customer_stewardship_lineage_dashboard_feed_table",
            create_table_sql(
                args,
                "customer_stewardship_lineage_dashboard_feed_table",
                f"""
SELECT
  f.asset_key,
  f.governance_domain,
  f.data_product,
  f.source_record_count,
  r.policy_exception_record_count,
  f.stewardship_priority,
  greatest(f.refreshed_at, r.refreshed_at) AS refreshed_at
FROM {exec_feed} f
LEFT JOIN {remediation} r
  ON f.asset_key = r.asset_key
""".strip(),
                "Dashboard-ready lineage feed derived from stewardship and remediation consumers.",
            ),
        ),
    ]


def finance_revenue_table_statements() -> list[tuple[str, str, str, str]]:
    revenue = fq_name("finance_prod", "curated", "revenue_daily")
    recognition = fq_name("finance_prod", "gold", "revenue_recognition")
    attribution = fq_name("marketing_mart", "gold", "attribution_daily")
    margin = fq_name("finance_prod", "gold", "revenue_margin_daily")
    anomaly = fq_name("finance_prod", "gold", "revenue_anomaly_monitor")
    board_pack = fq_name("finance_prod", "gold", "cfo_revenue_board_pack")
    booking_bridge = fq_name("sales_prod", "silver", "revenue_booking_bridge")
    ltv = fq_name("customer_360", "gold", "customer_revenue_ltv")
    product_signal = fq_name("product_events", "bronze", "revenue_product_signal")

    return [
        (
            "finance_prod",
            "gold",
            "revenue_margin_daily",
            create_uc_table_sql(
                "finance_prod",
                "gold",
                "revenue_margin_daily",
                f"""
SELECT
  revenue_date,
  net_revenue_usd,
  gross_revenue_usd,
  processing_fee_usd,
  gross_revenue_usd - processing_fee_usd AS contribution_revenue_usd,
  order_count,
  customer_count
FROM {revenue}
""".strip(),
                "Backed finance margin mart derived from the certified revenue daily table.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "finance_prod",
            "gold",
            "revenue_anomaly_monitor",
            create_uc_table_sql(
                "finance_prod",
                "gold",
                "revenue_anomaly_monitor",
                f"""
SELECT
  revenue_date,
  net_revenue_usd,
  gross_revenue_usd,
  order_count,
  CASE WHEN net_revenue_usd < 0 THEN 'negative revenue' ELSE 'within expected range' END AS anomaly_status
FROM {revenue}
""".strip(),
                "Backed revenue anomaly monitor sourced from revenue daily.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "finance_prod",
            "gold",
            "cfo_revenue_board_pack",
            create_uc_table_sql(
                "finance_prod",
                "gold",
                "cfo_revenue_board_pack",
                f"""
SELECT
  r.revenue_date,
  r.net_revenue_usd,
  r.gross_revenue_usd,
  r.order_count,
  m.contribution_revenue_usd,
  a.anomaly_status
FROM {revenue} r
LEFT JOIN {margin} m USING (revenue_date)
LEFT JOIN {anomaly} a USING (revenue_date)
""".strip(),
                "CFO board-pack revenue table derived from certified daily revenue, margin, and anomaly signals.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "finance_prod",
            "gold",
            "revenue_forecast_features",
            create_uc_table_sql(
                "finance_prod",
                "gold",
                "revenue_forecast_features",
                f"""
SELECT
  b.revenue_date,
  b.net_revenue_usd,
  b.contribution_revenue_usd,
  b.order_count,
  dayofweek(b.revenue_date) AS day_of_week,
  month(b.revenue_date) AS revenue_month
FROM {board_pack} b
""".strip(),
                "Forecast feature table derived from CFO revenue board-pack evidence.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "sales_prod",
            "silver",
            "revenue_booking_bridge",
            create_uc_table_sql(
                "sales_prod",
                "silver",
                "revenue_booking_bridge",
                f"""
SELECT
  revenue_date,
  net_revenue_usd,
  order_count,
  customer_count,
  concat('booking-', date_format(revenue_date, 'yyyyMMdd')) AS booking_batch_id
FROM {revenue}
""".strip(),
                "Sales booking bridge derived from certified revenue daily.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "sales_prod",
            "silver",
            "sales_pipeline_revenue",
            create_uc_table_sql(
                "sales_prod",
                "silver",
                "sales_pipeline_revenue",
                f"""
SELECT
  booking_batch_id,
  revenue_date,
  net_revenue_usd,
  order_count,
  customer_count
FROM {booking_bridge}
""".strip(),
                "Sales pipeline revenue consumer derived from the revenue booking bridge.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "marketing_mart",
            "gold",
            "revenue_attribution_snapshot",
            create_uc_table_sql(
                "marketing_mart",
                "gold",
                "revenue_attribution_snapshot",
                f"""
SELECT
  r.revenue_date,
  r.net_revenue_usd,
  r.customer_count,
  'all channels' AS attribution_scope,
  a.attributed_revenue_usd
FROM {revenue} r
LEFT JOIN {attribution} a
  ON r.revenue_date = a.revenue_date
""".strip(),
                "Marketing revenue attribution snapshot joined to certified revenue daily.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "marketing_mart",
            "gold",
            "campaign_roi_revenue",
            create_uc_table_sql(
                "marketing_mart",
                "gold",
                "campaign_roi_revenue",
                f"""
SELECT
  revenue_date,
  attribution_scope,
  net_revenue_usd,
  attributed_revenue_usd,
  CASE WHEN net_revenue_usd = 0 THEN NULL ELSE attributed_revenue_usd / net_revenue_usd END AS attributed_revenue_ratio
FROM {fq_name("marketing_mart", "gold", "revenue_attribution_snapshot")}
""".strip(),
                "Campaign ROI revenue consumer derived from attributed revenue snapshot.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "customer_360",
            "gold",
            "customer_revenue_ltv",
            create_uc_table_sql(
                "customer_360",
                "gold",
                "customer_revenue_ltv",
                f"""
SELECT
  revenue_date,
  customer_count,
  net_revenue_usd,
  CASE WHEN customer_count = 0 THEN NULL ELSE net_revenue_usd / customer_count END AS revenue_per_customer_usd
FROM {revenue}
""".strip(),
                "Customer lifetime-value revenue signal derived from certified revenue daily.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "customer_360",
            "gold",
            "customer_value_segments",
            create_uc_table_sql(
                "customer_360",
                "gold",
                "customer_value_segments",
                f"""
SELECT
  revenue_date,
  customer_count,
  revenue_per_customer_usd,
  CASE
    WHEN revenue_per_customer_usd >= 100 THEN 'high value'
    WHEN revenue_per_customer_usd >= 25 THEN 'core value'
    ELSE 'watch'
  END AS customer_value_segment
FROM {ltv}
""".strip(),
                "Customer value segment consumer derived from revenue LTV.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "product_events",
            "bronze",
            "revenue_product_signal",
            create_uc_table_sql(
                "product_events",
                "bronze",
                "revenue_product_signal",
                f"""
SELECT
  revenue_date,
  order_count,
  customer_count,
  net_revenue_usd,
  concat('product-signal-', date_format(revenue_date, 'yyyyMMdd')) AS product_signal_id
FROM {revenue}
""".strip(),
                "Product event revenue signal derived from certified revenue daily.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "product_events",
            "bronze",
            "product_revenue_experiment_feed",
            create_uc_table_sql(
                "product_events",
                "bronze",
                "product_revenue_experiment_feed",
                f"""
SELECT
  product_signal_id,
  revenue_date,
  order_count,
  customer_count,
  net_revenue_usd
FROM {product_signal}
""".strip(),
                "Product experiment feed derived from revenue product signals.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
        (
            "finance_prod",
            "gold",
            "revenue_close_control",
            create_uc_table_sql(
                "finance_prod",
                "gold",
                "revenue_close_control",
                f"""
SELECT
  r.revenue_date,
  r.net_revenue_usd,
  rec.recognized_net_revenue_usd,
  r.net_revenue_usd - rec.recognized_net_revenue_usd AS recognition_variance_usd
FROM {revenue} r
LEFT JOIN (
  SELECT
    revenue_date,
    SUM(net_revenue_usd) AS recognized_net_revenue_usd
  FROM {recognition}
  WHERE revenue_status = 'recognized'
  GROUP BY revenue_date
) rec
  ON r.revenue_date = rec.revenue_date
""".strip(),
                "Revenue close control derived from certified daily revenue and recognition ledger.",
                FINANCE_FOCUS_ASSET,
            ),
        ),
    ]


def tag_table_sql(args: argparse.Namespace, table: str) -> str:
    return f"""
ALTER TABLE {fq_name(args.catalog, args.demo_schema, table)}
SET TAGS (
  'governance_atlas_evidence_source' = {sql_string(SEED_SOURCE)},
  'governance_atlas_lineage_focus_asset' = {sql_string(seeded_fqn(args, SOURCE_VIEW))}
)
""".strip()


def tag_uc_table_sql(catalog: str, schema: str, table: str, focus_asset: str) -> str:
    return f"""
ALTER TABLE {fq_name(catalog, schema, table)}
SET TAGS (
  'governance_atlas_evidence_source' = {sql_string(SEED_SOURCE)},
  'governance_atlas_lineage_focus_asset' = {sql_string(focus_asset)}
)
""".strip()


def finance_operational_job_tag_sql(args: argparse.Namespace) -> str:
    job_id = str(args.operational_job_id or "").strip()
    job_name = str(args.operational_job_name or "").strip()
    if not job_id and not job_name:
        return ""
    tags = ["'governance_atlas_evidence_source' = " + sql_string(SEED_SOURCE)]
    if job_id:
        tags.append("'governance_atlas_operational_consumer_job_id' = " + sql_string(job_id))
    if job_name:
        tags.append("'governance_atlas_operational_consumer_job_name' = " + sql_string(job_name))
    tag_body = ",\n  ".join(tags)
    return f"""
ALTER TABLE {fq_name(*fqn_parts(FINANCE_FOCUS_ASSET))}
SET TAGS (
  {tag_body}
)
""".strip()


def enterprise_asset_tag_sql(profile: dict[str, str]) -> str:
    catalog, schema, table = fqn_parts(profile["fqn"])
    source_column = str(profile.get("sourceColumn") or "").strip()
    cde_tags = ""
    if source_column:
        cde_tags = f""",
  'cde_source_column' = {sql_string(source_column)},
  'cde_recert_window' = '90d',
  'cde_registry_source' = {sql_string(ENTERPRISE_SEED_SOURCE)}"""
    return f"""
ALTER TABLE {fq_name(catalog, schema, table)}
SET TAGS (
  'domain' = {sql_string(profile["domain"])},
  'tier' = 'Tier 1',
  'certification' = 'Certified',
  'sensitivity' = 'Confidential',
  'criticality' = 'Critical',
  'data_product' = {sql_string(profile["dataProduct"])},
  'glossary_term' = {sql_string(profile["glossaryTerm"])},
  'governance_atlas_evidence_source' = {sql_string(ENTERPRISE_SEED_SOURCE)}
  {cde_tags}
)
""".strip()


def enterprise_asset_comment_sql(profile: dict[str, str]) -> str:
    catalog, schema, table = fqn_parts(profile["fqn"])
    return (
        f"COMMENT ON TABLE {fq_name(catalog, schema, table)} IS "
        f"{sql_string(f'Governed {profile['dataProduct']} asset supporting enterprise stewardship, certification, and lineage review.')}"
    )


def enterprise_owner_refresh_sql(store_catalog: str, store_schema: str, profiles: list[dict[str, str]]) -> list[str]:
    fqn_literals = ", ".join(sql_string(profile["fqn"]) for profile in profiles)
    rows: list[str] = []
    for profile in profiles:
        rows.append(
            "("
            f"{sql_string(profile['fqn'])}, "
            f"{sql_string(profile['businessOwner'])}, "
            "'business', "
            "current_timestamp(), "
            f"{sql_string(ENTERPRISE_SEED_ACTOR)}"
            ")"
        )
        rows.append(
            "("
            f"{sql_string(profile['fqn'])}, "
            f"{sql_string(profile['technicalOwner'])}, "
            "'technical', "
            "current_timestamp(), "
            f"{sql_string(ENTERPRISE_SEED_ACTOR)}"
            ")"
        )
    return [
        (
            f"DELETE FROM {fq_name(store_catalog, store_schema, 'data_owners')} "
            f"WHERE uc_full_name IN ({fqn_literals}) "
            f"AND updated_by = {sql_string(ENTERPRISE_SEED_ACTOR)}"
        ),
        f"""
INSERT INTO {fq_name(store_catalog, store_schema, "data_owners")}
  (uc_full_name, owner_email, owner_type, updated_at, updated_by)
VALUES
  {", ".join(rows)}
""".strip(),
    ]


def lineage_count_sql(args: argparse.Namespace) -> str:
    focus = seeded_fqn(args, SOURCE_VIEW)
    return f"""
SELECT COUNT(DISTINCT target_table_full_name)
FROM system.access.table_lineage
WHERE source_table_full_name = {sql_string(focus)}
  AND target_table_full_name LIKE {sql_string(args.catalog + '.' + args.demo_schema + '.customer_stewardship_%')}
""".strip()


def finance_lineage_count_sql() -> str:
    return f"""
SELECT COUNT(DISTINCT target_table_full_name)
FROM system.access.table_lineage
WHERE source_table_full_name = {sql_string(FINANCE_FOCUS_ASSET)}
  AND (
    target_table_full_name LIKE 'finance_prod.gold.%'
    OR target_table_full_name LIKE 'sales_prod.silver.%'
    OR target_table_full_name LIKE 'marketing_mart.gold.%'
    OR target_table_full_name LIKE 'customer_360.gold.%'
    OR target_table_full_name LIKE 'product_events.bronze.%'
  )
""".strip()


def finance_governed_lineage_evidence_count_sql() -> str:
    return f"""
SELECT COUNT(DISTINCT CONCAT(catalog_name, '.', schema_name, '.', table_name))
FROM system.information_schema.table_tags
WHERE tag_name = 'governance_atlas_lineage_focus_asset'
  AND tag_value = {sql_string(FINANCE_FOCUS_ASSET)}
  AND (
    CONCAT(catalog_name, '.', schema_name, '.', table_name) LIKE 'finance_prod.gold.%'
    OR CONCAT(catalog_name, '.', schema_name, '.', table_name) LIKE 'sales_prod.silver.%'
    OR CONCAT(catalog_name, '.', schema_name, '.', table_name) LIKE 'marketing_mart.gold.%'
    OR CONCAT(catalog_name, '.', schema_name, '.', table_name) LIKE 'customer_360.gold.%'
    OR CONCAT(catalog_name, '.', schema_name, '.', table_name) LIKE 'product_events.bronze.%'
  )
""".strip()


def scalar_int(response: dict[str, Any]) -> int:
    rows = result_rows(response)
    if not rows or not rows[0]:
        return 0
    try:
        return int(float(rows[0][0]))
    except (TypeError, ValueError):
        return 0


def seed(args: argparse.Namespace) -> dict[str, Any]:
    statements: list[dict[str, Any]] = []
    for table_name, statement in table_statements(args):
        response = execute_sql(
            statement,
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        tag_response = execute_sql(
            tag_table_sql(args, table_name),
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        statements.append(
            {
                "table": seeded_fqn(args, table_name),
                "statementId": response.get("statement_id"),
                "tagStatementId": tag_response.get("statement_id"),
            }
        )

    finance_statements: list[dict[str, Any]] = []
    for catalog, schema, table_name, statement in finance_revenue_table_statements():
        response = execute_sql(
            statement,
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        tag_response = execute_sql(
            tag_uc_table_sql(catalog, schema, table_name, FINANCE_FOCUS_ASSET),
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        finance_statements.append(
            {
                "table": f"{catalog}.{schema}.{table_name}",
                "statementId": response.get("statement_id"),
                "tagStatementId": tag_response.get("statement_id"),
            }
        )
    operational_job_statement_id = ""
    operational_job_statement = finance_operational_job_tag_sql(args)
    if operational_job_statement:
        operational_job_response = execute_sql(
            operational_job_statement,
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        operational_job_statement_id = operational_job_response.get("statement_id") or ""

    enterprise_profiles = []
    for profile in enterprise_asset_profiles(args):
        enterprise_profiles.append(
            {
                **profile,
                "sourceColumn": source_column_for_profile(args, profile),
            }
        )
    enterprise_metadata_statements: list[dict[str, Any]] = []
    for profile in enterprise_profiles:
        comment_response = execute_sql(
            enterprise_asset_comment_sql(profile),
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        enterprise_metadata_statements.append(
            {
                "asset": profile["fqn"],
                "statementId": comment_response.get("statement_id"),
                "source": ENTERPRISE_SEED_SOURCE,
                "operation": "comment",
            }
        )
        response = execute_sql(
            enterprise_asset_tag_sql(profile),
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        enterprise_metadata_statements.append(
            {
                "asset": profile["fqn"],
                "statementId": response.get("statement_id"),
                "source": ENTERPRISE_SEED_SOURCE,
                "operation": "tags",
            }
        )
    for statement in enterprise_owner_refresh_sql(args.store_catalog, args.store_schema, enterprise_profiles):
        response = execute_sql(
            statement,
            profile=args.profile,
            warehouse_id=args.warehouse_id,
            timeout_s=args.timeout_s,
        )
        enterprise_metadata_statements.append(
            {
                "asset": "enterprise-owner-assignments",
                "statementId": response.get("statement_id"),
                "source": ENTERPRISE_SEED_SOURCE,
                "operation": "owners",
            }
        )

    verify = execute_sql(
        lineage_count_sql(args),
        profile=args.profile,
        warehouse_id=args.warehouse_id,
        timeout_s=args.timeout_s,
    )
    downstream_count = scalar_int(verify)
    finance_verify = execute_sql(
        finance_lineage_count_sql(),
        profile=args.profile,
        warehouse_id=args.warehouse_id,
        timeout_s=args.timeout_s,
    )
    finance_downstream_count = scalar_int(finance_verify)
    finance_evidence_verify = execute_sql(
        finance_governed_lineage_evidence_count_sql(),
        profile=args.profile,
        warehouse_id=args.warehouse_id,
        timeout_s=args.timeout_s,
    )
    finance_evidence_count = scalar_int(finance_evidence_verify)
    return {
        "source": "databricks-sql",
        "evidenceSource": SEED_SOURCE,
        "focusAsset": seeded_fqn(args, SOURCE_VIEW),
        "createdTables": statements,
        "financeFocusAsset": FINANCE_FOCUS_ASSET,
        "createdFinanceTables": finance_statements,
        "verificationStatementId": verify.get("statement_id"),
        "financeVerificationStatementId": finance_verify.get("statement_id"),
        "financeGovernedEvidenceStatementId": finance_evidence_verify.get("statement_id"),
        "financeOperationalJobStatementId": operational_job_statement_id,
        "financeOperationalJobId": str(args.operational_job_id or "").strip(),
        "financeOperationalJobName": str(args.operational_job_name or "").strip(),
        "enterpriseGovernanceEvidenceAssets": len(enterprise_profiles),
        "enterpriseGovernanceEvidenceStatements": enterprise_metadata_statements,
        "downstreamTargetCount": downstream_count,
        "financeDownstreamTargetCount": finance_downstream_count,
        "financeGovernedEvidenceTargetCount": finance_evidence_count,
        "passed": downstream_count >= 1 and finance_evidence_count >= 8,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--warehouse-id", default=DEFAULT_WAREHOUSE_ID, required=not DEFAULT_WAREHOUSE_ID)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--demo-schema", default=DEFAULT_DEMO_SCHEMA)
    parser.add_argument("--store-catalog", default=DEFAULT_STORE_CATALOG)
    parser.add_argument("--store-schema", default=DEFAULT_STORE_SCHEMA)
    parser.add_argument("--operational-job-id", default="")
    parser.add_argument("--operational-job-name", default="")
    parser.add_argument("--timeout-s", type=int, default=240)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    evidence = seed(args)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
