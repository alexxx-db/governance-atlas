import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchDiscoverySearch } from "../lib/api";
import { envelopeHydrating } from "../lib/envelope";
import { isNonAuthoritativeMockEvidence } from "../lib/nonAuthoritativeEvidence";
import { useAtlasQuery } from "./useAtlasQuery";

const DISCOVERY_DEFAULT_FETCH_LIMIT = 80;
const DISCOVERY_MAX_FETCH_LIMIT = 200;

function scopeKey(filters = {}) {
  return JSON.stringify({
    query: String(filters.query || "").trim(),
    views: [...(filters.views || [])].sort(),
    types: [...(filters.types || [])].sort(),
    catalogs: [...(filters.catalogs || [])].sort(),
    domains: [...(filters.domains || [])].sort(),
    tiers: [...(filters.tiers || [])].sort(),
    certifications: [...(filters.certifications || [])].sort(),
    sensitivities: [...(filters.sensitivities || [])].sort(),
    businessCriticalities: [...(filters.businessCriticalities || [])].sort(),
    cdeOnly: Boolean(filters.cdeOnly),
    sortBy: String(filters.sortBy || ""),
  });
}

function payloadAuthoritative(payload) {
  if (!payload || typeof payload !== "object") return false;
  if (isNonAuthoritativeMockEvidence(payload, payload.meta, payload.queryState, payload.warnings)) return false;
  const meta = payload.meta && typeof payload.meta === "object" ? payload.meta : {};
  const state = String(meta.state || meta.discoveryState || payload.state || "").trim().toLowerCase();
  const source = String(meta.source || payload.source || "").trim().toLowerCase();
  if (state === "prototype_mock" || source === "local-prototype-mock") return false;
  if (typeof payload.authoritative === "boolean") return payload.authoritative;
  if (typeof meta.authoritative === "boolean") return meta.authoritative;
  return ["authoritative", "live"].includes(state);
}

function payloadPrototypeMock(payload) {
  if (!payload || typeof payload !== "object") return false;
  return isNonAuthoritativeMockEvidence(payload, payload.meta, payload.queryState, payload.warnings);
}

// The local discoveryRefetchInterval predicate was deleted: lib/envelope.js
// `envelopeHydrating` covers every signal it checked (meta.state,
// meta.discoveryState, queryState.state, inventoryHydrating) and the poll now
// runs through useAtlasQuery's bounded engine — same 3s cadence, now bounded.
const DISCOVERY_POLL = { interval: 3_000, maxAttempts: 20 };

