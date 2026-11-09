from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import patch


def _load_runtime_app():
    try:
        import runtime_app as module

        return module
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "fastapi",
            "fastapi.responses",
            "fastapi.staticfiles",
            "pydantic",
        }:
            raise

    fastapi = ModuleType("fastapi")

    class _FastAPI:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def middleware(self, _name):
            def decorator(func):
                return func

            return decorator

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def exception_handler(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def mount(self, *args, **kwargs):
            return None

        def include_router(self, *args, **kwargs):
            return None

        def __getattr__(self, name):
            if name in {"get", "post", "put", "patch", "delete", "options", "head"}:
                return self.get
            raise AttributeError(name)

    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _APIRouter:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def add_api_route(self, *args, **kwargs):
            return None

        def __getattr__(self, name):
            if name in {"get", "post", "put", "patch", "delete", "options", "head"}:
                return lambda *args, **kwargs: lambda func: func
            raise AttributeError(name)

    def _query(*args, **kwargs):
        if args:
            return args[0]
        return kwargs.get("default")

    class _Request:
        headers = {}

    fastapi.FastAPI = _FastAPI
    fastapi.APIRouter = _APIRouter
    fastapi.HTTPException = _HTTPException
    fastapi.Query = _query
    fastapi.Request = _Request

    responses = ModuleType("fastapi.responses")

    class _HTMLResponse:
        def __init__(self, content="", status_code=200):
            self.content = content
            self.status_code = status_code
            self.headers = {}

    class _JSONResponse(_HTMLResponse):
        pass

    responses.HTMLResponse = _HTMLResponse
    responses.JSONResponse = _JSONResponse

    staticfiles = ModuleType("fastapi.staticfiles")

    class _StaticFiles:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    staticfiles.StaticFiles = _StaticFiles

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses
    sys.modules["fastapi.staticfiles"] = staticfiles

    pydantic = ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, *args, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def _field(default=None, **kwargs):
        return default

    def _field_validator(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    pydantic.BaseModel = _BaseModel
    pydantic.Field = _field
    pydantic.field_validator = _field_validator

    sys.modules["pydantic"] = pydantic

    import runtime_app as module

    return module


runtime_app = _load_runtime_app()


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_runtime_diagnostics_payload_includes_setup_checks_and_feature_flags(
        self,
    ) -> None:
        config = SimpleNamespace(
            build_id="build-123",
            diagnostics_enabled=False,
            slow_request_ms=2400,
            warehouse_id="warehouse-1",
            gov_catalog="main",
            gov_schema="gov",
        )
        capabilities = {
            "systemInventoryRead": {
                "state": "available",
                "available": True,
                "reason": "",
            },
            "tableLineage": {
                "state": "unknown",
                "available": False,
                "reason": "No lineage-observed catalogs are detected yet.",
            },
            "workloadVisibility": {
                "state": "unavailable",
                "available": False,
                "reason": "Query history is not shared in this workspace.",
            },
            "exportAllowed": {
                "state": "unavailable",
                "available": False,
                "reason": "Export is disabled until authenticated delivery is implemented.",
            },
        }

        with patch.object(runtime_app, "_config", return_value=config):
            payload = runtime_app._runtime_diagnostics_payload(
                None,
                runtime_status={
                    "state": "live",
                    "message": "",
                    "client": {
                        "authMode": "oauth-m2m-env",
                        "authType": "oauth-m2m",
                        "hostPresent": True,
                    },
                },
                store_status={"state": "live", "message": ""},
                summary={
                    "visibleAssets": 7,
                    "availableCatalogCount": 3,
                    "observedCatalogCount": 2,
                },
                capabilities=capabilities,
                boot_message="Workspace connected, but no visible assets were returned yet.",
            )

        self.assertEqual(payload["buildId"], "build-123")
        self.assertFalse(payload["diagnosticsEnabled"])
        self.assertEqual(payload["slowRequestMs"], 2400)
        self.assertEqual(payload["httpRequestId"], "")
        self.assertIsInstance(payload["featureFlags"], list)
        self.assertGreaterEqual(len(payload["featureFlags"]), 6)
        flag_keys = {item["key"] for item in payload["featureFlags"]}
        self.assertIn("workspace_setup_diagnostics", flag_keys)
        self.assertIn("query_history_surface", flag_keys)
        self.assertIn("background_work_plane", flag_keys)
        flag_map = {item["key"]: item for item in payload["featureFlags"]}
        self.assertIn("summary", flag_map["workspace_setup_diagnostics"])
        self.assertIn("reason", flag_map["workspace_setup_diagnostics"])
        self.assertIn("disabledReason", flag_map["workspace_setup_diagnostics"])
        self.assertIn("unavailableReason", flag_map["workspace_setup_diagnostics"])
        self.assertIn("reason", flag_map["query_history_surface"])
        self.assertIn("disabledReason", flag_map["query_history_surface"])
        self.assertEqual(
            flag_map["query_history_surface"]["safeSharingPath"]["state"], "unavailable"
        )
        self.assertEqual(payload["auth"]["mode"], "no-identity")
        self.assertEqual(payload["auth"]["visibilityScope"], "anonymous-app-principal")
        self.assertIn("serverTiming", payload["headers"])
        self.assertIn("setupSummary", payload)
        self.assertIn("setupReadiness", payload)
        self.assertIn("setupSequence", payload)
        self.assertIn("workspaceAccess", payload)
        self.assertEqual(payload["setupReadiness"]["state"], "attention_required")
        # OBO-deferred checks no longer drive the top-line nextStep; background_work_plane
        # is the first operational attention item in the no-identity fixture.
        self.assertEqual(payload["setupReadiness"]["nextStep"], "background_work_plane")
        self.assertTrue(payload["setupSequence"])
        self.assertEqual(payload["workspaceAccess"]["mode"], "no-identity")
        self.assertEqual(
            payload["workspaceAccess"]["visibilityScope"], "anonymous-app-principal"
        )
        self.assertTrue(payload["workspaceAccess"]["canUseDiscovery"])
        self.assertTrue(payload["workspaceAccess"]["canUseEntityMetadata"])
        self.assertFalse(payload["workspaceAccess"]["canUseAssetPreview"])
        self.assertFalse(payload["workspaceAccess"]["canUseLineage"])
        self.assertFalse(payload["workspaceAccess"]["canUseQueryHistory"])
        self.assertEqual(
            payload["workspaceAccess"]["queryHistorySharingPath"]["state"],
            "unavailable",
        )
        self.assertIn(
            "Queries, usage, and workloads",
            payload["workspaceAccess"]["blockedSurfaces"],
        )
        self.assertEqual(
            payload["workspaceAccess"]["transactionMode"]["state"], "degraded"
        )

        checks = {check["key"]: check for check in payload["setupChecks"]}
        self.assertIn("warehouse_runtime", checks)
        self.assertIn("governance_store", checks)
        self.assertIn("system_inventory", checks)
        self.assertIn("table_lineage", checks)
        self.assertIn("app_service_principal", checks)
        self.assertIn("workload_visibility", checks)
        self.assertIn("classification_recommendations", checks)
        self.assertEqual(checks["warehouse_runtime"]["state"], "available")
        self.assertEqual(checks["system_inventory"]["state"], "available")
        self.assertEqual(checks["app_service_principal"]["state"], "available")
        self.assertEqual(checks["table_lineage"]["state"], "unknown")
        self.assertEqual(checks["workload_visibility"]["state"], "unavailable")
        self.assertEqual(
            checks["workload_visibility"]["safeSharingPath"]["state"], "unavailable"
        )
        self.assertTrue(checks["classification_recommendations"]["remediation"])
        claim_surfaces = {
            item["surface"] for item in payload["setupReadiness"]["claimNarrowing"]
        }
        self.assertIn("Queries, usage, and workloads", claim_surfaces)
        self.assertEqual(
            payload["bootMessage"],
            "Workspace connected, but no visible assets were returned yet.",
        )

    def test_runtime_diagnostics_payload_reuses_one_setup_snapshot(self) -> None:
        config = SimpleNamespace(
            build_id="build-456",
            diagnostics_enabled=True,
            slow_request_ms=1800,
            warehouse_id="warehouse-2",
            gov_catalog="main",
            gov_schema="gov",
        )
        setup_snapshot = {
            "observedAt": "2026-04-14T22:10:00Z",
            "staleAfter": "2026-04-14T22:11:00Z",
            "summary": {
                "availableCount": 1,
                "degradedCount": 0,
                "unavailableCount": 0,
                "unknownCount": 0,
                "ready": True,
            },
            "readiness": {
                "state": "ready",
                "canRerun": True,
                "blockedBy": [],
                "attentionBy": [],
                "claimNarrowing": [],
                "retriable": True,
                "nextStep": "complete",
            },
            "setupSequence": [
                {
                    "key": "environment_config",
                    "label": "Environment configuration",
                    "state": "available",
                    "summary": "Required deployment settings are present.",
                },
            ],
            "checks": [
                {
                    "key": "warehouse_runtime",
                    "label": "Warehouse runtime",
                    "state": "available",
                    "summary": "The live metadata runtime is reachable.",
                    "observedAt": "2026-04-14T22:10:00Z",
                    "staleAfter": "2026-04-14T22:11:00Z",
                },
            ],
            "workspaceAccess": {
                "mode": "app-principal-only",
                "visibilityScope": "workspace-app-principal",
                "canUseDiscovery": True,
                "canUseEntityMetadata": True,
                "canWriteGovernance": True,
                "canUseAssetPreview": False,
                "canUseLineage": False,
                "canUseQueryHistory": False,
                "canExport": False,
                "canRunBackgroundWork": False,
                "canUseClassificationRecommendations": False,
                "transactionMode": {
                    "state": "degraded",
                    "summary": "Fallback-only mutation ordering is active.",
                    "reason": "Transaction eligibility has not been proven yet.",
                },
                "blockedSurfaces": ["Discovery and detail export"],
                "gates": [
                    {
                        "key": "governance_writes",
                        "label": "Governance writes",
                        "state": "available",
                        "reason": "The current actor can perform governed writes.",
                        "proofSource": "shared setup snapshot",
                        "blockedSurfaces": [],
                    },
                ],
                "observedAt": "2026-04-14T22:10:00Z",
                "staleAfter": "2026-04-14T22:11:00Z",
            },
            "featureFlags": [
                {
                    "key": "workspace_setup_diagnostics",
                    "label": "Workspace setup diagnostics",
                    "state": "available",
                    "enabled": True,
                },
            ],
            "auth": {
                "mode": "app-principal-only",
                "actorRole": "admin",
                "visibilityScope": "workspace-app-principal",
                "perUserAuthorization": {
                    "implemented": False,
                    "state": "unavailable",
                    "reason": "OBO is not implemented yet.",
                },
            },
        }

        with (
            patch.object(runtime_app, "_config", return_value=config),
            patch.object(
                runtime_app.runtime_setup_service,
                "setup_payload",
                return_value=setup_snapshot,
            ) as setup_payload,
        ):
            payload = runtime_app._runtime_diagnostics_payload(
                None,
                runtime_status={"state": "live", "message": ""},
                store_status={"state": "live", "message": ""},
                summary={},
                capabilities={},
                boot_message="",
            )

        self.assertEqual(setup_payload.call_count, 1)
        self.assertEqual(payload["observedAt"], "2026-04-14T22:10:00Z")
        self.assertEqual(payload["setupChecks"], setup_snapshot["checks"])
        self.assertEqual(payload["setupSequence"], setup_snapshot["setupSequence"])
        self.assertEqual(payload["workspaceAccess"], setup_snapshot["workspaceAccess"])


class RuntimeDiagnosticsWiringTests(unittest.TestCase):
    def test_runtime_status_payload_calls_shared_diagnostics_helper(self) -> None:
        source = Path("axiom/api/runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename="axiom/api/runtime.py")

        runtime_status_node = next(
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef)
            and item.name == "_api_runtime_status_response"
        )
        runtime_status_segment = (
            ast.get_source_segment(source, runtime_status_node) or ""
        )
        self.assertIn("_runtime_diagnostics_payload(", runtime_status_segment)

        bootstrap_node = next(
            item
            for item in tree.body
            if isinstance(item, ast.FunctionDef)
            and item.name == "_api_bootstrap_response"
        )
        bootstrap_segment = ast.get_source_segment(source, bootstrap_node) or ""
        self.assertNotIn("_runtime_diagnostics_payload(", bootstrap_segment)


if __name__ == "__main__":
    unittest.main()
