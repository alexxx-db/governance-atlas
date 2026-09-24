"""Job task 2: reconcile the collector's run into derived state.

Stage everything in memory with the pure ``atlas.ai.reconcile`` functions,
then write. Every write is idempotent (MERGE keyed on deterministic IDs,
control results replaced per run), and the run is marked ``succeeded`` last:
readers only trust the latest succeeded run, so a failure mid-write never
shows partial derived state, and re-running the same run converges.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

def _repo_root() -> str:
    """Serverless spark_python_task runs this file without __file__, so the
    bundle passes --repo-root ${workspace.file_path}; __file__ is the local
    fallback."""
    if "--repo-root" in sys.argv:
        return sys.argv[sys.argv.index("--repo-root") + 1]
    try:
        return str(Path(__file__).resolve().parents[3])
    except NameError:
        return os.getcwd()


sys.path.insert(0, _repo_root())

from atlas.ai.jobs import common  # noqa: E402

LOG = logging.getLogger("atlas.ai.jobs")


def write_result(ai: Any, result: Any, *, run_id: str, actor: str, prior_states: Dict[str, str]) -> Dict[str, Any]:
    from atlas.ai import models
    from atlas.ai.store import AuditEntry, relationship_id_for

    # Registry: only new assets or state changes (a steady-state run is cheap).
    registry_writes = 0
    for asset, state, confidence in result.registry:
        prior = prior_states.get(asset.entity_id)
        if prior == state:
            continue
        ai.upsert_ai_registry(
            entity_id=asset.entity_id,
            entity_kind=asset.entity_kind,
            source_system=asset.source_system,
            source_entity_id=asset.source_entity_id,
            reconciliation_state=state,
            confidence=confidence,
            observed_at=common_ts(asset.observed_at),
            actor_email=actor,
            prior_state=prior,
            entity_fqn=asset.display_name,
        )
        registry_writes += 1

    # Relationships and informational M1 aliases: write only what is missing.
    active_rels = ai.list_relationships(kinds=("declares", "serves"))
    existing_rel = {r["relationship_id"] for r in active_rels}
    # Retire derived declares links this run no longer supports (tag removed
    # or moved). Steward overrides stand; kinds this run couldn't see are left.
    wanted = {relationship_id_for("declares", f"intake:{i}", u.entity_id) for i, u, _ in result.declares}
    stale = [
        r["relationship_id"]
        for r in active_rels
        if r.get("relationship_kind") == "declares"
        and r.get("authority_source") != "override"
        and r["relationship_id"] not in wanted
        and str(r.get("target_entity_kind") or "") not in set(result.blind_kinds)
    ]
    ai.supersede_relationships(stale, actor_email=actor, run_id=run_id)
    existing_rel -= set(stale)
    for intake_id, unit, rule in result.declares:
        source_id = f"intake:{intake_id}"
        if relationship_id_for("declares", source_id, unit.entity_id) in existing_rel:
            continue
        ai.upsert_relationship(
            relationship_kind="declares",
            source_entity_id=source_id,
            source_entity_kind=models.INTAKE_RECORD,
            target_entity_id=unit.entity_id,
            target_entity_kind=unit.entity_kind,
            authority_source="override" if rule == "M2" else "registry",
            evidence={"matchRule": rule, "runId": run_id},
            actor_email=actor,
        )
    for asset, target_kind, target_id in result.serves:
        if relationship_id_for("serves", asset.entity_id, target_id) in existing_rel:
            continue
        ai.upsert_relationship(
            relationship_kind="serves",
            source_entity_id=asset.entity_id,
            source_entity_kind=asset.entity_kind,
            target_entity_id=target_id,
            target_entity_kind=target_kind,
            authority_source="registry",
            evidence={"observedBy": asset.collector, "runId": run_id},
            actor_email=actor,
        )
    existing_alias = {
        (str(r["entity_id"]), str(r["alias_value"]))
        for r in _frame_records(ai.store.list_entity_aliases(alias_type="external_id"))
    }
    for intake_id, unit, rule in result.declares:
        if rule == "M1" and (unit.entity_id, intake_id) not in existing_alias:
            # source 'intake_tag' is informational: M2 only trusts steward
            # confirmations (source intake_id / servicenow_sys_id), so
            # removing the tag later still un-matches the asset.
            ai.upsert_alias(entity_id=unit.entity_id, intake_id=intake_id, source="intake_tag", actor_email=actor)

    finding_counts = ai.upsert_findings(result.findings, run_id=run_id, actor_email=actor)
    resolved = ai.auto_resolve_findings(result.resolve_ids, run_id=run_id, actor_email=actor)

    # Controls for this run, then posture events for bands that changed.
    previous = ai.latest_succeeded_run()
    previous_postures: Dict[str, str] = {}
    if previous:
        from atlas.ai import controls as control_registry

        by_entity: Dict[str, list] = {}
        for row in ai.list_control_results(run_id=str(previous["run_id"])):
            by_entity.setdefault(str(row["entity_id"]), []).append(
                models.ControlResult(str(row["entity_id"]), str(row["entity_kind"]), str(row["control_id"]), "", str(row["status"]), "")
            )
        previous_postures = {eid: control_registry.posture(rows) for eid, rows in by_entity.items()}
    ai.replace_control_results_for_run(result.controls, run_id=run_id, actor_email=actor)
    posture_events = [
        AuditEntry(
            event_type="ai.controls.posture_changed",
            entity_kind="ai_asset",
            entity_id=entity_id,
            actor_email=actor,
            actor_role="system",
            before={"posture": previous_postures.get(entity_id)},
            after={"posture": band, "runId": run_id},
        )
        for entity_id, band in result.postures.items()
        if previous_postures.get(entity_id) != band
    ]
    ai.emit_events(posture_events)
    return {
        **result.counts,
        "findings": {**finding_counts, "resolved": resolved},
        "declaresSuperseded": len(stale),
        "registryWrites": registry_writes,
        "controls": len(result.controls),
        "postureChanges": len(posture_events),
    }


def _prior_declares(ai: Any) -> Dict[str, set]:
    """intake_id -> kinds of assets it is currently linked to."""
    out: Dict[str, set] = {}
    for rel in ai.list_relationships(kinds=("declares",)):
        intake_id = str(rel.get("source_entity_id") or "").removeprefix("intake:")
        out.setdefault(intake_id, set()).add(str(rel.get("target_entity_kind") or ""))
    return out


def common_ts(value: Any):
    from atlas.ai.reconcile import _as_utc

    return _as_utc(value)


def _frame_records(frame: Any) -> list:
    if frame is None or getattr(frame, "empty", True):
        return []
    return frame.to_dict(orient="records")


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = common.parse_args(argv, description=__doc__ or "")
    common.apply_env(args.env)

    from atlas.ai import reconcile
    from atlas.ai.store import AiStore
    from atlas.config import AppConfig
    from atlas.util import error_text

    cfg = AppConfig.from_env()
    run_id = common.resolve_run_id(args)
    w = common.workspace_client()
    actor = common.job_actor(w)
    store, _ = common.build_store(cfg)
    ai = AiStore(store)
    run = ai.get_run(run_id)
    # A failed reconcile is repairable: re-running it converges (DESIGN 3.4),
    # as long as collection finished (sources recorded).
    ready = run and (run.get("status") == "reconciling" or (run.get("status") == "failed" and run.get("sources_json")))
    if not ready:
        LOG.error("run %s is not ready to reconcile (status=%s)", run_id, (run or {}).get("status"))
        return 1
    try:
        result = reconcile.reconcile(
            ai.observations_for_run(run_id),
            ai.list_intake_records(),
            aliases=ai.intake_aliases(),
            active_findings=ai.active_findings(),
            sources=run.get("sources_json") or {},
            intake_tag_key=cfg.ai_intake_tag_key,
            tier_tag_key=cfg.ai_tier_tag_key,
            grace_days=cfg.ai_intake_grace_days,
            prior_declares=_prior_declares(ai),
        )
        counts = write_result(ai, result, run_id=run_id, actor=actor, prior_states=ai.ai_registry_states())
        counts["observations"] = (run.get("counts_json") or {}).get("observations")
        ai.update_reconciliation_run(run_id=run_id, actor_email=actor, status="succeeded", counts=counts, finished=True)
    except Exception as exc:  # noqa: BLE001 - record, then fail the task
        ai.update_reconciliation_run(run_id=run_id, actor_email=actor, status="failed", failure_reason=error_text(exc), finished=True)
        LOG.error("reconciliation failed: %s", error_text(exc))
        return 1
    LOG.info("run %s reconciled: %s", run_id, counts)
    return 0


if __name__ == "__main__":
    # Serverless tasks run under IPython, which reports even SystemExit(0) as
    # a failed workload: return normally on success, raise only on failure.
    exit_code = main()
    if exit_code:
        raise RuntimeError(f"{__doc__.splitlines()[0] if __doc__ else 'AI job task'} failed (exit {exit_code}); see the reconciliation run record.")
