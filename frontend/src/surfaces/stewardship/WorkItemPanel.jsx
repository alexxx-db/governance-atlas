import { useEffect, useRef, useState } from "react";
import { Badge, Button, EmptyState, EntityChip, StatusBanner, SuggestInput, toast } from "../../components/system";
import { useWorkspaceRoster } from "../../hooks/useWorkspaceRoster";
import {
  auditChipId,
  formatShortDate,
  looksLikeEmail,
  openingEvidenceFacts,
  priorityBadgeTone,
  priorityPickerValue,
  priorityShortLabel,
  slaBadgeTone,
  slaLabel,
  slaPolicyNote,
  textValue,
  workItemAuditTrail,
  workItemComments,
  workItemDisplayId,
  workItemFullId,
  workItemKind,
  humanizeCommentText,
} from "./format.js";

/*
 * surfaces/stewardship/WorkItemPanel.jsx — the request mini-hub
 * (PRODUCT_BLUEPRINT §3c, addressable as /stewardship?item=GOV-<hex8>).
 * Answers, in order: what & why → target asset chip strip → triage
 * controls → evidence trail (diff, facts, comments with AUD EntityChips).
 */

function CopyIdButton({ item }) {
  const fullId = workItemFullId(item);
  if (!fullId || fullId === workItemDisplayId(item)) return null;
  const copy = () => {
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : null;
    if (clipboard?.writeText) {
      clipboard
        .writeText(fullId)
        .then(() => toast("Request ID copied.", { tone: "success" }))
        .catch(() => toast(`Request ID: ${fullId}`));
    } else {
      // No clipboard API (older embeds): still surface the id so the click
      // is never a dead control.
      toast(`Request ID: ${fullId}`);
    }
  };
  return (
    <Button onClick={copy} size="sm" title={`Copy full request id ${fullId}`} variant="tertiary">
      Copy ID
    </Button>
  );
}

function EvidenceComments({ comments, evidenceResolvable = true }) {
  if (!comments.length) {
    return (
      <p className="ax-stew-panel-muted">
        No comments recorded for this work item yet. The Comment button files a review note.
      </p>
    );
  }
  return (
    <div className="ax-stew-comments">
      {comments.map((comment, index) => {
        const commentId = textValue(comment.id);
        const author = textValue(comment.author, "Unknown actor");
        // Audit events this item generated join the Evidence ledger by
        // their stable AUD id — the id text is the anchor. The backend now
        // maps comments to `displayAuditId` where possible; AUD-shaped
        // comment ids remain the fallback for older payloads. auditChipId
        // format-checks both so a malformed id never links.
        const commentAuditId = auditChipId(comment.displayAuditId) || auditChipId(commentId);
        return (
          <div className="ax-stew-comment" key={commentId || `comment-${index}`}>
            <div className="ax-stew-comment-head">
              {looksLikeEmail(author) ? (
                <EntityChip appearance="inline" entity={{ kind: "owner", id: author }} />
              ) : (
                <span>{author}</span>
              )}
              {textValue(comment.at) ? <span>{formatShortDate(comment.at) || comment.at}</span> : null}
              {/* Same withheld gating as AuditTrail: out-of-scope assets'
                  evidence is unresolvable on the Evidence page (follow-up
                  re-verify BLOCK — comments still minted dead chips). */}
              {commentAuditId && evidenceResolvable ? (
                <EntityChip appearance="inline" entity={{ kind: "event", id: commentAuditId }} />
              ) : commentAuditId ? (
                <span
                  className="ax-stew-panel-muted"
                  title="Evidence for this asset is withheld outside your visible estate"
                >
                  {commentAuditId}
                </span>
              ) : null}
            </div>
            <p>{humanizeCommentText(comment.text)}</p>
          </div>
        );
      })}
    </div>
  );
}

/*
 * The item's audit events, each anchored to its Evidence ledger row by the
 * backend-joined AUD display id (cross-linking LAW). Rows the backend could
 * not map to the ledger render as text — never a dead link.
 */
