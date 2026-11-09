from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List

from axiom.util import sql_literal


DEFAULT_SPACE_TITLE = "Axiom Metadata Room"
DEFAULT_PARENT_PATH = "/Shared/Axiom/genie_spaces"
DEFAULT_AI_SCHEMA = "axiom_ai"
DEFAULT_DESCRIPTION = (
    "Curated Databricks Genie space for Axiom metadata and governance questions. "
    "Answers are constrained to UC-backed assets, governance work, glossary, quality, audit, and lineage views."
)


def _id(*parts: str) -> str:
    return hashlib.md5(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _qi(value: str) -> str:
    return "`" + str(value).replace("`", "``") + "`"


def _fq(catalog: str, schema: str, name: str) -> str:
    return ".".join([_qi(catalog), _qi(schema), _qi(name)])


def _identifier(catalog: str, schema: str, name: str) -> str:
    return ".".join([catalog, schema, name])


def curated_view_names() -> tuple[str, ...]:
    return (
        "axiom_ai_assets_current",
        "axiom_ai_governance_work_current",
        "axiom_ai_glossary_current",
        "axiom_ai_quality_latest",
        "axiom_ai_audit_events",
        "axiom_ai_lineage_edges",
    )


def curated_view_statements(*, catalog: str, store_schema: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    source = lambda name: _fq(catalog, store_schema, name)
    target = lambda name: _fq(catalog, ai_schema, name)
    catalog_lit = sql_literal(catalog)
    store_schema_lit = sql_literal(store_schema)
    ai_schema_lit = sql_literal(ai_schema)
    return [
        {
            "name": "create_schema",
            "required": True,
            "sql": f"CREATE SCHEMA IF NOT EXISTS {_qi(catalog)}.{_qi(ai_schema)}",
        },
        {
            "name": "axiom_ai_assets_current",
            "required": True,
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_assets_current')}
COMMENT 'Current actor-queryable Unity Catalog assets enriched with Axiom ownership, tags, and open work counts for Genie.'
AS
WITH tags AS (
  SELECT
    catalog_name,
    schema_name,
    table_name,
    MAX(CASE WHEN lower(tag_name) IN ('domain', 'business_domain') THEN tag_value END) AS domain,
    MAX(CASE WHEN lower(tag_name) IN ('tier', 'data_tier') THEN tag_value END) AS tier,
    MAX(CASE WHEN lower(tag_name) IN ('certification', 'certified') THEN tag_value END) AS certification,
    MAX(CASE WHEN lower(tag_name) IN ('sensitivity', 'classification') THEN tag_value END) AS sensitivity,
    MAX(CASE WHEN lower(tag_name) = 'criticality' THEN tag_value END) AS criticality,
    MAX(CASE WHEN lower(tag_name) IN ('data_product', 'product') THEN tag_value END) AS data_product
  FROM system.information_schema.table_tags
  WHERE catalog_name = {catalog_lit}
  GROUP BY catalog_name, schema_name, table_name
),
owners AS (
  SELECT
    uc_full_name AS asset_fqn,
    CONCAT_WS(', ', SORT_ARRAY(COLLECT_SET(owner_email))) AS business_owners,
    COUNT(DISTINCT owner_email) AS owner_count
  FROM {source('data_owners')}
  GROUP BY uc_full_name
),
open_work AS (
  SELECT
    uc_full_name AS asset_fqn,
    COUNT(1) AS open_work_count
  FROM {source('change_requests')}
  WHERE lower(COALESCE(status, 'pending')) = 'pending'
  GROUP BY uc_full_name
),
visible_tables AS (
  SELECT DISTINCT
    table_catalog,
    table_schema,
    table_name
  FROM system.information_schema.table_privileges
  WHERE table_catalog = {catalog_lit}
    AND privilege_type IN ('SELECT', 'BROWSE', 'ALL PRIVILEGES')
    AND (
      grantee = current_user()
      OR lower(grantee) IN ('users', 'account users', 'all users')
      OR is_account_group_member(grantee)
    )
),
visible_schemas AS (
  SELECT DISTINCT
    catalog_name AS table_catalog,
    schema_name AS table_schema
  FROM system.information_schema.schema_privileges
  WHERE catalog_name = {catalog_lit}
    AND privilege_type IN ('USE_SCHEMA', 'EXTERNAL_USE_SCHEMA', 'ALL_PRIVILEGES', 'MANAGE')
    AND (
      grantee = current_user()
      OR lower(grantee) IN ('users', 'account users', 'all users')
      OR is_account_group_member(grantee)
    )
)
SELECT
  CONCAT(t.table_catalog, '.', t.table_schema, '.', t.table_name) AS asset_fqn,
  t.table_catalog AS catalog_name,
  t.table_schema AS schema_name,
  t.table_name,
  t.table_type,
  t.comment,
  t.created,
  t.last_altered,
  tags.domain,
  tags.tier,
  tags.certification,
  tags.sensitivity,
  tags.criticality,
  tags.data_product,
  owners.business_owners,
  COALESCE(owners.owner_count, 0) AS owner_count,
  COALESCE(open_work.open_work_count, 0) AS open_work_count,
  COALESCE(owners.owner_count, 0) > 0 AS has_owner,
  -- Strict certification matches axiom.services.semantics.CERTIFIED_STRICT_VALUES:
  -- only an explicit "Certified" label counts. Trusted/Approved/Gold get their
  -- own facets and are never silently folded into "certified" (kept the numbers
  -- from drifting across surfaces in the 2026-07 audit).
  lower(COALESCE(tags.certification, '')) = 'certified' AS is_certified,
  lower(COALESCE(tags.criticality, '')) IN ('critical', 'high', 'tier 1', 'tier1', 'tier-1', 'p0', 'p1') AS is_critical
FROM system.information_schema.tables t
LEFT JOIN tags
  ON tags.catalog_name = t.table_catalog
 AND tags.schema_name = t.table_schema
 AND tags.table_name = t.table_name
LEFT JOIN owners
  ON owners.asset_fqn = CONCAT(t.table_catalog, '.', t.table_schema, '.', t.table_name)
LEFT JOIN open_work
  ON open_work.asset_fqn = CONCAT(t.table_catalog, '.', t.table_schema, '.', t.table_name)
WHERE t.table_catalog = {catalog_lit}
  AND (
    EXISTS (
      SELECT 1
      FROM visible_tables visible
      WHERE visible.table_catalog = t.table_catalog
        AND visible.table_schema = t.table_schema
        AND visible.table_name = t.table_name
    )
    OR EXISTS (
      SELECT 1
      FROM visible_schemas visible_schema
      WHERE visible_schema.table_catalog = t.table_catalog
        AND visible_schema.table_schema = t.table_schema
    )
  )
  AND lower(t.table_schema) NOT IN ('information_schema', lower({store_schema_lit}), lower({ai_schema_lit}), 'governance_hub')
  AND lower(CONCAT(t.table_catalog, '.', t.table_schema, '.', t.table_name)) NOT LIKE '%__materialization_mat_%'
  AND lower(t.table_name) NOT LIKE 'temp_metric_view_%'
  AND lower(t.table_name) NOT LIKE 'sdp_%'
  AND lower(t.table_name) NOT LIKE '%_sdp_%'
""".strip(),
        },
        {
            "name": "axiom_ai_governance_work_current",
            "required": True,
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_governance_work_current')}
COMMENT 'Current Axiom work queue and review state for Genie.'
AS
WITH work AS (
SELECT
  request_id AS work_id,
  'change_request' AS work_type,
  status,
  uc_full_name AS asset_fqn,
  new_comment AS title,
  new_uc_tags_json AS requested_tags_json,
  created_by,
  created_at,
  reviewed_by,
  reviewed_at,
  review_note
FROM {source('change_requests')}
UNION ALL
SELECT
  tasks.task_id AS work_id,
  tasks.task_type AS work_type,
  tasks.status,
  tasks.entity_fqn_snapshot AS asset_fqn,
  COALESCE(get_json_object(tasks.requested_payload_json, '$.title'), tasks.task_type, 'Governance task') AS title,
  tasks.requested_payload_json AS requested_tags_json,
  threads.created_by_entry_id AS created_by,
  tasks.created_at,
  tasks.reviewer_entry_id AS reviewed_by,
  CASE WHEN lower(COALESCE(tasks.status, '')) IN ('resolved', 'closed', 'rejected') THEN tasks.updated_at ELSE NULL END AS reviewed_at,
  get_json_object(tasks.resolved_payload_json, '$.reviewNote') AS review_note
FROM {source('tasks')} tasks
LEFT JOIN {source('threads')} threads
  ON threads.thread_id = tasks.thread_id
)
SELECT *
FROM work
WHERE asset_fqn IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM {target('axiom_ai_assets_current')} assets
    WHERE assets.asset_fqn = work.asset_fqn
  )
""".strip(),
        },
        {
            "name": "axiom_ai_glossary_current",
            "required": True,
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_glossary_current')}
COMMENT 'Current glossary terms, reviewer state, and linked assets for Genie.'
AS
WITH links AS (
  SELECT
    term_id,
    COUNT(1) AS linked_asset_count,
    CONCAT_WS(', ', SLICE(SORT_ARRAY(COLLECT_SET(subject_fqn)), 1, 20)) AS linked_assets_sample
  FROM {source('glossary_term_links')}
  WHERE removed_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM {target('axiom_ai_assets_current')} assets
      WHERE assets.asset_fqn = subject_fqn
    )
  GROUP BY term_id
),
reviewers AS (
  SELECT
    term_id,
    CONCAT_WS(', ', SORT_ARRAY(COLLECT_SET(reviewer_email))) AS reviewers
  FROM {source('glossary_term_reviewers')}
  GROUP BY term_id
)
SELECT
  terms.term_id,
  terms.glossary_id,
  terms.parent_term_id,
  terms.name,
  terms.name AS display_name,
  terms.definition,
  terms.status,
  terms.status AS review_status,
  terms.domain,
  terms.owner_email,
  reviewers.reviewers,
  COALESCE(links.linked_asset_count, 0) AS linked_asset_count,
  links.linked_assets_sample,
  terms.updated_at,
  terms.updated_by
FROM {source('glossary_terms')} terms
LEFT JOIN links ON links.term_id = terms.term_id
LEFT JOIN reviewers ON reviewers.term_id = terms.term_id
""".strip(),
        },
        {
            "name": "axiom_ai_quality_latest",
            "required": True,
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_quality_latest')}
COMMENT 'Latest Axiom quality result rows by asset and case for Genie.'
AS
WITH ranked AS (
  SELECT
    results.result_id,
    results.run_id,
    results.case_id,
    results.entity_fqn AS asset_fqn,
    results.column_name,
    results.outcome,
    results.severity,
    results.metric_value,
    results.threshold_value,
    results.evidence_json,
    results.statement_id,
    results.row_bytes_scanned,
    results.executed_at,
    results.detail,
    runs.suite_id,
    runs.trigger,
    runs.status AS run_status,
    ROW_NUMBER() OVER (
      PARTITION BY COALESCE(results.entity_fqn, ''), COALESCE(results.column_name, ''), results.case_id
      ORDER BY results.executed_at DESC, results.result_id DESC
    ) AS result_rank
  FROM {source('quality_run_results')} results
  LEFT JOIN {source('quality_runs')} runs
    ON runs.run_id = results.run_id
)
SELECT *
FROM ranked
WHERE result_rank = 1
  AND asset_fqn IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM {target('axiom_ai_assets_current')} assets
    WHERE assets.asset_fqn = ranked.asset_fqn
  )
""".strip(),
        },
        {
            "name": "axiom_ai_audit_events",
            "required": True,
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_audit_events')}
COMMENT 'Recent Axiom metadata audit events for Genie.'
AS
SELECT
  audit_id,
  entity_type,
  entity_id,
  entity_fqn AS asset_fqn,
  column_name,
  action,
  source,
  status,
  request_id,
  actor_email,
  actor_role,
  detail,
  created_at,
  updated_at
FROM {source('metadata_audit_log')}
WHERE entity_fqn IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM {target('axiom_ai_assets_current')} assets
    WHERE assets.asset_fqn = entity_fqn
  )
""".strip(),
        },
        {
            "name": "axiom_ai_lineage_edges",
            "required": False,
            "fallback_sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_lineage_edges')}
COMMENT 'Lineage edge view is unavailable in this workspace or for this principal.'
AS
SELECT
  CAST(NULL AS STRING) AS source_asset_fqn,
  CAST(NULL AS STRING) AS target_asset_fqn,
  CAST(NULL AS STRING) AS lineage_source,
  CAST(NULL AS TIMESTAMP) AS event_time,
  CAST('unavailable' AS STRING) AS availability_state
WHERE FALSE
""".strip(),
            "sql": f"""
CREATE OR REPLACE VIEW {target('axiom_ai_lineage_edges')}
COMMENT 'Unity Catalog table lineage edges available to the current workspace for Genie.'
AS
SELECT
  source_table_full_name AS source_asset_fqn,
  target_table_full_name AS target_asset_fqn,
  COALESCE(source_type, entity_type, 'uc_lineage') AS lineage_source,
  event_time,
  'available' AS availability_state
FROM system.access.table_lineage
WHERE event_date >= date_sub(current_date(), 90)
  AND (source_table_full_name IS NOT NULL OR target_table_full_name IS NOT NULL)
  AND (
    EXISTS (
      SELECT 1
      FROM {target('axiom_ai_assets_current')} assets
      WHERE assets.asset_fqn = source_table_full_name
    )
    OR EXISTS (
      SELECT 1
      FROM {target('axiom_ai_assets_current')} assets
      WHERE assets.asset_fqn = target_table_full_name
    )
  )
""".strip(),
        },
    ]


