import "./system.css";
import { normalizeStatus } from "./statusContract";
import { StatusBanner } from "./StateViews";

/*
 * The one page frame (FRONTEND_BLUEPRINT §6). Every routed surface renders
 * exactly one PageShell: hero band (eyebrow/title/subtitle/actions),
 * breadcrumb row, the page-level status banner (rendered from the Wave-A2
 * status contract so no surface hand-renders banners), a sticky tab slot,
 * and an optional right rail. This single component is what makes 13
 * surfaces feel like one product.
 *
 * Wave-A note: breadcrumbs come from the A3 nav fabric later; until then
 * they are an explicit `breadcrumbs` node slot.
 */

export function PageShell({
  title,
  subtitle = "",
  eyebrow = "",
  status = null,
  actions = null,
  tabs = null,
  rail = null,
  breadcrumbs = null,
  onRetry = null,
  className = "",
  children,
}) {
  const norm = normalizeStatus(status);
  const retry = onRetry ?? norm?.refresh ?? null;
  const hydrating = norm?.status === "hydrating";
  const degraded = norm?.status === "degraded";
  const failed = norm?.status === "unavailable" || norm?.status === "error";

  return (
    <div className={`ax-sys-page ${className}`.trim()} data-status={norm?.status || undefined}>
      <header className="ax-sys-page-hero">
        {breadcrumbs ? (
          <nav className="ax-sys-page-breadcrumbs" aria-label="Breadcrumb">
            {breadcrumbs}
          </nav>
        ) : null}
        <div className="ax-sys-page-hero-row">
          <div className="ax-sys-page-hero-copy">
            {eyebrow ? <div className="ax-sys-eyebrow">{eyebrow}</div> : null}
            <h1>{title}</h1>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <div className="ax-sys-page-hero-side">
            {hydrating ? (
              // Quiet refresh indicator: seed data is on screen, a refresh
              // is in flight — never a blocking spinner (A2 seed contract).
              <span className="ax-sys-page-refreshing" role="status">
                Refreshing
              </span>
            ) : null}
            {actions ? <div className="ax-sys-page-actions">{actions}</div> : null}
          </div>
        </div>
      </header>
      {degraded ? (
        <StatusBanner
          tone="warning"
          title="Data availability is limited"
          warnings={norm.warnings}
          onRetry={retry}
        />
      ) : null}
      {failed ? (
        <StatusBanner
          tone="danger"
          title={norm.status === "error" ? "Something went wrong" : "This page is unavailable"}
          message={norm.reason || ""}
          warnings={norm.warnings}
          onRetry={retry}
        />
      ) : null}
      {tabs ? <div className="ax-sys-page-tabs">{tabs}</div> : null}
      <div className={`ax-sys-page-body ${rail ? "has-rail" : ""}`.trim()}>
        <div className="ax-sys-page-content">{children}</div>
        {rail ? <aside className="ax-sys-page-rail">{rail}</aside> : null}
      </div>
    </div>
  );
}

export default PageShell;
