"""emet control-plane integration for Axiom.

emet (a sibling Databricks-native validation product) installs a shared
control plane into ``<catalog>.emet`` — a managed schema of curated result
tables/views, one AI/BI dashboard, one managed Genie "Signal Room", and a
Databricks Job per validation suite. This service lets GA:

  * DETECT whether emet is installed + accessible on the workspace,
  * read the PORTFOLIO of validation jobs and their trust results,
  * read a single RUN's validations + per-check evidence,
  * TRIGGER a run (Jobs ``run-now``) and MONITOR its live status,
  * hand the Control Center the Genie space id + dashboard id.

Detection contract (see the repo notes on the emet seam):
  * The emet catalog is the one thing GA can't know a priori. We resolve it
    from ``AXIOM_EMET_CATALOG`` (baked per deploy for a fast, query-free
    bootstrap), else from emet's shared pointer file
    ``/Shared/emet/_metadata/workspace_manifest_pointer.json``.
  * The managed schema is the emet constant ``emet``.
  * ``<catalog>.emet.portfolio_surface_status`` is a one-row health view
    joining the ``workspace_manifest`` singleton with live surface state — it
    yields install state, dashboard id, genie space id, and shared-surface
    coherence in a single read.

Everything here reads real emet columns (verified against the live schema);
we never fabricate metadata. Numeric cells arrive as strings from the Statement
Execution API and are coerced defensively.

Trust Score is a priority-weighted pass rate (0-100, weights CRITICAL=5 …
LOW=2). Cross-run/portfolio rollups MUST re-derive it from
``SUM(successful_priority_weight_sum)/SUM(priority_weight_sum)*100`` — never
average per-run scores.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from axiom.config import AppConfig
from axiom.services.assets import normalize_str

# ── constants ──────────────────────────────────────────────────────────────

MANAGED_SCHEMA = "emet"
POINTER_PATH = "/Shared/emet/_metadata/workspace_manifest_pointer.json"
SOURCE = "emet-control-plane"

# emet's managed human-facing names (control_plane constants). The
# workspace_manifest records the dashboard/genie ids, but that record can go
# STALE when emet re-creates the shared surfaces (the manifest is only
# refreshed on maintenance actions) — so GA resolves the LIVE resource by name
# via the SDK and only falls back to the manifest id when resolution fails.
DASHBOARD_NAME = "emet Validation Intelligence"
GENIE_ROOM_NAME = "emet Signal Room"

# Only bare Unity Catalog identifiers may reach an FQN — the catalog/schema come
# from config or a workspace pointer file, so validate before interpolating.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Priority order for triage sorting + the trust-weight reference (documented for
# callers; the weighted numerator/denominator are persisted by emet so we
# never recompute weights ourselves).
_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_RUNNING_LIFECYCLE = {
    "PENDING",
    "RUNNING",
    "BLOCKED",
    "QUEUED",
    "TERMINATING",
    "WAITING_FOR_RETRY",
}


# ── value coercion (Statement Execution returns everything as strings) ──────

def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _f(value: Any) -> Optional[float]:
    text = _s(value)
    if not text or text.lower() in {"null", "nan", "none"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> Optional[int]:
    number = _f(value)
    return int(number) if number is not None else None


def _bool(value: Any) -> bool:
    return _s(value).lower() in {"true", "1", "t", "yes"}


# ── install resolution ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Install:
    catalog: str
    schema: str
    source: str  # "config" | "pointer"

    def fqn(self, obj: str) -> str:
        for part in (self.catalog, self.schema):
            if not _IDENT_RE.match(part):
                raise ValueError(f"Unsafe emet identifier: {part!r}")
        return f"`{self.catalog}`.`{self.schema}`.`{obj}`"


def _read_pointer(uc: Any) -> Optional[Dict[str, str]]:
    """Read emet's shared catalog pointer file, if our principal can.

    Returns ``{catalog, schema}`` or None. Any failure (ACL, missing file,
    SDK shape drift) is swallowed — detection simply reports "not detected".
    """

    client = getattr(uc, "w", None)
    if client is None:
        return None
    raw: Optional[str] = None
    try:
        workspace = client.workspace
        # Prefer download() (arbitrary workspace files); fall back to the
        # base64 export shape used by older SDKs.
        try:
            handle = workspace.download(POINTER_PATH)
            data = handle.read() if hasattr(handle, "read") else handle
            raw = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
        except Exception:
            export = workspace.export(POINTER_PATH)
            content = getattr(export, "content", None)
            if content:
                raw = base64.b64decode(content).decode("utf-8")
    except Exception:
        return None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    catalog = normalize_str(parsed.get("catalog"))
    if not catalog:
        return None
    return {"catalog": catalog, "schema": normalize_str(parsed.get("schema")) or MANAGED_SCHEMA}


def resolve_install(config: AppConfig, uc: Any) -> Optional[Install]:
    catalog = normalize_str(getattr(config, "emet_catalog", ""))
    schema = normalize_str(getattr(config, "emet_schema", "")) or MANAGED_SCHEMA
    if catalog:
        return Install(catalog=catalog, schema=schema, source="config")
    pointer = _read_pointer(uc)
    if pointer:
        return Install(catalog=pointer["catalog"], schema=pointer["schema"], source="pointer")
    return None


# ── live shared-surface resolution (manifest ids can be stale) ─────────────

def _lifecycle_active(dashboard: Any) -> bool:
    state = _s(getattr(dashboard, "lifecycle_state", ""))
    return state.upper().endswith("ACTIVE")


def _app_principal_client() -> Any:
    """A fresh app-principal (M2M) WorkspaceClient. In the deployed app this
    authenticates as the Axiom service principal, which is NOT limited to the
    OBO user-api-scopes — so it can call Lakeview list even when the forwarded
    user token lacks the scope."""

    try:
        from databricks.sdk import WorkspaceClient

        from axiom.services.workspace_clients import cached_workspace_client

        return cached_workspace_client("default", "", WorkspaceClient, WorkspaceClient)
    except Exception:
        return None


def _resolution_clients(uc: Any) -> List[Any]:
    """The clients to try, in order: the request's (OBO) client first, then the
    app principal. Dashboard resolution needs the app principal (no OBO
    Lakeview scope); Genie resolution works on either."""

    clients = []
    primary = getattr(uc, "w", None)
    if primary is not None:
        clients.append(primary)
    fallback = _app_principal_client()
    if fallback is not None and fallback is not primary:
        clients.append(fallback)
    return clients


def resolve_dashboard_id(uc: Any, manifest_id: str = "") -> str:
    """The LIVE 'emet Validation Intelligence' dashboard id, or the manifest
    id as a fallback. Prefers the live SDK resource because the manifest id can
    point at a deleted/re-created dashboard."""

    for client in _resolution_clients(uc):
        try:
            count = 0
            for dashboard in client.lakeview.list(page_size=100):
                count += 1
                if count > 500:
                    break
                if _s(getattr(dashboard, "display_name", "")) == DASHBOARD_NAME and _lifecycle_active(dashboard):
                    live = _s(getattr(dashboard, "dashboard_id", ""))
                    if live:
                        return live
        except Exception:
            continue
    return _s(manifest_id)


def resolve_genie_space_id(uc: Any, manifest_id: str = "") -> str:
    """The LIVE 'emet Signal Room' Genie space id, or the manifest id as a
    fallback. Prefers the live SDK resource (the manifest id can be stale)."""

    for client in _resolution_clients(uc):
        try:
            page_token = None
            pages = 0
            while pages < 10:
                pages += 1
                resp = client.genie.list_spaces(page_token=page_token) if page_token else client.genie.list_spaces()
                spaces = getattr(resp, "spaces", None) or []
                for space in spaces:
                    if _s(getattr(space, "title", "")) == GENIE_ROOM_NAME:
                        live = _s(getattr(space, "space_id", ""))
                        if live:
                            return live
                page_token = _s(getattr(resp, "next_page_token", ""))
                if not page_token:
                    break
        except Exception:
            continue
    return _s(manifest_id)


# ── detection + health ─────────────────────────────────────────────────────

def _disabled_status() -> Dict[str, Any]:
    return {
        "state": "disabled",
        "detected": False,
        "message": "emet integration is disabled (AXIOM_emet_ENABLED=false).",
    }


def _absent_status(reason: str, install: Optional[Install] = None) -> Dict[str, Any]:
    payload = {
        "state": "absent",
        "detected": False,
        "message": reason,
    }
    if install is not None:
        payload["catalog"] = install.catalog
        payload["schema"] = install.schema
        payload["source"] = install.source
    return payload


def status(config: AppConfig, uc: Any, *, timeout_s: int = 20) -> Dict[str, Any]:
    """One-shot detection + health for the Control Center header and rail tile.

    Never raises — a query failure degrades to ``absent``/``unavailable`` with a
    truthful message. ``timeout_s`` is kept tight for the bootstrap hot path.
    """

    if not bool(getattr(config, "emet_enabled", True)):
        return _disabled_status()
    install = resolve_install(config, uc)
    if install is None:
        return _absent_status(
            "emet was not detected. Set AXIOM_EMET_CATALOG or install "
            "emet so its /Shared/emet pointer is readable."
        )

    surface = install.fqn("portfolio_surface_status")
    manifest = install.fqn("workspace_manifest")
    query = (
        "SELECT s.manifest_key, s.installation_id, s.catalog_name, s.schema_name, "
        "s.workspace_state, s.dashboard_id, s.dashboard_url, s.genie_space_id, "
        "s.genie_url, s.genie_status, s.status_reason, s.manifest_updated_at, "
        "s.active_job_count, s.latest_portfolio_snapshot_ts, s.latest_portfolio_run_count, "
        "s.dashboard_registered, s.genie_ready, s.shared_surface_status, "
        "s.shared_surface_reason, m.installed_version AS installed_version "
        f"FROM {surface} s LEFT JOIN {manifest} m ON s.manifest_key = m.manifest_key "
        "WHERE s.manifest_key = 'primary' LIMIT 1"
    )
    try:
        df = uc.query_df(query, timeout_s=timeout_s)
    except Exception as exc:
        message = normalize_str(str(exc))
        # A missing schema/table means "not installed here"; anything else is a
        # transient/permission problem we surface as unavailable, not absent.
        lowered = message.lower()
        if any(token in lowered for token in ("does not exist", "not found", "cannot be found", "table_or_view")):
            return _absent_status(
                f"No emet control plane found in {install.catalog}.{install.schema}.",
                install,
            )
        return {
            "state": "unavailable",
            "detected": False,
            "catalog": install.catalog,
            "schema": install.schema,
            "source": install.source,
            "message": f"emet detection query failed: {message}" if message else "emet detection query failed.",
        }

    if df is None or df.empty:
        return _absent_status(
            f"No emet installation row in {install.catalog}.{install.schema}.workspace_manifest.",
            install,
        )

    row = df.iloc[0]
    workspace_state = _s(row.get("workspace_state")).upper()
    shared_surface = _s(row.get("shared_surface_status")).upper()
    genie_ready = _bool(row.get("genie_ready"))
    dashboard_registered = _bool(row.get("dashboard_registered"))

    if workspace_state == "READY":
        state = "available"
        message = "emet is installed and healthy."
    elif workspace_state in {"DEGRADED", "RESETTING", "INSTALLING"}:
        state = "degraded"
        message = _s(row.get("status_reason")) or f"emet workspace state is {workspace_state}."
    elif workspace_state in {"FAILED", "DELETED"}:
        state = "unavailable"
        message = _s(row.get("status_reason")) or f"emet workspace state is {workspace_state}."
    else:
        state = "degraded"
        message = _s(row.get("status_reason")) or f"emet workspace state is {workspace_state or 'unknown'}."

    # A healthy install whose shared dashboard/Genie surfaces drifted is still
    # usable but no longer coherent — flag it rather than claim perfect health.
    if state == "available" and shared_surface and shared_surface != "COHERENT":
        state = "degraded"
        message = _s(row.get("shared_surface_reason")) or f"Shared emet surfaces are {shared_surface}."

    # Resolve the LIVE dashboard + Genie ids (the manifest ids can be stale, which
    # made every Dashboard/Signal Room link 404). Build URLs from the resolved ids
    # rather than trusting the manifest's url strings.
    dashboard_id = resolve_dashboard_id(uc, _s(row.get("dashboard_id")))
    genie_id = resolve_genie_space_id(uc, _s(row.get("genie_space_id")))
    dashboard_url = f"/dashboardsv3/{dashboard_id}/published" if dashboard_id else ""
    genie_url = f"/genie/rooms/{genie_id}" if genie_id else ""

    return {
        "state": state,
        "detected": True,
        "message": message,
        "catalog": install.catalog,
        "schema": install.schema,
        "source": install.source,
        "installationId": _s(row.get("installation_id")),
        "workspaceState": workspace_state,
        "version": _s(row.get("installed_version")),
        "dashboardId": dashboard_id,
        "dashboardUrl": dashboard_url,
        "dashboardRegistered": dashboard_registered,
        "genieSpaceId": genie_id,
        "genieUrl": genie_url,
        "genieStatus": _s(row.get("genie_status")),
        "genieReady": genie_ready,
        "activeJobCount": _i(row.get("active_job_count")) or 0,
        "latestSnapshotAt": _s(row.get("latest_portfolio_snapshot_ts")),
        "latestRunCount": _i(row.get("latest_portfolio_run_count")) or 0,
        "sharedSurfaceStatus": shared_surface,
        "sharedSurfaceReason": _s(row.get("shared_surface_reason")),
        "updatedAt": _s(row.get("manifest_updated_at")),
    }


def shell_integration_status(config: AppConfig, uc: Any) -> Dict[str, Any]:
    """Best-effort status for the bootstrap shell rail tile.

    Runs the (tight-timeout) detection against the app principal. If the app
    principal lacks grants on the emet schema it may report ``absent`` while
    the surface (OBO) still connects — the surface performs the authoritative
    detection on load, per the "trust the live API over bootstrap" rule.
    """

    payload = status(config, uc, timeout_s=8)
    payload.setdefault("surface", "emet")
    payload["authoritative"] = False
    return payload


# ── portfolio overview (Overview + Jobs tabs) ──────────────────────────────

def _job_row(row: Any) -> Dict[str, Any]:
    return {
        "runId": _i(row.get("run_id")),
        "jobId": _i(row.get("job_id")),
        "jobName": _s(row.get("job_name")),
        "normalizedJobName": _s(row.get("normalized_job_name")),
        "jobStartTs": _s(row.get("job_start_ts")),
        "jobRunLabel": _s(row.get("job_run_label")),
        "trustScore": _f(row.get("trust_score")),
        "totalValidations": _i(row.get("total_validations")) or 0,
        "failedValidations": _i(row.get("failed_validations")) or 0,
        "successfulValidations": _i(row.get("successful_validations")) or 0,
        "successRatePercent": _f(row.get("success_rate_percent")),
        "criticalFailures": _i(row.get("critical_failures")) or 0,
        "potentialImpactUsd": _f(row.get("potential_impact_usd")),
        "realizedImpactUsd": _f(row.get("realized_impact_usd")),
        "avgSlaHours": _f(row.get("avg_expected_sla_hours")),
        "priorityWeightSum": _f(row.get("priority_weight_sum")),
        "successfulPriorityWeightSum": _f(row.get("successful_priority_weight_sum")),
    }


def _compare_row(row: Any) -> Dict[str, Any]:
    return {
        "trustScoreDelta": _f(row.get("trust_score_delta")),
        "successRateDelta": _f(row.get("success_rate_delta")),
        "failedValidationsDelta": _i(row.get("failed_validations_delta")),
        "criticalFailuresDelta": _i(row.get("critical_failures_delta")),
        "cutoverBlockersDelta": _i(row.get("cutover_blockers_delta")),
        "latestCutoverBlockers": _i(row.get("latest_cutover_blockers")) or 0,
        "previousCutoverBlockers": _i(row.get("previous_cutover_blockers")) or 0,
        "newRegressions": _i(row.get("new_regressions")) or 0,
        "healedValidations": _i(row.get("healed_validations")) or 0,
        "persistentFailures": _i(row.get("persistent_failures")) or 0,
        "previousRunId": _i(row.get("previous_run_id")),
        "previousTrustScore": _f(row.get("previous_trust_score")),
    }


def overview(config: AppConfig, uc: Any) -> Dict[str, Any]:
    """Portfolio payload: active jobs enriched with latest-run KPIs + deltas,
    an estate rollup, and the ranked fix-first queue. Powers both the Overview
    and Jobs tabs from one round of reads."""

    install = resolve_install(config, uc)
    if install is None:
        return {"detected": False, "jobs": [], "rollup": _empty_rollup(), "fixFirst": []}

    registry_fqn = install.fqn("job_registry_active")
    latest_fqn = install.fqn("portfolio_latest_runs")
    compare_fqn = install.fqn("portfolio_compare_latest_vs_previous")
    fixfirst_fqn = install.fqn("portfolio_fix_first")

    registry_df = uc.query_df(
        "SELECT display_job_name, normalized_job_name, execution_job_id, job_state, "
        "execution_warehouse, last_run_id, created_by, updated_at "
        f"FROM {registry_fqn} WHERE job_state = 'ACTIVE' ORDER BY display_job_name"
    )
    latest_df = uc.query_df(
        "SELECT run_id, job_id, job_name, normalized_job_name, job_start_ts, job_run_label, "
        "trust_score, total_validations, failed_validations, successful_validations, "
        "success_rate_percent, critical_failures, potential_impact_usd, realized_impact_usd, "
        "avg_expected_sla_hours, priority_weight_sum, successful_priority_weight_sum "
        f"FROM {latest_fqn} WHERE is_latest_run_for_job = true AND is_active_job = true"
    )
    try:
        compare_df = uc.query_df(f"SELECT * FROM {compare_fqn}")
    except Exception:
        compare_df = None
    try:
        fixfirst_df = uc.query_df(
            "SELECT job_name, normalized_job_name, run_id, task_key, business_priority, "
            "business_domain, business_owner, primary_failure_mode, failed_check_count, "
            "cutover_blocker, sla_breached, hours_over_sla, estimated_impact_usd, "
            "realized_impact_usd, failure_streak, fix_first_rank "
            f"FROM {fixfirst_fqn} ORDER BY fix_first_rank LIMIT 50"
        )
    except Exception:
        fixfirst_df = None

    latest_by_job: Dict[str, Dict[str, Any]] = {}
    if latest_df is not None and not latest_df.empty:
        for _, row in latest_df.iterrows():
            latest_by_job[_s(row.get("normalized_job_name"))] = _job_row(row)

    compare_by_job: Dict[str, Dict[str, Any]] = {}
    if compare_df is not None and not compare_df.empty:
        for _, row in compare_df.iterrows():
            compare_by_job[_s(row.get("normalized_job_name"))] = _compare_row(row)

    jobs: List[Dict[str, Any]] = []
    if registry_df is not None and not registry_df.empty:
        for _, row in registry_df.iterrows():
            norm = _s(row.get("normalized_job_name"))
            latest = latest_by_job.get(norm, {})
            compare = compare_by_job.get(norm, {})
            job = {
                "jobName": _s(row.get("display_job_name")) or latest.get("jobName") or norm,
                "normalizedJobName": norm,
                "executionJobId": _i(row.get("execution_job_id")),
                "jobState": _s(row.get("job_state")),
                "executionWarehouse": _s(row.get("execution_warehouse")),
                "lastRunId": _i(row.get("last_run_id")),
                "createdBy": _s(row.get("created_by")),
                "updatedAt": _s(row.get("updated_at")),
                "hasRun": bool(latest),
                "cutoverBlockers": compare.get("latestCutoverBlockers", 0),
            }
            job.update({k: v for k, v in latest.items() if k not in {"jobName", "normalizedJobName"}})
            job.update({k: v for k, v in compare.items() if k != "latestCutoverBlockers"})
            jobs.append(job)

    fix_first: List[Dict[str, Any]] = []
    if fixfirst_df is not None and not fixfirst_df.empty:
        for _, row in fixfirst_df.iterrows():
            fix_first.append(
                {
                    "jobName": _s(row.get("job_name")),
                    "runId": _i(row.get("run_id")),
                    "taskKey": _s(row.get("task_key")),
                    "businessPriority": _s(row.get("business_priority")),
                    "businessDomain": _s(row.get("business_domain")),
                    "businessOwner": _s(row.get("business_owner")),
                    "primaryFailureMode": _s(row.get("primary_failure_mode")),
                    "failedCheckCount": _i(row.get("failed_check_count")) or 0,
                    "cutoverBlocker": _bool(row.get("cutover_blocker")),
                    "slaBreached": _bool(row.get("sla_breached")),
                    "hoursOverSla": _f(row.get("hours_over_sla")),
                    "estimatedImpactUsd": _f(row.get("estimated_impact_usd")),
                    "realizedImpactUsd": _f(row.get("realized_impact_usd")),
                    "failureStreak": _i(row.get("failure_streak")) or 0,
                    "fixFirstRank": _i(row.get("fix_first_rank")),
                }
            )

    return {
        "detected": True,
        "install": _install_summary(install),
        "jobs": jobs,
        "rollup": _rollup(jobs),
        "fixFirst": fix_first,
    }


def _install_summary(install: Install) -> Dict[str, Any]:
    return {"catalog": install.catalog, "schema": install.schema, "source": install.source}


def _empty_rollup() -> Dict[str, Any]:
    return {
        "trustScore": None,
        "jobCount": 0,
        "jobsWithRuns": 0,
        "failingJobCount": 0,
        "totalValidations": 0,
        "totalFailed": 0,
        "criticalFailures": 0,
        "cutoverBlockers": 0,
        "potentialImpactUsd": 0.0,
        "realizedImpactUsd": 0.0,
    }


def _rollup(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    weight_num = 0.0
    weight_den = 0.0
    total_validations = 0
    total_failed = 0
    critical = 0
    cutover = 0
    potential = 0.0
    realized = 0.0
    jobs_with_runs = 0
    failing = 0
    for job in jobs:
        if not job.get("hasRun"):
            continue
        jobs_with_runs += 1
        num = job.get("successfulPriorityWeightSum")
        den = job.get("priorityWeightSum")
        if num is not None:
            weight_num += num
        if den is not None:
            weight_den += den
        total_validations += int(job.get("totalValidations") or 0)
        failed = int(job.get("failedValidations") or 0)
        total_failed += failed
        if failed > 0:
            failing += 1
        critical += int(job.get("criticalFailures") or 0)
        cutover += int(job.get("cutoverBlockers") or 0)
        potential += float(job.get("potentialImpactUsd") or 0.0)
        realized += float(job.get("realizedImpactUsd") or 0.0)
    trust = round(weight_num / weight_den * 100, 1) if weight_den > 0 else None
    return {
        "trustScore": trust,
        "jobCount": len(jobs),
        "jobsWithRuns": jobs_with_runs,
        "failingJobCount": failing,
        "totalValidations": total_validations,
        "totalFailed": total_failed,
        "criticalFailures": critical,
        "cutoverBlockers": cutover,
        "potentialImpactUsd": round(potential, 2),
        "realizedImpactUsd": round(realized, 2),
    }


# ── run detail (summary + validations + per-check evidence) ────────────────

def run_detail(config: AppConfig, uc: Any, run_id: int) -> Dict[str, Any]:
    install = resolve_install(config, uc)
    if install is None:
        return {"detected": False, "runId": run_id}
    rid = int(run_id)  # numeric-only — safe to inline

    summary_fqn = install.fqn("exec_run_summary")
    validations_fqn = install.fqn("run_validations")
    checks_fqn = install.fqn("run_checks")
    domains_fqn = install.fqn("exec_domain_breakdown")

    summary_df = uc.query_df(f"SELECT * FROM {summary_fqn} WHERE run_id = {rid} LIMIT 1")
    header: Dict[str, Any] = {}
    if summary_df is not None and not summary_df.empty:
        row = summary_df.iloc[0]
        header = {
            "runId": rid,
            "jobId": _i(row.get("job_id")),
            "jobName": _s(row.get("job_name")),
            "jobStartTs": _s(row.get("job_start_ts")),
            "trustScore": _f(row.get("trust_score")),
            "totalValidations": _i(row.get("total_validations")) or 0,
            "failedValidations": _i(row.get("failed_validations")) or 0,
            "successfulValidations": _i(row.get("successful_validations")) or 0,
            "successRatePercent": _f(row.get("success_rate_percent")),
            "criticalFailures": _i(row.get("critical_failures")) or 0,
            "potentialImpactUsd": _f(row.get("potential_impact_usd")),
            "realizedImpactUsd": _f(row.get("realized_impact_usd")),
            "avgSlaHours": _f(row.get("avg_expected_sla_hours")),
            "validationsWithSla": _i(row.get("validations_with_sla_count")) or 0,
        }

    validations_df = uc.query_df(
        "SELECT task_key, status, business_priority, business_domain, business_owner, "
        "source_table, target_table, primary_failure_mode, failed_check_count, "
        "cutover_blocker, sla_breached, hours_over_sla, estimated_impact_usd, "
        "realized_impact_usd, runtime_seconds "
        f"FROM {validations_fqn} WHERE run_id = {rid} "
        "ORDER BY cutover_blocker DESC, "
        "CASE business_priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 "
        "WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END, "
        "status DESC, task_key"
    )
    validations: List[Dict[str, Any]] = []
    if validations_df is not None and not validations_df.empty:
        for _, row in validations_df.iterrows():
            validations.append(
                {
                    "taskKey": _s(row.get("task_key")),
                    "status": _s(row.get("status")).upper(),
                    "businessPriority": _s(row.get("business_priority")),
                    "businessDomain": _s(row.get("business_domain")),
                    "businessOwner": _s(row.get("business_owner")),
                    "sourceTable": _s(row.get("source_table")),
                    "targetTable": _s(row.get("target_table")),
                    "primaryFailureMode": _s(row.get("primary_failure_mode")),
                    "failedCheckCount": _i(row.get("failed_check_count")) or 0,
                    "cutoverBlocker": _bool(row.get("cutover_blocker")),
                    "slaBreached": _bool(row.get("sla_breached")),
                    "hoursOverSla": _f(row.get("hours_over_sla")),
                    "estimatedImpactUsd": _f(row.get("estimated_impact_usd")),
                    "realizedImpactUsd": _f(row.get("realized_impact_usd")),
                    "runtimeSeconds": _f(row.get("runtime_seconds")),
                }
            )

    checks_df = uc.query_df(
        "SELECT task_key, check_category, check_name, status, details "
        f"FROM {checks_fqn} WHERE run_id = {rid} "
        "ORDER BY CASE WHEN status = 'FAIL' THEN 0 WHEN status = 'UNKNOWN' THEN 1 ELSE 2 END, "
        "task_key, check_category LIMIT 500"
    )
    checks: List[Dict[str, Any]] = []
    if checks_df is not None and not checks_df.empty:
        for _, row in checks_df.iterrows():
            checks.append(
                {
                    "taskKey": _s(row.get("task_key")),
                    "checkCategory": _s(row.get("check_category")),
                    "checkName": _s(row.get("check_name")),
                    "status": _s(row.get("status")).upper(),
                    "details": _s(row.get("details")),
                }
            )

    try:
        domains_df = uc.query_df(
            "SELECT business_domain, total_validations, failed_validations, "
            "success_rate_percent, potential_impact_usd, realized_impact_usd "
            f"FROM {domains_fqn} WHERE run_id = {rid} ORDER BY failed_validations DESC"
        )
    except Exception:
        domains_df = None
    domains: List[Dict[str, Any]] = []
    if domains_df is not None and not domains_df.empty:
        for _, row in domains_df.iterrows():
            domains.append(
                {
                    "businessDomain": _s(row.get("business_domain")),
                    "totalValidations": _i(row.get("total_validations")) or 0,
                    "failedValidations": _i(row.get("failed_validations")) or 0,
                    "successRatePercent": _f(row.get("success_rate_percent")),
                    "potentialImpactUsd": _f(row.get("potential_impact_usd")),
                    "realizedImpactUsd": _f(row.get("realized_impact_usd")),
                }
            )

    return {
        "detected": True,
        "runId": rid,
        "header": header,
        "validations": validations,
        "checks": checks,
        "domains": domains,
    }


# ── trigger + monitor (Databricks Jobs API via the request's client) ───────

def _extract_run_id(waiter: Any) -> Optional[int]:
    """Pull the run id out of the SDK ``run_now`` return, whatever its shape.

    ``JobsExt.run_now`` returns a ``Wait[Run]`` whose ids live in a private bind
    dict and on a ``.response`` attribute — mirror the defensive extraction the
    Genie starter uses."""

    for attr in ("run_id",):
        value = getattr(waiter, attr, None)
        if value is not None:
            return _i(value)
    response = getattr(waiter, "response", None)
    if response is not None:
        value = getattr(response, "run_id", None)
        if value is not None:
            return _i(value)
    bind_fn = getattr(waiter, "bind", None)
    if callable(bind_fn):
        try:
            bind = bind_fn() or {}
            if bind.get("run_id") is not None:
                return _i(bind.get("run_id"))
        except Exception:
            return None
    return None


def _run_page_url(config: AppConfig, job_id: Optional[int], run_id: Optional[int]) -> str:
    host = normalize_str(getattr(config, "workspace_host", ""))
    if not host or job_id is None or run_id is None:
        return ""
    return f"{host}/jobs/{job_id}/runs/{run_id}"


def trigger_run(
    config: AppConfig,
    uc: Any,
    *,
    execution_job_id: int,
    idempotency_token: str = "",
) -> Dict[str, Any]:
    """Launch a emet validation run via Jobs ``run-now`` on the request's
    (OBO) client, so the run is attributed to the acting steward."""

    job_id = int(execution_job_id)
    client = getattr(uc, "w", None)
    if client is None:
        raise RuntimeError("No Databricks client is available to trigger the run.")
    kwargs: Dict[str, Any] = {"job_id": job_id}
    token = normalize_str(idempotency_token)
    if token:
        kwargs["idempotency_token"] = token
    waiter = client.jobs.run_now(**kwargs)
    run_id = _extract_run_id(waiter)
    return {
        "jobId": job_id,
        "runId": run_id,
        "runPageUrl": _run_page_url(config, job_id, run_id),
    }


def _enum(value: Any) -> str:
    if value is None:
        return ""
    return _s(getattr(value, "value", value)).upper()


def _effective_status(life: str, result: str, task_results: List[str]) -> str:
    if life in _RUNNING_LIFECYCLE:
        return "running"
    if life == "TERMINATED" and result == "SUCCESS":
        return "success"
    # emet multi-task runs can report INTERNAL_ERROR at the run level even
    # when every validation task succeeded (a state-finalization race) — trust
    # "all tasks SUCCESS" over the run-level envelope.
    if task_results and all(state == "SUCCESS" for state in task_results):
        return "success"
    if result in {"FAILED", "TIMEDOUT", "CANCELED", "MAXIMUM_CONCURRENT_RUNS_REACHED"}:
        return "failed"
    if life == "INTERNAL_ERROR":
        return "failed"
    if result == "SUCCESS":
        return "success"
    return "unknown"


def run_live_status(config: AppConfig, uc: Any, run_id: int) -> Dict[str, Any]:
    """Live Databricks job-run status for the run monitor."""

    rid = int(run_id)
    client = getattr(uc, "w", None)
    if client is None:
        raise RuntimeError("No Databricks client is available to read the run.")
    run = client.jobs.get_run(run_id=rid)
    state = getattr(run, "state", None)
    life = _enum(getattr(state, "life_cycle_state", None))
    result = _enum(getattr(state, "result_state", None))
    message = _s(getattr(state, "state_message", ""))
    tasks = getattr(run, "tasks", None) or []
    task_payloads: List[Dict[str, Any]] = []
    task_results: List[str] = []
    for task in tasks:
        task_state = getattr(task, "state", None)
        t_life = _enum(getattr(task_state, "life_cycle_state", None))
        t_result = _enum(getattr(task_state, "result_state", None))
        if t_result:
            task_results.append(t_result)
        task_payloads.append(
            {
                "taskKey": _s(getattr(task, "task_key", "")),
                "lifeCycleState": t_life,
                "resultState": t_result,
            }
        )
    return {
        "runId": rid,
        "lifeCycleState": life,
        "resultState": result,
        "stateMessage": message,
        "effectiveStatus": _effective_status(life, result, task_results),
        "startTime": _i(getattr(run, "start_time", None)),
        "endTime": _i(getattr(run, "end_time", None)),
        "runPageUrl": _s(getattr(run, "run_page_url", "")),
        "tasks": task_payloads,
    }


def genie_space_id(config: AppConfig, uc: Any) -> str:
    """The LIVE emet Signal Room space id, or '' — resolved by name via the
    SDK (the manifest's genie_space_id can be stale), falling back to the
    manifest id only if live resolution finds nothing."""

    install = resolve_install(config, uc)
    if install is None:
        return ""
    manifest_id = ""
    manifest = install.fqn("workspace_manifest")
    try:
        df = uc.query_df(
            f"SELECT genie_space_id FROM {manifest} WHERE manifest_key = 'primary' LIMIT 1"
        )
        if df is not None and not df.empty:
            manifest_id = _s(df.iloc[0].get("genie_space_id"))
    except Exception:
        manifest_id = ""
    return resolve_genie_space_id(uc, manifest_id)


__all__ = [
    "Install",
    "MANAGED_SCHEMA",
    "SOURCE",
    "genie_space_id",
    "overview",
    "resolve_install",
    "run_detail",
    "run_live_status",
    "shell_integration_status",
    "status",
    "trigger_run",
]
