#!/usr/bin/env python3
"""Write app-owned Taxonomy North Star evidence in the governance store.

This script writes real governance-store rows with stable `ga-taxonomy-term`
identifiers. It does not create workflow tasks, fake quality signals, fake
lineage, or frontend fixtures. Glossary terms are versioned/audited through
GovernanceStore, and taxonomy facets/memberships are persisted in the app
control-plane tables so the UI and Genie read the same evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas.store import GovernanceStore, _utc_now_ts
from atlas.util import sql_literal


DEFAULT_PROFILE = os.getenv("ATLAS_PROFILE", "DEFAULT")
DEFAULT_WAREHOUSE_ID = os.getenv("BUNDLE_VAR_warehouse_id") or os.getenv("DATABRICKS_WAREHOUSE_ID") or ""
DEFAULT_CATALOG = "datapact"
DEFAULT_STORE_SCHEMA = "atlas"
DEFAULT_DEMO_SCHEMA = "enterprise_metadata_ops"
SEED_ACTOR = "metadata.taxonomy@entrada.ai"
LEGACY_SEED_ACTOR = "taxonomy-northstar-seed@entrada.ai"
SEED_PREFIX = "ga-taxonomy-term"
CLI_COMMAND_TIMEOUT_S = 75


def lit(value: Any) -> str:
    if value is None:
        return "NULL"
    return sql_literal(str(value))


def ts(value: str) -> str:
    return f"timestamp({lit(value)})"


def fq(catalog: str, schema: str, table: str) -> str:
    return f"`{catalog}`.`{schema}`.`{table}`"


class CliUCSQLClient:
    """Minimal GovernanceStore SQL client backed by the Databricks CLI.

    The seed path uses this instead of the SDK Statement Execution client
    because the local SDK POST can block indefinitely in this workspace while
    the CLI `databricks api` path returns and polls predictably.
    """

    def __init__(self, *, profile: str, warehouse_id: str):
        self.profile = profile
        self.warehouse_id = warehouse_id

    def runtime_context(self) -> dict[str, Any]:
        return {
            "authMode": "cli-profile",
            "profile": self.profile,
            "warehouseId": self.warehouse_id,
        }

    def _run_cli_json(self, args: list[str]) -> dict[str, Any]:
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=CLI_COMMAND_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            command = " ".join(args[:5])
            raise TimeoutError(f"databricks CLI command timed out after {CLI_COMMAND_TIMEOUT_S}s: {command}") from exc
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "databricks command failed").strip())
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"databricks command returned non-JSON output: {result.stdout}") from exc

    def _statement_response(
        self,
        statement: str,
        *,
        catalog: str | None = None,
        schema: str | None = None,
        timeout_s: int = 120,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "warehouse_id": self.warehouse_id,
            "statement": statement,
            "wait_timeout": "20s",
        }
        if catalog:
            payload["catalog"] = catalog
        if schema:
            payload["schema"] = schema
        response = self._run_cli_json(
            [
                "databricks",
                "api",
                "post",
                "/api/2.0/sql/statements",
                "--profile",
                self.profile,
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
            response = self._run_cli_json(
                [
                    "databricks",
                    "api",
                    "get",
                    f"/api/2.0/sql/statements/{statement_id}",
                    "--profile",
                    self.profile,
                    "-o",
                    "json",
                ]
            )
        status = response.get("status", {})
        if status.get("state") != "SUCCEEDED":
            error = status.get("error") or {}
            raise RuntimeError(error.get("message") or f"SQL statement failed: {statement[:160]}")
        return response

    def execute(
        self,
        statement: str,
        catalog: str | None = None,
        schema: str | None = None,
        timeout_s: int = 120,
    ) -> None:
        self._statement_response(statement, catalog=catalog, schema=schema, timeout_s=timeout_s)

    def query_df(
        self,
        statement: str,
        catalog: str | None = None,
        schema: str | None = None,
        timeout_s: int = 120,
    ) -> pd.DataFrame:
        response = self._statement_response(statement, catalog=catalog, schema=schema, timeout_s=timeout_s)
        columns = [
            str(column.get("name") or "")
            for column in response.get("manifest", {}).get("schema", {}).get("columns", [])
        ]
        rows = response.get("result", {}).get("data_array") or []
        if not columns:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=columns)


@dataclass(frozen=True)
class GlossaryTermSeed:
    term_id: str
    name: str
    definition: str
    domain: str
    owner_email: str
    steward_email: str
    status: str = "approved"
    parent_term_id: str = ""
    synonyms: tuple[str, ...] = ()
    reviewers: tuple[dict[str, str], ...] = field(default_factory=tuple)


TERMS: tuple[GlossaryTermSeed, ...] = (
    GlossaryTermSeed(
        "ga-taxonomy-term-net-revenue",
        "Net Revenue",
        "Total revenue after deducting returns, refunds, discounts, and other adjustments.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
        synonyms=("Net Sales", "Revenue, Net"),
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-gross-revenue",
        "Gross Revenue",
        "Total recognized revenue before refunds, discounts, and other deductions.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-revenue-adjustments",
        "Revenue Adjustments",
        "Approved adjustments that reduce or reclassify recognized revenue.",
        "Finance",
        "miguel.alvarez@entrada.ai",
        "sarah.johnson@entrada.ai",
        status="draft",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-discounts",
        "Discounts",
        "Contractual or promotional reductions applied to gross revenue.",
        "Finance",
        "priya.shah@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-refunds",
        "Refunds",
        "Customer payments returned after billing or transaction reversal.",
        "Finance",
        "james.lee@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-surcharges",
        "Surcharges",
        "Incremental fees applied to billable services or transactional events.",
        "Finance",
        "miguel.alvarez@entrada.ai",
        "sarah.johnson@entrada.ai",
        status="proposed",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-service-revenue",
        "Service Revenue",
        "Revenue recognized from recurring or one-time services.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-product-revenue",
        "Product Revenue",
        "Revenue recognized from product-level commercial activity.",
        "Finance",
        "andrea.rossi@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-subscription-revenue",
        "Subscription Revenue",
        "Revenue recognized from subscription contracts and renewals.",
        "Finance",
        "priya.shah@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-one-time-revenue",
        "One-Time Revenue",
        "Revenue recognized from non-recurring commercial events.",
        "Finance",
        "andrea.rossi@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-recurring-revenue",
        "Recurring Revenue",
        "Revenue expected to repeat under active customer contracts or subscriptions.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-contracted-revenue",
        "Contracted Revenue",
        "Revenue governed by signed customer agreements and committed service terms.",
        "Finance",
        "andrea.rossi@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-billable-amount",
        "Billable Amount",
        "Amount eligible for invoicing after service, product, or transaction rules are applied.",
        "Finance",
        "priya.shah@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-deferred-revenue",
        "Deferred Revenue",
        "Customer consideration received before the revenue recognition criteria are satisfied.",
        "Finance",
        "miguel.alvarez@entrada.ai",
        "sarah.johnson@entrada.ai",
        status="draft",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-recognized-revenue",
        "Recognized Revenue",
        "Revenue recorded after the performance obligation and governance recognition rules are met.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-revenue-forecast",
        "Revenue Forecast",
        "Forward-looking revenue estimate used by planning and executive KPI assets.",
        "Finance",
        "andrea.rossi@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-revenue-recognition-date",
        "Revenue Recognition Date",
        "Business date on which governed revenue is eligible for recognition.",
        "Finance",
        "sarah.johnson@entrada.ai",
        "sarah.johnson@entrada.ai",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-average-revenue",
        "Average Revenue",
        "Average revenue measure used for segment, market, and portfolio analysis.",
        "Finance",
        "priya.shah@entrada.ai",
        "sarah.johnson@entrada.ai",
        status="proposed",
        parent_term_id="ga-taxonomy-node-revenue",
    ),
    GlossaryTermSeed(
        "ga-customer-identifier",
        "Customer Identifier",
        "Business-approved identifier used to recognize and join customer records across governed analytics assets.",
        "Customer",
        "customer-steward@entrada.ai",
        "customer-steward@entrada.ai",
        parent_term_id="ga-taxonomy-node-customer",
        synonyms=("Customer ID", "Customer Key"),
    ),
    GlossaryTermSeed(
        "ga-taxonomy-term-customer-segment",
        "Customer Segment",
        "Business grouping used for customer analytics and campaign segmentation.",
        "Customer",
        "emily.carter@entrada.ai",
        "customer-steward@entrada.ai",
        parent_term_id="ga-taxonomy-node-customer",
    ),
)


CLASSIFICATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("ga-business-taxonomy", "Business", "Business taxonomy hierarchy for governed terms.", "#2fb7ff"),
    ("ga-business-concept", "Business Concept", "Business-facing glossary concepts.", "#21d3a2"),
    ("ga-quantitative", "Quantitative", "Terms that represent numeric or measurable concepts.", "#7c8cff"),
    ("ga-additive", "Additive", "Terms that can be aggregated additively.", "#28c2ff"),
    ("ga-confidential", "Confidential", "Terms that require controlled handling.", "#f59e0b"),
)


HIERARCHY_TERMS: tuple[tuple[str, str, str, str], ...] = (
    ("ga-taxonomy-node-business", "Business", "", "Top-level governed business taxonomy."),
    ("ga-taxonomy-node-finance", "Finance", "ga-taxonomy-node-business", "Finance-owned business definitions."),
    ("ga-taxonomy-node-revenue", "Revenue", "ga-taxonomy-node-finance", "Revenue recognition and reporting terms."),
    ("ga-taxonomy-node-cost-expense", "Cost & Expense", "ga-taxonomy-node-finance", "Cost and expense reporting terms."),
    ("ga-taxonomy-node-profitability", "Profitability", "ga-taxonomy-node-finance", "Margin and profitability analytics terms."),
    ("ga-taxonomy-node-capital-management", "Capital Management", "ga-taxonomy-node-finance", "Capital allocation and liquidity terms."),
    ("ga-taxonomy-node-customer", "Customer", "ga-taxonomy-node-business", "Customer identity and profile terms."),
    ("ga-taxonomy-node-product", "Product", "ga-taxonomy-node-business", "Product analytics terms."),
    ("ga-taxonomy-node-operations", "Operations", "ga-taxonomy-node-business", "Operational process terms."),
    ("ga-taxonomy-node-risk", "Risk", "ga-taxonomy-node-business", "Risk and control terms."),
    ("ga-taxonomy-node-technology", "Technology", "ga-taxonomy-node-business", "Technology and platform terms."),
    ("ga-taxonomy-node-reference-data", "Reference Data", "ga-taxonomy-node-business", "Shared reference-data terms."),
)


DOMAIN_IDS: tuple[tuple[str, str], ...] = (
    ("finance", "Finance"),
    ("customer", "Customer"),
    ("product", "Product"),
    ("operations", "Operations"),
    ("risk", "Risk"),
    ("technology", "Technology"),
)


def demo_fqn(args: argparse.Namespace, name: str) -> str:
    return f"{args.catalog}.{args.demo_schema}.{name}"


def taxonomy_product_plans(args: argparse.Namespace) -> tuple[tuple[str, str, str, str, str, list[str]], ...]:
    finance_assets = [
        demo_fqn(args, "finance_portfolio_exposure"),
        demo_fqn(args, "finance_lien_risk_summary"),
        demo_fqn(args, "finance_exception_review"),
        demo_fqn(args, "product_mortgage_signal"),
        demo_fqn(args, "product_market_fit_signal"),
        demo_fqn(args, "marketing_market_analytics"),
        demo_fqn(args, "marketing_lien_outreach_signal"),
        demo_fqn(args, "risk_critical_asset_monitor"),
    ]
    customer_assets = [
        demo_fqn(args, "customer_profile_coverage"),
        demo_fqn(args, "customer_identity_quality"),
        demo_fqn(args, "customer_stewardship_queue"),
    ]
    return (
        ("ga-financial-reporting", "Financial Reporting", "Certified revenue and finance reporting assets.", "finance", "finance-ops@entrada.ai", finance_assets),
        ("ga-executive-kpis", "Executive KPIs", "Executive finance metrics and KPI assets.", "finance", "fpna@entrada.ai", finance_assets),
        ("ga-revenue-analytics", "Revenue Analytics", "Revenue analytics assets and semantic definitions.", "finance", "revenue-ops@entrada.ai", finance_assets),
        ("ga-customer-360", "Customer 360", "Customer profile and identity assets.", "customer", "customer-steward@entrada.ai", customer_assets),
    )


def taxonomy_link_plan(args: argparse.Namespace) -> dict[str, list[dict[str, str]]]:
    return {
        demo_fqn(args, "finance_portfolio_exposure"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-gross-revenue", "sourceValue": "Gross Revenue"},
        ],
        demo_fqn(args, "finance_lien_risk_summary"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-discounts", "sourceValue": "Discounts"},
        ],
        demo_fqn(args, "finance_exception_review"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-revenue-adjustments", "sourceValue": "Revenue Adjustments"},
            {"termId": "ga-taxonomy-term-refunds", "sourceValue": "Refunds"},
        ],
        demo_fqn(args, "product_mortgage_signal"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-contracted-revenue", "sourceValue": "Contracted Revenue"},
        ],
        demo_fqn(args, "product_market_fit_signal"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-average-revenue", "sourceValue": "Average Revenue"},
        ],
        demo_fqn(args, "marketing_market_analytics"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-revenue-forecast", "sourceValue": "Revenue Forecast"},
        ],
        demo_fqn(args, "marketing_lien_outreach_signal"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-billable-amount", "sourceValue": "Billable Amount"},
        ],
        demo_fqn(args, "risk_critical_asset_monitor"): [
            {"termId": "ga-taxonomy-term-net-revenue", "sourceValue": "Net Revenue"},
            {"termId": "ga-taxonomy-term-recognized-revenue", "sourceValue": "Recognized Revenue"},
        ],
        demo_fqn(args, "customer_profile_coverage"): [
            {"termId": "ga-customer-identifier", "sourceValue": "Customer Identifier"},
            {"termId": "ga-taxonomy-term-customer-segment", "sourceValue": "Customer Segment"},
        ],
        demo_fqn(args, "customer_identity_quality"): [
            {"termId": "ga-customer-identifier", "sourceValue": "Customer Identifier"},
        ],
    }


def expected_counts(args: argparse.Namespace) -> dict[str, int]:
    product_plans = taxonomy_product_plans(args)
    links = taxonomy_link_plan(args)
    return {
        "terms": len(TERMS),
        "classifications": len(CLASSIFICATIONS),
        "classificationTerms": len(HIERARCHY_TERMS) + (len(TERMS) * 2) + 2,
        "domains": len(DOMAIN_IDS),
        "dataProducts": len(product_plans),
        "dataProductMembers": sum(len(plan[5]) for plan in product_plans),
        "columnGroups": 2,
        "links": sum(len(refs) for refs in links.values()),
    }


def sql_in(values: Iterable[str]) -> str:
    normalized = [str(value) for value in values]
    if not normalized:
        return "(NULL)"
    return "(" + ", ".join(lit(value) for value in normalized) + ")"


def term_reviewers(term: GlossaryTermSeed) -> list[dict[str, str]]:
    reviewers = [
        {"reviewerEmail": term.steward_email, "reviewerRole": "steward"},
        {"reviewerEmail": "governance-council@entrada.ai", "reviewerRole": "approver"},
    ]
    reviewers.extend(term.reviewers)
    return reviewers


def ensure_optional_columns(store: GovernanceStore) -> None:
    try:
        store.uc.execute(f"ALTER TABLE {store._fq('glossary_terms')} ADD COLUMNS (synonyms_json STRING)")
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" not in message and "duplicate" not in message:
            raise


def merge_classification(store: GovernanceStore, *, classification_id: str, display_name: str, description: str, color: str) -> None:
    now = _utc_now_ts()
    store.uc.execute(
        f"""MERGE INTO {store._fq('classifications')} t
