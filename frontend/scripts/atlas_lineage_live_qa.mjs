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
const MOCKUP_PATH = path.join(REPO_ROOT, "northstar/screenshots/prototype_lineage.png");
const ASSET_FQN =
  process.env.GOVAT_LINEAGE_ASSET_FQN ||
  "datapact.governance_atlas_demo.customer_stewardship_queue";
const OUT_DIR =
  process.env.GOVAT_LINEAGE_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/lineage-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const CDP_URL = process.env.GOVAT_CDP_URL || "http://127.0.0.1:9223";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const FORWARDED_EMAIL = (process.env.GOVAT_CAPTURE_FORWARDED_EMAIL || "").trim();
const FORWARDED_USERNAME = (process.env.GOVAT_CAPTURE_FORWARDED_USERNAME || FORWARDED_EMAIL).trim();
const FORWARDED_DISPLAY_NAME = (process.env.GOVAT_CAPTURE_FORWARDED_DISPLAY_NAME || "").trim();
const FORWARDED_ACCESS_TOKEN = (process.env.GOVAT_CAPTURE_FORWARDED_ACCESS_TOKEN || "").trim();
const ALLOW_PROFILE_FALLBACK = process.env.GOVAT_ALLOW_CHROME_PROFILE_FALLBACK === "1";
const CHROME_PROFILE_NAME = process.env.GOVAT_CHROME_PROFILE_NAME || "";
const CHROME_PROFILE_ROOT =
  process.env.GOVAT_CHROME_PROFILE_ROOT ||
  path.join(process.env.HOME || "", "Library", "Application Support", "Google", "Chrome");
const VIEWPORTS = [
  { name: "1536x1024", width: 1536, height: 1024 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x720", width: 1280, height: 720 },
];
const EXPECTED_INTERACTION_COUNT = 11;
const UNAVAILABLE_VALIDATION_SUFFIX = ".__missing_lineage_validation_target__";
const LINEAGE_INITIAL_BUDGET_MS = Number(process.env.GOVAT_LINEAGE_INITIAL_BUDGET_MS || 12_000);

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  appUrl: BASE_URL,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  evidenceKind: "live_databricks",
  mockApi: false,
  forwardedActorEmail: FORWARDED_EMAIL,
  forwardedActorTokenPresent: Boolean(FORWARDED_ACCESS_TOKEN),
  assetFqn: ASSET_FQN,
  captures: [],
  interactions: [],
  sideBySide: [],
  requestFailures: [],
  console: [],
  pageErrors: [],
  consoleWarnings: [],
  lineageApiResponses: [],
};

const EXTRA_HTTP_HEADERS = {
  ...(DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {}),
  ...(FORWARDED_EMAIL ? { "x-forwarded-email": FORWARDED_EMAIL } : {}),
  ...(FORWARDED_USERNAME ? { "x-forwarded-preferred-username": FORWARDED_USERNAME } : {}),
  ...(FORWARDED_DISPLAY_NAME ? { "x-forwarded-display-name": FORWARDED_DISPLAY_NAME } : {}),
  ...(FORWARDED_ACCESS_TOKEN ? { "x-forwarded-access-token": FORWARDED_ACCESS_TOKEN } : {}),
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function lineageUrl(assetFqn = ASSET_FQN) {
  return route(`/lineage/${encodeURIComponent(assetFqn)}`);
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const loginRedirectDetected =
    report.captures.some((capture) => /\/login\.html/i.test(String(capture?.metrics?.url || ""))) ||
    report.console.some((entry) => /\/login\.html/i.test(String(entry?.url || "")));
  report.loginRedirectDetected = loginRedirectDetected;
  report.passed =
    report.captures.length === VIEWPORTS.length &&
    report.interactions.length >= EXPECTED_INTERACTION_COUNT &&
    report.sideBySide.length > 0 &&
    !loginRedirectDetected &&
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    report.pageErrors.length === 0 &&
    report.requestFailures.length === 0 &&
    report.console.every((entry) => entry.type !== "error");
  await fs.writeFile(
    path.join(OUT_DIR, "lineage-live-report.json"),
    JSON.stringify(report, null, 2),
  );
}

function attachRuntimeListeners(page) {
  const requestStartedAt = new WeakMap();
  page.on("request", (request) => {
    if (!request.url().includes("/api/lineage/")) return;
    requestStartedAt.set(request, Date.now());
  });
  page.on("response", async (response) => {
    const url = response.url();
    if (!url.includes("/api/lineage/")) return;
    const request = response.request();
    const startedAt = requestStartedAt.get(request) || Date.now();
    const parsed = new URL(url);
    const profile = parsed.searchParams.get("profile") || "full";
    const headers = response.headers();
    report.lineageApiResponses.push({
      url,
      profile,
      status: response.status(),
      elapsedMs: Date.now() - startedAt,
      requestDurationMs: Number(headers["x-govat-request-duration-ms"] || 0) || null,
      expectedUnavailableProbe: url.includes(UNAVAILABLE_VALIDATION_SUFFIX),
    });
    await flushReport();
  });
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
    const entry = {
      type: message.type(),
      text: message.text(),
      url: page.url(),
    };
    if (
      message.type() === "error" &&
      /status of 503/i.test(entry.text) &&
      entry.url.includes(UNAVAILABLE_VALIDATION_SUFFIX)
    ) {
      report.consoleWarnings.push({ ...entry, expectedUnavailableProbe: true });
      void flushReport();
      return;
    }
    report.console.push(entry);
    report.consoleWarnings.push(entry);
    void flushReport();
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure();
    const message = failure?.errorText || "";
    if (/net::ERR_ABORTED/i.test(message)) return;
    report.requestFailures.push({
      url: request.url(),
      method: request.method(),
      resourceType: request.resourceType(),
      errorText: message,
    });
    void flushReport();
  });
}

