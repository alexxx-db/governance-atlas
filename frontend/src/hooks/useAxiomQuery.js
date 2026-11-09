// The single data-loading contract for the Axiom frontend.
//
// `useAxiomQuery` is a thin, opinionated wrapper over react-query's useQuery
// that codifies what the ~27 data hooks each half-implemented:
//   - ONE envelope-status resolution (lib/envelope.js) instead of 11+
//     copy-pasted hydration predicates;
//   - BOUNDED polling only: `poll.maxAttempts` is mandatory whenever
//     `poll.interval` is set. On exhaustion the status degrades with a
//     warning instead of polling forever (12 of 14 legacy polls were
//     open-ended);
//   - seed/SWR semantics: seed data renders instantly as "hydrating", never
//     a blank "loading" flash; refresh failures never wipe rendered data —
//     they flip status to "degraded" and surface warnings.
//
// The bounded-poll engine generalizes useLineage's battle-tested
// module-scoped attempt ledger (attempt spacing debounce so predicate
// re-evaluations between real fetches don't burn the budget; ledger survives
// remounts within a session; explicit refresh restores the budget).
//
// CI rule (COHESION_BLUEPRINT law 8): `refetchInterval` may only appear
// inside this file — polling is always bounded.

import { useCallback } from "react";
import { hashKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  envelopeHydrating,
  envelopeMeta,
  envelopeStatus,
  envelopeWarnings,
} from "../lib/envelope";

// ---------------------------------------------------------------------------
// Bounded poll engine (module-scoped ledger, generalized from useLineage)
// ---------------------------------------------------------------------------

// Count at most one attempt per ~poll period even if react-query evaluates
// the refetchInterval predicate more often (renders, focus events, query
// state changes). Mirrors useLineage's 2,500ms spacing for a 3,000ms poll.
const POLL_SPACING_SLACK_MS = 500;

// hashKey(queryKey) → { count, lastCountedAt }. Module-scoped ON PURPOSE:
// unmounting/remounting a surface must not hand an exhausted poll loop a
// fresh budget within the same session — only an explicit user refresh does.
const pollLedger = new Map();

/** Attempts consumed for a query key (0 when never polled). */
export function pollAttemptCount(queryKey) {
  return pollLedger.get(hashKey(queryKey))?.count || 0;
}

/** Has this key spent its budget? */
export function pollBudgetExhausted(queryKey, maxAttempts) {
  return pollAttemptCount(queryKey) >= maxAttempts;
}

/** Explicit user retry: hand the poll loop a fresh attempt budget. */
export function resetPollAttempts(queryKey) {
  pollLedger.delete(hashKey(queryKey));
}

function sectionsSatisfied(data, sections) {
  if (!Array.isArray(sections) || !sections.length) return true;
  if (!data || typeof data !== "object") return true;
  const loaded = new Set(
    Array.isArray(data.loadedSections) ? data.loadedSections : [],
  );
  return sections.every((section) => loaded.has(section));
}

/**
 * Is this payload terminal for polling purposes?
 *
 * Terminality MUST be state-based, never content-based (the lineage
 * adversarial-verify P0: a pending stub payload carries one node, so a
 * "has data → stop" rule froze polls mid-build). Default predicate: the
 * shared envelope-hydration signal is off AND (when `sections` is given)
 * every requested section is loaded. A custom `until(data, query)` — return
 * true to STOP — replaces the default for payloads whose "still building"
 * signal lives outside the canonical envelope (e.g. bootstrap contract
 * modes, governance inbox state).
 *
 * `data == null` is terminal: with no payload there is nothing to poll
 * toward — react-query's own pending fetch covers the first load. This
 * matches every legacy refetchInterval fn (all returned false on undefined).
 *
 * @param {any} data
 * @param {{ until?: Function, sections?: any }} [options]
 * @param {any} [query]
 */
function pollTerminal(data, { until, sections } = {}, query = null) {
  if (typeof until === "function") return until(data, query) === true;
  if (data == null) return true;
  return !envelopeHydrating(data) && sectionsSatisfied(data, sections);
}

function normalizePoll(poll, sections) {
  if (!poll || typeof poll !== "object") return null;
  const interval = Number(poll.interval);
  if (!Number.isFinite(interval) || interval <= 0) return null;
  const maxAttempts = Number(poll.maxAttempts);
  if (!Number.isFinite(maxAttempts) || maxAttempts <= 0) {
    // Contract enforcement, not a runtime nicety: an unbounded poll is the
    // exact defect class this wrapper exists to make impossible.
    throw new Error(
      "useAxiomQuery: poll.maxAttempts is required (and must be > 0) whenever poll.interval is set — polling is always bounded.",
    );
  }
  return {
    interval,
    maxAttempts: Math.trunc(maxAttempts),
    until: typeof poll.until === "function" ? poll.until : undefined,
    sections: Array.isArray(sections) && sections.length ? sections : undefined,
  };
}

/**
 * Build a bounded react-query `refetchInterval` function from a poll config.
 * Exported so hooks with bespoke poll shapes (useLineage) can reuse the ONE
 * ledger/spacing/terminality engine while keeping their own predicates.
 */
