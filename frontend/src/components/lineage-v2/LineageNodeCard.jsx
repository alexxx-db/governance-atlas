import { useMemo } from "react";

/**
 * LineageNodeCard — design-faithful card used by LineageCanvasV2.
 *
 * Two variants:
 *  - compact: header + footer only, ~210x86, used for non-table nodes (jobs,
 *    pipelines, dashboards, models, restricted boundary nodes).
 *  - tall: full schema preview with up to 5 columns, ~220x220, used for
 *    table / view nodes where useLineageGraphV2 surfaces column metadata.
 *
 * The component takes a single `node` from useLineageGraphV2's normalized
 * shape and an optional `header` from useLineageNodeHeaders' batch fetch
 * (which carries the UC-grade per-node detail the lineage system tables
 * don't expose: size, files, freshness, type, owner, state). State classes
 * (focus / hover / traced / dimmed) are passed via props so the parent
 * canvas can drive hover-trace highlight behavior with a single React
 * Flow selector.
 */

// Convert an ISO timestamp to a UC-style relative freshness label
// ("3h ago", "2d ago", "5mo ago"). Returns "" for invalid input so
// the card can fall back to the API's pre-formatted foot string.
function relativeTime(iso) {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "";
  const deltaMs = Date.now() - ts;
  if (deltaMs < 0) return "future";
  const minutes = Math.round(deltaMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.round(days / 365);
  return `${years}y ago`;
}

// Backend ships various dash/placeholder strings when a value is
// genuinely unknown ("—", "-", "–", "N/A", "Unknown", "Unassigned").
// These are NOT useful in a lineage card footer — we want to suppress
// them so the user sees what we actually know vs. an empty hyphen.
const PLACEHOLDER_TOKENS = new Set([
  "—",
  "-",
  "–",
  "n/a",
  "na",
  "unknown",
  "unassigned",
  "unavailable",
  "none",
  "null",
]);

function meaningful(value) {
  if (value == null) return null;
  const trimmed = String(value).trim();
  if (!trimmed) return null;
  if (PLACEHOLDER_TOKENS.has(trimmed.toLowerCase())) return null;
  return trimmed;
}

// Pull a UC-equivalent stat bag off the header payload. We prefer the
// batch-fetched `header` (richer fields) and fall back to whatever
// useLineageGraphV2 surfaced from the lineage payload. Always returns
// strings (or null) — the caller renders only non-empty entries.
// Exported so LineageDetailRail (LineageWorkspace.jsx) can reuse the exact
// same header→stats derivation for the selected node — the rail and the card
// must never disagree about what we know for a node (L2).
export function deriveCardStats(node, header) {
  const h = header || {};
  // Rows: header has pre-formatted "1.2M" string from the backend
  // formatter. Lineage payload only has it for the focus node, so prefer
  // header. Filter out placeholder values to avoid "— rows" footer rows.
  const rowCount = meaningful(h.rows) || meaningful(node?.rowCount) || null;

  // Size: backend ships pre-formatted "12.4 GiB" / "823 MiB". UC's lineage
  // panel shows "Size" prominently — this is one of the headline gaps the
  // user called out vs Databricks.
  const size = meaningful(h.size) || null;

  // Files: backend ships count/formatted. Falls behind size in importance
  // but UC shows it on its lineage card, so we mirror that.
  const files = meaningful(h.files) || null;

  // Freshness: try the relative time of the asset's updatedAt timestamp
  // first (most UC-equivalent), then fall back to whatever the lineage
  // adapter surfaced (typically empty). The card renders the relative
  // string and exposes the raw ISO via title for hover.
  const updatedAtIso = meaningful(h.updatedAt) || meaningful(h.lastRefresh) || meaningful(h.refreshedAt) || "";
  const freshnessRel = relativeTime(updatedAtIso);
  const freshness = freshnessRel || meaningful(node?.freshness) || null;
  const freshnessTitle = updatedAtIso ? `Last updated: ${updatedAtIso}` : freshness;

  // Type: prefer the human-readable "Managed" / "External" management
  // type, then fall back to objectType ("Table", "View"), then the raw
  // tableTypeRaw token. UC shows this on its node card under "Type".
  const management = meaningful(h.managementType);
  const objectType = meaningful(h.objectType);
  const rawType = meaningful(h.tableTypeRaw);
  const typeLabel =
    [management, objectType].filter(Boolean).join(" · ") ||
    (rawType ? rawType.replace(/_/g, " ") : "") ||
    meaningful(node?.apiKind) ||
    null;

  // Owner: UC shows the principal owner (user or group) on its node card.
  // Backend sends owners as [{ displayName, email }] — display the most
  // human-readable form available.
  const headerOwners = Array.isArray(h.owners) ? h.owners : [];
  const nodeOwners = Array.isArray(node?.owners) ? node.owners : [];
  const owners = headerOwners.length ? headerOwners : nodeOwners;
  const primaryOwner = owners[0] || null;
  const ownerLabel = primaryOwner
    ? primaryOwner.displayName || primaryOwner.email || primaryOwner.name || ""
    : "";
  const ownerCount = owners.length;
  const ownerTitle = owners
    .map((o) => o?.displayName || o?.email || o?.name)
    .filter(Boolean)
    .join(", ");

  // State: UC's lineage card shows certification + classification badges
  // and a "data is current/stale" pill. We fold those into a single state
  // chip when non-trivial.
  const certification = h.certification || (node?.isCertified ? "Certified" : "");
  const sensitivity = h.sensitivity || node?.classification || "";

  return {
    rowCount,
    size,
    files,
    freshness,
    freshnessTitle,
    typeLabel,
    ownerLabel,
    ownerCount,
    ownerTitle,
    certification,
    sensitivity,
  };
}

function KindGlyph({ kind, size = 14 }) {
  // Inline SVG glyphs so we don't pull lucide into the canvas bundle.
  const stroke = /** @type {const} */ ({
    stroke: "currentColor",
    strokeWidth: 1.6,
    fill: "none",
    strokeLinecap: "round",
    strokeLinejoin: "round",
  });
  const paths = {
    table: <><rect x="3" y="4" width="18" height="16" rx="1" {...stroke} /><path d="M3 9h18M3 14h18M9 4v16M15 4v16" {...stroke} /></>,
    pipeline: <><circle cx="6" cy="6" r="2.4" {...stroke} /><circle cx="18" cy="6" r="2.4" {...stroke} /><circle cx="6" cy="18" r="2.4" {...stroke} /><circle cx="18" cy="18" r="2.4" {...stroke} /><path d="M8.4 6h7.2M8.4 18h7.2M6 8.4v7.2M18 8.4v7.2" {...stroke} /></>,
    job: <><circle cx="12" cy="12" r="9" {...stroke} /><path d="M12 7v5l3 2" {...stroke} /></>,
    notebook: <><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4z" {...stroke} /><path d="M9 8h7M9 12h7M9 16h4" {...stroke} /></>,
    "saved-query": <><circle cx="11" cy="11" r="6.5" {...stroke} /><path d="M21 21l-5-5" {...stroke} /></>,
    dashboard: <><rect x="3" y="3" width="8" height="8" rx="1" {...stroke} /><rect x="13" y="3" width="8" height="5" rx="1" {...stroke} /><rect x="13" y="10" width="8" height="11" rx="1" {...stroke} /><rect x="3" y="13" width="8" height="8" rx="1" {...stroke} /></>,
    model: <><circle cx="12" cy="12" r="3" {...stroke} /><circle cx="12" cy="4" r="2" {...stroke} /><circle cx="12" cy="20" r="2" {...stroke} /><circle cx="4" cy="12" r="2" {...stroke} /><circle cx="20" cy="12" r="2" {...stroke} /><path d="M12 6v3M12 15v3M6 12h3M15 12h3" {...stroke} /></>,
    udf: <><path d="M4 7h2c1 0 2 1 2 2v6c0 1-1 2-2 2H4M20 7h-2c-1 0-2 1-2 2v6c0 1 1 2 2 2h2" {...stroke} /></>,
    volume: <><ellipse cx="12" cy="6" rx="8" ry="3" {...stroke} /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" {...stroke} /></>,
    restricted: <><rect x="5" y="11" width="14" height="9" rx="1" {...stroke} /><path d="M8 11V8a4 4 0 0 1 8 0v3" {...stroke} /></>,
  };
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
    >
      {paths[kind] || paths.table}
    </svg>
  );
}

