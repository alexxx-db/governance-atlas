import { describe, expect, it } from "vitest";
import {
  evidenceEnvelope,
  filterNonAuthoritativeRows,
  isNonAuthoritativeEvidenceEnvelope,
  isNonAuthoritativeMockEvidence,
  nonAuthoritativeMarkerValues,
} from "./nonAuthoritativeEvidence";

describe("nonAuthoritativeEvidence", () => {
  it("detects prototype, mock, and fixture provenance variants in metadata and warnings", () => {
    expect(isNonAuthoritativeMockEvidence({ meta: { state: "prototype-mock" } })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ evidenceKind: "non_authoritative_mock_capture" })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ warnings: ["Fixture data is not live proof."] })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ source: { type: "local-prototype-mock" } })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ mockApi: true })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ warnings: ["not live Databricks evidence"] })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ nonAuthoritative: true })).toBe(true);
  });

  it("does not reject ordinary asset names or source tables when no non-authoritative marker is present", () => {
    const payload = {
      assets: [
        { fqn: "main.dev.mock_data_observations", name: "mock_data_observations" },
      ],
      meta: { state: "available", source: "unity-catalog", sourceTable: "prod_governance.mock_audit_log", authoritative: true },
    };

    expect(isNonAuthoritativeMockEvidence(payload)).toBe(false);
    expect(nonAuthoritativeMarkerValues(payload)).toEqual([
      "state:available",
      "source:unity-catalog",
      "sourcetable:prod_governance.mock_audit_log",
      "authoritative:true",
    ]);
  });

  it("does not reject explicit live mockApi false provenance", () => {
    expect(isNonAuthoritativeMockEvidence({
      evidenceKind: "live_databricks",
      authoritative: true,
      liveDatabricksEvidence: true,
      mockApi: false,
      warnings: [],
    })).toBe(false);
  });

  it("rejects bare authority false markers without trusted degraded live provenance", () => {
    expect(isNonAuthoritativeMockEvidence({ authoritative: false })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({ liveDatabricksEvidence: false })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({
      meta: { state: "available", source: "unity-catalog-inventory", authoritative: false },
    })).toBe(true);
  });

  it("rejects local evidence providers even when derived from local metadata", () => {
    expect(isNonAuthoritativeMockEvidence({
      provider: "local-evidence",
      source: "unity-catalog-inventory+governance-store+local-evidence",
      authoritative: false,
      meta: { state: "degraded" },
    })).toBe(true);
  });

  it("does not reject degraded live envelopes marked authoritative false", () => {
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      liveDatabricksEvidence: false,
      meta: {
        state: "degraded",
        source: "unity-catalog-inventory",
        authoritative: false,
      },
      warnings: ["The forwarded user token is missing the sql scope."],
    })).toBe(false);
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      meta: {
        state: "degraded",
        source: "runtime-shell",
        authoritative: false,
      },
      warnings: ["Runtime setup is still resolving Databricks capabilities."],
    })).toBe(false);
  });

  it("does not reject empty trusted live loading envelopes", () => {
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "loading",
      source: "governance-store+unity-catalog-inventory",
      estate: {},
      kpis: [],
      topDomains: [],
      recentEvents: [],
      warnings: ["Command-center metrics are hydrating from live metadata."],
    })).toBe(false);
  });

  it("allows the explicit initial lineage shell while full visibility proof loads", () => {
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      profile: "initial",
      graphs: {
        data: {
          nodes: [{ id: "focus-main.default.orders", assetFqn: "main.default.orders" }],
          edges: [],
        },
      },
      meta: {
        state: "loading",
        source: "unity-catalog-lineage",
        authoritative: false,
        capabilities: {
          visibilityScope: "initial-route-shell",
          lineageProfile: "initial",
        },
      },
      warnings: [
        "Initial lineage shell does not verify asset visibility; backed detail and full lineage requests remain permission-gated.",
      ],
    })).toBe(false);
  });

  it("allows the full-profile hydrating lineage envelope the live API actually emits", () => {
    // Live cold-cache lineage: source=unity-catalog-lineage, state=loading,
    // authoritative=false, capabilities.visibilityScope=full-lineage-hydrating,
    // carrying the focus node while edges are still fetched. Must render as
    // hydrating, not be rejected as mock (which showed "No lineage edges").
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      profile: "full",
      graphs: {
        data: {
          nodes: [{ id: "focus-main.default.orders", assetFqn: "main.default.orders" }],
          edges: [],
        },
      },
      meta: {
        state: "loading",
        source: "unity-catalog-lineage",
        authoritative: false,
        capabilities: {
          visibilityScope: "full-lineage-hydrating",
          lineageProfile: "full",
          hydrating: true,
        },
      },
    })).toBe(false);
  });

  it("rejects populated business rows when the envelope is authoritative false", () => {
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "degraded",
      source: "databricks-genie",
      recommendations: [
        {
          title: "Review candidate governed assets",
          detail: "Generated without authoritative Genie proof.",
        },
      ],
    })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "unavailable",
      source: "runtime-configuration+databricks-genie",
      recommendations: [],
      evidence: [],
    })).toBe(false);
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "degraded",
      source: "unity-catalog-inventory",
      assets: [{ fqn: "datapact.atlas.customer_dim" }],
    })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "degraded",
      source: "unity-catalog-inventory",
      estate: { visibleAssetCount: 1302, coverageScore: 50.6 },
    })).toBe(true);
    expect(isNonAuthoritativeMockEvidence({
      authoritative: false,
      state: "degraded",
      source: "governance-store+unity-catalog-inventory",
      glossaryTerms: [{ termId: "customer-id", term: "Customer ID" }],
    })).toBe(true);
  });

  it("separates envelope authority from non-authoritative nested rows", () => {
    const asset = {
      fqn: "datapact.enterprise_metadata_ops.risk_data_quality_review",
      authoritative: true,
      source: "unity-catalog-inventory",
      metadataAudit: [
        { id: "GOV-HOME-EVIDENCE-audit-02", source: "home-evidence-plane" },
        { id: "audit-live-01", source: "store" },
      ],
    };

    expect(evidenceEnvelope(asset)).not.toHaveProperty("metadataAudit");
    expect(isNonAuthoritativeEvidenceEnvelope(asset)).toBe(false);
    expect(isNonAuthoritativeMockEvidence(asset)).toBe(true);
    expect(filterNonAuthoritativeRows(asset.metadataAudit)).toEqual([
      { id: "audit-live-01", source: "store" },
    ]);
  });
});
