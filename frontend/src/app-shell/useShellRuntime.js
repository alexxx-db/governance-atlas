/*
 * app-shell/useShellRuntime.js — the shell's single data spine (Wave B1).
 *
 * Ports the bootstrap/runtime-status merging that used to live inline in the
 * 1,172-line App.jsx (identity overlay, capability merge, effective boot
 * state, seed-asset derivation, Axiom AI availability, diagnostics gating)
 * into one hook consumed by AppShell and exposed to surfaces via
 * ShellContext. What deliberately did NOT survive the port:
 *
 *   - the lifted `liveDiscoveryState` / `liveGovernanceState` buses (surfaces
 *     own their queries now — FRONTEND_BLUEPRINT §8 kill table),
 *   - the 8s/24s navigation-pending state machine (its indicator UI was
 *     already dead: AppFrame never rendered `navigationState`),
 *   - the inline inbox-badge computation (replaced by hooks/useInboxWork).
 */

import { useCallback, useMemo } from "react";

import { useBootstrap } from "../hooks/useBootstrap";
import { useRuntimeStatus } from "../hooks/useRuntimeStatus";
import {
  diagnosticsRecoveryAvailable,
  diagnosticsSurfaceAvailable,
} from "../lib/capabilities";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";

function seedAssetHasNonAuthoritativeEvidence(asset) {
  return isNonAuthoritativeMockEvidence(asset, asset?.meta, asset?.provenance, asset?.warnings);
}

// De-duplicated, authoritative-only merge of seed asset groups (moved from
// App.jsx:51-61 — the mergeAssetGroups helper surfaces still consume via
// contextSeedAssets).
function mergeAssetGroups(...groups) {
  const merged = [];
  const seen = new Set();
  groups.flat().forEach((asset) => {
    if (seedAssetHasNonAuthoritativeEvidence(asset)) return;
    if (!asset?.fqn || seen.has(asset.fqn)) return;
    seen.add(asset.fqn);
    merged.push(asset);
  });
  return merged;
}

// The /api/bootstrap contract still speaks the legacy surface vocabulary
// (entity/governance/taxonomy/audit). Translate the new surface ids so the
// backend request is byte-identical to the pre-rewrite shell's.
const BOOTSTRAP_SURFACE_IDS = {
  assets: "entity",
  stewardship: "governance",
  glossary: "taxonomy",
  evidence: "audit",
};

