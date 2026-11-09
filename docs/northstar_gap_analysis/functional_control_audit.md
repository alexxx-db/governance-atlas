# Functional Control Audit

Status: reopened and blocking after the 2026-05-02 false-signoff review.

The previous `0` open control state is invalid. Current local prototype reports may
remain as reproduction/capture-health artifacts, but they cannot close
customer-facing product readiness rows. Each visible control now needs current
live/runtime evidence with `mockApi=false`, or a truthful disabled/unavailable
state recorded in the reopened audit.

This ledger is the control-level companion to `full_page_audit.md`. It tracks
visible controls that must be exercised, backed, truthfully unavailable, or disabled
before any `northstar/*` page can receive functional signoff.

Authoritative reading rule: unchecked reopened rows at the top of each page section
are the current blockers. Historical checked rows below those reopened blocks are
retained only as prior evidence history; they do not close the reopened controls and
must not be read as current functional completion proof.

Current closure evidence required:

- None of the reopened customer-facing control rows currently has closure-grade
  evidence unless that row cites current live/runtime evidence with `mockApi=false`
  from the active reopened epoch, or records a truthful disabled/unavailable outcome.
- Historical prototype, mock, fixture, local-only, or intercepted reports below are
  retained only for reproduction, capture health, or prior-state debugging. They do
  not close product-readiness controls, even when an older bullet says `passed`.
- Older live Databricks reports below prove only the build, deployment, and
  interaction IDs named in their own bullet. They must be rerun for the active epoch
  before they can close reopened controls.

Active current control evidence:

- `docs/northstar_visual_qa/live-runtime-current-v215-full-functional-emet-test-2026-05-04/prototype-current-report.json`
  is the active all-route local-runtime control report for build
  `frontend-39d0070a8f87`; it has `mockApi=false`, `interactionCount=48`, and two
  expected invalid structured-search `400` checks. It is not deployed Databricks App
  proof.
- `docs/northstar_visual_qa/live-runtime-current-v216-performance-emet-test-2026-05-04/performance-report.json`
  is local runtime performance evidence for build `frontend-39d0070a8f87`; it has
  `budgetPassed=true` and explicitly warns that it is not deployed Databricks App
  proof.
- Functional reviewer recheck on v215 remains BLOCKED for any row not explicitly
  closed with current control-level evidence, deployed proof, or a truthful
  disabled/unavailable outcome.

Historical reproduction and non-closing evidence inventory:

- Historical comparison screenshots: see `global_current_evidence_dir` in
  `docs/northstar_gap_analysis/reference_manifest.json`; as of this reopened audit it
  points to local prototype-mock comparison evidence and cannot close rows.
- Historical all-route functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `24` route captures and
  `132` interaction records. Its cross-page shared-control interaction inventories
  `322` visible controls at each reviewed viewport, separates `90` to `91`
  hidden/accessibility-only controls, records `0` uncovered visible controls, verifies
  Axiom AI markdown rendering, and explicitly records that this is local
  prototype-mock evidence only, not live Databricks proof. Its older shared mutation
  map is superseded by scoped mutation evidence in
  `docs/northstar_visual_qa/shared-mutation-functional-v342-local/prototype-current-report.json`.
- Current scoped shared mutation-control evidence:
  `docs/northstar_visual_qa/shared-mutation-functional-v342-local/prototype-current-report.json`
  passed at `1536x1024` with `1` route capture and interaction
  `cross-page-control-contract`. It records `307` visible controls, `0` uncovered
  controls, and updates Stewardship `Comment` and `Resolve` dispositions to
  `disabled with visible prototype work-item rationale; no PATCH submitted`. This is
  local prototype-mock evidence only, not live Databricks proof.
