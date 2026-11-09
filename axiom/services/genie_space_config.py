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
WHERE (source_table_full_name IS NOT NULL OR target_table_full_name IS NOT NULL)
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


def table_configs(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    identifier = lambda name: _identifier(catalog, ai_schema, name)
    tables = [
        _table(
            identifier("axiom_ai_assets_current"),
            "Current Unity Catalog asset inventory enriched with ownership, domain, certification, criticality, and open governance work.",
            [
                _column("asset_fqn", "Fully qualified asset name in catalog.schema.table form.", ["asset", "table", "data set"]),
                _column("domain", "Business domain tag for the asset.", ["domain", "business area"]),
                _column("certification", "Certification or certified tag value.", ["certified", "certification"]),
                _column("criticality", "Criticality tag value such as Critical or High.", ["critical asset", "criticality"]),
                _column("data_product", "Data product tag value.", ["product", "data product"]),
                _column("business_owners", "Comma-separated business owner emails from Axiom owner assignments.", ["owner", "steward"]),
                _column("owner_count", "Number of assigned owners."),
                _column("open_work_count", "Number of pending governance requests tied to the asset."),
                _column("has_owner", "True when the asset has at least one assigned owner."),
                _column("is_certified", "True when certification tag indicates the asset is certified."),
                _column("is_critical", "True when criticality tag indicates critical or high."),
            ],
        ),
        _table(
            identifier("axiom_ai_governance_work_current"),
            "Current open and reviewed governance work across requests and workflow tasks.",
            [
                _column("work_id", "Governance work identifier.", ["request", "task"]),
                _column("status", "Current work status such as pending, approved, rejected, open, or resolved.", ["state"]),
                _column("asset_fqn", "Asset affected by the work item.", ["asset", "table"]),
                _column("title", "Human-readable requested governance change."),
                _column("created_by", "Requester or creator identifier."),
                _column("created_at", "Creation timestamp."),
                _column("reviewed_by", "Reviewer identifier when reviewed."),
                _column("reviewed_at", "Review timestamp when reviewed."),
            ],
        ),
        _table(
            identifier("axiom_ai_glossary_current"),
            "Current glossary term hierarchy, review state, reviewers, and linked assets.",
            [
                _column("term_id", "Stable glossary term identifier."),
                _column("name", "Glossary term name.", ["term", "business term"]),
                _column("definition", "Term definition."),
                _column("review_status", "Review state for the term."),
                _column("domain", "Business domain for the term."),
                _column("reviewers", "Reviewer emails."),
                _column("linked_asset_count", "Number of linked assets."),
                _column("linked_assets_sample", "Sample linked asset FQNs."),
            ],
        ),
        _table(
            identifier("axiom_ai_quality_latest"),
            "Latest quality test outcomes by asset, column, and case.",
            [
                _column("asset_fqn", "Asset tested by the quality result.", ["asset", "table"]),
                _column("column_name", "Column tested, when applicable.", ["column"]),
                _column("outcome", "Latest quality outcome.", ["quality issue", "test result"]),
                _column("severity", "Severity of the quality issue."),
                _column("metric_value", "Observed metric value."),
                _column("threshold_value", "Configured threshold value."),
                _column("detail", "Human-readable quality detail."),
                _column("executed_at", "Execution timestamp for the result."),
            ],
        ),
        _table(
            identifier("axiom_ai_audit_events"),
            "Axiom metadata audit events.",
            [
                _column("audit_id", "Audit event identifier."),
                _column("asset_fqn", "Asset affected by the audit event.", ["asset", "table"]),
                _column("action", "Audit action such as owner-upserted or metadata updated.", ["change", "event"]),
                _column("status", "Outcome status for the audit event."),
                _column("actor_email", "Actor who performed the action."),
                _column("detail", "Event detail text."),
                _column("created_at", "Event timestamp."),
            ],
        ),
        _table(
            identifier("axiom_ai_lineage_edges"),
            "Unity Catalog lineage edges when available to the workspace and user.",
            [
                _column("source_asset_fqn", "Source asset in a lineage edge.", ["upstream", "source"]),
                _column("target_asset_fqn", "Target asset in a lineage edge.", ["downstream", "target"]),
                _column("lineage_source", "Lineage source/provenance."),
                _column("event_time", "Lineage event timestamp."),
                _column("availability_state", "Whether lineage evidence is available."),
            ],
        ),
    ]
    return sorted(tables, key=lambda table: table["identifier"])


def sample_questions() -> List[Dict[str, Any]]:
    questions = [
        "Which domains have the highest risk of policy exceptions?",
        "Which critical assets are not certified?",
        "What changed in governance metadata recently?",
        "Which assets are missing stewardship attention?",
        "Which assets have the lowest metadata coverage?",
        "Which glossary terms are linked to customer assets?",
    ]
    return sorted(
        [{"id": _id("sample", question), "question": [question]} for question in questions],
        key=lambda item: item["id"],
    )


def text_instructions() -> List[Dict[str, Any]]:
    content = (
        "Answer only from the curated Axiom views in this room. "
        "Never invent workflow state, owners, glossary links, quality issues, lineage, or certification. "
        "Never synthesize fallback rows, sentinel assets, or placeholder identifiers such as unavailable, none, no_data, or n/a. "
        "Do not use UNION fallback SELECT statements to fabricate a no-results row. If a query returns zero rows, keep the result empty and explain that no governed evidence rows were observed. "
        "Use axiom_ai_assets_current as the default asset inventory and join to the work, glossary, quality, audit, or lineage views only when the question asks for that evidence. "
        "Default unanswered or unavailable evidence to an explicit unavailable statement, not a guess. "
        "For questions about risk or stewardship, prefer pending work, missing owner, missing certification, criticality, quality failures, and recent audit events as evidence. "
        "When returning rows, include asset_fqn or the relevant work_id/audit_id so users can verify the answer."
    )
    return [{"id": _id("instruction", "axiom"), "content": [content]}]


def example_question_sqls(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    assets = _fq(catalog, ai_schema, "axiom_ai_assets_current")
    work = _fq(catalog, ai_schema, "axiom_ai_governance_work_current")
    audit = _fq(catalog, ai_schema, "axiom_ai_audit_events")
    glossary = _fq(catalog, ai_schema, "axiom_ai_glossary_current")
    quality = _fq(catalog, ai_schema, "axiom_ai_quality_latest")
    examples = [
        (
            "Which domains have the highest risk of policy exceptions?",
            f"""SELECT
  COALESCE(assets.domain, 'Unassigned') AS domain,
  COUNT(DISTINCT assets.asset_fqn) AS governed_assets,
  SUM(CASE WHEN lower(COALESCE(work.status, '')) IN ('pending', 'open') THEN 1 ELSE 0 END) AS open_policy_work,
  SUM(CASE WHEN assets.is_critical AND NOT assets.is_certified THEN 1 ELSE 0 END) AS uncertified_critical_assets
FROM {assets} assets
LEFT JOIN {work} work
  ON work.asset_fqn = assets.asset_fqn
GROUP BY COALESCE(assets.domain, 'Unassigned')
ORDER BY open_policy_work DESC, uncertified_critical_assets DESC, governed_assets DESC
LIMIT 10""",
            "Use for domain-risk and policy-exception concentration questions.",
        ),
        (
            "Which critical assets are not certified?",
            f"""SELECT asset_fqn, domain, data_product, criticality, certification, business_owners
FROM {assets}
WHERE is_critical = TRUE
  AND is_certified = FALSE
ORDER BY owner_count ASC, open_work_count DESC, asset_fqn
LIMIT 25""",
            "Use for critical-asset certification gap questions.",
        ),
        (
            "Which assets are missing stewardship attention?",
            f"""SELECT asset_fqn, domain, data_product, owner_count, open_work_count, certification, criticality
FROM {assets}
WHERE owner_count = 0 OR open_work_count > 0
ORDER BY open_work_count DESC, owner_count ASC, is_critical DESC, asset_fqn
LIMIT 25""",
            "Use for ownership and stewardship attention questions.",
        ),
        (
            "What changed in governance metadata recently?",
            f"""SELECT audit_id, asset_fqn, action, status, actor_email, detail, created_at
FROM {audit}
ORDER BY created_at DESC, audit_id DESC
LIMIT 25""",
            "Use for recent governance and metadata change questions.",
        ),
        (
            "Which glossary terms are linked to customer assets?",
            f"""SELECT term_id, name, definition, review_status, linked_asset_count, linked_assets_sample
FROM {glossary}
WHERE lower(COALESCE(linked_assets_sample, '')) LIKE '%customer%'
   OR lower(COALESCE(domain, '')) LIKE '%customer%'
   OR lower(COALESCE(name, '')) LIKE '%customer%'
ORDER BY linked_asset_count DESC, name
LIMIT 25""",
            "Use for glossary questions scoped to customer assets or terms.",
        ),
        (
            "Show me data quality issues impacting critical assets.",
            f"""SELECT quality.asset_fqn, quality.column_name, quality.outcome, quality.severity,
       quality.metric_value, quality.threshold_value, quality.detail, quality.executed_at
FROM {quality} quality
INNER JOIN {assets} assets
  ON assets.asset_fqn = quality.asset_fqn
WHERE assets.is_critical = TRUE
  AND lower(COALESCE(quality.outcome, '')) NOT IN ('pass', 'passed', 'success', 'succeeded')
ORDER BY quality.executed_at DESC, quality.severity DESC, quality.asset_fqn
LIMIT 25""",
            "Use for quality-impact questions on critical assets. Do not UNION in a placeholder row; zero rows means no observed failed quality results for critical assets.",
        ),
    ]
    return sorted(
        [
        {
            "id": _id("example", question),
            "question": [question],
            "sql": [sql],
            "usage_guidance": [usage],
        }
        for question, sql, usage in examples
        ],
        key=lambda item: item["id"],
    )


def join_specs(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> List[Dict[str, Any]]:
    def ref(name: str, alias: str) -> Dict[str, str]:
        return {"identifier": _identifier(catalog, ai_schema, name), "alias": alias}

    joins = [
        (
            "assets_work",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_governance_work_current", "work"),
            ["`assets`.`asset_fqn` = `work`.`asset_fqn`", "--rt=FROM_RELATIONSHIP_TYPE_ONE_TO_MANY--"],
            "Join assets to current governance work by asset_fqn.",
        ),
        (
            "assets_quality",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_quality_latest", "quality"),
            ["`assets`.`asset_fqn` = `quality`.`asset_fqn`", "--rt=FROM_RELATIONSHIP_TYPE_ONE_TO_MANY--"],
            "Join assets to latest quality outcomes by asset_fqn.",
        ),
        (
            "assets_audit",
            ref("axiom_ai_assets_current", "assets"),
            ref("axiom_ai_audit_events", "audit"),
            ["`assets`.`asset_fqn` = `audit`.`asset_fqn`", "--rt=FROM_RELATIONSHIP_TYPE_ONE_TO_MANY--"],
            "Join assets to audit events by asset_fqn.",
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
    return sorted(
        [
        {
            "id": _id("benchmark", example["question"][0]),
            "question": example["question"],
            "answer": [{"format": "SQL", "content": example["sql"]}],
        }
        for example in example_question_sqls(catalog=catalog, ai_schema=ai_schema)
        ],
        key=lambda item: item["id"],
    )


def serialized_space(*, catalog: str, ai_schema: str = DEFAULT_AI_SCHEMA) -> str:
    payload = {
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
    return json.dumps(payload, sort_keys=True, indent=2)


def benchmark_suite() -> List[Dict[str, Any]]:
    return [
        {
            "id": _id("bench-suite", question),
            "question": question,
            "must_have_any": ["asset", "domain", "work", "owner", "audit", "quality", "certified"],
        }
        for question in [
            "Which domains have the highest risk of policy exceptions?",
            "Which critical assets are not certified?",
            "What changed in governance metadata recently?",
            "Which assets are missing stewardship attention?",
            "Which assets have the lowest metadata coverage?",
            "Which glossary terms are linked to customer assets?",
            "Show me data quality issues impacting critical assets.",
        ]
    ]
