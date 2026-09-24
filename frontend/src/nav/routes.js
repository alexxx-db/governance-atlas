/**
 * nav/routes.js — THE route table for Governance Atlas (Wave A3, COHESION_BLUEPRINT).
 *
 * Single source of truth for the surface map: canonical routes, redirect aliases,
 * nav-rail metadata, and per-surface URL param schemas. Consumed (Wave B+) by:
 *   (a) the <Routes> tree in AppShell,
 *   (b) the nav rail (sections/labels/badges generated from `nav` metadata —
 *       fixing the "Asset 360 defined but never listed" dead-code bug),
 *   (c) navigate(entityRef|surfaceRef) resolution (nav/refs.js),
 *   (d) the command palette.
 *
 * NOTHING outside frontend/src/nav/ may import this module until Wave B (the
 * AppShell rewrite). The legacy useAppRouteState.js remains authoritative for the
 * running app until then.
 *
 * Framework-free on purpose: no React, no react-router imports. The hooks in
 * useAtlasNavigate.js / useSurfaceParams.js bind this table to react-router.
 */

/* ------------------------------------------------------------------ */
/* Param schema types                                                   */
/* ------------------------------------------------------------------ */

// Shorthand helpers so the table below stays readable.
const str = (def) => ({ type: "string", ...(def === undefined ? {} : { default: def }) });
const arr = () => ({ type: "array" });
const json = (def) => ({ type: "json", ...(def === undefined ? {} : { default: def }) });
const bool = (def) => ({ type: "bool", ...(def === undefined ? {} : { default: def }) });

// `?peek=<fqn>` is the Asset 360 drawer binding — addressable and shareable from
// ANY surface (COHESION: "drawer preview binds ?peek=<fqn>"), so every surface
// schema carries it.
const PEEK = { peek: str() };

/* ------------------------------------------------------------------ */
/* Nav sections (PRODUCT_BLUEPRINT §5)                                  */
/* ------------------------------------------------------------------ */

export const NAV_SECTION_ORDER = ["govern", "knowledge", "profile"];

export const NAV_SECTION_LABELS = {
  govern: "Govern",
  // "Knowledge & Proof" per PRODUCT_BLUEPRINT §5 rail sketch.
  knowledge: "Knowledge & Proof",
  // The profile cluster renders below the divider with no heading.
  profile: "",
};

/* ------------------------------------------------------------------ */
/* The table                                                            */
/* ------------------------------------------------------------------ */

/**
 * Entry shape:
 *   surface       stable surface id
 *   path          canonical path pattern. `:name` params are TERMINAL and greedy:
 *                 they consume the rest of the path (FQNs historically arrive
 *                 with extra "/" segments; the legacy parser joined them, we
 *                 preserve that tolerance).
 *   aliases[]     legacy paths that 301 to this route. String form forwards all
 *                 query params untouched; object form {from, params} also seeds
 *                 params (see resolveUrl for merge semantics). `*` in `from`
 *                 captures the remainder and fills the canonical path param.
 *   nav           {section, label, icon, badgeKey?} — rail metadata; null = not
 *                 a rail item (hubs/detail routes).
 *   paramsSchema  typed URL params for useSurfaceParams.
 *   gate          "admin" = surface is admin-gated (rail + route guard, Wave B).
 *   normalize     optional (searchParams) => {path}|null hook for canonical-form
 *                 rewrites that need more than static alias mapping.
 */