- Shared shell profile-menu evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024` with interaction `shared-shell-chrome`. It proves the profile
  menu opens and that avatar upload is labeled `Upload local avatar` with an explicit
  local-browser-only title that excludes Databricks profile mutation. This is local
  prototype-mock evidence only, not live Databricks proof.
- Command Center functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures,
  `15` Command Center interaction records. It covers export, Present mode, trend windows,
  info affordances, catalog/domain/risk/CDE/activity routing, lower-scroll CDE/activity
  regions, and Command Center Axiom AI suggestion click, typed prompt, loading, answer,
  evidence, shared topbar search, chrome, and error states. The
  report includes `3` expected `503` Axiom AI error-path responses that are counted as
  expected failures by the harness. This is local prototype-mock evidence only, not live
  Databricks proof.
- Discover functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `27` loaded Discover interaction specs.
  It covers topbar search preload into Discover, valid/invalid/loading/empty search
  states, facets, reset browse, sort, local favorites, row action menus,
  selected-preview tabs, Asset 360/Governance/Lineage routing, disabled unbacked
  Comment/Request actions, sticky preview footer visibility, bottom-card Axiom AI
  Recommendations execution/evidence routing, selected-preview non-live provenance,
  and floating Axiom AI prompt/evidence from Discover. The report has three expected
  invalid-query `400` responses, one per reviewed viewport, and no page errors. This is
  local prototype-mock evidence only, not live Databricks proof.
- Stewardship functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `12` Stewardship interaction specs.
  It covers filter/pill/row selection, Bulk assign and New work item unavailable
  panels, Assign owner and Archive suggested-action unavailable panels, visible
  Comment and Resolve disabled states with non-authoritative prototype rationale,
  disabled pagination rationale, affected asset routing, absence of the removed
  non-reference open-lineage-context control, and
  floating Axiom AI prompt/evidence from Stewardship. The shared mutation map is
  narrowed by `docs/northstar_visual_qa/shared-mutation-functional-v342-local/prototype-current-report.json`.
  This is local prototype-mock evidence only, not live Databricks proof.
- Glossary functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `12` Glossary interaction specs. Supplemental current evidence in
  `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`
  clicks the reviewer workflow unavailable note, verifies detail close behavior, and
  routes the renamed `Preview lineage` affordance. It covers New term unavailable
  rationale, linked-asset association browsing with source FQN display, reviewer
  workflow, version history, hierarchy unavailable state, lineage preview routing,
  global search, help, profile menu, floating Axiom AI prompt/evidence, and
  responsive card control containment. This is local prototype-mock evidence only,
  not live Databricks proof.
- CDE Registry functional evidence:
  `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `12` CDE Registry interaction specs. Supplemental current evidence in
  `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`
  clicks the owner and recertification workflow unavailable notes, verifies selected-detail
  close behavior, and routes Lineage with `tab=cdes`. It covers source/detail routing,
  owner and recertification unavailable workflow notes, Lineage routing, CDE-tab
  `+ New term` semantics, absence of the non-reference CDE search/status/sort controls,
  floating Axiom AI prompt/evidence, and responsive table/control containment. This is
  local prototype-mock evidence only, not live Databricks proof.
