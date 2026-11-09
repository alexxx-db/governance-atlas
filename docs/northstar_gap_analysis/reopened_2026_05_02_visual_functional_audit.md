# 2026-05-02 Reopened Visual And Functional Audit

Status: reopened and blocking.

This audit supersedes the zero-open-row state in `full_page_audit.md`,
`functional_control_audit.md`, and `signoff_matrix.md`. No North Star page is
approved by the current ledger. Historical v415 evidence is local `prototype_mock`
evidence with `mockApi=true` and `interactionCount=0`; it is useful for comparison
and failure reproduction only. Current 2026-05-03 runtime evidence below replaces
v415 as the active non-closing comparison epoch, but it is still not deployed
Databricks App proof.

## 2026-05-03 Current Evidence Refresh - v132-v140

Status: current evidence is refreshed and still blocking. No route is visually or
functionally signed off.

- Active all-route current screenshots:
  `docs/northstar_visual_qa/live-runtime-current-v140-all-viewports-current-2026-05-03/prototype-current-report.json`
  - build `frontend-33133f44f929`
  - `mockApi=false`
  - `evidenceKind=runtime_app_capture`
  - `liveDatabricksCapture=false`
  - `captureCount=32`, `expectedCaptureCount=32`, `interactionCount=0`,
    `requestFailureCount=0`, `pageErrorCount=0`
  - viewports `3037x1269`, `1536x1024`, `1440x900`, `1280x720`
- Current all-route functional report:
  `docs/northstar_visual_qa/live-runtime-current-v135-full-functional-all-routes-2026-05-03/prototype-current-report.json`
  - build `frontend-33133f44f929`
  - `mockApi=false`
  - `evidenceKind=runtime_app_capture`
  - `liveDatabricksCapture=false`
  - `interactionCount=48`
  - `requestFailureCount=2`, both expected invalid structured-search `400` checks
  - local runtime only; not deployed Databricks App proof
- Focused functional supplements:
  - `docs/northstar_visual_qa/live-runtime-current-v132-focused-functional-command-lineage-control-2026-05-03/prototype-current-report.json`
    proves Lineage drag/pan with `graphPanAfter={"x":48,"y":22}` for build
    `frontend-33133f44f929`.
  - `docs/northstar_visual_qa/live-runtime-current-v134-cde-functional-recheck-2026-05-03/prototype-current-report.json`
    proves the current CDE `Open lineage` route handoff for build
    `frontend-33133f44f929`.
- Current supporting route-state captures:
  - `docs/northstar_visual_qa/live-runtime-current-v136-wide-current-all-routes-2026-05-03/prototype-current-report.json`
  - `docs/northstar_visual_qa/live-runtime-current-v137-wide-scroll-command-center-2026-05-03/prototype-current-report.json`
  - `docs/northstar_visual_qa/live-runtime-current-v138-wide-discover-selected-2026-05-03/prototype-current-report.json`
- Current side-by-side and palette audit:
  `docs/northstar_visual_qa/live-runtime-current-v139-reference-current-audit-2026-05-03/audit-artifact-manifest.json`
  - generated from v136, v137, and v138 current screenshots
  - all `10` route/state pairs are `BLOCKED`
  - max changed-pixel percentage above threshold `8`: `39.66`
  - max sampled palette delta: `28.6`

Current v139 objective diff metrics:

| Route/state | Changed px >8 | Mean abs diff | Max sampled palette delta | Blocking readout |
| --- | ---: | ---: | ---: | --- |
| Command Center first | 19.73% | 8.17 | 0.00 | first-viewport route identity, posture values, KPI model, and hero/right-rail rhythm differ |
| Command Center lower | 39.48% | 10.26 | 17.20 | lower trend, risk, catalog, CDE, activity, and palette regions differ |
| Discover first | 32.28% | 10.03 | 23.04 | search copy, result set, count/density, filters, and AI rail differ |
| Discover selected | 39.66% | 11.74 | 28.60 | selected entity, drawer data richness, tabs/actions, overlay geometry, and palette differ |
| Stewardship | 25.85% | 8.80 | 21.40 | work-item counts, queue rows, selected detail, and AI rail differ |
| Glossary | 31.73% | 7.91 | 0.00 | counts, terms, hierarchy strip, card density, and evidence blocks differ |
| CDE Registry | 25.70% | 6.70 | 0.00 | CDE names, source columns, status/recert rows, icon geometry, and table density differ |
| Lineage | 38.75% | 10.89 | 3.00 | hero chips, graph topology, node placement, inspector, footer, and impact content differ |
| Audit Evidence | 37.54% | 12.09 | 21.42 | KPI totals, event mix, selected evidence panel, and lower palette differ |
| Control Center | 33.66% | 7.70 | 7.07 | job set/statuses, integrations, policy coverage, and readiness panel model differ |

