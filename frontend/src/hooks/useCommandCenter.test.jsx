import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { resetPollAttempts } from "./useAxiomQuery";
import { useCommandCenter, __resetCommandCenterRetention } from "./useCommandCenter";

const fetchCommandCenterMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchCommandCenter: (...args) => fetchCommandCenterMock(...args),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useCommandCenter", () => {
  beforeEach(() => {
    fetchCommandCenterMock.mockReset();
    // Retention is bounded by the poll budget; clear the module-scoped ledger
    // so one test's poll attempts don't flip another test's retention state.
    resetPollAttempts(["axiom", "command-center", "cache"]);
    resetPollAttempts(["axiom", "command-center", "force"]);
    // Retention now survives navigation at module scope — reset it between
    // cases so one test's backed payload doesn't mask another's warming/error.
    __resetCommandCenterRetention();
  });

  it("returns normalized command center data when fetch resolves", async () => {
    fetchCommandCenterMock.mockResolvedValue({
      estate: {
        visibleAssetCount: 12,
        catalogCount: 2,
        openRequests: 3,
        coverageScore: 82,
      },
      kpis: [],
      meta: { state: "available", warnings: [] },
    });

    const { result } = renderHook(() => useCommandCenter(true), {
      wrapper: createWrapper(),
    });

    expect(result.current.loading).toBe(true);
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(fetchCommandCenterMock).toHaveBeenCalledTimes(1);
    expect(fetchCommandCenterMock.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
    expect(result.current.data.estate.visibleAssetCount).toBe(12);
    expect(result.current.degraded).toBe(false);
  });

  it("retains last-good backed values when a refetch returns a warming payload", async () => {
    // First load: backed. Second (refresh): warming envelope with everything
    // null — the cold-warehouse case that used to blank a populated page.
    fetchCommandCenterMock
      .mockResolvedValueOnce({
        estate: { visibleAssetCount: 50, catalogCount: 6, coverageScore: 84.5 },
        kpis: [{ key: "governedAssets", value: 50 }],
        meta: { state: "available", warnings: [] },
      })
      .mockResolvedValueOnce({
        estate: { visibleAssetCount: null, catalogCount: null, coverageScore: null },
        kpis: [],
        meta: { state: "loading", warnings: ["Warming the Databricks SQL warehouse"] },
      });

    const { result } = renderHook(() => useCommandCenter(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data.estate.visibleAssetCount).toBe(50));

    await act(async () => {
      await result.current.refresh();
    });

    // The warming refetch must NOT wipe the rendered dashboard to nulls.
    expect(result.current.data.estate.visibleAssetCount).toBe(50);
    expect(result.current.data.estate.coverageScore).toBe(84.5);
    expect(result.current.hasLiveData).toBe(true);
  });

  it("stays idle when disabled", () => {
    const { result } = renderHook(() => useCommandCenter(false), {
      wrapper: createWrapper(),
    });

    expect(fetchCommandCenterMock).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.data.estate.visibleAssetCount).toBeNull();
  });

  it("surfaces an error when fetch fails without seed data", async () => {
    fetchCommandCenterMock.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useCommandCenter(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.error).toBe("boom");
    });
    expect(result.current.data.estate.visibleAssetCount).toBeNull();
  });

  it("keeps seed data and reports refreshError when fetch fails", async () => {
    fetchCommandCenterMock.mockRejectedValue(new Error("refresh failed"));
    const seedData = {
      estate: {
        visibleAssetCount: 7,
        catalogCount: 1,
        openRequests: 0,
        coverageScore: 70,
      },
      meta: { state: "available", warnings: [] },
    };

    const { result } = renderHook(
      () => useCommandCenter({ enabled: true, seedData }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.refreshError).toBe("refresh failed");
    });
    expect(result.current.error).toBe("");
    expect(result.current.data.estate.visibleAssetCount).toBe(7);
    expect(result.current.degraded).toBe(true);
  });

  it("reports hydration when seed data is visible before live command-center data returns", async () => {
    let resolveFetch;
    fetchCommandCenterMock.mockReturnValue(new Promise((resolve) => {
      resolveFetch = resolve;
    }));
    const seedData = {
      estate: {
        visibleAssetCount: 7,
        catalogCount: 1,
        openRequests: 0,
        coverageScore: 70,
      },
      meta: { state: "seed", warnings: [] },
    };

    const { result } = renderHook(
      () => useCommandCenter({ enabled: true, seedData }),
      { wrapper: createWrapper() },
    );

    expect(result.current.loading).toBe(false);
    expect(result.current.hydrating).toBe(true);
    expect(result.current.data.estate.visibleAssetCount).toBe(7);

    await act(async () => {
      resolveFetch({
        estate: { visibleAssetCount: 11 },
        meta: { state: "available", warnings: [] },
      });
    });

    await waitFor(() => {
      expect(result.current.hydrating).toBe(false);
    });
    expect(result.current.hasLiveData).toBe(true);
    expect(result.current.data.estate.visibleAssetCount).toBe(11);
  });

  it("drops preview warnings once live command-center data is available", async () => {
    fetchCommandCenterMock.mockResolvedValue({
      estate: { visibleAssetCount: 11 },
      meta: { state: "available", warnings: [] },
    });
    const seedData = {
      estate: { visibleAssetCount: 7 },
      meta: {
        state: "loading",
        warnings: ["Command-center metrics are hydrating from live metadata."],
      },
    };

    const { result } = renderHook(
      () => useCommandCenter({ enabled: true, seedData }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.hasLiveData).toBe(true);
    });
    expect(result.current.warnings).toEqual([]);
    expect(result.current.degraded).toBe(false);
  });

  it("refreshActorScope sends refresh flag on next fetch", async () => {
    fetchCommandCenterMock.mockResolvedValue({
      estate: { visibleAssetCount: 1 },
      meta: { state: "degraded", warnings: ["fallback"] },
    });

    const { result } = renderHook(() => useCommandCenter(true), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(fetchCommandCenterMock).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      result.current.refreshActorScope();
    });

    await waitFor(() => {
      expect(fetchCommandCenterMock).toHaveBeenCalledTimes(2);
    });
    expect(fetchCommandCenterMock.mock.calls[1][0].refresh).toBe(true);
  });
});
