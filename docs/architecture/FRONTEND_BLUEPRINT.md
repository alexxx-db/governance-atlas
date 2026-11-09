# Axiom — Experience-Layer Rebuild Blueprint

Principal frontend architecture blueprint. Scope: the experience layer only (shell, routing, page composition, data loading, styling). Backend contracts (canonical semantics module, real lineage, honest envelopes) are treated as fixed and truthful. Repo: `/Users/axbo/Development/alexxx-db/axiom//axiom`, branch `main`. All citations are `file:line` under `frontend/src` unless absolute.

## Executive summary

The experience layer is not under-built — it is **triple-built**. Three component generations coexist (gh shell primitives, ax northstar kit, lineage-v2 kit); 9 of 14 northstar components are orphans while 11 surfaces hand-roll their own heroes, 7 their own KPI systems, 8 their own tables. 32,972 lines of CSS (87% legacy `gh-*`, 1,451 `!important`, `.gh-primary-button` declared in 4 files) style them. Cross-surface navigation runs on **7 parallel mechanisms** (URL, 16 drilled callbacks, 5 sessionStorage families, 6 localStorage keys, 3 window events, a sessionStorage intent singleton, the query-client-as-bus) with zero React Context. Data loading has good bones (24/27 hooks on react-query, one envelope, one client) but **11+ copy-pasted hydration predicates, 10-12 divergent status renderings, and 12 of 14 polls unbounded**. The flagship record page (EntityWorkspace, 3,227 lines) is old-shell, has no nav address for its tabs, and loads through a 4-stage waterfall.

The fix is three system layers — a component kit (`components/system/`), one data contract (`useAxiomQuery` + `lib/envelope.js`), one navigation fabric (`navigate(ref)` + full URL addressability) — landed with no visual change (Wave A), proven on a rebuilt Asset 360 + new shell (Wave B), then rolled surface-by-surface (Wave C), with CI guardrails that make re-dispersion a build failure. Target: ~9k lines of CSS (-73%), one implementation per concept, every view addressable, every poll bounded.

---

# PART I — INVENTORY (what is actually dispersed, quantified)

## 1. Shell & layout

### 1.1 Composition today

- `main.jsx` mounts `BrowserRouter → QueryClientProvider → ReactFlowProvider → AppErrorBoundary → App` and imports **10 global stylesheets in load-order-significant sequence** (`app.css` → … → `northstar.css` → `lineage-v2.css`), with tokens entering only transitively via `app.css:1`'s `@import` (main.jsx:9-18).
- `App.jsx` (1,172 lines) is a **god component**: it is simultaneously the route switch (13-branch if/else over `surface`, App.jsx:805-1096), a lifted data bus (`liveDiscoveryState`, `liveGovernanceState` — App.jsx:267-278), a seed-merging engine (`mergeAssetGroups`/`visibleAssetSetFromGroups`/`searchSeedAssets`/`contextSeedAssets`, App.jsx:42-61, 619-639), the inbox-badge computer (App.jsx:96-116, 403-422), the command-center seed synthesizer (App.jsx:707-765), the Asset 360 drawer owner (App.jsx:284-291), and a hand-rolled navigation-pending state machine with 8s/24s timeouts (App.jsx:539-560).
- `AppFrame.jsx` (1,166 lines) is the `gh-*` prototype shell: header (`gh-shell-header` AppFrame.jsx:895), side rail, command palette wiring, **and a fully inlined floating Axiom AI chat** (~700 lines: `AxiomAiEvidenceDetail`, `AxiomAiMessageList`, drag/clamp positioning, prompts — AppFrame.jsx:224-388, 981-1130). The shell file owns a product feature.
- Every workspace receives 10-20 props from App (bootstrap, seeds, callbacks, boot state, feature flags, workspaceAccess) — e.g. DiscoveryWorkspace gets 22 props (App.jsx:816-844).

### 1.2 Page-shell generations — three coexisting kits

There are **three generations of "shared" layout primitives**, all live simultaneously:

| Generation | Files | Classes | Used by |
|---|---|---|---|
| 1. `gh-*` shell primitives | `ShellLayoutPrimitives.jsx` (SurfaceHeader/SurfaceTabs/SurfaceRail/SurfacePanelSection/SurfaceWorkbench/SurfaceDrawer, :56-249), `ShellStatePrimitives.jsx` (WorkspaceStateCard/InlineStatusBanner/EmptyStateBlock/LoadingState/SkeletonBlock, :5-94), `components/primitives/*` (28 files: Breadcrumbs, StatusBadge, MetadataChip, EntityHero, UserChip, GlobalHeader, SideIconRail…) | `gh-*` | App shell, EntityWorkspace, Discovery, most workspaces |
| 2. `ax-*` northstar kit | `components/northstar/*` (14 exports: PageHero, MetricCard, SectionCard, DataTable, EmptyState, DegradedBanner, StatusPill, BarList, DonutMetric, Sparkline, HeatmapMatrix, ActionTile, RightInspector, AxiomAiPanel — northstar/index.js:1-14) | `ax-*` | HomePage, InsightsWorkspace, parts of ops surfaces |
| 3. lineage-v2 kit | `components/lineage-v2/*` (LineageCanvasV2, LineageNodeCard, useLineageGraphV2 adapter) | `ax-lineage-v2-*` | Lineage surface + Entity lineage tab |

So a "page header" can be `SurfaceHeader` (gh), `PageHero` (ax), or hand-rolled hero markup per workspace; the duplication table in §5 quantifies this.

### 1.3 CSS census (quantified)

32,972 lines across 11 stylesheets + 10 token files (241 lines). Three files hold 73%: `northstar.css` 8,102, `operations-pages.css` 8,092, `app.css` 7,744; then `shell-rail.css` 2,690, `discovery.css` 2,630, `insights.css` 1,256, `lineage-v2.css` 984, `entity.css` 781, `lineage.css` 421, `capability-dashboard.css` 137, `governance.css` 135.

**Prefix reality: only two prefixes exist** — `gh-*` (legacy prototype) and `ax-*` (system). Repo-wide **6,251 `.gh-` selector occurrences vs 934 `.ga-`** (~87% legacy). Per file (unique gh/ax selectors): app.css 481/23; shell-rail.css 193/0; operations-pages.css 341/16; discovery.css 234/0; entity.css 126/0; governance.css 24/0; capability-dashboard.css 19/0; insights.css 58/2; northstar.css 342/152 (the "north star" file is itself 69% legacy); lineage.css 6/8; **lineage-v2.css 1/62 — the only clean system file**.

**Literal cascade collisions**: `.gh-primary-button` is re-declared in **4 files** (app.css:375, discovery.css:2018, northstar.css:5221, shell-rail.css:2231); `.gh-secondary-button` in 3 files (app.css re-declares it internally at 9+ line ranges); `.gh-tertiary-button` in 3; `.gh-icon-button` in 2 plus a parallel `.ax-icon-button` (northstar.css:1335).

