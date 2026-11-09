import { describe, expect, it } from "vitest";
import { normalizeInsightsDashboard } from "./useInsightsDashboard";

describe("normalizeInsightsDashboard", () => {
  it("unwraps Axiom API envelopes before normalizing insight rows", () => {
    const normalized = normalizeInsightsDashboard({
      data: {
        kpis: [{ key: "maturity", value: 82, format: "score" }],
        metadataCoverageHeatmap: [{ row: "Customer", column: "Ownership", value: 90 }],
        scoring: { maturityFormula: [{ signal: "metadataCoverage", weight: 0.3 }], availableSignals: ["metadataCoverage"] },
        meta: { state: "available", warnings: [] },
      },
      meta: { requestId: "req-1" },
    });

    expect(normalized.kpis).toHaveLength(1);
    expect(normalized.kpis[0]).toMatchObject({ key: "maturity", value: 82 });
    expect(normalized.metadataCoverageHeatmap).toHaveLength(1);
    expect(normalized.scoring.availableSignals).toEqual(["metadataCoverage"]);
    expect(normalized.meta.requestId).toBe("req-1");
  });

  it("preserves degraded envelope metadata from the Axiom API wrapper", () => {
    const normalized = normalizeInsightsDashboard({
      data: {
        kpis: [{ key: "policyCompliance", value: null, state: "unavailable" }],
        scoring: { maturityFormula: [], availableSignals: [] },
      },
      meta: {
        state: "degraded",
        warnings: ["Policy compliance is unavailable."],
        capabilities: { policyCompliance: false },
      },
    });

    expect(normalized.meta.state).toBe("degraded");
    expect(normalized.meta.warnings).toEqual(["Policy compliance is unavailable."]);
    expect(normalized.meta.capabilities).toEqual({ policyCompliance: false });
  });
});
