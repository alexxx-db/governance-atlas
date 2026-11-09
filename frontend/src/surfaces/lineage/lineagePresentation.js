/*
 * surfaces/lineage/lineagePresentation.js — pure presentation helpers for the
 * Lineage Atlas surface (Wave C7). Verbatim port of the helper layer from the
 * legacy components/LineageWorkspace.jsx (deleted this wave): the current
 * lineage behavior passed adversarial verification, so these functions are
 * the spec — every honesty rule (L5/L11/L12, truncation totals, evidence
 * gating) is preserved with its original WHY comment.
 */

export function compactCount(value) {
  const number = Number(value);
  // L12: a non-numeric count used to render the word "Unavailable", which
  // concatenated into gibberish like "Unavailable edges". A dash reads as
  // "no value" without pretending to be a stat.
  if (!Number.isFinite(number)) return "—";
  return Math.max(0, Math.trunc(number)).toLocaleString();
}

export function displayCount(value) {
  if (value == null || value === "") return "Unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return Math.max(0, Math.trunc(number)).toLocaleString();
}

export function isUcAssetFqn(value) {
  const parts = String(value || "").split(".").filter(Boolean);
  return parts.length === 3 && parts.every((part) => part.trim());
}

/**
 * Build an absolute Catalog Explorer deep link for a UC asset.
 *
 * Truth order (honesty contract — never invent a link we can't stand behind):
 *   1. A backend-supplied deepLink path (from the /access-explain payload's
 *      deepLinks.catalogExplorer) is authoritative — absolutize it against
 *      the workspace host if it is relative, or pass it through if absolute.
 *   2. Otherwise construct `/explore/data/<catalog>/<schema>/<table>` — the
 *      exact shape the backend itself emits (axiom/services/capabilities.py) —
 *      but ONLY when we have BOTH a real workspace host AND a 3-part FQN.
 *   3. No host or no FQN → "" (the caller renders nothing rather than a dead
 *      or wrong link).
 */
