import { useMemo } from "react";
import { fetchAssetAvailability, fetchAssetDetail, fetchAssetHeaders } from "../lib/api";
import { envelopeHydrating } from "../lib/envelope";
import { isNonAuthoritativeEvidenceEnvelope } from "../lib/nonAuthoritativeEvidence";
import { axiomQueryClient } from "../lib/queryClient";
import { useAxiomQuery } from "./useAxiomQuery";

const PLACEHOLDER_DESCRIPTION = "No description has been captured for this asset yet.";
const DETAIL_CACHE_TTL_MS = 20_000;
const AVAILABILITY_CACHE_TTL_MS = 10_000;
const ASSET_DETAIL_CANONICAL_PREFIX = "assetDetailCanonical";
const ASSET_DETAIL_REQUEST_PREFIX = "assetDetail";
const ASSET_AVAILABILITY_CANONICAL_PREFIX = "assetAvailabilityCanonical";
const ASSET_AVAILABILITY_REQUEST_PREFIX = "assetAvailability";
const DETAIL_SECTION_FIELDS = {
  header: [
    "fqn",
    "name",
    "catalog",
    "schema",
    "objectType",
    "description",
    "coverageScore",
    "rows",
    "format",
    "storageFormat",
    "tableTypeRaw",
    "managementType",
    "size",
    "files",
    "domain",
    "tier",
    "certification",
    "sensitivity",
    "criticality",
    "openRequests",
    // Freshness split + role/CDE facts ride the header payload; omitting
    // them from the merge list left stub-cached empties in place until the
    // /360 composite turned terminal (verifier round-4 hygiene note).
    "dataUpdatedAt",
    "lastAltered",
    "updatedAt",
    "isCde",
    "ucOwner",
    "businessOwner",
    "technicalOwner",
    "steward",
    "owners",
    "tags",
    "glossaryTerm",
    "glossaryTerms",
    "glossaryLinks",
    "governanceStatus",
    "metadataEditor",
  ],
  activity: ["ownerAssignments", "activity", "metadataAudit"],
  schema: ["columns", "columnCount"],
  preview: ["preview"],
  properties: ["tableProperties", "customProperties", "constraints"],
  operational: ["relatedAssets", "operationalContext", "queries", "usage"],
  profiler: ["profiler"],
};
const DEFAULT_DETAIL_SECTIONS = Object.keys(DETAIL_SECTION_FIELDS);

function normalizeDetailSections(sections = []) {
  if (!Array.isArray(sections) || !sections.length) return [];
  return [...new Set(sections.map((section) => String(section || "").trim().toLowerCase()).filter(Boolean))].sort();
}

function assetDetailCanonicalKey(assetFqn) {
  return [ASSET_DETAIL_CANONICAL_PREFIX, assetFqn];
}

function assetDetailRequestKey(assetFqn, sections = []) {
  const normalizedSections = normalizeDetailSections(sections);
  return [ASSET_DETAIL_REQUEST_PREFIX, assetFqn, normalizedSections.join(",") || "all"];
}

function assetAvailabilityCanonicalKey(assetFqn) {
  return [ASSET_AVAILABILITY_CANONICAL_PREFIX, assetFqn];
}

function assetAvailabilityRequestKey(targets = [], strict = false, requireRenderableDetail = false, visibilitySignature = "") {
  return [
    ASSET_AVAILABILITY_REQUEST_PREFIX,
    targets.slice().sort().join("|"),
    strict ? 1 : 0,
    requireRenderableDetail ? 1 : 0,
    visibilitySignature,
  ];
}

function queryUpdatedAt(queryKey) {
  return axiomQueryClient.getQueryState(queryKey)?.dataUpdatedAt || 0;
}

function isFresh(queryKey, maxAgeMs = null) {
  if (maxAgeMs == null) return true;
  const updatedAt = queryUpdatedAt(queryKey);
  if (!updatedAt) return false;
  return Date.now() - updatedAt <= maxAgeMs;
}

