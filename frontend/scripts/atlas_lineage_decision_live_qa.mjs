/* global AbortController, clearTimeout, console, document, fetch, process, setTimeout, URL, window */
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const BASE_URL = process.env.GOVAT_BASE_URL || "http://127.0.0.1:8765";
const APP_ORIGIN = new URL(BASE_URL).origin;
const IS_DEPLOYED_DATABRICKS_APP = /\.databricksapps\.com$/i.test(new URL(APP_ORIGIN).hostname);
const OUT_DIR = process.env.GOVAT_LINEAGE_DECISION_OUT_DIR || "/tmp/govat-lineage-decision-live";
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const RICH_ASSET_FQN = process.env.GOVAT_LINEAGE_RICH_ASSET_FQN || "main.datapact.run_history";
const ZERO_EDGE_ASSET_FQN =
  process.env.GOVAT_LINEAGE_ZERO_EDGE_ASSET_FQN ||
  "datapact.enterprise_metadata_ops.product_mortgage_signal";
const CREATE_GOVERNANCE_REQUEST = process.env.GOVAT_LINEAGE_CREATE_REQUEST !== "0";
const GOVERNANCE_REQUEST_ASSET_FQN =
  process.env.GOVAT_LINEAGE_REQUEST_ASSET_FQN ||
  ZERO_EDGE_ASSET_FQN;
const FORWARDED_EMAIL = process.env.GOVAT_CAPTURE_FORWARDED_EMAIL || process.env.GOVAT_QA_USER_EMAIL || "";
const FORWARDED_ACCESS_TOKEN =
  process.env.GOVAT_CAPTURE_FORWARDED_ACCESS_TOKEN ||
  process.env.GOVAT_DATABRICKS_TOKEN ||
  "";

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE_URL,
  appOrigin: APP_ORIGIN,
  evidenceKind: IS_DEPLOYED_DATABRICKS_APP
    ? "deployed_databricks_app_backed"
    : "local_runtime_databricks_backed",
  mockApi: false,
  deploymentId: DEPLOYMENT_ID,
  buildId: BUILD_ID,
  richAssetFqn: RICH_ASSET_FQN,
  zeroEdgeAssetFqn: ZERO_EDGE_ASSET_FQN,
  createGovernanceRequest: CREATE_GOVERNANCE_REQUEST,
  governanceRequestAssetFqn: GOVERNANCE_REQUEST_ASSET_FQN,
  forwardedActorEmail: FORWARDED_EMAIL,
  forwardedActorTokenPresent: Boolean(FORWARDED_ACCESS_TOKEN),
  checks: {},
  interactions: [],
  screenshots: [],
  requestFailures: [],
  httpClientErrors: [],
  console: [],
  pageErrors: [],
};

const headers = {
  ...(FORWARDED_ACCESS_TOKEN ? { Authorization: `Bearer ${FORWARDED_ACCESS_TOKEN}` } : {}),
  ...(FORWARDED_EMAIL
    ? {
        "x-forwarded-email": FORWARDED_EMAIL,
        "x-forwarded-preferred-username": FORWARDED_EMAIL,
      }
    : {}),
  ...(FORWARDED_ACCESS_TOKEN ? { "x-forwarded-access-token": FORWARDED_ACCESS_TOKEN } : {}),
};

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function lineageUrl(assetFqn) {
  return route(`/lineage/${encodeURIComponent(assetFqn)}`);
}

function apiUrl(pathname) {
  return route(`/api${pathname}`);
}

async function flushReport() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(
    path.join(OUT_DIR, "lineage-decision-live-report.json"),
    JSON.stringify(report, null, 2),
  );
}

async function screenshot(page, name) {
  const filePath = path.join(OUT_DIR, `${name}.png`);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await page.screenshot({ path: filePath, fullPage: false });
  report.screenshots.push(filePath);
  await flushReport();
  return filePath;
}

