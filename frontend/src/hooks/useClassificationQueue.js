// A9.4 — classification / PII recommendation queue for the Evidence surface.
//
// GET /api/classification-recommendations is steward-gated for the review
// action, but the LIST is visibility-scoped like the quality feed, so this
// hook carries no role gate of its own (the host page gates the decision
// buttons). fetchClassificationRecommendations already normalizes the payload
// into a flat { recommendations, count, pendingCount } envelope whose
// state/meta the shared useAxiomQuery contract resolves.
import { fetchClassificationRecommendations } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

function textFilter(value) {
  return String(value || "").trim();
}

/**
 * @param {{ status?: string, assetFqn?: string }} [filters]
 * @param {{ enabled?: boolean }} [options]
 */
export function useClassificationQueue(filters = {}, options = {}) {
  // "all" is the caller's sentinel for "no status filter" — the api-lib fn
  // treats an empty status as unbounded, so translate it here.
  const rawStatus = textFilter(filters.status).toLowerCase();
  const status = rawStatus === "all" ? "" : rawStatus;
  const assetFqn = textFilter(filters.assetFqn);
  const enabled = options.enabled !== false;

  const query = useAxiomQuery({
    key: ["axiom", "classification-recommendations", status, assetFqn],
    enabled,
    fetch: (signal) => fetchClassificationRecommendations({ status, assetFqn, signal }),
    // Keep the previous filter window's rows on screen while the next loads
    // (same stale-while-revalidate feel as the quality evidence feed).
    placeholderData: (previousData) => previousData,
    retry: false,
    staleTime: 60_000,
  });

  const payload = query.data && typeof query.data === "object" ? query.data : {};
  const recommendations = Array.isArray(payload.recommendations) ? payload.recommendations : [];
  const loading =
    query.status === "loading" || (query.status === "hydrating" && !recommendations.length);

  return {
    recommendations,
    count: Number(payload.count || recommendations.length || 0),
    pendingCount: Number(payload.pendingCount || 0),
    status: query.status,
    loading,
    error: query.error,
    errorMessage: query.errorMessage,
    warnings: query.warnings,
    refresh: query.refresh,
  };
}

export default useClassificationQueue;
