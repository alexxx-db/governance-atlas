import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL = (process.env.AXIOM_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const OUT_DIR =
  process.env.AXIOM_PERFORMANCE_OUT ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/runtime-performance-current");
const EXPECTED_BUILD_ID = process.env.AXIOM_BUILD_ID || "";
const TOKEN = process.env.AXIOM_DATABRICKS_TOKEN || "";
const FORWARDED_EMAIL = (process.env.AXIOM_CAPTURE_FORWARDED_EMAIL || "").trim();
const FORWARDED_USERNAME = (process.env.AXIOM_CAPTURE_FORWARDED_USERNAME || FORWARDED_EMAIL).trim();
const FORWARDED_DISPLAY_NAME = (process.env.AXIOM_CAPTURE_FORWARDED_DISPLAY_NAME || "").trim();
const FORWARDED_ACCESS_TOKEN = (process.env.AXIOM_CAPTURE_FORWARDED_ACCESS_TOKEN || "").trim();

const EXTRA_HTTP_HEADERS = {
  ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  ...(FORWARDED_EMAIL ? { "x-forwarded-email": FORWARDED_EMAIL } : {}),
  ...(FORWARDED_USERNAME ? { "x-forwarded-preferred-username": FORWARDED_USERNAME } : {}),
  ...(FORWARDED_DISPLAY_NAME ? { "x-forwarded-display-name": FORWARDED_DISPLAY_NAME } : {}),
  ...(FORWARDED_ACCESS_TOKEN ? { "x-forwarded-access-token": FORWARDED_ACCESS_TOKEN } : {}),
};

const LIVE_DATABRICKS_CAPTURE = Boolean(TOKEN && /\.databricksapps\.com(?:\/|$)/i.test(BASE_URL));
const FORWARDED_ACTOR_CAPTURE = Boolean(FORWARDED_EMAIL || FORWARDED_ACCESS_TOKEN);
const ASSET_FQN = process.env.AXIOM_PERFORMANCE_ASSET_FQN || "finance_prod.curated.revenue_daily";
const ENCODED_ASSET = encodeURIComponent(ASSET_FQN);

const API_ENDPOINTS = [
  { id: "bootstrap-home", path: "/api/bootstrap?surface=home", budgetMs: 500 },
  { id: "runtime-status", path: "/api/runtime/status", budgetMs: 1000 },
  { id: "command-center", path: "/api/axiom/command-center", budgetMs: 2000 },
  { id: "discovery-search", path: "/api/discovery/search?limit=80&sortBy=Best%20match", budgetMs: 2000 },
  { id: "asset-header", path: `/api/assets/${ENCODED_ASSET}?sections=header`, budgetMs: 2000 },
  { id: "asset-360", path: `/api/axiom/assets/${ENCODED_ASSET}/360`, budgetMs: 3000 },
  { id: "lineage-initial", path: `/api/lineage/${ENCODED_ASSET}?profile=initial`, budgetMs: 3000 },
  { id: "lineage-full", path: `/api/lineage/${ENCODED_ASSET}?profile=full`, budgetMs: 8000 },
  { id: "governance-workbench", path: "/api/axiom/governance/workbench", budgetMs: 3000 },
  { id: "taxonomy-overview", path: "/api/axiom/taxonomy/overview", budgetMs: 3000 },
  { id: "cde-dashboard", path: "/api/axiom/cde", budgetMs: 3000 },
  { id: "audit-evidence", path: "/api/axiom/audit/evidence?date_range=7d&limit=50", budgetMs: 3000 },
  { id: "admin-control-center", path: "/api/axiom/admin/control-center", budgetMs: 3000 },
];

const ROUTES = [
  { id: "command-center", path: "/command-center", settle: ".gh-home-page", budgetMs: 6000 },
  { id: "discover", path: "/discover", settle: ".gh-discovery-workspace,.gh-discovery-main-grid", budgetMs: 6000 },
  { id: "stewardship", path: "/stewardship", settle: ".gh-governance-ns-table,.gh-governance-ns-empty", budgetMs: 6000 },
  { id: "glossary", path: "/glossary-cdes", settle: ".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace", budgetMs: 6000 },
  { id: "cde-registry", path: "/glossary-cdes?tab=cdes", settle: ".gh-taxonomy-ns,.gh-taxonomy-workspace,.gh-workspace", budgetMs: 6000 },
  { id: "lineage", path: `/lineage-atlas/${ENCODED_ASSET}`, settle: ".ax-lineage-explorer,.gh-lineage-workspace,.gh-lineage-canvas,.gh-workspace", budgetMs: 8000 },
  { id: "audit", path: "/audit-evidence", settle: ".gh-audit-ns,.gh-audit-workspace,.gh-workspace", budgetMs: 6000 },
  { id: "control-center", path: "/control-center", settle: ".gh-admin-ns,.gh-admin-workspace,.gh-workspace", budgetMs: 6000 },
];

function normalizeEvidencePath(value) {
  const resolved = path.resolve(value);
  const relative = path.relative(REPO_ROOT, resolved);
  const normalized =
    relative && !relative.startsWith("..") && !path.isAbsolute(relative)
      ? relative
      : value;
  return normalized.split(path.sep).join("/");
}

function roundMs(value) {
  return Number.isFinite(value) ? Number(value.toFixed(1)) : null;
}

function parseServerDuration(headers) {
  const explicit =
    headers.get("x-process-time-ms") ||
    headers.get("x-response-time-ms") ||
    headers.get("x-runtime-ms") ||
    headers.get("x-server-duration-ms");
  if (explicit) {
    const parsed = Number.parseFloat(explicit);
    if (Number.isFinite(parsed)) return parsed;
  }
  const serverTiming = headers.get("server-timing") || "";
  const match = serverTiming.match(/dur=([0-9.]+)/i);
  if (match) {
    const parsed = Number.parseFloat(match[1]);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

async function timedFetch(endpoint, pass) {
  const start = performance.now();
  let status = 0;
  let ok = false;
  let bytes = 0;
  let serverDurationMs = null;
  let buildId = "";
  let error = "";
  try {
    const response = await fetch(`${BASE_URL}${endpoint.path}`, {
      headers: EXTRA_HTTP_HEADERS,
    });
    const text = await response.text();
    status = response.status;
    ok = response.ok;
    bytes = Buffer.byteLength(text, "utf8");
    serverDurationMs = parseServerDuration(response.headers);
    buildId = response.headers.get("x-axiom-build-id") || "";
    if (!response.ok) error = text.slice(0, 240);
  } catch (fetchError) {
    error = fetchError instanceof Error ? fetchError.message : String(fetchError);
  }
  const durationMs = performance.now() - start;
  return {
    id: endpoint.id,
    pass,
    path: endpoint.path,
    status,
    ok,
    durationMs: roundMs(durationMs),
    budgetMs: endpoint.budgetMs,
    withinBudget: ok && durationMs <= endpoint.budgetMs,
    bytes,
    serverDurationMs: roundMs(serverDurationMs),
    buildId,
    error,
  };
}

async function observeRoute(page, route, pass) {
  const start = performance.now();
  const observations = [];
  const requestFailures = [];
  page.on("requestfailed", (request) => {
    requestFailures.push({
      url: request.url(),
      failureText: request.failure()?.errorText || "",
    });
  });
  await page.goto(`${BASE_URL}${route.path}`, { waitUntil: "domcontentloaded", timeout: 90_000 });
  const domContentLoadedMs = performance.now() - start;
  const loadingBeforeSettle = await page
    .locator(".gh-workspace-state-skeleton,.gh-search-loading-indicator,[aria-busy='true']")
    .count()
    .catch(() => 0);
  observations.push({
    at: "after-domcontentloaded",
    loadingIndicators: loadingBeforeSettle,
  });
  let settled = false;
  let error = "";
  try {
    await page.waitForSelector(route.settle, { timeout: 90_000 });
    settled = true;
  } catch (settleError) {
    error = settleError instanceof Error ? settleError.message : String(settleError);
  }
  const settleMs = performance.now() - start;
  const visibleText = await page.locator("body").innerText({ timeout: 10_000 }).catch(() => "");
  const loadingAfterSettle = await page
    .locator(".gh-workspace-state-skeleton,.gh-search-loading-indicator,[aria-busy='true']")
    .count()
    .catch(() => 0);
  observations.push({
    at: "after-settle",
    loadingIndicators: loadingAfterSettle,
  });
  const navTiming = await page.evaluate(() => {
    const entry = performance.getEntriesByType("navigation")[0];
    if (!entry) return null;
    return {
      domContentLoadedEventEnd: entry.domContentLoadedEventEnd,
      loadEventEnd: entry.loadEventEnd,
      responseEnd: entry.responseEnd,
      transferSize: entry.transferSize,
      encodedBodySize: entry.encodedBodySize,
    };
  }).catch(() => null);
  return {
    id: route.id,
    pass,
    path: route.path,
    settled,
    domContentLoadedMs: roundMs(domContentLoadedMs),
    settleMs: roundMs(settleMs),
    budgetMs: route.budgetMs,
    withinBudget: settled && settleMs <= route.budgetMs,
    textLength: visibleText.length,
    hasUnavailableText: /unavailable|degraded|loading/i.test(visibleText),
    observations,
    requestFailures,
    navTiming,
    error,
  };
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const apiResults = [];
  for (const endpoint of API_ENDPOINTS) {
    apiResults.push(await timedFetch(endpoint, "first-observed"));
  }
  for (const endpoint of API_ENDPOINTS) {
    apiResults.push(await timedFetch(endpoint, "warm-repeat"));
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1536, height: 1024 },
    extraHTTPHeaders: EXTRA_HTTP_HEADERS,
  });
  const routeResults = [];
  for (const route of ROUTES) {
    const page = await context.newPage();
    routeResults.push(await observeRoute(page, route, "first-observed"));
    await page.close();
  }
  for (const route of ROUTES) {
    const page = await context.newPage();
    routeResults.push(await observeRoute(page, route, "warm-repeat"));
    await page.close();
  }
  await browser.close();

  const allResults = [...apiResults, ...routeResults];
  const failed = allResults.filter((result) => !result.withinBudget);
  const buildIds = Array.from(new Set(apiResults.map((result) => result.buildId).filter(Boolean)));
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    evidenceKind: "runtime_app_performance",
    mockApi: false,
    buildId: EXPECTED_BUILD_ID,
    observedBuildIds: buildIds,
    buildMatches: EXPECTED_BUILD_ID ? buildIds.every((buildId) => buildId === EXPECTED_BUILD_ID) : buildIds.length > 0,
    liveDatabricksCapture: LIVE_DATABRICKS_CAPTURE,
    forwardedActorCapture: FORWARDED_ACTOR_CAPTURE,
    warning: LIVE_DATABRICKS_CAPTURE
      ? "Deployed Databricks App performance evidence."
      : "Local runtime performance evidence only; not deployed Databricks App proof.",
    passed: failed.length === 0 && (EXPECTED_BUILD_ID ? buildIds.every((buildId) => buildId === EXPECTED_BUILD_ID) : true),
    budgetPassed: failed.length === 0,
    apiResults,
    routeResults,
    failed,
    worst: allResults
      .slice()
      .sort((a, b) => (b.durationMs || b.settleMs || 0) - (a.durationMs || a.settleMs || 0))
      .slice(0, 10),
  };
  const reportPath = path.join(OUT_DIR, "performance-report.json");
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  console.log(normalizeEvidencePath(reportPath));
  if (!report.passed) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
