#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RUN_ID_RE = re.compile(r"^ga-stress-\d{14}-[0-9a-f]{7,12}$")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ROW_MARKER = "governance_atlas.synthetic_stress"
APP_OWNED_MARKER = "governance_atlas_app_owned"
TEST_SCOPED_MARKER = "governance_atlas_test_scoped"
CLEANUP_SAFE_MARKER = "governance_atlas_cleanup_safe"
EXCLUDE_ORGANIC_MARKER = "governance_atlas_exclude_from_organic_evidence"
WORKFLOW_ENTITIES_TABLE = "workflow_entities"
WORKFLOW_AUDIT_TABLE = "workflow_audit_events"
VALIDATION_EVENTS_TABLE = "validation_events"
AUDIT_EVENTS_PER_WORKFLOW = 15


@dataclass(frozen=True)
class Scenario:
    id: str
    domain: str
    purpose: str


SCENARIOS: Sequence[Scenario] = (
    Scenario(
        id="discovery_asset_search",
        domain="Discovery",
        purpose="Create searchable synthetic assets and assert search/count/deleted/inaccessible disposition evidence.",
    ),
    Scenario(
        id="governance_workflow_review",
        domain="Governance",
        purpose="Create metadata change requests, review them, and assert approval and rejection outcomes with audit events.",
    ),
    Scenario(
        id="lakebase_shadow_write",
        domain="Lakebase",
        purpose="Create Delta-primary/Lakebase-shadow write records and assert direct mirror success counters.",
    ),
    Scenario(
        id="quality_run_health",
        domain="Quality",
        purpose="Persist quality-run health evidence and assert completed run and stale-boundary fields.",
    ),
    Scenario(
        id="lineage_column_trace",
        domain="Lineage",
        purpose="Create authoritative, degraded, and unavailable lineage cases with provenance and completeness flags.",
    ),
    Scenario(
        id="taxonomy_term_association",
        domain="Taxonomy",
        purpose="Create glossary hierarchy, reviewer assignment, asset association, review decision, and version evidence.",
    ),
    Scenario(
        id="genie_curated_question",
        domain="Genie",
        purpose="Persist Genie-grounded question evidence and assert no placeholder or sentinel fallback.",
    ),
    Scenario(
        id="cleanup_scoped_teardown",
        domain="cleanup",
        purpose="Inventory and remove only run-scoped synthetic validation artifacts.",
    ),
)


def _obj_get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _state_name(response: Any) -> str:
    status = _obj_get(response, "status")
    state = _obj_get(status, "state")
    value = getattr(state, "value", state)
    return str(value or "").upper()


def _error_message(response: Any) -> str:
    status = _obj_get(response, "status")
    error = _obj_get(status, "error")
    if not error:
        return ""
    as_dict = getattr(error, "as_dict", None)
    if callable(as_dict):
        try:
            return json.dumps(as_dict(), sort_keys=True)
        except Exception:
            pass
    return str(error)


def _statement_rows(response: Any) -> List[Dict[str, Any]]:
    result = _obj_get(response, "result") or {}
    data_array = _obj_get(result, "data_array") or []
    manifest = _obj_get(response, "manifest") or {}
    schema = _obj_get(manifest, "schema") or {}
    columns = _obj_get(schema, "columns") or []
    names = [str(_obj_get(column, "name") or "") for column in columns]
    if not names:
        return []
    rows: List[Dict[str, Any]] = []
    for raw_row in data_array:
        if isinstance(raw_row, (list, tuple)):
            rows.append({name: raw_row[index] if index < len(raw_row) else None for index, name in enumerate(names)})
    return rows


def _git_short_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip().lower()
        if re.fullmatch(r"[0-9a-f]{7,12}", value):
            return value
    except Exception:
        pass
    return "0000000"


def build_run_id(*, now: datetime | None = None, short_sha: str | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    sha = (short_sha or _git_short_sha()).lower()
    if not re.fullmatch(r"[0-9a-f]{7,12}", sha):
        raise ValueError(f"short sha must be 7-12 lowercase hex characters, got {sha!r}")
    run_id = f"ga-stress-{timestamp}-{sha}"
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"invalid generated run id: {run_id}")
    return run_id


def _quote_identifier(value: str) -> str:
    if not SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"unsafe UC identifier {value!r}; use letters, numbers, and underscores only")
    return f"`{value}`"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_bool(value: bool) -> str:
    return "true" if value else "false"