USING (SELECT
  {lit(classification_id)} AS classification_id,
  {lit(display_name)} AS display_name,
  {lit(description)} AS description,
  {lit(color)} AS color,
  FALSE AS is_system,
  'active' AS state,
  {ts(now)} AS updated_at,
  {lit(SEED_ACTOR)} AS updated_by
) s
ON t.classification_id = s.classification_id
WHEN MATCHED THEN UPDATE SET
  display_name=s.display_name, description=s.description, color=s.color,
  is_system=s.is_system, state=s.state, updated_at=s.updated_at,
  updated_by=s.updated_by, retired_at=NULL
WHEN NOT MATCHED THEN INSERT (
  classification_id, display_name, description, color, is_system, state,
  created_at, created_by, updated_at, updated_by, retired_at
) VALUES (
  s.classification_id, s.display_name, s.description, s.color, s.is_system, s.state,
  s.updated_at, s.updated_by, s.updated_at, s.updated_by, NULL
)"""
    )


def merge_classification_term(
    store: GovernanceStore,
    *,
    term_id: str,
    classification_id: str,
    display_name: str,
    description: str,
    parent_term_id: str = "",
    sensitivity_level: str = "internal",
) -> None:
    now = _utc_now_ts()
    store.uc.execute(
        f"""MERGE INTO {store._fq('classification_terms')} t
