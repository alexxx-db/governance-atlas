// Probe: at 1280px with the Discover preview open, the search-row buttons
// must sit fully inside the hero's clipping box and Sort must stay in-column.
import { chromium } from "playwright";

const BASE = process.env.AXIOM_CAPTURE_BASE || "http://localhost:3100";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
await page.goto(`${BASE}/discover`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 90000 }).catch(() => {});
await page.waitForTimeout(6000);

// Open the preview via the first result row if present; else force the attr.
const row = page.locator(".gh-discovery-result-row, [class*=result-card], [class*=result-row]").first();
try { await row.click({ timeout: 5000 }); } catch {
  await page.evaluate(() => {
    document.querySelector(".gh-discovery-main-grid")?.setAttribute("data-preview-open", "true");
  });
}
await page.waitForTimeout(1500);

const report = await page.evaluate(() => {
  const hero = document.querySelector(".gh-discovery-hero");
  const heroRect = hero?.getBoundingClientRect();
  const out = { heroRight: heroRect?.right, rowDisplay: null, buttons: [], sort: null, firstCardLeft: null };
  const srow = document.querySelector(".gh-discovery-search-row");
  if (srow) out.rowDisplay = getComputedStyle(srow).display;
  document.querySelectorAll(".gh-discovery-search-row button").forEach((b) => {
    const r = b.getBoundingClientRect();
    out.buttons.push({ label: b.textContent.trim().slice(0, 20), right: r.right, left: r.left, w: r.width });
  });
  const sortLabel = Array.from(document.querySelectorAll("span,label")).find((e) => e.textContent.trim() === "Sort:");
  if (sortLabel) out.sort = sortLabel.getBoundingClientRect().left;
  const card = document.querySelector("[class*=result]");
  if (card) out.firstCardLeft = card.getBoundingClientRect().left;
  return out;
});
console.log(JSON.stringify(report, null, 2));
await page.screenshot({ path: process.env.PROBE_OUT || "/tmp/probe_search_row.png" });
await browser.close();
