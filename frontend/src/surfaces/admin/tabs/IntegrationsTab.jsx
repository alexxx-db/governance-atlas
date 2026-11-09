import { Badge, LoadingState, SectionCard, UnavailableState } from "../../../components/system";
import { stateText, statusTone } from "../adminPresentation";

/*
 * Control Center · Integrations tab (Wave C6). Connection cards (warehouse,
 * Lakeflow, identity/Unity Catalog, AI) rendered VERBATIM from the backend's
 * integration rows — the states derive from the same live probes the product
 * uses (COHESION law: no "Unavailable while it works" lies), and no
 * fabricated placeholder slots exist for products the runtime never probes.
 */

export function IntegrationsTab({ integrations, hydrating }) {
  return (
    <div className="ax-admin-tab-body" id="ax-admin-panel-integrations" role="tabpanel">
      <SectionCard
        className="ax-admin-card"
        subtitle="Connection states from the same live probes the product uses — unsupported integrations stay honestly unavailable with the API's reason"
        title="Integrations"
      >
        {!integrations.length && hydrating ? (
          <LoadingState label="Loading integrations" variant="card" />
        ) : integrations.length ? (
          <div aria-label="Integration connections" className="ax-admin-integration-grid" role="list">
            {integrations.map((item) => (
              <article className="ax-admin-integration-card" key={item.id} role="listitem">
                <header>
                  <strong>{item.label}</strong>
                  <Badge tone={statusTone(item.status)}>{stateText(item.status)}</Badge>
                </header>
                <span className="ax-admin-integration-sub">{item.subtitle}</span>
                {/* The API's own reason string — never a synthesized excuse. */}
                {item.reason && item.reason !== item.subtitle ? (
                  <p className="ax-admin-integration-reason">{item.reason}</p>
                ) : null}
                {item.url ? (
                  <a
                    className="ax-admin-external-link"
                    href={item.url}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    Open in workspace ↗
                  </a>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <UnavailableState
            reason="Runtime diagnostics did not report any integration rows for this workspace."
            title="Runtime signal unavailable"
          />
        )}
      </SectionCard>
    </div>
  );
}

export default IntegrationsTab;