- Lineage Atlas functional evidence:
  `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `15` current Lineage interaction records covering control, selected-node/detail,
  Notify Owners, asset-action absence, and Axiom AI interactions.
  It covers the current non-authoritative prototype shape: hidden authoritative-only
  Compare/Table/Search/Export toolbar controls stay absent, visible header Column
  lineage and Run impact analysis controls update state, canvas `+`/`-` mutate graph
  zoom state, `Fit graph` resets zoom, `Graph history` is disabled with a persisted-snapshot
  rationale, timeline `Now` reports useful status, all `9` visible graph
  nodes, `2` details-panel rows, `5` impact rows, and `4` column-lineage rows are
  clicked and recorded, Notify Owners is disabled with backed-impact rationale, the
  former selected-strip `Open asset` action is confirmed absent from the non-authoritative
  prototype topology,
  and floating Axiom AI suggestion, typed prompt, disabled-submit rationale, prototype
  evidence routing, accuracy notice, and close control are exercised. The report records
  `0` console errors, `0` page errors, and `0` request failures. This is local
  prototype-mock evidence only, not live Databricks proof.
- Current deployed Lineage Atlas functional evidence:
  `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`
  passed against deployed build `frontend-a848646ee695`, deployment
  `01f145c5425111deb3dd027dea2aff20`. It covers the live Lineage route at
  `1536x1024`, `1440x900`, and `1280x720`, with route settle, header
  `Column lineage`, Run impact analysis, canvas zoom/fit, toolbar
  `Table lineage`/`Column lineage`/`Search`/`Export`, a verified JSON evidence
  download, focus-node selection, every visible live graph node class or explicit
  unavailable detail rows, Refocus graph, missing-asset unavailable controls, and
  shared shell controls from Lineage route context. The report had `0` request
  failures, `0` page errors, and `0` console errors. These reports are live
  Databricks evidence for only the exercised controls; remaining visual and
  live-proof blockers stay open in `full_page_audit.md`.
- Audit Evidence functional evidence:
  `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`
  passed at `1536x1024` and `1280x720` with `2` route captures and `8` Audit Evidence
  interaction specs. It covers date-range menu selection, the `date_range=7d` request
  scope, the visible `Events · 7d` KPI scope, event filters, report and CSV exports,
  selected row detail, request ID copy, selected-detail asset routing, inline evidence
  target routing, and floating Axiom AI prompt/evidence. This is local prototype-mock
  evidence only, not live Databricks proof.
- Current deployed Audit Evidence functional evidence:
  `docs/northstar_visual_qa/audit-live-v386-databricks/audit-live-report.json`
  passed against deployed build `frontend-22deff27b4c2`, deployment
  `01f145b7211c1802a5c6116de31d6b00`. It covers the live Audit route settle,
  Audit API RLS/actor-exposure contract, date-range and category controls,
  selected-row/detail actions, report JSON download, and CSV download. The RLS
  interaction records `rowLevelSecurity=visible-assets-only`,
  `actorIdentityExposure=steward-admin-gated`, redacted actor samples, and
  `noUnscopedActorExposure=true`.
- Control Center functional evidence:
  `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`
  passed at `1536x1024`, `1440x900`, and `1280x720` with `3` route captures and
  `12` Control Center interaction specs. It covers prototype URL withholding with
  disabled linked-resource state, no-URL disabled detail, integration and policy
  detail, topbar search, notifications, help, profile menu, floating Axiom AI
  prompt/evidence, and responsive job/integration/policy/detail containment. This is
  local prototype-mock evidence only, not live Databricks proof.
- Local prototype-mock captures are not live Databricks proof.
- Allowed older multi-route live Databricks functional evidence:
  `docs/northstar_visual_qa/live-functional-v314-databricks/prototype-current-report.json`
  passed against then-current deployed build `frontend-5f4d8d113643`. It wraps the live API route
  validation at `docs/northstar_visual_qa/live-route-v304-databricks/route-validation.json`
  and deployed browser validation for Discover, Stewardship, Glossary, CDE Registry,
  Lineage, and Audit at the individual report paths listed in
  `docs/northstar_gap_analysis/reference_manifest.json`.
  The API route gate validates the v314 runtime, bootstrap, Asset 360, Lineage,
  Governance, Insights, Taxonomy, CDE, Audit, Admin, Genie, and Lakebase evidence.
  The browser gates validate route controls, truthful empty/unavailable states,
  selected-row/detail workflows, report/CSV downloads, and Lineage thin-data controls
  where those controls are visible in the deployed app. This is live Databricks
  evidence, not prototype-mock evidence.
- Current Lineage-specific live Databricks control evidence is pinned separately at
  `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`
  for deployed build `frontend-a848646ee695` after the export-download,
  unavailable-state, restricted-boundary graph-node, and Lineage route-context
  shared-shell updates.

## Page Status Summary

| Page | Open Controls | Status |
| --- | ---: | --- |
| Command Center | 2 | Blocked |
| Discover | 3 | Blocked |
| Stewardship | 1 | Blocked |
| Glossary | 1 | Blocked |
| CDE Registry | 1 | Blocked |
| Lineage Atlas | 5 | Blocked |
| Audit Evidence | 1 | Blocked |
| Control Center | 1 | Blocked |
| Cross-Page Shared | 1 | Blocked |

## Command Center Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: export fallback must show visible failure feedback if browser blob export support is unavailable.
- [ ] functional: current Command Center evidence is local prototype evidence and does not prove current deployed/live controls.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] topbar search routes typed queries to Discover and preserves query text. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-search`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] workspace breadcrumb opens/navigates to Command Center without breaking active state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] notifications control opens a truthful notifications state or is disabled. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] help control opens useful support/help content. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] profile menu opens profile/avatar/preferences without layout breakage, and avatar upload is labeled as a local browser preference instead of Databricks profile mutation. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI button opens/closes the panel and records a prompt workflow result. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI suggestions and typed input show loading, answer, evidence, and error states. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Export brief produces an artifact with document-level, workspace-label, posture aggregate, KPI row, catalog row, and activity row mock/live provenance and verified contents. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `primary-controls`, downloaded artifact `command-center-brief-axiom-command-center-2026-05-01.json`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Present mode toggles a local presentation view with visible no-mutation framing. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `primary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] `12w`, `26w`, and `52w` trend controls are clicked and record exclusive active-state/range evidence in the local prototype report. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `primary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] chart/tooltips/info icons expose accessible detail. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `domain-risk-activity-lower`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] domain posture rows/links navigate or open detail where supported. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `domain-risk-activity-lower`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] risk breakdown queue/open-exposure links navigate or open detail where supported. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `domain-risk-activity-lower`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] catalog rows open catalog/asset health detail where supported. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `catalog-navigation`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] CDE cards/links open CDE or source asset detail where supported. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `cde-navigation`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] activity stream rows open corresponding asset, work item, or audit evidence. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `domain-risk-activity-lower`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] lower-scroll `prototype_home2` regions are captured and functionally exercised. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `domain-risk-activity-lower`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.

