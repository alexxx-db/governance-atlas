import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../../../lib/queryClient";
import { toast, ToastHost } from "../../../components/system";
import HomePage from "../HomePage.jsx";
import { __resetCommandCenterRetention } from "../../../hooks/useCommandCenter";

/* ------------------------------------------------------------------ mocks */

const api = vi.hoisted(() => ({
  fetchCommandCenter: vi.fn(),
  fetchInsightsDashboard: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

/* --------------------------------------------------------------- fixtures */

function commandCenterFixture(overrides = {}) {
  return {
    estate: {
      visibleAssetCount: 1247,
      catalogCount: 3,
      openRequests: 5,
      coverageScore: 95.5,
      estateLabel: "Data estate",
      cdeCount: 49,
    },
    kpis: [
      { key: "governedAssets", label: "Governed Assets", value: 1247, format: "number" },
      {
        key: "certifiedCriticalAssets",
        label: "Certified Critical Assets",
        value: 44,
        format: "number",
        deltaText: "+2 this week",
      },
      {
        key: "metadataCoverage",
        label: "Metadata Coverage",
        value: 95.5,
        format: "percent",
        formula: "Weighted coverage of required governance metadata fields across visible assets.",
      },
      { key: "openStewardship", label: "Open Stewardship Actions", value: 5, format: "number" },
      { key: "policyExceptions", label: "Policy Exceptions", value: 0, format: "number", state: "available" },
    ],
    posture: {
      overall: 87.4,
      formula: "40% metadata coverage + 25% strict certification rate",
      trend: [{ label: "2026-07-20", overall: 87.4 }],
      trendState: "collecting",
      collectingSince: "2026-07-20",
      byDomain: [
        { domain: "Risk", score: 61, count: 12 },
        { domain: "Customer", score: 84, count: 174 },
        { domain: "Revenue & Sales", score: 92, count: 138 },
      ],
    },
    catalogHealth: [
      { name: "customer_360", assetCount: 40, coverage: 82.1, classification: "Confidential", risk: "Medium" },
      { name: "finance_prod", assetCount: 120, coverage: 94.2, classification: "Restricted", risk: "High" },
    ],
    recentEvents: [
      {
        id: "AUD-0A1B2C3D",
        title: "Certification updated",
        detail: "finance_prod.curated.revenue_daily",
        actorEmail: "marisol@shorecp.com",
        createdAt: "2026-07-20T08:00:00Z",
        tone: "good",
      },
    ],
    recentAssets: [{ fqn: "finance_prod.curated.revenue_daily", catalog: "finance_prod" }],
    governance: {
      openRequests: 5,
      pendingRequests: [
        {
          request_id: "GOV-11223344",
          entity_fqn: "finance_prod.curated.revenue_daily",
          summary: "Request certification review",
          requested_by: "abarreto@shorecp.com",
          status: "pending",
          created_at: "2026-07-20T09:00:00Z",
        },
      ],
    },
    insights: {
      tiles: { cdeCount: 49 },
      qualitySla: 66.7,
      qualitySignalAvailable: true,
      qualityChecksEvaluated: 9,
      qualityEvidenceAt: "2026-05-03T11:00:00Z",
      lineageCoverage: 93.3,
    },
    lineage: { coverage: 93.3, state: "available", reason: "28 of 30 visible assets have recorded lineage." },
    riskBreakdown: {
      high: 2,
      medium: 3,
      informational: 4,
      total: 9,
      source: "quality_run_results",
      evidenceAt: "2026-05-03T11:00:00Z",
      label: "Quality risk findings",
    },
    cdes: [
      {
        id: "finance_prod.curated.revenue_daily",
        name: "revenue_daily",
        assetFqn: "finance_prod.curated.revenue_daily",
        owner: "finance-steward@shorecp.com",
        status: "Certified",
        sox: true,
      },
    ],
    cdeSignal: { count: 49, subtitle: "Criticality-derived", definition: "Criticality-derived population." },
    signalAvailability: { visibleAssets: true, audit: true, quality: true, lineage: true },
    meta: { state: "available", warnings: [], generatedAt: "2026-07-20T10:00:00Z", workspace: "prod" },
    ...overrides,
  };
}

function insightsFixture(overrides = {}) {
  return {
    kpis: [],
    policyComplianceTrend: [],
    resolutionTrend: [],
    metadataCoverageHeatmap: [
      { row: "Sales", column: "Discoverability", value: 90 },
      { row: "Sales", column: "Ownership", value: 70 },
    ],
    certificationCoverageByTier: [
      { label: "Tier 1 - Business Critical", value: 75, certified: 3, total: 4, filterValues: ["Critical"] },
    ],
    riskHeatmap: [{ row: "Very High", column: "High", value: 2, filterValues: ["Critical"] }],
    riskEvidenceAt: "2026-05-03T09:00:00Z",
    domainLeaderboard: [],
    recommendations: [
      {
        key: "metadataCoverage",
        title: "Improve Finance metadata coverage",
        detail: "Finance has 55% average metadata coverage across 2 assets.",
        evidence: [{ type: "domain", id: "Finance", metric: "metadataCoverage", value: 55 }],
      },
      {
        key: "assetsWithoutOwner",
        title: "Assign stewardship for Finance",
        detail: "Finance has 17 assets without an owner.",
        evidence: [{ type: "domain", id: "Finance", metric: "assetsWithoutOwner", value: 17 }],
      },
    ],
    scoring: { maturityFormula: [], availableSignals: [] },
    signalAvailability: {},
    meta: { state: "available", warnings: [] },
    ...overrides,
  };
}

/* ---------------------------------------------------------------- harness */

function renderPage() {
  return render(
    <QueryClientProvider client={axiomQueryClient}>
      <MemoryRouter initialEntries={["/home"]}>
        <HomePage />
        <ToastHost />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function primeHappyPath() {
  api.fetchCommandCenter.mockResolvedValue(commandCenterFixture());
  api.fetchInsightsDashboard.mockResolvedValue(insightsFixture());
}

async function settled() {
  await waitFor(() => expect(screen.getByText("What changed today")).toBeTruthy());
}

function linkByText(text) {
  const node = screen.getByText(text);
  const anchor = node.closest("a");
  expect(anchor, `expected "${text}" to be inside a real <a> anchor`).toBeTruthy();
  return anchor;
}

beforeEach(() => {
  api.fetchCommandCenter.mockReset();
  api.fetchInsightsDashboard.mockReset();
  axiomQueryClient.clear();
  __resetCommandCenterRetention();
  toast.clear();
});

/* ------------------------------------------------------------------ tests */

describe("Command Center (surfaces/home)", () => {
  it("renders skeletons while loading — never definitive zeros", () => {
    api.fetchCommandCenter.mockReturnValue(new Promise(() => {}));
    api.fetchInsightsDashboard.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByLabelText("Loading the command center")).toBeTruthy();
    // No fabricated values while the payload is in flight.
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText("No changes today")).toBeNull();
  });

  it("renders every KPI as a real anchor into its evidence surface", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    const kpiRow = screen.getByLabelText("Governance summary metrics");
    expect(within(kpiRow).getByText("Metadata coverage").closest("a").getAttribute("href")).toBe(
      "/discovery?sort=Governance+score",
    );
    expect(within(kpiRow).getByText("Certified critical assets").closest("a").getAttribute("href")).toBe(
      "/discovery?views=Certified",
    );
    expect(within(kpiRow).getByText("Open change requests").closest("a").getAttribute("href")).toBe(
      "/stewardship",
    );
    // Risk drills land on the Evidence quality tab (C5 route contract),
    // never on another dashboard tile.
    expect(within(kpiRow).getByText("High-risk quality findings").closest("a").getAttribute("href")).toBe(
      "/evidence?tab=quality&severity=high&outcome=failing&range=all",
    );
    // Formula tips come from the payload.
    expect(
      within(kpiRow).getByLabelText(
        "Weighted coverage of required governance metadata fields across visible assets.",
      ),
    ).toBeTruthy();
  });

  it("titles the hero for the estate and wires hero tiles + payload CDE subtitle", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    expect(screen.getByText(/The state of the data estate/i)).toBeTruthy();
    expect(screen.queryByText(/The state of finance_prod/i)).toBeNull();
    // CDE subtitle comes from the payload — never fabricated registry copy.
    expect(screen.getByText("Criticality-derived")).toBeTruthy();
    expect(screen.queryByText("Tag-governed · lineage-backed")).toBeNull();
    expect(linkByText("CDEs tracked").getAttribute("href")).toBe("/glossary?tab=cdes");
    expect(linkByText("Policy exceptions").getAttribute("href")).toBe("/stewardship");
  });

  it("renders the collecting state instead of a synthetic trend line, with window toggles hidden", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    expect(screen.getByText(/Collecting since Jul 20/i)).toBeTruthy();
    expect(screen.getByText(/Daily snapshots recording/i)).toBeTruthy();
    expect(screen.getByText(/one snapshot per day/i)).toBeTruthy();
    // Week toggles are dead chrome over one snapshot (kill list §7.6).
    expect(screen.queryByRole("button", { name: "12w" })).toBeNull();
    expect(screen.queryByRole("button", { name: "26w" })).toBeNull();
  });

  it("shows the honest no-changes state with the quality evidence date", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    // The fixture has no previous snapshot values, so nothing actually
    // changed today — zero-delta rows must not masquerade as movement.
    expect(screen.getByText("No changes today")).toBeTruthy();
    expect(screen.getByText(/Latest quality evidence from May 3/i)).toBeTruthy();
  });

  it("drills domains and catalogs into filtered Discovery via EntityChip anchors", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    // Scope to the domain card ("Risk" is also a catalog-table column header).
    const domainCard = screen.getByText("Posture by domain").closest("section");
    const domainHref = within(domainCard).getByText("Risk").closest("a").getAttribute("href");
    expect(domainHref.startsWith("/discovery?filters=")).toBe(true);
    expect(decodeURIComponent(domainHref)).toContain('"domains":["Risk"]');

    const catalogHref = linkByText("customer_360").getAttribute("href");
    expect(decodeURIComponent(catalogHref)).toContain('"catalogs":["customer_360"]');
    const labels = within(domainCard)
      .getAllByRole("link")
      .map((node) => node.textContent);
    expect(labels[0]).toContain("Risk");
  });

  it("drills quality risk severities to the Evidence quality tab with payload labels", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    // Panel is titled from the payload label.
    expect(screen.getByText("Quality risk findings")).toBeTruthy();
    expect(screen.getByText(/Quality-run findings by severity · evidence from May 3/i)).toBeTruthy();
    expect(linkByText("High severity").getAttribute("href")).toBe(
      "/evidence?tab=quality&severity=high&outcome=failing&range=all",
    );
    expect(linkByText("Medium severity").getAttribute("href")).toBe(
      "/evidence?tab=quality&severity=medium&outcome=failing&range=all",
    );
    expect(linkByText("Informational").getAttribute("href")).toBe(
      "/evidence?tab=quality&severity=informational&outcome=failing&range=all",
    );
  });

  it("links governance requests, activity events, and CDEs to their canonical routes", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    expect(linkByText("Request certification review").getAttribute("href")).toBe(
      "/stewardship?item=GOV-11223344",
    );
    expect(linkByText("Certification updated").getAttribute("href")).toBe("/evidence?event=AUD-0A1B2C3D");
    expect(linkByText("revenue_daily").getAttribute("href")).toBe(
      "/glossary?tab=cdes&cde=finance_prod.curated.revenue_daily",
    );
    expect(linkByText("View all").getAttribute("href")).toBe("/glossary?tab=cdes");
  });

  it("absorbs the three backed Insights widgets with the risk evidence date", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    const band = screen.getByLabelText("Risk and quality");
    expect(within(band).getByText("Risk heatmap")).toBeTruthy();
    expect(within(band).getByText("Evidence from May 3, 2026 (UTC)")).toBeTruthy();
    expect(
      within(band).getByRole("table", { name: "Governance risk heatmap: impact by likelihood" }),
    ).toBeTruthy();
    expect(within(band).getByRole("table", { name: "Metadata coverage by domain" })).toBeTruthy();
    expect(within(band).getByText("Tier 1 - Business Critical")).toBeTruthy();
    expect(within(band).getByText("75%")).toBeTruthy();
    // Legend decodes the colour ramp (was an unlabelled grid before).
    expect(within(band).getByLabelText("Severity colour key")).toBeTruthy();
  });

  it("links risk & quality tiles to the assets behind the numbers", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    const band = screen.getByLabelText("Risk and quality");
    // Populated risk cell drills into Discovery scoped to the impact's
    // criticality facet (reproduces the counted assets, no empty page).
    const riskCell = within(band).getByRole("cell", { name: /Open Very High-impact assets/i });
    expect(riskCell.getAttribute("href")).toContain("/discovery");
    expect(riskCell.getAttribute("href")).toContain("criticality=Critical");
    // Cert tier row is a real drill into its assets.
    const tierLink = within(band).getByRole("link", { name: /Open Tier 1 - Business Critical assets/i });
    expect(tierLink.getAttribute("href")).toContain("criticality=Critical");
  });

  it("renders evidence-backed recommendations as cards and nothing when there are none", async () => {
    primeHappyPath();
    renderPage();
    await settled();
    expect(screen.getByText("Improve Finance metadata coverage").closest("a")).toBeTruthy();
  });

  it("routes an assign-stewardship recommendation to that domain's ownerless assets", async () => {
    primeHappyPath();
    renderPage();
    await settled();
    // The recommended ACTION is "assign an owner" — the link must land on the
    // ownerless assets to assign, not the bare Discovery list or work queue.
    const rec = screen.getByText("Assign stewardship for Finance").closest("a");
    expect(rec).toBeTruthy();
    const href = rec.getAttribute("href");
    expect(href).toContain("domain=Finance");
    expect(href).toContain("owner=__unassigned__");
    expect(within(rec).getByText(/Assign owners/i)).toBeTruthy();
  });

  it("renders no recommendation slots at all when none are evidence-backed", async () => {
    api.fetchCommandCenter.mockResolvedValue(commandCenterFixture());
    api.fetchInsightsDashboard.mockResolvedValue(insightsFixture({ recommendations: [] }));
    renderPage();
    await settled();
    await waitFor(() => expect(screen.getByText("Risk heatmap")).toBeTruthy());

    expect(screen.queryByText("Axiom AI recommendations")).toBeNull();
    expect(screen.queryByText(/No evidence-backed recommendation/i)).toBeNull();
    expect(screen.queryByText(/No additional evidence-backed recommendation/i)).toBeNull();
  });

  it("ships none of the killed chrome or banned vocabulary", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    // Kill list §7: Present mode, ROI tiles, unavailable-forever trends,
    // duplicate KPI grid names, jargon vocabulary.
    expect(screen.queryByText(/Present mode/i)).toBeNull();
    expect(screen.queryByText(/Governance ROI/i)).toBeNull();
    expect(screen.queryByText(/Policy Compliance Trend/i)).toBeNull();
    expect(screen.queryByText(/Time to Resolution/i)).toBeNull();
    expect(screen.queryByText(/Governance Maturity Score/i)).toBeNull();
    expect(screen.queryByText(/hydrating/i)).toBeNull();
    expect(screen.queryByText(/actor-visible/i)).toBeNull();
    expect(screen.queryByText(/actor-scoped/i)).toBeNull();
  });

  it("shows degraded warnings without wiping the page", async () => {
    api.fetchCommandCenter.mockResolvedValue(
      commandCenterFixture({
        meta: {
          state: "degraded",
          warnings: ["Lineage coverage is temporarily unavailable."],
          generatedAt: "2026-07-20T10:00:00Z",
        },
      }),
    );
    api.fetchInsightsDashboard.mockResolvedValue(insightsFixture());
    renderPage();
    await settled();

    expect(screen.getByText("Data availability is limited")).toBeTruthy();
    expect(screen.getByText(/Lineage coverage is temporarily unavailable/i)).toBeTruthy();
    expect(screen.getByText("Catalog health · worst coverage first")).toBeTruthy();
  });

  it("rejects sample payloads before rendering any value as evidence", async () => {
    api.fetchCommandCenter.mockResolvedValue(
      commandCenterFixture({
        meta: {
          source: "prototype-mock",
          warnings: ["not live Databricks evidence"],
        },
      }),
    );
    api.fetchInsightsDashboard.mockResolvedValue(insightsFixture());
    renderPage();

    await waitFor(() => expect(screen.getByText("Live evidence unavailable")).toBeTruthy());
    expect(screen.queryByText("1,247")).toBeNull();
    expect(screen.queryByText("Quality risk findings")).toBeNull();
  });

  it("surfaces a fetch error with retry without pretending data exists", async () => {
    api.fetchCommandCenter.mockRejectedValue(new Error("boom"));
    api.fetchInsightsDashboard.mockResolvedValue(insightsFixture());
    renderPage();

    await waitFor(() => expect(screen.getByText("Something went wrong")).toBeTruthy());
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("What changed today")).toBeNull();
  });

  it("exports a command-center brief and confirms via toast", async () => {
    primeHappyPath();
    const createObjectURL = vi.fn(() => "blob:command-center");
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    try {
      renderPage();
      await settled();
      fireEvent.click(screen.getByRole("button", { name: "Export brief" }));
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(await screen.findByText("Command Center brief export started.")).toBeTruthy();
    } finally {
      Object.defineProperty(URL, "createObjectURL", { configurable: true, value: originalCreate });
      Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: originalRevoke });
      clickSpy.mockRestore();
    }
  });
});
