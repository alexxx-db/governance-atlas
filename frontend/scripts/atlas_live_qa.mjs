import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";
import { copyChromeProfileToTemp, resolveChromeProfileName } from "./chrome_profile_tmp.mjs";

const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const CDP_URL = process.env.GOVAT_CDP_URL || "http://127.0.0.1:9223";
const ALLOW_CHROME_PROFILE_FALLBACK =
  (process.env.GOVAT_ALLOW_CHROME_PROFILE_FALLBACK) === "1";
const MAX_VISIBLE_ASSET_CANDIDATES = Number.parseInt(
  process.env.GOVAT_MAX_VISIBLE_ASSET_CANDIDATES || "6",
  10,
);
const MAX_WRITABLE_ASSET_CANDIDATES = Number.parseInt(
  process.env.GOVAT_MAX_WRITABLE_ASSET_CANDIDATES || "18",
  10,
);
const WRITABLE_ASSET_FQN = "dev.wacs_silver_test.slv_work_req_latest_status";
const WRITABLE_COLUMN_NAME = "work_req_id";
const OUT_DIR = process.env.GOVAT_LIVE_QA_OUT_DIR || "/tmp/govat-live-qa";
const CHROME_PROFILE_ROOT =
  process.env.GOVAT_CHROME_PROFILE_ROOT ||
  path.join(process.env.HOME || "", "Library", "Application Support", "Google", "Chrome");
const RESPONSIVE_VIEWPORTS = [
  { name: "desktop-wide", width: 1600, height: 1040 },
  { name: "laptop", width: 1280, height: 960 },
  { name: "tablet", width: 920, height: 1180 },
  { name: "mobile", width: 720, height: 1280 },
];
const suffix = `${Date.now()}`.slice(-8);
const approveRequestTitle = `Codex QA approve request ${suffix}`;
const approveRequestNote = `Codex QA approve request note ${suffix}`;
const rejectRequestTitle = `Codex QA reject request ${suffix}`;
const rejectRequestNote = `Codex QA reject request note ${suffix}`;
const glossaryName = `Codex QA Term ${suffix}`;
const glossaryDefinition = `Codex QA definition ${suffix}`;
const glossaryDefinitionUpdated = `Codex QA definition updated ${suffix}`;
// A real workspace member the QA run may assign as glossary owner/reviewer.
const glossaryOwner =
  process.env.GOVAT_QA_USER_EMAIL ||
  (() => { throw new Error("Set GOVAT_QA_USER_EMAIL to a workspace member email for glossary QA"); })();
const glossaryReviewerInitial = `${glossaryOwner}:reviewer`;
const glossaryReviewerUpdated = `${glossaryOwner}:approver`;

const report = {
  generatedAt: new Date().toISOString(),
  assetFqn: "",
  lineageAssetFqn: "",
  columnName: "",
  writableAssetFqn: WRITABLE_ASSET_FQN,
  writableColumnName: WRITABLE_COLUMN_NAME,
  approveRequestTitle,
  rejectRequestTitle,
  glossaryName,
  screenshots: [],
  checks: [],
  pageErrors: [],
  consoleErrors: [],
};

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, "report.json"), JSON.stringify(report, null, 2));
}

function pushCheck(name, status, detail = {}) {
  report.checks.push({ name, status, ...detail });
  void flushReport();
}

async function connect() {
  try {
    const browser = await chromium.connectOverCDP(CDP_URL);
    const context = browser.contexts()[0];
    const existingPages = context.pages();
    const page =
      existingPages.find((candidate) => candidate.url().startsWith(BASE_URL)) ||
      existingPages.find((candidate) => /^https?:/i.test(candidate.url())) ||
      existingPages[0] ||
      (await context.newPage());
    await page.bringToFront();
    await page.setViewportSize({ width: 1600, height: 1040 });
    attachRuntimeListeners(page);
    return { browser, context, page, close: null, mode: "cdp" };
  } catch (error) {
    if (!ALLOW_CHROME_PROFILE_FALLBACK) {
      pushCheck("browser-connect", "error", {
        cdpUrl: CDP_URL,
        message:
          error?.message ||
          "Failed to attach to authenticated Chrome. Start Chrome with --remote-debugging-port=9223 first.",
      });
      await flushReport();
      throw new Error(
        "CDP connection unavailable and copied-profile fallback is disabled. "
          + "Start an authenticated Chrome session with --remote-debugging-port=9223 "
          + "or set GOVAT_ALLOW_CHROME_PROFILE_FALLBACK=1."
      );
    }
    pushCheck("browser-connect-fallback", "warn", {
      message: `CDP connection unavailable. Launching a copied Chrome profile instead.`,
      detail: error?.message || String(error),
    });
    return launchCopiedChromeContext();
  }
}

function attachRuntimeListeners(page) {
  page.on("pageerror", (error) => {
    const url = page.url();
    const appOrigin = url.startsWith(APP_ORIGIN);
    report.pageErrors.push({
      message: error?.message || String(error),
      stack: error?.stack || "",
      url,
      appOrigin,
    });
    void flushReport();
  });
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    const url = page.url();
    const appOrigin = url.startsWith(APP_ORIGIN);
    report.consoleErrors.push({
      type: message.type(),
      text: message.text(),
      url,
      appOrigin,
    });
    void flushReport();
  });
}

async function launchCopiedChromeContext() {
  const profileName = await resolveChromeProfileName(CHROME_PROFILE_ROOT);
  const copiedProfile = await copyChromeProfileToTemp({
    chromeProfileRoot: CHROME_PROFILE_ROOT,
    profileName,
    prefix: "govat-live-qa-chrome-profile-",
  });
  let context;
  try {
    context = await chromium.launchPersistentContext(copiedProfile.profileRoot, {
      channel: "chrome",
      headless: false,
      viewport: { width: 1600, height: 1040 },
      args: [`--profile-directory=${profileName}`],
    });
  } catch (error) {
    await copiedProfile.cleanup();
    throw error;
  }
  const existingPages = context.pages();
  const page =
    existingPages.find((candidate) => candidate.url().startsWith(BASE_URL)) ||
    existingPages.find((candidate) => /^https?:/i.test(candidate.url())) ||
    existingPages[0] ||
    (await context.newPage());
  await page.bringToFront();
  attachRuntimeListeners(page);
  return {
    browser: context.browser(),
    context,
    page,
    mode: "persistent",
    close: async () => {
      await context.close().catch(() => {});
      await copiedProfile.cleanup();
    },
  };
}

function sameAppOrigin(url) {
  try {
    return new URL(url).origin === APP_ORIGIN;
  } catch {
    return false;
  }
}

async function assertAppOrigin(page, name) {
  if (sameAppOrigin(page.url())) return;
  const detail = await page.evaluate(() => ({
    url: window.location.href,
    title: document.title,
    readyState: document.readyState,
    bodyPreview: (document.body?.innerText || "").slice(0, 1400),
  }));
  pushCheck(name, "error", {
    reason: "auth-required",
    expectedOrigin: APP_ORIGIN,
    landedUrl: page.url(),
    detail,
  });
  await screenshot(page, `${name}-auth-required`);
  throw new Error(`Navigation left the app origin during ${name}: ${page.url()}`);
}

async function gotoSurface(page, url, selector, waitMs = 1200) {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  await assertAppOrigin(page, "surface-navigation");
  try {
    await page.waitForSelector(selector, { timeout: 90000 });
  } catch (error) {
    let debug = {};
    try {
      debug = await page.evaluate((targetSelector) => {
        const target = document.querySelector(targetSelector);
        const rect = target?.getBoundingClientRect?.();
        return {
          url: window.location.href,
          title: document.title,
          readyState: document.readyState,
          bodyPreview: (document.body?.innerText || "").slice(0, 1400),
          selectors: {
            shellHeader: Boolean(document.querySelector(".gh-shell-header")),
            discoveryGrid: Boolean(document.querySelector(".gh-discovery-main-grid")),
            entityTabs: Boolean(document.querySelector(".gh-entity-record-tabs")),
            lineageShell: Boolean(document.querySelector(".gh-lineage-stage-shell")),
            governanceWorkbench: Boolean(document.querySelector(".gh-governance-workbench")),
            progress: Boolean(document.querySelector(".gh-shell-progress")),
            unavailable: Boolean(document.querySelector(".gh-unavailable-panel")),
          },
          targetState: target
            ? {
                display: getComputedStyle(target).display,
                visibility: getComputedStyle(target).visibility,
                width: rect?.width || 0,
                height: rect?.height || 0,
              }
            : null,
        };
      }, selector);
      await screenshot(page, `surface-timeout-${Date.now()}`);
    } catch {
      // Best-effort only.
    }
    throw new Error(
      `${error?.message || error}\nSurface debug: ${JSON.stringify(debug)}`
    );
  }
  await page.waitForTimeout(waitMs);
}

