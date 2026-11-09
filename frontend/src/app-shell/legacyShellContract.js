/*
 * app-shell/legacyShellContract.js — the shell ↔ legacy-surface compatibility
 * contract for Wave B1 (COHESION_BLUEPRINT Wave B1; FRONTEND_BLUEPRINT §9).
 *
 * The new shell emits ONLY clean `ax-shell-*` frame classes (zero legacy
 * prefixes in app-shell code — check-css enforced). Because five legacy
 * stylesheets still key surface-squeeze/sticky rules on the OLD frame class
 * names, those sheets carry selector ALIASES (", .ax-shell-app …") added in
 * Wave B1 so their rules also match the new frame. The alias lists — and the
 * sticky-offset custom-property bridge in shell-rail.css (the legacy
 * header-height var is re-exported from the new `--ax-shell-header-height`
 * the shell measures) — die per-surface in Wave C.
 */

// Window event DiscoveryWorkspace dispatches to open the palette without prop
// drilling (DiscoveryWorkspace.jsx:5963). The name is a legacy event id, not
// a class; it dies in Wave C1 when Discovery calls the shell context instead.
export const LEGACY_OPEN_PALETTE_EVENT = "gh:open-command-palette";

// New frame class vocabulary (single source so the CSS aliases stay
// greppable from one place).
export const SHELL_CLASSNAMES = Object.freeze({
  app: "ax-shell-app",
  header: "ax-shell-header",
  topbar: "ax-shell-topbar",
  main: "ax-shell-main",
  rail: "ax-shell-rail",
  accessBanner: "ax-shell-access-banner",
});

// Sticky-offset var the shell writes from its header measurement. Legacy
// surface CSS reads its old var name via the shell-rail.css bridge rule.
export const SHELL_HEADER_HEIGHT_VAR = "--ax-shell-header-height";