export function useShellRuntime({ surface = "home", assetFqn = "" } = {}) {
  const {
    loading,
    error,
    refreshError,
    data,
    refresh: refreshBootstrap,
  } = useBootstrap({
    surface: BOOTSTRAP_SURFACE_IDS[surface] || surface || "home",
    asset: assetFqn,
  });

  const runtimeStatus = useRuntimeStatus({
    enabled: Boolean(error) || Boolean(refreshError) || Boolean(data),
    // Poll while the warehouse is still warming; the interval policy itself
    // lives inside useRuntimeStatus (refetchInterval never leaves hooks/).
    pollWhileWarming: true,
  });
  const runtimeStatusRefresh = runtimeStatus.refresh;

  const resolvedIdentity = runtimeStatus.data?.identity || data?.identity || {};
  const runtimeStatusLoading = runtimeStatus.data?.runtime?.state === "loading";
  const runtimeCapabilitiesLive =
    runtimeStatus.data?.runtime?.state && !runtimeStatusLoading
      ? runtimeStatus.data?.capabilities || null
      : null;
  const runtimeFeatureFlagsLive =
    runtimeStatus.data?.runtime?.state && !runtimeStatusLoading
      ? runtimeStatus.data?.featureFlags ||
        runtimeStatus.data?.diagnostics?.featureFlags ||
        null
      : null;

  // Live runtime capabilities win over the bootstrap snapshot (CLAUDE.md:
  // trust the live API over bootstrap pessimism).
  const bootstrap = useMemo(() => {
    if (!data) return data;
    if (!runtimeCapabilitiesLive && !runtimeFeatureFlagsLive) return data;
    return {
      ...data,
      capabilities: runtimeCapabilitiesLive
        ? { ...(data.capabilities || {}), ...runtimeCapabilitiesLive }
        : data.capabilities,
      featureFlags: runtimeFeatureFlagsLive || data.featureFlags,
    };
  }, [data, runtimeCapabilitiesLive, runtimeFeatureFlagsLive]);

  const shell = useMemo(() => {
    const seededShell = data?.shell || {};
    return {
      ...seededShell,
      role: resolvedIdentity.actorRole || seededShell.role || "",
      roleProvisional:
        typeof resolvedIdentity.actorRoleProvisional === "boolean"
          ? resolvedIdentity.actorRoleProvisional
          : Boolean(seededShell.roleProvisional),
      userEmail:
        resolvedIdentity.actorEmail || seededShell.userEmail || data?.identity?.actorEmail || "",
      userName:
        resolvedIdentity.actorName || seededShell.userName || data?.identity?.actorName || "",
    };
  }, [data?.identity?.actorEmail, data?.identity?.actorName, data?.shell, resolvedIdentity.actorEmail, resolvedIdentity.actorName, resolvedIdentity.actorRole, resolvedIdentity.actorRoleProvisional]);

  const diagnosticsSource = runtimeStatus.data?.diagnostics
    ? { ...(data || {}), shell, diagnostics: runtimeStatus.data.diagnostics, identity: resolvedIdentity }
    : data
      ? { ...data, shell, identity: resolvedIdentity }
      : data;

  const runtimeFeatureFlags =
    (!runtimeStatusLoading ? runtimeStatus.data?.diagnostics?.featureFlags : null) ||
    diagnosticsSource?.featureFlags ||
    diagnosticsSource?.diagnostics?.featureFlags ||
    [];
  const workspaceAccess = diagnosticsSource?.diagnostics?.workspaceAccess || null;
  // While the runtime probe is warming, per-surface access gating stays
  // unknown (null) instead of pessimistic-stale.
  const surfaceWorkspaceAccess = runtimeStatusLoading ? null : workspaceAccess;

  const diagnosticsAvailable = diagnosticsSurfaceAvailable(diagnosticsSource);
  const diagnosticsRecovery = diagnosticsRecoveryAvailable(runtimeStatus.data || diagnosticsSource);
  const setupReadiness =
    diagnosticsSource?.diagnostics?.setupReadiness ||
    diagnosticsSource?.diagnostics?.readiness ||
    null;

  const refreshDiagnostics = useCallback(async () => {
    await Promise.allSettled([refreshBootstrap?.(), runtimeStatusRefresh?.()]);
  }, [refreshBootstrap, runtimeStatusRefresh]);

  /* ---- boot state ---- */

  const bootstrapReady = Boolean(data);
  const bootstrapPending = loading && !data;
  const bootState = bootstrapReady ? data.bootState || "live" : bootstrapPending ? "loading" : "error";
  const bootstrapTruthEnvelope = data
    ? {
        bootState: data.bootState,
        state: data.state,
        status: data.status,
        source: data.source,
        meta: data.meta,
        bootstrapContract: data.bootstrapContract,
        discovery: data.discovery,
        assets: data.assets,
        assetsCount: data.assetsCount,
      }
    : null;
  const bootstrapNonAuthoritative = isNonAuthoritativeMockEvidence(bootState, bootstrapTruthEnvelope);

  const rawBootstrapAssets = useMemo(() => data?.assets || [], [data?.assets]);
  const bootstrapAssets = useMemo(
    () => (bootstrapNonAuthoritative ? [] : rawBootstrapAssets),
    [bootstrapNonAuthoritative, rawBootstrapAssets],
  );

  // Seed groups. The old live-discovery overlay (baseline/current assets fed
  // back from DiscoveryWorkspace through App) is gone with the state bus; the
  // bootstrap inventory is the one seed source, which is what these groups
  // degraded to on every fresh page load anyway.
  const contextSeedAssets = useMemo(() => mergeAssetGroups(bootstrapAssets), [bootstrapAssets]);
  const visibleAssetSet = useMemo(
    () => new Set(contextSeedAssets.map((asset) => asset.fqn)),
    [contextSeedAssets],
  );

  const bootMessage = bootstrapReady ? data.bootMessage || "" : refreshError || error || "";
  const bootstrapRefreshFailed = Boolean(refreshError);
  const hasRenderableCatalogSeed = contextSeedAssets.length > 0;
  const effectiveBootState =
    bootState === "loading"
      ? "loading"
      : bootState === "unavailable" || bootState === "error"
        ? bootState
        : bootstrapNonAuthoritative
          ? "unavailable"
          : bootstrapRefreshFailed || bootState === "degraded"
            ? "degraded"
            : "live";
  const effectiveBootMessage =
    effectiveBootState === "live" && hasRenderableCatalogSeed ? "" : refreshError || bootMessage;

  /* ---- Axiom AI availability (honest gate: shell must report a configured
     evidence-backed endpoint; never fabricate availability) ---- */

  const axiomAiAvailableStates = new Set(["available", "ready", "enabled", "configured", "live"]);
  const axiomAiProviderState = String(shell?.ai?.state || "").trim().toLowerCase();
  const axiomAiProviderName = String(shell?.ai?.provider || "").trim().toLowerCase();
  const axiomAiProviderAuthoritative = !isNonAuthoritativeMockEvidence(shell?.ai, axiomAiProviderName);
  const axiomAiAvailable =
    effectiveBootState === "live" &&
    axiomAiProviderAuthoritative &&
    axiomAiAvailableStates.has(axiomAiProviderState);
  const axiomAiUnavailableReason =
    (typeof shell?.ai?.message === "string" && shell.ai.message.trim()) ||
    (effectiveBootState !== "live"
      ? "Axiom AI is waiting for the live metadata runtime before it can answer questions."
      : "Axiom AI requires a configured evidence-backed endpoint before it can answer questions.");

  /* ---- shell chrome state ---- */

  const shellDisabled =
    (effectiveBootState === "unavailable" || effectiveBootState === "error") &&
    !hasRenderableCatalogSeed;
  const shellDisabledReason = shellDisabled
    ? effectiveBootMessage ||
      (effectiveBootState === "error"
        ? "The live catalog failed to load. Complete workspace setup or retry to re-enable navigation."
        : "The live catalog is not available yet. Complete workspace setup to re-enable navigation.")
    : "";

  // Gate for the governance-summary/inbox-work queries (was App.jsx's
  // shouldLoadGovernanceSummary): only once real, authoritative bootstrap
  // data exists.
  const summariesEnabled =
    !loading && !error && Boolean(data) && !isNonAuthoritativeMockEvidence(data);

  return {
    // raw bootstrap query state
    bootstrapPending,
    bootstrapReady,
    bootstrapError: error,
    bootstrapRefreshError: refreshError,
    bootstrapNonAuthoritative,
    refreshBootstrap,
    summariesEnabled,
    // merged payloads
    bootstrap,
    shell,
    // boot truth
    bootState,
    effectiveBootState,
    effectiveBootMessage,
    // seeds
    contextSeedAssets,
    visibleAssetSet,
    // capability signals
    runtimeFeatureFlags,
    workspaceAccess,
    surfaceWorkspaceAccess,
    // diagnostics
    runtimeStatus,
    diagnosticsAvailable,
    diagnosticsRecovery,
    setupReadiness,
    refreshDiagnostics,
    // Axiom AI
    axiomAiAvailable,
    axiomAiUnavailableReason,
    // chrome
    shellDisabled,
    shellDisabledReason,
  };
}

export default useShellRuntime;
