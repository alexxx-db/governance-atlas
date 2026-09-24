import {
  filterNonAuthoritativeRows,
  isNonAuthoritativeEvidenceEnvelope,
  isNonAuthoritativeMockEvidence,
} from "./nonAuthoritativeEvidence";

function bootstrapConfig() {
  if (typeof window === "undefined") return null;
  return window.__GOVAT_BOOTSTRAP__ || null;
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeMetadataEditor(config) {
  if (!config || typeof config !== "object" || Array.isArray(config)) return null;
  return {
    ...config,
    fields: arrayValue(config.fields),
  };
}

function normalizeTagEntries(rawTags) {
  if (Array.isArray(rawTags)) {
    return rawTags
      .map((entry) => {
        if (typeof entry === "string") {
          const label = entry.trim();
          return label ? { name: label, value: "", label } : null;
        }
        const tag = objectValue(entry);
        const name = String(tag.name || tag.key || "").trim();
        const value = String(tag.value || "").trim();
        const label = value ? `${name}=${value}` : name;
        return name ? { name, value, label } : null;
      })
      .filter(Boolean);
  }

  const tagMap = objectValue(rawTags);
  return Object.entries(tagMap)
    .map(([name, value]) => {
      const normalizedName = String(name || "").trim();
      const normalizedValue = String(value || "").trim();
      if (!normalizedName) return null;
      return {
        name: normalizedName,
        value: normalizedValue,
        label: normalizedValue ? `${normalizedName}=${normalizedValue}` : normalizedName,
      };
    })
    .filter(Boolean);
}

function normalizeAssetRecord(asset) {
  if (!asset || typeof asset !== "object" || Array.isArray(asset)) return {};
  if (isNonAuthoritativeEvidenceEnvelope(asset)) return {};
  const operationalContext = objectValue(asset.operationalContext);
  const tagEntries = normalizeTagEntries(asset.tagEntries || asset.tags);
  const tagMap = Object.fromEntries(
    tagEntries.map((entry) => [entry.name, entry.value]),
  );
  const tagLabels = arrayValue(asset.tagLabels)
    .map((label) => String(label || "").trim())
    .filter(Boolean);
  return {
    ...asset,
    owners: arrayValue(asset.owners),
    glossaryTerms: arrayValue(asset.glossaryTerms),
    glossaryLinks: arrayValue(asset.glossaryLinks),
    glossaryTerm: String(asset.glossaryTerm || "").trim(),
    tags: tagLabels.length ? tagLabels : tagEntries.map((entry) => entry.label),
    tagEntries,
    tagMap,
    tagLabels: tagLabels.length ? tagLabels : tagEntries.map((entry) => entry.label),
    relatedAssets: arrayValue(asset.relatedAssets),
    preview: arrayValue(asset.preview),
    columns: arrayValue(asset.columns),
    ownerAssignments: filterNonAuthoritativeRows(asset.ownerAssignments),
    activity: filterNonAuthoritativeRows(asset.activity),
    metadataAudit: filterNonAuthoritativeRows(asset.metadataAudit),
    tableProperties: arrayValue(asset.tableProperties),
    customProperties: arrayValue(asset.customProperties || asset.tableProperties),
    constraints: arrayValue(asset.constraints),
    queries: arrayValue(asset.queries),
    operationalContext: {
      ...operationalContext,
      producers: arrayValue(operationalContext.producers),
      consumers: arrayValue(operationalContext.consumers),
    },
    profiler: objectValue(asset.profiler),
    metadataEditor: normalizeMetadataEditor(asset.metadataEditor),
    loadedSections: arrayValue(asset.loadedSections),
    deferredSections: arrayValue(asset.deferredSections),
  };
}

function normalizeGlossaryReviewer(entry, index = 0) {
  if (typeof entry === "string") {
    const email = entry.trim();
    return {
      id: email || `reviewer-${index}`,
      email,
      role: "Reviewer",
      state: "active",
      reviewedAt: "",
      note: "",
    };
  }

  const reviewer = objectValue(entry);
  const email = String(
    reviewer.email ||
      reviewer.ownerEmail ||
      reviewer.reviewerEmail ||
      reviewer.name ||
      reviewer.reviewedBy ||
      "",
  ).trim();
  const role = String(reviewer.role || reviewer.reviewerRole || "Reviewer").trim() || "Reviewer";
  const state = String(reviewer.state || reviewer.status || "active").trim() || "active";
  return {
    id: reviewer.id || email || `reviewer-${index}`,
    email,
    role,
    state,
    reviewedAt: String(reviewer.reviewedAt || reviewer.updatedAt || "").trim(),
    note: String(reviewer.note || reviewer.reviewNote || "").trim(),
  };
}

function normalizeGlossaryHistoryEntry(entry, index = 0) {
  if (typeof entry === "string") {
    const text = entry.trim();
    return {
      id: `history-${index}`,
      version: `v${index + 1}`,
      title: text,
      changedAt: "",
      changedBy: "",
      status: "",
      note: text,
    };
  }

  const history = objectValue(entry);
  const version = String(history.version || history.revision || history.label || "").trim();
  const title = String(history.title || history.name || history.action || "Term update").trim();
  return {
    id: history.id || history.termVersionId || history.requestId || `history-${index}`,
    version: version || `v${index + 1}`,
    title,
    changedAt: String(history.changedAt || history.createdAt || history.updatedAt || "").trim(),
    changedBy: String(history.changedBy || history.createdBy || history.updatedBy || history.reviewedBy || "").trim(),
    status: String(history.status || history.state || "").trim(),
    note: String(history.note || history.detail || history.reviewNote || history.description || "").trim(),
  };
}

function normalizeGlossaryRecord(item) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return {};
  const reviewerRoster = arrayValue(item.reviewerRoster || item.reviewerAssignments || item.reviewers).map(
    (entry, index) => normalizeGlossaryReviewer(entry, index),
  );
  const reviewerEmails = reviewerRoster
    .map((entry) => String(entry.email || "").trim())
    .filter(Boolean);
  const historyEntries = arrayValue(
    item.termHistory || item.versionHistory || item.history || item.recentRequests,
  ).map((entry, index) => normalizeGlossaryHistoryEntry(entry, index));

  return {
    ...item,
    reviewers: reviewerEmails,
    reviewerRoster,
    termHistory: historyEntries,
    versionHistory: historyEntries,
    currentVersion:
      String(item.currentVersion || item.version || historyEntries[0]?.version || "").trim(),
    reviewState:
      String(item.reviewState || item.status || historyEntries[0]?.status || "Draft").trim() || "Draft",
  };
}

function normalizeGlossaryTermPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const term = objectValue(payload.term || payload.glossaryTerm || payload.item);
  if (!Object.keys(term).length) return normalizeGlossaryRecord(payload);
  return normalizeGlossaryRecord(term);
}

function normalizeInboxItem(item, index = 0) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return {};
  return {
    notificationId: String(item.notificationId || item.id || `notification-${index}`).trim(),
    eventType: String(item.eventType || "").trim(),
    title: String(item.title || "").trim(),
    detail: String(item.detail || "").trim(),
    assetFqn: String(item.assetFqn || "").trim(),
    assetLabel: String(item.assetLabel || item.assetFqn || "").trim(),
    createdAt: String(item.createdAt || "").trim(),
    createdBy: String(item.createdBy || "").trim(),
    status: String(item.status || "").trim(),
    inboxState: String(item.inboxState || "").trim().toLowerCase(),
  };
}

