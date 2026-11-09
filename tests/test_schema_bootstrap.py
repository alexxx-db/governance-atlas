from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.jobs import migrate_schema
from axiom.services import lakebase
from axiom.store import GovernanceStore

ROOT = Path(__file__).resolve().parents[1]


class FakeUC:
    def __init__(self, fingerprint: str | None = None) -> None:
        self.fingerprint = fingerprint
        self.executed: list[str] = []

    def execute(self, statement: str, **_: object) -> None:
        self.executed.append(statement)

    def query_df(self, statement: str, **_: object) -> pd.DataFrame:
        if statement.startswith("SHOW TBLPROPERTIES") and self.fingerprint:
            return pd.DataFrame([{"key": "axiom.schema_fingerprint", "value": self.fingerprint}])
        return pd.DataFrame()


class SchemaBootstrapTests(unittest.TestCase):
    def _store(self, fingerprint: str | None = None) -> GovernanceStore:
        return GovernanceStore(uc=FakeUC(fingerprint), catalog="ops_governance", schema="axiom")

    def test_current_schema_runs_no_ddl(self) -> None:
        store = self._store(GovernanceStore.schema_fingerprint())
        self.assertEqual(store.bootstrap_schema("auto"), "current")
        self.assertEqual(store.uc.executed, [])

    def test_auto_mode_migrates_and_records_fingerprint(self) -> None:
        store = self._store("stale")
        self.assertEqual(store.bootstrap_schema("auto"), "migrated")
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS" in sql for sql in store.uc.executed))
        self.assertIn(GovernanceStore.schema_fingerprint(), store.uc.executed[-1])
        self.assertTrue(store.uc.executed[-1].startswith("ALTER TABLE"))

    def test_verify_mode_never_runs_ddl(self) -> None:
        store = self._store()
        self.assertEqual(store.bootstrap_schema("verify"), "outdated")
        self.assertEqual(store.uc.executed, [])

    def test_off_mode_skips_check(self) -> None:
        store = self._store()
        self.assertEqual(store.bootstrap_schema("off"), "skipped")
        self.assertEqual(store.uc.executed, [])

    def test_migration_job_grants_app_principal(self) -> None:
        store = self._store()
        w = SimpleNamespace(apps=SimpleNamespace(get=lambda name: SimpleNamespace(service_principal_client_id="sp-123")))
        migrate_schema.grant_app_access(store.uc, store, migrate_schema.app_principal(w, "axiom"))
        self.assertIn(
            "GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA `ops_governance`.`axiom` TO `sp-123`",
            store.uc.executed,
        )


class LakebasePoolTests(unittest.TestCase):
    def setUp(self) -> None:
        lakebase.close_pools()
        lakebase._TOKENS.clear()

    def tearDown(self) -> None:
        lakebase.close_pools()
        lakebase._TOKENS.clear()

    def test_token_is_cached_between_connections(self) -> None:
        calls: list[str] = []
        client = SimpleNamespace(
            postgres=SimpleNamespace(
                generate_database_credential=lambda endpoint: calls.append(endpoint) or SimpleNamespace(token="t")
            )
        )
        with patch.object(lakebase, "_workspace_client", return_value=client):
            self.assertEqual(lakebase._oauth_token("projects/p/branches/b/endpoints/e"), "t")
            self.assertEqual(lakebase._oauth_token("projects/p/branches/b/endpoints/e"), "t")
        self.assertEqual(len(calls), 1)

    def test_pool_is_shared_and_lets_compute_scale_to_zero(self) -> None:
        created: list[dict] = []

        class FakePool:
            check_connection = staticmethod(lambda conn: None)

            def __init__(self, **kwargs: object) -> None:
                created.append(kwargs)

            def close(self) -> None:
                pass

        env = {"PGHOST": "h", "PGDATABASE": "d", "PGUSER": "u", "PGPASSWORD": "p"}
        config = SimpleNamespace(lakebase_endpoint_name="")
        with patch.dict("os.environ", env), patch.object(lakebase, "_pool_class", return_value=FakePool):
            first = lakebase._pool_for(config)
            second = lakebase._pool_for(config)
        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["min_size"], 0)
        self.assertEqual(created[0]["kwargs"]["host"], "h")


class PrepareBundleTests(unittest.TestCase):
    def test_unconfigured_bindings_are_detected(self) -> None:
        spec = importlib.util.spec_from_file_location("prepare_bundle", ROOT / "scripts" / "prepare_bundle.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        app = {
            "resources": [
                {"name": "sql-warehouse", "sql_warehouse": {"id": "abc", "permission": "CAN_USE"}},
                {"name": "genie", "genie_space": {"name": "Room", "space_id": "not-configured", "permission": "CAN_RUN"}},
                {"name": "lakebase", "postgres": {"branch": "not-configured", "database": "x", "permission": "CAN_CONNECT_AND_CREATE"}},
                {"name": "ai", "serving_endpoint": {"name": "", "permission": "CAN_QUERY"}},
            ]
        }
        self.assertEqual(module._unconfigured_app_resources(app), {"genie", "lakebase", "ai"})


if __name__ == "__main__":
    unittest.main()
