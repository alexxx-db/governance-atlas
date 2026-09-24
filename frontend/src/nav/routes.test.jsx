/**
 * Wave A3 route-resolution suite.
 *
 * Contract under test (COHESION_BLUEPRINT surface map + cross-linking law):
 *   1. EVERY legacy URL from FRONTEND_BLUEPRINT §2.1-2.2 resolves to the right
 *      canonical target with query params preserved.
 *   2. Every entityRef kind produces its contract route.
 *   3. paramsSchema values round-trip (serialize → parse is identity).
 *   4. The hooks bind it all to react-router (navigate / peek / typed params).
 */

import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";

import {
  ROUTES,
  navSections,
  parseSearch,
  resolveUrl,
  routeForPathname,
  serializeSearch,
  writeParams,
} from "./routes.js";
import { refHref, resolveRef } from "./refs.js";
import { useAtlasNavigate, usePeek } from "./useAtlasNavigate.js";
import { useSurfaceParams } from "./useSurfaceParams.js";

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */

function sortedSearch(search) {
  const sp = new URLSearchParams(search);
  const entries = [...sp.entries()].sort(
    (a, b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]),
  );
  return entries.map(([k, v]) => `${k}=${v}`).join("&");
}

function expectResolves(input, expectedPathname, expectedSearch = "", { redirected } = {}) {
  const result = resolveUrl(input);
  expect(result, `expected ${input} to resolve`).not.toBeNull();
  expect(result.pathname, `pathname for ${input}`).toBe(expectedPathname);
  expect(sortedSearch(result.search), `search for ${input}`).toBe(sortedSearch(expectedSearch));
  if (redirected !== undefined) {
    expect(result.redirected, `redirected flag for ${input}`).toBe(redirected);
  }
  return result;
}

/* ------------------------------------------------------------------ */
/* 1. Legacy URL resolution (FRONTEND_BLUEPRINT §2.1-2.2 census)        */
/* ------------------------------------------------------------------ */

