const MARKER_KEYS = new Set([
  "state",
  "status",
  "source",
  "sourcekind",
  "source_kind",
  "sourcetable",
  "source_table",
  "inventorysource",
  "inventory_source",
  "datasource",
  "data_source",
  "provider",
  "providername",
  "provider_name",
  "evidencekind",
  "evidence_kind",
  "kind",
  "bootstate",
  "boot_state",
  "authoritative",
  "is_authoritative",
  "nonauthoritative",
  "non_authoritative",
  "liveevidence",
  "live_evidence",
  "liveproof",
  "live_proof",
  "livedatabricksevidence",
  "live_databricks_evidence",
  "livedatabricksproof",
  "live_databricks_proof",
  "databricksevidence",
  "databricks_evidence",
  "visibilityscope",
  "visibility_scope",
  "lineageprofile",
  "lineage_profile",
  "mockapi",
  "mock_api",
]);

const WARNING_KEYS = new Set([
  "warning",
  "warnings",
  "message",
  "messages",
  "notice",
  "notices",
  "reason",
  "reasons",
]);

const AUTHORITY_KEYS = new Set([
  "authoritative",
  "is_authoritative",
  "liveevidence",
  "live_evidence",
  "liveproof",
  "live_proof",
  "livedatabricksevidence",
  "live_databricks_evidence",
  "livedatabricksproof",
  "live_databricks_proof",
  "databricksevidence",
  "databricks_evidence",
]);

const STATE_KEYS = new Set([
  "state",
  "status",
  "bootstate",
  "boot_state",
]);

const DEGRADED_LIVE_STATES = new Set([
  "degraded",
  "hydrating",
  "initializing",
  "loading",
  "pending",
  "unavailable",
  "unknown",
  "error",
  "limited",
  "attention_required",
]);

const AUTHORITATIVE_FALSE_CONTENT_KEYS = new Set([
  "assets",
  "assetindex",
  "asset_index",
  "defaultresults",
  "default_results",
  "results",
  "facets",
  "estate",
  "kpis",
  "metrics",
  "topdomains",
  "top_domains",
  "recentevents",
  "recent_events",
  "recentassets",
  "recent_assets",
  "events",
  "recommendations",
  "evidence",
  "graph",
  "graphs",
  "nodes",
  "edges",
  "workflow",
  "workflows",
  "tasks",
  "requests",
  "changerequests",
  "change_requests",
  "audit",
  "auditevents",
  "audit_events",
  "cdes",
  "criticaldataelements",
  "critical_data_elements",
  "qualityruns",
  "quality_runs",
  "lineage",
  "impactanalysis",
  "impact_analysis",
  "columnlineage",
  "column_lineage",
  "terms",
  "glossaryterms",
  "glossary_terms",
  "classifications",
  "classificationterms",
  "classification_terms",
  "domains",
  "dataproducts",
  "data_products",
  "dataproductmembers",
  "data_product_members",
  "columngroups",
  "column_groups",
]);

function normalizedKey(value) {
  return String(value || "").trim().toLowerCase().replace(/[\s.-]+/g, "_");
}

function pushScalar(markers, key, value) {
  const text = String(value ?? "").trim();
  if (!text) return;
  markers.push(key ? `${normalizedKey(key)}:${text}` : text);
}

function markerKeyAndValue(marker) {
  const text = String(marker || "").trim();
  const separator = text.indexOf(":");
  if (separator < 0) return { key: "", value: text };
  return {
    key: normalizedKey(text.slice(0, separator)),
    value: text.slice(separator + 1).trim(),
  };
}

function truthyMarkerValue(value) {
  const normalized = normalizedKey(value);
  return normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "enabled";
}

function falseyMarkerValue(value) {
  const normalized = normalizedKey(value);
  return normalized === "false" || normalized === "0" || normalized === "no" || normalized === "disabled";
}

function warningRejects(value) {
  const lower = String(value || "").toLowerCase();
  return (
    lower.includes("not live databricks evidence") ||
    lower.includes("not live proof") ||
    lower.includes("non-authoritative") ||
    lower.includes("non_authoritative") ||
    lower.includes("prototype") ||
    lower.includes("mock") ||
    lower.includes("fixture")
  );
}

