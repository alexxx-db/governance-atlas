// Governance Atlas live UI capture harness.
// Usage: node ui_capture.mjs <bearer-token> <outdir> [surface...]
// Captures: loading state + hydrated full-page screenshot per surface,
// plus hover screenshots of interactive controls on hydrated pages.
import { chromium } from "playwright";
import { mkdirSync } from "fs";

// ATLAS_CAPTURE_BASE overrides the target (e.g. http://localhost:3100 for the
// vite dev server with the /api live proxy — token can be "none" there).
const BASE = process.env.ATLAS_CAPTURE_BASE || (() => { throw new Error("Set ATLAS_CAPTURE_BASE to the deployed Atlas app URL"); })();
const token = process.argv[2];
const outdir = process.argv[3] || "./shots";
const only = process.argv.slice(4);

const SURFACES = [
  ["command-center", "/command-center"],
  ["discover", "/discover"],
  ["stewardship", "/stewardship"],
  ["glossary", "/glossary-cdes"],
  ["cdes", "/glossary-cdes?tab=cdes"],
  ["lineage", "/lineage-atlas/finance_prod.curated.revenue_daily"],
  ["audit", "/audit-evidence"],
  ["control-center", "/control-center"],
].filter(([k]) => !only.length || only.includes(k));

mkdirSync(outdir, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1720, height: 1100 },
  extraHTTPHeaders: token && token !== "none" ? { Authorization: `Bearer ${token}` } : {},
  deviceScaleFactor: 1,
});

for (const [key, path] of SURFACES) {
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
  try {
    await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    // Loading-state capture ~1.2s in (skeletons / boot shell).
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${outdir}/${key}-loading.png`, fullPage: false });
    // Hydration: wait for network to settle and skeleton markers to go away.
    await page.waitForLoadState("networkidle", { timeout: 90000 }).catch(() => {});
    await page.waitForTimeout(8000);
    await page.screenshot({ path: `${outdir}/${key}.png`, fullPage: true });
    // Hover pass: hover the first few buttons and capture the viewport.
    const buttons = await page.locator("main button:visible, aside button:visible").all();
    let hovered = 0;
    for (const b of buttons) {
      if (hovered >= 3) break;
      try {
        await b.hover({ timeout: 1500 });
        hovered += 1;
        await page.waitForTimeout(250);
        await page.screenshot({ path: `${outdir}/${key}-hover${hovered}.png`, fullPage: false });
      } catch { /* detached/covered */ }
    }
    console.log(`${key}: ok (console errors: ${errors.length})`);
    if (errors.length) console.log(`${key} ERRORS: ${errors.slice(0, 3).join(" | ")}`);
  } catch (e) {
    console.log(`${key}: FAILED ${String(e).slice(0, 200)}`);
    await page.screenshot({ path: `${outdir}/${key}-error.png` }).catch(() => {});
  }
  await page.close();
}
await browser.close();
