/**
 * nav/useAxiomNavigate.js — THE navigation API (Wave A3).
 *
 * `navigate(ref, options)` is the only sanctioned way to move between surfaces
 * once Wave B lands. It replaces (FRONTEND_BLUEPRINT §8 kill table):
 *   - the ~16 drilled navigation callbacks wired through App.jsx,
 *   - sessionStorage handoffs (ax-pending-glossary-term, ax-insights-focus,
 *     workspaceIntent) — a ref works whether or not the target is mounted,
 *   - custom window events (ax:select-glossary-term, ...),
 *   - `location.state.fresh` (replaced by the explicit `push` option),
 *   - raw window.history.replaceState bypasses.
 *
 * Options:
 *   params   extra query params merged over the ref's own (typed via the target
 *            route's paramsSchema).
 *   replace  replace the current history entry (default false — cross-surface
 *            navigation pushes so Back always works).
 *   push     force a history push. Wins over `replace`. This is the explicit
 *            spelling of the old `location.state.fresh` "fresh opening" flag.
 *   peek     open the ref in the Asset 360 drawer on the CURRENT surface by
 *            binding ?peek=<fqn> instead of leaving the page.
 */

import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { resolveRef } from "./refs.js";
import { routeForPathname, serializeSearch, writeParams } from "./routes.js";

export function useAxiomNavigate() {
  const routerNavigate = useNavigate();
  const location = useLocation();

  return useCallback(
    (ref, options = {}) => {
      const { params: extraParams = null, replace = false, push, peek = false } = options;

      if (peek) {
        const fqn = peekFqnFromRef(ref);
        if (fqn) {
          const sp = new URLSearchParams(location.search);
          sp.set("peek", fqn);
          // WHY push by default: opening the drawer is a "fresh opening" —
          // Back should close the drawer, not leave the surface.
          routerNavigate(
            { pathname: location.pathname, search: searchString(sp) },
            { replace: push === true ? false : replace },
          );
          return;
        }
        // Refs without an asset FQN have no drawer form — fall through to a
        // full navigation rather than dead-clicking (never a dead control).
      }

      const { path, params } = resolveRef(ref);
      const route = routeForPathname(path);
      const merged = { ...params, ...(extraParams || {}) };
      const search = serializeSearch(route?.paramsSchema || {}, merged);
      routerNavigate(
        { pathname: path, search },
        { replace: push === true ? false : replace },
      );
    },
    [routerNavigate, location.pathname, location.search],
  );
}

/**
 * usePeek — the Asset 360 drawer binding (?peek=<fqn>), addressable and
 * shareable. `open` accepts an asset FQN string or any ref carrying one.
 */
export function usePeek() {
  const routerNavigate = useNavigate();
  const location = useLocation();

  const peekFqn = useMemo(
    () => new URLSearchParams(location.search).get("peek") || "",
    [location.search],
  );

  const openPeek = useCallback(
    (refOrFqn, { push = true } = {}) => {
      const fqn = peekFqnFromRef(refOrFqn);
      if (!fqn) return;
      const sp = writeParams({ peek: { type: "string" } }, new URLSearchParams(location.search), {
        peek: fqn,
      });
      routerNavigate(
        { pathname: location.pathname, search: searchString(sp) },
        // Push by default so Back closes the drawer (see useAxiomNavigate).
        { replace: !push },
      );
    },
    [routerNavigate, location.pathname, location.search],
  );

  const closePeek = useCallback(() => {
    const sp = new URLSearchParams(location.search);
    if (!sp.has("peek")) return;
    sp.delete("peek");
    // Closing is sub-state cleanup: replace, don't grow history.
    routerNavigate({ pathname: location.pathname, search: searchString(sp) }, { replace: true });
  }, [routerNavigate, location.pathname, location.search]);

  return { peekFqn, openPeek, closePeek };
}

function peekFqnFromRef(refOrFqn) {
  if (typeof refOrFqn === "string") return refOrFqn;
  if (refOrFqn && typeof refOrFqn === "object" && refOrFqn.fqn) return String(refOrFqn.fqn);
  return "";
}

function searchString(searchParams) {
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}
