/*
 * DiscoveryPage behavioral tests (Wave C1) — the ported intents from the
 * legacy DiscoveryWorkspace suites, rewritten against the system-layer DOM:
 * search → URL, filters → URL, preview → ?peek=, deep links, empty-state
 * honesty (no-matches / didYouMean / diagnostics), invalid queries, saved
 * searches + favorites via lib/prefs (with gh-* migration), Atlas AI
 * authority rules, and facet-bucket honesty (Show all / zero-count hiding).
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const resultsMock = vi.fn();
const aiMock = vi.hoisted(() => ({ fetchAtlasAiRecommendations: vi.fn() }));

vi.mock("../../../hooks/useDiscoveryResults", () => ({
  useDiscoveryResults: (...args) => resultsMock(...args),
}));

vi.mock("../../../lib/api", () => ({
  fetchAtlasAiRecommendations: (...args) => aiMock.fetchAtlasAiRecommendations(...args),
}));

import { readFavoriteAssets, readRecentAssets } from "../../../lib/prefs";
import DiscoveryPage from "../DiscoveryPage";

/* ---- storage stubs (vitest ships no web storage) ---------------------- */
function storageStub() {
  let map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    clear: () => {
      map = new Map();
    },
  };
}

/* ---- fixtures --------------------------------------------------------- */
const orders = {
  fqn: "main.sales.orders",
  name: "orders",
  description: "Orders fact table",
  coverageScore: 88,
  owners: [{ name: "Skyler Myers", email: "skyler@entrada.ai" }],
  domain: "Finance",
  tier: "Gold",
  certification: "Certified",
  sensitivity: "Confidential",
  governanceStatus: "Published",
};

const churn = {
  fqn: "main.cust.churn",
  name: "churn",
  description: "",
  coverageScore: null,
  owners: [],
  domain: "Unassigned",
  tier: "",
  certification: "",
  sensitivity: "",
};

function bootstrapPayload() {
  return {
    bootState: "live",
    shell: { userEmail: "skyler@entrada.ai" },
    identity: { authMode: "obo-available", visibilityScope: "actor" },
    discovery: {
      sortOptions: ["Best match", "Coverage score"],
      views: ["All assets", "Certified", "Needs owner", "Needs certification", "High coverage"],
      defaultFacets: {},
    },
  };
}

function resultsState(overrides = {}) {
  const assets = overrides.assets ?? [orders, churn];
  return {
    loading: false,
    error: "",
    assets,
    count: assets.length,
    facets: {
      domains: [
        { value: "Finance", count: 1 },
        { value: "Unassigned", count: 1 },
      ],
      certifications: [
        { value: "Certified", count: 1 },
        { value: "In Review", count: 0 },
      ],
      assetTypes: [{ value: "Delta Table", count: 2 }],
    },
    queryState: null,
    meta: null,
    refreshActorScope: vi.fn(),
    refreshing: false,
    requestKey: "scope-1",
    fetching: false,
    fetchLimit: 80,
    settled: true,
    authoritative: true,
    ...overrides,
  };
}

let lastLocation = null;
function LocationProbe() {
  lastLocation = useLocation();
  return null;
}

function renderPage(initialUrl = "/discovery", props = {}) {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <LocationProbe />
      <DiscoveryPage
        atlasAiAvailable
        atlasAiUnavailableReason=""
        bootMessage=""
        bootState="live"
        bootstrap={bootstrapPayload()}
        {...props}
      />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  resultsMock.mockReset();
  resultsMock.mockImplementation(() => resultsState());
  aiMock.fetchAtlasAiRecommendations.mockReset();
  aiMock.fetchAtlasAiRecommendations.mockResolvedValue({ recommendations: [] });
  lastLocation = null;
  Object.defineProperty(window, "localStorage", {
    value: storageStub(),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "sessionStorage", {
    value: storageStub(),
    configurable: true,
    writable: true,
  });
});

/* ---- search + URL state ---------------------------------------------- */

