/*
 * app-shell/AxiomAiDock.jsx — the floating Axiom AI chat + FAB (Wave B1).
 *
 * Extracted from AppFrame.jsx (~700 inlined lines) with behavior preserved:
 * drag/clamp positioning, resize re-clamping, per-route prompt copy, the
 * thinking-stage progress lines, evidence chips + the generated-SQL evidence
 * detail, the accuracy disclaimer. Refactor is intentionally gentle — the
 * only substantive changes are (a) class names move to the clean ax-ai-*
 * system prefix (styles in app-shell/shell.css), and (b) navigation goes
 * through the nav fabric: evidence asset chips open the ?peek= drawer (the
 * old drawer behavior), surface chips navigate(surfaceRef).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { AxiomAiMark } from "../components/northstar/AxiomAiPanel";
import { MarkdownBlock } from "../components/primitives/MarkdownBlock";
import { useAxiomAiConversation } from "../hooks/useAxiomAiConversation";
import { readPref, writePref } from "../lib/prefs.js";
import { useAxiomNavigate, usePeek } from "../nav/useAxiomNavigate.js";

const AI_CHAT_SIZE = { width: 360, height: 432 };
const AI_CHAT_WIDE_SIZE = { width: 440, height: 640 };
// Resize bounds. Min keeps the transcript + input usable; max is clamped again
// to the viewport at drag time so the dock can never exceed the visible area.
const AI_CHAT_MIN = { width: 320, height: 360 };
const AI_CHAT_MAX = { width: 720, height: 960 };
// Viewport gutters — SHARED by clampAiChatPosition (drag + ResizeObserver) and
// the resize handler, so the two paths agree. A mismatch here made a south-edge
// resize get yanked ~52px on the next ResizeObserver tick (review F5).
const AI_DOCK_GUTTER = { side: 12, top: 12, bottom: 64 };
// Resize grips: 4 edges + 4 corners, so a bottom-right-anchored dock can be
// grown from its top/left toward screen centre (not just shrunk from the se).
const RESIZE_HANDLES = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];

// setPointerCapture throws NotFoundError if the pointer is no longer active
// (e.g. released between events). Never let that surface as an unhandled error.
function capturePointer(event) {
  try {
    event.currentTarget.setPointerCapture?.(event.pointerId);
  } catch {
    /* pointer already released — capture is a best-effort nicety */
  }
}

// Active facet scope from the Discover URL (the URL is the source of truth for
// Discover state). Only present filters are included, so an unfiltered page
// sends no scope. Kept small + string-only for the backend's sanitizer.
//
// CALLER MUST gate this to the Discover surface: `q`/`domain` are Discover's
// facet grammar, but Glossary/Evidence/Lineage reuse the same param NAMES for
// their own search boxes. Reading them elsewhere would forward another
// surface's search text as an authoritative asset filter the user never set.
export function scopeFromSearch(search) {
  const params = new URLSearchParams(search || "");
  const list = (key) => params.getAll(key).map((value) => value.trim()).filter(Boolean);
  const single = (key) => String(params.get(key) || "").trim();
  const scope = {};
  // Real Discover array facets (discoveryParams.js). `view` = saved governance
  // views ("Needs owner", …) — a genuine active filter that changes which
  // assets are shown, so it MUST stay part of "here". type/catalog were missing
  // before, so a user filtered by those got an incomplete "here".
  for (const key of ["domain", "criticality", "tier", "certification", "sensitivity", "view", "type", "catalog"]) {
    const values = list(key);
    if (values.length) scope[key] = values;
  }
  const owner = single("owner");
  if (owner) scope.owner = owner;
  const query = single("q");
  if (query) scope.query = query;
  return Object.keys(scope).length ? scope : null;
}

