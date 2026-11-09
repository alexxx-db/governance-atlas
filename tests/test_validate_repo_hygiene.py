from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import validate_repo_hygiene


PACKAGE_JSON = {
    "scripts": {
        "lint": "eslint src vite.config.js",
        "test": "vitest run",
        "typecheck": "tsc --noEmit -p tsconfig.json",
        "build": "vite build",
    },
    "dependencies": {
        "@tanstack/react-query": "^5.0.0",
        "react-router-dom": "^6.0.0",
    },
    "devDependencies": {
        "typescript": "^5.0.0",
        "vite": "^5.0.0",
        "vitest": "^3.0.0",
        "eslint-plugin-react-hooks": "^5.0.0",
        "eslint-plugin-unused-imports": "^4.0.0",
    },
}

ESLINT_CONFIG = """
export default [{
  rules: {
    "no-undef": "error",
    "unused-imports/no-unused-imports": "error",
    "react-hooks/rules-of-hooks": "error",
    "react-hooks/exhaustive-deps": "warn",
  },
}];
""".strip()

USE_ASSET_DETAIL = """
export function prefetchAssetAvailability(details) {
  return details;
}

export function canOpenLinkedAssetRecord(detail) {
  return Boolean(detail);
}
""".strip()

APP_YAML = """
command:
  - python
  - run_app.py
""".strip()

RUN_APP = """
from pathlib import Path
from typing import Final

from axiom.runtime_contract import validate_frontend_bundle

APP_ENTRYPOINT: Final[str] = "runtime_app:app"
APP_MODULE: Final[str] = "runtime_app"
FRONTEND_DIST: Final[Path] = Path(__file__).resolve().parent / "frontend" / "dist" / "index.html"
FRONTEND_ASSETS: Final[Path] = Path(__file__).resolve().parent / "frontend" / "dist" / "assets"
FRONTEND_BUILD_MANIFEST: Final[Path] = Path(__file__).resolve().parent / "frontend" / "dist" / "axiom-build-manifest.json"
validate_frontend_bundle(Path(__file__).resolve().parent)
""".strip()

PREPARE_BUNDLE = """
REQUIRED_FRONTEND_FILES = ["frontend/dist/index.html"]
validate_frontend_bundle = object()
BUILD_MANIFEST = "frontend/dist/axiom-build-manifest.json"
IGNORED = {".git", ".github", "node_modules"}
""".strip()

DEPLOY_WORKFLOW = """
jobs:
  validate:
    steps:
      - run: npm run lint
      - run: npm run typecheck
      - run: npm run test
      - run: python3 -m py_compile run_app.py runtime_app.py
      - run: npm run build
      - run: python3 scripts/prepare_bundle.py --output /tmp/out
      - run: databricks bundle validate -t dev
      - run: databricks bundle summary -t dev
""".strip()

GITIGNORE = """
frontend/dist/
frontend/node_modules/
""".strip()

RUNTIME_MANIFEST = """
runtime:
  app_yaml: app.yaml
  launcher: run_app.py
  backend_module: runtime_app.py
  app_object: app
  frontend_dist: frontend/dist/index.html
  frontend_assets: frontend/dist/assets
  frontend_build_manifest: frontend/dist/axiom-build-manifest.json
removed_runtime_paths:
  - app.py
  - modern_app.py
  - modern_ui
  - axiom/openmetadata.py
""".strip()


