import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SOURCE_REPORT =
  process.env.AXIOM_SOURCE_CAPTURE_REPORT ||
  path.join(
    REPO_ROOT,
    "docs/northstar_visual_qa/all-routes-live-v416-databricks/prototype-current-report.json",
  );
const OUT_PATH =
  process.env.AXIOM_THIN_STATE_OUT ||
  path.join(
    REPO_ROOT,
    "docs/northstar_visual_qa/live-thin-state-v416-databricks/live-thin-state-report.json",
  );
const DEPLOYMENT_ID =
  process.env.AXIOM_DEPLOYMENT_ID || process.env.AXIOM_EXPECTED_DEPLOYMENT_ID || "";
const EXPECTED_BUILD_ID =
  process.env.AXIOM_BUILD_ID || process.env.AXIOM_EXPECTED_BUILD_ID || "";

function rel(filePath) {
  const relative = path.relative(REPO_ROOT, filePath);
  return relative && !relative.startsWith("..") ? relative : filePath;
}

function asText(capture) {
  return String(capture?.metrics?.textPreview || "");
}

function captureFor(captures, route, viewport = "3037x1269") {
  return captures.find((capture) => capture.route === route && capture.viewport === viewport) || null;
}

function matches(text, pattern) {
  return pattern.test(text);
}

function expectedForbiddenOnly(report) {
  const failures = report.requestFailures || [];
  return (
    failures.length > 0 &&
    failures.every((failure) => {
      const url = String(failure?.url || "");
      return (
        Number(failure?.status) === 403 &&
        (/\/api\/axiom\/audit\/evidence/.test(url) || /\/api\/axiom\/admin\/control-center/.test(url))
      );
    })
  );
}

function expectedConsoleErrorsOnly(report) {
  const errors = (report.console || []).filter(
    (entry) => String(entry?.type || "").toLowerCase() === "error",
  );
  return (
    errors.length > 0 &&
    errors.every((entry) => {
      const url = String(entry?.url || "");
      const text = String(entry?.text || "");
      return /403/.test(text) && (/\/audit$/.test(url) || /\/admin$/.test(url));
    })
  );
}

async function main() {
  const raw = await fs.readFile(SOURCE_REPORT, "utf8");
  const source = JSON.parse(raw);
  const captures = source.captures || [];
  const runtimeStatus = source.runtimeStatus || {};
  const buildId = EXPECTED_BUILD_ID || String(source.buildId || runtimeStatus.buildId || "");
  const deploymentId = DEPLOYMENT_ID || String(source.deploymentId || "");

  const routeCaptures = Object.fromEntries(
    [
      "command-center",
      "discover",
      "stewardship",
      "glossary",
      "cde-registry",
      "lineage",
      "audit",
      "control-center",
    ].map((route) => [route, captureFor(captures, route)]),
  );
  const routeText = Object.fromEntries(
    Object.entries(routeCaptures).map(([route, capture]) => [route, asText(capture)]),
  );

  const checks = {
    sourceLiveDatabricks: source.evidenceKind === "live_databricks" && source.mockApi === false,
    runtimeLive: runtimeStatus.ok === true && runtimeStatus.state === "live",
    buildMatches: buildId ? runtimeStatus.buildId === buildId : Boolean(runtimeStatus.buildId),
    deploymentPinned: Boolean(deploymentId),
    allCapturesLoaded: captures.length === source.expectedCaptureCount && captures.every((capture) => capture.loaded),
    routeCoverageComplete: Object.values(routeCaptures).every(Boolean),
    noPageErrors: (source.pageErrors || []).length === 0,
    expectedForbiddenOnly: expectedForbiddenOnly(source),
    expectedConsoleErrorsOnly: expectedConsoleErrorsOnly(source),
    shellAndFabHandled:
      captures.every((capture) => capture.wait?.shellReady === true) &&
      captures.every(
        (capture) =>
          !Object.hasOwn(capture, "mainBottomAiDisabled") ||
          capture.mainBottomAiDisabled === true ||
          capture.mainBottomAiOpened === true,
      ),
    commandCenterLabelsUnavailable:
      matches(routeText["command-center"], /Backed values use live Unity Catalog/) &&
      matches(routeText["command-center"], /Trend unavailable/) &&
      matches(routeText["command-center"], /No authoritative policy-exception signal is available/) &&
      matches(routeText["command-center"], /Lineage proof unavailable|Lineage signal unavailable/),
    stewardshipNoSyntheticRows:
      matches(routeText.stewardship, /0 open work items/) &&
      matches(routeText.stewardship, /SLA evidence unavailable/) &&
      matches(routeText.stewardship, /Queue shape retained; no synthetic `SI-\*` request row is created/),
    glossaryUnavailableShape:
      matches(routeText.glossary, /HIERARCHY Unavailable/) &&
      matches(routeText.glossary, /Term evidence unavailable/) &&
      matches(routeText.glossary, /CDE Registry 17/),
    cdeUnavailableShape:
      matches(routeText["cde-registry"], /Critical Data Elements|CDE Registry/) &&
      matches(routeText["cde-registry"], /Unavailable|Source columns unavailable|owner workflow is unavailable/i),
    lineageUnavailableLabels:
      matches(routeText.lineage, /Permission-aware lineage/) &&
      matches(routeText.lineage, /Owner unavailable|CDEs unavailable|Certification unavailable|Lineage unavailable/i),
    auditUnavailableShape:
      matches(routeText.audit, /Audit evidence is unavailable for this workspace/) &&
      matches(routeText.audit, /Audit trail is steward\/admin only/) &&
      matches(routeText.audit, /No audit events match the current filters/),
    controlCenterAdminOnlyShape:
      matches(routeText["control-center"], /Control Center is admin-only/) &&
      matches(routeText["control-center"], /Schedule unavailable/) &&
      matches(routeText["control-center"], /Runtime signal unavailable/),
  };

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl: source.baseUrl,
    appUrl: source.baseUrl,
    deploymentId,
    buildId,
    evidenceKind: "live_databricks",
    mockApi: false,
    passed: Object.values(checks).every(Boolean),
    captureCount: captures.length,
    interactionCount: 0,
    requestFailureCount: (source.requestFailures || []).length,
    consoleErrorCount: (source.console || []).filter(
      (entry) => String(entry?.type || "").toLowerCase() === "error",
    ).length,
    pageErrorCount: (source.pageErrors || []).length,
    sourceCaptureReport: rel(SOURCE_REPORT),
    sourceCapturePassed: source.passed === true,
    sourceFailureReason:
      "Source capture-health is expected to be false for Reader access because Audit/Admin APIs return 403; this report verifies the rendered unavailable/admin-only states.",
    runtimeStatus,
    expectedForbiddenEndpoints: [
      "/api/axiom/audit/evidence",
      "/api/axiom/admin/control-center",
    ],
    captures: captures.map((capture) => ({
      route: capture.route,
      viewport: capture.viewport,
      loaded: capture.loaded,
      screenshot: capture.screenshot,
      fullPageScreenshot: capture.fullPageScreenshot,
      mainBottomScreenshot: capture.mainBottomScreenshot,
      shellReady: capture.wait?.shellReady === true,
      textPreview: String(capture.metrics?.textPreview || "").slice(0, 1000),
    })),
    interactions: [],
    requestFailures: source.requestFailures || [],
    console: source.console || [],
    pageErrors: source.pageErrors || [],
    checks,
  };

  await fs.mkdir(path.dirname(OUT_PATH), { recursive: true });
  await fs.writeFile(OUT_PATH, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