**Duplication by concept (independent CSS implementations)**: buttons ~42 distinct selectors across 6 files; chips/pills/badges ~147 across 8; tabs ~84 across 9 (e.g. `gh-subtab` app.css:382, `gh-discovery-subtabs` discovery.css:9, `gh-entity-record-tabs` entity.css:52, `ax-tab-button` operations-pages.css:2187, `ax-lineage-v2-rail-tabs` lineage-v2.css:601); cards/panels ~181 across 9; **hero/KPI/stat tiles ~190 across 10 files — the single worst concept**; tables ~43 across 7; empty states ~56 across 8; toasts ~18 across 3; drawers/overlays ~36 across 5.

**Theme debt**: app.css is a light base with dark bolted on — **36 `:root[data-theme="dark"]` override blocks and 756 `!important`** in that one file (**1,451 `!important` repo-wide**). discovery.css carries 18 cream fallbacks like `var(--gh-surface-muted, #f3f6fb)` (discovery.css:721) and `var(--gh-accent, #5b3ff2)` (discovery.css:724-728). Raw hex literals: app.css 160, discovery.css 148, northstar.css 136, entity.css 52; fully tokenized files: operations-pages.css (5 hexes, 485 `var(--ax-*)`), lineage-v2.css, lineage.css, capability-dashboard.css (0 hexes).

**Token layer** (`design/tokens/`, 133 tokens, guarded by tokens.test.js): well-structured, `--ax-*` declared the contract with `--gh-*` kept as aliases (`--gh-bg: var(--ax-bg)`) — the token file itself encodes the migration debt. But 38 `--ga-`/`--gh-` custom properties are **locally re-defined outside the token dir** (app.css/northstar.css/shell-rail.css), shadowing the source of truth.

**Import wiring hazard**: `operations-pages.css` (8,092 lines) is *not* in main.jsx — it is component-imported by 5 workspaces (AdminWorkspace.jsx:7, AuditBrowserWorkspace.jsx:6, CdeWorkspace.jsx:5, GovernanceWorkspace.jsx:21, TaxonomyWorkspace.jsx:14), so it enters the cascade *after* all globals whenever any of those mounts. northstar.css contains rules that depend on loading before/after operations-pages.css (northstar.css:7738, 7895). Cascade order is nondeterministic by navigation path; the 1,451 `!important`s are the workaround.

## 2. Routing, URL state, and cross-surface navigation

### 2.1 Route model

`useAppRouteState.js` (716 lines) is a single hook over react-router's `useLocation`/`useNavigate` that: parses path + legacy aliases into 13 known surfaces (KNOWN_SURFACES :5; parsePathRoute :77-174), canonicalizes the URL on every change via `navigate(..., {replace:true})` (:339-354), and exposes per-surface imperative openers (`openEntityWorkspace` :356, `openLineageWorkspace` :373, `openGovernanceWorkspace` :393, `openDiscoveryWorkspace` :522) plus five discovery-only setters and a 130-line `onModuleChange` switch (:547-690) that repeats the same 8-argument `buildCanonicalUrl` call 10 times.

Canonical paths: `/home` (aliases `/command-center`, `/exec`; `/` defaults to home), `/discovery` (`/discover`), `/entity/<fqn>`, `/lineage/<fqn>` (`/lineage-atlas`), `/governance` (`/stewardship`, `/sk` — asset via `?asset=` only), `/audit` (`/audit-evidence`), `/taxonomy` (`/glossary*`), `/cde` → canonicalizes to `/taxonomy?tab=cdes`, `/help`, `/inbox`, `/admin` (`/control-center`), `/capabilities`, `/insights`.

**Structural quirk**: Discovery's entire query state (`?q`, `?sort`, `?preview`, `?views`, JSON `?filters`, plus 12 shortcut params) is threaded through **every** navigation call on every surface — `buildCanonicalUrl` takes 8 positional args and each `open*` caller must re-pass all discovery state (:356-545). Discovery params ride along in the URL on non-discovery surfaces.

### 2.2 URL-state coverage — what survives refresh/back and what doesn't

Addressable: the 13 surfaces, entity/lineage focus asset (path), governance asset (`?asset`), discovery q/sort/preview/views/filters, `?tab=cdes`, transient `?term=` (taxonomy deep link, self-deleting).

**NOT addressable (state lost on refresh/back)**:
- Entity active tab (Overview/Schema/Preview/Lineage/Queries) — sessionStorage `workspaceIntent` only (EntityWorkspace.jsx:1701, 2070)
- Lineage context (Data Lineage vs Operational Context) — workspaceIntent only (LineageWorkspace.jsx:1404-1408)
- Taxonomy selected term/node/detail tab/status filter/search — local state; `?term=` is deleted after consumption via **raw `window.history.replaceState` bypassing the router** (TaxonomyWorkspace.jsx:697, and `?tab` sync at :877)
- Asset 360 drawer open/fqn — App.jsx local state (:284)
- Insights risk-focus — sessionStorage `ax-insights-focus` handoff
- Discovery density/favorites/recents/saved-searches/pins — localStorage only; discovery filter session snapshot — sessionStorage, revived only when the URL is blank (useDiscoveryWorkspace.js:213, 370)

### 2.3 Cross-surface handoff mechanisms — 7 distinct systems (the core dispersion cause)

Verified by exhaustive sweep; **zero React Context anywhere** (no createContext/useContext outside tests):

1. **Router URL state** (§2.1), including the non-URL `location.state.fresh` boolean riding in history entries (useAppRouteState.js:334, 352, 430, 543).
2. **~16 distinct props-drilled navigation callbacks**, all wired in App.jsx: `onOpenAsset` (App.jsx:833,895,912,926,941,1089), `onOpenGovernance` (:834,867,894,1015), `onOpenLineage` (:835,868,927,942,1090,1164), `onSelectAsset` (:871), `onNavigate` (:983,997,1057), `onModuleChange` (:1119), `onOpenGlossaryTerm` (:1016), `onOpenAsset360Drawer` (:1058), `onOpenDiscoveryWithFilter` (:1059-1063), `onOpenAsset360` (:1120-1133), `onOpenCapabilities` (:1147), `onSearchResultSelect` (:1135-1142), `onBrowseCatalog` (:1118), `onRouteAssetChange` (:1088), plus intra-surface `onOpenSchema`/`onOpenLinkedAsset`/`onOpenAssetReference`. Three different prop names (`onOpenAsset`, `onSelectAsset`, `onOpenAsset360`) mean "go to this asset."
3. **5 sessionStorage handoff families**: `ax-pending-glossary-term` (written App.jsx:1020 + AppFrame.jsx:1146; read TaxonomyWorkspace.jsx:683), `ax-insights-focus` (HomePage.jsx:1369 → InsightsWorkspace.jsx:633), `gh.workspace.intent.v1:<path>:<kind>:<fqn>` (lib/workspaceIntent.js), `gh.discovery.session.v1:*` (useDiscoveryWorkspace.js:370/213), `axiom.discovery-ai.*` AI-response cache (DiscoveryWorkspace.jsx:96-116).
4. **6 localStorage keys**: `gh-favorite-assets`, `gh-recent-assets` (DiscoveryWorkspace.jsx:378-412, shared into CommandPalette.jsx:11-38), `gh-saved-searches` (:427-455), `gh-discovery-density` (:4840-4846), `gh-pinned-assets` (EntityHero.jsx:13-26), `axiom:profile-avatar:*` (UserChip.jsx:179-228).
5. **3 custom window events**: `ax:select-glossary-term` (dispatched App.jsx:1024, AppFrame.jsx:1150; listened TaxonomyWorkspace.jsx:1203 — paired with the sessionStorage key because the target may not be mounted), `gh:open-command-palette` (DiscoveryWorkspace.jsx:5963 → AppFrame.jsx:469), `ax:insights-focus` (listener InsightsWorkspace.jsx:654 with **no dispatcher in the repo — dormant code**).
6. **`workspaceIntent` module singleton** (set/peek/consume over sessionStorage, keyed by `window.location.pathname`) — the sanctioned side channel for entity tab + lineage context (lib/workspaceIntent.js:1-43).
7. **`axiomQueryClient` module singleton used as a bus** — imported directly (not via hooks) in useAssetDetail.js, useLineage.js, useAssetSearch.js; `setQueryData`/`invalidateQueries` called from TaxonomyWorkspace.jsx:1056-1086, 1802, 2018-2019, useGapAnalysis.js:62, useClassificationRecommendations.js:87-92 to coordinate cross-surface freshness.

