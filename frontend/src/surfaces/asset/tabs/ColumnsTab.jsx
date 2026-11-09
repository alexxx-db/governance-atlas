import "../asset.css";
import { DataTable, EntityChip, SectionCard } from "../../../components/system";
import { termRef } from "../format";

/*
 * Columns tab (teardown P2-9): Name / Type / Description always; a Glossary
 * column ONLY when at least one column actually carries a column-scoped
 * glossary link — the header never promises a mapping the data model lacks.
 * (Sensitivity/Policy-tag columns are deliberately absent: no column-level
 * source exists, and regex-derived pseudo-columns are banned.)
 */

function columnHasGlossary(column) {
  return (
    (Array.isArray(column?.glossaryLinks) && column.glossaryLinks.length > 0) ||
    (Array.isArray(column?.glossaryTerms) && column.glossaryTerms.length > 0)
  );
}

export function ColumnsTab({ asset, loading, highlightCol = "" }) {
  const rows = Array.isArray(asset?.columns) ? asset.columns : [];
  const hasGlossary = rows.some(columnHasGlossary);
  const highlight = String(highlightCol || "").trim();

  /** @type {any[]} */
  const columns = [
    {
      key: "name",
      header: "Column",
      sortable: true,
      sortValue: (row) => row.name,
      render: (row) => (
        <span
          className={`ax-asset-col-name ${highlight && row.name === highlight ? "is-highlight" : ""}`.trim()}
        >
          {row.name}
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      sortable: true,
      sortValue: (row) => row.type,
      render: (row) => (row.type ? <code className="ax-asset-col-type">{row.type}</code> : null),
    },
    {
      key: "description",
      header: "Description",
      render: (row) => {
        const text = String(row.description || "").trim();
        return text && text !== "No description" ? text : null;
      },
    },
  ];
  if (hasGlossary) {
    columns.push({
      key: "glossary",
      header: "Glossary term",
      render: (row) => {
        const links = Array.isArray(row.glossaryLinks) && row.glossaryLinks.length
          ? row.glossaryLinks
          : Array.isArray(row.glossaryTerms)
            ? row.glossaryTerms
            : [];
        const refs = links.map(termRef).filter(Boolean);
        if (!refs.length) return null;
        return (
          <span className="ax-asset-chip-row">
            {refs.map((ref, index) => (
              <EntityChip key={ref.id || ref.label || index} entity={ref} appearance="inline" />
            ))}
          </span>
        );
      },
    });
  }

  return (
    <SectionCard
      title="Columns"
      subtitle={rows.length ? `${rows.length} columns from the live schema.` : ""}
    >
      <DataTable
        columns={columns}
        rows={rows}
        rowKey="name"
        loading={Boolean(loading && !rows.length)}
        emptyMessage="Unity Catalog returned no columns for this asset."
        caption="Asset columns"
        stickyHeader
      />
    </SectionCard>
  );
}

export default ColumnsTab;
