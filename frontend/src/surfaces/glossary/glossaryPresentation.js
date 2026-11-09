/*
 * surfaces/glossary/glossaryPresentation.js — pure presentation helpers for
 * the Glossary & CDEs surface (Wave C4). Ported from the meaningful parts of
 * the legacy TaxonomyWorkspace/CdeWorkspace normalizers; no React, no I/O.
 *
 * Honesty rules carried over from the legacy gap fixes:
 *   - internal taxonomy ids ("ax-taxonomy-node-revenue") never render raw —
 *     humanizeTaxonomyRef() title-cases the slug tail;
 *   - hierarchy is REAL only: a parent renders when it resolves (or
 *     humanizes), children only when other terms actually point here;
 *   - CDE source backing is its own signal ("Not tagged"), never conflated
 *     into the certification status;
 *   - hydrating payloads never produce fabricated "unavailable" records.
 */

export function text(value) {
  if (value == null) return "";
  return String(value).trim();
}

export function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function jsonArrayValue(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function firstPresent(...values) {
  return values.find((value) => value !== undefined && value !== null && text(value) !== "");
}

function evidenceText(...values) {
  for (const value of values) {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const parts = [
        value.source,
        value.system,
        value.runId || value.workflowId || value.requestId,
        value.observedAt || value.updatedAt || value.reviewedAt,
      ]
        .map(text)
        .filter(Boolean);
      if (parts.length) return parts.join(" · ");
      continue;
    }
    const plain = text(value);
    if (plain) return plain;
  }
  return "";
}

export function normalizeStatusKey(value) {
  return text(value).toLowerCase().replace(/[\s-]+/g, "_");
}