**The same user intent — "open this glossary term" — takes three mechanisms at once** (sessionStorage + custom event + module change, App.jsx:1016-1026). That is the dispersion disease in one line.

### 2.4 Nav rail vs surfaces

`SideIconRail.jsx:34-45` lists 8 nav items (home, discovery, governance, taxonomy, lineage, audit, inbox, admin). **Not in the rail**: `insights`, `capabilities`, `cde`, `help`, and `entity`. Entity/Asset 360 is a special conditional item (`ASSET_360_NAV_ITEM`, `requiresAsset: true`, SideIconRail.jsx:48-53) that only appears when a `currentAssetFqn` is in flight — see §4.

## 3. Data loading

### 3.1 Foundation (good bones, unevenly used)

- One shared `QueryClient` (`lib/queryClient.js`): staleTime 60s, gcTime 15m, no focus/reconnect refetch, retry:false. No global polling.
- One network funnel `request()` (api.js:706) with `ApiError` (status, payload, request ids; :482), a 45s AbortController timeout (:716), and a bespoke one-shot 650ms retry inside `fetchLineage` on 502/503/504 (api.js:1096, 1109).
- Canonical envelope `{data, meta, errors}` with `unwrapEnvelope` (api.js:1463); `meta.state ∈ loading|degraded|unavailable|non_authoritative|available`, `meta.capabilities.hydrating`, `meta.warnings[]`, `meta.inventoryHydrating`; plus surface-specific status objects (`queryState.state` api.js:420, `inbox.state`, `runtime.state`, `bootState`+`bootstrapContract.mode`, per-section asset-360 states, `authoritative`+`provenance.warnings`), and a synthetic `nonAuthoritative` flag from `lib/nonAuthoritativeEvidence.js`.

### 3.2 Pattern census

Of ~27 data hooks, **~24 are react-query**, 2 are genuinely ad-hoc (`useAxiomAiConversation.js:55-62`, `useAssetMetadataEditor.js:142-207` — manual loading/error state), and `useDiscoveryWorkspace.js` is a hybrid (RQ-backed via `useDiscoveryResults` :417 plus its own filter/debounce state layer, setTimeout debounce :318).

But components bypass the hooks layer in two ways:
- **10 inline `useQuery` declarations in component bodies** (AuditBrowserWorkspace.jsx:510, 526; CdeWorkspace.jsx:213, 227; AdminWorkspace.jsx:662, 894; TaxonomyWorkspace.jsx:735, 742; InboxPage.jsx:89, 94).
- **8+ imperative `fetch().then()` sites**: GovernanceWorkspace's northstar workbench fetch with hand-rolled AbortController/cancelled-flag/`setNorthstarLoading` (GovernanceWorkspace.jsx:747-777) and request-detail loads (:951, :1071 — the second without abort); DiscoveryWorkspace AI recommendations with manual abort + timeout + request-seq guard (:5560-5595); CommandPalette debounced search + glossary (CommandPalette.jsx:111, 133); fire-and-forget `prefetchLineage` (DiscoveryWorkspace.jsx:4823, EntityWorkspace.jsx:2220).

### 3.3 Envelope-handling divergence (the second dispersion cause)

Envelope status strings are interpreted in **~55 non-test files**; heaviest: HomePage 88 refs, DiscoveryWorkspace 85, AdminWorkspace 64, LineageWorkspace 52, AuditBrowserWorkspace 46, TaxonomyWorkspace 40, InsightsWorkspace 39, EntityWorkspace 30, App 24.

- **11+ copy-pasted implementations of "is this envelope hydrating"**: local `envelopeHydrating` in CdeWorkspace.jsx:19, AdminWorkspace.jsx:15, AuditBrowserWorkspace.jsx:22, `hydratingEnvelope` in TaxonomyWorkspace.jsx:76, plus hook-level variants in useLineage, useAssetDetail, useAsset360, useDiscoveryResults, useLineageRecommendations, useInsightsDashboard, useCommandCenter — all the same predicate (`meta.state==="loading" || meta.capabilities.hydrating`).
- **10-12 divergent loading/empty/degraded/unavailable renderings**: northstar's EmptyState/DegradedBanner/StatusPill are imported by only 6 of ~13 surfaces; HomePage (88 refs) rolls its own evidence-kind/warning rendering (:435, 1082, 1664) and does not use DegradedBanner; App.jsx synthesizes degraded governance envelopes itself (:214) and computes bootState cascades at :687-692/:805/:1035; AppFrame has its own shell cascade (:480-599); Discovery/Lineage/Entity/Governance render inline banners; further variants in AppErrorBoundary, WorkspaceDiagnosticsSurface, WorkspaceSetupWizard, ShellStatePrimitives, shellStatusLabels.js.

### 3.4 Polling inventory

14 polling sites. Standard cadence 3s (lineage, lineage-recs, discovery, asset-detail, asset-360, bootstrap, taxonomy ×2, cde, admin, audit); outliers 2.5s (governance summary useGovernanceSummary.js:32), 4s (insights useInsightsDashboard.js:87), 15s (command center useCommandCenter.js:75; runtime status App.jsx:325). **Only the two lineage polls are attempt-bounded** (`LINEAGE_POLL_ATTEMPT_LIMIT=15` ≈45s with module-scoped per-fqn spacing, useLineage.js:139-190; useLineageRecommendations.js:37-49). The other 12 are open-ended — they stop only if the server flips `meta.state` off `"loading"`; a backend that stays "loading" polls forever. Also of note: EntityWorkspace stages lineage warm-up with hand-tuned setTimeout waves at 360ms/1.1s/2.8s/5.6s (EntityWorkspace.jsx:2134-2218).

