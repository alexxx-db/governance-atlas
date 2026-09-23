import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const OUT_DIR =
  process.env.GOVAT_DISCOVER_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/discover-live-current");
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  evidenceKind: "live_databricks",
  mockApi: false,
  route: "discover",
  captures: [],
  interactions: [],
  pageErrors: [],
  requestFailures: [],
  console: [],
};

function urlFor(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.pageErrors.length === 0 &&
    report.requestFailures.length === 0 &&
    !report.console.some((entry) => entry.type === "error") &&
    report.interactions.length > 0 &&
    report.interactions.every((interaction) => interaction.loaded);
  await fs.writeFile(path.join(OUT_DIR, "prototype-current-report.json"), JSON.stringify(report, null, 2));
}

async function connect() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    extraHTTPHeaders: DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {},
    viewport: { width: 1536, height: 1024 },
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => {
    report.pageErrors.push({ message: error?.message || String(error), stack: error?.stack || "", url: page.url() });
    void flushReport();
  });
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    report.console.push({ type: message.type(), text: message.text(), url: page.url() });
    void flushReport();
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText || "";
    if (/ERR_ABORTED/i.test(failure)) return;
    report.requestFailures.push({ method: request.method(), url: request.url(), failure });
    void flushReport();
  });
  page.on("response", (response) => {
    const status = response.status();
    if (status < 400 || /favicon|\\.map($|\\?)/i.test(response.url())) return;
    report.requestFailures.push({ method: response.request().method(), url: response.url(), status });
    void flushReport();
  });
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

async function waitForDiscover(page) {
  await page.waitForSelector(".gh-discovery-main-grid", { state: "visible", timeout: 90_000 });
  await waitForDiscoverLoading(page);
  await page.waitForSelector(".gh-discovery-table-row.gh-discovery-asset-card", { state: "visible", timeout: 30_000 });
}

async function waitForDiscoverLoading(page, timeout = 90_000) {
  await page.waitForFunction(
    () => !/Loading discovery|Preparing the workspace surface|Reading visible catalog metadata/i.test(document.body?.innerText || ""),
    undefined,
    { timeout },
  );
}

async function gotoDiscover(page) {
  let lastError = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.goto(urlFor("/discover"), { waitUntil: "domcontentloaded", timeout: 90_000 });
    try {
      await waitForDiscover(page);
      return;
    } catch (error) {
      lastError = error;
      await screenshot(page, `discover-live-route-wait-attempt-${attempt}`);
      await page.waitForTimeout(1500);
    }
  }
  throw lastError || new Error("Discover route did not settle");
}

async function clickVisible(locator, label) {
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const item = locator.nth(index);
    if ((await item.isVisible().catch(() => false)) && (await item.isEnabled().catch(() => false))) {
      await item.scrollIntoViewIfNeeded().catch(() => {});
      await item.click();
      return true;
    }
  }
  throw new Error(`${label} was not visible and enabled`);
}

async function firstResultFqn(page) {
  return page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first().getAttribute("data-asset-fqn");
}

