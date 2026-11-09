import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { StatTile } from "../StatTile";

describe("StatTile", () => {
  it("renders label, value, delta (with tone), and meta", () => {
    render(
      <StatTile label="Certified assets" value="44" delta="+3 this week" deltaTone="good" meta="of 1,240" />,
    );
    expect(screen.getByText("Certified assets")).not.toBeNull();
    expect(screen.getByText("44")).not.toBeNull();
    const delta = screen.getByText("+3 this week");
    expect(delta.className).toContain("tone-good");
    expect(screen.getByText("of 1,240")).not.toBeNull();
  });

  it("renders a sparkline for trend data (absorbed Sparkline variant)", () => {
    render(<StatTile label="Coverage" value="96%" trend={[1, 4, 2, 8]} />);
    expect(screen.getByRole("img", { name: "Coverage trend" })).not.toBeNull();
  });

  it("suppresses the sparkline for fewer than 2 points (no fabricated trends)", () => {
    render(<StatTile label="Coverage" value="96%" trend={[5]} />);
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("donut variant renders the ring and derives display value from percent", () => {
    render(<StatTile label="Maturity" variant="donut" percent={62.5} />);
    expect(document.querySelector(".ax-sys-donut")).not.toBeNull();
    expect(screen.getByText("62.5%")).not.toBeNull();
  });

  it("renders a progress bar when progress is numeric", () => {
    render(<StatTile label="Adoption" value="12" progress={40} />);
    const bar = document.querySelector(".ax-sys-progress");
    expect(bar).not.toBeNull();
    expect(bar.getAttribute("aria-label")).toBe("Adoption progress");
    expect(bar.querySelector("span").style.width).toBe("40%");
  });

  it("target makes the whole tile a real anchor to the ref's canonical route", () => {
    render(
      <StatTile
        label="Open requests"
        value="7"
        target={{ surface: "stewardship", params: { assignee: "me" } }}
      />,
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/stewardship?assignee=me");
    expect(link.className).toContain("is-link");
  });

  it("target works inside a Router as a client-side Link", () => {
    render(
      <MemoryRouter>
        <StatTile label="Assets" value="1240" target={{ kind: "asset", fqn: "a.b.c" }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link").getAttribute("href")).toBe("/assets/a.b.c");
  });

  it("navigate adapter intercepts plain left-click on a target tile", () => {
    const navigate = vi.fn();
    const target = { kind: "event", id: "AUD-1" };
    render(<StatTile label="Events" value="9" target={target} navigate={navigate} />);
    fireEvent.click(screen.getByRole("link"));
    expect(navigate).toHaveBeenCalledWith(target, { href: "/evidence?event=AUD-1" });
  });

  it("onClick without target renders an actionable button", () => {
    const onClick = vi.fn();
    render(<StatTile label="Filters" value="3" onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalled();
  });

  it("static tiles are plain articles (no interactive role)", () => {
    render(<StatTile label="Static" value="1" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("hint renders as a non-interactive accessible note (valid inside anchor roots)", () => {
    render(<StatTile label="Score" value="81" hint="Weighted governance score" target={{ kind: "term", id: "t" }} />);
    const tip = screen.getByRole("img", { name: "Weighted governance score" });
    expect(tip.tagName).toBe("SPAN");
  });
});
