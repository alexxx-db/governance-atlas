import { fetchAssetDatabricksEvidence } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function useAssetDatabricksEvidence(assetFqn, options = {}) {
  const trimmed = String(assetFqn || "").trim();
  const enabled = options.enabled !== false && Boolean(trimmed);
  const { query } = useAxiomQuery({
    key: ["assetDatabricksEvidence", trimmed],
    enabled,
    fetch: (signal) => fetchAssetDatabricksEvidence(trimmed, { signal }),
    staleTime: 60_000,
  });
  const data = objectValue(query.data);
  const loadingSection = { state: "loading", rows: [], warnings: [] };
  return {
    loading: enabled && query.isPending && !query.data,
    refreshing: query.isFetching,
    error: query.isError && !query.data ? query.error?.message || "Failed to load Databricks evidence." : "",
    available: Boolean(query.data),
    qualityMonitoring: query.isPending && !query.data ? loadingSection : objectValue(data.qualityMonitoring),
    profileMetrics: query.isPending && !query.data ? loadingSection : objectValue(data.profileMetrics),
    lakeflow: query.isPending && !query.data ? { ...loadingSection, jobs: [], pipelines: [] } : objectValue(data.lakeflow),
    pipelineEvents: query.isPending && !query.data ? loadingSection : objectValue(data.pipelineEvents),
    provenance: Array.isArray(data.provenance) ? data.provenance : [],
    refresh: query.refetch,
  };
}
