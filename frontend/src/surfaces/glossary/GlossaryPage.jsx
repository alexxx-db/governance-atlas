import "./glossary.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  EntityChip,
  FilterBar,
  LoadingState,
  PageShell,
  StatusBanner,
  SuggestInput,
  TabStrip,
  toast,
} from "../../components/system";
import { useCdeDashboard } from "../../hooks/useCdeDashboard";
import { useWorkspaceRoster } from "../../hooks/useWorkspaceRoster";
import { useAxiomMutation } from "../../hooks/useAxiomQuery";
import { useTaxonomyOverview } from "../../hooks/useTaxonomyOverview";
import { fetchAiAutofill, updateAssetMetadata, upsertGovernanceGlossaryTerm } from "../../lib/api";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import { useAxiomNavigate } from "../../nav/useAxiomNavigate";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { CdeRegistry } from "./CdeRegistry";
import {
  matchTermByIdOrName,
  cdeRowsFromPayloads,
  sortTermsForDisplay,
  statusLabelFor,
  statusToneFor,
  termAssociationSummary,
  termReviewSummary,
  termsFromOverviewPayload,
  text,
  titleFromValue,
} from "./glossaryPresentation";
import { TermDetail } from "./TermDetail";

/*
 * GlossaryPage — the Glossary & CDEs surface rebuilt on the system layers
 * (Wave C4, COHESION_BLUEPRINT surface map row "Glossary & CDEs").
 *
 * Contracts:
 *   - The URL is the state. Term detail is path-addressable /glossary/<termId>
 *     (read via useParams — back/forward and shared links restore it); the
 *     CDE registry is ?tab=cdes with ?cde=<id> selecting a row; search and
 *     status filters ride in ?q= / ?status=. The legacy sessionStorage +
 *     window-event term handoff (ax-pending-glossary-term /
 *     ax:select-glossary-term) and the raw history.replaceState bypasses are
 *     dead — nav/routes.js promotes legacy ?term= links to the durable path
 *     before this page mounts.
 *   - Data loads only through hooks on useAxiomQuery (bounded polls); writes
 *     go through useAxiomMutation against the existing governance APIs.
 *   - Every entity mention is an EntityChip anchor (cross-linking LAW).
 */

const GLOSSARY_PARAMS_SCHEMA = {
  tab: { type: "string" },
  cde: { type: "string" },
  q: { type: "string" },
  status: { type: "string" },
  domain: { type: "string" },
};

const STATUS_FILTER_OPTIONS = ["approved", "draft", "in_review", "proposed", "rejected", "deprecated"];