## 4. EntityWorkspace deep-dive (the Asset 360 record)

- **Size/structure**: `EntityWorkspace.jsx` is 3,227 lines, one file, ~30 internal components (`Asset360Hero` :573, `Asset360Overview` :820, `EntityShellPlaceholder` :1003, `MetadataEditorPanel` :1153, `ActivityFeed` :1323, `QueryRecords` :1385, `Asset360Panel` :1508, plus AttributeList/MetricTile/OwnerList/PropertyList/CoverageSignalRows…). The default export starts at :1594 and declares **~15 useState + ~25 useMemo** before the first render branch.
- **Old shell**: imports gh-generation primitives throughout — `SurfacePanelSection`/`SurfaceTabs` (:47), `LoadingState`/`SkeletonBlock` (:48), gh-primitives Breadcrumbs/OwnerAvatar/TabIcon/ProfilePanel/QualityPanel (:49-57); styled by pure-legacy `entity.css` (126 gh / 0 ax selectors, 52 raw hexes). Zero northstar imports. The one modern element is the embedded `LineageCanvasV2` (:45-46).
- **Why it isn't nav-reachable**: it has no rail entry — `ASSET_360_NAV_ITEM.requiresAsset: true` means the rail shows Asset 360 only when App passes a `currentAssetFqn` (which is `routeAssetFqn || discoveryRouteState.previewAssetFqn`, App.jsx:527). With no asset in the route there is no way to reach any entity page from the shell; and clicking it doesn't navigate directly — it runs `openAssetRecordSafely` (App.jsx:1120-1133), a pre-flight availability check that can *redirect you to Discovery instead*. The page is a destination without an address book: reachable only via other surfaces' `onOpenAsset` callbacks or a hand-typed `/entity/<fqn>` URL.
- **Capability-gate labyrinth**: :1610-1698 computes ~25 booleans crossing 4 signal sources (bootstrap capabilities × runtime feature flags × workspaceAccess gates × non-authoritative-evidence detection) to decide tab visibility — e.g. `lineageTabAvailable = lineageAvailable && lineageRolloutAvailable && workspaceLineageRouteAvailable` (:1654). This is exactly the "bootstrap pessimism" CLAUDE.md warns about, re-derived ad hoc per surface.
- **Data dependencies & load waterfall** (4 stages deep):
  1. `useSeededAssetContext(assetFqn, bootstrap, seedAssets)` — instant seed from props (:1736);
  2. `useAssetDetail(assetFqn, {sections})` — sections vary **by active tab** (`detailSectionsForTab` :253), react-query with self-scheduled `assetDetailRefetchInterval` polling (useAssetDetail.js:127, 621) and a header-batch prefetcher that previously fanned out 47 requests (useAssetDetail.js:358-388);
  3. `useAsset360(assetFqn)` — gated on `enabled: baseAsset?.fqn === assetFqn` (:1746-1748), i.e. **waits for stage 2** before firing, then merges via a 25-line `compositeBaseAsset` memo (:1751-1777) + `localOverrides` overlay (:1778);
  4. `useLineage(assetFqn, lineageEnabled)` — enabled only when tab is Lineage/Queries, or Overview *after* `overviewLineageWarm && loadedSections.has("header")` (:1815-1824). The loadedSections-key churn here previously re-fired /api/lineage 5-9× per view (comment :1798-1803).
  Tab state and lineage context arrive via `peekWorkspaceIntent` sessionStorage, not URL (:1699-1709). Editing state (metadata draft, column draft, mutations) lives beside display state in the same component (:1710-1722).
- **Verdict**: this is the most important page in the product (every surface links *to* it) implemented as the least systematized one — old shell, no address for its tabs, a 4-stage waterfall, a per-surface capability calculus, and 30 private components that duplicate the kit.

## 5. Component duplication — concept × implementations

Headline finding: **the design system was largely built and then not adopted.** 9 of 14 northstar components and 5 primitives are orphans (zero non-test importers) while surfaces re-implement the same concepts inline: `northstar/PageHero`, `MetricCard`, `DataTable`, `RightInspector`, `ActionTile`, `BarList`, `DonutMetric`, `HeatmapMatrix`, `Sparkline` and `primitives/EntityHero`, `UserChip`, `AssetHoverCard`, `AuditTimelineDrawer`, `ClassificationEvidenceDrawer` are all defined but unused by any workspace.

