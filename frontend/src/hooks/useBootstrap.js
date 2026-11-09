import { useMemo } from "react";
import { fetchBootstrap } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

/** @returns {any} */
function initialBootstrap() {
  if (typeof window === "undefined") return null;
  return /** @type {any} */ (window.__AXIOM_BOOTSTRAP__) || null;
}

function normalizeRouteContext(routeContext = {}) {
  return {
    surface: routeContext.surface || "discovery",
    asset: routeContext.asset || "",
  };
}

function isInlineShellBootstrap(payload) {
  return payload?.bootstrapContract?.mode === "inline-shell";
}

function isLoadingRouteBootstrap(payload) {
  return payload?.bootstrapContract?.mode === "route-bootstrap" && payload?.bootState === "loading";
}

export function useBootstrap(routeContext = {}) {
  const seeded = useMemo(() => initialBootstrap(), []);
  const resolvedRouteContext = normalizeRouteContext(routeContext);
  const { query } = useAxiomQuery({
    key: [
      "bootstrap",
      resolvedRouteContext.surface,
      resolvedRouteContext.asset,
    ],
    fetch: (signal) => fetchBootstrap(resolvedRouteContext, { signal }),
    initialData: seeded || undefined,
    initialDataUpdatedAt: 0,
    staleTime: 60_000,
    // Same 3s shell-upgrade cadence as before, now bounded: ~40 attempts ≈
    // 2 minutes of "still an inline shell / route bootstrap still loading"
    // before the loop stops instead of polling forever (§7 disposition map).
    // The pending signal lives in the bootstrap contract, not the envelope,
    // so a custom `until` (true = stop) carries the predicate.
    poll: {
      interval: 3_000,
      maxAttempts: 40,
      until: (data) => !(isInlineShellBootstrap(data) || isLoadingRouteBootstrap(data)),
    },
    refetchIntervalInBackground: true,
  });
  const message = query.error?.message || "Failed to load Axiom bootstrap payload.";
  const shellOnly = isInlineShellBootstrap(query.data);
  const hasData = Boolean(query.data);

  return {
    loading: !hasData,
    refreshing: query.isFetching,
    shellOnly,
    error: !hasData && query.isError ? message : "",
    refreshError: hasData && query.isError ? message : "",
    data: query.data || null,
    refresh: query.refetch,
  };
}
