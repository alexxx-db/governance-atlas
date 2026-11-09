import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SectionCard } from "../SectionCard";

describe("SectionCard", () => {
  it("keeps the absorbed northstar contract: title, eyebrow, subtitle, actions, tooltip, children", () => {
    render(
      <SectionCard
        title="Risk heatmap"
        eyebrow="Risk & quality"
        subtitle="By domain and severity"
        tooltip="Counts come from quality runs"
        actions={<button>Export</button>}
      >
        <p>card body</p>
      </SectionCard>,
    );
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("Risk heatmap");
    expect(screen.getByText("Risk & quality")).not.toBeNull();
    expect(screen.getByText("By domain and severity")).not.toBeNull();
    expect(screen.getByText("Export")).not.toBeNull();
    expect(screen.getByText("card body")).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Risk heatmap: Counts come from quality runs" }),
    ).not.toBeNull();
  });

  it("hydrating status marks the card busy with a shimmer class", () => {
    render(
      <SectionCard title="T" status={{ status: "hydrating" }}>
        <p>seed</p>
      </SectionCard>,
    );
    const card = document.querySelector(".ax-sys-section-card");
    expect(card.getAttribute("aria-busy")).toBe("true");
    expect(card.className).toContain("is-hydrating");
    expect(screen.getByText("seed")).not.toBeNull();
  });

  it("degraded status renders a warn footnote with the reason, keeping children visible", () => {
    render(
      <SectionCard title="T" status={{ status: "degraded", warnings: ["Freshness signal limited."] }}>
        <p>data stays</p>
      </SectionCard>,
    );
    expect(screen.getByText("data stays")).not.toBeNull();
    const footnote = screen.getByRole("status");
    expect(footnote.textContent).toContain("Freshness signal limited.");
    expect(footnote.className).toContain("tone-warn");
  });

  it("unavailable status renders an honest bad-tone footnote", () => {
    render(
      <SectionCard title="T" status={{ status: "unavailable" }}>
        <p>x</p>
      </SectionCard>,
    );
    const footnote = screen.getByRole("status");
    expect(footnote.className).toContain("tone-bad");
    expect(footnote.textContent).toContain("unavailable");
  });

  it("no status → no footnote, no busy state", () => {
    render(
      <SectionCard title="T">
        <p>x</p>
      </SectionCard>,
    );
    const card = document.querySelector(".ax-sys-section-card");
    expect(card.getAttribute("aria-busy")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
