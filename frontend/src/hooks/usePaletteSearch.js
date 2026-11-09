// Wave B/C surface hook (unused until CommandPalette's rewrite): replaces
// the palette's hand-rolled debounced fetchDiscoverySearch effect (manual
// AbortController + setTimeout + setLiveSearch state machine) and its
// fire-and-forget glossary fetch. Debounce and min-chars gating live here;
// the palette component becomes purely presentational.
import { useEffect, useState } from "react";
import { fetchDiscoverySearch, fetchGovernanceGlossary } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

// Mirror the palette's tuned constants (CommandPalette.jsx).
export const PALETTE_SEARCH_DEBOUNCE_MS = 250;
export const PALETTE_SEARCH_MIN_CHARS = 2;
export const PALETTE_SEARCH_LIMIT = 8;

/**
 * Debounced live asset search + glossary terms for the command palette.
 *
 * @param {string} query the raw palette input
 * @param {{ enabled?: boolean }} [options]
 * @returns {{
 *   assets: any[],
 *   glossaryTerms: any[],
 *   searching: boolean,
 *   searchError: string,
 *   resolvedQuery: string,
 *   search: ReturnType<typeof useAxiomQuery>,
 *   glossary: ReturnType<typeof useAxiomQuery>,
 * }}
 */
export function usePaletteSearch(query, options = {}) {
  const enabled = options.enabled !== false;
  const trimmed = String(query || "").trim();

  // Debounce the query string itself: the react-query key only changes once
  // the user pauses, so keystrokes never fan out network calls (aborting the
  // in-flight request on key change is react-query's job, not an effect's).
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    if (trimmed.length < PALETTE_SEARCH_MIN_CHARS) {
      setDebouncedQuery("");
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setDebouncedQuery(trimmed);
    }, PALETTE_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [trimmed]);

  const search = useAxiomQuery({
    key: ["palette-search", debouncedQuery.toLowerCase()],
    enabled: enabled && Boolean(debouncedQuery),
    fetch: (signal) =>
      fetchDiscoverySearch(
        { query: debouncedQuery, limit: PALETTE_SEARCH_LIMIT },
        { signal },
      ),
    staleTime: 30_000,
  });

  // Terms group must never block the palette: load once, tolerate failure
  // silently (matches the palette's existing catch-and-continue behavior).
  const glossary = useAxiomQuery({
    key: ["palette-glossary"],
    enabled,
    fetch: () => fetchGovernanceGlossary(),
    staleTime: 5 * 60_000,
  });

  const assets = Array.isArray(search.query.data?.assets)
    ? search.query.data.assets
    : [];
  const glossaryTerms = Array.isArray(glossary.query.data?.glossary)
    ? glossary.query.data.glossary
    : [];

  return {
    assets,
    glossaryTerms,
    // "searching" covers the debounce window too, so the palette can show
    // its spinner from the first keystroke.
    searching:
      enabled &&
      trimmed.length >= PALETTE_SEARCH_MIN_CHARS &&
      (debouncedQuery !== trimmed || search.query.isPending),
    searchError: search.query.isError
      ? search.query.error?.message || "Asset search failed."
      : "",
    resolvedQuery: debouncedQuery,
    search,
    glossary,
  };
}

export default usePaletteSearch;
