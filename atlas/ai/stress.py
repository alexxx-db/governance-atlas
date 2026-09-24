"""AI governance scenarios for scripts/run_synthetic_stress_validation.py.

Runs the real store + reconciliation code against a *run-scoped* schema
(``<prefix>_<run suffix>``) that is dropped afterwards. Synthetic
observations are allowed only here (AGENTS.md section 3): they never touch the
governance schema the app reads, and every row is marked
``provenance_class='sample'`` with ``sample_run_id=<run id>``.

Checks:
  collector append, reconciliation idempotency across two runs (no duplicate
  findings, last_seen advanced), steward suppression persisting across a run,
  steward confirmation becoming an M2 match, audit/event pairing, no organic
  leaks, and zero leftovers after cleanup.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from atlas.ai import models, reconcile, sample
from atlas.ai.intake import load_field_map, map_row

OWNER = "stress-owner@example.com"
ACTOR = "ga-ai-stress"


def synthetic_observations(run_id: str, sample_run_id: str) -> List[models.Observation]:
    """Observations shaped like the collector's output for the sample scenario."""
    now = datetime.now(timezone.utc)
    common = dict(run_id=run_id, source_system="databricks", collector="dbx_ai_collector", collector_version="stress",
                  observed_at=now, owner=OWNER, provenance_class=models.PROVENANCE_SAMPLE, sample_run_id=sample_run_id)
    out: List[models.Observation] = []
    for ep in sample.SCENARIO.endpoints:
        tags = {sample.INTAKE_TAG_KEY: ep.intake_id, sample.TIER_TAG_KEY: ep.tier}
        out.append(models.Observation(entity_kind=models.SERVING_ENDPOINT, source_entity_id=ep.name, display_name=ep.name,
                                      platform="external", provider=ep.provider, tags=tags,
                                      config={"ai_gateway": {"usage_tracking_config": {"enabled": ep.usage_tracking}}},
                                      relationships=[{"kind": "serves", "target_kind": models.EXTERNAL_MODEL, "target_source_entity_id": f"{ep.name}/model"}],
                                      **common))
        out.append(models.Observation(entity_kind=models.EXTERNAL_MODEL, source_entity_id=f"{ep.name}/model",
                                      parent_source_entity_id=ep.name, display_name=f"{ep.name} / model", platform="external",
                                      provider=ep.provider, model_family=ep.model, tags=tags,
                                      config={"credentials": {"observable": False, "secret_refs": [], "plaintext_fields": []}}, **common))
    out.append(models.Observation(entity_kind=models.MCP_SERVER, source_entity_id=sample.SCENARIO.mcp_connection,
                                  display_name=sample.SCENARIO.mcp_connection, platform="databricks", **common))
    fn = f"main.{sample.SCHEMA}.{sample.SCENARIO.function_tool}"
    out.append(models.Observation(entity_kind=models.UC_FUNCTION_TOOL, source_entity_id=fn, display_name=fn, platform="databricks",
                                  tags={sample.INTAKE_TAG_KEY: sample.SCENARIO.function_intake_id, sample.TIER_TAG_KEY: "low"}, **common))
    model = f"main.{sample.SCHEMA}.{sample.SCENARIO.registered_model}"
    out.append(models.Observation(entity_kind=models.AI_MODEL, source_entity_id=model, display_name=model, platform="databricks", **common))
    return out


def synthetic_intakes(sample_run_id: str) -> List[models.IntakeRecord]:
    records = []
    field_map = load_field_map()
    for index, row in enumerate(sample.intake_rows(OWNER), start=2):
        raw = {k: ("" if v is None else v) for k, v in row.items()}
        raw["owner"] = OWNER
        raw["approved_at"] = row["approved_at"].strftime("%Y-%m-%d") if row["approved_at"] else ""
        result = map_row(raw, field_map, row_number=index, ingest_run_id=sample_run_id,
                         provenance_class=models.PROVENANCE_SAMPLE, sample_run_id=sample_run_id)
        if not result.valid:
            raise ValueError(f"synthetic intake invalid: {result.errors}")
        records.append(result.record)
    return records


def _scalar(uc: Any, sql: str) -> int:
    frame = uc.query_df(sql)
    if frame is None or frame.empty:
        return 0
    return int(frame.iloc[0, 0] or 0)


