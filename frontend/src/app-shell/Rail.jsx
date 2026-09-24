/*
 * app-shell/Rail.jsx — the nav rail, generated from the route table (Wave B1).
 *
 * The rail renders what nav/routes.js declares (navSections()) instead of a
 * hard-coded item list — fixing the "Asset 360 nav item defined but never
 * listed" dead-code bug class: a contextual Asset 360 entry appears whenever
 * an asset is in context (asset/lineage route focus or ?peek=), linking to
 * the hub's real /assets/<fqn> address.
 *
 * Items are REAL <a href> anchors (cross-linking law: middle-clickable,
 * copyable), with left-click routed through useAtlasNavigate.
 */

import entradaLogoUrl from "../assets/brand/entrada-logo.png";
import { UserChip } from "../components/primitives/UserChip";
import { navSections } from "../nav/routes.js";
import { refHref } from "../nav/refs.js";
import { useAtlasNavigate } from "../nav/useAtlasNavigate.js";
import { SHELL_CLASSNAMES } from "./legacyShellContract.js";

const Icon = ({ children }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="19"
    height="19"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {children}
  </svg>
);

// Icon vocabulary for nav/routes.js `nav.icon` keys (moved from the deleted
// SideIconRail, plus `help` which the old hard-coded rail never listed).
const RAIL_ICONS = {
  gauge: <Icon><path d="M5 16a7 7 0 1 1 14 0" /><path d="M12 16l4-5" /><path d="M9 19h6" /></Icon>,
  discovery: <Icon><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Icon>,
  asset360: <Icon><path d="m12 3 8 4-8 4-8-4 8-4Z" /><path d="m4 12 8 4 8-4" /><path d="m4 17 8 4 8-4" /></Icon>,
  lineage: <Icon><circle cx="6" cy="6" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="M8 7.5 11 15" /><path d="m16 7.5-3 7.5" /></Icon>,
  listChecks: <Icon><path d="m4 7 1.5 1.5L8.5 5" /><path d="M11 7h9" /><path d="m4 13 1.5 1.5 3-3.5" /><path d="M11 13h9" /><path d="m4 19 1.5 1.5 3-3.5" /><path d="M11 19h9" /></Icon>,
  book: <Icon><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3-3Z" /><path d="M5 4v13" /><path d="M9 8h6" /><path d="M9 12h6" /></Icon>,
  shieldCheck: <Icon><path d="M12 3 5 6v5c0 4.5 3 7.5 7 10 4-2.5 7-5.5 7-10V6l-7-3Z" /><path d="m9 12 2 2 4-5" /></Icon>,
  datapact: <Icon><path d="M12 3 5 6v5c0 4.5 3 7.5 7 10 4-2.5 7-5.5 7-10V6l-7-3Z" /><path d="M9 11.5h6" /><path d="M9 14.5h4" /></Icon>,
  sliders: <Icon><path d="M4 6h10" /><path d="M18 6h2" /><path d="M4 12h2" /><path d="M10 12h10" /><path d="M4 18h8" /><path d="M16 18h4" /><circle cx="16" cy="6" r="2" /><circle cx="8" cy="12" r="2" /><circle cx="14" cy="18" r="2" /></Icon>,
  help: <Icon><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.7 2.7 0 0 1 5 1.4c0 1.8-2.5 2.1-2.5 4" /><path d="M12 17.5h.01" /></Icon>,
  sparkles: <Icon><path d="M12 4 13.8 9 19 10.8 13.8 12.6 12 18l-1.8-5.4L5 10.8 10.2 9Z" /><path d="M19 3v4" /><path d="M17 5h4" /></Icon>,
};

