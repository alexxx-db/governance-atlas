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
  process.env.GOVAT_GOVERNANCE_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/governance-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
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
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function governanceUrl() {
  return route("/governance");
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(
    path.join(OUT_DIR, "governance-live-report.json"),
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
    report.consoleWarnings.push({
      type: message.type(),
      text: message.text(),
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

async function waitForGovernance(page, detailResponse = Promise.resolve(null)) {
  await page.waitForSelector("[data-testid='governance-northstar-workbench']", {
    timeout: 90_000,
  });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Stewardship Workbench/i.test(text) &&
        /Open Governance Requests/i.test(text) &&
        !/Loading governance requests/i.test(text)
      );
    },
    undefined,
    { timeout: 90_000 },
  );
  await detailResponse;
  await page.waitForFunction(
    () => document.querySelectorAll(".gh-governance-ns-flow-step").length >= 2,
    undefined,
    { timeout: 30_000 },
  ).catch(() => {});
}

async function gotoGovernance(page) {
  const detailResponse = page.waitForResponse(
    (response) => response.url().includes("/api/atlas/governance/requests/") && response.status() === 200,
    { timeout: 90_000 },
  ).catch(() => null);
  await page.goto(governanceUrl(), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForGovernance(page, detailResponse);
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
      `governance-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
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
      await gotoGovernance(page);
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
    navigationError
      ? `governance-live-${viewport.name}-failure`
      : `governance-live-${viewport.name}`,
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
    const tableRows = [...document.querySelectorAll(".gh-governance-ns-table button[role='row']")];
    const actionButtons = ["Approve", "Request Changes", "Escalate", "More Actions"].map((label) => {
      const button = [...document.querySelectorAll(".gh-governance-ns-actions button")].find(
        (node) => node.textContent?.trim() === label,
      );
      return { label, present: Boolean(button), enabled: Boolean(button && !button.disabled) };
    });
    return {
      url: window.location.href,
      title: document.querySelector(".gh-governance-ns-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 3600),
      hasNorthstar: Boolean(document.querySelector("[data-testid='governance-northstar-workbench']")),
      loading: /Loading governance requests/i.test(bodyText),
      degraded: /Governance workbench degraded/i.test(bodyText),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      scrollHeight: document.documentElement.scrollHeight,
      viewportHeight: window.innerHeight,
      footer: rect(".ga-shell-footer"),
      workbench: rect("[data-testid='governance-northstar-workbench']"),
      hero: rect(".gh-governance-ns-hero"),
      kpis: rect(".gh-governance-ns-kpis"),
      requests: rect(".gh-governance-ns-requests"),
      detail: rect(".gh-governance-ns-detail"),
      tableRowCount: tableRows.length,
      actionButtons,
      regionText: {
        title: /Stewardship Workbench/i.test(bodyText),
        settings: /Workbench Settings/i.test(bodyText),
        kpis:
          /Pending Approvals/i.test(bodyText) &&
          /Overdue Items/i.test(bodyText) &&
          /Policy Exceptions/i.test(bodyText) &&
          /SLA Performance/i.test(bodyText),
        openRequests: /Open Governance Requests/i.test(bodyText),
        metadataChanges: /Metadata Changes/i.test(bodyText),
        businessContext: /Business Context/i.test(bodyText),
        assetImpact: /Asset Impact/i.test(bodyText),
        approverFlow: /Approver Flow/i.test(bodyText),
        actions:
          /Approve/i.test(bodyText) &&
          /Request Changes/i.test(bodyText) &&
          /Escalate/i.test(bodyText) &&
          /More Actions/i.test(bodyText),
      },
    };
  });
  const regionsOk = Object.values(metrics.regionText).every(Boolean);
  const actionButtonsOk = metrics.actionButtons.every((button) => button.present && button.enabled);
  const bottomAboveFooter =
    !metrics.footer || !metrics.workbench || metrics.workbench.bottom <= metrics.footer.top + 1;
  const passed =
    !navigationError &&
    metrics.hasNorthstar &&
    !metrics.loading &&
    !metrics.degraded &&
    !metrics.horizontalOverflow &&
    metrics.tableRowCount > 0 &&
    regionsOk &&
    actionButtonsOk &&
    bottomAboveFooter;
  report.captures.push({ viewport, screenshot: screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function firstRequestRow(page) {
  const row = page.locator(".gh-governance-ns-table button[role='row']").first();
  await row.waitFor({ state: "visible", timeout: 45_000 });
  return row;
}

async function secondRequestRow(page) {
  const rows = page.locator(".gh-governance-ns-table button[role='row']");
  const count = await rows.count();
  if (count < 2) return rows.first();
  return rows.nth(1);
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });
  await recordInteraction(page, "Direct Governance route settled", async () => {
    await gotoGovernance(page);
    return { url: page.url() };
  });
  if (!report.interactions[report.interactions.length - 1]?.passed) return;

  await recordInteraction(page, "Workbench settings toggle", async () => {
    await page.getByRole("button", { name: "Workbench Settings" }).click();
    await page.waitForSelector("text=/Live Governance Atlas requests are shown/i", { timeout: 6000 });
    await page.getByRole("button", { name: "Workbench Settings" }).click();
  });

  await recordInteraction(page, "Type filter menu", async () => {
    await page.getByRole("button", { name: "All Types" }).click();
    await page.getByRole("menuitem", { name: "Policy" }).click();
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: "Policy" }).click();
    await page.getByRole("menuitem", { name: "All Types" }).click();
  });

  await recordInteraction(page, "Sort menu", async () => {
    await page.getByRole("button", { name: /Sort: Due Soonest|Sort: Newest|Sort: High Priority/ }).click();
    await page.getByRole("menuitem", { name: "Newest" }).click();
    await page.waitForSelector("button:has-text('Sort: Newest')", { timeout: 6000 });
  });

  await recordInteraction(page, "Filter icon toggles request type", async () => {
    await page.getByRole("button", { name: "Filter requests" }).click();
    await page.waitForSelector("button:has-text('Policy')", { timeout: 6000 });
    await page.getByRole("button", { name: "Filter requests" }).click();
    await page.waitForSelector("button:has-text('All Types')", { timeout: 6000 });
  });

  await recordInteraction(page, "Request row selection", async () => {
    await (await secondRequestRow(page)).click();
    await page.waitForSelector(".gh-governance-ns-detail h2", { timeout: 6000 });
    const detailTitle = await page.locator(".gh-governance-ns-detail h2").first().textContent();
    return { detailTitle: String(detailTitle || "").trim() };
  });

  const detailTabs = [
    { label: "Approver Flow", locator: "Approver Flow" },
    {
      label: "Comments",
      locator: /^Comments (0|—)$/,
      unavailableMessage: /Comment thread evidence is unavailable/i,
    },
    {
      label: "Evidence",
      locator: /^Evidence (0|—)$/,
      unavailableMessage: /Evidence attachments are unavailable/i,
    },
    { label: "History", locator: "History" },
    { label: "Details", locator: "Details" },
  ];
  for (const tab of detailTabs) {
    await recordInteraction(page, `Detail tab ${tab.label}`, async () => {
      const tabControl = page.getByRole("tab", { name: tab.locator });
      const tabLabel = String((await tabControl.textContent()) || "").trim();
      await tabControl.click();
      if (tab.unavailableMessage && tabLabel.includes("—")) {
        await page.getByText(tab.unavailableMessage).waitFor({ timeout: 6000 });
      }
      return { tabLabel };
    });
  }

  await recordInteraction(page, "Escalate action", async () => {
    await page.getByRole("button", { name: "Escalate" }).click();
    await page.waitForSelector("text=/Escalation noted/i", { timeout: 6000 });
  });

  await recordInteraction(page, "Mutating actions remain available", async () => {
    const approveEnabled = await page.getByRole("button", { name: "Approve" }).isEnabled();
    const requestChangesEnabled = await page.getByRole("button", { name: "Request Changes" }).isEnabled();
    if (!approveEnabled || !requestChangesEnabled) {
      throw new Error("Approve and Request Changes must be enabled for real selected requests.");
    }
    return {
      approveEnabled,
      requestChangesEnabled,
      note: "Live click intentionally skipped to preserve governance request state; focused React tests cover updateGovernanceRequest payloads.",
    };
  });

  await recordInteraction(page, "More Actions menu", async () => {
    await page.getByRole("button", { name: "More Actions" }).click();
    await page.getByRole("menuitem", { name: "Open Lineage" }).waitFor({ state: "visible", timeout: 6000 });
  });

  await recordInteraction(page, "Governance to Glossary workbench action", async () => {
    await page.getByRole("menuitem", { name: "Open Glossary Workbench" }).click();
    await page.waitForSelector("text=/Glossary workbench/i", { timeout: 45_000 });
    await page.waitForSelector("text=/Term detail/i", { timeout: 45_000 });
    await page.waitForSelector("text=/Selected term/i", { timeout: 45_000 });
    const termTitle = String(
      (await page.locator(".gh-governance-focus-header h2").first().textContent()) || "",
    ).trim();
    if (!termTitle) throw new Error("Glossary workbench opened but did not expose a hydrated term title.");
    return {
      url: page.url(),
      termTitle,
      selectedTermHydrated: true,
    };
  });

  await recordInteraction(page, "Governance to Lineage action", async () => {
    await gotoGovernance(page);
    await page.getByRole("button", { name: "More Actions" }).click();
    await page.getByRole("menuitem", { name: "Open Lineage" }).waitFor({ state: "visible", timeout: 6000 });
    await page.getByRole("menuitem", { name: "Open Lineage" }).click();
    await page.waitForSelector("[data-testid='lineage-northstar-explorer']", { timeout: 90_000 });
    return { url: page.url() };
  });

  await recordInteraction(page, "Governance to Asset 360 action", async () => {
    await gotoGovernance(page);
    await firstRequestRow(page);
    await page.getByRole("button", { name: /View asset context/i }).click();
    await page.waitForSelector(".gh-entity-workspace", { timeout: 90_000 });
    return { url: page.url() };
  });

  await recordInteraction(page, "Close request detail", async () => {
    await gotoGovernance(page);
    await page.getByRole("button", { name: "Close request detail" }).click();
    await page.waitForSelector("text=/Select a governance request to review metadata changes/i", {
      timeout: 6000,
    });
  });
}

const { page, close } = await connect();
try {
  await fs.mkdir(OUT_DIR, { recursive: true });
  for (const viewport of VIEWPORTS) {
    await captureViewport(page, viewport);
  }
  await runInteractions(page);
  await flushReport();
} finally {
  await close?.();
}

if (!report.passed) {
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
}

console.log(JSON.stringify(report, null, 2));
