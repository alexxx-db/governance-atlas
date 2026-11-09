import "../asset.css";
import {
  Badge,
  EmptyState,
  EntityChip,
  LoadingState,
  SectionCard,
} from "../../../components/system";
import { formatUtcInstant, priorityLabel, priorityTone } from "../format";

/*
 * Activity tab — the rich projection (teardown P1-7 killed the poorest one):
 * actor as an owner chip, humanized title (server humanizes slugs — Wave A4),
 * priority badge, ABSOLUTE UTC time with ISO tooltip, and stable deep links:
 * AUD-<hex8> chips → /evidence?event=…, task rows → /stewardship?item=….
 */

function ActivityRow({ row }) {
  const actor = String(row.actorEmail || row.createdBy || "").trim();
  const when = formatUtcInstant(row.createdAt);
  const priority = priorityLabel(row.priority);
  const status = String(row.status || "").trim();
  const auditId = String(row.displayAuditId || "").trim();
  const taskId = String(row.taskId || "").trim();

  return (
    <li className="ax-asset-activity-row">
      <div className="ax-asset-activity-main">
        <span className="ax-asset-activity-title">{row.title || "Activity"}</span>
        {priority ? <Badge size="sm" tone={priorityTone(row.priority)}>{priority}</Badge> : null}
        {status ? <Badge size="sm" status={status} /> : null}
      </div>
      {row.detail ? <p className="ax-asset-activity-detail">{row.detail}</p> : null}
      <div className="ax-asset-activity-meta">
        {actor ? (
          <EntityChip appearance="inline" entity={{ kind: "owner", email: actor, label: actor }} />
        ) : null}
        {when ? (
          <time dateTime={when.iso} title={when.iso}>
            {when.display}
          </time>
        ) : null}
        {auditId ? (
          <EntityChip appearance="inline" entity={{ kind: "event", id: auditId, label: auditId }} />
        ) : null}
        {taskId ? (
          <EntityChip
            appearance="inline"
            entity={{ kind: "request", id: taskId, label: `Task ${taskId}` }}
          />
        ) : null}
      </div>
    </li>
  );
}

export function ActivityTab({ a360, a360Loading }) {
  const rows = Array.isArray(a360?.activity) ? a360.activity : [];
  return (
    <SectionCard title="Activity" subtitle="Governance events and audited changes for this asset.">
      {!a360 && a360Loading ? (
        <LoadingState variant="card" lines={4} />
      ) : rows.length ? (
        <ul className="ax-asset-activity-list">
          {rows.map((row, index) => (
            <ActivityRow key={row.id || row.displayAuditId || index} row={row} />
          ))}
        </ul>
      ) : (
        <EmptyState
          title="No recorded activity"
          body="Governance events for this asset will appear here as they happen."
        />
      )}
    </SectionCard>
  );
}

export default ActivityTab;
