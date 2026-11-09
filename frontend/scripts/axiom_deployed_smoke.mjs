import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { copyChromeProfileToTemp, resolveChromeProfileName } from "./chrome_profile_tmp.mjs";

const BASE_URL = process.env.AXIOM_BASE_URL || process.argv[2] || "";
const DEEP_LINK_ASSET =
  process.env.AXIOM_SMOKE_ASSET_FQN ||
  process.env.AXIOM_SMOKE_ASSET_FQN ||
  "prod.silver.ap_self_assessed_tax_dist";
const DATABRICKS_TOKEN = process.env.AXIOM_DATABRICKS_TOKEN || "";
const CDP_URL = process.env.AXIOM_CDP_URL || "http://127.0.0.1:9223";
const OUT_DIR = process.env.AXIOM_SMOKE_OUT_DIR || "/tmp/axiom-deployed-smoke";
const SMOKE_TIMEOUT_MS = Number(process.env.AXIOM_SMOKE_TIMEOUT_MS || 15000);
const LOCAL_BUILD_MANIFEST_PATHS = [
  new URL("../dist/axiom-build-manifest.json", import.meta.url),
];
const CHROME_PROFILE_ROOT =
  process.env.AXIOM_CHROME_PROFILE_ROOT ||
  process.env.AXIOM_CHROME_PROFILE_ROOT ||
  path.join(process.env.HOME || "", "Library", "Application Support", "Google", "Chrome");

if (!BASE_URL) {
  console.error(
    "Usage: node frontend/scripts/axiom_deployed_smoke.mjs <base-url>",
  );
  process.exit(1);
}

const APP_ORIGIN = new URL(BASE_URL).origin;
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  appOrigin: APP_ORIGIN,
  deepLinkAsset: DEEP_LINK_ASSET,
  checks: [],
  screenshots: [],
  consoleErrors: [],
  pageErrors: [],
  networkErrors: [],
};

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(
    path.join(OUT_DIR, "report.json"),
    JSON.stringify(report, null, 2),
  );
}

async function pushCheck(name, status, detail = {}, { blocking = true } = {}) {
  report.checks.push({ name, status, blocking, ...detail });
  await flushReport();
}

async function screenshot(page, name) {
  const filePath = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: filePath, fullPage: true });
  report.screenshots.push(filePath);
  await flushReport();
}

function sameOrigin(url) {
  try {
    return new URL(url).origin === APP_ORIGIN;
  } catch {
    return false;
  }
}

function attachRuntimeListeners(page) {
  page.on("pageerror", async (error) => {
    const currentUrl = page.url();
    if (!sameOrigin(currentUrl)) return;
    report.pageErrors.push({
      message: error?.message || String(error),
      stack: error?.stack || "",
      url: currentUrl,
    });
    await flushReport();
  });
  page.on("console", async (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    const currentUrl = page.url();
    if (!sameOrigin(currentUrl)) return;
    report.consoleErrors.push({
      type: message.type(),
      text: message.text(),
      url: currentUrl,
    });
    await flushReport();
  });
  page.on("requestfailed", async (request) => {
    if (!sameOrigin(request.url())) return;
    report.networkErrors.push({
      url: request.url(),
      failureText: request.failure()?.errorText || "Request failed",
      method: request.method(),
    });
    await flushReport();
  });
  page.on("response", async (response) => {
    if (!sameOrigin(response.url()) || response.status() < 400) return;
    report.networkErrors.push({
      url: response.url(),
      status: response.status(),
      statusText: response.statusText(),
    });
    await flushReport();
  });
}