export const ROUTES = [
  {
    surface: "home",
    path: "/home",
    // WHY these redirects: "/" has always defaulted to home; /command-center and
    // /exec are historical spellings of the same surface; /insights is ABSORBED
    // by Command Center (COHESION: its three backed widgets move here), so old
    // insights deep links — including ?focus=risk handoffs that used to travel
    // via sessionStorage — land on /home with their params forwarded.
    aliases: ["/", "/command-center", "/exec", "/insights"],
    nav: { section: "govern", label: "Command Center", icon: "gauge" },
    paramsSchema: { focus: str(), ...PEEK },
  },
  {
    surface: "discovery",
    path: "/discovery",
    // WHY: /discover is the long-standing short alias (useAppRouteState.js:89).
    aliases: ["/discover"],
    nav: { section: "govern", label: "Discover", icon: "discovery" },
    paramsSchema: {
      q: str(),
      sort: str(),
      view: str(),
      // ?filters= carries the JSON facet payload (existing contract, kept).
      filters: json(),
      // Repeatable facet shortcuts per FRONTEND_BLUEPRINT §8 URL conventions.
      domain: arr(),
      tier: arr(),
      owner: str(),
      ...PEEK,
    },
  },
  {
    surface: "assets",
    path: "/assets/:fqn",
    // WHY: the hub finally gets a stable plural address. /entity/* is the legacy
    // spelling (useAppRouteState.js:95); /asset/* appears in the product
    // blueprint's earlier draft and in shared links — both must keep working
    // forever (COHESION alias column: "/asset/*, /entity/*").
    aliases: ["/entity/*", "/asset/*"],
    // nav: null is deliberate — the DETAIL route is not itself a rail
    // destination. The rail's PERMANENT "Asset 360" entry (owner directive:
    // Asset 360 is no longer hidden) targets this route when an asset is in
    // context, and the bare /assets picker below otherwise.
    nav: null,
    paramsSchema: {
      tab: str(),
      // ?tab=columns&col=<name> scrolls to + highlights the column row
      // (cross-linking contract, column entity kind).
      col: str(),
      ...PEEK,
    },
  },
  {
    surface: "assets",
    path: "/assets",
    // Bare /assets is the search-first Asset 360 picker (owner directive:
    // "Asset 360 is still hidden by default — make it visible"). The permanent
    // rail entry lands here whenever no asset is in context or remembered, so
    // the entry is never a dead end. Mirrors the bare /lineage picker pattern.
    // Declared AFTER /assets/:fqn so the greedy detail route wins for any path
    // that carries an FQN segment; matchPattern only lands here for the exact
    // bare path.
    aliases: [],
    nav: null,
    paramsSchema: { q: str(), ...PEEK },
  },
  {
    surface: "stewardship",
    path: "/stewardship",
    // WHY: /governance and /sk are historical ids for the same queue. /inbox is
    // KILLED as a destination (InboxPage dies; the bell becomes a popover), so
    // its deep links land on the queue pre-filtered to the user's own work —
    // "?assignee=me" preserves the inbox's semantics, not just its URL.
    aliases: ["/governance", "/sk", { from: "/inbox", params: { assignee: "me" } }],
    nav: {
      section: "govern",
      label: "Stewardship",
      icon: "listChecks",
      // Audit B1: badge = actionable stewardship WORK across the estate
      // (open change requests + glossary term reviews) plus unread
      // notifications — it is NOT assignee-filtered and is a broader
      // population than the Command Center "Open change requests" KPI.
      badgeKey: "myWork",
    },
    paramsSchema: {
      assignee: str(),
      // ?item=GOV-<hex8> focuses the item detail pane (COHESION law; supersedes
      // the frontend blueprint's earlier `?request=` draft).
      item: str(),
      asset: str(),
      // "One queue, two lenses."
      lens: str(),
      ...PEEK,
    },
  },
  {
    surface: "datapact",
    path: "/datapact",
    // WHY: /data-pact and /data-quality are the natural spellings; the Control
    // Center is where DataPact validation results live inside Atlas.
    aliases: ["/data-pact", "/data-quality", "/quality-gate"],
    nav: { section: "govern", label: "DataPact", icon: "datapact" },
    paramsSchema: {
      // overview | jobs | ask | dashboard
      tab: str(),
      // ?run=<runId> opens the run-detail drawer (addressable + shareable).
      run: str(),
      // ?job=<normalizedJobName> focuses a job in the Jobs tab.
      job: str(),
      ...PEEK,
    },
  },
  {
    surface: "ai",
    path: "/ai/assets/:entityId",
    // AI Asset 360 (docs/ai_extension/DESIGN.md 10). Detail route: not a rail
    // destination; declared before the bare /ai route like /assets/:fqn.
    aliases: [],
    nav: null,
    gate: "aiGovernance",
    paramsSchema: { tab: str(), ...PEEK },
  },
  {
    surface: "ai",
    path: "/ai",
    // gate "aiGovernance": the rail entry and route exist only when the
    // backend registered /api/ai (bootstrap shell.aiGovernance.enabled).
    aliases: ["/ai-governance"],
    nav: { section: "govern", label: "AI Governance", icon: "sparkles" },
    gate: "aiGovernance",
    paramsSchema: {
      // inventory | findings | intake
      tab: str(),
      kind: str(),
      state: str(),
      provider: str(),
      q: str(),
      severity: str(),
      findingState: str(),
      // ?finding=<id> opens the finding evidence drawer.
      finding: str(),
      ...PEEK,
    },
  },
  {
    surface: "glossary",
    path: "/glossary/:termId",
    // Term detail is path-addressable (COHESION: "/glossary/<termId>"). Listed
    // before the bare route only for reading order; matching is length-exact.
    aliases: [],
    nav: null,
    paramsSchema: { tab: str(), ...PEEK },
  },
  {
    surface: "glossary",
    path: "/glossary",
    // WHY: /taxonomy is the legacy surface id; /glossary-cdes and
    // /glossary-and-cdes are old marketing spellings the legacy parser accepted
    // (useAppRouteState.js:124). /cde and /cdes were a SEPARATE surface that is
    // now a tab — the alias seeds ?tab=cdes so old links land on the right tab.
    aliases: [
      "/taxonomy",
      "/glossary-cdes",
      "/glossary-and-cdes",
      { from: "/cde", params: { tab: "cdes" } },
      { from: "/cdes", params: { tab: "cdes" } },
    ],
    nav: { section: "knowledge", label: "Glossary & CDEs", icon: "book" },
    paramsSchema: {
      tab: str(),
      // ?cde=<id> focuses a CDE inside ?tab=cdes (cross-linking contract).
      cde: str(),
      q: str(),
      status: str(),
      ...PEEK,
    },
    // WHY this normalize hook: legacy deep links carried a TRANSIENT ?term=
    // that TaxonomyWorkspace consumed and deleted via raw
    // window.history.replaceState (TaxonomyWorkspace.jsx:697) — the link died
    // after first use. The canonical form is the durable path /glossary/<id>,
    // so any ?term= arriving on the bare glossary route (via /taxonomy or
    // /glossary itself) is promoted to the path and survives refresh/share.
    normalize: (searchParams) => {
      const term = searchParams.get("term");
      if (!term) return null;
      searchParams.delete("term");
      return { path: `/glossary/${encodeURIComponent(term)}` };
    },
  },
  {
    surface: "lineage",
    path: "/lineage/:fqn",
    // WHY: /lineage-atlas is the legacy alias; the wildcard keeps focus-asset
    // deep links alive.
    aliases: ["/lineage-atlas/*"],
    nav: null,
    paramsSchema: {
      // Data Lineage vs Operational Context — was sessionStorage workspaceIntent,
      // now addressable (FRONTEND §8 kill table).
      context: str(),
      ...PEEK,
    },
  },
  {
    surface: "lineage",
    path: "/lineage",
    // Bare /lineage is the search-first asset picker (kills the jargon landing).
    aliases: ["/lineage-atlas"],
    nav: { section: "knowledge", label: "Lineage Atlas", icon: "lineage" },
    paramsSchema: { q: str(), ...PEEK },
  },
  {
    surface: "evidence",
    path: "/evidence",
    // WHY: Audit Evidence is renamed Evidence — it now carries quality findings
    // too (?tab=quality). Both legacy audit spellings redirect; params (e.g.
    // ?event=AUD-…) forward untouched so shared audit links keep working.
    aliases: ["/audit", "/audit-evidence"],
    nav: { section: "knowledge", label: "Evidence", icon: "shieldCheck" },
    paramsSchema: {
      tab: str(),
      // ?event=AUD-<hex8> — stable audit event id (cross-linking contract).
      event: str(),
      // Quality-finding drill params: ?tab=quality&asset=<fqn>&run=<runId>.
      asset: str(),
      run: str(),
      kind: str(),
      ...PEEK,
    },
  },
  {
    surface: "admin",
    path: "/admin",
    // WHY: /control-center is the legacy name. /capabilities was a separate
    // diagnostics surface now folded into Control Center as a tab — the alias
    // seeds ?tab=diagnostics so capability deep links land on the right tab.
    aliases: ["/control-center", { from: "/capabilities", params: { tab: "diagnostics" } }],
    // Demoted to the profile cluster: runtime ops is not a governance claim.
    nav: { section: "profile", label: "Control Center", icon: "sliders" },
    gate: "admin",
    paramsSchema: { tab: str(), ...PEEK },
  },
  {
    surface: "help",
    path: "/help",
    aliases: [],
    nav: { section: "profile", label: "Help", icon: "help" },
    paramsSchema: {},
  },
];