describe("route table: legacy alias resolution", () => {
  it("home absorbs /, /command-center, /exec, and /insights", () => {
    expectResolves("/", "/home", "", { redirected: true });
    expectResolves("/command-center", "/home", "", { redirected: true });
    expectResolves("/exec", "/home", "", { redirected: true });
    expectResolves("/insights", "/home", "", { redirected: true });
    // The old sessionStorage ga-insights-focus handoff becomes a plain param
    // and must survive the redirect.
    expectResolves("/insights?focus=risk", "/home", "?focus=risk", { redirected: true });
  });

  it("discovery keeps /discover with full query state", () => {
    expectResolves("/discover", "/discovery", "", { redirected: true });
    expectResolves(
      "/discover?q=revenue&sort=name&view=table",
      "/discovery",
      "?q=revenue&sort=name&view=table",
      { redirected: true },
    );
  });

  it("asset hub: /entity/* and /asset/* redirect to /assets/*", () => {
    const entity = expectResolves(
      "/entity/main.sales.orders",
      "/assets/main.sales.orders",
      "",
      { redirected: true },
    );
    expect(entity.surface).toBe("assets");
    expect(entity.pathParams.fqn).toBe("main.sales.orders");

    expectResolves("/asset/main.sales.orders", "/assets/main.sales.orders", "", {
      redirected: true,
    });
    // Entity tab was sessionStorage-only; now it rides the URL through redirects.
    expectResolves(
      "/entity/main.sales.orders?tab=columns&col=email",
      "/assets/main.sales.orders",
      "?tab=columns&col=email",
      { redirected: true },
    );
    // Legacy multi-segment FQNs joined with "/" keep working.
    const slashy = expectResolves("/entity/main/sales/orders", "/assets/main/sales/orders", "", {
      redirected: true,
    });
    expect(slashy.pathParams.fqn).toBe("main/sales/orders");
    // Percent-encoded FQNs decode into pathParams.
    const encoded = resolveUrl("/entity/main.sales.order%20items");
    expect(encoded.pathParams.fqn).toBe("main.sales.order items");
  });

  it("a bare /entity or /asset is not an asset link", () => {
    expect(resolveUrl("/entity")).toBeNull();
    expect(resolveUrl("/asset")).toBeNull();
  });

  it("stewardship absorbs /governance, /sk, and /inbox (as my-work)", () => {
    expectResolves("/governance", "/stewardship", "", { redirected: true });
    expectResolves("/sk", "/stewardship", "", { redirected: true });
    // Legacy ?asset= governance deep links survive.
    expectResolves("/governance?asset=main.sales.orders", "/stewardship", "?asset=main.sales.orders", {
      redirected: true,
    });
    // /inbox dies as a destination but keeps its MEANING: my open work.
    expectResolves("/inbox", "/stewardship", "?assignee=me", { redirected: true });
  });

  it("glossary absorbs /taxonomy, glossary spellings, and the CDE surface", () => {
    expectResolves("/taxonomy", "/glossary", "", { redirected: true });
    expectResolves("/glossary-cdes", "/glossary", "", { redirected: true });
    expectResolves("/glossary-and-cdes", "/glossary", "", { redirected: true });
    expectResolves("/taxonomy?tab=cdes", "/glossary", "?tab=cdes", { redirected: true });
    expectResolves("/cde", "/glossary", "?tab=cdes", { redirected: true });
    expectResolves("/cdes", "/glossary", "?tab=cdes", { redirected: true });
    // CDE focus param survives alongside the alias-seeded tab.
    expectResolves("/cde?cde=cde-7", "/glossary", "?tab=cdes&cde=cde-7", { redirected: true });
  });

  it("legacy transient ?term= is promoted to the durable /glossary/<id> path", () => {
    const viaTaxonomy = expectResolves("/taxonomy?term=t-42", "/glossary/t-42", "", {
      redirected: true,
    });
    expect(viaTaxonomy.surface).toBe("glossary");
    expect(viaTaxonomy.pathParams.termId).toBe("t-42");
    // Even on the canonical path, ?term= normalizes to the path form.
    expectResolves("/glossary?term=t-42", "/glossary/t-42", "", { redirected: true });
  });

  it("lineage keeps /lineage-atlas with and without a focus asset", () => {
    expectResolves("/lineage-atlas", "/lineage", "", { redirected: true });
    const focused = expectResolves(
      "/lineage-atlas/main.sales.orders",
      "/lineage/main.sales.orders",
      "",
      { redirected: true },
    );
    expect(focused.surface).toBe("lineage");
    expect(focused.pathParams.fqn).toBe("main.sales.orders");
  });

  it("evidence absorbs /audit and /audit-evidence with event params intact", () => {
    expectResolves("/audit", "/evidence", "", { redirected: true });
    expectResolves("/audit-evidence", "/evidence", "", { redirected: true });
    expectResolves("/audit?event=AUD-1234ABCD", "/evidence", "?event=AUD-1234ABCD", {
      redirected: true,
    });
  });

  it("admin absorbs /control-center and /capabilities (as diagnostics tab)", () => {
    expectResolves("/control-center", "/admin", "", { redirected: true });
    expectResolves("/capabilities", "/admin", "?tab=diagnostics", { redirected: true });
  });

  it("canonical URLs resolve to themselves without redirecting", () => {
    const canonical = [
      "/home",
      "/discovery",
      "/assets/main.sales.orders",
      "/stewardship",
      "/glossary",
      "/glossary/t-42",
      "/lineage",
      "/lineage/main.sales.orders",
      "/evidence",
      "/admin",
      "/help",
    ];
    for (const path of canonical) {
      const result = expectResolves(path, path, "", { redirected: false });
      expect(result.route).toBeTruthy();
    }
    // Params on canonical routes pass through untouched.
    expectResolves("/stewardship?item=GOV-BE17D517", "/stewardship", "?item=GOV-BE17D517", {
      redirected: false,
    });
  });

  it("unknown paths resolve to null (caller decides the not-found behavior)", () => {
    expect(resolveUrl("/nonsense")).toBeNull();
  });

  it("bare /assets resolves to the search-first Asset 360 picker (owner directive 1)", () => {
    const result = resolveUrl("/assets");
    expect(result).toBeTruthy();
    expect(result.surface).toBe("assets");
    expect(result.pathname).toBe("/assets");
    expect(result.pathParams.fqn).toBeUndefined();
    // The greedy detail route still wins for any path carrying an FQN segment.
    expect(resolveUrl("/assets/main.sales.orders").pathParams.fqn).toBe("main.sales.orders");
  });
});

