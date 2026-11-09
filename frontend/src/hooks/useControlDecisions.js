// Governance "controls in action" decisions feed for the Admin Control Center's
// Policy tab. Wraps GET /api/governance/control-decisions via useAxiomQuery so
// the panel renders the real steward review log (approvals / rejections /
// status updates) alongside the payload's honest enforcement caveat — these are
// governance REVIEW decisions, not access-enforcement events.
import { fetchControlDecisions } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * Recent governance control decisions.
 * `enabled` carries the admin gate — the caller decides (the Admin surface is
 * already admin-gated upstream); the hook never guesses.
 * @param {{ enabled?: boolean, limit?: number }} [options]
 */
export function useControlDecisions(options = {}) {
  const enabled = options.enabled !== false;
  const { limit } = options;
  const { data, status, refresh, query } = useAxiomQuery({
    key: ["admin", "control-decisions"],
    enabled,
    fetch: (signal) => fetchControlDecisions({ signal, limit }),
    retry: false,
    staleTime: 30_000,
  });

  const payload = data || {};
  const decisions = Array.isArray(payload.decisions) ? payload.decisions : [];
  const summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};

  return {
    decisions,
    summary,
    enforcementNote: payload.enforcementNote || "",
    status,
    loading: query.isPending && !query.data,
    error: query.isError ? query.error : null,
    refresh,
  };
}

export default useControlDecisions;
