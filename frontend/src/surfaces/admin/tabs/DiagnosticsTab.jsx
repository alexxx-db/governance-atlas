import { useState } from "react";
import {
  Badge,
  Button,
  DataTable,
  LoadingState,
  SectionCard,
  StatusBanner,
  UnavailableState,
} from "../../../components/system";
import { useAdminTruthCheck } from "../../../hooks/useAdminControlCenter";
import { useCapabilityDashboard } from "../../../hooks/useCapabilityDashboard";
import {
  availabilityLabel,
  deltaLabel,
  deltaTone,
  envelopeData,
  humanTimestamp,
  label,
  numberValue,
  readableState,
  responseStatus,
  stateText,
  text,
  toneForAvailability,
} from "../adminPresentation";

/*
 * Control Center · Diagnostics tab (Wave C6) — absorbs the /capabilities
 * surface (CapabilityDashboard) and the legacy Metastore truth check tab.
 *
 * Capability truth table: the RUNTIME's per-request capability flags
 * (/api/runtime/status via useCapabilityDashboard) side by side with the
 * conservative BOOTSTRAP signal. Where they disagree, the live runtime wins —
 * bootstrap pessimism must never read as product truth (CLAUDE.md).
 */

const CAPABILITY_KEYS = [
  { key: "governanceWrite", label: "Governance write" },
  { key: "governanceApproval", label: "Governance approval" },
  { key: "systemInventoryRead", label: "System inventory read" },
  { key: "tableLineage", label: "Table lineage" },
  { key: "columnLineage", label: "Column lineage" },
  { key: "workloadVisibility", label: "Workload visibility" },
  { key: "qualityRunEligibility", label: "Quality run eligibility" },
  { key: "exportAllowed", label: "Export allowed" },
  { key: "manualLineageOverrides", label: "Manual lineage overrides" },
];

const SYSTEM_TABLE_KEYS = [
  { key: "systemInventoryRead", label: "system.information_schema.tables / columns" },
  { key: "tableLineage", label: "system.access.table_lineage" },
  { key: "workloadVisibility", label: "system.query.history" },
];

function KvRow({ heading, value, tone = "neutral", hint = "" }) {
  return (
    <div className="ax-admin-kv">
      <span className="ax-admin-kv-label">{heading}</span>
      <span className="ax-admin-kv-value">
        <Badge tone={tone}>{value}</Badge>
      </span>
      {hint ? <span className="ax-admin-kv-hint">{hint}</span> : null}
    </div>
  );
}

function IdentitySection({ identity, capabilities }) {
  const actorEmail = identity?.actorEmail || "unknown";
  const authMode = identity?.authMode || "no-identity";
  const visibilityScope = identity?.visibilityScope || "";
  const authenticated = identity?.authenticatedUserPresent === true;
  // OBO scope-fallback: capabilities.systemInventoryRead.source reflects
  // which plane served the read — the closest honest signal available.
  const systemInventoryRead = capabilities?.systemInventoryRead || {};
  const scopeFallbackTriggered =
    authMode === "obo-available" && systemInventoryRead.source === "unity-catalog-app-principal";

  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Forwarded user, authorization mode, and read-path visibility scope"
      title="Identity and auth"
    >
      <div className="ax-admin-kv-grid">
        <KvRow heading="Actor email" value={actorEmail} />
        <KvRow
          heading="Authenticated user"
          tone={authenticated ? "good" : "warn"}
          value={authenticated ? "Yes" : "No"}
        />
        <KvRow
          heading="Auth mode"
          tone={authMode === "obo-available" ? "good" : authMode === "app-principal-only" ? "warn" : "bad"}
          value={authMode}
        />
        <KvRow
          heading="Visibility scope"
          tone={visibilityScope ? "neutral" : "warn"}
          value={visibilityScope || "unknown"}
        />
        <KvRow
          heading="OBO scope fallback"
          hint={
            scopeFallbackTriggered
              ? "The forwarded user token lacks the sql scope; reads are served by the app-principal."
              : ""
          }
          tone={scopeFallbackTriggered ? "warn" : "good"}
          value={scopeFallbackTriggered ? "Triggered" : "Not triggered"}
        />
      </div>
    </SectionCard>
  );
}

