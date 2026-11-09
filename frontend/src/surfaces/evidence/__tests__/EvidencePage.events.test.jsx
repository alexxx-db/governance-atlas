import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast, ToastHost } from "../../../components/system";
import EvidencePage from "../EvidencePage";

/*
 * Wave-C5 contract tests for the audit-events tab of the unified Evidence
 * surface. Ports the meaningful assertions from the deleted
 * AuditBrowserWorkspace suites onto the new contract: URL-addressed filters
 * (?actor/?action/?asset/?q/?range/?kind), ?event=AUD-<hex8> selection,
 * stable AUD ids as real anchors, truncation/exclusion captions, exports
 * carrying their own completeness warnings, and hydration honesty.
 */

const api = vi.hoisted(() => ({
  fetchAuditEvidence: vi.fn(),
  fetchAuditEvents: vi.fn(),
  fetchQualityFindings: vi.fn(),
}));

vi.mock("../../../lib/api", () => api);

const shell = { userEmail: "abarreto@shorecp.com", role: "admin" };

function auditEvent(id, overrides = {}) {
  return {
    audit_id: id,
    displayAuditId: id,
    auditEventId: `${id.toLowerCase()}-full-uuid`,
    entity_fqn: "main.customer.customer_dim",
    entity_type: "table",
    action: "metadata updated",
    status: "success",
    detail: "Owner changed",
    created_at: "2026-07-19T12:00:00Z",
    actor_email: "abarreto@shorecp.com",
    ...overrides,
  };
}

function envelope(events, summaryOverrides = {}, metaOverrides = {}) {
  return {
    data: {
      summary: {
        totalChanges: events.length,
        policyViolations: 0,
        governanceRequests: { label: "Governance requests", open: null, resolved: null, source: "" },
        lastEventAt: "",
        hiddenRowsExcluded: 0,
        sourceTable: "main.governance.metadata_audit_log",
        summarySource: "governance audit log",
        ...summaryOverrides,
      },
      events,
    },
    meta: {
      state: "available",
      authoritative: true,
      source: "governance-store+metadata-audit-log",
      ...metaOverrides,
    },
  };
}

function renderPage(initialUrl = "/evidence", pageShell = shell) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialUrl]}>
        <EvidencePage shell={pageShell} />
        <ToastHost />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  toast.clear();
  api.fetchAuditEvidence.mockResolvedValue(envelope([auditEvent("AUD-0001")]));
  api.fetchAuditEvents.mockResolvedValue([]);
  api.fetchQualityFindings.mockResolvedValue({ findings: [], summary: null, state: "unavailable", reason: "" });
});

afterEach(() => {
  cleanup();
});

