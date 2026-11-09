import { useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  EntityChip,
  FilterBar,
  StatusBanner,
  TabStrip,
  UnavailableState,
} from "../../components/system";
import { auditRangeSinceIso } from "../../hooks/useAuditEvents";
import { EmetQualityBand } from "./emetQualityBand.jsx";
import { useAssetSuggestions } from "../../hooks/useAssetSuggestions";
import { useQualityFindings } from "../../hooks/useQualityFindings";
import {
  compactDateTime,
  displayLabel,
  outcomeTone,
  rangeNoun,
  severityTone,
  statusTone,
  tableTimestamp,
  text,
} from "./evidenceFormat.js";

/*
 * surfaces/evidence/QualityTab.jsx — the quality-findings half of the
 * unified Evidence surface (Wave C5, PRODUCT J6/J7: quality runs finally
 * get a browsable, filterable home). This is where Home's risk drills and
 * the Asset 360 Quality tab links land:
 *   /evidence?tab=quality&severity=high        (risk-breakdown drill)
 *   /evidence?tab=quality&asset=<fqn>[&run=]   (per-asset findings)
 *
 * Data: GET /api/quality/findings via useQualityFindings — visibility-scoped
 * by asset (not steward-gated), stable QF-<hex8> ids, joined run metadata,
 * counted visibility exclusions, UTC-Z evidence stamps.
 */

// "all" carries no `since` (auditRangeSinceIso returns "" → unbounded), so the
// lifetime severity counts on the Command Center risk card reconcile with what
// this tab shows when the risk drill lands here (the counts are all-time; a
// 30-day default window showed 0 findings under a "2 high" drill).
const RANGES = ["24h", "7d", "30d", "90d", "all"];
const SEVERITY_OPTIONS = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "informational", label: "Informational" },
];
const OUTCOME_OPTIONS = [
  // "failing" = failed OR errored — the population the Command Center risk tiles
  // count, so a severity drill (?outcome=failing) reconciles with the tile.
  { value: "failing", label: "Failed or errored" },
  { value: "failed", label: "Failed" },
  { value: "passed", label: "Passed" },
  { value: "errored", label: "Errored" },
  { value: "skipped", label: "Skipped" },
];
const FINDING_PARAM_KEYS = [
  "tab",
  "actor",
  "action",
  "asset",
  "q",
  "range",
  "kind",
  "severity",
  "outcome",
  "run",
];

function carriedParams(params) {
  const carried = {};
  for (const key of FINDING_PARAM_KEYS) {
    if (params[key]) carried[key] = params[key];
  }
  return carried;
}

function metricText(value) {
  return value == null ? "—" : Number(value).toLocaleString();
}

