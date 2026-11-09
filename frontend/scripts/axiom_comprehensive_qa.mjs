/**
 * Prototype-era deployed QA compatibility wrapper.
 *
 * The legacy comprehensive QA script encoded the retired pre-prototype shell
 * selectors. Keep the public npm command stable, but delegate to the current
 * live endpoint validator that checks routed surfaces, Genie grounding,
 * Lakebase mirror health, lineage, Asset 360, audit, CDE, and control-center
 * contracts.
 *
 * Usage:
 *   node frontend/scripts/axiom_comprehensive_qa.mjs <base-url>
 */

if (process.argv[2] && !process.env.AXIOM_BASE_URL) {
  process.env.AXIOM_BASE_URL = process.argv[2];
}

if (process.env.AXIOM_QA_OUT_DIR && !process.env.AXIOM_ROUTE_OUT) {
  process.env.AXIOM_ROUTE_OUT = `${process.env.AXIOM_QA_OUT_DIR.replace(/\/+$/, "")}/route-validation.json`;
}

await import("./axiom_route_live_validation.mjs");