class RepoHygieneValidationTests(unittest.TestCase):
    def _write_base_tree(self, root: Path) -> None:
        (root / ".github/workflows").mkdir(parents=True, exist_ok=True)
        (root / "frontend/src/components").mkdir(parents=True, exist_ok=True)
        (root / "frontend/src/hooks").mkdir(parents=True, exist_ok=True)
        (root / "frontend/src/lib").mkdir(parents=True, exist_ok=True)
        (root / "frontend/src/types").mkdir(parents=True, exist_ok=True)
        (root / "axiom").mkdir(parents=True, exist_ok=True)
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "frontend/package.json").write_text(json.dumps(PACKAGE_JSON), encoding="utf-8")
        (root / "frontend/eslint.config.js").write_text(ESLINT_CONFIG, encoding="utf-8")
        (root / "frontend/src/App.jsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
        (root / "frontend/src/hooks/useAssetDetail.js").write_text(USE_ASSET_DETAIL, encoding="utf-8")
        (root / "frontend/src/lib/api.js").write_text("export function fetchBootstrap() { return {}; }\n", encoding="utf-8")
        (root / "frontend/src/main.jsx").write_text("console.log('main');\n", encoding="utf-8")
        (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        (root / ".github/workflows/deploy.yml").write_text(DEPLOY_WORKFLOW, encoding="utf-8")
        (root / "app.yaml").write_text(APP_YAML, encoding="utf-8")
        (root / "run_app.py").write_text(RUN_APP, encoding="utf-8")
        (root / "runtime_app.py").write_text("print('runtime')\n", encoding="utf-8")
        (root / "runtime_manifest.yaml").write_text(RUNTIME_MANIFEST, encoding="utf-8")
        (root / "axiom/runtime_contract.py").write_text("def validate_frontend_bundle(root=None):\n    return {}\n", encoding="utf-8")
        (root / "scripts/prepare_bundle.py").write_text(PREPARE_BUNDLE, encoding="utf-8")

    def _tracked_files(self) -> list[str]:
        return [
            ".gitignore",
            ".github/workflows/deploy.yml",
            "app.yaml",
            "run_app.py",
            "runtime_app.py",
            "runtime_manifest.yaml",
            "frontend/package.json",
            "frontend/eslint.config.js",
            "frontend/src/App.jsx",
            "frontend/src/hooks/useAssetDetail.js",
            "frontend/src/lib/api.js",
            "frontend/src/main.jsx",
            "axiom/runtime_contract.py",
            "scripts/prepare_bundle.py",
        ]

    def test_validate_accepts_current_branch_state_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_base_tree(root)

            failures = validate_repo_hygiene.validate(root=root, tracked_files=self._tracked_files())

        self.assertEqual(failures, [])

    def test_validate_reports_missing_asset_detail_hotfix_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_base_tree(root)
            (root / "frontend/src/hooks/useAssetDetail.js").write_text(
                'export function useAssetDetail() { return null; }\n',
                encoding="utf-8",
            )

            failures = validate_repo_hygiene.validate(root=root, tracked_files=self._tracked_files())

        self.assertTrue(
            any("useAssetDetail branch-state hotfix proof is missing" in failure for failure in failures)
        )

    def test_validate_reports_missing_frontend_foundation_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_base_tree(root)
            broken_package = dict(PACKAGE_JSON)
            broken_package["dependencies"] = {"react-router-dom": "^6.0.0"}
            broken_package["scripts"] = {"lint": "eslint src"}
            broken_package["devDependencies"] = {}
            (root / "frontend/package.json").write_text(json.dumps(broken_package), encoding="utf-8")

            failures = validate_repo_hygiene.validate(root=root, tracked_files=self._tracked_files())

        self.assertTrue(
            any("required `test` script contract" in failure for failure in failures)
        )
        self.assertTrue(
            any("required dependency `@tanstack/react-query`" in failure for failure in failures)
        )
        self.assertTrue(
            any("required devDependency `eslint-plugin-react-hooks`" in failure for failure in failures)
        )

    def test_validate_reports_missing_runtime_chain_and_bundle_proof_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_base_tree(root)
            (root / "app.yaml").write_text("command:\n  - python\n", encoding="utf-8")
            (root / "run_app.py").write_text("APP_ENTRYPOINT = 'legacy:app'\n", encoding="utf-8")
            (root / ".github/workflows/deploy.yml").write_text(
                "jobs:\n  validate:\n    steps:\n      - run: databricks bundle validate -t dev\n",
                encoding="utf-8",
            )
            (root / "scripts/prepare_bundle.py").write_text("IGNORED = {'.git'}\n", encoding="utf-8")
            (root / ".gitignore").write_text("frontend/node_modules/\n", encoding="utf-8")
            (root / "runtime_manifest.yaml").write_text("runtime:\n  launcher: legacy.py\n", encoding="utf-8")

            failures = validate_repo_hygiene.validate(root=root, tracked_files=self._tracked_files())

        self.assertTrue(any("app.yaml is missing" in failure for failure in failures))
        self.assertTrue(any("run_app.py is missing required runtime-chain token" in failure for failure in failures))
        self.assertTrue(any("deploy-proof token `databricks bundle summary`" in failure for failure in failures))
        self.assertTrue(any("packaged-artifact inventory token `REQUIRED_FRONTEND_FILES`" in failure for failure in failures))
        self.assertTrue(any(".gitignore is missing required ignore entry `frontend/dist/`" in failure for failure in failures))
        self.assertTrue(
            any("runtime_manifest.yaml does not match the supported runtime chain" in failure for failure in failures)
        )

    def test_validate_reports_required_paths_that_exist_only_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_base_tree(root)

            failures = validate_repo_hygiene.validate(
                root=root,
                tracked_files=[
                    path
                    for path in self._tracked_files()
                    if path not in {"frontend/src/lib/api.js", "frontend/src/main.jsx"}
                ],
            )

        self.assertTrue(
            any("exists locally but is not tracked by git: frontend/src/lib/api.js" in failure for failure in failures)
        )


if __name__ == "__main__":
    unittest.main()
