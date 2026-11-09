import { useMemo, useState } from "react";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  EntityChip,
  StatusBanner,
  TabStrip,
  UnavailableState,
  toast,
} from "../../components/system";
import { useAxiomMutation } from "../../hooks/useAxiomQuery";
import { useClassificationQueue } from "../../hooks/useClassificationQueue";
import { reviewClassificationRecommendation } from "../../lib/api";
import { compactDateTime, displayLabel, statusTone, text } from "./evidenceFormat.js";

/*
 * surfaces/evidence/ClassificationQueueTab.jsx — the classification / PII
 * review queue half of the unified Evidence surface (A9.4). This is where a
 * steward triages the sensitivity/tier/certification recommendations the
 * classifier proposed for columns across the estate:
 *   /evidence?tab=classification&cstatus=pending   (default triage view)
 *
 * Data: GET /api/classification-recommendations via useClassificationQueue —
 * visibility-scoped list, steward-gated review action. The decision buttons
 * only render when the host page passes canReview (steward/admin).
 */

// Status buckets the backend accepts, plus an "all" sentinel for the
// unfiltered view. "pending" is the default triage state.
const STATUS_TABS = [
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "deferred", label: "Deferred" },
  { key: "all", label: "All" },
];
const STATUS_KEYS = new Set(STATUS_TABS.map((tab) => tab.key));

// decision → toast phrasing + tone.
const DECISION_LABEL = {
  approved: { verb: "Approved", tone: "success" },
  rejected: { verb: "Rejected", tone: "warning" },
  deferred: { verb: "Deferred", tone: "neutral" },
};

