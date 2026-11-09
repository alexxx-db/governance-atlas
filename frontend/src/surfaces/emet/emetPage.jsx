/*
 * surfaces/emet/emetPage.jsx — the emet Control Center.
 *
 * A command center over the sibling emet validation product's control
 * plane (detected live on the workspace). One surface, four URL-addressed tabs:
 *   ?tab=overview (default) — portfolio trust rollup + fix-first + jobs
 *   ?tab=jobs               — every active job, trigger a run, monitor it live
 *   ?tab=ask                — the emet Signal Room (Genie) conversation
 *   ?tab=dashboard          — the embedded AI/BI trust dashboard
 * ?run=<runId> opens the run-detail drawer from any tab.
 *
 * Router-self-sufficient: reads params via useSurfaceParams, detects emet
 * via its own OBO endpoints. Only shell identity (steward gate for triggering)
 * and the workspace host (dashboard iframe) are threaded in.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  Badge,
  Button,
  Drawer,
  EmptyState,
  PageShell,
  SectionCard,
  StatTile,
  TabStrip,
  toast,
} from "../../components/system";
import {
  fetchemetRun,
  fetchemetRunLive,
  pollemetGenie,
  startemetGenie,
  triggeremetRun,
} from "../../lib/api";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { useEmetOverview, useEmetStatus } from "../../hooks/useemet";
import "./emet.css";

const PARAMS_SCHEMA = {
  tab: { type: "string" },
  run: { type: "string" },
  job: { type: "string" },
};

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "jobs", label: "Jobs & runs" },
  { key: "ask", label: "Ask emet" },
  { key: "dashboard", label: "Dashboard" },
];

const TRIGGER_ROLES = new Set(["steward", "admin"]);

/* ── formatting helpers ─────────────────────────────────────────────── */