Fresh reviewer findings:

- Visual fidelity reviewer: BLOCKED for every route. v139 has `10/10` blocked
  pairs; no route is visually closed.
- Product structure reviewer: BLOCKED. Command Center, Discover selected, and Lineage
  remain structurally open; other routes are only structurally defensible with
  explicit live-data/availability deferrals and still lack visual signoff.
- Functional workflow reviewer: BLOCKED. v135 is useful current local-runtime
  evidence, but Lineage search/export/selection/status-only controls, Discover
  drawer-context controls/favorites/AI unavailable proof, Command Center trend
  rescoping, stewardship mutation contradiction, glossary/CDE creation/request
  controls, audit degraded export behavior, Control Center unavailable reasons,
  responsive control exercise, deployed proof, and performance telemetry remain open.
- Process reviewer: BLOCKED. v135-v140 evidence must be manifest-pinned; stale v88-v93
  and v94-v138 reports must be retired or allowlisted; the guard must reject audit
  manifests as closure and preserve them only as blocking process evidence.
- Truth/provenance reviewer: BLOCKED. Current evidence is local runtime only, audit
  CSV/JSON exports overclaim authority without enough runtime/deployment boundary,
  Discover selected-state copy exposes internal `Buildability Note`/workflow-evidence
  language, Lineage does not clearly separate native UC/system lineage from governed
  tag evidence and unavailable column-lineage proof, Command Center uses
  posture/risk labels for coverage-derived signals, and several unavailable/degraded
  states remain honest but non-closing until backed or explicitly deferred.

## 2026-05-03 Current Evidence Refresh - v100-v104

Status: current build evidence is refreshed and every visual route/state remains
blocked.

- Current wide all-route screenshots:
  `docs/northstar_visual_qa/live-runtime-current-v100-wide-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-96be2ef7c4c5`
  - `mockApi=false`
  - `evidenceKind=runtime_app_capture`
  - `captureCount=8`, `requestFailureCount=0`, `pageErrorCount=0`
- Current lower-scroll screenshots:
  `docs/northstar_visual_qa/live-runtime-current-v101-wide-scroll-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-96be2ef7c4c5`
  - `mockApi=false`
  - Command Center, Discover, Lineage, and Audit produced lower-scroll captures.
- Current Discover selected screenshot:
  `docs/northstar_visual_qa/live-runtime-current-v102-discover-selected-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-96be2ef7c4c5`
  - `mockApi=false`
  - selected state `discover-selected-3037x1269.png`
- Current responsive screenshots:
  `docs/northstar_visual_qa/live-runtime-current-v103-responsive-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-96be2ef7c4c5`
  - `mockApi=false`
  - viewports `1440x900`, `1280x720`
- Current side-by-side and palette audit:
  `docs/northstar_visual_qa/live-runtime-current-v104-reference-current-finance-shell-audit-2026-05-03/audit-artifact-manifest.json`
  - generated from v100/v101/v102 current screenshots
  - all 10 route/state pairs are `BLOCKED`
- Current all-route functional report:
  `docs/northstar_visual_qa/live-runtime-current-v99-full-functional-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-96be2ef7c4c5`
  - `mockApi=false`
  - `interactionCount=48`
  - no failed interactions in the local runtime report
  - not deployed Databricks App proof

Current objective diff metrics from v104:

| Route/state | Current screenshot | Changed px >8 | Mean abs diff | Max sampled palette delta | Blocking readout |
| --- | --- | ---: | ---: | ---: | --- |
| Command Center first | `v100/command-center-3037x1269.png` | 40.06% | 9.74 | 15.00 | hero rhythm, metric content, topbar, and lower canvas still differ |
| Command Center lower | `v101/command-center-3037x1269-main-bottom.png` | 61.37% | 12.91 | 21.40 | lower-state content and chart/catalog/activity rhythm still materially differ |
| Discover first | `v100/discover-3037x1269.png` | 32.79% | 10.26 | 23.04 | result list density, filter rail, AI panel, and lower canvas differ |
| Discover selected | `v102/discover-selected-3037x1269.png` | 39.63% | 10.74 | 28.60 | selected drawer state, overlay treatment, palette, and sticky actions differ |
| Stewardship | `v100/stewardship-3037x1269.png` | 26.68% | 8.84 | 21.40 | selected detail, counts, table density, and page positioning differ |
| Glossary | `v100/glossary-3037x1269.png` | 32.30% | 7.96 | 11.22 | hierarchy strip, term-card density, source/review blocks, and AI rail differ |
| CDE Registry | `v100/cde-registry-3037x1269.png` | 26.27% | 6.79 | 11.22 | CDE table rows, source-unavailable copy, iconography, and AI rail differ |
| Lineage | `v100/lineage-3037x1269.png` | 34.39% | 9.31 | 11.22 | graph topology, node count/placement, inspector, toolbar, and footer differ |
| Audit Evidence | `v100/audit-3037x1269.png` | 39.53% | 12.36 | 21.42 | metric totals, event rows, selected evidence region, and lower palette differ |
| Control Center | `v100/control-center-3037x1269.png` | 30.13% | 7.71 | 11.22 | readiness tables, integrations, policy coverage shape, and diagnostics copy differ |