function safeDecode(value = "") {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

const EMPTY_TERM_DRAFT = { name: "", definition: "", domain: "", ownerEmail: "", status: "draft" };

export default function GlossaryPage({ shell = null }) {
  // G6: term Approve/Reject is a governance decision — steward/admin only.
  const canDecideReview = ["steward", "admin"].includes(
    String(shell?.role || shell?.actorRole || "").trim().toLowerCase(),
  );
  const routeParams = useParams();
  // Terminal greedy path param: /glossary/:termId mounts as a RR splat.
  const termId = safeDecode(String(routeParams["*"] || ""));
  const [params, setParams] = useSurfaceParams(GLOSSARY_PARAMS_SCHEMA);
  const navigate = useAxiomNavigate();

  const overviewQuery = useTaxonomyOverview();
  const cdeQuery = useCdeDashboard();

  // Non-authoritative payloads are rejected wholesale — fabricated glossary
  // evidence must never render as governed truth (CLAUDE.md).
  const overviewNonAuthoritative = isNonAuthoritativeMockEvidence(
    overviewQuery.data,
    overviewQuery.data?.meta,
    overviewQuery.data?.warnings,
  );
  const cdeNonAuthoritative = isNonAuthoritativeMockEvidence(
    cdeQuery.data,
    cdeQuery.data?.meta,
    cdeQuery.data?.warnings,
  );

  const terms = useMemo(
    () =>
      overviewNonAuthoritative
        ? []
        : sortTermsForDisplay(termsFromOverviewPayload(overviewQuery.data)),
    [overviewNonAuthoritative, overviewQuery.data],
  );
  const termLookup = useMemo(() => new Map(terms.map((term) => [term.termId, term])), [terms]);
  // Domains already in use across the glossary, so a new term reuses an
  // existing domain instead of a near-duplicate free-text spelling.
  const domainSuggestions = useMemo(() => {
    const set = new Set();
    for (const term of terms) {
      const domain = text(term.domain);
      if (domain && domain !== "Unassigned") set.add(domain);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [terms]);
  const cdeRows = useMemo(
    () =>
      cdeNonAuthoritative
        ? []
        : cdeRowsFromPayloads(cdeQuery.data, overviewNonAuthoritative ? null : overviewQuery.data),
    [cdeNonAuthoritative, cdeQuery.data, overviewNonAuthoritative, overviewQuery.data],
  );
  const cdeSummary = useMemo(() => {
    const payload = cdeQuery.data;
    const data = payload && typeof payload === "object" && "data" in payload ? payload.data : payload;
    return data?.summary && typeof data.summary === "object" ? data.summary : {};
  }, [cdeQuery.data]);

  const activeTab = termId ? "glossary" : params.tab === "cdes" ? "cdes" : "glossary";

  const glossaryLoading =
    (overviewQuery.status === "loading" || overviewQuery.status === "hydrating") && !terms.length;
  const cdeLoading =
    (cdeQuery.status === "loading" ||
      cdeQuery.status === "hydrating" ||
      overviewQuery.status === "loading" ||
      overviewQuery.status === "hydrating") &&
    !cdeRows.length;

  /* ---------------------------------------------------------------- */
  /* Term list filtering (?q= / ?status=)                              */
  /* ---------------------------------------------------------------- */

  const visibleTerms = useMemo(() => {
    const query = text(params.q).toLowerCase();
    const statusFilter = text(params.status).toLowerCase();
    return terms.filter((term) => {
      if (statusFilter && term.status !== statusFilter) return false;
      if (!query) return true;
      return [term.term, term.definition, term.domain, term.ownerEmail, term.stewardEmail]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [params.q, params.status, terms]);

  /* ---------------------------------------------------------------- */
  /* Term selection (path) + CDE selection (?cde=)                     */
  /* ---------------------------------------------------------------- */

  const selectedTerm = useMemo(
    () => (termId ? matchTermByIdOrName(terms, termId) : null),
    [termId, terms],
  );
  const termNotFound = Boolean(termId && terms.length && !selectedTerm && overviewQuery.status !== "loading");
  const childTerms = useMemo(
    () =>
      selectedTerm ? terms.filter((term) => term.parentTermId === selectedTerm.termId) : [],
    [selectedTerm, terms],
  );

  // Path-addressed selection scrolls the mini-hub into view (deep links land
  // above the fold; card clicks land where the detail actually renders).
  const termDetailRef = useRef(null);
  useEffect(() => {
    if (!selectedTerm || typeof window === "undefined") return;
    window.requestAnimationFrame(() => {
      const node = termDetailRef.current;
      if (!node || typeof node.scrollIntoView !== "function") return;
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
    });
  }, [selectedTerm]);

  const openTerm = (term) => {
    // Durable path address; filters ride along so Back and shared links keep
    // the working context.
    navigate(
      { kind: "term", id: term.termId },
      { params: { q: params.q || undefined, status: params.status || undefined } },
    );
  };
  const closeTermDetail = () => {
    navigate(
      { surface: "glossary" },
      { params: { q: params.q || undefined, status: params.status || undefined } },
    );
  };

  const handleTabChange = (key) => {
    if (key === activeTab) return;
    if (termId) {
      // Leaving the term path is a real navigation (push) — Back returns to
      // the term mini-hub.
      navigate({ surface: "glossary", params: key === "cdes" ? { tab: "cdes" } : {} });
      return;
    }
    // Tab flips on the bare route are sub-state: replace, don't grow history.
    setParams({ tab: key === "cdes" ? "cdes" : "", cde: "" });
  };

  /* ---------------------------------------------------------------- */
  /* Create / edit modals (Drawer: focus trap + Escape built in)       */
  /* ---------------------------------------------------------------- */

  const [termForm, setTermForm] = useState(null); // {mode:"create"|"edit", termId?, draft}
  const [termFormError, setTermFormError] = useState("");
  const [aiAutofilling, setAiAutofilling] = useState(false);

  // Agentic AI autofill: draft the definition (and suggest a domain) from the
  // term name via the foundation-model endpoint. It only FILLS EMPTY fields for
  // the steward to review/edit — it never overwrites text they already typed and
  // never saves. To re-draft, clear the field first.
  const handleAiAutofillTerm = async () => {
    const name = text(termForm?.draft?.name);
    if (!name) {
      setTermFormError("Enter a term name first — AI autofill drafts from it.");
      return;
    }
    setTermFormError("");
    setAiAutofilling(true);
    try {
      const { fields, warnings } = await fetchAiAutofill("glossaryTerm", {
        termName: name,
        domain: text(termForm?.draft?.domain),
      });
      if (!fields.definition && !fields.domain) {
        toast(warnings[0] || "AI autofill didn't return a draft. Try a more specific name.", { tone: "warning" });
        return;
      }
      // Decide from the CURRENT draft (not inside the async state updater) so
      // the toast reflects what actually filled. Only fill empty fields.
      const draftNow = termForm?.draft || {};
      const willFillDef = Boolean(fields.definition) && !text(draftNow.definition);
      const willFillDomain = Boolean(fields.domain) && !text(draftNow.domain);
      if (!willFillDef && !willFillDomain) {
        toast("Definition and domain are already filled; clear a field to re-draft it.", { tone: "info" });
        return;
      }
      setTermForm((current) => {
        if (!current) return current;
        const draft = { ...current.draft };
        if (willFillDef) draft.definition = fields.definition;
        if (willFillDomain) draft.domain = fields.domain;
        return { ...current, draft };
      });
      toast("AI drafted this term — review and edit before saving.", { tone: "success" });
    } catch (error) {
      toast(error?.message || "AI autofill is unavailable right now.", { tone: "warning" });
    } finally {
      setAiAutofilling(false);
    }
  };
  const [cdeForm, setCdeForm] = useState(null); // {assetFqn, rationale}
  // Real account principals for the owner autofill — fetched only while a term
  // form is open (the endpoint is steward-gated and rarely changes).
  const roster = useWorkspaceRoster({ enabled: Boolean(termForm) });
  const [cdeFormError, setCdeFormError] = useState("");

  const termUpsert = useAxiomMutation({
    mutate: (payload) => upsertGovernanceGlossaryTerm(payload),
    invalidates: [["axiom", "taxonomy-overview"], ["governance", "glossary"]],
  });
  const flagCde = useAxiomMutation({
    mutate: ({ assetFqn, rationale }) => updateAssetMetadata(assetFqn, { isCde: true, cdeRationale: rationale }),
    invalidates: [["axiom", "cde-dashboard"], ["axiom", "taxonomy-cde-dashboard"], ["axiom", "taxonomy-overview"]],
  });

  const handleSubmitTermForm = async (event) => {
    event.preventDefault();
    if (!termForm || termUpsert.submitting) return;
    const name = text(termForm.draft.name);
    if (!name) {
      setTermFormError("Term name is required.");
      return;
    }
    setTermFormError("");
    try {
      await termUpsert.mutate({
        termId: termForm.mode === "edit" ? termForm.termId : "",
        name,
        definition: text(termForm.draft.definition),
        domain: text(termForm.draft.domain),
        ownerEmail: text(termForm.draft.ownerEmail),
        status: termForm.mode === "edit" ? termForm.draft.status || "draft" : "draft",
        ...(termForm.mode === "edit"
          ? { changeNote: "Term updated from the glossary registry." }
          : {}),
      });
      toast(
        termForm.mode === "edit"
          ? `Glossary term “${name}” updated.`
          : `Glossary term “${name}” created with status Draft.`,
        { tone: "success" },
      );
      setTermForm(null);
    } catch (error) {
      setTermFormError(error?.message || "Failed to save the term — please try again.");
    }
  };

  const handleSubmitCdeForm = async (event) => {
    event.preventDefault();
    if (!cdeForm || flagCde.submitting) return;
    const assetFqn = text(cdeForm.assetFqn);
    // Minimal shape check: a Unity Catalog asset FQN is catalog.schema.table.
    if (assetFqn.split(".").filter(Boolean).length < 3) {
      setCdeFormError("Enter a full asset FQN (catalog.schema.table).");
      return;
    }
    setCdeFormError("");
    try {
      await flagCde.mutate({ assetFqn, rationale: text(cdeForm.rationale) });
      toast(`${assetFqn} flagged as a Critical Data Element.`, { tone: "success" });
      setCdeForm(null);
    } catch (error) {
      setCdeFormError(error?.message || "Failed to flag the asset as a CDE — please try again.");
    }
  };

  const openCreateAction = () => {
    if (activeTab === "cdes") {
      setCdeFormError("");
      setCdeForm({ assetFqn: "", rationale: "" });
      return;
    }
    setTermFormError("");
    setTermForm({ mode: "create", draft: { ...EMPTY_TERM_DRAFT } });
  };
  const openEditTerm = (term) => {
    setTermFormError("");
    setTermForm({
      mode: "edit",
      termId: term.termId,
      draft: {
        name: term.term,
        definition: term.definition || "",
        domain: term.domain === "Unassigned" ? "" : term.domain || "",
        ownerEmail: term.ownerEmail || "",
        status: term.status || "draft",
      },
    });
  };

  /* ---------------------------------------------------------------- */
  /* Page status (honest, from the active tab's query)                 */
  /* ---------------------------------------------------------------- */

  const activeQuery = activeTab === "cdes" ? cdeQuery : overviewQuery;
  const nonAuthoritativeActive = activeTab === "cdes" ? cdeNonAuthoritative : overviewNonAuthoritative;
  const pageStatus = nonAuthoritativeActive
    ? {
        status: "unavailable",
        reason:
          activeTab === "cdes"
            ? "Non-authoritative CDE dashboard payload rejected."
            : "Non-authoritative glossary and taxonomy payload rejected.",
        refresh: activeQuery.refresh,
      }
    : activeQuery;

  const glossaryCount = terms.length;
  const cdeCount = cdeRows.length;

  return (
    <PageShell
      className="ax-glos-page"
      eyebrow="Glossary & CDE Registry"
      title="Shared business meaning, anchored to data"
      subtitle="Glossary terms link to source-of-record assets. Critical Data Elements carry stricter ownership, certification, and lineage requirements."
      status={pageStatus}
      actions={
        <Button onClick={openCreateAction} variant="primary">
          {activeTab === "cdes" ? "+ New CDE" : "+ New term"}
        </Button>
      }
      tabs={
        <TabStrip
          ariaLabel="Glossary and CDE registry"
          onChange={handleTabChange}
          tabs={[
            {
              key: "glossary",
              label: "Glossary",
              badge: glossaryLoading && !glossaryCount ? "…" : glossaryCount,
            },
            {
              key: "cdes",
              label: "CDE Registry",
              badge: cdeLoading && !cdeCount ? "…" : cdeCount,
            },
          ]}
          value={activeTab}
        />
      }
    >
      {activeTab === "glossary" ? (
        <div className="ax-glos-section">
          {termNotFound ? (
            <StatusBanner
              action={
                <Button onClick={closeTermDetail} size="sm" variant="tertiary">
                  Back to glossary
                </Button>
              }
              message={`No glossary term matching “${termId}” was found.`}
              title="Term not found"
              tone="warning"
            />
          ) : null}
          <div className="ax-glos-toolbar">
            <FilterBar
              facets={[
                {
                  key: "q",
                  type: "search",
                  label: "Search glossary terms",
                  placeholder: "Search terms by name, definition, or domain…",
                },
                {
                  key: "status",
                  type: "select",
                  label: "Status",
                  options: STATUS_FILTER_OPTIONS.map((status) => ({
                    value: status,
                    label: titleFromValue(status),
                  })),
                },
              ]}
              label="Glossary filters"
              onChange={(next) => setParams({ q: next.q || "", status: next.status || "" })}
              value={{ q: params.q || "", status: params.status || "" }}
            />
          </div>
          <p
            aria-busy={glossaryLoading ? true : undefined}
            className="ax-glos-caption"
            role="status"
          >
            {/* "Showing … of …" only once data exists — a definitive "0 of 0"
                during hydration is the hydration-zero bug class. */}
            {glossaryLoading
              ? "Loading governed glossary terms…"
              : `Showing ${visibleTerms.length} of ${glossaryCount} governed glossary terms`}
          </p>
          {glossaryLoading ? (
            <LoadingState label="Loading glossary terms" variant="card" />
          ) : !visibleTerms.length ? (
            <EmptyState
              body={
                glossaryCount
                  ? "Adjust or clear the search and status filters to see all governed terms."
                  : "Create the first governed term with + New term."
              }
              title={glossaryCount ? "No terms match this view" : "No glossary terms yet"}
            />
          ) : (
            <div aria-label="Glossary cards" className="ax-glos-card-grid">
              {visibleTerms.map((term) => (
                <article
                  className={`ax-glos-card ${selectedTerm?.termId === term.termId ? "is-selected" : ""}`.trim()}
                  key={term.termId}
                  onClick={(event) => {
                    // Whole-card click is a convenience zone; the term chip
                    // below is the real anchor (middle-click/copy keep working).
                    if (/** @type {HTMLElement} */ (event.target).closest("a, button")) return;
                    openTerm(term);
                  }}
                >
                  <div className="ax-glos-card-head">
                    <div>
                      <h2>
                        <EntityChip
                          appearance="inline"
                          entity={{ kind: "term", id: term.termId, label: term.term }}
                        />
                      </h2>
                      <span className="ax-glos-card-sub">
                        {term.domain} · {term.stewardEmail || term.ownerEmail || "Unassigned steward"}
                      </span>
                    </div>
                    <Badge tone={statusToneFor(term.status)}>{statusLabelFor(term.status, "Draft")}</Badge>
                  </div>
                  <p className="ax-glos-card-definition">
                    {term.definition || "No definition recorded for this term."}
                  </p>
                  <dl aria-label={`${term.term} provenance`} className="ax-glos-card-proof">
                    <div>
                      <dt>Associations</dt>
                      <dd>{termAssociationSummary(term)}</dd>
                    </div>
                    <div>
                      <dt>Review</dt>
                      <dd>{termReviewSummary(term)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
          {selectedTerm ? (
            <div ref={termDetailRef} className="ax-glos-detail-anchor">
              <TermDetail
                canDecide={canDecideReview}
                childTerms={childTerms}
                onClose={closeTermDetail}
                onEdit={openEditTerm}
                term={selectedTerm}
                termLookup={termLookup}
                terms={terms}
              />
            </div>
          ) : null}
        </div>
      ) : (
        <div className="ax-glos-section">
          <CdeRegistry
            filters={{ q: params.q || "", domain: params.domain || "" }}
            loading={cdeLoading}
            onCloseDetail={() => setParams({ cde: "" })}
            onFiltersChange={(next) => setParams({ q: next.q || "", domain: next.domain || "" })}
            rows={cdeRows}
            selectedCdeId={params.cde || ""}
            summary={cdeSummary}
          />
        </div>
      )}

      {/* New/edit term modal — Drawer owns focus trap + Escape + scrim. */}
      <Drawer
        onClose={() => {
          if (!termUpsert.submitting) setTermForm(null);
        }}
        open={Boolean(termForm)}
        title={termForm?.mode === "edit" ? "Edit glossary term" : "New glossary term"}
      >
        {termForm ? (
          <form className="ax-glos-form" onSubmit={handleSubmitTermForm}>
            <p className="ax-glos-form-help">
              {termForm.mode === "edit"
                ? "Edits replay through the governed glossary upsert and are recorded in the term history."
                : "Drafts are saved with status Draft. Stewards can promote them to Proposed or Approved later."}
            </p>
            <label className="ax-glos-field">
              <span>Term name *</span>
              <input
                autoFocus
                disabled={termUpsert.submitting}
                onChange={(event) =>
                  setTermForm((current) => ({
                    ...current,
                    draft: { ...current.draft, name: event.target.value },
                  }))
                }
                placeholder="e.g. Net Revenue (USD)"
                required
                type="text"
                value={termForm.draft.name}
              />
            </label>
            <div className="ax-glos-field">
              <div className="ax-glos-field-label-row">
                <span>Definition</span>
                <Button
                  disabled={termUpsert.submitting}
                  loading={aiAutofilling}
                  onClick={(event) => {
                    event.preventDefault();
                    handleAiAutofillTerm();
                  }}
                  size="sm"
                  title="Draft the definition and domain from the term name using Axiom AI"
                  type="button"
                  variant="tertiary"
                >
                  ✨ AI draft
                </Button>
              </div>
              <textarea
                aria-label="Definition"
                disabled={termUpsert.submitting || aiAutofilling}
                onChange={(event) =>
                  setTermForm((current) => ({
                    ...current,
                    draft: { ...current.draft, definition: event.target.value },
                  }))
                }
                placeholder="Plain-language description used by analysts and stewards…"
                rows={4}
                value={termForm.draft.definition}
              />
            </div>
            <div className="ax-glos-field-row">
              <label className="ax-glos-field">
                <span>Domain</span>
                <SuggestInput
                  disabled={termUpsert.submitting}
                  onChange={(event) =>
                    setTermForm((current) => ({
                      ...current,
                      draft: { ...current.draft, domain: event.target.value },
                    }))
                  }
                  options={domainSuggestions}
                  placeholder="e.g. Finance"
                  type="text"
                  value={termForm.draft.domain}
                />
              </label>
              <label className="ax-glos-field">
                <span>Owner email</span>
                <SuggestInput
                  disabled={termUpsert.submitting}
                  onChange={(event) =>
                    setTermForm((current) => ({
                      ...current,
                      draft: { ...current.draft, ownerEmail: event.target.value },
                    }))
                  }
                  options={roster.emails}
                  placeholder="steward@your-company.ai"
                  type="email"
                  value={termForm.draft.ownerEmail}
                />
                {/* Honest hint: only real account principals validate on save;
                    say so when the roster is actually available. */}
                {roster.available ? (
                  <small className="ax-glos-field-hint">
                    Autofills from {roster.emails.length} account member
                    {roster.emails.length === 1 ? "" : "s"}
                  </small>
                ) : null}
              </label>
            </div>
            {termForm.mode === "edit" ? (
              <label className="ax-glos-field">
                <span>Status</span>
                <select
                  disabled={termUpsert.submitting}
                  onChange={(event) =>
                    setTermForm((current) => ({
                      ...current,
                      draft: { ...current.draft, status: event.target.value },
                    }))
                  }
                  value={termForm.draft.status}
                >
                  {STATUS_FILTER_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {titleFromValue(status)}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {termFormError ? (
              <p className="ax-glos-form-error" role="alert">
                {termFormError}
              </p>
            ) : null}
            <div className="ax-glos-form-actions">
              <Button
                disabled={termUpsert.submitting}
                onClick={() => setTermForm(null)}
                variant="tertiary"
              >
                Cancel
              </Button>
              <Button
                disabled={!text(termForm.draft.name)}
                loading={termUpsert.submitting}
                type="submit"
                variant="primary"
              >
                {termForm.mode === "edit" ? "Save term" : "Create term"}
              </Button>
            </div>
          </form>
        ) : null}
      </Drawer>

      {/* Flag-asset-as-CDE modal (backed asset-metadata PATCH path). */}
      <Drawer
        onClose={() => {
          if (!flagCde.submitting) setCdeForm(null);
        }}
        open={Boolean(cdeForm)}
        title="Flag asset as CDE"
      >
        {cdeForm ? (
          <form className="ax-glos-form" onSubmit={handleSubmitCdeForm}>
            <p className="ax-glos-form-help">
              Flags the asset as a Critical Data Element via the governed asset-metadata write path.
              The registry refreshes once the write lands.
            </p>
            <label className="ax-glos-field">
              <span>Asset FQN *</span>
              <input
                autoFocus
                disabled={flagCde.submitting}
                onChange={(event) =>
                  setCdeForm((current) => ({ ...current, assetFqn: event.target.value }))
                }
                placeholder="catalog.schema.table"
                required
                type="text"
                value={cdeForm.assetFqn}
              />
            </label>
            <label className="ax-glos-field">
              <span>Rationale</span>
              <textarea
                disabled={flagCde.submitting}
                onChange={(event) =>
                  setCdeForm((current) => ({ ...current, rationale: event.target.value }))
                }
                placeholder="Why this element is critical to the business…"
                rows={3}
                value={cdeForm.rationale}
              />
            </label>
            {cdeFormError ? (
              <p className="ax-glos-form-error" role="alert">
                {cdeFormError}
              </p>
            ) : null}
            <div className="ax-glos-form-actions">
              <Button disabled={flagCde.submitting} onClick={() => setCdeForm(null)} variant="tertiary">
                Cancel
              </Button>
              <Button
                disabled={!text(cdeForm.assetFqn)}
                loading={flagCde.submitting}
                type="submit"
                variant="primary"
              >
                Flag as CDE
              </Button>
            </div>
          </form>
        ) : null}
      </Drawer>
    </PageShell>
  );
}
