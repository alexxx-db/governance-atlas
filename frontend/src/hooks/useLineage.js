import { useCallback, useMemo } from "react";
import { fetchLineage } from "../lib/api";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { axiomQueryClient } from "../lib/queryClient";
import {
  boundedRefetchInterval,
  pollBudgetExhausted,
  resetPollAttempts,
  useAxiomQuery,
} from "./useAxiomQuery";

const LINEAGE_CACHE_TTL_MS = 300_000;
// Keep prefetched neighbor payloads alive long enough to be useful. The
// default React Query gcTime (5 min) drops inactive prefetched queries
// before the user can click them, causing a full refetch on refocus.
const LINEAGE_GC_TIME_MS = 15 * 60 * 1000;
const LINEAGE_QUERY_PREFIX = "lineage";
const LINEAGE_PROFILE_FULL = "full";
const LINEAGE_PROFILE_INITIAL = "initial";

function lineageQueryKey(assetFqn, profile = LINEAGE_PROFILE_FULL) {
  return [LINEAGE_QUERY_PREFIX, profile, assetFqn];
}

function queryUpdatedAt(queryKey) {
  return axiomQueryClient.getQueryState(queryKey)?.dataUpdatedAt || 0;
}

function isFresh(queryKey, maxAgeMs = null) {
  if (maxAgeMs == null) return true;
  const updatedAt = queryUpdatedAt(queryKey);
  if (!updatedAt) return false;
  return Date.now() - updatedAt <= maxAgeMs;
}

function readCachedLineage(assetFqn, { maxAgeMs = LINEAGE_CACHE_TTL_MS, profile = LINEAGE_PROFILE_FULL } = {}) {
  if (!assetFqn) return null;
  const queryKey = lineageQueryKey(assetFqn, profile);
  const payload = axiomQueryClient.getQueryData(queryKey) || null;
  if (!payload) return null;
  if (!isFresh(queryKey, maxAgeMs)) return null;
  return payload;
}

function normalizeCanonicalPayload(assetFqn, payload, { authoritative = false, source = "live" } = {}) {
  if (!assetFqn || !payload) return null;
  const meta = payload.meta && typeof payload.meta === "object" ? payload.meta : {};
  const payloadState = String(meta.state || payload.state || "").trim().toLowerCase();
  const payloadSource = String(meta.source || payload.source || source || "").trim().toLowerCase();
  const mockPayload = isNonAuthoritativeMockEvidence(payload, meta, payload.warnings);
  if (mockPayload) return null;
  const resolvedAuthoritative = mockPayload
    ? false
    : typeof payload.authoritative === "boolean"
      ? payload.authoritative
      : typeof meta.authoritative === "boolean"
        ? meta.authoritative
      : authoritative;
  return {
    ...payload,
    fqn: payload.fqn || assetFqn,
    authoritative: resolvedAuthoritative,
    source: payload.source || meta.source || source,
  };
}

function isWorkspaceScopedDatabricksLineage(payload, meta = {}) {
  if (!payload || typeof payload !== "object") return false;
  const payloadSource = String(meta.source || payload.source || "").trim().toLowerCase();
  const visibilityScope = String(meta.visibilityScope || meta.readScope || "").trim().toLowerCase();
  const authMode = String(meta.authMode || meta.productMode || "").trim().toLowerCase();
  const nodes = payload.graphs?.data?.nodes || payload.graph?.nodes || [];
  return (
    payloadSource.includes("unity-catalog-lineage") &&
    (
      visibilityScope === "workspace-app-principal" ||
      visibilityScope === "workspace_app_principal" ||
      authMode === "app-principal-only" ||
      authMode === "app_principal_only"
    ) &&
    Array.isArray(nodes) &&
    nodes.length > 0
  );
}

function setCachedLineage(assetFqn, payload) {
  const normalized = normalizeCanonicalPayload(assetFqn, payload);
  if (!normalized) return null;
  const profile = normalized.profile === LINEAGE_PROFILE_INITIAL ? LINEAGE_PROFILE_INITIAL : LINEAGE_PROFILE_FULL;
  axiomQueryClient.setQueryData(lineageQueryKey(assetFqn, profile), normalized);
  return normalized;
}

