#!/usr/bin/env python3
"""Validate the North Star audit ledger contract.

This guard does not claim visual parity. It prevents bookkeeping drift between
the route/reference manifest, materialized gap ledger, current screenshot
evidence, and the explicit signoff-supersession state.
"""

from __future__ import annotations

import json
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/northstar_gap_analysis/reference_manifest.json"
AUDIT_PATH = ROOT / "docs/northstar_gap_analysis/full_page_audit.md"
STATUS_PATH = ROOT / "IMPLEMENTATION_STATUS.md"
CHANGELOG_PATH = ROOT / "AGENT_CHANGELOG.md"
PROTOTYPE_CONTRACT_PATH = ROOT / "docs/northstar_gap_analysis/prototype_contract.md"
FUNCTIONAL_AUDIT_PATH = ROOT / "docs/northstar_gap_analysis/functional_control_audit.md"
SIGNOFF_MATRIX_PATH = ROOT / "docs/northstar_gap_analysis/signoff_matrix.md"
VISUAL_QA_ROOT = ROOT / "docs/northstar_visual_qa"
VISUAL_QA_PREFIX_PARTS = ("docs", "northstar_visual_qa")
COMPANION_AUDIT_GLOB = "docs/northstar_gap_analysis/*audit*.md"
STATUS_HISTORY_MARKER = "## Superseded Historical Checkpoints - Do Not Use As Current State"
REQUIRED_REVIEWER_ROLES = {
    "Visual fidelity",
    "Product structure",
    "Truth/provenance",
    "Functional workflow",
    "Process",
    "Feedback coverage",
}
COMPLETION_TERMS = [
    "visually indistinguishable",
    "North Star complete",
    "visual QA passed",
    "mockup matched",
    "signed off",
    "visually complete",
    "functionally signed off",
    "unanimous subagent signoff",
    "No blocking follow-ups remain",
    "no blockers remain",
    "Visual/product fidelity: SIGNOFF",
    "screenshot gate",
    "functionally complete",
    "functional evidence complete",
    "functional rows closed",
    "closed locally",
    "sign off",
    "sign-off",
    "approved for closure",
    "ready for closure",
    "closure approved",
    "approved to close",
    "ready to close",
    "zero route/shared open rows",
    "records `0` open controls",
    "rows are closed",
]
COMPLETION_CONTEXT_ALLOWLIST = (
    "superseded evidence failures",
    "is prohibited",
    "prohibited while",
    "must never be described",
    "must not be described",
    "must not be used",
    "must not use",
    "may not use",
    "cannot sign off",
    "cannot be signed off",
    "has not signed off",
    "no page is signed off",
    "cannot be used",
    "not a signoff",
    "not visual signoff",
    "not live databricks proof",
    "no page may be treated as complete",
    "preventive rule",
    "preventive rule: lineage may not use any matched, complete, signed-off",
    "any matched, complete, signed-off",
)
ALLOWED_GAP_CATEGORIES = {"visual", "functional", "truth/provenance", "process"}
STALE_ACTIVE_VERSION_RE = re.compile(
    r"\b(?:active|current|fresh|hash-pinned|captures?|report|evidence|directory)[^.\n]{0,80}\bv(?P<version>\d+)\b"
)


SUMMARY_ROW_RE = re.compile(
    r"^\| (?P<label>[^|]+) \| (?P<reference>[^|]+) \| (?P<evidence>[^|]+) \| (?P<count>[^|]+) \| (?P<status>[^|]+) \|$"
)
CONTROL_SUMMARY_ROW_RE = re.compile(
    r"^\| (?P<label>[^|]+) \| (?P<count>[^|]+) \| (?P<status>[^|]+) \|$"
)
SECTION_RE = re.compile(r"^## (?P<label>.+?) Gaps$")
CONTROL_SECTION_RE = re.compile(r"^## (?P<label>.+?) Controls$")
GAP_ROW_RE = re.compile(r"^- \[(?P<checked>[ xX])\] (?P<category>[^:]+):")
MALFORMED_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[^\]]*\]")
STATUS_GAP_SUMMARY_RE = re.compile(
    r"The active source of truth .* currently has `(?P<total>\d+)` open gaps: (?P<body>.+?)\."
)
STATUS_CONTROL_SUMMARY_RE = re.compile(
    r"The active control-level source of truth .* currently has `(?P<total>\d+)` open controls: (?P<body>.+?)\."
)
STATUS_COUNT_PAIR_RE = re.compile(r"(?P<label>[A-Za-z& -]+?) `(?P<count>\d+)`")
COMPANION_BLOCKER_RE = re.compile(
    r"status:\s*(?:reopened|open|blocking)|\bdoes not sign off\b|\breopened and blocking\b",
    re.IGNORECASE,
)
COMPANION_UNCHECKED_ROW_RE = re.compile(r"^- \[ \] ", re.MULTILINE)
COMPANION_NONZERO_SUMMARY_RE = re.compile(
    r"^\| [^|]+ \|(?: [^|]+ \|){0,3} (?P<count>[1-9]\d*) \| [^|]*"
    r"(?:reopened|blocking|open)",
    re.IGNORECASE | re.MULTILINE,
)
MOCK_EVIDENCE_KINDS = {"prototype_mock", "non_authoritative_mock_capture"}
NON_CLOSING_EVIDENCE_TYPES = {
    "local prototype_mock",
    "prototype_mock",
    "prototype mock",
    "mock",
    "fixture",
    "intercepted",
    "mixed",
    "local mock",
    "local fixture",
    "prototype fixture",
}


@dataclass(frozen=True)
class SummaryRow:
    label: str
    count: int
    status: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AssertionError(f"missing required file: {path.relative_to(ROOT)}") from None


def validate_companion_audit_blockers() -> None:
    """Block zero-gap bookkeeping while companion audits still say reopened/blocking."""
    blockers: list[str] = []
    for path in sorted(ROOT.glob(COMPANION_AUDIT_GLOB)):
        if path == AUDIT_PATH or not path.is_file():
            continue
        text = _read_text(path)
        if (
            COMPANION_BLOCKER_RE.search(text) or
            COMPANION_UNCHECKED_ROW_RE.search(text) or
            COMPANION_NONZERO_SUMMARY_RE.search(text)
        ):
            blockers.append(path.relative_to(ROOT).as_posix())
    if blockers:
        joined = ", ".join(blockers)
        raise AssertionError(
            "companion audit blocker(s) remain active and must be superseded row-by-row before signoff: "
            f"{joined}"
        )


def _load_manifest() -> dict:
    try:
        return json.loads(_read_text(MANIFEST_PATH))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"invalid JSON in {MANIFEST_PATH.relative_to(ROOT)}: {exc}") from exc


def _retired_current_evidence_reports(manifest: dict) -> set[str]:
    return {
        str(item).strip()
        for item in manifest.get("retired_current_evidence_reports") or []
        if str(item).strip()
    }


def _retired_current_evidence_dirs(manifest: dict) -> set[str]:
    dirs: set[str] = set()
    for report in _retired_current_evidence_reports(manifest):
        parent = Path(report).parent.as_posix()
        if parent and parent != ".":
            dirs.add(parent)
    return dirs


def _is_retired_current_evidence_path(manifest: dict, path: str) -> bool:
    normalized = str(path).strip()
    if not normalized:
        return False
    if normalized in _retired_current_evidence_reports(manifest):
        return True
    return any(
        normalized == evidence_dir or normalized.startswith(f"{evidence_dir}/")
        for evidence_dir in _retired_current_evidence_dirs(manifest)
    )


def _current_manifest_version_tokens(manifest: dict) -> set[str]:
    paths = [
        str(manifest.get("global_current_evidence_dir") or ""),
        *[str(path) for path in manifest.get("allowed_functional_evidence_reports") or []],
        *[str(path) for path in manifest.get("allowed_capture_health_evidence_reports") or []],
        *[str(path) for path in manifest.get("allowed_live_truth_evidence_reports") or []],
        *[str((item or {}).get("path") or "") for item in manifest.get("allowed_process_evidence_artifacts") or []],
        *[str((item or {}).get("current") or "") for item in manifest.get("allowed_process_evidence_artifacts") or []],
    ]
    tokens: set[str] = set()
    for path in paths:
        if _is_retired_current_evidence_path(manifest, path):
            continue
        tokens.update(match.group(1) for match in re.finditer(r"-v(\d+)(?:-|/)", path))
    return tokens


def _truth_evidence_reports(manifest: dict) -> set[str]:
    return {
        str(item).strip()
        for item in manifest.get("allowed_live_truth_evidence_reports") or []
        if str(item).strip()
    }


def _registered_evidence_artifacts(manifest: dict) -> set[str]:
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    artifacts = {
        f"{evidence_dir}/prototype-current-report.json" if evidence_dir else "",
        *[str(path).strip() for path in manifest.get("allowed_functional_evidence_reports") or []],
        *[str(path).strip() for path in manifest.get("allowed_capture_health_evidence_reports") or []],
        *[str(path).strip() for path in manifest.get("allowed_live_truth_evidence_reports") or []],
        *[str(path).strip() for path in manifest.get("retired_current_evidence_reports") or []],
    }
    for key in (
        "allowed_process_evidence_artifacts",
        "allowed_current_visual_evidence_artifacts",
        "allowed_extra_visual_state_artifacts",
        "allowed_live_visual_evidence_artifacts",
    ):
        for item in manifest.get(key) or []:
            value = _relative_path(str((item or {}).get("path") or ""))
            if value.endswith(".json"):
                artifacts.add(value)
    for item in manifest.get("allowed_process_evidence_artifacts") or []:
        for key in ("path", "sourceReport", "sourceManifest"):
            value = _relative_path(str((item or {}).get(key) or ""))
            if value.endswith(".json"):
                artifacts.add(value)
    return {path for path in artifacts if path}


