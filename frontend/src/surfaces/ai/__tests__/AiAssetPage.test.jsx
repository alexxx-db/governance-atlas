import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AiAssetPage from "../AiAssetPage";

const api = vi.hoisted(() => ({ fetchAiAsset: vi.fn() }));
vi.mock("../../../lib/api", () => api);

const ID = "b".repeat(32);

const ASSET = {
  entityId: ID,
  entityKind: "external_model",
  name: "chat-claude / claude",
  sourceEntityId: "ep1/claude",
  reconciliationState: "matched",
  posture: "unknown",
  provenance: { sourceSystem: "databricks", collector: "dbx_ai_collector", collectorVersion: "1.0.0", runId: "dbx-42", observedAt: "2026-09-24T06:00:00Z", provenanceClass: "organic" },
  declared: {
    intakeId: "INT-1",
    title: "Claims summarizer",
    authority: "registry",
    via: "parent",
    provenance: { ingestSource: "csv", ingestRunId: "csv-abc", updatedAt: "2026-09-20T00:00:00Z", provenanceClass: "organic" },
  },
  diff: [
    { field: "provider", declared: "openai", observed: "anthropic", differs: true },
    { field: "owner", declared: "a@b.co", observed: "a@b.co", differs: false },
  ],
  controls: [
    { controlId: "AIC-09", title: "External provider credentials use a secret reference", status: "unknown", signalSource: "serving_endpoints", evidence: { reason: "credential configuration is not exposed by the serving API" }, runId: "dbx-42" },
  ],
  findings: [],
  relationships: [],
  history: [{ eventId: "e1", eventType: "ai.registry.state_changed", actorEmail: "collector", source: "system", status: "emitted", occurredAt: "2026-09-24T06:05:00Z" }],
  config: { provider: "anthropic" },
};

function renderPage(shell = { role: "reader" }, url = `/ai/assets/${ID}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AiAssetPage entityId={ID} shell={shell} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.fetchAiAsset.mockReset();
  api.fetchAiAsset.mockResolvedValue({ asset: ASSET, meta: { state: "available", source: "governance-store:ai", authoritative: true, warnings: [] } });
});
afterEach(() => cleanup());

describe("AiAssetPage", () => {
  it("shows declared versus observed with provenance and highlighted differences", async () => {
    renderPage();
    expect(await screen.findByText("Declared (intake)")).toBeTruthy();
    expect(screen.getByText("Via parent endpoint")).toBeTruthy();
    expect(screen.getByText("csv-abc")).toBeTruthy();
    expect(screen.getByText("dbx-42")).toBeTruthy();
    const providerRow = screen.getByText("openai").closest("tr");
    expect(providerRow.className).toContain("is-different");
    expect(screen.getAllByText("a@b.co")[0].closest("tr").className).not.toContain("is-different");
    expect(screen.queryByText("Configuration (redacted)")).toBeNull(); // readers never see config
  });

  it("renders unknown controls with the unobservable source", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Controls" }));
    expect(
      screen.getByText("Unknown: signal not observable from serving_endpoints (credential configuration is not exposed by the serving API)"),
    ).toBeTruthy();
  });

  it("labels later-release tabs honestly and shows config to stewards", async () => {
    renderPage({ role: "steward" });
    expect(await screen.findByText("Configuration (redacted)")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Usage" }));
    expect(screen.getByText("Available in a later release")).toBeTruthy();
  });

  it("explains a missing asset instead of a blank page", async () => {
    const error = Object.assign(new Error("AI asset not found in the latest completed run."), { status: 404 });
    api.fetchAiAsset.mockRejectedValue(error);
    renderPage();
    expect(await screen.findByText("AI asset not found")).toBeTruthy();
  });

  it("does not claim a reader's asset has no findings when the API withholds them", async () => {
    api.fetchAiAsset.mockResolvedValue({ asset: { ...ASSET, findings: null }, meta: { state: "available", source: "governance-store:ai", authoritative: true, warnings: [] } });
    renderPage();
    expect(await screen.findByText("Findings are visible to stewards and admins.")).toBeTruthy();
    expect(screen.queryByText("No findings reference this asset.")).toBeNull();
  });
});
