import { fetchemetOverview, fetchemetStatus } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * emet detection + health (authoritative OBO read). Powers the Control
 * Center header/health band and gates the rest of the surface.
 */
export function useEmetStatus(options = {}) {
  const enabled = options.enabled !== false;
  const { query } = useAxiomQuery({
    key: ["emet", "status"],
    fetch: (signal) => fetchemetStatus({ signal }),
    enabled,
    staleTime: options.staleTime ?? 30_000,
    gcTime: 5 * 60_000,
  });
  const payload = query.data || null;
  return {
    status: payload?.status || null,
    detected: Boolean(payload?.detected),
    loading: enabled && query.isPending && !payload,
    refreshing: query.isFetching,
    error: query.isError && !payload ? query.error?.message || "emet status is unavailable." : "",
    refresh: query.refetch,
    meta: payload?.meta || null,
  };
}

/**
 * emet portfolio — every active validation job with its latest-run trust
 * KPIs + deltas, an estate rollup, and the ranked fix-first queue. Polls while
 * the server envelope is still hydrating.
 */
export function useEmetOverview(options = {}) {
  const enabled = options.enabled !== false;
  const { query } = useAxiomQuery({
    key: ["emet", "overview"],
    fetch: (signal) => fetchemetOverview({ signal }),
    enabled,
    staleTime: options.staleTime ?? 30_000,
    gcTime: 5 * 60_000,
    poll: {
      interval: 5_000,
      maxAttempts: 12,
      until: (data) => String(data?.meta?.state || "").trim().toLowerCase() !== "loading",
    },
  });
  const data = query.data || null;
  return {
    detected: Boolean(data?.detected),
    jobs: Array.isArray(data?.jobs) ? data.jobs : [],
    rollup: data?.rollup || null,
    fixFirst: Array.isArray(data?.fixFirst) ? data.fixFirst : [],
    install: data?.install || null,
    loading: enabled && query.isPending && !data,
    refreshing: query.isFetching,
    error: query.isError && !data ? query.error?.message || "emet portfolio is unavailable." : "",
    warnings: Array.isArray(data?.meta?.warnings) ? data.meta.warnings : [],
    refresh: query.refetch,
    meta: data?.meta || null,
  };
}

export default useEmetOverview;