/**
 * Is this payload still PENDING for the profile the caller asked for?
 *
 * Terminality MUST be state-based, never node-count-based (adversarial
 * verify P0): during a cold-cache full build the server serves a stale
 * envelope whose data graph contains exactly ONE stub focus node — so a
 * "has nodes → stop polling" rule froze the poll after a single full
 * request and every first visitor after cache expiry got a permanent
 * empty canvas. A payload is pending when:
 *   • the envelope state is loading/hydrating, or
 *   • the envelope capabilities say hydrating, or
 *   • (full profile requested only) the payload is still the initial
 *     profile / carries the deferred markers the initial build stamps.
 * The initial profile is inherently "deferred" by design (table lineage
 * loads in the full profile), so the deferred/profile checks apply ONLY
 * when the caller requested the full profile — otherwise the initial
 * query would poll forever on its own perfectly terminal payload.
 */
function lineagePayloadPending(payload, requestedProfile = LINEAGE_PROFILE_FULL) {
  if (!payload || typeof payload !== "object") return false;
  const meta = payload.meta && typeof payload.meta === "object" ? payload.meta : {};
  const capabilities = meta.capabilities && typeof meta.capabilities === "object"
    ? meta.capabilities
    : {};
  const state = String(meta.state || payload.state || "").trim().toLowerCase();
  if (state === "loading" || state === "hydrating") return true;
  if (capabilities.hydrating === true) return true;
  if (requestedProfile === LINEAGE_PROFILE_FULL) {
    const payloadProfile = String(payload.profile || "").trim().toLowerCase();
    // Requested full but got the (stale) initial payload back — the
    // server's full build has not finished; keep polling.
    if (payloadProfile && payloadProfile !== LINEAGE_PROFILE_FULL) return true;
    const dataMeta = payload.graphs?.data?.meta || payload.graph?.meta || {};
    if (dataMeta.deferred === true || payload.deferred === true) return true;
    if (payload.stats?.progressive?.tableLineageDeferred === true) return true;
  }
  return false;
}

// Poll-loop guard (perf audit P1 + adversarial verify P0): poll a pending
// build at 3s until a genuinely TERMINAL payload arrives (state
// available/degraded, deferred false, requested profile delivered) or the
// attempt budget is spent — never stop early just because a stub node is
// present. 15 attempts × 3s ≈ 45s comfortably covers the observed 10-14s
// cold full build.
//
// The module-scoped attempt ledger that used to live HERE (per-key counters,
// spacing debounce so predicate re-evaluations don't burn budget, survives
// remounts within a session, reset on explicit refresh) was generalized into
// useAxiomQuery's bounded-poll engine — this hook now supplies only the
// lineage-shaped terminality predicate.
export const LINEAGE_POLL_ATTEMPT_LIMIT = 15;
const LINEAGE_POLL_INTERVAL_MS = 3_000;

// The poll config shared by both profile queries. `until` returns true to
// STOP: terminality stays profile-aware (the queryKey carries the profile).
const LINEAGE_POLL = {
  interval: LINEAGE_POLL_INTERVAL_MS,
  maxAttempts: LINEAGE_POLL_ATTEMPT_LIMIT,
  until: (payload, query) =>
    !lineagePayloadPending(payload, String(query?.queryKey?.[1] || LINEAGE_PROFILE_FULL)),
};

export function lineagePollExhausted(assetFqn) {
  return (
    pollBudgetExhausted(
      lineageQueryKey(assetFqn, LINEAGE_PROFILE_INITIAL),
      LINEAGE_POLL_ATTEMPT_LIMIT,
    ) ||
    pollBudgetExhausted(
      lineageQueryKey(assetFqn, LINEAGE_PROFILE_FULL),
      LINEAGE_POLL_ATTEMPT_LIMIT,
    )
  );
}

