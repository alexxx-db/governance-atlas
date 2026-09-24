"""Shared bootstrap for AI governance job entry points.

Serverless job tasks don't get app-style environment variables, so the bundle
passes configuration as repeated ``--env KEY=VALUE`` parameters. The entry
point applies them to ``os.environ`` and then builds ``AppConfig`` and the
governance store exactly as the app does, including the Lakebase dual-write
wrapper, so registry writes keep the mirror consistent.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

# Job tasks run a file from the bundle's synced tree; make the repo root
# importable so `atlas` resolves without packaging a wheel.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from atlas.config import AppConfig  # noqa: E402

LOG = logging.getLogger("atlas.ai.jobs")


def parse_args(argv: Optional[Sequence[str]] = None, description: str = "") -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--env", action="append", default=[], help="KEY=VALUE applied to os.environ before config loads")
    parser.add_argument("--run-id", default="", help="Reconciliation run id; defaults to dbx-<job-run-id>")
    parser.add_argument("--job-run-id", default="", help="Databricks job run id ({{job.run_id}})")
    return parser.parse_args(argv)


def apply_env(pairs: Sequence[str]) -> None:
    for pair in pairs:
        key, sep, value = str(pair).partition("=")
        if sep and key.strip():
            os.environ[key.strip()] = value


def resolve_run_id(args: argparse.Namespace) -> str:
    if args.run_id:
        return args.run_id
    if args.job_run_id:
        return f"dbx-{args.job_run_id}"
    raise SystemExit("--run-id or --job-run-id is required so both tasks share one run")


def workspace_client() -> Any:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def job_actor(w: Any) -> str:
    """The identity the job runs as (the collector SP in staging/prod; the
    deploying user in dev, PHASE0 D7). Audit rows use it with source='system'."""
    try:
        me = w.current_user.me()
        return str(me.user_name or me.display_name or "ai-collector")
    except Exception:  # noqa: BLE001
        return "ai-collector"


def build_store(cfg: AppConfig) -> Tuple[Any, Any]:
    """Governance store as the app builds it (runtime_app._store), without
    importing the FastAPI app. Returns (store, uc)."""
    from atlas.services import lakebase as lakebase_service
    from atlas.services import lakebase_store as lakebase_store_service
    from atlas.store import GovernanceStore
    from atlas.uc import UCSQLClient

    uc = UCSQLClient(warehouse_id=cfg.warehouse_id)
    store = GovernanceStore(uc=uc, catalog=cfg.gov_catalog, schema=cfg.gov_schema)
    store.ensure_tables()
    if cfg.lakebase_enabled:
        try:
            lakebase_service.ensure_schema(cfg, include_upgrades=False)
            mirror = lakebase_store_service.LakebaseOperationalMirror(config=cfg, delta_store=store)
            return lakebase_store_service.DualWriteGovernanceStore(store, mirror), uc
        except Exception as exc:  # noqa: BLE001 - same degraded behavior as the app
            LOG.warning("Lakebase dual-write mirror inactive for this job: %s", type(exc).__name__)
    return store, uc


def split_list(value: str) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]
