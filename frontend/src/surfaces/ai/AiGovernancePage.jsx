/*
 * surfaces/ai/AiGovernancePage.jsx: the /ai surface (docs/ai_extension/
 * DESIGN.md 10). Inventory | Findings | Intake over the /api/ai views.
 *
 * Truthfulness:
 *  - Tiles show "—" when no reconciliation run has completed (the API sends
 *    null, never zero). PageShell renders the envelope's warnings, which name
 *    each unavailable or degraded source and its reason.
 *  - Every inventory row shows where it was observed (collector, run, time)
 *    and a Sample badge for labeled sample objects.
 *  - Steward actions render only for stewards/admins; the API enforces the
 *    same gate and audits before writing.
 */
import "./ai.css";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  FilterBar,
  LoadingState,
  PageShell,
  SectionCard,
  StatTile,
  TabStrip,
  UnavailableState,
  toast,
} from "../../components/system";
import { useAiFindingAction, useAiFindings, useAiIntake, useAiIntakeImport, useAiInventory, useAiSummary } from "../../hooks/useAiGovernance";
import { formatApiError } from "../../lib/api";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import {
  DASH,
  KIND_LABELS,
  LINK_STATUS_LABELS,
  RECONCILIATION_LABELS,
  aiAssetHref,
  countOrDash,
  findingTypeLabel,
  formatTimestamp,
  groupFindings,
  isSteward,
  kindLabel,
  linkTone,
  percentOrDash,
  postureTone,
  reconciliationLabel,
  reconciliationTone,
  severityTone,
  valueOrDash,
} from "./aiPresentation";

// Mirrors nav/routes.js /ai paramsSchema.
const PARAMS_SCHEMA = {
  tab: { type: "string" },
  kind: { type: "string" },
  state: { type: "string" },
  provider: { type: "string" },
  q: { type: "string" },
  severity: { type: "string" },
  findingState: { type: "string" },
  finding: { type: "string" },
};

const TAB_KEYS = ["inventory", "findings", "intake"];

function SampleBadge({ provenanceClass }) {
  return provenanceClass === "sample" ? (
    <Badge size="sm" tone="accent">
      Sample
    </Badge>
  ) : null;
}

