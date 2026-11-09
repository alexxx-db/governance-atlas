// Contract tests for the Wave B/C surface hooks (extracted from today's
// inline component useQuery/fetch sites; unused until their surfaces are
// rewritten). Each test pins: the query key (cache continuity for the
// adopting rewrite), the enablement gate, and the derived shape.
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../lib/queryClient";
import { AUDIT_EVIDENCE_DEFAULT_LIMIT, auditRangeSinceIso, useAuditEvents, useAuditEvidence } from "./useAuditEvents";
import { useCdeDashboard, useCdeDetail } from "./useCdeDashboard";
import { useAdminControlCenter, useAdminTruthCheck } from "./useAdminControlCenter";
import { useTaxonomyOverview } from "./useTaxonomyOverview";
import { GOVERNANCE_WORKBENCH_KEY, useGovernanceWorkbench } from "./useGovernanceWorkbench";
import { useInboxWork } from "./useInboxWork";
import { usePaletteSearch, PALETTE_SEARCH_MIN_CHARS } from "./usePaletteSearch";

const mocks = {
  fetchAuditEvidence: vi.fn(),
  fetchAuditEvents: vi.fn(),
  fetchCdeDashboard: vi.fn(),
  fetchCdeDetail: vi.fn(),
  fetchAdminControlCenter: vi.fn(),
  fetchAdminTruthCheck: vi.fn(),
  fetchTaxonomyOverview: vi.fn(),
  fetchGovernanceWorkbench: vi.fn(),
  fetchGovernanceGlossary: vi.fn(),
  fetchDiscoverySearch: vi.fn(),
};

vi.mock("../lib/api", () => ({
  fetchAuditEvidence: (...args) => mocks.fetchAuditEvidence(...args),
  fetchAuditEvents: (...args) => mocks.fetchAuditEvents(...args),
  fetchCdeDashboard: (...args) => mocks.fetchCdeDashboard(...args),
  fetchCdeDetail: (...args) => mocks.fetchCdeDetail(...args),
  fetchAdminControlCenter: (...args) => mocks.fetchAdminControlCenter(...args),
  fetchAdminTruthCheck: (...args) => mocks.fetchAdminTruthCheck(...args),
  fetchTaxonomyOverview: (...args) => mocks.fetchTaxonomyOverview(...args),
  fetchGovernanceWorkbench: (...args) => mocks.fetchGovernanceWorkbench(...args),
  fetchGovernanceGlossary: (...args) => mocks.fetchGovernanceGlossary(...args),
  fetchDiscoverySearch: (...args) => mocks.fetchDiscoverySearch(...args),
}));

function Wrapper({ children }) {
  return <QueryClientProvider client={axiomQueryClient}>{children}</QueryClientProvider>;
}

const AVAILABLE = { meta: { state: "available", warnings: [] } };

beforeEach(() => {
  Object.values(mocks).forEach((mock) => mock.mockReset());
  axiomQueryClient.clear();
});

