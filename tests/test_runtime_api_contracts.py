from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_runtime_api_openapi_snapshot.py"
SNAPSHOT_PATH = ROOT / "docs" / "runtime_api_openapi_snapshot.json"


def _load_snapshot_script():
    spec = importlib.util.spec_from_file_location(
        "generate_runtime_api_openapi_snapshot",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load runtime API snapshot script.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_script = _load_snapshot_script()

from fastapi.responses import JSONResponse  # noqa: E402
from atlas.api import response as _response_api  # noqa: E402
from atlas.api.runtime import build_runtime_router  # noqa: E402


def _response_json(response) -> dict[str, object]:
    if hasattr(response, "body"):
        return json.loads(response.body.decode("utf-8"))
    return response.content


class RuntimeApiContractsTests(unittest.TestCase):
    def test_in_memory_role_lookup_honors_configured_admin_emails(self) -> None:
        runtime_app = snapshot_script.runtime_app
        store = runtime_app._NullGovernanceStore()

        self.assertEqual(
            store.get_role("skyler@entrada.ai", admin_emails=["skyler@entrada.ai"]),
            "admin",
        )
        self.assertEqual(
            store.get_role("reader@entrada.ai", admin_emails=["skyler@entrada.ai"]),
            "reader",
        )

    def test_shell_payload_pins_minimal_shell_contract(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _route_context=lambda _request: {
                "surface": "entity",
                "asset": "main.sales.orders",
                "query": "",
            },
            _build_id=lambda: "build-123",
            _config=lambda: SimpleNamespace(
                build_id="build-123",
                diagnostics_enabled=True,
                admin_emails=[],
                warehouse_id="warehouse-123",
                gov_catalog="datapact",
                gov_schema="atlas",
                environment_label="Dev - DEFAULT",
                deploy_target="Dev",
                workspace_host="https://example.cloud.databricks.com",
            ),
        ):
            payload = runtime_app._shell_payload(
                request,
                mode="inline-shell",
                state="loading",
                message="Preparing the workspace shell.",
            )

        self.assertEqual(payload["bootstrapContract"]["version"], "bootstrap-v3")
        self.assertEqual(payload["bootstrapContract"]["class"], "shell-capability")
        self.assertEqual(payload["bootstrapContract"]["mode"], "inline-shell")
        self.assertNotIn("assets", payload)
        self.assertNotIn("assetIndex", payload)
        self.assertNotIn("diagnostics", payload)
        self.assertNotIn("summary", payload["discovery"])
        self.assertEqual(payload["routeHints"]["surface"], "entity")
        self.assertEqual(payload["routeHints"]["asset"], "main.sales.orders")
        self.assertEqual(payload["apiContract"]["bootstrap"], "/api/bootstrap")
        self.assertEqual(payload["apiContract"]["commandCenter"], "/api/atlas/command-center")
        self.assertEqual(payload["apiContract"]["asset360"], "/api/atlas/assets/{asset_fqn}/360")
        self.assertEqual(
            payload["apiContract"]["governanceWorkbench"],
            "/api/atlas/governance/workbench",
        )
        self.assertEqual(payload["apiContract"]["insightsDashboard"], "/api/atlas/insights")
        self.assertEqual(payload["apiContract"]["cdeDashboard"], "/api/atlas/cde")
        self.assertEqual(payload["apiContract"]["cdeDetail"], "/api/atlas/cde/{cde_id}")
        self.assertEqual(
            payload["apiContract"]["atlasAiRecommendations"],
            "/api/atlas-ai/recommendations",
        )
        self.assertEqual(payload["shell"]["buildId"], "build-123")
        self.assertEqual(payload["shell"]["environment"]["label"], "Dev - DEFAULT")
        self.assertEqual(payload["shell"]["environment"]["displayLabel"], "Dev · datapact.atlas")
        self.assertEqual(payload["shell"]["environment"]["target"], "Dev")
        self.assertEqual(payload["shell"]["environment"]["catalog"], "datapact")
        self.assertEqual(payload["shell"]["environment"]["schema"], "atlas")
        self.assertEqual(payload["shell"]["environment"]["warehouseId"], "warehouse-123")
        self.assertEqual(payload["shell"]["workspaceHost"], "https://example.cloud.databricks.com")
        self.assertEqual(
            payload["shell"]["product"],
            {
                "companyName": "Entrada",
                "productName": "Governance Atlas",
                "shortName": "Atlas",
                "aiName": "Atlas AI",
            },
        )
        flag_keys = {item["key"] for item in payload["featureFlags"]}
        self.assertIn("workspace_setup_diagnostics", flag_keys)
        self.assertIn("table_lineage_surface", flag_keys)
        self.assertIn("query_history_surface", flag_keys)

    def test_shell_payload_uses_fast_cached_summary_without_discovery_search(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        discovery_called = False

        def fail_if_discovery_search_runs(_request, **_kwargs):
            nonlocal discovery_called
            discovery_called = True
            raise AssertionError("bootstrap must not run a blocking discovery search")

        with patch.multiple(
            runtime_app,
            _route_context=lambda _request: {
                "surface": "discovery",
                "asset": "",
                "query": "",
            },
            _build_id=lambda: "build-123",
            _discovery_search_payload=fail_if_discovery_search_runs,
            _fast_bootstrap_inventory_summary=lambda _scope, start_background=True: {
                "visibleAssets": 12,
                "availableCatalogCount": 3,
                "observedCatalogCount": 2,
            },
            _config=lambda: SimpleNamespace(
                build_id="build-123",
                diagnostics_enabled=True,
                admin_emails=[],
                warehouse_id="warehouse-123",
                gov_catalog="datapact",
                gov_schema="atlas",
                environment_label="Dev - DEFAULT",
                deploy_target="Dev",
                workspace_host="https://example.cloud.databricks.com",
            ),
        ):
            payload = runtime_app._shell_payload(
                request,
                mode="route-bootstrap",
                state="live",
                message="",
                runtime_status={"state": "live", "message": ""},
            )

        self.assertFalse(discovery_called)
        self.assertNotEqual(payload["discovery"].get("defaultCount"), 12)
        self.assertEqual(payload["capabilities"]["systemInventoryRead"]["state"], "available")
        self.assertTrue(payload["capabilities"]["systemInventoryRead"]["available"])
        self.assertEqual(payload["capabilities"]["tableLineage"]["state"], "available")
        feature_flags = {item["key"]: item for item in payload["featureFlags"]}
        self.assertTrue(feature_flags["table_lineage_surface"]["enabled"])

    def test_api_bootstrap_response_returns_route_bootstrap_shell_only(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _uc_runtime_status=lambda: {"state": "live", "message": ""},
            _uc_runtime_status_fast=lambda background=True: {
                "state": "live",
                "message": "",
            },
            _route_context=lambda _request: {
                "surface": "discovery",
                "asset": "",
                "query": "",
            },
            _build_id=lambda: "build-123",
            _config=lambda: SimpleNamespace(
                diagnostics_enabled=True,
                admin_emails=[],
                warehouse_id="warehouse-123",
                gov_catalog="datapact",
                gov_schema="atlas",
                environment_label="Dev - DEFAULT",
                deploy_target="Dev",
                workspace_host="https://example.cloud.databricks.com",
            ),
        ):
            response = runtime_app._api_bootstrap_response(request)

        payload = _response_json(response)
        self.assertEqual(payload["bootstrapContract"]["mode"], "route-bootstrap")
        self.assertEqual(payload["bootState"], "live")
        self.assertNotIn("assets", payload)
        self.assertNotIn("assetIndex", payload)
        self.assertNotIn("diagnostics", payload)
        self.assertEqual(payload["apiContract"]["runtimeStatus"], "/api/runtime/status")
        self.assertEqual(payload["apiContract"]["adminControlCenter"], "/api/atlas/admin/control-center")

    def test_unavailable_bootstrap_payload_preserves_minimal_contract(self) -> None:
        runtime_app = snapshot_script.runtime_app

        with patch.multiple(
            runtime_app,
            _build_id=lambda: "build-123",
            _config=lambda: SimpleNamespace(
                diagnostics_enabled=False,
                admin_emails=[],
                warehouse_id="",
                gov_catalog="",
                gov_schema="",
                environment_label="",
                deploy_target="",
                workspace_host="",
            ),
        ):
            payload = runtime_app._bootstrap_unavailable_payload(
                None, "Warehouse unavailable."
            )

        self.assertEqual(payload["bootstrapContract"]["version"], "bootstrap-v3")
        self.assertEqual(payload["bootstrapContract"]["mode"], "bootstrap-unavailable")
        self.assertEqual(payload["bootState"], "unavailable")
        self.assertEqual(payload["bootMessage"], "Warehouse unavailable.")
        self.assertNotIn("assets", payload)
        self.assertNotIn("assetIndex", payload)
        self.assertNotIn("diagnostics", payload)
        self.assertNotIn("summary", payload["discovery"])
        self.assertEqual(payload["apiContract"]["bootstrap"], "/api/bootstrap")
        self.assertEqual(payload["apiContract"]["auditEvidence"], "/api/atlas/audit/evidence")

    def test_request_obo_token_reads_forwarded_access_token_header(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={"x-forwarded-access-token": "obo-token-abc"})
        self.assertEqual(runtime_app._request_obo_token(request), "obo-token-abc")

    def test_user_display_name_prefers_display_header(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-user": "5882225431657870",
                "x-forwarded-email": "skyler@entrada.ai",
                "x-forwarded-display-name": "Skyler Kohler",
            }
        )

        self.assertEqual(runtime_app._user_display_name(request), "Skyler Kohler")

    def test_user_display_name_falls_back_to_email_over_opaque_user_id(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-user": "5882225431657870",
                "x-forwarded-email": "skyler@entrada.ai",
            }
        )

        self.assertEqual(runtime_app._user_display_name(request), "skyler@entrada.ai")

    def test_runtime_diagnostics_headers_use_govat_names(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={"X-GOVAT-Client-Request-ID": "govat-request-id"},
            state=SimpleNamespace(),
        )

        self.assertEqual(runtime_app._http_request_id(request), "govat-request-id")
        self.assertEqual(
            runtime_app.CLIENT_REQUEST_ID_HEADER,
            "X-GOVAT-Client-Request-ID",
        )
        self.assertEqual(runtime_app.BUILD_ID_HEADER, "X-GOVAT-Build-ID")
        self.assertEqual(runtime_app.DURATION_HEADER, "X-GOVAT-Request-Duration-Ms")

    def test_request_auth_mode_flips_to_obo_when_token_forwarded(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "user@example.com",
                "x-forwarded-access-token": "obo-token-xyz",
            }
        )
        self.assertEqual(
            runtime_app._request_auth_mode(request),
            "obo-available",
        )

    def test_request_auth_mode_stays_app_principal_without_token(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={"x-forwarded-email": "user@example.com"})
        self.assertEqual(
            runtime_app._request_auth_mode(request),
            "app-principal-only",
        )

    def test_runtime_app_routes_delegate_to_runtime_helpers(self) -> None:
        from atlas.api import runtime as _runtime_api

        runtime_app = snapshot_script.runtime_app
        routes = {
            route.path: route
            for route in snapshot_script.iter_api_routes(runtime_app.app)
            if route.path in snapshot_script.RUNTIME_PATHS
        }
        request = object()

        with patch.object(
            _runtime_api,
            "_api_bootstrap_response",
            return_value=JSONResponse({"ok": "bootstrap"}),
        ) as bootstrap_patch:
            response = routes["/api/bootstrap"].endpoint(request)
        bootstrap_patch.assert_called_once_with(request)
        self.assertEqual(_response_json(response), {"ok": "bootstrap"})

        with patch.object(
            _runtime_api,
            "_api_runtime_status_response",
            return_value=JSONResponse({"ok": "runtime_status"}),
        ) as runtime_status_patch:
            response = routes["/api/runtime/status"].endpoint(request)
        runtime_status_patch.assert_called_once_with(request)
        self.assertEqual(_response_json(response), {"ok": "runtime_status"})

    def test_runtime_status_opens_lineage_surface_when_visible_assets_exist_without_edges(self) -> None:
        from atlas.api import runtime as _runtime_api

        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "skyler@entrada.ai",
                "x-forwarded-user": "skyler@entrada.ai",
                "x-forwarded-display-name": "Skyler Myers",
                "x-forwarded-access-token": "obo-token-live",
            }
        )

        with patch.multiple(
            runtime_app,
            _uc_runtime_status_fast=lambda: {
                "state": "live",
                "message": "",
                "client": {
                    "authMode": "oauth-m2m-env",
                    "authType": "oauth-m2m",
                    "hostPresent": True,
                },
            },
            _store_status_fast=lambda: {"state": "live", "message": ""},
            _fast_bootstrap_inventory_summary=lambda _scope: {
                "visibleAssets": 7,
                "availableCatalogCount": 3,
                "observedCatalogCount": 0,
            },
            _request_cache_scope=lambda _request: "skyler@entrada.ai|obo-available",
            _user_role_slug=lambda _request: "admin",
            _config=lambda: SimpleNamespace(
                build_id="build-123",
                diagnostics_enabled=True,
                admin_emails=[],
                warehouse_id="warehouse-123",
                gov_catalog="datapact",
                gov_schema="atlas",
                environment_label="Dev - DEFAULT",
                deploy_target="Dev",
                workspace_host="https://example.cloud.databricks.com",
                slow_request_ms=2500,
            ),
            _user_role=lambda _request: "Admin",
        ):
            response = _runtime_api._api_runtime_status_response(request)

        payload = _response_json(response)
        lineage_capability = payload["capabilities"]["tableLineage"]
        diagnostics = payload["diagnostics"]
        flags = {
            item["key"]: item
            for item in diagnostics["featureFlags"]
        }

        self.assertEqual(lineage_capability["state"], "available")
        self.assertTrue(lineage_capability["available"])
        self.assertIn("empty graph", lineage_capability["reason"])
        self.assertTrue(diagnostics["workspaceAccess"]["canUseLineage"])
        self.assertTrue(flags["table_lineage_surface"]["enabled"])
        self.assertEqual(flags["table_lineage_surface"]["state"], "available")
        self.assertNotIn(
            "Lineage graph and drawer",
            diagnostics["workspaceAccess"]["blockedSurfaces"],
        )

    def test_runtime_api_openapi_snapshot_matches_committed_contract(self) -> None:
        expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        observed = snapshot_script.build_runtime_api_snapshot()

        self.assertEqual(expected, observed)
        self.assertEqual(set(observed["paths"]), set(snapshot_script.RUNTIME_PATHS))

    def test_asset_availability_meta_degrades_without_obo(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "app-principal-only",
            _asset_visibility_record=lambda *_args, **_kwargs: {
                "visible": True,
                "exists": True,
                "openable": True,
                "visibilityState": "visible",
            },
        ), patch.object(
            _response_api,
            "_request_auth_mode",
            lambda _request: "app-principal-only",
        ):
            payload = runtime_app._asset_availability_payload(
                ["main.sales.orders"], request
            )

        self.assertFalse(payload["meta"]["authoritative"])
        self.assertTrue(payload["meta"]["degraded"])
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertEqual(payload["meta"]["visibilityScope"], "workspace-app-principal")
        self.assertFalse(payload["meta"]["capabilities"]["separatesExistsFromVisible"])

    def test_asset_detail_unknown_visibility_returns_canonical_error_payload(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _asset_visibility_record=lambda *_args, **_kwargs: {
                "visible": False,
                "exists": False,
                "openable": False,
                "visibilityState": "unknown",
                "reason": "Visibility verification failed.",
            },
        ):
            response = runtime_app.api_asset_detail(
                "main.sales.orders", request, sections=[]
            )

        payload = _response_json(response)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["detail"], "Visibility verification failed.")
        self.assertEqual(payload["meta"]["capabilities"]["visibilityState"], "unknown")
        self.assertEqual(payload["meta"]["state"], "unknown")
        self.assertEqual(
            payload["errors"][0]["message"], "Visibility verification failed."
        )

    def test_asset_availability_fails_closed_without_actor_scoped_visibility_proof(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "app-principal-only",
            _asset_is_visible=lambda *_args, **_kwargs: False,
            _asset_exists=lambda *_args, **_kwargs: True,
        ), patch.object(
            _response_api,
            "_request_auth_mode",
            lambda _request: "app-principal-only",
        ):
            payload = runtime_app._asset_availability_payload(
                ["main.sales.hidden_orders"], request
            )

        record = payload["assets"]["main.sales.hidden_orders"]
        self.assertFalse(record["exists"])
        self.assertFalse(record["visible"])
        self.assertFalse(record["openable"])
        self.assertEqual(record["visibilityState"], "missing")
        self.assertEqual(payload["meta"]["state"], "degraded")

    def test_direct_actor_identity_makes_deep_link_openable_when_inventory_omits_asset(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "actor-token",
            }
        )

        class FakeUC:
            def runtime_context(self):
                return {"authMode": "obo"}

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "obo-available",
            _asset_is_visible=lambda *_args, **_kwargs: False,
            _asset_exists=lambda *_args, **_kwargs: False,
            _uc_for_request=lambda _request: FakeUC(),
        ), patch.object(
            runtime_app.asset_service,
            "exact_identity_row",
            lambda *_args, **_kwargs: object(),
        ):
            record = runtime_app._asset_visibility_record(
                "main.sales.deep_link_only", request
            )

        self.assertTrue(record["exists"])
        self.assertTrue(record["visible"])
        self.assertTrue(record["openable"])
        self.assertEqual(record["visibilityState"], "visible")
        self.assertEqual(record["visibilityMethod"], "direct-identity")

    def test_direct_actor_identity_does_not_widen_when_obo_falls_back_to_app_principal(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "actor-token",
            }
        )

        class FallbackUC:
            def runtime_context(self):
                return {"obo_scope_fallback": True}

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "obo-available",
            _asset_is_visible=lambda *_args, **_kwargs: False,
            _asset_exists=lambda *_args, **_kwargs: True,
            _uc_for_request=lambda _request: FallbackUC(),
        ), patch.object(
            runtime_app.asset_service,
            "exact_identity_row",
            lambda *_args, **_kwargs: object(),
        ):
            record = runtime_app._asset_visibility_record(
                "main.sales.deep_link_only", request
            )

        self.assertTrue(record["exists"])
        self.assertFalse(record["visible"])
        self.assertFalse(record["openable"])
        self.assertEqual(record["visibilityState"], "hidden")
        self.assertEqual(record["visibilityMethod"], "inventory")

    def test_lineage_payload_uses_actor_uc_for_actor_scoped_system_lineage(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "analyst@example.com",
                "x-forwarded-access-token": "actor-token",
            }
        )
        actor_uc = object()
        app_uc = object()
        captured = {}

        def fake_lineage_payload(uc, store, asset_fqn, *, cache_scope="", system_uc=None, profile="full"):
            captured.update(
                {
                    "uc": uc,
                    "store": store,
                    "asset_fqn": asset_fqn,
                    "cache_scope": cache_scope,
                    "system_uc": system_uc,
                    "profile": profile,
                }
            )
            return {"fqn": asset_fqn}

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "obo-available",
            _uc_for_request=lambda _request: actor_uc,
            _uc=lambda: app_uc,
            _store_for_read=lambda: "store",
            _request_cache_scope=lambda _request: "actor-scope",
        ), patch.object(
            runtime_app.lineage_service,
            "lineage_payload",
            fake_lineage_payload,
        ):
            payload = runtime_app._lineage_payload("main.sales.orders", request)

        self.assertEqual(payload["fqn"], "main.sales.orders")
        self.assertIs(captured["uc"], actor_uc)
        self.assertIs(captured["system_uc"], actor_uc)
        self.assertEqual(captured["cache_scope"], "actor-scope")
        self.assertEqual(captured["profile"], "full")

    def test_invalid_discovery_query_preserves_invalid_query_payload_and_meta(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        invalid_query = {
            "state": "invalid",
            "message": "Expected a search term after OR.",
            "syntaxHint": "Finish the grouped expression before submitting the query.",
            "supportedFields": ["name", "domain"],
        }

        with (
            patch.multiple(
                runtime_app,
                _ensure_live_runtime=lambda: None,
                _discovery_search_payload=lambda **_kwargs: (_ for _ in ()).throw(
                    runtime_app.asset_service.DiscoveryQuerySyntaxError(
                        "Expected a search term after OR."
                    )
                ),
            ),
            patch.object(
                runtime_app.asset_service,
                "discovery_invalid_query_payload",
                return_value=invalid_query,
            ),
        ):
            response = runtime_app.api_discovery_search(request)

        payload = _response_json(response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["invalidQuery"], invalid_query)
        self.assertEqual(payload["detail"], "Expected a search term after OR.")
        self.assertIn("meta", payload)

    def test_governance_request_patch_rejects_hidden_asset_requests(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        mutated = {"called": False}

        class Store:
            def get_change_request(self, request_id):
                return SimpleNamespace(uc_full_name="main.sales.hidden_orders")

            def set_request_status(self, **_kwargs):
                mutated["called"] = True
                return None

        with (
            patch.multiple(
                runtime_app,
                _ensure_live_runtime=lambda: None,
                _ensure_can_approve=lambda _request: "steward@example.com",
                _user_role_slug=lambda _request: "admin",
                _store=lambda: Store(),
                _governance_summary=lambda _request: {"backlog": []},
                _invalidate_asset_caches=lambda _asset_fqn: None,
                _asset_visibility_record=lambda *_args, **_kwargs: {
                    "openable": False,
                    "visible": False,
                    "exists": False,
                    "visibilityState": "missing",
                },
            ),
            patch.object(
                runtime_app,
                "_asset_detail_payload",
                side_effect=AssertionError("hidden asset detail should not be loaded"),
            ),
        ):
            with self.assertRaises(runtime_app.HTTPException) as exc:
                runtime_app.api_governance_patch_request(
                    "req-1",
                    runtime_app.GovernanceRequestStatusPatch(status="approved"),
                    request,
                )

        self.assertEqual(exc.exception.status_code, 404)
        self.assertFalse(mutated["called"])

    def test_governance_request_patch_accepts_resolved_status(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        captured = {}

        class Store:
            def get_change_request(self, request_id):
                return SimpleNamespace(uc_full_name="main.sales.orders")

            def set_request_status(self, **kwargs):
                captured.update(kwargs)
                return None

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _ensure_can_approve=lambda _request: "steward@example.com",
            _user_role_slug=lambda _request: "steward",
            _store=lambda: Store(),
            _governance_summary=lambda _request: {"backlog": []},
            _invalidate_asset_caches=lambda _asset_fqn: None,
            _asset_visibility_record=lambda *_args, **_kwargs: {
                "openable": True,
                "visible": True,
                "exists": True,
                "visibilityState": "visible",
            },
            _asset_detail_payload=lambda *_args, **_kwargs: {"fqn": "main.sales.orders"},
        ):
            response = runtime_app.api_governance_patch_request(
                "req-1",
                runtime_app.GovernanceRequestStatusPatch(
                    status="resolved",
                    reviewNote="Resolved from Stewardship Workbench.",
                ),
                request,
            )

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(captured["status"], "resolved")
        self.assertEqual(captured["reviewed_by"], "steward@example.com")
        self.assertEqual(captured["review_note"], "Resolved from Stewardship Workbench.")

    def test_governance_request_patch_allows_existing_request_while_asset_visibility_hydrates(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        captured = {}

        class Store:
            def get_change_request(self, request_id):
                return SimpleNamespace(uc_full_name="main.sales.orders")

            def set_request_status(self, **kwargs):
                captured.update(kwargs)
                return None

        with (
            patch.multiple(
                runtime_app,
                _ensure_live_runtime=lambda: None,
                _ensure_can_approve=lambda _request: "steward@example.com",
                _user_role_slug=lambda _request: "steward",
                _store=lambda: Store(),
                _governance_summary=lambda _request: {"backlog": []},
                _invalidate_asset_caches=lambda _asset_fqn: None,
                _asset_visibility_record=lambda *_args, **_kwargs: {
                    "openable": False,
                    "visible": False,
                    "exists": False,
                    "visibilityState": "loading",
                },
            ),
            patch.object(
                runtime_app,
                "_asset_detail_payload",
                side_effect=AssertionError("loading visibility should not force detail hydration"),
            ),
        ):
            response = runtime_app.api_governance_patch_request(
                "req-1",
                runtime_app.GovernanceRequestStatusPatch(status="resolved"),
                request,
                fast=True,
            )

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["asset"])
        self.assertTrue(payload["refreshDeferred"])
        self.assertEqual(captured["status"], "resolved")

    def test_approval_guard_rejects_writer_role(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _ensure_governance_store=lambda: None,
            _user_email=lambda _request: "writer@example.com",
            _user_role_slug=lambda _request: "writer",
        ):
            with self.assertRaises(runtime_app.HTTPException) as exc:
                runtime_app._ensure_can_approve(request)

        self.assertEqual(exc.exception.status_code, 403)
        self.assertIn("steward or admin", str(exc.exception.detail))

    def test_approval_guard_allows_steward_and_admin(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})

        for role in ("steward", "admin"):
            with patch.multiple(
                runtime_app,
                _ensure_governance_store=lambda: None,
                _user_email=lambda _request: f"{role}@example.com",
                _user_role_slug=lambda _request, _role=role: _role,
            ):
                self.assertEqual(runtime_app._ensure_can_approve(request), f"{role}@example.com")

    def test_uc_for_request_returns_app_principal_client_without_token(self) -> None:
        runtime_app = snapshot_script.runtime_app
        sentinel = object()
        request = SimpleNamespace(headers={})

        with patch.multiple(
            runtime_app,
            _uc=lambda: sentinel,
            _uc_for_token=lambda _token: (_ for _ in ()).throw(
                AssertionError("token path should not run without forwarded token")
            ),
        ):
            client = runtime_app._uc_for_request(request)

        self.assertIs(client, sentinel)

    def test_uc_for_request_uses_forwarded_token_to_build_actor_scoped_client(
        self,
    ) -> None:
        runtime_app = snapshot_script.runtime_app
        app_principal_sentinel = object()
        actor_scoped_sentinel = object()
        observed_tokens: list[str] = []
        request = SimpleNamespace(headers={"x-forwarded-access-token": "obo-token-42"})

        def _actor_scoped(token: str) -> object:
            observed_tokens.append(token)
            return actor_scoped_sentinel

        with patch.multiple(
            runtime_app,
            _uc=lambda: app_principal_sentinel,
            _uc_for_token=_actor_scoped,
        ):
            client = runtime_app._uc_for_request(request)

        # With an OBO token the runtime serves the actor-scoped client only;
        # it never falls back to the app principal.
        self.assertIsInstance(client, runtime_app._UserScopedUC)
        self.assertIs(client._client, actor_scoped_sentinel)
        self.assertEqual(observed_tokens, ["obo-token-42"])

    def test_uc_for_request_refuses_if_actor_scoped_build_fails(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={"x-forwarded-access-token": "obo-token-99"})

        def _actor_scoped(_token: str) -> object:
            raise RuntimeError("boom")

        with patch.multiple(runtime_app, _uc=lambda: object(), _uc_for_token=_actor_scoped):
            with self.assertRaises(runtime_app.HTTPException):
                runtime_app._uc_for_request(request)

    def test_request_cache_scope_partitions_obo_and_app_principal_buckets(self) -> None:
        runtime_app = snapshot_script.runtime_app
        obo_request = SimpleNamespace(
            headers={
                "x-forwarded-email": "user@example.com",
                "x-forwarded-access-token": "obo-token-xyz",
            }
        )
        app_request = SimpleNamespace(
            headers={"x-forwarded-email": "user@example.com"}
        )

        obo_scope = runtime_app._request_cache_scope(obo_request)
        app_scope = runtime_app._request_cache_scope(app_request)

        self.assertNotEqual(obo_scope, app_scope)
        self.assertTrue(obo_scope.endswith("|obo-available"))
        self.assertTrue(app_scope.endswith("|app-principal-only"))

    def test_response_meta_downgrades_unity_catalog_reads_without_obo(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={"x-forwarded-email": "user@example.com"})

        meta = runtime_app._response_meta(
            request,
            source="unity-catalog-inventory",
            state="available",
            authoritative=True,
        )

        self.assertFalse(meta["authoritative"])
        self.assertEqual(meta["state"], "degraded")
        self.assertEqual(meta["visibilityScope"], "workspace-app-principal")
        self.assertTrue(meta["degraded"])
        self.assertTrue(
            any("workspace-scoped app-principal" in w for w in meta["warnings"])
        )

    def test_response_meta_keeps_obo_reads_authoritative_and_actor_scoped(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(
            headers={
                "x-forwarded-email": "user@example.com",
                "x-forwarded-access-token": "obo-token-live",
            }
        )

        meta = runtime_app._response_meta(
            request,
            source="unity-catalog-inventory",
            state="available",
            authoritative=True,
        )

        self.assertTrue(meta["authoritative"])
        self.assertEqual(meta["state"], "available")
        self.assertEqual(meta["visibilityScope"], "actor-scoped")
        self.assertFalse(meta["degraded"])
        self.assertEqual(meta["warnings"], [])


class AssetVisibilityInventoryFirstTests(unittest.TestCase):
    def test_warm_inventory_membership_short_circuits_identity_probe(self) -> None:
        # P0 perf fix: when the actor's warm inventory already contains the
        # asset, the visibility record must be answered from the in-memory
        # frame WITHOUT paying the two per-asset information_schema queries
        # (get_table_identity/get_table_tags) that used to run first.
        import pandas as pd

        runtime_app = snapshot_script.runtime_app
        request = SimpleNamespace(headers={})
        inventory = pd.DataFrame([{"fqn": "main.sales.orders"}])

        def _forbidden_uc(_request):
            raise AssertionError(
                "identity probe must not run when inventory proves visibility"
            )

        with patch.multiple(
            runtime_app,
            _request_auth_mode=lambda _request: "obo-available",
            _cached_visible_assets=lambda _request: inventory,
            _uc_for_request=_forbidden_uc,
        ):
            record = runtime_app._asset_visibility_record(
                "main.sales.orders", request
            )

        self.assertTrue(record["visible"])
        self.assertTrue(record["openable"])
        self.assertEqual(record["visibilityState"], "visible")
        self.assertEqual(record["visibilityMethod"], "inventory")


if __name__ == "__main__":
    unittest.main()