// P0-2 fix (ASSET360_TEARDOWN): callers pass `{ maxAgeMs: null }` to mean
// "no age limit — give me whatever canonical data exists". The old
// `options.maxAgeMs ?? TTL` treated that explicit null as UNSET
// (`null ?? x === x`), silently re-imposing the 20s TTL, so any tab switch
// >20s after load read the canonical cache as absent and regressed the whole
// record to the loading shell. Only an *omitted* option may fall back to the
// TTL; explicit null (and explicit numbers) must pass through untouched.
function resolveMaxAgeMs(options, fallback) {
  return "maxAgeMs" in options ? options.maxAgeMs : fallback;
}

function readCanonicalDetail(assetFqn, options = {}) {
  if (!assetFqn) return null;
  const queryKey = assetDetailCanonicalKey(assetFqn);
  const detail = axiomQueryClient.getQueryData(queryKey) || null;
  if (!detail) return null;
  if (!isFresh(queryKey, resolveMaxAgeMs(options, DETAIL_CACHE_TTL_MS))) return null;
  return detail;
}

function readCanonicalAvailability(assetFqn, options = {}) {
  if (!assetFqn) return null;
  const queryKey = assetAvailabilityCanonicalKey(assetFqn);
  const detail = axiomQueryClient.getQueryData(queryKey) || null;
  if (!detail) return null;
  if (!isFresh(queryKey, resolveMaxAgeMs(options, AVAILABILITY_CACHE_TTL_MS))) return null;
  return detail;
}

function cachedDetailHasSections(detail, sections = []) {
  const normalizedSections = normalizeDetailSections(sections);
  if (!normalizedSections.length) return Boolean(detail);
  const loadedSections = new Set(detail?.loadedSections || []);
  return normalizedSections.every((section) => loadedSections.has(section));
}

// Local `detailHydrating` + `assetDetailRefetchInterval` were deleted: the
// hydration predicate is now the shared lib/envelope.js `envelopeHydrating`
// (a superset of the old local check) and polling runs through
// useAxiomQuery's bounded engine — same 3s cadence, now attempt-bounded.

function mergeLoadedSections(currentDetail, incomingDetail) {
  const merged = new Set([...(currentDetail?.loadedSections || []), ...(incomingDetail?.loadedSections || [])]);
  return [...merged].sort();
}

function mergeAssetDetail(currentDetail, incomingDetail) {
  if (!currentDetail) return incomingDetail;
  if (!incomingDetail) return currentDetail;

  const merged = {
    ...currentDetail,
  };
  const incomingSections = new Set(incomingDetail.loadedSections || []);
  const mergedSections = mergeLoadedSections(currentDetail, incomingDetail);

  Object.entries(DETAIL_SECTION_FIELDS).forEach(([section, fields]) => {
    if (!incomingSections.has(section)) return;
    fields.forEach((field) => {
      merged[field] = incomingDetail[field];
    });
  });

  Object.keys(incomingDetail).forEach((field) => {
    if (field in merged) return;
    merged[field] = incomingDetail[field];
  });

  // A terminal payload retires the hydrating-stub markers. Without this, a
  // cached inventory-rebuild stub's `hydrating`/`headerSource` flags survive
  // the merge forever and consumers keep rejecting a record that is now real
  // (Wave-B verifier round-3: hub stayed skeletoned 70s past available truth).
  if (incomingDetail.hydrating !== true) {
    merged.hydrating = incomingDetail.hydrating ?? false;
    if (String(merged.headerSource || "") === "live-metadata-hydrating") {
      merged.headerSource = incomingDetail.headerSource || "";
    }
  }

  merged.loadedSections = mergedSections;
  merged.deferredSections = DEFAULT_DETAIL_SECTIONS.filter((section) => !mergedSections.includes(section));
  return merged;
}

