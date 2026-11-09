import "../asset.css";
import { useState } from "react";
import { createGovernanceRequest } from "../../../lib/api";
import { Badge, Button, LoadingState, SectionCard, UnavailableState, toast } from "../../../components/system";
import { useAxiomMutation } from "../../../hooks/useAxiomQuery";

/*
 * Access tab = access content ONLY (teardown P1-8 killed the "Composite
 * state / Loaded sections" developer-telemetry panel). Everything here comes
 * from the /360 access block, which shares its core with /access-explain so
 * the two can never disagree: auth mode, visibility scope, honest grants
 * unavailability WITH the reason, remediation steps, and real deep links.
 *
 * The "Request access" card files a real governance change request (the same
 * create-request API the header's Request-change flow uses) so an operator who
 * hits a grants wall can act in-app instead of chasing a steward out-of-band.
 */

export function AccessTab({ access, fqn }) {
  // Hooks run on EVERY render — declared before any early return (repo rule:
  // never a useState/useMutation after a conditional `return`).
  const [formOpen, setFormOpen] = useState(false);
  const [note, setNote] = useState("");
  // Single mutation contract; createGovernanceRequest is the same api-lib call
  // the header Request-change / Certify-stage flows use.
  const requestAccess = useAxiomMutation({
    mutate: (payload) => createGovernanceRequest(payload, { fast: true }),
  });

  const assetFqn = String(fqn || access?.fqn || "").trim();

  const handleSubmit = async (event) => {
    event.preventDefault();
    const trimmedNote = note.trim();
    if (!trimmedNote || !assetFqn || requestAccess.submitting) return;
    try {
      await requestAccess.mutate({
        assetFqn,
        title: "Access request",
        note: trimmedNote,
      });
      toast("Access request submitted", { tone: "success" });
      setNote("");
      setFormOpen(false);
    } catch {
      // Failure surfaces inline via requestAccess.errorMessage below — the
      // mutateAsync rejection is intentionally swallowed here.
    }
  };

  // The Request-access CTA is defined once and rendered in EVERY loaded state
  // (available OR unavailable) — a user most wants to request access precisely
  // when the access context is unavailable, and keeping it mounted stops the
  // button/form from flickering as the access payload settles.
  const requestAccessCard = (
    <SectionCard
      title="Request access"
      subtitle="File a governance request for a steward to widen your access to this asset."
    >
      {formOpen ? (
        <form className="ax-asset-dialog-form" onSubmit={handleSubmit}>
          <label className="ax-asset-field">
            <span>Why do you need access?</span>
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Describe the work that needs this asset — context helps the steward triage."
              rows={4}
              autoFocus
            />
          </label>
          {requestAccess.errorMessage ? (
            <p className="ax-asset-form-error" role="alert">
              {requestAccess.errorMessage}
            </p>
          ) : null}
          <div className="ax-asset-dialog-footer">
            <Button
              variant="tertiary"
              type="button"
              onClick={() => {
                setFormOpen(false);
                setNote("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              tone="accent"
              type="submit"
              loading={requestAccess.submitting}
              disabled={!note.trim() || !assetFqn}
            >
              Submit request
            </Button>
          </div>
        </form>
      ) : (
        <Button
          variant="secondary"
          disabled={!assetFqn}
          title={assetFqn ? undefined : "Asset identity unavailable — cannot file a request."}
          onClick={() => setFormOpen(true)}
        >
          Request access
        </Button>
      )}
    </SectionCard>
  );

  const state = String(access?.state || "").toLowerCase();
  if (!access || state === "loading") {
    return (
      <SectionCard title="Access">
        <LoadingState variant="card" lines={3} />
      </SectionCard>
    );
  }
  if (state !== "available") {
    return (
      <div className="ax-asset-tab-grid">
        <SectionCard title="Access">
          <UnavailableState
            title="Access context unavailable"
            reason={access?.message || "No access context was returned for this asset."}
          />
        </SectionCard>
        {requestAccessCard}
      </div>
    );
  }

  const remediation = Array.isArray(access.remediation) ? access.remediation : [];
  const deepLinks = access.deepLinks || {};
  const grants = access.grants || {};

  return (
    <div className="ax-asset-tab-grid">
      <SectionCard title="Authorization">
        <dl className="ax-asset-facts">
          <div className="ax-asset-fact">
            <dt>Auth mode</dt>
            <dd>
              <Badge tone={access.authMode === "obo" ? "good" : "info"}>{access.authMode || "unknown"}</Badge>
            </dd>
          </div>
          <div className="ax-asset-fact">
            <dt>Visibility scope</dt>
            <dd>{access.visibilityScope || "—"}</dd>
          </div>
          <div className="ax-asset-fact">
            <dt>Acting identity</dt>
            <dd>{access.actorEmail || "—"}</dd>
          </div>
        </dl>
      </SectionCard>

      <SectionCard title="Grants">
        {String(grants.state || "").toLowerCase() === "available" ? (
          // No grants source exists today; this branch is future-proofing for
          // a real grants payload — never an empty fabricated table.
          <p className="ax-asset-description">{grants.summary || ""}</p>
        ) : (
          <UnavailableState
            title="Grants not collected"
            reason={
              grants.reason ||
              "Per-principal Unity Catalog grants are not collected by the app; grant truth lives in Catalog Explorer."
            }
          />
        )}
        {deepLinks.catalogExplorer ? (
          <p className="ax-asset-deeplink-row">
            <a
              className="ax-asset-deeplink"
              href={deepLinks.catalogExplorer}
              target="_blank"
              rel="noreferrer"
            >
              Open in Catalog Explorer
            </a>
          </p>
        ) : null}
      </SectionCard>

      {remediation.length ? (
        <SectionCard title="Remediation" subtitle="Steps to widen the current access scope.">
          <ul className="ax-asset-remediation-list">
            {remediation.map((item, index) => (
              <li key={item.label || index}>
                <strong>{item.label}</strong>
                {item.detail ? <p>{item.detail}</p> : null}
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}

      {requestAccessCard}
    </div>
  );
}

export default AccessTab;
