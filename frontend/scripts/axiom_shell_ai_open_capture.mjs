import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL = process.env.AXIOM_BASE_URL || "http://127.0.0.1:3000";
const OUT_DIR =
  process.env.AXIOM_AI_OPEN_CAPTURE_OUT ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/prototype-ai-open");
const VIEWPORT = {
  width: Number(process.env.AXIOM_AI_OPEN_WIDTH || 1440),
  height: Number(process.env.AXIOM_AI_OPEN_HEIGHT || 900),
};

const BOOTSTRAP_FIXTURE = {
  bootState: "live",
  shell: {
    workspace: { name: "prod" },
    userName: "Marisol Reyes",
    userEmail: "marisol.reyes@shorecp.com",
    role: "Finance Steward",
    diagnosticsEnabled: true,
    ai: {
      state: "available",
      provider: "genie",
      message: "Axiom AI is grounded in governed metadata evidence.",
    },
  },
  discovery: {
    summary: {
      visibleAssets: 1247,
      catalogCount: 6,
      averageCoverage: 87.4,
    },
  },
  governance: {
    inbox: { state: "available", unreadCount: 0, items: [] },
    metrics: [],
    backlog: [],
    glossary: [],
  },
  assets: [
    {
      fqn: "finance_prod.curated.revenue_daily",
      name: "revenue_daily",
      type: "table",
      owner: "Marisol Reyes",
    },
  ],
};

const COMMAND_CENTER_FIXTURE = {
  estate: {
    visibleAssetCount: 1247,
    catalogCount: 6,
    openRequests: 184,
    coverageScore: 87.4,
  },
  kpis: [
    {
      key: "metadataCoverage",
      label: "Metadata Coverage",
      value: 87.4,
      format: "percent",
      deltaText: "+2.1 pts vs last week",
      sparkline: [72, 75, 80, 84, 86, 87.4],
    },
    {
      key: "certifiedCriticalAssets",
      label: "Certified Critical Assets",
      value: 612,
      format: "number",
      deltaText: "+37 this week",
      sparkline: [410, 460, 510, 560, 590, 612],
    },
    {
      key: "openStewardship",
      label: "Open Stewardship Actions",
      value: 184,
      format: "number",
      deltaText: "-11 this week",
      sparkline: [220, 210, 198, 192, 188, 184],
    },
    {
      key: "policyExceptions",
      label: "Policy Exceptions",
      value: 7,
      format: "number",
      deltaText: "+2 new this week",
      sparkline: [3, 4, 4, 5, 6, 7],
    },
  ],
  posture: {
    overall: 87.4,
    trend: [
      { label: "W14", overall: 72 },
      { label: "W16", overall: 79 },
      { label: "W18", overall: 83 },
      { label: "W20", overall: 85 },
      { label: "W22", overall: 86 },
      { label: "W24", overall: 87.4 },
    ],
    byDomain: [
      { domain: "Revenue & Sales", score: 92, count: 138 },
      { domain: "Customer", score: 84, count: 174 },
      { domain: "Marketing", score: 88, count: 89 },
      { domain: "Finance", score: 95, count: 121 },
      { domain: "Operations", score: 79, count: 64 },
      { domain: "People", score: 72, count: 26 },
    ],
  },
  topDomains: [
    { domain: "Revenue & Sales", score: 92, count: 138 },
    { domain: "Customer", score: 84, count: 174 },
    { domain: "Marketing", score: 88, count: 89 },
    { domain: "Finance", score: 95, count: 121 },
    { domain: "Operations", score: 79, count: 64 },
    { domain: "People", score: 72, count: 26 },
  ],
  recentAssets: [
    {
      fqn: "finance_prod.curated.revenue_daily",
      catalog: "finance_prod",
      metadataCoverage: 94,
      classification: "Restricted",
      risk: "Low",
    },
    {
      fqn: "sales_prod.silver.orders",
      catalog: "sales_prod",
      metadataCoverage: 91,
      classification: "Internal",
      risk: "Low",
    },
    {
      fqn: "customer_360.gold.customer_profile",
      catalog: "customer_360",
      metadataCoverage: 82,
      classification: "Confidential",
      risk: "Medium",
    },
  ],
  recentEvents: [
    {
      id: "evt-1",
      title: "certified finance_prod.curated.revenue_daily",
      actor: "Marisol Reyes",
      createdAt: "2026-04-27T08:00:00Z",
      tone: "good",
    },
    {
      id: "evt-2",
      title: "flagged missing owner on pricing_experiment_2025q4",
      actor: "svc-governance-sweeper",
      createdAt: "2026-04-27T07:12:00Z",
      tone: "warn",
    },
  ],
  meta: {
    state: "available",
    generatedAt: "2026-04-27T08:00:00Z",
    warnings: [],
  },
};

