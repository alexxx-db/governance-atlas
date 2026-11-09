import { Badge, Button, EmptyState, SectionCard, StatusBanner } from "../components/system";
import { getRuntimeDiagnostics } from "../lib/api";
import { ShellStateCard } from "./ShellStateCard.jsx";
import {
  AttributeList,
  ReadinessList,
  SummaryTile,
  availabilityLabel,
  labelForState,
} from "./readinessPrimitives.jsx";

/*
 * app-shell/WorkspaceDiagnosticsSurface.jsx — read-only workspace setup
 * truth (readiness sequence, access gates, surface policies, capability +
 * feature inventories, client timings). Rebuilt on the system kit in
 * cohesion follow-up 3 (was components/WorkspaceDiagnosticsSurface.jsx on
 * the legacy shell primitives). It renders PRE-BOOT — inside the bootstrap-failure
 * recovery card — so it lives in app-shell/, not surfaces/.
 *
 * Every rendered value mirrors the live /api/runtime/status payload or the
 * client-side diagnostics buffer; absent signals render explicit empty
 * states, never fabricated data (CLAUDE.md).
 */

function buildReadinessSteps(status, setupSummary, setupChecks, featureFlags) {
  const primaryRolloutFlag =
    featureFlags.find((flag) => flag?.key === "workspace_setup_diagnostics") || null;
  const rolloutState = primaryRolloutFlag?.state || "unknown";
  const rolloutSummary = primaryRolloutFlag
    ? primaryRolloutFlag.summary ||
      primaryRolloutFlag.reason ||
      "Workspace setup diagnostics rollout metadata is available."
    : featureFlags.length
      ? "No workspace setup diagnostics rollout flag was returned."
      : "No feature-flag inventory has been exposed yet.";
  const rolloutDetail = primaryRolloutFlag
    ? primaryRolloutFlag.description ||
      primaryRolloutFlag.reason ||
      "The shell-owned diagnostics rollout is sourced from the named workspace diagnostics flag."
    : featureFlags.length
      ? "Feature flags were returned, but the named workspace diagnostics rollout flag is missing."
      : "No feature-flag inventory has been exposed yet.";
  return [
    {
      key: "workspace_identity",
      label: "Confirm workspace identity",
      state: status?.identity?.actorEmail && status?.config?.warehouseId ? "available" : "unknown",
      summary: [status?.identity?.actorRole || "Unknown role", status?.identity?.source || "Unknown source"]
        .filter(Boolean)
        .join(" · "),
      detail: [
        status?.identity?.actorEmail ? `Actor ${status.identity.actorEmail}` : "Actor identity is not resolved yet.",
        status?.config?.warehouseId ? `Warehouse ${status.config.warehouseId}` : "Warehouse is not configured.",
      ].join(" "),
      observedAt: status?.diagnostics?.observedAt || "",
    },
    {
      key: "authorization_plane",
      label: "Check authorization plane",
      state: status?.diagnostics?.auth?.perUserAuthorization?.state || "unknown",
      summary: status?.diagnostics?.auth?.mode || "Unknown auth mode",
      detail:
        status?.diagnostics?.auth?.perUserAuthorization?.reason ||
        "Per-user authorization status is reported by the live runtime.",
      evidence: status?.diagnostics?.auth?.perUserAuthorization?.state
        ? "Runtime auth payload"
        : "No auth check returned",
      remediation:
        status?.diagnostics?.auth?.perUserAuthorization?.state === "unavailable"
          ? "Add per-user authorization before depending on actor-scoped protected reads."
          : "",
      observedAt: status?.diagnostics?.observedAt || "",
    },
    {
      key: "runtime_health",
      label: "Inspect runtime and store health",
      state:
        status?.runtime?.state === "unavailable" || status?.store?.state === "unavailable"
          ? "unavailable"
          : status?.runtime?.state === "degraded" || status?.store?.state === "degraded"
            ? "degraded"
            : status?.runtime?.state || status?.store?.state || "unknown",
      summary: [
        status?.runtime?.state ? `Runtime ${labelForState(status.runtime.state)}` : "",
        status?.store?.state ? `Store ${labelForState(status.store.state)}` : "",
      ]
        .filter(Boolean)
        .join(" · "),
      detail:
        status?.runtime?.message ||
        status?.store?.message ||
        "Runtime and governance store health are derived from the live status payload.",
      observedAt: status?.diagnostics?.observedAt || "",
    },
    {
      key: "readiness_probes",
      label: "Review readiness probes",
      state:
        setupSummary.unavailableCount
          ? "unavailable"
          : setupSummary.degradedCount
            ? "degraded"
            : setupSummary.availableCount
              ? "available"
              : "unknown",
      summary: `${setupSummary.availableCount || 0} ready, ${setupSummary.degradedCount || 0} degraded`,
      detail: `${setupSummary.unavailableCount || 0} unavailable and ${setupSummary.unknownCount || 0} unknown readiness checks.`,
      evidence: `${setupChecks.length} runtime checks`,
      observedAt: status?.diagnostics?.observedAt || "",
      staleAfter: setupChecks[0]?.staleAfter || "",
    },
    {
      key: "rollout_controls",
      label: "Review rollout controls",
      state: rolloutState,
      summary: rolloutSummary,
      detail: rolloutDetail,
      rollout: primaryRolloutFlag?.rollout || "",
      owner: primaryRolloutFlag?.owner || "",
      scope: primaryRolloutFlag?.scope || "",
      expiresAfter: primaryRolloutFlag?.expiresAfter || "",
      removalTicket: primaryRolloutFlag?.removalTicket || "",
      rollback: primaryRolloutFlag?.rollback || "",
      observedAt: status?.diagnostics?.observedAt || "",
    },
  ];
}

