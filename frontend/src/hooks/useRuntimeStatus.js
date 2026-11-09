import { fetchRuntimeStatus } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * Runtime status probe.
 *
 * Polling policy lives HERE (guardrail: refetchInterval never leaves the
 * hooks layer). `pollWhileWarming` keeps refetching every 15s while the
 * runtime probe reports `state: "loading"` — a cold serverless warehouse
 * answers instantly with "loading", so we poll until the real probe
 * resolves, then stop.
 *
 * @param {{enabled?: boolean, staleTime?: number, pollWhileWarming?: boolean} | boolean} [options={}]
 */
export function useRuntimeStatus(options = {}) {
  const resolvedOptions =
    typeof options === "boolean"
      ? { enabled: options }
      : options && typeof options === "object"
        ? options
        : {};
  const enabled = resolvedOptions.enabled !== false;
  const { query } = useAxiomQuery({
    key: ["runtime-status"],
    fetch: (signal) => fetchRuntimeStatus({ signal }),
    enabled,
    staleTime: resolvedOptions.staleTime ?? 15000,
    unsafeRefetchInterval: resolvedOptions.pollWhileWarming
      ? (q) => (q?.state?.data?.runtime?.state === "loading" ? 15000 : false)
      : false,
  });
  const message = query.error?.message || "Failed to load workspace diagnostics.";

  return {
    loading: enabled && query.isPending && !query.data,
    refreshing: query.isFetching,
    error: query.data ? "" : query.isError ? message : "",
    refreshError: query.data && query.isError ? message : "",
    data: query.data || null,
    refresh: query.refetch,
  };
}
