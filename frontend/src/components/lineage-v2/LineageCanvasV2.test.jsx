import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import * as helpers from "./LineageCanvasV2.test-helpers";

vi.mock("@xyflow/react", () => {
  const Handle = () => null;
  const ReactFlow = ({ children, maxZoom, nodes, onNodeMouseEnter, onNodeMouseLeave }) => (
    <div data-max-zoom={maxZoom} data-testid="rf-canvas">
      {nodes.map((node) => {
        const NodeType = node.type ? helpers.TYPES[node.type] : null;
        return (
          <div
            data-testid={`rf-node-${node.id}`}
            key={node.id}
            onMouseEnter={(e) => onNodeMouseEnter && onNodeMouseEnter(e, node)}
            onMouseLeave={() => onNodeMouseLeave && onNodeMouseLeave()}
          >
            {NodeType ? <NodeType data={node.data} /> : null}
          </div>
        );
      })}
      {children}
    </div>
  );
  return {
    Background: () => null,
    Controls: () => <div data-testid="rf-controls" />,
    Handle,
    MarkerType: { ArrowClosed: "arrowclosed" },
    Position: { Left: "left", Right: "right" },
    ReactFlow,
    ReactFlowProvider: ({ children }) => <>{children}</>,
    useReactFlow: () => ({ fitView: vi.fn() }),
    useUpdateNodeInternals: () => vi.fn(),
  };
});

import { LineageCanvasV2 } from "./LineageCanvasV2";