export function useDiscoveryResults(filters, options = {}) {
  const normalizedFilters = useMemo(
    () => ({
      query: String(filters?.query || "").trim(),
      views: [...(filters?.views || [])].sort(),
      types: [...(filters?.types || [])].sort(),
      catalogs: [...(filters?.catalogs || [])].sort(),
      domains: [...(filters?.domains || [])].sort(),
      tiers: [...(filters?.tiers || [])].sort(),
      certifications: [...(filters?.certifications || [])].sort(),
      sensitivities: [...(filters?.sensitivities || [])].sort(),
      businessCriticalities: [...(filters?.businessCriticalities || [])].sort(),
      cdeOnly: Boolean(filters?.cdeOnly),
      sortBy: String(filters?.sortBy || ""),
    }),
    [
      filters?.businessCriticalities,
      filters?.catalogs,
      filters?.cdeOnly,
      filters?.certifications,
      filters?.domains,
      filters?.query,
      filters?.sensitivities,
      filters?.sortBy,
      filters?.tiers,
      filters?.types,
      filters?.views,
    ],
  );
  const currentScopeKey = scopeKey(normalizedFilters);
  const safeLimit = Math.max(
    1,
    Math.min(
      Number.isFinite(Number(options?.limit))
        ? Math.trunc(Number(options.limit))
        : DISCOVERY_DEFAULT_FETCH_LIMIT,
      DISCOVERY_MAX_FETCH_LIMIT,
    ),
  );
  const safeOffset = Math.max(
    0,
    Number.isFinite(Number(options?.offset)) ? Math.trunc(Number(options.offset)) : 0,
  );
  // Bootstrap seed — when the outer app hands us an initial assets array
  // (served by the app's SSR-ish bootstrap endpoint), use it to paint cards
  // IMMEDIATELY instead of sitting on an empty grid for the ~1-3s it takes
  // the structured search to round-trip. Only applies to the default
  // unfiltered scope because the seed reflects that scope.
  const seededAssets = useMemo(
    () => (Array.isArray(options?.seedAssets) ? options.seedAssets : []),
    [options?.seedAssets],
  );
  const seededCount = Number.isFinite(Number(options?.seedCount))
    ? Number(options.seedCount)
    : seededAssets.length;
  const seededScopeIsDefault =
    !normalizedFilters.query &&
    !normalizedFilters.views.length &&
    !normalizedFilters.types.length &&
    !normalizedFilters.catalogs.length &&
    !normalizedFilters.domains.length &&
    !normalizedFilters.tiers.length &&
    !normalizedFilters.certifications.length &&
    !normalizedFilters.sensitivities.length;
  const seededFacets = options?.seedFacets && typeof options.seedFacets === "object"
    ? options.seedFacets
    : null;
  const seededFallback = useMemo(
    () =>
      seededAssets.length && seededScopeIsDefault
        ? { assets: seededAssets, count: seededCount, facets: seededFacets }
        : { assets: [], count: 0, facets: null },
    [seededAssets, seededCount, seededFacets, seededScopeIsDefault],
  );
  const lastAuthoritativeResultRef = useRef({
    scopeKey: "",
    data: seededFallback,
  });
  // Stale-while-revalidate ACROSS scope changes: keep the last authoritative
  // results on screen while a filter change refetches, instead of collapsing to
  // an empty skeleton (which made the whole grid shrink then re-expand — the
  // reported filter-click flicker). The "Refreshing" indicator on DiscoveryPage
  // signals the in-flight update; results swap in when the new scope resolves.
  const lastData = lastAuthoritativeResultRef.current.data;
  const placeholderData =
    lastData && Array.isArray(lastData.assets) && lastData.assets.length
      ? lastData
      : seededFallback;
  // Round 19 OBO hardening: one-shot cache-bypass flag. When the user
  // clicks "Retry with actor scope" on the fallback banner, we send
  // ?refresh=1 on the next fetch so the server evicts the per-actor
  // inventory cache and re-attempts OBO from scratch. The flag resets
  // after the fetch resolves so normal caching resumes.
  const [pendingRefresh, setPendingRefresh] = useState(false);
  const queryClient = useQueryClient();
  const { query } = useAtlasQuery({
    key: ["discoveryResults", currentScopeKey, safeLimit, safeOffset, pendingRefresh ? "force" : "cache"],
    fetch: (signal) =>
      fetchDiscoverySearch(
        {
          ...normalizedFilters,
          queryMode: "structured",
          limit: safeLimit,
          offset: safeOffset,
          refresh: pendingRefresh,
        },
        { signal },
      ).finally(() => {
        if (pendingRefresh) setPendingRefresh(false);
      }),
    placeholderData,
    poll: DISCOVERY_POLL,
    // Legacy escape hatch: callers that pass an explicit refetchInterval keep
    // it verbatim until their Wave B/C rewrite adopts the poll contract.
    unsafeRefetchInterval: options?.refetchInterval,
  });
  const refreshActorScope = useCallback(() => {
    setPendingRefresh(true);
    queryClient.invalidateQueries({ queryKey: ["discoveryResults"] });
  }, [queryClient]);
  const usingPlaceholder = query.isPlaceholderData === true;
  const currentPayloadPrototypeMock = query.isSuccess && !usingPlaceholder && payloadPrototypeMock(query.data);
  const assets = currentPayloadPrototypeMock ? [] : query.data?.assets || seededFallback.assets;
  const count = currentPayloadPrototypeMock ? 0 : typeof query.data?.count === "number" ? query.data.count : seededFallback.count;
  /** @type {{ status?: number, payload?: { invalidQuery?: { state?: string, message?: string, syntaxHint?: string, supportedFields?: string[] } } } | null} */
  const discoveryError =
    query.error && typeof query.error === "object"
      ? /** @type {{ status?: number, payload?: { invalidQuery?: { state?: string, message?: string, syntaxHint?: string, supportedFields?: string[] } } }} */ (query.error)
      : null;
  const invalidQuery =
    query.isError && discoveryError?.status === 400 && discoveryError?.payload?.invalidQuery
      ? discoveryError.payload.invalidQuery
      : null;

  const currentPayloadAuthoritative = !currentPayloadPrototypeMock && payloadAuthoritative(query.data);
  const currentMeta = query.data?.meta && typeof query.data.meta === "object" ? query.data.meta : null;
  // Single shared hydration predicate (covers state/discoveryState/
  // queryState fallbacks + inventoryHydrating — same signals as before).
  const inventoryHydrating = envelopeHydrating(query.data);

  useEffect(() => {
    if (query.isSuccess && !usingPlaceholder && currentPayloadAuthoritative) {
      lastAuthoritativeResultRef.current = {
        scopeKey: currentScopeKey,
        data: query.data || seededFallback,
      };
    }
  }, [currentPayloadAuthoritative, currentScopeKey, query.data, query.isSuccess, seededFallback, usingPlaceholder]);

  return {
    // Show the skeleton ONLY when there's nothing to display. While refetching a
    // new scope we keep the previous results on screen (usingPlaceholder with
    // non-empty assets) and expose `fetching` for the quiet "Refreshing"
    // indicator — no collapse-to-skeleton flicker.
    loading:
      query.isPending ||
      (query.isFetching && usingPlaceholder && !assets.length) ||
      inventoryHydrating,
    error:
      query.isError && !invalidQuery
        ? query.error?.message || "Failed to search metadata assets."
        : "",
    assets,
    count,
    facets: currentPayloadPrototypeMock ? null : query.data?.facets || seededFallback.facets,
    queryState: invalidQuery || (currentPayloadPrototypeMock ? { state: "unavailable", message: "Non-authoritative discovery payload rejected." } : query.data?.queryState) || null,
    // Expose the envelope `meta` block so downstream surfaces (diagnostics
    // strip for A1.4) can read the fine-grained discoveryState vocabulary
    // and observedAt timestamp without refetching.
    meta:
      currentMeta,
    refreshActorScope,
    refreshing: query.isFetching,
    requestKey: currentScopeKey,
    fetching: query.isFetching,
    fetchLimit: safeLimit,
    settled: query.isError || (query.isSuccess && !usingPlaceholder && !inventoryHydrating),
    authoritative: query.isSuccess && !usingPlaceholder && currentPayloadAuthoritative,
  };
}