## Discover Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: Saved searches are local/hardcoded rather than persisted or clearly unavailable.
- [ ] functional: Recommended Assets `View all` selects a recommendation instead of opening a complete recommendations view.
- [ ] functional: selected-preview and lineage warm-up latency need measured evidence from click to useful state.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] topbar search routes to Discover and preloads entered query. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `topbar-search-preload`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Discover search handles valid, invalid, loading, and empty queries. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] certification facet updates results and count state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] domain facet updates results and count state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] classification facet updates results and count state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] attribute facet updates results and count state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] clear filters resets results and all visible counts. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Saved searches opens, applies, creates, or truthfully disables saved-search workflow. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Advanced opens grouped OR search insertion and truthful deleted/inaccessible disabled states in the local prototype workflow. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, grouped query `domain:(Finance OR Customer)`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] sort menu changes visible sort order. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `sort-and-row-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] list/grid toggle controls are clickable and record visible pressed-state changes in the local prototype report. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `filters-layout`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] result row click opens the selected preview/asset workflow. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `selected`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] row favorite behavior is backed or clearly local/unavailable. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `sort-and-row-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] row kebab/action menu opens usable actions or truthful unavailable state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `row-menu-routing`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview close restores the results state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview tabs switch content. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview `Open Asset 360` opens the asset record/drawer. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-asset-routing`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview lineage action opens Lineage Atlas or truthful unavailable state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-lineage-navigation`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview governance/certify action opens a stewardship/governance workflow. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-asset-routing`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview Comment creates a backed thread/comment or is disabled. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview Request access creates a backed request or is disabled. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-actions`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] selected preview bottom sticky actions remain visible and usable at responsive widths. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `preview-actions`, viewport `1536x1024`, `1440x900`, and `1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing works from Discover and selected state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `axiom-ai-recommendations`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI Recommendations bottom-card `View all` generates recommendations or is disabled with rationale. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `axiom-ai-recommendations`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.

## Stewardship Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: governance mutation controls need disposable live proof or disabled unavailable states; current live QA skips mutation clicks.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] Filter opens the local prototype filter menu and records selected filter state. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] `All`, `P1 critical`, `Overdue`, and `Assigned to me` pills are exercised and record visible selected/pressed-state evidence. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] row selection updates the detail pane. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] affected asset opens Asset 360/asset record. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `asset-routing`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] non-reference open lineage context control is absent from the selected detail pane. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `lineage-navigation`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] suggested action `Assign owner` performs, opens a backed workflow, or is truthfully unavailable with rationale. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] suggested action archive/cleanup performs, opens a backed workflow, or is truthfully unavailable with rationale. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Comment is disabled for prototype work items with a non-authoritative visual-evidence rationale instead of submitting a mock PATCH. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Resolve is disabled for prototype work items with a non-authoritative visual-evidence rationale instead of submitting a mock PATCH. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Bulk assign performs, opens a backed workflow, or is truthfully unavailable with rationale. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] New work item opens/submits a backed creation workflow or is truthfully unavailable with rationale. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] single-page pagination is hidden with rationale instead of exposing non-reference footer controls. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `workbench-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing works from Stewardship. Evidence: `docs/northstar_visual_qa/stewardship-functional-v301-local/prototype-current-report.json`, interaction `axiom-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.

## Glossary Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: `TaxonomyWorkspace` is forced into prototype behavior, so reviewer, hierarchy, version, and association workflows cannot be treated as backed live workflows.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] Glossary/CDE tabs update URL state and active content. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] `+ New term` opens a creation/review workflow or truthful unavailable modal. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] glossary cards open a full term detail drawer/page. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] linked asset count opens an association browser, not only first asset. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] `Preview lineage` opens Lineage Atlas for a valid source asset without claiming live UC lineage proof. Evidence: `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] zero-asset glossary controls are absent in the current four-term prototype fixture, so no inert zero-association action is exposed. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] reviewer workflow is available or truthfully unavailable and the detail drawer close control is exercised. Evidence: `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`, interaction `glossary-controls`, validation checks `reviewerUnavailable`, `detailClosed`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] version history is available or truthfully unavailable. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] hierarchy/nested-term browsing is represented as a truthful unavailable/detail state in the current local prototype-mock route; an interactive hierarchy browser is not claimed. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `glossary-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] global search/help/profile controls work from Glossary. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `global-shell`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing works from Glossary. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `axiom-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] responsive card layout keeps controls visible. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `responsive-card-controls`, viewport `1536x1024, 1440x900, 1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.

## CDE Registry Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: CDE owner/recertification workflows require live proof or truthful disabled unavailable states.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] Glossary/CDE tabs update URL state and active content. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-tab-request-no-extra-tools`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] CDE row click opens a column/source detail workflow. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] CDE asset association opens an association browser or source asset. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] CDE lineage link opens Lineage Atlas for the source asset. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] reviewer/owner workflow is available or truthfully unavailable. Evidence: `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`, interaction `cde-controls`, validation check `ownerUnavailable`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] recertification workflow is available or truthfully unavailable and the selected CDE detail close control is exercised. Evidence: `docs/northstar_visual_qa/taxonomy-functional-v354-local/prototype-current-report.json`, interaction `cde-controls`, validation checks `recertUnavailable`, `detailClosed`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] non-reference CDE search/status/sort controls are absent from the current first viewport by design, so there are no visible inert CDE filter/sort controls to exercise. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-tab-request-no-extra-tools`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] `+ New term` clarifies whether it creates glossary term or CDE request. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `cde-tab-request-no-extra-tools`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing works from CDE Registry. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `axiom-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] responsive table layout keeps owner, recert, status, and SOX controls visible. Evidence: `docs/northstar_visual_qa/cde-functional-v225-local/prototype-current-report.json`, interaction `responsive-table-controls`, viewport `1536x1024, 1440x900, 1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.

## Lineage Atlas Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: custom North Star graph canvas did not support drag/pan.
- [ ] functional: `Now`/as-of action changes status text only unless wired to a backed refresh/time-selection workflow or disabled.
- [ ] functional: Search toggle announces opened even when closing and needs full open/search/clear/no-results/live-backed coverage.
- [ ] functional: Lineage export, graph search, pan/drag, zoom, reset, selected-node, restricted-boundary, notify-owner, and column-row workflows need current live/runtime evidence or explicit unavailable states.
- [ ] functional: Lineage edge selection, edge-detail affordances, and keyboard graph navigation have no current control-level evidence.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] authoritative-only Compare/Table/Search/Export toolbar controls are absent from the non-authoritative prototype Lineage view. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] header Run impact analysis focuses the impact panel and preserves non-live/backed-impact wording. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] header Column lineage activates column-lineage status and graph state. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] canvas `+` and `-` controls change graph zoom state, `Fit graph` resets zoom to `100%`, and `Graph history` is disabled with a persisted-snapshot rationale when no history exists. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] timeline `Now` resets the as-of status in the non-authoritative view. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] all `9` visible graph node/detail buttons are exercised and select the local detail surface without implying live lineage proof. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-selection`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] restricted node/detail preserves permission-boundary wording. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-selection`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] all `5` visible impact consumer/detail buttons are exercised and select local detail without implying backed usage or workflow mutation. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-selection`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] all `4` visible column-lineage lower rows are exercised and select local row state or render truthful unavailable shape. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-selection`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] both visible Lineage details-panel source/consumer rows are exercised and select local detail without creating a fake route workflow. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `lineage-selection`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] former selected-strip `Open asset` is absent in the non-authoritative prototype topology, so no hidden/unsupported asset route action is exposed. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `asset-navigation`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Historical only: the former Notify owners action was disabled with backed-impact rationale in local prototype evidence. It is not current closure proof; the current product control is renamed to Review owners unless a real notification mutation exists. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `notify-owners`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing, disabled-submit rationale, accuracy notice, and close control work from Lineage Atlas. Evidence: `docs/northstar_visual_qa/lineage-functional-v261-local/prototype-current-report.json`, interaction `axiom-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] authoritative live graph toolbar `Table lineage`, toolbar `Column lineage`, `Search`, and `Export` controls are exercised against the current deployed Lineage build, with search result selection and export artifact contents recorded. Evidence: `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`, interaction `deployed-lineage-toolbar-search-export`, downloaded artifact `lineage-evidence-customer_stewardship_queue.json`, validation checks `exportDownloaded`, `exportHasEvidenceKind`, `exportMatchesLiveAsset`; Reviewer: Functional workflow; Date: 2026-05-02; Type: live_databricks.
- [x] current live Lineage unavailable-state controls `Retry`, `Clear focus`, and selected-strip `Open asset` are clicked after a missing-asset route and recorded as truthfully unavailable or disabled with reason. Evidence: `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`, interaction `deployed-lineage-unavailable-controls`, validation checks `retryTruthful`, `openAssetHandled`, `clearFocusShowsSearchState`, `noSyntheticUnavailableGraph`; Reviewer: Functional workflow + Truth/provenance; Date: 2026-05-02; Type: live_databricks.
- [x] current live Lineage graph/detail interactions cover every visible graph node class and explicitly log consumer, restricted/permission-boundary, impact, and column-detail rows as covered or unavailable for the sampled live graph, including hidden `system.*` lineage-only upstream nodes and live downstream consumers. Evidence: `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`, interaction `deployed-lineage-all-node-detail-classes`, validation checks `everyVisibleNodeClassClicked`, `consumerRowsCoveredOrUnavailable`, `restrictedCoveredOrAbsent`, `columnRowsCoveredOrUnavailable`; Reviewer: Functional workflow; Date: 2026-05-02; Type: live_databricks.

