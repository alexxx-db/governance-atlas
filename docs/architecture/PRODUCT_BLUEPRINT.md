# Axiom — Target Product Architecture Blueprint

**Status: decided. This is the law for the cohesion rewrite.**
Author: principal product architect pass, 2026-07-21. Grounded in the eight persona audits
(`scratchpad/audit_*`), the verification swarm (`scratchpad/verify_*`), the wave-1/2 backend
contracts (`scratchpad/wave*_contracts/`), and a fresh live walk (`scratchpad/arch_product/walk_*.png`).

The owner's verdict — "too dispersed, not one interconnected unit" — has a precise diagnosis in
the evidence: **the app has nine surfaces but no connective tissue.** The UX census found ZERO
`<a href>` anchors on 12 of 13 surfaces (audit_ux/notes.md #1); the same governance fact renders
under different names and values on different screens ("OPEN EXPOSURES 0" beside "High-risk
exposures 2", audit_ux WF3); two full executive dashboards exist (Command Center + orphaned
Insights) showing the same 44/96%/0 numbers in different visual languages (walk_home.png,
walk_insights.png); and the one page that could tie everything together — Asset 360 — is not in
the nav, not in the palette, and collapses to "Asset unavailable" with no retry. The rewrite is
not about new features. It is about **one entity model, one queue, one evidence ledger, one
dashboard, and links everywhere.**

---

## 1. Governance jobs-to-be-done

The product exists for eight jobs. Every surface must justify itself against one of these.

| # | Job | Primary persona | Surfaces it spans today | Where the seams break today (evidence) |
|---|-----|-----------------|-------------------------|----------------------------------------|
| J1 | **Prove governance posture to leadership** — "show me the state of the estate and its trend, exportable" | CDO / exec | Command Center, Insights (orphan), Export brief | Two dashboards with the same KPIs styled differently (walk_insights.png vs walk_home.png); hero titled "THE STATE OF FINANCE_PROD" for a 7-catalog estate (audit_cdo report.json); flat 26-week trend drawn from 1 snapshot; contradictory exposure numbers on one screen (audit_ux WF3); Insights unreachable from nav (audit_ux #8). |
| J2 | **Assess whether an asset is trustworthy before using it** | Analyst | Discover → preview → Asset 360 | Three conflicting owner statements on one flow (preview "Skyler" / Access tab "3 owners" / card "Finance Steward" — audit_ux WF1); dead chips everywhere ("2 terms" span, CDE/PII pills — audit_ux #2); Request access files instantly with canned text, no dialog (audit_ux #15); rows/size blank on cards. |
| J3 | **Trace impact of a change / incident** | Data engineer | Lineage Atlas, Asset 360 Lineage tab | Engineer census: 28/30 assets have UC lineage, app rendered 12 (fix_plan); "Hydrating…" with 0 edges while the API had 15 nodes (audit_ux #5); CDE→Lineage context drop lands on an empty jargon landing (WF2); entity header says "Lineage Unavailable" while /lineage works (bootstrap pessimism, audit_ux #4). |
| J4 | **Triage and resolve governance work** | Steward | Stewardship, Inbox, entity Certify button, bell | Two half-queues: Stewardship (work items) and Inbox (requests + term reviews) with different item sets; bell → full-page Inbox that said "No inbox items" while 40 items sat in Stewardship (audit_ux round 2); Certify = redirect to the queue, not a flow (WF4); "New work item" dead button (sweep). Wave-2 fixes added assign/priority/resolve — the *split* remains. |
| J5 | **Define and govern business meaning** (terms, CDEs, source-of-record) | Steward / data owner | Glossary & CDEs, Asset 360 columns | Glossary search "mortgage" → 0 terms while the CDE registry holds "Product Mortgage Signal" (WF2); CDE source-of-record column shows a placeholder instruction, Recert "Unavailable"; per-column glossary cells honest-empty because links are asset-scoped (frontend1_handoff #5); term hierarchy panel was empty ids (fixed wave 2). |
| J6 | **Prove compliance to an auditor** — filterable, exportable, reconciling evidence | Compliance officer | Audit Evidence, exports, Asset 360 Activity | Exclusion arithmetic didn't reconcile across ranges; export silently sliced to 25; client-side regex suppressed rows; event identity was positional (all fix_plan "Audit evidence integrity" — fixed wave 1/2, but the *evidence for quality findings* still has no surface: risk drill-downs land on the Insights heatmap because "no surface renders raw quality-run results today" (wave2 home_handoff #2). |
| J7 | **Monitor and act on data quality** | Steward / engineer | nowhere first-class — fragments on Command Center (Quality SLA 66.7%), Insights heatmap, Asset 360 Quality tab | The J6 gap is the J7 gap: quality runs exist in the backend (9 checks evaluated, runs since May + fresh runs) but findings have no browsable, filterable home; Command Center risk rows deep-link to a dashboard tile, not to evidence. |
| J8 | **Operate the platform honestly** (integrations, jobs, capability truth) | Platform admin | Control Center, /capabilities (orphan) | Control Center said "Lineage Service: Unavailable" while lineage worked (audit_ux #12); internal job names leaked ("[RUNNER] pixels l 0f1f0a…"); /capabilities is a second diagnostics page reachable only by URL; admin activity not visibility-scoped (wave2 audit_handoff #3). |

---

## 2. Target surface map

**Seven primary surfaces + one hub. Everything else dies or folds in.**

| Surface | Route (canonical) | Mission (one sentence) | Primary persona | Absorbs / kills |
|---|---|---|---|---|
| **Command Center** | `/home` | The single executive answer to "what is the state of governance and what changed," with every number a door to its evidence. | CDO | **Absorbs Insights** (`/insights` → 301 to `/home`; its three honest widgets — Risk Heatmap, Metadata Coverage by Domain matrix, Certification by Tier — move into a "Risk & quality" band on Command Center). Kills Present mode, Governance ROI tiles, Axiom AI empty-slot fillers (see §7). |
| **Discover** | `/discovery` | Find and evaluate governed data with permission-aware search, facets, and a preview that agrees with Asset 360. | Analyst | Unchanged scope; its preview drawer becomes a strict subset of the Asset 360 header (same component, `Asset360Header compact`), killing the three-owners contradiction class. |
| **Asset 360** (the hub) | `/asset/<fqn>` (alias `/entity/…` kept) | Everything the estate knows about one asset, ordered by the trust decision a user is making. | all | Absorbs nothing; becomes the *destination* of every chip in the app. Not in left nav — see §3 hub-and-spoke decision. |
| **Stewardship** | `/stewardship` (alias `/governance`) | The one queue for all governance work — requests, reviews, term approvals — triaged by team or by "me". | Steward | **Absorbs Inbox.** `/inbox` → 301 to `/stewardship?assignee=me`. Term reviews become work items of type `term-review` in the same queue. The bell becomes a popover (top-3 of my queue + count) whose "View all" lands on `/stewardship?assignee=me`. Kills InboxPage.jsx and the InboxPanel-as-page. |
| **Glossary & CDEs** | `/glossary` (alias `/taxonomy`) | Shared business meaning — terms and Critical Data Elements — anchored to source-of-record assets. | Steward / owner | Unchanged split (Terms tab / CDE Registry tab) but with term detail addressable (`?term=`, shipped wave 2) and CDE detail addressable (`?cde=`). Kills the duplicate CDE filter-chip row (one filter bar, owned by the tab). |
| **Lineage Atlas** | `/lineage/<fqn>` | Permission-aware impact tracing outward from a focus asset, honest about truncation and build state. | Engineer | Unchanged scope. The empty `/lineage` landing (no fqn) is killed as a browsable page: it becomes a search-first "pick an asset" state using the Discover search component — never the jargon wall audit_ux WF2 hit. |
| **Evidence** | `/evidence` (alias `/audit`) | The immutable proof ledger — audit events AND quality findings — filterable, exportable, reconciling. | Compliance | **Absorbs quality findings** as a second tab: `Audit log` \| `Quality findings` (backed by the existing quality-run store the backend already serves). This is where Command Center risk rows drill to (`/evidence?tab=quality&severity=high`), fixing the "drill lands on a dashboard tile" seam (wave2 home_handoff #2). |
| **Control Center** | `/admin` | Admin-only runtime operations: integrations, scheduled jobs, coverage administration, capability truth. | Platform admin | **Absorbs /capabilities** as its "Diagnostics" tab (the capability flag table is genuinely useful — for admins). `/capabilities` → 301. Gated on admin role; demoted to the profile/bottom cluster of the rail, out of the governance nav groups. |

**Explicit calls the prompt demanded:**

- **Insights merges into Command Center.** There is no second executive dashboard. Evidence: both pages render Certified 44, Coverage ~96%, Policy exceptions 0 today with different chrome (walk screenshots); Insights has no nav entry and is reached only by drill-downs (audit_ux #8). What Insights uniquely had that is *backed* (heatmap, coverage-by-domain matrix, tier certification bars, maturity score) moves into Command Center; what it had that is *unbacked* (Policy Compliance trend, Time-to-Resolution trend, ROI tiles, empty AI slots) dies (§7).
- **Asset 360 is a hub, not a nav destination.** Hub-and-spoke: you never "go to Asset 360" in the abstract — you always arrive *about a specific asset* from Discover, search, lineage, a work item, an audit row, a CDE, or a term. It gets no rail entry; it gets first-class treatment everywhere else: breadcrumb (`Discover / customer_profile`), ⌘K asset results land there, every FQN in the app links there. The rail keeps a *contextual* highlight (existing `Asset 360` rail affordance stays visible only while on `/asset/*`).
- **Inbox/Stewardship boundary: there is no boundary — one queue, two lenses.** "My work" is a filter (`assignee=me`), not a place. The queue holds typed items: `governance-review`, `access-request`, `term-review`, `quality-finding-followup`. The bell is a notification popover over that queue, never a page.
- **Control Center is for admins to operate the runtime** — jobs, integrations, capability truth, coverage administration, metastore truth-check. It is not a governance surface and makes no governance claims; anything user-facing it asserts (e.g. "Lineage Service") must derive from the same live probes the product uses, ending the "Unavailable while it works" lie (audit_ux #12).

---

## 3. The entity-hub model

### 3a. Asset 360 (`/asset/<fqn>`) — what it must answer, in priority order

The page is an argument, top to bottom: *should I trust this, what does it mean, what does it
touch, is it healthy, can I get to it, what happened to it.*

1. **Trust verdict (header, always above the fold):** certification chip (strict semantics),
   governance score, CDE chip ("Criticality-derived" subtitle), sensitivity chip, freshness as
   two labeled values — "Data updated" (Delta write) and "Metadata changed" (last_altered) —
   never an unlabeled "Freshness" (fix_plan #6). Rows/size when the warm cache holds them, "—"
   otherwise. **One owner block:** Owner + Steward, each a link; this exact component is reused
   by the Discover preview so the WF1 three-owners contradiction is structurally impossible.
2. **Meaning:** description, domain, data product, glossary-term chips → `/glossary?term=…`
   (shipped wave 1), CDE linkage → `/glossary?tab=cdes&cde=…`.
3. **Lineage & impact:** a mini-map (first-hop up/downstream, reusing the v2 adapter via
   `useLineageGraphV2` — never raw payload) + "Open in Lineage Atlas" → `/lineage/<fqn>`.
   Honest states from `meta.emptyReason` (`no-lineage-rows` vs `lineage-query-failed`); the
   header button is *never* disabled by bootstrap pessimism alone (CLAUDE.md rule; audit_ux #4).
4. **Quality:** latest run verdicts per check with evidence dates ("evidence from May 3" when
   stale), link per finding → `/evidence?tab=quality&asset=<fqn>`.
5. **Access:** grants/requests summary + per-asset open-request count chip (true store count even
   out-of-inventory — never a false 0, fix_plan #3) → `/stewardship?asset=<fqn>`. "Request
   access" opens a real dialog (reason + duration), not an instant canned filing (audit_ux #15).
6. **Activity:** audit timeline with stable `AUD-<hex8>` ids that join Evidence rows
   (fix_plan #7), each row → `/evidence?event=AUD-…`.

**Inbound contract — every other surface renders chips/links toward the hub:** Discover rows and
preview (name, FQN), Command Center drill lists, Lineage nodes (any node with a real FQN is
navigable; destination surfaces the truth — CLAUDE.md), Stewardship work-item asset column,
Evidence target column (already has ↗; the FQN text itself becomes the link — audit_ux found the
text dead), Glossary "linked assets", CDE source-of-record FQN (dead today — audit_ux round 2),
search results.

**Failure contract:** the hub never collapses to a dead end. Error state keeps the header shell,
offers Retry (`useAssetDetail.retry`, shipped wave 1), and disables (with reason) the action
buttons instead of leaving Certify/Request Change enabled-looking on a dead page (audit_ux #4).

### 3b. Term page (miniature hub) — `/glossary?term=<id>`
Must answer, in order: **definition & status** (Approved/Draft/Proposed + steward, review date) →
**linked assets** (each FQN → `/asset/…`) → **hierarchy** (parent/child, real termIds — wave 2
fixed the sanitizer) → **pending review action** (if Draft/Proposed: "Review" → the Stewardship
work item `/stewardship?item=…`). Outbound: steward → owner search; assets → hub; review → queue.

### 3c. Request detail (miniature hub) — `/stewardship?item=GOV-<hex8>`
Must answer, in order: **what & why** (title, requester, created, SLA state) → **target asset**
(header chip strip from the hub component; FQN link) → **triage controls** (assign-to-me,
priority, resolve — shipped wave 2) → **evidence trail** (comments + the audit events this item
generated, ids linking to `/evidence?event=…`). Outbound: asset → hub, actor emails → owner
search, audit ids → Evidence.

---

## 4. Cross-linking contract (LAW: any mention anywhere is a link)

Every rendered mention of one of these entity types, on any surface, in any tab, chip, table
cell, tooltip, or caption, is a real `<a href>` to the canonical route (client-side navigation
via interception, but a real anchor — middle-click, copy-link, and a11y work). The census found
the app is "a giant click-delegated div" with zero anchors outside /help (audit_ux #1, round 2);
this table ends that.

| Entity type | Canonical route | Notes |
|---|---|---|
| Asset (table/view) | `/asset/<fqn>` | FQN text is always the anchor, not just an adjacent ↗ glyph. |
| Column | `/asset/<fqn>?tab=columns&col=<name>` | Columns tab scrolls to + highlights the row. Lineage column-path chips use it. |
| Glossary term | `/glossary?term=<termId>` | Name or id accepted (wave-2 resolver). Term chips on hub, Discover rows ("2 terms" → popover listing linked terms, each an anchor — not a fall-through to the row). |
| CDE | `/glossary?tab=cdes&cde=<id>` | CDE chips on hub/Discover link here, not to the generic tab. |
| Owner / steward (person) | `/discovery?q=owner:"<name-or-email>"` | The one owner-search grammar (frontend1_handoff #3). Every rendered email/name — audit actors, lineage rail owners, comment authors, preview owners — is this link. |
| Work item / request | `/stewardship?item=GOV-<hex8>` | Opens the queue with the item's detail pane focused. |
| Audit event | `/evidence?event=AUD-<hex8>` | Stable id (fix_plan #7); same id shown on hub Activity, exports, and Evidence. |
| Quality finding | `/evidence?tab=quality&asset=<fqn>&run=<runId>` | Command Center risk rows, hub Quality tab, and heatmap cells all land here. |
| Policy exception | `/evidence?tab=quality&kind=policy-exception` | One name ("Policy exceptions"), one number (0 today), one destination. |
| Catalog | `/discovery?filters={"catalogs":["<name>"]}` | Catalog-health rows on Command Center. |
| Domain | `/discovery?filters={"domains":["<name>"]}` | Posture-by-domain rows (already the pattern); the *label text* is the anchor, not just the row (audit_ux round 2 found the label dead). |
| Lineage graph | `/lineage/<fqn>` | Never a bare `/lineage` link from an asset/CDE context (WF2 context-drop bug class). |

Enforcement: one shared component set — `EntityLink` (kind, id, children) — is the only way to
render these. A lint rule (`no-raw-entity-mention`) greps JSX for FQN/`GOV-`/`AUD-` patterns
rendered outside `EntityLink` in review.

---

## 5. Navigation + wayfinding model

**Left rail — two groups + admin cluster (down from 3 groups / 8 items):**

```
GOVERN            Command Center      /home        (exec answer; absorbs Insights)
                  Discover            /discovery
                  Stewardship  [n]    /stewardship (badge = MY open items, not estate total)
KNOWLEDGE & PROOF Glossary & CDEs     /glossary
                  Lineage Atlas       /lineage
                  Evidence            /evidence    (audit log + quality findings)
──────────────────────────────────────────────────
(profile cluster) Control Center      /admin       (admin-gated; with Diagnostics tab)
                  Help                /help
```

- **Promoted:** Evidence (renamed from Audit Evidence — it now carries quality too); Stewardship
  badge semantics (my work, matching the bell).
- **Demoted:** Control Center out of the "Trust" governance group into the admin cluster —
  runtime ops is not a governance claim. Inbox and Insights disappear as destinations (redirects
  keep old links alive; the route normalizer already does alias mapping for
  `/lineage-atlas`→`/lineage` etc., so `/insights`→`/home`, `/inbox`→`/stewardship?assignee=me`,
  `/audit`→`/evidence`, `/taxonomy`→`/glossary`, `/governance`→`/stewardship`,
  `/entity/*`→`/asset/*`, `/capabilities`→`/admin?tab=diagnostics` extend the same table).
- **Breadcrumbs:** `Surface / Entity` everywhere an entity is open (`Discover / customer_profile`,
  `Stewardship / GOV-BE17D517`). The crumb's surface segment is a link; the dead decorative
  `Workspace › Dev` crumb is removed from the top bar (dead click, audit_ux sweep) — environment
  moves into the profile block where it already appears.
- **Global search = one grammar.** The top-bar search and ⌘K are the same index and the same
  result renderer: assets, glossary terms, owners, work-item ids (`GOV-…`), audit ids (`AUD-…`),
  surface commands. The current split — top bar finds 33 assets for "revenue" while ⌘K says "No
  commands match" (audit_ux round 2) — is abolished by deleting the palette's separate command
  list and feeding it from the search service + a static command section.
- **Where "my work" lives:** `/stewardship?assignee=me` — the badge on the rail, the count in
  the bell popover, and the "Assigned to me" tab are the *same number from the same query*
  (governanceInbox summary already loads at bootstrap, wave-2 App.jsx change).
- **Deep-link / URL-state rules:** every view state is addressable — surface, entity, tab
  (`?tab=`), filters (`?filters=` JSON, existing contract), selection (`?item=`, `?term=`,
  `?event=`, `?col=`). Back/forward always safe (already verified for surface nav, audit_ux
  round 2); tab changes push replace-state; filter changes push history entries. No modal holds
  state that the URL doesn't.

---

## 6. Feasibility gates (what each surface may claim, per the now-truthful backend)

The backend (post PR #6) has: canonical semantics (`axiom/services/semantics.py` — CDE=49,
strict Certified=44), real lineage with `buildState`/`truncation`/`emptyReason`
(lineage_backend.md), quality runs with evidence timestamps, an append-only Delta audit log with
stable event ids, and daily posture snapshots **since 2026-07-20**. The architecture promises
exactly that and nothing more:

| Surface | Backed today — render as live | NOT backed — render as "collecting"/"unavailable" (or kill) |
|---|---|---|
| Command Center | Posture score, coverage 95.5%, strict certified 44, CDE 49 (`cdeSignal.subtitle` "Criticality-derived"), open work, policy exceptions 0, catalog health (all 7, worst-first), domain posture (unsliced), quality SLA + risk breakdown **with `evidenceAt` labels**, lineage coverage, risk heatmap + domain matrix (from Insights). | **Trends: "Collecting since Jul 20, 2026"** state until ≥ ~8 snapshots — never a flat 26/52-week line (fix_plan Command Center). Week toggles hidden until then. |
| Discover | Search + facets (with Unassigned rows summing to total), didYouMean, governance score, per-row terms/CDE/PII chips, progressive rows/size (warm-cache only, "" when unknown — never fabricated). | Owner *facet* (no backend facet — owner filtering stays the `owner:` query grammar until one exists). |
| Asset 360 | Header (dual freshness labels), columns, asset-level term links, per-asset open-request truth, quality runs w/ dates, audit timeline w/ AUD ids, first-hop lineage. | Per-column glossary links only where column-scoped links exist in the store (asset-level terms stay hero chips — frontend1_handoff #5); rows/size "—" until DESCRIBE cache warms. |
| Stewardship | Full queue w/ visible/out-of-scope split caption, assign/priority/resolve, term-review items (terms API has status+steward). | Approval *workflows* beyond resolve (multi-step cert flow) — the Certify button stages a work item with a toast ("no dead buttons" rule) until a real flow ships. |
| Glossary & CDEs | 20 terms w/ real ids + hierarchy, 49 CDEs (canonical predicate), linked assets, review dates. | CDE recertification cadence ("Recert Unavailable" honestly until a recert source exists); source-of-record column only when the `cde_source_column` tag is actually set — placeholder instruction text is removed from the UI (it's operator documentation, not data). |
| Lineage Atlas | Real graphs (28/30 asset coverage), truncation captions ("Showing 16 of 659 edges"), degraded-vs-empty honesty, reference nodes for out-of-inventory neighbors, restricted dashed edges. | Per-node rows/freshness/owners (NOT in the lineage payload — CLAUDE.md data contract; the rail fetches `/api/assets/<fqn>?sections=header` for the selected node only). |
| Evidence | Audit tab: 500-row window w/ truncation caption, server-side counted exclusions, actor/entity/action/date filters, UTC everywhere, full exports. Quality tab: run findings by severity/asset/date (data exists; needs the browse endpoint — the one net-new backend piece this blueprint requires). | `actorKind` stays the documented heuristic until the backend emits the field (wave2 audit_handoff #1); "Violations" tab renders 0 honestly. |
| Control Center | Runtime summary, scheduled jobs (customer-safe names — internal `[RUNNER]`/dev-user names are sanitized server-side), integration states derived from the same live probes the product uses, capability flags (Diagnostics tab), coverage admin. | Admin activity feed stays hidden until it is visibility-scoped (wave2 audit_handoff #3 — one-line fix, gate on it). |

**Never claimable anywhere until a source exists** (these killed the app's credibility in the
audits): Policy Compliance score/trend ("No authoritative policy-compliance evaluation source is
configured" — walk_insights.png), Audit Readiness, Time-to-Resolution trend, Governance ROI, and
any "AI recommendation" slot without an evidence-backed recommendation.

---

## 7. Kill list (remove, don't polish)

1. **Insights as a surface** (`InsightsWorkspace.jsx` page shell, hero, filters bar) — merged per §2. Its unbacked widgets die with it: **Policy Compliance Trend**, **Time to Resolution trend**, **Governance ROI tiles** (all "Unavailable", walk_insights.png), **Axiom AI empty recommendation slots** (3 of 4 slots render "No additional evidence-backed recommendation" filler). One backed recommendation renders as one card on Command Center; zero render as nothing.
2. **Inbox page** (`InboxPage.jsx`) and its nav entry — merged into Stewardship per §2. The bell popover replaces it.
3. **Present mode** (Command Center header) — an untested projector toggle on a page whose numbers were still being disputed; no audit persona ever used it. Remove the button.
4. **Capability dashboard as a standalone surface** (`CapabilityDashboard.jsx` route) — admins keep it as the Control Center Diagnostics tab; the orphan route dies.
5. **The empty `/lineage` landing page** with "Axiom walks system.access.table_lineage outward…" jargon wall (WF2) — replaced by a search-first asset picker.
6. **Dead chrome:** `Workspace › Dev` crumb (dead click), dead "i" info glyphs (either a real tooltip or nothing — fix_plan says real tooltips; any glyph without content is removed), 12w/26w/52w toggles while only one snapshot exists, permanently-disabled CDE "Download" button (ship the CSV or remove — ship it: the data is client-side already).
7. **Duplicate CDE filter chips** in Glossary & CDEs (one filter bar owned by the active tab; the second chip row goes).
8. **The kebab "⋮ More asset actions"** on Asset 360 that only copies a share link (audit_ux #7) — replaced by a visible "Copy link" icon button; the fake menu dies.
9. **Legacy dead weight already indicted by auditors 4/5** (all_findings): pre-React cream boot splash (replace with dark minimal shell), `shell-rail.css` light `!important` layer, dead `admin.css`/`cde.css`, v1 lineage CSS (~95% of 5,142 lines), orphaned workspaces/hooks (`useTheme`, unrendered EntityHero/Discovery card), `WorkspaceDiagnosticsSurface` jargon strings, `describe.skip` legacy Entity contract tests.
10. **Jargon vocabulary, globally:** "actor-visible", "actor-scoped", "hydrating", "composite Asset 360 payload", "non-authoritative … rejected", "runtime payload", internal FQN footnotes (`emet.axiom.metadata_audit_log`), client request ids in banner copy (audit_ux #10). Replaced by the copy registry (§8, principle 6).

---

## 8. Cohesion principles (the eight laws)

1. **One entity model.** Nine entity types (§4), each with exactly one canonical route and one
   link component (`EntityLink`). Any mention anywhere is a link; the anchor is the text itself.
2. **One number per concept, defined once.** Semantics live in `axiom/services/semantics.py`
   (CDE, certified, open-request scope, coverage vs governance score, policy exception) and the
   frontend renders payload-provided labels/subtitles (`cdeSignal.subtitle`,
   `estate.estateLabel`, `riskBreakdown.label`) — never re-derives, never re-words. Two
   same-named numbers with different values on one screen is a release blocker (fix_plan #5).
3. **One loading grammar.** Skeleton = loading (visually distinct, never a definitive "0");
   "—" + one-line reason = unavailable; "Collecting since <date>" = a real time-series that is
   just young. `state=loading` envelopes are never HTTP-cached and never render as data
   (fix_plan Performance; my walk's walk_home.png shows why this grammar must also *look* calm —
   a wall of "Signal unavailable" chips reads as a broken product even when honest).
4. **Two freshness words, everywhere:** "Data updated" (Delta write) and "Metadata changed"
   (last_altered). No surface says "Freshness" unlabeled (fix_plan #6).
5. **Hub-and-spoke.** Surfaces answer *estate* questions; the Asset 360 hub answers *asset*
   questions; term and work-item panes answer theirs. No surface duplicates a hub answer — it
   links (the Discover preview literally reuses the hub header component).
6. **One voice, from a copy registry.** All user-facing state/empty/error strings live in
   `frontend/src/copy/` keyed by (surface, state); banned-word lint (actor-visible, hydrating,
   payload, authoritative, scope-blame). Empty states name the fact ("Unity Catalog has no
   lineage rows for this asset"), never the mechanism.
7. **No dead controls, no fabricated data.** Every clickable does something visible within 200ms
   (navigate, open, toast-staged intent); every rendered value is backed or explicitly
   unavailable. These are already CLAUDE.md law — they graduate to CI: the dead-click sweep and
   the semantics-consistency check (same concept, same value across surfaces) run in the QA
   harness that already exists in `frontend/scripts/`.
8. **The URL is the state.** Every view, tab, filter, and selection is addressable and
   back/forward-safe; deep links are the product's API to itself (chips, bell, drill-downs,
   exports all traffic in URLs from §4's table — nothing navigates by opaque callback that a URL
   couldn't reproduce).

---

## 9. Rewrite sequencing (feasibility-first; refactor, not greenfield)

The backend is truthful post-PR #6; this is an experience-layer refactor in five moves, each
shippable:

1. **Links + routes week:** `EntityLink`, route renames + alias table, breadcrumbs, anchor-ify
   every mention (§4). Highest cohesion-per-line-changed; zero backend work.
2. **Queue merge:** Stewardship absorbs Inbox (term-review item type, `assignee=me` lens, bell
   popover). Deletes InboxPage; one summary query already feeds the badge.
3. **Dashboard merge:** Command Center absorbs Insights' three backed widgets; kill list §7
   items 1, 3, 6. Route redirect.
4. **Evidence unification:** Quality-findings tab + the one net-new endpoint
   (`GET /api/quality/findings?severity=&asset=&since=`), retarget all risk drill-downs.
5. **Hub hardening:** Asset 360 priority-order layout, shared header with Discover preview,
   request-access dialog, failure contract; term + work-item mini-hubs.

Each move closes under the CLAUDE.md verification rule: independent subagent walk + owner-flow
sweep before "done".
