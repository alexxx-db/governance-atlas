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
  process.env.GOVAT_ASSET360_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/asset360-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const ASSET_FQN =
  process.env.GOVAT_ASSET_FQN || "datapact.governance_atlas_demo.customer_stewardship_queue";
const VIEWPORTS = [
  { name: "1536x1024", width: 1536, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x720", width: 1280, height: 720 },
];

const report = {
  generatedAt: new Date().toISOString(),
  appUrl: BASE_URL,
  evidenceKind: /\.databricksapps\.com$/i.test(new URL(APP_ORIGIN).hostname)
    ? "deployed_databricks_app_backed"
    : "local_runtime_databricks_backed",
  mockApi: false,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  assetFqn: ASSET_FQN,
  databricksEvidenceApi: null,
  captures: [],
  interactions: [],
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function assetUrl() {
  return route(`/entity/${ASSET_FQN}`);
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "asset360-live-report.json"),
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
    const location = message.location?.() || {};
    report.consoleWarnings.push({
      type: message.type(),
      text: message.text(),
      url: location.url || page.url(),
      lineNumber: location.lineNumber,
      columnNumber: location.columnNumber,
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
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: APP_ORIGIN });
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

async function fetchJson(pathname) {
  const response = await fetch(route(pathname), {
    headers: {
      Accept: "application/json",
      ...(DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {}),
    },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { rawText: text.slice(0, 1200) };
  }
  return {
    status: response.status,
    ok: response.ok,
    buildId: response.headers.get("x-govat-build-id") || "",
    body,
  };
}

async function recordApiInteraction(name, fn) {
  const item = { name, passed: false };
  try {
    const detail = (await fn()) || {};
    Object.assign(item, detail, { passed: true });
  } catch (error) {
    item.error = error?.message || String(error);
  }
  report.interactions.push(item);
  await flushReport();
}

async function waitForAsset360(page, { ensureOverview = true } = {}) {
  await page.waitForSelector(".ga-asset360-hero", { timeout: 120_000 });
  await page.waitForSelector(".gh-entity-record-tabs", { timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Asset 360/i.test(text) &&
        /Request Change/i.test(text) &&
        /Open Lineage/i.test(text) &&
        /Overview/i.test(text) &&
        /Columns/i.test(text) &&
        /Governance/i.test(text) &&
        /Profile/i.test(text) &&
        /Quality/i.test(text) &&
        /Access/i.test(text) &&
        /Activity/i.test(text) &&
        !/Loading Asset|Loading Asset 360|Loading live detail|Checking Lineage/i.test(text)
      );
    },
    undefined,
    { timeout: 120_000 },
  );
  if (ensureOverview) {
    const overview = page.getByRole("button", { name: /^Overview$/ });
    if ((await overview.getAttribute("aria-pressed").catch(() => "false")) !== "true") {
      await overview.click({ timeout: 30_000 });
    }
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText || "";
        return (
          Boolean(document.querySelector(".ga-asset360-main-grid")) &&
          /Business Description/i.test(text) &&
          /Usage Summary/i.test(text) &&
          /Schema/i.test(text) &&
          /Recent Activity/i.test(text) &&
          /Related Assets/i.test(text) &&
          /Downstream Dashboards/i.test(text)
        );
      },
      undefined,
      { timeout: 45_000 },
    );
  }
  await page.waitForTimeout(800);
}

