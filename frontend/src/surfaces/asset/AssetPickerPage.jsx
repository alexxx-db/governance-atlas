import "./asset.css";
import { useMemo } from "react";
import { Badge, EntityChip, PageShell } from "../../components/system";
import { fetchDiscoverySearch } from "../../lib/api";
import { readRecentAssets } from "../../lib/prefs";
import { usePaletteSearch } from "../../hooks/usePaletteSearch";
import { useAxiomQuery } from "../../hooks/useAxiomQuery";
import { useSurfaceParams } from "../../nav/useSurfaceParams";

/*
 * surfaces/asset/AssetPickerPage.jsx — bare /assets (owner directive 1).
 *
 * COHESION law mirror of the bare /lineage picker: /assets/<fqn> is the
 * canonical record; bare /assets is a search-first Asset 360 picker so the
 * PERMANENT rail entry is never a dead end when no asset is in context or
 * remembered. Three ways in, all REAL <a href> anchors (EntityChip):
 *   1. Hero search over the discovery API (?q= keeps it addressable).
 *   2. Recent assets (prefs.recentAssets) — the records you last opened.
 *   3. High-signal suggestions — certified / governed assets as rich cards.
 */

// Mirrors the nav/routes.js bare-assets paramsSchema; module-level so
// useSurfaceParams normalizes it once.
const PICKER_PARAMS_SCHEMA = {
  q: { type: "string" },
};

const SUGGESTION_LIMIT = 8;

function assetPathMeta(candidate) {
  return (
    [candidate.catalog || candidate.catalogName, candidate.schema || candidate.schemaName]
      .filter(Boolean)
      .join(" / ") ||
    candidate.fqn ||
    ""
  );
}

/** Certified / governed assets — the "start here" high-signal suggestions. */
function useAssetSuggestions() {
  const result = useAxiomQuery({
    key: ["asset-picker-suggestions"],
    fetch: (signal) =>
      fetchDiscoverySearch(
        { certifications: ["Certified"], sortBy: "governance", limit: SUGGESTION_LIMIT },
        { signal },
      ),
    staleTime: 60_000,
  });
  const assets = Array.isArray(result.query.data?.assets) ? result.query.data.assets : [];
  return {
    assets: assets.filter((asset) => asset.fqn),
    loading: result.query.isPending,
    error: result.query.isError ? result.query.error?.message || "Suggestions unavailable." : "",
  };
}

function SuggestionCard({ asset }) {
  const cert = String(asset.certification || "").trim();
  return (
    <EntityChip
      appearance="row"
      className="ax-asset-picker-card"
      entity={{
        kind: "asset",
        fqn: asset.fqn,
        label: asset.name || asset.fqn,
        meta: assetPathMeta(asset),
      }}
    >
      <span className="ax-asset-picker-card-body">
        <span className="ax-asset-picker-card-name">{asset.name || asset.fqn}</span>
        <span className="ax-asset-picker-card-path">{assetPathMeta(asset)}</span>
        <span className="ax-asset-picker-card-tags">
          {cert ? <Badge tone="good">{cert}</Badge> : null}
          {asset.domain && asset.domain !== "Unassigned" ? (
            <Badge tone="info">{asset.domain}</Badge>
          ) : null}
          {asset.cde ? <Badge tone="warn">CDE</Badge> : null}
        </span>
      </span>
    </EntityChip>
  );
}

export function AssetPickerPage() {
  const [params, setParams] = useSurfaceParams(PICKER_PARAMS_SCHEMA);
  const query = params.q || "";
  const search = usePaletteSearch(query);
  const suggestions = useAssetSuggestions();
  // Recents are read once per mount (prefs are localStorage — a stable list for
  // this session); the hub writes them as the user opens records.
  const recents = useMemo(() => readRecentAssets().slice(0, 6), []);

  return (
    <PageShell
      className="ax-asset-page ax-asset-picker-page"
      eyebrow="Govern"
      title="Asset 360"
      subtitle="Pick a governed asset to open its full record — trust verdict, schema, quality, access, activity and lineage in one place."
    >
      <div className="ax-asset-picker">
        <div className="ax-asset-picker-search">
          <label className="ax-asset-picker-label" htmlFor="ax-asset-picker-input">
            Search for an asset
          </label>
          <input
            autoFocus
            className="ax-lin-search-input"
            id="ax-asset-picker-input"
            onChange={(event) => setParams({ q: event.target.value })}
            placeholder="Search catalogs, schemas, tables and views…"
            type="search"
            value={query}
          />
          <div className="ax-asset-picker-results">
            {search.searching ? (
              <div className="ax-asset-picker-status" role="status">
                Searching assets…
              </div>
            ) : search.searchError ? (
              <div className="ax-asset-picker-status">{search.searchError}</div>
            ) : search.assets.length ? (
              search.assets.slice(0, 8).map((candidate) => (
                <EntityChip
                  appearance="row"
                  className="ax-asset-picker-row"
                  entity={{
                    kind: "asset",
                    fqn: candidate.fqn,
                    label: candidate.name || candidate.fqn,
                    meta: assetPathMeta(candidate),
                  }}
                  key={candidate.fqn}
                />
              ))
            ) : query.trim() ? (
              <div className="ax-asset-picker-status">No matching assets.</div>
            ) : (
              <div className="ax-asset-picker-status">
                Start typing to find an asset, or pick a suggested record below.
              </div>
            )}
          </div>
        </div>

        {recents.length ? (
          <section className="ax-asset-picker-section">
            <div className="ax-asset-picker-section-title">
              <span>Recent assets</span>
              <small>Records you opened most recently</small>
            </div>
            <div className="ax-asset-picker-list">
              {recents.map((fqn) => (
                <EntityChip
                  appearance="row"
                  className="ax-asset-picker-row"
                  entity={{ kind: "asset", fqn, label: fqn.split(".").pop() || fqn, meta: fqn }}
                  key={fqn}
                />
              ))}
            </div>
          </section>
        ) : null}

        <section className="ax-asset-picker-section">
          <div className="ax-asset-picker-section-title">
            <span>Certified &amp; governed assets</span>
            <small>High-signal records to start from</small>
          </div>
          {suggestions.loading ? (
            <div className="ax-asset-picker-status" role="status">
              Loading suggested assets…
            </div>
          ) : suggestions.error ? (
            <div className="ax-asset-picker-status">{suggestions.error}</div>
          ) : suggestions.assets.length ? (
            <div className="ax-asset-picker-cards">
              {suggestions.assets.map((asset) => (
                <SuggestionCard asset={asset} key={asset.fqn} />
              ))}
            </div>
          ) : (
            <div className="ax-asset-picker-status">
              No certified assets to suggest yet — search above to open any record.
            </div>
          )}
        </section>
      </div>
    </PageShell>
  );
}

export default AssetPickerPage;
