import { Link } from "react-router-dom";
import { EntityChip, SectionCard, hrefForRef } from "../../../components/system";
import { relativeTimeLabel } from "../format.js";

/*
 * GovernanceCards (Wave C2) — critical data elements, open governance
 * requests, and the audit activity stream. Every asset / CDE / work-item /
 * audit-event mention is an EntityChip anchor (cross-linking LAW): CDEs land
 * on the Glossary CDE tab, requests land on the Stewardship item, events
 * land on their Evidence ledger row.
 */

export function CdeCard({ cdes, liveEvidence }) {
  return (
    <SectionCard
      className="ax-home-cde-card"
      title="Critical data elements"
      subtitle={liveEvidence ? "Backed CDE registry rows" : "CDE rows unavailable until live evidence is returned"}
      tooltip="CDE rows require backed registry data or asset-level critical-element metadata."
      actions={
        <Link className="ax-home-link" to={hrefForRef({ surface: "glossary", params: { tab: "cdes" } })}>
          View all
        </Link>
      }
    >
      <div className="ax-home-cde-grid">
        {cdes.map((item) => (
          <article className="ax-home-cde" key={item.id || item.name}>
            <header>
              <EntityChip
                appearance="inline"
                entity={{ kind: "cde", id: item.id, label: item.name }}
              />
              {item.sox ? <em className="ax-home-cde-flag">SOX</em> : null}
            </header>
            {item.assetFqn ? (
              <EntityChip
                appearance="inline"
                className="ax-home-cde-asset"
                entity={{ kind: "asset", fqn: item.assetFqn }}
              />
            ) : null}
            <footer>
              {item.owner ? (
                <EntityChip
                  appearance="inline"
                  entity={{ kind: "owner", email: item.owner, label: item.owner }}
                />
              ) : (
                <span className="ax-home-muted">Owner unavailable</span>
              )}
              <i>{item.status || "Status unavailable"}</i>
            </footer>
          </article>
        ))}
        {!cdes.length ? (
          <p className="ax-home-inline-unavailable">
            No assets are tagged as Critical Data Elements yet. Flag an asset as a CDE to build the registry.
          </p>
        ) : null}
      </div>
    </SectionCard>
  );
}

export function RequestsCard({ requests, openCount }) {
  return (
    <SectionCard
      className="ax-home-requests-card"
      title="Open governance requests"
      subtitle={
        openCount === null
          ? "Governance request source is unavailable"
          : `${openCount.toLocaleString()} open in the stewardship queue`
      }
      tooltip="Pending governance change requests from the governed workflow store."
      actions={
        <Link className="ax-home-link" to={hrefForRef({ surface: "stewardship" })}>
          Open queue
        </Link>
      }
    >
      <ul className="ax-home-request-list">
        {requests.slice(0, 5).map((request) => (
          <li key={request.id || request.assetFqn}>
            {request.id ? (
              <EntityChip
                appearance="inline"
                entity={{ kind: "request", id: request.id, label: request.summary }}
              />
            ) : (
              <span>{request.summary}</span>
            )}
            <span className="ax-home-request-meta">
              {request.assetFqn ? (
                <EntityChip appearance="inline" entity={{ kind: "asset", fqn: request.assetFqn }} />
              ) : null}
              {request.requestedBy ? (
                <EntityChip
                  appearance="inline"
                  entity={{ kind: "owner", email: request.requestedBy, label: request.requestedBy }}
                />
              ) : null}
              <em>{relativeTimeLabel(request.createdAt)}</em>
            </span>
          </li>
        ))}
        {!requests.length ? (
          <p className="ax-home-inline-unavailable">
            {openCount === null
              ? "Governance requests are unavailable for the current visibility scope."
              : "No open governance requests right now."}
          </p>
        ) : null}
      </ul>
    </SectionCard>
  );
}

export function ActivityCard({ events, liveEvidence }) {
  return (
    <SectionCard
      className="ax-home-activity-card"
      title="Activity stream"
      subtitle={
        liveEvidence
          ? "Live audit log · permission-filtered"
          : "Audit events unavailable until live evidence is returned"
      }
      tooltip="Recent activity uses audit events returned by the command-center API; each row links to its evidence ledger entry."
    >
      <ul className="ax-home-activity-list">
        {events.map((event) => (
          <li className={`tone-${event.tone}`} key={event.id}>
            <b aria-hidden="true" />
            <span>
              <span className="ax-home-activity-line">
                {event.actor ? (
                  <EntityChip
                    appearance="inline"
                    entity={{ kind: "owner", email: event.actor, label: event.actor }}
                  />
                ) : null}{" "}
                {/* Only link when the row carries a real audit id — the
                    governance-summary feed's store eventIds live in a
                    different id space than the audit stream, and a link to
                    "Audit event not found" is worse than plain text (final
                    verifier BLOCK-B). The backend join of displayAuditId
                    onto summary activity rows has landed: format.js
                    eventRows emits the (format-checked) field, and rows
                    without one stay plain text. */}
                {event.displayAuditId ? (
                  <EntityChip
                    appearance="inline"
                    entity={{ kind: "event", id: event.displayAuditId, label: event.title }}
                  />
                ) : (
                  event.title
                )}
              </span>
              {event.detail ? (
                /^[\w-]+\.[\w-]+\.[\w-]+$/.test(event.detail) ? (
                  <EntityChip
                    appearance="inline"
                    className="ax-home-activity-target"
                    entity={{ kind: "asset", fqn: event.detail }}
                  />
                ) : (
                  <small>{event.detail}</small>
                )
              ) : null}
              <em>{event.time}</em>
            </span>
          </li>
        ))}
        {!events.length ? (
          <p className="ax-home-inline-unavailable">
            No recent governance activity is available for the current visibility scope.
          </p>
        ) : null}
      </ul>
    </SectionCard>
  );
}
