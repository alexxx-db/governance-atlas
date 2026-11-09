import { Link } from "react-router-dom";
import { LoadingState, SectionCard, UnavailableState, hrefForRef } from "../../../components/system";
import { numericValue } from "../format.js";

/*
 * InsightsBand (Wave C2) — the three widgets ABSORBED from the killed
 * Insights surface (COHESION surface map: "Absorbs Insights' three backed
 * widgets"): Risk Heatmap (with evidence date), Metadata-Coverage-by-Domain
 * matrix, and Certification-by-Tier. Everything else Insights rendered —
 * Policy Compliance Trend, Time-to-Resolution trend, Governance ROI tiles,
 * the duplicate KPI grid, empty AI recommendation slots — dies with the
 * surface (kill list §7.1).
 */

const RISK_COLUMNS = ["Very Low", "Low", "Medium", "High", "Very High"];
const RISK_ROWS = ["Very High", "High", "Medium", "Low", "Very Low"];

function evidenceStampLabel(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

function riskTone(row, column, value) {
  if (!value) return "empty";
  const score = RISK_ROWS.length - RISK_ROWS.indexOf(row) + RISK_COLUMNS.indexOf(column);
  if (score >= 8) return "critical";
  if (score >= 6) return "high";
  if (score >= 4) return "medium";
  return "low";
}

// Legend entries: the four occupied tones plus the empty cell, so the colour
// scale is never a mystery (the user had "no key" to read the map).
const RISK_LEGEND = [
  { tone: "empty", label: "None" },
  { tone: "low", label: "Lower" },
  { tone: "medium", label: "Moderate" },
  { tone: "high", label: "Elevated" },
  { tone: "critical", label: "Severe" },
];

export function RiskHeatmapCard({ cells, evidenceAt }) {
  const values = new Map();
  // impact bucket -> the exact Discovery criticality-facet values that
  // reproduce that row (backend-emitted; see _risk_heatmap). Lets a cell link
  // to the assets behind the count instead of being a dead number.
  const filtersByImpact = new Map();
  (Array.isArray(cells) ? cells : []).forEach((cell) => {
    const row = cell.row || cell.impact || "Medium";
    const column = cell.column || cell.likelihood || "Medium";
    values.set(`${row}::${column}`, numericValue(cell.value ?? cell.count) ?? 0);
    const filterValues = Array.isArray(cell.filterValues) ? cell.filterValues.filter(Boolean) : [];
    if (filterValues.length && !filtersByImpact.has(row)) filtersByImpact.set(row, filterValues);
  });
  const hasData = values.size > 0;
  const stamp = evidenceStampLabel(evidenceAt);
  return (
    <SectionCard
      className="ax-home-riskmap-card"
      title="Risk heatmap"
      subtitle="Impact (criticality) × likelihood (metadata gap) — cell = asset count"
      tooltip="Rows are business impact from criticality/tier; columns are likelihood from the metadata-completeness gap. Each cell counts assets; colour shows severity. Click a populated cell to open that impact level in Discovery."
    >
      {/* Date-stamp quality-derived evidence so stale runs never masquerade
          as today's signal. */}
      {stamp ? <p className="ax-home-evidence-stamp">{`Evidence from ${stamp} (UTC)`}</p> : null}
      {hasData ? (
        <>
          {/* Axis labels + colour key: the map read as an unlabelled grid
              before — "Impact" runs down the rows, "Likelihood" across the
              columns, and the legend decodes the colour ramp. */}
          <div className="ax-home-riskmap-frame">
            <span className="ax-home-riskmap-yaxis" aria-hidden="true">
              Impact
            </span>
            <div className="ax-home-riskmap" role="table" aria-label="Governance risk heatmap: impact by likelihood">
              {RISK_ROWS.map((row) => {
                const impactFilter = filtersByImpact.get(row);
                return (
                  <div className="ax-home-riskmap-row" role="row" key={row}>
                    <strong role="rowheader">{row}</strong>
                    {RISK_COLUMNS.map((column) => {
                      const value = values.get(`${row}::${column}`) || 0;
                      const tone = `tone-${riskTone(row, column, value)}`;
                      // Only a populated cell whose impact row carries real
                      // criticality facet values is clickable — the link opens
                      // that impact level (all likelihoods) in Discovery, which
                      // is the honest scope (likelihood has no facet).
                      if (value && impactFilter) {
                        const href = hrefForRef({ surface: "discovery", params: { criticality: impactFilter } });
                        const label = `Open ${row}-impact assets in Discovery (${column} likelihood cell: ${value})`;
                        return (
                          <Link
                            aria-label={label}
                            className={`${tone} is-link`}
                            key={column}
                            role="cell"
                            to={href}
                            title={label}
                          >
                            {value}
                          </Link>
                        );
                      }
                      return (
                        <span
                          className={tone}
                          key={column}
                          role="cell"
                          title={`${row} impact, ${column} likelihood: ${value}`}
                        >
                          {value || ""}
                        </span>
                      );
                    })}
                  </div>
                );
              })}
              <div className="ax-home-riskmap-axis" aria-hidden="true">
                {RISK_COLUMNS.map((column) => (
                  <span key={column}>{column}</span>
                ))}
              </div>
              <p className="ax-home-riskmap-xaxis" aria-hidden="true">
                Likelihood (metadata gap) →
              </p>
            </div>
          </div>
          <ul className="ax-home-riskmap-legend" aria-label="Severity colour key">
            {RISK_LEGEND.map((entry) => (
              <li key={entry.tone}>
                <i className={`tone-${entry.tone}`} aria-hidden="true" />
                <span>{entry.label}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <UnavailableState title="Risk evidence unavailable" reason="No recorded risk findings for the current scope." />
      )}
    </SectionCard>
  );
}

export function CoverageMatrixCard({ cells }) {
  const byRow = new Map();
  for (const cell of Array.isArray(cells) ? cells : []) {
    const rowName = cell.row || cell.domain || cell.label || "Unassigned";
    const column = cell.column || cell.metric || "Coverage";
    const current = byRow.get(rowName) || { domain: rowName, values: {} };
    current.values[column] = cell.value;
    byRow.set(rowName, current);
  }
  const rows = Array.from(byRow.values());
  const columns = Array.from(
    new Set((Array.isArray(cells) ? cells : []).map((cell) => cell.column || cell.metric || "Coverage")),
  );
  const tone = (value) => (value >= 85 ? "high" : value >= 65 ? "mid" : value > 0 ? "low" : "empty");
  return (
    <SectionCard
      className="ax-home-matrix-card"
      title="Metadata coverage by domain"
      subtitle="Coverage dimensions computed from visible asset metadata"
      tooltip="Each cell is the domain's completeness for one governance metadata dimension."
    >
      {rows.length && columns.length ? (
        <div
          className="ax-home-matrix"
          role="table"
          aria-label="Metadata coverage by domain"
          style={/** @type {import('react').CSSProperties} */ ({ "--ax-home-matrix-columns": columns.length })}
        >
          <div className="ax-home-matrix-row is-header" role="row">
            <span role="columnheader" />
            {columns.map((column) => (
              <span key={column} role="columnheader">
                {column}
              </span>
            ))}
          </div>
          {rows.map((row) => (
            <div className="ax-home-matrix-row" key={row.domain} role="row">
              {/* The domain row header links to Discovery filtered to that
                  domain — the one Risk & quality tile whose payload carries a
                  value that maps to a real filter. (Risk-heatmap cells and
                  cert tiers stay static: there's no impact×likelihood or tier
                  filter grammar, so a link would land on an empty page.) */}
              {hrefForRef({ kind: "domain", name: row.domain }) ? (
                <Link
                  role="rowheader"
                  className="ax-home-matrix-rowlink"
                  to={hrefForRef({ kind: "domain", name: row.domain })}
                  title={`Open ${row.domain} assets in Discovery`}
                >
                  {row.domain}
                </Link>
              ) : (
                <strong role="rowheader">{row.domain}</strong>
              )}
              {columns.map((column) => {
                const value = numericValue(row.values[column]) ?? 0;
                return (
                  <span
                    aria-label={`${row.domain} ${column} ${Math.round(value)} percent`}
                    className={`tone-${tone(value)}`}
                    key={column}
                    role="cell"
                    title={`${column}: ${Math.round(value)}%`}
                  />
                );
              })}
            </div>
          ))}
          <div className="ax-home-matrix-scale" aria-hidden="true">
            <span>Low</span>
            <i />
            <span>High</span>
          </div>
        </div>
      ) : (
        <UnavailableState
          title="Coverage matrix unavailable"
          reason="Domain coverage dimensions are unavailable for the current scope."
        />
      )}
    </SectionCard>
  );
}

export function CertificationTierCard({ rows }) {
  const items = (Array.isArray(rows) ? rows : []).map((item) => ({
    label: item.label || item.tier || "Unassigned tier",
    value: Math.max(0, Math.min(100, numericValue(item.value ?? item.coverage ?? item.percent) ?? 0)),
    certified: numericValue(item.certified),
    total: numericValue(item.total),
    // Exact criticality-facet values that reproduce this tier's assets
    // (backend-emitted) — makes the tier row a real drill instead of a label.
    filterValues: Array.isArray(item.filterValues) ? item.filterValues.filter(Boolean) : [],
  }));
  return (
    <SectionCard
      className="ax-home-tier-card"
      title="Certification coverage by tier"
      subtitle="Certified asset share by live tier metadata"
      tooltip='Share of each tier whose assets are strictly certified (certification == "Certified"). Click a tier to open its assets in Discovery.'
    >
      {items.length ? (
        <div className="ax-home-tier-rows">
          {items.map((item) => {
            const href = item.filterValues.length
              ? hrefForRef({ surface: "discovery", params: { criticality: item.filterValues } })
              : null;
            const countHint =
              Number.isFinite(item.certified) && Number.isFinite(item.total)
                ? ` — ${item.certified} of ${item.total} certified`
                : "";
            return (
              <div className="ax-home-tier-row" key={item.label}>
                {href ? (
                  <Link
                    aria-label={`Open ${item.label} assets in Discovery${countHint}`}
                    className="ax-home-tier-rowlink"
                    to={href}
                    title={`Open ${item.label} assets in Discovery${countHint}`}
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span title={countHint ? `${item.label}${countHint}` : undefined}>{item.label}</span>
                )}
                <i>
                  <b style={{ width: `${item.value}%` }} />
                </i>
                <strong>{Math.round(item.value)}%</strong>
              </div>
            );
          })}
        </div>
      ) : (
        <UnavailableState
          title="Tier certification unavailable"
          reason="Tier certification coverage is unavailable for the current live scope."
        />
      )}
    </SectionCard>
  );
}

/*
 * Axiom AI recommendations: ONLY evidence-backed rows render — one card per
 * recommendation, ZERO cards render nothing at all (kill list §7.1: the
 * "No additional evidence-backed recommendation" filler slots die).
 */
// Send each recommendation to where the recommended ACTION is actually
// performed, keyed on the evidence metric — not just the generic surface:
//   • assetsWithoutOwner  → Discovery scoped to that domain's OWNERLESS assets
//     (owner=__unassigned__), where each asset's inline Assign owner/steward
//     control does the write. "Assign stewardship for Finance" landing on the
//     bare Discovery list (or the work-item queue, which has no ownerless-asset
//     concept) was the dead end the user hit.
//   • criticalCertification → the asset page, where certification is set.
//   • metadataCoverage    → Discovery filtered to the domain to triage gaps.
//   • metadataChange      → the audit event in Evidence.
function recTarget(item) {
  const evidence = Array.isArray(item?.evidence) ? item.evidence[0] : null;
  const metric = String(evidence?.metric || "");
  const id = evidence?.id != null ? String(evidence.id) : "";
  if (evidence?.type === "asset" && id) return { kind: "asset", fqn: id };
  if (metric === "assetsWithoutOwner" && id)
    return { surface: "discovery", params: { domain: [id], owner: "__unassigned__" } };
  if (evidence?.type === "domain" && id) return { kind: "domain", name: id };
  if (evidence?.type === "audit" && id) return { kind: "event", id };
  return { surface: "stewardship" };
}

// A short verb for the card so the click target is legible before you follow
// it (the title alone didn't say the link now leads to an action surface).
function recActionLabel(item) {
  const metric = String(item?.evidence?.[0]?.metric || "");
  if (metric === "assetsWithoutOwner") return "Assign owners";
  if (metric === "criticalCertification") return "Review & certify";
  if (metric === "metadataCoverage") return "Improve coverage";
  if (metric === "metadataChange") return "View audit event";
  return "Open";
}

export function RecommendationsCard({ recommendations }) {
  const rows = (Array.isArray(recommendations) ? recommendations : []).filter(
    (item) => item && (item.title || item.detail),
  );
  if (!rows.length) return null;
  return (
    <SectionCard
      className="ax-home-recs-card"
      title="Axiom AI recommendations"
      subtitle="Evidence-backed recommendations only"
      tooltip="Each recommendation cites live governance evidence; slots without evidence render nothing."
    >
      <ul className="ax-home-rec-list">
        {rows.map((item) => (
          <li key={item.key || item.title}>
            <Link
              className="ax-home-rec"
              to={hrefForRef(recTarget(item)) || hrefForRef({ surface: "stewardship" })}
            >
              <strong>{item.title || "Evidence-backed recommendation"}</strong>
              <small>{item.detail || ""}</small>
              <span className="ax-home-rec-action">{recActionLabel(item)} →</span>
            </Link>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

/* The band wrapper: absorbed widgets render under one "Risk & quality"
 * heading; the Insights query has its own status handling so a slow insights
 * endpoint never blocks the command-center payload above it. */
export function InsightsBand({ insights }) {
  const data = insights.data || {};
  if (insights.loading) {
    return (
      <section className="ax-home-insights-band" aria-label="Risk and quality" aria-busy="true">
        <h2 className="ax-home-band-title">Risk &amp; quality</h2>
        <LoadingState variant="card" label="Loading risk and quality widgets" />
      </section>
    );
  }
  if (insights.error) {
    return (
      <section className="ax-home-insights-band" aria-label="Risk and quality">
        <h2 className="ax-home-band-title">Risk &amp; quality</h2>
        <UnavailableState
          title="Risk and quality widgets unavailable"
          reason={insights.error}
          onRetry={insights.refresh}
        />
      </section>
    );
  }
  return (
    <section className="ax-home-insights-band" aria-label="Risk and quality">
      <h2 className="ax-home-band-title">Risk &amp; quality</h2>
      <div className="ax-home-insights-grid">
        <RiskHeatmapCard
          cells={data.riskHeatmap}
          evidenceAt={data.riskEvidenceAt || data.qualityEvidenceAt}
        />
        <CoverageMatrixCard cells={data.metadataCoverageHeatmap} />
        <CertificationTierCard rows={data.certificationCoverageByTier} />
      </div>
      <RecommendationsCard recommendations={data.recommendations} />
    </section>
  );
}

export default InsightsBand;
