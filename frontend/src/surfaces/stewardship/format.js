/*
 * surfaces/stewardship/format.js — pure presentation + queue-model helpers
 * for the Stewardship surface (Wave C3). Ported from the deleted
 * components/GovernanceWorkspace.jsx so the semantics (priority/SLA tones,
 * GOV-id compression, validation-seed rejection, assigned-to-me identity
 * matching) survive the rewrite verbatim. No React, no fetches.
 */

export function textValue(value, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

/* ------------------------------------------------------------------ */
/* Dates                                                                */
/* ------------------------------------------------------------------ */

// Always UTC with an explicit label, matching the Evidence surface. A
// browser-local, year-less rendering made adjacent stored timestamps read
// as one timestamp drifting with the wall clock (persona-audit P2).
export function formatShortDate(value = "") {
  const text = textValue(value);
  if (!text) return "";
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

/* ------------------------------------------------------------------ */
/* Priority                                                             */
/* ------------------------------------------------------------------ */

export function priorityTone(priority = "") {
  const value = String(priority || "").toLowerCase();
  // p0 is the triage picker's most-urgent value; same visual tone as p1.
  if (value.includes("p0") || value.includes("p1") || value.includes("crit") || value.includes("high")) return "high";
  if (value.includes("p2") || value.includes("medium")) return "medium";
  if (value.includes("p3") || value.includes("low")) return "low";
  return "unassigned";
}

export function priorityShortLabel(priority = "") {
  const value = String(priority || "").toLowerCase();
  if (value.includes("p0")) return "P0";
  if (value.includes("p1") || value.includes("crit") || value.includes("high")) return "P1";
  if (value.includes("p2") || value.includes("medium")) return "P2";
  if (value.includes("p3") || value.includes("low")) return "P3";
  return textValue(priority, "—");
}

// Current priority as a picker value: "p0"–"p3" or "" for unassigned.
export function priorityPickerValue(priority = "") {
  const short = priorityShortLabel(priority).toLowerCase();
  return /^p[0-3]$/.test(short) ? short : "";
}

const PRIORITY_BADGE_TONES = { high: "bad", medium: "warn", low: "info", unassigned: "muted" };

export function priorityBadgeTone(priority = "") {
  return PRIORITY_BADGE_TONES[priorityTone(priority)] || "muted";
}

/* ------------------------------------------------------------------ */
/* SLA                                                                  */
/* ------------------------------------------------------------------ */

export function slaTone(item = {}) {
  const state = String(item.slaState || "").toLowerCase();
  if (["crit", "critical", "overdue", "breach"].some((term) => state.includes(term))) return "crit";
  if (["warn", "warning", "today"].some((term) => state.includes(term))) return "warn";
  if (["good", "ok", "healthy"].some((term) => state.includes(term))) return "good";
  const dueAt = item.dueAt ? new Date(item.dueAt).getTime() : Number.NaN;
  if (Number.isFinite(dueAt)) {
    const hours = (dueAt - Date.now()) / 36e5;
    if (hours < 0) return "crit";
    if (hours <= 24) return "warn";
    return "good";
  }
  return "muted";
}

const SLA_BADGE_TONES = { crit: "bad", warn: "warn", good: "good", muted: "muted" };

export function slaBadgeTone(item = {}) {
  return SLA_BADGE_TONES[slaTone(item)] || "muted";
}

function dueLabel(item = {}) {
  const due = formatShortDate(item.dueAt);
  return due ? `Due ${due}` : "Due not set";
}

export function slaLabel(item = {}) {
  return textValue(item.sla || item.slaLabel || item.dueLabel, dueLabel(item));
}

// Tooltip explaining a derived SLA. Only present when the backend flags the
// value as coming from the default 7-day policy — never for recorded SLAs.
export function slaPolicyNote(item = {}) {
  return textValue(item.slaPolicy) === "default_7d"
    ? "Default 7-day SLA derived from created_at; no explicit due date is recorded for this request."
    : "";
}

export function hasSlaEvidence(item = {}) {
  return Boolean(
    textValue(item.sla || item.slaLabel || item.dueLabel || item.slaState || item.dueAt),
  );
}

/* ------------------------------------------------------------------ */
/* Identity / ids                                                       */
/* ------------------------------------------------------------------ */

export function workItemKind(item = {}) {
  return textValue(item.kind || item.issue || item.rawTitle || item.title, "Governance work item");
}

export function workItemAssigned(item = {}) {
  // No requester fallback: showing the requester as the assignee made
  // "My work" counts false and painted unassigned work as owned.
  return textValue(
    item.assigned || item.assignee || item.assignedTo || item.team || item.ownerTeam,
    "Unassigned",
  );
}

export function workItemFullId(item = {}) {
  return textValue(item.requestId || item.id);
}

export function workItemDisplayId(item = {}) {
  const requestId = textValue(item.requestId || item.id, "—");
  const evidenceMatch = requestId.match(/^(?:ax-home-evidence|GOV-HOME-EVIDENCE)-request-(\d+)$/i);
  if (evidenceMatch) return `GOV-${evidenceMatch[1]}`;
  if (requestId.length > 14) {
    // Long store ids (UUID-shaped) compress to GOV-XXXXXXXX from the first
    // eight hex characters. The full id stays reachable via the row tooltip
    // and the detail panel's Copy ID affordance.
    const hex = requestId.replace(/[^0-9a-f]/gi, "");
    if (hex.length >= 8) return `GOV-${hex.slice(0, 8).toUpperCase()}`;
    return `${requestId.slice(0, 11)}…`;
  }
  return requestId;
}

/** True when a `?item=` param addresses this work item (display or full id). */
export function matchesItemParam(item, param) {
  const wanted = textValue(param);
  if (!wanted) return false;
  const lowered = wanted.toLowerCase();
  return (
    workItemFullId(item).toLowerCase() === lowered ||
    workItemDisplayId(item).toLowerCase() === lowered
  );
}

// Map a display status ("Pending", "Resolved", …) to the PATCH-allowed set.
// The status field is required on the PATCH body, so triage-only updates
// (assign / priority) re-send the current status unchanged.
export function patchableStatus(status = "") {
  const value = textValue(status).toLowerCase();
  return ["pending", "approved", "rejected", "resolved", "closed"].includes(value) ? value : "pending";
}

export function looksLikeEmail(value = "") {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(textValue(value));
}

/* ------------------------------------------------------------------ */
/* Current user                                                         */
/* ------------------------------------------------------------------ */

export function normalizeCurrentUser(value = {}) {
  const user = /** @type {Record<string, any>} */ (value && typeof value === "object" ? value : {});
  const email = textValue(user.email || user.userEmail || user.actorEmail).toLowerCase();
  const name = textValue(user.name || user.userName || user.actorName || user.displayName).toLowerCase();
  const role = textValue(user.role || user.actorRole);
  const aliases = new Set();
  if (email) {
    aliases.add(email);
    aliases.add(email.split("@")[0]);
  }
  if (name) {
    aliases.add(name);
    name.split(/\s+/).filter(Boolean).forEach((part) => aliases.add(part));
  }
  return { email, name, role, aliases: [...aliases].filter((item) => item.length >= 3) };
}

export function isAssignedToUser(item = {}, currentUser = {}) {
  const assigned = workItemAssigned(item).toLowerCase();
  if (!assigned || assigned === "unassigned") return false;
  if (item.assignedToMe === true) return true;
  const identity = normalizeCurrentUser(currentUser);
  if (!identity.aliases.length) return false;
  return identity.aliases.some((alias) => assigned.includes(alias));
}

export function mutationRole(currentUser = {}) {
  return textValue(currentUser?.role || currentUser?.actorRole || "");
}

export function canMutateRequests(currentUser = {}) {
  return /\b(?:admin|steward)\b/i.test(mutationRole(currentUser));
}

// New work items can be filed by writers too — the backend create endpoint
// only requires can-mutate (writer+), while approve/reject stays steward+.
export function canFileWorkItems(currentUser = {}) {
  return /\b(?:admin|steward|writer)\b/i.test(mutationRole(currentUser));
}

/* ------------------------------------------------------------------ */
/* Validation-seed / prototype rejection                                */
/* ------------------------------------------------------------------ */

export function hasNonAuthoritativeWorkItemMarker(...values) {
  const haystack = values
    .map((value) => {
      if (value == null) return "";
      if (typeof value === "object") {
        try {
          return JSON.stringify(value);
        } catch {
          return "";
        }
      }
      return String(value);
    })
    .join(" ")
    .toLowerCase();
  return /prototype|mock|fixture|validation[_\s-]*seed|validation sample|home[_\s-]*northstar[_\s-]*seed|home[_\s-]*evidence[_\s-]*plane|ax[_\s-]*home[_\s-]*seed/.test(
    haystack,
  );
}

/** @param {Record<string, any>} [item] */
export function isValidationWorkItem(item = {}) {
  if (!item || typeof item !== "object") return false;
  const requestId = textValue(item.requestId || item.id).toLowerCase();
  const source = textValue(item.source || item.provenance?.source || item.meta?.source).toLowerCase();
  return item.validationSample === true || hasNonAuthoritativeWorkItemMarker(requestId, source, item);
}

export function customerSafeEvidenceSource(source = "") {
  const text = textValue(source, "Unavailable");
  if (/home-evidence-plane|home-northstar-seed|seed|fixture|prototype|mock/i.test(text)) {
    return "Evidence source unavailable";
  }
  if (/metadata_audit|metadata audit/i.test(text)) return "Governance audit log";
  return text;
}

/* ------------------------------------------------------------------ */
/* Mutation failure copy                                                */
/* ------------------------------------------------------------------ */

// Backend 5xx bodies can carry raw exception text ("TypeError:
// DualWriteGovernanceStore…"). That text must never reach the UI: keep the
// request id for support correlation, swap the message for human copy.
function looksLikeRawException(message) {
  return /\b[A-Z][A-Za-z]*(?:Error|Exception)\b|Traceback|\bNoneType\b/.test(String(message || ""));
}

export function humanMutationError(error, fallback) {
  const requestId = textValue(
    error?.httpRequestId || error?.clientRequestId || error?.meta?.httpRequestId,
  );
  const detail = textValue(error?.detailMessage);
  const status = Number(error?.status);
  // Server copy is kept only for deliberate 4xx messages (permissions,
  // validation) that do not look like a stringified exception; everything
  // else gets the human fallback.
  const base =
    detail && Number.isFinite(status) && status > 0 && status < 500 && !looksLikeRawException(detail)
      ? detail
      : fallback;
  return requestId ? `${base} (Request ID: ${requestId})` : base;
}

/* ------------------------------------------------------------------ */
/* Queue item model                                                     */
/* ------------------------------------------------------------------ */

function assetNameFromFqn(value = "") {
  const parts = String(value || "").split(".").filter(Boolean);
  return parts[parts.length - 1] || "Unassigned asset";
}

/** Normalize one workbench request into the queue-row shape. */
export function normalizeWorkItem(item = {}) {
  const requestId = textValue(item.requestId || item.id);
  const assetFqn = textValue(item.assetFqn || item.asset);
  const kind = workItemKind(item);
  return {
    ...item,
    itemKind: "request",
    requestId,
    id: requestId,
    title: textValue(item.title || kind, "Governance work item"),
    kind,
    typeLabel: textValue(item.type || item.requestType || item.category),
    detail: textValue(item.detail || item.note || item.newComment),
    priority: textValue(item.priority, "Unassigned"),
    status: textValue(item.status, "Unavailable"),
    requester: textValue(item.requester || item.createdBy),
    createdAt: textValue(item.createdAt),
    dueAt: textValue(item.dueAt),
    assetFqn,
    assetName: assetNameFromFqn(assetFqn),
    assigned: workItemAssigned(item),
    sla: textValue(item.sla || item.slaLabel || item.dueLabel),
    slaState: textValue(item.slaState),
    slaPolicy: textValue(item.slaPolicy),
    age: textValue(item.age),
    evidence: textValue(item.evidence || item.businessContext || item.detail || item.note),
    suggestedActions: Array.isArray(item.suggestedActions) ? item.suggestedActions : [],
    validationSample: isValidationWorkItem(item),
  };
}

/**
 * Map a glossary term awaiting review into the same queue (Inbox absorbed:
 * term reviews are typed work items — COHESION "one queue, two lenses").
 */
export function termReviewItem(term = {}, index = 0) {
  const termId = textValue(term.termId);
  const name = textValue(term.term || term.name, "Glossary term");
  return {
    itemKind: "term-review",
    id: termId ? `term-${termId}` : `term-${index}`,
    termId,
    title: name,
    kind: name,
    status: textValue(term.reviewState || term.status, "Draft"),
    detail: textValue(term.definition),
    ownerEmail: textValue(term.ownerEmail),
    assigned: textValue(term.ownerEmail, "Unassigned"),
    assetFqn: "",
    priority: "",
    requestId: "",
  };
}

/* ------------------------------------------------------------------ */
/* Lenses (one queue, two lenses + severity slices)                     */
/* ------------------------------------------------------------------ */

export function isP1WorkItem(item = {}) {
  return item.itemKind === "request" && priorityTone(item.priority) === "high";
}

export function isOverdueWorkItem(item = {}) {
  return item.itemKind === "request" && slaTone(item) === "crit";
}

/**
 * `lensKey` ∈ all | p1 | overdue | mine. "mine" is the absorbed-inbox lens
 * (?assignee=me); term reviews count as "mine" when the signed-in user is
 * the term owner. p1/overdue only ever match requests — term reviews carry
 * no priority/SLA evidence and are never inferred into those slices.
 */
export function matchesLens(item = {}, lensKey = "all", currentUser = {}) {
  if (lensKey === "p1") return isP1WorkItem(item);
  if (lensKey === "overdue") return isOverdueWorkItem(item);
  if (lensKey === "mine") {
    if (item.itemKind === "term-review") {
      const identity = normalizeCurrentUser(currentUser);
      const owner = textValue(item.ownerEmail).toLowerCase();
      return Boolean(owner) && identity.aliases.some((alias) => owner.includes(alias));
    }
    return isAssignedToUser(item, currentUser);
  }
  return true;
}

export function lensCounts(items = [], currentUser = {}) {
  return {
    all: items.length,
    p1: items.filter((item) => matchesLens(item, "p1", currentUser)).length,
    overdue: items.filter((item) => matchesLens(item, "overdue", currentUser)).length,
    mine: items.filter((item) => matchesLens(item, "mine", currentUser)).length,
  };
}

/** Sort: explicit sortOrder, then priority tone, then due date. */
export function sortQueue(items = []) {
  const order = { high: 0, medium: 1, low: 2 };
  return [...items].sort((a, b) => {
    const explicitA = Number(a.sortOrder);
    const explicitB = Number(b.sortOrder);
    if (Number.isFinite(explicitA) && Number.isFinite(explicitB) && explicitA !== explicitB) {
      return explicitA - explicitB;
    }
    const priorityDelta = (order[priorityTone(a.priority)] ?? 3) - (order[priorityTone(b.priority)] ?? 3);
    if (priorityDelta) return priorityDelta;
    const aDue = new Date(a.dueAt || "9999-12-31").getTime();
    const bDue = new Date(b.dueAt || "9999-12-31").getTime();
    return aDue - bDue;
  });
}

/* ------------------------------------------------------------------ */
/* Scope split caption (backend openRequestScope)                       */
/* ------------------------------------------------------------------ */

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

// The workbench deliberately shows ALL open requests while estate KPIs count
// only the visible estate. Surfacing the split is what prevents "40 vs 21"
// confusion.
export function scopeSummary(openRequestScope) {
  const scope =
    openRequestScope && typeof openRequestScope === "object" ? openRequestScope : null;
  if (!scope) return "";
  const visible = finiteNumber(scope.visibleOpenCount);
  const outOfScope = finiteNumber(scope.outOfScopeOpenCount);
  const caption = textValue(scope.caption);
  if (visible !== null && outOfScope !== null) {
    // Audit B1: spell out that this partitions OPEN CHANGE REQUESTS (a subset
    // of the work queue, which also contains term reviews) — the bare
    // "N in the visible estate · M out-of-scope" read as a partition of the
    // "N work items" header it sits under (an impossible 1+1=6).
    const totalOpen = visible + outOfScope;
    return `${totalOpen} open change request${totalOpen === 1 ? "" : "s"}: ${visible} in the visible estate · ${outOfScope} on out-of-scope assets${caption ? ` (${caption})` : ""}`;
  }
  return caption;
}

/* ------------------------------------------------------------------ */
/* Detail payload                                                       */
/* ------------------------------------------------------------------ */

// Comment timeline for the selected work item. The backend detail payload
// carries `comments` (review notes + request-linked audit events); when it
// doesn't, fall back to the record's own reviewNote so a just-written
// comment is never invisible.
export function workItemComments(detail = null) {
  const list = Array.isArray(detail?.comments)
    ? detail.comments.filter((comment) => textValue(comment?.text))
    : [];
  if (list.length) return list;
  const reviewNote = textValue(detail?.reviewNote);
  if (!reviewNote) return [];
  return [
    {
      id: "review-note-local",
      author: textValue(detail?.reviewedBy),
      at: textValue(detail?.reviewedAt),
      text: reviewNote,
      kind: "review-note",
    },
  ];
}

/* ------------------------------------------------------------------ */
/* Audit trail (Evidence ledger join)                                   */
/* ------------------------------------------------------------------ */

// Canonical Evidence event address: AUD- + 8 hex chars. Defensive format
// check (kept even though the backend emits the field) so a malformed id
// can never mint a dead /evidence?event= link.
const AUDIT_DISPLAY_ID_PATTERN = /^AUD-[0-9A-F]{8}$/i;

/** "" unless the value is a well-formed AUD display id (uppercased). */
export function auditChipId(value = "") {
  const text = textValue(value);
  return AUDIT_DISPLAY_ID_PATTERN.test(text) ? text.toUpperCase() : "";
}

/** "metadata_update-requested" → "Metadata update requested". */
export function humanizeCommentText(text = "") {
  const value = textValue(text);
  // Seeded comment bodies are sometimes bare event slugs ("task-created",
  // "task-triage-updated") — humanize those to sentence case; leave real
  // prose untouched (no raw enums in the UI — verifier).
  if (/^[a-z]+(?:[-_][a-z]+)+$/.test(value)) {
    return humanizeAuditAction(value);
  }
  return value;
}

export function humanizeAuditAction(action = "") {
  const text = textValue(action).replace(/[_\s-]+/g, " ").trim();
  if (!text) return "Audit event";
  const lower = text.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/**
 * Normalize the workbench detail payload's `auditTrail` rows
 * ({displayAuditId, auditEventId, action, createdAt}) for the mini-hub's
 * Evidence trail block. Feature-detecting: payloads predating the backend
 * join simply have no `auditTrail` and yield [] — the panel renders its
 * honest empty state instead of inventing events. `displayAuditId` stays ""
 * for rows the backend could not map to the Evidence ledger, so the render
 * layer shows them as text (no dead links).
 */
export function workItemAuditTrail(item = null) {
  const raw = Array.isArray(item?.auditTrail) ? item.auditTrail : [];
  return raw
    .filter((row) => row && typeof row === "object")
    .map((row, index) => {
      const displayAuditId = auditChipId(row.displayAuditId);
      const auditEventId = textValue(row.auditEventId);
      return {
        key: displayAuditId || auditEventId || `audit-${index}`,
        displayAuditId,
        auditEventId,
        action: humanizeAuditAction(row.action),
        at: textValue(row.createdAt || row.at),
      };
    });
}

export function openingEvidenceFacts(item = {}) {
  if (!item) return [];
  const source = customerSafeEvidenceSource(
    textValue(
      item.source || item.evidenceSource || item.provenance?.source || item.meta?.source,
      "Unavailable",
    ),
  );
  const observedAt = textValue(
    item.observedAt || item.evidenceObservedAt || item.createdAt || item.updatedAt,
    "Timestamp unavailable",
  );
  return [
    ["Trigger", workItemKind(item)],
    ["Source", source],
    ["Observed", formatShortDate(observedAt) || observedAt],
    ["Affected asset", textValue(item.assetFqn || item.assetName, "Asset unavailable")],
  ];
}

/* ------------------------------------------------------------------ */
/* Optimistic cache patch                                               */
/* ------------------------------------------------------------------ */

/**
 * Patch one request inside a workbench payload (optimistic update for
 * useAxiomMutation). Handles both the bare `{requests}` shape and the
 * envelope `{data: {requests}}` shape without mutating the original.
 */
export function patchWorkbenchRequests(payload, requestId, patch) {
  if (!payload || typeof payload !== "object") return payload;
  const patchList = (container) => {
    if (!container || !Array.isArray(container.requests)) return container;
    return {
      ...container,
      requests: container.requests.map((item) =>
        textValue(item?.requestId || item?.id) === requestId ? { ...item, ...patch } : item,
      ),
    };
  };
  if (payload.data && typeof payload.data === "object" && Array.isArray(payload.data.requests)) {
    return { ...payload, data: patchList(payload.data) };
  }
  return patchList(payload);
}
