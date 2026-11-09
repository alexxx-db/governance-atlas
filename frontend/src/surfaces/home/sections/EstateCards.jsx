import { Link } from "react-router-dom";
import { EntityChip, SectionCard, hrefForRef } from "../../../components/system";
import { evidenceDateLabel, formatCount, percentLabel } from "../format.js";

/*
 * EstateCards (Wave C2) — posture by domain (worst-first, complete),
 * catalog health (worst-first, complete), and the quality risk breakdown.
 * Every domain/catalog mention is an EntityChip anchor into filtered
 * Discovery (cross-linking LAW); risk severities drill to the Evidence
 * quality tab (/evidence?tab=quality — the C5 route contract), never to
 * another dashboard tile.
 */

function domainTone(score) {
  if (score === null) return "empty";
  if (score >= 90) return "high";
  if (score >= 84) return "good";
  if (score >= 78) return "mid";
  return "warn";
}

export function DomainPostureCard({ domains, postureAvailable }) {
  const title = postureAvailable ? "Posture by domain" : "Coverage by domain";
  return (
    <SectionCard
      className="ax-home-domain-card"
      title={title}
      subtitle="Complete list, worst first"
      tooltip={
        postureAvailable
          ? "Domain posture scores use backed command-center domain signals; the list is never truncated."
          : "Domain coverage scores use backed metadata coverage signals; the list is never truncated."
      }
    >
      <div className="ax-home-domain-bars">
        {domains.map((domain) => (
          <div className={`ax-home-domain-row tone-${domainTone(domain.score)}`} key={domain.label}>
            <EntityChip
              appearance="inline"
              entity={{ kind: "domain", name: domain.label, label: domain.label }}
            />
            <i aria-hidden="true">
              <b style={{ width: `${domain.score ?? 0}%` }} />
            </i>
            <strong>{domain.score === null ? "—" : `${Math.round(domain.score)}%`}</strong>
            <em>{domain.count === null ? "Count unavailable" : `${formatCount(domain.count)} assets`}</em>
          </div>
        ))}
        {!domains.length ? (
          <p className="ax-home-inline-unavailable">Domain signals are unavailable for the current scope.</p>
        ) : null}
      </div>
    </SectionCard>
  );
}

export function CatalogHealthCard({ catalogs }) {
  // Visual cap only on very large estates, explicitly captioned — hiding
  // catalogs silently is how the worst-covered catalog vanished before.
  const CAP = 12;
  const visible = catalogs.slice(0, CAP);
  const capCaption = catalogs.length > CAP ? `Showing worst ${CAP} of ${catalogs.length} catalogs` : "";
  return (
    <SectionCard
      className="ax-home-catalog-card"
      title="Catalog health · worst coverage first"
      subtitle="Visible catalog inventory joined with backed metadata coverage"
      tooltip="Catalog rows come from visible asset inventory and backed coverage fields; nothing is inferred."
    >
      <div
        className="ax-home-catalog-table"
        role="table"
        aria-label="Catalog health snapshot, worst coverage first"
      >
        <div role="row" className="ax-home-catalog-head">
          <span role="columnheader">Catalog</span>
          <span role="columnheader">Tables</span>
          <span role="columnheader">Coverage</span>
          <span role="columnheader">Classification</span>
          <span role="columnheader">Risk</span>
        </div>
        {visible.map((catalog) => (
          <div role="row" className="ax-home-catalog-row" key={catalog.name}>
            <span role="cell">
              <EntityChip
                appearance="inline"
                entity={{ kind: "catalog", name: catalog.name, label: catalog.name }}
              />
            </span>
            <span role="cell">{formatCount(catalog.tables)}</span>
            <span role="cell" className="ax-home-catalog-coverage">
              <b>{percentLabel(catalog.coverage)}</b>
              <i aria-hidden="true">
                <em style={{ width: `${catalog.coverage ?? 0}%` }} />
              </i>
            </span>
            <span role="cell" className="ax-home-catalog-chip">{catalog.classification}</span>
            <span role="cell" className="ax-home-catalog-chip">{catalog.risk}</span>
          </div>
        ))}
        {!catalogs.length ? (
          <p className="ax-home-inline-unavailable">
            Catalog health rows are unavailable until visible asset inventory is returned.
          </p>
        ) : null}
      </div>
      {capCaption ? (
        <p className="ax-home-cap-caption" role="note">
          {capCaption}
        </p>
      ) : null}
    </SectionCard>
  );
}

const SEVERITIES = [
  { key: "high", label: "High severity", tone: "bad" },
  { key: "medium", label: "Medium severity", tone: "warn" },
  { key: "informational", label: "Informational", tone: "info" },
];

export function RiskFindingsCard({ risk, policyKpi }) {
  const riskStamp = evidenceDateLabel(risk.evidenceAt);
  if (!risk.available) {
    return (
      <SectionCard
        className="ax-home-risk-card"
        title="Policy exception signals"
        subtitle="Policy exception signal availability"
        tooltip="Policy exception signals render without inferring an unavailable severity split."
      >
        <div className="ax-home-risk-empty">
          {policyKpi && policyKpi.value !== null && policyKpi.value !== undefined ? (
            <>
              <strong>{formatCount(policyKpi.value)}</strong>
              <span>Open policy exceptions</span>
              <p>
                Backed by governance workflow evidence. A severity split appears once quality checks record
                findings.
              </p>
              <Link className="ax-home-link" to={hrefForRef({ surface: "stewardship" })}>
                Open the stewardship queue
              </Link>
            </>
          ) : (
            <>
              <strong aria-hidden="true">—</strong>
              <span>No severity data yet</span>
              <p>A severity split appears once quality checks record findings.</p>
            </>
          )}
        </div>
      </SectionCard>
    );
  }
  return (
    <SectionCard
      className="ax-home-risk-card"
      // Panel title comes from the payload label so the panel names its
      // actual source ("Quality risk findings"), never a generic "Risk".
      title={risk.label}
      subtitle={`Quality-run findings by severity${riskStamp ? ` · ${riskStamp}` : ""}`}
      tooltip="Findings come from recorded quality-run results split by severity; nothing is inferred."
    >
      <ul className="ax-home-risk-list">
        {SEVERITIES.map((severity) => {
          const count = risk[severity.key];
          return (
            <li key={severity.key}>
              <Link
                className={`ax-home-risk-row tone-${severity.tone}`}
                to={hrefForRef({
                  // The severity counts are lifetime failed/errored totals, so
                  // the drill must land on the all-time window filtered to the
                  // failing population — a 30-day, all-outcome default showed 0
                  // (or an over-count) under a non-zero risk count.
                  surface: "evidence",
                  params: {
                    tab: "quality",
                    severity: severity.key,
                    outcome: "failing",
                    range: "all",
                  },
                })}
                title={`Open quality findings filtered to ${severity.label.toLowerCase()}`}
              >
                <b aria-hidden="true" />
                <span>{severity.label}</span>
                <strong>{count === null ? "—" : formatCount(count)}</strong>
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="ax-home-risk-foot">
        Findings drill into the Evidence quality ledger for run-level proof.
      </p>
    </SectionCard>
  );
}
