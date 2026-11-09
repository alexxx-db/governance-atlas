import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "../../../components/system";
import EvidencePage from "../EvidencePage";

/*
 * Wave-C5 contract tests for the NEW quality-findings tab of the unified
 * Evidence surface (PRODUCT J6/J7). Asserts the deep-link contract Home's
 * risk drills and the Asset 360 Quality tab depend on:
 *   /evidence?tab=quality&severity=high  ·  &asset=<fqn>  ·  &run=<runId>
 * plus stable QF ids, visibility-scoped captions, UTC evidence stamps, run
 * detail, and the honest empty/unavailable split.
 */

const api = vi.hoisted(() => ({
  fetchAuditEvidence: vi.fn(),
  fetchAuditEvents: vi.fn(),
  fetchQualityFindings: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

const shell = { userEmail: "abarreto@shorecp.com", role: "admin" };

function finding(findingId, overrides = {}) {
  return {
    findingId,
    resultId: `${findingId.toLowerCase()}-result-uuid`,
    runId: "run-1",
    executedAt: "2026-07-20T10:00:00Z",
    assetFqn: "main.customer.customer_dim",
    columnName: "customer_id",
    caseId: "GOV-QUALITY-EVIDENCE-case-customer-profile-minimum-rows",
    checkName: "Customer profile coverage has source records",
    checkNameSource: "definition",
    testKey: "row_count",
    outcome: "failed",
    severity: "critical",
    severityLevel: "high",
    message: "row count 0 below minimum 1",
    metricValue: 0,
    thresholdValue: 1,
    run: {
      runId: "run-1",
      suiteId: "suite-1",
      trigger: "manual",
      status: "partial",
      startedAt: "2026-07-20T09:59:00Z",
      finishedAt: "2026-07-20T10:00:10Z",
    },
    ...overrides,
  };
}

function findingsPayload(findings, overrides = {}) {
  return {
    findings,
    summary: {
      total: findings.length,
      returned: findings.length,
      outcomes: { passed: 1, failed: 1, errored: 0, skipped: 0 },
      evidenceAt: "2026-07-20T10:00:05Z",
      source: "quality_run_results",
    },
    state: "available",
    reason: "",
    windowTruncated: false,
    visibilityScopedRowsExcluded: 0,
    meta: { state: "available", source: "quality-runner+governance-store", authoritative: true },
    ...overrides,
  };
}

function renderPage(initialUrl = "/evidence?tab=quality") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <EvidencePage shell={shell} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  toast.clear();
  api.fetchAuditEvidence.mockResolvedValue({
    data: { summary: {}, events: [] },
    meta: { state: "available", authoritative: true, source: "governance-store+metadata-audit-log" },
  });
  api.fetchAuditEvents.mockResolvedValue([]);
  api.fetchQualityFindings.mockResolvedValue(
    findingsPayload([
      finding("QF-A1B2C3D4"),
      finding("QF-FFE2C3D4", {
        runId: "run-2",
        caseId: "case-two",
        checkName: "Case Two",
        checkNameSource: "case-id",
        outcome: "passed",
        severity: "info",
        severityLevel: "informational",
        message: "",
        columnName: "",
        executedAt: "2026-07-20T10:00:05Z",
        run: null,
      }),
    ]),
  );
});

afterEach(() => {
  cleanup();
});

describe("Evidence quality tab", () => {
  it("honors the risk-drill deep link: ?tab=quality&severity=high hits the API with the bucket filter", async () => {
    renderPage("/evidence?tab=quality&severity=high");
    await waitFor(() => {
      expect(api.fetchQualityFindings).toHaveBeenCalledWith(
        expect.objectContaining({ severity: "high", since: expect.any(String) }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    // Stable QF ids render as real row anchors (?finding= address).
    const anchor = await screen.findByRole("link", { name: "QF-A1B2C3D4" });
    expect(anchor.getAttribute("href")).toContain("finding=QF-A1B2C3D4");
    expect(anchor.getAttribute("href")).toContain("severity=high");
  });

  it("renders finding rows with check names, severity badges, outcomes, UTC stamps and honest messages", async () => {
    renderPage();
    await screen.findByRole("link", { name: "QF-A1B2C3D4" });
    const table = screen.getByRole("table", { name: "Quality findings" });
    expect(within(table).getAllByText("High").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("Failed").length).toBeGreaterThan(0);
    expect(within(table).getByText("2026-07-20 10:00:00")).toBeTruthy();
    expect(within(table).getByText("row count 0 below minimum 1")).toBeTruthy();
    // Empty evaluator messages stay honest, never synthesized prose.
    expect(within(table).getByText("No evaluator message recorded")).toBeTruthy();
    // Derived check names carry their honesty marker.
    expect(within(table).getByText("name derived from case id")).toBeTruthy();
    // Asset mentions are real EntityChip anchors into the hub.
    const assetLinks = within(table).getAllByRole("link", { name: /main\.customer\.customer_dim/ });
    expect(assetLinks[0].getAttribute("href")).toContain("/assets/main.customer.customer_dim");
  });

  it("threads ?asset= deep links into the API and the caption", async () => {
    renderPage("/evidence?tab=quality&asset=main.customer.customer_dim");
    await waitFor(() => {
      expect(api.fetchQualityFindings).toHaveBeenCalledWith(
        expect.objectContaining({ asset: "main.customer.customer_dim" }),
        expect.anything(),
      );
    });
    await screen.findByText(/Showing 2 findings in the last 30 days/);
    expect(screen.getByText(/Latest evidence/)).toBeTruthy();
  });

  it("selects the deep-linked ?finding= and shows its run detail in the rail", async () => {
    renderPage("/evidence?tab=quality&finding=QF-A1B2C3D4");
    await screen.findByRole("link", { name: "QF-A1B2C3D4" });
    const rail = screen.getByLabelText("Quality run detail");
    expect(within(rail).getByText("Customer profile coverage has source records")).toBeTruthy();
    expect(within(rail).getByText("QF-A1B2C3D4")).toBeTruthy();
    // Full result UUID rides on the title attribute.
    expect(within(rail).getByText("QF-A1B2C3D4").getAttribute("title")).toBe("qf-a1b2c3d4-result-uuid");
    expect(within(rail).getByText("run-1")).toBeTruthy();
    expect(within(rail).getByText("Manual")).toBeTruthy();
    expect(within(rail).getByText("Partial")).toBeTruthy();
    expect(within(rail).getByText("Jul 20, 2026, 09:59 UTC")).toBeTruthy();
    // Column mention is a real chip into the hub's schema tab.
    const columnLink = within(rail).getByRole("link", { name: /customer_id/ });
    expect(columnLink.getAttribute("href")).toContain("tab=columns");
  });

  it("is honest about a finding whose run metadata was not reported", async () => {
    renderPage("/evidence?tab=quality&finding=QF-FFE2C3D4");
    await screen.findByRole("link", { name: "QF-A1B2C3D4" });
    const rail = screen.getByLabelText("Quality run detail");
    expect(within(rail).getByText(/Run metadata was not reported for this finding \(run run-2\)/)).toBeTruthy();
  });

  it("filters to one run via ?run= with an honest caption and clear affordance", async () => {
    renderPage("/evidence?tab=quality&run=run-2");
    await screen.findByText(/Run filter active · showing findings recorded by quality run run-2/);
    await screen.findByText(/Showing 1 finding from run run-2/);
    expect(screen.queryByRole("link", { name: "QF-A1B2C3D4" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Clear run filter" }));
    await screen.findByRole("link", { name: "QF-A1B2C3D4" });
  });

  it("renders the honest in-range empty state when filters match nothing", async () => {
    api.fetchQualityFindings.mockResolvedValue(
      findingsPayload([], {
        state: "unavailable",
        reason: "No quality findings match the requested filters.",
        summary: { total: 0, outcomes: { passed: 0, failed: 0, errored: 0, skipped: 0 }, evidenceAt: "" },
      }),
    );
    renderPage("/evidence?tab=quality&severity=high");
    await screen.findByText("No quality findings in range");
    expect(screen.getByText(/No quality findings match the requested filters/)).toBeTruthy();
    // The widen affordance drives the same URL-addressed window.
    fireEvent.click(screen.getByRole("button", { name: "Widen to 90 days" }));
    await waitFor(() => {
      expect(api.fetchQualityFindings).toHaveBeenCalledWith(
        expect.objectContaining({ severity: "high", since: expect.any(String) }),
        expect.anything(),
      );
    });
  });

  it("distinguishes 'no checks have run yet' from an unavailable ledger", async () => {
    api.fetchQualityFindings.mockResolvedValue(
      findingsPayload([], {
        state: "unavailable",
        reason:
          "No quality checks have run yet. Configure expectations from an asset's Quality tab to activate this feed.",
        summary: null,
      }),
    );
    renderPage();
    await screen.findByText("No quality checks have run yet");

    cleanup();
    api.fetchQualityFindings.mockResolvedValue(
      findingsPayload([], {
        state: "unavailable",
        reason: "Quality run ledger is not available from the governance store.",
        summary: null,
      }),
    );
    renderPage();
    await screen.findByText("Quality findings unavailable");
    expect(screen.getByText(/Quality run ledger is not available/)).toBeTruthy();
  });

  it("counts visibility-scoped exclusions instead of silently shrinking the feed", async () => {
    api.fetchQualityFindings.mockResolvedValue(
      findingsPayload([finding("QF-A1B2C3D4")], { visibilityScopedRowsExcluded: 1 }),
    );
    renderPage();
    await screen.findByText(/1 finding about assets outside your visibility scope withheld/);
  });

  it("shows an unavailable state with retry when the findings request itself fails", async () => {
    api.fetchQualityFindings.mockRejectedValue(new Error("quality endpoint failed"));
    renderPage();
    await screen.findByText("Quality findings unavailable");
    expect(screen.getByText("quality endpoint failed")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("reaches the quality tab from the events tab through the URL-bound tab strip", async () => {
    renderPage("/evidence");
    await screen.findByRole("tab", { name: "Quality findings" });
    fireEvent.click(screen.getByRole("tab", { name: "Quality findings" }));
    await waitFor(() => {
      expect(api.fetchQualityFindings).toHaveBeenCalled();
    });
    await screen.findByRole("link", { name: "QF-A1B2C3D4" });
  });
});
