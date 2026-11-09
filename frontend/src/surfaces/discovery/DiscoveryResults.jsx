import "./discovery.css";
import { Badge, Button, DataTable, EntityChip } from "../../components/system";
import { displayObjectType } from "../../lib/assetPresentation";
import {
  assetHasCdeSignal,
  assetHasPiiSignal,
  assetSourceLabel,
  certificationLabel,
  coveragePercent,
  glossaryTermLabels,
  ownerEmailForLabel,
  ownerLabelsForAsset,
  prettyOwnerName,
  sensitivityLabel,
  tagLabelsForAsset,
  usageSummary,
  workflowState,
} from "./discoveryPresentation";

/*
 * Discover result renderings (Wave C1): the system DataTable in list mode,
 * a ax-disc card grid in grid mode. One interaction contract for both:
 *   - the asset NAME is a real anchor to /assets/<fqn> (cross-linking law) —
 *     middle-click/copy-link always reach the hub;
 *   - a plain left-click anywhere on the row/card opens the ?peek= preview
 *     drawer (the legacy "single click selects, explicit action opens" UX);
 *   - owners and domains are EntityChips (owner-search grammar / domain
 *     filters), never dead text.
 */

function ownerCell(asset) {
  const owners = ownerLabelsForAsset(asset);
  if (!owners.length) return <span className="ax-disc-muted">Unassigned</span>;
  const primary = owners[0];
  return (
    <span className="ax-disc-owner-cell">
      <EntityChip
        appearance="inline"
        entity={{
          kind: "owner",
          id: ownerEmailForLabel(asset, primary),
          label: prettyOwnerName(primary),
        }}
      />
      {owners.length > 1 ? (
        <span className="ax-disc-muted" title={owners.join(", ")}>
          +{owners.length - 1}
        </span>
      ) : null}
    </span>
  );
}

function domainCell(asset) {
  if (!asset.domain || asset.domain === "Unassigned") {
    return <span className="ax-disc-muted">Unassigned</span>;
  }
  return <EntityChip appearance="inline" entity={{ kind: "domain", name: asset.domain }} />;
}

function certificationCell(asset) {
  const cert = certificationLabel(asset);
  return cert ? (
    <Badge status={cert}>{cert}</Badge>
  ) : (
    <span className="ax-disc-muted">Not certified</span>
  );
}

function coverageCell(asset, sourceAuthoritative) {
  const coverage = coveragePercent(asset);
  if (coverage === null) return <span className="ax-disc-muted">Unscored</span>;
  if (!sourceAuthoritative) return <span className="ax-disc-muted">Unavailable</span>;
  return (
    <span className="ax-disc-coverage">
      <span>{coverage}%</span>
      <span aria-hidden="true" className="ax-disc-coverage-bar">
        <i style={{ width: `${coverage}%` }} />
      </span>
    </span>
  );
}

function sensitivityCell(asset) {
  const sensitivity = sensitivityLabel(asset);
  if (!sensitivity) return <span className="ax-disc-muted">Unclassified</span>;
  const tone = /restricted|pii|personal|critical/i.test(sensitivity)
    ? "bad"
    : /confidential/i.test(sensitivity)
      ? "warn"
      : "info";
  return <Badge tone={tone}>{sensitivity}</Badge>;
}

function linkageCell(asset) {
  const isCde = assetHasCdeSignal(asset);
  const isPii = assetHasPiiSignal(asset);
  const terms = glossaryTermLabels(asset);
  if (isCde || isPii) {
    return (
      <span className="ax-disc-linkage">
        {isCde ? <Badge tone="accent">CDE</Badge> : null}
        {isPii ? <Badge tone="bad">PII</Badge> : null}
      </span>
    );
  }
  if (terms.length) {
    return (
      <span className="ax-disc-linkage" title={terms.join(", ")}>
        {terms.length} term{terms.length === 1 ? "" : "s"}
      </span>
    );
  }
  return <span className="ax-disc-muted">No links</span>;
}

function FavoriteStar({ asset, favorites, onToggleFavorite }) {
  const isFavorite = favorites.has(asset.fqn);
  return (
    <button
      aria-label={isFavorite ? "Remove local favorite" : "Add local favorite"}
      aria-pressed={isFavorite}
      className={`ax-disc-star ${isFavorite ? "is-favorite" : ""}`.trim()}
      onClick={(event) => {
        event.stopPropagation();
        onToggleFavorite?.(asset.fqn);
      }}
      title={isFavorite ? "Remove local browser favorite" : "Save local browser favorite"}
      type="button"
    >
      {isFavorite ? "★" : "☆"}
    </button>
  );
}

/**
 * @param {{ assets?: any[], loading?: boolean, density?: string, favorites?: Set<any>, onToggleFavorite?: Function, onPreview?: Function, sourceAuthoritative?: boolean, emptyState?: any }} props
 */