def reconcile_once(ai: Any, *, run_id: str, sample_run_id: str) -> Dict[str, Any]:
    from atlas.ai.jobs.reconcile import write_result

    ai.start_reconciliation_run(run_id=run_id, triggered_by=ACTOR, rule_set_version="stress")
    observations = synthetic_observations(run_id, sample_run_id)
    ai.append_observations(observations, run_id=run_id, actor_email=ACTOR)
    sources = {name: {"state": "available", "reason": ""} for name in reconcile.SOURCE_KINDS}
    ai.update_reconciliation_run(run_id=run_id, actor_email=ACTOR, status="reconciling", sources=sources)
    result = reconcile.reconcile(
        ai.observations_for_run(run_id), ai.list_intake_records(), aliases=ai.intake_aliases(),
        active_findings=ai.active_findings(), sources=sources, intake_tag_key=sample.INTAKE_TAG_KEY,
        tier_tag_key=sample.TIER_TAG_KEY, grace_days=30,
    )
    counts = write_result(ai, result, run_id=run_id, actor=ACTOR, prior_states=ai.ai_registry_states())
    ai.update_reconciliation_run(run_id=run_id, actor_email=ACTOR, status="succeeded", counts=counts, finished=True)
    return counts


def run_ai_scenarios(ai: Any, *, run_id: str, organic_check: Optional[Callable[[], int]] = None) -> Dict[str, Any]:
    """Execute every AI scenario against ``ai`` (bound to the run-scoped schema)."""
    uc = ai.uc
    checks: Dict[str, Dict[str, Any]] = {}

    def check(name: str, passed: bool, **detail: Any) -> None:
        checks[name] = {"passed": bool(passed), **detail}

    ai.upsert_intake_records(synthetic_intakes(run_id), actor_email=ACTOR, actor_role="system", source="system")
    first = reconcile_once(ai, run_id=f"{run_id}-r1", sample_run_id=run_id)
    check("collectorAppend", _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('ai_asset_observations')}") == len(synthetic_observations("x", run_id)))
    found = {(r["finding_type"], r.get("intake_id")) for r in ai.list_findings(states=("open",), limit=500)}
    check("expectedFindings", found == sample.EXPECTED_FINDINGS, got=sorted(map(str, found)))

    second = reconcile_once(ai, run_id=f"{run_id}-r2", sample_run_id=run_id)
    total = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('reconciliation_findings')}")
    distinct = _scalar(uc, f"SELECT COUNT(DISTINCT finding_id) FROM {ai._fq('reconciliation_findings')}")
    advanced = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('reconciliation_findings')} WHERE state = 'open' AND last_run_id = '{run_id}-r2'")
    open_count = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('reconciliation_findings')} WHERE state = 'open'")
    check("idempotentFindings", total == distinct == len(sample.EXPECTED_FINDINGS), total=total, distinct=distinct)
    check("lastSeenAdvanced", advanced == open_count > 0, advanced=advanced, open=open_count)
    check("secondRunOpenedNothing", second["findings"].get("opened", 0) == 0, counts=second["findings"])

    rows = ai.list_findings(states=("open",), limit=500)
    fnr = next(r for r in rows if r["finding_type"] == "found_not_registered")
    amb = next(r for r in rows if r["finding_type"] == "ambiguous_match")
    ai.update_finding_state(finding_id=fnr["finding_id"], action="suppress", actor_email=ACTOR, actor_role="steward", reason="stress: accepted")
    ai.confirm_match(finding_id=amb["finding_id"], entity_id=amb["entity_id"], entity_kind=amb["entity_kind"],
                     intake_id="AI-SAMPLE-005", actor_email=ACTOR, actor_role="steward", note="stress confirmation")
    reconcile_once(ai, run_id=f"{run_id}-r3", sample_run_id=run_id)
    after = ai.findings_by_id([fnr["finding_id"], amb["finding_id"]])
    check("suppressionPersists", after[fnr["finding_id"]]["state"] == "suppressed")
    registry = ai.ai_registry_rows()
    check("confirmationBecomesM2", registry.get(amb["entity_id"], {}).get("reconciliation_state") == "matched"
          and after[amb["finding_id"]]["state"] == "resolved")

    audits = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('metadata_audit_log')}")
    events = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('change_events')} WHERE event_type LIKE 'ai.%'")
    ai_audits = _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq('metadata_audit_log')} WHERE action LIKE 'ai.%'")
    check("auditEventPairing", ai_audits == events > 0, aiAudits=ai_audits, aiEvents=events, allAudits=audits)

    leaks = 0
    for table in ("ai_asset_observations", "intake_records", "reconciliation_findings", "ai_control_results"):
        leaks += _scalar(uc, f"SELECT COUNT(*) FROM {ai._fq(table)} WHERE NOT (provenance_class = 'sample' AND sample_run_id = '{run_id}')")
    organic = organic_check() if organic_check else 0
    check("noOrganicLeaks", leaks == 0 and organic == 0, nonSampleRows=leaks, organicSchemaRows=organic)
    return {"passed": all(c["passed"] for c in checks.values()), "checks": checks, "firstRun": first}
