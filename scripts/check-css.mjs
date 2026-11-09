#!/usr/bin/env node
/**
 * scripts/check-css.mjs — CSS-debt ratchet + guardrails (Wave A3).
 *
 * Per FRONTEND_BLUEPRINT §9 "Enforcement (CI, from Wave A day 1)":
 *   gh         legacy `gh-` prefix usage (classes and `--gh-` token aliases) in
 *              CSS/JSX/JS. May only go DOWN per file; new files must be at 0.
 *   hex        raw hex colors outside design/tokens/ — palette values belong in
 *              `--ax-*` tokens (CLAUDE.md: never hard-code a palette color).
 *   important  `!important` outside the third-party-override whitelist.
 *   cssImport  `import "*.css"` outside main.jsx and components/system/ —
 *              component-level CSS imports create cascade-order nondeterminism.
 *
 * Mechanism: a committed per-file baseline (frontend/gh-ratchet.json). A file
 * FAILS when any metric exceeds its baseline (absent file = all zeros), which
 * is exactly "no new debt in changed files" without needing git state — and it
 * is deterministic in CI.
 *
 * Usage:
 *   node scripts/check-css.mjs                    # check against the baseline
 *   node scripts/check-css.mjs --update-baseline  # rewrite the baseline
 *
 * Wiring: `npm run check:css` (frontend/package.json). NOT yet part of the
 * default build/test pipeline — Wave B flips it on.
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC_ROOT = path.join(REPO_ROOT, "frontend", "src");
const BASELINE_PATH = path.join(REPO_ROOT, "frontend", "gh-ratchet.json");

/* ------------------------------------------------------------------ */
/* Policy                                                               */
/* ------------------------------------------------------------------ */

// Paths (relative to frontend/src, "/" separators) exempt per metric.
const HEX_EXEMPT_PREFIXES = ["design/tokens/"];
// Files allowed to use !important (third-party override blocks). Empty today:
// every existing use is baselined and must ratchet to zero (target: 0/1,451).
const IMPORTANT_WHITELIST = [];
// Files/dirs allowed to import CSS: main.jsx owns the global cascade order;
// the system kit (Wave A1) carries its own system.css. Wave-B surfaces follow
// the same convention — each surface owns ONE stylesheet (surfaces/<x>/<x>.css)
// imported by its own components, so consumers pull the styles automatically.
const CSS_IMPORT_ALLOWED = ["main.jsx"];
const CSS_IMPORT_ALLOWED_PREFIXES = ["components/system/", "surfaces/"];

// Tests are excluded: they reference legacy gh- DOM until their surface
// migrates, and they contain no shippable CSS.
const EXCLUDED = [/\.test\.[jt]sx?$/u, /(^|\/)__tests__\//u, /^test\//u];

const CSS_EXT = new Set([".css"]);
const CODE_EXT = new Set([".js", ".jsx", ".ts", ".tsx", ".mjs"]);

/* ------------------------------------------------------------------ */
/* Metrics                                                              */
/* ------------------------------------------------------------------ */

// `gh-` with no preceding word char: matches .gh-card, "gh-pill", --gh-bg —
// but not "high-contrast".
const GH_RE = /(?<![A-Za-z0-9])gh-/gu;
// 3/4/6/8-digit hex colors.
const HEX_RE = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-fA-F\w])/gu;
const IMPORTANT_RE = /!\s*important/gu;
// import "./x.css"; import styles from "./x.css"; import "@pkg/dist/style.css"
const CSS_IMPORT_RE = /import\s+(?:[^"';]*?from\s+)?["'][^"']+\.css(?:\?[^"']*)?["']/gu;

const METRIC_HELP = {
  gh: "new legacy gh- class/token usage — use ax-* system classes and --ax-* tokens",
  hex: "raw hex color — use a --ax-* design token (tokens live in design/tokens/)",
  important: "!important — restructure specificity instead (whitelist is for third-party overrides only)",
  cssImport: "component-level CSS import — all app CSS is imported from main.jsx (or components/system/)",
};

function count(re, text) {
  const matches = text.match(re);
  return matches ? matches.length : 0;
}

function isExcluded(rel) {
  return EXCLUDED.some((re) => re.test(rel));
}

function hasPrefix(rel, prefixes) {
  return prefixes.some((prefix) => rel.startsWith(prefix));
}

function measureFile(rel, text) {
  const ext = path.extname(rel);
  const metrics = { gh: 0, hex: 0, important: 0, cssImport: 0 };
  metrics.gh = count(GH_RE, text);
  if (CSS_EXT.has(ext)) {
    if (!hasPrefix(rel, HEX_EXEMPT_PREFIXES)) metrics.hex = count(HEX_RE, text);
    if (!IMPORTANT_WHITELIST.includes(rel)) metrics.important = count(IMPORTANT_RE, text);
  } else {
    // Hard-coded palette hexes hide in JSX/JS too (inline styles, chart config).
    if (!hasPrefix(rel, HEX_EXEMPT_PREFIXES)) metrics.hex = count(HEX_RE, text);
    if (!CSS_IMPORT_ALLOWED.includes(rel) && !hasPrefix(rel, CSS_IMPORT_ALLOWED_PREFIXES)) {
      metrics.cssImport = count(CSS_IMPORT_RE, text);
    }
  }
  return metrics;
}

/* ------------------------------------------------------------------ */
/* Scan                                                                 */
/* ------------------------------------------------------------------ */

async function walk(dir, out = []) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "dist") continue;
      await walk(abs, out);
    } else if (entry.isFile()) {
      const ext = path.extname(entry.name);
      if (CSS_EXT.has(ext) || CODE_EXT.has(ext)) out.push(abs);
    }
  }
  return out;
}

