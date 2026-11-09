import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { useCapabilityDashboard } from "./useCapabilityDashboard";

const fetchRuntimeStatusMock = vi.fn();
const fetchAdminBackgroundStatusMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchRuntimeStatus: (...args) => fetchRuntimeStatusMock(...args),
  fetchAdminBackgroundStatus: (...args) => fetchAdminBackgroundStatusMock(...args),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useCapabilityDashboard", () => {
  beforeEach(() => {
    fetchRuntimeStatusMock.mockReset();
    fetchAdminBackgroundStatusMock.mockReset();
  });

  it("composes runtime status + background status into a single shape", async () => {
    fetchRuntimeStatusMock.mockResolvedValue({
      runtime: { state: "live", message: "", client: { host: "h" } },
      store: { state: "live", message: "" },
      config: { warehouseId: "wh-1" },
      identity: { actorEmail: "qa@example.com", authMode: "obo-available" },
      capabilities: {
        systemInventoryRead: { available: true, state: "available" },
      },
    });
    fetchAdminBackgroundStatusMock.mockResolvedValue({
      data: {
        drainer: {
          running: true,
          lastDrainAt: "2026-04-20T12:00:00Z",
          processedTotal: 5,
          lastError: null,
        },
        queue: { depthHint: null },
      },
      meta: { state: "available", reason: "" },
    });

    const { result } = renderHook(() => useCapabilityDashboard(), {
      wrapper: createWrapper(),
    });

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(fetchRuntimeStatusMock).toHaveBeenCalledTimes(1);
      expect(fetchAdminBackgroundStatusMock).toHaveBeenCalledTimes(1);
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.identity?.actorEmail).toBe("qa@example.com");
    expect(result.current.runtime?.state).toBe("live");
    expect(result.current.store?.state).toBe("live");
    expect(result.current.capabilities?.systemInventoryRead?.available).toBe(true);
    expect(result.current.background?.drainer?.running).toBe(true);
    expect(result.current.background?.state).toBe("available");
    expect(result.current.lastRefreshedAt).toBe("");
  });

  it("updates lastRefreshedAt after refetch is called", async () => {
    fetchRuntimeStatusMock.mockResolvedValue({
      runtime: { state: "live", message: "" },
      store: { state: "live", message: "" },
      config: {},
      identity: { actorEmail: "qa@example.com" },
      capabilities: {},
    });
    fetchAdminBackgroundStatusMock.mockResolvedValue({
      data: {
        drainer: { running: true, lastDrainAt: null, processedTotal: 0, lastError: null },
        queue: { depthHint: null },
      },
      meta: { state: "available", reason: "" },
    });

    const { result } = renderHook(() => useCapabilityDashboard(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.lastRefreshedAt).toBe("");

    await act(async () => {
      await result.current.refetch();
    });

    expect(result.current.lastRefreshedAt).not.toBe("");
    // lastRefreshedAt must parse as a valid ISO date.
    expect(Number.isNaN(Date.parse(result.current.lastRefreshedAt))).toBe(false);
    // Both endpoints refetched.
    expect(fetchRuntimeStatusMock).toHaveBeenCalledTimes(2);
    expect(fetchAdminBackgroundStatusMock).toHaveBeenCalledTimes(2);
  });

  it("stays idle when disabled", () => {
    const { result } = renderHook(
      () => useCapabilityDashboard({ enabled: false }),
      {
        wrapper: createWrapper(),
      },
    );

    expect(fetchRuntimeStatusMock).not.toHaveBeenCalled();
    expect(fetchAdminBackgroundStatusMock).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.runtime).toBeNull();
    expect(typeof result.current.refetch).toBe("function");
  });
});