// Per-surface grounding copy + suggested prompts, keyed by the NEW surface
// ids (nav/routes.js). Content is unchanged from AppFrame's AI_ROUTE_COPY —
// only the stewardship/glossary/evidence keys were renamed with their
// surfaces (assets = the old "entity" copy).
const AI_ROUTE_COPY = {
  home: {
    emptyLive: "Ask about executive-facing dashboards, owner risk, freshness, and certification using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about a dashboard, owner, or risk signal...",
    // Overview surface — no single dashboard/metric is selected here, so every
    // prompt must be answerable from the estate as a whole. (Prompts that named
    // "the selected X" made Genie pick an arbitrary asset — see the per-asset
    // copy below for when a concrete asset IS in scope.)
    prompts: [
      "Which executive dashboards have at-risk or stale sources this week?",
      "Which uncertified tables are queried by executives?",
      "Summarize PII coverage across customer domains.",
      "Which critical metrics are overdue for certification?",
    ],
  },
  discovery: {
    emptyLive: "Ask about search results, asset trust signals, owners, glossary coverage, or inaccessible records using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about search results, owners, or glossary coverage...",
    prompts: [
      "Which visible assets have the strongest trust signal?",
      "Show customer assets without a certified owner.",
      "Explain why a deleted or inaccessible result appears.",
      "Which assets in these results have incomplete lineage?",
    ],
  },
  stewardship: {
    emptyLive: "Ask about stewardship queues, review work, SLA risk, owners, and request evidence using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about queue risk, owners, or review evidence...",
    prompts: [
      "Which stewardship items need attention first?",
      "Summarize overdue owner or certification work.",
      "What evidence backs the highest-priority open request?",
      "Which lineage gaps should a steward review?",
    ],
  },
  glossary: {
    emptyLive: "Ask about glossary terms, CDEs, reviewers, version history, and asset associations using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about a term, CDE, reviewer, or linked asset...",
    prompts: [
      "Which CDEs are due for review?",
      "Which glossary terms have no linked assets?",
      "Summarize reviewer status for critical CDEs.",
      "Which glossary term has the most asset coverage?",
    ],
  },
  lineage: {
    emptyLive: "Ask about lineage hops, impact, provenance, and column completeness using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about upstream, downstream, or impact...",
    // Lineage OVERVIEW (no asset opened). "the selected table" / "a schema
    // change" had no referent here, so Genie chose an arbitrary asset. Each
    // prompt below is a one-shot aggregate over axiom_ai_lineage_edges
    // (source/target/lineage_source/event_time/availability_state) — every one
    // was live-verified to resolve deterministically in a single Genie pass.
    // Superlative/anti-join phrasings ("widest impact", "no consumers") made
    // Genie loop and time out, and column-completeness/restricted-node data
    // isn't in this table — so those were dropped. Open an asset and the
    // per-asset prompts below name it explicitly.
    prompts: [
      "Which assets have the most downstream consumers?",
      "Which assets have the most upstream sources?",
      "What are the most recent lineage changes?",
      "Which lineage relationships are restricted or unavailable?",
    ],
  },
  evidence: {
    emptyLive: "Ask about audit events, control evidence, grants, notebook activity, and export context using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about audit evidence, grants, or exports...",
    prompts: [
      "Summarize audit evidence for the recent activity window.",
      "Which high-severity events need review?",
      "What provenance backs recent audit exports?",
      "Show recent permission or grant activity.",
    ],
  },
  admin: {
    emptyLive: "Ask about runtime health, integrations, policy coverage, setup diagnostics, and control evidence using governed metadata. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about runtime jobs, integrations, or policies...",
    prompts: [
      "Which runtime job or integration needs attention?",
      "Summarize control coverage gaps.",
      "What setup diagnostic should an admin inspect first?",
      "Which policies are stale or missing evidence?",
    ],
  },
  assets: {
    emptyLive: "Ask about the selected asset's ownership, schema, usage, quality, and governance evidence. I read Unity Catalog metadata only — no customer or PII row content.",
    placeholder: "Ask about this asset's owner, schema, or evidence...",
    prompts: [
      "Summarize this asset's governance evidence.",
      "Who owns this asset and what changed recently?",
      "Which schema or quality signals need review?",
      "What related assets should I inspect next?",
    ],
  },
};

const DEFAULT_AI_ROUTE_COPY = AI_ROUTE_COPY.home;

function resolveAiRouteCopy(surface) {
  return AI_ROUTE_COPY[surface] || DEFAULT_AI_ROUTE_COPY;
}

function assetShortName(assetFqn) {
  const text = String(assetFqn || "").trim();
  if (!text) return "";
  const parts = text.split(".");
  return parts[parts.length - 1] || text;
}

// Per-ASSET prompts: when the user is on an asset page (or has one peeked),
// the suggestions name that specific table so the click is unmistakably about
// what they're looking at. The backend also receives the FQN as context, so
// "this asset" resolves server-side even for a free-typed question.
function assetPromptsFor(assetFqn) {
  const name = assetShortName(assetFqn);
  if (!name) return null;
  return {
    emptyLive: `Ask about ${name} — ownership, certification, upstream sources, quality, and governance evidence. I read Unity Catalog metadata only — no customer or PII row content.`,
    placeholder: `Ask about ${name}...`,
    prompts: [
      `Who owns ${name} and is it certified?`,
      `What feeds ${name} and what is downstream?`,
      `What governance evidence and open work exist for ${name}?`,
      `Which quality or schema signals on ${name} need review?`,
    ],
  };
}

