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
  process.env.GOVAT_DISCOVERY_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/discovery-current");
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

function discoveryUrl(search = "") {
  return route(`/discovery${search}`);
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "discovery-live-report.json"),
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
    report.consoleWarnings.push({
      type: message.type(),
      text: message.text(),
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

async function waitForDiscovery(page) {
  await page.waitForSelector(".gh-discovery-main-grid", { timeout: 90_000 });
  await page.waitForSelector(".gh-discovery-results-panel", { timeout: 180_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const aiRunning = [...document.querySelectorAll(".gh-discovery-bottom-card header button")]
        .some((button) => /Running/i.test(button.textContent || ""));
      return (
        /Discover Trusted Data/i.test(text) &&
        /Discovery results/i.test(document.querySelector(".gh-discovery-results-panel")?.getAttribute("aria-label") || "") &&
        document.querySelectorAll(".gh-discovery-table-row[data-asset-fqn]").length > 0 &&
        !/Loading catalog|Preparing live discovery|Discovery Unavailable|Asking Atlas AI/i.test(text) &&
        !aiRunning
      );
    },
    undefined,
    { timeout: 180_000 },
  );
  await page.waitForTimeout(1500);
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const aiRunning = [...document.querySelectorAll(".gh-discovery-bottom-card header button")]
        .some((button) => /Running/i.test(button.textContent || ""));
      return (
        !/Asking Atlas AI|Atlas AI is gathering|Lineage unavailable|Live rows unavailable/i.test(text) &&
        !aiRunning &&
        document.querySelectorAll(".gh-discovery-preview-actions button").length >= 3
      );
    },
    undefined,
    { timeout: 120_000 },
  );
}