/* ------------------------------------------------------------------ */
/* Route-table shape invariants                                         */
/* ------------------------------------------------------------------ */

describe("route table: shape", () => {
  it("covers exactly the blueprint's canonical paths", () => {
    expect(ROUTES.map((route) => route.path).sort()).toEqual(
      [
        "/admin",
        "/ai",
        "/ai/assets/:entityId",
        "/assets",
        "/assets/:fqn",
        "/datapact",
        "/discovery",
        "/evidence",
        "/glossary",
        "/glossary/:termId",
        "/help",
        "/home",
        "/lineage",
        "/lineage/:fqn",
        "/stewardship",
      ].sort(),
    );
  });

  it("builds the rail exactly per PRODUCT_BLUEPRINT §5", () => {
    const sections = navSections();
    expect(sections.map((section) => section.id)).toEqual(["govern", "knowledge", "profile"]);
    expect(sections[0].items.map((item) => item.label)).toEqual([
      "Command Center",
      "Discover",
      "Stewardship",
      "DataPact",
      "AI Governance",
    ]);
    expect(sections[1].items.map((item) => item.label)).toEqual([
      "Glossary & CDEs",
      "Lineage Atlas",
      "Evidence",
    ]);
    expect(sections[2].items.map((item) => item.label)).toEqual(["Control Center", "Help"]);
    // Stewardship badge = MY open items; Control Center is admin-gated.
    expect(sections[0].items[2].badgeKey).toBe("myWork");
    expect(sections[2].items[0].gate).toBe("admin");
    // AI Governance is feature-gated: hidden unless the backend flag is on.
    expect(sections[0].items[4].gate).toBe("aiGovernance");
    // The hub is NOT a static rail item (contextual entry comes in Wave B).
    const railSurfaces = sections.flatMap((section) => section.items.map((item) => item.surface));
    expect(railSurfaces).not.toContain("assets");
  });
});

/* ------------------------------------------------------------------ */
/* 2. entityRef / surfaceRef resolution (cross-linking contract)        */
/* ------------------------------------------------------------------ */