function routeUrl(pathname) {
  return new URL(pathname, BASE_URL).toString();
}

function jsonResponse(payload) {
  return {
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(payload),
    headers: { "x-axiom-build-id": "local-ai-open-fixture" },
  };
}

async function installFixtureRoutes(page) {
  await page.route("**/api/**", (route) =>
    route.fulfill(jsonResponse({ meta: { state: "local-fixture", warnings: [] } })),
  );
  await page.route("**/api/bootstrap**", (route) => route.fulfill(jsonResponse(BOOTSTRAP_FIXTURE)));
  await page.route("**/api/runtime/status**", (route) =>
    route.fulfill(jsonResponse({
      state: "live",
      store: "fixture",
      runtime: "local",
      ai: BOOTSTRAP_FIXTURE.shell.ai,
    })),
  );
  await page.route("**/api/axiom/command-center**", (route) =>
    route.fulfill(jsonResponse(COMMAND_CENTER_FIXTURE)),
  );
  await page.route("**/api/axiom-ai/recommendations**", async (route) => {
    const request = route.request();
    const body = request.postDataJSON?.() || {};
    const question = String(body.question || "metadata posture").trim();
    await route.fulfill(jsonResponse({
      answer: `Axiom AI found governed evidence for "${question}". The strongest signals are certified assets, open stewardship work, and catalog coverage.`,
      evidence: [
        {
          type: "governance_metadata",
          id: "local-ai-open-fixture",
          title: "Local Axiom AI open-state fixture",
        },
      ],
      meta: { source: "local-fixture" },
    }));
  });
}