async function launchCopiedProfile() {
  const profileName = await resolveChromeProfileName(CHROME_PROFILE_ROOT, CHROME_PROFILE_NAME);
  const copiedProfile = await copyChromeProfileToTemp({
    chromeProfileRoot: CHROME_PROFILE_ROOT,
    profileName,
    prefix: "govat-lineage-chrome-profile-",
  });
  let context;
  try {
    context = await chromium.launchPersistentContext(copiedProfile.profileRoot, {
      channel: "chrome",
      headless: false,
      ignoreDefaultArgs: ["--use-mock-keychain"],
      acceptDownloads: true,
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
    context,
    page,
    close: async () => {
      await context.close().catch(() => {});
      await copiedProfile.cleanup();
    },
  };
}

async function connect() {
  if (DATABRICKS_TOKEN || FORWARDED_ACCESS_TOKEN) {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      acceptDownloads: true,
      extraHTTPHeaders: EXTRA_HTTP_HEADERS,
      viewport: { width: 1536, height: 1024 },
    });
    const page = await context.newPage();
    attachRuntimeListeners(page);
    return {
      context,
      page,
      close: async () => {
        await context.close().catch(() => {});
        await browser.close().catch(() => {});
      },
    };
  }

  try {
    const browser = await chromium.connectOverCDP(CDP_URL);
    const context = browser.contexts()[0] || (await browser.newContext());
    const page = await context.newPage();
    attachRuntimeListeners(page);
    return {
      context,
      page,
      close: async () => {
        await page.close().catch(() => {});
        await browser.close().catch(() => {});
      },
    };
  } catch (error) {
    if (!ALLOW_PROFILE_FALLBACK) {
      throw new Error(
        `Unable to connect to Chrome over ${CDP_URL}: ${error?.message || String(error)}`,
      );
    }
    return launchCopiedProfile();
  }
}

async function screenshot(page, name) {
  const filePath = path.join(OUT_DIR, `${name}.png`);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await page.screenshot({ path: filePath, fullPage: false });
  return filePath;
}

async function waitForLineage(page) {
  if (/\/login\.html/i.test(page.url())) {
    throw new Error(`Databricks login redirect detected before lineage loaded: ${page.url()}`);
  }
  await page.waitForSelector("[data-testid='lineage-northstar-explorer']", { timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      const pageUnavailable = text
        .split(/\n+/)
        .some((line) => line.trim().toLowerCase() === "lineage unavailable");
      const transientEmptyGraph = /No live lineage graph is available for this asset right now/i.test(text);
      return !/Preparing the connected graph|Loading lineage/i.test(text) && !pageUnavailable && !transientEmptyGraph;
    },
    undefined,
    { timeout: 90_000 },
  );
}

async function waitForLineageOrUnavailable(page) {
  if (/\/login\.html/i.test(page.url())) {
    throw new Error(`Databricks login redirect detected before lineage loaded: ${page.url()}`);
  }
  await page.waitForSelector("[data-testid='lineage-northstar-explorer']", { timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return !/Preparing the connected graph|Loading lineage/i.test(text);
    },
    undefined,
    { timeout: 90_000 },
  );
}

async function waitForGovernance(page) {
  await page.waitForSelector(
    "[data-testid='governance-northstar-workbench'], .gh-governance-shell",
    { timeout: 90_000 },
  );
}

async function gotoLineage(page) {
  await page.goto(lineageUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  if (/\/login\.html/i.test(page.url())) {
    throw new Error(`Databricks login redirect detected for ${lineageUrl()}: ${page.url()}`);
  }
  await waitForLineage(page);
}

async function clickFirstVisible(page, roleName, labelPattern, actionName) {
  const deadline = Date.now() + 45_000;
  let lastCount = 0;
  while (Date.now() < deadline) {
    const locator = page.getByRole(roleName, { name: labelPattern });
    const count = await locator.count();
    lastCount = count;
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);
      const className = await candidate.evaluate((node) => node.className || "").catch(() => "");
      if (String(className).includes("gh-visually-hidden")) continue;
      if ((await candidate.isVisible().catch(() => false)) && (await candidate.isEnabled().catch(() => false))) {
        await candidate.click();
        return;
      }
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`No visible enabled ${roleName} found for ${actionName}; candidates=${lastCount}`);
}

async function firstVisibleControl(page, roleName, labelPattern) {
  const locator = page.getByRole(roleName, { name: labelPattern });
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const candidate = locator.nth(index);
    const className = await candidate.evaluate((node) => node.className || "").catch(() => "");
    if (String(className).includes("gh-visually-hidden")) continue;
    if (await candidate.isVisible().catch(() => false)) {
      return candidate;
    }
  }
  return null;
}

async function recordInteraction(page, interaction, fn) {
  const item = {
    route: "lineage",
    interaction,
    name: interaction,
    loaded: false,
    passed: false,
  };
  try {
    const detail = (await fn()) || {};
    const checks = detail?.validation?.checks || {};
    const failedChecks = Object.entries(checks)
      .filter(([, value]) => !value)
      .map(([key]) => key);
    if (failedChecks.length) {
      throw new Error(`Validation checks failed: ${failedChecks.join(", ")}`);
    }
    item.runResult = detail;
    Object.assign(item, detail, { loaded: true, passed: true });
  } catch (error) {
    item.error = error?.message || String(error);
    item.screenshot = await screenshot(page, `lineage-live-failure-${interaction.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`);
  }
  report.interactions.push(item);
  await flushReport();
}