function setCanonicalDetail(assetFqn, detail) {
  if (isNonAuthoritativeEvidenceEnvelope(detail)) {
    // Stability fix (persona audit P1 "unstable detail shell"): a degraded /
    // non-authoritative refetch used to WIPE the canonical cache, which
    // blanked an already-rendered header into loading skeletons and shrank
    // the tab set mid-session. Keep previously loaded authoritative data on
    // screen; only clear when we never had anything real for this asset.
    const existing = readCanonicalDetail(assetFqn, { maxAgeMs: null });
    if (existing) {
      syncAvailabilityRequestsForAsset(assetFqn);
      return existing;
    }
    axiomQueryClient.removeQueries({ queryKey: assetDetailCanonicalKey(assetFqn), exact: true });
    axiomQueryClient.removeQueries({ queryKey: [ASSET_DETAIL_REQUEST_PREFIX, assetFqn] });
    syncAvailabilityRequestsForAsset(assetFqn);
    return null;
  }
  const current = readCanonicalDetail(assetFqn, { maxAgeMs: null });
  const mergedDetail = mergeAssetDetail(current, detail);
  axiomQueryClient.setQueryData(assetDetailCanonicalKey(assetFqn), mergedDetail);
  axiomQueryClient.setQueriesData(
    { queryKey: [ASSET_DETAIL_REQUEST_PREFIX, assetFqn] },
    mergedDetail,
  );
  syncAvailabilityRequestsForAsset(assetFqn);
  return mergedDetail;
}

function setCanonicalAvailability(assetFqn, availability) {
  axiomQueryClient.setQueryData(assetAvailabilityCanonicalKey(assetFqn), availability);
  syncAvailabilityRequestsForAsset(assetFqn);
  return availability;
}

function buildVisibilitySignature(targets = [], knownVisibleAssetSet = null) {
  return targets.map((assetFqn) => (knownVisibleAssetSet?.has?.(assetFqn) ? "1" : "0")).join("");
}

function knownVisibleLookup(targets = [], visibilitySignature = "") {
  return {
    has(assetFqn) {
      const index = targets.indexOf(assetFqn);
      return index >= 0 && visibilitySignature.charAt(index) === "1";
    },
  };
}

function parseAvailabilityRequestKey(queryKey = /** @type {readonly unknown[]} */ ([])) {
  const targets = String(queryKey?.[1] || "")
    .split("|")
    .filter(Boolean);
  return {
    targets,
    strict: Number(queryKey?.[2] || 0) === 1,
    requireRenderableDetail: Number(queryKey?.[3] || 0) === 1,
    visibilitySignature: String(queryKey?.[4] || ""),
  };
}

function syncAvailabilityRequestsForAsset(assetFqn) {
  axiomQueryClient
    .getQueryCache()
    .findAll({ queryKey: [ASSET_AVAILABILITY_REQUEST_PREFIX] })
    .forEach((query) => {
      const { targets, strict, requireRenderableDetail, visibilitySignature } = parseAvailabilityRequestKey(query.queryKey);
      if (!targets.includes(assetFqn)) return;
      axiomQueryClient.setQueryData(
        query.queryKey,
        buildAvailabilityStateMap(
          targets,
          knownVisibleLookup(targets, visibilitySignature),
          {
            strict,
            requireRenderableDetail,
            maxAgeMs: strict ? AVAILABILITY_CACHE_TTL_MS : null,
          },
        ),
      );
    });
}

function readCachedDetail(assetFqn, options = {}) {
  const detail = readCanonicalDetail(assetFqn, { maxAgeMs: resolveMaxAgeMs(options, DETAIL_CACHE_TTL_MS) });
  if (!detail) return null;
  if (!cachedDetailHasSections(detail, options.sections)) return null;
  return detail;
}

function availabilityOpenableValue(availability = null) {
  if (!availability || typeof availability !== "object") return null;
  if (typeof availability.openable === "boolean") return availability.openable;
  if (typeof availability.visible === "boolean") return availability.visible;
  return null;
}

