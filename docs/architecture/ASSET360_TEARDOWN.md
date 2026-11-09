# Asset 360 / Entity Page — Forensic Teardown

Audited 2026-07-21 against live dev app `https://atlas-2543889327043640.aws.databricksapps.com`, 7 assets across 7 catalogs
(emet.enterprise_metadata_ops.product_mortgage_signal, finance_prod.curated.revenue_daily, finance_prod.gold.revenue_recognition,
main.emet.run_history, customer_360.gold.customer_profile, hr_secure.confidential.compensation_band, sales_prod.silver.orders).
Evidence: API captures in `arch_entity/api/`, screenshots + widget census in `arch_entity/shots/` (report.json), warehouse ground truth via SQL.
Probe script: `frontend/scripts/qa_tmp_a360_teardown.mjs`. Console errors during all runs: **0**.

---

## 1. Numbered findings (P0 → P3)

### P0-1 — Asset 360 nav entry is dead code; the surface is unreachable from the menu
`SideIconRail.jsx:47-53` defines `ASSET_360_NAV_ITEM { key:"asset360", moduleKey:"entity", requiresAsset:true }` — exported, unit-tested
(`__tests__/SideIconRail.test.jsx:30`), and **never rendered**: `NAV_SECTIONS` (line 55) is built exclusively from `NAV_ITEMS`, which does not
include it. The rail's click handler even has an `entry.moduleKey === "entity"` branch (line 118) that can never execute. Live nav census
confirms 8 items, none is Asset 360 (`shots/report.json → nav.railItems`). The page exists only behind other surfaces' row clicks.

### P0-2 — Any tab switch >20s after load regresses the whole page to the loading shell (the "old shell" flash)
Screenshot `shots/..._tab_Profile.png`: clicking **Profile** replaced the fully-loaded record with the `EntityShellPlaceholder`
("Loading asset record", skeleton cards, amber alert, tab bar reset to Overview, all tab clicks no-ops — placeholder tabs have
`onChange={() => {}}`, EntityWorkspace.jsx:1101).
Root cause: `useAssetDetail.js:609` calls `readCanonicalDetail(assetFqn, { maxAgeMs: null })` intending "no age limit", but line 97 computes
`options.maxAgeMs ?? DETAIL_CACHE_TTL_MS` — **`null ?? x` evaluates to `x`**, so the "no limit" read actually enforces the 20s TTL. After 20s
the canonical cache reads as absent → `placeholderData` is null → switching to a tab whose sections aren't in the request cache
(Profile/Quality request new section keys, EntityWorkspace.jsx:253-280) makes `query.isPending && !detail` true → `assetDetail.loading && !asset`
→ full placeholder shell (EntityWorkspace.jsx:2228). Same `null` misuse inside `setCanonicalDetail` (useAssetDetail.js:170) undermines the
"keep authoritative data on a degraded refetch" fix. One-token bug (`null` → `Infinity`/omit), page-wide blast radius.

