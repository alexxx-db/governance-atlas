# Axiom — Cohesion Rebuild (canonical architecture)

Status: **decided law** for the experience-layer rebuild (2026-07-21). Synthesized from three
adversarial blueprints: product/IA, frontend technical inventory, and the Asset 360 forensic
teardown (full texts archived in the session scratchpad `arch_product/BLUEPRINT.md`,
`arch_frontend/BLUEPRINT.md`, `arch_entity/TEARDOWN.md`). Backend services (canonical
`semantics.py`, truthful lineage, honest envelopes) are fixed ground; the experience layer is
rebuilt on three system layers.

## Diagnosis (measured)

- Three coexisting component generations; a prior design-system kit was built and orphaned
  (9 of 14 components have zero users) while surfaces hand-roll 11 heroes, ~190 KPI-tile
  selector families, 8 tables. 32,972 lines of CSS, 87% legacy `gh-*`, 1,451 `!important`.
- Seven parallel cross-surface navigation mechanisms; ~16 drilled callback props; zero real
  `<a href>` anchors — no entity mention anywhere is middle-clickable.
- 11+ copy-pasted envelope-hydration predicates; 12 of 14 polls unbounded.
- The hub page (Asset 360) is nav-orphaned (item defined, never listed), regresses to its
  loading shell on tab switches (`null ?? TTL` bug), and its composite endpoint hard-codes
  freshness/quality/access to "unavailable".

## Target surface map (seven surfaces + one hub)

| Surface | Canonical route | Aliases (redirects) | Notes |
|---|---|---|---|
| Command Center | `/home` | `/`, `/command-center`, `/exec`, `/insights` | Absorbs Insights' three backed widgets (Risk Heatmap, Coverage-by-Domain, Certification-by-Tier). Kills Present mode, ROI tiles, empty AI slots. |
| Discover | `/discovery` | `/discover` | Preview panel renders the same header component as the hub. |
| **Asset 360 (hub)** | `/assets/<fqn>` | `/asset/*`, `/entity/*` | Hub-and-spoke: reached from every chip, plus a rail entry. `?tab=` addressable; drawer preview binds `?peek=<fqn>`. |
| Stewardship | `/stewardship` | `/governance`, `/sk`, `/inbox` → `/stewardship?assignee=me` | One queue, two lenses; bell becomes a popover; InboxPage dies. `?item=GOV-<hex8>` addressable. |
| Glossary & CDEs | `/glossary` | `/taxonomy`, `/glossary-cdes`, `/cde` → `?tab=cdes` | Term detail path-addressable `/glossary/<termId>`; CDE `?tab=cdes&cde=<id>`. |
| Lineage Atlas | `/lineage/<fqn>` | `/lineage-atlas` | Bare `/lineage` = search-first asset picker (kills the jargon landing). |
| Evidence | `/evidence` | `/audit`, `/audit-evidence` | Absorbs quality findings as a tab (`?tab=quality`); risk drills land here, not on dashboard tiles. `?event=AUD-<hex8>` addressable. |
| Control Center | `/admin` | `/control-center`, `/capabilities` → `?tab=diagnostics` | Admin-gated; demoted to the profile cluster. |

Nav rail: **GOVERN** (Command Center, Discover, Stewardship [my-work badge]) ·
**KNOWLEDGE & PROOF** (Glossary & CDEs, Lineage Atlas, Evidence) · profile cluster
(Control Center admin-gated, Help). Asset 360 appears in the rail when an asset is in
context AND is listed in `NAV_SECTIONS` (the current dead-code bug is fixed by the route
table generating the rail).

## Cross-linking contract (LAW)

Any mention of these entities anywhere is a real `<a href>` rendered by `EntityChip` — the
only legal way to render them:

asset → `/assets/<fqn>` · column → `/assets/<fqn>?tab=columns&col=` · term →
`/glossary/<termId>` · CDE → `/glossary?tab=cdes&cde=` · owner/steward →
`/discovery?q=owner:"…"` · work item → `/stewardship?item=GOV-…` · audit event →
`/evidence?event=AUD-…` · quality finding → `/evidence?tab=quality&asset=…&run=…` ·
catalog/domain → `/discovery?filters=…`.