export function QualityTab({ params, setParams }) {
  const assetSuggestions = useAssetSuggestions();
  /* ------------------------------------------------------------ URL state */
  // Quality evidence accumulates slowly (runs since May); default to a 30-day
  // window so severity drill deep links land on real findings, and say so.
  const range = RANGES.includes(params.range) ? params.range : "30d";
  const severity = text(params.severity);
  const outcome = text(params.outcome);
  const assetFilter = text(params.asset);
  const runFilter = text(params.run);
  const findingParam = text(params.finding);

  // Asset filter drafts locally (a server round-trip per keystroke would
  // thrash the findings endpoint); Apply commits to the URL.
  const [assetDraft, setAssetDraft] = useState(assetFilter);

  /* ------------------------------------------------------------ data */
  const sinceIso = useMemo(() => auditRangeSinceIso(range), [range]);
  const findings = useQualityFindings({ asset: assetFilter, severity, outcome, since: sinceIso });

  const payload = findings.data && typeof findings.data === "object" ? findings.data : {};
  const allRows = useMemo(
    () => (Array.isArray(payload.findings) ? payload.findings : []),
    [payload.findings],
  );
  // ?run= narrows to a single quality run (Asset 360 "View findings in
  // Evidence" links carry it); the endpoint has no run param, so the slice is
  // client-side over the already-scoped payload and captioned honestly.
  const rows = useMemo(
    () => (runFilter ? allRows.filter((row) => text(row.runId) === runFilter) : allRows),
    [allRows, runFilter],
  );
  const summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};
  const outcomes = summary.outcomes && typeof summary.outcomes === "object" ? summary.outcomes : {};
  const visibilityScopedRowsExcluded = Number(payload.visibilityScopedRowsExcluded) || 0;
  const windowTruncated = payload.windowTruncated === true;
  const evidenceAt = text(summary.evidenceAt);
  const payloadState = text(payload.state).toLowerCase();
  const payloadReason = text(payload.reason);
  const loading = findings.status === "loading" || (findings.status === "hydrating" && !rows.length);

  /* ------------------------------------------------------------ selection */
  const selected = useMemo(() => {
    if (findingParam) return rows.find((row) => text(row.findingId) === findingParam) || null;
    return rows[0] || null;
  }, [findingParam, rows]);
  const findingParamUnresolved = Boolean(findingParam) && !selected && !loading;
  const selectedRun = selected?.run && typeof selected.run === "object" ? selected.run : null;

  // Deep-linked findings land where the run detail actually renders.
  const railRef = useRef(null);
  useEffect(() => {
    if (!findingParam || !selected || typeof window === "undefined") return;
    window.requestAnimationFrame(() => {
      const node = railRef.current;
      if (!node || typeof node.scrollIntoView !== "function") return;
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      node.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "nearest" });
    });
  }, [findingParam, selected]);

  /* ------------------------------------------------------------ columns */
  const columns = [
    {
      key: "findingId",
      header: "Finding",
      render: (row) => (
        // Stable QF-<hex8> derived from the result UUID — never positional
        // (same identity contract as AUD ids). The id text is the row anchor.
        <span
          className={`ax-evid-id${selected && text(selected.findingId) === text(row.findingId) ? " is-selected" : ""}`}
          title={text(row.resultId) || undefined}
        >
          {text(row.findingId) || "Unavailable"}
        </span>
      ),
    },
    {
      key: "checkName",
      header: "Check",
      render: (row) => (
        <span className="ax-evid-check-cell">
          <span>{text(row.checkName) || "Unnamed check"}</span>
          {/* Honesty marker from the payload: "case-id" names are derived
              from the id slug, not a curated definition. */}
          {text(row.checkNameSource) === "case-id" ? <small>name derived from case id</small> : null}
        </span>
      ),
    },
    {
      key: "asset",
      header: "Asset",
      render: (row) =>
        text(row.assetFqn) ? (
          <EntityChip appearance="inline" entity={{ kind: "asset", fqn: row.assetFqn }} />
        ) : (
          "—"
        ),
    },
    {
      key: "severity",
      header: "Severity",
      render: (row) => (
        <Badge size="sm" tone={severityTone(row.severityLevel)}>
          {displayLabel(row.severityLevel, "Unrated")}
        </Badge>
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (row) => (
        <Badge size="sm" tone={outcomeTone(row.outcome)}>
          {displayLabel(row.outcome, "Unknown")}
        </Badge>
      ),
    },
    {
      key: "executedAt",
      header: "Executed (UTC)",
      render: (row) => <span className="ax-evid-time">{tableTimestamp(row.executedAt)}</span>,
    },
    {
      key: "message",
      header: "Message",
      render: (row) =>
        text(row.message) ? (
          <small className="ax-evid-ref" title={row.message}>
            {row.message}
          </small>
        ) : (
          // Empty stays empty server-side; the honest fallback is ours.
          <small className="ax-evid-ref is-muted">No evaluator message recorded</small>
        ),
    },
  ];

  /* ------------------------------------------------------------ captions */
  const totalFiltered = Number(summary.total);
  const captionParts = [
    rows.length
      ? runFilter
        ? `Showing ${rows.length} finding${rows.length === 1 ? "" : "s"} from run ${runFilter}`
        : `Showing ${rows.length}${Number.isFinite(totalFiltered) && totalFiltered > rows.length ? ` of ${totalFiltered.toLocaleString()}` : ""} finding${rows.length === 1 ? "" : "s"} ${range === "all" ? "across all recorded runs" : `in the last ${rangeNoun(range)}`}`
      : "",
    visibilityScopedRowsExcluded
      ? `${visibilityScopedRowsExcluded} finding${visibilityScopedRowsExcluded === 1 ? "" : "s"} about assets outside your visibility scope withheld`
      : "",
    evidenceAt ? `Latest evidence ${compactDateTime(evidenceAt)}` : "",
  ].filter(Boolean);

  const filtersActive = Boolean(severity || outcome || assetFilter || runFilter);

  /* ------------------------------------------------------------ empty/error */
  const unavailableNoRows = !loading && payloadState === "unavailable" && !rows.length;
  const noFindingsMatch = unavailableNoRows && /no quality findings match/i.test(payloadReason);
  const noRunsYet = unavailableNoRows && /no quality checks have run yet/i.test(payloadReason);
  const runFilterEmpty = !loading && Boolean(runFilter) && allRows.length > 0 && !rows.length;

  if (findings.status === "error") {
    return (
      <UnavailableState
        className="ax-evid-gate"
        title="Quality findings unavailable"
        reason={findings.errorMessage || "The quality findings feed could not be loaded."}
        onRetry={findings.refresh}
      />
    );
  }

  /* ------------------------------------------------------------ render */
  return (
    <div className="ax-evid-quality">
      <EmetQualityBand />
      {findings.status === "degraded" ? (
        <StatusBanner
          tone="warning"
          title="Quality evidence availability is limited"
          warnings={findings.warnings}
          onRetry={findings.refresh}
        />
      ) : null}

      <div className="ax-evid-toolbar">
        <TabStrip
          ariaLabel="Evidence window"
          className="ax-evid-range"
          param={{ value: range, set: (key) => setParams({ range: key === "30d" ? "" : key }) }}
          tabs={RANGES.map((key) => ({ key, label: key === "all" ? "All time" : `Last ${key}` }))}
        />
        <div className="ax-evid-outcome-tally" role="status">
          {loading
            ? "Reading quality run results…"
            : `Window outcomes · ${metricText(outcomes.failed)} failed · ${metricText(outcomes.passed)} passed · ${metricText(outcomes.errored)} errored · ${metricText(outcomes.skipped)} skipped`}
        </div>
      </div>

      <div className="ax-evid-filter-row">
        <FilterBar
          facets={[
            { key: "severity", label: "Severity", type: "select", options: SEVERITY_OPTIONS },
            { key: "outcome", label: "Outcome", type: "select", options: OUTCOME_OPTIONS },
            { key: "asset", label: "Asset", type: "search", placeholder: "catalog.schema.table", suggestions: assetSuggestions.fqns },
          ]}
          label="Quality finding filters"
          onChange={(next) => {
            // Selects commit immediately (discrete, server-side filters);
            // the asset text facet drafts until Apply.
            setAssetDraft(next.asset || "");
            const patch = {};
            if ((next.severity || "") !== severity) patch.severity = next.severity || "";
            if ((next.outcome || "") !== outcome) patch.outcome = next.outcome || "";
            if (Object.keys(patch).length) setParams(patch);
          }}
          onClear={() => {
            setAssetDraft("");
            setParams({ severity: "", outcome: "", asset: "", run: "", finding: "" });
          }}
          value={{
            ...(severity ? { severity } : {}),
            ...(outcome ? { outcome } : {}),
            ...(assetDraft ? { asset: assetDraft } : {}),
          }}
        />
        <Button
          disabled={assetDraft.trim() === assetFilter}
          onClick={() => setParams({ asset: assetDraft.trim(), finding: "" })}
          title={assetDraft.trim() === assetFilter ? "Asset filter already applied." : "Apply the asset filter."}
          variant="secondary"
        >
          Apply asset filter
        </Button>
      </div>
      {runFilter ? (
        <p className="ax-evid-filter-note" role="status">
          {`Run filter active · showing findings recorded by quality run ${runFilter}.`}
          <Button onClick={() => setParams({ run: "", finding: "" })} size="sm" variant="tertiary">
            Clear run filter
          </Button>
        </p>
      ) : null}

      <div className="ax-evid-layout">
        <div className="ax-evid-main">
          {noFindingsMatch || runFilterEmpty ? (
            <EmptyState
              title="No quality findings in range"
              body={
                runFilterEmpty
                  ? `Run ${runFilter} recorded no findings inside the current filters. Clear the run filter to see the full window.`
                  : `${payloadReason} Window: ${range === "all" ? "all recorded runs" : `last ${rangeNoun(range)}`}${filtersActive ? ", with filters applied" : ""}.`
              }
              action={
                // Ladder out to the widest window so a drill that promised
                // findings can always reach them: 30d/24h/7d → 90d → All time.
                range === "all" ? null : (
                  <Button
                    onClick={() => setParams({ range: range === "90d" ? "all" : "90d" })}
                    variant="secondary"
                  >
                    {range === "90d" ? "Widen to all time" : "Widen to 90 days"}
                  </Button>
                )
              }
            />
          ) : noRunsYet ? (
            <EmptyState
              title="No quality checks have run yet"
              body={payloadReason}
            />
          ) : unavailableNoRows ? (
            <UnavailableState
              title="Quality findings unavailable"
              reason={payloadReason || "The quality run ledger is unavailable for the current visibility scope."}
              onRetry={findings.refresh}
            />
          ) : (
            <>
              <DataTable
                caption="Quality findings"
                columns={columns}
                density="compact"
                emptyMessage="No quality findings in range."
                loading={loading}
                rowKey="findingId"
                rows={rows}
                rowTarget={(row) =>
                  text(row.findingId)
                    ? { surface: "evidence", params: { ...carriedParams(params), finding: row.findingId } }
                    : null
                }
              />
              {windowTruncated ? (
                <p className="ax-evid-caption is-truncation" role="status">
                  The quality run ledger returned its maximum window — older in-range findings may exist. Narrow the
                  filters for complete evidence.
                </p>
              ) : null}
              {captionParts.length ? (
                <div className="ax-evid-caption-row">
                  <p className="ax-evid-caption">{captionParts.join(" · ")}</p>
                </div>
              ) : null}
            </>
          )}
          <p className="ax-evid-provenance">
            Quality findings are read from the same quality_run_results ledger scoring the Command Center risk tiles —
            visibility-scoped to your estate, one number per concept.
          </p>
        </div>

        <aside aria-label="Quality run detail" className="ax-evid-rail" ref={railRef}>
          {findingParamUnresolved ? (
            <UnavailableState
              title="Finding not found"
              reason={`${findingParam} is not in the current filtered view. It may be outside the ${rangeNoun(range)} window or your visibility scope.`}
            />
          ) : selected ? (
            <div className="ax-evid-detail">
              <header className="ax-evid-detail-head">
                <div>
                  <span className="ax-sys-eyebrow">Selected finding</span>
                  <h3>{text(selected.checkName) || "Unnamed check"}</h3>
                </div>
                <Badge tone={outcomeTone(selected.outcome)}>{displayLabel(selected.outcome, "Unknown")}</Badge>
              </header>
              <dl className="ax-evid-detail-list">
                <div>
                  <dt>Finding ID</dt>
                  {/* Stable QF-<hex8>; full result UUID on the title attribute. */}
                  <dd title={text(selected.resultId) || undefined}>{text(selected.findingId) || "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Asset</dt>
                  <dd>
                    {text(selected.assetFqn) ? (
                      <EntityChip appearance="inline" entity={{ kind: "asset", fqn: selected.assetFqn }} />
                    ) : (
                      "Unavailable"
                    )}
                  </dd>
                </div>
                {text(selected.columnName) ? (
                  <div>
                    <dt>Column</dt>
                    <dd>
                      <EntityChip
                        appearance="inline"
                        entity={{ kind: "column", fqn: selected.assetFqn, column: selected.columnName }}
                      />
                    </dd>
                  </div>
                ) : null}
                <div>
                  <dt>Severity</dt>
                  <dd>
                    <Badge size="sm" tone={severityTone(selected.severityLevel)}>
                      {displayLabel(selected.severityLevel, "Unrated")}
                    </Badge>
                    {text(selected.severity) && text(selected.severity) !== text(selected.severityLevel) ? (
                      <small className="ax-evid-detail-sub">{`recorded as "${selected.severity}"`}</small>
                    ) : null}
                  </dd>
                </div>
                <div>
                  <dt>Executed (UTC)</dt>
                  <dd>{compactDateTime(selected.executedAt)}</dd>
                </div>
                <div>
                  <dt>Metric / threshold</dt>
                  {/* "—" for genuinely-absent numbers, never a fabricated 0. */}
                  <dd>{`${selected.metricValue == null ? "—" : selected.metricValue} / ${selected.thresholdValue == null ? "—" : selected.thresholdValue}`}</dd>
                </div>
                <div>
                  <dt>Message</dt>
                  <dd>{text(selected.message) || "No evaluator message recorded"}</dd>
                </div>
              </dl>
              <div className="ax-evid-run-block">
                <h4>Quality run</h4>
                {selectedRun ? (
                  <dl className="ax-evid-detail-list">
                    <div>
                      <dt>Run</dt>
                      <dd className="ax-evid-run-actions">
                        <span title={text(selectedRun.runId) || undefined}>{text(selectedRun.runId) || "Unavailable"}</span>
                        {text(selectedRun.runId) && runFilter !== text(selectedRun.runId) ? (
                          <Button
                            onClick={() => setParams({ run: text(selectedRun.runId) })}
                            size="sm"
                            variant="tertiary"
                          >
                            Filter to this run
                          </Button>
                        ) : null}
                      </dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>
                        <Badge size="sm" tone={statusTone(selectedRun.status)}>
                          {displayLabel(selectedRun.status, "Unknown")}
                        </Badge>
                      </dd>
                    </div>
                    <div>
                      <dt>Trigger</dt>
                      <dd>{displayLabel(selectedRun.trigger, "Unavailable")}</dd>
                    </div>
                    <div>
                      <dt>Started (UTC)</dt>
                      <dd>{compactDateTime(selectedRun.startedAt)}</dd>
                    </div>
                    <div>
                      <dt>Finished (UTC)</dt>
                      <dd>{compactDateTime(selectedRun.finishedAt)}</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="ax-evid-diff-empty">
                    Run metadata was not reported for this finding{text(selected.runId) ? ` (run ${selected.runId})` : ""}.
                  </p>
                )}
              </div>
            </div>
          ) : loading ? (
            <EmptyState title="Loading quality findings" body="Reading the quality run ledger." />
          ) : (
            <EmptyState title="No finding selected" body="Select a finding to inspect its run evidence." />
          )}
        </aside>
      </div>
    </div>
  );
}

export default QualityTab;