function RuntimeSection({ runtime, store, config }) {
  const client = runtime?.client || {};
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Live Databricks SQL runtime, governance control-plane, and UC client metadata"
      title="Runtime and store"
    >
      <div className="ax-admin-kv-grid">
        <KvRow
          heading="Runtime state"
          hint={runtime?.message || ""}
          tone={toneForRuntime(runtime?.state)}
          value={readableState(runtime?.state || "unknown")}
        />
        <KvRow
          heading="Store state"
          hint={store?.message || ""}
          tone={toneForRuntime(store?.state)}
          value={readableState(store?.state || "unknown")}
        />
        <KvRow heading="Warehouse id" value={config?.warehouseId || client?.warehouseId || "—"} />
        <KvRow heading="Workspace host" value={client?.host || client?.workspaceHost || "—"} />
        <KvRow heading="OAuth mode" value={client?.authMode || client?.authType || "—"} />
        <KvRow
          heading="Gov catalog / schema"
          value={`${config?.govCatalog || "—"} / ${config?.govSchema || "—"}`}
        />
      </div>
    </SectionCard>
  );
}

function toneForRuntime(state) {
  const normalized = text(state).toLowerCase();
  if (["live", "available", "ready", "success"].includes(normalized)) return "good";
  if (["degraded", "warn", "warning", "unknown", "loading", "skipped"].includes(normalized)) return "warn";
  if (["unavailable", "error", "bad"].includes(normalized)) return "bad";
  return "neutral";
}

/** Bootstrap's conservative capability signal for one flag, or null. */
function bootstrapFlag(bootstrap, key) {
  const flag = bootstrap?.capabilities?.[key];
  return flag && typeof flag === "object" ? flag : null;
}

function CapabilityTruthTable({ capabilities, bootstrap }) {
  const rows = CAPABILITY_KEYS.map(({ key, label: flagLabel }) => {
    const flag = capabilities?.[key] || {};
    const boot = bootstrapFlag(bootstrap, key);
    return {
      id: key,
      label: flagLabel,
      available: flag.available,
      state: flag.state || "unknown",
      reason: flag.reason || "",
      visibilityScope: flag.visibilityScope || "",
      source: flag.source || "",
      protectedRead: flag.protectedRead === true,
      boot,
    };
  });

  const columns = [
    { key: "label", header: "Capability", render: (row) => <strong>{row.label}</strong> },
    {
      key: "runtime",
      header: "Runtime",
      render: (row) => (
        <Badge tone={toneForAvailability(row.available, row.state)}>
          {availabilityLabel(row.available, row.state)}
        </Badge>
      ),
    },
    {
      key: "bootstrap",
      header: "Bootstrap",
      render: (row) =>
        row.boot ? (
          <Badge tone={toneForAvailability(row.boot.available, row.boot.state)}>
            {availabilityLabel(row.boot.available, row.boot.state)}
          </Badge>
        ) : (
          // Bootstrap simply doesn't report every flag — say so, don't guess.
          <span title="The bootstrap payload does not report this capability.">—</span>
        ),
    },
    {
      key: "state",
      header: "State",
      render: (row) => <Badge tone={toneForRuntime(row.state)}>{readableState(row.state)}</Badge>,
    },
    { key: "reason", header: "Reason", render: (row) => row.reason || "—" },
    { key: "visibilityScope", header: "Visibility scope", render: (row) => row.visibilityScope || "—" },
    { key: "source", header: "Source", render: (row) => row.source || "—" },
    {
      key: "protectedRead",
      header: "Read plane",
      render: (row) =>
        row.protectedRead ? <Badge tone="warn">Protected</Badge> : <Badge tone="good">Open</Badge>,
    },
  ];

  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Runtime truth per request vs the conservative bootstrap signal. Where they disagree, the live runtime wins — bootstrap pessimism is a warm-up artifact, not product truth."
      title="Capability truth"
    >
      <DataTable
        caption="Capability truth flags"
        className="ax-admin-capability-table"
        columns={columns}
        emptyMessage="The runtime did not report capability flags."
        rowKey="id"
        rows={rows}
      />
    </SectionCard>
  );
}

