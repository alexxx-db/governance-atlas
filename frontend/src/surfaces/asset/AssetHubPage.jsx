import "./asset.css";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  EntityChip,
  PageShell,
  TabStrip,
} from "../../components/system";
import { useAsset360 } from "../../hooks/useAsset360";
import { invalidateAssetDetail, useAssetDetail } from "../../hooks/useAssetDetail";
import { useAssetMetadataEditor } from "../../hooks/useAssetMetadataEditor";
import { useLineageGraphV2 } from "../../components/lineage-v2/useLineageGraphV2";
import { useAxiomNavigate } from "../../nav/useAxiomNavigate";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { pushRecentAsset, writeLastAsset } from "../../lib/prefs";
import { AssetHeaderActions } from "./AssetHeaderActions";
import { AssetTrustHero } from "./AssetTrustHero";
import { AccessTab } from "./tabs/AccessTab";
import { ActivityTab } from "./tabs/ActivityTab";
import { ColumnsTab } from "./tabs/ColumnsTab";
import { LineageTab } from "./tabs/LineageTab";
import { OverviewTab } from "./tabs/OverviewTab";
import { QualityTab } from "./tabs/QualityTab";

/*
 * AssetHubPage — the Asset 360 hub, rebuilt on the system kit (Wave B2,
 * FRONTEND_BLUEPRINT §10 / ASSET360_TEARDOWN rebuild spec).
 *
 * Data contract: TWO PARALLEL queries — useAssetDetail(sections-per-tab) and
 * useAsset360 — replacing the old 4-stage waterfall. The 360 composite never
 * waits on detail; whichever answers first seeds the record header, and the
 * header persists across tab switches with per-section skeletons only
 * (teardown P0-2: the whole-page shell regression is structurally impossible
 * here because nothing gates the frame on a per-request pending flag).
 */

// Sections requested per tab. The canonical detail cache merges across
// requests, so switching tabs only fetches what is missing.
const SECTIONS_BY_TAB = {
  overview: ["header"],
  columns: ["header", "schema"],
  quality: ["header"],
  access: ["header"],
  activity: ["header", "activity"],
  lineage: ["header"],
};

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "columns", label: "Columns" },
  { key: "quality", label: "Quality" },
  { key: "access", label: "Access" },
  { key: "activity", label: "Activity" },
  { key: "lineage", label: "Lineage" },
];

// Matches nav/routes.js `/assets/:fqn` paramsSchema (tab + col); module-level
// constant so useSurfaceParams normalizes it once.
const PARAMS_SCHEMA = {
  tab: { type: "string", default: "overview" },
  col: { type: "string" },
};

function decodeFqnParam(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  try {
    return decodeURIComponent(value);
  } catch {
    return value; // malformed escapes degrade to the raw path segment
  }
}

/**
 * Freshness model: prefer the /360 freshness block (payload labels, split
 * fields — Wave A4); before it lands, derive an equivalent block from the
 * detail record's split fields so the hero never waits on the composite.
 */
function resolveFreshness(a360Data, asset) {
  const composite = a360Data?.freshness || null;
  const compositeState = String(composite?.state || "").toLowerCase();
  if (composite && compositeState === "available") return composite;
  const dataUpdatedAt = String(asset?.dataUpdatedAt || "").trim();
  const lastAltered = String(asset?.lastAltered || "").trim();
  if (dataUpdatedAt || lastAltered) {
    return {
      state: "available",
      dataUpdatedAt,
      lastAltered,
      labels: { dataUpdatedAt: "Data updated", lastAltered: "Metadata changed" },
      message: "",
    };
  }
  return composite; // loading / degraded / unavailable — or null while waiting
}

/**
 * Ownership model: the /360 `ownership` block carries exact-title role picks
 * (no regex shadowing — teardown P2-10). Until it lands, the detail record's
 * flat role fields (base_asset_payload) provide the same distinct roles.
 */
