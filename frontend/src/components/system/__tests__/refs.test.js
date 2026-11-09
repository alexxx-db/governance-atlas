import { describe, expect, it } from "vitest";
import { defaultRefLabel, hrefForRef } from "../refs";

function searchOf(href) {
  return new URLSearchParams(href.split("?")[1] ?? "");
}

describe("hrefForRef — Cross-linking contract (COHESION_BLUEPRINT LAW)", () => {
  it("asset → /assets/<fqn>", () => {
    expect(hrefForRef({ kind: "asset", fqn: "main.sales.orders" })).toBe("/assets/main.sales.orders");
  });

  it("asset accepts fqn via id and encodes unsafe characters while keeping dots", () => {
    expect(hrefForRef({ kind: "asset", id: "main.sales.orders" })).toBe("/assets/main.sales.orders");
    const href = hrefForRef({ kind: "asset", fqn: "main.raw.my table" });
    expect(href).toBe("/assets/main.raw.my%20table");
  });

  it("asset carries extra params (e.g. ?tab=)", () => {
    const href = hrefForRef({ kind: "asset", fqn: "a.b.c", params: { tab: "quality" } });
    expect(href).toBe("/assets/a.b.c?tab=quality");
  });

  it("column → /assets/<fqn>?tab=columns&col=<name>", () => {
    const href = hrefForRef({ kind: "column", fqn: "main.sales.orders", id: "order_id" });
    expect(href.startsWith("/assets/main.sales.orders?")).toBe(true);
    const params = searchOf(href);
    expect(params.get("tab")).toBe("columns");
    expect(params.get("col")).toBe("order_id");
  });

  it("column without a parent asset FQN has no address", () => {
    expect(hrefForRef({ kind: "column", id: "order_id" })).toBeNull();
  });

  it("term → /glossary/<termId>", () => {
    expect(hrefForRef({ kind: "term", id: "term-123" })).toBe("/glossary/term-123");
  });

  it("cde → /glossary?tab=cdes&cde=<id>", () => {
    const params = searchOf(hrefForRef({ kind: "cde", id: "CDE-9" }));
    expect(params.get("tab")).toBe("cdes");
    expect(params.get("cde")).toBe("CDE-9");
  });

  it('owner → /discovery?q=owner:"<email>"', () => {
    const href = hrefForRef({ kind: "owner", id: "jane@shorecp.com" });
    expect(href.startsWith("/discovery?")).toBe(true);
    expect(searchOf(href).get("q")).toBe('owner:"jane@shorecp.com"');
  });

  it("owner → null for non-principal values (system actors, team/domain labels)", () => {
    // Identity integrity: only real account principals (email-shaped) are
    // linkable owners; a system action slug or team name has no account page.
    expect(hrefForRef({ kind: "owner", id: "identity-integrity-cleanup" })).toBeNull();
    expect(hrefForRef({ kind: "owner", label: "Product" })).toBeNull();
    expect(hrefForRef({ kind: "owner", email: "svc-governance-sweeper" })).toBeNull();
  });

  it("request → /stewardship?item=GOV-…", () => {
    expect(searchOf(hrefForRef({ kind: "request", id: "GOV-BE17D517" })).get("item")).toBe("GOV-BE17D517");
    expect(hrefForRef({ kind: "request", id: "GOV-BE17D517" }).startsWith("/stewardship?")).toBe(true);
  });

  it("event → /evidence?event=AUD-…", () => {
    const href = hrefForRef({ kind: "event", id: "AUD-DEADBEEF" });
    expect(href.startsWith("/evidence?")).toBe(true);
    expect(searchOf(href).get("event")).toBe("AUD-DEADBEEF");
  });

  it("quality → /evidence?tab=quality&asset=…&run=…", () => {
    const params = searchOf(hrefForRef({ kind: "quality", fqn: "a.b.c", run: "run-7" }));
    expect(params.get("tab")).toBe("quality");
    expect(params.get("asset")).toBe("a.b.c");
    expect(params.get("run")).toBe("run-7");
  });

  it('domain → /discovery?filters={"domains":["<name>"]}', () => {
    const href = hrefForRef({ kind: "domain", name: "Finance" });
    expect(href.startsWith("/discovery?")).toBe(true);
    expect(JSON.parse(searchOf(href).get("filters"))).toEqual({ domains: ["Finance"] });
  });

  it('catalog → /discovery?filters={"catalogs":["<name>"]}', () => {
    const href = hrefForRef({ kind: "catalog", name: "main" });
    expect(JSON.parse(searchOf(href).get("filters"))).toEqual({ catalogs: ["main"] });
  });

  it("lineage → /lineage/<fqn>", () => {
    expect(hrefForRef({ kind: "lineage", fqn: "main.sales.orders" })).toBe("/lineage/main.sales.orders");
  });

  it("surfaceRef → surface path with serialized params (objects JSON-stringified)", () => {
    const href = hrefForRef({ surface: "discovery", params: { q: "pii", filters: { tiers: ["gold"] } } });
    expect(href.startsWith("/discovery?")).toBe(true);
    const params = searchOf(href);
    expect(params.get("q")).toBe("pii");
    expect(JSON.parse(params.get("filters"))).toEqual({ tiers: ["gold"] });
  });

  it("returns null for unknown kinds/surfaces and empty refs (no dead links)", () => {
    expect(hrefForRef(null)).toBeNull();
    expect(hrefForRef({ kind: "mystery", id: "x" })).toBeNull();
    expect(hrefForRef({ surface: "not-a-surface" })).toBeNull();
    expect(hrefForRef({ kind: "asset" })).toBeNull();
    expect(hrefForRef({ kind: "term" })).toBeNull();
  });
});

describe("defaultRefLabel", () => {
  it("prefers explicit label, then kind-appropriate identity", () => {
    expect(defaultRefLabel({ kind: "asset", fqn: "a.b.c", label: "Orders" })).toBe("Orders");
    expect(defaultRefLabel({ kind: "asset", fqn: "a.b.c" })).toBe("a.b.c");
    expect(defaultRefLabel({ kind: "owner", email: "jane@shorecp.com" })).toBe("jane@shorecp.com");
    expect(defaultRefLabel({ kind: "column", fqn: "a.b.c", id: "order_id" })).toBe("order_id");
    expect(defaultRefLabel({ kind: "request", id: "GOV-1" })).toBe("GOV-1");
  });
});