export function boundedRefetchInterval(pollConfig) {
  const poll = normalizePoll(pollConfig, pollConfig?.sections);
  if (!poll) return false;
  const spacing = Math.max(0, poll.interval - POLL_SPACING_SLACK_MS);
  return (query) => {
    const data = query?.state?.data;
    const key = hashKey(query?.queryKey || []);
    if (pollTerminal(data, poll, query)) {
      // Terminal state reached — clear the budget so a future legitimate
      // rebuild (e.g. explicit refresh, cache eviction) can poll again.
      pollLedger.delete(key);
      return false;
    }
    const entry = pollLedger.get(key) || { count: 0, lastCountedAt: 0 };
    if (entry.count >= poll.maxAttempts) return false;
    const now = Date.now();
    if (now - entry.lastCountedAt >= spacing) {
      pollLedger.set(key, { count: entry.count + 1, lastCountedAt: now });
    }
    return poll.interval;
  };
}

// ---------------------------------------------------------------------------
// useAxiomQuery
// ---------------------------------------------------------------------------

/**
 * @param {{
 *   key: readonly unknown[],
 *   fetch: (signal?: AbortSignal) => Promise<any>,
 *   enabled?: boolean,
 *   seed?: any,
 *   poll?: { interval: number, maxAttempts: number, until?: (data: any, query?: any) => boolean } | null,
 *   sections?: string[],
 *   fresh?: boolean,
 *   staleTime?: number,
 *   gcTime?: number,
 *   placeholderData?: any,
 *   retry?: any,
 *   retryDelay?: any,
 *   initialData?: any,
 *   initialDataUpdatedAt?: number,
 *   refetchIntervalInBackground?: boolean,
 *   unsafeRefetchInterval?: number | false | ((query: any) => number | false),
 * }} config
 * @returns {{
 *   data: any,
 *   status: "loading"|"hydrating"|"available"|"degraded"|"unavailable"|"error",
 *   meta: Record<string, any>,
 *   warnings: string[],
 *   refresh: () => Promise<any>,
 *   refreshing: boolean,
 *   isPolling: boolean,
 *   pollExhausted: boolean,
 *   error: any,
 *   errorMessage: string,
 *   query: import("@tanstack/react-query").UseQueryResult<any>,
 * }}
 */
export function useAxiomQuery(config = /** @type {any} */ ({})) {
  const {
    key,
    fetch: fetchFn,
    enabled = true,
    seed,
    poll = null,
    sections,
    fresh = false,
    staleTime,
    gcTime,
    placeholderData,
    retry,
    retryDelay,
    initialData,
    initialDataUpdatedAt,
    refetchIntervalInBackground,
    // Wave-A interop ONLY: a handful of legacy hook options let CALLERS pass
    // an explicit refetchInterval override (e.g. App.jsx's 15s runtime
    // heartbeat). Honoring it verbatim keeps those call sites
    // behavior-identical until their Wave B/C rewrite moves them onto
    // `poll`. New code must never use this.
    unsafeRefetchInterval,
  } = config;

  if (!Array.isArray(key)) {
    throw new Error("useAxiomQuery: `key` must be a query-key array.");
  }
  if (typeof fetchFn !== "function") {
    throw new Error("useAxiomQuery: `fetch` must be a function (signal) => Promise.");
  }

  // Validate poll config on every render so a bad config fails fast even if
  // the query is currently disabled.
  const normalizedPoll = normalizePoll(poll, sections);
  const refetchInterval =
    unsafeRefetchInterval !== undefined
      ? unsafeRefetchInterval
      : normalizedPoll
        ? boundedRefetchInterval({ ...normalizedPoll, sections })
        : false;

  // Build the option bag WITHOUT explicitly-undefined keys: react-query
  // merges `{...clientDefaults, ...options}`, so an explicit `retry:
  // undefined` would OVERRIDE the client's `retry: false` default and
  // silently re-enable exponential-backoff retries (observed: errors took
  // 7s+ to surface). Only options the caller actually provided may appear.
  const queryOptions = {
    queryKey: key,
    enabled,
    queryFn: ({ signal }) => fetchFn(signal),
    refetchInterval,
  };
  // `fresh: true` = the fetcher must bypass caches (no-store semantics):
  // every consumer refetches rather than trusting a stored envelope.
  if (fresh) {
    queryOptions.staleTime = 0;
    queryOptions.gcTime = 0;
  } else {
    if (staleTime !== undefined) queryOptions.staleTime = staleTime;
    if (gcTime !== undefined) queryOptions.gcTime = gcTime;
  }
  if (placeholderData !== undefined) queryOptions.placeholderData = placeholderData;
  if (retry !== undefined) queryOptions.retry = retry;
  if (retryDelay !== undefined) queryOptions.retryDelay = retryDelay;
  if (initialData !== undefined) queryOptions.initialData = initialData;
  if (initialDataUpdatedAt !== undefined) queryOptions.initialDataUpdatedAt = initialDataUpdatedAt;
  if (refetchIntervalInBackground !== undefined) {
    queryOptions.refetchIntervalInBackground = refetchIntervalInBackground;
  }

  const query = useQuery(queryOptions);

  const hasSeed = seed !== undefined && seed !== null;
  const data = query.data ?? (hasSeed ? seed : null);
  // Deliberately read (react-query v5 tracks accessed properties): without
  // subscribing to isFetching, poll cycles that return structurally-equal
  // payloads never re-render the consumer, so pollExhausted/status would
  // freeze at their pre-exhaustion values. Every legacy hook also exposes
  // this as `refreshing`.
  const refreshing = query.isFetching;
  const errorMessage = query.isError
    ? query.error?.message || "Request failed."
    : "";
  // Refresh-failure-over-data: an error while data is on screen degrades.
  const refreshError = data != null && query.isError ? errorMessage : "";

  const pending = normalizedPoll
    ? !pollTerminal(query.data, normalizedPoll, query)
    : false;
  const pollExhausted = Boolean(
    normalizedPoll && pending && pollBudgetExhausted(key, normalizedPoll.maxAttempts),
  );
  const isPolling = Boolean(normalizedPoll && enabled && pending && !pollExhausted);

  /** @type {"loading"|"hydrating"|"available"|"degraded"|"unavailable"|"error"} */
  let status = envelopeStatus(query.data ?? null, { hasSeed, refreshError });
  if (query.isError && data == null) {
    // The fetch itself failed with nothing renderable — a terminal error, not
    // an envelope state.
    status = "error";
  } else if (pollExhausted && (status === "loading" || status === "hydrating")) {
    // Budget spent while the server still reports building: degrade honestly
    // instead of spinning forever. Consumers render a retry affordance.
    status = "degraded";
  }

  const warnings = [...envelopeWarnings(query.data)];
  if (pollExhausted) {
    warnings.push(
      `The server is still preparing this data after ${normalizedPoll.maxAttempts} checks — retry shortly.`,
    );
  }
  if (refreshError && !warnings.includes(refreshError)) warnings.push(refreshError);

  const keyHash = hashKey(key);
  const refetch = query.refetch;
  const refresh = useCallback(() => {
    // Explicit user retry restores the poll budget so the loop can resume.
    pollLedger.delete(keyHash);
    return refetch();
  }, [keyHash, refetch]);

  return {
    data,
    status,
    meta: envelopeMeta(query.data ?? null),
    warnings,
    refresh,
    refreshing,
    isPolling,
    pollExhausted,
    error: query.isError ? query.error : null,
    errorMessage,
    query,
  };
}