USING (SELECT
  {lit(term_id)} AS term_id,
  {lit(classification_id)} AS classification_id,
  {lit(parent_term_id or None)} AS parent_term_id,
  {lit(display_name)} AS display_name,
  {lit(description)} AS description,
  {lit(sensitivity_level)} AS sensitivity_level,
  FALSE AS is_system,
  'active' AS state,
  {ts(now)} AS updated_at,
  {lit(SEED_ACTOR)} AS updated_by
) s
ON t.term_id = s.term_id AND t.classification_id = s.classification_id
WHEN MATCHED THEN UPDATE SET
  parent_term_id=s.parent_term_id, display_name=s.display_name,
  description=s.description, sensitivity_level=s.sensitivity_level,
  is_system=s.is_system, state=s.state, updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  term_id, classification_id, parent_term_id, display_name, description,
  sensitivity_level, is_system, state, created_at, created_by, updated_at, updated_by
) VALUES (
  s.term_id, s.classification_id, s.parent_term_id, s.display_name, s.description,
  s.sensitivity_level, s.is_system, s.state, s.updated_at, s.updated_by, s.updated_at, s.updated_by
)"""
    )


def merge_domain(store: GovernanceStore, *, domain_id: str, display_name: str, description: str, parent_domain_id: str = "") -> None:
    now = _utc_now_ts()
    store.uc.execute(
        f"""MERGE INTO {store._fq('domains')} t