describe("refs: every entity kind produces its contract route", () => {
  const FQN = "main.sales.orders";

  it("asset", () => {
    expect(resolveRef({ kind: "asset", fqn: FQN })).toEqual({
      path: `/assets/${FQN}`,
      params: {},
    });
  });

  it("column", () => {
    expect(resolveRef({ kind: "column", fqn: FQN, column: "email" })).toEqual({
      path: `/assets/${FQN}`,
      params: { tab: "columns", col: "email" },
    });
    expect(refHref({ kind: "column", fqn: FQN, column: "email" })).toBe(
      `/assets/${FQN}?tab=columns&col=email`,
    );
  });

  it("term", () => {
    expect(resolveRef({ kind: "term", id: "t-42" })).toEqual({
      path: "/glossary/t-42",
      params: {},
    });
  });

  it("cde", () => {
    expect(resolveRef({ kind: "cde", id: "cde-7" })).toEqual({
      path: "/glossary",
      params: { tab: "cdes", cde: "cde-7" },
    });
  });

  it("owner uses the one owner-search grammar", () => {
    expect(resolveRef({ kind: "owner", id: "jane@corp.com" })).toEqual({
      path: "/discovery",
      params: { q: 'owner:"jane@corp.com"' },
    });
  });

  it("request (work item) focuses the queue item", () => {
    expect(resolveRef({ kind: "request", id: "GOV-BE17D517" })).toEqual({
      path: "/stewardship",
      params: { item: "GOV-BE17D517" },
    });
  });

  it("event lands on Evidence, not the legacy /audit alias", () => {
    expect(resolveRef({ kind: "event", id: "AUD-1234ABCD" })).toEqual({
      path: "/evidence",
      params: { event: "AUD-1234ABCD" },
    });
  });

  it("quality finding lands on the Evidence quality tab scoped to asset+run", () => {
    expect(resolveRef({ kind: "quality-finding", asset: FQN, run: "run-9" })).toEqual({
      path: "/evidence",
      params: { tab: "quality", asset: FQN, run: "run-9" },
    });
  });

  it("catalog and domain pre-filter Discovery via the ?filters= JSON contract", () => {
    expect(resolveRef({ kind: "catalog", name: "main" })).toEqual({
      path: "/discovery",
      params: { filters: { catalogs: ["main"] } },
    });
    expect(resolveRef({ kind: "domain", name: "Finance" })).toEqual({
      path: "/discovery",
      params: { filters: { domains: ["Finance"] } },
    });
    // The href serializes filters as JSON on the wire.
    const href = refHref({ kind: "domain", name: "Finance" });
    expect(href.startsWith("/discovery?filters=")).toBe(true);
    const parsed = new URLSearchParams(href.split("?")[1]);
    expect(JSON.parse(parsed.get("filters"))).toEqual({ domains: ["Finance"] });
  });

  it("lineage always carries the focus asset", () => {
    expect(resolveRef({ kind: "lineage", fqn: FQN })).toEqual({
      path: `/lineage/${FQN}`,
      params: {},
    });
  });

  it("every ref href resolves back through the route table", () => {
    const refs = [
      { kind: "asset", fqn: FQN },
      { kind: "column", fqn: FQN, column: "email" },
      { kind: "term", id: "t-42" },
      { kind: "cde", id: "cde-7" },
      { kind: "owner", id: "jane@corp.com" },
      { kind: "request", id: "GOV-BE17D517" },
      { kind: "event", id: "AUD-1234ABCD" },
      { kind: "quality-finding", asset: FQN, run: "run-9" },
      { kind: "catalog", name: "main" },
      { kind: "domain", name: "Finance" },
      { kind: "lineage", fqn: FQN },
    ];
    for (const ref of refs) {
      const href = refHref(ref);
      const resolved = resolveUrl(href);
      expect(resolved, `refHref ${href} must resolve`).not.toBeNull();
      expect(resolved.redirected, `refHref ${href} must already be canonical`).toBe(false);
    }
  });

  it("surfaceRefs resolve, with path params consumed from ref.params", () => {
    expect(resolveRef({ surface: "discovery", params: { q: "revenue" } })).toEqual({
      path: "/discovery",
      params: { q: "revenue" },
    });
    expect(resolveRef({ surface: "lineage", params: { fqn: FQN } })).toEqual({
      path: `/lineage/${FQN}`,
      params: {},
    });
    expect(resolveRef({ surface: "assets", params: { fqn: FQN, tab: "quality" } })).toEqual({
      path: `/assets/${FQN}`,
      params: { tab: "quality" },
    });
    // Owner directive 1: the hub NOW has a bare route — a missing fqn resolves
    // to the search-first picker (/assets) instead of throwing.
    expect(resolveRef({ surface: "assets" })).toEqual({ path: "/assets", params: {} });
    expect(() => resolveRef({ surface: "not-a-surface" })).toThrow(/unknown surface/);
  });

  it("rejects unknown kinds and missing required fields loudly", () => {
    expect(() => resolveRef({ kind: "gizmo", id: "x" })).toThrow(/unknown entityRef kind/);
    expect(() => resolveRef({ kind: "asset" })).toThrow(/requires "fqn"/);
    expect(() => resolveRef({ kind: "column", fqn: FQN })).toThrow(/requires "column"/);
  });
});

/* ------------------------------------------------------------------ */
/* 3. paramsSchema round-trips                                          */
/* ------------------------------------------------------------------ */

