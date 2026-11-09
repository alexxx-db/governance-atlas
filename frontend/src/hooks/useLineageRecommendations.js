import { fetchLineageRecommendations } from "../lib/api";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { pollBudgetExhausted, resetPollAttempts, useAxiomQuery } from "./useAxiomQuery";

function normalizeRecommendation(item) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  if (isNonAuthoritativeMockEvidence(item, item.meta, item.provenance, item.warnings)) return null;
  const fqn = String(item.fqn || item.assetFqn || "").trim();
  if (!fqn) return null;
  return {
    ...item,
    fqn,
    name: String(item.name || fqn.split(".").pop() || fqn).trim(),
    edgeCount: Number.isFinite(Number(item.edgeCount)) ? Math.max(0, Number(item.edgeCount)) : 0,
    upstreamCount: Number.isFinite(Number(item.upstreamCount)) ? Math.max(0, Number(item.upstreamCount)) : 0,
    downstreamCount: Number.isFinite(Number(item.downstreamCount)) ? Math.max(0, Number(item.downstreamCount)) : 0,
  };
}

function lineageRecommendationHydrating(payload) {
  const state = String(payload?.meta?.state || payload?.state || "").trim().toLowerCase();
  return (
    state === "loading" ||
    state === "hydrating" ||
    payload?.recommendationMeta?.hydrating === true ||
    payload?.meta?.capabilities?.hydrating === true
  );
}

// Poll-loop guard (perf audit P1): mirror useLineage — the recommendations
// warmer used to re-poll every 3s indefinitely while the backend reported a
// loading envelope. Stop as soon as items exist or after a bounded number
// of attempts, then surface an honest "still warming" state via `warming`.
// The attempt ledger itself now lives in useAxiomQuery's shared bounded-poll
// engine; this hook only supplies the terminality predicate (`until` returns
// true to STOP: not hydrating anymore, or items already renderable).
const RECOMMENDATION_POLL_ATTEMPT_LIMIT = 10;
const RECOMMENDATION_POLL = {
  interval: 3_000,
  maxAttempts: RECOMMENDATION_POLL_ATTEMPT_LIMIT,
  until: (payload) =>
    !lineageRecommendationHydrating(payload) ||
    (Array.isArray(payload?.items) && payload.items.length > 0),
};

export function useLineageRecommendations(options = {}) {
  const enabled = options.enabled !== false;
  const limit = Number.isFinite(Number(options.limit))
    ? Math.max(1, Math.min(25, Math.trunc(Number(options.limit))))
    : 8;
  const queryKey = ["lineageRecommendations", limit];
  const { query } = useAxiomQuery({
    key: queryKey,
    enabled,
    staleTime: 120_000,
    poll: RECOMMENDATION_POLL,
    fetch: (signal) => fetchLineageRecommendations({ signal, limit }),
  });
  const payload = query.data && !isNonAuthoritativeMockEvidence(query.data, query.data?.meta, query.data?.warnings)
    ? query.data
    : null;
  const items = Array.isArray(payload?.items)
    ? payload.items.map(normalizeRecommendation).filter(Boolean)
    : [];
  const hydrating = lineageRecommendationHydrating(payload);
  // Warming = the envelope is still hydrating with zero items and the poll
  // budget is spent. Consumers must show "still warming — retry", not an
  // eternal loading spinner.
  const warming =
    hydrating &&
    !items.length &&
    pollBudgetExhausted(queryKey, RECOMMENDATION_POLL_ATTEMPT_LIMIT);
  return {
    loading: enabled && ((query.isPending && !payload) || (hydrating && !warming)),
    warming,
    refreshing: enabled && query.isFetching,
    error: query.isError && !payload ? query.error?.message || "Failed to load lineage recommendations." : "",
    items,
    meta: payload?.recommendationMeta || payload?.meta || null,
    envelopeMeta: payload?.meta || null,
    authoritative: payload ? payload?.meta?.authoritative === true : null,
    degraded: payload?.meta?.degraded === true || payload?.meta?.authoritative === false,
    visibilityScope:
      payload?.meta?.visibilityScope ||
      payload?.meta?.readScope ||
      payload?.meta?.capabilities?.visibilityScope ||
      "",
    relationshipVisibilityScope:
      payload?.meta?.capabilities?.relationshipVisibilityScope ||
      payload?.recommendationMeta?.relationshipVisibilityScope ||
      "",
    warning: Array.isArray(payload?.meta?.warnings) ? payload.meta.warnings[0] || "" : "",
    refresh: () => {
      // Explicit retry restores the poll budget so the warmer can resume.
      resetPollAttempts(queryKey);
      return query.refetch();
    },
  };
}

export default useLineageRecommendations;
