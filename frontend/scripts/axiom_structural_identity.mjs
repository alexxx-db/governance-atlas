/**
 * Prototype-era structural identity compatibility wrapper.
 *
 * The legacy identity script checked retired OM-style selectors and old shell
 * labels. Keep `npm run identity:deployed` stable, but delegate to the current
 * prototype route capture, which records screenshots and DOM metrics for the
 * Command Center, Discover, Stewardship, Glossary/CDE, Lineage, Audit,
 * Control Center, and Asset 360 route set.
 *
 * Usage:
 *   node frontend/scripts/axiom_structural_identity.mjs <base-url>
 */

if (process.argv[2] && !process.env.AXIOM_BASE_URL) {
  process.env.AXIOM_BASE_URL = process.argv[2];
}

if (process.env.AXIOM_QA_OUT_DIR && !process.env.AXIOM_PROTOTYPE_CAPTURE_OUT) {
  process.env.AXIOM_PROTOTYPE_CAPTURE_OUT = process.env.AXIOM_QA_OUT_DIR;
}

await import("./axiom_prototype_current_capture.mjs");
