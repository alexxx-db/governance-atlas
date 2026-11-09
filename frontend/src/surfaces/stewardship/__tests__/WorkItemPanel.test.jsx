import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { axiomQueryClient } from "../../../lib/queryClient";
import { WorkItemPanel } from "../WorkItemPanel.jsx";

// The panel now mounts AssignToControl, which calls useWorkspaceRoster
// (react-query) — so every render needs a QueryClientProvider, mirroring the
// StewardshipPage test harness. renderPanel wraps render + rerender for us.
const Providers = ({ children }) => (
  <QueryClientProvider client={axiomQueryClient}>{children}</QueryClientProvider>
);
const renderPanel = (ui, options) => render(ui, { wrapper: Providers, ...options });

/*
 * surfaces/stewardship/__tests__/WorkItemPanel.test.jsx — the request
 * mini-hub's Evidence trail (cohesion follow-up 1). The workbench detail
 * payload now carries `auditTrail` rows joined to the Evidence ledger by
 * AUD display ids; the panel renders each mapped row as an EntityChip
 * event anchor, keeps unmapped rows as text, shows an honest empty state,
 * and never claims "no audit events" while the detail query is loading.
 *
 * Rendered WITHOUT a Router on purpose: EntityChip degrades to plain
 * anchors outside a Router, which keeps href assertions direct.
 */

const baseItem = {
  requestId: "9f8e7d6c-5b4a-3921-8076-54efab321098",
  title: "Owner missing",
  kind: "Owner missing",
  status: "Pending",
  priority: "P1",
  requester: "sky@shorecp.com",
  createdAt: "2026-07-01T09:00:00Z",
  assetFqn: "finance_prod.curated.revenue_daily",
};

describe("WorkItemPanel evidence trail", () => {
  it("renders auditTrail rows as Evidence event anchors with humanized actions and UTC times", () => {
    renderPanel(
      <WorkItemPanel
        detailStatus="available"
        item={{
          ...baseItem,
          auditTrail: [
            {
              displayAuditId: "AUD-00FF00AA",
              auditEventId: "41",
              action: "request_created",
              createdAt: "2026-07-01T09:00:00Z",
            },
            // Unmapped row: backend could not join it to the ledger.
            { displayAuditId: "", auditEventId: "42", action: "priority_changed", createdAt: "2026-07-02T10:30:00Z" },
          ],
        }}
      />,
    );

    const chip = screen.getByRole("link", { name: "AUD-00FF00AA" });
    expect(chip.getAttribute("href")).toBe("/evidence?event=AUD-00FF00AA");
    expect(screen.getByText("Request created")).toBeTruthy();
    // UTC-labeled timestamp, matching the Evidence surface convention
    // (scoped: the header's Created date shares the same timestamp).
    const trailRegion = screen.getByLabelText("Audit events");
    expect(within(trailRegion).getByText(/Jul 1, 2026.*UTC/)).toBeTruthy();
    // The unmapped row renders as text — humanized, but never a dead link.
    const unmapped = screen.getByText("Priority changed");
    expect(unmapped.closest("a")).toBeNull();
    expect(screen.getAllByRole("link").filter((a) => /\/evidence\?event=/.test(a.getAttribute("href") || ""))).toHaveLength(1);
  });

  it("format-checks trail ids: malformed displayAuditId rows never link", () => {
    renderPanel(
      <WorkItemPanel
        detailStatus="available"
        item={{
          ...baseItem,
          auditTrail: [{ displayAuditId: "AUD-NOPE", auditEventId: "43", action: "status_changed" }],
        }}
      />,
    );
    expect(screen.getByText("Status changed")).toBeTruthy();
    expect(
      screen.queryAllByRole("link").filter((a) => /\/evidence\?event=/.test(a.getAttribute("href") || "")),
    ).toHaveLength(0);
  });

  it("shows the honest empty state when auditTrail is absent or empty", () => {
    const { rerender } = renderPanel(<WorkItemPanel detailStatus="available" item={baseItem} />);
    expect(screen.getByText("No audit events recorded for this item yet.")).toBeTruthy();

    rerender(<WorkItemPanel detailStatus="available" item={{ ...baseItem, auditTrail: [] }} />);
    expect(screen.getByText("No audit events recorded for this item yet.")).toBeTruthy();
  });

  it("never shows a definitive empty trail while the detail query is loading", () => {
    renderPanel(<WorkItemPanel detailStatus="loading" item={baseItem} />);
    expect(screen.getByText("Loading the audit trail…")).toBeTruthy();
    expect(screen.queryByText("No audit events recorded for this item yet.")).toBeNull();
    // Comments keep their own hydration-honest placeholder too.
    expect(screen.getByText("Loading the comment timeline…")).toBeTruthy();
  });

  it("renders a per-comment AUD chip from the backend-mapped displayAuditId", () => {
    renderPanel(
      <WorkItemPanel
        detailStatus="available"
        item={{
          ...baseItem,
          comments: [
            {
              id: "c-1",
              author: "ana@shorecp.com",
              at: "2026-07-03T12:00:00Z",
              text: "Reviewed the ownership evidence.",
              displayAuditId: "AUD-12ab34cd",
            },
            // No mapping: plain comment, no event anchor for this row.
            { id: "c-2", author: "bo@shorecp.com", at: "2026-07-04T12:00:00Z", text: "Second note." },
          ],
        }}
      />,
    );
    // auditChipId uppercases into the canonical AUD-XXXXXXXX form.
    const chip = screen.getByRole("link", { name: "AUD-12AB34CD" });
    expect(chip.getAttribute("href")).toBe("/evidence?event=AUD-12AB34CD");
    expect(
      screen.getAllByRole("link").filter((a) => /\/evidence\?event=/.test(a.getAttribute("href") || "")),
    ).toHaveLength(1);
  });
});