function normalizeInboxRecord(inbox) {
  if (!inbox || typeof inbox !== "object" || Array.isArray(inbox)) return null;
  return {
    state: String(inbox.state || "").trim(),
    message: String(inbox.message || "").trim(),
    unreadCount: Number.isFinite(Number(inbox.unreadCount))
      ? Math.max(0, Math.trunc(Number(inbox.unreadCount)))
      : 0,
    stewardshipCount: Number.isFinite(Number(inbox.stewardshipCount))
      ? Math.max(0, Math.trunc(Number(inbox.stewardshipCount)))
      : null,
    items: arrayValue(inbox.items).map((item, index) => normalizeInboxItem(item, index)),
  };
}

export function normalizeGovernancePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const provenance = objectValue(payload.provenance);
  const queue = objectValue(payload.queue);
  return {
    ...payload,
    metrics: arrayValue(payload.metrics),
    backlog: arrayValue(payload.backlog),
    activity: arrayValue(payload.activity),
    inbox: normalizeInboxRecord(payload.inbox),
    queue: {
      ...queue,
      laneCounts: objectValue(queue.laneCounts),
    },
    glossary: arrayValue(payload.glossary).map((item) => normalizeGlossaryRecord(item)),
    authoritative: payload.authoritative === true,
    provenance: {
      ...provenance,
      warnings: arrayValue(provenance.warnings),
    },
  };
}

function normalizeAssetIndex(assetIndex) {
  return Object.fromEntries(
    Object.entries(objectValue(assetIndex)).map(([assetFqn, asset]) => [assetFqn, normalizeAssetRecord(asset)]),
  );
}

function normalizeBootstrapContract(contract) {
  const normalized = objectValue(contract);
  return {
    ...normalized,
    warnings: arrayValue(normalized.warnings),
  };
}

function normalizeBootstrapPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const discovery = objectValue(payload.discovery);
  const governance = normalizeGovernancePayload(objectValue(payload.governance));
  return {
    ...payload,
    assets: arrayValue(payload.assets).map((asset) => normalizeAssetRecord(asset)),
    assetIndex: normalizeAssetIndex(payload.assetIndex),
    graphs: objectValue(payload.graphs),
    discovery: {
      ...discovery,
      catalogs: arrayValue(discovery.catalogs),
      domains: arrayValue(discovery.domains),
      tiers: arrayValue(discovery.tiers),
      certifications: arrayValue(discovery.certifications),
      sensitivities: arrayValue(discovery.sensitivities),
      businessCriticalities: arrayValue(discovery.businessCriticalities),
      views: arrayValue(discovery.views),
      sortOptions: arrayValue(discovery.sortOptions),
      assetTypes: arrayValue(discovery.assetTypes),
      summary: objectValue(discovery.summary),
    },
    governance,
    shell: objectValue(payload.shell),
    identity: objectValue(payload.identity),
    routeHints: objectValue(payload.routeHints),
    featureFlags: arrayValue(payload.featureFlags),
    bootstrapContract: normalizeBootstrapContract(payload.bootstrapContract),
    apiContract: objectValue(payload.apiContract),
    help: arrayValue(payload.help),
  };
}

function normalizeRuntimeStatusPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const diagnostics = objectValue(payload.diagnostics);
  const setupSummary = objectValue(diagnostics.setupSummary);
  const auth = objectValue(diagnostics.auth);
  return {
    ...payload,
    runtime: objectValue(payload.runtime),
    store: objectValue(payload.store),
    capabilities: objectValue(payload.capabilities),
    config: objectValue(payload.config),
    identity: objectValue(payload.identity),
    diagnostics: {
      ...diagnostics,
      setupSummary,
      auth,
      setupChecks: arrayValue(diagnostics.setupChecks),
      featureFlags: arrayValue(diagnostics.featureFlags),
    },
  };
}

function numberOrNull(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeCommandCenterPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  if (isNonAuthoritativeMockEvidence(payload, payload.meta, payload.provenance, payload.warnings)) {
    return {
      estate: {},
      kpis: [],
      posture: {},
      topDomains: [],
      recentEvents: [],
      recentAssets: [],
      governance: {},
      insights: {},
      quickActions: [],
      aiPrompts: [],
      signalAvailability: {},
      authoritative: false,
      meta: {
        ...objectValue(payload.meta),
        state: "non_authoritative",
        warnings: [
          ...arrayValue(payload.warnings),
          ...arrayValue(objectValue(payload.meta).warnings),
          "Non-authoritative command-center payload rejected.",
        ],
      },
    };
  }
  const estate = objectValue(payload.estate);
  const governance = objectValue(payload.governance);
  const insights = objectValue(payload.insights);
  const meta = objectValue(payload.meta);
  return {
    ...payload,
    estate: {
      ...estate,
      visibleAssetCount: numberOrNull(estate.visibleAssetCount),
      catalogCount: numberOrNull(estate.catalogCount),
      openRequests: numberOrNull(estate.openRequests),
      coverageScore: numberOrNull(estate.coverageScore),
    },
    kpis: arrayValue(payload.kpis).map((kpi) => objectValue(kpi)),
    posture: {
      ...objectValue(payload.posture),
      byDomain: arrayValue(objectValue(payload.posture).byDomain),
      heatmap: arrayValue(objectValue(payload.posture).heatmap),
      trend: arrayValue(objectValue(payload.posture).trend),
    },
    topDomains: arrayValue(payload.topDomains),
    recentEvents: arrayValue(payload.recentEvents),
    recentAssets: arrayValue(payload.recentAssets).map((asset) => normalizeAssetRecord(asset)),
    governance: {
      ...governance,
      pendingRequests: arrayValue(governance.pendingRequests),
    },
    insights: {
      ...insights,
      tiles: objectValue(insights.tiles),
    },
    quickActions: arrayValue(payload.quickActions),
    aiPrompts: arrayValue(payload.aiPrompts),
    signalAvailability: objectValue(payload.signalAvailability),
    meta: {
      ...meta,
      warnings: arrayValue(meta.warnings),
    },
  };
}

function normalizeDiscoveryPayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  if (isNonAuthoritativeMockEvidence(payload, payload.meta, payload.queryState, payload.warnings)) {
    return {
      ...payload,
      assets: [],
      count: 0,
      facets: {},
      authoritative: false,
      queryState: {
        state: "unavailable",
        message: "Non-authoritative discovery payload rejected.",
        syntaxHint: "",
        supportedFields: [],
        clauseChips: [],
      },
      meta: {
        ...objectValue(payload.meta),
        state: "non_authoritative",
        warnings: [
          ...arrayValue(payload.warnings),
          ...arrayValue(objectValue(payload.meta).warnings),
          "Non-authoritative discovery payload rejected.",
        ],
      },
    };
  }
  const queryState = objectValue(payload.queryState);
  return {
    ...payload,
    assets: arrayValue(payload.assets).map((asset) => normalizeAssetRecord(asset)),
    facets: objectValue(payload.facets),
    queryState: {
      ...queryState,
      state: String(queryState.state || "").trim().toLowerCase(),
      message: String(queryState.message || "").trim(),
      syntaxHint: String(queryState.syntaxHint || "").trim(),
      supportedFields: arrayValue(queryState.supportedFields)
        .map((field) => String(field || "").trim())
        .filter(Boolean),
      clauseChips: arrayValue(queryState.clauseChips)
        .map((chip) => {
          const normalizedChip = objectValue(chip);
          const label = String(
            normalizedChip.label || normalizedChip.expression || "",
          ).trim();
          if (!label) return null;
          return {
            label,
            expression: String(normalizedChip.expression || label).trim(),
            nextQuery: String(normalizedChip.nextQuery || "").trim(),
            removable: normalizedChip.removable !== false,
          };
        })
        .filter(Boolean),
    },
  };
}

function textValue(value) {
  return String(value || "").trim();
}

function payloadRequestId(payload) {
  const body = objectValue(payload);
  return textValue(
    body.requestId ||
      body.request_id ||
      objectValue(body.meta).requestId ||
      objectValue(body.meta).request_id,
  );
}

