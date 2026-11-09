from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from axiom import runtime_contract


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


class RuntimeContractTests(unittest.TestCase):
    def _write_tree(self, root: Path) -> None:
        (root / "frontend/src").mkdir(parents=True, exist_ok=True)
        (root / "frontend/dist/assets").mkdir(parents=True, exist_ok=True)
        (root / "runtime_manifest.yaml").write_text(RUNTIME_MANIFEST, encoding="utf-8")
        (root / "frontend/index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
        (root / "frontend/package.json").write_text('{"name":"axiom"}\n', encoding="utf-8")
        (root / "frontend/package-lock.json").write_text('{"name":"axiom"}\n', encoding="utf-8")
        (root / "frontend/eslint.config.js").write_text("export default [];\n", encoding="utf-8")
        (root / "frontend/tsconfig.json").write_text('{"include":[]}\n', encoding="utf-8")
        (root / "frontend/vite.config.js").write_text("export default {};\n", encoding="utf-8")
        (root / "frontend/src/main.jsx").write_text("console.log('axiom');\n", encoding="utf-8")
        (root / "frontend/dist/index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
        (root / "frontend/dist/assets/app.js").write_text("console.log('bundle');\n", encoding="utf-8")

    def test_validate_frontend_bundle_accepts_matching_build_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_tree(root)
            source_hash = runtime_contract.frontend_source_hash(root)
            build_manifest = {
                "buildId": "frontend-test-build",
                "generatedAt": "2026-04-16T00:00:00Z",
                "sourceHash": source_hash,
            }
            (root / "frontend/dist/axiom-build-manifest.json").write_text(
                json.dumps(build_manifest),
                encoding="utf-8",
            )

            resolved = runtime_contract.validate_frontend_bundle(root)

        self.assertEqual(resolved["buildId"], "frontend-test-build")

    def test_validate_frontend_bundle_rejects_stale_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_tree(root)
            source_hash = runtime_contract.frontend_source_hash(root)
            (root / "frontend/dist/axiom-build-manifest.json").write_text(
                json.dumps(
                    {
                        "buildId": "frontend-test-build",
                        "generatedAt": "2026-04-16T00:00:00Z",
                        "sourceHash": source_hash,
                    }
                ),
                encoding="utf-8",
            )
            (root / "frontend/src/main.jsx").write_text("console.log('changed');\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "frontend bundle is stale"):
                runtime_contract.validate_frontend_bundle(root)


if __name__ == "__main__":
    unittest.main()
