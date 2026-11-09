import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../../../lib/queryClient";
import { AssetPeekPanel } from "../AssetPeekPanel";
import { ShellProvider } from "../../../app-shell/ShellContext";

const api = vi.hoisted(() => ({
  fetchAssetDetail: vi.fn(),
  fetchAssetAvailability: vi.fn(),
  fetchAssetHeaders: vi.fn(),
  fetchAsset360: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

const FQN = "main.sales.orders";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPanel(props = {}) {
  const onClose = vi.fn();
  const view = render(
    <QueryClientProvider client={axiomQueryClient}>
      <ShellProvider value={{ shell: { workspaceHost: "https://example.cloud.databricks.com" } }}>
        <MemoryRouter initialEntries={[`/discovery?peek=${encodeURIComponent(FQN)}`]}>
          <AssetPeekPanel fqn={FQN} open onClose={onClose} {...props} />
          <LocationProbe />
        </MemoryRouter>
      </ShellProvider>
    </QueryClientProvider>,
  );
  return { ...view, onClose };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.fetchAssetAvailability.mockResolvedValue({ assets: {} });
  api.fetchAssetHeaders.mockResolvedValue({ assets: {} });
  api.fetchAssetDetail.mockResolvedValue({
    fqn: FQN,
    name: "orders",
    catalog: "main",
    schema: "sales",
    objectType: "Table",
    rows: 5,
    size: "1.2 MB",
    storageFormat: "DELTA",
    domain: "Sales",
    certification: "Certified",
    sensitivity: "Internal",
    coverageScore: 82,
    dataUpdatedAt: "2026-05-03T19:51:25.309000Z",
    lastAltered: "2026-06-01T00:00:00Z",
    loadedSections: ["header"],
  });
  api.fetchAsset360.mockResolvedValue({
    asset: { fqn: FQN, name: "orders" },
    access: { deepLinks: { catalogExplorer: "/explore/data/main/sales/orders" } },
    ownership: {
      ucOwner: { name: "abarreto@shorecp.com" },
      businessOwner: { name: "product-steward@shorecp.com" },
      steward: { name: "finance-steward@shorecp.com" },
    },
    freshness: {
      state: "available",
      dataUpdatedAt: "2026-05-03T19:51:25.309000Z",
      lastAltered: "2026-06-01T00:00:00Z",
      labels: { dataUpdatedAt: "Data updated", lastAltered: "Metadata changed" },
      message: "",
    },
    loadedSections: ["header", "activity", "schema"],
  });
  axiomQueryClient.clear();
});

describe("AssetPeekPanel", () => {
  it("renders identity + the SAME trust verdict as the hub + honest key facts, with no dead tabs or dev copy", async () => {
    renderPanel();

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText(FQN)).toBeTruthy());

    // Same trust verdict component: labeled freshness + distinct owner roles.
    const verdict = within(dialog).getByLabelText("Trust verdict");
    expect(within(verdict).getByText("Data updated")).toBeTruthy();
    expect(within(verdict).getByText("May 3, 2026, 19:51 UTC")).toBeTruthy();
    expect(within(verdict).getByText("Steward")).toBeTruthy();
    const steward = within(verdict).getByText("finance-steward@shorecp.com").closest("a");
    expect(steward.getAttribute("href")).toContain("/discovery");

    // Key facts, honest "—" for anything absent.
    expect(within(dialog).getByText("Rows")).toBeTruthy();
    expect(within(dialog).getByText("5")).toBeTruthy();
    expect(within(dialog).getByText("DELTA")).toBeTruthy();

    // No dead tabs, no drawer tab strip, no developer provenance note.
    expect(within(dialog).queryByRole("tab")).toBeNull();
    expect(within(dialog).queryByText(/Buildability/)).toBeNull();
  });

  it("'Open full record' navigates to the hub and closes the drawer", async () => {
    const { onClose } = renderPanel();

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(within(dialog).getByText("orders")).toBeTruthy());
    fireEvent.click(within(dialog).getByRole("button", { name: "Open full record" }));

    expect(onClose).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByTestId("location").textContent).toBe(`/assets/${encodeURIComponent(FQN)}`),
    );
  });

  it("offers a first-class 'Open in Databricks' link built from the live deepLink", async () => {
    renderPanel();
    const dialog = await screen.findByRole("dialog");
    const link = await within(dialog).findByRole("link", { name: "Open in Databricks" });
    expect(link.getAttribute("href")).toBe(
      "https://example.cloud.databricks.com/explore/data/main/sales/orders",
    );
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("title")).toBe("Open in Databricks Catalog Explorer");
  });

  it("renders nothing when closed", () => {
    renderPanel({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
