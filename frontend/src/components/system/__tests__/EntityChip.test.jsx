import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { EntityChip } from "../EntityChip";

function linkHref() {
  return screen.getByRole("link").getAttribute("href");
}

describe("EntityChip — the keystone: every entity mention is a real anchor", () => {
  it.each([
    [{ kind: "asset", fqn: "main.sales.orders" }, "/assets/main.sales.orders"],
    [{ kind: "term", id: "term-9" }, "/glossary/term-9"],
    [{ kind: "lineage", fqn: "main.sales.orders" }, "/lineage/main.sales.orders"],
  ])("renders %o as an <a> with the canonical href", (entity, expected) => {
    render(<EntityChip entity={entity} />);
    expect(linkHref()).toBe(expected);
  });

  it("renders every contract kind as a link (asset, column, term, cde, owner, request, event, domain, catalog)", () => {
    const entities = [
      { kind: "asset", fqn: "a.b.c" },
      { kind: "column", fqn: "a.b.c", id: "col1" },
      { kind: "term", id: "t1" },
      { kind: "cde", id: "cde1" },
      { kind: "owner", id: "jane@shorecp.com" },
      { kind: "request", id: "GOV-11112222" },
      { kind: "event", id: "AUD-33334444" },
      { kind: "domain", name: "Finance" },
      { kind: "catalog", name: "main" },
    ];
    render(
      <div>
        {entities.map((entity, index) => (
          <EntityChip key={index} entity={entity} />
        ))}
      </div>,
    );
    const links = screen.getAllByRole("link");
    expect(links.length).toBe(entities.length);
    for (const link of links) {
      expect(link.tagName).toBe("A");
      expect(link.getAttribute("href")).toBeTruthy();
    }
  });

  it("query-param kinds point at their canonical destinations", () => {
    render(
      <div>
        <EntityChip entity={{ kind: "owner", id: "jane@shorecp.com" }} />
        <EntityChip entity={{ kind: "request", id: "GOV-BE17D517" }} />
        <EntityChip entity={{ kind: "event", id: "AUD-DEADBEEF" }} />
        <EntityChip entity={{ kind: "cde", id: "CDE-4" }} />
      </div>,
    );
    const [owner, request, event, cde] = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(owner.startsWith("/discovery?")).toBe(true);
    expect(new URLSearchParams(owner.split("?")[1]).get("q")).toBe('owner:"jane@shorecp.com"');
    expect(request.startsWith("/stewardship?")).toBe(true);
    expect(new URLSearchParams(request.split("?")[1]).get("item")).toBe("GOV-BE17D517");
    expect(event.startsWith("/evidence?")).toBe(true);
    expect(new URLSearchParams(event.split("?")[1]).get("event")).toBe("AUD-DEADBEEF");
    expect(cde.startsWith("/glossary?")).toBe(true);
    expect(new URLSearchParams(cde.split("?")[1]).get("cde")).toBe("CDE-4");
  });

  it("renders a non-principal owner as plain text, never a link to a nonexistent user", () => {
    render(<EntityChip entity={{ kind: "owner", email: "identity-integrity-cleanup", label: "identity-integrity-cleanup" }} />);
    // No link is emitted…
    expect(screen.queryByRole("link")).toBeNull();
    // …but the name still shows as plain muted text.
    const span = screen.getByText("identity-integrity-cleanup");
    expect(span.tagName).toBe("SPAN");
    expect(span.className).toContain("ax-sys-owner-plain");
  });

  it("the FQN text is the anchor label by default (law: text is the anchor)", () => {
    render(<EntityChip entity={{ kind: "asset", fqn: "main.sales.orders" }} />);
    expect(screen.getByRole("link").textContent).toContain("main.sales.orders");
  });

  it("uses entity.label / children overrides when provided", () => {
    const { rerender } = render(
      <EntityChip entity={{ kind: "asset", fqn: "a.b.c", label: "Orders" }} />,
    );
    expect(screen.getByRole("link").textContent).toContain("Orders");
    rerender(<EntityChip entity={{ kind: "asset", fqn: "a.b.c", label: "Orders" }}>Custom</EntityChip>);
    expect(screen.getByRole("link").textContent).toContain("Custom");
  });

  it("applies appearance and kind classes", () => {
    render(<EntityChip entity={{ kind: "owner", id: "x@y.z" }} appearance="row" />);
    const link = screen.getByRole("link");
    expect(link.className).toContain("is-row");
    expect(link.className).toContain("is-kind-owner");
    expect(link.getAttribute("data-kind")).toBe("owner");
  });

  it("renders nothing (not a dead control) for unresolvable refs", () => {
    const { container } = render(<EntityChip entity={{ kind: "asset" }} />);
    expect(container.firstChild).toBeNull();
  });

  it("navigate adapter intercepts plain left-click and receives the entity + href", () => {
    const navigate = vi.fn();
    render(<EntityChip entity={{ kind: "term", id: "t1" }} navigate={navigate} />);
    fireEvent.click(screen.getByRole("link"));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate.mock.calls[0][0]).toEqual({ kind: "term", id: "t1" });
    expect(navigate.mock.calls[0][1]).toEqual({ href: "/glossary/t1" });
  });

  it("modified clicks (new-tab intent) are NOT intercepted by the adapter", () => {
    const navigate = vi.fn();
    render(<EntityChip entity={{ kind: "term", id: "t1" }} navigate={navigate} />);
    const link = screen.getByRole("link");
    fireEvent.click(link, { metaKey: true });
    fireEvent.click(link, { ctrlKey: true });
    fireEvent.click(link, { shiftKey: true });
    fireEvent.click(link, { button: 1 });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("renders a router <Link> inside a Router (client-side nav) and plain <a> outside", () => {
    render(
      <MemoryRouter>
        <EntityChip entity={{ kind: "asset", fqn: "a.b.c" }} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link").getAttribute("href")).toBe("/assets/a.b.c");
  });

  it("withHover renders a supplementary aria-hidden hover card with the full identity", () => {
    render(
      <EntityChip
        entity={{ kind: "asset", fqn: "main.sales.orders", label: "Orders", meta: { rows: "1.2M" } }}
        withHover
      />,
    );
    const link = screen.getByRole("link");
    const hover = link.querySelector(".ax-sys-entity-hover");
    expect(hover).not.toBeNull();
    expect(hover.getAttribute("aria-hidden")).toBe("true");
    expect(hover.textContent).toContain("main.sales.orders");
    expect(hover.textContent).toContain("1.2M");
  });
});