function resetLineagePollAttempts(assetFqn) {
  resetPollAttempts(lineageQueryKey(assetFqn, LINEAGE_PROFILE_INITIAL));
  resetPollAttempts(lineageQueryKey(assetFqn, LINEAGE_PROFILE_FULL));
}

// Exported for unit tests: the cold-cache P0 regression lived entirely in
// this predicate (stub-node payloads read as terminal), so tests pin its
// behavior directly against representative payload shapes. Now a thin alias
// over the shared bounded engine with the lineage `until` predicate.
export const lineageRefetchInterval = boundedRefetchInterval(LINEAGE_POLL);

export function primeLineagePayload(assetFqn, payload) {
  return setCachedLineage(assetFqn, payload);
}

export function invalidateLineage(assetFqn) {
  if (!assetFqn) return;
  axiomQueryClient.removeQueries({
    queryKey: [LINEAGE_QUERY_PREFIX],
    exact: false,
    predicate: (query) => query.queryKey?.[2] === assetFqn,
  });
}

export function prefetchLineage(assetFqn, options = {}) {
  if (!assetFqn) return Promise.resolve(null);
  const force = options.force === true;
  const profile = options.profile === LINEAGE_PROFILE_INITIAL ? LINEAGE_PROFILE_INITIAL : LINEAGE_PROFILE_FULL;
  const cached = force ? null : readCachedLineage(assetFqn, { profile });
  if (cached) return Promise.resolve(cached);
  return axiomQueryClient
    .fetchQuery({
      queryKey: lineageQueryKey(assetFqn, profile),
      staleTime: LINEAGE_CACHE_TTL_MS,
      gcTime: LINEAGE_GC_TIME_MS,
      queryFn: ({ signal }) => fetchLineage(assetFqn, { signal, profile }),
    })
    .then((payload) => setCachedLineage(assetFqn, payload))
    .catch(() => readCachedLineage(assetFqn, { maxAgeMs: null, profile }) || null);
}

