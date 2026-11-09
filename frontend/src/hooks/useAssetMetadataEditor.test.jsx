import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAxiomQueryClient } from "../lib/queryClient";
import { useAssetMetadataEditor } from "./useAssetMetadataEditor";

const updateAssetMetadataMock = vi.fn();
const fetchAssetMetadataEditorMock = vi.fn();

vi.mock("../lib/api", () => ({
  updateAssetMetadata: (...args) => updateAssetMetadataMock(...args),
  fetchAssetMetadataEditor: (...args) => fetchAssetMetadataEditorMock(...args),
  getAssetMetadataApiContract: () => ({ available: true, path: "/api/assets/:fqn/metadata" }),
}));

function createWrapper() {
  const queryClient = createAxiomQueryClient();
  return function Wrapper({ children }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

const asset = {
  metadataEditor: {
    available: true,
    updatePath: "/api/assets/:fqn/metadata",
    updateMethod: "PATCH",
    fields: [{ key: "domain", label: "Domain", type: "text" }],
  },
};

describe("useAssetMetadataEditor identity-integrity honesty", () => {
  beforeEach(() => {
    updateAssetMetadataMock.mockReset();
    fetchAssetMetadataEditorMock.mockReset();
  });

  it("surfaces the backend roster-rejection 400 message verbatim", async () => {
    updateAssetMetadataMock.mockRejectedValue(
      new Error("finance-steward@shorecp.com is not a member of this Databricks workspace."),
    );

    const { result } = renderHook(
      () => useAssetMetadataEditor({ assetFqn: "cat.sch.tbl", asset, bootstrap: {} }),
      { wrapper: createWrapper() },
    );

    expect(result.current.available).toBe(true);

    await act(async () => {
      await result.current.save({ domain: "Finance" }).catch(() => {});
    });

    await waitFor(() => {
      expect(result.current.submitError).toBe(
        "finance-steward@shorecp.com is not a member of this Databricks workspace.",
      );
    });
    expect(result.current.submitSuccess).toBe("");
  });

  it("reports success when the write is accepted", async () => {
    updateAssetMetadataMock.mockResolvedValue({ ok: true });

    const { result } = renderHook(
      () => useAssetMetadataEditor({ assetFqn: "cat.sch.tbl", asset, bootstrap: {} }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.save({ domain: "Finance" }).catch(() => {});
    });

    await waitFor(() => {
      expect(result.current.submitSuccess).toBe("Metadata saved.");
    });
    expect(result.current.submitError).toBe("");
  });
});
