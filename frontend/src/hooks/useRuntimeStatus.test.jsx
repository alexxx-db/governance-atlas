import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { useRuntimeStatus } from "./useRuntimeStatus";

const fetchRuntimeStatusMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchRuntimeStatus: (...args) => fetchRuntimeStatusMock(...args),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useRuntimeStatus", () => {
  beforeEach(() => {
    fetchRuntimeStatusMock.mockReset();
  });

  it("requests runtime status through an abortable query", async () => {
    fetchRuntimeStatusMock.mockResolvedValue({
      runtime: {
        state: "live",
        message: "",
        catalogCount: 3,
      },
      store: {
        state: "live",
        message: "",
      },
      capabilities: {
        tableLineage: {
          available: true,
          state: "available",
        },
      },
      config: {
        warehouseId: "warehouse-1",
      },
      identity: {
        actorEmail: "qa@example.com",
      },
      diagnostics: {
        buildId: "build-123",
      },
    });

    const { result } = renderHook(() => useRuntimeStatus(true), {
      wrapper: createWrapper(),
    });

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(fetchRuntimeStatusMock).toHaveBeenCalledTimes(1);
      expect(result.current.loading).toBe(false);
      expect(result.current.data?.runtime?.state).toBe("live");
    });

    expect(fetchRuntimeStatusMock.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
    expect(typeof result.current.refresh).toBe("function");

    await result.current.refresh();

    await waitFor(() => {
      expect(fetchRuntimeStatusMock).toHaveBeenCalledTimes(2);
    });
  });

  it("stays idle when disabled", () => {
    const { result } = renderHook(() => useRuntimeStatus(false), {
      wrapper: createWrapper(),
    });

    expect(fetchRuntimeStatusMock).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.refreshing).toBe(false);
    expect(result.current.data).toBeNull();
    expect(typeof result.current.refresh).toBe("function");
  });
});
