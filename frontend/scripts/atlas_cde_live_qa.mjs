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
  process.env.GOVAT_CDE_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/cde-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const MOCKUP_PATH = path.join(REPO_ROOT, "northstar/screenshots/prototype_stewardship2.png");
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

function cdeUrl() {
  return route("/taxonomy?tab=cdes");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    Boolean(report.sideBySide?.path) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(path.join(OUT_DIR, "cde-live-report.json"), JSON.stringify(report, null, 2));
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

async function waitForCde(page) {
  await page.waitForSelector("[data-testid='taxonomy-northstar']", { state: "visible", timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Glossary & CDE Registry/i.test(text) &&
        /CDE Registry/i.test(text) &&
        /Shared business meaning, anchored to data/i.test(text) &&
        !/Loading glossary registry|Loading taxonomy overview|Preparing workspace shell|Preparing the workspace surface/i.test(text)
      );
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
      const hasRows = document.querySelectorAll(".gh-taxonomy-prototype-cde-row").length > 0;
      const empty = /No CDE registry rows available/i.test(document.body?.innerText || "");
      return hasRows || empty;
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function gotoCde(page) {
  await page.goto(cdeUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForCde(page);
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
      `cde-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    );
  }
  report.interactions.push(item);
  await flushReport();
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

async function captureViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  let navigationError = "";
  for (const attempt of [1, 2]) {
    try {
      await gotoCde(page);
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
    navigationError ? `cde-live-${viewport.name}-failure` : `cde-live-${viewport.name}`,
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
    const page = rect("[data-testid='taxonomy-northstar']");
    const shell = rect(".gh-taxonomy-prototype-shell");
    const main = document.querySelector(".gh-main");
    const headings = [...document.querySelectorAll(".gh-taxonomy-prototype-cde-head span")].map((node) => node.textContent?.trim() || "");
    const tabs = [...document.querySelectorAll(".gh-taxonomy-prototype-tabs button")].map((node) => node.textContent?.trim() || "");
    const detailCards = [...document.querySelectorAll(".gh-taxonomy-prototype-detail-card h3")].map((node) => node.textContent?.trim() || "");
    const disabledActions = [...document.querySelectorAll(".gh-taxonomy-prototype-card-foot button, .gh-taxonomy-prototype-detail-actions button")]
      .filter((button) => button.disabled)
      .map((button) => button.textContent?.trim() || button.getAttribute("title") || "");
    const cdeTab = [...document.querySelectorAll(".gh-taxonomy-prototype-tabs button")]
      .find((button) => /CDE Registry/i.test(button.textContent || ""));
    const regionText = {
      title: /Shared business meaning, anchored to data/i.test(bodyText),
      supportCopy: /Glossary terms link to source-of-record assets/i.test(bodyText),
      tabs: tabs.some((tab) => /Glossary/i.test(tab)) && tabs.some((tab) => /CDE Registry/i.test(tab)),
      registry:
        headings.includes("CDE") &&
        headings.includes("Source-of-record column") &&
        headings.includes("Owner") &&
        headings.includes("Recert") &&
        headings.includes("Status"),
      provenance: /Status and recertification are registry metadata values/i.test(bodyText),
      detail:
        detailCards.length === 0 ||
        (
          detailCards.includes("Source-of-record column") &&
          detailCards.includes("Ownership") &&
          detailCards.includes("Reviewer workflow") &&
          detailCards.includes("Association source")
        ),
      truthfulUnavailable:
        /returned backing evidence|quality test-run|recertification workflow proof|Unity Catalog proof/i.test(bodyText) &&
        !/Certified Candidates/i.test(bodyText),
    };
    return {
      url: window.location.href,
      title: document.querySelector(".gh-taxonomy-prototype-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 5200),
      hasNorthstar: Boolean(document.querySelector("[data-testid='taxonomy-northstar']")),
      loading: /Loading glossary registry|Loading taxonomy overview|Preparing workspace shell|Preparing the workspace surface/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      mainScrollHeight: main?.scrollHeight || 0,
      mainClientHeight: main?.clientHeight || 0,
      mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
      footer,
      page,
      shell,
      registry: rect(".gh-taxonomy-prototype-cde-table"),
      detail: rect(".gh-taxonomy-prototype-detail"),
      kpiCount: 0,
      visibleFilters: tabs.length,
      tableHeadingCount: headings.length,
      groupCount: 0,
      rowCount: document.querySelectorAll(".gh-taxonomy-prototype-cde-row").length,
      selectedRowCount: document.querySelectorAll(".gh-taxonomy-prototype-cde-row.is-selected").length,
      detailTabCount: tabs.length,
      detailCardCount: detailCards.length,
      cdeTabSelected: cdeTab?.getAttribute("aria-selected") === "true",
      disabledActions,
      regionText,
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer || !metrics.shell || metrics.shell.bottom <= metrics.footer.top + 1;
  const railSeparated =
    !metrics.registry || !metrics.detail || metrics.registry.right <= metrics.detail.left - 8;
  const footerSafe =
    viewport.height <= 760
      ? bottomAboveFooter || metrics.mainScrolls
      : bottomAboveFooter;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    metrics.title === "Shared business meaning, anchored to data" &&
    metrics.cdeTabSelected &&
    metrics.visibleFilters === 2 &&
    metrics.tableHeadingCount === 5 &&
    metrics.rowCount > 0 &&
    railSeparated &&
    regionsOk &&
    !metrics.horizontalOverflow &&
    footerSafe;
  report.captures.push({ viewport, screenshotPath, metrics: { ...metrics, railSeparated }, navigationError, loaded: passed, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });

  await recordInteraction(page, "Direct CDE route settled", async () => {
    await gotoCde(page);
    return {
      url: page.url(),
      rows: await page.locator(".gh-taxonomy-prototype-cde-row").count(),
      cdeTabSelected: await page.getByRole("tab", { name: /CDE Registry/i }).first().getAttribute("aria-selected"),
    };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Glossary/CDE tab round trip", async () => {
    await gotoCde(page);
    const glossaryTab = page.getByRole("tab", { name: /Glossary/i }).first();
    const cdeTab = page.getByRole("tab", { name: /CDE Registry/i }).first();
    await glossaryTab.click();
    await page.waitForSelector(".gh-taxonomy-prototype-card,.gh-taxonomy-prototype-empty", { state: "visible", timeout: 20_000 });
    const glossarySelected = await glossaryTab.getAttribute("aria-selected");
    await cdeTab.click();
    await page.waitForSelector(".gh-taxonomy-prototype-cde-row,.gh-taxonomy-prototype-empty", { state: "visible", timeout: 20_000 });
    const cdeSelected = await cdeTab.getAttribute("aria-selected");
    if (glossarySelected !== "true" || cdeSelected !== "true") {
      throw new Error(`CDE tab round trip failed: ${JSON.stringify({ glossarySelected, cdeSelected })}`);
    }
    return { glossarySelected, cdeSelected };
  });

  await recordInteraction(page, "Row selection and selected detail", async () => {
    await gotoCde(page);
    const row = page.locator(".gh-taxonomy-prototype-cde-row").first();
    await row.waitFor({ state: "visible", timeout: 20_000 });
    const rowText = String((await row.textContent()) || "").trim();
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
      throw new Error(`CDE selected detail failed checks: ${JSON.stringify(checks)}`);
    }
    return {
      rowText: rowText.slice(0, 1000),
      detailText: detailText.slice(0, 1500),
      selectedRows: await page.locator(".gh-taxonomy-prototype-cde-row.is-selected").count(),
      detailScreenshot: await screenshot(page, "cde-live-selected-detail-1536x1024"),
      validation: { checks },
    };
  });

  await recordInteraction(page, "Unavailable CDE workflow controls", async () => {
    await gotoCde(page);
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
    const openSource = page.getByRole("button", { name: /Open source asset/i }).first();
    const openLineage = page.getByRole("button", { name: /Open lineage/i }).first();
    const openSourceEnabled = await openSource.isEnabled().catch(() => false);
    const openLineageEnabled = await openLineage.isEnabled().catch(() => false);
    const checks = {
      requestUnavailable: /New CDE request is unavailable|backed CDE registry workflow/i.test(requestStatus),
      recertDisabled,
      ownerStatusUnavailable: /owner workflow is unavailable|no CDE owner mutation/i.test(ownerStatus),
      recertStatusUnavailable: /recertification workflow is unavailable|no CDE mutation/i.test(recertStatus),
    };
    if (Object.values(checks).some((value) => value === false)) {
      throw new Error(`CDE unavailable workflow checks failed: ${JSON.stringify(checks)}`);
    }
    return { requestStatus, recertDisabled, openSourceEnabled, openLineageEnabled, ownerStatus, recertStatus, validation: { checks } };
  });
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(browser) {
  const currentPath = path.join(OUT_DIR, "cde-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await browser.newPage({ viewport: { width: 3200, height: 1120 } });
  const outputPath = path.join(OUT_DIR, "cde-live-side-by-side-1536x1024.png");
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
                <h1>Reference: northstar/screenshots/prototype_stewardship2.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current: CDE live 1536x1024</h1>
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

main().catch(async (error) => {
  report.pageErrors.push({ message: error?.message || String(error), stack: error?.stack || "" });
  await flushReport().catch(() => {});
  console.error(error);
  process.exit(1);
});