function resolveAvailabilityState(
  availability = null,
  knownVisible = false,
  strict = false,
  requireRenderableDetail = false,
  detail = null,
) {
  const availabilityOpenable = strict
    ? availabilityOpenableValue(availability) === true
      ? true
      : availabilityOpenableValue(availability) === false
        ? false
        : null
    : knownVisible || availabilityOpenableValue(availability) === true
      ? true
      : availabilityOpenableValue(availability) === false
        ? false
        : null;
  if (availabilityOpenable !== true) return availabilityOpenable;
  if (!requireRenderableDetail) return true;
  if (!detail) return null;
  return hasRenderableAssetRecord(detail) ? true : false;
}

function buildAvailabilityStateMap(targets = [], knownVisibleAssetSet = null, options = {}) {
  const strict = options.strict === true;
  const requireRenderableDetail = options.requireRenderableDetail === true;
  const maxAgeMs = resolveMaxAgeMs(options, strict ? AVAILABILITY_CACHE_TTL_MS : null);
  return Object.fromEntries(
    targets.map((assetFqn) => {
      const knownVisible = knownVisibleAssetSet?.has?.(assetFqn) === true;
      const availability = readCanonicalAvailability(assetFqn, { maxAgeMs });
      const detail = requireRenderableDetail
        ? readCanonicalDetail(assetFqn, { maxAgeMs: DETAIL_CACHE_TTL_MS })
        : null;
      return [
        assetFqn,
        resolveAvailabilityState(
          availability,
          knownVisible,
          strict,
          requireRenderableDetail,
          detail,
        ),
      ];
    }),
  );
}

async function ensureAssetDetail(assetFqn, options = {}) {
  if (!assetFqn) return null;
  const cachedDetail = options.force !== true
    ? readCachedDetail(assetFqn, {
        sections: options.sections,
        maxAgeMs: resolveMaxAgeMs(options, DETAIL_CACHE_TTL_MS),
      })
    : null;
  if (cachedDetail) return cachedDetail;

  const detail = await fetchAssetDetail(assetFqn, {
    sections: options.sections,
    signal: options.signal,
  });
  return setCanonicalDetail(assetFqn, detail);
}

async function ensureAssetAvailability(assetFqns = [], options = {}) {
  const targets = [...new Set((assetFqns || []).filter(Boolean))].sort();
  if (!targets.length) return {};

  const strict = options.strict === true;
  const requireRenderableDetail = options.requireRenderableDetail === true;
  const maxAgeMs = options.force === true
    ? 0
    : resolveMaxAgeMs(options, strict ? AVAILABILITY_CACHE_TTL_MS : null);

  const missing = options.force === true
    ? targets
    : targets.filter((assetFqn) => !readCanonicalAvailability(assetFqn, { maxAgeMs }));

  if (missing.length) {
    const payload = await fetchAssetAvailability(missing, { signal: options.signal });
    const assets = payload?.assets || {};
    missing.forEach((assetFqn) => {
      setCanonicalAvailability(
        assetFqn,
        assets[assetFqn] || {
          visible: false,
          exists: false,
          openable: false,
        },
      );
    });
  }

  if (requireRenderableDetail) {
    const renderableTargets = targets.filter((assetFqn) => {
      const availability = readCanonicalAvailability(assetFqn, { maxAgeMs: null });
      return availabilityOpenableValue(availability) === true;
    });
    // Perf audit P0 (Discovery prefetch storm): this used to fan out ~47
    // individual GET /api/assets/<fqn>?sections=header requests 4-at-a-time
    // (45s+ of serialized network). One POST /api/assets/headers batch call
    // returns the same header shape for every target in a single round
    // trip; we seed the per-FQN react-query detail cache from the batch so
    // preview panels stay instant without any per-asset request.
    const missingHeaderTargets = renderableTargets.filter(
      (assetFqn) => !readCachedDetail(assetFqn, { sections: ["header"] }),
    );
    if (missingHeaderTargets.length) {
      try {
        const payload = await fetchAssetHeaders(missingHeaderTargets, { signal: options.signal });
        const assets = payload?.assets && typeof payload.assets === "object" ? payload.assets : {};
        const batchHydrating =
          String(payload?.meta?.state || "").trim().toLowerCase() === "loading";
        missingHeaderTargets.forEach((assetFqn) => {
          const header = assets[assetFqn];
          // Never cache error stubs or inventory-loading placeholders as a
          // resolved header — a later real fetch must still happen.
          if (!header || typeof header !== "object" || header.error) return;
          if (batchHydrating || header.headerSource === "inventory-loading") return;
          setCanonicalDetail(assetFqn, {
            ...header,
            loadedSections: Array.isArray(header.loadedSections) && header.loadedSections.length
              ? header.loadedSections
              : ["header"],
          });
        });
      } catch {
        // Best-effort warm-up: a failed batch must not stall availability
        // resolution — individual consumers fetch on demand as before.
      }
    }
  }

  return buildAvailabilityStateMap(targets, options.knownVisibleAssetSet, {
    strict,
    requireRenderableDetail,
    maxAgeMs: strict ? AVAILABILITY_CACHE_TTL_MS : null,
  });
}

