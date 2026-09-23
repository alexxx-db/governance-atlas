import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { atlasQueryClient } from "../../../lib/queryClient";
import { toast, ToastHost } from "../../../components/system";
import AssetHubPage from "../AssetHubPage";
import { ShellProvider } from "../../../app-shell/ShellContext";

/* ------------------------------------------------------------------ mocks */

const api = vi.hoisted(() => ({
  fetchAssetDetail: vi.fn(),
  fetchAssetAvailability: vi.fn(),
  fetchAssetHeaders: vi.fn(),
  fetchAsset360: vi.fn(),
  fetchAssetQuality: vi.fn(),
  fetchLineage: vi.fn(),
  createGovernanceRequest: vi.fn(),
  updateAssetMetadata: vi.fn(),
  getAssetMetadataApiContract: vi.fn(),
  fetchAssetMetadataEditor: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

// React Flow + dagre are jsdom-hostile; the canvas has its own test suite.
vi.mock("../../../components/lineage-v2/LineageCanvasV2", () => {
  const Stub = () => <div data-testid="lineage-canvas" />;
  return { LineageCanvasV2: Stub, default: Stub };
});

/* --------------------------------------------------------------- fixtures */

const FQN = "main.sales.orders";

function detailFixture(overrides = {}) {
  return {
    fqn: FQN,
    name: "orders",
    catalog: "main",
    schema: "sales",
    objectType: "Table",
    description: "Sales orders fact table.",
    coverageScore: 82,
    rows: 5,
    size: "1.2 MB",
    domain: "Sales",
    certification: "Certified",
    sensitivity: "Internal",
    criticality: "Tier 1",
    isCde: true,
    openRequests: 2,
    ucOwner: "skyler@entrada.ai",
    businessOwner: "product-steward@entrada.ai",
    steward: "finance-steward@entrada.ai",
    dataUpdatedAt: "2026-05-03T19:51:25.309000Z",
    lastAltered: "2026-06-01T00:00:00Z",
    glossaryTerms: ["Net Revenue"],
    glossaryLinks: [{ term: "Net Revenue", termId: "term-9" }],
    columns: [
      { name: "order_id", type: "BIGINT", description: "Order key" },
      { name: "amount", type: "DECIMAL(18,2)", description: "No description" },
    ],
    columnCount: 2,
    loadedSections: ["header", "schema", "activity"],
    ...overrides,
  };
}

function asset360Fixture(overrides = {}) {
  return {
    asset: { fqn: FQN, name: "orders" },
    ownership: {
      ucOwner: { name: "skyler@entrada.ai", title: "Unity Catalog owner" },
      businessOwner: { name: "product-steward@entrada.ai", title: "Business Owner" },
      steward: { name: "finance-steward@entrada.ai", title: "Steward" },
    },
    freshness: {
      state: "available",
      dataUpdatedAt: "2026-05-03T19:51:25.309000Z",
      lastAltered: "2026-06-01T00:00:00Z",
      labels: { dataUpdatedAt: "Data updated", lastAltered: "Metadata changed" },
      message: "",
    },
    usage: {
      sources: {
        downstreamAssets: { label: "Downstream assets", source: "lineage", state: "available", count: 1, reason: "" },
        consumers: {
          label: "Consumers",
          source: "operational-context",
          state: "unavailable",
          count: null,
          reason: "Operational usage requires OBO.",
        },
        queries: {
          label: "Queries",
          source: "query-history",
          state: "unavailable",
          count: null,
          reason: "Operational usage requires OBO.",
        },
      },
      window: { state: "unavailable", label: "", reason: "" },
    },
    quality: {
      state: "available",
      message: "",
      latestRun: {
        runId: "run-1",
        executedAt: "2026-07-20T10:00:05Z",
        outcomes: { passed: 1, failed: 1, errored: 0, skipped: 0 },
        failedBySeverityLevel: { high: 1, medium: 0, informational: 0 },
        checkCount: 2,
      },
      evidenceAt: "2026-07-20T10:00:05Z",
      checksEvaluated: 3,
    },
    access: {
      state: "available",
      authMode: "app-principal-only",
      visibilityScope: "workspace-app-principal",
      actorEmail: "skyler@entrada.ai",
      remediation: [
        { label: "Enable per-user authorization (OBO)", detail: "Open from a Databricks session." },
      ],
      deepLinks: { catalogExplorer: "/explore/data/main/sales/orders" },
      grants: { state: "unavailable", reason: "Per-principal grants are not collected by the app." },
    },
    activity: [
      {
        id: "evt-1",
        title: "Task updated",
        detail: "open",
        status: "Pending",
        createdAt: "2026-07-21T15:04:19.000Z",
        createdBy: "skyler@entrada.ai",
        actorEmail: "skyler@entrada.ai",
        taskId: "task-9",
        priority: "p1",
      },
      {
        id: "aud-1",
        title: "Task Triage Updated",
        displayAuditId: "AUD-0F0E0D0C",
        actorEmail: "skyler@entrada.ai",
        createdAt: "2026-07-21T15:00:00.000Z",
        status: "Success",
      },
    ],
    relatedAssets: [{ fqn: "main.sales.orders_gold" }],
    loadedSections: ["header", "activity", "schema"],
    ...overrides,
  };
}

function lineageFixture() {
  return {
    profile: "full",
    // Real lineage envelopes carry an authority marker; without one the
    // non-authoritative-evidence guard (lib/nonAuthoritativeEvidence) nulls
    // the payload.
    authoritative: true,
    meta: { state: "available" },
    stats: {},
    graphs: {
      data: {
        nodes: [
          { id: `focus-${FQN}`, assetFqn: FQN, kicker: "Focus", kind: "Table", role: "focus" },
          { id: "up-1", assetFqn: "main.raw.orders_src", kicker: "Upstream", kind: "Table" },
        ],
        edges: [{ id: "e1", source: "up-1", target: `focus-${FQN}` }],
        meta: {},
      },
    },
  };
}

/* ---------------------------------------------------------------- harness */

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderPage(initialEntry = `/assets/${encodeURIComponent(FQN)}`) {
  return render(
    <QueryClientProvider client={atlasQueryClient}>
      <ShellProvider value={{ shell: { workspaceHost: "https://example.cloud.databricks.com" } }}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/assets/:fqn" element={<AssetHubPage />} />
          </Routes>
          <LocationProbe />
          <ToastHost />
        </MemoryRouter>
      </ShellProvider>
    </QueryClientProvider>,
  );
}

function primeHappyPath() {
  api.fetchAssetDetail.mockResolvedValue(detailFixture());
  api.fetchAsset360.mockResolvedValue(asset360Fixture());
  api.fetchLineage.mockResolvedValue(lineageFixture());
  api.fetchAssetQuality.mockResolvedValue({
    runs: [],
    results: [
      {
        result_id: "r-1",
        run_id: "run-1",
        case_id: "row_count_min",
        outcome: "failed",
        severity: "critical",
        metric_value: 0,
        threshold_value: 1,
        executed_at: "2026-07-20T10:00:00Z",
        detail: "row count below minimum",
      },
    ],
    summary: { passed: 1, failed: 1, errored: 0, skipped: 0 },
  });
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getAssetMetadataApiContract.mockReturnValue({ available: false, capabilityPath: "", updatePath: "" });
  api.fetchAssetMetadataEditor.mockResolvedValue(null);
  api.fetchAssetAvailability.mockResolvedValue({ assets: {} });
  api.fetchAssetHeaders.mockResolvedValue({ assets: {} });
  atlasQueryClient.clear();
  toast.clear();
});

/* ------------------------------------------------------------------ tests */

describe("AssetHubPage — trust verdict hero", () => {
  it("renders the full trust verdict with two labeled UTC freshness values and distinct owner roles", async () => {
    primeHappyPath();
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));

    const verdict = screen.getByLabelText("Trust verdict");
    expect(within(verdict).getByText("Certified")).toBeTruthy();
    expect(within(verdict).getByText("Governance score")).toBeTruthy();
    expect(within(verdict).getByText("82")).toBeTruthy();
    expect(within(verdict).getByText("CDE · Criticality-derived")).toBeTruthy();
    expect(within(verdict).getByText("Internal")).toBeTruthy();

    // Two labeled freshness values, absolute UTC display, ISO in tooltip —
    // never a raw ISO headline (teardown P0-4) and no sparkline SVG.
    expect(within(verdict).getByText("Data updated")).toBeTruthy();
    expect(within(verdict).getByText("Metadata changed")).toBeTruthy();
    const dataUpdated = within(verdict).getByText("May 3, 2026, 19:51 UTC");
    expect(dataUpdated.getAttribute("title")).toBe("2026-05-03T19:51:25.309Z");
    expect(within(verdict).getByText("Jun 1, 2026, 00:00 UTC")).toBeTruthy();
    // No fake sparkline (the only SVGs allowed are entity-chip icons).
    expect(verdict.querySelector(".ga-sys-sparkline")).toBeNull();
    expect(verdict.querySelector("polyline")).toBeNull();

    // Ownership: distinct roles, each a REAL owner-search anchor.
    expect(within(verdict).getByText("Owner (Unity Catalog)")).toBeTruthy();
    const business = within(verdict).getByText("product-steward@entrada.ai").closest("a");
    expect(business.getAttribute("href")).toContain("/discovery");
    expect(decodeURIComponent(business.getAttribute("href"))).toContain('owner:"product-steward@entrada.ai"');
    const steward = within(verdict).getByText("finance-steward@entrada.ai").closest("a");
    expect(steward).toBeTruthy();
  });

  it("renders the record header from the 360 composite WITHOUT waiting on the detail request (no waterfall)", async () => {
    api.fetchAssetDetail.mockReturnValue(new Promise(() => {})); // never resolves
    api.fetchAsset360.mockResolvedValue(asset360Fixture());
    api.fetchLineage.mockReturnValue(new Promise(() => {}));
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    // Freshness from the composite renders too — the hero is fully seeded.
    expect(screen.getByText("May 3, 2026, 19:51 UTC")).toBeTruthy();
  });

  it("keeps the frame + retry on a terminal detail failure (never a dead end)", async () => {
    api.fetchAssetDetail.mockRejectedValue(new Error("detail exploded"));
    api.fetchAsset360.mockResolvedValue({ meta: { state: "error" } });
    api.fetchLineage.mockResolvedValue(lineageFixture());
    renderPage();

    await waitFor(() => expect(screen.getByText("Something went wrong")).toBeTruthy(), {
      timeout: 10_000,
    });
    // The frame stays: breadcrumb FQN, tabs, and a Retry affordance.
    expect(screen.getByTestId("location").textContent).toContain("/assets/");
    expect(screen.getByRole("tab", { name: /Overview/ })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
  });
});

describe("AssetHubPage — tab addressability and persistence", () => {
  it("opens the tab named by ?tab= and keeps the record header on tab switches", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=columns`);

    await waitFor(() => expect(screen.getByText("order_id")).toBeTruthy());
    expect(screen.getByRole("tab", { name: /Columns/ }).getAttribute("aria-selected")).toBe("true");

    // Switch to Access via the strip: URL updates, hero verdict persists,
    // and the page NEVER regresses to a whole-page shell (teardown P0-2).
    fireEvent.click(screen.getByRole("tab", { name: "Access" }));
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toContain("tab=access"),
    );
    expect(screen.getByLabelText("Trust verdict")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders");
    await waitFor(() => expect(screen.getByText("Auth mode")).toBeTruthy());
  });

  it("highlights the ?col= column and only shows a Glossary column when column links exist", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=columns&col=amount`);

    await waitFor(() => expect(screen.getByText("amount")).toBeTruthy());
    expect(screen.getByText("amount").className).toContain("is-highlight");
    // No column carries a column-scoped glossary link → honest omission.
    expect(screen.queryByText("Glossary term")).toBeNull();
  });

  it("shows the Glossary column with real term anchors when column links exist", async () => {
    api.fetchAssetDetail.mockResolvedValue(
      detailFixture({
        columns: [
          {
            name: "revenue",
            type: "DECIMAL",
            description: "Recognized revenue",
            glossaryLinks: [{ term: "Net Revenue", termId: "term-9" }],
          },
        ],
      }),
    );
    api.fetchAsset360.mockResolvedValue(asset360Fixture());
    api.fetchLineage.mockResolvedValue(lineageFixture());
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=columns`);

    await waitFor(() => expect(screen.getByText("Glossary term")).toBeTruthy());
    const chip = screen.getByText("Net Revenue").closest("a");
    expect(chip.getAttribute("href")).toBe("/glossary/term-9");
  });
});

describe("AssetHubPage — overview content", () => {
  it("renders first-hop lineage, per-source usage truth, quality summary and related-asset chips", async () => {
    primeHappyPath();
    renderPage();

    // Mini-map neighbors come from the v2 adapter (compact labels, real hrefs).
    await waitFor(() => expect(screen.getByText("orders_src")).toBeTruthy(), { timeout: 8000 });
    expect(screen.getByText(/Upstream \(1\)/)).toBeTruthy();
    const upstreamChip = screen.getByText("orders_src").closest("a");
    expect(upstreamChip.getAttribute("href")).toBe(
      `/assets/${encodeURIComponent("main.raw.orders_src")}`,
    );

    // Usage: each source separately honest — no fabricated window.
    expect(screen.getByText("Downstream assets")).toBeTruthy();
    expect(screen.getByText("Consumers")).toBeTruthy();
    expect(screen.queryByText(/Last 30 days/)).toBeNull();

    // Quality summary links into Evidence.
    const findings = screen.getByText("View findings in Evidence").closest("a");
    expect(findings.getAttribute("href")).toContain("/evidence?tab=quality");
    expect(findings.getAttribute("href")).toContain("run=run-1");

    // Related assets are real asset anchors; open-request chip scopes Stewardship.
    const related = screen.getByText("main.sales.orders_gold").closest("a");
    expect(related.getAttribute("href")).toBe(`/assets/${encodeURIComponent("main.sales.orders_gold")}`);
    const openRequests = screen.getByText("2 open requests").closest("a");
    expect(openRequests.getAttribute("href")).toContain("/stewardship");
    expect(openRequests.getAttribute("href")).toContain("asset=");
  });
});

describe("AssetHubPage — header actions", () => {
  it("Certify writes through the metadata path, flips the badge optimistically and toasts", async () => {
    api.fetchAssetDetail.mockResolvedValue(
      detailFixture({
        certification: "",
        metadataEditor: {
          available: true,
          updatePath: "/api/assets/main.sales.orders/metadata",
          updateMethod: "PATCH",
          fields: [{ key: "certification" }],
        },
      }),
    );
    api.fetchAsset360.mockResolvedValue(asset360Fixture({ freshness: undefined }));
    api.fetchLineage.mockResolvedValue(lineageFixture());
    api.updateAssetMetadata.mockResolvedValue({});
    renderPage();

    await waitFor(() => expect(screen.getByText("Not certified")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Certify/ }));
    const menu = await screen.findByRole("menu", { name: "Certification actions" });
    // Live write contract available → no staging caption.
    expect(within(menu).queryByText(/change request/)).toBeNull();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Mark as Certified" }));

    await waitFor(() =>
      expect(api.updateAssetMetadata).toHaveBeenCalledWith(
        FQN,
        { certification: "Certified" },
        expect.anything(),
      ),
    );
    await waitFor(() => expect(screen.getByText("Certification set to Certified.")).toBeTruthy());
    // Optimistic badge in the trust verdict.
    const verdict = screen.getByLabelText("Trust verdict");
    await waitFor(() => expect(within(verdict).getByText("Certified")).toBeTruthy());
    expect(api.createGovernanceRequest).not.toHaveBeenCalled();
  });

  it("Certify stages a pre-filled change request (and says so) when no write path exists", async () => {
    primeHappyPath();
    api.createGovernanceRequest.mockResolvedValue({ requestId: "GOV-12345678" });
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    fireEvent.click(screen.getByRole("button", { name: /Certify/ }));
    const menu = await screen.findByRole("menu", { name: "Certification actions" });
    // Honesty BEFORE the click: the menu states selections file a request.
    expect(within(menu).getByText(/files a change request/)).toBeTruthy();
    fireEvent.click(within(menu).getByRole("menuitem", { name: /Mark as Certified/ }));

    await waitFor(() => expect(api.createGovernanceRequest).toHaveBeenCalled());
    const [payload] = api.createGovernanceRequest.mock.calls[0];
    expect(payload.assetFqn).toBe(FQN);
    expect(payload.title).toContain("Certification change requested: Certified");
    await waitFor(() => expect(screen.getByText(/filed change request GOV-12345678/)).toBeTruthy());
    expect(api.updateAssetMetadata).not.toHaveBeenCalled();
  });

  it("Request Change posts the real create-request API scoped to the asset, with a failure toast on error", async () => {
    primeHappyPath();
    api.createGovernanceRequest.mockRejectedValueOnce(new Error("queue is down"));
    api.createGovernanceRequest.mockResolvedValueOnce({ requestId: "GOV-abcdef01" });
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    fireEvent.click(screen.getByRole("button", { name: "Request change" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText(/What should change/), {
      target: { value: "Fix the owner" },
    });
    fireEvent.change(within(dialog).getByPlaceholderText(/Why is this change needed/), {
      target: { value: "Business owner left the company." },
    });

    // First submit fails → danger toast, dialog stays open.
    fireEvent.submit(document.getElementById("ga-asset-request-form"));
    await waitFor(() => expect(screen.getByText("queue is down")).toBeTruthy());
    expect(screen.getByRole("dialog")).toBeTruthy();

    // Second submit succeeds → success toast names the request id.
    fireEvent.submit(document.getElementById("ga-asset-request-form"));
    await waitFor(() => expect(screen.getByText(/GOV-abcdef01 filed/)).toBeTruthy());
    expect(api.createGovernanceRequest).toHaveBeenLastCalledWith(
      { assetFqn: FQN, title: "Fix the owner", note: "Business owner left the company." },
      { fast: true },
    );
  });

  it("renders a FIRST-CLASS 'Open in Databricks' header button as an absolute Catalog Explorer URL from the live deepLink", async () => {
    // Owner directive 2: the Catalog Explorer affordance is promoted OUT of the
    // kebab into a visible header button that always renders for a real FQN.
    // The relative deepLink is made absolute against the workspace host so the
    // anchor opens Databricks, not the app origin; new tab + rel=noopener.
    primeHappyPath();
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    const button = screen.getByRole("link", { name: "Open in Databricks" });
    expect(button.getAttribute("href")).toBe(
      "https://example.cloud.databricks.com/explore/data/main/sales/orders",
    );
    expect(button.getAttribute("target")).toBe("_blank");
    expect(button.getAttribute("rel")).toBe("noopener noreferrer");
    expect(button.getAttribute("title")).toBe("Open in Databricks Catalog Explorer");
  });

  it("kebab menu copies the canonical link and still offers Catalog Explorer as an absolute Databricks URL", async () => {
    primeHappyPath();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    fireEvent.click(screen.getByRole("button", { name: "More asset actions" }));
    const menu = await screen.findByRole("menu", { name: "More asset actions" });

    const explorer = within(menu).getByText("Open in Catalog Explorer");
    expect(explorer.closest("a").getAttribute("href")).toBe(
      "https://example.cloud.databricks.com/explore/data/main/sales/orders",
    );
    expect(explorer.closest("a").getAttribute("rel")).toBe("noopener noreferrer");

    fireEvent.click(within(menu).getByText("Copy link"));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText.mock.calls[0][0]).toContain(`/assets/${encodeURIComponent(FQN)}`);
    await waitFor(() => expect(screen.getByText("Link copied to clipboard.")).toBeTruthy());
  });

  it("keeps the lineage button ENABLED when the live lineage request fails (no bootstrap pessimism)", async () => {
    api.fetchAssetDetail.mockResolvedValue(detailFixture());
    api.fetchAsset360.mockResolvedValue(asset360Fixture());
    api.fetchLineage.mockRejectedValue(new Error("lineage down"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("orders"));
    const button = screen.getByRole("button", { name: "Open lineage" });
    await waitFor(() => expect(button.disabled).toBe(false));
  });
});

describe("AssetHubPage — Quality / Access / Activity / Lineage tabs", () => {
  it("Quality shows latest-run outcomes and per-check rows linking to Evidence", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=quality`);

    await waitFor(() => expect(screen.getByText("Latest run")).toBeTruthy());
    expect(screen.getByText("Passed")).toBeTruthy();
    expect(screen.getByText("Checks evaluated")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("row_count_min")).toBeTruthy());
    const finding = screen.getByText("row_count_min").closest("a");
    expect(finding.getAttribute("href")).toContain("/evidence?tab=quality");
    expect(finding.getAttribute("href")).toContain("run=run-1");
    expect(screen.getByText(/Evidence from/).getAttribute("title")).toBe("2026-07-20T10:00:05.000Z");
  });

  it("Quality is honestly unavailable when no checks have ever run", async () => {
    api.fetchAssetDetail.mockResolvedValue(detailFixture());
    api.fetchAsset360.mockResolvedValue(
      asset360Fixture({
        quality: { state: "unavailable", message: "No quality checks have run for this asset.", latestRun: null, evidenceAt: "", checksEvaluated: 0 },
      }),
    );
    api.fetchAssetQuality.mockResolvedValue({ runs: [], results: [], summary: null });
    api.fetchLineage.mockResolvedValue(lineageFixture());
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=quality`);

    await waitFor(() =>
      expect(screen.getByText("No quality checks have run for this asset.")).toBeTruthy(),
    );
  });

  it("Access renders auth mode, honest grants reason and remediation — and NO developer telemetry", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=access`);

    await waitFor(() => expect(screen.getByText("Auth mode")).toBeTruthy());
    expect(screen.getByText("app-principal-only")).toBeTruthy();
    expect(screen.getByText(/grants are not collected/)).toBeTruthy();
    expect(screen.getByText("Enable per-user authorization (OBO)")).toBeTruthy();
    // Teardown P1-8: the telemetry panel must be gone.
    expect(screen.queryByText(/Composite state/)).toBeNull();
    expect(screen.queryByText(/Loaded sections/)).toBeNull();
  });

  it("Activity renders actor chips, priority badges, absolute UTC times and AUD/task deep links", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=activity`);

    await waitFor(() => expect(screen.getByText("Task updated")).toBeTruthy());
    expect(screen.getByText("P1")).toBeTruthy();
    const time = screen.getByText("Jul 21, 2026, 15:04 UTC");
    expect(time.getAttribute("title")).toBe("2026-07-21T15:04:19.000Z");

    const audit = screen.getByText("AUD-0F0E0D0C").closest("a");
    expect(audit.getAttribute("href")).toBe("/evidence?event=AUD-0F0E0D0C");
    const task = screen.getByText("Task task-9").closest("a");
    expect(task.getAttribute("href")).toBe("/stewardship?item=task-9");
    const actors = screen.getAllByText("skyler@entrada.ai");
    expect(actors.some((node) => node.closest("a")?.getAttribute("href")?.includes("/discovery"))).toBe(true);
  });

  it("Lineage tab mounts the v2 canvas embed (resurrected dead embed)", async () => {
    primeHappyPath();
    renderPage(`/assets/${encodeURIComponent(FQN)}?tab=lineage`);

    await waitFor(() => expect(screen.getByTestId("lineage-canvas")).toBeTruthy());
  });
});
