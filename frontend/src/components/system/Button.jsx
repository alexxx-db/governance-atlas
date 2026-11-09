import "./system.css";

/*
 * The one button (FRONTEND_BLUEPRINT §6 "Badge / Button"). Replaces the
 * 4-file `.gh-primary-button` cascade collision at the end of its wave.
 * No surface writes its own button CSS again, ever.
 */

const VARIANTS = new Set(["primary", "secondary", "tertiary", "icon"]);
const TONES = new Set(["neutral", "accent", "danger", "success", "warning"]);
const SIZES = new Set(["sm", "md"]);

export function Button({
  variant = "secondary",
  tone = "neutral",
  size = "md",
  icon = null,
  loading = false,
  disabled = false,
  type = "button",
  className = "",
  children = null,
  ...rest
}) {
  const v = VARIANTS.has(variant) ? variant : "secondary";
  const t = TONES.has(tone) ? tone : "neutral";
  const s = SIZES.has(size) ? size : "md";
  const classes = [
    "ax-sys-button",
    `is-${v}`,
    `tone-${t}`,
    `size-${s}`,
    loading ? "is-loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={/** @type {"button" | "submit" | "reset"} */ (type)}
      className={classes}
      // Loading disables interaction; aria-busy tells AT why.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className="ax-sys-button-spinner" aria-hidden="true" /> : null}
      {icon ? (
        <span className="ax-sys-button-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {/* icon-variant buttons carry no visible text; callers MUST pass aria-label */}
      {v === "icon" ? null : children != null ? <span className="ax-sys-button-label">{children}</span> : null}
    </button>
  );
}

export default Button;
