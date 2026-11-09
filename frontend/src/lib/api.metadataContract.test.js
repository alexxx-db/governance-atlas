import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchAdminControlCenter,
  fetchAxiomAiRecommendations,
  fetchAiAutofill,
  fetchAssetDetail,
  fetchCdeDashboard,
  fetchCdeDetail,
  fetchClassificationRecommendations,
  fetchDiscoverySearch,
  fetchAuditEvidence,
  fetchGovernanceAuditTimeline,
  fetchInsightsDashboard,
  fetchRuntimeStatus,
  fetchTaxonomyOverview,
  formatApiError,
  getAssetMetadataApiContract,
  normalizeGovernancePayload,
} from "./api";

function stubJsonResponse(payload) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  }));
}

describe("asset metadata API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not treat a PATCH-only metadata update route as a GET editor capability route", () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        assetMetadataUpdate: "/api/assets/:fqn/metadata",
      },
    };

    expect(getAssetMetadataApiContract("main.sales.orders")).toEqual({
      available: true,
      capabilityPath: "",
      updatePath: "/api/assets/main.sales.orders/metadata",
    });
  });

  it("keeps a dedicated metadata editor route available for capability reads", () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        assetMetadataEditor: "/api/assets/:fqn/metadata-editor",
        assetMetadataUpdate: "/api/assets/:fqn/metadata",
      },
    };

    expect(getAssetMetadataApiContract("main.sales.orders")).toEqual({
      available: true,
      capabilityPath: "/api/assets/main.sales.orders/metadata-editor",
      updatePath: "/api/assets/main.sales.orders/metadata",
    });
  });

  it("keeps backed asset detail while filtering non-authoritative nested audit rows", async () => {
    stubJsonResponse({
      fqn: "emet.enterprise_metadata_ops.risk_data_quality_review",
      name: "risk_data_quality_review",
      objectType: "View",
      source: "unity-catalog-inventory",
      authoritative: true,
      metadataAudit: [
        { id: "GOV-HOME-EVIDENCE-audit-02", source: "home-evidence-plane" },
        { id: "audit-live-01", source: "store" },
      ],
      activity: [
        { id: "GOV-HOME-EVIDENCE-request-05", title: "Seed request" },
        { id: "activity-live-01", title: "Backed request", source: "governance-store" },
      ],
    });

    await expect(fetchAssetDetail("emet.enterprise_metadata_ops.risk_data_quality_review")).resolves.toEqual(
      expect.objectContaining({
        fqn: "emet.enterprise_metadata_ops.risk_data_quality_review",
        metadataAudit: [{ id: "audit-live-01", source: "store" }],
        activity: [{ id: "activity-live-01", title: "Backed request", source: "governance-store" }],
      }),
    );
  });
});