Current v104 route-level gaps, materialized from the side-by-side review:

- Cross-page shared:
  - [ ] visual: topbar bar color remains lighter than the reference on every route
    (`topbar` sampled delta `11.22` on most pairs).
  - [ ] visual: active nav row geometry is close but the icon glyphs, label weight, and
    cyan emphasis still differ from the references route by route.
  - [ ] visual: the workspace breadcrumb says `emet.axiom` instead of
    `prod`; this is product-truthful but still a visible reference mismatch.
  - [ ] visual: the UC chip now uses backed runtime coverage (`95.5%`) rather than the
    reference `87.4%`; this is an intentional truth constraint but must be recorded as
    a visual deviation or the reference data must be backed to match it.
  - [ ] visual: Axiom AI panels use route-specific current copy and often remain open
    over content where the reference either shows a different prompt set or no rail in
    the first viewport.
  - [ ] functional: v99 proves local runtime interactions only. Current deployed
    Databricks browser proof for build `frontend-96be2ef7c4c5` is still missing.
  - [ ] performance: cold-start and first useful route paint still need deployed and
    local measurements; no current report proves the app avoids minute-scale initial
    load.
  - [ ] process: v100-v104 reports are not yet manifest-pinned or retired, so
    `scripts/check_northstar_audit_contract.py` correctly fails.

- Command Center:
  - [ ] visual: current hero is narrower and centered differently; the reference ring,
    narrative, KPI row, and right `What changed today` column are not reproduced.
  - [ ] visual: backed live values (`95.5%`, `50`, `45`, `4`) replace the reference
    demo values (`87.4%`, `1,247`, `612`, `184`, etc.); this is truth-correct but
    creates large visual and copy drift unless the development data plane is extended
    to back the reference shape.
  - [ ] visual: trend and domain cards use unavailable states and different chart
    density from the reference.
  - [ ] visual: lower scroll state starts at a different content offset and does not
    match `prototype_home2.png`.
  - [ ] truth/provenance: CDE, trend, quality, and lineage coverage cards still render
    unavailable in places where the reference has backed-looking values.

- Discover:
  - [ ] visual: the first viewport has a different search placeholder, result counts,
    sort label, list width, card height, and visible row cadence.
  - [ ] visual: the current result list uses representative live assets but not the
    reference asset ordering/content for `revenue_daily`, `customer_profile`, and
    related rows in the same positions.
  - [ ] visual: the current right AI panel is open and overlays/competes with the
    reference side panel rhythm.
  - [ ] visual: selected preview is a right drawer over a blurred page, while the
    reference selected state is a larger asset detail surface with different header,
    metadata grid, tabs, sticky action footer, and tag/buildability blocks.
  - [ ] functional: Saved searches, Advanced filters, list/grid controls, drawer tabs,
    disabled comment/request access, and certification actions require deployed proof
    or precise unavailable-state decisions.

- Stewardship:
  - [ ] visual: current count is `4 open work items` with SLA unavailable; reference is
    `184 open work items · 7 SLA breaches`.
  - [ ] visual: table rows use safe `GOV-*` request IDs and long Databricks FQNs, while
    the reference uses compact `SI-*` rows and shorter asset names.
  - [ ] visual: selected detail is present but its trigger/source/implementation
    content, suggested actions, and button treatment differ from the reference.
  - [ ] functional: `Comment`, `Resolve`, bulk assign, filter, and new work item need
    deployed/current mutation or disabled proof tied to backed audit events.

- Glossary:
  - [ ] visual: hierarchy strip and term-card layout differ from the reference's two-up
    glossary cards.
  - [ ] visual: current source/association/review blocks are denser and lower than the
    reference card contents.
  - [ ] truth/provenance: term hierarchy and reviewer/version history are represented
    from current registry data but still lack full reviewer workflow proof.
  - [ ] functional: `New term`, term selection, preview lineage, tab switch, and AI
    prompts need deployed/current evidence or truthful unavailable states.

