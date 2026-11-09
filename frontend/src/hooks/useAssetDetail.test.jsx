import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../lib/queryClient";
import {
  prefetchAssetDetail,
  primeAssetDetail,
  useAssetDetail,
} from "./useAssetDetail";

const fetchAssetAvailabilityMock = vi.fn();
const fetchAssetDetailMock = vi.fn();

vi.mock("../lib/api", () => ({
  fetchAssetAvailability: (...args) => fetchAssetAvailabilityMock(...args),
  fetchAssetDetail: (...args) => fetchAssetDetailMock(...args),
}));

function Wrapper({ children }) {
  return <QueryClientProvider client={axiomQueryClient}>{children}</QueryClientProvider>;
}

describe("useAssetDetail", () => {
  beforeEach(() => {
    fetchAssetAvailabilityMock.mockReset();
    fetchAssetDetailMock.mockReset();
    axiomQueryClient.clear();
  });

  it("merges activity payloads into the canonical asset record, including metadata audit updates", async () => {
    primeAssetDetail("main.sales.orders", {
      fqn: "main.sales.orders",
      name: "orders",
      metadataAudit: [{ id: "audit-old" }],
      loadedSections: ["header"],
      deferredSections: ["activity", "schema"],
    });
    fetchAssetDetailMock.mockResolvedValue({
      fqn: "main.sales.orders",
      activity: [{ id: "activity-new" }],
      metadataAudit: [{ id: "audit-new" }],
      loadedSections: ["activity"],
      deferredSections: ["schema"],
    });

    const detail = await prefetchAssetDetail("main.sales.orders", {
      force: true,
      sections: ["activity"],
    });

    expect(detail.loadedSections).toEqual(["activity", "header"]);
    expect(detail.metadataAudit).toEqual([{ id: "audit-new" }]);
    expect(detail.activity).toEqual([{ id: "activity-new" }]);
  });

  it("does not prime canonical asset detail from non-authoritative mutation payloads", async () => {
    const primed = primeAssetDetail("main.sales.orders", {
      fqn: "main.sales.orders",
      name: "prototype orders",
      evidenceKind: "non_authoritative_mock_capture",
      loadedSections: ["header"],
      deferredSections: [],
    });
    fetchAssetDetailMock.mockResolvedValue({
      fqn: "main.sales.orders",
      name: "orders",
      loadedSections: ["header"],
      deferredSections: [],
    });

    const { result } = renderHook(
      () =>
        useAssetDetail("main.sales.orders", {
          sections: ["header"],
        }),
      {
        wrapper: Wrapper,
      },
    );

    expect(primed).toBeNull();
    await waitFor(() => {
      expect(fetchAssetDetailMock).toHaveBeenCalledTimes(1);
      expect(result.current.detail?.name).toBe("orders");
    });
  });

  it("does not prime canonical asset detail from authoritative false payloads", () => {
    const primed = primeAssetDetail("main.sales.orders", {
      fqn: "main.sales.orders",
      name: "orders",
      authoritative: false,
      loadedSections: ["header"],
      deferredSections: [],
    });

    expect(primed).toBeNull();
    expect(axiomQueryClient.getQueryData(["asset-detail", "main.sales.orders", "canonical"])).toBeUndefined();
  });

  it("requests asset detail through an abortable query-backed fetch", async () => {
    fetchAssetDetailMock.mockResolvedValue({
      fqn: "main.sales.orders",
      name: "orders",
      loadedSections: ["header"],
      deferredSections: [],
    });

    const { result } = renderHook(
      () =>
        useAssetDetail("main.sales.orders", {
          sections: ["header"],
        }),
      {
        wrapper: Wrapper,
      },
    );

    await waitFor(() => {
      expect(fetchAssetDetailMock).toHaveBeenCalledTimes(1);
      expect(result.current.detail?.fqn).toBe("main.sales.orders");
    });

    expect(fetchAssetDetailMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  // P0-2 regression (ASSET360_TEARDOWN): `readCanonicalDetail(fqn, { maxAgeMs:
  // null })` means "no age limit", but `options.maxAgeMs ?? TTL` treated the
  // explicit null as unset (`null ?? x === x`) and re-imposed the 20s TTL.
  // Result: switching to a tab whose sections weren't in the request cache
  // >20s after load found no placeholder, `loading && !detail` went true, and
  // the fully-rendered record regressed to the loading shell. This test
  // replays that exact scenario and pins the fix: the aged canonical record
  // must still serve as the placeholder while the new section fetch runs.
  it("keeps serving the aged canonical record as placeholder on tab switches after the 20s TTL", async () => {
    const nowSpy = vi.spyOn(Date, "now");
    try {
      primeAssetDetail("main.sales.orders", {
        fqn: "main.sales.orders",
        name: "orders",
        loadedSections: ["header"],
        deferredSections: ["profiler"],
      });
      // A tab switch requests a section set that has no request-cache entry;
      // the fetch hangs to prove the placeholder alone carries the render.
      fetchAssetDetailMock.mockImplementation(() => new Promise(() => {}));

      // 21s later — past DETAIL_CACHE_TTL_MS (20s) — the user clicks Profile.
      const realNow = Date.now();
      nowSpy.mockImplementation(() => realNow + 21_000);

      const { result } = renderHook(
        () =>
          useAssetDetail("main.sales.orders", {
            sections: ["profiler"],
          }),
        {
          wrapper: Wrapper,
        },
      );

      // The record must NOT vanish into the loading shell: detail stays
      // renderable from the aged canonical cache while the section loads.
      expect(result.current.detail?.fqn).toBe("main.sales.orders");
      expect(result.current.detail?.name).toBe("orders");
      // The requested section is genuinely absent, so a loading signal for
      // the *section* is fine — but never `loading && !detail` (the shell
      // regression condition in EntityWorkspace).
      expect(Boolean(result.current.loading && !result.current.detail)).toBe(false);
      await waitFor(() => {
        expect(fetchAssetDetailMock).toHaveBeenCalled();
      });
      expect(result.current.detail?.fqn).toBe("main.sales.orders");
    } finally {
      nowSpy.mockRestore();
    }
  });
});
