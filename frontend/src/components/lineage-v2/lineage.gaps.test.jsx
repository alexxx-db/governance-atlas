/**
 * Regression tests for the lineage-v2 KIT's gap fixes:
 *
 * L4/L9 — card foot renders backend loading / restricted status lines muted.
 * L2 (helper) — deriveCardStats derives rows/size/owner from a batch header.
 *
 * The workspace-level gap tests (L1/L2/L3/L5/L6/L10/L12/L13) moved to
 * surfaces/lineage/__tests__/lineage.gaps.test.jsx in Wave C7, when the
 * legacy LineageWorkspace host was deleted and the surface rebuilt as
 * surfaces/lineage/LineagePage.jsx.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LineageNodeCard, deriveCardStats } from "./LineageNodeCard";

describe("LineageNodeCard status foot lines (L4/L9)", () => {
  const bareNode = {
    id: "n",
    fqn: "a.b.n",
    label: "n",
    kind: "table",
    apiKind: "",
    rowCount: null,
    freshness: "",
    owners: [],
    ownerCount: 0,
    recentActivityCount: 0,
    columns: [],
  };

  it("renders the restricted foot line muted (single line, L9)", () => {
    const { container } = render(
      <LineageNodeCard node={{ ...bareNode, isOpenable: false, foot: ["Not visible to your account"] }} />,
    );
    const line = screen.getByText("Not visible to your account");
    expect(line.className).toContain("is-empty");
    expect(container.querySelectorAll(".ax-lineage-v2-card-foot .is-empty")).toHaveLength(1);
  });

  it("renders the cold-cache loading foot line muted (L4)", () => {
    render(<LineageNodeCard node={{ ...bareNode, foot: ["Loading metadata…"] }} />);
    const line = screen.getByText("Loading metadata…");
    expect(line.className).toContain("is-empty");
  });
});

describe("deriveCardStats header derivation (L2 helper)", () => {
  it("derives rows/size/owner from a batch header and skips placeholders", () => {
    const stats = deriveCardStats(
      { apiKind: "Table", owners: [] },
      {
        rows: "8.4M",
        size: "1.1 GiB",
        files: "—",
        owners: [{ displayName: "Peer Owner" }],
        managementType: "Managed",
        objectType: "Table",
      },
    );
    expect(stats.rowCount).toBe("8.4M");
    expect(stats.size).toBe("1.1 GiB");
    expect(stats.files).toBeNull(); // "—" placeholder suppressed
    expect(stats.ownerLabel).toBe("Peer Owner");
    expect(stats.typeLabel).toBe("Managed · Table");
  });
});