function resolveOwnership(a360Data, asset) {
  const roles = a360Data?.ownership || null;
  if (roles && (roles.ucOwner || roles.businessOwner || roles.steward)) return roles;
  if (!asset) return roles;
  const entry = (value) => {
    const name = String(value || "").trim();
    return name ? { name } : null;
  };
  // Header payloads leave the flat steward field empty, but the owners[]
  // array on the same payload already carries role-titled entries — derive
  // from it like the backend does, so the steward slot never claims
  // "Unassigned" while /360 is still cold (re-verify round-2 BLOCK).
  const fromOwners = (pattern) => {
    const owners = Array.isArray(asset.owners) ? asset.owners : [];
    const match = owners.find((o) =>
      pattern.test(String(o?.title || o?.role || o?.ownerType || "")),
    );
    return match ? { name: match.name || match.displayName || match.email, email: match.email } : null;
  };
  const fallback = {
    ucOwner: entry(asset.ucOwner) || fromOwners(/unity catalog/i),
    businessOwner: entry(asset.businessOwner) || fromOwners(/business/i),
    technicalOwner: entry(asset.technicalOwner) || fromOwners(/technical/i),
    steward: entry(asset.steward) || fromOwners(/steward/i),
  };
  if (fallback.ucOwner || fallback.businessOwner || fallback.steward) return fallback;
  return roles;
}

