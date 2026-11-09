import { useCallback, useMemo, useState } from "react";
import { fetchAdminBackgroundStatus, fetchRuntimeStatus } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/**
 * Composes `/api/runtime/status` + `/api/admin/background/status` into a
 * single read-only snapshot for the Capability Dashboard. Kept minimal
 * on purpose: the two endpoints already speak the capability truth —
 * this hook is a thin composition layer so the dashboard component
 * stays presentational.
 *
 * @param {{enabled?: boolean}} [options]
 */
export function useCapabilityDashboard(options = {}) {
  const enabled = options?.enabled !== false;
  const [lastRefreshedAt, setLastRefreshedAt] = useState("");

  const runtimeQuery = useAxiomQuery({
    key: ["capabilities-dashboard", "runtime-status"],
    fetch: (signal) => fetchRuntimeStatus({ signal }),
    enabled,
    staleTime: 15_000,
  }).query;

  const backgroundQuery = useAxiomQuery({
    key: ["capabilities-dashboard", "background-status"],
    fetch: (signal) => fetchAdminBackgroundStatus({ signal }),
    enabled,
    staleTime: 15_000,
  }).query;

  const refetch = useCallback(async () => {
    const outcomes = await Promise.allSettled([
      runtimeQuery.refetch(),
      backgroundQuery.refetch(),
    ]);
    setLastRefreshedAt(new Date().toISOString());
    return outcomes;
  }, [runtimeQuery, backgroundQuery]);

  const runtimeData = runtimeQuery.data || null;
  const backgroundData = backgroundQuery.data || null;

  const identity = useMemo(() => runtimeData?.identity || null, [runtimeData]);
  const runtime = useMemo(() => runtimeData?.runtime || null, [runtimeData]);
  const store = useMemo(() => runtimeData?.store || null, [runtimeData]);
  const config = useMemo(() => runtimeData?.config || null, [runtimeData]);
  const capabilities = useMemo(
    () => runtimeData?.capabilities || null,
    [runtimeData],
  );

  const background = useMemo(() => {
    if (!backgroundData) return null;
    const data = backgroundData.data || {};
    const meta = backgroundData.meta || {};
    return {
      drainer: data.drainer || null,
      queue: data.queue || null,
      state: meta.state || "",
      reason: meta.reason || "",
    };
  }, [backgroundData]);

  return {
    loading:
      enabled &&
      ((runtimeQuery.isPending && !runtimeQuery.data) ||
        (backgroundQuery.isPending && !backgroundQuery.data)),
    refreshing: runtimeQuery.isFetching || backgroundQuery.isFetching,
    runtimeError:
      runtimeQuery.isError && !runtimeQuery.data
        ? runtimeQuery.error?.message || "Runtime status unavailable."
        : "",
    backgroundError:
      backgroundQuery.isError && !backgroundQuery.data
        ? backgroundQuery.error?.message || "Background status unavailable."
        : "",
    identity,
    runtime,
    store,
    config,
    capabilities,
    background,
    lastRefreshedAt,
    refetch,
  };
}

export default useCapabilityDashboard;
