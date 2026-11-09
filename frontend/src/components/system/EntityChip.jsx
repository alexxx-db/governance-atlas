import "./system.css";
import { Link, useInRouterContext } from "react-router-dom";
import { KIND_ICONS } from "./icons.jsx";
import { defaultRefLabel, hrefForRef } from "./refs";

/*
 * The keystone component (FRONTEND_BLUEPRINT §6, COHESION cross-linking
 * LAW): every rendered mention of an asset, column, term, CDE, owner,
 * work item, audit event, domain or catalog is a REAL `<a href>` rendered
 * by EntityChip — middle-clickable, copyable, a11y-navigable. No surface
 * may render these as raw text or bespoke buttons.
 *
 * Wave-A note: the A3 nav fabric isn't wired yet, so the chip defaults to
 * href-only Links (react-router <Link> inside a Router, plain <a> outside)
 * and accepts an optional `navigate(entity, {href})` adapter that takes
 * over left-click navigation without breaking modified-click semantics.
 */

const KIND_LABELS = {
  asset: "Asset",
  column: "Column",
  term: "Glossary term",
  cde: "Critical data element",
  owner: "Owner",
  request: "Work item",
  event: "Audit event",
  domain: "Domain",
  catalog: "Catalog",
  lineage: "Lineage",
  quality: "Quality finding",
};

function isModifiedClick(event) {
  return (
    event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
  );
}

export function EntityChip({
  entity = null,
  appearance = "chip",
  withHover = false,
  navigate = null,
  className = "",
  children = null,
}) {
  // Hook runs unconditionally (before any early return) per CLAUDE.md.
  // useInRouterContext never throws outside a Router — it just returns
  // false, which lets the kit render plain anchors in isolation (tests,
  // storybook-style sandboxes) while getting client-side Links in the app.
  const inRouter = useInRouterContext();

  const href = hrefForRef(entity);
  if (!entity || !href) {
    // An owner value that isn't a real account principal (a system actor, a
    // team/domain label) has no owner-search page — render the NAME as plain
    // text so it still shows, but never as a link to a user who doesn't exist.
    // (Identity integrity: only real account users are clickable owners.)
    if (entity && entity.kind === "owner") {
      const ownerText = String(children ?? entity.label ?? entity.email ?? entity.id ?? "").trim();
      if (ownerText) {
        return (
          <span className={`ax-sys-owner-plain ${className}`.trim()} data-kind="owner">
            {ownerText}
          </span>
        );
      }
    }
    // Unresolvable ref: render nothing rather than a dead link (the
    // "no dead controls" law). Callers keep their raw text fallback.
    return null;
  }

  const kind = entity.kind;
  const label = children ?? entity.label ?? defaultRefLabel(entity);
  const look = appearance === "inline" || appearance === "row" ? appearance : "chip";
  const Anchor = inRouter ? Link : "a";
  const anchorProps = /** @type {any} */ (inRouter ? { to: href } : { href });

  const handleClick = (event) => {
    if (!navigate || event.defaultPrevented || isModifiedClick(event)) return;
    // Adapter owns plain left-click; the href stays live for new-tab/copy.
    event.preventDefault();
    navigate(entity, { href });
  };

  const meta = entity.meta != null ? String(entity.meta) : "";
  const metaEntries =
    entity.meta && typeof entity.meta === "object" && !Array.isArray(entity.meta)
      ? Object.entries(entity.meta)
      : null;

  return (
    <Anchor
      {...anchorProps}
      className={`ax-sys-entity-chip is-${look} is-kind-${kind} ${className}`.trim()}
      data-kind={kind}
      onClick={handleClick}
    >
      <span className="ax-sys-entity-chip-icon" aria-hidden="true">
        {KIND_ICONS[kind] ?? null}
      </span>
      <span className="ax-sys-entity-chip-label">{label}</span>
      {look === "row" && meta && !metaEntries ? (
        <span className="ax-sys-entity-chip-meta">{meta}</span>
      ) : null}
      {withHover ? (
        // CSS-only hover card (shown on :hover / :focus-visible). It is
        // supplementary — aria-hidden so AT reads only the anchor label.
        <span className="ax-sys-entity-hover" role="presentation" aria-hidden="true">
          <span className="ax-sys-entity-hover-kind">{KIND_LABELS[kind] ?? kind}</span>
          <span className="ax-sys-entity-hover-id">
            {entity.fqn ?? entity.email ?? entity.id ?? ""}
          </span>
          {metaEntries
            ? metaEntries.map(([key, value]) => (
                <span key={key} className="ax-sys-entity-hover-row">
                  <span>{key}</span>
                  <span>{String(value)}</span>
                </span>
              ))
            : meta
              ? <span className="ax-sys-entity-hover-row">{meta}</span>
              : null}
        </span>
      ) : null}
    </Anchor>
  );
}

export default EntityChip;
