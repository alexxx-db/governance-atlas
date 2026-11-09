import { Badge, DataTable, EmptyState, EntityChip } from "../../components/system";
import {
  formatShortDate,
  looksLikeEmail,
  priorityBadgeTone,
  priorityShortLabel,
  slaBadgeTone,
  slaLabel,
  slaPolicyNote,
  textValue,
  workItemDisplayId,
  workItemFullId,
} from "./format.js";

/*
 * surfaces/stewardship/StewardshipQueue.jsx — the ONE queue table (Wave C3).
 * DataTable from the system kit; every entity mention is an EntityChip:
 *   GOV ids  → /stewardship?item=GOV-…   (left-click keeps the current lens
 *              params via the select adapter; middle-click/copy get the
 *              canonical deep link)
 *   assets   → /assets/<fqn>
 *   terms    → /glossary/<termId>        (absorbed Inbox: term reviews are
 *              typed rows in the same queue, badged "Term review")
 *   owners   → /discovery?q=owner:"…"
 */

function itemCaption(item) {
  if (item.itemKind === "term-review") {
    return textValue(item.detail, "No definition recorded yet");
  }
  if (item.age) return `Age ${item.age}`;
  if (item.createdAt) return `Created ${formatShortDate(item.createdAt)}`;
  return "Age unavailable";
}

function IdCell({ item, selectedId, onSelect }) {
  if (item.itemKind === "term-review") {
    // Term reviews are resolved in the Glossary — the id cell IS the door.
    return (
      <EntityChip
        appearance="inline"
        className="ax-stew-id-chip"
        entity={{ kind: "term", id: item.termId || item.title, label: item.termId || "Term" }}
      />
    );
  }
  const displayId = workItemDisplayId(item);
  return (
    <span title={workItemFullId(item) || displayId}>
      <EntityChip
        appearance="inline"
        className={`ax-stew-id-chip is-mono ${item.id === selectedId ? "is-selected" : ""}`.trim()}
        entity={{ kind: "request", id: displayId, label: displayId }}
        // Plain left-click focuses the detail panel while PRESERVING the
        // active lens/asset params; the href stays the canonical deep link.
        navigate={() => onSelect(item)}
      />
    </span>
  );
}

export function StewardshipQueue({
  items = [],
  loading = false,
  selectedId = "",
  onSelect,
  bulkSelection = new Set(),
  onToggleBulk,
  bulkDisabled = false,
  emptyState = null,
}) {
  const columns = [
    {
      key: "select",
      header: <span className="ax-sys-visually-hidden">Select</span>,
      width: "36px",
      render: (item) =>
        item.itemKind === "request" && item.requestId ? (
          <input
            aria-label={`Select ${workItemDisplayId(item)} for bulk actions`}
            checked={bulkSelection.has(item.id)}
            className="ax-stew-bulk-checkbox"
            disabled={bulkDisabled}
            onChange={() => onToggleBulk?.(item.id)}
            type="checkbox"
          />
        ) : (
          <span aria-hidden="true" />
        ),
    },
    {
      key: "id",
      header: "ID",
      render: (item) => <IdCell item={item} onSelect={onSelect} selectedId={selectedId} />,
    },
    {
      key: "item",
      header: "Item",
      render: (item) => (
        <span className="ax-stew-item-cell">
          <strong>{item.kind}</strong>
          <small>{itemCaption(item)}</small>
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      render: (item) =>
        item.itemKind === "term-review" ? (
          <Badge size="sm" tone="accent">Term review</Badge>
        ) : (
          <Badge size="sm" tone="neutral">{textValue(item.typeLabel, "Request")}</Badge>
        ),
    },
    {
      key: "asset",
      header: "Asset",
      render: (item) =>
        item.assetFqn ? (
          <EntityChip
            appearance="inline"
            className="ax-stew-asset-chip"
            entity={{ kind: "asset", fqn: item.assetFqn }}
          />
        ) : (
          "—"
        ),
    },
    {
      key: "assigned",
      header: "Assigned",
      render: (item) => {
        const assigned = textValue(item.assigned, "Unassigned");
        if (assigned !== "Unassigned" && looksLikeEmail(assigned)) {
          // Every rendered email is the one owner-search link (COHESION law).
          return <EntityChip appearance="inline" entity={{ kind: "owner", id: assigned }} />;
        }
        return assigned;
      },
    },
    {
      key: "sla",
      header: "SLA",
      render: (item) =>
        item.itemKind === "term-review" ? (
          "—"
        ) : (
          <span title={slaPolicyNote(item) || undefined}>
            <Badge size="sm" tone={slaBadgeTone(item)}>{slaLabel(item)}</Badge>
          </span>
        ),
    },
    {
      key: "priority",
      header: "Priority",
      render: (item) =>
        item.itemKind === "term-review" ? (
          "—"
        ) : (
          <Badge size="sm" tone={priorityBadgeTone(item.priority)}>
            {priorityShortLabel(item.priority)}
          </Badge>
        ),
    },
  ];

  return (
    <DataTable
      caption="Governance work queue"
      className="ax-stew-queue-table"
      columns={columns}
      density="compact"
      emptyState={emptyState ?? <EmptyState title="No work items" body="Nothing in the queue matches this view." />}
      loading={loading}
      loadingRows={6}
      rows={items}
    />
  );
}

export default StewardshipQueue;