describe("Evidence events tab", () => {
  it("renders backed KPI tiles with the governance-request backlog aging", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([auditEvent("AUD-0001")], {
        events24h: 2184,
        policyViolations: 4,
        governanceRequests: {
          label: "Governance requests",
          open: 2,
          resolved: 5,
          source: "governance change requests",
          oldestOpenCreatedAt: "2026-05-05T02:26:52Z",
        },
      }),
    );
    renderPage();
    await screen.findByText("2,184");
    const policyTile = screen.getByText("Policy violations").closest("article");
    expect(within(policyTile).getByText("4")).toBeTruthy();
    const requestsTile = screen.getByText("Governance requests · open").closest("article");
    expect(within(requestsTile).getByText("2")).toBeTruthy();
    expect(
      screen.getByText("5 resolved · oldest open since May 5, 2026 · governance change requests"),
    ).toBeTruthy();
    // Retention and access-review tiles stay dead — they were never backed.
    expect(screen.queryByText(/Access reviews/)).toBeNull();
    expect(screen.queryByText("Retention")).toBeNull();
  });

  it("shows guidance and a 90d switch when the default range is empty", async () => {
    api.fetchAuditEvidence.mockResolvedValue(envelope([], { lastEventAt: "2026-07-01T08:30:00Z" }));
    renderPage();
    await screen.findByText("No governance events in the last 24 hours");
    expect(screen.getByText(/Most recent governance activity was recorded/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show last 90 days" }));
    await waitFor(() => {
      expect(api.fetchAuditEvidence).toHaveBeenCalledWith(expect.objectContaining({ dateRange: "90d" }));
    });
  });

  it("renders stable AUD ids as real ?event= anchors and honors the deep link", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([
        auditEvent("AUD-0001"),
        auditEvent("AUD-0002", { action: "certification updated", request_id: "REQ-9", displayRequestId: "REQ-9" }),
      ]),
    );
    renderPage("/evidence?event=AUD-0002");
    // Wait for rows to land, then the deep-linked event drives the rail.
    await screen.findByRole("link", { name: "AUD-0001" });
    const rail = screen.getByLabelText("Selected audit event detail");
    expect(within(rail).getByText("AUD-0002")).toBeTruthy();
    // Full backing UUID rides on the title attribute (joinable identity).
    expect(within(rail).getByText("AUD-0002").getAttribute("title")).toBe("aud-0002-full-uuid");
    // Every row id is a REAL anchor carrying the ?event= address.
    const anchor = screen.getByRole("link", { name: "AUD-0001" });
    expect(anchor.getAttribute("href")).toContain("event=AUD-0001");
  });

  it("shows an honest not-found rail for a ?event= outside the filtered view", async () => {
    renderPage("/evidence?event=AUD-9999");
    await screen.findByText("Audit event not found");
    expect(screen.getByText(/AUD-9999 is not in the current filtered view/)).toBeTruthy();
  });

  it("renders the diff with '—' for absent sides and the redaction reason when redacted", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([
        auditEvent("AUD-0001", {
          request_id: "REQ-1",
          displayRequestId: "REQ-1",
          before_json: JSON.stringify({ owner: "old.owner@shorecp.com" }),
          after_json: JSON.stringify({ owner: "new.owner@shorecp.com", steward: "s@shorecp.com" }),
        }),
      ]),
    );
    renderPage("/evidence?event=AUD-0001");
    const rail = await screen.findByLabelText("Selected audit event detail");
    await within(rail).findByText("old.owner@shorecp.com");
    expect(within(rail).getByText("new.owner@shorecp.com")).toBeTruthy();
    // A creation-side value legitimately has no prior state: "—", never
    // "Unavailable" (that implied missing evidence).
    expect(within(rail).getByText("—")).toBeTruthy();

    cleanup();
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([
        auditEvent("AUD-0002", {
          diffState: "redacted",
          diffReason: "Only internal store identifiers changed in this event.",
        }),
      ]),
    );
    renderPage("/evidence?event=AUD-0002");
    await screen.findByText(/Only internal store identifiers changed/);
  });

  it("renders truncation and per-cause exclusion captions without client-side row suppression", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope(
        [
          auditEvent("AUD-0001"),
          auditEvent("AUD-0002", {
            action: "Comment added",
            // An actor writing "mock" must NOT hide the event: suppression is
            // server-side and counted, never a client regex.
            detail: "Please mock up the new tag layout before approving.",
          }),
        ],
        {
          windowTruncated: true,
          fetchLimit: 500,
          nonAuthoritativeRowsExcluded: 4,
          visibilityScopedRowsExcluded: 2,
          internalRowsExcluded: 3,
        },
      ),
    );
    renderPage();
    await screen.findByText("Please mock up the new tag layout before approving.");
    expect(
      screen.getByText("Results truncated at 500 events — narrow the range for complete evidence."),
    ).toBeTruthy();
    const caption = screen.getByText(/Showing 2 of 2 events/);
    expect(caption.textContent).toContain("2 rows about assets outside your visibility scope withheld");
    expect(caption.textContent).toContain("3 internal/maintenance rows excluded");
    expect(caption.textContent).toContain("4 non-authoritative rows excluded server-side");
  });

  it("drives the server-side /api/audit/events query from the applied URL filters", async () => {
    api.fetchAuditEvents.mockResolvedValue([
      auditEvent("AUD-0009", { action: "Description updated", detail: "Filtered row from the audit events API." }),
    ]);
    renderPage();
    await screen.findByText(/Showing 1 of 1 events/);

    fireEvent.change(screen.getByLabelText("Actor email"), {
      target: { value: "marisol.reyes@shorecp.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(api.fetchAuditEvents).toHaveBeenCalledWith(
        expect.objectContaining({
          actorEmail: "marisol.reyes@shorecp.com",
          limit: 500,
          since: expect.any(String),
        }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    await screen.findByText("Filtered row from the audit events API.");
    expect(screen.getByText(/Server-side filter active · 1 matching event/)).toBeTruthy();
  });

  it("handles a 403 from the filtered audit events endpoint gracefully", async () => {
    const forbidden = Object.assign(new Error("Steward or admin role required."), { status: 403 });
    api.fetchAuditEvents.mockRejectedValue(forbidden);
    renderPage();
    await screen.findByText(/Showing 1 of 1 events/);

    fireEvent.change(screen.getByLabelText("Actor email"), { target: { value: "someone@shorecp.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    expect(
      await screen.findByText(/Audit event filters require steward or admin permissions/),
    ).toBeTruthy();
  });

  it("keeps kind-slice counts consistent with the free-text filtered set", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([
        auditEvent("AUD-0001", { detail: "Bulk import committed" }),
        auditEvent("AUD-0002", { detail: "Owner changed" }),
        auditEvent("AUD-0003", { actor_email: "svc-policy-engine", action: "Policy violation", status: "failed" }),
      ]),
    );
    renderPage();
    await screen.findByText(/Showing 3 of 3 events/);
    expect(screen.getByRole("tab", { name: /All events\s*3/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Services\s*1/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Violations\s*1/ })).toBeTruthy();

    // Free-text search applies BEFORE the slices: counts and caption agree.
    fireEvent.change(screen.getByLabelText("Search events"), { target: { value: "bulk" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await screen.findByText(/Showing 1 of 1 events/);
    expect(screen.getByRole("tab", { name: /All events\s*1/ })).toBeTruthy();
  });

  it("does not call the steward/admin audit endpoint for a reader shell", async () => {
    renderPage("/evidence", { userEmail: "reader@example.com", role: "Reader" });
    expect(await screen.findByText("Audit trail is steward/admin only")).toBeTruthy();
    expect(api.fetchAuditEvidence).not.toHaveBeenCalled();
  });

  it("stays hydration-honest: skeleton + placeholder metrics, never definitive zeros", async () => {
    let resolvePayload;
    api.fetchAuditEvidence.mockReturnValue(new Promise((resolve) => { resolvePayload = resolve; }));
    const { container } = renderPage();

    // Loading: the table is an aria-busy skeleton, the KPI values are
    // placeholders, and the REAL-empty copy is nowhere.
    expect(container.querySelector("table[aria-busy='true']")).toBeTruthy();
    expect(screen.queryByText("No audit events match the current filters.")).toBeNull();
    expect(screen.queryByText("No governance events in the last 24 hours")).toBeNull();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Reading audit rows").length).toBeGreaterThan(0);

    resolvePayload(envelope([auditEvent("AUD-0001")]));
    await screen.findByText(/Showing 1 of 1 events/);
    expect(container.querySelector("table[aria-busy='true']")).toBeNull();
  });

  it("keeps the skeleton up while the envelope reports hydrating", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([], { totalChanges: 0 }, { state: "loading", authoritative: false, capabilities: { hydrating: true } }),
    );
    const { container } = renderPage();
    await waitFor(() => {
      expect(api.fetchAuditEvidence).toHaveBeenCalled();
    });
    // Never final-looking zeros while hydrating.
    expect(container.querySelector("table[aria-busy='true']")).toBeTruthy();
    expect(screen.queryByText("No governance events in the last 24 hours")).toBeNull();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);
  });

  it("rejects non-authoritative audit payloads before rendering source rows", async () => {
    api.fetchAuditEvidence.mockResolvedValue({
      data: {
        summary: { events24h: 999, sourceTable: "system.fake.audit" },
        events: [auditEvent("AUD-0001", { action: "Certification" })],
      },
      meta: { source: "prototype-mock", warnings: ["not live Databricks evidence"] },
    });
    renderPage();
    await screen.findByText("Audit evidence source unavailable");
    expect(screen.queryByText("Certification")).toBeNull();
    expect(screen.queryByText("system.fake.audit")).toBeNull();
  });

  it("exports CSV carrying the same truncation warning the view shows", async () => {
    // jsdom's Blob has no .text(); capture the export body at construction.
    const blobBodies = [];
    const NativeBlob = globalThis.Blob;
    vi.stubGlobal(
      "Blob",
      class extends NativeBlob {
        constructor(parts, options) {
          super(parts, options);
          blobBodies.push((parts || []).join(""));
        }
      },
    );
    window.URL.createObjectURL = vi.fn(() => "blob:mock");
    window.URL.revokeObjectURL = vi.fn();
    api.fetchAuditEvidence.mockResolvedValue(
      envelope([auditEvent("AUD-0001")], { windowTruncated: true, fetchLimit: 500 }),
    );
    renderPage();
    await screen.findByText(/Showing 1 of 1 events/);

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(await screen.findByText(/CSV export prepared with 1 audit rows/)).toBeTruthy();
    const csv = blobBodies[0];
    expect(csv).toContain("audit_id");
    expect(csv).toContain("AUD-0001");
    expect(csv).toContain("aud-0001-full-uuid");
    expect(csv).toContain("window_truncated");
    expect(csv).toContain("Results truncated at 500 events — narrow the range for complete evidence.");
    vi.unstubAllGlobals();
  });

  it("generates a JSON report exporting every visible row with completeness flags", async () => {
    const blobBodies = [];
    const NativeBlob = globalThis.Blob;
    vi.stubGlobal(
      "Blob",
      class extends NativeBlob {
        constructor(parts, options) {
          super(parts, options);
          blobBodies.push((parts || []).join(""));
        }
      },
    );
    window.URL.createObjectURL = vi.fn(() => "blob:mock");
    window.URL.revokeObjectURL = vi.fn();
    api.fetchAuditEvidence.mockResolvedValue(
      envelope(
        Array.from({ length: 30 }, (_, index) => auditEvent(`AUD-${String(index + 1).padStart(4, "0")}`)),
        { windowTruncated: true, fetchLimit: 500 },
      ),
    );
    renderPage();
    await screen.findByText(/Showing 8 of 30 events/);

    fireEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByText(/Audit report generated from 30 visible evidence rows/)).toBeTruthy();
    const report = JSON.parse(blobBodies[0]);
    // The old silent slice(0,25) contradiction stays dead: every row exports.
    expect(report.events).toHaveLength(30);
    expect(report.summary.events).toBe(30);
    expect(report.windowTruncated).toBe(true);
    expect(report.truncationWarning).toContain("Results truncated at 500 events");
    expect(report.events[0].auditEventId).toBe("aud-0001-full-uuid");
    vi.unstubAllGlobals();
  });

  it("paginates with Load more from the compact page size", async () => {
    api.fetchAuditEvidence.mockResolvedValue(
      envelope(Array.from({ length: 20 }, (_, index) => auditEvent(`AUD-${String(index + 1).padStart(4, "0")}`))),
    );
    renderPage();
    await screen.findByText(/Showing 8 of 20 events/);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText(/Showing 16 of 20 events/);
  });
});