export function ClassificationQueueTab({ params, setParams, canReview = false }) {
  /* ------------------------------------------------------------ URL state */
  const rawStatus = text(params.cstatus).toLowerCase();
  const status = STATUS_KEYS.has(rawStatus) ? rawStatus : "pending";

  /* ------------------------------------------------------------ in-flight */
  // Which recommendation is mid-decision — disables that row's buttons so a
  // steward can't double-submit while the write is in flight.
  const [decidingId, setDecidingId] = useState("");

  /* ------------------------------------------------------------ data */
  const queue = useClassificationQueue({ status });
  const rows = queue.recommendations;
  const loading = queue.loading;

  /* ------------------------------------------------------------ mutation */
  const review = useAxiomMutation({
    mutate: ({ recommendationId, decision }) =>
      reviewClassificationRecommendation(recommendationId, { decision, note: "" }),
    // Prefix invalidation re-syncs every status window from the server so the
    // approved row leaves the pending view and lands in its new bucket.
    invalidates: [["axiom", "classification-recommendations"]],
  });

  const decide = async (row, decision) => {
    if (!canReview || review.submitting) return;
    const recommendationId = text(row.recommendationId);
    if (!recommendationId) {
      toast("This recommendation has no id to review.", { tone: "warning" });
      return;
    }
    setDecidingId(recommendationId);
    try {
      await review.mutate({ recommendationId, decision });
      const phrasing = DECISION_LABEL[decision] || { verb: displayLabel(decision), tone: "neutral" };
      toast(
        `${phrasing.verb} classification for ${text(row.columnName) || recommendationId}.`,
        { tone: phrasing.tone },
      );
    } catch {
      toast(review.errorMessage || "The classification review could not be recorded.", {
        tone: "danger",
      });
    } finally {
      setDecidingId("");
    }
  };

  /* ------------------------------------------------------------ columns */
  const columns = useMemo(
    () => [
      {
        key: "asset",
        header: "Asset",
        render: (row) =>
          text(row.assetFqn) ? (
            <EntityChip appearance="inline" entity={{ kind: "asset", fqn: row.assetFqn }} />
          ) : (
            "—"
          ),
      },
      {
        key: "columnName",
        header: "Column",
        render: (row) => (
          <span className="ax-clsq-column">{text(row.columnName) || "—"}</span>
        ),
      },
      {
        key: "suggested",
        header: "Suggested",
        render: (row) => {
          const chips = [
            text(row.suggestedSensitivity),
            text(row.suggestedTier),
            text(row.suggestedCertification),
          ].filter(Boolean);
          if (!chips.length) return <span className="ax-clsq-muted">No suggestion recorded</span>;
          return (
            <span className="ax-clsq-suggested">
              {chips.map((chip, index) => (
                <Badge key={`${chip}-${index}`} size="sm" tone="info">
                  {displayLabel(chip)}
                </Badge>
              ))}
            </span>
          );
        },
      },
      {
        key: "evidence",
        header: "Evidence",
        render: (row) => {
          const evidence = Array.isArray(row.evidence) ? row.evidence.filter(Boolean) : [];
          if (!evidence.length) {
            return <span className="ax-clsq-muted">No evidence recorded</span>;
          }
          const [first, ...rest] = evidence;
          return (
            <span className="ax-clsq-evidence" title={evidence.join("\n")}>
              <span className="ax-clsq-evidence-first">{text(first)}</span>
              {rest.length ? (
                <small className="ax-clsq-evidence-more">{`+${rest.length} more`}</small>
              ) : null}
            </span>
          );
        },
      },
      {
        key: "status",
        header: "Status",
        render: (row) => (
          <Badge size="sm" tone={statusTone(row.status)}>
            {displayLabel(row.status, "Pending")}
          </Badge>
        ),
      },
      {
        key: "actions",
        header: "Decision",
        render: (row) => {
          const isPending = text(row.status) === "pending";
          if (!isPending) {
            // Already reviewed: show who/when instead of dead buttons.
            const reviewer = text(row.reviewedBy);
            const at = text(row.reviewedAt);
            return (
              <small className="ax-clsq-reviewed">
                {reviewer || at
                  ? `${reviewer || "Reviewed"}${at ? ` · ${compactDateTime(at)}` : ""}`
                  : "Reviewed"}
              </small>
            );
          }
          if (!canReview) {
            // Reader shell: the row is visible but the decision is steward-only.
            return <small className="ax-clsq-muted">Steward review required</small>;
          }
          const busy = review.submitting && decidingId === text(row.recommendationId);
          return (
            <span className="ax-clsq-actions">
              <Button
                size="sm"
                variant="primary"
                loading={busy}
                disabled={review.submitting}
                onClick={() => decide(row, "approved")}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={review.submitting}
                onClick={() => decide(row, "rejected")}
              >
                Reject
              </Button>
              <Button
                size="sm"
                variant="tertiary"
                disabled={review.submitting}
                onClick={() => decide(row, "deferred")}
              >
                Defer
              </Button>
            </span>
          );
        },
      },
    ],
    // decide/decidingId/review.submitting drive the per-row button state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canReview, decidingId, review.submitting],
  );

  /* ------------------------------------------------------------ captions */
  const captionParts = [
    rows.length
      ? `Showing ${rows.length} recommendation${rows.length === 1 ? "" : "s"}${
          status === "all" ? " across every status" : ` in the "${displayLabel(status)}" bucket`
        }`
      : "",
    queue.pendingCount
      ? `${queue.pendingCount} pending review${queue.pendingCount === 1 ? "" : "s"} in total`
      : "",
  ].filter(Boolean);

  /* ------------------------------------------------------------ error */
  if (queue.status === "error") {
    return (
      <UnavailableState
        className="ax-evid-gate"
        title="Classification recommendations unavailable"
        reason={queue.errorMessage || "The classification recommendation feed could not be loaded."}
        onRetry={queue.refresh}
      />
    );
  }

  /* ------------------------------------------------------------ render */
  return (
    <div className="ax-clsq">
      {queue.status === "degraded" ? (
        <StatusBanner
          tone="warning"
          title="Classification evidence availability is limited"
          warnings={queue.warnings}
          onRetry={queue.refresh}
        />
      ) : null}

      <div className="ax-clsq-toolbar">
        <TabStrip
          ariaLabel="Classification status"
          className="ax-clsq-status"
          param={{
            value: status,
            // Default "pending" keeps the URL clean; other buckets carry a
            // ?cstatus= param.
            set: (key) => setParams({ cstatus: key === "pending" ? "" : key }),
          }}
          tabs={STATUS_TABS}
        />
        <p className="ax-clsq-lede" role="status">
          {loading
            ? "Reading classification recommendations…"
            : "Column sensitivity, tier and certification the classifier proposed for steward review."}
        </p>
      </div>

      {!canReview ? (
        <p className="ax-clsq-gate-note" role="status">
          You can browse the classification queue. Approving, rejecting or deferring a recommendation
          requires a steward or admin role.
        </p>
      ) : null}

      {!loading && !rows.length ? (
        <EmptyState
          title={
            status === "pending"
              ? "No classification recommendations awaiting review"
              : `No ${displayLabel(status).toLowerCase()} recommendations`
          }
          body={
            status === "pending"
              ? "The classifier has no pending column recommendations in your visibility scope. New detections land here for triage."
              : `No classification recommendations are in the "${displayLabel(status)}" bucket for your visibility scope.`
          }
          action={
            status === "pending" ? null : (
              <Button variant="secondary" onClick={() => setParams({ cstatus: "" })}>
                Back to pending
              </Button>
            )
          }
        />
      ) : (
        <>
          <DataTable
            caption="Classification recommendations"
            columns={columns}
            density="compact"
            emptyMessage="No classification recommendations in this bucket."
            loading={loading}
            rowKey="recommendationId"
            rows={rows}
          />
          {captionParts.length ? (
            <div className="ax-evid-caption-row">
              <p className="ax-evid-caption">{captionParts.join(" · ")}</p>
            </div>
          ) : null}
        </>
      )}

      <p className="ax-evid-provenance">
        Classification recommendations are read from the classifier's detection ledger — visibility
        scoped to your estate. Decisions are steward-gated and recorded as governed audit evidence.
      </p>
    </div>
  );
}

export default ClassificationQueueTab;
