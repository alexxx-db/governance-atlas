import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../lib/queryClient";
import {
  LINEAGE_POLL_ATTEMPT_LIMIT,
  lineageRefetchInterval,
  primeLineagePayload,
  useLineage,
} from "./useLineage";

const fetchLineageMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchLineage: (...args) => fetchLineageMock(...args),
}));

function Wrapper({ children }) {
  return <QueryClientProvider client={axiomQueryClient}>{children}</QueryClientProvider>;
}

function liveLineagePayload({ fqn = "main.sales.orders", id, profile = "initial" }) {
  return {
    fqn,
    profile,
    authoritative: true,
    meta: {
      state: "live",
      source: "unity-catalog-lineage",
      authoritative: true,
    },
    graphs: {
      data: {
        nodes: [{ id, assetFqn: fqn }],
        edges: [],
      },
    },
  };
}

describe("useLineage", () => {
  beforeEach(() => {
    fetchLineageMock.mockReset();
    axiomQueryClient.clear();
  });

  it("starts without provisional seeded lineage and resolves to the bounded initial payload", async () => {
    fetchLineageMock.mockResolvedValueOnce(liveLineagePayload({ id: "initial" }));

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    expect(result.current.graph).toBe(null);
    expect(result.current.loading).toBe(true);
    expect(result.current.authoritative).toBe(false);
    expect(result.current.provisional).toBe(false);

    await waitFor(() => {
      expect(fetchLineageMock).toHaveBeenCalled();
      expect(result.current.loading).toBe(false);
      expect(result.current.authoritative).toBe(true);
      expect(result.current.provisional).toBe(false);
      expect(result.current.graph).not.toBe(null);
    });

    expect(fetchLineageMock).toHaveBeenCalledTimes(1);
    expect(fetchLineageMock.mock.calls[0][1].profile).toBe("initial");
    expect(fetchLineageMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("does not render unannotated lineage payloads as evidence", async () => {
    fetchLineageMock.mockResolvedValueOnce({
      fqn: "main.sales.orders",
      profile: "initial",
      graphs: {
        data: {
          nodes: [{ id: "unannotated", assetFqn: "main.sales.orders" }],
          edges: [],
        },
      },
    });

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.graph).toBe(null);
    expect(result.current.payload).toBe(null);
    expect(result.current.authoritative).toBe(false);
    expect(result.current.provisional).toBe(false);
  });

  it("loads the full lineage profile only when requested", async () => {
    fetchLineageMock
      .mockResolvedValueOnce(liveLineagePayload({ id: "initial" }))
      .mockResolvedValueOnce(liveLineagePayload({ id: "full", profile: "full" }));

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true, { fullProfile: true }),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(fetchLineageMock).toHaveBeenCalledTimes(2);
      expect(result.current.graph?.data?.nodes?.[0]?.id).toBe("full");
    });

    expect(fetchLineageMock.mock.calls[0][1].profile).toBe("initial");
    expect(fetchLineageMock.mock.calls[1][1].profile).toBe("full");
  });

  it("does not reuse the previous asset graph when route focus changes", async () => {
    fetchLineageMock
      .mockResolvedValueOnce(liveLineagePayload({ id: "orders" }))
      .mockImplementation(
        () =>
          new Promise(() => {}),
      );

    primeLineagePayload("main.sales.orders", liveLineagePayload({ id: "orders" }));

    const { result, rerender } = renderHook(
      ({ assetFqn, enabled }) => useLineage(assetFqn, enabled),
      {
        initialProps: { assetFqn: "main.sales.orders", enabled: true },
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.graph?.data?.nodes?.[0]?.id).toBe("orders");
    });

    rerender({ assetFqn: "main.sales.customers", enabled: true });

    expect(result.current.loading).toBe(true);
    expect(result.current.graph).toBe(null);
    expect(result.current.payload).toBe(null);
    expect(result.current.authoritative).toBe(false);
    expect(result.current.provisional).toBe(false);
  });

  it("surfaces unavailable lineage errors without staying in retry-loading state", async () => {
    fetchLineageMock.mockRejectedValueOnce(new Error("Lineage unavailable"));

    const { result } = renderHook(
      () => useLineage("main.sales.missing", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBe("Lineage unavailable");
      expect(result.current.graph).toBe(null);
      expect(result.current.payload).toBe(null);
    });

    expect(fetchLineageMock).toHaveBeenCalledTimes(1);
    expect(fetchLineageMock.mock.calls[0][1].profile).toBe("initial");
  });

  it("exposes a current-graph refresh callback backed by live lineage refetches", async () => {
    fetchLineageMock
      .mockResolvedValueOnce(liveLineagePayload({ id: "initial" }))
      .mockResolvedValueOnce(liveLineagePayload({ id: "refreshed-initial" }))
      .mockResolvedValueOnce(liveLineagePayload({ id: "refreshed-full", profile: "full" }));

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.graph?.data?.nodes?.[0]?.id).toBe("initial");
    });

    const refreshed = await result.current.refresh();

    expect(fetchLineageMock).toHaveBeenCalledTimes(3);
    expect(fetchLineageMock.mock.calls[1][1].profile).toBe("initial");
    expect(fetchLineageMock.mock.calls[2][1].profile).toBe("full");
    expect(refreshed.graphs.data.nodes[0].id).toBe("refreshed-full");
  });

  it("rejects non-authoritative lineage payload variants before caching graph data", async () => {
    const flaggedPayload = {
      fqn: "main.sales.orders",
      profile: "initial",
      meta: {
        source: "prototype-mock",
        warnings: ["not live Databricks evidence"],
      },
      graphs: {
        data: {
          nodes: [{ id: "flagged", assetFqn: "main.sales.orders" }],
          edges: [],
        },
      },
    };
    fetchLineageMock
      .mockResolvedValueOnce(flaggedPayload)
      .mockResolvedValueOnce({ ...flaggedPayload, profile: "full" });

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.graph).toBe(null);
    expect(result.current.payload).toBe(null);
    expect(result.current.authoritative).toBe(false);
  });

  it("drops populated degraded live lineage payloads marked authoritative false", async () => {
    const payload = {
      fqn: "main.sales.orders",
      profile: "initial",
      authoritative: false,
      meta: {
        state: "degraded",
        source: "unity-catalog-lineage",
        authoritative: false,
      },
      graphs: {
        data: {
          nodes: [{ id: "degraded", assetFqn: "main.sales.orders" }],
          edges: [],
        },
      },
    };
    fetchLineageMock
      .mockResolvedValueOnce(payload)
      .mockResolvedValueOnce({ ...payload, profile: "full" });

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.graph?.data?.nodes || []).toEqual([]);
    expect(result.current.payload).toBeNull();
    expect(result.current.authoritative).toBe(false);
    expect(result.current.provisional).toBe(false);
  });

  it("keeps workspace-scoped Databricks lineage visible without promoting it to authoritative", async () => {
    const payload = {
      fqn: "main.sales.orders",
      profile: "initial",
      meta: {
        state: "live",
        source: "unity-catalog-lineage",
        visibilityScope: "workspace-app-principal",
        authoritative: false,
      },
      graphs: {
        data: {
          nodes: [{ id: "workspace-scoped", assetFqn: "main.sales.orders" }],
          edges: [],
        },
      },
    };
    fetchLineageMock.mockResolvedValueOnce(payload);

    const { result } = renderHook(
      () => useLineage("main.sales.orders", true),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.graph?.data?.nodes?.[0]?.id).toBe("workspace-scoped");
    });

    expect(result.current.payload?.meta?.visibilityScope).toBe("workspace-app-principal");
    expect(result.current.authoritative).toBe(false);
    expect(result.current.provisional).toBe(true);
  });
});

