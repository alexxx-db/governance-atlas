import { fetchColumnLineageTrace } from "../lib/api";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { useAxiomQuery } from "./useAxiomQuery";

function tracePayload(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  if (isNonAuthoritativeMockEvidence(data, data.meta, data.warnings)) return null;
  return data.data && typeof data.data === "object" ? data.data : data;
}

function normalizeTrace(data) {
  const payload = tracePayload(data);
  if (!payload) return null;
  return {
    ...payload,
    nodes: Array.isArray(payload.nodes) ? payload.nodes : [],
    edges: Array.isArray(payload.edges) ? payload.edges : [],
    meta: payload.meta && typeof payload.meta === "object" ? payload.meta : {},
  };
}

export function useColumnLineageTrace(assetFqn, columnName, options = {}) {
  const trimmedAsset = String(assetFqn || "").trim();
  const trimmedColumn = String(columnName || "").trim();
  const enabled = options.enabled !== false && Boolean(trimmedAsset && trimmedColumn);
  const depth = Number.isFinite(Number(options.depth))
    ? Math.max(1, Math.min(4, Math.trunc(Number(options.depth))))
    : 3;
  const upstream = useAxiomQuery({
    key: ["columnLineageTrace", trimmedAsset, trimmedColumn, "upstream", depth],
    enabled,
    retry: false,
    fetch: (signal) =>
      fetchColumnLineageTrace(trimmedAsset, trimmedColumn, {
        signal,
        direction: "upstream",
        depth,
      }),
  }).query;
  const downstream = useAxiomQuery({
    key: ["columnLineageTrace", trimmedAsset, trimmedColumn, "downstream", depth],
    enabled,
    retry: false,
    fetch: (signal) =>
      fetchColumnLineageTrace(trimmedAsset, trimmedColumn, {
        signal,
        direction: "downstream",
        depth,
      }),
  }).query;
  const upstreamTrace = normalizeTrace(upstream.data);
  const downstreamTrace = normalizeTrace(downstream.data);
  return {
    loading:
      enabled &&
      ((upstream.isPending && !upstreamTrace) || (downstream.isPending && !downstreamTrace)),
    refreshing: enabled && (upstream.isFetching || downstream.isFetching),
    upstream: upstreamTrace,
    downstream: downstreamTrace,
    upstreamError: upstream.isError && !upstreamTrace ? upstream.error?.message || "Upstream column trace unavailable." : "",
    downstreamError: downstream.isError && !downstreamTrace ? downstream.error?.message || "Downstream column trace unavailable." : "",
    refresh: () => Promise.all([upstream.refetch(), downstream.refetch()]),
  };
}

export default useColumnLineageTrace;