function strongEvidenceRejects(value) {
  const normalized = normalizedKey(value);
  return (
    normalized.includes("non_authoritative") ||
    normalized.includes("local_evidence") ||
    normalized.includes("prototype") ||
    normalized.includes("fixture") ||
    normalized.includes("mock")
  );
}

function sourceRejects(value) {
  const normalized = normalizedKey(value);
  return (
    normalized === "mock" ||
    normalized === "fixture" ||
    normalized === "prototype" ||
    normalized === "seed" ||
    normalized === "validation_seed" ||
    normalized.includes("validation_seed") ||
    normalized.includes("home_northstar_seed") ||
    normalized.includes("home_evidence_plane") ||
    normalized.includes("ax_home_seed") ||
    normalized.includes("ax_taxonomy_seed") ||
    normalized.includes("seed_source") ||
    normalized.includes("prototype_mock") ||
    normalized.includes("local_prototype") ||
    normalized.includes("local_evidence") ||
    normalized.includes("mock_capture") ||
    normalized.includes("mock_api") ||
    normalized.includes("non_authoritative")
  );
}

function trustedLiveSource(value) {
  const normalized = normalizedKey(value);
  return (
    normalized === "live" ||
    normalized.includes("unity_catalog") ||
    normalized.includes("databricks") ||
    normalized.includes("governance_store") ||
    normalized.includes("metadata_audit_log") ||
    normalized.includes("runtime_diagnostics") ||
    normalized.includes("runtime_shell") ||
    normalized.includes("query_history") ||
    normalized.includes("capability_probe") ||
    normalized.includes("capability_gap") ||
    normalized.includes("contract_gap") ||
    normalized.includes("contract_default")
  );
}

function trustedDegradedLiveEnvelope(parsedMarkers) {
  const hasTrustedSource = parsedMarkers.some(({ key, value }) => {
    if (!key) return false;
    if (
      key === "source" ||
      key === "source_table" ||
      key === "sourcetable" ||
      key === "inventorysource" ||
      key === "inventory_source" ||
      key === "datasource" ||
      key === "data_source" ||
      key === "provider" ||
      key === "provider_name" ||
      key === "providername"
    ) {
      return trustedLiveSource(value);
    }
    return false;
  });
  if (!hasTrustedSource) return false;
  return parsedMarkers.some(({ key, value }) => (
    STATE_KEYS.has(key) && DEGRADED_LIVE_STATES.has(normalizedKey(value))
  ));
}

function trustedWorkspaceScopedLiveEnvelope(parsedMarkers) {
  const hasTrustedSource = parsedMarkers.some(({ key, value }) => {
    if (!key) return false;
    return (
      key === "source" ||
      key === "source_table" ||
      key === "sourcetable" ||
      key === "inventorysource" ||
      key === "inventory_source" ||
      key === "datasource" ||
      key === "data_source"
    ) && trustedLiveSource(value);
  });
  if (!hasTrustedSource) return false;
  return parsedMarkers.some(({ key, value }) => {
    if (key !== "visibilityscope" && key !== "visibility_scope") return false;
    const normalized = normalizedKey(value);
    return normalized === "workspace_app_principal" || normalized === "app_principal_only";
  });
}

function initialLineageShell(parsedMarkers) {
  const hasLineageSource = parsedMarkers.some(({ key, value }) => (
    key === "source" && normalizedKey(value).includes("unity_catalog_lineage")
  ));
  const hasInitialScope = parsedMarkers.some(({ key, value }) => (
    (key === "visibilityscope" || key === "visibility_scope") &&
    normalizedKey(value) === "initial_route_shell"
  ));
  const hasInitialProfile = parsedMarkers.some(({ key, value }) => (
    (key === "lineageprofile" || key === "lineage_profile") &&
    normalizedKey(value) === "initial"
  ));
  const hasLoadingState = parsedMarkers.some(({ key, value }) => (
    STATE_KEYS.has(key) && normalizedKey(value) === "loading"
  ));
  return hasLineageSource && hasInitialScope && hasInitialProfile && hasLoadingState;
}

