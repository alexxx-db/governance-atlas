/*
 * Wave B1 shell tests — replaces the old App.test.jsx / AppFrame.test.jsx,
 * which asserted the dead architecture (13-branch switch, AppFrame props).
 * Covers: route generation from nav/routes.js, alias redirects via
 * resolveUrl, rail generation (incl. the contextual Asset 360 entry and the
 * admin gate), the my-work badge hydration contract, the unified palette,
 * the ?peek= drawer binding, and boot gating.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useBootstrapMock = vi.fn();
const useRuntimeStatusMock = vi.fn();
const useGovernanceSummaryMock = vi.fn();
const useInboxWorkMock = vi.fn();
const useCommandCenterMock = vi.fn();
const usePaletteSearchMock = vi.fn();

const homePageMock = vi.fn(() => <div data-testid="home-page" />);
const discoveryMock = vi.fn(() => <div data-testid="discovery-workspace" />);
const entityMock = vi.fn(() => <div data-testid="entity-workspace" />);
const lineageMock = vi.fn(() => <div data-testid="lineage-workspace" />);
const governanceMock = vi.fn(() => <div data-testid="governance-workspace" />);
const auditMock = vi.fn(() => <div data-testid="audit-workspace" />);
const glossaryMock = vi.fn(() => <div data-testid="glossary-page" />);
const adminMock = vi.fn(() => <div data-testid="admin-workspace" />);
const helpMock = vi.fn(() => <div data-testid="help-page" />);
// Wave-B2 contract: the peek panel receives {fqn, open, onClose} and owns
// its own drawer chrome.
const asset360DrawerMock = vi.fn(({ fqn, open }) =>
  open && fqn ? <div data-testid="asset360-drawer">{fqn}</div> : null,
);

vi.mock("../../hooks/useBootstrap", () => ({ useBootstrap: (...args) => useBootstrapMock(...args) }));
vi.mock("../../hooks/useRuntimeStatus", () => ({ useRuntimeStatus: (...args) => useRuntimeStatusMock(...args) }));
vi.mock("../../hooks/useGovernanceSummary", () => ({
  useGovernanceSummary: (...args) => useGovernanceSummaryMock(...args),
}));
vi.mock("../../hooks/useInboxWork", () => ({ useInboxWork: (...args) => useInboxWorkMock(...args) }));
vi.mock("../../hooks/useCommandCenter", () => ({ useCommandCenter: (...args) => useCommandCenterMock(...args) }));
vi.mock("../../hooks/usePaletteSearch", () => ({ usePaletteSearch: (...args) => usePaletteSearchMock(...args) }));
vi.mock("../../hooks/useAtlasAiConversation", () => ({
  useAtlasAiConversation: () => ({
    messages: [],
    loading: false,
    draft: "",
    setDraft: vi.fn(),
    ask: vi.fn(),
  }),
}));

// Wave C2: the Command Center lives at surfaces/home (components/HomePage
// was deleted with the legacy dashboard).
vi.mock("../../surfaces/home/HomePage.jsx", () => ({ default: (props) => homePageMock(props) }));
// Wave C1: Discover lives at surfaces/discovery (components/DiscoveryWorkspace
// was deleted with the legacy workspace).
vi.mock("../../surfaces/discovery/DiscoveryPage.jsx", () => ({ default: (props) => discoveryMock(props) }));
vi.mock("../../surfaces/asset/AssetHubPage.jsx", () => ({ default: (props) => entityMock(props) }));
// Wave-C7: the lineage surface is router-self-sufficient (reads the :fqn
// splat itself), so the mock echoes the splat to keep the route assertions.
vi.mock("../../surfaces/lineage/LineagePage.jsx", () => ({ default: (props) => lineageMock(props) }));
// Wave C3: Stewardship lives at surfaces/stewardship (components/
// GovernanceWorkspace and InboxPage were deleted with the queue merge).
vi.mock("../../surfaces/stewardship/StewardshipPage.jsx", () => ({ default: (props) => governanceMock(props) }));
// Wave C5: Evidence lives at surfaces/evidence (components/
// AuditBrowserWorkspace was deleted with the quality-findings merge).
vi.mock("../../surfaces/evidence/EvidencePage.jsx", () => ({ default: (props) => auditMock(props) }));
// Wave C4: Glossary & CDEs lives at surfaces/glossary (components/
// TaxonomyWorkspace and CdeWorkspace were deleted with the registry merge).
vi.mock("../../surfaces/glossary/GlossaryPage.jsx", () => ({ default: (props) => glossaryMock(props) }));
// Wave C6: Control Center lives at surfaces/admin (components/AdminWorkspace
// and CapabilityDashboard were deleted; /capabilities is its Diagnostics tab).
vi.mock("../../surfaces/admin/AdminPage.jsx", () => ({ default: (props) => adminMock(props) }));
// Follow-up 3: Help lives at surfaces/help on the system kit (components/
// HelpPage was deleted with the last legacy-shell consumers).
vi.mock("../../surfaces/help/HelpPage.jsx", () => ({ default: (props) => helpMock(props) }));
vi.mock("../../surfaces/asset/AssetPeekPanel.jsx", () => ({
  AssetPeekPanel: (props) => asset360DrawerMock(props),
  default: (props) => asset360DrawerMock(props),
}));
// Follow-up 3: the readiness surfaces moved into app-shell/ with the
// system-kit rebuild (they render pre-boot, so they never lived in surfaces/).
vi.mock("../WorkspaceSetupWizard.jsx", () => ({ default: () => <div data-testid="setup-wizard" /> }));
vi.mock("../WorkspaceDiagnosticsSurface.jsx", () => ({
  default: () => <div data-testid="diagnostics-surface" />,
}));

import App from "../../App";

let lastLocation = null;
function LocationProbe() {
  lastLocation = useLocation();
  return null;
}

const LIVE_BOOTSTRAP = {
  bootState: "live",
  shell: {
    userEmail: "skyler@entrada.ai",
    userName: "Skyler",
    role: "Admin",
    ai: { state: "available", provider: "genie" },
    environment: { label: "Dev" },
  },
  identity: { actorEmail: "skyler@entrada.ai", actorRole: "Admin" },
  assets: [{ fqn: "main.core.orders", name: "orders" }],
  discovery: {},
};

function primeHooks({
  bootstrap = LIVE_BOOTSTRAP,
  bootstrapLoading = false,
  bootstrapError = "",
  inboxLoading = false,
  badgeCount = 3,
  unreadCount = 2,
} = {}) {
  useBootstrapMock.mockReturnValue({
    loading: bootstrapLoading,
    shellOnly: false,
    error: bootstrapError,
    refreshError: "",
    data: bootstrapLoading || bootstrapError ? null : bootstrap,
    refresh: vi.fn(),
  });
  useRuntimeStatusMock.mockReturnValue({
    data: null,
    error: "",
    loading: false,
    refreshError: "",
    refreshing: false,
    refresh: vi.fn(),
  });
  useGovernanceSummaryMock.mockReturnValue({
    loading: false,
    refreshing: false,
    error: "",
    refreshError: "",
    data: { inbox: { state: "ready", unreadCount, items: [] } },
    refresh: vi.fn(),
  });
  useInboxWorkMock.mockReturnValue({
    openRequests: [],
    reviewTerms: [],
    badgeCount,
    loading: inboxLoading,
  });
  useCommandCenterMock.mockReturnValue({
    data: { estate: {}, recentAssets: [], insights: {}, meta: {} },
    loading: false,
    hydrating: false,
    hasLiveData: false,
    refreshing: false,
    error: "",
    refreshError: "",
    degraded: false,
    warnings: [],
    meta: null,
    refresh: vi.fn(),
    refreshActorScope: vi.fn(),
  });
  usePaletteSearchMock.mockReturnValue({
    assets: [],
    glossaryTerms: [],
    searching: false,
    searchError: "",
    resolvedQuery: "",
  });
}

function renderApp(initialEntry = "/home") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  lastLocation = null;
  window.sessionStorage.clear();
  window.localStorage.clear();
  primeHooks();
});

describe("AppShell routing", () => {
  it("renders the Command Center surface at /home", async () => {
    renderApp("/home");
    expect(await screen.findByTestId("home-page")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/home");
  });

  it("redirects every legacy alias to its canonical route", async () => {
    const cases = [
      ["/", "/home", "home-page"],
      ["/command-center", "/home", "home-page"],
      ["/insights", "/home", "home-page"],
      ["/discover", "/discovery", "discovery-workspace"],
      ["/governance", "/stewardship", "governance-workspace"],
      ["/sk", "/stewardship", "governance-workspace"],
      ["/audit", "/evidence", "audit-workspace"],
      ["/audit-evidence", "/evidence", "audit-workspace"],
      ["/taxonomy", "/glossary", "glossary-page"],
      ["/control-center", "/admin", "admin-workspace"],
    ];
    for (const [from, to, testId] of cases) {
      const view = renderApp(from);
      expect(await screen.findByTestId(testId)).toBeTruthy();
      expect(lastLocation.pathname).toBe(to);
      view.unmount();
    }
  });

  it("redirects /inbox to the stewardship queue scoped to my work", async () => {
    renderApp("/inbox");
    expect(await screen.findByTestId("governance-workspace")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/stewardship");
    expect(new URLSearchParams(lastLocation.search).get("assignee")).toBe("me");
  });

  it("redirects /cde to the glossary CDE tab", async () => {
    renderApp("/cde");
    expect(await screen.findByTestId("glossary-page")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/glossary");
    expect(new URLSearchParams(lastLocation.search).get("tab")).toBe("cdes");
  });

  it("redirects /capabilities to the Control Center diagnostics tab", async () => {
    renderApp("/capabilities");
    // Wave C6: the Control Center owns ?tab=diagnostics — one surface, one
    // mount; the standalone capability dashboard is gone.
    expect(await screen.findByTestId("admin-workspace")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/admin");
    expect(new URLSearchParams(lastLocation.search).get("tab")).toBe("diagnostics");
  });

  it("redirects legacy /entity/* deep links to /assets and mounts the hub with the decoded FQN", async () => {
    renderApp("/entity/main.core.orders");
    expect(await screen.findByTestId("entity-workspace")).toBeTruthy();
    // The rebuilt hub reads :fqn from the router itself — the URL, not a
    // drilled prop, is the contract now.
    expect(lastLocation.pathname).toBe("/assets/main.core.orders");
  });

  it("promotes transient /glossary?term= links to the durable term path", async () => {
    renderApp("/glossary?term=Churn%20Rate");
    expect(await screen.findByTestId("glossary-page")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/glossary/Churn%20Rate");
    // Wave C4: the sessionStorage/window-event pending-term handoff is dead —
    // the rebuilt surface reads the durable path itself.
    expect(window.sessionStorage.getItem("ga-pending-glossary-term")).toBeNull();
  });

  it("normalizes legacy discovery grammar into flat canonical params on /discovery", async () => {
    // Wave C1: ?filters=<JSON> + shortcut params rewrite (replace) into the
    // flat grammar the rebuilt surface reads via useSurfaceParams — the URL,
    // not drilled props, is the contract now.
    renderApp('/discovery?q=churn&domain=Customer&filters={"tiers":["Gold"]}&preview=main.core.orders');
    expect(await screen.findByTestId("discovery-workspace")).toBeTruthy();
    await waitFor(() => expect(new URLSearchParams(lastLocation.search).get("tier")).toBe("Gold"));
    const search = new URLSearchParams(lastLocation.search);
    expect(lastLocation.pathname).toBe("/discovery");
    expect(search.get("q")).toBe("churn");
    expect(search.getAll("domain")).toEqual(["Customer"]);
    expect(search.get("filters")).toBeNull();
    // ?preview= promotes to the addressable ?peek= drawer binding.
    expect(search.get("peek")).toBe("main.core.orders");
    expect(search.get("preview")).toBeNull();
  });

  it("routes bare /lineage to the picker and /lineage/<fqn> to the focused graph", async () => {
    // Wave-C7: LineagePage reads the :fqn splat itself (no initialAssetFqn
    // prop), so the shell contract is: both forms mount the lineage surface
    // at the canonical path, with the focus FQN preserved in the URL.
    const bare = renderApp("/lineage");
    expect(await screen.findByTestId("lineage-workspace")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/lineage");
    bare.unmount();
    renderApp("/lineage/main.core.orders");
    expect(await screen.findByTestId("lineage-workspace")).toBeTruthy();
    await waitFor(() => expect(lastLocation.pathname).toBe("/lineage/main.core.orders"));
  });

  it("falls back to /home for unknown paths", async () => {
    renderApp("/definitely-not-a-surface");
    expect(await screen.findByTestId("home-page")).toBeTruthy();
    expect(lastLocation.pathname).toBe("/home");
  });
});

describe("AppShell rail", () => {
  it("generates the rail from the route table sections", async () => {
    renderApp("/home");
    await screen.findByTestId("home-page");
    const nav = screen.getByLabelText("Primary modules");
    for (const label of [
      "Command Center",
      "Discover",
      "Stewardship",
      "Glossary & CDEs",
      "Lineage Atlas",
      "Evidence",
      "Control Center",
      "Help",
    ]) {
      expect(nav.textContent).toContain(label);
    }
  });

  it("hides the admin-gated Control Center entry for non-admin roles", async () => {
    primeHooks({
      bootstrap: {
        ...LIVE_BOOTSTRAP,
        shell: { ...LIVE_BOOTSTRAP.shell, role: "Data Steward" },
        identity: { actorEmail: "skyler@entrada.ai", actorRole: "Data Steward" },
      },
    });
    renderApp("/home");
    await screen.findByTestId("home-page");
    expect(screen.getByLabelText("Primary modules").textContent).not.toContain("Control Center");
  });

  it("shows the contextual Asset 360 entry when an asset is in context", async () => {
    renderApp("/assets/main.core.orders");
    await screen.findByTestId("entity-workspace");
    const entry = screen.getByLabelText("Primary modules").querySelector('a[href^="/assets/"]');
    expect(entry).toBeTruthy();
    expect(entry.textContent).toContain("Asset 360");
  });

  it("keeps a PERMANENT Asset 360 entry with no asset in context, targeting the picker", async () => {
    // Owner directive 1: Asset 360 is no longer hidden by default. With no
    // route/peek context and nothing remembered, the entry targets bare
    // /assets (the search-first picker) so it is never a dead end.
    renderApp("/home");
    await screen.findByTestId("home-page");
    const nav = screen.getByLabelText("Primary modules");
    expect(nav.textContent).toContain("Asset 360");
    const entry = [...nav.querySelectorAll("a")].find((a) => a.textContent.includes("Asset 360"));
    expect(entry).toBeTruthy();
    expect(entry.getAttribute("href")).toBe("/assets");
  });

  it("renders rail items as real anchors resolved from the route table", async () => {
    renderApp("/home");
    await screen.findByTestId("home-page");
    const nav = screen.getByLabelText("Primary modules");
    const hrefs = [...nav.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/discovery");
    expect(hrefs).toContain("/stewardship");
    expect(hrefs).toContain("/evidence");
  });
});

describe("my-work badge hydration contract", () => {
  it("shows no badge while inbox sources are loading (no definitive zeros)", async () => {
    primeHooks({ inboxLoading: true });
    renderApp("/home");
    await screen.findByTestId("home-page");
    expect(document.querySelector(".ga-side-nav-badge")).toBeNull();
  });

  it("shows unread + actionable work once both sources settle", async () => {
    primeHooks({ badgeCount: 3, unreadCount: 2 });
    renderApp("/home");
    await screen.findByTestId("home-page");
    expect(document.querySelector(".ga-side-nav-badge").textContent).toBe("5");
  });
});

describe("palette + drawers", () => {
  it("opens the unified palette on Cmd+K", async () => {
    renderApp("/home");
    await screen.findByTestId("home-page");
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByPlaceholderText("Search assets, glossary terms, owners…")).toBeTruthy();
  });

  it("opens the palette from the header search trigger", async () => {
    renderApp("/home");
    await screen.findByTestId("home-page");
    fireEvent.click(screen.getByLabelText("Search assets, glossary terms, and owners"));
    expect(await screen.findByPlaceholderText("Search assets, glossary terms, owners…")).toBeTruthy();
  });

  it("binds the asset preview drawer to ?peek=", async () => {
    renderApp("/home?peek=main.core.orders");
    expect(await screen.findByTestId("asset360-drawer")).toBeTruthy();
    expect(screen.getByTestId("asset360-drawer").textContent).toBe("main.core.orders");
  });
});

describe("boot gating", () => {
  it("renders the boot loading card before bootstrap resolves", async () => {
    primeHooks({ bootstrapLoading: true });
    renderApp("/home");
    expect(await screen.findByText("Preparing the workspace surface.")).toBeTruthy();
    expect(screen.queryByTestId("home-page")).toBeNull();
  });

  it("renders the unavailable card when bootstrap fails", async () => {
    primeHooks({ bootstrapError: "Bootstrap payload was unavailable." });
    renderApp("/home");
    expect(
      await screen.findByText("The live metadata workspace could not initialize."),
    ).toBeTruthy();
    expect(screen.queryByTestId("home-page")).toBeNull();
  });
});
