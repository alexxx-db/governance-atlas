// Wave B/C surface hooks (unused until AdminWorkspace's rewrite): extracted
// from the two inline useQuery declarations in AdminWorkspace.jsx (control
// center dashboard + metastore truth check). Query keys mirror the inline
// ones so Wave C adoption is a drop-in with cache continuity.
import { fetchAdminControlCenter, fetchAdminTruthCheck } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * The admin control-center dashboard. `enabled` carries the admin role gate
 * (`adminRoleAllowed(shell)`) — the caller decides, the hook never guesses.
 * @param {{ enabled?: boolean }} [options]
 */
export function useAdminControlCenter(options = {}) {
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "admin-control-center"],
    enabled,
    fetch: (signal) => fetchAdminControlCenter({ signal }),
    retry: false,
    staleTime: 60_000,
    // Same 3s hydration cadence as the inline refetchInterval, now bounded.
    poll: { interval: 3_000, maxAttempts: 20 },
  });
}

/**
 * Metastore truth check (counts catalogs/schemas/tables in
 * system.information_schema vs the visible-asset pipeline). Admin-only;
 * `enabled` carries the gate.
 * @param {{ enabled?: boolean }} [options]
 */
export function useAdminTruthCheck(options = {}) {
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "admin-truth-check"],
    enabled,
    fetch: (signal) => fetchAdminTruthCheck({ signal }),
    retry: false,
    staleTime: 60_000,
  });
}

export default useAdminControlCenter;
