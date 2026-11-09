import { Badge, DataTable, EmptyState, EntityChip, LoadingState, SectionCard, UnavailableState } from "../../../components/system";
import {
  humanTimestamp,
  label,
  looksLikeAssetFqn,
  numberOrNull,
  percentValue,
  stateText,
  statusTone,
  text,
} from "../adminPresentation";

/*
 * Control Center · Operations tab (Wave C6).
 *   - Runtime/coverage admin summary built ONLY from fields already present
 *     in the control-center payload — no synthesized metrics.
 *   - Scheduled jobs on the system DataTable with the honesty contract intact
 *     (Last run / Next run split, "Not yet run", UTC year-carrying stamps,
 *     hash-tail truncation, backend jobsReason on genuine emptiness).
 *   - Recent admin activity: the backend visibility-scopes the feed before it
 *     ships; asset mentions and actors render as EntityChip anchors (LAW).
 */

// Workspace host as an absolute https URL (defense-in-depth: the backend now
// normalizes it, but a schemeless value must never mint a relative deep link).
function absoluteHost(raw) {
  const host = text(raw).replace(/\/+$/, "");
  if (!host) return "";
  return /^https?:\/\//i.test(host) ? host : `https://${host}`;
}

/**
 * @param {{ heading?: string, value?: any, hint?: string, href?: string, linkTitle?: string }} props
 */
function SummaryTile({ heading, value, hint, href, linkTitle }) {
  const strong = <strong>{value}</strong>;
  return (
    <div className="ax-admin-summary-tile">
      <small>{heading}</small>
      {href ? (
        <a
          className="ax-admin-summary-link"
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          title={linkTitle || "Open in Databricks"}
        >
          {strong}
          <svg
            className="ax-admin-summary-ext"
            viewBox="0 0 24 24"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M7 17 17 7M17 7H8m9 0v9" />
          </svg>
        </a>
      ) : (
        strong
      )}
      {hint ? <span>{hint}</span> : null}
    </div>
  );
}

function RuntimeSummary({ dashboard, hydrating }) {
  const runtime = dashboard.runtimeSummary || dashboard.system || {};
  const access = dashboard.access || {};
  const coverage = dashboard.coverage || {};
  const environment = dashboard.environment || {};
  const role = dashboard.role || {};
  const hasSignal = [
    runtime.state,
    coverage.metadataCoverage,
    access.users?.value,
    environment.catalog,
    role.label,
  ].some((value) => value !== null && value !== undefined && value !== "");
  const namespace = [text(environment.catalog), text(environment.schema)].filter(Boolean).join(".");
  const users = numberOrNull(access.users?.value);
  const roles = numberOrNull(access.roles?.value);
  // Deep links into the Databricks workspace for the warehouse + account users.
  const workspaceHost = absoluteHost(environment.workspaceHost || runtime.host);
  const warehouseId = text(runtime.warehouseId || environment.warehouseId);
  const warehouseHref = workspaceHost && warehouseId ? `${workspaceHost}/sql/warehouses/${warehouseId}` : "";
  const usersHref = workspaceHost
    ? `${workspaceHost}/settings/workspace/identity-and-access/users`
    : "";

  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Live diagnostics reported by the app runtime"
      title="Runtime summary"
    >
      {hydrating && !hasSignal ? (
        <LoadingState label="Loading runtime summary" variant="tile" />
      ) : (
        <div aria-label="Runtime summary tiles" className="ax-admin-summary-grid" role="group">
          <SummaryTile
            heading="Runtime"
            hint={text(runtime.host) || text(runtime.authMode) || "workspace client"}
            value={stateText(runtime.state)}
          />
          <SummaryTile
            heading="Catalogs"
            hint="visible to runtime"
            value={numberOrNull(runtime.catalogCount) == null ? "Unavailable" : Number(runtime.catalogCount).toLocaleString()}
          />
          <SummaryTile
            heading="SQL warehouse"
            hint="bound warehouse"
            href={warehouseHref}
            linkTitle="Open this SQL warehouse in Databricks"
            value={label(runtime.warehouseId || environment.warehouseId)}
          />
          <SummaryTile
            heading="Metadata coverage"
            hint="across visible assets"
            value={percentValue(coverage.metadataCoverage)}
          />
          <SummaryTile
            heading="Access"
            hint={roles == null ? "roles unavailable" : `${roles.toLocaleString()} roles`}
            href={users == null ? "" : usersHref}
            linkTitle="Manage workspace users in Databricks"
            value={users == null ? "Unavailable" : `${users.toLocaleString()} users`}
          />
          <SummaryTile
            heading="Environment"
            hint={text(environment.target) || "target unreported"}
            value={label(namespace)}
          />
          <SummaryTile heading="Your role" hint="acting permissions" value={label(role.label)} />
        </div>
      )}
    </SectionCard>
  );
}