describe("DiscoveryPage — URL is the state", () => {
  it("seeds the search request from flat URL params", () => {
    renderPage("/discovery?q=churn&domain=Finance&tier=Gold&cde=1&sort=Coverage%20score");
    const filters = resultsMock.mock.calls.at(-1)[0];
    expect(filters.query).toBe("churn");
    expect(filters.domains).toEqual(["Finance"]);
    expect(filters.tiers).toEqual(["Gold"]);
    expect(filters.cdeOnly).toBe(true);
    expect(filters.sortBy).toBe("Coverage score");
  });

  it("debounces the search box into ?q=", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Search discovery assets"), {
      target: { value: "revenue" },
    });
    await waitFor(() =>
      expect(new URLSearchParams(lastLocation.search).get("q")).toBe("revenue"),
    );
  });

  it("writes facet selections from the FilterBar into flat params", () => {
    renderPage();
    const filterBar = screen.getByRole("group", { name: "Discovery filters" });
    fireEvent.click(within(filterBar).getByRole("button", { name: "Domain" }));
    fireEvent.click(within(filterBar).getByLabelText(/^Finance/));
    expect(new URLSearchParams(lastLocation.search).getAll("domain")).toEqual(["Finance"]);
  });

  it("removes an applied filter from its chip and resets the whole scope", () => {
    renderPage("/discovery?domain=Finance&tier=Gold&q=revenue");
    fireEvent.click(screen.getByRole("button", { name: "Clear Domain: Finance" }));
    expect(new URLSearchParams(lastLocation.search).getAll("domain")).toEqual([]);
    expect(new URLSearchParams(lastLocation.search).getAll("tier")).toEqual(["Gold"]);
    fireEvent.click(screen.getByRole("button", { name: "Reset browse" }));
    expect(lastLocation.search).toBe("");
  });

  it("offers sort options from the bootstrap with Best match rendered as Relevance", () => {
    renderPage();
    const sortSelect = screen.getByLabelText("Sort results");
    const labels = [...sortSelect.querySelectorAll("option")].map((option) => option.textContent);
    expect(labels).toEqual(["Relevance", "Coverage score"]);
    fireEvent.change(sortSelect, { target: { value: "Coverage score" } });
    expect(new URLSearchParams(lastLocation.search).get("sort")).toBe("Coverage score");
  });
});

/* ---- results + preview ------------------------------------------------ */

describe("DiscoveryPage — results and preview", () => {
  it("renders asset names as real anchors to the Asset 360 hub", () => {
    const { container } = renderPage();
    const rowLink = container.querySelector("a.ga-sys-table-rowlink");
    expect(rowLink).not.toBeNull();
    expect(rowLink.getAttribute("href")).toContain("/assets/main.sales.orders");
  });

  it("opens the ?peek= preview drawer on plain left-click and records the recent", () => {
    const { container } = renderPage();
    fireEvent.click(container.querySelector("a.ga-sys-table-rowlink"));
    expect(new URLSearchParams(lastLocation.search).get("peek")).toBe("main.sales.orders");
    expect(readRecentAssets()).toContain("main.sales.orders");
  });

  it("renders labeled fallbacks, never bare em-dashes, in sparse cells", () => {
    renderPage();
    expect(screen.getAllByText("Not certified").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unclassified").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unscored").length).toBeGreaterThan(0);
  });

  it("labels the per-asset governance_score as Gov. score, never Trust or Metadata coverage", () => {
    // Audit B3: this per-asset field is the weighted governance_score
    // (AssetTrustHero calls it "Governance score"); it must NOT reuse the
    // estate "Metadata coverage" label (a different formula) or "Trust".
    renderPage();
    expect(screen.getByRole("columnheader", { name: "Gov. score" })).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: /Trust/i })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /Metadata coverage/i })).toBeNull();
  });

  it("never claims No recent usage when the payload carries no usage fields", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Grid view" }));
    expect(screen.queryByText("No recent usage")).toBeNull();
  });

  it("floats favorites to the top and persists them through prefs", () => {
    const { container } = renderPage();
    const rows = () => [...container.querySelectorAll("tbody tr")];
    expect(rows()[0].textContent).toContain("orders");
    const churnRow = rows()[1];
    fireEvent.click(within(churnRow).getByRole("button", { name: "Add local favorite" }));
    expect(readFavoriteAssets()).toEqual(["main.cust.churn"]);
    expect(rows()[0].textContent).toContain("churn");
  });
});

/* ---- empty states + diagnostics --------------------------------------- */

describe("DiscoveryPage — empty-state honesty", () => {
  it("says No matches for the query (never blames unset filters) and offers didYouMean", () => {
    resultsMock.mockImplementation(() =>
      resultsState({ assets: [], count: 0, meta: { didYouMean: "revenue" } }),
    );
    renderPage("/discovery?q=revenu");
    expect(screen.getByText("No matches for “revenu”")).toBeTruthy();
    expect(screen.queryByText(/Relax the current search/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Search instead for “revenue”/ }));
    expect(new URLSearchParams(lastLocation.search).get("q")).toBe("revenue");
  });

  it("renders the humanized diagnostics strip on the inventory-empty state", () => {
    resultsMock.mockImplementation(() =>
      resultsState({
        assets: [],
        count: 0,
        authoritative: false,
        meta: {
          authMode: "obo-available",
          source: "unity-catalog",
          visibleAssetCount: 0,
          observedAt: "2026-07-21T10:00:00Z",
          discoveryState: "no_visible_assets",
        },
      }),
    );
    renderPage("/discovery", { bootState: "degraded", bootMessage: "Principal sees no assets." });
    expect(screen.getByText("No visible assets are being returned.")).toBeTruthy();
    const strip = screen.getByTestId("ga-disc-diagnostics");
    expect(within(strip).getByTestId("ga-disc-diagnostics-runtime").textContent).toBe(
      "Partially available",
    );
    expect(within(strip).getByTestId("ga-disc-diagnostics-auth").textContent).toBe(
      "Permission-aware (your access)",
    );
    // Humanized state — never the raw enum.
    expect(within(strip).getByTestId("ga-disc-diagnostics-state").textContent).toBe(
      "No assets are visible to your account",
    );
  });

  it("does not render the diagnostics strip when results exist", () => {
    renderPage();
    expect(screen.queryByTestId("ga-disc-diagnostics")).toBeNull();
  });

  it("renders invalid queries as a dedicated invalid-search state", () => {
    resultsMock.mockImplementation(() =>
      resultsState({
        assets: [],
        count: 0,
        queryState: {
          state: "invalid",
          message: "Invalid discovery query.",
          syntaxHint: "Use AND, OR, parentheses.",
        },
      }),
    );
    renderPage("/discovery?q=%22broken");
    expect(screen.getByText("Invalid discovery query.")).toBeTruthy();
    expect(screen.getByText("Use AND, OR, parentheses.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear search" })).toBeTruthy();
  });
});

