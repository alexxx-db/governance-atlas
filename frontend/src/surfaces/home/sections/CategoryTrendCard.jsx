import { useMemo, useState } from "react";
import { EmptyState, SectionCard, TabStrip } from "../../../components/system";
import { trendTickLabel } from "../format.js";

/*
 * CategoryTrendCard (G9) — per-category governance history from the command
 * center payload's `categoryTrends` key. Where TrendCard shows the single
 * aggregate posture line, this breaks the estate down by domain (governance
 * score) or certification tier (percent), one mini sparkline per category,
 * sorted worst-first so the categories that need attention lead.
 *
 * Honesty rules (mirroring TrendCard):
 *   - A category flagged `collecting` (fewer than a real week of snapshots)
 *     renders its real points as discrete dots with a "collecting since"
 *     caption — never a smooth multi-week line drawn through 1-2 points.
 *   - `delta` / `deltaTone` are shown only once there are >= 2 real points.
 */

const SPARK_W = 132;
const SPARK_H = 40;
const SPARK_PAD_Y = 5;
const MAX_ROWS = 8;

function formatPathNumber(value) {
  return Number(value).toFixed(1);
}

/* Compact Catmull-Rom → cubic-Bézier smoothing, same shape math as TrendCard
 * but scoped to the small sparkline geometry. */
function smoothLinePath(pairs) {
  if (pairs.length < 2) return "";
  let path = `M${formatPathNumber(pairs[0][0])} ${formatPathNumber(pairs[0][1])}`;
  for (let index = 0; index < pairs.length - 1; index += 1) {
    const previous = pairs[index - 1] || pairs[index];
    const current = pairs[index];
    const next = pairs[index + 1];
    const afterNext = pairs[index + 2] || next;
    const cp1x = current[0] + (next[0] - previous[0]) / 6;
    const cp1y = current[1] + (next[1] - previous[1]) / 6;
    const cp2x = next[0] - (afterNext[0] - current[0]) / 6;
    const cp2y = next[1] - (afterNext[1] - current[1]) / 6;
    path += ` C${formatPathNumber(cp1x)} ${formatPathNumber(cp1y)} ${formatPathNumber(cp2x)} ${formatPathNumber(cp2y)} ${formatPathNumber(next[0])} ${formatPathNumber(next[1])}`;
  }
  return path;
}

function toneClass(deltaTone) {
  const tone = String(deltaTone || "").toLowerCase();
  if (/up|pos|good|improv|rise|gain|success/.test(tone)) return "is-up";
  if (/down|neg|bad|regress|drop|fall|danger/.test(tone)) return "is-down";
  return "is-flat";
}

