"""Deploy-time job task: create or upgrade the Axiom governance schema.

Runs as the deploying identity, so the app does not need to run DDL when it
starts. It then grants the app's service principal read/write on the schema.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence


def _repo_root() -> str:
    """Serverless spark_python_task runs this file without __file__, so the
    bundle passes --repo-root ${workspace.file_path}."""
    if "--repo-root" in sys.argv:
        return sys.argv[sys.argv.index("--repo-root") + 1]
    try:
        return str(Path(__file__).resolve().parents[2])
    except NameError:
        return os.getcwd()


sys.path.insert(0, _repo_root())

from axiom.ai.jobs import common  # noqa: E402

LOG = logging.getLogger("axiom.jobs.migrate_schema")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--env", action="append", default=[], help="KEY=VALUE applied to os.environ before config loads")
    parser.add_argument("--repo-root", default="", help="Bundle files path (serverless tasks have no __file__)")
    parser.add_argument("--app-name", default="", help="Grant this app's service principal access to the schema")
    parser.add_argument("--force", action="store_true", help="Run the DDL even when the schema fingerprint matches")
    parser.add_argument("--dry-run", action="store_true", help="Only report whether the schema is current")
    return parser.parse_args(argv)


def app_principal(w: Any, app_name: str) -> str:
    app = w.apps.get(name=app_name)
    principal = str(getattr(app, "service_principal_client_id", "") or "").strip()
    if not principal:
        raise RuntimeError(f"App {app_name!r} has no service principal yet; deploy the bundle first.")
    return principal


def grant_app_access(uc: Any, store: Any, principal: str) -> None:
    from axiom.util import quote_ident

    grantee = quote_ident(principal)
    try:
        uc.execute(f"GRANT USE CATALOG ON CATALOG {quote_ident(store.catalog)} TO {grantee}")
    except Exception as exc:  # noqa: BLE001 - catalog grants may belong to a catalog owner
        LOG.warning("Could not grant USE CATALOG on %s: %s", store.catalog, exc)
    uc.execute(f"GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA {store.fq_schema} TO {grantee}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args(argv)
    common.apply_env(args.env)

    from axiom.config import AppConfig
    from axiom.store import GovernanceStore
    from axiom.uc import UCSQLClient

    cfg = AppConfig.from_env()
    uc = UCSQLClient(warehouse_id=cfg.warehouse_id)
    store = GovernanceStore(uc=uc, catalog=cfg.gov_catalog, schema=cfg.gov_schema)
    fingerprint = store.schema_fingerprint()

    if args.dry_run:
        state = "current" if store.schema_is_current() else "out of date"
        LOG.info("%s is %s (expected fingerprint %s)", store.fq_schema, state, fingerprint)
        return 0

    if args.force:
        store.ensure_tables()
        store.mark_schema_current()
        result = "migrated"
    else:
        result = store.bootstrap_schema("auto")
    LOG.info("%s: %s (fingerprint %s)", store.fq_schema, result, fingerprint)

    if args.app_name:
        principal = app_principal(common.workspace_client(), args.app_name)
        grant_app_access(uc, store, principal)
        LOG.info("Granted app %s (%s) USE SCHEMA, SELECT, MODIFY on %s", args.app_name, principal, store.fq_schema)
    return 0


if __name__ == "__main__":
    # Serverless spark_python_task runs under IPython, which reports even
    # SystemExit(0) as a task failure; only exit explicitly on error.
    exit_code = main()
    if exit_code:
        raise SystemExit(exit_code)