export function titleFromValue(value) {
  const normalized = text(value).replace(/[_-]+/g, " ").trim();
  if (!normalized) return "";
  return normalized.replace(/\w\S*/g, (part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase());
}

/**
 * Internal taxonomy ids ("ax-taxonomy-node-revenue") must never render as
 * user-facing labels: strip the machine prefix and title-case the slug tail
 * ("Revenue"). Non-prefixed values just get title-cased.
 */
export function humanizeTaxonomyRef(value) {
  const raw = text(value);
  if (!raw) return "";
  const tail = raw.replace(/^ax-taxonomy-(?:node|term)-/i, "");
  return titleFromValue(tail) || raw;
}

export function compactDate(value) {
  const raw = text(value);
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Legacy statusTone, mapped onto the system Badge tone vocabulary. */
export function statusToneFor(status) {
  const normalized = normalizeStatusKey(status);
  if (["approved", "certified", "active", "trusted", "healthy", "compliant", "complete"].includes(normalized)) {
    return "good";
  }
  if (normalized.includes("recert") || normalized.includes("due")) return "warn";
  if (["proposed", "in_review", "review", "pending", "draft_review"].includes(normalized)) return "warn";
  if (["rejected", "deprecated", "retired", "critical", "restricted", "confidential", "high"].includes(normalized)) {
    return "bad";
  }
  if (["draft"].includes(normalized)) return "muted";
  if (["low", "internal", "medium"].includes(normalized)) return "info";
  return "neutral";
}

export function statusLabelFor(value, fallback = "Unavailable") {
  return titleFromValue(value) || fallback;
}

/* ------------------------------------------------------------------ */
/* Glossary terms                                                       */
/* ------------------------------------------------------------------ */

// Demo-priority ordering preserved from the legacy registry so the governed
// revenue vocabulary leads the grid ahead of alphabetical stragglers.
const TERM_PRIORITY = [
  "net revenue",
  "gross revenue",
  "revenue adjustments",
  "discounts",
  "refunds",
  "surcharges",
  "service revenue",
  "product revenue",
  "subscription revenue",
  "one-time revenue",
  "recurring revenue",
  "contracted revenue",
  "billable amount",
  "deferred revenue",
  "recognized revenue",
  "revenue forecast",
  "revenue recognition date",
  "average revenue",
];

function normalizeReviewer(entry, index) {
  if (typeof entry === "string") {
    return { id: entry || `reviewer-${index}`, email: entry, role: "Reviewer", state: "active" };
  }
  const value = entry && typeof entry === "object" ? entry : {};
  const email = text(
    value.email || value.ownerEmail || value.reviewerEmail || value.reviewedBy || value.name,
  );
  return {
    id: text(value.id) || email || `reviewer-${index}`,
    email,
    role: text(value.role || value.reviewerRole || "Reviewer") || "Reviewer",
    state: text(value.state || value.status || "active") || "active",
    reviewedAt: text(value.reviewedAt || value.updatedAt || value.createdAt),
  };
}

function normalizeLinkedAsset(entry, index) {
  const value = entry && typeof entry === "object" ? entry : {};
  const fqn = text(value.assetFqn || value.subjectFqn || value.fqn || value.name || entry);
  const label = text(value.assetLabel || value.label || value.name || fqn.split(".").pop());
  return {
    id: fqn || `asset-${index}`,
    fqn,
    label: label || fqn || "Linked asset",
    type: text(value.assetType || value.type || value.objectType || "Asset"),
    platform: text(value.platform || value.source || value.catalog || ""),
  };
}

function normalizeHistory(entry, index) {
  const value = entry && typeof entry === "object" ? entry : {};
  return {
    id: text(value.id || value.versionId || value.requestId) || `history-${index}`,
    version: text(value.version || value.versionLabel || value.revision || value.label) || `v${index + 1}`,
    title: text(value.title || value.name || value.action) || "Term update",
    changedAt: text(value.changedAt || value.createdAt || value.updatedAt),
    changedBy: text(value.changedBy || value.createdBy || value.updatedBy || value.reviewedBy),
    status: text(value.status || value.state),
    note: text(value.note || value.changeNote || value.detail || value.reviewNote || value.description),
  };
}

function normalizeTermRequest(entry, index) {
  const value = entry && typeof entry === "object" ? entry : {};
  return {
    id: text(value.requestId || value.id) || `request-${index}`,
    title: text(value.title || value.detail || value.note) || "Governance request",
    status: normalizeStatusKey(value.status || value.state),
    createdAt: text(value.createdAt || value.created_at),
    assetFqn: text(value.assetFqn || value.subjectFqn),
  };
}

export function normalizeTerm(item, index) {
  const value = item && typeof item === "object" ? item : {};
  const termId = text(value.termId || value.term_id || value.id) || `term-${index}`;
  const term = text(value.term || value.name || value.title || value.display_name) || "Untitled term";
  const reviewers = arrayValue(value.reviewerRoster || value.reviewerAssignments || value.reviewers).map(
    normalizeReviewer,
  );
  const explicitSteward = reviewers.find((reviewer) =>
    ["steward", "data_steward"].includes(normalizeStatusKey(reviewer.role)),
  );
  const explicitReview = reviewers.find((reviewer) =>
    ["approver", "reviewer", "steward", "data_steward"].includes(normalizeStatusKey(reviewer.role)),
  );
  const assets = [
    ...arrayValue(value.assetPreview),
    ...arrayValue(value.assets),
    ...arrayValue(value.linkedAssets),
  ].map(normalizeLinkedAsset);
  const uniqueAssets = Array.from(new Map(assets.map((asset) => [asset.id, asset])).values());
  const synonyms = Array.from(
    new Set(
      [...arrayValue(value.synonyms).map(text), ...jsonArrayValue(value.synonyms_json).map(text)].filter(Boolean),
    ),
  );
  const requests = arrayValue(value.recentRequests).map(normalizeTermRequest);
  return {
    termId,
    term,
    parentTermId: text(value.parentTermId || value.parent_term_id),
    definition: text(value.definition || value.description || value.def),
    domain: text(value.domain) || "Unassigned",
    status: normalizeStatusKey(value.reviewState || value.status || "draft") || "draft",
    synonyms,
    ownerEmail: text(value.ownerEmail || value.owner_email),
    stewardEmail:
      text(value.stewardEmail || value.steward_email || value.steward) || explicitSteward?.email || "",
    reviewedAt:
      text(value.reviewedAt || value.reviewed_at || value.approvedAt || value.approved_at) ||
      explicitReview?.reviewedAt ||
      "",
    reviewers,
    assets: uniqueAssets,
    assetCount: Number.isFinite(Number(firstPresent(value.assetCount, value.linkedAssetCount)))
      ? Number(firstPresent(value.assetCount, value.linkedAssetCount))
      : uniqueAssets.length,
    childCount: Number.isFinite(Number(value.childCount)) ? Number(value.childCount) : 0,
    currentVersion: text(value.currentVersion || value.version),
    createdAt: text(value.createdAt || value.created_at),
    updatedAt: text(value.updatedAt || value.updated_at),
    termHistory: arrayValue(
      value.termHistory || value.versionHistory || value.history || value.recentRequests,
    ).map(normalizeHistory),
    recentRequests: requests,
    pendingRequestCount: Number.isFinite(Number(value.pendingRequestCount))
      ? Number(value.pendingRequestCount)
      : requests.filter((request) => request.status === "pending").length,
    summarySource: evidenceText(value.summarySource, value.source, value.provenance),
  };
}

function termStatusRank(term = {}) {
  // Approved/linked terms lead the registry so leftover draft/test rows
  // never occupy the first card slot (legacy G2).
  const normalized = normalizeStatusKey(term.status);
  if (["approved", "certified", "active"].includes(normalized)) return 0;
  if (["in_review", "proposed", "review", "pending"].includes(normalized)) return 1;
  if (normalized === "draft") return 2;
  return 3;
}

export function sortTermsForDisplay(terms) {
  return [...terms].sort((left, right) => {
    const leftPriority = TERM_PRIORITY.indexOf(left.term.toLowerCase());
    const rightPriority = TERM_PRIORITY.indexOf(right.term.toLowerCase());
    const leftRank = leftPriority >= 0 ? leftPriority : TERM_PRIORITY.length;
    const rightRank = rightPriority >= 0 ? rightPriority : TERM_PRIORITY.length;
    if (leftRank !== rightRank) return leftRank - rightRank;
    const statusDelta = termStatusRank(left) - termStatusRank(right);
    if (statusDelta) return statusDelta;
    const linkedDelta = Number(Boolean(right.assetCount)) - Number(Boolean(left.assetCount));
    if (linkedDelta) return linkedDelta;
    return left.term.localeCompare(right.term);
  });
}

export function matchTermByIdOrName(terms, reference) {
  const normalized = String(reference || "").trim().toLowerCase();
  if (!normalized) return null;
  return (
    terms.find((term) => term.termId.toLowerCase() === normalized) ||
    terms.find((term) => term.term.toLowerCase() === normalized) ||
    // Chips historically linked by display name; tolerate dashed/encoded forms.
    terms.find((term) => term.term.toLowerCase() === normalized.replace(/[-_]+/g, " ")) ||
    null
  );
}

export function termAssociationSummary(term = {}) {
  const count = Number(term.assetCount || 0);
  if (count > 0) return `${count.toLocaleString()} linked asset${count === 1 ? "" : "s"}`;
  return "No assets linked yet";
}

export function termReviewSummary(term = {}) {
  if (term.reviewedAt) return `Reviewed ${compactDate(term.reviewedAt) || term.reviewedAt}`;
  const latest = arrayValue(term.termHistory).find((entry) => text(entry?.changedAt));
  if (latest) {
    const approved = ["approved", "reviewed", "certified"].includes(normalizeStatusKey(latest.status));
    return `${approved ? "Reviewed" : "Updated"} ${compactDate(latest.changedAt) || latest.changedAt}`;
  }
  if (term.reviewers?.length) {
    return `${term.reviewers.length} reviewer${term.reviewers.length === 1 ? "" : "s"} assigned`;
  }
  return "Not yet reviewed";
}

/** A term needs review when its lifecycle state is anything pre-approval. */
export function termAwaitingReview(term = {}) {
  return ["draft", "proposed", "in_review", "review", "pending"].includes(normalizeStatusKey(term.status));
}

export function termsFromOverviewPayload(payload) {
  const overview = payload && typeof payload === "object" && "data" in payload ? payload.data : payload;
  return arrayValue(overview?.glossaryTerms).map(normalizeTerm);
}

/* ------------------------------------------------------------------ */
/* CDEs                                                                 */
/* ------------------------------------------------------------------ */

const CDE_PRIORITY = [
  "net revenue usd",
  "net revenue (usd)",
  "customer id",
  "lifetime value usd",
  "lifetime value (usd)",
  "compensation band",
  "order total usd",
  "order total (usd)",
];

export function displayCdeName(value) {
  const raw = text(value);
  if (!raw) return "Unnamed CDE";
  return raw
    .replace(/[_-]+/g, " ")
    .replace(/\busd\b/i, "(USD)")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace("(Usd)", "(USD)");
}

export function sourceAssetFqnForCde(cde = {}) {
  const explicit = text(cde.assetFqn || cde.fqn || cde.sourceAssetFqn || cde.tableFqn);
  if (explicit) return explicit;
  const column = text(cde.column || cde.sourceColumn || cde.sourceOfRecordColumn);
  const parts = column.split(".").filter(Boolean);
  if (parts.length >= 4) return parts.slice(0, -1).join(".");
  // Dashboard rows use the asset FQN itself as the row id (legacy G9) — the
  // fallback keeps "source asset"/"lineage" links alive for rows that carry one.
  const id = text(cde.id);
  return id.split(".").filter(Boolean).length >= 3 ? id : "";
}

export function normalizeCdeRow(item, index) {
  const value = item && typeof item === "object" ? item : {};
  const fqn = text(value.assetFqn || value.fqn || value.id || value.name) || `cde-${index}`;
  const rawName = text(value.name || value.rawName || fqn.split(".").pop()) || fqn;
  const sourceColumn = text(
    value.sourceColumn ||
      value.sourceOfRecordColumn ||
      value.source_of_record_column ||
      value.column ||
      value.columnFqn,
  );
  return {
    id: text(value.id) || fqn || `cde-${index}`,
    assetFqn: text(value.assetFqn || value.fqn) || (fqn.includes(".") ? fqn : ""),
    name: displayCdeName(rawName),
    rawName,
    column: sourceColumn,
    domain: text(value.domain) || "Unassigned",
    owner: text(value.owner || value.ownerEmail || value.steward || value.stewardEmail) || "Unassigned",
    // Sensitivity is a LABEL, never a protection claim (legacy persona audit).
    sensitivity: text(value.sensitivity) || "",
    criticality: text(value.criticality) || "",
    recert: text(value.recert || value.recertAge || value.reviewAge || value.reviewWindow) || "Unavailable",
    lastReview: text(value.lastReview || value.reviewedAt || value.reviewed_at),
    certification: text(value.certification),
    // Prefer the real certification over the legacy conflated status field.
    status:
      text(value.certification || value.status || value.health || value.controlState || value.state) ||
      "Unavailable",
    sourceBacked: value.sourceBacked === true || Boolean(sourceColumn),
    recertEvidence: evidenceText(value.recertEvidence, value.recertSource, value.recertWorkflow, value.reviewEvidence),
    healthEvidence: evidenceText(value.healthEvidence, value.qualityEvidence, value.testRun, value.qualityRunId),
    sox: Boolean(value.sox || value.soxRelevant || value.tags?.includes?.("SOX")),
    controls: arrayValue(value.controls),
    linkedAssets: arrayValue(value.linkedAssets).map(normalizeLinkedAsset),
    activity: arrayValue(value.activity),
  };
}

function cdePriorityRank(cde) {
  const normalizedName = text(cde.name).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const normalizedColumn = text(cde.column).toLowerCase();
  const exactRank = CDE_PRIORITY.indexOf(normalizedName);
  if (exactRank >= 0) return exactRank;
  const containsRank = CDE_PRIORITY.findIndex((label) =>
    normalizedName.includes(label.replace(/[()]/g, "").trim()),
  );
  if (containsRank >= 0) return containsRank;
  if (normalizedColumn.includes("net_revenue")) return 0;
  if (normalizedColumn.includes("customer_id")) return 1;
  if (normalizedColumn.includes("lifetime_value")) return 2;
  if (normalizedColumn.includes("compensation_band")) return 3;
  if (normalizedColumn.includes("gross_total") || normalizedColumn.includes("order_total")) return 4;
  return CDE_PRIORITY.length;
}

export function sortCdesForDisplay(cdes) {
  return [...cdes].sort(
    (left, right) => cdePriorityRank(left) - cdePriorityRank(right) || text(left.name).localeCompare(text(right.name)),
  );
}

/**
 * The registry rows: the CDE dashboard `items` list is canonical; the
 * taxonomy overview's embedded `cdes` list is the fallback for older
 * payload shapes. Both normalize to the same row shape.
 */
export function cdeRowsFromPayloads(dashboardPayload, overviewPayload) {
  const dashboard =
    dashboardPayload && typeof dashboardPayload === "object" && "data" in dashboardPayload
      ? dashboardPayload.data
      : dashboardPayload;
  const items = arrayValue(dashboard?.items);
  if (items.length) return sortCdesForDisplay(items.map(normalizeCdeRow));
  const overview =
    overviewPayload && typeof overviewPayload === "object" && "data" in overviewPayload
      ? overviewPayload.data
      : overviewPayload;
  const fallback = arrayValue(
    overview?.cdes || overview?.criticalDataElements || overview?.criticalDataElementRegistry,
  );
  return sortCdesForDisplay(fallback.map(normalizeCdeRow));
}

export function cdeSourceSummary(cde = {}) {
  // Source backing is its own signal — untagged rows get actionable copy in
  // the tooltip, never a value-cell instruction (legacy G4/G13).
  return cde.sourceBacked || cde.column
    ? "Source: tagged column"
    : "Source: not tagged — tag cde_source_column on the asset";
}

export function cdeRecertEvidenceSummary(cde = {}) {
  return text(cde.recertEvidence) || "Recertification workflow evidence unavailable";
}

export function cdeHealthEvidenceSummary(cde = {}) {
  return text(cde.healthEvidence) || "Quality/test-run evidence unavailable";
}

export function cdeLastReviewSummary(cde = {}) {
  const raw = text(cde.lastReview);
  if (!raw || raw.toLowerCase() === "unavailable") return "No review recorded yet";
  return `Reviewed ${compactDate(raw) || raw}`;
}

/* ------------------------------------------------------------------ */
/* CSV export                                                           */
/* ------------------------------------------------------------------ */

function csvCell(value) {
  const raw = value == null ? "" : String(value);
  return /[",\n]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

/**
 * Client-side CSV of the visible registry rows — the export the old
 * permanently-disabled Download button pretended to need a job for. Built
 * from the SAME normalized rows the table renders, so the file can never
 * disagree with the screen.
 */
export function buildCdeCsv(rows) {
  const header = [
    "name",
    "source_of_record_column",
    "source_asset_fqn",
    "domain",
    "owner",
    "sensitivity_label",
    "criticality",
    "recertification",
    "certification",
    "last_review",
    "sox",
  ];
  const lines = rows.map((row) =>
    [
      row.name,
      row.column || "Not tagged",
      sourceAssetFqnForCde(row),
      row.domain,
      row.owner,
      row.sensitivity || "",
      row.criticality || "",
      row.recert,
      row.status,
      row.lastReview || "",
      row.sox ? "yes" : "no",
    ]
      .map(csvCell)
      .join(","),
  );
  return [header.join(","), ...lines].join("\n");
}
