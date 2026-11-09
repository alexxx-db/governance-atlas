import { StatTile } from "../../../components/system";
import {
  evidenceDateLabel,
  formatCount,
  formatKpiValue,
  kpiState,
  numericValue,
  percentLabel,
  trendDeltaLabel,
  trendTickLabel,
} from "../format.js";

/*
 * PostureHero (Wave C2) — the executive answer band: posture ring, estate
 * narrative, hero stat tiles (each a real anchor into its evidence surface),
 * and the "What changed today" column with its honesty gate.
 *
 * Present mode is gone (PRODUCT_BLUEPRINT §7 kill list #3) — no fullscreen
 * toggle ships here.
 */

function PostureRing({ value, label, caption, formula, sublabel }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  const size = 168;
  const stroke = 13;
  const radius = (size - stroke - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;
  const center = size / 2;
  const display = Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(1);
  return (
    <div className="ax-home-ring-block">
      {/* Only the value lives inside the arc now — the descriptive label used
          to overlap the ring stroke ("interposed on the visual"); it renders
          as a proper caption beneath the gauge. */}
      <div className="ax-home-ring" style={{ width: size, height: size }}>
        <svg aria-hidden="true" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          <circle className="ax-home-ring-track" cx={center} cy={center} r={radius} />
          <circle
            className="ax-home-ring-value"
            cx={center}
            cy={center}
            r={radius}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform={`rotate(-90 ${center} ${center})`}
          />
        </svg>
        <div className="ax-home-ring-center">
          <strong>
            {display}
            <small>%</small>
          </strong>
        </div>
      </div>
      <div className="ax-home-ring-label">
        <span className="ax-home-ring-title">
          {label}
          {formula ? (
            /* Formula popover survives the rebuild: payload formula string,
               surfaced through the kit's info tip. */
            <span className="ax-sys-info-tip" role="img" aria-label={`How ${label} is calculated: ${formula}`} title={formula}>
              i
            </span>
          ) : null}
        </span>
        {/* One-line disambiguation: posture is a composite score, coverage is
            one metadata metric — the two numbers looked interchangeable. */}
        {sublabel ? <p className="ax-home-ring-sub">{sublabel}</p> : null}
        {caption ? <em>{caption}</em> : null}
      </div>
    </div>
  );
}

function changeRows({ data, coverageKpi, policyKpi, risk }) {
  const qualityStamp = evidenceDateLabel(data.insights?.qualityEvidenceAt);
  const riskStamp = evidenceDateLabel(risk.evidenceAt || data.insights?.qualityEvidenceAt);
  const explicit = (Array.isArray(data.changesToday) ? data.changesToday : [])
    .map((item, index) => ({
      label: item?.label || item?.metric || `Change ${index + 1}`,
      value: item?.value,
      delta: item?.delta || item?.detail || "",
      previous: item?.previous ?? item?.previousValue ?? null,
      format: item?.format || item?.previousFormat || "count",
      tone: item?.tone || "info",
    }))
    .filter((item) => item.label);
  if (explicit.length) return { rows: explicit, hasRealDelta: true, qualityStamp };

  const rows = [
    {
      label: "Metadata coverage",
      value: percentLabel(coverageKpi?.value),
      numeric: numericValue(coverageKpi?.value),
      delta: coverageKpi?.deltaText || coverageKpi?.delta || "Coverage evidence unavailable",
      previous: numericValue(coverageKpi?.previousValue ?? coverageKpi?.previous),
      format: "percent",
      tone: kpiState(coverageKpi) === "unavailable" ? "muted" : "good",
    },
    {
      label: "Quality SLA",
      value: percentLabel(data.insights?.qualitySla),
      numeric: numericValue(data.insights?.qualitySla),
      delta: data.insights?.qualitySignalAvailable
        ? `${formatCount(data.insights?.qualityChecksEvaluated)} checks evaluated${qualityStamp ? ` · ${qualityStamp}` : ""}`
        : "No quality checks run yet",
      previous: numericValue(data.insights?.previousQualitySla),
      format: "percent",
      tone: data.insights?.qualitySignalAvailable ? "good" : "muted",
    },
    {
      label: risk.available ? "High-risk quality findings" : "Policy exceptions",
      value: risk.available ? formatCount(risk.high) : formatKpiValue(policyKpi),
      numeric: risk.available ? risk.high : numericValue(policyKpi?.value),
      delta: risk.available
        ? riskStamp || "Quality-run findings by severity"
        : policyKpi?.reason || "Signal unavailable",
      previous: numericValue(policyKpi?.previousValue ?? policyKpi?.previous),
      format: "count",
      tone: risk.available ? (risk.high > 0 ? "warn" : "good") : "muted",
    },
    {
      label: "Lineage coverage",
      value: percentLabel(data.lineage?.coverage),
      numeric: numericValue(data.lineage?.coverage),
      delta: data.signalAvailability?.lineage
        ? data.lineage?.reason || "Backed by Unity Catalog lineage"
        : "Lineage signal unavailable",
      previous: numericValue(data.lineage?.previousCoverage),
      format: "percent",
      tone: data.signalAvailability?.lineage ? "info" : "muted",
    },
  ];
  // Honesty gate: a row only counts as "changed today" when a prior snapshot
  // value exists AND differs from the current value. All-zero deltas render
  // an explicit "No changes today" instead of rows dressed as news.
  const hasRealDelta = rows.some(
    (row) => row.previous !== null && row.numeric !== null && Math.abs(row.numeric - row.previous) >= 0.05,
  );
  return { rows, hasRealDelta, qualityStamp };
}

function formatChange(value, format) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  return format === "percent" ? percentLabel(value) : formatCount(value);
}

