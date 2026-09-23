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
  process.env.GOVAT_CDE_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/cde-live-current");
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
  route: "cde-registry",
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

async function waitForCdeRegistry(page) {
  await page.waitForSelector("[data-testid='taxonomy-northstar']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return /Glossary & CDE Registry/i.test(text) && /CDE Registry/i.test(text) && !/Loading taxonomy overview|Preparing the workspace surface/i.test(text);
    },
    undefined,
    { timeout: 120_000 },
  );
  const cdeTab = page.getByRole("tab", { name: /CDE Registry/i }).first();
  if ((await cdeTab.count()) && (await cdeTab.getAttribute("aria-selected")) !== "true") {
    await cdeTab.click();
  }
  await page.waitForFunction(
    () => {
      const rows = document.querySelectorAll(".gh-taxonomy-prototype-cde-row").length;
      const empty = /No CDE registry rows available/i.test(document.body?.innerText || "");
      return rows > 0 || empty;
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function gotoCdeRegistry(page) {
  await page.goto(urlFor("/taxonomy?tab=cdes"), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForCdeRegistry(page);
}

async function recordInteraction(page, interaction, run) {
  const item = { route: "cde-registry", interaction, loaded: false };
  try {
    const details = await run();
    item.loaded = true;
    Object.assign(item, details || {});
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `cde-live-failure-${interaction.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function main() {
  const { page, close } = await connect();
  try {
    await gotoCdeRegistry(page);
    report.captures.push({
      route: "cde-registry",
      viewport: "1536x1024",
      screenshot: await screenshot(page, "cde-live-1536x1024"),
      loaded: true,
    });

    await recordInteraction(page, "deployed-cde-selected-detail-screenshot", async () => {
      await gotoCdeRegistry(page);
      const row = page.locator(".gh-taxonomy-prototype-cde-row").first();
      await row.waitFor({ state: "visible", timeout: 20_000 });
      const rowText = String((await row.innerText()) || "").trim();
      await row.click();
      const detail = page.locator(".gh-taxonomy-prototype-detail").first();
      await detail.waitFor({ state: "visible", timeout: 10_000 });
      const detailText = await detail.innerText();
      const checks = {
        selectedDetail: /Selected detail/i.test(detailText),
        sourceOfRecord: /Source-of-record column/i.test(detailText),
        ownership: /Ownership/i.test(detailText),
        reviewerWorkflow: /Reviewer workflow/i.test(detailText),
        associationSource: /Association source/i.test(detailText),
        backingEvidenceBoundary:
          /returned backing evidence|Quality, recertification, and Unity Catalog proof require returned backing evidence/i.test(detailText) ||
          /Status and recertification are registry metadata values/i.test(document.body?.innerText || ""),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`CDE detail screenshot failed checks: ${JSON.stringify(checks)}`);
      }
      const detailScreenshot = await screenshot(page, "cde-live-selected-detail-1536x1024");
      return {
        rowText: rowText.slice(0, 1000),
        detailText: detailText.slice(0, 1500),
        detailScreenshot,
        validation: { checks },
      };
    });

    await recordInteraction(page, "deployed-cde-unavailable-workflow-controls", async () => {
      await gotoCdeRegistry(page);
      await clickVisible(page.getByRole("button", { name: /\+ New term/i }).first(), "New CDE request");
      const requestStatus = await page.locator(".gh-taxonomy-prototype-status").first().innerText();
      const row = page.locator(".gh-taxonomy-prototype-cde-row").first();
      await row.click();
      await page.locator(".gh-taxonomy-prototype-detail").first().waitFor({ state: "visible", timeout: 10_000 });
      const recertButton = page.getByRole("button", { name: /Request recertification unavailable/i }).first();
      const recertDisabled = await recertButton.isDisabled();
      await clickVisible(page.getByRole("button", { name: /Show owner workflow note/i }).first(), "Show owner workflow note");
      const ownerStatus = await page.locator(".gh-taxonomy-prototype-status").first().innerText();
      await clickVisible(page.getByRole("button", { name: /Show recertification note/i }).first(), "Show recertification note");
      const recertStatus = await page.locator(".gh-taxonomy-prototype-status").first().innerText();
      const openSourceDisabled = await page.getByRole("button", { name: /Open source asset/i }).first().isDisabled().catch(() => false);
      const openLineageDisabled = await page.getByRole("button", { name: /Open lineage/i }).first().isDisabled().catch(() => false);
      const checks = {
        requestUnavailable: /New CDE request is unavailable|backed CDE registry workflow/i.test(requestStatus),
        recertDisabled,
        ownerStatusUnavailable: /owner workflow is unavailable|no CDE owner mutation/i.test(ownerStatus),
        recertStatusUnavailable: /recertification workflow is unavailable|no CDE mutation/i.test(recertStatus),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`CDE unavailable workflow checks failed: ${JSON.stringify(checks)}`);
      }
      return { requestStatus, recertDisabled, openSourceDisabled, openLineageDisabled, ownerStatus, recertStatus, validation: { checks } };
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
  report.interactions.push({ route: "cde-registry", interaction: "script-error", loaded: false, error: error?.message || String(error) });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