// Cold-cache poll termination (adversarial verify P0): while the server's
// full build is warming it serves a stale envelope whose data graph carries
// exactly ONE stub focus node. The old predicate treated "has nodes" as
// terminal, so the frontend never re-polled and every first visitor after
// cache expiry got a permanent empty canvas. Terminality must be
// STATE-based: keep polling while the payload is deferred / still-initial
// for a full-profile request; stop only on a genuinely terminal full
// payload or when the attempt budget is spent.
describe("lineageRefetchInterval (poll terminality)", () => {
  function queryFor(payload, { profile = "full", assetFqn = "main.poll.asset" } = {}) {
    return { state: { data: payload }, queryKey: ["lineage", profile, assetFqn] };
  }

  // The deferred stale payload the live API serves during a cold full build:
  // profile "initial", buildState ok, ONE stub node, zero edges.
  function deferredStubPayload() {
    return {
      fqn: "main.poll.asset",
      profile: "initial",
      buildState: "ok",
      meta: { state: "loading", capabilities: { hydrating: true } },
      stats: { progressive: { tableLineageDeferred: true } },
      graphs: {
        data: {
          nodes: [{ id: "focus-main.poll.asset", assetFqn: "main.poll.asset", role: "focus" }],
          edges: [],
          meta: { deferred: true },
        },
      },
    };
  }

  function terminalFullPayload() {
    return {
      fqn: "main.poll.asset",
      profile: "full",
      buildState: "ok",
      meta: { state: "available" },
      stats: { progressive: { tableLineageDeferred: false } },
      graphs: {
        data: {
          nodes: [
            { id: "focus-main.poll.asset", assetFqn: "main.poll.asset", role: "focus" },
            { id: "source-a.b.c", assetFqn: "a.b.c", role: "source" },
          ],
          edges: [{ source: "source-a.b.c", target: "focus-main.poll.asset" }],
          meta: { deferred: false },
        },
      },
    };
  }

  it("keeps polling a deferred stub payload even though it carries a node", () => {
    expect(
      lineageRefetchInterval(queryFor(deferredStubPayload(), { assetFqn: "main.poll.stub" })),
    ).toBe(3000);
  });

  it("keeps polling when a full request is answered with a still-initial profile", () => {
    // Even with a non-loading envelope state, profile "initial" under a
    // full-profile query key means the build has not delivered yet.
    const payload = deferredStubPayload();
    payload.meta = { state: "degraded" };
    expect(
      lineageRefetchInterval(queryFor(payload, { assetFqn: "main.poll.stale" })),
    ).toBe(3000);
  });

  it("stops polling when a genuinely terminal full payload arrives", () => {
    expect(
      lineageRefetchInterval(queryFor(terminalFullPayload(), { assetFqn: "main.poll.done" })),
    ).toBe(false);
  });

  it("treats a terminal degraded full payload as terminal (no infinite retry)", () => {
    const payload = terminalFullPayload();
    payload.buildState = "degraded";
    payload.meta = { state: "degraded", warnings: ["Lineage query failed"] };
    expect(
      lineageRefetchInterval(queryFor(payload, { assetFqn: "main.poll.degraded" })),
    ).toBe(false);
  });

  it("does not poll the initial-profile query for its own terminal initial payload", () => {
    // The initial profile is inherently "deferred by design"; only
    // loading/hydrating envelope states keep the initial query polling.
    const payload = deferredStubPayload();
    payload.meta = { state: "available" };
    expect(
      lineageRefetchInterval(
        queryFor(payload, { profile: "initial", assetFqn: "main.poll.initialdone" }),
      ),
    ).toBe(false);
  });

  it("exhausts the bounded attempt budget instead of polling forever", () => {
    vi.useFakeTimers();
    try {
      const results = [];
      for (let i = 0; i < LINEAGE_POLL_ATTEMPT_LIMIT + 3; i += 1) {
        results.push(
          lineageRefetchInterval(queryFor(deferredStubPayload(), { assetFqn: "main.poll.cap" })),
        );
        vi.advanceTimersByTime(3000); // real polls are 3s apart
      }
      expect(results.slice(0, LINEAGE_POLL_ATTEMPT_LIMIT)).toEqual(
        Array(LINEAGE_POLL_ATTEMPT_LIMIT).fill(3000),
      );
      expect(results.slice(LINEAGE_POLL_ATTEMPT_LIMIT)).toEqual([false, false, false]);
    } finally {
      vi.useRealTimers();
    }
  });
});