function BackgroundSection({ background, error }) {
  if (error) {
    return (
      <SectionCard className="ax-admin-card" title="Background work health">
        <StatusBanner message={error} title="Background status unavailable" tone="warning" />
      </SectionCard>
    );
  }
  if (!background) {
    return (
      <SectionCard className="ax-admin-card" title="Background work health">
        <StatusBanner
          message="The background drainer has not reported a tick yet. If the app just started, refresh in a few seconds; the first drain pass runs on the 30-second interval."
          title="Not yet observed"
          tone="warning"
        />
      </SectionCard>
    );
  }
  const drainer = background.drainer || {};
  const queue = background.queue || {};
  const running = drainer.running === true;
  const processedTotal = Number.isFinite(Number(drainer.processedTotal))
    ? Number(drainer.processedTotal)
    : 0;
  const lastError = drainer.lastError || "";
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="In-process drainer that claims queued work items every 30 seconds"
      title="Background work health"
    >
      <div className="ax-admin-kv-grid">
        <KvRow heading="Drainer running" tone={running ? "good" : "bad"} value={running ? "Yes" : "No"} />
        <KvRow
          heading="Last drain at"
          tone={drainer.lastDrainAt ? "good" : "warn"}
          value={drainer.lastDrainAt ? humanTimestamp(drainer.lastDrainAt) : "Not yet observed"}
        />
        <KvRow heading="Processed total" value={String(processedTotal)} />
        <KvRow
          heading="Queue depth hint"
          tone={queue.depthHint == null ? "warn" : "neutral"}
          value={queue.depthHint == null ? "Not observed" : String(queue.depthHint)}
        />
        <KvRow heading="Last error" tone={lastError ? "bad" : "good"} value={lastError || "None"} />
        <KvRow
          heading="Envelope state"
          hint={background.reason || ""}
          tone={toneForRuntime(background.state || "unknown")}
          value={readableState(background.state || "unknown")}
        />
      </div>
    </SectionCard>
  );
}

function SystemTableHealth({ capabilities }) {
  const rows = SYSTEM_TABLE_KEYS.map(({ key, label: tableLabel }) => {
    const flag = capabilities?.[key] || {};
    return {
      id: key,
      label: tableLabel,
      available: flag.available,
      state: flag.state || "unknown",
      reason: flag.reason || "",
    };
  });
  const columns = [
    { key: "label", header: "System table", render: (row) => <code>{row.label}</code> },
    {
      key: "available",
      header: "Reachable",
      render: (row) => (
        <Badge tone={toneForAvailability(row.available, row.state)}>
          {availabilityLabel(row.available, row.state)}
        </Badge>
      ),
    },
    {
      key: "state",
      header: "State",
      render: (row) => <Badge tone={toneForRuntime(row.state)}>{readableState(row.state)}</Badge>,
    },
    { key: "reason", header: "Reason", render: (row) => row.reason || "—" },
  ];
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Reachability of the Databricks system tables that power discovery, lineage, and workload surfaces"
      title="System-table health"
    >
      <DataTable
        caption="System table reachability"
        className="ax-admin-capability-table"
        columns={columns}
        rowKey="id"
        rows={rows}
      />
    </SectionCard>
  );
}

/*
 * Metastore truth check — authoritative counts from
 * system.information_schema vs the inventory + visible-asset pipeline the
 * UI actually surfaced, so admins can spot stale caches, missing scopes, or
 * over-aggressive visibility filters without a notebook.
 */
