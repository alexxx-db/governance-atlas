import "./discovery.css";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  EmptyState,
  EntityChip,
  FilterBar,
  PageShell,
  StatusBanner,
  toast,
} from "../../components/system";
import { useDiscoveryResults } from "../../hooks/useDiscoveryResults";
import { exportAssets, fetchEvidencePackBlob } from "../../lib/api";
import { exportAvailable, exportReason } from "../../lib/capabilities";
import { isNonAuthoritativeMockEvidence } from "../../lib/nonAuthoritativeEvidence";
import {
  readDiscoveryDensity,
  readDiscoveryLayout,
  readFavoriteAssets,
  readRecentAssets,
  pushRecentAsset,
  toggleFavoriteAsset,
  writeDiscoveryDensity,
  writeDiscoveryLayout,
} from "../../lib/prefs";
import { usePeek } from "../../nav/useAtlasNavigate";
import { useSurfaceParams } from "../../nav/useSurfaceParams";
import { DiscoveryDiagnosticsStrip } from "./DiscoveryDiagnosticsStrip";
import { DiscoveryFacetRail } from "./DiscoveryFacetRail";
import { DiscoveryInsightPanels, savedViewCountsFor } from "./DiscoveryInsightPanels";
import { DiscoveryQueryBuilder } from "./DiscoveryQueryBuilder";
import { DiscoveryLoadMore, DiscoveryResultsGrid, DiscoveryResultsTable } from "./DiscoveryResults";
import { DiscoverySavedSearches } from "./DiscoverySavedSearches";
import {
  DISCOVERY_PARAMS_SCHEMA,
  PARAM_TO_FILTER_GROUP,
  clearedFacetParams,
  filtersFromParams,
  hasNonQueryFilters,
} from "./discoveryParams";
import {
  appendDiscoveryQueryClause,
  facetOptions,
  isDatabricksBackedDiscoveryMeta,
  ownerLabelsForAsset,
  prettyOwnerName,
  summarizeDiscoveryError,
} from "./discoveryPresentation";
import { useDiscoveryAi } from "./useDiscoveryAi";

/*
 * DiscoveryPage — the Discover surface rebuilt on the system layers (Wave C1).
 *
 * Contracts:
 *   - URL is the state: q/sort/view/facets ride in flat params through
 *     useSurfaceParams (discoveryParams.js); the legacy sessionStorage
 *     snapshot is gone. Legacy ?filters=/?preview=/?views= arrive normalized
 *     by the route wrapper's redirect-normalizer.
 *   - Preview binds ?peek=<fqn> (usePeek): the shell's AssetPeekPanel renders
 *     the SAME AssetTrustHero as the Asset 360 hub, so preview and hub can
 *     never tell different trust stories (PRODUCT_BLUEPRINT §2).
 *   - Data loads only through hooks (useDiscoveryResults on useAtlasQuery —
 *     bounded 3s poll; useDiscoveryAi for click-driven Genie asks).
 *   - Preference-state (density, layout, favorites, recents, saved searches)
 *     lives behind lib/prefs.js with legacy storage-key migration.
 */

const RESULT_PAGE_SIZE = 60;
const MAX_FETCH_LIMIT = 200;

const CRITICALITY_FALLBACK = [
  "Mission Critical",
  "Business Critical",
  "Operational",
  "Low Impact",
  "Not Assessed",
];

const UNASSIGNED_OWNER = "__unassigned__";

function heroSubtitle(sourceAuthoritative, sourceWorkspaceScoped) {
  if (sourceWorkspaceScoped) {
    return "Search across catalogs, schemas, tables, columns, models, and glossary terms. Workspace-scoped results use Unity Catalog and governance store signals; actor-scoped protected reads remain restricted.";
  }
  if (sourceAuthoritative) {
    return "Search across catalogs, schemas, tables, columns, models, and glossary terms. Results are permission-aware and ranked by governed trust signals.";
  }
  return "Search across catalogs, schemas, tables, columns, models, and glossary terms. Non-authoritative payloads are rejected and live trust ranking remains unavailable.";
}

