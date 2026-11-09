from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from axiom import runtime_contract
import run_app


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_runtime_api_openapi_snapshot.py"
APP_YAML_PATH = ROOT / "app.yaml"


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


class RuntimeRouteServingTests(unittest.TestCase):
    def test_app_yaml_launches_run_app(self) -> None:
        content = APP_YAML_PATH.read_text(encoding="utf-8")

        self.assertIn("- run_app.py", content)

    def test_run_app_points_to_runtime_app(self) -> None:
        self.assertEqual(run_app.APP_ENTRYPOINT, "runtime_app:app")
        self.assertEqual(run_app.APP_MODULE, "runtime_app")
        self.assertTrue(run_app.FRONTEND_DIST.as_posix().endswith("frontend/dist/index.html"))
        self.assertTrue(run_app.FRONTEND_ASSETS.as_posix().endswith("frontend/dist/assets"))
        self.assertTrue(
            run_app.FRONTEND_BUILD_MANIFEST.as_posix().endswith(
                "frontend/dist/axiom-build-manifest.json"
            )
        )

    def test_runtime_manifest_declares_single_supported_runtime_chain(self) -> None:
        manifest = runtime_contract.load_runtime_manifest(ROOT)

        self.assertEqual(manifest["runtime"]["app_yaml"], "app.yaml")
        self.assertEqual(manifest["runtime"]["launcher"], "run_app.py")
        self.assertEqual(manifest["runtime"]["backend_module"], "runtime_app.py")
        self.assertEqual(manifest["runtime"]["frontend_dist"], "frontend/dist/index.html")
        self.assertEqual(
            manifest["runtime"]["frontend_build_manifest"],
            "frontend/dist/axiom-build-manifest.json",
        )

    def test_runtime_app_exposes_shell_and_runtime_routes(self) -> None:
        runtime_app = snapshot_script.runtime_app
        paths = {route.path for route in snapshot_script.iter_api_routes(runtime_app.app)}

        self.assertIn("/", paths)
        self.assertIn("/api/bootstrap", paths)
        self.assertIn("/api/runtime/status", paths)

    def test_runtime_app_defers_bundle_validation_until_runtime_use(self) -> None:
        source = (ROOT / "runtime_app.py").read_text(encoding="utf-8")

        self.assertIn("def _frontend_bundle_metadata()", source)
        self.assertNotIn("FRONTEND_BUNDLE_METADATA = validate_frontend_bundle(ROOT)", source)

    def test_spa_shell_response_serves_inline_shell_without_bootstrap_inventory_work(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = object()

        with (
            patch.object(runtime_app, "_shell_payload", return_value={"bootState": "loading"}) as shell_payload,
            patch.object(runtime_app, "_render_index", return_value="<html>shell</html>") as render_index,
        ):
            response = runtime_app._spa_shell_response(request)

        shell_payload.assert_called_once_with(
            request,
            mode="inline-shell",
            state="loading",
            message="Preparing the live metadata workspace.",
        )
        render_index.assert_called_once_with({"bootState": "loading"})
        self.assertEqual(response.status_code, 200)

    def test_client_route_shell_uses_spa_shell_for_entity_paths(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = object()

        with patch.object(runtime_app, "_spa_shell_response", return_value="shell-response") as shell_response:
            response = runtime_app.client_route_shell("entity/main.sales.orders", request)

        shell_response.assert_called_once_with(request)
        self.assertEqual(response, "shell-response")

    def test_client_route_shell_serves_active_prototype_paths(self) -> None:
        runtime_app = snapshot_script.runtime_app
        request = object()
        prototype_paths = [
            "command-center",
            "discover",
            "stewardship",
            "glossary-cdes",
            "glossary-cdes?tab=cdes",
            "lineage-atlas/finance_prod.curated.revenue_daily",
            "audit-evidence",
            "control-center",
            # emet Control Center + its aliases must hard-load to the SPA
            # shell (regression: /emet 404'd server-side on first deploy).
            "emet",
            "emet?tab=jobs",
            "data-quality",
        ]

        with patch.object(runtime_app, "_spa_shell_response", return_value="shell-response") as shell_response:
            responses = [
                runtime_app.client_route_shell(client_path, request)
                for client_path in prototype_paths
            ]

        self.assertEqual(responses, ["shell-response"] * len(prototype_paths))
        self.assertEqual(shell_response.call_count, len(prototype_paths))

    def test_run_app_fails_fast_when_frontend_bundle_contract_is_invalid(self) -> None:
        with (
            patch.object(run_app.importlib.util, "find_spec", return_value=object()),
            patch.object(
                run_app,
                "validate_frontend_bundle",
                side_effect=RuntimeError("bundle contract failed"),
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "bundle contract failed"):
                run_app._run_runtime()


if __name__ == "__main__":
    unittest.main()