async function resetDiscoverySession(page) {
  await page.goto(`${BASE_URL}/?module=discovery&surface=discovery&_cb=codex-qa-reset-${suffix}`, {
    waitUntil: "domcontentloaded",
  });
  await page.evaluate(() => {
    try {
      window.sessionStorage.clear();
    } catch {
      // Best-effort only.
    }
  });
}

async function screenshot(page, name, fullPage = false) {
  const filePath = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: filePath, fullPage });
  report.screenshots.push(filePath);
  await flushReport();
}

function currentRoute(page) {
  const parsed = new URL(page.url());
  const params = parsed.searchParams;
  return {
    url: parsed.href,
    module: params.get("module") || "",
    surface: params.get("surface") || "",
    asset: params.get("asset") || "",
    q: params.get("q") || "",
  };
}

async function collectDiscoveryCards(page, limit = 6) {
  return page.evaluate(
    ({ maxCards }) =>
      [...document.querySelectorAll(".gh-discovery-result-row")]
        .slice(0, maxCards)
        .map((row) => ({
          title: row.querySelector(".gh-discovery-result-title")?.textContent?.trim() || "",
          fqn: row.querySelector(".gh-discovery-result-fqn")?.textContent?.trim() || "",
          buttonLabels: [...row.querySelectorAll("button")].map((button) => button.textContent.trim()),
        })),
    { maxCards: limit },
  );
}

async function finalizeRuntimeChecks() {
  const pageErrors = report.pageErrors.filter((entry) => entry.appOrigin !== false);
  const consoleMessages = report.consoleErrors.filter((entry) => entry.appOrigin !== false);
  const pageErrorCount = pageErrors.length;
  const consoleWarningCount = consoleMessages.filter((entry) => entry.type === "warning").length;
  const consoleErrorCount = consoleMessages.filter((entry) => entry.type === "error").length;

  pushCheck("page-errors", pageErrorCount ? "error" : "ok", {
    count: pageErrorCount,
    messages: pageErrors.slice(0, 5),
  });
  pushCheck("console-errors", consoleErrorCount ? "error" : consoleWarningCount ? "warn" : "ok", {
    warningCount: consoleWarningCount,
    errorCount: consoleErrorCount,
    messages: consoleMessages.slice(0, 10),
  });

  if (pageErrorCount || consoleErrorCount) {
    process.exitCode = 1;
  }
}

async function captureResponsiveSnapshot(page, name, url, selector, viewportSize, detailSelector = selector) {
  await page.setViewportSize(viewportSize);
  await gotoSurface(page, url, selector, 900);
  const snapshot = await page.evaluate(
    ({ targetSelector }) => {
      const target = document.querySelector(targetSelector);
      const targetRect = target?.getBoundingClientRect?.() || null;
      const layoutSelectors = [
        ".gh-discovery-main-grid",
        ".gh-entity-record-layout",
        ".gh-entity-record-layout-governance",
        ".gh-governance-workbench",
        ".gh-governance-glossary-workbench",
        ".gh-lineage-stage-shell",
      ];
      return {
        url: window.location.href,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        bodyScrollWidth: document.documentElement?.scrollWidth || 0,
        bodyScrollHeight: document.documentElement?.scrollHeight || 0,
        horizontalOverflow: (document.documentElement?.scrollWidth || 0) > window.innerWidth + 4,
        targetVisible: Boolean(target) && Boolean(targetRect) && targetRect.width > 0 && targetRect.height > 0,
        targetDisplay: target ? getComputedStyle(target).display : "",
        targetGridTemplateColumns: target ? getComputedStyle(target).gridTemplateColumns : "",
        discoveryGridColumns: document.querySelector(".gh-discovery-main-grid")
          ? getComputedStyle(document.querySelector(".gh-discovery-main-grid")).gridTemplateColumns
          : "",
        entityLayoutColumns: document.querySelector(".gh-entity-record-layout")
          ? getComputedStyle(document.querySelector(".gh-entity-record-layout")).gridTemplateColumns
          : "",
        governanceLayoutColumns: document.querySelector(".gh-governance-workbench")
          ? getComputedStyle(document.querySelector(".gh-governance-workbench")).gridTemplateColumns
          : "",
        lineageStageColumns: document.querySelector(".gh-lineage-stage-shell")
          ? getComputedStyle(document.querySelector(".gh-lineage-stage-shell")).gridTemplateColumns
          : "",
        visibleLayoutSelectors: layoutSelectors.filter((layoutSelector) => Boolean(document.querySelector(layoutSelector))),
      };
    },
    { targetSelector: detailSelector },
  );
  pushCheck(name, snapshot.targetVisible && !snapshot.horizontalOverflow ? "ok" : "warn", snapshot);
}

async function createGovernanceRequest(page, requestTitle, requestNote) {
  const requestBlock = page.locator(".gh-form-block").filter({ hasText: "Create request" }).first();
  await requestBlock.locator('input[placeholder="Request title"]').fill(requestTitle);
  await requestBlock.locator('textarea[placeholder="Optional note"]').fill(requestNote);
  await requestBlock.getByRole("button", { name: "Create request" }).click();
  await page
    .waitForFunction(
      (title) => {
        const text = document.body?.innerText || "";
        return text.includes(title) || text.includes("Governance request created.");
      },
      requestTitle,
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1000);
  const summary = await fetchJson(page, `/api/governance/summary?_qa=${Date.now()}`);
  const requestMatch =
    (summary.json?.backlog || []).find((item) => item.title === requestTitle) || null;
  return {
    summary,
    requestMatch,
    requestId: requestMatch?.requestId || "",
    bodyPreview: (await page.evaluate(() => document.body?.innerText || "")).slice(0, 1800),
  };
}

async function actOnGovernanceRequest(page, { requestTitle, requestId, buttonName, successText }) {
  const selectedWorkSection = page.locator(".gh-detail-section").filter({ hasText: "Selected work" }).first();
  const requestRow = page.locator(".gh-request-row").filter({ hasText: requestTitle }).first();
  const selectedActionButton = selectedWorkSection.getByRole("button", { name: buttonName }).first();

  if (await selectedActionButton.count()) {
    await selectedActionButton.click();
  } else if (await requestRow.count()) {
    await requestRow.click();
    await page.waitForTimeout(800);
    await page.getByRole("button", { name: buttonName }).click();
  } else {
    return {
      acted: false,
      requestStillOpen: true,
      reason: "Neither the selected-work action nor the request row was visible.",
      summary: null,
    };
  }

  await page
    .waitForFunction(
      (message) => {
        const text = document.body?.innerText || "";
        return text.includes(message) || text.includes(message.replace(".", ""));
      },
      successText,
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1000);
  const summary = await fetchJson(page, `/api/governance/summary?_qa=${Date.now()}`);
  const requestStillOpen = (summary.json?.backlog || []).some(
    (item) => item.requestId === requestId || item.title === requestTitle,
  );
  return {
    acted: true,
    requestStillOpen,
    summary,
    selectedWorkVisible: Boolean(await selectedWorkSection.count()),
    requestRowVisible: Boolean(await requestRow.count()),
  };
}

