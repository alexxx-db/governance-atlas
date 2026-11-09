import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../../../lib/queryClient";
import { pushRecentAsset } from "../../../lib/prefs";
import { AssetPickerPage } from "../AssetPickerPage";

const api = vi.hoisted(() => ({
  fetchDiscoverySearch: vi.fn(),
  fetchGovernanceGlossary: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

function renderPicker(entry = "/assets") {
  return render(
    <QueryClientProvider client={axiomQueryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <AssetPickerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
  api.fetchDiscoverySearch.mockResolvedValue({
    assets: [
      {
        fqn: "main.sales.orders",
        name: "orders",
        catalog: "main",
        schema: "sales",
        certification: "Certified",
        domain: "Sales",
      },
      {
        fqn: "main.finance.ledger",
        name: "ledger",
        catalog: "main",
        schema: "finance",
        certification: "Certified",
        domain: "Finance",
      },
    ],
  });
  try {
    window.localStorage?.clear();
  } catch {
    /* storage may be unavailable in some environments */
  }
  axiomQueryClient.clear();
});

describe("AssetPickerPage — search-first Asset 360 picker", () => {
  it("renders the hero search and certified suggestion cards as real /assets anchors", async () => {
    renderPicker();

    expect(screen.getByLabelText("Search for an asset")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("Asset 360");

    await waitFor(() => expect(screen.getByText("Certified & governed assets")).toBeTruthy());
    const orders = await screen.findByText("orders");
    const card = orders.closest("a");
    expect(card.getAttribute("href")).toBe(`/assets/${encodeURIComponent("main.sales.orders")}`);
    // Rich card surfaces the governance signal.
    expect(within(card).getByText("Certified")).toBeTruthy();
  });

  it("lists recent assets from prefs as anchors to their records", async () => {
    pushRecentAsset("main.core.customers");
    renderPicker();

    await waitFor(() => expect(screen.getByText("Recent assets")).toBeTruthy());
    const recent = screen.getByText("customers").closest("a");
    expect(recent.getAttribute("href")).toBe(`/assets/${encodeURIComponent("main.core.customers")}`);
  });
});