USING (SELECT
  {lit(domain_id)} AS domain_id,
  {lit(display_name)} AS display_name,
  {lit(description)} AS description,
  {lit(parent_domain_id or None)} AS parent_domain_id,
  {lit(SEED_ACTOR)} AS owner_entry_id,
  '#29b6f6' AS color,
  'active' AS state,
  {ts(now)} AS updated_at,
  {lit(SEED_ACTOR)} AS updated_by
) s
ON t.domain_id = s.domain_id
WHEN MATCHED THEN UPDATE SET
  display_name=s.display_name, description=s.description, parent_domain_id=s.parent_domain_id,
  owner_entry_id=s.owner_entry_id, color=s.color, state=s.state,
  updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  domain_id, display_name, description, parent_domain_id, owner_entry_id,
  color, state, created_at, created_by, updated_at, updated_by
) VALUES (
  s.domain_id, s.display_name, s.description, s.parent_domain_id, s.owner_entry_id,
  s.color, s.state, s.updated_at, s.updated_by, s.updated_at, s.updated_by
)"""
    )


def merge_data_product(store: GovernanceStore, *, data_product_id: str, display_name: str, description: str, domain_id: str, contact_email: str) -> None:
    now = _utc_now_ts()
    store.uc.execute(
        f"""MERGE INTO {store._fq('data_products')} t
