from __future__ import annotations

import sys
import unittest
from types import ModuleType
from unittest.mock import patch


def _load_admin_module():
    try:
        from axiom.api import admin as module

        return module
    except ModuleNotFoundError as exc:
        if exc.name not in {"fastapi", "fastapi.responses"}:
            raise

    fastapi = ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.routes = []

        def add_api_route(self, *args, **kwargs):
            return None

        def __getattr__(self, name):
            if name in {"get", "post", "put", "patch", "delete", "options", "head"}:
                def decorator(*args, **kwargs):
                    def wrap(func):
                        self.routes.append(func)
                        return func

                    return wrap

                return decorator
            raise AttributeError(name)

    fastapi.APIRouter = _APIRouter

    responses = ModuleType("fastapi.responses")

    class _JSONResponse:
        def __init__(self, content=None, status_code=200):
            self.content = content
            self.status_code = status_code
            self.headers = {}

        def json(self):
            return self.content

    responses.JSONResponse = _JSONResponse

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses

    from axiom.api import admin as module  # type: ignore

    return module


admin = _load_admin_module()


class AdminBackgroundStatusTests(unittest.TestCase):
    def test_running_drainer_returns_available_envelope(self) -> None:
        snapshot = {
            "running": True,
            "lastDrainAt": "2026-04-20T12:00:00Z",
            "processedTotal": 12,
            "lastError": None,
        }

        with patch.object(
            admin, "_background_drainer_snapshot", return_value=snapshot, create=True
        ):
            # _background_drainer_snapshot lives in runtime_app. Patch the
            # lazy import by stubbing the runtime_app module in sys.modules.
            pass

        # Replace the lazy runtime_app import target with our fake so the
        # route reads the snapshot from our patched function.
        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._background_drainer_snapshot = lambda: snapshot
        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}):
            payload = admin._background_status_payload()

        self.assertIn("data", payload)
        self.assertIn("meta", payload)
        drainer = payload["data"]["drainer"]
        self.assertEqual(drainer["running"], True)
        self.assertEqual(drainer["lastDrainAt"], "2026-04-20T12:00:00Z")
        self.assertEqual(drainer["processedTotal"], 12)
        self.assertIsNone(drainer["lastError"])
        self.assertIsNone(payload["data"]["queue"]["depthHint"])
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertEqual(payload["meta"]["reason"], "")

    def test_stopped_drainer_returns_degraded_envelope(self) -> None:
        snapshot = {
            "running": False,
            "lastDrainAt": None,
            "processedTotal": 0,
            "lastError": None,
        }
        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._background_drainer_snapshot = lambda: snapshot
        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}):
            payload = admin._background_status_payload()

        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertIn("not currently running", payload["meta"]["reason"])
        self.assertFalse(payload["data"]["drainer"]["running"])

    def test_drainer_error_surfaces_in_meta(self) -> None:
        snapshot = {
            "running": True,
            "lastDrainAt": "2026-04-20T12:00:00Z",
            "processedTotal": 3,
            "lastError": "RuntimeError: store unavailable",
        }
        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._background_drainer_snapshot = lambda: snapshot
        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}):
            payload = admin._background_status_payload()

        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertIn(
            "store unavailable",
            payload["meta"]["reason"],
        )
        self.assertEqual(
            payload["data"]["drainer"]["lastError"],
            "RuntimeError: store unavailable",
        )

    def test_router_registers_background_status_route(self) -> None:
        router = admin.build_admin_router()
        # The fake APIRouter stores route callables in self.routes when
        # tests run without fastapi installed. With real fastapi, the
        # router has `.routes`. Either way the endpoint must be reachable.
        if hasattr(router, "routes") and router.routes:
            paths = []
            for route in router.routes:
                path = getattr(route, "path", None)
                if path:
                    paths.append(path)
            self.assertIn("/api/admin/background/status", paths)


class _FakeUC:
    """Minimal stand-in for UCSQLClient used by the truth-check tests."""

    def __init__(self, results):
        # results: dict mapping a substring of the SQL to a pandas DataFrame.
        import pandas as pd  # local import to keep top-level import optional
        self._pd = pd
        self._results = results
        self.calls = []

    def query_df(self, sql, **_kwargs):
        self.calls.append(sql)
        for needle, df in self._results.items():
            if needle in sql:
                return df
        return self._pd.DataFrame()


class TruthCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reset the in-process truth-check cache so each test produces a
        # fresh payload from its fakes.
        admin._TRUTH_CACHE.clear()

    def test_payload_aggregates_per_catalog_and_drift(self) -> None:
        import pandas as pd

        catalogs_df = pd.DataFrame([{"catalog_count": 12}])
        schemas_df = pd.DataFrame(
            [
                {"catalog": "emet", "schema_count": 5},
                {"catalog": "finance_prod", "schema_count": 3},
            ]
        )
        tables_df = pd.DataFrame(
            [
                {"catalog": "emet", "table_count": 200},
                {"catalog": "finance_prod", "table_count": 40},
            ]
        )
        fake_uc = _FakeUC({
            "system.information_schema.catalogs": catalogs_df,
            "system.information_schema.schemata": schemas_df,
            "system.information_schema.tables": tables_df,
        })

        # Build a fake runtime_app exposing _uc that returns our FakeUC.
        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._uc = lambda: fake_uc
        fake_runtime_app._store = lambda: None
        fake_runtime_app._user_role_slug = lambda _request: "admin"

        # Patch the real axiom.services.assets module so the lazy import
        # inside _ui_inventory_counts picks up our deterministic fixtures.
        from axiom.services import assets as real_assets
        inventory_df = pd.DataFrame(
            [{"table_catalog": "emet"} for _ in range(198)]
            + [{"table_catalog": "finance_prod"} for _ in range(40)]
        )
        visible_df = pd.DataFrame(
            [{"table_catalog": "emet"} for _ in range(195)]
            + [{"table_catalog": "finance_prod"} for _ in range(40)]
        )

        env = {
            "AXIOM_DISCOVERY_CATALOGS": "emet,finance_prod",
        }

        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}), patch.dict(
            "os.environ", env, clear=False
        ), patch.object(
            real_assets, "inventory", lambda *_a, **_k: inventory_df
        ), patch.object(
            real_assets, "visible_assets", lambda _df, **_k: visible_df
        ):
            payload = admin._build_truth_check_payload()

        self.assertIn("data", payload)
        data = payload["data"]
        self.assertEqual(data["discoveryCatalogs"], ["emet", "finance_prod"])
        self.assertEqual(data["metastore"]["catalogTotal"], 12)
        self.assertEqual(data["metastore"]["schemaTotalForDiscovery"], 8)
        self.assertEqual(data["metastore"]["tableTotalForDiscovery"], 240)
        self.assertEqual(data["ui"]["inventoryTotal"], 238)
        self.assertEqual(data["ui"]["visibleTotal"], 235)
        # Drift = metastore tables - ui inventory = 240 - 238 = 2
        self.assertEqual(data["drift"]["inventoryDelta"], 2)
        # hiddenByVisibility = ui inventory - ui visible = 238 - 235 = 3
        self.assertEqual(data["drift"]["hiddenByVisibility"], 3)
        # Per-catalog breakdown contains both discovery catalogs.
        catalogs = {entry["catalog"]: entry for entry in data["metastore"]["perCatalog"]}
        self.assertIn("emet", catalogs)
        self.assertEqual(catalogs["emet"]["metastore"]["tableCount"], 200)
        self.assertEqual(catalogs["emet"]["ui"]["inventoryAssetCount"], 198)
        self.assertEqual(catalogs["emet"]["drift"]["inventoryDelta"], 2)
        self.assertTrue(catalogs["emet"]["configured"])
        # Queries collection is non-empty with no errors.
        self.assertGreaterEqual(len(data["queries"]), 3)
        self.assertTrue(all(q["error"] is None for q in data["queries"]))
        self.assertEqual(payload["meta"]["state"], "available")

    def test_query_failure_marks_state_degraded(self) -> None:
        import pandas as pd

        class _FailingUC:
            def query_df(self, sql, **_kwargs):
                raise RuntimeError("warehouse unreachable")

        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._uc = lambda: _FailingUC()
        fake_runtime_app._store = lambda: None
        fake_runtime_app._user_role_slug = lambda _request: "admin"

        from axiom.services import assets as real_assets

        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}), patch.dict(
            "os.environ", {"AXIOM_DISCOVERY_CATALOGS": "emet"}, clear=False
        ), patch.object(
            real_assets, "inventory", lambda *_a, **_k: pd.DataFrame()
        ), patch.object(
            real_assets, "visible_assets", lambda _df, **_k: pd.DataFrame()
        ):
            payload = admin._build_truth_check_payload()

        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertIn("warehouse unreachable", payload["meta"]["reason"])
        self.assertGreater(len(payload["data"]["drift"]["warnings"]), 0)
        # All probes still surface so the operator can see what failed.
        self.assertGreaterEqual(len(payload["data"]["queries"]), 3)

    def test_router_registers_truth_check_route(self) -> None:
        router = admin.build_admin_router()
        if hasattr(router, "routes") and router.routes:
            paths = []
            for route in router.routes:
                path = getattr(route, "path", None)
                if path:
                    paths.append(path)
            self.assertIn("/api/admin/truth-check", paths)


if __name__ == "__main__":
    unittest.main()
