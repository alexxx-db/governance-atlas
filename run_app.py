#!/usr/bin/env python3
"""Axiom launcher."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Final

from axiom.runtime_contract import validate_frontend_bundle


APP_ENTRYPOINT: Final[str] = "runtime_app:app"
APP_MODULE: Final[str] = "runtime_app"
ROOT: Final[Path] = Path(__file__).resolve().parent
FRONTEND_DIST: Final[Path] = ROOT / "frontend" / "dist" / "index.html"
FRONTEND_ASSETS: Final[Path] = ROOT / "frontend" / "dist" / "assets"
FRONTEND_BUILD_MANIFEST: Final[Path] = ROOT / "frontend" / "dist" / "axiom-build-manifest.json"


def _port() -> str:
    return (
        os.getenv("DATABRICKS_APP_PORT")
        or os.getenv("PORT")
        or os.getenv("APP_PORT")
        or "8000"
    )


def _exec(cmd: list[str]) -> None:
    os.execvp(cmd[0], cmd)


def _run_runtime() -> None:
    if importlib.util.find_spec(APP_MODULE) is None:
        raise SystemExit(
            "Axiom runtime is unavailable: backend module runtime_app.py is missing."
        )
    if importlib.util.find_spec("uvicorn") is None:
        raise SystemExit("Axiom requires uvicorn to be installed.")
    try:
        validate_frontend_bundle(ROOT)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    _exec(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP_ENTRYPOINT,
            "--host",
            "0.0.0.0",
            "--port",
            _port(),
            # One process on purpose: extra workers would each keep their own
            # metadata caches and multiply warehouse load. Concurrency is
            # bounded by AXIOM_SQL_MAX_CONCURRENCY and AXIOM_THREADPOOL_SIZE.
            "--workers",
            "1",
        ]
    )


def main() -> None:
    _run_runtime()


if __name__ == "__main__":
    main()
