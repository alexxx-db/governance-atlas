import { StatTile } from "../../../components/system";
import { evidenceDateLabel, formatCount, formatKpiValue, kpiState, numericValue, percentLabel } from "../format.js";

/*
 * KpiRow (Wave C2) — THE one KPI row for the estate. Every tile is a real
 * anchor into its evidence surface (StatTile target=), labelled from the
 * payload, with the payload formula string as its info tip. This replaces
 * both the legacy Command Center KPI row AND the Insights KPI grid — one
 * number per concept (COHESION law #2), so the duplicate implementations
 * (Insights "Metadata Coverage"/"Certified Assets" tiles, plus the
 * never-backed Policy Compliance and Time-to-Resolution tiles) die here.
 */

export function KpiRow({ kpis }) {
  const coverage = kpis.metadataCoverage;
  const certified = kpis.certifiedCriticalAssets;
  const stewardship = kpis.openStewardship;
  const policy = kpis.policyExceptions;
  const risk = kpis.risk;
  const riskStamp = evidenceDateLabel(risk.evidenceAt);

  const tiles = [
    {
      key: "coverage",
      label: "Metadata coverage",
      value: percentLabel(coverage?.value),
      delta: coverage?.deltaText || coverage?.reason || "",
      deltaTone: kpiState(coverage) === "unavailable" ? "neutral" : "good",
      trend: Array.isArray(coverage?.sparkline) ? coverage.sparkline : [],
      progress: numericValue(coverage?.value) ?? undefined,
      hint:
        coverage?.formula ||
        "Weighted coverage of required governance metadata fields across visible assets.",
      // Evidence: Discover sorted by governance score so the weakest-scored
      // assets are inspectable from the coverage number.
      target: { surface: "discovery", params: { sort: "Governance score" } },
    },
    {
      key: "certified",
      label: "Certified critical assets",
      value: formatKpiValue(certified),
      delta: certified?.deltaText || certified?.reason || "",
      deltaTone: kpiState(certified) === "unavailable" ? "neutral" : "good",
      trend: Array.isArray(certified?.sparkline) ? certified.sparkline : [],
      hint:
        certified?.formula ||
        'Assets that are both critical and strictly certified (certification == "Certified"), counted when both source signals are available.',
      target: { surface: "discovery", params: { views: ["Certified"] } },
    },
    {
      key: "stewardship",
      // Audit B1/B5: this counts open change requests ESTATE-WIDE (not just the
      // visible estate, and NOT the full Stewardship work queue, which also
      // includes glossary term reviews). Named distinctly so it no longer
      // collides with the "N work items" queue count / nav badge.
      label: "Open change requests",
      value: formatKpiValue(stewardship),
      delta: stewardship?.deltaText || stewardship?.reason || "",
      deltaTone: kpiState(stewardship) === "unavailable" ? "neutral" : "warn",
      trend: Array.isArray(stewardship?.sparkline) ? stewardship.sparkline : [],
      hint:
        stewardship?.formula ||
        "All open governance change requests across the estate. The Stewardship queue also folds in glossary term reviews and shows the visible-estate split.",
      target: { surface: "stewardship" },
    },
    risk.available
      ? {
          // The count is failed quality-run findings — a different source
          // than policy exceptions, so it never shares that tile's name.
          key: "risk",
          label: "High-risk quality findings",
          value: formatCount(risk.high),
          delta: riskStamp || "Quality-run findings by severity",
          deltaTone: numericValue(risk.high) > 0 ? "bad" : "good",
          trend: [],
          hint: `High-severity findings from the most recent quality runs (${risk.source || "quality run results"}).`,
          // Risk drills land on Evidence's quality tab (the C5 route contract),
          // never on another dashboard tile. range=all because the severity
          // count is a lifetime total (a 30-day default window landed the drill
          // on an empty page under a non-zero "high" count); outcome=failing so
          // the tab's total counts the same failed/errored rows as this tile.
          target: {
            surface: "evidence",
            params: { tab: "quality", severity: "high", outcome: "failing", range: "all" },
          },
        }
      : {
          key: "risk",
          label: "Policy exceptions",
          value: formatKpiValue(policy),
          delta: policy?.deltaText || policy?.reason || "",
          deltaTone:
            kpiState(policy) === "unavailable" ? "neutral" : numericValue(policy?.value) === 0 ? "good" : "bad",
          trend: Array.isArray(policy?.sparkline) ? policy.sparkline : [],
          hint:
            policy?.formula || "Explicit policy-exception signals from governed workflow and audit records.",
          target: { surface: "stewardship" },
        },
  ];

  return (
    <section className="ax-home-kpi-row" aria-label="Governance summary metrics">
      {tiles.map((tile) => (
        <StatTile
          key={tile.key}
          label={tile.label}
          value={tile.value}
          delta={tile.delta}
          deltaTone={tile.deltaTone}
          trend={tile.trend}
          progress={tile.progress}
          hint={tile.hint}
          target={tile.target}
          className="ax-home-kpi"
        />
      ))}
    </section>
  );
}

export default KpiRow;
