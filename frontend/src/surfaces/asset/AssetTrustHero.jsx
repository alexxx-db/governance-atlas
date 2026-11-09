import "./asset.css";
import { useState } from "react";
import { Badge, Button, EntityChip, SuggestInput, toast } from "../../components/system";
import { useWorkspaceRoster } from "../../hooks/useWorkspaceRoster";
import { useAxiomMutation } from "../../hooks/useAxiomQuery";
import { upsertGovernanceOwner } from "../../lib/api";
import { formatUtcInstant, ownerRef } from "./format";

// Which governance roles can be assigned in-place, and their API ownerType.
// The Unity Catalog owner is the catalog-native owner (not writable here), so
// it stays read-only.
const ASSIGNABLE_OWNER_TYPES = { "Business owner": "business", Steward: "steward" };

function AssignOwnerControl({ assetFqn, ownerType, role, onAssigned }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const roster = useWorkspaceRoster({ enabled: open });
  const assign = useAxiomMutation({
    mutate: (ownerEmail) => upsertGovernanceOwner({ assetFqn, ownerEmail, ownerType }),
  });

  const submit = (event) => {
    event.preventDefault();
    const value = email.trim();
    if (!value || assign.submitting) return;
    assign
      .mutate(value)
      .then(() => {
        toast(`${role} assigned to ${value}.`, { tone: "success" });
        setOpen(false);
        setEmail("");
        if (typeof onAssigned === "function") onAssigned();
      })
      .catch((error) => {
        // Surface the roster-gate / validation message honestly.
        toast(error?.message || `Could not assign ${role.toLowerCase()}.`, { tone: "warning" });
      });
  };

  if (!open) {
    return (
      <button type="button" className="ax-asset-owner-assign-btn" onClick={() => setOpen(true)}>
        Unassigned · Assign
      </button>
    );
  }
  return (
    <form className="ax-asset-owner-assign-form" onSubmit={submit}>
      <SuggestInput
        aria-label={`${role} email`}
        className="ax-asset-owner-assign-input"
        disabled={assign.submitting}
        onChange={(event) => setEmail(event.target.value)}
        options={roster.emails}
        placeholder="name@company.com"
        type="email"
        value={email}
        autoFocus
      />
      <div className="ax-asset-owner-assign-actions">
        <Button size="sm" type="submit" variant="primary" loading={assign.submitting} disabled={!email.trim()}>
          Assign
        </Button>
        <Button size="sm" type="button" variant="tertiary" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/*
 * AssetTrustHero — the trust verdict block (PRODUCT_BLUEPRINT §3a, priority
 * item 1). Rendered by BOTH the hub page and the peek drawer so the two can
 * never tell different trust stories for the same asset (the WF1
 * three-owners contradiction becomes structurally impossible).
 *
 * Order is the law's priority order: certification (strict) → governance
 * score → CDE → sensitivity → the TWO labeled freshness values → ownership.
 */

/** Strict certification semantics: only the literal "Certified" is good. */
function certificationBadge(certification, hydrating) {
  const value = String(certification || "").trim();
  if (value === "Certified") return <Badge tone="good">Certified</Badge>;
  if (value) return <Badge tone="neutral">{value}</Badge>;
  if (hydrating) return null; // unknown yet — skeleton covers it
  return <Badge tone="muted">Not certified</Badge>;
}

function FreshnessValue({ label, value, hydrating, fallbackReason }) {
  const formatted = formatUtcInstant(value);
  return (
    <div className="ax-asset-fresh-item">
      <span className="ax-asset-fresh-label">{label}</span>
      {formatted ? (
        // Absolute UTC headline, ISO in the tooltip — never a raw ISO
        // headline, never a fake sparkline (teardown P0-4).
        <time className="ax-asset-fresh-value" dateTime={formatted.iso} title={formatted.iso}>
          {formatted.display}
        </time>
      ) : hydrating ? (
        <span className="ax-sys-skeleton ax-asset-fresh-skeleton" aria-hidden="true" />
      ) : (
        <span className="ax-asset-fresh-value is-empty" title={fallbackReason || undefined}>
          —
        </span>
      )}
    </div>
  );
}

/**
 * @param {{
 *   role: string,
 *   entry?: any,
 *   hydrating?: boolean,
 *   assetFqn?: string,
 *   canMutate?: boolean,
 *   onAssigned?: () => void,
 * }} props
 */
function OwnerRole({ role, entry, hydrating = false, assetFqn = "", canMutate = false, onAssigned }) {
  const ref = ownerRef(entry);
  const ownerType = ASSIGNABLE_OWNER_TYPES[role];
  // Offer an inline assign affordance when the role is unassigned AND writable —
  // instead of a dead "Unassigned" label the user can't act on.
  const canAssign = Boolean(canMutate && ownerType && assetFqn);
  return (
    <div className="ax-asset-owner-role">
      <span className="ax-asset-owner-role-label">{role}</span>
      {ref ? (
        <EntityChip entity={ref} appearance="inline" />
      ) : hydrating ? (
        // Unknown yet — "Unassigned" is a governance claim, not a loading
        // state (Wave-B verifier BLOCK).
        <span className="ax-asset-owner-unassigned" aria-busy="true">…</span>
      ) : canAssign ? (
        <AssignOwnerControl
          assetFqn={assetFqn}
          ownerType={ownerType}
          role={role}
          onAssigned={onAssigned}
        />
      ) : (
        <span className="ax-asset-owner-unassigned">Unassigned</span>
      )}
    </div>
  );
}

/**
 * @param {{
 *   asset: any,
 *   freshness: { state?: string, dataUpdatedAt?: string, lastAltered?: string,
 *                labels?: Record<string,string>, message?: string } | null,
 *   ownership: { ucOwner?: any, businessOwner?: any, steward?: any } | null,
 *   ownershipPending?: boolean,
 *   hydrating?: boolean,
 *   compact?: boolean,
 *   canMutate?: boolean,
 *   onAssigned?: () => void,
 * }} props
 */
export function AssetTrustHero({ asset, freshness, ownership, ownershipPending = false, hydrating = false, compact = false, canMutate = false, onAssigned }) {
  const assetFqn = String(asset?.fqn || asset?.assetFqn || "").trim();
  const coverage = Number(asset?.coverageScore);
  const hasCoverage = Number.isFinite(coverage) && asset?.coverageScore !== null && asset?.coverageScore !== "";
  const sensitivity = String(asset?.sensitivity || "").trim();
  const isCde = asset?.isCde === true;
  const freshnessBusy =
    hydrating || String(freshness?.state || "").toLowerCase() === "loading" || !freshness;
  // Payload-provided labels win so no surface can re-mislabel the semantics
  // (cohesion law 4); the literals below are the same two lawful words.
  const labels = freshness?.labels || {};

  return (
    <section
      className={`ax-asset-verdict ${compact ? "is-compact" : ""}`.trim()}
      aria-label="Trust verdict"
      aria-busy={hydrating || undefined}
    >
      <div className="ax-asset-verdict-chips">
        {certificationBadge(asset?.certification, hydrating)}
        <span className="ax-asset-score" title="Composite governance score from the live inventory.">
          <span className="ax-asset-score-label">Governance score</span>
          <strong className="ax-asset-score-value">
            {hasCoverage ? coverage : hydrating ? "…" : "—"}
          </strong>
        </span>
        {isCde ? (
          // Canonical CDE predicate is criticality-derived (semantics.py);
          // the subtitle must say so, never "tag-governed".
          <Badge tone="warn" className="ax-asset-cde-chip">
            CDE · Criticality-derived
          </Badge>
        ) : null}
        {sensitivity ? <Badge tone="info">{sensitivity}</Badge> : null}
      </div>

      <div className="ax-asset-fresh" aria-label="Freshness">
        <FreshnessValue
          label={labels.dataUpdatedAt || "Data updated"}
          value={freshness?.dataUpdatedAt}
          hydrating={freshnessBusy}
          fallbackReason={freshness?.message || "No data-write timestamp was reported."}
        />
        <FreshnessValue
          label={labels.lastAltered || "Metadata changed"}
          value={freshness?.lastAltered}
          hydrating={freshnessBusy}
          fallbackReason={freshness?.message || "No metadata-change timestamp was reported."}
        />
      </div>

      <div className="ax-asset-owners" aria-label="Ownership">
        <OwnerRole hydrating={hydrating || (ownershipPending && !ownership?.ucOwner)} role="Owner (Unity Catalog)" entry={ownership?.ucOwner} />
        <OwnerRole
          hydrating={hydrating || (ownershipPending && !ownership?.businessOwner)}
          role="Business owner"
          entry={ownership?.businessOwner}
          assetFqn={assetFqn}
          canMutate={canMutate}
          onAssigned={onAssigned}
        />
        <OwnerRole
          hydrating={hydrating || (ownershipPending && !ownership?.steward)}
          role="Steward"
          entry={ownership?.steward}
          assetFqn={assetFqn}
          canMutate={canMutate}
          onAssigned={onAssigned}
        />
      </div>
    </section>
  );
}

export default AssetTrustHero;