| Concept | Shared impl(s) | Adoption | Independent inline impls (file:line) |
|---|---|---|---|
| Page hero | northstar/PageHero (`ax-page-hero`), primitives/EntityHero | **both orphans — 0 usages** | **11**: `gh-discovery-hero` DiscoveryWorkspace.jsx:2206; `ax-asset360-hero` EntityWorkspace.jsx:605/1026; `gh-taxonomy-ns-hero`+`-prototype-hero` TaxonomyWorkspace.jsx:902/1220; `gh-command-center-hero` HomePage.jsx:1621; `gh-governance-ns-hero` GovernanceWorkspace.jsx:1309; `ax-lineage-v2-hero` LineageWorkspace.jsx:505 (+:364); `gh-audit-hero` AuditBrowserWorkspace.jsx:872; `gh-admin-*-hero` AdminWorkspace.jsx:705/1009; `gh-insights-hero` InsightsWorkspace.jsx:728; `gh-cde-hero` CdeWorkspace.jsx:317 |
| KPI/stat tiles | northstar/MetricCard + DonutMetric/BarList/Sparkline | **orphans — 0 usages** | **7 systems**: `gh-command-center-kpi-*` (Home), `gh-insights-kpi-*`, `gh-cde-kpis`, `gh-audit-kpis`, `gh-entity-metric-card`/`gh-preview-stat-*` (Entity), `gh-discovery-preview-metric-grid`, `ax-lineage-v2-rail-stats` |
| Section cards | northstar/SectionCard; ShellLayout SurfacePanelSection/SurfaceWorkbench | SectionCard: **HomePage only** (6×, :1845-2129); SurfacePanelSection: Entity/Capability/Diagnostics | ~10 surfaces roll their own: `gh-taxonomy-panel`, `gh-governance-ns-*-panel`, `gh-insights-card` (+6 variants), `gh-admin-control-card`, `ax-lineage-*-panel`, `ax-asset360-panel` (+4), `gh-asset-preview-section`, `gh-capability-section-*`, `gh-panel` |
| Badges/chips | **3 competing shared**: primitives/StatusBadge (`gh-status-chip`), primitives/MetadataChip (`gh-chip`), northstar/StatusPill (`ax-status-pill`) | StatusBadge: Capability 7×; StatusPill: Taxonomy 5×/Admin 5×/Cde 7×; MetadataChip: Capability 1× | inline spans bypassing all three: Discovery **38**, Entity **27** (own `gh-state-pill`), Diagnostics **26** raw `gh-chip` spans, Governance 5, Home 2; Asset360Drawer defines a private `Chip` (Asset360Drawer.jsx:69); Discovery has own `gh-discovery-status-pill` |
| Tables | northstar/DataTable | **orphan — 0 usages** | **8 inline tables**: EntityWorkspace.jsx:739 (bare), :2768 `gh-schema-table`, :3059 `gh-table`; AdminWorkspace.jsx:780; CapabilityDashboard.jsx:240/357; Asset360Drawer.jsx:232 (inline-styled) |
| Empty/loading/degraded | **two shared families doing the same job**: northstar EmptyState/DegradedBanner (ax) vs ShellState EmptyStateBlock/LoadingState/WorkspaceStateCard/InlineStatusBanner (gh) | northstar: 6 surfaces; ShellState: 7 surfaces + AppFrame + primitives | plus inline: `gh-discovery-empty-state`, `gh-empty-state` (Entity), `ax-lineage-zero-state`, `gh-insights-empty-panel`, `gh-home-status-spinner` |
| Toasts | **none shared** | — | `gh-discovery-preview-action-toast` DiscoveryWorkspace.jsx:4237; Governance status-banner-as-toast (:687-1161); Taxonomy inline banner (:1231) |
| Drawers/modals | ShellLayout SurfaceDrawer (used only by 2 orphan primitive drawers); Asset360Drawer (self-contained, App-only); northstar/RightInspector (orphan) | — | inline dialogs: Discovery popovers :2560/:6547 (`role="dialog"`), Taxonomy scrim+modal :1565/:1663 |
| Tab strips | ShellLayout SurfaceTabs | **EntityWorkspace only** (:1096, :2636) | **6 inline tablists**: DiscoveryWorkspace.jsx:4011/:4407, TaxonomyWorkspace.jsx:1259, LineageWorkspace.jsx:943, AdminWorkspace.jsx:1019, CdeWorkspace.jsx:579, Asset360Drawer.jsx:420 |
| Entity mentions (asset/term/owner/request as link) | **no shared component.** OwnerAvatar(Stack) shared for owners; UserChip/AssetHoverCard orphans | — | per-surface inline `<button onClick={openAssetRecordSafely…}>` with divergent classes: Discovery 24× (`gh-discovery-row-title`), Taxonomy 31×, Cde 14× (`gh-cde-asset-link`), Audit 8×, Entity 5× (`ax-asset360-kv-chip is-link`), Lineage 5× (`ax-lineage-linked-row`), Governance 4×, Home 3×; Entity routes mentions to a drawer while everyone else routes to the record (161 asset360/openDrawer refs); zero `<a href>` anywhere — no mention is middle-clickable |

Adoption census: DiscoveryWorkspace, GovernanceWorkspace, LineageWorkspace import **zero** northstar components; EntityWorkspace imports zero northstar and nine gh-primitives; only Home/Taxonomy/Cde/Admin/Audit/Insights partially adopted the ax kit (mostly just DegradedBanner/EmptyState/StatusPill).

---

# PART II — TARGET ARCHITECTURE (the calls, made)

Design thesis: the product's dispersion has exactly three roots — **(a)** no single component kit (three generations coexist), **(b)** no single data-loading contract (11+ hydration predicates, 12 unbounded polls, 10-12 status renderings), **(c)** no single navigation fabric (7 handoff mechanisms). The rebuild therefore ships three system layers first, then migrates surfaces onto them. Nothing else is allowed to exist afterwards.

## 6. Shared primitives layer — `frontend/src/components/system/`

One kit, one directory, one stylesheet per component, all `ax-*` classes, all tokens. The existing `northstar/` kit is the seed (it is already `ax-*`): components below marked *absorb* start from the northstar implementation; marked *new* are built fresh; everything they replace is deleted at the end of its migration wave. The northstar lesson (§5: 9 of 14 components orphaned) is that building a kit without forcing adoption fails — so the kit ships in Wave A but every migration wave has a hard rule: **a surface exits its wave only when it renders zero non-system chrome**, and the legacy component it replaced is deleted in the same PR so there is nothing to drift back to.

Layout of the directory:

```
components/system/
  PageShell.jsx        SectionCard.jsx     StatTile.jsx      EntityChip.jsx
  DataTable.jsx        StateViews.jsx      Toast.jsx         Drawer.jsx
  TabStrip.jsx         FilterBar.jsx       Badge.jsx         Button.jsx
  index.js             system.css          __tests__/
```

### Contracts

**`PageShell`** *(new; replaces SurfaceHeader ShellLayoutPrimitives.jsx:56, northstar PageHero, and every inline hero)* —
`<PageShell title subtitle eyebrow status={queryStatus} actions tabs={<TabStrip/>} rail={<aside/>} onRetry>{children}</PageShell>`.
Owns: the hero band, the breadcrumb row (from `useAxiomNavigate` context), the page-level status banner (degraded/stale/unavailable — rendered from the `status` envelope, §7, so no surface hand-renders banners), optional right rail slot, sticky tab slot. Every routed surface renders exactly one PageShell. This single component is what makes 13 surfaces feel like one product.

**`SectionCard`** *(absorb northstar/SectionCard.jsx)* — keep contract `{title, eyebrow, subtitle, actions, tooltip, children}`; add `status` prop taking the same envelope-status object so a card can show its own hydrating shimmer / degraded footnote without bespoke markup. Replaces `SurfacePanelSection` (ShellLayoutPrimitives.jsx:177) and the ~181 inline card selector families.

**`StatTile`** *(absorb northstar/MetricCard + DonutMetric + Sparkline as variants)* —
`<StatTile label value delta trend={sparkData} tone hint onClick target={entityRef|surfaceRef}>`. `target` makes every KPI a navigable link through §8 — kills the `onOpenDiscoveryWithFilter` prop chain. Replaces the ~190 hero/KPI selector families (the worst duplication in the product) including EntityWorkspace's private `MetricTile` (:347) and `Asset360SignalCard` (:555).

**`EntityChip`** *(new — the keystone component)* — renders ANY entity mention as a consistent, clickable chip:
```jsx
<EntityChip entity={{ kind: "asset"|"term"|"owner"|"request"|"event"|"column"|"domain", id, label?, meta? }}
            appearance="chip"|"inline"|"row" withHover={bool} />
```
Internally: icon by kind (absorb AssetTypeIcon), label formatting (absorb assetPresentation.js helpers), hover card (absorb AssetHoverCard), and — critically — navigation via `navigate(entityRef)` (§8), rendered as a **real `<a href>`** (router Link) so mentions are middle-clickable and copyable — today zero entity mentions anywhere are anchors (§5), they're all `<button onClick>`. **Rule: no surface may render an asset FQN, owner email, term name, request id, or audit event as raw text or a bespoke button/anchor.** This directly replaces the ~94 per-surface inline `openAssetRecordSafely` buttons with divergent classes (Discovery 24×, Taxonomy 31×, Cde 14×, Audit 8×… §5) and unifies the record-vs-drawer split (`appearance` + `peek` decide, not the surface). Replaces UserChip/OwnerAvatar(Stack)/AssetHoverCard/MetadataChip-as-link and every inline `ownerDiscoveryHref`-style helper (EntityWorkspace.jsx:383).

