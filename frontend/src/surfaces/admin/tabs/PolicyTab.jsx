import { Badge, EmptyState, EntityChip, LoadingState, SectionCard, UnavailableState } from "../../../components/system";
import { useControlDecisions } from "../../../hooks/useControlDecisions";
import { numberOrNull, numberValue, percentValue, stateText } from "../adminPresentation";

// Decision → Badge tone: approvals read good (green), rejections bad (red),
// everything else (updated / reassigned / etc.) stays neutral.
const DECISION_TONE = { approved: "good", rejected: "bad" };

function formatWhen(value) {
  const text = String(value || "").trim();
  if (!text) return "—";
  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? text : new Date(parsed).toLocaleDateString();
}

/*
 * Control Center · Policy tab (Wave C6). Renders the backed policy-exceptions
 * signal (an AVAILABLE zero when sources respond — consistent with the
 * Command Center, never "Unavailable") plus the API's honest-unavailable
 * policy library/enforcement cards with their own reason strings. Coverage
 * rows that carry METADATA coverage retitle the panel honestly instead of
 * implying policy-enforcement data exists.
 */

function PolicyRequirementCards({ cards, hydrating }) {
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle={
        cards.some((card) => card.state === "available")
          ? "Backed policy signals; unsupported checks stay marked unavailable"
          : "Policy diagnostics unavailable"
      }
      title="Policy"
    >
      {!cards.length && hydrating ? (
        <LoadingState label="Loading policy diagnostics" variant="tile" />
      ) : cards.length ? (
        <div aria-label="Policy requirement cards" className="ax-admin-policy-grid" role="group">
          {cards.map((card) => (
            <article
              className={`ax-admin-policy-card ${card.state === "available" ? "" : "is-unavailable"}`.trim()}
              key={card.id}
            >
              <small>{card.label}</small>
              <strong>{card.state === "available" ? numberValue(card.value) : "Unavailable"}</strong>
              {card.reason ? <span>{card.reason}</span> : null}
            </article>
          ))}
        </div>
      ) : (
        <UnavailableState
          reason="No policy diagnostics were reported by the control-center payload."
          title="Policy diagnostics unavailable"
        />
      )}
    </SectionCard>
  );
}

function CoveragePanel({ policies, hydrating }) {
  // When every row carries metadata coverage (no policy-enforcement source
  // exists), retitle the panel honestly instead of implying enforcement data.
  const metadataScoped = policies.length > 0 && policies.every((policy) => policy.coverageKind === "metadata");
  const panelTitle = metadataScoped ? "Metadata coverage by domain" : "Policy coverage";
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle={
        metadataScoped
          ? "Metadata completeness per domain — not policy-enforcement coverage"
          : policies.some((policy) => numberOrNull(policy.value) != null)
            ? "Coverage reported by diagnostics"
            : "Policy coverage unavailable"
      }
      title={panelTitle}
    >
      {metadataScoped ? (
        // Audit G4: make the enforcement gap explicit for auditors instead of
        // leaving it implied by the subtitle. There is no policy-enforcement
        // data source in the workspace, so we do NOT fabricate "control X was
        // enforced" evidence — we show metadata completeness and point to the
        // real, immutable control/audit evidence.
        <p className="ax-admin-coverage-note">
          Policy-enforcement evidence is not yet wired to a source, so this shows
          metadata completeness per domain — not proof a control was enforced.
          For enforced-control and grant evidence, see the Evidence surface.
        </p>
      ) : null}
      {!policies.length && hydrating ? (
        <LoadingState label="Loading coverage rows" variant="card" />
      ) : policies.length ? (
        <ul aria-label={`${panelTitle} rows`} className="ax-admin-coverage-list">
          {policies.map((policy) => {
            const numeric = numberOrNull(policy.value);
            const available = numeric != null;
            return (
              <li className={available ? "" : "is-unavailable"} key={policy.id}>
                <span className="ax-admin-coverage-label">
                  {/* Domain mentions are real anchors into Discover (LAW);
                      non-domain rule rows stay labeled text. */}
                  {policy.domain ? (
                    <EntityChip appearance="inline" entity={{ kind: "domain", name: policy.domain, label: policy.label }} />
                  ) : (
                    policy.label
                  )}
                </span>
                <strong>{available ? percentValue(numeric) : stateText(policy.status)}</strong>
                {policy.note ? <em className="ax-admin-coverage-note">{policy.note}</em> : null}
                <i aria-hidden="true" className="ax-admin-coverage-bar">
                  <b style={{ width: available ? `${Math.max(0, Math.min(100, numeric))}%` : "0%" }} />
                </i>
              </li>
            );
          })}
        </ul>
      ) : (
        <UnavailableState
          reason="No backed policy-coverage rows are available yet."
          title="Coverage rows unavailable"
        />
      )}
    </SectionCard>
  );
}