describe("WorkItemPanel suggested actions (M1)", () => {
  it("renders suggested actions as non-actionable planned-change items, never executable buttons", () => {
    renderPanel(
      <WorkItemPanel
        canMutate
        detailStatus="available"
        item={{
          ...baseItem,
          suggestedActions: [
            { label: "Assign a business owner", detail: "No business owner is recorded." },
            { label: "Confirm sensitivity classification" },
          ],
        }}
      />,
    );
    // The labels render as plain text inside a "planned changes" list…
    const planned = screen.getByLabelText("Planned changes — not yet applied");
    expect(within(planned).getByText("Assign a business owner")).toBeTruthy();
    expect(within(planned).getByText("Confirm sensitivity classification")).toBeTruthy();
    // …and NOT as buttons the user could click expecting an effect.
    expect(screen.queryByRole("button", { name: /Assign a business owner/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirm sensitivity classification/ })).toBeNull();
    // The honest "not yet applied" framing is present.
    expect(within(planned).getAllByText("Planned")).toHaveLength(2);
  });
});

describe("WorkItemPanel assign to another steward (G7)", () => {
  it("reveals a roster typeahead and calls onAssignTo with the picked email, closing on success", async () => {
    const onAssignTo = vi.fn().mockResolvedValue(true);
    renderPanel(
      <WorkItemPanel
        canMutate
        detailStatus="available"
        item={baseItem}
        onAssignTo={onAssignTo}
      />,
    );

    // Collapsed by default: a single "Assign to…" trigger, no input yet.
    const trigger = screen.getByRole("button", { name: "Assign to…" });
    expect(screen.queryByLabelText("Assignee email")).toBeNull();
    fireEvent.click(trigger);

    const input = screen.getByLabelText("Assignee email");
    fireEvent.change(input, { target: { value: "steward@shorecp.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(onAssignTo).toHaveBeenCalledWith("steward@shorecp.com");
    // A successful (truthy) write collapses the picker back to the trigger.
    await waitFor(() => expect(screen.queryByLabelText("Assignee email")).toBeNull());
    expect(screen.getByRole("button", { name: "Assign to…" })).toBeTruthy();
  });

  it("keeps the picker open when the assign write is rejected (resolves falsy)", async () => {
    const onAssignTo = vi.fn().mockResolvedValue(false);
    renderPanel(
      <WorkItemPanel canMutate detailStatus="available" item={baseItem} onAssignTo={onAssignTo} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Assign to…" }));
    fireEvent.change(screen.getByLabelText("Assignee email"), {
      target: { value: "ghost@shorecp.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(onAssignTo).toHaveBeenCalledWith("ghost@shorecp.com"));
    // Rejected write leaves the input in place so the steward can correct it.
    expect(screen.getByLabelText("Assignee email")).toBeTruthy();
  });
});