/** Chips for the applied-filter strip (clause chips when the query is valid). */
function appliedChips(filters, params, queryState) {
  const chips = [];
  if (String(queryState?.state || "").trim().toLowerCase() === "valid") {
    const clauseChips = Array.isArray(queryState?.clauseChips) ? queryState.clauseChips : [];
    clauseChips.forEach((chip, index) => {
      const label = String(chip?.label || chip?.expression || "").trim();
      if (!label) return;
      chips.push({
        id: `clause-${index}`,
        label,
        patch: { q: String(chip?.nextQuery || "").trim() },
      });
    });
  }
  for (const [param, group] of Object.entries(PARAM_TO_FILTER_GROUP)) {
    for (const value of filters[group] || []) {
      chips.push({
        id: `${param}-${value}`,
        label: `${param.charAt(0).toUpperCase()}${param.slice(1)}: ${value}`,
        patch: { [param]: (filters[group] || []).filter((item) => item !== value) },
      });
    }
  }
  for (const view of filters.views || []) {
    chips.push({
      id: `view-${view}`,
      label: view,
      patch: { view: (filters.views || []).filter((item) => item !== view) },
    });
  }
  if (params.owner) {
    chips.push({
      id: "owner",
      label:
        params.owner === UNASSIGNED_OWNER
          ? "Owner: Unassigned"
          : `Owner: ${prettyOwnerName(params.owner)}`,
      patch: { owner: "" },
    });
  }
  if (filters.cdeOnly) {
    chips.push({ id: "cde", label: "CDE only", patch: { cde: false } });
  }
  return chips;
}