**`DataTable`** *(absorb northstar/DataTable, extend)* — add `{sort, onSort, rowTarget(row)→entityRef, density, stickyHeader, loading, emptyState, pagination?}`. `rowTarget` + `EntityChip` cells make tables navigation-consistent. Replaces the ~43 inline table implementations across 7 CSS files (gh-discovery-table, gh-audit-browser-table, gh-capability-table, gh-taxonomy-table, gh-profile-columns-table…).

**`StateViews`** *(new file exporting the triad + banner)* — `LoadingState` (skeleton variants: tile/table/card/page), `EmptyState` (absorb northstar/EmptyState: icon, title, body, action), `UnavailableState` (honest-unavailability card: reason string straight from `meta`, retry, no fake data), and `StatusBanner` (absorb northstar/DegradedBanner: degraded/stale/refresh-failed strip). These four are the ONLY status renderings allowed; they consume the §7 status object directly (`<StateViews.ForQuery query={q} empty={...}>`). Replaces WorkspaceStateCard/EmptyStateBlock/LoadingState/SkeletonBlock (ShellStatePrimitives.jsx), the ~56 empty-state selector families, and the 10-12 divergent renderings in §3.3.

**`Toast`** *(new)* — module-level `toast(message, {tone, action})` + `<ToastHost/>` mounted once in AppShell. Replaces the 3 CSS toast families (`gh-discovery-preview-action-toast` app.css:7686 etc.) and satisfies the CLAUDE.md rule that unwired buttons must stage intent visibly.

**`Drawer`** *(new base; keep feature drawers as thin content)* — `<Drawer open onClose title width footer>` with focus trap, ESC, URL-bound open state where the drawer is addressable (Asset 360 preview drawer binds to `?peek=<fqn>`, §8). Asset360Drawer, AuditTimelineDrawer, ClassificationEvidenceDrawer become content rendered inside it; SurfaceDrawer (ShellLayoutPrimitives.jsx:249) and inline overlays are deleted.

**`TabStrip`** *(new)* — `<TabStrip tabs=[{key,label,icon,badge,disabled,disabledReason}] value onChange/>`; when given `param` it binds itself to a URL search param via §8 (`<TabStrip param="tab" …/>`) so tabs are addressable by default. Replaces SurfaceTabs (ShellLayoutPrimitives.jsx:84) and the ~84 tab selector families across 9 files.

**`FilterBar`** *(new)* — declarative facet model `{key, label, options|search, multi}` + `value` + `onChange`, URL-serialized by §8's param conventions (kills the bespoke JSON `?filters` plumbing being re-passed through 8-arg builders). Discovery is the flagship consumer; Audit, Taxonomy, Governance queues reuse it.

**`Badge` / `Button`** *(new, trivial but load-bearing)* — `Badge {tone, size}` replaces the ~147 chip/pill/badge selector families and StatusBadge/StatusPill/shellStatusLabels; `Button {variant: primary|secondary|tertiary|icon, tone, size}` replaces the 4-file `.gh-primary-button` collision and ActionButton. No surface writes its own button CSS again, ever.

Ownership rule: `components/system/` has its own tests (`__tests__/`), its own `system.css`, and NO imports from `components/*` outside `system/` — dependencies point inward only.

## 7. One data-loading contract — `useAxiomQuery`

New file `frontend/src/hooks/useAxiomQuery.js` (plus `lib/envelope.js`). It is a thin, opinionated wrapper over `useQuery` against `axiomQueryClient` that codifies everything the 27 hooks each half-implement:

```js
const q = useAxiomQuery({
  key: ["asset-detail", fqn, sections],
  fetch: (signal) => fetchAssetDetail(fqn, { sections, signal }),
  enabled,
  seed,                    // optional seed data → status becomes "hydrating", never "loading"
  poll: { interval: 3000, maxAttempts: 15 },   // BOUNDED. maxAttempts required when interval set
  sections,                // optional: poll continues until envelope.loadedSections ⊇ sections
});
// returns { data, status, meta, warnings, refresh, isPolling }
// status ∈ "loading" | "hydrating" | "available" | "degraded" | "unavailable" | "error"
```

Codified semantics (single source of truth in `lib/envelope.js`):
- `envelopeStatus(payload, {hasSeed, refreshError})` — THE one implementation of the predicate currently copy-pasted 11+ times (§3.3): `meta.state`, `capabilities.hydrating`, `inventoryHydrating`, `nonAuthoritative` → `unavailable`, refresh-failure-over-data → `degraded` (the pattern App.jsx:562-568 hand-rolls for governance).
- **Bounded polling only.** `poll.maxAttempts` is mandatory; on exhaustion status degrades to `degraded` with warning "server still hydrating after N attempts" instead of polling forever. The lineage module-scoped attempt ledger (useLineage.js:139-190) generalizes into the wrapper. This fixes the 12 unbounded polls in §3.4 without changing cadences.
- Seed/SWR: seed renders instantly as `hydrating` (never a blank "loading" flash — the hydration-zero bug class already noted at App.jsx:417-419); refresh failures never wipe rendered data, they flip status to `degraded` and surface `warnings`.
- `no-store` awareness: fetchers that must bypass cache declare `fresh: true` → wrapper sets `staleTime: 0, gcTime: 0` instead of components calling `fetch` directly.
- Mutations: `useAxiomMutation` sibling wrapping optimistic-update + rollback (the App.jsx:658-672 inbox pattern) and query invalidation by key prefix.

**The rule** (enforced, §10 guardrails): *no component imports `fetch`, `apiFetch`, `useQuery`, or `axiomQueryClient`; no component interprets `meta.state`. Components consume `q.status` and render it exclusively through `StateViews`.*

### Hook disposition map

