import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AiGovernancePage from "../AiGovernancePage";

/*
 * /ai surface contract: honest states (loading, empty-but-observed,
 * degraded with named sources, unavailable with "—" tiles), provenance on
 * every row, steward-only findings and import, and audited action flows that
 * require reasons.
 */

const api = vi.hoisted(() => ({
  fetchAiSummary: vi.fn(),
  fetchAiInventory: vi.fn(),
  fetchAiFindings: vi.fn(),
  fetchAiIntake: vi.fn(),
  fetchAiAsset: vi.fn(),
  patchAiFinding: vi.fn(),
  confirmAiFindingMatch: vi.fn(),
  importAiIntake: vi.fn(),
  formatApiError: (error, fallback) => error?.message || fallback,
}));
vi.mock("../../../lib/api", () => api);

const EP = "a".repeat(32);
const RUN = { runId: "dbx-42", status: "succeeded", finishedAt: "2026-09-24T06:05:00Z" };

function meta(state = "available", warnings = [], unavailableReason = "") {
  return { state, source: "governance-store:ai", authoritative: true, warnings, unavailableReason };
}

const SUMMARY = {
  summary: {
    assetCount: 3,
    assetsByKind: { serving_endpoint: 1, external_model: 1, mcp_server: 1 },
    findings: { open: 4, openByType: {}, openBySeverity: {} },
    shadowAi: 2,
    ambiguousMatches: 1,
    posture: { coverage: 0.5 },
  },
  availability: { state: "available", run: RUN, sources: {} },
  meta: meta(),
};

const ROW = {
  entityId: EP,
  entityKind: "serving_endpoint",
  name: "chat-claude",
  sourceEntityId: "ep1",
  provider: "anthropic",
  owner: "owner@example.com",
  tier: "high",
  reconciliationState: "orphaned",
  openFindings: 2,
  posture: "partial",
  provenance: { sourceSystem: "databricks", collector: "dbx_ai_collector", collectorVersion: "1.0.0", runId: "dbx-42", observedAt: "2026-09-24T06:00:00Z", provenanceClass: "sample" },
};

const FINDING = {
  findingId: "f".repeat(64),
  findingType: "ambiguous_match",
  severity: "low",
  state: "open",
  entityId: EP,
  intakeId: "INT-1",
  matchRule: "M3",
  matchScore: 0.86,
  lastSeenAt: "2026-09-24T06:05:00Z",
  lastRunId: "dbx-42",
  evidence: {
    reason: "More than one intake could describe this asset.",
    assetName: "chat-claude",
    candidates: [{ intakeId: "INT-1", score: 0.86 }],
    provenance: ROW.provenance,
  },
};

function renderPage(url = "/ai", shell = { role: "steward", userEmail: "s@example.com" }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AiGovernancePage shell={shell} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((fn) => typeof fn?.mockReset === "function" && fn.mockReset());
  api.fetchAiSummary.mockResolvedValue(SUMMARY);
  api.fetchAiInventory.mockResolvedValue({ items: [ROW], total: 1, availability: SUMMARY.availability, meta: meta() });
  api.fetchAiFindings.mockResolvedValue({ items: [FINDING], total: 1, meta: meta() });
  api.fetchAiIntake.mockResolvedValue({ items: [], total: 0, meta: meta() });
  api.patchAiFinding.mockResolvedValue({ finding: { ...FINDING, state: "suppressed" } });
  api.confirmAiFindingMatch.mockResolvedValue({ finding: { ...FINDING, state: "resolved" } });
});

afterEach(() => cleanup());