describe("governance API normalization", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("preserves stewardship badge counts from the governance inbox payload", () => {
    expect(
      normalizeGovernancePayload({
        inbox: {
          state: "ready",
          unreadCount: 2,
          stewardshipCount: 184,
          items: [],
        },
      }).inbox,
    ).toEqual({
      state: "ready",
      message: "",
      unreadCount: 2,
      stewardshipCount: 184,
      items: [],
    });
  });

  it("rejects non-authoritative classification recommendations before they reach governance surfaces", async () => {
    stubJsonResponse({
      recommendations: [{
        recommendationId: "rec-1",
        assetFqn: "main.sales.orders",
        evidenceKind: "non_authoritative_mock_capture",
        evidence: [{ source: "local-prototype-mock" }],
        sampleValues: ["123-45-6789"],
      }],
      count: 1,
      pendingCount: 1,
    });

    await expect(fetchClassificationRecommendations()).resolves.toEqual({
      recommendations: [],
      count: 0,
      pendingCount: 0,
      nonAuthoritative: true,
    });
  });

  it("rejects classification recommendation payloads marked explicitly non-authoritative", async () => {
    stubJsonResponse({
      nonAuthoritative: true,
      recommendations: [{
        recommendationId: "rec-1",
        assetFqn: "main.sales.orders",
        sampleValues: ["123-45-6789"],
      }],
      count: 1,
      pendingCount: 1,
    });

    await expect(fetchClassificationRecommendations()).resolves.toEqual({
      recommendations: [],
      count: 0,
      pendingCount: 0,
      nonAuthoritative: true,
    });
  });

  it("rejects non-authoritative governance audit timeline entries before drawer rendering", async () => {
    stubJsonResponse({
      fqn: "main.sales.orders",
      entries: [{
        action: "grant",
        actor: "reviewer@example.com",
        evidenceKind: "non_authoritative_mock_capture",
      }],
      total: 1,
    });

    await expect(fetchGovernanceAuditTimeline("main.sales.orders")).resolves.toEqual({
      fqn: "main.sales.orders",
      entries: [],
      total: 0,
      nonAuthoritative: true,
    });
  });

  it("rejects governance audit timelines marked explicitly non-authoritative", async () => {
    stubJsonResponse({
      fqn: "main.sales.orders",
      nonAuthoritative: true,
      entries: [{
        action: "grant",
        actor: "reviewer@example.com",
      }],
      total: 1,
    });

    await expect(fetchGovernanceAuditTimeline("main.sales.orders")).resolves.toEqual({
      fqn: "main.sales.orders",
      entries: [],
      total: 0,
      nonAuthoritative: true,
    });
  });

  it("forwards page context (surface, assetFqn, active-filter scope) into the request body", async () => {
    stubJsonResponse({ answer: "ok", authoritative: true, evidence: [] });
    await fetchAxiomAiRecommendations("how many assets here lack an owner?", {
      context: { surface: "discovery", assetFqn: "", scope: { domain: ["Finance"], owner: "__unassigned__" } },
    });
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.context.surface).toBe("discovery");
    expect(body.context.scope).toEqual({ domain: ["Finance"], owner: "__unassigned__" });
    // An unfiltered call sends no context object at all.
    stubJsonResponse({ answer: "ok", authoritative: true, evidence: [] });
    await fetchAxiomAiRecommendations("hello");
    expect(JSON.parse(fetch.mock.calls[0][1].body).context).toBeUndefined();
  });

  it("fetchAiAutofill posts kind+context and returns drafted fields", async () => {
    stubJsonResponse({ kind: "glossaryTerm", fields: { definition: "A drafted definition.", domain: "Finance" }, model: "databricks-claude-sonnet-4-6", warnings: [] });
    const result = await fetchAiAutofill("glossaryTerm", { termName: "Net Revenue" });
    expect(result.fields).toEqual({ definition: "A drafted definition.", domain: "Finance" });
    expect(result.model).toBe("databricks-claude-sonnet-4-6");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.kind).toBe("glossaryTerm");
    expect(body.context.termName).toBe("Net Revenue");
  });

  it("polls Genie for progress stages and returns the final answer", async () => {
    // POST → pending; poll → pending (new stage); poll → final answer.
    const responses = [
      { intent: "genie-pending", conversationId: "c1", messageId: "m1", stage: "Submitted to Genie" },
      { intent: "genie-pending", conversationId: "c1", messageId: "m1", stage: "Selecting relevant tables" },
      { intent: "genie", answer: "Finance has 16 certified assets.", authoritative: true, evidence: [{}] },
    ];
    let idx = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        const payload = responses[Math.min(idx, responses.length - 1)];
        idx += 1;
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => payload,
          text: async () => JSON.stringify(payload),
        });
      }),
    );

    const stages = [];
    const result = await fetchAxiomAiRecommendations("How many certified assets in Finance?", {
      pollIntervalMs: 1,
      onStage: (stage) => stages.push(stage),
    });

    expect(result.answer).toBe("Finance has 16 certified assets.");
    expect(stages).toContain("Submitted to Genie");
    expect(stages).toContain("Selecting relevant tables");
    // POST + 2 polls
    expect(fetch.mock.calls.length).toBe(3);
    expect(fetch.mock.calls[1][0]).toContain("/axiom-ai/message");
  });

  it("returns an unavailable Axiom AI recommendation response for non-authoritative providers", async () => {
    stubJsonResponse({
      provider: "local-prototype-mock",
      recommendations: [{
        title: "Fake recommendation",
        detail: "Do not render.",
      }],
    });

    await expect(fetchAxiomAiRecommendations("recommend assets")).resolves.toEqual({
      recommendations: [],
      authoritative: false,
      nonAuthoritative: true,
      warning: "Axiom AI recommendations unavailable until live evidence-backed provider returns results.",
    });
  });

  it("returns an unavailable Axiom AI recommendation response for explicitly non-authoritative payloads", async () => {
    stubJsonResponse({
      nonAuthoritative: true,
      recommendations: [{
        title: "Unbacked recommendation",
        detail: "Do not render.",
      }],
    });

    await expect(fetchAxiomAiRecommendations("recommend assets")).resolves.toEqual({
      recommendations: [],
      authoritative: false,
      nonAuthoritative: true,
      warning: "Axiom AI recommendations unavailable until live evidence-backed provider returns results.",
    });
  });

  it("rejects populated Axiom AI recommendations from authoritative-false degraded live envelopes", async () => {
    stubJsonResponse({
      authoritative: false,
      state: "degraded",
      source: "databricks-genie",
      recommendations: [{
        title: "Genie text without evidence",
        detail: "Do not render.",
      }],
      evidence: [],
    });

    await expect(fetchAxiomAiRecommendations("recommend assets")).resolves.toEqual({
      recommendations: [],
      authoritative: false,
      nonAuthoritative: true,
      warning: "Axiom AI recommendations unavailable until live evidence-backed provider returns results.",
    });
  });
});