export default function WorkspaceDiagnosticsSurface({
  title = "Workspace Setup & Diagnostics",
  loading = false,
  error = "",
  refreshError = "",
  refreshing = false,
  onRefresh = null,
  status = null,
}) {
  const setupSummary = status?.diagnostics?.setupSummary || {};
  const setupReadiness = status?.diagnostics?.setupReadiness || status?.diagnostics?.readiness || {};
  const setupChecks = status?.diagnostics?.setupChecks || [];
  const setupSequence =
    status?.diagnostics?.setupSequence?.length
      ? status.diagnostics.setupSequence
      : buildReadinessSteps(status, setupSummary, setupChecks, status?.diagnostics?.featureFlags || []);
  const featureFlags = status?.diagnostics?.featureFlags || [];
  const workspaceAccess = status?.diagnostics?.workspaceAccess || null;
  const workspaceAccessGates = workspaceAccess?.gates || [];
  const surfacePolicies = workspaceAccess?.surfacePolicies || [];
  const transactionCheck = setupChecks.find((item) => item?.key === "transaction_mode") || null;
  const capabilities = Object.entries(status?.capabilities || {}).map(([key, value]) => ({
    key,
    label: key
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\b\w/g, (match) => match.toUpperCase()),
    state: value?.state || "unknown",
    summary: value?.reason || "",
  }));
  const clientDiagnostics = /** @type {{
    lastRequest?: { httpRequestId?: string, clientRequestId?: string, clientDurationMs?: number } | null,
    initialNavigation?: { durationMs?: number } | null,
  } | null} */ (getRuntimeDiagnostics());
  const lastRequest = clientDiagnostics?.lastRequest || null;
  const initialNavigation = clientDiagnostics?.initialNavigation || null;
  const claimNarrowingItems = (setupReadiness.claimNarrowing || []).map((item, index) => ({
    key: item.key || `claim-${index}`,
    label: item.surface || "Claim narrowing",
    state: item.state || "unknown",
    summary: item.reason || "This surface remains narrowed until setup checks are satisfied.",
    effect: item.effect || "",
  }));

  if (loading && !status) {
    return (
      <div className="ax-shell-readiness-layout is-single">
        <ShellStateCard
          eyebrow="Workspace diagnostics"
          loading
          message="Rerunning setup checks, capability probes, and shell readiness for the current workspace."
          title="Loading workspace setup diagnostics..."
        />
      </div>
    );
  }

  if (error && !status) {
    return (
      <div className="ax-shell-readiness-layout is-single">
        <ShellStateCard
          eyebrow="Workspace diagnostics"
          message={error}
          title="Workspace setup diagnostics could not be loaded."
          tone="bad"
        />
      </div>
    );
  }

  return (
    <div className="ax-shell-readiness-layout">
      <div className="ax-shell-readiness-main">
        <SectionCard
          actions={
            <>
              {typeof onRefresh === "function" ? (
                <Button
                  disabled={refreshing || loading}
                  onClick={onRefresh}
                  size="sm"
                  title={
                    refreshing
                      ? "Refreshing workspace readiness probe — please wait."
                      : loading
                        ? "Initial readiness probe in progress — please wait."
                        : undefined
                  }
                  variant="secondary"
                >
                  {refreshing ? "Refreshing readiness..." : "Refresh readiness"}
                </Button>
              ) : null}
              {status?.diagnostics?.observedAt ? (
                <Badge tone="muted">Observed {status.diagnostics.observedAt}</Badge>
              ) : null}
            </>
          }
          subtitle="Read-only setup truth for the current workspace, actor, and live runtime."
          title={title}
        >
          {refreshError ? <StatusBanner message={refreshError} title="Refresh incomplete" tone="warning" /> : null}
          {refreshing ? (
            <StatusBanner
              message="Rerunning the runtime status probe against the current workspace."
              title="Refreshing"
              tone="info"
            />
          ) : null}
          {setupReadiness.state && setupReadiness.state !== "ready" ? (
            <StatusBanner
              message={
                setupReadiness.nextStep
                  ? `Next step: ${labelForState(setupReadiness.nextStep)}.`
                  : "The workspace still has unresolved readiness constraints."
              }
              title="Claims narrowed"
              tone="warning"
            />
          ) : null}
          <div className="ax-shell-readiness-subhead">
            <h3>Readiness sequence</h3>
            <p>Ordered setup checks that rerun against the live runtime without leaving the shell.</p>
          </div>
          <ReadinessList items={setupSequence} />
          <div className="ax-shell-readiness-tiles">
            <SummaryTile
              label="Warehouse runtime"
              note={status?.runtime?.message || "Live metadata runtime health."}
              state={status?.runtime?.state || "unknown"}
              value={labelForState(status?.runtime?.state || "unknown")}
            />
            <SummaryTile
              label="Governance store"
              note={status?.store?.message || "Control-plane reachability."}
              state={status?.store?.state || "unknown"}
              value={labelForState(status?.store?.state || "unknown")}
            />
            <SummaryTile
              label="Setup status"
              note={[
                `${setupSummary.availableCount || 0} ready`,
                `${setupSummary.degradedCount || 0} degraded`,
                `${setupSummary.unavailableCount || 0} unavailable`,
                `${setupSummary.unknownCount || 0} unknown`,
                setupReadiness.nextStep ? `Next ${labelForState(setupReadiness.nextStep)}` : "",
              ]
                .filter(Boolean)
                .join(", ")}
              state={
                setupReadiness.state === "blocked"
                  ? "unavailable"
                  : setupReadiness.state === "attention_required"
                    ? "degraded"
                    : setupReadiness.state || "unknown"
              }
              value={labelForState(setupReadiness.state || "unknown")}
            />
            <SummaryTile
              label="Auth mode"
              note={
                status?.diagnostics?.auth?.perUserAuthorization?.reason ||
                "Per-user enforcement and actor-scoped diagnostics status."
              }
              state={status?.diagnostics?.auth?.perUserAuthorization?.state || "unknown"}
              value={labelForState(status?.diagnostics?.auth?.mode || status?.identity?.authMode || "unknown")}
            />
          </div>
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{workspaceAccessGates.length} gates</Badge>}
          subtitle="Current actor and workspace access derived from live readiness checks and capability probes."
          title="Workspace access"
        >
          <AttributeList
            items={[
              { label: "Access mode", value: labelForState(workspaceAccess?.mode || status?.diagnostics?.auth?.mode || "unknown") },
              { label: "Visibility scope", value: workspaceAccess?.visibilityScope || status?.diagnostics?.auth?.visibilityScope || "Unknown" },
              { label: "Discovery", value: availabilityLabel(workspaceAccess?.canUseDiscovery) },
              { label: "Entity metadata", value: availabilityLabel(workspaceAccess?.canUseEntityMetadata) },
              { label: "Preview / sample", value: availabilityLabel(workspaceAccess?.canUseAssetPreview) },
              { label: "Governance writes", value: availabilityLabel(workspaceAccess?.canWriteGovernance) },
              { label: "Lineage", value: availabilityLabel(workspaceAccess?.canUseLineage) },
              { label: "Query history", value: availabilityLabel(workspaceAccess?.canUseQueryHistory) },
              { label: "Export", value: availabilityLabel(workspaceAccess?.canExport) },
              { label: "Background work", value: availabilityLabel(workspaceAccess?.canRunBackgroundWork) },
              {
                label: "Classification recommendations",
                value: availabilityLabel(workspaceAccess?.canUseClassificationRecommendations),
              },
              {
                label: "Mutation mode",
                value:
                  workspaceAccess?.transactionMode?.summary ||
                  transactionCheck?.summary ||
                  labelForState(transactionCheck?.state || "unknown"),
              },
            ]}
          />
          {workspaceAccess?.blockedSurfaces?.length ? (
            <div className="ax-shell-chip-row">
              {workspaceAccess.blockedSurfaces.map((surface) => (
                <Badge key={`blocked-surface:${surface}`} tone="muted">
                  {surface}
                </Badge>
              ))}
            </div>
          ) : null}
          {workspaceAccessGates.length ? (
            <ReadinessList items={workspaceAccessGates} />
          ) : (
            <EmptyState
              body="No workspace access summary was returned by the runtime yet."
              title="Workspace access summary pending"
            />
          )}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{surfacePolicies.length} policies</Badge>}
          subtitle="Product-mode contract for discovery, entity metadata, preview, lineage, query history, export, and governance writes."
          title="Surface policy matrix"
        >
          {surfacePolicies.length ? (
            <ReadinessList items={surfacePolicies} />
          ) : (
            <EmptyState
              body="No surface policy matrix was returned by the runtime yet."
              title="Surface policy pending"
            />
          )}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{claimNarrowingItems.length} narrowed</Badge>}
          subtitle="Surfaces the app must narrow or hide until the relevant readiness checks turn green."
          title="Claim discipline"
        >
          {claimNarrowingItems.length ? (
            <ReadinessList items={claimNarrowingItems} />
          ) : (
            <EmptyState
              body="No active claim narrowing is required for the current runtime payload."
              title="Claims at full breadth"
            />
          )}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{setupChecks.length} checks</Badge>}
          subtitle="Workspace readiness checks backed by the current runtime and capability probes."
          title="Setup checks"
        >
          {setupChecks.length ? (
            <ReadinessList items={setupChecks} />
          ) : (
            <EmptyState body="No setup checks were returned by the runtime yet." title="Setup checks pending" />
          )}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{capabilities.length} capabilities</Badge>}
          subtitle="Actor-scoped capability hints from the live runtime."
          title="Capability inventory"
        >
          {capabilities.length ? (
            <ReadinessList items={capabilities} />
          ) : (
            <EmptyState body="No runtime capabilities were returned." title="Capability inventory pending" />
          )}
        </SectionCard>
      </div>

      <aside className="ax-shell-readiness-side">
        <SectionCard title="Workspace context">
          <AttributeList
            items={[
              { label: "Actor", value: status?.identity?.actorEmail || "unknown" },
              { label: "Role", value: status?.identity?.actorRole || "Unknown" },
              { label: "Identity source", value: status?.identity?.source || "Unknown" },
              { label: "Warehouse", value: status?.config?.warehouseId || "Unconfigured" },
              { label: "Catalog", value: status?.config?.govCatalog || "Unconfigured" },
              { label: "Schema", value: status?.config?.govSchema || "Unconfigured" },
            ]}
          />
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{featureFlags.length} flags</Badge>}
          subtitle="Runtime feature flags exposed for shell and surface gating."
          title="Feature inventory"
        >
          {featureFlags.length ? (
            <ReadinessList items={featureFlags} />
          ) : (
            <EmptyState body="No feature-flag inventory is exposed yet." title="Feature inventory pending" />
          )}
        </SectionCard>

        <SectionCard
          subtitle="Last request and initial navigation timings captured in the browser."
          title="Client diagnostics"
        >
          <AttributeList
            items={[
              {
                label: "Last request",
                value: lastRequest?.httpRequestId || lastRequest?.clientRequestId || "No requests yet",
              },
              {
                label: "Request duration",
                value: lastRequest?.clientDurationMs ? `${lastRequest.clientDurationMs} ms` : "—",
              },
              {
                label: "Initial navigation",
                value: initialNavigation?.durationMs ? `${initialNavigation.durationMs} ms` : "—",
              },
              {
                label: "Diagnostics enabled",
                value: status?.diagnostics?.diagnosticsEnabled ? "Yes" : "No",
              },
            ]}
          />
        </SectionCard>
      </aside>
    </div>
  );
}
