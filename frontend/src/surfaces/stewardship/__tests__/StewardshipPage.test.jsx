import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast, ToastHost } from "../../../components/system";
import { axiomQueryClient } from "../../../lib/queryClient";
import StewardshipPage from "../StewardshipPage.jsx";

/*
 * surfaces/stewardship/__tests__/StewardshipPage.test.jsx — Wave C3.
 * Ports the meaningful contracts from the deleted GovernanceWorkspace +
 * InboxPage suites onto the rebuilt surface: triage flows (incl. failure
 * banners + rollback), bulk confirm, lens filters (?assignee=me is the
 * absorbed inbox), ?item deep links, scope captions, hydration honesty,
 * validation-seed rejection, and the merged term-review queue rows.
 */

/* ------------------------------------------------------------------ mocks */

const api = vi.hoisted(() => ({
  createGovernanceRequest: vi.fn(),
  fetchGovernanceGlossary: vi.fn(),
  fetchGovernanceRequestDetail: vi.fn(),
  fetchGovernanceWorkbench: vi.fn(),
  updateGovernanceRequest: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

/* --------------------------------------------------------------- fixtures */

const requestOne = {
  requestId: "SI-2491",
  title: "Owner missing",
  rawTitle: "Owner missing",
  kind: "Owner missing",
  type: "owner",
  status: "Pending",
  priority: "P1 critical",
  requester: "svc-governance-sweeper",
  createdAt: "2026-04-17T12:00:00Z",
  dueAt: "2026-04-24T12:00:00Z",
  assetFqn: "experimental.sandbox.pricing_experiment_2025q4",
  assetName: "pricing_experiment_2025q4",
  domain: "Revenue & Sales",
  assigned: "Revenue Stewards",
  sla: "4d overdue",
  slaState: "crit",
  age: "11d",
  detail: "Auto-flag: no owner set; queries detected from 3 users.",
  evidence: "Auto-flag: no owner set; queries detected from 3 users.",
  suggestedActions: [],
};

const requestTwo = {
  ...requestOne,
  requestId: "SI-2487",
  title: "Description missing",
  rawTitle: "Description missing",
  kind: "Description missing",
  type: "description",
  priority: "P2",
  assetFqn: "product_events.bronze.clickstream_events",
  assetName: "clickstream_events",
  domain: "Customer",
  assigned: "Customer Stewards",
  sla: "2d left",
  slaState: "warn",
  age: "5d",
  detail: "No steward-approved description is recorded.",
  evidence: "No steward-approved description is recorded.",
};

function workbenchFixture(overrides = {}) {
  return {
    requests: [requestOne, requestTwo],
    ...overrides,
  };
}

function glossaryFixture() {
  return {
    glossary: [
      { termId: "t-1", term: "Average Revenue", status: "Proposed", definition: "Avg revenue measure." },
      { termId: "t-2", term: "Axiom Test Term", status: "Draft", definition: "" },
      { termId: "t-3", term: "Net Revenue", status: "Approved", definition: "Approved term." },
    ],
  };
}

/* ---------------------------------------------------------------- harness */

let lastLocation = null;
function LocationProbe() {
  lastLocation = useLocation();
  return null;
}

const STEWARD = { email: "skyler.myers@shorecp.com", name: "Skyler Myers", role: "Steward" };

function renderPage({ initialEntry = "/stewardship", currentUser = STEWARD } = {}) {
  return render(
    <QueryClientProvider client={axiomQueryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <StewardshipPage currentUser={currentUser} />
        <ToastHost />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function primeHappyPath() {
  api.fetchGovernanceWorkbench.mockResolvedValue(workbenchFixture());
  api.fetchGovernanceGlossary.mockResolvedValue(glossaryFixture());
  api.fetchGovernanceRequestDetail.mockImplementation((requestId) =>
    Promise.resolve(
      [requestOne, requestTwo].find((item) => item.requestId === requestId) || requestOne,
    ),
  );
  api.updateGovernanceRequest.mockResolvedValue({ ok: true });
  api.createGovernanceRequest.mockResolvedValue({ ok: true, requestId: "REQ-NEW-42" });
}

async function settled() {
  await waitFor(() => {
    expect(screen.getAllByText("Owner missing").length).toBeGreaterThan(0);
  });
}

function panel() {
  return screen.getByRole("region", { name: "Work item detail" });
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  axiomQueryClient.clear();
  toast.clear();
  lastLocation = null;
});

/* ------------------------------------------------------------------ tests */

describe("StewardshipPage (surfaces/stewardship)", () => {
  it("shows loading placeholders while hydrating — never definitive zeros", () => {
    api.fetchGovernanceWorkbench.mockReturnValue(new Promise(() => {}));
    api.fetchGovernanceGlossary.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading the governance work queue…")).toBeTruthy();
    expect(screen.queryByText(/0 open work items/)).toBeNull();
    // Lens badges are placeholders, not zeros.
    const allTab = screen.getByRole("tab", { name: /All/ });
    expect(within(allTab).getByText("…")).toBeTruthy();
    expect(within(allTab).queryByText("0")).toBeNull();
  });

  it("renders the one queue: workbench requests AND term reviews with kind badges + real anchors", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    // Counts merge both sources: 2 requests + 2 review terms (approved
    // terms are not review work).
    expect(screen.getByText("4 open work items · 1 SLA breach")).toBeTruthy();

    // GOV id chips are real anchors to the canonical ?item deep link.
    const idChip = screen.getByRole("link", { name: /SI-2491/ });
    expect(idChip.getAttribute("href")).toBe("/stewardship?item=SI-2491");

    // Asset cells are EntityChips to the Asset 360 hub.
    const assetChip = screen.getAllByRole("link", {
      name: /experimental\.sandbox\.pricing_experiment_2025q4/,
    })[0];
    expect(assetChip.getAttribute("href")).toMatch(/^\/assets\//);

    // Absorbed Inbox: term reviews are typed rows linking to the glossary.
    expect(screen.getAllByText("Term review").length).toBe(2);
    expect(screen.getByText("Average Revenue")).toBeTruthy();
    expect(screen.queryByText("Net Revenue")).toBeNull();
    const termChip = screen.getByRole("link", { name: "t-1" });
    expect(termChip.getAttribute("href")).toBe("/glossary/t-1");
  });

  it("filters through the lens tabs and writes the lens/assignee URL params", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.click(screen.getByRole("tab", { name: /P1 critical/ }));
    expect(new URLSearchParams(lastLocation.search).get("lens")).toBe("p1");
    await waitFor(() => {
      expect(screen.queryByText("Description missing")).toBeNull();
    });
    expect(screen.getAllByText("Owner missing").length).toBeGreaterThan(0);
    expect(screen.queryByText("Average Revenue")).toBeNull();

    // "My work" is the absorbed inbox lens — a filter param, not a place.
    fireEvent.click(screen.getByRole("tab", { name: /My work/ }));
    expect(new URLSearchParams(lastLocation.search).get("assignee")).toBe("me");
    expect(new URLSearchParams(lastLocation.search).get("lens")).toBeNull();
  });

  it("treats /stewardship?assignee=me (the /inbox redirect target) as the active My-work lens", async () => {
    primeHappyPath();
    api.fetchGovernanceWorkbench.mockResolvedValue(
      workbenchFixture({
        requests: [requestOne, { ...requestTwo, assigned: "Skyler Myers" }],
      }),
    );
    renderPage({ initialEntry: "/stewardship?assignee=me" });

    await waitFor(() => {
      expect(screen.getAllByText("Description missing").length).toBeGreaterThan(0);
    });
    const mineTab = screen.getByRole("tab", { name: /My work/ });
    expect(mineTab.getAttribute("aria-selected")).toBe("true");
    // Only work assigned to the signed-in identity survives the lens.
    expect(screen.queryByText("Owner missing")).toBeNull();
  });

  it("opens the request mini-hub from a ?item= deep link", async () => {
    primeHappyPath();
    renderPage({ initialEntry: "/stewardship?item=SI-2487" });

    await waitFor(() => {
      expect(within(panel()).getByRole("heading", { name: "SI-2487" })).toBeTruthy();
    });
    expect(within(panel()).getAllByText("Description missing").length).toBeGreaterThan(0);
    // Target asset chip strip links to the hub.
    const assetChip = within(panel()).getAllByRole("link", {
      name: /product_events\.bronze\.clickstream_events/,
    })[0];
    expect(assetChip.getAttribute("href")).toMatch(/^\/assets\//);
  });

  it("says so honestly when a ?item deep link is not in the visible queue", async () => {
    primeHappyPath();
    renderPage({ initialEntry: "/stewardship?item=GOV-DEADBEEF" });
    await settled();

    expect(screen.getByText("Work item not found")).toBeTruthy();
    expect(screen.getByText(/GOV-DEADBEEF is not in the visible queue/)).toBeTruthy();
  });

  it("assigns the selected work item to the signed-in user through the PATCH API", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));

    await waitFor(() => {
      expect(api.updateGovernanceRequest).toHaveBeenCalledWith(
        "SI-2491",
        { status: "pending", assignee: "skyler.myers@shorecp.com", priority: "" },
        { fast: true },
      );
    });
    expect(await screen.findByText("Assigned to you (skyler.myers@shorecp.com).")).toBeTruthy();
  });

  it("sets priority from the triage picker through the PATCH API", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.change(screen.getByLabelText("Set work item priority"), { target: { value: "p2" } });

    await waitFor(() => {
      expect(api.updateGovernanceRequest).toHaveBeenCalledWith(
        "SI-2491",
        { status: "pending", assignee: "", priority: "p2" },
        { fast: true },
      );
    });
    expect(await screen.findByText("Priority set to P2.")).toBeTruthy();
  });

  it("resolves and comments through the PATCH API", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.click(within(panel()).getByRole("button", { name: "Comment" }));
    await waitFor(() => {
      expect(api.updateGovernanceRequest).toHaveBeenCalledWith(
        "SI-2491",
        { status: "pending", reviewNote: "Comment recorded from Stewardship." },
        { fast: true },
      );
    });
    expect(await screen.findByText("Comment recorded.")).toBeTruthy();

    fireEvent.click(within(panel()).getByRole("button", { name: "Resolve" }));
    await waitFor(() => {
      expect(api.updateGovernanceRequest).toHaveBeenLastCalledWith(
        "SI-2491",
        { status: "resolved", reviewNote: "Resolved from Stewardship." },
        { fast: true },
      );
    });
    expect(await screen.findByText("Work item resolved.")).toBeTruthy();
  });

  it("renders a failed triage PATCH as an error banner with human copy and rolls the queue back", async () => {
    // Persona-audit P0-adjacent: a backend 500 whose body carried
    // "TypeError: DualWriteGovernanceStore…" used to render verbatim inside
    // success-styled chrome.
    primeHappyPath();
    api.updateGovernanceRequest.mockRejectedValue(
      Object.assign(new Error("TypeError: DualWriteGovernanceStore.update_request() blew up"), {
        status: 500,
        detailMessage: "TypeError: DualWriteGovernanceStore.update_request() blew up",
        httpRequestId: "req-err-42",
      }),
    );
    renderPage();
    await settled();

    fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));

    const banner = await screen.findByText(
      "Couldn't update the assignment — the server rejected the change. (Request ID: req-err-42)",
    );
    expect(banner.closest(".ax-sys-status-banner")?.className).toContain("tone-danger");
    // The raw exception text never reaches the DOM.
    expect(screen.queryByText(/DualWriteGovernanceStore/)).toBeNull();
    // Rollback: the optimistic assignee never survives the failed write.
    expect(screen.queryByText(/Assigned to you/)).toBeNull();
    expect(screen.getAllByText("Revenue Stewards").length).toBeGreaterThan(0);
  });

  it("bulk-resolves selected work items behind an explicit confirm, one PATCH per request", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.click(screen.getByLabelText("Select SI-2491 for bulk actions"));
    fireEvent.click(screen.getByLabelText("Select SI-2487 for bulk actions"));
    expect(screen.getByText("2 selected")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Resolve selected" }));
    expect(screen.getByRole("alertdialog", { name: "Confirm bulk resolve" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm resolve" }));

    await waitFor(() => {
      expect(api.updateGovernanceRequest).toHaveBeenCalledWith(
        "SI-2491",
        { status: "resolved", reviewNote: "Bulk-resolved from Stewardship." },
        { fast: true },
      );
      expect(api.updateGovernanceRequest).toHaveBeenCalledWith(
        "SI-2487",
        { status: "resolved", reviewNote: "Bulk-resolved from Stewardship." },
        { fast: true },
      );
    });
    expect(await screen.findByText("2 work items resolved.")).toBeTruthy();
  });

  it("scopes the queue per asset and syncs the ?asset= URL param", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.change(screen.getByLabelText("Asset"), {
      target: { value: "product_events.bronze.clickstream_events" },
    });

    expect(new URLSearchParams(lastLocation.search).get("asset")).toBe(
      "product_events.bronze.clickstream_events",
    );
    await waitFor(() => {
      expect(screen.queryByText("Owner missing")).toBeNull();
    });
    expect(screen.getAllByText("Description missing").length).toBeGreaterThan(0);
    // Term reviews carry no target asset — an asset-scoped queue is honest
    // about only containing that asset's requests.
    expect(screen.queryByText("Average Revenue")).toBeNull();
  });

  it("keeps scoped empty states truthful instead of inventing requests", async () => {
    primeHappyPath();
    renderPage({ initialEntry: "/stewardship?asset=emet.demo.unrelated_asset" });
    await waitFor(() => {
      expect(screen.getByText("No work items for this asset")).toBeTruthy();
    });
    expect(
      screen.getByText("No open work items target emet.demo.unrelated_asset."),
    ).toBeTruthy();
    expect(screen.getByText(/SLA evidence unavailable/)).toBeTruthy();
    expect(screen.getByText("No work item selected")).toBeTruthy();
  });

  it("renders the openRequestScope split so visible vs out-of-scope counts cannot be confused", async () => {
    primeHappyPath();
    api.fetchGovernanceWorkbench.mockResolvedValue(
      workbenchFixture({
        openRequestScope: {
          totalOpen: 2,
          scope: "all-requests",
          visibleOpenCount: 1,
          outOfScopeOpenCount: 1,
          outOfScopeAssetCount: 1,
          caption: "1 target asset outside the visible estate",
        },
      }),
    );
    renderPage();
    await settled();

    expect(
      screen.getByText(
        "2 open change requests: 1 in the visible estate · 1 on out-of-scope assets (1 target asset outside the visible estate)",
      ),
    ).toBeTruthy();
  });

  it("disables triage and creation for reader actors with the role reason", async () => {
    primeHappyPath();
    renderPage({ currentUser: { email: "reader@example.com", name: "Reader", role: "Reader" } });
    await settled();

    expect(
      screen.getByText("Triage and resolve require Steward or Admin role. Current actor role: Reader."),
    ).toBeTruthy();
    expect(within(panel()).getByRole("button", { name: "Comment" }).disabled).toBe(true);
    expect(within(panel()).getByRole("button", { name: "Resolve" }).disabled).toBe(true);
    fireEvent.click(within(panel()).getByRole("button", { name: "Resolve" }));
    expect(api.updateGovernanceRequest).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "New work item" }));
    fireEvent.change(screen.getByLabelText("New work item asset FQN"), {
      target: { value: "main.sales.orders" },
    });
    fireEvent.change(screen.getByLabelText("New work item title"), {
      target: { value: "Anything" },
    });
    const submit = screen.getByRole("button", { name: "Create work item" });
    expect(submit.disabled).toBe(true);
    expect(submit.title).toMatch(/requires Writer, Steward, or Admin role/);
    fireEvent.click(submit);
    expect(api.createGovernanceRequest).not.toHaveBeenCalled();
  });

  it("files a real governance request from the New work item dialog", async () => {
    primeHappyPath();
    renderPage();
    await settled();

    fireEvent.click(screen.getByRole("button", { name: "New work item" }));
    fireEvent.change(screen.getByLabelText("New work item asset FQN"), {
      target: { value: "main.sales.orders" },
    });
    fireEvent.change(screen.getByLabelText("New work item title"), {
      target: { value: "Add a steward-approved description" },
    });
    fireEvent.change(screen.getByLabelText("New work item note"), {
      target: { value: "Flagged during discovery review." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create work item" }));

    await waitFor(() => {
      expect(api.createGovernanceRequest).toHaveBeenCalledWith(
        {
          assetFqn: "main.sales.orders",
          title: "Add a steward-approved description",
          note: "Flagged during discovery review.",
        },
        { fast: true },
      );
    });
    expect(await screen.findByText(/Work item created/)).toBeTruthy();
  });

  it("filters validation seed rows from the live queue", async () => {
    primeHappyPath();
    api.fetchGovernanceWorkbench.mockResolvedValue(
      workbenchFixture({
        requests: [
          {
            ...requestOne,
            requestId: "ax-home-seed-request-9",
            id: "ax-home-seed-request-9",
            title: "Validation sample owner check",
            rawTitle: "Validation sample owner check",
            kind: "Validation sample owner check",
            source: "validation_seed",
            validationSample: true,
          },
          requestOne,
        ],
      }),
    );
    api.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
    renderPage();
    await settled();

    expect(screen.getByText("1 open work item · 1 SLA breach")).toBeTruthy();
    expect(screen.queryByText("Validation sample owner check")).toBeNull();
  });

  it("rejects prototype stewardship payloads instead of rendering them as product data", async () => {
    primeHappyPath();
    api.fetchGovernanceWorkbench.mockResolvedValue(
      workbenchFixture({
        meta: { source: "prototype-mock", warnings: ["not live Databricks evidence"] },
      }),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Live work-item evidence unavailable")).toBeTruthy();
    });
    expect(screen.queryByText("Owner missing")).toBeNull();
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });

  it("compresses long request ids to GOV-XXXXXXXX and keeps the full id reachable", async () => {
    const longId = "9f8e7d6c-5b4a-3921-8076-54efab321098";
    const longItem = { ...requestOne, requestId: longId, id: longId };
    primeHappyPath();
    api.fetchGovernanceWorkbench.mockResolvedValue(workbenchFixture({ requests: [longItem] }));
    api.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
    api.fetchGovernanceRequestDetail.mockResolvedValue(longItem);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderPage();
    await settled();

    expect(screen.getAllByText("GOV-9F8E7D6C").length).toBeGreaterThan(0);
    const heading = within(panel()).getByRole("heading", { name: "GOV-9F8E7D6C" });
    expect(heading.getAttribute("title")).toBe(longId);

    fireEvent.click(screen.getByRole("button", { name: "Copy ID" }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(longId);
    });
    expect(await screen.findByText("Request ID copied.")).toBeTruthy();
  });

  it("renders an honest retryable error when the workbench cannot load at all", async () => {
    api.fetchGovernanceWorkbench.mockRejectedValue(new Error("Governance store unavailable"));
    api.fetchGovernanceGlossary.mockResolvedValue({ glossary: [] });
    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText("Unable to load the governance work queue right now."),
      ).toBeTruthy();
    });
    // Human copy only — never the raw transport error text.
    expect(screen.queryByText("Governance store unavailable")).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
