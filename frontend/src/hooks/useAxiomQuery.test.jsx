import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../lib/queryClient";
import {
  boundedRefetchInterval,
  pollAttemptCount,
  pollBudgetExhausted,
  resetPollAttempts,
  useAxiomMutation,
  useAxiomQuery,
} from "./useAxiomQuery";

function Wrapper({ children }) {
  return <QueryClientProvider client={axiomQueryClient}>{children}</QueryClientProvider>;
}

describe("useAxiomQuery", () => {
  beforeEach(() => {
    axiomQueryClient.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves an available envelope with data/status/meta/warnings", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      data: { rows: [1] },
      meta: { state: "available", warnings: ["heads up"] },
    });
    const { result } = renderHook(
      () => useAxiomQuery({ key: ["axiom-query-test", "available"], fetch: fetchMock }),
      { wrapper: Wrapper },
    );

    expect(result.current.status).toBe("loading");
    await waitFor(() => {
      expect(result.current.status).toBe("available");
    });
    expect(result.current.data.data.rows).toEqual([1]);
    expect(result.current.meta.state).toBe("available");
    expect(result.current.warnings).toEqual(["heads up"]);
    expect(fetchMock.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
  });

  it("renders seed data instantly as hydrating, never a blank loading flash", async () => {
    const fetchMock = vi.fn(() => new Promise(() => {}));
    const { result } = renderHook(
      () =>
        useAxiomQuery({
          key: ["axiom-query-test", "seeded"],
          fetch: fetchMock,
          seed: { data: { rows: ["seed"] }, meta: { state: "available" } },
        }),
      { wrapper: Wrapper },
    );

    // Seed renders immediately: status is hydrating (not loading), data is
    // the seed — the hydration-zero bug class this contract eliminates.
    expect(result.current.status).toBe("hydrating");
    expect(result.current.data.data.rows).toEqual(["seed"]);
  });

  it("degrades (never wipes) when a refresh fails over rendered data", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new Error("refresh blew up"))
      .mockResolvedValueOnce({ data: { rows: [1] }, meta: { state: "available" } });
    const { result } = renderHook(
      () => useAxiomQuery({ key: ["axiom-query-test", "refresh-fail"], fetch: fetchMock }),
      { wrapper: Wrapper },
    );

    await waitFor(() => expect(result.current.status).toBe("available"));
    await act(async () => {
      await result.current.refresh().catch(() => {});
    });
    await waitFor(() => expect(result.current.status).toBe("degraded"));
    // Data survives the failed refresh.
    expect(result.current.data.data.rows).toEqual([1]);
    expect(result.current.warnings).toContain("refresh blew up");
  });

  it("reports terminal error status when the first fetch fails with nothing renderable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(
      () => useAxiomQuery({ key: ["axiom-query-test", "error"], fetch: fetchMock, retry: false }),
      { wrapper: Wrapper },
    );
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.data).toBe(null);
    expect(result.current.errorMessage).toBe("boom");
  });

  it("maps explicitly non-authoritative payloads to unavailable", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      data: { assets: [] },
      meta: { state: "non_authoritative" },
    });
    const { result } = renderHook(
      () => useAxiomQuery({ key: ["axiom-query-test", "nonauth"], fetch: fetchMock }),
      { wrapper: Wrapper },
    );
    await waitFor(() => expect(result.current.status).toBe("unavailable"));
  });

  it("REQUIRES poll.maxAttempts when poll.interval is set", () => {
    expect(() =>
      renderHook(
        () =>
          useAxiomQuery({
            key: ["axiom-query-test", "unbounded"],
            fetch: async () => ({}),
            poll: { interval: 3000 },
          }),
        { wrapper: Wrapper },
      ),
    ).toThrow(/maxAttempts is required/);
  });

  it("polls a hydrating envelope and stops when it turns terminal", async () => {
    let call = 0;
    const fetchMock = vi.fn(async () => {
      call += 1;
      return call < 3
        ? { data: {}, meta: { state: "loading" } }
        : { data: { rows: [1] }, meta: { state: "available" } };
    });
    const key = ["axiom-query-test", "poll-until-terminal"];
    const { result } = renderHook(
      () =>
        useAxiomQuery({
          key,
          fetch: fetchMock,
          // Tight cadence keeps the test fast; the engine only debounces
          // attempt COUNTING, not the actual refetch cadence.
          poll: { interval: 20, maxAttempts: 10 },
        }),
      { wrapper: Wrapper },
    );

    // Reaches terminal via bounded polling; the terminal payload clears the
    // ledger for future legitimate rebuilds.
    await waitFor(() => expect(result.current.status).toBe("available"), { timeout: 5000 });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(result.current.isPolling).toBe(false);
    expect(pollAttemptCount(key)).toBe(0);
  });

  it("degrades with an honest warning when the poll budget is exhausted", async () => {
    const fetchMock = vi.fn(async () => ({ data: {}, meta: { state: "loading" } }));
    const key = ["axiom-query-test", "poll-exhausted"];
    const { result } = renderHook(
      () =>
        useAxiomQuery({
          key,
          fetch: fetchMock,
          poll: { interval: 10, maxAttempts: 2 },
        }),
      { wrapper: Wrapper },
    );

    await waitFor(
      () => {
        expect(result.current.pollExhausted).toBe(true);
        expect(result.current.status).toBe("degraded");
      },
      { timeout: 5000 },
    );
    expect(result.current.isPolling).toBe(false);
    expect(
      result.current.warnings.some((warning) => warning.includes("after 2 checks")),
    ).toBe(true);

    // Explicit refresh restores the budget: a new fetch fires even though the
    // budget was spent (the ledger reset re-arms the loop).
    const callsBeforeRefresh = fetchMock.mock.calls.length;
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeRefresh);
  });

  it("honors a custom until predicate for non-envelope pending signals", () => {
    const interval = boundedRefetchInterval({
      interval: 3000,
      maxAttempts: 5,
      until: (data) => data?.inbox?.state !== "loading",
    });
    expect(
      interval({ state: { data: { inbox: { state: "loading" } } }, queryKey: ["custom-until", "a"] }),
    ).toBe(3000);
    expect(
      interval({ state: { data: { inbox: { state: "ready" } } }, queryKey: ["custom-until", "a"] }),
    ).toBe(false);
  });

  it("keeps polling until requested sections are loaded", () => {
    const interval = boundedRefetchInterval({
      interval: 3000,
      maxAttempts: 5,
      sections: ["schema"],
    });
    // Non-hydrating envelope but schema not loaded yet → keep polling.
    expect(
      interval({
        state: { data: { meta: { state: "available" }, loadedSections: ["header"] } },
        queryKey: ["sections-poll", "a"],
      }),
    ).toBe(3000);
    expect(
      interval({
        state: { data: { meta: { state: "available" }, loadedSections: ["header", "schema"] } },
        queryKey: ["sections-poll", "a"],
      }),
    ).toBe(false);
  });

  it("bounds the attempt budget with per-interval spacing (lineage ledger semantics)", () => {
    vi.useFakeTimers();
    const key = ["engine-test", "budget"];
    resetPollAttempts(key);
    const interval = boundedRefetchInterval({ interval: 3000, maxAttempts: 3 });
    const pendingQuery = {
      state: { data: { meta: { state: "loading" } } },
      queryKey: key,
    };
    // Rapid re-evaluations inside the same poll period must not burn budget
    // (react-query re-evaluates on every query-state change).
    expect(interval(pendingQuery)).toBe(3000);
    expect(interval(pendingQuery)).toBe(3000);
    expect(pollAttemptCount(key)).toBe(1);
    vi.advanceTimersByTime(3000);
    // One evaluation per period, like real polling: budget spends exactly.
    const results = [];
    for (let i = 0; i < 5; i += 1) {
      results.push(interval(pendingQuery));
      vi.advanceTimersByTime(3000);
    }
    expect(results).toEqual([3000, 3000, false, false, false]);
    expect(pollBudgetExhausted(key, 3)).toBe(true);
    resetPollAttempts(key);
    expect(pollAttemptCount(key)).toBe(0);
  });
});