describe("paramsSchema: serialize → parse round-trips", () => {
  const discoverySchema = routeForPathname("/discovery").paramsSchema;

  it("round-trips the full discovery state", () => {
    const values = {
      q: 'owner:"jane@corp.com"',
      sort: "name",
      view: "table",
      filters: { domains: ["Finance"], tiers: ["gold"] },
      domain: ["Finance", "Risk"],
      tier: ["gold"],
      owner: "jane@corp.com",
      peek: "main.sales.orders",
    };
    const search = serializeSearch(discoverySchema, values);
    expect(parseSearch(discoverySchema, search)).toEqual(values);
  });

  it("empty/default values serialize to a clean URL and parse back to defaults", () => {
    const search = serializeSearch(discoverySchema, {
      q: "",
      filters: null,
      domain: [],
      tier: [],
      view: "",
      sort: "",
      owner: "",
      peek: "",
    });
    expect(search).toBe("");
    expect(parseSearch(discoverySchema, search)).toEqual({
      q: "",
      sort: "",
      view: "",
      filters: null,
      domain: [],
      tier: [],
      owner: "",
      peek: "",
    });
  });

  it("bool params honor defaults in both directions", () => {
    const schema = { expanded: { type: "bool", default: true }, dense: { type: "bool" } };
    // Non-default values hit the wire; defaults stay off it.
    expect(serializeSearch(schema, { expanded: false, dense: true })).toBe("?expanded=0&dense=1");
    expect(serializeSearch(schema, { expanded: true, dense: false })).toBe("");
    expect(parseSearch(schema, "?expanded=0&dense=1")).toEqual({ expanded: false, dense: true });
    expect(parseSearch(schema, "")).toEqual({ expanded: true, dense: false });
    // Tolerant parsing of hand-typed booleans.
    expect(parseSearch(schema, "?dense=true").dense).toBe(true);
    expect(parseSearch(schema, "?expanded=no").expanded).toBe(false);
  });

  it("malformed JSON degrades to the default instead of throwing", () => {
    expect(parseSearch({ filters: { type: "json" } }, "?filters=%7Bnope").filters).toBeNull();
    expect(
      parseSearch({ filters: { type: "json", default: { all: true } } }, "?filters=%7Bnope").filters,
    ).toEqual({ all: true });
  });

  it("writeParams patches only the given keys and preserves foreign params", () => {
    const current = new URLSearchParams("?q=revenue&peek=main.sales.orders&stray=1");
    const next = writeParams(discoverySchema, current, { q: "churn", domain: ["Finance"] });
    expect(next.get("q")).toBe("churn");
    expect(next.getAll("domain")).toEqual(["Finance"]);
    expect(next.get("peek")).toBe("main.sales.orders");
    expect(next.get("stray")).toBe("1");
    // Clearing a key removes it entirely.
    const cleared = writeParams(discoverySchema, next, { q: "", domain: [] });
    expect(cleared.has("q")).toBe(false);
    expect(cleared.has("domain")).toBe(false);
    expect(cleared.get("stray")).toBe("1");
  });
});

/* ------------------------------------------------------------------ */
/* 4. Hooks over react-router                                           */
/* ------------------------------------------------------------------ */

function LocationProbe() {
  const location = useLocation();
  return (
    <>
      <div data-testid="path">{location.pathname}</div>
      <div data-testid="search">{location.search}</div>
    </>
  );
}

describe("useAtlasNavigate", () => {
  function NavigateHarness() {
    const navigate = useAtlasNavigate();
    globalThis.__atlasNavigate = navigate;
    return <LocationProbe />;
  }

  function renderAt(initialEntry) {
    return render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <NavigateHarness />
      </MemoryRouter>,
    );
  }

  it("navigates to an entityRef's canonical route with serialized params", () => {
    renderAt("/home");
    act(() => globalThis.__atlasNavigate({ kind: "cde", id: "cde-7" }));
    expect(screen.getByTestId("path").textContent).toBe("/glossary");
    expect(sortedSearch(screen.getByTestId("search").textContent)).toBe(
      sortedSearch("?tab=cdes&cde=cde-7"),
    );
  });

  it("merges extra params over the ref's own", () => {
    renderAt("/home");
    act(() =>
      globalThis.__atlasNavigate(
        { kind: "asset", fqn: "main.sales.orders" },
        { params: { tab: "quality" } },
      ),
    );
    expect(screen.getByTestId("path").textContent).toBe("/assets/main.sales.orders");
    expect(screen.getByTestId("search").textContent).toBe("?tab=quality");
  });

  it("peek stays on the current surface and binds ?peek=", () => {
    renderAt("/discovery?q=revenue");
    act(() =>
      globalThis.__atlasNavigate({ kind: "asset", fqn: "main.sales.orders" }, { peek: true }),
    );
    expect(screen.getByTestId("path").textContent).toBe("/discovery");
    expect(sortedSearch(screen.getByTestId("search").textContent)).toBe(
      sortedSearch("?q=revenue&peek=main.sales.orders"),
    );
  });
});

