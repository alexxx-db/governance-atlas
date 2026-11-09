import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { useGovernanceSummary } from "./useGovernanceSummary";

const fetchGovernanceSummaryMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchGovernanceSummary: (...args) => fetchGovernanceSummaryMock(...args),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useGovernanceSummary", () => {
  beforeEach(() => {
    fetchGovernanceSummaryMock.mockReset();
  });

  it("requests governance summary through an abortable query", async () => {
    fetchGovernanceSummaryMock.mockResolvedValue({
      metrics: [],
      backlog: [],
      glossary: [],
      inbox: {
        state: "ready",
        unreadCount: 2,
        items: [],
      },
    });

    const { result } = renderHook(() => useGovernanceSummary(true), {
      wrapper: createWrapper(),
    });

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(fetchGovernanceSummaryMock).toHaveBeenCalledTimes(1);
      expect(result.current.loading).toBe(false);
      expect(result.current.data?.inbox?.unreadCount).toBe(2);
    });

    expect(fetchGovernanceSummaryMock.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
    expect(typeof result.current.refresh).toBe("function");
  });

  it("stays idle when disabled", () => {
    const { result } = renderHook(() => useGovernanceSummary(false), {
      wrapper: createWrapper(),
    });

    expect(fetchGovernanceSummaryMock).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
    expect(result.current.refreshing).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.empty).toEqual({
      metrics: [],
      backlog: [],
      glossary: [],
      inbox: null,
    });
  });
});
