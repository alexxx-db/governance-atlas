import "./system.css";
import { Link, useInRouterContext } from "react-router-dom";
import { hrefForRef } from "./refs";

/*
 * The one KPI/stat tile (FRONTEND_BLUEPRINT §6). Absorbs northstar
 * MetricCard + DonutMetric + Sparkline as variants; replaces the ~190
 * hero/KPI selector families at their consumers' waves. `target` makes any
 * KPI a navigable door to its evidence (a real anchor — COHESION law #1);
 * pass the Wave-A3 `navigate` adapter to intercept left-click.
 */

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

/** Absorbed northstar/Sparkline — same geometry, kit class name. */
function Spark({ values = [], width = 96, height = 32, label = "Trend" }) {
  const nums = values.map(Number).filter(Number.isFinite);
  if (nums.length < 2) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = max - min || 1;
  const points = nums
    .map((value, index) => {
      const x = (index / (nums.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      aria-label={label}
      className="ax-sys-sparkline"
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

/** Absorbed northstar/DonutMetric — same ring math, kit class name. */
function Donut({ percent = 0, size = 112 }) {
  const pct = clampPercent(percent);
  const radius = 45;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;
  return (
    <span className="ax-sys-donut" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 110 110">
        <circle className="ax-sys-donut-track" cx="55" cy="55" r={radius} />
        <circle
          className="ax-sys-donut-value"
          cx="55"
          cy="55"
          r={radius}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
    </span>
  );
}

const DELTA_TONES = new Set(["good", "warn", "bad", "neutral"]);

export function StatTile({
  label,
  value,
  delta = "",
  deltaTone = "neutral",
  trend = [],
  tone = "neutral",
  hint = "",
  icon = null,
  meta = "",
  progress = undefined,
  variant = "metric",
  percent = undefined,
  onClick = null,
  target = null,
  navigate = null,
  className = "",
}) {
  // Hooks first, unconditionally (CLAUDE.md hook-order rule).
  const inRouter = useInRouterContext();

  const href = target ? hrefForRef(target) : null;
  const isDonut = variant === "donut";
  const hasProgress = typeof progress === "number";
  const resolvedDeltaTone = DELTA_TONES.has(deltaTone) ? deltaTone : "neutral";

  const classes = [
    "ax-sys-stat-tile",
    `tone-${tone}`,
    isDonut ? "is-donut" : "",
    href ? "is-link" : "",
    !href && onClick ? "is-action" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const body = (
    <>
      <span className="ax-sys-stat-tile-head">
        {icon ? (
          <span className="ax-sys-stat-tile-icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        <span className="ax-sys-stat-tile-label" title={hint || undefined}>
          {label}
        </span>
        {hint ? (
          // Not a nested <button>: tile roots can be anchors/buttons, and
          // interactive content inside them is invalid HTML.
          <span className="ax-sys-info-tip" role="img" aria-label={hint}>
            i
          </span>
        ) : null}
      </span>
      <span className="ax-sys-stat-tile-main">
        {isDonut ? <Donut percent={percent ?? value} /> : null}
        <strong className="ax-sys-stat-tile-value">
          {value ?? (isDonut && percent != null ? `${clampPercent(percent)}%` : "—")}
        </strong>
        {!isDonut && trend.length ? <Spark values={trend} label={`${label} trend`} /> : null}
      </span>
      {hasProgress ? (
        <span className="ax-sys-progress" aria-label={`${label} progress`}>
          <span style={{ width: `${clampPercent(progress)}%` }} />
        </span>
      ) : null}
      {delta ? <span className={`ax-sys-stat-tile-delta tone-${resolvedDeltaTone}`}>{delta}</span> : null}
      {meta ? <span className="ax-sys-stat-tile-meta">{meta}</span> : null}
    </>
  );

  if (href) {
    const Anchor = inRouter ? Link : "a";
    const anchorProps = /** @type {any} */ (inRouter ? { to: href } : { href });
    const handleClick = (event) => {
      if (!navigate || event.defaultPrevented) return;
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(target, { href });
    };
    return (
      <Anchor {...anchorProps} className={classes} onClick={handleClick}>
        {body}
      </Anchor>
    );
  }
  if (onClick) {
    return (
      <button type="button" className={classes} onClick={onClick}>
        {body}
      </button>
    );
  }
  return <article className={classes}>{body}</article>;
}

export default StatTile;
