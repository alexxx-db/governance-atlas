import { useMemo } from "react";
import { fetchAsset360 } from "../lib/api";
import { envelopeHydrating } from "../lib/envelope";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { useAxiomQuery } from "./useAxiomQuery";

export const EMPTY_ASSET_360 = {
  asset: null,
  owners: [],
  stewards: [],
  badges: [],
  freshness: { state: "unavailable", observedAt: "", message: "" },
  usage: {},
  schema: [],
  governance: {
    glossaryTerms: [],
    ownerAssignments: [],
    openActivity: [],
  },
  quality: { state: "unavailable", runs: [], message: "" },
  access: { state: "unavailable", message: "" },
  activity: [],
  relatedAssets: [],
  downstreamDashboards: [],
  loadedSections: [],
  meta: null,
};

function normalizeAsset360Payload(payload, assetFqn = "") {
  const data = payload && typeof payload === "object" ? payload : {};
  if (isNonAuthoritativeMockEvidence(data, data.meta, data.asset, data.warnings)) {
    return {
      ...EMPTY_ASSET_360,
      meta: {
        state: "non_authoritative",
        warnings: ["Non-authoritative Asset 360 payload rejected."],
      },
      sameAsset: false,
    };
  }
  const asset = data.asset && typeof data.asset === "object" ? data.asset : null;
  return {
    ...EMPTY_ASSET_360,
    ...data,
    asset,
    owners: Array.isArray(data.owners) ? data.owners : [],
    stewards: Array.isArray(data.stewards) ? data.stewards : [],
    badges: Array.isArray(data.badges) ? data.badges : [],
    usage: data.usage && typeof data.usage === "object" ? data.usage : {},
    schema: Array.isArray(data.schema) ? data.schema : [],
    governance: {
      ...EMPTY_ASSET_360.governance,
      ...(data.governance && typeof data.governance === "object" ? data.governance : {}),
    },
    quality: {
      ...EMPTY_ASSET_360.quality,
      ...(data.quality && typeof data.quality === "object" ? data.quality : {}),
    },
    access: {
      ...EMPTY_ASSET_360.access,
      ...(data.access && typeof data.access === "object" ? data.access : {}),
    },
    freshness: {
      ...EMPTY_ASSET_360.freshness,
      ...(data.freshness && typeof data.freshness === "object" ? data.freshness : {}),
    },
    activity: Array.isArray(data.activity) ? data.activity : [],
    relatedAssets: Array.isArray(data.relatedAssets) ? data.relatedAssets : [],
    downstreamDashboards: Array.isArray(data.downstreamDashboards) ? data.downstreamDashboards : [],
    loadedSections: Array.isArray(data.loadedSections) ? data.loadedSections : [],
    sameAsset: Boolean(asset?.fqn && asset?.fqn === assetFqn),
  };
}

// Poll while the composite is hydrating OR while it has started streaming
// sections but the schema section (the one every consumer needs) hasn't
// landed. `until` returns true to STOP; the loadedSections check is
// deliberately identical to the deleted local refetchInterval — only the
// hydration half moved to the shared lib/envelope.js predicate. Same 3s
// cadence as before, now bounded (~1min).
const ASSET_360_POLL = {
  interval: 3_000,
  maxAttempts: 20,
  until: (payload) => {
    if (envelopeHydrating(payload)) return false;
    const capabilities = payload?.meta?.capabilities;
    const loadedSections = Array.isArray(capabilities?.loadedSections)
      ? capabilities.loadedSections
      : Array.isArray(payload?.loadedSections)
        ? payload.loadedSections
        : [];
    if (loadedSections.length && !loadedSections.includes("schema")) return false;
    return true;
  },
};

export function useAsset360(assetFqn, options = {}) {
  /** @type {{ enabled?: boolean, staleTime?: number, gcTime?: number, refetchInterval?: number | false }} */
  const resolvedOptions = options && typeof options === "object" ? options : {};
  const normalizedFqn = String(assetFqn || "").trim();
  const enabled = resolvedOptions.enabled !== false && Boolean(normalizedFqn);
  const { query } = useAxiomQuery({
    key: ["axiom", "asset360", normalizedFqn],
    fetch: (signal) => fetchAsset360(normalizedFqn, { signal }),
    enabled,
    staleTime: resolvedOptions.staleTime ?? 60_000,
    gcTime: resolvedOptions.gcTime ?? 5 * 60_000,
    poll: ASSET_360_POLL,
    // Legacy escape hatch for callers passing an explicit refetchInterval.
    unsafeRefetchInterval: resolvedOptions.refetchInterval,
  });
  const data = useMemo(
    () => (query.data ? normalizeAsset360Payload(query.data, normalizedFqn) : null),
    [normalizedFqn, query.data],
  );
  return {
    data,
    loading: enabled && query.isPending,
    refreshing: query.isFetching && Boolean(query.data),
    error: query.error?.message || "",
    meta: data?.meta || null,
    refetch: query.refetch,
  };
}

export default useAsset360;
