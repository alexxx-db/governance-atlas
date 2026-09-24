import { useCallback, useEffect, useState } from "react";
import { fetchCommandCenter } from "../lib/api";
import { pollBudgetExhausted, useAtlasQuery } from "./useAtlasQuery";

// Last dashboard payload that carried real backed signal, held at MODULE level
// so it survives navigating away from the Command Center and back — a
// per-instance ref was destroyed on unmount, so back-nav re-mounted with no
// retention and (whenever the serverless SQL warehouse had gone cold) blanked
// the whole dashboard to "—" until the warm refetch returned. The poll-budget
// bound below still makes this self-healing, so a genuinely degraded estate
// can't show phantom values forever.
let lastBackedCommandCenter = null;

// Test seam: reset the cross-navigation retention between test cases so
// module-level state never bleeds across them.
export function __resetCommandCenterRetention() {
  lastBackedCommandCenter = null;
}

export const EMPTY_COMMAND_CENTER = {
  estate: {
    visibleAssetCount: null,
    catalogCount: null,
    openRequests: null,
    coverageScore: null,
  },
  kpis: [],
  posture: { overall: null, trend: [], byDomain: [], heatmap: [] },
  topDomains: [],
  recentEvents: [],
  recentAssets: [],
  governance: { pendingRequests: [] },
  insights: { tiles: {} },
  quickActions: [],
  aiPrompts: [],
  signalAvailability: {},
  meta: { state: "unknown", warnings: [] },
};

function normalizeOptions(options) {
  if (typeof options === "boolean") return { enabled: options };
  return options && typeof options === "object" ? options : {};
}

