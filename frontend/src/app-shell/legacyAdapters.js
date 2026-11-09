/*
 * app-shell/legacyAdapters.js — Wave B1 bridge between the nav fabric and the
 * legacy surfaces' drilled callback props, now shrunk to its last living
 * consumers (Wave C8): every rebuilt surface is router-self-sufficient, so
 * the per-entity adapters (onOpenAsset/onOpenLineage/onOpenGovernance/
 * onOpenGlossaryTerm/onOpenDiscoveryWithFilter and the workspaceIntent
 * sessionStorage staging) are gone. What remains is the module-key → surface
 * ref map used by shell chrome (setup wizard capabilities link) and the
 * discovery opener that carries the `location.state.fresh` flag.
 */

import { useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";

import { refHref } from "../nav/refs.js";
import { useAxiomNavigate } from "../nav/useAxiomNavigate.js";

// Legacy module keys (SideIconRail/HomePage/AdminWorkspace vocabulary) → nav
// fabric surface refs, honoring the COHESION_BLUEPRINT absorptions: inbox →
// stewardship?assignee=me, cde → glossary?tab=cdes, capabilities →
// admin?tab=diagnostics, insights → home.
export const LEGACY_MODULE_TARGETS = Object.freeze({
  home: { surface: "home" },
  discovery: { surface: "discovery" },
  lineage: { surface: "lineage" },
  governance: { surface: "stewardship" },
  stewardship: { surface: "stewardship" },
  inbox: { surface: "stewardship", params: { assignee: "me" } },
  audit: { surface: "evidence" },
  evidence: { surface: "evidence" },
  taxonomy: { surface: "glossary" },
  glossary: { surface: "glossary" },
  cde: { surface: "glossary", params: { tab: "cdes" } },
  admin: { surface: "admin" },
  capabilities: { surface: "admin", params: { tab: "diagnostics" } },
  insights: { surface: "home" },
  help: { surface: "help" },
});

export function useLegacyNavAdapters() {
  const navigate = useAxiomNavigate();
  const routerNavigate = useNavigate();

  // Discovery opens ride the router directly (not useAxiomNavigate) because
  // the legacy `location.state.fresh` flag must travel with the entry.
  const openDiscovery = useCallback(
    (params = {}, { fresh = true, replace = false } = {}) => {
      routerNavigate(refHref({ surface: "discovery", params }), {
        replace,
        state: { fresh: Boolean(fresh) },
      });
    },
    [routerNavigate],
  );

  const onNavigate = useCallback(
    (moduleKey) => {
      const target = LEGACY_MODULE_TARGETS[String(moduleKey || "").trim()];
      if (!target) return;
      if (target.surface === "discovery") {
        openDiscovery(target.params || {}, { fresh: true });
        return;
      }
      navigate(target);
    },
    [navigate, openDiscovery],
  );

  return useMemo(
    () => ({
      onNavigate,
      openDiscovery,
      navigate,
    }),
    [navigate, onNavigate, openDiscovery],
  );
}

export default useLegacyNavAdapters;
