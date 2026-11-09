// Lineage Atlas interactive-state capture for the enterprise UI pass.
// Usage: node scripts/lineage_state_capture.mjs <outdir>
// Captures: canvas, node-selected + rail tabs, hover states, keyboard focus,
// and a 1280px-wide pass to check truncation/overlap.
import { chromium } from "playwright";
import { mkdirSync } from "fs";

const BASE = process.env.AXIOM_CAPTURE_BASE || "http://localhost:3100";
const outdir = process.argv[2] || "./lineage-states";
mkdirSync(outdir, { recursive: true });

const browser = await chromium.launch();

async function run(width, height, suffix) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await page.goto(`${BASE}/lineage-atlas/finance_prod.curated.revenue_daily`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${outdir}/cold-load${suffix}.png` });
  await page.waitForLoadState("networkidle", { timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(6000);
  await page.screenshot({ path: `${outdir}/canvas${suffix}.png`, fullPage: true });

  // Rail tabs on the focus asset (role=tab). Capture each panel state.
  for (const tab of ["Details", "Columns", "Evidence", "Impact Brief"]) {
    const t = page.getByRole("tab", { name: tab, exact: true }).first();
    if (await t.count()) {
      await t.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(900);
      const slug = tab.toLowerCase().replace(/\s+/g, "-");
      await page.screenshot({ path: `${outdir}/rail-${slug}${suffix}.png` });
    }
  }

  // Hover an unselected rail tab for hover treatment.
  const railTab = page.getByRole("tab", { name: "Details", exact: true }).first();
  if (await railTab.count()) {
    await railTab.hover().catch(() => {});
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${outdir}/tab-hover${suffix}.png` });
  }

  // Hover a non-focus node card, then select it (in-canvas seamless focus).
  const card = page.locator(".ax-lineage-v2-card").nth(2);
  if (await card.count()) {
    await card.hover({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${outdir}/node-hover${suffix}.png` });
    await card.click({ timeout: 3000, force: true }).catch(() => {});
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${outdir}/node-selected${suffix}.png` });
  }

  // Keyboard focus ring: tab into the main content a few times.
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${outdir}/kbd-focus${suffix}.png` });

  // Empty/search state: navigate to bare lineage-atlas route.
  await page.goto(`${BASE}/lineage-atlas`, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${outdir}/empty-state${suffix}.png`, fullPage: true });

  if (errors.length) console.log(`pageerrors${suffix}:`, errors.slice(0, 3).join(" | "));
  await ctx.close();
}

await run(1720, 1100, "");
await run(1280, 900, "-1280");
await browser.close();
console.log("done:", outdir);
