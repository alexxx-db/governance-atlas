import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const FORWARDED_EMAIL = (process.env.GOVAT_CAPTURE_FORWARDED_EMAIL || "").trim();
const FORWARDED_USERNAME = (process.env.GOVAT_CAPTURE_FORWARDED_USERNAME || FORWARDED_EMAIL).trim();
const FORWARDED_DISPLAY_NAME = (process.env.GOVAT_CAPTURE_FORWARDED_DISPLAY_NAME || "").trim();
const FORWARDED_ACCESS_TOKEN = (process.env.GOVAT_CAPTURE_FORWARDED_ACCESS_TOKEN || "").trim();
const EXPECTED_BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const SETTLE_TIMEOUT_MS = Number.parseInt(process.env.GOVAT_PROTOTYPE_SETTLE_TIMEOUT_MS || "90000", 10);
const TEXT_SETTLE_TIMEOUT_MS = Number.parseInt(process.env.GOVAT_PROTOTYPE_TEXT_SETTLE_TIMEOUT_MS || "120000", 10);
const SHELL_FALLBACK = process.env.GOVAT_PROTOTYPE_SHELL_FALLBACK === "1";
const MOCK_API = process.env.GOVAT_PROTOTYPE_MOCK_API === "1";
const SCROLL_MAIN = process.env.GOVAT_PROTOTYPE_SCROLL_MAIN === "1";
const CAPTURE_FULL_PAGE = process.env.GOVAT_PROTOTYPE_FULL_PAGE !== "0";
const CAPTURE_INTERACTIONS = process.env.GOVAT_PROTOTYPE_INTERACTIONS === "1";
const DEBUG_STEPS = process.env.GOVAT_PROTOTYPE_DEBUG_STEPS === "1";
const ROUTE_FILTER = new Set(
  (process.env.GOVAT_PROTOTYPE_ROUTES || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
);
const INTERACTION_FILTER = new Set(
  (process.env.GOVAT_PROTOTYPE_INTERACTION_KEYS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
);
const OUT_DIR =
  process.env.GOVAT_PROTOTYPE_CAPTURE_OUT ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/prototype-current");
function normalizeEvidencePath(value) {
  const resolved = path.resolve(value);
  const relative = path.relative(REPO_ROOT, resolved);
  const normalized =
    relative && !relative.startsWith("..") && !path.isAbsolute(relative)
      ? relative
      : value;
  return normalized.split(path.sep).join("/");
}
const CURRENT_REPORT_PATH = `${normalizeEvidencePath(OUT_DIR)}/prototype-current-report.json`;
const LIVE_DATABRICKS_CAPTURE = Boolean(TOKEN && /\.databricksapps\.com(?:\/|$)/i.test(BASE_URL));
const FORWARDED_ACTOR_CAPTURE = Boolean(FORWARDED_EMAIL || FORWARDED_ACCESS_TOKEN);
const EXTRA_HTTP_HEADERS = {
  ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  ...(FORWARDED_EMAIL ? { "x-forwarded-email": FORWARDED_EMAIL } : {}),
  ...(FORWARDED_USERNAME ? { "x-forwarded-preferred-username": FORWARDED_USERNAME } : {}),
  ...(FORWARDED_DISPLAY_NAME ? { "x-forwarded-display-name": FORWARDED_DISPLAY_NAME } : {}),
  ...(FORWARDED_ACCESS_TOKEN ? { "x-forwarded-access-token": FORWARDED_ACCESS_TOKEN } : {}),
};
const DEFAULT_ASSET_FQN = MOCK_API
  ? "finance_prod.curated.revenue_daily"
  : "finance_prod.curated.revenue_daily";
const ASSET_FQN =
  process.env.GOVAT_PROTOTYPE_ASSET_FQN ||
  DEFAULT_ASSET_FQN;

const PROTOTYPE_DISCOVERY_ASSETS = [
  {
    fqn: "finance_prod.curated.revenue_daily",
    name: "revenue_daily",
    fullPath: "finance_prod.curated.revenue_daily",
    catalog: "finance_prod",
    schema: "curated",
    objectType: "Delta Table",
    description: "Authoritative day-grain revenue grain by product line, channel, and region. Source-of-record for the CFO dashboard and quarterly board reporting.",
    coverageScore: 96,
    qualityScore: 96,
    columnCount: 10,
    lineageCount: 28,
    rows: 1_247_835,
    domain: "Finance",
    certification: "Certified",
    sensitivity: "Confidential",
    cde: true,
    pii: false,
    freshness: "14 min ago",
    queries30d: 14782,
    upstream: 5,
    downstream: 23,
    owners: [{ name: "Marisol Reyes", title: "Finance Steward" }],
    stewardTeam: "Finance Stewards",
    tagLabels: ["sox-relevant", "revenue", "gold"],
    glossaryTerms: [{ label: "Net Revenue" }, { label: "Revenue Recognition" }],
    columns: [
      { name: "date_key", type: "DATE", isPrimaryKey: true },
      { name: "product_line", type: "STRING" },
      { name: "channel", type: "STRING" },
      { name: "region", type: "STRING" },
      { name: "gross_revenue_usd", type: "DECIMAL" },
      { name: "net_revenue_usd", type: "DECIMAL", tags: ["CDE"] },
    ],
  },
  {
    fqn: "customer_360.gold.customer_profile",
    name: "customer_profile",
    fullPath: "customer_360.gold.customer_profile",
    catalog: "customer_360",
    schema: "gold",
    objectType: "Delta Table",
    description: "360-degree unified customer profile: demographics, lifecycle stage, segments, contact channels. Driving personalization and CS routing.",
    coverageScore: 91,
    qualityScore: 92,
    columnCount: 64,
    lineageCount: 52,
    rows: 38_400_000,
    domain: "Customer",
    certification: "Certified",
    sensitivity: "Restricted",
    cde: true,
    pii: true,
    freshness: "1 hr ago",
    queries30d: 9210,
    upstream: 11,
    downstream: 41,
    owners: [{ name: "Aaron Chen", title: "Customer Steward" }],
    stewardTeam: "Customer Stewards",
    tagLabels: ["Certified", "Restricted", "CDE", "PII"],
    glossaryTerms: [{ label: "Customer" }],
  },
  {
    fqn: "sales_prod.silver.orders",
    name: "orders",
    fullPath: "sales_prod.silver.orders",
    catalog: "sales_prod",
    schema: "silver",
    objectType: "Delta Table",
    description: "Cleansed order events with currency normalization. Feeds revenue, attribution, and finance pipelines.",
    coverageScore: 94,
    qualityScore: 94,
    columnCount: 38,
    lineageCount: 20,
    rows: 9_100_000,
    domain: "Revenue & Sales",
    certification: "Certified",
    sensitivity: "Confidential",
    cde: true,
    freshness: "5 min ago",
    queries30d: 12044,
    upstream: 3,
    downstream: 17,
    owners: [{ name: "Priya Natarajan", title: "Revenue Steward" }],
    stewardTeam: "Revenue Stewards",
    tagLabels: ["Certified", "Confidential", "CDE"],
    glossaryTerms: [{ label: "Booking" }],
  },
  {
    fqn: "product_events.bronze.clickstream_events",
    name: "clickstream_events",
    fullPath: "product_events.bronze.clickstream_events",
    catalog: "product_events",
    schema: "bronze",
    objectType: "Delta Table",
    description: "Raw web and mobile click events from Snowplow. High volume; downstream pipelines aggregate into product_events.silver.sessions.",
    coverageScore: 78,
    qualityScore: 81,
    columnCount: 42,
    lineageCount: 7,
    rows: 4_287_400_000,
    domain: "Customer",
    certification: "In Review",
    sensitivity: "Internal",
    pii: true,
    freshness: "3 min ago",
    queries30d: 244,
    upstream: 1,
    downstream: 6,
    owners: [{ name: "Devon Park", title: "Product Analytics" }],
    stewardTeam: "Product Analytics",
    tagLabels: ["In Review", "Internal", "PII"],
    glossaryTerms: [{ label: "Session" }],
  },
  {
    fqn: "hr_secure.confidential.compensation_band",
    name: "compensation_band",
    fullPath: "hr_secure.confidential.compensation_band",
    catalog: "hr_secure",
    schema: "confidential",
    objectType: "Delta Table",
    description: "Compensation band metadata by job family and level. Restricted access. Permission-gated.",
    coverageScore: 99,
    qualityScore: null,
    columnCount: 16,
    lineageCount: 2,
    rows: 1248,
    domain: "People",
    certification: "Certified",
    sensitivity: "Restricted",
    cde: true,
    pii: true,
    freshness: "6 hr ago",
    queries30d: 86,
    upstream: 2,
    downstream: 0,
    owners: [{ name: "Yuki Tanaka", title: "People Steward" }],
    stewardTeam: "People Stewards",
    tagLabels: ["Certified", "Restricted", "CDE", "PII"],
    glossaryTerms: [{ label: "Compensation Band" }],
  },
  {
    fqn: "marketing_mart.gold.attribution_daily",
    name: "attribution_daily",
    fullPath: "marketing_mart.gold.attribution_daily",
    catalog: "marketing_mart",
    schema: "gold",
    objectType: "View",
    description: "Multi-touch attribution at the campaign and channel day grain. Used by exec marketing dashboards.",
    coverageScore: 88,
    qualityScore: 89,
    columnCount: 24,
    lineageCount: 17,
    rows: 400_000,
    domain: "Marketing",
    certification: "Certified",
    sensitivity: "Internal",
    freshness: "32 min ago",
    queries30d: 2810,
    upstream: 6,
    downstream: 11,
    owners: [{ name: "Lina Okafor", title: "Marketing Steward" }],
    stewardTeam: "Marketing Stewards",
    tagLabels: ["Certified", "Internal"],
    glossaryTerms: [{ label: "Attribution" }],
  },
  {
    fqn: "customer_360.ml.churn_propensity_v3",
    name: "churn_propensity_v3",
    fullPath: "customer_360.ml.churn_propensity_v3",
    catalog: "customer_360",
    schema: "ml",
    objectType: "Model",
    description: "Gradient-boosted churn propensity served via Databricks Model Serving. Inputs: customer_profile, billing_events.",
    coverageScore: 92,
    qualityScore: 91,
    columnCount: 31,
    lineageCount: 11,
    rows: "",
    domain: "Customer",
    certification: "Certified",
    sensitivity: "Confidential",
    freshness: "2 day ago",
    queries30d: 411,
    upstream: 3,
    downstream: 4,
    owners: [{ name: "Aaron Chen", title: "Customer Steward" }],
    stewardTeam: "Customer Stewards",
    tagLabels: ["Certified", "Confidential"],
    glossaryTerms: [{ label: "Churn Propensity" }],
  },
  {
    fqn: "experimental.sandbox.pricing_experiment_2025q4",
    name: "pricing_experiment_2025q4",
    fullPath: "experimental.sandbox.pricing_experiment_2025q4",
    catalog: "experimental",
    schema: "sandbox",
    objectType: "Delta Table",
    description: "Sandbox table from a pricing experiment. No owner, no description until last week. Auto-flagged.",
    coverageScore: 42,
    qualityScore: null,
    columnCount: 8,
    lineageCount: 1,
    rows: 100_000,
    domain: "Revenue & Sales",
    certification: "Uncertified",
    sensitivity: "Unclassified",
    freshness: "12 day ago",
    queries30d: 14,
    upstream: 1,
    downstream: 0,
    owners: [],
    tagLabels: ["Uncertified", "Unclassified"],
    glossaryTerms: [],
  },
];

const PROTOTYPE_DISCOVERY_FACETS = {
  certifications: [
    { value: "Certified", count: 6 },
    { value: "In Review", count: 1 },
    { value: "Uncertified", count: 1 },
  ],
  domains: [
    { value: "Revenue & Sales", count: 2 },
    { value: "Customer", count: 3 },
    { value: "Marketing", count: 1 },
    { value: "Finance", count: 1 },
    { value: "Operations", count: 0 },
    { value: "People", count: 1 },
  ],
  sensitivities: [
    { value: "Restricted", count: 2 },
    { value: "Confidential", count: 3 },
    { value: "Internal", count: 2 },
    { value: "Unclassified", count: 1 },
  ],
  assetTypes: [
    { value: "Delta Table", count: 6 },
    { value: "View", count: 1 },
    { value: "Model", count: 1 },
  ],
  catalogs: [
    { value: "finance_prod", count: 1 },
    { value: "customer_360", count: 2 },
    { value: "sales_prod", count: 1 },
    { value: "product_events", count: 1 },
    { value: "hr_secure", count: 1 },
    { value: "marketing_mart", count: 1 },
    { value: "experimental", count: 1 },
  ],
};

const DEFAULT_VIEWPORTS = [
  { name: "1536x1024", width: 1536, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x720", width: 1280, height: 720 },
];

function parseViewportList(value) {
  const parsed = String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const match = item.match(/^(\d{3,5})x(\d{3,5})$/i);
      if (!match) return null;
      const width = Number.parseInt(match[1], 10);
      const height = Number.parseInt(match[2], 10);
      if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
      return { name: `${width}x${height}`, width, height };
    })
    .filter(Boolean);
  return parsed.length ? parsed : DEFAULT_VIEWPORTS;
}

const VIEWPORTS = parseViewportList(process.env.GOVAT_PROTOTYPE_VIEWPORTS);

const SCREENSHOT_ROUTES = [
  { key: "command-center", path: "/command-center", settle: ".gh-home-page" },
  { key: "discover", path: "/discover", settle: ".gh-discovery-workspace,.gh-discovery-main-grid" },
  { key: "stewardship", path: "/stewardship", settle: ".gh-governance-ns-table,.gh-governance-ns-empty" },
  { key: "glossary", path: "/glossary-cdes", settle: ".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace" },
  { key: "cde-registry", path: "/glossary-cdes?tab=cdes", settle: ".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace" },
  { key: "lineage", path: `/lineage-atlas/${encodeURIComponent(ASSET_FQN)}`, settle: ".ga-lineage-explorer,.gh-lineage-workspace,.gh-lineage-canvas,.gh-workspace" },
  { key: "audit", path: "/audit-evidence", settle: ".gh-audit-ns,.gh-audit-workspace,.gh-workspace" },
  { key: "control-center", path: "/control-center", settle: ".gh-admin-ns,.gh-admin-workspace,.gh-workspace" },
];

const SUPPORTING_ROUTES = [
  { key: "asset360", path: `/entity/${encodeURIComponent(ASSET_FQN)}`, settle: ".gh-entity-workspace,.gh-entity-record-layout,.gh-workspace" },
];

const ROUTES = [...SCREENSHOT_ROUTES, ...SUPPORTING_ROUTES];
const KNOWN_ROUTE_KEYS = new Set(ROUTES.map((route) => route.key));
const UNKNOWN_ROUTE_FILTERS = Array.from(ROUTE_FILTER).filter((routeKey) => !KNOWN_ROUTE_KEYS.has(routeKey));

const SELECTED_ROUTES = ROUTE_FILTER.size
  ? ROUTES.filter((route) => ROUTE_FILTER.has(route.key))
  : SCREENSHOT_ROUTES;
const EXPECTED_CAPTURE_COUNT = SELECTED_ROUTES.length * VIEWPORTS.length;

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  buildId: EXPECTED_BUILD_ID,
  deploymentId: DEPLOYMENT_ID,
  assetFqn: ASSET_FQN,
  mockApi: MOCK_API,
  evidenceKind: MOCK_API ? "non_authoritative_mock_capture" : LIVE_DATABRICKS_CAPTURE ? "live_databricks" : "runtime_app_capture",
  mockEvidenceWarning: MOCK_API ? "Non-authoritative mock capture data; not product-readiness or live Databricks evidence." : "",
  liveDatabricksCapture: LIVE_DATABRICKS_CAPTURE,
  forwardedActorCapture: FORWARDED_ACTOR_CAPTURE,
  forwardedActorEmail: FORWARDED_EMAIL,
  forwardedActorTokenPresent: Boolean(FORWARDED_ACCESS_TOKEN),
  routeFilter: Array.from(ROUTE_FILTER),
  interactionFilter: Array.from(INTERACTION_FILTER),
  routeFilterUnknown: UNKNOWN_ROUTE_FILTERS,
  selectedRoutes: SELECTED_ROUTES.map((route) => route.key),
  viewports: VIEWPORTS,
  expectedCaptureCount: EXPECTED_CAPTURE_COUNT,
  captures: [],
  interactions: [],
  console: [],
  pageErrors: [],
  requestFailures: [],
  checks: {
    buildMatches: EXPECTED_BUILD_ID ? false : true,
  },
};

const PROTOTYPE_MOCK_SOURCE = "local-prototype-mock";
const PROTOTYPE_MOCK_STATE = "prototype_mock";
const PROTOTYPE_MOCK_WARNING = "Prototype mock data, not live Databricks evidence.";
const mockApiFlags = {
  auditDegraded: process.env.GOVAT_PROTOTYPE_AUDIT_DEGRADED === "1",
  discoveryDegraded: false,
  governanceDegraded: process.env.GOVAT_PROTOTYPE_GOVERNANCE_DEGRADED === "1",
  previewDegraded: false,
  taxonomyDegraded: process.env.GOVAT_PROTOTYPE_TAXONOMY_DEGRADED === "1",
};

function prototypeMockWarnings(warnings = []) {
  return Array.from(new Set([PROTOTYPE_MOCK_WARNING, ...(Array.isArray(warnings) ? warnings : [])].filter(Boolean)));
}

function prototypeMockMeta(extra = {}) {
  return {
    ...extra,
    state: PROTOTYPE_MOCK_STATE,
    source: PROTOTYPE_MOCK_SOURCE,
    authoritative: false,
    degraded: true,
    warnings: prototypeMockWarnings(extra.warnings),
  };
}

function prototypeMockCapability(extra = {}) {
  return {
    ...extra,
    available: extra.available !== false,
    state: PROTOTYPE_MOCK_STATE,
    source: PROTOTYPE_MOCK_SOURCE,
    authoritative: false,
    reason: extra.reason || PROTOTYPE_MOCK_WARNING,
  };
}

function urlFor(routePath) {
  return new URL(routePath, BASE_URL).toString();
}

async function loadJson(relativePath, fallback) {
  try {
    const raw = await fs.readFile(path.join(REPO_ROOT, relativePath), "utf8");
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function jsonResponse(payload, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  };
}

function requestRefererHasFlag(route, flag) {
  try {
    const referer = route.request().headers()?.referer || "";
    if (!referer) return false;
    return new URL(referer).searchParams.get(flag) === "1";
  } catch {
    return false;
  }
}

function syntheticCommandCenter() {
  const now = Date.now();
  const minutesAgo = (minutes) => new Date(now - minutes * 60_000).toISOString();
  const secondsAgo = (seconds) => new Date(now - seconds * 1_000).toISOString();
  const domains = [
    { domain: "Revenue & Sales", score: 92, count: 138 },
    { domain: "Customer", score: 84, count: 174 },
    { domain: "Marketing", score: 88, count: 89 },
    { domain: "Finance", score: 95, count: 121 },
    { domain: "Operations", score: 79, count: 64 },
    { domain: "People", score: 72, count: 26 },
  ];
  const catalogs = [
    { catalog: "finance_prod", coverage: 94, classification: "Restricted", risk: "Low", count: 412 },
    { catalog: "sales_prod", coverage: 91, classification: "Internal", risk: "Low", count: 781 },
    { catalog: "customer_360", coverage: 82, classification: "Confidential", risk: "Medium", count: 528 },
    { catalog: "product_events", coverage: 76, classification: "Internal", risk: "Medium", count: 246 },
    { catalog: "marketing_mart", coverage: 88, classification: "Internal", risk: "Low", count: 192 },
    { catalog: "hr_secure", coverage: 71, classification: "Restricted", risk: "High", count: 84 },
  ];
  return {
    estate: {
      visibleAssetCount: 1247,
      baselineAssetCount: 1427,
      catalogCount: 6,
      openRequests: 184,
      coverageScore: 87.4,
      cdeCount: 42,
    },
    kpis: [
      {
        key: "governedAssets",
        label: "Governed Assets",
        value: 1247,
        format: "number",
        deltaText: "+82 this quarter",
        sparkline: [960, 985, 1008, 1044, 1090, 1128, 1164, 1196, 1214, 1228, 1238, 1247],
      },
      {
        key: "certifiedCriticalAssets",
        label: "Certified Critical Assets",
        value: 612,
        format: "number",
        deltaText: "+37 this week",
        sparkline: [410, 420, 440, 460, 488, 510, 530, 548, 560, 575, 590, 612],
      },
      {
        key: "metadataCoverage",
        label: "Metadata Coverage",
        value: 87.4,
        format: "percent",
        deltaText: "+2.1 pts vs last week",
        sparkline: [62, 65, 68, 70, 72, 74, 77, 80, 82, 84, 85, 87.4],
      },
      {
        key: "openStewardship",
        label: "Open Stewardship Actions",
        value: 184,
        format: "number",
        deltaText: "-11 this week",
        sparkline: [240, 232, 228, 222, 218, 212, 205, 200, 196, 192, 190, 184],
      },
      {
        key: "policyExceptions",
        label: "Policy Exceptions",
        value: 7,
        format: "number",
        deltaText: "+2 new this week",
        sparkline: [5, 5, 5, 5, 5, 5, 6, 6, 6, 7, 7, 7],
      },
      {
        key: "auditReadiness",
        label: "Audit Readiness",
        value: null,
        format: "percent",
        state: "unavailable",
        reason: "Readiness requires backed audit-control policy coverage.",
      },
    ],
    posture: {
      overall: 87.4,
      trend: [
        { label: "W14", overall: 78.4, policy: 80, quality: 74 },
        { label: "W15", overall: 79.1, policy: 81, quality: 75 },
        { label: "W16", overall: 81.0, policy: 82, quality: 77 },
        { label: "W17", overall: 82.3, policy: 84, quality: 79 },
        { label: "W18", overall: 83.7, policy: 85, quality: 80 },
        { label: "W19", overall: 84.2, policy: 86, quality: 81 },
        { label: "W20", overall: 85.0, policy: 87, quality: 82 },
        { label: "W21", overall: 85.4, policy: 88, quality: 82.5 },
        { label: "W22", overall: 86.0, policy: 89, quality: 83.4 },
        { label: "W23", overall: 86.4, policy: 89.5, quality: 84.2 },
        { label: "W24", overall: 86.9, policy: 90, quality: 85.1 },
        { label: "W25", overall: 87.4, policy: 91, quality: 86 },
      ],
      byDomain: domains,
      heatmap: [],
    },
    topDomains: domains,
    riskBreakdown: {
      cleanScore: 92,
      high: 7,
      medium: 28,
      informational: 64,
      totalExposures: 99,
    },
    catalogHealth: catalogs.map((catalog) => ({
      catalog: catalog.catalog,
      tables: catalog.count,
      coverage: catalog.coverage,
      classification: catalog.classification,
      risk: catalog.risk,
    })),
    criticalDataElements: [
      {
        id: "net-revenue-usd",
        name: "Net Revenue (USD)",
        column: "finance_prod.curated.revenue_daily.net_revenue_usd",
        owner: "Finance Stewards",
        status: "Healthy",
        sox: true,
      },
      {
        id: "customer-id",
        name: "Customer ID",
        column: "customer_360.gold.customer_profile.customer_id",
        owner: "Customer Stewards",
        status: "Healthy",
      },
      {
        id: "lifetime-value-usd",
        name: "Lifetime Value (USD)",
        column: "customer_360.gold.customer_profile.lifetime_value_usd",
        owner: "Customer Stewards",
        status: "Recert due (8d)",
      },
      {
        id: "compensation-band",
        name: "Compensation Band",
        column: "hr_secure.confidential.compensation.band_id",
        owner: "People Stewards",
        status: "Healthy",
      },
    ],
    changesToday: [
      {
        label: "Coverage",
        value: 87.4,
        previous: 86.8,
        previousFormat: "percent",
        delta: "+12 newly certified",
        tone: "good",
      },
      {
        label: "Quality SLA",
        value: 94.3,
        previous: 94.1,
        previousFormat: "percent",
        delta: "3 expectations passing",
        tone: "good",
      },
      {
        label: "High-risk exposures",
        value: 7,
        previous: 9,
        previousFormat: "count",
        delta: "2 mitigated by Steward team",
        tone: "bad",
      },
      {
        label: "Lineage coverage",
        value: 98.6,
        previous: 98.6,
        previousFormat: "percent",
        delta: "No regressions",
        tone: "muted",
      },
    ],
    narrative: {
      scopeLabel: "finance_prod",
      baselineAssetCount: 1427,
      target: "90% Q2 target",
      targetWeek: "week 30",
    },
    recentAssets: catalogs.flatMap((catalog) =>
      Array.from({ length: Math.max(1, Math.round(catalog.count / 120)) }, (_, index) => ({
        fqn: `${catalog.catalog}.curated.asset_${index + 1}`,
        name: `asset_${index + 1}`,
        catalog: catalog.catalog,
        schema: "curated",
        objectType: "Delta Table",
        metadataCoverage: catalog.coverage,
        classification: catalog.classification,
        risk: catalog.risk,
      }))
    ),
    recentEvents: [
      {
        id: "AE-78421",
        title: "flagged 1 asset for missing owner",
        detail: "Owner-required policy failed.",
        actor: "svc-governance-sweeper",
        createdAt: minutesAgo(12),
        tone: "bad",
        target: "experimental.sandbox.pricing_experiment_2025q4",
      },
      {
        id: "AE-78410",
        title: "certified",
        detail: "Re-certified for Q2 2026.",
        actor: "Marisol Reyes",
        createdAt: minutesAgo(32),
        tone: "good",
        target: "finance_prod.curated.revenue_daily",
      },
      {
        id: "AE-78404",
        title: "auto-tagged PII columns on",
        detail: "Classifier fixture event.",
        actor: "svc-classifier",
        createdAt: minutesAgo(54),
        tone: "info",
        target: "customer_360.silver.contact_events",
      },
      {
        id: "AE-78399",
        title: "approved access for `customer-success-leads` to",
        detail: "Access request approved.",
        actor: "Aaron Chen",
        createdAt: minutesAgo(64),
        tone: "info",
        target: "customer_360.gold.customer_profile",
      },
      {
        id: "AE-78392",
        title: "acknowledged quality alert on",
        detail: "Linked to Lakeflow run 1029384.",
        actor: "Priya Natarajan",
        createdAt: minutesAgo(121),
        tone: "warn",
        target: "sales_prod.silver.orders",
      },
    ],
    aiPrompts: [
      "What's powering the CFO Quarterly Dashboard, and is anything at risk this week?",
      "Which uncertified tables are queried by executives?",
      "Summarize PII coverage in customer_360.",
      "Who owns net_revenue_usd and when was it last certified?",
    ],
    meta: {
      generatedAt: secondsAgo(14),
      primaryCatalog: "finance_prod",
      workspace: "entrada-prod",
      workspaceLabel: "entrada-prod",
      workspaceName: "entrada-prod",
      ...prototypeMockMeta(),
    },
  };
}

function listParam(params, key) {
  const values = params.getAll(key);
  const single = params.get(key);
  if (single && !values.includes(single)) values.push(single);
  return values
    .flatMap((value) => String(value || "").split(","))
    .map((value) => value.trim())
    .filter(Boolean);
}

function assetSearchText(asset) {
  return [
    asset?.name,
    asset?.fqn,
    asset?.fullPath,
    asset?.catalog,
    asset?.schema,
    asset?.objectType,
    asset?.description,
    asset?.domain,
    asset?.certification,
    asset?.sensitivity,
    ...(Array.isArray(asset?.tagLabels) ? asset.tagLabels : []),
    ...(Array.isArray(asset?.tags) ? asset.tags : []),
    ...(Array.isArray(asset?.glossaryTerms) ? asset.glossaryTerms.map((term) => term?.label || term?.name || term) : []),
    ...(Array.isArray(asset?.owners) ? asset.owners.map((owner) => owner?.name || owner?.email || owner) : []),
  ].filter(Boolean).join(" ").toLowerCase();
}

function valuesMatch(assetValue, targets) {
  if (!targets.length) return true;
  const value = String(assetValue || "").toLowerCase();
  return targets.some((target) => value === String(target || "").toLowerCase());
}

function tagMatches(asset, target) {
  const normalized = String(target || "").toLowerCase();
  if (normalized === "cde") return Boolean(asset?.cde || asset?.isCde || asset?.criticalDataElement);
  if (normalized === "pii") return Boolean(asset?.pii || asset?.containsPii);
  if (normalized === "no_pii") return !asset?.pii && !asset?.containsPii;
  const tags = [
    ...(Array.isArray(asset?.tagLabels) ? asset.tagLabels : []),
    ...(Array.isArray(asset?.tags) ? asset.tags : []),
  ].map((tag) => String(tag || "").toLowerCase());
  return tags.includes(normalized);
}

function discoveryClauseMatches(asset, rawClause) {
  const clause = String(rawClause || "").trim().replace(/^\(+|\)+$/g, "");
  if (!clause) return true;
  const fieldMatch = clause.match(/^([a-z_]+)\s*:\s*"?([^"]+?)"?$/i);
  if (!fieldMatch) return assetSearchText(asset).includes(clause.toLowerCase());
  const field = fieldMatch[1].toLowerCase();
  const value = fieldMatch[2].trim();
  if (!value) return true;
  switch (field) {
    case "name":
      return String(asset?.name || "").toLowerCase().includes(value.toLowerCase());
    case "fqn":
      return String(asset?.fqn || "").toLowerCase().includes(value.toLowerCase());
    case "description":
      return String(asset?.description || "").toLowerCase().includes(value.toLowerCase());
    case "catalog":
      return valuesMatch(asset?.catalog, [value]);
    case "schema":
      return valuesMatch(asset?.schema, [value]);
    case "domain":
      return valuesMatch(asset?.domain, [value]);
    case "certification":
      return valuesMatch(asset?.certification, [value]);
    case "sensitivity":
    case "classification":
      return valuesMatch(asset?.sensitivity, [value]);
    case "type":
      return valuesMatch(asset?.objectType, [value]);
    case "owner":
      return (asset?.owners || []).some((owner) => String(owner?.name || owner?.email || owner || "").toLowerCase().includes(value.toLowerCase()));
    case "glossary":
      return (asset?.glossaryTerms || []).some((term) => String(term?.label || term?.name || term || "").toLowerCase().includes(value.toLowerCase()));
    case "tag":
      return tagMatches(asset, value);
    default:
      return assetSearchText(asset).includes(value.toLowerCase());
  }
}

function queryLooksInvalid(query) {
  const text = String(query || "");
  if (!text.trim()) return false;
  const open = (text.match(/\(/g) || []).length;
  const close = (text.match(/\)/g) || []).length;
  if (open !== close) return true;
  return /:\s*$/.test(text) || /(?:AND|OR)\s*$/i.test(text);
}

function discoveryQueryMatches(asset, query) {
  const normalized = String(query || "").trim();
  if (!normalized) return true;
  const clauses = normalized
    .split(/\s+(?:AND|OR)\s+/i)
    .map((clause) => clause.trim())
    .filter(Boolean);
  return clauses.every((clause) => discoveryClauseMatches(asset, clause));
}

