import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Badge } from "../Badge";
import { Button } from "../Button";

describe("Button", () => {
  it("defaults to a type=button secondary neutral md button", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.getAttribute("type")).toBe("button");
    expect(button.className).toContain("is-secondary");
    expect(button.className).toContain("tone-neutral");
    expect(button.className).toContain("size-md");
  });

  it("applies variant, tone and size classes", () => {
    render(
      <Button variant="primary" tone="danger" size="sm">
        Delete
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button.className).toContain("is-primary");
    expect(button.className).toContain("tone-danger");
    expect(button.className).toContain("size-sm");
  });

  it("fires onClick, and not when disabled", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Go</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(
      <Button onClick={onClick} disabled>
        Go
      </Button>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("loading disables the button, marks it busy, and shows a spinner", () => {
    render(<Button loading>Deploying</Button>);
    const button = screen.getByRole("button");
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.querySelector(".ax-sys-button-spinner")).not.toBeNull();
  });

  it("icon variant renders no visible label and relies on aria-label", () => {
    render(<Button variant="icon" aria-label="Close panel" icon={<svg />} />);
    const button = screen.getByRole("button", { name: "Close panel" });
    expect(button.querySelector(".ax-sys-button-label")).toBeNull();
    expect(button.querySelector(".ax-sys-button-icon")).not.toBeNull();
  });

  it("unknown variant/tone fall back to safe defaults instead of unstyled output", () => {
    render(
      <Button variant="mystery" tone="sparkle">
        X
      </Button>,
    );
    const button = screen.getByRole("button");
    expect(button.className).toContain("is-secondary");
    expect(button.className).toContain("tone-neutral");
  });
});

describe("Badge", () => {
  it("renders children with the neutral default tone", () => {
    render(<Badge>PII</Badge>);
    const badge = screen.getByText("PII");
    expect(badge.className).toContain("ax-sys-badge");
    expect(badge.className).toContain("tone-neutral");
  });

  it("maps status vocabulary to tones (absorbed from StatusPill)", () => {
    const { rerender } = render(<Badge status="Approved" />);
    expect(screen.getByText("Approved").className).toContain("tone-good");
    rerender(<Badge status="Failed" />);
    expect(screen.getByText("Failed").className).toContain("tone-bad");
    rerender(<Badge status="Proposed" />);
    expect(screen.getByText("Proposed").className).toContain("tone-warn");
    rerender(<Badge status="Pending" />);
    expect(screen.getByText("Pending").className).toContain("tone-info");
  });

  it("infers tone from children when only children are given", () => {
    render(<Badge>certified</Badge>);
    expect(screen.getByText("certified").className).toContain("tone-good");
  });

  it("explicit tone wins over status inference; size sm applies", () => {
    render(
      <Badge tone="muted" status="failed" size="sm">
        Draft
      </Badge>,
    );
    const badge = screen.getByText("Draft");
    expect(badge.className).toContain("tone-muted");
    expect(badge.className).toContain("size-sm");
  });
});
