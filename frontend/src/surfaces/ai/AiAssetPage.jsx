/*
 * surfaces/ai/AiAssetPage.jsx: AI Asset 360 (/ai/assets/:entityId,
 * docs/ai_extension/DESIGN.md 10). Overview | Controls | History | Usage.
 *
 * Every side of the declared-versus-observed comparison carries its own
 * provenance: the observation's collector/run/time and the intake record's
 * ingest source/run. Differences are highlighted only when both sides have a
 * value. The relationship graph and usage are later-release features and say
 * so; they never show placeholder numbers.
 */
import "./ai.css";
import { Link } from "react-router-dom";

import { Badge, EmptyState, LoadingState, PageShell, SectionCard, TabStrip, UnavailableState } from "../../components/system";
import { useAiAsset } from "../../hooks/useAiGovernance";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import {
  DASH,
  controlDetail,
  controlTone,
  findingTypeLabel,
  formatTimestamp,
  isSteward,
  kindLabel,
  postureTone,
  reconciliationLabel,
  reconciliationTone,
  severityTone,
  valueOrDash,
} from "./aiPresentation";

const PARAMS_SCHEMA = { tab: { type: "string" } };
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "controls", label: "Controls" },
  { key: "history", label: "History" },
  { key: "usage", label: "Usage" },
];

function ProvenanceChips({ items }) {
  return (
    <div className="ga-ai-chips" aria-label="Provenance">
      {items
        .filter(([, value]) => value)
        .map(([label, value]) => (
          <span className="ga-ai-chip" key={label}>
            <span className="ga-ai-muted">{label}</span> {value}
          </span>
        ))}
    </div>
  );
}