async function launchCopiedChromeContext() {
  const profileName = await resolveChromeProfileName(CHROME_PROFILE_ROOT);
  const copiedProfile = await copyChromeProfileToTemp({
    chromeProfileRoot: CHROME_PROFILE_ROOT,
    profileName,
    prefix: "axiom-smoke-chrome-profile-",
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
  const page =
    context.pages().find((candidate) => candidate.url().startsWith(BASE_URL)) ||
    context.pages().find((candidate) => /^https?:/i.test(candidate.url())) ||
    context.pages()[0] ||
    (await context.newPage());
  await page.bringToFront();
  attachRuntimeListeners(page);
  return {
    browser: context.browser(),
    context,
    page,
    close: async () => {
      await context.close().catch(() => {});
      await copiedProfile.cleanup();
    },
  };
}

async function connect() {
  if (DATABRICKS_TOKEN) {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      extraHTTPHeaders: { Authorization: `Bearer ${DATABRICKS_TOKEN}` },
      viewport: { width: 1600, height: 1040 },
    });
    const page = await context.newPage();
    attachRuntimeListeners(page);
    await pushCheck("browser-connect-token", "ok", { auth: "bearer-token" }, { blocking: false });
    return { browser, context, page };
  }
  try {
    const browser = await chromium.connectOverCDP(CDP_URL);
    const context = browser.contexts()[0] || (await browser.newContext());
    if (DATABRICKS_TOKEN) {
      await context.setExtraHTTPHeaders({ Authorization: `Bearer ${DATABRICKS_TOKEN}` });
    }
    const page = await context.newPage();
    await page.setViewportSize({ width: 1600, height: 1040 });
    attachRuntimeListeners(page);
    return { browser, context, page };
  } catch (error) {
    await pushCheck("browser-connect", "warn", {
      cdpUrl: CDP_URL,
      message: error?.message || "Failed to attach to authenticated Chrome over CDP.",
    }, { blocking: false });
  }

  const fallback = await launchCopiedChromeContext();
  await pushCheck("browser-connect-fallback", "ok", {
    profileRoot: CHROME_PROFILE_ROOT,
  });
  return fallback;
}

async function loadLocalBuildManifest() {
  const errors = [];
  for (const manifestPath of LOCAL_BUILD_MANIFEST_PATHS) {
    try {
      return JSON.parse(await fs.readFile(manifestPath, "utf-8"));
    } catch (error) {
      errors.push({ path: manifestPath.pathname, message: error?.message || String(error) });
    }
  }
  try {
    throw new Error("No local build manifest could be read.");
  } catch (error) {
    await pushCheck("local-build-manifest", "error", { errors });
    throw error;
  }
}

async function captureFailureState(page, name) {
  const detail = await page.evaluate(() => ({
    url: window.location.href,
    title: document.title,
    readyState: document.readyState,
    bodyPreview: (document.body?.innerText || "").slice(0, 1600),
    selectors: {
      shellHeader: Boolean(document.querySelector(".gh-shell-header")),
      discoveryGrid: Boolean(document.querySelector(".gh-discovery-main-grid")),
      entityTabs: Boolean(document.querySelector(".gh-entity-record-tabs")),
      unavailable: Boolean(document.querySelector(".gh-unavailable-panel")),
      shellProgress: Boolean(document.querySelector(".gh-shell-progress")),
    },
  }));
  await screenshot(page, `${name}-failure`);
  return detail;
}

async function guardedNavigate(page, name, targetUrl, selector) {
  const startedAt = Date.now();
  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });

  if (!sameOrigin(page.url())) {
    const detail = await captureFailureState(page, `${name}-auth-required`);
    await pushCheck(name, "error", {
      reason: "auth-required",
      expectedOrigin: APP_ORIGIN,
      landedUrl: page.url(),
      detail,
    });
    throw new Error(`Navigation left the app origin during ${name}: ${page.url()}`);
  }

  try {
    await page.waitForSelector(selector, { timeout: 45_000 });
  } catch (error) {
    const detail = await captureFailureState(page, name);
    await pushCheck(name, "error", {
      reason: "selector-timeout",
      selector,
      message: error?.message || String(error),
      detail,
    });
    throw error;
  }

  await page.waitForTimeout(1200);
  const shellProgressVisible = await page.evaluate(() =>
    Boolean(document.querySelector(".gh-shell-progress")),
  );
  await pushCheck(name, shellProgressVisible ? "warn" : "ok", {
    selector,
    settledMs: Date.now() - startedAt,
    shellProgressVisible,
    url: page.url(),
  });
}

async function fetchJson(page, apiPath, timeoutMs = SMOKE_TIMEOUT_MS) {
  return page.evaluate(async ({ targetUrl, timeoutMs: timeoutValue }) => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutValue);
    try {
      const response = await fetch(targetUrl, {
        credentials: "include",
        headers: {
          "Cache-Control": "no-store",
        },
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
        json,
        text,
        timedOut: false,
        error: "",
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        json: null,
        text: "",
        timedOut: error?.name === "AbortError",
        error: error?.message || String(error),
      };
    } finally {
      window.clearTimeout(timeoutId);
    }
  }, { targetUrl: apiPath, timeoutMs });
}

