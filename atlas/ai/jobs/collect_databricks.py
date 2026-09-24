"""Job task 1: collect Databricks AI assets into ai_asset_observations.

Starts the reconciliation run record, probes and collects every source,
appends redacted observations, and records per-source availability in
``reconciliation_runs.sources_json`` for the reconcile task and the UI.
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from atlas.ai.jobs import common  # noqa: E402


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = common.parse_args(argv, description=__doc__ or "")
    common.apply_env(args.env)

    from atlas.ai.collectors import databricks as collector
    from atlas.ai.models import RunContext, utc_now
    from atlas.ai.store import AiStore
    from atlas.config import AppConfig
    from atlas.util import error_text

    cfg = AppConfig.from_env()
    run_id = common.resolve_run_id(args)
    w = common.workspace_client()
    actor = common.job_actor(w)
    store, uc = common.build_store(cfg)
    ai = AiStore(store)
    ai.start_reconciliation_run(run_id=run_id, triggered_by=actor, job_run_id=args.job_run_id or None, rule_set_version="phase1")

    ctx = RunContext(
        run_id=run_id,
        collector=collector.COLLECTOR,
        collector_version=collector.COLLECTOR_VERSION,
        source_system=collector.SOURCE_SYSTEM,
        started_at=utc_now(),
        job_run_id=args.job_run_id or None,
        actor=actor,
    )
    # Empty allowlist means "use discovery catalogs"; both empty means every
    # catalog the job identity can list.
    catalogs = cfg.ai_catalog_allowlist or common.split_list(os.environ.get("GOVAT_DISCOVERY_CATALOGS", ""))
    try:
        observations, sources = collector.collect(
            w,
            ctx,
            catalogs=catalogs,
            tool_schemas=cfg.ai_tool_schema_allowlist,
            routine_tags=collector.routine_tag_lookup(uc),
        )
        ai.append_observations(observations, run_id=run_id, actor_email=actor)
        ai.update_reconciliation_run(
            run_id=run_id,
            actor_email=actor,
            status="reconciling",
            sources={name: result.to_dict() for name, result in sources.items()},
            counts={"observations": dict(Counter(o.entity_kind for o in observations))},
        )
    except Exception as exc:  # noqa: BLE001 - record the failure, then fail the task
        ai.update_reconciliation_run(run_id=run_id, actor_email=actor, status="failed", failure_reason=error_text(exc), finished=True)
        logging.getLogger("atlas.ai.jobs").error("collection failed: %s", error_text(exc))
        return 1
    logging.getLogger("atlas.ai.jobs").info("run %s: %d observations", run_id, len(observations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