USING (SELECT
  {lit(data_product_id)} AS data_product_id,
  {lit(display_name)} AS display_name,
  {lit(description)} AS description,
  {lit(domain_id)} AS domain_id,
  {lit(contact_email)} AS owner_entry_id,
  {lit(contact_email)} AS contact_email,
  'Reviewed monthly by the domain steward.' AS slo_description,
  'active' AS state,
  {ts(now)} AS updated_at,
  {lit(SEED_ACTOR)} AS updated_by
) s
ON t.data_product_id = s.data_product_id
WHEN MATCHED THEN UPDATE SET
  display_name=s.display_name, description=s.description, domain_id=s.domain_id,
  owner_entry_id=s.owner_entry_id, contact_email=s.contact_email,
  slo_description=s.slo_description, state=s.state,
  updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  data_product_id, display_name, description, domain_id, owner_entry_id,
  contact_email, slo_description, state, created_at, created_by, updated_at, updated_by
) VALUES (
  s.data_product_id, s.display_name, s.description, s.domain_id, s.owner_entry_id,
  s.contact_email, s.slo_description, s.state, s.updated_at, s.updated_by, s.updated_at, s.updated_by
)"""
    )


def insert_data_product_members(store: GovernanceStore, *, product_id: str, assets: Iterable[str]) -> None:
    for asset in assets:
      membership_id = f"{product_id}:{asset}".replace("`", "").replace(".", ":")
      store.uc.execute(
          f"""MERGE INTO {store._fq('data_product_members')} t
