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
  process.env.GOVAT_AUDIT_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/audit-live-current");
const DOWNLOAD_DIR = path.join(OUT_DIR, "downloads");
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
  route: "audit",
  captures: [],
  interactions: [],
  downloads: [],
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
    acceptDownloads: true,
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

async function waitForAudit(page) {
  await page.waitForSelector("[data-testid='audit-northstar']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Immutable governance event log/i.test(text) &&
        /Time \(UTC\)/i.test(text) &&
        /Generate report/i.test(text) &&
        /Export CSV/i.test(text)
      );
    },
    undefined,
    { timeout: 120_000 },
  );
  await page.waitForFunction(
    () => {
      const rows = document.querySelectorAll(".gh-audit-row").length;
      const loading = /Loading audit trail|Preparing workspace shell|Preparing the workspace surface/i.test(document.body?.innerText || "");
      const empty = /No audit events match/i.test(document.body?.innerText || "");
      return rows > 0 || (empty && !loading);
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function gotoAudit(page) {
  await page.goto(urlFor("/audit"), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForAudit(page);
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

async function recordInteraction(page, interaction, run) {
  const item = { route: "audit", interaction, loaded: false };
  try {
    const details = await run();
    item.loaded = true;
    Object.assign(item, details || {});
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `audit-live-failure-${interaction.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function saveDownload(download, prefix) {
  await fs.mkdir(DOWNLOAD_DIR, { recursive: true });
  const suggested = download.suggestedFilename();
  const fileName = `${prefix}-${suggested}`.replace(/[^a-z0-9._-]+/gi, "-");
  const filePath = path.join(DOWNLOAD_DIR, fileName);
  await download.saveAs(filePath);
  const text = await fs.readFile(filePath, "utf8");
  const entry = {
    type: prefix,
    path: path.relative(REPO_ROOT, filePath),
    suggestedFilename: suggested,
    bytes: Buffer.byteLength(text),
  };
  report.downloads.push(entry);
  return { filePath, text, entry };
}

async function main() {
  const { page, close } = await connect();
  try {
    await gotoAudit(page);
    report.captures.push({
      route: "audit",
      viewport: "1536x1024",
      screenshot: await screenshot(page, "audit-live-1536x1024"),
      loaded: true,
    });

    await recordInteraction(page, "deployed-audit-date-filter-and-detail", async () => {
      await gotoAudit(page);
      await clickVisible(page.getByRole("button", { name: /Date range/i }).first(), "Date range");
      await clickVisible(page.getByRole("menuitemradio", { name: /7d/i }).first(), "7d date range");
      await page.getByText(/Audit date range set to 7d/i).waitFor({ state: "visible", timeout: 10_000 });
      const tabStates = {};
      for (const name of ["All events", "By users", "By services", "Violations"]) {
        const tab = page.getByRole("button", { name: new RegExp(name, "i") }).first();
        if (await tab.isVisible().catch(() => false)) {
          await tab.click();
          tabStates[name] = await tab.getAttribute("aria-pressed");
        }
      }
      await clickVisible(page.getByRole("button", { name: /All events/i }).first(), "All events");
      const firstRow = page.locator(".gh-audit-row").first();
      await firstRow.waitFor({ state: "visible", timeout: 20_000 });
      const rowText = String((await firstRow.innerText()) || "").trim();
      await firstRow.click();
      const detail = page.getByLabel("Selected audit event detail").first();
      await detail.waitFor({ state: "visible", timeout: 10_000 });
      const detailText = await detail.innerText();
      const detailScreenshot = await screenshot(page, "audit-live-selected-detail-1536x1024");
      const copyRequest = page.getByRole("button", { name: /Copy request ID/i }).first();
      const copyRequestVisible = await copyRequest.isVisible().catch(() => false);
      const copyRequestEnabled = copyRequestVisible && (await copyRequest.isEnabled().catch(() => false));
      if (copyRequestEnabled) {
        await copyRequest.click();
      }
      const statusText = await page.locator(".gh-audit-status-line").first().innerText();
      return {
        tabStates,
        rowText: rowText.slice(0, 1000),
        detailText: detailText.slice(0, 1500),
        detailScreenshot,
        copyRequestVisible,
        copyRequestEnabled,
        statusText,
      };
    });

    await recordInteraction(page, "deployed-audit-report-artifact", async () => {
      await gotoAudit(page);
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 20_000 }),
        page.getByRole("button", { name: /Generate report/i }).click(),
      ]);
      const { text, entry } = await saveDownload(download, "audit-report");
      const parsed = JSON.parse(text);
      const checks = {
        hasEvents: Array.isArray(parsed.events) && parsed.events.length > 0,
        hasSummary: Boolean(parsed.summary && typeof parsed.summary === "object"),
        hasEvidenceKind: Boolean(parsed.evidenceKind),
        notPrototypeMock: parsed.evidenceKind !== "prototype_mock" && parsed.prototypeMockEvidence !== true,
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Audit report artifact failed checks: ${JSON.stringify(checks)}`);
      }
      return {
        artifact: entry,
        artifactEvidenceKind: parsed.evidenceKind,
        authoritative: parsed.authoritative,
        eventCount: parsed.events.length,
        validation: { checks },
      };
    });

    await recordInteraction(page, "deployed-audit-csv-artifact", async () => {
      await gotoAudit(page);
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 20_000 }),
        page.getByRole("button", { name: /Export CSV/i }).click(),
      ]);
      const { text, entry } = await saveDownload(download, "audit-events");
      const firstLine = text.split(/\r?\n/)[0] || "";
      const checks = {
        hasRows: text.split(/\r?\n/).filter(Boolean).length > 1,
        hasEvidenceKindColumn: firstLine.includes("evidence_kind"),
        hasAuthoritativeColumn: firstLine.includes("authoritative"),
        notPrototypeMockCsv: !/prototype_mock/i.test(text),
      };
      if (Object.values(checks).some((value) => value === false)) {
        throw new Error(`Audit CSV artifact failed checks: ${JSON.stringify(checks)}`);
      }
      return { artifact: entry, header: firstLine, validation: { checks } };
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
  report.interactions.push({ route: "audit", interaction: "script-error", loaded: false, error: error?.message || String(error) });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
