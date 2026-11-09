import { describe, expect, it } from "vitest";
import {
  firstHopNeighbors,
  formatUtcInstant,
  ownerRef,
  priorityLabel,
  priorityTone,
  termRef,
} from "../format";

describe("formatUtcInstant", () => {
  it("formats an ISO timestamp as absolute UTC with the ISO preserved", () => {
    const out = formatUtcInstant("2026-05-03T19:51:25.309000Z");
    expect(out.display).toBe("May 3, 2026, 19:51 UTC");
    expect(out.iso).toBe("2026-05-03T19:51:25.309Z");
  });

  it("returns null for empty or unparseable input (callers render an honest dash)", () => {
    expect(formatUtcInstant("")).toBeNull();
    expect(formatUtcInstant(null)).toBeNull();
    expect(formatUtcInstant("not-a-date")).toBeNull();
  });
});

describe("priority helpers", () => {
  it("uppercases priorities and maps urgency tones", () => {
    expect(priorityLabel("p1")).toBe("P1");
    expect(priorityLabel("")).toBe("");
    expect(priorityTone("p1")).toBe("bad");
    expect(priorityTone("p2")).toBe("warn");
    expect(priorityTone("p3")).toBe("neutral");
  });
});

describe("termRef", () => {
  it("uses the canonical term route when a termId exists", () => {
    expect(termRef({ term: "Net Revenue", termId: "term-9" })).toEqual({
      kind: "term",
      id: "term-9",
      label: "Net Revenue",
    });
  });

  it("falls back to the glossary search grammar for name-only terms", () => {
    expect(termRef("Net Revenue")).toEqual({
      surface: "glossary",
      params: { term: "Net Revenue" },
      label: "Net Revenue",
    });
  });

  it("returns null for empty input", () => {
    expect(termRef("")).toBeNull();
    expect(termRef({})).toBeNull();
  });
});

describe("ownerRef", () => {
  it("builds owner refs without regex prettifying", () => {
    expect(ownerRef({ name: "product-steward@shorecp.com" })).toEqual({
      kind: "owner",
      email: "product-steward@shorecp.com",
      label: "product-steward@shorecp.com",
    });
    expect(ownerRef({ name: "abarreto@shorecp.com", displayName: "Skyler" }).label).toBe("Skyler");
    expect(ownerRef(null)).toBeNull();
  });
});

describe("firstHopNeighbors", () => {
  const graph = {
    focus: { id: "focus-a", fqn: "c.s.a" },
    nodes: [
      { id: "focus-a", fqn: "c.s.a", label: "a" },
      { id: "up-1", fqn: "c.s.up1", label: "up1" },
      { id: "down-1", fqn: "c.s.down1", label: "down1" },
    ],
    edges: [
      { id: "e1", source: "up-1", target: "focus-a" },
      { id: "e2", source: "focus-a", target: "down-1" },
    ],
  };

  it("splits first-hop upstream and downstream around the focus", () => {
    const { upstream, downstream } = firstHopNeighbors(graph);
    expect(upstream.map((node) => node.fqn)).toEqual(["c.s.up1"]);
    expect(downstream.map((node) => node.fqn)).toEqual(["c.s.down1"]);
  });

  it("is empty-safe without a focus", () => {
    expect(firstHopNeighbors(null)).toEqual({ focus: null, upstream: [], downstream: [] });
  });
});