function hydratingLiveLineageShell(parsedMarkers) {
  // The live /api/lineage endpoint emits a trusted-but-hydrating envelope on
  // cold cache: source=unity-catalog-lineage, authoritative=false, state=loading
  // (or capabilities.visibilityScope=full-lineage-hydrating), carrying the focus
  // node while upstream/downstream edges are still being fetched. This is a real
  // Databricks degraded envelope, not mock evidence — per IMPLEMENTATION_STATUS
  // it must render as a hydrating state rather than being rejected (which made
  // the canvas falsely claim "No lineage edges returned" during warm-up). The
  // initialLineageShell whitelist only covered the initial_route_shell scope;
  // this covers the actual full-profile hydrating markers the API emits.
  const hasLineageSource = parsedMarkers.some(({ key, value }) => (
    key === "source" && normalizedKey(value).includes("unity_catalog_lineage")
  ));
  if (!hasLineageSource) return false;
  const hasLoadingState = parsedMarkers.some(({ key, value }) => (
    STATE_KEYS.has(key) && normalizedKey(value) === "loading"
  ));
  const hasHydratingScope = parsedMarkers.some(({ key, value }) => (
    (key === "visibilityscope" || key === "visibility_scope") &&
    normalizedKey(value).includes("hydrating")
  ));
  const hasInitialProfile = parsedMarkers.some(({ key, value }) => (
    (key === "lineageprofile" || key === "lineage_profile") &&
    normalizedKey(value) === "initial"
  ));
  return hasLoadingState || hasHydratingScope || hasInitialProfile;
}

function hasPopulatedAuthoritativeFalseContent(value, key = "") {
  if (value == null) return false;
  const normalized = normalizedKey(key);
  const keyIsContent = AUTHORITATIVE_FALSE_CONTENT_KEYS.has(normalized);
  if (keyIsContent) return hasRenderableContent(value);
  if (Array.isArray(value)) {
    return value.some((item) => hasPopulatedAuthoritativeFalseContent(item, key));
  }
  if (typeof value !== "object") return false;
  return Object.entries(value).some(([entryKey, entryValue]) =>
    hasPopulatedAuthoritativeFalseContent(entryValue, entryKey),
  );
}

function hasRenderableContent(value) {
  if (value == null) return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") {
    return Object.entries(value).some(([key, entryValue]) => {
      const normalized = normalizedKey(key);
      if (normalized === "meta" || normalized === "provenance" || normalized.endsWith("warnings")) {
        return false;
      }
      return hasRenderableContent(entryValue);
    });
  }
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return value;
  return false;
}

function collectMarkers(value, key = "", inherited = false, markers = []) {
  if (value == null) return markers;
  const normalized = normalizedKey(key);
  const inspectHere =
    inherited ||
    !key ||
    MARKER_KEYS.has(normalized) ||
    WARNING_KEYS.has(normalized) ||
    normalized.endsWith("warning") ||
    normalized.endsWith("warnings");

  if (typeof value !== "object") {
    if (inspectHere) pushScalar(markers, key, value);
    return markers;
  }

  if (Array.isArray(value)) {
    value.forEach((item) => collectMarkers(item, key, inspectHere, markers));
    return markers;
  }

  Object.entries(value).forEach(([entryKey, entryValue]) => {
    const entryNormalized = normalizedKey(entryKey);
    const forceChild =
      (inspectHere && (MARKER_KEYS.has(normalized) || WARNING_KEYS.has(normalized))) ||
      WARNING_KEYS.has(entryNormalized) ||
      entryNormalized.endsWith("warning") ||
      entryNormalized.endsWith("warnings");
    collectMarkers(entryValue, entryKey, forceChild, markers);
  });
  return markers;
}

export function nonAuthoritativeMarkerValues(...sources) {
  return sources.flatMap((source) => collectMarkers(source));
}