def validate_no_unregistered_current_evidence_reports() -> None:
    manifest = _load_manifest()
    cutoff = str(manifest.get("global_current_evidence_generated_at") or "").strip()
    if not cutoff:
        raise AssertionError("reference_manifest.json has no global_current_evidence_generated_at")
    registered = _registered_evidence_artifacts(manifest)
    unregistered: list[str] = []
    for artifact_path in sorted((ROOT / "docs/northstar_visual_qa").glob("**/*.json")):
        relative = artifact_path.relative_to(ROOT).as_posix()
        if relative in registered:
            continue
        try:
            report = json.loads(artifact_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if relative in registered:
                raise AssertionError(f"invalid JSON in registered visual QA report {relative}: {exc}") from exc
            continue
        if not isinstance(report, dict):
            continue
        generated_at = str(report.get("generatedAt") or "").strip()
        if generated_at and generated_at >= cutoff:
            unregistered.append(relative)
    if unregistered:
        raise AssertionError(
            "current-era visual QA JSON artifact(s) are neither manifest-allowed nor retired: "
            + ", ".join(unregistered)
        )


def _parse_summary(lines: Iterable[str]) -> dict[str, SummaryRow]:
    rows: dict[str, SummaryRow] = {}
    for line in lines:
        match = SUMMARY_ROW_RE.match(line.strip())
        if not match:
            continue
        label = match.group("label").strip()
        if label == "---":
            continue
        raw_count = match.group("count").strip()
        if raw_count == "---" or raw_count == "Open Gaps":
            continue
        if raw_count.upper() == "TBD":
            raise AssertionError(f"summary row for {label} still has TBD open gaps")
        try:
            count = int(raw_count)
        except ValueError:
            raise AssertionError(f"summary row for {label} has non-numeric open gap count {raw_count!r}") from None
        rows[label] = SummaryRow(label=label, count=count, status=match.group("status").strip())
    return rows


def _parse_sections(lines: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for line in lines:
        match = SECTION_RE.match(line.rstrip())
        if match:
            current = match.group("label").strip()
            counts[current] = 0
            continue
        if current and line.startswith("- [ ]"):
            counts[current] += 1
    return counts


def _parse_control_summary(lines: Iterable[str]) -> dict[str, SummaryRow]:
    rows: dict[str, SummaryRow] = {}
    for line in lines:
        match = CONTROL_SUMMARY_ROW_RE.match(line.strip())
        if not match:
            continue
        label = match.group("label").strip()
        raw_count = match.group("count").strip()
        if label in {"---", "Page"} or raw_count in {"---", "Open Controls"}:
            continue
        try:
            count = int(raw_count)
        except ValueError:
            continue
        rows[label] = SummaryRow(label=label, count=count, status=match.group("status").strip())
    return rows


def _parse_control_sections(lines: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    for line in lines:
        match = CONTROL_SECTION_RE.match(line.rstrip())
        if match:
            current = match.group("label").strip()
            counts[current] = 0
            continue
        if current and line.startswith("- [ ]"):
            counts[current] += 1
    return counts


def _require_file(relative_path: str) -> None:
    path = ROOT / relative_path
    if not path.exists():
        raise AssertionError(f"manifest reference does not exist: {relative_path}")


def _sha256_file(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        raise AssertionError(f"hash-pinned evidence path does not exist: {relative_path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: str) -> str:
    return value.replace("../", "").strip()


def _visual_qa_top_dir(value: str) -> str:
    path = Path(_relative_path(str(value or "")))
    parts = path.parts
    if len(parts) < 3 or parts[:2] != VISUAL_QA_PREFIX_PARTS:
        return ""
    return Path(*parts[:3]).as_posix()


def _manifest_visual_qa_dirs(manifest: dict) -> set[str]:
    dirs: set[str] = set()

    def add(value: str | None) -> None:
        top_dir = _visual_qa_top_dir(str(value or ""))
        if top_dir:
            dirs.add(top_dir)

    add(str(manifest.get("global_current_evidence_dir") or ""))
    for key in (
        "allowed_functional_evidence_reports",
        "allowed_capture_health_evidence_reports",
        "allowed_live_truth_evidence_reports",
        "retired_current_evidence_reports",
    ):
        for value in manifest.get(key) or []:
            add(str(value))
    for key in (
        "allowed_functional_evidence_report_pins",
        "allowed_capture_health_evidence_report_pins",
        "allowed_live_truth_evidence_report_pins",
        "global_current_evidence_hashes",
    ):
        values = manifest.get(key) or {}
        if isinstance(values, dict):
            for value in values:
                add(str(value))
    for key in (
        "allowed_process_evidence_artifacts",
        "allowed_current_visual_evidence_artifacts",
        "allowed_extra_visual_state_artifacts",
        "allowed_live_visual_evidence_artifacts",
    ):
        for item in manifest.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in (
                "path",
                "current",
                "sourceReport",
                "sourceManifest",
                "fullPageScreenshot",
                "fullPagePath",
            ):
                add(str(item.get(field) or ""))
    return dirs


def validate_visual_qa_retention() -> None:
    manifest = _load_manifest()
    allowed_dirs = _manifest_visual_qa_dirs(manifest)
    if not VISUAL_QA_ROOT.exists():
        return
    unexpected_dirs = []
    generated_state_dirs = []
    for child in sorted(VISUAL_QA_ROOT.iterdir()):
        if not child.is_dir():
            continue
        relative = child.relative_to(ROOT).as_posix()
        if relative not in allowed_dirs:
            unexpected_dirs.append(relative)
    for path in sorted(VISUAL_QA_ROOT.rglob("*")):
        if not path.is_dir():
            continue
        if path.name == "downloads" or path.name.startswith("chrome-profile"):
            generated_state_dirs.append(path.relative_to(ROOT).as_posix())
    if unexpected_dirs:
        raise AssertionError(
            "unregistered North Star visual QA directories must be pruned or manifest-pinned: "
            + ", ".join(unexpected_dirs[:25])
            + (f", ... {len(unexpected_dirs) - 25} more" if len(unexpected_dirs) > 25 else "")
        )
    if generated_state_dirs:
        raise AssertionError(
            "generated browser/download state must not live under North Star visual QA evidence: "
            + ", ".join(generated_state_dirs[:25])
            + (f", ... {len(generated_state_dirs) - 25} more" if len(generated_state_dirs) > 25 else "")
        )


def validate_manifest() -> None:
    manifest = _load_manifest()
    routes = manifest.get("routes")
    if not isinstance(routes, list) or not routes:
        raise AssertionError("reference_manifest.json must define a non-empty routes list")
    seen: set[str] = set()
    for route in routes:
        key = str(route.get("route") or "").strip()
        label = str(route.get("label") or "").strip()
        if not key or not label:
            raise AssertionError(f"manifest route is missing route/label: {route!r}")
        if key in seen:
            raise AssertionError(f"duplicate manifest route: {key}")
        seen.add(key)
        refs = route.get("prototype_references")
        if not isinstance(refs, list) or not refs:
            raise AssertionError(f"manifest route {key} has no prototype references")
        for ref in refs:
            path = str((ref or {}).get("path") or "")
            if path.endswith(".png") or path.endswith(".jsx") or path.endswith(".html"):
                _require_file(path)
        if route.get("standalone_visual_gate") and not route.get("current_screenshot_pattern"):
            raise AssertionError(f"standalone visual route {key} has no current screenshot pattern")


def _required_viewports(manifest: dict) -> list[str]:
    viewports = manifest.get("required_viewports") or []
    if not isinstance(viewports, list) or not viewports:
        raise AssertionError("reference_manifest.json must define required_viewports")
    return [str(viewport).strip() for viewport in viewports if str(viewport).strip()]


def _format_pattern(pattern: str, viewport: str) -> str:
    if "{viewport}" not in pattern:
        raise AssertionError(f"screenshot pattern is missing {{viewport}} placeholder: {pattern}")
    return pattern.replace("{viewport}", viewport)


def _load_json_file(relative_path: str, *, label: str) -> dict:
    path = ROOT / relative_path
    if not path.exists():
        raise AssertionError(f"{label} does not exist: {relative_path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"invalid JSON in {relative_path}: {exc}") from exc


def _current_report_visual_paths(manifest: dict) -> set[str]:
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    if not evidence_dir:
        return set()
    report_path = f"{evidence_dir}/prototype-current-report.json"
    report = _load_json_file(report_path, label="current evidence report")
    paths: set[str] = set()
    for capture in report.get("captures") or []:
        for key in ("screenshot", "fullPageScreenshot", "mainBottomScreenshot"):
            value = _relative_path(str(capture.get(key) or ""))
            if value:
                paths.add(value)
    return paths


def _extra_visual_state_artifacts(manifest: dict) -> dict[str, dict]:
    extras = manifest.get("allowed_extra_visual_state_artifacts") or []
    if not isinstance(extras, list):
        raise AssertionError("allowed_extra_visual_state_artifacts must be a list when present")
    artifacts: dict[str, dict] = {}
    for index, item in enumerate(extras, start=1):
        if not isinstance(item, dict):
            raise AssertionError(f"allowed_extra_visual_state_artifacts[{index}] must be an object")
        path = _relative_path(str(item.get("path") or ""))
        if not path:
            raise AssertionError(f"allowed_extra_visual_state_artifacts[{index}] is missing path")
        artifacts[path] = item
        full_path = _relative_path(str(item.get("fullPagePath") or ""))
        if full_path:
            artifacts[full_path] = {**item, "path": full_path}
    return artifacts


def _supplemental_current_visual_artifacts(manifest: dict) -> dict[str, dict]:
    entries = manifest.get("allowed_current_visual_evidence_artifacts") or []
    if not isinstance(entries, list):
        raise AssertionError("allowed_current_visual_evidence_artifacts must be a list when present")
    artifacts: dict[str, dict] = {}
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise AssertionError(f"allowed_current_visual_evidence_artifacts[{index}] must be an object")
        path = _relative_path(str(item.get("path") or ""))
        if not path:
            raise AssertionError(f"allowed_current_visual_evidence_artifacts[{index}] is missing path")
        artifacts[path] = item
    return artifacts


def _process_evidence_artifacts(manifest: dict) -> dict[str, dict]:
    entries = manifest.get("allowed_process_evidence_artifacts") or []
    if not isinstance(entries, list):
        raise AssertionError("allowed_process_evidence_artifacts must be a list when present")
    artifacts: dict[str, dict] = {}
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise AssertionError(f"allowed_process_evidence_artifacts[{index}] must be an object")
        artifact_path = _relative_path(str(item.get("path") or ""))
        if not artifact_path:
            raise AssertionError(f"allowed_process_evidence_artifacts[{index}] is missing path")
        artifacts[artifact_path] = item
    return artifacts


def _live_visual_evidence_artifacts(manifest: dict) -> dict[str, dict]:
    entries = manifest.get("allowed_live_visual_evidence_artifacts") or []
    if not isinstance(entries, list):
        raise AssertionError("allowed_live_visual_evidence_artifacts must be a list when present")
    artifacts: dict[str, dict] = {}
    for index, item in enumerate(entries, start=1):
        if not isinstance(item, dict):
            raise AssertionError(f"allowed_live_visual_evidence_artifacts[{index}] must be an object")
        artifact_path = _relative_path(str(item.get("path") or ""))
        if not artifact_path:
            raise AssertionError(f"allowed_live_visual_evidence_artifacts[{index}] is missing path")
        artifacts[artifact_path] = item
    return artifacts


def _valid_current_visual_paths(manifest: dict) -> set[str]:
    return (
        _current_report_visual_paths(manifest)
        | set(_extra_visual_state_artifacts(manifest))
        | set(_supplemental_current_visual_artifacts(manifest))
    )


def validate_supplemental_current_visual_artifacts(manifest: dict) -> None:
    for artifact_path, item in _supplemental_current_visual_artifacts(manifest).items():
        if not (ROOT / artifact_path).exists():
            raise AssertionError(f"supplemental current visual artifact does not exist: {artifact_path}")
        expected_hash = str(item.get("sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"supplemental current visual artifact is missing sha256: {artifact_path}")
        actual_hash = _sha256_file(artifact_path)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"supplemental current visual artifact hash mismatch for {artifact_path}: "
                f"actual={actual_hash}, manifest={expected_hash}"
            )
        source_report_path = _relative_path(str(item.get("sourceReport") or ""))
        if not source_report_path:
            raise AssertionError(f"supplemental current visual artifact is missing sourceReport: {artifact_path}")
        source_report = _load_json_file(source_report_path, label="supplemental current visual source report")
        if source_report.get("passed") is not True:
            raise AssertionError(f"supplemental current visual source report did not pass: {source_report_path}")
        expected_generated_at = str(item.get("generatedAt") or "").strip()
        if not expected_generated_at or source_report.get("generatedAt") != expected_generated_at:
            raise AssertionError(
                f"supplemental current visual source report generatedAt mismatch for {artifact_path}: "
                f"report={source_report.get('generatedAt')}, manifest={expected_generated_at}"
            )
        expected_evidence_kind = str(item.get("evidenceKind") or "").strip()
        if not expected_evidence_kind or source_report.get("evidenceKind") != expected_evidence_kind:
            raise AssertionError(
                f"supplemental current visual source report evidenceKind mismatch for {artifact_path}: "
                f"report={source_report.get('evidenceKind')}, manifest={expected_evidence_kind}"
            )
        expected_mock_api = item.get("mockApi")
        if expected_mock_api is None or bool(source_report.get("mockApi")) != bool(expected_mock_api):
            raise AssertionError(
                f"supplemental current visual source report mockApi mismatch for {artifact_path}: "
                f"report={source_report.get('mockApi')}, manifest={expected_mock_api}"
            )
        if source_report.get("mockApi") and "not live Databricks evidence" not in str(source_report.get("mockEvidenceWarning") or ""):
            raise AssertionError(f"supplemental mock visual source report lacks warning: {source_report_path}")
        expected_base_url = str(item.get("baseUrl") or "").strip()
        if expected_base_url and source_report.get("baseUrl") != expected_base_url:
            raise AssertionError(
                f"supplemental current visual source report baseUrl mismatch for {artifact_path}: "
                f"report={source_report.get('baseUrl')}, manifest={expected_base_url}"
            )
        route = str(item.get("route") or "").strip()
        viewport = str(item.get("viewport") or "").strip()
        if not route or not viewport:
            raise AssertionError(f"supplemental current visual artifact missing route/viewport: {artifact_path}")
        matched = False
        for capture in source_report.get("captures") or []:
            if str((capture or {}).get("route") or "").strip() != route:
                continue
            if str((capture or {}).get("viewport") or "").strip() != viewport:
                continue
            capture_paths = {
                _relative_path(str((capture or {}).get(key) or ""))
                for key in ("screenshot", "fullPageScreenshot", "mainBottomScreenshot")
            }
            if artifact_path in capture_paths and capture.get("loaded") is True:
                matched = True
                break
        if not matched:
            raise AssertionError(
                f"supplemental current visual artifact is not backed by a loaded source capture "
                f"{source_report_path}:{route}:{viewport}: {artifact_path}"
            )


def validate_live_visual_evidence_artifacts(manifest: dict) -> None:
    for artifact_path, item in _live_visual_evidence_artifacts(manifest).items():
        if not (ROOT / artifact_path).exists():
            raise AssertionError(f"live visual evidence artifact does not exist: {artifact_path}")
        expected_hash = str(item.get("sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"live visual evidence artifact is missing sha256 content pin: {artifact_path}")
        actual_hash = _sha256_file(artifact_path)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"live visual evidence artifact hash mismatch for {artifact_path}: "
                f"actual={actual_hash}, manifest={expected_hash}"
            )
        source_report_path = _relative_path(str(item.get("sourceReport") or ""))
        if not source_report_path:
            raise AssertionError(f"live visual evidence artifact is missing sourceReport: {artifact_path}")
        source_report = _load_json_file(source_report_path, label="live visual source report")
        if source_report.get("passed") is not True:
            raise AssertionError(f"live visual source report did not pass: {source_report_path}")
        if source_report.get("mockApi") is not False:
            raise AssertionError(f"live visual source report must be non-mock: {source_report_path}")
        expected_generated_at = str(item.get("generatedAt") or "").strip()
        if not expected_generated_at or source_report.get("generatedAt") != expected_generated_at:
            raise AssertionError(
                f"live visual source report generatedAt mismatch for {artifact_path}: "
                f"report={source_report.get('generatedAt')}, manifest={expected_generated_at}"
            )
        expected_evidence_kind = str(item.get("evidenceKind") or "").strip()
        if expected_evidence_kind != "live_databricks" or source_report.get("evidenceKind") != expected_evidence_kind:
            raise AssertionError(
                f"live visual source report evidenceKind mismatch for {artifact_path}: "
                f"report={source_report.get('evidenceKind')}, manifest={expected_evidence_kind}"
            )
        expected_base_url = str(item.get("baseUrl") or "").strip()
        if expected_base_url and source_report.get("appUrl") != expected_base_url and source_report.get("baseUrl") != expected_base_url:
            raise AssertionError(
                f"live visual source report baseUrl/appUrl mismatch for {artifact_path}: "
                f"report={source_report.get('appUrl') or source_report.get('baseUrl')}, manifest={expected_base_url}"
            )
        expected_build_id = str(item.get("buildId") or "").strip()
        if expected_build_id and source_report.get("buildId") != expected_build_id:
            raise AssertionError(
                f"live visual source report buildId mismatch for {artifact_path}: "
                f"report={source_report.get('buildId')}, manifest={expected_build_id}"
            )
        route = str(item.get("route") or "").strip()
        viewport = str(item.get("viewport") or "").strip()
        if not route or not viewport:
            raise AssertionError(f"live visual evidence artifact missing route/viewport: {artifact_path}")
        matched = False
        for capture in source_report.get("captures") or []:
            raw_viewport = (capture or {}).get("viewport")
            if isinstance(raw_viewport, dict):
                capture_viewport = str(raw_viewport.get("name") or "").strip()
            else:
                capture_viewport = str(raw_viewport or "").strip()
            capture_path = _relative_path(str((capture or {}).get("screenshot") or ""))
            capture_passed = capture.get("passed") is True or capture.get("loaded") is True
            capture_route = str((capture or {}).get("route") or "").strip()
            if capture_route == route and capture_viewport == viewport and capture_path == artifact_path and capture_passed:
                matched = True
                break
        if not matched:
            raise AssertionError(
                f"live visual evidence artifact is not backed by a passed capture "
                f"{source_report_path}:{route}:{viewport}: {artifact_path}"
            )


def validate_process_evidence_artifacts(manifest: dict) -> None:
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    if not evidence_dir:
        raise AssertionError("process evidence artifacts require global_current_evidence_dir")
    current_report_path = f"{evidence_dir}/prototype-current-report.json"
    current_report = _load_json_file(current_report_path, label="current evidence report")
    current_generated_at = str(current_report.get("generatedAt") or "").strip()
    current_evidence_kind = str(current_report.get("evidenceKind") or "").strip()
    current_visual_paths = _current_report_visual_paths(manifest)
    current_hashes = manifest.get("global_current_evidence_hashes") or {}
    if not isinstance(current_hashes, dict):
        raise AssertionError("global_current_evidence_hashes must be an object")
    for artifact_path, item in _process_evidence_artifacts(manifest).items():
        if not (ROOT / artifact_path).exists():
            raise AssertionError(f"process evidence artifact does not exist: {artifact_path}")
        expected_hash = str(item.get("sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"process evidence artifact is missing sha256 content pin: {artifact_path}")
        actual_hash = _sha256_file(artifact_path)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"process evidence artifact hash mismatch for {artifact_path}: "
                f"actual={actual_hash}, manifest={expected_hash}"
            )
        artifact_kind = str(item.get("kind") or "").strip()
        if artifact_kind not in {"side-by-side", "pixel-diff", "process-readme", "audit-manifest"}:
            raise AssertionError(f"process evidence artifact has unsupported kind: {artifact_path}")
        if artifact_kind == "audit-manifest":
            audit_manifest = _load_json_file(artifact_path, label="process audit manifest")
            generated_at = str(item.get("generatedAt") or "").strip()
            if not generated_at or str(audit_manifest.get("generatedAt") or "").strip() != generated_at:
                raise AssertionError(
                    f"process audit manifest generatedAt mismatch for {artifact_path}: "
                    f"manifest={generated_at!r}, report={audit_manifest.get('generatedAt')!r}"
                )
            evidence_kind = str(item.get("evidenceKind") or "").strip()
            if not evidence_kind:
                raise AssertionError(f"process audit manifest is missing evidenceKind: {artifact_path}")
            pairs = audit_manifest.get("pairs") or []
            summary = audit_manifest.get("summary") or {}
            pair_count = int(summary.get("pairCount") or len(pairs))
            blocked_pair_count = int(
                summary.get("blockedPairCount")
                if summary.get("blockedPairCount") is not None
                else len([pair for pair in pairs if (pair or {}).get("visualGate") == "BLOCKED"])
            )
            if pair_count <= 0:
                raise AssertionError(f"process audit manifest has no visual pairs: {artifact_path}")
            if blocked_pair_count <= 0:
                raise AssertionError(
                    f"process audit manifest must be blocking evidence unless every pair is closed elsewhere: {artifact_path}"
                )
            if any(str((pair or {}).get("visualGate") or "") != "BLOCKED" for pair in pairs):
                raise AssertionError(
                    f"process audit manifest contains a non-BLOCKED pair; route rows must cite its closure directly: "
                    f"{artifact_path}"
                )
            continue
        route = str(item.get("route") or "").strip()
        if not route:
            raise AssertionError(f"process evidence artifact is missing route: {artifact_path}")
        reference = _relative_path(str(item.get("reference") or ""))
        if not reference:
            raise AssertionError(f"process evidence artifact is missing reference: {artifact_path}")
        if not (ROOT / reference).exists():
            raise AssertionError(f"process evidence artifact reference does not exist: {artifact_path} -> {reference}")
        current = _relative_path(str(item.get("current") or ""))
        if not current:
            raise AssertionError(f"process evidence artifact is missing current screenshot: {artifact_path}")
        evidence_kind = str(item.get("evidenceKind") or "").strip()
        if evidence_kind == "live_databricks":
            if not (ROOT / current).exists():
                raise AssertionError(f"live process evidence current screenshot does not exist: {artifact_path} -> {current}")
            expected_current_hash = str(item.get("currentSha256") or "").strip()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_current_hash):
                raise AssertionError(f"live process evidence current screenshot is missing currentSha256 pin: {artifact_path}")
            actual_current_hash = _sha256_file(current)
            if actual_current_hash != expected_current_hash:
                raise AssertionError(
                    f"live process evidence current screenshot hash mismatch for {artifact_path}: "
                    f"actual={actual_current_hash}, manifest={expected_current_hash}"
                )
            source_report_path = _relative_path(str(item.get("sourceReport") or ""))
            if not source_report_path:
                raise AssertionError(f"live process evidence artifact is missing sourceReport: {artifact_path}")
            source_report = _load_json_file(source_report_path, label="live process source report")
            if source_report.get("passed") is not True:
                raise AssertionError(f"live process source report did not pass: {source_report_path}")
            if source_report.get("mockApi") is not False:
                raise AssertionError(f"live process source report must be non-mock: {source_report_path}")
            if source_report.get("evidenceKind") != "live_databricks":
                raise AssertionError(
                    f"live process source report evidenceKind mismatch for {artifact_path}: "
                    f"report={source_report.get('evidenceKind')}"
                )
            generated_at = str(item.get("generatedAt") or "").strip()
            if not generated_at or source_report.get("generatedAt") != generated_at:
                raise AssertionError(
                    f"live process source report generatedAt mismatch for {artifact_path}: "
                    f"report={source_report.get('generatedAt')}, manifest={generated_at}"
                )
            expected_base_url = str(item.get("baseUrl") or "").strip()
            if expected_base_url and source_report.get("appUrl") != expected_base_url and source_report.get("baseUrl") != expected_base_url:
                raise AssertionError(
                    f"live process source report baseUrl/appUrl mismatch for {artifact_path}: "
                    f"report={source_report.get('appUrl') or source_report.get('baseUrl')}, manifest={expected_base_url}"
                )
            expected_build_id = str(item.get("buildId") or "").strip()
            if expected_build_id and source_report.get("buildId") != expected_build_id:
                raise AssertionError(
                    f"live process source report buildId mismatch for {artifact_path}: "
                    f"report={source_report.get('buildId')}, manifest={expected_build_id}"
                )
            viewport = str(item.get("viewport") or "").strip()
            if not viewport:
                raise AssertionError(f"live process evidence artifact is missing viewport: {artifact_path}")
            if artifact_kind == "side-by-side":
                matched = False
                for entry in source_report.get("sideBySide") or []:
                    if str((entry or {}).get("route") or "").strip() != route:
                        continue
                    if str((entry or {}).get("viewport") or "").strip() != viewport:
                        continue
                    if _relative_path(str((entry or {}).get("path") or "")) != artifact_path:
                        continue
                    if _relative_path(str((entry or {}).get("currentPath") or "")) != current:
                        continue
                    if _relative_path(str((entry or {}).get("mockupPath") or "")) != reference:
                        continue
                    matched = True
                    break
                if not matched:
                    raise AssertionError(
                        f"live process side-by-side artifact is not backed by source report entry: "
                        f"{source_report_path}:{route}:{viewport}: {artifact_path}"
                    )
            continue
        if not current.startswith(f"{evidence_dir}/"):
            raise AssertionError(
                f"process evidence artifact current screenshot is outside global_current_evidence_dir: {artifact_path} -> {current}"
            )
        if current not in current_visual_paths:
            raise AssertionError(
                f"process evidence artifact current screenshot is not in current capture report: {artifact_path} -> {current}"
            )
        if current not in current_hashes:
            raise AssertionError(
                f"process evidence artifact current screenshot is not content-pinned in global_current_evidence_hashes: "
                f"{artifact_path} -> {current}"
            )
        if evidence_kind != current_evidence_kind:
            raise AssertionError(
                f"process evidence artifact evidenceKind does not match current report: "
                f"{artifact_path} has {evidence_kind!r}, current report has {current_evidence_kind!r}"
            )
        generated_at = str(item.get("generatedAt") or "").strip()
        if generated_at != current_generated_at:
            raise AssertionError(
                f"process evidence artifact generatedAt does not match current report: "
                f"{artifact_path} has {generated_at!r}, current report has {current_generated_at!r}"
            )


def validate_extra_visual_state_artifacts(manifest: dict) -> None:
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    if not evidence_dir:
        return
    extras = _extra_visual_state_artifacts(manifest)
    for artifact_path, item in extras.items():
        if not artifact_path.startswith(f"{evidence_dir}/"):
            raise AssertionError(
                f"extra visual state artifact must live under global_current_evidence_dir: {artifact_path}"
            )
        if not (ROOT / artifact_path).exists():
            raise AssertionError(f"extra visual state artifact does not exist: {artifact_path}")
        full_page_path = _relative_path(str(item.get("fullPagePath") or ""))
        artifact_key = "fullPageScreenshot" if full_page_path and artifact_path == full_page_path else "screenshot"
        artifact_hash_field = "fullPageSha256" if artifact_key == "fullPageScreenshot" else "sha256"
        expected_artifact_hash = str(item.get(artifact_hash_field) or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_artifact_hash):
            raise AssertionError(
                f"extra visual state artifact is missing {artifact_hash_field} content pin: {artifact_path}"
            )
        source_report_path = _relative_path(str(item.get("sourceReport") or ""))
        if not source_report_path:
            raise AssertionError(f"extra visual state artifact is missing sourceReport: {artifact_path}")
        source_report = _load_json_file(source_report_path, label="extra visual state source report")
        expected_generated_at = str(item.get("generatedAt") or "").strip()
        expected_base_url = str(item.get("baseUrl") or "").strip()
        expected_evidence_kind = str(item.get("evidenceKind") or "").strip()
        if not expected_generated_at or source_report.get("generatedAt") != expected_generated_at:
            raise AssertionError(
                f"extra visual state source report generatedAt mismatch for {artifact_path}: "
                f"report={source_report.get('generatedAt')}, manifest={expected_generated_at}"
            )
        if not expected_base_url or source_report.get("baseUrl") != expected_base_url:
            raise AssertionError(
                f"extra visual state source report baseUrl mismatch for {artifact_path}: "
                f"report={source_report.get('baseUrl')}, manifest={expected_base_url}"
            )
        if not expected_evidence_kind or source_report.get("evidenceKind") != expected_evidence_kind:
            raise AssertionError(
                f"extra visual state source report evidenceKind mismatch for {artifact_path}: "
                f"report={source_report.get('evidenceKind')}, manifest={expected_evidence_kind}"
            )
        if source_report.get("passed") is not True:
            raise AssertionError(f"extra visual state source report did not pass: {source_report_path}")
        if source_report.get("mockApi") and "not live Databricks evidence" not in str(source_report.get("mockEvidenceWarning") or ""):
            raise AssertionError(f"extra mock visual state source report lacks warning: {source_report_path}")
        route = str(item.get("route") or "").strip()
        viewport = str(item.get("viewport") or "").strip()
        interaction = str(item.get("interaction") or "").strip()
        if not route or not viewport or not interaction:
            raise AssertionError(f"extra visual state artifact missing route/viewport/interaction: {artifact_path}")
        matched = False
        source_artifact_path = ""
        for entry in source_report.get("interactions") or []:
            if str(entry.get("route") or "") != route:
                continue
            if str(entry.get("viewport") or "") != viewport:
                continue
            if str(entry.get("interaction") or "") != interaction:
                continue
            source_artifact_path = _relative_path(str(entry.get(artifact_key) or ""))
            if (
                source_artifact_path
                and Path(source_artifact_path).name == Path(artifact_path).name
                and entry.get("loaded") is True
            ):
                matched = True
                break
        if not matched:
            raise AssertionError(
                f"extra visual state artifact is not backed by loaded source interaction "
                f"{source_report_path}:{route}:{interaction}:{viewport}: {artifact_path}"
            )
        if not (ROOT / source_artifact_path).exists():
            raise AssertionError(f"extra visual state source image is missing: {source_artifact_path}")
        artifact_hash = _sha256_file(artifact_path)
        source_hash = _sha256_file(source_artifact_path)
        if artifact_hash != source_hash:
            raise AssertionError(
                f"extra visual state artifact bytes do not match source interaction image: "
                f"{artifact_path} vs {source_artifact_path}"
            )
        if artifact_hash != expected_artifact_hash:
            raise AssertionError(
                f"extra visual state artifact hash mismatch for {artifact_path}: "
                f"actual={artifact_hash}, manifest={expected_artifact_hash}"
            )


def validate_current_evidence() -> None:
    manifest = _load_manifest()
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    if not evidence_dir:
        raise AssertionError("reference_manifest.json has no global_current_evidence_dir")
    evidence_root = ROOT / evidence_dir
    if not evidence_root.exists():
        raise AssertionError(f"current evidence directory does not exist: {evidence_dir}")
    report_path = evidence_root / "prototype-current-report.json"
    if not report_path.exists():
        raise AssertionError(f"current evidence directory has no prototype-current-report.json: {evidence_dir}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssertionError(f"invalid current evidence report JSON: {report_path.relative_to(ROOT)}: {exc}") from exc
    evidence_kind = str(report.get("evidenceKind") or "").strip()
    if not evidence_kind:
        raise AssertionError("current evidence report must declare evidenceKind")
    expected_generated_at = str(manifest.get("global_current_evidence_generated_at") or "").strip()
    expected_base_url = str(manifest.get("global_current_evidence_base_url") or "").strip()
    expected_evidence_kind = str(manifest.get("global_current_evidence_kind") or "").strip()
    expected_capture_command = str(manifest.get("global_current_capture_command") or "").strip()
    if not expected_generated_at or report.get("generatedAt") != expected_generated_at:
        raise AssertionError(
            f"current evidence report generatedAt does not match manifest pin: report={report.get('generatedAt')}, manifest={expected_generated_at}"
        )
    if not expected_base_url or report.get("baseUrl") != expected_base_url:
        raise AssertionError(
            f"current evidence report baseUrl does not match manifest pin: report={report.get('baseUrl')}, manifest={expected_base_url}"
        )
    if not expected_evidence_kind or evidence_kind != expected_evidence_kind:
        raise AssertionError(
            f"current evidence report evidenceKind does not match manifest pin: report={evidence_kind}, manifest={expected_evidence_kind}"
        )
    if "axiom_prototype_current_capture.mjs" not in expected_capture_command:
        raise AssertionError("reference_manifest.json must record the current capture command")
    if report.get("mockApi") or evidence_kind in MOCK_EVIDENCE_KINDS:
        raise AssertionError(
            "active current evidence must be customer-facing runtime/live evidence with mockApi=false; "
            f"got evidenceKind={evidence_kind!r}, mockApi={report.get('mockApi')!r}"
        )
    if report.get("passed") is not True:
        raise AssertionError("current evidence report must have passed=true for capture-health use")
    for key in ("pageErrors", "requestFailures"):
        values = report.get(key) or []
        if values:
            raise AssertionError(f"current evidence report has non-empty {key}")
    if any(str((entry or {}).get("type") or "").lower() == "error" for entry in report.get("console") or []):
        raise AssertionError("current evidence report contains console error entries")
    viewports = _required_viewports(manifest)
    report_viewports = {str((viewport or {}).get("name") or "").strip() for viewport in report.get("viewports") or []}
    missing_report_viewports = [viewport for viewport in viewports if viewport not in report_viewports]
    if missing_report_viewports:
        raise AssertionError(f"current evidence report is missing required viewport(s): {', '.join(missing_report_viewports)}")
    report_routes = {str(route).strip() for route in report.get("selectedRoutes") or []}
    captures = report.get("captures") or []
    hash_pins = manifest.get("global_current_evidence_hashes")
    if not isinstance(hash_pins, dict) or not hash_pins:
        raise AssertionError("reference_manifest.json must content-pin current screenshots in global_current_evidence_hashes")
    seen_hash_pins: set[str] = set()
    expected_capture_count = len([
        route for route in manifest.get("routes") or [] if route.get("standalone_visual_gate")
    ]) * len(viewports)
    if int(report.get("expectedCaptureCount") or 0) != expected_capture_count:
        raise AssertionError(
            f"current evidence report expectedCaptureCount mismatch: report={report.get('expectedCaptureCount')}, actual={expected_capture_count}"
        )
    if len(captures) != expected_capture_count:
        raise AssertionError(f"current evidence report has {len(captures)} captures; expected {expected_capture_count}")
    for capture in captures:
        if capture.get("loaded") is not True:
            raise AssertionError(f"current evidence capture did not load: {capture.get('route')} {capture.get('viewport')}")
        for key in ("screenshot", "fullPageScreenshot", "mainBottomScreenshot"):
            value = _relative_path(str(capture.get(key) or ""))
            if key == "mainBottomScreenshot" and not value:
                continue
            if not value or not (ROOT / value).exists():
                raise AssertionError(f"current evidence capture missing {key}: {value}")
            expected_hash = str(hash_pins.get(value) or "").strip()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise AssertionError(f"current evidence capture is missing content hash pin: {value}")
            actual_hash = _sha256_file(value)
            if actual_hash != expected_hash:
                raise AssertionError(
                    f"current evidence capture hash mismatch for {value}: actual={actual_hash}, manifest={expected_hash}"
                )
            seen_hash_pins.add(value)
    extra_hash_pins = sorted(set(hash_pins) - seen_hash_pins)
    if extra_hash_pins:
        raise AssertionError(
            "global_current_evidence_hashes contains paths that are not in the current capture report: "
            + ", ".join(extra_hash_pins)
        )
    for route in manifest.get("routes") or []:
        if not route.get("standalone_visual_gate"):
            continue
        key = str(route.get("route") or "").strip()
        if key not in report_routes:
            raise AssertionError(f"current evidence report did not capture manifest route: {key}")
        label = str(route.get("label") or route.get("route") or "").strip()
        screenshot_pattern = str(route.get("current_screenshot_pattern") or "").strip()
        full_pattern = str(route.get("full_current_screenshot_pattern") or "").strip()
        if not screenshot_pattern or not full_pattern:
            raise AssertionError(f"{label} must define viewport and full-page screenshot patterns")
        for viewport in viewports:
            for pattern in (screenshot_pattern, full_pattern):
                relative = _format_pattern(pattern, viewport)
                if not (evidence_root / relative).exists():
                    raise AssertionError(f"{label} is missing current screenshot evidence: {evidence_dir}/{relative}")
    validate_extra_visual_state_artifacts(manifest)
    validate_supplemental_current_visual_artifacts(manifest)
    validate_process_evidence_artifacts(manifest)
    validate_live_visual_evidence_artifacts(manifest)


def validate_audit() -> None:
    text = _read_text(AUDIT_PATH)
    if "TBD" in text or "Audit pending" in text:
        raise AssertionError("full_page_audit.md still contains TBD or Audit pending")
    lines = text.splitlines()
    summary = _parse_summary(lines)
    section_counts = _parse_sections(lines)
    if not summary:
        raise AssertionError("full_page_audit.md has no page status summary rows")
    for label, row in summary.items():
        if label not in section_counts:
            raise AssertionError(f"summary row {label} has no matching '## {label} Gaps' section")
        actual = section_counts[label]
        if actual != row.count:
            raise AssertionError(f"summary count mismatch for {label}: summary={row.count}, actual={actual}")
        if row.count > 0 and row.status.lower() not in {"blocked", "open"}:
            raise AssertionError(f"{label} has {row.count} open gaps but status is {row.status!r}")
        if row.count == 0 and row.status.lower() in {"blocked", "open"}:
            raise AssertionError(f"{label} has zero open gaps but status is still {row.status!r}")


def _validate_gap_rows(path: Path, *, enforce_categories: bool) -> None:
    manifest = _load_manifest()
    current_evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    current_manifest_versions = _current_manifest_version_tokens(manifest)
    valid_current_visual_paths = _valid_current_visual_paths(manifest)
    allowed_process_artifacts = set(_process_evidence_artifacts(manifest))
    allowed_functional_reports = {
        str(item).strip()
        for item in manifest.get("allowed_functional_evidence_reports") or []
        if str(item).strip()
    }
    allowed_capture_health_reports = {
        str(item).strip()
        for item in manifest.get("allowed_capture_health_evidence_reports") or []
        if str(item).strip()
    }
    allowed_truth_reports = _truth_evidence_reports(manifest)
    retired_current_reports = {
        str(item).strip()
        for item in manifest.get("retired_current_evidence_reports") or []
        if str(item).strip()
    }

    def evidence_kind(evidence_path: str) -> str:
        current_prefix = f"{current_evidence_dir}/"
        if _is_retired_current_evidence_path(manifest, evidence_path):
            return "retired_current_evidence"
        if Path(evidence_path).suffix.lower() == ".png" and evidence_path in valid_current_visual_paths:
            return "current_screenshot"
        if evidence_path in allowed_functional_reports:
            return "functional_report"
        if evidence_path in allowed_capture_health_reports:
            return "current_report"
        if evidence_path in allowed_truth_reports:
            return "truth_report"
        if evidence_path.startswith(current_prefix):
            suffix = Path(evidence_path).suffix.lower()
            if suffix == ".png" and evidence_path in valid_current_visual_paths:
                return "current_screenshot"
            if suffix == ".png":
                return "unreported_current_screenshot"
            if suffix == ".json":
                return "current_report"
            return "current_artifact"
        if evidence_path.startswith("docs/northstar_gap_analysis/"):
            return "ledger"
        if evidence_path in {"AGENT_CHANGELOG.md", "IMPLEMENTATION_STATUS.md"}:
            return "process_log"
        if evidence_path in allowed_process_artifacts:
            return "process_artifact"
        if evidence_path in _live_visual_evidence_artifacts(manifest):
            return "live_visual_screenshot"
        return "stale_or_external"

    for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
        evidence_paths: list[str] = []
        if MALFORMED_CHECKBOX_RE.match(line) and not line.startswith("- ["):
            raise AssertionError(
                f"{path.relative_to(ROOT)}:{lineno} has an indented or malformed checklist row"
            )
        if line.startswith("- [") and not re.match(r"^- \[[ xX]\] ", line):
            raise AssertionError(
                f"{path.relative_to(ROOT)}:{lineno} has a malformed checklist marker"
            )
        if not line.startswith("- ["):
            continue
        match = GAP_ROW_RE.match(line)
        if enforce_categories and not match:
            raise AssertionError(
                f"{path.relative_to(ROOT)}:{lineno} is missing a supported gap category"
            )
        checked = line.startswith("- [x]") or line.startswith("- [X]")
        for version_match in STALE_ACTIVE_VERSION_RE.finditer(line):
            version = version_match.group("version")
            if current_manifest_versions and version not in current_manifest_versions:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} describes stale v{version} evidence as active/current"
                )
        lowered_line = line.lower()
        retired_markers = retired_current_reports | _retired_current_evidence_dirs(manifest)
        if any(marker in line for marker in retired_markers) and re.search(
            r"\b(current|active|fresh|latest)\b", lowered_line
        ) and "historical" not in lowered_line:
            raise AssertionError(
                f"{path.relative_to(ROOT)}:{lineno} cites retired evidence as current/active"
            )
        if checked:
            lowered = line.lower()
            required = ("evidence:", "reviewer:", "date:", "type:")
            missing = [item for item in required if item not in lowered]
            if missing:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} is checked without structured metadata: {', '.join(missing)}"
                )
            if "viewport" not in lowered and "interaction" not in lowered:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} is checked without viewport or interaction metadata"
                )
            type_match = re.search(r"\btype:\s*([^.;]+)", line, flags=re.IGNORECASE)
            if type_match:
                row_type = type_match.group(1).strip().lower()
                if row_type in NON_CLOSING_EVIDENCE_TYPES or any(
                    token in row_type
                    for token in ("prototype", "fixture", "mock", "intercepted", "mixed")
                ):
                    raise AssertionError(
                        f"{path.relative_to(ROOT)}:{lineno} uses non-closing evidence type in a checked row: "
                        f"{type_match.group(1).strip()!r}"
                    )
            evidence_paths = [
                candidate for candidate in re.findall(r"`([^`]+)`", line)
                if "/" in candidate and not candidate.startswith("http")
            ]
            if not evidence_paths:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} is checked without a backticked evidence path"
                )
            for evidence_path in evidence_paths:
                if not (ROOT / evidence_path).exists():
                    raise AssertionError(
                        f"{path.relative_to(ROOT)}:{lineno} cites missing evidence path: {evidence_path}"
                    )
            if path == AUDIT_PATH:
                category = match.group("category").strip() if match else ""
                kinds = {evidence_path: evidence_kind(evidence_path) for evidence_path in evidence_paths}
                invalid_paths = []
                if category == "visual":
                    invalid_paths = [
                        evidence_path
                        for evidence_path, kind in kinds.items()
                        if kind not in {"current_screenshot", "live_visual_screenshot"}
                    ]
                elif category == "functional":
                    invalid_paths = [
                        evidence_path
                        for evidence_path, kind in kinds.items()
                        if kind != "functional_report"
                    ]
                elif category == "truth/provenance":
                    invalid_paths = [
                        evidence_path
                        for evidence_path, kind in kinds.items()
                        if kind not in {"current_screenshot", "live_visual_screenshot", "current_report", "functional_report", "truth_report"}
                    ]
                elif category == "process":
                    invalid_paths = [
                        evidence_path
                        for evidence_path, kind in kinds.items()
                        if kind not in {"current_report", "functional_report", "truth_report", "ledger", "process_log", "process_artifact"}
                    ]
                else:
                    invalid_paths = [
                        evidence_path
                        for evidence_path, kind in kinds.items()
                        if kind == "stale_or_external"
                    ]
                if invalid_paths:
                    raise AssertionError(
                        f"{path.relative_to(ROOT)}:{lineno} cites evidence path(s) invalid for {category or 'unknown'} row: {', '.join(invalid_paths)}"
                    )
                if category == "functional":
                    interaction_names = _checked_row_interactions(line)
                    if not interaction_names:
                        raise AssertionError(
                            f"{path.relative_to(ROOT)}:{lineno} is a checked functional row without backticked interaction metadata"
                        )
                    for evidence_path in evidence_paths:
                        if evidence_kind(evidence_path) == "functional_report":
                            _require_report_interactions(evidence_path, interaction_names, path, lineno)
        if checked and path == FUNCTIONAL_AUDIT_PATH:
            invalid_paths = [evidence_path for evidence_path in evidence_paths if evidence_path not in allowed_functional_reports]
            if invalid_paths:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} cites functional evidence outside the manifest allowlist: {', '.join(invalid_paths)}"
                )
            interaction_names = _checked_row_interactions(line)
            if not interaction_names:
                raise AssertionError(
                    f"{path.relative_to(ROOT)}:{lineno} is checked without backticked interaction metadata"
                )
            for evidence_path in evidence_paths:
                _require_report_interactions(evidence_path, interaction_names, path, lineno)
        if not enforce_categories:
            continue
        category = match.group("category").strip()
        if category not in ALLOWED_GAP_CATEGORIES:
            raise AssertionError(
                f"{path.relative_to(ROOT)}:{lineno} uses unsupported gap category {category!r}"
            )


