import { memo, useCallback, useEffect, useMemo, useState } from "react";
import dagre from "dagre";
import {
  Background,
  Controls,
  // @ts-ignore @xyflow/react exports Handle as a runtime component and a legacy type alias.
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useUpdateNodeInternals,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { LineageNodeCard } from "./LineageNodeCard";
import { mergeAccumulatedGraph } from "./mergeAccumulatedGraph";
import { catalogExplorerUrl } from "../../surfaces/lineage/lineagePresentation";

/**
 * LineageCanvasV2 — design-faithful lineage canvas built on React Flow.
 *
 * Layout is dagre-driven (Sugiyama / layered DAG) with rankdir = LR so
 * upstream nodes always sit to the LEFT of focus and downstream nodes
 * always sit to the RIGHT. Multi-parent / multi-child topologies route
 * cleanly without overlapping siblings. Ranks are stable across re-anchors
 * because dagre considers the entire returned graph and assigns each
 * node a deterministic rank from edge structure.
 *
 * Interaction:
 *   wheel = zoom only (React Flow handles the preventDefault for us)
 *   drag = pan (React Flow built-in)
 *   click node card = re-anchor focus (calls onFocusChange)
 *   hover node card = trace the connected subgraph
 *
 * The toolbar is docked top-right inside the canvas (React Flow's <Controls>
 * gives us the +/-/fit set) so it can never end up floating outside the
 * graph viewport like the legacy `.ax-lineage-canvas-tools` did.
 */

const NODE_WIDTH = 224;
const NODE_HEIGHT_COMPACT = 96;
const NODE_HEIGHT_TALL = 230;
const RANK_SEP = 86; // horizontal gap between dagre ranks (pixels)
const NODE_SEP = 16; // vertical gap between siblings in the same rank (pixels)
const EDGE_SEP = 14;

// ---------------------------------------------------------------------------
// Dagre layout: feed the entire (nodes, edges) set into a directed graph
// with rankdir = LR (left-to-right). Dagre handles multi-parent + multi-child
// topologies by assigning each node a stable rank based on longest path and
// minimizing edge crossings. The resulting positions are absolute pixel
// coords we hand straight to React Flow.
// ---------------------------------------------------------------------------
function computeDagreLayout(nodes, edges) {
  if (!nodes.length) return new Map();
  const g = new dagre.graphlib.Graph({ multigraph: false, compound: false });
  g.setGraph({
    rankdir: "LR",
    ranksep: RANK_SEP,
    nodesep: NODE_SEP,
    edgesep: EDGE_SEP,
    marginx: 24,
    marginy: 24,
  });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((node) => {
    g.setNode(node.id, {
      width: NODE_WIDTH,
      height: nodeIsTall(node) ? NODE_HEIGHT_TALL : NODE_HEIGHT_COMPACT,
    });
  });

  edges.forEach((edge) => {
    if (!g.hasNode(edge.source) || !g.hasNode(edge.target)) return;
    g.setEdge(edge.source, edge.target);
  });

  dagre.layout(g);

  const positions = new Map();
  nodes.forEach((node) => {
    const layoutNode = g.node(node.id);
    if (!layoutNode) return;
    // dagre returns center positions; React Flow expects top-left.
    positions.set(node.id, {
      x: layoutNode.x - NODE_WIDTH / 2,
      y: layoutNode.y - (nodeIsTall(node) ? NODE_HEIGHT_TALL : NODE_HEIGHT_COMPACT) / 2,
    });
  });
  return positions;
}

function nodeIsTall(node) {
  return Boolean(node?.columns?.length);
}

// ---------------------------------------------------------------------------
// React Flow node component — wraps LineageNodeCard with React Flow's
// connection handles. Both sides of the card have a handle so edges can
// enter from the left and exit on the right.
// ---------------------------------------------------------------------------
/**
 * @param {{ data: any }} props
 */
function LineageFlowNodeComponent({ data }) {
  return (
    <div className="ax-lineage-v2-flow-node">
      <Handle
        className="ax-lineage-v2-flow-handle"
        position={Position.Left}
        type="target"
      />
      <LineageNodeCard
        databricksHref={data.databricksHref}
        header={data.header}
        isDimmed={data.isDimmed}
        isFocus={data.isFocus}
        isHovered={data.isHovered}
        isSelected={data.isSelected}
        isTraced={data.isTraced}
        node={data.node}
        onClick={data.onSelect}
        onColumnSelect={data.onColumnSelect}
        onOpenAsset={data.onOpenAsset}
        selectedColumnName={data.selectedColumnName}
        variant={nodeIsTall(data.node) ? "tall" : "compact"}
      />
      <Handle
        className="ax-lineage-v2-flow-handle"
        position={Position.Right}
        type="source"
      />
    </div>
  );
}

const LineageFlowNode = memo(LineageFlowNodeComponent);

const NODE_TYPES = { lineage: LineageFlowNode };

/**
 * Graph-shaped loading skeleton (owner direction #4). Instead of a bare
 * spinner, we shimmer a miniature upstream → focus → downstream topology so
 * the wait reads as "a graph is assembling", plus an honest caption of what
 * is loading. Purely decorative — aria-hidden, with a polite status label.
 */
function LineageGraphSkeleton({ caption = "Loading lineage from Unity Catalog…" }) {
  const upstream = [0, 1, 2];
  const downstream = [0, 1];
  return (
    <div className="ax-lineage-v2-skeleton" role="status" aria-live="polite">
      <div className="ax-lineage-v2-skeleton-stage" aria-hidden="true">
        <svg className="ax-lineage-v2-skeleton-edges" viewBox="0 0 100 100" preserveAspectRatio="none">
          {upstream.map((i) => (
            <path key={`u${i}`} d={`M20 ${22 + i * 28} C 38 ${22 + i * 28}, 40 50, 50 50`} />
          ))}
          {downstream.map((i) => (
            <path key={`d${i}`} d={`M50 50 C 60 50, 62 ${34 + i * 32}, 80 ${34 + i * 32}`} />
          ))}
        </svg>
        <div className="ax-lineage-v2-skeleton-col is-upstream">
          {upstream.map((i) => (
            <span className="ax-lineage-v2-skeleton-card" key={`uc${i}`} />
          ))}
        </div>
        <div className="ax-lineage-v2-skeleton-col is-focus">
          <span className="ax-lineage-v2-skeleton-card is-focus" />
        </div>
        <div className="ax-lineage-v2-skeleton-col is-downstream">
          {downstream.map((i) => (
            <span className="ax-lineage-v2-skeleton-card" key={`dc${i}`} />
          ))}
        </div>
      </div>
      {caption ? (
        <div className="ax-lineage-v2-skeleton-caption">
          <span aria-hidden="true" className="ax-lineage-v2-canvas-spinner" />
          <span>{caption}</span>
        </div>
      ) : null}
    </div>
  );
}

// Human labels for the kind filter/legend (owner direction #2a + #3 legend).
const KIND_LABELS = {
  table: "Table",
  pipeline: "Pipeline",
  job: "Job",
  notebook: "Notebook",
  "saved-query": "Query",
  dashboard: "Dashboard",
  model: "Model",
  udf: "Function",
  volume: "Volume",
  restricted: "Reference",
};

function kindLabel(kind) {
  return KIND_LABELS[kind] || (kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : "Asset");
}

// Directed reachability from the focus node id: `upstream` = nodes that flow
// INTO the focus (follow target→source), `downstream` = nodes the focus flows
// INTO (follow source→target). Used to bucket the type filters by direction
// and to power the Upstream/Downstream direction toggle. Classification runs
// over the FULL edge set so hidden nodes still carry a correct direction.
function directedReach(edges, focusId, forward) {
  const adj = new Map();
  edges.forEach((edge) => {
    const from = forward ? edge.source : edge.target;
    const to = forward ? edge.target : edge.source;
    if (!adj.has(from)) adj.set(from, []);
    adj.get(from).push(to);
  });
  const seen = new Set();
  const queue = [focusId];
  while (queue.length) {
    const next = queue.shift();
    (adj.get(next) || []).forEach((id) => {
      if (seen.has(id)) return;
      seen.add(id);
      queue.push(id);
    });
  }
  seen.delete(focusId);
  return seen;
}

function buildAdjacency(edges) {
  const adjacency = new Map();
  edges.forEach((edge) => {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
    adjacency.get(edge.source).add(edge.target);
    adjacency.get(edge.target).add(edge.source);
  });
  return adjacency;
}

function tracedSubgraph(adjacency, seedId) {
  if (!seedId || !adjacency.has(seedId)) return new Set();
  const visited = new Set([seedId]);
  const queue = [seedId];
  while (queue.length) {
    const next = queue.shift();
    (adjacency.get(next) || []).forEach((id) => {
      if (visited.has(id)) return;
      visited.add(id);
      queue.push(id);
    });
  }
  return visited;
}

function CanvasInner({
  graph,
  hydrating,
  error,
  onFocusChange,
  focusId,
  nodeHeaders = new Map(),
  selectedNodeFqn = "",
  selectedColumn = null,
  onColumnSelect = null,
  warming = false,
  onRetry = null,
  onRenderedGraphChange = null,
  onOpenAsset = null,
  workspaceHost = "",
  minZoom = 0.5,
}) {
  const reactFlow = useReactFlow();
  const updateNodeInternals = useUpdateNodeInternals();
  const [hoveredNodeId, setHoveredNodeId] = useState("");
  // Canvas-level view filters (owner direction #2a). `disabledKinds` holds the
  // kinds the user has toggled OFF (storing the OFF set means any newly-
  // arrived kind defaults to visible as the accumulated graph grows). The
  // `direction` segment scopes to upstream/downstream relative to focus.
  const [disabledKinds, setDisabledKinds] = useState(() => new Set());
  const [direction, setDirection] = useState("all");
  // Accumulated graph: the merged superset of nodes/edges seen across
  // all lineage payloads received THIS focus session. Two regimes:
  //   • EXPAND: the new payload's focus node is already in the merged
  //     set (because the user clicked it from the canvas, which fired
  //     onFocusChange → URL change → refetch). Merge new neighbors in
  //     additively so the canvas extends outward — the seamless UX.
  //   • RESET: the new payload's focus node is NOT in the merged set
  //     (external navigation: the user typed a new URL, used the
  //     hero search, or routed in from another page). Discard the
  //     accumulated state and start fresh — the merged set from the
  //     previous focus is irrelevant to this asset and would just
  //     confuse the dagre layout (and previously left the canvas
  //     blank when the new focus had nothing in common with the old).
  const [accumulatedGraph, setAccumulatedGraph] = useState(() =>
    mergeAccumulatedGraph(
      { nodes: [], edges: [] },
      { nodes: graph.nodes, edges: graph.edges, focus: graph.focus },
    ),
  );
  useEffect(() => {
    if (!graph.nodes.length && !graph.edges.length) return;
    // EXPAND vs RESET and node/edge merging are FQN-keyed (see
    // mergeAccumulatedGraph): the API assigns role-prefixed ids so the same
    // asset changes id when it becomes the focus. Comparing by raw id here
    // made every in-canvas click RESET the graph instead of extending it.
    setAccumulatedGraph((current) =>
      mergeAccumulatedGraph(current, {
        nodes: graph.nodes,
        edges: graph.edges,
        focus: graph.focus,
      }),
    );
  }, [graph.nodes, graph.edges, graph.focus]);

  // Render from the accumulated set so the canvas never blanks while a
  // refetch is in flight. The accumulated set always contains at least
  // the current graph after the effect above runs.
  const nodesArray = accumulatedGraph.nodes.length ? accumulatedGraph.nodes : graph.nodes;
  const edgesArray = accumulatedGraph.edges.length ? accumulatedGraph.edges : graph.edges;
  const useSticky = !graph.nodes.length && accumulatedGraph.nodes.length > 0;
  // Report the RENDERED graph (accumulated superset) upward so chrome like
  // the hero's "N edges" chip reflects what the user actually sees, not the
  // raw in-flight payload (which reads "0 edges / Hydrating…" mid-refocus
  // while edges are visibly drawn — persona audit P2).
  useEffect(() => {
    onRenderedGraphChange?.({
      nodeCount: nodesArray.length,
      edgeCount: edgesArray.length,
      sticky: useSticky,
    });
  }, [nodesArray.length, edgesArray.length, useSticky, onRenderedGraphChange]);
  // Reset the view filters whenever the focus asset changes (a genuine
  // re-anchor / fresh navigation). Keyed on the focus FQN so an in-place
  // EXPAND (same focus, more neighbors) keeps the user's chosen filters.
  const focusFqnForReset = graph.focus?.fqn || "";
  useEffect(() => {
    setDisabledKinds(new Set());
    setDirection("all");
  }, [focusFqnForReset]);

  // Classify every node's direction relative to the focus and tally kind
  // counts (owner direction #2a: "counts"). Runs over the full accumulated
  // set so the legend describes the whole graph, not the filtered view.
  const focusNodeId = useMemo(() => {
    const byFqn = focusFqnForReset
      ? nodesArray.find((node) => node.fqn === focusFqnForReset)
      : null;
    return byFqn?.id || nodesArray.find((node) => node.isFocus)?.id || "";
  }, [nodesArray, focusFqnForReset]);
  const upstreamIds = useMemo(
    () => (focusNodeId ? directedReach(edgesArray, focusNodeId, false) : new Set()),
    [edgesArray, focusNodeId],
  );
  const downstreamIds = useMemo(
    () => (focusNodeId ? directedReach(edgesArray, focusNodeId, true) : new Set()),
    [edgesArray, focusNodeId],
  );
  const directionOf = useCallback(
    (node) => {
      if (!node || node.id === focusNodeId || node.fqn === focusFqnForReset) return "focus";
      if (upstreamIds.has(node.id)) return "upstream";
      if (downstreamIds.has(node.id)) return "downstream";
      return "other";
    },
    [upstreamIds, downstreamIds, focusNodeId, focusFqnForReset],
  );
  // Kind tallies split by direction — the legend chips show a total count and
  // the direction segment shows upstream/downstream totals.
  const kindMeta = useMemo(() => {
    const map = new Map();
    let upstreamTotal = 0;
    let downstreamTotal = 0;
    nodesArray.forEach((node) => {
      const dir = directionOf(node);
      if (dir === "upstream") upstreamTotal += 1;
      if (dir === "downstream") downstreamTotal += 1;
      if (dir === "focus") return;
      const entry = map.get(node.kind) || { kind: node.kind, count: 0, upstream: 0, downstream: 0 };
      entry.count += 1;
      if (dir === "upstream") entry.upstream += 1;
      if (dir === "downstream") entry.downstream += 1;
      map.set(node.kind, entry);
    });
    const kinds = [...map.values()].sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind));
    return { kinds, upstreamTotal, downstreamTotal, peerTotal: nodesArray.length - (focusNodeId ? 1 : 0) };
  }, [nodesArray, directionOf, focusNodeId]);

  const directionMatches = useCallback(
    (node) => {
      if (directionOf(node) === "focus") return true;
      if (direction === "all") return true;
      return directionOf(node) === direction;
    },
    [direction, directionOf],
  );

  // The filtered (visible) view fed to dagre + React Flow. The focus node is
  // always kept so the graph never loses its anchor. Edges survive only when
  // BOTH endpoints survive.
  const visibleNodes = useMemo(
    () =>
      nodesArray.filter(
        (node) =>
          directionOf(node) === "focus" ||
          (!disabledKinds.has(node.kind) && directionMatches(node)),
      ),
    [nodesArray, disabledKinds, directionMatches, directionOf],
  );
  const visibleIdSet = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edgesArray.filter((edge) => visibleIdSet.has(edge.source) && visibleIdSet.has(edge.target)),
    [edgesArray, visibleIdSet],
  );
  const filtersActive = disabledKinds.size > 0 || direction !== "all";
  const toggleKind = useCallback((kind) => {
    setDisabledKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);
  const resetFilters = useCallback(() => {
    setDisabledKinds(new Set());
    setDirection("all");
  }, []);

  const adjacency = useMemo(() => buildAdjacency(visibleEdges), [visibleEdges]);
  const tracedNodeIds = useMemo(() => tracedSubgraph(adjacency, hoveredNodeId), [adjacency, hoveredNodeId]);

  const handleNodeClick = useCallback(
    (node) => {
      if (!node) return;
      // Permission-honest: refuse to "select" a lineage-only / unverified
      // reference. The card already disables hover state for those.
      if (node.isOpenable === false) return;
      // Click triggers the parent's selection handler — the parent
      // updates BOTH the rail subject AND the URL (so a fresh
      // /api/lineage/<fqn> fires in the background). When that payload
      // arrives the canvas MERGES new neighbors into the accumulated
      // graph (above) instead of replacing — so the user sees the
      // graph extend outward toward the clicked node, never blanks.
      if (node.fqn) onFocusChange?.(node.fqn);
    },
    [onFocusChange],
  );

  const positions = useMemo(
    () => computeDagreLayout(visibleNodes, visibleEdges),
    [visibleNodes, visibleEdges],
  );

  // React Flow expects { id, position, data, type } for nodes and
  // { id, source, target, type } for edges. We wrap the node id in
  // a stable object so we can pass tracing flags into LineageFlowNode
  // through `data` without the parent re-mounting React Flow.
  // Single-FOCUS rule (persona audit P2): the accumulated graph keeps stale
  // node copies whose `isFocus` / kicker still say "Focus" from a previous
  // payload. Only the CURRENT payload focus may render the FOCUS treatment;
  // every other card is demoted to a plain peer.
  const currentFocusFqn = graph.focus?.fqn || "";
  const flowNodes = useMemo(() => {
    return visibleNodes.map((node) => {
      const position = positions.get(node.id) || { x: 0, y: 0 };
      const measuredHeight = nodeIsTall(node) ? NODE_HEIGHT_TALL : NODE_HEIGHT_COMPACT;
      const isFocus = currentFocusFqn
        ? node.fqn === currentFocusFqn
        : node.isFocus;
      const isHovered = hoveredNodeId === node.id;
      const isTraced = !hoveredNodeId || tracedNodeIds.has(node.id);
      const isDimmed = false;
      // The clicked / actively-selected node — distinct from the URL focus.
      // The card renders an extra "selected" outline so the user can see
      // exactly which card the rail is currently describing, separate from
      // the deep "FOCUS" highlight on the URL-anchored node.
      const isSelected = Boolean(selectedNodeFqn) && node.fqn === selectedNodeFqn;
      // Look up the per-node header batch-fetched by useLineageNodeHeaders.
      // This is what carries the UC-grade size / freshness / type / owner
      // detail that the lineage system tables don't expose. May be undefined
      // until the header request resolves; the card renders its API-foot
      // strings as a fallback.
      const header = nodeHeaders?.get?.(node.fqn) || null;
      return {
        id: node.id,
        type: "lineage",
        position,
        width: NODE_WIDTH,
        height: measuredHeight,
        initialWidth: NODE_WIDTH,
        initialHeight: measuredHeight,
        style: {
          width: NODE_WIDTH,
          height: measuredHeight,
        },
        data: {
          node,
          header,
          isFocus,
          isHovered,
          isTraced,
          isDimmed,
          isSelected,
          selectedColumnName:
            selectedColumn?.assetFqn === node.fqn ? selectedColumn?.columnName || "" : "",
          onSelect: handleNodeClick,
          onColumnSelect,
          onOpenAsset,
          // Node-level Databricks deep link (owner direction #2c). Built from
          // the workspace host + FQN; "" when we can't stand behind a real
          // link, so the card omits the affordance rather than dead-linking.
          databricksHref: catalogExplorerUrl(node.fqn, workspaceHost),
        },
        // Disable React Flow's selection / drag — node identity is the
        // model, not a draggable artifact.
        selectable: false,
        draggable: false,
      };
    });
  }, [
    visibleNodes,
    positions,
    hoveredNodeId,
    tracedNodeIds,
    handleNodeClick,
    nodeHeaders,
    selectedNodeFqn,
    selectedColumn?.assetFqn,
    selectedColumn?.columnName,
    onColumnSelect,
    onOpenAsset,
    workspaceHost,
    currentFocusFqn,
  ]);

  const focusReactFlowId = graph.focus?.id;
  // Pull edge colors from CSS custom properties so design-token updates
  // flow through automatically. Falls back to bright-blue if
  // the variable isn't yet applied (SSR / first-paint).
  const cssVar = (name, fallback) =>
    (typeof document !== "undefined"
      && getComputedStyle(document.documentElement).getPropertyValue(name).trim())
    || fallback;
  // Direction-tinted edges (owner direction #3): upstream flow reads teal,
  // downstream reads bright-blue, so the eye can follow provenance vs impact
  // at a glance. Restricted edges keep their dashed-amber treatment (the CSS
  // override wins) — a verified honesty contract we must not regress.
  const focusEdgeColor = cssVar("--ax-bright-blue", "rgba(116,151,220,1)");
  const upstreamEdgeColor = cssVar("--ax-teal", "rgba(200,200,200,1)");
  const edgeSideOf = useCallback(
    (edge) => {
      const upSide = (id) => id === focusNodeId || upstreamIds.has(id);
      const downSide = (id) => id === focusNodeId || downstreamIds.has(id);
      if (upSide(edge.source) && upSide(edge.target)) return "upstream";
      if (downSide(edge.source) && downSide(edge.target)) return "downstream";
      return "downstream";
    },
    [focusNodeId, upstreamIds, downstreamIds],
  );
  const flowEdges = useMemo(() => {
    return visibleEdges.map((edge) => {
      const isFocusEdge = focusReactFlowId
        ? edge.source === focusReactFlowId || edge.target === focusReactFlowId
        : false;
      const isTraced = !hoveredNodeId
        || (tracedNodeIds.has(edge.source) && tracedNodeIds.has(edge.target));
      const side = edgeSideOf(edge);
      const tint = side === "upstream" ? upstreamEdgeColor : focusEdgeColor;
      const idleStroke = side === "upstream" ? "rgba(200, 200, 200, 0.42)" : "rgba(116, 151, 220, 0.42)";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        animated: isFocusEdge,
        markerEnd: { type: MarkerType.ArrowClosed, color: tint },
        style: {
          stroke: isFocusEdge ? tint : idleStroke,
          strokeWidth: isFocusEdge ? 1.8 : 1.1,
          opacity: isTraced ? (isFocusEdge ? 1 : 0.62) : 0.16,
          transition: "opacity 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        },
        data: { isRestricted: edge.isRestricted },
        className: edge.isRestricted ? "ax-lineage-v2-edge-restricted" : undefined,
      };
    });
  }, [visibleEdges, focusReactFlowId, hoveredNodeId, tracedNodeIds, focusEdgeColor, upstreamEdgeColor, edgeSideOf]);

  // Header hydration changes node card content after React Flow's initial
  // measurements. Refresh node internals so invisible handles keep valid
  // bounds and edge paths do not disappear after the UC detail footers load.
  useEffect(() => {
    if (!flowNodes.length) return undefined;
    let disposed = false;
    const frames = [];
    const refresh = () => {
      if (disposed) return;
      flowNodes.forEach((node) => updateNodeInternals(node.id));
    };
    const schedule = (callback) => {
      const frame = window.requestAnimationFrame(callback);
      frames.push(frame);
    };
    schedule(refresh);
    schedule(() => schedule(refresh));
    return () => {
      disposed = true;
      frames.forEach((frame) => window.cancelAnimationFrame(frame));
    };
  }, [flowNodes, updateNodeInternals]);

  // After the graph changes, fit the new node set into view exactly once.
  useEffect(() => {
    if (!flowNodes.length) return;
    const handle = window.requestAnimationFrame(() => {
      try {
        reactFlow.fitView({ padding: 0.2, includeHiddenNodes: false, duration: 240 });
      } catch (_) {
        // React Flow not ready yet — ignore silently
      }
    });
    return () => window.cancelAnimationFrame(handle);
  }, [reactFlow, flowNodes.length, focusId]);

  const handlePaneNodeMouseEnter = useCallback(
    (_event, node) => setHoveredNodeId(node?.id || ""),
    [],
  );
  const handlePaneNodeMouseLeave = useCallback(() => setHoveredNodeId(""), []);

  if (error) {
    return (
      <div className="ax-lineage-v2-canvas-state ax-lineage-v2-canvas-state-error">
        <strong>Lineage unavailable</strong>
        <span>{error}</span>
      </div>
    );
  }

  // A pending payload's data graph carries exactly ONE stub focus node and
  // zero edges (cold-cache full build). Treat that stub-only shape the same
  // as a truly empty graph for the warming/hydrating states below —
  // otherwise the single stub suppressed both, leaving no progress copy and
  // no Retry affordance (adversarial verify P0). A sticky accumulated graph
  // (nodes > 1) keeps rendering instead.
  const stubOnlyGraph = nodesArray.length <= 1 && !edgesArray.length;

  if (stubOnlyGraph && warming) {
    // Honest terminal state for an exhausted poll loop (persona audit P1):
    // the graph build is still warming server-side — offer a real retry
    // instead of an infinite spinner.
    return (
      <div className="ax-lineage-v2-canvas-state">
        <strong>Lineage is still warming</strong>
        <span>The lineage build has not finished on the server yet. Retry in a moment.</span>
        {onRetry ? (
          <button className="gh-secondary-button" onClick={() => onRetry()} type="button">
            Retry lineage
          </button>
        ) : null}
      </div>
    );
  }

  if (stubOnlyGraph && hydrating) {
    return (
      <div className="ax-lineage-v2-canvas-state ax-lineage-v2-canvas-state-hydrating ax-lineage-v2-canvas-state-skeleton">
        <LineageGraphSkeleton caption="" />
        <strong>Loading lineage from Unity Catalog</strong>
        <span>Walking system.access.table_lineage outward from the focus asset…</span>
      </div>
    );
  }

  if (!nodesArray.length) {
    // True-empty copy must not blame the user's visibility scope for an
    // app-side condition (fix_plan lineage-truth rule).
    return (
      <div className="ax-lineage-v2-canvas-state">
        <strong>No lineage recorded</strong>
        <span>Unity Catalog has no table-lineage rows for this asset.</span>
      </div>
    );
  }

  return (
    <div className="ax-lineage-v2-canvas">
      {kindMeta.kinds.length ? (
        <div className="ax-lineage-v2-legend" role="group" aria-label="Lineage graph filters and legend">
          <div className="ax-lineage-v2-legend-directions" role="group" aria-label="Direction filter">
            {/** @type {[string, string, number][]} */ ([
              ["all", "All", kindMeta.peerTotal],
              ["upstream", "Upstream", kindMeta.upstreamTotal],
              ["downstream", "Downstream", kindMeta.downstreamTotal],
            ]).map(([key, label, count]) => (
              <button
                aria-pressed={direction === key}
                className={`ax-lineage-v2-legend-dir ${direction === key ? "is-active" : ""}`.trim()}
                key={key}
                onClick={() => setDirection(key)}
                title={`Show ${label.toLowerCase()} assets`}
                type="button"
              >
                {label}
                <span className="ax-lineage-v2-legend-count">{count}</span>
              </button>
            ))}
          </div>
          <div className="ax-lineage-v2-legend-kinds">
            {kindMeta.kinds.map((entry) => {
              const off = disabledKinds.has(entry.kind);
              return (
                <button
                  aria-pressed={!off}
                  className={`ax-lineage-v2-legend-chip ${off ? "is-off" : ""}`.trim()}
                  data-node-kind={entry.kind}
                  key={entry.kind}
                  onClick={() => toggleKind(entry.kind)}
                  title={`${off ? "Show" : "Hide"} ${kindLabel(entry.kind)} nodes (${entry.upstream} up / ${entry.downstream} down)`}
                  type="button"
                >
                  <span aria-hidden="true" className="ax-lineage-v2-legend-swatch" />
                  {kindLabel(entry.kind)}
                  <span className="ax-lineage-v2-legend-count">{entry.count}</span>
                </button>
              );
            })}
            {filtersActive ? (
              <button
                className="ax-lineage-v2-legend-reset"
                onClick={resetFilters}
                type="button"
              >
                Reset
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {hydrating || useSticky ? (
        <div className="ax-lineage-v2-canvas-banner" role="status">
          <span aria-hidden="true" className="ax-lineage-v2-canvas-spinner" />
          {useSticky ? "Switching focus…" : "Loading from Unity Catalog…"}
        </div>
      ) : null}
      {!flowNodes.length ? (
        <div className="ax-lineage-v2-filter-empty" role="status">
          <strong>No nodes match the current filters</strong>
          <span>Every connected asset is hidden by the direction or type filters above.</span>
          <button className="ax-lineage-v2-secondary-btn" onClick={resetFilters} type="button">
            Reset filters
          </button>
        </div>
      ) : null}
      <ReactFlow
        edges={flowEdges}
        // Edges are informational, not actionable — keeping them focusable
        // put ~26 invisible keyboard tab stops before the first node.
        edgesFocusable={false}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        maxZoom={2.25}
        minZoom={minZoom}
        nodes={flowNodes}
        nodeTypes={NODE_TYPES}
        nodesConnectable={false}
        nodesDraggable={false}
        onlyRenderVisibleElements={false}
        onNodeMouseEnter={handlePaneNodeMouseEnter}
        onNodeMouseLeave={handlePaneNodeMouseLeave}
        panOnDrag
        proOptions={{ hideAttribution: true }}
        zoomOnScroll
        preventScrolling={true}
      >
        <Background color="rgba(91, 127, 208, 0.18)" gap={24} size={1} />
        <Controls position="top-right" showInteractive={false} />
      </ReactFlow>
      {/*
        L8: the graph is intentionally bounded to 1 hop per fetch (backend
        LINEAGE_GRAPH_DEPTH_LIMIT). Caption the limit so the boundary reads
        as a designed behavior — clicking a node merges its neighbors into
        the accumulated graph, which is the sanctioned way to go deeper.
        Inline style uses ax-* tokens (this file cannot own lineage-v2.css).
      */}
      <div
        role="note"
        style={{
          position: "absolute",
          left: 14,
          bottom: 10,
          zIndex: 5,
          pointerEvents: "none",
          fontSize: 11,
          letterSpacing: "0.02em",
          color: "var(--ax-text-muted)",
          // Solid pill: at narrow widths the auto-layout can push a node
          // card into this corner, and bare text collided with card text.
          background: "var(--ax-surface-strong)",
          border: "1px solid var(--ax-border-muted)",
          borderRadius: 999,
          padding: "3px 10px",
        }}
      >
        {(() => {
          // Truncation honesty (persona audit P1): when the backend capped
          // the graph, say exactly how much is shown. Falls back to the
          // hop-limit caption when no truncation metadata is present.
          const truncation = graph.meta?.truncation;
          const edgesShown = Number(truncation?.edgesShown);
          const edgesTotal = Number(truncation?.edgesTotal);
          const nodesShown = Number(truncation?.nodesShown);
          const nodesTotal = Number(truncation?.nodesTotal);
          if (Number.isFinite(edgesShown) && Number.isFinite(edgesTotal) && edgesTotal > edgesShown) {
            return `Showing ${edgesShown} of ${edgesTotal} edges — highest-traffic neighbors first`;
          }
          if (Number.isFinite(nodesShown) && Number.isFinite(nodesTotal) && nodesTotal > nodesShown) {
            return `Showing ${nodesShown} of ${nodesTotal} connected assets — highest-traffic neighbors first`;
          }
          const hops = Number(graph.meta?.graphDepthLimit) > 1
            ? `${graph.meta.graphDepthLimit} hops`
            : "1 hop";
          return `Showing ${hops} from focus — select a node and use Re-anchor to extend the graph`;
        })()}
      </div>
    </div>
  );
}

export function LineageCanvasV2({
  graph,
  hydrating,
  error,
  focusId,
  onFocusChange,
  nodeHeaders = new Map(),
  selectedNodeFqn = "",
  selectedColumn = null,
  onColumnSelect = null,
  warming = false,
  onRetry = null,
  onRenderedGraphChange = null,
  onOpenAsset = null,
  workspaceHost = "",
  minZoom = 0.5,
}) {
  // The provider lives here, not in main.jsx, so React Flow only loads with
  // the lineage surfaces. CanvasInner consumes it via useReactFlow().
  return (
    <ReactFlowProvider>
      <CanvasInner
        error={error}
        focusId={focusId}
        graph={graph}
        hydrating={hydrating}
        minZoom={minZoom}
        nodeHeaders={nodeHeaders}
        onFocusChange={onFocusChange}
        onColumnSelect={onColumnSelect}
        onOpenAsset={onOpenAsset}
        onRenderedGraphChange={onRenderedGraphChange}
        onRetry={onRetry}
        selectedColumn={selectedColumn}
        selectedNodeFqn={selectedNodeFqn}
        warming={warming}
        workspaceHost={workspaceHost}
      />
    </ReactFlowProvider>
  );
}

export default LineageCanvasV2;
