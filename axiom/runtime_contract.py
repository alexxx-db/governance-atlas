"""Runtime chain and packaged frontend contract helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Final, Iterator


ROOT: Final[Path] = Path(__file__).resolve().parent.parent
RUNTIME_MANIFEST_PATH: Final[str] = "runtime_manifest.yaml"
FRONTEND_HASH_FILE_PATHS: Final[tuple[str, ...]] = (
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/eslint.config.js",
    "frontend/tsconfig.json",
    "frontend/vite.config.js",
)
FRONTEND_HASH_DIRS: Final[tuple[str, ...]] = ("frontend/src",)


def _repo_root(root: Path | None = None) -> Path:
    return Path(root or ROOT).resolve()


def _runtime_manifest_path(root: Path | None = None) -> Path:
    return _repo_root(root) / RUNTIME_MANIFEST_PATH


def load_runtime_manifest(root: Path | None = None) -> Dict[str, Any]:
    path = _runtime_manifest_path(root)
    if not path.exists():
        raise RuntimeError("Axiom runtime manifest is missing at runtime_manifest.yaml.")

    manifest: Dict[str, Any] = {}
    current_key = ""

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            if stripped.endswith(":"):
                current_key = stripped[:-1].strip()
                manifest[current_key] = {} if current_key == "runtime" else []
                continue
            raise RuntimeError(
                f"Unsupported runtime manifest syntax at line {line_number}: {raw_line}"
            )

        if current_key == "runtime" and indent == 2 and ":" in stripped:
            key, value = stripped.split(":", 1)
            manifest["runtime"][key.strip()] = value.strip()
            continue

        if (
            current_key == "removed_runtime_paths"
            and indent == 2
            and stripped.startswith("- ")
        ):
            manifest["removed_runtime_paths"].append(stripped[2:].strip())
            continue

        raise RuntimeError(
            f"Unsupported runtime manifest syntax at line {line_number}: {raw_line}"
        )

    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or not runtime:
        raise RuntimeError("runtime_manifest.yaml is missing the required `runtime` map.")

    return manifest


def runtime_paths(root: Path | None = None) -> Dict[str, Path]:
    repo_root = _repo_root(root)
    manifest = load_runtime_manifest(repo_root)
    runtime = manifest.get("runtime") or {}
    required_keys = (
        "app_yaml",
        "launcher",
        "backend_module",
        "frontend_dist",
        "frontend_assets",
        "frontend_build_manifest",
    )
    paths: Dict[str, Path] = {}
    for key in required_keys:
        relative = str(runtime.get(key) or "").strip()
        if not relative:
            raise RuntimeError(f"runtime_manifest.yaml is missing runtime.{key}.")
        paths[key] = repo_root / relative
    return paths


# OS metadata files are dropped by scripts/prepare_bundle.py, so they must not
# count toward the hash. Keep in sync with frontend/scripts/write_build_manifest.mjs.
FRONTEND_HASH_IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db"})


def required_frontend_bundle_paths(root: Path | None = None) -> list[Path]:
    paths = runtime_paths(root)
    return [
        paths["frontend_dist"],
        paths["frontend_assets"],
        paths["frontend_build_manifest"],
    ]


def _iter_frontend_source_files(root: Path | None = None) -> Iterator[Path]:
    repo_root = _repo_root(root)

    for relative in FRONTEND_HASH_FILE_PATHS:
        path = repo_root / relative
        if path.is_file():
            yield path

    for relative_dir in FRONTEND_HASH_DIRS:
        directory = repo_root / relative_dir
        if not directory.exists():
            continue
        for candidate in sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.name not in FRONTEND_HASH_IGNORED_NAMES
        ):
            yield candidate


def frontend_source_hash(root: Path | None = None) -> str:
    repo_root = _repo_root(root)
    digest = hashlib.sha256()
    for file_path in _iter_frontend_source_files(repo_root):
        relative = file_path.relative_to(repo_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_frontend_build_manifest(root: Path | None = None) -> Dict[str, Any]:
    manifest_path = runtime_paths(root)["frontend_build_manifest"]
    if not manifest_path.exists():
        raise RuntimeError(
            "Axiom requires a packaged frontend build manifest at "
            f"{manifest_path.relative_to(_repo_root(root)).as_posix()}."
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Axiom frontend build manifest is not valid JSON: {exc}"
        ) from exc


def validate_frontend_bundle(root: Path | None = None) -> Dict[str, Any]:
    repo_root = _repo_root(root)
    required_paths = required_frontend_bundle_paths(repo_root)
    missing = [path.relative_to(repo_root).as_posix() for path in required_paths if not path.exists()]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(
            "Axiom requires a packaged React frontend bundle at "
            f"{missing_list}. Build and package the frontend before launch."
        )

    build_manifest = load_frontend_build_manifest(repo_root)
    source_hash = str(build_manifest.get("sourceHash") or "").strip()
    if not source_hash:
        raise RuntimeError(
            "Axiom frontend build manifest is missing the required `sourceHash` proof."
        )

    current_hash = frontend_source_hash(repo_root)
    if source_hash != current_hash:
        raise RuntimeError(
            "Axiom frontend bundle is stale: frontend source changed after the "
            "last build. Re-run `npm run build` before launch or packaging."
        )

    return build_manifest
