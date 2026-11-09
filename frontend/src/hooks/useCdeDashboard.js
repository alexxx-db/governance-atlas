// Wave B/C surface hooks (unused until CdeWorkspace's rewrite): extracted
// from the two inline useQuery declarations in CdeWorkspace.jsx. Query keys
// mirror the inline ones so Wave C adoption is a drop-in with cache
// continuity.
import { fetchCdeDashboard, fetchCdeDetail } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * The Critical Data Elements dashboard (candidates, controls, KPIs).
 * @param {{ enabled?: boolean }} [options]
 */
export function useCdeDashboard(options = {}) {
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "cde-dashboard"],
    enabled,
    fetch: (signal) => fetchCdeDashboard({ signal }),
    staleTime: 60_000,
    // Same 3s hydration cadence as the inline refetchInterval, now bounded.
    poll: { interval: 3_000, maxAttempts: 20 },
  });
}

/**
 * A single CDE's detail record (controls, linked assets, activity).
 * @param {string} cdeId
 * @param {{ enabled?: boolean }} [options]
 */
export function useCdeDetail(cdeId, options = {}) {
  const normalized = String(cdeId || "").trim();
  const enabled = options.enabled !== false && Boolean(normalized);
  return useAxiomQuery({
    key: ["axiom", "cde-detail", normalized],
    enabled,
    fetch: (signal) => fetchCdeDetail(normalized, { signal }),
    staleTime: 60_000,
  });
}

export default useCdeDashboard;