/** @param {Record<string, any>} [value] */
export function evidenceEnvelope(value = {}) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return {
    authoritative: value.authoritative,
    evidenceKind: value.evidenceKind,
    liveDatabricksEvidence: value.liveDatabricksEvidence,
    liveDatabricksProof: value.liveDatabricksProof,
    meta: value.meta,
    mockApi: value.mockApi,
    nonAuthoritative: value.nonAuthoritative,
    provenance: value.provenance,
    source: value.source,
    state: value.state,
    status: value.status,
    warnings: value.warnings,
  };
}

export function isNonAuthoritativeEvidenceEnvelope(value = {}) {
  return isNonAuthoritativeMockEvidence(evidenceEnvelope(value));
}

/** @param {Record<string, any>} [row] */
function rowIdentifierRejects(row = {}) {
  if (!row || typeof row !== "object" || Array.isArray(row)) return false;
  const text = [
    row.id,
    row.requestId,
    row.evidenceId,
    row.source,
    row.evidenceSource,
    row.meta?.source,
    row.provenance?.source,
  ].map((value) => String(value || "")).join(" ").toLowerCase();
  return /validation[_\s-]*seed|validation sample|home[_\s-]*northstar[_\s-]*seed|home[_\s-]*evidence[_\s-]*plane|ax[_\s-]*home[_\s-]*seed|gov[_\s-]*home[_\s-]*evidence/.test(text);
}

export function filterNonAuthoritativeRows(rows = []) {
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => (
    !rowIdentifierRejects(row) &&
    !isNonAuthoritativeMockEvidence(row, row?.meta, row?.provenance, row?.warnings)
  ));
}

export function isNonAuthoritativeMockEvidence(...sources) {
  const parsedMarkers = nonAuthoritativeMarkerValues(...sources).map(markerKeyAndValue);
  const hasAuthorityFalse = parsedMarkers.some(({ key, value }) =>
    AUTHORITY_KEYS.has(key) && falseyMarkerValue(value),
  );
  const hasTrustedDegradedLiveEnvelope = trustedDegradedLiveEnvelope(parsedMarkers);
  const hasPopulatedRowsWithoutAuthority = sources.some((source) =>
    hasPopulatedAuthoritativeFalseContent(source),
  );
  const hasRejectingMarker = parsedMarkers.some(({ key, value }) => {
    const normalizedValue = normalizedKey(value);
    if (!key) return warningRejects(value);
    if (key === "mockapi" || key === "mock_api") return truthyMarkerValue(value);
    if (key === "nonauthoritative" || key === "non_authoritative") return truthyMarkerValue(value);
    if (AUTHORITY_KEYS.has(key) && falseyMarkerValue(value)) return false;
    if (
      WARNING_KEYS.has(key) ||
      key.endsWith("warning") ||
      key.endsWith("warnings")
    ) {
      return warningRejects(value);
    }
    if (key === "source" || key === "source_table" || key === "sourcetable") {
      return sourceRejects(value);
    }
    if (normalizedValue.includes("not_live_databricks_evidence")) return true;
    return strongEvidenceRejects(value);
  });
  if (hasRejectingMarker) return true;
  if (initialLineageShell(parsedMarkers)) return false;
  if (hydratingLiveLineageShell(parsedMarkers)) return false;
  if (trustedWorkspaceScopedLiveEnvelope(parsedMarkers)) return false;
  // A trusted live source that is still WARMING (meta.state loading) is never
  // mock evidence — classifying it as "sample data" told executives the
  // metadata service returned fakes during every warehouse warm-up
  // (C1/C2 verifier BLOCK). Loading envelopes render as loading, full stop.
  const hasLoadingState = parsedMarkers.some(
    ({ key, value }) => STATE_KEYS.has(key) && normalizedKey(value) === "loading",
  );
  if (hasLoadingState && hasTrustedDegradedLiveEnvelope) return false;
  if (hasAuthorityFalse && hasTrustedDegradedLiveEnvelope && hasPopulatedRowsWithoutAuthority) return true;
  return hasAuthorityFalse && !hasTrustedDegradedLiveEnvelope;
}
