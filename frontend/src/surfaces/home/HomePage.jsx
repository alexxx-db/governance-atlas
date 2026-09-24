import "./home.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, LoadingState, PageShell, UnavailableState, toast } from "../../components/system";
import { fetchBoardReportHtml } from "../../lib/api";
import { useCommandCenter } from "../../hooks/useCommandCenter";
import { useInsightsDashboard } from "../../hooks/useInsightsDashboard";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import {
  catalogRows,
  cdeRows,
  domainRows,
  eventRows,
  hasBackedSignal,
  numericValue,
  relativeTimeLabel,
  requestRows,
  riskSummary,
} from "./format.js";
import { PostureHero } from "./sections/PostureHero.jsx";
import { KpiRow } from "./sections/KpiRow.jsx";
import { TrendCard } from "./sections/TrendCard.jsx";
import { CategoryTrendCard } from "./sections/CategoryTrendCard.jsx";
import { CatalogHealthCard, DomainPostureCard, RiskFindingsCard } from "./sections/EstateCards.jsx";
import { ActivityCard, CdeCard, RequestsCard } from "./sections/GovernanceCards.jsx";
import { InsightsBand } from "./sections/InsightsBand.jsx";

/*
 * surfaces/home/HomePage.jsx — Command Center (Wave C2, COHESION surface map
 * J1). The single executive answer to "what is the state of governance and
 * what changed", with every number a door to its evidence. Absorbs the
 * Insights surface's three backed widgets (InsightsBand); kills Present
 * mode, ROI tiles, the never-backed Policy-Compliance / Time-to-Resolution
 * tiles + trends, the duplicate KPI grid, and empty AI slots (kill list §7).
 *
 * Router-self-sufficient: no drilled callbacks — StatTile/EntityChip render
 * real anchors resolved through the system refs contract. Data comes from
 * useCommandCenter + useInsightsDashboard (both on useAtlasQuery; bounded
 * polling lives in the hooks, never here).
 */

function kpiByKey(kpis, key) {
  return (Array.isArray(kpis) ? kpis : []).find((item) => item?.key === key) || null;
}

