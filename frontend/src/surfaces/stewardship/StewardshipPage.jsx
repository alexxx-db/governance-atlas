import "./stewardship.css";
import { useEffect, useMemo, useState } from "react";
import {
  Button,
  FilterBar,
  PageShell,
  SectionCard,
  TabStrip,
  UnavailableState,
  toast,
} from "../../components/system";
import { GOVERNANCE_WORKBENCH_KEY } from "../../hooks/useGovernanceWorkbench";
import { useInboxWork } from "../../hooks/useInboxWork";
import { useAxiomQuery, useAxiomMutation } from "../../hooks/useAxiomQuery";
import {
  createGovernanceRequest,
  fetchGovernanceRequestDetail,
  updateGovernanceRequest,
} from "../../lib/api";
import { envelopeData } from "../../lib/envelope";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { useAxiomNavigate } from "../../nav/useAxiomNavigate";
import {
  canFileWorkItems,
  canMutateRequests,
  hasSlaEvidence,
  humanMutationError,
  isValidationWorkItem,
  lensCounts,
  matchesItemParam,
  matchesLens,
  mutationRole,
  normalizeCurrentUser,
  normalizeWorkItem,
  patchWorkbenchRequests,
  patchableStatus,
  scopeSummary,
  sortQueue,
  termReviewItem,
  textValue,
  workItemDisplayId,
} from "./format.js";
import { NewWorkItemDialog } from "./NewWorkItemDialog.jsx";
import { StewardshipQueue } from "./StewardshipQueue.jsx";
import { WorkItemPanel } from "./WorkItemPanel.jsx";

/*
 * surfaces/stewardship/StewardshipPage.jsx — Stewardship rebuilt on the
 * system layers (Wave C3, COHESION surface map J4).
 *
 * ONE queue, two lenses: the governance workbench queue plus glossary
 * term-reviews (the absorbed Inbox — /inbox now redirects here as
 * ?assignee=me) render as typed rows in the same table. "My work" is a
 * filter (?assignee=me), never a place. ?item=GOV-<hex8> addresses the
 * request mini-hub detail panel; ?asset= scopes the queue per asset; both
 * survive refresh/share — the URL is the state.
 *
 * Data: useInboxWork (workbench + glossary on the canonical cache keys —
 * the same entries feeding the rail badge and bell popover). Triage writes
 * go through useAxiomMutation with optimistic cache patches + rollback.
 */

// Mirrors nav/routes.js stewardship paramsSchema; module-level so
// useSurfaceParams normalizes it once.
const PARAMS_SCHEMA = {
  assignee: { type: "string" },
  item: { type: "string" },
  asset: { type: "string" },
  lens: { type: "string" },
};

const REQUEST_DETAIL_KEY = ["axiom", "governance-request"];

const LENS_KEYS = new Set(["all", "p1", "overdue", "mine"]);

