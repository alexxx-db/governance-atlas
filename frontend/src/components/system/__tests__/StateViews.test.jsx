import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  EmptyState,
  ForQuery,
  LoadingState,
  StateViews,
  StatusBanner,
  UnavailableState,
} from "../StateViews";

describe("StateViews primitives", () => {
  it("LoadingState renders a polite status skeleton per variant", () => {
    render(<LoadingState variant="table" />);
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.className).toContain("is-table");
    expect(region.querySelectorAll(".ax-sys-skeleton").length).toBeGreaterThan(0);
  });

  it("EmptyState renders title, body and action", () => {
    const onClick = vi.fn();
    render(
      <EmptyState
        title="No findings"
        body="Nothing matched."
        action={<button onClick={onClick}>Reset</button>}
      />,
    );
    expect(screen.getByText("No findings")).not.toBeNull();
    expect(screen.getByText("Nothing matched.")).not.toBeNull();
    fireEvent.click(screen.getByText("Reset"));
    expect(onClick).toHaveBeenCalled();
  });

  it("UnavailableState shows the honest dash glyph, a reason, and retry", () => {
    const onRetry = vi.fn();
    render(<UnavailableState reason="lineage-query-failed" onRetry={onRetry} />);
    expect(screen.getByText("—")).not.toBeNull();
    expect(screen.getByText("lineage-query-failed")).not.toBeNull();
    fireEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalled();
  });

  it("UnavailableState never fabricates a reason silently — default honest copy", () => {
    render(<UnavailableState />);
    expect(screen.getByText("This signal is unavailable for the current visibility scope.")).not.toBeNull();
  });

  it("StatusBanner joins warnings, uses role=status for warning tone and role=alert for danger", () => {
    const { rerender } = render(
      <StatusBanner title="Limited" warnings={["W1.", "W2."]} tone="warning" />,
    );
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("W1. W2.");
    rerender(<StatusBanner title="Broken" message="It failed." tone="danger" />);
    expect(screen.getByRole("alert").textContent).toContain("It failed.");
  });
});

describe("StateViews.ForQuery — Wave-A2 status contract rendering", () => {
  const data = [{ id: 1, name: "row" }];
  const content = (rows) => <ul>{rows.map((row) => <li key={row.id}>{row.name}</li>)}</ul>;

  it("loading → skeleton", () => {
    render(<ForQuery query={{ status: "loading" }}>{content}</ForQuery>);
    expect(screen.getByRole("status").querySelector(".ax-sys-skeleton")).not.toBeNull();
  });

  it("available → children as render function receiving data", () => {
    render(<ForQuery query={{ status: "available", data }}>{content}</ForQuery>);
    expect(screen.getByText("row")).not.toBeNull();
  });

  it("available + empty data → EmptyState (custom override honored)", () => {
    const { rerender } = render(<ForQuery query={{ status: "available", data: [] }}>{content}</ForQuery>);
    expect(screen.getByText("Nothing to show")).not.toBeNull();
    rerender(
      <ForQuery query={{ status: "available", data: [] }} empty={<p>Zero rows here.</p>}>
        {content}
      </ForQuery>,
    );
    expect(screen.getByText("Zero rows here.")).not.toBeNull();
  });

  it("hydrating with seed data → children rendered inside an aria-busy wrapper (no blank flash)", () => {
    const { container } = render(<ForQuery query={{ status: "hydrating", data }}>{content}</ForQuery>);
    expect(screen.getByText("row")).not.toBeNull();
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("hydrating with no seed yet → skeleton, never a wrong empty state", () => {
    render(<ForQuery query={{ status: "hydrating", data: [] }}>{content}</ForQuery>);
    expect(screen.queryByText("Nothing to show")).toBeNull();
    expect(screen.getByRole("status").querySelector(".ax-sys-skeleton")).not.toBeNull();
  });

  it("degraded → banner with warnings + retry ABOVE intact children (data never wiped)", () => {
    const refresh = vi.fn();
    render(
      <ForQuery query={{ status: "degraded", data, warnings: ["Signal limited."], refresh }}>
        {content}
      </ForQuery>,
    );
    expect(screen.getByText("row")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Signal limited.");
    fireEvent.click(screen.getByText("Retry"));
    expect(refresh).toHaveBeenCalled();
  });

  it("unavailable → honest UnavailableState with meta reason", () => {
    render(
      <ForQuery query={{ status: "unavailable", data: null, meta: { emptyReason: "no-lineage-rows" } }}>
        {content}
      </ForQuery>,
    );
    expect(screen.getByText("Unavailable")).not.toBeNull();
    expect(screen.getByText("no-lineage-rows")).not.toBeNull();
  });

  it("error → 'Something went wrong' + retry wired to query.refresh", () => {
    const refresh = vi.fn();
    render(<ForQuery query={{ status: "error", refresh }}>{content}</ForQuery>);
    expect(screen.getByText("Something went wrong")).not.toBeNull();
    fireEvent.click(screen.getByText("Retry"));
    expect(refresh).toHaveBeenCalled();
  });

  it("missing/garbage status is treated as loading (never guesses data)", () => {
    render(<ForQuery query={{ status: "banana", data }}>{content}</ForQuery>);
    expect(screen.queryByText("row")).toBeNull();
    expect(screen.getByRole("status")).not.toBeNull();
  });

  it("is exported on the StateViews namespace object", () => {
    expect(StateViews.ForQuery).toBe(ForQuery);
    expect(StateViews.LoadingState).toBe(LoadingState);
    expect(StateViews.EmptyState).toBe(EmptyState);
    expect(StateViews.UnavailableState).toBe(UnavailableState);
    expect(StateViews.StatusBanner).toBe(StatusBanner);
  });
});