function defaultAiChatPosition() {
  if (typeof window === "undefined") return { top: 128, left: 960 };
  const size = window.innerWidth >= 2200 ? AI_CHAT_WIDE_SIZE : AI_CHAT_SIZE;
  const right = 22;
  const bottom = window.innerWidth >= 2200 ? 88 : 90;
  return {
    top: Math.max(82, window.innerHeight - size.height - bottom),
    left: Math.max(12, window.innerWidth - size.width - right),
  };
}

function clampAiChatPosition(position) {
  if (typeof window === "undefined") return position;
  const padding = AI_DOCK_GUTTER.side;
  const footerReserve = AI_DOCK_GUTTER.bottom;
  const defaultSize = window.innerWidth >= 2200 ? AI_CHAT_WIDE_SIZE : AI_CHAT_SIZE;
  const width = Number(position.width) || defaultSize.width;
  const height = Number(position.height) || defaultSize.height;
  const maxLeft = Math.max(padding, window.innerWidth - width - padding);
  const maxTop = Math.max(AI_DOCK_GUTTER.top, window.innerHeight - height - footerReserve);
  return {
    left: Math.min(Math.max(position.left, padding), maxLeft),
    top: Math.min(Math.max(position.top, AI_DOCK_GUTTER.top), maxTop),
  };
}