## Three system layers (Wave A)

1. **Component kit** `frontend/src/components/system/` — PageShell, SectionCard, StatTile,
   EntityChip, DataTable, StateViews (Loading/Empty/Unavailable/StatusBanner — the only
   status renderings allowed), Toast, Drawer, TabStrip (URL-bound via `param`), FilterBar,
   Badge, Button. One `system.css`, all `ax-*` tokens. Dependencies point inward only.
2. **Data contract** `hooks/useAxiomQuery.js` + `lib/envelope.js` — the single
   envelope-status implementation; bounded polling mandatory (`poll.maxAttempts`); seeds
   render as `hydrating` (never blank "loading"); refresh failures degrade, never wipe.
   No component may import fetch/useQuery/axiomQueryClient or interpret `meta.state`.
3. **Navigation fabric** `frontend/src/nav/` — `routes.js` table (surface, path, aliases,
   nav metadata, params schema) drives `<Routes>`, the rail, the palette, and
   `navigate(entityRef|surfaceRef)`. `useSurfaceParams(schema)` for typed URL state.
   Kills: sessionStorage handoffs, custom window events, `workspaceIntent`, raw
   `history.replaceState`, `location.state.fresh`, drilled callbacks, discovery params
   riding on other surfaces. The URL is the state.

## Cohesion laws (permanent, CI-enforced)

1. One entity model — one route per entity kind, one EntityChip; the text is the anchor.
2. One number per concept — semantics live in `axiom/services/semantics.py`; the frontend
   renders payload labels, never re-derives. Two same-named numbers with different values
   on one screen is a release blocker.
3. One loading grammar — skeleton = loading; "—" + reason = unavailable; "Collecting since
   <date>" = young series. Loading envelopes are never cached and never rendered as data;
   definitive zeros during hydration are release blockers.
4. Two freshness words — "Data updated" (Delta write) vs "Metadata changed"
   (last_altered); nothing unlabeled.
5. Hub-and-spoke — surfaces answer estate questions, hubs answer entity questions;
   surfaces link to hubs instead of duplicating them.
6. One voice — copy registry; banned vocabulary ("actor-visible", "hydrating", raw enums,
   internal ids) enforced by lint.
7. No dead controls, no fabricated data (incl. fake sparklines, hard-coded "unavailable"
   composites, "(Last 30 days)" labels on unwindowed counts).
8. CI guardrails: `scripts/check-css.mjs` (no new `gh-*`, no raw hex outside tokens, no
   `!important`, no CSS imports outside main.jsx, gh-count ratchet); ESLint restrictions
   (fetch/useQuery/storage/events/history bans outside sanctioned modules);
   `refetchInterval` only inside useAxiomQuery.

## Waves

- **A (parallel, no visual change):** A1 system kit · A2 data contract + hook refactors
  (incl. the `null ?? TTL` fix) · A3 nav fabric + CI guardrails · A4 backend
  (`GET /api/quality/findings`; /360 composite joins real freshness/quality/access;
  activity payloads carry actor/priority/task ids; distinct `dataUpdatedAt`/`lastAltered`
  fields).
- **B:** B1 AppShell rewrite (Routes from the table; App.jsx → ~150 lines; AppFrame dies;
  Axiom AI extracted to a dock) · B2 Asset 360 rewritten on the kit (PageShell + `?tab=` +
  EntityChips; two parallel queries replacing the 4-stage waterfall; real header actions —
  Certify writes + audits, Request composer, honest lineage button; teardown rebuild spec
  items 1-12).
- **C (pairs):** C1 Discovery ∥ C2 Command Center (absorbs Insights) → C3 Stewardship
  (absorbs Inbox) ∥ C4 Glossary/CDE → C5 Evidence (quality tab) ∥ C6 Admin (+ diagnostics)
  → C7 Lineage adoption → C8 cleanup (delete northstar/, legacy primitives, legacy CSS,
  `--gh-*` aliases; ratchet to zero).
- Every wave closes per CLAUDE.md: build + deploy + independent subagent browser signoff +
  owner sweep; waves B and C1 additionally get the four-role critical-review swarm.
