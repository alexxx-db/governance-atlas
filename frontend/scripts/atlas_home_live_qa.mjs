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
  process.env.GOVAT_HOME_OUT_DIR ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/home-current");
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const MOCKUP_PATH = path.join(REPO_ROOT, "docs/mockups/mock1.png");
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
  atlasAiResponses: [],
  pageErrors: [],
  consoleWarnings: [],
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  report.passed =
    report.captures.every((capture) => capture.passed) &&
    report.interactions.every((interaction) => interaction.passed) &&
    Boolean(report.sideBySide?.path) &&
    report.pageErrors.length === 0 &&
    report.consoleWarnings.length === 0;
  await fs.writeFile(path.join(OUT_DIR, "home-live-report.json"), JSON.stringify(report, null, 2));
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
  page.on("response", async (response) => {
    const url = response.url();
    if (!url.includes("/api/atlas-ai/recommendations")) return;
    try {
      const payload = await response.json();
      report.atlasAiResponses.push({
        status: response.status(),
        provider: payload?.meta?.capabilities?.provider || payload?.provider || "",
        confidence: payload?.confidence || "",
        evidenceCount: Array.isArray(payload?.evidence) ? payload.evidence.length : 0,
        source: payload?.meta?.source || "",
        state: payload?.meta?.state || "",
        warnings: payload?.meta?.warnings || payload?.warnings || [],
      });
      await flushReport();
    } catch {
      // Ignore non-JSON failed reads; interaction checks will catch failures.
    }
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

async function waitForHome(page) {
  await page.waitForSelector(".gh-home-page", { timeout: 240_000 });
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return (
        /Enterprise Governance Command Center/i.test(text) &&
        /Unified visibility\. Trusted data\. Confident decisions\./i.test(text) &&
        /Ask Atlas AI/i.test(text) &&
        /Open Stewardship Actions[\s\S]*?\b5\b/i.test(text) &&
        /Policy Exceptions[\s\S]*?\b4\b/i.test(text) &&
        /Product[\s\S]*?96%/i.test(text) &&
        /Policy Exception Detected/i.test(text) &&
        !/Loading command center|Preparing workspace shell|Loading home|Hydrating live Unity Catalog command center/i.test(text)
      );
    },
    undefined,
    { timeout: 240_000 },
  );
  await page.waitForTimeout(900);
}