describe("insights API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("returns the Axiom envelope so degraded metadata reaches the Insights hook", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        insightsDashboard: "/axiom/insights",
      },
    };
    const envelope = {
      data: { kpis: [], scoring: { maturityFormula: [], availableSignals: [] } },
      meta: { state: "degraded", warnings: ["Quality health score is unavailable."] },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchInsightsDashboard()).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/insights",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("discovery + retired-endpoint contract guards", () => {
  // Regression guard for a live-observed stale-bundle class of bug: an older
  // client POSTed to /api/discovery/search (→ 405) and called removed endpoints
  // /api/discovery/facets and /api/insights/dashboard (→ 404). The current
  // contract consolidated all three — search is GET (facets ride inside its
  // payload) and insights moved to /axiom/insights. These lock the migration so
  // a stale endpoint call can't silently creep back in.
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("searches over GET /api/discovery/search (never POST → 405)", async () => {
    stubJsonResponse({ assets: [], count: 0, facets: {}, meta: {} });
    await fetchDiscoverySearch({ query: "revenue" });
    const [url, init] = globalThis.fetch.mock.calls[0];
    expect(String(url)).toContain("/api/discovery/search");
    expect(String(url)).toContain("query=revenue");
    // request() omits `method`, defaulting to GET; anything else means a 405.
    expect((init?.method || "GET").toUpperCase()).toBe("GET");
  });

  it("never targets the retired facets or insights-dashboard endpoints", async () => {
    stubJsonResponse({ assets: [], count: 0, facets: {}, meta: {} });
    await fetchDiscoverySearch({ query: "x", domains: ["Finance"] });
    await fetchInsightsDashboard();
    const calledUrls = globalThis.fetch.mock.calls.map((call) => String(call[0]));
    expect(calledUrls.length).toBeGreaterThan(0);
    for (const url of calledUrls) {
      expect(url).not.toContain("/api/discovery/facets");
      expect(url).not.toContain("/api/insights/dashboard");
    }
    // Insights resolves to the consolidated route, not the retired one.
    expect(calledUrls.some((url) => url.includes("/api/axiom/insights"))).toBe(true);
  });
});