const baseGraph = {
  focus: { id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus" },
  nodes: [
    {
      id: "focus-a",
      fqn: "emet.x.focus",
      label: "focus",
      kind: "table",
      isFocus: true,
      isOpenable: true,
      rowCount: "1.2M",
      freshness: "2h ago",
    },
    {
      id: "u1",
      fqn: "emet.x.upstream",
      label: "upstream",
      kind: "table",
      isFocus: false,
      isOpenable: true,
      rowCount: "8.4M",
    },
    {
      id: "u2",
      fqn: "emet.x.lineage_only",
      label: "lineage_only",
      kind: "table",
      isFocus: false,
      isOpenable: false,
    },
  ],
  edges: [
    { id: "e1", source: "u1", target: "focus-a", isRestricted: false },
    { id: "e2", source: "u2", target: "focus-a", isRestricted: false },
  ],
  columnEdges: [],
};

beforeEach(() => {
  helpers.TYPES.lineage = ({ data }) => (
    <button
      data-testid={`card-${data.node.id}`}
      onClick={() => data.onSelect(data.node)}
      type="button"
    >
      {data.node.label}
    </button>
  );
});

describe("LineageCanvasV2", () => {
  it("renders the hydrating state when graph has no nodes and hydrating=true", () => {
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={{ focus: null, nodes: [], edges: [], columnEdges: [] }}
        hydrating={true}
        onFocusChange={() => {}}
      />,
    );
    expect(screen.getByText("Loading lineage from Unity Catalog")).toBeTruthy();
  });

  // Stub-only pending shapes (adversarial verify P0): the cold-cache
  // deferred payload carries exactly ONE stub focus node and zero edges. A
  // single stub must not suppress the hydrating/warming states — the old
  // "no nodes" gate left the user with a near-empty flow canvas, no
  // progress copy, and no Retry.
  it("renders the hydrating state for the one-stub-node pending graph", () => {
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={{
          focus: { id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus" },
          nodes: [{ id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus", kind: "table" }],
          edges: [],
          columnEdges: [],
        }}
        hydrating={true}
        onFocusChange={() => {}}
      />,
    );
    expect(screen.getByText("Loading lineage from Unity Catalog")).toBeTruthy();
  });

  it("renders the warming retry state for the one-stub-node graph after poll exhaustion", () => {
    const onRetry = vi.fn();
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={{
          focus: { id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus" },
          nodes: [{ id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus", kind: "table" }],
          edges: [],
          columnEdges: [],
        }}
        hydrating={false}
        onFocusChange={() => {}}
        onRetry={onRetry}
        warming={true}
      />,
    );
    expect(screen.getByText("Lineage is still warming")).toBeTruthy();
    fireEvent.click(screen.getByText("Retry lineage"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  // Truncation honesty (adversarial verify P1): when the adapter-merged
  // graph.meta carries truncation totals, the canvas caption must state the
  // exact shown-of-total counts instead of the static 1-hop hint.
  it("captions exact truncation totals when the backend capped the graph", () => {
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={{
          ...baseGraph,
          meta: {
            truncation: { nodesShown: 21, nodesTotal: 660, edgesShown: 20, edgesTotal: 659 },
            upstreamTruncated: true,
            downstreamTruncated: false,
          },
        }}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    expect(
      screen.getByText("Showing 20 of 659 edges — highest-traffic neighbors first"),
    ).toBeTruthy();
  });

  it("renders the error state when error is set", () => {
    render(
      <LineageCanvasV2
        error="Asset not visible to actor"
        focusId="emet.x.focus"
        graph={{ focus: null, nodes: [], edges: [], columnEdges: [] }}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    expect(screen.getByText("Lineage unavailable")).toBeTruthy();
    expect(screen.getByText("Asset not visible to actor")).toBeTruthy();
  });

  it("renders one rf-node per graph node when nodes are present", () => {
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    expect(screen.getByTestId("rf-node-focus-a")).toBeTruthy();
    expect(screen.getByTestId("rf-node-u1")).toBeTruthy();
    expect(screen.getByTestId("rf-node-u2")).toBeTruthy();
  });

  it("keeps enough max zoom headroom for visible canvas controls", () => {
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    expect(Number(screen.getByTestId("rf-canvas").dataset.maxZoom)).toBeGreaterThan(2);
  });

  it("calls onFocusChange when a navigable node card is clicked", () => {
    const onFocusChange = vi.fn();
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={onFocusChange}
      />,
    );
    fireEvent.click(screen.getByTestId("card-u1"));
    expect(onFocusChange).toHaveBeenCalledWith("emet.x.upstream");
  });

  it("does NOT call onFocusChange for lineage-only (isOpenable=false) nodes", () => {
    const onFocusChange = vi.fn();
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={onFocusChange}
      />,
    );
    fireEvent.click(screen.getByTestId("card-u2"));
    expect(onFocusChange).not.toHaveBeenCalled();
  });

  it("keeps accumulated topology when the same FQN returns with a new focus node id", async () => {
    const nextGraph = {
      focus: { id: "focus-upstream", fqn: "emet.x.upstream", isFocus: true, label: "upstream" },
      nodes: [
        {
          id: "focus-upstream",
          fqn: "emet.x.upstream",
          label: "upstream",
          kind: "table",
          isFocus: true,
          isOpenable: true,
        },
        {
          id: "target-new",
          fqn: "emet.x.new_target",
          label: "new_target",
          kind: "table",
          isOpenable: true,
        },
      ],
      edges: [{ id: "e-new", source: "focus-upstream", target: "target-new" }],
      columnEdges: [],
    };
    const { rerender } = render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    rerender(
      <LineageCanvasV2
        error=""
        focusId="emet.x.upstream"
        graph={nextGraph}
        hydrating={false}
        onFocusChange={() => {}}
      />,
    );
    expect(await screen.findByTestId("rf-node-focus-a")).toBeTruthy();
    expect(screen.getByTestId("rf-node-focus-upstream")).toBeTruthy();
    expect(screen.getByTestId("rf-node-target-new")).toBeTruthy();
  });

  // Type filters (owner direction #2a): the legend chips toggle node kinds
  // and re-layout live; the direction segment scopes upstream/downstream.
  const mixedGraph = {
    focus: { id: "focus-a", fqn: "emet.x.focus", isFocus: true, label: "focus" },
    nodes: [
      { id: "focus-a", fqn: "emet.x.focus", label: "focus", kind: "table", isFocus: true, isOpenable: true },
      { id: "up1", fqn: "emet.x.upstream", label: "upstream", kind: "table", isOpenable: true },
      { id: "job1", fqn: "emet.x.job", label: "job", kind: "job", isOpenable: true },
    ],
    edges: [
      { id: "e-up", source: "up1", target: "focus-a", isRestricted: false },
      { id: "e-job", source: "focus-a", target: "job1", isRestricted: false },
    ],
    columnEdges: [],
  };

  it("hides a node kind when its legend chip is toggled off, then restores on reset", () => {
    render(
      <LineageCanvasV2 error="" focusId="emet.x.focus" graph={mixedGraph} hydrating={false} onFocusChange={() => {}} />,
    );
    expect(screen.getByTestId("rf-node-job1")).toBeTruthy();
    fireEvent.click(screen.getByTitle(/Hide Job nodes/i));
    expect(screen.queryByTestId("rf-node-job1")).toBeNull();
    // Focus + the still-enabled upstream survive.
    expect(screen.getByTestId("rf-node-focus-a")).toBeTruthy();
    expect(screen.getByTestId("rf-node-up1")).toBeTruthy();
    fireEvent.click(screen.getByText("Reset"));
    expect(screen.getByTestId("rf-node-job1")).toBeTruthy();
  });

  it("scopes to upstream when the Upstream direction is selected", () => {
    render(
      <LineageCanvasV2 error="" focusId="emet.x.focus" graph={mixedGraph} hydrating={false} onFocusChange={() => {}} />,
    );
    fireEvent.click(screen.getByTitle("Show upstream assets"));
    // Downstream job drops; upstream + focus stay.
    expect(screen.queryByTestId("rf-node-job1")).toBeNull();
    expect(screen.getByTestId("rf-node-up1")).toBeTruthy();
    expect(screen.getByTestId("rf-node-focus-a")).toBeTruthy();
  });

  it("DOES call onFocusChange when clicking the focus node — selection state, not refetch", () => {
    // Click is now a client-side selection event. The handler can fire
    // even on the URL-focus node so the user can re-select it after
    // visiting a different card. The parent decides whether to refetch
    // (it does NOT — focus-change is rail/highlight only; URL change is
    // gated behind an explicit "Re-anchor" button).
    const onFocusChange = vi.fn();
    render(
      <LineageCanvasV2
        error=""
        focusId="emet.x.focus"
        graph={baseGraph}
        hydrating={false}
        onFocusChange={onFocusChange}
      />,
    );
    fireEvent.click(screen.getByTestId("card-focus-a"));
    expect(onFocusChange).toHaveBeenCalledWith("emet.x.focus");
  });
});
