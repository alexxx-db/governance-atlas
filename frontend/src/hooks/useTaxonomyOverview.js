// The classification taxonomy overview hook consumed by the Glossary & CDEs
// surface. (Its former sibling useTaxonomyCdeDashboard died in Wave C8: the
// C4 merge kept useCdeDashboard's ["axiom", "cde-dashboard"] key, so the
// taxonomy-scoped duplicate never gained a consumer.)
import { fetchTaxonomyOverview } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * The classification taxonomy overview (namespaces, nodes, terms).
 * @param {{ enabled?: boolean }} [options]
 */
export function useTaxonomyOverview(options = {}) {
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "taxonomy-overview"],
    enabled,
    fetch: (signal) => fetchTaxonomyOverview({ signal }),
    staleTime: 60_000,
    // Same 3s hydration cadence as the inline refetchInterval, now bounded.
    poll: { interval: 3_000, maxAttempts: 20 },
  });
}

export default useTaxonomyOverview;
