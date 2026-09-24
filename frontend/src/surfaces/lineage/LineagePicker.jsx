import "./lineage.css";
import { useMemo } from "react";
import { EntityChip, PageShell } from "../../components/system";
import { LineageCanvasV2 } from "../../components/lineage-v2/LineageCanvasV2";
import { useLineageGraphV2 } from "../../components/lineage-v2/useLineageGraphV2";
import { usePaletteSearch } from "../../hooks/usePaletteSearch";
import { useLineageRecommendations } from "../../hooks/useLineageRecommendations";
import { readRecentLineage } from "../../lib/prefs";
import { useAtlasNavigate } from "../../nav/useAtlasNavigate";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { compactCount } from "./lineagePresentation.js";

/*
 * surfaces/lineage/LineagePicker.jsx — the Lineage Atlas springboard
 * (experience-polish wave).
 *
 * COHESION law: /lineage/<fqn> is canonical; bare /lineage is the deliberate
 * home screen — never a silent redirect. This rebuild turns the old
 * search-box-over-dead-space landing into a product surface that SELLS the
 * feature: a hero search, ranked high-lineage assets as rich cards
 * (edge counts, direction split, domain + owner chips), a live featured
 * mini-graph of the top asset (the lineage-v2 canvas in a compact read-only
 * mode), a prefs-backed "recent journeys" strip, and a "how lineage works"
 * explainer. Every asset mention is a real EntityChip `<a href>` per the
 * cross-linking law.
 */

const PICKER_PARAMS_SCHEMA = {
  q: { type: "string" },
};

function assetPathMeta(candidate) {
  return (
    [candidate.catalogName, candidate.schemaName].filter(Boolean).join(" / ") ||
    candidate.fqn ||
    ""
  );
}

// Placeholder tokens the backend emits when a value is genuinely unknown —
// we suppress them so a card shows what we know, not a hyphen.
const PLACEHOLDERS = new Set(["", "—", "-", "–", "n/a", "unknown", "unassigned", "unavailable", "none", "null"]);
function meaningful(value) {
  const text = String(value ?? "").trim();
  return text && !PLACEHOLDERS.has(text.toLowerCase()) ? text : "";
}

/**
 * A ranked high-lineage asset rendered as a rich card. The title is a real
 * lineage link; domain + owner are their own EntityChips. The whole card is
 * click-navigable (guarding nested-anchor clicks) so the big target opens the
 * graph while middle-click/copy still work on the inner links.
 */