def _sql_json(value: Dict[str, Any]) -> str:
    return _sql_string(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _run_id_schema_suffix(run_id: str) -> str:
    match = RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise ValueError(f"invalid run id: {run_id!r}")
    _, _, timestamp, short_sha = run_id.split("-")
    return f"{timestamp}_{short_sha}"


def _run_slug(run_id: str) -> str:
    return run_id.replace("-", "_")


def schema_name_for_run(schema_prefix: str, run_id: str) -> str:
    if not SAFE_IDENTIFIER_RE.fullmatch(schema_prefix):
        raise ValueError(f"unsafe schema prefix {schema_prefix!r}")
    return f"{schema_prefix}_{_run_id_schema_suffix(run_id)}"


def assert_run_scoped_schema(schema_name: str, *, schema_prefix: str, run_id: str) -> None:
    expected = schema_name_for_run(schema_prefix, run_id)
    if schema_name != expected:
        raise ValueError(f"refusing cleanup for unscoped schema {schema_name!r}; expected {expected!r}")


def _fq_name(catalog: str, schema: str, table: str | None = None) -> str:
    parts = [_quote_identifier(catalog), _quote_identifier(schema)]
    if table is not None:
        parts.append(_quote_identifier(table))
    return ".".join(parts)


def synthetic_provenance(run_id: str) -> Dict[str, Any]:
    return {
        "runId": run_id,
        "synthetic": True,
        "appOwned": True,
        "testScoped": True,
        "cleanupSafe": True,
        "excludeFromOrganicEvidence": True,
        "rowMarker": ROW_MARKER,
        "appOwnedMarker": APP_OWNED_MARKER,
        "testScopedMarker": TEST_SCOPED_MARKER,
        "cleanupSafeMarker": CLEANUP_SAFE_MARKER,
        "excludeOrganicMarker": EXCLUDE_ORGANIC_MARKER,
    }


def create_schema_statement(*, catalog: str, schema: str, run_id: str) -> str:
    comment = (
        f"Governance Atlas synthetic stress validation; run_id={run_id}; "
        f"{APP_OWNED_MARKER}=true; {TEST_SCOPED_MARKER}=true; {CLEANUP_SAFE_MARKER}=true; "
        f"{EXCLUDE_ORGANIC_MARKER}=true"
    )
    return f"CREATE SCHEMA IF NOT EXISTS {_fq_name(catalog, schema)} COMMENT {_sql_string(comment)}"


def create_events_table_statement(*, catalog: str, schema: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_fq_name(catalog, schema, VALIDATION_EVENTS_TABLE)} (
  run_id STRING NOT NULL,
  scenario_id STRING NOT NULL,
  scenario_domain STRING NOT NULL,
  scenario_order INT NOT NULL,
  stress_row INT NOT NULL,
  marker STRING NOT NULL,
  app_owned BOOLEAN NOT NULL,
  test_scoped BOOLEAN NOT NULL,
  cleanup_safe BOOLEAN NOT NULL,
  exclude_from_organic_evidence BOOLEAN NOT NULL,
  payload_json STRING NOT NULL,
  created_at TIMESTAMP NOT NULL
)
USING DELTA
TBLPROPERTIES (
  'governance_atlas.validation_kind' = 'synthetic_stress',
  'governance_atlas.app_owned' = 'true',
  'governance_atlas.test_scoped' = 'true',
  'governance_atlas.cleanup_safe' = 'true',
  'governance_atlas.exclude_from_organic_evidence' = 'true'
)
""".strip()


def create_workflow_entities_table_statement(*, catalog: str, schema: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE)} (
  run_id STRING NOT NULL,
  workflow_id STRING NOT NULL,
  entity_id STRING NOT NULL,
  entity_kind STRING NOT NULL,
  workflow_domain STRING NOT NULL,
  asset_fqn STRING NOT NULL,
  synthetic BOOLEAN NOT NULL,
  app_owned BOOLEAN NOT NULL,
  test_scoped BOOLEAN NOT NULL,
  cleanup_safe BOOLEAN NOT NULL,
  exclude_from_organic_evidence BOOLEAN NOT NULL,
  actor STRING NOT NULL,
  reviewer STRING NOT NULL,
  state STRING NOT NULL,
  expected_state STRING NOT NULL,
  observed_state STRING NOT NULL,
  source_system STRING NOT NULL,
  provenance STRING NOT NULL,
  evidence_json STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
TBLPROPERTIES (
  'governance_atlas.validation_kind' = 'synthetic_workflow_stress',
  'governance_atlas.app_owned' = 'true',
  'governance_atlas.test_scoped' = 'true',
  'governance_atlas.cleanup_safe' = 'true',
  'governance_atlas.exclude_from_organic_evidence' = 'true'
)
""".strip()


def create_workflow_audit_table_statement(*, catalog: str, schema: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {_fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE)} (
  run_id STRING NOT NULL,
  audit_event_id STRING NOT NULL,
  workflow_id STRING NOT NULL,
  workflow_domain STRING NOT NULL,
  event_order INT NOT NULL,
  event_type STRING NOT NULL,
  actor STRING NOT NULL,
  target_id STRING NOT NULL,
  source_system STRING NOT NULL,
  request_id STRING NOT NULL,
  before_state STRING NOT NULL,
  after_state STRING NOT NULL,
  synthetic BOOLEAN NOT NULL,
  app_owned BOOLEAN NOT NULL,
  test_scoped BOOLEAN NOT NULL,
  cleanup_safe BOOLEAN NOT NULL,
  exclude_from_organic_evidence BOOLEAN NOT NULL,
  immutable_event_id STRING NOT NULL,
  payload_json STRING NOT NULL,
  created_at TIMESTAMP NOT NULL
)
USING DELTA
TBLPROPERTIES (
  'governance_atlas.validation_kind' = 'synthetic_workflow_audit',
  'governance_atlas.app_owned' = 'true',
  'governance_atlas.test_scoped' = 'true',
  'governance_atlas.cleanup_safe' = 'true',
  'governance_atlas.exclude_from_organic_evidence' = 'true'
)
""".strip()


def insert_event_statement(
    *,
    catalog: str,
    schema: str,
    run_id: str,
    scenario: Scenario,
    scenario_order: int,
    stress_row: int,
) -> str:
    payload = {
        **synthetic_provenance(run_id),
        "scenario": scenario.domain,
        "scenarioId": scenario.id,
        "purpose": scenario.purpose,
    }
    values = [
        _sql_string(run_id),
        _sql_string(scenario.id),
        _sql_string(scenario.domain),
        str(scenario_order),
        str(stress_row),
        _sql_string(ROW_MARKER),
        "true",
        "true",
        "true",
        "true",
        _sql_json(payload),
        "current_timestamp()",
    ]
    return f"INSERT INTO {_fq_name(catalog, schema, VALIDATION_EVENTS_TABLE)} VALUES ({', '.join(values)})"


def _entity_values(
    *,
    run_id: str,
    workflow_id: str,
    entity_id: str,
    entity_kind: str,
    workflow_domain: str,
    asset_fqn: str,
    actor: str,
    reviewer: str,
    state: str,
    expected_state: str,
    source_system: str,
    provenance: str,
    evidence: Dict[str, Any],
) -> str:
    values = [
        _sql_string(run_id),
        _sql_string(workflow_id),
        _sql_string(entity_id),
        _sql_string(entity_kind),
        _sql_string(workflow_domain),
        _sql_string(asset_fqn),
        "true",
        "true",
        "true",
        "true",
        "true",
        _sql_string(actor),
        _sql_string(reviewer),
        _sql_string(state),
        _sql_string(expected_state),
        _sql_string(state),
        _sql_string(source_system),
        _sql_string(provenance),
        _sql_json({**synthetic_provenance(run_id), **evidence}),
        "current_timestamp()",
        "current_timestamp()",
    ]
    return ", ".join(values)


def insert_entity_statement(*, catalog: str, schema: str, **kwargs: Any) -> str:
    columns = """
run_id, workflow_id, entity_id, entity_kind, workflow_domain, asset_fqn, synthetic,
app_owned, test_scoped, cleanup_safe, exclude_from_organic_evidence, actor, reviewer,
state, expected_state, observed_state, source_system, provenance, evidence_json,
created_at, updated_at
""".replace("\n", " ")
    return (
        f"INSERT INTO {_fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE)} ({columns}) "
        f"VALUES ({_entity_values(**kwargs)})"
    )


def update_entity_state_statement(
    *,
    catalog: str,
    schema: str,
    run_id: str,
    entity_id: str,
    state: str,
    evidence_patch: Dict[str, Any],
) -> str:
    patch_json = _sql_json({**synthetic_provenance(run_id), **evidence_patch})
    return f"""
UPDATE {_fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE)}
SET state = {_sql_string(state)},
    observed_state = {_sql_string(state)},
    evidence_json = {patch_json},
    updated_at = current_timestamp()