- CDE Registry:
  - [ ] visual: current rows render source columns as unavailable, while reference rows
    show concrete source-of-record column names and healthy/recert states.
  - [ ] visual: row icon geometry differs from the reference small linked-key glyphs.
  - [ ] truth/provenance: source columns and recertification state must be backed by
    Unity Catalog/governance-store data or remain honestly unavailable; visual parity
    cannot be closed by fake source columns.
  - [ ] functional: CDE row selection, recertification, owner, source asset navigation,
    and CDE-tab workflows need deployed/current proof.

- Lineage Atlas:
  - [ ] visual: graph topology is not the reference topology; node count, node
    positions, edge curves, arrowheads, downstream continuation, and canvas scrollbars
    differ materially.
  - [ ] visual: current header chips, toolbar, graph footer, node cards, column rows,
    and right inspector density differ from `prototype_lineage.png`.
  - [ ] truth/provenance: current live graph is restricted to backed UC/system lineage
    edges; missing reference nodes cannot be filled with fake lineage.
  - [x] functional: local runtime graph drag/pan now works in v99, interaction
    `lineage-controls`; this does not close deployed proof or remaining graph controls.
  - [ ] functional: edge selection, keyboard graph navigation, export content,
    search/no-results/clear, fit/reset, column-row selection, run impact, and selected
    node workflows still require deployed/current proof.

- Audit Evidence:
  - [ ] visual: metric card values and labels now use live evidence (`48`, `1`, `0`,
    unavailable retention) rather than the reference (`2,184`, `6`, `3`, `7 yr`),
    causing large first-viewport differences.
  - [ ] visual: event table rows now show safe evidence IDs and live recent events; row
    ordering, wrapping, target truncation, and selected-evidence panel differ from the
    reference.
  - [ ] functional: date range, all/by-user/by-service/violations filters, report
    generation, CSV export, open asset, and copy evidence ID need deployed proof for
    current build.

- Control Center:
  - [ ] visual: reference shows concrete backed jobs, integrations, model serving,
    Slack/PagerDuty, and policy coverage bars; current renders unavailable diagnostics
    for several rows and therefore has a different structure.
  - [ ] truth/provenance: unavailable diagnostics are correct when no backed data
    exists, but representative jobs/integrations/policy coverage must be created in
    the real development workspace before this page can visually match without fake
    values.
  - [ ] functional: scheduled-job rows, integration rows, policy coverage rows, and
    linked-resource actions need deployed/current proof or disabled unavailable
    states.

## 2026-05-03 Current Evidence Refresh

- Current runtime all-route screenshot capture:
  `docs/northstar_visual_qa/live-runtime-current-v88-all-routes-finance-shell-2026-05-03/prototype-current-report.json`
  - build `frontend-a9fae05546f7`
  - `mockApi=false`
  - `evidenceKind=runtime_app_capture`
  - `liveDatabricksCapture=false`
  - `forwardedActorCapture=true`
  - `captureCount=8`, `expectedCaptureCount=8`, `requestFailureCount=0`
- Current wide screenshot capture:
  `docs/northstar_visual_qa/live-runtime-current-v89-wide-finance-shell-2026-05-03/prototype-current-report.json`
- Current lower-scroll capture:
  `docs/northstar_visual_qa/live-runtime-current-v90-wide-scroll-finance-shell-2026-05-03/prototype-current-report.json`
- Current Discover selected-state capture:
  `docs/northstar_visual_qa/live-runtime-current-v92-wide-discover-selected-finance-shell-2026-05-03/prototype-current-report.json`
- Current Lineage functional control evidence:
  `docs/northstar_visual_qa/live-runtime-current-v132-focused-functional-command-lineage-control-2026-05-03/prototype-current-report.json`
  - `graphPanAfter={"x":48,"y":22}` from a realistic drag
  - zoom, wheel zoom, fit, column lineage, impact analysis, refocus, and as-of controls exercised in this local runtime report
- Current side-by-side audit artifacts:
  `docs/northstar_visual_qa/live-runtime-current-v93-reference-current-finance-shell-audit-2026-05-03/audit-artifact-manifest.json`

Current objective diff metrics from v93 remain blocking:

