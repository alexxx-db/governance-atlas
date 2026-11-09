# Prototype North Star Contract

Last updated: 2026-04-29 01:32 EDT

Active reference:

- HTML prototype: `northstar/Axiom.html`
- Prototype source: `northstar/app.jsx`, `northstar/pages/*.jsx`, `northstar/components/*.jsx`, `northstar/styles/*.css`, `northstar/data/mock.js`
- Prototype screenshots: `northstar/screenshots/*.png`
- Current evidence target is not hard-coded in this file. The only active
  current-evidence pointer is `global_current_evidence_dir` in
  `docs/northstar_gap_analysis/reference_manifest.json`.
- Any older screenshot directory listed in changelog/status output is historical unless
  it is the manifest's current directory at the time of review.

This file supersedes the previous Home-only checklist for any new visual signoff. The previous evidence is historical only.

## Rules Of Engagement After False Signoff

- Every screenshot-backed route in `northstar/screenshots/*` must be audited with the
  same rigor as the Command Center audit: visible differences, functional gaps, and
  truth/provenance gaps must be written into
  `docs/northstar_gap_analysis/full_page_audit.md`.
- Subagent consensus is only valid when each reviewer names the exact reference
  screenshot(s), current screenshot(s), viewport(s), and audit rows inspected.
- Route capture success, unit tests, typecheck, Databricks bundle validation, and
  subagent assertions are separate inputs; none of them can substitute for
  side-by-side visual inspection or control-level workflow testing.
- A page with any unchecked must-fix visual or functional row remains blocked, even if
  all previously known blockers have been fixed.
- When a prototype element is unrealistic for Databricks Apps or Unity Catalog, replace
  it only with a stronger Databricks-native product behavior and record the deviation
  and rationale in the audit ledger before closing the row.

## Global Shell

### Structural Parity Required Now

- Left rail uses the prototype taxonomy: `Command Center`, `Discover`, `Stewardship`, `Glossary & CDEs`, `Lineage Atlas`, `Audit Evidence`, `Control Center`.
- Rail groups remain visible as `Govern`, `Knowledge`, and `Trust`.
- Topbar contains workspace breadcrumb, centered global search, UC connection/coverage chip, alert/help affordances, and `Axiom AI`.
- Floating Axiom AI panel is available from all pages and remains visually consistent with the prototype.
- Content is centered within a wide product canvas with a large right-side AI rail/floating panel presence where applicable.

### Functional Required Now

- Every nav item routes to the intended page and preserves active state.
- Topbar search opens Discover and preloads the entered query.
- `Axiom AI` opens/closes the floating AI panel, can submit a prompt, shows loading, renders evidence-backed answers, and avoids raw markdown artifacts.
- User/profile affordance must not break existing avatar upload/fallback behavior.

### Truth Constraints

- UC connection and coverage chip must be derived from runtime/bootstrap/command-center state, or marked degraded.
- AI grounding claims must be true for Genie-backed answers. If Genie is unavailable, the UI must say so.

## Command Center

Reference screenshots: `prototype_home1.png`, `prototype_home2.png`

Important correction: `prototype_cc.png` is a Control Center screenshot and must not
be used as Command Center/Home evidence.

### Structural Parity Required Now

- Hero headline reads as executive posture rather than generic command-center copy.
- Hero card includes trust/posture ring, executive narrative, narrative stats, and `What changed today`.
- KPI row has four compact cards with labels, large values, deltas, and sparklines.
- Main grid includes coverage trend, posture by domain, risk breakdown, top catalog health snapshot, critical data elements, and activity stream.
- Page density should fit the prototype rhythm at the 3037x1269 reference ratio and nearest Playwright viewport.

### Functional Required Now

- `Export brief` exports/downloads a truthful brief or opens a truthful unavailable state.
- `Present mode` toggles a presentation-friendly view or records a truthful deferral with disabled state.
- Time-range buttons on coverage trend update active state and chart data.
- Catalog rows, activity asset links, CDE links, and queue links navigate to the corresponding surface where openable.

### Truth / Data Required Now

- Posture, KPI, domain, risk, catalog, CDE, and activity values must be live/seeded governance state, not hard-coded client fiction.
- Synthetic seed data may create UC tables/tags/comments/owners/workflow rows in `DEFAULT` to produce realistic variance, but must be identifiable as seeded demo metadata and removable by cleanup.

## Discover

Reference screenshots: `prototype_discover1.png`, `prototype_discover2.png`

### Structural Parity Required Now

- Page header: `Find trusted, governed data`.
- Prominent search row with saved-searches and advanced controls.
- Left filter rail with certification, domain, classification, and attributes.
- Results list with asset icon, name, FQN, certification/classification/CDE/PII chips, description, owner/freshness/usage/lineage metrics, and right-side trust score.
- Asset detail/preview/Asset 360 behavior must preserve the prototype's quick-inspect feel.