describe("usePeek", () => {
  function PeekHarness() {
    const peek = usePeek();
    globalThis.__atlasPeek = peek;
    return (
      <>
        <div data-testid="peekFqn">{peek.peekFqn}</div>
        <LocationProbe />
      </>
    );
  }

  it("reads, opens, and closes the drawer binding", () => {
    render(
      <MemoryRouter initialEntries={["/discovery?q=revenue"]}>
        <PeekHarness />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("peekFqn").textContent).toBe("");

    act(() => globalThis.__atlasPeek.openPeek("main.sales.orders"));
    expect(screen.getByTestId("peekFqn").textContent).toBe("main.sales.orders");
    expect(screen.getByTestId("path").textContent).toBe("/discovery");

    act(() => globalThis.__atlasPeek.closePeek());
    expect(screen.getByTestId("peekFqn").textContent).toBe("");
    // The surface's own params survive the drawer lifecycle.
    expect(screen.getByTestId("search").textContent).toBe("?q=revenue");
  });
});

describe("useSurfaceParams", () => {
  const schema = routeForPathname("/discovery").paramsSchema;

  function ParamsHarness() {
    const [params, setParams] = useSurfaceParams(schema);
    globalThis.__atlasSetParams = setParams;
    const navigate = useNavigate();
    globalThis.__atlasBack = () => navigate(-1);
    return (
      <>
        <div data-testid="q">{params.q}</div>
        <div data-testid="domain">{params.domain.join("|")}</div>
        <div data-testid="filters">{JSON.stringify(params.filters)}</div>
        <LocationProbe />
      </>
    );
  }

  function renderAt(initialEntry) {
    return render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <ParamsHarness />
      </MemoryRouter>,
    );
  }

  it("reads typed values from the URL", () => {
    renderAt(
      "/discovery?q=revenue&domain=Finance&domain=Risk&filters=%7B%22tiers%22%3A%5B%22gold%22%5D%7D",
    );
    expect(screen.getByTestId("q").textContent).toBe("revenue");
    expect(screen.getByTestId("domain").textContent).toBe("Finance|Risk");
    expect(screen.getByTestId("filters").textContent).toBe('{"tiers":["gold"]}');
  });

  it("writes patches without disturbing foreign params, replacing by default", () => {
    // Seed a prior history entry so we can PROVE the write replaced rather
    // than pushed: Back must skip the pre-edit discovery state entirely.
    render(
      <MemoryRouter
        initialEntries={["/home", "/discovery?q=revenue&peek=main.sales.orders"]}
        initialIndex={1}
      >
        <ParamsHarness />
      </MemoryRouter>,
    );
    act(() => globalThis.__atlasSetParams({ q: "churn", domain: ["Finance"] }));
    const sp = new URLSearchParams(screen.getByTestId("search").textContent);
    expect(sp.get("q")).toBe("churn");
    expect(sp.getAll("domain")).toEqual(["Finance"]);
    expect(sp.get("peek")).toBe("main.sales.orders");

    // Default write is replace: no intermediate entry — Back lands on /home.
    act(() => globalThis.__atlasBack());
    expect(screen.getByTestId("path").textContent).toBe("/home");
  });

  it("push:true creates a history entry so Back restores the previous state", () => {
    renderAt("/discovery?q=revenue");
    act(() => globalThis.__atlasSetParams({ q: "churn" }, { push: true }));
    expect(screen.getByTestId("q").textContent).toBe("churn");
    act(() => globalThis.__atlasBack());
    expect(screen.getByTestId("q").textContent).toBe("revenue");
  });
});