def _column(name: str, description: str, synonyms: Iterable[str] = ()) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "column_name": name,
        "description": [description],
    }
    if synonyms:
        config["synonyms"] = list(synonyms)
        config["enable_format_assistance"] = True
        config["enable_entity_matching"] = True
    return config


def _table(identifier: str, description: str, columns: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "identifier": identifier,
        "description": [description],
        "column_configs": sorted(columns, key=lambda column: column["column_name"]),
    }


# Shared vocabularies so the instructions, examples, and benchmarks agree.
# Open statuses match axiom.services.axiom_metrics._OPEN_EXCEPTION_STATUSES plus
# "blocked"; failing outcomes match the "failing" filter in axiom.services.quality.
OPEN_WORK_STATUSES = ("", "new", "pending", "open", "in_review", "blocked")
CLOSED_WORK_STATUSES = ("approved", "rejected", "resolved", "closed", "applied", "cancelled", "canceled", "done")
FAILING_QUALITY_OUTCOMES = ("failed", "errored")
SENSITIVE_VALUES = ("pii", "phi", "pci", "confidential", "highly confidential", "restricted", "sensitive", "secret")


def _sql_list(values: Iterable[str]) -> str:
    return "(" + ", ".join(sql_literal(value) for value in values) + ")"


_OPEN = _sql_list(OPEN_WORK_STATUSES)
_CLOSED = _sql_list(CLOSED_WORK_STATUSES)
_FAILING = _sql_list(FAILING_QUALITY_OUTCOMES)
_SENSITIVE = (
    f"(lower(COALESCE(sensitivity, '')) IN {_sql_list(SENSITIVE_VALUES)}"
    " OR lower(COALESCE(sensitivity, '')) LIKE '%pii%')"
)
_DOCUMENTED = "NULLIF(trim(comment), '') IS NOT NULL"
_COVERAGE_SCORE = (
    f"(CASE WHEN {_DOCUMENTED} THEN 1 ELSE 0 END"
    " + CASE WHEN has_owner THEN 1 ELSE 0 END"
    " + CASE WHEN domain IS NOT NULL THEN 1 ELSE 0 END"
    " + CASE WHEN sensitivity IS NOT NULL THEN 1 ELSE 0 END"
    " + CASE WHEN certification IS NOT NULL THEN 1 ELSE 0 END)"
)


