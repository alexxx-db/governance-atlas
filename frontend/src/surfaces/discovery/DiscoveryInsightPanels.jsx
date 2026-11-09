import "./discovery.css";
import { Button, EntityChip, SectionCard } from "../../components/system";
import { coveragePercent } from "./discoveryPresentation";

/*
 * Discover accelerator band (Wave C1 port of the legacy bottom panels):
 * Governance Views (live saved-view drills with real client-side counts),
 * High Coverage Assets, and the Axiom AI recommendations card (evidence-
 * backed only — non-authoritative responses are rejected upstream in
 * useDiscoveryAi and never rendered).
 */

const GOVERNANCE_VIEWS = [
  { label: "Needs Owner", view: "Needs owner" },
  { label: "Needs Certification", view: "Needs certification" },
  { label: "Certified Data", view: "Certified" },
  { label: "High Coverage Assets", view: "High coverage" },
];

// Degraded-only fallback: DiscoveryPage renders the SERVER `facets.views`
// counts (authoritative `view_matches` over the full estate). This client
// recompute runs ONLY when the server omits the views facet, so its predicates
// MUST mirror axiom/services/assets.py `view_matches` exactly — otherwise the
// count drifts from what clicking the view actually returns. (Audit B2/B4: the
// old code counted Certified leniently — certified+trusted+draft = 47 vs the
// strict 44 — and used a High-coverage threshold of 80 vs the server's 75.)
export function savedViewCountsFor(assets = []) {
  const counts = {
    "All assets": assets.length,
    "Needs attention": 0,
    "Needs owner": 0,
    "Needs certification": 0,
    Certified: 0,
    "High coverage": 0,
  };
  for (const entry of assets) {
    const certification = String(entry?.certification || "").trim();
    const noOwner = !entry?.owners?.length;
    const isCertified = certification.toLowerCase() === "certified"; // strict, matches semantics.is_certified
    const needsCertification = certification === "Unassigned"; // server: == "Unassigned" only
    const score = Number(entry?.coverageScore || 0);
    const needsAttention =
      String(entry?.governanceStatus || "") === "Needs Work" || Number(entry?.openRequests || 0) > 0;
    if (noOwner) counts["Needs owner"] += 1;
    if (needsCertification) counts["Needs certification"] += 1;
    if (isCertified) counts.Certified += 1;
    if (score >= 75) counts["High coverage"] += 1;
    if (needsAttention) counts["Needs attention"] += 1;
  }
  return counts;
}

export function DiscoveryInsightPanels({
  assets = [],
  savedViewCounts = {},
  onApplyView,
  onPreview,
  ai,
  onAskAxiom,
  axiomAiAvailable = true,
  axiomAiUnavailableReason = "",
}) {
  const highCoverageAssets = [...assets]
    .filter((asset) => coveragePercent(asset) !== null)
    .sort((a, b) => (coveragePercent(b) || 0) - (coveragePercent(a) || 0))
    .slice(0, 3);

  return (
    <div className="ax-disc-insights">
      <SectionCard
        actions={
          <Button onClick={() => onApplyView?.([])} title="Clear live governance filters" variant="tertiary">
            Clear
          </Button>
        }
        title="Governance Views"
      >
        <div className="ax-disc-insight-list">
          {GOVERNANCE_VIEWS.map((view) => (
            <button
              key={view.label}
              onClick={() => onApplyView?.(view.view ? [view.view] : [])}
              type="button"
            >
              <span>{view.label}</span>
              <small>{Number(savedViewCounts[view.view] || 0).toLocaleString()} visible</small>
              <span aria-hidden="true">›</span>
            </button>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        actions={
          <Button
            onClick={() => onApplyView?.(["High coverage"])}
            title="Apply the live high-coverage filter"
            variant="tertiary"
          >
            Filter all
          </Button>
        }
        title="High Coverage Assets"
      >
        {highCoverageAssets.length ? (
          <div className="ax-disc-insight-list">
            {highCoverageAssets.map((asset) => (
              <button key={asset.fqn} onClick={() => onPreview?.(asset.fqn)} type="button">
                <span className="ax-disc-insight-asset">
                  <strong>{asset.name}</strong>
                  <small>{asset.domain && asset.domain !== "Unassigned" ? asset.domain : asset.fqn}</small>
                </span>
                <b>{coveragePercent(asset)}%</b>
              </button>
            ))}
          </div>
        ) : (
          <p className="ax-disc-support-copy">
            High-coverage assets appear after live coverage evidence is available.
          </p>
        )}
      </SectionCard>

      <SectionCard
        actions={
          <Button
            aria-label="Run Axiom AI recommendations"
            disabled={ai.loading || !axiomAiAvailable}
            onClick={() => onAskAxiom?.()}
            title={!axiomAiAvailable ? axiomAiUnavailableReason : undefined}
            variant="tertiary"
          >
            {ai.loading ? "Running" : "View all"}
          </Button>
        }
        eyebrow="Beta"
        title="Axiom AI Recommendations"
      >
        {ai.error ? <p className="ax-disc-support-copy">{ai.error}</p> : null}
        {ai.recommendations.length ? (
          <div className="ax-disc-insight-list ax-disc-ai-list">
            {ai.recommendations.slice(0, 3).map((recommendation, index) => {
              const evidence = Array.isArray(recommendation.evidence)
                ? recommendation.evidence[0]
                : null;
              const evidenceId = evidence?.id || "";
              const asset = evidenceId
                ? assets.find((candidate) => candidate.fqn === evidenceId)
                : null;
              const provider =
                recommendation.provider ||
                ai.response?.recommendationsProvider ||
                ai.response?.provider ||
                "AI";
              const authorityLabel =
                ai.response?.authoritative === false || /local-evidence|prototype/i.test(String(provider))
                  ? "Recommendation unavailable without live Genie proof"
                  : "Evidence-backed recommendation from Axiom AI";
              return (
                <div className="ax-disc-ai-recommendation" key={`${recommendation.title || "recommendation"}-${index}`}>
                  <strong>{recommendation.title || "Governance recommendation"}</strong>
                  <small>
                    {recommendation.detail ? `${authorityLabel}: ${recommendation.detail}` : authorityLabel}
                  </small>
                  <span className="ax-disc-ai-recommendation-foot">
                    {asset ? (
                      <EntityChip
                        appearance="inline"
                        entity={{ kind: "asset", fqn: asset.fqn, label: asset.name }}
                      />
                    ) : null}
                    <em>{provider}</em>
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="ax-disc-support-copy">
            {!axiomAiAvailable
              ? axiomAiUnavailableReason ||
                "Axiom AI recommendations require a configured evidence-backed endpoint."
              : ai.nonAuthoritative
                ? "Axiom AI recommendations unavailable until live evidence-backed provider returns results."
                : ai.unavailableMessage
                  ? ai.unavailableMessage
                  : ai.loading
                    ? "Axiom AI is gathering governed metadata evidence."
                    : "Run Axiom AI to generate evidence-backed recommendations for this result set."}
          </p>
        )}
      </SectionCard>
    </div>
  );
}

export default DiscoveryInsightPanels;