| Route/state | Changed px >8 | Mean abs diff | Max sampled palette delta | Blocking readout |
| --- | ---: | ---: | ---: | --- |
| Command Center first | 16.49% | 9.73 | 11.58 | main lower/topbar palette and first-viewport rhythm still drift |
| Command Center lower | 34.47% | 12.78 | 23.69 | lower scroll state remains materially different |
| Discover first | 29.12% | 10.23 | 12.37 | result density, frame, and main canvas still drift |
| Discover selected | 28.26% | 10.67 | 34.44 | selected drawer/right rail palette remains far off |
| Stewardship | 18.98% | 9.09 | 12.41 | content frame and main panel treatment still differ |
| CDE Registry | 18.19% | 6.71 | 10.44 | table density/iconography and topbar palette still differ |
| Glossary | 21.12% | 7.90 | 10.44 | card density and topbar/right rail still differ |
| Lineage | 25.15% | 10.10 | 8.19 | graph topology, node density, inspector, and footer still differ |
| Audit Evidence | 31.72% | 11.90 | 17.83 | event table, metrics, and lower palette still differ |
| Control Center | 20.56% | 7.70 | 17.49 | rail/main palette and readiness panels still differ |

Performance evidence from the current local runtime:

- Cold `/api/axiom/command-center`: `0.026s`, returns honest loading/degraded envelope.
- Cold `/api/bootstrap?surface=home`: `0.002s`, shell bootstrap returns immediately.
- Cold `/api/assets/finance_prod.curated.revenue_daily?sections=header`: `4.019s`, now uses `headerSource=direct-unity-catalog-identity` with real UC tags and governance-store owners/requests; this is improved from the previous full-inventory block but remains open for more tightening.
- Warm `/api/discovery/search?limit=100`: `0.010s`, `50` assets, minimum coverage `100`, no assets below `100`.
- Warm `/api/assets/finance_prod.curated.revenue_daily?sections=header`: `0.002s`, `headerSource=visible-unity-catalog-inventory`.
- Command Center after visible inventory cache: `1.770s`, `50` visible assets, `7` catalogs, `5` open requests, `100.0` coverage; still workspace-app-principal degraded, not actor-authoritative proof.

## Evidence Compared

- Reference screenshots:
  - `northstar/screenshots/prototype_home1.png`
  - `northstar/screenshots/prototype_home2.png`
  - `northstar/screenshots/prototype_discover1.png`
  - `northstar/screenshots/prototype_discover2.png`
  - `northstar/screenshots/prototype_stewardship1.png`
  - `northstar/screenshots/prototype_stewardship2.png`
  - `northstar/screenshots/prototype_glossary1.png`
  - `northstar/screenshots/prototype_lineage.png`
  - `northstar/screenshots/prototype_audit1.png`
  - `northstar/screenshots/prototype_cc.png`
- Historical non-closing screenshots: `docs/northstar_visual_qa/all-routes-shared-layout-v415-local/`
- Current screenshots:
  - `docs/northstar_visual_qa/live-runtime-current-v88-all-routes-finance-shell-2026-05-03/`
  - `docs/northstar_visual_qa/live-runtime-current-v89-wide-finance-shell-2026-05-03/`
  - `docs/northstar_visual_qa/live-runtime-current-v90-wide-scroll-finance-shell-2026-05-03/`
  - `docs/northstar_visual_qa/live-runtime-current-v92-wide-discover-selected-finance-shell-2026-05-03/`
- Fresh side-by-side audit artifacts:
  - `docs/northstar_visual_qa/live-runtime-current-v93-reference-current-finance-shell-audit-2026-05-03/audit-artifact-manifest.json`
  - `docs/northstar_visual_qa/live-runtime-current-v93-reference-current-finance-shell-audit-2026-05-03/*-reference-current.png`
  - `docs/northstar_visual_qa/live-runtime-current-v93-reference-current-finance-shell-audit-2026-05-03/*-diff-common-crop.png`

## Objective Findings

- Lineage reference/current dimensions differ: reference is `2933x1249`; current is
  `3037x1269`, so the old nearest-viewport comparison was never exact.
- The v415 current report is `prototype_mock`, `mockApi=true`, and has
  `interactionCount=0`.
- Current side-by-side and diff artifacts show differences across the full common
  crop, not localized defects.
- Average sampled main/right-region colors still drift by page. Examples:
  - Discover main region reference `rgb(15, 34, 55)`, current `rgb(14, 39, 63)`.
  - Glossary main region reference `rgb(11, 29, 49)`, current `rgb(11, 36, 58)`.
  - Control Center main region reference `rgb(13, 33, 54)`, current `rgb(12, 41, 64)`.
  - Audit main region reference `rgb(15, 35, 57)`, current `rgb(12, 42, 63)`.

## Cross-Page Shared Gaps

- [ ] process: v415 has no loading-state screenshots, so shared loading-state
  structure, palette, overlays, and topbar behavior remain unreviewed.
- [ ] process: degraded-state screenshots exist only for Discover and Audit. Command
  Center, Stewardship, Glossary, CDE Registry, Lineage, and Control Center degraded
  states remain unmapped.