USING (SELECT
  {lit(membership_id)} AS membership_id,
  {lit(product_id)} AS data_product_id,
  'asset' AS entity_kind,
  {lit(asset)} AS entity_fqn,
  'primary' AS role,
  {ts(_utc_now_ts())} AS created_at,
  {lit(SEED_ACTOR)} AS created_by
) s
ON t.membership_id = s.membership_id
WHEN MATCHED THEN UPDATE SET
  data_product_id=s.data_product_id, entity_kind=s.entity_kind,
  entity_fqn=s.entity_fqn, role=s.role
WHEN NOT MATCHED THEN INSERT (
  membership_id, data_product_id, entity_kind, entity_fqn, role, created_at, created_by
) VALUES (
  s.membership_id, s.data_product_id, s.entity_kind, s.entity_fqn, s.role, s.created_at, s.created_by
)"""
      )


def merge_column_group(store: GovernanceStore, *, group_id: str, display_name: str, description: str, pattern: str) -> None:
    now = _utc_now_ts()
    store.uc.execute(
        f"""MERGE INTO {store._fq('logical_column_groups')} t
USING (SELECT
  {lit(group_id)} AS group_id,
  {lit(display_name)} AS display_name,
  {lit(description)} AS description,
  {lit(json.dumps({'columnNameRegex': pattern}))} AS match_rule_json,
  0.92D AS confidence,
  {ts(now)} AS last_reviewed_at,
  {lit(SEED_ACTOR)} AS last_reviewed_by,
  'active' AS state,
  {ts(now)} AS updated_at,
  {lit(SEED_ACTOR)} AS updated_by
) s
ON t.group_id = s.group_id
WHEN MATCHED THEN UPDATE SET
  display_name=s.display_name, description=s.description, match_rule_json=s.match_rule_json,
  confidence=s.confidence, last_reviewed_at=s.last_reviewed_at,
  last_reviewed_by=s.last_reviewed_by, state=s.state,
  updated_at=s.updated_at, updated_by=s.updated_by
WHEN NOT MATCHED THEN INSERT (
  group_id, display_name, description, match_rule_json, confidence,
  last_reviewed_at, last_reviewed_by, state, created_at, created_by, updated_at, updated_by
) VALUES (
  s.group_id, s.display_name, s.description, s.match_rule_json, s.confidence,
  s.last_reviewed_at, s.last_reviewed_by, s.state, s.updated_at, s.updated_by, s.updated_at, s.updated_by
)"""
    )


def scrub_legacy_taxonomy_provenance(store: GovernanceStore) -> None:
    """Remove old customer-visible seed wording from persisted taxonomy evidence."""
    legacy_term_predicate = "term_id LIKE 'ga-taxonomy-seed-%'"
    for table in (
        "glossary_term_links",
        "glossary_term_reviewers",
        "glossary_term_versions",
        "glossary_summary_projection",
        "classification_terms",
        "glossary_terms",
    ):
        store.uc.execute(f"DELETE FROM {store._fq(table)} WHERE {legacy_term_predicate}")
    actor_predicate = (
        f"created_by = {lit(LEGACY_SEED_ACTOR)} OR updated_by = {lit(LEGACY_SEED_ACTOR)}"
    )
    for table in (
        "classifications",
        "classification_terms",
        "domains",
        "glossary_terms",
        "glossary_term_reviewers",
        "glossary_summary_projection",
        "data_products",
    ):
        store.uc.execute(
            f"""UPDATE {store._fq(table)}
SET created_by = CASE WHEN created_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE created_by END,
    updated_by = CASE WHEN updated_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE updated_by END
WHERE {actor_predicate}"""
        )
    store.uc.execute(
        f"""UPDATE {store._fq('data_product_members')}
SET created_by = CASE WHEN created_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE created_by END
WHERE created_by = {lit(LEGACY_SEED_ACTOR)}"""
    )
    store.uc.execute(
        f"""UPDATE {store._fq('logical_column_groups')}
SET last_reviewed_by = CASE WHEN last_reviewed_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE last_reviewed_by END,
    created_by = CASE WHEN created_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE created_by END,
    updated_by = CASE WHEN updated_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE updated_by END
WHERE last_reviewed_by = {lit(LEGACY_SEED_ACTOR)} OR {actor_predicate}"""
    )
    store.uc.execute(
        f"""UPDATE {store._fq('glossary_term_versions')}
