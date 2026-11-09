import "./discovery.css";
import { useState } from "react";
import { Button } from "../../components/system";
import { readSavedSearches, writeSavedSearches } from "../../lib/prefs";

/*
 * Local-browser saved searches (Wave C1 port). Persisted through lib/prefs.js
 * (migrated from the legacy storage key) — honestly labeled as
 * local-only. Entry shape: { id, name, savedAt, query, cdeOnly, views, types,
 * catalogs, domains, tiers, certifications, sensitivities,
 * businessCriticalities }.
 */

export const SAVED_SEARCH_FILTER_KEYS = [
  "views",
  "types",
  "catalogs",
  "domains",
  "tiers",
  "certifications",
  "sensitivities",
  "businessCriticalities",
];

export function savedSearchFromFilters(name, filters) {
  const entry = {
    id: `saved-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
    name: String(name || "").trim(),
    savedAt: new Date().toISOString(),
    query: String(filters?.query || ""),
    cdeOnly: Boolean(filters?.cdeOnly),
  };
  for (const key of SAVED_SEARCH_FILTER_KEYS) {
    entry[key] = Array.isArray(filters?.[key]) ? [...filters[key]] : [];
  }
  return entry;
}

function savedSearchSummary(entry) {
  const parts = [];
  if (String(entry?.query || "").trim()) parts.push(`"${String(entry.query).trim()}"`);
  const filterCount =
    SAVED_SEARCH_FILTER_KEYS.reduce(
      (sum, key) => sum + (Array.isArray(entry?.[key]) ? entry[key].length : 0),
      0,
    ) + (entry?.cdeOnly ? 1 : 0);
  if (filterCount) parts.push(`${filterCount} filter${filterCount === 1 ? "" : "s"}`);
  return parts.join(" · ") || "Empty scope (matches everything)";
}

export function DiscoverySavedSearches({ filters, onApply, onClose }) {
  const [savedSearches, setSavedSearches] = useState(() => readSavedSearches());
  const [draftName, setDraftName] = useState("");

  const saveCurrentSearch = () => {
    const name = draftName.trim();
    if (!name) return;
    const entry = savedSearchFromFilters(name, filters);
    setSavedSearches((current) => {
      // Same name replaces the previous save so re-saving a scope updates it.
      const next = [entry, ...current.filter((item) => item.name !== name)].slice(0, 20);
      writeSavedSearches(next);
      return next;
    });
    setDraftName("");
  };

  const deleteSavedSearch = (id) => {
    setSavedSearches((current) => {
      const next = current.filter((item) => item.id !== id);
      writeSavedSearches(next);
      return next;
    });
  };

  return (
    <div aria-label="Saved searches" className="ax-disc-saved-searches" role="dialog">
      <div className="ax-disc-saved-searches-save">
        <label>
          <span>Save current search as</span>
          <input
            aria-label="Saved search name"
            onChange={(event) => setDraftName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                saveCurrentSearch();
              }
            }}
            placeholder="e.g. Finance PII tables"
            value={draftName}
          />
        </label>
        <Button
          disabled={!draftName.trim()}
          onClick={saveCurrentSearch}
          title={
            draftName.trim()
              ? "Save the current query and filters to this browser."
              : "Name the saved search to store the current query and filters."
          }
          variant="secondary"
        >
          Save current search
        </Button>
        <small>{savedSearchSummary(savedSearchFromFilters(draftName || "draft", filters))} · Local</small>
      </div>
      {savedSearches.length ? (
        <ul className="ax-disc-saved-searches-list">
          {savedSearches.map((entry) => (
            <li key={entry.id}>
              <button
                aria-label={`Apply saved search ${entry.name}`}
                className="ax-disc-saved-search-apply"
                onClick={() => {
                  onApply?.(entry);
                  onClose?.();
                }}
                title={`Apply saved search ${entry.name}`}
                type="button"
              >
                <strong>{entry.name}</strong>
                <span>{savedSearchSummary(entry)}</span>
              </button>
              <Button
                aria-label={`Delete saved search ${entry.name}`}
                onClick={() => deleteSavedSearch(entry.id)}
                title="Removes this saved search from this browser only."
                variant="tertiary"
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ax-disc-support-copy">
          No saved searches in this browser yet. Set a query or filters, then save them here.
        </p>
      )}
      <div className="ax-disc-saved-searches-foot">
        <span>Saved searches live in this browser&apos;s local storage.</span>
        <Button onClick={onClose} variant="tertiary">
          Close
        </Button>
      </div>
    </div>
  );
}

export default DiscoverySavedSearches;