async function recordInteraction(page, interaction, run) {
  const item = { route: "discover", interaction, loaded: false };
  try {
    const details = await run();
    item.runResult = details || {};
    item.loaded = true;
    Object.assign(item, details || {});
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `discover-live-failure-${interaction.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function main() {
  const { page, close } = await connect();
  try {
    await gotoDiscover(page);
    report.captures.push({
      route: "discover",
      viewport: "1536x1024",
      screenshot: await screenshot(page, "discover-live-1536x1024"),
      loaded: true,
    });

    await recordInteraction(page, "deployed-discover-search-and-layout-controls", async () => {
      await waitForDiscoverLoading(page);
      await clickVisible(page.getByRole("button", { name: /List view/i }).first(), "List view");
      const listPressed = await page.getByRole("button", { name: /List view/i }).first().getAttribute("aria-pressed");
      await clickVisible(page.getByRole("button", { name: /Grid view/i }).first(), "Grid view");
      const gridPressed = await page.getByRole("button", { name: /Grid view/i }).first().getAttribute("aria-pressed");
      await clickVisible(page.getByRole("button", { name: /Saved searches/i }).first(), "Saved searches");
      await page.getByRole("dialog", { name: /Saved searches/i }).waitFor({ state: "visible", timeout: 10_000 });
      const savedDialog = await page.getByRole("dialog", { name: /Saved searches/i }).first().innerText();
      await page.keyboard.press("Escape");
      await page.getByRole("dialog", { name: /Saved searches/i }).waitFor({ state: "hidden", timeout: 10_000 }).catch(() => {});
      const search = page.getByLabel("Search discovery assets").first();
      await search.fill("customer");
      await search.press("Enter");
      await waitForDiscoverLoading(page);
      await page.waitForFunction(() => /customer|results|visible assets/i.test(document.body?.innerText || ""), undefined, { timeout: 20_000 });
      const afterSearch = await page.evaluate(() => document.body.innerText.slice(0, 2000));
      const clear = page.getByRole("button", { name: /Clear search/i }).first();
      if (await clear.isVisible().catch(() => false)) await clear.click();
      await waitForDiscoverLoading(page);
      const checks = {
        listPressed: listPressed === "true",
        gridPressed: gridPressed === "true",
        savedSearchesVisible: /Revenue CDEs|PII assets|High coverage certified/i.test(savedDialog),
        searchApplied: /customer/i.test(afterSearch),
        resultsVisible: /Showing\s+\d+|visible assets|assets/i.test(afterSearch),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Discover search/layout checks failed: ${JSON.stringify(checks)}`);
      }
      return { afterSearch: afterSearch.slice(0, 1000), listPressed, gridPressed, savedDialog: savedDialog.slice(0, 500), validation: { checks } };
    });

    await recordInteraction(page, "deployed-discover-row-menu-routing", async () => {
      await gotoDiscover(page);
      const originalFqn = await firstResultFqn(page);
      await clickVisible(page.getByRole("button", { name: /Open asset actions/i }).first(), "Open asset actions");
      await page.getByRole("menu").first().waitFor({ state: "visible", timeout: 10_000 });
      await clickVisible(page.getByRole("menuitem", { name: /View details/i }).first(), "View details");
      await page.waitForURL(/\/entity\//, { timeout: 20_000 });
      const detailPath = new URL(page.url()).pathname;
      await gotoDiscover(page);
      await clickVisible(page.getByRole("button", { name: /Open asset actions/i }).first(), "Open asset actions");
      await clickVisible(page.getByRole("menuitem", { name: /Open governance/i }).first(), "Open governance");
      await page.waitForURL(/\/governance/, { timeout: 20_000 });
      const governancePath = `${new URL(page.url()).pathname}${new URL(page.url()).search}`;
      await gotoDiscover(page);
      await clickVisible(page.getByRole("button", { name: /Open asset actions/i }).first(), "Open asset actions");
      await clickVisible(page.getByRole("menuitem", { name: /Open lineage/i }).first(), "Open lineage");
      await page.waitForURL(/\/lineage\//, { timeout: 20_000 });
      const lineagePath = new URL(page.url()).pathname;
      const checks = {
        originalFqn: Boolean(originalFqn),
        detailPath: /\/entity\//.test(detailPath),
        governancePath: /\/governance/.test(governancePath),
        lineagePath: /\/lineage\//.test(lineagePath),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Discover row menu checks failed: ${JSON.stringify(checks)}`);
      }
      return { originalFqn, detailPath, governancePath, lineagePath, validation: { checks } };
    });

    await recordInteraction(page, "deployed-discover-preview-tabs-and-actions", async () => {
      await gotoDiscover(page);
      await page.locator(".gh-discovery-table-row.gh-discovery-asset-card").first().click();
      await page.waitForSelector(".gh-selection-preview", { state: "visible", timeout: 20_000 });
      const tabs = {};
      for (const name of ["Overview", "Columns", "Lineage", "Quality", "Access"]) {
        const tab = page.getByRole("tab", { name: new RegExp(name, "i") }).first();
        if (await tab.isVisible().catch(() => false)) {
          await tab.click();
          tabs[name] = await tab.getAttribute("aria-selected");
        }
      }
      const comment = page.getByRole("button", { name: /Comment/i }).first();
      const requestAccess = page.getByRole("button", { name: /Request access/i }).first();
      const reviewCert = page.getByRole("button", { name: /Review cert|Review certification/i }).first();
      const commentDisabled = await comment.isDisabled().catch(() => false);
      const requestAccessDisabled = await requestAccess.isDisabled().catch(() => false);
      let reviewPath = "";
      if (await reviewCert.isVisible().catch(() => false)) {
        await reviewCert.click();
        await page.waitForURL(/\/governance/, { timeout: 20_000 });
        reviewPath = `${new URL(page.url()).pathname}${new URL(page.url()).search}`;
      }
      const checks = {
        overviewTab: tabs.Overview === "true",
        columnsTab: tabs.Columns === "true",
        lineageTab: tabs.Lineage === "true",
        qualityTab: tabs.Quality === "true",
        accessTab: tabs.Access === "true",
        commentUnavailable: commentDisabled,
        requestAccessUnavailable: requestAccessDisabled,
        reviewRoutesGovernance: /\/governance/.test(reviewPath),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Discover preview checks failed: ${JSON.stringify(checks)}`);
      }
      return { tabs, commentDisabled, requestAccessDisabled, reviewPath, validation: { checks } };
    });

    await recordInteraction(page, "deployed-discover-atlas-ai", async () => {
      await gotoDiscover(page);
      await clickVisible(page.getByRole("button", { name: /Atlas AI/i }).first(), "Atlas AI");
      const input = page.getByPlaceholder(/Ask about/i).first();
      await input.fill("Which governed assets are visible in Discover?");
      await input.press("Enter");
      const panel = page.getByRole("dialog", { name: /Atlas AI/i }).first();
      await panel.waitFor({ state: "visible", timeout: 10_000 });
      await page.waitForFunction(
        () => {
          const messages = Array.from(document.querySelectorAll(".gh-floating-ai-message.tone-assistant:not(.is-pending)"));
          return messages.some((message) => {
            const text = message.textContent || "";
            return /Discover|asset|evidence|Unity Catalog|governed metadata/i.test(text) && !/Checking governed metadata/i.test(text);
          });
        },
        undefined,
        { timeout: 90_000 },
      );
      const panelText = await panel.innerText();
      const checks = {
        promptVisible: /Which governed assets are visible in Discover/i.test(panelText),
        assistantAnswered: /ATLAS AI/i.test(panelText) && !/Checking governed metadata/i.test(panelText),
        groundedCopy: /Discover|asset|evidence|Unity Catalog|governed metadata/i.test(panelText),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Discover Atlas AI checks failed: ${JSON.stringify(checks)}`);
      }
      const close = page.getByRole("button", { name: /Close Atlas AI/i }).first();
      if (await close.isVisible().catch(() => false)) await close.click();
      return { panelText: panelText.slice(0, 1200), validation: { checks } };
    });
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
  report.interactions.push({ route: "discover", interaction: "script-error", loaded: false, error: error?.message || String(error) });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