export function formatApiError(error, fallback = "Request failed.") {
  const baseMessage = textValue(error?.detailMessage || error?.message) || fallback;
  const requestId = textValue(
    error?.httpRequestId ||
      error?.meta?.httpRequestId ||
      payloadRequestId(error?.payload),
  );
  const clientRequestId = textValue(error?.clientRequestId || error?.meta?.clientRequestId);
  const details = [];
  if (requestId) details.push(`Request ID: ${requestId}`);
  if (clientRequestId && clientRequestId !== requestId) {
    details.push(`Client request ID: ${clientRequestId}`);
  }
  return details.length ? `${baseMessage} (${details.join("; ")})` : baseMessage;
}

class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} status
   * @param {unknown} payload
   * @param {{ httpRequestId?: string, clientRequestId?: string, buildId?: string, clientDurationMs?: number }} meta
   */
  constructor(message, status, payload, meta = {}) {
    const enrichedMeta = /** @type {{ httpRequestId?: string, clientRequestId?: string, buildId?: string, clientDurationMs?: number }} */ ({
      ...meta,
      httpRequestId: meta.httpRequestId || payloadRequestId(payload),
    });
    const displayMessage = formatApiError(
      {
        message,
        payload,
        meta: enrichedMeta,
        httpRequestId: enrichedMeta.httpRequestId,
        clientRequestId: enrichedMeta.clientRequestId,
      },
      message,
    );
    super(displayMessage);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.meta = enrichedMeta;
    this.detailMessage = message;
    this.httpRequestId = enrichedMeta.httpRequestId || "";
    this.clientRequestId = enrichedMeta.clientRequestId || "";
    this.buildId = enrichedMeta.buildId || "";
    this.durationMs = enrichedMeta.clientDurationMs || 0;
  }
}

const REQUEST_ID_HEADER = "X-Request-ID";
const CLIENT_REQUEST_ID_HEADER = "X-GOVAT-Client-Request-ID";
const BUILD_ID_HEADER = "X-GOVAT-Build-ID";
const DURATION_HEADER = "X-GOVAT-Request-Duration-Ms";

function nowMs() {
  if (typeof performance !== "undefined" && typeof performance.now === "function") {
    return performance.now();
  }
  return Date.now();
}

function createClientRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function diagnosticsStore() {
  if (typeof window === "undefined") return null;
  const runtimeWindow = /** @type {Window & {
    __GOVAT_DIAGNOSTICS__?: {
      initialNavigation: unknown,
      lastRequest: unknown,
      requests: unknown[]
    },
    __GOVAT_NAVIGATION_DIAGNOSTICS_RECORDED__?: boolean
  }} */ (window);
  if (runtimeWindow.__GOVAT_DIAGNOSTICS__ && typeof runtimeWindow.__GOVAT_DIAGNOSTICS__ === "object") {
    return runtimeWindow.__GOVAT_DIAGNOSTICS__;
  }
  runtimeWindow.__GOVAT_DIAGNOSTICS__ = {
    initialNavigation: null,
    lastRequest: null,
    requests: [],
  };
  return runtimeWindow.__GOVAT_DIAGNOSTICS__;
}

function recordInitialNavigationTiming() {
  if (typeof window === "undefined") return;
  const runtimeWindow = /** @type {Window & {
    __GOVAT_DIAGNOSTICS__?: {
      initialNavigation: unknown,
      lastRequest: unknown,
      requests: unknown[]
    },
    __GOVAT_NAVIGATION_DIAGNOSTICS_RECORDED__?: boolean
  }} */ (window);
  if (runtimeWindow.__GOVAT_NAVIGATION_DIAGNOSTICS_RECORDED__) return;
  const store = diagnosticsStore();
  if (!store || typeof performance === "undefined" || typeof performance.getEntriesByType !== "function") {
    return;
  }
  const navigation = /** @type {PerformanceNavigationTiming | undefined} */ (
    performance.getEntriesByType("navigation")?.[0]
  );
  if (!navigation) return;
  store.initialNavigation = {
    type: navigation.type || "",
    durationMs: Math.round(Number(navigation.duration || 0) * 10) / 10,
    domInteractiveMs: Math.round(Number(navigation.domInteractive || 0) * 10) / 10,
    loadEventEndMs: Math.round(Number(navigation.loadEventEnd || 0) * 10) / 10,
    serverTiming: Array.from(navigation.serverTiming || []).map((entry) => ({
          name: entry?.name || "",
          duration: Number(entry?.duration || 0),
        })),
  };
  runtimeWindow.__GOVAT_NAVIGATION_DIAGNOSTICS_RECORDED__ = true;
}

function recordRequestDiagnostics(entry) {
  const store = diagnosticsStore();
  if (!store) return;
  store.lastRequest = entry;
  const existing = Array.isArray(store.requests) ? store.requests : [];
  store.requests = [entry, ...existing].slice(0, 25);
}

export function getRuntimeDiagnostics() {
  return diagnosticsStore() || { initialNavigation: null, lastRequest: null, requests: [] };
}

recordInitialNavigationTiming();

function apiBase() {
  return (
    import.meta.env.VITE_GOVAT_API_BASE ||
    bootstrapConfig()?.apiBase ||
    "/api"
  );
}