export function primeAssetDetail(assetFqn, detail) {
  if (!assetFqn || !detail) return detail || null;
  return setCanonicalDetail(assetFqn, detail);
}

export function primeAssetAvailability(assetFqn, availability) {
  if (!assetFqn || !availability) return availability || null;
  return setCanonicalAvailability(assetFqn, availability);
}

export function invalidateAssetDetail(assetFqn) {
  if (!assetFqn) return Promise.resolve();
  axiomQueryClient.removeQueries({ queryKey: assetDetailCanonicalKey(assetFqn), exact: true });
  return axiomQueryClient.invalidateQueries({ queryKey: [ASSET_DETAIL_REQUEST_PREFIX, assetFqn] });
}

export function invalidateAssetAvailability(assetFqns = []) {
  const targets = [...new Set((assetFqns || []).filter(Boolean))];
  targets.forEach((assetFqn) => {
    axiomQueryClient.removeQueries({ queryKey: assetAvailabilityCanonicalKey(assetFqn), exact: true });
  });
  return axiomQueryClient.invalidateQueries({ queryKey: [ASSET_AVAILABILITY_REQUEST_PREFIX] });
}

export function prefetchAssetDetail(assetFqn, options = {}) {
  if (!assetFqn) return Promise.resolve(null);
  const force = options.force === true;
  const cachedDetail = force
    ? null
    : readCachedDetail(assetFqn, {
        sections: options.sections,
        maxAgeMs: resolveMaxAgeMs(options, DETAIL_CACHE_TTL_MS),
      });
  if (cachedDetail) return Promise.resolve(cachedDetail);

  return axiomQueryClient.fetchQuery({
    queryKey: assetDetailRequestKey(assetFqn, options.sections),
    staleTime: force ? 0 : DETAIL_CACHE_TTL_MS,
    queryFn: ({ signal }) =>
      ensureAssetDetail(assetFqn, {
        sections: options.sections,
        signal: options.signal || signal,
        force,
        maxAgeMs: options.maxAgeMs,
      }),
  }).catch(() => readCanonicalDetail(assetFqn, { maxAgeMs: null }) || null);
}

