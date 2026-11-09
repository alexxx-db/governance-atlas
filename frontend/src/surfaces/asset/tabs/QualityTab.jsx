import "../asset.css";
import {
  Badge,
  DataTable,
  EntityChip,
  LoadingState,
  SectionCard,
  StatTile,
  UnavailableState,
} from "../../../components/system";
import { useAssetQuality } from "../../../hooks/useAssetQuality";
import { formatUtcInstant } from "../format";

/*
 * Quality tab — latest-run verdicts from the /360 composite (real ledger
 * join, Wave A4) plus per-check rows from the per-asset quality endpoint.
 * Each finding links to Evidence (?tab=quality&asset=…&run=…) per the
 * cross-linking LAW. Honest unavailability when no checks have ever run.
 */

const OUTCOME_TONES = { passed: "good", failed: "bad", errored: "warn", skipped: "muted" };

function LatestRunSummary({ quality }) {
  const run = quality?.latestRun || {};
  const outcomes = run.outcomes || {};
  const evidence = formatUtcInstant(quality?.evidenceAt);
  return (
    <>
      <div className="ax-asset-stat-row">
        <StatTile label="Passed" value={outcomes.passed ?? 0} tone="neutral" />
        <StatTile label="Failed" value={outcomes.failed ?? 0} tone={Number(outcomes.failed) > 0 ? "bad" : "neutral"} />
        <StatTile label="Errored" value={outcomes.errored ?? 0} tone={Number(outcomes.errored) > 0 ? "warn" : "neutral"} />
        <StatTile
          label="Checks evaluated"
          value={quality?.checksEvaluated ?? "—"}
          meta={run.runId ? `Latest run ${run.runId}` : ""}
        />
      </div>
      {evidence ? (
        <p className="ax-asset-evidence-line" title={evidence.iso}>
          Evidence from {evidence.display}
        </p>
      ) : null}
    </>
  );
}

export function QualityTab({ fqn, quality }) {
  // Per-check rows come from the dedicated per-asset endpoint; this hook is
  // mounted only while the tab is active, and its query is cached/bounded.
  const checks = useAssetQuality(fqn);
  const state = String(quality?.state || "").toLowerCase();

  const resultRows = checks.results || [];
  const checkColumns = [
    {
      key: "case",
      header: "Check",
      render: (row) => (
        <EntityChip
          appearance="inline"
          entity={{
            kind: "quality",
            fqn,
            run: row.run_id || undefined,
            label: String(row.case_id || row.result_id || "check"),
          }}
        />
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (row) => {
        const outcome = String(row.outcome || "").toLowerCase();
        return outcome ? <Badge tone={OUTCOME_TONES[outcome] || "neutral"}>{outcome}</Badge> : null;
      },
    },
    { key: "severity", header: "Severity", render: (row) => row.severity },
    {
      key: "metric",
      header: "Metric / threshold",
      align: "right",
      render: (row) =>
        row.metric_value != null && row.threshold_value != null
          ? `${row.metric_value} / ${row.threshold_value}`
          : row.metric_value != null
            ? String(row.metric_value)
            : null,
    },
    {
      key: "executed",
      header: "Executed (UTC)",
      render: (row) => {
        const at = formatUtcInstant(row.executed_at);
        return at ? <time dateTime={at.iso} title={at.iso}>{at.display}</time> : null;
      },
    },
    { key: "detail", header: "Detail", render: (row) => row.detail },
  ];

  return (
    <div className="ax-asset-tab-grid">
      <SectionCard title="Latest run">
        {!quality || state === "loading" ? (
          <LoadingState variant="card" lines={2} />
        ) : state === "available" ? (
          <LatestRunSummary quality={quality} />
        ) : (
          <UnavailableState
            title="No quality evidence"
            reason={quality?.message || "No quality checks have run for this asset."}
          />
        )}
      </SectionCard>

      <SectionCard
        title="Check results"
        subtitle="Individual check outcomes from the quality run ledger."
        actions={<EntityChip entity={{ kind: "quality", fqn, label: "Open in Evidence" }} />}
      >
        {checks.error && !resultRows.length ? (
          <UnavailableState title="Check results unavailable" reason={checks.error} onRetry={checks.refresh} />
        ) : (
          <DataTable
            columns={checkColumns}
            rows={resultRows}
            rowKey="result_id"
            loading={Boolean(checks.loading && !resultRows.length)}
            emptyMessage="No per-check results are recorded for this asset."
            caption="Quality check results"
          />
        )}
      </SectionCard>
    </div>
  );
}

export default QualityTab;
