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
  process.env.GOVAT_STEWARDSHIP_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/stewardship-live-current");
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
  route: "stewardship",
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
    report.captures.every((capture) => capture.loaded) &&
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
    if (status < 400 || /favicon|\.map($|\?)/i.test(response.url())) return;
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

async function waitForStewardship(page) {
  await page.waitForSelector("[data-testid='governance-northstar-workbench']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Stewardship Workbench/i.test(text) &&
        /Work queue|Open Governance Requests/i.test(text) &&
        !/Loading governance requests|Preparing workspace shell|Preparing the workspace surface/i.test(text)
      );
    },
    undefined,
    { timeout: 120_000 },
  );
  await page.waitForFunction(
    () => {
      const rows = document.querySelectorAll(".gh-governance-ns-table button[role='row']");
      const text = document.body?.innerText || "";
      return rows.length > 0 || /No open work items are available for this filter|No open work items are attached to this asset/i.test(text);
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function gotoStewardship(page) {
  await page.goto(urlFor("/stewardship"), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForStewardship(page);
}

async function recordInteraction(page, interaction, run) {
  const item = { route: "stewardship", interaction, loaded: false };
  try {
    const details = await run();
    item.loaded = true;
    Object.assign(item, details || {});
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `stewardship-live-failure-${interaction.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function main() {
  const { page, close } = await connect();
  try {
    await gotoStewardship(page);
    report.captures.push({
      route: "stewardship",
      viewport: "1536x1024",
      screenshot: await screenshot(page, "stewardship-live-1536x1024"),
      loaded: true,
    });

    await recordInteraction(page, "deployed-stewardship-row-selection", async () => {
      await gotoStewardship(page);
      const rows = page.locator(".gh-governance-ns-table button[role='row']");
      const rowCount = await rows.count();
      const bodyText = String((await page.locator("body").innerText()) || "").trim();
      const validationLeak = /Validation sample|ga-home-seed|VAL-\d+/i.test(bodyText);
      if (validationLeak) {
        throw new Error("Live Stewardship queue exposed validation seed work items.");
      }
      if (rowCount === 0) {
        const emptyText = String((await page.locator(".gh-governance-ns-empty").first().innerText()) || "").trim();
        const detailText = String((await page.locator(".gh-governance-ns-detail").first().innerText()) || "").trim();
        const commentControls = await page.getByRole("button", { name: "Comment" }).count();
        const resolveControls = await page.getByRole("button", { name: "Resolve" }).count();
        const checks = {
          emptyStateVisible: /No open work items/i.test(emptyText),
          detailPlaceholderVisible: /Select a work item/i.test(detailText),
          validationSeedsHidden: true,
          mutationControlsHidden: commentControls === 0 && resolveControls === 0,
        };
        if (Object.values(checks).some((value) => value === false)) {
          throw new Error(`Stewardship empty-state validation failed checks: ${JSON.stringify(checks)}`);
        }
        return {
          rowCount,
          mode: "truthful-empty-state",
          emptyText: emptyText.slice(0, 1000),
          detailText: detailText.slice(0, 1500),
          commentControls,
          resolveControls,
          validation: { checks },
        };
      }
      const first = rows.first();
      const target = rowCount > 1 ? rows.nth(1) : first;
      const firstText = String((await first.innerText()) || "").trim();
      await first.click();
      await page.waitForSelector(".gh-governance-ns-detail h2", { state: "visible", timeout: 10_000 });
      const firstDetail = String((await page.locator(".gh-governance-ns-detail h2").first().innerText()) || "").trim();
      const targetText = String((await target.innerText()) || "").trim();
      await target.click();
      await page.waitForSelector(".gh-governance-ns-detail h2", { state: "visible", timeout: 10_000 });
      const selectedRows = await page.locator(".gh-governance-ns-table button[role='row'].is-selected").count();
      const detailTitle = String((await page.locator(".gh-governance-ns-detail h2").first().innerText()) || "").trim();
      const detailText = String((await page.locator(".gh-governance-ns-detail").first().innerText()) || "").trim();
      const checks = {
        rowCountPositive: rowCount > 0,
        detailVisible: Boolean(detailTitle),
        detailUpdated: rowCount === 1 || firstDetail !== detailTitle || firstText !== targetText,
        selectedAtMostOne: selectedRows <= 1,
        governanceEvidence: /Affected Asset|Why this is open|Implementation|Validation sample|Stewardship/i.test(detailText),
        validationSeedsHidden: !/Validation sample|ga-home-seed|VAL-\d+/i.test(`${firstText}\n${targetText}\n${detailText}`),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Stewardship row selection failed checks: ${JSON.stringify(checks)}`);
      }
      const detailScreenshot = await screenshot(page, "stewardship-live-selected-detail-1536x1024");
      return {
        rowCount,
        firstText: firstText.slice(0, 1000),
        selectedText: targetText.slice(0, 1000),
        detailTitle,
        detailText: detailText.slice(0, 1500),
        selectedRows,
        detailScreenshot,
        validation: { checks },
      };
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
  report.interactions.push({ route: "stewardship", interaction: "script-error", loaded: false, error: error?.message || String(error) });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