def validate_gap_row_contracts() -> None:
    _validate_gap_rows(AUDIT_PATH, enforce_categories=True)
    _validate_gap_rows(FUNCTIONAL_AUDIT_PATH, enforce_categories=False)


def validate_signoff_supersession() -> None:
    status = _read_text(STATUS_PATH)
    changelog = _read_text(CHANGELOG_PATH)
    open_rows = sum(_audit_open_counts().values()) + sum(_functional_open_counts().values())
    required_status_phrases = [
        "All prior `northstar/*` visual, functional, truth/provenance, and process signoffs are superseded",
        "Mock API screenshots are local prototype evidence only.",
    ]
    if open_rows:
        required_status_phrases.extend([
            "Current Authoritative State - Reopened And Blocking",
            "No page is signed off.",
        ])
    else:
        required_status_phrases.append("Current Authoritative State - Reviewer Signoff Recorded")
    for phrase in required_status_phrases:
        if phrase not in status:
            raise AssertionError(f"IMPLEMENTATION_STATUS.md missing current supersession phrase: {phrase}")

    stale_markers = [
        "Prototype Final Signoff And Closeout Passed",
        "No blocking risks remain",
        "No blocking follow-ups remain",
    ]
    first_status_lines = "\n".join(status.splitlines()[:20])
    expected_heading = (
        "Current Authoritative State - Reopened And Blocking"
        if open_rows
        else "Current Authoritative State - Reviewer Signoff Recorded"
    )
    if expected_heading not in first_status_lines:
        raise AssertionError("IMPLEMENTATION_STATUS.md must put the reopened blocking state at the top of the file")
    history_index = status.find(STATUS_HISTORY_MARKER)
    if history_index < 0:
        raise AssertionError("IMPLEMENTATION_STATUS.md must fence superseded checkpoints with the historical marker")
    current_prefix = status[:history_index]
    if "Only `2` functional-control rows remain" in current_prefix or "`267` visual/page/shared gaps remain" in current_prefix:
        raise AssertionError("IMPLEMENTATION_STATUS.md current section contains stale reopened-checkpoint counts")

    changelog_supersession = "North Star Signoff Supersession"
    if changelog_supersession not in changelog:
        raise AssertionError("AGENT_CHANGELOG.md must include a current North Star signoff supersession entry")
    if open_rows:
        latest_changelog_stale = max((changelog.rfind(marker) for marker in stale_markers + ["SIGNOFF"]), default=-1)
        latest_changelog_reopen = changelog.rfind(changelog_supersession)
        if latest_changelog_stale > latest_changelog_reopen:
            raise AssertionError("AGENT_CHANGELOG.md has stale signoff/closeout text after the supersession entry")
    else:
        latest_changelog_entry = _current_changelog_entry(changelog)
        contradictory_zero_row_patterns = {
            "docs/northstar_gap_analysis/full_page_audit.md": _read_text(AUDIT_PATH),
            "docs/northstar_gap_analysis/functional_control_audit.md": _read_text(FUNCTIONAL_AUDIT_PATH),
            "docs/northstar_gap_analysis/signoff_matrix.md": _read_text(SIGNOFF_MATRIX_PATH),
            "IMPLEMENTATION_STATUS.md": current_prefix,
            "AGENT_CHANGELOG.md latest active entry": latest_changelog_entry,
        }
        stale_zero_row_phrases = [
            "Status: reopened and blocking",
            "active blocker for every page until the current rows are closed",
            "active blocker for lineage atlas until all lineage rows below are closed",
            "every page below remains blocked until its own itemized visual",
            "signoff remains blocked",
            "remains blocked in `full_page_audit.md`",
            "process reviewer recheck are pending",
            "final guard, source checks, build/tests, databricks bundle validation, and process reviewer recheck are pending",
        ]
        for path_name, scoped_text in contradictory_zero_row_patterns.items():
            lowered = scoped_text.lower()
            for phrase in stale_zero_row_phrases:
                if phrase.lower() in lowered:
                    raise AssertionError(
                        f"{path_name} contains stale blocking wording after ledgers reached zero open rows: {phrase!r}"
                    )