function TruthCheckSection({ enabled }) {
  const [showSql, setShowSql] = useState(false);
  const truthQuery = useAdminTruthCheck({ enabled });
  const payload = truthQuery.data || null;
  const data = envelopeData(payload) || {};
  const meta = payload?.meta || {};
  const forbidden = !enabled || responseStatus(truthQuery.error) === 403;

  if (enabled && (truthQuery.status === "loading" || truthQuery.status === "hydrating") && !payload) {
    return (
      <SectionCard className="ax-admin-card" title="Metastore truth check">
        <LoadingState label="Running metastore truth check" variant="table" />
      </SectionCard>
    );
  }
  if (forbidden || truthQuery.status === "error") {
    return (
      <SectionCard className="ax-admin-card" title="Metastore truth check">
        <UnavailableState
          reason={
            forbidden
              ? "Ask a workspace admin to grant administration access."
              : truthQuery.errorMessage || "Truth check unavailable."
          }
          title={forbidden ? "Metastore truth check is admin-only" : "Truth check unavailable"}
        />
      </SectionCard>
    );
  }

  const metastore = data.metastore || {};
  const ui = data.ui || {};
  const drift = data.drift || {};
  const perCatalog = Array.isArray(metastore.perCatalog) ? metastore.perCatalog : [];
  const queries = Array.isArray(data.queries) ? data.queries : [];
  const warnings = Array.isArray(drift.warnings) ? drift.warnings : [];
  const discoveryCatalogs = Array.isArray(data.discoveryCatalogs) ? data.discoveryCatalogs : [];

  const catalogColumns = [
    {
      key: "catalog",
      header: "Catalog",
      render: (row) => (
        <span className="ax-admin-truth-catalog">
          <code>{row.catalog}</code>
          {/* All-zero catalogs are ambiguous (empty vs. missing grants);
              badge them so the zeros don't read as a broken pipeline. */}
          {text(row.state) === "empty-or-unauthorized" ? (
            <span title={text(row.stateReason) || undefined}>
              <Badge tone="muted">No objects visible to app principal</Badge>
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "configured",
      header: "Configured",
      render: (row) => (
        <Badge tone={row.configured ? "good" : "muted"}>
          {row.configured ? "Configured" : "Not configured"}
        </Badge>
      ),
    },
    { key: "schemas", header: "Metastore schemas", render: (row) => numberValue(row.metastore?.schemaCount) },
    { key: "tables", header: "Metastore tables", render: (row) => numberValue(row.metastore?.tableCount) },
    { key: "inventory", header: "UI inventory", render: (row) => numberValue(row.ui?.inventoryAssetCount) },
    { key: "visible", header: "UI visible", render: (row) => numberValue(row.ui?.visibleAssetCount) },
    {
      key: "drift",
      header: "Inventory drift",
      render: (row) => (
        <span className={`ax-admin-truth-delta tone-${deltaTone(row.drift?.inventoryDelta)}`}>
          {deltaLabel(row.drift?.inventoryDelta)}
        </span>
      ),
    },
    {
      key: "hidden",
      header: "Hidden by visibility",
      render: (row) => (
        <span className={`ax-admin-truth-delta tone-${deltaTone(row.drift?.hiddenByVisibility)}`}>
          {deltaLabel(row.drift?.hiddenByVisibility)}
        </span>
      ),
    },
  ];

  return (
    <SectionCard
      actions={
        <Button onClick={() => truthQuery.refresh()} size="sm" variant="secondary">
          Re-run truth check
        </Button>
      }
      className="ax-admin-card"
      subtitle="Authoritative counts from system.information_schema compared to what the inventory and visibility pipeline surfaced"
      title="Metastore truth check"
    >
      <div aria-label="Truth check totals" className="ax-admin-summary-grid" role="group">
        <div className="ax-admin-summary-tile">
          <small>Catalogs</small>
          <strong>{numberValue(metastore.catalogTotal)}</strong>
          <span>in metastore (excl. hidden)</span>
        </div>
        <div className="ax-admin-summary-tile">
          <small>Schemas</small>
          <strong>{numberValue(metastore.schemaTotalForDiscovery)}</strong>
          <span>across discovery catalogs</span>
        </div>
        <div className="ax-admin-summary-tile">
          <small>Tables</small>
          <strong>{numberValue(metastore.tableTotalForDiscovery)}</strong>
          <span>across discovery catalogs</span>
        </div>
        <div className="ax-admin-summary-tile">
          <small>UI inventory</small>
          <strong>{numberValue(ui.inventoryTotal)}</strong>
          <span>before visibility filters</span>
        </div>
        <div className="ax-admin-summary-tile">
          <small>UI visible</small>
          <strong>{numberValue(ui.visibleTotal)}</strong>
          <span>after visibility filters</span>
        </div>
        <div className="ax-admin-summary-tile">
          <small>Drift</small>
          <strong className={`ax-admin-truth-delta tone-${deltaTone(drift.inventoryDelta)}`}>
            {deltaLabel(drift.inventoryDelta)}
          </strong>
          <span>metastore − inventory</span>
        </div>
      </div>

      {/* Render EVERY warning: drift explanations ride alongside query
          failures, and showing only the first hid the drift context. */}
      {warnings.map((warning) => (
        <StatusBanner key={warning} message={warning} tone="warning" />
      ))}

      <p className="ax-admin-truth-meta">
        Observed <strong>{humanTimestamp(data.observedAt)}</strong> · Discovery catalogs:{" "}
        {discoveryCatalogs.length ? (
          discoveryCatalogs.map((catalog) => <code key={catalog}>{catalog}</code>)
        ) : (
          <em>none configured</em>
        )}
      </p>

      <DataTable
        caption="Per-catalog metastore vs UI comparison"
        className="ax-admin-truth-table"
        columns={catalogColumns}
        emptyState={
          <UnavailableState
            reason="The truth-check returned an empty per-catalog breakdown. Configure AXIOM_DISCOVERY_CATALOGS or grant the app principal access to system.information_schema."
            title="No catalog rows reported"
          />
        }
        rowKey="catalog"
        rows={perCatalog}
      />

      <details
        className="ax-admin-truth-queries"
        onToggle={(event) => setShowSql(event.currentTarget.open)}
        open={showSql}
      >
        <summary>SQL probes ({queries.length})</summary>
        <ul>
          {queries.map((entry, index) => (
            <li key={`${entry.label || "query"}-${index}`}>
              <header>
                <strong>{label(entry.label, "Query")}</strong>
                <span>
                  {/* `== null` (not truthiness): a legit 0 ms probe must
                      render "0 ms", not "elapsed unavailable". */}
                  {entry.elapsedMs == null ? "elapsed unavailable" : `${entry.elapsedMs} ms`} · rowCount{" "}
                  {numberValue(entry.rowCount)}
                </span>
              </header>
              <pre>{entry.sql || ""}</pre>
              {entry.error ? <p className="ax-admin-truth-query-error">{entry.error}</p> : null}
            </li>
          ))}
        </ul>
      </details>

      <p className="ax-admin-truth-state" data-state={text(meta.state)}>
        Truth-check state: <strong>{stateText(meta.state || "available")}</strong>
        {meta.reason ? <span> · {meta.reason}</span> : null}
      </p>
    </SectionCard>
  );
}

export function DiagnosticsTab({ canReadAdmin, bootstrap }) {
  const dashboard = useCapabilityDashboard({ enabled: canReadAdmin });
  const {
    loading,
    refreshing,
    runtimeError,
    backgroundError,
    identity,
    runtime,
    store,
    config,
    capabilities,
    background,
    lastRefreshedAt,
    refetch,
  } = dashboard;

  return (
    <div className="ax-admin-tab-body" id="ax-admin-panel-diagnostics" role="tabpanel">
      <div className="ax-admin-diagnostics-toolbar">
        <p className="ax-admin-diagnostics-note">
          Read-only snapshot of what the live runtime says the app can do, sourced from{" "}
          <code>/api/runtime/status</code> and <code>/api/admin/background/status</code>. Every value
          is a truthful mirror of a server-side signal — no synthesized metrics.
          {lastRefreshedAt ? ` Last refreshed ${humanTimestamp(lastRefreshedAt)}.` : ""}
        </p>
        <Button
          aria-label="Refresh capability snapshot"
          loading={refreshing}
          onClick={() => {
            void refetch();
          }}
          variant="primary"
        >
          {refreshing ? "Refreshing…" : "Refresh snapshot"}
        </Button>
      </div>

      {loading ? (
        <LoadingState label="Loading capability snapshot" variant="page" />
      ) : (
        <>
          {runtimeError ? (
            <StatusBanner message={runtimeError} title="Runtime status unavailable" tone="danger" />
          ) : null}
          <CapabilityTruthTable bootstrap={bootstrap} capabilities={capabilities || {}} />
          <IdentitySection capabilities={capabilities || {}} identity={identity} />
          <RuntimeSection config={config} runtime={runtime} store={store} />
          <BackgroundSection background={background} error={backgroundError} />
          <SystemTableHealth capabilities={capabilities || {}} />
          <TruthCheckSection enabled={canReadAdmin} />
        </>
      )}
    </div>
  );
}

export default DiagnosticsTab;
