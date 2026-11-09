// Asset-FQN suggestions for autofilling asset inputs (new work item, evidence
// asset filters). Fetches a bounded slice of the visible-asset inventory ONCE
// via discovery search (empty query) and returns the FQN list for a client-side
// SuggestInput/datalist filter — the same shape as useWorkspaceRoster.
//
// Visibility-scoped by the backend like the rest of discovery; if the fetch is
// degraded the list is empty and callers fall back to free text.
import { useMemo } from "react";
import { fetchDiscoverySearch } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

export function useAssetSuggestions(options = {}) {
  const enabled = options.enabled !== false;
  const limit = Number.isFinite(options.limit) ? options.limit : 250;
  const { query } = useAxiomQuery({
    key: ["axiom", "asset-suggestions", limit],
    fetch: (signal) => fetchDiscoverySearch({ query: "", limit }, { signal }),
    enabled,
    // The visible inventory changes rarely within a session; cache generously.
    staleTime: 5 * 60_000,
    retry: false,
  });

  const fqns = useMemo(() => {
    const assets = Array.isArray(query.data?.assets) ? query.data.assets : [];
    const seen = new Set();
    const out = [];
    for (const asset of assets) {
      const fqn = String(asset?.fqn || asset?.assetFqn || "").trim();
      if (!fqn || seen.has(fqn)) continue;
      seen.add(fqn);
      out.push(fqn);
    }
    return out;
  }, [query.data]);

  return { fqns, loading: enabled && query.isPending };
}

export default useAssetSuggestions;
