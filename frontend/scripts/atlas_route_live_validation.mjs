import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const DEPLOYMENT_ID = process.env.GOVAT_DEPLOYMENT_ID || "";
const EXPECTED_BUILD_ID = process.env.GOVAT_BUILD_ID || "";
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const REQUEST_TIMEOUT_MS = Number(process.env.GOVAT_ROUTE_REQUEST_TIMEOUT_MS || 120_000);
const ASSET_FQN =
  process.env.GOVAT_ROUTE_ASSET_FQN ||
  "datapact.governance_atlas_demo.customer_stewardship_queue";
const OUT_PATH =
  process.env.GOVAT_ROUTE_OUT ||
  path.join(REPO_ROOT, "docs/genie/live-route-validation-latest.json");
const ASSET360_OUT_PATH =
  process.env.GOVAT_ASSET360_API_OUT ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/asset360-current/asset360-live-api-report.json");
const execFileAsync = promisify(execFile);

const SENTINEL_FALLBACK_SQL_RE =
  /union\s+all\s+select[\s\S]{0,240}['"]?(unavailable|none|no_data|n\/a|not_applicable)['"]?/i;
const SENTINEL_VALUES = new Set(["unavailable", "none", "no_data", "n/a", "not_applicable"]);
const SENTINEL_ID_KEYS = ["asset_fqn", "source_asset_fqn", "target_asset_fqn", "work_id", "audit_id", "term_id"];
const SENTINEL_DETAIL_KEYS = new Set(["detail", "message", "status"]);

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

function encodePathValue(value) {
  return encodeURIComponent(value).replaceAll("%2E", ".");
}

function get(obj, pathParts, fallback = undefined) {
  let current = obj;
  for (const part of pathParts) {
    if (current === null || current === undefined) return fallback;
    current = current[part];
  }
  return current === undefined ? fallback : current;
}

async function request(pathname, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const headers = {
    Accept: "application/json",
    ...(DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {}),
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  try {
    const response = await fetch(route(pathname), {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { rawText: text.slice(0, 2000) };
    }
    return {
      path: pathname,
      status: response.status,
      ok: response.ok,
      buildId: response.headers.get("x-govat-build-id") || "",
      payload,
    };
  } catch (error) {
    return requestWithCurl(pathname, options, headers, error);
  } finally {
    clearTimeout(timeout);
  }
}

async function requestWithCurl(pathname, options, headers, fetchError) {
  const args = [
    "-sS",
    "--connect-timeout",
    "30",
    "--max-time",
    "120",
    "-X",
    options.method || "GET",
  ];
  Object.entries(headers).forEach(([key, value]) => {
    args.push("-H", `${key}: ${value}`);
  });
  if (options.body) {
    args.push("--data-binary", JSON.stringify(options.body));
  }
  args.push("-D", "-", route(pathname));
  try {
    const { stdout } = await execFileAsync("curl", args, {
      maxBuffer: 20 * 1024 * 1024,
    });
    const chunks = stdout.split(/\r?\n\r?\n/);
    const body = chunks.pop() || "";
    const headerText = [...chunks].reverse().find((chunk) => /^HTTP\//i.test(chunk.trim())) || "";
    const status = Number((headerText.match(/^HTTP\/\S+\s+(\d+)/i) || [])[1] || 0);
    const headerMap = {};
    headerText.split(/\r?\n/).slice(1).forEach((line) => {
      const index = line.indexOf(":");
      if (index <= 0) return;
      headerMap[line.slice(0, index).trim().toLowerCase()] = line.slice(index + 1).trim();
    });
    let payload = null;
    try {
      payload = body ? JSON.parse(body) : null;
    } catch {
      payload = { rawText: body.slice(0, 2000) };
    }
    return {
      path: pathname,
      status,
      ok: status >= 200 && status < 300,
      buildId: headerMap["x-govat-build-id"] || "",
      payload,
      transport: "curl-fallback",
      fetchError: fetchError?.message || String(fetchError),
    };
  } catch (curlError) {
    return {
      path: pathname,
      status: 0,
      ok: false,
      buildId: "",
      payload: {
        fetchError: fetchError?.message || String(fetchError),
        curlError: curlError?.message || String(curlError),
      },
    };
  }
}

function resultRows(evidence) {
  const rows = [];
  for (const item of Array.isArray(evidence) ? evidence : []) {
    if (Array.isArray(item?.resultRows)) {
      rows.push(...item.resultRows.filter((row) => row && typeof row === "object"));
    }
  }
  return rows;
}

function rowText(row, key) {
  const value = row?.[key];
  return value === null || value === undefined ? "" : String(value).trim();
}

function isSentinelRow(row) {
  const idValues = SENTINEL_ID_KEYS.map((key) => rowText(row, key).toLowerCase()).filter(Boolean);
  if (!idValues.some((value) => SENTINEL_VALUES.has(value))) return false;
  const nonSentinelValues = Object.entries(row || {}).filter(([key, value]) => {
    if (SENTINEL_ID_KEYS.includes(key) || SENTINEL_DETAIL_KEYS.has(key)) return false;
    return value !== null && value !== undefined && String(value).trim();
  });
  if (nonSentinelValues.length) return false;
  const detail = [...SENTINEL_DETAIL_KEYS].map((key) => rowText(row, key).toLowerCase()).find(Boolean) || "";
  return (
    !detail ||
    detail.includes("no data") ||
    detail.includes("no quality issues") ||
    detail.includes("not available") ||
    detail.includes("unavailable")
  );
}

function hasSentinelEvidence(evidence, warnings) {
  const sqlFallback = (Array.isArray(evidence) ? evidence : []).some((item) =>
    SENTINEL_FALLBACK_SQL_RE.test(String(item?.sql || "")),
  );
  const rowFallback = resultRows(evidence).some((row) => isSentinelRow(row));
  const warningFallback = (Array.isArray(warnings) ? warnings : []).some((warning) =>
    String(warning || "").toLowerCase().includes("sentinel no-result"),
  );
  return { sqlFallback, rowFallback, warningFallback };
}

async function main() {
  const assetPath = encodePathValue(ASSET_FQN);
  const endpoints = {
    runtime: await request("/api/runtime/status"),
    bootstrap: await request("/api/bootstrap"),
    assetDetail: await request(
      `/api/assets/${assetPath}?sections=header&sections=activity&sections=schema&sections=properties&sections=operational&sections=profiler`,
    ),
    asset360: await request(`/api/atlas/assets/${assetPath}/360`),
    lineage: await request(`/api/lineage/${assetPath}`),
    governanceWorkbench: await request("/api/atlas/governance/workbench"),
    insights: await request("/api/atlas/insights"),
    taxonomyOverview: await request("/api/atlas/taxonomy/overview"),
    cdeDashboard: await request("/api/atlas/cde"),
    auditEvidence: await request("/api/atlas/audit/evidence?limit=25"),
    adminControlCenter: await request("/api/atlas/admin/control-center"),
    genieChat: await request("/api/atlas-ai/chat", {
      method: "POST",
      body: { question: "Show me data quality issues impacting critical assets." },
    }),
  };
  const cdePayloadForDetail = endpoints.cdeDashboard.payload || {};
  const cdeForDetail = cdePayloadForDetail.data || cdePayloadForDetail;
  const cdeItemsForDetail = [
    ...(Array.isArray(cdeForDetail.items) ? cdeForDetail.items : []),
    ...(Array.isArray(cdeForDetail.groups)
      ? cdeForDetail.groups.flatMap((group) => (Array.isArray(group?.items) ? group.items : []))
      : []),
  ];
  const cdeDetailId =
    cdeItemsForDetail.find((item) => item?.id || item?.assetFqn || item?.name)?.id ||
    cdeItemsForDetail.find((item) => item?.assetFqn || item?.name)?.assetFqn ||
    cdeItemsForDetail.find((item) => item?.name)?.name ||
    "";
  if (cdeDetailId) {
    endpoints.cdeDetail = await request(`/api/atlas/cde/${encodePathValue(cdeDetailId)}`);
  }
  const auditPayloadForDetail = endpoints.auditEvidence.payload || {};
  const auditForDetail = auditPayloadForDetail.data || auditPayloadForDetail;
  const auditEventsForDetail = Array.isArray(auditForDetail.events) ? auditForDetail.events : [];
  const auditDetailId =
    auditForDetail.selectedEvent?.audit_id ||
    auditForDetail.selectedEvent?.auditId ||
    auditEventsForDetail.find((event) => event?.audit_id || event?.auditId)?.audit_id ||
    auditEventsForDetail.find((event) => event?.audit_id || event?.auditId)?.auditId ||
    "";
  if (auditDetailId) {
    endpoints.auditEvidenceDetail = await request(
      `/api/atlas/audit/evidence?audit_id=${encodeURIComponent(auditDetailId)}&limit=25`,
    );
  }
  const governanceWorkbench = endpoints.governanceWorkbench.payload || {};
  const governanceRequestId =
    get(governanceWorkbench, ["selectedRequest", "requestId"]) ||
    get(governanceWorkbench, ["requests", 0, "requestId"]) ||
    "";
  if (governanceRequestId) {
    endpoints.governanceRequestDetail = await request(
      `/api/atlas/governance/requests/${encodeURIComponent(governanceRequestId)}`,
    );
  }

  const buildIds = Object.fromEntries(
    Object.entries(endpoints).map(([name, endpoint]) => [name, endpoint.buildId]),
  );
  const buildMatches = EXPECTED_BUILD_ID
    ? Object.values(buildIds).every((buildId) => buildId === EXPECTED_BUILD_ID)
    : Object.values(buildIds).every(Boolean);

  const bootstrap = endpoints.bootstrap.payload || {};
  const lakebase = get(bootstrap, ["shell", "storage", "lakebase"], {});
  const mirror = lakebase.writeMirror || {};
  const asset360 = endpoints.asset360.payload || {};
  const lineage = endpoints.lineage.payload || {};
  const governanceRequestDetail = endpoints.governanceRequestDetail?.payload || {};
  const insightsPayload = endpoints.insights.payload || {};
  const insights = insightsPayload.data || insightsPayload;
  const taxonomyPayload = endpoints.taxonomyOverview.payload || {};
  const taxonomy = taxonomyPayload.data || taxonomyPayload;
  const cdePayload = endpoints.cdeDashboard.payload || {};
  const cde = cdePayload.data || cdePayload;
  const cdeDetailPayload = endpoints.cdeDetail?.payload || {};
  const cdeDetail = cdeDetailPayload.data || cdeDetailPayload;
  const auditPayload = endpoints.auditEvidence.payload || {};
  const audit = auditPayload.data || auditPayload;
  const auditDetailPayload = endpoints.auditEvidenceDetail?.payload || {};
  const auditDetail = auditDetailPayload.data || auditDetailPayload;
  const adminPayload = endpoints.adminControlCenter.payload || {};
  const admin = adminPayload.data || adminPayload;
  const genie = endpoints.genieChat.payload || {};
  const genieWarnings = [
    ...(Array.isArray(genie.warnings) ? genie.warnings : []),
    ...(Array.isArray(genie.meta?.warnings) ? genie.meta.warnings : []),
  ];
  const sentinelEvidence = hasSentinelEvidence(genie.evidence, genieWarnings);
  const dataGraph = get(lineage, ["graphs", "data"], {});
  const operationalGraph = get(lineage, ["graphs", "operational"], {});
  const dataNodes = Array.isArray(dataGraph.nodes) ? dataGraph.nodes : [];
  const dataEdges = Array.isArray(dataGraph.edges) ? dataGraph.edges : [];
  const operationalNodes = Array.isArray(operationalGraph.nodes) ? operationalGraph.nodes : [];
  const focusNodeIds = new Set(
    dataNodes
      .filter((node) => String(node?.role || "").toLowerCase() === "focus")
      .map((node) => String(node?.id || ""))
      .filter(Boolean),
  );
  const stats = lineage.stats || {};
  const columnLineage = lineage.columnLineage || {};
  const columnUpstreamRows = Array.isArray(columnLineage.upstream) ? columnLineage.upstream : [];
  const columnDownstreamRows = Array.isArray(columnLineage.downstream)
    ? columnLineage.downstream
    : [];
  const derivedUpstreamCount = dataEdges.filter((edge) =>
    focusNodeIds.has(String(edge?.target || "")),
  ).length;
  const derivedDownstreamCount = dataEdges.filter((edge) =>
    focusNodeIds.has(String(edge?.source || "")),
  ).length;

  const checks = {
    runtimeOk: endpoints.runtime.ok,
    bootstrapOk: endpoints.bootstrap.ok,
    assetDetailOk: endpoints.assetDetail.ok && get(endpoints.assetDetail.payload, ["meta", "state"]) === "available",
    asset360Ok: endpoints.asset360.ok && get(asset360, ["meta", "state"]) === "available",
    lineageOk: endpoints.lineage.ok && get(lineage, ["meta", "state"]) === "available",
    governanceWorkbenchOk:
      endpoints.governanceWorkbench.ok &&
      Array.isArray(governanceWorkbench.requests) &&
      governanceWorkbench.requests.length > 0,
    governanceMetricCount: Array.isArray(governanceWorkbench.metrics)
      ? governanceWorkbench.metrics.length
      : 0,
    governanceRequestCount: Array.isArray(governanceWorkbench.requests)
      ? governanceWorkbench.requests.length
      : 0,
    governanceSelectedRequestId: governanceRequestId,
    governanceRequestDetailOk:
      Boolean(governanceRequestId) &&
      endpoints.governanceRequestDetail?.ok &&
      governanceRequestDetail.requestId === governanceRequestId,
    governanceDiffRows: Array.isArray(governanceRequestDetail.diff?.rows)
      ? governanceRequestDetail.diff.rows.length
      : 0,
    governanceApproverSteps: Array.isArray(governanceRequestDetail.approverFlow)
      ? governanceRequestDetail.approverFlow.length
      : 0,
    insightsDashboardOk:
      endpoints.insights.ok &&
      Array.isArray(insights.kpis) &&
      insights.kpis.length >= 6 &&
      Array.isArray(insights.metadataCoverageHeatmap) &&
      Array.isArray(insights.domainLeaderboard),
    insightsKpiCount: Array.isArray(insights.kpis) ? insights.kpis.length : 0,
    insightsHeatmapCellCount: Array.isArray(insights.metadataCoverageHeatmap)
      ? insights.metadataCoverageHeatmap.length
      : 0,
    insightsTierCount: Array.isArray(insights.certificationCoverageByTier)
      ? insights.certificationCoverageByTier.length
      : 0,
    insightsRiskCellCount: Array.isArray(insights.riskHeatmap)
      ? insights.riskHeatmap.length
      : 0,
    taxonomyOverviewOk:
      endpoints.taxonomyOverview.ok &&
      Array.isArray(taxonomy.classifications) &&
      Array.isArray(taxonomy.domains) &&
      Array.isArray(taxonomy.dataProducts) &&
      Array.isArray(taxonomy.columnGroups) &&
      Array.isArray(taxonomy.glossaryTerms) &&
      Number(taxonomy.summary?.termCount ?? taxonomy.glossaryTerms.length) === taxonomy.glossaryTerms.length,
    taxonomyClassificationCount: Array.isArray(taxonomy.classifications)
      ? taxonomy.classifications.length
      : 0,
    taxonomyDomainCount: Array.isArray(taxonomy.domains) ? taxonomy.domains.length : 0,
    taxonomyDataProductCount: Array.isArray(taxonomy.dataProducts)
      ? taxonomy.dataProducts.length
      : 0,
    taxonomyColumnGroupCount: Array.isArray(taxonomy.columnGroups)
      ? taxonomy.columnGroups.length
      : 0,
    taxonomyGlossaryTermCount: Array.isArray(taxonomy.glossaryTerms)
      ? taxonomy.glossaryTerms.length
      : 0,
    taxonomyGlossaryEnriched: Boolean(
      taxonomyPayload.meta?.capabilities?.glossaryEnriched ||
      taxonomy.meta?.capabilities?.glossaryEnriched,
    ),
    cdeDashboardOk:
      endpoints.cdeDashboard.ok &&
      Array.isArray(cde.items) &&
      Array.isArray(cde.groups) &&
      Number.isFinite(Number(cde.summary?.totalCdes ?? 0)) &&
      Number.isFinite(Number(cde.summary?.domainsCovered ?? 0)),
    cdeItemCount: Array.isArray(cde.items) ? cde.items.length : 0,
    cdeGroupCount: Array.isArray(cde.groups) ? cde.groups.length : 0,
    cdeTotalCdes: Number(cde.summary?.totalCdes ?? 0),
    cdeDomainsCovered: Number(cde.summary?.domainsCovered ?? 0),
    cdeControlCoverageUnavailable: Boolean(
      cdePayload.meta?.capabilities?.controlCoverage === false ||
      cde.meta?.capabilities?.controlCoverage === false,
    ),
    cdeProtectedNotInferred: cde.summary?.protectedCdes == null,
    cdeSensitiveCandidateCount: Number(cde.summary?.sensitiveCandidates ?? 0),
    cdeSourceNoQualityRunner: !String(cdePayload.meta?.source || cde.meta?.source || "").includes("quality-runner"),
    cdeDetailId,
    cdeDetailOk:
      !cdeDetailId ||
      (endpoints.cdeDetail?.ok &&
        (cdeDetail.id === cdeDetailId || cdeDetail.assetFqn === cdeDetailId || cdeDetail.name === cdeDetailId) &&
        Array.isArray(cdeDetail.controls) &&
        Boolean(cdeDetail.lineageSnapshot && typeof cdeDetail.lineageSnapshot === "object") &&
        Array.isArray(cdeDetail.linkedAssets) &&
        Array.isArray(cdeDetail.activity)),
    cdeDetailControlsArray: Array.isArray(cdeDetail.controls),
    cdeDetailLineageSnapshot: Boolean(cdeDetail.lineageSnapshot && typeof cdeDetail.lineageSnapshot === "object"),
    cdeDetailLinkedAssetsArray: Array.isArray(cdeDetail.linkedAssets),
    cdeDetailActivityArray: Array.isArray(cdeDetail.activity),
    auditEvidenceOk:
      endpoints.auditEvidence.ok &&
      Array.isArray(audit.events) &&
      Number.isFinite(Number(audit.summary?.totalChanges ?? 0)) &&
      Boolean(audit.selectedEvent && typeof audit.selectedEvent === "object") &&
      Boolean(audit.evidence && typeof audit.evidence === "object"),
    auditEventCount: Array.isArray(audit.events) ? audit.events.length : 0,
    auditSelectedId: auditDetailId,
    auditSourceTruth:
      String(auditPayload.meta?.source || audit.meta?.source || "") === "governance-store+metadata-audit-log",
    auditNoChangeEventsClaim: !String(auditPayload.meta?.source || audit.meta?.source || "").includes("change-events"),
    auditAuthoritative: Boolean(auditPayload.authoritative || audit.authoritative || auditPayload.meta?.authoritative),
    auditSummaryNumeric:
      Number.isFinite(Number(audit.summary?.totalChanges ?? NaN)) &&
      Number.isFinite(Number(audit.summary?.policyChanges ?? NaN)) &&
      Number.isFinite(Number(audit.summary?.approvals ?? NaN)) &&
      Number.isFinite(Number(audit.summary?.failedActions ?? NaN)),
    auditDetailOk:
      !auditDetailId ||
      (endpoints.auditEvidenceDetail?.ok &&
        (auditDetail.selectedEvent?.audit_id === auditDetailId || auditDetail.selectedEvent?.auditId === auditDetailId) &&
        Boolean(auditDetail.evidence && typeof auditDetail.evidence === "object")),
    auditEvidenceArrays:
      Array.isArray(auditDetail.evidence?.approvalChain || audit.evidence?.approvalChain) &&
      Array.isArray(auditDetail.evidence?.artifacts || audit.evidence?.artifacts),
    auditBeforeAfterKeys:
      Object.prototype.hasOwnProperty.call(auditDetail.evidence || audit.evidence || {}, "before") &&
      Object.prototype.hasOwnProperty.call(auditDetail.evidence || audit.evidence || {}, "after"),
    auditLinkedRequestKey:
      Object.prototype.hasOwnProperty.call(auditDetail.evidence || audit.evidence || {}, "linkedRequest"),
    adminControlCenterOk:
      endpoints.adminControlCenter.ok &&
      Boolean(admin && typeof admin === "object") &&
      Boolean(admin.policyRequirements && typeof admin.policyRequirements === "object") &&
      Boolean(admin.coverage && typeof admin.coverage === "object") &&
      Boolean(admin.bulkImport && typeof admin.bulkImport === "object") &&
      Array.isArray(admin.integrations) &&
      Array.isArray(admin.recentAdminActivity),
    adminMetaOk:
      String(adminPayload.meta?.source || admin.meta?.source || "") === "runtime-diagnostics+governance-store" &&
      String(adminPayload.meta?.state || admin.meta?.state || "") === "available" &&
      Boolean(adminPayload.authoritative || admin.authoritative || adminPayload.meta?.authoritative),
    adminCoverageOk:
      Object.prototype.hasOwnProperty.call(admin.coverage || {}, "metadataCoverage") &&
      (admin.coverage?.metadataCoverage == null || Number.isFinite(Number(admin.coverage.metadataCoverage))) &&
      Array.isArray(admin.coverage?.byDomain),
    adminBrandingOk:
      Boolean(String(admin.branding?.companyName || "").trim()) &&
      Boolean(String(admin.branding?.productName || "").trim()),
    adminBulkImportOk:
      Boolean(String(admin.bulkImport?.state || "").trim()) &&
      (
        String(admin.bulkImport?.state || "").toLowerCase() !== "unavailable" ||
        Boolean(String(admin.bulkImport?.message || "").trim())
      ),
    adminIntegrationsOk:
      Array.isArray(admin.integrations) &&
      admin.integrations.some((item) => item?.key === "unityCatalog") &&
      admin.integrations.every((item) =>
        item &&
        String(item.key || "").trim() &&
        String(item.label || "").trim() &&
        ["connected", "available", "unavailable", "degraded", "active"].includes(String(item.state || "").toLowerCase()),
      ),
    adminSystemOk:
      Boolean(admin.system && typeof admin.system === "object") &&
      !Object.prototype.hasOwnProperty.call(admin.system, "clientSecretPresent") &&
      !Object.prototype.hasOwnProperty.call(admin.system, "client"),
    adminRecentActivityOk:
      Array.isArray(admin.recentAdminActivity) &&
      (
        !admin.recentAdminActivity.length ||
        Boolean(admin.recentAdminActivity[0].id) &&
        Boolean(admin.recentAdminActivity[0].title) &&
        (
          Boolean(admin.recentAdminActivity[0].createdAt) ||
          Boolean(admin.recentAdminActivity[0].actorEmail) ||
          Boolean(admin.recentAdminActivity[0].detail)
        )
      ),
    genieChatOk: endpoints.genieChat.ok && get(genie, ["meta", "source"]) === "databricks-genie",
    buildMatches,
    lakebaseWriteMirror: mirror.state || "",
    lakebaseMode: mirror.mode || "",
    lakebaseAttempted: Number(mirror.attempted || 0),
    lakebaseSucceeded: Number(mirror.succeeded || 0),
    lakebaseFailed: Number(mirror.failed || 0),
    lakebaseActiveTables: mirror.activeTables || [],
    lakebaseDeferredTables: mirror.deferredTables || [],
    lakebaseDeltaRetainedTables: mirror.deltaRetainedTables || [],
    asset360SameAsset: get(asset360, ["asset", "fqn"]) === ASSET_FQN,
    asset360Sections: asset360.loadedSections || [],
    asset360SchemaCount: Array.isArray(asset360.schema) ? asset360.schema.length : 0,
    asset360ActivityCount: Array.isArray(asset360.activity) ? asset360.activity.length : 0,
    lineageAuthoritative: Boolean(lineage.authoritative || get(lineage, ["meta", "authoritative"])),
    lineageNodeCount:
      dataNodes.length + operationalNodes.length,
    lineageEdgeCount: dataEdges.length,
    lineageUpstreamCount: Number.isFinite(Number(stats.upstreamCount))
      ? Number(stats.upstreamCount)
      : derivedUpstreamCount,
    lineageDownstreamCount: Number.isFinite(Number(stats.downstreamCount))
      ? Number(stats.downstreamCount)
      : derivedDownstreamCount,
    lineageColumnLineageCount: columnUpstreamRows.length + columnDownstreamRows.length,
    lineageColumnUpstreamCount: columnUpstreamRows.length,
    lineageColumnDownstreamCount: columnDownstreamRows.length,
    genieProvider: genie.provider || "",
    genieConfidence: genie.confidence || "",
    genieEvidenceCount: Array.isArray(genie.evidence) ? genie.evidence.length : 0,
    genieAnswerLength: String(genie.answer || "").length,
    genieSentinelSqlFallback: sentinelEvidence.sqlFallback,
    genieSentinelRowFallback: sentinelEvidence.rowFallback,
    genieSentinelWarning: sentinelEvidence.warningFallback,
  };

  const endpointSummary = Object.fromEntries(
    Object.entries(endpoints).map(([name, endpoint]) => [
      name,
      {
        path: endpoint.path,
        status: endpoint.status,
        ok: endpoint.ok,
        buildId: endpoint.buildId,
      },
    ]),
  );

  const passed =
    checks.runtimeOk &&
    checks.bootstrapOk &&
    checks.assetDetailOk &&
    checks.asset360Ok &&
    checks.lineageOk &&
    checks.governanceWorkbenchOk &&
    checks.governanceMetricCount >= 4 &&
    checks.governanceRequestDetailOk &&
    checks.governanceDiffRows > 0 &&
    checks.governanceApproverSteps > 0 &&
    checks.insightsDashboardOk &&
    checks.taxonomyOverviewOk &&
    checks.cdeDashboardOk &&
    checks.cdeControlCoverageUnavailable &&
    checks.cdeProtectedNotInferred &&
    checks.cdeSourceNoQualityRunner &&
    checks.cdeDetailOk &&
    checks.auditEvidenceOk &&
    checks.auditEventCount > 0 &&
    checks.auditSourceTruth &&
    checks.auditNoChangeEventsClaim &&
    checks.auditAuthoritative &&
    checks.auditSummaryNumeric &&
    checks.auditDetailOk &&
    checks.auditEvidenceArrays &&
    checks.auditBeforeAfterKeys &&
    checks.auditLinkedRequestKey &&
    checks.adminControlCenterOk &&
    checks.adminMetaOk &&
    checks.adminCoverageOk &&
    checks.adminBrandingOk &&
    checks.adminBulkImportOk &&
    checks.adminIntegrationsOk &&
    checks.adminSystemOk &&
    checks.adminRecentActivityOk &&
    checks.genieChatOk &&
    checks.buildMatches &&
    checks.lakebaseWriteMirror === "active" &&
    checks.lakebaseMode === "delta-primary-lakebase-shadow" &&
    checks.lakebaseAttempted > 0 &&
    checks.lakebaseSucceeded === checks.lakebaseAttempted &&
    checks.lakebaseFailed === 0 &&
    checks.asset360SameAsset &&
    checks.asset360SchemaCount > 0 &&
    checks.asset360ActivityCount > 0 &&
    checks.lineageAuthoritative &&
    checks.lineageNodeCount > 0 &&
    checks.genieProvider === "genie" &&
    checks.genieConfidence === "genie-grounded" &&
    checks.genieEvidenceCount > 0 &&
    !checks.genieSentinelSqlFallback &&
    !checks.genieSentinelRowFallback &&
    !checks.genieSentinelWarning;

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    appUrl: APP_ORIGIN,
    deploymentId: DEPLOYMENT_ID,
    assetFqn: ASSET_FQN,
    evidenceKind: "live_databricks",
    mockApi: false,
    expectedBuildId: EXPECTED_BUILD_ID,
    buildIds,
    checks,
    endpoints: endpointSummary,
    passed,
    validationRule:
      "Endpoint checks must return HTTP 200 on the active build, Lakebase write mirror must be active with zero failures, Asset 360 must be same-asset, lineage must be authoritative/reachable, Governance workbench/detail must expose live requests with diff and approver evidence, Insights must return the dashboard KPI/heatmap/leaderboard contract, Taxonomy must return array-backed facet and glossary contracts, CDEs must return dashboard/detail envelopes with unavailable control coverage and no quality-runner source claim, Audit must return steward/admin-gated metadata-audit evidence with numeric summary, selected event, before/after keys, array-backed approval/artifact fields, a linkedRequest key, and no unsupported change-events source claim, Admin must return same-build control-center evidence with runtime diagnostics, coverage object, branding, integration health, bulk-import state, system/access shape, and recent admin activity array, and Atlas AI transport must be provider=genie with query evidence and no sentinel fallback SQL or result rows.",
  };

  await fs.mkdir(path.dirname(OUT_PATH), { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  await fs.mkdir(path.dirname(ASSET360_OUT_PATH), { recursive: true });
  await fs.writeFile(ASSET360_OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!passed) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