- [ ] visual: shared topbar UC chip differs on every route. Reference shows
  `UC connected · 87.4% coverage`; current runtime evidence shows workspace-scoped
  Databricks state and `100%` representative coverage. This is truthful but still a
  visible copy/metric mismatch against the reference.
- [x] truth/provenance: visible mock/local/prototype chip copy is no longer rendered in
  the current runtime screenshots. Closure evidence:
  `docs/northstar_visual_qa/live-runtime-current-v88-all-routes-finance-shell-2026-05-03/prototype-current-report.json`,
  build `frontend-a9fae05546f7`, `mockApi=false`, plus production-surface grep showing
  no `Prototype mock`, `Prototype fixture`, `prototype_mock`, or `local-prototype-mock`
  strings outside tests, capture/reference tooling, and non-authoritative evidence
  detectors. This does not close visual parity or deployed/live proof.
- [ ] visual: Discover, Stewardship, Glossary, CDE Registry, Audit, and Control Center
  content frames are wider and more left-shifted than the references.
- [ ] visual: route AI panels use route-specific prototype copy/prompts instead of the
  shared reference prompt set.
- [ ] visual: Lineage lacks the reference bottom-right AI launcher in the first viewport.
- [ ] visual: responsive FAB states can overlap lower-right actions, including Discover
  selected-state `Review cert` at `1280x720`.
- [ ] process: full-page and lower-scroll screenshots are not consistently mapped to
  the corresponding reference state by route.
- [ ] functional: local prototype functional evidence has been used to close route
  controls that need current live/runtime proof or truthful disabled states.

## Command Center Gaps

- [ ] visual: header/topbar copy diverges from `prototype_home1.png` through
  prototype/non-live text and the changed UC status treatment.
- [ ] visual: page main region is brighter/bluer than the reference sample.
- [ ] visual: lower-scroll capture does not align to `prototype_home2.png`; the current
  lower capture begins with the coverage chart title clipped under the topbar.
- [ ] visual: lower-scroll content frame is substantially wider/left-shifted than the
  reference, changing chart, risk, catalog, CDE, and activity rhythm.
- [ ] visual: lower AI rail copy and prompt set differ from the reference Axiom AI panel.
- [ ] functional: export fallback must show visible failure feedback if browser blob
  export support is unavailable.
- [ ] functional: current Command Center evidence is local prototype evidence and does
  not prove current deployed/live controls.

## Discover Gaps

- [ ] process: `prototype_discover2.png` is a selected-preview state, but the manifest
  must explicitly map it to `discover-selected-{viewport}.png`.
- [ ] visual: `discover-3037x1269.png` is left-shifted and wider than
  `prototype_discover1.png`; filter rail and results no longer sit in the same centered
  frame.
- [ ] visual: page subcopy uses prototype-fixture wording instead of the reference
  permission-aware/trust-signal wording.
- [ ] visual: result cards are taller/brighter and the final visible row clips at the
  first viewport bottom.
- [ ] visual: AI panel copy and prompts differ from the reference.
- [ ] visual: `discover-selected-3037x1269.png` has an open AI panel inside the drawer,
  obscuring Tags/Glossary and Buildability regions.
- [ ] visual: selected drawer header, metadata density, tab spacing, and sticky actions
  differ from `prototype_discover2.png`.
- [ ] visual: selected drawer adds `Review cert` and extra prototype-connected-assets
  content not present in the reference.
- [ ] visual: Discover degraded state introduces a large pale banner/card that breaks
  the dark palette and row-list rhythm.
- [ ] functional: Saved searches are local/hardcoded rather than persisted or clearly
  unavailable.
- [ ] functional: Recommended Assets `View all` selects a recommendation instead of
  opening a complete recommendations view.
- [ ] functional: selected-preview and lineage warm-up latency need measured evidence
  from click to useful state.

## Stewardship Gaps

- [ ] visual: page content is left-shifted and wider than `prototype_stewardship1.png`.
- [ ] visual: header subcopy uses prototype/non-live wording instead of the reference
  workbench description.
- [ ] visual: selected work-item detail adds trigger/source/observed grid content not
  present in the reference.
- [ ] visual: work-item hierarchy and density differ in the selected side panel.
- [ ] visual: table columns truncate at `1440x900` and `1280x720`, especially asset names
  and assigned owner cells.
- [ ] functional: governance mutation controls need disposable live proof or disabled
  unavailable states; current live QA skips mutation clicks.

## Glossary Gaps

- [ ] visual: page content is left-shifted and wider than `prototype_glossary1.png`.
- [ ] visual: current adds a hierarchy strip and `4 visible terms` count not present in
  the reference screenshot.