async function waitForOverviewWarmup(page, timeoutMs = 12000) {
  try {
    await page.waitForFunction(
      () => {
        const cards = [...document.querySelectorAll(".gh-record-card")];
        const liveSignalCard = cards.find((card) => card.innerText.includes("Live Record Signals"));
        const lineageCard = cards.find((card) => card.innerText.includes("Lineage Context"));
        if (!liveSignalCard || !lineageCard) return false;
        const liveText = liveSignalCard.innerText;
        const lineageText = lineageCard.innerText;
        return (
          !liveText.includes("Loading…") &&
          !liveText.includes("Loading connected lineage") &&
          !liveText.includes("Workloads\n—") &&
          !lineageText.includes("Loading connected lineage") &&
          !lineageText.includes("Loading connected")
        );
      },
      { timeout: timeoutMs },
    );
    return true;
  } catch {
    return false;
  }
}

async function fetchJson(page, url, init = {}, timeoutMs = 15000) {
  return page.evaluate(
    async ({ url: targetUrl, init: targetInit, timeoutMs: targetTimeoutMs }) => {
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort("Timed out"), targetTimeoutMs);
      try {
        const response = await fetch(targetUrl, {
          ...targetInit,
          signal: controller.signal,
        });
        const text = await response.text();
        let json = null;
        try {
          json = JSON.parse(text);
        } catch {
          json = null;
        }
        return {
          ok: response.ok,
          status: response.status,
          text,
          json,
        };
      } catch (error) {
        return {
          ok: false,
          status: 0,
          text: String(error?.message || error || "Request failed"),
          json: null,
        };
      } finally {
        window.clearTimeout(timeoutId);
      }
    },
    { url, init, timeoutMs },
  );
}

function assetApiPath(assetFqn, query = "") {
  const encoded = encodeURIComponent(assetFqn || "");
  return `/api/assets/${encoded}${query}`;
}

function lineageApiPath(assetFqn, query = "") {
  const encoded = encodeURIComponent(assetFqn || "");
  return `/api/lineage/${encoded}${query}`;
}

async function resolveVisibleAssetTargets(page) {
  const visibleAssetFqn = process.env.GOVAT_VISIBLE_ASSET_FQN;
  if (visibleAssetFqn) {
    return {
      assetFqn: visibleAssetFqn,
      columnName: process.env.GOVAT_VISIBLE_COLUMN_NAME || "",
      lineageAssetFqn:
        process.env.GOVAT_LINEAGE_ASSET_FQN ||
        process.env.GOVAT_LINEAGE_ASSET_FQN ||
        visibleAssetFqn,
    };
  }
  const candidateFqns = await page.evaluate(() => {
    const selected = document.querySelector(".gh-selection-preview[data-asset-fqn]")?.dataset?.assetFqn || "";
    const resultRows = [...document.querySelectorAll(".gh-discovery-result-row[data-asset-fqn]")]
      .map((row) => row.dataset.assetFqn || "")
      .filter(Boolean);
    const bootstrapAssets = ((window.__GOVAT_BOOTSTRAP__)?.assets || [])
      .map((asset) => asset?.fqn || "")
      .filter(Boolean);
    return [...new Set([selected, ...resultRows, ...bootstrapAssets])].filter(Boolean);
  });

  if (!candidateFqns.length) {
    return { assetFqn: "", columnName: "", lineageAssetFqn: "" };
  }

  let assetFqn = candidateFqns[0] || "";
  let columnName = "";
  for (const candidate of candidateFqns.slice(0, Math.max(1, MAX_VISIBLE_ASSET_CANDIDATES))) {
    const assetDetail = await fetchJson(page, `${assetApiPath(candidate, `?sections=schema&_qa=${Date.now()}`)}`);
    const nextColumnName = assetDetail.json?.columns?.[0]?.name || "";
    if (nextColumnName) {
      assetFqn = candidate;
      columnName = nextColumnName;
      break;
    }
  }

  let lineageAssetFqn = assetFqn;
  for (const candidate of candidateFqns.slice(0, Math.max(1, MAX_VISIBLE_ASSET_CANDIDATES))) {
    const lineagePayload = await fetchJson(page, `${lineageApiPath(candidate, `?_qa=${Date.now()}`)}`);
    const dataEdges = lineagePayload.json?.graphs?.data?.edges?.length || 0;
    const opEdges = lineagePayload.json?.graphs?.operational?.edges?.length || 0;
    if (dataEdges || opEdges) {
      lineageAssetFqn = candidate;
      break;
    }
  }

  return {
    assetFqn,
    columnName,
    lineageAssetFqn,
  };
}

async function resolveWritableAssetTarget(page) {
  const writableAssetFqn = process.env.GOVAT_WRITABLE_ASSET_FQN;
  if (writableAssetFqn) {
    return {
      assetFqn: writableAssetFqn,
      columnName: process.env.GOVAT_WRITABLE_COLUMN_NAME || "",
    };
  }
  const seededCandidates = await page.evaluate(() => {
    const resultRows = [...document.querySelectorAll(".gh-discovery-result-row[data-asset-fqn]")]
      .map((row) => row.dataset.assetFqn || "")
      .filter(Boolean);
    const bootstrapAssets = ((window.__GOVAT_BOOTSTRAP__)?.assets || [])
      .map((asset) => asset?.fqn || "")
      .filter(Boolean);
    return [...new Set([...resultRows, ...bootstrapAssets])].filter(Boolean);
  });
  const deltaSearch = await fetchJson(
    page,
    `/api/discovery/search?types=${encodeURIComponent("Delta Table")}&limit=${Math.max(6, MAX_WRITABLE_ASSET_CANDIDATES)}&_qa=${Date.now()}`,
  );
  const apiCandidates = (deltaSearch.json?.assets || [])
    .map((asset) => asset?.fqn || "")
    .filter(Boolean);
  const candidateFqns = [...new Set([...seededCandidates, ...apiCandidates])];

  for (const candidate of candidateFqns.slice(0, Math.max(1, MAX_WRITABLE_ASSET_CANDIDATES))) {
    const detail = await fetchJson(
      page,
      assetApiPath(candidate, `?sections=header,schema&_qa=${Date.now()}`),
    );
    const writable = detail.json?.metadataEditor?.available === true;
    const columnName = detail.json?.columns?.[0]?.name || "";
    if (writable && columnName) {
      return { assetFqn: candidate, columnName };
    }
  }

  return { assetFqn: "", columnName: "" };
}

function rowMap(rows = []) {
  return Object.fromEntries(
    rows
      .map((row) => {
        const [label, ...rest] = String(row || "")
          .split("\n")
          .map((part) => part.trim())
          .filter(Boolean);
        return label ? [label, rest.join(" ")] : null;
      })
      .filter(Boolean),
  );
}

await fs.mkdir(OUT_DIR, { recursive: true });
await flushReport();

const runtime = await connect();
const { page } = runtime;

let originalWritableColumnDraft = { description: "", tags: "" };
let createdApproveRequestId = "";
let createdRejectRequestId = "";
let createdGlossaryTermId = "";
let visibleAssetFqn = "";
let visibleLineageAssetFqn = "";
let visibleColumnName = "";
let writableAssetFqn = WRITABLE_ASSET_FQN;
let writableColumnName = WRITABLE_COLUMN_NAME;
let discoveryRouteCandidate = null;

