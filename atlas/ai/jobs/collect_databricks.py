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
        )
        # A retried task reuses the run id: clear what an earlier attempt
        # appended so the run never holds duplicate observations.
        ai.clear_run_observations(run_id=run_id, actor_email=actor)
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
    # Serverless tasks run under IPython, which reports even SystemExit(0) as
    # a failed workload: return normally on success, raise only on failure.
    exit_code = main()
    if exit_code:
        raise RuntimeError(f"{__doc__.splitlines()[0] if __doc__ else 'AI job task'} failed (exit {exit_code}); see the reconciliation run record.")
