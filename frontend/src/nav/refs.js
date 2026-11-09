/**
 * nav/refs.js — the entity/surface ref model + resolver (Wave A3).
 *
 * Implements the cross-linking contract (COHESION_BLUEPRINT "LAW" section):
 * any mention of one of these entity kinds, anywhere in the product, resolves
 * through resolveRef() to its ONE canonical route. EntityChip, StatTile.target,
 * DataTable.rowTarget, the command palette, and the rail all route through here
 * (Wave B+) — no surface builds entity URLs by hand.
 *
 * Ref shapes:
 *   entityRef  — where a THING lives:
 *     { kind: "asset",           fqn }
 *     { kind: "column",          fqn, column }
 *     { kind: "term",            id }
 *     { kind: "cde",             id }
 *     { kind: "owner",           id }            // email or display name
 *     { kind: "request",         id }            // work item, GOV-<hex8>
 *     { kind: "event",           id }            // audit event, AUD-<hex8>
 *     { kind: "quality-finding", asset, run }
 *     { kind: "catalog",         name }
 *     { kind: "domain",          name }
 *     { kind: "lineage",         fqn }
 *   surfaceRef — where a SURFACE lives:
 *     { surface: "discovery", params: { q, filters, ... } }
 *     (path params — fqn/termId — may ride in `params` and fill the path.)
 *
 * resolveRef(ref) → { path, params } with RAW param values (objects for json
 * params); serialization to the wire happens against the route's paramsSchema
 * (refHref / useAxiomNavigate).
 */

import { matchPattern, routesForSurface, routeForPathname, serializeSearch } from "./routes.js";

/** Encode an asset FQN for use as a single path segment-run. */
function encodeFqn(fqn) {
  // encodeURIComponent also encodes "/" so an exotic FQN can never change the
  // route shape; matchPattern decodes on the way back in.
  return encodeURIComponent(String(fqn));
}

function required(ref, field) {
  const value = ref[field];
  if (value === undefined || value === null || `${value}` === "") {
    throw new Error(`nav/refs: ref kind "${ref.kind}" requires "${field}"`);
  }
  return value;
}

/**
 * Resolve an entityRef or surfaceRef to `{ path, params }`.
 * One route per entity kind — this switch IS the cross-linking contract.
 */
export function resolveRef(ref) {
  if (!ref || typeof ref !== "object") {
    throw new Error("nav/refs: resolveRef requires an entityRef or surfaceRef object");
  }

  if (ref.surface) return resolveSurfaceRef(ref);

  switch (ref.kind) {
    case "asset":
      return { path: `/assets/${encodeFqn(required(ref, "fqn"))}`, params: {} };

    case "column":
      // Columns tab scrolls to + highlights the row (?tab=columns&col=).
      return {
        path: `/assets/${encodeFqn(required(ref, "fqn"))}`,
        params: { tab: "columns", col: required(ref, "column") },
      };

    case "term":
      return { path: `/glossary/${encodeURIComponent(required(ref, "id"))}`, params: {} };

    case "cde":
      // CDE chips link to the focused CDE, not the generic tab.
      return { path: "/glossary", params: { tab: "cdes", cde: required(ref, "id") } };

    case "owner":
      // The ONE owner-search grammar: /discovery?q=owner:"<name-or-email>".
      // Every rendered email/name — audit actors, lineage rail owners, comment
      // authors, preview owners — is this link.
      return { path: "/discovery", params: { q: `owner:"${required(ref, "id")}"` } };

    case "request":
      // Work item → the queue with the detail pane focused. COHESION law uses
      // ?item=GOV-<hex8> (supersedes the frontend blueprint's ?request= draft).
      return { path: "/stewardship", params: { item: required(ref, "id") } };

    case "event":
      // Audit event → Evidence (the /audit spelling is only a redirect alias).
      return { path: "/evidence", params: { event: required(ref, "id") } };

    case "quality":
    case "quality-finding":
      // Command Center risk rows, hub Quality tab, and heatmap cells all land
      // on the same Evidence quality tab, scoped to the asset + run.
      return {
        path: "/evidence",
        params: { tab: "quality", asset: required(ref, "asset"), run: required(ref, "run") },
      };

    case "catalog":
      // Catalog-health rows → Discovery pre-filtered (existing ?filters= JSON contract).
      return {
        path: "/discovery",
        params: { filters: { catalogs: [ref.name ?? required(ref, "id")] } },
      };

    case "domain":
      // The domain LABEL is the anchor, not just the row.
      return {
        path: "/discovery",
        params: { filters: { domains: [ref.name ?? required(ref, "id")] } },
      };

    case "lineage":
      // Never a bare /lineage link from an asset context (context-drop bug class).
      return { path: `/lineage/${encodeFqn(required(ref, "fqn"))}`, params: {} };

    default:
      throw new Error(`nav/refs: unknown entityRef kind "${ref.kind}"`);
  }
}

function resolveSurfaceRef(ref) {
  const routes = routesForSurface(ref.surface);
  if (!routes.length) {
    throw new Error(`nav/refs: unknown surface "${ref.surface}"`);
  }
  const params = { ...(ref.params || {}) };

  // Prefer the route whose terminal path param is satisfied by `params`
  // (e.g. {surface:"lineage", params:{fqn}} → /lineage/<fqn>); otherwise the
  // bare route. Path params are consumed out of the query params.
  for (const route of routes) {
    const paramName = terminalParamName(route.path);
    if (paramName && params[paramName]) {
      const value = params[paramName];
      delete params[paramName];
      return { path: route.path.replace(`:${paramName}`, encodeFqn(value)), params };
    }
  }
  const bare = routes.find((route) => !terminalParamName(route.path));
  if (!bare) {
    throw new Error(
      `nav/refs: surface "${ref.surface}" needs a path param (e.g. fqn) in ref.params`,
    );
  }
  return { path: bare.path, params };
}

function terminalParamName(pattern) {
  const match = /:([A-Za-z0-9_]+)$/u.exec(pattern);
  return match ? match[1] : null;
}

/**
 * Full href for a ref — for the REAL `<a href>` the cross-linking law demands
 * (middle-click, copy-link, a11y). Serializes params against the target route's
 * schema so json/array params hit the wire in their contract encoding.
 */
export function refHref(ref, extraParams) {
  const { path, params } = resolveRef(ref);
  const route = routeForPathname(path);
  const merged = { ...params, ...(extraParams || {}) };
  return `${path}${serializeSearch(route?.paramsSchema || {}, merged)}`;
}

/** True when a pathname is (or aliases to) the route a ref resolves to. */
export function refMatchesPathname(ref, pathname) {
  const { path } = resolveRef(ref);
  const route = routeForPathname(path);
  return Boolean(route && matchPattern(route.path, pathname));
}