### P0-3 — Composite /360 endpoint hard-codes Freshness, Quality, and Access as "unavailable" — forever, for every asset
`axiom_metrics.py:1693-1719`: `freshness: {state:"unavailable"...}`, `quality: {state:"unavailable", message:"Quality runs are not included in
this composite payload yet."}`, `access: {state:"unavailable"...}` are literal constants. No code path ever populates them. Consequences:
- The hero freshness card can never show a real state; the drawer's Freshness fact and Quality/Access tabs are placeholders **by construction**
  (drawer Quality tab literally prints the backend's apology string — `Asset360Drawer.jsx:447-456`).
- Meanwhile real quality/profile/access endpoints exist and answer in ~0.5-1.2s (`/api/assets/<fqn>/quality`, `/profile`, `/access-explain` —
  all probed 200). The composite simply never joins them.

### P0-4 — The "DATA UPDATED" hero card is wrong three ways at once (the owner's "text transposed" example)
Live census (`report.json`, every one of 7 assets): label **DATA UPDATED**, value **"Unavailable"**, detail **raw ISO
"2026-05-03T19:51:25.309000Z"**, plus a **fake sparkline**. Screenshots also catch the raw ISO rendered as the headline value, wrapped
mid-string ("2026-05-\03T19:51:25.309000Z").
- Value/detail transposed: `Asset360SignalCard` value = `statusText(freshness.state)` where state is the hard-coded "unavailable" (P0-3) →
  headline "Unavailable"; the actual timestamp is relegated to the detail slot **unformatted** (EntityWorkspace.jsx:783-812).
- The label lies about semantics: the frontend comment (EntityWorkspace.jsx:801-805) claims `updatedAt` is a Delta data write; the backend maps
  `information_schema.last_altered` (a metadata-change time) into `updatedAt` (assets.py:1267-1269). "DATA UPDATED" is actually
  "metadata last altered".
- The sparkline is a hard-coded static SVG path (EntityWorkspace.jsx:565-567) — identical fake trend for every asset. Data-dishonesty by decoration.
- During load, the same card is labeled "Freshness" (placeholder, line 1088) then flips to "Data updated" — label churn.

### P1-5 — Header actions are dishonest controls
Live census: `Request Change`, `Open Lineage`, `Certify ⌄`, `⋮` (all enabled).
- **Certify ⌄** renders a dropdown caret but has no dropdown, writes nothing, audit-logs nothing, never updates the badge — it is
  `onOpenGovernance(asset.fqn)` (EntityWorkspace.jsx:662-668), a plain navigation to Stewardship.
- **Request Change** is the *same* `onOpenGovernance` call (line 637) — two differently-styled buttons, one identical action, neither
  pre-stages a request for this asset beyond `?asset=` scoping.
- **⋮ kebab** is aria-labeled "More asset actions" but is a copy-share-link button (lines 670-672, `copyShareLink`) — no menu.
- **"Lineage Unavailable"**: bootstrap reports `tableLineage {available:false, state:"unknown", reason:"No lineage-observed catalogs…"}` and
  flag `table_lineage_surface {enabled:false}` (live curl), while the per-asset lineage API returns a real graph (product_mortgage_signal:
  1 upstream edge, 2 nodes — `api/*.lineage.json`). `tableLineageAvailable` requires `state === "available"` (capabilities.js:26-31), so the
  first paint says "Lineage Unavailable"; it flips to "Open Lineage" only after `/api/runtime/status` (~1.5s, whose capability copy says
  available:true) merges into `mergedBootstrap` (App.jsx:341-351). On any session where runtime status is slow or fails, the button stays
  disabled against live lineage data — exactly the CLAUDE.md "bootstrap pessimism" violation. Meanwhile Overview's "View all usage" /
  "Related Assets → View all" links call `onOpenLineage` unconditionally — the page can simultaneously claim lineage is unavailable in the
  header and link into it below the fold.

### P1-6 — First-visit hydration takes minutes while widgets show dashes; client polls every 3s indefinitely
Cold `GET /api/assets/<fqn>?sections=header,activity,schema,operational,profiler,properties` took **5.4-7.1s** and still returned
`loadedSections:["header"]` with `state:"loading"` (all 7 assets; `api/*.detail.json`). `GET /api/axiom/assets/<fqn>/360` returns in ~0.5s but
`state:"loading"`, `loadedSections:[]`, empty schema/activity/usage; a background thread warms the full detail (axiom.py:774-801) — observed
completion ~4 minutes after first touch (17:04 → 17:08 re-poll: schema 22 cols, activity 40). Until then the Overview renders "—" everywhere
and both `useAsset360` and `useAssetDetail` refetch on 3s intervals (useAsset360.js:86-88, useAssetDetail.js:127-129). Warm loads are fine
(shell 150ms, hero 350-1000ms, warm hero reload 3.9s on the deep asset), so the pain is concentrated on first-ever views — which is what a
demo audience always hits.

### P1-7 — Activity is rendered from the poorest projection of rich stored data
UI: "Task updated 2026-07-21T15:04:19.000Z" (Overview rail, no actor, raw ISO, click → generic Stewardship). The API payload for the same
entry carries `createdBy:"abarreto@shorecp.com"`, `status:"Pending"`, `detail:"open"`; the Overview rail renders only
`item.createdAt || item.actorEmail || item.detail` (EntityWorkspace.jsx:947) — **`createdBy` is fetched but never rendered** (field-name
mismatch: it checks `actorEmail`). The store row (`emet.axiom.activity_events`, verified by SQL) additionally holds `task_id`,
`thread_id`, and `payload_json` with **priority ("p1")** — dropped entirely. The Activity tab does show the actor but concatenates text
without separators: "Task updatedPending open abarreto@shorecp.com • 2026-07-21T15:04:19.000Z". 360 activity also mixes humanized and raw slug
titles ("Task updated" vs "task-status-updated" / "task-triage-updated") because `metadataAudit` items pass `item.action` through raw
(axiom_metrics.py:1660-1673).

### P1-8 — The Access tab contains no access content; it leaks developer telemetry instead
Screenshot `..._tab_Access.png`: left panel "Live Record Signals" = storage facts (mostly "—", "Workloads Unavailable", "Connected Assets
Loading…" stuck); right panel "ASSET 360" prints **"Composite state: Loaded"** and **"Loaded sections: header, activity, schema, properties,
operational, profiler"** — internal cache-state strings as user-facing rows (`Asset360Panel` facts, EntityWorkspace.jsx:1549-1569). The actual
access story (grants, auth mode, remediation deep links) exists at `/api/assets/<fqn>/access-explain` (200 in 0.44s with catalogExplorer/jobs/
queryHistory links) but only surfaces as a conditional banner. No grants are ever listed.

### P2-9 — Schema preview promises three columns of governance mapping it can never fill
Overview schema table headers: Column Name / Type / **Glossary Term / Sensitivity / Policy Tags**. Across all 7 assets every Glossary Term and
Sensitivity cell is "—". Column-level `glossaryTerm`/`glossaryTerms` are in the payload contract and the store supports column-subject links
(`glossary_link_lookup`, assets.py:3331-3350, key `column:<fqn>:<col>`), but **no column-level glossary_links rows exist** — only asset-level
terms do (header chips show them). So the header advertises "Contracted Revenue, Net Revenue" while the schema's Glossary column is uniformly
empty — the mapping gap the owner noticed. Sensitivity is derived by regex over tag labels (EntityWorkspace.jsx:755) and no column tags carry
those markers. For main.emet.run_history, "Policy Tags" prints raw operational tags including a GUID
("emet_installation_id: 07a31656…") — noise presented as policy.

### P2-10 — Owner/steward attribution is fragile and contradicts the drawer
Every asset shows Owner "Skyler" because `ownerForRole(/owner/i)` (EntityWorkspace.jsx:441-449) matches the UC owner entry
("Unity Catalog owner" title) first — business owners (product-steward@, metadata-platform@) never win the Owner card. Steward matching relies
on "steward" appearing in the email ("product-steward@…" → prettied to "Product Steward"); run_history (1 owner) renders Steward "Unassigned".
The **drawer disagrees with the page for the same asset**: revenue_daily drawer shows "Steward unavailable" + owner name duplicated as its own
subtitle (Asset360Drawer.jsx:118-129 reads `displayName` which business-owner entries lack), while the full page shows "Finance Steward".

### P2-11 — Usage Summary: three different truths in one card
- product_mortgage_signal & hr_secure: all "—" + "Usage evidence is unavailable for this actor/workspace."
- revenue_daily: "8 Downstream Assets / 0 Users / 0 Queries"; run_history: "0 Downstream / **29 Users** / 0 Queries".
Downstream count comes from lineage-derived relatedAssets, Users from operational consumers, Queries from query-history — three sources with
different availability, rendered as one coherent "Last 30 days" block (there is no 30-day scoping anywhere in the backend; `usage` counts are
list lengths — axiom_metrics.py:1681-1686). The "(Last 30 days)" caption is fabricated. Root availability: `workloadVisibility`
capability is `unknown/false` (bootstrap), the 360 only requests `operational` when OBO actor-scoped (axiom.py:757-759) — so Queries/Users are
*never-fetched* in non-OBO contexts, not "unavailable".
- "View all usage" routes to the Lineage workspace's Operational Context — which the same page's header may claim is unavailable (P1-5).

### P2-12 — Hero hover states are dead on the two secondary actions
Computed-style probe (report.json → hoverStyles): Request Change and Open Lineage show **zero change** on hover (bg rgba(12,33,56,.96) before
and after) — a later `!important` rule (northstar.css button overrides, ~7722-7734 layering war with app.css:459-490) pins the background so
the hover rule never lands. The kebab does respond. So the hero mixes hover-dead and hover-live buttons side by side. The CSS file itself
documents the prior inverse failure ("hovered buttons to a near-white fill … 'highlight contrasts to the point you can't see'") — the fix
layer overshot into no-feedback. Old-shell remnants persist: the entire page chrome is `gh-*` classes patched by `!important` `ax-*` overrides;
residual light leak: `.gh-owner-avatar` backgrounds rgb(236,254,255)/rgb(240,249,255) (light pastel chips on dark card).

### P2-13 — The two "unavailable"-claiming placeholders mislabel in-flight state and dead-end states
`EntityShellPlaceholder` shows breadcrumb "Asset 360 / Assets / <fqn>" where "Assets" is dead text (no onClick, line 617/1032), disabled
Certify/Request buttons, and — during load — "Lineage Unavailable" whenever the merged capability hasn't flipped yet (line 1059). The pre-load
shell also carries a large dead zone (cards end ~470px, tabs ~545px, first content ~655px — visible in `..._tab_Profile.png`), which is the
"huge empty band" the owner describes: it's the placeholder/regressed shell, not the loaded page (loaded gap is 12px).

### P3-14 — Dead tab machinery and misleading tab set
`entityTabs()` (EntityWorkspace.jsx:282-292) ignores all three availability args; there is no Lineage/SampleData/Queries/CustomProperties tab,
yet full render branches for `activeTab === "Lineage" | "SampleData" | "Queries" | "CustomProperties"` remain (2718, 3040, 3083, 3148) plus
`EntityLineageEmbed` (3201) — unreachable via `resolvedEntityTab` (294-304). ~500 lines of dead UI. The page has no in-page lineage canvas at
all despite shipping one.

### P3-15 — Drawer vs page duplication and drift
The drawer (5 tabs) and page (7 tabs) consume the same `useAsset360` but render different fields with different fallbacks: 3 of 5 drawer tabs
are permanent placeholders (Lineage, Quality, Access — the latter two blocked by P0-3), the Overview repeats a "Buildability note" of
dev-facing provenance copy, the footer buttons overflow the panel edge ("Open full re…" clipped — `nav__drawer.png`), and its facts contradict
the page (P2-10, usage: drawer "Usage unavailable" vs page "8 Downstream Assets"). Inline hex colors throughout (`#a8d3e8`, `#34d399`,
rgba literals — Asset360Drawer.jsx:71-77) violate the `--ax-*` token rule.

### P3-16 — Misc copy/consistency
- Hero subtitle "Product 360" / "Finance 360" (domain + literal "360") reads as a template artifact (EntityWorkspace.jsx:629).
- Top-bar coverage pill flickers between "95.5% coverage" and "coverage unavailable" across renders of the same session (screenshots).
- Kebab tooltip after a failed clipboard write shows "Copy failed" with no other affordance.
- `detail` payloads emit literal "—" for size/files on some paths (product_mortgage_signal `size:"—"`) despite base_asset_payload's
  "never a literal '—'" comment — the header-from-inventory path does not follow the same contract.

---

## 2. Data honesty — three-way split per widget (truly-absent vs fetched-not-rendered vs never-fetched)

Legend: ✔ real data rendered · ∅ honest empty (data truly absent in backend) · FNR fetched-but-not-rendered · NF never-fetched/never-populated by design · ✖ dishonest render

| Widget (tab) | mortgage_signal | revenue_daily | revenue_recognition | run_history | customer_profile | compensation_band | orders | Verdict |
|---|---|---|---|---|---|---|---|---|
| Hero chips (domain/cert/glossary/requests) | ✔ | ✔ | ✔ | ∅ (all Unassigned) | ✔ | ✔ | ✔ | real |
| Owner card | ✖ (UC owner shadows business owner) | ✖ | ✖ | ✔ | ✖ | ✖ | ✖ | FNR — business owners in payload, wrong pick |
| Steward card | ✔ | ✔ | ✔ | ✖ "Unassigned" fallback | ✔ | ✔ | ✔ | fragile email-regex |
| DATA UPDATED card | ✖ raw ISO + "Unavailable" + fake sparkline | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ | FNR (timestamp present) + NF (freshness state hard-coded, P0-3) |
| Rows / Size cards | ✔ (1 = COUNT(*) verified) | ✔ (4 ✓) | ✔ (5) | ✔ (239 ✓) | ✔ | ✔ | ✔ (5 ✓) | honest, verified vs warehouse |
| Usage Summary | ✖ dashes | mixed ✔/NF | mixed | mixed ("29 Users") | mixed | ✖ dashes | mixed | Queries/Users NF (operational gated on OBO; workloadVisibility unknown); "(Last 30 days)" fabricated |
| Schema preview (Glossary/Sensitivity cols) | ∅→✖ (headers promise what data model lacks) | same | same | ✖ raw GUID tags | same | same | same | truly absent at column level (no column glossary_links) |
| Governance card | ✔ | ✔ | ✔ | ∅ | ✔ | ✔ | ✔ | real; "policies" always empty (no policy source wired = NF) |
| Recent Activity rail | FNR (actor dropped, raw ISO) | FNR | ∅ | FNR | ∅ | ∅ | FNR | store holds priority/task_id/thread — dropped |
| Related Assets rail | ∅ (lineage has 1 upstream but availability-filtered) | ✔ 4 | ✔ 4 | ∅ | ✔ 1 | ∅ | ✔ 1 | real when lineage warm |
| Downstream Dashboards | ∅ (no dashboard consumers exist) | ∅ | ∅ | ∅ | ∅ | ∅ | ∅ | NF in non-OBO (operational excluded) |
| Columns tab | ✔ types/nullable; ∅ desc | ✔ + desc | ✔ | ✔ rich desc | ✔ | ✔ | ✔ | real |
| Quality tab | ∅ "not monitored" (endpoint real, empty) | ∅ | ∅ | ∅ | ∅ | ∅ | ∅ | truly absent (no monitors); drawer variant NF (P0-3) |
| Profile tab | ∅ (no monitor/profile runs) + P0-2 shell regression | ∅ | ∅ | ∅ | ∅ | ∅ | ∅ | truly absent; UX broken |
| Access tab | ✖ telemetry leak; grants NF | same | same | same | same | same | same | access-explain endpoint has real data, barely used |
| Activity tab | ✔ actor shown, ✖ formatting | ✔ | ∅ | ✔ | ∅ | ∅ | ✔ | FNR on priority/links |

Ground truth: COUNT(*) — product_mortgage_signal=1, revenue_daily=4, run_history=239, orders=5 → **the UI row counts are accurate**; the
"ROWS 1" that looks broken is real (the table has one row).

## 3. Inbound / outbound link map

**Inbound (works):** Discover result row & preview "Open" → `/entity/<fqn>` (App.jsx:833); Lineage workspace "Open asset" (895); Audit
"Open asset" (912); Taxonomy (926); CDE registry (941); Insights (1089); drawer "Open full record" (1162); sidebar "Asset 360" *only via*
`onOpenAsset360` when a current asset exists (App.jsx:1120-1133 — but see P0-1: never rendered); direct URL.
**Inbound (broken/absent):** Left-nav entry (P0-1); global top search & ⌘K palette open the *drawer*, never the page directly (App.jsx:1141);
no breadcrumb path ("Assets" crumb dead); Command Center asset mentions open the drawer.
**Outbound (works):** Domain chip → `/discovery?domain=…` (consumed, useAppRouteState.js:211-222); Glossary chips → `/glossary?term=…`
(consumed, TaxonomyWorkspace.jsx:681); Open-requests chip → `/governance?asset=…`; owner/steward names → `/discovery?q=owner:"…"`;
"View all columns" → Columns tab; access-explain deep links.
**Outbound (weak/dead):** "View history", Recent Activity rows, "View all policies" → all the same generic `onOpenGovernance`; "View all
usage" / Related / Dashboards "View all" → lineage workspace even when header claims lineage unavailable; kebab = copy-link only; Certify ⌄ =
navigation; Breadcrumb "Assets" dead text.

## 4. Performance

| Phase | Measured |
|---|---|
| Shell first paint (warm SPA) | 150-720ms |
| Hero resolved | 352-2764ms (cold worst) |
| Consolidated detail request (cold) | 5.4-7.1s — returns header-only + `state:loading` |
| Detail request (warm) | 0.2-0.9s |
| /360 request | ~0.5s but `loading` until background warm completes — observed ~4 min to full hydration; client polls every 3s |
| Tab switch | ~3.5s to settle; Quality triggered a 5.7s sections request; >20s after load ⇒ P0-2 full-shell regression |
| Per-view request fanout | 8-10 API calls incl. command-center, workbench, glossary, governance summary on an entity view |

Verdict vs the ~2s warm target: warm entity views meet it; **cold views and tab switches do not**, and the minutes-long 360 hydration means
first impressions are all dashes.

## 5. Rebuild spec — what a truthful, fast, connected Asset 360 renders (priority order)

1. **Navigation**: render `ASSET_360_NAV_ITEM` in the rail (disabled-with-tooltip when no current asset; opens last-viewed asset otherwise).
   Top search/palette results get explicit "Preview" (drawer) vs "Open record" affordances.
2. **Kill the shell regression**: fix the `?? DETAIL_CACHE_TTL_MS` null-semantics bug; placeholder shell may only ever appear on first load of
   an unknown asset; tab switches render the cached record + per-section skeletons, never the global shell; active tab must survive loading.
3. **One composite contract**: make `/360` actually composite — join freshness (already have `last_altered`; label it "Metadata changed", add
   Delta write history when available), quality (`/quality` summary state), access (auth mode + effective-permission summary from
   access-explain), and usage — or delete those hard-coded "unavailable" blocks and the widgets that depend on them. Never ship a field no code
   can populate.
4. **Honest freshness card**: label = what the signal is ("Metadata changed 11 weeks ago"), humanized relative time with ISO in tooltip, no
   sparkline unless backed by a series. Rows/Size keep the verified real values, add "observed <date>" provenance.
5. **Real header actions**: Certify becomes an actual menu (Certify / Revoke / Request certification) writing through the existing governance
   store with audit rows and optimistic badge update; Request Change opens a pre-scoped request composer (asset FQN + field picker), not a
   generic workspace; kebab becomes a real menu (Copy link, Open in Catalog Explorer via access-explain deepLink, Refresh metadata); lineage
   button trusts the per-asset lineage response (fetch is already prefetched at 1.5s dwell) over bootstrap, per CLAUDE.md.
6. **Usage truth**: split the card into what each source really is — "Downstream assets (lineage)", "Consumers (ops context)", "Queries
   (query history)" — each with its own availability reason; drop the fabricated "(Last 30 days)" until a windowed query exists.
7. **Activity with substance**: render actor, humanized event ("Skyler moved task to P1"), priority chip, and deep-link each row to the task in
   Stewardship (`/governance?asset=…&task=<task_id>` — task_id is already in the store). Normalize slug titles server-side.
8. **Column-level glossary**: the store already supports `subject_type=column` glossary links; add "Map term" affordance on the Columns tab
   writing glossary_links rows; until links exist, drop the empty Glossary/Sensitivity columns from the 5-column preview (show description
   instead — it's the richest column data we have and today it's omitted from the preview entirely).
9. **Access tab = access**: grants summary + auth mode + remediation deep links from access-explain; delete the "Composite state / Loaded
   sections" telemetry panel (move to a debug flag).
10. **Perf**: first paint from the batch-header cache (already instant), one consolidated detail request that streams sections
    (server currently defers everything anyway — make the contract explicit), cap 3s polling with backoff + a visible "hydrating live
    metadata (Xs)" indicator, and pre-warm 360 on discovery hover like detail headers already are.
11. **Drawer**: keep it as the quick-preview (it's good at identity + columns); delete its dead Lineage/Quality/Access tabs until the
    composite backs them; fix steward/owner display-name fallbacks and the clipped footer; tokenize the inline hexes.
12. **Delete dead code**: unreachable Lineage/SampleData/Queries/CustomProperties tab branches + `EntityLineageEmbed`, or reintroduce a real
    Lineage tab using the v2 canvas (preferred — the embed already exists and works).

## Screenshot index (arch_entity/shots/)
- `*__overview.png` per asset — full Overview
- `emet_…__hero.png`, `…__hero_hover.png` — header actions
- `emet_…__tab_{Columns,Governance,Profile,Quality,Access,Activity}.png` — note tab_Profile = shell-regression evidence; tab_Quality actually captured the Profiler tab because placeholder tab clicks are no-ops (itself evidence)
- `nav__discovery.png`, `nav__search_results.png`, `nav__drawer*.png` — reachability + drawer
- `report.json` — full widget census, hover probes, timings, request logs
