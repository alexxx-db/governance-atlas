/*
 * Wave-A2 query status contract (COHESION_BLUEPRINT "Three system layers" #2,
 * FRONTEND_BLUEPRINT §7). `useAxiomQuery` returns
 * `{ data, status, meta, warnings, refresh, isPolling }` with
 * status ∈ loading | hydrating | available | degraded | unavailable | error.
 *
 * The kit codes against that SHAPE, not the hook (A2 builds the hook in
 * parallel): every component that accepts a `status` prop funnels it through
 * `normalizeStatus` so surfaces can pass either the whole query object or a
 * bare status string and get identical rendering. This is the single point
 * where the kit interprets status — components never read `meta.state`
 * (that predicate lives in lib/envelope.js, owned by A2).
 */

export const QUERY_STATUSES = Object.freeze([
  "loading",
  "hydrating",
  "available",
  "degraded",
  "unavailable",
  "error",
]);

/**
 * Accepts a status string, a `useAxiomQuery`-shaped object, or null.
 * Returns `{ status, warnings, reason, refresh }` or null when there is
 * nothing recognizable — callers treat null as "no status supplied" and
 * render nothing status-related (never guess).
 */
export function normalizeStatus(input) {
  if (!input) return null;
  const raw = typeof input === "string" ? { status: input } : input;
  const status = QUERY_STATUSES.includes(raw.status) ? raw.status : null;
  if (!status) return null;
  const warnings = Array.isArray(raw.warnings)
    ? raw.warnings.filter(Boolean).map(String)
    : [];
  // Honest-unavailability copy: prefer an explicit reason, then the meta
  // emptyReason the lineage contract already ships, then the first warning.
  const reason =
    raw.reason ??
    raw.meta?.reason ??
    raw.meta?.emptyReason ??
    (warnings.length ? warnings[0] : null);
  return {
    status,
    warnings,
    reason: reason == null ? null : String(reason),
    refresh: typeof raw.refresh === "function" ? raw.refresh : null,
  };
}

/** True when the status means data may legitimately be rendered. */
export function statusShowsData(status) {
  return status === "available" || status === "hydrating" || status === "degraded";
}
