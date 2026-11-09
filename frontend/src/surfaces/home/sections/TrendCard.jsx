import { useState } from "react";
import { SectionCard } from "../../../components/system";
import { normalizeTrend, trendDeltaLabel, trendTickLabel } from "../format.js";

/*
 * TrendCard (Wave C2) — daily posture snapshots. Honors the payload's
 * collecting state: while history is young (< MIN_WINDOW_POINTS snapshots)
 * the card renders an explicit "Collecting since <date>" state and HIDES the
 * week-window toggles (kill list §7.6: no 12w/26w/52w chrome over one
 * snapshot; feasibility gate: toggles appear only with real history).
 */

const TREND_WINDOWS = [
  { key: "12w", label: "12w", points: 84 },
  { key: "26w", label: "26w", points: 182 },
  { key: "52w", label: "52w", points: 364 },
];

// Snapshots (days) required before a windowed line is honest to draw.
const MIN_WINDOW_POINTS = 8;

const WIDTH = 360;
const HEIGHT = 156;

function formatPathNumber(value) {
  return Number(value).toFixed(1);
}

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

function smoothAreaPath(pairs, baseline) {
  if (pairs.length < 2) return "";
  const line = smoothLinePath(pairs).replace(/^M[^\s]+ [^\s]+/, "");
  const first = pairs[0];
  const last = pairs[pairs.length - 1];
  return [
    `M${formatPathNumber(first[0])} ${formatPathNumber(baseline)}`,
    `L${formatPathNumber(first[0])} ${formatPathNumber(first[1])}`,
    line,
    `L${formatPathNumber(last[0])} ${formatPathNumber(baseline)}`,
    "Z",
  ].join(" ");
}

function visibleTicks(points) {
  if (points.length <= 7) return points;
  const cadence = Math.ceil(points.length / 6);
  return points.filter((_, index) => index === 0 || index === points.length - 1 || index % cadence === 0);
}

function AxisFrame({ children, ariaLabel }) {
  return (
    <div className="ax-home-trend" role="img" aria-label={ariaLabel}>
      <div className="ax-home-trend-axis" aria-hidden="true">
        <span>100%</span>
        <span>75%</span>
        <span>50%</span>
        <span>25%</span>
        <span>0%</span>
      </div>
      <div className="ax-home-trend-plot">{children}</div>
    </div>
  );
}

/* Collecting / unavailable state: one dot per real snapshot, no line drawn
 * through a single point (a 26-week line through one snapshot is synthetic
 * data — the exact defect this card exists to prevent). */
function CollectingChart({ point = null, collectingSince = "" }) {
  const hasPoint = Number.isFinite(point);
  const pointY = hasPoint ? 8 + ((100 - Math.max(0, Math.min(100, point))) / 100) * (HEIGHT - 22) : null;
  return (
    <AxisFrame
      ariaLabel={
        hasPoint
          ? `Trend history collecting since ${collectingSince || "today"}`
          : "Governance posture trend unavailable"
      }
    >
      {hasPoint ? (
        <svg className="ax-home-trend-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
          <line className="ax-home-trend-line" x1="24" x2={WIDTH - 24} y1={pointY} y2={pointY} strokeDasharray="4 6" opacity="0.5" />
          <circle className="ax-home-trend-dot" cx={WIDTH - 30} cy={pointY} r="4" />
        </svg>
      ) : null}
      <div className="ax-home-trend-note">
        {hasPoint
          ? `Daily snapshots recording — history since ${collectingSince || "today"}`
          : "Trend history unavailable"}
      </div>
    </AxisFrame>
  );
}

function TrendLineChart({ points }) {
  const min = Math.min(...points.map((p) => p.overall)) - 2;
  const max = Math.max(...points.map((p) => p.overall)) + 2;
  const range = max - min || 1;
  const pairs = points.map((point, index) => [
    points.length > 1 ? (index / (points.length - 1)) * WIDTH : WIDTH / 2,
    8 + ((max - point.overall) / range) * (HEIGHT - 22),
  ]);
  const latest = pairs[pairs.length - 1];
  return (
    <AxisFrame ariaLabel="Governance posture trend">
      <svg className="ax-home-trend-svg" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
        <path className="ax-home-trend-area" d={smoothAreaPath(pairs, HEIGHT)} />
        <path className="ax-home-trend-line" d={smoothLinePath(pairs)} />
        {latest ? <circle className="ax-home-trend-dot" cx={latest[0]} cy={latest[1]} r="4" /> : null}
      </svg>
      <div className="ax-home-trend-ticks" aria-hidden="true">
        {visibleTicks(points).map((point) => (
          <span key={point.label}>{trendTickLabel(point.label)}</span>
        ))}
      </div>
    </AxisFrame>
  );
}

/**
 * @param {{ posture?: Record<string, any> }} props
 */
export function TrendCard({ posture = {} }) {
  // Hook runs unconditionally, before any early return (CLAUDE.md rule).
  const [windowKey, setWindowKey] = useState("26w");

  const points = normalizeTrend(posture.trend || []).filter((point) => Number.isFinite(point.overall));
  const collecting = posture.trendState === "collecting" || points.length < 2;
  const showWindows = !collecting && points.length >= MIN_WINDOW_POINTS;
  const selectedWindow = TREND_WINDOWS.find((item) => item.key === windowKey) || TREND_WINDOWS[0];
  const windowedPoints =
    showWindows && points.length > selectedWindow.points ? points.slice(-selectedWindow.points) : points;
  const collectingSince = trendTickLabel(posture.collectingSince) || "";

  return (
    <SectionCard
      className="ax-home-trend-card"
      title={showWindows ? `Posture trend · ${selectedWindow.label}` : "Posture trend"}
      subtitle="Daily governance snapshots recorded by Axiom"
      tooltip="Historical posture snapshots are shown only when recorded; nothing is interpolated."
      actions={
        showWindows ? (
          <div className="ax-home-trend-windows" role="group" aria-label="Posture trend range">
            {TREND_WINDOWS.map((item) => (
              <button
                aria-pressed={selectedWindow.key === item.key}
                className={selectedWindow.key === item.key ? "is-active" : ""}
                key={item.key}
                onClick={() => setWindowKey(item.key)}
                type="button"
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null
      }
    >
      {collecting ? (
        <CollectingChart
          point={points.length ? points[points.length - 1].overall : null}
          collectingSince={collectingSince}
        />
      ) : (
        <TrendLineChart points={windowedPoints} />
      )}
      <p className="ax-home-trend-footer">
        <strong>
          {collecting
            ? `Collecting since ${collectingSince || "today"}`
            : trendDeltaLabel(windowedPoints)}
        </strong>
        {collecting
          ? " · one snapshot per day"
          : showWindows
            ? ` over the last ${selectedWindow.label.replace("w", " weeks")}`
            : ""}
      </p>
    </SectionCard>
  );
}

export default TrendCard;
