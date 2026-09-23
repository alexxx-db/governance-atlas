import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BASE_URL =
  process.env.GOVAT_BASE_URL ||
  (() => { throw new Error("Set GOVAT_BASE_URL to the deployed Atlas app URL"); })();
const APP_ORIGIN = new URL(BASE_URL).origin;
const DATABRICKS_TOKEN = process.env.GOVAT_DATABRICKS_TOKEN || "";
const DEPLOYMENT_ID =
  process.env.GOVAT_DEPLOYMENT_ID || process.env.GOVAT_EXPECTED_DEPLOYMENT_ID || "";
const EXPECTED_BUILD_ID =
  process.env.GOVAT_BUILD_ID || process.env.GOVAT_EXPECTED_BUILD_ID || "";
const OUT_PATH =
  process.env.GOVAT_LINEAGE_TRUTH_OUT ||
  path.join(REPO_ROOT, "docs/northstar_visual_qa/lineage-truth-live/lineage-truth-report.json");
const REQUEST_TIMEOUT_MS = Number(process.env.GOVAT_LINEAGE_TRUTH_TIMEOUT_MS || 180_000);
const ASSETS = [
  {
    key: "richDatapact",
    fqn: "main.datapact.run_history",
    minUpstream: 20,
    minDownstream: 4,
    minColumnPaths: 20,
  },
  {
    key: "richMortgage",
    fqn: "mip.gold.borrower_360",
    minUpstream: 7,
    minDownstream: 12,
    minColumnPaths: 70,
  },
  {
    key: "restrictedDownstream",
    fqn: "main.mdm_schema.mdm_manual_overrides",
    minUpstream: 0,
    minDownstream: 20,
    minColumnPaths: 1,
    minRestrictedDownstream: 1,
  },
  {
    key: "restrictedBoundary",
    fqn: "alex.observability.user_dbu_cost_daily",
    minUpstream: 3,
    minDownstream: 2,
    minColumnPaths: 20,
    requireRestrictedNode: true,
  },
  {
    key: "hiddenFocus",
    fqn: "system.__internal_logging.payload_logs",
    expectUnavailableState: "hidden",
  },
];

function encodePathValue(value) {
  return encodeURIComponent(value).replaceAll("%2E", ".");
}

function route(pathname) {
  return new URL(pathname, APP_ORIGIN).toString();
}

async function requestLineage(assetFqn) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(route(`/api/lineage/${encodePathValue(assetFqn)}`), {
      headers: {
        Accept: "application/json",
        ...(DATABRICKS_TOKEN ? { Authorization: `Bearer ${DATABRICKS_TOKEN}` } : {}),
      },
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
      status: response.status,
      ok: response.ok,
      buildId: response.headers.get("x-govat-build-id") || "",
      payload,
    };
  } finally {
    clearTimeout(timeout);
  }
}

function array(value) {
  return Array.isArray(value) ? value : [];
}

function lineageMetrics(payload) {
  const dataGraph = payload?.graphs?.data || {};
  const nodes = array(dataGraph.nodes);
  const edges = array(dataGraph.edges);
  const columnLineage = payload?.columnLineage || {};
  const columnUpstream = array(columnLineage.upstream);
  const columnDownstream = array(columnLineage.downstream);
  const restrictedNodes = nodes.filter((node) => {
    const detail = node?.details || {};
    const text = `${node?.assetFqn || ""} ${node?.label || ""} ${node?.foot || ""} ${detail.openabilityState || ""} ${detail.resolutionState || ""}`.toLowerCase();
    return (
      detail.isOpenable === false ||
      /metadata record unavailable|lineage-only|system\./.test(text)
    );
  });
  const stats = payload?.stats || {};
  return {
    authoritative: Boolean(payload?.authoritative || payload?.meta?.authoritative),
    state: payload?.meta?.state || "",
    source: payload?.meta?.source || "",
    visibilityState: payload?.meta?.capabilities?.visibilityState || "",
    upstreamCount: Number(stats.upstreamCount || 0),
    downstreamCount: Number(stats.downstreamCount || 0),
    nodeCount: nodes.length,
    edgeCount: edges.length,
    columnUpstreamCount: columnUpstream.length,
    columnDownstreamCount: columnDownstream.length,
    columnPathCount: columnUpstream.length + columnDownstream.length,
    columnTruncated: Boolean(columnLineage?.meta?.truncated),
    restrictedNodeCount: restrictedNodes.length,
    restrictedNodes: restrictedNodes.map((node) => ({
      assetFqn: node?.assetFqn || "",
      role: node?.role || "",
      label: node?.label || "",
      openabilityState: node?.details?.openabilityState || "",
      resolutionState: node?.details?.resolutionState || "",
      isOpenable: node?.details?.isOpenable,
      foot: array(node?.foot),
    })),
    restrictedDownstreamCount: restrictedNodes.filter((node) => node?.role === "target").length,
    sampleNodes: nodes.slice(0, 10).map((node) => ({
      assetFqn: node?.assetFqn || "",
      role: node?.role || "",
      label: node?.label || "",
      openabilityState: node?.details?.openabilityState || "",
      resolutionState: node?.details?.resolutionState || "",
      isOpenable: node?.details?.isOpenable,
    })),
  };
}

