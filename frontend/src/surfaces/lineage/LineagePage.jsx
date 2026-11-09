import "./lineage.css";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { LineageCanvasV2 } from "../../components/lineage-v2/LineageCanvasV2";
import { useLineageGraphV2 } from "../../components/lineage-v2/useLineageGraphV2";
import { useLineageNodeHeaders } from "../../components/lineage-v2/useLineageNodeHeaders";
import { Button, PageShell, UnavailableState } from "../../components/system";
import { useAccessExplain } from "../../hooks/useAccessExplain";
import { useAssetDatabricksEvidence } from "../../hooks/useAssetDatabricksEvidence";
import { useAssetDetail } from "../../hooks/useAssetDetail";
import { useAssetQuality } from "../../hooks/useAssetQuality";
import { useColumnLineageTrace } from "../../hooks/useColumnLineageTrace";
import { useLineageRecommendations } from "../../hooks/useLineageRecommendations";
import { useSeededAssetContext } from "../../hooks/useSeededAssetContext";
import { createGovernanceRequest } from "../../lib/api";
import {
  runtimeFeatureFlagAvailable,
  runtimeFeatureFlagReason,
  tableLineageAvailable,
  tableLineageReason,
  workspaceAccessAvailable,
  workspaceAccessReason,
} from "../../lib/capabilities";
import { useAxiomNavigate } from "../../nav/useAxiomNavigate";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { LineageDetailRail } from "./LineageDetailRail.jsx";
import { LineagePicker } from "./LineagePicker.jsx";
import { LineageRecommendations } from "./LineageRecommendations.jsx";
import {
  downloadImpactPacket,
  isUcAssetFqn,
  relativeFreshness,
  workspaceHostFromBootstrap,
} from "./lineagePresentation.js";
import { pushRecentLineage } from "../../lib/prefs";

/*
 * surfaces/lineage/LineagePage.jsx — the Lineage Atlas surface (Wave C7).
 *
 * COHESION law: /lineage/<fqn> is canonical (this page); bare /lineage is
 * the search-first picker (LineagePicker). The page is router-self-
 * sufficient: it reads :fqn from the route splat and ?context=/?selected=
 * via useSurfaceParams — the workspaceIntent sessionStorage handoff for
 * "lineageContext" is DEAD (FRONTEND_BLUEPRINT §8 kill table): the URL is
 * the state, so hop context and rail selection survive refresh/share.
 *
 * The canvas experience is the adversarially-verified lineage-v2 kit
 * (LineageCanvasV2 + useLineageGraphV2 adapter), adopted unchanged; this
 * file only ports the legacy LineageWorkspace composition (hero chips,
 * honest degraded/zero-edge states, Impact Inspector rail, select-vs-
 * re-anchor contract) onto PageShell + system components.
 */

// Mirrors the nav/routes.js /lineage/:fqn paramsSchema; module-level so
// useSurfaceParams normalizes it once.
const FOCUS_PARAMS_SCHEMA = {
  // Data Lineage vs Operational Context — was sessionStorage workspaceIntent.
  context: { type: "string" },
  // The rail's selected node (canvas click is SELECT-ONLY; focus is the path).
  selected: { type: "string" },
};