function baseUrl(pathname = "/") {
  return new URL(pathname, `${BASE_URL.replace(/\/+$/, "")}/`).toString();
}

function finalizeRuntimeChecks() {
  const pageErrorCount = report.pageErrors.length;
  const consoleWarningCount = report.consoleErrors.filter((entry) => entry.type === "warning").length;
  const consoleErrorCount = report.consoleErrors.filter((entry) => entry.type === "error").length;
  const networkErrorCount = report.networkErrors.length;
  report.checks.push({
    name: "page-errors",
    status: pageErrorCount ? "error" : "ok",
    blocking: true,
    count: pageErrorCount,
    messages: report.pageErrors.slice(0, 5),
  });
  report.checks.push({
    name: "console-errors",
    status: consoleErrorCount ? "error" : consoleWarningCount ? "warn" : "ok",
    blocking: true,
    warningCount: consoleWarningCount,
    errorCount: consoleErrorCount,
    messages: report.consoleErrors.slice(0, 10),
  });
  report.checks.push({
    name: "network-errors",
    status: networkErrorCount ? "error" : "ok",
    blocking: true,
    count: networkErrorCount,
    messages: report.networkErrors.slice(0, 10),
  });
  const blockingFailures = report.checks.filter(
    (check) => check.blocking !== false && check.status === "error",
  );
  if (blockingFailures.length || pageErrorCount || consoleErrorCount || networkErrorCount) {
    process.exitCode = 1;
  }
}

let runtime = null;

try {
  runtime = await connect();
  const { page } = runtime;
  const localBuildManifest = await loadLocalBuildManifest();

  await guardedNavigate(page, "root-shell", `${BASE_URL}/`, ".gh-shell-header");
  await screenshot(page, "root-shell");

  const bootstrap = await fetchJson(page, baseUrl("/api/bootstrap?_smoke=1"));
  await pushCheck("bootstrap-endpoint", bootstrap.ok ? "ok" : "error", {
    status: bootstrap.status,
    bootState: bootstrap.json?.bootState || "",
    buildId: bootstrap.json?.shell?.buildId || "",
    timedOut: bootstrap.timedOut,
    error: bootstrap.error || "",
    message: bootstrap.ok ? "" : bootstrap.error || bootstrap.text.slice(0, 400),
  });
  await pushCheck(
    "bootstrap-build-id",
    bootstrap.json?.shell?.buildId === localBuildManifest.buildId ? "ok" : "error",
    {
      expectedBuildId: localBuildManifest.buildId || "",
      observedBuildId: bootstrap.json?.shell?.buildId || "",
    },
  );

  const runtimeStatus = await fetchJson(page, baseUrl("/api/runtime/status?_smoke=1"));
  await pushCheck("runtime-status-endpoint", runtimeStatus.ok ? "ok" : "error", {
    status: runtimeStatus.status,
    runtimeState: runtimeStatus.json?.runtime?.state || "",
    actorRole: runtimeStatus.json?.identity?.actorRole || "",
    actorRoleProvisional: runtimeStatus.json?.identity?.actorRoleProvisional,
    timedOut: runtimeStatus.timedOut,
    error: runtimeStatus.error || "",
    message: runtimeStatus.ok ? "" : runtimeStatus.error || runtimeStatus.text.slice(0, 400),
  });

  await guardedNavigate(
    page,
    "entity-deep-link",
    `${BASE_URL}/?module=discovery&surface=entity&asset=${encodeURIComponent(DEEP_LINK_ASSET)}&_smoke=1`,
    ".gh-entity-record-tabs",
  );
  await screenshot(page, "entity-deep-link");

  finalizeRuntimeChecks();
  await flushReport();
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  await pushCheck("smoke-run", "error", {
    message: error?.message || String(error),
  });
  await flushReport();
  console.error(JSON.stringify(report, null, 2));
  process.exitCode = 1;
} finally {
  try {
    await runtime?.close?.();
  } catch {}
  try {
    await runtime?.context?.close?.();
  } catch {}
  try {
    await runtime?.browser?.close?.();
  } catch {}
}