## Audit Evidence Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: date-range evidence must prove backed query scope changes, not only local labels and download names.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] Date range menu changes query scope in the local prototype report; a full calendar workflow is not evidenced here. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Generate report creates a backed artifact or clearly labeled local/mock artifact with top-level, summary, and event-level provenance. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, downloaded artifact `audit-report-governance-audit-report-7d.json`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Export CSV downloads filtered rows with provenance and verified contents. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, downloaded artifact `audit-events-governance-audit-7d.csv`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] All events tab filters rows. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] By users tab filters/group rows. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] By services tab filters/group rows. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Violations tab filters rows. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-controls`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] evidence/open-link affordances open detail or external evidence where available. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `audit-evidence-link`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] Axiom AI suggestions/input/evidence routing works from Audit Evidence. Evidence: `docs/northstar_visual_qa/audit-functional-v199-local/prototype-current-report.json`, interaction `axiom-ai`, viewports `1536x1024`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.

## Control Center Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: row actions can end in local status text instead of opening a real resource or disabled unavailable detail.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] scheduled job rows open backed Databricks job/run detail only outside prototype-mock evidence; prototype fixture URLs are disabled and withheld with a non-live rationale. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] scheduled job rows show truthful unavailable detail when no URL exists. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] integration rows expose connection detail/configuration state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] policy coverage rows open policy/evidence detail where supported. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] `Open linked resource` is disabled for prototype URLs and unavailable rows, and the report records that no external URL opened in prototype-mock evidence. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] topbar search/help/profile controls work from Control Center. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] notifications state is accurate for runtime/control-center events. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `control-shell-chrome`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI route-specific prompts/input/evidence routing works from Control Center. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `axiom-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] responsive layout keeps job, integration, and policy controls visible. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `responsive-control-layout`, viewport `1536x1024, 1440x900, 1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.