function safeDecode(segment = "") {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function FocusChip({ tone, children, title = "" }) {
  return (
    <span className={`ax-lineage-v2-chip tone-${tone || "neutral"}`} title={title || undefined}>
      {children}
    </span>
  );
}

/**
 * The hero evidence chips (rendered in the PageShell hero band's chip row).
 * Sourced from the asset detail when available — the lineage payload's
 * `focus` node is a thin stub from system.access.table_lineage and doesn't
 * carry freshness / owner / certification by itself; the asset detail is
 * the authoritative source, matching what the rail shows.
 */
function LineageHeroChips({ asset, focus, hydrating, edgeCount, loading = false, restricted = false }) {
  const certified =
    asset?.certification === "Certified" ||
    asset?.isCertified ||
    focus?.isCertified;
  const classification = asset?.sensitivity || focus?.classification || "";
  const ownerEntry =
    (Array.isArray(asset?.owners) && asset.owners[0]) ||
    (Array.isArray(focus?.owners) && focus.owners[0]) ||
    null;
  const owner =
    ownerEntry?.displayName ||
    ownerEntry?.email ||
    ownerEntry?.name ||
    "";
  // Freshness derived from updatedAt the same way the rail does, so hero
  // and rail stay consistent.
  const updatedAtIso =
    asset?.updatedAt ||
    asset?.lastRefresh ||
    asset?.refreshedAt ||
    "";
  const freshness = relativeFreshness(updatedAtIso) || asset?.freshness || focus?.freshness || "";
  return (
    <div className="ax-lin-chips" aria-busy={loading || undefined}>
      {/*
        L6: while the asset header is still loading, four grey
        "… unavailable" chips used to flash on EVERY load — a false
        negative. Render ellipsis placeholders during load; only a
        RESOLVED header may claim an honest empty ("Not certified").
        Restricted assets say "Restricted", not "unavailable".
      */}
      {loading ? (
        ["Certification", "Freshness", "Sensitivity", "Owner"].map((label) => (
          <FocusChip key={label} tone="neutral" title="Loading asset metadata">
            {label} …
          </FocusChip>
        ))
      ) : restricted && !asset?.fqn ? (
        <FocusChip tone="warn" title="This asset's metadata is not visible to your account">
          Restricted · metadata not visible to your account
        </FocusChip>
      ) : (
        <>
          <FocusChip tone={certified ? "good" : "neutral"}>
            {certified ? "Certified" : "Not certified"}
          </FocusChip>
          {/* Freshness label honesty (fix_plan #6): this value derives
              from updatedAt — a data write — so label it as such. */}
          <FocusChip tone={freshness ? "info" : "neutral"}>
            {freshness ? `Data updated · ${freshness}` : "No freshness signal"}
          </FocusChip>
          <FocusChip tone={classification ? "warn" : "neutral"} title={classification}>
            {classification || "No sensitivity label"}
          </FocusChip>
          <FocusChip tone={owner ? "info" : "neutral"} title={owner}>
            {owner ? `Owner · ${owner}` : "No owner assigned"}
          </FocusChip>
        </>
      )}
      {edgeCount !== null ? (
        <FocusChip tone="info">
          {edgeCount} {edgeCount === 1 ? "edge" : "edges"}
        </FocusChip>
      ) : null}
      {hydrating ? <FocusChip tone="info">Loading…</FocusChip> : null}
    </div>
  );
}

function LineageFocusPage({
  fqn,
  bootstrap = null,
  contextSeedAssets = [],
  runtimeFeatureFlags = [],
  workspaceAccess = null,
}) {
  const navigate = useAxiomNavigate();
  const [params, setParams] = useSurfaceParams(FOCUS_PARAMS_SCHEMA);
  const workspaceHost = workspaceHostFromBootstrap(bootstrap);
  const [selectedColumn, setSelectedColumn] = useState(null);
  const [impactRequestState, setImpactRequestState] = useState({
    loading: false,
    message: "",
    error: "",
  });
  // ?selected= is CLIENT-VIEW state in the URL — it tracks which node the
  // user last clicked on the canvas (rail subject + highlight). It is NOT
  // the focus: the path fqn drives the lineage HTTP query. Decoupling these
  // means clicking a node never refetches — an instant highlight + rail
  // update. To genuinely re-anchor (refetch centered on a different node)
  // the user clicks the explicit "Re-anchor lineage" rail button, which
  // navigates to /lineage/<node>.
  const selectedNodeFqn = params.selected || fqn;
  // Once we've successfully rendered a canvas with at least one node, keep
  // the workspace in canvas mode for the rest of the session. Without this,
  // a focus-switch triggers a brief moment where the new asset's payload
  // hasn't returned yet AND bootstrap.capabilities.tableLineage is marked
  // unavailable — the page would flip to the "Lineage unavailable" error UI
  // mid-transition, unmount the canvas, then remount when nodes arrive. We
  // pin the canvas open so only the graph data inside swaps.
  const [canvasEverRendered, setCanvasEverRendered] = useState(false);
  // Rendered-graph stats reported by the canvas (its accumulated superset).
  // The hero chip counts read from here so they describe what is actually
  // drawn — the raw payload reads "0 edges" mid-refocus while the sticky
  // canvas still shows a full graph (persona audit P2).
  const [renderedGraphStats, setRenderedGraphStats] = useState(null);

  const lineageAvailable = tableLineageAvailable(bootstrap);
  const lineageUnavailableReason = tableLineageReason(bootstrap);
  const workspaceLineageAvailable = workspaceAccessAvailable(workspaceAccess, "canUseLineage", false);
  const lineageRolloutAvailable = runtimeFeatureFlagAvailable(
    runtimeFeatureFlags,
    "table_lineage_surface",
  );
  const workspaceAccessResolved = Boolean(
    workspaceAccess &&
      (
        workspaceAccess.mode ||
        workspaceAccess.observedAt ||
        Array.isArray(workspaceAccess.gates) ||
        typeof workspaceAccess.canUseLineage === "boolean"
      ),
  );
  const lineageSurfaceAvailable =
    lineageAvailable &&
    lineageRolloutAvailable &&
    (!workspaceAccessResolved || workspaceLineageAvailable);
  const lineageRolloutUnavailableReason =
    "Table lineage rollout is not available in this workspace right now.";
  const lineageSurfaceUnavailableReason = workspaceAccessResolved && !workspaceLineageAvailable
    ? workspaceAccessReason(workspaceAccess, "table_lineage", lineageUnavailableReason)
    : lineageAvailable
    ? lineageRolloutAvailable
      ? lineageUnavailableReason
      : runtimeFeatureFlagReason(
          runtimeFeatureFlags,
          "table_lineage_surface",
          lineageRolloutUnavailableReason,
        )
    : lineageUnavailableReason;
  const seedAssets = contextSeedAssets?.length ? contextSeedAssets : bootstrap?.assets || [];
  const seeded = useSeededAssetContext(fqn, bootstrap, seedAssets, {
    allowFallback: false,
  });
  const assetDetail = useAssetDetail(fqn || "", { sections: ["header"] });
  // Always fetch for a focused asset — bootstrap can under-report capability
  // (e.g. when its workspace-wide check hasn't hydrated) even though
  // /api/lineage will return real edges. The API is the authoritative source
  // of "is this asset openable"; bootstrap only gates as a fallback when we
  // have nothing (trust-live-API rule).
  const graph = useLineageGraphV2(fqn || "", { enabled: Boolean(fqn) });
  const lineageRecommendations = useLineageRecommendations({ enabled: true, limit: 8 });
  const recommendedAssets = useMemo(
    () =>
      (lineageRecommendations.items || [])
        .filter((item) => item.fqn && item.fqn !== fqn)
        .sort((left, right) => Number(right.edgeCount || 0) - Number(left.edgeCount || 0)),
    [fqn, lineageRecommendations.items],
  );
  const recommendationsDegraded = Boolean(
    lineageRecommendations.degraded ||
      lineageRecommendations.authoritative === false ||
      String(lineageRecommendations.visibilityScope || "").includes("workspace-app-principal"),
  );
  const assetHeaderHydrated = Boolean(assetDetail.detail?.fqn) && !assetDetail.loading && !assetDetail.detail?.error;
  // L1: quality + Databricks evidence were once additionally gated on a
  // bootstrap SEED visibility set that under-reports what the live API can
  // serve. Per the trust-live-API rule, a successfully hydrated asset
  // header IS the proof of visibility: gate on that alone.
  const quality = useAssetQuality(fqn || "", {
    enabled: Boolean(fqn && assetHeaderHydrated),
  });
  const databricksEvidence = useAssetDatabricksEvidence(fqn || "", {
    enabled: Boolean(fqn && assetHeaderHydrated),
  });
  const accessExplain = useAccessExplain(fqn || "", { enabled: Boolean(fqn) });
  const columnTrace = useColumnLineageTrace(
    selectedColumn?.assetFqn || "",
    selectedColumn?.columnName || "",
    {
      enabled: Boolean(selectedColumn?.assetFqn && selectedColumn?.columnName),
      depth: 3,
    },
  );
  // Batch-fetch bounded card headers from visible inventory. This enriches
  // the first visible cards without turning a lineage render into N full
  // asset-detail requests.
  const lineageNodeFqns = useMemo(
    () => (graph.nodes || [])
      .map((node) => node.fqn)
      .filter((nodeFqn) => isUcAssetFqn(nodeFqn) && nodeFqn !== fqn),
    [fqn, graph.nodes],
  );
  const { headers: nodeHeaders } = useLineageNodeHeaders(lineageNodeFqns);
  // L3: the focus FQN is deliberately excluded from the batch header fetch
  // (its full header already arrives via useAssetDetail above), but the
  // canvas header map never received it — so the focus card lacked the
  // rows/size/freshness/owner footer its PEERS had. Seed the map with the
  // asset detail for the focus; the asset-detail payload is a superset of
  // the batch header shape, so deriveCardStats consumes it unchanged.
  const canvasNodeHeaders = useMemo(() => {
    const base = nodeHeaders instanceof Map ? new Map(nodeHeaders) : new Map();
    const detail = assetDetail.detail;
    if (fqn && detail?.fqn === fqn) {
      base.set(fqn, detail);
    }
    return base;
  }, [assetDetail.detail, fqn, nodeHeaders]);
  const asset =
    assetDetail.detail ||
    (fqn && assetDetail.loading ? seeded.summary : null);

  // When the URL focus changes (re-anchor or fresh navigation), reset the
  // per-focus client state. ?selected= is dropped by the navigation itself
  // (re-anchor serializes only ?context=), so rail + highlight start
  // aligned with the new graph.
  useEffect(() => {
    setSelectedColumn(null);
    setImpactRequestState({ loading: false, message: "", error: "" });
  }, [fqn]);

  // Record the opened lineage journey once the graph resolves with real nodes
  // (prefs-backed "recent journeys" strip on the picker). Gate on a populated
  // graph so a dead/gated FQN never pollutes the recents list.
  useEffect(() => {
    if (fqn && isUcAssetFqn(fqn) && graph.nodes.length > 0) {
      pushRecentLineage(fqn);
    }
  }, [fqn, graph.nodes.length]);

  // Track whether we've ever shown a populated canvas this session (see
  // canvasEverRendered above). CRITICAL: this hook MUST run on every render
  // — a hook after an early return causes React error 310 ("Rendered fewer
  // hooks than expected") the moment the early-return branch flips
  // (CLAUDE.md hook-order rule).
  useEffect(() => {
    if (graph.nodes.length > 0 && !canvasEverRendered) {
      setCanvasEverRendered(true);
    }
  }, [graph.nodes.length, canvasEverRendered]);

  // Select-only canvas click (persona audit P2): update ?selected= — rail
  // subject + highlight, nothing else. Selecting the focus clears the param
  // so the canonical URL stays minimal.
  const handleNodeSelect = (nextNodeFqn) => {
    if (!nextNodeFqn) return;
    setParams({ selected: nextNodeFqn === fqn ? "" : nextNodeFqn });
  };

  // Explicit re-anchor: navigate to /lineage/<node> → useLineage fetches the
  // new fqn → the canvas MERGES the new payload into its accumulated graph
  // (EXPAND — the clicked node is already on canvas), preserving the
  // traversed edge and extending outward. ?context= rides along.
  const handleReAnchor = (nextNodeFqn) => {
    if (!nextNodeFqn) return;
    navigate(
      { kind: "lineage", fqn: nextNodeFqn },
      params.context ? { params: { context: params.context } } : undefined,
    );
  };

  const handleColumnSelect = (node, column) => {
    if (!node?.fqn || !column?.name) return;
    setParams({ selected: node.fqn === fqn ? "" : node.fqn });
    setSelectedColumn({
      assetFqn: node.fqn,
      columnName: column.name,
      type: column.type || "",
    });
  };

  // Bare /lineage is the search-first picker now — clearing focus just goes
  // there (the legacy auto-redirect-to-top-recommendation is dead, so no
  // suppression flag is needed).
  const handleClearFocus = () => {
    navigate({ surface: "lineage" });
  };

  const handleOpenAsset = (assetFqn, tab = "overview") => {
    if (!assetFqn) return;
    navigate({ kind: "asset", fqn: assetFqn }, { params: { tab } });
  };

  const handleExportImpactBrief = (packet) => {
    downloadImpactPacket(packet);
    setImpactRequestState({
      loading: false,
      message: "Impact packet exported from the current loaded evidence.",
      error: "",
    });
  };

  const handleCreateImpactRequest = async (payload) => {
    if (!payload?.assetFqn || impactRequestState.loading) return;
    setImpactRequestState({ loading: true, message: "", error: "" });
    try {
      const response = await createGovernanceRequest(payload, { fast: true });
      const requestId = response?.requestId || response?.id || "";
      setImpactRequestState({
        loading: false,
        message: requestId
          ? `Governance request created: ${requestId}`
          : "Governance request created.",
        error: "",
      });
    } catch (error) {
      setImpactRequestState({
        loading: false,
        message: "",
        error: error?.message || "Governance request creation is unavailable.",
      });
    }
  };

  // L6: while the header request is in flight AND we have nothing (no
  // detail, no seeded summary) the hero must render loading chips, not
  // "… unavailable" false negatives.
  const heroMetadataLoading = Boolean(fqn) && assetDetail.loading && !asset?.fqn;
  // L6: restricted focus — the graph payload marks the focus non-openable.
  // The hydrated asset detail (if any) still wins per trust-live-API.
  const focusRestricted = graph.focus ? graph.focus.isOpenable === false : false;

  // Bootstrap can report lineage "unavailable" for an asset the live
  // /api/lineage endpoint *does* return real edges for — the capability
  // check uses a narrower workspace-wide signal than the per-asset query.
  // Only block when capability is off AND the API returned nothing AND
  // we've never rendered the canvas before.
  const gatedOff = !lineageSurfaceAvailable && !graph.nodes.length && !canvasEverRendered;

  // Three honest states, in priority order (adversarial verify P0 —
  // "dishonest build-failed banner"):
  //   (a) pending/warming — the full build is still hydrating server-side;
  //       progress copy only, NEVER the words "failed"/"degraded".
  //   (b) build degraded — ONLY when the payload itself says the build
  //       failed: buildState "degraded"/"failed", lineageQueryFailed, or
  //       emptyReason "lineage-query-failed".
  //   (c) true empty — ONLY a terminal, non-deferred payload whose
  //       emptyReason is "no-lineage-rows".
  // The envelope's meta.degraded is true whenever ANY warning rides on the
  // response — including the benign "hydrating" warning on every pending
  // envelope — so it MUST NOT drive the "build failed" banner.
  const graphWarnings = Array.isArray(graph.meta?.warnings) ? graph.meta.warnings : [];
  const payloadBuildState = String(graph.payload?.buildState || "").toLowerCase();
  const buildFailed = Boolean(
    payloadBuildState === "degraded" ||
      payloadBuildState === "failed" ||
      graph.meta?.lineageQueryFailed === true ||
      String(graph.meta?.emptyReason || "") === "lineage-query-failed",
  );
  // Pending = the hook still reports hydrating (deferred/initial/loading
  // envelope) or the poll budget is spent (warming). A failed build is
  // terminal, never pending.
  const graphPending = Boolean((graph.hydrating || graph.warming) && !buildFailed);
  const zeroEdgeLoaded = Boolean(
    fqn &&
      !graph.loading &&
      !graphPending &&
      !graph.error &&
      !buildFailed &&
      graph.nodes.length <= 1 &&
      graph.edges.length === 0 &&
      // Require the backend's explicit true-empty marker: a payload without
      // it (older cache shape, partial envelope) must not claim "Unity
      // Catalog has no rows" — the canvas's neutral empty state covers it.
      String(graph.meta?.emptyReason || "") === "no-lineage-rows",
  );
  const degradedNoGraph = Boolean(
    fqn && buildFailed && graph.nodes.length <= 1 && graph.edges.length === 0,
  );
  const heroEdgeCount = renderedGraphStats?.edgeCount ?? graph.edges.length;

  return (
    <PageShell
      actions={
        <Button onClick={handleClearFocus} variant="tertiary">
          ← Clear lineage focus
        </Button>
      }
      className="ax-lin-page"
      eyebrow="Lineage Atlas"
      subtitle="Permission-aware lineage from the upstream assets you can see through to permitted downstream consumers."
      title={fqn}
    >
      <LineageHeroChips
        asset={asset}
        edgeCount={gatedOff ? null : heroEdgeCount}
        focus={graph.focus}
        // The chip must reflect the RENDERED graph: while a sticky
        // accumulated graph is on screen, don't flash "Hydrating…" over
        // visibly drawn edges.
        hydrating={!gatedOff && graph.hydrating && !renderedGraphStats?.edgeCount}
        loading={heroMetadataLoading}
        restricted={focusRestricted}
      />
      {gatedOff ? (
        <UnavailableState
          className="ax-lin-unavailable"
          reason={lineageSurfaceUnavailableReason}
          title="Lineage unavailable"
        />
      ) : (
        <div className="ax-lineage-v2-workbench">
          <div className="ax-lineage-v2-workbench-canvas">
            {degradedNoGraph ? (
              <div className="ax-lineage-zero-state" role="status">
                <div>
                  <span className="ax-lin-eyebrow">Lineage Build Degraded</span>
                  <strong>The lineage build failed or returned degraded evidence for this asset.</strong>
                  <p>
                    {graphWarnings[0] ||
                      "The lineage graph could not be built from system.access.table_lineage on this attempt. This is an app/warehouse condition — not a reflection of your access."}
                  </p>
                  <Button onClick={() => graph.refresh?.()} variant="secondary">
                    Retry lineage build
                  </Button>
                </div>
              </div>
            ) : null}
            {zeroEdgeLoaded ? (
              <div className="ax-lineage-zero-state" role="status">
                <div>
                  {/* True empty: state the fact without blaming the caller's
                      visibility scope (persona audit P1). */}
                  <span className="ax-lin-eyebrow">No Lineage Recorded</span>
                  <strong>Unity Catalog has no table-lineage rows for this asset.</strong>
                  <p>
                    No upstream or downstream table-lineage edges are recorded for the
                    selected focus. Open a ranked high-lineage asset below, or keep this
                    asset selected to inspect its evidence boundaries.
                  </p>
                </div>
                <LineageRecommendations
                  compact
                  degraded={recommendationsDegraded}
                  error={lineageRecommendations.error}
                  loading={lineageRecommendations.loading}
                  recommendations={recommendedAssets}
                />
              </div>
            ) : null}
            <LineageCanvasV2
              error={graph.error}
              focusId={fqn}
              graph={graph}
              hydrating={graph.hydrating}
              nodeHeaders={canvasNodeHeaders}
              onColumnSelect={handleColumnSelect}
              onFocusChange={handleNodeSelect}
              onOpenAsset={handleOpenAsset}
              onRenderedGraphChange={setRenderedGraphStats}
              onRetry={graph.refresh}
              selectedColumn={selectedColumn}
              selectedNodeFqn={selectedNodeFqn}
              warming={graph.warming}
              workspaceHost={workspaceHost}
            />
          </div>
          <LineageDetailRail
            accessExplain={accessExplain}
            asset={asset}
            columnTrace={columnTrace}
            graph={graph}
            focus={graph.focus}
            impactRequestState={impactRequestState}
            isFocusSelected={selectedNodeFqn === fqn}
            nodeHeaders={canvasNodeHeaders}
            onCreateImpactRequest={handleCreateImpactRequest}
            onExportImpactBrief={handleExportImpactBrief}
            selectedNode={
              selectedNodeFqn
                ? graph.nodes.find((n) => n.fqn === selectedNodeFqn) || null
                : null
            }
            selectedColumn={selectedColumn}
            quality={quality}
            databricksEvidence={databricksEvidence}
            onOpenAsset={handleOpenAsset}
            onReAnchor={handleReAnchor}
            onSelectAsset={handleNodeSelect}
          />
        </div>
      )}
    </PageShell>
  );
}

export function LineagePage({
  bootstrap = null,
  contextSeedAssets = [],
  runtimeFeatureFlags = [],
  workspaceAccess = null,
}) {
  const routeParams = useParams();
  const fqn = safeDecode(String(routeParams["*"] ?? routeParams.fqn ?? "")).trim();

  // Surface title (matches the sibling-surface convention). Runs before any
  // conditional return so hook order is stable across picker/focus flips.
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const previous = document.title;
    document.title = fqn ? `${fqn} · Lineage - Axiom` : "Lineage Atlas - Axiom";
    return () => {
      document.title = previous;
    };
  }, [fqn]);

  if (!fqn) {
    return <LineagePicker />;
  }
  return (
    <LineageFocusPage
      bootstrap={bootstrap}
      contextSeedAssets={contextSeedAssets}
      fqn={fqn}
      runtimeFeatureFlags={runtimeFeatureFlags}
      workspaceAccess={workspaceAccess}
    />
  );
}

export default LineagePage;
