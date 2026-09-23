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
  process.env.GOVAT_ADMIN_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/admin-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const MOCKUP_PATH = path.join(REPO_ROOT, "docs/mockups/mock10.png");
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

function adminUrl() {
  return route("/admin");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    Boolean(report.sideBySide?.path) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(path.join(OUT_DIR, "admin-live-report.json"), JSON.stringify(report, null, 2));
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

async function waitForAdmin(page) {
  await page.waitForSelector("[data-testid='admin-northstar']", { timeout: 120_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Administration & Control Center/i.test(text) &&
        /Configure, manage, and extend Governance Atlas/i.test(text) &&
        /Governance Policy Requirements/i.test(text) &&
        /System & Access/i.test(text) &&
        !/Loading admin control center|Preparing workspace shell|Admin Control Center/i.test(text)
      );
    },
    undefined,
    { timeout: 120_000 },
  );
}

async function gotoAdmin(page) {
  await page.goto(adminUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForAdmin(page);
  await page.waitForTimeout(800);
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
      `admin-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
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
      await gotoAdmin(page);
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
    navigationError ? `admin-live-${viewport.name}-failure` : `admin-live-${viewport.name}`,
  );
  const metrics = await page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const box = node.getBoundingClientRect();
      return {
        top: box.top,
        bottom: box.bottom,
        left: box.left,
        right: box.right,
        width: box.width,
        height: box.height,
      };
    };
    const bodyText = document.body?.innerText || "";
    const footer = rect(".ga-shell-footer");
    const shell = rect(".gh-admin-shell");
    const main = document.querySelector(".gh-main");
    const regionText = {
      title: /Administration & Control Center/i.test(bodyText),
      noLegacyTitle: !/Admin Control Center/i.test(bodyText),
      context: /Environment:/i.test(bodyText) && /Role:/i.test(bodyText),
      tabs:
        /Coverage/i.test(bodyText) &&
        /Branding/i.test(bodyText) &&
        /Bulk Import/i.test(bodyText) &&
        /Integrations/i.test(bodyText),
      policy:
        /Governance Policy Requirements/i.test(bodyText) &&
        /Policy Coverage by Domain/i.test(bodyText) &&
        /Compliance Drilldown/i.test(bodyText),
      recentActivity: /Recent Admin Activity/i.test(bodyText) && /View all/i.test(bodyText),
      lowerCards:
        /Brand Settings/i.test(bodyText) &&
        /Validation Summary/i.test(bodyText) &&
        /Integrations & Runtime/i.test(bodyText) &&
        /System & Access/i.test(bodyText),
      truthfulUnavailable:
        /Unavailable/i.test(bodyText) &&
        /No backed import history is available|Import reports are unavailable/i.test(bodyText),
      noRawRuntimeJson:
        !/clientSecretPresent|hostPresent|\\{\\\"authMode\\\"|\"authMode\"|\"clientSecretPresent\"/i.test(bodyText),
    };
    return {
      url: window.location.href,
      title: document.querySelector(".gh-admin-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 5200),
      hasNorthstar: Boolean(document.querySelector("[data-testid='admin-northstar']")),
      loading: /Loading admin control center|Preparing workspace shell/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      mainScrollHeight: main?.scrollHeight || 0,
      mainClientHeight: main?.clientHeight || 0,
      mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
      footer,
      shell,
      policy: rect(".gh-admin-policy"),
      activity: rect(".gh-admin-activity"),
      bottom: rect(".gh-admin-bottom"),
      tabCount: document.querySelectorAll(".gh-admin-tabs button").length,
      policyCardCount: document.querySelectorAll(".gh-admin-policy-card").length,
      lowerCardCount: document.querySelectorAll(".gh-admin-bottom .gh-admin-card").length,
      disabledActionCount: [...document.querySelectorAll(".gh-admin-card button, .gh-admin-compliance button")]
        .filter((button) => button.disabled)
        .length,
      regionText,
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const bottomAboveFooter =
    !metrics.footer || !metrics.shell || metrics.shell.bottom <= metrics.footer.top + 1;
  const footerSafe =
    viewport.height <= 760
      ? bottomAboveFooter || metrics.mainScrolls
      : bottomAboveFooter;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    metrics.title === "Administration & Control Center" &&
    metrics.tabCount === 4 &&
    metrics.policyCardCount === 5 &&
    metrics.lowerCardCount === 4 &&
    metrics.disabledActionCount >= 4 &&
    regionsOk &&
    !metrics.horizontalOverflow &&
    footerSafe;
  report.captures.push({ viewport, screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });

  await recordInteraction(page, "Direct Admin route settled", async () => {
    await gotoAdmin(page);
    return {
      url: page.url(),
      activeTab: await page.locator("[data-testid='admin-northstar']").getAttribute("data-active-admin-tab"),
    };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Admin tabs update local focus", async () => {
    await gotoAdmin(page);
    for (const tab of ["Branding", "Bulk Import", "Integrations", "Coverage"]) {
      await page.getByRole("button", { name: `Admin tab ${tab}` }).click();
      await page.locator(`[data-active-admin-tab='${tab}']`).waitFor({ timeout: 10_000 });
    }
    return { activeTab: "Coverage" };
  });

  await recordInteraction(page, "Recent activity routes to Audit", async () => {
    await gotoAdmin(page);
    await page.getByRole("button", { name: "View all admin activity" }).click();
    await page.waitForFunction(
      () => /\/audit/i.test(window.location.pathname) || /Audit Trail & Change Evidence/i.test(document.body?.innerText || ""),
      undefined,
      { timeout: 90_000 },
    );
    const url = page.url();
    await gotoAdmin(page);
    return { url };
  });

  await recordInteraction(page, "Policy exception action is backed or disabled", async () => {
    await gotoAdmin(page);
    const action = page.getByRole("button", { name: /View Policy Exceptions/ });
    const disabled = await action.isDisabled();
    let url = "";
    if (!disabled) {
      await action.click();
      await page.waitForFunction(
        () => /\/governance/i.test(window.location.pathname) || /Governance Workbench/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 90_000 },
      );
      url = page.url();
    }
    return { disabled, url };
  });

  await recordInteraction(page, "Unavailable admin actions stay disabled", async () => {
    await gotoAdmin(page);
    const actions = [
      "Edit Branding",
      "View Full Report",
      "View all import history",
      "Manage Integrations",
      "Manage Access",
    ];
    const states = {};
    for (const name of actions) {
      const disabled = await page.getByRole("button", { name }).isDisabled();
      states[name] = disabled;
      if (!disabled) throw new Error(`${name} must be disabled until backed.`);
    }
    return states;
  });
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(browser) {
  const currentPath = path.join(OUT_DIR, "admin-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await browser.newPage({ viewport: { width: 3200, height: 1120 } });
  const outputPath = path.join(OUT_DIR, "admin-live-side-by-side-1536x1024.png");
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
                <h1>Reference: docs/mockups/mock10.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current: Admin live 1536x1024</h1>
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