- [ ] visual: glossary cards are taller and include Source/Associations/Review blocks,
  while the reference uses compact term cards with assets and lineage links.
- [ ] visual: AI panel copy/prompts differ from the reference.
- [ ] functional: `TaxonomyWorkspace` is forced into prototype behavior, so reviewer,
  hierarchy, version, and association workflows cannot be treated as backed live
  workflows.

## CDE Registry Gaps

- [ ] visual: page content is left-shifted and wider than `prototype_stewardship2.png`.
- [ ] visual: CDE table copy differs: current uses `Future`/`Fixture` recert/status
  treatments where the reference uses compact `90d`, `180d`, `Healthy`, and `Recert due`.
- [ ] visual: CDE iconography differs from the reference small key/link glyphs.
- [ ] process: `cde-registry-cde-detail-state-*` has no explicit screenshot-reference
  mapping and must be tracked as a separate selected-detail state if reviewed.
- [ ] visual: at `1280x720`, CDE Registry changes from table structure to stacked cards
  without a recorded responsive reference or deferral.
- [ ] functional: CDE owner/recertification workflows require live proof or truthful
  disabled unavailable states.

## Lineage Gaps

- [ ] visual: current first viewport is vertically compressed versus
  `prototype_lineage.png`; lower Impact/Column panels begin too early.
- [ ] visual: current and reference screenshots are not the same dimensions.
- [ ] visual: graph topology differs in node positions, graph scale, edge curves,
  arrowhead landings, glow, and convergence around notebook/downstream paths.
- [ ] visual: downstream boundary card is visible as `4 downstream assets` with
  prototype permission copy; the reference has a subtler continuation shape.
- [ ] visual: header action buttons sit differently against the right edge.
- [ ] visual: header chip styling is flatter/smaller than the reference icon-chip
  treatment.
- [ ] visual: current graph canvas and right inspector palette still differ from sampled
  reference regions.
- [ ] visual: canvas toolbar is shorter and more cramped than the reference toolbar.
- [ ] visual: reference graph scroll affordances are not reproduced in the same form.
- [ ] visual: hop/depth controls and visible topology-depth scaffolding do not match
  the reference graph operating model.
- [ ] visual: left source cards crop/truncate differently from the reference.
- [ ] visual: node cards differ in title baselines, icon boxes, footer spacing, row
  density, and schema truncation.
- [ ] visual: current inspector includes prototype/non-live proof copy absent from the
  reference.
- [ ] visual: inspector stats differ: `11 min ago` wrapping/dot treatment and row/owner
  density do not match.
- [ ] visual: source/consumer/activity rows differ in wrapping, separators, dots, and
  copy spacing.
- [ ] visual: node-type strip adds `Prototype topology shape; system.access.table_lineage
  not verified`; reference is quieter and says `via system.access.table_lineage`.
- [ ] visual: `LINEAGE AS OF` strip differs: current says `Prototype fixture`,
  `not live`, and `Reset preview`; reference says `Today`, `live`, and `Now`.
- [ ] visual: at `1536x1024` and `1440x900`, graph content is cropped/truncated.
- [ ] visual: at `1280x720`, toolbar, graph cards, and inspector crowd the first
  viewport and text becomes hard to use.
- [x] functional: custom North Star graph canvas did not support drag/pan. Closure
  evidence:
  `docs/northstar_visual_qa/live-runtime-current-v132-focused-functional-command-lineage-control-2026-05-03/prototype-current-report.json`,
  interaction `lineage-controls`, build `frontend-33133f44f929`, `mockApi=false`,
  `graphPanAfter={"x":48,"y":22}` and visible pan status. This closes only the
  drag/pan behavior row; Lineage visual and remaining control rows stay open.
- [ ] functional: `Now`/as-of action changes status text only unless wired to a backed
  refresh/time-selection workflow or disabled.
- [ ] functional: Search toggle announces opened even when closing and needs full
  open/search/clear/no-results/live-backed coverage.
- [ ] functional: Lineage export, graph search, pan/drag, zoom, reset, selected-node,
  restricted-boundary, notify-owner, and column-row workflows need current live/runtime
  evidence or explicit unavailable states.
- [ ] functional: Lineage edge selection, edge-detail affordances, and keyboard graph
  navigation have no current control-level evidence.

## Audit Evidence Gaps

- [ ] visual: page content is left-shifted and wider than `prototype_audit1.png`.
- [ ] visual: metric cards and event table have different column proportions; target
  and evidence cells wrap differently.
- [ ] visual: current Evidence cells include repeated `Prototype fixture` subtext not
  visible in the reference table.