def table_configs(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    identifier = lambda name: _identifier(catalog, ai_schema, name)
    asset_synonyms = ["asset", "table", "view", "dataset", "data set"]
    tables = [
        _table(
            identifier("axiom_ai_assets_current"),
            "Current Unity Catalog asset inventory (one row per table or view the current user can see) enriched with "
            "Unity Catalog tags, Axiom owner assignments, certification, criticality, and pending change-request counts. "
            "Default table for any asset, inventory, ownership, certification, sensitivity, or metadata-coverage question.",
            [
                _column("asset_fqn", "Fully qualified asset name in catalog.schema.table form. Always return it so users can verify the answer.", asset_synonyms),
                _column("catalog_name", "Unity Catalog catalog that contains the asset."),
                _column("schema_name", "Unity Catalog schema that contains the asset.", ["schema", "database"]),
                _column("table_name", "Table or view name without catalog and schema.", ["table name", "view name"]),
                _column("table_type", "Unity Catalog object type such as MANAGED, EXTERNAL, VIEW, MATERIALIZED_VIEW, STREAMING_TABLE, or METRIC_VIEW.", ["object type", "asset type", "table type"]),
                _column("comment", "Unity Catalog description. NULL or blank means the asset is undocumented."),
                _column("created", "Timestamp when the asset was created."),
                _column("last_altered", "Timestamp of the last schema or metadata change. Use for staleness and recently-changed questions."),
                _column("domain", "Business domain from the domain or business_domain tag. NULL means no domain tag.", ["domain", "business area", "business domain"]),
                _column("tier", "Data tier from the tier or data_tier tag.", ["tier", "data tier", "layer"]),
                _column("certification", "Raw certification tag value. Only the exact value Certified counts as certified; Trusted, Approved, or Gold are different labels.", ["certification", "certification label"]),
                _column("sensitivity", "Sensitivity or classification tag value such as PII, Confidential, Restricted, or Public. NULL means unclassified.", ["sensitivity", "classification", "pii", "data classification"]),
                _column("criticality", "Criticality tag value such as Critical, High, Tier 1, P0, or P1.", ["criticality", "critical asset", "business criticality"]),
                _column("data_product", "Data product from the data_product or product tag.", ["data product", "product"]),
                _column("business_owners", "Comma-separated owner emails assigned in Axiom. NULL means no Axiom owner. Unity Catalog object owners and owner tags are not included.", ["owner", "steward", "data owner", "business owner"]),
                _column("owner_count", "Number of distinct Axiom owners assigned to the asset."),
                _column("open_work_count", "Number of pending Axiom change requests on the asset. Workflow tasks are counted in axiom_ai_governance_work_current, not here."),
                _column("has_owner", "True when the asset has at least one Axiom owner."),
                _column("is_certified", "True only when the certification tag equals Certified (case-insensitive)."),
                _column("is_critical", "True when criticality is critical, high, tier 1, p0, or p1."),
            ],
        ),
        _table(
            identifier("axiom_ai_governance_work_current"),
            "Axiom governance work: change requests and workflow tasks, one row per work item, with status, requester, and review outcome. "
            "Only work on assets visible in axiom_ai_assets_current is included.",
            [
                _column("work_id", "Change request or task identifier. Return it so users can open the item in Axiom.", ["request", "task", "ticket", "work item"]),
                _column("work_type", "change_request for metadata change requests, otherwise the workflow task type.", ["request type", "task type", "work type"]),
                _column("status", "Work status. Open: blank, new, pending, open, in_review, blocked. Closed: approved, rejected, resolved, closed, applied, cancelled, done.", ["state", "status", "workflow status"]),
                _column("asset_fqn", "Asset the work item changes.", ["asset", "table"]),
                _column("title", "Short description of the requested change."),
                _column("requested_tags_json", "JSON payload of the requested tags or change. Use get_json_object to read fields."),
                _column("created_by", "Requester identifier (email or directory entry id).", ["requester", "requested by", "submitter"]),
                _column("created_at", "Timestamp when the work item was created."),
                _column("reviewed_by", "Reviewer identifier when reviewed.", ["reviewer", "approver"]),
                _column("reviewed_at", "Timestamp when the work item was reviewed or closed. NULL while open."),
                _column("review_note", "Reviewer note or rejection reason."),
            ],
        ),
        _table(
            identifier("axiom_ai_glossary_current"),
            "Business glossary terms with hierarchy, status, owner, reviewers, and the assets each term is linked to.",
            [
                _column("term_id", "Stable glossary term identifier."),
                _column("glossary_id", "Glossary the term belongs to."),
                _column("parent_term_id", "Parent term identifier for hierarchical terms. NULL for top-level terms."),
                _column("name", "Glossary term name.", ["term", "business term", "glossary term"]),
                _column("display_name", "Display name for the term (same as name)."),
                _column("definition", "Business definition of the term. NULL or blank means undefined.", ["meaning", "definition"]),
                _column("status", "Term lifecycle status such as draft, in_review, approved, or deprecated.", ["term status"]),
                _column("review_status", "Review state for the term (same values as status).", ["review state"]),
                _column("domain", "Business domain of the term.", ["domain", "business area"]),
                _column("owner_email", "Term owner email.", ["term owner", "owner"]),
                _column("reviewers", "Comma-separated reviewer emails."),
                _column("linked_asset_count", "Number of visible assets linked to the term. 0 means the term is not linked to any asset."),
                _column("linked_assets_sample", "Up to 20 linked asset FQNs, comma-separated."),
                _column("updated_at", "Timestamp of the last term update."),
                _column("updated_by", "Who last updated the term."),
            ],
        ),
        _table(
            identifier("axiom_ai_quality_latest"),
            "Latest data quality result per asset, column, and test case (older results are excluded). "
            "outcome is passed, failed, errored, or skipped; failed and errored are failing.",
            [
                _column("result_id", "Quality result identifier."),
                _column("run_id", "Quality run that produced the result."),
                _column("case_id", "Quality test case identifier.", ["test", "check", "rule", "quality check"]),
                _column("asset_fqn", "Asset tested by the quality result.", ["asset", "table"]),
                _column("column_name", "Column tested, when applicable. NULL for table-level checks.", ["column", "field"]),
                _column("outcome", "Latest outcome: passed, failed, errored, or skipped.", ["result", "test result", "quality issue", "pass", "fail"]),
                _column("severity", "Severity: critical, high, medium, or low.", ["severity", "priority"]),
                _column("metric_value", "Observed metric value."),
                _column("threshold_value", "Configured threshold for the check."),
                _column("evidence_json", "JSON evidence captured for the result."),
                _column("statement_id", "Databricks SQL statement id that executed the check."),
                _column("row_bytes_scanned", "Bytes scanned by the check."),
                _column("executed_at", "Timestamp when the check executed."),
                _column("detail", "Human-readable result detail."),
                _column("suite_id", "Quality suite that owns the run."),
                _column("trigger", "What started the run, such as manual or schedule."),
                _column("run_status", "Status of the quality run."),
                _column("result_rank", "Always 1; the view keeps only the latest result per asset, column, and case."),
            ],
        ),
        _table(
            identifier("axiom_ai_audit_events"),
            "Axiom metadata audit log: one row per governance action on a visible asset, such as owner, tag, comment, quality, or workflow changes.",
            [
                _column("audit_id", "Audit event identifier. Return it so users can verify the event."),
                _column("entity_type", "Kind of entity changed, such as table or column."),
                _column("entity_id", "Identifier of the changed entity."),
                _column("asset_fqn", "Asset affected by the audit event.", ["asset", "table"]),
                _column("column_name", "Column affected, when the change is column-level.", ["column"]),
                _column("action", "Audit action such as owner-upserted, asset-metadata-updated, asset-metadata-proposed, column-tags-updated, task-created, or quality-run-executed.", ["change", "event", "activity", "action"]),
                _column("source", "Where the change came from, such as ui, api, ai, or job.", ["origin", "channel"]),
                _column("status", "Outcome of the action, such as applied, queued, failed, or skipped.", ["outcome", "result"]),
                _column("request_id", "Related change request id, when any."),
                _column("actor_email", "Who performed the action.", ["user", "actor", "changed by", "who"]),
                _column("actor_role", "Role of the actor at the time of the action."),
                _column("detail", "Event detail text."),
                _column("created_at", "Event timestamp."),
                _column("updated_at", "Timestamp of the last update to the event."),
            ],
        ),
        _table(
            identifier("axiom_ai_lineage_edges"),
            "Unity Catalog table lineage edges from system.access.table_lineage for the last 90 days, limited to edges that touch a visible asset. "
            "One row per observed lineage event, so count DISTINCT assets. Empty when lineage is unavailable to the workspace or user.",
            [
                _column("source_asset_fqn", "Upstream asset (read from). NULL for non-table sources such as files.", ["upstream", "source", "feeds", "input"]),
                _column("target_asset_fqn", "Downstream asset (written to). NULL when the target is not a table, such as a dashboard or notebook read.", ["downstream", "target", "consumer", "output"]),
                _column("lineage_source", "Kind of lineage event or entity, such as TABLE, NOTEBOOK, JOB, or PIPELINE."),
                _column("event_time", "Timestamp when the lineage event was observed."),
                _column("availability_state", "available when real lineage rows exist; the fallback view is empty."),
            ],
        ),
    ]
    return sorted(tables, key=lambda table: table["identifier"])


def text_instructions() -> List[Dict[str, Any]]:
    content = [
        "You are Axiom AI, the Shore Capital governance assistant. Answer only from the six curated Axiom views in this room. "
        "Never invent assets, owners, workflow state, glossary links, quality results, lineage, certification, or audit history.\n",
        "Evidence rules: Never synthesize fallback rows, sentinel assets, or placeholder identifiers such as unavailable, none, no_data, or n/a. "
        "Never use UNION ALL SELECT fallbacks to fabricate a no-results row. If a query returns zero rows, keep the result empty and say "
        "that no governed evidence rows were observed for that question; do not guess. When returning rows, include asset_fqn, work_id, "
        "audit_id, term_id, or case_id so users can verify the answer, plus the relevant timestamp.\n",
        "Table choice: use axiom_ai_assets_current as the default inventory. Join to governance work, quality, audit, or lineage on asset_fqn "
        "only when the question asks for that evidence. Lineage joins use source_asset_fqn (upstream) or target_asset_fqn (downstream). "
        "Glossary links are in linked_assets_sample; there is no join key from glossary to assets.\n",
        "Definitions: certified means is_certified = TRUE (certification tag exactly Certified). Critical means is_critical = TRUE. "
        "Owned means has_owner = TRUE (an Axiom owner assignment; Unity Catalog object owners do not count). "
        "Documented means comment is not NULL and not blank. Sensitive means sensitivity is PII, PHI, PCI, Confidential, Highly Confidential, "
        "Restricted, Sensitive, or Secret, or contains pii. Unclassified means sensitivity IS NULL. "
        "Metadata coverage is a 0-5 score: one point each for a description, an owner, a domain tag, a sensitivity tag, and a certification tag. "
        "Stale means last_altered more than 180 days ago.\n",
        "Workflow: open work has status blank, new, pending, open, in_review, or blocked; closed work has status approved, rejected, resolved, "
        "closed, applied, cancelled, or done. Compare status with lower(). Age is datediff(current_date(), created_at) in days. "
        "Review turnaround is the time between created_at and reviewed_at for reviewed items. open_work_count on assets counts pending change "
        "requests only; count tasks from axiom_ai_governance_work_current.\n",
        "Quality: axiom_ai_quality_latest holds only the latest result per asset, column, and case. Failing means outcome failed or errored. "
        "Pass rate is passed / (passed + failed + errored); exclude skipped. Order severity critical, high, medium, low.\n",
        "Lineage: rows are lineage events, not unique edges, so use COUNT(DISTINCT ...). The view covers the last 90 days. "
        "If the lineage view is empty, say lineage evidence is unavailable rather than claiming an asset has no dependencies.\n",
        "Risk and stewardship: prefer pending work, missing owner, missing certification on critical assets, failing quality checks, "
        "sensitive unowned assets, and recent audit events as evidence. Time windows: recently means the last 30 days unless the user says otherwise; "
        "this quarter means created_at >= date_trunc('quarter', current_date()).\n",
        "Formatting: default to LIMIT 25 for lists, order by the most important signal first then asset_fqn for stable results, round percentages "
        "to one decimal place, and show COALESCE(domain, 'Unassigned') for missing domains.",
    ]
    return [{"id": _id("instruction", "axiom"), "content": content}]


def _example_catalog(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, str]]:
    A = _fq(catalog, ai_schema, "axiom_ai_assets_current")
    W = _fq(catalog, ai_schema, "axiom_ai_governance_work_current")
    G = _fq(catalog, ai_schema, "axiom_ai_glossary_current")
    Q = _fq(catalog, ai_schema, "axiom_ai_quality_latest")
    U = _fq(catalog, ai_schema, "axiom_ai_audit_events")
    L = _fq(catalog, ai_schema, "axiom_ai_lineage_edges")
    entries = [
        # Inventory and metadata coverage
        ("inventory_by_schema_type", "How many assets do we have by schema and type?", f"""SELECT schema_name, table_type, COUNT(*) AS asset_count
FROM {A}
GROUP BY schema_name, table_type
ORDER BY asset_count DESC, schema_name, table_type""",
         "Use for inventory size and breakdown questions."),
        ("coverage_overall", "What is our overall metadata coverage?", f"""SELECT
  COUNT(*) AS total_assets,
  ROUND(100.0 * AVG(CASE WHEN {_DOCUMENTED} THEN 1 ELSE 0 END), 1) AS pct_documented,
  ROUND(100.0 * AVG(CASE WHEN has_owner THEN 1 ELSE 0 END), 1) AS pct_owned,
  ROUND(100.0 * AVG(CASE WHEN domain IS NOT NULL THEN 1 ELSE 0 END), 1) AS pct_domain_tagged,
  ROUND(100.0 * AVG(CASE WHEN sensitivity IS NOT NULL THEN 1 ELSE 0 END), 1) AS pct_classified,
  ROUND(100.0 * AVG(CASE WHEN is_certified THEN 1 ELSE 0 END), 1) AS pct_certified
FROM {A}""",
         "Use for estate-wide metadata completeness and governance KPI questions."),
        ("coverage_lowest", "Which assets have the lowest metadata coverage?", f"""SELECT asset_fqn, table_type,
  {_COVERAGE_SCORE} AS coverage_score,
  {_DOCUMENTED} AS has_description, has_owner, domain, sensitivity, certification
FROM {A}
ORDER BY coverage_score ASC, is_critical DESC, asset_fqn
LIMIT 25""",
         "Use for lowest-coverage and metadata-gap questions. Coverage is the 0-5 score from the instructions."),
        ("coverage_by_schema", "Which schemas have the most undocumented assets?", f"""SELECT schema_name,
  COUNT(*) AS assets,
  SUM(CASE WHEN {_DOCUMENTED} THEN 0 ELSE 1 END) AS undocumented_assets,
  ROUND(100.0 * AVG(CASE WHEN {_DOCUMENTED} THEN 0 ELSE 1 END), 1) AS pct_undocumented
FROM {A}
GROUP BY schema_name
ORDER BY undocumented_assets DESC, schema_name""",
         "Use for documentation gaps rolled up by schema."),
        ("undocumented_assets", "Which assets have no description?", f"""SELECT asset_fqn, table_type, domain, business_owners, last_altered
FROM {A}
WHERE NOT ({_DOCUMENTED})
ORDER BY is_critical DESC, last_altered DESC, asset_fqn
LIMIT 50""",
         "Use for missing description or undocumented asset lists."),
        ("new_assets", "Which assets were created in the last 30 days?", f"""SELECT asset_fqn, table_type, created, has_owner, {_DOCUMENTED} AS has_description
FROM {A}
WHERE created >= current_timestamp() - INTERVAL 30 DAYS
ORDER BY created DESC, asset_fqn
LIMIT 50""",
         "Use for newly created asset questions. Change the interval for other windows."),
        ("stale_assets", "Which assets have not changed in over 180 days?", f"""SELECT asset_fqn, table_type, last_altered,
  datediff(current_date(), last_altered) AS days_since_change, has_owner, is_certified
FROM {A}
WHERE last_altered < current_timestamp() - INTERVAL 180 DAYS
ORDER BY last_altered ASC, asset_fqn
LIMIT 50""",
         "Use for stale, abandoned, or unmaintained asset questions."),
        ("assets_by_domain", "How are assets distributed across domains?", f"""SELECT COALESCE(domain, 'Unassigned') AS domain,
  COUNT(*) AS assets,
  SUM(CASE WHEN is_certified THEN 1 ELSE 0 END) AS certified_assets,
  SUM(CASE WHEN is_critical THEN 1 ELSE 0 END) AS critical_assets,
  SUM(CASE WHEN has_owner THEN 0 ELSE 1 END) AS unowned_assets
FROM {A}
GROUP BY COALESCE(domain, 'Unassigned')
ORDER BY assets DESC, domain""",
         "Use for domain breakdowns and domain-level governance posture."),
        ("assets_by_data_product", "Which data products have the most assets?", f"""SELECT data_product,
  COUNT(*) AS assets,
  SUM(CASE WHEN is_certified THEN 1 ELSE 0 END) AS certified_assets,
  SUM(CASE WHEN is_critical THEN 1 ELSE 0 END) AS critical_assets
FROM {A}
WHERE data_product IS NOT NULL
GROUP BY data_product
ORDER BY assets DESC, data_product
LIMIT 25""",
         "Use for data product size and composition questions."),
        # Classification and sensitivity
        ("sensitive_assets", "Which assets contain sensitive or PII data?", f"""SELECT asset_fqn, sensitivity, domain, business_owners, is_certified
FROM {A}
WHERE {_SENSITIVE}
ORDER BY sensitivity, asset_fqn
LIMIT 50""",
         "Use for PII, confidential, restricted, or sensitive data questions."),
        ("sensitive_unowned", "Which sensitive assets have no owner?", f"""SELECT asset_fqn, sensitivity, domain, criticality, open_work_count
FROM {A}
WHERE {_SENSITIVE}
  AND NOT has_owner
ORDER BY is_critical DESC, asset_fqn
LIMIT 50""",
         "Use for high-risk ownership gaps on sensitive data."),
        ("unclassified_critical", "Which critical assets have no sensitivity classification?", f"""SELECT asset_fqn, domain, criticality, business_owners
FROM {A}
WHERE is_critical
  AND sensitivity IS NULL
ORDER BY asset_fqn
LIMIT 50""",
         "Use for classification gaps on critical assets."),
        # Certification and criticality
        ("critical_uncertified", "Which critical assets are not certified?", f"""SELECT asset_fqn, domain, data_product, criticality, certification, business_owners
FROM {A}
WHERE is_critical = TRUE
  AND is_certified = FALSE
ORDER BY owner_count ASC, open_work_count DESC, asset_fqn
LIMIT 25""",
         "Use for critical-asset certification gap questions."),
        ("certification_rate_by_domain", "What is the certification rate by domain?", f"""SELECT COALESCE(domain, 'Unassigned') AS domain,
  COUNT(*) AS assets,
  SUM(CASE WHEN is_certified THEN 1 ELSE 0 END) AS certified_assets,
  ROUND(100.0 * AVG(CASE WHEN is_certified THEN 1 ELSE 0 END), 1) AS certification_rate_pct
FROM {A}
GROUP BY COALESCE(domain, 'Unassigned')
ORDER BY certification_rate_pct ASC, assets DESC, domain""",
         "Use for certification progress by domain."),
        ("certification_labels", "Which certification labels are in use?", f"""SELECT COALESCE(certification, 'Not tagged') AS certification,
  COUNT(*) AS assets,
  SUM(CASE WHEN is_certified THEN 1 ELSE 0 END) AS counted_as_certified
FROM {A}
GROUP BY COALESCE(certification, 'Not tagged')
ORDER BY assets DESC, certification""",
         "Use to explain which certification tag values exist and which count as certified."),
        # Ownership and stewardship
        ("unowned_assets", "Which assets have no assigned owner?", f"""SELECT asset_fqn, table_type, domain, criticality, sensitivity, open_work_count
FROM {A}
WHERE NOT has_owner
ORDER BY is_critical DESC, open_work_count DESC, asset_fqn
LIMIT 50""",
         "Use for unowned or orphaned asset questions."),
        ("owner_portfolio", "Who owns the most assets?", f"""WITH owner_assets AS (
  SELECT asset_fqn, is_critical, is_certified, trim(owner_raw) AS owner_email
  FROM {A}
  LATERAL VIEW explode(split(business_owners, ',')) owner_list AS owner_raw
  WHERE business_owners IS NOT NULL
)
SELECT owner_email,
  COUNT(DISTINCT asset_fqn) AS owned_assets,
  COUNT(DISTINCT CASE WHEN is_critical THEN asset_fqn END) AS critical_assets,
  COUNT(DISTINCT CASE WHEN is_certified THEN asset_fqn END) AS certified_assets
FROM owner_assets
WHERE owner_email <> ''
GROUP BY owner_email
ORDER BY owned_assets DESC, owner_email
LIMIT 25""",
         "Use for owner workload and stewardship portfolio questions."),
        ("stewardship_attention", "Which assets are missing stewardship attention?", f"""SELECT asset_fqn, domain, data_product, owner_count, open_work_count, certification, criticality
FROM {A}
WHERE owner_count = 0 OR open_work_count > 0
ORDER BY open_work_count DESC, owner_count ASC, is_critical DESC, asset_fqn
LIMIT 25""",
         "Use for ownership and stewardship attention questions."),
        ("domain_policy_risk", "Which domains have the highest risk of policy exceptions?", f"""SELECT
  COALESCE(assets.domain, 'Unassigned') AS domain,
  COUNT(DISTINCT assets.asset_fqn) AS governed_assets,
  COUNT(DISTINCT CASE WHEN lower(COALESCE(work.status, '')) IN {_OPEN} THEN work.work_id END) AS open_policy_work,
  COUNT(DISTINCT CASE WHEN assets.is_critical AND NOT assets.is_certified THEN assets.asset_fqn END) AS uncertified_critical_assets,
  COUNT(DISTINCT CASE WHEN NOT assets.has_owner THEN assets.asset_fqn END) AS unowned_assets
FROM {A} assets
LEFT JOIN {W} work
  ON work.asset_fqn = assets.asset_fqn
GROUP BY COALESCE(assets.domain, 'Unassigned')
ORDER BY open_policy_work DESC, uncertified_critical_assets DESC, unowned_assets DESC, governed_assets DESC
LIMIT 10""",
         "Use for domain-risk and policy-exception concentration questions."),
        # Governance work
        ("work_status_summary", "How many governance requests are there by status and type?", f"""SELECT lower(COALESCE(status, '')) AS status, work_type, COUNT(*) AS work_items
FROM {W}
GROUP BY lower(COALESCE(status, '')), work_type
ORDER BY work_items DESC, status, work_type""",
         "Use for workflow volume and status breakdowns."),
        ("oldest_open_work", "What is the oldest open governance work?", f"""SELECT work_id, work_type, status, asset_fqn, title, created_by, created_at,
  datediff(current_date(), created_at) AS age_days
FROM {W}
WHERE lower(COALESCE(status, '')) IN {_OPEN}
ORDER BY created_at ASC, work_id
LIMIT 25""",
         "Use for backlog aging and overdue governance work."),
        ("review_turnaround", "What is the average review turnaround time?", f"""SELECT work_type,
  COUNT(*) AS reviewed_items,
  ROUND(AVG((unix_timestamp(reviewed_at) - unix_timestamp(created_at)) / 3600.0), 1) AS avg_hours_to_review,
  ROUND(percentile_approx((unix_timestamp(reviewed_at) - unix_timestamp(created_at)) / 3600.0, 0.5), 1) AS median_hours_to_review
FROM {W}
WHERE reviewed_at IS NOT NULL
  AND created_at IS NOT NULL
GROUP BY work_type
ORDER BY reviewed_items DESC, work_type""",
         "Use for review SLA, turnaround, and cycle-time questions."),
        ("top_requesters_quarter", "Who submitted the most governance requests this quarter?", f"""SELECT created_by, COUNT(*) AS requests,
  SUM(CASE WHEN lower(COALESCE(status, '')) IN {_OPEN} THEN 1 ELSE 0 END) AS still_open
FROM {W}
WHERE created_at >= date_trunc('quarter', current_date())
GROUP BY created_by
ORDER BY requests DESC, created_by
LIMIT 25""",
         "Use for requester activity within a period."),
        ("reviewer_decisions", "Which reviewers approved or rejected the most requests?", f"""SELECT reviewed_by,
  COUNT(*) AS reviewed_items,
  SUM(CASE WHEN lower(status) IN ('approved', 'applied', 'resolved') THEN 1 ELSE 0 END) AS approved_items,
  SUM(CASE WHEN lower(status) = 'rejected' THEN 1 ELSE 0 END) AS rejected_items
FROM {W}
WHERE reviewed_by IS NOT NULL
GROUP BY reviewed_by
ORDER BY reviewed_items DESC, reviewed_by
LIMIT 25""",
         "Use for reviewer workload and decision questions."),
        ("rejected_requests", "Which requests were rejected and why?", f"""SELECT work_id, work_type, asset_fqn, title, created_by, reviewed_by, reviewed_at, review_note
FROM {W}
WHERE lower(status) = 'rejected'
ORDER BY reviewed_at DESC, work_id
LIMIT 25""",
         "Use for rejection reasons and declined change questions."),
        ("assets_most_open_work", "Which assets have the most open governance work?", f"""SELECT work.asset_fqn, assets.domain, assets.is_critical,
  COUNT(*) AS open_work_items,
  MIN(work.created_at) AS oldest_open_since
FROM {W} work
INNER JOIN {A} assets
  ON assets.asset_fqn = work.asset_fqn
WHERE lower(COALESCE(work.status, '')) IN {_OPEN}
GROUP BY work.asset_fqn, assets.domain, assets.is_critical
ORDER BY open_work_items DESC, oldest_open_since ASC, work.asset_fqn
LIMIT 25""",
         "Use for asset hotspots in the governance backlog."),
        ("critical_open_work", "What open governance work is on critical assets?", f"""SELECT work.work_id, work.work_type, work.status, work.asset_fqn, work.title, work.created_at,
  datediff(current_date(), work.created_at) AS age_days
FROM {W} work
INNER JOIN {A} assets
  ON assets.asset_fqn = work.asset_fqn
WHERE assets.is_critical
  AND lower(COALESCE(work.status, '')) IN {_OPEN}
ORDER BY work.created_at ASC, work.work_id
LIMIT 25""",
         "Use for prioritizing backlog on critical assets."),
        # Glossary
        ("glossary_customer_terms", "Which glossary terms are linked to customer assets?", f"""SELECT term_id, name, definition, review_status, linked_asset_count, linked_assets_sample
FROM {G}
WHERE lower(COALESCE(linked_assets_sample, '')) LIKE '%customer%'
   OR lower(COALESCE(domain, '')) LIKE '%customer%'
   OR lower(COALESCE(name, '')) LIKE '%customer%'
ORDER BY linked_asset_count DESC, name
LIMIT 25""",
         "Use for glossary questions scoped to a subject such as customer; replace the keyword for other subjects."),
        ("glossary_unlinked", "Which glossary terms are not linked to any asset?", f"""SELECT term_id, name, domain, status, owner_email, updated_at
FROM {G}
WHERE linked_asset_count = 0
ORDER BY domain, name
LIMIT 50""",
         "Use for orphaned or unused glossary term questions."),
        ("glossary_pending_review", "Which glossary terms are waiting for review?", f"""SELECT term_id, name, domain, status, owner_email, reviewers, updated_at
FROM {G}
WHERE lower(COALESCE(review_status, '')) IN ('', 'draft', 'new', 'pending', 'in_review', 'proposed')
ORDER BY updated_at ASC, name
LIMIT 50""",
         "Use for glossary review backlog questions."),
        ("glossary_by_domain", "How many glossary terms are there per domain and status?", f"""SELECT COALESCE(domain, 'Unassigned') AS domain, lower(COALESCE(status, '')) AS status,
  COUNT(*) AS terms,
  SUM(CASE WHEN linked_asset_count > 0 THEN 1 ELSE 0 END) AS linked_terms
FROM {G}
GROUP BY COALESCE(domain, 'Unassigned'), lower(COALESCE(status, ''))
ORDER BY terms DESC, domain, status""",
         "Use for glossary size and maturity by domain."),
        ("glossary_gaps", "Which glossary terms are missing a definition, owner, or reviewers?", f"""SELECT term_id, name, domain, status,
  NULLIF(trim(definition), '') IS NULL AS missing_definition,
  owner_email IS NULL AS missing_owner,
  reviewers IS NULL AS missing_reviewers
FROM {G}
WHERE NULLIF(trim(definition), '') IS NULL OR owner_email IS NULL OR reviewers IS NULL
ORDER BY domain, name
LIMIT 50""",
         "Use for glossary completeness questions."),
        # Data quality
        ("quality_critical_failures", "Show me data quality issues impacting critical assets.", f"""SELECT quality.asset_fqn, quality.column_name, quality.case_id, quality.outcome, quality.severity,
       quality.metric_value, quality.threshold_value, quality.detail, quality.executed_at
FROM {Q} quality
INNER JOIN {A} assets
  ON assets.asset_fqn = quality.asset_fqn
WHERE assets.is_critical = TRUE
  AND lower(COALESCE(quality.outcome, '')) IN {_FAILING}
ORDER BY quality.executed_at DESC, quality.asset_fqn
LIMIT 25""",
         "Use for quality-impact questions on critical assets. Do not UNION in a placeholder row; zero rows means no failing latest results on critical assets."),
        ("quality_failing_checks", "Which quality checks are currently failing?", f"""SELECT asset_fqn, column_name, case_id, outcome, severity, metric_value, threshold_value, detail, executed_at
FROM {Q}
WHERE lower(COALESCE(outcome, '')) IN {_FAILING}
ORDER BY CASE lower(COALESCE(severity, '')) WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END,
  executed_at DESC, asset_fqn
LIMIT 50""",
         "Use for current failing data quality checks across all assets."),
        ("quality_pass_rate_by_asset", "What is the quality pass rate by asset?", f"""SELECT asset_fqn,
  COUNT(*) AS evaluated_checks,
  SUM(CASE WHEN lower(outcome) = 'passed' THEN 1 ELSE 0 END) AS passed_checks,
  SUM(CASE WHEN lower(outcome) IN {_FAILING} THEN 1 ELSE 0 END) AS failing_checks,
  ROUND(100.0 * SUM(CASE WHEN lower(outcome) = 'passed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pass_rate_pct,
  MAX(executed_at) AS last_checked_at
FROM {Q}
WHERE lower(COALESCE(outcome, '')) <> 'skipped'
GROUP BY asset_fqn
ORDER BY pass_rate_pct ASC, failing_checks DESC, asset_fqn
LIMIT 25""",
         "Use for quality scorecards and pass-rate questions. Skipped checks are excluded."),
        ("quality_recent_failures", "Which quality checks failed in the last 7 days?", f"""SELECT asset_fqn, column_name, case_id, outcome, severity, detail, executed_at
FROM {Q}
WHERE lower(COALESCE(outcome, '')) IN {_FAILING}
  AND executed_at >= current_timestamp() - INTERVAL 7 DAYS
ORDER BY executed_at DESC, asset_fqn
LIMIT 50""",
         "Use for recent quality incidents."),
        ("quality_untested_critical", "Which critical assets have no data quality checks?", f"""SELECT assets.asset_fqn, assets.domain, assets.criticality, assets.business_owners
FROM {A} assets
LEFT ANTI JOIN {Q} quality
  ON quality.asset_fqn = assets.asset_fqn
WHERE assets.is_critical
ORDER BY assets.asset_fqn
LIMIT 50""",
         "Use for quality test coverage gaps on critical assets."),
        # Audit
        ("recent_changes", "What changed in governance metadata recently?", f"""SELECT audit_id, asset_fqn, action, status, actor_email, detail, created_at
FROM {U}
ORDER BY created_at DESC, audit_id DESC
LIMIT 25""",
         "Use for recent governance and metadata change questions."),
        ("top_actors_30d", "Who made the most metadata changes in the last 30 days?", f"""SELECT actor_email, COUNT(*) AS changes, COUNT(DISTINCT asset_fqn) AS assets_changed, MAX(created_at) AS last_change_at
FROM {U}
WHERE created_at >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY actor_email
ORDER BY changes DESC, actor_email
LIMIT 25""",
         "Use for change activity by person."),
        ("audit_actions_daily", "How many audit events happened per day by action over the last 30 days?", f"""SELECT to_date(created_at) AS event_date, action, COUNT(*) AS events
FROM {U}
WHERE created_at >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY to_date(created_at), action
ORDER BY event_date DESC, events DESC, action""",
         "Use for change trends over time."),
        ("audit_failed_actions", "Which governance changes failed or were not applied?", f"""SELECT audit_id, asset_fqn, action, status, source, actor_email, detail, created_at
FROM {U}
WHERE lower(COALESCE(status, '')) IN ('failed', 'error', 'errored', 'skipped', 'rejected')
ORDER BY created_at DESC, audit_id DESC
LIMIT 25""",
         "Use for failed writes and changes that did not take effect."),
        ("critical_asset_changes", "What changed on critical assets in the last 30 days?", f"""SELECT audit.audit_id, audit.asset_fqn, audit.action, audit.status, audit.actor_email, audit.created_at
FROM {U} audit
INNER JOIN {A} assets
  ON assets.asset_fqn = audit.asset_fqn
WHERE assets.is_critical
  AND audit.created_at >= current_timestamp() - INTERVAL 30 DAYS
ORDER BY audit.created_at DESC, audit.audit_id DESC
LIMIT 25""",
         "Use for change monitoring on critical assets."),
        # Lineage
        ("lineage_most_downstream", "Which assets have the most downstream dependents?", f"""SELECT source_asset_fqn AS asset_fqn,
  COUNT(DISTINCT target_asset_fqn) AS downstream_assets,
  MAX(event_time) AS last_seen_at
FROM {L}
WHERE source_asset_fqn IS NOT NULL
  AND target_asset_fqn IS NOT NULL
GROUP BY source_asset_fqn
ORDER BY downstream_assets DESC, asset_fqn
LIMIT 25""",
         "Use for blast-radius and most-depended-on asset questions."),
        ("lineage_most_upstream", "Which assets depend on the most upstream sources?", f"""SELECT target_asset_fqn AS asset_fqn,
  COUNT(DISTINCT source_asset_fqn) AS upstream_assets,
  MAX(event_time) AS last_seen_at
FROM {L}
WHERE source_asset_fqn IS NOT NULL
  AND target_asset_fqn IS NOT NULL
GROUP BY target_asset_fqn
ORDER BY upstream_assets DESC, asset_fqn
LIMIT 25""",
         "Use for complex or fan-in assets."),
        ("lineage_critical_uncertified_downstream", "Which critical assets feed uncertified downstream assets?", f"""SELECT DISTINCT lineage.source_asset_fqn, lineage.target_asset_fqn, downstream.certification AS downstream_certification
FROM {L} lineage
INNER JOIN {A} upstream
  ON upstream.asset_fqn = lineage.source_asset_fqn
INNER JOIN {A} downstream
  ON downstream.asset_fqn = lineage.target_asset_fqn
WHERE upstream.is_critical
  AND NOT downstream.is_certified
ORDER BY lineage.source_asset_fqn, lineage.target_asset_fqn
LIMIT 50""",
         "Use for certification propagation and downstream trust questions."),
        ("lineage_no_activity", "Which assets have no lineage activity in the last 90 days?", f"""SELECT assets.asset_fqn, assets.table_type, assets.last_altered
FROM {A} assets
WHERE NOT EXISTS (
  SELECT 1 FROM {L} lineage
  WHERE lineage.source_asset_fqn = assets.asset_fqn OR lineage.target_asset_fqn = assets.asset_fqn
)
ORDER BY assets.last_altered ASC, assets.asset_fqn
LIMIT 50""",
         "Use for unused or isolated asset questions. If the lineage view is empty, say lineage is unavailable instead of listing every asset."),
        ("lineage_daily_activity", "How many lineage events were observed per day in the last 30 days?", f"""SELECT to_date(event_time) AS event_date,
  COUNT(*) AS lineage_events,
  COUNT(DISTINCT source_asset_fqn) AS source_assets,
  COUNT(DISTINCT target_asset_fqn) AS target_assets
FROM {L}
WHERE event_time >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY to_date(event_time)
ORDER BY event_date DESC""",
         "Use for pipeline activity and lineage freshness questions."),
    ]
    return [
        {"key": key, "question": question, "sql": sql, "usage": usage}
        for key, question, sql, usage in entries
    ]