function validateProbe(spec, response, metrics) {
  if (spec.expectUnavailableState) {
    const checks = {
      statusUnavailable: response.status >= 400 && response.status < 500,
      buildMatches: EXPECTED_BUILD_ID ? response.buildId === EXPECTED_BUILD_ID : Boolean(response.buildId),
    };
    checks.unavailableStateMatches =
      metrics.state === "unavailable" &&
      metrics.visibilityState === spec.expectUnavailableState &&
      response.payload?.graphs === undefined;
    return checks;
  }
  const checks = {
    statusOk: response.status >= 200 && response.status < 300,
    buildMatches: EXPECTED_BUILD_ID ? response.buildId === EXPECTED_BUILD_ID : Boolean(response.buildId),
  };
  checks.available = metrics.state === "available";
  checks.authoritative = metrics.authoritative;
  checks.sourceIsUcLineage = metrics.source === "unity-catalog-lineage";
  checks.upstreamMeetsMinimum = metrics.upstreamCount >= Number(spec.minUpstream || 0);
  checks.downstreamMeetsMinimum = metrics.downstreamCount >= Number(spec.minDownstream || 0);
  checks.edgesPresent = metrics.edgeCount >= metrics.upstreamCount + metrics.downstreamCount;
  checks.columnLineageMeetsMinimum = metrics.columnPathCount >= Number(spec.minColumnPaths || 0);
  if (spec.requireRestrictedNode) {
    checks.restrictedNodePresent = metrics.restrictedNodeCount > 0;
  }
  if (spec.minRestrictedDownstream) {
    checks.restrictedDownstreamPresent =
      metrics.restrictedDownstreamCount >= Number(spec.minRestrictedDownstream || 0);
  }
  return checks;
}

async function main() {
  const probes = [];
  for (const spec of ASSETS) {
    const response = await requestLineage(spec.fqn);
    const metrics = lineageMetrics(response.payload || {});
    const checks = validateProbe(spec, response, metrics);
    probes.push({
      key: spec.key,
      assetFqn: spec.fqn,
      status: response.status,
      ok: response.ok,
      buildId: response.buildId,
      metrics,
      checks,
      passed: Object.values(checks).every(Boolean),
    });
  }
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: BASE_URL,
    appUrl: APP_ORIGIN,
    deploymentId: DEPLOYMENT_ID,
    buildId: EXPECTED_BUILD_ID,
    evidenceKind: "live_databricks",
    mockApi: false,
    captureCount: 0,
    interactionCount: probes.length,
    requestFailureCount: 0,
    consoleErrorCount: 0,
    pageErrorCount: 0,
    probes,
    interactions: probes.map((probe) => ({
      route: "lineage",
      interaction: `lineage-truth-${probe.key}`,
      name: `lineage-truth-${probe.key}`,
      assetFqn: probe.assetFqn,
      passed: probe.passed,
      validation: { checks: probe.checks },
      metrics: probe.metrics,
    })),
    requestFailures: [],
    console: [],
    pageErrors: [],
  };
  report.checks = {
    buildMatches: probes.every((probe) =>
      EXPECTED_BUILD_ID ? probe.buildId === EXPECTED_BUILD_ID : Boolean(probe.buildId),
    ),
    richDatapactLineageBacked: probes.find((probe) => probe.key === "richDatapact")?.passed === true,
    richMortgageLineageBacked: probes.find((probe) => probe.key === "richMortgage")?.passed === true,
    restrictedDownstreamBoundaryBacked:
      probes.find((probe) => probe.key === "restrictedDownstream")?.passed === true,
    restrictedBoundaryBacked:
      probes.find((probe) => probe.key === "restrictedBoundary")?.passed === true,
    hiddenFocusFailsClosed: probes.find((probe) => probe.key === "hiddenFocus")?.passed === true,
  };
  report.passed = Object.values(report.checks).every(Boolean);
  await fs.mkdir(path.dirname(OUT_PATH), { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
