import "./system.css";
import { normalizeStatus } from "./statusContract";

/*
 * The one section card (FRONTEND_BLUEPRINT §6). Contract absorbed by COPY
 * from components/northstar/SectionCard.jsx (northstar/ stays untouched
 * until Wave C moves its consumers): {title, eyebrow, subtitle, actions,
 * tooltip, children} — plus a `status` prop taking the Wave-A2 query/status
 * shape so a card shows its own hydrating shimmer / degraded footnote
 * without bespoke markup. Children are never hidden by status: content-level
 * states belong to StateViews.ForQuery inside the card.
 */

export function SectionCard({
  title,
  eyebrow = "",
  subtitle = "",
  actions = null,
  tooltip = "",
  status = null,
  children,
  className = "",
}) {
  const norm = normalizeStatus(status);
  const busy = norm?.status === "loading" || norm?.status === "hydrating";
  const degraded = norm?.status === "degraded";
  const unavailable = norm?.status === "unavailable" || norm?.status === "error";

  return (
    <section
      className={`ax-sys-section-card ${busy ? "is-hydrating" : ""} ${className}`.trim()}
      aria-busy={busy || undefined}
      data-status={norm?.status || undefined}
    >
      <header className="ax-sys-section-card-header">
        <div>
          {eyebrow ? <div className="ax-sys-eyebrow">{eyebrow}</div> : null}
          <h2>
            <span>{title}</span>
            {tooltip ? (
              <button
                aria-label={`${title}: ${tooltip}`}
                className="ax-sys-info-tip"
                title={tooltip}
                type="button"
              >
                i
              </button>
            ) : null}
          </h2>
          {subtitle ? <p className="ax-sys-section-card-subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="ax-sys-section-card-actions">{actions}</div> : null}
      </header>
      {children}
      {degraded || unavailable ? (
        <p className={`ax-sys-section-card-footnote tone-${unavailable ? "bad" : "warn"}`} role="status">
          {norm.reason ||
            (unavailable
              ? "This section is unavailable for the current visibility scope."
              : "Some signals in this section are limited right now.")}
        </p>
      ) : null}
    </section>
  );
}

export default SectionCard;
