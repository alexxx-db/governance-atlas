import "./lineage.css";
import { useMemo, useState } from "react";
import { Button, EntityChip } from "../../components/system";
import { deriveCardStats } from "../../components/lineage-v2/LineageNodeCard";
import { useAssetDetail } from "../../hooks/useAssetDetail";
import {
  arrayValue,
  buildColumnDirectLineage,
  buildEvidenceRecords,
  collectSqlSnippets,
  compactCount,
  displayCount,
  evidenceRows,
  evidenceSourceNames,
  evidenceState,
  firstMeaningful,
  isUcAssetFqn,
  ownerLabel,
  relativeFreshness,
} from "./lineagePresentation.js";

/*
 * surfaces/lineage/LineageDetailRail.jsx — the Impact Inspector rail
 * (Wave C7 port of the rail from components/LineageWorkspace.jsx; the
 * legacy behavior passed adversarial verification, so the port preserves
 * it — the only chrome swaps are the legacy prototype buttons → system
 * <Button> and bespoke node-row buttons → EntityChip rows with a select-on-click
 * adapter, keeping the SELECT-ONLY canvas contract while making every
 * node mention a real, middle-clickable `<a href>`).
 */

// Every rendered owner is a real link to the owner-search grammar (cross-
// linking law + owner direction #2b). Falls back to plain text only when the
// owner string is a placeholder we can't address.
function OwnerLink({ owner, className = "" }) {
  const text = String(owner || "").trim();
  if (!text) return <>No owner recorded</>;
  return (
    <EntityChip
      appearance="inline"
      className={className}
      entity={{ kind: "owner", email: text, label: text }}
    />
  );
}