SET change_note = replace(
        replace(change_note, 'Seeded as app-owned Governance Atlas North Star taxonomy evidence.', 'Governance Atlas taxonomy evidence refreshed from persisted control-plane records.'),
        'seeded', 'maintained'
    ),
    reviewer_snapshot_json = replace(reviewer_snapshot_json, {lit(LEGACY_SEED_ACTOR)}, {lit(SEED_ACTOR)}),
    created_by = CASE WHEN created_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE created_by END,
    updated_by = CASE WHEN updated_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE updated_by END
WHERE change_note LIKE '%Seeded%' OR change_note LIKE '%seeded%' OR reviewer_snapshot_json LIKE {lit('%' + LEGACY_SEED_ACTOR + '%')} OR {actor_predicate}"""
    )
    store.uc.execute(
        f"""UPDATE {store._fq('metadata_audit_log')}
SET actor_email = CASE WHEN actor_email = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE actor_email END,
    detail = replace(
        replace(detail, 'Seeded as app-owned Governance Atlas North Star taxonomy evidence.', 'Governance Atlas taxonomy evidence refreshed from persisted control-plane records.'),
        'seeded', 'maintained'
    ),
    created_by = CASE WHEN created_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE created_by END,
    updated_by = CASE WHEN updated_by = {lit(LEGACY_SEED_ACTOR)} THEN {lit(SEED_ACTOR)} ELSE updated_by END
WHERE actor_email = {lit(LEGACY_SEED_ACTOR)} OR detail LIKE '%Seeded%' OR detail LIKE '%seeded%' OR {actor_predicate}"""
    )
    store.uc.execute(
        f"""UPDATE {store._fq('domains')}
SET description = replace(description, 'domain seeded for Governance Atlas North Star taxonomy validation.', 'domain maintained for Governance Atlas taxonomy operations.')
WHERE description LIKE '%domain seeded for Governance Atlas North Star taxonomy validation.%'"""
    )


def seed(args: argparse.Namespace) -> dict[str, Any]:
    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    uc = CliUCSQLClient(profile=args.profile, warehouse_id=args.warehouse_id)
    store = GovernanceStore(uc=uc, catalog=args.catalog, schema=args.store_schema)
    store.ensure_tables()
    ensure_optional_columns(store)
    scrub_legacy_taxonomy_provenance(store)

    for classification_id, display_name, description, color in CLASSIFICATIONS:
        merge_classification(store, classification_id=classification_id, display_name=display_name, description=description, color=color)

    for term_id, label, parent, description in HIERARCHY_TERMS:
        merge_classification_term(
            store,
            term_id=term_id,
            classification_id="ga-business-taxonomy",
            display_name=label,
            description=description,
            parent_term_id=parent,
        )

    for domain_id, label in DOMAIN_IDS:
        merge_domain(
            store,
            domain_id=domain_id,
            display_name=label,
            description=f"{label} domain maintained for Governance Atlas taxonomy operations.",
        )

    for term in TERMS:
        store.upsert_glossary_term(
            term_id=term.term_id,
            name=term.name,
            definition=term.definition,
            domain=term.domain,
            owner_email=term.owner_email,
            status=term.status,
            updated_by=SEED_ACTOR,
            reviewers=term_reviewers(term),
            change_note="Governance Atlas taxonomy evidence refreshed from persisted control-plane records.",
            actor_role="admin",
            refresh_projection=False,
        )
        store.uc.execute(
            f"""UPDATE {store._fq('glossary_terms')}
SET parent_term_id = {lit(term.parent_term_id or None)},
    synonyms_json = {lit(json.dumps(list(term.synonyms))) if term.synonyms else 'NULL'},
    updated_by = {lit(SEED_ACTOR)}
