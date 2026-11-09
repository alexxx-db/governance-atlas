import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import HelpPage from "../HelpPage.jsx";

function renderHelp(props = {}) {
  return render(
    <MemoryRouter>
      <HelpPage {...props} />
    </MemoryRouter>,
  );
}

describe("HelpPage (surfaces/help)", () => {
  afterEach(() => {
    document.title = "";
  });

  it("renders the hero and every help section on the system kit", () => {
    const { container } = renderHelp();

    expect(screen.getByRole("heading", { level: 1, name: "How Axiom works" })).not.toBeNull();
    for (const title of [
      "Getting started",
      "Who sees what",
      "Keyboard shortcuts",
      "Getting help",
      "Privacy",
      "Terms",
    ]) {
      expect(screen.getByRole("heading", { level: 2, name: title })).not.toBeNull();
    }
    // System-kit frame, zero legacy gh- classes.
    expect(container.querySelector(".ax-sys-page")).not.toBeNull();
    expect(container.querySelectorAll(".ax-sys-section-card").length).toBe(6);
    expect(container.querySelector('[class*="gh-"]')).toBeNull();
  });

  it("renders a table of contents with real in-page anchors", () => {
    renderHelp();
    const toc = screen.getByLabelText("Help sections");
    const links = [...toc.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "#getting-started",
      "#authentication",
      "#shortcuts",
      "#support",
      "#privacy",
      "#terms",
    ]);
    // Each anchor target exists.
    for (const link of links) {
      expect(document.getElementById(link.getAttribute("href").slice(1))).not.toBeNull();
    }
  });

  it("sets the document title while mounted and restores it on unmount", () => {
    document.title = "Axiom";
    const view = renderHelp();
    expect(document.title).toBe("Help — Axiom");
    view.unmount();
    expect(document.title).toBe("Axiom");
  });

  it("renders the back action only when onBack is provided, and wires the click", () => {
    const onBack = vi.fn();
    const view = renderHelp({ onBack });
    fireEvent.click(screen.getByRole("button", { name: "← Back to Discovery" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    view.unmount();

    renderHelp();
    expect(screen.queryByRole("button", { name: "← Back to Discovery" })).toBeNull();
  });

  it("keeps the OBO access answer available (help copy contract)", () => {
    renderHelp();
    expect(screen.getByText("On-behalf-of access")).not.toBeNull();
    expect(screen.getByText("Why can't I see a catalog I have access to?")).not.toBeNull();
  });
});
