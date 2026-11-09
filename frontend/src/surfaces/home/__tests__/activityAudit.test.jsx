import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { eventRows } from "../format.js";
import { ActivityCard } from "../sections/GovernanceCards.jsx";

/*
 * surfaces/home/__tests__/activityAudit.test.jsx — the activity feed's
 * Evidence-ledger anchoring (cohesion follow-up 1). The backend
 * governance-summary join now emits `displayAuditId` per activity row;
 * eventRows format-checks it and the ActivityCard gates the event link on
 * that single field — rows without one stay plain text (never dead links).
 */

describe("eventRows displayAuditId contract", () => {
  it("prefers the backend-joined displayAuditId over the store event id", () => {
    const rows = eventRows({
      recentEvents: [
        {
          id: "store-evt-991",
          displayAuditId: "AUD-0a1b2c3d",
          auditEventId: "991",
          title: "Certification updated",
          createdAt: "2026-07-20T08:00:00Z",
        },
      ],
    });
    expect(rows).toHaveLength(1);
    // Canonical uppercase form — Evidence addresses events as AUD-XXXXXXXX.
    expect(rows[0].displayAuditId).toBe("AUD-0A1B2C3D");
    expect(rows[0].id).toBe("AUD-0A1B2C3D");
    expect(rows[0].auditEventId).toBe("991");
  });

  it("keeps the defensive format check: malformed ids never become links", () => {
    const rows = eventRows({
      recentEvents: [
        { id: "store-evt-1", displayAuditId: "AUD-XYZ", title: "Tag applied" },
        { id: "store-evt-2", displayAuditId: "totally-wrong", title: "Owner set" },
        { id: "store-evt-3", title: "Comment recorded" },
      ],
    });
    expect(rows.map((row) => row.displayAuditId)).toEqual(["", "", ""]);
    // Plain rows keep their store id for React keys.
    expect(rows[0].id).toBe("store-evt-1");
  });

  it("degrades gracefully on pre-join payloads: an AUD-shaped row id still anchors", () => {
    const rows = eventRows({
      recentEvents: [{ id: "AUD-11223344", title: "Certification updated" }],
    });
    expect(rows[0].displayAuditId).toBe("AUD-11223344");
  });
});

describe("ActivityCard event anchoring", () => {
  const renderCard = (events) =>
    render(
      <MemoryRouter>
        <ActivityCard events={events} liveEvidence />
      </MemoryRouter>,
    );

  it("renders rows with displayAuditId as Evidence event anchors", () => {
    const events = eventRows({
      recentEvents: [
        {
          id: "store-evt-1",
          displayAuditId: "AUD-0A1B2C3D",
          title: "Certification updated",
          actorEmail: "marisol@shorecp.com",
          createdAt: "2026-07-20T08:00:00Z",
        },
      ],
    });
    renderCard(events);
    const anchor = screen.getByRole("link", { name: "Certification updated" });
    expect(anchor.getAttribute("href")).toBe("/evidence?event=AUD-0A1B2C3D");
  });

  it("renders rows without displayAuditId as plain text (no dead link)", () => {
    const events = eventRows({
      recentEvents: [
        { id: "store-evt-2", title: "Ownership transferred", createdAt: "2026-07-19T10:00:00Z" },
      ],
    });
    renderCard(events);
    const title = screen.getByText("Ownership transferred");
    expect(title.closest("a")).toBeNull();
    expect(screen.queryByRole("link", { name: "Ownership transferred" })).toBeNull();
  });
});
