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
  process.env.GOVAT_AUDIT_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/audit-current");
const DOWNLOAD_DIR = path.join(OUT_DIR, "downloads");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const MOCKUP_PATH = path.join(REPO_ROOT, "northstar/screenshots/prototype_audit1.png");
const VIEWPORTS = [
  { name: "1536x1024", width: 1536, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x720", width: 1280, height: 720 },
];

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  appUrl: BASE_URL,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  evidenceKind: "live_databricks",
  mockApi: false,
  captures: [],
  interactions: [],
  sideBySide: null,
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function auditUrl() {
  return route("/audit");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    Boolean(report.sideBySide?.path) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(path.join(OUT_DIR, "audit-live-report.json"), JSON.stringify(report, null, 2));
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
    acceptDownloads: true,
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

async function waitForAudit(page) {
  await page.waitForSelector("[data-testid='audit-northstar']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Immutable governance event log/i.test(text) &&
        /Time \(UTC\)/i.test(text) &&
        /Generate report/i.test(text) &&
        /Export CSV/i.test(text) &&
        !/Loading audit trail|Preparing workspace shell|Preparing the workspace surface/i.test(text)
      );
    },
    undefined,
    { timeout: 120_000 },
  );
  await page.waitForFunction(
    () => {
      const rows = document.querySelectorAll(".gh-audit-row").length;
      const empty = /No audit events match/i.test(document.body?.innerText || "");
      return rows > 0 || empty;
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function gotoAudit(page) {
  await page.goto(auditUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForAudit(page);
  await page.waitForTimeout(800);
}

async function recordInteraction(page, name, fn) {
  const item = { name, loaded: false, passed: false };
  try {
    const detail = (await fn()) || {};
    Object.assign(item, detail, { loaded: true, passed: true });
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(
      page,
      `audit-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    );
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
  return {
    filePath,
    text,
    artifact: {
      path: path.relative(REPO_ROOT, filePath),
      suggestedFilename: suggested,
      bytes: Buffer.byteLength(text),
    },
  };
}

async function captureViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  let navigationError = "";
  for (const attempt of [1, 2]) {
    try {
      await gotoAudit(page);
      navigationError = "";
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
    navigationError ? `audit-live-${viewport.name}-failure` : `audit-live-${viewport.name}`,
  );
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const box = node.getBoundingClientRect();
      if (box.width === 0 && box.height === 0) return null;
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
    const footer = rect(".ga-shell-footer");
    const shell = rect(".gh-audit-shell");
    const main = document.querySelector(".gh-main");
    const tableHeadings = [...document.querySelectorAll(".gh-audit-table-head span")]
      .map((node) => node.textContent?.trim() || "")
      .filter(Boolean);
    const tabs = [...document.querySelectorAll(".gh-audit-prototype-tabs button")]
      .map((node) => node.textContent?.trim() || "")
      .filter(Boolean);
    const disabledActions = [...document.querySelectorAll(".gh-audit-selected-actions button, .gh-audit-source button")]
      .filter((button) => button.disabled)
      .map((button) => button.textContent?.trim() || button.getAttribute("title") || "");
    const regionText = {
      title: /Immutable governance event log/i.test(bodyText),
      noLegacyTitle: !/Audit Evidence Browser/i.test(bodyText),
      hero: /Every governance action/i.test(bodyText) || /Audit evidence is unavailable/i.test(bodyText),
      kpis:
        /Events/i.test(bodyText) &&
        /Policy violations/i.test(bodyText) &&
        /Access reviews/i.test(bodyText) &&
        /Retention/i.test(bodyText),
      filters: tabs.includes("All events") && tabs.includes("By users") && tabs.includes("By services") && tabs.includes("Violations"),
      table:
        tableHeadings.includes("Time (UTC)") &&
        tableHeadings.includes("Actor") &&
        tableHeadings.includes("Event") &&
        tableHeadings.includes("Target") &&
        tableHeadings.includes("Evidence"),
      actions: /Date range/i.test(bodyText) && /Generate report/i.test(bodyText) && /Export CSV/i.test(bodyText),
      truthfulUnavailable:
        /Retention policy not reported|Retention/i.test(bodyText) &&
        /Append-only Delta audit log|governance-store\+metadata-audit-log|Audit evidence source unavailable|Audit trail is steward\/admin only/i.test(bodyText),
      rowState: document.querySelectorAll(".gh-audit-row").length > 0 || /No audit events match/i.test(bodyText),
    };
    return {
      url: window.location.href,
      title: document.querySelector(".gh-audit-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 5200),
      hasNorthstar: Boolean(document.querySelector("[data-testid='audit-northstar']")),
      loading: /Loading audit trail|Preparing workspace shell|Preparing the workspace surface/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      mainScrollHeight: main?.scrollHeight || 0,
      mainClientHeight: main?.clientHeight || 0,
      mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
      footer,
      shell,
      table: rect(".gh-audit-table-panel"),
      detail: rect(".gh-audit-selected-detail"),
      kpiCount: document.querySelectorAll(".gh-audit-kpi").length,
      filterCount: tabs.length,
      tableHeadingCount: tableHeadings.length,
      rowCount: document.querySelectorAll(".gh-audit-row").length,
      selectedRowCount: document.querySelectorAll(".gh-audit-row.is-selected").length,
      selectedDetailPresent: Boolean(document.querySelector(".gh-audit-selected-detail")),
      disabledActions,
      regionText,
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer || !metrics.shell || metrics.shell.bottom <= metrics.footer.top + 1;
  const railSeparated =
    !metrics.table || !metrics.detail || metrics.table.right <= metrics.detail.left - 8;
  const footerSafe =
    viewport.height <= 760
      ? bottomAboveFooter || metrics.mainScrolls
      : bottomAboveFooter;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    metrics.title === "Immutable governance event log" &&
    metrics.kpiCount === 4 &&
    metrics.filterCount === 4 &&
    metrics.tableHeadingCount === 5 &&
    metrics.regionText.rowState &&
    metrics.selectedRowCount <= 1 &&
    railSeparated &&
    regionsOk &&
    !metrics.horizontalOverflow &&
    footerSafe;
  report.captures.push({ viewport, screenshotPath, metrics: { ...metrics, railSeparated }, navigationError, loaded: passed, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });

  await recordInteraction(page, "Direct Audit route settled", async () => {
    await gotoAudit(page);
    return {
      url: page.url(),
      rows: await page.locator(".gh-audit-row").count(),
      selectedRows: await page.locator(".gh-audit-row.is-selected").count(),
    };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Audit API RLS and actor exposure contract", async () => {
    await gotoAudit(page);
    const apiResult = await page.evaluate(async () => {
      const response = await fetch("/api/atlas/audit/evidence?date_range=24h&limit=50", {
        headers: { Accept: "application/json" },
      });
      const contentType = response.headers.get("content-type") || "";
      const body = contentType.includes("application/json")
        ? await response.json()
        : { detail: await response.text() };
      return { status: response.status, body };
    });
    const body = apiResult.body || {};
    const meta = body.meta || {};
    const capabilities = meta.capabilities || {};
    const summary = body.summary || {};
    const events = Array.isArray(body.events) ? body.events : [];
    const redactedActorSamples = events
      .map((event) => String(event.actor_email || event.actorEmail || event.actor || "").trim())
      .filter(Boolean)
      .slice(0, 5)
      .map((actor) => actor.replace(/^(.{2}).*(@.*)$/i, "$1***$2"));
    const checks = {
      statusOk: apiResult.status === 200,
      sourceIsAuditLog: /metadata-audit-log/i.test(String(meta.source || "")),
      roleGated: capabilities.requiredRole === "steward-or-admin",
      rowLevelSecurity: capabilities.rowLevelSecurity === "visible-assets-only",
      actorExposureGated: capabilities.actorIdentityExposure === "steward-admin-gated",
      rowScopeVisibleAssets: summary.rowScope === "visible-assets",
      hiddenRowsExcludedReported:
        Number.isFinite(Number(summary.hiddenRowsExcluded)) && Number(summary.hiddenRowsExcluded) >= 0,
      noUnscopedActorExposure:
        capabilities.rowLevelSecurity === "visible-assets-only" &&
        capabilities.actorIdentityExposure === "steward-admin-gated",
    };
    if (Object.values(checks).some((value) => value === false)) {
      throw new Error(`Audit API RLS contract failed checks: ${JSON.stringify(checks)}`);
    }
    return {
      status: apiResult.status,
      state: meta.state || "",
      authoritative: body.authoritative,
      source: meta.source || "",
      capabilities,
      summary: {
        rowScope: summary.rowScope,
        hiddenRowsExcluded: summary.hiddenRowsExcluded,
        totalChanges: summary.totalChanges,
      },
      validation: { checks },
      redactedActorSamples,
    };
  });

  await recordInteraction(page, "Date range menu and audit category filters", async () => {
    await gotoAudit(page);
    await page.getByRole("button", { name: /Date range/i }).click();
    await page.getByRole("menuitemradio", { name: /7d/i }).click();
    await page.getByText(/Audit date range set to 7d/i).waitFor({ state: "visible", timeout: 10_000 });
    const tabStates = {};
    for (const name of ["All events", "By users", "By services", "Violations"]) {
      const tab = page.getByRole("button", { name: new RegExp(name, "i") }).first();
      await tab.click();
      tabStates[name] = await tab.getAttribute("aria-pressed");
    }
    await page.getByRole("button", { name: /All events/i }).first().click();
    if (tabStates["All events"] !== "true") {
      throw new Error(`Audit tab state did not record the expected active state: ${JSON.stringify(tabStates)}`);
    }
    return { tabStates };
  });

  await recordInteraction(page, "Row selection and detail actions", async () => {
    await gotoAudit(page);
    const rowCount = await page.locator(".gh-audit-row").count();
    if (rowCount === 0) {
      const emptyVisible = await page.getByText(/No audit events match/i).isVisible().catch(() => false);
      if (!emptyVisible) {
        throw new Error("Audit has zero rows but no truthful empty audit state is visible.");
      }
      return {
        rowCount,
        noRowsTruthfulUnavailable: true,
        detailActionUnavailable: true,
      };
    }
    const firstRow = page.locator(".gh-audit-row").first();
    await firstRow.waitFor({ state: "visible", timeout: 20_000 });
    const rowText = String((await firstRow.textContent()) || "").trim();
    await firstRow.click();
    const detail = page.getByLabel("Selected audit event detail").first();
    await detail.waitFor({ state: "visible", timeout: 10_000 });
    const detailText = await detail.innerText();
    const selectedAfterClick = await page.locator(".gh-audit-row.is-selected").count();
    const copyButton = page.getByRole("button", { name: /Copy request ID/i }).first();
    const copyVisible = await copyButton.isVisible().catch(() => false);
    const copyEnabled = copyVisible && (await copyButton.isEnabled().catch(() => false));
    if (copyEnabled) await copyButton.click();
    const openAsset = page.getByRole("button", { name: /^Open asset$/i }).first();
    const openAssetVisible = await openAsset.isVisible().catch(() => false);
    const openAssetEnabled = openAssetVisible && (await openAsset.isEnabled().catch(() => false));
    if (selectedAfterClick !== 1 || !/Selected evidence/i.test(detailText)) {
      throw new Error("Audit row selection did not expose the selected evidence detail.");
    }
    return {
      rowText: rowText.slice(0, 1000),
      detailText: detailText.slice(0, 1500),
      selectedAfterClick,
      copyVisible,
      copyEnabled,
      openAssetVisible,
      openAssetEnabled,
      selectedDetailScreenshot: await screenshot(page, "audit-live-selected-detail-1536x1024"),
    };
  });

  await recordInteraction(page, "Report artifact download", async () => {
    await gotoAudit(page);
    const rowCount = await page.locator(".gh-audit-row").count();
    if (rowCount === 0) {
      await page.getByRole("button", { name: /Generate report/i }).click();
      await page.getByText(/Report unavailable because no audit rows match/i).waitFor({ state: "visible", timeout: 10_000 });
      return {
        rowCount,
        artifact: null,
        truthfulUnavailable: true,
        validation: { checks: { noRowsTruthfulUnavailable: true } },
      };
    }
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20_000 }),
      page.getByRole("button", { name: /Generate report/i }).click(),
    ]);
    const { text, artifact } = await saveDownload(download, "audit-report");
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
    return { artifact, artifactEvidenceKind: parsed.evidenceKind, authoritative: parsed.authoritative, eventCount: parsed.events.length, validation: { checks } };
  });

  await recordInteraction(page, "CSV artifact download", async () => {
    await gotoAudit(page);
    const rowCount = await page.locator(".gh-audit-row").count();
    if (rowCount === 0) {
      await page.getByRole("button", { name: /Export CSV/i }).click();
      await page.getByText(/CSV export unavailable because no audit rows match/i).waitFor({ state: "visible", timeout: 10_000 });
      return {
        rowCount,
        artifact: null,
        truthfulUnavailable: true,
        validation: { checks: { noRowsTruthfulUnavailable: true } },
      };
    }
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20_000 }),
      page.getByRole("button", { name: /Export CSV/i }).click(),
    ]);
    const { text, artifact } = await saveDownload(download, "audit-events");
    const rows = text.split(/\r?\n/).filter(Boolean);
    const header = rows[0] || "";
    const checks = {
      hasRows: rows.length > 1,
      hasEvidenceKindColumn: header.includes("evidence_kind"),
      hasAuthoritativeColumn: header.includes("authoritative"),
      notPrototypeMockCsv: !/prototype_mock/i.test(text),
    };
    if (Object.values(checks).some((value) => value === false)) {
      throw new Error(`Audit CSV artifact failed checks: ${JSON.stringify(checks)}`);
    }
    return { artifact, header, validation: { checks } };
  });
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(browser) {
  const currentPath = path.join(OUT_DIR, "audit-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await browser.newPage({ viewport: { width: 3200, height: 1120 } });
  const outputPath = path.join(OUT_DIR, "audit-live-side-by-side-1536x1024.png");
  try {
    await page.setContent(
      `<!doctype html>
        <html>
          <head>
            <meta charset="utf-8" />
            <style>
              body {
                margin: 0;
                background: #061625;
                color: #d9e9f8;
                font-family: Inter, Arial, sans-serif;
              }
              .wrap {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
                padding: 16px;
              }
              .panel {
                border: 1px solid rgba(79, 197, 255, 0.28);
                background: #03111e;
              }
              h1 {
                font-size: 18px;
                font-weight: 700;
                margin: 12px 16px;
              }
              img {
                display: block;
                width: 100%;
                height: auto;
              }
            </style>
          </head>
          <body>
            <div class="wrap">
              <section class="panel">
                <h1>Reference: northstar/screenshots/prototype_audit1.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current: Audit live 1536x1024</h1>
                <img src="${currentUrl}" />
              </section>
            </div>
          </body>
        </html>`,
      { waitUntil: "load" },
    );
    await page.screenshot({ path: outputPath, fullPage: true });
    report.sideBySide = { path: outputPath, mockupPath: MOCKUP_PATH, currentPath };
    await flushReport();
  } finally {
    await page.close().catch(() => {});
  }
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const session = await connect();
  try {
    for (const viewport of VIEWPORTS) {
      await captureViewport(session.page, viewport);
    }
    await runInteractions(session.page);
    await createSideBySide(session.page.context().browser());
    await flushReport();
    console.log(JSON.stringify(report, null, 2));
    if (!report.passed) process.exit(1);
  } finally {
    await session.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