WHERE run_id = {_sql_string(run_id)}
  AND entity_id = {_sql_string(entity_id)}
""".strip()


def insert_audit_statement(
    *,
    catalog: str,
    schema: str,
    run_id: str,
    workflow_id: str,
    workflow_domain: str,
    event_order: int,
    event_type: str,
    actor: str,
    target_id: str,
    source_system: str,
    request_id: str,
    before_state: str,
    after_state: str,
    payload: Dict[str, Any],
) -> str:
    audit_event_id = f"{workflow_id}-{event_order:02d}-{event_type}"
    immutable_event_id = f"immutable-{audit_event_id}"
    values = [
        _sql_string(run_id),
        _sql_string(audit_event_id),
        _sql_string(workflow_id),
        _sql_string(workflow_domain),
        str(event_order),
        _sql_string(event_type),
        _sql_string(actor),
        _sql_string(target_id),
        _sql_string(source_system),
        _sql_string(request_id),
        _sql_string(before_state),
        _sql_string(after_state),
        "true",
        "true",
        "true",
        "true",
        "true",
        _sql_string(immutable_event_id),
        _sql_json({**synthetic_provenance(run_id), **payload}),
        "current_timestamp()",
    ]
    return f"INSERT INTO {_fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE)} VALUES ({', '.join(values)})"


def workflow_statements_for_row(*, catalog: str, schema: str, run_id: str, stress_row: int) -> List[str]:
    actor = "synthetic.data_owner@governance-atlas.local"
    reviewer = "synthetic.steward@governance-atlas.local"
    workflow_id = f"{run_id}-customer-workflow-{stress_row}"
    slug = _run_slug(run_id)
    asset_fqn = f"datapact.synthetic_stress.{slug}_customer_profile_{stress_row}"
    approval_request = f"{workflow_id}-approval-request"
    rejection_request = f"{workflow_id}-rejection-request"
    taxonomy_association = f"{workflow_id}-taxonomy-association"
    lineage_degraded = f"{workflow_id}-lineage-degraded"
    lineage_unavailable = f"{workflow_id}-lineage-unavailable"
    quality_run = f"{workflow_id}-quality-run"
    genie_question = f"{workflow_id}-genie-question"
    lakebase_mirror = f"{workflow_id}-lakebase-mirror"
    statements: List[str] = []

    statements.append(
        insert_entity_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            entity_id=f"{workflow_id}-asset",
            entity_kind="asset",
            workflow_domain="Discovery",
            asset_fqn=asset_fqn,
            actor=actor,
            reviewer=reviewer,
            state="created",
            expected_state="searchable",
            source_system="synthetic_uc_delta",
            provenance="run-scoped Delta validation table",
            evidence={
                "searchQuery": "customer pii payment",
                "resultCount": 1,
                "deletedDisposition": "excluded",
                "inaccessibleDisposition": "excluded",
                "truthfulCountAssertion": True,
            },
        )
    )
    statements.append(
        update_entity_state_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            entity_id=f"{workflow_id}-asset",
            state="searchable",
            evidence_patch={
                "searchQuery": "customer pii payment",
                "resultCount": 1,
                "deletedDisposition": "excluded",
                "inaccessibleDisposition": "excluded",
                "truthfulCountAssertion": True,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Discovery",
            event_order=1,
            event_type="asset_created",
            actor=actor,
            target_id=f"{workflow_id}-asset",
            source_system="synthetic_uc_delta",
            request_id=f"{workflow_id}-discovery",
            before_state="absent",
            after_state="created",
            payload={"assetFqn": asset_fqn},
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Discovery",
            event_order=2,
            event_type="asset_search_observed",
            actor=actor,
            target_id=f"{workflow_id}-asset",
            source_system="synthetic_search_contract",
            request_id=f"{workflow_id}-discovery",
            before_state="created",
            after_state="searchable",
            payload={"searchQuery": "customer pii payment", "resultCount": 1},
        )
    )

    for request_id, final_state, event_base, order_offset in (
        (approval_request, "approved", "request_approved", 10),
        (rejection_request, "rejected", "request_rejected", 20),
    ):
        statements.append(
            insert_entity_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                entity_id=request_id,
                entity_kind="governance_request",
                workflow_domain="Governance",
                asset_fqn=asset_fqn,
                actor=actor,
                reviewer=reviewer,
                state="submitted",
                expected_state=final_state,
                source_system="metadata_change_request",
                provenance="run-scoped workflow validation",
                evidence={
                    "requestId": request_id,
                    "threadId": f"{request_id}-thread",
                    "taskId": f"{request_id}-task",
                    "reviewer": reviewer,
                    "targetFinalState": final_state,
                },
            )
        )
        statements.append(
            insert_audit_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_domain="Governance",
                event_order=order_offset,
                event_type="request_submitted",
                actor=actor,
                target_id=request_id,
                source_system="metadata_change_request",
                request_id=request_id,
                before_state="absent",
                after_state="submitted",
                payload={"threadId": f"{request_id}-thread", "taskId": f"{request_id}-task"},
            )
        )
        statements.append(
            update_entity_state_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                entity_id=request_id,
                state="in_review",
                evidence_patch={"requestId": request_id, "reviewer": reviewer, "threadId": f"{request_id}-thread"},
            )
        )
        statements.append(
            insert_audit_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_domain="Governance",
                event_order=order_offset + 1,
                event_type="request_reviewed",
                actor=reviewer,
                target_id=request_id,
                source_system="metadata_change_request",
                request_id=request_id,
                before_state="submitted",
                after_state="in_review",
                payload={"reviewer": reviewer},
            )
        )
        statements.append(
            update_entity_state_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                entity_id=request_id,
                state=final_state,
                evidence_patch={"requestId": request_id, "reviewer": reviewer, "decision": final_state},
            )
        )
        statements.append(
            insert_audit_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_domain="Governance",
                event_order=order_offset + 2,
                event_type=event_base,
                actor=reviewer,
                target_id=request_id,
                source_system="metadata_change_request",
                request_id=request_id,
                before_state="in_review",
                after_state=final_state,
                payload={"decision": final_state, "reviewer": reviewer},
            )
        )

    statements.append(
        insert_entity_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            entity_id=taxonomy_association,
            entity_kind="taxonomy_association",
            workflow_domain="Taxonomy",
            asset_fqn=asset_fqn,
            actor=actor,
            reviewer=reviewer,
            state="pending_review",
            expected_state="approved",
            source_system="glossary_association_workflow",
            provenance="run-scoped workflow validation",
            evidence={
                "termHierarchyId": f"{workflow_id}-term-customer-pii",
                "parentTermId": f"{workflow_id}-term-sensitive-data",
                "reviewerAssignmentId": f"{taxonomy_association}-reviewer",
                "associationTarget": asset_fqn,
                "version": 1,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Taxonomy",
            event_order=30,
            event_type="taxonomy_reviewer_assigned",
            actor=actor,
            target_id=taxonomy_association,
            source_system="glossary_association_workflow",
            request_id=f"{taxonomy_association}-review",
            before_state="draft",
            after_state="pending_review",
            payload={"reviewer": reviewer},
        )
    )
    statements.append(
        update_entity_state_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            entity_id=taxonomy_association,
            state="approved",
            evidence_patch={
                "termHierarchyId": f"{workflow_id}-term-customer-pii",
                "associationTarget": asset_fqn,
                "reviewDecision": "approved",
                "version": 2,
                "historyEvidence": True,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Taxonomy",
            event_order=31,
            event_type="taxonomy_association_approved",
            actor=reviewer,
            target_id=taxonomy_association,
            source_system="glossary_association_workflow",
            request_id=f"{taxonomy_association}-review",
            before_state="pending_review",
            after_state="approved",
            payload={"reviewDecision": "approved", "version": 2},
        )
    )

    for entity_id, state, payload, event_order, event_type in (
        (
            lineage_degraded,
            "degraded",
            {
                "provenance": "system.lineage with truncated preview",
                "truncated": True,
                "columnLineageComplete": False,
                "unavailableReason": "",
            },
            40,
            "lineage_degraded_asserted",
        ),
        (
            lineage_unavailable,
            "unavailable",
            {
                "provenance": "system.lineage unavailable",
                "truncated": False,
                "columnLineageComplete": False,
                "unavailableReason": "no observed lineage for actor-visible catalogs",
            },
            41,
            "lineage_unavailable_asserted",
        ),
    ):
        statements.append(
            insert_entity_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                entity_id=entity_id,
                entity_kind="lineage_case",
                workflow_domain="Lineage",
                asset_fqn=asset_fqn,
                actor=actor,
                reviewer=reviewer,
                state=state,
                expected_state=state,
                source_system="system.lineage",
                provenance=str(payload["provenance"]),
                evidence=payload,
            )
        )
        statements.append(
            insert_audit_statement(
                catalog=catalog,
                schema=schema,
                run_id=run_id,
                workflow_id=workflow_id,
                workflow_domain="Lineage",
                event_order=event_order,
                event_type=event_type,
                actor=actor,
                target_id=entity_id,
                source_system="system.lineage",
                request_id=f"{workflow_id}-lineage",
                before_state="unknown",
                after_state=state,
                payload=payload,
            )
        )

    statements.append(
        insert_entity_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            entity_id=quality_run,
            entity_kind="quality_run",
            workflow_domain="Quality",
            asset_fqn=asset_fqn,
            actor=actor,
            reviewer=reviewer,
            state="queued",
            expected_state="completed",
            source_system="quality_run_registry",
            provenance="run-scoped quality result",
            evidence={"definitionId": f"{quality_run}-definition", "status": "queued", "staleBoundaryHours": 24},
        )
    )
    statements.append(
        update_entity_state_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            entity_id=quality_run,
            state="completed",
            evidence_patch={
                "definitionId": f"{quality_run}-definition",
                "qualityRunId": quality_run,
                "status": "passed",
                "persistedResultRows": 3,
                "staleBoundaryHours": 24,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Quality",
            event_order=50,
            event_type="quality_run_completed",
            actor=actor,
            target_id=quality_run,
            source_system="quality_run_registry",
            request_id=f"{workflow_id}-quality",
            before_state="queued",
            after_state="completed",
            payload={"status": "passed", "persistedResultRows": 3},
        )
    )

    statements.append(
        insert_entity_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            entity_id=genie_question,
            entity_kind="genie_question",
            workflow_domain="Genie",
            asset_fqn=asset_fqn,
            actor=actor,
            reviewer=reviewer,
            state="submitted",
            expected_state="answered",
            source_system="atlas_genie_space",
            provenance="configured Governance Atlas Genie space",
            evidence={
                "questionText": "Which customer assets have open governance requests?",
                "provider": "genie",
                "confidence": "genie-grounded",
                "evidenceCount": 1,
                "sentinelFallback": False,
            },
        )
    )
    statements.append(
        update_entity_state_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            entity_id=genie_question,
            state="answered",
            evidence_patch={
                "questionText": "Which customer assets have open governance requests?",
                "provider": "genie",
                "confidence": "genie-grounded",
                "evidenceCount": 1,
                "sentinelFallback": False,
                "placeholderAnswer": False,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Genie",
            event_order=60,
            event_type="genie_answer_grounded",
            actor=actor,
            target_id=genie_question,
            source_system="atlas_genie_space",
            request_id=f"{workflow_id}-genie",
            before_state="submitted",
            after_state="answered",
            payload={"provider": "genie", "evidenceCount": 1, "sentinelFallback": False},
        )
    )

    statements.append(
        insert_entity_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            entity_id=lakebase_mirror,
            entity_kind="lakebase_mirror",
            workflow_domain="Lakebase",
            asset_fqn=asset_fqn,
            actor=actor,
            reviewer=reviewer,
            state="attempted",
            expected_state="succeeded",
            source_system="delta_primary_lakebase_shadow",
            provenance="run-scoped mirror assertion",
            evidence={"deltaWriteId": f"{workflow_id}-delta-write", "mirrorKey": lakebase_mirror, "attempted": 1},
        )
    )
    statements.append(
        update_entity_state_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            entity_id=lakebase_mirror,
            state="succeeded",
            evidence_patch={
                "deltaWriteId": f"{workflow_id}-delta-write",
                "mirrorKey": lakebase_mirror,
                "attempted": 1,
                "succeeded": 1,
                "failed": 0,
                "directMirrorReadback": True,
            },
        )
    )
    statements.append(
        insert_audit_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            workflow_id=workflow_id,
            workflow_domain="Lakebase",
            event_order=70,
            event_type="lakebase_mirror_succeeded",
            actor=actor,
            target_id=lakebase_mirror,
            source_system="delta_primary_lakebase_shadow",
            request_id=f"{workflow_id}-lakebase",
            before_state="attempted",
            after_state="succeeded",
            payload={"attempted": 1, "succeeded": 1, "failed": 0, "directMirrorReadback": True},
        )
    )
    return statements


def marker_verify_statement(*, catalog: str, schema: str, run_id: str) -> str:
    return f"""
