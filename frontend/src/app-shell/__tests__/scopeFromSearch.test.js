import { describe, expect, it } from "vitest";
import { scopeFromSearch } from "../AxiomAiDock.jsx";

// scopeFromSearch turns the active Discover URL facets into the AI "here"
// scope. The caller gates it to the Discover surface; these tests lock the
// facet key set so a saved-view or facet is never silently dropped again.
describe("scopeFromSearch", () => {
  it("returns null when no facets are active", () => {
    expect(scopeFromSearch("")).toBeNull();
    expect(scopeFromSearch("?peek=main.a.b")).toBeNull();
  });

  it("captures every real Discover facet, including saved views", () => {
    const scope = scopeFromSearch(
      "?domain=Finance&domain=Sales&criticality=Critical&tier=Tier+1" +
        "&certification=Certified&sensitivity=PII&view=Needs+owner&type=Table&catalog=main" +
        "&owner=__unassigned__&q=revenue",
    );
    expect(scope).toEqual({
      domain: ["Finance", "Sales"],
      criticality: ["Critical"],
      tier: ["Tier 1"],
      certification: ["Certified"],
      sensitivity: ["PII"],
      view: ["Needs owner"],
      type: ["Table"],
      catalog: ["main"],
      owner: "__unassigned__",
      query: "revenue",
    });
  });

  it("keeps a saved-view-only scope (the flagship 'Needs owner' flow)", () => {
    expect(scopeFromSearch("?view=Needs+owner")).toEqual({ view: ["Needs owner"] });
  });
});