function Provenance({ provenance, showSample = true }) {
  if (!provenance) return <span className="ga-ai-muted">{DASH}</span>;
  return (
    <span className="ga-ai-provenance" title={`Collector ${provenance.collector || DASH} ${provenance.collectorVersion || ""}`}>
      <span>{valueOrDash(provenance.sourceSystem)}</span>
      <span className="ga-ai-muted">run {valueOrDash(provenance.runId)}</span>
      <span className="ga-ai-muted">{formatTimestamp(provenance.observedAt)}</span>
      {showSample ? <SampleBadge provenanceClass={provenance.provenanceClass} /> : null}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Inventory                                                            */
/* ------------------------------------------------------------------ */

function InventoryTab({ params, setParams }) {
  const inventory = useAiInventory({
    kind: params.kind,
    state: params.state,
    provider: params.provider,
    q: params.q,
    sort: "findings",
  });
  const rows = useMemo(() => inventory.data?.items || [], [inventory.data]);
  const total = inventory.data?.total;
  const unavailable = inventory.status === "unavailable" || inventory.status === "error";
  const providerOptions = useMemo(() => {
    const providers = new Set(rows.map((row) => row.provider).filter(Boolean));
    if (params.provider) providers.add(params.provider);
    return [...providers].sort().map((value) => ({ value, label: value }));
  }, [rows, params.provider]);

  const columns = [
    {
      key: "name",
      header: "Asset",
      render: (row) => (
        <span className="ga-ai-name-cell">
          <Link to={aiAssetHref(row.entityId)} title={row.sourceEntityId}>
            {row.name}
          </Link>
          <SampleBadge provenanceClass={row.provenance?.provenanceClass} />
        </span>
      ),
    },
    { key: "entityKind", header: "Kind", render: (row) => kindLabel(row.entityKind) },
    { key: "provider", header: "Provider", render: (row) => valueOrDash(row.provider) },
    { key: "owner", header: "Owner", render: (row) => valueOrDash(row.owner) },
    { key: "tier", header: "Tier", render: (row) => valueOrDash(row.tier) },
    {
      key: "reconciliationState",
      header: "Intake",
      render: (row) =>
        row.reconciliationState ? (
          <Badge size="sm" tone={reconciliationTone(row.reconciliationState)}>
            {reconciliationLabel(row.reconciliationState)}
          </Badge>
        ) : (
          DASH
        ),
    },
    { key: "openFindings", header: "Open findings", render: (row) => row.openFindings.toLocaleString() },
    {
      key: "posture",
      header: "Posture",
      render: (row) =>
        row.posture ? (
          <Badge size="sm" tone={postureTone(row.posture)}>
            {row.posture}
          </Badge>
        ) : (
          DASH
        ),
    },
    // The Sample badge already sits beside the name; don't repeat it per row.
    { key: "provenance", header: "Observed", render: (row) => <Provenance provenance={row.provenance} showSample={false} /> },
  ];

  return (
    <SectionCard
      title="AI inventory"
      subtitle={typeof total === "number" ? `${total.toLocaleString()} asset${total === 1 ? "" : "s"} in the last completed run` : "No completed run"}
    >
      <FilterBar
        facets={[
          { key: "q", label: "Search", type: "search", placeholder: "Search name, id, or owner" },
          { key: "kind", label: "Kind", type: "select", options: Object.entries(KIND_LABELS).filter(([k]) => k !== "intake_record").map(([value, label]) => ({ value, label })) },
          { key: "state", label: "Intake status", type: "select", options: Object.entries(RECONCILIATION_LABELS).map(([value, label]) => ({ value, label })) },
          { key: "provider", label: "Provider", type: "select", options: providerOptions },
        ]}
        label="Inventory filters"
        onChange={(next) => setParams({ q: next.q || "", kind: next.kind || "", state: next.state || "", provider: next.provider || "" })}
        onClear={() => setParams({ q: "", kind: "", state: "", provider: "" })}
        value={{ q: params.q || "", kind: params.kind || "", state: params.state || "", provider: params.provider || "" }}
      />
      {unavailable ? (
        <UnavailableState
          title="No AI inventory to show"
          reason={inventory.meta?.unavailableReason || inventory.errorMessage || "The AI inventory is unavailable."}
          onRetry={inventory.refresh}
        />
      ) : (
        <DataTable
          caption="AI assets observed in the last completed reconciliation run"
          columns={columns}
          emptyState={
            <EmptyState
              title="No AI assets observed"
              body="The last completed run observed no AI assets matching these filters. Check the source availability banner if you expected results."
            />
          }
          loading={inventory.status === "loading"}
          rowKey="entityId"
          rows={rows}
        />
      )}
    </SectionCard>
  );
}

/* ------------------------------------------------------------------ */
/* Findings                                                             */
/* ------------------------------------------------------------------ */

function FindingEvidence({ finding }) {
  const evidence = finding?.evidence || {};
  const differences = Array.isArray(evidence.differences) ? evidence.differences : [];
  const candidates = Array.isArray(evidence.candidates) ? evidence.candidates : [];
  return (
    <div className="ga-ai-evidence">
      <p>{evidence.reason || DASH}</p>
      <dl className="ga-ai-facts">
        <dt>Severity</dt>
        <dd>
          <Badge size="sm" tone={severityTone(finding.severity)}>
            {finding.severity}
          </Badge>
        </dd>
        <dt>Asset</dt>
        <dd>{finding.entityId ? <Link to={aiAssetHref(finding.entityId)}>{evidence.assetName || finding.entityId}</Link> : DASH}</dd>
        <dt>Intake</dt>
        <dd>{valueOrDash(finding.intakeId)}</dd>
        <dt>Match</dt>
        <dd>
          {finding.matchRule ? `${finding.matchRule}, score ${Number(finding.matchScore).toFixed(2)}` : "No match"}
        </dd>
        <dt>First seen</dt>
        <dd>{formatTimestamp(finding.firstSeenAt)}</dd>
        <dt>Last seen</dt>
        <dd>
          {formatTimestamp(finding.lastSeenAt)} (run {valueOrDash(finding.lastRunId)})
        </dd>
        <dt>Observed by</dt>
        <dd>
          <Provenance provenance={evidence.provenance} />
        </dd>
      </dl>
      {differences.length ? (
        <table className="ga-ai-diff">
          <caption>Declared versus observed</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Declared</th>
              <th scope="col">Observed</th>
            </tr>
          </thead>
          <tbody>
            {differences.map((diff) => (
              <tr className="is-different" key={diff.field}>
                <td>{diff.field}</td>
                <td>{valueOrDash(diff.declared)}</td>
                <td>{Array.isArray(diff.observed) ? diff.observed.join(", ") : valueOrDash(diff.observed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {candidates.length ? (
        <div>
          <h4 className="ga-ai-subhead">Candidate intake records</h4>
          <ul className="ga-ai-candidates">
            {candidates.map((candidate) => (
              <li key={candidate.intakeId}>
                {candidate.intakeId}: score {Number(candidate.score).toFixed(2)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function FindingActions({ finding, onDone }) {
  const action = useAiFindingAction();
  const [mode, setMode] = useState("");
  const [text, setText] = useState("");
  const candidates = Array.isArray(finding?.evidence?.candidates) ? finding.evidence.candidates : [];
  const [intakeId, setIntakeId] = useState(candidates[0]?.intakeId || finding?.intakeId || "");
  const canConfirm = ["ambiguous_match", "found_not_registered"].includes(finding?.findingType) && Boolean(finding?.entityId);

  const run = async (variables, success) => {
    try {
      await action.mutateAsync({ findingId: finding.findingId, ...variables });
      toast(success, { tone: "success" });
      setMode("");
      setText("");
      onDone?.();
    } catch (error) {
      toast(formatApiError(error, "The finding could not be updated."), { tone: "danger" });
    }
  };

  const prompts = {
    assign: { label: "Assignee email", button: "Assign", required: true, submit: () => run({ action: "assign", assigneeEmail: text.trim() }, "Finding assigned.") },
    resolve: { label: "Resolution note (required)", button: "Resolve", required: true, submit: () => run({ action: "resolve", note: text.trim() }, "Finding resolved.") },
    suppress: { label: "Suppression reason (required)", button: "Suppress", required: true, submit: () => run({ action: "suppress", reason: text.trim() }, "Finding suppressed. It stays suppressed on later runs.") },
    confirm: { label: "Note (optional)", button: "Confirm match", required: false, submit: () => run({ action: "confirm-match", intakeId, note: text.trim() }, `Match confirmed to ${intakeId}. The next run treats it as a steward match.`) },
  };
  const prompt = prompts[mode];

  if (prompt) {
    const blocked = (prompt.required && !text.trim()) || (mode === "confirm" && !intakeId.trim());
    return (
      <div className="ga-ai-action-form">
        {mode === "confirm" ? (
          <label className="ga-ai-field">
            <span>Intake record</span>
            <input list="ga-ai-candidate-list" onChange={(event) => setIntakeId(event.target.value)} value={intakeId} />
            <datalist id="ga-ai-candidate-list">
              {candidates.map((candidate) => (
                <option key={candidate.intakeId} value={candidate.intakeId} />
              ))}
            </datalist>
          </label>
        ) : null}
        <label className="ga-ai-field">
          <span>{prompt.label}</span>
          <textarea onChange={(event) => setText(event.target.value)} rows={3} value={text} />
        </label>
        <div className="ga-ai-action-row">
          <Button disabled={blocked} loading={action.submitting} onClick={prompt.submit} variant="primary">
            {prompt.button}
          </Button>
          <Button onClick={() => setMode("")} variant="tertiary">
            Cancel
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="ga-ai-action-row">
      {finding.state === "open" ? (
        <Button loading={action.submitting} onClick={() => run({ action: "acknowledge" }, "Finding acknowledged.")} variant="secondary">
          Acknowledge
        </Button>
      ) : null}
      <Button onClick={() => setMode("assign")} variant="secondary">
        Assign
      </Button>
      {canConfirm ? (
        <Button onClick={() => setMode("confirm")} variant="secondary">
          Confirm match
        </Button>
      ) : null}
      <Button onClick={() => setMode("resolve")} variant="secondary">
        Resolve
      </Button>
      <Button onClick={() => setMode("suppress")} tone="danger" variant="tertiary">
        Suppress
      </Button>
    </div>
  );
}

function FindingsTab({ params, setParams }) {
  const findings = useAiFindings({ state: params.findingState || "open,acknowledged", severity: params.severity || "" });
  const rows = findings.data?.items || [];
  const groups = groupFindings(rows);
  const selected = rows.find((row) => row.findingId === params.finding) || null;
  const unavailable = findings.status === "unavailable" || findings.status === "error";

  const columns = [
    {
      key: "severity",
      header: "Severity",
      render: (row) => (
        <Badge size="sm" tone={severityTone(row.severity)}>
          {row.severity}
        </Badge>
      ),
    },
    {
      key: "asset",
      header: "Asset or intake",
      render: (row) => (
        <button className="ga-ai-linkish" onClick={() => setParams({ finding: row.findingId })} type="button">
          {row.evidence?.assetName || row.intakeId || row.entityId}
        </button>
      ),
    },
    { key: "intakeId", header: "Intake", render: (row) => valueOrDash(row.intakeId) },
    { key: "state", header: "State", render: (row) => row.state },
    { key: "assigneeEmail", header: "Assignee", render: (row) => valueOrDash(row.assigneeEmail) },
    { key: "lastSeenAt", header: "Last seen", render: (row) => formatTimestamp(row.lastSeenAt) },
  ];

  return (
    <>
      <FilterBar
        facets={[
          {
            key: "severity",
            label: "Severity",
            type: "select",
            options: ["critical", "high", "medium", "low"].map((value) => ({ value, label: value })),
          },
          {
            key: "findingState",
            label: "State",
            type: "select",
            options: [
              { value: "open,acknowledged", label: "Open and acknowledged" },
              { value: "open", label: "Open" },
              { value: "acknowledged", label: "Acknowledged" },
              { value: "suppressed", label: "Suppressed" },
              { value: "resolved", label: "Resolved" },
            ],
          },
        ]}
        label="Finding filters"
        onChange={(next) => setParams({ severity: next.severity || "", findingState: next.findingState || "" })}
        onClear={() => setParams({ severity: "", findingState: "" })}
        value={{ severity: params.severity || "", findingState: params.findingState || "" }}
      />
      {unavailable ? (
        <UnavailableState
          title="Findings unavailable"
          reason={findings.meta?.unavailableReason || findings.errorMessage || "Findings could not be loaded."}
          onRetry={findings.refresh}
        />
      ) : findings.status === "loading" ? (
        <SectionCard status="loading" title="Findings">
          <LoadingState label="Loading findings" />
        </SectionCard>
      ) : groups.length === 0 ? (
        <EmptyState title="No findings in this view" body="Reconciliation found nothing matching these filters in the completed runs." />
      ) : (
        groups.map((group) => (
          <SectionCard key={group.type} subtitle={`${group.items.length} finding${group.items.length === 1 ? "" : "s"}`} title={findingTypeLabel(group.type)}>
            <DataTable caption={findingTypeLabel(group.type)} columns={columns} rowKey="findingId" rows={group.items} />
          </SectionCard>
        ))
      )}
      <Drawer
        onClose={() => setParams({ finding: "" })}
        open={Boolean(selected)}
        title={selected ? findingTypeLabel(selected.findingType) : ""}
        footer={selected ? <FindingActions finding={selected} key={selected.findingId} onDone={() => setParams({ finding: "" })} /> : null}
      >
        {selected ? <FindingEvidence finding={selected} /> : null}
      </Drawer>
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Intake                                                               */
/* ------------------------------------------------------------------ */

function ImportDrawer({ open, onClose }) {
  const importer = useAiIntakeImport();
  const [text, setText] = useState("");
  const [report, setReport] = useState(null);
  const [validatedText, setValidatedText] = useState(null);
  const [confirming, setConfirming] = useState(false);

  const readFile = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    file.text().then((content) => {
      setText(content);
      setReport(null);
      setConfirming(false);
    });
  };

  const submit = async (mode) => {
    try {
      const result = await importer.mutateAsync({ csvText: text, mode });
      setReport(result);
      if (mode === "dry_run") {
        setValidatedText(text);
        return;
      }
      const committed = result.committed || {};
      toast(`Imported intake: ${committed.created || 0} created, ${committed.updated || 0} updated, ${committed.unchanged || 0} unchanged.`, { tone: "success" });
      setText("");
      setReport(null);
      setValidatedText(null);
      setConfirming(false);
      onClose?.();
    } catch (error) {
      // A rejected commit (422) carries the per-row report: show it.
      if (error?.payload?.results) setReport(error.payload);
      toast(formatApiError(error, "The intake import failed."), { tone: "danger" });
      setConfirming(false);
    }
  };

  const invalidRows = (report?.results || []).filter((row) => row.status === "invalid");
  const canCommit = Boolean(report?.ok) && validatedText === text && text.trim().length > 0;

  return (
    <Drawer
      footer={
        <div className="ga-ai-action-row">
          <Button disabled={!text.trim()} loading={importer.submitting && !confirming} onClick={() => submit("dry_run")} variant="secondary">
            Validate (dry run)
          </Button>
          {confirming ? (
            <Button loading={importer.submitting} onClick={() => submit("commit")} variant="primary">
              Confirm import of {report?.summary?.valid || 0} rows
            </Button>
          ) : (
            <Button disabled={!canCommit} onClick={() => setConfirming(true)} variant="primary">
              Commit
            </Button>
          )}
        </div>
      }
      onClose={onClose}
      open={open}
      title="Import intake records"
    >
      <div className="ga-ai-import">
        <p className="ga-ai-muted">
          Upload or paste a CSV. Required columns: intake ID, title, state, owner. Validate first; commit writes only when every row is valid, and each row is audited.
        </p>
        <label className="ga-ai-field">
          <span>CSV file</span>
          <input accept=".csv,text/csv" onChange={readFile} type="file" />
        </label>
        <label className="ga-ai-field">
          <span>CSV text</span>
          <textarea
            onChange={(event) => {
              setText(event.target.value);
              setConfirming(false);
            }}
            rows={8}
            value={text}
          />
        </label>
        {report ? (
          <div className="ga-ai-import-report" role="status">
            <strong>
              {report.summary?.valid || 0} valid, {report.summary?.invalid || 0} invalid of {report.summary?.total || 0} rows
            </strong>
            {(report.parseErrors || []).map((error) => (
              <p className="ga-ai-error" key={`${error.row}-${error.message}`}>
                Row {error.row}: {error.message}
              </p>
            ))}
            {invalidRows.slice(0, 50).map((row) => (
              <p className="ga-ai-error" key={row.rowNumber}>
                Row {row.rowNumber} {row.intakeId ? `(${row.intakeId})` : ""}: {row.errors.map((error) => `${error.field}: ${error.message}`).join("; ")}
              </p>
            ))}
            {validatedText !== null && validatedText !== text ? <p className="ga-ai-muted">The CSV changed since validation. Validate again before committing.</p> : null}
          </div>
        ) : null}
      </div>
    </Drawer>
  );
}

function IntakeTab({ steward }) {
  const intake = useAiIntake();
  const [importOpen, setImportOpen] = useState(false);
  const rows = intake.data?.items || [];
  const columns = [
    { key: "intakeId", header: "Intake ID" },
    { key: "title", header: "Title" },
    { key: "state", header: "State", render: (row) => <Badge size="sm" status={row.state}>{row.state}</Badge> },
    { key: "ownerEmail", header: "Owner" },
    { key: "riskTier", header: "Tier", render: (row) => valueOrDash(row.riskTier) },
    { key: "provider", header: "Provider", render: (row) => valueOrDash(row.provider) },
    {
      key: "linkStatus",
      header: "Link",
      render: (row) => (
        <Badge size="sm" tone={linkTone(row.linkStatus)}>
          {LINK_STATUS_LABELS[row.linkStatus] || row.linkStatus}
        </Badge>
      ),
    },
    {
      key: "provenance",
      header: "Source",
      render: (row) => (
        <span className="ga-ai-provenance">
          <span>{valueOrDash(row.provenance?.ingestSource)}</span>
          <span className="ga-ai-muted">{valueOrDash(row.provenance?.ingestRunId)}</span>
          <SampleBadge provenanceClass={row.provenance?.provenanceClass} />
        </span>
      ),
    },
  ];
  return (
    <SectionCard
      actions={
        steward ? (
          <Button onClick={() => setImportOpen(true)} variant="primary">
            Import CSV
          </Button>
        ) : null
      }
      subtitle={intake.status === "loading" ? "Loading intake records…" : `${rows.length.toLocaleString()} intake record${rows.length === 1 ? "" : "s"}`}
      title="Intake records"
    >
      {intake.status === "error" ? (
        <UnavailableState title="Intake unavailable" reason={intake.errorMessage} onRetry={intake.refresh} />
      ) : (
        <DataTable
          caption="Declared AI intake records"
          columns={columns}
          emptyState={<EmptyState title="No intake records" body={steward ? "Import a CSV to declare AI use cases." : "A steward can import intake records."} />}
          loading={intake.status === "loading"}
          rowKey="intakeId"
          rows={rows}
        />
      )}
      {steward ? <ImportDrawer onClose={() => setImportOpen(false)} open={importOpen} /> : null}
    </SectionCard>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                 */
/* ------------------------------------------------------------------ */

export function AiGovernancePage({ shell = null }) {
  const [params, setParams] = useSurfaceParams(PARAMS_SCHEMA);
  const steward = isSteward(shell);
  const summary = useAiSummary();
  const data = summary.data?.summary || {};
  const run = summary.data?.availability?.run || null;
  const requested = TAB_KEYS.includes(params.tab) ? params.tab : "inventory";
  // Findings are steward-only on the API; readers never see a tab that 403s.
  const tab = requested === "findings" && !steward ? "inventory" : requested;

  const tabs = [
    { key: "inventory", label: "Inventory" },
    ...(steward ? [{ key: "findings", label: "Findings", badge: data.findings?.open || undefined }] : []),
    { key: "intake", label: "Intake" },
  ];

  return (
    <PageShell
      className="ga-ai-page"
      eyebrow="Govern"
      status={summary}
      subtitle={
        run
          ? `Last completed reconciliation run ${run.runId}, finished ${formatTimestamp(run.finishedAt)}`
          : summary.status === "loading"
            ? "Loading AI governance…"
            : "No reconciliation run has completed yet"
      }
      tabs={<TabStrip ariaLabel="AI governance views" param={{ value: tab, set: (key) => setParams({ tab: key, finding: "" }) }} tabs={tabs} />}
      title="AI Governance"
    >
      <div className="ga-ai-tiles">
        <StatTile hint="Observed in the last completed run" label="AI assets" value={countOrDash(data.assetCount)} />
        <StatTile
          hint="Open found-not-registered and rejected-but-running findings"
          label="Shadow AI"
          tone={data.shadowAi ? "danger" : "neutral"}
          value={countOrDash(data.shadowAi)}
        />
        <StatTile hint="Awaiting steward confirmation" label="Ambiguous matches" value={countOrDash(data.ambiguousMatches)} />
        <StatTile
          hint="Share of assets with at least one known control result (unknowns excluded)"
          label="Posture coverage"
          value={percentOrDash(data.posture?.coverage)}
        />
      </div>
      {tab === "inventory" ? <InventoryTab params={params} setParams={setParams} /> : null}
      {tab === "findings" ? <FindingsTab params={params} setParams={setParams} /> : null}
      {tab === "intake" ? <IntakeTab steward={steward} /> : null}
    </PageShell>
  );
}

export default AiGovernancePage;