function ImpactFact({ label, value, detail, tone = "neutral" }) {
  return (
    <div className={`ax-lineage-impact-fact tone-${tone}`.trim()}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function LineageRows({ items, empty, onSelectAsset }) {
  if (!items?.length) return <p className="ax-lineage-v2-rail-empty">{empty}</p>;
  return (
    <ul>
      {items.map((node) => (
        <li key={node.id}>
          {node.isOpenable === false || !node.fqn ? (
            // Restricted / unresolvable nodes stay honest non-controls
            // (matches the legacy disabled-button rendering).
            <span className="ax-lin-rail-row-static">
              <strong>{node.label}</strong>
              <span>{node.subtitle}</span>
            </span>
          ) : (
            // Left-click keeps the legacy select-only behavior (rail subject
            // + canvas highlight, NO refetch); the live /lineage/<fqn> href
            // adds middle-click/copy per the cross-linking law.
            <EntityChip
              appearance="row"
              className="ax-lin-rail-row"
              entity={{ kind: "lineage", fqn: node.fqn, label: node.label, meta: node.subtitle || "" }}
              navigate={() => onSelectAsset(node.fqn)}
            />
          )}
        </li>
      ))}
    </ul>
  );
}

function ColumnTracePath({ title, trace, directItems, error }) {
  const nodes = Array.isArray(trace?.nodes) ? trace.nodes : [];
  const truncated = Boolean(trace?.meta?.truncated);
  // Asset mentions inside a trace step become inline EntityChips (asset
  // record links); the column name stays the emphasized text.
  const assetRef = (fqn) =>
    isUcAssetFqn(fqn) ? (
      <EntityChip appearance="inline" entity={{ kind: "asset", fqn, label: fqn }} />
    ) : (
      <span>{fqn}</span>
    );
  return (
    <div className="ax-lineage-column-trace-card">
      <header>
        <span>{title}</span>
        <strong>{trace ? `${Math.max(0, nodes.length - 1)} traced` : `${directItems.length} direct`}</strong>
      </header>
      {trace ? (
        <>
          <div className="ax-lineage-column-path-list">
            {nodes.slice(1, 6).map((node) => (
              <div key={node.id || `${node.assetFqn}-${node.column}`}>
                <strong>{node.column}</strong>
                {assetRef(node.assetFqn)}
              </div>
            ))}
            {nodes.length <= 1 ? <p>No multi-hop column paths returned.</p> : null}
          </div>
          {truncated ? <p className="ax-lineage-v2-rail-empty">Trace truncated by bounded fan-out limits.</p> : null}
        </>
      ) : error ? (
        <p className="ax-lineage-v2-rail-empty">{error}</p>
      ) : directItems.length ? (
        <div className="ax-lineage-column-path-list">
          {directItems.slice(0, 6).map((item) => (
            <div key={`${item.assetFqn}-${item.column}`}>
              <strong>{item.column}</strong>
              {assetRef(item.assetFqn)}
            </div>
          ))}
        </div>
      ) : (
        <p className="ax-lineage-v2-rail-empty">No column paths returned for this direction.</p>
      )}
    </div>
  );
}

// L10: stable section list so the lazy activity fetch below keys a stable
// react-query cache entry instead of re-normalizing a fresh array per render.
const RAIL_ACTIVITY_SECTIONS = ["activity"];

export function LineageDetailRail({
  graph,
  focus,
  asset,
  selectedNode,
  selectedColumn,
  columnTrace,
  quality,
  databricksEvidence,
  accessExplain,
  impactRequestState,
  nodeHeaders = null,
  onCreateImpactRequest,
  onExportImpactBrief,
  onOpenAsset,
  onSelectAsset,
  onReAnchor,
  isFocusSelected,
}) {
  const [activeTab, setActiveTab] = useState("impact");
  const subject = selectedNode || focus;
  const subjectId = subject?.id;
  const subjectFqn = subject?.fqn || "";
  // L2: the batch header fetch (useLineageNodeHeaders) already holds
  // rows/size/owner/updatedAt for visible peer nodes — reuse it via the
  // exact card derivation so the rail never says "Unavailable" for data
  // that is already sitting in memory for the selected node.
  const subjectHeader = nodeHeaders?.get?.(subjectFqn) || null;
  const subjectStats = deriveCardStats(subject, subjectHeader);
  // L10: recorded activity is a lazy asset-detail section. Fetch it only
  // once the Details tab is open (enabled flag — the hook itself must run
  // unconditionally to keep hook order stable). Reuses the shared
  // asset-detail cache, so a cached section costs no request.
  const activityFetch = useAssetDetail(isUcAssetFqn(subjectFqn) ? subjectFqn : "", {
    sections: RAIL_ACTIVITY_SECTIONS,
    enabled: activeTab === "details",
  });
  const sources = useMemo(
    () =>
      graph.edges
        .filter((edge) => edge.target === subjectId)
        .map((edge) => graph.nodes.find((node) => node.id === edge.source))
        .filter(Boolean),
    [graph.edges, graph.nodes, subjectId],
  );
  const consumers = useMemo(
    () =>
      graph.edges
        .filter((edge) => edge.source === subjectId)
        .map((edge) => graph.nodes.find((node) => node.id === edge.target))
        .filter(Boolean),
    [graph.edges, graph.nodes, subjectId],
  );
  const focusedAsset = isFocusSelected ? asset : null;
  const RAIL_PLACEHOLDERS = new Set([
    "—",
    "-",
    "–",
    "n/a",
    "na",
    "unknown",
    "unassigned",
    "unavailable",
    "none",
    "null",
  ]);
  const railMeaningful = (value) => {
    if (value == null) return "";
    const trimmed = String(value).trim();
    if (!trimmed) return "";
    if (RAIL_PLACEHOLDERS.has(trimmed.toLowerCase())) return "";
    return trimmed;
  };
  const updatedAtIso =
    focusedAsset?.updatedAt ||
    focusedAsset?.lastRefresh ||
    focusedAsset?.refreshedAt ||
    focusedAsset?.detail?.updatedAt ||
    "";
  const updatedAtRelative = relativeFreshness(updatedAtIso);
  const detailFreshness =
    updatedAtRelative ||
    focusedAsset?.lastRefreshDisplay ||
    focusedAsset?.freshness ||
    focusedAsset?.lastRefresh ||
    focusedAsset?.refreshedAt ||
    focusedAsset?.detail?.freshness ||
    "";
  const detailRowCount = focusedAsset?.rowCountDisplay || focusedAsset?.rowCount || focusedAsset?.rows;
  const detailOwner = ownerLabel(focusedAsset, subject);
  const detailSize = railMeaningful(focusedAsset?.size);
  const detailFiles = railMeaningful(focusedAsset?.files);
  const detailType =
    [railMeaningful(focusedAsset?.managementType), railMeaningful(focusedAsset?.objectType)]
      .filter(Boolean)
      .join(" · ") || "";
  const detailActivity = Array.isArray(focusedAsset?.recentActivity)
    ? focusedAsset.recentActivity
    : Array.isArray(focusedAsset?.activity)
      ? focusedAsset.activity
      : [];
  // L10: lazily fetched `sections=activity` rows for the selected subject.
  const fetchedActivity = arrayValue(activityFetch?.detail?.activity);
  const recentActivity = detailActivity.length
    ? detailActivity
    : fetchedActivity.length
      ? fetchedActivity
      : subject?.recentActivity || [];
  const recentActivityCount = recentActivity.length || subject?.recentActivityCount || 0;
  // L2: merged rail stats — the focus subject reads from the asset detail
  // (focusedAsset); a selected non-focus subject falls back to its
  // batch-fetched node header stats so real values render instead of
  // "Unavailable".
  const railFreshness = detailFreshness || subjectStats.freshness || subject?.freshness || "";
  const railRows =
    detailRowCount != null && detailRowCount !== ""
      ? displayCount(detailRowCount)
      : subjectStats.rowCount || subject?.rowCount || "";
  const railOwner = detailOwner || subjectStats.ownerLabel || "";
  const railType = detailType || subjectStats.typeLabel || "";
  const railSize = detailSize || subjectStats.size || "";
  const railFiles = detailFiles || subjectStats.files || "";
  // L13: every count in this rail is bounded by the caller's visibility
  // scope. Annotate so "0" reads as "0 visible to you", not "0 exist".
  const railVisibilityScope = String(
    graph.meta?.visibilityScope || graph.meta?.capabilities?.visibilityScope || "",
  );
  const scopeNote = railVisibilityScope && railVisibilityScope !== "full"
    ? " within your visibility scope"
    : "";
  const columnLineageCount = Array.isArray(graph.columnEdges) ? graph.columnEdges.length : 0;
  const downstreamDashboards = consumers.filter((node) => node.kind === "dashboard");
  const downstreamJobs = consumers.filter((node) => node.kind === "job");
  const linkedPolicies = arrayValue(focusedAsset?.policies || focusedAsset?.linkedPolicies);
  const linkedControls = arrayValue(focusedAsset?.controls || focusedAsset?.linkedControls);
  const accessGrants = arrayValue(accessExplain?.data?.grants || accessExplain?.data?.permissions);
  const directColumnLineage = buildColumnDirectLineage(
    graph.columnLineage,
    selectedColumn,
    focus?.fqn,
  );
  const qualityRuns = arrayValue(quality?.runs).length;
  const qualityResults = arrayValue(quality?.results).length;
  const dqm = databricksEvidence?.qualityMonitoring || quality?.databricksMonitoring || {};
  const dqmRows = evidenceRows(dqm);
  const dqmSummary = dqm?.summary || {};
  const profileMetrics = databricksEvidence?.profileMetrics || {};
  const profileMetricRows = evidenceRows(profileMetrics);
  const lakeflow = databricksEvidence?.lakeflow || {};
  const lakeflowJobs = evidenceRows(lakeflow, "jobs");
  const lakeflowPipelines = evidenceRows(lakeflow, "pipelines");
  const pipelineEvents = databricksEvidence?.pipelineEvents || {};
  const pipelineEventRows = evidenceRows(pipelineEvents);
  const qualityAvailable = Boolean(
    quality?.summaryBacked ||
      qualityRuns ||
      qualityResults ||
      evidenceState(dqm) === "available",
  );
  const failedQuality = qualityAvailable
    ? Number(quality?.summary?.failed || 0) + Number(quality?.summary?.errored || 0)
    : null;
  const truncated = graph.stats?.truncated || {};
  const progressive = graph.stats?.progressive || {};
  // Truncation honesty (adversarial verify P1): the API emits exact totals
  // at graphs.data.meta.truncation ({nodesShown,nodesTotal,edgesShown,
  // edgesTotal}) plus upstreamTruncated/downstreamTruncated flags — the
  // adapter merges them into graph.meta. The old row only looked at
  // stats.truncated and rendered "No truncation flag returned" while the
  // payload said upstreamTruncated true. Consume the real fields.
  const truncationTotals =
    graph.meta?.truncation && typeof graph.meta.truncation === "object"
      ? graph.meta.truncation
      : null;
  const truncatedDirections = [
    graph.meta?.upstreamTruncated ? "upstream" : "",
    graph.meta?.downstreamTruncated ? "downstream" : "",
  ].filter(Boolean);
  const truncationEdgesShown = Number(truncationTotals?.edgesShown);
  const truncationEdgesTotal = Number(truncationTotals?.edgesTotal);
  const truncationSummary =
    Number.isFinite(truncationEdgesShown) &&
    Number.isFinite(truncationEdgesTotal) &&
    truncationEdgesTotal > truncationEdgesShown
      ? `Showing ${truncationEdgesShown} of ${truncationEdgesTotal} edges${
          truncatedDirections.length ? ` (${truncatedDirections.join(" + ")} capped)` : ""
        } — highest-traffic neighbors first`
      : truncatedDirections.length || Object.values(truncated).some(Boolean)
        ? `One or more lineage limits were reached${
            truncatedDirections.length ? ` (${truncatedDirections.join(" + ")})` : ""
          }`
        : truncationTotals
          ? "Not truncated — all recorded lineage edges shown"
          : "No truncation flag returned";
  const evidenceRecords = buildEvidenceRecords({
    accessExplain,
    columnLineageCount,
    databricksEvidence,
    focusedAsset,
    graph,
    quality,
  });
  const evidenceSources = evidenceSourceNames(evidenceRecords);
  const sqlSnippets = collectSqlSnippets(graph.edgeDetails, selectedColumn);
  const impactPacket = {
    generatedAt: new Date().toISOString(),
    assetFqn: subject?.fqn || focus?.fqn || "",
    selectedColumn: selectedColumn || null,
    lineage: {
      edgeCount: graph.edges.length,
      upstreamCount: sources.length,
      downstreamCount: consumers.length,
      stats: graph.stats || {},
      truncated,
      // Exact "shown of total" truncation counts from graphs.data.meta so
      // the exported brief matches the on-screen Decision Packet row.
      truncation: truncationTotals,
      truncatedDirections,
      progressive,
      source: graph.payload?.source || graph.meta?.source || "unity-catalog-lineage",
      authoritative: graph.payload?.authoritative === true || graph.meta?.authoritative === true,
      visibilityScope: graph.meta?.visibilityScope || graph.meta?.capabilities?.visibilityScope || "",
    },
    sources: sources.map((node) => ({ fqn: node.fqn, label: node.label, kind: node.kind })),
    consumers: consumers.map((node) => ({ fqn: node.fqn, label: node.label, kind: node.kind })),
    columnLineage: {
      directUpstream: directColumnLineage.upstream,
      directDownstream: directColumnLineage.downstream,
      upstreamTrace: columnTrace?.upstream || null,
      downstreamTrace: columnTrace?.downstream || null,
      upstreamError: columnTrace?.upstreamError || "",
      downstreamError: columnTrace?.downstreamError || "",
    },
    governance: {
      owner: detailOwner || "",
      certification: focusedAsset?.certification || subject?.raw?.details?.certification || "",
      sensitivity: focusedAsset?.sensitivity || subject?.classification || "",
      openRequests: focusedAsset?.openRequests ?? null,
      glossaryTerms: focusedAsset?.glossaryTerms || [],
      cde: focusedAsset?.isCde ?? null,
    },
    quality: {
      runs: quality?.runs || [],
      summary: qualityAvailable ? quality?.summary || null : null,
      databricksMonitoring: dqm,
      available: qualityAvailable,
      error: quality?.error || "",
    },
    databricksEvidence: {
      qualityMonitoring: dqm,
      profileMetrics,
      lakeflow,
      pipelineEvents,
      provenance: databricksEvidence?.provenance || [],
    },
    access: accessExplain?.data || null,
    evidenceSources,
    evidenceRecords,
  };
  const createNote = [
    `Asset: ${impactPacket.assetFqn}`,
    selectedColumn?.columnName ? `Selected column: ${selectedColumn.columnName}` : "",
    `Visible lineage edges: ${graph.edges.length}`,
    `Downstream consumers in current graph: ${consumers.length}`,
    qualityAvailable
      ? `Quality failures/errors returned: ${failedQuality}`
      : "Quality evidence unavailable in the current payload.",
    `Evidence records: ${evidenceRecords.map((record) => `${record.source} (${record.status})`).join(", ")}`,
  ].filter(Boolean).join("\n");

  return (
    <aside className="ax-lineage-v2-rail">
      <div className="ax-lineage-v2-rail-head">
        <span className="ax-lin-eyebrow">{isFocusSelected ? "Impact Inspector" : "Selected Node"}</span>
        <h2>{subject?.label || "Lineage Details"}</h2>
        {subject?.subtitle ? <small>{subject.subtitle}</small> : null}
        {!isFocusSelected && subject?.fqn ? (
          <button
            className="ax-lineage-v2-rail-reanchor"
            onClick={() => onReAnchor?.(subject.fqn)}
            title="Re-anchor the canvas on this node"
            type="button"
          >
            Re-anchor lineage
          </button>
        ) : null}
      </div>

      <div className="ax-lineage-v2-rail-tabs" role="tablist" aria-label="Lineage inspector tabs">
        {[
          ["impact", "Impact Brief"],
          ["details", "Details"],
          ["columns", "Columns"],
          ["evidence", "Evidence"],
        ].map(([key, label]) => (
          <button
            aria-selected={activeTab === key}
            className={activeTab === key ? "is-active" : ""}
            key={key}
            onClick={() => setActiveTab(key)}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === "impact" ? (
        <div className="ax-lineage-impact-panel">
          <div className="ax-lineage-impact-grid">
            <ImpactFact label="Downstream" value={compactCount(consumers.length)} detail={`visible graph consumers${scopeNote}`} tone={consumers.length ? "warn" : "neutral"} />
            <ImpactFact label="Column paths" value={compactCount(columnLineageCount)} detail="direct UC column links" tone={columnLineageCount ? "info" : "neutral"} />
            <ImpactFact
              label="Quality issues"
              value={qualityAvailable ? compactCount(failedQuality) : "Unavailable"}
              detail={qualityAvailable ? `${qualityRuns} Axiom run(s) · DQM ${dqmSummary.healthStatus || evidenceState(dqm) || "unavailable"}` : "quality evidence unavailable"}
              tone={failedQuality ? "crit" : "neutral"}
            />
            <ImpactFact
              label="DQM health"
              value={dqmSummary.healthStatus || (evidenceState(dqm) === "available" ? "Observed" : "Unavailable")}
              detail={dqmRows.length ? `${dqmRows.length} monitoring row(s)` : "system.data_quality_monitoring"}
              tone={String(dqmSummary.healthStatus || "").toLowerCase() === "healthy" ? "good" : String(dqmSummary.healthStatus || "").toLowerCase() === "unhealthy" ? "crit" : "neutral"}
            />
            <ImpactFact label="Open requests" value={focusedAsset?.openRequests ?? "Unavailable"} detail="governance store" tone={Number(focusedAsset?.openRequests) ? "warn" : "neutral"} />
            <ImpactFact label="Dashboards" value={compactCount(downstreamDashboards.length)} detail="downstream dashboard nodes" tone={downstreamDashboards.length ? "info" : "neutral"} />
            <ImpactFact label="Jobs" value={compactCount(Math.max(downstreamJobs.length, lakeflowJobs.length))} detail={lakeflowJobs.length ? "Lakeflow job runs" : "downstream job nodes"} tone={downstreamJobs.length || lakeflowJobs.length ? "warn" : "neutral"} />
            <ImpactFact label="Pipelines" value={compactCount(lakeflowPipelines.length)} detail={pipelineEventRows.length ? `${pipelineEventRows.length} event-log row(s)` : "Lakeflow updates"} tone={lakeflowPipelines.length ? "info" : "neutral"} />
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header><span>Decision packet</span></header>
            {/*
              L5: this packet used to render up to 8 "Unavailable: no …
              records returned" rows, several for fields no backend ever
              emits. Rows with a real backing source (owners, sensitivity,
              access, DQM/profile/Lakeflow via evidence hooks, approvals
              via the header's openRequests) render their backed values;
              fields with NO backend source (policies, controls) use plain
              honest copy. The "Approval blockers" row was removed — no
              backend emits approval-blocker records.
            */}
            <ul className="ax-lineage-impact-list">
              <li>Owners: <OwnerLink owner={detailOwner || subjectStats.ownerLabel} /></li>
              <li>Sensitivity: {focusedAsset?.sensitivity || subject?.classification || "No sensitivity label"}</li>
              <li>Access scope: {(() => {
                const scope = accessExplain?.data?.visibilityScope || graph.meta?.visibilityScope || "";
                const map = { "actor-scoped": "Your access", "workspace-scoped": "Workspace", "full-lineage": "Full lineage", "full": "Full" };
                return map[scope] || (scope ? scope.replace(/-/g, " ").replace(/scoped/g, "").trim() || "Permission-aware" : "Not returned");
              })()}</li>
              <li>Access grants: {accessGrants.length ? `${accessGrants.length} grant row(s) returned` : "No access-grant rows returned"}</li>
              <li>Policies: {linkedPolicies.length ? linkedPolicies.map((policy) => firstMeaningful(policy?.name, policy?.title, policy?.id, policy)).slice(0, 3).join(", ") : "No policies linked"}</li>
              <li>Controls affected: {linkedControls.length ? `${linkedControls.length} linked control(s)` : "No controls linked"}</li>
              <li>Databricks DQM: {dqmSummary.healthStatus ? `${dqmSummary.healthStatus} · freshness ${dqmSummary.freshnessStatus || "—"} · completeness ${dqmSummary.completenessStatus || "—"}` : "No DQM status returned"}</li>
              <li>Databricks profile: {profileMetricRows.length ? `${profileMetricRows.length} metric table row(s)` : profileMetrics?.monitor?.profileMetricsTableName ? "Monitor configured; metric tables not visible" : "No profile monitor returned"}</li>
              <li>Lakeflow: {lakeflowJobs.length || lakeflowPipelines.length ? `${lakeflowJobs.length} job run(s), ${lakeflowPipelines.length} pipeline update(s)` : "No Lakeflow rows joined from lineage"}</li>
              <li>
                Required approvals:{" "}
                {focusedAsset?.openRequests == null ? (
                  "Not returned for this selection"
                ) : Number(focusedAsset.openRequests) ? (
                  // Owner direction #2b: the open-request count links into the
                  // Stewardship queue scoped to this asset (surface ref — no
                  // per-item id is returned on the count, so we address the
                  // filtered queue, never a dead GOV-… link).
                  <EntityChip
                    appearance="inline"
                    entity={{
                      surface: "stewardship",
                      params: { q: subject?.fqn || focus?.fqn || "" },
                      label: `${focusedAsset.openRequests} open request(s)`,
                    }}
                  />
                ) : (
                  "No open approval requests"
                )}
              </li>
              <li>Truncation: {truncationSummary}</li>
              <li>Graph state: {Object.values(progressive).some(Boolean) ? "Still loading the full graph" : "Full graph loaded"}</li>
            </ul>
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header>
              <span>Downstream consumers</span>
              <span className="ax-lineage-v2-rail-count">{consumers.length}</span>
            </header>
            <LineageRows items={consumers.slice(0, 5)} empty={`No downstream consumers returned for this asset${scopeNote}.`} onSelectAsset={onSelectAsset} />
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header>
              <span>Downstream dashboards</span>
              <span className="ax-lineage-v2-rail-count">{downstreamDashboards.length}</span>
            </header>
            <LineageRows items={downstreamDashboards.slice(0, 4)} empty="No downstream dashboard nodes returned." onSelectAsset={onSelectAsset} />
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header>
              <span>Downstream jobs</span>
              <span className="ax-lineage-v2-rail-count">{Math.max(downstreamJobs.length, lakeflowJobs.length)}</span>
            </header>
            <LineageRows items={downstreamJobs.slice(0, 4)} empty="No downstream job nodes returned." onSelectAsset={onSelectAsset} />
            {lakeflowJobs.length ? (
              <ul className="ax-lineage-impact-list">
                {lakeflowJobs.slice(0, 3).map((job, index) => (
                  <li key={`${job.job_id || "job"}-${job.run_id || index}`}>
                    <strong>{job.job_name || job.job_id || "Lakeflow job"}</strong>
                    {/* L11: omit missing fragments instead of rendering
                        "Result unavailable · time unavailable" filler. */}
                    {[job.result_state, job.period_start_time || job.last_lineage_event]
                      .filter(Boolean)
                      .join(" · ") ? (
                      <span>
                        {[job.result_state, job.period_start_time || job.last_lineage_event]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <div className="ax-lineage-v2-rail-actions">
            <Button
              onClick={() => onExportImpactBrief?.(impactPacket)}
              variant="tertiary"
            >
              Export packet
            </Button>
            <Button
              disabled={!impactPacket.assetFqn}
              loading={Boolean(impactRequestState?.loading)}
              onClick={() =>
                onCreateImpactRequest?.({
                  assetFqn: impactPacket.assetFqn,
                  title: `Lineage impact review: ${subject?.label || impactPacket.assetFqn}`,
                  note: createNote,
                })
              }
              title={!impactPacket.assetFqn ? "Select an openable asset before creating a request." : undefined}
              variant="tertiary"
            >
              {impactRequestState?.loading ? "Creating request..." : "Create request"}
            </Button>
          </div>
          {impactRequestState?.message ? <p className="ax-lineage-request-status">{impactRequestState.message}</p> : null}
          {impactRequestState?.error ? <p className="ax-lineage-request-status tone-error">{impactRequestState.error}</p> : null}
        </div>
      ) : null}

      {activeTab === "details" ? (
        <>
          {subject ? (
            // L2: merged rail stats (asset detail for focus; batch node
            // header for non-focus subjects) — see railFreshness et al.
            <div className="ax-lineage-v2-rail-stats">
              {/* "Data updated" (not "Last refresh"): the value derives from
                  updatedAt / Delta write history (fix_plan #6). */}
              <div><span>Data updated</span><strong>{railFreshness || "Unavailable"}</strong></div>
              <div><span>Rows</span><strong>{railRows || "Unavailable"}</strong></div>
              <div><span>Owner</span><strong>{railOwner ? <OwnerLink owner={railOwner} /> : "Unavailable"}</strong></div>
              {railType ? <div><span>Type</span><strong>{railType}</strong></div> : null}
              {railSize ? <div><span>Size</span><strong>{railSize}{railFiles ? ` · ${railFiles} files` : ""}</strong></div> : null}
            </div>
          ) : null}
          <div className="ax-lineage-v2-rail-section">
            <header><span>Sources</span><span className="ax-lineage-v2-rail-count">{sources.length}</span></header>
            <LineageRows items={sources} empty={`No upstream sources returned${scopeNote}.`} onSelectAsset={onSelectAsset} />
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header><span>Recent activity</span><span className="ax-lineage-v2-rail-count">{recentActivityCount}</span></header>
            {recentActivity.length ? (
              <ul>
                {recentActivity.slice(0, 5).map((event, index) => {
                  const label = event.kind || event.title || event.action || "Activity";
                  const when = event.timestamp || event.observedAt || event.at || "";
                  // Owner direction #2b: an audit event with an id becomes a
                  // real link into the Evidence ledger (→ /evidence?event=ID).
                  // Events without an addressable id stay honest static rows.
                  const eventId = event.id || event.auditId || event.eventId || "";
                  return (
                    <li key={`${eventId || label}-${index}`}>
                      {eventId ? (
                        <EntityChip
                          appearance="row"
                          className="ax-lin-rail-row"
                          entity={{ kind: "event", id: eventId, label, meta: when }}
                        />
                      ) : (
                        <span className="ax-lin-rail-row-static">
                          <strong>{label}</strong>
                          <span>{when}</span>
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : activityFetch?.loading ? (
              // L10: activity is being fetched lazily now that this tab is
              // open — say "loading", never a premature empty.
              <p className="ax-lineage-v2-rail-empty">Loading recorded activity…</p>
            ) : (
              <p className="ax-lineage-v2-rail-empty">No recorded activity.</p>
            )}
          </div>
          {focus?.fqn ? (
            <div className="ax-lineage-v2-rail-actions">
              <Button onClick={() => onOpenAsset?.(focus.fqn, "overview")} variant="tertiary">
                Open asset record
              </Button>
            </div>
          ) : null}
        </>
      ) : null}

      {activeTab === "columns" ? (
        <div className="ax-lineage-column-panel">
          <div className="ax-lineage-v2-rail-section">
            <header>
              <span>{selectedColumn?.columnName ? "Selected column" : "Column lineage"}</span>
              <span className="ax-lineage-v2-rail-count">{columnLineageCount}</span>
            </header>
            <p className="ax-lineage-v2-rail-empty">
              {selectedColumn?.columnName
                ? `${selectedColumn.columnName} on ${selectedColumn.assetFqn}`
                : "Select a column on a table card to trace column-level impact."}
            </p>
          </div>
          {selectedColumn?.columnName ? (
            <>
              <ColumnTracePath
                directItems={directColumnLineage.upstream}
                error={columnTrace?.upstreamError}
                title="Upstream"
                trace={columnTrace?.upstream}
              />
              <ColumnTracePath
                directItems={directColumnLineage.downstream}
                error={columnTrace?.downstreamError}
                title="Downstream"
                trace={columnTrace?.downstream}
              />
              <div className="ax-lineage-sql-placeholder">
                <strong>Transformation SQL</strong>
                {sqlSnippets.length ? (
                  <div className="ax-lineage-sql-snippets">
                    {sqlSnippets.map((snippet) => (
                      <pre key={snippet.edgeId}>{snippet.sqlSnippet}</pre>
                    ))}
                  </div>
                ) : (
                  <span>Unity Catalog column lineage did not return transformation SQL for this path. SQL remains unavailable unless a backed query, view, job, or pipeline source supplies it.</span>
                )}
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {activeTab === "evidence" ? (
        <div className="ax-lineage-evidence-panel">
          <div className="ax-lineage-v2-rail-section">
            <header><span>Evidence sources</span></header>
            <ul className="ax-lineage-impact-list">
              {evidenceRecords.map((record) => (
                <li key={record.source}>
                  <strong>{record.source}</strong> · {record.status}
                  <span>{record.detail}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="ax-lineage-v2-rail-section">
            <header><span>Axiom AI evidence boundary</span></header>
            <p className="ax-lineage-v2-rail-empty">
              The impact packet is generated from the currently loaded lineage, governance, access, and quality evidence. Axiom AI should answer from this packet and returned evidence records; if the AI provider is unavailable, the exported packet remains the backed artifact.
            </p>
          </div>
        </div>
      ) : null}
    </aside>
  );
}

export default LineageDetailRail;
