import { Badge } from "../../components/system";
import { refHref } from "../../nav/refs.js";
import { useAxiomNavigate } from "../../nav/useAxiomNavigate.js";
import { useEmetOverview, useEmetStatus } from "../../hooks/useemet";

/*
 * EmetQualityBand — surfaces the sibling emet product's validation
 * trust inside GA's Evidence › Quality findings tab, so the two products'
 * quality signals live side by side. It is additive and self-detecting: when
 * emet isn't installed it renders nothing (the tab is unchanged). It never
 * fabricates — every number comes from the live emet control plane.
 */

function num(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function trustStatus(score) {
  const n = num(score);
  if (n === null) return "loading";
  if (n >= 90) return "available";
  if (n >= 75) return "pending";
  if (n >= 50) return "degraded";
  return "unavailable";
}

export function EmetQualityBand() {
  const status = useEmetStatus();
  const overview = useEmetOverview({ enabled: status.detected });
  const navigate = useAxiomNavigate();

  // Self-detecting: render nothing at all unless emet is present. Never
  // show a broken/empty band on workspaces without emet.
  if (!status.detected) return null;

  const rollup = overview.rollup;
  const trust = num(rollup?.trustScore);
  const target = { surface: "emet", params: {} };
  const href = refHref(target);

  const stats = [
    { key: "trust", label: "Portfolio trust", value: trust === null ? "—" : trust.toFixed(1), status: trustStatus(trust) },
    { key: "failing", label: "Jobs failing", value: rollup ? String(rollup.failingJobCount ?? 0) : "—", danger: (rollup?.failingJobCount ?? 0) > 0 },
    { key: "cutover", label: "Cutover blockers", value: rollup ? String(rollup.cutoverBlockers ?? 0) : "—", danger: (rollup?.cutoverBlockers ?? 0) > 0 },
    { key: "jobs", label: "Active jobs", value: rollup ? String(rollup.jobCount ?? 0) : "—" },
  ];

  return (
    <section className="ax-evid-emet" aria-label="emet validation trust">
      <div className="ax-evid-emet-lead">
        <Badge status={status.status?.state === "available" ? "available" : "degraded"}>emet</Badge>
        <span>Validation trust from the emet control plane, alongside Axiom quality findings.</span>
      </div>
      <div className="ax-evid-emet-stats">
        {stats.map((stat) => (
          <div key={stat.key} className="ax-evid-emet-stat">
            <span className="ax-evid-emet-label">{stat.label}</span>
            <strong className={stat.danger ? "is-danger" : stat.status ? `is-${stat.status}` : ""}>{stat.value}</strong>
          </div>
        ))}
      </div>
      <a
        className="ax-evid-emet-link"
        href={href}
        onClick={(event) => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
          event.preventDefault();
          navigate(target);
        }}
      >
        Open Control Center ↗
      </a>
    </section>
  );
}

export default EmetQualityBand;