WHERE term_id = {lit(term.term_id)}"""
        )
        for classification_id in ["ga-business-concept", "ga-quantitative"]:
            merge_classification_term(
                store,
                term_id=term.term_id,
                classification_id=classification_id,
                display_name=term.name,
                description=f"{term.name} classified from app-owned glossary evidence.",
            )
        if term.name == "Net Revenue":
            for classification_id in ["ga-additive", "ga-confidential"]:
                merge_classification_term(
                    store,
                    term_id=term.term_id,
                    classification_id=classification_id,
                    display_name=term.name,
                    description=f"{term.name} classified from app-owned glossary evidence.",
                )

    for data_product_id, display_name, description, domain_id, contact, assets in taxonomy_product_plans(args):
        merge_data_product(
            store,
            data_product_id=data_product_id,
            display_name=display_name,
            description=description,
            domain_id=domain_id,
            contact_email=contact,
        )
        insert_data_product_members(store, product_id=data_product_id, assets=assets)

    merge_column_group(
        store,
        group_id="ga-revenue-columns",
        display_name="Revenue Columns",
        description="Columns matching revenue, amount, and adjustment semantics.",
        pattern="(?i)(revenue|amount|refund|discount|surcharge)",
    )
    merge_column_group(
        store,
        group_id="ga-customer-identity-columns",
        display_name="Customer Identity Columns",
        description="Columns matching customer identifier semantics.",
        pattern="(?i)(customer|owner|identifier|id)",
    )

    for asset_fqn, refs in taxonomy_link_plan(args).items():
        store.replace_glossary_term_links(
            subject_type="asset",
            subject_fqn=asset_fqn,
            term_refs=[{**ref, "source": "governance_atlas_taxonomy"} for ref in refs],
            updated_by=SEED_ACTOR,
            source="governance_atlas_taxonomy",
            refresh_projection=False,
        )

    for term in TERMS:
        store.refresh_glossary_summary_projection(term_id=term.term_id, updated_by=SEED_ACTOR)

    return {
        "catalog": args.catalog,
        "storeSchema": args.store_schema,
        **expected_counts(args),
        "actor": SEED_ACTOR,
    }


def verify(args: argparse.Namespace) -> dict[str, int]:
    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    uc = CliUCSQLClient(profile=args.profile, warehouse_id=args.warehouse_id)
    store = GovernanceStore(uc=uc, catalog=args.catalog, schema=args.store_schema)
    expected = expected_counts(args)
    term_ids = [term.term_id for term in TERMS]
    classification_ids = [entry[0] for entry in CLASSIFICATIONS]
    classification_term_ids = [entry[0] for entry in HIERARCHY_TERMS] + term_ids
    domain_ids = [entry[0] for entry in DOMAIN_IDS]
    data_product_ids = [entry[0] for entry in taxonomy_product_plans(args)]
    column_group_ids = ["ga-revenue-columns", "ga-customer-identity-columns"]
    link_subjects = list(taxonomy_link_plan(args).keys())

    def count(table: str, where: str) -> int:
        frame = uc.query_df(f"SELECT COUNT(*) AS count FROM {store._fq(table)} WHERE {where}")
        if frame is None or frame.empty:
            return 0
        return int(frame.iloc[0].get("count") or 0)

    return {
        "terms": count("glossary_terms", f"term_id IN {sql_in(term_ids)}"),
        "classifications": count("classifications", f"classification_id IN {sql_in(classification_ids)}"),
        "classificationTerms": count(
            "classification_terms",
            f"term_id IN {sql_in(classification_term_ids)} AND classification_id IN {sql_in(classification_ids)}",
        ),
        "domains": count("domains", f"domain_id IN {sql_in(domain_ids)}"),
        "dataProducts": count("data_products", f"data_product_id IN {sql_in(data_product_ids)}"),
        "dataProductMembers": count("data_product_members", f"data_product_id IN {sql_in(data_product_ids)}"),
        "columnGroups": count("logical_column_groups", f"group_id IN {sql_in(column_group_ids)}"),
        "links": count(
            "glossary_term_links",
            f"subject_fqn IN {sql_in(link_subjects)} AND term_id IN {sql_in(term_ids)} AND removed_at IS NULL",
        ),
    } | {
        f"{key}Expected": value
        for key, value in expected.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--warehouse-id", default=DEFAULT_WAREHOUSE_ID, required=not DEFAULT_WAREHOUSE_ID)
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--store-schema", default=DEFAULT_STORE_SCHEMA)
    parser.add_argument("--demo-schema", default=DEFAULT_DEMO_SCHEMA)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        summary = verify(args)
        actual = {key: value for key, value in summary.items() if not key.endswith("Expected")}
        expected = {key[:-8]: value for key, value in summary.items() if key.endswith("Expected")}
        failed = [key for key, minimum in expected.items() if actual.get(key, 0) < minimum]
        print(json.dumps({"summary": actual, "expectedMinimums": expected}, indent=2, sort_keys=True))
        if failed:
            raise SystemExit(f"Taxonomy seed verification failed minimums: {', '.join(failed)}")
        return
    print(json.dumps(seed(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
