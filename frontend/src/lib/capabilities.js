import { isNonAuthoritativeMockEvidence } from "./nonAuthoritativeEvidence";

const DEFAULT_TABLE_LINEAGE_UNAVAILABLE_REASON =
  "Live table lineage is not available in this workspace right now.";
const DEFAULT_SYSTEM_INVENTORY_UNAVAILABLE_REASON =
  "Live asset details and preview rows are not available in this workspace right now.";
const DEFAULT_WORKLOAD_VISIBILITY_UNAVAILABLE_REASON =
  "Operational query and workload visibility is not available in this workspace right now.";
const DEFAULT_DIAGNOSTICS_UNAVAILABLE_REASON =
  "Workspace setup diagnostics are not available in this workspace right now.";
const OBO_AVAILABLE_MODE = "obo-available";
const APP_PRINCIPAL_ONLY_MODE = "app-principal-only";
const NO_IDENTITY_MODE = "no-identity";

function runtimeFeatureFlags(source) {
  if (Array.isArray(source)) return source;
  if (Array.isArray(source?.featureFlags)) return source.featureFlags;
  const diagnostics = source?.diagnostics || source || {};
  return Array.isArray(diagnostics?.featureFlags) ? diagnostics.featureFlags : [];
}

export function tableLineageCapability(bootstrap) {
  return bootstrap?.capabilities?.tableLineage || null;
}

export function tableLineageAvailable(bootstrap) {
  const capability = tableLineageCapability(bootstrap);
  if (!capability) return false;
  if (capability?.available === false) return false;
  return capability?.state === "available";
}

export function tableLineageReason(
  bootstrap,
  fallback = DEFAULT_TABLE_LINEAGE_UNAVAILABLE_REASON,
) {
  const capability = tableLineageCapability(bootstrap);
  return capability?.reason || fallback;
}

export function systemInventoryCapability(bootstrap) {
  return bootstrap?.capabilities?.systemInventoryRead || null;
}

export function systemInventoryAvailable(bootstrap) {
  // The backend reports "degraded" when its bootstrap-time visible-asset
  // count is 0 but the runtime is otherwise live and OBO is working.
  // Per-asset detail / lineage / search requests still succeed in that
  // state — only the workspace-wide count is lagging. Treating
  // "degraded" as unavailable was hiding live data behind a misleading
  // "LIVE ROWS UNAVAILABLE" banner for admins with full access whose
  // individual asset reads were fine. We now accept any non-explicitly-
  // unavailable capability.
  const capability = systemInventoryCapability(bootstrap);
  if (!capability) return false;
  if (isNonAuthoritativeMockEvidence(capability)) return false;
  if (capability?.available === false) return false;
  const state = String(capability?.state || "").trim().toLowerCase();
  if (state === "unavailable" || state === "unknown") return false;
  return capability?.available === true || state === "available" || state === "degraded";
}

export function systemInventoryReason(
  bootstrap,
  fallback = DEFAULT_SYSTEM_INVENTORY_UNAVAILABLE_REASON,
) {
  const capability = systemInventoryCapability(bootstrap);
  return capability?.reason || fallback;
}

export function emetCapability(bootstrap) {
  return bootstrap?.capabilities?.emet || null;
}

export function emetAvailable(bootstrap) {
  // Best-effort bootstrap signal (app-principal probe). The Control Center
  // surface performs the authoritative OBO detection on load, so this only
  // decorates the nav — treat "degraded" as available.
  const capability = emetCapability(bootstrap);
  if (!capability) return false;
  if (capability.available === true) return true;
  const state = String(capability.state || "").trim().toLowerCase();
  return state === "available" || state === "degraded";
}

export function emetReason(bootstrap, fallback = "") {
  const capability = emetCapability(bootstrap);
  return capability?.reason || fallback;
}

export function exportCapability(bootstrap) {
  return bootstrap?.capabilities?.exportAllowed || null;
}

export function exportAvailable(bootstrap) {
  // G2: export runs under OBO; the backend flag is available exactly when
  // per-user authorization is active (see capabilities.py exportAllowed).
  const capability = exportCapability(bootstrap);
  return capability?.available === true || capability?.state === "available";
}

export function exportReason(bootstrap, fallback = "") {
  return (
    exportCapability(bootstrap)?.reason ||
    fallback ||
    "Export runs under your Databricks identity and stays disabled until per-user authorization is active."
  );
}

export function workloadVisibilityCapability(bootstrap) {
  return bootstrap?.capabilities?.workloadVisibility || null;
}

export function workloadVisibilityAvailable(bootstrap) {
  const capability = workloadVisibilityCapability(bootstrap);
  return capability?.available === true || capability?.state === "available";
}

export function workloadVisibilityReason(
  bootstrap,
  fallback = DEFAULT_WORKLOAD_VISIBILITY_UNAVAILABLE_REASON,
) {
  const capability = workloadVisibilityCapability(bootstrap);
  return capability?.reason || fallback;
}

