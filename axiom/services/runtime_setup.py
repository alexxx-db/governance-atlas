from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping

from axiom.services import capabilities as capability_service

SAFE_OPERATIONAL_SHARING_PATHS = [
    "actor-scoped OBO",
    "validated dynamic-view plane",
    "warehouse CAN VIEW plus downstream visibility rules",
]


def _utc_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return _utc_iso(datetime.now(timezone.utc))


def _future_iso(seconds: int) -> str:
    return _utc_iso(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def _normalize_state(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    if text in {"available", "live", "success"}:
        return "available"
    if text in {"degraded", "warning"}:
        return "degraded"
    if text in {"unavailable", "error", "failed"}:
        return "unavailable"
    if text in {"unknown", "skipped"}:
        return "unknown"
    return fallback


def _state_rank(state: str) -> int:
    return {
        "available": 3,
        "degraded": 2,
        "unknown": 1,
        "unavailable": 0,
    }.get(_normalize_state(state), 1)


def _worst_state(*states: str, fallback: str = "unknown") -> str:
    normalized = [
        _normalize_state(state, fallback)
        for state in states
        if str(state or "").strip()
    ]
    if not normalized:
        return fallback
    return min(normalized, key=_state_rank)


def _check(
    key: str,
    label: str,
    state: str,
    summary: str,
    detail: str = "",
    *,
    observed_at: str,
    stale_after: str,
    category: str = "setup",
    evidence: str = "",
    remediation: str = "",
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "category": category,
        "state": _normalize_state(state),
        "summary": summary,
        "detail": detail,
        "evidence": evidence,
        "remediation": remediation,
        "observedAt": observed_at,
        "staleAfter": stale_after,
    }


def _sequence_step(
    order: int,
    key: str,
    label: str,
    state: str,
    summary: str,
    detail: str = "",
    *,
    observed_at: str,
    stale_after: str,
    category: str = "setup",
    evidence: str = "",
    remediation: str = "",
    rerunnable: bool = True,
    prerequisites: Iterable[str] | None = None,
    unlocks: Iterable[str] | None = None,
) -> Dict[str, Any]:
    step = _check(
        key,
        label,
        state,
        summary,
        detail,
        observed_at=observed_at,
        stale_after=stale_after,
        category=category,
        evidence=evidence,
        remediation=remediation,
    )
    step.update(
        {
            "order": order,
            "rerunnable": rerunnable,
            "prerequisites": list(prerequisites or []),
            "unlocks": list(unlocks or []),
        }
    )
    return step


def _flag_state(flag: Mapping[str, Any] | None, fallback: str = "unknown") -> str:
    if not flag:
        return fallback
    return _normalize_state(str(flag.get("state") or ""), fallback)


def _flag_reason(flag: Mapping[str, Any] | None, fallback: str) -> str:
    if not flag:
        return fallback
    reason = str(flag.get("reason") or "").strip()
    return reason or fallback


def _safe_operational_sharing_path(validated_path: str = "") -> Dict[str, Any]:
    normalized = str(validated_path or "").strip()
    return {
        "required": True,
        "state": "available" if normalized else "unavailable",
        "validatedPath": normalized,
        "acceptedPaths": list(SAFE_OPERATIONAL_SHARING_PATHS),
    }


def _capability_check(
    key: str,
    label: str,
    flag: Mapping[str, Any] | None,
    success_summary: str,
    *,
    observed_at: str,
    stale_after: str,
    remediation: str,
) -> Dict[str, Any]:
    state = _flag_state(flag)
    detail = _flag_reason(flag, f"{label} has not been verified yet.")
    summary_by_state = {
        "available": success_summary,
        "degraded": detail,
        "unavailable": detail,
        "unknown": detail,
    }
    return _check(
        key,
        label,
        state,
        summary_by_state.get(state, detail),
        detail if state != "available" else "",
        observed_at=observed_at,
        stale_after=stale_after,
        category="capability",
        evidence=detail,
        remediation=remediation if state != "available" else "",
    )


def _app_service_principal_probe(
    *,
    runtime_status: Mapping[str, Any],
    runtime_state: str,
    store_state: str,
    warehouse_id: str,
    gov_catalog: str,
    gov_schema: str,
) -> Dict[str, str]:
    client = runtime_status.get("client") if isinstance(runtime_status, Mapping) else {}
    auth_mode = str((client or {}).get("authMode") or "").strip()
    auth_type = str((client or {}).get("authType") or "").strip()
    host_present = bool((client or {}).get("hostPresent"))
    client_error = str((client or {}).get("clientInitError") or "").strip()
    explicit_app_principal = auth_mode == "oauth-m2m-env" and host_present
    config_ready = bool(warehouse_id and gov_catalog and gov_schema)
    runtime_state = _normalize_state(runtime_state)
    store_state = _normalize_state(store_state)
    evidence_parts = [
        f"runtime={runtime_state}",
        f"store={store_state}",
        f"config={'present' if config_ready else 'missing'}",
        f"clientAuthMode={auth_mode or 'unknown'}",
        f"clientAuthType={auth_type or 'unknown'}",
        f"host={'present' if host_present else 'missing'}",
    ]
    if client_error:
        evidence_parts.append(f"clientInitError={client_error}")
    evidence = ", ".join(evidence_parts)

    if not config_ready:
        return {
            "state": "unavailable",
            "evidence": evidence,
            "detail": "Deploy-time warehouse, catalog, or schema configuration is still missing.",
        }
    if runtime_state == "unavailable":
        return {
            "state": "unavailable",
            "evidence": evidence,
            "detail": "The app-principal SQL probe did not reach the live warehouse runtime.",
        }
    if (
        runtime_state == "available"
        and store_state == "available"
        and explicit_app_principal
    ):
        return {
            "state": "available",
            "evidence": evidence,
            "detail": "The app-principal SQL runtime explicitly proved warehouse and governance-store access.",
        }
    if runtime_state == "available" and store_state == "available":
        return {
            "state": "unknown",
            "evidence": evidence,
            "detail": (
                "The warehouse runtime and governance store responded, but the client auth context did not "
                "explicitly prove app-principal ownership."
            ),
        }
    if runtime_state in {"degraded", "unknown"} or store_state in {
        "degraded",
        "unknown",
    }:
        return {
            "state": "degraded",
            "evidence": evidence,
            "detail": "The app principal partially reached the runtime, but store or runtime proof is still degraded.",
        }
    return {
        "state": "unknown",
        "evidence": evidence,
        "detail": "The app-principal reachability probe did not produce a definitive state.",
    }


def _claim_item(
    check: Mapping[str, Any], *, surface: str, effect: str
) -> Dict[str, Any]:
    return {
        "key": str(check.get("key") or surface).strip() or surface,
        "surface": surface,
        "state": _normalize_state(str(check.get("state") or "unknown")),
        "reason": str(check.get("summary") or check.get("detail") or "").strip(),
        "effect": effect,
    }


def _workspace_access_gate(
    check: Mapping[str, Any],
    *,
    blocked_surfaces: Iterable[str],
) -> Dict[str, Any]:
    return {
        "key": str(check.get("key") or "").strip(),
        "label": str(check.get("label") or "").strip(),
        "state": _normalize_state(str(check.get("state") or "unknown")),
        "reason": str(check.get("summary") or check.get("detail") or "").strip(),
        "proofSource": str(check.get("evidence") or "").strip(),
        "remediation": str(check.get("remediation") or "").strip(),
        "blockedSurfaces": list(blocked_surfaces),
    }


def _surface_policy(
    *,
    key: str,
    label: str,
    allowed: bool,
    state: str,
    mode: str,
    visibility_scope: str,
    reason: str,
    blocked_surfaces: Iterable[str] | None = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "allowed": bool(allowed),
        "state": _normalize_state(state),
        "mode": str(mode or "").strip(),
        "visibilityScope": str(visibility_scope or "").strip(),
        "reason": str(reason or "").strip(),
        "blockedSurfaces": list(blocked_surfaces or []),
    }


def _feature_flag(
    *,
    key: str,
    label: str,
    enabled: bool,
    state: str,
    summary: str,
    rationale: str,
    truth_source: str,
    rollout: str,
    rollout_policy: str,
    scope: str,
    default_state: str,
    expires_after: str,
    removal_ticket: str,
    rollback: str,
    description: str,
    owner: str,
    source: str,
    reason: str = "",
    disabled_reason: str = "",
    unavailable_reason: str = "",
) -> Dict[str, Any]:
    normalized_state = _normalize_state(state)
    canonical_reason = str(reason or "").strip()
    if not canonical_reason:
        if normalized_state == "available":
            canonical_reason = str(summary or description or rationale).strip()
        elif normalized_state == "degraded":
            canonical_reason = str(rationale or summary or description).strip()
        else:
            canonical_reason = str(
                unavailable_reason
                or disabled_reason
                or rationale
                or summary
                or description
            ).strip()

    disabled_text = str(disabled_reason or "").strip()
    if not disabled_text and not enabled:
        disabled_text = canonical_reason

    unavailable_text = str(unavailable_reason or "").strip()
    if not unavailable_text and normalized_state == "unavailable":
        unavailable_text = canonical_reason

    return {
        "key": key,
        "label": label,
        "enabled": bool(enabled),
        "state": normalized_state,
        "summary": summary or canonical_reason,
        "detail": description,
        "reason": canonical_reason,
        "disabledReason": disabled_text,
        "unavailableReason": unavailable_text,
        "kind": "surface",
        "owner": owner,
        "source": source,
        "rationale": rationale,
        "truthSource": truth_source,
        "rollout": rollout,
        "rolloutPolicy": rollout_policy,
        "scope": scope,
        "defaultState": default_state,
        "expiresAfter": expires_after,
        "removalTicket": removal_ticket,
        "rollback": rollback,
        "description": description,
    }


def feature_flag_inventory(
    *,
    diagnostics_enabled: bool,
    capabilities: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    workload_state = _flag_state(capabilities.get("workloadVisibility"))
    export_state = _flag_state(capabilities.get("exportAllowed"))
    table_lineage_state = _flag_state(capabilities.get("tableLineage"))
    return [
        _feature_flag(
            key="workspace_setup_diagnostics",
            label="Workspace setup diagnostics",
            enabled=bool(diagnostics_enabled),
            state="available" if diagnostics_enabled else "unavailable",
            summary="Shell-owned operator diagnostics are available."
            if diagnostics_enabled
            else "Shell-owned operator diagnostics are disabled.",
            rationale="Expose the operator-only setup truth needed for first-run validation without creating a separate admin route.",
            truth_source="runtime configuration",
            rollout="global",
            rollout_policy="Always available to operators while diagnostics are enabled.",
            scope="shell diagnostics + bootstrap-unavailable fallback",
            default_state="enabled" if diagnostics_enabled else "disabled",
            expires_after="Before a dedicated admin diagnostics surface replaces the shell-owned setup view.",
            removal_ticket="phase-5-admin-diagnostics-route",
            rollback="Hide the diagnostics surface while preserving /api/runtime/status for operator probes.",
            description="Read-only setup and diagnostics baseline surfaced in the shell-owned operator view.",
            owner="phase-5-foundation",
            source="code",
            disabled_reason=""
            if diagnostics_enabled
            else "Diagnostics are intentionally disabled until the shell-owned setup view is enabled.",
            unavailable_reason=""
            if diagnostics_enabled
            else "Diagnostics are not available because the shell-owned setup view is disabled.",
        ),
        _feature_flag(
            key="per_user_authorization",
            label="Per-user authorization",
            enabled=False,
            state="unavailable",
            summary="Per-user authorization is not implemented yet.",
            rationale="Keep actor-scoped protected reads disabled until Databricks user authorization / OBO is real in this runtime.",
            truth_source="Databricks Apps OBO",
            rollout="blocked",
            rollout_policy="Unavailable until install/setup proves user authorization is enabled and consented.",
            scope="protected reads and actor-scoped surfaces",
            default_state="disabled",
            expires_after="Remove after per-user authorization is implemented and verified in install/setup.",
            removal_ticket="phase-5-per-user-auth",
            rollback="Keep protected reads read-only until a per-user authorization plane is available.",
            description="Truthful reminder that actor-scoped reads remain conservative without OBO.",
            owner="runtime-auth",
            source="capability-gap",
            disabled_reason="Actor-scoped protected reads stay disabled until Databricks user authorization / OBO is real.",
            unavailable_reason="Databricks user authorization / OBO is not implemented in the live runtime yet.",
        ),
        {
            **_feature_flag(
                key="query_history_surface",
                label="Query history surface",
                enabled=workload_state == "available",
                state=workload_state,
                summary="Query and workload visibility is workspace-scoped.",
                rationale="Do not expose query and workload tabs unless the workspace proves a safe sharing path for non-admin actors.",
                truth_source="Databricks query history",
                rollout="workspace-scoped",
                rollout_policy="Only enable when the capability probe proves OBO, a validated dynamic-view plane, or warehouse CAN VIEW plus downstream visibility rules for the current actor.",
                scope="queries, workloads, usage, and preview evidence",
                default_state="disabled",
                expires_after="Revisit after the query/workload plane is production-safe for parity-core surfaces.",
                removal_ticket="phase-10-query-usage-surface",
                rollback="Keep query-history-driven surfaces hidden or explicitly unavailable when the workspace does not expose a safe plane.",
                description="Controls whether query and workload visibility may be rendered as an actual surface once a safe non-admin sharing path is validated.",
                owner="workspace-capabilities",
                source="capability-probe",
                disabled_reason="Query and workload surfaces remain disabled until the capability probe proves OBO, a validated dynamic-view plane, or warehouse CAN VIEW plus downstream visibility rules.",
                unavailable_reason=_flag_reason(
                    capabilities.get("workloadVisibility"),
                    "Query history is not available in this workspace.",
                ),
            ),
            "safeSharingPath": _safe_operational_sharing_path(),
        },
        _feature_flag(
            key="export_delivery",
            label="Export delivery",
            enabled=export_state == "available",
            state=export_state,
            summary="Export delivery is guarded by authenticated, redacted delivery.",
            rationale="Exports must remain disabled until delivery, audit, and redaction contracts exist.",
            truth_source="authenticated export policy",
            rollout="workspace-scoped",
            rollout_policy="Only enable when the runtime can deliver authenticated, redacted exports safely.",
            scope="discovery export and detail export",
            default_state="disabled",
            expires_after="Keep until async export jobs or safe synchronous export limits are implemented.",
            removal_ticket="phase-9-export-job-model",
            rollback="Keep export unavailable until delivery, redaction, and audit proof exist.",
            description="Controls whether export can deliver authenticated, redacted result sets.",
            owner="discovery",
            source="capability-probe",
            disabled_reason="Export remains disabled until authenticated delivery, audit, and redaction contracts exist.",
            unavailable_reason=_flag_reason(
                capabilities.get("exportAllowed"),
                "Export delivery is unavailable in this workspace.",
            ),
        ),
        _feature_flag(
            key="table_lineage_surface",
            label="Table lineage surface",
            enabled=table_lineage_state == "available",
            state=table_lineage_state,
            summary="Lineage is workspace-scoped and capability-gated.",
            rationale="Lineage must only open when Unity Catalog lineage truth is available for the actor and workspace.",
            truth_source="Unity Catalog lineage probe",
            rollout="workspace-scoped",
            rollout_policy="Only enable when the table lineage capability is available for the current actor.",
            scope="lineage graph and drawer",
            default_state="disabled",
            expires_after="Remove once lineage is a stable capability-gated default surface.",
            removal_ticket="phase-8-lineage-read-only-core",
            rollback="Keep lineage affordances explicit and hidden when table lineage is not available.",
            description="Controls whether lineage can open as a truthful live surface.",
            owner="lineage",
            source="capability-probe",
            disabled_reason="Lineage remains hidden until Unity Catalog lineage truth is available for the current actor.",
            unavailable_reason=_flag_reason(
                capabilities.get("tableLineage"),
                "Table lineage is unavailable in this workspace.",
            ),
        ),
        _feature_flag(
            key="background_work_plane",
            label="Background work plane",
            enabled=False,
            state="unavailable",
            summary="Background execution is unavailable.",
            rationale="Durable background work must not be implied until a managed runner and job registry exist.",
            truth_source="managed background work plane",
            rollout="blocked",
            rollout_policy="Unavailable until the background work plane is implemented and install/setup can probe it.",
            scope="corpus rebuilds, async exports, notification fanout, scheduled quality work",
            default_state="disabled",
            expires_after="Keep until the background work plane and operator queue diagnostics ship.",
            removal_ticket="phase-7-background-work-plane",
            rollback="Keep all durable background work absent until a managed runner and job registry are in place.",
            description="Marks that background work is still a missing runtime capability.",
            owner="runtime",
            source="contract-gap",
            disabled_reason="Background work remains disabled until a managed runner and job registry exist.",
            unavailable_reason="The background work plane is not implemented in the live runtime yet.",
        ),
        _feature_flag(
            key="classification_recommendations",
            label="Classification recommendations",
            enabled=False,
            state="unavailable",
            summary="Classification recommendations are operator-only.",
            rationale="Classification detections stay privileged and operator-only until redaction and approval flows exist.",
            truth_source="Databricks classification detections",
            rollout="blocked",
            rollout_policy="Unavailable until privileged ingestion, redaction, and acceptance workflows are implemented.",
            scope="sensitivity and classification recommendation ingestion",
            default_state="disabled",
            expires_after="Keep until classification recommendations can ship as steward-reviewed guidance.",
            removal_ticket="phase-11-classification-recommendations",
            rollback="Keep recommendation evidence hidden until privileged ingestion and redaction are implemented.",
            description="Records that classification recommendations are not yet a general-facing source of truth.",
            owner="governance",
            source="capability-gap",
            disabled_reason="Recommendation evidence stays disabled until redaction and acceptance flows exist.",
            unavailable_reason="Databricks classification detections are privileged and not exposed as general truth yet.",
        ),
        _feature_flag(
            key="transaction_fallback_mode",
            label="Transaction fallback mode",
            enabled=True,
            state="degraded",
            summary="Fallback-only mutation ordering is active.",
            rationale="Fallback ordering is the only portable write mode until transaction eligibility is proven in the workspace.",
            truth_source="idempotent write ordering",
            rollout="default",
            rollout_policy="Keep fallback ordering as the default until install/setup proves transaction support.",
            scope="control-plane mutations",
            default_state="fallback-only",
            expires_after="Replace after a transaction eligibility matrix is implemented and validated.",
            removal_ticket="phase-5-transaction-eligibility-matrix",
            rollback="Keep fallback ordering as the portable default until proven transactions are available in the target workspace.",
            description="States that portable fallback ordering remains the default mutation path.",
            owner="governance",
            source="contract-default",
            reason="Portable fallback ordering remains the truthful default mutation path until install/setup proves transaction support.",
        ),
    ]


def setup_payload(
    *,
    runtime_status: Mapping[str, Any],
    store_status: Mapping[str, Any],
    capabilities: Mapping[str, Mapping[str, Any]],
    warehouse_id: str,
    gov_catalog: str,
    gov_schema: str,
    authenticated: bool,
    actor_role: str,
    diagnostics_enabled: bool,
    per_user_authorization: bool = False,
) -> Dict[str, Any]:
    observed_at = _now_iso()
    stale_after = _future_iso(60)
    runtime_state = _normalize_state(str(runtime_status.get("state") or "unknown"))
    store_state = _normalize_state(str(store_status.get("state") or "unknown"))
    role = str(actor_role or "reader").strip().lower() or "reader"
    auth_mode = capability_service.runtime_auth_mode(
        authenticated=authenticated,
        per_user_authorization=bool(per_user_authorization),
    )
    read_visibility_scope = capability_service.runtime_visibility_scope(auth_mode)

    runtime_message = str(runtime_status.get("message") or "").strip()
    store_message = str(store_status.get("message") or "").strip()
    app_service_principal_probe = _app_service_principal_probe(
        runtime_status=runtime_status,
        runtime_state=runtime_state,
        store_state=store_state,
        warehouse_id=warehouse_id,
        gov_catalog=gov_catalog,
        gov_schema=gov_schema,
    )
    app_service_principal_state = app_service_principal_probe["state"]
    app_service_principal_evidence = app_service_principal_probe["evidence"]

    checks = [
        _check(
            "warehouse_runtime",
            "Warehouse runtime",
            runtime_state,
            "The live metadata runtime is reachable."
            if runtime_state == "available"
            else runtime_message
            or "The live metadata runtime is not currently reachable.",
            "" if runtime_state == "available" else runtime_message,
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=runtime_message
            or "Runtime health is derived from the live SQL metadata probe.",
            remediation=""
            if runtime_state == "available"
            else "Verify the configured warehouse is running and that the app can execute Unity Catalog metadata queries.",
        ),
        _check(
            "governance_store",
            "Governance store",
            store_state,
            "The governance control-plane store is reachable."
            if store_state == "available"
            else store_message
            or "The governance control-plane store is degraded or unavailable.",
            "" if store_state == "available" else store_message,
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=store_message
            or "Governance store reachability is derived from the control-plane probe.",
            remediation=""
            if store_state == "available"
            else "Verify the governance catalog/schema exists and that the app principal can read and write the control-plane tables.",
        ),
        _check(
            "governance_config",
            "Governance config",
            "available"
            if warehouse_id and gov_catalog and gov_schema
            else "unavailable",
            "Warehouse, catalog, and schema configuration are present."
            if warehouse_id and gov_catalog and gov_schema
            else "Warehouse, catalog, or schema configuration is missing.",
            ""
            if warehouse_id and gov_catalog and gov_schema
            else "Deploy-time environment injection must provide DATABRICKS_WAREHOUSE_ID, AXIOM_CATALOG, and AXIOM_SCHEMA.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=(
                f"warehouse={warehouse_id or 'missing'}, catalog={gov_catalog or 'missing'}, schema={gov_schema or 'missing'}"
            ),
            remediation=""
            if warehouse_id and gov_catalog and gov_schema
            else "Inject the warehouse, governance catalog, and governance schema settings before the app is marked ready.",
        ),
        _check(
            "identity_forwarding",
            "Forwarded actor identity",
            "available" if authenticated else "degraded",
            "A forwarded Databricks user identity is present."
            if authenticated
            else "No forwarded Databricks user identity was detected; the app is in read-only mode.",
            ""
            if authenticated
            else "Governance writes require a forwarded user identity header.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=(
                "A forwarded Databricks user identity header is present."
                if authenticated
                else "No forwarded Databricks user identity header was available on the request."
            ),
            remediation=""
            if authenticated
            else "Use a Databricks App session with forwarded user identity before enabling write-capable governance actions.",
        ),
        _check(
            "app_service_principal",
            "App service-principal reachability and permissions",
            app_service_principal_state,
            "The app service principal can reach the warehouse and governance store."
            if app_service_principal_state == "available"
            else "The app service-principal reachability and permissions have not been proven yet.",
            ""
            if app_service_principal_state == "available"
            else app_service_principal_probe["detail"],
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=app_service_principal_evidence,
            remediation=""
            if app_service_principal_state == "available"
            else "Grant the app service principal access to the warehouse and governance catalog/schema, then rerun install/setup.",
        ),
        _check(
            "per_user_authorization",
            "Per-user authorization",
            "unavailable",
            "Per-user Databricks authorization / OBO is not implemented in the live runtime yet.",
            "Actor-scoped reads remain conservative and capability-gated until a per-user enforcement plane is added.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence="The current runtime authenticates with forwarded identity headers only; no per-user OBO token flow is exposed.",
            remediation="Add and verify Databricks Apps per-user authorization before enabling actor-scoped protected reads.",
        ),
        _capability_check(
            "system_inventory",
            "System inventory",
            capabilities.get("systemInventoryRead"),
            "Live visible-inventory reads are available.",
            observed_at=observed_at,
            stale_after=stale_after,
            remediation="Verify Unity Catalog inventory permissions and keep the capability probe actor-scoped.",
        ),
        _capability_check(
            "table_lineage",
            "Table lineage",
            capabilities.get("tableLineage"),
            "Live table-lineage reads are available.",
            observed_at=observed_at,
            stale_after=stale_after,
            remediation="Verify Unity Catalog lineage permissions and label missing or masked lineage explicitly in the UI.",
        ),
        {
            **_capability_check(
                "workload_visibility",
                "Query and workload visibility",
                capabilities.get("workloadVisibility"),
                "Operational query and workload visibility is available for the current actor.",
                observed_at=observed_at,
                stale_after=stale_after,
                remediation="Treat workload and query surfaces as unavailable until install/setup proves OBO, a validated dynamic-view plane, or warehouse CAN VIEW plus downstream visibility rules.",
            ),
            "safeSharingPath": _safe_operational_sharing_path(),
        },
        _capability_check(
            "export_delivery",
            "Export delivery prerequisites",
            capabilities.get("exportAllowed"),
            "Authenticated export delivery prerequisites are available.",
            observed_at=observed_at,
            stale_after=stale_after,
            remediation="Keep export disabled until server-side auth, redaction, delivery staging, and audit constraints are implemented.",
        ),
        _check(
            "background_work_plane",
            "Background work runner",
            "unavailable",
            "A managed background work runner is not implemented in the live runtime yet.",
            "Corpus rebuilds, async exports, notification fanout, and scheduled quality work still need a durable runner and job registry.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence="No Databricks Job-backed runner or durable job registry is configured in the current runtime.",
            remediation="Add a managed background work runner before enabling async exports, corpus rebuilds, notification fanout, or scheduled quality work.",
        ),
        _check(
            "transaction_mode",
            "Transaction eligibility",
            "degraded",
            "Portable fallback-only mutation ordering is the active mode.",
            "Multi-statement transaction eligibility has not been proven in install/setup yet; idempotent fallback remains the truthful default.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence="Install/setup has not validated transaction support for the target governance tables.",
            remediation="Treat idempotent fallback ordering as the default until transaction eligibility is proven in the target workspace.",
        ),
        _check(
            "classification_recommendations",
            "Classification recommendation source eligibility",
            "unavailable",
            "Databricks classification recommendations are not enabled as a general runtime source yet.",
            "Classification detections remain a privileged, preview-governed source and are not exposed as general user-facing truth.",
            observed_at=observed_at,
            stale_after=stale_after,
            category="capability",
            evidence="Databricks classification results are preview/admin-governed, may include sampled evidence, and require serverless and permission prerequisites.",
            remediation="Keep classification ingestion operator-only until redaction, permission checks, and recommendation acceptance flows are implemented.",
        ),
    ]

    sequence = [
        _sequence_step(
            1,
            "environment_config",
            "Environment configuration",
            "available"
            if warehouse_id and gov_catalog and gov_schema
            else "unavailable",
            "Required deployment settings are present."
            if warehouse_id and gov_catalog and gov_schema
            else "Deployment settings are incomplete.",
            "This step can be re-run safely because it only inspects injected config.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=(
                f"warehouse={warehouse_id or 'missing'}, catalog={gov_catalog or 'missing'}, schema={gov_schema or 'missing'}"
            ),
            remediation="Inject the warehouse, governance catalog, and governance schema before marking the runtime ready.",
            unlocks=["runtime_probe", "store_probe"],
        ),
        _sequence_step(
            2,
            "runtime_probe",
            "Runtime probe",
            runtime_state,
            "The live metadata runtime probe has been evaluated."
            if runtime_state == "available"
            else runtime_message
            or "The live metadata runtime is not currently reachable.",
            runtime_message,
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=runtime_message
            or "Runtime health is derived from the live SQL metadata probe.",
            remediation=""
            if runtime_state == "available"
            else "Verify the configured warehouse is running and that the app can execute Unity Catalog metadata queries.",
            prerequisites=["environment_config"],
            unlocks=[
                "system_inventory",
                "table_lineage_surface",
                "query_history_surface",
            ],
        ),
        _sequence_step(
            3,
            "store_probe",
            "Governance store probe",
            store_state,
            "The governance control-plane probe has been evaluated."
            if store_state == "available"
            else store_message
            or "The governance control-plane store is degraded or unavailable.",
            store_message,
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=store_message
            or "Governance store reachability is derived from the control-plane probe.",
            remediation=""
            if store_state == "available"
            else "Verify the governance catalog/schema exists and that the app principal can reach the control-plane tables.",
            prerequisites=["environment_config"],
            unlocks=[
                "classification_recommendations",
                "background_work_plane",
                "transaction_fallback_mode",
            ],
        ),
        _sequence_step(
            4,
            "app_service_principal_probe",
            "App service-principal probe",
            app_service_principal_state,
            "The app service principal can reach the warehouse and governance store."
            if app_service_principal_state == "available"
            else "The app service-principal reachability and permissions have not been proven yet.",
            ""
            if app_service_principal_state == "available"
            else app_service_principal_probe["detail"],
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=app_service_principal_evidence,
            remediation=""
            if app_service_principal_state == "available"
            else "Grant the app service principal access to the warehouse and governance catalog/schema, then rerun install/setup.",
            prerequisites=["environment_config", "runtime_probe", "store_probe"],
            unlocks=["identity_probe"],
        ),
        _sequence_step(
            5,
            "identity_probe",
            "Identity and authorization probe",
            "available" if authenticated else "degraded",
            "A forwarded Databricks user identity is present."
            if authenticated
            else "No forwarded Databricks user identity was detected; the app is in read-only mode.",
            ""
            if authenticated
            else "Governance writes require a forwarded user identity header.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence=(
                "A forwarded Databricks user identity header is present."
                if authenticated
                else "No forwarded Databricks user identity header was available on the request."
            ),
            remediation=""
            if authenticated
            else "Use a Databricks App session with forwarded user identity before enabling write-capable governance actions.",
            prerequisites=["environment_config"],
            unlocks=["per_user_authorization"],
        ),
        _sequence_step(
            6,
            "capability_inventory",
            "Capability inventory",
            _worst_state(
                _flag_state(capabilities.get("systemInventoryRead")),
                _flag_state(capabilities.get("tableLineage")),
                _flag_state(capabilities.get("workloadVisibility")),
                _flag_state(capabilities.get("exportAllowed")),
            ),
            "Workspace capability inventory has been evaluated.",
            "Capability gates remain read-only and truthful.",
            observed_at=observed_at,
            stale_after=stale_after,
            category="capability",
            evidence="Capability truth is sourced from the runtime probes and is not inferred from empty payloads.",
            remediation="Keep capability-gated surfaces hidden or explicitly degraded until the workspace probes prove them available.",
            prerequisites=[
                "runtime_probe",
                "store_probe",
                "app_service_principal_probe",
                "identity_probe",
            ],
        ),
        _sequence_step(
            7,
            "rollout_controls",
            "Rollout controls",
            "available" if diagnostics_enabled else "unavailable",
            "Workspace setup diagnostics rollout control is available."
            if diagnostics_enabled
            else "Workspace setup diagnostics rollout control is disabled.",
            "The setup surface can be reopened without mutating any backend state.",
            observed_at=observed_at,
            stale_after=stale_after,
            evidence="Rollout control truth is sourced from the runtime configuration only.",
            remediation=""
            if diagnostics_enabled
            else "Enable diagnostics in runtime configuration if the operator surface should be available.",
            prerequisites=["environment_config"],
            unlocks=["workspace_setup_diagnostics"],
        ),
    ]

    counts = {"available": 0, "degraded": 0, "unavailable": 0, "unknown": 0}
    for item in checks:
        state = _normalize_state(item.get("state"), "unknown")
        counts[state] = counts.get(state, 0) + 1

    check_map = {item["key"]: item for item in checks}
    can_use_discovery = check_map.get("system_inventory", {}).get("state") in {
        "available",
        "degraded",
    }
    can_use_entity_metadata = can_use_discovery
    can_write_governance = all(
        check_map.get(key, {}).get("state") == "available"
        for key in [
            "identity_forwarding",
            "governance_config",
            "warehouse_runtime",
            "governance_store",
            "app_service_principal",
        ]
    )
    can_use_asset_preview = (
        auth_mode == capability_service.OBO_AVAILABLE_MODE
        and check_map.get("system_inventory", {}).get("state")
        in {"available", "degraded"}
    )
    # Lineage reads come from system.access.table_lineage / column_lineage and succeed for
    # the app principal when it has been granted SELECT. OBO narrows the view to the acting
    # user, but its absence does not hide the surface — workspace-scoped lineage is still
    # truthful, it is just labeled as app-principal visibility in the capability payload.
    can_use_lineage = check_map.get("table_lineage", {}).get("state") == "available"
    can_use_query_history = (
        auth_mode == capability_service.OBO_AVAILABLE_MODE
        and check_map.get("workload_visibility", {}).get("state") == "available"
    )
    can_export = (
        auth_mode == capability_service.OBO_AVAILABLE_MODE
        and check_map.get("export_delivery", {}).get("state") == "available"
        and check_map.get("identity_forwarding", {}).get("state") == "available"
    )
    can_run_background_work = (
        check_map.get("background_work_plane", {}).get("state") == "available"
    )
    can_use_classification_recommendations = (
        check_map.get("classification_recommendations", {}).get("state") == "available"
    )
    blocked_surfaces: list[str] = []
    if not can_use_discovery:
        blocked_surfaces.append("Discovery and entity inventory")
    if not can_write_governance:
        blocked_surfaces.append("Governance writes")
    if not can_use_asset_preview:
        blocked_surfaces.append("Asset preview and sample data")
    if not can_use_lineage:
        blocked_surfaces.append("Lineage graph and drawer")
    if not can_use_query_history:
        blocked_surfaces.append("Queries, usage, and workloads")
    if not can_export:
        blocked_surfaces.append("Discovery and detail export")
    if not can_run_background_work:
        blocked_surfaces.append("Background work runner")
    if not can_use_classification_recommendations:
        blocked_surfaces.append("Classification recommendations")
    hard_block_keys = [
        key
        for key in ["governance_config", "warehouse_runtime", "app_service_principal"]
        if check_map.get(key, {}).get("state") == "unavailable"
    ]
    attention_keys = [
        item["key"]
        for item in checks
        if item["state"] in {"degraded", "unavailable", "unknown"}
        and item["key"] not in hard_block_keys
    ]
    # These checks are expected to remain unavailable whenever Databricks per-user
    # authorization / OBO is not wired into the app. They reflect an honest product-mode
    # restriction, not a workspace fault, and must not keep the readiness banner in
    # `attention_required` forever. They stay visible in the detailed check list and in
    # `attentionBy` so operators can see why actor-scoped surfaces are narrowed, but they
    # do not drive the top-line readiness state.
    obo_deferred_keys = {
        "per_user_authorization",
        "table_lineage",
        "column_lineage",
        "workload_visibility",
        "export_delivery",
        "identity_forwarding",
    }
    operational_attention_keys = [
        key for key in attention_keys if key not in obo_deferred_keys
    ]
    readiness_state = (
        "blocked"
        if hard_block_keys
        else "attention_required"
        if operational_attention_keys
        else "ready"
    )
    claim_narrowing = []
    for key, surface, effect in [
        (
            "system_inventory",
            "Discovery and entity inventory",
            "Discovery and entity inventory surfaces must stay degraded or unavailable instead of implying empty truth.",
        ),
        (
            "per_user_authorization",
            "Workspace-scoped metadata reads",
            "Workspace-scoped app-principal inventory must stay explicitly restricted until actor-scoped OBO exists.",
        ),
        (
            "table_lineage",
            "Lineage surface",
            "Lineage affordances stay hidden or explicitly unavailable until Unity Catalog lineage is available for the actor.",
        ),
        (
            "workload_visibility",
            "Queries, usage, and workloads",
            "Operational query and workload tabs stay hidden or explicitly unavailable until a validated non-admin sharing path exists, instead of showing empty history.",
        ),
        (
            "export_delivery",
            "Discovery and detail export",
            "Export remains disabled until authenticated delivery, redaction, and audit guarantees are implemented.",
        ),
        (
            "per_user_authorization",
            "Actor-scoped protected reads",
            "Protected reads remain conservative until per-user authorization / OBO is implemented and verified.",
        ),
        (
            "app_service_principal",
            "App service-principal reachability and permissions",
            "App-principal reachability remains unresolved until the workspace proves the app's own warehouse and governance-store access.",
        ),
        (
            "classification_recommendations",
            "Classification recommendations",
            "Recommendation evidence stays operator-only or unavailable until privileged ingestion and redaction exist.",
        ),
        (
            "background_work_plane",
            "Background work runner",
            "Async exports, corpus rebuilds, notification fanout, and scheduled quality work remain out of scope until a background work plane exists.",
        ),
    ]:
        item = check_map.get(key)
        if item and item.get("state") != "available":
            claim_narrowing.append(_claim_item(item, surface=surface, effect=effect))

    workspace_access_gates = [
        {
            **_workspace_access_gate(
                check_map["system_inventory"],
                blocked_surfaces=[]
                if can_use_discovery
                else ["Discovery and entity inventory"],
            ),
            "key": "discovery_inventory",
            "label": "Discovery and entity inventory",
        },
        {
            "key": "governance_writes",
            "label": "Governance writes",
            "state": "available"
            if can_write_governance
            else _worst_state(
                check_map["identity_forwarding"]["state"],
                check_map["governance_config"]["state"],
                check_map["warehouse_runtime"]["state"],
                check_map["governance_store"]["state"],
                check_map["app_service_principal"]["state"],
            ),
            "reason": (
                "Governance writes are available."
                if can_write_governance
                else "Governance writes remain blocked until identity forwarding, warehouse runtime, governance config, governance store access, and app service-principal reachability are all proven."
            ),
            "proofSource": "; ".join(
                [
                    f"{key}={str(check_map[key].get('state') or 'unknown')}"
                    for key in [
                        "identity_forwarding",
                        "governance_config",
                        "warehouse_runtime",
                        "governance_store",
                        "app_service_principal",
                    ]
                ]
            ),
            "remediation": (
                ""
                if can_write_governance
                else "Restore the missing identity, config, runtime, store, or app-principal dependency before enabling governance writes."
            ),
            "blockedSurfaces": [] if can_write_governance else ["Governance writes"],
        },
        {
            **_workspace_access_gate(
                check_map["system_inventory"],
                blocked_surfaces=[]
                if can_use_asset_preview
                else ["Asset preview and sample data"],
            ),
            "key": "asset_preview",
            "label": "Asset preview and sample data",
            "state": (
                "available"
                if can_use_asset_preview
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else _normalize_state(check_map["system_inventory"]["state"])
            ),
            "reason": (
                "Actor-scoped preview and sample data are available."
                if can_use_asset_preview
                else "Asset preview and sample data require per-user authorization / OBO; app-principal fallback does not widen user-visible data."
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else str(
                    check_map["system_inventory"].get("summary")
                    or check_map["system_inventory"].get("detail")
                    or ""
                )
            ),
            "remediation": (
                ""
                if can_use_asset_preview
                else "Enable and verify Databricks Apps per-user authorization before enabling actor-scoped asset preview and sample data."
            ),
        },
        {
            **_workspace_access_gate(
                check_map["table_lineage"],
                blocked_surfaces=[]
                if can_use_lineage
                else ["Lineage graph and drawer"],
            ),
            "state": (
                "available"
                if can_use_lineage
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else _normalize_state(check_map["table_lineage"]["state"])
            ),
            "reason": (
                "Actor-scoped table lineage is available."
                if can_use_lineage
                else "Lineage requires per-user authorization / OBO; app-principal fallback does not widen user-visible data."
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else str(
                    check_map["table_lineage"].get("summary")
                    or check_map["table_lineage"].get("detail")
                    or ""
                )
            ),
            "remediation": (
                ""
                if can_use_lineage
                else "Enable and verify Databricks Apps per-user authorization before enabling actor-scoped lineage."
            ),
        },
        {
            **_workspace_access_gate(
                check_map["workload_visibility"],
                blocked_surfaces=[]
                if can_use_query_history
                else ["Queries, usage, and workloads"],
            ),
            "state": (
                "available"
                if can_use_query_history
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else _normalize_state(check_map["workload_visibility"]["state"])
            ),
            "reason": (
                "Actor-scoped workload visibility is available."
                if can_use_query_history
                else "Queries, usage, and workloads require per-user authorization / OBO or a validated safe-sharing path; app-principal fallback does not widen user-visible data."
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else str(
                    check_map["workload_visibility"].get("summary")
                    or check_map["workload_visibility"].get("detail")
                    or ""
                )
            ),
            "remediation": (
                ""
                if can_use_query_history
                else "Enable OBO or a validated safe-sharing path before exposing query history and workload surfaces."
            ),
            "safeSharingPath": _safe_operational_sharing_path(),
        },
        {
            **_workspace_access_gate(
                check_map["export_delivery"],
                blocked_surfaces=[] if can_export else ["Discovery and detail export"],
            ),
            "state": (
                "available"
                if can_export
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else _normalize_state(
                    _worst_state(
                        check_map["export_delivery"]["state"],
                        check_map["identity_forwarding"]["state"],
                    )
                )
            ),
            "reason": (
                "Authenticated export delivery is available for the current actor."
                if can_export
                else "Discovery and detail export require per-user authorization / OBO plus authenticated delivery; app-principal fallback does not widen user-visible data."
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else str(
                    check_map["export_delivery"].get("summary")
                    or check_map["export_delivery"].get("detail")
                    or ""
                )
            ),
            "remediation": (
                ""
                if can_export
                else "Enable per-user authorization and validated export delivery before exposing export actions."
            ),
        },
        _workspace_access_gate(
            check_map["background_work_plane"],
            blocked_surfaces=[]
            if can_run_background_work
            else ["Background work runner"],
        ),
        _workspace_access_gate(
            check_map["classification_recommendations"],
            blocked_surfaces=[]
            if can_use_classification_recommendations
            else ["Classification recommendations"],
        ),
        _workspace_access_gate(
            check_map["transaction_mode"],
            blocked_surfaces=[],
        ),
    ]

    surface_policies = [
        _surface_policy(
            key="discovery",
            label="Discovery browse and search",
            allowed=can_use_discovery,
            state="available"
            if can_use_discovery
            else check_map["system_inventory"]["state"],
            mode=auth_mode,
            visibility_scope=read_visibility_scope,
            reason=(
                "Actor-scoped discovery is available."
                if auth_mode == capability_service.OBO_AVAILABLE_MODE
                and can_use_discovery
                else "Discovery is restricted to workspace-scoped app-principal inventory until per-user authorization / OBO exists."
                if auth_mode == capability_service.APP_PRINCIPAL_ONLY_MODE
                and can_use_discovery
                else "Discovery is degraded read-only inventory until actor identity and per-user authorization exist."
                if auth_mode == capability_service.NO_IDENTITY_MODE
                and can_use_discovery
                else check_map["system_inventory"]["summary"]
            ),
            blocked_surfaces=[]
            if can_use_discovery
            else ["Discovery and entity inventory"],
        ),
        _surface_policy(
            key="entity_metadata",
            label="Entity summary and metadata record",
            allowed=can_use_entity_metadata,
            state="available"
            if can_use_entity_metadata
            else check_map["system_inventory"]["state"],
            mode=auth_mode,
            visibility_scope=read_visibility_scope,
            reason=(
                "Entity metadata is actor-scoped."
                if auth_mode == capability_service.OBO_AVAILABLE_MODE
                and can_use_entity_metadata
                else "Entity metadata remains workspace-scoped and read-only until per-user authorization / OBO exists."
                if can_use_entity_metadata
                else check_map["system_inventory"]["summary"]
            ),
            blocked_surfaces=[]
            if can_use_entity_metadata
            else ["Discovery and entity inventory"],
        ),
        _surface_policy(
            key="asset_preview",
            label="Asset preview and sample data",
            allowed=can_use_asset_preview,
            state="available" if can_use_asset_preview else "unavailable",
            mode=auth_mode,
            visibility_scope=capability_service.ACTOR_SCOPED_VISIBILITY
            if can_use_asset_preview
            else "",
            reason=(
                "Sample rows and preview details are actor-scoped."
                if can_use_asset_preview
                else "Asset preview and sample data stay disabled until Databricks per-user authorization / OBO is real."
            ),
            blocked_surfaces=[]
            if can_use_asset_preview
            else ["Asset preview and sample data"],
        ),
        _surface_policy(
            key="lineage",
            label="Lineage graph and drawer",
            allowed=can_use_lineage,
            state=(
                "available"
                if can_use_lineage
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else check_map["table_lineage"]["state"]
            ),
            mode=auth_mode,
            visibility_scope=capability_service.ACTOR_SCOPED_VISIBILITY
            if can_use_lineage
            else "",
            reason=(
                "Lineage is actor-scoped."
                if can_use_lineage
                else "Lineage stays degraded until actor-scoped authorization / OBO is available."
            ),
            blocked_surfaces=[] if can_use_lineage else ["Lineage graph and drawer"],
        ),
        _surface_policy(
            key="query_history",
            label="Queries, usage, and workloads",
            allowed=can_use_query_history,
            state=(
                "available"
                if can_use_query_history
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else check_map["workload_visibility"]["state"]
            ),
            mode=auth_mode,
            visibility_scope=capability_service.ACTOR_SCOPED_VISIBILITY
            if can_use_query_history
            else "",
            reason=(
                "Operational query history is available."
                if can_use_query_history
                else "Query and workload visibility stays disabled until both OBO and a validated safe-sharing path exist."
            ),
            blocked_surfaces=[]
            if can_use_query_history
            else ["Queries, usage, and workloads"],
        ),
        _surface_policy(
            key="export",
            label="Discovery and detail export",
            allowed=can_export,
            state=(
                "available"
                if can_export
                else "unavailable"
                if auth_mode != capability_service.OBO_AVAILABLE_MODE
                else check_map["export_delivery"]["state"]
            ),
            mode=auth_mode,
            visibility_scope=capability_service.ACTOR_SCOPED_VISIBILITY
            if can_export
            else "",
            reason=(
                "Export is actor-scoped and authenticated."
                if can_export
                else "Export remains disabled until actor-scoped authorization, delivery, redaction, and audit guarantees exist."
            ),
            blocked_surfaces=[] if can_export else ["Discovery and detail export"],
        ),
        _surface_policy(
            key="governance_writes",
            label="Governance writes",
            allowed=can_write_governance,
            state="available"
            if can_write_governance
            else _worst_state(
                check_map["identity_forwarding"]["state"],
                check_map["governance_config"]["state"],
                check_map["warehouse_runtime"]["state"],
                check_map["governance_store"]["state"],
                check_map["app_service_principal"]["state"],
            ),
            mode=auth_mode,
            visibility_scope=capability_service.CONTROL_PLANE_VISIBILITY
            if can_write_governance
            else "",
            reason=(
                "Governance writes are limited to the app-owned control plane for the current actor and workspace."
                if can_write_governance
                else "Governance writes remain blocked until identity, runtime, store, config, and app-principal proof all succeed."
            ),
            blocked_surfaces=[] if can_write_governance else ["Governance writes"],
        ),
    ]

    feature_flags = feature_flag_inventory(
        diagnostics_enabled=diagnostics_enabled,
        capabilities=capabilities,
    )

    return {
        "observedAt": observed_at,
        "staleAfter": stale_after,
        "summary": {
            "availableCount": counts["available"],
            "degradedCount": counts["degraded"],
            "unavailableCount": counts["unavailable"],
            "unknownCount": counts["unknown"],
            "ready": counts["unavailable"] == 0
            and counts["degraded"] == 0
            and counts["unknown"] == 0,
        },
        "readiness": {
            "state": readiness_state,
            "canRerun": True,
            "blockedBy": hard_block_keys,
            "attentionBy": attention_keys,
            "claimNarrowing": claim_narrowing,
            "retriable": True,
            "nextStep": (hard_block_keys or operational_attention_keys or ["complete"])[
                0
            ],
        },
        "setupSequence": sequence,
        "checks": checks,
        "auth": {
            "mode": auth_mode,
            "actorRole": role,
            "visibilityScope": read_visibility_scope,
            "modeSummary": (
                "Actor-scoped Databricks authorization is available."
                if auth_mode == capability_service.OBO_AVAILABLE_MODE
                else "Workspace-scoped app-principal metadata is active."
                if auth_mode == capability_service.APP_PRINCIPAL_ONLY_MODE
                else "No forwarded actor identity is present; the runtime is degraded read-only."
            ),
            "perUserAuthorization": (
                {
                    "implemented": True,
                    "state": "available",
                    "reason": "Databricks per-user authorization / OBO token was forwarded on this request.",
                }
                if per_user_authorization
                else {
                    "implemented": False,
                    "state": "unavailable",
                    "reason": "No forwarded Databricks per-user authorization / OBO token on this request; reads fall back to the app-principal scope.",
                }
            ),
        },
        "workspaceAccess": {
            "mode": auth_mode,
            "visibilityScope": read_visibility_scope,
            "transactionMode": {
                "state": check_map["transaction_mode"]["state"],
                "summary": check_map["transaction_mode"]["summary"],
                "reason": check_map["transaction_mode"].get("detail", ""),
            },
            "canUseDiscovery": can_use_discovery,
            "canUseEntityMetadata": can_use_entity_metadata,
            "canWriteGovernance": can_write_governance,
            "canUseAssetPreview": can_use_asset_preview,
            "canUseLineage": can_use_lineage,
            "canUseQueryHistory": can_use_query_history,
            "queryHistorySharingPath": _safe_operational_sharing_path(),
            "canExport": can_export,
            "canRunBackgroundWork": can_run_background_work,
            "canUseClassificationRecommendations": can_use_classification_recommendations,
            "blockedSurfaces": blocked_surfaces,
            "gates": workspace_access_gates,
            "surfacePolicies": surface_policies,
            "observedAt": observed_at,
            "staleAfter": stale_after,
        },
        "featureFlags": feature_flags,
    }