async function scan() {
  const files = await walk(SRC_ROOT);
  const results = {};
  for (const abs of files.sort()) {
    const rel = path.relative(SRC_ROOT, abs).split(path.sep).join("/");
    if (isExcluded(rel)) continue;
    const text = await fs.readFile(abs, "utf8");
    const metrics = measureFile(rel, text);
    if (Object.values(metrics).some((v) => v > 0)) results[rel] = metrics;
  }
  return results;
}

/* ------------------------------------------------------------------ */
/* Baseline compare                                                     */
/* ------------------------------------------------------------------ */

function trimZeros(metrics) {
  const out = {};
  for (const [key, value] of Object.entries(metrics)) if (value > 0) out[key] = value;
  return out;
}

async function main() {
  const update = process.argv.includes("--update-baseline");
  const current = await scan();

  if (update) {
    const files = {};
    for (const [rel, metrics] of Object.entries(current)) files[rel] = trimZeros(metrics);
    const payload = {
      version: 1,
      note: "CSS-debt ratchet baseline (scripts/check-css.mjs). Counts may only go DOWN. Regenerate ONLY after removing debt: node scripts/check-css.mjs --update-baseline",
      files,
    };
    await fs.writeFile(BASELINE_PATH, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    console.log(
      `check-css: baseline written to ${path.relative(REPO_ROOT, BASELINE_PATH)} (${Object.keys(files).length} files carrying debt)`,
    );
    return;
  }

  let baselineRaw;
  try {
    baselineRaw = JSON.parse(await fs.readFile(BASELINE_PATH, "utf8"));
  } catch {
    console.error(
      `check-css: missing/unreadable baseline ${path.relative(REPO_ROOT, BASELINE_PATH)}.\n` +
        "Run: node scripts/check-css.mjs --update-baseline (and commit the result).",
    );
    process.exitCode = 1;
    return;
  }
  const baseline = baselineRaw.files || {};

  const violations = [];
  const improvements = [];
  for (const [rel, metrics] of Object.entries(current)) {
    const base = baseline[rel] || {};
    for (const [metric, value] of Object.entries(metrics)) {
      const allowed = base[metric] || 0;
      if (value > allowed) {
        violations.push({ rel, metric, value, allowed });
      } else if (value < allowed) {
        improvements.push({ rel, metric, value, allowed });
      }
    }
  }
  // Files fully cleaned up (or deleted) since the baseline.
  for (const [rel, base] of Object.entries(baseline)) {
    if (current[rel]) continue;
    for (const [metric, allowed] of Object.entries(base)) {
      if (allowed > 0) improvements.push({ rel, metric, value: 0, allowed });
    }
  }

  if (violations.length) {
    console.error("check-css: FAIL — new CSS debt exceeds the committed ratchet baseline:\n");
    for (const { rel, metric, value, allowed } of violations) {
      console.error(
        `  frontend/src/${rel}\n    ${metric}: ${value} (baseline ${allowed}, +${value - allowed}) — ${METRIC_HELP[metric]}`,
      );
    }
    console.error(
      "\nFix the new debt (do NOT regenerate the baseline to absorb it — the ratchet only turns one way).",
    );
    process.exitCode = 1;
    return;
  }

  const totals = { gh: 0, hex: 0, important: 0, cssImport: 0 };
  for (const metrics of Object.values(current)) {
    for (const [metric, value] of Object.entries(metrics)) totals[metric] += value;
  }
  console.log(
    `check-css: PASS — gh:${totals.gh} hex:${totals.hex} !important:${totals.important} cssImport:${totals.cssImport} across ${Object.keys(current).length} files (within baseline).`,
  );
  if (improvements.length) {
    console.log(
      `check-css: ${improvements.length} metric(s) improved below baseline — ratchet down with: node scripts/check-css.mjs --update-baseline`,
    );
  }
}

main().catch((error) => {
  console.error(`check-css: unexpected error: ${error?.stack || error}`);
  process.exitCode = 1;
});