async function gotoDiscovery(page, search = "") {
  await page.goto(discoveryUrl(search), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForDiscovery(page);
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
      `discovery-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    );
  }
  report.interactions.push(item);
  await flushReport();
}

async function captureViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  let navigationError = "";
  try {
    await gotoDiscovery(page);
    await page.waitForTimeout(1000);
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText || "";
        const aiRunning = [...document.querySelectorAll(".gh-discovery-bottom-card header button")]
          .some((button) => /Running/i.test(button.textContent || ""));
        return !/Asking Atlas AI|Atlas AI is gathering/i.test(text) && !aiRunning;
      },
      undefined,
      { timeout: 120_000 },
    );
  } catch (error) {
    navigationError = error?.message || String(error);
  }
  const screenshotPath = await screenshot(
    page,
    navigationError ? `discovery-live-${viewport.name}-failure` : `discovery-live-${viewport.name}`,
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
    const rowCount = document.querySelectorAll(".gh-discovery-table-row[data-asset-fqn]").length;
    const viewAllButtons = [...document.querySelectorAll(".gh-discovery-bottom-card header button")]
      .filter((button) => /View all|Running/i.test(button.textContent || ""))
      .map((button) => ({
        label: button.textContent?.trim() || "",
        disabled: button.disabled,
      }));
    const previewButtons = ["Open Asset 360", "View Lineage", "Start Stewardship Review"].map((label) => {
      const button = [...document.querySelectorAll(".gh-discovery-preview-actions button")]
        .find((node) => (node.textContent || "").trim() === label);
      return { label, present: Boolean(button), enabled: Boolean(button && !button.disabled) };
    });
    const regionText = {
      hero: /Discover Trusted Data/i.test(bodyText),
      search: Boolean(document.querySelector("input[aria-label='Search discovery assets']")),
      filters:
        /Asset Type/i.test(bodyText) &&
        /Catalog/i.test(bodyText) &&
        /Domain/i.test(bodyText) &&
        /Owner/i.test(bodyText) &&
        /Certification/i.test(bodyText) &&
        /Sensitivity/i.test(bodyText) &&
        /Quality/i.test(bodyText) &&
        /Criticality/i.test(bodyText),
      tabs: /Results/i.test(bodyText) && /Datasets/i.test(bodyText) && /Glossary Terms/i.test(bodyText),
      table:
        /Asset Name/i.test(bodyText) &&
        /Metadata Coverage/i.test(bodyText) &&
        /Glossary Linkage/i.test(bodyText),
      preview:
        /Quick Actions/i.test(bodyText) &&
        /Lineage/i.test(bodyText) &&
        Boolean(document.querySelector(".gh-discovery-preview-card[data-asset-fqn]")),
      bottom:
        /Saved Views/i.test(bodyText) &&
        /Recommended Assets/i.test(bodyText) &&
        /Atlas AI Recommendations/i.test(bodyText),
    };
    return {
      url: window.location.href,
      title: document.querySelector(".gh-discovery-hero-copy h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 4200),
      hasNorthstar: Boolean(document.querySelector(".gh-discovery-main-grid")),
      loading: /Loading catalog|Preparing live discovery/i.test(bodyText),
      degraded: /Discovery search degraded|Discovery Unavailable|Live rows unavailable/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      rowCount,
      filterSelectCount: document.querySelectorAll(".gh-discovery-filter-select select").length,
      tabCount: document.querySelectorAll(".gh-discovery-results-tabs button").length,
      bottomCardCount: document.querySelectorAll(".gh-discovery-bottom-card").length,
      viewAllButtons,
      previewButtons,
      footer: rect(".ga-shell-footer"),
      grid: rect(".gh-discovery-main-grid"),
      hero: rect(".gh-discovery-hero"),
      results: rect(".gh-discovery-results-panel"),
      bottomGrid: rect(".gh-discovery-bottom-grid"),
      preview: rect(".gh-discovery-preview-card"),
      regionText,
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const viewAllOk = metrics.viewAllButtons.length >= 3 && metrics.viewAllButtons.every((button) => !button.disabled);
  const previewButtonsOk = metrics.previewButtons.every((button) => button.present && button.enabled);
  const mainAboveFooter =
    !metrics.footer ||
    ((!metrics.bottomGrid || metrics.bottomGrid.bottom <= metrics.footer.top + 1) &&
      (!metrics.preview || metrics.preview.bottom <= metrics.footer.top + 1));
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    !metrics.degraded &&
    !metrics.horizontalOverflow &&
    metrics.rowCount > 0 &&
    metrics.filterSelectCount >= 8 &&
    metrics.bottomCardCount === 3 &&
    regionsOk &&
    viewAllOk &&
    previewButtonsOk &&
    mainAboveFooter;
  report.captures.push({ viewport, screenshot: screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function firstResultRow(page) {
  const row = page.locator(".gh-discovery-table-row[data-asset-fqn]").first();
  await row.waitFor({ state: "visible", timeout: 45_000 });
  return row;
}

async function waitForResultRows(page) {
  await page.waitForFunction(
    () => document.querySelectorAll(".gh-discovery-table-row[data-asset-fqn]").length > 0,
    undefined,
    { timeout: 45_000 },
  );
}

async function firstOptionValue(page, label) {
  return page.evaluate((selectLabel) => {
    const select = document.querySelector(`select[aria-label="${selectLabel}"]`);
    if (!select) return "";
    return [...select.options].find((option) => option.value)?.value || "";
  }, label);
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });
  await recordInteraction(page, "Direct Discovery route settled", async () => {
    await gotoDiscovery(page);
    return { url: page.url(), rows: await page.locator(".gh-discovery-table-row[data-asset-fqn]").count() };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Search and clear", async () => {
    const input = page.getByLabel("Search discovery assets");
    await input.fill("customer");
    await waitForResultRows(page);
    const searchedRows = await page.locator(".gh-discovery-table-row[data-asset-fqn]").count();
    await input.fill("");
    await waitForResultRows(page);
    return { searchedRows };
  });

  await recordInteraction(page, "Domain filter and Clear All", async () => {
    const domain = await firstOptionValue(page, "Domain");
    if (!domain) return { skipped: "No live domain facet options available." };
    await page.getByLabel("Domain", { exact: true }).selectOption(domain);
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: "Clear All" }).click();
    await waitForResultRows(page);
    return { domain };
  });

  await recordInteraction(page, "More Filters opens and closes", async () => {
    await page.getByRole("button", { name: "More Filters" }).click();
    await page.waitForSelector("#gh-discovery-filter-popover", { state: "visible", timeout: 6000 });
    await page.locator("#gh-discovery-filter-popover").getByRole("button", { name: "Close" }).click();
    await page.waitForSelector("#gh-discovery-filter-popover", { state: "detached", timeout: 6000 });
  });

  await recordInteraction(page, "Result tab filter", async () => {
    const tabs = page.locator(".gh-discovery-results-tabs");
    await tabs.getByRole("button", { name: /Datasets/i }).click();
    await page.waitForTimeout(700);
    await tabs.getByRole("button", { name: /^Results\b/i }).click();
    await waitForResultRows(page);
  });

  await recordInteraction(page, "Sort menu", async () => {
    await page.locator(".gh-discovery-sort-trigger").click();
    const options = page.locator(".gh-discovery-sort-option");
    const count = await options.count();
    if (count < 1) throw new Error("No Discovery sort options rendered.");
    const target = count > 1 ? options.nth(1) : options.first();
    const option = String((await target.textContent()) || "").trim();
    await target.click();
    await page.waitForTimeout(500);
    return { option };
  });

  await recordInteraction(page, "Row selection and preview close", async () => {
    const rows = page.locator(".gh-discovery-table-row[data-asset-fqn]");
    const target = (await rows.count()) > 1 ? rows.nth(1) : rows.first();
    await target.click();
    await page.waitForSelector(".gh-discovery-preview-card[data-asset-fqn]", { timeout: 6000 });
    const selectedAsset = await page.locator(".gh-discovery-preview-card[data-asset-fqn]").getAttribute("data-asset-fqn");
    await page.getByRole("button", { name: "Close preview" }).click();
    await page.getByText("Nothing selected").waitFor({ timeout: 6000 });
    await (await firstResultRow(page)).click();
    await page.waitForSelector(".gh-discovery-preview-card[data-asset-fqn]", { timeout: 6000 });
    return { selectedAsset };
  });

  await recordInteraction(page, "Bottom card View all controls", async () => {
    const buttons = page.locator(".gh-discovery-bottom-card header button");
    const labels = [];
    const count = await buttons.count();
    for (let index = 0; index < count; index += 1) {
      const button = buttons.nth(index);
      const label = String((await button.textContent()) || "").trim();
      labels.push(label);
      if (await button.isEnabled()) {
        await button.click();
        await page.waitForTimeout(500);
      }
    }
    await waitForResultRows(page);
    return { labels };
  });

  await recordInteraction(page, "Ask Atlas AI recommendations", async () => {
    await page.getByRole("button", { name: /Ask Atlas AI/i }).click();
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText || "";
        const aiRunning = [...document.querySelectorAll(".gh-discovery-bottom-card header button")]
          .some((button) => /Running/i.test(button.textContent || ""));
        return /Atlas AI Recommendations/i.test(text) && !/Atlas AI is gathering|Asking Atlas AI/i.test(text) && !aiRunning;
      },
      undefined,
      { timeout: 90_000 },
    );
  });

  await recordInteraction(page, "Discovery to Asset 360 action", async () => {
    await gotoDiscovery(page);
    await (await firstResultRow(page)).click();
    await page.waitForSelector(".gh-discovery-preview-actions", { timeout: 45_000 });
    await page.locator(".gh-discovery-preview-actions button:has-text('Open Asset 360')").click();
    await page.waitForSelector(".gh-entity-workspace", { timeout: 90_000 });
    return { url: page.url() };
  });

  await recordInteraction(page, "Discovery to Lineage action", async () => {
    await gotoDiscovery(page);
    await (await firstResultRow(page)).click();
    await page.waitForSelector(".gh-discovery-preview-actions", { timeout: 45_000 });
    await page.locator(".gh-discovery-preview-actions button:has-text('View Lineage')").click();
    await page.waitForSelector("[data-testid='lineage-northstar-explorer']", { timeout: 90_000 });
    return { url: page.url() };
  });

  await recordInteraction(page, "Discovery to Governance action", async () => {
    await gotoDiscovery(page);
    await (await firstResultRow(page)).click();
    await page.waitForSelector(".gh-discovery-preview-actions", { timeout: 45_000 });
    await page.locator(".gh-discovery-preview-actions button:has-text('Start Stewardship Review')").click();
    await page.waitForSelector("[data-testid='governance-northstar-workbench']", { timeout: 90_000 });
    return { url: page.url() };
  });
}

const { page, close } = await connect();
try {
  await fs.mkdir(OUT_DIR, { recursive: true });
  for (const viewport of VIEWPORTS) {
    await captureViewport(page, viewport);
  }
  await runInteractions(page);
  await flushReport();
} finally {
  await close?.();
}

if (!report.passed) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}

console.log(JSON.stringify(report, null, 2));