def _current_changelog_entry(text: str) -> str:
    marker = "## Active Entries"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise AssertionError("AGENT_CHANGELOG.md missing Active Entries section")
    active_text = text[marker_index + len(marker):]
    headings = list(re.finditer(r"^## \d{4}-\d{2}-\d{2} .+$", active_text, flags=re.MULTILINE))
    if not headings:
        raise AssertionError("AGENT_CHANGELOG.md Active Entries section has no dated entry")
    candidates = []
    for index, heading in enumerate(headings):
        match = re.match(
            r"^## (?P<date>\d{4}-\d{2}-\d{2})(?: (?P<time>\d{2}:\d{2}) [A-Z]+)? .+$",
            heading.group(0),
        )
        if not match:
            raise AssertionError(f"AGENT_CHANGELOG.md has malformed active entry heading: {heading.group(0)!r}")
        candidates.append(((match.group("date"), match.group("time") or "00:00", index), index))
    _, newest_index = max(candidates, key=lambda item: item[0])
    start = headings[newest_index].start()
    end = headings[newest_index + 1].start() if newest_index + 1 < len(headings) else len(active_text)
    return active_text[start:end]


def validate_current_changelog_evidence() -> None:
    manifest = _load_manifest()
    evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    current_report = f"{evidence_dir}/prototype-current-report.json"
    allowed_reports = {
        str(path).strip()
        for path in manifest.get("allowed_functional_evidence_reports") or []
        if str(path).strip() and not _is_retired_current_evidence_path(manifest, str(path).strip())
    }
    allowed_reports.update(
        str(path).strip()
        for path in manifest.get("allowed_capture_health_evidence_reports") or []
        if str(path).strip() and not _is_retired_current_evidence_path(manifest, str(path).strip())
    )
    allowed_reports.update(
        path for path in _truth_evidence_reports(manifest)
        if not _is_retired_current_evidence_path(manifest, path)
    )
    allowed_reports.add(current_report)
    allowed_report_dirs = {str(Path(path).parent) for path in allowed_reports}
    allowed_process_paths = {
        _relative_path(str((item or {}).get("path") or ""))
        for item in manifest.get("allowed_process_evidence_artifacts") or []
        if _relative_path(str((item or {}).get("path") or ""))
    }
    entry = _current_changelog_entry(_read_text(CHANGELOG_PATH))
    cited_reports = {
        match.group(0)
        for match in re.finditer(r"docs/northstar_visual_qa/[^\s`]+/prototype-current-report\.json", entry)
    }
    invalid_reports = sorted(cited_reports - allowed_reports)
    if invalid_reports:
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry cites non-current or non-allowlisted report(s): "
            + ", ".join(invalid_reports)
        )
    cited_qa_paths = {
        match.group(0)
        for match in re.finditer(r"docs/northstar_visual_qa/[^\s`,)]+", entry)
    }
    invalid_paths = []
    for path in cited_qa_paths:
        if _is_retired_current_evidence_path(manifest, path):
            invalid_paths.append(path)
            continue
        if path in allowed_reports:
            continue
        if path in allowed_report_dirs:
            continue
        if path in allowed_process_paths:
            continue
        if path.startswith(f"{evidence_dir}/"):
            continue
        invalid_paths.append(path)
    if invalid_paths:
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry cites stale visual QA artifact(s): "
            + ", ".join(sorted(invalid_paths))
        )


