import { useMemo, useState } from "react";
import { Badge, Button, EmptyState, SectionCard, StatusBanner } from "../components/system";
import { ShellStateCard } from "./ShellStateCard.jsx";
import {
  AttributeList,
  ReadinessList,
  StateBadge,
  SummaryTile,
  availabilityLabel,
  labelForState,
} from "./readinessPrimitives.jsx";
import WorkspaceDiagnosticsSurface from "./WorkspaceDiagnosticsSurface.jsx";

/*
 * app-shell/WorkspaceSetupWizard.jsx — the operator-facing workspace setup
 * guide (readiness sequence, safe operational-sharing path, claim
 * discipline, surface policies) with the full diagnostics surface behind a
 * toggle. Rebuilt on the system kit in cohesion follow-up 3 (was
 * components/WorkspaceSetupWizard.jsx on the legacy shell primitives). Lives in
 * app-shell/ because it opens from the shell's settings entry pre-surface.
 *
 * All wizard behavior is preserved: the refresh probe, the show/hide full
 * diagnostics toggle, and every backed readiness section. Values mirror the
 * live /api/runtime/status payload; absent signals render explicit empty
 * states, never fabricated data (CLAUDE.md).
 */

export default function WorkspaceSetupWizard({
  title = "Workspace setup",
  loading = false,
  error = "",
  refreshError = "",
  refreshing = false,
  onRefresh = null,
  status = null,
}) {
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const diagnostics = status?.diagnostics || {};
  const setupSummary = diagnostics.setupSummary || diagnostics.summary || {};
  const setupReadiness = diagnostics.setupReadiness || diagnostics.readiness || {};
  const setupSequence = Array.isArray(diagnostics.setupSequence) ? diagnostics.setupSequence : [];
  const claimNarrowing = Array.isArray(setupReadiness.claimNarrowing) ? setupReadiness.claimNarrowing : [];
  const workspaceAccess = diagnostics.workspaceAccess || {};
  const workspaceAccessGates = Array.isArray(workspaceAccess.gates) ? workspaceAccess.gates : [];
  const surfacePolicies = Array.isArray(workspaceAccess.surfacePolicies) ? workspaceAccess.surfacePolicies : [];
  const safeSharingPath = workspaceAccess.queryHistorySharingPath || {};
  const acceptedSharingPaths = Array.isArray(safeSharingPath.acceptedPaths)
    ? safeSharingPath.acceptedPaths
    : [];
  const workloadGate = workspaceAccessGates.find((item) => item?.key === "workload_visibility") || null;
  const blockedSurfaces = Array.isArray(workspaceAccess.blockedSurfaces) ? workspaceAccess.blockedSurfaces : [];
  const featureFlags = Array.isArray(diagnostics.featureFlags) ? diagnostics.featureFlags : [];
  const observedAt = diagnostics.observedAt || workspaceAccess.observedAt || "";
  const readyCount = Number(setupSummary.availableCount || 0);
  const degradedCount = Number(setupSummary.degradedCount || 0);
  const unavailableCount = Number(setupSummary.unavailableCount || 0);
  const unknownCount = Number(setupSummary.unknownCount || 0);
  const validatedSharingPath = String(safeSharingPath.validatedPath || "").trim();
  const sharingState = safeSharingPath.state || "unknown";
  const nextStep = setupReadiness.nextStep || "";
  const readinessNote = useMemo(() => {
    const parts = [
      `${readyCount} ready`,
      `${degradedCount} degraded`,
      `${unavailableCount} unavailable`,
      `${unknownCount} unknown`,
    ];
    if (nextStep) parts.push(`Next ${labelForState(nextStep)}`);
    return parts.join(", ");
  }, [degradedCount, nextStep, readyCount, unavailableCount, unknownCount]);

  if (loading && !status) {
    return (
      <ShellStateCard
        eyebrow="Workspace setup"
        loading
        message="Rerunning setup checks, claim narrowing, and operational-sharing validation for the current workspace."
        title="Loading workspace setup guidance..."
      />
    );
  }

  if (error && !status) {
    return (
      <ShellStateCard
        eyebrow="Workspace setup"
        message={error}
        title="Workspace setup guidance could not be loaded."
        tone="bad"
      />
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
              <Button onClick={() => setShowDiagnostics((current) => !current)} size="sm" variant="tertiary">
                {showDiagnostics ? "Hide full diagnostics" : "Show full diagnostics"}
              </Button>
            </>
          }
          eyebrow="Workspace setup"
          subtitle="Shell-owned readiness truth for the current actor, workspace, and safe operational-sharing path."
          title={title}
        >
          <div className="ax-shell-chip-row">
            <StateBadge state={setupReadiness.state || "unknown"} />
            {observedAt ? <Badge tone="muted">Observed {observedAt}</Badge> : null}
          </div>
          <p className="ax-shell-readiness-note">
            Use this guide to confirm readiness, understand claim narrowing, and verify how protected
            operational surfaces are shared before widening product claims.
          </p>
          {refreshError ? <StatusBanner message={refreshError} title="Refresh incomplete" tone="warning" /> : null}
          {refreshing ? (
            <StatusBanner
              message="Rerunning runtime setup checks and capability probes against the current workspace."
              title="Refreshing"
              tone="info"
            />
          ) : null}
          {setupReadiness.state && setupReadiness.state !== "ready" ? (
            <StatusBanner
              message={
                nextStep
                  ? `Next step: ${labelForState(nextStep)}. Claim-narrowed surfaces stay hidden or explicitly unavailable until this check improves.`
                  : "Claim-narrowed surfaces stay hidden or explicitly unavailable until readiness improves."
              }
              title="Claims narrowed"
              tone="warning"
            />
          ) : null}

          <div className="ax-shell-readiness-tiles">
            <SummaryTile
              label="Setup status"
              note={readinessNote}
              state={
                setupReadiness.state === "attention_required"
                  ? "degraded"
                  : setupReadiness.state === "blocked"
                    ? "unavailable"
                    : setupReadiness.state || "unknown"
              }
              value={labelForState(setupReadiness.state || "unknown")}
            />
            <SummaryTile
              label="Auth mode"
              note={
                diagnostics.auth?.perUserAuthorization?.reason ||
                "The live runtime decides whether actor-scoped protected reads are available."
              }
              state={diagnostics.auth?.perUserAuthorization?.state || "unknown"}
              value={labelForState(diagnostics.auth?.mode || status?.identity?.authMode || "unknown")}
            />
            <SummaryTile
              label="Operational sharing"
              note={
                validatedSharingPath
                  ? `Validated path: ${validatedSharingPath}.`
                  : "Queries, usage, and workload surfaces remain narrowed until one accepted sharing path is validated."
              }
              state={sharingState}
              value={validatedSharingPath || "Required"}
            />
            <SummaryTile
              label="Governance writes"
              note={
                workspaceAccess.canWriteGovernance
                  ? "Governed mutations are available for the current actor and workspace."
                  : "Writes remain disabled until identity, runtime, and governance-store checks are green."
              }
              state={workspaceAccess.canWriteGovernance ? "available" : "unavailable"}
              value={availabilityLabel(workspaceAccess.canWriteGovernance)}
            />
            <SummaryTile
              label="Preview / sample"
              note="Preview and sample data remain actor-scoped protected reads."
              state={workspaceAccess.canUseAssetPreview ? "available" : "unavailable"}
              value={availabilityLabel(workspaceAccess.canUseAssetPreview)}
            />
          </div>
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{setupSequence.length} steps</Badge>}
          subtitle="Ordered setup checks sourced from the live runtime. This is the shell-owned checklist for the current workspace, not a second readiness store."
          title="Readiness sequence"
        >
          {setupSequence.length ? (
            <ReadinessList items={setupSequence} />
          ) : (
            <EmptyState
              body="No ordered setup sequence was returned by the runtime yet."
              title="Readiness sequence pending"
            />
          )}
        </SectionCard>

        <SectionCard
          actions={<StateBadge state={sharingState} />}
          subtitle="Queries, usage, and workload surfaces stay narrowed until one accepted sharing path is validated."
          title="Safe operational-sharing path"
        >
          {validatedSharingPath ? (
            <StatusBanner
              message={`Validated path: ${validatedSharingPath}.`}
              title="Operational sharing verified"
              tone="success"
            />
          ) : (
            <StatusBanner
              message="No safe-sharing path is validated yet. Queries, usage, and workload surfaces must remain hidden or explicitly unavailable."
              title="Operational sharing required"
              tone="warning"
            />
          )}
          <AttributeList
            items={[
              { label: "Validated path", value: validatedSharingPath || "Not validated" },
              { label: "Query history", value: availabilityLabel(workspaceAccess.canUseQueryHistory) },
              {
                label: "Blocked surfaces",
                value: blockedSurfaces.includes("Queries, usage, and workloads")
                  ? "Queries, usage, and workloads"
                  : blockedSurfaces.length
                    ? blockedSurfaces.join(", ")
                    : "None",
              },
            ]}
          />
          {acceptedSharingPaths.length ? (
            <div className="ax-shell-chip-row">
              {acceptedSharingPaths.map((path) => (
                <Badge key={path} tone="muted">
                  {path}
                </Badge>
              ))}
            </div>
          ) : null}
          {workloadGate ? <ReadinessList items={[workloadGate]} /> : null}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{claimNarrowing.length} narrowed</Badge>}
          subtitle="Surfaces that must remain narrowed until setup checks turn green."
          title="Claim discipline"
        >
          {claimNarrowing.length ? (
            <ReadinessList items={claimNarrowing} />
          ) : (
            <EmptyState
              body="No active claim narrowing is required for the current runtime payload."
              title="Claims at full breadth"
            />
          )}
        </SectionCard>

        <SectionCard
          actions={<Badge tone="muted">{surfacePolicies.length} policies</Badge>}
          subtitle="Runtime mode mapping for discovery, entity metadata, preview, lineage, query history, export, and governance writes."
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

        {showDiagnostics ? (
          <SectionCard
            subtitle="Raw setup checks, workspace access gates, capability inventory, and client diagnostics."
            title="Full diagnostics"
          >
            <WorkspaceDiagnosticsSurface
              error={error}
              loading={loading}
              refreshError=""
              refreshing={false}
              status={status}
              title="Workspace diagnostics"
            />
          </SectionCard>
        ) : null}
      </div>

      <aside className="ax-shell-readiness-side">
        <SectionCard
          subtitle="Current actor, deployment context, and rollout scope for this setup session."
          title="Workspace context"
        >
          <div className="ax-shell-readiness-subhead">
            <h3>Identity</h3>
          </div>
          <AttributeList
            items={[
              { label: "Actor", value: status?.identity?.actorEmail || "unknown" },
              { label: "Role", value: status?.identity?.actorRole || "Unknown" },
              { label: "Identity source", value: status?.identity?.source || "Unknown" },
              { label: "Auth mode", value: diagnostics.auth?.mode || status?.identity?.authMode || "Unknown" },
              { label: "Visibility scope", value: workspaceAccess.visibilityScope || diagnostics.auth?.visibilityScope || "Unknown" },
            ]}
          />

          <div className="ax-shell-readiness-subhead">
            <h3>Configuration</h3>
          </div>
          <AttributeList
            items={[
              { label: "Warehouse", value: status?.config?.warehouseId || "Unconfigured" },
              { label: "Catalog", value: status?.config?.govCatalog || "Unconfigured" },
              { label: "Schema", value: status?.config?.govSchema || "Unconfigured" },
            ]}
          />

          <div className="ax-shell-readiness-subhead">
            <h3>Scope</h3>
          </div>
          <AttributeList
            items={[
              { label: "Lineage", value: availabilityLabel(workspaceAccess.canUseLineage) },
              { label: "Export", value: availabilityLabel(workspaceAccess.canExport) },
              { label: "Background work", value: availabilityLabel(workspaceAccess.canRunBackgroundWork) },
              {
                label: "Classification recommendations",
                value: availabilityLabel(workspaceAccess.canUseClassificationRecommendations),
              },
            ]}
          />

          <div className="ax-shell-readiness-subhead">
            <h3>Blocked surfaces</h3>
          </div>
          {blockedSurfaces.length ? (
            <div className="ax-shell-chip-row">
              {blockedSurfaces.map((surface) => (
                <Badge key={surface} tone="muted">
                  {surface}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="ax-shell-readiness-note">No blocked surfaces are reported right now.</p>
          )}

          <div className="ax-shell-readiness-subhead">
            <h3>Feature inventory</h3>
          </div>
          <p className="ax-shell-readiness-note">
            {featureFlags.length
              ? `${featureFlags.length} runtime feature flags are exposed for setup and surface gating.`
              : "No feature-flag inventory is exposed yet."}
          </p>
        </SectionCard>
      </aside>
    </div>
  );
}
