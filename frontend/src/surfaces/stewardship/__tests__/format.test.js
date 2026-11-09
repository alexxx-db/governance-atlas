import { describe, expect, it } from "vitest";
import {
  auditChipId,
  humanMutationError,
  humanizeAuditAction,
  isValidationWorkItem,
  lensCounts,
  matchesItemParam,
  matchesLens,
  normalizeWorkItem,
  patchWorkbenchRequests,
  scopeSummary,
  termReviewItem,
  workItemAuditTrail,
  workItemDisplayId,
} from "../format.js";

describe("stewardship format helpers", () => {
  it("compresses long store ids to GOV-XXXXXXXX and keeps short ids verbatim", () => {
    expect(workItemDisplayId({ requestId: "SI-2491" })).toBe("SI-2491");
    expect(workItemDisplayId({ requestId: "9f8e7d6c-5b4a-3921-8076-54efab321098" })).toBe(
      "GOV-9F8E7D6C",
    );
    expect(workItemDisplayId({ requestId: "ax-home-evidence-request-09" })).toBe("GOV-09");
  });

  it("matches ?item= params against display AND full ids, case-insensitively", () => {
    const item = { requestId: "9f8e7d6c-5b4a-3921-8076-54efab321098" };
    expect(matchesItemParam(item, "gov-9f8e7d6c")).toBe(true);
    expect(matchesItemParam(item, "9f8e7d6c-5b4a-3921-8076-54efab321098")).toBe(true);
    expect(matchesItemParam(item, "GOV-00000000")).toBe(false);
    expect(matchesItemParam(item, "")).toBe(false);
  });

  it("keeps lens semantics honest: term reviews never match p1/overdue", () => {
    const term = termReviewItem({ termId: "t-1", term: "Average Revenue", status: "Proposed" });
    expect(matchesLens(term, "p1", {})).toBe(false);
    expect(matchesLens(term, "overdue", {})).toBe(false);
    expect(matchesLens(term, "all", {})).toBe(true);
  });

  it("counts the my-work lens from real assignment fields only (no requester fallback)", () => {
    const user = { email: "abarreto@shorecp.com", name: "Skyler Myers" };
    const assigned = normalizeWorkItem({ requestId: "r1", assigned: "Skyler Myers" });
    const requesterOnly = normalizeWorkItem({ requestId: "r2", requester: "Skyler Myers" });
    const counts = lensCounts([assigned, requesterOnly], user);
    expect(counts.mine).toBe(1);
    expect(counts.all).toBe(2);
  });

  it("rejects validation-seed rows", () => {
    expect(isValidationWorkItem({ requestId: "ax-home-seed-request-9" })).toBe(true);
    expect(isValidationWorkItem({ requestId: "SI-2491", source: "governance-store" })).toBe(false);
  });

  it("patches a request inside both workbench payload shapes without mutating", () => {
    const bare = { requests: [{ requestId: "r1", status: "Pending" }] };
    const patchedBare = patchWorkbenchRequests(bare, "r1", { status: "Resolved" });
    expect(patchedBare.requests[0].status).toBe("Resolved");
    expect(bare.requests[0].status).toBe("Pending");

    const enveloped = { data: { requests: [{ requestId: "r1", status: "Pending" }] } };
    const patchedEnv = patchWorkbenchRequests(enveloped, "r1", { status: "Resolved" });
    expect(patchedEnv.data.requests[0].status).toBe("Resolved");
    expect(enveloped.data.requests[0].status).toBe("Pending");
  });

  it("summarizes the openRequestScope split", () => {
    expect(
      scopeSummary({ visibleOpenCount: 1, outOfScopeOpenCount: 2, caption: "2 outside" }),
    ).toBe("3 open change requests: 1 in the visible estate · 2 on out-of-scope assets (2 outside)");
    expect(scopeSummary(null)).toBe("");
  });

  it("humanizes mutation failures and keeps the request id, never raw exception text", () => {
    const error = Object.assign(new Error("TypeError: boom"), {
      status: 500,
      detailMessage: "TypeError: boom",
      httpRequestId: "req-1",
    });
    expect(humanMutationError(error, "Couldn't update the work item.")).toBe(
      "Couldn't update the work item. (Request ID: req-1)",
    );
    const validation = Object.assign(new Error("nope"), {
      status: 403,
      detailMessage: "Steward role required.",
    });
    expect(humanMutationError(validation, "fallback")).toBe("Steward role required.");
  });

  it("format-checks and canonicalizes AUD display ids", () => {
    expect(auditChipId("AUD-12ab34cd")).toBe("AUD-12AB34CD");
    expect(auditChipId("AUD-NOPE")).toBe("");
    expect(auditChipId("12AB34CD")).toBe("");
    expect(auditChipId("")).toBe("");
  });

  it("humanizes audit actions from snake/kebab case", () => {
    expect(humanizeAuditAction("request_created")).toBe("Request created");
    expect(humanizeAuditAction("PRIORITY-CHANGED")).toBe("Priority changed");
    expect(humanizeAuditAction("")).toBe("Audit event");
  });

  it("normalizes auditTrail rows and yields [] when the backend field is absent", () => {
    // Feature detection: pre-join detail payloads carry no auditTrail.
    expect(workItemAuditTrail({ requestId: "r1" })).toEqual([]);
    expect(workItemAuditTrail(null)).toEqual([]);
    const rows = workItemAuditTrail({
      auditTrail: [
        { displayAuditId: "AUD-00ff00aa", auditEventId: "41", action: "request_created", createdAt: "2026-07-01T09:00:00Z" },
        { displayAuditId: "bogus", auditEventId: "42", action: "comment_added" },
        null,
      ],
    });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      key: "AUD-00FF00AA",
      displayAuditId: "AUD-00FF00AA",
      auditEventId: "41",
      action: "Request created",
      at: "2026-07-01T09:00:00Z",
    });
    // Unmappable id degrades to text-only (no dead Evidence link).
    expect(rows[1]).toMatchObject({ key: "42", displayAuditId: "", action: "Comment added" });
  });
});