## Cross-Page Shared Controls

<!-- reopened-2026-05-02-active-rows:start -->
Reopened active rows from `docs/northstar_gap_analysis/reopened_2026_05_02_visual_functional_audit.md`:
- [ ] functional: local prototype functional evidence has been used to close route controls that need current live/runtime proof or truthful disabled states.
<!-- reopened-2026-05-02-active-rows:end -->

- [x] every visible button/link/menu/tab/pill/search/input is included in this ledger or page ledger. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `cross-page-control-contract`, `322` visible controls and `0` uncovered controls at each reviewed viewport, viewports `1536x1024`, `1440x900`, `1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] visible no-op handler candidates are inventoried and non-mutation closures are either routed, disabled, or shown with a truthful unavailable panel; scoped shared mutation evidence now records no-PATCH disabled Stewardship Comment/Resolve dispositions. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `cross-page-control-contract`, `0` uncovered controls, viewports `1536x1024`, `1440x900`, `1280x720`; supplemental evidence `docs/northstar_visual_qa/shared-mutation-functional-v342-local/prototype-current-report.json`, interaction `cross-page-control-contract`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] visible controls are distinguished from hidden accessibility-only controls in QA artifacts. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `cross-page-control-contract`, `322` visible controls and `90` to `91` hidden/accessibility-only controls, viewports `1536x1024`, `1440x900`, `1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] functional report records control name, interaction, result, backing, and evidence path. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `row-menu-routing`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] global navigation routes all prototype pages and preserves active state. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `global-navigation-routes`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] global search supports keyboard submission and mouse submission. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-search`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] global command palette supports slash open, search-result navigation, no-match empty state, and Escape close. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-command-palette`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI panel supports open, close, prompt suggestion, typed submit, loading, answer, evidence, and error states. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI renders markdown safely without raw formatting artifacts. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `cross-page-control-contract`, markdown safety flags `hasStrong`, `hasListItem`, `hasCode`, `hasSafeLink`, and no raw markers/unsafe href/script element, viewports `1536x1024`, `1440x900`, `1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] Axiom AI evidence links route to supported product surfaces. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] downloadable/export controls are verified by artifact content, not just click success. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `audit-controls`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] shared mutation-control evidence map was narrowed so Stewardship `Comment` and `Resolve` are recorded as disabled with visible prototype work-item rationale and no PATCH submission, matching current route evidence. Evidence: `docs/northstar_visual_qa/shared-mutation-functional-v342-local/prototype-current-report.json`, interaction `cross-page-control-contract`, `307` visible controls, `0` uncovered controls, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-05-01; Type: local prototype_mock.
- [x] loading states show useful progress for slow startup and slow AI responses. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `shared-shell-ai`, viewport `1536x1024`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] responsive viewports are tested for controls hidden behind the AI rail. Evidence: `docs/northstar_visual_qa/all-functional-v122-local/prototype-current-report.json`, interaction `responsive-control-layout`, viewport `1536x1024, 1440x900, 1280x720`; Reviewer: Functional workflow; Date: 2026-04-30; Type: local prototype_mock.
- [x] responsive Axiom AI floating action button opens and closes the chat from every non-Lineage route at `1536x1024`, `1440x900`, and `1280x720`, while Lineage keeps that launcher hidden to preserve the lineage-detail reference shape. Evidence: `docs/northstar_visual_qa/responsive-ai-fab-v412-local/prototype-current-report.json`, interaction `responsive-ai-fab`, viewports `1536x1024`, `1440x900`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-02; Type: local prototype_mock.
- [x] deployed/live Databricks validation was rerun against the then-current multi-route deployed bundle, and the current broad live route API gate is pinned separately for build/deployment truth. Evidence: `docs/northstar_visual_qa/live-functional-v314-databricks/prototype-current-report.json`, interactions `deployed-live-route-validation`, `discover-deployed-browser-validation-summary`, `stewardship-deployed-browser-validation-summary`, `glossary-deployed-browser-validation-summary`, `cde-registry-deployed-browser-validation-summary`, `lineage-deployed-browser-validation-summary`, `audit-deployed-browser-validation-summary`, viewport `DEFAULT dev deployment + 1536x1024, 1440x900, 1280x720`; Reviewer: Functional workflow; Date: 2026-05-01; Type: live_databricks.
- [x] current deployed/live Lineage validation was rerun against build `frontend-a848646ee695` and deployment `01f145c5425111deb3dd027dea2aff20` for the current live restricted-boundary route. Evidence: `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`, interactions `deployed-lineage-route-settled`, `deployed-lineage-column-action`, `deployed-lineage-impact-action`, `deployed-lineage-canvas-zoom`, `deployed-lineage-toolbar-search-export`, `deployed-lineage-focus-node-selection`, `deployed-lineage-all-node-detail-classes`, `deployed-lineage-refocus-graph`, `deployed-lineage-unavailable-controls`, `deployed-lineage-shared-shell-controls`, viewports `1536x1024`, `1440x900`, `1280x720`; Reviewer: Functional workflow; Date: 2026-05-02; Type: live_databricks.
- [x] current deployed Lineage build exercises shared shell controls from the Lineage route context, including topbar search, command palette, notifications, help, profile, and Axiom AI open/prompt/close behavior. Evidence: `docs/northstar_visual_qa/lineage-restricted-live-v399-databricks/lineage-live-report.json`, interaction `deployed-lineage-shared-shell-controls`, validation checks `topbarSearchRoutes`, `commandPaletteLineageResult`, `notificationsHandled`, `helpRoutes`, `profileMenuHandled`, `axiomAiHandled`, `axiomAiClosed`; Reviewer: Functional workflow; Date: 2026-05-02; Type: live_databricks.