describe("useAxiomMutation", () => {
  beforeEach(() => {
    axiomQueryClient.clear();
  });

  it("applies an optimistic update and rolls back on failure", async () => {
    const key = ["mutation-test", "inbox"];
    axiomQueryClient.setQueryData(key, { items: [{ id: "a", read: false }] });
    const mutateMock = vi.fn().mockRejectedValue(new Error("write failed"));

    const { result } = renderHook(
      () =>
        useAxiomMutation({
          mutate: mutateMock,
          optimistic: {
            key,
            update: (current, variables) => ({
              items: (current?.items || []).map((item) =>
                item.id === variables.id ? { ...item, read: true } : item,
              ),
            }),
          },
        }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.mutate({ id: "a" }).catch(() => {});
    });
    // Rolled back: optimistic UI must never survive a failed write.
    expect(axiomQueryClient.getQueryData(key)).toEqual({
      items: [{ id: "a", read: false }],
    });
    await waitFor(() => expect(result.current.errorMessage).toBe("write failed"));
  });

  it("invalidates key prefixes and runs onSuccess after a successful write", async () => {
    const invalidateSpy = vi.spyOn(axiomQueryClient, "invalidateQueries");
    const onSuccess = vi.fn();
    const { result } = renderHook(
      () =>
        useAxiomMutation({
          mutate: vi.fn().mockResolvedValue({ ok: true }),
          invalidates: [["mutation-test", "list"]],
          onSuccess,
        }),
      { wrapper: Wrapper },
    );

    await act(async () => {
      await result.current.mutate({});
    });
    expect(onSuccess).toHaveBeenCalledWith({ ok: true }, {}, axiomQueryClient);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["mutation-test", "list"] });
    await waitFor(() => expect(result.current.data).toEqual({ ok: true }));
    invalidateSpy.mockRestore();
  });
});
