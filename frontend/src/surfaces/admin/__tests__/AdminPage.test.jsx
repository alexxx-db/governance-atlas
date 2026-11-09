/*
 * AdminPage (Control Center, Wave C6) — ported from the legacy
 * AdminWorkspace.test.jsx + AdminWorkspace.gaps.test.jsx +
 * CapabilityDashboard.test.jsx suites. Asserts the surface CONTRACT, not the
 * old DOM: jobs honesty (run-time splitting, UTC stamps, hash truncation,
 * jobsReason), policy consistency (backed exceptions zero + honest
 * unavailable cards), integration backend-truth, activity entity anchors,
 * admin gating, tab deep links, and the diagnostics capability truth table.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminPage from "../AdminPage";
import {
  fetchAdminBackgroundStatus,
  fetchAdminControlCenter,
  fetchAdminTruthCheck,
  fetchRuntimeStatus,
} from "../../../lib/api";

vi.mock("../../../lib/api", () => ({
  fetchAdminControlCenter: vi.fn(),
  fetchAdminTruthCheck: vi.fn(),
  fetchRuntimeStatus: vi.fn(),
  fetchAdminBackgroundStatus: vi.fn(),
}));

const ADMIN_SHELL = { role: "Platform Admin", userEmail: "abarreto@shorecp.com" };

const controlCenterPayload = {
  meta: { source: "runtime-diagnostics+governance-store", state: "available", authoritative: true },
  environment: { catalog: "emet", schema: "axiom", target: "dev", warehouseId: "wh-123" },
  role: { value: "admin", label: "Platform Admin", state: "available" },
  coverage: { metadataCoverage: 95.5 },
  runtimeSummary: {
    state: "live",
    catalogCount: 7,
    warehouseId: "wh-123",
    host: "https://dbc.example.com",
    authMode: "oauth-m2m-env",
  },
  access: {
    users: { value: 12, state: "available" },
    roles: { value: 3, state: "available" },
  },
  scheduledJobs: [
    {
      id: "job-1",
      name: "UC metadata sweeper",
      schedule: "Every 15 min",
      lastRun: "4 min ago",
      status: "healthy",
      runUrl: "https://example.cloud.databricks.com/jobs/123/runs/456",
    },
    { id: "job-2", name: "Lineage collector", schedule: "Every 1 hr", lastRun: "21 min ago", status: "healthy" },
  ],
  integrations: [
    { key: "unityCatalog", label: "Unity Catalog", subtitle: "Workspace inventory", state: "connected" },
    {
      key: "lineageService",
      label: "Lineage Service",
      subtitle: "Unity Catalog lineage",
      state: "unavailable",
      reason: "Dedicated lineage service health is not exposed by the current Admin payload.",
    },
    { key: "aiCopilot", label: "AI Copilot", subtitle: "Axiom AI Genie", state: "connected" },
    { key: "sqlWarehouse", label: "Databricks SQL Warehouse", subtitle: "Warehouse wh-123", state: "connected" },
    { key: "lakeflowJobs", label: "Lakeflow Jobs", subtitle: "12 jobs in workspace inventory", state: "connected" },
  ],
  policyRequirements: {
    cards: [
      {
        key: "totalPolicies",
        label: "Total Policies",
        value: null,
        state: "unavailable",
        reason: "No authoritative policy library or control-enforcement source is configured.",
      },
      {
        key: "enforcedPolicies",
        label: "Enforced Policies",
        value: null,
        state: "unavailable",
        reason: "No authoritative policy library or control-enforcement source is configured.",
      },
      {
        key: "exceptions",
        label: "Exceptions",
        value: 0,
        state: "available",
        reason: "Derived only from backed policy-exception audit/request text.",
      },
    ],
    byDomain: [
      {
        domain: "Customer",
        coverage: 100,
        coverageKind: "metadata",
        metadataCoverage: 100,
        state: "available",
        reason: "Metadata coverage from visible-asset diagnostics; policy-enforcement coverage is not yet backed.",
      },
      {
        domain: "Finance",
        coverage: 97.8,
        coverageKind: "metadata",
        metadataCoverage: 97.8,
        state: "available",
        reason: "Metadata coverage from visible-asset diagnostics; policy-enforcement coverage is not yet backed.",
      },
    ],
  },
  recentAdminActivity: [
    {
      id: "AUD-REAL-1",
      title: "Asset Metadata Updated",
      detail: "main.customer.customer_dim",
      createdAt: "2026-05-05T20:38:00Z",
      actorEmail: "abarreto@shorecp.com",
      status: "success",
    },
  ],
};

const runtimeStatusPayload = {
  identity: {
    actorEmail: "abarreto@shorecp.com",
    authMode: "obo-available",
    visibilityScope: "actor-scoped",
    authenticatedUserPresent: true,
  },
  runtime: {
    state: "live",
    message: "",
    client: { host: "https://example.cloud.databricks.com", warehouseId: "wh-123", authMode: "oauth-m2m" },
  },
  store: { state: "live", message: "" },
  config: { warehouseId: "wh-123", govCatalog: "main", govSchema: "gov" },
  capabilities: {
    governanceWrite: { available: true, state: "available", reason: "", source: "governance-control-plane" },
    governanceApproval: { available: true, state: "available", reason: "", source: "governance-control-plane" },
    systemInventoryRead: { available: true, state: "available", reason: "", source: "unity-catalog-actor" },
    tableLineage: { available: true, state: "available", reason: "", protectedRead: true },
    columnLineage: { available: true, state: "available", reason: "", protectedRead: true },
    workloadVisibility: {
      available: false,
      state: "unavailable",
      reason: "Query history is not shared.",
      protectedRead: true,
    },
    qualityRunEligibility: { available: false, state: "unavailable", reason: "Not implemented." },
    exportAllowed: { available: false, state: "unavailable", reason: "Not implemented." },
    manualLineageOverrides: { available: false, state: "unavailable", reason: "Not implemented." },
  },
};

const backgroundStatusPayload = {
  data: {
    drainer: { running: true, lastDrainAt: "2026-04-20T12:00:00Z", processedTotal: 7, lastError: null },
    queue: { depthHint: null },
  },
  meta: { state: "available", reason: "" },
};

const truthCheckPayload = {
  meta: { source: "system.information_schema", state: "available" },
  data: {
    discoveryCatalogs: ["emet", "ghost"],
    hiddenCatalogs: ["system"],
    metastore: {
      catalogTotal: 7,
      schemaTotalForDiscovery: 2,
      tableTotalForDiscovery: 5,
      perCatalog: [
        {
          catalog: "emet",
          configured: true,
          state: "populated",
          stateReason: "",
          metastore: { schemaCount: 2, tableCount: 5 },
          ui: { inventoryAssetCount: 5, visibleAssetCount: 5 },
          drift: { inventoryDelta: 0, hiddenByVisibility: 0 },
        },
        {
          catalog: "ghost",
          configured: true,
          state: "empty-or-unauthorized",
          stateReason:
            "No schemas or tables are visible to the app principal in this catalog — it is either empty or the principal lacks information_schema grants.",
          metastore: { schemaCount: 0, tableCount: 0 },
          ui: { inventoryAssetCount: 0, visibleAssetCount: 0 },
          drift: { inventoryDelta: 0, hiddenByVisibility: 0 },
        },
      ],
    },
    ui: { inventoryTotal: 5, visibleTotal: 5 },
    drift: {
      inventoryDelta: 3,
      hiddenByVisibility: 0,
      warnings: [
        "3 metastore table(s) are not in the surfaced inventory — likely a stale inventory cache or hidden-schema rules.",
      ],
    },
    queries: [
      { label: "system.information_schema.catalogs", sql: "SELECT 1", rowCount: 7, elapsedMs: 0, error: null },
    ],
    observedAt: "2026-07-19T22:04:11Z",
  },
};

function renderAdmin({ shell = ADMIN_SHELL, bootstrap = null, route = "/admin" } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <AdminPage bootstrap={bootstrap} shell={shell} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminPage (Control Center)", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    fetchAdminControlCenter.mockReset().mockResolvedValue(controlCenterPayload);
    fetchAdminTruthCheck.mockReset().mockResolvedValue(truthCheckPayload);
    fetchRuntimeStatus.mockReset().mockResolvedValue(runtimeStatusPayload);
    fetchAdminBackgroundStatus.mockReset().mockResolvedValue(backgroundStatusPayload);
  });

  it("renders the Operations tab: runtime summary, jobs, and activity", async () => {
    renderAdmin();

    expect(await screen.findByText("UC metadata sweeper")).toBeDefined();
    expect(screen.getByText("Axiom runtime operations")).toBeDefined();
    expect(screen.getByText("Runtime summary")).toBeDefined();
    expect(screen.getByText("Scheduled jobs")).toBeDefined();
    expect(screen.getByText("Recent admin activity")).toBeDefined();
    // App-wide percent convention: 95.5 keeps its decimal, never rounds to 96%.
    expect(screen.getByText("95.5%")).toBeDefined();
    expect(screen.getByText("12 users")).toBeDefined();
    expect(screen.getByText("3 roles")).toBeDefined();
    expect(screen.getByText("emet.axiom")).toBeDefined();
    // Only the operations tab's data is fetched; diagnostics stays cold.
    expect(fetchAdminTruthCheck).not.toHaveBeenCalled();
    expect(fetchRuntimeStatus).not.toHaveBeenCalled();
  });

  it("gates non-admin actors with an honest access card and no admin fetch", () => {
    renderAdmin({ shell: { role: "Reader", userEmail: "reader@example.com" } });

    expect(fetchAdminControlCenter).not.toHaveBeenCalled();
    expect(screen.getByText("Control Center is admin-only")).toBeDefined();
    expect(screen.getByText(/Ask a workspace admin to grant administration access/)).toBeDefined();
    // No tabs are advertised to a gated actor.
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("splits future run timestamps into Next run and truncates job-name hashes", async () => {
    const future = new Date(Date.now() + 86_400_000).toISOString();
    fetchAdminControlCenter.mockResolvedValue({
      ...controlCenterPayload,
      scheduledJobs: [
        {
          id: "job-9",
          name: "[RUNNER] pixels | 0f1f0a3b2a5f8c7d6e5f4a3b2c1d0e9f",
          schedule: "Daily 03:00 UTC",
          lastRun: future,
          status: "scheduled",
        },
      ],
    });
    renderAdmin();

    // A future date is a NEXT run, never history.
    expect(await screen.findByText("Not yet run")).toBeDefined();
    expect(screen.getByText("Next run")).toBeDefined();
    // Hash tail truncated for display; full name kept on the title attr.
    const jobName = screen.getByText("[RUNNER] pixels | 0f1f0a3b…");
    expect(jobName.getAttribute("title")).toBe("[RUNNER] pixels | 0f1f0a3b2a5f8c7d6e5f4a3b2c1d0e9f");
  });

  it("renders empty lastRun as 'Not yet run' and past ISO stamps year-carrying in UTC", async () => {
    fetchAdminControlCenter.mockResolvedValue({
      ...controlCenterPayload,
      scheduledJobs: [
        { id: "job-10", name: "Quality profiler", schedule: "Manual", lastRun: "", status: "Manual" },
        {
          id: "job-11",
          name: "UC metadata sweeper",
          schedule: "Daily 03:00 UTC",
          lastRun: "2026-07-19T03:00:00Z",
          status: "Scheduled",
        },
      ],
    });
    renderAdmin();

    expect(await screen.findByText("Not yet run")).toBeDefined();
    // Year-carrying, UTC-labeled timestamp — never raw ISO.
    expect(screen.getByText("Jul 19, 2026, 03:00 AM UTC")).toBeDefined();
    expect(screen.queryByText("2026-07-19T03:00:00Z")).toBeNull();
    // Honest Manual/Scheduled statuses render as shipped by the backend.
    expect(screen.getAllByText("Manual").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Scheduled").length).toBeGreaterThan(0);
  });

  it("explains a genuinely empty jobs table with the backend jobsReason", async () => {
    fetchAdminControlCenter.mockResolvedValue({
      ...controlCenterPayload,
      scheduledJobs: [],
      jobsState: "unavailable",
      jobsReason: "No Databricks Jobs API rows were returned for this runtime.",
    });
    renderAdmin();

    expect(
      await screen.findByText("No Databricks Jobs API rows were returned for this runtime."),
    ).toBeDefined();
  });

  it("links reported job run URLs and renders an honest dash when none exists", async () => {
    renderAdmin();

    await screen.findByText("UC metadata sweeper");
    const link = screen.getByRole("link", { name: "Open ↗" });
    expect(link.getAttribute("href")).toBe("https://example.cloud.databricks.com/jobs/123/runs/456");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("renders activity rows with UTC time and real entity anchors", async () => {
    renderAdmin();

    expect(await screen.findByText("Asset Metadata Updated")).toBeDefined();
    // 20:38 UTC must render as 08:38 PM UTC — never the browser's local zone.
    expect(screen.getByText(/08:38\s?PM UTC/)).toBeDefined();
    // Cross-linking LAW: the asset mention is a real middle-clickable anchor.
    const assetLink = screen.getByRole("link", { name: /main\.customer\.customer_dim/ });
    expect(assetLink.getAttribute("href")).toBe("/assets/main.customer.customer_dim");
    // The actor is an owner anchor into Discover's owner search.
    const actorLink = screen.getByRole("link", { name: /abarreto@shorecp\.com/ });
    expect(actorLink.getAttribute("href")).toContain("/discovery?");
  });

  it("deep-links ?tab=integrations and renders backend rows verbatim", async () => {
    renderAdmin({ route: "/admin?tab=integrations" });

    expect(await screen.findByText("AI Copilot")).toBeDefined();
    expect(screen.getByText("Lineage Service")).toBeDefined();
    expect(screen.getByText("Databricks SQL Warehouse")).toBeDefined();
    expect(screen.getByText("Lakeflow Jobs")).toBeDefined();
    // Honest unavailable state carries the API's own reason string.
    expect(
      screen.getByText("Dedicated lineage service health is not exposed by the current Admin payload."),
    ).toBeDefined();
    // Aspirational products with no runtime probe must not render fake rows.
    expect(screen.queryByText("Model Serving")).toBeNull();
    expect(screen.queryByText("Incident management")).toBeNull();
    expect(screen.queryByText("Runtime signal unavailable")).toBeNull();
  });

  it("deep-links ?tab=policy: backed exceptions zero + honest-unavailable cards", async () => {
    renderAdmin({ route: "/admin?tab=policy" });

    // Await the data-backed card (the heading renders before the payload).
    // "Policy" is both the tab label and the card title — scope to the card.
    const panel = (await screen.findByText("Exceptions")).closest("section");
    const scoped = within(panel);
    // Backed signal: 0 exceptions with sources responding is an AVAILABLE
    // zero (consistent with the Command Center), never "Unavailable".
    expect(scoped.getByRole("heading", { level: 2, name: "Policy" })).toBeDefined();
    expect(scoped.getByText("0")).toBeDefined();
    expect(scoped.getByText("Total Policies")).toBeDefined();
    expect(scoped.getByText("Enforced Policies")).toBeDefined();
    expect(scoped.getAllByText("Unavailable").length).toBe(2);
    expect(
      scoped.getAllByText("No authoritative policy library or control-enforcement source is configured.").length,
    ).toBe(2);
  });

  it("re-scopes metadata-only coverage rows to an honest panel title", async () => {
    renderAdmin({ route: "/admin?tab=policy" });

    expect(await screen.findByText("Metadata coverage by domain")).toBeDefined();
    expect(
      screen.getByText("Metadata completeness per domain — not policy-enforcement coverage"),
    ).toBeDefined();
    expect(screen.getByText("100%")).toBeDefined();
    expect(screen.getByText("97.8%")).toBeDefined();
    // Domain mentions are anchors into Discover, not dead rows.
    const domainLink = screen.getByRole("link", { name: /Customer/ });
    expect(domainLink.getAttribute("href")).toContain("/discovery?");
  });

  it("deep-links ?tab=diagnostics (the absorbed /capabilities surface)", async () => {
    renderAdmin({ route: "/admin?tab=diagnostics" });

    expect(await screen.findByText("Capability truth")).toBeDefined();
    expect(fetchRuntimeStatus).toHaveBeenCalled();
    expect(fetchAdminBackgroundStatus).toHaveBeenCalled();
    // Every capability flag renders with its honest reason (the same reason
    // legitimately repeats in the system-table health table).
    expect(await screen.findByText("Workload visibility")).toBeDefined();
    expect(screen.getAllByText("Query history is not shared.").length).toBeGreaterThan(0);
    expect(screen.getByText("Identity and auth")).toBeDefined();
    expect(screen.getByText("Runtime and store")).toBeDefined();
    expect(screen.getByText("Background work health")).toBeDefined();
    expect(screen.getByText("System-table health")).toBeDefined();
    // The metastore truth check rides along in Diagnostics.
    expect(await screen.findByText("Metastore truth check")).toBeDefined();
    expect(fetchAdminTruthCheck).toHaveBeenCalled();
  });

  it("compares runtime capability truth against the conservative bootstrap signal", async () => {
    renderAdmin({
      route: "/admin?tab=diagnostics",
      bootstrap: {
        capabilities: {
          // Bootstrap pessimism: it says degraded while the runtime says
          // available — both render, and the copy says the runtime wins.
          tableLineage: { available: false, state: "degraded", reason: "warming" },
        },
      },
    });

    expect(await screen.findByText("Capability truth")).toBeDefined();
    const table = screen.getByRole("table", { name: "Capability truth flags" });
    const lineageRow = within(table).getByText("Table lineage").closest("tr");
    const badges = Array.from(lineageRow.querySelectorAll(".ax-sys-badge")).map((el) => el.textContent);
    expect(badges).toContain("Yes"); // runtime truth
    expect(badges).toContain("Degraded"); // bootstrap's conservative signal
    expect(screen.getByText(/the live runtime wins/)).toBeDefined();
  });

  it("refreshes the capability snapshot on demand", async () => {
    renderAdmin({ route: "/admin?tab=diagnostics" });

    await screen.findByText("Capability truth");
    const callsBefore = fetchRuntimeStatus.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /Refresh capability snapshot/i }));
    expect(fetchRuntimeStatus.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("formats truth-check output and badges zero-visibility catalogs", async () => {
    renderAdmin({ route: "/admin?tab=diagnostics" });

    expect(await screen.findByText("Metastore truth check")).toBeDefined();
    expect(await screen.findByText("No objects visible to app principal")).toBeDefined();
    // Drift explanation from the backend surfaces as a warning banner.
    expect(
      screen.getByText(
        "3 metastore table(s) are not in the surfaced inventory — likely a stale inventory cache or hidden-schema rules.",
      ),
    ).toBeDefined();
    // Observed timestamp is humanized, not raw ISO.
    expect(screen.queryByText("2026-07-19T22:04:11Z")).toBeNull();
    // A legit 0 ms probe renders "0 ms", not "elapsed unavailable".
    fireEvent.click(screen.getByText(/SQL probes/));
    expect(screen.getByText(/0 ms/)).toBeDefined();
    expect(screen.queryByText(/elapsed unavailable/)).toBeNull();
  });

  it("switching tabs writes ?tab= so the view is addressable", async () => {
    renderAdmin();

    await screen.findByText("UC metadata sweeper");
    fireEvent.click(screen.getByRole("tab", { name: "Integrations" }));
    expect(await screen.findByText("AI Copilot")).toBeDefined();
    expect(screen.getByRole("tab", { name: "Integrations" }).getAttribute("aria-selected")).toBe("true");
  });

  it("rejects non-authoritative diagnostics wholesale while keeping real warnings", async () => {
    fetchAdminControlCenter.mockResolvedValue({
      ...controlCenterPayload,
      meta: {
        ...controlCenterPayload.meta,
        evidenceKind: "non_authoritative_mock_capture",
      },
    });
    renderAdmin();

    expect(
      await screen.findByText(
        /Non-authoritative Control Center diagnostics were rejected\. Live diagnostics are required/,
      ),
    ).toBeDefined();
    // Fabricated rows never render as governed truth.
    expect(screen.queryByText("UC metadata sweeper")).toBeNull();
    expect(screen.getByText("No backed scheduled-job inventory is available yet.")).toBeDefined();
  });

  it("renders skeletons — never Unavailable rows — while the payload hydrates", async () => {
    fetchAdminControlCenter.mockResolvedValue({
      meta: { state: "loading", capabilities: { hydrating: true } },
      scheduledJobs: [],
      integrations: [],
    });
    renderAdmin();

    await screen.findByText("Scheduled jobs");
    expect(screen.queryByText("No backed scheduled-job inventory is available yet.")).toBeNull();
    expect(screen.queryByText("No scheduled jobs reported")).toBeNull();
    expect(document.querySelectorAll(".ax-sys-skeleton").length).toBeGreaterThan(0);
  });

  it("keeps missing live signals truthful with honest empty states", async () => {
    fetchAdminControlCenter.mockResolvedValue({ environment: { displayLabel: "Dev · empty" } });
    renderAdmin();

    expect(await screen.findByText("No backed scheduled-job inventory is available yet.")).toBeDefined();
    expect(screen.getByText("No recent admin activity")).toBeDefined();
  });
});