SELECT
  scenario_domain,
  COUNT(*) AS event_count,
  MIN(CASE WHEN app_owned THEN 1 ELSE 0 END) AS all_app_owned,
  MIN(CASE WHEN test_scoped THEN 1 ELSE 0 END) AS all_test_scoped,
  MIN(CASE WHEN cleanup_safe THEN 1 ELSE 0 END) AS all_cleanup_safe,
  MIN(CASE WHEN exclude_from_organic_evidence THEN 1 ELSE 0 END) AS all_excluded_from_organic_evidence
FROM {_fq_name(catalog, schema, VALIDATION_EVENTS_TABLE)}
WHERE run_id = {_sql_string(run_id)}
  AND marker = {_sql_string(ROW_MARKER)}
GROUP BY scenario_domain
ORDER BY scenario_domain
""".strip()


def workflow_verify_statement(*, catalog: str, schema: str, run_id: str) -> str:
    entities = _fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE)
    audit = _fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE)
    validation = _fq_name(catalog, schema, VALIDATION_EVENTS_TABLE)
    run_sql = _sql_string(run_id)
    return f"""
SELECT *
FROM (
  SELECT
    COUNT(DISTINCT CASE WHEN entity_kind = 'asset' AND state = 'searchable' THEN entity_id END) AS discovery_assets,
    COUNT(DISTINCT CASE WHEN entity_kind = 'governance_request' AND state = 'approved' THEN entity_id END) AS governance_approved_requests,
    COUNT(DISTINCT CASE WHEN entity_kind = 'governance_request' AND state = 'rejected' THEN entity_id END) AS governance_rejected_requests,
    COUNT(DISTINCT CASE WHEN entity_kind = 'taxonomy_association' AND state = 'approved' THEN entity_id END) AS taxonomy_approved_associations,
    COUNT(DISTINCT CASE WHEN entity_kind = 'lineage_case' AND state = 'degraded' THEN entity_id END) AS degraded_lineage_cases,
    COUNT(DISTINCT CASE WHEN entity_kind = 'lineage_case' AND state = 'unavailable' THEN entity_id END) AS unavailable_lineage_cases,
    COUNT(DISTINCT CASE WHEN entity_kind = 'quality_run' AND state = 'completed' THEN entity_id END) AS quality_completed_runs,
    COUNT(DISTINCT CASE WHEN entity_kind = 'genie_question' AND state = 'answered' THEN entity_id END) AS genie_grounded_answers,
    SUM(CASE WHEN entity_kind = 'genie_question' AND get_json_object(evidence_json, '$.sentinelFallback') = 'true' THEN 1 ELSE 0 END) AS genie_sentinel_fallbacks,
    COUNT(DISTINCT CASE WHEN entity_kind = 'lakebase_mirror' AND state = 'succeeded' THEN entity_id END) AS lakebase_mirror_success_records,
    SUM(CASE WHEN entity_kind = 'lakebase_mirror' THEN CAST(COALESCE(get_json_object(evidence_json, '$.succeeded'), '0') AS INT) ELSE 0 END) AS lakebase_succeeded_writes,
    SUM(CASE WHEN entity_kind = 'lakebase_mirror' THEN CAST(COALESCE(get_json_object(evidence_json, '$.failed'), '0') AS INT) ELSE 0 END) AS lakebase_failed_writes,
    MIN(CASE WHEN synthetic AND app_owned AND test_scoped AND cleanup_safe AND exclude_from_organic_evidence THEN 1 ELSE 0 END) AS all_entity_provenance,
    SUM(CASE WHEN exclude_from_organic_evidence THEN 0 ELSE 1 END) AS organic_evidence_leaks
  FROM {entities}
  WHERE run_id = {run_sql}
) entity_metrics
CROSS JOIN (
  SELECT
    COUNT(*) AS audit_event_count,
    COUNT(DISTINCT immutable_event_id) AS distinct_audit_event_ids,
    COUNT(CASE WHEN event_type = 'request_approved' THEN 1 END) AS audit_approved_events,
    COUNT(CASE WHEN event_type = 'request_rejected' THEN 1 END) AS audit_rejected_events,
    MIN(CASE WHEN synthetic AND app_owned AND test_scoped AND cleanup_safe AND exclude_from_organic_evidence THEN 1 ELSE 0 END) AS all_audit_provenance
  FROM {audit}
  WHERE run_id = {run_sql}
) audit_metrics
CROSS JOIN (
  SELECT COUNT(*) AS marker_event_count
  FROM {validation}
  WHERE run_id = {run_sql}
    AND marker = {_sql_string(ROW_MARKER)}
) marker_metrics
""".strip()


def workflow_steps_statement(*, catalog: str, schema: str, run_id: str) -> str:
    return f"""