function currentLocationSearch(routeContext = null) {
  if (!routeContext && typeof window === "undefined") return "";
  const search = routeContext?.search || (typeof window !== "undefined" ? window.location.search || "" : "");
  const pathname = routeContext?.pathname || (typeof window !== "undefined" ? window.location.pathname || "/" : "/");
  const params = new URLSearchParams(search);
  if (routeContext?.surface) {
    params.set("surface", routeContext.surface);
    if (routeContext.surface === "discovery") {
      params.delete("asset");
      if (routeContext.discoveryQuery?.trim()) params.set("q", routeContext.discoveryQuery.trim());
      else params.delete("q");
    } else if (routeContext.asset) {
      params.set("asset", routeContext.asset);
      params.delete("q");
    } else {
      params.delete("asset");
      params.delete("q");
    }
    params.delete("module");
    const query = params.toString();
    return query ? `?${query}` : "";
  }
  const safeDecode = (value) => {
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  };
  const segments = String(pathname || "/")
    .split("/")
    .filter(Boolean);
  const [root, ...rest] = segments;
  if (root === "discovery") {
    params.set("surface", "discovery");
    params.delete("asset");
  } else if (root === "entity" && rest.length) {
    params.set("surface", "entity");
    params.set("asset", safeDecode(rest.join("/")));
  } else if (root === "lineage" && rest.length) {
    params.set("surface", "lineage");
    params.set("asset", safeDecode(rest.join("/")));
  } else if (root === "governance" || root === "glossary") {
    params.set("surface", "governance");
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function buildUrl(path) {
  if (!path) return apiBase();
  if (/^https?:\/\//.test(path)) return path;
  const base = apiBase();
  if (path.startsWith(base)) return path;
  if (path.startsWith("/")) return `${base}${path}`;
  return `${base}/${path}`;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (response.status === 204) return null;

  try {
    if (contentType.includes("application/json")) {
      return await response.json();
    }
    return await response.text();
  } catch {
    return null;
  }
}

function payloadLooksLikeHtml(payload) {
  if (typeof payload !== "string") return false;
  const sample = payload.trim().slice(0, 240).toLowerCase();
  return sample.startsWith("<!doctype html") || sample.startsWith("<html") || sample.includes("<body");
}

function friendlyHtmlErrorMessage(status, payload) {
  if (!payloadLooksLikeHtml(payload)) return "";
  if (status === 502 || status === 503 || status === 504) {
    return "The Databricks app returned a temporary gateway error while loading live metadata. Retry the action in a moment.";
  }
  return "The app returned an unexpected HTML error page instead of metadata. Retry the action or refresh the workspace.";
}

function responseErrorMessage(status, payload) {
  const htmlMessage = friendlyHtmlErrorMessage(status, payload);
  if (htmlMessage) return htmlMessage;
  if (typeof payload === "string" && payload.trim()) return payload;
  if (payload?.detail) return String(payload.detail);
  if (payload?.message) return String(payload.message);
  return `Request failed: ${status}`;
}

async function request(path, options = {}) {
  const startedAt = nowMs();
  const clientRequestId = options.clientRequestId || createClientRequestId();
  const requestUrl = buildUrl(path);
  const timeoutMs = Number.isFinite(Number(options.timeoutMs)) ? Number(options.timeoutMs) : 45_000;
  const controller = new AbortController();
  let timeoutId = null;
  let externalAbortHandler = null;
  let timedOut = false;
  if (timeoutMs > 0) {
    timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      externalAbortHandler = () => controller.abort();
      options.signal.addEventListener("abort", externalAbortHandler, { once: true });
    }
  }
  let response;
  try {
    response = await fetch(requestUrl, {
      method: options.method || "GET",
      headers: {
        Accept: "application/json",
        [CLIENT_REQUEST_ID_HEADER]: clientRequestId,
        ...(options.headers || {}),
      },
      signal: controller.signal,
      body: options.body,
    });
  } catch (error) {
    const meta = {
      path: requestUrl,
      status: 0,
      clientRequestId,
      httpRequestId: "",
      buildId: "",
      serverDurationMs: 0,
      clientDurationMs: Math.round((nowMs() - startedAt) * 10) / 10,
      receivedAt: new Date().toISOString(),
    };
    recordRequestDiagnostics(meta);
    if (timedOut) {
      throw new ApiError(
        "The metadata request timed out before Databricks returned a response. The surface remains available with stale or unavailable state.",
        0,
        { detail: "client_timeout", timeoutMs },
        meta,
      );
    }
    throw error;
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
    if (options.signal && externalAbortHandler) {
      options.signal.removeEventListener("abort", externalAbortHandler);
    }
  }
  const payload = await parseResponse(response);
  const meta = {
    path: requestUrl,
    status: response.status,
    clientRequestId,
    httpRequestId: response.headers.get(REQUEST_ID_HEADER) || payloadRequestId(payload),
    buildId: response.headers.get(BUILD_ID_HEADER) || "",
    serverDurationMs: Number(response.headers.get(DURATION_HEADER) || 0) || 0,
    clientDurationMs: Math.round((nowMs() - startedAt) * 10) / 10,
    receivedAt: new Date().toISOString(),
  };
  recordRequestDiagnostics(meta);
  if (!response.ok) {
    throw new ApiError(responseErrorMessage(response.status, payload), response.status, payload, meta);
  }
  return payload;
}

async function requestJson(path, method, body, options = {}) {
  return request(path, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: options.signal,
  });
}

function contractPath(...keys) {
  const contract = bootstrapConfig()?.apiContract || {};
  for (const key of keys) {
    const value = contract?.[key];
    if (typeof value === "string" && value) return value;
  }
  return "";
}

function assetRoute(pathTemplate, assetFqn) {
  if (!pathTemplate) return "";
  if (!assetFqn) return pathTemplate;
  const encoded = encodeURIComponent(assetFqn);
  return pathTemplate
    .replaceAll(":fqn", encoded)
    .replaceAll("{fqn}", encoded)
    .replaceAll("[fqn]", encoded);
}

function routeToken(pathTemplate, token, value) {
  if (!pathTemplate) return "";
  if (!value) return pathTemplate;
  const encoded = encodeURIComponent(value);
  return pathTemplate
    .replaceAll(`:${token}`, encoded)
    .replaceAll(`{${token}}`, encoded)
    .replaceAll(`[${token}]`, encoded);
}

function appendQueryFlag(path, key, enabled) {
  if (!enabled) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}${encodeURIComponent(key)}=1`;
}

function columnRoute(pathTemplate, assetFqn, columnName) {
  if (!pathTemplate) return "";
  const assetEncoded = encodeURIComponent(assetFqn || "");
  const columnEncoded = encodeURIComponent(columnName || "");
  return pathTemplate
    .replaceAll(":fqn", assetEncoded)
    .replaceAll("{fqn}", assetEncoded)
    .replaceAll("[fqn]", assetEncoded)
    .replaceAll(":column", columnEncoded)
    .replaceAll("{column}", columnEncoded)
    .replaceAll("[column]", columnEncoded);
}

function normalizedMethod(value, fallback = "PATCH") {
  return (value || fallback).toString().trim().toUpperCase();
}

export function fetchBootstrap(routeContext = null, options = {}) {
  const bootstrapRouteContext = routeContext
    ? {
        surface: routeContext.surface || "discovery",
        asset: routeContext.asset || "",
      }
    : null;
  const path = contractPath("bootstrap") || "/bootstrap";
  return request(`${path}${currentLocationSearch(bootstrapRouteContext)}`, options).then((payload) =>
    normalizeBootstrapPayload(payload),
  );
}

export function fetchRuntimeStatus(options = {}) {
  const path = contractPath("runtimeStatus") || "/runtime/status";
  return request(path, options).then((payload) => normalizeRuntimeStatusPayload(payload));
}

export function fetchCommandCenter(options = {}) {
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  const path = contractPath("commandCenter") || "/atlas/command-center";
  return request(`${path}${query ? `?${query}` : ""}`, {
    signal: options.signal,
  }).then((payload) => normalizeCommandCenterPayload(payload));
}

// Ground-truth roster of real account principals for owner/steward pickers.
// Steward/admin-gated server-side; a 401/403/degraded response resolves to an
// unavailable roster so callers fall back to free text rather than pretending
// the list is complete (identity-integrity: never fabricate a member).
export function fetchWorkspaceRoster(options = {}) {
  const path = contractPath("identityWorkspaceRoster") || "/api/identity/workspace-roster";
  return request(path, { signal: options.signal })
    .then((payload) => {
      const data = unwrapEnvelope(payload) || payload || {};
      const members = Array.isArray(data.members) ? data.members : [];
      return {
        available: data.available === true,
        source: String(data.source || ""),
        members: members
          .map((m) => ({
            principal: String(m?.principal || "").trim(),
            principalType: String(m?.principalType || "user"),
            accountMember: m?.accountMember !== false,
          }))
          .filter((m) => m.principal),
      };
    })
    .catch((error) => {
      // Not authorized / not reachable → unavailable, not an error surface.
      if (error?.name === "AbortError") throw error;
      return { available: false, source: "", members: [] };
    });
}

function abortableDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      // Remove the listener on the normal path too, so a long poll loop can't
      // accrete one abort listener per iteration on the shared signal.
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function fetchAtlasAiRecommendations(question = "", options = {}) {
  const path = contractPath("atlasAiRecommendations") || "/atlas-ai/recommendations";
  const body = { question: String(question || "").trim() };
  // Page-awareness: forward the surface + asset the user is viewing so the AI
  // resolves "this asset"/"this page" to a concrete entity (backend injects it
  // into the Genie prompt). Only send fields that are actually present.
  const context = options.context || {};
  const surface = String(context.surface || "").trim();
  const assetFqn = String(context.assetFqn || "").trim();
  // `scope` carries the active facet filters so the AI can resolve "here"/"this
  // page" to the actual domain/criticality the user is filtered to.
  const scope = context.scope && typeof context.scope === "object" ? context.scope : null;
  if (surface || assetFqn || scope) {
    body.context = {};
    if (surface) body.context.surface = surface;
    if (assetFqn) body.context.assetFqn = assetFqn;
    if (scope) body.context.scope = scope;
  }

  const normalize = (payload) => {
    const response = unwrapEnvelope(payload);
    if (isNonAuthoritativeMockEvidence(response, response?.recommendations, response?.warnings)) {
      return {
        recommendations: [],
        authoritative: false,
        nonAuthoritative: true,
        warning: "Atlas AI recommendations unavailable until live evidence-backed provider returns results.",
      };
    }
    return response;
  };

  const first = unwrapEnvelope(await requestJson(path, "POST", body, { signal: options.signal }));
  // Genie answers run asynchronously: the POST returns a "pending" handle
  // (conversation + message id) immediately, and we poll /atlas-ai/message for
  // the REAL pipeline stages + the final answer — so the UI shows progress
  // instead of hanging on one indefinite request. Grounded (instant) answers
  // skip this entirely. onStage(stage) is invoked as the stage changes.
  if (first?.intent === "genie-pending" && first.conversationId && first.messageId) {
    if (typeof options.onStage === "function") options.onStage(first.stage || "Working");
    const pollPath = contractPath("atlasAiMessage") || "/atlas-ai/message";
    const pollBody = { conversationId: first.conversationId, messageId: first.messageId, question: body.question };
    if (body.context) pollBody.context = body.context;
    const deadline = Date.now() + (options.timeoutMs || 150000);
    let lastStage = first.stage || "";
    while (Date.now() < deadline) {
      await abortableDelay(options.pollIntervalMs || 1200, options.signal);
      const polled = unwrapEnvelope(await requestJson(pollPath, "POST", pollBody, { signal: options.signal }));
      if (polled?.stage && polled.stage !== lastStage && typeof options.onStage === "function") {
        lastStage = polled.stage;
        options.onStage(lastStage);
      }
      if (polled?.intent === "genie-pending") continue;
      return normalize(polled); // terminal: done, unavailable, or error envelope
    }
    throw new Error("Atlas AI timed out waiting for Genie to finish. Try a narrower question.");
  }
  return normalize(first);
}

// AI autofill: draft freeform field values from context (e.g. a glossary
// definition + domain from a term name) via the generative endpoint. Returns
// { fields, model, warnings }; the caller drops fields into the form for review.
export async function fetchAiAutofill(kind, context = {}, options = {}) {
  const path = contractPath("atlasAiAutofill") || "/atlas-ai/autofill";
  const body = { kind: String(kind || "").trim() };
  if (context && typeof context === "object" && Object.keys(context).length) body.context = context;
  const response = unwrapEnvelope(await requestJson(path, "POST", body, { signal: options.signal }));
  return {
    fields: response?.fields && typeof response.fields === "object" ? response.fields : {},
    model: String(response?.model || ""),
    warnings: Array.isArray(response?.warnings) ? response.warnings : [],
  };
}

export function fetchAsset360(assetFqn, options = {}) {
  const template = contractPath("asset360") || "/atlas/assets/{asset_fqn}/360";
  return request(routeToken(assetRoute(template, assetFqn), "asset_fqn", assetFqn), {
    signal: options.signal,
  });
}

export function fetchGovernanceWorkbench(options = {}) {
  const path = contractPath("governanceWorkbench") || "/atlas/governance/workbench";
  return request(path, { signal: options.signal });
}

export function fetchGovernanceRequestDetail(requestId, options = {}) {
  const template = contractPath("governanceRequestDetail") || "/atlas/governance/requests/{request_id}";
  return request(routeToken(template, "request_id", requestId), {
    signal: options.signal,
  });
}

export function fetchInsightsDashboard(options = {}) {
  const path = contractPath("insightsDashboard") || "/atlas/insights";
  return request(path, { signal: options.signal });
}

// ── DataPact Control Center ──────────────────────────────────────────────

export function fetchDataPactStatus(options = {}) {
  return request("/datapact/status", { signal: options.signal });
}

export function fetchDataPactOverview(options = {}) {
  const query = options.refresh ? "?refresh=1" : "";
  return request(`/datapact/overview${query}`, { signal: options.signal });
}

export function fetchDataPactRun(runId, options = {}) {
  return request(`/datapact/runs/${encodeURIComponent(runId)}`, { signal: options.signal });
}

export function fetchDataPactRunLive(runId, options = {}) {
  return request(`/datapact/runs/${encodeURIComponent(runId)}/live`, { signal: options.signal });
}

export function triggerDataPactRun(jobId, body = {}, options = {}) {
  return requestJson(`/datapact/jobs/${encodeURIComponent(jobId)}/run`, "POST", body, options);
}

export function startDataPactGenie(question, options = {}) {
  return requestJson("/datapact/genie/start", "POST", { question }, options);
}

export function pollDataPactGenie(conversationId, messageId, options = {}) {
  return requestJson(
    "/datapact/genie/poll",
    "POST",
    { conversationId, messageId },
    options,
  );
}

/* ------------------------------------------------------------------ */
/* AI governance (/api/ai, DESIGN.md 9). Registered only when the       */
/* backend flag is on; the surface is hidden otherwise.                 */
/* ------------------------------------------------------------------ */

function aiQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function fetchAiSummary(options = {}) {
  return request("/ai/summary", { signal: options.signal });
}

export function fetchAiInventory(filters = {}, options = {}) {
  return request(`/ai/inventory${aiQuery(filters)}`, { signal: options.signal });
}

export function fetchAiAsset(entityId, options = {}) {
  return request(`/ai/assets/${encodeURIComponent(entityId)}`, { signal: options.signal });
}

export function fetchAiFindings(filters = {}, options = {}) {
  return request(`/ai/findings${aiQuery(filters)}`, { signal: options.signal });
}

export function patchAiFinding(findingId, body, options = {}) {
  return requestJson(`/ai/findings/${encodeURIComponent(findingId)}`, "PATCH", body, options);
}

export function confirmAiFindingMatch(findingId, body, options = {}) {
  return requestJson(`/ai/findings/${encodeURIComponent(findingId)}/confirm-match`, "POST", body, options);
}

export function fetchAiIntake(options = {}) {
  return request("/ai/intake", { signal: options.signal });
}

export function importAiIntake(csvText, mode, options = {}) {
  return requestJson(`/ai/intake/import?mode=${encodeURIComponent(mode)}`, "POST", { csvText }, options);
}

export function fetchAiRuns(options = {}) {
  return request("/ai/reconciliation/runs", { signal: options.signal });
}

export function fetchTaxonomyOverview(options = {}) {
  const path = contractPath("taxonomyOverview") || "/atlas/taxonomy/overview";
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchCdeDashboard(options = {}) {
  const path = contractPath("cdeDashboard") || "/atlas/cde";
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchCdeDetail(cdeId, options = {}) {
  const template = contractPath("cdeDetail") || "/atlas/cde/{cde_id}";
  return request(routeToken(template, "cde_id", cdeId), { signal: options.signal });
}

export function fetchAuditEvidence(options = {}) {
  const params = new URLSearchParams();
  if (options.auditId) params.set("audit_id", options.auditId);
  if (options.dateRange) params.set("date_range", options.dateRange);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  const path = contractPath("auditEvidence") || "/atlas/audit/evidence";
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchAdminControlCenter(options = {}) {
  const path = contractPath("adminControlCenter") || "/atlas/admin/control-center";
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchAdminBackgroundStatus(options = {}) {
  // The contract normally advertises the full `/api/...` path. Strip the
  // api prefix so `request()` can layer it back on via `buildUrl`.
  const contract = contractPath("adminBackgroundStatus") || "/api/admin/background/status";
  const path = contract.startsWith("/api") ? contract.slice(4) : contract;
  return request(path || "/admin/background/status", options);
}

export function fetchAdminTruthCheck(options = {}) {
  // /api/admin/truth-check is mounted directly under /api by the
  // admin router (no contract entry), so build the path manually and
  // strip the /api prefix that request() will re-add.
  const path = "/admin/truth-check";
  const params = new URLSearchParams();
  if (options.refresh) params.set("refresh", "1");
  const query = params.toString();
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

function appendList(params, key, values) {
  (values || []).forEach((value) => {
    if (!value) return;
    params.append(key, value);
  });
}

export function fetchDiscoverySearch(filters = {}, options = {}) {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.queryMode) params.set("queryMode", filters.queryMode);
  appendList(params, "views", filters.views);
  appendList(params, "types", filters.types);
  if (filters.view) params.set("view", filters.view);
  if (filters.type) params.set("type", filters.type);
  if (filters.sortBy) params.set("sortBy", filters.sortBy);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  appendList(params, "catalogs", filters.catalogs);
  appendList(params, "domains", filters.domains);
  appendList(params, "tiers", filters.tiers);
  appendList(params, "certifications", filters.certifications);
  appendList(params, "sensitivities", filters.sensitivities);
  appendList(params, "businessCriticalities", filters.businessCriticalities);
  if (filters.cdeOnly) params.set("cdeOnly", "true");
  // Round 19 OBO hardening: `refresh: true` evicts the server's per-actor
  // inventory cache before the search so the OBO client re-attempts a
  // fresh fetch. Used by the "Retry with actor scope" banner button.
  if (filters.refresh) params.set("refresh", "1");
  const query = params.toString();
  const discoveryPath = contractPath("discoverySearch") || "/discovery/search";
  return request(`${discoveryPath}${query ? `?${query}` : ""}`, options).then((payload) =>
    normalizeDiscoveryPayload(payload),
  );
}

export function fetchAssetDetail(assetFqn, options = {}) {
  const params = new URLSearchParams();
  (options.sections || []).forEach((section) => {
    if (section) params.append("sections", section);
  });
  const query = params.toString();
  return request(
    `/assets/${encodeURIComponent(assetFqn)}${query ? `?${query}` : ""}`,
    { signal: options.signal },
  ).then((payload) =>
    normalizeAssetRecord(payload),
  );
}

export function fetchCdeRegistry(options = {}) {
  const params = new URLSearchParams();
  appendList(params, "domains", options.domains);
  const query = params.toString();
  const path = contractPath("cdeRegistry") || "/cde";
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function postBulkImportDryRun(csvText, options = {}) {
  const path = contractPath("bulkImportDryRun") || "/admin/bulk-import/dry-run";
  return requestJson(path, "POST", { csvText: String(csvText || "") }, options);
}

export function postBulkImportCommit(rows, options = {}) {
  const path = contractPath("bulkImportCommit") || "/admin/bulk-import/commit";
  return requestJson(
    path,
    "POST",
    { rows: Array.isArray(rows) ? rows : [] },
    options,
  );
}

export function fetchAdminCoverage(options = {}) {
  const params = new URLSearchParams();
  appendList(params, "requiredFields", options.requiredFields);
  const query = params.toString();
  const path = contractPath("adminCoverage") || "/admin/coverage";
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchAdminBranding(options = {}) {
  const path = contractPath("adminBranding") || "/admin/branding";
  return request(path, { signal: options.signal });
}

export function updateAdminBranding(payload, options = {}) {
  const path = contractPath("adminBranding") || "/admin/branding";
  return requestJson(path, "PUT", payload || {}, options);
}

// G3 — workspace role assignment (admin only).
export function fetchAdminRoles(options = {}) {
  return request("/admin/roles", { signal: options.signal });
}

export function updateAdminRole(email, role, options = {}) {
  return requestJson("/admin/roles", "PUT", { email, role }, options);
}

// G2 — export the current selection as a visibility-redacted CSV. Returns the
// raw CSV text (the endpoint responds with text/csv under OBO auth).
export function exportAssets(assetFqns, options = {}) {
  return requestJson(
    "/export/assets",
    "POST",
    { assetFqns: Array.isArray(assetFqns) ? assetFqns : [] },
    options,
  );
}

// G10 — fetch the tamper-evident evidence pack (.zip: CSV + provenance
// manifest) as a Blob. Bypasses the JSON `request` helper because the response
// is binary; still routes through buildUrl for the /api base + OBO cookies.
export async function fetchEvidencePackBlob(assetFqns, options = {}) {
  const response = await fetch(buildUrl("/export/evidence-pack"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/zip" },
    body: JSON.stringify({ assetFqns: Array.isArray(assetFqns) ? assetFqns : [] }),
    signal: options.signal,
  });
  if (!response.ok) {
    let message = `Evidence pack export failed (${response.status}).`;
    try {
      const payload = await response.json();
      message = payload?.error?.message || payload?.detail || message;
    } catch {
      /* keep default */
    }
    throw new ApiError(message, response.status, {});
  }
  return response.blob();
}

// G8 — board-ready executive report as print-ready HTML text (POST, no body).
export function fetchBoardReportHtml(options = {}) {
  return request("/export/board-report", { method: "POST", signal: options.signal });
}

// G4 — "Controls in action": governance decisions (approvals/rejections).
export function fetchControlDecisions(options = {}) {
  const query = options.limit ? `?limit=${encodeURIComponent(options.limit)}` : "";
  return request(`/governance/control-decisions${query}`, { signal: options.signal });
}

export function fetchAdminCoverageDrilldown(options = {}) {
  const params = new URLSearchParams();
  appendList(params, "requiredFields", options.requiredFields);
  if (options.tier) params.set("tier", options.tier);
  if (options.domain) params.set("domain", options.domain);
  if (options.missingField) params.set("missingField", options.missingField);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  const path =
    contractPath("adminCoverageDrilldown") || "/admin/coverage/drilldown";
  return request(`${path}${query ? `?${query}` : ""}`, { signal: options.signal });
}

export function fetchAssetAvailability(assetFqns = [], options = {}) {
  const targets = [...new Set((assetFqns || []).filter(Boolean))];
  if (!targets.length) return Promise.resolve({ assets: {} });
  const path = contractPath("assetAvailability") || "/assets/availability";
  return requestJson(path, "POST", { assets: targets }, { signal: options.signal });
}

export function fetchAssetHeaders(assetFqns = [], options = {}) {
  const targets = [...new Set((assetFqns || []).filter(Boolean))].slice(0, 64);
  if (!targets.length) return Promise.resolve({ assets: {} });
  const path = contractPath("assetHeaders") || "/assets/headers";
  return requestJson(path, "POST", { assets: targets }, { signal: options.signal });
}

export function fetchLineage(assetFqn, options = {}) {
  const params = new URLSearchParams();
  if (options.profile) params.set("profile", String(options.profile));
  if (options.force) params.set("refresh", "1");
  const query = params.toString();
  const path = `/lineage/${encodeURIComponent(assetFqn)}${query ? `?${query}` : ""}`;
  const execute = () => request(path, { signal: options.signal });
  return execute().catch((error) => {
    if (options.signal?.aborted) {
      throw error;
    }
    if (error?.status === 502 || error?.status === 503 || error?.status === 504) {
      return new Promise((resolve, reject) => {
        const timeoutId = globalThis.setTimeout(() => {
          if (options.signal?.aborted) {
            reject(error);
            return;
          }
          execute().then(resolve).catch(reject);
        }, 650);
        const abortHandler = () => {
          globalThis.clearTimeout(timeoutId);
          reject(error);
        };
        options.signal?.addEventListener?.("abort", abortHandler, { once: true });
      });
    }
    throw error;
  });
}

export function fetchLineageRecommendations(options = {}) {
  const params = new URLSearchParams();
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return request(`/lineage/recommendations${query ? `?${query}` : ""}`, {
    signal: options.signal,
  });
}

export function fetchGovernanceSummary(options = {}) {
  const params = new URLSearchParams();
  const sections = Array.isArray(options.sections)
    ? options.sections
    : options.section
      ? [options.section]
      : [];
  sections
    .filter(Boolean)
    .forEach((section) => params.append("sections", String(section)));
  const query = params.toString();
  return request(`/governance/summary${query ? `?${query}` : ""}`, options).then((payload) => normalizeGovernancePayload(payload));
}

export function fetchGapAnalysis(options = {}) {
  const limit = Number.isFinite(Number(options.limit))
    ? Math.max(1, Math.min(500, Math.trunc(Number(options.limit))))
    : 200;
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (options.refresh) params.set("refresh", "1");
  return request(`/insights/gap-analysis?${params.toString()}`, {
    signal: options.signal,
  });
}

export function fetchGovernanceGlossary() {
  return request("/governance/glossary").then((payload) => normalizeGovernancePayload(payload));
}

export function fetchGovernanceAuditTimeline(assetFqn, options = {}) {
  const normalized = String(assetFqn || "").trim();
  if (!normalized) return Promise.resolve({ fqn: "", entries: [], total: 0 });
  return request(`/governance/audit-timeline/${encodeURIComponent(normalized)}`, {
    signal: options.signal,
  }).then((payload) => {
    if (isNonAuthoritativeMockEvidence(payload, payload?.meta, payload?.provenance, payload?.warnings)) {
      return { fqn: normalized, entries: [], total: 0, nonAuthoritative: true };
    }
    const entries = arrayValue(payload?.entries);
    if (entries.some((entry) => isNonAuthoritativeMockEvidence(entry, entry?.meta, entry?.provenance, entry?.warnings))) {
      return { fqn: normalized, entries: [], total: 0, nonAuthoritative: true };
    }
    return {
      ...objectValue(payload),
      fqn: String(payload?.fqn || normalized),
      entries,
      total: entries.length,
    };
  });
}

export function fetchGovernanceGlossaryTerm(termId, options = {}) {
  const template = contractPath("governanceGlossaryTerm") || "/governance/glossary/:id";
  return request(routeToken(template, "id", termId), { signal: options.signal }).then((payload) =>
    normalizeGlossaryTermPayload(payload),
  );
}

export function createGovernanceRequest(payload, options = {}) {
  const path = appendQueryFlag("/governance/requests", "fast", options.fast);
  return requestJson(path, "POST", payload, { signal: options.signal });
}

export function upsertGovernanceOwner(payload) {
  return requestJson("/governance/owners", "POST", payload);
}

export function upsertGovernanceGlossaryTerm(payload) {
  return requestJson("/governance/glossary", "POST", payload);
}

export function updateGovernanceRequest(requestId, payload, options = {}) {
  const template = contractPath("governanceRequest") || "/governance/requests/:id";
  const path = appendQueryFlag(routeToken(template, "id", requestId), "fast", options.fast);
  return requestJson(path, "PATCH", payload, { signal: options.signal });
}

export function updateGovernanceNotification(notificationId, payload) {
  const template = contractPath("governanceNotification") || "/governance/notifications/:id";
  return requestJson(routeToken(template, "id", notificationId), "PATCH", payload);
}

export function updateGovernanceGlossaryTerm(termId, payload) {
  const template = contractPath("governanceGlossaryTerm") || "/governance/glossary/:id";
  return requestJson(routeToken(template, "id", termId), "PATCH", payload);
}

// A9.4 Classification Recommendation Workflow --------------------------------

function normalizeClassificationRecord(record) {
  if (!record || typeof record !== "object" || Array.isArray(record)) return null;
  if (isNonAuthoritativeMockEvidence(record, record.meta, record.provenance, record.warnings, record.evidence)) {
    return null;
  }
  return {
    recommendationId: String(record.recommendationId || record.recommendation_id || "").trim(),
    assetFqn: String(record.assetFqn || record.asset_fqn || "").trim(),
    columnName: String(record.columnName || record.column_name || "").trim(),
    suggestedSensitivity: String(record.suggestedSensitivity || "").trim(),
    suggestedTier: String(record.suggestedTier || "").trim(),
    suggestedCertification: String(record.suggestedCertification || "").trim(),
    evidence: Array.isArray(record.evidence) ? record.evidence : [],
    sampleRedacted: Boolean(record.sampleRedacted),
    sampleValues: Array.isArray(record.sampleValues) ? record.sampleValues : [],
    status: String(record.status || "pending").trim().toLowerCase(),
    remediationSuggestions: Array.isArray(record.remediationSuggestions)
      ? record.remediationSuggestions
      : [],
    reviewNote: String(record.reviewNote || "").trim(),
    reviewedBy: String(record.reviewedBy || "").trim(),
    reviewedAt: String(record.reviewedAt || "").trim(),
    createdAt: String(record.createdAt || "").trim(),
    createdBy: String(record.createdBy || "").trim(),
    updatedAt: String(record.updatedAt || "").trim(),
    updatedBy: String(record.updatedBy || "").trim(),
  };
}

/**
 * @param {{ status?: string, assetFqn?: string, signal?: AbortSignal }} [options]
 */
export function fetchClassificationRecommendations({ status = "pending", assetFqn = "", signal } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (assetFqn) params.set("assetFqn", assetFqn);
  const qs = params.toString();
  const path = qs
    ? `/classification-recommendations?${qs}`
    : "/classification-recommendations";
  return request(path, { signal }).then((payload) => {
    if (isNonAuthoritativeMockEvidence(payload, payload?.meta, payload?.provenance, payload?.warnings)) {
      return { recommendations: [], count: 0, pendingCount: 0, nonAuthoritative: true };
    }
    const recs = Array.isArray(payload?.recommendations) ? payload.recommendations : [];
    if (recs.some((record) => isNonAuthoritativeMockEvidence(record, record?.meta, record?.provenance, record?.warnings, record?.evidence))) {
      return { recommendations: [], count: 0, pendingCount: 0, nonAuthoritative: true };
    }
    const recommendations = recs.map(normalizeClassificationRecord).filter(Boolean);
    return {
      recommendations,
      count: Number(payload?.count || recommendations.length || 0),
      pendingCount: Number(payload?.pendingCount || 0),
    };
  });
}

/**
 * @param {string} recommendationId
 * @param {{ signal?: AbortSignal }} [options]
 */
export function fetchClassificationRecommendation(recommendationId, { signal } = {}) {
  const normalized = String(recommendationId || "").trim();
  if (!normalized) return Promise.resolve(null);
  return request(
    `/classification-recommendations/${encodeURIComponent(normalized)}`,
    { signal },
  ).then((payload) => {
    if (isNonAuthoritativeMockEvidence(payload, payload?.meta, payload?.provenance, payload?.warnings)) {
      return null;
    }
    return normalizeClassificationRecord(payload?.recommendation);
  });
}

/**
 * @param {string} recommendationId
 * @param {{ decision?: string, note?: string }} [payload]
 */
export function reviewClassificationRecommendation(recommendationId, { decision, note = "" } = {}) {
  const normalized = String(recommendationId || "").trim();
  if (!normalized) {
    return Promise.reject(new Error("recommendationId is required"));
  }
  return requestJson(
    `/classification-recommendations/${encodeURIComponent(normalized)}/review`,
    "POST",
    { decision, note },
  ).then((payload) => {
    if (isNonAuthoritativeMockEvidence(payload, payload?.meta, payload?.provenance, payload?.warnings)) {
      return null;
    }
    return normalizeClassificationRecord(payload?.recommendation);
  });
}

export function scanClassificationRecommendations(assetFqn) {
  const normalized = String(assetFqn || "").trim();
  if (!normalized) {
    return Promise.reject(new Error("assetFqn is required"));
  }
  return requestJson(
    `/classification-recommendations/scan/${encodeURIComponent(normalized)}`,
    "POST",
    {},
  ).then((payload) => {
    if (isNonAuthoritativeMockEvidence(payload, payload?.meta, payload?.provenance, payload?.warnings)) {
      return {
        ok: false,
        assetFqn: normalized,
        scanned: 0,
        generated: 0,
        recommendations: [],
        nonAuthoritative: true,
      };
    }
    const recs = Array.isArray(payload?.recommendations) ? payload.recommendations : [];
    if (recs.some((record) => isNonAuthoritativeMockEvidence(record, record?.meta, record?.provenance, record?.warnings, record?.evidence))) {
      return {
        ok: false,
        assetFqn: String(payload?.assetFqn || normalized),
        scanned: 0,
        generated: 0,
        recommendations: [],
        nonAuthoritative: true,
      };
    }
    const recommendations = recs.map(normalizeClassificationRecord).filter(Boolean);
    return {
      ok: Boolean(payload?.ok),
      assetFqn: String(payload?.assetFqn || normalized),
      scanned: Number(payload?.scanned || 0),
      generated: Number(payload?.generated || recommendations.length || 0),
      recommendations,
    };
  });
}

export function updateAssetColumnDescription(assetFqn, columnName, description) {
  return requestJson(
    columnRoute("/assets/:fqn/columns/:column/description", assetFqn, columnName),
    "PATCH",
    { description },
  );
}

export function updateAssetColumnTags(assetFqn, columnName, tags) {
  return requestJson(
    columnRoute("/assets/:fqn/columns/:column/tags", assetFqn, columnName),
    "PATCH",
    { tags },
  );
}

export function updateAssetColumnMetadata(assetFqn, columnName, payload) {
  const template = contractPath("assetColumnMetadataUpdate") || "/assets/:fqn/columns/:column/metadata";
  return requestJson(
    columnRoute(template, assetFqn, columnName),
    "PATCH",
    payload,
  );
}

export function getAssetMetadataApiContract(assetFqn) {
  const capabilityTemplate = contractPath(
    "assetMetadataEditor",
    "assetMetadataEdit",
    "assetMetadata",
  );
  const updateTemplate = contractPath(
    "assetMetadataUpdate",
    "assetMetadataEditor",
    "assetMetadataEdit",
    "assetMetadata",
  );

  return {
    available: Boolean(capabilityTemplate || updateTemplate),
    capabilityPath: capabilityTemplate ? assetRoute(capabilityTemplate, assetFqn) : "",
    updatePath: assetRoute(updateTemplate || capabilityTemplate, assetFqn),
  };
}

export async function fetchAssetMetadataEditor(assetFqn, endpoint) {
  const contract = getAssetMetadataApiContract(assetFqn);
  const path = endpoint || contract.capabilityPath;
  if (!path) return null;

  try {
    return await request(path);
  } catch (error) {
    if ([404, 405, 501].includes(error?.status)) {
      return null;
    }
    throw error;
  }
}

export async function updateAssetMetadata(assetFqn, payload, config = {}) {
  const contract = getAssetMetadataApiContract(assetFqn);
  const targetPath = assetRoute(
    config.updatePath || config.path || config.endpoint || contract.updatePath,
    assetFqn,
  );
  if (!targetPath) {
    throw new Error("Metadata editing is not available for this asset.");
  }

  const methods = [
    normalizedMethod(config.updateMethod, ""),
    normalizedMethod(config.method, ""),
    "PATCH",
    "POST",
    "PUT",
  ].filter(Boolean);
  const attempts = [...new Set(methods)];
  let lastError = null;

  for (const method of attempts) {
    try {
      return await requestJson(targetPath, method, payload);
    } catch (error) {
      if ([404, 405, 501].includes(error?.status)) {
        lastError = error;
        continue;
      }
      throw error;
    }
  }

  throw lastError || new Error("Metadata editing is not available for this asset.");
}

// Phase 8/10/11/13/14 fetchers — thin wrappers around the consolidated
// catalog router. These return raw envelope payloads ({data, meta,
// errors}); callers pick `.data` as needed.

function unwrapEnvelope(payload) {
  if (payload && typeof payload === "object" && "data" in payload) {
    return payload.data;
  }
  return payload;
}

export function patchAssetDescription(assetFqn, description) {
  return requestJson(
    `/assets/${encodeURIComponent(assetFqn)}/description`,
    "PATCH",
    { description: description ?? "" },
  );
}

export function fetchAssetCustomProperties(assetFqn, options = {}) {
  return request(
    `/assets/${encodeURIComponent(assetFqn)}/custom-properties`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchAssetProfile(assetFqn, options = {}) {
  return request(
    `/assets/${encodeURIComponent(assetFqn)}/profile`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchAssetQuality(assetFqn, options = {}) {
  return request(
    `/assets/${encodeURIComponent(assetFqn)}/quality`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchAssetDatabricksEvidence(assetFqn, options = {}) {
  return request(
    `/assets/${encodeURIComponent(assetFqn)}/databricks-evidence`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchAccessExplain(assetFqn = "", options = {}) {
  const path = assetFqn
    ? `/assets/${encodeURIComponent(assetFqn)}/access-explain`
    : "/access-explain";
  return request(path, { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchClassifications(options = {}) {
  return request("/classifications", { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchClassification(classificationId, options = {}) {
  return request(
    `/classifications/${encodeURIComponent(classificationId)}`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchDomains(options = {}) {
  return request("/domains", { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchDataProducts(options = {}) {
  return request("/data-products", { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchLogicalColumnGroups(options = {}) {
  return request("/governance/columns", { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchLogicalColumnGroup(groupId, options = {}) {
  return request(
    `/governance/columns/${encodeURIComponent(groupId)}`,
    { signal: options.signal },
  ).then(unwrapEnvelope);
}

export function fetchAuditEvents(filters = {}, options = {}) {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.append(key, value);
  });
  const qs = params.toString();
  return request(`/audit/events${qs ? `?${qs}` : ""}`, { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchQualityFindings(filters = {}, options = {}) {
  // Wave C5 — the Evidence quality tab. GET /api/quality/findings returns a
  // FLAT envelope ({findings, summary, state, reason, windowTruncated,
  // visibilityScopedRowsExcluded, meta}); deliberately NOT unwrapEnvelope'd
  // so useAtlasQuery's envelope-status resolution (lib/envelope.js flat-payload
  // fallbacks) can honor state/meta/warnings.
  const params = new URLSearchParams();
  if (filters.asset) params.set("asset", filters.asset);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.outcome) params.set("outcome", filters.outcome);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.limit) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return request(`/quality/findings${qs ? `?${qs}` : ""}`, { signal: options.signal });
}

export function fetchAdminExportJobs(filters = {}, options = {}) {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.append(key, value);
  });
  const qs = params.toString();
  return request(`/admin/export-jobs${qs ? `?${qs}` : ""}`, { signal: options.signal }).then(unwrapEnvelope);
}

export function fetchColumnLineageTrace(assetFqn, columnName, options = {}) {
  const direction = options.direction || "upstream";
  const depth = options.depth != null ? options.depth : 2;
  const params = new URLSearchParams({
    asset_fqn: assetFqn,
    column_name: columnName,
    direction,
    depth: String(depth),
  });
  return request(`/lineage/column-trace?${params.toString()}`, {
    signal: options.signal,
  }).then(unwrapEnvelope);
}

export function createCustomPropertyDefinition(payload) {
  return requestJson("/custom-properties/definitions", "POST", payload).then(unwrapEnvelope);
}

export function upsertCustomPropertyAssignment(payload) {
  return requestJson("/custom-properties/assignments", "POST", payload).then(unwrapEnvelope);
}

export function validateQualityCustomSql(payload) {
  return requestJson("/quality/custom-sql/validate", "POST", payload).then(unwrapEnvelope);
}