describe("API error formatting", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("surfaces server and client request ids on ApiError messages", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({
        detail: "Forbidden",
        requestId: "server-request-123",
        meta: { requestId: "server-request-123" },
      }),
      text: async () => "",
    }));

    let caught = null;
    try {
      await fetchRuntimeStatus({ clientRequestId: "client-request-456" });
    } catch (error) {
      caught = error;
    }

    expect(caught).not.toBeNull();
    expect(caught.status).toBe(403);
    expect(caught.detailMessage).toBe("Forbidden");
    expect(caught.httpRequestId).toBe("server-request-123");
    expect(caught.clientRequestId).toBe("client-request-456");
    expect(caught.message).toBe(
      "Forbidden (Request ID: server-request-123; Client request ID: client-request-456)",
    );
    expect(formatApiError(caught)).toBe(caught.message);
  });

  it("keeps non-ApiError formatting usable without request metadata", () => {
    expect(formatApiError(new Error("Network unavailable"))).toBe("Network unavailable");
  });
});

describe("taxonomy API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("returns the Axiom envelope so taxonomy metadata and capabilities reach the page", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        taxonomyOverview: "/axiom/taxonomy/overview",
      },
    };
    const envelope = {
      data: {
        classifications: [],
        domains: [],
        dataProducts: [],
        columnGroups: [],
        glossaryTerms: [{ termId: "customer-id", term: "Customer Identifier" }],
        summary: { termCount: 1 },
      },
      meta: {
        state: "degraded",
        capabilities: { glossaryEnriched: true },
        warnings: ["Domain hierarchy is unavailable."],
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchTaxonomyOverview()).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/taxonomy/overview",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("CDE API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("returns the Axiom envelope for CDE dashboard metadata and degraded capabilities", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        cdeDashboard: "/axiom/cde",
      },
    };
    const envelope = {
      data: {
        summary: {
          totalCdes: 1,
          protectedCdes: null,
          sensitiveCandidates: 1,
          overdueReviews: null,
          domainsCovered: 1,
        },
        groups: [],
        items: [],
      },
      meta: {
        state: "degraded",
        capabilities: { controlCoverage: false },
        warnings: ["Dedicated CDE control coverage is unavailable."],
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchCdeDashboard()).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/cde",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("encodes CDE detail ids through the route contract and preserves the envelope", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        cdeDetail: "/axiom/cde/{cde_id}",
      },
    };
    const envelope = {
      data: {
        id: "main.customer.customer_dim",
        lineageSnapshot: { state: "unavailable" },
        controls: [],
        linkedAssets: [],
        activity: [],
      },
      meta: {
        state: "degraded",
        capabilities: { controlCoverage: false },
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchCdeDetail("main.customer.customer_dim")).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/cde/main.customer.customer_dim",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("Audit API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("encodes audit ids through the route contract and preserves the envelope", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        auditEvidence: "/axiom/audit/evidence",
      },
    };
    const envelope = {
      data: {
        summary: { totalChanges: 1, policyChanges: 0, approvals: 0, failedActions: 0 },
        events: [{ audit_id: "AUD-1", action: "metadata updated" }],
        selectedEvent: { audit_id: "AUD-1", action: "metadata updated" },
        evidence: { before: "{}", after: "{}", approvalChain: [], artifacts: [], linkedRequest: "" },
      },
      meta: {
        source: "governance-store+metadata-audit-log",
        state: "available",
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchAuditEvidence({ auditId: "AUD-1", limit: 25 })).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/audit/evidence?audit_id=AUD-1&limit=25",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("Admin API contract", () => {
  afterEach(() => {
    delete window.__AXIOM_BOOTSTRAP__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("returns the Admin control-center envelope from the bootstrap route contract", async () => {
    window.__AXIOM_BOOTSTRAP__ = {
      apiContract: {
        adminControlCenter: "/axiom/admin/control-center",
      },
    };
    const envelope = {
      data: {
        policyRequirements: { cards: [], byDomain: [] },
        integrations: [],
        recentAdminActivity: [],
      },
      meta: {
        source: "runtime-diagnostics+governance-store",
        state: "available",
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => envelope,
      text: async () => JSON.stringify(envelope),
    }));

    await expect(fetchAdminControlCenter()).resolves.toEqual(envelope);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/axiom/admin/control-center",
      expect.objectContaining({ method: "GET" }),
    );
  });
});