function roleSlug(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

// Same admin gate AdminWorkspace enforces on its content (AdminWorkspace.jsx
// adminRoleAllowed) — the rail hides the entry instead of advertising a
// surface that will render "requires platform admin permissions".
export function adminRailAllowed(shell) {
  if (!shell) return true;
  const email = roleSlug(shell.userEmail || shell.actorEmail);
  if (!email || email === "unknown") return false;
  const role = roleSlug(shell.role || shell.actorRole);
  if (!role) return Boolean(shell.roleProvisional);
  return role.includes("admin");
}

// Feature gate for surfaces the backend registers conditionally. The AI
// governance entry shows only when bootstrap reports the flag on, so the rail
// never advertises a surface whose API is not mounted.
export function railGateAllowed(gate, shell) {
  if (!gate) return true;
  if (gate === "admin") return adminRailAllowed(shell);
  if (gate === "aiGovernance") return Boolean(shell?.aiGovernance?.enabled);
  return false;
}

function isModifiedClick(event) {
  return event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
}

function badgeLabel(value) {
  return value > 999 ? "999+" : String(value);
}

// Build the PERMANENT "Asset 360" rail entry (owner directive 1: no longer
// hidden by default). Target precedence: the asset in context (route focus or
// ?peek=) → the last record you opened (prefs) → the search-first /assets
// picker. The tooltip names the behavior so the entry is never a mystery door.
function asset360Item({ contextAssetFqn, lastAssetFqn }) {
  const base = {
    key: "asset360",
    surface: "assets",
    label: "Asset 360",
    icon: "asset360",
  };
  if (contextAssetFqn) {
    return {
      ...base,
      entityRef: { kind: "asset", fqn: contextAssetFqn },
      title: `Asset 360 — ${contextAssetFqn}`,
    };
  }
  if (lastAssetFqn) {
    return {
      ...base,
      entityRef: { kind: "asset", fqn: lastAssetFqn },
      title: `Asset 360 — reopen last viewed: ${lastAssetFqn}`,
    };
  }
  // No context and nothing remembered: the picker (a surfaceRef, resolved to
  // bare /assets by nav/refs.js).
  return { ...base, params: {}, title: "Asset 360 — pick an asset to open its full record" };
}

export function Rail({
  activeSurface = "",
  contextAssetFqn = "",
  // Last opened Asset 360 record (prefs.lastAssetFqn) — the rail entry's
  // no-context target so the permanent entry is never a dead end.
  lastAssetFqn = "",
  // My-work badge (nav.badgeKey "myWork"): null while its sources load —
  // a definitive 0 during hydration is the bug class the cohesion laws ban.
  myWorkBadgeCount = null,
  shell = null,
  shellDisabled = false,
  shellDisabledReason = "",
  onOpenSettings,
  onOpenCapabilities,
  onSignOut,
}) {
  const navigate = useAtlasNavigate();

  const renderItem = (item) => {
    const target = item.entityRef || { surface: item.surface, params: item.params || {} };
    const href = refHref(target);
    const active = item.activeOverride ?? (activeSurface === item.surface);
    const badgeValue =
      item.badgeKey === "myWork" && Number.isFinite(Number(myWorkBadgeCount))
        ? Math.max(0, Math.trunc(Number(myWorkBadgeCount)))
        : null;
    return (
      <a
        aria-current={active ? "page" : undefined}
        aria-disabled={shellDisabled ? "true" : undefined}
        className={`ga-side-nav-item ga-shell-nav-item ${active ? "is-active" : ""}`.trim()}
        href={href}
        key={item.key || item.surface}
        onClick={(event) => {
          if (isModifiedClick(event)) return; // keep native new-tab semantics
          event.preventDefault();
          if (shellDisabled) return;
          navigate(target);
        }}
        title={shellDisabled && shellDisabledReason ? shellDisabledReason : item.title || item.label}
      >
        <span className="ga-side-nav-icon">{RAIL_ICONS[item.icon] || RAIL_ICONS.gauge}</span>
        <span>{item.label}</span>
        {badgeValue > 0 ? <span className="ga-side-nav-badge">{badgeLabel(badgeValue)}</span> : null}
      </a>
    );
  };

  const sections = navSections()
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => railGateAllowed(item.gate, shell)),
    }))
    .filter((section) => section.items.length > 0);

  return (
    <aside
      aria-label="Governance Atlas navigation"
      className={`ga-side-nav ${SHELL_CLASSNAMES.rail}`}
    >
      <div className="ga-side-nav-logo">
        <img src={entradaLogoUrl} alt="Entrada" />
        <span>
          <strong>Governance Atlas</strong>
          <em>By Entrada</em>
        </span>
      </div>
      <nav aria-label="Primary modules" className="ga-side-nav-items">
        {sections.map((section) => (
          <div className="ga-side-nav-section" key={section.id}>
            {section.label ? (
              <div className="ga-side-nav-section-title">{section.label}</div>
            ) : (
              <div aria-hidden="true" className="ga-side-nav-section-title ga-shell-nav-divider" />
            )}
            {section.items.map((item) => renderItem(item))}
            {/* PERMANENT Asset 360 entry (owner directive 1): routes.js
                declares both /assets routes with nav:null, so the rail owns
                this GOVERN entry. It is ALWAYS shown; its target adapts to the
                asset in context, the last opened record, or the picker. */}
            {section.id === "govern"
              ? renderItem({
                  ...asset360Item({ contextAssetFqn, lastAssetFqn }),
                  activeOverride: activeSurface === "assets",
                })
              : null}
          </div>
        ))}
      </nav>
      <div className="ga-side-nav-user">
        <UserChip
          userEmail={shell?.userEmail || ""}
          userName={shell?.userName || shell?.displayName || shell?.userEmail || ""}
          role={shell?.role || ""}
          roleProvisional={Boolean(shell?.roleProvisional)}
          onOpenSettings={onOpenSettings}
          onOpenCapabilities={onOpenCapabilities}
          onSignOut={onSignOut}
          variant="sidebar"
        />
      </div>
    </aside>
  );
}

export default Rail;