export function prefetchAssetAvailability(assetFqns = [], options = {}) {
  const targets = [...new Set((assetFqns || []).filter(Boolean))].sort();
  if (!targets.length) return Promise.resolve({});

  const strict = options.strict === true;
  const requireRenderableDetail = options.requireRenderableDetail === true;
  const visibilitySignature = buildVisibilitySignature(targets, options.knownVisibleAssetSet);
  const cachedAvailability = options.force === true
    ? null
    : buildAvailabilityStateMap(targets, options.knownVisibleAssetSet, {
        strict,
        requireRenderableDetail,
        maxAgeMs: strict ? AVAILABILITY_CACHE_TTL_MS : null,
      });
  const hasAllCachedValues = cachedAvailability && targets.every((assetFqn) => cachedAvailability[assetFqn] !== undefined);
  if (hasAllCachedValues && targets.every((assetFqn) => readCanonicalAvailability(assetFqn, {
    maxAgeMs: resolveMaxAgeMs(options, strict ? AVAILABILITY_CACHE_TTL_MS : null),
  }))) {
    return Promise.resolve(cachedAvailability);
  }

  return axiomQueryClient.fetchQuery({
    queryKey: assetAvailabilityRequestKey(
      targets,
      strict,
      requireRenderableDetail,
      visibilitySignature,
    ),
    staleTime: options.force === true ? 0 : AVAILABILITY_CACHE_TTL_MS,
    queryFn: ({ signal }) =>
      ensureAssetAvailability(targets, {
        force: options.force === true,
        knownVisibleAssetSet: options.knownVisibleAssetSet,
        strict,
        requireRenderableDetail,
        maxAgeMs: options.maxAgeMs,
        signal: options.signal || signal,
      }),
  }).catch(() =>
    buildAvailabilityStateMap(targets, options.knownVisibleAssetSet, {
      strict,
      requireRenderableDetail,
      maxAgeMs: null,
    }),
  );
}

export function isUsableAssetDetail(detail) {
  if (!detail?.fqn) return false;
  return (
    hasStructuredAssetDetail(detail) ||
    hasLiveAssetSignals(detail) ||
    hasResolvedAssetIdentity(detail)
  );
}

export function hasStructuredAssetDetail(detail) {
  if (!detail?.fqn) return false;
  if (Array.isArray(detail.columns) && detail.columns.length) return true;
  if (Array.isArray(detail.preview) && detail.preview.length) return true;
  return false;
}

export function hasLiveAssetSignals(detail) {
  if (!detail?.fqn) return false;
  const description = String(detail?.description || "").trim();
  if (description && description !== PLACEHOLDER_DESCRIPTION && description !== "—") return true;
  if (detail?.rows != null && detail.rows !== "" && detail.rows !== "—") return true;
  if (detail?.size != null && detail.size !== "" && detail.size !== "—") return true;
  if (detail?.files != null && detail.files !== "" && detail.files !== "—") return true;
  return false;
}

export function hasResolvedAssetIdentity(detail) {
  if (!detail?.fqn) return false;
  const rawTableType = String(detail?.tableTypeRaw || "").trim();
  if (rawTableType) return true;
  const managementType = String(detail?.managementType || "").trim();
  if (managementType && managementType !== "—") return true;
  const objectType = String(detail?.objectType || "").trim();
  if (objectType && !objectType.toLowerCase().includes("unknown")) return true;
  const storageFormat = String(detail?.storageFormat || detail?.format || "").trim();
  if (storageFormat && storageFormat !== "—" && !storageFormat.toLowerCase().includes("unknown")) {
    return true;
  }
  return false;
}

export function isNavigableAssetDetail(detail) {
  if (!detail?.fqn) return false;
  return hasStructuredAssetDetail(detail) || hasLiveAssetSignals(detail);
}

export function hasRenderableAssetRecord(detail) {
  if (!detail?.fqn) return false;
  return isNavigableAssetDetail(detail) || hasResolvedAssetIdentity(detail);
}

export function canOpenLinkedAssetRecord(detail, availability = null) {
  const availabilityOpenable = availabilityOpenableValue(availability);
  if (availabilityOpenable === false) return false;
  if (availabilityOpenable === true) return true;
  return hasRenderableAssetRecord(detail);
}

export function canOpenAssetRecord(detail, availability = null) {
  const availabilityOpenable = availabilityOpenableValue(availability);
  if (availabilityOpenable === false) return false;
  if (availabilityOpenable === true) return true;
  return hasRenderableAssetRecord(detail);
}