async function metrics(page) {
  return page.evaluate(() => {
    const rect = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const box = node.getBoundingClientRect();
      return {
        top: box.top,
        left: box.left,
        right: box.right,
        bottom: box.bottom,
        width: box.width,
        height: box.height,
      };
    };
    const styles = (selector) => {
      const node = document.querySelector(selector);
      if (!node) return null;
      const computed = window.getComputedStyle(node);
      return {
        width: computed.width,
        minWidth: computed.minWidth,
        gridTemplateColumns: computed.gridTemplateColumns,
        justifyContent: computed.justifyContent,
        justifyItems: computed.justifyItems,
        justifySelf: computed.justifySelf,
        alignSelf: computed.alignSelf,
        marginLeft: computed.marginLeft,
        marginRight: computed.marginRight,
        paddingLeft: computed.paddingLeft,
        paddingRight: computed.paddingRight,
        boxSizing: computed.boxSizing,
        direction: computed.direction,
        writingMode: computed.writingMode,
        overflow: computed.overflow,
        overflowX: computed.overflowX,
        transform: computed.transform,
        left: computed.left,
        position: computed.position,
        gridColumn: computed.gridColumn,
      };
    };
    const railNavFirst = document.querySelector(".ax-side-nav-item");
    const railNavFirstLabel = railNavFirst?.querySelector("span:nth-child(2)");
    return {
      url: window.location.href,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      rail: {
        html: rect("html"),
        body: rect("body"),
        root: rect("#root"),
        app: rect(".gh-app"),
        sideNav: rect(".ax-side-nav"),
        logo: rect(".ax-side-nav-logo"),
        logoImage: rect(".ax-side-nav-logo img"),
        logoText: rect(".ax-side-nav-logo span"),
        firstNavItem: rect(".ax-side-nav-item"),
        firstNavIcon: rect(".ax-side-nav-item .ax-side-nav-icon"),
        firstNavLabel: railNavFirstLabel
          ? {
              top: railNavFirstLabel.getBoundingClientRect().top,
              left: railNavFirstLabel.getBoundingClientRect().left,
              right: railNavFirstLabel.getBoundingClientRect().right,
              bottom: railNavFirstLabel.getBoundingClientRect().bottom,
              width: railNavFirstLabel.getBoundingClientRect().width,
              height: railNavFirstLabel.getBoundingClientRect().height,
              text: railNavFirstLabel.textContent,
            }
          : null,
        styles: {
          app: styles(".gh-app"),
          html: styles("html"),
          body: styles("body"),
          root: styles("#root"),
          sideNav: styles(".ax-side-nav"),
          logo: styles(".ax-side-nav-logo"),
        },
      },
      aiDialog: rect(".gh-floating-ai-chat"),
      aiFab: rect(".gh-axiom-ai-fab"),
      main: rect(".gh-main"),
      home: rect(".gh-home-page"),
      scroll: {
        windowX: window.scrollX,
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        mainScrollLeft: document.querySelector(".gh-main")?.scrollLeft || 0,
        mainScrollWidth: document.querySelector(".gh-main")?.scrollWidth || 0,
        mainClientWidth: document.querySelector(".gh-main")?.clientWidth || 0,
        appScrollLeft: document.querySelector(".gh-app")?.scrollLeft || 0,
        appScrollWidth: document.querySelector(".gh-app")?.scrollWidth || 0,
        appClientWidth: document.querySelector(".gh-app")?.clientWidth || 0,
      },
      textPreview: document.body.innerText.replace(/\s+/g, " ").trim().slice(0, 1600),
      hasOpenDialog: Boolean(document.querySelector(".gh-floating-ai-chat")),
      axiomButtonDisabled: Boolean(document.querySelector(".ax-ai-chip")?.disabled),
    };
  });
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    outDir: OUT_DIR,
    viewport: VIEWPORT,
    fixture: "local-bootstrap-and-api",
    console: [],
    pageErrors: [],
    requestFailures: [],
  };
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    const text = message.text();
    if (/ResizeObserver loop|React Router Future Flag Warning/i.test(text)) return;
    report.console.push({ type: message.type(), text, url: page.url() });
  });
  page.on("pageerror", (error) => {
    report.pageErrors.push({ message: error?.message || String(error), stack: error?.stack || "" });
  });
  page.on("requestfailed", (request) => {
    const failureText = request.failure()?.errorText || "failed";
    if (failureText === "net::ERR_ABORTED") return;
    report.requestFailures.push({
      method: request.method(),
      url: request.url(),
      failureText,
    });
  });
  await installFixtureRoutes(page);
  await page.addInitScript((bootstrap) => {
    window.__AXIOM_BOOTSTRAP__ = bootstrap;
  }, BOOTSTRAP_FIXTURE);

  await page.goto(routeUrl("/command-center"), { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".gh-home-page", { timeout: 20_000 });
  await page.locator(".ax-ai-chip").click();
  await page.waitForSelector(".gh-floating-ai-chat", { timeout: 5_000 });
  await page.screenshot({
    path: path.join(OUT_DIR, "axiom-ai-open-1440x900.png"),
    fullPage: false,
  });
  report.metrics = await metrics(page);
  report.passed =
    report.metrics.hasOpenDialog &&
    !report.metrics.axiomButtonDisabled &&
    report.metrics.rail?.sideNav?.left >= 0 &&
    report.metrics.rail?.sideNav?.right <= report.metrics.viewport.width &&
    report.metrics.rail?.logoImage?.left >= 0 &&
    report.metrics.rail?.firstNavIcon?.left >= 0 &&
    report.metrics.rail?.firstNavLabel?.left >= 0 &&
    report.metrics.home?.right <= report.metrics.aiDialog?.left &&
    report.metrics.scroll.windowX === 0 &&
    report.metrics.scroll.mainScrollLeft === 0 &&
    report.metrics.scroll.appScrollLeft === 0 &&
    report.pageErrors.length === 0 &&
    report.requestFailures.length === 0;
  await fs.writeFile(path.join(OUT_DIR, "axiom-ai-open-report.json"), JSON.stringify(report, null, 2));
  await context.close().catch(() => {});
  await browser.close().catch(() => {});
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
