// Audit-evidence hooks for the Evidence surface (surfaces/evidence, Wave C5):
// the evidence feed + server-filtered events extracted from the deleted
// AuditBrowserWorkspace's inline useQuery declarations. Query keys mirror the
// legacy inline ones for cache continuity.
import { fetchAuditEvents, fetchAuditEvidence } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

// Must match the backend default/max (AUDIT_EVIDENCE_DEFAULT_LIMIT = 500).
export const AUDIT_EVIDENCE_DEFAULT_LIMIT = 500;

/**
 * "24h" | "7d" | "30d" | "90d" → ISO floor for the server-side filter.
 * Any other value (including "all") returns "" → no floor → unbounded window.
 */
export function auditRangeSinceIso(range, now = Date.now()) {
  const hours = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30, "90d": 24 * 90 }[range];
  if (!hours) return "";
  return new Date(now - hours * 3_600_000).toISOString();
}

/**
 * The main audit-evidence feed.
 * @param {{ dateRange?: string, limit?: number, enabled?: boolean }} [options]
 */
export function useAuditEvidence(options = {}) {
  const dateRange = options.dateRange || "24h";
  const limit = Number.isFinite(Number(options.limit))
    ? Math.max(1, Math.trunc(Number(options.limit)))
    : AUDIT_EVIDENCE_DEFAULT_LIMIT;
  const enabled = options.enabled !== false;
  return useAxiomQuery({
    key: ["axiom", "audit-evidence", dateRange, limit],
    enabled,
    fetch: (signal) => fetchAuditEvidence({ dateRange, limit, signal }),
    // Keep the previous range's rows on screen while the new range loads
    // (matches the inline `placeholderData: (prev) => prev`).
    placeholderData: (previousData) => previousData,
    retry: false,
    staleTime: 60_000,
    // Same 3s hydration cadence as the inline refetchInterval, now bounded.
    poll: { interval: 3_000, maxAttempts: 20 },
  });
}

/**
 * Server-side structured filters (actor / action / target asset): the
 * /api/audit/events endpoint applies the same steward/admin gate +
 * visibility scoping as the main feed, so filtered rows can never leak more
 * than the page shows.
 *
 * @param {{ actorEmail?: string, action?: string, entityFqn?: string, since?: string, limit?: number }} [filters]
 * @param {{ enabled?: boolean }} [options]
 */
export function useAuditEvents(filters = {}, options = {}) {
  const actorEmail = String(filters.actorEmail || "").trim();
  const action = String(filters.action || "").trim();
  const entityFqn = String(filters.entityFqn || "").trim();
  const since = String(filters.since || "").trim();
  const limit = Number.isFinite(Number(filters.limit))
    ? Math.max(1, Math.trunc(Number(filters.limit)))
    : AUDIT_EVIDENCE_DEFAULT_LIMIT;
  const hasFilters = Boolean(actorEmail || action || entityFqn);
  // Filters drive enablement (matches the inline `serverFiltersActive` gate):
  // an unfiltered call must not duplicate the main evidence feed.
  const enabled = options.enabled !== false && hasFilters;
  return useAxiomQuery({
    key: ["axiom", "audit-events", actorEmail, action, entityFqn, since],
    enabled,
    fetch: (signal) =>
      fetchAuditEvents({ actorEmail, action, entityFqn, since, limit }, { signal }),
    retry: false,
    staleTime: 60_000,
  });
}

export default useAuditEvents;
