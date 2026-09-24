import { describe, expect, it } from "vitest";

import { railGateAllowed } from "../../../app-shell/Rail.jsx";
import {
  DASH,
  availabilityWarnings,
  controlDetail,
  countOrDash,
  groupFindings,
  isSteward,
  percentOrDash,
} from "../aiPresentation";

describe("aiPresentation", () => {
  it("never turns missing data into zero", () => {
    expect(countOrDash(null)).toBe(DASH);
    expect(countOrDash(undefined)).toBe(DASH);
    expect(countOrDash(0)).toBe("0");
    expect(percentOrDash(null)).toBe(DASH);
    expect(percentOrDash(0.5)).toBe("50%");
  });

  it("groups findings in triage order", () => {
    const groups = groupFindings([
      { findingId: "a", findingType: "ambiguous_match" },
      { findingId: "b", findingType: "rejected_but_running" },
      { findingId: "c", findingType: "ambiguous_match" },
    ]);
    expect(groups.map((g) => [g.type, g.items.length])).toEqual([
      ["rejected_but_running", 1],
      ["ambiguous_match", 2],
    ]);
  });

  it("explains unknown controls by source", () => {
    expect(
      controlDetail({ status: "unknown", signalSource: "serving_endpoints", evidence: { reason: "credential configuration is not exposed by the serving API" } }),
    ).toBe("Unknown: signal not observable from serving_endpoints (credential configuration is not exposed by the serving API)");
    expect(controlDetail({ status: "fail", evidence: { enabled: false, gatewayConfigured: false } })).toBe("No AI Gateway configuration");
  });

  it("steward gate and warnings", () => {
    expect(isSteward({ role: "Data Steward" })).toBe(true);
    expect(isSteward({ role: "admin" })).toBe(true);
    expect(isSteward({ role: "reader" })).toBe(false);
    expect(availabilityWarnings({ warnings: ["a", "b"], meta: { warnings: ["b", "c"] } })).toEqual(["a", "b", "c"]);
  });
});

describe("railGateAllowed", () => {
  it("shows the AI entry only when the backend flag is on, and fails closed on unknown gates", () => {
    expect(railGateAllowed("aiGovernance", { aiGovernance: { enabled: true } })).toBe(true);
    expect(railGateAllowed("aiGovernance", { aiGovernance: { enabled: false } })).toBe(false);
    expect(railGateAllowed("aiGovernance", {})).toBe(false);
    expect(railGateAllowed(null, {})).toBe(true);
    expect(railGateAllowed("mystery", {})).toBe(false);
  });
});
