import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/*
 * surfaces/lineage/__tests__/LineagePage.test.jsx — Wave C7 port of the
 * meaningful LineageWorkspace.test.jsx contracts onto the rebuilt surface:
 * canvas mount, honest degraded/zero-edge/truncation states, the
 * select-vs-re-anchor contract (now URL-addressable via ?selected=), the
 * evidence-gating rules, plus the NEW bare-/lineage search-first picker and
 * ?context=/?selected= deep links. The legacy auto-redirect-to-top-
 * recommendation test was deliberately NOT ported: COHESION law makes bare
 * /lineage a deliberate picker, never a silent redirect.
 */

vi.mock("../../../hooks/useAssetDetail", () => ({ useAssetDetail: vi.fn() }));
vi.mock("../../../hooks/useAssetDatabricksEvidence", () => ({ useAssetDatabricksEvidence: vi.fn() }));
vi.mock("../../../hooks/useAssetQuality", () => ({ useAssetQuality: vi.fn() }));
vi.mock("../../../hooks/useAccessExplain", () => ({ useAccessExplain: vi.fn() }));
vi.mock("../../../hooks/useColumnLineageTrace", () => ({ useColumnLineageTrace: vi.fn() }));
vi.mock("../../../hooks/useLineageRecommendations", () => ({ useLineageRecommendations: vi.fn() }));
vi.mock("../../../hooks/usePaletteSearch", () => ({ usePaletteSearch: vi.fn() }));
vi.mock("../../../hooks/useSeededAssetContext", () => ({ useSeededAssetContext: vi.fn() }));
vi.mock("../../../lib/api", () => ({ createGovernanceRequest: vi.fn() }));
vi.mock("../../../components/lineage-v2/useLineageGraphV2", () => ({ useLineageGraphV2: vi.fn() }));
vi.mock("../../../components/lineage-v2/useLineageNodeHeaders", () => ({ useLineageNodeHeaders: vi.fn(() => ({ headers: {} })) }));
vi.mock("../../../components/lineage-v2/LineageCanvasV2", () => ({
  LineageCanvasV2: ({ focusId, onColumnSelect, onFocusChange, graph }) => (
    <div data-testid="canvas-v2">
      <span>focus={focusId}</span>
      <span>nodes={graph?.nodes?.length || 0}</span>
      <button data-testid="canvas-pick-upstream" onClick={() => onFocusChange("a.b.upstream")} type="button">
        click upstream
      </button>
      <button
        data-testid="canvas-pick-column"
        onClick={() => onColumnSelect?.({ fqn: focusId }, { name: "mortgage_amount", type: "DECIMAL" })}
        type="button"
      >
        click column
      </button>
    </div>
  ),
}));

import LineagePage from "../LineagePage.jsx";
import { useAssetDetail } from "../../../hooks/useAssetDetail";
import { useAssetDatabricksEvidence } from "../../../hooks/useAssetDatabricksEvidence";
import { useAssetQuality } from "../../../hooks/useAssetQuality";
import { useAccessExplain } from "../../../hooks/useAccessExplain";
import { useColumnLineageTrace } from "../../../hooks/useColumnLineageTrace";
import { useLineageRecommendations } from "../../../hooks/useLineageRecommendations";
import { usePaletteSearch } from "../../../hooks/usePaletteSearch";
import { useSeededAssetContext } from "../../../hooks/useSeededAssetContext";
import { createGovernanceRequest } from "../../../lib/api";
import { useLineageGraphV2 } from "../../../components/lineage-v2/useLineageGraphV2";

const baseBootstrap = {
  capabilities: { tableLineage: { available: true, state: "available" } },
  featureFlags: [{ key: "table_lineage_surface", enabled: true }],
};
const baseRuntimeFeatureFlags = [{ key: "table_lineage_surface", enabled: true }];
const baseWorkspaceAccess = { canUseLineage: true, mode: "obo-available" };

const emptyGraph = () => ({
  focus: null,
  nodes: [],
  edges: [],
  columnEdges: [],
  columnLineage: { upstream: [], downstream: [], meta: {} },
  edgeDetails: {},
  stats: {},
  payload: null,
  hydrating: false,
  warming: false,
  loading: false,
  error: "",
  meta: null,
  refresh: () => null,
});