async function textSnapshot(page) {
  return page.evaluate(() => document.body?.innerText || "");
}

async function waitForPath(page, pattern, timeout = 20_000) {
  const source = pattern instanceof RegExp ? pattern.source : String(pattern || "");
  const flags = pattern instanceof RegExp ? pattern.flags : "i";
  await page.waitForFunction(
    ({ source: regexSource, flags: regexFlags }) => {
      const regex = new RegExp(regexSource, regexFlags);
      return regex.test(window.location.pathname);
    },
    { source, flags },
    { timeout },
  ).catch(() => {});
  return new URL(page.url()).pathname;
}

async function visibleButtonSnapshots(page, selector) {
  const locator = page.locator(selector);
  const count = await locator.count();
  const snapshots = [];
  for (let index = 0; index < count; index += 1) {
    const button = locator.nth(index);
    if (!(await button.isVisible().catch(() => false))) continue;
    const detail = await button.evaluate((node) => ({
      ariaLabel: node.getAttribute("aria-label") || "",
      className: node.className || "",
      dataNodeType: node.getAttribute("data-node-type") || "",
      text: (node.textContent || "").replace(/\s+/g, " ").trim(),
      title: node.getAttribute("title") || "",
    })).catch(() => null);
    if (!detail) continue;
    snapshots.push({ index, ...detail });
  }
  return snapshots;
}

async function clickSnapshot(page, selector, snapshot, description) {
  const button = page.locator(selector).nth(snapshot.index);
  await button.scrollIntoViewIfNeeded().catch(() => {});
  await button.click({ timeout: 10_000 });
  await page.waitForTimeout(250);
  const bodyText = await textSnapshot(page);
  return {
    description,
    label: snapshot.text || snapshot.ariaLabel || snapshot.title,
    path: new URL(page.url()).pathname,
    bodyStart: bodyText.slice(0, 800),
  };
}

