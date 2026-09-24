/*
 * surfaces/ai/aiPresentation.js: labels, tones, and formatting for the AI
 * governance surface. Pure functions only (tested in __tests__).
 *
 * Truthfulness: a missing value renders as the "—" glyph (COHESION law #3),
 * never as 0 or an invented label.
 */

export const DASH = "—";

export const KIND_LABELS = {
  serving_endpoint: "Serving endpoint",
  external_model: "External model",
  agent: "Agent",
  mcp_server: "MCP server",
  uc_function_tool: "UC function tool",
  ai_model: "Registered model",
  ai_model_version: "Model version",
  intake_record: "Intake record",
};

export const RECONCILIATION_LABELS = {
  matched: "Matched",
  ambiguous: "Ambiguous",
  orphaned: "No intake",
  pending_intake: "Intake pending",
};

const RECONCILIATION_TONES = { matched: "good", ambiguous: "warn", orphaned: "bad", pending_intake: "info" };

export const FINDING_TYPE_LABELS = {
  rejected_but_running: "Rejected but running",
  found_not_registered: "Found, not registered",
  found_different: "Differs from intake",
  registered_not_found: "Registered, not found",
  ambiguous_match: "Ambiguous match",
};

export const FINDING_TYPE_ORDER = [
  "rejected_but_running",
  "found_not_registered",
  "found_different",
  "registered_not_found",
  "ambiguous_match",
];

const SEVERITY_TONES = { critical: "bad", high: "bad", medium: "warn", low: "info" };
const CONTROL_TONES = { pass: "good", fail: "bad", unknown: "muted", not_applicable: "muted" };
const POSTURE_TONES = { strong: "good", partial: "warn", weak: "bad", unknown: "muted" };
const LINK_TONES = { linked: "good", not_found: "bad", unlinked: "muted" };

export const LINK_STATUS_LABELS = { linked: "Linked", not_found: "Not found", unlinked: "Not linked yet" };

export function kindLabel(kind) {
  return KIND_LABELS[kind] || kind || DASH;
}

export function reconciliationLabel(state) {
  return RECONCILIATION_LABELS[state] || (state ? String(state) : DASH);
}

export function reconciliationTone(state) {
  return RECONCILIATION_TONES[state] || "muted";
}

export function severityTone(severity) {
  return SEVERITY_TONES[severity] || "muted";
}

export function controlTone(status) {
  return CONTROL_TONES[status] || "muted";
}

export function postureTone(band) {
  return POSTURE_TONES[band] || "muted";
}

export function linkTone(status) {
  return LINK_TONES[status] || "muted";
}

export function findingTypeLabel(type) {
  return FINDING_TYPE_LABELS[type] || type || DASH;
}

export function valueOrDash(value) {
  if (value === null || value === undefined || value === "") return DASH;
  return String(value);
}

/** Counts render as numbers only when the backend supplied one (null = no run). */
export function countOrDash(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : DASH;
}

export function percentOrDash(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : DASH;
}

export function formatTimestamp(value) {
  if (!value) return DASH;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function roleSlug(value) {
  return String(value || "").trim().toLowerCase();
}

/** Steward actions render only for steward/admin; the API enforces the same gate. */
export function isSteward(shell) {
  const role = roleSlug(shell?.role || shell?.actorRole);
  return role.includes("steward") || role.includes("admin");
}

export function aiAssetHref(entityId) {
  return `/ai/assets/${encodeURIComponent(entityId || "")}`;
}

/** Group findings by type in the fixed triage order, preserving row order. */
export function groupFindings(rows = []) {
  const groups = new Map(FINDING_TYPE_ORDER.map((type) => [type, []]));
  rows.forEach((row) => {
    const type = row?.findingType || "other";
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type).push(row);
  });
  return [...groups.entries()].filter(([, items]) => items.length > 0).map(([type, items]) => ({ type, items }));
}

/** "Unknown: signal not observable from <source>" for unknown control results. */
export function controlDetail(control) {
  if (!control) return DASH;
  if (control.status === "unknown") {
    const reason = control.evidence?.reason ? ` (${control.evidence.reason})` : "";
    return `Unknown: signal not observable from ${control.signalSource || "the source"}${reason}`;
  }
  const evidence = control.evidence || {};
  if (evidence.reason) return evidence.reason;
  if (evidence.intakeId) return `Intake ${evidence.intakeId} (${evidence.intakeState || "unknown state"})`;
  if (evidence.observedTier || evidence.declaredTier) {
    return `Observed tier ${valueOrDash(evidence.observedTier)}; declared ${valueOrDash(evidence.declaredTier)}`;
  }
  if (typeof evidence.enabled === "boolean") return evidence.enabled ? "Enabled" : evidence.gatewayConfigured ? "Disabled" : "No AI Gateway configuration";
  if (Array.isArray(evidence.plaintextFields)) return `Plaintext credential fields: ${evidence.plaintextFields.join(", ")}`;
  if (Array.isArray(evidence.secretRefs)) return `${evidence.secretRefs.length} secret reference(s)`;
  return DASH;
}

/** Source warnings from the envelope, deduplicated, for the availability banner. */
export function availabilityWarnings(query) {
  const warnings = [...(query?.warnings || []), ...(query?.meta?.warnings || [])];
  return [...new Set(warnings.map((w) => String(w || "").trim()).filter(Boolean))];
}