### Functional Required Now

- Search is live and permission-aware.
- Filters update counts/results and can be cleared.
- Saved searches can be opened/created or clearly state unavailable with no dead buttons.
- Advanced search supports grouped/structured filtering, or a truthful current-scope implementation.
- View mode/sort controls change state.
- Result click opens Asset 360 or a full asset record without broken navigation.

### Truth / Data Required Now

- Counts and trust scores must be derived from real/seeded metadata and governance control-plane rows.
- Deleted/inaccessible assets must be represented truthfully, not fabricated as openable records.

## Stewardship

Reference screenshot: `prototype_stewardship1.png`

Important correction: `prototype_stewardship2.png` is a CDE Registry screenshot and
must not be used as Stewardship evidence.

### Structural Parity Required Now

- Header shows open work items and SLA breaches with action buttons.
- Queue filter pills: All, P1 critical, Overdue, Assigned to me.
- Work queue table with selected row highlighting.
- Right detail pane shows item ID, priority/SLA/assigned chips, affected asset, why-open evidence, suggested actions, comment/resolve controls, and implementation provenance.

### Functional Required Now

- Filter pills update table and counts.
- Row selection updates the detail pane.
- Affected asset opens Asset 360/asset record.
- Suggested actions are clickable and either perform supported actions or open accurate workflows.
- Comment and Resolve create/write auditable governance workflow state.
- Bulk assign and New work item are functional or disabled with precise truthful reason.

### Truth / Data Required Now

- Work items must come from real governance workflow rows or seeded workflow rows in `DEFAULT`.
- SLA state and routing must be computed from item timestamps/domain ownership where practical.

## Glossary & CDEs

Reference screenshots: `prototype_glossary1.png` and `prototype_stewardship2.png`

Important correction: `prototype_stewardship2.png` is the checked-in CDE Registry
visual reference despite its filename.

### Structural Parity Required Now

- Header: `Shared business meaning, anchored to data`.
- Tabs for Glossary and CDE Registry with counts.
- Glossary card grid with term, domain/steward, status, definition, linked-assets count, lineage link.
- CDE table with source-of-record column, owner, recert, status, and SOX indicator.

### Functional Required Now

- Tabs switch without reload and preserve layout.
- New term opens a creation/review workflow or truthful unavailable modal.
- View lineage links route to Lineage Atlas for a source asset.
- CDE rows open Asset 360/asset record scoped to the backing column/table.

### Truth / Data Required Now

- Glossary and CDE content must be backed by governance tables or seeded governance rows.
- Reviewer/version history must remain accessible where supported; otherwise display an honest partial state.

## Lineage Atlas

Reference screenshot: `prototype_lineage.png`

### Structural Parity Required Now

- Header names a real focus asset and explains permission-aware lineage.
- Chips show certification, freshness, CDE count, owner, upstream/downstream.
- Main graph uses upstream/focus/downstream hop columns, typed nodes, arrows, restricted node affordance, and column-lineage controls.
- Lower grid includes impact analysis and column lineage.

### Functional Required Now

- Lineage page loads reliably from nav and from Asset 360.
- Compare versions opens a comparison workflow or clear unavailable state.
- Run impact analysis returns affected consumers/work items or honest unavailable state.
- Column lineage toggle changes visible column lineage state.
- Zoom/export controls work.
- Impact rows and graph nodes open assets where permission allows.

### Truth / Data Required Now

- Table and column lineage must use Databricks lineage/system tables or seeded lineage metadata with explicit provenance.
- Hidden/restricted nodes must not expose unauthorized asset details.

## Audit Evidence

Reference screenshot: `prototype_audit1.png`

### Structural Parity Required Now

- Header: `Immutable governance event log`.
- Four KPI cards: events, policy violations, access reviews, retention.
- Filter tabs: all events, by users, by services, violations.
- Audit table with time, actor, event, target, evidence, and open-evidence affordance.
- Delta retention/evidence note appears below the table.

### Functional Required Now

- Date range changes query scope.
- Generate report produces an artifact or clear unavailable state.
- Export CSV downloads the filtered audit rows.
- Filter tabs update rows and counts.
- Evidence links open supported detail pages or external evidence where available.

### Truth / Data Required Now

- Events must be real audit/governance event rows or seeded append-only audit rows.
- No raw row values should be exposed in audit evidence.

## Control Center

Reference screenshot: `prototype_cc.png`

### Structural Parity Required Now

- Header: `Axiom runtime, integrations, and policy`.
- Scheduled jobs table with job, schedule, last run, and status.
- Integrations card with Unity Catalog, SQL Warehouse, Lakeflow Jobs, Model Serving, Slack/PagerDuty style integrations where applicable.
- Policy coverage card with policy bars.

### Functional Required Now

- Job rows link to Databricks job/run details when available.
- Integration rows expose connection status/details and do not imply unavailable integrations are configured.
- Policy rows link to definitions/evidence or show accurate unavailable state.

