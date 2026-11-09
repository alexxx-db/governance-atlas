// Wave B/C surface hook (unused until GovernanceWorkspace's rewrite):
// replaces BOTH of today's bypasses of the hooks layer for the same
// endpoint —
//   - GovernanceWorkspace.jsx's imperative fetchGovernanceWorkbench with a
//     hand-rolled AbortController / cancelled-flag / setNorthstarLoading
//     state machine (no query key, no cache), and
//   - InboxPage.jsx's inline useQuery under the divergent
//     ["inbox", "governance-workbench"] key.
// ONE canonical key so every consumer shares one cache entry and one
// invalidation point.
import { fetchGovernanceWorkbench } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

export const GOVERNANCE_WORKBENCH_KEY = ["axiom", "governance-workbench"];

/**
 * @param {{ enabled?: boolean, staleTime?: number }} [options]
 */
export function useGovernanceWorkbench(options = {}) {
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: GOVERNANCE_WORKBENCH_KEY,
    enabled,
    fetch: (signal) => fetchGovernanceWorkbench({ signal }),
    staleTime: options.staleTime ?? 60_000,
    // Same 3s hydration cadence as every operations surface, bounded (~1min).
    poll: { interval: 3_000, maxAttempts: 20 },
  });
}

export default useGovernanceWorkbench;