function num(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

// Does a payload actually carry backed governance values (vs. a still-warming
// envelope that answered 200 with everything null)? Mirrors home/format.js's
// hasBackedSignal, kept local so the hook has no surface dependency.
function commandCenterHasBackedSignal(data) {
  if (!data || typeof data !== "object") return false;
  const estate = data.estate || {};
  if (
    num(estate.visibleAssetCount) !== null ||
    num(estate.catalogCount) !== null ||
    num(estate.coverageScore) !== null
  ) {
    return true;
  }
  if (Array.isArray(data.kpis) && data.kpis.some((kpi) => num(kpi?.value) !== null)) return true;
  return Array.isArray(data.recentAssets) && data.recentAssets.length > 0;
}


function mergeCommandCenter(seedData, queryData) {
  const base = seedData || EMPTY_COMMAND_CENTER;
  const data = queryData || base;
  const warningSource = queryData || data;
  return {
    ...EMPTY_COMMAND_CENTER,
    ...base,
    ...data,
    estate: {
      ...EMPTY_COMMAND_CENTER.estate,
      ...(base.estate || {}),
      ...(data.estate || {}),
    },
    posture: {
      ...EMPTY_COMMAND_CENTER.posture,
      ...(base.posture || {}),
      ...(data.posture || {}),
    },
    governance: {
      ...EMPTY_COMMAND_CENTER.governance,
      ...(base.governance || {}),
      ...(data.governance || {}),
    },
    insights: {
      ...EMPTY_COMMAND_CENTER.insights,
      ...(base.insights || {}),
      ...(data.insights || {}),
    },
    meta: {
      ...EMPTY_COMMAND_CENTER.meta,
      ...(base.meta || {}),
      ...(data.meta || {}),
      warnings: (warningSource.meta && Array.isArray(warningSource.meta.warnings))
        ? warningSource.meta.warnings
        : [],
    },
    kpis: Array.isArray(data.kpis) ? data.kpis : [],
    topDomains: Array.isArray(data.topDomains) ? data.topDomains : [],
    recentEvents: Array.isArray(data.recentEvents) ? data.recentEvents : [],
    recentAssets: Array.isArray(data.recentAssets) ? data.recentAssets : [],
    quickActions: Array.isArray(data.quickActions) ? data.quickActions : [],
    aiPrompts: Array.isArray(data.aiPrompts) ? data.aiPrompts : [],
  };
}

// Same 15s cold-rebuild cadence as before, now bounded: 8 attempts ≈ 2min of
// server-side "loading" before the loop stops with an honest degraded state
// instead of polling forever. Poll only on the coarse meta.state — a command
// center envelope can be "available" with warnings without re-polling.
const COMMAND_CENTER_POLL = {
  interval: 15_000,
  maxAttempts: 8,
  until: (data) => String(data?.meta?.state || "").trim().toLowerCase() !== "loading",
};

export function useCommandCenter(options = {}) {
  const resolvedOptions = normalizeOptions(options);
  const enabled = resolvedOptions.enabled !== false;
  const seedData = resolvedOptions.seedData || null;
  const [pendingRefresh, setPendingRefresh] = useState(false);

  const { query } = useAtlasQuery({
    key: ["atlas", "command-center", pendingRefresh ? "force" : "cache"],
    fetch: (signal) =>
      fetchCommandCenter({ signal, refresh: pendingRefresh }).finally(() => {
        if (pendingRefresh) setPendingRefresh(false);
      }),
    enabled,
    staleTime: resolvedOptions.staleTime ?? 60_000,
    // Keep the cached dashboard for the whole session so back-nav re-renders it
    // instantly instead of refetching from an empty state.
    gcTime: resolvedOptions.gcTime ?? 30 * 60_000,
    poll: COMMAND_CENTER_POLL,
    // Legacy escape hatch: callers that pass an explicit refetchInterval keep
    // it verbatim until their Wave B/C rewrite adopts the poll contract.
    unsafeRefetchInterval: resolvedOptions.refetchInterval,
  });

  const refreshActorScope = useCallback(() => {
    setPendingRefresh(true);
  }, []);

  // Retention (per-instance, pure): a serverless SQL warehouse goes cold
  // between visits, so a refetch on back-nav can settle on a warming payload
  // with NO backed values and blank a populated dashboard to "—". We keep the
  // last payload that carried real signal in a ref (committed in an effect, not
  // mutated during render) and serve it over a warming payload — but only while
  // a refresh could still replace it: fetch in flight OR the bounded poll still
  // has budget. Once the poll settles on warming, we STOP masking so the honest
  // degraded/warning state surfaces. That bound makes it self-healing: a
  // genuinely-empty/degraded estate can't show phantom old values forever, and
  // an all-zero (backed) estate is treated as real data, never as "warming".
  const freshBacked = commandCenterHasBackedSignal(query.data);
  useEffect(() => {
    if (freshBacked) lastBackedCommandCenter = query.data;
  }, [freshBacked, query.data]);
  const pollExhausted = pollBudgetExhausted(
    ["atlas", "command-center", pendingRefresh ? "force" : "cache"],
    COMMAND_CENTER_POLL.maxAttempts,
  );
  const canRetain =
    !freshBacked && Boolean(lastBackedCommandCenter) && (query.isFetching || !pollExhausted);
  const retainedData = freshBacked ? query.data : canRetain ? lastBackedCommandCenter : query.data;
  const servedFromRetention = canRetain && Boolean(query.data);

  const usableData = retainedData || seedData || null;
  const data = mergeCommandCenter(seedData, retainedData);
  const message = query.error?.message || "Command center is unavailable.";
  const warnings = Array.isArray(data?.meta?.warnings) ? data.meta.warnings : [];
  const refreshError = usableData && query.isError ? message : "";

  return {
    data,
    loading: enabled && query.isPending && !query.data && !seedData,
    hydrating: enabled && query.isPending && !query.data && Boolean(seedData),
    hasLiveData: Boolean(query.data) || servedFromRetention,
    // Serving retained values while a warming refetch is in flight is a refresh
    // in progress, not a settled state — surface it so the "Live" chip reads
    // honestly instead of the page looking frozen.
    refreshing: query.isFetching || servedFromRetention,
    error: usableData ? "" : query.isError ? message : "",
    refreshError,
    degraded:
      data?.meta?.state === "degraded" ||
      Boolean(refreshError) ||
      warnings.length > 0,
    warnings,
    meta: data?.meta || null,
    refresh: query.refetch,
    refreshActorScope,
  };
}

export default useCommandCenter;