async function gotoHome(page) {
  await page.goto(route("/home"), { waitUntil: "domcontentloaded", timeout: 90_000 });
  await waitForHome(page);
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
      `home-live-failure-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
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
      await gotoHome(page);
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
    navigationError ? `home-live-${viewport.name}-failure` : `home-live-${viewport.name}`,
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
    const textFits = (selector) => {
      const node = document.querySelector(selector);
      return !node || node.scrollWidth <= node.clientWidth + 1;
    };
    const bodyText = document.body?.innerText || "";
    const footer = rect(".ga-shell-footer");
    const home = rect(".gh-home-page");
    const main = document.querySelector(".gh-main");
    const copyright = rect(".ga-shell-footer-copyright");
    const atlasRail = rect(".ga-atlas-ai-panel");
    const bottomCards = [
      rect(".gh-home-top-domains"),
      rect(".gh-home-events"),
      rect(".gh-home-actions"),
    ].filter(Boolean);
    const bottomAlignmentDelta = atlasRail && bottomCards.length
      ? Math.max(...bottomCards.map((card) => Math.abs(card.bottom - atlasRail.bottom)))
      : null;
    const logo = document.querySelector(".ga-side-nav-logo img");
    const globeCanvas = document.querySelector(".gh-home-globe canvas");
    let globePixelCoverage = 0;
    if (globeCanvas instanceof HTMLCanvasElement) {
      try {
        const ctx = globeCanvas.getContext("2d");
        if (ctx && globeCanvas.width > 0 && globeCanvas.height > 0) {
          const sampleWidth = Math.min(180, globeCanvas.width);
          const sampleHeight = Math.min(90, globeCanvas.height);
          const data = ctx.getImageData(
            Math.max(0, Math.floor((globeCanvas.width - sampleWidth) / 2)),
            Math.max(0, Math.floor((globeCanvas.height - sampleHeight) / 2)),
            sampleWidth,
            sampleHeight,
          ).data;
          let lit = 0;
          for (let index = 3; index < data.length; index += 4) {
            if (data[index] > 4) lit += 1;
          }
          globePixelCoverage = sampleWidth && sampleHeight
            ? lit / (sampleWidth * sampleHeight)
            : 0;
        }
      } catch {
        globePixelCoverage = 0;
      }
    }
    const regionText = {
      title: /Enterprise Governance Command Center/i.test(bodyText),
      subtitle: /Unified visibility\. Trusted data\. Confident decisions\./i.test(bodyText),
      kpis:
        /Governed Assets/i.test(bodyText) &&
        /Certified Critical Assets/i.test(bodyText) &&
        /Metadata Coverage/i.test(bodyText) &&
        /Open Stewardship Actions/i.test(bodyText) &&
        /Policy Exceptions/i.test(bodyText) &&
        /Audit Readiness/i.test(bodyText),
      charts:
        /Governance Posture Over Time/i.test(bodyText) &&
        /Posture by Domain/i.test(bodyText) &&
        /Top Domains/i.test(bodyText),
      eventsAndActions:
        /Recent High-Priority Events/i.test(bodyText) &&
        /Quick Actions/i.test(bodyText) &&
        /Browse Discovery/i.test(bodyText) &&
        /Audit Trail/i.test(bodyText),
      ai:
        /Ask Atlas AI/i.test(bodyText) &&
        /Ask a question\.\.\./i.test(document.querySelector(".gh-home-ai-input input")?.placeholder || "") &&
        /Atlas AI uses AI\. Review for accuracy\./i.test(bodyText),
      footer:
        /© 2026 Entrada\. All rights reserved\./i.test(bodyText) &&
        /Privacy/i.test(bodyText) &&
        /Terms/i.test(bodyText) &&
        /Support/i.test(bodyText) &&
        /System Status/i.test(bodyText),
    };
    const headerTextFits = {
      topDomains: textFits(".gh-home-top-domains .ga-section-card-header h2 > span"),
      recentEvents: textFits(".gh-home-events .ga-section-card-header h2 > span"),
      quickActions: textFits(".gh-home-actions .ga-section-card-header h2 > span"),
    };
    const footerSafe = !footer || !home || home.bottom <= footer.top + 1;
    return {
      url: window.location.href,
      title: document.querySelector(".gh-home-hero h1")?.textContent?.trim() || "",
      bodyStart: bodyText.slice(0, 5200),
      kpiCount: document.querySelectorAll(".gh-home-kpi").length,
      actionTileCount: document.querySelectorAll(".gh-home-action-tile").length,
      promptCount: document.querySelectorAll(".ga-ai-prompts button").length,
      actualLogoLoaded:
        Boolean(logo?.src?.includes("entrada-2026-logo")) &&
        (logo?.naturalWidth || 0) >= 1200 &&
        (logo?.naturalHeight || 0) >= 120,
      globeCanvasPresent: globeCanvas instanceof HTMLCanvasElement,
      globeCanvasWidth: globeCanvas?.width || 0,
      globeCanvasHeight: globeCanvas?.height || 0,
      globePixelCoverage,
      atlasAiMarkDots: document.querySelectorAll(".ga-ai-mark circle").length,
      bottomAlignmentDelta,
      footer,
      home,
      copyright,
      copyrightSingleLine: !copyright || copyright.height <= 24,
      mainScrollHeight: main?.scrollHeight || 0,
      mainClientHeight: main?.clientHeight || 0,
      mainScrolls: main ? main.scrollHeight > main.clientHeight + 2 : false,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 2,
      footerSafe,
      regionText,
      headerTextFits,
    };
  });
  const passed =
    !navigationError &&
    metrics.title === "Enterprise Governance Command Center" &&
    metrics.kpiCount === 6 &&
    metrics.actionTileCount === 6 &&
    metrics.promptCount >= 4 &&
    metrics.actualLogoLoaded &&
    metrics.globeCanvasPresent &&
    metrics.globeCanvasWidth >= 400 &&
    metrics.globeCanvasHeight >= 140 &&
    metrics.globePixelCoverage > 0.01 &&
    metrics.atlasAiMarkDots >= 2 &&
    typeof metrics.bottomAlignmentDelta === "number" &&
    metrics.bottomAlignmentDelta <= 3 &&
    metrics.copyrightSingleLine &&
    metrics.footerSafe &&
    !metrics.mainScrolls &&
    !metrics.horizontalOverflow &&
    Object.values(metrics.headerTextFits).every(Boolean) &&
    Object.values(metrics.regionText).every(Boolean);
  report.captures.push({ viewport, screenshotPath, metrics, navigationError, passed });
  await flushReport();
}

async function runInteractions(page) {
  await page.setViewportSize({ width: 1536, height: 1024 });

  await recordInteraction(page, "Direct Home route settled", async () => {
    await gotoHome(page);
    return { url: page.url(), title: await page.title() };
  });

  await recordInteraction(page, "Collapse centers navigation icons", async () => {
    await gotoHome(page);
    const collapseButton = page.getByRole("button", { name: "Collapse navigation" });
    await collapseButton.click();
    await page.locator(".gh-app[data-rail-collapsed='true']").waitFor({ timeout: 10_000 });
    const metrics = await page.evaluate(() => {
      const rail = document.querySelector(".ga-side-nav");
      const railBox = rail?.getBoundingClientRect();
      const railCenter = railBox ? railBox.left + railBox.width / 2 : 0;
      const icons = [...document.querySelectorAll(".ga-side-nav-icon")].map((icon) => {
        const box = icon.getBoundingClientRect();
        return {
          center: box.left + box.width / 2,
          delta: Math.abs((box.left + box.width / 2) - railCenter),
        };
      });
      const collapse = document.querySelector(".ga-side-nav-collapse")?.getBoundingClientRect();
      const footer = document.querySelector(".ga-shell-footer")?.getBoundingClientRect();
      return {
        railCenter,
        maxIconDelta: Math.max(...icons.map((icon) => icon.delta)),
        collapseBottom: collapse?.bottom || 0,
        footerTop: footer?.top || 0,
      };
    });
    if (metrics.maxIconDelta > 4) {
      throw new Error(`Collapsed rail icons are not centered; max delta ${metrics.maxIconDelta}`);
    }
    await screenshot(page, "home-live-collapsed-1536x1024");
    await page.getByRole("button", { name: "Expand navigation" }).click();
    await page.locator(".gh-app[data-rail-collapsed='false']").waitFor({ timeout: 10_000 });
    return metrics;
  });

  await recordInteraction(page, "Header AI Copilot opens draggable floating chat", async () => {
    await gotoHome(page);
    const startUrl = page.url();
    await page.getByRole("button", { name: "AI Copilot" }).click();
    const dialog = page.getByRole("dialog", { name: "Atlas AI Copilot" });
    await dialog.waitFor({ timeout: 10_000 });
    const initialCount = await page.locator(".gh-floating-ai-chat").count();
    const before = await dialog.boundingBox();
    const header = dialog.locator(".gh-floating-ai-header");
    const headerBox = await header.boundingBox();
    if (!before || !headerBox) throw new Error("Floating Atlas AI dialog did not expose drag bounds.");
    await page.mouse.move(headerBox.x + 72, headerBox.y + headerBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(headerBox.x + 138, headerBox.y + headerBox.height / 2 + 42, { steps: 8 });
    await page.mouse.up();
    const after = await dialog.boundingBox();
    if (!after) throw new Error("Floating Atlas AI dialog disappeared after drag.");
    const dragDelta = Math.abs(after.x - before.x) + Math.abs(after.y - before.y);
    if (dragDelta < 20) throw new Error(`Floating Atlas AI dialog did not move enough during drag: ${dragDelta}`);
    if (after.x < 0 || after.y < 0) throw new Error("Floating Atlas AI dialog moved out of viewport.");

    const responsePromise = page.waitForResponse(
      (response) => response.url().includes("/api/atlas-ai/recommendations") && response.request().method() === "POST",
      { timeout: 120_000 },
    );
    await dialog.locator(".gh-floating-ai-input input").fill("What changed in governance metadata recently?");
    await dialog.locator(".gh-floating-ai-input button").click();
    await dialog.locator(".gh-floating-ai-spinner").waitFor({ timeout: 10_000 });
    const response = await responsePromise;
    const payload = await response.json();
    await dialog.locator(".gh-floating-ai-message.tone-assistant:not(.is-pending)").last().waitFor({ timeout: 120_000 });
    await screenshot(page, "home-live-floating-ai-1536x1024");
    const provider = payload?.meta?.capabilities?.provider || payload?.provider || "";
    const evidenceCount = Array.isArray(payload?.evidence) ? payload.evidence.length : 0;
    if (response.status() >= 400) throw new Error(`Floating Atlas AI returned HTTP ${response.status()}`);
    if (provider !== "genie") throw new Error(`Floating Atlas AI provider was ${provider || "missing"}, expected genie`);
    if (evidenceCount < 1) throw new Error("Floating Atlas AI returned no evidence records.");

    await page.getByRole("button", { name: "Close Atlas AI Copilot" }).click();
    await page.locator(".gh-floating-ai-chat").waitFor({ state: "detached", timeout: 10_000 });
    await page.getByRole("button", { name: "AI Copilot" }).click();
    await dialog.waitFor({ timeout: 10_000 });
    const reopenedCount = await page.locator(".gh-floating-ai-chat").count();
    if (initialCount !== 1 || reopenedCount !== 1) {
      throw new Error(`Expected a single floating Atlas AI window; saw ${initialCount} then ${reopenedCount}`);
    }
    const resizeMode = await dialog.evaluate((node) => getComputedStyle(node).resize);
    if (resizeMode !== "both") {
      throw new Error(`Floating Atlas AI dialog is not corner-resizable; resize=${resizeMode}`);
    }
    const resizeBefore = await dialog.boundingBox();
    if (!resizeBefore) throw new Error("Floating Atlas AI dialog did not expose resize bounds.");
    await page.mouse.move(resizeBefore.x + resizeBefore.width - 3, resizeBefore.y + resizeBefore.height - 3);
    await page.mouse.down();
    await page.mouse.move(
      resizeBefore.x + resizeBefore.width + 96,
      resizeBefore.y + resizeBefore.height + 74,
      { steps: 10 },
    );
    await page.mouse.up();
    await page.waitForTimeout(350);
    const resizeAfter = await dialog.boundingBox();
    if (!resizeAfter) throw new Error("Floating Atlas AI dialog disappeared after resize.");
    const resizeDelta =
      Math.max(0, resizeAfter.width - resizeBefore.width) +
      Math.max(0, resizeAfter.height - resizeBefore.height);
    if (resizeDelta < 24) {
      throw new Error(`Floating Atlas AI dialog did not resize enough; delta ${resizeDelta}`);
    }
    const viewport = page.viewportSize();
    if (
      resizeAfter.x < -1 ||
      resizeAfter.y < -1 ||
      resizeAfter.x + resizeAfter.width > viewport.width + 1 ||
      resizeAfter.y + resizeAfter.height > viewport.height + 1
    ) {
      throw new Error(`Floating Atlas AI dialog resized outside viewport: ${JSON.stringify(resizeAfter)}`);
    }
    await page.getByRole("button", { name: "Close Atlas AI Copilot" }).click();
    await page.locator(".gh-floating-ai-chat").waitFor({ state: "detached", timeout: 10_000 });
    return {
      url: page.url(),
      stayedOnHome: page.url() === startUrl,
      initialCount,
      reopenedCount,
      dragDelta,
      resizeMode,
      resizeDelta,
      resizeBefore,
      resizeAfter,
      status: response.status(),
      provider,
      evidenceCount,
    };
  });

  await recordInteraction(page, "Home View all buttons route to backed surfaces", async () => {
    const routes = [];
    for (const [label, destination] of [
      ["Posture by Domain", /\/insights/i],
      ["Top Domains", /\/insights/i],
      ["Recent High-Priority Events", /\/audit/i],
    ]) {
      await gotoHome(page);
      const section = page.locator(".ga-section-card", { hasText: label }).first();
      await section.getByRole("button", { name: "View all" }).click();
      await page.waitForFunction(
        (pattern) => new RegExp(pattern, "i").test(window.location.pathname),
        destination.source,
        { timeout: 90_000 },
      );
      routes.push({ label, url: page.url() });
    }
    return { routes };
  });

  await recordInteraction(page, "Home quick actions route to operational pages", async () => {
    const checks = [
      ["Browse Discovery", /\/discovery/i],
      ["Review Queue", /\/governance/i],
      ["Review Quality", /\/insights/i],
      ["Access Reviews", /\/governance/i],
      ["Open Glossary", /\/taxonomy/i],
      ["Audit Trail", /\/audit/i],
    ];
    const routes = [];
    for (const [label, pattern] of checks) {
      await gotoHome(page);
      await page.getByRole("button", { name: new RegExp(label, "i") }).click();
      await page.waitForFunction(
        (patternSource) => new RegExp(patternSource, "i").test(window.location.pathname),
        pattern.source,
        { timeout: 90_000 },
      );
      routes.push({ label, url: page.url() });
    }
    return { routes };
  });

  await recordInteraction(page, "Footer links route to backed help/status surfaces", async () => {
    const routes = [];
    for (const [label, expected] of [
      ["Privacy", { path: /\/help/i, hash: "#privacy" }],
      ["Terms", { path: /\/help/i, hash: "#terms" }],
      ["Support", { path: /\/help/i, hash: "#support" }],
      ["System Status", { path: /\/capabilities/i, hash: "" }],
    ]) {
      await gotoHome(page);
      const button = label === "System Status"
        ? page.getByRole("button", { name: /System Status/i })
        : page.getByRole("button", { name: label, exact: true });
      await button.click();
      await page.waitForFunction(
        ({ source, hash }) => {
          const pathOk = new RegExp(source, "i").test(window.location.pathname);
          const hashOk = hash ? window.location.hash === hash : true;
          return pathOk && hashOk;
        },
        { source: expected.path.source, hash: expected.hash },
        { timeout: 90_000 },
      );
      routes.push({ label, url: page.url() });
    }
    return { routes };
  });

  await recordInteraction(page, "Profile menu exposes avatar upload", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoHome(page);
    await page.getByRole("button", { name: /Open profile menu/i }).click();
    await page.getByRole("menuitem", { name: "Upload avatar" }).waitFor({ timeout: 10_000 });
    await screenshot(page, "home-live-profile-menu-1440x900");
    return {
      uploadVisible: await page.getByRole("menuitem", { name: "Upload avatar" }).isVisible(),
    };
  });

  await recordInteraction(page, "Atlas AI prompt returns Genie-grounded evidence", async () => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await gotoHome(page);
    await page.getByRole("button", { name: "More suggestions" }).click();
    const cycledPrompt = await page.locator(".ga-ai-prompts button").first().innerText();
    const responsePromise = page.waitForResponse(
      (response) => response.url().includes("/api/atlas-ai/recommendations") && response.request().method() === "POST",
      { timeout: 120_000 },
    );
    await page.locator(".ga-ai-prompts button").first().click();
    const response = await responsePromise;
    const payload = await response.json();
    await page.waitForFunction(
      () => [...document.querySelectorAll(".gh-home-ai-message.tone-assistant .gh-ai-message-markdown")]
        .some((node) => {
          const text = (node.textContent || "").trim();
          return text.length > 20 &&
            !/Ready for governed metadata questions\./i.test(text) &&
            !/Genie said/i.test(text) &&
            !/Review the rows and generated SQL before acting/i.test(text);
        }),
      undefined,
      { timeout: 120_000 },
    );
    await screenshot(page, "home-live-ai-1440x900");
    const display = await page.evaluate(() => {
      const bodyText = document.body?.innerText || "";
      const assistantNodes = [...document.querySelectorAll(".gh-home-ai-message.tone-assistant .gh-ai-message-markdown")];
      return {
        promptCount: document.querySelectorAll(".ga-ai-prompts button").length,
        assistantText: assistantNodes
          .map((node) => node.textContent?.trim() || "")
          .filter(Boolean)
          .join("\n\n"),
        assistantTextFits: assistantNodes.every((node) => node.scrollWidth <= node.clientWidth + 1),
        readyRemoved: !/Ready for governed metadata questions\./i.test(bodyText),
        rawBoilerplateRemoved:
          !/Genie said/i.test(bodyText) &&
          !/Review the rows and generated SQL before acting/i.test(bodyText),
      };
    });
    const provider = payload?.meta?.capabilities?.provider || payload?.provider || "";
    const evidenceCount = Array.isArray(payload?.evidence) ? payload.evidence.length : 0;
    if (response.status() >= 400) throw new Error(`Atlas AI returned HTTP ${response.status()}`);
    if (provider !== "genie") throw new Error(`Atlas AI provider was ${provider || "missing"}, expected genie`);
    if (evidenceCount < 1) throw new Error("Atlas AI returned no evidence records.");
    if (display.promptCount > 1) {
      throw new Error(`Atlas AI suggestions did not collapse after answer; prompt count ${display.promptCount}`);
    }
    if (!display.assistantTextFits) {
      throw new Error("Atlas AI answer text overflows its right-rail message container.");
    }
    if (!display.readyRemoved || !display.rawBoilerplateRemoved) {
      throw new Error("Atlas AI still displays removed ready/Genie boilerplate copy.");
    }
    return {
      cycledPrompt,
      status: response.status(),
      provider,
      evidenceCount,
      confidence: payload?.confidence || "",
      source: payload?.meta?.source || "",
      screenshotViewport: page.viewportSize(),
      display,
    };
  });
}

async function imageDataUrl(filePath) {
  const buffer = await fs.readFile(filePath);
  return `data:image/png;base64,${buffer.toString("base64")}`;
}

async function createSideBySide(browser) {
  const currentPath = path.join(OUT_DIR, "home-live-1536x1024.png");
  const [mockUrl, currentUrl] = await Promise.all([
    imageDataUrl(MOCKUP_PATH),
    imageDataUrl(currentPath),
  ]);
  const page = await browser.newPage({ viewport: { width: 3200, height: 1120 } });
  const outputPath = path.join(OUT_DIR, "home-live-side-by-side-1536x1024.png");
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
                <h1>Reference: docs/mockups/mock1.png</h1>
                <img src="${mockUrl}" />
              </section>
              <section class="panel">
                <h1>Current: Home live 1536x1024</h1>
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
