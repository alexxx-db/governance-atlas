import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PageShell } from "../PageShell";

describe("PageShell", () => {
  it("renders eyebrow, h1 title, subtitle, actions and children", () => {
    render(
      <PageShell
        title="Discovery"
        eyebrow="Governed estate"
        subtitle="Find and evaluate governed data."
        actions={<button>New search</button>}
      >
        <p>body content</p>
      </PageShell>,
    );
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Discovery");
    expect(screen.getByText("Governed estate")).not.toBeNull();
    expect(screen.getByText("Find and evaluate governed data.")).not.toBeNull();
    expect(screen.getByText("New search")).not.toBeNull();
    expect(screen.getByText("body content")).not.toBeNull();
  });

  it("renders breadcrumb, tabs, and rail slots", () => {
    render(
      <PageShell
        title="T"
        breadcrumbs={<span>Discover / orders</span>}
        tabs={<div data-testid="tabs" />}
        rail={<div data-testid="rail" />}
      >
        <p>x</p>
      </PageShell>,
    );
    expect(screen.getByRole("navigation", { name: "Breadcrumb" }).textContent).toContain("Discover / orders");
    expect(screen.getByTestId("tabs").closest(".ax-sys-page-tabs")).not.toBeNull();
    expect(screen.getByTestId("rail").closest("aside")).not.toBeNull();
  });

  it("degraded status renders the page-level warning banner with warnings and retry", () => {
    const refresh = vi.fn();
    render(
      <PageShell title="T" status={{ status: "degraded", warnings: ["Inventory limited."], refresh }}>
        <p>still here</p>
      </PageShell>,
    );
    expect(screen.getByRole("status").textContent).toContain("Inventory limited.");
    expect(screen.getByText("still here")).not.toBeNull();
    fireEvent.click(screen.getByText("Retry"));
    expect(refresh).toHaveBeenCalled();
  });

  it("unavailable status renders a danger banner (role=alert) with honest reason; onRetry prop wins", () => {
    const onRetry = vi.fn();
    render(
      <PageShell
        title="T"
        status={{ status: "unavailable", reason: "system tables offline" }}
        onRetry={onRetry}
      >
        <p>content</p>
      </PageShell>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("This page is unavailable");
    expect(alert.textContent).toContain("system tables offline");
    fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalled();
  });

  it("hydrating status shows the quiet Refreshing indicator, not a banner", () => {
    render(
      <PageShell title="T" status="hydrating">
        <p>seed</p>
      </PageShell>,
    );
    expect(screen.getByText("Refreshing")).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("accepts a bare status string and stamps data-status for styling hooks", () => {
    render(
      <PageShell title="T" status="degraded">
        <p>x</p>
      </PageShell>,
    );
    expect(document.querySelector(".ax-sys-page").getAttribute("data-status")).toBe("degraded");
  });
});
