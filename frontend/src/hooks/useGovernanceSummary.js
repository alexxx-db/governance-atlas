import { fetchGovernanceSummary } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

const EMPTY_GOVERNANCE = {
  metrics: [],
  backlog: [],
  glossary: [],
  inbox: null,
};

/**
 * @param {{enabled?: boolean, staleTime?: number, refetchInterval?: number | false, sections?: string[], section?: string} | boolean} [options={}]
 */
export function useGovernanceSummary(options = {}) {
  const resolvedOptions =
    typeof options === "boolean"
      ? { enabled: options }
      : options && typeof options === "object"
        ? options
        : {};
  const enabled = resolvedOptions.enabled !== false;
  const sections = Array.isArray(resolvedOptions.sections)
    ? resolvedOptions.sections.filter(Boolean)
    : resolvedOptions.section
      ? [resolvedOptions.section]
      : [];
  const { query } = useAxiomQuery({
    key: ["governance-summary", sections],
    fetch: (signal) => fetchGovernanceSummary({ signal, sections }),
    enabled,
    staleTime: resolvedOptions.staleTime ?? 15000,
    // Same 2.5s inbox-warmup cadence as before, now bounded (~1min). The
    // pending signal lives in the surface-specific `inbox.state`, not the
    // canonical envelope, so a custom `until` (true = stop) carries it.
    poll: {
      interval: 2_500,
      maxAttempts: 24,
      until: (data) => String(data?.inbox?.state || "").trim().toLowerCase() !== "loading",
    },
    // Legacy escape hatch for callers passing an explicit refetchInterval.
    unsafeRefetchInterval: resolvedOptions.refetchInterval,
  });
  const message = query.error?.message || "Failed to load governance summary.";

  return {
    loading: enabled && query.isPending && !query.data,
    refreshing: query.isFetching,
    error: query.data ? "" : query.isError ? message : "",
    refreshError: query.data && query.isError ? message : "",
    data: query.data || null,
    empty: EMPTY_GOVERNANCE,
    refresh: query.refetch,
  };
}
