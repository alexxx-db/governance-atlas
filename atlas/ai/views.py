"""Read models for /api/ai (DESIGN.md 9).

Every view is built from the **latest succeeded reconciliation run**, the
commit marker for derived state (DESIGN.md 3.4), and reports availability
honestly:

- no succeeded run yet: ``unavailable`` with a reason, and counts are ``None``
  (never zero);
- latest run failed or still running, or a source was unavailable/degraded in
  the run shown: ``degraded``, with one warning per source naming the reason.

Every asset row carries provenance (source system, collector and version,
run ID, observed-at, provenance class).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence

from atlas.ai import controls as control_registry
from atlas.ai import models

SHADOW_TYPES = ("found_not_registered", "rejected_but_running")
OPEN_STATES = ("open", "acknowledged")
DIFF_FIELDS = (("provider", "provider"), ("model_family", "model_family"), ("owner", "owner_email"), ("platform", "platform"))


def availability(ai: Any) -> Dict[str, Any]:
    """Which run the views reflect, and what (if anything) is degraded."""
    runs = ai.list_runs(limit=1)
    latest = runs[0] if runs else None
    succeeded = ai.latest_succeeded_run()
    warnings: List[str] = []
    sources: Dict[str, Any] = {}
    if succeeded is None:
        reason = (
            "No AI reconciliation run has completed yet. Run the atlas-ai-collect-and-reconcile job."
            if latest is None
            else f"No AI reconciliation run has completed yet (latest run {latest['run_id']} is {latest.get('status')})."
        )
        return {"state": "unavailable", "reason": reason, "run": None, "latestRun": _run_summary(latest), "sources": {}, "warnings": [reason]}
    sources = dict(succeeded.get("sources_json") or {})
    notes: List[str] = []
    for name, probe in sorted(sources.items()):
        state = str((probe or {}).get("state") or "unknown")
        reason = (probe or {}).get("reason") or "no reason recorded"
        if state in (models.PROBE_NOT_SUPPORTED, models.PROBE_NOT_CONFIGURED):
            # Known permanent gaps are disclosed, but they are not an outage.
            label = "not supported" if state == models.PROBE_NOT_SUPPORTED else "not configured"
            notes.append(f"{name} ({label}): {reason}")
        elif state != models.PROBE_AVAILABLE:
            warnings.append(f"{name} was {state} in run {succeeded['run_id']}: {reason}")
    if latest and latest["run_id"] != succeeded["run_id"]:
        if latest.get("status") == "failed":
            warnings.append(
                f"Latest run {latest['run_id']} failed ({latest.get('failure_reason') or 'no reason recorded'}); showing run {succeeded['run_id']}."
            )
        else:
            warnings.append(f"Run {latest['run_id']} is {latest.get('status')}; showing the last completed run {succeeded['run_id']}.")
    return {
        "state": "degraded" if warnings else "available",
        "reason": "",
        "run": _run_summary(succeeded),
        "latestRun": _run_summary(latest),
        "sources": sources,
        "warnings": warnings,
        "notes": notes,
    }


def _run_summary(run: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not run:
        return None
    return {
        "runId": run.get("run_id"),
        "jobRunId": run.get("job_run_id"),
        "status": run.get("status"),
        "startedAt": _iso(run.get("started_at")),
        "finishedAt": _iso(run.get("finished_at")),
        "counts": run.get("counts_json") or {},
        "failureReason": run.get("failure_reason"),
    }


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _asset_row(obs: Mapping[str, Any], registry: Mapping[str, Mapping[str, Any]], open_counts: Mapping[str, int], postures: Mapping[str, str], tier_key: str) -> Dict[str, Any]:
    entity_id = models.ai_entity_id(str(obs["entity_kind"]), str(obs["source_system"]), str(obs["source_entity_id"]))
    reg = registry.get(entity_id) or {}
    tags = obs.get("tags_json") or {}
    return {
        "entityId": entity_id,
        "entityKind": obs["entity_kind"],
        "name": obs.get("display_name") or obs["source_entity_id"],
        "sourceEntityId": obs["source_entity_id"],
        "parentSourceEntityId": obs.get("parent_source_entity_id"),
        "platform": obs.get("platform"),
        "provider": obs.get("provider"),
        "modelFamily": obs.get("model_family"),
        "owner": obs.get("owner"),
        "tier": tags.get(tier_key),
        "reconciliationState": reg.get("reconciliation_state"),
        "confidence": _num(reg.get("reconciliation_confidence")),
        "openFindings": int(open_counts.get(entity_id, 0)),
        "posture": postures.get(entity_id),
        "provenance": {
            "sourceSystem": obs.get("source_system"),
            "collector": obs.get("collector"),
            "collectorVersion": obs.get("collector_version"),
            "runId": obs.get("run_id"),
            "observedAt": _iso(obs.get("observed_at")),
            "provenanceClass": obs.get("provenance_class"),
            "sampleRunId": obs.get("sample_run_id"),
        },
    }


def _postures(control_rows: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    by_entity: Dict[str, List[models.ControlResult]] = {}
    for row in control_rows:
        by_entity.setdefault(str(row["entity_id"]), []).append(
            models.ControlResult(str(row["entity_id"]), str(row["entity_kind"]), str(row["control_id"]), "", str(row["status"]), "")
        )
    return {eid: control_registry.posture(rows) for eid, rows in by_entity.items()}


def inventory_rows(ai: Any, avail: Mapping[str, Any], tier_key: str) -> List[Dict[str, Any]]:
    run = avail.get("run")
    if not run:
        return []
    run_id = str(run["runId"])
    observations = ai.observations_for_run(run_id)
    registry = ai.ai_registry_rows()
    open_counts = ai.open_findings_by_entity()
    postures = _postures(ai.list_control_results(run_id=run_id))
    return [_asset_row(o, registry, open_counts, postures, tier_key) for o in observations]


def filter_rows(rows: List[Dict[str, Any]], filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    def keep(row: Mapping[str, Any]) -> bool:
        for key, field in (("kind", "entityKind"), ("provider", "provider"), ("platform", "platform"), ("tier", "tier"), ("state", "reconciliationState")):
            want = filters.get(key)
            if want and str(row.get(field) or "").lower() != str(want).lower():
                return False
        if filters.get("hasOpenFindings") is True and not row["openFindings"]:
            return False
        if filters.get("hasOpenFindings") is False and row["openFindings"]:
            return False
        query = str(filters.get("q") or "").strip().lower()
        if query and query not in f"{row['name']} {row['sourceEntityId']} {row.get('owner') or ''}".lower():
            return False
        return True

    return [row for row in rows if keep(row)]


SORT_KEYS = {
    "name": lambda r: (str(r["name"]).lower(),),
    "kind": lambda r: (r["entityKind"], str(r["name"]).lower()),
    "state": lambda r: (str(r.get("reconciliationState") or ""), str(r["name"]).lower()),
    "findings": lambda r: (-r["openFindings"], str(r["name"]).lower()),
}


def summary(ai: Any, avail: Mapping[str, Any], tier_key: str) -> Dict[str, Any]:
    if not avail.get("run"):
        return {"assetsByKind": None, "findings": None, "shadowAi": None, "ambiguousMatches": None, "posture": None, "assetCount": None}
    rows = inventory_rows(ai, avail, tier_key)
    finding_rows = ai.finding_counts()
    open_rows = [r for r in finding_rows if r["state"] in OPEN_STATES]
    by_type = Counter()
    by_severity = Counter()
    for r in open_rows:
        by_type[str(r["finding_type"])] += int(r["n"])
        by_severity[str(r["severity"])] += int(r["n"])
    postures = Counter(r["posture"] for r in rows if r.get("posture"))
    assessed = sum(v for k, v in postures.items() if k != "unknown")
    return {
        "assetCount": len(rows),
        "assetsByKind": dict(Counter(r["entityKind"] for r in rows)),
        "findings": {"openByType": dict(by_type), "openBySeverity": dict(by_severity), "open": sum(by_type.values())},
        "shadowAi": sum(by_type.get(t, 0) for t in SHADOW_TYPES),
        "ambiguousMatches": by_type.get("ambiguous_match", 0),
        "posture": {
            "bands": dict(postures),
            "assessed": assessed,
            "withControls": sum(postures.values()),
            "coverage": (assessed / len(rows)) if rows else None,
        },
    }


def _declared_intake(ai: Any, entity_id: str, parent_entity_id: Optional[str], intakes: Mapping[str, Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    for candidate in (entity_id, parent_entity_id):
        if not candidate:
            continue
        for rel in ai.list_relationships(entity_id=candidate, kinds=("declares",)):
            if rel.get("target_entity_id") == candidate:
                intake_id = str(rel.get("source_entity_id") or "").removeprefix("intake:")
                if intake_id in intakes:
                    return {"intake": intakes[intake_id], "authority": rel.get("authority_source"), "via": "self" if candidate == entity_id else "parent"}
    return None


def _num(value: Any) -> Optional[float]:
    """Warehouse rows are strings; send numbers as numbers."""
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def asset_detail(ai: Any, avail: Mapping[str, Any], entity_id: str, *, tier_key: str, include_config: bool) -> Optional[Dict[str, Any]]:
    """``include_config`` marks a steward/admin caller: only they receive
    config, findings, and finding history (findings are steward-only, DESIGN 9)."""
    run = avail.get("run")
    if not run:
        return None
    run_id = str(run["runId"])
    observations = ai.observations_for_run(run_id)
    by_id = {models.ai_entity_id(str(o["entity_kind"]), str(o["source_system"]), str(o["source_entity_id"])): o for o in observations}
    obs = by_id.get(entity_id)
    if obs is None:
        return None
    parent = None
    if obs.get("parent_source_entity_id"):
        for candidate_id, candidate in by_id.items():
            if candidate["source_entity_id"] == obs["parent_source_entity_id"] and candidate["entity_kind"] != obs["entity_kind"]:
                parent = candidate_id
                break
    registry = ai.ai_registry_rows()
    open_counts = ai.open_findings_by_entity()
    control_rows = ai.list_control_results(run_id=run_id, entity_id=entity_id)
    row = _asset_row(obs, registry, open_counts, _postures(control_rows), tier_key)
    intakes = {str(r["intake_id"]): r for r in ai.list_intake_records()}
    declared = _declared_intake(ai, entity_id, parent, intakes)
    intake = (declared or {}).get("intake")
    observed_values = {
        "provider": obs.get("provider"),
        "model_family": obs.get("model_family"),
        "owner": obs.get("owner"),
        "platform": obs.get("platform"),
        "risk_tier": (obs.get("tags_json") or {}).get(tier_key),
    }
    diff = []
    for obs_field, intake_field in (*DIFF_FIELDS, ("risk_tier", "risk_tier")):
        declared_value = (intake or {}).get(intake_field)
        observed_value = observed_values.get(obs_field)
        differs = bool(declared_value and observed_value and str(declared_value).strip().lower() != str(observed_value).strip().lower())
        diff.append({"field": obs_field, "declared": declared_value, "observed": observed_value, "differs": differs})
    findings = ai.list_findings(entity_id=entity_id, limit=100) if include_config else []
    events = ai.list_entity_events([entity_id, *[f["finding_id"] for f in findings]], limit=100)
    detail = {
        **row,
        "tags": obs.get("tags_json") or {},
        "declared": None
        if not intake
        else {
            "intakeId": intake.get("intake_id"),
            "title": intake.get("title"),
            "state": intake.get("state"),
            "ownerEmail": intake.get("owner_email"),
            "riskTier": intake.get("risk_tier"),
            "provider": intake.get("provider"),
            "modelFamily": intake.get("model_family"),
            "platform": intake.get("platform"),
            "authority": declared.get("authority"),
            "via": declared.get("via"),
            "provenance": {
                "sourceSystem": intake.get("source_system"),
                "ingestSource": intake.get("ingest_source"),
                "ingestRunId": intake.get("ingest_run_id"),
                "updatedAt": _iso(intake.get("updated_at")),
                "provenanceClass": intake.get("provenance_class"),
            },
        },
        "diff": diff,
        "relationships": [
            {k: rel.get(k) for k in ("relationship_kind", "source_entity_id", "source_entity_kind", "target_entity_id", "target_entity_kind", "authority_source")}
            for rel in ai.list_relationships(entity_id=entity_id)
        ],
        "controls": [control_view(r) for r in control_rows],
        "findings": [finding_view(f) for f in findings] if include_config else None,
        "history": [
            {
                "eventId": e.get("event_id"),
                "eventType": e.get("event_type"),
                "actorEmail": e.get("actor_email"),
                "source": e.get("source"),
                "status": e.get("status"),
                "requestId": e.get("request_id"),
                "occurredAt": _iso(e.get("occurred_at")),
                "before": e.get("before_json"),
                "after": e.get("after_json"),
            }
            for e in events
        ],
    }
    if include_config:
        detail["config"] = obs.get("config_json") or {}
    return detail


def control_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "controlId": row.get("control_id"),
        "title": control_registry.CONTROL_TITLES.get(str(row.get("control_id")), str(row.get("control_id"))),
        "status": row.get("status"),
        "signalSource": row.get("signal_source"),
        "evidence": row.get("evidence_json") or {},
        "runId": row.get("run_id"),
        "observedAt": _iso(row.get("observed_at")),
    }


def finding_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "findingId": row.get("finding_id"),
        "findingType": row.get("finding_type"),
        "ruleId": row.get("rule_id"),
        "severity": row.get("severity"),
        "state": row.get("state"),
        "entityId": row.get("entity_id"),
        "entityKind": row.get("entity_kind"),
        "intakeId": row.get("intake_id"),
        "matchRule": row.get("match_rule"),
        "matchScore": _num(row.get("match_score")),
        "evidence": row.get("evidence_json") or {},
        "firstSeenAt": _iso(row.get("first_seen_at")),
        "lastSeenAt": _iso(row.get("last_seen_at")),
        "lastRunId": row.get("last_run_id"),
        "assigneeEmail": row.get("assignee_email"),
        "resolutionNote": row.get("resolution_note"),
        "suppressionReason": row.get("suppression_reason"),
        "resolvedBy": row.get("resolved_by"),
        "resolvedAt": _iso(row.get("resolved_at")),
        "stateChangedBy": row.get("state_changed_by"),
        "stateChangedAt": _iso(row.get("state_changed_at")),
        "provenanceClass": row.get("provenance_class"),
        "sampleRunId": row.get("sample_run_id"),
    }


def intake_rows(ai: Any) -> List[Dict[str, Any]]:
    declares = ai.list_relationships(kinds=("declares",))
    linked: Dict[str, List[str]] = {}
    for rel in declares:
        intake_id = str(rel.get("source_entity_id") or "").removeprefix("intake:")
        linked.setdefault(intake_id, []).append(str(rel.get("target_entity_id")))
    rnf = ai.not_found_intake_ids()
    out = []
    for row in ai.list_intake_records():
        intake_id = str(row["intake_id"])
        entities = linked.get(intake_id, [])
        out.append(
            {
                "intakeId": intake_id,
                "title": row.get("title"),
                "state": row.get("state"),
                "ownerEmail": row.get("owner_email"),
                "riskTier": row.get("risk_tier"),
                "provider": row.get("provider"),
                "modelFamily": row.get("model_family"),
                "approvedAt": _iso(row.get("approved_at")),
                "linkStatus": "linked" if entities else ("not_found" if intake_id in rnf else "unlinked"),
                "linkedEntityIds": entities,
                "provenance": {
                    "sourceSystem": row.get("source_system"),
                    "ingestSource": row.get("ingest_source"),
                    "ingestRunId": row.get("ingest_run_id"),
                    "updatedAt": _iso(row.get("updated_at")),
                    "provenanceClass": row.get("provenance_class"),
                },
            }
        )
    return out