function ControlsInAction() {
  // Hooks first, no early return (React hook-order rule). The Admin surface is
  // admin-gated upstream, so no extra gating here.
  const { decisions, summary, enforcementNote, status } = useControlDecisions();

  const total = numberOrNull(summary.total) ?? decisions.length;
  // Honest, informative breakdown by the ACTUAL outcomes present (resolved,
  // approved, rejected, pending, …) rather than only approve/reject — which
  // read 0 when the log is mostly stewardship resolutions.
  const byOutcome = Array.isArray(summary.byOutcome) ? summary.byOutcome : [];
  const outcomeSummary = byOutcome.length
    ? byOutcome
        .filter((entry) => entry && entry.outcome)
        .map((entry) => `${entry.count} ${entry.outcome}`)
        .join(" · ")
    : `${numberOrNull(summary.approved) ?? 0} approved · ${numberOrNull(summary.rejected) ?? 0} rejected`;

  return (
    <SectionCard
      className="ax-admin-card"
      status={status === "loading" || status === "hydrating" ? "loading" : undefined}
      subtitle={`${total} decision${total === 1 ? "" : "s"} — ${outcomeSummary}`}
      title="Controls in action"
    >
      {decisions.length ? (
        <div className="ax-admin-decisions-scroll">
          <table className="ax-admin-decisions-table">
            <thead>
              <tr>
                <th>Decision</th>
                <th>Asset</th>
                <th>Actor</th>
                <th>Change</th>
                <th>Note</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((entry) => {
                const decision = String(entry.decision || "").trim();
                const asset = entry.entityFqn || entry.entityId || "—";
                const hasChange = entry.beforeStatus && entry.afterStatus;
                return (
                  <tr key={entry.auditId || `${asset}-${entry.at}`}>
                    <td>
                      <Badge tone={DECISION_TONE[decision.toLowerCase()] || "neutral"}>
                        {decision || "—"}
                      </Badge>
                    </td>
                    <td className="ax-admin-decisions-asset">{asset}</td>
                    <td>
                      <span className="ax-admin-decisions-actor">{entry.actor || "—"}</span>
                      {entry.actorRole ? (
                        <span className="ax-admin-decisions-role">{entry.actorRole}</span>
                      ) : null}
                    </td>
                    <td className="ax-admin-decisions-change">
                      {hasChange ? (
                        <>
                          {entry.beforeStatus}
                          <i aria-hidden="true"> → </i>
                          {entry.afterStatus}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="ax-admin-decisions-note">{entry.note || "—"}</td>
                    <td className="ax-admin-decisions-when">{formatWhen(entry.at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          body="Approvals and rejections appear here as stewards act on requests."
          title="No governance decisions recorded yet"
        />
      )}
      {enforcementNote ? (
        // Honesty gate: these are governance REVIEW decisions, not access
        // enforcement. Keep the payload's caveat prominent under the panel.
        <p className="ax-admin-decisions-caveat">{enforcementNote}</p>
      ) : null}
    </SectionCard>
  );
}

export function PolicyTab({ policyCards, policies, hydrating }) {
  return (
    <div className="ax-admin-tab-body" id="ax-admin-panel-policy" role="tabpanel">
      <PolicyRequirementCards cards={policyCards} hydrating={hydrating} />
      <ControlsInAction />
      <CoveragePanel hydrating={hydrating} policies={policies} />
    </div>
  );
}

export default PolicyTab;
