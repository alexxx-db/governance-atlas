import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  process.argv[2] ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const OUT_DIR =
  process.env.GOVAT_INSIGHTS_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/insights-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const VIEWPORTS = [
  { name: "1536x1024", width: 1536, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x720", width: 1280, height: 720 },
];

const report = {
  generatedAt: new Date().toISOString(),
  appUrl: BASE_URL,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  captures: [],
  interactions: [],
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function insightsUrl() {
  return route("/insights");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "insights-live-report.json"),
    JSON.stringify(report, null, 2),
  );
}

function attachRuntimeListeners(page) {
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
    report.consoleWarnings.push({
      type: message.type(),
      text,
      url: page.url(),
    });
    void flushReport();
  });
}

async function connect() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    extraHTTPHeaders: DATABRICKS_TOKEN
      ? {
          Authorization: `Bearer ${DATABRICKS_TOKEN}`,
        }
      : {},
    viewport: { width: 1536, height: 1024 },
  });
  const page = await context.newPage();
  attachRuntimeListeners(page);
  return {
    page,
    close: async () => {
      await context.close().catch(() => {});
      await browser.close().catch(() => {});
    },
  };
}

async function screenshot(page, name) {
  const filePath = path.join(OUT_DIR, `${name}.png`);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await page.screenshot({ path: filePath, fullPage: false });
  return filePath;
}

async function waitForInsights(page) {
  await page.waitForSelector("[data-surface='insights']", { timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Governance Insights/i.test(text) &&
        /Governance Maturity Score/i.test(text) &&
        /Strategic Recommendations/i.test(text) &&
        !/Loading insights/i.test(text)
      );
    },
    undefined,
    { timeout: 90_000 },
  );
  await page.waitForFunction(
    () => document.querySelectorAll(".gh-insights-kpi").length >= 6,
    undefined,
    { timeout: 30_000 },
  );
  await page.waitForFunction(
    () => {
      const values = [...document.querySelectorAll(".gh-insights-kpi-main strong")]
        .map((node) => node.textContent?.trim() || "")
        .filter(Boolean);
      const hasLiveKpi = values.some((value) => value !== "-" && value !== "Unavailable");
      const hasLiveRows =
        document.querySelectorAll(".gh-insights-coverage-row:not(.is-header)").length > 0 ||
        document.querySelectorAll(".gh-insights-domain-row").length > 0;
      return hasLiveKpi && hasLiveRows;
    },
    undefined,
    { timeout: 90_000 },
  );
}