# Rephrasings that must resolve to the same SQL as an example. They exercise
# synonyms and phrasing variety in the benchmark without adding new examples.
_BENCHMARK_PARAPHRASES = (
    ("inventory_by_schema_type", "Give me a breakdown of tables and views per schema."),
    ("coverage_overall", "What percent of our assets are documented, owned, and classified?"),
    ("coverage_lowest", "Show the assets with the worst metadata completeness."),
    ("coverage_by_schema", "Which schemas are least documented?"),
    ("undocumented_assets", "List tables that are missing a description."),
    ("new_assets", "What new tables showed up this month?"),
    ("stale_assets", "Which tables look stale or unmaintained?"),
    ("assets_by_domain", "How many assets does each business domain have?"),
    ("sensitive_assets", "Where is our PII?"),
    ("sensitive_unowned", "Are there any PII or confidential tables without an owner?"),
    ("critical_uncertified", "List uncertified critical tables."),
    ("certification_rate_by_domain", "Which domains are furthest behind on certification?"),
    ("unowned_assets", "Show orphaned tables with no steward."),
    ("owner_portfolio", "How many assets does each owner steward?"),
    ("stewardship_attention", "Which tables need stewardship follow-up?"),
    ("domain_policy_risk", "Where are policy exceptions concentrated by domain?"),
    ("work_status_summary", "How big is the governance backlog by status?"),
    ("oldest_open_work", "Which governance tasks have been open the longest?"),
    ("review_turnaround", "How long do governance reviews take on average?"),
    ("reviewer_decisions", "Who is reviewing the most governance requests?"),
    ("rejected_requests", "Why were change requests rejected?"),
    ("glossary_unlinked", "Which business terms are unused?"),
    ("glossary_pending_review", "Which glossary terms still need approval?"),
    ("quality_failing_checks", "What data quality tests are failing right now?"),
    ("quality_pass_rate_by_asset", "Which tables have the worst data quality pass rate?"),
    ("quality_untested_critical", "Which critical tables have no quality tests?"),
    ("recent_changes", "Show the latest governance audit events."),
    ("top_actors_30d", "Who has been changing metadata the most this month?"),
    ("lineage_most_downstream", "Which tables would break the most things downstream if they changed?"),
    ("lineage_most_upstream", "Which assets have the most upstream inputs?"),
)