// ---------------------------------------------------------------------------
// useAxiomMutation
// ---------------------------------------------------------------------------

/**
 * The single mutation contract: optimistic update + rollback + invalidation
 * by key prefix (the pattern App.jsx's inbox handler hand-rolled).
 *
 * @param {{
 *   mutate: (variables: any) => Promise<any>,
 *   invalidates?: (readonly unknown[])[],
 *   optimistic?: { key: readonly unknown[], update: (current: any, variables: any) => any } | null,
 *   onSuccess?: (data: any, variables: any, queryClient: import("@tanstack/react-query").QueryClient) => void,
 * }} config
 */
export function useAxiomMutation(config = /** @type {any} */ ({})) {
  const {
    mutate: mutationFn,
    invalidates = [],
    optimistic = null,
    onSuccess,
  } = config;
  if (typeof mutationFn !== "function") {
    throw new Error("useAxiomMutation: `mutate` must be a function (variables) => Promise.");
  }
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn,
    onMutate: async (variables) => {
      if (!optimistic) return undefined;
      // Cancel in-flight fetches so they can't clobber the optimistic value,
      // snapshot for rollback, then apply.
      await queryClient.cancelQueries({ queryKey: optimistic.key });
      const previous = queryClient.getQueryData(optimistic.key);
      queryClient.setQueryData(optimistic.key, (current) =>
        optimistic.update(current, variables),
      );
      return { previous };
    },
    onError: (_error, _variables, contextValue) => {
      // Rollback: optimistic UI must never survive a failed write.
      if (optimistic && contextValue && "previous" in contextValue) {
        queryClient.setQueryData(optimistic.key, contextValue.previous);
      }
    },
    onSuccess: (data, variables) => {
      if (typeof onSuccess === "function") onSuccess(data, variables, queryClient);
    },
    onSettled: () => {
      // Invalidation by key prefix — success AND failure both re-sync from
      // the server so the cache never drifts from persisted truth.
      invalidates.forEach((invalidKey) => {
        queryClient.invalidateQueries({ queryKey: invalidKey });
      });
    },
  });

  const mutateAsync = mutation.mutateAsync;
  const submit = useCallback((variables) => mutateAsync(variables), [mutateAsync]);

  return {
    mutate: submit,
    mutateAsync,
    submitting: mutation.isPending,
    error: mutation.isError ? mutation.error : null,
    errorMessage: mutation.isError
      ? mutation.error?.message || "Request failed."
      : "",
    data: mutation.data ?? null,
    reset: mutation.reset,
  };
}

export default useAxiomQuery;