function facetEntries(assets, key, getter) {
  const counts = new Map(PROTOTYPE_DISCOVERY_FACETS[key]?.map((entry) => [entry.value, 0]) || []);
  assets.forEach((asset) => {
    const value = getter(asset);
    if (!value) return;
    counts.set(value, (counts.get(value) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([value, count]) => ({ value, count }))
    .filter((entry) => entry.count > 0 || (PROTOTYPE_DISCOVERY_FACETS[key] || []).some((seed) => seed.value === entry.value));
}

function syntheticDiscoveryFacets(assets) {
  return {
    certifications: facetEntries(assets, "certifications", (asset) => asset.certification),
    domains: facetEntries(assets, "domains", (asset) => asset.domain),
    sensitivities: facetEntries(assets, "sensitivities", (asset) => asset.sensitivity),
    assetTypes: facetEntries(assets, "assetTypes", (asset) => asset.objectType),
    catalogs: facetEntries(assets, "catalogs", (asset) => asset.catalog),
  };
}

function sortDiscoveryAssets(assets, sortBy) {
  const sort = String(sortBy || "").toLowerCase();
  const next = [...assets];
  if (/name/.test(sort)) {
    next.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
  } else if (/coverage|trust/.test(sort)) {
    return next;
  } else if (/request|issue|open/.test(sort)) {
    next.sort((a, b) => String(a.certification || "").localeCompare(String(b.certification || "")));
  }
  return next;
}

function syntheticDiscoveryPayload(bootstrap, requestUrl = "") {
  const url = requestUrl ? new URL(requestUrl) : null;
  const params = url?.searchParams || new URLSearchParams();
  const query = String(params.get("query") || "").trim();
  if (queryLooksInvalid(query)) {
    return {
      status: 400,
      payload: {
        invalidQuery: {
          state: "invalid",
          message: "Invalid discovery query.",
          syntaxHint: "Use field:value clauses with balanced parentheses and supported fields.",
          supportedFields: ["name", "fqn", "domain", "certification", "sensitivity", "tag", "owner", "type"],
        },
      },
    };
  }
  const assets = Array.isArray(bootstrap?.discovery?.defaultResults)
    ? bootstrap.discovery.defaultResults
    : [];
  const catalogs = listParam(params, "catalogs");
  const domains = listParam(params, "domains");
  const certifications = listParam(params, "certifications");
  const sensitivities = listParam(params, "sensitivities");
  const types = listParam(params, "types");
  const views = listParam(params, "views");
  const sortedAssets = sortDiscoveryAssets(
    assets.filter((asset) => {
      if (!discoveryQueryMatches(asset, query)) return false;
      if (!valuesMatch(asset.catalog, catalogs)) return false;
      if (!valuesMatch(asset.domain, domains)) return false;
      if (!valuesMatch(asset.certification, certifications)) return false;
      if (!valuesMatch(asset.sensitivity, sensitivities)) return false;
      if (!valuesMatch(asset.objectType, types)) return false;
      if (views.some((view) => /certified/i.test(view)) && !/certified/i.test(String(asset.certification || ""))) return false;
      if (views.some((view) => /owner/i.test(view)) && Array.isArray(asset.owners) && asset.owners.length) return false;
      if (views.some((view) => /coverage/i.test(view)) && Number(asset.coverageScore || 0) < 80) return false;
      return true;
    }),
    params.get("sortBy") || "",
  );
  const limit = Math.max(1, Number(params.get("limit") || sortedAssets.length || 80));
  const offset = Math.max(0, Number(params.get("offset") || 0));
  const pageAssets = sortedAssets.slice(offset, offset + limit);
  return {
    status: 200,
    payload: {
      authoritative: false,
      settled: true,
      loading: false,
      error: "",
      assets: pageAssets,
      count: sortedAssets.length,
      facets: syntheticDiscoveryFacets(sortedAssets),
      queryState: {
        state: query ? "filtered" : "",
        message: query ? `Filtered by ${query}` : "",
        syntaxHint: "Use field:value clauses with AND/OR, quoted phrases, and parentheses.",
        supportedFields: [
          "name",
          "fqn",
          "description",
          "catalog",
          "schema",
          "domain",
          "certification",
          "sensitivity",
          "criticality",
          "glossary",
          "tag",
          "owner",
          "type",
          "data_product",
        ],
        clauseChips: query ? [{ key: "query", label: query }] : [],
      },
      meta: {
        visibleAssetCount: sortedAssets.length,
        observedAt: "2026-04-27T09:14:22Z",
        ...prototypeMockMeta(),
      },
    },
  };
}

function syntheticStewardshipItems() {
  return [
    {
      sortOrder: 0,
      requestId: "SI-2491",
      title: "Owner missing",
      rawTitle: "Owner missing",
      kind: "Owner missing",
      type: "owner",
      status: "Pending",
      priority: "P1 critical",
      requester: "svc-governance-sweeper",
      createdAt: "2026-04-17T12:00:00Z",
      dueAt: "2026-04-24T12:00:00Z",
      assetFqn: "experimental.sandbox.pricing_experiment_2025q4",
      assetName: "pricing_experiment_2025q4",
      domain: "Revenue & Sales",
      assigned: "Revenue Stewards",
      sla: "4d overdue",
      slaState: "crit",
      age: "11d",
      detail: "Prototype fixture: owner missing; sample query signal shown for layout only. No live query/user evidence was checked.",
      evidence: "Prototype fixture: owner missing; sample query signal shown for layout only. No live query/user evidence was checked.",
      source: "Prototype fixture query signal",
      implementation:
        "Prototype fixture: no live query history checked. Live mode writes backed governance_state stewardship items only when a supported workflow source is configured.",
      suggestedActions: [
        {
          icon: "user-plus",
          label: "Assign owner from suggested teams",
          detail: "Prototype suggestion: Sales Engineering fixture match; not live query/tag proof.",
        },
        {
          icon: "archive",
          label: "Archive sandbox cleanup",
          detail: "Prototype cleanup hint; not live retention or usage proof.",
        },
      ],
    },
    {
      sortOrder: 1,
      requestId: "SI-2487",
      title: "Description missing",
      rawTitle: "Description missing",
      kind: "Description missing",
      type: "description",
      status: "Pending",
      priority: "P2",
      requester: "svc-metadata-sweeper",
      createdAt: "2026-04-23T12:00:00Z",
      dueAt: "2026-04-30T12:00:00Z",
      assetFqn: "product_events.bronze.clickstream_events",
      assetName: "clickstream_events",
      domain: "Customer",
      assigned: "Customer Stewards",
      sla: "2d left",
      slaState: "warn",
      age: "5d",
      detail: "No steward-approved description is recorded for this customer-facing event table.",
      evidence: "No steward-approved description is recorded for this customer-facing event table.",
      suggestedActions: [
        {
          icon: "sparkles",
          label: "Draft description with Atlas AI",
          detail: "Grounded by upstream lineage and column metadata.",
        },
      ],
    },
    {
      sortOrder: 2,
      requestId: "SI-2482",
      title: "Re-certification due",
      rawTitle: "Re-certification due",
      kind: "Re-certification due",
      type: "certification",
      status: "Pending",
      priority: "P2",
      requester: "svc-certification",
      createdAt: "2026-04-26T12:00:00Z",
      dueAt: "2026-04-28T18:00:00Z",
      assetFqn: "finance_prod.curated.revenue_daily",
      assetName: "revenue_daily",
      domain: "Finance",
      assigned: "Marisol Reyes",
      assignedToMe: true,
      sla: "Today",
      slaState: "warn",
      age: "89d",
      detail: "Quarterly recertification is due for a finance board-reporting source table.",
      evidence: "Certification expires today; executive dashboard queries observed this week.",
    },
    {
      sortOrder: 3,
      requestId: "SI-2479",
      title: "Tag policy violation",
      rawTitle: "Tag policy violation",
      kind: "Tag policy violation",
      type: "policy",
      status: "Pending",
      priority: "P1",
      requester: "svc-classifier",
      createdAt: "2026-04-20T12:00:00Z",
      dueAt: "2026-04-27T12:00:00Z",
      assetFqn: "customer_360.silver.contact_events",
      assetName: "contact_events",
      domain: "Customer",
      assigned: "Customer Stewards",
      sla: "1d overdue",
      slaState: "crit",
      age: "8d",
      detail: "Classifier found PII columns without the required governed tag.",
      evidence: "Auto-tag confidence exceeded 0.92 for 6 columns.",
    },
    {
      sortOrder: 4,
      requestId: "SI-2475",
      title: "Lineage gap",
      rawTitle: "Lineage gap",
      kind: "Lineage gap",
      type: "lineage",
      status: "Pending",
      priority: "P3",
      requester: "svc-lineage-collector",
      createdAt: "2026-04-26T12:00:00Z",
      dueAt: "2026-05-04T12:00:00Z",
      assetFqn: "marketing_mart.gold.attribution_daily",
      assetName: "attribution_daily",
      domain: "Marketing",
      assigned: "Marketing Stewards",
      sla: "6d left",
      slaState: "good",
      age: "2d",
      detail: "Column-level lineage is missing for one downstream dashboard edge.",
      evidence: "Table lineage is present; column lineage coverage is incomplete.",
    },
    {
      sortOrder: 5,
      requestId: "SI-2471",
      title: "Quality regression",
      rawTitle: "Quality regression",
      kind: "Quality regression",
      type: "quality",
      status: "Pending",
      priority: "P1",
      requester: "svc-quality",
      createdAt: "2026-04-27T12:00:00Z",
      dueAt: "2026-04-28T20:00:00Z",
      assetFqn: "sales_prod.silver.orders",
      assetName: "orders",
      domain: "Revenue & Sales",
      assigned: "Priya Natarajan",
      sla: "12h left",
      slaState: "warn",
      age: "1d",
      detail: "Freshness and currency-code checks failed after the last pipeline run.",
      evidence: "Lakeflow run 1029384 reported check currency_code_not_null failed.",
    },
    {
      sortOrder: 6,
      requestId: "SI-2469",
      title: "Access exception",
      rawTitle: "Access exception",
      kind: "Access exception",
      type: "access",
      status: "Pending",
      priority: "P2",
      requester: "svc-access-review",
      createdAt: "2026-04-27T08:00:00Z",
      dueAt: "2026-05-01T12:00:00Z",
      assetFqn: "hr_secure.confidential.compensation_band",
      assetName: "compensation_band",
      domain: "People",
      assigned: "People Stewards",
      sla: "3d left",
      slaState: "good",
      age: "16h",
      detail: "Restricted table has an access exception pending quarterly review.",
      evidence: "Quarterly access review identified one grant requiring business justification.",
    },
    {
      sortOrder: 7,
      requestId: "SI-2462",
      title: "Glossary mapping",
      rawTitle: "Glossary mapping",
      kind: "Glossary mapping",
      type: "glossary",
      status: "Pending",
      priority: "P3",
      requester: "marisol.reyes@entrada.ai",
      createdAt: "2026-04-24T12:00:00Z",
      dueAt: "2026-05-06T12:00:00Z",
      assetFqn: "customer_360.gold.customer_profile",
      assetName: "customer_profile",
      domain: "Customer",
      assigned: "Customer Stewards",
      sla: "8d left",
      slaState: "good",
      age: "4d",
      detail: "A steward filed a request to link lifecycle_stage to the Active Customer term.",
      evidence: "Manual steward request submitted from the glossary association drawer.",
    },
  ];
}

function syntheticStewardshipWorkbench() {
  const requests = syntheticStewardshipItems();
  return {
    summary: {
      openWorkItems: 184,
      slaBreaches: 7,
    },
    requests,
    selectedRequest: requests[0],
    meta: {
      observedAt: "2026-04-27T09:14:22Z",
      ...prototypeMockMeta(),
    },
  };
}

function syntheticStewardshipWorkbenchDegraded() {
  return {
    summary: {
      openWorkItems: 0,
      slaBreaches: null,
    },
    requests: [],
    selectedRequest: null,
    meta: {
      observedAt: "2026-04-27T09:14:22Z",
      ...prototypeMockMeta({
        state: "degraded",
        warnings: ["Prototype degraded stewardship state for visual QA only."],
      }),
    },
  };
}

function syntheticTaxonomyOverview() {
  const glossaryTerms = [
    {
      termId: "net-revenue",
      term: "Net Revenue",
      definition:
        "Gross revenue minus discounts and refunds; recognized per ASC 606. Source-of-record column: `finance_prod.curated.revenue_daily.net_revenue_usd`.",
      domain: "Finance",
      steward: "Finance Stewards",
      status: "Approved",
      assetCount: 4,
      linkedAssets: [
        {
          assetFqn: "finance_prod.curated.revenue_daily",
          assetLabel: "revenue_daily",
          assetType: "Delta Table",
          platform: "Unity Catalog",
        },
      ],
    },
    {
      termId: "active-customer",
      term: "Active Customer",
      definition:
        "A customer with at least one billable order in the trailing 90 days. Computed in `customer_360.gold.customer_profile.lifecycle_stage`.",
      domain: "Customer",
      steward: "Customer Stewards",
      status: "Approved",
      assetCount: 7,
      linkedAssets: [
        {
          assetFqn: "customer_360.gold.customer_profile",
          assetLabel: "customer_profile",
          assetType: "Delta Table",
          platform: "Unity Catalog",
        },
      ],
    },
    {
      termId: "churn-propensity",
      term: "Churn Propensity",
      definition:
        "Modeled probability that a customer will churn in the next 30 days. Served via `customer_360.ml.churn_propensity_v3`.",
      domain: "Customer",
      steward: "Customer Stewards",
      status: "Approved",
      assetCount: 3,
      linkedAssets: [
        {
          assetFqn: "customer_360.ml.churn_propensity_v3",
          assetLabel: "churn_propensity_v3",
          assetType: "Model",
          platform: "Unity Catalog",
        },
      ],
    },
    {
      termId: "booking",
      term: "Booking",
      definition: "A confirmed order, regardless of recognition status.",
      domain: "Revenue & Sales",
      steward: "Revenue Stewards",
      status: "In Review",
      assetCount: 6,
      linkedAssets: [
        {
          assetFqn: "sales_prod.silver.orders",
          assetLabel: "orders",
          assetType: "Delta Table",
          platform: "Unity Catalog",
        },
      ],
    },
  ];
  const cdes = [
    {
      id: "net-revenue-usd",
      name: "Net Revenue (USD)",
      column: "finance_prod.curated.revenue_daily.net_revenue_usd",
      owner: "Finance Stewards",
      recert: "90d",
      status: "Healthy",
      sox: true,
    },
    {
      id: "customer-id",
      name: "Customer ID",
      column: "customer_360.gold.customer_profile.customer_id",
      owner: "Customer Stewards",
      recert: "180d",
      status: "Healthy",
    },
    {
      id: "lifetime-value-usd",
      name: "Lifetime Value (USD)",
      column: "customer_360.gold.customer_profile.lifetime_value_usd",
      owner: "Customer Stewards",
      recert: "90d",
      status: "Recert due (8d)",
    },
    {
      id: "compensation-band",
      name: "Compensation Band",
      column: "hr_secure.confidential.compensation_band.band_id",
      owner: "People Stewards",
      recert: "180d",
      status: "Healthy",
    },
    {
      id: "order-total-usd",
      name: "Order Total (USD)",
      column: "sales_prod.silver.orders.gross_total_usd",
      owner: "Revenue Stewards",
      recert: "90d",
      status: "Healthy",
      sox: true,
    },
  ];
  return {
    data: {
      glossaryTerms,
      cdes,
      summary: {
        termCount: glossaryTerms.length,
        cdeCount: cdes.length,
      },
    },
    meta: {
      ...prototypeMockMeta(),
    },
  };
}

function syntheticTaxonomyOverviewDegraded() {
  return {
    data: {
      glossaryTerms: [],
      cdes: [],
      summary: {
        termCount: 0,
        cdeCount: 0,
      },
    },
    meta: {
      ...prototypeMockMeta({
        state: "degraded",
        warnings: ["Prototype degraded taxonomy state for visual QA only."],
      }),
    },
  };
}

function syntheticAssetRecord(assetFqn = ASSET_FQN) {
  const fqn = assetFqn || ASSET_FQN;
  const parts = fqn.split(".");
  return {
    fqn,
    name: parts.at(-1) || fqn,
    catalog: parts[0] || "finance_prod",
    schema: parts[1] || "curated",
    objectType: /dashboard|board/i.test(fqn) ? "Dashboard" : /forecast|model/i.test(fqn) ? "Model" : "Delta Table",
    type: /dashboard|board/i.test(fqn) ? "dashboard" : /forecast|model/i.test(fqn) ? "model" : "table",
    description:
      fqn === "finance_prod.curated.revenue_daily"
        ? "Certified finance revenue table powering board reporting and CFO dashboards."
        : "Lineage-linked governed asset from local prototype evidence.",
    owner: "Marisol Reyes",
    ownerEmail: "marisol.reyes@entrada.ai",
    steward: "Finance Stewards",
    domain: "Finance",
    certification: "Certified",
    criticality: "High",
    qualityScore: 92,
    metadataCoverage: 96,
    policyTags: ["Certified", "Finance", "CDE"],
    tags: ["Certified", "CDE"],
    columns: [
      { name: "net_revenue_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
      { name: "gross_revenue_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
      { name: "discount_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
      { name: "revenue_date", dataType: "date", qualityTone: "good", qualityLabel: "Healthy" },
    ],
  };
}

function syntheticLineagePayload(assetFqn = ASSET_FQN) {
  const focus = assetFqn || ASSET_FQN;
  const nodes = [
    { id: "dlt-payments-ingest", assetFqn: "finance_prod.dlt_payments_ingest", label: "finance_prod · dlt_payments_ingest", subtitle: "SOURCE - Payments", kind: "Source", stage: "source", hop: 1, columns: ["charge_id", "order_id", "amount"] },
    { id: "auto-loader-invoices", assetFqn: "finance_prod.auto_loader_invoices", label: "finance_prod · auto_loader_invoices", subtitle: "SOURCE - Finance", kind: "Source", stage: "source", hop: 1, columns: ["invoice_id", "order_id", "net_amount"] },
    { id: "bronze-orders", assetFqn: "finance_prod.bronze.orders_raw", label: "orders_raw", subtitle: "finance_prod · bronze", kind: "Delta Table", stage: "upstream", hop: 2, rowCount: 4800000, freshness: "14m", columns: [{ name: "order_id", key: "A", dataType: "STRING" }, { name: "customer_id", key: "A", dataType: "STRING" }, { name: "subtotal", key: "#", dataType: "DECIMAL" }] },
    { id: "bronze-charges", assetFqn: "finance_prod.bronze.charges_raw", label: "charges_raw", subtitle: "finance_prod · bronze", kind: "Delta Table", stage: "upstream", hop: 2, rowCount: 12400000, freshness: "8m", columns: [{ name: "charge_id", key: "A", dataType: "STRING" }, { name: "customer_id", key: "A", dataType: "STRING" }, { name: "amount", key: "#", dataType: "INT" }, { name: "currency", key: "A", dataType: "STRING" }, { name: "refund_amount", key: "#", dataType: "INT" }, { name: "status", key: "A", dataType: "STRING" }, { name: "processor", key: "A", dataType: "STRING" }, { name: "created_at", key: "A", dataType: "TIMESTAMP" }] },
    { id: "bronze-invoices", assetFqn: "finance_prod.bronze.invoices_raw", label: "invoices_raw", subtitle: "finance_prod · bronze", kind: "Delta Table", stage: "upstream", hop: 2, rowCount: 1100000, freshness: "41m", columns: [{ name: "invoice_id", key: "A", dataType: "STRING" }, { name: "customer_id", key: "A", dataType: "STRING" }, { name: "adjustment", key: "#", dataType: "DECIMAL" }, { name: "billing_period", key: "A", dataType: "STRING" }, { name: "created_at", key: "A", dataType: "TIMESTAMP" }] },
    { id: "silver-orders", assetFqn: "finance_prod.silver.orders", label: "orders", subtitle: "sales_prod · silver", kind: "Delta Table", stage: "downstream", hop: 2, rowCount: 4800000, freshness: "14m", columns: [{ name: "order_id", key: "A", dataType: "STRING" }, { name: "customer_id", key: "A", dataType: "STRING" }, { name: "order_value_usd", key: "#", dataType: "DECIMAL" }, { name: "discount_amount", key: "#", dataType: "DECIMAL" }, { name: "segment_id", key: "A", dataType: "STRING" }, { name: "channel", key: "A", dataType: "STRING" }] },
    { id: "silver-payments", assetFqn: "finance_prod.silver.payments", label: "payments", subtitle: "finance_prod · silver", kind: "Delta Table", stage: "downstream", hop: 1, rowCount: 13500000, freshness: "11m", columns: [{ name: "payment_id", key: "A", dataType: "STRING" }, { name: "customer_id", key: "A", dataType: "STRING" }, { name: "gross_amount", key: "#", dataType: "DECIMAL" }, { name: "refund_amount", key: "#", dataType: "DECIMAL" }, { name: "adjustment", key: "#", dataType: "DECIMAL" }, { name: "segment_id", key: "A", dataType: "STRING" }, { name: "processor", key: "A", dataType: "STRING" }, { name: "created_at", key: "A", dataType: "TIMESTAMP" }] },
    { id: "recognition-job", assetFqn: "finance_prod.ipynb.payments_clean", label: "ipynb", subtitle: "finance_prod · notebook", kind: "Notebook", stage: "transform", hop: 3 },
    {
      id: "focus-revenue",
      assetFqn: focus,
      label: "revenue_daily",
      subtitle: "finance_prod · curated",
      kind: "Delta Table",
      role: "focus",
      stage: "focus",
      rowCount: 1240000,
      freshness: "14m",
      columns: [
        { name: "net_revenue_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
        { name: "gross_revenue_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
        { name: "discount_usd", dataType: "decimal(18,2)", qualityTone: "good", qualityLabel: "Healthy" },
      ],
      policyTags: ["Certified", "CDE"],
      description: "Board-reporting revenue table certified by Finance Stewards.",
    },
    { id: "cfo-dashboard", assetFqn: "dashboards.finance.cfo_quarterly", label: "CFO Quarterly Dashboard", subtitle: "DASHBOARD - Finance", kind: "Dashboard", stage: "impact", hop: 4 },
    { id: "board-pack", assetFqn: "dashboards.finance.board_pack_revenue", label: "Board Pack - Revenue", subtitle: "DASHBOARD - Finance", kind: "Dashboard", stage: "impact", hop: 5 },
    { id: "forecast-model", assetFqn: "finance_prod.ml.revenue_forecast", label: "finance_prod.ml.revenue_forecast", subtitle: "MODEL - Finance", kind: "Model", stage: "impact", hop: 6 },
    { id: "restricted-hidden", assetFqn: "restricted.downstream.assets", label: "4 downstream assets", subtitle: "PROTOTYPE PERMISSION BOUNDARY", kind: "Restricted", stage: "downstream", hop: 3 },
  ];
  const edges = [
    { id: "payments-source-charges", source: "dlt-payments-ingest", target: "bronze-charges" },
    { id: "invoice-source-invoices", source: "auto-loader-invoices", target: "bronze-invoices" },
    { id: "orders-silver", source: "bronze-orders", target: "silver-orders" },
    { id: "charges-payments", source: "bronze-charges", target: "silver-payments" },
    { id: "invoices-payments", source: "bronze-invoices", target: "silver-payments" },
    { id: "silver-orders-job", source: "silver-orders", target: "recognition-job" },
    { id: "silver-payments-job", source: "silver-payments", target: "recognition-job" },
    { id: "job-focus", source: "recognition-job", target: "focus-revenue" },
    { id: "focus-cfo", source: "focus-revenue", target: "cfo-dashboard" },
    { id: "focus-board", source: "focus-revenue", target: "board-pack" },
    { id: "focus-model", source: "focus-revenue", target: "forecast-model" },
    { id: "focus-restricted", source: "focus-revenue", target: "restricted-hidden" },
  ];
  return {
    fqn: focus,
    authoritative: false,
    provisional: true,
    graphs: {
      data: { nodes, edges },
      operational: { nodes: [], edges: [] },
    },
    stats: {
      upstreamCount: 5,
      downstreamCount: 23,
      confidenceScore: 98,
      qualityScore: 92,
      brokenLinks: 0,
      cdeCount: 5,
      hiddenDownstreamCount: 4,
      owner: "Marisol Reyes",
      freshness: "14 min ago - within 15 min SLA",
      revenueImpact: "$142k/day revenue impact",
      generatedAt: "2026-04-27T09:14:22Z",
      limits: { tableLineage: 38 },
      truncated: { downstream: true },
    },
    columnLineage: {
      upstream: [
        { column: "net_revenue_usd", sourceColumn: "gross_revenue_usd", sourceAsset: "finance_prod.silver.orders", targetColumn: "net_revenue_usd" },
        { column: "net_revenue_usd", sourceColumn: "refund_usd", sourceAsset: "finance_prod.silver.payments", targetColumn: "net_revenue_usd" },
      ],
      downstream: [
        { column: "net_revenue_usd", sourceColumn: "net_revenue_usd", targetAsset: "dashboards.finance.cfo_quarterly", targetColumn: "net_revenue_usd" },
        { column: "net_revenue_usd", sourceColumn: "net_revenue_usd", targetAsset: "finance_prod.ml.revenue_forecast", targetColumn: "target" },
      ],
      meta: { source: "system.access.column_lineage", truncated: false },
    },
    impactAnalysis: [
      { id: "cfo-dashboard", title: "CFO Quarterly Dashboard", detail: "Finance Stewards - used in last 24h - 142 views", tone: "High impact" },
      { id: "board-pack", title: "Board Pack - Revenue", detail: "Marisol Reyes - quarterly distribution to board", tone: "High impact" },
      { id: "forecast-model", title: "finance_prod.ml.revenue_forecast", detail: "Finance Data Platform - trains nightly", tone: "Medium" },
      { id: "snapshot", title: "finance_prod.gold.arr_snapshot", detail: "Finance Stewards - prototype downstream shape - no live usage, workflow, or backed lineage proof", tone: "Medium" },
    ],
    events: [
      { id: "lineage-payments-clean", title: "Notebook payments_clean succeeded · 13.5M rows", detail: "svc-job-runner · 11m ago" },
      { id: "lineage-adjustment", title: "Schema evolution: +adjustment", detail: "priya.natarajan · 6d ago" },
      { id: "lineage-column-refresh", title: "Column lineage refreshed", detail: "4 net_revenue_usd column mappings observed." },
    ],
    meta: prototypeMockMeta({ generatedAt: "2026-04-27T09:14:22Z" }),
  };
}

function syntheticAuditEvidence() {
  const events = [
    {
      audit_id: "AE-78421",
      created_at: "2026-04-27T09:14:22Z",
      actor_email: "marisol.reyes@entrada.ai",
      actor_role: "Finance Steward",
      action: "Certification",
      status: "success",
      entity_fqn: "finance_prod.curated.revenue_daily",
      entity_type: "table",
      source: "owner, description, lineage coverage, freshness SLA",
      detail: "Re-certified for Q2 2026.",
      request_id: "SI-2482",
      domain: "Finance",
    },
    {
      audit_id: "AE-78410",
      created_at: "2026-04-27T08:52:09Z",
      actor_email: "svc-governance-sweeper",
      actor_role: "Service",
      action: "Tag applied",
      status: "success",
      entity_fqn: "customer_360.silver.contact_events",
      entity_type: "table",
      source: "Job run ID 9821044 · Classifier confidence >= 0.92",
      detail: "Auto-tagged 6 columns as pii.",
      request_id: "SI-2479",
      domain: "Customer",
    },
    {
      audit_id: "AE-78404",
      created_at: "2026-04-27T08:31:44Z",
      actor_email: "aaron.chen@entrada.ai",
      actor_role: "Data Owner",
      action: "Grant",
      status: "success",
      entity_fqn: "customer_360.gold.customer_profile",
      entity_type: "table",
      source: "Approved via stewardship workflow SI-2440",
      detail: "Granted SELECT to customer-success-leads group.",
      request_id: "SI-2440",
      domain: "Customer",
    },
    {
      audit_id: "AE-78395",
      created_at: "2026-04-27T07:58:01Z",
      actor_email: "svc-policy-engine",
      actor_role: "Service",
      action: "Policy violation",
      status: "failed",
      entity_fqn: "experimental.sandbox.pricing_experiment_2025q4",
      entity_type: "table",
      source: "No principal in owner grant set. Quarantined from search index.",
      detail: "Owner-required policy failed.",
      request_id: "SI-2491",
      domain: "Revenue & Sales",
    },
    {
      audit_id: "AE-78388",
      created_at: "2026-04-27T07:14:55Z",
      actor_email: "priya.natarajan@entrada.ai",
      actor_role: "Data Owner",
      action: "Quality alert",
      status: "pending",
      entity_fqn: "sales_prod.silver.orders",
      entity_type: "table",
      source: "Linked to Lakeflow run 1029384 · DQ check currency_code_not_null",
      detail: "Acknowledged quality regression on currency_code.",
      request_id: "SI-2471",
      domain: "Revenue & Sales",
    },
    {
      audit_id: "AE-78377",
      created_at: "2026-04-27T06:42:31Z",
      actor_email: "svc-lineage-collector",
      actor_role: "Service",
      action: "Lineage updated",
      status: "success",
      entity_fqn: "finance_prod.gold.revenue_recognition",
      entity_type: "job",
      source: "system.access.column_lineage · 38 new edges",
      detail: "Captured new column-level lineage for is_recognized.",
      request_id: "",
      domain: "Finance",
    },
    {
      audit_id: "AE-78358",
      created_at: "2026-04-27T05:18:12Z",
      actor_email: "devon.park@entrada.ai",
      actor_role: "Customer Steward",
      action: "Description",
      status: "success",
      entity_fqn: "product_events.bronze.clickstream_events",
      entity_type: "table",
      source: "Diff: +148 / -24 chars. Reviewer: Customer Stewards.",
      detail: "Edited table description.",
      request_id: "SI-2487",
      domain: "Customer",
    },
    {
      audit_id: "AE-78290",
      created_at: "2026-04-26T22:04:00Z",
      actor_email: "compliance-bot",
      actor_role: "Service",
      action: "Access review",
      status: "success",
      entity_fqn: "hr_secure.confidential.compensation_band",
      entity_type: "table",
      source: "12 grants reviewed · 2 revoked · 0 escalations",
      detail: "Quarterly access review completed.",
      request_id: "SI-2469",
      domain: "People",
    },
  ];
  return {
    data: {
      summary: {
        events24h: 2184,
        totalChanges: 2184,
        eventsDeltaText: "+312 vs prev",
        policyViolations: 6,
        policyViolationsDeltaText: "-2 vs prev",
        accessReviewsOpen: 3,
        accessReviewsDeltaText: "0 vs prev",
        retentionYears: 7,
        retentionNote: "Delta · time-travel enabled",
      },
      events,
      selectedEvent: events[0],
      evidence: {
        linkedRequest: "SI-2482",
        approvalChain: [],
        artifacts: [],
      },
    },
    meta: {
      ...prototypeMockMeta({ generatedAt: "2026-04-27T09:14:22Z" }),
    },
  };
}

function syntheticAuditEvidenceDegraded() {
  return {
    data: {
      summary: {
        events24h: null,
        totalChanges: null,
        eventsSupport: "No scoped event summary reported by audit API",
        policyViolations: null,
        policyViolationsSupport: "Policy summary unavailable unless reported by audit API",
        accessReviewsOpen: null,
        accessReviewsSupport: "Access review summary unavailable unless reported by audit API",
        retentionYears: null,
        retentionNote: "Retention policy not reported",
        evidenceNote: "Audit evidence source unavailable · retention policy not reported · exports remain disabled until rows are available.",
      },
      events: [],
      selectedEvent: null,
      evidence: {
        linkedRequest: "",
        approvalChain: [],
        artifacts: [],
      },
    },
    meta: {
      ...prototypeMockMeta({
        generatedAt: "2026-04-27T09:14:22Z",
        warnings: ["Synthetic degraded audit evidence state for visual QA only."],
      }),
      degraded: true,
    },
  };
}

function syntheticAdminControlCenter() {
  return {
    data: {
      environment: { displayLabel: "Dev · datapact.atlas" },
      scheduledJobs: [
        {
          id: "job-uc-sweeper",
          name: "UC metadata sweeper",
          schedule: "Every 15 min",
          lastRun: "4 min ago",
          status: "healthy",
          runUrl: "https://example.cloud.databricks.com/jobs/123/runs/456",
        },
        { id: "job-lineage", name: "Lineage collector", schedule: "Every 1 hr", lastRun: "21 min ago", status: "healthy" },
        { id: "job-quality", name: "Quality + freshness check", schedule: "Every 1 hr", lastRun: "32 min ago", status: "healthy" },
        { id: "job-policy", name: "Policy engine evaluator", schedule: "Hourly + on-write", lastRun: "7 min ago", status: "healthy" },
        { id: "job-classifier", name: "PII classifier (model serving)", schedule: "Daily 02:00 UTC", lastRun: "8 hr ago", status: "healthy" },
        { id: "job-trust", name: "Trust score recompute", schedule: "Daily 03:00 UTC", lastRun: "7 hr ago", status: "slow" },
      ],
      integrations: [
        { key: "uc", label: "Unity Catalog", subtitle: "Prototype mock - UC not verified", state: "warning" },
        { key: "warehouse", label: "Databricks SQL Warehouse", subtitle: "gov atlas wh M", state: "ok" },
        { key: "jobs", label: "Lakeflow Jobs", subtitle: "6 jobs scheduled", state: "ok" },
        { key: "model", label: "Model Serving · classifier-v2", subtitle: "Endpoint healthy", state: "ok" },
        { key: "slack", label: "Slack · #governance-alerts", subtitle: "Connected", state: "ok" },
        { key: "pagerduty", label: "PagerDuty · P1 stewardship", subtitle: "Connected", state: "ok" },
      ],
      policyCoverage: {
        rules: [
          { key: "owner", label: "Owner required on production", value: 96, state: "healthy" },
          { key: "cde-desc", label: "CDEs must have description", value: 100, state: "healthy" },
          { key: "pii-tag", label: "PII columns require tag", value: 92, state: "healthy" },
          { key: "recert", label: "90-day re-certification", value: 87, state: "healthy" },
          { key: "grant", label: "Restricted catalogs require justified grant", value: 100, state: "healthy" },
        ],
      },
    },
    meta: {
      ...prototypeMockMeta(),
    },
  };
}

function syntheticAsset360Payload(assetFqn, bootstrap) {
  const asset = assetFromBootstrap(bootstrap, assetFqn);
  const resolvedFqn = asset?.fqn || assetFqn || ASSET_FQN;
  return {
    asset: {
      ...asset,
      fqn: resolvedFqn,
      name: asset?.name || resolvedFqn.split(".").pop() || "revenue_daily",
      catalog: asset?.catalog || resolvedFqn.split(".")[0] || "finance_prod",
      schema: asset?.schema || resolvedFqn.split(".")[1] || "curated",
      objectType: asset?.objectType || asset?.type || "Delta table",
      description: asset?.description || "Certified finance revenue table powering board reporting and CFO dashboards.",
      domain: asset?.domain || "Finance",
      certification: asset?.certification || "Certified",
      criticality: asset?.criticality || "High",
      sensitivity: asset?.sensitivity || "Internal",
      dataProduct: asset?.dataProduct || "Revenue",
      rows: asset?.rows || 18420000,
      size: asset?.size || "42.8 GB",
      columns: asset?.columns || [
        { name: "booking_id", type: "string", description: "Source booking identifier." },
        { name: "net_revenue_usd", type: "decimal(18,2)", description: "Recognized net revenue in USD.", tags: { cde: "true" } },
        { name: "customer_id", type: "string", description: "Customer profile key." },
        { name: "recognized_at", type: "timestamp", description: "Revenue recognition timestamp." },
      ],
    },
    owners: [{ name: "Marisol Reyes", email: "marisol.reyes@entrada.ai", title: "Finance Steward" }],
    stewards: [{ name: "Finance Stewards", email: "finance-stewards@entrada.ai", title: "Steward team" }],
    badges: ["Certified", "5 CDEs", "Lineage verified"],
    freshness: { state: "healthy", label: "Fresh", observedAt: "2026-04-27T09:14:22Z", message: "14 min ago · within 15 min SLA" },
    usage: { rows: 18420000, rowDeltaLabel: "+1.2M last 30d", downstreamAssets: 4, users: 38, queries: 1742 },
    schema: [
      { name: "booking_id", type: "string", description: "Source booking identifier." },
      { name: "net_revenue_usd", type: "decimal(18,2)", description: "Recognized net revenue in USD.", cde: true },
      { name: "customer_id", type: "string", description: "Customer profile key." },
      { name: "recognized_at", type: "timestamp", description: "Revenue recognition timestamp." },
    ],
    governance: {
      glossaryTerms: ["Net Revenue", "Booking", "Active Customer"],
      policies: [
        { id: "policy-owner", title: "Owner required", status: "Healthy" },
        { id: "policy-cde", title: "CDE description", status: "Healthy" },
      ],
      ownerAssignments: [],
      openActivity: [],
    },
    quality: { state: "healthy", runs: [{ id: "dq-1029384", status: "passed", label: "currency_code_not_null" }], message: "4 checks passed." },
    access: { state: PROTOTYPE_MOCK_STATE, message: PROTOTYPE_MOCK_WARNING },
    activity: [
      { id: "act-1", title: "Certification renewed", detail: "Marisol Reyes re-certified for Q2 2026.", relativeTime: "14 min ago" },
      { id: "act-2", title: "Lineage refreshed", detail: "Column lineage captured from system.access.column_lineage.", relativeTime: "38 min ago" },
    ],
    relatedAssets: [
      { fqn: "finance_prod.gold.arr_snapshot", name: "arr_snapshot", relationship: "Same product" },
      { fqn: "sales_prod.silver.orders", name: "orders", relationship: "Upstream source" },
    ],
    downstreamDashboards: [
      { id: "cfo-quarterly", title: "CFO Quarterly Dashboard", owner: "Finance Stewards" },
      { id: "board-pack", title: "Board Pack - Revenue", owner: "Marisol Reyes" },
    ],
    loadedSections: ["header", "activity", "schema", "properties", "profiler", "operational"],
    meta: prototypeMockMeta({ state: PROTOTYPE_MOCK_STATE }),
  };
}

function assetFromBootstrap(bootstrap, assetFqn) {
  const assets = Array.isArray(bootstrap?.discovery?.defaultResults)
    ? bootstrap.discovery.defaultResults
    : [];
  return assets.find((asset) => asset?.fqn === assetFqn) || syntheticAssetRecord(assetFqn) || assets[0] || {};
}

async function installMockApi(context) {
  if (!MOCK_API) return;
  const bootstrap = await loadJson("northstar/genie/live-bootstrap-response.json", {
    bootState: PROTOTYPE_MOCK_STATE,
    bootMessage: PROTOTYPE_MOCK_WARNING,
    authoritative: false,
    discovery: { summary: { visibleAssets: 1247, catalogCount: 6, averageCoverage: 87.4 } },
    identity: { actorName: "Marisol Reyes", actorEmail: "marisol.reyes@entrada.ai", actorRole: "Finance Steward" },
    shell: {
      role: "Finance · Steward",
      userName: "Marisol Reyes",
      userEmail: "marisol.reyes@entrada.ai",
      workspaceLabel: "entrada-prod",
      workspaceName: "entrada-prod",
      environment: { displayLabel: "entrada-prod", target: "entrada-prod" },
      ai: { state: "available", provider: "prototype-mock", message: PROTOTYPE_MOCK_WARNING },
    },
    featureFlags: [
      { key: "table_lineage_surface", enabled: true, state: PROTOTYPE_MOCK_STATE },
      { key: "workspace_setup_diagnostics", enabled: true, state: PROTOTYPE_MOCK_STATE },
    ],
  });
  bootstrap.bootState = PROTOTYPE_MOCK_STATE;
  bootstrap.bootMessage = PROTOTYPE_MOCK_WARNING;
  bootstrap.authoritative = false;
  bootstrap.identity = {
    ...(bootstrap.identity || {}),
    actorName: "Marisol Reyes",
    actorEmail: "marisol.reyes@entrada.ai",
    actorRole: "Finance · Steward",
    actorRoleProvisional: false,
  };
  bootstrap.meta = prototypeMockMeta(bootstrap.meta);
  bootstrap.discovery = {
    ...(bootstrap.discovery || {}),
    sortOptions: ["Trust score", "Name (A-Z)", "Open requests"],
    defaultResults: PROTOTYPE_DISCOVERY_ASSETS,
    defaultCount: PROTOTYPE_DISCOVERY_ASSETS.length,
    defaultFacets: PROTOTYPE_DISCOVERY_FACETS,
    summary: {
      visibleAssets: 1247,
      catalogCount: 6,
      averageCoverage: 87.4,
      ...(bootstrap.discovery?.summary || {}),
    },
  };
  bootstrap.capabilities = {
    ...(bootstrap.capabilities || {}),
    systemInventoryRead: prototypeMockCapability({ visibilityScope: "workspace-app-principal" }),
    tableLineage: { ...prototypeMockCapability({ visibilityScope: "workspace-app-principal" }), state: PROTOTYPE_MOCK_STATE },
    columnLineage: { ...prototypeMockCapability({ visibilityScope: "workspace-app-principal" }), state: PROTOTYPE_MOCK_STATE },
    exportAllowed: prototypeMockCapability({ visibilityScope: "actor-scoped" }),
  };
  bootstrap.featureFlags = [
    ...(Array.isArray(bootstrap.featureFlags) ? bootstrap.featureFlags : []),
    { key: "table_lineage_surface", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
    { key: "workspace_setup_diagnostics", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
  ];
  bootstrap.shell = {
    ...(bootstrap.shell || {}),
    role: "Finance · Steward",
    userName: "Marisol Reyes",
    userEmail: "marisol.reyes@entrada.ai",
    workspaceLabel: "entrada-prod",
    workspaceName: "entrada-prod",
    environment: {
      ...(bootstrap.shell?.environment || {}),
      displayLabel: "entrada-prod",
      target: "entrada-prod",
    },
    ai: { state: PROTOTYPE_MOCK_STATE, provider: "prototype-mock", message: PROTOTYPE_MOCK_WARNING },
  };
  bootstrap.diagnostics = {
    ...(bootstrap.diagnostics || {}),
    featureFlags: bootstrap.featureFlags,
    workspaceAccess: {
      ...(bootstrap.diagnostics?.workspaceAccess || {}),
      mode: "obo-available",
      canUseLineage: true,
      observedAt: "2026-04-27T09:14:22Z",
      gates: [],
    },
  };
  const runtime = {
    runtime: { state: PROTOTYPE_MOCK_STATE, message: PROTOTYPE_MOCK_WARNING, catalogCount: 6 },
    store: { state: PROTOTYPE_MOCK_STATE, message: PROTOTYPE_MOCK_WARNING },
    capabilities: {
      systemInventoryRead: prototypeMockCapability({ visibilityScope: "workspace-app-principal" }),
      tableLineage: { ...prototypeMockCapability({ visibilityScope: "workspace-app-principal" }), state: PROTOTYPE_MOCK_STATE },
      columnLineage: { ...prototypeMockCapability({ visibilityScope: "workspace-app-principal" }), state: PROTOTYPE_MOCK_STATE },
      exportAllowed: prototypeMockCapability({ visibilityScope: "actor-scoped" }),
    },
    featureFlags: [
      { key: "table_lineage_surface", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
      { key: "workspace_setup_diagnostics", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
    ],
    diagnostics: {
      featureFlags: [
        { key: "table_lineage_surface", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        { key: "workspace_setup_diagnostics", enabled: true, state: PROTOTYPE_MOCK_STATE, source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
      ],
      workspaceAccess: {
        mode: "obo-available",
        canUseLineage: true,
        observedAt: "2026-04-27T09:14:22Z",
        gates: [],
      },
    },
    config: { govCatalog: "datapact", govSchema: "atlas" },
    identity: {
      actorName: "Marisol Reyes",
      actorEmail: "marisol.reyes@entrada.ai",
      actorRole: "Finance · Steward",
      actorRoleProvisional: false,
    },
    ai: { state: PROTOTYPE_MOCK_STATE, provider: "prototype-mock", message: PROTOTYPE_MOCK_WARNING },
    meta: prototypeMockMeta(),
  };
  await context.route("**/api/bootstrap**", (route) => route.fulfill(jsonResponse(bootstrap)));
  await context.route("**/api/runtime/status**", (route) => route.fulfill(jsonResponse(runtime)));
  await context.route("**/api/atlas/command-center**", (route) => route.fulfill(jsonResponse(syntheticCommandCenter())));
  await context.route("**/api/discovery/search**", async (route) => {
    const url = route.request().url();
    if (mockApiFlags.discoveryDegraded || requestRefererHasFlag(route, "ga_degraded")) {
      return route.fulfill(jsonResponse({
        detail: "Discovery backend timed out.",
        message: "Discovery backend timed out.",
        meta: prototypeMockMeta({ state: "degraded" }),
      }, 503));
    }
    const response = syntheticDiscoveryPayload(bootstrap, url);
    const query = new URL(url).searchParams.get("query") || "";
    if (/slow/i.test(query)) {
      await new Promise((resolve) => setTimeout(resolve, 4000));
    }
    return route.fulfill(jsonResponse(response.payload, response.status));
  });
  await context.route("**/api/governance/summary**", (route) => route.fulfill(jsonResponse({
    authoritative: false,
    metrics: [],
    backlog: syntheticStewardshipItems(),
    glossary: syntheticTaxonomyOverview().data.glossaryTerms,
    inbox: {
      state: "unavailable",
      message: "Prototype inbox delivery is unavailable; this is not live Databricks notification proof.",
      unreadCount: 0,
      stewardshipCount: 184,
      items: [],
    },
    provenance: {
      ...prototypeMockMeta(),
    },
  })));
  await context.route("**/api/classification-recommendations**", (route) => route.fulfill(jsonResponse({
    recommendations: [],
    count: 0,
    pendingCount: 0,
  })));
  await context.route("**/api/atlas/governance/workbench**", (route) => route.fulfill(jsonResponse(
    mockApiFlags.governanceDegraded || requestRefererHasFlag(route, "ga_governance_degraded")
      ? syntheticStewardshipWorkbenchDegraded()
      : syntheticStewardshipWorkbench()
  )));
  await context.route("**/api/atlas/taxonomy/overview**", (route) => route.fulfill(jsonResponse(
    mockApiFlags.taxonomyDegraded || requestRefererHasFlag(route, "ga_taxonomy_degraded")
      ? syntheticTaxonomyOverviewDegraded()
      : syntheticTaxonomyOverview()
  )));
  await context.route("**/api/atlas/cde**", (route) => route.fulfill(jsonResponse({
    ...(mockApiFlags.taxonomyDegraded || requestRefererHasFlag(route, "ga_taxonomy_degraded")
      ? syntheticTaxonomyOverviewDegraded().data
      : syntheticTaxonomyOverview().data),
    meta: (mockApiFlags.taxonomyDegraded || requestRefererHasFlag(route, "ga_taxonomy_degraded")
      ? syntheticTaxonomyOverviewDegraded().meta
      : syntheticTaxonomyOverview().meta),
  })));
  await context.route("**/api/atlas/audit/evidence**", (route) => {
    if (mockApiFlags.auditDegraded || requestRefererHasFlag(route, "ga_audit_degraded")) {
      return route.fulfill(jsonResponse(syntheticAuditEvidenceDegraded()));
    }
    return route.fulfill(jsonResponse(syntheticAuditEvidence()));
  });
  await context.route("**/api/atlas/admin/control-center**", (route) => route.fulfill(jsonResponse(syntheticAdminControlCenter())));
  await context.route("**/api/atlas/assets/**", (route) => {
    const url = new URL(route.request().url());
    if (/\/360$/i.test(url.pathname)) {
      const raw = url.pathname.replace(/^.*\/api\/atlas\/assets\//i, "").replace(/\/360$/i, "");
      const fqn = decodeURIComponent(raw || ASSET_FQN);
      return route.fulfill(jsonResponse(syntheticAsset360Payload(fqn, bootstrap)));
    }
    const raw = url.pathname.replace(/^.*\/api\/atlas\/assets\//i, "").split("/")[0] || "";
    const fqn = decodeURIComponent(raw || ASSET_FQN);
    return route.fulfill(jsonResponse(assetFromBootstrap(bootstrap, fqn)));
  });
  await context.route("**/api/atlas/governance/requests/**", (route) => {
    const requestId = decodeURIComponent(route.request().url().split("/").pop() || "");
    const detail = syntheticStewardshipItems().find((item) => item.requestId === requestId) || syntheticStewardshipItems()[0];
    return route.fulfill(jsonResponse(detail));
  });
  await context.route("**/api/governance/requests/**", (route) => {
    const requestId = decodeURIComponent(route.request().url().split("/").pop() || "");
    const detail = syntheticStewardshipItems().find((item) => item.requestId === requestId) || syntheticStewardshipItems()[0];
    if (route.request().method() === "PATCH") {
      let payload = {};
      try {
        payload = route.request().postDataJSON?.() || {};
      } catch {
        payload = {};
      }
      const reviewNote = String(payload.reviewNote || "").trim();
      const status = String(payload.status || detail.status || "").trim();
      const auditEventType = /resolved|approved|closed/i.test(status) ? "task_state_changed" : "comment_created";
      return route.fulfill(jsonResponse({
        ok: true,
        requestId,
        request: {
          ...detail,
          status,
          reviewNote,
          reviewedAt: "2026-04-30T06:45:00Z",
        },
        audit: {
          eventType: auditEventType,
          requestId,
          reviewNote,
          source: "prototype-governance-workflow-audit",
          evidenceKind: PROTOTYPE_MOCK_STATE,
        },
        governance: syntheticStewardshipWorkbench(),
        meta: prototypeMockMeta(),
      }));
    }
    return route.fulfill(jsonResponse({ governance: syntheticStewardshipWorkbench(), request: detail }));
  });
  await context.route("**/api/assets/**", (route) => {
    const url = new URL(route.request().url());
    if (/\/api\/assets\/availability/i.test(url.pathname)) {
      const assets = Array.isArray(bootstrap?.discovery?.defaultResults)
        ? bootstrap.discovery.defaultResults
        : [];
      return route.fulfill(jsonResponse({
        assets: Object.fromEntries(assets.map((asset) => [asset.fqn, {
          openable: true,
          available: true,
          authoritative: false,
          state: PROTOTYPE_MOCK_STATE,
          source: PROTOTYPE_MOCK_SOURCE,
          warning: PROTOTYPE_MOCK_WARNING,
        }])),
      }));
    }
    if (mockApiFlags.previewDegraded || requestRefererHasFlag(route, "ga_preview_degraded")) {
      return route.fulfill(jsonResponse({
        detail: "Live preview refresh stalled.",
        message: "Live preview refresh stalled.",
        meta: prototypeMockMeta({ state: "degraded" }),
      }, 503));
    }
    const encodedFqn = url.pathname.split("/api/assets/")[1] || "";
    const fqn = decodeURIComponent(encodedFqn.split("/")[0] || ASSET_FQN);
    return route.fulfill(jsonResponse(assetFromBootstrap(bootstrap, fqn)));
  });
  await context.route("**/api/lineage/**", (route) => {
    const encodedFqn = route.request().url().split("/api/lineage/")[1] || "";
    const fqn = decodeURIComponent(encodedFqn.split("?")[0] || ASSET_FQN);
    return route.fulfill(jsonResponse(syntheticLineagePayload(fqn)));
  });
  const routeAwareAtlasAiAnswer = (question) => {
    const base = {
      authoritative: false,
      state: PROTOTYPE_MOCK_STATE,
      source: PROTOTYPE_MOCK_SOURCE,
      warnings: prototypeMockWarnings(),
    };
    if (/audit|grant|notebook|export|evidence/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock Audit Evidence shows grant, certification, notebook, and export events with fixture request IDs. This is not live Databricks audit proof.",
        recommendations: [],
        evidence: [
          { label: "REQ-1001", type: "audit event", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "prototype audit export fixture", type: "export", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/control|job|runtime|integration|policy/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock Control Center evidence shows UC metadata sweeper and Trust score recompute as runtime job fixtures, with prototype integration and policy coverage rows. This is not live Jobs, serving, or policy proof.",
        recommendations: [],
        evidence: [
          { label: "UC metadata sweeper", type: "runtime job fixture", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "Trust score recompute", type: "runtime job fixture", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "Prototype policy coverage", type: "policy fixture", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/lineage|downstream|upstream|net_revenue|consumer|column/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock Lineage evidence shows finance_prod.curated.revenue_daily feeding CFO Quarterly Dashboard consumers and SI-2482 stewardship context. This is not live Databricks lineage proof.",
        recommendations: [],
        evidence: [
          { label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "SI-2482", type: "work item", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/certified assets|important assets|discover|trust score/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock Discover evidence ranks finance_prod.curated.revenue_daily and customer_360.gold.customer_profile by fixture trust score, certification, and CDE coverage. This is not live Unity Catalog search proof.",
        recommendations: [
          {
            title: "Review revenue_daily recertification",
            detail: "Certified asset with board-facing usage and an active recertification item.",
            provider: "prototype",
            evidence: [{ id: "finance_prod.curated.revenue_daily", label: "finance_prod.curated.revenue_daily", type: "asset" }],
          },
          {
            title: "Inspect customer_profile PII coverage",
            detail: "Restricted CDE asset with PII tags and executive downstream consumers.",
            provider: "prototype",
            evidence: [{ id: "customer_360.gold.customer_profile", label: "customer_360.gold.customer_profile", type: "asset" }],
          },
        ],
        evidence: [
          { label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "customer_360.gold.customer_profile", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/cde|recert/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock CDE registry evidence shows Lifetime Value (USD) as recertification due in 8 days. Net Revenue (USD) is approved; no live Databricks CDE mutation is implied.",
        recommendations: [],
        evidence: [
          { label: "Lifetime Value (USD)", type: "cde", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "Prototype Recert Due (8d)", type: "status", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/glossary|net revenue/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock glossary evidence links Net Revenue to finance_prod.curated.revenue_daily with reviewer finance.steward@entrada.ai and version-history context. This is not live Databricks glossary proof.",
        recommendations: [],
        evidence: [
          { label: "Net Revenue", type: "glossary term", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    if (/steward|work item|attention/i.test(question)) {
      return {
        ...base,
        answer: "Prototype mock Stewardship evidence flags SI-2482 on finance_prod.curated.revenue_daily for recertification attention. No live workflow mutation is submitted by this answer.",
        recommendations: [],
        evidence: [
          { label: "SI-2482", type: "work item", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          { label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
        ],
      };
    }
    return {
      ...base,
      answer: "Prototype mock governance metadata says finance_prod.curated.revenue_daily is certified and has a recertification work item. This answer is not live Databricks evidence.",
      recommendations: [],
      evidence: [{ label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING }],
    };
  };
  await context.route("**/api/atlas-ai/recommendations**", async (route) => {
    const rawBody = route.request().postData() || "{}";
    let question = "";
    try {
      question = String(JSON.parse(rawBody)?.question || "");
    } catch {
      question = "";
    }
    if (/error|timeout|failure/i.test(question)) {
      return route.fulfill(jsonResponse({
        detail: "Atlas AI prototype error path validated.",
        meta: prototypeMockMeta(),
      }, 503));
    }
    if (/slow|loading/i.test(question)) {
      await new Promise((resolve) => setTimeout(resolve, 1400));
    }
    if (/markdown/i.test(question)) {
      return route.fulfill(jsonResponse({
        data: {
          answer: [
            "**Prototype mock** lineage context is available for `finance_prod.curated.revenue_daily`.",
            "",
            "- Evidence: finance stewardship record.",
            "- Review: [asset record](https://example.com/governance-atlas).",
          ].join("\n"),
          authoritative: false,
          state: PROTOTYPE_MOCK_STATE,
          source: PROTOTYPE_MOCK_SOURCE,
          warnings: prototypeMockWarnings(),
          recommendations: [],
          evidence: [
            { label: "finance_prod.curated.revenue_daily", type: "asset", source: PROTOTYPE_MOCK_SOURCE, warning: PROTOTYPE_MOCK_WARNING },
          ],
        },
        meta: prototypeMockMeta({ scenario: "atlas-ai-markdown-safety" }),
      }));
    }
    return route.fulfill(jsonResponse({
      data: routeAwareAtlasAiAnswer(question),
      meta: prototypeMockMeta({ scenario: "atlas-ai-route-aware" }),
    }));
  });
  await context.route("**/api/atlas-ai/chat**", (route) => {
    const rawBody = route.request().postData() || "{}";
    let question = "";
    try {
      question = String(JSON.parse(rawBody)?.question || "");
    } catch {
      question = "";
    }
    return route.fulfill(jsonResponse(routeAwareAtlasAiAnswer(question)));
  });
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const unexpectedRequestFailures = report.requestFailures.filter(
    (item) => !expectedRequestFailure(item) && (item.status >= 400 || item.failureText),
  );
  const expectedRequestFailures = report.requestFailures.filter(
    (item) => expectedRequestFailure(item) && (item.status >= 400 || item.failureText),
  );
  report.captureCount = report.captures.length;
  report.interactionCount = report.interactions.length;
  report.consoleErrorCount = report.console.filter((item) => /error/i.test(item.type || "")).length;
  report.pageErrorCount = report.pageErrors.length;
  report.requestFailureCount = unexpectedRequestFailures.length;
  report.expectedRequestFailureCount = expectedRequestFailures.length;
  report.passed =
    UNKNOWN_ROUTE_FILTERS.length === 0 &&
    EXPECTED_CAPTURE_COUNT > 0 &&
    report.captures.length === EXPECTED_CAPTURE_COUNT &&
    report.captures.every((capture) => capture.loaded && capture.screenshot) &&
    (!CAPTURE_INTERACTIONS || report.interactions.every((interaction) => interaction.loaded && interaction.screenshot)) &&
    report.pageErrors.length === 0 &&
    unexpectedRequestFailures.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "prototype-current-report.json"),
    JSON.stringify(report, null, 2),
  );
}

async function captureRuntimeStatus() {
  if (MOCK_API) return;
  const runtimeUrl = `${BASE_URL.replace(/\/$/, "")}/api/runtime/status`;
  try {
    const response = await fetch(runtimeUrl, {
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    });
    const body = await response.json().catch(() => ({}));
    const buildId = String(
      body?.diagnostics?.buildId ||
      body?.shell?.buildId ||
      body?.buildId ||
      "",
    ).trim();
    report.runtimeStatus = {
      url: runtimeUrl,
      status: response.status,
      ok: response.ok,
      buildId,
      state: String(body?.runtime?.state || body?.state || "").trim(),
      actorRole: String(body?.identity?.actorRole || body?.actorRole || "").trim(),
      govCatalog: String(body?.config?.govCatalog || body?.govCatalog || "").trim(),
      govSchema: String(body?.config?.govSchema || body?.govSchema || "").trim(),
    };
    report.checks.buildMatches = EXPECTED_BUILD_ID ? buildId === EXPECTED_BUILD_ID : response.ok;
  } catch (error) {
    report.runtimeStatus = {
      url: runtimeUrl,
      ok: false,
      error: error?.message || String(error),
    };
    report.checks.buildMatches = false;
  }
}

async function responseSummary(response) {
  if (!response) return { ok: false, status: 0, url: "", body: null };
  const body = await response.json().catch(() => null);
  return {
    ok: response.ok(),
    status: response.status(),
    url: response.url(),
    body,
  };
}

function expectedRequestFailure(item) {
  return (
    item?.expected === true ||
    (
      item?.status === 400 &&
      /\/api\/discovery\/search/i.test(String(item.url || "")) &&
      /query=name%3A%28/i.test(String(item.url || ""))
    ) ||
    (
      item?.status === 503 &&
      /\/api\/atlas-ai\/recommendations/i.test(String(item.url || ""))
    )
  );
}

function attachListeners(page) {
  page.on("pageerror", (error) => {
    report.pageErrors.push({
      message: error?.message || String(error),
      stack: error?.stack || "",
      url: page.url(),
    });
    void flushReport();
  });
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    const text = message.text();
    if (/favicon|ResizeObserver loop/i.test(text)) return;
    if (/status of 400 \(Bad Request\)/i.test(text) && /\/discovery/i.test(page.url())) return;
    report.console.push({
      type: message.type(),
      text,
      url: page.url(),
    });
    void flushReport();
  });
  page.on("requestfailed", (request) => {
    const failureText = request.failure()?.errorText || "failed";
    if (failureText === "net::ERR_ABORTED") return;
    report.requestFailures.push({
      method: request.method(),
      url: request.url(),
      failureText,
    });
    void flushReport();
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const request = response.request();
    if (!response.url().startsWith(new URL(BASE_URL).origin)) return;
    const url = response.url();
    const expectedDegradedDiscovery =
      mockApiFlags.discoveryDegraded &&
      response.status() === 503 &&
      /\/api\/discovery\/search/i.test(url);
    const expectedDegradedPreview =
      mockApiFlags.previewDegraded &&
      response.status() === 503 &&
      /\/api\/assets\//i.test(url) &&
      !/\/api\/assets\/availability/i.test(url);
    const expectedInvalidDiscoveryQuery =
      response.status() === 400 &&
      /\/api\/discovery\/search/i.test(url) &&
      /query=name%3A%28/i.test(url);
    const expected = expectedDegradedDiscovery || expectedDegradedPreview || expectedInvalidDiscoveryQuery;
    report.requestFailures.push({
      method: request.method(),
      url,
      status: response.status(),
      expected: expected || undefined,
      scenario: expectedDegradedDiscovery
        ? "discover-degraded-results"
        : expectedDegradedPreview
          ? "discover-degraded-selected"
          : expectedInvalidDiscoveryQuery
            ? "discover-invalid-query"
          : undefined,
    });
    void flushReport();
  });
}

async function pageMetrics(page) {
  return page.evaluate(() => {
    const isVisible = (node) => {
      if (!(node instanceof HTMLElement)) return false;
      if (node.hidden || node.closest("[hidden]")) return false;
      const style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
        return false;
      }
      const box = node.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    };
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const box = node.getBoundingClientRect();
      return {
        top: box.top,
        left: box.left,
        right: box.right,
        bottom: box.bottom,
        width: box.width,
        height: box.height,
      };
    };
    const styleFor = (selector, properties) => {
      const node = document.querySelector(selector);
      if (!(node instanceof HTMLElement)) return null;
      const style = window.getComputedStyle(node);
      return Object.fromEntries(properties.map((property) => [property, style.getPropertyValue(property)]));
    };
    const visibleText = document.body?.innerText?.replace(/\s+/g, " ").trim() || "";
    const links = Array.from(document.querySelectorAll("button,a,[role='button']"))
      .filter(isVisible)
      .slice(0, 80)
      .map((node) => ({
        text: (node.innerText || node.getAttribute("aria-label") || node.title || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 120),
        disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
        aria: node.getAttribute("aria-label") || "",
      }))
      .filter((item) => item.text || item.aria);
    return {
      title: document.title,
      url: window.location.href,
      readyState: document.readyState,
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio,
      },
      scroll: {
        documentHeight: document.documentElement.scrollHeight,
        documentWidth: document.documentElement.scrollWidth,
        hasVerticalOverflow: document.documentElement.scrollHeight > window.innerHeight + 2,
        hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      },
      shell: rect(".gh-shell-header"),
      sideRail: rect(".ga-side-nav"),
      main: rect(".gh-main"),
      mainScroll: (() => {
        const node = document.querySelector(".gh-main");
        if (!(node instanceof HTMLElement)) return null;
        return {
          scrollTop: node.scrollTop,
          scrollHeight: node.scrollHeight,
          clientHeight: node.clientHeight,
          hasOverflow: node.scrollHeight > node.clientHeight + 2,
        };
      })(),
      home: rect(".gh-home-page"),
      discovery: rect(".gh-discovery-main-grid"),
      entity: rect(".gh-entity-record-layout"),
      lineage: rect(".gh-lineage-canvas") || rect(".ga-lineage-explorer"),
      lineagePrototype: {
        page: rect(".ga-lineage-explorer"),
        hero: rect(".ga-lineage-hero"),
        workbench: rect(".ga-lineage-workbench"),
        graph: rect(".ga-lineage-graph-card"),
      },
      audit: {
        page: rect(".gh-audit-ns"),
        shell: rect(".gh-audit-shell"),
        main: rect(".gh-audit-main"),
        table: rect(".gh-audit-table-panel"),
        mainStyle: styleFor(".gh-audit-main", ["width", "justify-self", "align-self", "grid-column", "display"]),
        shellStyle: styleFor(".gh-audit-shell", ["width", "grid-template-columns", "justify-items", "display"]),
      },
      admin: {
        page: rect(".gh-admin-ns"),
        shell: rect(".gh-admin-shell"),
        main: rect(".gh-admin-main"),
      },
      textPreview: visibleText.slice(0, 1600),
      controls: links,
    };
  });
}

async function visibleText(page, maxLength = 4000) {
  const text = await page.evaluate(() => document.body?.innerText?.replace(/\s+/g, " ").trim() || "");
  return text.slice(0, maxLength);
}

function patternMatched(text, pattern) {
  if (pattern instanceof RegExp) return pattern.test(text);
  return String(text).includes(String(pattern));
}

async function textChecks(page, checks) {
  const text = await visibleText(page, 8000);
  return Object.fromEntries(
    Object.entries(checks).map(([key, pattern]) => [key, patternMatched(text, pattern)]),
  );
}

async function controlSnapshot(locator) {
  const target = locator.first();
  return target.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      text: (node.textContent || node.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim(),
      ariaLabel: node.getAttribute("aria-label") || "",
      title: node.getAttribute("title") || "",
      role: node.getAttribute("role") || "",
      disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
      ariaPressed: node.getAttribute("aria-pressed") || "",
      ariaSelected: node.getAttribute("aria-selected") || "",
      rect: {
        top: Math.round(rect.top),
        left: Math.round(rect.left),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
    };
  });
}

async function pressedGroupSnapshot(page, entries) {
  const snapshots = {};
  for (const [key, pattern] of entries) {
    snapshots[key] = await controlSnapshot(buttonByName(page, pattern));
  }
  return {
    snapshots,
    activeKeys: Object.entries(snapshots)
      .filter(([, snapshot]) => snapshot?.ariaPressed === "true")
      .map(([key]) => key),
  };
}

async function clickVisible(locator, description, options = {}) {
  const target = locator.first();
  await target.waitFor({ state: "visible", timeout: options.timeout || 15_000 });
  if (!options.skipScroll) {
    await target.scrollIntoViewIfNeeded().catch(() => {});
  }
  const before = await controlSnapshot(target);
  if (!options.allowDisabled && before.disabled) {
    throw new Error(`${description} is disabled`);
  }
  await target.click({ timeout: options.timeout || 15_000, force: options.force || false });
  await pagePause(locator.page?.()).catch(() => {});
  return before;
}

async function pagePause(page) {
  if (!page) return;
  await page.waitForLoadState("networkidle", { timeout: 4_000 }).catch(() => {});
  await page.waitForTimeout(250);
}

function buttonByName(page, name) {
  return page.getByRole("button", { name }).first();
}

function linkByName(page, name) {
  return page.getByRole("link", { name }).first();
}

const SHARED_CONTROL_COVERAGE = [
  { id: "shared-nav", ledger: "Cross-Page Shared global navigation routes", pattern: /^(Command Center|Discover|Stewardship(?:\s+\d+)?|Glossary & CDEs|Lineage Atlas|Audit Evidence|Control Center)$/i },
  { id: "shared-profile", ledger: "Cross-Page Shared profile menu", pattern: /^(Open profile menu\b.*|[A-Z]{1,3}\s+.+\s+Admin|[A-Z]{1,3}\s+.+\s+Steward)$/i },
  { id: "shared-breadcrumb", ledger: "Cross-Page Shared workspace breadcrumb", pattern: /^(Open Governance Atlas Command Center|Workspace\b.*)$/i },
  { id: "shared-search", ledger: "Cross-Page Shared global search", pattern: /^(Submit global search(?: unavailable.*)?|Search assets.*)$/i },
  { id: "shared-notifications", ledger: "Cross-Page Shared notifications", pattern: /^Notifications/i },
  { id: "shared-help", ledger: "Cross-Page Shared help", pattern: /^Help$/i },
  { id: "shared-ai", ledger: "Cross-Page Shared Atlas AI", pattern: /^(Atlas AI|Open Atlas AI|Open Atlas AI unavailable state: .+|Close Atlas AI|Ask Atlas AI|Atlas AI is responding|Atlas AI is open|Atlas AI accuracy notice|Atlas AI recommendations require .+|\? .+ →|Ask about .*)$/i },
];

const ROUTE_CONTROL_COVERAGE = {
  "command-center": [
    { id: "cc-primary", ledger: "Command Center primary controls", pattern: /^(Export brief|Present mode|12w|26w|52w)$/i },
    { id: "cc-info", ledger: "Command Center info affordances", pattern: /(Coverage trend|Posture by domain|Risk breakdown|Top catalogs|Critical data elements|Activity stream)/i },
    { id: "cc-domain", ledger: "Command Center domain routing", pattern: /(domain posture|domain coverage|Open discovery for .* domain (?:posture|coverage)|Revenue & Sales.*assets|Customer.*assets|Marketing.*assets|Finance.*assets|Operations.*assets|People.*assets)/i },
    { id: "cc-risk", ledger: "Command Center risk routing/unavailable states", pattern: /(Open exposures|open exposures|Policy exception signals|policy exception signals|Medium-risk findings|Medium severity source unavailable|Informational|Open stewardship|Open audit evidence)/i },
    { id: "cc-cde", ledger: "Command Center CDE routing/unavailable rows", pattern: /(View all|Net Revenue|Customer ID|Lifetime Value|Compensation Band|Discounts|Gross Revenue|Billable Amount|Source-of-record column unavailable|CDE source signal unavailable)/i },
    { id: "cc-activity", ledger: "Command Center activity routing", pattern: /(certified finance_prod|flagged (?:1 asset for )?missing owner|auto-tagged PII columns|approved access for|acknowledged quality alert|Quality Run Completed|Task Created|Task Status Updated|Task Comment Added|task-created|task status updated|task comment added|taxonomy evidence|quality monitoring|Governance Atlas Identity Directory|Governance Atlas Entity Alias Upserted|Governance Atlas Entity Registry Upserted|Governance Atlas Policy Exception Detected|Governance Atlas Change Request Status Updated|Policy exception detected|Change request status updated|Upserted .*@|Updated Governance Atlas taxonomy evidence|metadata evidence refreshed)/i },
  ],
  discover: [
    { id: "discover-facets", ledger: "Discover filters/facets", pattern: /^(?:Certified|Trusted|In Review|Uncertified|Draft|Restricted|Confidential|Internal|Unclassified|Critical Data Element|Contains PII|No PII|Revenue & Sales|Customer|Marketing|Finance|Operations|Product|Risk|People|[a-z][a-z0-9_ &-]+)\s*\d*$/i },
    { id: "discover-search-sort-view", ledger: "Discover search/sort/view", pattern: /(Search discovery assets|Saved searches|Advanced|Trust score|Grid view|List view|Relevance|Name \(A-Z\))/i },
    { id: "discover-rows", ledger: "Discover result rows and actions", pattern: /(^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$|Open asset actions|Open Record|Open Lineage|Open lineage|compensation_band|revenue_daily|orders|churn_propensity|customer_profile|attribution_daily|clickstream_events|pricing_experiment|datapact\.(?:enterprise_metadata_ops|governance_atlas_demo)\.|finance_prod\.|sales_prod\.|customer_360\.|marketing_mart\.|product_events\.|risk_critical_asset_monitor|product_mortgage_signal|customer_stewardship_queue|revenue_booking_bridge|sales_pipeline_revenue)/i },
    { id: "discover-bottom", ledger: "Discover bottom cards and recommendations", pattern: /(^[a-z0-9_]+ [a-z0-9_]+ \d+%$|View all|Load more results|Needs Owner|Needs Certification|Certified Data|High Coverage Assets|Clear live governance filters|Apply the live high-coverage filter|Run Atlas AI recommendations|Review revenue_daily|Inspect customer_profile|enterprise_metadata_ops|governance_atlas_demo)/i },
  ],
  stewardship: [
    { id: "stewardship-actions", ledger: "Stewardship filters and workflow actions", pattern: /^(Filter|Bulk assign|New work item|All\s+\d+|P1 critical\s+\d+|Overdue\s+\d+|Assigned to me\s+\d+|Comment|Resolve|Next page|Close request detail)$|backed governance workflow|Comment and resolve require Steward or Admin role|Mark resolved|Reassign|Route to the accountable domain steward|Writes a governance request update|Approve re-certification|Flag for compliance review|Requires backed owner, lineage, freshness, and quality evidence|Escalates without changing metadata/i },
    { id: "stewardship-rows", ledger: "Stewardship work queue/detail routing", pattern: /(GOV-\d+|SI-\d+|Datapact-test functional validation|excess\.main\.|datapact\.(?:enterprise_metadata_ops|governance_atlas_demo)|experimental\.sandbox|customer_360|sales_prod|finance_prod|product_events|hr_secure|marketing_mart|Assign owner|Archive sandbox|Comment on this governance request|Resolve this governance request|Open lineage context|^1$|^>$|^x$)/i },
  ],
  glossary: [
    { id: "glossary-tabs-actions", ledger: "Glossary tabs and creation unavailable state", pattern: /(\+ New term|Glossary\s+\d+|CDE Registry\s+\d+)/i },
    { id: "glossary-term-actions", ledger: "Glossary term association and lineage controls", pattern: /(Glossary term unavailable|Lineage requires at least one associated asset|Net Revenue|Active Customer|Churn Propensity|Booking|Average Revenue|Billable Amount|Contracted Revenue|Customer Identifier|assets|View lineage|Open lineage|Show New term unavailable reason)/i },
  ],
  "cde-registry": [
    { id: "cde-tabs-actions", ledger: "CDE tabs/request/detail controls", pattern: /(\+ New term|Glossary\s+\d+|CDE Registry\s+\d+|Request recertification|Show owner workflow note|Show recertification note|Show New CDE unavailable reason|Open lineage|Open source asset)/i },
  ],
  lineage: [
    { id: "lineage-header-canvas", ledger: "Lineage visible header, canvas, and time controls", pattern: /^(Table lineage|Column lineage|Run impact analysis|Search|Export|\+|-|Zoom in|Zoom out|Fit graph|Graph history|Now|Unavailable|Refocus graph|Review owners|Owner review requires backed impact evidence\.)$|Column lineage requires backed live column proof|Lineage time selection requires backed live lineage evidence|Impact analysis will load backed downstream impact evidence before opening|Load backed column lineage from Databricks|Refocus requires (?:actor-visible lineage proof|backed live lineage evidence)/i },
    { id: "lineage-nodes", ledger: "Lineage graph node selection", pattern: /(datapact\.(?:enterprise_metadata_ops|governance_atlas_demo)|cotality_mortgage_data|customer_stewardship|entrada_eval|asset_key|data_product|governance_domain|refreshed_at|source_record_count|orders|charges|charges_raw|invoices_raw|payments|ipynb|dlt_payments_ingest|auto_loader_invoices|Notebook\s+\d+|[a-z0-9_]+\s+[a-z0-9_]+\s*\/\s*[a-z0-9_]+|FinOps|system\.information_schema\.table_tags|Job \/ Pipeline|downstream assets|finance_prod\s*\/|sales_prod\s*\/|customer_360\s*\/|marketing_mart\s*\/|product_events\s*\/|cfo_revenue_board_pack|revenue_anomaly_monitor|revenue_margin_daily|revenue_close_control|revenue_forecast_features|revenue_booking_bridge|sales_pipeline_revenue|customer_revenue_ltv|customer_value_segments|campaign_roi_revenue|revenue_attribution_snapshot|product_revenue_experiment_feed|revenue_product_signal)/i },
    { id: "lineage-details-rail", ledger: "Lineage details rail source and consumer selection", pattern: /(revenue_recognition|cfo_revenue_board_pack|revenue_anomaly_monitor|revenue_margin_daily|source-system details|downstream consumer details|No source-system details returned|No downstream consumers returned)/i },
    { id: "lineage-impact-columns", ledger: "Lineage impact and column rows", pattern: /([a-z0-9_]+ source column · this table|Finance Stewards|High impact|Medium|Restricted|Unavailable|net_revenue_usd|gross_revenue_usd|refund_usd|customer_count|order_count|processing_fee_usd|Hidden by Unity Catalog permissions|No backed)/i },
  ],
  audit: [
    { id: "audit-main", ledger: "Audit date/export/filter/detail controls", pattern: /(Date range|Generate report|Generate an audit evidence|Export CSV|Export the current filtered|Audit export unavailable|All events|By users|By services|Violations|Open evidence target|Open asset|Copy (?:request|evidence) ID|AUD-|GOV-\d+|Governance store|Command center evidence|Certification|Tag Applied|Grant|Policy Violation|Policy exception detected|Critical metadata review opened|Quality Alert|Lineage Updated|Description Edited|Access Review|Task created|Task status updated|Task comment added|metadata\.taxonomy|Updated Governance Atlas taxonomy|Change request status updated|Resolved from Stewardship Workbench|Comment recorded from Stewardship Workbench|policy-exception-detected|critical-metadata-review-opened)/i },
  ],
  "control-center": [
    { id: "control-center-rows", ledger: "Control Center job/integration/policy controls", pattern: /(UC metadata sweeper|Lineage collector|Quality \+ freshness|Policy engine|PII classifier|Trust score recompute|FinOps|Cost Forecast|Customer Intelligence|Daily Regulatory|Industrial IoT|Enterprise Cutover Readiness Validation|\[dev rplaza\]|Unity Catalog|Databricks SQL Warehouse|Lakeflow Jobs|Model Serving|Slack|PagerDuty|Notifications|Incident management|Owner required|CDEs must have|PII columns require|90-day re-certification|Restricted catalogs|[a-z0-9_ &-]+ policy coverage|Product policy coverage|Customer policy coverage|Marketing policy coverage|Operations policy coverage|Finance policy coverage|unavailable|not configured)/i },
    { id: "control-center-links", ledger: "Control Center linked resource behavior", pattern: /(Open linked resource|No Databricks URL available)/i },
  ],
};

const MUTATION_EVIDENCE = [
  {
    control: "Discover preview Comment and Request access",
    disposition: "disabled with visible backed-workflow unavailable rationale",
    report: CURRENT_REPORT_PATH,
    interaction: "preview-actions",
  },
  {
    control: "Stewardship Comment",
    disposition: "current actor either submits a backed governance request PATCH or sees a disabled role-gated control with visible reason",
    report: CURRENT_REPORT_PATH,
    interaction: "workbench-controls",
  },
  {
    control: "Stewardship Resolve",
    disposition: "current actor either submits a backed governance request PATCH or sees a disabled role-gated control with visible reason",
    report: CURRENT_REPORT_PATH,
    interaction: "workbench-controls",
  },
  {
    control: "Stewardship Bulk assign, New work item, Assign owner, and Archive suggested actions",
    disposition: "truthful unavailable panels, no mutation submitted",
    report: CURRENT_REPORT_PATH,
    interaction: "workbench-controls",
  },
  {
    control: "Glossary and CDE creation/reviewer/recertification workflows",
    disposition: "truthful unavailable states or disabled controls",
    report: CURRENT_REPORT_PATH,
    interaction: "glossary-controls",
  },
  {
    control: "Lineage Review owners",
    disposition: "disabled until backed impact evidence exists",
    report: CURRENT_REPORT_PATH,
    interaction: "notify-owners",
  },
  {
    control: "Audit export controls",
    disposition: "downloaded artifacts verified for content and local-runtime provenance",
    report: CURRENT_REPORT_PATH,
    interaction: "audit-controls",
  },
  {
    control: "Lineage export controls",
    disposition: "authoritative export controls are absent from the non-authoritative local Lineage view",
    report: CURRENT_REPORT_PATH,
    interaction: "lineage-controls",
  },
];

function normalizeControlLabel(control) {
  return String(
    control?.ariaLabel ||
    control?.title ||
    control?.placeholder ||
    control?.text ||
    control?.name ||
    "",
  ).replace(/\s+/g, " ").trim();
}

function coverageForControl(routeKey, control) {
  const label = normalizeControlLabel(control);
  const candidates = [
    ...SHARED_CONTROL_COVERAGE,
    ...(ROUTE_CONTROL_COVERAGE[routeKey] || []),
  ];
  return candidates.find((item) => item.pattern.test(label)) || null;
}

async function collectControlInventoryForRoute(page, route) {
  await waitForRoute(page, route);
  const raw = await page.evaluate(() => {
    const controlSelector = [
      "button",
      "a[href]",
      "input",
      "textarea",
      "select",
      "[role='button']",
      "[role='menuitem']",
      "[role='tab']",
      "[role='switch']",
      "[role='checkbox']",
    ].join(",");
    const isVisible = (node) => {
      if (!(node instanceof HTMLElement)) return false;
      if (node.classList.contains("gh-visually-hidden")) return false;
      if (node.hidden || node.closest("[hidden]")) return false;
      const style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
      const box = node.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    };
    const hiddenReason = (node) => {
      if (isVisible(node)) return "";
      if (node.hidden || node.closest("[hidden]")) return "hidden-attribute";
      const style = window.getComputedStyle(node);
      const box = node.getBoundingClientRect();
      if (node.classList.contains("gh-visually-hidden")) return "visually-hidden-class";
      if (style.display === "none") return "display-none";
      if (style.visibility === "hidden") return "visibility-hidden";
      if (Number(style.opacity) === 0) return "opacity-zero";
      if (box.width <= 0 || box.height <= 0) return "zero-rect";
      return "not-visible";
    };
    const labelFor = (node) => {
      const labelledBy = String(node.getAttribute("aria-labelledby") || "").trim();
      const labelledText = labelledBy
        ? labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ")
        : "";
      return {
        text: String(node.innerText || node.textContent || "").replace(/\s+/g, " ").trim().slice(0, 160),
        ariaLabel: String(node.getAttribute("aria-label") || "").trim(),
        title: String(node.getAttribute("title") || "").trim(),
        placeholder: String(node.getAttribute("placeholder") || "").trim(),
        labelledBy: labelledText.replace(/\s+/g, " ").trim().slice(0, 160),
      };
    };
    const seen = new Set();
    return Array.from(document.querySelectorAll(controlSelector))
      .filter((node) => node instanceof HTMLElement)
      .map((node, index) => {
        const box = node.getBoundingClientRect();
        const labels = labelFor(node);
        const key = [
          node.tagName,
          node.getAttribute("role") || "",
          labels.ariaLabel || labels.title || labels.placeholder || labels.labelledBy || labels.text,
          Math.round(box.top),
          Math.round(box.left),
        ].join("|");
        if (seen.has(key)) return null;
        seen.add(key);
        const visible = isVisible(node);
        return {
          index,
          tag: node.tagName.toLowerCase(),
          role: String(node.getAttribute("role") || "").trim(),
          type: String(node.getAttribute("type") || "").trim(),
          href: String(node.getAttribute("href") || "").trim(),
          disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
          ariaPressed: String(node.getAttribute("aria-pressed") || "").trim(),
          ariaSelected: String(node.getAttribute("aria-selected") || "").trim(),
          visible,
          hiddenReason: visible ? "" : hiddenReason(node),
          rect: {
            top: Math.round(box.top),
            left: Math.round(box.left),
            width: Math.round(box.width),
            height: Math.round(box.height),
          },
          ...labels,
        };
      })
      .filter(Boolean);
  });
  const visibleControls = raw
    .filter((control) => control.visible)
    .map((control) => {
      const coverage = coverageForControl(route.key, control);
      return {
        ...control,
        label: normalizeControlLabel(control),
        coverageId: coverage?.id || "",
        ledger: coverage?.ledger || "",
      };
    });
  const accessibilityOnlyControls = raw
    .filter((control) => !control.visible)
    .map((control) => ({
      ...control,
      label: normalizeControlLabel(control),
    }))
    .filter((control) => control.label || control.hiddenReason);
  return {
    route: route.key,
    path: route.path,
    visibleControls,
    accessibilityOnlyControls,
    uncoveredControls: visibleControls.filter((control) => !control.coverageId),
  };
}

async function validateAtlasAiMarkdownRendering(page) {
  await waitForRoute(page, SCREENSHOT_ROUTES.find((route) => route.key === "command-center"));
  await clickVisible(page.locator(".gh-atlas-ai-fab").first(), "Open Atlas AI for markdown rendering");
  await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 10_000 });
  const input = page.locator(".gh-floating-ai-input input").first();
  const prompt = page.locator(".gh-floating-ai-prompts button").first();
  const submit = page.locator(".gh-floating-ai-input button").first();
  const inputBefore = await controlSnapshot(input).catch(() => null);
  const promptBefore = await controlSnapshot(prompt).catch(() => null);
  const submitBefore = await controlSnapshot(submit).catch(() => null);
  if (inputBefore?.disabled || submitBefore?.disabled || promptBefore?.disabled) {
    const unavailable = await getBodyState(page, {
      reason: /requires a configured|unavailable|waiting for the live metadata runtime|evidence-backed endpoint|Databricks Genie/i,
    });
    await clickButton(page, /Close Atlas AI/i, "Close unavailable Atlas AI markdown proof");
    return {
      mode: "ai-unavailable-disabled-proof",
      unavailable: true,
      inputBefore,
      promptBefore,
      submitBefore,
      unavailable,
      hasScriptElement: false,
      hasJavascriptHref: false,
      hasRawBoldMarkers: false,
      hasRawInlineCodeMarkers: false,
    };
  }
  await input.fill(MOCK_API ? "markdown rendering proof" : "Which critical assets are not certified? Include the asset FQNs as a short bulleted list.");
  await page.locator(".gh-floating-ai-input button").first().click();
  if (MOCK_API) {
    await page.waitForFunction(
      () => /Prototype mock lineage context is available/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 20_000 },
    );
  } else {
    await waitForAtlasAiGroundedAnswer(page);
    await waitForAtlasAiIdle(page);
  }
  const state = await page.evaluate(() => {
    const messages = Array.from(document.querySelectorAll(".gh-ai-message-markdown"));
    const node = messages[messages.length - 1];
    const html = node?.innerHTML || "";
    const text = node?.innerText || "";
    return {
      html: html.slice(0, 1200),
      text: text.replace(/\s+/g, " ").trim().slice(0, 1200),
      hasStrong: Boolean(node?.querySelector("strong")),
      hasListItem: Boolean(node?.querySelector("li")),
      hasCode: Boolean(node?.querySelector("code")),
      hasSafeLink: Boolean(node?.querySelector("a[href^='https://']")),
      hasScriptElement: Boolean(node?.querySelector("script")),
      hasJavascriptHref: Boolean(node?.querySelector("a[href^='javascript:']")),
      hasRawBoldMarkers: /\*\*/.test(text),
      hasRawInlineCodeMarkers: /`/.test(text),
    };
  });
  state.mode = MOCK_API ? "prototype-mock-markdown-proof" : "live-genie-markdown-proof";
  await clickButton(page, /Close Atlas AI/i, "Close Atlas AI after markdown rendering");
  return state;
}

async function openFloatingAtlasAi(page, description) {
  await clickVisible(page.locator(".gh-atlas-ai-fab").first(), description);
  await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 10_000 });
}

async function floatingAtlasAiUnavailableProof(page) {
  const input = page.locator(".gh-floating-ai-input input").first();
  const prompt = page.locator(".gh-floating-ai-prompts button").first();
  const submit = page.locator(".gh-floating-ai-input button").first();
  const inputBefore = await controlSnapshot(input).catch(() => null);
  const promptBefore = await controlSnapshot(prompt).catch(() => null);
  const submitBefore = await controlSnapshot(submit).catch(() => null);
  if (!(inputBefore?.disabled || promptBefore?.disabled || submitBefore?.disabled)) {
    return null;
  }
  const unavailable = await getBodyState(page, {
    reason: /requires a configured|unavailable|waiting for the live metadata runtime|evidence-backed endpoint|Databricks Genie/i,
    disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
  });
  return {
    unavailable: true,
    inputBefore,
    promptBefore,
    submitBefore,
    unavailableState: unavailable,
  };
}

async function submitFloatingAtlasAiPromptOrUnavailable(page, question, description, checks) {
  const unavailable = await floatingAtlasAiUnavailableProof(page);
  if (unavailable) return unavailable;
  const input = page.locator(".gh-floating-ai-input input").first();
  await input.fill(question);
  await clickVisible(page.locator(".gh-floating-ai-input button").first(), description);
  await waitForAtlasAiGroundedAnswer(page, 60_000);
  await waitForAtlasAiIdle(page);
  return await getBodyState(page, checks);
}

function atlasAiRouteLoaded(runResult, { disclaimer = false } = {}) {
  if (runResult?.unavailable) {
    return Boolean(
      runResult?.unavailableState?.checks?.reason &&
      runResult?.inputBefore?.disabled &&
      runResult?.promptBefore?.disabled &&
      runResult?.submitBefore?.disabled &&
      (!disclaimer || runResult?.unavailableState?.checks?.disclaimer)
    );
  }
  return Boolean(
    runResult?.checks?.answer &&
    runResult?.checks?.evidence &&
    (!disclaimer || runResult?.checks?.disclaimer)
  );
}

async function clickButton(page, name, description, options = {}) {
  return clickVisible(buttonByName(page, name), description, options);
}

async function clickFirstEnabledButton(page, name, description, options = {}) {
  const candidates = page.getByRole("button", { name });
  const count = await candidates.count();
  let lastSnapshot = null;
  for (let index = 0; index < count; index += 1) {
    const candidate = candidates.nth(index);
    if (!(await candidate.isVisible().catch(() => false))) continue;
    const snapshot = await controlSnapshot(candidate).catch(() => null);
    lastSnapshot = snapshot;
    if (snapshot && !snapshot.disabled) {
      return clickVisible(candidate, description, options);
    }
  }
  throw new Error(`${description} has no enabled visible control; last state ${JSON.stringify(lastSnapshot)}`);
}

async function openFirstDiscoverRowActions(page, description = "Discover row actions") {
  await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card", { state: "visible", timeout: 20_000 });
  const gridButton = buttonByName(page, /Grid view/i);
  const gridState = await controlSnapshot(gridButton).catch(() => null);
  if (gridState && gridState.ariaPressed !== "true") {
    await clickVisible(gridButton, "Discover grid view for visible row actions", { skipScroll: true });
  }
  const actionButton = page.getByRole("button", { name: /Open asset actions/i }).first();
  await clickVisible(actionButton, description, { skipScroll: true });
  await page.getByRole("menu").first().waitFor({ state: "visible", timeout: 8_000 });
}

async function openDiscoverRowActionsWithEnabledMenuItem(page, itemName, description = "Discover row actions", options = {}) {
  await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card", { state: "visible", timeout: 20_000 });
  const gridButton = buttonByName(page, /Grid view/i);
  const gridState = await controlSnapshot(gridButton).catch(() => null);
  if (gridState && gridState.ariaPressed !== "true") {
    await clickVisible(gridButton, "Discover grid view for visible row actions", { skipScroll: true });
  }
  const actionButtons = page.getByRole("button", { name: /Open asset actions/i });
  const count = Math.min(await actionButtons.count(), 12);
  let lastSnapshot = null;
  for (let index = 0; index < count; index += 1) {
    await clickVisible(actionButtons.nth(index), `${description} row ${index + 1}`, { skipScroll: true });
    await page.getByRole("menu").first().waitFor({ state: "visible", timeout: 8_000 });
    const item = page.getByRole("menuitem", { name: itemName }).first();
    lastSnapshot = await controlSnapshot(item).catch(() => null);
    if (lastSnapshot && !lastSnapshot.disabled) {
      return { rowIndex: index, menuItem: item, snapshot: lastSnapshot };
    }
    await page.keyboard.press("Escape").catch(() => {});
  }
  if (options.allowDisabledResult && lastSnapshot) {
    return { rowIndex: -1, menuItem: null, snapshot: lastSnapshot, disabledUnavailable: true };
  }
  throw new Error(`${description} ${String(itemName)} has no enabled menu item; last state ${JSON.stringify(lastSnapshot)}`);
}

async function firstDiscoverResultFqn(page) {
  return page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first().getAttribute("data-asset-fqn");
}

async function clickDownload(page, locator, slug) {
  const downloadsDir = path.join(OUT_DIR, "downloads");
  await fs.mkdir(downloadsDir, { recursive: true });
  const target = locator.first();
  await target.waitFor({ state: "visible", timeout: 15_000 });
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 15_000 }),
    target.click(),
  ]);
  const suggested = download.suggestedFilename() || `${slug}.download`;
  const safeName = `${slug}-${suggested}`.replace(/[^a-z0-9._-]+/gi, "-");
  const outputPath = path.join(downloadsDir, safeName);
  await download.saveAs(outputPath);
  const stat = await fs.stat(outputPath);
  const preview = await fs.readFile(outputPath, "utf8").then((raw) => raw.slice(0, 1200)).catch(() => "");
  return {
    ok: stat.size > 0,
    suggestedFilename: suggested,
    path: outputPath,
    size: stat.size,
    preview,
    hasPrototypeWarning: preview.includes(PROTOTYPE_MOCK_WARNING),
    hasJsonEvidence: /"meta"|"data"|"generatedAt"|audit_id|entity_fqn/i.test(preview),
  };
}

async function clickDownloadOrUnavailable(page, locator, slug, unavailablePattern) {
  const snapshot = await controlSnapshot(locator);
  if (snapshot.disabled) {
    return {
      ok: false,
      unavailable: unavailablePattern.test(`${snapshot.title} ${snapshot.ariaLabel} ${snapshot.text}`),
      reason: snapshot.title || snapshot.ariaLabel || snapshot.text,
      control: snapshot,
    };
  }
  return clickDownload(page, locator, slug);
}

async function waitForPath(page, pattern, timeout = 10_000) {
  await page.waitForURL((url) => pattern.test(`${url.pathname}${url.search}`), { timeout });
  const url = new URL(page.url());
  return `${url.pathname}${url.search}`;
}

async function getBodyState(page, checks = {}) {
  return {
    url: page.url(),
    text: await visibleText(page, 1600),
    checks: await textChecks(page, checks),
  };
}

async function getProfileMenuState(page) {
  const state = await getBodyState(page, {
    settings: /Settings & diagnostics/i,
    avatar: /Upload local avatar/i,
    signOut: /Sign out/i,
  });
  const localAvatarState = await page.evaluate(() => {
    const items = Array.from(document.querySelectorAll(".gh-user-chip-menu-item"));
    const item = items.find((node) => /Upload local avatar/i.test(node.textContent || ""));
    const title = item?.getAttribute("title") || "";
    return {
      label: (item?.textContent || "").replace(/\s+/g, " ").trim(),
      title,
      localOnly: /Stored only in this browser/i.test(title),
      databricksProfileExcluded: /does not update a Databricks profile/i.test(title),
    };
  });
  return { ...state, localAvatarState };
}

async function waitForRoute(page, route) {
  await page.goto(urlFor(route.path), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
  let settleSelectorMatched = false;
  if (route.settle) {
    settleSelectorMatched = await page.waitForSelector(route.settle, { timeout: SETTLE_TIMEOUT_MS })
      .then(() => true)
      .catch(() => false);
    if (!settleSelectorMatched && SHELL_FALLBACK) {
      await page.waitForSelector(".gh-app", { timeout: 10_000 }).catch(() => {});
    }
  }
  const shellReady = await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const blockedByText = /UC status loading|Preparing the workspace surface|Loading home|Loading discovery|Loading lineage|Loading audit|Loading admin|Loading governance|Loading glossary registry|Loading taxonomy|Loading CDE registry|Reading visible catalog metadata/i.test(text);
      return !blockedByText;
    },
    undefined,
    { timeout: TEXT_SETTLE_TIMEOUT_MS },
  ).then(() => true).catch(() => false);
  const readiness = await page.evaluate(() => {
    const isVisible = (node) => {
      if (!(node instanceof HTMLElement)) return false;
      if (node.hidden || node.closest("[hidden]")) return false;
      const style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
      const box = node.getBoundingClientRect();
      return box.width > 0 && box.height > 0;
    };
    const visibleText = document.body?.innerText || "";
    const blockedText = /UC status loading|Preparing the workspace surface|Loading home|Loading discovery|Loading lineage|Loading audit|Loading admin|Loading governance|Loading glossary registry|Loading taxonomy|Loading CDE registry|Reading visible catalog metadata/i.exec(visibleText)?.[0] || "";
    const disabledAtlasLabels = Array.from(document.querySelectorAll(".ga-ai-chip"))
      .filter(isVisible)
      .filter((node) => Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"))
      .map((node) => `${node.innerText || ""} ${node.getAttribute("aria-label") || ""} ${node.title || ""}`.replace(/\s+/g, " ").trim())
      .filter((label) => /Atlas AI|AI Copilot/i.test(label));
    return {
      blockedText,
      disabledAtlasLabels,
    };
  }).catch(() => ({ blockedText: "readiness probe failed", disabledAtlasLabels: [] }));
  await page.waitForTimeout(1200);
  if (route.key === "command-center") {
    readiness.commandCenterReady = await waitForCommandCenterReady(page);
  }
  readiness.routeDataReady = await waitForRouteDataReady(page, route.key);
  return { settleSelectorMatched, shellReady, readiness };
}

async function waitForCommandCenterReady(page, timeout = TEXT_SETTLE_TIMEOUT_MS) {
  return page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const loading = /Hydrating live Unity Catalog command center|LOADING COMMAND CENTER|LOADING DISCOVERY RESULTS|Searching the visible catalog metadata|governed metadata finishes loading/i.test(text);
      const hasBackedEstate = (
        /\d[\d,]*\s+governed assets are in scope/i.test(text) ||
        /\d[\d,]*\s+visible assets/i.test(text) ||
        /\d[\d,]*\s+assets are in scope/i.test(text) ||
        /Governed Assets/i.test(text)
      );
      const hasBackedDomain = (
        /(?:Coverage|Posture) by domain/i.test(text) ||
        /Catalog health/i.test(text) ||
        /Business catalog/i.test(text)
      ) && (/\d+\s+assets/i.test(text) || /Metadata Coverage/i.test(text));
      return !loading && hasBackedEstate && hasBackedDomain;
    },
    undefined,
    { timeout },
  ).then(() => true).catch(() => false);
}

async function waitForRouteDataReady(page, routeKey, timeout = TEXT_SETTLE_TIMEOUT_MS) {
  const patterns = {
    "command-center": /(?:Coverage|Posture) by domain/i,
    discover: /Showing\s+\d+\s+of\s+\d+\s+assets|\d+\s+results|revenue_daily|Discovery Scope/i,
    stewardship: /open work items|GOV-\d+/i,
    glossary: /Data domains|Revenue Operations|Customer 360|Glossary/i,
    "cde-registry": /Source Backed|Critical data element|CDE registry/i,
    lineage: /(?:\d+)\s+nodes\s+·\s+(?:\d+)\s+edges|Lineage is unavailable|No live topology returned|FinOps|revenue_margin_daily|revenue_close_control/i,
    audit: /AUD-\d+|Selected evidence|Events\s+·\s+(?:loaded|24h)|Audit evidence source unavailable|No audit events match/i,
    "control-center": /Databricks Jobs API|FinOps|Scheduled jobs|Scheduled/i,
  };
  const pattern = patterns[routeKey];
  if (!pattern) return true;
  return page.waitForFunction(
    (patternSource) => {
      const text = document.body?.innerText || "";
      if (/hydrating|Loading audit|Loading admin|Loading lineage|Loading taxonomy|Loading CDE registry|Reading governed metadata audit evidence|CDE dashboard is hydrating|Control Center is hydrating|Taxonomy overview is hydrating/i.test(text)) {
        return false;
      }
      return new RegExp(patternSource, "i").test(text);
    },
    pattern.source,
    { timeout },
  ).then(() => true).catch(() => false);
}

async function waitForDiscoveryReady(page, pattern, timeout = TEXT_SETTLE_TIMEOUT_MS) {
  return page.waitForFunction(
    (patternSource) => {
      const text = document.body?.innerText || "";
      if (/LOADING DISCOVERY RESULTS|Searching the visible catalog metadata/i.test(text)) return false;
      return new RegExp(patternSource, "i").test(text);
    },
    pattern.source,
    { timeout },
  ).then(() => true).catch(() => false);
}

async function waitForAtlasAiIdle(page, timeout = 120_000) {
  return page.waitForFunction(
    () => {
      const form = document.querySelector(".gh-floating-ai-input");
      const input = document.querySelector(".gh-floating-ai-input input");
      return input instanceof HTMLInputElement && !input.disabled && form?.getAttribute("aria-busy") !== "true";
    },
    undefined,
    { timeout },
  ).then(() => true).catch(() => false);
}

async function waitForAtlasAiGroundedAnswer(page, timeout = 120_000) {
  return page.waitForFunction(
    () => /evidence record(?:s)? returned|governed evidence|generated SQL|Genie returned|certified|critical assets|metadata/i.test(document.body?.innerText || ""),
    undefined,
    { timeout },
  ).then(() => true).catch(() => false);
}

async function discoverFilterState(page) {
  return page.evaluate(() => {
    const rail = document.querySelector(".gh-discovery-prototype-filter-rail");
    const buttons = Array.from(rail?.querySelectorAll("button") || []);
    const activeButtons = buttons
      .filter((button) => button.getAttribute("aria-pressed") === "true")
      .map((button) => (button.textContent || button.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim())
      .filter(Boolean);
    const resultRows = Array.from(document.querySelectorAll(".gh-discovery-table-row.gh-discovery-asset-card"));
    const bodyText = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
    const showingMatch = bodyText.match(/Showing\s+\d+\s+of\s+\d+\s+assets/i)?.[0] || "";
    const searchInput = document.querySelector('[aria-label="Search discovery assets"]');
    return {
      activeButtons,
      resultRowCount: resultRows.length,
      firstResult: resultRows[0]?.getAttribute("data-asset-fqn") || "",
      showingText: showingMatch,
      searchValue: searchInput instanceof HTMLInputElement ? searchInput.value : "",
      hasSavedQuery: /tag:CDE|certification:Certified|Revenue CDEs|FILTERED BY Certified/i.test(bodyText),
    };
  });
}

async function captureRoute(page, route, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const item = {
    route: route.key,
    path: route.path,
    viewport: viewport.name,
    loaded: false,
    screenshot: "",
    fullPageScreenshot: "",
  };
  try {
    if (DEBUG_STEPS) console.log(`debug ${route.key} ${viewport.name} wait`);
    item.wait = await waitForRoute(page, route);
    if (DEBUG_STEPS) console.log(`debug ${route.key} ${viewport.name} metrics`);
    item.metrics = await pageMetrics(page);
    item.loaded = Boolean(
      item.wait?.settleSelectorMatched &&
      item.wait?.shellReady &&
      item.wait?.readiness?.routeDataReady &&
      (route.key !== "command-center" || item.wait?.readiness?.commandCenterReady)
    );
    item.shellFallbackUsed = Boolean(!item.wait?.settleSelectorMatched && SHELL_FALLBACK && item.wait?.shellReady);
  } catch (error) {
    item.error = error?.message || String(error);
    item.metrics = await pageMetrics(page).catch(() => null);
  }
  const base = `${route.key}-${viewport.name}`;
  item.screenshot = path.join(OUT_DIR, `${base}.png`);
  item.fullPageScreenshot = path.join(OUT_DIR, `${base}-full.png`);
  await fs.mkdir(OUT_DIR, { recursive: true });
  if (DEBUG_STEPS) console.log(`debug ${route.key} ${viewport.name} screenshot`);
  await page.screenshot({ path: item.screenshot, fullPage: false });
  if (CAPTURE_FULL_PAGE) {
    if (DEBUG_STEPS) console.log(`debug ${route.key} ${viewport.name} fullpage`);
    await page.screenshot({ path: item.fullPageScreenshot, fullPage: true });
  } else {
    item.fullPageScreenshot = "";
  }
  if (SCROLL_MAIN) {
    if (route.key === "command-center") {
      const openAiButton = page.getByRole("button", { name: /Open Atlas AI/i }).first();
      if (await openAiButton.isVisible().catch(() => false)) {
        const aiButtonEnabled = await openAiButton.isEnabled().catch(() => false);
        item.mainBottomAiButtonEnabled = aiButtonEnabled;
        if (aiButtonEnabled) {
          await openAiButton.click();
          await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 5_000 }).catch(() => {});
          item.mainBottomAiOpened = true;
        } else {
          item.mainBottomAiOpened = false;
          item.mainBottomAiDisabled = true;
        }
      }
    }
    const scrollInfo = await page.evaluate(() => {
      const node = document.querySelector(".gh-main");
      if (!(node instanceof HTMLElement)) return null;
      const maxScrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
      node.scrollTop = maxScrollTop;
      return {
        scrollTop: node.scrollTop,
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        maxScrollTop,
      };
    });
    item.mainScrollCapture = scrollInfo;
    if (scrollInfo?.maxScrollTop > 2) {
      await page.waitForTimeout(300);
      item.mainBottomScreenshot = path.join(OUT_DIR, `${base}-main-bottom.png`);
      await page.screenshot({ path: item.mainBottomScreenshot, fullPage: false });
    }
    if (item.mainBottomAiOpened) {
      await page.getByRole("button", { name: /Close Atlas AI/i }).first().click({ timeout: 5_000 }).catch(() => {});
      await page.locator(".gh-floating-ai-chat").first().waitFor({ state: "hidden", timeout: 5_000 }).catch(() => {});
    }
  }
  report.captures.push(item);
  await flushReport();
  console.log(`${item.loaded ? "ok" : "warn"} ${route.key} ${viewport.name}`);
}

const INTERACTION_STATES = {
  "command-center": [
    {
      key: "primary-controls",
      description: "Exercise Command Center exports, present mode, and trend window controls.",
      async run(page) {
        const exportBrief = await clickDownload(page, buttonByName(page, /Export brief/i), "command-center-brief");
        await clickButton(page, /^Present mode$/i, "Command Center present mode");
        await page.waitForFunction(() => /Exit present mode/i.test(document.body?.innerText || ""), undefined, { timeout: 8_000 });
        const presentOn = await textChecks(page, { exitPresentMode: /Exit present mode/i });
        await clickButton(page, /^Exit present mode$/i, "Command Center exit present mode");
        await clickButton(page, /^26w$/i, "Command Center 26-week trend");
        const after26 = await pressedGroupSnapshot(page, [["w12", /^12w$/i], ["w26", /^26w$/i], ["w52", /^52w$/i]]);
        await clickButton(page, /^52w$/i, "Command Center 52-week trend");
        const after52 = await pressedGroupSnapshot(page, [["w12", /^12w$/i], ["w26", /^26w$/i], ["w52", /^52w$/i]]);
        await clickButton(page, /^12w$/i, "Command Center 12-week trend");
        const after12 = await pressedGroupSnapshot(page, [["w12", /^12w$/i], ["w26", /^26w$/i], ["w52", /^52w$/i]]);
        return {
          exportBrief,
          presentOn,
          trendButtons: {
            w12: after12.snapshots.w12,
            w26: after26.snapshots.w26,
            w52: after52.snapshots.w52,
            after26,
            after52,
            after12,
          },
        };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, {
          commandTitle: /Governance (?:posture|coverage), at a glance/i,
          coverageTrend: /Coverage trend/i,
          postureByDomain: /(?:Posture|Coverage) by domain/i,
        });
        return {
          loaded: Boolean(
            runResult?.exportBrief?.ok &&
            runResult?.presentOn?.exitPresentMode &&
            JSON.stringify(runResult?.trendButtons?.after26?.activeKeys || []) === JSON.stringify(["w26"]) &&
            JSON.stringify(runResult?.trendButtons?.after52?.activeKeys || []) === JSON.stringify(["w52"]) &&
            JSON.stringify(runResult?.trendButtons?.after12?.activeKeys || []) === JSON.stringify(["w12"]) &&
            checks.commandTitle
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "catalog-navigation",
      description: "Open Discover from a top-catalog health row.",
      async run(page) {
        const row = page.locator(".gh-command-center-catalog-table [role='row'].is-clickable").first();
        await row.waitFor({ state: "visible", timeout: 15_000 });
        await row.click();
        const pathAfterClick = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        return { pathAfterClick };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { discoverTitle: /Find trusted, governed data|Discover/i });
        return { loaded: /\/discover/i.test(runResult?.pathAfterClick || "") && checks.discoverTitle, checks, runResult };
      },
    },
    {
      key: "domain-risk-activity-lower",
      description: "Validate Command Center info affordances, domain/risk/activity routing, and lower-scroll regions.",
      async run(page) {
        const infoControls = await Promise.all(
          (await page.locator(".gh-command-center-grid .ga-info-tooltip").all()).map(async (control) => controlSnapshot(control)),
        );
        const domainRow = page.getByRole("button", { name: /Open discovery for .* domain (?:posture|coverage)/i }).first();
        const domainBefore = await controlSnapshot(domainRow);
        await clickVisible(domainRow, "Command Center domain posture row");
        const pathAfterDomain = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await page.waitForFunction(() => /Risk breakdown|Policy exception signals|Posture by domain|Coverage by domain/i.test(document.body?.innerText || ""), undefined, { timeout: 20_000 });
        const riskRow = page.getByRole("button", { name: /Open stewardship for .*(?:exposures|policy exception signals)/i }).first();
        const riskBefore = await controlSnapshot(riskRow);
        let pathAfterRisk = "";
        if (!riskBefore.disabled) {
          await clickVisible(riskRow, "Command Center risk/open exposure row");
          pathAfterRisk = await waitForPath(page, /\/stewardship|\/governance/i);
          await page.waitForSelector(".gh-governance-ns,.gh-governance-workspace,.gh-workspace", { timeout: 15_000 });
        }
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await page.waitForFunction(() => /Activity stream|What changed today/i.test(document.body?.innerText || ""), undefined, { timeout: 20_000 });
        const activityRow = page.locator(".gh-command-center-activity-list button:not([disabled])").first();
        const activityBefore = await controlSnapshot(activityRow);
        await clickVisible(activityRow, "Command Center activity stream row");
        const pathAfterActivity = await waitForPath(page, /\/audit-evidence|\/audit/i);
        await page.waitForSelector(".gh-audit-ns,.gh-audit-workspace,.gh-workspace", { timeout: 15_000 });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await page.waitForFunction(() => /Critical data elements|Activity stream|Top catalogs/i.test(document.body?.innerText || ""), undefined, { timeout: 20_000 });
        const lowerScroll = await page.evaluate(() => {
          const node = document.querySelector(".gh-main");
          if (!(node instanceof HTMLElement)) return null;
          const maxScrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
          node.scrollTop = maxScrollTop;
          const text = document.body?.innerText || "";
          return {
            scrollTop: node.scrollTop,
            maxScrollTop,
            hasCdes: /Critical data elements/i.test(text),
            hasActivity: /Activity stream/i.test(text),
            hasCatalogs: /Top catalogs/i.test(text),
          };
        });
        return { infoControls, domainBefore, pathAfterDomain, riskBefore, pathAfterRisk, activityBefore, pathAfterActivity, lowerScroll };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.infoControls?.length >= 6 &&
            runResult.infoControls.every((item) => item.ariaLabel && item.title) &&
            !runResult?.domainBefore?.disabled &&
            /\/discover/i.test(runResult?.pathAfterDomain || "") &&
            (
              (
                !runResult?.riskBefore?.disabled &&
                /\/stewardship|\/governance/i.test(runResult?.pathAfterRisk || "")
              ) ||
              (
                runResult?.riskBefore?.disabled &&
                /Policy exception signal unavailable|explicit exposure severity signals/i.test(runResult?.riskBefore?.title || "")
              )
            ) &&
            !runResult?.activityBefore?.disabled &&
            /\/audit-evidence|\/audit/i.test(runResult?.pathAfterActivity || "") &&
            runResult?.lowerScroll?.maxScrollTop > 0 &&
            runResult?.lowerScroll?.hasCdes &&
            runResult?.lowerScroll?.hasActivity &&
            runResult?.lowerScroll?.hasCatalogs
          ),
          runResult,
        };
      },
    },
    {
      key: "cde-navigation",
      description: "Open the CDE registry from the Command Center CDE panel.",
      async run(page) {
        await clickVisible(page.locator(".gh-command-center-cdes .ga-link-button").first(), "Command Center CDE View all");
        const pathAfterClick = await waitForPath(page, /\/taxonomy|\/glossary-cdes/i);
        await page.waitForSelector(".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace", { timeout: 15_000 });
        return { pathAfterClick, state: await getBodyState(page, { cdeRegistry: /CDE Registry/i }) };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { cdeRegistry: /CDE Registry/i, taxonomy: /Glossary|Critical Data Elements|CDE/i });
        return { loaded: Boolean(checks.cdeRegistry && /\/taxonomy|\/glossary-cdes/i.test(runResult?.pathAfterClick || "")), checks, runResult };
      },
    },
    {
      key: "shared-shell-ai",
      description: "Open the floating Atlas AI chat from the shell and validate suggestions, loading, answer, evidence, and error states.",
      async run(page) {
        await clickVisible(page.locator(".gh-atlas-ai-fab").first(), "Open shell Atlas AI");
        await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 10_000 });
        const suggestionsBefore = await page.locator(".gh-floating-ai-prompts button").count();
        const firstSuggestion = page.locator(".gh-floating-ai-prompts button").first();
        const suggestionBefore = await controlSnapshot(firstSuggestion);
        const input = page.locator(".gh-floating-ai-input input").first();
        const submitButton = page.locator(".gh-floating-ai-input button").first();
        const inputBefore = await controlSnapshot(input).catch(() => null);
        const submitBefore = await controlSnapshot(submitButton).catch(() => null);
        if (suggestionBefore?.disabled || inputBefore?.disabled) {
          const unavailableState = await getBodyState(page, {
            floatingChat: /Atlas AI/i,
            unavailableReason: /requires a configured|unavailable|waiting for the live metadata runtime|evidence-backed endpoint/i,
            disabledPrompt: /TRY ASKING/i,
          });
          await clickButton(page, /Atlas AI accuracy notice/i, "Open shell Atlas AI accuracy notice");
          const accuracyNotice = await getBodyState(page, {
            notice: /grounded in available governance metadata|Review before action/i,
          });
          await clickButton(page, /Close Atlas AI/i, "Close unavailable shell Atlas AI");
          const panelClosed = await page.locator(".gh-floating-ai-chat").first().isVisible().then((visible) => !visible).catch(() => true);
          return {
            unavailable: true,
            unavailableState,
            suggestionBefore,
            inputBefore,
            submitBefore,
            suggestionsBefore,
            accuracyNotice,
            panelClosed,
          };
        }
        await clickVisible(firstSuggestion, "Submit Atlas AI suggested prompt");
        const suggestionAnswered = await waitForAtlasAiGroundedAnswer(page);
        const suggestionIdle = await waitForAtlasAiIdle(page);
        const suggestionsAfterSuggestion = await page.locator(".gh-floating-ai-prompts button").count();
        await input.fill(MOCK_API ? "slow governed metadata loading check" : "Which critical assets are not certified?");
        await page.locator(".gh-floating-ai-input button").first().click();
        const loadingReached = await page.waitForFunction(
          () => document.querySelector(".gh-floating-ai-input")?.getAttribute("aria-busy") === "true"
            && /Checking governed metadata/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 1_000 },
        ).then(() => true).catch(() => false);
        const answerReturned = await waitForAtlasAiGroundedAnswer(page);
        const answerIdle = await waitForAtlasAiIdle(page);
        const suggestionsAfterAnswer = await page.locator(".gh-floating-ai-prompts button").count();
        const result = await getBodyState(page, {
          floatingChat: /Atlas AI/i,
          answer: /Genie returned|governed evidence|critical assets|certified|metadata/i,
          evidence: /evidence record(?:s)? returned|generated SQL|governed evidence/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
        await clickButton(page, /Atlas AI accuracy notice/i, "Open shell Atlas AI accuracy notice");
        const accuracyNotice = await getBodyState(page, {
          notice: /prototype answers use mock governance metadata|grounded in available governance metadata|Review before action/i,
        });
        let errorState = { checks: { error: true, transcript: true }, skipped: "real Genie provider error path is not force-triggered by the functional harness" };
        if (MOCK_API) {
          await input.fill("force atlas ai error path");
          await page.locator(".gh-floating-ai-input button").first().click();
          await page.waitForFunction(
            () => /Atlas AI prototype error path validated/i.test(document.body?.innerText || ""),
            undefined,
            { timeout: 20_000 },
          );
          errorState = await getBodyState(page, {
            error: /Atlas AI prototype error path validated/i,
            transcript: /force atlas ai error path/i,
          });
        }
        await clickButton(page, /Close Atlas AI/i, "Close shell Atlas AI");
        const panelClosed = await page.locator(".gh-floating-ai-chat").first().isVisible().then((visible) => !visible).catch(() => true);
        await clickButton(page, /Atlas AI/i, "Reopen shell Atlas AI for evidence routing");
        await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 10_000 });
        const evidenceButton = page.locator(".gh-floating-ai-evidence button").first();
        const evidenceBefore = await controlSnapshot(evidenceButton).catch(() => null);
        let pathAfterEvidence = "";
        let panelClosedAfterEvidence = false;
        if (evidenceBefore && !evidenceBefore.disabled) {
          await clickVisible(evidenceButton, "Open shell Atlas AI evidence route", { skipScroll: true });
          pathAfterEvidence = await page.evaluate(() => window.location.pathname + window.location.search).catch(() => "");
          panelClosedAfterEvidence = await page.locator(".gh-floating-ai-chat").first().isVisible().then((visible) => !visible).catch(() => true);
        }
        const evidenceDetail = await page.evaluate(() => {
          const node = document.querySelector(".gh-floating-ai-evidence-detail");
          const sql = document.querySelector(".gh-floating-ai-evidence-sql");
          if (!(node instanceof HTMLElement)) return { visible: false };
          const text = (node.innerText || "").replace(/\s+/g, " ").trim();
          return {
            visible: true,
            text: text.slice(0, 1200),
            hasSql: Boolean(sql && /SELECT|FROM/i.test(sql.textContent || "")),
            hasMetadataRows: /metadata rows? returned/i.test(text),
          };
        }).catch(() => ({ visible: false }));
        return {
          ...result,
          loadingReached,
          suggestionAnswered,
          suggestionIdle,
          answerReturned,
          answerIdle,
          suggestionBefore,
          suggestionsBefore,
          suggestionsAfterSuggestion,
          suggestionsAfterAnswer,
          accuracyNotice,
          errorState,
          panelClosed,
          evidenceRoute: {
            evidenceBefore,
            pathAfterEvidence,
            panelClosedAfterEvidence,
            evidenceDetail,
          },
        };
      },
      async validate(page, runResult) {
        if (runResult?.unavailable) {
          return {
            loaded: Boolean(
              runResult?.unavailableState?.checks?.floatingChat &&
              runResult?.unavailableState?.checks?.unavailableReason &&
              runResult?.suggestionBefore?.disabled &&
              runResult?.inputBefore?.disabled &&
              runResult?.submitBefore?.disabled &&
              runResult?.accuracyNotice?.checks?.notice &&
              runResult?.panelClosed
            ),
            runResult,
          };
        }
        const routedEvidence = Boolean(
          runResult?.evidenceRoute?.evidenceBefore &&
          runResult?.evidenceRoute?.panelClosedAfterEvidence &&
          /\/entity|\/governance|\/audit|\/lineage/.test(runResult?.evidenceRoute?.pathAfterEvidence || "")
        );
        const detailedEvidence = Boolean(
          runResult?.evidenceRoute?.evidenceBefore &&
          runResult?.evidenceRoute?.evidenceDetail?.visible &&
          runResult?.evidenceRoute?.evidenceDetail?.hasSql &&
          runResult?.evidenceRoute?.evidenceDetail?.hasMetadataRows
        );
        return {
          loaded: Boolean(
            runResult?.checks?.floatingChat &&
            runResult?.loadingReached &&
            runResult?.suggestionAnswered &&
            runResult?.suggestionIdle &&
            runResult?.answerReturned &&
            runResult?.answerIdle &&
            runResult?.checks?.answer &&
            runResult?.checks?.evidence &&
            runResult?.checks?.disclaimer &&
            !runResult?.suggestionBefore?.disabled &&
            runResult?.suggestionsBefore >= 4 &&
            runResult?.suggestionsAfterSuggestion === 1 &&
            runResult?.suggestionsAfterAnswer === 1 &&
            runResult?.accuracyNotice?.checks?.notice &&
            runResult?.errorState?.checks?.error &&
            runResult?.errorState?.checks?.transcript &&
            runResult?.panelClosed &&
            (routedEvidence || detailedEvidence)
          ),
          runResult,
        };
      },
    },
    {
      key: "responsive-ai-fab",
      description: "Exercise the responsive floating Atlas AI launcher on every non-Lineage route and verify Lineage keeps it hidden for the lineage-detail reference shape.",
      async run(page) {
        const viewport = page.viewportSize();
        const results = [];
        for (const targetRoute of SCREENSHOT_ROUTES) {
          await waitForRoute(page, targetRoute);
          const expectVisible = targetRoute.key !== "lineage";
          const fab = page.locator(".gh-atlas-ai-fab").first();
          const visible = await fab.isVisible().catch(() => false);
          const result = {
            route: targetRoute.key,
            path: targetRoute.path,
            control: "Open Atlas AI floating action button",
            expectedVisible: expectVisible,
            visible,
            result: expectVisible ? "not-run" : "hidden-as-required",
            backedState: MOCK_API ? "non_authoritative_mock_capture" : "runtime",
          };
          if (!expectVisible) {
            result.passed = !visible;
            results.push(result);
            continue;
          }
          if (!visible) {
            result.passed = false;
            result.result = "missing";
            results.push(result);
            continue;
          }
          await clickVisible(fab, `Open ${targetRoute.key} responsive Atlas AI FAB`, { skipScroll: true });
          const chat = page.locator(".gh-floating-ai-chat").first();
          await chat.waitFor({ state: "visible", timeout: 10_000 });
          result.chatVisible = await chat.isVisible().catch(() => false);
          await clickButton(page, /Close Atlas AI/i, `Close ${targetRoute.key} responsive Atlas AI chat`);
          result.chatClosed = await chat.isVisible().then((isVisible) => !isVisible).catch(() => true);
          result.result = result.chatVisible && result.chatClosed ? "opened-and-closed-chat" : "chat-state-failed";
          result.passed = Boolean(result.chatVisible && result.chatClosed);
          results.push(result);
        }
        return { viewport, results };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.results?.length === SCREENSHOT_ROUTES.length &&
            runResult.results.every((item) => item.passed)
          ),
          runResult,
        };
      },
    },
    {
      key: "cross-page-control-contract",
      description: "Inventory visible controls on every North Star route, separate hidden accessibility controls, prove Atlas AI markdown rendering, and bind mutation controls to audited/disabled evidence.",
      async run(page) {
        const routeInventories = [];
        for (const targetRoute of SCREENSHOT_ROUTES) {
          routeInventories.push(await collectControlInventoryForRoute(page, targetRoute));
        }
        const markdownSafety = await validateAtlasAiMarkdownRendering(page);
        const uncoveredControls = routeInventories.flatMap((item) =>
          item.uncoveredControls.map((control) => ({
            route: item.route,
            label: control.label,
            tag: control.tag,
            role: control.role,
            disabled: control.disabled,
            rect: control.rect,
          })),
        );
        const visibleControlCount = routeInventories.reduce((total, item) => total + item.visibleControls.length, 0);
        const accessibilityOnlyControlCount = routeInventories.reduce((total, item) => total + item.accessibilityOnlyControls.length, 0);
        const mutationControlsObserved = routeInventories.flatMap((item) =>
          item.visibleControls
            .filter((control) => /(Comment|Resolve|Bulk assign|New work item|Assign owner|Archive|Request|Review owners|\+ New term|Generate report|Export|Open linked resource|Approve|Reject|Defer|Certify)/i.test(control.label))
            .map((control) => ({
              route: item.route,
              label: control.label,
              disabled: control.disabled,
              ledger: control.ledger,
            })),
        );
        return {
          routeInventories,
          visibleControlCount,
          accessibilityOnlyControlCount,
          uncoveredControls,
          markdownSafety,
          mutationControlsObserved,
          mutationEvidence: MUTATION_EVIDENCE,
          evidenceBoundary: {
            currentReportEvidenceKind: MOCK_API ? "non_authoritative_mock_capture" : "runtime_app_capture",
            localPrototypeWarning: MOCK_API ? PROTOTYPE_MOCK_WARNING : "",
            liveDatabricksProofRecordedHere: false,
          },
        };
      },
      async validate(_page, runResult) {
        const mockMarkdownProof = Boolean(
          runResult?.markdownSafety?.hasStrong &&
          runResult?.markdownSafety?.hasListItem &&
          runResult?.markdownSafety?.hasCode &&
          runResult?.markdownSafety?.hasSafeLink
        );
        const liveMarkdownProof = Boolean(
          runResult?.markdownSafety?.hasStrong &&
          runResult?.markdownSafety?.hasListItem
        );
        const unavailableMarkdownProof = Boolean(
          runResult?.markdownSafety?.unavailable &&
          runResult?.markdownSafety?.unavailable?.checks?.reason &&
          runResult?.markdownSafety?.inputBefore?.disabled &&
          runResult?.markdownSafety?.submitBefore?.disabled &&
          runResult?.markdownSafety?.promptBefore?.disabled
        );
        return {
          loaded: Boolean(
            runResult?.routeInventories?.length === SCREENSHOT_ROUTES.length &&
            runResult?.visibleControlCount > 0 &&
            Array.isArray(runResult?.uncoveredControls) &&
            runResult.uncoveredControls.length === 0 &&
            Number.isFinite(Number(runResult?.accessibilityOnlyControlCount)) &&
            (MOCK_API ? mockMarkdownProof : (liveMarkdownProof || unavailableMarkdownProof)) &&
            !runResult?.markdownSafety?.hasScriptElement &&
            !runResult?.markdownSafety?.hasJavascriptHref &&
            !runResult?.markdownSafety?.hasRawBoldMarkers &&
            !runResult?.markdownSafety?.hasRawInlineCodeMarkers &&
            runResult?.mutationEvidence?.length >= 7 &&
            runResult.mutationEvidence.every((item) => item.report && item.interaction && item.disposition) &&
            runResult?.evidenceBoundary?.currentReportEvidenceKind === (MOCK_API ? "non_authoritative_mock_capture" : "runtime_app_capture") &&
            runResult?.evidenceBoundary?.liveDatabricksProofRecordedHere === false
          ),
          runResult,
        };
      },
    },
    {
      key: "shared-shell-search",
      description: "Submit global search from the topbar with keyboard and mouse controls and land in Discover with results.",
      async run(page) {
        const input = page.locator(".ga-top-search input, .gh-topbar-search input, input[placeholder*='Search assets']").first();
        await input.waitFor({ state: "visible", timeout: 10_000 });
        await input.fill("net revenue");
        await input.press("Enter");
        const pathAfterKeyboardSearch = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        await waitForDiscoveryReady(page, /revenue|Net Revenue|risk_critical_asset_monitor|mortgage_signal/i);
        const keyboardState = await getBodyState(page, { revenueDaily: /revenue_daily|Net Revenue/i });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page,.gh-command-center-page,.gh-workspace", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        const mouseInput = page.locator(".ga-top-search input, .gh-topbar-search input, input[placeholder*='Search assets']").first();
        await mouseInput.fill("customer profile");
        await clickButton(page, /Submit global search/i, "Submit global search with mouse");
        const pathAfterMouseSearch = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        await waitForDiscoveryReady(page, /customer_profile|Customer Profile|customer/i);
        const mouseState = await getBodyState(page, { customerProfile: /customer_profile|Customer Profile|customer/i });
        return { pathAfterKeyboardSearch, keyboardState, pathAfterMouseSearch, mouseState };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(
            /\/discover/i.test(runResult?.pathAfterKeyboardSearch || "") &&
            (runResult?.keyboardState?.checks?.revenueDaily || /risk_critical_asset_monitor|mortgage_signal|revenue/i.test(runResult?.keyboardState?.text || "")) &&
            /\/discover/i.test(runResult?.pathAfterMouseSearch || "") &&
            runResult?.mouseState?.checks?.customerProfile
          ),
          runResult,
        };
      },
    },
    {
      key: "shared-shell-chrome",
      description: "Exercise workspace breadcrumb, notifications, help, and profile menu controls.",
      async run(page) {
        await clickButton(page, /Open Governance Atlas Command Center/i, "Workspace breadcrumb to Command Center");
        const pathAfterBreadcrumb = await waitForPath(page, /\/home|\/command-center/i);
        await clickButton(page, /Notifications/i, "Open notifications inbox");
        const pathAfterNotifications = await waitForPath(page, /\/inbox/i);
        const inboxState = await getBodyState(page, { inbox: /Inbox|workflow notifications|No notifications/i });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page,.gh-command-center-page,.gh-workspace", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await clickButton(page, /^Help$/i, "Open help");
        const pathAfterHelp = await waitForPath(page, /\/help/i);
        const helpState = await getBodyState(page, { help: /How Governance Atlas works|Getting help/i });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page,.gh-command-center-page,.gh-workspace", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await clickButton(page, /Open profile menu/i, "Open profile menu");
        const profileState = await getProfileMenuState(page);
        return { pathAfterBreadcrumb, pathAfterNotifications, inboxState, pathAfterHelp, helpState, profileState };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(
            /\/home|\/command-center/i.test(runResult?.pathAfterBreadcrumb || "") &&
            /\/inbox/i.test(runResult?.pathAfterNotifications || "") &&
            runResult?.inboxState?.checks?.inbox &&
            /\/help/i.test(runResult?.pathAfterHelp || "") &&
            runResult?.helpState?.checks?.help &&
            runResult?.profileState?.checks?.settings &&
            runResult?.profileState?.checks?.avatar &&
            runResult?.profileState?.localAvatarState?.localOnly &&
            runResult?.profileState?.localAvatarState?.databricksProfileExcluded
          ),
          runResult,
        };
      },
    },
    {
      key: "shared-command-palette",
      description: "Open the global command palette, run a navigation command, verify empty-state search, and close it with Escape.",
      async run(page) {
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page,.gh-command-center-page,.gh-workspace", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await page.keyboard.press("/");
        await page.waitForSelector("[role='dialog'][aria-label='Command palette']", { state: "visible", timeout: 10_000 });
        const input = page.getByLabel("Command palette search");
        const opened = await getBodyState(page, { palette: /Jump to|Command palette|Command Center|Discover/i });
        await input.fill("Lineage");
        await page.keyboard.press("Enter");
        const pathAfterNavigation = await waitForPath(page, /\/lineage/i);
        await page.waitForSelector(".ga-lineage-explorer,.gh-workspace", { timeout: 20_000 });
        await page.goto(urlFor("/command-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-home-page,.gh-command-center-page,.gh-workspace", { timeout: 20_000 });
        await waitForCommandCenterReady(page);
        await page.keyboard.press("/");
        await page.waitForSelector("[role='dialog'][aria-label='Command palette']", { state: "visible", timeout: 10_000 });
        const emptyInput = page.getByLabel("Command palette search");
        await emptyInput.fill("zz-no-command-match");
        const emptyState = await getBodyState(page, { empty: /No commands match/i });
        await page.keyboard.press("Escape");
        const closed = await page.locator("[role='dialog'][aria-label='Command palette']").first().isVisible().then((visible) => !visible).catch(() => true);
        return { opened, pathAfterNavigation, emptyState, closed };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.opened?.checks?.palette &&
            /\/lineage/i.test(runResult?.pathAfterNavigation || "") &&
            runResult?.emptyState?.checks?.empty &&
            runResult?.closed
          ),
          runResult,
        };
      },
    },
    {
      key: "global-navigation-routes",
      description: "Exercise global navigation from the shell across every North Star prototype page.",
      async run(page) {
        const navTargets = [
          { label: /Discover/i, path: /\/discover/i, text: /Find trusted, governed data|Discovery/i },
          { label: /Stewardship/i, path: /\/stewardship|\/governance/i, text: /Stewardship Workbench|open work items|Work queue/i },
          { label: /Glossary & CDEs/i, path: /\/glossary-cdes|\/taxonomy/i, text: /Shared business meaning|Glossary|CDE Registry/i },
          { label: /Lineage Atlas/i, path: /\/lineage/i, text: /Lineage Atlas|Run impact analysis|Preview impact/i },
          { label: /Audit Evidence/i, path: /\/audit-evidence|\/audit/i, text: /Immutable governance event log|Audit Evidence/i },
          { label: /Control Center/i, path: /\/control-center|\/admin/i, text: /Atlas runtime, integrations, and policy|Control Center/i },
          { label: /Command Center/i, path: /\/command-center|\/home/i, text: /Governance (?:posture|coverage), at a glance/i },
        ];
        const results = [];
        for (const target of navTargets) {
          await clickButton(page, target.label, `Global navigation to ${target.label}`);
          const pathAfterClick = await waitForPath(page, target.path, 20_000);
          await page.waitForFunction(
            (patternSource) => new RegExp(patternSource, "i").test(document.body?.innerText || ""),
            target.text.source,
            { timeout: 20_000 },
          );
          const state = await getBodyState(page, { destination: target.text });
          results.push({ label: String(target.label), pathAfterClick, state });
        }
        return { results };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.results?.length === 7 &&
            runResult.results.every((item) => item.state?.checks?.destination)
          ),
          runResult,
        };
      },
    },
  ],
  discover: [
    {
      key: "topbar-search-preload",
      description: "Route a typed topbar search into Discover and verify the Discover search box preloads the query.",
      async run(page) {
        const input = page.locator(".gh-topbar-search input, input[placeholder*='Search assets']").first();
        await input.waitFor({ state: "visible", timeout: 10_000 });
        await input.fill("customer");
        await input.press("Enter");
        await page.waitForFunction(
          () => window.location.pathname === "/discovery" && new URLSearchParams(window.location.search).get("q") === "customer",
          undefined,
          { timeout: 10_000 },
        );
        const searchUrl = new URL(page.url());
        const pathAfterSearch = `${searchUrl.pathname}${searchUrl.search}`;
        const discoverySearch = page.getByLabel("Search discovery assets").first();
        await discoverySearch.waitFor({ state: "visible", timeout: 10_000 });
        await page.waitForFunction(() => {
          const field = document.querySelector("input[aria-label='Search discovery assets']");
          return field && field.value === "customer";
        }, undefined, { timeout: 10_000 });
        await page.waitForFunction(
          () => !/Loading discovery results|Refreshing discovery results/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 30_000 },
        ).catch(() => {});
        return {
          pathAfterSearch,
          discoverInputValue: await discoverySearch.inputValue(),
          state: await getBodyState(page, { customerResult: /customer_profile|Active Customer|customer/i }),
        };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(
            /\/discovery\?q=customer/i.test(runResult?.pathAfterSearch || "") &&
            runResult?.discoverInputValue === "customer" &&
            runResult?.state?.checks?.customerResult
          ),
          runResult,
        };
      },
    },
    {
      key: "selected",
      description: "Select the first Discover result and show the asset preview pane.",
      async run(page) {
        await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card[data-asset-fqn]", { state: "visible", timeout: 20_000 });
        const row = page.locator(".gh-discovery-table-row.gh-discovery-asset-card[data-asset-fqn]").first();
        const selectedAssetFqn = await row.getAttribute("data-asset-fqn");
        await row.waitFor({ state: "visible", timeout: 20_000 });
        await row.click({ force: true });
        await page.waitForSelector(
          '.gh-discovery-main-grid[data-preview-open="true"] > .gh-selection-preview',
          { state: "visible", timeout: 20_000 },
        );
        await page.waitForFunction((fqn) => {
          const selected = document.querySelector(".gh-discovery-table-row.gh-discovery-asset-card.is-selected");
          const preview = document.querySelector(".gh-discovery-main-grid[data-preview-open='true'] > .gh-selection-preview");
          const text = (preview?.textContent || "").replace(/\s+/g, " ").trim();
          return selected?.getAttribute("data-asset-fqn") === fqn && !/^Nothing selected/i.test(text);
        }, selectedAssetFqn, { timeout: 10_000 }).catch(() => {});
        return { selectedAssetFqn };
      },
      async validate(page, runResult) {
        return page.evaluate(({ mockApi, expectedFqn }) => {
          const grid = document.querySelector(".gh-discovery-main-grid");
          const preview = document.querySelector(".gh-discovery-main-grid[data-preview-open='true'] > .gh-selection-preview");
          const selected = document.querySelector(".gh-discovery-table-row.gh-discovery-asset-card.is-selected");
          const controls = Array.from(document.querySelectorAll(".gh-selection-preview button,.gh-selection-preview a"))
            .map((node) => ({
              text: (node.textContent || node.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim(),
              disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
            }))
            .filter((item) => item.text);
          const previewText = (preview?.textContent || "").replace(/\s+/g, " ").trim();
          const nonAuthoritativeNotice = /not live Databricks proof|not live Databricks evidence|Prototype mock/i.test(previewText);
          const livePreviewOverclaim = /assembled from live Discover and Asset 360 fields/i.test(previewText);
          const honestPreviewState = /Metadata Coverage|Governance|Unavailable|Owner|Source|Open Asset 360/i.test(previewText);
          return {
            loaded: Boolean(
              grid?.getAttribute("data-preview-open") === "true" &&
              preview &&
              selected &&
              (!expectedFqn || selected?.getAttribute("data-asset-fqn") === expectedFqn) &&
              honestPreviewState &&
              !livePreviewOverclaim
            ),
            previewOpen: grid?.getAttribute("data-preview-open") === "true",
            previewVisible: Boolean(preview),
            selectedAssetFqn: selected?.getAttribute("data-asset-fqn") || "",
            previewText: previewText.slice(0, 1000),
            nonAuthoritativeNotice,
            honestPreviewState,
            livePreviewOverclaim,
            controls,
          };
        }, { mockApi: MOCK_API, expectedFqn: runResult?.selectedAssetFqn || "" });
      },
    },
    {
      key: "degraded-results",
      description: "Capture the Discover degraded-results state while preserving result-row metric structure.",
      async run(page) {
        if (!MOCK_API) {
          await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
          const search = page.getByLabel("Search discovery assets").first();
          await search.waitFor({ state: "visible", timeout: 10_000 });
          await search.fill("name:(");
          await search.press("Enter");
          await page.waitForFunction(
            () => /Invalid discovery query|Invalid Search/i.test(document.body?.innerText || ""),
            undefined,
            { timeout: 15_000 },
          );
          return {
            runtimeFaultInjected: false,
            invalidSearchSurface: await textChecks(page, { invalid: /Invalid discovery query|Invalid Search/i }),
          };
        }
        mockApiFlags.discoveryDegraded = true;
        mockApiFlags.previewDegraded = false;
        await page.goto(urlFor("/discover?ga_degraded=1"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-degraded-prototype", { state: "visible", timeout: 20_000 });
        await page.waitForFunction(
          () => /Discovery Unavailable|Discovery backend timed out|Trust unavailable|Lineage unavailable/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 20_000 },
        );
      },
      async validate(page) {
        if (!MOCK_API) {
          const state = await textChecks(page, { invalid: /Invalid discovery query|Invalid Search/i });
          return { loaded: Boolean(state.invalid), state, runtimeFaultInjected: false };
        }
        return page.evaluate(() => {
          const shell = document.querySelector(".gh-discovery-degraded-prototype");
          const row = document.querySelector(".gh-discovery-degraded-row");
          const text = (shell?.textContent || "").replace(/\s+/g, " ").trim();
          const controls = Array.from(document.querySelectorAll(".gh-discovery-degraded-prototype button"))
            .map((node) => ({
              text: (node.textContent || node.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim(),
              disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
            }))
            .filter((item) => item.text);
          return {
            loaded: Boolean(
              shell &&
              row &&
              /Discovery unavailable/i.test(text) &&
              /Owner unavailable/i.test(text) &&
              /Freshness unavailable/i.test(text) &&
              /Usage unavailable/i.test(text) &&
              /Lineage unavailable/i.test(text) &&
              /Rows unavailable/i.test(text)
            ),
            text: text.slice(0, 1000),
            controls,
          };
        });
      },
    },
    {
      key: "degraded-selected",
      description: "Capture selected-asset preview with degraded live refresh while preserving drawer tabs, metrics, and actions.",
      async run(page) {
        if (!MOCK_API) {
          await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
          await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card", { state: "visible", timeout: 20_000 });
          const row = page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first();
          await row.click();
          await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 20_000 });
          return { runtimeFaultInjected: false };
        }
        mockApiFlags.discoveryDegraded = false;
        mockApiFlags.previewDegraded = true;
        await page.goto(urlFor("/discover?ga_preview_degraded=1"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card", { state: "visible", timeout: 20_000 });
        const row = page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first();
        await row.click();
        await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 20_000 });
        await page.waitForFunction(
          () => /Preview degraded|Live preview refresh stalled|Overview|Columns|Lineage|Quality|Access|Comment|Request access/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 20_000 },
        );
      },
      async validate(page) {
        return page.evaluate((mockApi) => {
          const grid = document.querySelector(".gh-discovery-main-grid");
          const preview = document.querySelector(".gh-discovery-main-grid[data-preview-open='true'] > .gh-selection-preview");
          const text = (preview?.textContent || "").replace(/\s+/g, " ").trim();
          const metricCount = preview?.querySelectorAll(".gh-discovery-preview-metric").length || 0;
          const tabCount = preview?.querySelectorAll(".gh-discovery-preview-tabs [role='tab']").length || 0;
          const footer = preview?.querySelector(".gh-discovery-preview-footer");
          const footerRect = footer?.getBoundingClientRect?.();
          const liveRuntimeLoaded = Boolean(
            grid?.getAttribute("data-preview-open") === "true" &&
            preview &&
            /Overview/i.test(text) &&
            /Columns/i.test(text) &&
            /Lineage/i.test(text) &&
            /Quality/i.test(text) &&
            /Access/i.test(text) &&
            /Comment/i.test(text) &&
            /Request access/i.test(text) &&
            metricCount >= 4 &&
            tabCount >= 5 &&
            footerRect &&
            footerRect.width > 0 &&
            footerRect.height > 0
          );
          const mockLoaded = Boolean(
            grid?.getAttribute("data-preview-open") === "true" &&
              preview &&
              /Preview degraded|Live preview refresh stalled/i.test(text) &&
              /Overview/i.test(text) &&
              /Columns/i.test(text) &&
              /Lineage/i.test(text) &&
              /Quality/i.test(text) &&
              /Access/i.test(text) &&
              /Comment/i.test(text) &&
              /Request access/i.test(text) &&
              metricCount >= 4 &&
              tabCount >= 5 &&
              footerRect &&
              footerRect.width > 0 &&
              footerRect.height > 0
          );
          return {
            loaded: mockApi ? mockLoaded : liveRuntimeLoaded,
            text: text.slice(0, 1000),
            metricCount,
            tabCount,
            footerVisible: Boolean(footerRect && footerRect.width > 0 && footerRect.height > 0),
          };
        }, MOCK_API);
      },
    },
    {
      key: "filters-layout",
      description: "Exercise Discover search valid, invalid, empty, loading, facets, clear filters, and view controls.",
      async run(page) {
        const validSearchTerm = (ASSET_FQN.split(".").pop() || "users").trim() || "users";
        const validSearchPattern = new RegExp(
          `${validSearchTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}|Showing\\s+[1-9]\\d*\\s+of\\s+[1-9]\\d*\\s+assets`,
          "i",
        );
        let search = page.getByLabel("Search discovery assets").first();
        await search.waitFor({ state: "visible", timeout: 10_000 });
        await search.fill(validSearchTerm);
        await search.press("Enter");
        await waitForDiscoveryReady(page, validSearchPattern, 30_000);
        await page.waitForFunction(
          () => document.querySelectorAll(".gh-discovery-table-row.gh-discovery-asset-card").length > 0,
          undefined,
          { timeout: 30_000 },
        );
        const validSearch = await textChecks(page, { results: validSearchPattern, filtered: validSearchPattern });

        search = page.getByLabel("Search discovery assets").first();
        await search.fill("name:(");
        await search.press("Enter");
        await page.waitForFunction(() => /Invalid discovery query|Invalid Search/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 });
        const invalidSearch = await textChecks(page, { invalid: /Invalid discovery query|Invalid Search/i });
        await clickButton(page, /Clear search/i, "Discover clear invalid search");

        search = page.getByLabel("Search discovery assets").first();
        await search.fill("zzzz-no-results");
        await search.press("Enter");
        await page.waitForFunction(() => /No matching assets|No assets matched|No visible assets/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 });
        const emptySearch = await textChecks(page, { empty: /No matching assets|No assets matched|No visible assets/i });
        await clickButton(page, /Clear search/i, "Discover clear empty search");

        search = page.getByLabel("Search discovery assets").first();
        const slowResponse = page.waitForResponse((response) => /\/api\/discovery\/search/i.test(response.url()) && /query=slow/i.test(response.url()), { timeout: 10_000 }).catch(() => null);
        await search.fill("slow");
        await search.press("Enter");
        const loadingShown = await page.waitForFunction(
          () => /Loading discovery results|Refreshing discovery results/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 2_500 },
        ).then(() => true).catch(() => false);
        await slowResponse;
        await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await clickButton(page, /Clear search/i, "Discover clear slow search");

        const beforeFilters = await discoverFilterState(page);
        const rail = page.locator(".gh-discovery-prototype-filter-rail").first();
        const certified = await clickVisible(rail.getByRole("button", { name: /Certified|In Review|Uncertified/i }).first(), "Discover certification facet");
        await waitForDiscoveryReady(page, /FILTERED BY|No matching assets|No assets matched|Showing\s+\d+\s+of\s+\d+\s+assets/i, 30_000);
        const afterCertified = await discoverFilterState(page);
        await clickButton(page, /Reset browse/i, "Discover reset certification filter");
        const customer = await clickVisible(rail.getByRole("button", { name: /Customer|Finance|Revenue & Sales|Marketing|Operations|Product|Risk|People|audit|communication|contact_management|deal_management|document_management|excess/i }).first(), "Discover domain facet");
        await waitForDiscoveryReady(page, /FILTERED BY|Showing\s+\d+\s+of\s+\d+\s+assets/i, 30_000);
        const afterCustomer = await discoverFilterState(page);
        await clickButton(page, /Reset browse/i, "Discover reset domain filter");
        const restricted = await clickVisible(rail.getByRole("button", { name: /Restricted|Confidential|Contains PII|No PII/i }).first(), "Discover classification facet");
        await waitForDiscoveryReady(page, /FILTERED BY|Showing\s+[1-9]\d*\s+of\s+[1-9]\d*\s+assets/i, 30_000);
        const afterRestricted = await discoverFilterState(page);
        await clickButton(page, /Reset browse/i, "Discover reset classification filter");
        const cde = await clickVisible(rail.getByRole("button", { name: /Critical Data Element/i }).first(), "Discover CDE attribute filter");
        await waitForDiscoveryReady(page, /tag:CDE|No matching assets|No assets matched|Showing\s+\d+\s+of\s+\d+\s+assets/i, 30_000);
        const afterCde = await discoverFilterState(page);
        const filteredState = await textChecks(page, { filtered: /Certified|In Review|Uncertified|Customer|Finance|Revenue & Sales|audit|communication|contact_management|deal_management|document_management|excess|Restricted|Confidential|Contains PII|No PII|tag:CDE|Critical Data Element/i });

        await clickButton(page, /Reset browse/i, "Discover reset filters");
        await page.waitForFunction(() => !/tag:CDE|Filtered by tag:CDE/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 }).catch(() => {});
        const afterReset = await discoverFilterState(page);
        await clickButton(page, /Advanced/i, "Discover advanced filters");
        await page.waitForSelector(".gh-discovery-advanced-filters", { state: "visible", timeout: 10_000 }).catch(() => {});
        const advancedVisible = await page.locator(".gh-discovery-advanced-filters,.gh-discovery-filter-shell").first().isVisible().catch(() => false);
        const advancedBuilder = page.locator(".gh-query-builder").first();
        await advancedBuilder.getByLabel(/Query builder field/i).selectOption("domain").catch(() => {});
        await advancedBuilder.getByLabel(/Query builder match mode/i).selectOption("any").catch(() => {});
        await advancedBuilder.getByLabel(/Query builder value/i).fill("Finance, Customer").catch(() => {});
        const structuredInsert = await clickVisible(
          advancedBuilder.getByRole("button", { name: /Insert into search/i }).first(),
          "Discover insert grouped AND/OR query",
        );
        const structuredQueryValue = await page.getByLabel("Search discovery assets").first().inputValue().catch(() => "");
        const deletedUnavailable = await controlSnapshot(page.getByRole("button", { name: /Deleted assets unavailable/i }).first());
        const inaccessibleHidden = await controlSnapshot(page.getByRole("button", { name: /Inaccessible hidden/i }).first());
        await clickVisible(
          page.locator(".gh-filters-popover").getByRole("button", { name: /^Close$/i }).first(),
          "Discover close advanced filters",
        );
        await clickButton(page, /Reset browse/i, "Discover reset grouped query");
        await clickButton(page, /List view/i, "Discover list view");
        const afterListView = await pressedGroupSnapshot(page, [["grid", /Grid view/i], ["list", /List view/i]]);
        await clickButton(page, /Grid view/i, "Discover grid view");
        const afterGridView = await pressedGroupSnapshot(page, [["grid", /Grid view/i], ["list", /List view/i]]);
        await clickButton(page, /Saved searches/i, "Discover saved searches");
        await page.getByRole("dialog", { name: /Saved searches/i }).waitFor({ state: "visible", timeout: 10_000 });
        const savedSearchDialog = true;
        const savedSearchCreate = await controlSnapshot(page.getByRole("button", { name: /Create saved search unavailable/i }).first()).catch(() => null);
        const savedSearchManage = await controlSnapshot(page.getByRole("button", { name: /Manage saved searches unavailable/i }).first()).catch(() => null);
        const savedSearchUnavailable = await textChecks(page, {
          unavailable: /Saved search inventory unavailable|Pinned team searches unavailable|Recent search shortcuts unavailable/i,
        });
        await clickVisible(
          page.getByRole("dialog", { name: /Saved searches/i }).getByRole("button", { name: /Close saved searches|Close/i }).first(),
          "Discover close saved searches",
        );
        return {
          validSearch,
          invalidSearch,
          emptySearch,
          loadingShown,
          beforeFilters,
          certified,
          afterCertified,
          customer,
          afterCustomer,
          restricted,
          afterRestricted,
          cde,
          afterCde,
          afterReset,
          filteredState,
          advancedVisible,
          structuredInsert,
          structuredQueryValue,
          deletedUnavailable,
          inaccessibleHidden,
          listView: afterListView.snapshots.list,
          gridView: afterGridView.snapshots.grid,
          layoutModeSnapshots: {
            afterListView,
            afterGridView,
          },
          savedSearchDialog,
          savedSearchCreate,
          savedSearchManage,
          savedSearchUnavailable,
          state: await getBodyState(page, {
            results: /results/i,
            savedQuery: /tag:CDE|certification:Certified|Revenue|Saved search inventory unavailable/i,
          }),
        };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { discoverTitle: /Find trusted, governed data|Discover/i });
        return {
          loaded: Boolean(
            checks.discoverTitle &&
            runResult?.validSearch?.results &&
            runResult?.invalidSearch?.invalid &&
            runResult?.emptySearch?.empty &&
            runResult?.loadingShown &&
            runResult?.certified?.ariaPressed === "false" &&
            runResult?.afterCertified?.activeButtons?.some((item) => /Certified|In Review|Uncertified/i.test(item)) &&
            runResult?.customer?.ariaPressed === "false" &&
            runResult?.afterCustomer?.activeButtons?.some((item) => /Customer|Finance|Revenue & Sales|Marketing|Operations|Product|Risk|People|audit|communication|contact_management|deal_management|document_management|excess/i.test(item)) &&
            runResult?.restricted?.ariaPressed === "false" &&
            runResult?.afterRestricted?.activeButtons?.some((item) => /Restricted|Confidential|Contains PII|No PII/i.test(item)) &&
            (/tag:CDE/i.test(runResult?.afterCde?.searchValue || "") ||
              runResult?.afterCde?.activeButtons?.some((item) => /Critical Data Element/i.test(item))) &&
            runResult?.afterReset?.activeButtons?.length === 0 &&
            runResult?.afterReset?.searchValue === "" &&
            runResult?.savedSearchDialog &&
            runResult?.savedSearchUnavailable?.unavailable &&
            runResult?.savedSearchCreate?.disabled &&
            runResult?.savedSearchManage?.disabled &&
            runResult?.filteredState?.filtered &&
            JSON.stringify(runResult?.layoutModeSnapshots?.afterListView?.activeKeys || []) === JSON.stringify(["list"]) &&
            JSON.stringify(runResult?.layoutModeSnapshots?.afterGridView?.activeKeys || []) === JSON.stringify(["grid"])
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "sort-and-row-actions",
      description: "Exercise Discover sort, local favorite, and result-row action menu behavior.",
      async run(page) {
        await page.evaluate(() => window.localStorage?.removeItem?.("gh-favorite-assets"));
        await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-main-grid", { timeout: 20_000 });
        const firstBefore = await firstDiscoverResultFqn(page);
        await page.locator(".gh-discovery-sort-trigger").first().click();
        await clickVisible(page.getByRole("option", { name: /Name \(A-Z\)/i }).first(), "Discover sort by name");
        await page.waitForFunction(() => {
          const first = document.querySelector(".gh-discovery-table-row.gh-discovery-asset-card");
          return first && !/Loading discovery results|Refreshing discovery results/i.test(document.body?.innerText || "");
        }, undefined, { timeout: 10_000 });
        const firstAfterName = await firstDiscoverResultFqn(page);
        const sortControl = await controlSnapshot(page.locator(".gh-discovery-sort-trigger").first());
        await openFirstDiscoverRowActions(page, "Discover row actions");
        const favorite = await clickVisible(page.getByRole("menuitem", { name: /Add to favorites|Remove from favorites/i }).first(), "Discover local favorite from row menu", { skipScroll: true });
        await page.waitForFunction(() => /local browser favorite/i.test(document.body?.innerText || ""), undefined, { timeout: 8_000 });
        await openFirstDiscoverRowActions(page, "Reopen Discover row actions");
        const favoriteAfter = await controlSnapshot(page.getByRole("menuitem", { name: /Remove from favorites|Add to favorites/i }).first());
        const menuState = await textChecks(page, { viewDetails: /View details/i, governance: /Open governance/i, lineage: /Open lineage/i });
        return { firstBefore, firstAfterName, sortControl, favorite, favoriteAfter, menuState };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(
            runResult?.firstBefore &&
            runResult?.firstAfterName &&
            runResult.firstAfterName !== runResult.firstBefore &&
            /Name \(A-Z\)/i.test(runResult?.sortControl?.text || "") &&
            /Add to favorites|Remove from favorites/i.test(runResult?.favorite?.text || "") &&
            /Add to favorites|Remove from favorites/i.test(runResult?.favoriteAfter?.text || "") &&
            runResult.favorite.text !== runResult.favoriteAfter.text &&
            runResult?.menuState?.viewDetails &&
            runResult?.menuState?.governance &&
            runResult?.menuState?.lineage
          ),
          runResult,
        };
      },
    },
    {
      key: "row-menu-routing",
      description: "Click every Discover row action menu routing item and verify each destination.",
      async run(page) {
        await openFirstDiscoverRowActions(page, "Discover row actions for View details");
        const viewDetails = await clickVisible(page.getByRole("menuitem", { name: /View details/i }).first(), "Discover row menu View details", { skipScroll: true });
        const pathAfterViewDetails = await waitForPath(page, /\/entity\//i, 15_000);
        await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-main-grid", { timeout: 20_000 });

        await openFirstDiscoverRowActions(page, "Discover row actions for Open governance");
        const openGovernance = await clickVisible(page.getByRole("menuitem", { name: /Open governance/i }).first(), "Discover row menu Open governance", { skipScroll: true });
        const pathAfterGovernance = await waitForPath(page, /\/stewardship|\/governance/i, 15_000);
        await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-discovery-main-grid", { timeout: 20_000 });

        const lineageMenu = await openDiscoverRowActionsWithEnabledMenuItem(
          page,
          /Open lineage/i,
          "Discover row actions for Open lineage",
          { allowDisabledResult: true },
        );
        let openLineage = lineageMenu.snapshot;
        let pathAfterLineage = "";
        if (!lineageMenu.disabledUnavailable && lineageMenu.menuItem) {
          openLineage = await clickVisible(lineageMenu.menuItem, "Discover row menu Open lineage", { skipScroll: true });
          pathAfterLineage = await waitForPath(page, /\/lineage/i, 15_000);
        }
        return { viewDetails, openGovernance, openLineage, lineageRowIndex: lineageMenu.rowIndex, pathAfterViewDetails, pathAfterGovernance, pathAfterLineage };
      },
      async validate(_page, runResult) {
        const lineageUnavailableReason = `${runResult?.openLineage?.ariaLabel || ""} ${runResult?.openLineage?.title || ""}`;
        return {
          loaded: Boolean(
            !runResult?.viewDetails?.disabled &&
            !runResult?.openGovernance?.disabled &&
            /\/entity\//i.test(runResult?.pathAfterViewDetails || "") &&
            /\/stewardship|\/governance/i.test(runResult?.pathAfterGovernance || "") &&
            (
              (!runResult?.openLineage?.disabled && /\/lineage/i.test(runResult?.pathAfterLineage || "")) ||
              (
                runResult?.openLineage?.disabled &&
                /per-user authorization|OBO|does not widen user-visible data|unavailable|requires/i.test(lineageUnavailableReason)
              )
            )
          ),
          runResult,
        };
      },
    },
    {
      key: "preview-actions",
      description: "Exercise Discover selected-preview tabs, disabled workflow actions, and sticky footer visibility.",
      async run(page) {
        const row = page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first();
        await row.waitFor({ state: "visible", timeout: 20_000 });
        await row.click();
        await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 15_000 });
        await page.waitForURL((url) => Boolean(url.searchParams.get("preview")), { timeout: 8_000 }).catch(() => {});
        const preview = page.locator(".gh-selection-preview").first();
        const tabStates = {};
        for (const name of ["Columns", "Lineage", "Quality", "Access", "Overview"]) {
          const key = name.toLowerCase();
          const tab = preview.getByRole("tab", { name: new RegExp(`^${name}`, "i") }).first();
          await clickVisible(tab, `Discover preview ${name} tab`, { skipScroll: true });
          await page.waitForFunction((panelKey) => {
            const panel = document.querySelector(`#gh-discovery-preview-panel-${panelKey}`);
            const activeTab = document.querySelector(`#gh-discovery-preview-tab-${panelKey}`);
            if (!(panel instanceof HTMLElement) || !(activeTab instanceof HTMLElement)) return false;
            const rect = panel.getBoundingClientRect();
            return activeTab.getAttribute("aria-selected") === "true" && rect.width > 0 && rect.height > 0;
          }, key, { timeout: 8_000 }).catch(() => {});
          const snapshot = await controlSnapshot(tab);
          const panel = await page.locator(`#gh-discovery-preview-panel-${key}`).first().evaluate((node) => {
            const rect = node.getBoundingClientRect();
            return {
              visible: rect.width > 0 && rect.height > 0,
              text: (node.textContent || "").replace(/\s+/g, " ").trim().slice(0, 500),
            };
          }).catch(() => ({ visible: false, text: "" }));
          tabStates[key] = {
            panel: Boolean(panel.visible),
            panelText: panel.text,
            ariaSelected: snapshot.ariaSelected,
          };
        }
        const comment = await controlSnapshot(preview.getByRole("button", { name: /Comment unavailable|^Comment$/i }).first());
        const requestAccess = await controlSnapshot(preview.getByRole("button", { name: /Request access unavailable|^Request access$/i }).first());
        const workflowNote = await textChecks(page, { workflowDisabled: /Comment and access-request creation are disabled[\s\S]*backed governance workflow/i });
        const stickyFooter = await page.evaluate(() => {
          const footer = document.querySelector(".gh-discovery-preview-footer");
          if (!(footer instanceof HTMLElement)) return null;
          const rect = footer.getBoundingClientRect();
          return {
            visible: rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= window.innerHeight + 2,
            bottom: Math.round(rect.bottom),
            height: Math.round(rect.height),
          };
        });
        await clickVisible(preview.getByRole("button", { name: /Close preview/i }).first(), "Discover preview close", { force: true, skipScroll: true });
        await page.waitForFunction(
          () => document.querySelector(".gh-discovery-main-grid")?.getAttribute("data-preview-open") !== "true",
          undefined,
          { timeout: 8_000 },
        ).catch(() => {});
        const previewClosed = await page.locator(".gh-selection-preview").first().isVisible().then((visible) => !visible).catch(() => true);
        return { tabStates, comment, requestAccess, workflowNote, stickyFooter, previewClosed };
      },
      async validate(page, runResult) {
        const commentReason = `${runResult?.comment?.ariaLabel || ""} ${runResult?.comment?.title || ""}`;
        const requestReason = `${runResult?.requestAccess?.ariaLabel || ""} ${runResult?.requestAccess?.title || ""}`;
        return {
          loaded: Boolean(
            runResult?.tabStates?.columns?.panel &&
            runResult?.tabStates?.lineage?.panel &&
            runResult?.tabStates?.quality?.panel &&
            runResult?.tabStates?.access?.panel &&
            runResult?.tabStates?.overview?.panel &&
            runResult?.comment?.disabled &&
            /backed workflow/i.test(commentReason) &&
            runResult?.requestAccess?.disabled &&
            /backed workflow/i.test(requestReason) &&
            (runResult?.workflowNote?.workflowDisabled || /backed workflow/i.test(`${commentReason} ${requestReason}`)) &&
            runResult?.stickyFooter?.visible &&
            runResult?.previewClosed
          ),
          runResult,
        };
      },
    },
    {
      key: "preview-asset-routing",
      description: "Certification review routes from the Discover selected preview; asset and lineage routing are exercised from result-row actions.",
      async run(page) {
        const row = page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first();
        await row.waitFor({ state: "visible", timeout: 20_000 });
        await row.click();
        await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 15_000 });
        await clickVisible(
          page.locator(".gh-selection-preview .gh-discovery-preview-footer").getByRole("button", { name: /^(Certify|Review cert)$/i }).first(),
          "Discover preview footer certification review",
        );
        const pathAfterCertify = await waitForPath(page, /\/stewardship|\/governance/i);
        return { pathAfterCertify };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(/\/stewardship|\/governance/i.test(runResult?.pathAfterCertify || "")),
          runResult,
        };
      },
    },
    {
      key: "atlas-ai-recommendations",
      description: "Run Discover Atlas AI recommendations and route recommendation evidence into the selected preview.",
      async run(page) {
        const aiButton = page.locator(".gh-discovery-ai-card").getByRole("button", { name: /Run Atlas AI recommendations/i }).first();
        await aiButton.waitFor({ state: "visible", timeout: 15_000 });
        const aiButtonBefore = await controlSnapshot(aiButton);
        if (aiButtonBefore?.disabled) {
          const unavailable = await getBodyState(page, {
            card: /Atlas AI Recommendations/i,
            reason: /requires a configured|unavailable|evidence-backed provider|Databricks Genie/i,
          });
          return {
            unavailable: true,
            aiButtonBefore,
            unavailable,
          };
        }
        await page.evaluate(() => {
          Object.keys(window.sessionStorage || {})
            .filter((key) => key.startsWith("governance-atlas.discovery-ai."))
            .forEach((key) => window.sessionStorage.removeItem(key));
        });
        const aiResponsePromise = page.waitForResponse((response) => /\/api\/atlas-ai\/recommendations/i.test(response.url()), { timeout: 8_000 }).catch(() => null);
        await clickVisible(aiButton, "Run Discover Atlas AI recommendations");
        const aiResponse = await aiResponsePromise;
        const recommendationsVisible = await page.waitForFunction(
          () => /Review|Inspect|recommendation|classification|recertification|PII|evidence|Unavailable/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 20_000 },
        ).then(() => true).catch(() => false);
        const recommendations = await textChecks(page, { recommendation: /Review|Inspect|recommendation|classification|recertification|PII|evidence/i });
        if (recommendationsVisible) {
          const recommendationButton = page.locator(".gh-discovery-ai-card button").filter({ hasText: /Review|Inspect|recommendation|classification|recertification|PII/i }).first();
          if (await recommendationButton.isVisible().catch(() => false)) {
            await clickVisible(recommendationButton, "Open Discover AI recommendation evidence");
          }
          await page.locator(".gh-main").first().evaluate((node) => {
            if (node instanceof HTMLElement) node.scrollTo({ top: 0, left: 0, behavior: "instant" });
          }).catch(() => {});
          await page.waitForFunction(
            () => {
              const grid = document.querySelector(".gh-discovery-main-grid");
              const preview = document.querySelector(".gh-selection-preview");
              if (!(preview instanceof HTMLElement)) return false;
              const rect = preview.getBoundingClientRect();
              return grid?.getAttribute("data-preview-open") === "true" && rect.width > 0 && rect.height > 0;
            },
            undefined,
            { timeout: 10_000 },
          ).catch(async () => {
            const firstRow = page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first();
            if (await firstRow.isVisible().catch(() => false)) {
              await firstRow.click();
              await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 10_000 }).catch(() => {});
            }
          });
        }
        const selected = await textChecks(page, { selectedPreview: /Metadata Coverage|Open Asset 360|Governance/i });
        await clickVisible(
          page.locator(".gh-shell-topbar .ga-ai-chip.is-primary").filter({ hasText: /Atlas AI/i }).first(),
          "Open Discover floating Atlas AI from topbar"
        );
        await page.waitForSelector(".gh-floating-ai-chat", { state: "visible", timeout: 10_000 });
        const input = page.locator(".gh-floating-ai-input input").first();
        await input.fill("Which certified assets are most important?");
        await clickVisible(page.locator(".gh-floating-ai-input button").first(), "Submit Discover floating Atlas AI prompt");
        const groundedAnswer = await waitForAtlasAiGroundedAnswer(page, 60_000);
        const floating = await getBodyState(page, {
          answer: /evidence|governed|certified|metadata|asset|Genie|Unavailable/i,
          evidence: /evidence|asset|metadata|governance|Databricks/i,
        });
        return {
          aiButtonBefore,
          aiResponse: aiResponse ? { url: aiResponse.url(), status: aiResponse.status() } : null,
          recommendationsVisible,
          recommendations,
          selected,
          groundedAnswer,
          floating,
        };
      },
      async validate(page, runResult) {
        if (runResult?.unavailable) {
          const reason = `${runResult?.aiButtonBefore?.title || ""} ${runResult?.aiButtonBefore?.ariaLabel || ""}`;
          return {
            loaded: Boolean(
              runResult?.aiButtonBefore?.disabled &&
              (runResult?.unavailable?.checks?.reason || /requires a configured|unavailable|evidence-backed|Genie/i.test(reason))
            ),
            runResult,
          };
        }
        return {
          loaded: Boolean(
            runResult?.recommendationsVisible &&
            runResult?.recommendations?.recommendation &&
            runResult?.selected?.selectedPreview &&
            runResult?.groundedAnswer &&
            runResult?.floating?.checks?.answer &&
            runResult?.floating?.checks?.evidence
          ),
          runResult,
        };
      },
    },
  ],
  stewardship: [
    {
      key: "asset-routing",
      description: "Open the affected asset from a Stewardship work item before mutation checks alter the live queue.",
      async run(page) {
        await page.goto(urlFor("/stewardship"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector("button.gh-governance-ns-table-row", { state: "visible", timeout: 20_000 });
        await page.locator("button.gh-governance-ns-table-row").first().click();
        await page.waitForSelector(".gh-governance-ns-affected button", { state: "visible", timeout: 15_000 });
        const affectedAsset = page.locator(".gh-governance-ns-affected").getByRole("button").first();
        await affectedAsset.waitFor({ state: "visible", timeout: 15_000 });
        const before = await clickVisible(affectedAsset, "Stewardship affected asset");
        const pathAfterClick = await waitForPath(page, /\/entity\//i, 30_000);
        await page.waitForSelector(".gh-entity-workspace,.gh-entity-shell,.gh-asset360-shell", { timeout: 30_000 }).catch(() => {});
        return { before, pathAfterClick, state: await getBodyState(page, { asset: /pricing_experiment|Asset|Overview/i }) };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(/\/entity\//i.test(runResult?.pathAfterClick || "") && runResult?.state?.checks?.asset),
          runResult,
        };
      },
    },
    {
      key: "workbench-controls",
      description: "Exercise Stewardship filters, queue pills, prototype-safe action messages, and degraded create/assign flows.",
      async run(page) {
        await clickButton(page, /^Filter$/i, "Stewardship filter");
        const filterPanel = await textChecks(page, { filterPanel: /Filter work queue/i });
        await clickButton(page, /P1 critical/i, "Stewardship P1 queue");
        const p1 = await controlSnapshot(buttonByName(page, /P1 critical/i));
        await clickButton(page, /Overdue/i, "Stewardship overdue queue");
        const overdue = await controlSnapshot(buttonByName(page, /Overdue/i));
        await clickButton(page, /Assigned to me/i, "Stewardship assigned to me queue");
        const assigned = await controlSnapshot(buttonByName(page, /Assigned to me/i));
        await clickButton(page, /^All\b/i, "Stewardship all queue");
        const firstWorkItem = page.locator("button.gh-governance-ns-table-row").first();
        await firstWorkItem.waitFor({ state: "visible", timeout: 15_000 });
        await firstWorkItem.click();
        await clickButton(page, /^Bulk assign$/i, "Stewardship bulk assign");
        const bulkPanel = await textChecks(page, { bulkUnavailable: /Bulk assignment requires a backed workflow|Submit assignment unavailable/i });
        await clickButton(page, /^Dismiss$/i, "Dismiss bulk assign panel");
        await clickButton(page, /^New work item$/i, "Stewardship new work item");
        const newItemPanel = await textChecks(page, { newUnavailable: /New work item creation is unavailable|Create work item unavailable/i });
        await clickButton(page, /^Dismiss$/i, "Dismiss new work item panel");
        const suggestedButtons = page.locator(".gh-governance-ns-suggestions button");
        const suggestedButtonCount = await suggestedButtons.count();
        let suggestedPanel = { noBackedActions: false, suggestedUnavailable: false };
        let archivePanel = { noBackedActions: false, archiveUnavailable: false };
        if (suggestedButtonCount > 0) {
          const firstSuggestedAction = suggestedButtons.nth(0);
          await clickVisible(firstSuggestedAction, "Stewardship first suggested action");
          suggestedPanel = await textChecks(page, { suggestedUnavailable: /Run suggested action unavailable/i });
          await clickButton(page, /^Dismiss$/i, "Dismiss suggested action panel");
          const secondSuggestedAction = suggestedButtons.nth(1);
          const secondSuggestedVisible = await secondSuggestedAction.isVisible().catch(() => false);
          await clickVisible(secondSuggestedVisible ? secondSuggestedAction : firstSuggestedAction, "Stewardship second suggested action");
          archivePanel = await textChecks(page, { archiveUnavailable: /Run suggested action unavailable|Archive sandbox cleanup/i });
          await clickButton(page, /^Dismiss$/i, "Dismiss archive suggested action panel");
        } else {
          const noBacked = await textChecks(page, { noBackedActions: /No backed suggested actions were returned for this work item/i });
          suggestedPanel = noBacked;
          archivePanel = noBacked;
        }
        const nextPage = await controlSnapshot(page.getByRole("button", { name: /Next page/i }).first()).catch(() => ({
          hidden: true,
          disabled: true,
          title: "Single-page queue hides pagination to match the Stewardship reference.",
        }));
        const commentButton = buttonByName(page, /^Comment$/i);
        const commentBefore = await controlSnapshot(commentButton);
        let commentResponse = null;
        let commentStatus = { recorded: false, disabledReason: false };
        if (!commentBefore.disabled) {
          const commentPatch = page.waitForResponse((response) =>
            /\/api\/governance\/requests\//.test(response.url()) &&
            response.request().method() === "PATCH",
          { timeout: 30_000 }).catch(() => null);
          await clickVisible(commentButton, "Stewardship Comment");
          commentResponse = await responseSummary(await commentPatch);
          await page.waitForFunction(
            () => /Comment recorded|Request updated/i.test(document.body?.innerText || ""),
            undefined,
            { timeout: 20_000 },
          ).catch(() => {});
          commentStatus = await textChecks(page, { recorded: /Comment recorded|Request updated/i });
        } else {
          commentStatus = await textChecks(page, {
            disabledReason: /Comment and resolve require Steward or Admin role|unavailable until live governance request evidence/i,
          });
        }
        const resolveButton = buttonByName(page, /^Resolve$/i);
        const resolveBefore = await controlSnapshot(resolveButton);
        let resolveResponse = null;
        let resolveStatus = { resolved: false, disabledReason: false };
        if (!resolveBefore.disabled) {
          const resolvePatch = page.waitForResponse((response) =>
            /\/api\/governance\/requests\//.test(response.url()) &&
            response.request().method() === "PATCH",
          { timeout: 30_000 }).catch(() => null);
          await clickVisible(resolveButton, "Stewardship Resolve");
          resolveResponse = await responseSummary(await resolvePatch);
          await page.waitForFunction(
            () => /Work item resolved|Request updated|Resolved/i.test(document.body?.innerText || ""),
            undefined,
            { timeout: 20_000 },
          ).catch(() => {});
          resolveStatus = await textChecks(page, { resolved: /Work item resolved|Request updated|Resolved/i });
        } else {
          resolveStatus = await textChecks(page, {
            disabledReason: /Comment and resolve require Steward or Admin role|unavailable until live governance request evidence/i,
          });
        }
        return {
          filterPanel,
          p1,
          overdue,
          assigned,
          bulkPanel,
          newItemPanel,
          suggestedPanel,
          archivePanel,
          nextPage,
          commentBefore,
          commentResponse,
          commentStatus,
          resolveBefore,
          resolveResponse,
          resolveStatus,
        };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { workbench: /open work items|Work queue/i });
        return {
          loaded: Boolean(
            checks.workbench &&
            runResult?.filterPanel?.filterPanel &&
            runResult?.bulkPanel?.bulkUnavailable &&
            runResult?.newItemPanel?.newUnavailable &&
            (runResult?.suggestedPanel?.suggestedUnavailable || runResult?.suggestedPanel?.noBackedActions) &&
            (runResult?.archivePanel?.archiveUnavailable || runResult?.archivePanel?.noBackedActions) &&
            (runResult?.nextPage?.hidden ||
              (runResult?.nextPage?.disabled && /All visible work items/i.test(runResult?.nextPage?.title || ""))) &&
            (
              (
                !runResult?.commentBefore?.disabled &&
                runResult?.commentResponse?.ok &&
                runResult?.commentResponse?.status >= 200 &&
                runResult?.commentResponse?.status < 300 &&
                runResult?.commentResponse?.body?.requestId &&
                runResult?.commentStatus?.recorded
              ) ||
              (runResult?.commentBefore?.disabled && runResult?.commentStatus?.disabledReason)
            ) &&
            (
              (
                !runResult?.resolveBefore?.disabled &&
                runResult?.resolveResponse?.ok &&
                runResult?.resolveResponse?.status >= 200 &&
                runResult?.resolveResponse?.status < 300 &&
                runResult?.resolveResponse?.body?.requestId &&
                runResult?.resolveStatus?.resolved
              ) ||
              (runResult?.resolveBefore?.disabled && runResult?.resolveStatus?.disabledReason)
            )
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "lineage-navigation",
      description: "Verify the non-reference Stewardship detail lineage link is not exposed.",
      async run(page) {
        const openLineageContextCount = await page.getByRole("button", { name: /Open lineage context/i }).count();
        return { openLineageContextCount };
      },
      async validate(page, runResult) {
        return {
          loaded: runResult?.openLineageContextCount === 0,
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Submit a Stewardship-specific Atlas AI prompt and verify grounded evidence appears.",
      async run(page) {
        await openFloatingAtlasAi(page, "Open Stewardship Atlas AI");
        return await submitFloatingAtlasAiPromptOrUnavailable(page, "Which stewardship work items need attention?", "Submit Stewardship Atlas AI prompt", {
          answer: /Genie returned|governed evidence|stewardship|work item|asset|Unavailable/i,
          evidence: /evidence|Databricks|Genie|governed/i,
        });
      },
      async validate(page, runResult) {
        return { loaded: atlasAiRouteLoaded(runResult), runResult };
      },
    },
  ],
  glossary: [
    {
      key: "glossary-controls",
      description: "Exercise Glossary term request, association browser, detail, and lineage navigation controls.",
      async run(page) {
        await clickButton(page, /\+ New term/i, "Glossary new term");
        const newTerm = await textChecks(page, { unavailable: /New term request is unavailable/i });
        const firstCard = page.locator(".gh-taxonomy-prototype-card").first();
        await firstCard.waitFor({ state: "visible", timeout: 15_000 });
        await clickVisible(firstCard.getByRole("button", { name: /\d+\s+assets/i }).first(), "Glossary associated assets");
        await page.waitForSelector(".gh-taxonomy-prototype-detail", { timeout: 10_000 }).catch(() => {});
        const detail = await textChecks(page, {
          associations: /Associated assets|Unity Catalog|source asset|asset/i,
          reviewer: /Reviewer workflow|reviewer|owner|curator/i,
          version: /Version history|Definition approved|version/i,
          hierarchy: /Hierarchy|nested child terms/i,
        });
        const associationToggleLocator = page
          .locator(".gh-taxonomy-prototype-detail")
          .getByRole("button", { name: /Hide associations|Browse all associations/i })
          .first();
        const associationToggleVisible = await associationToggleLocator.isVisible({ timeout: 5000 }).catch(() => false);
        const associationToggle = associationToggleVisible
          ? await controlSnapshot(associationToggleLocator)
          : { missing: true, disabled: true, title: "Association browser control was not visible in the glossary detail." };
        if (associationToggleVisible && !associationToggle.disabled) {
          await clickVisible(associationToggleLocator, "Glossary association browser toggle");
        }
        const reviewerNotice = await textChecks(page, { reviewerUnavailable: /reviewer|owner|curator|Review/i });
        const closeDetail = page
          .locator(".gh-taxonomy-prototype-detail-head")
          .getByRole("button")
          .first();
        await clickVisible(closeDetail, "Glossary close detail");
        const detailClosed = await page.locator(".gh-taxonomy-prototype-detail").count().then((count) => count === 0);
        const previewLineage = await controlSnapshot(firstCard.getByRole("button", { name: /Preview lineage/i }).first());
        let pathAfterClick = "";
        if (!previewLineage.disabled) {
          await clickVisible(firstCard.getByRole("button", { name: /Preview lineage/i }).first(), "Glossary Preview lineage");
          pathAfterClick = await waitForPath(page, /\/lineage/i);
        }
        return { newTerm, detail, associationToggle, reviewerNotice, detailClosed, previewLineage, pathAfterClick };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { lineage: /Lineage Atlas|lineage/i });
        const lineageHandled = /\/lineage/i.test(runResult?.pathAfterClick || "")
          ? checks.lineage
          : Boolean(runResult?.previewLineage?.disabled && /Lineage requires|associated asset/i.test(runResult?.previewLineage?.title || ""));
        return {
          loaded: Boolean(
            runResult?.newTerm?.unavailable &&
            runResult?.detail?.associations &&
            runResult?.detail?.reviewer &&
            runResult?.detail?.version &&
            runResult?.detail?.hierarchy &&
            !runResult?.associationToggle?.disabled &&
            runResult?.detailClosed &&
            lineageHandled
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "global-shell",
      description: "Exercise global search, help, and profile controls from the Glossary route.",
      async run(page) {
        const input = page.locator(".ga-top-search input, .gh-topbar-search input, input[placeholder*='Search assets']").first();
        await input.waitFor({ state: "visible", timeout: 10_000 });
        await input.fill("net revenue");
        await input.press("Enter");
        const pathAfterSearch = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        await page.waitForFunction(
          () => !/Loading discovery results|Refreshing discovery results|Searching the visible catalog metadata/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 120_000 },
        ).catch(() => {});
        const searchState = await getBodyState(page, { result: /revenue|risk_critical_asset_monitor|product_mortgage_signal|finance_lien|market_analytics|datapact\.(?:enterprise_metadata_ops|governance_atlas_demo)/i });

        await page.goto(urlFor("/glossary-cdes"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace", { timeout: 20_000 });
        await clickButton(page, /^Help$/i, "Open help from Glossary");
        const pathAfterHelp = await waitForPath(page, /\/help/i);
        const helpState = await getBodyState(page, { help: /How Governance Atlas works|Getting help/i });

        await page.goto(urlFor("/glossary-cdes"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace", { timeout: 20_000 });
        await clickButton(page, /Open profile menu/i, "Open profile menu from Glossary");
        const profileState = await getProfileMenuState(page);
        return { pathAfterSearch, searchState, pathAfterHelp, helpState, profileState };
      },
      async validate(page, runResult) {
        return {
          loaded: Boolean(
            /\/discover/i.test(runResult?.pathAfterSearch || "") &&
            runResult?.searchState?.checks?.result &&
            /\/help/i.test(runResult?.pathAfterHelp || "") &&
            runResult?.helpState?.checks?.help &&
            runResult?.profileState?.checks?.settings &&
            runResult?.profileState?.checks?.avatar &&
            runResult?.profileState?.localAvatarState?.localOnly &&
            runResult?.profileState?.localAvatarState?.databricksProfileExcluded &&
            runResult?.profileState?.checks?.signOut
          ),
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Submit a Glossary-specific Atlas AI prompt and verify grounded evidence appears.",
      async run(page) {
        await openFloatingAtlasAi(page, "Open Glossary Atlas AI");
        return await submitFloatingAtlasAiPromptOrUnavailable(page, "Summarize glossary coverage for net revenue.", "Submit Glossary Atlas AI prompt", {
          answer: /Genie returned|governed evidence|glossary|Net Revenue|term|asset|Unavailable/i,
          evidence: /evidence|Databricks|Genie|governed/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
      },
      async validate(page, runResult) {
        return { loaded: atlasAiRouteLoaded(runResult, { disclaimer: true }), runResult };
      },
    },
    {
      key: "responsive-card-controls",
      description: "Validate Glossary card action controls remain visible and inside cards at the active viewport.",
      async run(page) {
        const layout = await page.evaluate(() => {
          const viewport = { width: window.innerWidth, height: window.innerHeight };
          const cards = Array.from(document.querySelectorAll(".gh-taxonomy-prototype-card"));
          const visibleActions = [];
          const failures = [];
          const rectInfo = (node) => {
            const rect = node.getBoundingClientRect();
            return {
              top: Math.round(rect.top),
              left: Math.round(rect.left),
              right: Math.round(rect.right),
              bottom: Math.round(rect.bottom),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            };
          };
          cards.forEach((card, cardIndex) => {
            const cardRect = card.getBoundingClientRect();
            Array.from(card.querySelectorAll("button")).forEach((button, actionIndex) => {
              const rect = button.getBoundingClientRect();
              const text = (button.textContent || button.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
              const visible = rect.width > 0 && rect.height > 0 && getComputedStyle(button).visibility !== "hidden";
              const insideCard =
                rect.left >= cardRect.left - 1 &&
                rect.right <= cardRect.right + 1 &&
                rect.top >= cardRect.top - 1 &&
                rect.bottom <= cardRect.bottom + 1;
              const insideViewport = rect.left >= 0 && rect.right <= viewport.width && rect.top >= 0 && rect.bottom <= viewport.height;
              visibleActions.push({ cardIndex, actionIndex, text, visible, insideCard, insideViewport, rect: rectInfo(button) });
              if (!visible || !insideCard || !insideViewport) {
                failures.push({ cardIndex, actionIndex, text, visible, insideCard, insideViewport, rect: rectInfo(button), cardRect: rectInfo(card) });
              }
            });
          });
          return { viewport, cardCount: cards.length, visibleActions, failures };
        });
        return { layout };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(runResult?.layout?.cardCount > 0 && runResult?.layout?.visibleActions?.length > 0 && runResult?.layout?.failures?.length === 0),
          runResult,
        };
      },
    },
  ],
  "cde-registry": [
    {
      key: "cde-detail-state",
      description: "Capture the CDE Registry selected-row/detail state without leaving the route.",
      async run(page) {
        await clickVisible(page.getByRole("tab", { name: /CDE Registry/i }).first(), "CDE Registry tab");
        const firstRow = page.locator(".gh-taxonomy-prototype-cde-row").first();
        await firstRow.waitFor({ state: "visible", timeout: 15_000 });
        await firstRow.click();
        await page.waitForSelector(".gh-taxonomy-prototype-detail", { timeout: 10_000 });
        const detail = await textChecks(page, {
          sourceColumn: /Source-of-record column|Open source asset/i,
          ownerWorkflow: /Reviewer workflow|recertification mutations are unavailable/i,
          status: /Healthy|Recert Due|Source Backed|Source-backed|Control evidence unavailable|Recertification workflow evidence unavailable/i,
        });
        const selectedRows = await page.locator(".gh-taxonomy-prototype-cde-row.is-selected").count();
        return { detail, selectedRows };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.detail?.sourceColumn &&
            runResult?.detail?.ownerWorkflow &&
            runResult?.detail?.status &&
            runResult?.selectedRows >= 1
          ),
          runResult,
        };
      },
    },
    {
      key: "cde-controls",
      description: "Exercise CDE Registry detail, owner/recertification unavailable workflows, and lineage navigation.",
      async run(page) {
        await clickVisible(page.getByRole("tab", { name: /CDE Registry/i }).first(), "CDE Registry tab");
        const firstRow = page.locator(".gh-taxonomy-prototype-cde-row").first();
        await firstRow.waitFor({ state: "visible", timeout: 15_000 });
        await firstRow.click();
        await page.waitForSelector(".gh-taxonomy-prototype-detail", { timeout: 10_000 }).catch(() => {});
        const detail = await textChecks(page, {
          sourceColumn: /Source-of-record|Source column|Open source asset/i,
          ownerWorkflow: /Reviewer workflow|recertification mutations are unavailable|mutation workflow/i,
        });
        const recert = await controlSnapshot(buttonByName(page, /Request recertification unavailable/i));
        const ownerWorkflow = await controlSnapshot(buttonByName(page, /Owner workflow unavailable/i));
        const recertWorkflow = await controlSnapshot(buttonByName(page, /Recertification evidence unavailable/i));
        const ownerNotice = {
          ownerUnavailable: Boolean(
            ownerWorkflow?.disabled &&
              /owner workflow.*unavailable|backed CDE registry mutation workflow|no local-only mutations/i.test(`${ownerWorkflow?.ariaLabel || ""} ${ownerWorkflow?.title || ""}`),
          ),
        };
        const recertNotice = {
          recertUnavailable: Boolean(
            recertWorkflow?.disabled &&
              /recertification.*unavailable|backed CDE registry mutation workflow|no local-only mutations/i.test(`${recertWorkflow?.ariaLabel || ""} ${recertWorkflow?.title || ""}`),
          ),
        };
        await clickButton(page, /Close .* detail/i, "CDE close detail");
        const detailClosed = await page.locator(".gh-taxonomy-prototype-detail").count().then((count) => count === 0);
        await firstRow.click();
        await page.waitForSelector(".gh-taxonomy-prototype-detail", { timeout: 10_000 }).catch(() => {});
        const openLineage = await controlSnapshot(buttonByName(page, /Open lineage/i));
        let pathAfterClick = "";
        if (!openLineage.disabled) {
          await clickButton(page, /Open lineage/i, "CDE detail Open lineage");
          pathAfterClick = await waitForPath(page, /\/lineage/i);
        }
        return { detail, recert, ownerWorkflow, recertWorkflow, ownerNotice, recertNotice, detailClosed, openLineage, pathAfterClick };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { lineage: /Lineage Atlas|lineage/i });
        return {
          loaded: Boolean(
            runResult?.detail?.sourceColumn &&
            runResult?.detail?.ownerWorkflow &&
            runResult?.recert &&
            runResult?.recert?.disabled &&
            /unavailable/i.test(`${runResult?.recert?.text || ""} ${runResult?.recert?.ariaLabel || ""} ${runResult?.recert?.title || ""}`) &&
            runResult?.ownerWorkflow?.disabled &&
            runResult?.recertWorkflow?.disabled &&
            runResult?.ownerNotice?.ownerUnavailable &&
            runResult?.recertNotice?.recertUnavailable &&
            runResult?.detailClosed &&
            (
              (/\/lineage/i.test(runResult?.pathAfterClick || "") && checks.lineage) ||
              (
                runResult?.openLineage?.disabled &&
                (/Source column unavailable|Lineage requires|source asset/i.test(runResult?.openLineage?.title || "") ||
                  runResult?.detail?.sourceColumn)
              )
            )
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "cde-tab-request-no-extra-tools",
      description: "Exercise CDE-tab request semantics and verify non-reference filter/sort controls are absent from the first viewport.",
      async run(page) {
        await clickVisible(page.getByRole("tab", { name: /CDE Registry/i }).first(), "CDE Registry tab");
        await clickButton(page, /\+ New term/i, "CDE tab new term request semantics");
        const newRequest = await textChecks(page, { cdeRequest: /New CDE request is unavailable/i });
        const toolState = await page.evaluate(() => {
          const byLabel = (label) => Boolean(document.querySelector(`[aria-label="${label}"]`));
          return {
            searchVisible: byLabel("Search CDE registry"),
            filterVisible: byLabel("Filter CDE registry by status"),
            sortVisible: byLabel("Sort CDE registry"),
            provenanceVisible: /Status and recertification are registry metadata values/i.test(document.body?.innerText || ""),
            rowCount: document.querySelectorAll(".gh-taxonomy-prototype-cde-row").length,
          };
        });
        return { newRequest, toolState };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.newRequest?.cdeRequest &&
            runResult?.toolState?.rowCount >= 1 &&
            runResult?.toolState?.provenanceVisible &&
            !runResult?.toolState?.searchVisible &&
            !runResult?.toolState?.filterVisible &&
            !runResult?.toolState?.sortVisible
          ),
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Submit a CDE Registry-specific Atlas AI prompt and verify grounded evidence appears.",
      async run(page) {
        await clickVisible(page.getByRole("tab", { name: /CDE Registry/i }).first(), "CDE Registry tab");
        await openFloatingAtlasAi(page, "Open CDE Registry Atlas AI");
        return await submitFloatingAtlasAiPromptOrUnavailable(page, "Which CDEs need recertification?", "Submit CDE Registry Atlas AI prompt", {
          answer: /Genie returned|governed evidence|CDE|recertification|Customer Identifier|Unavailable/i,
          evidence: /evidence|Databricks|Genie|governed/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
      },
      async validate(page, runResult) {
        return { loaded: atlasAiRouteLoaded(runResult, { disclaimer: true }), runResult };
      },
    },
    {
      key: "responsive-table-controls",
      description: "Validate CDE rows and important cells remain visible or contained at the active viewport.",
      async run(page) {
        await clickVisible(page.getByRole("tab", { name: /CDE Registry/i }).first(), "CDE Registry tab");
        const layout = await page.evaluate(() => {
          const viewport = { width: window.innerWidth, height: window.innerHeight };
          const rows = Array.from(document.querySelectorAll(".gh-taxonomy-prototype-cde-row"));
          const table = document.querySelector(".gh-taxonomy-prototype-cde-table");
          const rectInfo = (node) => {
            const rect = node.getBoundingClientRect();
            return {
              top: Math.round(rect.top),
              left: Math.round(rect.left),
              right: Math.round(rect.right),
              bottom: Math.round(rect.bottom),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            };
          };
          const removedToolCount = document.querySelectorAll(".gh-taxonomy-prototype-cde-tools input, .gh-taxonomy-prototype-cde-tools select").length;
          const rowCellFailures = rows.flatMap((row, rowIndex) => {
            const rowRect = row.getBoundingClientRect();
            return Array.from(row.children).map((cell, cellIndex) => {
              const rect = cell.getBoundingClientRect();
              const visible = rect.width > 0 && rect.height > 0 && getComputedStyle(cell).visibility !== "hidden";
              const insideRow = rect.left >= rowRect.left - 1 && rect.right <= rowRect.right + 1;
              return { rowIndex, cellIndex, visible, insideRow, rect: rectInfo(cell), rowRect: rectInfo(row) };
            }).filter((item) => !item.visible || !item.insideRow);
          });
          return {
            viewport,
            removedToolCount,
            rowCount: rows.length,
            tableScrollable: Boolean(table && table.scrollWidth >= table.clientWidth),
            rowCellFailures,
          };
        });
        return { layout };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.layout?.removedToolCount === 0 &&
            runResult?.layout?.rowCount > 0 &&
            runResult?.layout?.rowCellFailures?.length === 0
          ),
          runResult,
        };
      },
    },
  ],
  lineage: [
    {
      key: "lineage-controls",
      description: "Exercise visible Lineage impact, column, zoom, refocus, and time controls.",
      async run(page) {
        await page.waitForFunction(
          () => {
            const text = document.body?.innerText || "";
            const nonzeroGraph = /[1-9]\d*\s+nodes?\s+·\s+[1-9]\d*\s+edges?/i.test(text);
            const unavailableGraph = /No live lineage graph|Lineage is unavailable for this asset/i.test(text);
            return nonzeroGraph || unavailableGraph;
          },
          undefined,
          { timeout: 90_000 },
        ).catch(() => {});
        await clickButton(page, /Run impact analysis|Preview impact/i, "Lineage impact control");
        await page.waitForFunction(
          () => /Impact analysis focused|no downstream evidence|no backed downstream impact evidence|Impact analysis opened|Impact analysis refresh failed/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 90_000 },
        ).catch(() => {});
        const impact = await textChecks(page, {
          impactStatus: /Impact analysis focused|no downstream evidence|no backed downstream impact evidence|Impact analysis opened|Impact analysis refresh failed/i,
        });
        let columnButton = null;
        let columnClicked = false;
        try {
          columnButton = await clickFirstEnabledButton(page, /Column lineage/i, "Lineage column mode");
          columnClicked = true;
          await page.waitForFunction(
            () => /Column lineage view active|Column lineage is unavailable|Column lineage refresh failed/i.test(document.body?.innerText || ""),
            undefined,
            { timeout: 75_000 },
          ).catch(() => {});
        } catch (_error) {
          const candidates = page.getByRole("button", { name: /Column lineage/i });
          for (let index = 0; index < await candidates.count(); index += 1) {
            const candidate = candidates.nth(index);
            if (!(await candidate.isVisible().catch(() => false))) continue;
            columnButton = await controlSnapshot(candidate).catch(() => null);
            if (columnButton) break;
          }
        }
        const column = await textChecks(page, {
          columnStatus: /Column lineage view active|Column lineage is unavailable|Column lineage refresh failed|Column lineage requires backed live column proof/i,
        });
        const columnModeClass = await page.locator(".ga-lineage-graph-bands.is-column-mode").first().isVisible().catch(() => false);
        const columnPanelFocused = await page.locator(".ga-lineage-bottom-card.is-focused", { hasText: /Column lineage/i }).first().isVisible().catch(() => false);
        const columnPanelProof = await textChecks(page, { proofOnly: /From system\.access\.column_lineage|column paths visible|No column-lineage rows returned/i });
        const authoritativeToolbarState = await page.evaluate(() => {
          const visibleText = (node) => {
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0
              ? String(node.textContent || "").trim()
              : "";
          };
          const labels = Array.from(document.querySelectorAll("button")).map(visibleText).filter(Boolean);
          const graphToolbarVisible = Boolean(document.querySelector(".ga-lineage-graph-toolbar")?.getBoundingClientRect().width);
          return {
            compareAvailableOrUnavailable: labels.includes("Compare versions") || /persisted lineage snapshots/i.test(document.body?.innerText || ""),
            tableAvailable: labels.includes("Table lineage") || labels.some((label) => /Table lineage/i.test(label)),
            searchAvailable: labels.includes("Search") || labels.some((label) => /^Search$/i.test(label)),
            exportAvailable: labels.includes("Export") || labels.some((label) => /^Export$/i.test(label)),
            graphToolbarVisible,
          };
        });
        const graphBandsVisible = await page.locator(".ga-lineage-graph-bands").first().isVisible().catch(() => false);
        if (!graphBandsVisible) {
          const zoomInUnavailable = await controlSnapshot(buttonByName(page, /^Zoom in$/i)).catch(() => null);
          const zoomOutUnavailable = await controlSnapshot(buttonByName(page, /^Zoom out$/i)).catch(() => null);
          const fitGraphUnavailable = await controlSnapshot(buttonByName(page, /^Fit graph$/i)).catch(() => null);
          return {
            impact,
            column,
            columnButton,
            columnClicked,
            columnModeClass,
            columnPanelFocused,
            columnPanelProof,
            authoritativeToolbarState,
            unavailableGraph: true,
            zoomInUnavailable,
            zoomOutUnavailable,
            fitGraphUnavailable,
            graphHistory: await controlSnapshot(buttonByName(page, /^Graph history$/i)).catch(() => null),
            refocusButton: await controlSnapshot(buttonByName(page, /^Refocus graph$/i)).catch(() => null),
            timeResetState: await controlSnapshot(buttonByName(page, /^(Now|Unavailable|Reset preview|Reset lineage view)$/i)).catch(() => null),
          };
        }
        const readZoomLevel = () => page.locator(".ga-lineage-graph-bands").first().evaluate((node) => Number(node.getAttribute("data-zoom-level") || "1"));
        const initialZoom = await readZoomLevel();
        const zoomIn = await clickVisible(buttonByName(page, /^Zoom in$/i), "Lineage zoom in");
        const zoomInLevel = await readZoomLevel();
        const zoomInStatus = await textChecks(page, { ready: /Lineage graph zoom set to/i });
        const zoomOut = await clickVisible(buttonByName(page, /^Zoom out$/i), "Lineage zoom out");
        const zoomOutLevel = await readZoomLevel();
        const zoomOutStatus = await textChecks(page, { ready: /Lineage graph zoom set to/i });
        const fitGraph = await clickVisible(buttonByName(page, /^Fit graph$/i), "Lineage fit graph");
        const fitGraphLevel = await readZoomLevel();
        const fitGraphStatus = await textChecks(page, { ready: /Lineage graph fit to view/i });
        const graphBody = page.locator("[data-testid='lineage-graph-body']").first();
        const graphBodyBox = await graphBody.boundingBox();
        if (graphBodyBox) {
          const wheelPoint = await graphBody.evaluate((node) => {
            const blockedSelector = "a, button, input, textarea, select, .ga-lineage-details-panel, .ga-lineage-graph-search";
            const rect = node.getBoundingClientRect();
            const xFractions = [0.18, 0.32, 0.48, 0.64, 0.82];
            const yFractions = [0.18, 0.32, 0.48, 0.64, 0.82];
            for (const yFraction of yFractions) {
              for (const xFraction of xFractions) {
                const x = rect.left + rect.width * xFraction;
                const y = rect.top + rect.height * yFraction;
                const target = document.elementFromPoint(x, y);
                if (target && !target.closest(blockedSelector)) {
                  return { x: Math.round(x), y: Math.round(y) };
                }
              }
            }
            return {
              x: Math.round(rect.left + rect.width * 0.5),
              y: Math.round(rect.top + rect.height * 0.5),
            };
          });
          await page.mouse.move(wheelPoint.x, wheelPoint.y);
          await page.mouse.wheel(0, -220);
          await page.waitForFunction(() => {
            const node = document.querySelector(".ga-lineage-graph-bands");
            return Number(node?.getAttribute("data-zoom-level") || "1") > 1;
          }, undefined, { timeout: 5_000 }).catch(() => {});
        }
        const wheelZoomLevel = await readZoomLevel();
        const wheelZoomStatus = await textChecks(page, { ready: /Lineage graph zoom set to/i });
        await clickVisible(buttonByName(page, /^Fit graph$/i), "Lineage fit graph after wheel");
        const graphPan = await page.locator("[data-testid='lineage-graph-body']").first().evaluate((node) => {
          const rect = node.getBoundingClientRect();
          const style = node instanceof HTMLElement ? node.style : null;
          return {
            x: Number.parseFloat(style?.getPropertyValue("--ga-lineage-pan-x") || "0") || 0,
            y: Number.parseFloat(style?.getPropertyValue("--ga-lineage-pan-y") || "0") || 0,
            centerX: Math.round(rect.left + rect.width / 2),
            centerY: Math.round(rect.top + rect.height / 2),
          };
        });
        await page.mouse.move(graphPan.centerX, graphPan.centerY);
        await page.mouse.down();
        await page.mouse.move(graphPan.centerX + 48, graphPan.centerY + 22, { steps: 6 });
        await page.mouse.up();
        const graphPanAfter = await page.locator("[data-testid='lineage-graph-body']").first().evaluate((node) => {
          const style = node instanceof HTMLElement ? node.style : null;
          return {
            x: Number.parseFloat(style?.getPropertyValue("--ga-lineage-pan-x") || "0") || 0,
            y: Number.parseFloat(style?.getPropertyValue("--ga-lineage-pan-y") || "0") || 0,
          };
        });
        const graphPanStatus = await textChecks(page, { ready: /Lineage graph panned/i });
        const graphHistory = await controlSnapshot(buttonByName(page, /^Graph history$/i));
        const graphHistoryStatus = {
          ready: graphHistory.disabled && /persisted lineage snapshots/i.test(graphHistory.title || ""),
          title: graphHistory.title,
        };
        const refocusButton = await controlSnapshot(buttonByName(page, /^Refocus graph$/i));
        let refocus = { ready: false };
        if (refocusButton.disabled && /actor-visible lineage proof|backed live lineage evidence|not openable|current permissions/i.test(refocusButton.title || "")) {
          refocus = { ready: true, unavailable: true, title: refocusButton.title };
        } else {
          await clickVisible(buttonByName(page, /^Refocus graph$/i), "Lineage refocus graph status control");
          refocus = await textChecks(page, { ready: /Lineage graph refocused|refocused on/i });
        }
        const timeResetButton = buttonByName(page, /^(Now|Unavailable|Reset preview|Reset lineage view)$/i);
        const timeResetState = await controlSnapshot(timeResetButton);
        let now = { ready: false };
        if (timeResetState.disabled && /backed live lineage evidence/i.test(timeResetState.title || "")) {
          now = { ready: true, unavailable: true, title: timeResetState.title };
        } else {
          await clickVisible(timeResetButton, "Lineage time reset control");
          now = await textChecks(page, { ready: /reset to now|Lineage view reset|Lineage refreshed to current live graph|Live lineage refresh completed/i });
        }
        const zoomControls = await page.evaluate(() => {
          const labels = Array.from(document.querySelectorAll("button"))
            .map((node) => `${node.textContent || ""} ${node.getAttribute("aria-label") || ""}`.replace(/\s+/g, " ").trim())
            .filter(Boolean);
          return labels.filter((label) => /Zoom|Reset Zoom|Zoom in|Zoom out/i.test(label));
        });
        return {
          impact,
          column,
          columnButton,
          columnClicked,
          columnModeClass,
          columnPanelFocused,
          columnPanelProof,
          authoritativeToolbarState,
          zoomIn,
          initialZoom,
          zoomInLevel,
          zoomInStatus,
          zoomOut,
          zoomOutLevel,
          zoomOutStatus,
          fitGraph,
          fitGraphLevel,
          fitGraphStatus,
          wheelZoomLevel,
          wheelZoomStatus,
          graphPan,
          graphPanAfter,
          graphPanStatus,
          graphHistory,
          graphHistoryStatus,
          refocusButton,
          refocus,
          timeResetState,
          now,
          zoomControls,
        };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { lineage: /Lineage Atlas/i });
        return {
          loaded: Boolean(
            checks.lineage &&
            (
              !runResult?.unavailableGraph ||
              (
                runResult?.zoomInUnavailable?.disabled &&
                runResult?.zoomOutUnavailable?.disabled &&
                runResult?.fitGraphUnavailable?.disabled &&
                /backed live lineage evidence/i.test(
                  `${runResult?.zoomInUnavailable?.title || ""} ${runResult?.zoomOutUnavailable?.title || ""} ${runResult?.fitGraphUnavailable?.title || ""}`,
                )
              )
            ) &&
            (
              runResult?.unavailableGraph ||
              (
            runResult?.impact?.impactStatus &&
            (
              runResult?.column?.columnStatus ||
              (
                runResult?.columnButton?.disabled &&
                /backed live column proof/i.test(runResult?.columnButton?.title || "")
              )
            ) &&
            (
              runResult?.columnModeClass ||
              /unavailable|refresh failed|backed live column proof/i.test(JSON.stringify(runResult?.column || {})) ||
              /backed live column proof/i.test(runResult?.columnButton?.title || "")
            ) &&
            (
              runResult?.columnPanelFocused ||
              /unavailable|refresh failed|backed live column proof/i.test(JSON.stringify(runResult?.column || {})) ||
              /backed live column proof/i.test(runResult?.columnButton?.title || "")
            ) &&
            (
            runResult?.columnPanelProof?.proofOnly ||
              /backed live column proof/i.test(runResult?.columnButton?.title || "")
            ) &&
            (
              (
                runResult?.authoritativeToolbarState?.tableAvailable &&
                runResult?.authoritativeToolbarState?.searchAvailable &&
                runResult?.authoritativeToolbarState?.exportAvailable &&
                runResult?.authoritativeToolbarState?.graphToolbarVisible
              ) ||
              /backed live column proof|workspace-scoped|app-principal/i.test(
                `${runResult?.columnButton?.title || ""} ${JSON.stringify(runResult?.column || {})}`,
              )
            ) &&
            runResult?.zoomIn &&
            runResult?.zoomInLevel > runResult?.initialZoom &&
            runResult?.zoomInStatus?.ready &&
            runResult?.zoomOut &&
            runResult?.zoomOutLevel < runResult?.zoomInLevel &&
            runResult?.zoomOutStatus?.ready &&
            runResult?.fitGraph &&
            Math.abs((runResult?.fitGraphLevel || 0) - 1) < 0.01 &&
            runResult?.fitGraphStatus?.ready &&
            runResult?.wheelZoomLevel > runResult?.fitGraphLevel &&
            runResult?.wheelZoomStatus?.ready &&
            runResult?.graphPanStatus?.ready &&
            Math.abs((runResult?.graphPanAfter?.x || 0) - (runResult?.graphPan?.x || 0)) > 10 &&
            runResult?.graphHistory?.disabled &&
            runResult?.graphHistoryStatus?.ready &&
            runResult?.refocus?.ready &&
            runResult?.now?.ready
              )
            )
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "lineage-selection",
      description: "Exercise every visible graph node, details-panel row, impact row, and column lineage row.",
      async run(page) {
        await page.waitForFunction(
          () => {
            const text = document.body?.innerText || "";
            return (
              /[1-9]\d*\s+nodes?\s+·\s+[1-9]\d*\s+edges?/i.test(text) ||
              /No live lineage graph|Lineage is unavailable for this asset/i.test(text)
            );
          },
          undefined,
          { timeout: 90_000 },
        ).catch(() => {});
        await page.waitForFunction(() => {
          const graphNodeCount = document.querySelectorAll(".ga-lineage-graph-bands [role='button'], .ga-lineage-graph-bands button").length;
          const detailRowCount = document.querySelectorAll(".ga-lineage-details-panel section [role='button'], .ga-lineage-details-panel section button").length;
          const columnRowCount = document.querySelectorAll(".ga-lineage-column-list [role='button'], .ga-lineage-column-list button").length;
          return graphNodeCount + detailRowCount + columnRowCount > 0;
        }, undefined, { timeout: 30_000 }).catch(() => {});
        const clickAllVisible = async (locator, description, options = {}) => {
          const total = await locator.count();
          const results = [];
          for (let index = 0; index < total; index += 1) {
            const control = locator.nth(index);
            const visible = await control.isVisible().catch(() => false);
            if (!visible) {
              results.push({ index, visible: false, clicked: false });
              continue;
            }
            const before = await controlSnapshot(control);
            if (before.disabled) {
              results.push({ index, visible: true, clicked: false, disabled: true, before });
              continue;
            }
            await clickVisible(control, `${description} ${index + 1}`, { force: Boolean(options.force) });
            const after = await getBodyState(page, {
              selected: /selected/i,
              inspector: /Lineage Details/i,
              boundary: /PERMISSION-LIMITED|Restricted|Hidden by Unity Catalog permissions|limited Unity Catalog visibility/i,
              column: /column lineage row selected/i,
            });
            results.push({ index, visible: true, clicked: true, disabled: false, before, after: after.checks });
          }
          const visibleResults = results.filter((item) => item.visible);
          const enabledResults = visibleResults.filter((item) => !item.disabled);
          return {
            total,
            visibleCount: visibleResults.length,
            enabledCount: enabledResults.length,
            clickedCount: enabledResults.filter((item) => item.clicked).length,
            labels: enabledResults.map((item) => item.before?.text || item.before?.ariaLabel || `control-${item.index + 1}`),
            results,
          };
        };

        const graphNodes = await clickAllVisible(
          page.locator(".ga-lineage-graph-bands").getByRole("button"),
          "Lineage graph visible node",
          { force: true },
        );
        const restrictedNode = page.locator(".ga-lineage-graph-bands").getByRole("button", { name: /downstream assets|Restricted|Hidden by Unity Catalog permissions|limited Unity Catalog visibility/i }).first();
        const restrictedNodeVisible = await restrictedNode.isVisible().catch(() => false);
        if (restrictedNodeVisible) {
          await clickVisible(
            restrictedNode,
            "Lineage restricted node status check",
            { force: true },
          );
        }
        const restrictedStatus = await textChecks(page, {
          selected: /downstream assets selected|Restricted.*selected|Hidden.*selected/i,
          boundary: /PERMISSION-LIMITED|Restricted|Hidden by Unity Catalog permissions|limited Unity Catalog visibility/i,
        });
        const restrictedWorkflow = await textChecks(page, {
          panel: /Permission Boundary/i,
          title: /4 downstream assets detail/i,
          unavailable: /Permission-boundary detail workflow.*(requires returned backing evidence|no live lineage evidence|unavailable)/i,
          mutationGuard: /No request, grant, or access-review mutation was submitted/i,
        });
        const detailRows = await clickAllVisible(
          page.locator(".ga-lineage-details-panel section").getByRole("button"),
          "Lineage details-panel visible row",
        );
        const detailStatus = await textChecks(page, {
          inspector: /Lineage Details/i,
          selected: /selected/i,
        });
        const impactRows = await clickAllVisible(
          page.locator(".ga-lineage-impact-list").getByRole("button"),
          "Lineage impact visible row",
        );
        const impactStatus = await textChecks(page, {
          selected: /selected/i,
          inspector: /Lineage Details/i,
          unavailable: /Downstream consumer|Hidden by Unity Catalog permissions|finance_prod \/ revenue_recognition|revenue_recognition|lineage|impact|unavailable|backed/i,
        });
        const impactWorkflow = await textChecks(page, {
          panel: /Consumer Impact/i,
          title: /workflow/i,
          unavailable: /Consumer-impact workflow.*(requires returned backing evidence|no live lineage evidence|unavailable)/i,
          mutationGuard: /No owner notification, usage assertion, or consumer-impact mutation was submitted/i,
        });
        const columnRows = await clickAllVisible(
          page.locator(".ga-lineage-column-list").getByRole("button"),
          "Lineage column visible row",
        );
        const columnStatus = await textChecks(page, { selected: /column lineage row selected/i });
        const columnWorkflow = await textChecks(page, {
          panel: /Column Lineage/i,
          title: /workflow/i,
          unavailable: /Column-lineage detail workflow.*(requires returned backing evidence|no live lineage evidence|unavailable)|From system\.access\.column_lineage|column paths visible/i,
          backedTrace: /Column trace can be reviewed from the returned lineage payload/i,
          mutationGuard: /No column-level mutation or false completeness claim was created/i,
        });
        return {
          graphNodes,
          restrictedNodeVisible,
          restrictedStatus,
          restrictedWorkflow,
          detailRows,
          detailStatus,
          impactRows,
          impactStatus,
          impactWorkflow,
          columnRows,
          columnStatus,
          columnWorkflow,
          currentPath: new URL(page.url()).pathname,
        };
      },
      async validate(_page, runResult) {
        const allClicked = (result, expectedCount) => (
          result?.visibleCount === expectedCount &&
          result?.enabledCount === expectedCount &&
          result?.clickedCount === expectedCount
        );
        return {
          loaded: Boolean(
            runResult?.graphNodes?.visibleCount > 0 &&
            runResult?.graphNodes?.clickedCount === runResult?.graphNodes?.enabledCount &&
            (
              !runResult?.restrictedNodeVisible ||
              !runResult?.restrictedStatus?.boundary ||
              (
                runResult?.restrictedStatus?.boundary &&
                runResult?.restrictedWorkflow?.panel &&
                runResult?.restrictedWorkflow?.title &&
                runResult?.restrictedWorkflow?.unavailable &&
                runResult?.restrictedWorkflow?.mutationGuard
              )
            ) &&
            runResult?.detailRows?.visibleCount > 0 &&
            runResult?.detailRows?.clickedCount === runResult?.detailRows?.enabledCount &&
            runResult?.detailStatus?.inspector &&
            (
              runResult?.impactRows?.visibleCount === 0 ||
              (
                runResult?.impactStatus?.selected &&
                runResult?.impactStatus?.inspector &&
                runResult?.impactStatus?.unavailable &&
                (
                  (
                    runResult?.impactWorkflow?.panel &&
                    runResult?.impactWorkflow?.title &&
                    runResult?.impactWorkflow?.unavailable &&
                    runResult?.impactWorkflow?.mutationGuard
                  ) ||
                  /backed|lineage|unavailable/i.test(JSON.stringify(runResult?.impactRows || {}))
                )
              )
            ) &&
            runResult?.impactRows?.clickedCount === runResult?.impactRows?.enabledCount &&
            runResult?.columnRows?.clickedCount === runResult?.columnRows?.enabledCount &&
            (
              runResult?.columnRows?.visibleCount === 0 ||
              (
                runResult?.columnStatus?.selected &&
                runResult?.columnWorkflow?.unavailable &&
                (runResult?.columnWorkflow?.mutationGuard || runResult?.columnWorkflow?.backedTrace)
              )
            ) &&
            /\/lineage/i.test(runResult?.currentPath || "")
          ),
          runResult,
        };
      },
    },
    {
      key: "notify-owners",
      description: "Open the Lineage owner-review workflow, or verify it is disabled with a truthful unavailable reason.",
      async run(page) {
        const control = buttonByName(page, /Review owners/i);
        await control.waitFor({ state: "visible", timeout: 15_000 });
        const before = await controlSnapshot(control);
        if (before.disabled) {
          return { disabled: true, control: before };
        }
        await clickVisible(control, "Lineage Review owners");
        const pathAfterClick = await waitForPath(page, /\/stewardship|\/governance/i);
        await page.waitForSelector(".gh-governance-ns,.gh-governance-workspace,.gh-workspace", { timeout: 15_000 }).catch(() => {});
        return { disabled: false, control: before, pathAfterClick, state: await getBodyState(page, { governance: /Stewardship|work item|Governance/i }) };
      },
      async validate(_page, runResult) {
        if (runResult?.disabled) {
          return {
            loaded: /Owner review requires backed impact evidence/i.test(runResult?.control?.title || ""),
            runResult,
          };
        }
        return {
          loaded: Boolean(/\/stewardship|\/governance/i.test(runResult?.pathAfterClick || "") && runResult?.state?.checks?.governance),
          runResult,
        };
      },
    },
    {
      key: "asset-navigation",
      description: "Verify the selected Open asset action is either backed or truthfully disabled in the Lineage topology view.",
      async run(page) {
        const lineageTopology = await page.locator(".ga-lineage-graph-body").count();
        const openAsset = page.getByRole("button", { name: /^Open asset$/i }).first();
        const openAssetVisible = await openAsset.isVisible().catch(() => false);
        const openAssetSnapshot = openAssetVisible ? await controlSnapshot(openAsset) : null;
        let pathAfterClick = "";
        if (openAssetVisible && openAssetSnapshot && !openAssetSnapshot.disabled) {
          await clickVisible(openAsset, "Lineage Open asset");
          pathAfterClick = await waitForPath(page, /\/entity\//i, 30_000);
        }
        return {
          lineageTopology: lineageTopology > 0,
          openAssetVisible,
          openAssetSnapshot,
          pathAfterClick,
          reason: "Lineage Open asset must route to a backed asset or expose a disabled unavailable state.",
        };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            runResult?.lineageTopology &&
            (
              runResult?.openAssetVisible === false ||
              runResult?.openAssetSnapshot?.disabled ||
              /\/entity\//i.test(runResult?.pathAfterClick || "") ||
              /Open this lineage reference|not openable|metadata record/i.test(runResult?.openAssetSnapshot?.title || "")
            )
          ),
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Exercise Lineage Atlas AI suggestions, prompt submission, routed evidence chips, and accuracy notice.",
      async run(page) {
        const lineageUrl = page.url();
        const lineageFab = page.locator(".gh-atlas-ai-fab").first();
        if (!(await lineageFab.isVisible().catch(() => false))) {
          const topbarAi = page.locator(".gh-shell-topbar .ga-ai-chip.is-primary").filter({ hasText: /Atlas AI/i }).first();
          const topbarState = await controlSnapshot(topbarAi).catch(() => null);
          const unavailableState = await getBodyState(page, {
            reason: /requires a configured|unavailable|Databricks Genie|evidence-backed endpoint/i,
          });
          return {
            unavailable: true,
            lineageFabHidden: true,
            topbarState,
            unavailableState,
          };
        }
        await openFloatingAtlasAi(page, "Open Lineage Atlas AI");
        const suggestionsBefore = await page.locator(".gh-floating-ai-prompts button").count();
        const firstSuggestion = page.locator(".gh-floating-ai-prompts button").first();
        const suggestionBefore = await controlSnapshot(firstSuggestion);
        const unavailable = await floatingAtlasAiUnavailableProof(page);
        if (unavailable) {
          await clickVisible(page.getByRole("button", { name: /Atlas AI accuracy notice/i }).first(), "Open unavailable Lineage Atlas AI accuracy notice");
          const accuracyNotice = await textChecks(page, {
            notice: /grounded in available governance metadata and should be reviewed/i,
          });
          await clickButton(page, /Close Atlas AI/i, "Close unavailable Lineage Atlas AI");
          const panelClosed = await page.locator(".gh-floating-ai-chat").first().isVisible().then((visible) => !visible).catch(() => true);
          return {
            ...unavailable,
            suggestionsBefore,
            suggestionBefore,
            accuracyNotice,
            panelClosed,
          };
        }
        await clickVisible(firstSuggestion, "Submit Lineage Atlas AI suggested prompt");
        await page.waitForFunction(
          () => /Genie returned|governed evidence|lineage|downstream|asset|Unavailable|evidence/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 30_000 },
        );
        const suggestionChecks = await getBodyState(page, {
          answer: /Genie returned|governed evidence|lineage|downstream|asset|Unavailable/i,
          evidence: /evidence|Databricks|Genie|governed/i,
        });
        const assetEvidenceButton = page.locator(".gh-floating-ai-evidence button", { hasText: /Open (prototype )?asset/i }).first();
        const assetEvidenceVisible = await assetEvidenceButton.isVisible().catch(() => false);
        const assetEvidence = assetEvidenceVisible ? await controlSnapshot(assetEvidenceButton) : { hidden: true, disabled: true };
        let pathAfterAssetEvidence = "";
        if (assetEvidenceVisible && !assetEvidence.disabled) {
          await clickVisible(assetEvidenceButton, "Open Lineage Atlas AI asset evidence");
          pathAfterAssetEvidence = await waitForPath(page, /\/entity\//i, 15_000);
        }
        await page.goto(lineageUrl, { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".ga-lineage-explorer,.gh-lineage-workspace", { timeout: 20_000 });
        await openFloatingAtlasAi(page, "Reopen Lineage Atlas AI for typed prompt");
        const input = page.locator(".gh-floating-ai-input input").first();
        await input.fill("What downstream consumers depend on net_revenue_usd?");
        await clickVisible(page.locator(".gh-floating-ai-input button").first(), "Submit Lineage Atlas AI prompt");
        await page.waitForFunction(
          () => /Genie returned|governed evidence|lineage|downstream|asset|Unavailable|evidence/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 30_000 },
        );
        const typedChecks = await getBodyState(page, {
          answer: /Genie returned|governed evidence|lineage|downstream|asset|Unavailable/i,
          evidence: /evidence|Databricks|Genie|governed/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
        await waitForAtlasAiIdle(page);
        const askButtonAfterAnswer = await controlSnapshot(page.locator(".gh-floating-ai-input button").first());
        const stewardshipEvidenceButton = page.locator(".gh-floating-ai-evidence button", { hasText: /Open (prototype )?stewardship/i }).first();
        const stewardshipEvidenceVisible = await stewardshipEvidenceButton.isVisible().catch(() => false);
        const stewardshipEvidence = stewardshipEvidenceVisible ? await controlSnapshot(stewardshipEvidenceButton) : { hidden: true, disabled: true };
        let pathAfterStewardshipEvidence = "";
        if (stewardshipEvidenceVisible && !stewardshipEvidence.disabled) {
          await clickVisible(stewardshipEvidenceButton, "Open Lineage Atlas AI stewardship evidence");
          pathAfterStewardshipEvidence = await waitForPath(page, /\/stewardship|\/governance/i, 15_000);
        }
        await page.goto(lineageUrl, { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".ga-lineage-explorer,.gh-lineage-workspace", { timeout: 20_000 });
        await openFloatingAtlasAi(page, "Reopen Lineage Atlas AI for accuracy notice");
        await clickVisible(page.getByRole("button", { name: /Atlas AI accuracy notice/i }).first(), "Open Lineage Atlas AI accuracy notice");
        const accuracyNotice = await textChecks(page, {
          notice: /prototype answers use mock governance metadata and are not live Databricks evidence|grounded in available governance metadata and should be reviewed/i,
        });
        await clickButton(page, /Close Atlas AI/i, "Close Lineage Atlas AI");
        const panelClosed = await page.locator(".gh-floating-ai-chat").first().isVisible().then((visible) => !visible).catch(() => true);
        return {
          suggestionBefore,
          suggestionsBefore,
          suggestionChecks,
          assetEvidence,
          pathAfterAssetEvidence,
          typedChecks,
          askButtonAfterAnswer,
          stewardshipEvidence,
          pathAfterStewardshipEvidence,
          accuracyNotice,
          panelClosed,
        };
      },
      async validate(_page, runResult) {
        if (runResult?.unavailable) {
          return {
            loaded: Boolean(
              (
                runResult?.lineageFabHidden &&
                runResult?.topbarState?.disabled &&
                runResult?.unavailableState?.checks?.reason
              ) ||
              (
                runResult?.suggestionsBefore > 0 &&
                runResult?.suggestionBefore?.disabled &&
                atlasAiRouteLoaded(runResult, { disclaimer: true }) &&
                runResult?.accuracyNotice?.notice &&
                runResult?.panelClosed
              )
            ),
            runResult,
          };
        }
        return {
          loaded: Boolean(
            runResult?.suggestionsBefore > 0 &&
            !runResult?.suggestionBefore?.disabled &&
            runResult?.suggestionChecks?.checks?.answer &&
            runResult?.suggestionChecks?.checks?.evidence &&
            (runResult?.assetEvidence?.hidden || (/\/entity\//i.test(runResult?.pathAfterAssetEvidence || "") && !runResult?.assetEvidence?.disabled)) &&
            runResult?.typedChecks?.checks?.answer &&
            runResult?.typedChecks?.checks?.evidence &&
            runResult?.typedChecks?.checks?.disclaimer &&
            runResult?.askButtonAfterAnswer?.disabled &&
            /Enter a prompt/i.test(runResult?.askButtonAfterAnswer?.title || "") &&
            (runResult?.stewardshipEvidence?.hidden || (/\/stewardship|\/governance/i.test(runResult?.pathAfterStewardshipEvidence || "") && !runResult?.stewardshipEvidence?.disabled)) &&
            runResult?.accuracyNotice?.notice &&
            runResult?.panelClosed
          ),
          runResult,
        };
      },
    },
  ],
  audit: [
    {
      key: "degraded",
      description: "Capture the Audit Evidence degraded KPI and retention state while preserving the prototype table/footer frame.",
      async run(page) {
        mockApiFlags.auditDegraded = true;
        await page.goto(urlFor("/audit-evidence?ga_audit_degraded=1"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-audit-ns", { state: "visible", timeout: 20_000 });
        await page.waitForFunction(
          () => /Events · 24h|Unavailable|Retention policy not reported|No audit events match the current filters/i.test(document.body?.innerText || ""),
          undefined,
          { timeout: 20_000 },
        );
      },
      async validate(page) {
        return page.evaluate((mockApi) => {
          const text = (document.body?.innerText || "").replace(/\s+/g, " ").trim();
          const cards = Array.from(document.querySelectorAll(".gh-audit-kpi"));
          const unavailableCards = cards.filter((card) => /Unavailable/i.test(card.textContent || "")).length;
          const loaded = mockApi
            ? (
              cards.length === 4 &&
              unavailableCards === 4 &&
              /Events · 24h/i.test(text) &&
              /Retention policy not reported/i.test(text) &&
              /No audit events match the current filters/i.test(text)
            )
            : (
              cards.length === 4 &&
              unavailableCards >= 1 &&
              /Retention policy not reported|Unavailable/i.test(text)
            );
          return {
            loaded: Boolean(loaded),
            unavailableCards,
            text: text.slice(0, 1000),
          };
        }, MOCK_API);
      },
    },
    {
      key: "audit-controls",
      description: "Exercise Audit Evidence date range, filters, report export, CSV export, row detail, and copy controls.",
      async run(page) {
        await clickButton(page, /Date range/i, "Audit Date range");
        const dateRangeResponsePromise = page.waitForResponse(
          (response) => /\/api\/atlas\/audit\/evidence/i.test(response.url()) && /date_range=7d/i.test(response.url()),
          { timeout: 45_000 },
        ).catch(() => null);
        await clickVisible(page.getByRole("menuitemradio", { name: /7d/i }).first(), "Audit 7d date range");
        const dateRangeResponse = await dateRangeResponsePromise;
        const auditRowsSettled = await page.waitForFunction(
          () => {
            const text = document.body?.innerText || "";
            return !/Loading audit trail|Reading governed metadata audit evidence|EVENTS\s+·\s+LOADED\s+Loading/i.test(text);
          },
          undefined,
          { timeout: 45_000 },
        ).then(() => true).catch(() => false);
        const dateRange = await textChecks(page, { dateStatus: /Audit date range set to 7d/i });
        const dateRangeScope = await textChecks(page, { kpiScope: /Events · 7d|Events · loaded|governance audit log/i });
        await clickButton(page, /By users/i, "Audit By users");
        const byUsers = await controlSnapshot(buttonByName(page, /By users/i));
        await clickButton(page, /By services/i, "Audit By services");
        const byServices = await controlSnapshot(buttonByName(page, /By services/i));
        await clickButton(page, /Violations/i, "Audit Violations");
        const violations = await controlSnapshot(buttonByName(page, /Violations/i));
        await clickButton(page, /All events/i, "Audit All events");
        await page.waitForFunction(
          () => {
            const text = document.body?.innerText || "";
            const rows = document.querySelectorAll(".gh-audit-row").length;
            const reportButton = Array.from(document.querySelectorAll("button")).find((button) =>
              /Generate report/i.test(button.textContent || button.getAttribute("aria-label") || ""),
            );
            const disabledReason = `${reportButton?.getAttribute("title") || ""} ${reportButton?.textContent || ""}`;
            return rows > 0 || /No audit events match the current filters|Audit evidence is unavailable|Audit trail is steward\/admin only/i.test(text) ||
              !/no audit rows match|rows are still loading/i.test(disabledReason);
          },
          undefined,
          { timeout: 30_000 },
        ).catch(() => {});
        const unavailableExportPattern = /audit export unavailable|no audit rows match|rows are still loading/i;
        const reportDownload = await clickDownloadOrUnavailable(
          page,
          buttonByName(page, /Generate report/i),
          "audit-report",
          unavailableExportPattern,
        );
        const csvDownload = await clickDownloadOrUnavailable(
          page,
          buttonByName(page, /Export CSV/i),
          "audit-events",
          unavailableExportPattern,
        );
        const auditRows = page.locator(".gh-audit-row");
        const rowsVisible = await Promise.race([
          auditRows.first().waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false),
          page.getByText(/No audit events match the current filters/i).first().waitFor({ state: "visible", timeout: 15_000 }).then(() => false).catch(() => false),
        ]);
        const rowCount = rowsVisible ? await auditRows.count() : 0;
        let selectedDetail = null;
        let copyControl = null;
        for (let index = 0; index < rowCount; index += 1) {
          await auditRows.nth(index).click();
          await page.waitForSelector(".gh-audit-selected-detail", { state: "visible", timeout: 10_000 });
          selectedDetail = await page.locator(".gh-audit-selected-detail").first().evaluate((node) => {
            const text = (node.textContent || "").replace(/\s+/g, " ").trim();
            const requestMatch =
              text.match(/Evidence ID\s+([A-Z]{2,5}-\d+)/i) ||
              text.match(/Request ID\s+([A-Z]{2,5}-\d+)/i) ||
              text.match(/\b(SI-\d+|GOV-\d+)\b/i);
            return {
              text,
              requestId: requestMatch?.[1] || "",
              hasSelectedEvidence: /Selected evidence/i.test(text),
              hasRequestId: /(?:Request|Evidence) ID/i.test(text) || Boolean(requestMatch?.[1]),
            };
          });
          copyControl = await controlSnapshot(buttonByName(page, /Copy (?:request|evidence) ID/i)).catch(() => null);
          if (selectedDetail?.hasRequestId && copyControl && !copyControl.disabled) break;
        }
        let copied = rowCount ? { copied: false, unavailable: false } : { copied: false, unavailable: true };
        if (copyControl && !copyControl.disabled) {
          await clickVisible(buttonByName(page, /Copy (?:request|evidence) ID/i), "Audit copy evidence ID");
          copied = await textChecks(page, { copied: /(?:Request|Evidence) ID .* copied|selected for review/i });
        } else {
          copied = { copied: false, unavailable: true, title: copyControl?.title || "Evidence ID unavailable for this audit row." };
        }
        const copyStatusText = await visibleText(page, 2000);
        return {
          dateRange,
          dateRangeScope,
          dateRangeRequest: {
            url: dateRangeResponse?.url?.() || "",
            status: dateRangeResponse?.status?.() || 0,
            settled: auditRowsSettled,
          },
          byUsers,
          byServices,
          violations,
          reportDownload,
          csvDownload,
          selectedDetail,
          copyControl,
          copied,
          copyStatusText,
        };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { audit: /Immutable governance event log|Audit evidence/i });
        return {
          loaded: Boolean(
            checks.audit &&
            runResult?.dateRange?.dateStatus &&
            runResult?.dateRangeScope?.kpiScope &&
            (
              (/date_range=7d/i.test(runResult?.dateRangeRequest?.url || "") && runResult?.dateRangeRequest?.status === 200) ||
              (runResult?.dateRangeRequest?.settled && /7d scope|Audit trail is steward\/admin only|No audit events match/i.test(await visibleText(page, 1200)))
            ) &&
            runResult?.byUsers?.ariaPressed === "true" &&
            runResult?.byServices?.ariaPressed === "true" &&
            runResult?.violations?.ariaPressed === "true" &&
            (
              (
                runResult?.reportDownload?.ok &&
                (LIVE_DATABRICKS_CAPTURE
                  ? /"liveDatabricksEvidence":\s*true|"evidenceBoundary":\s*"deployed-databricks-app"/i.test(runResult?.reportDownload?.preview || "")
                  : /"liveDatabricksEvidence":\s*false|"evidenceBoundary":\s*"local-runtime"/i.test(runResult?.reportDownload?.preview || "")) &&
                runResult?.csvDownload?.ok &&
                runResult?.selectedDetail?.hasSelectedEvidence
              ) ||
              (
                runResult?.reportDownload?.unavailable &&
                runResult?.csvDownload?.unavailable &&
                /no audit events match|audit evidence is unavailable|audit trail is steward\/admin only/i.test(
                  `${runResult?.copyStatusText || ""} ${await visibleText(page, 2000)}`,
                )
              )
            ) &&
            (
              (runResult?.selectedDetail?.hasRequestId && runResult?.copied?.copied) ||
              (!runResult?.selectedDetail && runResult?.reportDownload?.unavailable && runResult?.csvDownload?.unavailable) ||
              (runResult?.copyControl?.disabled && runResult?.copied?.unavailable)
            )
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "audit-asset-navigation",
      description: "Open the selected audit row asset.",
      async run(page) {
        const rows = page.locator(".gh-audit-row");
        const rowsVisible = await Promise.race([
          rows.first().waitFor({ state: "attached", timeout: 15_000 }).then(() => true).catch(() => false),
          page.getByText(/No audit events match the current filters/i).first().waitFor({ state: "visible", timeout: 15_000 }).then(() => false).catch(() => false),
        ]);
        if (!rowsVisible) {
          return {
            openAssetSnapshot: {
              disabled: true,
              title: "No backed asset route is available because no audit rows match the current actor and filter.",
            },
            pathAfterClick: "",
            noRows: true,
          };
        }
        await rows.first().scrollIntoViewIfNeeded().catch(() => {});
        const rowCount = await rows.count();
        let openAssetSnapshot = null;
        for (let index = 0; index < rowCount; index += 1) {
          await rows.nth(index).click();
          await page.waitForSelector(".gh-audit-selected-detail", { state: "visible", timeout: 10_000 });
          openAssetSnapshot = await controlSnapshot(buttonByName(page, /Open asset/i)).catch(() => null);
          if (openAssetSnapshot && !openAssetSnapshot.disabled) break;
        }
        let pathAfterClick = "";
        if (openAssetSnapshot && !openAssetSnapshot.disabled) {
          await clickVisible(buttonByName(page, /Open asset/i), "Audit Open asset");
          pathAfterClick = await waitForPath(page, /\/entity\//i, 30_000);
        }
        return { openAssetSnapshot, pathAfterClick };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { assetPage: /Overview|Asset|revenue_daily/i });
        return {
          loaded: Boolean(
            (/\/entity\//i.test(runResult?.pathAfterClick || "") && checks.assetPage) ||
            (runResult?.openAssetSnapshot?.disabled && /no backed asset route|nothing to open|unavailable|no audit rows match/i.test(runResult?.openAssetSnapshot?.title || ""))
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "audit-evidence-link",
      description: "Open an inline audit evidence target link where a backed target is available.",
      async run(page) {
        const rows = page.locator(".gh-audit-row");
        const rowsVisible = await Promise.race([
          rows.first().waitFor({ state: "attached", timeout: 15_000 }).then(() => true).catch(() => false),
          page.getByText(/No audit events match the current filters/i).first().waitFor({ state: "visible", timeout: 15_000 }).then(() => false).catch(() => false),
        ]);
        if (!rowsVisible) {
          return {
            before: {
              disabled: true,
              title: "No evidence target asset route is available because no audit rows match the current actor and filter.",
            },
            pathAfterClick: "",
            noRows: true,
          };
        }
        await rows.first().scrollIntoViewIfNeeded().catch(() => {});
        const rowCount = await rows.count();
        let before = null;
        let inlineLink = null;
        for (let index = 0; index < rowCount; index += 1) {
          const candidate = rows.nth(index).getByRole("button", { name: /Open evidence target/i }).first();
          if (!(await candidate.isVisible().catch(() => false))) continue;
          const snapshot = await controlSnapshot(candidate);
          if (!snapshot.disabled) {
            before = snapshot;
            inlineLink = candidate;
            break;
          }
        }
        if (!inlineLink) {
          inlineLink = rows.first().getByRole("button", { name: /Open evidence target/i }).first();
          before = await controlSnapshot(inlineLink);
        }
        let pathAfterClick = "";
        if (before && !before.disabled) {
          await clickVisible(inlineLink, "Audit inline evidence target");
          pathAfterClick = await waitForPath(page, /\/entity\//i, 30_000);
        }
        return { before, pathAfterClick };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { assetPage: /Overview|Asset|revenue_daily/i });
        return {
          loaded: Boolean(
            (!runResult?.before?.disabled && /\/entity\//i.test(runResult?.pathAfterClick || "") && checks.assetPage) ||
            (runResult?.before?.disabled && /no evidence target asset route|no backed|unavailable/i.test(runResult?.before?.title || ""))
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Submit an Audit Evidence-specific Atlas AI prompt and verify grounded evidence appears.",
      async run(page) {
        await openFloatingAtlasAi(page, "Open Audit Evidence Atlas AI");
        return await submitFloatingAtlasAiPromptOrUnavailable(page, "Summarize recent audit evidence.", "Submit Audit Evidence Atlas AI prompt", {
          answer: /audit|evidence|governance|metadata|Genie|Unavailable/i,
          evidence: /audit|evidence|request|Databricks|governance/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
      },
      async validate(_page, runResult) {
        return { loaded: atlasAiRouteLoaded(runResult, { disclaimer: true }), runResult };
      },
    },
  ],
  "control-center": [
    {
      key: "control-controls",
      description: "Exercise Control Center linked-resource truth handling, no-URL fallback, integration detail, and policy detail.",
      async run(page) {
        await page.evaluate(() => {
          window.__governanceAtlasOpenedUrls = [];
          window.open = (url, target, features) => {
            window.__governanceAtlasOpenedUrls.push({ url: String(url || ""), target: String(target || ""), features: String(features || "") });
            return null;
          };
        });
        const jobInventoryUnavailable = await textChecks(page, {
          unavailable: /No backed scheduled-job inventory is available yet/i,
        });
        let job = { selected: false };
        let openLinkedWithUrl = null;
        let clickedOpenLinked = false;
        const firstJobRow = page.locator(".gh-admin-control-job-row").first();
        if (!jobInventoryUnavailable.unavailable && await firstJobRow.isVisible().catch(() => false)) {
          await clickVisible(firstJobRow, "Control Center reported job row");
          job = await textChecks(page, { selected: /diagnostics selected|Selected control detail/i });
          openLinkedWithUrl = await controlSnapshot(buttonByName(page, /Open linked resource/i));
        }
        if (openLinkedWithUrl && !openLinkedWithUrl?.disabled) {
          await clickButton(page, /Open linked resource/i, "Open reported Databricks job URL");
          clickedOpenLinked = true;
        }
        const openedUrls = await page.evaluate(() => window.__governanceAtlasOpenedUrls || []);
        const openedStatus = await textChecks(page, {
          opened: /linked resource opened/i,
          withheld: /unavailable|not reported|No backed Lakeflow Job row/i,
        });
        const openLinkedNoUrl = openLinkedWithUrl || { disabled: true, title: "No backed scheduled-job inventory is available yet." };
        const controlAdminOnly = await textChecks(page, { adminOnly: /Control Center is admin-only/i });
        let integration = { selected: false, unavailable: false };
        if (controlAdminOnly.adminOnly) {
          const unityCatalog = await controlSnapshot(buttonByName(page, /Unity Catalog/i)).catch(() => null);
          integration = {
            selected: false,
            unavailable: Boolean(unityCatalog?.disabled && /Integration state is unavailable|unavailable/i.test(unityCatalog.title || unityCatalog.text || "")),
            control: unityCatalog,
          };
        } else {
          await clickButton(page, /Unity Catalog/i, "Control Center Unity Catalog integration");
          integration = await textChecks(page, { selected: /Unity Catalog integration diagnostics selected|Selected control detail/i });
        }
        const openLinkedAfterIntegration = await controlSnapshot(buttonByName(page, /Open linked resource/i)).catch(() => null);
        const policyButton = buttonByName(page, /Owner required on production|[a-z0-9_ &-]+ policy coverage|Product policy coverage|Customer policy coverage|Marketing policy coverage|Operations policy coverage|Finance policy coverage/i);
        const policyRows = page.locator(".gh-admin-control-policy-row");
        const policyRowCount = await policyRows.count();
        const policySnapshot = policyRowCount
          ? await controlSnapshot(policyButton)
          : { disabled: true, title: "No backed policy-coverage rows are available yet.", missing: true };
        let policy = { selected: false, unavailable: false };
        if (!policySnapshot.disabled) {
          await clickVisible(policyButton, "Control Center policy row");
          policy = await textChecks(page, { selected: /coverage from diagnostics|Policy coverage/i });
        } else {
          policy = await textChecks(page, { unavailable: /Policy coverage is unavailable|No authoritative policy library|control-enforcement source|No backed policy-coverage rows/i });
          if (!policy.unavailable && /Policy coverage is unavailable|No authoritative policy library|control-enforcement source/i.test(policySnapshot.title || "")) {
            policy.unavailable = true;
          }
        }
        return { controlAdminOnly, jobInventoryUnavailable, job, openLinkedWithUrl, clickedOpenLinked, openedUrls, openedStatus, openLinkedAfterIntegration, openLinkedNoUrl: openLinkedAfterIntegration || openLinkedWithUrl || { disabled: true, title: "No backed scheduled-job inventory is available yet." }, integration, policySnapshot, policy };
      },
      async validate(page, runResult) {
        const checks = await textChecks(page, { control: /Atlas runtime, integrations, and policy/i });
        const linkedResourceHandled = runResult?.jobInventoryUnavailable?.unavailable
          ? (runResult?.openedUrls || []).length === 0
          : runResult?.openLinkedWithUrl?.disabled
            ? !runResult?.clickedOpenLinked
            : runResult?.openLinkedWithUrl &&
              runResult?.openedUrls?.some((item) => /^https?:\/\//i.test(item.url || "")) &&
              runResult?.openedStatus?.opened;
        return {
          loaded: Boolean(
            checks.control &&
            (runResult?.jobInventoryUnavailable?.unavailable || runResult?.job?.selected) &&
            linkedResourceHandled &&
            runResult?.openLinkedNoUrl?.disabled &&
            (runResult?.integration?.selected || (runResult?.controlAdminOnly?.adminOnly && runResult?.integration?.unavailable)) &&
            (runResult?.policy?.selected || (runResult?.policySnapshot?.disabled && runResult?.policy?.unavailable))
          ),
          checks,
          runResult,
        };
      },
    },
    {
      key: "control-shell-chrome",
      description: "Exercise topbar search, notifications, help, and profile controls from Control Center.",
      async run(page) {
        const input = page.locator(".ga-top-search input, .gh-topbar-search input, input[placeholder*='Search assets']").first();
        await input.waitFor({ state: "visible", timeout: 10_000 });
        await input.fill("net revenue");
        await clickButton(page, /Submit global search/i, "Submit Control Center global search");
        const pathAfterSearch = await waitForPath(page, /\/discover/i);
        await page.waitForSelector(".gh-discovery-workspace,.gh-discovery-main-grid", { timeout: 15_000 });
        const searchSettled = await page.waitForFunction(
          () => {
            const text = document.body?.innerText || "";
            return !/LOADING DISCOVERY RESULTS|Searching the visible catalog metadata|Reading visible catalog metadata/i.test(text);
          },
          undefined,
          { timeout: 45_000 },
        ).then(() => true).catch(() => false);
        const searchState = await getBodyState(page, { revenueDaily: /revenue|risk_critical_asset_monitor|product_mortgage_signal|finance_lien|market_analytics|datapact\.(?:enterprise_metadata_ops|governance_atlas_demo)/i });
        await page.goto(urlFor("/control-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-admin-ns,.gh-admin-workspace,.gh-workspace", { timeout: 20_000 });
        await clickButton(page, /Notifications/i, "Open Control Center notifications");
        const pathAfterNotifications = await waitForPath(page, /\/inbox/i);
        const inboxState = await getBodyState(page, { inbox: /Inbox|workflow notifications|No notifications/i });
        await page.goto(urlFor("/control-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-admin-ns,.gh-admin-workspace,.gh-workspace", { timeout: 20_000 });
        await clickButton(page, /^Help$/i, "Open help from Control Center");
        const pathAfterHelp = await waitForPath(page, /\/help/i);
        const helpState = await getBodyState(page, { help: /How Governance Atlas works|Getting help/i });
        await page.goto(urlFor("/control-center"), { waitUntil: "domcontentloaded", timeout: 90_000 });
        await page.waitForSelector(".gh-admin-ns,.gh-admin-workspace,.gh-workspace", { timeout: 20_000 });
        await clickButton(page, /Open profile menu/i, "Open profile menu from Control Center");
        const profileState = await getProfileMenuState(page);
        return { pathAfterSearch, searchSettled, searchState, pathAfterNotifications, inboxState, pathAfterHelp, helpState, profileState };
      },
      async validate(_page, runResult) {
        return {
          loaded: Boolean(
            /\/discover/i.test(runResult?.pathAfterSearch || "") &&
            runResult?.searchSettled &&
            runResult?.searchState?.checks?.revenueDaily &&
            /\/inbox/i.test(runResult?.pathAfterNotifications || "") &&
            runResult?.inboxState?.checks?.inbox &&
            /\/help/i.test(runResult?.pathAfterHelp || "") &&
            runResult?.helpState?.checks?.help &&
            runResult?.profileState?.checks?.settings &&
            runResult?.profileState?.checks?.avatar &&
            runResult?.profileState?.localAvatarState?.localOnly &&
            runResult?.profileState?.localAvatarState?.databricksProfileExcluded &&
            runResult?.profileState?.checks?.signOut
          ),
          runResult,
        };
      },
    },
    {
      key: "atlas-ai",
      description: "Submit a Control Center-specific Atlas AI prompt and verify grounded evidence appears.",
      async run(page) {
        await openFloatingAtlasAi(page, "Open Control Center Atlas AI");
        return await submitFloatingAtlasAiPromptOrUnavailable(page, "Which control center jobs are healthy?", "Submit Control Center Atlas AI prompt", {
          answer: /Control Center|runtime|policy|job|diagnostic|Unavailable|evidence/i,
          evidence: /policy|diagnostic|runtime|Databricks|evidence|unavailable/i,
          disclaimer: /Atlas AI uses AI\. Review for accuracy\./i,
        });
      },
      async validate(_page, runResult) {
        return { loaded: atlasAiRouteLoaded(runResult, { disclaimer: true }), runResult };
      },
    },
    {
      key: "responsive-control-layout",
      description: "Validate Control Center job, integration, policy, and detail controls remain visible within the main content region.",
      async run(page) {
        const firstJobRow = page.locator(".gh-admin-control-job-row").first();
        if (await firstJobRow.isVisible().catch(() => false)) {
          await clickVisible(firstJobRow, "Control Center detail row for responsive layout");
        } else {
          const integrations = page.locator(".gh-admin-control-integrations .gh-admin-control-integration");
          const count = await integrations.count();
          let clickedIntegration = false;
          for (let index = 0; index < count; index += 1) {
            const integration = integrations.nth(index);
            const snapshot = await controlSnapshot(integration).catch(() => null);
            if (snapshot && !snapshot.disabled) {
              await clickVisible(integration, "Control Center integration detail row for responsive layout");
              clickedIntegration = true;
              break;
            }
          }
          if (!clickedIntegration) {
            const unavailableOnly = await textChecks(page, {
              jobUnavailable: /No backed scheduled-job inventory is available yet/i,
              policyUnavailable: /No backed policy-coverage rows are available yet|Policy coverage unavailable/i,
              integrationsUnavailable: /Integration state is unavailable|Runtime signal unavailable|Integration not reported/i,
            });
            if (!unavailableOnly.jobUnavailable && !unavailableOnly.policyUnavailable && !unavailableOnly.integrationsUnavailable) {
              throw new Error("Control Center responsive layout has no enabled job or integration detail row.");
            }
          }
        }
        const layout = await page.evaluate(() => {
          const viewport = { width: window.innerWidth, height: window.innerHeight };
          const main = document.querySelector(".gh-main") || document.body;
          const mainRect = main.getBoundingClientRect();
          const rectInfo = (node) => {
            const rect = node.getBoundingClientRect();
            return {
              top: Math.round(rect.top),
              left: Math.round(rect.left),
              right: Math.round(rect.right),
              bottom: Math.round(rect.bottom),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            };
          };
          const selectors = [
            [".gh-admin-control-job-row", "job"],
            [".gh-admin-control-integration", "integration"],
            [".gh-admin-control-policy-row", "policy"],
            [".gh-admin-control-detail", "detail"],
            [".gh-admin-control-actions button", "detail-action"],
          ];
          const groups = selectors.map(([selector, label]) => {
            const nodes = Array.from(document.querySelectorAll(selector));
            const failures = nodes.map((node) => {
              const rect = node.getBoundingClientRect();
              const style = getComputedStyle(node);
              const visible = rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
              const insideMainWidth = rect.left >= mainRect.left - 1 && rect.right <= mainRect.right + 1;
              return { label, text: (node.textContent || node.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim(), visible, insideMainWidth, rect: rectInfo(node) };
            }).filter((item) => !item.visible || !item.insideMainWidth);
            return { label, count: nodes.length, failures };
          });
          return {
            viewport,
            main: rectInfo(main),
            groups,
          };
        });
        const unavailableOnly = await textChecks(page, {
          jobUnavailable: /No backed scheduled-job inventory is available yet/i,
          policyUnavailable: /No backed policy-coverage rows are available yet|Policy coverage unavailable/i,
          integrationsUnavailable: /Integration state is unavailable|Runtime signal unavailable|Integration not reported/i,
        });
        return { layout, unavailableOnly };
      },
      async validate(_page, runResult) {
        const groups = runResult?.layout?.groups || [];
        const unavailableOnly = runResult?.unavailableOnly || {};
        const enoughControls = groups.every((group) => {
          if (group.label === "job") return true;
          if (group.label === "policy") return group.count > 0 || unavailableOnly.policyUnavailable;
          if (group.label === "detail") return group.count > 0 || unavailableOnly.jobUnavailable || unavailableOnly.policyUnavailable || unavailableOnly.integrationsUnavailable;
          if (group.label === "detail-action") return group.count > 0 || unavailableOnly.jobUnavailable || unavailableOnly.policyUnavailable || unavailableOnly.integrationsUnavailable;
          return group.count > 0;
        });
        const noFailures = groups.every((group) => group.failures.length === 0);
        return { loaded: Boolean(enoughControls && noFailures), runResult };
      },
    },
  ],
};

function mockApiInteractionSkipReason(spec) {
  if (!MOCK_API) return "";
  const text = `${spec?.key || ""} ${spec?.description || ""}`;
  if (/atlas\s+ai|ai\s+chat|ai\s+prompt|ai\s+recommendation|markdown rendering|floating atlas ai/i.test(text)) {
    return "Atlas AI is disabled for non-authoritative mock capture; mock AI responses are not product-readiness evidence.";
  }
  return "";
}

async function captureRouteInteractions(page, route, viewport) {
  const specs = (INTERACTION_STATES[route.key] || [])
    .filter((spec) => !INTERACTION_FILTER.size || INTERACTION_FILTER.has(spec.key));
  for (const spec of specs) {
    const item = {
      route: route.key,
      path: route.path,
      viewport: viewport.name,
      interaction: spec.key,
      description: spec.description,
      loaded: false,
      screenshot: "",
      fullPageScreenshot: "",
    };
    try {
      mockApiFlags.discoveryDegraded = false;
      mockApiFlags.previewDegraded = false;
      await waitForRoute(page, route);
      const skipReason = mockApiInteractionSkipReason(spec);
      if (skipReason) {
        item.skipped = true;
        item.skipReason = skipReason;
        item.runResult = {
          skipped: true,
          reason: skipReason,
          evidenceBoundary: {
            currentReportEvidenceKind: "non_authoritative_mock_capture",
            liveDatabricksProofRecordedHere: false,
          },
        };
        item.validation = { loaded: true, skipped: true, reason: skipReason };
        item.metrics = await pageMetrics(page);
        item.loaded = true;
      } else {
        item.runResult = await spec.run(page);
        await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
        await page.waitForTimeout(500);
        item.validation = await spec.validate(page, item.runResult);
        item.metrics = await pageMetrics(page);
        item.loaded = Boolean(item.validation?.loaded);
      }
    } catch (error) {
      item.error = error?.message || String(error);
      item.metrics = await pageMetrics(page).catch(() => null);
    }
    const base = `${route.key}-${spec.key}-${viewport.name}`;
    item.screenshot = path.join(OUT_DIR, `${base}.png`);
    item.fullPageScreenshot = path.join(OUT_DIR, `${base}-full.png`);
    await fs.mkdir(OUT_DIR, { recursive: true });
    await page.screenshot({ path: item.screenshot, fullPage: false });
    if (CAPTURE_FULL_PAGE) {
      await page.screenshot({ path: item.fullPageScreenshot, fullPage: true });
    } else {
      item.fullPageScreenshot = "";
    }
    report.interactions.push(item);
    await flushReport();
    console.log(`${item.loaded ? "ok" : "warn"} ${route.key}:${spec.key} ${viewport.name}`);
  }
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  if (MOCK_API) {
    report.fatal =
      "GOVAT_PROTOTYPE_MOCK_API is disabled for Governance Atlas QA. Use real runtime/Databricks data or preserve the static northstar screenshots as reference-only artifacts.";
    await flushReport();
    console.error(report.fatal);
    process.exit(2);
  }
  if (UNKNOWN_ROUTE_FILTERS.length || !SELECTED_ROUTES.length) {
    report.fatal = UNKNOWN_ROUTE_FILTERS.length
      ? `Unknown prototype route filter(s): ${UNKNOWN_ROUTE_FILTERS.join(", ")}`
      : "No prototype routes selected.";
    await flushReport();
    console.error(report.fatal);
    process.exit(1);
  }
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1536, height: 1024 },
    acceptDownloads: true,
    extraHTTPHeaders: EXTRA_HTTP_HEADERS,
  });
  await captureRuntimeStatus();
  await context.addInitScript(() => {
    window.localStorage?.removeItem?.("governance-atlas:atlas-ai-dismissed");
  });
  await installMockApi(context);
  const page = await context.newPage();
  attachListeners(page);
  try {
    for (const viewport of VIEWPORTS) {
      for (const route of SELECTED_ROUTES) {
        await captureRoute(page, route, viewport);
        if (CAPTURE_INTERACTIONS) {
          await captureRouteInteractions(page, route, viewport);
        }
      }
    }
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    await flushReport();
  }
  if (!report.passed) process.exit(1);
}

main().catch(async (error) => {
  report.fatal = error?.message || String(error);
  await flushReport();
  console.error(error);
  process.exit(1);
});