function Overview({ asset }) {
  const declared = asset.declared;
  const observedProvenance = asset.provenance || {};
  return (
    <>
      <div className="ga-ai-compare">
        <SectionCard title="Declared (intake)" subtitle={declared ? `${declared.intakeId}: ${declared.title}` : "No linked intake record"}>
          {declared ? (
            <ProvenanceChips
              items={[
                ["Source", declared.provenance?.ingestSource],
                ["Import", declared.provenance?.ingestRunId],
                ["Updated", formatTimestamp(declared.provenance?.updatedAt)],
                ["Link", declared.authority === "override" ? "Steward confirmed" : declared.via === "parent" ? "Via parent endpoint" : "Intake tag"],
                ["Class", declared.provenance?.provenanceClass === "sample" ? "Sample" : ""],
              ]}
            />
          ) : (
            <p className="ga-ai-muted">This asset is not linked to an intake record. A steward can confirm a match from its finding.</p>
          )}
        </SectionCard>
        <SectionCard title="Observed (platform)" subtitle={`${kindLabel(asset.entityKind)} · ${asset.sourceEntityId}`}>
          <ProvenanceChips
            items={[
              ["Source", observedProvenance.sourceSystem],
              ["Collector", `${observedProvenance.collector || DASH} ${observedProvenance.collectorVersion || ""}`.trim()],
              ["Run", observedProvenance.runId],
              ["Observed", formatTimestamp(observedProvenance.observedAt)],
              ["Class", observedProvenance.provenanceClass === "sample" ? "Sample" : ""],
            ]}
          />
        </SectionCard>
      </div>
      <SectionCard title="Declared versus observed">
        <table className="ga-ai-diff">
          <caption className="ga-ai-visually-hidden">Declared versus observed field comparison</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Declared</th>
              <th scope="col">Observed</th>
            </tr>
          </thead>
          <tbody>
            {(asset.diff || []).map((row) => (
              <tr className={row.differs ? "is-different" : ""} key={row.field}>
                <td>
                  {row.field.replace(/_/g, " ")}
                  {row.differs ? <span className="ga-ai-visually-hidden"> (differs)</span> : null}
                </td>
                <td>{valueOrDash(row.declared)}</td>
                <td>{valueOrDash(row.observed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
      <SectionCard title="Findings" subtitle={`${(asset.findings || []).length} finding(s) on this asset`}>
        {(asset.findings || []).length ? (
          <ul className="ga-ai-list">
            {asset.findings.map((finding) => (
              <li key={finding.findingId}>
                <Badge size="sm" tone={severityTone(finding.severity)}>
                  {finding.severity}
                </Badge>{" "}
                {findingTypeLabel(finding.findingType)} · {finding.state}
                {finding.evidence?.reason ? <span className="ga-ai-muted"> · {finding.evidence.reason}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="ga-ai-muted">No findings reference this asset.</p>
        )}
      </SectionCard>
      <SectionCard title="Relationships" subtitle="Observed and declared edges. The relationship graph is available in a later release.">
        {(asset.relationships || []).length ? (
          <ul className="ga-ai-list">
            {asset.relationships.map((rel) => (
              <li key={`${rel.relationship_kind}-${rel.source_entity_id}-${rel.target_entity_id}`}>
                {rel.relationship_kind}: {rel.source_entity_id} → {rel.target_entity_id}{" "}
                <span className="ga-ai-muted">({rel.authority_source})</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="ga-ai-muted">No relationships recorded for this asset.</p>
        )}
      </SectionCard>
    </>
  );
}

function Controls({ asset }) {
  const controls = asset.controls || [];
  if (!controls.length) {
    return <EmptyState title="No controls apply" body="None of the Phase 1 controls apply to this kind of asset." />;
  }
  return (
    <SectionCard title="Controls" subtitle={`From run ${controls[0]?.runId || DASH}. Unknown results are excluded from posture.`}>
      <table className="ga-ai-diff">
        <thead>
          <tr>
            <th scope="col">Control</th>
            <th scope="col">Result</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {controls.map((control) => (
            <tr key={control.controlId}>
              <td>
                <strong>{control.controlId}</strong> {control.title}
              </td>
              <td>
                <Badge size="sm" tone={controlTone(control.status)}>
                  {control.status === "unknown" ? "Unknown" : control.status}
                </Badge>
              </td>
              <td>{controlDetail(control)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  );
}

function History({ asset }) {
  const events = asset.history || [];
  if (!events.length) return <EmptyState title="No history yet" body="No governance events reference this asset or its findings." />;
  return (
    <SectionCard title="History" subtitle="Registry and finding events, newest first">
      <ol className="ga-ai-timeline">
        {events.map((event) => (
          <li key={event.eventId}>
            <strong>{event.eventType}</strong>
            <span className="ga-ai-muted">
              {" "}
              · {formatTimestamp(event.occurredAt)} · {valueOrDash(event.actorEmail)} · {event.source}
              {event.requestId ? ` · request ${event.requestId}` : ""}
              {event.status && event.status !== "emitted" ? ` · ${event.status}` : ""}
            </span>
          </li>
        ))}
      </ol>
    </SectionCard>
  );
}

export function AiAssetPage({ entityId = "", shell = null }) {
  const [params, setParams] = useSurfaceParams(PARAMS_SCHEMA);
  const query = useAiAsset(entityId);
  const asset = query.data?.asset || null;
  const tab = TABS.some((t) => t.key === params.tab) ? params.tab : "overview";
  const notFound = query.error?.status === 404;
  const badRequest = query.error?.status === 400;

  return (
    <PageShell
      breadcrumbs={<Link to="/ai">AI Governance</Link>}
      className="ga-ai-page"
      eyebrow="AI Asset 360"
      status={notFound || badRequest ? null : query}
      subtitle={asset ? `${kindLabel(asset.entityKind)} · ${asset.sourceEntityId}` : ""}
      actions={
        asset ? (
          <span className="ga-ai-subtitle">
            {asset.reconciliationState ? (
              <Badge size="sm" tone={reconciliationTone(asset.reconciliationState)}>
                {reconciliationLabel(asset.reconciliationState)}
              </Badge>
            ) : null}
            {asset.posture ? (
              <Badge size="sm" tone={postureTone(asset.posture)}>
                Posture: {asset.posture}
              </Badge>
            ) : null}
          </span>
        ) : null
      }
      tabs={asset ? <TabStrip ariaLabel="Asset views" param={{ value: tab, set: (key) => setParams({ tab: key }) }} tabs={TABS} /> : null}
      title={asset?.name || (query.status === "loading" ? "Loading AI asset…" : "AI asset")}
    >
      {notFound || badRequest ? (
        <UnavailableState
          title="AI asset not found"
          reason={notFound ? "This asset is not in the latest completed reconciliation run. It may have been removed, or its source was unavailable." : "The asset id in this link is not valid."}
        />
      ) : !asset ? (
        query.status === "loading" ? (
          <SectionCard status="loading" title="AI asset">
            <LoadingState label="Loading AI asset" />
          </SectionCard>
        ) : null
      ) : (
        <>
          {tab === "overview" ? <Overview asset={asset} /> : null}
          {tab === "controls" ? <Controls asset={asset} /> : null}
          {tab === "history" ? <History asset={asset} /> : null}
          {tab === "usage" ? (
            <EmptyState title="Available in a later release" body="Usage and spend come from aggregated system tables in Phase 2." />
          ) : null}
          {tab === "overview" && isSteward(shell) && asset.config ? (
            <SectionCard title="Configuration (redacted)" subtitle="Allowlisted fields only. Credentials are never stored.">
              <pre className="ga-ai-config">{JSON.stringify(asset.config, null, 2)}</pre>
            </SectionCard>
          ) : null}
        </>
      )}
    </PageShell>
  );
}

export default AiAssetPage;