const focusGraph = (overrides = {}) => ({
  ...emptyGraph(),
  focus: { id: "f", fqn: "a.b.focus", label: "focus", subtitle: "a / b" },
  nodes: [{ id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" }],
  payload: { source: "unity-catalog-lineage" },
  ...overrides,
});

const richRecommendations = () => ({
  loading: false,
  error: "",
  items: [
    {
      fqn: "a.b.rich",
      name: "rich",
      catalogName: "a",
      schemaName: "b",
      edgeCount: 12,
      upstreamCount: 5,
      downstreamCount: 7,
      source: "system.access.table_lineage",
    },
  ],
  meta: { source: "system.access.table_lineage" },
  envelopeMeta: { authoritative: true, visibilityScope: "actor-scoped" },
  authoritative: true,
  degraded: false,
  visibilityScope: "actor-scoped",
  relationshipVisibilityScope: "",
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

function renderLineage(initialEntry, props = {}) {
  const page = (
    <LineagePage
      bootstrap={baseBootstrap}
      runtimeFeatureFlags={baseRuntimeFeatureFlags}
      workspaceAccess={baseWorkspaceAccess}
      {...props}
    />
  );
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <Routes>
        <Route element={page} path="/lineage/*" />
        <Route element={page} path="/lineage" />
        <Route element={null} path="*" />
      </Routes>
    </MemoryRouter>,
  );
}

function probe() {
  return screen.getByTestId("location-probe").textContent;
}

beforeEach(() => {
  useAssetDetail.mockReset();
  useAssetDatabricksEvidence.mockReset();
  useAssetQuality.mockReset();
  useAccessExplain.mockReset();
  useColumnLineageTrace.mockReset();
  useLineageRecommendations.mockReset();
  usePaletteSearch.mockReset();
  useSeededAssetContext.mockReset();
  useLineageGraphV2.mockReset();
  createGovernanceRequest.mockReset();
  useAssetDetail.mockReturnValue({ detail: null, loading: false, error: "" });
  useAssetDatabricksEvidence.mockReturnValue({
    loading: false,
    error: "",
    available: false,
    qualityMonitoring: {},
    profileMetrics: {},
    lakeflow: {},
    pipelineEvents: {},
    provenance: [],
  });
  useAssetQuality.mockReturnValue({
    loading: false,
    error: "",
    runs: [],
    results: [],
    available: false,
    summaryBacked: false,
    summary: { passed: 0, failed: 0, errored: 0, skipped: 0 },
  });
  useAccessExplain.mockReturnValue({ loading: false, error: "", data: null });
  useColumnLineageTrace.mockReturnValue({
    loading: false,
    upstream: null,
    downstream: null,
    upstreamError: "",
    downstreamError: "",
  });
  useLineageRecommendations.mockReturnValue({
    loading: false,
    error: "",
    items: [],
    meta: null,
    envelopeMeta: null,
    authoritative: null,
    degraded: false,
    visibilityScope: "",
    relationshipVisibilityScope: "",
  });
  usePaletteSearch.mockReturnValue({
    assets: [],
    glossaryTerms: [],
    searching: false,
    searchError: "",
    resolvedQuery: "",
  });
  useSeededAssetContext.mockReturnValue({ summary: null });
  useLineageGraphV2.mockReturnValue(emptyGraph());
});

describe("LineagePage — bare /lineage picker", () => {
  it("renders the search-first picker and never auto-redirects to a recommendation", () => {
    useLineageRecommendations.mockReturnValue(richRecommendations());
    renderLineage("/lineage");
    expect(screen.getByPlaceholderText("Search tables, views, catalogs…")).toBeTruthy();
    expect(screen.getByText("High-lineage assets")).toBeTruthy();
    // Ranked candidate is a REAL link to the canonical /lineage/<fqn> path.
    const row = screen.getByText("rich").closest("a");
    expect(row?.getAttribute("href")).toBe("/lineage/a.b.rich");
    // COHESION law: bare /lineage is a deliberate picker — no silent
    // redirect to the top ranked asset (legacy behavior, killed in C7).
    expect(probe()).toBe("/lineage");
  });

  it("offers search results as lineage links for the addressable ?q=", () => {
    usePaletteSearch.mockImplementation((query) => ({
      assets: query === "c" ? [{ fqn: "a.b.c", name: "c", catalogName: "a", schemaName: "b" }] : [],
      glossaryTerms: [],
      searching: false,
      searchError: "",
      resolvedQuery: query,
    }));
    renderLineage("/lineage?q=c");
    expect(screen.getByPlaceholderText("Search tables, views, catalogs…").value).toBe("c");
    const row = screen.getByText("c").closest("a");
    expect(row?.getAttribute("href")).toBe("/lineage/a.b.c");
    fireEvent.click(screen.getByText("c"));
    expect(probe()).toBe("/lineage/a.b.c");
  });

  it("writes the picker query to the URL", () => {
    renderLineage("/lineage");
    fireEvent.change(screen.getByPlaceholderText("Search tables, views, catalogs…"), {
      target: { value: "loan" },
    });
    expect(probe()).toBe("/lineage?q=loan");
  });

  it("labels aggregate recommendation fallback without leaking scope tokens", () => {
    useLineageRecommendations.mockReturnValue({
      ...richRecommendations(),
      envelopeMeta: { authoritative: false, visibilityScope: "actor-scoped" },
      authoritative: false,
      degraded: true,
      relationshipVisibilityScope: "actor-openable-candidate-aggregate",
    });
    renderLineage("/lineage");
    // Persona audit P1 (preserved): human copy only, no internal tokens.
    expect(
      screen.getByText(/edge counts include assets outside your visible catalogs/i),
    ).toBeTruthy();
    expect(screen.queryByText(/actor-openable-candidate-aggregate/i)).toBeNull();
  });
});

describe("LineagePage — focused /lineage/<fqn>", () => {
  it("renders the v2 canvas + hero chips when an asset is focused", () => {
    useLineageGraphV2.mockReturnValue(focusGraph());
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByTestId("canvas-v2")).toBeTruthy();
    expect(screen.getByText("focus=a.b.focus")).toBeTruthy();
    expect(screen.getByText("nodes=1")).toBeTruthy();
    // The PageShell hero carries the focus FQN as the page title.
    expect(screen.getByRole("heading", { level: 1, name: "a.b.focus" })).toBeTruthy();
  });

  it("does not fetch quality evidence until the focus asset header hydrates", () => {
    useAssetDetail.mockReturnValue({ detail: null, loading: true, error: "" });
    useLineageGraphV2.mockReturnValue(focusGraph());
    renderLineage("/lineage/a.b.focus");
    expect(useAssetQuality).toHaveBeenCalledWith("a.b.focus", { enabled: false });
    expect(useAssetDatabricksEvidence).toHaveBeenCalledWith("a.b.focus", { enabled: false });
  });

  it("fetches quality evidence once the live asset header hydrates", () => {
    useAssetDetail.mockReturnValue({
      detail: { fqn: "a.b.focus", name: "focus" },
      loading: false,
      error: "",
    });
    useLineageGraphV2.mockReturnValue(focusGraph());
    renderLineage("/lineage/a.b.focus");
    expect(useAssetQuality).toHaveBeenCalledWith("a.b.focus", { enabled: true });
    expect(useAssetDatabricksEvidence).toHaveBeenCalledWith("a.b.focus", { enabled: true });
  });

  // Persona-audit P2 behavior (preserved): canvas click is SELECT-ONLY —
  // now addressable as ?selected=. Only the rail's explicit "Re-anchor
  // lineage" button changes the canonical focus path.
  it("selects on canvas click (?selected=) and only re-anchors via the rail button", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "u", fqn: "a.b.upstream", label: "upstream", subtitle: "a / b" },
        ],
      }),
    );
    renderLineage("/lineage/a.b.focus");
    fireEvent.click(screen.getByTestId("canvas-pick-upstream"));
    // Click alone must not change the focus path — selection is URL
    // sub-state on the SAME path (no refetch).
    expect(probe()).toBe("/lineage/a.b.focus?selected=a.b.upstream");
    expect(screen.getByText("Selected Node")).toBeTruthy();
    fireEvent.click(screen.getByText("Re-anchor lineage"));
    expect(probe()).toBe("/lineage/a.b.upstream");
  });

  it("restores a deep-linked ?selected= node as the rail subject", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "u", fqn: "a.b.upstream", label: "upstream", subtitle: "a / b" },
        ],
      }),
    );
    renderLineage("/lineage/a.b.focus?selected=a.b.upstream");
    expect(screen.getByText("Selected Node")).toBeTruthy();
    expect(screen.getByText("Re-anchor lineage")).toBeTruthy();
  });

  it("carries ?context= through a re-anchor instead of sessionStorage", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "u", fqn: "a.b.upstream", label: "upstream", subtitle: "a / b" },
        ],
      }),
    );
    renderLineage("/lineage/a.b.focus?context=Operational%20Context");
    fireEvent.click(screen.getByTestId("canvas-pick-upstream"));
    fireEvent.click(screen.getByText("Re-anchor lineage"));
    expect(probe()).toBe("/lineage/a.b.upstream?context=Operational+Context");
  });

  it("shows honest zero-edge recommendations for a dead lineage asset", () => {
    useLineageRecommendations.mockReturnValue(richRecommendations());
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        // True-empty requires the backend's explicit marker (adversarial
        // verify P0): terminal, non-deferred payload with emptyReason
        // "no-lineage-rows".
        payload: { source: "unity-catalog-lineage", profile: "full", buildState: "ok" },
        meta: { state: "available", emptyReason: "no-lineage-rows" },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByText("Unity Catalog has no table-lineage rows for this asset.")).toBeTruthy();
    fireEvent.click(screen.getByText("rich"));
    expect(probe()).toBe("/lineage/a.b.rich");
  });

  it("never shows the build-degraded banner while the full build is merely pending", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        stats: { progressive: { tableLineageDeferred: true } },
        payload: { source: "unity-catalog-lineage", profile: "initial", buildState: "ok" },
        hydrating: true,
        // meta.degraded true purely because the envelope has a warning —
        // exactly the input that used to fire the dishonest banner.
        meta: {
          state: "loading",
          degraded: true,
          deferred: true,
          warnings: ["Full lineage topology is hydrating from Unity Catalog system lineage tables."],
          capabilities: { hydrating: true },
        },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.queryByText(/lineage build failed/i)).toBeNull();
    expect(screen.queryByText("Lineage Build Degraded")).toBeNull();
    expect(
      screen.queryByText("Unity Catalog has no table-lineage rows for this asset."),
    ).toBeNull();
  });

  it("shows the build-degraded banner only for a genuinely failed build", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        payload: { source: "unity-catalog-lineage", profile: "full", buildState: "degraded" },
        meta: {
          state: "degraded",
          lineageQueryFailed: true,
          emptyReason: "lineage-query-failed",
          warnings: ["Lineage query failed; showing cached/partial data."],
        },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByText("Lineage Build Degraded")).toBeTruthy();
    expect(
      screen.queryByText("Unity Catalog has no table-lineage rows for this asset."),
    ).toBeNull();
  });

  // Truncation honesty (adversarial verify P1): the Decision Packet row
  // consumes graphs.data.meta.truncation totals + directional flags.
  it("renders exact truncation totals in the Decision Packet row", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "u", fqn: "a.b.up", label: "up" },
        ],
        edges: [{ id: "e1", source: "u", target: "f" }],
        stats: { truncated: { upstream: true, downstream: false } },
        payload: { source: "unity-catalog-lineage", profile: "full", buildState: "ok" },
        meta: {
          state: "available",
          truncation: { nodesShown: 21, nodesTotal: 660, edgesShown: 20, edgesTotal: 659 },
          upstreamTruncated: true,
          downstreamTruncated: false,
        },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(
      screen.getByText(/Showing 20 of 659 edges \(upstream capped\) — highest-traffic neighbors first/),
    ).toBeTruthy();
    expect(screen.queryByText(/No truncation flag returned/)).toBeNull();
  });

  it("traces a selected column through the inspector column tab", () => {
    useColumnLineageTrace.mockReturnValue({
      loading: false,
      upstream: { nodes: [{ id: "root", assetFqn: "a.b.focus", column: "mortgage_amount" }] },
      downstream: null,
      upstreamError: "",
      downstreamError: "Column lineage requires per-user authorization (OBO).",
    });
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        columnEdges: [{ column: "mortgage_amount" }],
        columnLineage: {
          upstream: [{ column: "mortgage_amount", sources: [{ assetFqn: "raw.loan", column: "amount" }] }],
          downstream: [],
          meta: {},
        },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    fireEvent.click(screen.getByTestId("canvas-pick-column"));
    fireEvent.click(screen.getByRole("tab", { name: "Columns" }));
    expect(screen.getByText("mortgage_amount on a.b.focus")).toBeTruthy();
    expect(screen.getByText("Column lineage requires per-user authorization (OBO).")).toBeTruthy();
  });

  it("does not report zero quality issues when quality evidence is unavailable", () => {
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "d", fqn: "a.b.down", role: "downstream", label: "down" },
        ],
        edges: [{ id: "e", source: "f", target: "d" }],
        payload: { source: "unity-catalog-lineage", authoritative: true },
        meta: { source: "unity-catalog-lineage", authoritative: true, visibilityScope: "actor-scoped" },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByText("Quality issues")).toBeTruthy();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Quality failures\/errors returned: 0/i)).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }));
    expect(screen.getByText(/quality-runner/)).toBeTruthy();
    expect(screen.getAllByText(/unavailable/).length).toBeGreaterThan(0);
  });

  it("does not promote an empty quality API payload to available quality evidence", () => {
    useAssetQuality.mockReturnValue({
      loading: false,
      error: "",
      runs: [],
      results: [],
      available: true,
      summaryBacked: false,
      summary: { passed: 0, failed: 0, errored: 0, skipped: 0 },
    });
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "d", fqn: "a.b.down", role: "downstream", label: "down" },
        ],
        edges: [{ id: "e", source: "f", target: "d" }],
        payload: { source: "unity-catalog-lineage", authoritative: true },
        meta: { source: "unity-catalog-lineage", authoritative: true, visibilityScope: "actor-scoped" },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByText("Quality issues")).toBeTruthy();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("0 Axiom run(s) · DQM unavailable")).toBeNull();
  });

  it("surfaces backed Databricks quality and Lakeflow evidence in the impact inspector", () => {
    useAssetDetail.mockReturnValue({
      detail: { fqn: "a.b.focus", name: "focus", openRequests: 1 },
      loading: false,
      error: "",
    });
    useAssetDatabricksEvidence.mockReturnValue({
      loading: false,
      error: "",
      available: true,
      qualityMonitoring: {
        state: "available",
        source: "system.data_quality_monitoring.table_results",
        rows: [{ event_time: "2026-05-05T01:00:00Z", status: "Healthy" }],
        summary: {
          healthStatus: "Healthy",
          freshnessStatus: "Healthy",
          completenessStatus: "Healthy",
        },
      },
      profileMetrics: {
        state: "available",
        source: "system.information_schema.tables",
        rows: [{ table_name: "focus_profile_metrics" }],
        summary: { lookupMethod: "data_quality.get_monitor" },
      },
      lakeflow: {
        state: "available",
        source: "system.lakeflow",
        jobs: [{ job_id: "job-1", job_name: "daily refresh", result_state: "SUCCESS" }],
        pipelines: [],
      },
      pipelineEvents: { state: "empty", source: "event_log", rows: [] },
      provenance: ["system.data_quality_monitoring.table_results", "system.lakeflow.jobs"],
    });
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "d", fqn: "a.b.down", role: "downstream", label: "down", kind: "job" },
        ],
        edges: [{ id: "e", source: "f", target: "d" }],
        payload: { source: "unity-catalog-lineage", authoritative: true },
        meta: { source: "unity-catalog-lineage", authoritative: true, visibilityScope: "actor-scoped" },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    expect(screen.getByText("DQM health")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByText(/daily refresh/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Evidence" }));
    expect(screen.getByText(/system.data_quality_monitoring.table_results/)).toBeTruthy();
    expect(screen.getByText(/system.lakeflow/)).toBeTruthy();
  });

  it("creates a backed governance request from the impact brief action", async () => {
    createGovernanceRequest.mockResolvedValue({ requestId: "req-123" });
    useAssetQuality.mockReturnValue({
      loading: false,
      error: "",
      runs: [{ run_id: "run-1" }],
      results: [{ result_id: "result-1", outcome: "failed" }],
      available: true,
      summaryBacked: true,
      summary: { passed: 0, failed: 1, errored: 0, skipped: 0 },
    });
    useLineageGraphV2.mockReturnValue(
      focusGraph({
        nodes: [
          { id: "f", fqn: "a.b.focus", isFocus: true, label: "focus" },
          { id: "d", fqn: "a.b.down", role: "downstream", label: "down", kind: "job" },
        ],
        edges: [{ id: "e", source: "f", target: "d" }],
        columnLineage: { upstream: [], downstream: [], meta: { truncated: false } },
        payload: { source: "unity-catalog-lineage", authoritative: true },
        meta: { source: "unity-catalog-lineage", authoritative: true, visibilityScope: "actor-scoped" },
      }),
    );
    renderLineage("/lineage/a.b.focus");
    fireEvent.click(screen.getByRole("button", { name: "Create request" }));
    await waitFor(() => {
      expect(createGovernanceRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          assetFqn: "a.b.focus",
          title: expect.stringContaining("Lineage impact review"),
          note: expect.stringContaining("Quality failures/errors returned: 1"),
        }),
        { fast: true },
      );
    });
    await waitFor(() => {
      expect(screen.getByText("Governance request created: req-123")).toBeTruthy();
    });
  });

  it("shows the honest unavailable state when lineage surface is gated off", () => {
    renderLineage("/lineage/a.b.focus", {
      bootstrap: { capabilities: { tableLineage: { available: false, reason: "Not granted" } } },
      runtimeFeatureFlags: [],
      workspaceAccess: baseWorkspaceAccess,
    });
    expect(screen.getByText("Lineage unavailable")).toBeTruthy();
  });
});
