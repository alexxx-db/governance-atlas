import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LineageNodeCard } from "./LineageNodeCard";

const baseNode = {
  id: "n1",
  fqn: "emet.curated.revenue_daily",
  label: "revenue_daily",
  subtitle: "emet / curated",
  kind: "table",
  isOpenable: true,
  isCertified: true,
  classification: "Confidential",
  containsPii: false,
  rowCount: "1.2M",
  freshness: "2h ago",
  freshnessRaw: "2026-05-04T01:00:00Z",
  owners: [{ displayName: "Marisol Reyes" }],
  ownerCount: 1,
  recentActivity: [{}, {}, {}],
  recentActivityCount: 3,
  columns: [
    { name: "id", type: "BIGINT" },
    { name: "amount", type: "DECIMAL" },
  ],
  totalColumns: 12,
};

describe("LineageNodeCard", () => {
  it("renders the title, subtitle, and footer metadata in compact mode", () => {
    render(<LineageNodeCard node={baseNode} variant="compact" />);
    expect(screen.getByText("revenue_daily")).toBeTruthy();
    expect(screen.getByText("emet / curated")).toBeTruthy();
    expect(screen.getByText("1.2M rows")).toBeTruthy();
    expect(screen.getByText("2h ago")).toBeTruthy();
    // The owner footer now shows the owner's name (UC-equivalent), not
    // a generic "1 owner" count.
    expect(screen.getByText("Marisol Reyes")).toBeTruthy();
    expect(screen.getByText("3 recent")).toBeTruthy();
  });

  it("prefers batch-fetched header values over the node-level fallbacks", () => {
    // header carries UC-grade per-node detail (size, freshness via
    // updatedAt, type, owner) — the card should render those.
    const header = {
      size: "12.4 GiB",
      files: "143",
      rows: "1.2M",
      managementType: "Managed",
      objectType: "Table",
      updatedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      owners: [{ displayName: "Devon Cho" }],
    };
    render(<LineageNodeCard node={baseNode} header={header} variant="compact" />);
    expect(screen.getByText("Managed · Table")).toBeTruthy();
    expect(screen.getByText("12.4 GiB")).toBeTruthy();
    // Header owner overrides node owner
    expect(screen.getByText("Devon Cho")).toBeTruthy();
    // Relative-time label derived from updatedAt
    expect(screen.getByText("2h ago")).toBeTruthy();
  });

  it("renders columns + classification chip + PII chip in tall mode", () => {
    render(
      <LineageNodeCard
        node={{ ...baseNode, containsPii: true }}
        variant="tall"
      />,
    );
    expect(screen.getByText("id")).toBeTruthy();
    expect(screen.getByText("BIGINT")).toBeTruthy();
    expect(screen.getByText("amount")).toBeTruthy();
    expect(screen.getByText("DECIMAL")).toBeTruthy();
    expect(screen.getByText("+10 more columns")).toBeTruthy();
    expect(screen.getByText("PII")).toBeTruthy();
    expect(screen.getByText("Confidential")).toBeTruthy();
  });

  it("fires onClick when the card is navigable", () => {
    const onClick = vi.fn();
    render(<LineageNodeCard node={baseNode} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledWith(baseNode);
  });

  it("fires onColumnSelect without firing card navigation when a column is clicked", () => {
    const onClick = vi.fn();
    const onColumnSelect = vi.fn();
    render(
      <LineageNodeCard
        node={baseNode}
        onClick={onClick}
        onColumnSelect={onColumnSelect}
        selectedColumnName="amount"
        variant="tall"
      />,
    );
    fireEvent.click(screen.getByText("amount").closest("button"));
    expect(onColumnSelect).toHaveBeenCalledWith(baseNode, { name: "amount", type: "DECIMAL" });
    expect(onClick).not.toHaveBeenCalled();
  });

  it("does NOT mark the card navigable when isOpenable=false", () => {
    const lineageOnly = { ...baseNode, isOpenable: false };
    const { container } = render(<LineageNodeCard node={lineageOnly} onClick={() => {}} />);
    const card = container.querySelector(".ax-lineage-v2-card");
    expect(card?.getAttribute("data-navigable")).toBe("false");
  });

  it("falls back to the API foot strings when no header is loaded", () => {
    const sparse = {
      ...baseNode,
      rowCount: null,
      freshness: "",
      owners: [],
      ownerCount: 0,
      recentActivityCount: 0,
      foot: ["Table", "Metadata unavailable"],
    };
    render(<LineageNodeCard node={sparse} />);
    expect(screen.getByText("Table")).toBeTruthy();
    expect(screen.getByText("Metadata unavailable")).toBeTruthy();
  });

  it("shows a 'Loading header…' placeholder when nothing is available yet", () => {
    const empty = {
      ...baseNode,
      rowCount: null,
      freshness: "",
      apiKind: "",
      owners: [],
      ownerCount: 0,
      recentActivityCount: 0,
      foot: [],
    };
    render(<LineageNodeCard node={empty} />);
    expect(screen.getByText("Loading header…")).toBeTruthy();
  });

  it("marks the focus card with is-focus and aria-current", () => {
    const { container } = render(<LineageNodeCard node={baseNode} isFocus />);
    const card = container.querySelector(".ax-lineage-v2-card");
    expect(card?.classList.contains("is-focus")).toBe(true);
    expect(card?.getAttribute("aria-current")).toBe("true");
  });

  // Node-level affordances (owner direction #2c).
  it("renders Asset 360 + Databricks affordances for a navigable node", () => {
    const onOpenAsset = vi.fn();
    render(
      <LineageNodeCard
        databricksHref="https://dbc-x.cloud.databricks.com/explore/data/emet/curated/revenue_daily"
        node={baseNode}
        onClick={() => {}}
        onOpenAsset={onOpenAsset}
      />,
    );
    fireEvent.click(screen.getByText("Asset 360"));
    expect(onOpenAsset).toHaveBeenCalledWith("emet.curated.revenue_daily");
    const dbx = screen.getByText("Databricks").closest("a");
    expect(dbx?.getAttribute("href")).toContain("/explore/data/emet/curated/revenue_daily");
    expect(dbx?.getAttribute("target")).toBe("_blank");
  });

  it("clicking a node action does NOT trigger card selection", () => {
    const onClick = vi.fn();
    const onOpenAsset = vi.fn();
    render(<LineageNodeCard node={baseNode} onClick={onClick} onOpenAsset={onOpenAsset} />);
    fireEvent.click(screen.getByText("Asset 360"));
    expect(onOpenAsset).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("omits the Databricks affordance when no deep link is available", () => {
    render(<LineageNodeCard node={baseNode} onClick={() => {}} onOpenAsset={() => {}} />);
    expect(screen.queryByText("Databricks")).toBeNull();
    expect(screen.getByText("Asset 360")).toBeTruthy();
  });

  it("shows no action strip for a non-navigable (lineage-only) node", () => {
    const lineageOnly = { ...baseNode, isOpenable: false };
    render(<LineageNodeCard node={lineageOnly} onClick={() => {}} onOpenAsset={() => {}} />);
    expect(screen.queryByText("Asset 360")).toBeNull();
  });
});
