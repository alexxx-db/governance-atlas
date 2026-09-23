import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { copyChromeProfileToTemp, resolveChromeProfileName } from "./chrome_profile_tmp.mjs";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  process.argv[2] ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const CDP_URL = process.env.GOVAT_CDP_URL || "http://127.0.0.1:9223";
const ALLOW_PROFILE_FALLBACK = process.env.GOVAT_ALLOW_CHROME_PROFILE_FALLBACK === "1";
const CHROME_PROFILE_ROOT =
  process.env.GOVAT_CHROME_PROFILE_ROOT ||
  path.join(process.env.HOME || "", "Library", "Application Support", "Google", "Chrome");
const OUT_DIR =
  process.env.GOVAT_TAXONOMY_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/taxonomy-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const MOCKUP_PATH = path.join(REPO_ROOT, "docs/mockups/mock7.png");
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
  sideBySide: null,
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function taxonomyUrl() {
  return route("/taxonomy");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    Boolean(report.sideBySide?.path) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "taxonomy-live-report.json"),
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

async function launchCopiedProfile() {
  const profileName = await resolveChromeProfileName(CHROME_PROFILE_ROOT);
  const copiedProfile = await copyChromeProfileToTemp({
    chromeProfileRoot: CHROME_PROFILE_ROOT,
    profileName,
    prefix: "govat-taxonomy-chrome-profile-",
  });
  let context;
  try {
    context = await chromium.launchPersistentContext(copiedProfile.profileRoot, {
      channel: "chrome",
      headless: false,
      viewport: { width: 1536, height: 1024 },
      args: [`--profile-directory=${profileName}`],
    });
  } catch (error) {
    await copiedProfile.cleanup();
    throw error;
  }
  const page = context.pages()[0] || (await context.newPage());
  attachRuntimeListeners(page);
  return {
    page,
    close: async () => {
      await context.close().catch(() => {});
      await copiedProfile.cleanup();
    },
  };
}

async function connect() {
  try {
    const browser = await chromium.connectOverCDP(CDP_URL);
    const context = browser.contexts()[0] || (await browser.newContext());
    const page = await context.newPage();
    attachRuntimeListeners(page);
    return {
      page,
      close: async () => {
        await page.close().catch(() => {});
      },
    };
  } catch (error) {
    if (!DATABRICKS_TOKEN && !ALLOW_PROFILE_FALLBACK) {
      throw new Error(
        `Unable to connect to authenticated Chrome over ${CDP_URL}: ${error?.message || String(error)}`,
      );
    }
    if (!DATABRICKS_TOKEN && ALLOW_PROFILE_FALLBACK) {
      return launchCopiedProfile();
    }
  }

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

async function waitForTaxonomy(page) {
  await page.waitForSelector("[data-testid='taxonomy-northstar']", { timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Business Taxonomy & Glossary/i.test(text) &&
        /Organize and govern the business language/i.test(text) &&
        /Terms in/i.test(text) &&
        /Glossary term detail/i.test(document.querySelector(".gh-taxonomy-detail")?.getAttribute("aria-label") || "") &&
        !/Loading taxonomy overview|Preparing workspace shell|Preparing the workspace surface/i.test(text)
      );
    },
    undefined,
    { timeout: 90_000 },
  );
  await page.waitForFunction(
    () => {
      const rows = document.querySelectorAll(".gh-taxonomy-table-row").length;
      const empty = /No live terms match this view|No live glossary term selected/i.test(document.body?.innerText || "");
      return rows > 0 || empty;
    },
    undefined,
    { timeout: 45_000 },
  );
}