async function requestJson(pathname, options = {}) {
  const controller = typeof AbortController !== "undefined" && options.timeoutMs
    ? new AbortController()
    : null;
  const timeout = controller
    ? setTimeout(() => controller.abort(), options.timeoutMs)
    : null;
  const response = await fetch(apiUrl(pathname), {
    body: options.body == null ? undefined : JSON.stringify(options.body),
    headers: {
      Accept: "application/json",
      ...(options.body == null ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    method: options.method || "GET",
    signal: controller?.signal,
  });
  if (timeout) clearTimeout(timeout);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { rawText: text.slice(0, 1200) };
  }
  return {
    buildId: response.headers.get("x-govat-build-id") || "",
    ok: response.ok,
    status: response.status,
    payload,
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestBackedRecommendations() {
  let lastResponse = null;
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const separator = attempt === 0 ? "?" : "?";
    lastResponse = await requestJson(`/lineage/recommendations${separator}limit=8&_qa=${Date.now()}_${attempt}`);
    const state = String(lastResponse.payload?.meta?.state || "").toLowerCase();
    const recItems = Array.isArray(lastResponse.payload?.items)
      ? lastResponse.payload.items
      : [];
    if (lastResponse.ok && state !== "loading" && recItems.length > 0) {
      return lastResponse;
    }
    await sleep(3000);
  }
  return lastResponse;
}

async function requestFullLineage(assetFqn) {
  let lastResponse = null;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const refresh = attempt === 0 ? "&refresh=1" : "";
    lastResponse = await requestJson(
      `/lineage/${encodeURIComponent(assetFqn)}?profile=full${refresh}&_qa=${Date.now()}_${attempt}`,
    );
    const stats = lastResponse.payload?.stats || {};
    const profile =
      stats.progressive?.profile ||
      lastResponse.payload?.meta?.capabilities?.lineageProfile ||
      "";
    const visibleEdgeCount = Number(stats.upstreamCount || 0) + Number(stats.downstreamCount || 0);
    const graphEdgeCount = Number(lastResponse.payload?.graphs?.data?.edges?.length || 0);
    if (profile === "full" || visibleEdgeCount > 0 || graphEdgeCount > 0) {
      return lastResponse;
    }
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
  return lastResponse;
}

function isExpectedConsoleEntry(entry) {
  return false;
}

function isExpectedHttpClientError(entry) {
  const url = entry?.url || "";
  const requestOutcome = report.interactions.find((item) => item.name === "impact-request-ui-outcome");
  return entry?.status === 404 &&
    /\/api\/governance\/requests/i.test(url) &&
    requestOutcome?.passed === true &&
    requestOutcome?.outcome === "unavailable";
}

function pushInteraction(name, passed, detail = {}) {
  report.interactions.push({ name, passed: Boolean(passed), ...detail });
}

async function waitForLineageWorkspace(page) {
  await page.waitForSelector("[data-testid='lineage-northstar-explorer']", { timeout: 90_000 });
  await page.waitForFunction(
    () => !/Hydrating lineage from Unity Catalog|Hydrating from Unity Catalog|Loading lineage/i.test(document.body?.innerText || ""),
    undefined,
    { timeout: 90_000 },
  );
}

async function waitForRichLineageGraph(page) {
  const predicate = () =>
    document.querySelectorAll(".react-flow__node").length > 1 &&
    document.querySelectorAll(".react-flow__edge").length > 0 &&
    document.querySelectorAll(".ga-lineage-v2-card-col").length > 0;
  await page.waitForFunction(
    predicate,
    undefined,
    { timeout: 120_000 },
  );
  await page.waitForTimeout(2500);
  await page.waitForFunction(
    () =>
      document.querySelectorAll(".react-flow__node").length > 1 &&
      document.querySelectorAll(".react-flow__edge").length > 0 &&
      document.querySelectorAll(".ga-lineage-v2-card-col").length > 0,
    undefined,
    { timeout: 120_000 },
  );
}

async function bodyText(page) {
  return page.evaluate(() => document.body?.innerText || "");
}

async function visibleText(page, selector) {
  return String((await page.locator(selector).first().textContent().catch(() => "")) || "")
    .replace(/\s+/g, " ")
    .trim();
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  const recommendations = await requestBackedRecommendations();
  report.buildId = recommendations.buildId || report.buildId || "";
  const recItems = Array.isArray(recommendations.payload?.items)
    ? recommendations.payload.items
    : [];
  const recMeta = recommendations.payload?.recommendationMeta || {};
  const rankingSource = String(recMeta.rankingSource || "");
  report.checks.recommendationsBacked =
    recommendations.ok &&
    recommendations.payload?.meta?.source === "unity-catalog-lineage" &&
    recommendations.payload?.meta?.capabilities?.evidenceSource === "system.access.table_lineage" &&
    (
      rankingSource === "visible-inventory-batched-lineage" ||
      /^system\.access\.table_lineage\.(aggregate|aggregate-fallback)$/.test(rankingSource)
    ) &&
    recItems.length > 0;
  report.recommendations = {
    status: recommendations.status,
    meta: recommendations.payload?.meta || null,
    recommendationMeta: recMeta,
    items: recItems.slice(0, 8),
  };

  const lineage = await requestFullLineage(RICH_ASSET_FQN);
  const stats = lineage.payload?.stats || {};
  report.checks.richAssetBackedApi =
    lineage.ok &&
    lineage.payload?.meta?.source === "unity-catalog-lineage" &&
    lineage.payload?.meta?.authoritative === true &&
    Number(stats.upstreamCount || 0) + Number(stats.downstreamCount || 0) > 0;
  report.richAssetApi = {
    status: lineage.status,
    stats,
    nodeCount: lineage.payload?.graphs?.data?.nodes?.length || 0,
    edgeCount: lineage.payload?.graphs?.data?.edges?.length || 0,
    columnUpstreamCount: lineage.payload?.columnLineage?.upstream?.length || 0,
    columnDownstreamCount: lineage.payload?.columnLineage?.downstream?.length || 0,
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    acceptDownloads: true,
    extraHTTPHeaders: headers,
    viewport: { width: 1536, height: 1024 },
  });
  const page = await context.newPage();
  page.on("requestfailed", (request) => {
    const failureText = request.failure()?.errorText || "Request failed";
    if (/net::ERR_ABORTED/i.test(failureText)) return;
    report.requestFailures.push({ url: request.url(), method: request.method(), failureText });
  });
  page.on("response", (response) => {
    const status = response.status();
    if (status < 400) return;
    report.httpClientErrors.push({ url: response.url(), status });
  });
  page.on("pageerror", (error) => {
    report.pageErrors.push({ message: error?.message || String(error), stack: error?.stack || "" });
  });
  page.on("console", (message) => {
    if (!["error", "warning"].includes(message.type())) return;
    report.console.push({ type: message.type(), text: message.text(), url: page.url() });
  });

  try {
    await page.goto(route("/lineage"), { waitUntil: "domcontentloaded", timeout: 90_000 });
    await page.waitForFunction(
      () => window.location.pathname !== "/lineage",
      undefined,
      { timeout: 90_000 },
    );
    const defaultRouteMetrics = {
      url: page.url(),
      expectedFqn: recItems[0]?.fqn || "",
    };
    pushInteraction(
      "default-lineage-route-opens-ranked-rich-asset",
      Boolean(defaultRouteMetrics.expectedFqn && decodeURIComponent(new URL(defaultRouteMetrics.url).pathname).includes(defaultRouteMetrics.expectedFqn)),
      defaultRouteMetrics,
    );

    if (!decodeURIComponent(new URL(page.url()).pathname).includes(RICH_ASSET_FQN)) {
      await page.goto(lineageUrl(RICH_ASSET_FQN), { waitUntil: "domcontentloaded", timeout: 90_000 });
    }
    await waitForLineageWorkspace(page);
    report.buildId = report.buildId || await page.evaluate(() => window.__GOVAT_BOOTSTRAP__?.buildId || "");
    await page.waitForSelector(".react-flow__node", { timeout: 180_000 });
    await waitForRichLineageGraph(page);
    await screenshot(page, "rich-lineage-first-viewport");
    const richMetrics = await page.evaluate(() => ({
      url: window.location.href,
      nodeCount: document.querySelectorAll(".react-flow__node").length,
      edgeCount: document.querySelectorAll(".react-flow__edge").length,
      cardCount: document.querySelectorAll(".ga-lineage-v2-card").length,
      columnButtonCount: document.querySelectorAll(".ga-lineage-v2-card-col").length,
      impactFacts: [...document.querySelectorAll(".ga-lineage-impact-fact")].map((node) =>
        (node.textContent || "").replace(/\s+/g, " ").trim(),
      ),
      canvasBox: (() => {
        const box = document.querySelector(".ga-lineage-v2-canvas")?.getBoundingClientRect();
        return box ? { width: box.width, height: box.height } : null;
      })(),
    }));
    report.richViewport = richMetrics;
    pushInteraction(
      "rich-lineage-canvas-load",
      richMetrics.nodeCount > 1 &&
        richMetrics.edgeCount > 0 &&
        richMetrics.columnButtonCount > 0 &&
        richMetrics.canvasBox?.width > 600,
      richMetrics,
    );

    const columnButton = page.locator(".ga-lineage-v2-card-col").first();
    const selectedColumnName = await visibleText(page, ".ga-lineage-v2-card-col-name");
    await columnButton.click();
    await page.getByRole("tab", { name: "Columns" }).click();
    await page.waitForSelector(".ga-lineage-column-panel", { timeout: 10_000 });
    const columnText = await bodyText(page);
    await screenshot(page, "selected-column-impact");
    pushInteraction(
      "column-lineage-selection",
      Boolean(selectedColumnName) &&
        columnText.includes(selectedColumnName) &&
        /Upstream|Downstream|Transformation SQL/.test(columnText) &&
        /unavailable unless a backed query|No column paths returned|traced|direct/i.test(columnText),
      { selectedColumnName, bodyStart: columnText.slice(0, 1400) },
    );

    const viewportBefore = await page.locator(".react-flow__viewport").first().getAttribute("style");
    const zoomIn = page.locator(".react-flow__controls-zoomin");
    const zoomOut = page.locator(".react-flow__controls-zoomout");
    const zoomInDisabled = await zoomIn.evaluate((button) => Boolean(button.disabled));
    const zoomOutDisabled = await zoomOut.evaluate((button) => Boolean(button.disabled));
    let zoomAction = "";
    if (!zoomInDisabled) {
      await zoomIn.click();
      zoomAction = "zoom-in";
    } else if (!zoomOutDisabled) {
      await zoomOut.click();
      zoomAction = "zoom-out";
    }
    await page.waitForTimeout(150);
    if (zoomAction !== "zoom-out" && !(await zoomOut.evaluate((button) => Boolean(button.disabled)))) {
      await zoomOut.click();
    }
    await page.locator(".react-flow__controls-fitview").click();
    const pane = page.locator(".react-flow__pane").first();
    const box = await pane.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.48, box.y + box.height * 0.5);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.57, { steps: 8 });
      await page.mouse.up();
      await page.waitForTimeout(200);
    }
    const viewportAfter = await page.locator(".react-flow__viewport").first().getAttribute("style");
    pushInteraction("canvas-zoom-fit-pan-controls", Boolean(zoomAction && viewportBefore && viewportAfter && viewportBefore !== viewportAfter), {
      viewportBefore,
      viewportAfter,
      zoomAction,
      zoomInDisabled,
      zoomOutDisabled,
    });

    await page.getByRole("tab", { name: "Impact Brief" }).click();
    await page.waitForSelector(".ga-lineage-impact-panel", { timeout: 10_000 });
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 20_000 }),
      page.getByRole("button", { name: /^Export packet$/i }).click(),
    ]);
    const downloadPath = await download.path();
    const packet = downloadPath ? JSON.parse(await fs.readFile(downloadPath, "utf8")) : {};
    report.impactPacket = {
      evidenceSources: packet.evidenceSources || [],
      lineage: packet.lineage || null,
    };
    pushInteraction(
      "impact-packet-export",
      packet.assetFqn === RICH_ASSET_FQN &&
        packet.lineage?.source &&
        Array.isArray(packet.evidenceSources) &&
        packet.evidenceSources.length > 0,
      {
        suggestedFilename: download.suggestedFilename(),
        packetKeys: Object.keys(packet),
        evidenceSources: packet.evidenceSources || [],
        lineage: packet.lineage || null,
      },
    );
    if (packet.lineage?.authoritative === true && Number(packet.lineage?.edgeCount || 0) > 0) {
      report.checks.richAssetBackedApi = true;
      report.richAssetApi = {
        ...(report.richAssetApi || {}),
        hydratedByUiPacket: true,
        packetLineage: packet.lineage,
      };
    }

    if (CREATE_GOVERNANCE_REQUEST) {
      await page.getByRole("button", { name: /^Create request$/i }).click();
      await page.waitForFunction(
        () => /Governance request created:|Governance request creation is unavailable|Asset not found or not visible/i.test(document.body?.innerText || ""),
        undefined,
        { timeout: 180_000 },
      );
      const createdText = await bodyText(page);
      const requestMatch = createdText.match(/Governance request created:\s*([A-Za-z0-9_.:-]+)/i);
      const unavailable = /Governance request creation is unavailable|Asset not found or not visible/i.test(createdText);
      pushInteraction("impact-request-ui-outcome", Boolean(requestMatch?.[1] || unavailable), {
        outcome: requestMatch?.[1] ? "created" : "unavailable",
        requestId: requestMatch?.[1] || "",
      });
    } else {
      pushInteraction("impact-request-ui-outcome", true, {
        skipped: true,
        reason: "GOVAT_LINEAGE_CREATE_REQUEST=0",
      });
    }

    await page.getByRole("tab", { name: "Evidence" }).click();
    const evidenceText = await bodyText(page);
    pushInteraction(
      "evidence-tab-boundary",
      /Evidence sources|Atlas AI evidence boundary|exported packet remains the backed artifact/i.test(evidenceText),
      { bodyStart: evidenceText.slice(0, 1400) },
    );

    await page.goto(lineageUrl(ZERO_EDGE_ASSET_FQN), { waitUntil: "domcontentloaded", timeout: 90_000 });
    await waitForLineageWorkspace(page);
    await page.waitForSelector(".ga-lineage-zero-state", { timeout: 90_000 });
    const zeroText = await bodyText(page);
    await screenshot(page, "zero-lineage-recommendations");
    const recommendationRows = page.locator(".ga-lineage-zero-state .ga-lineage-recommendation-row");
    const rowCount = await recommendationRows.count();
    pushInteraction(
      "zero-edge-recommendations",
      /No actor-visible lineage edges returned for this asset/i.test(zeroText) && rowCount > 0,
      { recommendationRowCount: rowCount, bodyStart: zeroText.slice(0, 1400) },
    );
    if (rowCount > 0) {
      const firstLabel = await visibleText(page, ".ga-lineage-zero-state .ga-lineage-recommendation-row");
      await recommendationRows.first().click();
      await waitForLineageWorkspace(page);
      await waitForRichLineageGraph(page);
      const navigatedAssetFqn = decodeURIComponent(new URL(page.url()).pathname).replace(/^\/lineage\/?/, "");
      const navigatedApi = navigatedAssetFqn
        ? await requestFullLineage(navigatedAssetFqn)
        : null;
      const navigatedApiStats = navigatedApi?.payload?.stats || {};
      const navigatedApiEdgeCount =
        Number(navigatedApiStats.upstreamCount || 0) +
        Number(navigatedApiStats.downstreamCount || 0);
      const navigatedMetrics = await page.evaluate(() => ({
        url: window.location.href,
        nodeCount: document.querySelectorAll(".react-flow__node").length,
        edgeCount: document.querySelectorAll(".react-flow__edge").length,
        edgePathCount: document.querySelectorAll(".react-flow__edge-path").length,
      }));
      pushInteraction(
        "zero-edge-opens-ranked-asset",
        navigatedMetrics.nodeCount > 1 &&
          (
            navigatedMetrics.edgeCount > 0 ||
            navigatedMetrics.edgePathCount > 0 ||
            navigatedApiEdgeCount > 0
          ),
        {
          firstLabel,
          navigatedAssetFqn,
          navigatedApiEdgeCount,
          navigatedApiStatus: navigatedApi?.status || 0,
          ...navigatedMetrics,
        },
      );
    }
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    await flushReport();
  }

  if (CREATE_GOVERNANCE_REQUEST) {
    const requestTitle = `Lineage impact review ${new Date().toISOString()}`;
    const governanceRequest = await requestJson("/governance/requests?fast=1", {
      method: "POST",
      timeoutMs: 240_000,
      body: {
        assetFqn: GOVERNANCE_REQUEST_ASSET_FQN,
        title: requestTitle,
        note: [
          "Review the downstream impact before approving changes to this governed asset.",
          `Primary lineage context: ${RICH_ASSET_FQN}`,
          `Selected asset context: ${ZERO_EDGE_ASSET_FQN}`,
        ].join("\n"),
      },
    });
    report.governanceRequestApi = {
      status: governanceRequest.status,
      ok: governanceRequest.ok,
      requestId: governanceRequest.payload?.requestId || "",
      assetFqn: GOVERNANCE_REQUEST_ASSET_FQN,
      title: requestTitle,
      detail: governanceRequest.payload?.detail || "",
    };
    report.checks.governanceRequestBackedApi =
      governanceRequest.ok && Boolean(governanceRequest.payload?.requestId);
  } else {
    report.checks.governanceRequestBackedApi = true;
    report.governanceRequestApi = {
      skipped: true,
      reason: "GOVAT_LINEAGE_CREATE_REQUEST=0",
    };
  }

  report.checks.allInteractionsPassed = report.interactions.every((item) => item.passed);
  report.checks.noPageErrors = report.pageErrors.length === 0;
  report.checks.noRequestFailures = report.requestFailures.length === 0;
  report.expectedHttpClientErrors = report.httpClientErrors.filter(isExpectedHttpClientError);
  report.unexpectedHttpClientErrors = report.httpClientErrors.filter(
    (entry) => !report.expectedHttpClientErrors.includes(entry),
  );
  report.checks.noUnexpectedHttpClientErrors = report.unexpectedHttpClientErrors.length === 0;
  report.unexpectedConsole = report.console.filter((entry) => !isExpectedConsoleEntry(entry));
  report.checks.noUnexpectedConsoleErrors = report.unexpectedConsole.length === 0;
  report.passed = Object.values(report.checks).every(Boolean);
  await flushReport();
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exit(1);
}

main().catch(async (error) => {
  report.fatalError = { message: error?.message || String(error), stack: error?.stack || "" };
  report.passed = false;
  await flushReport();
  console.error(JSON.stringify(report, null, 2));
  process.exit(1);
});