export function DiscoveryPage({
  bootstrap = null,
  bootState = "live",
  bootMessage = "",
  atlasAiAvailable = true,
  atlasAiUnavailableReason = "Atlas AI is unavailable until the shell reports a configured Genie endpoint.",
}) {
  /* ---- URL state (the only view state) --------------------------------- */
  const [params, setParams] = useSurfaceParams(DISCOVERY_PARAMS_SCHEMA);
  const { peekFqn, openPeek } = usePeek();
  const filters = useMemo(() => filtersFromParams(params, bootstrap), [params, bootstrap]);

  /* ---- search input (draft debounced into ?q=) ------------------------- */
  const [queryDraft, setQueryDraft] = useState(params.q);
  const queryDraftRef = useRef(params.q);
  queryDraftRef.current = queryDraft;
  useEffect(() => {
    // External q changes (owner chips, didYouMean, back/forward) win over a
    // stale draft; while typing, params.q lags the draft and this no-ops.
    if (params.q !== queryDraftRef.current) setQueryDraft(params.q);
  }, [params.q]);
  useEffect(() => {
    if (queryDraft === params.q) return undefined;
    const timeout = setTimeout(() => setParams({ q: queryDraft }), 220);
    return () => clearTimeout(timeout);
  }, [queryDraft, params.q, setParams]);

  /* ---- preferences (lib/prefs.js) -------------------------------------- */
  const [favorites, setFavorites] = useState(() => new Set(readFavoriteAssets()));
  const [recents, setRecents] = useState(() => readRecentAssets());
  const [layout, setLayout] = useState(() => readDiscoveryLayout());
  const [density, setDensity] = useState(() => readDiscoveryDensity());

  /* ---- popovers -------------------------------------------------------- */
  const [showSavedSearches, setShowSavedSearches] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const advancedRef = useRef(null);
  useEffect(() => {
    if (!showAdvanced) return undefined;
    const onPointerDown = (event) => {
      if (!advancedRef.current?.contains(event.target)) setShowAdvanced(false);
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") setShowAdvanced(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [showAdvanced]);

  /* ---- bootstrap seed (paints the grid before the first search lands) --- */
  const bootstrapTruthEnvelope = bootstrap
    ? {
        bootState: bootstrap.bootState,
        state: bootstrap.state,
        status: bootstrap.status,
        source: bootstrap.source,
        meta: bootstrap.meta,
        bootstrapContract: bootstrap.bootstrapContract,
        discovery: bootstrap.discovery,
        assets: bootstrap.assets,
        assetsCount: bootstrap.assetsCount,
      }
    : null;
  const bootstrapNonAuthoritative = isNonAuthoritativeMockEvidence(
    bootstrapTruthEnvelope,
    bootstrap?.discovery?.meta,
  );
  const rawBootstrapAssets =
    Array.isArray(bootstrap?.discovery?.defaultResults) && bootstrap.discovery.defaultResults.length
      ? bootstrap.discovery.defaultResults
      : Array.isArray(bootstrap?.assets)
        ? bootstrap.assets
        : [];
  const seedAssets = bootstrapNonAuthoritative ? [] : rawBootstrapAssets;
  const seedCount = bootstrapNonAuthoritative
    ? 0
    : Number.isFinite(Number(bootstrap?.discovery?.defaultCount))
      ? Number(bootstrap.discovery.defaultCount)
      : Number.isFinite(Number(bootstrap?.assetsCount))
        ? Number(bootstrap.assetsCount)
        : seedAssets.length;
  const seedFacets =
    !bootstrapNonAuthoritative &&
    bootstrap?.discovery?.defaultFacets &&
    typeof bootstrap.discovery.defaultFacets === "object"
      ? bootstrap.discovery.defaultFacets
      : null;

  /* ---- results (the one search query — bounded poll via useAtlasQuery) -- */
  const [visibleCount, setVisibleCount] = useState(RESULT_PAGE_SIZE);
  const requestedLimit = Math.min(Math.max(visibleCount, 80), MAX_FETCH_LIMIT);
  const results = useDiscoveryResults(filters, {
    limit: requestedLimit,
    seedAssets,
    seedCount,
    seedFacets,
  });
  useEffect(() => {
    // Result depth is local UI state; it resets when the scope changes.
    setVisibleCount(RESULT_PAGE_SIZE);
  }, [results.requestKey]);

  const ai = useDiscoveryAi({
    scopeKey: results.requestKey,
    query: filters.query,
    available: atlasAiAvailable,
    unavailableReason: atlasAiUnavailableReason,
  });

  /* ---- derived result views -------------------------------------------- */
  const suppressCatalogRows =
    bootState !== "live" && !results.authoritative && !(results.assets || []).length;
  const allAssets = useMemo(
    () => (suppressCatalogRows || !Array.isArray(results.assets) ? [] : results.assets),
    [results.assets, suppressCatalogRows],
  );

  // Client-side owner facet (?owner=): exact label/email match, or the
  // explicit Unassigned bucket. Mirrors the legacy in-page owner scope.
  const ownerNeedle = String(params.owner || "").trim();
  const renderableAssets = useMemo(() => {
    if (!ownerNeedle) return allAssets;
    if (ownerNeedle === UNASSIGNED_OWNER) {
      return allAssets.filter((asset) => !ownerLabelsForAsset(asset).length);
    }
    const needle = ownerNeedle.toLowerCase();
    return allAssets.filter((asset) =>
      (Array.isArray(asset?.owners) ? asset.owners : []).some((owner) => {
        const label =
          typeof owner === "string" ? owner : owner?.name || owner?.email || owner?.label || "";
        return String(label).toLowerCase().includes(needle);
      }),
    );
  }, [allAssets, ownerNeedle]);

  // Favorites float to the top only when at least one exists, preserving
  // backend (relevance) order otherwise so load-more stays predictable.
  const sortedAssets = useMemo(() => {
    if (!favorites.size) return renderableAssets;
    const starred = [];
    const rest = [];
    for (const asset of renderableAssets) {
      (favorites.has(asset.fqn) ? starred : rest).push(asset);
    }
    return [...starred, ...rest];
  }, [renderableAssets, favorites]);
  const renderedAssets = useMemo(
    () => sortedAssets.slice(0, visibleCount),
    [sortedAssets, visibleCount],
  );

  // G2 — export the current (filtered) result set as a visibility-redacted CSV.
  // Available only under OBO (bootstrap.capabilities.exportAllowed); the backend
  // enforces the same actor-scoped contract and caps a sync export at 500.
  const [exporting, setExporting] = useState(false);
  const exportEnabled = exportAvailable(bootstrap);
  const handleExport = async () => {
    const fqns = sortedAssets.map((asset) => asset?.fqn).filter(Boolean).slice(0, 500);
    if (!fqns.length || exporting) return;
    setExporting(true);
    try {
      const csv = await exportAssets(fqns);
      const text = typeof csv === "string" ? csv : "";
      if (!text.trim()) throw new Error("Export returned no rows.");
      const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atlas-assets-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast(`Exported ${fqns.length} asset${fqns.length === 1 ? "" : "s"} to CSV.`, { tone: "success" });
    } catch (error) {
      toast(error?.message || "Export failed.", { tone: "danger" });
    } finally {
      setExporting(false);
    }
  };

  // G10 — tamper-evident evidence pack (.zip: CSV + SHA-256 provenance manifest).
  const [exportingPack, setExportingPack] = useState(false);
  const handleEvidencePack = async () => {
    const fqns = sortedAssets.map((asset) => asset?.fqn).filter(Boolean).slice(0, 500);
    if (!fqns.length || exportingPack) return;
    setExportingPack(true);
    try {
      const blob = await fetchEvidencePackBlob(fqns);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atlas-evidence-pack-${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast(`Evidence pack (${fqns.length} asset${fqns.length === 1 ? "" : "s"} + checksum manifest) downloaded.`, { tone: "success" });
    } catch (error) {
      toast(error?.message || "Evidence pack export failed.", { tone: "danger" });
    } finally {
      setExportingPack(false);
    }
  };
  const assetsByFqn = useMemo(() => {
    const map = new Map();
    for (const asset of allAssets) if (asset?.fqn) map.set(asset.fqn, asset);
    return map;
  }, [allAssets]);

  const invalidQuery = results.queryState?.state === "invalid" ? results.queryState : null;
  const hasResults = renderableAssets.length > 0;
  const discoveryMeta = results.meta || null;
  const databricksBacked = isDatabricksBackedDiscoveryMeta(discoveryMeta);
  const sourceAuthoritative = results.authoritative === true || databricksBacked;
  const sourceLabel =
    results.authoritative === true
      ? "Live Unity Catalog"
      : databricksBacked
        ? "Databricks-backed · workspace scope"
        : "Degraded discovery payload";

  /* ---- interactions ---------------------------------------------------- */
  const openPreview = (fqn) => {
    if (!fqn) return;
    setRecents(pushRecentAsset(fqn));
    openPeek(fqn);
  };
  const toggleFavorite = (fqn) => {
    const next = toggleFavoriteAsset(fqn);
    setFavorites(new Set(next));
    const name = assetsByFqn.get(fqn)?.name || String(fqn).split(".").pop() || "asset";
    toast(
      next.includes(fqn)
        ? `Saved ${name} as a local browser favorite.`
        : `Removed ${name} from local browser favorites.`,
    );
  };
  const toggleLayout = (next) => {
    setLayout(writeDiscoveryLayout(next));
  };
  const toggleDensity = () => {
    setDensity(writeDiscoveryDensity(density === "compact" ? "comfortable" : "compact"));
  };
  const resetBrowse = () => {
    // One write clears the whole scope INCLUDING the preview drawer (?peek=
    // is outside the schema, so it needs the explicit empty patch).
    setParams({ ...clearedFacetParams(), sort: "", peek: "" });
  };
  const applyView = (views) => setParams({ view: views });
  const applySavedSearch = (entry) =>
    setParams({
      q: String(entry.query || ""),
      cde: Boolean(entry.cdeOnly),
      view: entry.views || [],
      type: entry.types || [],
      catalog: entry.catalogs || [],
      domain: entry.domains || [],
      tier: entry.tiers || [],
      certification: entry.certifications || [],
      sensitivity: entry.sensitivities || [],
      criticality: entry.businessCriticalities || [],
    });
  const toggleFacetValue = (param, value) => {
    const group = PARAM_TO_FILTER_GROUP[param];
    const current = group ? filters[group] || [] : [];
    setParams({
      [param]: current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    });
  };
  const appendQueryClause = (clause) =>
    setParams({ q: appendDiscoveryQueryClause(filters.query, clause, "AND") });

  /* ---- filter bar model ------------------------------------------------- */
  const facets = results.facets;
  const bootstrapCatalogFallback = (bootstrap?.discovery?.defaultFacets?.catalogs || [])
    .map((entry) => (typeof entry === "string" ? entry : entry?.value || entry?.label || ""))
    .filter(Boolean);
  const ownerFacetOptions = useMemo(() => {
    const live = Array.isArray(facets?.owners) ? facets.owners : [];
    const fromFacets = live
      .filter((entry) => entry?.value && entry.value !== "All owners" && entry.value !== "Unassigned")
      .map((entry) => ({
        value: String(entry.value),
        label: prettyOwnerName(String(entry.value)),
        count: Number(entry.count || 0),
      }));
    const unassignedFacet = live.find((entry) => entry?.value === "Unassigned");
    const seen = new Set(fromFacets.map((entry) => entry.value));
    let localUnassigned = 0;
    const fromAssets = [];
    for (const asset of allAssets) {
      const labels = ownerLabelsForAsset(asset);
      if (!labels.length) localUnassigned += 1;
      for (const label of labels) {
        if (seen.has(label)) continue;
        seen.add(label);
        fromAssets.push({ value: label, label: prettyOwnerName(label) });
      }
    }
    const unassignedCount = Number(unassignedFacet?.count || 0) || localUnassigned;
    const options = [...fromFacets, ...fromAssets].slice(0, 20);
    if (unassignedCount > 0) {
      options.push({ value: UNASSIGNED_OWNER, label: "Unassigned", count: unassignedCount });
    }
    return options;
  }, [facets, allAssets]);

  const filterFacets = [
    {
      key: "type",
      label: "Type",
      type: "multi",
      options: facetOptions(facets, "assetTypes", filters.types),
    },
    {
      key: "catalog",
      label: "Catalog",
      type: "multi",
      options: facetOptions(facets, "catalogs", filters.catalogs, bootstrapCatalogFallback),
    },
    {
      key: "domain",
      label: "Domain",
      type: "multi",
      options: facetOptions(facets, "domains", filters.domains),
    },
    {
      key: "tier",
      label: "Tier",
      type: "multi",
      options: facetOptions(facets, "tiers", filters.tiers),
    },
    {
      key: "certification",
      label: "Certification",
      type: "multi",
      options: facetOptions(facets, "certifications", filters.certifications),
    },
    {
      key: "sensitivity",
      label: "Classification",
      type: "multi",
      options: facetOptions(facets, "sensitivities", filters.sensitivities),
    },
    {
      key: "criticality",
      label: "Criticality",
      type: "multi",
      options: facetOptions(
        facets,
        "businessCriticalities",
        filters.businessCriticalities,
        CRITICALITY_FALLBACK,
      ),
    },
    { key: "owner", label: "Owner", type: "select", options: ownerFacetOptions },
    {
      key: "view",
      label: "Saved view",
      type: "multi",
      options: (bootstrap?.discovery?.views || [])
        .filter((view) => view && view !== "All assets")
        .map((view) => ({ value: view, label: view })),
    },
  ];
  const filterValue = {};
  if (filters.types.length) filterValue.type = filters.types;
  if (filters.catalogs.length) filterValue.catalog = filters.catalogs;
  if (filters.domains.length) filterValue.domain = filters.domains;
  if (filters.tiers.length) filterValue.tier = filters.tiers;
  if (filters.certifications.length) filterValue.certification = filters.certifications;
  if (filters.sensitivities.length) filterValue.sensitivity = filters.sensitivities;
  if (filters.businessCriticalities.length) filterValue.criticality = filters.businessCriticalities;
  if (params.owner) filterValue.owner = params.owner;
  if (filters.views.length) filterValue.view = filters.views;
  const onFilterBarChange = (next) =>
    setParams({
      type: next.type || [],
      catalog: next.catalog || [],
      domain: next.domain || [],
      tier: next.tier || [],
      certification: next.certification || [],
      sensitivity: next.sensitivity || [],
      criticality: next.criticality || [],
      owner: next.owner || "",
      view: next.view || [],
    });

  /* ---- sort model (bootstrap-owned vocabulary; "Relevance" = default) --- */
  const sortOptions = useMemo(() => {
    const raw = Array.isArray(bootstrap?.discovery?.sortOptions)
      ? bootstrap.discovery.sortOptions
      : [];
    // "Best match" reads as fake precision; it IS the default relevance
    // order, so it renders as Relevance (the wire value stays canonical).
    return raw.map((option) =>
      /best\s*match/i.test(String(option)) ? { value: "", label: "Relevance" } : { value: option, label: option },
    );
  }, [bootstrap]);
  const activeSortValue = sortOptions.some((option) => option.value === params.sort)
    ? params.sort
    : "";

  /* ---- empty/degraded state copy (honesty rules preserved) -------------- */
  const trimmedQuery = filters.query.trim();
  const nonQueryFiltersActive = hasNonQueryFilters(filters) || Boolean(params.owner);
  const showInventoryEmptyState = results.settled && suppressCatalogRows && !hasResults;
  // A query with zero filters that matches nothing IS "no matches" — never
  // blame filters the user hasn't set.
  const discoveryNoMatches =
    !showInventoryEmptyState && Boolean(trimmedQuery) && !nonQueryFiltersActive;
  const didYouMean =
    typeof discoveryMeta?.didYouMean === "string" ? discoveryMeta.didYouMean.trim() : "";
  const emptyHeading = showInventoryEmptyState
    ? "No visible assets are being returned."
    : discoveryNoMatches
      ? `No matches for “${trimmedQuery}”`
      : "No assets match the current scope.";
  const emptyCopy = showInventoryEmptyState
    ? bootMessage ||
      "The workspace can load, but the current principal is not surfacing any visible catalog assets yet."
    : discoveryNoMatches
      ? "Nothing in the visible catalog matched that search. Check the spelling or try a name, tag, or owner."
      : "Relax the current search, saved view, or filters to widen the catalog scope.";

  const diagnostics = {
    runtimeState: bootState || discoveryMeta?.state || bootstrap?.bootState || "",
    authMode:
      bootstrap?.identity?.authMode || discoveryMeta?.authMode || discoveryMeta?.productMode || "",
    visibilityScope:
      bootstrap?.identity?.visibilityScope ||
      discoveryMeta?.visibilityScope ||
      discoveryMeta?.readScope ||
      "",
    inventorySource: discoveryMeta?.source || "",
    visibleAssets:
      typeof discoveryMeta?.visibleAssetCount === "number"
        ? discoveryMeta.visibleAssetCount
        : Array.isArray(results.assets)
          ? results.assets.length
          : 0,
    observedAt: discoveryMeta?.observedAt || "",
    discoveryState: discoveryMeta?.discoveryState || "",
  };

  const chips = appliedChips(filters, params, results.queryState);
  // Audit B2/B4: prefer the SERVER `facets.views` counts (authoritative
  // `view_matches` over the full matched estate) so each "Governance Views"
  // number equals what clicking the view actually returns. The client
  // recompute is a degraded-only fallback for when the facet is absent.
  const savedViewCounts = useMemo(() => {
    const serverViews = Array.isArray(results.facets?.views) ? results.facets.views : null;
    if (serverViews && serverViews.length) {
      const map = {};
      for (const item of serverViews) {
        if (item && item.value != null) map[item.value] = Number(item.count) || 0;
      }
      return map;
    }
    return savedViewCountsFor(allAssets);
  }, [results.facets, allAssets]);
  const favoriteChipAssets = [...favorites]
    .map((fqn) => ({ fqn, name: assetsByFqn.get(fqn)?.name }))
    .slice(0, 6);
  const recentChipAssets = recents
    .filter((fqn) => !favorites.has(fqn))
    .map((fqn) => ({ fqn, name: assetsByFqn.get(fqn)?.name }))
    .slice(0, 6);

  const showingCount = renderedAssets.length;
  const loadingMore =
    hasResults && results.count > showingCount && results.loading && renderableAssets.length < visibleCount;

  // PageShell status: quiet "Refreshing" while stale-while-revalidate is in
  // flight; a degraded banner when a refresh fails over rendered data.
  const pageStatus =
    results.error && hasResults
      ? { status: "degraded", warnings: [summarizeDiscoveryError(results.error)] }
      : results.fetching && hasResults
        ? { status: "hydrating" }
        : { status: "available" };

  const emptyActions = (
    <div className="ga-disc-empty-actions">
      {discoveryNoMatches && didYouMean ? (
        <Button onClick={() => setParams({ q: didYouMean })} tone="accent" variant="primary">
          Search instead for “{didYouMean}”
        </Button>
      ) : null}
      {filters.query ? (
        <Button onClick={() => setParams({ q: "" })} variant="secondary">
          Clear search
        </Button>
      ) : null}
      <Button onClick={resetBrowse} variant="secondary">
        Reset browse
      </Button>
    </div>
  );

  return (
    <PageShell
      className="ga-disc-page"
      eyebrow="Discover"
      status={pageStatus}
      subtitle={heroSubtitle(sourceAuthoritative, databricksBacked && results.authoritative !== true)}
      title="Find trusted, governed data"
      actions={
        <Button
          disabled={ai.loading || !atlasAiAvailable}
          onClick={() => ai.run()}
          title={!atlasAiAvailable ? atlasAiUnavailableReason : undefined}
          tone="accent"
          variant="primary"
        >
          {ai.loading ? "Asking Atlas AI…" : "Ask Atlas AI"}
        </Button>
      }
    >
      {!sourceAuthoritative ? (
        <StatusBanner
          message="Asset values shown here require an explicitly live and authoritative source before they can be used for product-readiness evidence."
          title={sourceLabel}
          tone="warning"
        />
      ) : null}

      <div className="ga-disc-toolbar">
        <label className="ga-disc-search">
          <span aria-hidden="true" className="ga-disc-search-icon">
            <svg fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" viewBox="0 0 24 24" width="16">
              <circle cx="11" cy="11" r="7" />
              <path d="m16.5 16.5 4 4" />
            </svg>
          </span>
          <input
            aria-label="Search discovery assets"
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder='Try: revenue, customer_id, owner:"name@company.com", tag:CDE…'
            type="search"
            value={queryDraft}
          />
        </label>
        <label className="ga-disc-sort">
          <span>Sort</span>
          <select
            aria-label="Sort results"
            onChange={(event) => setParams({ sort: event.target.value })}
            value={activeSortValue}
          >
            {sortOptions.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <Button
          aria-pressed={filters.cdeOnly}
          className={filters.cdeOnly ? "is-pressed" : ""}
          onClick={() => setParams({ cde: !filters.cdeOnly })}
          variant="secondary"
        >
          CDE only
        </Button>
        <div aria-label="Result layout" className="ga-disc-layout-toggle" role="group">
          <Button
            aria-label="List view"
            aria-pressed={layout === "list"}
            className={layout === "list" ? "is-pressed" : ""}
            onClick={() => toggleLayout("list")}
            variant="secondary"
          >
            List
          </Button>
          <Button
            aria-label="Grid view"
            aria-pressed={layout === "grid"}
            className={layout === "grid" ? "is-pressed" : ""}
            onClick={() => toggleLayout("grid")}
            variant="secondary"
          >
            Grid
          </Button>
          <Button
            aria-label="Toggle compact density"
            aria-pressed={density === "compact"}
            className={density === "compact" ? "is-pressed" : ""}
            onClick={toggleDensity}
            variant="secondary"
          >
            Compact
          </Button>
        </div>
        <Button
          aria-expanded={showSavedSearches}
          onClick={() => setShowSavedSearches((current) => !current)}
          variant="secondary"
        >
          Saved searches
        </Button>
        <Button
          aria-expanded={showAdvanced}
          onClick={() => setShowAdvanced((current) => !current)}
          variant="secondary"
        >
          Advanced
        </Button>
        {exportEnabled ? (
          <>
            <Button
              disabled={exporting || !sortedAssets.length}
              loading={exporting}
              onClick={handleExport}
              title={`Export the current ${Math.min(sortedAssets.length, 500)} result${sortedAssets.length === 1 ? "" : "s"} as CSV`}
              variant="secondary"
            >
              Export CSV
            </Button>
            <Button
              disabled={exportingPack || !sortedAssets.length}
              loading={exportingPack}
              onClick={handleEvidencePack}
              title="Download a tamper-evident evidence pack (.zip): the CSV + a SHA-256 provenance manifest"
              variant="secondary"
            >
              Evidence pack
            </Button>
          </>
        ) : (
          <Button
            aria-disabled="true"
            className="is-disabled"
            onClick={() => toast(exportReason(bootstrap), { tone: "warning" })}
            title={exportReason(bootstrap)}
            variant="secondary"
          >
            Export CSV
          </Button>
        )}
      </div>

      <FilterBar
        facets={filterFacets}
        label="Discovery filters"
        onChange={onFilterBarChange}
        onClear={() => setParams({ ...clearedFacetParams(), q: filters.query })}
        value={filterValue}
      />

      {showSavedSearches ? (
        <DiscoverySavedSearches
          filters={filters}
          onApply={applySavedSearch}
          onClose={() => setShowSavedSearches(false)}
        />
      ) : null}

      {showAdvanced ? (
        <div aria-label="Advanced discovery filters" className="ga-disc-advanced" ref={advancedRef} role="dialog">
          <DiscoveryQueryBuilder
            activeQuery={filters.query}
            onApplyQuery={(nextQuery) => setParams({ q: nextQuery })}
            queryState={results.queryState}
            resultsCount={results.count}
            supportedFields={results.queryState?.supportedFields || []}
            syntaxHint={results.queryState?.syntaxHint || ""}
          />
        </div>
      ) : null}

      {chips.length ? (
        <div aria-live="polite" className="ga-disc-chip-row" role="status">
          <span className="ga-disc-chip-label">Filtered by</span>
          {chips.map((chip) => (
            <button
              aria-label={`Clear ${chip.label}`}
              className="ga-disc-chip"
              key={chip.id}
              onClick={() => setParams(chip.patch)}
              title={`Clear ${chip.label}`}
              type="button"
            >
              <span>{chip.label}</span>
              <span aria-hidden="true">×</span>
            </button>
          ))}
          <button className="ga-disc-chip-clear-all" onClick={resetBrowse} type="button">
            Reset browse
          </button>
        </div>
      ) : null}

      {favoriteChipAssets.length || recentChipAssets.length ? (
        <div className="ga-disc-activity" aria-label="Favorites and recently viewed">
          {favoriteChipAssets.length ? (
            <div className="ga-disc-activity-group">
              <span className="ga-disc-activity-title">★ Your favorites</span>
              {favoriteChipAssets.map((entry) => (
                <EntityChip
                  entity={{
                    kind: "asset",
                    fqn: entry.fqn,
                    label: entry.name || entry.fqn.split(".").pop(),
                  }}
                  key={entry.fqn}
                />
              ))}
            </div>
          ) : null}
          {recentChipAssets.length ? (
            <div className="ga-disc-activity-group">
              <span className="ga-disc-activity-title">⧗ Recently viewed</span>
              {recentChipAssets.map((entry) => (
                <EntityChip
                  entity={{
                    kind: "asset",
                    fqn: entry.fqn,
                    label: entry.name || entry.fqn.split(".").pop(),
                  }}
                  key={entry.fqn}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="ga-disc-body">
        <DiscoveryFacetRail
          facets={facets}
          onAppendQueryClause={appendQueryClause}
          onToggle={toggleFacetValue}
          selections={{
            certifications: filters.certifications,
            domains: filters.domains,
            sensitivities: filters.sensitivities,
          }}
        />

        <div className="ga-disc-results">
          {invalidQuery ? (
            <>
              <EmptyState
                body={
                  invalidQuery.syntaxHint ||
                  "Use AND, OR, parentheses, quoted phrases, and supported field selectors."
                }
                className="ga-disc-empty"
                title={invalidQuery.message || "Invalid discovery query."}
                action={emptyActions}
              />
            </>
          ) : results.error && !hasResults ? (
            <>
              <DiscoveryDiagnosticsStrip {...diagnostics} />
              <EmptyState
                body={summarizeDiscoveryError(results.error)}
                className="ga-disc-empty"
                title="Discovery search degraded"
                action={emptyActions}
              />
            </>
          ) : hasResults ? (
            <>
              {/* The backend silently runs the near-match pass and returns
                  corrected results + didYouMean; without this caption a typo
                  shows "21 results" under the wrong chip with no explanation
                  (C1/C2 verifier BLOCK). */}
              {didYouMean && didYouMean.toLowerCase() !== trimmedQuery.toLowerCase() ? (
                <p className="ga-disc-correction" role="status">
                  Showing close matches for <strong>“{didYouMean}”</strong> — corrected from
                  “{trimmedQuery}”.
                  <Button onClick={() => setParams({ q: didYouMean })} size="small" variant="tertiary">
                    Search “{didYouMean}” exactly
                  </Button>
                </p>
              ) : null}
              {layout === "grid" ? (
                <DiscoveryResultsGrid
                  assets={renderedAssets}
                  favorites={favorites}
                  onPreview={openPreview}
                  onToggleFavorite={toggleFavorite}
                  sourceAuthoritative={sourceAuthoritative}
                />
              ) : (
                <DiscoveryResultsTable
                  assets={renderedAssets}
                  density={density}
                  favorites={favorites}
                  loading={false}
                  onPreview={openPreview}
                  onToggleFavorite={toggleFavorite}
                  sourceAuthoritative={sourceAuthoritative}
                />
              )}
              <DiscoveryLoadMore
                loadingMore={loadingMore}
                onLoadMore={() =>
                  setVisibleCount((current) =>
                    Math.min(current + RESULT_PAGE_SIZE, results.count || current + RESULT_PAGE_SIZE),
                  )
                }
                showing={showingCount}
                total={results.count}
              />
              <DiscoveryInsightPanels
                ai={ai}
                assets={renderedAssets}
                atlasAiAvailable={atlasAiAvailable}
                atlasAiUnavailableReason={atlasAiUnavailableReason}
                onApplyView={applyView}
                onAskAtlas={() => ai.run()}
                onPreview={openPreview}
                savedViewCounts={savedViewCounts}
              />
            </>
          ) : results.loading ? (
            <DiscoveryResultsTable assets={[]} density={density} loading />
          ) : (
            <>
              <DiscoveryDiagnosticsStrip {...diagnostics} />
              <EmptyState
                action={emptyActions}
                body={emptyCopy}
                className="ga-disc-empty"
                title={emptyHeading}
              />
            </>
          )}
        </div>
      </div>

      {/* The preview drawer itself is the shell-mounted AssetPeekPanel bound
          to ?peek= — it renders the same AssetTrustHero as the Asset 360 hub,
          so Discover can never tell a different trust story. peekFqn is read
          here only to reflect selection state. */}
      <span className="ga-sys-visually-hidden" data-peek-fqn={peekFqn || undefined} />
    </PageShell>
  );
}

export default DiscoveryPage;