- [ ] visual: Audit degraded state has no reference screenshot; current unavailable
  metrics and large empty table panel alter first-viewport rhythm.
- [ ] functional: date-range evidence must prove backed query scope changes, not only
  local labels and download names.

## Control Center Gaps

- [ ] visual: page content is left-shifted and wider than `prototype_cc.png`.
- [ ] visual: header subcopy uses prototype diagnostic/non-live wording instead of the
  reference runtime/configuration copy.
- [ ] visual: Scheduled Jobs status chips all read as fixture-style rows with chevrons;
  reference uses `Healthy`/`Slow` readiness treatments.
- [ ] visual: Integrations panel changes `OK` connection chips to fixture chips and adds
  row chevrons, changing the control/readiness model.
- [ ] visual: Policy coverage panel is lower and denser than the reference because the
  upper grid dimensions changed.
- [ ] functional: row actions can end in local status text instead of opening a real
  resource or disabled unavailable detail.

## Mock And Fixture Removal Gaps

- [ ] truth/provenance: `frontend/scripts/axiom_prototype_current_capture.mjs` intercepts
  app APIs and serves prototype payloads; it must not be a closure path for product rows.
- [ ] truth/provenance: `northstar/data/mock.js` remains a reference/prototype data
  source and must not feed customer-facing runtime behavior.
- [x] truth/provenance: production frontend files render `prototype_mock`, `Prototype
  mock`, `Prototype fixture`, and `local-prototype-mock` copy in multiple app surfaces.
  Closure evidence: current runtime v88 screenshots render no such visible product
  copy, and `rg` over `frontend/src`, `runtime_app.py`, `axiom`, `app.yaml`,
  `databricks.yml`, and `scripts` found the remaining tokens only in tests,
  non-authoritative evidence detection, capture/reference tooling, audit guards, or
  backend validation constants rather than customer-facing runtime copy.
- [ ] truth/provenance: `TaxonomyWorkspace` has forced prototype behavior and must be
  converted to live/backed glossary and CDE workflows or truthful unavailable states.
- [ ] truth/provenance: a representative enterprise development workspace must be built
  from real UC tables/jobs/pipelines/quality runs/permissions/lineage-producing flows
  rather than UI mock values.
- [ ] process: `full_page_audit.md`, `functional_control_audit.md`, and
  `signoff_matrix.md` still preserve historical zero-open or closure language that
  can mislead reviewers unless every active summary row is visibly reopened.
- [ ] process: future visual, truth, functional, and reviewer matrix closure must name
  one current build/deployment evidence epoch instead of mixing local and deployed
  artifacts from different builds.
- [ ] process: every route needs explicit mappings for first viewport, lower scroll,
  responsive, selected/detail, loading, and degraded states before those states can be
  reviewed or deferred.
- [ ] process: Lineage visual, functional, truth/provenance, and reviewer evidence may
  not mix epochs unless an audit row explicitly records the mismatch and rationale.

## How The Previous Review Missed This

- Reviewers accepted a zero-open-row ledger while `lineage_reopened_visual_audit.md`
  still said reopened and blocking.
- The guard validated bookkeeping, path existence, hashes, and metadata pins rather
  than visual equivalence or interaction semantics.
- The signoff matrix turned checked rows into reviewer unanimity, even though many
  rows cited a single screenshot or stale/local evidence.
- Current visual evidence was local `prototype_mock` with `mockApi=true`; this was
  treated as closure-quality evidence instead of comparison-only evidence.
- Evidence epochs were mixed: local v415 screenshots, old local functional reports,
  old live route reports, and newer truth reports were all allowed to support the same
  current state.
- Functional validation checked interaction names more than current-build, route-scoped,
  backed/degraded/unavailable outcomes.
- Process rows could cite the same ledger/status artifacts they were supposed to audit.
- Palette drift was not sampled or thresholded.
- Responsive text clipping and missing loading/degraded states were treated as secondary
  rather than blocking.
- The review did not force each page to re-open after a material miss was found on one
  page.

## Required Next Gates

- Replace or demote mock/local evidence pins so they cannot close product readiness
  rows.
- Add a single current evidence epoch across visual, truth, functional, and matrix
  rows.
- Capture current live/runtime screenshots for every mapped route/state, including
  loading and degraded states.
- Capture control-level functional evidence for every visible control, with route,
  viewport, build/deployment, interaction, outcome, backing kind, and artifact path.
- Create or refresh representative enterprise UC data, jobs, pipelines, quality runs,
  permissions, glossary/CDE state, audit events, and lineage-producing workflows.
- Iterate page by page until the open rows above are either closed by current evidence
  or explicitly deferred with rationale.
