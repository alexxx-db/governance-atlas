#!/usr/bin/env python3
"""Validate that legacy runtime drift and tracked build artifacts stay out of the repo."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from axiom.runtime_contract import load_runtime_manifest



REMOVED_PATHS = (
    "app.py",
    "modern_app.py",
    "axiom/openmetadata.py",
    "axiom/legacy_auth.py",
    "axiom/legacy_auth 2.py",
    "axiom/services/live_metadata 2.py",
    "frontend/src/components/AppErrorBoundary 2.jsx",
)

TRACKED_ARTIFACT_PREFIXES = (
    "frontend/dist/",
    "frontend/node_modules/",
    "node_modules/",
    ".venv/",
    "__MACOSX/",
)

DUPLICATE_NAME_MARKER = " 2."

RUNTIME_HYGIENE_TARGETS = (
    "app.yaml",
    "databricks.yml",
    "requirements.txt",
    "run_app.py",
    "runtime_app.py",
    "axiom",
    "sql/bootstrap.sql",
)

BANNED_RUNTIME_TOKENS = (
    "APP_MODE",
    "OPENMETADATA_SERVER_URL",
    "OPENMETADATA_JWT_TOKEN",
    "om_server_url",
    "om_jwt_token",
    "openmetadata_enabled",
    "asset_links",
    "streamlit>=",
)

REQUIRED_BRANCH_STATE_PATHS = (
    ".gitignore",
    ".github/workflows/deploy.yml",
    "app.yaml",
    "run_app.py",
    "runtime_app.py",
    "runtime_manifest.yaml",
    "frontend/package.json",
    "frontend/eslint.config.js",
    "frontend/src/App.jsx",
    # The entity/asset workspace was consolidated into the asset surfaces + the
    # useAssetDetail hook during the cohesive-architecture rebuild (#7/#8); the
    # availability-prefetch + link-openability proof now lives in this hook.
    "frontend/src/hooks/useAssetDetail.js",
    "frontend/src/lib/api.js",
    "frontend/src/main.jsx",
    "axiom/runtime_contract.py",
    "scripts/prepare_bundle.py",
)

REQUIRED_RUNTIME_MANIFEST = {
    "app_yaml": "app.yaml",
    "launcher": "run_app.py",
    "backend_module": "runtime_app.py",
    "app_object": "app",
    "frontend_dist": "frontend/dist/index.html",
    "frontend_assets": "frontend/dist/assets",
    "frontend_build_manifest": "frontend/dist/axiom-build-manifest.json",
}

REQUIRED_RUNTIME_REMOVED_PATHS = (
    "app.py",
    "modern_app.py",
    "modern_ui",
    "axiom/openmetadata.py",
)

REQUIRED_FRONTEND_SCRIPTS = {
    "lint": "eslint",
    "test": "vitest",
    "typecheck": "tsc",
    "build": "vite build",
}

REQUIRED_FRONTEND_DEPENDENCIES = (
    "@tanstack/react-query",
    "react-router-dom",
)

REQUIRED_FRONTEND_DEV_DEPENDENCIES = (
    "typescript",
    "vite",
    "vitest",
    "eslint-plugin-react-hooks",
    "eslint-plugin-unused-imports",
)

REQUIRED_ESLINT_TOKENS = (
    '"no-undef": "error"',
    '"unused-imports/no-unused-imports": "error"',
    '"react-hooks/rules-of-hooks": "error"',
    '"react-hooks/exhaustive-deps": "warn"',
)

# Availability-prefetch + link-openability proof. This behavior moved from the
# retired EntityWorkspace.jsx into the useAssetDetail hook (#7/#8 rebuild).
REQUIRED_ASSET_DETAIL_TOKENS = (
    "prefetchAssetAvailability",
    "canOpenLinkedAssetRecord",
)

REQUIRED_GITIGNORE_TOKENS = (
    "frontend/dist/",
    "frontend/node_modules/",
)

REQUIRED_APP_YAML_TOKENS = (
    "run_app.py",
)

REQUIRED_RUN_APP_TOKENS = (
    'APP_ENTRYPOINT: Final[str] = "runtime_app:app"',
    'APP_MODULE: Final[str] = "runtime_app"',
    "FRONTEND_DIST",
    "FRONTEND_ASSETS",
    "FRONTEND_BUILD_MANIFEST",
    "validate_frontend_bundle",
)

REQUIRED_PREPARE_BUNDLE_TOKENS = (
    "REQUIRED_FRONTEND_FILES",
    "validate_frontend_bundle",
    "axiom-build-manifest.json",
    ".git",
    ".github",
    "node_modules",
)

REQUIRED_DEPLOY_WORKFLOW_TOKENS = (
    "npm run lint",
    "npm run typecheck",
    "npm run test",
    "databricks bundle validate",
    "databricks bundle summary",
    "python3 scripts/prepare_bundle.py",
    "python3 -m py_compile run_app.py",
    "npm run build",
)


def _tracked_files(root: Path = ROOT) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def _target_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for target in RUNTIME_HYGIENE_TARGETS:
        path = root / target
        if path.is_file():
            files.append(path)
            continue
        if path.is_dir():
            files.extend(candidate for candidate in path.rglob("*") if candidate.is_file())
    return files


def _looks_like_removed_legacy_shell(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name.startswith(".") or path.name in {"frontend", "axiom", "tests", "scripts", "docs", "sql"}:
        return False
    return (path / "index.html").exists() and (
        (path / "assets").exists() or (path / "data.js").exists()
    )


def _validate_required_branch_state(
    root: Path,
    tracked_set: set[str],
    failures: list[str],
) -> None:
    missing_paths = [path for path in REQUIRED_BRANCH_STATE_PATHS if not (root / path).exists()]
    for path in missing_paths:
        failures.append(f"Required branch-state path is missing: {path}")
    for path in REQUIRED_BRANCH_STATE_PATHS:
        if path in tracked_set:
            continue
        if (root / path).exists():
            failures.append(
                "Required branch-state path exists locally but is not tracked by git: "
                f"{path}"
            )

    runtime_manifest_path = root / "runtime_manifest.yaml"
    if runtime_manifest_path.exists():
        try:
            runtime_manifest = load_runtime_manifest(root)
        except RuntimeError as exc:
            failures.append(str(exc))
        else:
            runtime = runtime_manifest.get("runtime") or {}
            for key, expected_value in REQUIRED_RUNTIME_MANIFEST.items():
                actual_value = str(runtime.get(key) or "").strip()
                if actual_value != expected_value:
                    failures.append(
                        "runtime_manifest.yaml does not match the supported runtime chain for "
                        f"`runtime.{key}`."
                    )
            removed_runtime_paths = tuple(runtime_manifest.get("removed_runtime_paths") or ())
            for expected_path in REQUIRED_RUNTIME_REMOVED_PATHS:
                if expected_path not in removed_runtime_paths:
                    failures.append(
                        "runtime_manifest.yaml is missing the required removed runtime path "
                        f"`{expected_path}`."
                    )

    package_path = root / "frontend/package.json"
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"frontend/package.json is not valid JSON: {exc}")
        else:
            scripts = package.get("scripts") or {}
            dependencies = package.get("dependencies") or {}
            dev_dependencies = package.get("devDependencies") or {}
            for script_name, token in REQUIRED_FRONTEND_SCRIPTS.items():
                script_value = str(scripts.get(script_name) or "")
                if token not in script_value:
                    failures.append(
                        f"frontend/package.json is missing the required `{script_name}` script contract."
                    )
            for dependency in REQUIRED_FRONTEND_DEPENDENCIES:
                if dependency not in dependencies:
                    failures.append(
                        f"frontend/package.json is missing required dependency `{dependency}`."
                    )
            for dependency in REQUIRED_FRONTEND_DEV_DEPENDENCIES:
                if dependency not in dev_dependencies:
                    failures.append(
                        f"frontend/package.json is missing required devDependency `{dependency}`."
                    )

    eslint_path = root / "frontend/eslint.config.js"
    if eslint_path.exists():
        content = eslint_path.read_text(encoding="utf-8")
        for token in REQUIRED_ESLINT_TOKENS:
            if token not in content:
                failures.append(
                    f"frontend/eslint.config.js is missing required lint rule token `{token}`."
                )

    asset_detail_path = root / "frontend/src/hooks/useAssetDetail.js"
    if asset_detail_path.exists():
        content = asset_detail_path.read_text(encoding="utf-8")
        for token in REQUIRED_ASSET_DETAIL_TOKENS:
            if token not in content:
                failures.append(
                    "useAssetDetail branch-state hotfix proof is missing "
                    f"`{token}`."
                )

    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        for token in REQUIRED_GITIGNORE_TOKENS:
            if token not in content:
                failures.append(f".gitignore is missing required ignore entry `{token}`.")

    app_yaml_path = root / "app.yaml"
    if app_yaml_path.exists():
        content = app_yaml_path.read_text(encoding="utf-8")
        for token in REQUIRED_APP_YAML_TOKENS:
            if token not in content:
                failures.append(
                    f"app.yaml is missing the required launcher token `{token}`."
                )

    run_app_path = root / "run_app.py"
    if run_app_path.exists():
        content = run_app_path.read_text(encoding="utf-8")
        for token in REQUIRED_RUN_APP_TOKENS:
            if token not in content:
                failures.append(
                    f"run_app.py is missing required runtime-chain token `{token}`."
                )

    prepare_bundle_path = root / "scripts/prepare_bundle.py"
    if prepare_bundle_path.exists():
        content = prepare_bundle_path.read_text(encoding="utf-8")
        for token in REQUIRED_PREPARE_BUNDLE_TOKENS:
            if token not in content:
                failures.append(
                    "scripts/prepare_bundle.py is missing required packaged-artifact "
                    f"inventory token `{token}`."
                )

    deploy_workflow_path = root / ".github/workflows/deploy.yml"
    if deploy_workflow_path.exists():
        content = deploy_workflow_path.read_text(encoding="utf-8")
        for token in REQUIRED_DEPLOY_WORKFLOW_TOKENS:
            if token not in content:
                failures.append(
                    ".github/workflows/deploy.yml is missing required deploy-proof "
                    f"token `{token}`."
                )


def validate(root: Path = ROOT, tracked_files: list[str] | None = None) -> list[str]:
    failures: list[str] = []
    tracked_files = tracked_files if tracked_files is not None else _tracked_files(root)
    tracked_set = set(tracked_files)

    for path in REMOVED_PATHS:
        if (root / path).exists():
            failures.append(f"Removed legacy path still exists: {path}")

    for path in root.iterdir():
        if _looks_like_removed_legacy_shell(path):
            failures.append(f"Removed legacy shell path still exists: {path.name}")

    for path in tracked_files:
        file_path = root / path
        if not file_path.exists():
            continue
        if any(path.startswith(prefix) for prefix in TRACKED_ARTIFACT_PREFIXES) or "__pycache__/" in path:
            failures.append(f"Tracked build/runtime artifact found: {path}")
        if DUPLICATE_NAME_MARKER in file_path.name:
            failures.append(f"Tracked duplicate-suffix file found: {path}")

    for file_path in _target_files(root):
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in BANNED_RUNTIME_TOKENS:
            if token in content:
                failures.append(
                    f"Banned runtime token '{token}' found in {file_path.relative_to(root)}"
                )

    _validate_required_branch_state(root, tracked_set, failures)

    # `frontend/dist` is allowed in the working tree after a build, but must not be tracked.
    if "frontend/dist/index.html" in tracked_set and (root / "frontend/dist/index.html").exists():
        failures.append("frontend/dist is still tracked by git.")

    return failures


def main() -> int:
    failures = validate()
    if not failures:
        print("Repo hygiene checks passed.")
        return 0
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