describe("AiGovernancePage", () => {
  it("renders tiles and inventory rows with provenance and sample labels", async () => {
    renderPage();
    expect(await screen.findByText("chat-claude")).toBeTruthy();
    expect(screen.getByText("Shadow AI")).toBeTruthy();
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getAllByText("run dbx-42").length).toBeGreaterThan(0);
    expect(screen.getByText("Sample")).toBeTruthy();
    expect(screen.getByText("chat-claude").closest("a").getAttribute("href")).toBe(`/ai/assets/${EP}`);
    expect(screen.getByText(/Last completed reconciliation run dbx-42/)).toBeTruthy();
  });

  it("shows dashes, not zeros, and the reason when no run has completed", async () => {
    const reason = "No AI reconciliation run has completed yet. Run the atlas-ai-collect-and-reconcile job.";
    api.fetchAiSummary.mockResolvedValue({
      summary: { assetCount: null, shadowAi: null, ambiguousMatches: null, posture: null, findings: null },
      availability: { state: "unavailable", run: null },
      meta: meta("unavailable", [reason], reason),
    });
    api.fetchAiInventory.mockResolvedValue({ items: [], total: null, meta: meta("unavailable", [reason], reason) });
    renderPage();
    expect((await screen.findAllByText(reason)).length).toBeGreaterThan(0);
    const tiles = screen.getByText("AI assets").closest(".ga-sys-stat-tile");
    expect(within(tiles).getByText("—")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("names degraded sources in the availability banner", async () => {
    const warning = "registered_models was degraded in run dbx-42: 3 model(s) unreadable";
    api.fetchAiSummary.mockResolvedValue({ ...SUMMARY, meta: meta("degraded", [warning]) });
    renderPage();
    expect(await screen.findByText("Data availability is limited")).toBeTruthy();
    expect(screen.getByText(new RegExp("registered_models was degraded"))).toBeTruthy();
  });

  it("discloses known gaps without a degraded banner", async () => {
    api.fetchAiSummary.mockResolvedValue({
      ...SUMMARY,
      availability: { ...SUMMARY.availability, notes: ["ai_asset_registry (not supported): No AI asset registry API"] },
    });
    renderPage();
    expect(await screen.findByText(/Not collected: ai_asset_registry \(not supported\)/)).toBeTruthy();
    expect(screen.queryByText("Data availability is limited")).toBeNull();
  });

  it("distinguishes an observed-empty inventory from a failed one", async () => {
    api.fetchAiInventory.mockResolvedValue({ items: [], total: 0, meta: meta() });
    renderPage();
    expect(await screen.findByText("No AI assets observed")).toBeTruthy();
  });

  it("hides findings and import from readers", async () => {
    renderPage("/ai?tab=findings", { role: "reader" });
    expect(await screen.findByText("chat-claude")).toBeTruthy(); // fell back to inventory
    expect(screen.queryByRole("tab", { name: /Findings/ })).toBeNull();
    expect(api.fetchAiFindings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("tab", { name: /Intake/ }));
    await screen.findByText("No intake records");
    expect(screen.queryByText("Import CSV")).toBeNull();
  });

  it("requires a reason to suppress, then calls the audited API", async () => {
    renderPage(`/ai?tab=findings&finding=${FINDING.findingId}`);
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("More than one intake could describe this asset.")).toBeTruthy();
    expect(within(drawer).getByText("INT-1: score 0.86")).toBeTruthy();
    fireEvent.click(within(drawer).getByText("Suppress"));
    const submit = within(drawer).getByRole("button", { name: "Suppress" });
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(drawer).getByLabelText("Suppression reason (required)"), { target: { value: "Known pilot" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Suppress" }));
    await waitFor(() =>
      expect(api.patchAiFinding).toHaveBeenCalledWith(FINDING.findingId, { action: "suppress", note: "", reason: "Known pilot", assigneeEmail: "" }),
    );
  });

  it("offers only Reopen on a closed finding", async () => {
    api.fetchAiFindings.mockResolvedValue({ items: [{ ...FINDING, state: "suppressed" }], total: 1, meta: meta() });
    renderPage(`/ai?tab=findings&findingState=suppressed&finding=${FINDING.findingId}`);
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByText("Resolve")).toBeNull();
    fireEvent.click(within(drawer).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(api.patchAiFinding).toHaveBeenCalledWith(FINDING.findingId, { action: "reopen", note: "", reason: "", assigneeEmail: "" }));
  });

  it("says when findings are truncated or a deep link is filtered out", async () => {
    api.fetchAiFindings.mockResolvedValue({ items: [FINDING], total: 450, meta: meta() });
    renderPage("/ai?tab=findings&finding=" + "a".repeat(64));
    expect(await screen.findByText(/Showing 1 of 450/)).toBeTruthy();
    expect(screen.getByText(/The linked finding is not in this view/)).toBeTruthy();
  });

  it("confirms a match to the chosen intake", async () => {
    renderPage(`/ai?tab=findings&finding=${FINDING.findingId}`);
    const drawer = await screen.findByRole("dialog");
    fireEvent.click(within(drawer).getByText("Confirm match"));
    fireEvent.click(within(drawer).getByRole("button", { name: "Confirm match" }));
    await waitFor(() => expect(api.confirmAiFindingMatch).toHaveBeenCalledWith(FINDING.findingId, { intakeId: "INT-1", note: "" }));
  });

  it("imports intake only after a clean dry run and an explicit confirmation", async () => {
    api.importAiIntake.mockImplementation((csvText, mode) =>
      Promise.resolve(
        mode === "dry_run"
          ? { ok: true, summary: { total: 1, valid: 1, invalid: 0 }, results: [], parseErrors: [] }
          : { ok: true, summary: { total: 1, valid: 1, invalid: 0 }, committed: { created: 1, updated: 0, unchanged: 0 } },
      ),
    );
    renderPage("/ai?tab=intake");
    fireEvent.click(await screen.findByText("Import CSV"));
    const drawer = await screen.findByRole("dialog");
    const commit = within(drawer).getByRole("button", { name: "Commit" });
    expect(commit.disabled).toBe(true);
    fireEvent.change(within(drawer).getByLabelText("CSV text"), { target: { value: "intake_id,title,state,owner\nI1,t,approved,a@b.co" } });
    fireEvent.click(within(drawer).getByText("Validate (dry run)"));
    await within(drawer).findByText("1 valid, 0 invalid of 1 rows");
    fireEvent.click(within(drawer).getByRole("button", { name: "Commit" }));
    fireEvent.click(within(drawer).getByRole("button", { name: /Confirm import of 1 rows/ }));
    await waitFor(() => expect(api.importAiIntake).toHaveBeenLastCalledWith(expect.stringContaining("I1"), "commit"));
  });
});