def validate_current_changelog_counts() -> None:
    entry = _current_changelog_entry(_read_text(CHANGELOG_PATH))
    full_open = sum(_parse_sections(_read_text(AUDIT_PATH).splitlines()).values())
    functional_open = sum(_functional_open_counts().values())
    full_matches = [
        int(match.group("count"))
        for match in re.finditer(
            r"full_page_audit\.md`?[\s\S]{0,180}`(?P<count>\d+)`\s+open\s+(?:page/shared\s+)?(?:gaps|rows)",
            entry,
        )
    ]
    functional_matches = [
        int(match.group("count"))
        for match in re.finditer(
            r"functional_control_audit\.md`?[\s\S]{0,180}`(?P<count>\d+)`\s+open\s+(?:control|controls|row|rows)",
            entry,
        )
    ]
    if full_open not in full_matches:
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry must state the current full_page_audit.md open gap count "
            f"({full_open})"
        )
    if any(count != full_open for count in full_matches):
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry states stale full_page_audit.md open gap counts: "
            + ", ".join(str(count) for count in full_matches)
        )
    if functional_open not in functional_matches:
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry must state the current functional_control_audit.md open control count "
            f"({functional_open})"
        )
    if any(count != functional_open for count in functional_matches):
        raise AssertionError(
            "latest AGENT_CHANGELOG.md entry states stale functional_control_audit.md open control counts: "
            + ", ".join(str(count) for count in functional_matches)
        )
    if functional_open == 0:
        stale_patterns = [
            r"\b[1-9]\d*\s+functional[^.\n]{0,80}\b(?:row|rows|control|controls)[^.\n]{0,80}\b(?:remain|remains|open)",
            r"\bfunctional[^.\n]{0,80}\b[1-9]\d*\s+(?:row|rows|control|controls)[^.\n]{0,80}\b(?:remain|remains|open)",
            r"\bfunctional live-validation row[^.\n]{0,80}\b(?:remain|remains|open)",
        ]
        for pattern in stale_patterns:
            if re.search(pattern, entry, flags=re.IGNORECASE):
                raise AssertionError(
                    "latest AGENT_CHANGELOG.md entry states stale open functional/control counts "
                    "while functional_control_audit.md has zero open rows"
                )