export function DiscoveryResultsTable({
  assets = [],
  loading = false,
  density = "comfortable",
  favorites = new Set(),
  onToggleFavorite,
  onPreview,
  sourceAuthoritative = true,
  emptyState = null,
}) {
  const columns = [
    {
      key: "name",
      header: "Asset Name",
      render: (asset) => (
        <span className="ax-disc-name">
          <strong>{asset.name}</strong>
          <small>{assetSourceLabel(asset)}</small>
        </span>
      ),
    },
    {
      key: "type",
      header: "Type",
      render: (asset) => (
        <span className="ax-disc-type">{displayObjectType(asset) || "Asset"}</span>
      ),
    },
    { key: "owner", header: "Owner", render: ownerCell },
    { key: "certification", header: "Certification", render: certificationCell },
    { key: "domain", header: "Domain", render: domainCell },
    // Audit B3: this is the weighted per-asset governance_score (coverageScore),
    // the SAME field AssetTrustHero labels "Governance score" — NOT the
    // equal-weight estate "Metadata coverage" KPI (a different formula). Label
    // it "Gov. score" so the two distinct metrics never share the word.
    {
      key: "coverage",
      header: "Gov. score",
      render: (asset) => coverageCell(asset, sourceAuthoritative),
    },
    { key: "sensitivity", header: "Sensitivity", render: sensitivityCell },
    { key: "linkage", header: "Glossary Linkage", render: linkageCell },
    {
      key: "description",
      header: "Description",
      render: (asset) => (
        <span className="ax-disc-description" title={asset.description || ""}>
          {String(asset.description || "").trim() ||
            "No description has been captured for this asset yet."}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (asset) => (
        <FavoriteStar asset={asset} favorites={favorites} onToggleFavorite={onToggleFavorite} />
      ),
    },
  ];

  return (
    <DataTable
      caption="Discovery results"
      className="ax-disc-table"
      columns={columns}
      density={density}
      emptyState={emptyState}
      loading={loading}
      // Plain left-click opens the ?peek= preview; the href (modified clicks,
      // copy-link) stays the Asset 360 hub address.
      navigate={(target) => onPreview?.(target.fqn)}
      rowKey="fqn"
      rowTarget={(asset) => ({ kind: "asset", fqn: asset.fqn })}
      rows={assets}
      stickyHeader
    />
  );
}

/**
 * @param {{ assets?: any[], favorites?: Set<any>, onToggleFavorite?: Function, onPreview?: Function, sourceAuthoritative?: boolean }} props
 */
export function DiscoveryResultsGrid({
  assets = [],
  favorites = new Set(),
  onToggleFavorite,
  onPreview,
  sourceAuthoritative = true,
}) {
  return (
    <div aria-label="Discovery results" className="ax-disc-cards" role="list">
      {assets.map((asset) => {
        const usage = usageSummary(asset);
        const workflow = workflowState(asset);
        const coverage = coveragePercent(asset);
        const tags = tagLabelsForAsset(asset).slice(0, 3);
        return (
          <article
            className="ax-disc-card"
            data-asset-fqn={asset.fqn}
            key={asset.fqn}
            onClick={(event) => {
              if (/** @type {HTMLElement} */ (event.target).closest("a, button, input, select, textarea, label")) return;
              onPreview?.(asset.fqn);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                if (event.target !== event.currentTarget) return;
                event.preventDefault();
                onPreview?.(asset.fqn);
              }
            }}
            role="listitem"
            tabIndex={0}
          >
            <header className="ax-disc-card-head">
              <span className="ax-disc-type">{displayObjectType(asset) || "Asset"}</span>
              <FavoriteStar asset={asset} favorites={favorites} onToggleFavorite={onToggleFavorite} />
            </header>
            <h3 className="ax-disc-card-title">
              {/* The name is the anchor to the hub; the card body previews. */}
              <EntityChip appearance="inline" entity={{ kind: "asset", fqn: asset.fqn, label: asset.name }} />
            </h3>
            <div className="ax-disc-card-meta">
              {domainCell(asset)}
              {ownerCell(asset)}
              {tags.length ? (
                tags.map((tag) => (
                  <Badge key={tag} size="sm" tone="muted">
                    {tag}
                  </Badge>
                ))
              ) : (
                <Badge size="sm" tone="muted">
                  Untagged
                </Badge>
              )}
              {workflow ? (
                <Badge size="sm" tone={workflow.tone}>
                  {workflow.label}
                </Badge>
              ) : null}
            </div>
            <p className="ax-disc-card-description">
              {String(asset.description || "").trim() ||
                "No description has been captured for this asset yet."}
            </p>
            <footer className="ax-disc-card-foot">
              {/* Absence of usage fields is NOT zero usage — no claim without
                  evidence in the payload. */}
              {usage.items.length ? (
                <span className="ax-disc-card-usage">{usage.items.join(" · ")}</span>
              ) : usage.none ? (
                <span className="ax-disc-card-usage ax-disc-muted">No recent usage</span>
              ) : null}
              {coverage !== null && sourceAuthoritative ? (
                <span className="ax-disc-card-coverage" title={`Governance score: ${coverage}% (weighted metadata completeness + certification + glossary)`}>
                  Gov. score {coverage}%
                </span>
              ) : null}
            </footer>
          </article>
        );
      })}
    </div>
  );
}

/** "Showing X of Y · Load more" strip shared by both layouts. */
export function DiscoveryLoadMore({ showing, total, loadingMore = false, onLoadMore }) {
  if (!total || total <= showing) return null;
  return (
    <div className="ax-disc-load-more">
      <span>
        Showing {showing.toLocaleString()} of {total.toLocaleString()} results to keep the catalog
        responsive.
      </span>
      <Button disabled={loadingMore} onClick={onLoadMore} variant="secondary">
        {loadingMore ? "Loading more results…" : "Load more results"}
      </Button>
    </div>
  );
}
