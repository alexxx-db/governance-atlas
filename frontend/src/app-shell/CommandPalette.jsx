/*
 * app-shell/CommandPalette.jsx — the unified search + command surface (⌘K).
 *
 * Replaces BOTH components/primitives/CommandPalette.jsx and the header's
 * inline TopbarSearch typeahead (Wave B1: "header search + ⌘K palette unified
 * on usePaletteSearch"). Differences from the legacy palette, on purpose:
 *   - Data comes from hooks/usePaletteSearch (debounced live search +
 *     glossary) instead of a hand-rolled AbortController/setTimeout effect.
 *   - "Jump to" rows are generated from nav/routes.js navSections() — the
 *     palette can never disagree with the rail again.
 *   - Every result row is a REAL <a href> resolved via nav/refs (EntityChip
 *     semantics: middle-click/copy work); left-click routes through
 *     useAtlasNavigate.
 *   - "Search Discover for …" row carries the old header-search submit
 *     behavior (Enter on a free-text query lands on Discovery results).
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { AssetTypeIcon } from "../components/primitives/AssetTypeIcon";
import { usePaletteSearch } from "../hooks/usePaletteSearch";
import { refHref } from "../nav/refs.js";
import { navSections } from "../nav/routes.js";
import { railGateAllowed } from "./Rail.jsx";

const SURFACE_SUBTITLES = {
  home: "Executive governance posture",
  discovery: "Find governed data and terms",
  stewardship: "Open governance work queue",
  glossary: "Business terms and critical data elements",
  lineage: "Connected asset graph",
  evidence: "Immutable governance event log",
  admin: "Runtime, integrations, and policy",
  help: "How Governance Atlas works",
  ai: "AI assets, intake, and findings",
  datapact: "DataPact validation results",
};

function ownerDisplayName(owner) {
  if (typeof owner === "string") return owner.trim();
  if (!owner || typeof owner !== "object") return "";
  return String(owner.name || owner.email || owner.ownerEmail || "").trim();
}

function distinctOwners(assets = []) {
  const names = new Set();
  for (const asset of Array.isArray(assets) ? assets : []) {
    const owners = Array.isArray(asset?.owners) ? asset.owners : [];
    for (const owner of owners) {
      const name = ownerDisplayName(owner);
      if (name) names.add(name);
    }
    const single = ownerDisplayName(asset?.owner);
    if (single) names.add(single);
  }
  return [...names].sort((left, right) => left.localeCompare(right));
}

// Substring OR in-order fuzzy match (legacy palette behavior, kept).
function matches(query, target) {
  const q = query.toLowerCase();
  const t = String(target || "").toLowerCase();
  if (!q) return true;
  if (t.includes(q)) return true;
  let j = 0;
  for (const ch of t) {
    if (ch === q[j]) j += 1;
    if (j >= q.length) return true;
  }
  return false;
}

function isModifiedClick(event) {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}

export function CommandPalette({ seedAssets = [], onNavigateRef, onSearchDiscovery, onClose, shell = null }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);
  const { assets: liveAssets, glossaryTerms, searching } = usePaletteSearch(query);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  const owners = useMemo(
    () => distinctOwners([...(Array.isArray(seedAssets) ? seedAssets : []), ...liveAssets]),
    [seedAssets, liveAssets],
  );

  const items = useMemo(() => {
    const trimmed = query.trim();
    const rows = [];
    for (const section of navSections()) {
      for (const item of section.items) {
        // Same gates as the rail: never offer a jump to a surface that is
        // admin-only for this user or not mounted (AI governance flag off).
        if (!railGateAllowed(item.gate, shell)) continue;
        rows.push({
          id: `nav-${item.surface}-${item.path}`,
          group: "Jump to",
          title: item.label,
          subtitle: SURFACE_SUBTITLES[item.surface] || "",
          ref: { surface: item.surface },
        });
      }
    }
    // NOTE (Wave B1): the legacy palette's Favorites/Recent groups read
    // Discovery's private localStorage keys. That storage contract is banned
    // outside lib/prefs.js (and its keys carry the legacy prefix), so the
    // groups return in Wave C1 when Discovery's preference state moves to
    // lib/prefs.js. Live search + nav rows cover the palette's core promise.
    const staticRows = trimmed
      ? rows.filter(
          (row) => matches(trimmed, row.title) || matches(trimmed, row.subtitle) || matches(trimmed, row.group),
        )
      : rows;

    const queryRows = [];
    if (trimmed) {
      // Free-text escape hatch first — the old header-search submit behavior.
      queryRows.push({
        id: `discover-${trimmed}`,
        group: "Search",
        title: `Search Discover for “${trimmed}”`,
        subtitle: "Full catalog search with filters",
        badge: "Search",
        discoveryQuery: trimmed,
        ref: { surface: "discovery", params: { q: trimmed } },
      });
      const seen = new Set(staticRows.map((row) => row.id));
      const pushAssetRow = (asset) => {
        if (!asset?.fqn) return;
        const id = `asset-${asset.fqn}`;
        if (seen.has(id)) return;
        queryRows.push({
          id,
          group: "Assets",
          title: asset.name || asset.fqn,
          subtitle: asset.fqn,
          badge: "Asset",
          asset,
          ref: { kind: "asset", fqn: asset.fqn },
        });
        seen.add(id);
      };
      // Live results lead (server-ranked), seed fuzzy matches fill in.
      for (const asset of liveAssets) pushAssetRow(asset);
      let assetRows = queryRows.length;
      for (const asset of seedAssets || []) {
        if (assetRows >= 20) break;
        if (!asset?.fqn) continue;
        if (
          matches(trimmed, asset.name) ||
          matches(trimmed, asset.fqn) ||
          matches(trimmed, asset.catalog) ||
          matches(trimmed, asset.schema)
        ) {
          pushAssetRow(asset);
          assetRows = queryRows.length;
        }
      }
      let termRows = 0;
      for (const term of glossaryTerms) {
        const name = String(term?.term || term?.name || "").trim();
        if (!name) continue;
        const definition = String(term?.definition || "").trim();
        if (!(matches(trimmed, name) || matches(trimmed, definition) || matches(trimmed, term?.domain))) continue;
        const termId = String(term?.termId || "").trim();
        queryRows.push({
          id: `term-${termId || name}`,
          group: "Glossary terms",
          title: name,
          subtitle: definition || String(term?.domain || "").trim() || "Glossary term",
          badge: "Term",
          ref: { kind: "term", id: termId || name },
        });
        termRows += 1;
        if (termRows >= 8) break;
      }
      let ownerRows = 0;
      for (const owner of owners) {
        if (!matches(trimmed, owner)) continue;
        queryRows.push({
          id: `owner-${owner}`,
          group: "Owners",
          title: owner,
          subtitle: `Search Discover for assets owned by ${owner}`,
          badge: "Owner",
          ref: { kind: "owner", id: owner },
        });
        ownerRows += 1;
        if (ownerRows >= 6) break;
      }
    }
    return [...staticRows, ...queryRows];
  }, [glossaryTerms, liveAssets, owners, query, seedAssets, shell]);

  const runItem = (item) => {
    if (!item) return;
    if (item.discoveryQuery !== undefined) {
      // Fresh Discovery open (legacy state.fresh semantics live in the adapter).
      onSearchDiscovery?.(item.discoveryQuery);
    } else {
      onNavigateRef?.(item.ref);
    }
    onClose?.();
  };

  const handleKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose?.();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(items.length - 1, c + 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runItem(items[cursor]);
    }
  };

  const grouped = useMemo(() => {
    const map = new Map();
    items.forEach((item, index) => {
      if (!map.has(item.group)) map.set(item.group, []);
      map.get(item.group).push({ ...item, _idx: index });
    });
    return [...map.entries()];
  }, [items]);

  return (
    <div aria-label="Search and commands" aria-modal="true" className="ga-cmdk-backdrop" onMouseDown={onClose} role="dialog">
      <div className="ga-cmdk" onMouseDown={(event) => event.stopPropagation()}>
        <div className="ga-cmdk-input-row">
          <span aria-hidden="true" className="ga-cmdk-prefix">⌘</span>
          <input
            aria-label="Search assets, glossary terms, and owners"
            className="ga-cmdk-input"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKey}
            placeholder="Search assets, glossary terms, owners…"
            ref={inputRef}
            type="search"
            value={query}
          />
          <span aria-hidden="true" className="ga-cmdk-hint">Esc to close</span>
        </div>
        <div className="ga-cmdk-list" role="listbox">
          {items.length === 0 ? (
            searching ? (
              // Honest in-flight state: never claim "no matches" while the
              // live query is still out.
              <div aria-busy="true" className="ga-cmdk-empty is-loading" role="status">
                Searching assets, glossary terms, and owners…
              </div>
            ) : (
              <div className="ga-cmdk-empty">
                {query.trim()
                  ? `No matches for "${query.trim()}"`
                  : "Type to search assets, glossary terms, and owners."}
              </div>
            )
          ) : (
            grouped.map(([group, groupItems]) => (
              <div key={group}>
                <div className="ga-cmdk-group">{group}</div>
                {groupItems.map((item) => (
                  <a
                    aria-selected={cursor === item._idx}
                    className={`ga-cmdk-item ${cursor === item._idx ? "is-active" : ""}`.trim()}
                    href={refHref(item.ref)}
                    key={item.id}
                    onClick={(event) => {
                      if (isModifiedClick(event)) return; // native new-tab keeps working
                      event.preventDefault();
                      runItem(item);
                    }}
                    onMouseEnter={() => setCursor(item._idx)}
                    role="option"
                  >
                    <span aria-hidden="true" className="ga-cmdk-item-glyph">
                      {item.asset ? (
                        <AssetTypeIcon asset={item.asset} size="sm" />
                      ) : (
                        <span className="ga-cmdk-generic-glyph">›</span>
                      )}
                    </span>
                    <span className="ga-cmdk-item-text">
                      <span className="ga-cmdk-item-title">{item.title}</span>
                      <span className="ga-cmdk-item-subtitle">{item.subtitle}</span>
                    </span>
                    {item.badge ? (
                      <span aria-hidden="true" className="ga-cmdk-item-badge">{item.badge}</span>
                    ) : null}
                  </a>
                ))}
              </div>
            ))
          )}
          {items.length > 0 && searching ? (
            <div aria-busy="true" className="ga-cmdk-live-status" role="status">
              Searching the live catalog…
            </div>
          ) : null}
        </div>
        <div className="ga-cmdk-footer">
          <span className="ga-cmdk-footer-hint"><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span className="ga-cmdk-footer-hint"><kbd>↵</kbd> open</span>
          <span className="ga-cmdk-footer-hint"><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}

export default CommandPalette;
