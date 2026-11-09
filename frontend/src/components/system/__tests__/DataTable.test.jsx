import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "../DataTable";

const columns = [
  { key: "name", header: "Name", accessor: "name", sortable: true },
  { key: "rows", header: "Rows", accessor: "rows", sortable: true, align: "right" },
];

const rows = [
  { id: "b", name: "beta", rows: 20 },
  { id: "a", name: "alpha", rows: 300 },
  { id: "c", name: "carbon", rows: 1 },
];

function bodyCellTexts(columnIndex = 0) {
  const body = document.querySelector("tbody");
  return within(body)
    .getAllByRole("row")
    .map((row) => row.querySelectorAll("td")[columnIndex]?.textContent);
}

describe("DataTable", () => {
  it("renders headers and cells from the column contract", () => {
    render(<DataTable columns={columns} rows={rows} />);
    expect(screen.getByText("Name")).not.toBeNull();
    expect(screen.getByText("beta")).not.toBeNull();
    expect(screen.getByText("300")).not.toBeNull();
  });

  it("renders '—' for absent values (honest fallback, never fabricated)", () => {
    render(<DataTable columns={columns} rows={[{ id: "x", name: "solo" }]} />);
    expect(screen.getByText("—")).not.toBeNull();
  });

  it("uncontrolled sorting: clicking a sortable header sorts asc then desc with aria-sort", () => {
    render(<DataTable columns={columns} rows={rows} />);
    const nameSort = screen.getByRole("button", { name: "Name" });
    fireEvent.click(nameSort);
    expect(bodyCellTexts(0)).toEqual(["alpha", "beta", "carbon"]);
    expect(nameSort.closest("th").getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(nameSort);
    expect(bodyCellTexts(0)).toEqual(["carbon", "beta", "alpha"]);
    expect(nameSort.closest("th").getAttribute("aria-sort")).toBe("descending");
  });

  it("numeric columns sort numerically, not lexicographically", () => {
    render(<DataTable columns={columns} rows={rows} defaultSort={{ key: "rows", dir: "asc" }} />);
    expect(bodyCellTexts(1)).toEqual(["1", "20", "300"]);
  });

  it("controlled sorting: onSort fires with next sort and the kit does NOT re-order rows", () => {
    const onSort = vi.fn();
    render(<DataTable columns={columns} rows={rows} sort={{ key: "name", dir: "asc" }} onSort={onSort} />);
    // Parent owns order — rows stay exactly as passed.
    expect(bodyCellTexts(0)).toEqual(["beta", "alpha", "carbon"]);
    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(onSort).toHaveBeenCalledWith({ key: "name", dir: "desc" });
  });

  it("empty rows render the emptyState (default honest message)", () => {
    const { rerender } = render(<DataTable columns={columns} rows={[]} />);
    expect(screen.getByText("No rows available.")).not.toBeNull();
    rerender(<DataTable columns={columns} rows={[]} emptyState={<p>Custom empty.</p>} />);
    expect(screen.getByText("Custom empty.")).not.toBeNull();
  });

  it("loading renders skeleton rows and marks the table busy", () => {
    render(<DataTable columns={columns} rows={rows} loading loadingRows={3} />);
    const table = document.querySelector("table");
    expect(table.getAttribute("aria-busy")).toBe("true");
    expect(document.querySelectorAll(".ax-sys-table-skeleton-row").length).toBe(3);
    // real rows are not rendered while loading
    expect(screen.queryByText("beta")).toBeNull();
  });

  it("rowTarget renders the first cell as a real anchor with the canonical href", () => {
    render(
      <DataTable
        columns={columns}
        rows={rows}
        rowTarget={(row) => ({ kind: "asset", fqn: `main.sales.${row.id}` })}
      />,
    );
    const anchors = screen.getAllByRole("link");
    expect(anchors.length).toBe(3);
    expect(anchors[0].getAttribute("href")).toBe("/assets/main.sales.b");
    expect(anchors[0].className).toContain("ax-sys-table-rowlink");
  });

  it("clicking anywhere in a rowTarget row delegates to the row anchor (navigate adapter)", () => {
    const navigate = vi.fn();
    render(
      <DataTable
        columns={columns}
        rows={rows}
        navigate={navigate}
        rowTarget={(row) => ({ kind: "asset", fqn: `main.sales.${row.id}` })}
      />,
    );
    // Click the SECOND cell (not the anchor) of the first row.
    const firstRow = within(document.querySelector("tbody")).getAllByRole("row")[0];
    fireEvent.click(firstRow.querySelectorAll("td")[1]);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate.mock.calls[0][0]).toEqual({ kind: "asset", fqn: "main.sales.b" });
  });

  it("applies density and stickyHeader classes", () => {
    render(<DataTable columns={columns} rows={rows} density="compact" stickyHeader />);
    const wrap = document.querySelector(".ax-sys-table-wrap");
    expect(wrap.className).toContain("density-compact");
    expect(wrap.className).toContain("is-sticky");
  });
});