### Truth / Data Required Now

- Runtime status must come from bootstrap/runtime/probe data.
- External integrations not configured in this app must not be shown as active customer truth unless seeded explicitly as demo-only metadata.

## Asset 360 Supporting Drawer

Reference source: `northstar/pages/asset360.jsx`

Current signoff status: supporting workflow only. There is no Asset 360 screenshot under
`northstar/screenshots/`, so this drawer must remain functional and truthful where
prototype links open assets, but it is not a standalone visual parity gate for the
current screenshot contract.

### Structural Parity Required For Supporting Interactions

- Right drawer with asset hero, certification/classification/CDE/PII chips, tabs for overview, columns, lineage, quality, access.
- Overview stats: owner, steward team, freshness, quality, rows, usage, tags, glossary, buildability/provenance.
- Columns table with tags and masked/permission-gated behavior.
- Lineage preview can expand to Lineage Atlas.
- Quality and access tabs show backed checks/grants.

### Functional Required For Supporting Interactions

- Drawer opens from Discover, Command Center links, Stewardship affected asset, Lineage impact, and AI evidence where possible.
- All tabs switch and preserve content.
- Comment, request access, certify, profile now, and lineage expand either work or are disabled with a precise reason.

### Truth / Data Required For Supporting Interactions

- Asset metadata, columns, grants, tags, lineage, quality checks, and usage must be backed by UC/system/governance data or explicit seeded demo data.

## Axiom AI

Reference source: `northstar/pages/extras.jsx` and all screenshots with the right AI panel

### Structural Parity Required Now

- Floating panel has compact header, grounding statement, welcome text, suggestions, scrollable thread, evidence cards, and bottom input.
- Loading state shows what Axiom is querying.
- AI panel is available on every page without obscuring primary controls.

### Functional Required Now

- Suggestions send prompts.
- Input sends on Enter/click.
- Answers render markdown cleanly and show evidence.
- Evidence links route to Asset 360, Lineage, Work item, or Audit evidence.
- Panel open/close and resize/drag behavior remains intact where implemented.

### Truth / Data Required Now

- Axiom AI must route through Genie when configured.
- The UI must never claim row-level reads or unsupported access.
- Fallback/local responses must be clearly unavailable or degraded, not presented as Genie truth.

## Validation Matrix

- Prototype/current screenshots required at minimum: native prototype ratio `3037x1269`, `1536x1024`, `1440x900`, and a compact viewport near `1280x720` or nearest stable ratio.
- Functional workflow QA must cover shell nav, search, Discover filtering/sorting/opening, Stewardship item lifecycle, Glossary/CDE tabbing and links, Lineage loading/interactions/export, Audit filters/export/report, Control Center links, Asset 360 tabs/actions, and Axiom AI.
- Databricks closeout must run `bundle validate`, `bundle summary`, deploy, app deploy, live route validation, Genie benchmark, and seeded workflow verification for the `DEFAULT` profile unless an external blocker is recorded.

## Current Blocking Evidence

- Active current screenshot evidence is the directory named in
  `docs/northstar_gap_analysis/reference_manifest.json`.
- The active materialized gap ledger is
  `docs/northstar_gap_analysis/full_page_audit.md`.
- The active materialized control ledger is
  `docs/northstar_gap_analysis/functional_control_audit.md`.
- Local prototype-mock screenshots are useful for visual iteration, but they are not
  live Databricks proof. They must remain marked `prototype_mock` and
  non-authoritative.
- Older deployed captures, previous route-validation reports, and previous closeout
  notes are historical only unless they are regenerated for the current code state and
  cited by the manifest/ledger.

## Open Must-Fix Count

- Current open visual, functional, truth/provenance, and process counts are not stored
  in this contract. They must be computed from the active ledgers above.
- No page may be treated as complete while either active ledger has open rows for that
  page or shared shell/AI/process behavior.
- Any future zero-gap claim must be accompanied by current manifest evidence,
  control-level functional evidence, live Databricks validation where required, and
  reviewer signoff entries that cite exact artifacts.
- Signoff is route-scoped. A global `northstar/*` signoff, visual-completion claim,
  or reviewer-unanimity statement is invalid unless `signoff_matrix.md` has current
  route rows for every required reviewer role and the active ledgers show zero open
  rows for that route plus Cross-Page Shared.
- Closeout/status language must not use `visually indistinguishable`. Current state
  must be reported as concrete evidence paths, compared viewports, open row counts,
  reviewer roles, and explicit deferrals.
- Checked rows in the active ledgers must be evidence-backed. The evidence can live in
  the row itself or in the signoff matrix, but it must name the screenshot/report,
  viewport or interaction, reviewer role, date, and evidence type.
- Checked rows without structured evidence are invalid and must be reopened. The
  audit guard must reject evidence-less checkmarks before any reviewer closeout can
  stand.