export function useAssetAvailability(assetFqns = [], knownVisibleAssetSet = null, options = {}) {
  const targets = useMemo(
    () => [...new Set((assetFqns || []).filter(Boolean))].sort(),
    [assetFqns],
  );
  const strict = options?.strict === true;
  const requireRenderableDetail = options?.requireRenderableDetail === true;
  const visibilitySignature = useMemo(
    () => buildVisibilitySignature(targets, knownVisibleAssetSet),
    [knownVisibleAssetSet, targets],
  );
  const placeholder = useMemo(
    () =>
      buildAvailabilityStateMap(targets, knownVisibleAssetSet, {
        strict,
        requireRenderableDetail,
        maxAgeMs: strict ? AVAILABILITY_CACHE_TTL_MS : null,
      }),
    [knownVisibleAssetSet, requireRenderableDetail, strict, targets],
  );

  const availability = useAxiomQuery({
    key: assetAvailabilityRequestKey(
      targets,
      strict,
      requireRenderableDetail,
      visibilitySignature,
    ),
    enabled: targets.length > 0,
    fetch: (signal) =>
      ensureAssetAvailability(targets, {
        knownVisibleAssetSet,
        strict,
        requireRenderableDetail,
        signal,
      }),
    placeholderData: placeholder,
    staleTime: AVAILABILITY_CACHE_TTL_MS,
  });

  return targets.length ? availability.query.data || placeholder : {};
}

export function useAssetDetail(assetFqn, options = {}) {
  const enabled = options.enabled !== false;
  const sections = useMemo(
    () => normalizeDetailSections(options.sections || []),
    [options.sections],
  );
  const cachedAnyDetail = assetFqn ? readCanonicalDetail(assetFqn, { maxAgeMs: null }) : null;
  const placeholder = cachedAnyDetail || null;
  const axiomQuery = useAxiomQuery({
    key: assetDetailRequestKey(assetFqn || "", sections),
    enabled: Boolean(enabled && assetFqn),
    fetch: (signal) =>
      ensureAssetDetail(assetFqn, {
        sections,
        signal,
      }),
    placeholderData: placeholder || undefined,
    staleTime: DETAIL_CACHE_TTL_MS,
    // Same 3s hydration-poll cadence as before, now bounded: 20 attempts
    // (~60s) comfortably covers the observed 5-7s cold consolidated build;
    // on exhaustion useAxiomQuery degrades with an honest warning instead of
    // polling a stuck backend forever.
    poll: { interval: 3_000, maxAttempts: 20 },
    // Reliability fix (persona audit P0 "Asset unavailable" wall): the detail
    // API demonstrably answers in ~2s, but a single transient client timeout /
    // gateway blip used to become a terminal error (global retry: false).
    // One retry absorbs the blip; a genuine outage still errors out.
    retry: 1,
    retryDelay: 800,
  });
  const query = axiomQuery.query;

  if (!assetFqn) {
    return {
      loading: false,
      error: "",
      detail: null,
      retry: async () => null,
    };
  }

  if (!enabled) {
    return {
      loading: false,
      error: "",
      detail: cachedAnyDetail,
      retry: async () => null,
    };
  }

  const detail = query.data || placeholder || null;
  const missingRequestedSections = !cachedDetailHasSections(detail, sections);
  const hydrating = envelopeHydrating(detail);
  return {
    loading:
      Boolean(query.isPending && !detail) ||
      Boolean(query.isFetching && missingRequestedSections) ||
      // Honesty fix (persona audit P2 preview banner): a hydrating server
      // envelope only counts as "loading" while the requested sections are
      // still absent. Once real data is on screen the background poll keeps
      // refreshing it silently — no sticky "Refreshing preview" banner.
      Boolean(hydrating && missingRequestedSections),
    error:
      query.isError && missingRequestedSections
        ? query.error?.message || "Failed to load asset detail."
        : "",
    detail,
    // Working Retry affordance for the terminal-failure placeholder.
    retry: query.refetch,
  };
}