def _benchmark_only(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[tuple]:
    A = _fq(catalog, ai_schema, "axiom_ai_assets_current")
    W = _fq(catalog, ai_schema, "axiom_ai_governance_work_current")
    G = _fq(catalog, ai_schema, "axiom_ai_glossary_current")
    Q = _fq(catalog, ai_schema, "axiom_ai_quality_latest")
    U = _fq(catalog, ai_schema, "axiom_ai_audit_events")
    L = _fq(catalog, ai_schema, "axiom_ai_lineage_edges")
    return [
        ("How many tables versus views do we have?", f"""SELECT table_type, COUNT(*) AS asset_count
FROM {A}
GROUP BY table_type
ORDER BY asset_count DESC, table_type"""),
        ("What percentage of assets are certified?", f"""SELECT COUNT(*) AS total_assets,
  SUM(CASE WHEN is_certified THEN 1 ELSE 0 END) AS certified_assets,
  ROUND(100.0 * AVG(CASE WHEN is_certified THEN 1 ELSE 0 END), 1) AS pct_certified
FROM {A}"""),
        ("How many critical assets do we have?", f"""SELECT COUNT(*) AS critical_assets
FROM {A}
WHERE is_critical"""),
        ("List the 10 most recently changed assets.", f"""SELECT asset_fqn, table_type, last_altered
FROM {A}
ORDER BY last_altered DESC, asset_fqn
LIMIT 10"""),
        ("Which assets have no domain tag?", f"""SELECT asset_fqn, table_type, business_owners
FROM {A}
WHERE domain IS NULL
ORDER BY is_critical DESC, asset_fqn
LIMIT 50"""),
        ("How many assets are unclassified for sensitivity?", f"""SELECT COUNT(*) AS unclassified_assets
FROM {A}
WHERE sensitivity IS NULL"""),
        ("Which open requests are older than 14 days?", f"""SELECT work_id, work_type, status, asset_fqn, title, created_at,
  datediff(current_date(), created_at) AS age_days
FROM {W}
WHERE lower(COALESCE(status, '')) IN {_OPEN}
  AND created_at < current_timestamp() - INTERVAL 14 DAYS
ORDER BY created_at ASC, work_id
LIMIT 50"""),
        ("How many governance requests were closed in the last 30 days?", f"""SELECT lower(status) AS status, COUNT(*) AS closed_items
FROM {W}
WHERE lower(COALESCE(status, '')) IN {_CLOSED}
  AND reviewed_at >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY lower(status)
ORDER BY closed_items DESC, status"""),
        ("How many glossary terms are approved?", f"""SELECT COUNT(*) AS approved_terms
FROM {G}
WHERE lower(COALESCE(status, '')) IN ('approved', 'published', 'active')"""),
        ("Which glossary terms are linked to the most assets?", f"""SELECT term_id, name, domain, linked_asset_count
FROM {G}
WHERE linked_asset_count > 0
ORDER BY linked_asset_count DESC, name
LIMIT 25"""),
        ("How many quality checks passed, failed, or errored?", f"""SELECT lower(COALESCE(outcome, '')) AS outcome, COUNT(*) AS checks
FROM {Q}
GROUP BY lower(COALESCE(outcome, ''))
ORDER BY checks DESC, outcome"""),
        ("Which columns have failing quality checks?", f"""SELECT asset_fqn, column_name, COUNT(*) AS failing_checks, MAX(executed_at) AS last_failed_at
FROM {Q}
WHERE column_name IS NOT NULL
  AND lower(COALESCE(outcome, '')) IN {_FAILING}
GROUP BY asset_fqn, column_name
ORDER BY failing_checks DESC, asset_fqn, column_name
LIMIT 50"""),
        ("Which assets had the most audit events in the last 30 days?", f"""SELECT asset_fqn, COUNT(*) AS events, MAX(created_at) AS last_event_at
FROM {U}
WHERE created_at >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY asset_fqn
ORDER BY events DESC, asset_fqn
LIMIT 25"""),
        ("Which owner assignments changed recently?", f"""SELECT audit_id, asset_fqn, actor_email, status, detail, created_at
FROM {U}
WHERE lower(action) = 'owner-upserted'
ORDER BY created_at DESC, audit_id DESC
LIMIT 25"""),
        ("How many distinct lineage edges were observed in the last 90 days?", f"""SELECT COUNT(DISTINCT source_asset_fqn, target_asset_fqn) AS distinct_edges,
  COUNT(DISTINCT source_asset_fqn) AS source_assets,
  COUNT(DISTINCT target_asset_fqn) AS target_assets
FROM {L}
WHERE source_asset_fqn IS NOT NULL
  AND target_asset_fqn IS NOT NULL"""),
        ("Which unowned assets have downstream dependents?", f"""SELECT lineage.source_asset_fqn AS asset_fqn,
  COUNT(DISTINCT lineage.target_asset_fqn) AS downstream_assets
FROM {L} lineage
INNER JOIN {A} assets
  ON assets.asset_fqn = lineage.source_asset_fqn
WHERE NOT assets.has_owner
  AND lineage.target_asset_fqn IS NOT NULL
GROUP BY lineage.source_asset_fqn
ORDER BY downstream_assets DESC, asset_fqn
LIMIT 25"""),
    ]


_SAMPLE_QUESTION_KEYS = (
    "coverage_overall",
    "coverage_lowest",
    "critical_uncertified",
    "sensitive_unowned",
    "unowned_assets",
    "owner_portfolio",
    "domain_policy_risk",
    "oldest_open_work",
    "review_turnaround",
    "glossary_customer_terms",
    "glossary_pending_review",
    "quality_critical_failures",
    "quality_pass_rate_by_asset",
    "recent_changes",
    "lineage_most_downstream",
    "stale_assets",
)


def sample_questions() -> List[Dict[str, Any]]:
    by_key = {entry["key"]: entry["question"] for entry in _example_catalog(catalog="catalog")}
    questions = [by_key[key] for key in _SAMPLE_QUESTION_KEYS]
    return sorted(
        [{"id": _id("sample", question), "question": [question]} for question in questions],
        key=lambda item: item["id"],
    )


def example_question_sqls(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    return sorted(
        [
            {
                "id": _id("example", entry["question"]),
                "question": [entry["question"]],
                "sql": [entry["sql"]],
                "usage_guidance": [entry["usage"]],
            }
            for entry in _example_catalog(catalog=catalog, ai_schema=ai_schema)
        ],
        key=lambda item: item["id"],
    )


def join_specs(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    def ref(name: str, alias: str) -> Dict[str, str]:
        return {"identifier": _identifier(catalog, ai_schema, name), "alias": alias}

    one_to_many = "--rt=FROM_RELATIONSHIP_TYPE_ONE_TO_MANY--"
    joins = [
        (
            "assets_work",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_governance_work_current", "work"),
            ["`assets`.`asset_fqn` = `work`.`asset_fqn`", one_to_many],
            "Join assets to current governance work by asset_fqn.",
        ),
        (
            "assets_quality",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_quality_latest", "quality"),
            ["`assets`.`asset_fqn` = `quality`.`asset_fqn`", one_to_many],
            "Join assets to latest quality outcomes by asset_fqn.",
        ),
        (
            "assets_audit",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_audit_events", "audit"),
            ["`assets`.`asset_fqn` = `audit`.`asset_fqn`", one_to_many],
            "Join assets to audit events by asset_fqn.",
        ),
        (
            "assets_downstream_lineage",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_lineage_edges", "downstream"),
            ["`assets`.`asset_fqn` = `downstream`.`source_asset_fqn`", one_to_many],
            "Join an asset to the lineage events where it is the upstream source; target_asset_fqn is then a downstream dependent.",
        ),
        (
            "assets_upstream_lineage",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_lineage_edges", "upstream"),
            ["`assets`.`asset_fqn` = `upstream`.`target_asset_fqn`", one_to_many],
            "Join an asset to the lineage events where it is the downstream target; source_asset_fqn is then an upstream input.",
        ),
    ]
    return sorted(
        [
            {
                "id": _id("join", name),
                "left": left,
                "right": right,
                "sql": sql,
                "comment": [comment],
                "instruction": [comment],
            }
            for name, left, right, sql, comment in joins
        ],
        key=lambda item: item["id"],
    )


def benchmark_questions(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    examples = _example_catalog(catalog=catalog, ai_schema=ai_schema)
    sql_by_key = {entry["key"]: entry["sql"] for entry in examples}
    pairs = [(entry["question"], entry["sql"]) for entry in examples]
    pairs += [(question, sql_by_key[key]) for key, question in _BENCHMARK_PARAPHRASES]
    pairs += _benchmark_only(catalog=catalog, ai_schema=ai_schema)
    return sorted(
        [
            {
                "id": _id("benchmark", question),
                "question": [question],
                "answer": [{"format": "SQL", "content": [sql]}],
            }
            for question, sql in pairs
        ],
        key=lambda item: item["id"],
    )


def serialized_space_payload(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> Dict[str, Any]:
    return {
        "version": 2,
        "config": {
            "sample_questions": sample_questions(),
        },
        "data_sources": {
            "tables": table_configs(catalog=catalog, ai_schema=ai_schema),
        },
        "instructions": {
            "text_instructions": text_instructions(),
            "example_question_sqls": example_question_sqls(catalog=catalog, ai_schema=ai_schema),
            "sql_functions": [],
            "join_specs": join_specs(catalog=catalog, ai_schema=ai_schema),
            "sql_snippets": {"filters": [], "expressions": [], "measures": []},
        },
        "benchmarks": {
            "questions": benchmark_questions(catalog=catalog, ai_schema=ai_schema),
        },
    }


def serialized_space(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> str:
    return json.dumps(serialized_space_payload(catalog=catalog, ai_schema=ai_schema), sort_keys=True, indent=2)


_ASSET_TERMS = ["asset", "table", "view", "schema", "domain", "owner", "certified", "coverage", "description"]
_WORK_TERMS = ["work", "request", "task", "status", "pending", "open", "review", "backlog"]
_GLOSSARY_TERMS = ["glossary", "term", "definition", "linked"]
_QUALITY_TERMS = ["quality", "check", "test", "outcome", "pass", "fail"]
_AUDIT_TERMS = ["audit", "change", "changed", "event", "action", "actor"]
_LINEAGE_TERMS = ["lineage", "downstream", "upstream", "depend", "source", "target"]

_LIVE_SUITE = (
    ("Which domains have the highest risk of policy exceptions?", _ASSET_TERMS + _WORK_TERMS),
    ("Which critical assets are not certified?", _ASSET_TERMS),
    ("What changed in governance metadata recently?", _AUDIT_TERMS),
    ("Which assets are missing stewardship attention?", _ASSET_TERMS + _WORK_TERMS),
    ("Which assets have the lowest metadata coverage?", _ASSET_TERMS),
    ("Which glossary terms are linked to customer assets?", _GLOSSARY_TERMS),
    ("Show me data quality issues impacting critical assets.", _QUALITY_TERMS + _ASSET_TERMS),
    ("What is our overall metadata coverage?", _ASSET_TERMS),
    ("Which sensitive assets have no owner?", _ASSET_TERMS + ["sensitive", "pii", "confidential"]),
    ("Who owns the most assets?", _ASSET_TERMS),
    ("What is the certification rate by domain?", _ASSET_TERMS),
    ("Which tables look stale or unmaintained?", _ASSET_TERMS + ["stale", "altered", "days"]),
    ("What is the oldest open governance work?", _WORK_TERMS),
    ("How long do governance reviews take on average?", _WORK_TERMS + ["hours", "turnaround"]),
    ("Which requests were rejected and why?", _WORK_TERMS + ["rejected"]),
    ("Which glossary terms are not linked to any asset?", _GLOSSARY_TERMS),
    ("Which quality checks are currently failing?", _QUALITY_TERMS),
    ("Which critical assets have no data quality checks?", _QUALITY_TERMS + _ASSET_TERMS),
    ("Who made the most metadata changes in the last 30 days?", _AUDIT_TERMS),
    ("Which assets have the most downstream dependents?", _LINEAGE_TERMS + _ASSET_TERMS),
    ("Which critical assets feed uncertified downstream assets?", _LINEAGE_TERMS + _ASSET_TERMS),
    ("Where is our PII?", _ASSET_TERMS + ["sensitive", "pii", "classification"]),
)


def benchmark_suite() -> List[Dict[str, Any]]:
    return [
        {
            "id": _id("bench-suite", question),
            "question": question,
            "must_have_any": list(dict.fromkeys(terms)),
        }
        for question, terms in _LIVE_SUITE
    ]
