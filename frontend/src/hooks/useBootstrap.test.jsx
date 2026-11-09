import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { useBootstrap } from "./useBootstrap";

const fetchBootstrapMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchBootstrap: (...args) => fetchBootstrapMock(...args),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return (
      <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MemoryRouter>
    );
  };
}

describe("useBootstrap", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    fetchBootstrapMock.mockReset();
    window.__AXIOM_BOOTSTRAP__ = {
      bootState: "live",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      assets: [{ fqn: "main.sales.seeded" }],
    };
  });

  it("seeds from the bootstrap payload and refreshes with route-aware abortable fetches", async () => {
    fetchBootstrapMock.mockResolvedValue({
      bootState: "live",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      assets: [{ fqn: "main.sales.authoritative" }, { fqn: "main.sales.other" }],
    });

    const { result } = renderHook(
      () =>
        useBootstrap({
          surface: "discovery",
          asset: "",
        }),
      {
        wrapper: createWrapper(),
      },
    );

    expect(result.current.data?.assets?.[0]?.fqn).toBe("main.sales.seeded");
    expect(result.current.data?.apiContract?.governanceSummary).toBeUndefined();
    expect(result.current.refreshing).toBe(true);

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(1);
      expect(result.current.refreshing).toBe(false);
      expect(result.current.data?.assets?.[0]?.fqn).toBe("main.sales.authoritative");
      expect(result.current.data?.apiContract?.governanceSummary).toBeUndefined();
    });

    expect(fetchBootstrapMock.mock.calls[0][0]).toEqual({
      surface: "discovery",
      asset: "",
    });
    expect(fetchBootstrapMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(typeof result.current.refresh).toBe("function");

    await result.current.refresh();

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(2);
    });
  });

  it("does not refetch bootstrap when only the discovery query changes", async () => {
    fetchBootstrapMock.mockResolvedValue({
      bootState: "live",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      assets: [{ fqn: "main.sales.authoritative" }],
    });

    const { rerender } = renderHook(
      ({ discoveryQuery }) =>
        useBootstrap({
          surface: "discovery",
          asset: "",
          discoveryQuery,
        }),
      {
        initialProps: { discoveryQuery: "finance" },
        wrapper: createWrapper(),
      },
    );

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(1);
    });

    rerender({ discoveryQuery: "marketing" });

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(1);
    });
  });

  it("preserves additive top-level capability flags through the seed and refresh path", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      bootState: "live",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      capabilities: {
        systemInventoryRead: {
          available: true,
          state: "degraded",
        },
      },
      assets: [{ fqn: "main.sales.seeded" }],
    };

    fetchBootstrapMock.mockResolvedValue({
      bootState: "live",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      capabilities: {
        tableLineage: {
          available: true,
          state: "available",
        },
      },
      assets: [{ fqn: "main.sales.authoritative" }],
    });

    const { result } = renderHook(
      () =>
        useBootstrap({
          surface: "discovery",
          asset: "",
        }),
      {
        wrapper: createWrapper(),
      },
    );

    expect(result.current.data?.capabilities?.systemInventoryRead?.state).toBe("degraded");

    await waitFor(() => {
      expect(result.current.data?.capabilities?.tableLineage?.state).toBe("available");
    });
  });

  it("keeps polling route bootstrap payloads while the runtime is still loading", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      bootState: "loading",
      shell: {
        userEmail: "qa@example.com",
      },
      bootstrapContract: {
        class: "shell-capability",
        mode: "route-bootstrap",
        warnings: [],
      },
      apiContract: {
        bootstrap: "/api/bootstrap",
      },
      assets: [],
    };

    fetchBootstrapMock
      .mockResolvedValueOnce({
        bootState: "loading",
        shell: {
          userEmail: "qa@example.com",
        },
        bootstrapContract: {
          class: "shell-capability",
          mode: "route-bootstrap",
          warnings: [],
        },
        apiContract: {
          bootstrap: "/api/bootstrap",
        },
        assets: [],
      })
      .mockResolvedValueOnce({
        bootState: "live",
        shell: {
          userEmail: "qa@example.com",
        },
        bootstrapContract: {
          class: "shell-capability",
          mode: "route-bootstrap",
          warnings: [],
        },
        apiContract: {
          bootstrap: "/api/bootstrap",
        },
        assets: [{ fqn: "main.sales.authoritative" }],
      });

    const { result } = renderHook(
      () =>
        useBootstrap({
          surface: "taxonomy",
          asset: "",
        }),
      {
        wrapper: createWrapper(),
      },
    );

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(1);
      expect(result.current.data?.bootState).toBe("loading");
    });

    await waitFor(() => {
      expect(fetchBootstrapMock).toHaveBeenCalledTimes(2);
      expect(result.current.data?.bootState).toBe("live");
      expect(result.current.data?.assets?.[0]?.fqn).toBe("main.sales.authoritative");
    }, { timeout: 4_500 });
  }, 6_000);
});