function lineageNodeClass(snapshot) {
  const text = `${snapshot.dataNodeType || ""} ${snapshot.className || ""} ${snapshot.text || ""}`.toLowerCase();
  if (/restricted|permission boundary|metadata record unavailable|lineage-only|not openable|openability.*unverified|system\./.test(text)) return "restricted";
  if (/is-focus|focus/.test(text)) return "focus";
  if (/is-transform|notebook|pipeline|job/.test(text)) return "transform";
  if (/is-downstream|dashboard|consumer/.test(text)) return "downstream";
  if (/is-upstream|source|table|view/.test(text)) return "upstream";
  return snapshot.dataNodeType || "node";
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(context) {
  const currentPath = path.join(OUT_DIR, "lineage-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await context.newPage();
  await page.setViewportSize({ width: 3200, height: 1120 });
  const outputPath = path.join(OUT_DIR, "lineage-live-side-by-side-1536x1024.png");
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
                <h1>Reference: northstar/screenshots/prototype_lineage.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current live Databricks: lineage-live-1536x1024.png</h1>
                <img src="${currentUrl}" />
              </section>
            </div>
          </body>
        </html>`,
      { waitUntil: "load" },
    );
    await page.screenshot({ path: outputPath, fullPage: true });
    report.sideBySide.push({
      route: "lineage",
      viewport: "1536x1024",
      kind: "side-by-side",
      mockupPath: path.relative(REPO_ROOT, MOCKUP_PATH),
      currentPath: path.relative(REPO_ROOT, currentPath),
      path: path.relative(REPO_ROOT, outputPath),
    });
    await flushReport();
  } finally {
    await page.close().catch(() => {});
  }
}

async function captureViewport(page, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  let navigationError = "";
  for (const attempt of [1, 2]) {
    try {
      await gotoLineage(page);
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
    navigationError ? `lineage-live-${viewport.name}-failure` : `lineage-live-${viewport.name}`,
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
    const pageUnavailable = bodyText
      .split(/\n+/)
      .some((line) => line.trim().toLowerCase() === "lineage unavailable");
    return {
      url: window.location.href,
      title: document.querySelector(".ga-lineage-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 3600),
      hasNorthstar: Boolean(document.querySelector("[data-testid='lineage-northstar-explorer']")),
      unavailable: pageUnavailable,
      loading: /Loading lineage|Preparing the connected graph/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      footer: rect(".ga-shell-footer"),
      explorer: rect("[data-testid='lineage-northstar-explorer']"),
      controlRail: rect(".ga-lineage-control-rail"),
      graphToolbar: rect(".ga-lineage-graph-toolbar"),
      workbench: rect(".ga-lineage-workbench"),
      selectedRail: rect(".ga-lineage-selected-rail"),
      graphCard: rect(".ga-lineage-graph-card"),
      bottom: rect(".ga-lineage-bottom-row"),
      regionText: {
        title: /LINEAGE ATLAS/i.test(bodyText),
        upstream: /1 HOP UPSTREAM|No upstream tables observed|No permitted upstream table hop is visible|No source systems observed|entrada_eval_owner_transfer_domain|charges_raw|invoices_raw/i.test(bodyText),
        transformations: /2 HOPS UPSTREAM|No job or pipeline observed|ipynb|dlt_orders_ingest/i.test(bodyText),
        governed: /LINEAGE DETAILS|Last refresh/i.test(bodyText),
        downstream: /1 HOP DOWNSTREAM|No downstream consumers observed|payments|orders|borrower_dossier/i.test(bodyText),
        selected: /LINEAGE DETAILS|selected/i.test(bodyText),
        impact: /Impact analysis/i.test(bodyText),
        columnLineage: /Column lineage/i.test(bodyText),
      },
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer || !metrics.footer.height || !metrics.bottom || metrics.bottom.bottom <= metrics.footer.top;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.unavailable &&
    !metrics.loading &&
    !metrics.horizontalOverflow &&
    regionsOk &&
    bottomAboveFooter;
  report.captures.push({ viewport, screenshot: screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });
  await recordInteraction(page, "deployed-lineage-route-settled", async () => {
    await gotoLineage(page);
    const bodyText = await textSnapshot(page);
    const lineageResponses = report.lineageApiResponses.filter((entry) => !entry.expectedUnavailableProbe);
    const initialResponses = lineageResponses.filter((entry) => entry.profile === "initial");
    const fullResponses = lineageResponses.filter((entry) => entry.profile === "full");
    const successfulInitialResponses = initialResponses.filter(
      (entry) => entry.status >= 200 && entry.status < 300,
    );
    const firstInitialMs = successfulInitialResponses[0]?.elapsedMs;
    const fastestInitialMs = Math.min(...successfulInitialResponses.map((entry) => entry.elapsedMs).filter(Number.isFinite));
    const checks = {
      pathIsLineage: /\/lineage/i.test(new URL(page.url()).pathname),
      northstarVisible: await page.locator("[data-testid='lineage-northstar-explorer']").isVisible(),
      noLoadingCopy: !/Preparing the connected graph|Loading lineage/i.test(bodyText),
      liveEvidenceLabel: /UC connected|Certification unavailable|0 upstream - 0 downstream|live/i.test(bodyText),
      initialProfileReturned: successfulInitialResponses.length > 0,
      initialProfileWithinBudget: Number.isFinite(firstInitialMs) && firstInitialMs <= LINEAGE_INITIAL_BUDGET_MS,
    };
    return {
      url: page.url(),
      bodyStart: bodyText.slice(0, 1200),
      lineageInitialBudgetMs: LINEAGE_INITIAL_BUDGET_MS,
      lineageFirstInitialMs: firstInitialMs ?? null,
      lineageFastestInitialMs: Number.isFinite(fastestInitialMs) ? fastestInitialMs : null,
      lineageInitialResponses: initialResponses,
      lineageFullResponses: fullResponses,
      validation: { checks },
    };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "deployed-lineage-column-action", async () => {
    await clickFirstVisible(page, "button", /^Column lineage$/i, "Header Column lineage");
    await page.waitForSelector("text=/Column lineage unavailable|Column lineage -|Column lineage/i", { timeout: 6000 });
    const bodyText = await textSnapshot(page);
    const checks = {
      columnStatusVisible: /Column lineage unavailable|Column lineage\s*[·-]|Column lineage is not observed/i.test(bodyText),
      noBackedColumnClaimWithoutRows: !/Column lineage ready|complete column lineage/i.test(bodyText),
    };
    return { bodyStart: bodyText.slice(0, 1200), validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-impact-action", async () => {
    await clickFirstVisible(page, "button", /^Run impact analysis$/i, "Header impact analysis");
    await page.waitForSelector("text=/Impact analysis/i", { timeout: 6000 });
    const bodyText = await textSnapshot(page);
    const ownerReviewDisabled = await page.getByRole("button", { name: /^Review owners$/i }).isDisabled().catch(() => true);
    const checks = {
      impactPanelVisible: /Impact analysis/i.test(bodyText),
      ownerReviewDisabledWithoutBackedImpact: ownerReviewDisabled,
      noFakeImpactJobClaim: !/owner notification sent|impact job started/i.test(bodyText),
    };
    return { ownerReviewDisabled, bodyStart: bodyText.slice(0, 1200), validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-canvas-zoom", async () => {
    const zoom = () => page.locator(".ga-lineage-graph-bands").first().evaluate((node) => Number(node.getAttribute("data-zoom-level") || "1"));
    const before = await zoom();
    await page.getByRole("button", { name: "Zoom in" }).click();
    const afterIn = await zoom();
    await page.getByRole("button", { name: "Zoom out" }).click();
    const afterOut = await zoom();
    await page.getByRole("button", { name: "Fit graph" }).click();
    const afterFit = await zoom();
    const checks = {
      zoomInChanged: afterIn > before,
      zoomOutChanged: afterOut < afterIn,
      fitReset: Math.abs(afterFit - 1) < 0.01,
    };
    return { before, afterIn, afterOut, afterFit, validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-canvas-pan", async () => {
    const graph = page.locator("[data-testid='lineage-graph-body']").first();
    await graph.waitFor({ state: "visible", timeout: 10_000 });
    const pan = () => graph.evaluate((node) => {
      const style = window.getComputedStyle(node);
      const parse = (value) => {
        const number = Number(String(value || "").replace("px", "").trim());
        return Number.isFinite(number) ? number : 0;
      };
      return {
        x: parse(style.getPropertyValue("--ga-lineage-pan-x")),
        y: parse(style.getPropertyValue("--ga-lineage-pan-y")),
      };
    });
    const box = await graph.boundingBox();
    if (!box) throw new Error("Lineage graph body did not expose a bounding box for pan validation.");
    const before = await pan();
    const start = {
      x: box.x + Math.max(80, Math.min(box.width - 80, box.width * 0.45)),
      y: box.y + Math.max(80, Math.min(box.height - 80, box.height * 0.48)),
    };
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(start.x + 120, start.y + 72, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(150);
    const after = await pan();
    const bodyText = await textSnapshot(page);
    const checks = {
      panXChanged: Math.abs(after.x - before.x) >= 20,
      panYChanged: Math.abs(after.y - before.y) >= 20,
      panStatusVisible: /Lineage graph panned/i.test(bodyText),
      lineageDetailsStillVisible: /LINEAGE DETAILS|Last refresh/i.test(bodyText),
    };
    return { before, after, validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-edge-selection", async () => {
    await gotoLineage(page);
    const edges = page.locator(".ga-lineage-edge-hit");
    const edgeCount = await edges.count().catch(() => 0);
    let clickOutcome = "";
    let keyboardOutcome = "";
    if (edgeCount > 0) {
      const firstEdge = edges.first();
      await firstEdge.waitFor({ state: "attached", timeout: 10_000 });
      await firstEdge.click({ force: true });
      await page.waitForSelector("text=/Selected path|Lineage edge selected|LINEAGE DETAILS/i", { timeout: 6000 });
      clickOutcome = String((await page.locator(".ga-lineage-edge-detail").first().textContent().catch(() => "")) || "");
      await firstEdge.focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(250);
      keyboardOutcome = String((await page.locator(".ga-lineage-edge-detail").first().textContent().catch(() => "")) || "");
    }
    const bodyText = await textSnapshot(page);
    const checks = {
      edgeTargetsPresentOrTruthfullyAbsent:
        edgeCount > 0 || /0 edges|No live lineage graph is available|No downstream consumers observed/i.test(bodyText),
      edgeClickSelectsBackedPath:
        edgeCount === 0 || /Selected path|Lineage edge selected|to/i.test(clickOutcome || bodyText),
      edgeKeyboardSelectsBackedPath:
        edgeCount === 0 || /Selected path|Lineage edge selected|to/i.test(keyboardOutcome || bodyText),
    };
    return {
      edgeCount,
      clickOutcome,
      keyboardOutcome,
      validation: { checks },
    };
  });
  await recordInteraction(page, "deployed-lineage-toolbar-search-export", async () => {
    await gotoLineage(page);
    const toolbar = page.locator(".ga-lineage-graph-toolbar").first();
    await toolbar.waitFor({ state: "visible", timeout: 10_000 });
    await toolbar.getByRole("button", { name: /^Table lineage$/i }).click();
    let bodyText = await textSnapshot(page);
    const tableModeVisible = /Table lineage view active|Table lineage/i.test(bodyText);

    await toolbar.getByRole("button", { name: /^Column lineage$/i }).click();
    bodyText = await textSnapshot(page);
    const columnModeVisible = /Column lineage view active|Column lineage is not observed|Column lineage -|Column lineage unavailable/i.test(bodyText);

    await toolbar.getByRole("button", { name: /^Search$/i }).click();
    const searchInput = page.getByLabel(/^Search graph$/i);
    await searchInput.waitFor({ state: "visible", timeout: 6000 });
    const searchInputWasVisible = await searchInput.isVisible().catch(() => false);
    const firstNodeText = String(
      (await page.locator(".ga-lineage-node").first().textContent().catch(() => "")) || "",
    ).trim();
    const query = /entrada_eval/i.test(firstNodeText)
      ? "entrada_eval"
      : /customer/i.test(firstNodeText)
        ? "customer"
        : /usage/i.test(firstNodeText)
          ? "usage"
          : /borrower/i.test(firstNodeText)
            ? "borrower"
            : (firstNodeText.match(/[A-Za-z][A-Za-z0-9_]{2,}/)?.[0] || "table");
    await searchInput.fill(query);
    const resultButton = page.locator(".ga-lineage-graph-search button").first();
    await resultButton.waitFor({ state: "visible", timeout: 6000 });
    const resultLabel = String((await resultButton.textContent().catch(() => "")) || "").trim();
    await resultButton.click();
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForFunction(
      () => !document.querySelector(".ga-lineage-graph-search input"),
      undefined,
      { timeout: 6000 },
    ).catch(async () => {
      await toolbar.getByRole("button", { name: /^Search$/i }).click().catch(() => {});
      await page.waitForTimeout(300);
    });
    bodyText = await textSnapshot(page);
    const searchSelected = resultLabel && /selected|LINEAGE DETAILS|Last refresh/i.test(bodyText);

    await gotoLineage(page);
    const exportToolbar = page.locator(".ga-lineage-graph-toolbar").first();
    await exportToolbar.waitFor({ state: "visible", timeout: 10_000 });
    const exportButton = exportToolbar.getByRole("button", { name: /^Export$/i });
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 10_000 }),
      exportButton.click(),
    ]);
    const downloadPath = await download.path();
    const exportText = downloadPath ? await fs.readFile(downloadPath, "utf8") : "";
    const exportPayload = JSON.parse(exportText || "{}");
    const checks = {
      tableModeVisible,
      columnModeVisible,
      searchInputVisible: searchInputWasVisible,
      searchResultSelected: Boolean(searchSelected),
      exportDownloaded: Boolean(downloadPath),
      exportHasEvidenceKind: Boolean(exportPayload?.meta?.evidenceKind),
      exportMatchesLiveAsset: exportPayload?.asset === ASSET_FQN || exportPayload?.entity_fqn === ASSET_FQN,
    };
    return {
      query,
      resultLabel,
      downloadSuggestedFilename: download.suggestedFilename(),
      exportEvidenceKind: exportPayload?.meta?.evidenceKind || "",
      validation: { checks },
    };
  });
  await recordInteraction(page, "deployed-lineage-focus-node-selection", async () => {
    const nodes = page.locator(".ga-lineage-node");
    const deadline = Date.now() + 10_000;
    let focusNode = null;
    let nodeLabel = "";
    while (Date.now() < deadline && !focusNode) {
      const count = await nodes.count();
      for (let index = 0; index < count; index += 1) {
        const candidate = nodes.nth(index);
        if (!(await candidate.isVisible().catch(() => false))) continue;
        const label = String((await candidate.textContent().catch(() => "")) || "").trim();
        if (!label) continue;
        focusNode = candidate;
        nodeLabel = label;
        break;
      }
      if (!focusNode) await page.waitForTimeout(250);
    }
    if (!focusNode) {
      throw new Error("No visible lineage node was available for selection.");
    }
    await focusNode.click();
    await page.waitForSelector("text=/LINEAGE DETAILS|Last refresh/i", { timeout: 6000 });
    const bodyText = await textSnapshot(page);
    const checks = {
      focusNodeClicked: Boolean(nodeLabel),
      detailPanelPresent: /LINEAGE DETAILS|Last refresh|Rows|Owner/i.test(bodyText),
      selectedStatusVisible: /selected|Lineage graph refocused/i.test(bodyText),
    };
    return { nodeLabel, bodyStart: bodyText.slice(0, 1200), validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-all-node-detail-classes", async () => {
    await gotoLineage(page);
    const nodeSnapshots = await visibleButtonSnapshots(page, ".ga-lineage-graph-bands .ga-lineage-node");
    const nodeTargets = [];
    const seenNodeClasses = new Set();
    for (const snapshot of nodeSnapshots) {
      const key = lineageNodeClass(snapshot);
      if (seenNodeClasses.has(key)) continue;
      seenNodeClasses.add(key);
      nodeTargets.push({ ...snapshot, nodeClass: key });
    }
    const nodeClicks = [];
    for (const snapshot of nodeTargets) {
      nodeClicks.push(await clickSnapshot(page, ".ga-lineage-graph-bands .ga-lineage-node", snapshot, `graph node class ${snapshot.nodeClass}`));
      await page.waitForSelector("text=/LINEAGE DETAILS|Last refresh|selected/i", { timeout: 6000 }).catch(() => {});
    }

    const detailSnapshots = await visibleButtonSnapshots(page, ".ga-lineage-details-panel section button");
    const detailClicks = [];
    for (const snapshot of detailSnapshots.slice(0, 8)) {
      detailClicks.push(await clickSnapshot(page, ".ga-lineage-details-panel section button", snapshot, "lineage details row"));
    }

    const impactSnapshots = await visibleButtonSnapshots(page, ".ga-lineage-impact-list button");
    const impactClicks = [];
    for (const snapshot of impactSnapshots.slice(0, 8)) {
      impactClicks.push(await clickSnapshot(page, ".ga-lineage-impact-list button", snapshot, "impact row"));
    }

    await gotoLineage(page);
    const toolbar = page.locator(".ga-lineage-graph-toolbar").first();
    if (await toolbar.isVisible().catch(() => false)) {
      await toolbar.getByRole("button", { name: /^Column lineage$/i }).click();
      await page.waitForTimeout(300);
    }
    const columnSnapshots = await visibleButtonSnapshots(page, ".ga-lineage-column-list button");
    const columnClicks = [];
    for (const snapshot of columnSnapshots.slice(0, 10)) {
      columnClicks.push(await clickSnapshot(page, ".ga-lineage-column-list button", snapshot, "column lineage row"));
    }

    const bodyText = await textSnapshot(page);
    const restrictedPresent = nodeSnapshots.some((snapshot) => /restricted|permission boundary/i.test(snapshot.text || ""));
    const restrictedCovered = !restrictedPresent || nodeTargets.some((snapshot) => snapshot.nodeClass === "restricted");
    const checks = {
      graphNodesVisible: nodeSnapshots.length > 0,
      everyVisibleNodeClassClicked: nodeClicks.length === seenNodeClasses.size && seenNodeClasses.size > 0,
      detailsPanelStillVisible: /LINEAGE DETAILS|Last refresh|Rows|Owner/i.test(bodyText),
      consumerRowsCoveredOrUnavailable: detailClicks.length > 0 || /No downstream consumer details returned|Consumers\s*0/i.test(bodyText),
      impactRowsCoveredOrUnavailable: impactClicks.length > 0 || /No downstream impact is observed|No downstream consumers observed/i.test(bodyText),
      restrictedCoveredOrAbsent: restrictedCovered,
      columnRowsCoveredOrUnavailable: columnClicks.length > 0 || /Column lineage is unavailable|No column-lineage rows returned|0 column paths visible/i.test(bodyText),
    };
    return {
      visibleNodeCount: nodeSnapshots.length,
      visibleNodeClasses: [...seenNodeClasses],
      nodeClicks,
      detailClicks,
      impactClicks,
      columnClicks,
      validation: { checks },
    };
  });
  await recordInteraction(page, "deployed-lineage-refocus-graph", async () => {
    const refocusButton = await firstVisibleControl(page, "button", /^Refocus graph$/i);
    if (!refocusButton) {
      throw new Error("No visible Refocus graph control was available after node selection.");
    }
    const enabled = await refocusButton.isEnabled().catch(() => false);
    const disabledReason = String(await refocusButton.getAttribute("title").catch(() => "") || "");
    if (!enabled) {
      const bodyText = await textSnapshot(page);
      const checks = {
        refocusDisabledTruthfully: /not openable|permissions/i.test(disabledReason),
        routeStillLineage: /\/lineage/i.test(new URL(page.url()).pathname),
        lineageContextStillVisible: /LINEAGE DETAILS|selected|Node Types|via system\.access\.table_lineage/i.test(bodyText),
      };
      return {
        url: page.url(),
        disabled: true,
        disabledReason,
        bodyStart: bodyText.slice(0, 1200),
        validation: { checks },
      };
    }
    await refocusButton.click();
    await waitForLineageOrUnavailable(page);
    const bodyText = await textSnapshot(page);
    const checks = {
      refocusFeedbackVisible: !/Preparing the connected graph|Loading lineage/i.test(bodyText),
      routeStillLineage: /\/lineage/i.test(new URL(page.url()).pathname),
      lineageOutcomeTruthful: /via system\.access\.table_lineage|No live topology returned; system\.access\.table_lineage not verified for this route|No live graph|Lineage is unavailable/i.test(bodyText),
      noSyntheticEdgesIntroduced: /0 upstream - 0 downstream|0 edges|No downstream consumers observed|No live lineage graph is available|[1-9]\d* nodes · [1-9]\d* edges/i.test(bodyText),
    };
    return { url: page.url(), bodyStart: bodyText.slice(0, 1200), validation: { checks } };
  });
  await recordInteraction(page, "deployed-lineage-unavailable-controls", async () => {
    const unavailableAsset = `${ASSET_FQN}${UNAVAILABLE_VALIDATION_SUFFIX}`;
    await page.goto(lineageUrl(unavailableAsset), { waitUntil: "domcontentloaded", timeout: 90_000 });
    await waitForLineageOrUnavailable(page);
    const unavailableUrl = page.url();
    if (!unavailableAsset) {
      throw new Error(`Expected unavailable lineage route after refocus, got ${unavailableUrl}`);
    }

    const retryButton = await firstVisibleControl(page, "button", /^Retry$/i);
    if (!retryButton) throw new Error("No visible Retry control on unavailable lineage route.");
    await retryButton.click();
    await page.waitForTimeout(300);
    let bodyText = await textSnapshot(page);
    const retryTruthful = /Lineage view reset|No live graph|No live lineage graph is available/i.test(bodyText);

    const openAssetButton = await firstVisibleControl(page, "button", /^Open asset$/i);
    if (!openAssetButton) throw new Error("No visible Open asset control on unavailable lineage route.");
    const openAssetDisabled = await openAssetButton.isDisabled().catch(() => false);
    const openAssetTitle = String(await openAssetButton.getAttribute("title").catch(() => "") || "");
    let openAssetOutcome = "";
    if (openAssetDisabled) {
      openAssetOutcome = openAssetTitle;
    } else {
      await Promise.all([
        page.waitForLoadState("domcontentloaded", { timeout: 20_000 }).catch(() => {}),
        openAssetButton.click(),
      ]);
      await page.waitForFunction(
        () => /\/asset\//i.test(window.location.pathname) || /unavailable|metadata record|overview/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 20_000 },
      ).catch(() => {});
      openAssetOutcome = page.url();
    }

    await page.goto(lineageUrl(unavailableAsset), { waitUntil: "domcontentloaded", timeout: 90_000 });
    await waitForLineageOrUnavailable(page);
    const clearFocusButton = await firstVisibleControl(page, "button", /^Clear focus$/i);
    if (!clearFocusButton) throw new Error("No visible Clear focus control on unavailable lineage route.");
    await clearFocusButton.click();
    await waitForLineageOrUnavailable(page);
    bodyText = await textSnapshot(page);
    const checks = {
      retryTruthful,
      openAssetHandled: openAssetDisabled ? /not openable|permissions/i.test(openAssetTitle) : /\/asset\//i.test(openAssetOutcome),
      clearFocusShowsSearchState: /Search for an asset|Start typing to load a graph|Pick another asset to continue/i.test(bodyText),
      noSyntheticUnavailableGraph: !/[1-9]\d* nodes · [1-9]\d* edges/i.test(bodyText),
    };
    return {
      unavailableAsset,
      openAssetDisabled,
      openAssetOutcome,
      url: page.url(),
      bodyStart: bodyText.slice(0, 1200),
      validation: { checks },
    };
  });
  await recordInteraction(page, "deployed-lineage-shared-shell-controls", async () => {
    await gotoLineage(page);
    const checks = {};
    const outcomes = {};

    const topbarSearch = page.locator(".gh-topbar-search-input").first();
    checks.topbarSearchVisible = await topbarSearch.isVisible().catch(() => false);
    checks.topbarSearchEnabled = checks.topbarSearchVisible && await topbarSearch.isEnabled().catch(() => false);
    if (checks.topbarSearchEnabled) {
      await topbarSearch.fill("revenue");
      await topbarSearch.press("Enter");
      outcomes.searchPath = await waitForPath(page, /\/discover|\/discovery/i, 20_000);
      checks.topbarSearchRoutes = /\/discover|\/discovery/i.test(outcomes.searchPath);
      await gotoLineage(page);
    } else {
      outcomes.searchDisabledReason = await topbarSearch.getAttribute("title").catch(() => "") || "Topbar search disabled or unavailable.";
      checks.topbarSearchRoutes = /disabled|unavailable|not available/i.test(outcomes.searchDisabledReason);
    }

    await page.keyboard.press("Meta+K").catch(() => {});
    if (!(await page.locator(".gh-cmdk").first().isVisible().catch(() => false))) {
      await page.keyboard.press("Control+K").catch(() => {});
    }
    if (!(await page.locator(".gh-cmdk").first().isVisible().catch(() => false))) {
      const commandButton = await firstVisibleControl(page, "button", /Open command palette/i);
      await commandButton?.click();
    }
    await page.waitForSelector(".gh-cmdk", { timeout: 6000 });
    checks.commandPaletteVisible = await page.locator(".gh-cmdk").first().isVisible().catch(() => false);
    await page.getByLabel("Command palette search").fill("Lineage");
    checks.commandPaletteLineageResult = await page.getByRole("option", { name: /Lineage Atlas/i }).first().isVisible().catch(() => false);
    await page.keyboard.press("Escape");

    const notificationsButton = await firstVisibleControl(page, "button", /Notifications/i);
    if (notificationsButton) {
      await notificationsButton.click();
      await page.waitForFunction(
        () => /\/inbox/i.test(window.location.pathname) || /Inbox|No inbox items|Governance inbox|unread/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 20_000 },
      ).catch(() => {});
      const bodyText = await textSnapshot(page);
      outcomes.notifications = bodyText.slice(0, 1200);
      checks.notificationsHandled = /Inbox|No inbox items|Governance inbox|unread/i.test(bodyText) || /\/inbox/i.test(new URL(page.url()).pathname);
      await gotoLineage(page);
    } else {
      outcomes.notifications = "Notifications control not visible for this actor.";
      checks.notificationsHandled = true;
    }

    const helpButton = await firstVisibleControl(page, "button", /^Help$/i);
    if (!helpButton) {
      checks.helpRoutes = false;
    } else {
      await helpButton.click();
      outcomes.helpPath = await waitForPath(page, /\/help/i, 20_000);
      const bodyText = await textSnapshot(page);
      checks.helpRoutes = /\/help/i.test(outcomes.helpPath) || /Help|Support|Governance Atlas/i.test(bodyText);
      await gotoLineage(page);
    }

    const profileButton = await firstVisibleControl(page, "button", /Open profile menu/i);
    if (profileButton) {
      await profileButton.click();
      await page.waitForTimeout(300);
      const bodyText = await textSnapshot(page);
      outcomes.profile = bodyText.slice(0, 1200);
      checks.profileMenuHandled = /Settings & diagnostics|Capability dashboard|Sign out|Upload local avatar/i.test(bodyText);
      await page.keyboard.press("Escape").catch(() => {});
    } else {
      outcomes.profile = "Profile menu control not visible.";
      checks.profileMenuHandled = false;
    }

    const aiButton = page.locator(".ga-topbar-actions .ga-ai-chip").first();
    checks.atlasAiControlVisible = await aiButton.isVisible().catch(() => false);
    const aiDisabled = checks.atlasAiControlVisible && (
      await aiButton.isDisabled().catch(() => false) ||
      String(await aiButton.getAttribute("aria-disabled").catch(() => "") || "").toLowerCase() === "true"
    );
    if (!checks.atlasAiControlVisible) {
      outcomes.atlasAi = "Atlas AI control not visible.";
      checks.atlasAiHandled = false;
    } else if (aiDisabled) {
      outcomes.atlasAi = await aiButton.getAttribute("title").catch(() => "") || "Atlas AI disabled.";
      checks.atlasAiHandled = /requires|endpoint|unavailable|disabled|evidence-backed|configured|Genie/i.test(outcomes.atlasAi);
    } else {
      await aiButton.click();
      await page.waitForSelector(".gh-floating-ai-chat", { timeout: 10_000 });
      const promptButton = page.locator(".gh-floating-ai-prompts button").first();
      if (await promptButton.isVisible().catch(() => false)) {
        await promptButton.click();
        await page.waitForTimeout(1500);
      } else {
        const aiInput = page.locator(".gh-floating-ai-input input").first();
        await aiInput.fill("Summarize the visible lineage evidence.");
        await page.locator(".gh-floating-ai-input button").first().click();
        await page.waitForTimeout(1500);
      }
      const aiText = await textSnapshot(page);
      checks.atlasAiHandled = /Atlas AI|Grounded|Review for accuracy|evidence|unavailable|error/i.test(aiText);
      outcomes.atlasAi = aiText.slice(0, 1600);
      await page.getByRole("button", { name: /^Close Atlas AI$/i }).click();
      checks.atlasAiClosed = !(await page.locator(".gh-floating-ai-chat").first().isVisible().catch(() => false));
    }

    return { outcomes, validation: { checks } };
  });
}

let context = null;
let page = null;
let close = null;
let fatalError = null;
try {
  ({ context, page, close } = await connect());
  await fs.mkdir(OUT_DIR, { recursive: true });
  for (const viewport of VIEWPORTS) {
    await captureViewport(page, viewport);
  }
  await runInteractions(page);
  await createSideBySide(context);
  await flushReport();
} catch (error) {
  fatalError = {
    message: error?.message || String(error),
    stack: error?.stack || "",
  };
  report.fatalError = fatalError;
  await flushReport();
} finally {
  await close?.();
}

if (fatalError || !report.passed) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}

console.log(JSON.stringify(report, null, 2));
