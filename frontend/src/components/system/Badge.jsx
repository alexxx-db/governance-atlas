import "./system.css";

/*
 * The one badge/pill (FRONTEND_BLUEPRINT §6). Replaces StatusBadge (gh),
 * MetadataChip (gh) and northstar StatusPill — the status→tone map below is
 * absorbed from StatusPill so existing status vocabulary keeps its colors.
 */

const TONE_BY_STATUS = {
  approved: "good",
  certified: "good",
  complete: "good",
  compliant: "good",
  ready: "good",
  available: "good",
  pending: "info",
  draft: "muted",
  proposed: "warn",
  warning: "warn",
  degraded: "warn",
  overdue: "bad",
  failed: "bad",
  critical: "bad",
  unavailable: "bad",
  error: "bad",
};

const TONES = new Set(["good", "warn", "bad", "info", "muted", "accent", "neutral"]);

export function Badge({ tone = "", status = "", size = "md", className = "", children = null }) {
  const resolvedTone =
    (TONES.has(tone) && tone) ||
    TONE_BY_STATUS[String(status || children || "").trim().toLowerCase()] ||
    "neutral";
  const classes = ["ax-sys-badge", `tone-${resolvedTone}`, `size-${size === "sm" ? "sm" : "md"}`, className]
    .filter(Boolean)
    .join(" ");
  return <span className={classes}>{children || status}</span>;
}

export default Badge;