export function HomePage() {
  const commandCenter = useCommandCenter();
  const insights = useInsightsDashboard();
  // Board-report generation is a network round-trip; guard against double-fire.
  const [boardReportBusy, setBoardReportBusy] = useState(false);
  // Stable reference so the useMemo derivations below only recompute when
  // the hook actually returns new data (react-hooks/exhaustive-deps).
  const commandCenterData = commandCenter.data;
  const data = useMemo(() => commandCenterData || {}, [commandCenterData]);

  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const previous = document.title;
    document.title = "Command Center - Governance Atlas";
    return () => {
      document.title = previous;
    };
  }, []);

  // Sample/prototype payloads are rejected before any value renders — the
  // Command Center never presents unverified numbers as evidence.
  const rejectedSamplePayload = commandCenter.hasLiveData
    ? isNonAuthoritativeMockEvidence(data, data.meta, commandCenter.warnings)
    : false;

  // Hydration honesty: a 200-with-still-warming envelope has no backed
  // values yet. Keep skeletons up rather than rendering definitive zeros
  // (COHESION law #3) — value-presence, not meta.state, decides.
  const loading =
    commandCenter.loading || (!commandCenter.error && !rejectedSamplePayload && !hasBackedSignal(data));

  const status = commandCenter.error
    ? { status: "error", reason: commandCenter.error, refresh: commandCenter.refresh }
    : loading
      ? { status: "loading" }
      : commandCenter.degraded
        ? {
            status: "degraded",
            warnings: commandCenter.warnings.length
              ? commandCenter.warnings
              : [commandCenter.refreshError].filter(Boolean),
            refresh: commandCenter.refresh,
          }
        : { status: "available" };

  const kpis = useMemo(
    () => ({
      governedAssets: kpiByKey(data.kpis, "governedAssets"),
      certifiedCriticalAssets: kpiByKey(data.kpis, "certifiedCriticalAssets"),
      metadataCoverage: kpiByKey(data.kpis, "metadataCoverage"),
      openStewardship: kpiByKey(data.kpis, "openStewardship"),
      policyExceptions: kpiByKey(data.kpis, "policyExceptions"),
      risk: riskSummary(data),
    }),
    [data],
  );

  const domains = useMemo(() => domainRows(data), [data]);
  const catalogs = useMemo(() => catalogRows(data), [data]);
  const cdes = useMemo(() => cdeRows(data), [data]);
  const requests = useMemo(() => requestRows(data), [data]);
  const events = useMemo(() => eventRows(data), [data]);
  const liveEvidence = !rejectedSamplePayload && hasBackedSignal(data);

  const refreshedLabel = (() => {
    const stamp = data.meta?.generatedAt || data.meta?.updatedAt || data.meta?.observedAt;
    if (!liveEvidence) return "";
    return stamp ? `Live · refreshed ${relativeTimeLabel(stamp)}` : "Live";
  })();

  const exportBrief = useCallback(() => {
    if (typeof document === "undefined" || typeof Blob === "undefined" || typeof URL?.createObjectURL !== "function") {
      toast("Export is unavailable in this browser context.", { tone: "warning" });
      return;
    }
    const brief = {
      exportedAt: new Date().toISOString(),
      workspace: data.meta?.workspace || data.estate?.workspace || null,
      liveEvidence,
      warnings: commandCenter.warnings,
      posture: {
        value: numericValue(data.posture?.overall),
        formula: data.posture?.formula || "",
        trendState: data.posture?.trendState || "",
        collectingSince: data.posture?.collectingSince || "",
      },
      kpis: (data.kpis || []).map((kpi) => ({
        key: kpi.key,
        label: kpi.label,
        value: kpi.value ?? null,
        state: kpi.state || (kpi.value === null || kpi.value === undefined ? "unavailable" : "available"),
        reason: kpi.reason || "",
      })),
      riskBreakdown: data.riskBreakdown || null,
      catalogHealth: catalogs,
      domains,
      recentActivity: events,
    };
    const blob = new Blob([JSON.stringify(brief, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `governance-atlas-command-center-${new Date().toISOString().slice(0, 10)}.json`;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    toast("Command Center brief export started.", { tone: "success" });
  }, [catalogs, commandCenter.warnings, data, domains, events, liveEvidence]);

  // G8 — board report: the backend renders print-ready HTML; we download it
  // as a Blob using the same anchor pattern as the brief export above.
  const exportBoardReport = useCallback(async () => {
    if (boardReportBusy) return;
    if (typeof document === "undefined" || typeof Blob === "undefined" || typeof URL?.createObjectURL !== "function") {
      toast("Export is unavailable in this browser context.", { tone: "warning" });
      return;
    }
    setBoardReportBusy(true);
    try {
      const html = await fetchBoardReportHtml();
      if (!html || typeof html !== "string") {
        throw new Error("Empty board report");
      }
      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atlas-board-report-${new Date().toISOString().slice(0, 10)}.html`;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      toast("Board report downloaded.", { tone: "success" });
    } catch (error) {
      toast(`Board report failed: ${error?.message || "unavailable"}`, { tone: "danger" });
    } finally {
      setBoardReportBusy(false);
    }
  }, [boardReportBusy]);

  return (
    <PageShell
      className="ga-home-page"
      eyebrow="Executive overview"
      title="Command Center"
      subtitle={
        liveEvidence
          ? "Backed values use live Unity Catalog and governance-store signals; unavailable values are labeled instead of inferred."
          : "Values appear as live evidence arrives; nothing is inferred while signals are unavailable."
      }
      status={status}
      actions={
        <div className="ga-home-actions">
          {refreshedLabel ? (
            <span className="ga-home-live" role="status">
              <span aria-hidden="true" />
              {refreshedLabel}
            </span>
          ) : null}
          <Button variant="secondary" size="sm" onClick={exportBrief}>
            Export brief
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={exportBoardReport}
            loading={boardReportBusy}
          >
            Board report
          </Button>
        </div>
      }
    >
      {rejectedSamplePayload ? (
        <UnavailableState
          title="Live evidence unavailable"
          reason="The metadata service returned sample data instead of live evidence. Values stay hidden until live evidence is returned."
          onRetry={commandCenter.refresh}
        />
      ) : loading && !commandCenter.error ? (
        <LoadingState variant="page" label="Loading the command center" />
      ) : commandCenter.error ? (
        // PageShell already rendered the error banner + retry; nothing below
        // pretends to be data.
        null
      ) : (
        <>
          <PostureHero data={data} kpis={kpis} loading={false} />
          <KpiRow kpis={kpis} />
          <div className="ga-home-grid">
            <TrendCard posture={data.posture || {}} />
            <CategoryTrendCard categoryTrends={data.categoryTrends} />
            <DomainPostureCard
              domains={domains}
              postureAvailable={numericValue(data.posture?.overall) !== null}
            />
            <RiskFindingsCard risk={kpis.risk} policyKpi={kpis.policyExceptions} />
            <CatalogHealthCard catalogs={catalogs} />
            <CdeCard cdes={cdes} liveEvidence={liveEvidence} />
            <RequestsCard
              requests={requests}
              openCount={numericValue(data.governance?.openRequests)}
            />
            <ActivityCard events={events} liveEvidence={liveEvidence && events.length > 0} />
          </div>
          <InsightsBand insights={insights} />
        </>
      )}
    </PageShell>
  );
}

export default HomePage;