export function catalogExplorerUrl(fqn, workspaceHost, deepLinkPath = "") {
  let host = String(workspaceHost || "").trim().replace(/\/+$/, "");
  if (host && !/^https?:\/\//i.test(host)) host = `https://${host}`;
  const rel = String(deepLinkPath || "").trim();
  if (/^https?:\/\//i.test(rel)) return rel;
  if (host && rel.startsWith("/")) return `${host}${rel}`;
  const parts = String(fqn || "").split(".").filter((part) => part.trim());
  if (parts.length < 3 || !host) return "";
  return `${host}/explore/data/${parts[0]}/${parts[1]}/${parts.slice(2).join("/")}`;
}

/** Resolve the workspace host from a bootstrap payload (shell block). */
export function workspaceHostFromBootstrap(bootstrap) {
  return String(
    bootstrap?.shell?.workspaceHost ||
      bootstrap?.shell?.environment?.workspaceHost ||
      bootstrap?.workspaceHost ||
      "",
  ).trim();
}

export function ownerLabel(asset, fallbackNode) {
  const owners = Array.isArray(asset?.owners) && asset.owners.length
    ? asset.owners
    : Array.isArray(fallbackNode?.owners)
      ? fallbackNode.owners
      : [];
  const first = owners[0] || {};
  return (
    asset?.ownerDisplayName ||
    asset?.owner ||
    asset?.steward ||
    first.displayName ||
    first.email ||
    first.name ||
    ""
  );
}

/**
 * Relative "Data updated" formatting derived from an updatedAt-style ISO
 * timestamp — the ONE implementation the hero chips and the rail stats both
 * use, so they can never disagree (was duplicated inline in the legacy
 * workspace's hero + rail).
 */
export function relativeFreshness(updatedAtIso) {
  if (!updatedAtIso) return "";
  const ts = Date.parse(updatedAtIso);
  if (!Number.isFinite(ts)) return "";
  const deltaMs = Date.now() - ts;
  if (deltaMs < 0) return "future";
  const minutes = Math.round(deltaMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.round(days / 365);
  return `${years}y ago`;
}

export function buildColumnDirectLineage(columnLineage, selectedColumn, focusFqn) {
  const columnName = selectedColumn?.columnName || "";
  if (!columnName || selectedColumn?.assetFqn !== focusFqn) {
    return { upstream: [], downstream: [], appliesToFocus: false };
  }
  const upstreamEntry = (columnLineage?.upstream || []).find((entry) => entry.column === columnName);
  const downstreamEntry = (columnLineage?.downstream || []).find((entry) => entry.column === columnName);
  return {
    upstream: upstreamEntry?.sources || [],
    downstream: downstreamEntry?.targets || [],
    appliesToFocus: true,
  };
}

export function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

export function firstMeaningful(...values) {
  for (const value of values) {
    if (value == null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}

export function evidenceState(section) {
  return String(section?.state || "").trim().toLowerCase();
}

export function evidenceRows(section, key = "rows") {
  return Array.isArray(section?.[key]) ? section[key] : [];
}

export function sourceStateToEvidenceStatus(state) {
  const normalized = String(state || "").toLowerCase();
  if (normalized === "available") return "available";
  if (normalized === "empty") return "unavailable";
  if (normalized === "loading") return "loading";
  if (normalized === "degraded") return "degraded";
  if (normalized === "unavailable" || normalized === "not_authorized" || normalized === "timeout") return "unavailable";
  return normalized || "unavailable";
}

export function buildEvidenceRecords({
  accessExplain,
  columnLineageCount,
  databricksEvidence,
  focusedAsset,
  graph,
  quality,
}) {
  const graphSource = graph?.payload?.source || graph?.meta?.source || "unity-catalog-lineage";
  const graphAuthoritative = graph?.payload?.authoritative === true || graph?.meta?.authoritative === true;
  const graphVisibility = graph?.meta?.visibilityScope || graph?.meta?.capabilities?.visibilityScope || "";
  const graphDegraded = graph?.meta?.degraded === true || graph?.meta?.authoritative === false;
  const columnMeta = graph?.columnLineage?.meta || {};
  const columnAvailable = columnLineageCount > 0 || (
    Object.keys(columnMeta).length > 0 &&
    columnMeta.deferred !== true
  );
  const governanceAvailable = Boolean(
    focusedAsset &&
      (
        focusedAsset.openRequests != null ||
        arrayValue(focusedAsset.glossaryTerms).length ||
        focusedAsset.isCde != null ||
        firstMeaningful(focusedAsset.certification, focusedAsset.sensitivity, focusedAsset.criticality)
      ),
  );
  const qualityAvailable = Boolean(
    quality?.summaryBacked ||
      arrayValue(quality?.runs).length ||
      arrayValue(quality?.results).length ||
      evidenceState(quality?.databricksMonitoring) === "available" ||
      evidenceState(databricksEvidence?.qualityMonitoring) === "available",
  );
  const accessAvailable = Boolean(accessExplain?.data && !accessExplain?.error);
  const dqm = databricksEvidence?.qualityMonitoring || quality?.databricksMonitoring || {};
  const profileMetrics = databricksEvidence?.profileMetrics || {};
  const lakeflow = databricksEvidence?.lakeflow || {};
  const pipelineEvents = databricksEvidence?.pipelineEvents || {};
  return [
    {
      source: graphSource,
      status: graphDegraded ? "degraded" : "available",
      detail: graphAuthoritative
        ? `Actor-scoped lineage${graphVisibility ? ` (${graphVisibility})` : ""}.`
        : `Lineage returned without actor-scoped authority${graphVisibility ? ` (${graphVisibility})` : ""}.`,
    },
    {
      source: "system.access.table_lineage",
      status: graph?.edges?.length || graph?.stats?.progressive?.tableLineageDeferred === false ? "available" : "unavailable",
      detail: graph?.edges?.length
        ? `${graph.edges.length} visible graph edge(s) loaded.`
        : "No table-lineage edges are loaded for this focus.",
    },
    {
      source: "system.access.column_lineage",
      status: columnAvailable ? "available" : "unavailable",
      detail: columnAvailable
        ? `${columnLineageCount} direct column lineage path(s) loaded.`
        : "Column lineage did not return backed paths for the current focus/selection.",
    },
    {
      source: "governance-store",
      status: governanceAvailable ? "available" : "unavailable",
      detail: governanceAvailable
        ? "Governance fields or request counts are present on the asset record."
        : "Governance request/control rows are not available for this asset in the current payload.",
    },
    {
      source: "quality-runner+databricks-dqm",
      status: qualityAvailable ? "available" : "unavailable",
      detail: qualityAvailable
        ? `${arrayValue(quality?.runs).length} Axiom quality run(s), ${arrayValue(quality?.results).length} result row(s), Databricks DQM ${evidenceState(dqm) || "unavailable"}.`
        : quality?.error || "No backed quality or Databricks monitoring evidence is available for this asset.",
    },
    {
      source: dqm?.source || "system.data_quality_monitoring.table_results",
      status: sourceStateToEvidenceStatus(evidenceState(dqm)),
      detail: dqm?.summary?.healthStatus
        ? `Health ${dqm.summary.healthStatus}; freshness ${dqm.summary.freshnessStatus || "Unavailable"}; completeness ${dqm.summary.completenessStatus || "Unavailable"}.`
        : (arrayValue(dqm?.warnings)[0] || "No Databricks data quality monitoring rows returned."),
    },
    {
      source: profileMetrics?.source || "databricks-data-profiling",
      status: sourceStateToEvidenceStatus(evidenceState(profileMetrics)),
      detail: evidenceState(profileMetrics) === "available"
        ? `${evidenceRows(profileMetrics).length} metric table row(s); lookup ${profileMetrics?.summary?.lookupMethod || "unknown"}.`
        : (arrayValue(profileMetrics?.warnings)[0] || "No Databricks profile metric tables returned."),
    },
    {
      source: lakeflow?.source || "system.lakeflow",
      status: sourceStateToEvidenceStatus(evidenceState(lakeflow)),
      detail: evidenceState(lakeflow) === "available"
        ? `${evidenceRows(lakeflow, "jobs").length} job run(s), ${evidenceRows(lakeflow, "pipelines").length} pipeline update(s) joined from lineage.`
        : (arrayValue(lakeflow?.warnings)[0] || "No Lakeflow workflow rows returned for this asset."),
    },
    {
      source: pipelineEvents?.source || "event_log",
      status: sourceStateToEvidenceStatus(evidenceState(pipelineEvents)),
      detail: evidenceState(pipelineEvents) === "available"
        ? `${evidenceRows(pipelineEvents).length} pipeline event-log row(s) returned.`
        : (arrayValue(pipelineEvents?.warnings)[0] || "No pipeline event-log rows returned."),
    },
    {
      source: "access-explain",
      status: accessAvailable ? "available" : "unavailable",
      detail: accessAvailable
        ? accessExplain.data?.visibilityScope || accessExplain.data?.authMode || "Access explainer payload returned."
        : accessExplain?.error || "Access-grant detail is not available in this payload.",
    },
  ].filter((record) => record.source);
}

export function collectSqlSnippets(edgeDetails, selectedColumn) {
  if (!selectedColumn?.columnName || !edgeDetails || typeof edgeDetails !== "object") return [];
  const columnName = String(selectedColumn.columnName).trim().toLowerCase();
  return Object.entries(edgeDetails)
    .map(([edgeId, detail]) => ({ edgeId, detail }))
    .filter(({ detail }) => {
      const snippet = firstMeaningful(detail?.sqlSnippet, detail?.sql);
      if (!snippet) return false;
      const mappings = arrayValue(detail?.columnMappings);
      if (!mappings.length) return true;
      return mappings.some((mapping) =>
        String(mapping?.sourceColumn || "").trim().toLowerCase() === columnName ||
        String(mapping?.targetColumn || "").trim().toLowerCase() === columnName,
      );
    })
    .slice(0, 3)
    .map(({ edgeId, detail }) => ({
      edgeId,
      sourceAssetFqn: detail?.sourceAssetFqn || "",
      targetAssetFqn: detail?.targetAssetFqn || "",
      sqlSnippet: firstMeaningful(detail?.sqlSnippet, detail?.sql),
    }));
}

export function evidenceSourceNames(records) {
  return [
    ...new Set(
      arrayValue(records)
        .filter((record) => record.status === "available" || record.status === "degraded")
        .map((record) => record.source)
        .filter(Boolean),
    ),
  ];
}

export function downloadImpactPacket(packet) {
  if (typeof document === "undefined") return;
  const blob = new Blob([JSON.stringify(packet, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeFqn = String(packet?.assetFqn || "lineage-impact")
    .replace(/[^a-zA-Z0-9_.-]/g, "_")
    .slice(0, 120);
  link.href = url;
  link.download = `axiom-impact-brief-${safeFqn}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