async function gotoTaxonomy(page) {
  await page.goto(taxonomyUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForTaxonomy(page);
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
      `taxonomy-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
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
      await gotoTaxonomy(page);
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
    navigationError ? `taxonomy-live-${viewport.name}-failure` : `taxonomy-live-${viewport.name}`,
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
    const main = document.querySelector(".gh-main");
    const oldSurface = /Taxonomy Workbench|Governance taxonomy|LIVE STORE/i.test(bodyText);
    const contextButtons = [...document.querySelectorAll(".gh-taxonomy-contexts button")]
      .map((button) => button.textContent?.trim() || "");
    const detailTabs = [...document.querySelectorAll(".gh-taxonomy-detail-tabs button")]
      .map((button) => button.textContent?.trim() || "");
    const viewAllButtons = [...document.querySelectorAll(".gh-taxonomy-section-head button")]
      .map((button) => ({
        label: button.textContent?.trim() || "",
        disabled: button.disabled,
        title: button.getAttribute("title") || "",
      }));
    const previous = document.querySelector("button[aria-label='Previous page']");
    const next = document.querySelector("button[aria-label='Next page']");
    const rowAction = document.querySelector(".gh-taxonomy-row-action");
    const selectedTermName = document.querySelector(".gh-taxonomy-detail h2")?.textContent?.trim() || "";
    const termsHeading = document.querySelector(".gh-taxonomy-terms-panel h2")?.textContent?.trim() || "";
    const termsCount = Number(document.querySelector(".gh-taxonomy-terms-panel .gh-taxonomy-count")?.textContent?.trim() || "0");
    const synonymCard = [...document.querySelectorAll(".gh-taxonomy-detail-card")]
      .find((card) => (card.querySelector("h3")?.textContent || "").trim() === "Synonyms");
    const synonymChips = synonymCard
      ? [...synonymCard.querySelectorAll(".gh-taxonomy-tags span")].map((node) => node.textContent?.trim() || "").filter(Boolean)
      : [];
    const linkedAssetsCard = [...document.querySelectorAll(".gh-taxonomy-detail-card")]
      .find((card) => /Linked Assets/i.test(card.querySelector("h3")?.textContent || ""));
    const linkedAssetHeading = linkedAssetsCard?.querySelector("h3")?.textContent?.trim() || "";
    const linkedAssetCount = Number((linkedAssetHeading.match(/(\d+)/) || [])[1] || "0");
    const linkedAssetRows = linkedAssetsCard?.querySelectorAll(".gh-taxonomy-linked-assets button")?.length || 0;
    const moreAssetsText = linkedAssetsCard?.querySelector(".gh-taxonomy-more-assets")?.textContent?.trim() || "";
    const regionText = {
      title: /Business Taxonomy & Glossary/i.test(bodyText),
      supportCopy: /Organize and govern the business language of your organization/i.test(bodyText),
      taxonomyRail:
        /Taxonomy/i.test(document.querySelector(".gh-taxonomy-panel-label")?.textContent || "") &&
        contextButtons.includes("Classifications") &&
        contextButtons.includes("Domains") &&
        contextButtons.includes("Data Products") &&
        contextButtons.includes("Column Groups"),
      sourceState:
        /No live classifications defined|No live domains defined|No live data products defined|No live column groups defined/i.test(bodyText) ||
        document.querySelectorAll(".gh-taxonomy-tree button").length >= 4,
      terms:
        /Terms in/i.test(bodyText) &&
        Boolean(document.querySelector(".gh-taxonomy-search input")) &&
        /Term/i.test(bodyText) &&
        /Status/i.test(bodyText) &&
        /Steward/i.test(bodyText),
      detail:
        Boolean(document.querySelector(".gh-taxonomy-detail[aria-label='Glossary term detail']")) &&
        /Definition/i.test(bodyText) &&
        /Owner/i.test(bodyText) &&
        /Steward/i.test(bodyText) &&
        /Approval Status/i.test(bodyText),
      tabs:
        detailTabs.includes("Overview") &&
        detailTabs.includes("Technical") &&
        detailTabs.includes("History") &&
        detailTabs.includes("Related"),
      secondary:
        /Domain Relationship/i.test(bodyText) &&
        /Data Products/i.test(bodyText) &&
        /Classifications/i.test(bodyText),
      provenance:
        Boolean(document.querySelector(".gh-taxonomy-row-action:disabled")) &&
        /Favorite unavailable|More term actions unavailable|Term actions unavailable/i.test(
          [...document.querySelectorAll("[aria-label]")]
            .map((node) => node.getAttribute("aria-label") || "")
            .join(" "),
        ),
    };
    return {
      url: window.location.href,
      title: document.querySelector(".gh-taxonomy-ns-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 5000),
      hasNorthstar: Boolean(document.querySelector("[data-testid='taxonomy-northstar']")),
      loading: /Loading taxonomy overview|Preparing workspace shell|Preparing the workspace surface/i.test(bodyText),
      oldSurface,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      mainScrollHeight: main?.scrollHeight || 0,
      mainClientHeight: main?.clientHeight || 0,
      mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
      footer: rect(".ga-shell-footer"),
      page: rect("[data-testid='taxonomy-northstar']"),
      layout: rect(".gh-taxonomy-ns-layout"),
      rail: rect(".gh-taxonomy-rail"),
      terms: rect(".gh-taxonomy-terms-panel"),
      detail: rect(".gh-taxonomy-detail"),
      termRowCount: document.querySelectorAll(".gh-taxonomy-table-row").length,
      selectedRowCount: document.querySelectorAll(".gh-taxonomy-table-row.is-selected").length,
      contextButtonCount: contextButtons.length,
      detailTabCount: detailTabs.length,
      classificationCount: document.querySelectorAll(".gh-taxonomy-tree button").length,
      previousDisabled: Boolean(previous?.disabled),
      nextDisabled: Boolean(next?.disabled),
      rowActionDisabled: Boolean(rowAction?.disabled),
      rowActionLabel: rowAction?.getAttribute("aria-label") || "",
      viewAllButtons,
      selectedTermName,
      termsHeading,
      termsCount,
      synonymChips,
      synonymUniqueCount: new Set(synonymChips).size,
      linkedAssetHeading,
      linkedAssetCount,
      linkedAssetRows,
      moreAssetsText,
      regionText,
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer || !metrics.layout || metrics.layout.bottom <= metrics.footer.top + 1;
  const footerSafe =
    viewport.height <= 760
      ? bottomAboveFooter || metrics.mainScrolls
      : bottomAboveFooter;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    !metrics.oldSurface &&
    metrics.title === "Business Taxonomy & Glossary" &&
    metrics.contextButtonCount === 4 &&
    metrics.detailTabCount === 4 &&
    metrics.classificationCount >= 4 &&
    metrics.termRowCount > 0 &&
    metrics.selectedRowCount === 1 &&
    metrics.previousDisabled &&
    !metrics.nextDisabled &&
    metrics.selectedTermName === "Net Revenue" &&
    /Terms in Revenue/i.test(metrics.termsHeading) &&
    metrics.termsCount >= 18 &&
    metrics.synonymChips.includes("Net Sales") &&
    metrics.synonymChips.includes("Revenue, Net") &&
    metrics.synonymChips.length === metrics.synonymUniqueCount &&
    metrics.linkedAssetCount >= 8 &&
    metrics.linkedAssetRows === 3 &&
    /\+5 more assets/i.test(metrics.moreAssetsText) &&
    metrics.rowActionDisabled &&
    /Term actions unavailable/i.test(metrics.rowActionLabel) &&
    regionsOk &&
    !metrics.horizontalOverflow &&
    footerSafe;
  report.captures.push({ viewport, screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });

  await recordInteraction(page, "Direct Taxonomy route settled", async () => {
    await gotoTaxonomy(page);
    return { url: page.url(), rows: await page.locator(".gh-taxonomy-table-row").count() };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Category tabs and branch selection", async () => {
    await page.getByRole("button", { name: /^Domains$/i }).click();
    await page.waitForFunction(
      () => /Domain Root/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    const customer = page.getByRole("tree").getByRole("button", { name: /Customer/i });
    if (await customer.count()) {
      await customer.first().click();
      await page.waitForFunction(
        () => /Terms in Customer/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 10_000 },
      );
    }
    await page.getByRole("button", { name: /^Classifications$/i }).click();
    await page.waitForFunction(
      () => /Classification Root/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    const revenue = page.getByRole("tree").getByRole("button", { name: /Revenue/i });
    if (await revenue.count()) {
      await revenue.first().click();
      await page.waitForFunction(
        () => /Terms in Revenue/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 10_000 },
      );
    }
    return { selectedBranch: (await revenue.count()) ? "Revenue" : ((await customer.count()) ? "Customer" : "All Terms") };
  });

  await recordInteraction(page, "Term row selection", async () => {
    const row = page.locator(".gh-taxonomy-table-row").first();
    await row.waitFor({ state: "visible", timeout: 20_000 });
    await row.locator(".gh-taxonomy-term-row-main").click();
    const term = String((await row.locator(".gh-taxonomy-term-cell").textContent()) || "").trim();
    await page.locator(".gh-taxonomy-detail h2", { hasText: term }).waitFor({ timeout: 10_000 });
    return { term };
  });

  await recordInteraction(page, "Search filters and clears", async () => {
    const input = page.locator(".gh-taxonomy-search input");
    await input.fill("Revenue");
    await page.locator(".gh-taxonomy-table-row", { hasText: /Revenue/i }).first().waitFor({ timeout: 10_000 });
    const matchingRows = await page.locator(".gh-taxonomy-table-row").count();
    await input.fill("missing-taxonomy-term");
    await page.locator(".gh-taxonomy-table-empty", { hasText: "No live terms match this view" }).waitFor({ timeout: 10_000 });
    await input.fill("");
    await page.locator(".gh-taxonomy-table-row").first().waitFor({ state: "visible", timeout: 10_000 });
    return { matchingRows };
  });

  await recordInteraction(page, "Status filter menu", async () => {
    await page.getByRole("button", { name: "Filter terms by status" }).click();
    await page.getByRole("button", { name: /^Approved$/i }).click();
    await page.locator(".gh-taxonomy-table-row").first().waitFor({ timeout: 10_000 });
    await page.getByRole("button", { name: "Filter terms by status" }).click();
    await page.getByRole("button", { name: /^All statuses$/i }).click();
    await page.locator(".gh-taxonomy-table-row").first().waitFor({ state: "visible", timeout: 10_000 });
    return { selectedStatus: "Approved" };
  });

  await recordInteraction(page, "Detail tabs switch", async () => {
    await page.getByRole("tab", { name: "Technical" }).click();
    await page.locator(".gh-taxonomy-technical dt", { hasText: "Term ID" }).waitFor({ timeout: 10_000 });
    await page.getByRole("tab", { name: "History" }).click();
    await page.locator(".gh-taxonomy-history h3", { hasText: "History" }).waitFor({ timeout: 10_000 });
    await page.getByRole("tab", { name: "Related" }).click();
    await page.locator(".gh-taxonomy-detail-card", { hasText: "Linked Assets" }).waitFor({ timeout: 10_000 });
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.locator(".gh-taxonomy-definition h3", { hasText: "Definition" }).waitFor({ timeout: 10_000 });
  });

  await recordInteraction(page, "Pagination and unavailable actions", async () => {
    const previous = page.getByRole("button", { name: "Previous page" });
    const next = page.getByRole("button", { name: "Next page" });
    const pageSize = page.getByRole("button", { name: "Rows per page" });
    const previousDisabled = await previous.isDisabled();
    const nextInitiallyEnabled = !(await next.isDisabled());
    const rowsPerPageVisible = await pageSize.isVisible();
    const rowAction = page.locator(".gh-taxonomy-row-action").first();
    const rowActionDisabled = await rowAction.isDisabled();
    const rowActionLabel = await rowAction.getAttribute("aria-label");
    if (!previousDisabled || !nextInitiallyEnabled || !rowsPerPageVisible || !rowActionDisabled) {
      throw new Error("Pagination or unavailable row-action controls are not in the expected state.");
    }
    await next.click();
    await page.waitForFunction(
      () => /11-\d+ of 18/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    const previousEnabledAfterNext = !(await previous.isDisabled());
    await previous.click();
    await page.waitForFunction(
      () => /1-10 of 18/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    await pageSize.click();
    await page.getByRole("menu").getByRole("button", { name: "20 per page" }).click();
    await page.waitForFunction(
      () => /1-18 of 18/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    await pageSize.click();
    await page.getByRole("menu").getByRole("button", { name: "10 per page" }).click();
    await page.waitForFunction(
      () => /1-10 of 18/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 10_000 },
    );
    return {
      previousDisabled,
      nextInitiallyEnabled,
      previousEnabledAfterNext,
      rowsPerPageVisible,
      rowActionLabel,
    };
  });

  await recordInteraction(page, "Secondary View all controls", async () => {
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.locator(".gh-taxonomy-definition h3", { hasText: "Definition" }).waitFor({ timeout: 10_000 });
    const buttons = page.locator(".gh-taxonomy-section-head button");
    const labels = [];
    const count = await buttons.count();
    for (let index = 0; index < count; index += 1) {
      const button = buttons.nth(index);
      const label = String((await button.textContent()) || "").trim();
      const disabled = await button.isDisabled();
      labels.push({ label, disabled });
      if (!disabled) {
        await button.click();
        await page.waitForTimeout(250);
        await button.click();
      }
    }
    if (count < 2) throw new Error("Expected linked-assets and data-products View all controls.");
    return { labels };
  });

  await recordInteraction(page, "Linked asset routing or empty state", async () => {
    await page.getByRole("tab", { name: "Related" }).click();
    await page.locator(".gh-taxonomy-detail-card", { hasText: "Linked Assets" }).waitFor({ timeout: 10_000 });
    const linkedAssets = page.locator(".gh-taxonomy-linked-assets button:not([disabled])");
    const count = await linkedAssets.count();
    if (count > 0) {
      await linkedAssets.first().click();
      await page.waitForSelector(".gh-entity-workspace", { timeout: 90_000 });
      return { routed: true, url: page.url() };
    }
    await page.locator(".gh-taxonomy-detail-card", { hasText: "No linked assets are recorded for this term." }).waitFor({ timeout: 10_000 });
    return { routed: false, emptyState: true };
  });
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(browser) {
  const currentPath = path.join(OUT_DIR, "taxonomy-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await browser.newPage({ viewport: { width: 3200, height: 1120 } });
  const outputPath = path.join(OUT_DIR, "taxonomy-live-side-by-side-1536x1024.png");
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
                <h1>Reference: docs/mockups/mock7.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current: Taxonomy live 1536x1024</h1>
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
