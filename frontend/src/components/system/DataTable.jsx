import "./system.css";
import { useMemo, useState } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import { hrefForRef } from "./refs";
import { EmptyState } from "./StateViews";

/*
 * The one table (FRONTEND_BLUEPRINT §6). Absorbs northstar/DataTable's
 * column contract ({key|accessor, header|label, render}) and extends it
 * with sort, rowTarget→entityRef, density, stickyHeader, loading and
 * emptyState. Replaces the ~43 inline table implementations at their
 * consumers' waves.
 *
 * Sorting contract: pass `sort` + `onSort` for controlled sorting (parent
 * owns row order — the kit does NOT re-sort); omit them and mark columns
 * `sortable` for internal sorting. This mirrors controlled/uncontrolled
 * input semantics so tables backed by server-side sort don't double-sort.
 *
 * rowTarget contract: `rowTarget(row) → entityRef` renders the FIRST
 * column's content wrapped in a real anchor (the FQN text is the anchor —
 * COHESION law) and makes the whole row a convenience click zone that
 * delegates to that anchor, so middle-click/copy-link still work.
 */

function columnKey(column) {
  return column.key ?? column.accessor;
}

function cellValue(column, row) {
  if (typeof column.render === "function") return column.render(row);
  const accessor = column.accessor ?? column.key;
  return row?.[accessor];
}

function sortValue(column, row) {
  if (typeof column.sortValue === "function") return column.sortValue(row);
  const accessor = column.accessor ?? column.key;
  return row?.[accessor];
}

function compareValues(a, b) {
  const aNull = a == null || a === "";
  const bNull = b == null || b === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls sort last regardless of direction start
  if (bNull) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

function rowIdentity(row, rowKey, index) {
  return row?.[rowKey] ?? row?.fqn ?? row?.id ?? row?.name ?? index;
}

const ROW_INTERACTIVE = "a, button, input, select, textarea, label, [role='button']";

export function DataTable({
  columns = [],
  rows = [],
  rowKey = "id",
  sort = undefined,
  onSort = null,
  defaultSort = null,
  rowTarget = null,
  navigate = null,
  density = "comfortable",
  stickyHeader = false,
  loading = false,
  loadingRows = 5,
  emptyState = null,
  emptyMessage = "No rows available.",
  caption = "",
  className = "",
}) {
  // All hooks run on every render, before any branching (CLAUDE.md rule).
  const inRouter = useInRouterContext();
  const [internalSort, setInternalSort] = useState(defaultSort);
  const controlled = sort !== undefined || typeof onSort === "function";
  const activeSort = sort !== undefined ? sort : internalSort;

  const sortedRows = useMemo(() => {
    // Controlled mode: the parent owns row order; never re-sort under it.
    if (controlled || !activeSort?.key) return rows;
    const column = columns.find((col) => columnKey(col) === activeSort.key);
    if (!column) return rows;
    const dir = activeSort.dir === "desc" ? -1 : 1;
    return [...rows].sort((a, b) => dir * compareValues(sortValue(column, a), sortValue(column, b)));
  }, [rows, columns, activeSort, controlled]);

  const handleSortClick = (column) => {
    const key = columnKey(column);
    const nextDir = activeSort?.key === key && activeSort?.dir === "asc" ? "desc" : "asc";
    const next = { key, dir: nextDir };
    if (typeof onSort === "function") onSort(next);
    if (sort === undefined) setInternalSort(next);
  };

  const handleRowClick = (event) => {
    // Convenience full-row click: delegate to the row's real anchor unless
    // the user clicked something interactive inside the row.
    if (event.target.closest(ROW_INTERACTIVE)) return;
    const anchor = event.currentTarget.querySelector("a.ax-sys-table-rowlink");
    if (anchor) anchor.click();
  };

  const Anchor = inRouter ? Link : "a";
  const classes = [
    "ax-sys-table-wrap",
    `density-${density === "compact" ? "compact" : "comfortable"}`,
    stickyHeader ? "is-sticky" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const colCount = Math.max(columns.length, 1);
  const showEmpty = !loading && sortedRows.length === 0;

  return (
    <div className={classes}>
      <table className="ax-sys-table" aria-busy={loading || undefined}>
        {caption ? <caption className="ax-sys-visually-hidden">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => {
              const key = columnKey(column);
              const isSorted = activeSort?.key === key;
              const ariaSort = isSorted
                ? activeSort.dir === "desc"
                  ? "descending"
                  : "ascending"
                : undefined;
              return (
                <th
                  key={key}
                  scope="col"
                  aria-sort={column.sortable ? (ariaSort ?? "none") : undefined}
                  className={column.align === "right" ? "align-right" : undefined}
                  style={column.width ? { width: column.width } : undefined}
                >
                  {column.sortable ? (
                    <button
                      type="button"
                      className={`ax-sys-table-sort ${isSorted ? `is-${activeSort.dir}` : ""}`.trim()}
                      onClick={() => handleSortClick(column)}
                    >
                      <span>{column.header ?? column.label}</span>
                      <span className="ax-sys-table-sort-arrow" aria-hidden="true" />
                    </button>
                  ) : (
                    (column.header ?? column.label)
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: loadingRows }, (_, index) => (
                <tr key={`skeleton-${index}`} className="ax-sys-table-skeleton-row" aria-hidden="true">
                  {columns.map((column) => (
                    <td key={columnKey(column)}>
                      <span className="ax-sys-skeleton" />
                    </td>
                  ))}
                </tr>
              ))
            : null}
          {showEmpty ? (
            <tr className="ax-sys-table-empty-row">
              <td colSpan={colCount}>{emptyState ?? <EmptyState title="No rows" body={emptyMessage} />}</td>
            </tr>
          ) : null}
          {!loading
            ? sortedRows.map((row, rowIndex) => {
                const target = rowTarget ? rowTarget(row) : null;
                const href = target ? hrefForRef(target) : null;
                return (
                  <tr
                    key={rowIdentity(row, rowKey, rowIndex)}
                    className={href ? "is-rowlink" : undefined}
                    onClick={href ? handleRowClick : undefined}
                  >
                    {columns.map((column, colIndex) => {
                      const key = columnKey(column);
                      const value = cellValue(column, row);
                      // Honest fallback: absent values render "—", never a
                      // fabricated number (COHESION law #7).
                      const content = value ?? "—";
                      const wrapAsLink = href && colIndex === 0;
                      return (
                        <td key={key} className={column.align === "right" ? "align-right" : undefined}>
                          {wrapAsLink ? (
                            <Anchor
                              {.../** @type {any} */ (inRouter ? { to: href } : { href })}
                              className="ax-sys-table-rowlink"
                              onClick={(event) => {
                                if (!navigate || event.defaultPrevented) return;
                                if (
                                  event.button !== 0 ||
                                  event.metaKey ||
                                  event.ctrlKey ||
                                  event.shiftKey ||
                                  event.altKey
                                )
                                  return;
                                event.preventDefault();
                                navigate(target, { href });
                              }}
                            >
                              {content}
                            </Anchor>
                          ) : (
                            content
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            : null}
        </tbody>
      </table>
    </div>
  );
}

export default DataTable;
