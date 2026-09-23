import { describe, expect, it } from "vitest";
import {
  catalogExplorerUrl,
  workspaceHostFromBootstrap,
} from "../lineagePresentation.js";

/*
 * Deep-link construction is a honesty-sensitive helper (owner direction #2c):
 * it must prefer a backend-supplied deepLink path, construct the exact Catalog
 * Explorer shape the backend itself emits when it can, and return "" (never a
 * dead or wrong link) when it can't stand behind one.
 */
describe("catalogExplorerUrl", () => {
  const host = "https://example.cloud.databricks.com";

  it("constructs /explore/data/<catalog>/<schema>/<table> from host + fqn", () => {
    expect(catalogExplorerUrl("cat.sch.tbl", host)).toBe(
      `${host}/explore/data/cat/sch/tbl`,
    );
  });

  it("prefers an absolute backend deepLink verbatim", () => {
    const absolute = "https://other.databricks.com/explore/data/a/b/c";
    expect(catalogExplorerUrl("cat.sch.tbl", host, absolute)).toBe(absolute);
  });

  it("absolutizes a relative backend deepLink against the workspace host", () => {
    expect(catalogExplorerUrl("cat.sch.tbl", host, "/explore/data/x/y/z")).toBe(
      `${host}/explore/data/x/y/z`,
    );
  });

  it("adds a protocol when the host lacks one", () => {
    expect(catalogExplorerUrl("cat.sch.tbl", "dbc-x.cloud.databricks.com")).toBe(
      "https://dbc-x.cloud.databricks.com/explore/data/cat/sch/tbl",
    );
  });

  it("returns '' when there is no host and no absolute deepLink", () => {
    expect(catalogExplorerUrl("cat.sch.tbl", "")).toBe("");
  });

  it("returns '' for a non-three-part fqn with no deepLink", () => {
    expect(catalogExplorerUrl("cat.sch", host)).toBe("");
  });
});

describe("workspaceHostFromBootstrap", () => {
  it("reads shell.workspaceHost first", () => {
    expect(workspaceHostFromBootstrap({ shell: { workspaceHost: "h1" } })).toBe("h1");
  });
  it("falls back to shell.environment.workspaceHost", () => {
    expect(
      workspaceHostFromBootstrap({ shell: { environment: { workspaceHost: "h2" } } }),
    ).toBe("h2");
  });
  it("returns '' when absent", () => {
    expect(workspaceHostFromBootstrap(null)).toBe("");
    expect(workspaceHostFromBootstrap({})).toBe("");
  });
});