try {
  await resetDiscoverySession(page);
  await gotoSurface(
    page,
    `${BASE_URL}/?module=discovery&surface=discovery&_cb=codex-qa-${suffix}`,
    ".gh-discovery-main-grid",
  );
  await screenshot(page, "discovery-home");

  const discoverySummary = await page.evaluate(() => {
    const categoryRows = [...document.querySelectorAll(".gh-category-row")].map((row) => {
      const [label, count] = row.innerText
        .split("\n")
        .map((part) => part.trim())
        .filter(Boolean);
      return [label, Number(String(count || "").replace(/[^\d]/g, ""))];
    });
    const selectedButtons = [...document.querySelectorAll(".gh-selection-preview-actions button")].map((button) => {
      const rect = button.getBoundingClientRect();
      return {
        text: button.textContent.trim(),
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
      };
    });
    const moduleLabel = document.querySelector(".gh-shell-module-label");
    const userEmail = document.querySelector(".gh-shell-user");
    const brand = document.querySelector(".gh-shell-brand-mark");
    const catalogChip = document.querySelector(".gh-discovery-sidebar .gh-chip-stack button");
    const connectedAssets = [...document.querySelectorAll(".gh-selection-preview .gh-lineage-linked-row")].map((row) =>
      row.innerText.trim(),
    );
    return {
      counts: Object.fromEntries(categoryRows),
      selectedButtons,
      sameButtonRow: new Set(selectedButtons.map((button) => Math.round(button.y))).size === 1,
      moduleLabelFont: moduleLabel ? parseFloat(getComputedStyle(moduleLabel).fontSize) : 0,
      userFont: userEmail ? parseFloat(getComputedStyle(userEmail).fontSize) : 0,
      brandSize: brand
        ? {
            width: brand.getBoundingClientRect().width,
            height: brand.getBoundingClientRect().height,
          }
        : null,
      catalogCursor: catalogChip ? getComputedStyle(catalogChip).cursor : "",
      connectedAssets,
    };
  });
  pushCheck("discovery-shell", "ok", discoverySummary);

  const resolvedTargets = await resolveVisibleAssetTargets(page);
  visibleAssetFqn = resolvedTargets.assetFqn;
  visibleLineageAssetFqn = resolvedTargets.lineageAssetFqn || resolvedTargets.assetFqn;
  visibleColumnName = resolvedTargets.columnName;
  report.assetFqn = visibleAssetFqn;
  report.lineageAssetFqn = visibleLineageAssetFqn;
  report.columnName = visibleColumnName;
  pushCheck(
    "visible-asset-resolution",
    visibleAssetFqn ? "ok" : "warn",
    resolvedTargets,
  );
  if (!visibleAssetFqn) {
    throw new Error("No visible discovery asset could be resolved from the authenticated workspace.");
  }

  const resolvedWritableTarget = await resolveWritableAssetTarget(page);
  if (resolvedWritableTarget.assetFqn && resolvedWritableTarget.columnName) {
    writableAssetFqn = resolvedWritableTarget.assetFqn;
    writableColumnName = resolvedWritableTarget.columnName;
    report.writableAssetFqn = writableAssetFqn;
    report.writableColumnName = writableColumnName;
  }
  pushCheck(
    "writable-asset-resolution",
    writableAssetFqn && writableColumnName ? "ok" : "warn",
    {
      assetFqn: writableAssetFqn,
      columnName: writableColumnName,
      fallback: !resolvedWritableTarget.assetFqn,
    },
  );

  await page.locator("#gh-global-search-input").fill("ta");
  await page.waitForSelector(".gh-search-dropdown", { timeout: 15000 });
  await screenshot(page, "discovery-search-open");
  const searchOverlay = await page.evaluate(() => {
    const dropdown = document.querySelector(".gh-search-dropdown");
    const row = document.querySelector(".gh-search-result-row");
    const catalogPanel = document.querySelector(".gh-discovery-command-panel");
    if (!dropdown || !row || !catalogPanel) return null;
    const rowRect = row.getBoundingClientRect();
    const probeX = rowRect.left + Math.min(40, rowRect.width / 4);
    const probeY = rowRect.top + Math.min(22, rowRect.height / 2);
    const topElement = document.elementFromPoint(probeX, probeY);
    return {
      dropdownOnTop: Boolean(topElement?.closest(".gh-search-dropdown")),
      dropdownTop: dropdown.getBoundingClientRect().top,
      dropdownBottom: dropdown.getBoundingClientRect().bottom,
      catalogTop: catalogPanel.getBoundingClientRect().top,
      resultLabels: [...document.querySelectorAll(".gh-search-result-title")].slice(0, 4).map((node) => node.textContent.trim()),
    };
  });
  pushCheck("global-search-overlay", searchOverlay?.dropdownOnTop ? "ok" : "warn", searchOverlay || {});
  await page.keyboard.press("Escape");

  const discoveryCards = await collectDiscoveryCards(page);
  discoveryRouteCandidate =
    discoveryCards.find((item) => item.fqn && item.fqn !== visibleAssetFqn) ||
    discoveryCards.find((item) => item.fqn) ||
    null;
  pushCheck("discovery-link-routing-candidate", discoveryRouteCandidate ? "ok" : "warn", {
    discoveryRouteCandidate,
    discoveryCards: discoveryCards.slice(0, 4),
  });
  const discoveryRouteCard = discoveryRouteCandidate
    ? page.locator(".gh-discovery-result-row").filter({ hasText: discoveryRouteCandidate.title }).first()
    : page.locator(".gh-discovery-result-row").first();
  const discoveryOpenRecordButton = discoveryRouteCard.getByRole("button", { name: "Open Record" }).first();
  if (await discoveryOpenRecordButton.count()) {
    const beforeRoute = currentRoute(page);
    await discoveryOpenRecordButton.click();
    await page
      .waitForFunction(
        (previousUrl) => {
          const next = new URL(window.location.href);
          return (
            window.location.href !== previousUrl &&
            next.searchParams.get("surface") === "entity" &&
            Boolean(next.searchParams.get("asset"))
          );
        },
        beforeRoute.url,
        { timeout: 15000 },
      )
      .catch(() => {});
    const afterRoute = currentRoute(page);
    pushCheck("discovery-link-routing", afterRoute.surface === "entity" && afterRoute.asset ? "ok" : "warn", {
      beforeRoute,
      afterRoute,
      candidate: discoveryRouteCandidate,
    });
  } else {
    pushCheck("discovery-link-routing", "warn", {
      reason: "Open Record was not available on the first discovery result card.",
      candidate: discoveryRouteCandidate,
    });
  }

  await gotoSurface(
    page,
    `${BASE_URL}/?module=discovery&surface=entity&asset=${visibleAssetFqn}&_cb=codex-qa-entity-${suffix}`,
    ".gh-entity-record-tabs",
  );
  const overviewWarmSettled = await waitForOverviewWarmup(page);
  await screenshot(page, "entity-overview");

  const operationalApi = await fetchJson(
    page,
    assetApiPath(visibleAssetFqn, `?sections=header&sections=activity&sections=operational&_qa=${Date.now()}`),
  );
  const lineageApi = await fetchJson(
    page,
    lineageApiPath(visibleLineageAssetFqn, `?_qa=${Date.now()}`),
  );
  pushCheck(
    "entity-operational-api",
    operationalApi.ok &&
      (operationalApi.json?.usage?.producerCount || 0) + (operationalApi.json?.usage?.consumerCount || 0) > 0
      ? "ok"
      : "warn",
    {
      warmSettled: overviewWarmSettled,
      usage: operationalApi.json?.usage || null,
      operationalContext: operationalApi.json?.operationalContext || null,
    },
  );
  pushCheck(
    "entity-lineage-api",
    lineageApi.ok && (lineageApi.json?.graphs?.data?.nodes || []).length > 0 ? "ok" : "warn",
    {
      stats: lineageApi.json?.stats || null,
      dataNodes: lineageApi.json?.graphs?.data?.nodes?.length || 0,
      dataEdges: lineageApi.json?.graphs?.data?.edges?.length || 0,
    },
  );

  const overviewRaw = await page.evaluate(() => {
    const liveSignalCard = [...document.querySelectorAll(".gh-record-card")].find((card) =>
      card.innerText.includes("Live Record Signals"),
    );
    const lineageCard = [...document.querySelectorAll(".gh-record-card")].find((card) =>
      card.innerText.includes("Lineage Context"),
    );
    const signalRows = liveSignalCard
      ? [...liveSignalCard.querySelectorAll(".gh-attribute-row")].map((row) => row.innerText.trim())
      : [];
    const metricRows = [...document.querySelectorAll(".gh-preview-stat-card.gh-entity-metric-card")].map((row) =>
      row.innerText.trim(),
    );
    return {
      signalRows,
      metricRows,
      lineageSummary: lineageCard ? lineageCard.innerText.trim() : "",
    };
  });
  const overview = {
    ...overviewRaw,
    signals: rowMap(overviewRaw.signalRows),
  };
  pushCheck("entity-overview", "ok", overview);

  const metadataEditorCard = page.locator(".gh-record-card").filter({ hasText: "Metadata Controls" }).first();
  const metadataSaveButton = metadataEditorCard.getByRole("button", { name: "Save metadata" }).first();
  const metadataEditorEditable = await metadataSaveButton.count();
  if (metadataEditorEditable) {
    const metadataDescriptionField = metadataEditorCard
      .locator('.gh-metadata-edit-field:has-text("Description") textarea')
      .first();
    const metadataDomainField = metadataEditorCard.locator('.gh-metadata-edit-field:has-text("Domain") input').first();
    const metadataTierField = metadataEditorCard.locator('.gh-metadata-edit-field:has-text("Tier") input').first();
    const metadataCertificationField = metadataEditorCard
      .locator('.gh-metadata-edit-field:has-text("Certification") input')
      .first();
    const metadataSensitivityField = metadataEditorCard
      .locator('.gh-metadata-edit-field:has-text("Sensitivity") input')
      .first();
    const originalAssetMetadataDraft = {
      description: await metadataDescriptionField.inputValue().catch(() => ""),
      domain: await metadataDomainField.inputValue().catch(() => ""),
      tier: await metadataTierField.inputValue().catch(() => ""),
      certification: await metadataCertificationField.inputValue().catch(() => ""),
      sensitivity: await metadataSensitivityField.inputValue().catch(() => ""),
    };
    const updatedAssetMetadataDraft = {
      ...originalAssetMetadataDraft,
      description: `Codex QA asset description ${suffix}`,
    };
    await metadataDescriptionField.fill(updatedAssetMetadataDraft.description);
    await metadataDomainField.fill(updatedAssetMetadataDraft.domain);
    await metadataTierField.fill(updatedAssetMetadataDraft.tier);
    await metadataCertificationField.fill(updatedAssetMetadataDraft.certification);
    await metadataSensitivityField.fill(updatedAssetMetadataDraft.sensitivity);
    await metadataSaveButton.click();
    await page
      .waitForFunction(
        () => {
          const text = document.body?.innerText || "";
          return text.includes("Metadata saved.") || text.includes("Saving...");
        },
        { timeout: 30000 },
      )
      .catch(() => {});
    await page.waitForTimeout(1500);
    const metadataAfterUpdate = await fetchJson(
      page,
      assetApiPath(visibleAssetFqn, `?sections=header&_qa=${Date.now()}`),
    );
    const metadataUpdated =
      metadataAfterUpdate.ok &&
      String(metadataAfterUpdate.json?.description || "").includes(updatedAssetMetadataDraft.description);
    pushCheck("asset-metadata-edit", metadataUpdated ? "ok" : "warn", {
      originalAssetMetadataDraft,
      updatedAssetMetadataDraft,
      apiAsset: metadataAfterUpdate.json || null,
    });
    if (metadataUpdated) {
      await metadataDescriptionField.fill(originalAssetMetadataDraft.description);
      await metadataDomainField.fill(originalAssetMetadataDraft.domain);
      await metadataTierField.fill(originalAssetMetadataDraft.tier);
      await metadataCertificationField.fill(originalAssetMetadataDraft.certification);
      await metadataSensitivityField.fill(originalAssetMetadataDraft.sensitivity);
      await metadataSaveButton.click();
      await page.waitForTimeout(1500);
      const metadataAfterRestore = await fetchJson(
        page,
        assetApiPath(visibleAssetFqn, `?sections=header&_qa=${Date.now()}`),
      );
      const metadataRestored =
        metadataAfterRestore.ok &&
        String(metadataAfterRestore.json?.description || "") === String(originalAssetMetadataDraft.description || "");
      pushCheck("asset-metadata-restore", metadataRestored ? "ok" : "warn", {
        restoredAssetMetadataDraft: originalAssetMetadataDraft,
        apiAsset: metadataAfterRestore.json || null,
      });
    } else {
      pushCheck("asset-metadata-restore", "warn", {
        reason: "Asset metadata update did not round-trip cleanly, so restore was skipped.",
        originalAssetMetadataDraft,
        updatedAssetMetadataDraft,
      });
    }
  } else {
    pushCheck("asset-metadata-edit", "warn", {
      reason: "Metadata Controls were not editable on the entity overview surface.",
    });
    pushCheck("asset-metadata-restore", "warn", {
      reason: "Metadata Controls were not editable on the entity overview surface.",
    });
  }

  await page.getByRole("button", { name: "Usage & Workloads" }).click();
  await page
    .waitForFunction(
      () => {
        const taskTitles = document.querySelectorAll(".gh-task-row .gh-task-title").length;
        if (taskTitles > 0) return true;
        const text = document.body?.innerText || "";
        return (
          text.includes("Loading workload and operational context") ||
          text.includes("No workload usage was surfaced for this direction.")
        );
      },
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1000);
  await screenshot(page, "entity-usage-workloads");
  const usageState = await page.evaluate(() => {
    const titles = [...document.querySelectorAll(".gh-task-title")].map((node) => node.textContent.trim());
    const relatedButtons = [...document.querySelectorAll(".gh-task-row .gh-chip-row button")].map((button) =>
      button.textContent.trim(),
    );
    return {
      titles,
      relatedButtons,
      loadingVisible: document.body.innerText.includes("Loading workload and operational context"),
      emptyVisible: document.body.innerText.includes("No workload usage was surfaced for this direction."),
      rawUuidOnlyTitles: titles.filter((title) =>
        /^[0-9a-f]{8,}(-[0-9a-f]{4,}){0,}$/i.test(title),
      ),
    };
  });
  pushCheck(
    "usage-workloads",
    usageState.relatedButtons.length ? "ok" : "warn",
    usageState,
  );

  const usageLinkedAsset = page.locator(".gh-task-row .gh-chip-row button").first();
  if (await usageLinkedAsset.count()) {
    const linkedLabel = await usageLinkedAsset.textContent();
    const beforeRoute = currentRoute(page);
    await usageLinkedAsset.click();
    await page
      .waitForFunction(
        (previousUrl) => window.location.href !== previousUrl && window.location.search.includes("asset="),
        beforeRoute.url,
        { timeout: 15000 },
      )
      .catch(() => {});
    const navigatedRoute = currentRoute(page);
    pushCheck(
      "usage-linked-asset-routing",
      navigatedRoute.surface === "entity" && navigatedRoute.asset && navigatedRoute.url !== beforeRoute.url ? "ok" : "warn",
      {
      linkedLabel: (linkedLabel || "").trim(),
      beforeRoute,
      navigatedRoute,
      },
    );
  } else {
    pushCheck("usage-linked-asset-routing", "warn", {
      reason: "No linked asset buttons were rendered in Usage & Workloads.",
    });
  }

  await gotoSurface(
    page,
    `${BASE_URL}/?module=discovery&surface=entity&asset=${visibleAssetFqn}&_cb=codex-qa-entity-schema-${suffix}`,
    ".gh-entity-record-tabs",
  );
  await page.getByRole("button", { name: "Schema" }).click();
  await page.waitForSelector(".gh-table tbody tr", { timeout: 15000 });
  await page.locator(".gh-table tbody tr").filter({ hasText: visibleColumnName }).first().click();
  const selectedColumnCard = page.locator(".gh-record-card").filter({ hasText: "Selected Column" }).first();
  await selectedColumnCard.waitFor({ timeout: 15000 });
  const readOnlySchemaState = await page.evaluate(() => {
    const selected = [...document.querySelectorAll(".gh-record-card")].find((card) =>
      card.innerText.includes("Selected Column"),
    );
    if (!selected) return null;
    return {
      hasTextarea: Boolean(selected.querySelector("textarea")),
      hasTagsInput: Boolean(selected.querySelector('input[placeholder="domain=Finance, sensitivity=PII"]')),
      hasSaveButton: [...selected.querySelectorAll("button")].some(
        (button) => button.textContent.trim() === "Save column",
      ),
      text: selected.innerText.trim(),
    };
  });
  pushCheck(
    "schema-column-readonly",
    readOnlySchemaState && !readOnlySchemaState.hasTextarea && !readOnlySchemaState.hasSaveButton ? "ok" : "warn",
    readOnlySchemaState || {},
  );

  const writableTargetValidation = writableAssetFqn
    ? await fetchJson(page, assetApiPath(writableAssetFqn, `?sections=header,schema&_qa=${Date.now()}`))
    : null;
  const canExerciseWritableColumnFlow = Boolean(
    writableTargetValidation?.ok &&
      writableTargetValidation.json?.metadataEditor?.available === true &&
      (writableTargetValidation.json?.columns || []).some((column) => column.name === writableColumnName),
  );

  if (canExerciseWritableColumnFlow) {
    await gotoSurface(
      page,
      `${BASE_URL}/?module=discovery&surface=entity&asset=${writableAssetFqn}&_cb=codex-qa-entity-schema-write-${suffix}`,
      ".gh-entity-record-tabs",
    );
    await page.getByRole("button", { name: "Schema" }).click();
    await page.waitForSelector(".gh-table tbody tr", { timeout: 15000 });
    await page.locator(".gh-table tbody tr", { hasText: writableColumnName }).click();
    const writableColumnCard = page.locator(".gh-record-card").filter({ hasText: "Selected Column" }).first();
    await writableColumnCard.waitFor({ timeout: 15000 });
    const descriptionField = writableColumnCard.locator("textarea").first();
    const tagsField = writableColumnCard.locator('input[placeholder="domain=Finance, sensitivity=PII"]').first();
    originalWritableColumnDraft = {
      description: await descriptionField.inputValue(),
      tags: await tagsField.inputValue(),
    };
    const updatedColumnDraft = {
      description: `Codex QA column description ${suffix}`,
      tags: originalWritableColumnDraft.tags
        ? `${originalWritableColumnDraft.tags}, qa_probe=${suffix}`
        : `qa_probe=${suffix}`,
    };
    await descriptionField.fill(updatedColumnDraft.description);
    await tagsField.fill(updatedColumnDraft.tags);
    await writableColumnCard.getByRole("button", { name: "Save column" }).click();
    await page.waitForTimeout(1800);
    const columnAfterUpdate = await fetchJson(
      page,
      assetApiPath(writableAssetFqn, `?sections=schema&_qa=${Date.now()}`),
    );
    const updatedColumn =
      (columnAfterUpdate.json?.columns || []).find((column) => column.name === writableColumnName) || null;
    const columnUpdateOk =
      columnAfterUpdate.ok &&
      updatedColumn &&
      String(updatedColumn.description || "").includes(updatedColumnDraft.description) &&
      (updatedColumn.tagLabels || []).some((tag) => String(tag).includes(`qa_probe=${suffix}`));
    pushCheck("schema-column-update", columnUpdateOk ? "ok" : "warn", {
      originalWritableColumnDraft,
      updatedColumnDraft,
      apiColumn: updatedColumn,
    });

    await descriptionField.fill(originalWritableColumnDraft.description);
    await tagsField.fill(originalWritableColumnDraft.tags);
    await writableColumnCard.getByRole("button", { name: "Save column" }).click();
    await page.waitForTimeout(1500);
    const columnAfterRestore = await fetchJson(
      page,
      assetApiPath(writableAssetFqn, `?sections=schema&_qa=${Date.now()}`),
    );
    const restoredColumn =
      (columnAfterRestore.json?.columns || []).find((column) => column.name === writableColumnName) || null;
    const restoredTagLabels = restoredColumn?.tagLabels || [];
    pushCheck(
      "schema-column-restore",
      columnAfterRestore.ok &&
        String(restoredColumn?.description || "") === String(originalWritableColumnDraft.description || "") &&
        !restoredTagLabels.some((tag) => String(tag).includes(`qa_probe=${suffix}`))
        ? "ok"
        : "warn",
      {
        restoredTo: originalWritableColumnDraft,
        apiColumn: restoredColumn,
      },
    );
  } else {
    pushCheck("schema-column-update", "warn", {
      assetFqn: writableAssetFqn,
      columnName: writableColumnName,
      reason: "No writable Delta-table column editor was reachable in the live workspace session.",
      validation: writableTargetValidation?.json || null,
    });
    pushCheck("schema-column-restore", "warn", {
      assetFqn: writableAssetFqn,
      columnName: writableColumnName,
      reason: "Skipped restore because the writable column editor was not reachable in the live workspace session.",
    });
  }

  await gotoSurface(
    page,
    `${BASE_URL}/?module=discovery&surface=entity&asset=${visibleLineageAssetFqn}&_cb=codex-qa-entity-lineage-${suffix}`,
    ".gh-entity-record-tabs",
  );
  await page.locator(".gh-entity-record-tabs .gh-subtab", { hasText: /^Lineage$/ }).click();
  await page
    .waitForFunction(
      () => {
        const nodeCount = document.querySelectorAll(".react-flow__node").length;
        const text = document.body?.innerText || "";
        return (
          nodeCount > 0 ||
          text.includes("Loading lineage graph") ||
          text.includes("No connected lineage edges are available for this asset yet.")
        );
      },
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1200);
  await screenshot(page, "entity-lineage-tab");
  const entityLineage = await page.evaluate(() => ({
    nodeCount: document.querySelectorAll(".react-flow__node").length,
    edgeCount: document.querySelectorAll(".react-flow__edge").length,
    loadingVisible: document.body.innerText.includes("Loading lineage graph"),
    hasBlankCanvas:
      Boolean(document.querySelector(".gh-lineage-stage-shell")) &&
      document.querySelectorAll(".react-flow__node").length === 0,
  }));
  pushCheck(
    "entity-lineage-tab",
    entityLineage.nodeCount > 0 ? "ok" : "warn",
    entityLineage,
  );

  await page.getByRole("button", { name: "Open full graph" }).click();
  await page.waitForSelector(".gh-lineage-stage-shell", { timeout: 15000 });
  await page
    .waitForFunction(
      () => {
        const nodeCount = document.querySelectorAll(".react-flow__node").length;
        const text = document.body?.innerText || "";
        return (
          nodeCount > 0 ||
          text.includes("Loading lineage graph") ||
          text.includes("No connected lineage edges are available for this asset yet.")
        );
      },
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1200);
  await screenshot(page, "lineage-full-graph");
  const fullLineage = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".react-flow__node")].map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        text: node.textContent.trim(),
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
      };
    });
    let overlaps = 0;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        if (a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top) {
          continue;
        }
        overlaps += 1;
      }
    }
    return {
      nodeCount: nodes.length,
      edgeCount: document.querySelectorAll(".react-flow__edge").length,
      overlaps,
      loadingVisible: document.body.innerText.includes("Loading lineage graph"),
      drawerTitle: document.querySelector(".gh-lineage-drawer-head")?.textContent?.trim() || "",
    };
  });
  pushCheck(
    "lineage-full-graph",
    fullLineage.nodeCount > 0 && fullLineage.overlaps === 0 ? "ok" : "warn",
    fullLineage,
  );

  const lineageNodes = page.locator(".react-flow__node");
  if (await lineageNodes.count()) {
    await lineageNodes.first().click({ force: true }).catch(() => {});
    await page.waitForTimeout(800);
    const lineageDrawerDetails = await page.evaluate(() => {
      const drawer = document.querySelector(".gh-lineage-drawer");
      const drawerHead = document.querySelector(".gh-lineage-drawer-head");
      return {
        drawerOpen: Boolean(drawer?.classList.contains("is-open")),
        head: drawerHead?.textContent?.trim() || "",
        actionButtons: [...document.querySelectorAll(".gh-lineage-drawer .gh-lineage-drawer-actions button")].map((button) =>
          button.textContent.trim(),
        ),
        attributeRows: [...document.querySelectorAll(".gh-lineage-drawer .gh-attribute-row")].map((row) =>
          row.textContent.trim(),
        ),
        linkedRows: [...document.querySelectorAll(".gh-lineage-drawer .gh-lineage-linked-row")]
          .slice(0, 8)
          .map((row) => row.textContent.trim()),
        entityDetails: [...document.querySelectorAll(".gh-lineage-drawer .gh-lineage-linked-row.is-readonly")].map((row) =>
          row.textContent.trim(),
        ),
      };
    });
    pushCheck(
      "lineage-drawer-details",
      lineageDrawerDetails.drawerOpen &&
        lineageDrawerDetails.head.length > 0 &&
        lineageDrawerDetails.actionButtons.length > 0 &&
        lineageDrawerDetails.attributeRows.length > 0
        ? "ok"
        : "warn",
      lineageDrawerDetails,
    );
  } else {
    pushCheck("lineage-drawer-details", "warn", {
      reason: "No lineage nodes were available to open the drawer.",
    });
  }

  if (discoveryRouteCandidate?.title) {
    const originalLineageRoute = currentRoute(page);
    const refocusButton = page.getByRole("button", { name: "Refocus" }).first();
    if (await refocusButton.count()) {
      await refocusButton.click();
      await page.waitForTimeout(600);
      const refocusInput = page.locator(".gh-lineage-command-popover input").first();
      await refocusInput.fill(discoveryRouteCandidate.title);
      await page.waitForTimeout(1200);
      const refocusCandidateRow = page
        .locator(".gh-lineage-search-row")
        .filter({ hasText: discoveryRouteCandidate.title })
        .first();
      const refocusSearchBefore = currentRoute(page);
      if (await refocusCandidateRow.count()) {
        await refocusCandidateRow.click();
        await page
          .waitForFunction(
            (previousAsset) => {
              const next = new URL(window.location.href);
              return next.searchParams.get("asset") && next.searchParams.get("asset") !== previousAsset;
            },
            originalLineageRoute.asset,
            { timeout: 20000 },
          )
          .catch(() => {});
        const refocusedRoute = currentRoute(page);
        let returnedRoute = null;
        const returnToFocusButton = page.getByRole("button", { name: "Return to focus" }).first();
        if (await returnToFocusButton.count()) {
          await returnToFocusButton.click();
          await page
            .waitForFunction(
              (previousAsset) => {
                const next = new URL(window.location.href);
                return next.searchParams.get("asset") === previousAsset;
              },
              originalLineageRoute.asset,
              { timeout: 20000 },
            )
            .catch(() => {});
          returnedRoute = currentRoute(page);
        }
        pushCheck(
          "lineage-workspace-refocus",
          refocusedRoute.asset && refocusedRoute.asset !== originalLineageRoute.asset ? "ok" : "warn",
          {
            originalLineageRoute,
            refocusSearchBefore,
            refocusedRoute,
            returnedRoute,
            candidate: discoveryRouteCandidate,
          },
        );
      } else {
        pushCheck("lineage-workspace-refocus", "warn", {
          reason: "The refocus search did not surface a matching asset row.",
          originalLineageRoute,
          candidate: discoveryRouteCandidate,
        });
      }
    } else {
      pushCheck("lineage-workspace-refocus", "warn", {
        reason: "The Refocus control was not available in the full lineage workspace.",
        candidate: discoveryRouteCandidate,
      });
    }
  } else {
    pushCheck("lineage-workspace-refocus", "warn", {
      reason: "No alternate discovery route candidate was captured to drive a lineage refocus.",
    });
  }

  await gotoSurface(
    page,
    `${BASE_URL}/?module=governance&surface=governance&asset=${visibleAssetFqn}&_cb=codex-qa-governance-${suffix}`,
    ".gh-governance-workbench",
  );
  await page.waitForTimeout(1500);
  await screenshot(page, "governance-workbench");
  const approveRequestCreate = await createGovernanceRequest(page, approveRequestTitle, approveRequestNote);
  createdApproveRequestId = approveRequestCreate.requestId;
  pushCheck("governance-request-approve-create", createdApproveRequestId ? "ok" : "warn", {
    requestId: createdApproveRequestId,
    requestMatch: approveRequestCreate.requestMatch,
    bodyPreview: approveRequestCreate.bodyPreview,
  });
  if (createdApproveRequestId) {
    const approveAction = await actOnGovernanceRequest(page, {
      requestTitle: approveRequestTitle,
      requestId: createdApproveRequestId,
      buttonName: "Approve",
      successText: "Request approved.",
    });
    pushCheck(
      "governance-request-approve",
      approveAction.acted && !approveAction.requestStillOpen ? "ok" : "warn",
      {
        requestId: createdApproveRequestId,
        requestStillOpen: approveAction.requestStillOpen,
        summary: approveAction.summary?.json || null,
        reason: approveAction.reason || "",
      },
    );
  } else {
    pushCheck("governance-request-approve", "warn", {
      reason: "The approval request was not returned by the governance API.",
    });
  }

  const rejectRequestCreate = await createGovernanceRequest(page, rejectRequestTitle, rejectRequestNote);
  createdRejectRequestId = rejectRequestCreate.requestId;
  pushCheck("governance-request-reject-create", createdRejectRequestId ? "ok" : "warn", {
    requestId: createdRejectRequestId,
    requestMatch: rejectRequestCreate.requestMatch,
    bodyPreview: rejectRequestCreate.bodyPreview,
  });
  if (createdRejectRequestId) {
    const rejectAction = await actOnGovernanceRequest(page, {
      requestTitle: rejectRequestTitle,
      requestId: createdRejectRequestId,
      buttonName: "Reject",
      successText: "Request rejected.",
    });
    pushCheck(
      "governance-request-reject",
      rejectAction.acted && !rejectAction.requestStillOpen ? "ok" : "warn",
      {
        requestId: createdRejectRequestId,
        requestStillOpen: rejectAction.requestStillOpen,
        summary: rejectAction.summary?.json || null,
        reason: rejectAction.reason || "",
      },
    );
  } else {
    pushCheck("governance-request-reject", "warn", {
      reason: "The rejection request was not returned by the governance API.",
    });
  }

  const glossaryCreateBlock = page.locator(".gh-form-block").filter({ hasText: "Create glossary term" });
  await glossaryCreateBlock.locator('input[placeholder="Term name"]').fill(glossaryName);
  await glossaryCreateBlock.locator('textarea[placeholder="Definition"]').fill(glossaryDefinition);
  await glossaryCreateBlock.locator('input[placeholder="Domain"]').fill("Finance");
  await glossaryCreateBlock.locator('input[placeholder="Owner email"]').fill(glossaryOwner);
  await glossaryCreateBlock.locator('input[placeholder="draft"]').fill("draft");
  await glossaryCreateBlock
    .locator('textarea[placeholder*="Initial reviewers"]')
    .fill(glossaryReviewerInitial);
  await glossaryCreateBlock.locator('textarea[placeholder="Optional creation note"]').fill(`Created ${suffix}`);
  await page
    .waitForFunction(
      () => {
        const buttons = [...document.querySelectorAll(".gh-form-block button")];
        const createButton = buttons.find((button) => button.textContent.trim() === "Create term");
        return Boolean(createButton && !createButton.disabled);
      },
      { timeout: 15000 },
    )
    .catch(() => {});
  await glossaryCreateBlock.getByRole("button", { name: "Create term" }).click();
  await page
    .waitForFunction(
      (title) => {
        const text = document.body?.innerText || "";
        return text.includes(title) || text.includes("Glossary term saved.");
      },
      glossaryName,
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(1200);
  await screenshot(page, "governance-glossary-create");
  const glossaryAfterCreate = await fetchJson(page, `/api/governance/glossary?_qa=${Date.now()}`);
  const glossaryMatch =
    (glossaryAfterCreate.json?.glossary || []).find(
      (item) => item.title === glossaryName || item.term === glossaryName,
    ) || null;
  createdGlossaryTermId = glossaryMatch?.termId || glossaryMatch?.id || "";
  const glossaryBodyAfterCreate = await page.evaluate(() => document.body?.innerText || "");
  pushCheck(
    "glossary-create",
    createdGlossaryTermId ? "ok" : "warn",
    { termId: createdGlossaryTermId, glossaryMatch, bodyPreview: glossaryBodyAfterCreate.slice(0, 1800) },
  );

  if (createdGlossaryTermId) {
    const glossarySaveButton = page.getByRole("button", { name: "Save term" }).first();
    if (!(await glossarySaveButton.count())) {
      const glossaryModeButton = page.getByRole("button", { name: "Glossary" }).first();
      if (await glossaryModeButton.count()) {
        await glossaryModeButton.click();
        await page.waitForTimeout(1200);
      }
      const glossaryRow = page.locator(".gh-request-row").filter({ hasText: glossaryName }).first();
      if (await glossaryRow.count()) {
        await glossaryRow.click();
        await page.waitForTimeout(1000);
      }
    }
    await page.locator('.gh-metadata-edit-field:has-text("Definition") textarea').fill(glossaryDefinitionUpdated);
    await page.locator('.gh-metadata-edit-field:has-text("Reviewer roster") textarea').fill(glossaryReviewerUpdated);
    await page.locator('.gh-metadata-edit-field:has-text("Change note") textarea').fill(`Edited ${suffix}`);
    await page.getByRole("button", { name: "Save term" }).click();
    await page
      .waitForFunction(
        () => {
          const text = document.body?.innerText || "";
          return text.includes("Glossary term updated.");
        },
        { timeout: 30000 },
      )
      .catch(() => {});
    await page.waitForTimeout(1500);
    let glossaryAfterEdit = null;
    let glossaryEdited = null;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      glossaryAfterEdit = await fetchJson(page, `/api/governance/glossary?_qa=${Date.now()}`);
      glossaryEdited =
        (glossaryAfterEdit.json?.glossary || []).find(
        (item) => item.title === glossaryName || item.term === glossaryName,
        ) || null;
      const roles = (glossaryEdited?.reviewerRoster || []).map((reviewer) =>
        `${reviewer.email || reviewer.reviewerEmail || ""}:${reviewer.role || reviewer.reviewerRole || ""}`,
      );
      if (
        glossaryEdited &&
        String(glossaryEdited.definition || glossaryEdited.detail || "").includes(glossaryDefinitionUpdated) &&
        roles.some((entry) => entry.includes("approver")) &&
        (glossaryEdited.termHistory || glossaryEdited.versionHistory || []).length > 1
      ) {
        break;
      }
      await page.waitForTimeout(1500);
    }
    const reviewerRoles = (glossaryEdited?.reviewerRoster || []).map((reviewer) =>
      `${reviewer.email || reviewer.reviewerEmail || ""}:${reviewer.role || reviewer.reviewerRole || ""}`,
    );
    pushCheck(
      "glossary-edit",
      glossaryEdited &&
        String(glossaryEdited.definition || glossaryEdited.detail || "").includes(glossaryDefinitionUpdated) &&
        reviewerRoles.some((entry) => entry.includes("approver")) &&
        (glossaryEdited.termHistory || []).length > 0
        ? "ok"
        : "warn",
      {
      termId: createdGlossaryTermId,
      glossaryEdited,
      reviewerRoles,
    },
    );
    const glossaryModeButton = page.getByRole("button", { name: "Glossary" }).first();
    if (await glossaryModeButton.count()) {
      await glossaryModeButton.click();
      await page.waitForTimeout(1000);
    }
    const glossaryToolbar = page.locator(".gh-governance-glossary-toolbar");
    const glossarySearchField = glossaryToolbar
      .locator('input[placeholder="Search terms, definitions, or domains"]')
      .first();
    await glossarySearchField.fill(glossaryName);
    const glossaryFinanceChip = glossaryToolbar.locator(".gh-filter-chip").filter({ hasText: "Finance" }).first();
    if (await glossaryFinanceChip.count()) {
      await glossaryFinanceChip.click();
    }
    await page.waitForTimeout(800);
    const glossaryBeforePersistence = await page.evaluate(() => {
      const searchInput = document.querySelector(
        '.gh-governance-glossary-toolbar input[placeholder="Search terms, definitions, or domains"]',
      );
      return {
        queryValue: searchInput?.value || "",
        activeFilters: [...document.querySelectorAll(".gh-governance-glossary-toolbar .gh-filter-chip.is-active")].map(
          (button) => button.textContent.trim(),
        ),
        visibleTermCount: document.querySelectorAll(".gh-governance-glossary-list .gh-request-row").length,
        visibleTerms: [...document.querySelectorAll(".gh-governance-glossary-list .gh-request-row")]
          .slice(0, 5)
          .map((node) => node.textContent.trim()),
      };
    });
    const stewardshipButton = page.getByRole("button", { name: "Stewardship" }).first();
    if (await stewardshipButton.count()) {
      await stewardshipButton.click();
      await page.waitForTimeout(1000);
    }
    if (await glossaryModeButton.count()) {
      await glossaryModeButton.click();
      await page.waitForTimeout(1000);
    }
    const glossaryAfterPersistence = await page.evaluate(() => {
      const searchInput = document.querySelector(
        '.gh-governance-glossary-toolbar input[placeholder="Search terms, definitions, or domains"]',
      );
      return {
        queryValue: searchInput?.value || "",
        activeFilters: [...document.querySelectorAll(".gh-governance-glossary-toolbar .gh-filter-chip.is-active")].map(
          (button) => button.textContent.trim(),
        ),
        visibleTermCount: document.querySelectorAll(".gh-governance-glossary-list .gh-request-row").length,
        visibleTerms: [...document.querySelectorAll(".gh-governance-glossary-list .gh-request-row")]
          .slice(0, 5)
          .map((node) => node.textContent.trim()),
      };
    });
    const glossaryPersistenceOk =
      glossaryAfterPersistence.queryValue === glossaryName &&
      glossaryAfterPersistence.visibleTermCount === glossaryBeforePersistence.visibleTermCount &&
      glossaryAfterPersistence.activeFilters.join("|") === glossaryBeforePersistence.activeFilters.join("|");
    pushCheck("glossary-query-filter-persistence", glossaryPersistenceOk ? "ok" : "warn", {
      before: glossaryBeforePersistence,
      after: glossaryAfterPersistence,
      glossaryName,
    });
  } else {
    pushCheck("glossary-edit", "warn", {
      termId: createdGlossaryTermId,
      reason: "Created glossary term was not returned by the glossary API.",
    });
    pushCheck("glossary-query-filter-persistence", "warn", {
      reason: "Glossary persistence was skipped because the created term was not returned by the API.",
    });
  }

  for (const responsiveCheck of [
    {
      name: "responsive-discovery-tablet",
      viewport: RESPONSIVE_VIEWPORTS[2],
      url: `${BASE_URL}/?module=discovery&surface=discovery&_cb=codex-qa-responsive-discovery-${suffix}`,
      selector: ".gh-discovery-main-grid",
    },
    {
      name: "responsive-entity-tablet",
      viewport: RESPONSIVE_VIEWPORTS[2],
      url: `${BASE_URL}/?module=discovery&surface=entity&asset=${visibleAssetFqn}&_cb=codex-qa-responsive-entity-${suffix}`,
      selector: ".gh-entity-record-layout",
    },
    {
      name: "responsive-lineage-mobile",
      viewport: RESPONSIVE_VIEWPORTS[3],
      url: `${BASE_URL}/?module=lineage&surface=lineage&asset=${visibleLineageAssetFqn}&_cb=codex-qa-responsive-lineage-${suffix}`,
      selector: ".gh-lineage-stage-shell",
    },
    {
      name: "responsive-governance-tablet",
      viewport: RESPONSIVE_VIEWPORTS[2],
      url: `${BASE_URL}/?module=governance&surface=governance&asset=${visibleAssetFqn}&_cb=codex-qa-responsive-governance-${suffix}`,
      selector: ".gh-governance-workbench",
    },
  ]) {
    await captureResponsiveSnapshot(
      page,
      responsiveCheck.name,
      responsiveCheck.url,
      responsiveCheck.selector,
      responsiveCheck.viewport,
    );
  }

  await finalizeRuntimeChecks();

  await fs.writeFile(path.join(OUT_DIR, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  pushCheck("suite-error", "error", {
    message: error?.message || String(error),
    stack: error?.stack || "",
  });
  await finalizeRuntimeChecks();
  await fs.writeFile(path.join(OUT_DIR, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  process.exitCode = 1;
} finally {
  await runtime?.close?.();
  process.exit(process.exitCode || 0);
}