async function gotoAsset360(page, options = {}) {
  await page.goto(assetUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForAsset360(page, options);
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
      `asset360-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
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
      await gotoAsset360(page);
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
      ? `asset360-live-${viewport.name}-failure`
      : `asset360-live-${viewport.name}`,
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
    const tabs = [...document.querySelectorAll(".gh-entity-record-tabs button")]
      .map((button) => button.textContent?.trim())
      .filter(Boolean);
    const actionButtons = ["Request Change", "Open Lineage", "Certify"].map((label) => {
      const button = [...document.querySelectorAll(".ga-asset360-actions button")]
        .find((node) => new RegExp(label, "i").test(node.textContent || node.getAttribute("aria-label") || ""));
      return { label, present: Boolean(button), enabled: Boolean(button && !button.disabled) };
    });
    const panelNodes = [
      ...document.querySelectorAll(".ga-asset360-panel, .ga-asset360-card"),
    ];
    const lightPanels = panelNodes.filter((node) => {
      const color = window.getComputedStyle(node).backgroundColor || "";
      const match = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
      if (!match) return false;
      const avg = (Number(match[1]) + Number(match[2]) + Number(match[3])) / 3;
      return avg > 170;
    }).length;
    return {
      url: window.location.href,
      title: document.querySelector(".ga-asset360-title-block h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 3600),
      hasNorthstar: Boolean(document.querySelector(".ga-asset360-main-grid")),
      loading: /Loading Asset|Loading Asset 360|Loading live detail|Checking Lineage/i.test(bodyText),
      degraded: /Asset 360 is unavailable|Asset 360 unavailable/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      footer: rect(".ga-shell-footer"),
      hero: rect(".ga-asset360-hero"),
      cardRow: rect(".ga-asset360-card-row"),
      tabsBox: rect(".gh-entity-record-tabs"),
      mainGrid: rect(".ga-asset360-main-grid"),
      primary: rect(".ga-asset360-primary"),
      rail: rect(".ga-asset360-rail"),
      tabs,
      actionButtons,
      lightPanels,
      regionText: {
        hero: /Asset 360/i.test(bodyText) && Boolean(document.querySelector(".ga-asset360-hero")),
        actions: actionButtons.every((button) => button.present && button.enabled),
        cards:
          /Owner/i.test(bodyText) &&
          /Steward/i.test(bodyText) &&
          /Freshness/i.test(bodyText) &&
          /Rows/i.test(bodyText) &&
          /Size/i.test(bodyText),
          tabs:
            tabs.includes("Overview") &&
            tabs.includes("Columns") &&
            tabs.includes("Governance") &&
            tabs.includes("Profile") &&
            tabs.includes("Quality") &&
            tabs.includes("Access") &&
          tabs.includes("Activity"),
        overview:
          /Business Description/i.test(bodyText) &&
          /Usage Summary/i.test(bodyText) &&
          /Schema/i.test(bodyText) &&
          /Governance/i.test(bodyText),
        rail:
          /Recent Activity/i.test(bodyText) &&
          /Related Assets/i.test(bodyText) &&
          /Downstream Dashboards/i.test(bodyText),
      },
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const footerPresent = Boolean(metrics.footer && metrics.footer.width > 0 && metrics.footer.height > 0);
  const footerTop = footerPresent ? metrics.footer.top : Number.POSITIVE_INFINITY;
  const mainAboveFooter =
    (!metrics.mainGrid || metrics.mainGrid.bottom <= footerTop + 1) &&
    (!metrics.rail || metrics.rail.bottom <= footerTop + 1);
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    regionsOk &&
    !metrics.loading &&
    !metrics.degraded &&
    !metrics.horizontalOverflow &&
    metrics.lightPanels === 0 &&
    mainAboveFooter;
  report.captures.push({
    viewport,
    screenshot: screenshotPath,
    metrics,
    navigationError,
    passed,
  });
  await flushReport();
}

async function clickAndExpectRoute(page, buttonLocator, expectedPathRegex) {
  await buttonLocator.click({ timeout: 30_000 });
  await page.waitForFunction(
    (pattern) => new RegExp(pattern).test(window.location.pathname + window.location.search),
    expectedPathRegex.source,
    { timeout: 45_000 },
  );
  return { url: page.url() };
}

async function runInteractions(page) {
  await recordInteraction(page, "Direct Asset 360 route settled", async () => {
    await gotoAsset360(page);
    const rows = await page.locator(".ga-asset360-schema-card tbody tr").count().catch(() => 0);
    return { url: page.url(), schemaRows: rows };
  });

  await recordInteraction(page, "Tabs and schema search", async () => {
    await gotoAsset360(page);
    const entityTabs = page.getByLabel("Entity sections");
    await entityTabs.getByRole("button", { name: /^Columns$/ }).click();
    await page.locator("input[aria-label='Filter columns']").fill("customer");
    await page.waitForSelector(".gh-schema-table, .gh-schema-empty-row", { timeout: 30_000 });
    await entityTabs.getByRole("button", { name: /^Governance$/ }).click();
    await page.waitForFunction(() => /Governance classifications/i.test(document.body?.innerText || ""), undefined, { timeout: 30_000 });
    await entityTabs.getByRole("button", { name: /^Profile$/ }).click();
    await page.waitForFunction(
      () => /Profiler & Evidence|Databricks metric tables|No profile runs recorded/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 30_000 },
    );
    await entityTabs.getByRole("button", { name: /^Quality$/ }).click();
    await page.waitForFunction(
      () => /Databricks DQ|Databricks monitoring|No quality evidence recorded|Latest results|Recent runs/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 30_000 },
    );
    await entityTabs.getByRole("button", { name: /^Access$/ }).click();
    await page.waitForFunction(() => /Live Record Signals|Access/i.test(document.body?.innerText || ""), undefined, { timeout: 30_000 });
    await entityTabs.getByRole("button", { name: /^Activity$/ }).click();
    await page.waitForFunction(() => /Activity & Tasks/i.test(document.body?.innerText || ""), undefined, { timeout: 30_000 });
    return { tabs: ["Columns", "Governance", "Profile", "Quality", "Access", "Activity"] };
  });

  await recordInteraction(page, "Overview View all columns", async () => {
    await gotoAsset360(page);
    await page.getByRole("button", { name: /View all columns/i }).click();
    await page.waitForSelector("input[aria-label='Filter columns']", { timeout: 30_000 });
    return { activeTab: "Columns" };
  });

  await recordInteraction(page, "Open Lineage action", async () => {
    await gotoAsset360(page);
    return clickAndExpectRoute(
      page,
      page.getByRole("button", { name: /^Open Lineage$/ }),
      /\/lineage\//,
    );
  });

  await recordInteraction(page, "Request Change action", async () => {
    await gotoAsset360(page);
    return clickAndExpectRoute(
      page,
      page.getByRole("button", { name: "Request Change" }),
      /\/governance/,
    );
  });

  await recordInteraction(page, "Certify action", async () => {
    await gotoAsset360(page);
    return clickAndExpectRoute(
      page,
      page.getByRole("button", { name: /Certify/ }),
      /\/governance/,
    );
  });

  await recordInteraction(page, "Overview and rail View all controls", async () => {
    const controls = [];
    await gotoAsset360(page);
    controls.push({
      label: "View history",
      ...(await clickAndExpectRoute(
        page,
        page.getByRole("button", { name: "View history" }),
        /\/governance/,
      )),
    });
    await gotoAsset360(page);
    controls.push({
      label: "View all usage",
      ...(await clickAndExpectRoute(
        page,
        page.getByRole("button", { name: "View all usage" }),
        /\/lineage\//,
      )),
    });
    await gotoAsset360(page);
    controls.push({
      label: "View all policies",
      ...(await clickAndExpectRoute(
        page,
        page.getByRole("button", { name: /View all policies/i }),
        /\/governance/,
      )),
    });
    await gotoAsset360(page);
    controls.push({
      label: "Recent Activity View all",
      ...(await clickAndExpectRoute(
        page,
        page
          .locator(".ga-asset360-rail section")
          .filter({ hasText: "Recent Activity" })
          .getByRole("button", { name: "View all" }),
        /\/governance/,
      )),
    });
    await gotoAsset360(page);
    controls.push({
      label: "Related Assets View all",
      ...(await clickAndExpectRoute(
        page,
        page
          .locator(".ga-asset360-rail section")
          .filter({ hasText: "Related Assets" })
          .getByRole("button", { name: "View all" }),
        /\/lineage\//,
      )),
    });
    await gotoAsset360(page);
    controls.push({
      label: "Downstream Dashboards View all",
      ...(await clickAndExpectRoute(
        page,
        page
          .locator(".ga-asset360-rail section")
          .filter({ hasText: "Downstream Dashboards" })
          .getByRole("button", { name: "View all" }),
        /\/lineage\//,
      )),
    });
    return { controls };
  });

  await recordInteraction(page, "Overflow share action", async () => {
    await gotoAsset360(page);
    const button = page.getByRole("button", { name: "More asset actions" });
    await button.click();
    await page.waitForFunction(
      () => {
        const node = document.querySelector(".ga-asset360-kebab");
        const title = node?.getAttribute("title") || "";
        return /Link copied/i.test(title);
      },
      undefined,
      { timeout: 5_000 },
    );
    return { title: await button.getAttribute("title"), clipboard: "copied" };
  });
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await recordApiInteraction("Databricks evidence API states", async () => {
    const encoded = encodeURIComponent(ASSET_FQN);
    const result = await fetchJson(`/api/assets/${encoded}/databricks-evidence`);
    const data = result.body?.data || {};
    const detail = {
      status: result.status,
      buildId: result.buildId,
      qualityMonitoring: data.qualityMonitoring?.state || "",
      profileMetrics: data.profileMetrics?.state || "",
      lakeflow: data.lakeflow?.state || "",
      pipelineEvents: data.pipelineEvents?.state || "",
      source: result.body?.meta?.source || "",
      authoritative: result.body?.meta?.authoritative === true,
    };
    report.databricksEvidenceApi = detail;
    if (!result.ok) throw new Error(`Databricks evidence API returned ${result.status}`);
    if (result.body?.meta?.source !== "databricks-system-tables") {
      throw new Error("Databricks evidence API did not return databricks-system-tables provenance.");
    }
    return detail;
  });
  const { page, close } = await connect();
  try {
    for (const viewport of VIEWPORTS) {
      await captureViewport(page, viewport);
    }
    await runInteractions(page);
  } finally {
    await flushReport();
    await close();
  }
  if (!report.passed) {
    console.error(JSON.stringify(report, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(report, null, 2));
}

main().catch(async (error) => {
  report.fatal = error?.message || String(error);
  await flushReport();
  console.error(error);
  process.exit(1);
});