export function useLineage(assetFqn, enabled = true, options = {}) {
  const fullProfileRequested = options.fullProfile === true || options.loadFullProfile === true;
  const cachedFullPayload = useMemo(
    () => readCachedLineage(assetFqn, { maxAgeMs: null, profile: LINEAGE_PROFILE_FULL }),
    [assetFqn],
  );
  const cachedInitialPayload = useMemo(
    () => readCachedLineage(assetFqn, { maxAgeMs: null, profile: LINEAGE_PROFILE_INITIAL }),
    [assetFqn],
  );

  const initialQuery = useAxiomQuery({
    key: lineageQueryKey(assetFqn || "", LINEAGE_PROFILE_INITIAL),
    enabled: Boolean(assetFqn) && enabled,
    staleTime: LINEAGE_CACHE_TTL_MS,
    gcTime: LINEAGE_GC_TIME_MS,
    retry: false,
    poll: LINEAGE_POLL,
    fetch: (signal) => fetchLineage(assetFqn, { signal, profile: LINEAGE_PROFILE_INITIAL }),
  }).query;

  const fullQuery = useAxiomQuery({
    key: lineageQueryKey(assetFqn || "", LINEAGE_PROFILE_FULL),
    enabled: Boolean(assetFqn) &&
      enabled &&
      fullProfileRequested &&
      Boolean(initialQuery.data || cachedInitialPayload || cachedFullPayload),
    staleTime: LINEAGE_CACHE_TTL_MS,
    gcTime: LINEAGE_GC_TIME_MS,
    retry: false,
    poll: LINEAGE_POLL,
    fetch: (signal) => fetchLineage(assetFqn, { signal, profile: LINEAGE_PROFILE_FULL }),
  }).query;
  // Neighbor prefetch is intentionally *not* auto-triggered here. Eager
  // stampedes (8 parallel lineage queries) starved the SQL warehouse and
  // turned every focus load into a 2+ minute wait. Callers that actually
  // need a warm neighbor (e.g. hover dwell > 600 ms) must call
  // `prefetchLineage()` explicitly, one neighbor at a time.

  // Stable identity: a new refresh closure every render busted the
  // useLineageGraphV2 useMemo (refresh is a dep), forcing a full dagre
  // relayout of the canvas on every parent re-render. Declared BEFORE the
  // early returns below so hook order is stable (React error #310 rule).
  const refresh = useCallback(async () => {
    if (!assetFqn) return null;
    // Explicit user retry: hand the poll loop a fresh attempt budget.
    resetLineagePollAttempts(assetFqn);
    axiomQueryClient.removeQueries({
      queryKey: [LINEAGE_QUERY_PREFIX],
      exact: false,
      predicate: (query) => query.queryKey?.[2] === assetFqn,
    });
    const initial = await initialQuery.refetch();
    const initialValue = normalizeCanonicalPayload(assetFqn, initial.data, {
      authoritative: false,
      source: "live",
    });
    if (!initialValue) return null;
    setCachedLineage(assetFqn, initialValue);
    const full = await fullQuery.refetch();
    const fullValue = normalizeCanonicalPayload(assetFqn, full.data, {
      authoritative: false,
      source: "live",
    });
    if (fullValue) return setCachedLineage(assetFqn, fullValue);
    return initialValue;
  }, [assetFqn, initialQuery, fullQuery]);

  if (!assetFqn) {
    return {
      loading: false,
      error: "",
      graph: null,
      payload: null,
      authoritative: false,
      provisional: false,
      warming: false,
      refresh: async () => null,
    };
  }

  const initialPayload = initialQuery.data
    ? normalizeCanonicalPayload(assetFqn, initialQuery.data, { authoritative: false, source: "live" })
    : cachedInitialPayload || null;
  const fullPayload = fullQuery.data
    ? normalizeCanonicalPayload(assetFqn, fullQuery.data, { authoritative: false, source: "live" })
    : null;
  const payload = fullPayload || cachedFullPayload || initialPayload || null;
  const meta = payload?.meta && typeof payload.meta === "object" ? payload.meta : {};
  const payloadState = String(meta.state || payload?.state || "").trim().toLowerCase();
  const payloadSource = String(meta.source || payload?.source || "").trim().toLowerCase();
  const prototypePayload = isNonAuthoritativeMockEvidence(payload, meta, payload?.warnings);
  const safePayload = prototypePayload ? null : payload;
  const explicitAuthoritativeFalse = safePayload?.authoritative === false || meta.authoritative === false;
  const workspaceScopedLineage = isWorkspaceScopedDatabricksLineage(safePayload, meta);
  const authoritative = Boolean(
    safePayload &&
      payloadState !== "prototype_mock" &&
      payloadSource !== "local-prototype-mock" &&
      !explicitAuthoritativeFalse &&
      !workspaceScopedLineage &&
      (
        safePayload.authoritative === true ||
        meta.authoritative === true ||
        ["authoritative", "live"].includes(payloadState)
      ),
  );
  const provisional = Boolean(safePayload) && !authoritative;
  // "Warming" = the backend is still reporting a pending/deferred envelope
  // AND we've exhausted the bounded poll budget. Consumers render an honest
  // "still warming — retry" affordance instead of an infinite spinner
  // (persona-audit finding 4). Deliberately NOT gated on node count — the
  // pending stub carries one focus node, which must not mask warming
  // (adversarial verify P0).
  const warming =
    lineagePayloadPending(
      safePayload,
      fullProfileRequested ? LINEAGE_PROFILE_FULL : LINEAGE_PROFILE_INITIAL,
    ) && lineagePollExhausted(assetFqn);

  if (!enabled) {
    return {
      loading: false,
      error: "",
      graph: safePayload?.graphs || null,
      payload: safePayload || null,
      authoritative,
      provisional,
      warming,
      refresh: async () => safePayload,
    };
  }

  return {
    loading: !safePayload && initialQuery.isPending && !initialQuery.isError,
    error: !safePayload && (initialQuery.isError || fullQuery.isError)
      ? initialQuery.error?.message || fullQuery.error?.message || "Failed to load lineage."
      : "",
    graph: safePayload?.graphs || null,
    payload: safePayload || null,
    authoritative,
    provisional,
    warming,
    refresh,
  };
}