export function runtimeFeatureFlag(source, key) {
  const normalizedKey = String(key || "").trim();
  if (!normalizedKey) return null;
  return (
    runtimeFeatureFlags(source).find((flag) => String(flag?.key || "").trim() === normalizedKey) || null
  );
}

export function runtimeFeatureFlagAvailable(source, key, fallback = false) {
  const flag = runtimeFeatureFlag(source, key);
  if (!flag) return fallback;
  if (flag.enabled === false) return false;
  if (flag.state) return flag.state === "available";
  return flag.enabled === true;
}

export function runtimeFeatureFlagReason(source, key, fallback = "") {
  const flag = runtimeFeatureFlag(source, key);
  return (
    flag?.unavailableReason ||
    flag?.disabledReason ||
    flag?.reason ||
    flag?.rationale ||
    flag?.rolloutPolicy ||
    flag?.summary ||
    flag?.description ||
    fallback
  );
}

function diagnosticsRole(source) {
  const resolvedRole =
    source?.identity?.actorRole ||
    source?.diagnostics?.auth?.actorRole ||
    "";
  if (source?.shell?.roleProvisional) {
    return resolvedRole || source?.shell?.role || "";
  }
  return (
    resolvedRole ||
    source?.shell?.role ||
    ""
  );
}

export function diagnosticsSurfaceAvailable(source, fallbackRole = diagnosticsRole(source)) {
  const role = String(fallbackRole || "").trim().toLowerCase();
  return (
    source?.shell?.diagnosticsEnabled !== false &&
    runtimeFeatureFlagAvailable(source, "workspace_setup_diagnostics") &&
    ["admin", "steward"].includes(role)
  );
}

export function diagnosticsRecoveryAvailable(source, fallbackRole = diagnosticsRole(source)) {
  const role = String(fallbackRole || "").trim().toLowerCase();
  const diagnostics = source?.diagnostics || {};
  const hasRecoveryPayload = Boolean(
    source?.runtime ||
      source?.store ||
      diagnostics?.observedAt ||
      diagnostics?.setupSummary ||
      diagnostics?.auth,
  );
  return (
    diagnostics?.diagnosticsEnabled !== false &&
    hasRecoveryPayload &&
    ["admin", "steward"].includes(role)
  );
}

export function diagnosticsSurfaceReason(
  source,
  fallback = DEFAULT_DIAGNOSTICS_UNAVAILABLE_REASON,
) {
  return runtimeFeatureFlagReason(source, "workspace_setup_diagnostics", fallback);
}

export function workspaceAccessMode(source) {
  return (
    source?.diagnostics?.workspaceAccess?.mode ||
    source?.workspaceAccess?.mode ||
    source?.diagnostics?.auth?.mode ||
    source?.identity?.authMode ||
    ""
  );
}

export function workspaceAccessVisibilityScope(source) {
  return (
    source?.diagnostics?.workspaceAccess?.visibilityScope ||
    source?.workspaceAccess?.visibilityScope ||
    source?.diagnostics?.auth?.visibilityScope ||
    source?.identity?.visibilityScope ||
    ""
  );
}

export function workspaceAccessBanner(source) {
  const mode = workspaceAccessMode(source);
  const visibilityScope = workspaceAccessVisibilityScope(source);
  if (mode === OBO_AVAILABLE_MODE) return null;
  if (mode === APP_PRINCIPAL_ONLY_MODE) {
    return {
      tone: "warn",
      title: "Workspace-scoped metadata",
      message:
        "Discovery and entity metadata are currently sourced from workspace-scoped app-principal reads. Sample rows, lineage, query history, export, and other actor-scoped protected reads stay restricted until Databricks per-user authorization / OBO is available.",
      visibilityScope,
    };
  }
  if (mode === NO_IDENTITY_MODE) {
    return {
      tone: "bad",
      title: "No actor identity",
      message:
        "No forwarded Databricks actor identity was detected. The workspace is degraded read-only and any metadata surfaced here is not actor-scoped proof.",
      visibilityScope,
    };
  }
  return null;
}

export function workspaceAccessGate(access, key) {
  if (!access || !key) return null;
  return (Array.isArray(access.gates) ? access.gates : []).find(
    (gate) => String(gate?.key || "").trim() === String(key).trim(),
  ) || null;
}

export function workspaceAccessAvailable(access, key, fallback = false) {
  if (!access) return fallback;
  const normalizedKey = String(key || "").trim();
  if (!normalizedKey) return fallback;
  if (access[normalizedKey] === false) return false;
  if (access[normalizedKey] === true) return true;
  return fallback;
}

export function workspaceAccessReason(access, key, fallback = "") {
  const gate = workspaceAccessGate(access, key);
  return gate?.reason || gate?.remediation || fallback;
}
