import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GlossaryPage from "../GlossaryPage";

/*
 * Wave-C4 contract tests for the rebuilt Glossary & CDEs surface. Ports the
 * meaningful assertions from the deleted TaxonomyWorkspace/CdeWorkspace
 * suites onto the new contract: durable /glossary/<termId> paths, ?tab=cdes
 * + ?cde= addressing, EntityChip anchors, hierarchy honesty, review flows,
 * and the working client-side CSV download.
 */

const api = vi.hoisted(() => ({
  fetchTaxonomyOverview: vi.fn(),
  fetchCdeDashboard: vi.fn(),
  fetchCdeDetail: vi.fn(),
  createGovernanceRequest: vi.fn(),
  updateAssetMetadata: vi.fn(),
  upsertGovernanceGlossaryTerm: vi.fn(),
  upsertGovernanceOwner: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

/* --------------------------------------------------------------- fixtures */

function term(termId, name, overrides = {}) {
  return {
    termId,
    term: name,
    definition: `${name} definition used by governed analytics.`,
    domain: "Finance",
    status: "approved",
    ownerEmail: "owner@shorecp.com",
    assetCount: 2,
    assetPreview: [
      {
        assetFqn: `finance_prod.curated.${termId.replaceAll("-", "_")}`,
        assetLabel: termId,
        assetType: "Delta Table",
        platform: "Unity Catalog",
      },
    ],
    ...overrides,
  };
}

// 21 governed terms — mirrors the live payload volume the legacy registry
// once truncated to 4 cards (ported G1 regression).
const manyTerms = [
  term("axiom-test-term", "Axiom Test Term", {
    status: "draft",
    assetCount: 0,
    assetPreview: [],
    domain: "Unassigned",
    definition: "Leftover test row.",
  }),
  term("net-revenue", "Net Revenue"),
  term("gross-revenue", "Gross Revenue"),
  term("discounts", "Discounts"),
  term("refunds", "Refunds"),
  ...Array.from({ length: 16 }, (_, index) =>
    term(`metric-${index + 1}`, `Metric ${String(index + 1).padStart(2, "0")}`, {
      domain: index % 2 ? "Customer" : "Finance",
    }),
  ),
];

function cdeItem(id, overrides = {}) {
  return {
    id,
    assetFqn: id,
    name: id.split(".").pop(),
    sourceColumn: `${id}.value`,
    domain: "Finance",
    owner: "finance-steward@shorecp.com",
    certification: "Certified",
    sourceBacked: true,
    recert: "90d",
    lastReview: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

const manyCdes = [
  cdeItem("main.finance.net_revenue_usd"),
  cdeItem("main.finance.order_total_usd"),
  cdeItem("main.finance.invoice_number", { certification: "", status: "Certification pending" }),
  cdeItem("main.finance.revenue_code", { sourceColumn: "", sourceBacked: false }),
  cdeItem("main.customer.customer_id", { domain: "Customer" }),
  cdeItem("main.customer.lifetime_value_usd", { domain: "Customer" }),
];

function overviewPayload(terms = manyTerms) {
  return { data: { glossaryTerms: terms, summary: { termCount: terms.length } }, meta: { state: "available", warnings: [] } };
}

function cdePayload(items = manyCdes, summary = {}) {
  return { data: { items, summary }, meta: { state: "available", warnings: [] } };
}

/* ---------------------------------------------------------------- harness */

let lastLocation = null;

function LocationProbe() {
  lastLocation = useLocation();
  return null;
}

/* Re-render helper: RTL cleanup() between multi-mount assertions. */
function cleanupRender() {
  cleanup();
}

function renderGlossary(initialPath = "/glossary") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationProbe />
        <Routes>
          <Route element={<GlossaryPage />} path="/glossary/*" />
          <Route element={<GlossaryPage />} path="/glossary" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function cards() {
  return await screen.findByLabelText("Glossary cards");
}

beforeEach(() => {
  lastLocation = null;
  api.fetchTaxonomyOverview.mockReset().mockResolvedValue(overviewPayload());
  api.fetchCdeDashboard.mockReset().mockResolvedValue(cdePayload());
  api.fetchCdeDetail.mockReset().mockResolvedValue({ data: {}, meta: { state: "available" } });
  api.createGovernanceRequest.mockReset().mockResolvedValue({ ok: true, requestId: "GOV-11aa22bb" });
  api.updateAssetMetadata.mockReset().mockResolvedValue({ ok: true });
  api.upsertGovernanceGlossaryTerm.mockReset().mockResolvedValue({ ok: true, termId: "net-revenue" });
  api.upsertGovernanceOwner.mockReset().mockResolvedValue({ ok: true });
});

/* ------------------------------------------------------------------ tests */

describe("GlossaryPage — glossary tab", () => {
  it("renders every governed term with an accurate count and a working search", async () => {
    renderGlossary();

    const grid = await cards();
    expect(within(grid).getAllByRole("heading").length).toBe(manyTerms.length);
    expect(
      screen.getByText(`Showing ${manyTerms.length} of ${manyTerms.length} governed glossary terms`),
    ).toBeDefined();

    fireEvent.change(screen.getByLabelText("Search glossary terms"), {
      target: { value: "gross revenue" },
    });
    const filtered = screen.getByLabelText("Glossary cards");
    expect(within(filtered).getAllByRole("heading").length).toBe(1);
    expect(within(filtered).getByRole("heading", { name: "Gross Revenue" })).toBeDefined();
    // The search rides in the URL — refresh/share restores it.
    expect(lastLocation.search).toContain("q=gross+revenue");
  });

  it("keeps leftover draft test rows out of the lead card slot", async () => {
    renderGlossary();

    const grid = await cards();
    const headings = within(grid).getAllByRole("heading").map((node) => node.textContent);
    expect(headings[0]).toBe("Net Revenue");
    expect(headings[headings.length - 1]).toBe("Axiom Test Term");
  });

  it("term mentions are real anchors and card selection navigates to the durable path", async () => {
    renderGlossary();

    const grid = await cards();
    const chip = within(grid).getByRole("link", { name: /Net Revenue/ });
    expect(chip.getAttribute("href")).toBe("/glossary/net-revenue");

    fireEvent.click(within(grid).getByRole("heading", { name: "Gross Revenue" }).closest("article"));
    expect(lastLocation.pathname).toBe("/glossary/gross-revenue");
    expect(screen.getByLabelText("Gross Revenue detail")).toBeDefined();
  });

  it("resolves /glossary/<termId> deep links by id and by display name", async () => {
    renderGlossary("/glossary/net-revenue");
    expect(await screen.findByLabelText("Net Revenue detail")).toBeDefined();

    cleanupRender();
    renderGlossary("/glossary/Net%20Revenue");
    expect(await screen.findByLabelText("Net Revenue detail")).toBeDefined();
  });

  it("shows an honest not-found banner for unknown term paths", async () => {
    renderGlossary("/glossary/no-such-term");
    expect(await screen.findByText(/No glossary term matching “no-such-term”/)).toBeDefined();
  });

  it("a hydrating envelope renders skeletons and never a definitive zero count", async () => {
    api.fetchTaxonomyOverview.mockResolvedValue({
      data: { glossaryTerms: [], summary: { termCount: 0 } },
      meta: { state: "loading", capabilities: { hydrating: true }, warnings: [] },
    });
    renderGlossary();

    expect(await screen.findByLabelText("Loading glossary terms")).toBeDefined();
    expect(screen.getByText("Loading governed glossary terms…")).toBeDefined();
    expect(screen.queryByText(/Showing 0 of 0/)).toBeNull();
  });

  it("a genuinely empty glossary shows an honest empty state", async () => {
    api.fetchTaxonomyOverview.mockResolvedValue(overviewPayload([]));
    renderGlossary();
    expect(await screen.findByText("No glossary terms yet")).toBeDefined();
  });
});

describe("GlossaryPage — term mini-hub", () => {
  it("renders definition/status, linked-asset anchors, and pending-review work-item link in hub order", async () => {
    api.fetchTaxonomyOverview.mockResolvedValue(
      overviewPayload([
        term("net-revenue", "Net Revenue", {
          status: "proposed",
          recentRequests: [
            {
              requestId: "GOV-77ee88ff",
              title: "Approve Net Revenue definition",
              status: "pending",
              createdAt: "2026-07-10T00:00:00Z",
            },
          ],
        }),
      ]),
    );
    renderGlossary("/glossary/net-revenue");

    const detail = await screen.findByLabelText("Net Revenue detail");
    expect(within(detail).getByText("Net Revenue definition used by governed analytics.")).toBeDefined();
    expect(within(detail).getByText("Proposed")).toBeDefined();

    // Linked assets are real anchors to the Asset 360 hub.
    const assetChip = within(detail).getByRole("link", {
      name: /finance_prod\.curated\.net_revenue/,
    });
    expect(assetChip.getAttribute("href")).toContain("/assets/finance_prod.curated.net_revenue");

    // Pending review links the stewardship work item by its GOV id.
    const reviewChip = within(detail).getByRole("link", { name: /GOV-77ee88ff/ });
    expect(reviewChip.getAttribute("href")).toBe("/stewardship?item=GOV-77ee88ff");
  });

  it("hierarchy is real only: resolved parents link, taxonomy-node ids humanize, raw ids never render", async () => {
    api.fetchTaxonomyOverview.mockResolvedValue(
      overviewPayload([
        term("parent-term", "Revenue"),
        term("child-term", "Adjusted Revenue", { parentTermId: "parent-term" }),
        term("orphan-term", "Deferred Revenue", { parentTermId: "ax-taxonomy-node-revenue" }),
      ]),
    );
    renderGlossary("/glossary/child-term");

    let detail = await screen.findByLabelText("Adjusted Revenue detail");
    let hierarchy = within(detail).getByRole("heading", { name: "Hierarchy" }).closest("section");
    const parentLink = within(hierarchy).getByRole("link", { name: /Revenue/ });
    expect(parentLink.getAttribute("href")).toBe("/glossary/parent-term");

    // Parent card lists its child as a link too.
    fireEvent.click(parentLink);
    detail = await screen.findByLabelText("Revenue detail");
    hierarchy = within(detail).getByRole("heading", { name: "Hierarchy" }).closest("section");
    expect(within(hierarchy).getByRole("link", { name: /Adjusted Revenue/ })).toBeDefined();

    cleanupRender();
    renderGlossary("/glossary/orphan-term");
    detail = await screen.findByLabelText("Deferred Revenue detail");
    hierarchy = within(detail).getByRole("heading", { name: "Hierarchy" }).closest("section");
    expect(within(hierarchy).getByText("Revenue")).toBeDefined();
    expect(within(hierarchy).queryByText("ax-taxonomy-node-revenue")).toBeNull();
  });

  it("assigns a reviewer through the governed glossary upsert", async () => {
    renderGlossary("/glossary/net-revenue");
    const detail = await screen.findByLabelText("Net Revenue detail");

    fireEvent.click(within(detail).getByRole("button", { name: "Assign reviewer" }));
    const form = within(detail).getByRole("form", { name: /Assign reviewer to/ });
    fireEvent.change(within(form).getByLabelText("Reviewer email"), {
      target: { value: "reviewer@shorecp.com" },
    });
    fireEvent.submit(form);
    await waitFor(() => {
      expect(api.upsertGovernanceGlossaryTerm).toHaveBeenCalledWith(
        expect.objectContaining({
          termId: "net-revenue",
          name: "Net Revenue",
          reviewers: expect.arrayContaining([
            expect.objectContaining({ email: "reviewer@shorecp.com" }),
          ]),
        }),
      );
    });
  });

  it("closing the detail returns to the bare glossary route", async () => {
    renderGlossary("/glossary/net-revenue");
    const detail = await screen.findByLabelText("Net Revenue detail");
    fireEvent.click(within(detail).getByRole("button", { name: "Close Net Revenue detail" }));
    expect(lastLocation.pathname).toBe("/glossary");
  });
});

describe("GlossaryPage — term create/edit modals", () => {
  it("creates a draft term through the glossary upsert and surfaces failures as styled errors", async () => {
    renderGlossary();
    await cards();

    fireEvent.click(screen.getByRole("button", { name: "+ New term" }));
    const dialog = await screen.findByRole("dialog", { name: "New glossary term" });

    api.upsertGovernanceGlossaryTerm.mockRejectedValueOnce(new Error("Store write rejected."));
    fireEvent.change(within(dialog).getByLabelText(/Term name/), {
      target: { value: "Churn Rate" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create term" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Store write rejected.");

    api.upsertGovernanceGlossaryTerm.mockResolvedValueOnce({ ok: true, termId: "churn-rate" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create term" }));
    await waitFor(() => {
      expect(api.upsertGovernanceGlossaryTerm).toHaveBeenLastCalledWith(
        expect.objectContaining({ termId: "", name: "Churn Rate", status: "draft" }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "New glossary term" })).toBeNull();
    });
  });

  it("edit replays the term through the upsert with its termId", async () => {
    renderGlossary("/glossary/net-revenue");
    const detail = await screen.findByLabelText("Net Revenue detail");

    fireEvent.click(within(detail).getByRole("button", { name: "Edit term" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit glossary term" });
    fireEvent.change(within(dialog).getByLabelText("Definition"), {
      target: { value: "Updated definition." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save term" }));
    await waitFor(() => {
      expect(api.upsertGovernanceGlossaryTerm).toHaveBeenCalledWith(
        expect.objectContaining({
          termId: "net-revenue",
          name: "Net Revenue",
          definition: "Updated definition.",
        }),
      );
    });
  });
});

describe("GlossaryPage — CDE registry tab", () => {
  it("renders registry rows with honest Not tagged sources, certification labels, and asset anchors", async () => {
    renderGlossary("/glossary?tab=cdes");

    const table = await screen.findByRole("table", { name: "CDE registry" });
    expect(await within(table).findByText("Net Revenue (USD)")).toBeDefined();
    expect(screen.getByText(`Showing ${manyCdes.length} of ${manyCdes.length} CDE registry rows`)).toBeDefined();

    // Untagged sources: honest state in the cell, remediation in the tooltip.
    const untagged = within(table).getByText("Not tagged");
    expect(untagged.getAttribute("title") || "").toMatch(/tag cde_source_column/i);
    expect(within(table).getAllByText("Certified").length).toBeGreaterThan(0);
    expect(within(table).getByText("Certification Pending")).toBeDefined();

    // The name column is a real anchor to the canonical CDE address.
    const rowLink = within(table).getByRole("link", { name: /Net Revenue \(USD\)/ });
    expect(rowLink.getAttribute("href")).toBe("/glossary?tab=cdes&cde=main.finance.net_revenue_usd");

    // Source assets are anchors into the hub.
    const assetLink = within(table).getAllByRole("link", { name: "main.customer.customer_id" })[0];
    expect(assetLink.getAttribute("href")).toContain("/assets/main.customer.customer_id");
  });

  it("filters by domain through the URL-backed filter bar", async () => {
    renderGlossary("/glossary?tab=cdes");
    const table = await screen.findByRole("table", { name: "CDE registry" });
    await within(table).findByText("Net Revenue (USD)");

    fireEvent.change(screen.getByLabelText("Domain"), { target: { value: "Customer" } });
    expect(screen.getByText(`Showing 2 of ${manyCdes.length} CDE registry rows`)).toBeDefined();
    expect(lastLocation.search).toContain("domain=Customer");
  });

  it("?cde= selects the detail panel and its actions route through governance APIs", async () => {
    renderGlossary("/glossary?tab=cdes&cde=main.finance.net_revenue_usd");

    const detail = await screen.findByLabelText("Net Revenue (USD) detail", {}, { timeout: 5000 });
    expect(within(detail).getByText("main.finance.net_revenue_usd.value")).toBeDefined();

    fireEvent.click(within(detail).getByRole("button", { name: "Request recertification" }));
    await waitFor(() => {
      expect(api.createGovernanceRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          assetFqn: "main.finance.net_revenue_usd",
          title: expect.stringContaining("Recertification requested"),
        }),
        { fast: true },
      );
    });

    fireEvent.click(within(detail).getByRole("button", { name: "Assign owner" }));
    const form = within(detail).getByRole("form", { name: /Assign owner for/ });
    fireEvent.change(within(form).getByLabelText("Owner email"), {
      target: { value: "new-owner@shorecp.com" },
    });
    fireEvent.submit(form);
    await waitFor(() => {
      expect(api.upsertGovernanceOwner).toHaveBeenCalledWith({
        assetFqn: "main.finance.net_revenue_usd",
        ownerEmail: "new-owner@shorecp.com",
        ownerType: "steward",
      });
    });
  });

  it("downloads the visible registry rows as a client-built CSV", async () => {
    const objectUrls = [];
    URL.createObjectURL = vi.fn((blob) => {
      objectUrls.push(blob);
      return "blob:mock-csv";
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderGlossary("/glossary?tab=cdes");
    const table = await screen.findByRole("table", { name: "CDE registry" });
    await within(table).findByText("Net Revenue (USD)");

    const download = screen.getByRole("button", { name: "Download CSV" });
    expect(download.disabled).toBe(false);
    fireEvent.click(download);

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    // jsdom's Blob lacks .text(); FileReader is the supported read path.
    const csvText = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(objectUrls[0]);
    });
    expect(csvText.split("\n").length).toBe(manyCdes.length + 1);
    expect(csvText).toContain("name,source_of_record_column,source_asset_fqn");
    expect(csvText).toContain("Net Revenue (USD)");
    expect(csvText).toContain("Not tagged");
    click.mockRestore();
  });

  it("flags a new CDE through the asset-metadata PATCH path with FQN validation", async () => {
    renderGlossary("/glossary?tab=cdes");
    await screen.findByRole("table", { name: "CDE registry" });

    fireEvent.click(screen.getByRole("button", { name: "+ New CDE" }));
    const dialog = await screen.findByRole("dialog", { name: "Flag asset as CDE" });

    fireEvent.change(within(dialog).getByLabelText(/Asset FQN/), { target: { value: "not-an-fqn" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Flag as CDE" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(/catalog\.schema\.table/);
    expect(api.updateAssetMetadata).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText(/Asset FQN/), {
      target: { value: "main.finance.new_cde_table" },
    });
    fireEvent.change(within(dialog).getByLabelText("Rationale"), {
      target: { value: "Feeds the revenue close." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Flag as CDE" }));
    await waitFor(() => {
      expect(api.updateAssetMetadata).toHaveBeenCalledWith("main.finance.new_cde_table", {
        isCde: true,
        cdeRationale: "Feeds the revenue close.",
      });
    });
  });

  it("a hydrating CDE envelope renders skeleton rows, an empty registry renders an honest empty state", async () => {
    api.fetchCdeDashboard.mockResolvedValue({
      data: { items: [] },
      meta: { state: "loading", capabilities: { hydrating: true }, warnings: [] },
    });
    api.fetchTaxonomyOverview.mockResolvedValue(overviewPayload([]));
    renderGlossary("/glossary?tab=cdes");
    expect(await screen.findByText("Loading the CDE registry…")).toBeDefined();

    cleanupRender();
    api.fetchCdeDashboard.mockResolvedValue(cdePayload([]));
    renderGlossary("/glossary?tab=cdes");
    expect(await screen.findByText("No Critical Data Elements yet")).toBeDefined();
  });
});

describe("GlossaryPage — tab routing", () => {
  it("switching tabs from a term path drops the termId and lands on ?tab=cdes", async () => {
    renderGlossary("/glossary/net-revenue");
    await screen.findByLabelText("Net Revenue detail");

    fireEvent.click(screen.getByRole("tab", { name: /CDE Registry/ }));
    expect(lastLocation.pathname).toBe("/glossary");
    expect(lastLocation.search).toContain("tab=cdes");
    expect(await screen.findByRole("table", { name: "CDE registry" })).toBeDefined();
  });

  it("tab flips on the bare route write ?tab= as replace-style sub-state", async () => {
    renderGlossary();
    await cards();

    fireEvent.click(screen.getByRole("tab", { name: /CDE Registry/ }));
    expect(lastLocation.search).toContain("tab=cdes");
    fireEvent.click(screen.getByRole("tab", { name: /Glossary/ }));
    expect(lastLocation.search).not.toContain("tab=cdes");
  });
});