async function gotoInsights(page) {
  await page.goto(insightsUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForInsights(page);
}

async function recordInteraction(page, name, fn) {
  const item = { name, passed: false };
  try {
    const detail = (await fn()) || {};
    Object.assign(item, detail, { passed: true });
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(
      page,
      `insights-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    );
  }
  report.interactions.push(item);
  await flushReport();
}

async function captureViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  let navigationError = "";
  for (const attempt of [1, 2]) {
    try {
      await gotoInsights(page);
      navigationError = "";
      await page.waitForTimeout(1000);
      break;
    } catch (error) {
      navigationError = error?.message || String(error);
      if (attempt === 2) break;
      await page.waitForTimeout(2000);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 90_000 }).catch(() => {});
    }
  }
  const screenshotPath = await screenshot(
    page,
    navigationError
      ? `insights-live-${viewport.name}-failure`
      : `insights-live-${viewport.name}`,
  );
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const box = node.getBoundingClientRect();
      return {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
        top: box.top,
        bottom: box.bottom,
        left: box.left,
        right: box.right,
      };
    };
    const bodyText = document.body?.innerText || "";
    const sectionBottoms = [...document.querySelectorAll(".gh-insights-card, .gh-insights-right-rail")]
      .map((node) => node.getBoundingClientRect().bottom)
      .filter((value) => Number.isFinite(value));
      const footer = rect(".ga-shell-footer");
      const page = rect("[data-surface='insights']");
      const main = document.querySelector(".gh-main");
      const trendRangeButtons = [...document.querySelectorAll(".gh-insights-card-header .gh-insights-range > button")]
        .map((node) => node.getAttribute("aria-label") || node.textContent?.trim() || "");
      return {
      url: window.location.href,
      title: document.querySelector(".gh-insights-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 4200),
      hasNorthstar: Boolean(document.querySelector("[data-surface='insights']")),
      loading: /Loading insights/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
        mainScrollHeight: main?.scrollHeight || 0,
        mainClientHeight: main?.clientHeight || 0,
        mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
        footer,
        page,
      hero: rect(".gh-insights-hero"),
      kpis: rect(".gh-insights-kpi-grid"),
      dashboard: rect(".gh-insights-dashboard"),
      recommendations: rect(".gh-insights-right-rail"),
      kpiCount: document.querySelectorAll(".gh-insights-kpi").length,
      recommendationCardCount: document.querySelectorAll(".gh-insights-rec-card").length,
      trendRangeControlCount: trendRangeButtons.length,
      trendRangeButtons,
      recommendationEmpty:
        /No evidence-backed recommendations are available from the current live signals/i.test(bodyText) ||
        /No additional evidence-backed recommendation/i.test(bodyText),
      maxSectionBottom: sectionBottoms.length ? Math.max(...sectionBottoms) : 0,
      regionText: {
        title: /Governance Insights/i.test(bodyText),
        supportCopy: /Operationalize trust at scale/i.test(bodyText),
        kpis:
          /Governance Maturity Score/i.test(bodyText) &&
          /Policy Compliance/i.test(bodyText) &&
          /Time to Resolution \(P1\)/i.test(bodyText) &&
          /Certified Assets/i.test(bodyText) &&
          /Critical Policy Exceptions/i.test(bodyText) &&
          /Metadata Coverage/i.test(bodyText),
        policyTrend: /Policy Compliance Trend/i.test(bodyText),
        resolutionTrend: /Time to Resolution Trend \(P1\)/i.test(bodyText),
        coverageHeatmap: /Metadata Coverage by Domain/i.test(bodyText),
        recommendations: /Strategic Recommendations/i.test(bodyText),
        tierCoverage: /Certification Coverage by Tier/i.test(bodyText),
        riskHeatmap: /Risk Heatmap/i.test(bodyText),
        topDomains: /Top Domains by Governance Maturity/i.test(bodyText),
        roi: /Governance ROI/i.test(bodyText),
      },
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer ||
    metrics.maxSectionBottom <= metrics.footer.top + 2;
  const compactContentReachable =
    viewport.height > 760 ||
    bottomAboveFooter ||
    metrics.mainScrolls;
  const footerSafe = viewport.height <= 760 ? compactContentReachable : bottomAboveFooter;
  const compactViewportReason =
    viewport.height <= 760 && !bottomAboveFooter && metrics.mainScrolls
      ? "compact viewport scrolls below fold in the main content area"
      : "";
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    metrics.title === "Governance Insights" &&
    metrics.kpiCount === 6 &&
    metrics.recommendationCardCount === 4 &&
    metrics.trendRangeControlCount >= 2 &&
    regionsOk &&
    !metrics.horizontalOverflow &&
    footerSafe;
  report.captures.push({
    viewport,
    screenshotPath,
    passed,
    navigationError,
    metrics,
    compactViewportReason,
  });
  await flushReport();
}

async function runInteractions(page) {
  await gotoInsights(page);

  await recordInteraction(page, "date range menu", async () => {
    await page.getByRole("button", { name: /Global date range: Last 6 Months/i }).click();
    await page.getByRole("button", { name: /Last 30 Days/i }).click();
    await page.waitForFunction(() => /Last 30 Days/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 });
    return { selectedRange: "Last 30 Days" };
  });

  await recordInteraction(page, "trend range controls", async () => {
    await page.getByRole("button", { name: /Policy Compliance Trend date range: Last 30 Days/i }).click();
    await page.getByRole("button", { name: /Last 90 Days/i }).click();
    await page.getByRole("button", { name: /Time to Resolution Trend date range: Last 90 Days/i }).click();
    await page.getByRole("button", { name: /Last 6 Months/i }).click();
    await page.getByRole("button", { name: /Policy Compliance Trend date range: Last 6 Months/i }).waitFor({ timeout: 10_000 });
    return { trendControls: 2, selectedRange: "Last 6 Months" };
  });

  await recordInteraction(page, "filters panel toggles", async () => {
    await page.getByRole("button", { name: /^Filters$/i }).click();
    await page.waitForFunction(() => /Live visibility scope/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 });
    await page.getByRole("button", { name: /^Close$/i }).click();
    await page.waitForFunction(() => !/Live visibility scope/i.test(document.body?.innerText || ""), undefined, { timeout: 10_000 });
    return { toggled: true };
  });

  await recordInteraction(page, "view all tier and domain controls", async () => {
    await page.getByRole("button", { name: /View all tiers/i }).click();
    await page.getByRole("button", { name: /Show fewer tiers/i }).waitFor({ timeout: 10_000 });
    await page.getByRole("button", { name: /View all domains/i }).click();
    await page.getByRole("button", { name: /Show fewer domains/i }).waitFor({ timeout: 10_000 });
    return { tierToggle: true, domainToggle: true };
  });

  await recordInteraction(page, "recommendations route to governance", async () => {
    await page.getByRole("button", { name: /View all recommendations/i }).click();
    await page.waitForURL(/\/governance/, { timeout: 30_000 });
    await page.waitForFunction(() => /Stewardship Workbench/i.test(document.body?.innerText || ""), undefined, { timeout: 30_000 });
    return { url: page.url() };
  });
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const session = await connect();
  try {
    for (const viewport of VIEWPORTS) {
      await captureViewport(session.page, viewport);
    }
    await session.page.setViewportSize({ width: 1536, height: 1024 });
    await runInteractions(session.page);
    await flushReport();
    console.log(JSON.stringify(report, null, 2));
    if (!report.passed) process.exit(1);
  } finally {
    await session.close();
  }
}

main().catch(async (error) => {
  report.pageErrors.push({ message: error?.message || String(error), stack: error?.stack || "" });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
