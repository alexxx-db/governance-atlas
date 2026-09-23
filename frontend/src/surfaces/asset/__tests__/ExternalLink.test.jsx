import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExternalLink, catalogExplorerUrl } from "../ExternalLink";

const HOST = "https://example.cloud.databricks.com";

describe("catalogExplorerUrl — deepLink-first, constructed fallback", () => {
  it("prefers a relative access deepLink, made absolute against the workspace host", () => {
    expect(catalogExplorerUrl("main.sales.orders", "/explore/data/main/sales/orders", HOST)).toBe(
      `${HOST}/explore/data/main/sales/orders`,
    );
  });

  it("passes an already-absolute deepLink through untouched", () => {
    const abs = "https://other.databricks.com/explore/data/a/b/c";
    expect(catalogExplorerUrl("a.b.c", abs)).toBe(abs);
  });

  it("constructs the Catalog Explorer URL from a real three-part FQN when no deepLink", () => {
    expect(catalogExplorerUrl("main.sales.orders", "", HOST)).toBe(
      `${HOST}/explore/data/main/sales/orders`,
    );
  });

  it("joins remaining name segments like the backend does (dotted object names)", () => {
    expect(catalogExplorerUrl("cat.sch.part.name", "", HOST)).toBe(
      `${HOST}/explore/data/cat/sch/part/name`,
    );
  });

  it("returns '' for anything that is not an addressable three-part object", () => {
    expect(catalogExplorerUrl("main.sales", "", HOST)).toBe("");
    expect(catalogExplorerUrl("", "")).toBe("");
    expect(catalogExplorerUrl(undefined, undefined)).toBe("");
  });
});

describe("catalogExplorerUrl without a workspace host", () => {
  it("renders no link for relative targets instead of one that 404s on the app origin", () => {
    expect(catalogExplorerUrl("main.sales.orders", "/explore/data/main/sales/orders")).toBe("");
    expect(catalogExplorerUrl("main.sales.orders", "")).toBe("");
  });
});

describe("ExternalLink component", () => {
  it("renders a new-tab, noopener anchor with the contractual title", () => {
    render(<ExternalLink href={`${HOST}/explore/data/main/sales/orders`} />);
    const link = screen.getByRole("link", { name: "Open in Databricks" });
    expect(link.getAttribute("href")).toBe(`${HOST}/explore/data/main/sales/orders`);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("title")).toBe("Open in Databricks Catalog Explorer");
  });

  it("renders nothing without an href (no dead control)", () => {
    const { container } = render(<ExternalLink href="" />);
    expect(container.querySelector("a")).toBeNull();
  });
});
