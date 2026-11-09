import { fetchInsightsDashboard } from "../lib/api";
import { useAxiomQuery } from "./useAxiomQuery";

const EMPTY_INSIGHTS_DASHBOARD = {
  kpis: [],
  policyComplianceTrend: [],
  resolutionTrend: [],
  metadataCoverageHeatmap: [],
  certificationCoverageByTier: [],
  riskHeatmap: [],
  domainLeaderboard: [],
  recommendations: [],
  scoring: { maturityFormula: [], availableSignals: [] },
  signalAvailability: {},
  meta: { state: "unknown", warnings: [] },
};

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeInsightsDashboard(payload) {
  const raw = objectValue(payload);
  const data = raw.data && typeof raw.data === "object" && !Array.isArray(raw.data)
    ? raw.data
    : raw;
  const scoring = objectValue(data.scoring);
  const envelopeMeta = objectValue(raw.meta);
  const dataMeta = objectValue(data.meta);
  const warnings = Array.from(new Set([
    ...arrayValue(envelopeMeta.warnings),
    ...arrayValue(dataMeta.warnings),
  ].filter(Boolean)));
  return {
    ...EMPTY_INSIGHTS_DASHBOARD,
    ...data,
    kpis: arrayValue(data.kpis).map((item) => objectValue(item)),
    policyComplianceTrend: arrayValue(data.policyComplianceTrend),
    resolutionTrend: arrayValue(data.resolutionTrend),
    metadataCoverageHeatmap: arrayValue(data.metadataCoverageHeatmap),
    certificationCoverageByTier: arrayValue(data.certificationCoverageByTier),
    riskHeatmap: arrayValue(data.riskHeatmap),
    domainLeaderboard: arrayValue(data.domainLeaderboard),
    recommendations: arrayValue(data.recommendations).map((item) => objectValue(item)),
    scoring: {
      ...scoring,
      maturityFormula: arrayValue(scoring.maturityFormula),
      availableSignals: arrayValue(scoring.availableSignals),
    },
    signalAvailability: objectValue(data.signalAvailability),
    meta: {
      ...envelopeMeta,
      ...dataMeta,
      warnings,
      state: dataMeta.state || envelopeMeta.state || "unknown",
      capabilities: {
        ...objectValue(envelopeMeta.capabilities),
        ...objectValue(dataMeta.capabilities),
      },
    },
  };
}

function normalizeOptions(options) {
  if (typeof options === "boolean") return { enabled: options };
  return options && typeof options === "object" ? options : {};
}

export function useInsightsDashboard(options = {}) {
  const resolvedOptions = normalizeOptions(options);
  const enabled = resolvedOptions.enabled !== false;
  const seedData = resolvedOptions.seedData || null;

  const { query } = useAxiomQuery({
    key: ["axiom", "insights-dashboard"],
    fetch: (signal) => fetchInsightsDashboard({ signal }),
    enabled,
    staleTime: resolvedOptions.staleTime ?? 60_000,
    // Retain the cached Risk & quality band across back-nav for the session.
    gcTime: resolvedOptions.gcTime ?? 30 * 60_000,
    // Poll while the server envelope is still hydrating (cold rebuild after a
    // deploy/TTL expiry returns 200 + meta.state "loading" with empty KPIs);
    // without this the page sits on the empty envelope for the full
    // staleTime and renders as if the signals don't exist. Same 4s cadence as
    // before, now bounded (~1min) instead of open-ended.
    poll: {
      interval: 4_000,
      maxAttempts: 15,
      until: (data) => String(data?.meta?.state || "").trim().toLowerCase() !== "loading",
    },
    // Legacy escape hatch for callers passing an explicit refetchInterval.
    unsafeRefetchInterval: resolvedOptions.refetchInterval,
  });

  const usableData = query.data || seedData || null;
  const data = normalizeInsightsDashboard(usableData || EMPTY_INSIGHTS_DASHBOARD);
  const message = query.error?.message || "Insights dashboard is unavailable.";
  const warnings = Array.isArray(data.meta?.warnings) ? data.meta.warnings : [];
  const refreshError = usableData && query.isError ? message : "";
  const state = query.isError && !usableData
    ? "error"
    : query.isPending && !usableData
      ? "loading"
      : data.meta?.state === "degraded" || refreshError || warnings.length
        ? "degraded"
        : "ready";

  return {
    data,
    state,
    loading: enabled && query.isPending && !usableData,
    refreshing: query.isFetching,
    error: usableData ? "" : query.isError ? message : "",
    refreshError,
    warnings,
    degraded: state === "degraded",
    refresh: query.refetch,
  };
}

export default useInsightsDashboard;
export { EMPTY_INSIGHTS_DASHBOARD, normalizeInsightsDashboard };