function CertifiedBadge() {
  return (
    <span
      aria-label="Certified by data steward"
      className="ax-lineage-v2-card-cert"
      title="Certified by data steward"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" width="11" height="11">
        <path
          d="M12 2l2.5 2.4 3.4-.5.6 3.4 3 1.7-1.5 3.1 1.5 3.1-3 1.7-.6 3.4-3.4-.5L12 22l-2.5-2.4-3.4.5-.6-3.4-3-1.7L4 12 2.5 8.9l3-1.7.6-3.4 3.4.5z"
          fill="color-mix(in srgb, var(--ax-success) 18%, transparent)"
          stroke="var(--ax-success)"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path d="M9 12l2 2 4-4" fill="none" stroke="var(--ax-success)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

function PiiBadge() {
  return (
    <span
      aria-label="Contains PII"
      className="ax-lineage-v2-card-pii"
      title="Contains PII"
    >
      PII
    </span>
  );
}

function ClassificationBadge({ classification }) {
  if (!classification) return null;
  const lower = classification.toLowerCase();
  const tone =
    lower.includes("restricted") ? "crit" :
    lower.includes("confidential") ? "warn" :
    lower.includes("internal") ? "info" : "neutral";
  return (
    <span
      className={`ax-lineage-v2-card-class tone-${tone}`}
      title={`Sensitivity: ${classification}`}
    >
      {classification}
    </span>
  );
}

function FootStat({ glyph, label, title }) {
  return (
    <span className="ax-lineage-v2-card-footstat" title={title || undefined}>
      {glyph}
      <span>{label}</span>
    </span>
  );
}

export function LineageNodeCard({
  node,
  header = null,
  variant = "compact",
  isFocus = false,
  isHovered = false,
  isSelected = false,
  isTraced = true,
  isDimmed = false,
  selectedColumnName = "",
  onClick,
  onColumnSelect,
  onOpenAsset = null,
  databricksHref = "",
}) {
  const visibleColumns = Array.isArray(node?.columns) ? node.columns.slice(0, 5) : [];
  const totalColumns = Number(node?.totalColumns) || visibleColumns.length;
  const hiddenColumns = Math.max(0, totalColumns - visibleColumns.length);
  // Derive UC-equivalent stat strings from the (optional) batch-fetched
  // header. This is what fills the "size / freshness / type / owner"
  // gap vs Databricks UC's native lineage UX.
  const stats = useMemo(() => deriveCardStats(node, header), [node, header]);

  const stateClass = useMemo(() => {
    const classes = [];
    if (isDimmed) classes.push("is-dimmed");
    else if (isFocus) classes.push("is-focus");
    else if (isHovered) classes.push("is-hovered");
    else if (!isTraced) classes.push("is-untraced");
    // is-selected layers ON TOP of focus/hover (it's an outline, not a
    // background). Both focus and selected can be true at once when the
    // user has the URL focus selected (the default case).
    if (isSelected && !isFocus) classes.push("is-selected");
    return classes.join(" ");
  }, [isDimmed, isFocus, isHovered, isSelected, isTraced]);

  const navigable = node?.isOpenable !== false;

  const handleClick = (event) => {
    if (!onClick) return;
    // Columns and the action strip own their own clicks — a click there must
    // not bubble to the card's select/re-anchor behavior.
    if (event.target.closest?.(".ax-lineage-v2-card-col")) return;
    if (event.target.closest?.(".ax-lineage-v2-card-actions")) return;
    onClick(node);
  };

  // Node-level affordances (owner direction #2c). Both are permission-honest:
  // Asset 360 opens the in-app record (destination surfaces the truth), and
  // the Databricks link is only rendered when we can build a real Catalog
  // Explorer URL. Only navigable (openable, real-FQN) nodes get them.
  const showActions = navigable && Boolean(node?.fqn);
  const handleOpenAsset = (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (node?.fqn) onOpenAsset?.(node.fqn);
  };

  const handleColumnClick = (event, column) => {
    event.preventDefault();
    event.stopPropagation();
    if (!column?.name) return;
    onColumnSelect?.(node, column);
  };

  return (
    <div
      aria-current={isFocus ? "true" : undefined}
      className={`ax-lineage-v2-card ax-lineage-v2-card-${variant} ${stateClass}`.trim()}
      data-node-fqn={node?.fqn || undefined}
      data-node-kind={node?.kind || undefined}
      data-navigable={navigable ? "true" : "false"}
      onClick={handleClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(event) => {
        if (!onClick) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick(node);
        }
      }}
    >
      <header className="ax-lineage-v2-card-head">
        <span aria-hidden="true" className="ax-lineage-v2-card-glyph">
          <KindGlyph kind={node?.kind || "table"} />
        </span>
        <span className="ax-lineage-v2-card-title-wrap">
          {/*
            Single-FOCUS rule (persona audit P2): the accumulated canvas can
            hold a stale node copy whose API kicker still says "Focus" from a
            previous payload. Only the card the canvas marks isFocus may show
            the FOCUS kicker; stale "Focus" kickers are suppressed rather
            than rendered as a second FOCUS designation.
          */}
          {(() => {
            const kickerLabel = isFocus
              ? node?.kicker || "Focus"
              : /^focus$/i.test(String(node?.kicker || "")) ? "" : node?.kicker;
            return kickerLabel ? (
              <span className="ax-lineage-v2-card-kicker">{kickerLabel}</span>
            ) : null;
          })()}
          <span className="ax-lineage-v2-card-title" title={node?.label || node?.fqn || ""}>
            {node?.label || "Unknown"}
          </span>
          <span className="ax-lineage-v2-card-path">{node?.subtitle || ""}</span>
        </span>
        {node?.isCertified ? <CertifiedBadge /> : null}
      </header>

      {variant === "tall" && visibleColumns.length ? (
        <div className="ax-lineage-v2-card-cols">
          {visibleColumns.map((col) => (
            <button
              className={`ax-lineage-v2-card-col ${
                selectedColumnName && selectedColumnName === col.name ? "is-selected" : ""
              }`.trim()}
              key={col.name}
              onClick={(event) => handleColumnClick(event, col)}
              title={`Trace column lineage for ${col.name}`}
              type="button"
            >
              <span className="ax-lineage-v2-card-col-name">{col.name}</span>
              <span className="ax-lineage-v2-card-col-type">
                {String(col.type || "").toUpperCase()}
              </span>
            </button>
          ))}
          {hiddenColumns > 0 ? (
            <div className="ax-lineage-v2-card-col-more">
              +{hiddenColumns} more {hiddenColumns === 1 ? "column" : "columns"}
            </div>
          ) : null}
        </div>
      ) : null}

      {(node?.classification || node?.containsPii) && variant === "tall" ? (
        <div className="ax-lineage-v2-card-chiprow">
          {node?.containsPii ? <PiiBadge /> : null}
          {node?.classification ? <ClassificationBadge classification={node.classification} /> : null}
        </div>
      ) : null}

      <footer className="ax-lineage-v2-card-foot">
        {/*
          Per-node footer renders UC-grade stats (type · size · rows ·
          freshness · owner) derived from the batch-fetched asset header.
          When the header hasn't loaded yet OR the asset is a lineage-only
          reference with no header detail, we fall back to the API's
          pre-formatted foot strings ("Table", "Metadata unavailable")
          instead of showing "Metadata pending".
        */}
        {stats.typeLabel ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <rect x="3" y="4" width="18" height="16" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M3 9h18M9 4v16" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            }
            label={stats.typeLabel}
            title={`Type: ${stats.typeLabel}`}
          />
        ) : null}
        {stats.size ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <path d="M4 7h16v10H4z" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M4 11h16M4 15h16" stroke="currentColor" strokeWidth="1.2" />
              </svg>
            }
            label={stats.size}
            title={`Size on storage: ${stats.size}${stats.files ? ` · ${stats.files} files` : ""}`}
          />
        ) : null}
        {stats.rowCount ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            }
            label={`${stats.rowCount} rows`}
            title={`${stats.rowCount} rows reported by Unity Catalog`}
          />
        ) : null}
        {stats.freshness ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            }
            label={stats.freshness}
            title={stats.freshnessTitle || `Freshness: ${stats.freshness}`}
          />
        ) : null}
        {stats.ownerLabel ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <circle cx="12" cy="8" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M5 21a7 7 0 0 1 14 0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            }
            label={
              stats.ownerCount > 1
                ? `${stats.ownerLabel} +${stats.ownerCount - 1}`
                : stats.ownerLabel
            }
            title={stats.ownerTitle || stats.ownerLabel}
          />
        ) : null}
        {node?.recentActivityCount ? (
          <FootStat
            glyph={
              <svg aria-hidden="true" viewBox="0 0 24 24" width="10" height="10">
                <path d="M3 12h4l3-7 4 14 3-7h4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            }
            label={
              node.recentActivityCount === 1 ? "1 recent" : `${node.recentActivityCount} recent`
            }
            title={`${node.recentActivityCount} recent lineage events`}
          />
        ) : null}
        {!stats.typeLabel &&
        !stats.size &&
        !stats.rowCount &&
        !stats.freshness &&
        !stats.ownerLabel &&
        !node?.recentActivityCount ? (
          // Header not yet loaded AND no derived metadata — surface the
          // pre-formatted lineage-payload foot strings. They're already
          // honest ("Table" for visible nodes; "Metadata unavailable"
          // when the asset is lineage-only).
          (node?.foot || []).length ? (
            (node.foot || []).slice(0, 2).map((line, idx) => (
              <span
                className={`ax-lineage-v2-card-footstat ${
                  // "Not visible to your account" (restricted, L9) and
                  // "Loading metadata…" (cold-cache initial profile, L4)
                  // are status lines, not stats — render them muted.
                  /unavailable|pending|not visible|loading/i.test(line) ? "is-empty" : ""
                }`.trim()}
                key={`${line}-${idx}`}
                title={line}
              >
                {line}
              </span>
            ))
          ) : (
            <span className="ax-lineage-v2-card-footstat is-empty">Loading header…</span>
          )
        ) : null}
      </footer>

      {showActions ? (
        <div className="ax-lineage-v2-card-actions">
          {onOpenAsset ? (
            <button
              className="ax-lineage-v2-card-action"
              onClick={handleOpenAsset}
              title={`Open ${node?.label || node?.fqn || "asset"} in Asset 360`}
              type="button"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" width="11" height="11">
                <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
                <path d="M12 8v8M8 12h8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
              <span>Asset 360</span>
            </button>
          ) : null}
          {databricksHref ? (
            <a
              className="ax-lineage-v2-card-action"
              href={databricksHref}
              onClick={(event) => event.stopPropagation()}
              rel="noreferrer noopener"
              target="_blank"
              title={`Open ${node?.label || node?.fqn || "asset"} in Databricks Catalog Explorer`}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" width="11" height="11">
                <path d="M14 4h6v6M20 4l-9 9M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Databricks</span>
            </a>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default LineageNodeCard;