function AuditTrail({ trail, evidenceResolvable = true }) {
  if (!trail.length) {
    // Honest empty state — an absent `auditTrail` field (older backend) and
    // a genuinely empty trail both mean "nothing to show", not zero-padding.
    return (
      <p className="ax-stew-panel-muted">No audit events recorded for this item yet.</p>
    );
  }
  return (
    <div aria-label="Audit events" className="ax-stew-comments">
      {trail.map((row) => (
        <div className="ax-stew-comment" key={row.key}>
          <div className="ax-stew-comment-head">
            <span>{row.action}</span>
            {row.at ? <span>{formatShortDate(row.at) || row.at}</span> : null}
            {/* Evidence visibility-scopes out events about assets outside
                the visible estate — a chip there is a guaranteed dead link
                (follow-up verifier). Show the id as text with the withheld
                reason instead. */}
            {row.displayAuditId && evidenceResolvable ? (
              <EntityChip appearance="inline" entity={{ kind: "event", id: row.displayAuditId }} />
            ) : row.displayAuditId ? (
              <span
                className="ax-stew-panel-muted"
                title="Evidence for this asset is withheld outside your visible estate"
              >
                {row.displayAuditId}
              </span>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

/*
 * Assign this work item to ANOTHER steward (not just "me"). The backend triage
 * PATCH accepts an `assignee` email validated against the workspace roster
 * (axiom/api/governance.py → identity_roster.validate_principal), so this is a
 * real, backed write — same roster + SuggestInput typeahead used for reviewer /
 * owner autofill elsewhere. `onAssignTo(email)` returns a promise that resolves
 * truthy on a successful write so the control closes; the roster only loads
 * once the picker is opened (enabled: open) to avoid a fetch on every render.
 */
function AssignToControl({ disabled = false, disabledReason = "", busy = false, onAssignTo }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const roster = useWorkspaceRoster({ enabled: open });

  if (!open) {
    return (
      <Button
        disabled={disabled}
        onClick={() => setOpen(true)}
        size="sm"
        title={disabledReason || "Assign this work item to another steward."}
        variant="secondary"
      >
        Assign to…
      </Button>
    );
  }

  const close = () => {
    setOpen(false);
    setEmail("");
  };
  const submit = (event) => {
    event.preventDefault();
    const value = email.trim();
    if (!value || busy) return;
    // The server does authoritative roster validation; on a rejected write the
    // parent keeps the picker open (resolves falsy) and surfaces the reason in
    // the triage error banner, so a failed reassignment never masquerades as saved.
    Promise.resolve(onAssignTo?.(value)).then((ok) => {
      if (ok) close();
    });
  };

  return (
    <form className="ax-stew-assign-form" onSubmit={submit}>
      <SuggestInput
        aria-label="Assignee email"
        className="ax-stew-assign-input"
        disabled={busy}
        onChange={(event) => setEmail(event.target.value)}
        options={roster.emails}
        placeholder="name@company.com"
        type="email"
        value={email}
        autoFocus
      />
      <Button size="sm" type="submit" variant="secondary" loading={busy} disabled={!email.trim()}>
        Assign
      </Button>
      <Button size="sm" type="button" variant="tertiary" onClick={close} disabled={busy}>
        Cancel
      </Button>
    </form>
  );
}

export function WorkItemPanel({
  item = null,
  detailStatus = "available",
  canMutate = false,
  mutationUnavailableReason = "",
  triageBusy = false,
  triageError = "",
  onAssignToMe,
  onAssignTo,
  onSetPriority,
  onComment,
  onResolve,
}) {
  // Hooks run unconditionally (before any early return) per CLAUDE.md.
  const panelRef = useRef(null);
  const prevIdRef = useRef("");
  const itemId = item ? workItemFullId(item) || workItemDisplayId(item) : "";
  useEffect(() => {
    const previous = prevIdRef.current;
    prevIdRef.current = itemId;
    // Bring the detail panel into view + focus it when the selection changes to
    // a NEW item — clicking a queue row (or a Command Center request link) that
    // repoints ?item= otherwise looked like "nothing happened" when the panel
    // sat below the queue on a narrow layout. Skip the first mount / deep-link
    // so we never yank the page on load; scrollIntoView({block:"nearest"}) is a
    // no-op when the panel is already visible.
    if (!itemId || itemId === previous || previous === "") return;
    const node = panelRef.current;
    if (!node || typeof node.scrollIntoView !== "function") return;
    const reduced =
      typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest", inline: "nearest" });
    if (typeof node.focus === "function") node.focus({ preventScroll: true });
  }, [itemId]);

  if (!item) {
    return (
      <EmptyState
        className="ax-stew-panel-empty"
        title="No work item selected"
        body="Select a work item to review its evidence, target asset, and triage controls."
      />
    );
  }

  const displayId = workItemDisplayId(item);
  const fullId = workItemFullId(item);
  const canTriage = Boolean(item.requestId) && canMutate && !triageBusy;
  const disabledReason = mutationUnavailableReason || "";
  const comments = workItemComments(item);
  const diffRows = Array.isArray(item?.diff?.rows)
    ? item.diff.rows.filter((row) => textValue(row?.after) || textValue(row?.before))
    : [];
  const suggestedActions = Array.isArray(item.suggestedActions) ? item.suggestedActions : [];
  const requester = textValue(item.requester);

  return (
    <section aria-label="Work item detail" className="ax-stew-panel" ref={panelRef} tabIndex={-1}>
      {/* What & why ---------------------------------------------------- */}
      <header className="ax-stew-panel-head">
        <div className="ax-sys-eyebrow">Work item</div>
        <h2 className="ax-stew-panel-id" title={fullId || undefined}>{displayId}</h2>
        <p className="ax-stew-panel-kind">{workItemKind(item)}</p>
        <div className="ax-stew-panel-chips">
          <Badge size="sm" status={textValue(item.status, "Unavailable")} />
          <Badge size="sm" tone={priorityBadgeTone(item.priority)}>
            {priorityShortLabel(item.priority)}
          </Badge>
          <span title={slaPolicyNote(item) || undefined}>
            <Badge size="sm" tone={slaBadgeTone(item)}>{slaLabel(item)}</Badge>
          </span>
          <CopyIdButton item={item} />
        </div>
        <dl className="ax-stew-panel-meta">
          <div>
            <dt>Requested by</dt>
            <dd>
              {requester && looksLikeEmail(requester) ? (
                <EntityChip appearance="inline" entity={{ kind: "owner", id: requester }} />
              ) : (
                requester || "Requester unavailable"
              )}
            </dd>
          </div>
          <div>
            <dt>Created</dt>
            <dd>{formatShortDate(item.createdAt) || "Unavailable"}</dd>
          </div>
          <div>
            <dt>Assigned</dt>
            <dd>
              {looksLikeEmail(item.assigned) ? (
                <EntityChip appearance="inline" entity={{ kind: "owner", id: item.assigned }} />
              ) : (
                textValue(item.assigned, "Unassigned")
              )}
            </dd>
          </div>
        </dl>
      </header>

      {/* Target asset chip strip -------------------------------------- */}
      <div className="ax-stew-panel-asset">
        <div className="ax-sys-eyebrow">Target asset</div>
        {item.assetFqn ? (
          <div className="ax-stew-panel-asset-chips">
            <EntityChip appearance="row" entity={{ kind: "asset", fqn: item.assetFqn }} />
            <EntityChip
              appearance="inline"
              entity={{ kind: "lineage", fqn: item.assetFqn, label: "Trace lineage" }}
            />
          </div>
        ) : (
          <p className="ax-stew-panel-muted">No target asset recorded for this work item.</p>
        )}
      </div>

      {/* Triage controls ----------------------------------------------- */}
      <div className="ax-stew-panel-triage" aria-label="Triage controls">
        {disabledReason ? <p className="ax-stew-panel-muted">{disabledReason}</p> : null}
        <div className="ax-stew-panel-triage-row">
          <Button
            disabled={!canTriage || Boolean(disabledReason)}
            loading={triageBusy}
            onClick={onAssignToMe}
            size="sm"
            title={disabledReason || "Assign this work item to yourself."}
            variant="secondary"
          >
            Assign to me
          </Button>
          <AssignToControl
            busy={triageBusy}
            disabled={!canTriage || Boolean(disabledReason)}
            disabledReason={disabledReason}
            onAssignTo={onAssignTo}
          />
          <label className="ax-stew-priority-picker">
            <span>Priority</span>
            <select
              aria-label="Set work item priority"
              disabled={!canTriage || Boolean(disabledReason)}
              onChange={(event) => onSetPriority?.(event.target.value)}
              title={disabledReason || "Set the triage priority for this work item."}
              value={priorityPickerValue(item.priority)}
            >
              <option disabled value="">Unassigned</option>
              <option value="p0">P0</option>
              <option value="p1">P1</option>
              <option value="p2">P2</option>
              <option value="p3">P3</option>
            </select>
          </label>
          <Button
            disabled={!canTriage || Boolean(disabledReason)}
            onClick={onComment}
            size="sm"
            title={disabledReason || "Comment on this governance request."}
            variant="secondary"
          >
            Comment
          </Button>
          <Button
            disabled={!canTriage || Boolean(disabledReason)}
            onClick={onResolve}
            size="sm"
            title={disabledReason || "Resolve this governance request."}
            tone="success"
            variant="primary"
          >
            Resolve
          </Button>
        </div>
        {triageError ? (
          <StatusBanner message={triageError} title="Work item update failed" tone="danger" />
        ) : null}
      </div>

      {/* Evidence trail ------------------------------------------------- */}
      <div className="ax-stew-panel-evidence" aria-label="Evidence trail">
        <h3>Why this is open</h3>
        <p>
          {textValue(
            item.evidence || item.businessContext || item.detail,
            diffRows.length
              ? "This request proposes the metadata changes listed below."
              : "No opening evidence was recorded for this work item.",
          )}
        </p>
        {diffRows.length ? (
          // The request's own field diff IS the opening evidence for
          // steward-filed metadata changes. `before` renders only when the
          // backend recorded it — after-only rows stay honest.
          <dl aria-label="Requested metadata changes" className="ax-stew-evidence-grid">
            {diffRows.map((row) => (
              <div key={row.field || row.label}>
                <dt>{textValue(row.label || row.field, "Field")}</dt>
                <dd>
                  {textValue(row.before)
                    ? `${textValue(row.before)} → ${textValue(row.after, "—")}`
                    : textValue(row.after, "—")}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        <dl aria-label="Opening evidence facts" className="ax-stew-evidence-grid">
          {openingEvidenceFacts(item).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                {label === "Affected asset" && item.assetFqn ? (
                  <EntityChip appearance="inline" entity={{ kind: "asset", fqn: item.assetFqn }} />
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
        </dl>

        {suggestedActions.length ? (
          <>
            <h3>Suggested actions</h3>
            {/* These are recommendations derived from the request evidence, NOT
                wired write actions — there is no "apply suggestion" endpoint in
                the backend. They were previously primary-looking <Button>s whose
                only effect was a toast, which reads as an executable control that
                changes nothing (CLAUDE.md "never wire a no-op button"). Render
                them as de-emphasized, non-actionable planned-change items so a
                click can never imply a metadata write happened. Stewards act via
                the triage controls (Assign / Priority / Comment / Resolve) or by
                filing a metadata change on the asset page. */}
            <ul className="ax-stew-suggestions" aria-label="Planned changes — not yet applied">
              {suggestedActions.map((action, index) => (
                <li
                  className="ax-stew-suggestion"
                  key={`${action.label || "action"}-${index}`}
                  title={textValue(action.detail) || undefined}
                >
                  <span className="ax-stew-suggestion-tag">Planned</span>
                  <span className="ax-stew-suggestion-label">
                    {textValue(action.label, "Suggested action")}
                  </span>
                  {textValue(action.detail) ? (
                    <span className="ax-stew-suggestion-detail">{textValue(action.detail)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
            <p className="ax-stew-panel-muted">
              Recommendations from the request evidence — not yet applied. Act on this item with the
              triage controls above.
            </p>
          </>
        ) : null}

        <h3>Evidence trail</h3>
        {detailStatus === "loading" ? (
          // Hydration honesty: the trail rides the workbench detail query —
          // never show a definitive "no audit events" while it is in flight.
          <p className="ax-stew-panel-muted">Loading the audit trail…</p>
        ) : (
          <AuditTrail evidenceResolvable={item?.assetInVisibleScope !== false} trail={workItemAuditTrail(item)} />
        )}

        <h3>Comments</h3>
        {detailStatus === "loading" ? (
          <p className="ax-stew-panel-muted">Loading the comment timeline…</p>
        ) : (
          <EvidenceComments evidenceResolvable={item?.assetInVisibleScope !== false} comments={comments} />
        )}
      </div>
    </section>
  );
}

export default WorkItemPanel;