export function StewardshipPage({ currentUser = null }) {
  /* ---------------------------------------------------------- URL state */
  const [params, setParams] = useSurfaceParams(PARAMS_SCHEMA);
  // "One queue, two lenses": ?assignee=me (the absorbed-inbox lens) wins;
  // otherwise ?lens= picks a severity slice.
  const lensKey = params.assignee === "me"
    ? "mine"
    : LENS_KEYS.has(params.lens)
      ? params.lens
      : "all";
  const assetFilter = textValue(params.asset);

  const setLens = (key) => {
    if (key === "mine") setParams({ assignee: "me", lens: "" });
    else setParams({ assignee: "", lens: key === "all" ? "" : key });
  };

  /* ---------------------------------------------------------- data */
  const inbox = useInboxWork();
  const workbench = inbox.workbench;
  const workbenchPayload = workbench.query.data ?? null;
  const workbenchLoading = workbench.status === "loading";
  const glossaryLoading = inbox.glossary.status === "loading";

  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const previous = document.title;
    document.title = "Stewardship - Axiom";
    return () => {
      document.title = previous;
    };
  }, []);

  // Sample/prototype payloads are rejected before any row renders — the
  // queue never presents unverified work items as product data.
  const prototypeEvidence = useMemo(() => {
    if (!workbenchPayload) return false;
    return isNonAuthoritativeMockEvidence({
      authoritative: workbenchPayload.authoritative,
      evidenceKind: workbenchPayload.evidenceKind,
      meta: workbenchPayload.meta,
      mockApi: workbenchPayload.mockApi,
      provenance: workbenchPayload.provenance,
      source: workbenchPayload.source,
      state: workbenchPayload.state,
      warnings: workbenchPayload.warnings,
    });
  }, [workbenchPayload]);

  const workbenchData = useMemo(() => envelopeData(workbenchPayload) || {}, [workbenchPayload]);

  // Full trustworthy queue BEFORE per-asset/lens filters: facet options and
  // scope captions need the unfiltered population.
  const requestRows = useMemo(() => {
    const raw = Array.isArray(workbenchData.requests) ? workbenchData.requests : [];
    if (prototypeEvidence) return [];
    return raw.map(normalizeWorkItem).filter((item) => !isValidationWorkItem(item));
  }, [prototypeEvidence, workbenchData.requests]);

  // The absorbed Inbox: glossary terms awaiting review are typed work items
  // in the SAME queue, badged "Term review", linking to their glossary page.
  const termRows = useMemo(
    () => (prototypeEvidence ? [] : inbox.reviewTerms.map(termReviewItem)),
    [inbox.reviewTerms, prototypeEvidence],
  );

  const universe = useMemo(() => {
    const scopedRequests = assetFilter
      ? requestRows.filter((item) => item.assetFqn === assetFilter)
      : requestRows;
    // Term reviews carry no target asset; an asset-scoped queue is honest
    // about only containing that asset's requests.
    const scopedTerms = assetFilter ? [] : termRows;
    return [...sortQueue(scopedRequests), ...scopedTerms];
  }, [assetFilter, requestRows, termRows]);

  const counts = useMemo(() => lensCounts(universe, currentUser || {}), [currentUser, universe]);
  const visibleItems = useMemo(
    () => universe.filter((item) => matchesLens(item, lensKey, currentUser || {})),
    [currentUser, lensKey, universe],
  );

  // Asset facet options: distinct target FQNs with open-item counts. The
  // active URL-driven asset (?asset=…) stays selectable even at zero items
  // so the filter state remains visible and clearable.
  const assetFacetOptions = useMemo(() => {
    const tally = new Map();
    requestRows.forEach((item) => {
      if (!item.assetFqn) return;
      tally.set(item.assetFqn, (tally.get(item.assetFqn) || 0) + 1);
    });
    if (assetFilter && !tally.has(assetFilter)) tally.set(assetFilter, 0);
    return [...tally.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([fqn, count]) => ({ value: fqn, label: fqn, count }));
  }, [assetFilter, requestRows]);

  /* ---------------------------------------------------------- selection */
  const visibleRequests = useMemo(
    () => visibleItems.filter((item) => item.itemKind === "request"),
    [visibleItems],
  );
  const itemParam = textValue(params.item);
  const navigate = useAxiomNavigate();
  // Term reviews live in the Glossary — their mini-hub IS the term page, so a
  // ?item= deep link to a term id forwards there instead of silently failing
  // to select anything (follow-up verifier claim-3: unreachable state).
  useEffect(() => {
    if (/^ax-taxonomy-term-/.test(itemParam)) {
      navigate({ kind: "term", id: itemParam }, { replace: true });
    }
  }, [itemParam, navigate]);
  const selectedRow = useMemo(() => {
    if (itemParam) {
      // Deep links resolve against the WHOLE queue, not just the active
      // lens — a shared GOV link must open its item regardless of filters.
      return (
        visibleRequests.find((item) => matchesItemParam(item, itemParam)) ||
        requestRows.find((item) => matchesItemParam(item, itemParam)) ||
        null
      );
    }
    return visibleRequests[0] || null;
  }, [itemParam, requestRows, visibleRequests]);
  const itemParamUnresolved = Boolean(itemParam) && !selectedRow;

  const selectedRequestId = textValue(selectedRow?.requestId);
  const detail = useAxiomQuery({
    key: [...REQUEST_DETAIL_KEY, selectedRequestId],
    enabled: Boolean(selectedRequestId),
    fetch: (signal) => fetchGovernanceRequestDetail(selectedRequestId, { signal }),
    staleTime: 30_000,
  });
  const detailPayload = envelopeData(detail.data);
  const selectedItem = selectedRow
    ? textValue(detailPayload?.requestId) === selectedRequestId
      ? normalizeWorkItem({ ...selectedRow, ...detailPayload })
      : selectedRow
    : null;

  /* ---------------------------------------------------------- mutations */
  const [triageFailure, setTriageFailure] = useState("");
  const triage = useAxiomMutation({
    mutate: ({ requestId, body }) => updateGovernanceRequest(requestId, body, { fast: true }),
    // Optimistic patch on the ONE workbench cache entry; useAxiomMutation
    // rolls it back automatically when the PATCH fails, and re-syncs from
    // the server either way.
    optimistic: {
      key: GOVERNANCE_WORKBENCH_KEY,
      update: (current, { requestId, patch }) =>
        patchWorkbenchRequests(current, requestId, patch || {}),
    },
    invalidates: [GOVERNANCE_WORKBENCH_KEY, REQUEST_DETAIL_KEY],
  });

  const runTriage = async ({ body, patch }, successMessage, failureFallback) => {
    if (!selectedRequestId || triage.submitting) return;
    setTriageFailure("");
    try {
      await triage.mutate({ requestId: selectedRequestId, body, patch });
      toast(successMessage, { tone: "success" });
    } catch (error) {
      // Human copy + request id — raw backend exception text ("TypeError:
      // DualWriteGovernanceStore…") must never reach the UI, and a failed
      // write must never masquerade as saved (persona-audit P0-adjacent).
      setTriageFailure(humanMutationError(error, failureFallback));
    }
  };

  const identity = normalizeCurrentUser(currentUser || {});
  const assignToMe = () => {
    if (!identity.email) {
      setTriageFailure("Assign to me is unavailable because no signed-in user email was resolved.");
      return;
    }
    runTriage(
      {
        body: {
          status: patchableStatus(selectedItem?.status),
          assignee: identity.email,
          priority: "",
        },
        patch: { assigned: identity.email, assignee: identity.email, assignedTo: identity.email },
      },
      `Assigned to you (${identity.email}).`,
      "Couldn't update the assignment — the server rejected the change.",
    );
  };

  // Assign to ANOTHER steward. Same backed triage PATCH as assignToMe, but the
  // assignee is a roster-validated email the steward picks. Returns a promise
  // resolving truthy on success so the inline picker knows to close itself; a
  // rejected write resolves falsy and surfaces the reason in the triage banner.
  const assignTo = async (rawEmail) => {
    const email = String(rawEmail || "").trim();
    if (!email || !selectedRequestId || triage.submitting) return false;
    setTriageFailure("");
    try {
      await triage.mutate({
        requestId: selectedRequestId,
        body: {
          status: patchableStatus(selectedItem?.status),
          assignee: email,
          priority: "",
        },
        patch: { assigned: email, assignee: email, assignedTo: email },
      });
      toast(`Assigned to ${email}.`, { tone: "success" });
      return true;
    } catch (error) {
      setTriageFailure(
        humanMutationError(error, "Couldn't reassign the work item — the server rejected the change."),
      );
      return false;
    }
  };

  const setPriority = (priority) => {
    if (!priority) return;
    runTriage(
      {
        body: { status: patchableStatus(selectedItem?.status), assignee: "", priority },
        patch: { priority: priority.toUpperCase() },
      },
      `Priority set to ${priority.toUpperCase()}.`,
      "Couldn't update the priority — the server rejected the change.",
    );
  };

  const commentOnItem = () => {
    const note = "Comment recorded from Stewardship.";
    runTriage(
      {
        body: { status: patchableStatus(selectedItem?.status), reviewNote: note },
        patch: { reviewNote: note },
      },
      "Comment recorded.",
      "Couldn't record the comment — the server rejected the change.",
    );
  };

  const resolveItem = () => {
    const note = "Resolved from Stewardship.";
    runTriage(
      {
        body: { status: "resolved", reviewNote: note },
        patch: { status: "Resolved", reviewNote: note },
      },
      "Work item resolved.",
      "Couldn't resolve the work item — the server rejected the change.",
    );
  };

  /* ---------------------------------------------------------- bulk */
  const [bulkSelection, setBulkSelection] = useState(() => new Set());
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false);
  const [bulkProgress, setBulkProgress] = useState(null);

  useEffect(() => {
    // A new filter scope invalidates row selection: never carry a bulk
    // selection into a row set the user can no longer see.
    setBulkSelection(new Set());
    setBulkConfirmOpen(false);
  }, [lensKey, assetFilter]);

  const toggleBulk = (id) => {
    setBulkSelection((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBulkResolve = async () => {
    // Loop the existing single-request PATCH: no bulk endpoint exists, so
    // each request keeps its own audit row exactly like a manual resolve.
    const targets = visibleRequests.filter((item) => bulkSelection.has(item.id) && item.requestId);
    setBulkConfirmOpen(false);
    if (!targets.length) return;
    setBulkProgress({ done: 0, total: targets.length, failed: 0 });
    let done = 0;
    let failed = 0;
    for (const item of targets) {
      try {
        await updateGovernanceRequest(
          item.requestId,
          { status: "resolved", reviewNote: "Bulk-resolved from Stewardship." },
          { fast: true },
        );
      } catch {
        failed += 1;
      }
      done += 1;
      setBulkProgress({ done, total: targets.length, failed });
    }
    setBulkProgress(null);
    setBulkSelection(new Set());
    if (failed) {
      // Partial failure is a failure notice, not a ✓ success toast; it
      // stays until dismissed so nothing hides that some writes were lost.
      toast(`Bulk resolve finished: ${targets.length - failed} resolved, ${failed} failed.`, {
        tone: "danger",
        duration: 0,
      });
    } else {
      toast(`${targets.length} work item${targets.length === 1 ? "" : "s"} resolved.`, {
        tone: "success",
      });
    }
    workbench.refresh();
  };

  /* ---------------------------------------------------------- create */
  const [newItemOpen, setNewItemOpen] = useState(false);
  const [createFailure, setCreateFailure] = useState("");
  const create = useAxiomMutation({
    mutate: (draft) => createGovernanceRequest(draft, { fast: true }),
    invalidates: [GOVERNANCE_WORKBENCH_KEY],
  });

  const submitNewItem = async (draft) => {
    setCreateFailure("");
    try {
      const response = await create.mutate(draft);
      setNewItemOpen(false);
      const createdId = textValue(response?.requestId);
      toast(
        createdId
          ? `Work item created (${workItemDisplayId({ requestId: createdId })}).`
          : "Work item created.",
        { tone: "success" },
      );
    } catch (error) {
      setCreateFailure(
        humanMutationError(error, "Couldn't create the work item — the server rejected the change."),
      );
    }
  };

  /* ---------------------------------------------------------- roles */
  const canMutate = canMutateRequests(currentUser || {}) && !prototypeEvidence;
  const canFile = canFileWorkItems(currentUser || {});
  const actorRole = mutationRole(currentUser || {}) || "Reader";
  const mutationUnavailableReason = prototypeEvidence
    ? "Work items are unavailable until live governance request evidence is loaded."
    : !canMutateRequests(currentUser || {})
      ? `Triage and resolve require Steward or Admin role. Current actor role: ${actorRole}.`
      : "";
  const fileDisabledReason = !canFile
    ? `Creating work items requires Writer, Steward, or Admin role. Current actor role: ${actorRole}.`
    : "";

  /* ---------------------------------------------------------- derived copy */
  // Hydration honesty: while the workbench is still loading, every count on
  // this surface shows a placeholder — never a definitive zero that flips
  // to the real number when the response lands (COHESION law #3).
  const hydrating = workbenchLoading || (glossaryLoading && !universe.length);
  const openCount = counts.all;
  const slaEvidenceAvailable = universe.some(
    (item) => item.itemKind === "request" && (hasSlaEvidence(item) || textValue(item.createdAt)),
  );
  const slaSummary = slaEvidenceAvailable
    ? `${counts.overdue.toLocaleString()} SLA breach${counts.overdue === 1 ? "" : "es"}`
    : "SLA evidence unavailable";
  const sortLabel = slaEvidenceAvailable ? "backed SLA risk" : "available work-item evidence";
  const scopeCaption = prototypeEvidence ? "" : scopeSummary(workbenchData.openRequestScope);

  const workbenchErrorNoData = workbench.status === "error";
  const pageStatus = workbenchErrorNoData
    ? {
        status: "error",
        reason: humanMutationError(workbench.error, "Unable to load the governance work queue right now."),
        refresh: workbench.refresh,
      }
    : {
        status: workbench.status,
        warnings: workbench.warnings,
        refresh: workbench.refresh,
      };

  const lensTabs = [
    { key: "all", label: "All", badge: hydrating ? "…" : counts.all },
    { key: "p1", label: "P1 critical", badge: workbenchLoading ? "…" : counts.p1 },
    { key: "overdue", label: "Overdue", badge: workbenchLoading ? "…" : counts.overdue },
    // The absorbed Inbox lens — same number the rail badge and bell use.
    { key: "mine", label: "My work", badge: hydrating ? "…" : counts.mine },
  ];

  const emptyState = (
    <div className="ax-stew-queue-empty">
      <strong>{assetFilter ? "No work items for this asset" : "No work items in this view"}</strong>
      <span>
        {assetFilter
          ? `No open work items target ${assetFilter}.`
          : "Nothing in the queue matches the selected filter."}
      </span>
    </div>
  );

  /* ---------------------------------------------------------- render */
  return (
    <PageShell
      className="ax-stew-page"
      eyebrow="Governance"
      title="Stewardship"
      subtitle={
        hydrating
          ? "Loading the governance work queue…"
          : `${openCount.toLocaleString()} open work item${openCount === 1 ? "" : "s"} · ${slaSummary}`
      }
      status={pageStatus}
      actions={
        <Button onClick={() => setNewItemOpen(true)} variant="primary">
          New work item
        </Button>
      }
      rail={
        prototypeEvidence || workbenchErrorNoData ? null : itemParamUnresolved && !workbenchLoading ? (
          <UnavailableState
            title="Work item not found"
            reason={`${itemParam} is not in the visible queue. It may be resolved or outside your visibility scope.`}
            onRetry={workbench.refresh}
          />
        ) : (
          <WorkItemPanel
            canMutate={canMutate}
            detailStatus={detail.status}
            item={selectedItem}
            mutationUnavailableReason={mutationUnavailableReason}
            onAssignToMe={assignToMe}
            onAssignTo={assignTo}
            onComment={commentOnItem}
            onResolve={resolveItem}
            onSetPriority={setPriority}
            triageBusy={triage.submitting}
            triageError={triageFailure}
          />
        )
      }
    >
      {prototypeEvidence ? (
        <UnavailableState
          title="Live work-item evidence unavailable"
          reason="The governance service returned sample data instead of live work items. The queue stays hidden until live evidence is returned."
          onRetry={workbench.refresh}
        />
      ) : workbenchErrorNoData ? null : (
        <>
          <div className="ax-stew-controls">
            <TabStrip
              ariaLabel="Queue lenses"
              param={{ value: lensKey, set: setLens }}
              tabs={lensTabs}
            />
            <FilterBar
              facets={[
                {
                  key: "asset",
                  label: "Asset",
                  type: "select",
                  options: assetFacetOptions,
                },
              ]}
              label="Queue filters"
              onChange={(next) => setParams({ asset: next.asset || "" })}
              value={assetFilter ? { asset: assetFilter } : {}}
            />
          </div>

          <SectionCard
            className="ax-stew-queue-card"
            title="Work queue"
            subtitle={
              hydrating
                ? "Loading work items…"
                : `${visibleItems.length} item${visibleItems.length === 1 ? "" : "s"} · sorted by ${sortLabel}`
            }
            status={hydrating ? "loading" : null}
          >
            {scopeCaption ? <p className="ax-stew-scope-caption">{scopeCaption}</p> : null}

            {bulkSelection.size ? (
              <div className="ax-stew-bulk-bar" role="status">
                <span>{bulkSelection.size} selected</span>
                {bulkProgress ? (
                  <span className="ax-stew-bulk-progress">
                    {`Resolving ${bulkProgress.done} of ${bulkProgress.total}…${bulkProgress.failed ? ` ${bulkProgress.failed} failed` : ""}`}
                  </span>
                ) : (
                  <>
                    <Button
                      disabled={!canMutate}
                      onClick={() => setBulkConfirmOpen(true)}
                      size="sm"
                      title={
                        canMutate
                          ? "Resolve every selected work item."
                          : mutationUnavailableReason
                      }
                      tone="success"
                      variant="secondary"
                    >
                      Resolve selected
                    </Button>
                    <Button onClick={() => setBulkSelection(new Set())} size="sm" variant="tertiary">
                      Clear selection
                    </Button>
                  </>
                )}
              </div>
            ) : null}

            {bulkConfirmOpen ? (
              <div aria-label="Confirm bulk resolve" className="ax-stew-bulk-confirm" role="alertdialog">
                <p>
                  {`Resolve ${bulkSelection.size} selected work item${bulkSelection.size === 1 ? "" : "s"}? Each resolve writes its own request state and audit evidence.`}
                </p>
                <div>
                  <Button onClick={runBulkResolve} size="sm" tone="success" variant="primary">
                    Confirm resolve
                  </Button>
                  <Button onClick={() => setBulkConfirmOpen(false)} size="sm" variant="tertiary">
                    Cancel
                  </Button>
                </div>
              </div>
            ) : null}

            <StewardshipQueue
              bulkDisabled={Boolean(bulkProgress)}
              bulkSelection={bulkSelection}
              emptyState={emptyState}
              items={visibleItems}
              loading={hydrating && !visibleItems.length}
              // Selecting a row repoints the ?item= rail while KEEPING the
              // current lens/asset filter — dropping the lens reset the tab out
              // from under the click and read as "nothing happened".
              onSelect={(item) =>
                setParams({
                  item: workItemDisplayId(item),
                  lens: params.lens || "",
                  assignee: params.assignee || "",
                  asset: params.asset || "",
                })
              }
              onToggleBulk={toggleBulk}
              selectedId={selectedRow?.id || ""}
            />
          </SectionCard>
        </>
      )}

      <NewWorkItemDialog
        // Remount per opening so the draft resets and seeds from the
        // current ?asset= scope.
        key={newItemOpen ? `open-${assetFilter}` : "closed"}
        canFile={canFile}
        error={createFailure}
        fileDisabledReason={fileDisabledReason}
        initialAssetFqn={assetFilter}
        onClose={() => {
          setNewItemOpen(false);
          setCreateFailure("");
        }}
        onSubmit={submitNewItem}
        open={newItemOpen}
        submitting={create.submitting}
      />
    </PageShell>
  );
}

export default StewardshipPage;
