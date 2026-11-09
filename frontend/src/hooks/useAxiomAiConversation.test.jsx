import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAxiomAiConversation } from "./useAxiomAiConversation";

describe("useAxiomAiConversation", () => {
  it("normalizes Genie prefixes and markdown tables before display", async () => {
    const request = vi.fn().mockResolvedValue({
      answer: [
        "Genie said: governed evidence is available.",
        "",
        "| Domain | Governed assets |",
        "| --- | --- |",
        "| Finance | 3 |",
      ].join("\n"),
      evidence: [{ label: "finance_prod.curated.revenue_daily" }],
    });
    const { result } = renderHook(() => useAxiomAiConversation({ request }));

    await act(async () => {
      await result.current.ask("Which domains are governed?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    const assistant = result.current.messages.find((message) => message.role === "assistant");
    expect(assistant.text).not.toMatch(/Genie said/i);
    expect(assistant.text).not.toContain("| Domain |");
    expect(assistant.text).toContain("- Domain: Finance; Governed assets: 3");
    expect(assistant.evidenceCount).toBe(1);
  });

  it("forwards page-awareness context to the request", async () => {
    const request = vi.fn().mockResolvedValue({ answer: "ok", evidence: [] });
    const { result } = renderHook(() => useAxiomAiConversation({ request }));

    await act(async () => {
      await result.current.ask("Who owns this asset?", {
        surface: "assets",
        assetFqn: "finance_prod.curated.revenue_daily",
      });
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(request).toHaveBeenCalledWith(
      "Who owns this asset?",
      expect.objectContaining({
        context: { surface: "assets", assetFqn: "finance_prod.curated.revenue_daily" },
      }),
    );
  });

  it("keeps an explicit error message in the transcript", async () => {
    const request = vi.fn().mockRejectedValue(new Error("Genie endpoint timed out."));
    const { result } = renderHook(() => useAxiomAiConversation({ request }));

    await act(async () => {
      await result.current.ask("What changed today?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("Genie endpoint timed out.");
    const assistant = result.current.messages.find((message) => message.role === "assistant");
    expect(assistant.error).toBe(true);
    expect(assistant.pending).toBe(false);
    expect(assistant.text).toBe("Genie endpoint timed out.");
  });
});
