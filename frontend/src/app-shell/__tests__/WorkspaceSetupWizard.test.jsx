import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkspaceSetupWizard from "../WorkspaceSetupWizard.jsx";

const workspaceDiagnosticsSurfaceMock = vi.fn((props) => (
  <div data-testid="workspace-diagnostics-surface">{props.title || "Workspace diagnostics"}</div>
));

vi.mock("../WorkspaceDiagnosticsSurface.jsx", () => ({
  default: (props) => workspaceDiagnosticsSurfaceMock(props),
}));

function statusPayload(overrides = {}) {
  return {
    runtime: {
      state: "live",
      message: "",
    },
    store: {
      state: "live",
      message: "",
    },
    identity: {
      actorEmail: "admin@example.com",
      actorRole: "Admin",
      source: "x-forwarded-email",
    },
    config: {
      warehouseId: "warehouse-1",
      govCatalog: "main",
      govSchema: "gov",
    },
    diagnostics: {
      observedAt: "2026-04-15T12:00:00Z",
      auth: {
        mode: "forwarded-user-header",
        perUserAuthorization: {
          state: "unavailable",
          reason: "Per-user authorization is not implemented yet.",
        },
      },
      setupSummary: {
        availableCount: 4,
        degradedCount: 1,
        unavailableCount: 2,
        unknownCount: 0,
      },
      setupReadiness: {
        state: "attention_required",
        nextStep: "per_user_authorization",
        claimNarrowing: [
          {
            key: "workload_visibility",
            surface: "Queries, usage, and workloads",
            state: "unavailable",
            reason: "Operational history is not safely shared for the current actor.",
            effect: "Operational tabs stay hidden or explicitly unavailable instead of showing empty history.",
          },
        ],
      },
      setupSequence: [
        {
          key: "identity_forwarding",
          label: "Identity forwarding",
          state: "available",
          summary: "Forwarded actor identity headers are present.",
          detail: "The shell can identify the current actor.",
          observedAt: "2026-04-15T12:00:00Z",
          staleAfter: "2026-04-15T12:05:00Z",
        },
        {
          key: "per_user_authorization",
          label: "Per-user authorization",
          state: "unavailable",
          summary: "Per-user Databricks authorization / OBO is not implemented in the live runtime yet.",
          detail: "Actor-scoped protected reads remain narrowed.",
          remediation: "Implement and validate a safe operational-sharing path before widening operational claims.",
          observedAt: "2026-04-15T12:00:00Z",
          staleAfter: "2026-04-15T12:05:00Z",
        },
      ],
      workspaceAccess: {
        canWriteGovernance: true,
        canUseLineage: false,
        canUseQueryHistory: false,
        canExport: false,
        canRunBackgroundWork: false,
        canUseClassificationRecommendations: false,
        blockedSurfaces: ["Queries, usage, and workloads", "Lineage graph"],
        queryHistorySharingPath: {
          state: "unavailable",
          validatedPath: "",
          acceptedPaths: [
            "actor-scoped OBO",
            "validated dynamic-view plane",
            "warehouse CAN VIEW plus downstream visibility rules",
          ],
        },
        gates: [
          {
            key: "workload_visibility",
            label: "Workload visibility",
            state: "unavailable",
            summary: "Operational history is not safely shared for the current actor.",
            detail: "Safe sharing must be validated before operational surfaces can claim live truth.",
            remediation: "Validate one accepted sharing path or keep the operational plane disabled.",
          },
        ],
      },
      featureFlags: [
        {
          key: "workspace_setup_diagnostics",
          label: "Workspace setup diagnostics",
          state: "available",
          enabled: true,
        },
      ],
    },
    ...overrides,
  };
}

describe("WorkspaceSetupWizard (app-shell, system kit)", () => {
  beforeEach(() => {
    workspaceDiagnosticsSurfaceMock.mockClear();
  });

  it("renders a setup loading card when no status payload is available yet", () => {
    const { container } = render(<WorkspaceSetupWizard loading />);

    expect(screen.getByText("Workspace setup")).not.toBeNull();
    expect(screen.getByText("Loading workspace setup guidance...")).not.toBeNull();
    expect(container.querySelector(".ax-shell-state-card")).not.toBeNull();
    expect(container.querySelector('[class*="gh-"]')).toBeNull();
  });

  it("renders a setup error card when setup guidance cannot be loaded", () => {
    const { container } = render(<WorkspaceSetupWizard error="Runtime status request failed." />);

    expect(screen.getByText("Workspace setup")).not.toBeNull();
    expect(screen.getByText("Workspace setup guidance could not be loaded.")).not.toBeNull();
    expect(screen.getByText("Runtime status request failed.")).not.toBeNull();
    expect(container.querySelector(".ax-shell-state-card.tone-bad")).not.toBeNull();
  });

  it("renders readiness, safe sharing, claim narrowing, and advanced diagnostics from the live payload", () => {
    const onRefresh = vi.fn();

    const { container } = render(<WorkspaceSetupWizard onRefresh={onRefresh} status={statusPayload()} />);

    expect(screen.getByText("Readiness sequence")).not.toBeNull();
    expect(screen.getByText("Safe operational-sharing path")).not.toBeNull();
    expect(screen.getByText("Claim discipline")).not.toBeNull();
    expect(screen.getAllByText("Queries, usage, and workloads").length).toBeGreaterThan(0);
    expect(screen.getByText("actor-scoped OBO")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Refresh readiness" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "Show full diagnostics" })).not.toBeNull();
    expect(container.querySelector('[class*="gh-"]')).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Refresh readiness" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Show full diagnostics" }));
    expect(screen.getByTestId("workspace-diagnostics-surface")).not.toBeNull();
    expect(workspaceDiagnosticsSurfaceMock).toHaveBeenCalled();
    // The toggle flips to the hide affordance once diagnostics are shown.
    expect(screen.getByRole("button", { name: "Hide full diagnostics" })).not.toBeNull();
  });

  it("disables refresh while readiness is refreshing", () => {
    render(<WorkspaceSetupWizard onRefresh={() => {}} refreshing status={statusPayload()} />);

    const refreshButton = screen.getByRole("button", { name: "Refreshing readiness..." });
    expect(refreshButton.hasAttribute("disabled")).toBe(true);
  });

  it("uses explicit empty states when readiness sequence and claim narrowing are missing", () => {
    render(
      <WorkspaceSetupWizard
        status={statusPayload({
          diagnostics: {
            ...statusPayload().diagnostics,
            setupReadiness: {
              state: "ready",
              nextStep: "complete",
              claimNarrowing: [],
            },
            setupSequence: [],
          },
        })}
      />,
    );

    expect(screen.getByText("Readiness sequence pending")).not.toBeNull();
    expect(screen.getByText("Claims at full breadth")).not.toBeNull();
  });
});
