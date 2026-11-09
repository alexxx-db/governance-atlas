import "./system.css";
import { Button } from "./Button";
import { normalizeStatus } from "./statusContract";

/*
 * The ONLY status renderings allowed in the product (FRONTEND_BLUEPRINT §6,
 * COHESION law #3 "one loading grammar"):
 *   skeleton               = loading
 *   "—" + reason           = unavailable (honest, never fake data)
 *   banner strip           = degraded / stale
 * `ForQuery` consumes the Wave-A2 `useAxiomQuery` status contract directly
 * so surfaces stop hand-interpreting envelope states (the 10-12 divergent
 * renderings in FRONTEND_BLUEPRINT §3.3 die at their consumers' waves).
 */

const SKELETON_VARIANTS = { tile: 3, card: 4, table: 6, page: 8 };

/**
 * @param {{ variant?: string, lines?: number, label?: string, className?: string }} props
 */
export function LoadingState({ variant = "card", lines, label = "Loading", className = "" }) {
  const kind = SKELETON_VARIANTS[variant] != null ? variant : "card";
  const count = Number.isInteger(lines) && lines > 0 ? lines : SKELETON_VARIANTS[kind];
  return (
    <div
      className={`ax-sys-loading is-${kind} ${className}`.trim()}
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className="ax-sys-skeleton" aria-hidden="true" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon = null,
  title = "Nothing to show",
  body = "",
  action = null,
  className = "",
}) {
  return (
    <div className={`ax-sys-empty-state ${className}`.trim()}>
      {icon ? (
        <span className="ax-sys-empty-state-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <h3>{title}</h3>
      {body ? <p>{body}</p> : null}
      {action ? <div className="ax-sys-empty-state-action">{action}</div> : null}
    </div>
  );
}

export function UnavailableState({
  title = "Unavailable",
  reason = "",
  onRetry = null,
  retryLabel = "Retry",
  className = "",
}) {
  return (
    <div className={`ax-sys-unavailable ${className}`.trim()} role="status">
      {/* "—" is the one honest-unavailability glyph (COHESION law #3) */}
      <span className="ax-sys-unavailable-glyph" aria-hidden="true">
        —
      </span>
      <div className="ax-sys-unavailable-copy">
        <h3>{title}</h3>
        <p>{reason || "This signal is unavailable for the current visibility scope."}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

export function StatusBanner({
  tone = "warning",
  title = "",
  message = "",
  warnings = [],
  onRetry = null,
  retryLabel = "Retry",
  action = null,
  className = "",
}) {
  const items = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
  const body =
    message || (items.length ? items.join(" ") : "Some live signals are unavailable for the current visibility scope.");
  return (
    <div
      className={`ax-sys-status-banner tone-${tone} ${className}`.trim()}
      // danger banners must interrupt AT; informational ones must not.
      role={tone === "danger" ? "alert" : "status"}
    >
      <div className="ax-sys-status-banner-copy">
        {title ? <strong>{title}</strong> : null}
        <span>{body}</span>
      </div>
      {action}
      {onRetry ? (
        <Button variant="tertiary" size="sm" onClick={onRetry}>
          {retryLabel}
        </Button>
      ) : null}
    </div>
  );
}

function defaultIsEmpty(data) {
  if (Array.isArray(data)) return data.length === 0;
  return data == null;
}

/**
 * `<StateViews.ForQuery query={q} empty={<EmptyState/>}>{(data) => …}</StateViews.ForQuery>`
 *
 * Renders per the A2 status contract:
 *   loading            → skeleton (or `loading` override)
 *   hydrating          → children with aria-busy (seed rendered, refresh in flight);
 *                        falls back to skeleton only when the seed is empty
 *   available          → children, or `empty` when isEmpty(data)
 *   degraded           → StatusBanner (warnings + retry) ABOVE children — data never wiped
 *   unavailable/error  → UnavailableState with honest reason + retry
 */
export function ForQuery({
  query,
  children = null,
  isEmpty = defaultIsEmpty,
  empty = null,
  loading = null,
  unavailable = null,
  loadingVariant = "card",
}) {
  const norm = normalizeStatus(query);
  const status = norm?.status ?? "loading";
  const data = query && typeof query === "object" ? query.data : undefined;

  if (status === "loading") {
    return loading ?? <LoadingState variant={loadingVariant} />;
  }
  if (status === "unavailable" || status === "error") {
    return (
      unavailable ?? (
        <UnavailableState
          title={status === "error" ? "Something went wrong" : "Unavailable"}
          reason={norm?.reason ?? ""}
          onRetry={norm?.refresh}
        />
      )
    );
  }

  const emptyNow = Boolean(isEmpty(data));
  if (emptyNow) {
    // Empty while still hydrating means the seed hasn't arrived — keep the
    // skeleton rather than flashing an empty state that will be wrong in 1s.
    if (status === "hydrating") return loading ?? <LoadingState variant={loadingVariant} />;
    return empty ?? <EmptyState />;
  }

  const content = typeof children === "function" ? children(data, norm) : children;
  if (status === "degraded") {
    return (
      <>
        <StatusBanner
          tone="warning"
          title="Data availability is limited"
          warnings={norm?.warnings}
          onRetry={norm?.refresh}
        />
        {content}
      </>
    );
  }
  if (status === "hydrating") {
    return (
      <div className="ax-sys-hydrating" aria-busy="true">
        {content}
      </div>
    );
  }
  return content;
}

export const StateViews = {
  LoadingState,
  EmptyState,
  UnavailableState,
  StatusBanner,
  ForQuery,
};

export default StateViews;