const JOB_COLUMNS = [
  {
    key: "name",
    header: "Job",
    render: (job) => (
      // Hash tails truncate for display; the raw job name stays reachable
      // on the title attribute.
      <strong className="ax-admin-job-name" title={job.name}>
        {job.displayName || job.name}
      </strong>
    ),
  },
  { key: "schedule", header: "Schedule" },
  // Split columns: a FUTURE date under "Last run" was a lie — the next
  // scheduled run has its own honest column.
  { key: "lastRun", header: "Last run" },
  { key: "nextRun", header: "Next run", render: (job) => job.nextRun || "—" },
  {
    key: "status",
    header: "Status",
    render: (job) => <Badge tone={statusTone(job.status)}>{stateText(job.status)}</Badge>,
  },
  {
    key: "url",
    header: "Run link",
    render: (job) =>
      job.url ? (
        <a
          className="ax-admin-external-link"
          // Defense-in-depth: a schemeless job.url resolves relative to the app
          // origin and 404s (the reported dead run-link). Force an absolute URL.
          href={absoluteHost(job.url)}
          rel="noopener noreferrer"
          target="_blank"
          title="Open the backed Databricks resource URL reported by diagnostics."
        >
          Open ↗
        </a>
      ) : (
        // "—" (not a disabled button): most jobs legitimately report no URL,
        // and a dead control would violate the no-dead-controls law.
        <span title="No backed Databricks resource URL was reported for this row.">—</span>
      ),
  },
];

function ScheduledJobs({ jobs, hydrating, emptyMessage }) {
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle={jobs.length ? "Backed scheduled-job inventory" : "Scheduled-job inventory"}
      title="Scheduled jobs"
    >
      <DataTable
        caption="Scheduled jobs reported by runtime diagnostics"
        className="ax-admin-jobs-table"
        columns={JOB_COLUMNS}
        // While diagnostics hydrate, show skeleton rows — an "Unavailable"
        // wall during a background warm-up reads as a broken product.
        loading={hydrating && !jobs.length}
        emptyState={
          <UnavailableState
            reason={emptyMessage || "No backed scheduled-job inventory is available yet."}
            title="No scheduled jobs reported"
          />
        }
        rows={jobs}
      />
    </SectionCard>
  );
}

function ActivityFeed({ events, hydrating }) {
  return (
    <SectionCard
      className="ax-admin-card"
      subtitle="Visibility-scoped governance activity from the audit stream — internal bookkeeping rows are filtered server-side"
      title="Recent admin activity"
    >
      {!events.length && hydrating ? (
        <LoadingState label="Loading admin activity" variant="card" />
      ) : events.length ? (
        <ul aria-label="Recent admin activity" className="ax-admin-activity-list">
          {events.map((event) => (
            <li key={event.id}>
              <b aria-hidden="true">{(event.title || "?").charAt(0).toUpperCase()}</b>
              <div className="ax-admin-activity-copy">
                <strong>{event.title}</strong>
                <span className="ax-admin-activity-detail">
                  {/* Cross-linking LAW: asset mentions and actors are real
                      anchors, never raw text. Non-FQN detail stays text. */}
                  {looksLikeAssetFqn(event.detail) ? (
                    <EntityChip appearance="inline" entity={{ kind: "asset", fqn: event.detail }} />
                  ) : (
                    event.detail || event.status || "No detail recorded"
                  )}
                  {event.actorEmail ? (
                    <EntityChip
                      appearance="inline"
                      className="ax-admin-activity-actor"
                      entity={{ kind: "owner", id: event.actorEmail }}
                    />
                  ) : null}
                </span>
              </div>
              <time dateTime={event.createdAt || undefined}>{humanTimestamp(event.createdAt)}</time>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          body="No governance activity has been recorded in the audit stream yet."
          title="No recent admin activity"
        />
      )}
    </SectionCard>
  );
}

export function OperationsTab({ dashboard, jobs, activity, hydrating, jobsEmptyMessage }) {
  return (
    <div className="ax-admin-tab-body" id="ax-admin-panel-operations" role="tabpanel">
      <RuntimeSummary dashboard={dashboard} hydrating={hydrating} />
      <ScheduledJobs emptyMessage={jobsEmptyMessage} hydrating={hydrating} jobs={jobs} />
      <ActivityFeed events={activity} hydrating={hydrating} />
    </div>
  );
}

export default OperationsTab;
