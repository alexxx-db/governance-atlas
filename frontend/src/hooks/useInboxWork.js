// Wave B/C surface hook (unused until InboxPage dies into Stewardship and
// the Rail badge adopts it): aggregates the actionable governance work
// InboxPage currently assembles from two inline useQuery calls — open
// stewardship requests (governance workbench) + glossary terms awaiting
// review. Per COHESION_BLUEPRINT, `/inbox` becomes
// `/stewardship?assignee=me` and the rail's my-work badge is fed by THIS
// hook instead of App.jsx's lifted inbox-badge computation.
import { useMemo } from "react";
import { fetchGovernanceGlossary } from "../lib/api";
import { envelopeData } from "../lib/envelope";
import { useAxiomQuery } from "./useAxiomQuery";
import { useGovernanceWorkbench } from "./useGovernanceWorkbench";

function textValue(value) {
  return String(value ?? "").trim();
}

// Status vocabularies mirror InboxPage.jsx — "actionable" means a human
// still has to do something.
const OPEN_REQUEST_STATUSES = new Set(["", "pending", "open", "in_review", "new"]);
const REVIEW_TERM_STATUSES = new Set(["proposed", "draft", "in_review", "review", "pending"]);

export function openRequestsFromWorkbench(payload) {
  const data = envelopeData(payload) || {};
  const requests = Array.isArray(data.requests) ? data.requests : [];
  return requests.filter((request) =>
    OPEN_REQUEST_STATUSES.has(textValue(request?.status).toLowerCase()),
  );
}

export function reviewTermsFromGlossary(payload) {
  const terms = Array.isArray(payload?.glossary) ? payload.glossary : [];
  return terms.filter((term) =>
    REVIEW_TERM_STATUSES.has(textValue(term?.reviewState || term?.status).toLowerCase()),
  );
}

/**
 * @param {{ enabled?: boolean }} [options]
 * @returns {{
 *   openRequests: any[],
 *   reviewTerms: any[],
 *   badgeCount: number,
 *   loading: boolean,
 *   workbench: ReturnType<typeof useAxiomQuery>,
 *   glossary: ReturnType<typeof useAxiomQuery>,
 * }}
 */
export function useInboxWork(options = {}) {
  const enabled = options.enabled !== false;
  const workbench = useGovernanceWorkbench({ enabled });
  const glossary = useAxiomQuery({
    key: ["axiom", "governance-glossary"],
    enabled,
    fetch: () => fetchGovernanceGlossary(),
    staleTime: 60_000,
  });

  const openRequests = useMemo(
    () => openRequestsFromWorkbench(workbench.query.data),
    [workbench.query.data],
  );
  const reviewTerms = useMemo(
    () => reviewTermsFromGlossary(glossary.query.data),
    [glossary.query.data],
  );

  return {
    openRequests,
    reviewTerms,
    // The rail badge: total items a steward can act on right now. Never
    // renders a definitive 0 while sources are still loading — consumers
    // must check `loading` first (Inbox "definitive zeros" rule).
    badgeCount: openRequests.length + reviewTerms.length,
    loading:
      enabled && (workbench.status === "loading" || glossary.status === "loading"),
    workbench,
    glossary,
  };
}

export default useInboxWork;
