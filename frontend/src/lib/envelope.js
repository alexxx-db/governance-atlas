// The ONE envelope-status implementation for the Axiom frontend.
//
// Before this module existed, "is this envelope still hydrating?" was
// copy-pasted 11+ times (CdeWorkspace, AdminWorkspace, AuditBrowserWorkspace,
// TaxonomyWorkspace, useLineage, useAssetDetail, useAsset360,
// useDiscoveryResults, useLineageRecommendations, useInsightsDashboard,
// useCommandCenter, ...) and each copy drifted: some checked
// `capabilities.hydrating`, some `inventoryHydrating`, some only
// `meta.state === "loading"`. Every data hook and (eventually) every surface
// must resolve envelope semantics through these helpers and nothing else.
//
// Canonical envelope shape (see lib/api.js `request()`):
//   { data, meta: { state, warnings[], capabilities: { hydrating }, inventoryHydrating }, errors }
// with `meta.state ∈ loading | degraded | unavailable | non_authoritative | available`.
// Legacy payloads also carry state in `payload.state`, `meta.discoveryState`,
// or `payload.queryState.state`; those fallbacks are codified HERE so no
// caller ever re-derives them.

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

/** Unwrap `{data, meta, errors}` → data; pass through legacy flat payloads. */
export function envelopeData(payload) {
  if (payload && typeof payload === "object" && "data" in payload) return payload.data;
  return payload ?? null;
}

/** The envelope's meta block (always an object; `{}` when absent). */
export function envelopeMeta(payload) {
  return objectValue(objectValue(payload)?.meta) || {};
}

/**
 * Normalized envelope state string (lowercased). Resolution order codifies
 * every legacy location a state has ever lived in: `meta.state` is the
 * contract; `meta.discoveryState` (discovery search), `payload.state`
 * (flat legacy payloads), and `payload.queryState.state` (discovery query
 * validation) are honored as fallbacks so ONE implementation understands
 * every payload the backend still emits.
 */
export function envelopeState(payload) {
  const source = objectValue(payload);
  if (!source) return "";
  const meta = envelopeMeta(source);
  const raw =
    meta.state ??
    meta.discoveryState ??
    source.state ??
    objectValue(source.queryState)?.state ??
    "";
  return String(raw || "").trim().toLowerCase();
}

/** Deduplicated warnings from `meta.warnings` + top-level `payload.warnings`. */
export function envelopeWarnings(payload) {
  const source = objectValue(payload);
  if (!source) return [];
  const meta = envelopeMeta(source);
  const collected = [
    ...(Array.isArray(meta.warnings) ? meta.warnings : []),
    ...(Array.isArray(source.warnings) ? source.warnings : []),
  ]
    .map((warning) => String(warning || "").trim())
    .filter(Boolean);
  return [...new Set(collected)];
}

/**
 * THE hydration predicate (single source of truth). An envelope is hydrating
 * when ANY of the signals the backend uses to say "still building" is set:
 *   - state loading/hydrating (any legacy location, see envelopeState),
 *   - `meta.capabilities.hydrating === true`,
 *   - `meta.inventoryHydrating === true` (discovery inventory warm-up),
 *   - `payload.hydrating === true` (asset-detail flat flag).
 * Deliberately a superset union of every predicate it replaces: a payload any
 * legacy copy considered hydrating is hydrating here too.
 */
export function envelopeHydrating(payload) {
  const source = objectValue(payload);
  if (!source) return false;
  const state = envelopeState(source);
  if (state === "loading" || state === "hydrating") return true;
  const meta = envelopeMeta(source);
  if (objectValue(meta.capabilities)?.hydrating === true) return true;
  if (meta.inventoryHydrating === true) return true;
  if (source.hydrating === true) return true;
  return false;
}

/**
 * Explicitly-marked non-authoritative payloads → "unavailable".
 *
 * Only EXPLICIT markers count here (state non_authoritative/prototype_mock,
 * `nonAuthoritative: true`, mock/prototype sources). `authoritative: false`
 * alone is deliberately NOT enough: trusted degraded live envelopes (e.g.
 * workspace-scoped Databricks lineage) carry authoritative:false yet must
 * render as provisional data, not be blanked — that nuance lives in
 * lib/nonAuthoritativeEvidence.js. Callers that ran the deep heuristic pass
 * its verdict via `envelopeStatus(..., { nonAuthoritative: true })`.
 */
export function envelopeNonAuthoritative(payload) {
  const source = objectValue(payload);
  if (!source) return false;
  const state = envelopeState(source);
  if (state === "non_authoritative" || state === "prototype_mock") return true;
  const meta = envelopeMeta(source);
  if (source.nonAuthoritative === true || meta.nonAuthoritative === true) return true;
  const sourceKind = String(meta.source || source.source || "").trim().toLowerCase();
  if (sourceKind === "local-prototype-mock" || sourceKind === "mock" || sourceKind === "fixture") {
    return true;
  }
  return false;
}

/**
 * The single envelope → UI status resolution.
 *
 * @param {any} payload  the raw envelope payload (or null before first response)
 * @param {{ hasSeed?: boolean, refreshError?: string | Error | boolean, nonAuthoritative?: boolean }} [context]
 *   - hasSeed: seed/placeholder data is renderable → a missing payload is
 *     "hydrating", never a blank "loading" flash (the hydration-zero bug class).
 *   - refreshError: a refetch failed while data is on screen → "degraded",
 *     never wipe (the pattern App.jsx hand-rolled for governance).
 *   - nonAuthoritative: verdict of the deep lib/nonAuthoritativeEvidence.js
 *     heuristic when the caller ran it.
 * @returns {"loading"|"hydrating"|"available"|"degraded"|"unavailable"}
 */
export function envelopeStatus(payload, context = {}) {
  const hasSeed = context.hasSeed === true;
  const refreshError = Boolean(context.refreshError);
  const source = objectValue(payload);

  // No envelope at all: seeds render immediately as "hydrating" so consumers
  // never flash an empty loading shell over renderable seed data.
  if (!source) return hasSeed ? "hydrating" : "loading";

  // Non-authoritative data must never be presented as real: unavailable.
  if (context.nonAuthoritative === true || envelopeNonAuthoritative(source)) {
    return "unavailable";
  }

  const state = envelopeState(source);
  if (state === "unavailable" || state === "error") return "unavailable";

  // Hydration outranks degradation: the server is still building, keep the
  // shimmer/poll semantics rather than a terminal degraded banner.
  if (envelopeHydrating(source)) return "hydrating";

  // Refresh-failure-over-data: the payload on screen is stale but real.
  if (refreshError) return "degraded";
  if (state === "degraded") return "degraded";

  return "available";
}

export default envelopeStatus;