function RankedAssetCard({ item, onOpen, rank }) {
  const domain = meaningful(item.domain);
  const owner = meaningful(item.owner);
  const objectType = meaningful(item.objectType);
  const certification = meaningful(item.certification);
  const sensitivity = meaningful(item.sensitivity);
  const up = Number(item.upstreamCount || 0);
  const down = Number(item.downstreamCount || 0);
  // L12 honesty: a non-numeric edgeCount renders "—" (via compactCount),
  // never a synthesized total. The split bar still uses the numeric up/down.
  const totalLabel = compactCount(item.edgeCount);
  const denom = up + down;
  const upPct = denom ? Math.round((up / denom) * 100) : 0;

  const handleClick = (event) => {
    if (event.target.closest?.("a")) return; // inner links own their clicks
    onOpen(item.fqn);
  };

  return (
    <div
      className="ga-lin-rank-card"
      onClick={handleClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          if (/** @type {HTMLElement} */ (event.target).closest?.("a")) return;
          event.preventDefault();
          onOpen(item.fqn);
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className="ga-lin-rank-badge" aria-hidden="true">{rank}</div>
      <div className="ga-lin-rank-body">
        <div className="ga-lin-rank-head">
          <EntityChip
            appearance="inline"
            className="ga-lin-rank-title"
            entity={{ kind: "lineage", fqn: item.fqn, label: item.name || item.fqn }}
          />
          {objectType ? <span className="ga-lin-rank-type">{objectType}</span> : null}
        </div>
        <div className="ga-lin-rank-path">{assetPathMeta(item)}</div>
        <div className="ga-lin-rank-edges">
          <span className="ga-lin-rank-edgecount">
            <strong>{totalLabel}</strong> edges
          </span>
          <span className="ga-lin-rank-split">
            <span className="ga-lin-rank-up">{compactCount(up)} up</span>
            <span className="ga-lin-rank-splitbar" aria-hidden="true">
              <span style={{ width: `${upPct}%` }} />
            </span>
            <span className="ga-lin-rank-down">{compactCount(down)} down</span>
          </span>
        </div>
        {(domain || owner || certification || sensitivity) ? (
          <div className="ga-lin-rank-chips">
            {domain ? (
              <EntityChip appearance="chip" entity={{ kind: "domain", name: domain, label: domain }} />
            ) : null}
            {owner ? (
              <EntityChip appearance="chip" entity={{ kind: "owner", email: owner, label: owner }} />
            ) : null}
            {certification ? <span className="ga-lin-rank-tag tone-good">{certification}</span> : null}
            {sensitivity ? <span className="ga-lin-rank-tag tone-warn">{sensitivity}</span> : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Live featured mini-graph of the top-ranked asset, rendered with the real
 * lineage-v2 canvas in a compact read-only mode. Clicking any node opens its
 * full lineage. The backend pre-warms the top recommendations, so this is
 * designed assuming a warm cache.
 */
function FeaturedPreview({ fqn, label, onOpen }) {
  const graph = useLineageGraphV2(fqn || "", { enabled: Boolean(fqn) });
  if (!fqn) return null;
  return (
    <aside className="ga-lin-feature">
      <div className="ga-lineage-v2-section-title">
        <span>Featured graph</span>
        <small>Live preview · click to explore</small>
      </div>
      <div className="ga-lin-feature-frame">
        <LineageCanvasV2
          error={graph.error}
          focusId={fqn}
          graph={graph}
          hydrating={graph.hydrating}
          minZoom={0.2}
          onFocusChange={(nextFqn) => onOpen(nextFqn || fqn)}
          onRetry={graph.refresh}
          warming={graph.warming}
        />
      </div>
      <button className="ga-lin-feature-open" onClick={() => onOpen(fqn)} type="button">
        Open {label || fqn} lineage →
      </button>
    </aside>
  );
}

const HOW_IT_WORKS = [
  {
    title: "Anchor on an asset",
    body: "Pick any governed table or view. Atlas walks Unity Catalog lineage outward from that focus.",
  },
  {
    title: "Follow upstream & downstream",
    body: "Teal edges trace provenance; blue edges trace impact. Filter by direction or node type to cut noise.",
  },
  {
    title: "Prove impact",
    body: "The Impact Inspector packs owners, quality, access and Databricks evidence into an exportable brief.",
  },
];

export function LineagePicker() {
  const [params, setParams] = useSurfaceParams(PICKER_PARAMS_SCHEMA);
  const navigate = useAtlasNavigate();
  const query = params.q || "";
  const search = usePaletteSearch(query);
  const recommendations = useLineageRecommendations({ enabled: true, limit: 8 });
  const items = (recommendations.items || [])
    .filter((item) => item.fqn)
    .sort((left, right) => Number(right.edgeCount || 0) - Number(left.edgeCount || 0));
  const recommendationsDegraded = Boolean(
    recommendations.degraded ||
      recommendations.authoritative === false ||
      String(recommendations.visibilityScope || "").includes("workspace-app-principal"),
  );
  const topAsset = items[0] || null;
  const recentFqns = useMemo(() => {
    const topSet = new Set(items.map((item) => item.fqn));
    return readRecentLineage()
      .filter((fqn) => fqn && !topSet.has(fqn))
      .slice(0, 6);
  }, [items]);

  const openLineage = (fqn) => {
    if (fqn) navigate({ kind: "lineage", fqn });
  };

  return (
    <PageShell
      className="ga-lin-page"
      eyebrow="Knowledge & Proof"
      title="Lineage Atlas"
      subtitle="Trace any governed asset from its upstream sources through to the downstream consumers you can see, with owners, quality and access evidence one click away."
    >
      <div className="ga-lin-home">
        <div className="ga-lin-home-main">
          <div className="ga-lin-picker-search">
            <label className="ga-lin-picker-label" htmlFor="ga-lin-picker-input">
              Search for an asset to open its lineage
            </label>
            <input
              autoFocus
              className="ga-lin-search-input"
              id="ga-lin-picker-input"
              onChange={(event) => setParams({ q: event.target.value })}
              placeholder="Search tables, views, catalogs…"
              type="search"
              value={query}
            />
            {query.trim() || search.searching || search.searchError ? (
              <div className="ga-lin-picker-results">
                {search.searching ? (
                  <div className="ga-lin-picker-status" role="status">Searching assets…</div>
                ) : search.searchError ? (
                  <div className="ga-lin-picker-status">{search.searchError}</div>
                ) : search.assets.length ? (
                  search.assets.slice(0, 8).map((candidate) => (
                    <EntityChip
                      appearance="row"
                      className="ga-lin-rec-row"
                      entity={{
                        kind: "lineage",
                        fqn: candidate.fqn,
                        label: candidate.name || candidate.fqn,
                        meta: assetPathMeta(candidate),
                      }}
                      key={candidate.fqn}
                    />
                  ))
                ) : (
                  <div className="ga-lin-picker-status">No matching assets.</div>
                )}
              </div>
            ) : null}
          </div>

          <div className="ga-lin-ranked">
            <div className="ga-lineage-v2-section-title">
              <span>High-lineage assets</span>
              <small>
                {recommendationsDegraded
                  ? "Ranked from degraded Databricks lineage evidence"
                  : "Ranked by connectivity in the lineage you can see"}
              </small>
            </div>
            {recommendations.loading ? (
              <div className="ga-lin-rank-grid">
                {[0, 1, 2, 3].map((i) => (
                  <div className="ga-lin-rank-card is-skeleton" key={i} aria-hidden="true" />
                ))}
              </div>
            ) : recommendations.error ? (
              <p className="ga-lineage-v2-rail-empty">{recommendations.error}</p>
            ) : items.length ? (
              <>
                {recommendationsDegraded ? (
                  <p className="ga-lineage-v2-rail-empty">
                    Each candidate is verified openable for you, but edge counts include
                    assets outside your visible catalogs.
                  </p>
                ) : null}
                <div className="ga-lin-rank-grid">
                  {items.slice(0, 6).map((item, index) => (
                    <RankedAssetCard item={item} key={item.fqn} onOpen={openLineage} rank={index + 1} />
                  ))}
                </div>
              </>
            ) : (
              <p className="ga-lineage-v2-rail-empty">
                No ranked high-lineage assets were returned for the current visibility scope.
              </p>
            )}
          </div>

          {recentFqns.length ? (
            <div className="ga-lin-recent">
              <div className="ga-lineage-v2-section-title">
                <span>Recent journeys</span>
                <small>Lineage graphs you opened before</small>
              </div>
              <div className="ga-lin-recent-rows">
                {recentFqns.map((fqn) => (
                  <EntityChip
                    appearance="row"
                    className="ga-lin-rec-row"
                    entity={{
                      kind: "lineage",
                      fqn,
                      label: fqn.split(".").pop() || fqn,
                      meta: fqn.split(".").slice(0, 2).join(" / "),
                    }}
                    key={fqn}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {topAsset ? (
          <FeaturedPreview fqn={topAsset.fqn} label={topAsset.name} onOpen={openLineage} />
        ) : null}
      </div>

      <div className="ga-lin-how">
        {HOW_IT_WORKS.map((step, index) => (
          <div className="ga-lin-how-step" key={step.title}>
            <span className="ga-lin-how-num" aria-hidden="true">{index + 1}</span>
            <div>
              <strong>{step.title}</strong>
              <p>{step.body}</p>
            </div>
          </div>
        ))}
      </div>
    </PageShell>
  );
}

export default LineagePicker;