def validate_prototype_contract() -> None:
    text = _read_text(PROTOTYPE_CONTRACT_PATH)
    banned_phrases = [
        "Final deployed prototype capture report",
        "Final deployed prototype capture status",
        "Visual must-fix items: `0` open",
        "Functional must-fix items: `0` open",
        "Truth/provenance must-fix items: `0` open",
        "No blocking risks remain",
        "No blocking follow-ups remain",
    ]
    for phrase in banned_phrases:
        if phrase in text:
            raise AssertionError(f"prototype_contract.md contains stale closeout phrase: {phrase}")
    required = [
        "Active current screenshot evidence is the directory named in",
        "functional_control_audit.md",
        "No page may be treated as complete while either active ledger has open rows",
    ]
    for phrase in required:
        if phrase not in text:
            raise AssertionError(f"prototype_contract.md missing reopened evidence rule: {phrase}")


def validate_functional_audit() -> None:
    text = _read_text(FUNCTIONAL_AUDIT_PATH)
    if "TBD" in text or "Audit pending" in text:
        raise AssertionError("functional_control_audit.md still contains TBD or Audit pending")
    allowed_reports = {
        str(path).strip()
        for path in _load_manifest().get("allowed_functional_evidence_reports") or []
        if str(path).strip()
    }
    cited_reports = {
        match.group(0)
        for match in re.finditer(r"docs/northstar_visual_qa/[^\s`]+/prototype-current-report\.json", text)
    }
    invalid_reports = sorted(cited_reports - allowed_reports)
    if invalid_reports:
        raise AssertionError(
            "functional_control_audit.md cites non-allowlisted functional report(s): "
            + ", ".join(invalid_reports)
        )
    lines = text.splitlines()
    summary = _parse_control_summary(lines)
    sections = _parse_control_sections(lines)
    if not summary:
        raise AssertionError("functional_control_audit.md has no page status summary rows")
    for label, row in summary.items():
        if label not in sections:
            raise AssertionError(f"functional summary row {label} has no matching '## {label} Controls' section")
        actual = sections[label]
        if actual != row.count:
            raise AssertionError(f"functional count mismatch for {label}: summary={row.count}, actual={actual}")
        if row.count > 0 and row.status.lower() not in {"blocked", "open"}:
            raise AssertionError(f"{label} has {row.count} open controls but status is {row.status!r}")


def validate_allowed_functional_reports() -> None:
    manifest = _load_manifest()
    reports = [
        str(path).strip()
        for path in manifest.get("allowed_functional_evidence_reports") or []
        if str(path).strip()
    ]
    pins = manifest.get("allowed_functional_evidence_report_pins") or {}
    expected_failures = manifest.get("allowed_functional_evidence_expected_failures") or {}
    if not reports:
        raise AssertionError("reference_manifest.json must allowlist functional evidence reports")
    seen: set[str] = set()
    for report in reports:
        if report in seen:
            raise AssertionError(f"duplicate functional evidence report in manifest: {report}")
        seen.add(report)
        path = ROOT / report
        if not path.exists():
            raise AssertionError(f"functional evidence report does not exist: {report}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid functional evidence report JSON: {report}: {exc}") from exc
        pin = pins.get(report)
        if not isinstance(pin, dict):
            raise AssertionError(f"functional evidence report has no manifest pin metadata: {report}")
        for key in ("generatedAt", "baseUrl", "evidenceKind"):
            expected_value = str(pin.get(key) or "").strip()
            if not expected_value:
                raise AssertionError(f"functional evidence report pin is missing {key}: {report}")
            if str(data.get(key) or "").strip() != expected_value:
                raise AssertionError(
                    f"functional evidence report {key} does not match manifest pin for {report}: "
                    f"report={data.get(key)!r}, manifest={expected_value!r}"
                )
        if "mockApi" not in pin or bool(pin.get("mockApi")) != bool(data.get("mockApi")):
            raise AssertionError(
                f"functional evidence report mockApi mismatch for {report}: "
                f"report={data.get('mockApi')!r}, manifest={pin.get('mockApi')!r}"
            )
        for key in ("buildId", "deploymentId"):
            expected_value = str(pin.get(key) or "").strip()
            actual_value = str(data.get(key) or "").strip()
            if data.get("evidenceKind") == "live_databricks" and not expected_value:
                raise AssertionError(f"live functional evidence report pin is missing {key}: {report}")
            if expected_value and actual_value != expected_value:
                raise AssertionError(
                    f"functional evidence report {key} does not match manifest pin for {report}: "
                    f"report={data.get(key)!r}, manifest={expected_value!r}"
                )
        expected_sha256 = str(pin.get("sha256") or "").strip()
        if not expected_sha256:
            raise AssertionError(f"functional evidence report pin is missing sha256: {report}")
        actual_sha256 = _sha256_file(report)
        if actual_sha256 != expected_sha256:
            raise AssertionError(
                f"functional evidence report sha256 does not match manifest pin for {report}: "
                f"report={actual_sha256}, manifest={expected_sha256}"
            )
        if data.get("passed") is not True:
            raise AssertionError(f"functional evidence report must have passed=true: {report}")
        if data.get("mockApi"):
            if data.get("evidenceKind") not in MOCK_EVIDENCE_KINDS:
                raise AssertionError(
                    f"mock functional evidence must use an explicitly non-authoritative mock evidenceKind: {report}"
                )
            warning = str(data.get("mockEvidenceWarning") or "")
            if "not live Databricks evidence" not in warning:
                raise AssertionError(f"mock functional evidence must carry explicit non-live warning: {report}")
        if data.get("pageErrors") or []:
            raise AssertionError(f"functional evidence report has pageErrors: {report}")
        interactions = data.get("interactions") or []
        if not interactions:
            raise AssertionError(f"functional evidence report has no interaction records: {report}")
        count_checks = {
            "captureCount": len(data.get("captures") or []),
            "interactionCount": len(interactions),
            "requestFailureCount": len(data.get("requestFailures") or []),
            "consoleErrorCount": len([
                entry for entry in data.get("console") or []
                if str((entry or {}).get("type") or "").lower() == "error"
            ]),
            "pageErrorCount": len(data.get("pageErrors") or []),
        }
        for key, actual in count_checks.items():
            if key not in pin or int(pin.get(key)) != actual:
                raise AssertionError(
                    f"functional evidence report {key} mismatch for {report}: "
                    f"report={actual}, manifest={pin.get(key)!r}"
                )
        if not any(bool((item or {}).get("loaded")) for item in interactions):
            raise AssertionError(f"functional evidence report has no loaded interactions: {report}")
        unloaded = [
            str((item or {}).get("interaction") or index)
            for index, item in enumerate(interactions)
            if not bool((item or {}).get("loaded"))
        ]
        if unloaded:
            raise AssertionError(
                f"functional evidence report has unloaded interaction(s) in {report}: {', '.join(unloaded)}"
            )
        failed_validation_checks = []
        for item in interactions:
            validation = (item or {}).get("validation") or {}
            checks = validation.get("checks") if isinstance(validation, dict) else {}
            if not isinstance(checks, dict):
                continue
            failed_validation_checks.extend(
                f"{(item or {}).get('interaction') or 'unknown'}.{key}"
                for key, value in checks.items()
                if value is False
            )
        if failed_validation_checks:
            raise AssertionError(
                f"functional evidence report has failed validation check(s) in {report}: "
                f"{', '.join(failed_validation_checks)}"
            )
        exceptions = expected_failures.get(report) if isinstance(expected_failures, dict) else {}
        _validate_expected_functional_failures(report, data, exceptions if isinstance(exceptions, dict) else {})