/* ---- facet rail honesty ----------------------------------------------- */

describe("DiscoveryPage — facet-bucket honesty", () => {
  it("hides zero-count certification options and shows facet-sum counts", () => {
    renderPage();
    const rail = screen.getByLabelText("Discovery quick facets");
    expect(within(rail).getByText("Certified")).toBeTruthy();
    expect(within(rail).queryByText("In Review")).toBeNull();
    expect(within(rail).getByText("1 results")).toBeTruthy();
  });

  it("caps domain buckets behind an explicit Show all expander (never silent truncation)", () => {
    const domains = [
      "Finance",
      "Sales",
      "Marketing",
      "Operations",
      "Risk",
      "Product",
      "Customer",
      "Unassigned",
    ].map((value, index) => ({ value, count: index + 1 }));
    resultsMock.mockImplementation(() => resultsState({ facets: { domains } }));
    renderPage();
    const rail = screen.getByLabelText("Discovery quick facets");
    expect(within(rail).getByText("Finance")).toBeTruthy();
    expect(within(rail).queryByText("Unassigned")).toBeNull();
    fireEvent.click(within(rail).getByRole("button", { name: "Show all 8" }));
    expect(within(rail).getByText("Unassigned")).toBeTruthy();
    expect(within(rail).getByRole("button", { name: "Show fewer" })).toBeTruthy();
  });
});

/* ---- saved searches + Atlas AI ---------------------------------------- */

describe("DiscoveryPage — saved searches (prefs-backed)", () => {
  it("migrates legacy gh-saved-searches and applies an entry into URL state", () => {
    window.localStorage.setItem(
      "gh-saved-searches",
      JSON.stringify([{ id: "s1", name: "Finance revenue", query: "revenue", domains: ["Finance"] }]),
    );
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Saved searches" }));
    const dialog = screen.getByRole("dialog", { name: "Saved searches" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Apply saved search Finance revenue" }),
    );
    const search = new URLSearchParams(lastLocation.search);
    expect(search.get("q")).toBe("revenue");
    expect(search.getAll("domain")).toEqual(["Finance"]);
  });

  it("saves and deletes the current scope locally", () => {
    renderPage("/discovery?q=revenue&domain=Finance");
    fireEvent.click(screen.getByRole("button", { name: "Saved searches" }));
    const dialog = screen.getByRole("dialog", { name: "Saved searches" });
    fireEvent.change(within(dialog).getByLabelText("Saved search name"), {
      target: { value: "Finance revenue" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save current search" }));
    const stored = JSON.parse(window.localStorage.getItem("ga.prefs.savedSearches"));
    expect(stored).toHaveLength(1);
    expect(stored[0].query).toBe("revenue");
    expect(stored[0].domains).toEqual(["Finance"]);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete saved search Finance revenue" }),
    );
    expect(JSON.parse(window.localStorage.getItem("ga.prefs.savedSearches"))).toHaveLength(0);
  });
});

describe("DiscoveryPage — Atlas AI recommendations", () => {
  it("runs recommendations on demand and renders evidence-backed results", async () => {
    aiMock.fetchAtlasAiRecommendations.mockResolvedValue({
      authoritative: true,
      state: "available",
      recommendations: [
        {
          title: "Certify orders",
          detail: "High usage, no certification.",
          evidence: [{ id: "main.sales.orders" }],
          provider: "genie",
        },
      ],
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Ask Atlas AI" }));
    expect(await screen.findByText("Certify orders")).toBeTruthy();
    expect(aiMock.fetchAtlasAiRecommendations).toHaveBeenCalledTimes(1);
  });

  it("rejects non-authoritative responses instead of rendering them", async () => {
    aiMock.fetchAtlasAiRecommendations.mockResolvedValue({
      nonAuthoritative: true,
      recommendations: [{ title: "Fake rec" }],
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Ask Atlas AI" }));
    expect(
      await screen.findByText(
        "Atlas AI recommendations unavailable until live evidence-backed provider returns results.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Fake rec")).toBeNull();
  });

  it("disables the ask button when no backed endpoint is available", () => {
    renderPage("/discovery", {
      atlasAiAvailable: false,
      atlasAiUnavailableReason: "No Genie endpoint configured.",
    });
    expect(screen.getByRole("button", { name: "Ask Atlas AI" }).disabled).toBe(true);
  });
});