function compactEvidenceValue(value) {
  if (value == null || value === "") return "Unavailable";
  if (Array.isArray(value)) return value.map((item) => compactEvidenceValue(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function evidenceRowsFor(item) {
  if (Array.isArray(item?.resultRows)) return item.resultRows;
  if (Array.isArray(item?.rows)) return item.rows;
  if (Array.isArray(item?.results)) return item.results;
  return [];
}

function evidenceColumnsFor(item, rows = []) {
  const explicit = Array.isArray(item?.resultColumns) ? item.resultColumns : [];
  if (explicit.length) return explicit.map((column) => String(column || "").trim()).filter(Boolean);
  return Array.from(new Set(rows.flatMap((row) => Object.keys(row || {})))).slice(0, 8);
}

function normalizeAiEvidenceItem(item, index) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  const rawType = String(item.type || item.kind || item.metric || "").trim().toLowerCase();
  const rawMetric = String(item.metric || "").trim().toLowerCase();
  const assetFqn = String(item.assetFqn || item.asset_fqn || item.fqn || "").trim();
  const rawLabel = String(item.label || item.title || item.name || item.id || item.statementId || assetFqn || "").trim();
  const isQueryEvidence =
    rawType.includes("genie") ||
    rawType.includes("query") ||
    rawMetric === "generatedsql" ||
    Boolean(item.sql || item.statementId || item.statement_id);
  const label = isQueryEvidence
    ? String(item.title || item.label || "Generated SQL evidence").trim()
    : rawLabel || `Evidence ${index + 1}`;
  if (!label) return null;
  if (isQueryEvidence) {
    return {
      key: `${label}-${item.statementId || item.statement_id || index}`,
      label,
      routeLabel: "Open query evidence",
      target: { kind: "query-evidence", evidence: item },
    };
  }
  if (assetFqn || rawType === "asset" || /\w+\.\w+\.\w+/.test(label)) {
    return {
      key: `${label}-${index}`,
      label,
      routeLabel: "Open asset",
      target: { kind: "asset", assetFqn: assetFqn || label },
    };
  }
  if (rawType.includes("work") || /^SI-\d+/i.test(label)) {
    return {
      key: `${label}-${index}`,
      label,
      routeLabel: "Open Stewardship",
      target: { kind: "surface", surface: "stewardship" },
    };
  }
  if (rawType.includes("audit") || rawType.includes("event")) {
    return {
      key: `${label}-${index}`,
      label,
      routeLabel: "Open Evidence",
      target: { kind: "surface", surface: "evidence" },
    };
  }
  if (rawType.includes("lineage")) {
    return {
      key: `${label}-${index}`,
      label,
      routeLabel: "Open Lineage",
      target: { kind: "surface", surface: "lineage" },
    };
  }
  return { key: `${label}-${index}`, label, routeLabel: "", target: null };
}

function AxiomAiEvidenceDetail({ evidence, onClose }) {
  if (!evidence) return null;
  const rows = evidenceRowsFor(evidence);
  const columns = evidenceColumnsFor(evidence, rows);
  const visibleRows = rows.slice(0, 4);
  const rowCount = Number.isFinite(Number(evidence.rowCount ?? evidence.totalRowCount))
    ? Number(evidence.rowCount ?? evidence.totalRowCount)
    : rows.length;
  const sql = String(evidence.sql || evidence.generatedSql || "").trim();
  const statementId = String(evidence.statementId || evidence.statement_id || evidence.id || "").trim();
  return (
    <section aria-label="Axiom AI query evidence" className="ax-ai-dock-evidence-detail">
      <header>
        <div>
          <span>Query Evidence</span>
          <strong>{rowCount.toLocaleString()} metadata row{rowCount === 1 ? "" : "s"} returned</strong>
        </div>
        <button aria-label="Close Axiom AI query evidence" onClick={onClose} type="button">
          x
        </button>
      </header>
      {statementId ? <p className="ax-ai-dock-evidence-statement">Statement {statementId}</p> : null}
      {sql ? (
        <pre className="ax-ai-dock-evidence-sql" data-testid="axiom-ai-query-evidence-sql">
          <code>{sql}</code>
        </pre>
      ) : (
        <p className="ax-ai-dock-evidence-empty">Generated SQL was not returned for this evidence record.</p>
      )}
      {visibleRows.length && columns.length ? (
        <div aria-label="Axiom AI query evidence rows" className="ax-ai-dock-evidence-table" role="table">
          <div role="row">
            {columns.map((column) => (
              <span key={column} role="columnheader">{column}</span>
            ))}
          </div>
          {visibleRows.map((row, rowIndex) => (
            <div key={`evidence-row-${rowIndex}`} role="row">
              {columns.map((column) => (
                <span key={`${column}-${rowIndex}`} role="cell">{compactEvidenceValue(row?.[column])}</span>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

// The generated SQL, shown INLINE with the answer (open by default) so the
// user sees how Genie derived it without hunting for a toggle — "more
// information, not less". Collapsible for when they want it out of the way.
function AxiomAiInlineSql({ evidence = [] }) {
  const query = (Array.isArray(evidence) ? evidence : []).find(
    (item) => item && (item.sql || item.generatedSql),
  );
  const sql = String(query?.sql || query?.generatedSql || "").trim();
  if (!sql) return null;
  const statementId = String(query?.statementId || query?.statement_id || "").trim();
  const rowCount = Number(query?.rowCount ?? query?.totalRowCount);
  return (
    <details className="ax-ai-dock-inline-sql" open>
      <summary>
        Generated SQL
        {Number.isFinite(rowCount) ? ` · ${rowCount.toLocaleString()} row${rowCount === 1 ? "" : "s"}` : ""}
        {statementId ? ` · ${statementId.slice(0, 10)}…` : ""}
      </summary>
      <pre className="ax-ai-dock-evidence-sql" data-testid="axiom-ai-inline-sql">
        <code>{sql}</code>
      </pre>
    </details>
  );
}

function AxiomAiEvidenceList({ evidence = [], onOpenEvidence }) {
  const items = evidence
    .map((item, index) => normalizeAiEvidenceItem(item, index))
    .filter(Boolean)
    .slice(0, 4);
  if (!items.length) return null;
  return (
    <div aria-label="Axiom AI evidence" className="ax-ai-dock-evidence">
      {items.map((item) =>
        item.target ? (
          <button key={item.key} onClick={() => onOpenEvidence?.(item.target)} title={item.routeLabel} type="button">
            <span>{item.label}</span>
            <em>{item.routeLabel}</em>
          </button>
        ) : (
          <span className="ax-ai-dock-evidence-chip" key={item.key}>
            {item.label}
          </span>
        ),
      )}
    </div>
  );
}

// Progress copy while the AI provider responds. These lines describe the
// governed-metadata pipeline in general terms only — never name a specific
// table or claim a query happened, because the backend does not return a
// real execution plan and fabricated evidence violates the honesty rule.
// The dock shows the REAL Genie pipeline stages as they arrive (via the
// `stage` prop, updated by the polling layer): "Selecting relevant tables" →
// "Generating the SQL query" → "Running the query". Completed stages are
// checked; the current one carries the caret. Grounded (instant) answers never
// reach a stage, so this just flashes a brief "Working". No canned animation.
function AxiomAiThinkingStage({ stage = "" }) {
  const [history, setHistory] = useState([]);
  useEffect(() => {
    const next = String(stage || "").trim();
    if (!next) return;
    setHistory((prev) => (prev[prev.length - 1] === next ? prev : [...prev, next]));
  }, [stage]);
  const lines = history.length ? history : ["Preparing your answer"];
  return (
    <div aria-live="polite" className="ax-ai-stage is-thinking" role="status">
      <div className="ax-ai-stage-label">
        <span aria-hidden="true" className="ax-live-dot" />
        {history.length ? "Genie is working" : "Working"}
      </div>
      {lines.map((line, index) => {
        const isLast = index === lines.length - 1;
        return (
          <div className="ax-ai-stage-plan-line" key={`${line}-${index}`} style={{ animationDelay: `${index * 60}ms` }}>
            <span aria-hidden="true">{isLast ? "→" : "✓"}</span>
            <span>
              <span>{line}</span>
              {isLast ? <span aria-hidden="true" className="ax-ai-stage-caret" /> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function AxiomAiMessageList({ messages = [], onOpenEvidence, emptyMessage }) {
  if (!messages.length) {
    return (
      <div className="ax-ai-dock-message tone-assistant is-empty" role="status">
        <strong>
          {emptyMessage ||
            "I answer questions about your governed data using Unity Catalog metadata. I read Unity Catalog metadata only — no customer or PII row content."}
        </strong>
      </div>
    );
  }
  return messages.map((item) => (
    <div
      className={`ax-ai-dock-message tone-${item.role} ${item.pending ? "is-pending" : ""} ${item.error ? "tone-warn" : ""}`.trim()}
      key={item.id}
      role={item.error ? "alert" : "status"}
    >
      <span>{item.role === "user" ? "You" : "Axiom AI"}</span>
      {item.role === "assistant" && item.pending ? (
        <AxiomAiThinkingStage stage={item.stage} />
      ) : (
        <MarkdownBlock className="ax-ai-dock-markdown" source={item.text} />
      )}
      {item.role === "assistant" && !item.pending && !item.error ? (
        <>
          <AxiomAiEvidenceList evidence={item.response?.evidence || []} onOpenEvidence={onOpenEvidence} />
          <AxiomAiInlineSql evidence={item.response?.evidence || []} />
          <em>
            {item.evidenceCount
              ? `${item.evidenceCount} evidence record${item.evidenceCount === 1 ? "" : "s"} returned.`
              : "No evidence records returned for this question."}
          </em>
        </>
      ) : null}
    </div>
  ));
}

// Controlled component: AppShell owns `open` because the frame root must
// reflect it as data-ai-open (legacy per-surface squeeze CSS keys on it) and
// the header's Axiom AI chip opens the dock too.
/**
 * @param {{
 *   surface?: string,
 *   assetFqn?: string,
 *   available?: boolean,
 *   unavailableReason?: string,
 *   open?: boolean,
 *   onOpenChange?: (open?: boolean) => void,
 * }} props
 */
export function AxiomAiDock({
  surface = "home",
  assetFqn = "",
  available = false,
  unavailableReason = "",
  open = false,
  onOpenChange = () => {},
}) {
  const navigate = useAxiomNavigate();
  const { openPeek } = usePeek();

  const setOpen = onOpenChange;
  const [position, setPosition] = useState(() => defaultAiChatPosition());
  // Persisted user size + maximize state (lib/prefs.js). width/height 0 means
  // "use the default size"; the dock stores the chosen size after a resize.
  const [size, setSize] = useState(() => {
    const stored = readPref("aiDockLayout");
    return { width: stored.width || 0, height: stored.height || 0 };
  });
  const [maximized, setMaximized] = useState(() => Boolean(readPref("aiDockLayout").maximized));
  const [infoOpen, setInfoOpen] = useState(false);
  const [evidenceDetail, setEvidenceDetail] = useState(null);
  const chatRef = useRef(null);
  const inputRef = useRef(null);
  const dragRef = useRef(null);
  const resizeRef = useRef(null);

  // Page-awareness context sent with every question so the backend can resolve
  // "this asset"/"this page"/"here" to a concrete scope. Recomputed as the user
  // navigates OR changes filters; memoized so the ask callbacks get a stable
  // reference. `scope` carries the ACTIVE facet filters from the URL (the URL is
  // the state) so "how many assets here lack an owner?" can see the domain the
  // user is filtered to — not just the surface name.
  const location = useLocation();
  // Gate to Discover: only that surface's URL uses the facet grammar
  // scopeFromSearch reads. Elsewhere, `q`/`domain` mean something else entirely.
  const scope = useMemo(
    () => (surface === "discovery" ? scopeFromSearch(location.search) : null),
    [surface, location.search],
  );
  const aiContext = useMemo(
    () => ({
      surface,
      assetFqn: String(assetFqn || "").trim(),
      ...(scope ? { scope } : {}),
    }),
    [surface, assetFqn, scope],
  );
  const aiChat = useAxiomAiConversation();

  // On an asset page (or with a peeked asset), suggestions name that specific
  // table; otherwise fall back to the per-surface copy.
  const assetCopy = surface === "assets" || assetFqn ? assetPromptsFor(assetFqn) : null;
  const routeCopy = assetCopy || resolveAiRouteCopy(surface);
  const prompts = routeCopy.prompts || DEFAULT_AI_ROUTE_COPY.prompts;
  const groundingLine = available
    ? "Grounded in Unity Catalog metadata only - no customer or PII row content"
    : "Unavailable until an evidence-backed Axiom AI endpoint is configured";
  const emptyMessage = available ? routeCopy.emptyLive : unavailableReason;
  const placeholder = routeCopy.placeholder || DEFAULT_AI_ROUTE_COPY.placeholder;

  const askWithContext = useCallback(
    (prompt) => {
      setEvidenceDetail(null);
      void aiChat.ask(prompt, aiContext);
    },
    [aiChat, aiContext],
  );

  // Persist size + maximize whenever they change so the dock restores on reopen.
  useEffect(() => {
    writePref("aiDockLayout", { width: size.width, height: size.height, maximized });
  }, [size.width, size.height, maximized]);

  const toggleMaximize = useCallback(() => {
    setMaximized((current) => !current);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    setInfoOpen(false);
    setEvidenceDetail(null);
    if (typeof window === "undefined") return;
    window.setTimeout?.(() => {
      const trigger = document.querySelector(".ax-ai-chip");
      if (trigger instanceof HTMLElement) trigger.focus();
    }, 0);
  }, [setOpen]);

  const openDock = useCallback(() => {
    setOpen(true);
  }, [setOpen]);

  // Whoever opens the dock (FAB here, or the header's Axiom AI chip via
  // AppShell), position clamping + input focus run on the open transition.
  useEffect(() => {
    if (!open || typeof window === "undefined") return undefined;
    setInfoOpen(false);
    setPosition((current) => clampAiChatPosition(current.left ? current : defaultAiChatPosition()));
    const timer = window.setTimeout(() => {
      const box = chatRef.current?.getBoundingClientRect?.();
      if (box) {
        setPosition((current) => clampAiChatPosition({ ...current, width: box.width, height: box.height }));
      }
      inputRef.current?.focus?.();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [open]);

  const openEvidence = useCallback(
    (target) => {
      if (!target) return;
      if (target.kind === "query-evidence") {
        setEvidenceDetail(target.evidence || {});
        return;
      }
      if (target.kind === "asset" && target.assetFqn) {
        // The old shell opened the Asset 360 drawer; the ?peek= binding is
        // that drawer's addressable successor — user keeps their place.
        openPeek(target.assetFqn);
        return;
      }
      if (target.kind === "surface" && target.surface) {
        close();
        navigate({ surface: target.surface });
      }
    },
    [close, navigate, openPeek],
  );

  // (Removed the lineage force-close: the dock used to snap shut the moment you
  // entered /lineage, so the AI was unreachable exactly where its lineage
  // grounding — "what feeds/depends on this table?" — is most useful. The dock
  // floats/drags over the canvas and does not fight lineage's own side panels.)

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onResize = () => {
      const box = chatRef.current?.getBoundingClientRect?.();
      setPosition((current) =>
        clampAiChatPosition({ ...current, width: box?.width, height: box?.height }),
      );
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onPointerMove = (event) => {
      const drag = dragRef.current;
      if (!drag) return;
      setPosition(
        clampAiChatPosition({
          left: drag.left + event.clientX - drag.x,
          top: drag.top + event.clientY - drag.y,
          width: drag.width,
          height: drag.height,
        }),
      );
    };
    const onPointerUp = () => {
      dragRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, []);

  // Edge/corner resize. `start.dir` is one of n/s/e/w/ne/nw/se/sw. Dragging a
  // west/north edge grows the dock toward screen centre while pinning the
  // opposite edge (left/top move with the size) — the bottom-right-anchored
  // dock could otherwise only SHRINK, since its se corner sits against the
  // viewport edge. Clamps to [AI_CHAT_MIN, AI_CHAT_MAX] and the viewport, and a
  // resize implicitly exits the maximized state.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onPointerMove = (event) => {
      const start = resizeRef.current;
      if (!start) return;
      const dir = start.dir || "se";
      const innerW = window.innerWidth;
      const innerH = window.innerHeight;
      const rightEdge = start.left + start.width;
      const bottomEdge = start.top + start.height;
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      let width = start.width;
      let height = start.height;
      let left = start.left;
      let top = start.top;
      if (dir.includes("e")) width = start.width + dx;
      if (dir.includes("w")) width = start.width - dx;
      if (dir.includes("s")) height = start.height + dy;
      if (dir.includes("n")) height = start.height - dy;
      width = Math.min(AI_CHAT_MAX.width, Math.max(AI_CHAT_MIN.width, width));
      height = Math.min(AI_CHAT_MAX.height, Math.max(AI_CHAT_MIN.height, height));
      // Anchor the opposite edge, then clamp to the SAME viewport gutters
      // clampAiChatPosition uses, so the ResizeObserver never re-clamps and
      // yanks the dock after a drag (review F5).
      const { side, top: topGutter, bottom: bottomGutter } = AI_DOCK_GUTTER;
      if (dir.includes("w")) {
        left = rightEdge - width;
        if (left < side) { left = side; width = rightEdge - side; }
      } else if (dir.includes("e") && left + width > innerW - side) {
        width = innerW - side - left;
      }
      if (dir.includes("n")) {
        top = bottomEdge - height;
        if (top < topGutter) { top = topGutter; height = bottomEdge - topGutter; }
      } else if (dir.includes("s") && top + height > innerH - bottomGutter) {
        height = innerH - bottomGutter - top;
      }
      width = Math.max(AI_CHAT_MIN.width, width);
      height = Math.max(AI_CHAT_MIN.height, height);
      setSize({ width: Math.round(width), height: Math.round(height) });
      setPosition((prev) => ({ ...prev, left: Math.round(left), top: Math.round(top) }));
      if (maximized) setMaximized(false);
    };
    const onPointerUp = () => {
      resizeRef.current = null;
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [maximized]);

  useEffect(() => {
    if (!open || typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const node = chatRef.current;
    if (!node) return undefined;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const box = node.getBoundingClientRect();
        setPosition((current) => clampAiChatPosition({ ...current, width: box.width, height: box.height }));
      });
    });
    observer.observe(node);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [open]);

  // Rendered box. Maximized pins to a near-fullscreen panel on the right;
  // otherwise the persisted size (or the responsive default) at the dragged
  // position. Explicit width/height make the persisted resize visible.
  const viewportW = typeof window !== "undefined" ? window.innerWidth : 1440;
  const viewportH = typeof window !== "undefined" ? window.innerHeight : 900;
  const defaultSize = viewportW >= 2200 ? AI_CHAT_WIDE_SIZE : AI_CHAT_SIZE;
  let dockBox;
  if (maximized) {
    const width = Math.min(AI_CHAT_MAX.width, viewportW - 24);
    const height = Math.min(AI_CHAT_MAX.height, viewportH - 100);
    dockBox = { left: Math.max(12, viewportW - width - 12), top: 82, width, height };
  } else {
    dockBox = {
      left: position.left,
      top: position.top,
      width: size.width || defaultSize.width,
      height: size.height || defaultSize.height,
    };
  }

  return (
    <>
      <button
        aria-label={
          open
            ? "Axiom AI is open"
            : available
              ? "Open Axiom AI"
              : `Open Axiom AI unavailable state: ${unavailableReason}`
        }
        aria-pressed={open}
        className="ax-ai-fab"
        onClick={openDock}
        title={available ? "Open Axiom AI" : unavailableReason}
        type="button"
      >
        <AxiomAiMark />
      </button>

      {open ? (
        <section
          aria-label="Axiom AI"
          aria-modal="false"
          className={`ax-ai-dock${maximized ? " is-maximized" : ""}`}
          data-ai-maximized={maximized ? "true" : "false"}
          ref={chatRef}
          role="dialog"
          style={{
            left: `${dockBox.left}px`,
            top: `${dockBox.top}px`,
            width: `${dockBox.width}px`,
            height: `${dockBox.height}px`,
          }}
        >
          <header
            className="ax-ai-dock-header"
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              if (event.target instanceof Element && event.target.closest("button")) return;
              const box = event.currentTarget.closest(".ax-ai-dock")?.getBoundingClientRect?.();
              dragRef.current = {
                x: event.clientX,
                y: event.clientY,
                left: position.left,
                top: position.top,
                width: box?.width,
                height: box?.height,
              };
              capturePointer(event);
            }}
          >
            <div>
              <AxiomAiMark />
              <span>
                <strong>Axiom AI</strong>
                <em>{groundingLine}</em>
              </span>
            </div>
            <div className="ax-ai-dock-header-actions">
              <button
                aria-label={maximized ? "Restore Axiom AI size" : "Maximize Axiom AI"}
                aria-pressed={maximized}
                className="ax-ai-dock-icon-btn"
                onClick={toggleMaximize}
                title={maximized ? "Restore" : "Maximize"}
                type="button"
              >
                {maximized ? (
                  <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3.5" y="5.5" width="7" height="7" rx="1" />
                    <path d="M6 5.5V4a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1.5" />
                  </svg>
                ) : (
                  <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="3" y="3" width="10" height="10" rx="1" />
                  </svg>
                )}
              </button>
              <button aria-label="Close Axiom AI" className="ax-ai-dock-icon-btn" onClick={close} type="button">
                <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  <path d="M4 4l8 8M12 4l-8 8" />
                </svg>
              </button>
            </div>
          </header>
          <div className="ax-ai-dock-body">
            <div aria-live="polite" className="ax-ai-dock-transcript">
              <AxiomAiMessageList
                emptyMessage={emptyMessage}
                messages={aiChat.messages}
                onOpenEvidence={openEvidence}
              />
              <AxiomAiEvidenceDetail evidence={evidenceDetail} onClose={() => setEvidenceDetail(null)} />
            </div>
            <div className="ax-ai-dock-prompt-group">
              <div className="ax-ai-dock-prompt-label">TRY ASKING</div>
              <div aria-label="Axiom AI suggested prompts" className="ax-ai-dock-prompts">
                {prompts.slice(0, aiChat.messages.length ? 1 : prompts.length).map((prompt) => (
                  <button
                    disabled={!available || aiChat.loading}
                    key={prompt}
                    onClick={() => {
                      if (!available) return;
                      askWithContext(prompt);
                    }}
                    title={
                      !available
                        ? unavailableReason
                        : aiChat.loading
                          ? "Axiom AI is answering the current question."
                          : undefined
                    }
                    type="button"
                  >
                    <span aria-hidden="true" className="ax-ai-dock-prompt-icon">?</span>
                    <span>{prompt}</span>
                    <span aria-hidden="true" className="ax-ai-dock-prompt-arrow">→</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
          <form
            aria-busy={aiChat.loading ? "true" : "false"}
            className="ax-ai-dock-input"
            onSubmit={(event) => {
              event.preventDefault();
              if (!available) return;
              askWithContext(aiChat.draft);
            }}
          >
            <input
              disabled={!available || aiChat.loading}
              onChange={(event) => aiChat.setDraft(event.target.value)}
              placeholder={available ? placeholder : unavailableReason}
              ref={inputRef}
              type="text"
              value={aiChat.draft}
            />
            <button
              aria-label={aiChat.loading ? "Axiom AI is responding" : "Ask Axiom AI"}
              disabled={!available || aiChat.loading || !aiChat.draft.trim()}
              title={
                !available
                  ? unavailableReason
                  : aiChat.loading
                    ? "Axiom AI is answering the current question."
                    : !aiChat.draft.trim()
                      ? "Enter a prompt to ask Axiom AI."
                      : undefined
              }
              type="submit"
            >
              {aiChat.loading ? (
                <span aria-hidden="true" className="ax-ai-dock-spinner" />
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12 19 5l-5 14-3-6-6-1Z" />
                </svg>
              )}
            </button>
          </form>
          <p className="ax-ai-dock-disclaimer">
            <span>Axiom AI uses AI. Review for accuracy.</span>
            <button
              aria-expanded={infoOpen}
              aria-label="Axiom AI accuracy notice"
              onClick={() => setInfoOpen((current) => !current)}
              title="Axiom AI answers are grounded in available governance metadata and should be reviewed for accuracy."
              type="button"
            >
              <svg aria-hidden="true" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="8" cy="8" r="6.25" />
                <path d="M8 7.25v4" />
                <path d="M8 5.1h.01" />
              </svg>
            </button>
          </p>
          {infoOpen ? (
            <p className="ax-ai-dock-info" role="status">
              Axiom AI answers are grounded in available governance metadata and should be reviewed before action.
            </p>
          ) : null}
          {maximized
            ? null
            : RESIZE_HANDLES.map((dir) => (
                <div
                  aria-hidden="true"
                  className={`ax-ai-dock-resize ax-ai-dock-resize-${dir}`}
                  key={dir}
                  onPointerDown={(event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    resizeRef.current = {
                      x: event.clientX,
                      y: event.clientY,
                      width: dockBox.width,
                      height: dockBox.height,
                      left: dockBox.left,
                      top: dockBox.top,
                      dir,
                    };
                    capturePointer(event);
                  }}
                  title="Drag to resize"
                >
                  {dir === "se" ? (
                    <svg viewBox="0 0 12 12" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                      <path d="M11 5 5 11M11 9l-2 2" />
                    </svg>
                  ) : null}
                </div>
              ))}
        </section>
      ) : null}
    </>
  );
}

export default AxiomAiDock;