| Existing hook | Verdict | Note |
|---|---|---|
| useBootstrap, useRuntimeStatus | **refactor** onto useAxiomQuery | keep semantics; bound the 3s/15s polls (bootstrap maxAttempts ~40 ≈ 2min then degraded) |
| useCommandCenter | **refactor** | seed goes through `seed` param; delete bespoke seed/meta merging in App.jsx:707-765 |
| useInsightsDashboard, useGovernanceSummary, useDiscoveryResults, useAssetDetail, useAsset360, useCapabilityDashboard, useGapAnalysis, useClassificationRecommendations, useAssetSearch, useAccessExplain, useAssetCustomProperties, useAssetProfile, useAssetQuality, useAssetDatabricksEvidence, useColumnLineageTrace, useGovernanceAuditTimeline, useGovernanceGlossaryTerm | **refactor** | mechanical: swap useQuery→useAxiomQuery, delete local hydration predicates and refetchInterval fns |
| useLineage, useLineageRecommendations | **refactor** | their bounded-poll ledger BECOMES the wrapper's poll engine; hook keeps only lineage-shape logic; `useLineageGraphV2` adapter unchanged (it stays the single lineage normalization point per CLAUDE.md) |
| useAxiomAiConversation | **keep ad-hoc** (streaming/imperative send doesn't fit query semantics) but route status rendering through StateViews |
| useAssetMetadataEditor | **refactor** to useAxiomQuery + useAxiomMutation |
| useDiscoveryWorkspace | **split**: results loading → useAxiomQuery; filter/URL state → §8's `useSurfaceParams`; delete its sessionStorage snapshot revival (URL is the snapshot) |
| useSeededAssetContext | **keep** (pure derivation) |
| useAppRouteState | **delete** — replaced by §8 |
| 10 inline component useQuery sites + GovernanceWorkspace/CommandPalette imperative fetches (§3.2) | **delete** — extract to surface hooks on useAxiomQuery (`useAuditEvents`, `useCdeDashboard`, `useAdminControlCenter`, `useTaxonomyOverview`, `useInboxWork`, `useGovernanceWorkbench`, `usePaletteSearch`) |

## 8. One navigation system

New files: `frontend/src/nav/routes.js` (route table), `nav/refs.js` (entity/surface ref model), `nav/useAxiomNavigate.js`, `nav/useSurfaceParams.js`.

### The ref model

```js
// entityRef — where a THING lives
{ kind: "asset",   fqn }                    → /assets/<fqn>            (+ ?tab=)
{ kind: "term",    id }                     → /glossary/<id>
{ kind: "owner",   id: email }              → /discovery?owner=<email>
{ kind: "request", id }                     → /stewardship?request=<id>
{ kind: "event",   id }                     → /audit?event=<id>
{ kind: "lineage", fqn }                    → /lineage/<fqn>
// surfaceRef — where a SURFACE lives
{ surface: "discovery", params: { q, filters, sort, view, peek } }
```

`navigate(ref, { params, replace, peek })` is the ONLY navigation API. `EntityChip`, `StatTile.target`, `DataTable.rowTarget`, command palette, and the rail all call it. It resolves through the route table, serializes params per the conventions below, and uses react-router underneath. A `usePeek(ref)` variant opens the Drawer bound to `?peek=` instead of leaving the surface.

### URL-state conventions (every surface fully addressable)

1. Path identifies surface + primary entity: `/assets/:fqn`, `/lineage/:fqn`, `/glossary/:termId`. Legacy aliases (`/entity/*`, `/command-center`, `/sk`, `/glossary-cdes`…) remain as redirects in the route table only.
2. Search params are surface-scoped and flat: `?tab=` (any tabbed surface — entity tab finally addressable), `?q=`, `?sort=`, `?view=`, facet params (`?domain=`, `?tier=`, repeatable), `?peek=<fqn>` (Asset 360 drawer — addressable, shareable), `?request=`, `?event=`, `?term=` (persistent, not self-deleting).
3. **Discovery params no longer ride along on other surfaces** — the 8-positional-arg `buildCanonicalUrl` threading dies; back/forward restores Discovery state because it's in Discovery's own history entries.
4. Sub-state worth restoring goes in the URL; preference-state (density, favorites, pins) stays in localStorage behind one typed helper `lib/prefs.js` — the only storage API allowed.
5. `useSurfaceParams(schema)` gives each surface typed read/write of its own params (default replace, `push:true` for fresh openings — preserving today's push/replace discipline, useAppRouteState.js:427-449).

### Killed outright (with their replacements)

| Mechanism | Replacement |
|---|---|
| `ax-pending-glossary-term` sessionStorage + `ax:select-glossary-term` event (App.jsx:1016-1026, AppFrame.jsx:1146-1150, TaxonomyWorkspace.jsx:683, 1203) | `navigate({kind:"term", id})` → `/glossary/<id>` — works mounted or not |
| `ax-insights-focus` sessionStorage + dormant `ax:insights-focus` listener (HomePage.jsx:1369, InsightsWorkspace.jsx:633, 654) | `/insights?focus=risk` param + scroll-on-mount |
| `gh:open-command-palette` event (DiscoveryWorkspace.jsx:5963 → AppFrame.jsx:469) | palette opener exposed from AppShell context |
| `workspaceIntent` singleton (lib/workspaceIntent.js; entity tab, lineage context) | `?tab=` and `?context=` params |
| `window.history.replaceState` bypasses (TaxonomyWorkspace.jsx:697, 877) | `useSurfaceParams` |
| ~16 drilled callbacks (`onOpenAsset`/`onSelectAsset`/`onOpenAsset360`/`onOpenDiscoveryWithFilter`/…) | `navigate()`/`usePeek()` imported where needed — App.jsx stops being a switchboard |
| `location.state.fresh` | explicit `push:true` option |
| discovery sessionStorage snapshot (useDiscoveryWorkspace.js:213, 370) | URL is the snapshot |

### Route table mechanism

`nav/routes.js` exports `ROUTES: [{ surface, path, aliases[], element, nav: {section, label, icon, badgeKey} | null, paramsSchema }]`, consumed by (a) a real `<Routes>` tree in `AppShell` (replacing App.jsx's 13-branch if/else — each surface stays `lazy()`), (b) the rail (which today hides insights/capabilities/cde/help because SideIconRail hard-codes 8 items), (c) `navigate()` resolution, (d) the command palette. The product-architecture sibling defines the final surface list; this table is where their IA plugs in — adding a surface is one entry, and it is automatically routable, raily, palette-searchable, and addressable.

## 9. CSS consolidation

### End state

```
src/design/tokens/            (keep; 133 tokens; delete --gh-* aliases at the end)
src/components/system/system.css   (~2,500 lines: all primitives, all ax-*)
src/app-shell/shell.css            (~800 lines: rail, header, palette, toasts)
src/surfaces/<surface>/<surface>.css  (≤300 lines each: layout-only, ax-* prefixed,
                                       no buttons/chips/tables/cards — those are system)
```

Target ≈ 8-9k lines total, down from 32,972 (-73%). All imports in main.jsx in fixed order (tokens → system → shell → surfaces); **component-level CSS imports are banned** (removes the operations-pages.css cascade nondeterminism, §1.3). `!important` budget: 0 outside third-party overrides (from 1,451).

### What gets deleted, when

| File | Fate |
|---|---|
| lineage-v2.css | keep — rename into surfaces/lineage/, already clean |
| northstar.css | split: ax-* system rules → system.css; gh-* remainder dies with each surface migration |
| operations-pages.css, discovery.css, entity.css, shell-rail.css, governance.css, capability-dashboard.css, insights.css, lineage.css | deleted at the end of their surface's wave (§10) |
| app.css | shrinks per wave; the 36 `data-theme=dark` blocks + 756 `!important` die with the shell rewrite; deleted last |
| tokens colors.css `--gh-*` aliases | deleted in the final wave; build fails on any survivor |

### Migration without a flag day

Per-surface, in wave order (§10): a surface migrates by (1) rebuilding on system components — which carry their own CSS, (2) moving surface-specific layout rules into `surfaces/<s>/<s>.css` under `ga-` names, (3) deleting that surface's legacy sheet + its slice of app.css. Old and new surfaces coexist because legacy sheets remain loaded until their owning surface's wave completes — the system kit's `ax-*` classes never collide with `gh-*`.

### Enforcement (CI, from Wave A day 1)

- `scripts/check-css.mjs` in the vitest/CI pipeline: fail on (a) new `gh-` class in any changed JSX/CSS, (b) raw hex color outside `design/tokens/`, (c) `!important` outside a whitelisted third-party-override block, (d) `import "*.css"` outside main.jsx, (e) local re-definition of `--ax-*` outside tokens (kills the 38 shadow definitions).
- Ratchet file with current gh-count per file; the count may only go down.

## 10. Migration plan — ordered waves, disjoint file ownership

Sizing assumes parallel subagents per CLAUDE.md rules (checkpoint commits, no stash, explicit file ownership; every wave ends with the deploy + independent subagent browser signoff + owner sweep loop).

### Wave A — the system, no visual change (3 parallel tracks, disjoint)

- **A1 · System kit** — owns `components/system/**`, `system.css`. Builds §6 components + their vitest suites (render contracts, a11y roles, status-prop rendering). Northstar absorbed by copy, not edit — `northstar/` untouched until Wave C consumers move.
- **A2 · Data contract** — owns `hooks/useAxiomQuery.js`, `lib/envelope.js`, plus mechanical refactors of the 19 "refactor" hooks (§7 table). Behavior-preserving: same keys, same cadences, now bounded. Existing hook tests keep passing — that is the acceptance gate.
- **A3 · Nav system** — owns `nav/**` only. Builds routes.js/refs.js/useAxiomNavigate/useSurfaceParams + alias redirects + tests (every legacy URL in §2.1 must resolve). Nothing consumes it yet.
- Conflict-free by construction: A1/A2/A3 touch zero shared files. `frontend/src/components/lineage-v2/**`, `LineageWorkspace.jsx`, `lineage-v2.css` stay off-limits (CLAUDE.md parallel-work rule).

### Wave B — shell + Asset 360 flagship (2 tracks)

- **B1 · AppShell rewrite** — owns new `app-shell/**` (AppShell.jsx, Rail.jsx, Header.jsx, shell.css) + `App.jsx` + `main.jsx`. `<Routes>` from ROUTES table; App.jsx shrinks to ~150 lines (providers + shell + routes); the lifted discovery/governance state buses die (surfaces own their queries; the inbox badge becomes a `useInboxWork` hook consumed by Rail); Axiom AI chat extracted from AppFrame into `app-shell/AxiomAiDock.jsx`. AppFrame.jsx deleted.
- **B2 · Asset 360 rebuild** — owns new `surfaces/asset/**`. EntityWorkspace.jsx (3,227 lines) is **rewritten, not migrated**: PageShell + TabStrip(`?tab=`) + SectionCards + EntityChips; the 4-stage waterfall collapses to two parallel `useAxiomQuery` calls (`asset-detail?sections=…` + `asset-360`) with seed from route-loader context — 360 no longer waits on detail; the 25-boolean capability calculus moves to one `lib/capabilities.js` helper `surfaceGates(bootstrap, runtimeFlags, workspaceAccess)` honoring the trust-live-API-over-bootstrap rule; Asset 360 gains a real rail entry + `/assets/:fqn` address, and the drawer binds `?peek=`. This page is the flagship: it exercises every system component and both contracts, and every other surface links into it.
- B1/B2 disjoint (shell vs surface files); both land behind the alias-redirect net so no deep link breaks.

### Wave C+ — surface-by-surface (order + rationale; one owner each, parallel in pairs)

1. **C1 Discovery** (biggest file 6,797 lines, most handoffs; FilterBar+DataTable flagship; deletes discovery.css's cream fallbacks + sessionStorage snapshot) ∥ **C2 Home** (already ax-leaning; StatTile/SectionCard conversion; deletes the App.jsx command-center seed synthesis remnants).
2. **C3 Governance/Stewardship** (imperative fetches → hooks; request `?request=` addressable) ∥ **C4 Taxonomy+CDE** (deletes history.replaceState bypasses, `?term=` becomes persistent; absorbs CdeWorkspace as `/glossary?tab=cdes` per today's canonicalization).
3. **C5 Audit + Inbox** (inline useQuery → hooks; `?event=` addressable) ∥ **C6 Insights + Capabilities + Admin** (rail entries from route table; deletes insights.css/capability-dashboard.css).
4. **C7 Lineage** last (v2 kit already clean; only PageShell/status/nav adoption — minimal churn honoring the don't-touch list until the end).
5. **C8 Cleanup**: delete `northstar/`, `primitives/` leftovers, ShellLayout/ShellStatePrimitives, workspaceIntent.js, remaining legacy CSS, `--gh-*` token aliases; flip the CI ratchet to zero.

Rationale for the order: highest-traffic + highest-debt first (Discovery), cheap wins pairing (Home), then write-path surfaces (Governance/Taxonomy) once the kit has proven itself on read paths, then long-tail, then the already-clean lineage.

### Test strategy

- **Kit tests carry the burden**: system/ components get exhaustive vitest contracts (status rendering per envelope state, keyboard/a11y, EntityChip per kind, TabStrip URL binding) — so surface tests stop re-testing chrome and shrink to data-wiring assertions.
- **What breaks and how it's caught**: envelope regressions → `lib/envelope.js` table-driven tests over recorded payloads (loading/hydrating/degraded/unavailable/non_authoritative fixtures); route regressions → routes.test walks every legacy alias + param permutation from §2.1-2.2; per-surface `.gaps.test.jsx` files (existing pattern, components/__tests__/) are rewritten per wave to assert the new contract, not the old DOM.
- **Live verification**: per CLAUDE.md every wave closes with `npm run build`, dev-target deploy, per-surface independent subagent browser walks (`SIGNOFF: PASS` required), owner sweep, and for waves B and C1 the full four-role critical-review swarm.

### Guardrails against re-dispersion (permanent)

1. CI check-css (§9) — no gh-, no raw hex, no CSS imports outside main.jsx, no `!important`.
2. ESLint `no-restricted-imports`/`no-restricted-syntax`: `fetch`/`apiFetch`/`useQuery`/`axiomQueryClient` banned outside `hooks/` + `lib/`; `sessionStorage`/`localStorage` banned outside `lib/prefs.js`; `dispatchEvent(new CustomEvent` banned outside `app-shell/`; `window.history` banned everywhere.
3. `refetchInterval` may only appear inside useAxiomQuery — polling is always bounded.
4. New surface = ROUTES entry + `surfaces/<name>/` dir; PR template requires naming which system components it composes; any new one-off button/chip/tab/table/empty-state in a surface file is a review blocker.
5. The dependency direction is law: `surfaces → system → tokens`, `surfaces → hooks → lib`; nothing imports from a surface.