export function PostureHero({ data, kpis, loading = false }) {
  const coverageKpi = kpis.metadataCoverage;
  const certifiedKpi = kpis.certifiedCriticalAssets;
  const policyKpi = kpis.policyExceptions;
  const governedKpi = kpis.governedAssets;
  const risk = kpis.risk;

  const postureOverall = numericValue(data.posture?.overall);
  const coverageValue = numericValue(coverageKpi?.value);
  const postureValue = postureOverall ?? coverageValue;
  const postureTitle = postureOverall !== null ? "Governance posture" : "Metadata coverage";
  // The ring and the "metadata coverage" figure in the headline are different
  // measures; spell out which is which so the two percentages don't read as
  // the same number reported twice.
  const postureSublabel =
    postureOverall !== null
      ? "Composite health score — blends coverage, certification & stewardship"
      : "Share of visible assets with complete metadata";
  const ringCaption =
    data.posture?.trendState === "collecting"
      ? `History since ${trendTickLabel(data.posture?.collectingSince) || "today"}`
      : trendDeltaLabel(data.posture?.trend || []);

  const estateLabel = (() => {
    const label = String(data.estate?.estateLabel || "").trim();
    if (label) return /^data estate$/i.test(label) ? "the data estate" : label;
    const catalogCount = numericValue(data.estate?.catalogCount);
    return catalogCount
      ? `the data estate (${formatCount(catalogCount)} visible catalog${catalogCount === 1 ? "" : "s"})`
      : "the visible data estate";
  })();

  const governedCount = numericValue(governedKpi?.value);
  const cdeCount = numericValue(data.cdeSignal?.count ?? data.estate?.cdeCount);
  const { rows, hasRealDelta, qualityStamp } = changeRows({ data, coverageKpi, policyKpi, risk });

  const heroTiles = [
    {
      key: "certified",
      label: "Certified critical assets",
      value: formatKpiValue(certifiedKpi),
      delta: certifiedKpi?.deltaText || certifiedKpi?.reason || "",
      deltaTone: kpiState(certifiedKpi) === "unavailable" ? "neutral" : "good",
      hint:
        certifiedKpi?.formula ||
        'Assets that are both critical and strictly certified (certification == "Certified").',
      target: { surface: "discovery", params: { views: ["Certified"] } },
    },
    {
      key: "exceptions",
      label: "Policy exceptions",
      value: formatKpiValue(policyKpi),
      delta: policyKpi?.deltaText || policyKpi?.reason || "",
      deltaTone:
        kpiState(policyKpi) === "unavailable" ? "neutral" : numericValue(policyKpi?.value) === 0 ? "good" : "bad",
      hint: policyKpi?.formula || "Explicit policy-exception signals from governance workflow and audit records.",
      target: { surface: "stewardship" },
    },
    {
      key: "cdes",
      label: "CDEs tracked",
      value: cdeCount === null ? "—" : formatCount(cdeCount),
      // Subtitle comes from the payload ("Criticality-derived") — never the
      // fabricated "Tag-governed · lineage-backed" copy.
      delta:
        cdeCount === null
          ? "CDE registry unavailable"
          : cdeCount === 0
            ? "No assets tagged as CDEs yet"
            : data.cdeSignal?.subtitle || "",
      deltaTone: "neutral",
      hint: data.cdeSignal?.definition || "",
      target: { surface: "glossary", params: { tab: "cdes" } },
    },
  ];

  return (
    <section className="ax-home-hero" aria-label="Current governance posture">
      <div className="ax-home-hero-ring">
        {postureValue === null ? (
          <div className="ax-home-ring-unavailable">
            <strong aria-hidden="true">—</strong>
            <span>Governance posture unavailable</span>
            <em>{ringCaption}</em>
          </div>
        ) : (
          <PostureRing
            value={postureValue}
            label={postureTitle}
            sublabel={postureSublabel}
            caption={ringCaption}
            formula={postureOverall !== null ? data.posture?.formula || "" : coverageKpi?.formula || ""}
          />
        )}
      </div>
      <div className="ax-home-hero-copy">
        <span className="ax-sys-eyebrow">The state of {estateLabel}</span>
        <h2 className="ax-home-headline">
          {governedCount !== null ? (
            <>
              <strong>{formatKpiValue(governedKpi)}</strong> governed assets are in scope
              {coverageValue !== null ? (
                <>
                  {" "}
                  with <strong>{percentLabel(coverageKpi?.value)}</strong> metadata coverage across the visible
                  estate.
                </>
              ) : (
                <> Coverage evidence is still loading.</>
              )}
            </>
          ) : loading ? (
            <>Reading live governance evidence…</>
          ) : (
            <>
              <strong>Command Center is waiting on backed governance metrics.</strong> Unavailable values stay
              blank until Unity Catalog or the governance store returns evidence.
            </>
          )}
        </h2>
        <div className="ax-home-hero-tiles">
          {heroTiles.map((tile) => (
            <StatTile
              key={tile.key}
              label={tile.label}
              value={tile.value}
              delta={tile.delta}
              deltaTone={tile.deltaTone}
              hint={tile.hint}
              target={tile.target}
              className="ax-home-hero-tile"
            />
          ))}
        </div>
      </div>
      <div className="ax-home-changes" aria-label="What changed today">
        <h3>What changed today</h3>
        {loading && !hasRealDelta ? (
          // Still loading: never assert "No changes today" before the
          // command-center payload has actually arrived.
          <div className="ax-home-no-changes" role="status">
            <strong>Loading today's changes…</strong>
            <em>Reading the latest governance snapshot</em>
          </div>
        ) : hasRealDelta ? (
          rows.map((row) => (
            <div className={`ax-home-change tone-${row.tone}`} key={row.label}>
              <span>{row.label}</span>
              <strong>
                {row.previous !== null && row.previous !== undefined ? (
                  <>
                    <small>{formatChange(row.previous, row.format)}</small>
                    {formatChange(row.value, row.format)}
                  </>
                ) : (
                  formatChange(row.value, row.format)
                )}
              </strong>
              <em>{row.delta}</em>
            </div>
          ))
        ) : (
          // Honest zero-delta state: old evidence keeps its date instead of
          // masquerading as today's movement.
          <div className="ax-home-no-changes" role="status">
            <strong>No changes today</strong>
            <em>
              {qualityStamp
                ? `Latest quality ${qualityStamp}`
                : "Signals are unchanged since the last recorded snapshot"}
            </em>
          </div>
        )}
      </div>
    </section>
  );
}

export default PostureHero;
