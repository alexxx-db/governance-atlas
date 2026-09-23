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
  process.env.GOVAT_GLOSSARY_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/glossary-live-current");
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
  route: "glossary",
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

async function waitForTaxonomy(page) {
  await page.waitForSelector("[data-testid='taxonomy-northstar']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return /Glossary & CDE Registry/i.test(text) && /Glossary/i.test(text) && /CDE Registry/i.test(text) && !/Loading taxonomy overview|Preparing the workspace surface/i.test(text);
    },
    undefined,
    { timeout: 120_000 },
  );
}

async function gotoGlossary(page) {
  await page.goto(urlFor("/taxonomy"), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForTaxonomy(page);
}

async function recordInteraction(page, interaction, run) {
  const item = { route: "glossary", interaction, loaded: false };
  try {
    const details = await run();
    item.loaded = true;
    Object.assign(item, details || {});
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `glossary-live-failure-${interaction.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function main() {
  const { page, close } = await connect();
  try {
    await gotoGlossary(page);
    report.captures.push({
      route: "glossary",
      viewport: "1536x1024",
      screenshot: await screenshot(page, "glossary-live-1536x1024"),
      loaded: true,
    });

    await recordInteraction(page, "deployed-glossary-tab-click-validation", async () => {
      await gotoGlossary(page);
      const glossaryTab = page.getByRole("tab", { name: /Glossary/i }).first();
      const cdeTab = page.getByRole("tab", { name: /CDE Registry/i }).first();
      await glossaryTab.click();
      await page.waitForSelector(".gh-taxonomy-prototype-card", { state: "visible", timeout: 30_000 });
      const glossarySelected = await glossaryTab.getAttribute("aria-selected");
      const glossaryCardCount = await page.locator(".gh-taxonomy-prototype-card").count();
      const glossaryText = (await page.locator(".gh-taxonomy-prototype-section").first().innerText()).slice(0, 1200);
      await cdeTab.click();
      await page.waitForSelector(".gh-taxonomy-prototype-cde-row,.gh-taxonomy-prototype-empty", { state: "visible", timeout: 30_000 });
      const cdeSelected = await cdeTab.getAttribute("aria-selected");
      const cdeRowCount = await page.locator(".gh-taxonomy-prototype-cde-row").count();
      const cdeText = (await page.locator(".gh-taxonomy-prototype-section").first().innerText()).slice(0, 1200);
      await glossaryTab.click();
      await page.waitForSelector(".gh-taxonomy-prototype-card", { state: "visible", timeout: 30_000 });
      const returnedGlossarySelected = await glossaryTab.getAttribute("aria-selected");
      const checks = {
        glossarySelected: glossarySelected === "true",
        cdeSelected: cdeSelected === "true",
        returnedGlossarySelected: returnedGlossarySelected === "true",
        glossaryHasCards: glossaryCardCount > 0,
        cdeHasRowsOrEmptyState: cdeRowCount > 0 || /No CDE registry rows available/i.test(cdeText),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Glossary tab validation failed checks: ${JSON.stringify(checks)}`);
      }
      const tabScreenshot = await screenshot(page, "glossary-live-tabs-returned-1536x1024");
      return { glossaryCardCount, cdeRowCount, glossaryText, cdeText, tabScreenshot, validation: { checks } };
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
  report.interactions.push({ route: "glossary", interaction: "script-error", loaded: false, error: error?.message || String(error) });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