function numeric(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatValue(value, unit) {
  const n = numeric(value);
  if (n === null) return "—";
  if (unit === "percent") return `${Math.round(n)}%`;
  // score / default: keep one decimal only when it carries information.
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function formatDelta(delta, unit) {
  if (typeof delta === "string") return delta.trim() || null;
  const n = numeric(delta);
  if (n === null || n === 0) return null;
  const sign = n > 0 ? "+" : "";
  const suffix = unit === "percent" ? "pp" : "pt";
  const magnitude = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return `${sign}${magnitude}${suffix}`;
}

/* One category's mini history. `collecting` categories render discrete dots
 * (never a synthetic line); established categories render a smooth line +
 * fill tinted by the delta tone. */
function CategorySparkline({ points, collecting, tone }) {
  const values = points.map((p) => numeric(p.value)).filter((v) => v !== null);
  if (!values.length) {
    return <div className="ax-home-cat-spark is-empty" aria-hidden="true" />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const usable = points.filter((p) => numeric(p.value) !== null);
  const pairs = usable.map((point, index) => [
    usable.length > 1 ? (index / (usable.length - 1)) * SPARK_W : SPARK_W / 2,
    SPARK_PAD_Y + ((max - numeric(point.value)) / range) * (SPARK_H - SPARK_PAD_Y * 2),
  ]);
  const drawLine = !collecting && pairs.length >= 2;
  const last = pairs[pairs.length - 1];
  return (
    <svg
      className={`ax-home-cat-spark ${toneClass(tone)}`.trim()}
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {drawLine ? <path className="ax-home-cat-spark-line" d={smoothLinePath(pairs)} /> : null}
      {collecting
        ? pairs.map((pair, index) => (
            <circle
              key={index}
              className="ax-home-cat-spark-collecting-dot"
              cx={pair[0]}
              cy={pair[1]}
              r="2.4"
            />
          ))
        : last
          ? <circle className="ax-home-cat-spark-dot" cx={last[0]} cy={last[1]} r="3" />
          : null}
    </svg>
  );
}

function CategoryRow({ category, unit }) {
  const points = Array.isArray(category.points) ? category.points : [];
  const realPoints = points.filter((p) => numeric(p.value) !== null);
  const collecting = Boolean(category.collecting) || realPoints.length < 2;
  const since = trendTickLabel(category.collectingSince) || "";
  const delta = collecting ? null : formatDelta(category.delta, unit);
  const assetCount = numeric(category.assetCount);

  return (
    <li className="ax-home-cat-row">
      <div className="ax-home-cat-head">
        <span className="ax-home-cat-label" title={category.label}>
          {category.label || category.key}
        </span>
        {assetCount !== null ? (
          <span className="ax-home-cat-count">{assetCount.toLocaleString()} assets</span>
        ) : null}
      </div>
      <CategorySparkline points={realPoints} collecting={collecting} tone={category.deltaTone} />
      <div className="ax-home-cat-meta">
        <span className="ax-home-cat-latest">{formatValue(category.latest, unit)}</span>
        {collecting ? (
          <span className="ax-home-cat-collecting">
            {since ? `collecting since ${since}` : "collecting"}
          </span>
        ) : delta ? (
          <span className={`ax-home-cat-delta ${toneClass(category.deltaTone)}`.trim()}>{delta}</span>
        ) : null}
      </div>
    </li>
  );
}

/**
 * @param {{ categoryTrends?: Record<string, any> | null }} props
 */
export function CategoryTrendCard({ categoryTrends = null }) {
  // All hooks run before any early return (CLAUDE.md hook-order rule).
  const kinds = useMemo(
    () => (Array.isArray(categoryTrends?.kinds) ? categoryTrends.kinds.filter((k) => k && k.key) : []),
    [categoryTrends],
  );
  const [kindKey, setKindKey] = useState(null);

  const activeKind = useMemo(() => {
    if (!kinds.length) return null;
    return kinds.find((k) => k.key === kindKey) || kinds[0];
  }, [kinds, kindKey]);

  const series = useMemo(() => {
    if (!categoryTrends || !activeKind) return [];
    const rows = categoryTrends[activeKind.key];
    return Array.isArray(rows) ? rows.filter(Boolean) : [];
  }, [categoryTrends, activeKind]);

  const hasAnySeries = useMemo(
    () => kinds.some((k) => Array.isArray(categoryTrends?.[k.key]) && categoryTrends[k.key].length > 0),
    [kinds, categoryTrends],
  );

  // Honest empty state: no kinds declared, or every kind's series is empty.
  if (!categoryTrends || !kinds.length || !hasAnySeries) {
    return (
      <SectionCard
        className="ax-home-cat-card"
        title="Category trends"
        subtitle="Per-category governance history"
        tooltip="Domain and tier histories are shown only from recorded daily snapshots; nothing is interpolated."
      >
        <EmptyState
          title="Per-category history is collecting"
          body="Trends appear here as daily snapshots accumulate across domains and certification tiers."
        />
      </SectionCard>
    );
  }

  const unit = activeKind?.unit || "score";
  const visible = series.slice(0, MAX_ROWS);
  const overflow = series.length - visible.length;

  return (
    <SectionCard
      className="ax-home-cat-card"
      title={activeKind?.label || "Category trends"}
      subtitle="Daily snapshots, worst-first"
      tooltip="Domain and tier histories are shown only from recorded daily snapshots; categories still collecting are labeled, never drawn as a full line."
      actions={
        kinds.length > 1 ? (
          <TabStrip
            ariaLabel="Category trend breakdown"
            tabs={kinds.map((k) => ({ key: k.key, label: k.label }))}
            value={activeKind?.key}
            onChange={setKindKey}
          />
        ) : null
      }
    >
      {visible.length ? (
        <ul className="ax-home-cat-list">
          {visible.map((category) => (
            <CategoryRow key={category.key || category.label} category={category} unit={unit} />
          ))}
        </ul>
      ) : (
        <EmptyState
          title="Nothing to show for this breakdown"
          body="No categories have recorded snapshots yet."
        />
      )}
      {overflow > 0 ? (
        <p className="ax-home-cat-footer">
          Showing the {MAX_ROWS} categories needing the most attention · {overflow} more not shown
        </p>
      ) : null}
    </SectionCard>
  );
}

export default CategoryTrendCard;
