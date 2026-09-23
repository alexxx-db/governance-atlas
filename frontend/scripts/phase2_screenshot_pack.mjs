/**
 * Phase 2 design-review screenshot pack.
 *
 * Regenerates the 5 golden-path screenshots that close out Phase 2-f:
 *   01-discovery         — shell + discovery workspace
 *   02-entity            — entity record hero + metrics + tabs
 *   03-lineage           — lineage stage + upstream/downstream graph
 *   04-governance        — stewardship workbench + glossary snapshot
 *   05-degraded          — entity-not-found degraded variant
 *
 * Both viewport and full-page variants are captured where useful.
 *
 * Requires a running CDP-enabled Chrome session with an authenticated
 * Databricks cookie for the target workspace. Launch with:
 *
 *   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
 *     --remote-debugging-port=9223 \
 *     --user-data-dir="$HOME/.chrome-cdp-profile" \
 *     <app-url>
 *
 * Then run (from the repo root):
 *
 *   node frontend/scripts/phase2_screenshot_pack.mjs \
 *     https://<your-atlas-app>.databricksapps.com
 *
 * Environment overrides:
 *   GOVAT_BASE_URL             base URL of the deployed app
 *   GOVAT_CDP_URL              CDP endpoint (default http://127.0.0.1:9223)
 *   GOVAT_SCREENSHOT_OUT_DIR   output dir (default docs/screenshots/phase2)
 *   GOVAT_SCREENSHOT_ASSET     entity FQN (default prod.silver.ap_self_assessed_tax_dist)
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

const BASE_URL = process.env.GOVAT_BASE_URL || process.argv[2] || "";
const CDP_URL = process.env.GOVAT_CDP_URL || "http://127.0.0.1:9223";
const OUT_DIR =
  process.env.GOVAT_SCREENSHOT_OUT_DIR ||
  path.join(REPO_ROOT, "docs", "screenshots", "phase2");
const ENTITY_FQN =
  process.env.GOVAT_SCREENSHOT_ASSET ||
  "prod.silver.ap_self_assessed_tax_dist";
const VIEWPORT = { width: 1440, height: 900 };

if (!BASE_URL) {
  console.error(
    "Usage: node frontend/scripts/phase2_screenshot_pack.mjs <base-url>",
  );
  process.exit(1);
}

function urlFor(pathSegment) {
  const base = BASE_URL.replace(/\/+$/, "");
  return `${base}${pathSegment}`;
}

async function capture(page, { filename, fullPage = false }) {
  const full = path.join(OUT_DIR, filename);
  await page.screenshot({ path: full, fullPage, type: "png" });
  console.log(`  wrote ${path.relative(REPO_ROOT, full)}`);
}

async function waitForMainReady(page) {
  // The shell always renders the brand link; wait for that as the
  // broadest "page reacted" signal, then give late-mount content a
  // short settle window.
  await page.getByRole("button", { name: /Governance Atlas/i }).first().waitFor({
    state: "visible",
    timeout: 30_000,
  });
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => {});
}

async function gotoGolden(page, title, relativeUrl, extraWait, settleSelector) {
  console.log(`→ ${title}  (${relativeUrl})`);
  await page.goto(urlFor(relativeUrl), { waitUntil: "domcontentloaded" });
  await waitForMainReady(page);
  if (settleSelector) {
    await page.waitForSelector(settleSelector, { state: "visible", timeout: 20_000 }).catch(() => {});
  }
  if (extraWait) {
    await page.waitForTimeout(extraWait);
  }
}

async function main() {
  await fs.mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.connectOverCDP(CDP_URL);
  const [context] = browser.contexts();
  if (!context) {
    throw new Error(
      "No browser context found. Ensure Chrome is running with --remote-debugging-port on the CDP URL.",
    );
  }
  const page = await context.newPage();
  await page.setViewportSize(VIEWPORT);

  try {
    // Wait for at least one result row so the discovery capture shows real
    // data instead of the "Loading the latest visible assets" skeleton.
    await gotoGolden(page, "Discovery", "/discovery", 1500, ".gh-discovery-result-row");
    await capture(page, { filename: "01-discovery-viewport.png" });
    await capture(page, { filename: "01-discovery.png", fullPage: true });

    // Settle on the EntityHero title so the loading skeleton is past before
    // the screenshot fires.
    await gotoGolden(page, "Entity", `/entity/${ENTITY_FQN}`, 1500, ".gh-entity-hero-title");
    await capture(page, { filename: "02-entity-viewport.png" });
    await capture(page, { filename: "02-entity-fullpage.png", fullPage: true });

    // Wait for at least one rendered lineage node before snapshotting so the
    // graph shape is captured instead of the "Loading lineage graph" skeleton.
    await gotoGolden(page, "Lineage", `/lineage/${ENTITY_FQN}`, 1500, ".gh-graph-node-card");
    await capture(page, { filename: "03-lineage-viewport.png" });
    await capture(page, { filename: "03-lineage-fullpage.png", fullPage: true });

    await gotoGolden(page, "Governance", "/governance", 1500);
    await capture(page, { filename: "04-governance-viewport.png" });
    await capture(page, { filename: "04-governance-fullpage.png", fullPage: true });

    await gotoGolden(page, "Degraded (entity-not-found)", "/entity/does.not.exist", 2000);
    await capture(page, { filename: "05-degraded-entity-not-found.png" });

    console.log(`\n✓ Screenshot pack written to ${path.relative(REPO_ROOT, OUT_DIR)}`);
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error("Screenshot pack failed:", err);
  process.exit(1);
});