function num(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatInt(value) {
  const n = num(value);
  return n === null ? "—" : n.toLocaleString();
}

function formatPct(value) {
  const n = num(value);
  return n === null ? "—" : `${n.toFixed(n % 1 === 0 ? 0 : 1)}%`;
}

function formatUsd(value) {
  const n = num(value);
  if (n === null) return "—";
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

// Badge/text tone vocabulary: good | info | warn | bad | neutral.
function trustTone(score) {
  const n = num(score);
  if (n === null) return "neutral";
  if (n >= 90) return "good";
  if (n >= 75) return "info";
  if (n >= 50) return "warn";
  return "bad";
}

// StatTile only styles tone-danger / tone-warning (else neutral).
function tileTone(score) {
  const n = num(score);
  if (n === null) return "neutral";
  if (n < 50) return "danger";
  if (n < 75) return "warning";
  return "neutral";
}

function deltaTone(delta) {
  const n = num(delta);
  if (n === null || n === 0) return "neutral";
  return n > 0 ? "good" : "bad";
}

function relTime(value) {
  if (!value) return "";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return String(value);
  const diffMs = Date.now() - parsed;
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function absoluteUrl(host, path) {
  const h = String(host || "").replace(/\/$/, "");
  const p = String(path || "");
  if (!p) return "";
  if (/^https?:\/\//.test(p)) return p;
  if (!h) return "";
  return `${h}${p.startsWith("/") ? p : `/${p}`}`;
}

/* ── health band ────────────────────────────────────────────────────── */

const HEALTH_BADGE = {
  available: { status: "available", label: "Connected" },
  degraded: { status: "degraded", label: "Degraded" },
  unavailable: { status: "unavailable", label: "Unavailable" },
  absent: { status: "unavailable", label: "Not detected" },
  disabled: { status: "unavailable", label: "Disabled" },
  unknown: { status: "loading", label: "Detecting…" },
};

function HealthBand({ status, host, onRefresh, refreshing }) {
  const state = String(status?.state || "unknown").toLowerCase();
  const badge = HEALTH_BADGE[state] || HEALTH_BADGE.unknown;
  const dashboardUrl = absoluteUrl(host, status?.dashboardUrl);
  const genieUrl = absoluteUrl(host, status?.genieUrl);
  return (
    <div className="ax-dp-health" data-state={state}>
      <div className="ax-dp-health-lead">
        <Badge status={badge.status}>{badge.label}</Badge>
        <div className="ax-dp-health-copy">
          <strong>emet{status?.version ? ` v${status.version}` : ""}</strong>
          <span>{status?.message || "Detecting the emet control plane…"}</span>
        </div>
      </div>
      <dl className="ax-dp-health-facts">
        {status?.catalog ? (
          <div>
            <dt>Control plane</dt>
            <dd>{status.catalog}.{status.schema || "emet"}</dd>
          </div>
        ) : null}
        {num(status?.activeJobCount) !== null ? (
          <div>
            <dt>Active jobs</dt>
            <dd>{formatInt(status.activeJobCount)}</dd>
          </div>
        ) : null}
        {status?.latestSnapshotAt ? (
          <div>
            <dt>Latest run</dt>
            <dd>{relTime(status.latestSnapshotAt)}</dd>
          </div>
        ) : null}
      </dl>
      <div className="ax-dp-health-actions">
        {dashboardUrl ? (
          <a className="ax-dp-link" href={dashboardUrl} target="_blank" rel="noreferrer">Dashboard ↗</a>
        ) : null}
        {genieUrl && status?.genieReady ? (
          <a className="ax-dp-link" href={genieUrl} target="_blank" rel="noreferrer">Signal Room ↗</a>
        ) : null}
        <Button size="sm" variant="tertiary" loading={refreshing} onClick={onRefresh}>Refresh</Button>
      </div>
    </div>
  );
}

/* ── rollup tiles ───────────────────────────────────────────────────── */

function RollupTiles({ rollup }) {
  if (!rollup) return null;
  const tiles = [
    {
      key: "trust",
      label: "Portfolio trust score",
      value: num(rollup.trustScore) === null ? "—" : `${rollup.trustScore.toFixed(1)}`,
      tone: tileTone(rollup.trustScore),
      hint: "Priority-weighted pass rate across every active job's latest run (CRITICAL failures weigh heaviest). 0–100.",
      variant: "donut",
      percent: num(rollup.trustScore) ?? undefined,
    },
    {
      key: "jobs",
      label: "Active jobs",
      value: formatInt(rollup.jobCount),
      meta: `${formatInt(rollup.jobsWithRuns)} with runs`,
      hint: "Validation suites currently installed and active in this emet workspace.",
    },
    {
      key: "failing",
      label: "Jobs failing",
      value: formatInt(rollup.failingJobCount),
      tone: num(rollup.failingJobCount) > 0 ? "danger" : "neutral",
      hint: "Active jobs whose latest run has at least one failed validation.",
    },
    {
      key: "cutover",
      label: "Cutover blockers",
      value: formatInt(rollup.cutoverBlockers),
      tone: num(rollup.cutoverBlockers) > 0 ? "danger" : "neutral",
      hint: "CRITICAL-priority validations that failed — emet recommends NOT promoting these runs.",
    },
    {
      key: "potential",
      label: "Potential impact",
      value: formatUsd(rollup.potentialImpactUsd),
      hint: "Modeled financial exposure across failing validations in the latest runs.",
    },
    {
      key: "realized",
      label: "Realized impact",
      value: formatUsd(rollup.realizedImpactUsd),
      tone: num(rollup.realizedImpactUsd) > 0 ? "warning" : "neutral",
      hint: "Modeled exposure on validations that actually failed in the latest runs.",
    },
  ];
  return (
    <section className="ax-dp-rollup" aria-label="emet portfolio summary">
      {tiles.map((tile) => (
        <StatTile
          key={tile.key}
          label={tile.label}
          value={tile.value}
          tone={tile.tone || "neutral"}
          hint={tile.hint}
          meta={tile.meta || ""}
          variant={tile.variant || "metric"}
          percent={tile.percent}
          className="ax-dp-tile"
        />
      ))}
    </section>
  );
}

/* ── fix-first ──────────────────────────────────────────────────────── */

function FixFirst({ items, onOpenRun }) {
  if (!items.length) {
    return (
      <EmptyState
        title="Nothing to fix first"
        body="No failing validations are queued for remediation across the active jobs. Trust is holding."
      />
    );
  }
  return (
    <ol className="ax-dp-fixfirst">
      {items.map((item) => (
        <li key={`${item.runId}:${item.taskKey}`} className="ax-dp-fixfirst-row">
          <span className="ax-dp-rank">{item.fixFirstRank ?? "•"}</span>
          <div className="ax-dp-fixfirst-body">
            <div className="ax-dp-fixfirst-title">
              <button type="button" className="ax-dp-linkbtn" onClick={() => onOpenRun(item.runId)}>
                {item.taskKey}
              </button>
              {item.cutoverBlocker ? <Badge status="unavailable">Cutover blocker</Badge> : null}
              {item.businessPriority ? <Badge tone={item.businessPriority === "CRITICAL" ? "bad" : "warn"}>{item.businessPriority}</Badge> : null}
            </div>
            <div className="ax-dp-fixfirst-meta">
              <span>{item.jobName}</span>
              {item.primaryFailureMode ? <span>· {item.primaryFailureMode}</span> : null}
              {num(item.failedCheckCount) ? <span>· {item.failedCheckCount} failed checks</span> : null}
              {num(item.failureStreak) ? <span>· streak {item.failureStreak}</span> : null}
              {num(item.realizedImpactUsd) ? <span>· {formatUsd(item.realizedImpactUsd)} at risk</span> : null}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

/* ── jobs table ─────────────────────────────────────────────────────── */

function JobRow({ job, canTrigger, onTrigger, onOpenRun, triggeringId, host }) {
  const [confirming, setConfirming] = useState(false);
  const isTriggering = triggeringId === job.executionJobId;
  const trust = num(job.trustScore);
  return (
    <tr>
      <td className="ax-dp-cell-job">
        <strong>{job.jobName}</strong>
        {job.lastRunId ? <span className="ax-dp-subtle">run {job.lastRunId}</span> : <span className="ax-dp-subtle">never run</span>}
      </td>
      <td>
        {trust === null ? (
          <span className="ax-dp-subtle">—</span>
        ) : (
          <span className="ax-dp-trust">
            <Badge tone={trustTone(trust)}>{trust.toFixed(0)}</Badge>
            {num(job.trustScoreDelta) ? (
              <span className={`ax-dp-delta tone-${deltaTone(job.trustScoreDelta)}`}>
                {job.trustScoreDelta > 0 ? "▲" : "▼"}{Math.abs(job.trustScoreDelta).toFixed(1)}
              </span>
            ) : null}
          </span>
        )}
      </td>
      <td>
        {job.hasRun ? (
          <span className={num(job.failedValidations) > 0 ? "ax-dp-fail" : "ax-dp-pass"}>
            {formatInt(job.successfulValidations)}/{formatInt(job.totalValidations)}
          </span>
        ) : <span className="ax-dp-subtle">—</span>}
      </td>
      <td>{num(job.criticalFailures) > 0 ? <Badge tone="bad">{job.criticalFailures}</Badge> : <span className="ax-dp-subtle">0</span>}</td>
      <td>{num(job.cutoverBlockers) > 0 ? <Badge status="unavailable">{job.cutoverBlockers}</Badge> : <span className="ax-dp-subtle">0</span>}</td>
      <td>{formatUsd(job.realizedImpactUsd)}</td>
      <td className="ax-dp-cell-actions">
        {job.runId ? (
          <button type="button" className="ax-dp-linkbtn" onClick={() => onOpenRun(job.runId)}>View</button>
        ) : null}
        {host && job.executionJobId ? (
          <a
            className="ax-dp-linkbtn"
            href={`${host}/jobs/${job.executionJobId}`}
            target="_blank"
            rel="noreferrer"
            title="Open this job in Databricks"
          >
            Job ↗
          </a>
        ) : null}
        {confirming ? (
          <span className="ax-dp-confirm">
            <Button size="sm" variant="primary" tone="warning" loading={isTriggering}
              onClick={() => { onTrigger(job); setConfirming(false); }}>
              Confirm
            </Button>
            <Button size="sm" variant="tertiary" onClick={() => setConfirming(false)}>Cancel</Button>
          </span>
        ) : (
          <Button size="sm" variant="secondary" disabled={!canTrigger || !job.executionJobId}
            title={canTrigger ? "Trigger a validation run" : "Requires steward or admin permissions"}
            onClick={() => setConfirming(true)}>
            Run now
          </Button>
        )}
      </td>
    </tr>
  );
}

function JobsTable({ jobs, canTrigger, onTrigger, onOpenRun, triggeringId, host }) {
  if (!jobs.length) {
    return <EmptyState title="No active validation jobs" body="emet is installed but no active jobs were found in the registry." />;
  }
  return (
    <div className="ax-dp-table-scroll">
      <table className="ax-dp-table">
        <thead>
          <tr>
            <th>Job</th><th>Trust</th><th>Validations</th><th>Critical</th><th>Cutover</th><th>At risk</th><th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <JobRow key={job.normalizedJobName || job.jobName} job={job} host={host}
              canTrigger={canTrigger} onTrigger={onTrigger} onOpenRun={onOpenRun} triggeringId={triggeringId} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── live run monitor (post-trigger) ────────────────────────────────── */

function LiveRunMonitor({ liveRun, host, onDone, onClose }) {
  const [live, setLive] = useState(null);
  const doneRef = useRef(false);

  useEffect(() => {
    if (!liveRun?.runId) return undefined;
    let cancelled = false;
    let timer = null;
    doneRef.current = false;
    const tick = async () => {
      try {
        const res = await fetchemetRunLive(liveRun.runId);
        if (cancelled) return;
        setLive(res);
        const status = String(res?.effectiveStatus || "").toLowerCase();
        if (status === "running") {
          timer = setTimeout(tick, 4000);
        } else if (!doneRef.current) {
          doneRef.current = true;
          onDone?.(status);
        }
      } catch {
        if (!cancelled) timer = setTimeout(tick, 6000);
      }
    };
    tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [liveRun?.runId, onDone]);

  if (!liveRun?.runId) return null;
  const status = String(live?.effectiveStatus || "running").toLowerCase();
  const badge = status === "success" ? "available" : status === "failed" ? "unavailable" : "loading";
  const runUrl = absoluteUrl(host, live?.runPageUrl || liveRun.runPageUrl);
  return (
    <div className="ax-dp-liverun" data-status={status}>
      <Badge status={badge}>{status === "running" ? "Running" : status === "success" ? "Succeeded" : status === "failed" ? "Failed" : "Working"}</Badge>
      <span className="ax-dp-liverun-copy">
        <strong>{liveRun.jobName}</strong> — {live?.stateMessage || (status === "running" ? "Validation run in progress…" : `Run ${liveRun.runId}`)}
      </span>
      {runUrl ? <a className="ax-dp-link" href={runUrl} target="_blank" rel="noreferrer">Open run ↗</a> : null}
      <Button size="sm" variant="tertiary" onClick={onClose}>Dismiss</Button>
    </div>
  );
}

/* ── run detail drawer ──────────────────────────────────────────────── */

function RunDrawer({ runId, open, onClose, host }) {
  const [state, setState] = useState({ loading: false, detail: null, error: "" });

  useEffect(() => {
    if (!open || !runId) return undefined;
    let cancelled = false;
    setState({ loading: true, detail: null, error: "" });
    fetchemetRun(runId)
      .then((res) => { if (!cancelled) setState({ loading: false, detail: res, error: "" }); })
      .catch((err) => { if (!cancelled) setState({ loading: false, detail: null, error: err?.message || "Run detail unavailable." }); });
    return () => { cancelled = true; };
  }, [open, runId]);

  const detail = state.detail;
  const header = detail?.header || {};
  const validations = Array.isArray(detail?.validations) ? detail.validations : [];
  const checks = Array.isArray(detail?.checks) ? detail.checks : [];
  const domains = Array.isArray(detail?.domains) ? detail.domains : [];

  return (
    <Drawer open={open} onClose={onClose} title={header.jobName ? `${header.jobName} · run ${runId}` : `Run ${runId}`} width={640}>
      {state.loading ? <p className="ax-dp-subtle">Loading run evidence…</p> : null}
      {state.error ? <p className="ax-dp-fail">{state.error}</p> : null}
      {detail ? (
        <div className="ax-dp-run">
          {host && header.jobId ? (
            <div className="ax-dp-run-links">
              <a className="ax-dp-link" href={`${host}/jobs/${header.jobId}`} target="_blank" rel="noreferrer">Open job in Databricks ↗</a>
            </div>
          ) : null}
          <div className="ax-dp-run-kpis">
            <div><span>Trust</span><strong className={`tone-${trustTone(header.trustScore)}`}>{num(header.trustScore) === null ? "—" : header.trustScore.toFixed(1)}</strong></div>
            <div><span>Validations</span><strong>{formatInt(header.successfulValidations)}/{formatInt(header.totalValidations)}</strong></div>
            <div><span>Critical</span><strong>{formatInt(header.criticalFailures)}</strong></div>
            <div><span>At risk</span><strong>{formatUsd(header.realizedImpactUsd)}</strong></div>
          </div>

          {domains.length ? (
            <section className="ax-dp-run-section">
              <h4>By domain</h4>
              <ul className="ax-dp-domains">
                {domains.map((dom) => (
                  <li key={dom.businessDomain}>
                    <span>{dom.businessDomain || "—"}</span>
                    <span className={num(dom.failedValidations) > 0 ? "ax-dp-fail" : "ax-dp-pass"}>
                      {formatPct(dom.successRatePercent)} · {formatInt(dom.failedValidations)} failed
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="ax-dp-run-section">
            <h4>Validations ({validations.length})</h4>
            <div className="ax-dp-table-scroll">
              <table className="ax-dp-table ax-dp-table-compact">
                <thead><tr><th>Task</th><th>Status</th><th>Priority</th><th>Failure mode</th><th>Checks</th></tr></thead>
                <tbody>
                  {validations.map((v) => (
                    <tr key={v.taskKey}>
                      <td className="ax-dp-cell-job"><strong>{v.taskKey}</strong>{v.targetTable ? <span className="ax-dp-subtle">{v.targetTable}</span> : null}</td>
                      <td><Badge tone={v.status === "SUCCESS" ? "good" : "bad"}>{v.status === "SUCCESS" ? "Pass" : "Fail"}</Badge></td>
                      <td>{v.businessPriority || "—"}{v.cutoverBlocker ? " ⛔" : ""}</td>
                      <td>{v.primaryFailureMode || (v.status === "SUCCESS" ? "—" : "Failed")}</td>
                      <td>{num(v.failedCheckCount) ? <span className="ax-dp-fail">{v.failedCheckCount}</span> : <span className="ax-dp-pass">0</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="ax-dp-run-section">
            <h4>Checks ({checks.length})</h4>
            <ul className="ax-dp-checks">
              {checks.slice(0, 60).map((c, i) => (
                <li key={`${c.taskKey}:${c.checkCategory}:${c.checkName}:${i}`} data-status={c.status}>
                  <Badge tone={c.status === "PASS" ? "good" : c.status === "FAIL" ? "bad" : "neutral"}>{c.status}</Badge>
                  <span className="ax-dp-check-name">{c.checkCategory} · {c.checkName}</span>
                  {c.details ? <span className="ax-dp-subtle">{c.details}</span> : null}
                </li>
              ))}
            </ul>
            {checks.length > 60 ? <p className="ax-dp-subtle">Showing the first 60 of {checks.length} checks.</p> : null}
          </section>
        </div>
      ) : null}
    </Drawer>
  );
}

/* ── ask (Signal Room / Genie) ──────────────────────────────────────── */

const GENIE_STARTERS = [
  "Which jobs have the lowest trust scores right now?",
  "What are the top cutover blockers across the portfolio?",
  "Which validations regressed since their previous run?",
  "What is the total realized financial impact of failing validations?",
];

function AskPanel({ detected }) {
  const [question, setQuestion] = useState("");
  const [convo, setConvo] = useState(null); // {conversationId, messageId}
  const [stage, setStage] = useState("");
  const [answer, setAnswer] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cancelRef = useRef(false);

  useEffect(() => () => { cancelRef.current = true; }, []);

  const ask = useCallback(async (text) => {
    const q = String(text || "").trim();
    if (!q || busy) return;
    setBusy(true); setError(""); setAnswer(null); setStage("Starting…");
    cancelRef.current = false;
    try {
      const started = await startemetGenie(q);
      const conversationId = started?.conversationId;
      const messageId = started?.messageId;
      if (!conversationId || !messageId) throw new Error("The Signal Room did not start a conversation.");
      setConvo({ conversationId, messageId });
      setStage(started?.stage || "Working…");
      // poll
      for (let attempt = 0; attempt < 45 && !cancelRef.current; attempt += 1) {
        await new Promise((r) => setTimeout(r, 2500));
        if (cancelRef.current) return;
        const res = await pollemetGenie(conversationId, messageId);
        setStage(res?.stage || "Working…");
        if (res?.done) {
          setAnswer(res?.payload || { answer: "The Signal Room returned no answer." });
          setBusy(false);
          return;
        }
      }
      if (!cancelRef.current) { setError("The Signal Room took too long to respond."); setBusy(false); }
    } catch (err) {
      if (!cancelRef.current) { setError(err?.message || "The Signal Room is unavailable."); setBusy(false); }
    }
  }, [busy]);

  if (!detected) {
    return <EmptyState title="Signal Room unavailable" body="emet must be detected on this workspace before you can ask its Genie Signal Room." />;
  }

  const answerText = answer?.answer || answer?.text || "";
  const table = Array.isArray(answer?.table?.rows) ? answer.table : (Array.isArray(answer?.rows) ? { rows: answer.rows, columns: answer.columns } : null);

  return (
    <div className="ax-dp-ask">
      <p className="ax-dp-subtle">Ask the emet Signal Room about validation trust, failures, and remediation. Grounded on the governed semantic layer.</p>
      <div className="ax-dp-ask-starters">
        {GENIE_STARTERS.map((s) => (
          <button key={s} type="button" className="ax-dp-chip" disabled={busy} onClick={() => { setQuestion(s); ask(s); }}>{s}</button>
        ))}
      </div>
      <form className="ax-dp-ask-form" onSubmit={(e) => { e.preventDefault(); ask(question); }}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about trust, failures, or impact…" aria-label="Ask the emet Signal Room" />
        <Button type="submit" variant="primary" loading={busy} disabled={!question.trim()}>Ask</Button>
      </form>
      {busy ? <p className="ax-dp-subtle" aria-live="polite">{stage || "Working…"}</p> : null}
      {error ? <p className="ax-dp-fail">{error}</p> : null}
      {answerText ? (
        <div className="ax-dp-answer">
          <p>{answerText}</p>
          {table && table.rows?.length ? (
            <div className="ax-dp-table-scroll">
              <table className="ax-dp-table ax-dp-table-compact">
                {Array.isArray(table.columns) && table.columns.length ? (
                  <thead><tr>{table.columns.map((c, i) => <th key={i}>{typeof c === "string" ? c : c?.name || `col ${i}`}</th>)}</tr></thead>
                ) : null}
                <tbody>
                  {table.rows.slice(0, 25).map((row, ri) => (
                    <tr key={ri}>{(Array.isArray(row) ? row : Object.values(row)).map((cell, ci) => <td key={ci}>{String(cell ?? "")}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ── dashboard (embedded AI/BI) ─────────────────────────────────────── */

function DashboardTab({ status, host }) {
  const [failed, setFailed] = useState(false);
  const embedUrl = absoluteUrl(host, status?.dashboardUrl);
  if (!status?.dashboardId || !embedUrl) {
    return <EmptyState title="No dashboard registered" body="emet has not published a shared AI/BI dashboard on this workspace yet." />;
  }
  if (failed) {
    return (
      <EmptyState
        title="Dashboard can’t be embedded here"
        body="The Databricks dashboard blocked framing. Open it in a new tab instead."
        action={<a className="ax-dp-link" href={embedUrl} target="_blank" rel="noreferrer">Open dashboard ↗</a>}
      />
    );
  }
  return (
    <div className="ax-dp-dashboard">
      <div className="ax-dp-dashboard-bar">
        <span className="ax-dp-subtle">emet Validation Intelligence — published dashboard</span>
        <a className="ax-dp-link" href={embedUrl} target="_blank" rel="noreferrer">Open in Databricks ↗</a>
      </div>
      <iframe
        title="emet Validation Intelligence dashboard"
        src={embedUrl}
        className="ax-dp-iframe"
        onError={() => setFailed(true)}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"
      />
    </div>
  );
}

/* ── page ───────────────────────────────────────────────────────────── */

export default function EmetPage({ shell = null }) {
  const [params, setParams] = useSurfaceParams(PARAMS_SCHEMA);
  const tab = TABS.some((t) => t.key === params.tab) ? params.tab : "overview";

  const statusHook = useEmetStatus();
  const overview = useEmetOverview({ enabled: statusHook.detected || statusHook.loading });

  const [triggeringId, setTriggeringId] = useState(null);
  const [liveRun, setLiveRun] = useState(null);

  const host = shell?.workspaceHost || shell?.environment?.workspaceHost || "";
  const role = String(shell?.role || shell?.actorRole || "").trim().toLowerCase();
  const canTrigger = TRIGGER_ROLES.has(role);

  const openRun = useCallback((runId) => { if (runId) setParams({ run: String(runId) }); }, [setParams]);
  const closeRun = useCallback(() => setParams({ run: "" }), [setParams]);

  const onTrigger = useCallback(async (job) => {
    if (!job?.executionJobId) return;
    setTriggeringId(job.executionJobId);
    try {
      const token = `axiom-${job.executionJobId}-${Date.now()}`;
      const res = await triggeremetRun(job.executionJobId, { confirm: true, idempotencyToken: token });
      toast(`Triggered ${job.jobName}`, { tone: "success" });
      if (res?.runId) {
        setLiveRun({ runId: res.runId, jobName: job.jobName, runPageUrl: res.runPageUrl });
      }
    } catch (err) {
      toast(err?.message || "Could not trigger the run.", { tone: "danger" });
    } finally {
      setTriggeringId(null);
    }
  }, []);

  const onLiveDone = useCallback((status) => {
    toast(status === "success" ? "emet run succeeded" : "emet run finished", { tone: status === "success" ? "success" : "warning" });
    overview.refresh?.();
    statusHook.refresh?.();
  }, [overview, statusHook]);

  const pageStatus = statusHook.loading
    ? "loading"
    : !statusHook.detected
      ? "unavailable"
      : overview.warnings.length
        ? "degraded"
        : "available";

  const notDetected = !statusHook.loading && !statusHook.detected;

  return (
    <PageShell
      eyebrow="Data quality"
      title="emet Control Center"
      subtitle="Detect, command, and monitor emet validations — trust scores, cutover blockers, and financial impact feed directly into Axiom."
      status={pageStatus}
      onRetry={statusHook.refresh}
      tabs={
        <TabStrip
          tabs={TABS}
          value={tab}
          onChange={(key) => setParams({ tab: key === "overview" ? "" : key })}
        />
      }
    >
      <HealthBand status={statusHook.status} host={host} onRefresh={statusHook.refresh} refreshing={statusHook.refreshing} />

      {liveRun ? (
        <LiveRunMonitor liveRun={liveRun} host={host} onDone={onLiveDone} onClose={() => setLiveRun(null)} />
      ) : null}

      {notDetected ? (
        <SectionCard title="emet not detected" eyebrow="Integration">
          <EmptyState
            title="No emet control plane found"
            body={statusHook.status?.message || "Axiom could not detect a emet installation on this workspace. Install emet, or set AXIOM_emet_CATALOG, then refresh."}
          />
        </SectionCard>
      ) : null}

      {!notDetected && tab === "overview" ? (
        <>
          <RollupTiles rollup={overview.rollup} />
          <SectionCard title="Fix first" eyebrow="Ranked remediation" subtitle="The highest-impact failing validations across the portfolio."
            status={overview.loading ? "loading" : undefined}>
            <FixFirst items={overview.fixFirst} onOpenRun={openRun} />
          </SectionCard>
          <SectionCard title="Validation jobs" eyebrow="Portfolio" subtitle="Every active job with its latest-run trust and trend."
            status={overview.loading ? "loading" : undefined}>
            <JobsTable jobs={overview.jobs} host={host} canTrigger={canTrigger} onTrigger={onTrigger} onOpenRun={openRun} triggeringId={triggeringId} />
          </SectionCard>
        </>
      ) : null}

      {!notDetected && tab === "jobs" ? (
        <SectionCard title="Jobs & runs" eyebrow="Command"
          subtitle={canTrigger ? "Trigger validation runs and monitor them live." : "Read-only — triggering runs requires steward or admin permissions."}
          status={overview.loading ? "loading" : undefined}>
          <JobsTable jobs={overview.jobs} host={host} canTrigger={canTrigger} onTrigger={onTrigger} onOpenRun={openRun} triggeringId={triggeringId} />
        </SectionCard>
      ) : null}

      {!notDetected && tab === "ask" ? (
        <SectionCard title="Ask emet" eyebrow="Signal Room">
          <AskPanel detected={statusHook.detected} />
        </SectionCard>
      ) : null}

      {!notDetected && tab === "dashboard" ? (
        <SectionCard title="Validation Intelligence" eyebrow="AI/BI dashboard">
          <DashboardTab status={statusHook.status} host={host} />
        </SectionCard>
      ) : null}

      <RunDrawer runId={params.run} open={Boolean(params.run)} onClose={closeRun} host={host} />
    </PageShell>
  );
}