describe("useAuditEvidence / useAuditEvents", () => {
  it("loads the evidence feed under the legacy inline query key", async () => {
    mocks.fetchAuditEvidence.mockResolvedValue({ data: { events: [{ id: "AUD-1" }] }, ...AVAILABLE });
    const { result } = renderHook(() => useAuditEvidence({ dateRange: "7d" }), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(mocks.fetchAuditEvidence).toHaveBeenCalledWith(
      expect.objectContaining({ dateRange: "7d", limit: AUDIT_EVIDENCE_DEFAULT_LIMIT }),
    );
    // Cache continuity: the adopting rewrite finds the same cache entry.
    expect(
      axiomQueryClient.getQueryData(["axiom", "audit-evidence", "7d", AUDIT_EVIDENCE_DEFAULT_LIMIT]),
    ).toBeTruthy();
  });

  it("only queries events when a structured filter is active", async () => {
    mocks.fetchAuditEvents.mockResolvedValue({ data: { events: [] }, ...AVAILABLE });
    const { result, rerender } = renderHook(
      ({ filters }) => useAuditEvents(filters),
      { wrapper: Wrapper, initialProps: { filters: {} } },
    );
    expect(result.current.query.fetchStatus).toBe("idle");
    expect(mocks.fetchAuditEvents).not.toHaveBeenCalled();

    rerender({ filters: { actorEmail: "abarreto@shorecp.com" } });
    await waitFor(() => expect(mocks.fetchAuditEvents).toHaveBeenCalledTimes(1));
    expect(mocks.fetchAuditEvents.mock.calls[0][0]).toMatchObject({
      actorEmail: "abarreto@shorecp.com",
    });
  });

  it("computes range floors like the audit surface", () => {
    const now = Date.UTC(2026, 6, 21);
    expect(auditRangeSinceIso("24h", now)).toBe(new Date(now - 24 * 3_600_000).toISOString());
    expect(auditRangeSinceIso("bogus", now)).toBe("");
  });
});

describe("useCdeDashboard / useCdeDetail", () => {
  it("loads the dashboard under the legacy inline query key", async () => {
    mocks.fetchCdeDashboard.mockResolvedValue({ data: { candidates: [] }, ...AVAILABLE });
    const { result } = renderHook(() => useCdeDashboard(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(axiomQueryClient.getQueryData(["axiom", "cde-dashboard"])).toBeTruthy();
  });

  it("gates detail on a non-empty id", async () => {
    mocks.fetchCdeDetail.mockResolvedValue({ data: { id: "cde-1" }, ...AVAILABLE });
    const { result, rerender } = renderHook(({ id }) => useCdeDetail(id), {
      wrapper: Wrapper,
      initialProps: { id: "" },
    });
    expect(result.current.query.fetchStatus).toBe("idle");
    rerender({ id: "cde-1" });
    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(mocks.fetchCdeDetail).toHaveBeenCalledWith("cde-1", expect.anything());
  });
});

describe("useAdminControlCenter / useAdminTruthCheck", () => {
  it("respects the admin gate via enabled", () => {
    renderHook(() => useAdminControlCenter({ enabled: false }), { wrapper: Wrapper });
    renderHook(() => useAdminTruthCheck({ enabled: false }), { wrapper: Wrapper });
    expect(mocks.fetchAdminControlCenter).not.toHaveBeenCalled();
    expect(mocks.fetchAdminTruthCheck).not.toHaveBeenCalled();
  });

  it("loads both admin feeds under their legacy inline query keys", async () => {
    mocks.fetchAdminControlCenter.mockResolvedValue({ data: {}, ...AVAILABLE });
    mocks.fetchAdminTruthCheck.mockResolvedValue({ data: {}, ...AVAILABLE });
    const control = renderHook(() => useAdminControlCenter(), { wrapper: Wrapper });
    const truth = renderHook(() => useAdminTruthCheck(), { wrapper: Wrapper });
    await waitFor(() => {
      expect(control.result.current.status).toBe("available");
      expect(truth.result.current.status).toBe("available");
    });
    expect(axiomQueryClient.getQueryData(["axiom", "admin-control-center"])).toBeTruthy();
    expect(axiomQueryClient.getQueryData(["axiom", "admin-truth-check"])).toBeTruthy();
  });
});

describe("useTaxonomyOverview", () => {
  it("loads the overview under the legacy key", async () => {
    mocks.fetchTaxonomyOverview.mockResolvedValue({ data: { namespaces: [] }, ...AVAILABLE });
    const overview = renderHook(() => useTaxonomyOverview(), { wrapper: Wrapper });
    await waitFor(() => {
      expect(overview.result.current.status).toBe("available");
    });
    expect(axiomQueryClient.getQueryData(["axiom", "taxonomy-overview"])).toBeTruthy();
  });

  it("reports hydrating (and polls bounded) while the overview envelope loads", async () => {
    mocks.fetchTaxonomyOverview.mockResolvedValue({ data: {}, meta: { state: "loading" } });
    const { result } = renderHook(() => useTaxonomyOverview(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.status).toBe("hydrating"));
    expect(result.current.isPolling).toBe(true);
  });
});

describe("useGovernanceWorkbench", () => {
  it("uses ONE canonical key for the endpoint both legacy call sites shared", async () => {
    mocks.fetchGovernanceWorkbench.mockResolvedValue({ data: { requests: [] }, ...AVAILABLE });
    const { result } = renderHook(() => useGovernanceWorkbench(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.status).toBe("available"));
    expect(axiomQueryClient.getQueryData(GOVERNANCE_WORKBENCH_KEY)).toBeTruthy();
  });
});

describe("useInboxWork", () => {
  it("aggregates actionable requests + review terms into the badge count", async () => {
    mocks.fetchGovernanceWorkbench.mockResolvedValue({
      data: {
        requests: [
          { id: "GOV-1", status: "pending" },
          { id: "GOV-2", status: "approved" },
          { id: "GOV-3", status: "open" },
        ],
      },
      ...AVAILABLE,
    });
    mocks.fetchGovernanceGlossary.mockResolvedValue({
      glossary: [
        { id: "term-1", reviewState: "proposed" },
        { id: "term-2", reviewState: "published" },
      ],
    });
    const { result } = renderHook(() => useInboxWork(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.openRequests.map((request) => request.id)).toEqual(["GOV-1", "GOV-3"]);
    expect(result.current.reviewTerms.map((term) => term.id)).toEqual(["term-1"]);
    expect(result.current.badgeCount).toBe(3);
  });

  it("stays in loading (no definitive zero badge) until both sources answer", () => {
    mocks.fetchGovernanceWorkbench.mockImplementation(() => new Promise(() => {}));
    mocks.fetchGovernanceGlossary.mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => useInboxWork(), { wrapper: Wrapper });
    expect(result.current.loading).toBe(true);
  });
});

describe("usePaletteSearch", () => {
  it("debounces keystrokes: only the settled query hits the network", async () => {
    vi.useFakeTimers();
    try {
      mocks.fetchDiscoverySearch.mockResolvedValue({ assets: [{ fqn: "main.a.b" }], ...AVAILABLE });
      mocks.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
      const { result, rerender } = renderHook(({ q }) => usePaletteSearch(q), {
        wrapper: Wrapper,
        initialProps: { q: "cu" },
      });
      rerender({ q: "cus" });
      rerender({ q: "customer" });
      // The spinner shows from the first keystroke (debounce window counts).
      expect(result.current.searching).toBe(true);
      await vi.advanceTimersByTimeAsync(300);
      vi.useRealTimers();
      await waitFor(() => expect(result.current.assets.length).toBe(1));
      // Only the settled query fired — never one per keystroke.
      expect(mocks.fetchDiscoverySearch).toHaveBeenCalledTimes(1);
      expect(mocks.fetchDiscoverySearch.mock.calls[0][0]).toMatchObject({ query: "customer" });
      expect(result.current.resolvedQuery).toBe("customer");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not search below the min-chars threshold", () => {
    mocks.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
    const { result } = renderHook(() => usePaletteSearch("c"), { wrapper: Wrapper });
    expect("c".length).toBeLessThan(PALETTE_SEARCH_MIN_CHARS);
    expect(result.current.searching).toBe(false);
    expect(mocks.fetchDiscoverySearch).not.toHaveBeenCalled();
  });
});
