import "./lineage.css";
import { EntityChip } from "../../components/system";
import { compactCount } from "./lineagePresentation.js";

/*
 * Ranked high-lineage candidates (system.access.table_lineage edge counts),
 * shared by the bare-/lineage picker and the focused page's honest
 * zero-edge state. Wave C7: each candidate is now an EntityChip — a REAL
 * `<a href="/lineage/<fqn>">` (middle-clickable, copyable) instead of the
 * legacy bespoke button row, per the cross-linking law.
 */
export function LineageRecommendations({
  recommendations,
  loading,
  error,
  compact = false,
  degraded = false,
}) {
  if (loading) {
    return <p className="ax-lineage-v2-rail-empty">Loading ranked lineage assets from system.access.table_lineage...</p>;
  }
  if (error) {
    return <p className="ax-lineage-v2-rail-empty">{error}</p>;
  }
  if (!recommendations?.length) {
    return (
      <p className="ax-lineage-v2-rail-empty">
        No ranked high-lineage assets were returned for the current visibility scope.
      </p>
    );
  }
  return (
    <div className={`ax-lin-recommendations ${compact ? "is-compact" : ""}`.trim()}>
      {degraded ? (
        // Persona audit P1 (preserved from the legacy workspace): internal
        // scope tokens ("actor-openable-candidate-aggregate" etc.) must not
        // leak into this caption. Human copy only.
        <p className="ax-lineage-v2-rail-empty">
          Ranked from degraded Databricks lineage evidence. Each candidate asset is
          verified openable for you, but edge counts include assets outside your
          visible catalogs.
        </p>
      ) : null}
      {recommendations.slice(0, compact ? 4 : 6).map((item) => (
        <EntityChip
          appearance="row"
          className="ax-lin-rec-row"
          entity={{
            kind: "lineage",
            fqn: item.fqn,
            label: item.name,
            meta: `${[item.catalogName, item.schemaName].filter(Boolean).join(" / ") || item.fqn} · ${compactCount(item.edgeCount)} edges · ${compactCount(item.upstreamCount)} up / ${compactCount(item.downstreamCount)} down`,
          }}
          key={item.fqn}
        />
      ))}
    </div>
  );
}

export default LineageRecommendations;