/* ------------------------------------------------------------------ */
/* Derived views of the table                                           */
/* ------------------------------------------------------------------ */

/** Rail model: ordered sections, each with its routes (nav metadata present). */
export function navSections() {
  return NAV_SECTION_ORDER.map((id) => ({
    id,
    label: NAV_SECTION_LABELS[id],
    items: ROUTES.filter((route) => route.nav && route.nav.section === id).map((route) => ({
      surface: route.surface,
      path: route.path,
      gate: route.gate || null,
      ...route.nav,
    })),
  })).filter((section) => section.items.length > 0);
}

/** All routes for a surface id (detail routes first if declared first). */
export function routesForSurface(surface) {
  return ROUTES.filter((route) => route.surface === surface);
}

/** The route entry whose canonical pattern matches a CONCRETE pathname. */
export function routeForPathname(pathname) {
  for (const route of ROUTES) {
    if (matchPattern(route.path, pathname)) return route;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Path matching                                                        */
/* ------------------------------------------------------------------ */

function splitPath(pathname) {
  return String(pathname || "/")
    .split("/")
    .filter(Boolean);
}

function safeDecode(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Match a pattern ("/assets/:fqn", "/entity/*", "/home") against a pathname.
 * Returns {params} or null. `:name` and `*` are terminal + greedy and require
 * at least one segment (a bare "/entity" is NOT an asset link — it falls
 * through to not-found handling, matching the legacy parser's behavior).
 */
export function matchPattern(pattern, pathname) {
  const pat = splitPath(pattern);
  const segs = splitPath(pathname);
  const params = {};
  for (let i = 0; i < pat.length; i += 1) {
    const token = pat[i];
    if (token.startsWith(":")) {
      const rest = segs.slice(i);
      if (!rest.length) return null;
      params[token.slice(1)] = safeDecode(rest.join("/"));
      return params;
    }
    if (token === "*") {
      const rest = segs.slice(i);
      if (!rest.length) return null;
      // Splat stays ENCODED — it is re-emitted into the canonical path.
      params["*"] = rest.join("/");
      return params;
    }
    if (segs[i] !== token) return null;
  }
  return segs.length === pat.length ? params : null;
}

/** Fill a canonical pattern's terminal param with a (still-encoded) splat. */
function fillPattern(pattern, splat) {
  return pattern.replace(/:[A-Za-z0-9_]+$/u, splat);
}

/* ------------------------------------------------------------------ */
/* URL resolution (aliases → canonical)                                 */
/* ------------------------------------------------------------------ */

function normalizeAlias(alias) {
  return typeof alias === "string" ? { from: alias, params: null } : alias;
}

/**
 * Resolve any app URL (canonical or legacy) to its canonical form.
 *
 * @param {string} input  pathname, or pathname?search, or absolute URL.
 * @returns {null | {
 *   surface: string,
 *   route: object,
 *   pathname: string,        // canonical pathname
 *   search: string,          // canonical search ("" or "?...")
 *   pathParams: object,      // decoded path params ({fqn} / {termId})
 *   redirected: boolean,     // true when input was an alias / non-canonical form
 * }}
 *
 * Merge semantics for alias-seeded params: incoming query params are ALWAYS
 * forwarded verbatim; alias params fill in only when the key is absent. WHY:
 * the alias expresses the legacy surface's default semantics (e.g. /inbox means
 * "my work"), but an explicit param in the shared link is user intent and wins.
 */
export function resolveUrl(input, _depth = 0) {
  const url = new URL(String(input || "/"), "https://atlas.invalid");
  const pathname = url.pathname;
  const incoming = url.searchParams;

  // Guard against a normalize/alias cycle ever being introduced in the table.
  if (_depth > 4) return null;

  // 1. Canonical match (may still normalize, e.g. /glossary?term= → /glossary/<id>).
  for (const route of ROUTES) {
    const params = matchPattern(route.path, pathname);
    if (!params) continue;
    if (route.normalize) {
      const rewritten = route.normalize(incoming);
      if (rewritten) {
        const next = resolveUrl(`${rewritten.path}${searchString(incoming)}`, _depth + 1);
        return next ? { ...next, redirected: true } : null;
      }
    }
    return {
      surface: route.surface,
      route,
      pathname,
      search: searchString(incoming),
      pathParams: params,
      redirected: false,
    };
  }

  // 2. Alias match → rebuild as canonical and re-resolve (so normalize hooks and
  //    param seeding compose, e.g. /taxonomy?term=x → /glossary?term=x → /glossary/x).
  for (const route of ROUTES) {
    for (const rawAlias of route.aliases || []) {
      const alias = normalizeAlias(rawAlias);
      const matched = matchPattern(alias.from, pathname);
      if (!matched) continue;
      const target =
        matched["*"] !== undefined ? fillPattern(route.path, matched["*"]) : route.path;
      const merged = new URLSearchParams(incoming);
      for (const [key, value] of Object.entries(alias.params || {})) {
        if (!merged.has(key)) merged.set(key, value);
      }
      const next = resolveUrl(`${target}${searchString(merged)}`, _depth + 1);
      return next ? { ...next, redirected: true } : null;
    }
  }

  return null;
}

function searchString(searchParams) {
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

/* ------------------------------------------------------------------ */
/* Typed param (de)serialization — shared by useSurfaceParams and refs  */
/* ------------------------------------------------------------------ */

export function normalizeSchema(schema) {
  const out = {};
  for (const [key, spec] of Object.entries(schema || {})) {
    out[key] = typeof spec === "string" ? { type: spec } : spec;
  }
  return out;
}

const TRUE_TOKENS = new Set(["1", "true", "yes", "on"]);
const FALSE_TOKENS = new Set(["0", "false", "no", "off"]);

function parseValue(spec, searchParams, key) {
  switch (spec.type) {
    case "array": {
      const all = searchParams.getAll(key);
      return all.length ? all : (spec.default ?? []);
    }
    case "bool": {
      const raw = searchParams.get(key);
      if (raw === null) return spec.default ?? false;
      const token = raw.trim().toLowerCase();
      if (TRUE_TOKENS.has(token)) return true;
      if (FALSE_TOKENS.has(token)) return false;
      return spec.default ?? false;
    }
    case "json": {
      const raw = searchParams.get(key);
      if (raw === null || raw === "") return spec.default ?? null;
      try {
        return JSON.parse(raw);
      } catch {
        // Malformed hand-edited URLs degrade to the default, never throw.
        return spec.default ?? null;
      }
    }
    case "string":
    default: {
      const raw = searchParams.get(key);
      return raw === null ? (spec.default ?? "") : raw;
    }
  }
}

/**
 * Write one typed value into a URLSearchParams. Values equal to their default
 * (or empty) are REMOVED — canonical URLs carry only meaningful state.
 */
function writeValue(spec, searchParams, key, value) {
  searchParams.delete(key);
  if (value === undefined || value === null) return;
  switch (spec.type) {
    case "array": {
      const items = Array.isArray(value) ? value : [value];
      for (const item of items) {
        if (item !== undefined && item !== null && `${item}` !== "") {
          searchParams.append(key, `${item}`);
        }
      }
      return;
    }
    case "bool": {
      const def = spec.default ?? false;
      if (value === def) return;
      searchParams.set(key, value ? "1" : "0");
      return;
    }
    case "json": {
      const encoded = JSON.stringify(value);
      const defEncoded = spec.default === undefined ? undefined : JSON.stringify(spec.default);
      if (encoded === undefined || encoded === defEncoded) return;
      searchParams.set(key, encoded);
      return;
    }
    case "string":
    default: {
      const str2 = `${value}`;
      if (str2 === "" || str2 === (spec.default ?? "")) return;
      searchParams.set(key, str2);
    }
  }
}

// Permissive spec for params not declared in a schema (navigate() extras):
// infer the wire shape from the runtime value so nothing is silently dropped.
function inferSpec(value) {
  if (Array.isArray(value)) return { type: "array" };
  if (typeof value === "boolean") return { type: "bool" };
  if (value !== null && typeof value === "object") return { type: "json" };
  return { type: "string" };
}

/** Parse a search string / URLSearchParams into a fully-defaulted value object. */
export function parseSearch(schema, search) {
  const sp = search instanceof URLSearchParams ? search : new URLSearchParams(search || "");
  const norm = normalizeSchema(schema);
  const out = {};
  for (const [key, spec] of Object.entries(norm)) {
    out[key] = parseValue(spec, sp, key);
  }
  return out;
}

/** Serialize a value object to a search string ("" or "?..."). */
export function serializeSearch(schema, values) {
  const norm = normalizeSchema(schema);
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(values || {})) {
    writeValue(norm[key] ?? inferSpec(value), sp, key, value);
  }
  return searchString(sp);
}

/**
 * Apply a patch of typed values on top of existing search params. Keys not in
 * the patch are left untouched (other features' params — e.g. ?peek= — survive).
 * Returns a NEW URLSearchParams.
 */
export function writeParams(schema, currentSearchParams, patch) {
  const norm = normalizeSchema(schema);
  const sp = new URLSearchParams(currentSearchParams);
  for (const [key, value] of Object.entries(patch || {})) {
    writeValue(norm[key] ?? inferSpec(value), sp, key, value);
  }
  return sp;
}