def validate_allowed_capture_health_reports() -> None:
    manifest = _load_manifest()
    reports = [
        str(path).strip()
        for path in manifest.get("allowed_capture_health_evidence_reports") or []
        if str(path).strip()
    ]
    pins = manifest.get("allowed_capture_health_evidence_report_pins") or {}
    seen: set[str] = set()
    for report in reports:
        if report in seen:
            raise AssertionError(f"duplicate capture-health evidence report in manifest: {report}")
        seen.add(report)
        path = ROOT / report
        if not path.exists():
            raise AssertionError(f"capture-health evidence report does not exist: {report}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid capture-health evidence report JSON: {report}: {exc}") from exc
        pin = pins.get(report)
        if not isinstance(pin, dict):
            raise AssertionError(f"capture-health evidence report has no manifest pin metadata: {report}")
        expected_hash = str(pin.get("sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"capture-health evidence report pin is missing sha256: {report}")
        actual_hash = _sha256_file(report)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"capture-health evidence report sha256 mismatch for {report}: "
                f"actual={actual_hash}, manifest={expected_hash}"
            )
        for key in ("generatedAt", "baseUrl", "evidenceKind"):
            expected_value = str(pin.get(key) or "").strip()
            if not expected_value:
                raise AssertionError(f"capture-health evidence report pin is missing {key}: {report}")
            if str(data.get(key) or "").strip() != expected_value:
                raise AssertionError(
                    f"capture-health evidence report {key} does not match manifest pin for {report}: "
                    f"report={data.get(key)!r}, manifest={expected_value!r}"
                )
        if "mockApi" not in pin or bool(pin.get("mockApi")) != bool(data.get("mockApi")):
            raise AssertionError(
                f"capture-health evidence report mockApi mismatch for {report}: "
                f"report={data.get('mockApi')!r}, manifest={pin.get('mockApi')!r}"
            )
        if data.get("evidenceKind") == "live_databricks":
            expected_deployment_id = str(pin.get("deploymentId") or "").strip()
            actual_deployment_id = str(data.get("deploymentId") or "").strip()
            if not expected_deployment_id:
                raise AssertionError(f"live capture-health report pin is missing deploymentId: {report}")
            if actual_deployment_id != expected_deployment_id:
                raise AssertionError(
                    f"live capture-health report deploymentId mismatch for {report}: "
                    f"report={actual_deployment_id!r}, manifest={expected_deployment_id!r}"
                )
            expected_build_id = str(pin.get("buildId") or "").strip()
            actual_build_id = str(data.get("buildId") or data.get("expectedBuildId") or "").strip()
            if not expected_build_id:
                raise AssertionError(f"live capture-health report pin is missing buildId: {report}")
            if actual_build_id != expected_build_id:
                raise AssertionError(
                    f"live capture-health report buildId mismatch for {report}: "
                    f"report={actual_build_id!r}, manifest={expected_build_id!r}"
                )
            runtime_status = data.get("runtimeStatus") or {}
            if isinstance(runtime_status, dict) and runtime_status:
                runtime_build_id = str(runtime_status.get("buildId") or "").strip()
                runtime_ok = bool(runtime_status.get("ok"))
                runtime_http_status = int(runtime_status.get("status") or 0)
                if not runtime_ok or runtime_http_status != 200:
                    raise AssertionError(
                        f"live capture-health report runtimeStatus is not a successful live probe for {report}: "
                        f"ok={runtime_status.get('ok')!r}, status={runtime_status.get('status')!r}"
                    )
                if runtime_build_id != expected_build_id:
                    raise AssertionError(
                        f"live capture-health report runtimeStatus buildId mismatch for {report}: "
                        f"runtimeStatus={runtime_build_id!r}, manifest={expected_build_id!r}"
                    )
            elif data.get("liveDatabricksCapture") is True:
                raise AssertionError(
                    f"live Databricks capture-health report is missing runtimeStatus build proof: {report}"
                )
            build_ids = data.get("buildIds") or {}
            if isinstance(build_ids, dict) and build_ids:
                mismatched = {
                    key: value
                    for key, value in build_ids.items()
                    if str(value or "").strip() != expected_build_id
                }
                if mismatched:
                    raise AssertionError(
                        f"live capture-health report has endpoint buildId mismatches for {report}: "
                        + ", ".join(f"{key}={value}" for key, value in sorted(mismatched.items()))
                    )
            checks = data.get("checks") or {}
            if isinstance(checks, dict) and checks.get("buildMatches") is not True:
                raise AssertionError(f"live capture-health report does not have checks.buildMatches=true: {report}")
        if data.get("passed") is not True:
            raise AssertionError(f"capture-health evidence report must have passed=true: {report}")
        count_checks = {
            "captureCount": len(data.get("captures") or []),
            "interactionCount": len(data.get("interactions") or []),
            "requestFailureCount": len(data.get("requestFailures") or []),
            "consoleErrorCount": len([
                entry for entry in data.get("console") or []
                if str((entry or {}).get("type") or "").lower() == "error"
            ]),
            "pageErrorCount": len(data.get("pageErrors") or []),
        }
        for key, actual in count_checks.items():
            if key not in pin or int(pin.get(key)) != actual:
                raise AssertionError(
                    f"capture-health evidence report {key} mismatch for {report}: "
                    f"report={actual}, manifest={pin.get(key)!r}"
                )


def validate_allowed_live_truth_reports() -> None:
    manifest = _load_manifest()
    reports = [
        str(path).strip()
        for path in manifest.get("allowed_live_truth_evidence_reports") or []
        if str(path).strip()
    ]
    pins = manifest.get("allowed_live_truth_evidence_report_pins") or {}
    seen: set[str] = set()
    for report in reports:
        if report in seen:
            raise AssertionError(f"duplicate live truth evidence report in manifest: {report}")
        seen.add(report)
        path = ROOT / report
        if not path.exists():
            raise AssertionError(f"live truth evidence report does not exist: {report}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid live truth evidence report JSON: {report}: {exc}") from exc
        pin = pins.get(report)
        if not isinstance(pin, dict):
            raise AssertionError(f"live truth evidence report has no manifest pin metadata: {report}")
        expected_hash = str(pin.get("sha256") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise AssertionError(f"live truth evidence report pin is missing sha256: {report}")
        actual_hash = _sha256_file(report)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"live truth evidence report sha256 mismatch for {report}: "
                f"actual={actual_hash}, manifest={expected_hash}"
            )
        for key in ("generatedAt", "baseUrl", "evidenceKind", "deploymentId", "buildId"):
            expected_value = str(pin.get(key) or "").strip()
            if not expected_value:
                raise AssertionError(f"live truth evidence report pin is missing {key}: {report}")
            if str(data.get(key) or "").strip() != expected_value:
                raise AssertionError(
                    f"live truth evidence report {key} does not match manifest pin for {report}: "
                    f"report={data.get(key)!r}, manifest={expected_value!r}"
                )
        if data.get("evidenceKind") != "live_databricks" or data.get("mockApi") is not False:
            raise AssertionError(f"live truth evidence report must be live_databricks/mockApi=false: {report}")
        if data.get("passed") is not True:
            raise AssertionError(f"live truth evidence report must have passed=true: {report}")
        checks = data.get("checks") or {}
        if not isinstance(checks, dict) or not checks or not all(bool(value) for value in checks.values()):
            raise AssertionError(f"live truth evidence report has failed or missing checks: {report}")
        count_checks = {
            "captureCount": len(data.get("captures") or []),
            "interactionCount": len(data.get("interactions") or []),
            "requestFailureCount": len(data.get("requestFailures") or []),
            "consoleErrorCount": len([
                entry for entry in data.get("console") or []
                if str((entry or {}).get("type") or "").lower() == "error"
            ]),
            "pageErrorCount": len(data.get("pageErrors") or []),
        }
        for key, actual in count_checks.items():
            if key not in pin or int(pin.get(key)) != actual:
                raise AssertionError(
                    f"live truth evidence report {key} mismatch for {report}: "
                    f"report={actual}, manifest={pin.get(key)!r}"
                )


def _checked_row_interactions(line: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"\binteraction(?P<plural>s?)\s*:?\s+", line):
        remainder = line[match.end():]
        first = re.match(r"`([^`]+)`", remainder)
        if not first:
            continue
        names.extend(
            item.strip()
            for item in re.split(r"\s*,\s*", first.group(1))
            if item.strip()
        )
        if not match.group("plural"):
            continue
        offset = first.end()
        while True:
            next_match = re.match(r"\s*,\s*`([^`]+)`", remainder[offset:])
            if not next_match:
                break
            names.extend(
                item.strip()
                for item in re.split(r"\s*,\s*", next_match.group(1))
                if item.strip()
            )
            offset += next_match.end()
    return names


def _require_report_interactions(report: str, interaction_names: list[str], path: Path, lineno: int) -> None:
    try:
        data = json.loads((ROOT / report).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"{path.relative_to(ROOT)}:{lineno} cannot validate interactions for report {report}: {exc}"
        ) from exc
    actual = {
        str((item or {}).get("interaction") or "").strip()
        for item in data.get("interactions") or []
        if str((item or {}).get("interaction") or "").strip()
    }
    missing = [name for name in interaction_names if name not in actual]
    if missing:
        raise AssertionError(
            f"{path.relative_to(ROOT)}:{lineno} cites interaction(s) not present in {report}: {', '.join(missing)}"
        )


def _matches_expected_failure(entry: dict, expected: dict) -> bool:
    status = expected.get("status")
    if status is not None and int(entry.get("status") or 0) != int(status):
        return False
    url_includes = str(expected.get("urlIncludes") or "").strip()
    if url_includes and url_includes not in str(entry.get("url") or ""):
        return False
    text_includes = str(expected.get("textIncludes") or "").strip()
    if text_includes and text_includes not in str(entry.get("text") or ""):
        return False
    return True


def _validate_expected_functional_failures(report: str, data: dict, exceptions: dict) -> None:
    request_failures = data.get("requestFailures") or []
    expected_request_failures = exceptions.get("requestFailures") or []
    for expected in expected_request_failures:
        if not any(_matches_expected_failure(failure or {}, expected or {}) for failure in request_failures):
            raise AssertionError(
                f"functional evidence report has unused expected request failure pattern in {report}: {expected!r}"
            )
    for failure in request_failures:
        if not any(_matches_expected_failure(failure or {}, expected or {}) for expected in expected_request_failures):
            raise AssertionError(f"functional evidence report has unexpected request failure in {report}: {failure!r}")
    console_errors = [
        entry for entry in data.get("console") or []
        if str((entry or {}).get("type") or "").lower() == "error"
    ]
    expected_console_errors = exceptions.get("consoleErrors") or []
    for expected in expected_console_errors:
        if not any(_matches_expected_failure(entry or {}, expected or {}) for entry in console_errors):
            raise AssertionError(
                f"functional evidence report has unused expected console error pattern in {report}: {expected!r}"
            )
    for entry in console_errors:
        if not any(_matches_expected_failure(entry or {}, expected or {}) for expected in expected_console_errors):
            raise AssertionError(f"functional evidence report has unexpected console error in {report}: {entry!r}")


def _audit_open_counts() -> dict[str, int]:
    return _parse_sections(_read_text(AUDIT_PATH).splitlines())


def _functional_open_counts() -> dict[str, int]:
    return _parse_control_sections(_read_text(FUNCTIONAL_AUDIT_PATH).splitlines())


def _matrix_rows(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("| ") or stripped.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] == "Route":
            continue
        if len(cells) < 9:
            raise AssertionError(f"signoff matrix row has too few columns: {stripped}")
        rows.append(cells)
    return rows


def _strip_markdown_code(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("`") and stripped.endswith("`"):
        return stripped[1:-1].strip()
    return stripped


def _require_existing_matrix_artifact(value: str, *, route: str, role: str) -> None:
    artifact = _strip_markdown_code(value)
    if not artifact or artifact in {"local prototype-mock capture", "active current directory", "current manifest evidence"}:
        raise AssertionError(f"signoff matrix {route}/{role} has a prose current artifact instead of a path")
    path = ROOT / artifact
    if not path.exists():
        raise AssertionError(f"signoff matrix {route}/{role} current artifact does not exist: {artifact}")


def _matrix_current_evidence_dir(text: str) -> str:
    marker = "Current evidence directory:"
    if marker not in text:
        raise AssertionError("signoff_matrix.md missing Current evidence directory section")
    after = text.split(marker, 1)[1]
    match = re.search(r"- `([^`]+)`", after)
    if not match:
        raise AssertionError("signoff_matrix.md missing current evidence directory path")
    return match.group(1).strip()


def validate_signoff_matrix() -> None:
    text = _read_text(SIGNOFF_MATRIX_PATH)
    manifest = _load_manifest()
    manifest_evidence_dir = str(manifest.get("global_current_evidence_dir") or "").strip()
    matrix_evidence_dir = _matrix_current_evidence_dir(text)
    if matrix_evidence_dir != manifest_evidence_dir:
        raise AssertionError(
            f"signoff matrix current evidence dir mismatch: matrix={matrix_evidence_dir}, manifest={manifest_evidence_dir}"
        )
    allowed_functional_reports = {
        str(path).strip()
        for path in manifest.get("allowed_functional_evidence_reports") or []
        if str(path).strip() and not _is_retired_current_evidence_path(manifest, str(path).strip())
    }
    allowed_truth_reports = _truth_evidence_reports(manifest)
    rows = _matrix_rows(text.splitlines())
    if not rows:
        raise AssertionError("signoff_matrix.md has no route reviewer rows")
    manifest_labels = [
        str(route.get("label") or route.get("route") or "").strip()
        for route in _load_manifest().get("routes") or []
        if route.get("standalone_visual_gate")
    ]
    required_labels = manifest_labels + ["Cross-Page Shared"]
    audit_open = _audit_open_counts()
    functional_open = _functional_open_counts()
    for label in required_labels:
        route_rows = [row for row in rows if row[0] == label]
        roles = {row[1] for row in route_rows}
        missing_roles = sorted(REQUIRED_REVIEWER_ROLES - roles)
        if missing_roles:
            raise AssertionError(f"signoff matrix for {label} missing reviewer role(s): {', '.join(missing_roles)}")
        route_open = audit_open.get(label, 0) + functional_open.get(label, 0)
        if label != "Cross-Page Shared":
            route_open += audit_open.get("Cross-Page Shared", 0) + functional_open.get("Cross-Page Shared", 0)
        for row in route_rows:
            verdict = row[2].upper()
            if verdict not in {"BLOCKED", "SIGNOFF"}:
                raise AssertionError(f"signoff matrix for {label} has invalid verdict: {row[2]!r}")
            if verdict == "SIGNOFF" and route_open > 0:
                raise AssertionError(f"signoff matrix cannot sign off {label} while {route_open} route/shared rows remain open")
            try:
                matrix_open = int(row[7])
            except ValueError:
                raise AssertionError(f"signoff matrix for {label}/{row[1]} has non-numeric open-row count: {row[7]!r}") from None
            if matrix_open != route_open:
                raise AssertionError(
                    f"signoff matrix open-row count mismatch for {label}/{row[1]}: matrix={matrix_open}, actual={route_open}"
                )
            _require_existing_matrix_artifact(row[4], route=label, role=row[1])
            artifact = _strip_markdown_code(row[4])
            role = row[1]
            if _is_retired_current_evidence_path(manifest, artifact):
                raise AssertionError(
                    f"signoff matrix {label}/{role} cites retired current evidence as its current artifact: {artifact}"
                )
            if role in {"Visual fidelity", "Product structure"} and not artifact.startswith(f"{manifest_evidence_dir}/"):
                raise AssertionError(
                    f"signoff matrix {label}/{role} must use current manifest evidence dir"
                )
            if role == "Truth/provenance" and not (
                artifact.startswith(f"{manifest_evidence_dir}/") or artifact in allowed_truth_reports
            ):
                raise AssertionError(
                    f"signoff matrix {label}/{role} must use current manifest evidence dir or an allowed truth report"
                )
            if role == "Functional workflow" and artifact not in allowed_functional_reports:
                raise AssertionError(
                    f"signoff matrix {label}/{role} uses functional evidence not allowed by manifest: {artifact}"
                )


def _parse_status_counts(pattern: re.Pattern[str], text: str, label: str) -> tuple[int, dict[str, int]]:
    match = pattern.search(text)
    if not match:
        raise AssertionError(f"IMPLEMENTATION_STATUS.md missing current {label} count summary")
    total = int(match.group("total"))
    counts: dict[str, int] = {}
    for item in STATUS_COUNT_PAIR_RE.finditer(match.group("body")):
        item_label = re.sub(r"^and\s+", "", item.group("label").strip())
        counts[item_label] = int(item.group("count"))
    if not counts:
        raise AssertionError(f"IMPLEMENTATION_STATUS.md current {label} summary has no per-page counts")
    return total, counts


def validate_status_counts() -> None:
    status = _read_text(STATUS_PATH)
    history_index = status.find(STATUS_HISTORY_MARKER)
    if history_index < 0:
        raise AssertionError("IMPLEMENTATION_STATUS.md must fence superseded checkpoints with the historical marker")
    current_status = status[:history_index]
    gap_total, gap_counts = _parse_status_counts(STATUS_GAP_SUMMARY_RE, current_status, "gap")
    control_total, control_counts = _parse_status_counts(STATUS_CONTROL_SUMMARY_RE, current_status, "control")
    audit_counts = _audit_open_counts()
    functional_counts = _functional_open_counts()
    if gap_total != sum(audit_counts.values()):
        raise AssertionError(f"IMPLEMENTATION_STATUS.md gap total mismatch: status={gap_total}, actual={sum(audit_counts.values())}")
    if control_total != sum(functional_counts.values()):
        raise AssertionError(
            f"IMPLEMENTATION_STATUS.md control total mismatch: status={control_total}, actual={sum(functional_counts.values())}"
        )
    for label, count in audit_counts.items():
        if gap_counts.get(label) != count:
            raise AssertionError(f"IMPLEMENTATION_STATUS.md gap count mismatch for {label}: status={gap_counts.get(label)}, actual={count}")
    for label, count in functional_counts.items():
        if control_counts.get(label) != count:
            raise AssertionError(
                f"IMPLEMENTATION_STATUS.md control count mismatch for {label}: status={control_counts.get(label)}, actual={count}"
            )


def validate_no_completion_language_with_open_rows() -> None:
    open_rows = sum(_audit_open_counts().values()) + sum(_functional_open_counts().values())
    if open_rows == 0:
        return
    status_text = _read_text(STATUS_PATH)
    status_history_line = None
    for index, line in enumerate(status_text.splitlines(), start=1):
        if line.strip() == STATUS_HISTORY_MARKER:
            status_history_line = index
            break
    if status_history_line is None:
        raise AssertionError("IMPLEMENTATION_STATUS.md is missing the superseded historical checkpoint marker")
    changelog = _read_text(CHANGELOG_PATH)
    changelog_markers = [
        "Evidence-Backed Audit Row Reopen",
        "Current North Star Signoff Supersession",
    ]
    marker_index = max(changelog.rfind(marker) for marker in changelog_markers)
    current_changelog = changelog[marker_index:] if marker_index >= 0 else changelog[-4000:]
    latest_changelog_entry = _current_changelog_entry(changelog)
    for path_name, scoped_text in {
        "IMPLEMENTATION_STATUS.md": status_text,
        "AGENT_CHANGELOG.md": current_changelog,
        "AGENT_CHANGELOG.md latest active entry": latest_changelog_entry,
        "docs/northstar_gap_analysis/full_page_audit.md": _read_text(AUDIT_PATH),
        "docs/northstar_gap_analysis/functional_control_audit.md": _read_text(FUNCTIONAL_AUDIT_PATH),
        "docs/northstar_gap_analysis/signoff_matrix.md": _read_text(SIGNOFF_MATRIX_PATH),
        "docs/northstar_gap_analysis/prototype_contract.md": _read_text(PROTOTYPE_CONTRACT_PATH),
    }.items():
        for lineno, line in enumerate(scoped_text.splitlines(), start=1):
            lowered = line.lower()
            scan_line = lowered
            for allowed in COMPLETION_CONTEXT_ALLOWLIST:
                scan_line = scan_line.replace(allowed, "")
            normalized_scan_line = re.sub(r"[-_]+", " ", scan_line)
            for term in COMPLETION_TERMS:
                normalized_term = re.sub(r"[-_]+", " ", term.lower())
                if term.lower() not in scan_line and normalized_term not in normalized_scan_line:
                    continue
                term_index = lowered.find(term.lower())
                if term_index < 0:
                    term_index = lowered.find(normalized_term)
                term_context = lowered[max(0, term_index - 48): term_index + len(term) + 24]
                if "historical statements about" in lowered and "superseded evidence failures" in lowered:
                    continue
                if "do not prove" in term_context or "not " in term_context:
                    continue
                if path_name == "IMPLEMENTATION_STATUS.md" and lineno > status_history_line:
                    continue
                raise AssertionError(
                    f"{path_name} contains completion language while audit rows remain open: {term!r}"
                )


def main() -> int:
    if not VISUAL_QA_ROOT.exists():
        # North Star visual QA evidence (screenshots, capture reports, side-by-side
        # PNGs) is regenerable artifact state produced locally by the capture
        # scripts. As of the 2026-07 repo-size cleanup it is gitignored and no
        # longer tracked in git (it accounted for ~1.3GB and made the repo
        # unpushable against GitHub's 2GB pack limit). Without the evidence checked
        # out there is nothing for this contract to validate, so skip cleanly.
        # Regenerate the evidence locally (frontend/scripts/axiom_*_qa.mjs, etc.)
        # to run the full contract.
        print(
            "northstar audit contract skipped: visual QA evidence not checked out "
            "(regenerable, gitignored). Regenerate via the capture scripts to validate."
        )
        return 0
    try:
        validate_manifest()
        validate_no_unregistered_current_evidence_reports()
        validate_visual_qa_retention()
        validate_companion_audit_blockers()
        validate_current_evidence()
        validate_audit()
        validate_functional_audit()
        validate_allowed_functional_reports()
        validate_allowed_capture_health_reports()
        validate_allowed_live_truth_reports()
        validate_gap_row_contracts()
        validate_status_counts()
        validate_signoff_matrix()
        validate_no_completion_language_with_open_rows()
        validate_prototype_contract()
        validate_signoff_supersession()
        validate_current_changelog_evidence()
        validate_current_changelog_counts()
    except AssertionError as exc:
        print(f"northstar audit contract failed: {exc}", file=sys.stderr)
        return 1
    print("northstar audit contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