SELECT
  workflow_domain AS workflow,
  event_type AS operation,
  target_id,
  actor,
  after_state AS observed_state,
  source_system,
  request_id,
  immutable_event_id,
  payload_json
FROM {_fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE)}
WHERE run_id = {_sql_string(run_id)}
ORDER BY workflow_id, event_order, event_type
""".strip()


def pre_cleanup_inventory_statement(*, catalog: str, schema: str, run_id: str) -> str:
    return f"""
SELECT 'schema' AS resource_kind, {_sql_string(_fq_name(catalog, schema))} AS resource_id, 1 AS observed_count
UNION ALL
SELECT {_sql_string(VALIDATION_EVENTS_TABLE)} AS resource_kind, {_sql_string(_fq_name(catalog, schema, VALIDATION_EVENTS_TABLE))} AS resource_id, COUNT(*) AS observed_count
FROM {_fq_name(catalog, schema, VALIDATION_EVENTS_TABLE)}
WHERE run_id = {_sql_string(run_id)}
UNION ALL
SELECT {_sql_string(WORKFLOW_ENTITIES_TABLE)} AS resource_kind, {_sql_string(_fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE))} AS resource_id, COUNT(*) AS observed_count
FROM {_fq_name(catalog, schema, WORKFLOW_ENTITIES_TABLE)}
WHERE run_id = {_sql_string(run_id)}
UNION ALL
SELECT {_sql_string(WORKFLOW_AUDIT_TABLE)} AS resource_kind, {_sql_string(_fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE))} AS resource_id, COUNT(*) AS observed_count
FROM {_fq_name(catalog, schema, WORKFLOW_AUDIT_TABLE)}
WHERE run_id = {_sql_string(run_id)}
""".strip()


def cleanup_statement(*, catalog: str, schema: str, schema_prefix: str, run_id: str) -> str:
    assert_run_scoped_schema(schema, schema_prefix=schema_prefix, run_id=run_id)
    return f"DROP SCHEMA IF EXISTS {_fq_name(catalog, schema)} CASCADE"


def cleanup_verification_statement(*, catalog: str, schema: str) -> str:
    return f"SHOW SCHEMAS IN {_quote_identifier(catalog)} LIKE {_sql_string(schema)}"


def build_plan(
    *,
    catalog: str,
    schema_prefix: str,
    run_id: str,
    rows_per_scenario: int,
    cleanup: bool,
) -> Dict[str, Any]:
    if rows_per_scenario < 1:
        raise ValueError("rows_per_scenario must be at least 1")
    schema = schema_name_for_run(schema_prefix, run_id)
    setup_statements = [
        create_schema_statement(catalog=catalog, schema=schema, run_id=run_id),
        create_events_table_statement(catalog=catalog, schema=schema),
        create_workflow_entities_table_statement(catalog=catalog, schema=schema),
        create_workflow_audit_table_statement(catalog=catalog, schema=schema),
    ]
    insert_statements = [
        insert_event_statement(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            scenario=scenario,
            scenario_order=scenario_index,
            stress_row=stress_row,
        )
        for scenario_index, scenario in enumerate(SCENARIOS, start=1)
        for stress_row in range(1, rows_per_scenario + 1)
    ]
    workflow_statements = [
        statement
        for stress_row in range(1, rows_per_scenario + 1)
        for statement in workflow_statements_for_row(
            catalog=catalog,
            schema=schema,
            run_id=run_id,
            stress_row=stress_row,
        )
    ]
    validation_statements = [
        marker_verify_statement(catalog=catalog, schema=schema, run_id=run_id),
        workflow_verify_statement(catalog=catalog, schema=schema, run_id=run_id),
        workflow_steps_statement(catalog=catalog, schema=schema, run_id=run_id),
    ]
    inventory_statements = [pre_cleanup_inventory_statement(catalog=catalog, schema=schema, run_id=run_id)]
    cleanup_statements = (
        [cleanup_statement(catalog=catalog, schema=schema, schema_prefix=schema_prefix, run_id=run_id)]
        if cleanup
        else []
    )
    cleanup_verification_statements = (
        [cleanup_verification_statement(catalog=catalog, schema=schema)] if cleanup else []
    )
    return {
        "runId": run_id,
        "catalog": catalog,
        "schema": schema,
        "schemaPrefix": schema_prefix,
        "tables": [VALIDATION_EVENTS_TABLE, WORKFLOW_ENTITIES_TABLE, WORKFLOW_AUDIT_TABLE],
        "rowMarker": ROW_MARKER,
        "appOwnedMarker": APP_OWNED_MARKER,
        "testScopedMarker": TEST_SCOPED_MARKER,
        "cleanupSafeMarker": CLEANUP_SAFE_MARKER,
        "excludeOrganicMarker": EXCLUDE_ORGANIC_MARKER,
        "rowsPerScenario": rows_per_scenario,
        "expectedRowCount": rows_per_scenario * len(SCENARIOS),
        "expectedWorkflowCount": rows_per_scenario,
        "expectedAuditEventCount": rows_per_scenario * AUDIT_EVENTS_PER_WORKFLOW,
        "scenarios": [asdict(scenario) for scenario in SCENARIOS],
        "setupStatements": setup_statements,
        "insertStatements": insert_statements,
        "workflowStatements": workflow_statements,
        "validationStatements": validation_statements,
        "inventoryStatements": inventory_statements,
        "cleanupStatements": cleanup_statements,
        "cleanupVerificationStatements": cleanup_verification_statements,
        "statements": (
            setup_statements
            + insert_statements
            + workflow_statements
            + validation_statements
            + inventory_statements
            + cleanup_statements
            + cleanup_verification_statements
        ),
    }


def validate_runtime_safety(args: argparse.Namespace) -> None:
    if not args.live:
        return
    if args.profile != "DEFAULT":
        raise ValueError("live Databricks mutations require explicit --profile DEFAULT")
    if not args.warehouse_id:
        raise ValueError("live Databricks mutations require --warehouse-id")


def execute_sql(w: Any, *, warehouse_id: str, statement: str, timeout_seconds: int = 180) -> Dict[str, Any]:
    response = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    statement_id = _obj_get(response, "statement_id")
    deadline = time.time() + timeout_seconds
    while _state_name(response) in {"PENDING", "RUNNING"} and time.time() < deadline:
        time.sleep(2)
        response = w.statement_execution.get_statement(statement_id)
    state = _state_name(response)
    if state != "SUCCEEDED":
        raise RuntimeError(f"SQL statement failed with state={state}: {_error_message(response)}")
    return {"statementId": statement_id, "state": state, "rows": _statement_rows(response)}


def _execute_statements(w: Any, *, warehouse_id: str, statements: Iterable[str]) -> List[Dict[str, Any]]:
    results = []
    for statement in statements:
        result = execute_sql(w, warehouse_id=warehouse_id, statement=statement)
        results.append({**result, "statement": statement})
    return results


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _evaluate_markers(plan: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    expected_domains = {scenario["domain"] for scenario in plan["scenarios"]}
    observed_domains = {str(row.get("scenario_domain") or "") for row in rows}
    observed_count = 0
    marker_failures = []
    for row in rows:
        observed_count += _to_int(row.get("event_count"))
        for field in ("all_app_owned", "all_test_scoped", "all_cleanup_safe", "all_excluded_from_organic_evidence"):
            if str(row.get(field)).lower() not in {"true", "1"}:
                marker_failures.append(f"{field}:{row.get('scenario_domain')}")
    failures = []
    if observed_domains != expected_domains:
        failures.append("scenario_domain_mismatch")
    if observed_count != int(plan["expectedRowCount"]):
        failures.append("row_count_mismatch")
    failures.extend(marker_failures)
    return {
        "passed": not failures,
        "failures": failures,
        "expectedDomains": sorted(expected_domains),
        "observedDomains": sorted(observed_domains),
        "expectedRowCount": plan["expectedRowCount"],
        "observedRowCount": observed_count,
    }


def _evaluate_workflows(plan: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    row = rows[0] if rows else {}
    expected = int(plan["expectedWorkflowCount"])
    expected_audit_events = int(plan["expectedAuditEventCount"])
    metrics = {
        "discoveryAssets": _to_int(row.get("discovery_assets")),
        "governanceApprovedRequests": _to_int(row.get("governance_approved_requests")),
        "governanceRejectedRequests": _to_int(row.get("governance_rejected_requests")),
        "taxonomyApprovedAssociations": _to_int(row.get("taxonomy_approved_associations")),
        "degradedLineageCases": _to_int(row.get("degraded_lineage_cases")),
        "unavailableLineageCases": _to_int(row.get("unavailable_lineage_cases")),
        "qualityCompletedRuns": _to_int(row.get("quality_completed_runs")),
        "genieGroundedAnswers": _to_int(row.get("genie_grounded_answers")),
        "genieSentinelFallbacks": _to_int(row.get("genie_sentinel_fallbacks")),
        "lakebaseMirrorSuccessRecords": _to_int(row.get("lakebase_mirror_success_records")),
        "lakebaseSucceededWrites": _to_int(row.get("lakebase_succeeded_writes")),
        "lakebaseFailedWrites": _to_int(row.get("lakebase_failed_writes")),
        "auditEventCount": _to_int(row.get("audit_event_count")),
        "distinctAuditEventIds": _to_int(row.get("distinct_audit_event_ids")),
        "auditApprovedEvents": _to_int(row.get("audit_approved_events")),
        "auditRejectedEvents": _to_int(row.get("audit_rejected_events")),
        "markerEventCount": _to_int(row.get("marker_event_count")),
        "allEntityProvenance": _to_int(row.get("all_entity_provenance")),
        "allAuditProvenance": _to_int(row.get("all_audit_provenance")),
        "organicEvidenceLeaks": _to_int(row.get("organic_evidence_leaks")),
    }
    equal_expected = [
        "discoveryAssets",
        "governanceApprovedRequests",
        "governanceRejectedRequests",
        "taxonomyApprovedAssociations",
        "degradedLineageCases",
        "unavailableLineageCases",
        "qualityCompletedRuns",
        "genieGroundedAnswers",
        "lakebaseMirrorSuccessRecords",
        "lakebaseSucceededWrites",
        "auditApprovedEvents",
        "auditRejectedEvents",
    ]
    failures = [f"{key}_mismatch" for key in equal_expected if metrics[key] != expected]
    if metrics["genieSentinelFallbacks"] != 0:
        failures.append("genie_sentinel_fallback_detected")
    if metrics["lakebaseFailedWrites"] != 0:
        failures.append("lakebase_failed_writes_detected")
    if metrics["auditEventCount"] != expected_audit_events:
        failures.append("audit_event_count_mismatch")
    if metrics["distinctAuditEventIds"] != metrics["auditEventCount"]:
        failures.append("audit_event_id_not_unique")
    if metrics["markerEventCount"] != int(plan["expectedRowCount"]):
        failures.append("marker_event_count_mismatch")
    if metrics["allEntityProvenance"] != 1 or metrics["allAuditProvenance"] != 1:
        failures.append("synthetic_provenance_missing")
    if metrics["organicEvidenceLeaks"] != 0:
        failures.append("organic_evidence_leak")
    return {
        "passed": not failures,
        "failures": failures,
        "expectedWorkflowCount": expected,
        "expectedAuditEventCount": expected_audit_events,
        "metrics": metrics,
    }


def _steps_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps = []
    for row in rows:
        observed_state = str(row.get("observed_state") or "")
        steps.append(
            {
                "workflow": str(row.get("workflow") or ""),
                "operation": str(row.get("operation") or ""),
                "targetId": str(row.get("target_id") or ""),
                "actor": str(row.get("actor") or ""),
                "expectedState": observed_state,
                "observedState": observed_state,
                "sourceSystem": str(row.get("source_system") or ""),
                "apiOrSqlPath": "databricks.statement_execution",
                "evidenceQueryOrEndpoint": WORKFLOW_AUDIT_TABLE,
                "requestId": str(row.get("request_id") or ""),
                "immutableEventId": str(row.get("immutable_event_id") or ""),
                "passed": bool(observed_state),
            }
        )
    return steps


def _evaluate_cleanup(rows: List[Dict[str, Any]], *, cleanup_expected: bool) -> Dict[str, Any]:
    if not cleanup_expected:
        return {"passed": True, "cleanupExpected": False, "postCleanupSchemaRows": []}
    return {
        "passed": not rows,
        "cleanupExpected": True,
        "postCleanupSchemaRows": rows,
        "leftoverCount": len(rows),
    }


def run_validation(args: argparse.Namespace) -> Dict[str, Any]:
    validate_runtime_safety(args)
    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or build_run_id()
    plan = build_plan(
        catalog=args.catalog,
        schema_prefix=args.schema_prefix,
        run_id=run_id,
        rows_per_scenario=args.rows_per_scenario,
        cleanup=not args.keep_resources,
    )
    payload: Dict[str, Any] = {
        "generatedAt": started_at.isoformat().replace("+00:00", "Z"),
        "startedAt": started_at.isoformat().replace("+00:00", "Z"),
        "completedAt": "",
        "mode": "live" if args.live else "dry-run",
        "profile": args.profile or "DEFAULT",
        "warehouseId": args.warehouse_id or "",
        "catalog": args.catalog,
        "schema": plan["schema"],
        "gitSha": _git_short_sha(),
        "syntheticProvenance": synthetic_provenance(run_id),
        "plan": plan,
        "steps": [],
        "passed": True,
        "safety": {
            "liveRequiresExplicitProfileDefault": True,
            "dryRunDefault": True,
            "cleanupStatementCount": len(plan["cleanupStatements"]),
            "unscopedDeletesGenerated": False,
            "excludeSyntheticFromOrganicEvidence": True,
        },
    }
    if not args.live:
        payload["evaluation"] = {
            "markers": {
                "passed": True,
                "expectedRowCount": plan["expectedRowCount"],
                "dryRunOnly": True,
            },
            "workflow": {
                "passed": True,
                "expectedWorkflowCount": plan["expectedWorkflowCount"],
                "expectedAuditEventCount": plan["expectedAuditEventCount"],
                "dryRunOnly": True,
            },
            "cleanup": {"passed": True, "cleanupExpected": not args.keep_resources, "dryRunOnly": True},
        }
        payload["completedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return payload

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    execution: Dict[str, Any] = {
        "setup": [],
        "insert": [],
        "workflow": [],
        "validation": [],
        "preCleanupInventory": [],
        "cleanup": [],
        "cleanupVerification": [],
    }
    marker_rows: List[Dict[str, Any]] = []
    workflow_rows: List[Dict[str, Any]] = []
    step_rows: List[Dict[str, Any]] = []
    try:
        execution["setup"] = _execute_statements(w, warehouse_id=args.warehouse_id, statements=plan["setupStatements"])
        execution["insert"] = _execute_statements(w, warehouse_id=args.warehouse_id, statements=plan["insertStatements"])
        execution["workflow"] = _execute_statements(w, warehouse_id=args.warehouse_id, statements=plan["workflowStatements"])
        execution["validation"] = _execute_statements(
            w,
            warehouse_id=args.warehouse_id,
            statements=plan["validationStatements"],
        )
        if len(execution["validation"]) >= 1:
            marker_rows = execution["validation"][0].get("rows") or []
        if len(execution["validation"]) >= 2:
            workflow_rows = execution["validation"][1].get("rows") or []
        if len(execution["validation"]) >= 3:
            step_rows = execution["validation"][2].get("rows") or []
        execution["preCleanupInventory"] = _execute_statements(
            w,
            warehouse_id=args.warehouse_id,
            statements=plan["inventoryStatements"],
        )
        payload["steps"] = _steps_from_rows(step_rows)
        payload["evaluation"] = {
            "markers": _evaluate_markers(plan, marker_rows),
            "workflow": _evaluate_workflows(plan, workflow_rows),
        }
        payload["passed"] = bool(payload["evaluation"]["markers"]["passed"] and payload["evaluation"]["workflow"]["passed"])
    except Exception as exc:
        payload["passed"] = False
        payload["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
    finally:
        cleanup_errors = []
        for statement in plan["cleanupStatements"]:
            try:
                execution["cleanup"].append(execute_sql(w, warehouse_id=args.warehouse_id, statement=statement))
            except Exception as cleanup_exc:
                cleanup_errors.append({"type": cleanup_exc.__class__.__name__, "message": str(cleanup_exc)})
        for statement in plan["cleanupVerificationStatements"]:
            try:
                execution["cleanupVerification"].append(
                    execute_sql(w, warehouse_id=args.warehouse_id, statement=statement)
                )
            except Exception as cleanup_verify_exc:
                cleanup_errors.append(
                    {"type": cleanup_verify_exc.__class__.__name__, "message": str(cleanup_verify_exc)}
                )
        cleanup_rows = []
        if execution["cleanupVerification"]:
            cleanup_rows = execution["cleanupVerification"][-1].get("rows") or []
        cleanup_evaluation = _evaluate_cleanup(cleanup_rows, cleanup_expected=not args.keep_resources)
        payload.setdefault("evaluation", {})["cleanup"] = cleanup_evaluation
        if not cleanup_evaluation["passed"]:
            payload["passed"] = False
        payload["execution"] = execution
        if cleanup_errors:
            payload["passed"] = False
            payload["cleanupErrors"] = cleanup_errors
        payload["completedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or run a scoped Governance Atlas synthetic workflow stress validation."
    )
    parser.add_argument("--live", action="store_true", help="Execute UC mutations. Omitted means dry-run only.")
    parser.add_argument("--profile", default=None, help="Required as DEFAULT when --live is used.")
    parser.add_argument("--warehouse-id", default="", help="Required when --live is used.")
    parser.add_argument("--catalog", default="datapact")
    parser.add_argument("--schema-prefix", default="atlas_ga_stress")
    parser.add_argument("--run-id", default="", help="Optional prebuilt ga-stress-YYYYMMDDHHMMSS-<shortsha> id.")
    parser.add_argument("--rows-per-scenario", type=int, default=3)
    parser.add_argument("--keep-resources", action="store_true", help="Leave the run-scoped schema in place.")
    parser.add_argument("--output", default="", help="Optional JSON artifact path.")
    parser.add_argument(
        "--scenario",
        choices=("workflow", "ai"),
        default="workflow",
        help="workflow (default): governance workflow stress. ai: AI governance collect/reconcile scenarios.",
    )
    return parser.parse_args(argv)


def run_ai_validation(args: argparse.Namespace) -> Dict[str, Any]:
    """AI governance scenarios (atlas/ai/stress.py) in a run-scoped schema.

    The whole governance schema (migrations 1-22) is created inside
    <schema-prefix>_<run suffix>, exercised with synthetic sample rows, and
    dropped afterwards; the schema name is re-checked before the DROP."""
    validate_runtime_safety(args)
    run_id = args.run_id or build_run_id()
    schema = schema_name_for_run(args.schema_prefix, run_id)
    payload: Dict[str, Any] = {
        "scenario": "ai",
        "mode": "live" if args.live else "dry-run",
        "runId": run_id,
        "catalog": args.catalog,
        "schema": schema,
        "syntheticProvenance": synthetic_provenance(run_id),
        "passed": True,
    }
    if not args.live:
        payload["plan"] = [
            "create run-scoped schema and apply migrations 1-22",
            "import synthetic sample intake; collector append; reconcile run 1",
            "reconcile run 2: no duplicate findings, last_seen advanced",
            "suppress one finding, confirm the ambiguous match; reconcile run 3",
            "verify suppression persists and confirmation became an M2 match",
            "verify ai.* audit rows pair 1:1 with change events; no organic leaks",
            "drop the run-scoped schema and verify zero leftovers",
        ]
        return payload

    from atlas.ai.store import AiStore
    from atlas.ai.stress import run_ai_scenarios
    from atlas.store import GovernanceStore
    from atlas.uc import UCSQLClient

    import os

    os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", args.profile)
    uc = UCSQLClient(warehouse_id=args.warehouse_id)
    store = GovernanceStore(uc=uc, catalog=args.catalog, schema=schema)
    try:
        store.ensure_tables()
        payload["evaluation"] = run_ai_scenarios(AiStore(store), run_id=run_id)
        payload["passed"] = bool(payload["evaluation"]["passed"])
    finally:
        if not args.keep_resources:
            assert_run_scoped_schema(schema, schema_prefix=args.schema_prefix, run_id=run_id)
            uc.execute(f"DROP SCHEMA IF EXISTS {_fq_name(args.catalog, schema)} CASCADE")
            remaining = uc.query_df(
                f"SELECT COUNT(*) AS n FROM system.information_schema.schemata "
                f"WHERE catalog_name = {_sql_string(args.catalog)} AND schema_name = {_sql_string(schema)}"
            )
            leftover = int(remaining.iloc[0, 0]) if remaining is not None and not remaining.empty else -1
            payload["cleanup"] = {"passed": leftover == 0, "leftoverSchemas": leftover}
            payload["passed"] = payload["passed"] and leftover == 0
    return payload


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    payload = run_ai_validation(args) if args.scenario == "ai" else run_validation(args)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