export function AssetHubPage() {
  const routeParams = useParams();
  const fqn = decodeFqnParam(routeParams.fqn ?? routeParams["*"]);
  const [params, setParams] = useSurfaceParams(PARAMS_SCHEMA);
  const navigate = useAxiomNavigate();

  const tab = TABS.some((entry) => entry.key === params.tab) ? params.tab : "overview";
  const sections = SECTIONS_BY_TAB[tab] || SECTIONS_BY_TAB.overview;

  // --- The two PARALLEL queries (never sequenced). -----------------------
  const detail = useAssetDetail(fqn, { sections });
  const a360 = useAsset360(fqn);
  // Lineage feeds the Overview mini-map, the Lineage tab canvas AND the
  // header button label from ONE query, so they can never disagree.
  const lineageActive = tab === "overview" || tab === "lineage";
  const graph = useLineageGraphV2(fqn, { enabled: Boolean(fqn) && lineageActive });
  const editor = useAssetMetadataEditor({ assetFqn: fqn, asset: detail.detail, bootstrap: null });

  // Optimistic certification badge: shown immediately after a successful
  // write, cleared once the refetched record confirms (or the asset changes).
  const [certOverride, setCertOverride] = useState(null);
  useEffect(() => {
    setCertOverride(null);
  }, [fqn]);

  // Remember the last opened record so the permanent "Asset 360" rail entry has
  // a no-context target (owner directive 1), and keep the picker's recents list
  // fresh. Guarded to real three-part FQNs so a dead-end URL never poisons the
  // remembered target.
  useEffect(() => {
    if (fqn && fqn.split(".").filter(Boolean).length >= 3) {
      writeLastAsset(fqn);
      pushRecentAsset(fqn);
    }
  }, [fqn]);

  // A hydrating-envelope stub (inventory rebuilding: headerSource
  // "live-metadata-hydrating", hydrating flag) is NOT an asset yet — adopting
  // it rendered definitive "Unassigned"/score-0 for Certified assets during
  // cold windows (Wave-B verifier BLOCK). Treat it as still-loading.
  const isHydratingStub = (candidate) =>
    Boolean(candidate) &&
    (candidate.hydrating === true ||
      String(candidate.headerSource || "") === "live-metadata-hydrating");
  const detailIsStub = isHydratingStub(detail.detail);
  // The /360 fallback embeds the SAME inventory stub verbatim during cold
  // windows (sameAsset matches, hydrating rides along) — guard both paths or
  // the hub adopts from whichever slipped through (re-verify BLOCK).
  const a360Asset = a360.data?.sameAsset ? a360.data.asset : null;
  const a360IsStub = isHydratingStub(a360Asset);
  const baseAsset =
    (detailIsStub ? null : detail.detail) || (a360IsStub ? null : a360Asset) || null;
  useEffect(() => {
    if (certOverride !== null && String(baseAsset?.certification ?? "") === certOverride) {
      setCertOverride(null);
    }
  }, [baseAsset?.certification, certOverride]);

  const asset = useMemo(() => {
    if (!baseAsset) return null;
    return certOverride !== null ? { ...baseAsset, certification: certOverride } : baseAsset;
  }, [baseAsset, certOverride]);

  const freshness = resolveFreshness(a360.data, asset);
  const ownership = resolveOwnership(a360.data, asset);
  const heroHydrating =
    (!asset && (detail.loading || a360.loading)) ||
    (!asset && (detailIsStub || a360IsStub));

  // Failure contract (PRODUCT §3a): the hub never collapses to a dead end —
  // the frame + retry stay up, and only the failing sections go honest-empty.
  const pageStatus =
    detail.error && !asset
      ? { status: "error", reason: detail.error, refresh: detail.retry }
      : null;

  const tabDefs = useMemo(() => {
    const columnCount = Array.isArray(asset?.columns) && asset.columns.length
      ? asset.columns.length
      : Number(asset?.columnCount) || 0;
    return TABS.map((entry) =>
      entry.key === "columns" && columnCount
        ? { ...entry, badge: String(columnCount) }
        : entry,
    );
  }, [asset]);

  const afterWrite = () => {
    // Re-sync both parallel sources after any governance write so the badge,
    // open-request chip and activity feed reflect persisted truth.
    invalidateAssetDetail(fqn);
    a360.refetch();
  };

  const title = asset?.name || fqn.split(".").pop() || "Asset";
  const identity = [asset?.objectType, asset?.catalog && asset?.schema ? `${asset.catalog}.${asset.schema}` : ""]
    .filter(Boolean)
    .join(" · ");

  return (
    <PageShell
      className="ax-asset-page"
      eyebrow="Asset 360"
      title={title}
      subtitle={identity || fqn}
      status={pageStatus}
      onRetry={detail.retry}
      breadcrumbs={
        <span className="ax-asset-breadcrumbs">
          {asset?.catalog ? (
            <EntityChip appearance="inline" entity={{ kind: "catalog", name: asset.catalog }} />
          ) : null}
          <span className="ax-asset-breadcrumb-fqn" title={fqn}>
            {fqn}
          </span>
        </span>
      }
      actions={
        fqn ? (
          <AssetHeaderActions
            fqn={fqn}
            editor={editor}
            access={a360.data?.access || null}
            graph={graph}
            onCertified={(value) => setCertOverride(value)}
            onAfterWrite={afterWrite}
          />
        ) : null
      }
      tabs={
        <TabStrip
          ariaLabel="Asset record sections"
          tabs={tabDefs}
          param={{ value: tab, set: (key) => setParams({ tab: key }) }}
        />
      }
    >
      <AssetTrustHero
        asset={asset}
        freshness={freshness}
        ownership={ownership}
        // Ownership resolves from the asset payload itself; don't keep it in the
        // "…" hydrating state until the WHOLE a360 envelope (slow OBO
        // lineage/usage) settles — that left owner/steward perpetually "…" for
        // assets whose lineage keeps warming, hiding both the "Unassigned" claim
        // and the inline assign affordance. Pending only until a real asset
        // payload exists.
        ownershipPending={!asset && (a360.loading || a360IsStub)}
        hydrating={heroHydrating}
        // The hub is the authoring surface (it renders Request change / Certify
        // here too). Offer the inline assign affordance; the backend enforces
        // the actual mutate/roster permission and surfaces an honest message on
        // reject. The read-only peek drawer does not pass this, so it stays
        // read-only. onAssigned re-fetches the /360 payload to show the new owner.
        canMutate
        onAssigned={afterWrite}
      />

      {tab === "overview" ? (
        <OverviewTab
          fqn={fqn}
          asset={asset}
          a360={a360.data}
          graph={graph}
          detailLoading={detail.loading}
        />
      ) : null}
      {tab === "columns" ? (
        <ColumnsTab asset={asset} loading={detail.loading} highlightCol={params.col} />
      ) : null}
      {tab === "quality" ? <QualityTab fqn={fqn} quality={a360.data?.quality || null} /> : null}
      {tab === "access" ? <AccessTab access={a360.data?.access || null} fqn={fqn} /> : null}
      {tab === "activity" ? <ActivityTab a360={a360.data} a360Loading={a360.loading} /> : null}
      {tab === "lineage" ? (
        <LineageTab
          fqn={fqn}
          graph={graph}
          onFocusChange={(nextFqn) =>
            // Re-anchoring inside the embed opens that asset's own record,
            // staying on the lineage view (hub-and-spoke law).
            navigate({ kind: "asset", fqn: nextFqn }, { params: { tab: "lineage" } })
          }
        />
      ) : null}
    </PageShell>
  );
}

export default AssetHubPage;
