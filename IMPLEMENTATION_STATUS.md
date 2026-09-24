# Implementation Status

Last updated: 2026-09-24 during the AI governance extension Phase 1 build on `feat/ai-governance-extension`.

## Checkpoint - 2026-09-24 AI Governance Extension, Phases 0 and 1 (NOT signed off)

Scope: `docs/ai_extension/DESIGN.md` (v0.2, verified against databricks-sdk
0.95), with Phase 0 evidence in `docs/ai_extension/PHASE0_FINDINGS.md` and
operations in `docs/ai_extension/RUNBOOK.md`. Everything sits behind
`ai_features_enabled` (default `false`).

Built:
- Config and flag. `/api/ai` registers only when the flag is on; bootstrap
  exposes `shell.aiGovernance.enabled`.
- Migrations 19 to 22: observations, intake plus history, runs plus findings,
  and control results. 23 and 24 are reserved.
- `atlas/ai`:
  - models, allowlist redaction, and never-raise probes;
  - `AiStore`, which audits before mutating and goes through the store wrapper
    so writes reach the Lakebase mirror;
  - the Databricks collector;
  - intake CSV with the YAML field map;
  - reconciliation (M1 to M3, five finding rules);
  - controls AIC-01, 03, 04, 06 and 09;
  - job entry points, sample scenario, and stress scenarios.
- Bundle job `atlas-ai-collect-and-reconcile`: two serverless tasks, paused
  schedule, `run_as` the collector SP in staging/prod.
- `/api/ai` routes: summary, inventory, asset, controls, findings,
  finding actions, confirm-match, intake, import, and runs.
- `/ai` frontend surface: Inventory, Findings, Intake, and AI Asset 360.
  The rail, route and command palette are gated by the flag.
- Dev seed of real, labeled sample objects (decision D1), plus `--cleanup`.

Validation evidence:
- Backend: 849 unittest OK (up from 742 at baseline).
- Frontend: 724 vitest OK (up from 706). Typecheck is clean, check-css passes,
  and the build succeeds.
- Live stress, `run_synthetic_stress_validation.py --scenario ai` in
  run-scoped schema `atlas_ga_stress_20260924175926_dc3ccfe4`: 9 of 9 checks
  pass. Audit and event rows pair 53 to 53, with 0 organic leaks and 0
  leftovers. An earlier run caught sample control results stored as organic;
  that is fixed.
- Dev app `atlas-alex` is deployed with the flag on. The job ran live:
  - `dbx-879840517064763`: 99 findings opened.
  - `dbx-835023281092064`: 99 unchanged, 99 distinct IDs, `last_seen`
    advanced, 0 registry writes.
  - `dbx-94212139478758`: 99 unchanged.
  - Observed: 85 endpoints, 8 agents, 3 external models, 4 MCP servers,
    1 tool, and 1 model in `main`.
  - The sample scenario produced exactly its five intended findings.
- The live runs corrected Phase 0: models must be listed per schema, and UC
  function tags are unobservable. Serverless IPython exit and `__file__`
  handling, and duplicate observations on task retry, were also fixed.

Branch review fixes (after the checkpoint above, not yet redeployed):
- Finding state guard: closed findings only reopen, and active ones can't
  reopen. confirm-match returns 409 unless the finding is open or
  acknowledged. The drawer offers only Reopen on closed findings.
- M1 intake-tag aliases are now audited (`ai.registry.alias_upserted`).
  Stale `declares` links are superseded unless they are steward overrides or
  their source kind was blind this run.
- Registered-but-not-found now skips intakes previously linked to a kind
  whose source was blind, and its evidence names the sources not searched.
  Intake link status reads open RNF findings directly.
- Redaction catches keys embedded anywhere in a value and strips userinfo
  from connection hosts. Endpoint tags are scrubbed.
- The model listing cap degrades the source instead of truncating silently.
- `query_df` follows statement result chunks, so large reads are no longer
  cut at the first chunk.
- Readers get `findings: null` (not `[]`) on Asset 360, and the UI says
  findings are steward-visible instead of "none".
- The UI shows "Showing X of N" when results are truncated, and a notice
  when a deep-linked finding is filtered out. The import drawer resets on
  close, and file read errors surface.
- Sample purge deletes the Lakebase mirror rows too.
- Backend 859 unittest OK. Frontend 727 vitest OK, and the build succeeds.

Remaining before sign-off:
- Redeploy `atlas-alex` and re-run the job with the review fixes.
- The `CLAUDE.md` browser walk-through and independent subagent sign-off have
  **not** run. They need an authenticated Chrome session on CDP `:9223`.
  - The walk-through covers inventory, Asset 360, the findings confirm,
    suppress and resolve actions with job re-runs, the intake dry run and
    commit, and the Evidence page.
- The Lakebase mirror is inactive inside the job (`RuntimeError`), so AI
  registry rows written by the job are Delta-only. App reads use Delta.
- Finding assignment does not create tasks: `create_workflow_request` models
  asset change requests.
- The run `dbx-104603715079527` has two rows from a pre-fix task retry. Both
  are marked failed.


## Checkpoint - 2026-07-20 Full Audit Remediation

An 8-dimension independent audit (repo + live Databricks app) plus a personal
live sweep drove a remediation batch on branch
`fix/command-center-stale-while-revalidate`. Note: the audit found the older
`northstar_gap_analysis` ledgers below are heavily stale (~85% of sampled open
rows already fixed in current code); treat them as historical, not current.

Fixed and validated (442 backend pytest, 486 frontend vitest, clean build):
- **P0** Dashboard caches (command-center/taxonomy/audit/control-center) flipped
  available→loading→available on every TTL lapse; now stale-while-revalidate.
- **P0** Same endpoints could stick in `loading` forever when a warm loader ran
  slower than its TTL; TTL entries are now stamped at loader completion.
- **P0/security** Live-metadata + assets caches were keyed only by warehouse,
  leaking per-user OBO Unity Catalog reads (sample rows, columns, lineage)
  across users; now partitioned by acting credentials.
- **P1** SQL identifier escaping in `uc.get_information_schema_table_metadata`
  and every `quality_runner` built-in evaluator; context-aware PermissionDenied
  handler (no false "write access" copy on reads, config suffix stripped);
  job-inventory scope error degrades instead of killing control-center.
- **P1** Lineage v2: FQN-keyed canvas accumulation (in-canvas click now expands
  instead of resetting), hydrating live-lineage payload renders instead of
  showing "No lineage edges", stable `refresh` closure (no relayout storm).
- **P1/UX** Dark-brand preboot splash (was the old light/cream shell on every
  load), favicon, legible ga-token tone chips, resilient error boundary (a stray
  global reject no longer replaces the app), removed fabricated Command Center
  narrative constants, de-creamed the load-order-fragile masked `!important` CSS.
- **Build/tests** Restored portable `app.yaml` (dev values baked only into the
  packaged bundle), FastAPI 0.139 route introspection, regenerated OpenAPI
  snapshot, 400 (not 503) for malformed FQNs, removed orphan workspaces/hooks/CSS.

## Current Authoritative State - Reopened And Blocking

- All prior `northstar/*` visual, functional, truth/provenance, and process signoffs are superseded by the 2026-05-02 reopened audit.
- The active source of truth is now `docs/northstar_gap_analysis/full_page_audit.md` and currently has `90` open gaps: Command Center `7`, Discover `12`, Stewardship `6`, Glossary `5`, CDE Registry `6`, Lineage Atlas `24`, Audit Evidence `5`, Control Center `6`, Mock And Fixture Removal `9`, and Cross-Page Shared `10`.
- The active control-level source of truth is reopened and currently has `16` open controls: Command Center `2`, Discover `3`, Stewardship `1`, Glossary `1`, CDE Registry `1`, Lineage Atlas `5`, Audit Evidence `1`, Control Center `1`, and Cross-Page Shared `1`. The previous `0` open controls in `docs/northstar_gap_analysis/functional_control_audit.md` is invalid until each visible control has current live/runtime evidence with `mockApi=false` or a truthful disabled/unavailable outcome recorded in the reopened audit.
- `docs/northstar_gap_analysis/signoff_matrix.md` is reopened and all route/role verdicts are now `BLOCKED`.
- No page is signed off.
- Latest provenance rule: explicit mock/prototype/fixture/local-evidence markers and
  bare authority-false evidence fail closed before customer-facing render paths. Real
  Databricks degraded envelopes may render only as degraded/provisional state when
  they carry trusted live-source provenance and a degraded/unavailable/error state.
- Active all-route current screenshot capture-health evidence is `docs/northstar_visual_qa/live-runtime-current-v221-all-viewports-datapact-test-2026-05-04/prototype-current-report.json` for build `frontend-39d0070a8f87`. It is local runtime evidence with `mockApi=false`, `captureCount=32`, and `liveDatabricksCapture=false`; it is not visual parity, deployed browser proof, or live Databricks App proof.
- Active side-by-side/palette blocker evidence is `docs/northstar_visual_qa/live-runtime-current-v220-reference-current-datapact-test-audit-2026-05-04/audit-artifact-manifest.json`. It records `10` route/state pairs and `10` blocked pairs; max changed-pixel percentage above threshold `8` is `39.74`, and max sampled palette delta is `28.6`.
- Active functional-control evidence is local-runtime only: `docs/northstar_visual_qa/live-runtime-current-v215-full-functional-datapact-test-2026-05-04/prototype-current-report.json`. It has `mockApi=false`, `interactionCount=48`, and only the expected invalid structured-search `400` checks. Local runtime performance evidence is `docs/northstar_visual_qa/live-runtime-current-v216-performance-datapact-test-2026-05-04/performance-report.json` with `budgetPassed=true`. These reports do not close deployed proof, visual parity, or remaining open control rows.
- Older v415/v416/v419 and v88-v93 artifacts are historical comparison, truth, or prior-build evidence only unless a specific open row explicitly cites them as historical context. They are not the active current epoch and cannot close product-readiness rows for this tranche.
- The failed stricter MIP downstream probe at `docs/northstar_visual_qa/lineage-truth-v418-databricks/lineage-truth-report.json` and the earlier failed v400 probe are not closure evidence. The closed restricted-downstream row uses `main.mdm_schema.mdm_manual_overrides` in the passing v419 report.
- Capture reports prove route/capture health only. They do not by themselves prove visual parity, functional completion, live Databricks truth, or reviewer signoff.
- Mock API screenshots are local prototype evidence only. They must be labeled non-authoritative and cannot be used as live Databricks evidence.
- `.claude/skills/*` is available through symlinks to Databricks skill packs. Agents and reviewers must resolve those paths with `find -L .claude/skills` or equivalent before making skill-availability claims.
- A future audit row may be checked only when it carries current evidence metadata and the guard accepts that metadata; if any row reopens, this section must return to the reopened-blocking state before any further signoff wording is allowed.

## Superseded Historical Checkpoints - Do Not Use As Current State

The entries below this line are retained only as historical audit trail. Their
counts, signoff language, validation claims, and remaining-risk statements are
superseded by the current authoritative state above unless a future entry
explicitly revalidates them against the active ledgers and current evidence.

### Checkpoint - Backend Mutation And Live Validation Gate Started

- Trigger:
  - Only `2` functional-control rows remain open, both cross-page: auditable mutation proof and deployed/live Databricks validation.
  - Existing subagent reviewers remain blocking on live-proof grounds; a new reviewer spawn was attempted but the thread is at the agent limit, so the active reviewer findings are being used.
- Planned validation:
  - Run focused backend tests for fail-closed write auditing, request IDs, text sanitization, API error contracts, and synthetic stress workflow contracts.
  - Run the run-scoped synthetic Databricks stress validator in live mode with `DEFAULT` and the dev SQL warehouse to prove synthetic workflow mutation/audit/Lakebase/Genie paths without leaking into organic evidence.
  - Run Databricks bundle validation and `bundle summary` with `DEFAULT`.
  - Deploy the current app snapshot if validation passes, then run live route/API and browser interaction validation without `GOVAT_PROTOTYPE_MOCK_API`.
- Current blockers:
  - No live validation from this tranche has run yet.
  - `267` visual/page/shared gaps remain open in `full_page_audit.md`; no visual signoff is available.

### Checkpoint - Focused Backend Mutation/Audit Tests Passed

- Validation:
  - `./.venv/bin/python -m pytest -q tests/test_backend_write_audit_contracts.py tests/test_synthetic_stress_contract.py tests/test_api_error_contracts.py tests/test_api_text_sanitization.py tests/test_metadata_audit.py` -> passed, `35` tests.
- Coverage:
  - Fail-closed write auditing for custom properties.
  - Request-ID propagation into owner/profile/quality/export writes.
  - Open-asset authorization before read/write store access.
  - Text sanitization and structured API error contracts.
  - Synthetic stress plan safety for run-scoped mutation/audit/Lakebase/Genie workflows.
- Current blockers:
  - Live Databricks synthetic mutation proof has not run yet.
  - Databricks bundle validation, deploy, and live route/browser validation have not run yet.

### Checkpoint - Live Synthetic Stress Mutation Run Started

- Scope:
  - Execute `scripts/run_synthetic_stress_validation.py` in live mode against the `DEFAULT` profile and dev SQL warehouse `da02d15a9490650b`.
  - Use the run-scoped schema prefix `atlas_ga_stress`; the script marks all rows app-owned/test-scoped/cleanup-safe/excluded-from-organic-evidence and drops the run schema after validation.
- Preconditions:
  - `databricks current-user me --profile DEFAULT` succeeded for `skyler@entrada.ai`.
  - `databricks warehouses get da02d15a9490650b --profile DEFAULT` succeeded; warehouse `cotality_dais` is `RUNNING` and `HEALTHY`.
- Current blockers:
  - Live stress execution is in progress next; results will be recorded before the deploy gate.

### Checkpoint - Live Synthetic Stress Mutation Run Passed

- Validation:
  - `./.venv/bin/python scripts/run_synthetic_stress_validation.py --live --profile DEFAULT --warehouse-id da02d15a9490650b --catalog datapact --schema-prefix atlas_ga_stress --rows-per-scenario 2 --output docs/northstar_visual_qa/live-synthetic-stress-latest.json` -> passed.
- Evidence:
  - Artifact: `docs/northstar_visual_qa/live-synthetic-stress-latest.json`.
  - Run ID: `ga-stress-20260429210542-e95f5b0a`.
  - Run-scoped schema: `atlas_ga_stress_20260429210542_e95f5b0a`.
  - Marker validation: `16` expected/observed rows across Discovery, Governance, Lakebase, Quality, Lineage, Taxonomy, Genie, and cleanup; `0` marker failures.
  - Workflow validation: `2` expected workflows; `30` expected/observed immutable audit events; `30` distinct immutable event IDs.
  - Mutation coverage: approved and rejected governance paths, taxonomy association approvals, degraded and unavailable lineage cases, completed quality runs, Genie grounded answers, Lakebase mirror success records.
  - Safety: `0` Genie sentinel fallbacks, `0` Lakebase failed writes, `0` organic evidence leaks, `0` leftover cleanup rows.
- Current blockers:
  - Databricks bundle validation, deploy, and live route/browser validation still have not run for the current app snapshot.
  - Visual parity remains blocked by `267` open rows in `full_page_audit.md`.

### Checkpoint - Databricks Bundle Validation Started

- Scope:
  - Run Databricks-native bundle validation and `bundle summary` for target `dev` using `DEFAULT` and warehouse `da02d15a9490650b`.
  - Treat known non-matching `sync.exclude` warnings as warnings only if validation otherwise succeeds.
- Current blockers:
  - Bundle validation and summary results are pending.
  - No current app deployment has been performed in this tranche yet.

### Checkpoint - Databricks Bundle Validation Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed, `Validation OK!`.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed; workspace root `/Workspace/Users/skyler@entrada.ai/.bundle/atlas/dev`, app resource `atlas`.
- Notes:
  - `bundle summary` reports the Apps URL as `(not deployed)`, consistent with prior logged behavior when the active app snapshot is deployed via the Apps API. This is not being counted as live app proof.
- Current blockers:
  - The frontend bundle still needs a fresh `npm run build` before deploy.
  - Current snapshot deploy and live route/browser validation are still pending.

### Checkpoint - Frontend Production Build Started

- Scope:
  - Rebuild `frontend/dist` so the Databricks app deploy ships the current React code and updated interaction harness behavior.
- Current blockers:
  - Build result is pending.
  - App deploy and live validation remain pending.

### Checkpoint - Frontend Production Build Passed

- Validation:
  - `npm run build` from `frontend/` -> passed.
- Evidence:
  - `frontend/dist/atlas-build-manifest.json` build ID: `frontend-7c7d062bb864`.
  - Source hash: `7c7d062bb864ba2fb52a4e456c6b31e2d47e3340e80f0471ee1959e3fc8722ef`.
- Current blockers:
  - Deploying the rebuilt app snapshot is pending.
  - Live route/API and browser interaction validation are pending.

### Checkpoint - Current Snapshot Deploy Started

- Scope:
  - Deploy the current rebuilt app snapshot to the Databricks `dev` target using `DEFAULT`.
  - Use `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json`, matching the target-aware path previously used for this app.
- Current blockers:
  - Deployment result is pending.
  - Live route/API and browser validation must not run until the active build ID matches `frontend-7c7d062bb864`.

### Checkpoint - Current Snapshot Deploy Passed

- Validation:
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
  - `databricks apps get atlas --profile DEFAULT -o json` -> app `RUNNING`, compute `ACTIVE`, active deployment `SUCCEEDED`.
- Evidence:
  - Active deployment ID: `01f1441075861f65aaaabf7a93e30ddd`.
  - App URL: `https://atlas-2543889327043640.aws.databricksapps.com`.
  - Source code path: `/Workspace/Users/skyler@entrada.ai/.bundle/atlas/dev/files`.
  - Attached resources: SQL warehouse `da02d15a9490650b`, Genie space `01f1406a11221afa985d3fe64c9fbea1`, Lakebase branch/database resource.
  - Effective user scopes include `sql`, Unity Catalog read scopes, `catalog.connections`, `dashboards.genie`, and implicit IAM read scopes.
- Current blockers:
  - Live route/API validation must prove all checked endpoints serve build `frontend-7c7d062bb864`.
  - Live browser screenshot/interaction validation is still pending.

### Checkpoint - Live Route/API Validation Started

- Scope:
  - Run `frontend/scripts/atlas_route_live_validation.mjs` against `https://atlas-2543889327043640.aws.databricksapps.com` with a `DEFAULT` profile OAuth token.
  - Require deployed endpoints to report build ID `frontend-7c7d062bb864`.
  - Validate runtime/bootstrap, Asset 360, lineage, governance workbench/detail, insights, taxonomy, CDE dashboard/detail, audit evidence/detail, admin control-center, Genie, and Lakebase mirror state.
- Current blockers:
  - Live route/API validation is pending.
  - Live browser screenshot/interaction validation is pending.

### Checkpoint - Live Route/API Validation Passed

- Validation:
  - `frontend/scripts/atlas_route_live_validation.mjs` against `https://atlas-2543889327043640.aws.databricksapps.com` -> passed.
- Evidence:
  - Artifact: `docs/hardening/live-route-validation-reopened-functional.json`.
  - Deployment ID: `01f1441075861f65aaaabf7a93e30ddd`.
  - Expected build ID: `frontend-7c7d062bb864`.
  - Runtime, bootstrap, Asset 360, lineage, governance workbench/detail, insights, taxonomy, CDE dashboard/detail, audit evidence/detail, admin control-center, and Genie endpoints all returned build `frontend-7c7d062bb864`.
  - Lakebase write mirror: `active`, `delta-primary-lakebase-shadow`, `3` attempted / `3` succeeded / `0` failed.
  - Genie: provider `genie`, confidence `genie-grounded`, evidence count `1`, no sentinel SQL fallback, no sentinel row fallback, no sentinel warning.
  - Governance detail: `5` workbench requests, selected request `ga-home-seed-request-01`, `4` diff rows, `2` approver steps.
  - Audit evidence: `25` events, authoritative metadata-audit source, numeric summary, before/after keys, linked request evidence.
- Current blockers:
  - Live browser screenshot/interaction validation is still pending.
  - Visual parity remains blocked by the open full-page audit rows.

### Checkpoint - Live Browser Screenshot/Interaction Validation Started

- Scope:
  - Run `frontend/scripts/atlas_prototype_current_capture.mjs` against the deployed app without `GOVAT_PROTOTYPE_MOCK_API`.
  - Capture Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, and Control Center at `1536x1024`, `1440x900`, and `1280x720`.
  - Exercise route interaction harnesses with live APIs and record artifacts under `docs/northstar_visual_qa/prototype-live-reopened-functional`.
- Current blockers:
  - Live browser capture/interaction result is pending.

### Checkpoint - Discover Functional Controls Guard Passed

- Implemented:
  - Reconciled the Discover functional ledger with the latest local prototype-mock interaction evidence in `docs/northstar_visual_qa/prototype-current-discover-functional-local/prototype-current-report.json`.
  - Discover now has `3` open functional controls: topbar search preload from Discover, explicit loading-state proof for Discover search, and the bottom-card Atlas AI Recommendations `View all` behavior.
- Validation:
  - `npm run test -- src/components/DiscoveryWorkspace.test.jsx src/hooks/useDiscoveryResults.test.jsx` from `frontend/` -> passed, `42` tests.
  - Local prototype-mock Discover functional capture passed at `1536x1024` with `7` Discover interaction specs, `0` page errors, and no unexpected request failures.
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md AGENT_CHANGELOG.md docs/northstar_gap_analysis/functional_control_audit.md frontend/scripts/atlas_prototype_current_capture.mjs frontend/src/components/DiscoveryWorkspace.jsx frontend/src/components/DiscoveryWorkspace.test.jsx frontend/src/styles/northstar.css` -> passed.
- Current blockers:
  - `267` visual/page/shared gaps remain open in `docs/northstar_gap_analysis/full_page_audit.md`.
  - `53` functional controls remain open in `docs/northstar_gap_analysis/functional_control_audit.md`.
  - No page has visual or functional signoff.
- Exact next actions:
  - Close the `3` remaining Discover functional controls before moving to Stewardship.
  - Re-run the Discover tests, local prototype-mock Discover interaction capture, audit guard, and scoped diff check after the next patch.

### Checkpoint - Discover Functional Controls Closed Locally

- Implemented:
  - Aligned Atlas AI availability so prototype-mock Atlas AI can be exercised consistently by the Discover bottom-card recommendation flow and the shared shell chat.
  - Added a visible `Loading discovery results` banner while Discover searches are pending.
  - Added direct Discover unit coverage for loading state, bottom-card Atlas AI recommendations, and disabled bottom-card Atlas AI when no backed endpoint exists.
  - Expanded the local prototype-mock Discover interaction harness to validate topbar search preload, search loading, and bottom-card Atlas AI Recommendations request/evidence routing.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/DiscoveryWorkspace.test.jsx src/hooks/useDiscoveryResults.test.jsx` from `frontend/` -> passed, `45` tests.
  - `docs/northstar_visual_qa/prototype-current-discover-functional-local/prototype-current-report.json` -> passed with `1` capture, `8` Discover interactions, `0` page errors, and `0` unexpected request failures.
- Current blockers:
  - Discover has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `44` open full-page audit gaps.
  - Overall functional controls now stand at `50` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to Stewardship functional controls only after the guard passes.

### Checkpoint - Stewardship Functional Controls Started

- Trigger:
  - Discover functional rows are locally closed, but Stewardship still has `9`
    open visible-control rows in `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise or truthfully disable the remaining Stewardship controls: affected
    asset opening, suggested actions, Comment, Resolve, Bulk assign, New work item,
    pagination, and route-specific Atlas AI prompt/evidence routing.
  - Do not claim backed workflow persistence unless the UI/API evidence proves it.
- Subagent input:
  - Existing reviewers continue to block signoff on visual parity and live-proof
    grounds, and specifically called out Stewardship queue/detail density, suggested
    action backing, and missing route-level click-through evidence.
  - New subagent spawn remains unavailable because the current thread already has the
    active reviewer set; their findings are being treated as required input.
- Validation target:
  - Focused Stewardship component tests for any behavior changed.
  - Local prototype-mock Stewardship interaction capture.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - Stewardship Functional Controls Closed Locally

- Implemented:
  - Added disabled pagination rationale for one-page Stewardship queues.
  - Added Stewardship component coverage for affected asset opening and Archive suggested-action unavailable state.
  - Expanded the local prototype-mock Stewardship interaction harness to validate affected asset routing, suggested action unavailable panels, Comment/Resolve PATCH payloads, disabled pagination rationale, Lineage routing, and route-specific Atlas AI prompt/evidence.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/GovernanceWorkspace.test.jsx` from `frontend/` -> passed, `10` tests.
  - `docs/northstar_visual_qa/prototype-current-stewardship-functional-local/prototype-current-report.json` -> passed with `1` capture, `4` Stewardship interactions, `0` page errors, and `0` unexpected request failures.
- Current blockers:
  - Stewardship has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `30` open full-page audit gaps.
  - Overall functional controls now stand at `41` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to Glossary functional controls after the guard passes.

### Checkpoint - Glossary Functional Controls Started

- Trigger:
  - Glossary still has `7` open visible-control rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise or truthfully disable linked asset association browsing, zero-asset
    controls, version history, hierarchy/nested term browsing, global shell controls,
    Atlas AI, and responsive card control visibility.
  - Preserve the prototype shape without inventing backed glossary workflows.
- Validation target:
  - Focused Glossary/Taxonomy tests for any behavior changed.
  - Local prototype-mock Glossary interaction capture.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - Glossary Functional Controls Closed Locally

- Implemented:
  - Changed Glossary linked-asset count behavior to open a real association browser instead of opening only the first asset.
  - Displayed source FQNs inside the association browser so the linked Unity Catalog object is inspectable before routing.
  - Added zero-asset disabled-state rationale for card and detail actions.
  - Added Glossary detail coverage for reviewer workflow, version history, hierarchy/unavailable state, and association browsing.
  - Expanded the prototype interaction harness to validate Glossary global search, help, profile menu, Atlas AI prompt/evidence, lineage routing, and responsive card control containment.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/TaxonomyWorkspace.test.jsx` from `frontend/` -> passed, `7` tests.
  - `docs/northstar_visual_qa/prototype-current-glossary-functional-local/prototype-current-report.json` -> passed with `3` captures, `12` Glossary interactions, `0` page errors, and `0` request failures across `1536x1024`, `1440x900`, and `1280x720`.
- Current blockers:
  - Glossary has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `30` open full-page audit gaps.
  - Overall functional controls now stand at `34` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to CDE Registry functional controls after the guard passes.

### Checkpoint - CDE Registry Functional Controls Started

- Trigger:
  - CDE Registry still has `5` open visible-control rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise or truthfully disable reviewer/owner workflow, sort/filter behavior,
    `+ New term` semantics from the CDE tab, Atlas AI prompt/evidence routing, and
    responsive table control visibility.
  - Preserve source-of-record column truth and do not invent CDE recertification or
    owner mutations.
- Validation target:
  - Focused Taxonomy/CDE tests for any changed CDE behavior.
  - Local prototype-mock CDE Registry interaction capture across target viewports.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - CDE Registry Functional Controls Closed Locally

- Implemented:
  - Added CDE Registry search, status filter, and sort controls backed by local table state.
  - Made the shared `+ New term` control clarify CDE request semantics when the CDE tab is active.
  - Added explicit CDE owner workflow unavailable feedback without inventing an owner mutation.
  - Expanded the local prototype-mock harness to validate CDE source detail, owner/recertification unavailable workflows, Lineage routing, search/filter/sort, Atlas AI prompt/evidence, and responsive table/control containment.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/TaxonomyWorkspace.test.jsx` from `frontend/` -> passed, `8` tests.
  - `docs/northstar_visual_qa/prototype-current-cde-functional-local/prototype-current-report.json` -> passed with `3` captures, `12` CDE Registry interactions, `0` page errors, and `0` request failures across `1536x1024`, `1440x900`, and `1280x720`.
- Current blockers:
  - CDE Registry has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `27` open full-page audit gaps.
  - Overall functional controls now stand at `29` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to Lineage Atlas functional controls after the guard passes.

### Checkpoint - Lineage Atlas Functional Controls Started

- Trigger:
  - Lineage Atlas still has `7` open visible-control rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise or truthfully disable graph zoom controls, node detail selection,
    restricted-node affordance, impact-row navigation, Notify owners, column-lineage
    row/tree interactions, and Atlas AI prompt/evidence routing.
  - Preserve permission boundaries and do not invent hidden downstream assets or
    notification delivery.
- Validation target:
  - Focused Lineage component tests for changed behavior.
  - Local prototype-mock Lineage interaction capture across target viewports.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - Lineage Atlas Functional Controls Closed Locally

- Implemented:
  - Made column-lineage rows selectable so the advertised column tree/list is interactive.
  - Added unit coverage for graph node selection, impact rows, restricted rows, and column lineage row selection.
  - Expanded the local prototype-mock harness to validate version/impact/table-column/search/export controls, absence of unimplemented zoom controls, graph node selection, restricted-boundary affordance, impact rows, Notify owners routing, selected asset routing, column-lineage rows, and Atlas AI prompt/evidence.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/LineageStage.test.jsx` from `frontend/` -> passed, `6` tests.
  - `docs/northstar_visual_qa/prototype-current-lineage-functional-local/prototype-current-report.json` -> passed with `3` captures, `15` Lineage Atlas interactions, `0` page errors, and `0` request failures across `1536x1024`, `1440x900`, and `1280x720`.
- Current blockers:
  - Lineage Atlas has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `34` open full-page audit gaps.
  - Overall functional controls now stand at `22` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to Audit Evidence functional controls after the guard passes.

### Checkpoint - Audit Evidence Functional Controls Started

- Trigger:
  - Audit Evidence still has `2` open visible-control rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise row evidence-link behavior and route-specific Atlas AI prompt/evidence.
  - Preserve append-only/provenance truth; local artifacts must remain labeled local
    prototype-mock evidence.
- Validation target:
  - Focused Audit component tests if UI behavior changes.
  - Local prototype-mock Audit Evidence interaction capture across target viewports.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - Audit Evidence Functional Controls Closed Locally

- Implemented:
  - Added accessible labels and titles to inline audit evidence target buttons.
  - Expanded unit coverage to assert inline evidence target routing is discoverable and backed by the selected entity FQN.
  - Expanded the local prototype-mock harness to validate inline evidence target routing and route-specific Atlas AI prompt/evidence in addition to the existing audit filters, exports, row detail, and selected-detail asset routing.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/AuditBrowserWorkspace.test.jsx` from `frontend/` -> passed, `6` tests.
  - `docs/northstar_visual_qa/prototype-current-audit-functional-local/prototype-current-report.json` -> passed with `3` captures, `12` Audit Evidence interactions, `0` page errors, and `0` request failures across `1536x1024`, `1440x900`, and `1280x720`.
- Current blockers:
  - Audit Evidence has `0` open rows in `functional_control_audit.md`, but it is not visually signed off and still has `28` open full-page audit gaps.
  - Overall functional controls now stand at `20` open rows.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and the scoped diff check.
  - Move to Control Center functional controls after the guard passes.

### Checkpoint - Control Center Functional Controls Started

- Trigger:
  - Control Center still has `5` open visible-control rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Scope:
  - Exercise job/run URL behavior where available, global search/help/profile controls
    from Control Center, notifications state, route-specific Atlas AI prompt/evidence,
    and responsive job/integration/policy control containment.
  - Keep unavailable linked resources disabled with rationale rather than faking
    external Databricks URLs.
- Validation target:
  - Focused Control Center/Admin tests for any changed behavior.
  - Local prototype-mock Control Center interaction capture across target viewports.
  - `npm run northstar:audit-contract`.
  - Scoped `git diff --check`.

### Checkpoint - Rules And Control Center Patch Started

- Trigger:
  - The product owner required the Command Center audit discipline to be applied to
    every `northstar/*` page and asked that repo rules prevent future false visual or
    subagent signoff.
  - Control Center remains the active functional tranche with `5` open rows in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
- Planned edits:
  - Tighten `AGENTS.md` so every page needs a materialized failure-analysis note when
    a prior signoff misses obvious visual differences, and so reviewer signoff cannot
    precede a page-by-page gap ledger refresh.
  - Add Control Center evidence for backed job URL opening, no-URL disabled state,
    topbar search/help/profile controls, notifications, route-specific Atlas AI, and
    responsive control containment.
- Validation target:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - `npm run test -- src/components/AdminWorkspace.test.jsx`
  - Local prototype-mock Control Center interaction capture at `1536x1024`,
    `1440x900`, and `1280x720`.
  - `npm run northstar:audit-contract`
  - Scoped `git diff --check`

### Checkpoint - Control Center Functional Controls Closed Locally

- Implemented:
  - Added a reported Databricks job/run URL to the prototype-mock Control Center
    diagnostics payload and verified `Open linked resource` opens it only when present.
  - Preserved the no-URL job disabled state with a truthful diagnostic rationale.
  - Expanded Control Center browser interaction evidence for topbar search,
    notifications, help, profile menu, route-specific Atlas AI prompt/evidence, and
    responsive job/integration/policy/detail containment.
  - Tightened `AGENTS.md` and `full_page_audit.md` with explicit false-signoff failure
    analysis and page-by-page audit requirements.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/AdminWorkspace.test.jsx` from `frontend/` ->
    passed, `8` tests.
  - `docs/northstar_visual_qa/control-functional-controls-v2-local/prototype-current-report.json`
    -> passed with `3` captures, `12` Control Center interactions, `0` page errors,
    and `0` request failures across `1536x1024`, `1440x900`, and `1280x720`.
- Current blockers:
  - Control Center has `0` open rows in `functional_control_audit.md`, but it is not
    visually signed off and still has `24` open full-page audit gaps.
  - Overall functional controls now stand at `15` open rows: Command Center `6` and
    Cross-Page Shared `9`.
  - Evidence is local prototype-mock only, not live Databricks proof.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and scoped diff hygiene.
  - Continue with the remaining Command Center and Cross-Page Shared functional rows
    before any visual-signoff attempt.

### Checkpoint - Control Center Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- AGENTS.md IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/functional_control_audit.md frontend/src/components/AdminWorkspace.test.jsx frontend/scripts/atlas_prototype_current_capture.mjs`
    -> passed.
- Current blockers:
  - `267` visual/page/shared gaps remain open in
    `docs/northstar_gap_analysis/full_page_audit.md`.
  - `15` functional controls remain open in
    `docs/northstar_gap_analysis/functional_control_audit.md`.
  - No page is signed off and no live Databricks proof has been produced in this
    checkpoint.
- Exact next action:
  - Start the remaining Command Center and Cross-Page Shared functional-control tranche.

### Checkpoint - Command Center And Shared Functional Tranche Started

- Trigger:
  - `docs/northstar_gap_analysis/functional_control_audit.md` still has `15` open
    rows: Command Center `6` and Cross-Page Shared `9`.
- Scope:
  - Exercise or implement truthful behavior for Command Center Atlas AI
    loading/answer/evidence/error states, chart/info affordances, domain posture,
    risk/open-exposure, activity-stream, and lower-scroll regions.
  - Reconcile shared open rows for visible-control inventory, no-op prevention,
    navigation, Atlas AI state coverage, mutation/backing, loading states,
    responsive controls, and separate live Databricks validation.
- Validation target:
  - Focused Home/AppFrame tests for changed behavior.
  - Local prototype-mock Command Center interaction capture across target viewports.
  - Audit contract and scoped diff hygiene.
  - Keep live Databricks validation open unless it is actually deployed and captured.

### Checkpoint - Command Center And Shared Functional Local Closure

- Implemented:
  - Converted Command Center domain posture rows and risk/open-exposure rows from
    static text into route-aware controls with truthful disabled states when the source
    signal is unavailable.
  - Expanded the Command Center browser interaction harness to validate info tooltip
    affordances, domain/risk/activity routing, lower-scroll regions, global North Star
    navigation, Atlas AI suggestion click, typed prompt, loading, answer, evidence, and
    error states.
  - Added a deliberate prototype-mock Atlas AI `503` error path to prove the visible
    error transcript without treating the error-path requests as unexpected failures.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useAtlasAiConversation.test.jsx`
    from `frontend/` -> passed, `33` tests.
  - `docs/northstar_visual_qa/prototype-current-command-functional-local/prototype-current-report.json`
    -> passed with `3` captures, `3` main-bottom screenshots, `24` interactions, `0`
    page errors, and `0` unexpected request failures across `1536x1024`, `1440x900`,
    and `1280x720`.
- Current blockers:
  - Functional control audit now has `2` open rows: mutation controls still need
    live/auditable-state proof and deployed/live Databricks validation must be recorded
    separately from local prototype-mock evidence.
  - `267` visual/page/shared gaps remain open in `full_page_audit.md`.
  - No page is signed off.
- Exact next actions:
  - Run `npm run northstar:audit-contract` and scoped diff hygiene.
  - Begin the live/auditable mutation and deployed Databricks validation tranche.

### Checkpoint - Live Mutation And Deploy Validation Tranche Started

- Trigger:
  - Only `2` functional-control rows remain open: mutation controls need auditable
    live/backed-state proof or disabled-state proof, and deployed/live Databricks
    validation must be recorded separately from local prototype-mock validation.
- Scope:
  - Inspect existing live QA scripts and backend mutation/audit tests before running
    live actions.
  - Run Databricks-native validation and `bundle summary` with profile `DEFAULT`.
  - Deploy/validate the app only through the normal Databricks App development flow.
  - Record live evidence separately from local prototype-mock evidence.
- Validation target:
  - Focused backend audit/mutation tests.
  - Databricks bundle validation/summary.
  - Live deployed route/control QA artifact if deploy succeeds.

### Checkpoint - AI Responsive Auto-Open Retune Started

- Trigger:
  - Fresh prototype-mock screenshots in `docs/northstar_visual_qa/prototype-current-ai-responsive-local/` show the AI rail no longer covers narrow pages at `1280x720` and `1440x900`, but it still collides with the Discover selected drawer at `1536x1024`.
- Planned change:
  - Keep the Atlas AI topbar control and floating/resizable chat available at all widths.
  - Stop auto-opening the docked AI rail until wide desktop viewports where it can reserve space without hiding route-specific panels.
  - Keep this as a shared shell change, not a route-specific workaround.
- Validation target:
  - `npm run test -- src/components/AppFrame.test.jsx`
  - fresh prototype-mock capture at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720`
  - visual inspection of Discover selected, Audit, Lineage, Glossary, Control Center, and Command Center responsive screenshots
  - `npm run northstar:audit-contract`
  - focused `git diff --check`

### Checkpoint - AI Responsive Auto-Open Unit Validation Passed

- Implemented:
  - Raised the shared Atlas AI auto-open/reserved-layout breakpoint from `1500px` to `1800px`.
  - The AI Copilot topbar button still opens the floating chat at narrower widths, but the rail no longer auto-opens where it can collide with page-specific drawers or tables.
- Validation:
  - `npm run test -- src/components/AppFrame.test.jsx` from `frontend/` -> passed, `1` file, `16` tests.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/components/AppFrame.jsx frontend/src/components/AppFrame.test.jsx frontend/src/styles/northstar.css` -> passed.
- Important limitation:
  - This is not a visual signoff. Fresh screenshots must prove the `1536x1024` Discover selected drawer, Audit, Lineage, and other responsive pages are no longer covered.
- Exact next action:
  - Regenerate the current prototype-mock screenshot set and inspect the affected responsive pages before changing any audit rows.

### Checkpoint - AI Responsive Screenshot Evidence Promoted

- Evidence:
  - Regenerated all screenshot-backed `northstar/*` routes and Discover selected-state captures into `docs/northstar_visual_qa/prototype-current-ai-responsive-local/`.
  - Capture report: `32` static captures plus `4` Discover selected-state captures at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720`; report `passed=true`, `0` page errors, and `0` request failures.
  - Evidence kind remains `prototype_mock`; it is not live Databricks evidence.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-ai-responsive-local/` in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` current screenshot paths.
  - Checked off only screenshot-proven responsive AI occlusion rows for Command Center, Discover selected-state, Stewardship, Glossary, Lineage, Audit, and Cross-Page shared shell behavior.
- Current open gap count:
  - `267` open gaps: Command Center `33`, Discover `44`, Stewardship `30`, Glossary `30`, CDE Registry `27`, Lineage Atlas `34`, Audit Evidence `28`, Control Center `24`, Cross-Page Shared `17`.
- Important limitation:
  - This closes only the responsive AI occlusion problem. The Atlas AI rail still has open visual/content/functionality rows, and no page is signed off.
- Exact next action:
  - Run the audit guard, then start the next tranche: control-level interaction evidence for every visible control before marking functional rows complete.

### Checkpoint - AI Responsive Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/reference_manifest.json frontend/src/components/AppFrame.jsx frontend/src/components/AppFrame.test.jsx frontend/src/styles/northstar.css` -> passed.
- Current blockers remain:
  - `267` open visual/functional/truth/process gaps.
  - `130` open control-level workflow items.
  - No page is signed off.
- Exact next action:
  - Build and run a current-app interaction harness that clicks/validates visible controls across all North Star pages, then use the resulting evidence to drive the next functional fixes.

### Checkpoint - Functional Interaction Harness Started

- Trigger:
  - `docs/northstar_gap_analysis/functional_control_audit.md` still lists `130` open visible-control workflow items.
  - Current screenshot capture records visible controls but does not execute them or prove useful outcomes.
- Scope:
  - Add a bounded Playwright interaction harness for the current `northstar/*` route set.
  - Validate real, observable behavior for navigation, tab/range/filter toggles, drawer actions, AI prompt submission/loading, export/download actions, and route-specific workflow buttons where implemented.
  - Record failures as evidence without marking rows complete unless the workflow is proven.
- Validation target:
  - Harness syntax/execution against local prototype-mock app.
  - `npm run northstar:audit-contract`
  - focused `git diff --check`

### Checkpoint - Functional Interaction Harness Implementation In Progress

- Planned script changes:
  - Extend `frontend/scripts/atlas_prototype_current_capture.mjs` with reusable Playwright helpers for visible-control clicks, dialogs, downloads, route assertions, and text/status assertions.
  - Add route-specific interaction specs for Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, Control Center, and shared Atlas AI shell behavior.
  - Save interaction screenshots and structured validation results into the existing `prototype-current-report.json` so control-level evidence is reviewable beside visual captures.
- Guardrail:
  - This harness will not close rows by itself. A control remains open unless the report proves the visible control has a useful, truthful outcome or the app explicitly marks an unavailable workflow as disabled/degraded.
- Exact next actions:
  - Patch the capture script.
  - Run syntax validation.
  - Run a one-viewport local prototype-mock interaction pass before promoting any evidence.

### Checkpoint - Functional Interaction Harness Local Pass

- Implemented:
  - Added route-level Playwright interaction specs for Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, Control Center, and shared shell AI/search behavior.
  - Added download verification for Command Center brief export, Lineage graph export, Audit report export, and Audit CSV export.
  - Fixed the Command Center CDE handoff so CDE navigation opens the North Star `taxonomy?tab=cdes` registry instead of the legacy standalone CDE surface.
  - Passed `onOpenLineage` into the North Star Glossary/CDE workspace so term and CDE lineage controls route to Lineage Atlas instead of falling back to Asset 360.
  - Made the Discover preview close affordance remain reachable during preview action testing.
- Evidence:
  - `docs/northstar_visual_qa/prototype-current-functional-local/prototype-current-report.json` passed at `1536x1024`: `8` route captures, `18` interaction specs, `0` page errors, `0` request failures.
  - Evidence kind remains `prototype_mock`; this is not live Databricks evidence and is not visual signoff.
- Ledger update:
  - Updated `docs/northstar_gap_analysis/functional_control_audit.md` to record the functional evidence and check off only the rows proven by the local interaction report.
  - Functional controls now have `75` open rows: Command Center `11`, Discover `17`, Stewardship `9`, Glossary `7`, CDE Registry `5`, Lineage Atlas `7`, Audit Evidence `2`, Control Center `5`, Cross-Page Shared `12`.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/hooks/useAppRouteState.test.jsx` -> passed, `31` tests.
  - `npm run test -- src/App.test.jsx src/hooks/useAppRouteState.test.jsx` -> failed only in existing/adjacent `App > uses command center estate for the home route over bootstrap seed values`, which remained on the `Loading home` fallback and did not find expected command-center text. This remains an open risk, not signoff.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/scripts/atlas_prototype_current_capture.mjs frontend/src/App.jsx frontend/src/hooks/useAppRouteState.js frontend/src/styles/northstar.css` -> passed before this status update.
- Exact next actions:
  - Run the North Star audit-contract guard against the updated functional ledger.
  - Fix or isolate the failing `App.test.jsx` home-route loading test.
  - Continue with the remaining `75` functional controls and `267` visual gaps.

### Checkpoint - Home Route App Test Repaired

- Implemented:
  - Added a focused `HomePage` mock in `frontend/src/App.test.jsx` so App-level tests validate route/data handoff without waiting on the full lazy HomePage implementation.
- Validation:
  - `npm run test -- src/App.test.jsx src/hooks/useAppRouteState.test.jsx` from `frontend/` -> passed, `2` files, `56` tests.
- Current blockers:
  - `75` functional controls remain open.
  - `267` visual/page/shared gaps remain open.
  - No page is signed off.
- Exact next action:
  - Run guard/diff hygiene after the test repair, then continue the next functional/visual tranche.

### Checkpoint - Rules Of Engagement Hardening Started

- Trigger:
  - User identified that prior "visually indistinguishable" and subagent-signoff claims missed obvious page-level differences.
  - The same exhaustive, screenshot-backed audit used on Command Center must now apply to every `northstar/*` page before any page can be considered complete.
- Scope:
  - Harden repo rules and machine guards so stale screenshots, route-capture health, previous reviewer notes, and subagent assertions cannot be treated as visual or functional signoff.
  - Re-run the current audit/validation baseline after the guard update.
  - Generate fresh current screenshots after the newest Worker D changes before checking off any Audit Evidence or Control Center rows.
- Current blockers:
  - No page is signed off.
  - `docs/northstar_gap_analysis/full_page_audit.md` still has `262` open gaps and remains the only active materialized gap ledger.
  - Current promoted evidence predates the latest Audit Evidence and Control Center worker changes.
- Exact next actions:
  - Patch `AGENTS.md` and the North Star audit guard with stricter evidence/signoff requirements.
  - Run the audit contract, focused Audit/Control tests, and diff hygiene.
  - Capture and inspect fresh current screenshots for every screenshot-backed `northstar/*` route.

### Checkpoint - Rules Of Engagement Hardening Validated

- Implemented:
  - Added explicit false-signoff failure-prevention gates to `AGENTS.md`, including prohibitions on completion language while audit rows remain open, current-evidence-only reviewer quorum, control-level functional evidence, and mandatory reopening when the product owner identifies an obvious missed mismatch.
  - Updated `docs/northstar_gap_analysis/prototype_contract.md` so the active evidence source is always the manifest, not any hard-coded stale screenshot directory.
  - Strengthened `scripts/check_northstar_audit_contract.py` to require a current evidence report, evidence kind, mock/non-live warning for mock captures, report viewport coverage, and captured manifest routes.
- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `npm run test -- src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx` from `frontend/` -> passed, `2` files, `13` tests.
  - `git diff --check -- AGENTS.md IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/prototype_contract.md scripts/check_northstar_audit_contract.py` -> passed.
- Important limitation:
  - This hardens process only. It closes no visual or functional page gaps and signs off no page.
- Exact next action:
  - Regenerate fresh current screenshots after the latest Worker D changes and inspect the Audit Evidence / Control Center pages before updating the ledger.

### Checkpoint - Fresh Worker D Current Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes plus Discover selected overlay states at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-worker-d-local/`.
  - Capture report: `32` static captures, `4` Discover selected interaction captures, `0` page errors, `0` request failures, and `0` console errors.
  - Evidence kind is `prototype_mock`; the report includes `Prototype mock data, not live Databricks evidence.`
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-worker-d-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` screenshot paths to the fresh evidence directory only.
- Important limitation:
  - No visual or functional rows were checked off in this checkpoint. The screenshots are current evidence, not signoff.
- Exact next action:
  - Reconcile subagent page-audit findings against `full_page_audit.md`, then update the materialized gap list before implementing the next tranche.

### Checkpoint - Full Subagent Audit Findings Materialized

- Reviewers:
  - Command Center / Discover visual reviewer: blocked signoff and identified remaining shell, hero, risk, lower-scroll, responsive AI-rail, Discover trust-score, drawer, and control-evidence gaps.
  - Stewardship / Glossary / CDE visual reviewer: blocked signoff and identified remaining table rhythm, detail-pane, responsive, copy, icon, workflow, and route-mapping gaps.
  - Lineage / Audit / Control visual reviewer: blocked signoff and identified remaining topology, audit/action, policy/job/integration, responsive AI-rail, and route-specific AI gaps.
  - Cross-page functional/truth reviewer: blocked signoff and identified stale contract closeout language, missing control-level evidence, local-only controls, and prototype-mock truth risks.
- Implemented:
  - Removed stale zero-gap/current-closeout claims from `docs/northstar_gap_analysis/prototype_contract.md`.
  - Added `docs/northstar_gap_analysis/functional_control_audit.md` with `130` open visible-control workflow items.
  - Strengthened `scripts/check_northstar_audit_contract.py` to validate the control ledger and reject stale prototype-contract closeout claims.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` with the reviewer findings and fresh evidence paths.
- Current open gap count:
  - `274` open visual/functional/truth/process gaps in `full_page_audit.md`.
  - `130` open controls in `functional_control_audit.md`.
- Important limitation:
  - These changes improve process and materialize the missing work. They do not close any page and do not provide signoff.
- Exact next action:
  - Run the audit contract and diff hygiene, then start the next implementation tranche against the largest shared blockers: AI rail responsive occlusion, prototype palette/shell mismatch, and missing control-level interaction harness.

### Checkpoint - Full Audit Materialization Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- AGENTS.md AGENT_CHANGELOG.md IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/functional_control_audit.md docs/northstar_gap_analysis/prototype_contract.md docs/northstar_gap_analysis/reference_manifest.json scripts/check_northstar_audit_contract.py` -> passed.
- Current blockers remain:
  - `274` open page/shared gaps.
  - `130` open visible-control workflow gaps.
  - No page is signed off.
- Exact next action:
  - Implement the first shared remediation tranche: prevent the Atlas AI rail from occluding primary page content at responsive widths, then add control-level interaction capture coverage that can begin reducing functional rows.

### Checkpoint - Shared AI Responsive Remediation Started

- Target:
  - Prevent the open Atlas AI panel from covering page content at `1536x1024`, `1440x900`, and `1280x720`.
  - Keep the current floating/drag/resizable behavior, but reserve layout space for the panel whenever it is open in the North Star shell.
- Planned edits:
  - Centralize the reservation in shared shell CSS instead of applying page-specific offsets.
  - Add a shell-level attribute/test hook if needed for future page-specific review, without changing routing behavior.
- Validation target:
  - `npm run test -- src/components/AppFrame.test.jsx`
  - fresh Playwright captures at all required viewports
  - audit-contract and diff hygiene

### Checkpoint - Shared AI Responsive Unit Validation Passed

- Implemented:
  - Added a shell `data-active-module` attribute for future page-specific inspection hooks.
  - Updated shared North Star shell CSS so an open Atlas AI panel reserves right-side main-content space at all prototype viewports, not only wide desktop.
  - Kept the floating, draggable, resizable panel behavior intact.
- Validation:
  - `npm run test -- src/components/AppFrame.test.jsx` from `frontend/` -> passed, `1` file, `16` tests.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/components/AppFrame.jsx frontend/src/styles/northstar.css` -> passed.
- Important limitation:
  - This does not close the responsive AI-rail visual rows until fresh screenshots prove the panel no longer covers primary content.
- Exact next action:
  - Regenerate current screenshots at all required viewports and inspect the responsive pages before checking off any visual rows.

### Checkpoint - Prototype Mock AI Rail Validation Started

- Trigger:
  - Fresh page audit found that the prototype AI rail was absent from current prototype-mock screenshots even though the `northstar/*` reference has it open on every page.
  - The topbar Atlas AI control also appeared disabled or low-confidence in prototype-mock captures, which made visual comparison structurally invalid.
- Implemented before this checkpoint:
  - Updated the shell AI availability gate so explicitly labeled `prototype_mock` / `prototype-mock` evidence can render the Atlas AI rail in local prototype visual captures without presenting it as live Databricks evidence.
  - Added a focused `AppFrame` test for prototype-mock AI visibility and the non-live grounding label.
- Validation target:
  - Rerun `npm run test -- src/components/AppFrame.test.jsx`.
  - Regenerate Playwright screenshots after the test if it passes.
  - Update this file and the audit ledger only with evidence-backed changes.

### Checkpoint - Prototype Mock AI Rail Unit Validation Passed

- Validation:
  - `npm run test -- src/components/AppFrame.test.jsx` from `frontend/` -> passed, `1` file, `15` tests.
- Important limitation:
  - This proves the shell renders and labels prototype-mock Atlas AI in component tests. It does not prove the rail appears correctly in page screenshots or matches the prototype.
- Exact next action:
  - Regenerate current-app Playwright screenshots with prototype mock API enabled and inspect whether the AI rail is visible on every screenshot-backed `northstar/*` page without being mislabeled as live Databricks evidence.

### Checkpoint - Prototype Mock AI Rail Screenshot Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-ai-rail-local/`.
  - Capture report: `32` expected captures, `32` captured, `0` page errors, `0` request failures.
  - Evidence kind remains `prototype_mock`; the UI rail labels it `Prototype mock evidence - not live Databricks`.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-ai-rail-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` screenshot paths and checked off only the AI-rail-present/topbar-active rows proven by the new screenshots.
- Current open gap count:
  - `286` open gaps: Command Center `42`, Discover `51`, Stewardship `33`, Glossary `31`, CDE Registry `27`, Lineage Atlas `36`, Audit Evidence `29`, Control Center `22`, Cross-Page Shared `15`.
- Important limitation:
  - AI rail presence is now evidenced, but AI rail content/layout, prompt workflow, answer quality, and evidence-link behavior still remain open and must be validated separately.
- Exact next action:
  - Run the audit-contract guard and then continue with high-ripple shared visual/functionality gaps, starting with shell/sidebar badge and unmocked prototype-mock warning banners that still distort first-viewport parity.

### Checkpoint - Prototype Mock AI Rail Evidence Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/reference_manifest.json frontend/src/components/AppFrame.jsx frontend/src/components/AppFrame.test.jsx` -> passed.
- Remaining blockers:
  - AI rail is present but not visually or functionally signed off.
  - Prototype-mock warning banners still appear in page content and alter first-viewport parity.
  - Left-rail Stewardship count/badge still does not match the prototype route set.
- Exact next action:
  - Repair the shared shell/status presentation so truthful mock/degraded provenance is visible without injecting unmocked layout banners, and ensure the Stewardship badge renders from the governance inbox count.

### Checkpoint - Shared Shell Status And Badge Patch Validated

- Implemented:
  - Enabled the governance summary query for the shell across loaded app surfaces so the Stewardship badge is not limited to the Stewardship route.
  - Kept prototype-mock provenance out of the Command Center layout banner when that provenance is already labeled by shell/AI capture context, while preserving real degraded warning banners.
  - Added focused tests for the shell Stewardship badge and Command Center prototype-mock banner suppression.
- Validation:
  - `npm run test -- src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/App.test.jsx` -> passed, `4` files, `63` tests.
- Important limitation:
  - Browser screenshots still need to confirm the badge and banner behavior in the actual app layout before any ledger rows are checked off.
- Exact next action:
  - Regenerate the current-app Playwright captures and update the audit ledger only for rows proven fixed by screenshots.

### Checkpoint - Stewardship Badge Normalization Repair Validated

- Finding from browser evidence:
  - The Command Center screenshot still lacked the Stewardship badge after enabling the global governance summary query.
  - Root cause: `normalizeGovernancePayload` dropped `inbox.stewardshipCount`, so the shell never received the count from `/api/governance/summary`.
- Implemented:
  - Preserved `stewardshipCount` in governance inbox normalization.
  - Added a normalization contract test for the shell badge count.
- Validation:
  - `npm run test -- src/lib/api.metadataContract.test.js src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/App.test.jsx` -> passed, `5` files, `74` tests.
- Exact next action:
  - Regenerate current-app screenshots again and only then mark the Stewardship badge visual rows fixed if visible in the rendered app.

### Checkpoint - Shared Prototype Mock Banner Suppression Validated

- Browser finding:
  - The homepage banner was gone after the page-local fix, but Glossary/CDE still rendered a full-width `Data availability is limited` banner for prototype-mock provenance.
- Implemented:
  - Updated the shared `DegradedBanner` primitive to suppress prototype-mock-only provenance warnings while preserving real degraded warnings.
  - Added direct `DegradedBanner` tests and reran affected page suites.
- Validation:
  - `npm run test -- src/components/northstar/DegradedBanner.test.jsx src/components/HomePage.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx src/components/AdminWorkspace.test.jsx src/lib/api.metadataContract.test.js src/components/AppFrame.test.jsx src/App.test.jsx` -> passed, `8` files, `79` tests.
- Important limitation:
  - Screenshot proof is still required before checking off the remaining banner rows in the full-page audit.
- Exact next action:
  - Regenerate current-app screenshots and verify banner removal and Stewardship badge visibility across the affected pages.

### Checkpoint - Shared Badge And Banner Screenshot Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-shared-banner-badge-local/`.
  - Capture report: `32` expected captures, `32` captured, `0` page errors, `0` request failures.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-shared-banner-badge-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` screenshot paths.
  - Checked off only the rows proven by screenshots: Stewardship badge visible in the shell, Home prototype-mock banner removed, and Glossary/CDE `Data availability is limited` banner removed.
- Current open gap count:
  - `278` open gaps: Command Center `39`, Discover `50`, Stewardship `32`, Glossary `30`, CDE Registry `26`, Lineage Atlas `36`, Audit Evidence `29`, Control Center `22`, Cross-Page Shared `14`.
- Remaining related blockers:
  - Control Center still shows a prototype-mock warning banner in the page body.
  - Lineage still has its degraded refresh banner shape open.
  - The global AI rail is present but still not visually/functionally signed off.
- Exact next action:
  - Run the audit-contract guard and diff hygiene, then continue with the next visible page-body blocker instead of making any signoff claim.

### Checkpoint - Shared Badge And Banner Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/reference_manifest.json frontend/src/App.jsx frontend/src/lib/api.js frontend/src/lib/api.metadataContract.test.js frontend/src/components/HomePage.jsx frontend/src/components/HomePage.test.jsx frontend/src/components/AppFrame.test.jsx frontend/src/components/northstar/DegradedBanner.jsx frontend/src/components/northstar/DegradedBanner.test.jsx` -> passed.
- Exact next action:
  - Remove or restyle the remaining unmocked prototype-mock warning banner in Control Center without hiding real degraded runtime warnings, then validate with tests and screenshots.

### Checkpoint - Control Center Prototype Warning Patch Started

- Target:
  - Remove the Control Center page-body prototype-mock provenance banner from local prototype screenshots because the reference page has no such banner and the non-live provenance is already labeled in the shell/AI evidence context.
  - Preserve real degraded runtime warnings in the Control Center body.
- Current blocker:
  - `AdminWorkspace` code filters prototype-mock warnings, but the first targeted test used a `rerender` pattern that did not reliably force a fresh query for the second warning payload.
- Exact next action:
  - Repair the test to render prototype-mock and real-warning scenarios independently, then rerun the targeted Control Center suite.

### Checkpoint - Control Center Prototype Warning Unit Validation Passed

- Implemented:
  - `AdminWorkspace` now filters prototype-mock/non-live provenance warnings out of the Control Center body while preserving real degraded runtime warnings.
  - The Control Center warning test now renders prototype-mock and real-warning scenarios independently so each query reads the intended mocked payload.
- Validation:
  - `npm run test -- src/components/AdminWorkspace.test.jsx` from `frontend/` -> passed, `1` file, `6` tests.
- Important limitation:
  - This proves component behavior only. The Control Center row in `full_page_audit.md` cannot be checked off until fresh browser screenshots prove the page-body banner is gone in the rendered app.
- Exact next action:
  - Regenerate current-app Playwright screenshots and inspect `control-center-3037x1269.png`.

### Checkpoint - Control Center Prototype Warning Screenshot Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-control-warning-local/`.
  - Capture result: `32` expected captures, `32` captured, `0` page errors, `0` request failures.
  - Visual inspection of `control-center-3037x1269.png` confirms the page-body prototype-mock warning banner is gone while the shell still labels the evidence as prototype mock/non-live.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-control-warning-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` screenshot paths and checked off only the Control Center warning-banner row proven by the screenshot.
- Current open gap count:
  - `277` open gaps: Command Center `39`, Discover `50`, Stewardship `32`, Glossary `30`, CDE Registry `26`, Lineage Atlas `36`, Audit Evidence `29`, Control Center `21`, Cross-Page Shared `14`.
- Important limitation:
  - This does not sign off Control Center. It removes one layout-distorting banner only; the page still has visual, functional, and truth/provenance gaps.
- Exact next action:
  - Run the audit-contract guard and scoped diff hygiene, then continue with the next first-viewport blocker.

### Checkpoint - Control Center Prototype Warning Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/reference_manifest.json frontend/src/components/AdminWorkspace.jsx frontend/src/components/AdminWorkspace.test.jsx` -> passed.
- Next implementation lanes:
  - Local lane: Lineage Atlas first-viewport degraded-banner/card shape, because it visibly pushes the graph away from the prototype.
  - Subagent lanes: disjoint page/workflow slices for Command Center, Discover, and workflow pages, with findings required before any signoff.

### Checkpoint - Parallel Page Lanes Started

- Active subagent work:
  - Worker A `019dd8f0-9da8-7990-b6d7-708405aa26b3`: Command Center/Home ownership.
  - Worker B `019dd8f1-0436-7c73-ae87-b05324173232`: Discover ownership.
  - Worker C `019dd8f3-19a9-7df1-9479-c6f213f3587e`: Stewardship + Glossary/CDE ownership.
  - Worker D `019dd8f3-ae90-7f22-a595-cfb99d74af7c`: Audit Evidence + Control Center ownership.
- Local work:
  - Continue with Lineage Atlas because the degraded warning/card shape is page-specific and currently not assigned to another writer.
- Guardrail:
  - No subagent may claim signoff; their findings and patches must be reviewed, tested, and screenshot-validated before any ledger rows are checked off.

### Checkpoint - Lineage Degraded Banner Patch Started

- Target:
  - Remove the Lineage Atlas page-body degraded warning banner from the full North Star route because the prototype has no banner above the graph and the current banner pushes the graph out of first-viewport alignment.
  - Preserve truthful degraded/refresh information as compact graph/status metadata instead of hiding it.
- Exact next action:
  - Patch `LineageStage` full-route rendering only; embedded Asset 360 lineage keeps its existing warning behavior.

### Checkpoint - Lineage Degraded Banner Unit Validation Passed

- Implemented:
  - Full-route `LineageStage` no longer renders `Lineage refresh degraded` or provisional refresh states as full-width `InlineStatusBanner` rows above the graph.
  - Degraded refresh state is preserved as compact graph legend/status metadata.
  - Embedded lineage keeps its existing warning-banner path.
- Validation:
  - `npm run test -- src/components/LineageStage.test.jsx` from `frontend/` -> passed, `1` file, `5` tests.
- Important limitation:
  - This does not close the visual gap until fresh current screenshots prove the beige banner is absent from `lineage-3037x1269.png`.
- Exact next action:
  - Regenerate prototype-mock screenshots and inspect the Lineage page.

### Checkpoint - Lineage Degraded Banner Screenshot Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-lineage-banner-local/`.
  - Capture result: `32` expected captures, `32` captured, `0` page errors, `0` request failures.
  - Visual inspection of `lineage-3037x1269.png` confirms the beige `LINEAGE REFRESH DEGRADED` page-body banner is gone; refresh degradation appears as a compact graph legend/status note.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-lineage-banner-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` screenshot paths and checked off only the Lineage degraded-banner row proven by the screenshot.
- Current open gap count:
  - `276` open gaps: Command Center `39`, Discover `50`, Stewardship `32`, Glossary `30`, CDE Registry `26`, Lineage Atlas `35`, Audit Evidence `29`, Control Center `21`, Cross-Page Shared `14`.
- Important limitation:
  - This does not sign off Lineage. The graph still does not match the prototype and the degraded placeholder card remains open.
- Exact next action:
  - Run the audit-contract guard and scoped diff hygiene, then continue with the next visible Lineage graph-shape blocker or integrate completed worker patches.

### Checkpoint - Lineage Degraded Banner Guard Passed

- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/full_page_audit.md docs/northstar_gap_analysis/reference_manifest.json frontend/src/components/LineageStage.jsx frontend/src/components/LineageStage.test.jsx` -> passed.
- Exact next action:
  - Continue locally on the Lineage graph placeholder/overlay shape unless a subagent worker finishes first with a clean disjoint patch.

### Checkpoint - Worker B/C Integration Review Started

- Completed worker reports received:
  - Worker B `019dd8f1-0436-7c73-ae87-b05324173232`: Discover selected preview overlay/tabs/actions and grid/list state.
  - Worker C `019dd8f3-19a9-7df1-9479-c6f213f3587e`: Stewardship filter/unavailable write panels and Glossary/CDE detail panels.
- Guardrail:
  - Worker reports are not signoff. Their changes must be reviewed in the combined worktree, rerun locally, screenshot-captured, and mapped back to `full_page_audit.md` before any gap is checked off.
- Exact next action:
  - Inspect diffs for the worker-owned files and rerun their focused tests.

### Checkpoint - Worker B/C Focused Integration Tests Passed

- Reviewed:
  - Confirmed Worker B/C edits are present in the shared worktree.
  - Worker B changes affect Discover preview overlay/tabs/footer actions and display-mode state.
  - Worker C changes affect Stewardship filter/unavailable write panels and Glossary/CDE detail workflows.
- Validation:
  - `npm run test -- src/components/DiscoveryWorkspace.test.jsx src/hooks/useDiscoveryResults.test.jsx src/components/GovernanceWorkspace.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx src/components/LineageStage.test.jsx` from `frontend/` -> passed, `6` files, `68` tests.
- Important limitation:
  - No rows are checked off yet. These tests prove focused interaction behavior only; visual rows require fresh screenshot evidence, and backed/live workflow rows remain open unless explicitly validated.
- Exact next action:
  - Capture fresh current screenshots including the Discover selected overlay state and inspect before updating the audit ledger.

### Checkpoint - Worker A/B/C Screenshot Evidence Promoted

- Evidence:
  - Captured all screenshot-backed `northstar/*` routes plus Discover selected overlay states at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-worker-bc-local/`.
  - Capture result: `32` static captures plus Discover interaction captures, `0` page errors, `0` request failures.
- Implemented:
  - Promoted `docs/northstar_visual_qa/prototype-current-worker-bc-local/` as the current evidence directory in `docs/northstar_gap_analysis/reference_manifest.json`.
  - Checked off only screenshot/test-backed rows for Command Center narrative/provenance/trend shape, Discover selected-overlay structure, and CDE `Source-of-record column` label.
- Current open gap count:
  - `262` open gaps: Command Center `34`, Discover `42`, Stewardship `32`, Glossary `30`, CDE Registry `25`, Lineage Atlas `35`, Audit Evidence `29`, Control Center `21`, Cross-Page Shared `14`.
- Important limitation:
  - These screenshots predate Worker D's final Audit/Control changes. Audit/Control rows remain open until new screenshots are captured and reviewed.

### Checkpoint - Worker D Integration Review Started

- Completed worker report received:
  - Worker D `019dd8f3-ae90-7f22-a595-cfb99d74af7c`: Audit Evidence date range/filter counts/row detail/export provenance and Control Center diagnostic detail/copy changes.
- Worker D reported validation:
  - `npm run test -- src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx` -> passed, `13` tests.
  - `npm run northstar:audit-contract` -> passed.
  - `git diff --check` on touched files -> passed.
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed; app URL reported as not deployed.
- Guardrail:
  - Worker D did not capture screenshots and did not claim signoff. Rerun the targeted tests in the combined worktree and then capture current evidence before checking off any Audit/Control rows.

### Checkpoint - Full Page Audit Enforcement Continuation Started

- Trigger:
  - User rejected the prior visual signoff and required the homepage-level critical comparison to be applied to every `northstar/*` page.
  - User required rules-of-engagement hardening so capture-health, stale screenshots, or reviewer memory cannot be mistaken for visual or functional completion again.
- Current state:
  - `docs/northstar_gap_analysis/full_page_audit.md` remains the blocking ledger for all pages.
  - `docs/northstar_gap_analysis/reference_manifest.json` still points its global current evidence to `docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final`, which is stale for the newest local changes and must be refreshed before renewed page review.
  - Fresh local prototype-mock evidence exists under `docs/northstar_visual_qa/prototype-current-tranche1-local`, but it is not yet promoted in the manifest and is not visual signoff.
  - A failed deployed capture under `docs/northstar_visual_qa/prototype-current-tranche1` hit the Databricks login page and is invalid for visual parity evidence.
- Planned changes:
  - Run a fresh validation baseline against the current dirty tree.
  - Capture current app states, including interaction states such as Discover selected asset preview, at the prototype viewport.
  - Update the audit ledger only for gaps proven fixed by current screenshots or tests; leave all other gaps open.
- Validation target:
  - Focused frontend suites for recently touched components.
  - `npm run typecheck`
  - `npm run northstar:audit-contract`
  - Playwright current-app captures with explicit evidence-kind labeling.

### Checkpoint - Full Page Audit Enforcement Baseline Validated

- Validation:
  - `npm run typecheck` from `frontend/` -> passed.
  - `npm run northstar:audit-contract` from `frontend/` -> passed against the current manifest and ledger.
  - `npm run test -- src/components/DiscoveryWorkspace.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx src/components/AppFrame.test.jsx src/hooks/useDiscoveryResults.test.jsx src/hooks/useLineage.test.jsx` -> passed, `7` files, `70` tests.
  - Scoped `git diff --check` for the current rules/status/provenance/UI files -> passed.
- Important limitation:
  - This is only static/unit/ledger validation. It does not reduce any visual gap count and does not sign off any page.
- Exact next action:
  - Regenerate current-app browser screenshots and interaction evidence for every `northstar/*` page before editing more visual parity gaps.

### Checkpoint - Fresh Current-App Prototype Capture Completed

- Evidence:
  - Captured all standalone `northstar/*` routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720` into `docs/northstar_visual_qa/prototype-current-continuation-local/`.
  - Capture report: `32` captures expected, `32` captured, `0` page errors, `0` request failures.
  - Evidence kind is `prototype_mock` with warning: `Prototype mock data, not live Databricks evidence.`
- Important limitation:
  - This is current local browser evidence only. It is not deployed/live Databricks evidence and not visual signoff.
  - Static route captures do not cover interaction states such as Discover selected asset preview, selected queue rows, drawer actions, or AI chat interactions.
- Exact next action:
  - Add scripted interaction captures for the prototype selected/drawer/control states so the page audits can be closed by actual UI evidence rather than first-load screenshots.

### Checkpoint - Discover Selected-State Evidence Added

- Implemented:
  - Added optional `GOVAT_PROTOTYPE_INTERACTIONS=1` interaction capture support to `frontend/scripts/atlas_prototype_current_capture.mjs`.
  - Added a Discover selected-result interaction that clicks the first result and captures the asset preview pane.
- Evidence:
  - `docs/northstar_visual_qa/prototype-current-continuation-interactions/discover-selected-3037x1269.png`
  - `docs/northstar_visual_qa/prototype-current-continuation-interactions/discover-selected-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-current-continuation-interactions/discover-selected-1440x900.png`
  - `docs/northstar_visual_qa/prototype-current-continuation-interactions/discover-selected-1280x720.png`
  - Interaction report loaded `finance_prod.curated.revenue_daily` and exposed preview controls: close, `Open Asset 360`, `Lineage unavailable`, and `Start Stewardship Review`.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Interaction capture report -> passed with `4` route captures, `4` interaction captures, `0` page errors, and `0` request failures.
- Important limitation:
  - This closes evidence collection for Discover selected-state existence only. It does not prove visual equivalence or functional completion for the selected preview controls.
- Exact next action:
  - Delegate/currently run side-by-side visual, functional, and truth review against the fresh screenshots and update the materialized audit ledger with only evidence-backed changes.

### Checkpoint - Fresh Screenshot Subagent Audit Started

- Delegated review lanes:
  - Command Center and Discover visual fidelity against `prototype_home1.png`, `prototype_home2.png`, `prototype_discover1.png`, and `prototype_discover2.png`.
  - Stewardship, Glossary, and CDE Registry visual fidelity against `prototype_stewardship1.png`, `prototype_glossary1.png`, and `prototype_stewardship2.png`.
  - Lineage Atlas, Audit Evidence, and Control Center visual fidelity against `prototype_lineage.png`, `prototype_audit1.png`, and `prototype_cc.png`.
  - Cross-page functional workflow and truth/provenance review against current screenshots and code paths.
- Reviewer instructions:
  - No file edits.
  - No signoff from capture success.
  - Identify gaps already present in `full_page_audit.md` separately from newly discovered missing gaps.
- Status:
  - Reviews are running and are expected to block signoff until their findings are incorporated or explicitly deferred with rationale.

### Checkpoint - Fresh Screenshot Subagent Audit Materialized

- Reviewer outcome:
  - Command Center / Discover visual reviewer: blocked signoff.
  - Stewardship / Glossary / CDE Registry visual reviewer: blocked signoff.
  - Lineage / Audit Evidence / Control Center visual reviewer: blocked signoff.
  - Functional workflow and truth/provenance reviewer: blocked signoff.
- Implemented:
  - Updated `docs/northstar_gap_analysis/full_page_audit.md` to use fresh current evidence paths.
  - Checked off only stale rows disproven by fresh screenshots or code review.
  - Added newly identified blockers for missing/open AI rail states, disabled-looking topbar AI, missing Stewardship badge, disruptive prototype-mock banners, Discover selected-drawer shape, Lineage degraded-card shape, Audit table/footer imbalance, Control Center compressed job columns, and mock provenance in artifacts/claims.
  - Updated page summary counts from the ledger parser.
- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - Scoped `git diff --check` for status/audit/manifest/capture files -> passed.
- Current open gap count:
  - `298` open gaps: Command Center `44`, Discover `53`, Stewardship `34`, Glossary `32`, CDE Registry `28`, Lineage Atlas `37`, Audit Evidence `30`, Control Center `23`, Cross-Page Shared `17`.
- Exact next action:
  - Start implementation with the highest-ripple shared blocker: make prototype-mock visual evidence preserve the prototype AI rail layout without making mock evidence look live or authoritative.

### Checkpoint - Process And Truth Gate Repair Started

- Trigger:
  - Process review found stale signoff language and a weak audit guard.
  - Truth/provenance review found mock API payloads reporting `authoritative=true` / `state=ready` while using `source=local-prototype-mock`.
- Planned changes:
  - Mark this file's current status as reopened and blocking at the top so later historical signoff entries cannot be mistaken for current state.
  - Add cross-page shared gaps to the machine-checked audit summary.
  - Strengthen `scripts/check_northstar_audit_contract.py` to verify required screenshot evidence and stale signoff supersession.
  - Make prototype mock capture payloads explicitly non-authoritative with `state=prototype_mock` and warning copy.
- Validation target:
  - `npm run northstar:audit-contract`
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - focused tests for affected provenance surfaces after UI/capture changes

### Checkpoint - Process And Truth Gate Repair Validated

- Implemented:
  - Marked all prior North Star signoff language as superseded at the top of this file.
  - Added a cross-page shared gap row to `docs/northstar_gap_analysis/full_page_audit.md`.
  - Strengthened `scripts/check_northstar_audit_contract.py` so stale signoff language, missing screenshot evidence, or missing supersession state fails the guard.
  - Converted prototype capture mock payloads to `state=prototype_mock`, `authoritative=false`, and warning-labeled local evidence.
  - Tightened Discovery, Lineage, and Audit provenance handling so `local-prototype-mock` evidence cannot be treated as live authoritative Databricks evidence.
  - Preserved ordinary live lineage API payloads as authoritative unless explicitly marked false or prototype mock.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - `npm run test -- src/hooks/useDiscoveryResults.test.jsx src/hooks/useLineage.test.jsx src/components/AuditBrowserWorkspace.test.jsx` -> passed, `3` files, `13` tests.
  - Scoped `git diff --check` for the process/truth files -> passed.
- Exact next action:
  - Start the first visual/functionality repair tranche from the materialized audit list, beginning with high-confidence page-shape blockers that do not require backend architecture changes.

### Checkpoint - Cross-Page Visual And Functional Repair Tranche Started

- Scope:
  - Remove or restyle unmocked first-viewport raw detail sections that make Glossary, CDE Registry, and Audit Evidence diverge from the prototype.
  - Fix Control Center policy coverage row styling so unavailable/live policy bars preserve the prototype rhythm instead of rendering gray utility rows.
  - Re-check AI rail/default-open behavior, page density, and control affordances after the first patch set.
- Guardrails:
  - Preserve truthful unavailable/degraded states rather than inventing workflow counters, lineage, tasks, quality, or control coverage.
  - Keep existing future Asset 360 and older-page work intact unless it blocks the active `northstar/*` prototype pages.
  - Do not claim visual or functional completion from smoke captures alone.
- Parallel review roles requested:
  - Visual fidelity and product structure reviewer.
  - Functional workflow reviewer.
  - Truth/provenance reviewer.
  - Regression/ripple reviewer.
- Validation target:
  - Focused component tests for modified pages.
  - North Star audit-contract guard.
  - Fresh Playwright capture after patches.
  - Subagent findings incorporated, rejected with rationale, or explicitly deferred before any signoff language is used.

### Checkpoint - Cross-Page Visual And Truth Patch Set 1 Validated

- Implemented:
  - Removed visible raw/debug-style selected detail panels from the prototype Glossary, CDE Registry, and Audit Evidence first-viewport layouts while preserving screen-reader detail context.
  - Added CDE row key-style affordances and hid prototype count helper text from the visual layout.
  - Reset Control Center policy coverage rows to prototype dark-row styling and disabled unavailable policy rows instead of rendering clickable `0%`-style controls.
  - Stopped `prototype_mock` bootstrap state from becoming shell `live`.
  - Labeled mock AI, asset availability, and capture report evidence as prototype mock / runtime capture instead of live Databricks evidence.
  - Narrowed Audit Evidence copy from append-only claims to source-scoped audit evidence, and added authoritative/mock flags to generated report payloads.
  - Preserved live lineage authority while retaining local/mock source provenance.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run test -- src/components/TaxonomyWorkspace.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx src/hooks/useLineage.test.jsx src/hooks/useAtlasAiConversation.test.jsx src/components/AppFrame.test.jsx` -> passed for existing files, `5` files, `30` tests. `useAtlasAiConversation.test.jsx` is not present in this checkout.
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
  - Scoped `git diff --check` for touched files -> passed.
- Reviewer findings still open:
  - Discover selected asset preview is hidden by prototype CSS and must be restored.
  - Atlas AI open/closed visual matrix still needs deterministic Playwright evidence.
  - Functional QA scripts are stale against active `northstar/*` routes.
  - Control Center row iconography and Audit action iconography still trail the prototype.

### Checkpoint - Focused Regression Repair Started

- Trigger: recovered context showed partial subagent patches landed for Command Center, shell/AI, Taxonomy/CDE, Lineage, Audit, and Control Center, with focused page tests failing afterward.
- Scope for this checkpoint:
  - Re-run the isolated failing frontend suites because prior process IDs were not resumable after context compaction.
  - Fix only confirmed regressions in test hygiene, component behavior, or truthful prototype workflow support.
  - Preserve all existing dirty worktree changes unless a failure proves one is incorrect.
- Validation target:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx src/components/LineageStage.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx`
  - `npm run typecheck`
  - `npm run northstar:audit-contract`
  - scoped `git diff --check`
- Risk:
  - The worktree contains many unrelated deletions and generated screenshot artifacts; this checkpoint will not attempt cleanup or reversion.

### Checkpoint - Focused Page Regression Tests Passed

- Implemented:
  - Reset Taxonomy/CDE URL state in tests so URL-backed tab persistence does not leak across isolated cases.
  - Scoped Audit and Taxonomy assertions to the table/card regions now that selected-detail panels intentionally duplicate row titles.
  - Aligned Control Center tests with prototype-shaped unavailable rows and truthful selection messages.
  - Aligned Audit action tests with local metadata-only export/report artifact behavior.
- Validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx src/components/LineageStage.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx` -> passed, `5` files, `23` tests.
- Exact next action:
  - Run frontend typecheck, North Star audit-contract guard, and scoped diff hygiene before returning to Playwright visual/functional inspection.

### Checkpoint - Static Guards Passed After Regression Repair

- Validation:
  - `npm run typecheck` -> passed.
  - `npm run northstar:audit-contract` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/components/TaxonomyWorkspace.test.jsx frontend/src/components/AuditBrowserWorkspace.test.jsx frontend/src/components/AdminWorkspace.test.jsx` -> passed.
- Exact next action:
  - Run current-app Playwright captures against the screenshot-backed `northstar/*` route set and use the resulting screenshots for true page-by-page comparison, not capture-health signoff.

### Checkpoint - Fresh Local North Star Capture Started

- Trigger: local Vite was not running on `127.0.0.1:3000`; browser evidence must be regenerated after the focused repairs before any visual or functional claims.
- Planned action:
  - Start the local frontend server.
  - Capture all screenshot-backed prototype routes in mock-API mode at native `3037x1269` viewport into a fresh evidence directory.
  - Inspect screenshots against `northstar/screenshots/*` and update the audit ledger with concrete remaining gaps before more UI edits.
- Validation target:
  - Capture report with no route failures, request failures, page errors, console errors, or horizontal overflow.

### Checkpoint - Scoped Subagent Page Pass Started

- Scope owner: Glossary/CDE Registry, Lineage Atlas, Audit Evidence, and Control Center only.
- Files in scope:
  - `frontend/src/components/TaxonomyWorkspace.jsx`
  - `frontend/src/components/LineageStage.jsx`
  - `frontend/src/components/LineageWorkspace.jsx` / `LineageGraph.jsx` only if required for scoped lineage behavior
  - `frontend/src/components/AuditBrowserWorkspace.jsx`
  - `frontend/src/components/AdminWorkspace.jsx`
  - related page tests and page-local styles
- Explicit non-scope:
  - shared shell/topbar/AI rail
  - Home/Command Center
  - Discover
  - Stewardship
- Completed before implementation:
  - Read `AGENTS.md`, `docs/northstar_gap_analysis/reference_manifest.json`, and the scoped sections of `docs/northstar_gap_analysis/full_page_audit.md`.
  - Historical note superseded on 2026-04-30: `.claude/skills/*` resolves through symlinks in this checkout; use `find -L .claude/skills` before judging skill availability.
  - Confirmed the worktree is already heavily dirty, including shared shell/backend changes that must be preserved.
- Planned edits:
  - Preserve prototype shape for Glossary/CDE rows and reconcile visible counts.
  - Add concrete row/detail/action feedback for Glossary/CDE without inventing backend state.
  - Improve Lineage unavailable/empty graph shape and replace status-only controls with truthful disabled/download/action behavior where possible.
  - Make Audit Evidence actions either produce backed artifacts or truthful local artifacts, add row detail, and preserve prototype footer/table shape.
  - Fix Control Center truth bugs around null policy coverage and preserve prototype rows with truthful unavailable placeholders.
- Validation target:
  - Scoped frontend tests for Taxonomy/CDE, LineageStage, AuditBrowserWorkspace, and AdminWorkspace.
  - `git diff --check` on touched files.

### Checkpoint - Command Center Owner Pass Started

- Trigger: user assigned this lane to Command Center/homepage only and required exact North Star parity against `northstar/screenshots/prototype_home1.png` and `northstar/screenshots/prototype_home2.png`.
- Scope guard:
  - Owned files for this pass: `frontend/src/components/HomePage.jsx`, `frontend/src/hooks/useCommandCenter.js`, `frontend/src/components/HomePage.test.jsx`, `frontend/src/hooks/useCommandCenter.test.jsx`, and page-local CSS selectors in existing CSS.
  - Avoid shared shell/AI files unless a homepage prop/class hook is required.
  - Preserve all unrelated dirty worktree changes.
- Read before editing:
  - `AGENTS.md`
  - `IMPLEMENTATION_STATUS.md`
  - `docs/northstar_gap_analysis/full_page_audit.md` Command Center section
  - `docs/northstar_gap_analysis/reference_manifest.json`
  - `northstar/pages/exec.jsx`
  - `northstar/screenshots/prototype_home1.png`
  - `northstar/screenshots/prototype_home2.png`
  - current deployed comparison screenshot: `docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final/command-center-3037x1269.png`
- Planned implementation:
  - Tighten first-viewport density and header/live-status rhythm.
  - Preserve prototype regions under unavailable data instead of sparse empty blocks.
  - Add prototype-shaped KPI sparkline/delta, coverage trend, domain, risk, catalog, CDE, and activity degraded states.
  - Keep export, present mode, range, catalog, CDE, and activity controls functional or truthfully unavailable.
- Validation target:
  - Focused homepage and hook tests.
  - Diff hygiene for touched files.
  - Local Command Center screenshot capture if the test gate passes.

## Active Tranche - Prototype North Star Rebase

- New active contract: `/Users/entrada-mac/repos/governance_atlas/northstar/Governance Atlas.html` and screenshots under `northstar/screenshots/*`.
- Current owner clarification: the active prototype scope is the `northstar/*` product, not the older Home/Asset 360 mockup set. Asset 360 work is preserved in the repo for possible future reuse, but it is not part of the current prototype signoff because no Asset 360 screenshot exists under `northstar/screenshots/`.
- Required scope:
  - Decompose every prototype page into explicit visual and functional checklist items before page edits.
  - Compare the current app with Playwright screenshots at matching/nearest viewports.
  - Bring the app as close as practical to the prototype while preserving Unity Catalog, Databricks Apps, Genie, Lakebase, actor-permission, and no-fake-state constraints.
  - Validate every button/control/workflow end to end with seeded customer-style data in the `DEFAULT` workspace where needed.
  - Require multiple subagent review lanes before any page signoff: feedback coverage, visual fidelity/product structure, truth/provenance, functional workflow/regression/ripple.

### Checkpoint - Re-Scoped Continuation Started

- Trigger: user clarified that the new North Star lives under `northstar/*` and that Asset 360 is not part of this prototype. The active goal is exact-or-better parity with the prototype screenshots and behavior, with unanimous subagent review before signoff.
- Prototype files confirmed:
  - `northstar/Governance Atlas.html`
  - `northstar/app.jsx`, `northstar/pages/*.jsx`, `northstar/components/*.jsx`, `northstar/styles/*.css`, `northstar/data/mock.js`
  - screenshots: `prototype_home1.png`, `prototype_home2.png`, `prototype_discover.png`, `prototype_stewardship1.png`, `prototype_stewardship2.png`, `prototype_glossary1.png`, `prototype_lineage.png`, `prototype_audit1.png`, `prototype_cc.png`
  - Genie/Lakebase/live validation artifacts under `northstar/genie/` and hardening artifacts under `northstar/hardening/`
- Completed in this checkpoint:
  - Confirmed the stale Asset 360 capture session is not running.
  - Confirmed the repo tracker already contains earlier Command Center, Stewardship, Glossary/CDE, Lineage, Audit, Control Center, and Atlas AI dock work.
- Pending immediate work:
  - Read and summarize all `northstar/*` implementation files and screenshots into a fresh prototype contract checklist.
  - Remove Asset 360 from the current capture/signoff route set while preserving existing code.
  - Re-run current app Playwright captures only for the prototype routes.
  - Address remaining visual/functional gaps found by screenshot comparison and subagent reviewers.
- Validation status:
  - No new validation has run after this re-scope.
- Risks:
  - Prior all-route harness still includes Asset 360 by default; that can waste time and produce irrelevant failures unless narrowed.
  - Existing app surfaces may be broader than the prototype; parity work should keep that code available but avoid exposing non-prototype surfaces as required signoff gates.

### Checkpoint - Prototype Contract Reconciled With Screenshot Scope

- Implemented:
  - Updated `docs/northstar_gap_analysis/prototype_contract.md` so Asset 360 is explicitly classified as a supporting drawer/workflow, not a standalone current visual signoff page.
  - Kept the Asset 360 truth/functionality requirements for routes that open asset context from Discover, Stewardship, Lineage, Command Center, or Atlas AI evidence.
- Validation:
  - No runtime validation needed for this documentation-only scope correction.
- Exact next action:
  - Redirect the review lanes to the corrected prototype scope and run a narrowed Playwright capture that excludes standalone Asset 360 route validation.

### Checkpoint - Prototype Capture Route Scope Fix Started

- Trigger: `frontend/scripts/atlas_prototype_current_capture.mjs` still includes `asset360` in the default route set, even though the current screenshot-backed North Star excludes a standalone Asset 360 page.
- Planned edit:
  - Split screenshot-backed routes from supporting routes.
  - Make the default all-route capture cover only Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, and Control Center.
  - Preserve explicit `GOVAT_PROTOTYPE_ROUTES=asset360` support for drawer/entity workflow debugging.
- Planned validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - `git diff --check frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/prototype_contract.md`
  - run narrowed mock-API Playwright capture.

### Checkpoint - Prototype Capture Route Scope Fix Validated

- Implemented:
  - Split `SCREENSHOT_ROUTES` from `SUPPORTING_ROUTES` in `frontend/scripts/atlas_prototype_current_capture.mjs`.
  - Default captures now exclude `asset360`; `GOVAT_PROTOTYPE_ROUTES=asset360` still works for supporting drawer/entity workflow debugging.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/prototype_contract.md` -> passed.
- Exact next action:
  - Run the narrowed screenshot-backed local Playwright mock-API capture and inspect the report for request/page/console failures and layout overflows.

### Checkpoint - Local Prototype Capture Started

- Trigger: local Vite server was not running on `127.0.0.1:3000`.
- Planned action:
  - Start the frontend Vite server locally.
  - Run the default screenshot-backed capture set with `GOVAT_PROTOTYPE_MOCK_API=1`.
  - Inspect current app evidence against the `northstar/screenshots/*` contract before additional implementation.
- Validation target:
  - Capture report has no route failures, request failures, page errors, console errors, or horizontal overflow.

### Checkpoint - Screenshot-Backed Capture Completed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-screenshot-backed ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-screenshot-backed/prototype-current-report.json`
  - 24 screenshots across Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, and Control Center at `1536x1024`, `1440x900`, and `1280x720`.
- Report result:
  - no request failures
  - no page errors
  - no console errors
  - `mockApi=true`
- Manual inspection finding:
  - The default 1536-wide Command Center capture is not a direct visual-comparison frame for the 3037x1269 prototype screenshots. The current open Atlas AI dock consumes horizontal room immediately, causing the hero/title to wrap and the app to look narrower than the reference.
- Exact next action:
  - Add an explicit viewport override to the capture script and capture at the prototype's native `3037x1269` dimensions before deciding whether the app needs layout changes or only comparison-frame changes.

### Checkpoint - Truth/Provenance Blocker Fix Started

- Trigger: truth/provenance review blocked signoff after the corrected `northstar/*` scope review.
- Blocking findings to fix before visual/product signoff:
  - `frontend/src/components/LineageStage.jsx`: production fallback lineage chips/impact/column rows overclaim owner, certification, freshness, impact, and `system.access.column_lineage` provenance.
  - `frontend/src/components/AuditBrowserWorkspace.jsx`: prototype audit copy and defaults overclaim retention, deltas, report/export readiness, cryptographic ordering, SOC/SOX export, and fixed `governance_state.audit_log` backing.
  - `frontend/src/components/AdminWorkspace.jsx`: Control Center copy and policy defaults overclaim available policy/integration/job state when live payloads are unavailable.
  - `frontend/src/components/GovernanceWorkspace.jsx`: `Assigned to me` filtering/counting uses hardcoded names, creating synthetic workflow-count risk.
- Planned implementation:
  - Replace overclaimed production fallbacks with explicit unavailable/degraded states unless backed data is present.
  - Keep mock-API visual evidence rich only when `GOVAT_PROTOTYPE_MOCK_API=1`.
  - Tie `Assigned to me` to the actual signed-in user identity or disable/degrade the filter when identity cannot be matched.
- Planned validation:
  - Focused tests for Lineage, Audit, Admin, and Governance.
  - `npm run lint -- --quiet`
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - narrowed Playwright capture after fixes.

### Checkpoint - Truth/Provenance Test Alignment Started

- Trigger: the first focused validation after removing fabricated fallback claims failed because tests still expected old report/export success copy and old Control Center marketing copy.
- Planned edit:
  - Align Audit Evidence tests with truthful unavailable report/export backend states.
  - Align Control Center tests with the narrower runtime diagnostics copy.
  - Add a Governance Workbench regression guard so `Assigned to me` is based on the signed-in user identity instead of hardcoded names.
- Planned validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx src/components/GovernanceWorkspace.test.jsx`
  - `git diff --check` for the changed component/test/status files.

### Checkpoint - Regression Reviewer Blockers Incorporated

- Trigger: functional/regression review blocked corrected-scope signoff.
- Additional blockers now in scope:
  - Typecheck regression from stale `NorthStarLineageExplorer` props in `LineageStage.jsx`.
  - Brittle `App.test.jsx` `88%` assertion.
  - Governance no-evidence wording and hardcoded fallback detail.
  - Runtime contract tests failing because `runtime_manifest.yaml` and `docs/runtime_api_openapi_snapshot.json` are deleted.
  - Audit `Date range` control not wired into the query key/API request.
  - Audit KPI support copy still hardcoded rather than payload-backed or unavailable.
- Validation gate expanded:
  - focused frontend tests above
  - relevant `App.test.jsx` route test
  - frontend typecheck
  - backend runtime contract pytest subset that reported deleted contract files
  - `npm run lint -- --quiet`
  - `git diff --check`

### Checkpoint - Truth/Regression Focused Tests Passed

- Implemented:
  - Removed stale full-surface Lineage props that caused typecheck failures.
  - Stopped Stewardship Workbench from defaulting missing detail to synthetic `Awaiting governance review.` copy.
  - Wired Audit Evidence `dateRange` into the React Query key and API request.
  - Replaced audit action success claims with truthful unavailable-backend messages.
  - Restored `runtime_manifest.yaml` and regenerated `docs/runtime_api_openapi_snapshot.json`.
  - Added regression coverage for signed-in-user-based `Assigned to me` counts.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx src/components/GovernanceWorkspace.test.jsx src/App.test.jsx` -> passed, `5` files, `49` tests.
- Exact next action:
  - Run typecheck, backend runtime contract tests, lint, and diff hygiene before refreshed Playwright evidence.

### Checkpoint - Runtime Gate Pass With Typecheck Follow-Up

- Validation:
  - `.venv/bin/python -m pytest tests/test_runtime_route_serving.py tests/test_runtime_api_contracts.py` -> passed, `34` tests.
  - `npm run lint -- --quiet` -> passed.
  - scoped `git diff --check` -> passed.
  - `npm run typecheck` -> failed on JavaScript type inference only: audit `text()` fallback arity and `normalizeCurrentUser()` object property typing.
- Follow-up implemented:
  - Allowed `text(value, fallback)` in `AuditBrowserWorkspace.jsx`.
  - Annotated the local current-user object shape in `GovernanceWorkspace.jsx`.
- Exact next action:
  - Re-run typecheck and the focused frontend tests touched by the type fixes.

### Checkpoint - Typecheck Follow-Up Passed

- Validation:
  - `npm run typecheck` -> passed.
  - `npm test -- --run src/components/AuditBrowserWorkspace.test.jsx src/components/GovernanceWorkspace.test.jsx` -> passed, `2` files, `15` tests.
  - `git diff --check -- frontend/src/components/AuditBrowserWorkspace.jsx frontend/src/components/GovernanceWorkspace.jsx frontend/src/components/AuditBrowserWorkspace.test.jsx frontend/src/components/GovernanceWorkspace.test.jsx IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Run the broader frontend regression suite and lint once more, then refresh Playwright screenshots.

### Checkpoint - Broad Frontend Regression Follow-Up Started

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm test -- --run` -> failed on `2` stale expectations:
    - Discovery parity test still expected old heading `Discover Trusted Data`; current/new prototype heading is `Find trusted, governed data`.
    - Design token test still expected old `--ga-bg: #0a263d`; current token is `#0b3451`.
- Planned edit:
  - Update tests to lock the new `northstar/*` prototype contract instead of the retired Home/Discovery mockup contract.
- Planned validation:
  - Re-run the failed tests, then the full frontend test suite.

### Checkpoint - Broad Frontend Regression Passed

- Implemented:
  - Updated the Discovery parity test to the active prototype heading `Find trusted, governed data`.
  - Updated the design-token test to lock current `--ga-bg: #0b3451`.
- Validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.identity.test.jsx src/design/tokens/tokens.test.js` -> passed, `2` files, `13` tests.
  - `npm test -- --run` -> passed, `53` files, `379` tests passed, `27` skipped.
- Exact next action:
  - Run final lint/typecheck/diff hygiene after these test-only changes, then refresh screenshot evidence.

### Checkpoint - Final Local Hygiene Gates Passed

- Validation:
  - `npm run typecheck` -> passed.
  - `npm run lint -- --quiet` -> passed.
  - scoped `git diff --check` across the changed blocker-fix/test/status files -> passed.
- Exact next action:
  - Add exact prototype viewport capture support, then run refreshed screenshot-backed Playwright capture at the prototype dimensions and standard responsive dimensions.

### Checkpoint - Glossary/CDE Wide Title Wrap Fix Started

- Trigger: manual inspection of `docs/northstar_visual_qa/prototype-taxonomy-rail-pass/glossary-3037x1269.png` against `northstar/screenshots/prototype_glossary1.png` found the shell now aligns to the wide prototype rail, but the page title still wraps onto two lines. The prototype keeps `Shared business meaning, anchored to data` on one line at the native `3037x1269` viewport.
- Planned edit:
  - Adjust only the wide-viewport taxonomy hero title rule so the heading can occupy the available prototype rail width without changing smaller viewport behavior.
- Planned validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx`
  - `git diff --check -- frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md`
  - targeted Playwright capture for `glossary,cde-registry` at `3037x1269`.

### Checkpoint - Glossary/CDE Wide Title Unit Gate Passed

- Implemented:
  - Widened and no-wrapped the taxonomy prototype hero heading only under the native/wide prototype breakpoint.
- Validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx` -> passed, `2` files, `9` tests.
  - `git diff --check -- frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `glossary,cde-registry` at `3037x1269` and inspect against `northstar/screenshots/prototype_glossary1.png`.

### Checkpoint - Glossary/CDE Native Capture Passed

- Validation:
  - `GOVAT_PROTOTYPE_ROUTES=glossary,cde-registry GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-taxonomy-title-pass/glossary-3037x1269.png`
  - `docs/northstar_visual_qa/prototype-taxonomy-title-pass/cde-registry-3037x1269.png`
- Manual inspection:
  - The wide taxonomy rail, tabs, cards/table, right AI dock, and single-line prototype title now match the `northstar/screenshots/prototype_glossary1.png` layout closely.
- Exact next action:
  - Continue route-by-route native screenshot inspection for Command Center, Lineage Atlas, Audit Evidence, and Control Center before broader recapture/signoff.

### Checkpoint - Command Center Wide Rail Fix Started

- Trigger: manual inspection of `docs/northstar_visual_qa/prototype-all-routes-native/command-center-3037x1269.png` against `northstar/screenshots/prototype_home1.png` and `prototype_home2.png` found the Command Center content still capped to the old narrow rail. The prototype uses a broader centered command rail before the right Atlas AI dock.
- Planned edit:
  - Apply the same native/wide prototype rail width to the Command Center shell and preserve existing card content.
- Planned validation:
  - focused Command Center frontend tests.
  - `git diff --check` for the touched shell/style/status files.
  - targeted `command-center` Playwright capture at `3037x1269`.

### Checkpoint - Command Center Wide Rail Unit Gate Passed

- Implemented:
  - Added a native/wide prototype breakpoint for `.gh-command-center-shell` using the shared `1544px` prototype rail and AI-dock offset variables.
- Validation:
  - `npm test -- --run src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` -> passed, `2` files, `15` tests.
  - `git diff --check -- frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `command-center` at `3037x1269` and compare with `prototype_home1.png` / `prototype_home2.png`.

### Checkpoint - Command Center Hero Column Fix Started

- Trigger: recaptured `docs/northstar_visual_qa/prototype-command-center-rail-pass/command-center-3037x1269.png` shows the shell width now matches the prototype, but the AI-open responsive rule still collapses `What changed today` below the posture hero. The prototype uses a three-column hero summary at the native width.
- Planned edit:
  - At `min-width: 2200px`, restore the posture hero to score/narrative/change columns even when the Atlas AI dock is open.
- Planned validation:
  - focused Command Center frontend tests.
  - `git diff --check -- frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md`
  - recapture `command-center` at `3037x1269`.

### Checkpoint - Command Center Hero Column Unit Gate Passed

- Implemented:
  - Restored the Command Center posture hero to score, narrative, and `What changed today` columns at the native prototype breakpoint when Atlas AI is open.
- Validation:
  - `npm test -- --run src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` -> passed, `2` files, `15` tests.
  - `git diff --check -- frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `command-center` at `3037x1269` and inspect density/column parity.

### Checkpoint - Command Center Native Capture Passed

- Validation:
  - `GOVAT_PROTOTYPE_ROUTES=command-center GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-command-center-hero-pass/command-center-3037x1269.png`
- Manual inspection:
  - The Command Center now uses the wide prototype rail, preserves the three-column posture hero, keeps four KPI cards on one row, and aligns the Atlas AI dock with the `prototype_home2.png` side-panel rhythm.
- Exact next action:
  - Inspect remaining native captures for Discover, Stewardship, Lineage, Audit, and Control Center against their reference screenshots before running the full refreshed route capture.

### Checkpoint - Lineage Native Stage Height Fix Started

- Trigger: manual inspection of `docs/northstar_visual_qa/prototype-all-routes-native/lineage-3037x1269.png` against `northstar/screenshots/prototype_lineage.png` found the Lineage Atlas graph stage is taller than the prototype, pushing the impact-analysis and column-lineage panels too low.
- Planned edit:
  - Tighten the lineage graph canvas height only at the native/wide prototype breakpoint.
- Planned validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx`
  - `git diff --check -- frontend/src/styles/lineage.css frontend/src/styles/operations-pages.css frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md`
  - targeted `lineage` Playwright capture at `3037x1269`.

### Checkpoint - Lineage Native Stage Unit Gate Passed

- Implemented:
  - Reduced the wide/native Lineage graph row height and hid inline graph-node column chips at that breakpoint so the graph matches the prototype's compact node rhythm while column lineage remains available in the lower evidence panel.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx` -> passed, `2` files, `13` tests.
  - `git diff --check -- frontend/src/styles/lineage.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `lineage` at `3037x1269` and compare lower panel positioning against `northstar/screenshots/prototype_lineage.png`.

### Checkpoint - Lineage Stage Height Correction Started

- Trigger: recapturing `docs/northstar_visual_qa/prototype-lineage-stage-pass/lineage-3037x1269.png` showed the previous interpretation was inverted: the prototype graph stage is taller, with nodes distributed through the full lineage canvas. The chip suppression is still useful, but the native graph canvas needs to be taller, not shorter.
- Planned edit:
  - Increase the wide/native lineage graph stage height and distribute graph bands vertically while keeping inline node column chips hidden.
- Planned validation:
  - rerun focused Lineage tests.
  - `git diff --check -- frontend/src/styles/lineage.css IMPLEMENTATION_STATUS.md`
  - recapture `lineage` at `3037x1269`.

### Checkpoint - Lineage Stage Height Correction Unit Gate Passed

- Implemented:
  - Increased the native/wide lineage graph band height to match the reference's larger canvas and distributed nodes vertically across each hop column.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx` -> passed, `2` files, `13` tests.
  - `git diff --check -- frontend/src/styles/lineage.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture Lineage and inspect against `northstar/screenshots/prototype_lineage.png`.

### Checkpoint - Lineage Edge Overlay Started

- Trigger: the recaptured Lineage page now matches the prototype stage height more closely, but graph columns still lack visible connector paths. The reference graph shows explicit lineage edges between source, table, job, focus, and downstream nodes.
- Planned edit:
  - Add a lightweight SVG connector overlay that renders only when the lineage payload has backed edge evidence; do not render connectors for empty/unavailable lineage.
- Planned validation:
  - focused Lineage tests.
  - `git diff --check -- frontend/src/components/LineageStage.jsx frontend/src/styles/lineage.css IMPLEMENTATION_STATUS.md`
  - recapture `lineage` at `3037x1269`.

### Checkpoint - Lineage Edge Overlay Unit Gate Passed

- Implemented:
  - Added an SVG edge overlay to the Lineage Atlas graph. It renders only when the graph payload has edge evidence and uses the existing displayed nodes as its visual endpoints.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx` -> passed, `2` files, `13` tests.
  - `git diff --check -- frontend/src/components/LineageStage.jsx frontend/src/styles/lineage.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture Lineage at `3037x1269` and inspect graph connector parity.

### Checkpoint - Lineage Native Capture With Edges Passed

- Validation:
  - `GOVAT_PROTOTYPE_ROUTES=lineage GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-lineage-edge-pass/lineage-3037x1269.png`
- Manual inspection:
  - Lineage now uses the wide rail, larger prototype graph canvas, distributed hop nodes, visible backed connector paths, and lower impact/column-lineage panels in the same visual region as `northstar/screenshots/prototype_lineage.png`.
- Exact next action:
  - Inspect Audit Evidence and Control Center native captures against their prototype screenshots.

### Checkpoint - Audit Evidence Note Fix Started

- Trigger: manual inspection of `docs/northstar_visual_qa/prototype-all-routes-native/audit-3037x1269.png` against `northstar/screenshots/prototype_audit1.png` found the Audit table footer still says `Audit evidence source: local-prototype-mock` inside the table. The prototype uses a standalone evidence strip below the table describing append-only Delta retention/evidence.
- Planned edit:
  - Move the audit source/retention copy into the prototype note strip and render a truthful mock-backed or backend-backed note without raw row values.
- Planned validation:
  - `npm test -- --run src/components/AuditBrowserWorkspace.test.jsx`
  - `git diff --check -- frontend/src/components/AuditBrowserWorkspace.jsx frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md`
  - targeted `audit` Playwright capture at `3037x1269`.

### Checkpoint - Audit Evidence Note Unit Gate Passed

- Implemented:
  - Moved the Audit Evidence source/retention statement into a standalone prototype note strip below the table.
  - The note now uses backend-provided evidence copy when available, an explicit local-prototype mock note in mock capture, or an unavailable source statement otherwise.
- Validation:
  - `npm test -- --run src/components/AuditBrowserWorkspace.test.jsx` -> passed, `1` file, `5` tests.
  - `git diff --check -- frontend/src/components/AuditBrowserWorkspace.jsx frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `audit` at `3037x1269` and inspect against `northstar/screenshots/prototype_audit1.png`.

### Checkpoint - Prototype Viewport Capture Support Added

- Implemented:
  - Added `GOVAT_PROTOTYPE_VIEWPORTS` parsing to `frontend/scripts/atlas_prototype_current_capture.mjs` so captures can run at exact prototype dimensions such as `3037x1269`.
  - Capture reports now include the viewport list used for the run.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check -- frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Run a fresh mock-API capture for screenshot-backed routes at `3037x1269`, `1536x1024`, `1440x900`, and `1280x720`.

### Checkpoint - Refreshed Prototype Screenshot Capture Passed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024,1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-screenshot-backed-refresh ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-screenshot-backed-refresh/prototype-current-report.json`
  - `32` screenshots across `8` screenshot-backed routes and `4` viewports.
- Report result:
  - `passed=true`
  - `requestFailures=0`
  - `pageErrors=0`
  - `consoleErrors=0`
  - all captures loaded
  - no document-level horizontal overflow
- Exact next action:
  - Manually inspect the `3037x1269` captures against `northstar/screenshots/*`, record any remaining visual gaps, and send refreshed evidence to the review lanes.

### Checkpoint - Native-Size Visual Inspection Blocker Found

- Manual inspection against `northstar/screenshots/*`:
  - Command Center is close to the prototype's centered executive layout.
  - Discover, Stewardship, Lineage Atlas, Audit Evidence, and Control Center are too far left at `3037x1269`; their content starts immediately after the sidebar instead of using the prototype's centered work rail.
  - Atlas AI dock and right-side reserved area are present, but the main content rail is not consistently constrained or centered across pages.
- Planned edit:
  - Add shared prototype page-frame constraints for the screenshot-backed non-command pages so their primary content width and horizontal offset match the North Star layout at native size while remaining responsive at smaller viewports.
- Planned validation:
  - CSS diff hygiene.
  - Re-run targeted screenshot capture at `3037x1269` for the affected pages, then full route capture.

### Checkpoint - Shared Prototype Work Rail Remediation Started

- Trigger: native-size screenshot inspection showed the non-command prototype pages do not consistently use the centered work rail shown in `northstar/screenshots/*`.
- Planned code scope:
  - `frontend/src/styles/northstar.css`
  - `frontend/src/styles/lineage.css`
  - `frontend/src/styles/operations-pages.css`
- Planned change:
  - constrain and center Discover, Lineage Atlas, Audit Evidence, and Control Center primary content at wide prototype viewports while preserving existing responsive behavior at `1536x1024`, `1440x900`, and `1280x720`.
  - do not alter the current Command Center, Stewardship, Glossary, or CDE Registry page content unless the shared CSS change exposes a regression.
- Planned validation:
  - CSS diff hygiene
  - focused component tests for the affected pages if selectors or layout assumptions change
  - targeted Playwright capture for `discover,lineage,audit,control-center` at `3037x1269`
  - inspect screenshots before full-route capture and reviewer re-check.

### Checkpoint - Shared Prototype Work Rail Focused Tests Passed

- Implemented:
  - Added shared wide-viewport frame variables for the open Atlas AI dock and prototype rail width.
  - Constrained and centered the Discover grid at native prototype width.
  - Centered the Lineage Atlas hero, workbench, graph, and status rail at native prototype width.
  - Widened and centered the Audit Evidence and Control Center prototype shells at native prototype width.
  - Added Lineage Atlas prototype rects to the Playwright capture report.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check -- frontend/src/styles/northstar.css frontend/src/styles/lineage.css frontend/src/styles/operations-pages.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx src/components/LineageStage.test.jsx src/components/AuditBrowserWorkspace.test.jsx src/components/AdminWorkspace.test.jsx` -> `4` files passed, `48` tests passed.
- Exact next action:
  - Run targeted native-size Playwright capture for `discover,lineage,audit,control-center` and inspect the resulting screenshots/rects before any broader route capture.

### Checkpoint - Shared Prototype Work Rail Screenshot Evidence Refreshed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover,lineage,audit,control-center GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx` -> `1` file passed, `34` tests passed after the Discover-specific control/horizontal-frame adjustment.
- Evidence:
  - `docs/northstar_visual_qa/prototype-wide-rail-targeted/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-wide-rail-targeted/{discover,lineage,audit,control-center}-3037x1269.png`
  - focused Discover recapture: `docs/northstar_visual_qa/prototype-discover-wide-rail/discover-3037x1269.png`
- Result:
  - Discover, Lineage Atlas, Audit Evidence, and Control Center primary content now measures at approximately `left=867/868`, `right=2411/2412`, `width=1544`, matching the prototype centered work rail at native width.
  - Removed obsolete prototype Discover top filter dropdown row and page-local `Ask Atlas AI` control from the visual layout; the global Atlas AI dock remains the assistant surface.
- Remaining visual/product issues found during inspection:
  - topbar coverage still falls back to `UC connected · 0% coverage` outside Command Center in the mock-API capture.
  - Discover result cards are close structurally but still carry older card/action/chip rhythm compared with `northstar/screenshots/prototype_discover.png`.
- Exact next action:
  - Fix the topbar coverage source so the shell uses the same visible catalog coverage signal across routes, then continue Discover result-row parity.

### Checkpoint - Cross-Route UC Coverage Signal Fixed

- Implemented:
  - `App.jsx` now derives the shell UC coverage score from the bootstrap/discovery summary when present, then governance summary, then the visible asset coverage values instead of depending only on the Command Center API query.
  - The prototype Playwright mock bootstrap now guarantees a discovery summary while preserving any real fixture fields.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check -- frontend/src/App.jsx frontend/scripts/atlas_prototype_current_capture.mjs frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md` -> passed.
  - `npm test -- --run src/App.test.jsx src/components/DiscoveryWorkspace.test.jsx` -> `2` files passed, `59` tests passed.
  - Refreshed Discover native-size capture -> passed, `requestFailures=0`, and text evidence contains `UC connected · 87.4% coverage`.
- Evidence:
  - `docs/northstar_visual_qa/prototype-discover-wide-rail/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-discover-wide-rail/discover-3037x1269.png`
- Exact next action:
  - Continue Discover result-row/card parity against `northstar/screenshots/prototype_discover.png`.

### Checkpoint - Discover Result Row Prototype Remediation Started

- Trigger: after the wide work-rail and coverage fixes, the current Discover screenshot still differs from `northstar/screenshots/prototype_discover.png` in the result-card grammar.
- Current visual gaps:
  - result rows still expose old table/card cells such as the visible object-type chip and favorite/menu controls, while the prototype uses compact asset cards with a single blue asset icon, asset name, full path, governance chips, description, metadata line, and right-aligned trust score.
  - default sort still visually reads as `Relevance`; the prototype uses `Trust score`.
  - mock-API evidence still inherits broad live-bootstrap result counts and uniform coverage values; production must stay truthful, but local prototype mock evidence should use explicit fixture-backed values when validating the prototype layout.
- Planned edit:
  - Add stable semantic classes to Discover row cells so prototype-mode CSS can match the North Star layout without breaking table-mode behavior.
  - Restyle prototype-mode Discover rows to the North Star asset-card hierarchy.
  - Keep row click, favorite/action handlers, and asset-opening workflows functional even if the prototype-mode visual treatment de-emphasizes old controls.
- Planned validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx`
  - `npm run typecheck`
  - `git diff --check`
  - recapture `discover` at `3037x1269` with `GOVAT_PROTOTYPE_MOCK_API=1`.

### Checkpoint - Discover Result Row Focused Validation Passed

- Implemented:
  - Added stable Discover row cell classes for type, certification, domain, sensitivity, and linkage cells.
  - Added prototype-mode metadata lines and governance-chip styling so rows can match the North Star asset-card hierarchy without removing the underlying row click/action workflow.
  - Added working list/grid view toggle buttons in the prototype result toolbar.
  - Updated local Playwright mock-API Discover data to use the explicit North Star result fixtures and `Trust score` sort option while keeping the fixture source marked `local-prototype-mock`.
- Validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx` -> passed, `34` tests.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check -- frontend/src/components/DiscoveryWorkspace.jsx frontend/src/styles/northstar.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Re-run the Discover native-size Playwright capture and inspect the current screenshot against `northstar/screenshots/prototype_discover.png`.

### Checkpoint - Discover Native Recapture Found Shared AI Dock Gap

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-discover-row-pass ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-discover-row-pass/discover-3037x1269.png`
- Result:
  - Discover rows now use North Star fixture content, varied trust scores, compact asset-card hierarchy, `Trust score` sort, and prototype result count.
  - Remaining blocker from screenshot inspection is shared, not Discover-specific: the floating Atlas AI dock defaults too low at the native prototype viewport. The prototype places it mid-right beside the work rail, while the current default uses a low bottom offset.
- Planned edit:
  - Adjust only the default wide-screen Atlas AI dock placement so `3037x1269` prototype captures align with the North Star while preserving the lower placement on smaller viewports.
- Planned validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/DiscoveryWorkspace.test.jsx`
  - `npm run typecheck`
  - recapture Discover at `3037x1269`.

### Checkpoint - Shared AI Dock Wide-Viewport Placement Validated

- Implemented:
  - `AppFrame.jsx` now uses a higher default Atlas AI dock position only on very wide prototype-class viewports (`>=2200px`), while preserving the previous lower default on smaller desktop and responsive viewports.
- Validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/DiscoveryWorkspace.test.jsx` -> passed, `48` tests.
  - `npm run typecheck` -> passed.
  - `git diff --check -- frontend/src/components/AppFrame.jsx frontend/src/components/DiscoveryWorkspace.jsx frontend/src/styles/northstar.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture Discover after the wide-dock placement fix and compare the dock/results frame with the prototype.

### Checkpoint - Discover Native Row/Dock Recapture Passed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-discover-row-pass ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-discover-row-pass/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-discover-row-pass/discover-3037x1269.png`
- Result:
  - Discover now matches the prototype’s core structure: centered rail, left filter rail, compact result cards, varied trust scores, `Trust score` sort, global Atlas AI dock at the prototype vertical position, and `UC connected · 87.4% coverage`.
- Remaining visual deltas to watch in broader route review:
  - workspace label remains environment-driven (`Dev`) instead of the prototype fixture `entrada-prod`; this is an accepted truth-based data difference unless local mock evidence specifically needs prototype branding.
  - result-card typography is slightly denser/smaller than the static prototype but preserves the same hierarchy and gains real overflow resilience.
- Exact next action:
  - Run a full screenshot-backed capture across all current `northstar/*` routes with the corrected Discover fixture and shared dock placement, then inspect the next largest route-level gaps.

### Checkpoint - Full Native Capture Found Stewardship Rail Width Gap

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-all-routes-native ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed across all `8` screenshot-backed routes.
- Evidence:
  - `docs/northstar_visual_qa/prototype-all-routes-native/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-all-routes-native/stewardship-3037x1269.png`
- Current blocker:
  - Stewardship content is still capped around the older `1120px` layout width, leaving a large blank gap before the Atlas AI rail. The North Star stewardship screenshot uses the same centered `1544px` rail as Discover, Audit, Control Center, and Lineage.
- Planned edit:
  - Add a wide-viewport rail override for `.gh-governance-ns` hero, filter pills, queue/detail layout, and status/action panels only.
- Planned validation:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx`
  - `git diff --check`
  - targeted Stewardship native capture.

### Checkpoint - Stewardship Rail Parity Validated

- Implemented:
  - Added a wide-viewport rail override for `.gh-governance-ns` hero, filter pills, work queue/detail layout, and status/action panels.
- Validation:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx` -> passed, `10` tests.
  - `git diff --check -- frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
  - targeted Stewardship native capture -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-stewardship-rail-pass/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-stewardship-rail-pass/stewardship-3037x1269.png`
- Result:
  - Stewardship work queue and detail panel now align to the prototype-wide rail and no longer leave the large blank gap before the Atlas AI dock.
- Exact next action:
  - Continue route-by-route visual inspection, starting with Glossary/CDE and Lineage captures from `docs/northstar_visual_qa/prototype-all-routes-native/`.

### Checkpoint - Glossary/CDE Rail Width Gap Started

- Trigger: native Glossary screenshot still uses the older `1120px` prototype shell, while `northstar/screenshots/prototype_glossary1.png` uses the same wide centered rail as the other prototype pages. The current heading also wraps because of a narrow heading max-width.
- Planned edit:
  - Widen `.gh-taxonomy-prototype-shell` to the shared prototype rail only at `>=2200px`.
  - Widen the prototype heading max-width at that same breakpoint so the title matches the screenshot hierarchy.
- Planned validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx`
  - `git diff --check`
  - targeted Glossary/CDE native capture.

### Checkpoint - Lineage Atlas Prototype Remediation In Progress

- Trigger: local Playwright mock-API evidence for `/lineage-atlas/finance_prod.curated.revenue_daily` loaded successfully, but visual inspection showed the older `End-to-End Lineage Explorer` shell rather than the new prototype `Lineage Atlas` asset-first page.
- Current blocker:
  - page header/title, action controls, graph layout, and bottom evidence panels do not match `northstar/screenshots/prototype_lineage.png`
  - graph classification currently relies on immediate focus-node edges, which hides the multi-hop upstream/source, transformation, and downstream/consumer structure shown by the prototype
- Current edit scope:
  - `frontend/src/components/LineageStage.jsx`
  - `frontend/src/components/LineageStage.test.jsx`
  - `frontend/src/styles/lineage.css`
  - `frontend/scripts/atlas_prototype_current_capture.mjs`
- Planned validation after edit:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx`
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - `npm run lint -- --quiet`
  - local Playwright mock-API capture for `GOVAT_PROTOTYPE_ROUTES=lineage`
  - send refreshed Lineage evidence to visual/product, functional/regression, and truth/provenance review lanes before any signoff

### Checkpoint - Lineage Atlas Component Patch Validated Locally

- Implemented:
  - Replaced the full-page lineage shell with a prototype-aligned `Lineage Atlas` asset-first page: asset FQN header, evidence chips, compare/run-analysis actions, wide lineage graph card, graph legend/tools, impact analysis, and column-lineage evidence panels.
  - Updated lineage graph classification to honor explicit staged/multi-hop payload fields and to fall back to graph traversal for live Unity Catalog lineage.
  - Updated local prototype mock lineage data with staged source/upstream/transform/focus/downstream nodes, CDE/freshness/owner evidence, impact rows, and column-lineage rows.
  - Realigned `LineageStage` tests to the prototype layout and retained embedded Asset 360 graph behavior.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx` -> `2` files passed, `13` tests passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/components/LineageStage.jsx frontend/src/components/LineageStage.test.jsx frontend/src/styles/lineage.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
- Next action:
  - Run lint and refreshed local Playwright mock-API lineage screenshots at `1536x1024`, `1440x900`, and `1280x720`; inspect the output before sending it to review lanes.

### Checkpoint - Lineage Atlas Screenshot Evidence Refreshed

- Additional remediation after screenshot inspection:
  - Removed the oversized standalone partial-lineage banner and moved truncation evidence into the graph card legend as a compact `Partial lineage` marker with the full message preserved for assistive/queryable text.
  - Reduced header/graph vertical spacing so the graph and the first row of bottom evidence panels are visible in the `1440x900` capture.
- Validation:
  - `npm test -- --run src/components/LineageStage.test.jsx src/components/LineageWorkspace.test.jsx` -> `2` files passed, `13` tests passed.
  - `npm run lint -- --quiet` -> passed.
  - `git diff --check frontend/src/components/LineageStage.jsx frontend/src/components/LineageStage.test.jsx frontend/src/styles/lineage.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=lineage GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-lineage-functional ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-lineage-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-lineage-functional/lineage-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-lineage-functional/lineage-1440x900.png`
  - `docs/northstar_visual_qa/prototype-lineage-functional/lineage-1280x720.png`
- Manual inspection result:
  - The page now renders the prototype lineage structure: asset-first `Lineage Atlas` header, evidence chips, compare/run actions, wide multi-hop graph card, graph legend/tools, compact truncation evidence, impact analysis panel, and column lineage panel.
  - Remaining visual judgment items for reviewers: shell/sidebar width and content left offset still differ from the prototype chrome; the graph uses HTML node bands rather than a true curved-edge canvas.
- Next action:
  - Send refreshed evidence to review lanes and continue the next page only after blockers are incorporated or recorded.

### Checkpoint - Audit Evidence and Control Center Baseline Started

- Trigger: Lineage evidence has been sent to review lanes; next explicit prototype screenshots without a completed continuation pass are Audit Evidence and Control Center.
- Current baseline task:
  - capture `/audit-evidence` and `/control-center` at `1536x1024`, `1440x900`, and `1280x720` using the local Playwright mock-API harness
  - inspect whether the pages already match the new prototype or still render older workspace layouts
- Planned edit scope if gaps are confirmed:
  - `frontend/src/components/AuditBrowserWorkspace.jsx`
  - `frontend/src/components/AdminWorkspace.jsx`
  - page-specific tests and `frontend/scripts/atlas_prototype_current_capture.mjs` mock data as needed
- Planned validation after each page edit:
  - focused component tests
  - `npm run lint -- --quiet`
  - local Playwright screenshots with `GOVAT_PROTOTYPE_MOCK_API=1`
  - reviewer-lane evidence before signoff

### Checkpoint - Audit Evidence Prototype Width Remediation Started

- Trigger: local mock-API Audit Evidence screenshots render the correct prototype content, but manual visual inspection of `docs/northstar_visual_qa/prototype-audit-functional/audit-1440x900.png` showed the page body constrained to a narrow column. The KPI row, table, and heading wrap far more than `northstar/screenshots/prototype_audit.png`.
- Root-cause hypothesis:
  - the shell-level AI dock reservation is correct, but the Audit page grid item is not consistently stretching to the available `.gh-main` content width.
  - old audit media-query rules may still override prototype table columns.
- Current edit scope:
  - `frontend/src/styles/operations-pages.css`
- Planned validation:
  - `npm test -- --run src/components/AuditBrowserWorkspace.test.jsx`
  - `npm run lint -- --quiet`
  - local mock-API Playwright capture for `GOVAT_PROTOTYPE_ROUTES=audit`
  - manual screenshot inspection before sending refreshed evidence to review lanes.

### Checkpoint - Audit Evidence Prototype Width Remediation Validated

- Implemented:
  - Forced `.gh-audit-ns` and `.gh-audit-shell` to stretch to the available `.gh-main` width.
  - Overrode the older two-column audit media-query shell for the prototype audit page.
  - Protected the prototype audit table from old seven-column audit rules.
  - Added audit/admin element rects to `frontend/scripts/atlas_prototype_current_capture.mjs` so future screenshot reports expose layout constraints directly.
- Validation:
  - `npm test -- --run src/components/AuditBrowserWorkspace.test.jsx` -> `1` file passed, `4` tests passed.
  - `npm run lint -- --quiet` -> passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/styles/operations-pages.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=audit ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed for `1536x1024`, `1440x900`, and `1280x720`.
- Evidence:
  - `docs/northstar_visual_qa/prototype-audit-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-audit-functional/audit-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-audit-functional/audit-1440x900.png`
  - `docs/northstar_visual_qa/prototype-audit-functional/audit-1280x720.png`
- Manual inspection result:
  - The page now renders the prototype Audit Evidence structure with the hero, action buttons, KPI row, filter pills, wide immutable event table, Delta evidence note, and Atlas AI dock visible.
  - Remaining review judgment item: the current shell still uses the app's 240px rail and DEFAULT workspace labels rather than the prototype's narrower rail and `entrada-prod` labels; this is cross-shell/data-context drift, not an Audit page-only defect.
- Next action:
  - Send refreshed Audit Evidence evidence to review lanes and start the Control Center prototype remediation.

### Checkpoint - Control Center Prototype Remediation Started

- Trigger: baseline Playwright evidence showed `/control-center` still rendering the older `Administration & Control Center` diagnostics/workspace surface instead of `northstar/screenshots/prototype_control_center.png`.
- Required prototype structure:
  - Eyebrow `Control Center`, title `Atlas runtime, integrations, and policy`, and Databricks Apps/workspace-scoped explanatory copy.
  - `Scheduled jobs` table with job, schedule, last run, and status.
  - `Integrations` status list.
  - `Policy coverage` bars.
  - Preserve truthful unavailable states for missing live admin data; deterministic mock API may populate the prototype for local visual validation only.
- Current edit scope:
  - `frontend/src/components/AdminWorkspace.jsx`
  - `frontend/src/components/AdminWorkspace.test.jsx`
  - `frontend/src/styles/operations-pages.css`
  - `frontend/scripts/atlas_prototype_current_capture.mjs`
- Planned validation:
  - `npm test -- --run src/components/AdminWorkspace.test.jsx`
  - `npm run lint -- --quiet`
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - local mock-API Playwright capture for `GOVAT_PROTOTYPE_ROUTES=control-center`
  - send refreshed Control Center evidence to review lanes.

### Checkpoint - Control Center Prototype Remediation Validated

- Implemented:
  - Replaced the old `Administration & Control Center` diagnostics/workspace layout with the prototype `Control Center` surface.
  - Added truthful-backed sections for scheduled Lakeflow jobs, integrations, and policy coverage; missing live signals remain as unavailable rows.
  - Added deterministic local mock-API Control Center payload for Playwright visual evidence.
  - Tightened the scheduled-jobs grid so job, schedule, last run, and status remain visible at `1440x900` with the Atlas AI dock open.
- Validation:
  - `npm test -- --run src/components/AdminWorkspace.test.jsx` -> `1` file passed, `5` tests passed.
  - `npm run lint -- --quiet` -> passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/components/AdminWorkspace.jsx frontend/src/components/AdminWorkspace.test.jsx frontend/src/styles/operations-pages.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=control-center ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed for `1536x1024`, `1440x900`, and `1280x720`.
- Evidence:
  - `docs/northstar_visual_qa/prototype-control-center-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-control-center-functional/control-center-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-control-center-functional/control-center-1440x900.png`
  - `docs/northstar_visual_qa/prototype-control-center-functional/control-center-1280x720.png`
- Manual inspection result:
  - The page now renders the prototype runtime/integrations/policy structure with the scheduled jobs table, integrations list, policy bars, and Atlas AI dock visible.
  - Remaining review judgment item: shared shell rail width and DEFAULT/local labels differ from the prototype data context, consistent with the broader shell/data-context caveat.
- Next action:
  - Send refreshed Control Center evidence to review lanes, then run an all-route mock-API screenshot pass to find remaining prototype-page regressions before final signoff.

### Checkpoint - All-Route Prototype Regression Pass Started

- Trigger: Audit Evidence and Control Center now have refreshed local mock-API evidence; before page signoff, the full prototype route set needs one capture pass to expose cross-page CSS/layout regressions.
- Route set:
  - Command Center
  - Discover
  - Stewardship
  - Glossary
  - CDE Registry
  - Lineage Atlas
  - Audit Evidence
  - Control Center
  - Asset 360
- Planned validation:
  - local Playwright mock-API screenshots at `1536x1024`, `1440x900`, and `1280x720`
  - inspect `prototype-current-report.json` for failed route loads, request failures, console errors, overflow, and obvious text/layout clipping.

### Checkpoint - Asset 360 Mock-API Regression Fix Started

- Trigger: the all-route prototype regression pass reported `404` request failures for `/api/atlas/assets/finance_prod.curated.revenue_daily/360` at all viewports. The page loaded from fallback data, but the exact Asset 360 composite endpoint used by the UI was not mocked, leaving a functional validation gap.
- Current edit scope:
  - `frontend/scripts/atlas_prototype_current_capture.mjs`
- Planned validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - local mock-API Playwright capture for `GOVAT_PROTOTYPE_ROUTES=asset360`
  - repeat all-route regression summary and confirm request failures are gone.

### Checkpoint - Command Center Short-Viewport Remediation Started

- Trigger: reviewer evidence blocker found the hydrated Command Center screenshots at `1280x720` did not expose the lower prototype sections; `.gh-main` reported no scroll despite the lower content being clipped.
- Current edit scope:
  - `frontend/src/styles/northstar.css`
  - `frontend/scripts/atlas_prototype_current_capture.mjs` only if additional scroll evidence instrumentation is needed.
- Constraint: preserve the prototype compact density and do not hide sections or mark visual signoff until refreshed `1280x720`, `1440x900`, and `1536x1024` screenshots prove the Command Center lower sections are reachable.
- Planned validation after edit:
  - focused Home/Command Center tests
  - lint/typecheck if CSS or script changes affect app/runtime assumptions
  - local Playwright capture with `GOVAT_PROTOTYPE_MOCK_API=1`, `GOVAT_PROTOTYPE_SCROLL_MAIN=1`, and Command Center route only
  - send refreshed evidence to visual/product, functional/regression, and truth/provenance review lanes

### Checkpoint - Command Center Short-Viewport CSS Fix

- Implemented a scoped override for `.gh-command-center-page.gh-home-page.ga-page` so legacy Home short-height rules can no longer force the prototype Command Center root to `height: 100%` with clipped overflow.
- Added a small short-height density adjustment for the Command Center shell, hero title, state card, and KPI cards to keep the `1280x720` view compact without deleting lower sections.
- Validation:
  - `npm test -- --run src/components/HomePage.test.jsx` -> `1` file passed, `9` tests passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md` -> passed.
- Next action: rerun the hydrated Command Center Playwright capture with internal-main scroll evidence and confirm `1280x720` now exposes lower Command Center sections.

### Checkpoint - Command Center Short-Viewport Evidence Refreshed

- Refreshed hydrated mock-API Command Center screenshots:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_SCROLL_MAIN=1 GOVAT_PROTOTYPE_ROUTES=command-center GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-command-center-functional ...`
- Evidence:
  - `docs/northstar_visual_qa/prototype-command-center-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1280x720-main-bottom.png`
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1440x900-main-bottom.png`
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1536x1024-main-bottom.png`
- Result:
  - report `passed=true`
  - `1280x720` `.gh-main` scroll now reports `scrollHeight=1425`, `clientHeight=664`, `hasOverflow=true`, `maxScrollTop=761`
  - lower Command Center sections are visible in the 1280 bottom capture: Risk breakdown, Top catalogs health snapshot, Critical data elements, and Activity stream.
- Next action: send refreshed evidence back to the Command Center review lanes and continue with the next prototype page only after blockers are incorporated or explicitly recorded.

### Checkpoint - Stewardship Prototype Remediation Started

- Starting the Stewardship Workbench tranche against `northstar/screenshots/prototype_stewardship1.png` and `prototype_stewardship2.png`.
- Current implementation baseline:
  - `GovernanceWorkspace.jsx` already calls the live governance workbench API and request-detail API.
  - Existing UI is still a broader old North Star governance request surface with KPI cards, approval tabs, and request metadata diff panels; it does not match the new prototype work-queue/detail model.
- Planned code scope:
  - `frontend/src/components/GovernanceWorkspace.jsx`
  - `frontend/src/components/GovernanceWorkspace.test.jsx`
  - `frontend/src/styles/operations-pages.css`
  - `frontend/scripts/atlas_prototype_current_capture.mjs` for deterministic local workbench API evidence.
- Prototype-specific requirements for this pass:
  - header title with open work items and SLA breaches
  - action buttons: Filter, Bulk assign, New work item
  - queue pills: All, P1 critical, Overdue, Assigned to me
  - table columns: ID, Item, Asset, Assigned, SLA, Priority
  - selected-row detail pane with affected asset, why-open evidence, suggested actions, Comment/Resolve controls, and implementation provenance
  - no fake workflow state; local mock capture must be explicitly recorded as mock-API evidence
- Planned validation:
  - focused GovernanceWorkspace tests
  - lint/typecheck if component/CSS changes touch shared contracts
  - hydrated local Playwright capture for `/stewardship`
  - send Stewardship evidence to visual/product, functional/regression, and truth/provenance review lanes

### Checkpoint - Stewardship Prototype Test Realignment Started

- Focused validation before this edit:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx` -> failed, `8` failed / `1` passed.
- Cause:
  - The component has already moved to the prototype work-queue/detail shape, but the test suite still asserts the prior governance approval UI: KPI cards, `Open Governance Requests`, metadata-change tabs, Approve/Request Changes/Escalate, and old empty-state copy.
  - The current component also still renders old inner type/sort controls inside the work queue head, which diverges from the prototype Stewardship screenshot.
- Current edit scope:
  - `frontend/src/components/GovernanceWorkspace.jsx`
  - `frontend/src/components/GovernanceWorkspace.test.jsx`
- Exact next action:
  - Align the test fixture with prototype-backed work item fields, remove stale inner queue controls from the Stewardship page, and validate Comment/Resolve/filter/detail/lineage workflows through focused tests.

### Checkpoint - Stewardship Focused Tests Passed

- Implemented:
  - Removed the old inner queue type/sort controls from the Stewardship prototype branch so the work queue matches the prototype layout more closely.
  - Rebuilt `GovernanceWorkspace` focused test fixtures around prototype-shaped stewardship work items (`SI-*` IDs, assigned teams, SLA labels, evidence, suggested actions, implementation provenance).
  - Updated workflow tests for Filter, queue pills, Bulk assign, New work item, row selection, Comment, Resolve, suggested-action notes, lineage handoff, degraded fallback, and scoped empty state.
- Validation:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx` -> `1` file passed, `9` tests passed.
- Next action:
  - Add hydrated Stewardship mock-API coverage to `frontend/scripts/atlas_prototype_current_capture.mjs`, run syntax/lint checks, and capture `/stewardship` screenshots for review.

### Checkpoint - Stewardship Hydrated Screenshot Evidence Captured

- Added deterministic mock-API coverage for the Stewardship visual run:
  - `/api/atlas/governance/workbench`
  - `/api/atlas/governance/requests/{request_id}`
  - `/api/governance/requests/{request_id}` mutation echo for local interaction paths
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/components/GovernanceWorkspace.jsx frontend/src/components/GovernanceWorkspace.test.jsx frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `npm run lint -- --quiet` -> passed.
  - Local Vite probe at `http://127.0.0.1:3000` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=stewardship GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-stewardship-functional ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-stewardship-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-stewardship-functional/stewardship-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-stewardship-functional/stewardship-1440x900.png`
  - `docs/northstar_visual_qa/prototype-stewardship-functional/stewardship-1280x720.png`
- Result:
  - report `passed=true`
  - no page errors, no request failures, no horizontal overflow in all three viewports
  - visual page now renders prototype-like Stewardship header, queue pills, 8-row work queue, selected detail pane, affected asset, why-open evidence, suggested actions, Comment/Resolve controls, and implementation provenance.
- Open cross-page visual issue found during manual screenshot inspection:
  - The prototype shows the Atlas AI dock open as a right-side panel on most pages, while the current local capture shows only the persistent bottom-right FAB unless Atlas AI is explicitly opened. This is a global shell/Atlas AI parity item, not a Stewardship-only issue.
- Next action:
  - Send the Stewardship evidence to visual/product, functional/regression, and truth/provenance review lanes; incorporate blockers before treating the page as complete.

### Checkpoint - Glossary & CDEs Prototype Remediation Started

- Starting the next independent prototype page while Stewardship review lanes run.
- Target screenshots:
  - `northstar/screenshots/prototype_glossary1.png`
  - `northstar/screenshots/prototype_glossary2.png`
- Planned code scope:
  - `frontend/src/components/TaxonomyWorkspace.jsx`
  - `frontend/src/components/TaxonomyWorkspace.test.jsx` if existing coverage needs prototype alignment
  - `frontend/src/styles/operations-pages.css` / `frontend/src/styles/northstar.css` only where required for layout parity
  - `frontend/scripts/atlas_prototype_current_capture.mjs` for deterministic glossary/CDE mock-API evidence if needed
- Prototype-specific requirements for this pass:
  - Header: `Glossary & CDE Registry`, title `Shared business meaning, anchored to data`, and `New term` action.
  - Tabs: `Glossary` and `CDE Registry`.
  - Glossary card grid with term title, steward/domain, definition, status pill, asset count, and lineage link.
  - CDE table with CDE name, source-of-record column, owner, recert age, and health/recent-due status.
  - Preserve truthfulness: real glossary/CDE data when live-backed; mock data only for local Playwright visual evidence.
- Planned validation:
  - focused TaxonomyWorkspace tests or add coverage if missing
  - lint/diff hygiene
  - local hydrated Playwright captures for `/glossary-cdes` and `/cde`
  - send evidence to visual/product, functional/regression, and truth/provenance reviewers

### Checkpoint - Glossary & CDEs Focused Tests Passed

- Implemented the prototype Glossary & CDE Registry shell in `TaxonomyWorkspace`:
  - header, subtitle, `+ New term` action, and `Glossary` / `CDE Registry` tabs
  - glossary term cards with domain/steward, definition, status, asset count, and lineage handoff
  - CDE table with source-of-record column, owner, recert age, and health status
  - honest empty states when no glossary terms or CDE rows are returned
- Preserved live-data truth by normalizing real API payloads first; local seeded rows remain only for tests and Playwright mock-API evidence.
- Validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx` -> `1` file passed, `4` tests passed.
  - `git diff --check frontend/src/components/TaxonomyWorkspace.jsx frontend/src/components/TaxonomyWorkspace.test.jsx frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
- Next action:
  - Add deterministic taxonomy/CDE mock responses to the prototype capture script, update route settling for the new prototype root, then capture `/glossary-cdes` and `/cde` evidence.

### Checkpoint - Glossary & CDEs Playwright Evidence Started

- Added deterministic local Playwright mock responses for:
  - `/api/atlas/taxonomy/overview`
  - `/api/atlas/cde`
- Updated prototype capture routes so:
  - `glossary` captures `/glossary-cdes`
  - `cde-registry` captures `/glossary-cdes?tab=cdes`
  - both settle on `.gh-taxonomy-ns` so they evaluate the new prototype registry page rather than the legacy standalone CDE workspace.
- Validation before screenshots:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx` -> `1` file passed, `4` tests passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/components/TaxonomyWorkspace.jsx frontend/src/components/TaxonomyWorkspace.test.jsx frontend/scripts/atlas_prototype_current_capture.mjs frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Probe local Vite, run hydrated Playwright capture for `glossary,cde-registry`, inspect report/screenshots, then send evidence to review lanes.

### Checkpoint - Glossary & CDEs Hydrated Screenshot Evidence Captured

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - Local Vite probe at `http://127.0.0.1:3000` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=glossary,cde-registry GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-glossary-functional ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-glossary-functional/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-glossary-functional/glossary-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-glossary-functional/glossary-1440x900.png`
  - `docs/northstar_visual_qa/prototype-glossary-functional/glossary-1280x720.png`
  - `docs/northstar_visual_qa/prototype-glossary-functional/cde-registry-1536x1024.png`
  - `docs/northstar_visual_qa/prototype-glossary-functional/cde-registry-1440x900.png`
  - `docs/northstar_visual_qa/prototype-glossary-functional/cde-registry-1280x720.png`
- Result:
  - report `passed=true`, `mockApi=true`
  - no page errors, no request failures, and no horizontal overflow in all three viewports
  - prototype page shape is present: hero, `New term`, tabs, glossary cards, and CDE table.
- Manual screenshot blocker:
  - The global Atlas AI dock is still missing from these page captures; the current shell shows only the bottom-right Atlas AI FAB. This remains a global cross-page parity blocker before any visual signoff can be claimed.
- Next action:
  - Send the screenshots and report to reviewer lanes, then continue with the global Atlas AI dock or the next prototype page based on blockers.

### Checkpoint - Global Atlas AI Dock Remediation Started

- Trigger:
  - Manual inspection of Command Center, Stewardship, and Glossary/CDE captures shows the prototype expects an open Atlas AI right-side assistant on most pages, but the current shell only renders a bottom-right FAB until the user opens the floating chat.
- Planned code scope:
  - `frontend/src/components/AppFrame.jsx`
  - `frontend/src/components/AppFrame.test.jsx`
  - `frontend/src/styles/northstar.css`
  - `frontend/scripts/atlas_prototype_current_capture.mjs` only if screenshot settling needs an Atlas AI selector.
- Prototype/functional requirements:
  - Atlas AI opens by default when the shell reports a live, evidence-backed AI provider.
  - The user can still close, reopen from the topbar/FAB, drag, resize, and use Escape.
  - The dialog remains grounded in the existing `useAtlasAiConversation` path and API; no local fake AI answers in production.
  - Suggested prompts should leave room for the answer after a question is asked.
- Planned validation:
  - focused `AppFrame` tests
  - lint/diff hygiene
  - refreshed Playwright capture for at least `glossary,cde-registry,stewardship` to verify the dock is visible without opening it manually
  - reviewer lane re-check for visual/product, functional/regression, and truth/provenance

### Checkpoint - Global Atlas AI Dock Focused Tests Passed

- Implemented:
  - Atlas AI now opens by default when the shell is live and the AI provider state is available/configured.
  - Closing the dock persists a user dismissal in local storage; topbar/FAB reopening clears that dismissal.
  - Existing topbar/FAB open, close, Escape-close, drag, resize, and API-backed conversation paths remain in `AppFrame`.
  - The default assistant message now describes governed UC metadata grounding and raw-row avoidance.
  - Suggested prompts collapse to one prompt after a conversation starts so responses have usable reading space.
  - Default dock dimensions were reduced to a prototype-like right-side assistant footprint while remaining resizable.
- Validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx` -> `2` files passed, `21` tests passed.
  - `git diff --check frontend/src/components/AppFrame.jsx frontend/src/components/AppFrame.test.jsx frontend/src/styles/northstar.css IMPLEMENTATION_STATUS.md` -> passed.
- Next action:
  - Run lint and refreshed hydrated Playwright captures for affected prototype routes to confirm the Atlas AI dock appears by default.

### Checkpoint - Global Atlas AI Dock Hydrated Evidence Captured

- Additional implementation:
  - Added mock responses for `/api/governance/summary` and `/api/classification-recommendations` in the prototype Playwright harness so local screenshot evidence has no avoidable 404 noise.
  - Added focused test coverage that Atlas AI is open by default, can be closed, and can be reopened without route changes.
- Validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx` -> `2` files passed, `21` tests passed.
  - `npm run lint -- --quiet` -> passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `git diff --check frontend/src/components/AppFrame.jsx frontend/src/components/AppFrame.test.jsx frontend/src/styles/northstar.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=command-center,stewardship,glossary,cde-registry GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-global-ai-dock ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-global-ai-dock/prototype-current-report.json`
  - refreshed screenshots for `command-center`, `stewardship`, `glossary`, and `cde-registry` at `1536x1024`, `1440x900`, and `1280x720`
- Result:
  - report `passed=true`, `mockApi=true`
  - no page errors, no request failures, and no horizontal overflow
  - all captured routes expose the open Atlas AI dialog close control by default.
- Manual screenshot note:
  - The dock is now visible and positioned close to the prototype, but the reserved right-side area creates a visible background tone change on some pages. This needs visual reviewer judgment before claiming final parity.
- Next action:
  - Send global dock evidence to reviewer lanes and continue the next prototype page tranche.

### Checkpoint - Lineage Atlas Prototype Remediation Started

- Target screenshot:
  - `northstar/screenshots/prototype_lineage.png`
- Trigger:
  - The prototype requires a loaded lineage atlas surface with focus asset, hop bands, visible upstream/downstream nodes, impact analysis, and column-lineage evidence.
  - Prior user feedback specifically called out that Lineage does not load at all in the live app.
- Planned code scope:
  - `frontend/src/components/LineageWorkspace.jsx`
  - lineage styles only if existing component shape can be adapted safely
  - `frontend/scripts/atlas_prototype_current_capture.mjs` for deterministic lineage mock evidence
  - focused lineage tests if current assertions no longer cover the prototype path
- Constraints:
  - Do not fake production lineage. Use live/system lineage where available; local mock graph is only for Playwright evidence.
  - If production lineage is unavailable, preserve the prototype panel shape with honest unavailable/degraded messaging.
- Planned validation:
  - focused Lineage tests
  - lint/diff hygiene
  - hydrated Playwright capture for `/lineage-atlas/{asset}`
  - reviewer lane checks for visual/product, functional/regression, and truth/provenance

### Completed Changes

- Read the active repo instructions from the user and confirmed the repo-local `.claude/skills/*` symlinks resolve to Databricks skill packs.
- Read the current active changelog/status enough to identify the prior Home tranche as closed/superseded for this pass.
- Inspected the new prototype folder structure and confirmed prototype pages/assets/data/screenshots are present under `northstar/`.

### Pending Tasks

- Create a new prototype-wide gap-analysis directory/checklist under `docs/northstar_gap_analysis/` because that directory is currently absent in the working tree.
- Capture current app Playwright screenshots for the same prototype pages/routes.
- Build a route/component/API mapping from prototype pages to the real app surfaces:
  - Command Center / Home
  - Discover
  - Stewardship
  - Glossary & CDEs
  - Lineage Atlas
  - Audit Evidence
  - Control Center
  - Asset 360 and Atlas AI cross-surface behavior
- Decide the first implementation tranche after the side-by-side audit and subagent findings.

### Validation Status

- No new prototype validation has run yet.
- Previous live Home validation remains historical evidence only and is not prototype-wide signoff.
- Databricks validation/deploy is pending for this tranche.

### Risks

- The worktree is already heavily dirty from earlier tranches, including many deleted historical docs/screenshots and generated Chrome profile files. Do not revert or restage unrelated changes.
- Prototype data is intentionally curated. Any production app parity must distinguish real UC-backed state, seeded demonstration metadata, and honest unavailable/degraded states.
- The app currently uses a different route/module taxonomy than the new prototype, so shell navigation and compatibility aliases may need careful migration without breaking existing deep links.

### Exact Next Actions

- Spawn the required read-only review lanes early so findings shape the implementation.
- Generate the prototype visual/functional checklist from `northstar/screenshots/*` and `northstar/pages/*.jsx`.
- Start a local app session, capture current screenshots with Playwright, and compare against the prototype.
- Update this status file again before the first code-edit tranche.

### Checkpoint - Prototype Checklist Created

- Added `docs/northstar_gap_analysis/prototype_contract.md`.
- The checklist covers global shell, Command Center, Discover, Stewardship, Glossary & CDEs, Lineage Atlas, Audit Evidence, Control Center, Asset 360, Atlas AI, validation matrix, and truth constraints.
- Required review lanes are running:
  - visual fidelity / product structure
  - truth / provenance / Databricks feasibility
  - functional workflow / regression coverage
  - frontend architecture / integration strategy
- Next action: add and run a focused Playwright baseline capture for the current app across the prototype route set.

### Checkpoint - Current App Prototype Baseline Captured

- Added `frontend/scripts/atlas_prototype_current_capture.mjs`.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Active deployed app readback: `atlas` is `RUNNING`, compute `ACTIVE`, deployment `01f142bd851310689d54f2f264850a47`, deployment state `SUCCEEDED`.
  - Live Playwright baseline capture against the deployed app with `DEFAULT` token -> passed.
- Evidence:
  - Report: `docs/northstar_visual_qa/prototype-current/prototype-current-report.json`.
  - Screenshots captured for `1536x1024` and `1440x900`: Command Center/Home, Discover, Stewardship, Glossary, CDE Registry, Lineage, Audit, Control Center, Asset 360.
  - Report summary: `18` captures, `0` page errors, `0` console warnings/errors, `0` request failures.
- Findings incorporated from review lanes:
  - Architecture: adapt production app; do not transplant `northstar` source or global CSS.
  - Visual/product: shell/nav/token authority blocks page parity and should be first.
  - Truth/provenance: preserve prototype structure, but unsupported prototype claims must be live-backed, seeded through real stores, or rendered degraded/unavailable.
  - Workflow: add deterministic E2E coverage for saved searches, advanced search, stewardship mutations, exports, evidence links, and cross-page Atlas AI before broad signoff.
- Next implementation checkpoint:
  - Shell and route taxonomy convergence first: prototype nav labels/groups, `Atlas AI` naming, route aliases, no broken existing routes.
  - Then global Atlas AI dock behavior and Command Center page structure.

### Checkpoint - Shell Implementation Started

- Starting global shell/navigation/header tranche.
- Planned code scope: `SideIconRail`, `GlobalHeader`, shell CSS, route aliases, shell tests, and the current screenshot capture route list.
- Validation planned immediately after: targeted Vitest for shell primitives and route behavior, focused lint/typecheck/build smoke as needed, then refreshed Playwright screenshots for affected shell routes.
- Risk: legacy tests encode old nav labels (`Home`, `Discovery`, `Governance`, `Admin`, `AI Copilot`); these will be updated to the prototype contract (`Command Center`, `Discover`, `Stewardship`, `Control Center`, `Atlas AI`) rather than preserving stale labels.

### Checkpoint - Shell Implementation Functional Validation

- Implemented prototype shell/navigation changes:
  - Sidebar now uses grouped prototype modules: Govern, Knowledge, Trust.
  - Primary labels now match the prototype taxonomy: `Command Center`, `Discover`, `Stewardship`, `Glossary & CDEs`, `Lineage Atlas`, `Audit Evidence`, `Control Center`.
  - Legacy `Asset 360` remains routable/deep-linkable but is no longer shown as a primary rail item because the prototype exposes it from search/results/drawers.
  - Topbar now uses a workspace breadcrumb and `Atlas AI` naming.
  - Prototype route aliases now canonicalize to production routes: `/command-center`, `/discover`, `/stewardship`, `/glossary-cdes`, `/lineage-atlas`, `/audit-evidence`, `/control-center`.
  - Legacy footer is visually hidden to match the prototype chrome; collapse remains functional through the sidebar user footer.
- Validation:
  - `npm test -- --run src/components/primitives/__tests__/SideIconRail.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx src/hooks/useAppRouteState.test.jsx` -> `3` files passed, `48` tests passed.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Focused `git diff --check` on shell/navigation/route/capture files -> passed.
- Next action: run lint/typecheck for the shell tranche, then start a local server and capture current screenshots against the prototype alias routes before subagent review.

### Checkpoint - Shell Local Visual Evidence

- Additional validation:
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - Post-width focused shell tests -> `2` files passed, `18` tests passed.
- Local screenshot evidence:
  - Started local Vite server at `http://127.0.0.1:3000`.
  - Captured prototype alias route set with `frontend/scripts/atlas_prototype_current_capture.mjs` into `docs/northstar_visual_qa/prototype-local-shell/`.
  - Report: `18` captures, `0` page errors. Local API calls return expected `404` because the standalone Vite server is not connected to the backend; screenshots use shell fallback and are visual-shell evidence only, not data parity evidence.
  - Manually inspected `docs/northstar_visual_qa/prototype-local-shell/command-center-1440x900.png`; shell now has prototype-style grouped sidebar, 56px topbar, workspace breadcrumb, `Atlas AI` button, and no visible footer.
- Review lanes:
  - Visual shell review and functional/regression shell review are running.
  - Product/truth shell review is running after closing completed earlier discovery agents to free agent capacity.
- Next action: incorporate review blockers, then proceed to Command Center page structure with status update before edits.

### Checkpoint - Command Center Implementation Started

- Starting Command Center/Home page structure tranche against `northstar/screenshots/prototype_command_center*`.
- Planned code scope: `frontend/src/components/HomePage.jsx`, supporting `northstar.css`, and Home/Command Center tests.
- Data contract decision:
  - Use existing `useCommandCenter`/`/atlas/command-center` payload fields (`estate`, `kpis`, `posture`, `topDomains`, `recentEvents`, `recentAssets`, `meta`) and visible asset seeds.
  - Derive catalog health only from visible asset records when available.
  - Render unsupported prototype claims (quality SLA, cryptographic audit readiness, risk-clean score, scheduled target confidence) as unavailable/degraded rather than inventing values.
- Validation planned immediately after: focused Home tests, lint/typecheck/build smoke, local Playwright screenshot update, then review-lane incorporation.

### Checkpoint - Shell Review Blockers Reopened

- Visual shell review returned blockers, so Command Center implementation is paused until global chrome is corrected.
- Shell blockers to address before page continuation:
  - Topbar action cluster must match prototype order: UC status, notification, help, primary `Atlas AI`; the topbar avatar should move out of the topbar.
  - Status pill must be prototype-shaped and truth-backed or explicitly degraded, not generic `Workspace`.
  - Global Atlas AI needs prototype persistent bottom-right FAB plus docked panel behavior; current floating dialog alone is insufficient.
  - Sidebar icon semantics need to match the prototype (`gauge`, `list-checks`, `book`, `shield-check`, `sliders` equivalents).
  - Sidebar footer must be user/account chrome, not a disguised collapse toggle.
  - `/glossary` should route to Glossary & CDEs, not Stewardship/Governance.
- Truth/provenance shell review also returned blockers:
  - Loading/unknown bootstrap state must not be coerced into green `live` shell status.
  - `Atlas AI` must not enable when provider state is unknown or backend/runtime status is unavailable.
  - Stewardship badge must not use truncated backlog length as a total open-work count.
- Validation after fixes: focused shell tests, lint/typecheck, local screenshots including closed/open Atlas AI global chrome, then re-review.

### Checkpoint - Shell Blocker Remediation Started

- Starting focused remediation of the shell blockers returned by the functional, visual, and truth review lanes.
- Code scope:
  - Route `/glossary` to Glossary & CDEs rather than Stewardship/Governance.
  - Remove the topbar profile chip and make the sidebar footer a real user/account menu.
  - Reorder the topbar to prototype shape: UC status, notifications, help, primary `Atlas AI`.
  - Prevent loading/unknown runtime state from rendering as green live status.
  - Disable `Atlas AI` unless the runtime reports a known evidence-backed AI provider state.
  - Add persistent bottom-right Atlas AI FAB behavior and update tests/accessible labels.
- Validation planned before page work resumes:
  - Focused AppFrame, shell primitive, topbar, route, and search tests.
  - Lint/typecheck after the focused tests pass.
  - Refreshed local Playwright shell screenshots, including closed/open Atlas AI chrome.

### Checkpoint - Shell Blocker Focused Tests Passed

- Implemented the first shell-blocker remediation pass:
  - `/glossary` and nested glossary paths now canonicalize to the Glossary & CDEs workspace (`/taxonomy`).
  - The topbar action cluster now follows the prototype order: UC status, notifications, help, primary `Atlas AI`.
  - The topbar profile chip was removed; the sidebar footer now owns the user/account menu and avatar upload affordance.
  - Loading/degraded/unavailable boot states no longer render as a green live UC status.
  - `Atlas AI` and the persistent bottom-right FAB are disabled unless the runtime reports a known available AI provider state.
  - The topbar search accessible label now matches the prototype placeholder text.
- Validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx src/hooks/useAppRouteState.test.jsx` -> `4` files passed, `63` tests passed.
- Next action: run lint/typecheck, capture refreshed local shell screenshots, and send the shell back to review before resuming Command Center work.

### Checkpoint - Shell Lint And Typecheck Passed

- Validation:
  - `npm run lint` -> passed after removing stale Home imports from the paused Command Center edit.
  - `npm run typecheck` -> passed after making optional shell callback props explicit.
- Local Vite server remains active at `http://127.0.0.1:3000` for refreshed browser evidence.
- Next action: capture the prototype alias route set locally and manually inspect closed/open Atlas AI chrome before requesting shell re-review.

### Checkpoint - Shell Local Screenshot Evidence Refreshed

- Refreshed local prototype alias screenshots after the shell blocker fixes:
  - `docs/northstar_visual_qa/prototype-local-shell/prototype-current-report.json`
  - `docs/northstar_visual_qa/prototype-local-shell/command-center-1440x900.png`
  - companion route screenshots for Discover, Stewardship, Glossary & CDEs, CDE Registry, Lineage Atlas, Audit Evidence, Control Center, and Asset 360 at `1536x1024` and `1440x900`.
- Report summary:
  - `18` captures, `0` page errors, local shell report `passed=true`.
  - Expected local Vite API `404` request failures remain because this capture intentionally used shell fallback without the backend.
  - Hidden footer controls are no longer counted as visible controls by the capture script.
- Manual screenshot inspection:
  - Sidebar grouping, labels, active state, profile footer, topbar status/search/help/Atlas AI order, disabled Atlas AI state, and persistent bottom-right FAB now match the prototype shell shape much more closely.
  - Local screenshots still show the shell loading fallback instead of hydrated page content; live deployed evidence is still required for page/content signoff.
- Next action: send refreshed shell evidence to the review lanes and incorporate any remaining blockers before resuming Command Center page work.

### Checkpoint - Command Center Styling Resumed

- Shell re-review is running in parallel.
- Resuming the Command Center/Home prototype tranche using the already-started `HomePage.jsx` prototype layout.
- Code scope for this checkpoint:
  - Add production CSS for the new `gh-command-center-*` layout.
  - Replace stale Home tests that targeted the old Home mockup with tests for the prototype Command Center contract.
  - Preserve truthful unavailable states for unsupported prototype claims instead of inventing quality, risk, CDE, or target metrics.
- Validation planned after this checkpoint:
  - Focused Home tests.
  - Lint/typecheck.
  - Local screenshot capture of Command Center shell/content.

### Checkpoint - Command Center Test Fix Started

- Focused blocker: the new Command Center KPI test was matching repeated text outside the KPI row.
- Edit scope: `frontend/src/components/HomePage.test.jsx` only.
- Validation planned immediately after: focused Home tests, then the combined shell/Home focused suite.

### Checkpoint - Command Center Focused Test Passed

- Fixed the KPI assertion by scoping it to the `Governance summary metrics` region.
- Validation:
  - `cd frontend && npm test -- --run src/components/HomePage.test.jsx` -> `1` file passed, `7` tests passed.
- Next action: run the combined Command Center and shell-focused regression suite, then lint/typecheck.

### Checkpoint - Command Center And Shell Regression Passed

- Validation:
  - `cd frontend && npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx src/hooks/useAppRouteState.test.jsx` -> `5` files passed, `70` tests passed.
- Next action: run frontend lint and typecheck before refreshing screenshots.

### Checkpoint - Command Center Lint And Typecheck Passed

- Validation:
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run typecheck` -> passed.
- Next action: refresh local Playwright screenshots for the prototype route set, then inspect Command Center visual fit.

### Checkpoint - Prototype Local Screenshot Refresh

- Refreshed local prototype-route screenshots after the Command Center structure/test fix:
  - `docs/northstar_visual_qa/prototype-local-command-center/prototype-current-report.json`
  - route screenshots for Command Center, Discover, Stewardship, Glossary & CDEs, CDE Registry, Lineage Atlas, Audit Evidence, Control Center, and Asset 360 at `1536x1024` and `1440x900`.
- Report summary:
  - `18` captures, `0` page errors, `0` console warnings/errors, `passed=true`.
  - Local request failures are expected API `404`s because this was Vite-only shell fallback evidence, not hydrated backend evidence.
- Review blocker follow-up:
  - Functional/regression review found the public deployed QA commands still pointed at legacy selector scripts.
  - Remediation started: convert `atlas_comprehensive_qa.mjs` and `atlas_structural_identity.mjs` into compatibility wrappers over the current live route validator and prototype capture.

### Checkpoint - Deployed QA Wrapper Remediation Started

- Code scope:
  - `frontend/scripts/atlas_comprehensive_qa.mjs`
  - `frontend/scripts/atlas_structural_identity.mjs`
- Decision: keep `npm run qa:deployed` and `npm run identity:deployed` command names stable, but remove retired selector assertions by delegating to the current validators.
- Validation planned: `node --check` for both wrappers, focused npm script smoke with local fallback for `identity:deployed`, and route-validator syntax check.

### Checkpoint - Atlas AI Open-State Evidence Started

### Checkpoint - Command Center Functional Remediation Started

- Timestamp: 2026-04-28 06:54 EDT.
- Review-input blockers being addressed before broader page work:
  - `Export brief` and `Present mode` are currently placeholder browser actions rather than product-visible Command Center state changes.
  - The coverage trend range is static (`12w`) instead of a functional `12w / 26w / 52w` control.
  - Backed KPI `deltaText` values are ignored, causing supported trend deltas to degrade to generic unavailable copy.
  - Top catalog and activity rows are visual-only even though the prototype implies click-through workflows.
- Code scope: `frontend/src/components/HomePage.jsx`, `frontend/src/components/HomePage.test.jsx`, and Command Center CSS in `frontend/src/styles/northstar.css`.
- Validation planned immediately after:
  - `npm test -- --run src/components/HomePage.test.jsx`
  - focused shell/Home regression if Home tests pass
  - `npm run lint`
  - `npm run typecheck`

### Checkpoint - Command Center Focused Functional Tests Passed

- Implemented bounded Command Center workflow fixes:
  - `Export brief` now emits a downloadable JSON brief with backed posture, KPI, catalog, and activity evidence instead of invoking print.
  - `Present mode` now toggles a visible Command Center state with `aria-pressed` instead of a browser-only fullscreen attempt.
  - Coverage trend has functional `12w / 26w / 52w` controls.
  - KPI cards and "What changed today" now honor backed `deltaText` values.
  - Top catalog rows route to Discover and activity rows route to Audit Evidence.
- Validation:
  - `npm test -- --run src/components/HomePage.test.jsx` -> `1` file passed, `9` tests passed.
- Broader validation:
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx src/hooks/useAppRouteState.test.jsx` -> `5` files passed, `72` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
- Next action: refresh focused local Playwright screenshots for the Command Center and then continue page-by-page prototype parity work.

### Checkpoint - Hydrated Prototype Screenshot Capture Started

- Timestamp: 2026-04-28 07:03 EDT.
- Problem with existing evidence: local Vite screenshots without a backend only show shell/loading states, which is not valid page-content visual QA.
- Planned support-code scope:
  - Add an explicit mock-API mode to `frontend/scripts/atlas_prototype_current_capture.mjs`.
  - Keep this mode opt-in and clearly reported as synthetic local evidence, separate from live Databricks evidence.
  - Add route filtering so focused page screenshots can be refreshed quickly after each tranche.
- Validation planned:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - Focused Command Center capture at `1440x900`, `1280x720`, and `1536x1024` with hydrated deterministic data.

### Checkpoint - Hydrated Command Center Evidence Captured

- Support-code changes:
  - `frontend/scripts/atlas_prototype_current_capture.mjs` now supports opt-in `GOVAT_PROTOTYPE_MOCK_API=1` and `GOVAT_PROTOTYPE_ROUTES=...`.
  - The report records `mockApi: true` so synthetic local visual evidence cannot be confused with live Databricks evidence.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=command-center GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-command-center-functional GOVAT_PROTOTYPE_SETTLE_TIMEOUT_MS=30000 GOVAT_PROTOTYPE_TEXT_SETTLE_TIMEOUT_MS=30000 node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-command-center-functional/prototype-current-report.json`.
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1536x1024.png`.
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1440x900.png`.
  - `docs/northstar_visual_qa/prototype-command-center-functional/command-center-1280x720.png`.
  - Report summary: `passed=true`, `mockApi=true`, `3` captures, `0` request failures, `0` page errors. Console output only contains the existing React Router v7 future-flag warnings.
- Review status:
  - Command Center visual/product review requested.
  - Functional/regression review requested.
  - Truth/provenance review requested with the explicit caveat that this is local mock-API evidence, not live Databricks signoff.

### Checkpoint - Discover Prototype Remediation Started

- Starting the Discover page tranche while Command Center review runs in parallel.
- Known prototype blockers from review:
  - Current Discover still follows the legacy Databricks-helper structure instead of the prototype search-first trusted-data architecture.
  - Results should read as trust-ranked cards/list rows with certification/classification/CDE/PII chips and trust scores.
  - Saved searches and Advanced controls must be functional, not static labels.
  - Result click-through must open a useful Asset 360/detail path instead of a dead preview-only state.
  - Synthetic local screenshot evidence must hydrate real-looking asset data, while live behavior must remain permission-aware and truthful.
- Planned code scope for this checkpoint:
  - Inspect current `DiscoveryWorkspace` and prototype `northstar/pages/discover.jsx`.
  - Make the smallest production-aligned architecture changes that move Discover toward the prototype while preserving existing API contracts.
  - Add/adjust focused Discover tests before screenshot capture.

### Checkpoint - Discover Focused Tests Passed

- Implemented first Discover prototype-alignment pass:
  - Updated the Discover hero title/copy/placeholder to the prototype contract.
  - Added functional `Saved searches` control and popover that applies backed discovery filters/query clauses.
  - Added visible prototype-style filter rail for Certification, Domain, Classification, and Attributes without changing the discovery hook contract.
  - Restyled result rows into card-like trust-ranked rows while preserving existing selection, menu, favorite, lineage, and Asset 360 actions.
  - Extended mock-API capture support with hydrated discovery search, asset detail/availability, and lineage responses.
- Validation:
  - `npm run lint` -> passed.
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx` -> `1` file passed, `34` tests passed.
  - `npm run typecheck` -> passed.
- Next action: run syntax check for the updated capture script and capture hydrated Discover screenshots for visual review.

### Checkpoint - Hydrated Discover Evidence Captured

- Additional Discover adjustment:
  - Hid the legacy always-on asset preview rail in the prototype Discover layout so the search/results column does not overlap controls at `1280x720`.
  - Asset 360 remains reachable through the existing result/menu actions; this only changes the prototype Discover default layout.
- Validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.test.jsx` -> `1` file passed, `34` tests passed after the responsive change.
  - `npm run lint` -> passed after the responsive change.
  - `npm run typecheck` -> passed after the responsive change.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-discover-functional GOVAT_PROTOTYPE_SETTLE_TIMEOUT_MS=30000 GOVAT_PROTOTYPE_TEXT_SETTLE_TIMEOUT_MS=30000 node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-discover-functional/prototype-current-report.json`.
  - `docs/northstar_visual_qa/prototype-discover-functional/discover-1536x1024.png`.
  - `docs/northstar_visual_qa/prototype-discover-functional/discover-1440x900.png`.
  - `docs/northstar_visual_qa/prototype-discover-functional/discover-1280x720.png`.
  - Report summary: `passed=true`, `mockApi=true`, `3` captures, `0` request failures, `0` page errors.
- Remaining caveat:
  - This is local hydrated mock-API evidence only. Live Databricks screenshots remain required before page signoff.

### Checkpoint - Command Center Lower-Viewport Evidence Blocker Started

- Review finding:
  - Command Center code/functionality was not blocked, but visual evidence did not prove lower-section parity against `prototype_home2.png`.
  - Root cause: the page uses an internal `.gh-main` scroll container, so viewport and full-page screenshots were byte-equivalent and did not capture lower Command Center rows.
- Planned support-code scope:
  - Add opt-in internal main-scroll screenshot capture to `frontend/scripts/atlas_prototype_current_capture.mjs`.
  - Rerun hydrated Command Center capture with bottom-scroll screenshots.

- Visual review blocker: closed shell chrome was accepted, but no open global Atlas AI screenshot existed.
- Code scope: add a dedicated Playwright QA capture for the Atlas AI open shell state using local fixture bootstrap data only.
- Truth note: this fixture proves UI behavior/geometry only; it is not live Databricks or Genie evidence.
- Validation planned: script syntax check, local capture with the current Vite server, and report/screenshot inspection.

### Checkpoint - Shell Review Blockers Remediated Locally

- Deployed QA wrapper remediation:
  - `frontend/scripts/atlas_comprehensive_qa.mjs` now delegates to `atlas_route_live_validation.mjs`.
  - `frontend/scripts/atlas_structural_identity.mjs` now delegates to `atlas_prototype_current_capture.mjs`.
  - `node --check` passed for both wrappers plus `atlas_route_live_validation.mjs`, `atlas_prototype_current_capture.mjs`, and `atlas_shell_ai_open_capture.mjs`.
  - Stale selector scan found no retired shell selectors in the two public wrapper scripts.
- Public command smoke:
  - `cd frontend && GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_CAPTURE_OUT=../docs/northstar_visual_qa/prototype-identity-wrapper-smoke GOVAT_PROTOTYPE_SHELL_FALLBACK=1 GOVAT_PROTOTYPE_SETTLE_TIMEOUT_MS=1500 GOVAT_PROTOTYPE_TEXT_SETTLE_TIMEOUT_MS=1500 npm run identity:deployed -- http://127.0.0.1:3000` -> passed with `18` captures.
- Atlas AI open-state fixture evidence:
  - Added `frontend/scripts/atlas_shell_ai_open_capture.mjs`.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_AI_OPEN_CAPTURE_OUT=docs/northstar_visual_qa/prototype-ai-open node frontend/scripts/atlas_shell_ai_open_capture.mjs` -> passed.
  - Evidence: `docs/northstar_visual_qa/prototype-ai-open/atlas-ai-open-report.json` and `docs/northstar_visual_qa/prototype-ai-open/atlas-ai-open-1440x900.png`.
  - Report confirms open dialog, enabled Atlas AI trigger, no console warnings, no page errors, and no request failures.
- Next action: send these artifacts back to the review lanes and incorporate any final shell blocker before page-by-page implementation continues.

### Checkpoint - Atlas AI Docked Default Fix Started

- Visual re-review kept one blocker open:
  - The Atlas AI panel opened as a top-right floating dialog.
  - The prototype opens as a right-side, bottom-docked AI rail/popover above the FAB and avoids covering primary content.
- Code scope:
  - `frontend/src/components/AppFrame.jsx`: set the default AI chat geometry to the prototype dock position and expose `data-ai-open`.
  - `frontend/src/styles/northstar.css`: widen/tall the panel and reserve a desktop right gutter while Atlas AI is open.
- Validation planned immediately after:
  - Focused AppFrame tests.
  - Lint/typecheck.
  - Refreshed `atlas_shell_ai_open_capture.mjs` screenshot/report.

### Checkpoint - Atlas AI Docked Default Validated Locally

- Implemented:
  - Default open panel geometry is now `440px` wide, `640px` tall, bottom-anchored above the FAB.
  - The app root exposes `data-ai-open`.
  - Desktop `.gh-main` reserves a right gutter while Atlas AI is open so the panel is a docked rail/popover rather than a modal covering primary content.
  - Command Center state-card layout adapts while the AI rail is open.
- Validation:
  - `cd frontend && npm test -- --run src/components/AppFrame.test.jsx` -> `1` file passed, `14` tests passed.
  - `cd frontend && npm run lint` -> passed.
  - `cd frontend && npm run typecheck` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_AI_OPEN_CAPTURE_OUT=docs/northstar_visual_qa/prototype-ai-open-docked node frontend/scripts/atlas_shell_ai_open_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-ai-open-docked/atlas-ai-open-report.json`
  - `docs/northstar_visual_qa/prototype-ai-open-docked/atlas-ai-open-1440x900.png`
- Next action: ask visual review to re-check the docked open-state evidence.

### Checkpoint - Identity Gate Hardening Started

- Functional/regression review cleared stale selector remediation but found that `identity:deployed` could still false-green because `atlas_prototype_current_capture.mjs` wrote `passed=false` without exiting nonzero.
- Code scope: `frontend/scripts/atlas_prototype_current_capture.mjs`.
- Change: after the final report flush, the script exits nonzero when `report.passed` is false.
- Validation planned: syntax check plus public `identity:deployed` smoke.

### Checkpoint - Identity Gate Hardened

- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `node --check frontend/scripts/atlas_structural_identity.mjs` -> passed.
  - `cd frontend && GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_CAPTURE_OUT=../docs/northstar_visual_qa/prototype-identity-wrapper-smoke-hardened GOVAT_PROTOTYPE_SHELL_FALLBACK=1 GOVAT_PROTOTYPE_SETTLE_TIMEOUT_MS=1500 GOVAT_PROTOTYPE_TEXT_SETTLE_TIMEOUT_MS=1500 npm run identity:deployed -- http://127.0.0.1:3000` -> passed with `18` captures.
- Next action: send hardening evidence back to functional/regression review.

### Checkpoint - Open Atlas AI Rail Clipping Fix Started

- Visual re-review accepted the docked Atlas AI geometry, but still blocks shell signoff because the open-state screenshot clips the far-left rail/logo/nav text.
- Initial inspection found legacy `shell-rail.css` selectors still declaring `.gh-side-rail.gh-side-rail { overflow: visible !important; }` after the North Star rail block, which can override the intended fixed-width, clipped, left-anchored rail geometry.
- Code scope:
  - `frontend/src/styles/northstar.css`: add a final high-specificity rail authority block after legacy shell rules so the rail stays left anchored, full width, and clipped inside its grid column.
  - `frontend/scripts/atlas_shell_ai_open_capture.mjs`: add measurable rail/logo/nav rectangles and pass criteria so the screenshot cannot false-green while the rail is clipped.
- Validation planned:
  - `node --check frontend/scripts/atlas_shell_ai_open_capture.mjs`
  - focused AppFrame/shell tests if CSS behavior changed enough to warrant component coverage
  - refreshed `docs/northstar_visual_qa/prototype-ai-open-docked/` screenshot/report
  - visual review re-check before resuming page-by-page implementation.

### Checkpoint - Open Atlas AI Rail Clipping Fix Validated Locally

- Root cause confirmed by instrumented Playwright capture:
  - Opening Atlas AI made the root `.gh-app` scroll horizontally to `scrollLeft=66` while `window.scrollX` stayed `0`, clipping the rail at `left=-66`.
  - The logo image, first nav icon, and first nav label were therefore partially or fully off-screen even though the previous report passed.
- Implemented:
  - The North Star app grid now uses `overflow: clip !important` so the root shell cannot become a horizontal scroll container.
  - The rail has a final high-specificity North Star authority block: left anchored, fixed to the rail grid area, `240px` wide, clipped inside its column, and not affected by legacy sticky rail rules.
  - The open Atlas AI capture now records html/body/root/app/rail/logo/nav rectangles, root/app/main scroll metrics, and fails if the rail is clipped, if `.gh-app.scrollLeft` is nonzero, or if the page content overlaps the docked AI panel.
  - The right AI-open content gutter was increased so the Command Center content ends before the docked Atlas AI panel.
- Validation:
  - `node --check frontend/scripts/atlas_shell_ai_open_capture.mjs` -> passed.
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/primitives/__tests__/SideIconRail.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx` -> `3` files passed, `32` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_AI_OPEN_CAPTURE_OUT=docs/northstar_visual_qa/prototype-ai-open-docked node frontend/scripts/atlas_shell_ai_open_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-ai-open-docked/atlas-ai-open-report.json`
  - `docs/northstar_visual_qa/prototype-ai-open-docked/atlas-ai-open-1440x900.png`
  - Report confirms rail `left=0`, first nav label `left=51`, main `left=240`, content `right=952`, AI panel `left=978`, and `.gh-app.scrollLeft=0`.
- Next action: send refreshed evidence to the visual/product review lane and resume page-by-page prototype implementation only after shell signoff or a recorded deferral.

### Checkpoint - Prototype Route Screenshot Refresh Started

- Added the required compact `1280x720` viewport to `frontend/scripts/atlas_prototype_current_capture.mjs` so prototype route evidence covers `1536x1024`, `1440x900`, and `1280x720`.
- Spawned/readied page audit lanes:
  - Command Center/Home
  - Discover/Asset 360
  - Stewardship/Glossary/CDE
  - Lineage/Audit/Control via the existing truth/provenance reviewer because the agent thread cap was reached.
- Validation planned:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - local prototype route capture with shell fallback into a fresh evidence directory.

## Superseded Tranche - Home Second Reopen (Closed)

- Home fidelity has been reopened again from fresh product-owner screenshots. Previous Home evidence remains useful history, but it is not accepted as closeout for this second pass.
- Scope for this pass is limited to the eight latest Home defects:
  - replace the custom wordmark with the actual Entrada logo asset from `/Users/entrada-mac/Documents/branding/Entrada_2026_Logo.png`
  - reduce the excessive vertical gap between the subtitle and KPI cards
  - make Home cards darker while keeping the overall background lighter and shell chrome/borders darkest
  - unify the collapse border, bottom border, top border, and left menu color
  - repair the Atlas AI rail width/layout so the input is larger and bottom-anchored, remove the ready-state chip, make `More suggestions` functional, and keep suggestions out of the way after a question
  - repair floating `AI Copilot` answer formatting, remove awkward `Genie said... please review` phrasing from the displayed text, and add corner resize behavior
  - restore KPI sparkline and change-rhythm visibility wherever backed data exists, without inventing unsupported values
  - replace the current drawn globe with a more realistic rotating globe with continents/lights if feasible in React/Vite
- Subagent review lanes assigned for feedback coverage, visual/product, regression/ripple, and truth/provenance. They are read-only and will provide blockers/signoff criteria while implementation proceeds.
- Frontend checkpoint completed for the second reopened Home pass:
  - Copied the actual Entrada 2026 logo asset into the frontend brand assets and wired the side rail to use it.
  - Replaced the decorative Home SVG globe with a native React canvas globe that rotates slowly and draws simplified real continent shapes, city lights, latitude/longitude lines, and governed-network arcs.
  - Reduced Home hero height/gaps so the subtitle and KPI row sit closer together.
  - Darkened card surfaces and normalized the chrome/footer/side-rail/collapse colors back to the same darkest navy token.
  - Widened the Home Atlas AI rail, removed the ready-state message, bottom-anchored a larger input, made `More suggestions` cycle prompts, and reduces suggestions to one once a conversation starts.
  - Updated Home and floating Atlas AI messages to render the existing safe Markdown subset instead of exposing raw Markdown symbols.
  - Cleaned displayed Genie boilerplate such as `Genie returned... Review generated SQL...` while preserving evidence counts and grounded answer content.
  - Added CSS resize support to the floating `AI Copilot` dialog.
  - Restored visible truthful KPI rhythm by showing neutral trend-unavailable status when a backed trend is absent and preserving sparklines for backed metric histories.
- Focused validation after the frontend checkpoint:
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run typecheck` -> passed.
  - `git diff --check` on the focused Home/logo/chat/style files -> passed.
- Broader frontend validation after the frontend checkpoint:
  - `npm run lint` -> passed.
  - `npm run build` -> passed and emitted the new Entrada logo asset in `dist/assets/entrada-2026-logo-*.png`.
- Next checkpoint in progress:
  - Update the Home Playwright QA gate for the actual Entrada PNG logo, canvas-based rotating globe, cleaned Markdown-rendered Atlas AI answers, functional `More suggestions`, prompt reduction after a question, and floating chat resize contract before deploying this second reopened Home pass.
- Home QA gate update validation:
  - `node --check frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
- Local browser visual checkpoint in progress:
  - Start a local Vite server with intercepted live-shaped Home/Atlas AI API payloads.
  - Capture Home screenshots and verify logo asset loading, canvas-globe pixels, spacing/color token order, Atlas rail prompt/input behavior, and floating AI resize/Markdown cleanup before the Databricks deploy cycle.
- Globe fidelity escalation in progress:
  - Replace the hand-simplified canvas land shapes with real low-resolution world-atlas land geometry so the Home globe has actual rotating continent outlines and can still render lights/arcs without external image loading.
- Globe fidelity escalation validation:
  - Added `world-atlas` and `topojson-client` so the canvas globe renders real land geometry instead of hand-simplified continent polygons.
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run lint` -> passed.
  - `npm run build` -> passed; Home bundle now includes the geography-backed globe code and the actual Entrada PNG logo asset.
- Local browser visual checkpoint completed after the compact-rail input fix:
  - Initial local Playwright probe failed because it was launched from the repo root where Playwright is not installed; rerun from `frontend` succeeded.
  - The local browser gate also found and fixed a real compact-height regression where the 1280x720 media rule overrode `margin-top: auto` and shrank the Atlas input.
  - `docs/northstar_visual_qa/home-current/home-local-second-pass-report.json` -> passed.
  - Screenshots captured: `home-local-second-pass-1536x1024.png`, `home-local-second-pass-1440x900.png`, `home-local-second-pass-1280x720.png`, `home-local-second-pass-ai-1440x900.png`, and `home-local-second-pass-floating-ai.png`.
  - Local metrics passed for actual logo asset loading, nonblank geography-backed canvas globe, subtitle-to-KPI gap, six KPI sparklines, prompt cycling, prompt reduction after answer, cleaned Atlas AI answer formatting, and resizable floating AI chat.
- Post-local frontend validation after the CSS/dependency fixes:
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed.
  - `npm audit --omit=dev --json` -> `0` production vulnerabilities; the install-time moderate warnings are dev-transitive only and not in the shipped dependency set.
- Checklist/evidence tracking update:
  - Added the 2026-04-27 second Home pass to `docs/northstar_gap_analysis/home_todo.md` with S01-S08 mapped to code/evidence, SV01-SV07 validation gates, local screenshot paths, remaining live gates, and no local deferrals.
- Review/deploy checkpoint in progress:
  - Recheck prompts sent to the required review lanes after the current implementation, replacing the stale pre-patch blocker findings.
  - Starting Databricks `DEFAULT` bundle validation, summary, deploy, and app deploy for the second Home pass. The project-target app deploy form must be used; direct `apps deploy atlas` is rejected for this repo because it can drop bundle target environment injection.
- Databricks pre-deploy gates:
  - Focused `git diff --check` on the current Home/logo/chat/style/package/docs/status files -> passed.
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
- Databricks deploy/readback:
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
  - Active deployment: `01f142b60f8e1725a06a980d1436665a`; app state `RUNNING`; compute state `ACTIVE`; local frontend build manifest `frontend-fba50e31cace`.
  - Runtime readback confirms `GOVAT_CATALOG=datapact`, `GOVAT_SCHEMA=atlas`, warehouse `da02d15a9490650b`, runtime `live`, store `live`, Lakebase dual-write state `active`, and failed Lakebase writes `0`.
  - Authenticated command-center readback passed: state `available`, governed assets `792`, certified critical assets `13`, metadata coverage `11.7`, open stewardship actions `5` with sparkline `[0,0,0,0,0,5]`, policy exceptions `4` with sparkline `[0,0,0,0,0,4]`, audit readiness unavailable, top-domain scores `95.8/91.7/87.5/87.5/83.3`, and varied heatmap values `[0.0,6.1,9.3,9.7,54.0,66.7,100.0]`.
- Live Home QA on deployment `01f142b60f8e1725a06a980d1436665a` passed before final compact polish:
  - `GOVAT_DEPLOYMENT_ID=01f142b60f8e1725a06a980d1436665a GOVAT_BUILD_ID=frontend-fba50e31cace node frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - Fresh live screenshots/report captured for `1536x1024`, `1440x900`, `1280x720`, collapsed rail, profile menu, Home AI response, floating AI response, and side-by-side mockup comparison.
  - Manual review then caught a compact 1280-only visual polish issue that the mechanical gate did not fail: the posture title could truncate and the heatmap row height was too tall. A scoped 1280 CSS patch is in progress and must be rebuilt/redeployed/revalidated before final signoff.
- Compact 1280 polish validation:
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed with build `frontend-54a9bb1f2807`.
  - Focused `git diff --check` for the current Home/style/package/docs/status files -> passed.
- Intermediate compact-polish redeploy/readback, superseded by the later resize-containment and visual-blocker deployments:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
  - Active deployment: `01f142b7ed06163dabe62bfe99ba3285`; app state `RUNNING`; compute state `ACTIVE`; final build `frontend-54a9bb1f2807`.
  - Runtime readback remains `live` / `live`, `datapact.atlas`, Lakebase dual-write state `active`, failed writes `0`.
  - Command-center readback remains available with backed open-stewardship and policy-exception sparklines, audit readiness unavailable, and varied top-domain scores.
- Intermediate live Home QA on deployment `01f142b7ed06163dabe62bfe99ba3285`, superseded by deployment `01f142bd851310689d54f2f264850a47`:
  - `GOVAT_DEPLOYMENT_ID=01f142b7ed06163dabe62bfe99ba3285 GOVAT_BUILD_ID=frontend-54a9bb1f2807 node frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - `docs/northstar_visual_qa/home-current/home-live-report.json` now records deployment `01f142b7ed06163dabe62bfe99ba3285`, build `frontend-54a9bb1f2807`, all three viewport captures passed, no page errors, no console warnings, and all scripted interactions passed.
  - Final live evidence verifies actual logo asset loaded, canvas globe present/nonblank, footer-safe/no-scroll/no-horizontal-overflow layout, bottom alignment delta <= `0.015625`, collapsed rail icon centering, footer route behavior, profile avatar upload affordance, draggable/resizable floating AI chat, functional `More suggestions`, prompt collapse after answer, cleaned displayed answer text, and Genie-backed Atlas AI responses with `provider=genie`, `source=databricks-genie`, evidence count `1`.
  - This checkpoint exposed the need for a later reviewer re-check and is retained as history only; current SV07 state is complete below.
- Regression recheck remediation in progress:
  - Current regression reviewer signoff is blocked on Git-visible reproducibility for new logo/QA evidence files and a stronger floating-chat resize containment proof.
  - Added floating-chat ResizeObserver/drag-size clamping in `AppFrame.jsx` so native corner resize keeps the dialog in viewport.
  - Updated `frontend/scripts/atlas_home_live_qa.mjs` to physically drag the floating chat resize handle, verify width/height change, and assert right/bottom viewport containment.
  - Marked the actual logo asset, live QA script, and local second-pass evidence artifacts with Git intent-to-add so reviewer `git ls-files`/diff checks can see the reproducibility-critical new files without staging a commit.
- Regression remediation validation:
  - `node --check frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - Focused `git diff --check` for `AppFrame.jsx`, `atlas_home_live_qa.mjs`, status/checklist, logo, and local report files -> passed.
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed with build `frontend-34b8cda77d6d`.
- Intermediate resize-containment redeploy/readback, superseded by the later visual-blocker deployment:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
  - Active deployment: `01f142ba8d3518979b00189e8944f2fb`; app state `RUNNING`; compute state `ACTIVE`; final build `frontend-34b8cda77d6d`.
  - Runtime readback remains `live` / `live`, `datapact.atlas`, Lakebase dual-write state `active`, failed writes `0`.
  - Command-center readback remains available with backed open-stewardship and policy-exception sparklines, audit readiness unavailable, and varied top-domain/heatmap scores.
- Intermediate live Home QA on deployment `01f142ba8d3518979b00189e8944f2fb`, superseded by deployment `01f142bd851310689d54f2f264850a47`:
  - `GOVAT_DEPLOYMENT_ID=01f142ba8d3518979b00189e8944f2fb GOVAT_BUILD_ID=frontend-34b8cda77d6d node frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - `docs/northstar_visual_qa/home-current/home-live-report.json` records deployment `01f142ba8d3518979b00189e8944f2fb`, build `frontend-34b8cda77d6d`, all three viewport captures passed, no page errors, no console warnings, and all scripted interactions passed.
  - Final live evidence verifies actual logo asset loaded, canvas globe present/nonblank, footer-safe/no-scroll/no-horizontal-overflow layout, bottom alignment delta <= `0.015625`, collapsed rail icon centering, footer route behavior, profile avatar upload affordance, draggable/resizable floating AI chat, functional `More suggestions`, prompt collapse after answer, cleaned displayed answer text, and Genie-backed Atlas AI responses with `provider=genie`, `source=databricks-genie`, evidence count `1`.
  - Floating `AI Copilot` resize proof now physically drags the native corner resize handle: `resizeMode=both`, `resizeDelta=176`, bounds changed from `392x560` to `491x637`, and the resized dialog remains contained in the viewport.
  - Feedback/regression/truth reviewer re-checks passed against this exact deployment/build.
  - Visual/product reviewer re-check found three concrete evidence defects at this intermediate checkpoint: right-rail Atlas AI long FQN wrapping, `1280x720` bottom-card title truncation, and the AI answer-state screenshot label/viewport mismatch. Those blockers are remediated in the final checkpoint below.
- Visual-blocker remediation checkpoint:
  - Added wrapping safeguards for Home rail and floating Atlas AI Markdown answer bodies so long FQNs cannot run into the right edge.
  - Tuned the compact-height `Recent High-Priority Events` header so the title fits at `1280x720` without ellipsis.
  - Hardened `frontend/scripts/atlas_home_live_qa.mjs` to fail if bottom-card header text overflows, to fail if the Atlas AI answer body overflows its rail container, and to capture `home-live-ai-1440x900.png` at a real `1440x900` viewport.
  - `node --check frontend/scripts/atlas_home_live_qa.mjs` -> passed.
  - Focused `git diff --check` for the current visual-blocker files -> passed.
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `34` tests passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed with build `frontend-e11d3b7cac8f`.
  - Databricks redeploy/readback for build `frontend-e11d3b7cac8f`:
    - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
    - Active deployment: `01f142bd851310689d54f2f264850a47`; app state `RUNNING`; compute state `ACTIVE`.
  - Final live Home QA after visual-blocker remediation:
    - `GOVAT_DEPLOYMENT_ID=01f142bd851310689d54f2f264850a47 GOVAT_BUILD_ID=frontend-e11d3b7cac8f node frontend/scripts/atlas_home_live_qa.mjs` -> passed.
    - `docs/northstar_visual_qa/home-current/home-live-report.json` records deployment `01f142bd851310689d54f2f264850a47`, build `frontend-e11d3b7cac8f`, all three viewport captures passed, no page errors, no console warnings, and all scripted interactions passed.
    - New hard gates passed: `headerTextFits.recentEvents=true` at `1280x720`, rail `assistantTextFits=true`, and the answer-state screenshot records viewport `{width: 1440, height: 900}`.
  - Final reviewer signoff passed against deployment `01f142bd851310689d54f2f264850a47`, build `frontend-e11d3b7cac8f`:
    - Feedback coverage: prior final signoff remains applicable; all S01-S08 items are mapped to code/evidence.
    - Regression/ripple: SIGNOFF after confirming Git-visible assets/scripts/evidence, resize containment, header-fit hard gates, focused validation, and live QA.
    - Visual/product fidelity: SIGNOFF after confirming the actual logo, geography-backed canvas globe, 1280 bottom-header fit, true 1440 AI answer screenshot, AI answer wrapping, and interaction evidence.
    - Truth/provenance: SIGNOFF after confirming active deployment/build alignment, Genie-backed Atlas AI evidence, unsupported KPI histories remaining unavailable, and no fake metric/workflow claims.
  - SV07 is complete; there are no remaining second-pass Home must-fix blockers.

## Previous Tranche State

- Home visual/performance parity was reopened from live user evidence. The reopened Home defects are implemented, validated against the active Databricks app deployment, and signed off by the required review lanes.
- Scope is limited to the current Home defects called out by the product owner:
  - bottom-card and Atlas AI rail depth/alignment mismatch
  - slow initial data load without a credible loading state
  - weak or overly uniform real/synthetic governance quality signals
  - missing KPI sparkline/growth rhythm
  - globe position/fidelity gap
  - color-zone drift toward near-black instead of navy/ocean-blue layering
  - Entrada wordmark scale/geometry mismatch
  - Atlas AI rail not behaving like a real chat surface
  - slow Atlas AI responses without visible progress
  - top-right `AI Copilot` button must open a draggable, closable Atlas AI chat window
- Feedback-coverage review criteria were incorporated: every product-owner complaint maps to `docs/northstar_gap_analysis/home_todo.md` reopened items with live evidence or truth-backed rationale.
- Visual/product and regression/ripple review findings were implementation inputs:
  - `AI Copilot` must stop routing users to Home and instead open a fixed, draggable, closable chat from shell chrome.
  - Home rail must become a readable chat surface with separate response/transcript, prompt, input, progress, and disclaimer regions.
  - Home hydration must be visible when seed/bootstrap data is displayed while the live command-center request is still pending.
  - Bottom-card and Atlas AI depth need a shared grid contract rather than fixed bottom-card heights plus a 100% rail.
  - Color/globe/logo updates must be verified visually; old Home live report assertions are not accepted as closeout evidence.
- Frontend checkpoint completed:
  - Added shared Atlas AI conversation state with abort/stale-response protection.
  - Home now displays seed-data hydration progress while preserving the North Star panels.
  - Home Atlas AI rail now uses a transcript-style chat area, visible progress, prompt/input separation, and non-clamped answer text.
  - Header `AI Copilot` now opens a fixed, draggable, closable Atlas AI chat dialog without routing away from the current surface.
  - KPI cards now reserve sparkline/progress rhythm with truthful empty styling until backed data is present.
  - Home card/rail layout now uses shared grid row heights so bottom-card and Atlas AI lower edges can align.
  - Color-zone, globe placement, and wordmark scale updates are validated in the final live screenshot report.
- Backend/sample-data checkpoint completed:
  - command-center KPIs now emit backed `delta`, `deltaTone`, and `sparkline` for open stewardship actions and policy exceptions when governance request/audit timestamps are available.
  - governed asset and audit-readiness unsupported histories remain unavailable/no-delta rather than invented.
  - Home sample seed now omits selected real UC tags and owner assignments to create truthful variation across domain and heatmap signals.
  - seed verification now checks tag-count and owner-count variance in addition to count minimums.
  - Seed script dry-run passed and shows `UNSET TAGS` plus selective `SET TAGS` omissions for varied real metadata evidence.

## Completed Changes

- Lakebase readiness and the Atlas table split are implemented and deployed. Delta/Unity Catalog remains authoritative; Lakebase is the app-owned write mirror.
- Atlas AI is routed through the configured Governance Atlas Genie space on the active dev deployment.
- Broad hardening has landed for request-id errors, markdown/payload sanitization, frontend avatar upload guardrails, write-action auditing, role-gating, optional Genie/Lakebase portability, fail-closed asset visibility, and page-shell preservation under loading/error/unavailable states.
- Synthetic workflow stress validation now creates and mutates scoped customer-style workflows instead of marker-only rows:
  - Discovery searchable asset/count/deleted/inaccessible disposition evidence
  - Governance submitted -> reviewed -> approved and submitted -> reviewed -> rejected paths
  - Taxonomy reviewer assignment, asset association approval, and version/history evidence
  - Lineage degraded and unavailable cases with provenance/completeness flags
  - Quality completed run evidence
  - Genie grounded answer evidence with sentinel fallback rejection
  - Lakebase mirror success/readback evidence
  - pre-cleanup inventory and post-cleanup schema absence proof
- Regression reviewer visibility blockers are patched:
  - asset-scoped custom-property reads require actor-openable assets before store reads
  - asset profile reads require actor-openable assets before store reads
  - quality run/result reads and custom SQL validation require actor-openable assets before exposing control-plane data
  - classification recommendation list/get/review/scan paths enforce actor-openable assets before exposing or generating evidence
- Evidence-hygiene and portability blockers are patched:
  - generated Chrome profile directories were removed from `docs/northstar_visual_qa`
  - `.gitignore` excludes `docs/northstar_visual_qa/**/chrome-profile*/`
  - `app.yaml` source defaults no longer encode `datapact` or `skyler@entrada.ai`
  - `README.md` documents the `dev` bundle target as Entrada internal validation configuration, not the portable customer default
  - zero-byte app deploy evidence was replaced with current non-empty app status/deployment evidence

## Pending Tasks

- Active Home parity/performance tasks:
  - Collect final reviewer recheck after the status ledger correction and then update `docs/northstar_gap_analysis/home_todo.md` RV09.
  - Append the tranche entry to `AGENT_CHANGELOG.md`.
- No open residual-warning blockers remain.
- Residual-warning targets completed:
  - FastAPI `on_event` startup/shutdown handlers were replaced with an explicit lifespan handler.
  - Frontend hook-dependency lint warnings were removed without disabling lint rules.
  - Vitest localstorage-file warning was removed from the default `npm test` output.
  - Vite large-chunk/circular chunk warnings were removed through stable vendor chunking.
  - Full frontend test execution was stabilized for jsdom-heavy product-surface suites.
  - Databricks bundle validation warnings from stale unmatched sync excludes were removed.
  - Live route validation no longer hangs indefinitely on slow app/API calls.
- Regression/ripple blockers were remediated:
  - Hidden/non-openable assets cannot enter the asset profile write path before actor-openable checks.
  - Custom-property assignment persistence is blocked when fail-closed audit recording fails.
  - Invalid classification review decisions return the intended endpoint-level `400`.
- Visual/page QA blocker was remediated:
  - Home, Taxonomy, CDEs, Audit, and Admin gap-analysis files now carry current hardening deployment/build evidence.
- Previous hardening review lanes are signed off:
  - Feedback/status: Kuhn -> SIGNOFF
  - Regression/ripple: Descartes -> SIGNOFF
  - Truth/provenance: Leibniz -> SIGNOFF
  - Visual/page QA: Euclid -> SIGNOFF
- Residual-warning review lanes are signed off:
  - Backend/runtime: Sartre -> SIGNOFF
  - Frontend hooks/lint: Maxwell -> SIGNOFF
  - Test/build/bundle: Mendel -> SIGNOFF
  - Final regression/ripple: Hegel -> SIGNOFF

## Validation Status

- Active Home tranche validation status:
  - Tracker/status reopening completed.
  - Subagent review lanes assigned.
  - Feedback-coverage reviewer returned partial signoff with tracker-criteria blockers; checklist refinement completed.
  - Visual/product and regression/ripple reviewers returned blockers that are being implemented in the frontend checkpoint.
  - Focused frontend validation after the frontend checkpoint:
    - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
  - Focused backend validation after the backend/sample-data checkpoint:
    - `./.venv/bin/python -m py_compile atlas/services/atlas_metrics.py scripts/seed_home_sample_data.py` -> passed.
    - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `34 passed`.
    - `./.venv/bin/python scripts/seed_home_sample_data.py --dry-run` -> passed and produced `/tmp/govat-home-seed-dry-run.sql`.
  - Focused validation after the Home micro-regression patch:
    - `npm test -- --run src/components/AppFrame.test.jsx src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
    - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `34 passed`.
  - Broader local validation before live seed/deploy:
    - `npm run lint` -> passed.
    - `npm run build` -> passed.
    - `git diff --check` -> passed.
    - `npm run typecheck` -> failed once on the new AppFrame DOM calls requiring explicit `HTMLElement` narrowing; patched and rerun -> passed.
    - `npm test -- --run src/components/AppFrame.test.jsx src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` after the narrowing patch -> `3` files passed, `32` tests passed.
    - `npm run build` after the narrowing patch -> passed.
    - `git diff --check` after the narrowing patch -> passed.
  - Next validation step is live Home seed/update on Databricks `DEFAULT` using warehouse `da02d15a9490650b`, then verify-only checks for varied tags/owners and backed Home signal variance.
  - Live Home seed/update on Databricks `DEFAULT` completed:
    - `./.venv/bin/python scripts/seed_home_sample_data.py --profile DEFAULT --warehouse-id da02d15a9490650b` -> passed.
    - `./.venv/bin/python scripts/seed_home_sample_data.py --verify-only --profile DEFAULT --warehouse-id da02d15a9490650b` -> passed.
    - Verify-only summary: `18` app-owned UC views, `84` tag rows, `32` owner rows, `5` governance change-request rows, `6` audit rows, `tag_variance=3`, `owner_variance=2`.
  - Next validation step is Databricks bundle validation/deploy on `DEFAULT`, then command-center/API readback and Playwright screenshot evidence from the refreshed app.
  - Databricks bundle pre-deploy gates on `DEFAULT`:
    - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - Next validation step is bundle deploy and Databricks App deploy.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> bundle upload/resources passed, but app deployment failed because Databricks reports app compute `UPDATING` and management temporarily unavailable during infrastructure migration.
  - `databricks apps get atlas --profile DEFAULT -o json` confirms the app object is `RUNNING`, active deployment remains `01f14266773e1c94a61aa2d3b3e22e43`, compute is `UPDATING`, and target resources for SQL warehouse, Genie, and Lakebase are present.
  - Home live QA script updated so the live validation gate now checks bottom-card/Atlas-rail lower-edge alignment and the new floating `AI Copilot` contract: single draggable window, close/reopen, request spinner, and Genie-backed response.
  - Validation after live QA script update:
    - `node --check frontend/scripts/atlas_home_live_qa.mjs` -> passed.
    - `npm test -- --run src/components/AppFrame.test.jsx src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
    - `npm run typecheck` -> passed.
  - Next step: retry Databricks App deploy once compute leaves `UPDATING`.
  - While Databricks App management is unavailable, start the local runtime with the same `DEFAULT` profile/warehouse/catalog/schema settings to validate the current code path against live Databricks data before the live deployment retry.
  - Local runtime started on port `8010` with `DEFAULT` profile, live warehouse/catalog/schema, Genie enabled, and current built frontend.
  - Local command-center API readback failed after live hydration with `ValueError: Out of range float values are not JSON compliant: nan`; patching the metrics payload sanitization before any deploy retry is accepted.
  - Added command-center JSON-safety sanitizer and regression test. First focused pytest rerun failed because the test incorrectly expected the existing missing-description fallback to be `None`; correcting the assertion to check strict JSON safety instead.
  - NaN serialization fix validation:
    - `./.venv/bin/python -m py_compile atlas/services/atlas_metrics.py` -> passed.
    - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `35 passed`.
    - `git diff --check atlas/services/atlas_metrics.py tests/test_atlas_metrics.py` -> passed.
  - Next step: restart local runtime and rerun command-center readback against live data.
  - Local command-center readback after restart now serializes successfully and shows backed KPI trends from real governance request/audit timestamps, but domain scores remain too clustered (`Product=100.0`, several domains at `95.2`). Tightening the backed signal model and seed omissions before final screenshots.
  - Signal-variance patch completed locally:
    - Metadata coverage now counts the `data_product` field.
    - Home seed now omits a broader explicit set of real UC tags and owner assignments across Customer, Finance, Product, Operations, Marketing, and Risk assets.
    - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `35 passed`.
    - `./.venv/bin/python -m py_compile atlas/services/atlas_metrics.py scripts/seed_home_sample_data.py` -> passed.
    - `./.venv/bin/python scripts/seed_home_sample_data.py --dry-run` -> passed and produced `/tmp/govat-home-seed-dry-run.sql`.
  - Next step: apply the updated Home seed live and rerun command-center readback.
  - Updated Home seed applied live and verify-only passed:
    - `./.venv/bin/python scripts/seed_home_sample_data.py --profile DEFAULT --warehouse-id da02d15a9490650b` -> passed.
    - `./.venv/bin/python scripts/seed_home_sample_data.py --verify-only --profile DEFAULT --warehouse-id da02d15a9490650b` -> passed.
    - Verify-only summary: `18` views, `81` tag rows, `29` owner rows, `5` requests, `6` audit rows, `tag_variance=3`, `owner_variance=2`.
  - Local command-center readback after cache reset passed with strict JSON serialization and better backed variance:
    - KPI trends: `openStewardship` sparkline `[0,0,0,0,0,5]`, `policyExceptions` sparkline `[0,0,0,0,0,4]`.
    - Top-domain scores now vary: `Product=95.8`, `Customer=91.7`, `Marketing=87.5`, `Operations=87.5`, `Finance=83.3`.
    - Heatmap values include multiple backed levels, including `66.7` and `100.0`, rather than a uniform all-100 grid.
  - The live API cold read still took roughly 175 seconds locally; Home loading/hydration UI remains a required visual gate, and backend narrowing/caching remains a separate performance-hardening follow-up unless final live UX still feels blocked.
  - Next step: rerun bundle validation/deploy with the latest backend/script changes and retry Databricks App deploy.
  - Databricks app management is available again: `databricks apps get atlas --profile DEFAULT -o json` reports app `RUNNING`, compute `ACTIVE`, active deployment still `01f14266773e1c94a61aa2d3b3e22e43` before the retry.
  - Final pre-deploy local checks:
    - `npm run build` -> passed.
    - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `35 passed`.
    - `git diff --check` -> passed.
  - Next step: bundle validate/summary/deploy and Databricks App deploy retry.
  - Final Databricks deploy gates passed:
    - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed; app started successfully.
  - Active app readback:
    - Deployment: `01f1429bea0c1294b4cbab5aae24872f`
    - App state: `RUNNING`; compute state: `ACTIVE`
    - Frontend build: `frontend-56ed89436716`
    - Runtime/status with Databricks bearer token: runtime `live`, store `live`, Lakebase dual-write mode `delta-primary-lakebase-shadow`, state `active`, failed writes `0`.
  - Next step: live command-center/API readback and Home Playwright screenshot validation on deployment `01f1429bea0c1294b4cbab5aae24872f`.
  - Authenticated live command-center readback passed on deployment `01f1429bea0c1294b4cbab5aae24872f`:
    - state `available`
    - governed assets `792`, certified critical `13`, metadata coverage `11.7`
    - open stewardship `5` with sparkline `[0,0,0,0,0,5]`
    - policy exceptions `4` with sparkline `[0,0,0,0,0,4]`
    - top-domain scores are non-uniform: `95.8`, `91.7`, `87.5`, `87.5`, `83.3`
  - First live Home Playwright QA run failed because the script captured the intentional hydration state as if it were final visual evidence and still waited for the removed `.gh-home-ai-result` node. It did verify route, collapse, floating AI dialog, View all, quick actions, footer links, profile avatar upload, and two Genie-backed Atlas AI responses. Patching the QA gate to wait for live hydrated Home data and transcript messages before accepting final screenshots.
  - Local validation after the 1280x720 density patch:
    - `npm run build` -> passed, build `frontend-8237a8b08757`.
    - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
    - `git diff --check frontend/src/styles/app.css frontend/scripts/atlas_home_live_qa.mjs IMPLEMENTATION_STATUS.md` -> passed.
  - Databricks redeploy after the 1280x720 density patch:
    - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks apps deploy atlas --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed mechanically but is rejected as final evidence because passing `APP_NAME` forces API-direct deployment and ignores bundle target env injection.
    - Rejected deployment: `01f1429fa43719a1a218e363d51f487b`; runtime readback showed generic source defaults `main.atlas`, local AI provider defaults, and Home command-center values inconsistent with the live `datapact.atlas` seeded evidence.
    - The corresponding live QA run was stopped; it was waiting on `datapact.atlas` Home values that the rejected deployment could not serve.
  - Next step: redeploy with the project-target form `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json`, then rerun authenticated live Home Playwright QA.
  - Target-aware Databricks app redeploy accepted:
    - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed via the project pipeline.
    - Active deployment: `01f142a1ce651ec8942132ea1308ffce`; app state `RUNNING`; compute state `ACTIVE`; frontend build `frontend-8237a8b08757`.
    - Runtime status readback confirms dev target env injection: `GOVAT_CATALOG=datapact`, `GOVAT_SCHEMA=atlas`, warehouse `da02d15a9490650b`, runtime `live`, store `live`.
    - Authenticated command-center readback passed: state `available`, governed assets `792`, certified critical assets `13`, metadata coverage `11.7`, open stewardship actions `5` with sparkline `[0,0,0,0,0,5]`, policy exceptions `4` with sparkline `[0,0,0,0,0,4]`, top-domain scores `95.8/91.7/87.5/87.5/83.3`, and varied heatmap values `[0.0,6.1,9.3,9.7,54.0,66.7,100.0]`.
  - Next step: rerun authenticated live Home Playwright QA on deployment `01f142a1ce651ec8942132ea1308ffce`, including 1280x720 no-scroll/bottom-alignment and floating `AI Copilot` interaction gates.
  - Live Home Playwright QA on accepted deployment `01f142a1ce651ec8942132ea1308ffce`:
    - 1536x1024 capture -> passed; no scroll; bottom alignment delta `0.015625`.
    - 1440x900 capture -> passed; no scroll; bottom alignment delta `0.015625`.
    - 1280x720 capture -> failed only the no-scroll gate: `.gh-main` scrollHeight `673` vs clientHeight `618`, while all region text, footer, interactions, Genie responses, and bottom-alignment checks passed.
    - Interaction gates all passed: direct Home route, collapse-centered icons, draggable/closable floating `AI Copilot`, View all routes, quick-action routes, footer links, profile avatar upload, and Genie-backed Atlas AI evidence.
  - Live CSS probe at 1280x720 found the dashboard row was `400px`, but `.gh-home-main-grid` and the Atlas AI rail expanded to roughly `467px` due min-content sizing. Applying a small-height CSS patch so `.gh-home-page`, `.gh-home-dashboard-grid`, and `.gh-home-main-grid` honor the available grid row and hide internal overflow instead of making the main pane scroll.
  - Local validation after the final 1280x720 grid overflow patch:
    - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
    - `npm run build` -> passed, build `frontend-c9fa13e965f9`.
    - `git diff --check frontend/src/styles/app.css IMPLEMENTATION_STATUS.md` -> passed.
  - Databricks deploy after the final 1280x720 grid overflow patch:
    - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
    - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed via the target-aware project pipeline.
    - Active deployment: `01f142a3894c17e0982d31dc89b788d0`; app state `RUNNING`; compute state `ACTIVE`; frontend build `frontend-c9fa13e965f9`.
    - Runtime status readback confirms `GOVAT_CATALOG=datapact`, `GOVAT_SCHEMA=atlas`, warehouse `da02d15a9490650b`, runtime `live`, store `live`.
  - Authenticated live Home Playwright QA was rerun on deployment `01f142a3894c17e0982d31dc89b788d0` after this deploy.
  - Final authenticated live Home Playwright QA passed on deployment `01f142a3894c17e0982d31dc89b788d0`, build `frontend-c9fa13e965f9`:
    - `1536x1024`, `1440x900`, and `1280x720` captures all passed.
    - `1280x720` now reports `.gh-main` scrollHeight `618` and clientHeight `618`, `mainScrolls=false`, `horizontalOverflow=false`, footer-safe layout, and bottom alignment delta `0`.
    - 1536/1440 bottom alignment delta is `0.015625`; all captures have single-line copyright and footer-safe layout.
    - Interaction gates passed: direct Home route, collapse-centered icons, draggable/closable header `AI Copilot`, View all routes, quick-action routes, footer links, profile avatar upload, and Home Atlas AI prompt.
    - Atlas AI responses were `provider=genie`, `confidence=genie-grounded`, `evidenceCount=1`, with no page errors and no console warnings.
    - Evidence report: `docs/northstar_visual_qa/home-current/home-live-report.json`.
    - Side-by-side evidence: `docs/northstar_visual_qa/home-current/home-live-side-by-side-1536x1024.png`.
  - Home reopened checklist updated: R01-R11 and RV01-RV09 are complete.
  - Final local hygiene after the passing live QA:
    - `npm run lint` -> passed.
    - `npm run typecheck` -> passed.
    - `git diff --check` -> passed.
  - Next step: collect final review-lane signoff and update RV09 / changelog.
- Current live app for the Home reopened tranche:
  - App URL: `https://atlas-2543889327043640.aws.databricksapps.com`
  - Deployment: `01f142a68ce31747ba493e3c752d09f2`
  - Frontend build: `frontend-62510a30c84f`
  - App status evidence: `databricks apps get atlas --profile DEFAULT -o json` readback in this tranche and `docs/northstar_visual_qa/home-current/home-live-report.json`
  - App state: `RUNNING`; compute state: `ACTIVE`
- Prior residual-warning full local validation evidence, retained as historical context:
  - `./.venv/bin/python -m pytest -q` -> `365 passed`
  - `npm run lint` -> passed with no warnings
  - `npm run typecheck` -> passed
  - `npm test` -> `53` files passed, `376` passed, `27` skipped
  - `npm run build` -> passed, build `frontend-8b1e24a8c498`, with no large-chunk or circular-chunk warning
- Focused hardening validation passed:
  - `./.venv/bin/python -m pytest -q tests/test_synthetic_stress_contract.py` -> `9 passed`
  - `./.venv/bin/python -m pytest -q tests/test_backend_write_audit_contracts.py tests/test_classification_api.py` -> `30 passed`
  - `./.venv/bin/python -m pytest -q tests/test_config.py tests/test_backend_write_audit_contracts.py tests/test_classification_api.py tests/test_synthetic_stress_contract.py` -> `42 passed`
- Prior residual-warning live Databricks validation, retained as historical context:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m`
- Regression-fix deployment evidence:
  - Active deployment: `01f14257eebe1af6b2e06a582474815e`
  - `docs/hardening/live-app-deploy-hardening-target.json` -> `01f14257eebe1af6b2e06a582474815e RUNNING ACTIVE`
  - `docs/hardening/live-app-deploy-hardening.json` -> `01f14257eebe1af6b2e06a582474815e SUCCEEDED`
- Route/API validation on deployment `01f14257eebe1af6b2e06a582474815e` failed because the app-name deploy path used portable `app.yaml` defaults instead of the dev bundle target env overrides:
  - Lakebase reported disabled / `delta-primary`
  - Atlas AI reported local evidence instead of Genie
  - Audit/Admin endpoints returned 403
  - This deployment is not accepted for final evidence.
- Target-aware redeploy evidence:
  - Active deployment: `01f1425909d91aba8f4a6751c1bb4909`
  - `docs/hardening/live-app-deploy-hardening-target.json` -> `01f1425909d91aba8f4a6751c1bb4909 RUNNING ACTIVE`
  - `docs/hardening/live-app-deploy-hardening.json` -> `01f1425909d91aba8f4a6751c1bb4909 SUCCEEDED`
- Route/API validation passed on corrected deployment:
  - Artifact: `docs/hardening/live-route-validation-hardening.json`
  - All checked endpoints returned HTTP 200 on deployment `01f1425909d91aba8f4a6751c1bb4909`, build `frontend-b5fe86ae40b3`
  - Atlas AI is `provider=genie`, `confidence=genie-grounded`, evidence count `1`, with no sentinel fallback SQL/row/warning
  - Lakebase mirror is active: `3` attempted, `3` succeeded, `0` failed
- Live workflow stress validation passed:
  - Artifact: `docs/hardening/synthetic-stress-latest.json`
  - Run/schema: `ga-stress-20260427154845-e95f5b0a` / `datapact.atlas_ga_stress_20260427154845_e95f5b0a`
  - Workflow validation: `16` marker rows, `2` complete workflow sets, `2` approved governance requests, `2` rejected governance requests, `2` taxonomy approvals, `2` degraded lineage cases, `2` unavailable lineage cases, `2` completed quality runs, `2` Genie grounded answers, `2` Lakebase mirror successes, `30` unique audit events, `0` Genie sentinel fallbacks, `0` Lakebase failed writes, `0` organic evidence leaks
  - Cleanup validation: `DROP SCHEMA ... CASCADE` succeeded and post-cleanup `SHOW SCHEMAS` returned no rows
- Live all-page Playwright QA passed on the same corrected deployment/build (`01f1425909d91aba8f4a6751c1bb4909` / `frontend-b5fe86ae40b3`):
  - `docs/northstar_visual_qa/home-current/home-live-report.json`
  - `docs/northstar_visual_qa/discovery-current/discovery-live-report.json`
  - `docs/northstar_visual_qa/asset360-current/asset360-live-report.json`
  - `docs/northstar_visual_qa/lineage-current/lineage-live-report.json`
  - `docs/northstar_visual_qa/governance-current/governance-live-report.json`
  - `docs/northstar_visual_qa/insights-current/insights-live-report.json`
  - `docs/northstar_visual_qa/taxonomy-current/taxonomy-live-report.json`
  - `docs/northstar_visual_qa/cde-current/cde-live-report.json`
  - `docs/northstar_visual_qa/audit-current/audit-live-report.json`
  - `docs/northstar_visual_qa/admin-current/admin-live-report.json`
- Side-by-side evidence was refreshed for Discovery, Asset 360, Lineage, Governance, and Insights on deployment `01f1425909d91aba8f4a6751c1bb4909`:
  - `docs/northstar_visual_qa/discovery-current/discovery-live-side-by-side-1536x1024.png`
  - `docs/northstar_visual_qa/asset360-current/asset360-live-side-by-side-1536x1024.png`
  - `docs/northstar_visual_qa/lineage-current/lineage-live-side-by-side-1536x1024.png`
  - `docs/northstar_visual_qa/governance-current/governance-live-side-by-side-1536x1024.png`
  - `docs/northstar_visual_qa/insights-current/insights-live-side-by-side-1536x1024.png`
- Evidence hygiene checks passed:
  - `find docs/northstar_visual_qa -path '*chrome-profile*' -type f | wc -l` -> `0`
  - `wc -c docs/hardening/live-app-deploy-hardening-target.json` -> `3547`
  - `jq -r '.active_deployment.deployment_id + " " + .app_status.state + " " + .compute_status.state' docs/hardening/live-app-deploy-hardening-target.json` -> `01f1425909d91aba8f4a6751c1bb4909 RUNNING ACTIVE`
  - `git diff --check` -> passed
- Aggregate evidence reconciliation passed:
  - All 10 live page reports have `passed=true`, deployment `01f1425909d91aba8f4a6751c1bb4909`, build `frontend-b5fe86ae40b3`, and explicit `sideBySide.path` / `mockupPath` / `currentPath`
  - `docs/hardening/live-route-validation-hardening.json` reports `passed=true`, `lakebaseMode=delta-primary-lakebase-shadow`, `genieProvider=genie`, and `lakebaseFailed=0`
  - Active app status artifact reports `01f1425909d91aba8f4a6751c1bb4909 RUNNING ACTIVE`
  - `find docs/northstar_visual_qa -path '*chrome-profile*' -type f | wc -l` -> `0`
  - `git diff --check` -> passed
- Documentation consistency checks passed after the status/checklist/changelog update:
  - No stale hardening deployment ID remains in `IMPLEMENTATION_STATUS.md`, `docs/northstar_acceptance_checklist.md`, or affected page gap-analysis files
  - Current app status artifact still reports `01f1425909d91aba8f4a6751c1bb4909 RUNNING ACTIVE`
  - All 10 live page reports still pass on deployment `01f1425909d91aba8f4a6751c1bb4909`, build `frontend-b5fe86ae40b3`
  - `git diff --check` -> passed
- `AGENT_CHANGELOG.md` now includes the regression reviewer blocker remediation, rejected app-name deployment, accepted target-aware deployment, and final evidence package.
- Visual/page documentation blocker remediation checks passed:
  - `docs/northstar_gap_analysis/home.md`, `taxonomy.md`, `cdes.md`, `audit.md`, and `admin.md` now carry the current hardening deployment/build evidence
  - No stale `docs/genie/live-route-validation-latest.json`, `final completion remains gated`, or misleading `Current live evidence on deployment` references remain in those five page contracts
  - `git diff --check` -> passed after the remediation
- Final focused hardening revalidation passed after the docs update:
  - `./.venv/bin/python -m pytest -q tests/test_config.py tests/test_backend_write_audit_contracts.py tests/test_classification_api.py tests/test_synthetic_stress_contract.py tests/test_api_error_contracts.py tests/test_api_text_sanitization.py` -> `53 passed` in the pre-cleanup hardening baseline
  - `docs/northstar_visual_qa` size is `50M`; `docs/hardening` size is `440K`
  - Hardening artifacts are non-empty: app deploy/status `3547` bytes, route validation `9034` bytes, synthetic stress `411287` bytes
  - Synthetic stress artifact reports `passed=true`, cleanup `SUCCEEDED`, cleanup verification `SUCCEEDED`
- Final reviewer blocker remediation checks passed:
  - `docs/hardening/live-app-deploy-hardening.json` -> `01f1425909d91aba8f4a6751c1bb4909 SUCCEEDED`
  - `docs/hardening/live-app-deploy-hardening-target.json` -> `01f1425909d91aba8f4a6751c1bb4909 RUNNING ACTIVE`
  - Asset 360, Discovery, Governance, Insights, and Lineage live reports all include `sideBySide.path`, `sideBySide.mockupPath`, and `sideBySide.currentPath`
  - Affected page gap-analysis files list active deployment `01f1425909d91aba8f4a6751c1bb4909`, build `frontend-b5fe86ae40b3`, and `docs/hardening/live-route-validation-hardening.json`
  - `find docs/northstar_visual_qa -path '*chrome-profile*' -type f | wc -l` -> `0`
  - `git diff --check` -> passed
- Regression blocker focused validation passed:
  - `./.venv/bin/python -m py_compile atlas/api/catalog.py atlas/api/classification.py tests/test_backend_write_audit_contracts.py tests/test_classification_api.py`
  - `./.venv/bin/python -m pytest -q tests/test_backend_write_audit_contracts.py tests/test_classification_api.py` -> `30 passed`
- Full local validation passed after the regression fixes:
  - This pre-cleanup baseline is superseded by the current no-warning residual-risk validation above and below.
- Final reviewer signoff passed:
  - Kuhn: feedback/status SIGNOFF
  - Descartes: regression/ripple SIGNOFF after source/tests/evidence recheck
  - Leibniz: truth/provenance SIGNOFF on deployment `01f1425909d91aba8f4a6751c1bb4909`
  - Euclid: visual/page QA SIGNOFF after Home, Taxonomy, CDEs, Audit, and Admin gap-analysis evidence refresh
- Final lightweight consistency check passed:
  - All 10 live page reports remain on deployment `01f1425909d91aba8f4a6751c1bb4909`, build `frontend-b5fe86ae40b3`, with `passed=true` and side-by-side bindings
  - No stale hardening deployment `01f1425299ce19b2ae74789f6073e644` remains in `IMPLEMENTATION_STATUS.md`, `docs/northstar_acceptance_checklist.md`, `AGENT_CHANGELOG.md`, or `docs/northstar_gap_analysis`
  - `find docs/northstar_visual_qa -path '*chrome-profile*' -type f | wc -l` -> `0`
  - `git diff --check` -> passed
- Residual-warning focused frontend stability check passed:
  - `npm test -- --run src/components/CdeWorkspace.test.jsx src/components/DiscoveryWorkspace.test.jsx src/components/EntityWorkspace.test.jsx src/components/LineageGraph.test.jsx` -> `4` files passed, `56` passed, `27` skipped
  - Log scan of `/tmp/govat-focused-frontend-risk.log` found no `--localstorage-file`, `Warning:`, timeout, or failure text
- Residual-warning full frontend validation passed:
  - `npm run lint` -> passed with no warnings
  - `npm run typecheck` -> passed
  - `npm test` -> `53` files passed, `376` passed, `27` skipped
  - Log scan of `/tmp/govat-full-npm-test-risk.log` found no `--localstorage-file`, `Warning:`, timeout, or failure text
  - `npm run build` -> passed with no Vite large-chunk warning and no circular-chunk warning
- Residual-warning full backend validation passed:
  - `rg -n "on_event" runtime_app.py` -> no matches
  - `./.venv/bin/python -m pytest -q` -> `365 passed`
  - Log scan of `/tmp/govat-backend-risk.log` found no `on_event`, `DeprecationWarning`, warning, or failure text
- Residual-warning Databricks pre-deploy validation passed:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> `Validation OK!` with no warnings after stale unmatched sync excludes were removed
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> completed with no warnings
  - Log scan of `/tmp/govat-bundle-validate-risk.log` and `/tmp/govat-bundle-summary-risk.log` found no warnings or errors
  - `git diff --check` -> passed
- Residual-warning deployment completed:
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> deployment complete
  - `databricks apps deploy --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m` -> app started successfully
  - Active deployment evidence: `docs/hardening/live-app-deploy-residual-warning-target.json`
  - Active deployment: `01f14266773e1c94a61aa2d3b3e22e43`; app state `RUNNING`; compute state `ACTIVE`
- Live route validation found a tooling gap before product evidence:
  - First run of `frontend/scripts/atlas_route_live_validation.mjs` hung before report creation because native `fetch` had no request timeout.
  - The validator now applies a bounded `AbortController` timeout before falling back to curl or failing explicitly.
- Live residual-warning validation passed on the new deployment:
  - `frontend/scripts/atlas_route_live_validation.mjs` -> `passed=true`
  - Artifact: `docs/hardening/live-route-validation-residual-warning.json`
  - Deployment/build: `01f14266773e1c94a61aa2d3b3e22e43` / `frontend-8b1e24a8c498`
  - All checked endpoints returned HTTP 200 on the active build.
  - Atlas AI is `provider=genie`, `confidence=genie-grounded`, evidence count `1`, with no sentinel fallback SQL/row/warning.
  - Lakebase mirror is active: `21` attempted, `21` succeeded, `0` failed; mode `delta-primary-lakebase-shadow`.
  - Active app evidence reports `01f14266773e1c94a61aa2d3b3e22e43 SUCCEEDED RUNNING ACTIVE`.
  - `node --check frontend/scripts/atlas_route_live_validation.mjs` -> passed.
  - Precise residual-warning scan found no FastAPI `on_event`/deprecation warnings, no hook lint warnings, no Vitest localstorage warning, no Vite large-chunk/circular warning, no timed-out tests, and no bundle validation warning.
  - `git diff --check` -> passed.
- Residual-warning reviewer signoff passed:
  - Sartre: backend/runtime SIGNOFF
  - Maxwell: frontend hooks/lint SIGNOFF
  - Mendel: test/build/bundle SIGNOFF
  - Hegel: final regression/ripple SIGNOFF
- Final residual-warning consistency checks passed after status/changelog updates:
  - `git diff --check` -> passed
  - `docs/hardening/live-route-validation-residual-warning.json` still reports `passed=true`, deployment `01f14266773e1c94a61aa2d3b3e22e43`, build `frontend-8b1e24a8c498`, Genie `provider=genie`, and Lakebase failures `0`
  - `docs/hardening/live-app-deploy-residual-warning-target.json` still reports `01f14266773e1c94a61aa2d3b3e22e43 SUCCEEDED RUNNING ACTIVE`
  - Residual-warning log scan found no localstorage-file, timeout, FastAPI deprecation, `on_event`, Vite chunk, bundle validation, or test failure warnings
  - `IMPLEMENTATION_STATUS.md` no longer lists the prior residual warnings as remaining risks

### Checkpoint - Control Center Native Visual Inspection Started

- Trigger: after the native-route fixes for Command Center, Discover, Stewardship, Glossary/CDE, Lineage, and Audit, Control Center still needs a fresh side-by-side inspection against `northstar/screenshots/prototype_cc.png`.
- Scope reminder:
  - Current active North Star remains `northstar/*`; standalone Asset 360 is a supporting workflow only because no standalone Asset 360 screenshot exists in `northstar/screenshots/`.
  - Historical note superseded on 2026-04-30: `.claude/skills` resolves skill files through symlinks when inspected with `find -L`; reviewers must not treat the symlink directory as empty.
- Planned validation:
  - Inspect `northstar/screenshots/prototype_cc.png` against the latest `docs/northstar_visual_qa/prototype-screenshot-backed-refresh/control-center-3037x1269.png` and/or recapture if stale.
  - If edits are required, run the focused Admin/Control Center test, `git diff --check`, and a targeted `control-center` Playwright capture at `3037x1269`.
- Current risk:
  - Do not claim North Star route signoff until Control Center is inspected, all prototype routes are recaptured together, and reviewer lanes unanimously sign off.

### Checkpoint - Control Center And Atlas AI Dock Fix Started

- Control Center visual findings from `northstar/screenshots/prototype_cc.png` vs `docs/northstar_visual_qa/prototype-wide-rail-targeted/control-center-3037x1269.png`:
  - The floating Atlas AI dock is still the compact app size; the prototype dock is wider/taller and reaches near the bottom input area.
  - Control Center hero copy has drifted from the prototype.
  - The integrations and policy coverage cards are vertically compressed relative to the prototype card stack.
- Planned edit:
  - Add a native/wide AI dock size that matches the prototype while preserving drag/resize behavior and compact viewport sizing.
  - Restore the Control Center prototype hero description.
  - Increase only the Control Center prototype card row density where the current capture is visibly shorter than the reference.
- Planned validation:
  - `npm test -- --run src/components/AdminWorkspace.test.jsx src/components/AppFrame.test.jsx`
  - `git diff --check -- frontend/src/components/AppFrame.jsx frontend/src/components/AdminWorkspace.jsx frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css frontend/src/components/AdminWorkspace.test.jsx IMPLEMENTATION_STATUS.md`
  - Targeted `control-center` and representative `discover` capture at `3037x1269` to verify dock sizing and Control Center stack height.

### Checkpoint - Control Center And Atlas AI Dock Unit Gate Passed

- Implemented:
  - Added a prototype-native floating Atlas AI dock size (`440x640`) at wide viewports while preserving compact viewport sizing, drag, resize, and clamping behavior.
  - Restored the Control Center hero description to the prototype copy.
  - Removed the extra Control Center environment pill from the hero because the workspace/environment is already represented in the global chrome.
  - Increased only the Control Center integration/policy stack vertical rhythm to better match `northstar/screenshots/prototype_cc.png`.
- Validation:
  - `npm test -- --run src/components/AdminWorkspace.test.jsx src/components/AppFrame.test.jsx` -> passed, `2` files, `19` tests.
  - `git diff --check -- frontend/src/components/AppFrame.jsx frontend/src/components/AdminWorkspace.jsx frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css frontend/src/components/AdminWorkspace.test.jsx IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Recapture `control-center,discover` at `3037x1269` and inspect the updated Atlas AI dock and Control Center card stack against the prototype screenshots.

### Checkpoint - Control Center Native Capture Follow-Up Started

- Targeted capture:
  - `GOVAT_PROTOTYPE_ROUTES=control-center,discover GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... atlas_prototype_current_capture.mjs` -> passed.
  - Evidence: `docs/northstar_visual_qa/prototype-control-ai-dock-pass/control-center-3037x1269.png` and `discover-3037x1269.png`.
- Manual inspection:
  - The floating Atlas AI dock now matches the prototype width/height and bottom input placement closely.
  - Control Center content rail is correct, but the page stack still starts slightly high and the integrations/policy column remains a little compressed versus `northstar/screenshots/prototype_cc.png`.
- Planned edit:
  - Apply a CSS-only Control Center vertical rhythm follow-up: slightly lower the shell, increase shell gap, and expand integration/policy rows.
- Planned validation:
  - Focused Admin test and targeted Control Center capture.

### Checkpoint - Control Center Native Capture Follow-Up Passed

- Implemented:
  - Lowered the Control Center prototype shell and increased the shell gap.
  - Expanded the integrations and policy rows so the right stack matches `prototype_cc.png` more closely.
- Validation:
  - `npm test -- --run src/components/AdminWorkspace.test.jsx` -> passed, `1` file, `5` tests.
  - `git diff --check -- frontend/src/styles/operations-pages.css IMPLEMENTATION_STATUS.md` -> passed.
  - Targeted capture `GOVAT_PROTOTYPE_ROUTES=control-center GOVAT_PROTOTYPE_VIEWPORTS=3037x1269 ... atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-control-center-final-pass/control-center-3037x1269.png`
  - `docs/northstar_visual_qa/prototype-control-center-final-pass/prototype-current-report.json`
- Manual inspection:
  - The header, card rail, right integrations/policy stack, and floating Atlas AI dock now closely match `northstar/screenshots/prototype_cc.png`.
- Exact next action:
  - Run the full screenshot-backed prototype route capture set at native and responsive viewports.

### Checkpoint - Full Prototype Route Capture Passed

- Validation:
  - `GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024,1440x900,1280x720 GOVAT_PROTOTYPE_MOCK_API=1 ... atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-all-routes-final/prototype-current-report.json`
  - 32 viewport screenshots covering `command-center`, `discover`, `stewardship`, `glossary`, `cde-registry`, `lineage`, `audit`, and `control-center`.
- Report result:
  - `passed=true`
  - `mockApi=true`
  - `captures=32`
  - no request failures
  - no page errors
  - no console errors
  - no horizontal overflow
  - no main scroll failures
- Exact next action:
  - Spot-check the high-risk final native screenshots, then obtain reviewer-lane findings/signoff before broad validation gates.

### Checkpoint - Reviewer Signoff And Broad Validation Started

- Reviewer lanes:
  - Visual/product reviewer updated with `prototype-all-routes-final` evidence.
  - Functional/regression/ripple reviewer updated with final capture and focused-test evidence.
  - Truth/provenance reviewer updated with final capture and explicit mock-vs-live provenance boundaries.
  - Feedback coverage/scope reviewer spawned to verify the `northstar/*` re-scope and standalone Asset 360 exclusion.
- Planned validation:
  - `npm run typecheck`
  - `npm run lint -- --quiet`
  - full frontend Vitest suite
  - backend runtime/API/Genie/Lakebase/hardening pytest subset, escalating to full backend pytest if failures suggest broader risk
  - Databricks bundle validation and summary with `--profile DEFAULT`
- Current risk:
  - Final closeout remains blocked until reviewer lanes return unanimous signoff or all blockers are fixed and revalidated.

### Checkpoint - Broad Local Gate Batch 1 Passed

- Validation:
  - `npm run typecheck` -> passed.
  - `npm run lint -- --quiet` -> passed.
  - `git diff --check -- frontend/src/components/AppFrame.jsx frontend/src/components/AdminWorkspace.jsx frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css frontend/src/components/AdminWorkspace.test.jsx IMPLEMENTATION_STATUS.md` -> passed.
  - `./.venv/bin/python -m pytest -q tests/test_runtime_route_serving.py tests/test_runtime_api_contracts.py tests/test_api_error_contracts.py tests/test_api_text_sanitization.py tests/test_backend_write_audit_contracts.py tests/test_genie_service.py tests/test_genie_benchmark.py tests/test_lakebase_service.py tests/test_synthetic_stress_contract.py tests/test_lineage_api.py tests/test_atlas_api.py tests/test_atlas_metrics.py` -> passed, `122` tests.
- Exact next action:
  - Run the full frontend Vitest suite.

### Checkpoint - Full Frontend Suite Passed

- Validation:
  - `npm test -- --run` -> passed, `53` files, `379` tests passed, `27` skipped.
- Exact next action:
  - Remediate the feedback/scope reviewer documentation blockers by updating `prototype_contract.md` evidence paths/counts and the stale `Exact Next Actions` section, then rerun diff hygiene and request renewed signoff.

### Checkpoint - Feedback Scope Documentation Blocker Remediation Started

- Reviewer blocker:
  - `docs/northstar_gap_analysis/prototype_contract.md` still pointed current evidence at `prototype-current/` and left open must-fix counts as `TBD`.
  - `IMPLEMENTATION_STATUS.md` still listed stale exact next actions that had already been completed in this continuation.
- Implemented:
  - Updated `prototype_contract.md` to point at `docs/northstar_visual_qa/prototype-all-routes-final/`.
  - Recorded the final local route set, viewports, capture count, and no-standalone-Asset-360 route scope.
  - Replaced `TBD` must-fix counts with the current local evidence state.
- Planned validation:
  - `git diff --check -- docs/northstar_gap_analysis/prototype_contract.md IMPLEMENTATION_STATUS.md`
  - Send the remediation back to the feedback/scope reviewer.

### Checkpoint - Feedback Scope Documentation Blocker Remediation Sent

- Validation:
  - `git diff --check -- docs/northstar_gap_analysis/prototype_contract.md IMPLEMENTATION_STATUS.md` -> passed.
- Reviewer follow-up:
  - Feedback/scope reviewer was asked to re-review the remediated `prototype_contract.md` and `IMPLEMENTATION_STATUS.md`.
- Exact next action:
  - Run frontend build and Databricks bundle validation/summary for the current changed tree.

### Checkpoint - Databricks Closeout Validation Started

- Planned validation:
  - `npm run build`
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
- Current risk:
  - Deploy/live validation cannot start until the build and bundle checks pass.

### Checkpoint - Bundle Validation Warning Remediation Started

- Validation:
  - `npm run build` -> passed.
  - First `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` exited successfully but emitted stale unmatched `sync.exclude` warnings for deleted paths:
    - `docs/northstar_baseline_screenshots/**`
    - `docs/screenshots/**`
    - `docs/mockups/*.png`
- Planned edit:
  - Remove only the stale unmatched sync excludes from `databricks.yml`.
- Planned validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - warning scan for both command outputs.

### Checkpoint - Bundle Validation Warning Remediation Passed

- Implemented:
  - Removed stale unmatched sync excludes from `databricks.yml` for deleted legacy screenshot/mockup paths.
- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> `Validation OK!`.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - Warning scan of `/tmp/govat-prototype-bundle-validate.log` and `/tmp/govat-prototype-bundle-summary.log` -> clean.
  - `git diff --check -- databricks.yml IMPLEMENTATION_STATUS.md docs/northstar_gap_analysis/prototype_contract.md` -> passed.
- Exact next action:
  - Deploy bundle/app and run live route validation on the deployed Databricks App.

### Checkpoint - Databricks Deploy Started

- Planned commands:
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b`
  - `databricks apps deploy --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json`
- Current risk:
  - Live route validation and final reviewer signoff remain blocked until the active Databricks App deployment is refreshed with this build.

### Checkpoint - Databricks Deploy Completed And Live Validation Auth Fix Started

- Validation:
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> deployment complete.
  - `databricks apps deploy --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> app started successfully.
  - Active deployment readback: `docs/hardening/live-app-deploy-prototype-target.json`.
  - Active deployment: `01f14340869c13a5a75e2fdae896defe`; app state `RUNNING`; compute state `ACTIVE`.
  - Frontend build: `frontend-f69be7ba3216`.
- Live validation attempt:
  - First `frontend/scripts/atlas_route_live_validation.mjs` attempt returned HTTP `401` for all endpoints because no Databricks bearer token was supplied to the direct API validator.
- Planned remediation:
  - Obtain a short-lived `DEFAULT` profile token through `databricks auth token` and rerun the same validator with `GOVAT_DATABRICKS_TOKEN` set.

### Checkpoint - Live Route Validation Passed

- Validation:
  - Authenticated `frontend/scripts/atlas_route_live_validation.mjs` with `GOVAT_DATABRICKS_TOKEN` from the `DEFAULT` profile -> passed.
- Evidence:
  - `docs/hardening/live-route-validation-prototype.json`
  - mirrored Asset 360 API report: `docs/northstar_visual_qa/asset360-current/asset360-live-api-report.json`
- Active deployment/build:
  - Deployment `01f14340869c13a5a75e2fdae896defe`
  - Frontend build `frontend-f69be7ba3216`
  - App state `RUNNING`
  - Compute state `ACTIVE`
- Report result:
  - all checked endpoints returned HTTP `200`
  - all endpoint build headers matched `frontend-f69be7ba3216`
  - Lakebase write mirror `active`
  - Lakebase mode `delta-primary-lakebase-shadow`
  - Lakebase attempted/succeeded/failed: `3/3/0`
  - Atlas AI `provider=genie`, `confidence=genie-grounded`, evidence count `1`
  - no Genie sentinel SQL fallback, row fallback, or warning fallback
  - Governance, Taxonomy/CDE, Audit, Admin, Lineage, and supporting Asset 360 API contracts passed.
- Exact next action:
  - Run a deployed-app screenshot pass for the prototype routes so final visual evidence is not local-only.

### Checkpoint - Deployed Prototype Direct-Route Blocker Started

- Trigger: the deployed-app screenshot pass reached the active Databricks App but direct prototype paths returned HTTP `404` for the SPA shell, including `/command-center`, `/discover`, `/stewardship`, `/glossary-cdes`, and `/glossary-cdes?tab=cdes`.
- Diagnosis:
  - Runtime API validation passed, so backend APIs and build headers are healthy.
  - `runtime_app.py` still allowlists legacy SPA route prefixes such as `home`, `discovery`, `governance`, and `taxonomy`, but not the active `northstar/*` prototype route names.
- Planned edit:
  - Add active prototype route prefixes to `CLIENT_ROUTE_PREFIXES` while preserving legacy prefixes for routes that may return later.
  - Add a runtime regression test proving each screenshot-backed prototype path serves the SPA shell.
- Planned validation:
  - `./.venv/bin/python -m pytest -q tests/test_runtime_route_serving.py`
  - `git diff --check -- runtime_app.py tests/test_runtime_route_serving.py IMPLEMENTATION_STATUS.md`
- Exact next action:
  - Patch route serving and rerun the runtime route-serving tests before rebuilding and redeploying.

### Checkpoint - Deployed Prototype Direct-Route Fix Validated Locally

- Implemented:
  - Added active prototype route prefixes to `CLIENT_ROUTE_PREFIXES` in `runtime_app.py`: `command-center`, `discover`, `stewardship`, `glossary-cdes`, `lineage-atlas`, `audit-evidence`, and `control-center`.
  - Hardened `client_route_shell()` root parsing against query strings/fragments.
  - Added a regression test proving each screenshot-backed prototype path returns the SPA shell.
- Validation:
  - `./.venv/bin/python -m pytest -q tests/test_runtime_route_serving.py` -> passed, `9` tests.
  - `git diff --check -- runtime_app.py tests/test_runtime_route_serving.py IMPLEMENTATION_STATUS.md` -> passed.
- Exact next action:
  - Rebuild, validate the Databricks bundle, redeploy the app, and retry deployed-app prototype screenshot capture.

### Checkpoint - Rebuild After Direct-Route Fix Passed

- Validation:
  - `./.venv/bin/python -m py_compile runtime_app.py` -> passed.
  - `npm run build` -> passed.
- Build manifest:
  - Frontend build `frontend-f69be7ba3216`
  - Source hash `f69be7ba32161e8cc9ae5ddea14ce4da522ee5de82862a955afc91846183b1bd`
- Exact next action:
  - Run Databricks bundle validation and summary for the deployable artifact.

### Checkpoint - Bundle Validation After Direct-Route Fix Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> `Validation OK!`.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - Warning scan of `/tmp/govat-prototype-routefix-bundle-validate.log` and `/tmp/govat-prototype-routefix-bundle-summary.log` -> clean.
- Exact next action:
  - Deploy the bundle and app target, then confirm the active deployment ID before rerunning live validation.

### Checkpoint - Databricks Redeploy After Direct-Route Fix Passed

- Validation:
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> deployment complete.
  - `databricks apps deploy atlas --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> app started successfully.
  - Active deployment readback: `docs/hardening/live-app-deploy-prototype-routefix.json`.
- Active deployment/build:
  - Deployment `01f143456f4d17eab6651aa7f2e2dcb9`
  - App URL `https://atlas-2543889327043640.aws.databricksapps.com`
  - App state `RUNNING`
  - Compute state `ACTIVE`
  - Frontend build remains `frontend-f69be7ba3216`
- Exact next action:
  - Rerun authenticated live route validation, then deployed-app prototype screenshots against this deployment.

### Checkpoint - Direct App Deploy Regression Identified

- Trigger: live route validation against deployment `01f143456f4d17eab6651aa7f2e2dcb9` failed despite the runtime route patch.
- Findings:
  - `/api/runtime/status` reported `govCatalog=main`, `adminEmailsConfigured=false`, `GOVAT_ATLAS_AI_PROVIDER=local`, and Lakebase disabled.
  - Audit and Control Center returned `403` because the generic direct-deploy defaults did not include the dev target admin email.
  - Atlas AI returned `provider=local-evidence` and bootstrap reported `lakebase.writeMirror=disabled` for the same reason.
- Root cause:
  - `databricks apps deploy atlas ...` used the direct API deploy path and read generic `app.yaml` defaults instead of the dev target variables from `databricks.yml`.
- Planned remediation:
  - Redeploy through the Databricks Apps project pipeline without the `APP_NAME` argument:
    `databricks apps deploy --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m`.
- Validation:
  - Re-run runtime status readback to confirm `govCatalog=datapact`, configured admin email, Genie provider, and Lakebase enabled.
  - Re-run live route validation and deployed screenshots.

### Checkpoint - Target-Aware Project Redeploy Restored Dev Runtime Config

- Validation:
  - `databricks apps deploy --profile DEFAULT --target dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m` -> deployment complete.
  - Active deployment readback: `docs/hardening/live-app-deploy-prototype-project-routefix.json`.
  - Runtime status readback: `docs/hardening/live-runtime-status-prototype-project-routefix.json`.
- Active deployment:
  - Deployment `01f14346de8f117aa46d04333202cbf3`
  - App state `RUNNING`
  - Compute state `ACTIVE`
  - Source path `/Workspace/Users/skyler@entrada.ai/.bundle/atlas/dev/files`
- Runtime config now matches the dev target:
  - `govCatalog=datapact`
  - `govSchema=atlas`
  - `adminEmailsConfigured=true`
  - actor role `Admin`
- Exact next action:
  - Rerun authenticated live route validation against deployment `01f14346de8f117aa46d04333202cbf3`.

### Checkpoint - Live Route Validation Passed After Target-Aware Redeploy

- Validation:
  - Authenticated `frontend/scripts/atlas_route_live_validation.mjs` against deployment `01f14346de8f117aa46d04333202cbf3` -> passed.
- Evidence:
  - `docs/hardening/live-route-validation-prototype-project-routefix.json`
- Report result:
  - all checked endpoints returned HTTP `200`
  - all endpoint build headers matched `frontend-f69be7ba3216`
  - Lakebase write mirror `active`
  - Lakebase mode `delta-primary-lakebase-shadow`
  - Lakebase attempted/succeeded/failed: `6/6/0`
  - Atlas AI `provider=genie`, `confidence=genie-grounded`, evidence count `1`
  - no Genie sentinel SQL fallback, row fallback, or warning fallback
  - Governance workbench/detail, Insights, Taxonomy/CDE, Audit, Admin, Lineage, and supporting Asset 360 API contracts passed.
- Exact next action:
  - Run deployed-app prototype screenshot capture for the screenshot-backed North Star routes.

### Checkpoint - North Star Live Lineage Seed Started

- Trigger: deployed screenshot capture rendered all pages but logged eight live request failures for `finance_prod.curated.revenue_daily`: four asset-detail `404`s and four lineage `404`s across the Lineage route viewports.
- Decision:
  - Treat this as a real synthetic-data/workflow blocker. The prototype Lineage page names `finance_prod.curated.revenue_daily`; the live workspace needs a real UC asset there instead of relying on a local mock or accepting 404s.
  - Seed app-owned North Star validation tables in the `DEFAULT` workspace using live SQL, with comments marking them as Governance Atlas North Star validation data.
- Planned validation:
  - Verify `finance_prod.curated.revenue_daily` exists through the live asset and lineage APIs.
  - Rerun deployed screenshot capture and require zero request failures.

### Checkpoint - North Star Live Lineage Seed Validated

- Implemented:
  - Created North Star validation catalogs/schemas/tables for `finance_prod`, `sales_prod`, `customer_360`, `product_events`, `marketing_mart`, and `hr_secure`.
  - Created the prototype lineage target `finance_prod.curated.revenue_daily` from real synthetic upstream UC tables.
  - Added table/column comments identifying the data as Governance Atlas North Star validation data.
  - Granted read visibility for the validation actor `skyler@entrada.ai` on the synthetic catalogs/schemas.
- Validation:
  - First seed attempt failed before DDL because Statement Execution `wait_timeout` was set above the API maximum; rerun used `50s`.
  - Seed artifact: `docs/hardening/northstar-live-uc-seed-result.json`.
  - Grant artifact: `docs/hardening/northstar-live-uc-grants-result.json`.
  - SQL verification found `finance_prod.curated.revenue_daily` in `system.information_schema.tables`.
  - Live discovery refresh cleared the per-actor inventory cache.
  - Live asset detail for `finance_prod.curated.revenue_daily?sections=header` -> HTTP `200`, `state=available`, `visibilityState=visible`, `authoritative=true`.
  - Live lineage for `finance_prod.curated.revenue_daily` -> HTTP `200`, `state=available`, `visibilityState=visible`, `authoritative=true`.
- Exact next action:
  - Rerun deployed-app prototype screenshots and require zero live request failures.

### Checkpoint - Final Deployed Prototype Screenshot Capture Passed

- Validation:
  - Authenticated deployed-app Playwright capture against `https://atlas-2543889327043640.aws.databricksapps.com` with `GOVAT_PROTOTYPE_MOCK_API` unset -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-live-deployed-final-clean/prototype-current-report.json`
  - Screenshots in `docs/northstar_visual_qa/prototype-live-deployed-final-clean/`
- Report result:
  - `passed=true`
  - `mockApi=false`
  - captures: `32`
  - routes: `command-center`, `discover`, `stewardship`, `glossary`, `cde-registry`, `lineage`, `audit`, `control-center`
  - viewports: `3037x1269`, `1536x1024`, `1440x900`, `1280x720`
  - request failures: `0`
  - page errors: `0`
  - console errors: `0`
  - horizontal overflow failures: `0`
  - main-scroll failures: `0`
- Exact next action:
  - Send final live evidence to review lanes and reconcile unanimous signoff.

### Checkpoint - Visual Reviewer Blocker Remediation Started

- Trigger: post-capture visual/product review blocked final North Star signoff even though the deployed Playwright capture had no technical request/page/console failures.
- Reviewer blockers to remediate:
  - `stewardship-3037x1269.png` captured a loading screen instead of the prototype work queue/detail surface.
  - `glossary-3037x1269.png` still showed glossary loading/empty-state styling instead of the populated prototype glossary cards.
  - `cde-registry-3037x1269.png` rendered an empty CDE registry even though live route validation says CDE data exists.
  - `command-center-3037x1269.png` captured unsettled global chrome (`UC status loading` / disabled-looking Atlas AI) instead of the settled prototype shell.
  - `audit-3037x1269.png` over-truncated target column values to unusable fragments.
- Decisions:
  - Treat the visual-review blockers as active must-fix items. The prior zero-open-must-fix status is superseded until these screenshots are recaptured and reviewers re-sign.
  - Fix the underlying page/data-binding or capture-settle issue rather than accepting a technically green screenshot report.
  - Keep the active North Star route scope limited to screenshot-backed prototype routes under `northstar/*`; no standalone Asset 360 page will be added to the visual scope.
- Planned validation:
  - Focused component/unit tests for the changed surfaces.
  - Targeted local and deployed Playwright recaptures for `command-center`, `stewardship`, `glossary`, `cde-registry`, and `audit`.
  - Full deployed prototype screenshot capture after targeted blockers are cleared.
  - Send updated evidence to visual/product, functional/regression, truth/provenance, and feedback/scope review lanes for unanimous signoff.

### Checkpoint - Visual Blocker First Fix Pass Tested

- Implemented:
  - Removed the old route-level governance-summary loading gate in `App.jsx` so `/stewardship` renders the North Star Stewardship Workbench while its own live workbench endpoint hydrates.
  - Added live CDE dashboard hydration to `TaxonomyWorkspace.jsx` so the prototype `Glossary & CDEs` CDE tab can render backed CDE rows when `/api/atlas/taxonomy/overview` does not include CDE rows.
  - Hardened `frontend/scripts/atlas_prototype_current_capture.mjs` to wait past `UC status loading`, page-level governance/glossary/CDE loading text, and the old Stewardship loading shell.
  - Widened/wrapped the prototype Audit target column so target values remain useful instead of collapsing to fragments.
- Validation:
  - `npm test -- --run src/components/TaxonomyWorkspace.test.jsx src/components/GovernanceWorkspace.test.jsx src/components/AuditBrowserWorkspace.test.jsx` -> passed, `3` files / `19` tests.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Exact next action:
  - Run targeted local Playwright capture for `command-center,stewardship,glossary,cde-registry,audit` before redeploy.

### Checkpoint - Targeted Local Visual Blockers Cleared

- Validation:
  - Local mock-API Playwright capture for `command-center,stewardship,glossary,cde-registry,audit` at `3037x1269` and `1536x1024` -> passed.
  - Evidence: `docs/northstar_visual_qa/prototype-blocker-local-first-pass/prototype-current-report.json`.
  - Focused Audit wrap recapture at `3037x1269` -> passed.
  - Evidence: `docs/northstar_visual_qa/prototype-blocker-local-audit-wrap-pass/prototype-current-report.json`.
- Visual observations:
  - Stewardship no longer renders the loading shell; it shows the North Star work queue and selected detail rail.
  - Glossary no longer captures loading/empty state under mock API; cards are populated.
  - CDE Registry now shows CDE rows in the prototype taxonomy tab.
  - Command Center local chrome waits until `UC connected`.
  - Audit target values are readable instead of breaking into single-character fragments.
- Exact next action:
  - Run lint/typecheck/build and target-aware Databricks deploy, then repeat live route validation and deployed screenshot capture.

### Checkpoint - Pre-Deploy Validation Passed

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed.
  - `git diff --check frontend/src/App.jsx frontend/src/components/TaxonomyWorkspace.jsx frontend/src/styles/operations-pages.css frontend/scripts/atlas_prototype_current_capture.mjs IMPLEMENTATION_STATUS.md` -> passed.
- Build:
  - Frontend build ID: `frontend-7bf5c531b234`.
- Exact next action:
  - Run Databricks bundle validation/summary and deploy through the target-aware `DEFAULT` profile flow.

### Checkpoint - Target-Aware Databricks Deploy Passed

- Validation/deploy:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
  - `databricks apps get atlas --profile DEFAULT -o json` -> app `RUNNING`, compute `ACTIVE`.
- Evidence:
  - `docs/hardening/live-app-deploy-prototype-visual-blockers.json`
  - `docs/hardening/live-app-get-prototype-visual-blockers.json`
- Active deployment:
  - `01f143530a9e15db9d945850ae8a1163`
  - App URL: `https://atlas-2543889327043640.aws.databricksapps.com`
- Exact next action:
  - Run authenticated live runtime/route validation and deployed screenshot recapture on deployment `01f143530a9e15db9d945850ae8a1163`.

### Checkpoint - Live Route Validation Passed After Visual Fix Deploy

- Validation:
  - Authenticated `frontend/scripts/atlas_route_live_validation.mjs` against deployment `01f143530a9e15db9d945850ae8a1163` -> passed.
- Evidence:
  - `docs/hardening/live-runtime-status-prototype-visual-blockers.json`
  - `docs/hardening/live-route-validation-prototype-visual-blockers.json`
- Report result:
  - all checked endpoints returned HTTP `200`
  - all endpoint build headers matched `frontend-7bf5c531b234`
  - Lakebase write mirror `active`
  - Lakebase mode `delta-primary-lakebase-shadow`
  - Lakebase attempted/succeeded/failed: `6/6/0`
  - Atlas AI `provider=genie`, `confidence=genie-grounded`, evidence count `1`
  - no Genie sentinel SQL fallback, row fallback, or warning fallback
  - Governance workbench/detail, Taxonomy/CDE, Audit, Admin, Lineage, Insights, and supporting Asset 360 API contracts passed.
- Exact next action:
  - Rerun deployed-app prototype screenshots across the full screenshot-backed North Star route set.

### Checkpoint - Clean Deployed Prototype Screenshot Capture Passed

- Validation:
  - Authenticated deployed-app Playwright capture against `https://atlas-2543889327043640.aws.databricksapps.com` with `GOVAT_PROTOTYPE_MOCK_API` unset -> passed after live inventory refresh for `finance_prod.curated.revenue_daily`.
- Evidence:
  - `docs/hardening/live-discovery-refresh-finance-prod-visual-blockers.json`
  - `docs/hardening/live-asset-finance-prod-before-refresh-check.json`
  - `docs/hardening/live-lineage-finance-prod-before-refresh-check.json`
  - `docs/northstar_visual_qa/prototype-live-deployed-visual-blocker-clean/prototype-current-report.json`
  - Screenshots in `docs/northstar_visual_qa/prototype-live-deployed-visual-blocker-clean/`
- Report result:
  - `passed=true`
  - `mockApi=false`
  - captures: `32`
  - routes: `command-center`, `discover`, `stewardship`, `glossary`, `cde-registry`, `lineage`, `audit`, `control-center`
  - viewports: `3037x1269`, `1536x1024`, `1440x900`, `1280x720`
  - request failures: `0`
  - page errors: `0`
  - console errors: `0`
- Visual blocker status:
  - Stewardship now captures the work queue/detail surface, not the loading shell.
  - Glossary now captures populated glossary cards, not loading/empty state.
  - CDE Registry now captures live CDE rows in the prototype tab.
  - Command Center captures settled `UC connected` chrome.
  - Audit target values remain readable in the table.
- Exact next action:
  - Update the prototype contract evidence pointer and submit the clean deployed evidence to review lanes for unanimous signoff.

### Checkpoint - Broad Regression Gates Passed

- Validation:
  - Full frontend Vitest suite: `npm test` -> passed, `53` files / `379` tests passed / `27` skipped.
  - Backend/runtime/API/Genie/Lakebase/hardening subset:
    `./.venv/bin/python -m pytest -q tests/test_runtime_route_serving.py tests/test_atlas_api.py tests/test_atlas_metrics.py tests/test_api_error_contracts.py tests/test_api_text_sanitization.py tests/test_backend_write_audit_contracts.py tests/test_genie_service.py tests/test_lakebase_service.py tests/test_genie_benchmark.py tests/test_synthetic_stress_contract.py` -> passed, `94` tests.
  - Full `git diff --check` -> passed.
- Exact next action:
  - Wait for review-lane signoff and remediate any blockers before final closeout.

### Checkpoint - Review Blocker Remediation Restarted

- Trigger: review lanes rejected the mechanically clean deployed prototype capture as insufficient for final signoff.
- Active blockers to remediate:
  - Visual/product: Control Center integration status pills clip in the native-width screenshot; Stewardship work queue IDs wrap too heavily.
  - Functional/regression: `frontend/scripts/atlas_prototype_current_capture.mjs` can pass when `GOVAT_PROTOTYPE_ROUTES` selects no valid routes, and it can mark captures as passed while shell readiness text or a disabled Atlas AI header is still visible.
  - Truth/provenance: seeded validation workflow rows render as ordinary live work, Discovery copy still says results are ranked by `trust signal`, Discovery result authority ignores backend `meta.authoritative`, Discover-page Atlas AI can bypass shell AI availability, and Lineage hero copy overclaims end-to-end lineage when no graph edges are present.
- Planned implementation:
  - Make seeded validation work visible as validation workflow state and shorten row IDs while preserving full IDs in titles/detail.
  - Replace overclaimed `trust signal` and lineage wording with backend-backed governance/metadata coverage wording.
  - Make the prototype capture harness fail closed on empty route filters and incomplete shell readiness.
  - Fix the remaining Control Center/Stewardship native visual fit blockers.
- Planned validation:
  - Focused frontend tests for Discovery, Governance, Lineage, Admin, and the capture script.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - Negative route-filter harness check.
  - Local prototype recapture for affected routes, then full lint/typecheck/build and redeploy/live capture if focused validation passes.

### Checkpoint - Review Blocker Remediation Focused Gates Passed

- Implemented:
  - Discovery result authority now requires backend `authoritative` or `meta.authoritative` evidence.
  - Discovery copy now says results are ranked by governed metadata coverage, not an unbacked trust signal.
  - Discover-page Atlas AI now honors shell Genie availability before enabling or auto-running recommendations.
  - Lineage hero copy now narrows to actor-visible lineage and conditionally avoids end-to-end claims when no backed graph edges exist.
  - Stewardship validation-seed work items now display shortened row IDs and visible `Validation sample` provenance while preserving full request IDs in titles/detail.
  - Control Center integration status pills no longer clip at the native prototype width.
  - Prototype screenshot capture now fails closed on unknown route filters, empty selected routes, missing captures, unresolved shell-loading text, or disabled Atlas AI controls.
- Validation:
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm test -- --run src/hooks/useDiscoveryResults.test.jsx src/components/DiscoveryWorkspace.identity.test.jsx src/components/GovernanceWorkspace.test.jsx src/components/LineageWorkspace.test.jsx src/components/AdminWorkspace.test.jsx` -> passed, `5` files / `41` tests.
  - `GOVAT_PROTOTYPE_ROUTES=not-a-route ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> failed as expected with `Unknown prototype route filter(s): not-a-route`.
  - scoped `git diff --check` for touched files -> passed.
- Exact next action:
  - Run targeted local prototype captures for `stewardship`, `discover`, `lineage`, and `control-center`, then inspect the reports for shell readiness and visual fit.

### Checkpoint - Targeted Local Prototype Recapture Passed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3001 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=stewardship,discover,lineage,control-center GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024 ... node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-review-blocker-local-pass/prototype-current-report.json`
  - screenshots in `docs/northstar_visual_qa/prototype-review-blocker-local-pass/`
- Report result:
  - captures: `8/8`
  - request failures: `0`
  - page errors: `0`
  - all captures `loaded=true`
  - shell readiness blockers: none
  - disabled shell Atlas AI controls: none
- Inspection:
  - Discovery text now uses governed metadata coverage and `Coverage score`.
  - Control Center integration status pills render full labels at the native prototype width.
  - Stewardship row IDs no longer risk long validation-seed wrapping in live captures because seeded IDs now shorten to `VAL-##` with full-ID tooltips.
  - Lineage hero copy now avoids end-to-end claims unless backed edges are present.
- Exact next action:
  - Run full frontend hygiene (`lint`, `typecheck`, `build`), then Databricks bundle validation/summary/deploy before new live route and screenshot evidence.

### Checkpoint - Full Frontend Hygiene Passed

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm run typecheck` -> passed.
  - `npm test -- --run` -> passed, `53` files / `380` tests passed / `27` skipped.
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist` generated with `DiscoveryWorkspace-BYPmq8Wf.js`, `GovernanceWorkspace-dEStMCEc.js`, `AdminWorkspace-arvKXxEK.js`, `LineageStage-B2XCX3Xf.js`, and `index-BQDpZsvD.js`.
- Exact next action:
  - Run required Databricks app gates: `bundle validate`, `bundle summary`, `bundle deploy`, and `apps deploy` with profile `DEFAULT`.

### Checkpoint - Databricks Deploy Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy atlas --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
- Active deployment:
  - deployment id: `01f1435febf310a2a1db7cae86e88604`
  - app state: `RUNNING`
  - compute state: `ACTIVE`
  - app URL: `https://atlas-2543889327043640.aws.databricksapps.com`
- Evidence:
  - `docs/hardening/live-app-get-prototype-review-blockers.json`
- Exact next action:
  - Run authenticated live route validation, then deployed-app screenshot capture across the screenshot-backed prototype route set.

### Checkpoint - Target-Aware App Deploy Remediation Started

- Trigger: live route validation after deployment `01f1435febf310a2a1db7cae86e88604` showed the app running source `app.yaml` defaults (`main.atlas`, local AI, Lakebase disabled) instead of the dev bundle target (`datapact.atlas`, Genie, Lakebase enabled).
- Root cause found:
  - `databricks apps deploy --help` confirms that passing an `APP_NAME` from a Databricks Apps project directory uses direct API deploy mode.
  - The prior command passed `atlas`, so it bypassed the enhanced project/bundle deployment pipeline and did not apply `databricks.yml` target config.
- Planned action:
  - Redeploy with the target-aware project command: `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json`.
  - Re-read live runtime/bootstrap config and require `datapact.atlas`, Genie, and Lakebase-enabled state before route/screenshot signoff.
- Planned validation:
  - `databricks apps deploy` project-mode deploy.
  - `databricks apps get atlas`.
  - Authenticated `/api/runtime/status` and `/api/bootstrap` readback.
  - `frontend/scripts/atlas_route_live_validation.mjs`.
  - Deployed screenshot-backed prototype capture.

### Checkpoint - Target-Aware App Deploy Remediation Readback Passed

- Validation:
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed using project-mode deploy.
  - `databricks apps get atlas --profile DEFAULT -o json` -> app `RUNNING`, compute `ACTIVE`, active deployment `01f14362af3416b0a0de4d3a0044bfd8`, source path `/Workspace/Users/skyler@entrada.ai/.bundle/atlas/dev/files`.
  - Authenticated `/api/runtime/status` readback -> runtime `live`, store `live`, Lakebase dual-write enabled with `delta-primary-lakebase-shadow` active tables.
  - Authenticated `/api/bootstrap` readback -> shell environment `Dev · datapact.atlas`, role `Admin`, boot state `live`, authoritative `true`.
- Evidence:
  - `docs/hardening/live-app-get-prototype-target-aware-redeploy.json`
  - `docs/hardening/live-runtime-status-prototype-target-aware-redeploy.json`
  - `docs/hardening/live-bootstrap-prototype-target-aware-redeploy.json`
- Exact next action:
  - Run authenticated route validation against deployment `01f14362af3416b0a0de4d3a0044bfd8` and require Genie/Lakebase/workflow gates to pass before screenshot capture.

### Checkpoint - Live Route Validation Passed After Target-Aware Deploy

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f14362af3416b0a0de4d3a0044bfd8 GOVAT_BUILD_ID=frontend-0915dd1ba7d4 GOVAT_ROUTE_OUT=docs/hardening/live-route-validation-prototype-target-aware-redeploy.json node frontend/scripts/atlas_route_live_validation.mjs` -> passed.
- Evidence:
  - `docs/hardening/live-route-validation-prototype-target-aware-redeploy.json`
- Result summary:
  - all checked endpoints returned HTTP `200` on build `frontend-0915dd1ba7d4`.
  - Governance workbench/detail returned `5` requests with diff and approver evidence.
  - Audit, Admin, Taxonomy, CDE, Insights, Asset 360, and Lineage endpoint contracts passed.
  - Lakebase write mirror is `active`, mode `delta-primary-lakebase-shadow`, `6/6` writes succeeded, `0` failed.
  - Atlas AI is provider `genie`, confidence `genie-grounded`, evidence count `1`, with no sentinel fallback SQL/rows/warnings.
- Exact next action:
  - Capture the deployed app visually across the screenshot-backed prototype route set and viewport matrix.

### Checkpoint - Deployed Screenshot Capture Startup-State Fix Started

- Trigger: deployed prototype screenshot capture after target-aware deploy failed on three frames even though content panels rendered. The common blocker was topbar shell readiness: `UC status loading` remained visible and the `.ga-ai-chip` was disabled.
- Root cause:
  - `/api/bootstrap?surface=...` may return a truthful `bootState: loading` route-bootstrap payload while the fast runtime probe warms a background SQL check.
  - The frontend treated any non-inline bootstrap payload as final data and did not keep polling when `bootState` remained `loading`, so a cold or multi-worker app could leave the topbar status and Atlas AI disabled indefinitely.
  - The capture script also used the mock prototype `finance_prod.curated.revenue_daily` asset by default for live captures, causing avoidable live `404` requests when that prototype-only asset is not installed.
- Planned edit:
  - Make `useBootstrap` poll route-bootstrap loading payloads until they become live/degraded/error.
  - Keep mock captures on the prototype `finance_prod.curated.revenue_daily` asset, but default live captures to the seeded `datapact.governance_atlas_demo.customer_stewardship_queue` asset unless overridden.
- Planned validation:
  - `npm test -- --run src/hooks/useBootstrap.test.jsx`
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs`
  - focused deployed recapture of the failed route/viewports.

### Checkpoint - Deployed Screenshot Startup-State Focused Gates Passed

- Implemented:
  - `frontend/src/hooks/useBootstrap.js` now polls route-bootstrap payloads while `bootState` is `loading`, so cold or multi-worker `/api/bootstrap?surface=...` responses can hydrate the topbar to live state without a page reload.
  - `frontend/scripts/atlas_prototype_current_capture.mjs` now defaults live captures to `datapact.governance_atlas_demo.customer_stewardship_queue` while preserving `finance_prod.curated.revenue_daily` for mock prototype captures.
- Validation:
  - `npm test -- --run src/hooks/useBootstrap.test.jsx` -> passed, `4` tests.
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - scoped `git diff --check` for the touched hook/test/script/status files -> passed.
- Exact next action:
  - Run frontend hygiene/build and redeploy so the startup-state fix is present in the live app before recapturing screenshots.

### Checkpoint - Startup-State Fix Frontend Hygiene Passed

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm run typecheck` -> passed.
  - `npm test -- --run` -> passed, `53` files / `381` tests passed / `27` skipped.
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist/atlas-build-manifest.json` build id `frontend-baf116f70e64`, generated `2026-04-29T01:21:15.345Z`.
- Exact next action:
  - Run Databricks bundle validate/summary/deploy and target-aware app deploy for build `frontend-baf116f70e64`.

### Checkpoint - Startup-State Fix Databricks Deploy Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
- Active deployment:
  - deployment id: `01f1436a328f180ab9729a5b2620035e`
  - app state: `RUNNING`
  - compute state: `ACTIVE`
  - build id readback: `frontend-baf116f70e64`
- Readback:
  - `/api/runtime/status` -> runtime `live`, store `live`, Lakebase mirror `active`.
  - `/api/bootstrap?surface=taxonomy&asset=` -> build `frontend-baf116f70e64`, `bootState=live`, `mode=route-bootstrap`, shell environment `Dev · datapact.atlas`, AI provider `genie`.
- Evidence:
  - `docs/hardening/live-app-get-prototype-startup-fix.json`
  - `docs/hardening/live-runtime-status-prototype-startup-fix.json`
  - `docs/hardening/live-bootstrap-taxonomy-prototype-startup-fix.json`
- Exact next action:
  - Re-run authenticated route validation on deployment `01f1436a328f180ab9729a5b2620035e`, build `frontend-baf116f70e64`.

### Checkpoint - Startup-State Fix Live Route Validation Passed

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f1436a328f180ab9729a5b2620035e GOVAT_BUILD_ID=frontend-baf116f70e64 GOVAT_ROUTE_OUT=docs/hardening/live-route-validation-prototype-startup-fix.json node frontend/scripts/atlas_route_live_validation.mjs` -> passed.
- Evidence:
  - `docs/hardening/live-route-validation-prototype-startup-fix.json`
- Result summary:
  - all endpoint build ids matched `frontend-baf116f70e64`.
  - Lakebase mirror remained `active`, `6/6` writes succeeded, `0` failed.
  - Atlas AI remained `provider=genie`, `confidence=genie-grounded`, with no sentinel fallback SQL/rows/warnings.
  - Governance, Audit, Admin, Taxonomy, CDE, Insights, Asset 360, and Lineage endpoint contracts passed.
- Exact next action:
  - Re-run deployed screenshot-backed prototype capture with the corrected live default asset and startup-state polling fix.

### Checkpoint - Startup-State Fix Deployed Screenshot Capture Passed

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f1436a328f180ab9729a5b2620035e GOVAT_BUILD_ID=frontend-baf116f70e64 GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024,1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-live-deployed-startup-fix node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Evidence:
  - `docs/northstar_visual_qa/prototype-live-deployed-startup-fix/prototype-current-report.json`
  - `32` viewport screenshots plus `32` full-page screenshots under `docs/northstar_visual_qa/prototype-live-deployed-startup-fix/`.
- Report result:
  - `passed=true`
  - expected captures: `32`
  - actual captures: `32`
  - page errors: `0`
  - request failures: `0`
  - console warnings/errors: `0`
  - readiness blockers: none
  - horizontal overflow: none
- Exact next action:
  - Perform final side-by-side visual inspection against `northstar/screenshots/*`, then send the fresh deployed evidence to the review lanes for unanimous signoff.

### Continuation / Compaction Note - Current Prototype Evidence

- Current North Star scope:
  - Active prototype is `northstar/*`.
  - Screenshot-backed visual signoff routes are `command-center`, `discover`, `stewardship`, `glossary`, `cde-registry`, `lineage`, `audit`, and `control-center`.
  - Standalone Asset 360 is excluded from current visual signoff because `northstar/screenshots/` contains no standalone Asset 360 reference; the existing Asset 360 implementation remains preserved as a supporting workflow opened from prototype routes.
- Current deployed evidence:
  - deployment: `01f1436a328f180ab9729a5b2620035e`
  - build: `frontend-baf116f70e64`
  - app URL: `https://atlas-2543889327043640.aws.databricksapps.com`
  - route/API report: `docs/hardening/live-route-validation-prototype-startup-fix.json`
  - screenshot report: `docs/northstar_visual_qa/prototype-live-deployed-startup-fix/prototype-current-report.json`
  - screenshots: `docs/northstar_visual_qa/prototype-live-deployed-startup-fix/*.png`
  - prototype contract: `docs/northstar_gap_analysis/prototype_contract.md`
- Current truth/validation anchors:
  - Runtime/store readback is live on `datapact.atlas`.
  - Lakebase dual-write mirror is `active`, mode `delta-primary-lakebase-shadow`, `6/6` validation writes succeeded, `0` failed.
  - Atlas AI is Genie-backed with `provider=genie`, `confidence=genie-grounded`, and no sentinel fallback SQL/rows/warnings in live validation.
  - Synthetic validation rows must remain visibly labeled as validation/sample provenance and must not be presented as organic customer workflow state.
- Current closeout state:
  - Feedback/scope review initially blocked on stale contract evidence pointers and this missing continuation note; both are now remediated in this checkpoint.
  - Remaining closeout actions are: receive/sign off remaining review lanes, run final hygiene (`git diff --check` at minimum), append `AGENT_CHANGELOG.md`, stop any local dev server if still running, and then final report.

### Checkpoint - Truth Review Copy Blocker Started

- Trigger: truth/provenance review blocked signoff on the Command Center hero sentence saying every metric is `lineage-aware` while live lineage evidence for the validation asset is authoritative but currently has `0` upstream, `0` downstream, and `0` column-lineage rows.
- Planned edit:
  - Narrow the universal Command Center claim from `lineage-aware` to lineage-aware only where Databricks reports lineage, while preserving the prototype structure and the permission/provenance claim.
- Planned validation:
  - focused Home/Command Center tests.
  - frontend build.
  - target-aware Databricks deploy.
  - live route validation and deployed screenshot capture refresh.

### Checkpoint - Truth Review Copy Blocker Focused Gate Passed

- Implemented:
  - Command Center hero copy now says metrics are `lineage-aware where Databricks reports lineage`, avoiding a universal lineage-backed claim when live lineage rows are currently empty.
- Validation:
  - `npm test -- --run src/components/HomePage.test.jsx src/hooks/useCommandCenter.test.jsx` -> passed, `15` tests.
  - scoped `git diff --check` for the touched status/contract/Home files -> passed.
- Exact next action:
  - Build and redeploy the narrowed-copy frontend, then refresh live route/screenshot evidence and send back to truth review.

### Checkpoint - Truth Review Copy Blocker Final Live Evidence Passed

- Validation:
  - `npm run build` -> passed, build `frontend-97e174a8d5a6`.
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
  - Live app readback -> deployment `01f1436f4b3c1e35a236f8d9154e7930`, app `RUNNING`, compute `ACTIVE`, build `frontend-97e174a8d5a6`, runtime `live`, store `live`, Lakebase mirror `active`, bootstrap `Dev · datapact.atlas`, AI provider `genie`.
  - Live route validation -> passed on build `frontend-97e174a8d5a6`.
  - Deployed screenshot-backed prototype capture -> passed on build `frontend-97e174a8d5a6`.
- Evidence:
  - `docs/hardening/live-app-get-prototype-truth-copy-fix.json`
  - `docs/hardening/live-runtime-status-prototype-truth-copy-fix.json`
  - `docs/hardening/live-bootstrap-home-prototype-truth-copy-fix.json`
  - `docs/hardening/live-route-validation-prototype-truth-copy-fix.json`
  - `docs/northstar_visual_qa/prototype-live-deployed-truth-copy-fix/prototype-current-report.json`
  - screenshots in `docs/northstar_visual_qa/prototype-live-deployed-truth-copy-fix/`
- Screenshot report result:
  - `passed=true`
  - expected captures: `32`
  - actual captures: `32`
  - page errors: `0`
  - request failures: `0`
  - console warnings/errors: `0`
  - readiness blockers: none
  - horizontal overflow: none
- Contract update:
  - `docs/northstar_gap_analysis/prototype_contract.md` now points at the truth-copy-fix route and screenshot evidence.
- Exact next action:
  - Resubmit final evidence to review lanes for signoff after the truth-copy remediation.

## Risks

- Prior Home evidence before deployment `01f142bd851310689d54f2f264850a47` is stale for the second reopened Home tranche. The accepted Home evidence is `docs/northstar_visual_qa/home-current/home-live-report.json` on build `frontend-e11d3b7cac8f`.
- Improving Home sample signals must not introduce fake workflow counters, fake lineage, fake governance state, fake quality signals, or unbacked metric claims. Synthetic seed data is allowed only when it creates real Unity Catalog/governance-store records with visible provenance.
- Data-load work must preserve truthfulness and fail-closed visibility; perceived-speed improvements cannot silently show stale or unauthorized records as current truth.
- The worktree is heavily dirty from source changes, deployment/config updates, generated screenshots, route reports, and deliberate deletion of tracked browser-profile QA artifacts. Do not revert unrelated work.
- Synthetic validation data is app-owned, test-scoped, run-scoped, cleanup-safe, and excluded from organic evidence. It must not be presented as organic customer data.
- The repo-level default Databricks profile is `DEFAULT`; live mutations for this tranche used explicit `--profile DEFAULT --warehouse-id da02d15a9490650b`.
- Post-deploy app API calls were temporarily slow while the app warmed and drained queued validation requests; live validation ultimately passed and the route validator now uses bounded request timeouts.
- No residual-warning blockers remain.
- No Home R01-R11 blockers remain in the implementation checklist.
- No second-pass Home S01-S08 blockers remain in the implementation checklist.
- Regression-review blocker remediation:
  - Marked `frontend/src/hooks/useAtlasAiConversation.js` intent-to-add so the new shared AI hook is visible in `git diff`.
  - Added a final `max-width: 980px` shell override after the desktop shell authority rules so mobile topbar layout is not forced back to desktop grid/min-width constraints.
  - Hardened command-center JSON serialization for pandas `Timestamp` and `datetime/date` values and sanitized row records at ingestion.
  - Added a regression test for timestamp-backed change request/audit rows.
- Focused validation after regression-review blocker remediation:
  - `./.venv/bin/python -m pytest -q tests/test_atlas_metrics.py tests/test_atlas_api.py` -> `36 passed`.
  - `npm test -- --run src/components/HomePage.test.jsx src/components/AppFrame.test.jsx src/hooks/useCommandCenter.test.jsx` -> `3` files passed, `32` tests passed.
  - `git diff --check atlas/services/atlas_metrics.py tests/test_atlas_metrics.py frontend/src/styles/northstar.css frontend/src/hooks/useAtlasAiConversation.js` -> passed.
- Broader local validation after regression-review blocker remediation:
  - `./.venv/bin/python -m py_compile atlas/services/atlas_metrics.py` -> passed.
  - `npm run lint` -> passed.
  - `npm run typecheck` -> passed.
  - `npm run build` -> passed, build `frontend-62510a30c84f`.
  - Built-CSS mobile sanity probe -> passed; final `max-width: 980px` shell rule appears after the `max-width: 1280px` desktop compaction rule, forces a one-column topbar, and allows topbar actions to wrap.
- Databricks deploy after regression-review blocker remediation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed via the target-aware project pipeline.
  - Active deployment: `01f142a68ce31747ba493e3c752d09f2`; app state `RUNNING`; compute state `ACTIVE`; frontend build `frontend-62510a30c84f`.
  - Runtime status readback confirms `GOVAT_CATALOG=datapact`, `GOVAT_SCHEMA=atlas`, warehouse `da02d15a9490650b`, runtime `live`, store `live`.
- Final authenticated live Home Playwright QA passed on deployment `01f142a68ce31747ba493e3c752d09f2`, build `frontend-62510a30c84f`:
  - `1536x1024`, `1440x900`, and `1280x720` captures all passed.
  - `1280x720` reports `.gh-main` scrollHeight `618` and clientHeight `618`, `mainScrolls=false`, `horizontalOverflow=false`, footer-safe layout, and bottom alignment delta `0`.
  - 1536/1440 bottom alignment delta is `0.015625`; all captures have single-line copyright and footer-safe layout.
  - Interaction gates passed: direct Home route, collapse-centered icons, draggable/closable header `AI Copilot`, View all routes, quick-action routes, footer links, profile avatar upload, and Home Atlas AI prompt.
  - Atlas AI responses were `provider=genie`, `confidence=genie-grounded`, `evidenceCount=1`, with no page errors and no console warnings.
  - Evidence report: `docs/northstar_visual_qa/home-current/home-live-report.json`.
  - Side-by-side evidence: `docs/northstar_visual_qa/home-current/home-live-side-by-side-1536x1024.png`.
- Final review lane signoff:
  - Feedback coverage: SIGNOFF.
  - Visual/product fidelity: SIGNOFF.
  - Truth/provenance: SIGNOFF.
  - Regression/ripple: SIGNOFF after remediation of added-hook visibility, mobile-shell override, and timestamp JSON-safety blockers.
- Final closeout hygiene:
  - `git diff --check` across the current worktree -> passed after the final checklist, changelog, and status-ledger updates.
  - Latest final closeout `git diff --check` after the second reopened Home status/checklist/changelog updates -> passed.
  - The local validation runtime and automated QA browser were stopped before closeout.

## Exact Next Actions

1. Send final live evidence to review lanes and reconcile unanimous signoff.
2. Run final hygiene checks and update `AGENT_CHANGELOG.md`.

### Checkpoint - Prototype Responsive Blocker Tranche Started

- Trigger: final visual/product review of the deployed `northstar/*` evidence still blocks unanimous signoff on three responsive parity issues even though route validation and mechanical screenshot capture passed.
- Active blockers:
  - Discover result rows collide/compress at `1440x900` and `1280x720`.
  - Stewardship selected-work-item detail pane clips against the right Atlas AI area at `1440x900` and `1280x720`.
  - CDE Registry table columns overlap at `1440x900` and `1280x720`.
- In-scope rules:
  - Keep the prototype route set limited to Command Center, Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, and Control Center.
  - Preserve Asset 360 as a supporting drawer/workflow only; do not expand current visual signoff to a standalone Asset 360 page.
  - Use responsive layout and density fixes only; do not introduce fake counts, workflow rows, lineage, quality, or overclaimed data to make screenshots look fuller.
- Review lanes:
  - Visual/product, functional/regression, truth/provenance, and feedback/scope lanes have been re-opened against this narrowed blocker set.
- Planned validation:
  - Focused frontend tests for Discover, Stewardship/Governance, and CDE.
  - `npm run lint -- --quiet`, `npm run typecheck`, `npm run build`.
  - Databricks `bundle validate`, `bundle summary`, target-aware deploy, live route validation, and deployed screenshot capture.
  - Updated subagent review after fresh evidence.

### Checkpoint - Prototype Responsive Blocker Focused Gate Passed

- Implemented:
  - Discover prototype rows now reserve space for the trust/coverage score when the right Atlas AI dock is open and truncate long FQNs instead of allowing them to collide with score/chip content.
  - Stewardship Workbench now stacks the queue and selected-detail pane at constrained widths when Atlas AI is open, avoiding clipped detail content while preserving the wide two-column prototype layout.
  - Glossary/CDE Registry now converts CDE rows into compact readable rows at constrained widths when Atlas AI is open, preventing owner/source/status column overlap.
- Validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.identity.test.jsx src/components/GovernanceWorkspace.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx` -> passed, `4` files / `30` tests.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css` -> passed.
- Exact next action:
  - Run local Playwright captures for the three blocker routes at `1440x900` and `1280x720`, inspect screenshots against the remaining visual blockers, then proceed to full frontend hygiene/build.

### Checkpoint - Prototype Responsive Local Screenshot Gate Passed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover,stewardship,cde-registry GOVAT_PROTOTYPE_VIEWPORTS=1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-responsive-local-fix node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Follow-up `1280x720` spot captures after row-density tuning also passed under `docs/northstar_visual_qa/prototype-responsive-local-fix-2/` and `docs/northstar_visual_qa/prototype-responsive-local-fix-3/`.
- Manual inspection:
  - Discover rows no longer allow FQN/title text to run into coverage values; chips move below the name line at constrained dock widths.
  - Stewardship no longer clips the detail column under the Atlas AI dock; the work queue uses a compact readable table and detail stacks below.
  - CDE Registry rows no longer overlap owner/source/status content; rows render as compact readable records at constrained dock widths.
- Exact next action:
  - Re-run focused tests after the final density tweak, then execute full lint/typecheck/build before Databricks validation/deploy.

### Checkpoint - Prototype Responsive Frontend Gates Passed

- Validation:
  - `npm test -- --run src/components/DiscoveryWorkspace.identity.test.jsx src/components/GovernanceWorkspace.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/CdeWorkspace.test.jsx` -> passed, `4` files / `30` tests.
  - `npm run lint -- --quiet` -> passed.
  - `npm run typecheck` -> passed.
  - `npm test -- --run` -> passed, `53` files / `381` tests passed / `27` skipped.
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist/atlas-build-manifest.json` build id `frontend-98b7193c36b1`, generated `2026-04-29T02:58:50.372Z`.
- Exact next action:
  - Run Databricks bundle validate/summary/deploy and target-aware app deploy for build `frontend-98b7193c36b1`.

### Checkpoint - Stewardship Compact Priority Follow-Up Passed

- Trigger: the first deployed responsive screenshot for `stewardship-1280x720` showed the priority column compressed in the constrained Atlas AI dock layout.
- Implemented:
  - Hid only the priority column in the constrained dock layout, preserving the wide prototype table shape while keeping the `1280x720` and `1440x900` work queue readable.
- Validation:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx src/components/TaxonomyWorkspace.test.jsx src/components/DiscoveryWorkspace.identity.test.jsx` -> passed, `3` files / `25` tests.
  - `npm run lint -- --quiet` -> passed.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=stewardship GOVAT_PROTOTYPE_VIEWPORTS=1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-responsive-local-fix-4 node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist/atlas-build-manifest.json` build id `frontend-08b79b8a20aa`, generated `2026-04-29T03:24:37.715Z`.
- Exact next action:
  - Redeploy build `frontend-08b79b8a20aa`, re-run live route validation, and recapture deployed screenshots.

### Checkpoint - Prototype Topbar Responsive Follow-Up Started

- Trigger: deployed `docs/northstar_visual_qa/prototype-live-deployed-responsive-final/discover-1440x900.png` showed the top-right Atlas AI header action clipped at the viewport edge, even though the route capture gate passed.
- Scope:
  - Fix only the constrained-width prototype header elasticity so the workspace breadcrumb, search, UC status, notifications/help, and Atlas AI button fit at `1440x900` and nearby viewport widths.
  - Preserve the approved prototype route set and the current page content/layout fixes.
- Planned validation:
  - Focused topbar tests and `git diff --check`.
  - Local Playwright capture at `1440x900` and `1280x720`.
  - Rebuild, Databricks validation/deploy, live route validation, deployed screenshot recapture, and subagent signoff.

### Checkpoint - Prototype Topbar Focused Gate Passed

- Implemented:
  - The prototype shell header now uses a more elastic grid between `1281px` and `1600px`, with a bounded search column, smaller header-control gaps, and truncation on long UC status labels.
  - The fix is scoped to the constrained prototype-width band that clipped the Atlas AI button and leaves the existing `1280px` mobile-tablet header behavior intact.
- Validation:
  - `npm test -- --run src/components/AppFrame.test.jsx src/components/primitives/__tests__/ShellTopbarIdentity.test.jsx` -> passed, `2` files / `21` tests.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/styles/northstar.css` -> passed.
- Exact next action:
  - Capture local prototype screenshots for `discover` at `1440x900` and `1280x720` to verify the topbar controls fit before rebuild/deploy.

### Checkpoint - Prototype Topbar Local Screenshot Gate Passed

- Validation:
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=discover GOVAT_PROTOTYPE_VIEWPORTS=1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-topbar-local-fix node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Manual inspection:
  - `docs/northstar_visual_qa/prototype-topbar-local-fix/discover-1440x900.png` shows the UC status, notification/help controls, and full `Atlas AI` header button inside the viewport.
  - `docs/northstar_visual_qa/prototype-topbar-local-fix/discover-1280x720.png` preserved the already-working compact header.
- Exact next action:
  - Run frontend hygiene/build, then redeploy the corrected build and recapture the full live prototype matrix.

### Checkpoint - Prototype Topbar Frontend Hygiene Passed

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm run typecheck` -> passed.
  - `npm test -- --run` -> passed, `53` files / `381` tests passed / `27` skipped.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css` -> passed.
- Exact next action:
  - Build the frontend bundle and deploy that exact build through the Databricks app target.

### Checkpoint - Prototype Topbar Build Passed

- Validation:
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist/atlas-build-manifest.json` build id `frontend-9cc5e24ea7d4`, generated `2026-04-29T04:00:25.828Z`.
- Exact next action:
  - Run Databricks `bundle validate`, `bundle summary`, deploy, target-aware app deploy, runtime readback, live route validation, and full deployed screenshot capture for build `frontend-9cc5e24ea7d4`.

### Checkpoint - Prototype Topbar Databricks Deploy Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed; app URL remains reported as `(not deployed)` by bundle summary, consistent with prior Databricks CLI behavior for this app resource.
  - `databricks bundle deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks apps deploy atlas --profile DEFAULT --source-code-path /Workspace/Users/skyler@entrada.ai/.bundle/atlas/dev/files --skip-validation --timeout 20m -o json` -> passed.
- Live deployment:
  - Deployment id `01f1438066af13dda5063215c95e789b`.
  - App status `SUCCEEDED`; message `App started successfully`.
- Exact next action:
  - Run live runtime/bootstrap readback, route validation, and deployed screenshot capture against deployment `01f1438066af13dda5063215c95e789b` / build `frontend-9cc5e24ea7d4`.

### Checkpoint - Prototype Topbar First Live Route Gate Blocked

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f1438066af13dda5063215c95e789b GOVAT_BUILD_ID=frontend-9cc5e24ea7d4 GOVAT_ROUTE_OUT=docs/hardening/live-route-validation-prototype-responsive-topbar-final.json GOVAT_ASSET360_API_OUT=docs/northstar_visual_qa/asset360-current/asset360-live-api-prototype-responsive-topbar-final.json node frontend/scripts/atlas_route_live_validation.mjs` -> failed.
- Evidence:
  - All checked endpoints served build `frontend-9cc5e24ea7d4`, so the source build was live.
  - Runtime truth regressed because the API-style deploy used source defaults from `app.yaml`: Lakebase reported `disabled`, Atlas AI provider reported `local-evidence`, and admin/audit routes returned `403`.
- Decision:
  - Do not capture or sign off screenshots from this deployment state.
  - Re-run `databricks apps deploy` from the bundle project path without an explicit `APP_NAME` argument so the `dev` target config injects Genie/Lakebase/admin environment values.
- Exact next action:
  - Execute target-aware project deploy for build `frontend-9cc5e24ea7d4`, then rerun live route validation.

### Checkpoint - Prototype Topbar Target-Aware App Deploy Passed

- Validation:
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
  - `databricks apps get atlas --profile DEFAULT -o json` -> active deployment `01f143819c8a18d286a657964c7a2516`, status `SUCCEEDED`, app `RUNNING`, compute `ACTIVE`.
- Evidence:
  - Active deployment now lists the bundle-injected environment variable names and the configured `atlas-genie-space` and `atlas-lakebase` app resources.
- Exact next action:
  - Rerun live route validation against deployment `01f143819c8a18d286a657964c7a2516` and build `frontend-9cc5e24ea7d4`.

### Checkpoint - Prototype Topbar Live Route Gate Passed

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f143819c8a18d286a657964c7a2516 GOVAT_BUILD_ID=frontend-9cc5e24ea7d4 GOVAT_ROUTE_OUT=docs/hardening/live-route-validation-prototype-responsive-topbar-final.json GOVAT_ASSET360_API_OUT=docs/northstar_visual_qa/asset360-current/asset360-live-api-prototype-responsive-topbar-final.json node frontend/scripts/atlas_route_live_validation.mjs` -> passed.
- Evidence:
  - Every checked endpoint returned build id `frontend-9cc5e24ea7d4`.
  - Lakebase write mirror `active`, mode `delta-primary-lakebase-shadow`, attempted `3`, succeeded `3`, failed `0`.
  - Atlas AI provider `genie`, confidence `genie-grounded`, evidence count `1`, with no sentinel SQL/row/warning fallback.
  - Governance workbench/detail, audit evidence/detail, admin control center, insights, taxonomy, CDE dashboard/detail, lineage, asset detail, and supporting Asset 360 API routes all passed the live route contract.
- Artifacts:
  - `docs/hardening/live-route-validation-prototype-responsive-topbar-final.json`
  - `docs/hardening/live-app-get-prototype-responsive-topbar-final.json`
  - `docs/hardening/live-runtime-status-prototype-responsive-topbar-final.json`
  - `docs/hardening/live-bootstrap-prototype-responsive-topbar-final.json`
- Exact next action:
  - Capture the full deployed prototype route matrix at the required viewports and inspect the previous visual blockers plus the topbar.

### Checkpoint - Prototype Live Screenshot Gate Reopened

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f143819c8a18d286a657964c7a2516 GOVAT_BUILD_ID=frontend-9cc5e24ea7d4 GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024,1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-live-deployed-responsive-topbar-final node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed, `32` screenshots captured with no script-level page/request/console failures.
- Manual inspection:
  - `discover-1440x900.png` confirms the topbar clipping is fixed in live deployment.
  - `discover-1280x720.png`, `stewardship-1440x900.png`, and `cde-registry-1280x720.png` preserve the prior responsive row/readability fixes.
- Remaining blocker:
  - `stewardship-1280x720-full.png` hides the selected detail pane because the responsive stacked work area is constrained by the parent grid row instead of becoming scrollable content.
- Decision:
  - Reopen the screenshot gate and apply a narrow Stewardship responsive-grid fix before final signoff.

### Checkpoint - Prototype Stewardship Scroll Follow-Up Passed

- Implemented:
  - The constrained `1181px`-`1320px` Stewardship layout now forces the work queue and selected-detail region into a single-column stack and releases the page overflow to the main shell scroller.
  - This keeps the selected detail reachable on narrow prototype viewports instead of positioning it outside the visible content band.
- Validation:
  - `npm test -- --run src/components/GovernanceWorkspace.test.jsx` -> passed, `1` file / `10` tests.
  - `git diff --check -- IMPLEMENTATION_STATUS.md frontend/src/styles/operations-pages.css` -> passed.
  - `GOVAT_BASE_URL=http://127.0.0.1:3000 GOVAT_PROTOTYPE_MOCK_API=1 GOVAT_PROTOTYPE_ROUTES=stewardship GOVAT_PROTOTYPE_VIEWPORTS=1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-stewardship-scroll-local-fix-2 node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Exact next action:
  - Rebuild, deploy with the target-aware project deploy path, rerun live route validation, and recapture the deployed screenshot matrix.

### Checkpoint - Prototype Stewardship Scroll Build Passed

- Validation:
  - `npm run lint -- --quiet` -> passed.
  - `npm run build` -> passed.
- Build artifact:
  - `frontend/dist/atlas-build-manifest.json` build id `frontend-ca2280f39a0f`, generated `2026-04-29T04:45:03.394Z`.
- Exact next action:
  - Run Databricks bundle validate/summary and target-aware project deploy for build `frontend-ca2280f39a0f`.

### Checkpoint - Prototype Stewardship Scroll Databricks Deploy Passed

- Validation:
  - `databricks bundle validate --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed.
  - `databricks bundle summary --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b` -> passed; app URL remains reported as `(not deployed)` by bundle summary, consistent with prior CLI behavior.
  - `databricks apps deploy --profile DEFAULT -t dev --var warehouse_id=da02d15a9490650b --skip-validation --timeout 20m -o json` -> passed.
  - `databricks apps get atlas --profile DEFAULT -o json` -> active deployment `01f143868f691f769c94fa616ce2e7cd`, status `SUCCEEDED`, app `RUNNING`, compute `ACTIVE`.
- Exact next action:
  - Rerun live route validation and deployed screenshot capture against deployment `01f143868f691f769c94fa616ce2e7cd` / build `frontend-ca2280f39a0f`.

### Checkpoint - Prototype Stewardship Scroll Live Route Gate Passed

- Validation:
  - Initial live route attempt after deploy returned `401` for every endpoint because `/tmp/govat-default-token` had expired; the token was refreshed with `databricks auth token --profile DEFAULT -o json`.
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f143868f691f769c94fa616ce2e7cd GOVAT_BUILD_ID=frontend-ca2280f39a0f GOVAT_ROUTE_OUT=docs/hardening/live-route-validation-prototype-responsive-scroll-final.json GOVAT_ASSET360_API_OUT=docs/northstar_visual_qa/asset360-current/asset360-live-api-prototype-responsive-scroll-final.json node frontend/scripts/atlas_route_live_validation.mjs` -> passed.
- Evidence:
  - Every checked endpoint returned build id `frontend-ca2280f39a0f`.
  - Lakebase write mirror `active`, mode `delta-primary-lakebase-shadow`, attempted `3`, succeeded `3`, failed `0`.
  - Atlas AI provider `genie`, confidence `genie-grounded`, evidence count `1`, with no sentinel SQL/row/warning fallback.
- Artifacts:
  - `docs/hardening/live-route-validation-prototype-responsive-scroll-final.json`
  - `docs/hardening/live-app-get-prototype-responsive-scroll-final.json`
  - `docs/hardening/live-runtime-status-prototype-responsive-scroll-final.json`
  - `docs/hardening/live-bootstrap-prototype-responsive-scroll-final.json`
- Exact next action:
  - Capture and inspect the final deployed prototype screenshots for the full North Star route matrix.

### Checkpoint - Prototype Final Deployed Screenshot Gate Passed

- Validation:
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f143868f691f769c94fa616ce2e7cd GOVAT_BUILD_ID=frontend-ca2280f39a0f GOVAT_PROTOTYPE_VIEWPORTS=3037x1269,1536x1024,1440x900,1280x720 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Capture report `docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final/prototype-current-report.json` has `passed=true`, `expectedCaptureCount=32`, `captures=32`, and no page/request/console failures.
  - `GOVAT_DATABRICKS_TOKEN=... GOVAT_DEPLOYMENT_ID=01f143868f691f769c94fa616ce2e7cd GOVAT_BUILD_ID=frontend-ca2280f39a0f GOVAT_PROTOTYPE_ROUTES=stewardship GOVAT_PROTOTYPE_VIEWPORTS=1280x720 GOVAT_PROTOTYPE_SCROLL_MAIN=1 GOVAT_PROTOTYPE_CAPTURE_OUT=docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final-scrolled node frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
- Manual inspection:
  - `discover-1440x900.png` shows the full topbar action set, including the full `Atlas AI` button, inside the viewport.
  - `discover-1280x720.png` and `cde-registry-1280x720.png` keep rows readable without text collisions.
  - `stewardship-1440x900.png` shows the stacked queue and selected detail without clipping.
  - `stewardship-1280x720-main-bottom.png` in the scrolled capture proves the selected detail pane is reachable below the queue in the constrained viewport.
- Exact next action:
  - Send final evidence to the review lanes and reconcile any reviewer blockers before closeout.

### Checkpoint - Prototype Truth Artifact Refresh Passed

- Trigger: truth/provenance review found the cited runtime/bootstrap readback artifacts contained `{}` because the curl header used an unexported inline shell variable.
- Implemented:
  - Refreshed `docs/hardening/live-runtime-status-prototype-responsive-scroll-final.json` and `docs/hardening/live-bootstrap-prototype-responsive-scroll-final.json` using the refreshed `DEFAULT` Databricks token.
  - Re-polled runtime status until it recorded `runtime.state=live` and `store.state=live`.
- Validation:
  - Runtime artifact now shows build `frontend-ca2280f39a0f`, Lakebase mirror `active`, mode `delta-primary-lakebase-shadow`, failed `0`.
  - Bootstrap artifact now shows build `frontend-ca2280f39a0f`, Atlas AI provider `genie`, Lakebase mirror `active`, failed `0`, environment `Dev · datapact.atlas`.
  - `git diff --check -- docs/hardening/live-runtime-status-prototype-responsive-scroll-final.json docs/hardening/live-bootstrap-prototype-responsive-scroll-final.json docs/northstar_gap_analysis/prototype_contract.md IMPLEMENTATION_STATUS.md frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css` -> passed.
- Exact next action:
  - Re-send refreshed evidence to truth/provenance review and wait for unanimous signoff.

### Checkpoint - Prototype Final Signoff And Closeout Passed

- Review signoff:
  - Visual/product reviewer: SIGNOFF. The final deployed screenshot matrix clears the Discover row collision, Stewardship detail clipping, and CDE Registry overlap blockers for the active `northstar/*` route set.
  - Functional/regression reviewer: SIGNOFF. Live routes, screenshot matrix, constrained Stewardship scroll proof, Lakebase mirror, and Genie grounding have no remaining blockers.
  - Truth/provenance reviewer: SIGNOFF. Refreshed runtime/bootstrap artifacts prove live runtime/store state, build `frontend-ca2280f39a0f`, Lakebase mirror `active`, and Atlas AI `provider=genie` without unsupported synthetic workflow, lineage, quality, or AI claims.
  - Feedback/scope reviewer: SIGNOFF. The contract and evidence now point at `prototype-live-deployed-responsive-scroll-final`; standalone Asset 360 remains excluded from the visual gate because it is not in the new `northstar/*` prototype scope.
- Validation:
  - Final active deployment: `01f143868f691f769c94fa616ce2e7cd`.
  - Final build: `frontend-ca2280f39a0f`.
  - Route gate: `docs/hardening/live-route-validation-prototype-responsive-scroll-final.json` passed with Lakebase `3/3/0` and Genie grounded evidence.
  - Screenshot gate: `docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final/prototype-current-report.json` passed with `32` deployed captures across the eight prototype routes and four required viewports.
  - Scrolled constrained proof: `docs/northstar_visual_qa/prototype-live-deployed-responsive-scroll-final-scrolled/stewardship-1280x720-main-bottom.png`.
- Risks:
  - No blocking risks remain for the active `northstar/*` prototype route scope.
  - The large dirty worktree contains many pre-existing/generated files; unrelated changes were preserved and not reverted.
- Exact next action:
  - Close the tranche after appending `AGENT_CHANGELOG.md`, running a final whitespace check, and stopping the local Vite server if still running.

### Checkpoint - Final Local Cleanup Passed

- Implemented:
  - Appended the chronological `AGENT_CHANGELOG.md` closeout entry for the active `northstar/*` prototype tranche.
  - Stopped the leftover local Vite server on `127.0.0.1:3000` (`PID 6182`).
- Validation:
  - `git diff --check -- IMPLEMENTATION_STATUS.md AGENT_CHANGELOG.md docs/northstar_gap_analysis/prototype_contract.md frontend/src/styles/northstar.css frontend/src/styles/operations-pages.css docs/hardening/live-runtime-status-prototype-responsive-scroll-final.json docs/hardening/live-bootstrap-prototype-responsive-scroll-final.json docs/hardening/live-route-validation-prototype-responsive-scroll-final.json` -> passed.
  - `lsof -nP -iTCP:3000 -sTCP:LISTEN` returned no listener after stopping the dev server.
- Exact next action:
  - Report the deployed app URL, build/deployment ids, evidence artifacts, validation status, and unanimous review signoff.

### Checkpoint - Homepage Visual Signoff Retraction

- Trigger:
  - Product-owner review challenged the latest homepage/Command Center visual signoff against the `northstar/*` prototype screenshots.
- Finding:
  - The prior visual signoff was too broad and is retracted for the homepage/Command Center.
  - The deployed homepage is not visually indistinguishable from `northstar/screenshots/prototype_home1.png` and `northstar/screenshots/prototype_home2.png`.
  - `northstar/screenshots/prototype_cc.png` is a Control Center reference, not a Command Center/homepage reference; the prototype contract incorrectly grouped it under Command Center.
- Main blockers found:
  - Homepage live/degraded data replaces multiple prototype regions instead of preserving the prototype's visual and information architecture.
  - The capture report was treated as visual QA even though it only proves route/capture health, not region-by-region visual parity.
  - The final review lanes focused on previously known blockers rather than performing a fresh homepage bit-by-bit comparison.
- Subagent audit:
  - Visual fidelity reviewer: NOT SIGNED OFF for homepage parity.
  - Product/truth reviewer: NOT SIGNED OFF for homepage structure/provenance parity.
  - Process reviewer: NOT SIGNED OFF for the prior signoff process.
- Exact next action:
  - Split the prototype reference manifest so Command Center maps only to `prototype_home1.png` and `prototype_home2.png`, Control Center maps to `prototype_cc.png`, and add a real per-page visual-diff checklist before any renewed parity claim.

### Checkpoint - North Star Rules Hardening Started

- Trigger:
  - Product-owner direction: prevent the previous false visual signoff class from recurring, audit every page bit-by-bit, materialize all gaps, and iterate until each visible and functional gap is closed with true UI inspection.
- Required rules update:
  - Route capture success must be called capture health only, never visual QA.
  - Every route must map to exact reference screenshots before review.
  - Every visual signoff must cite a current screenshot, reference screenshot, compared viewport, gap count, reviewer role, and explicit deferrals.
  - Data-unavailable states must preserve prototype layout regions unless explicitly deferred with rationale.
  - Functional signoff must click every visible actionable control or record a precise truthful disabled/unavailable behavior.
- Exact next action:
  - Patch `AGENTS.md`, create a machine-readable route-to-reference manifest, and create the full per-page gap ledger before implementation resumes.

### Checkpoint - North Star Rules Hardening Landed

- Implemented:
  - Updated `AGENTS.md` so capture reports are explicitly capture-health artifacts only and cannot be used as visual QA signoff.
  - Added mandatory route-to-reference mapping, region-by-region side-by-side review, unavailable-state shape preservation, functional click validation, and named reviewer evidence requirements.
  - Added `docs/northstar_gap_analysis/reference_manifest.json` with explicit page-to-reference mappings. Command Center now maps only to `prototype_home1.png` and `prototype_home2.png`; Control Center maps to `prototype_cc.png`.
  - Added `docs/northstar_gap_analysis/full_page_audit.md` with the reopened Command Center gaps and pending slots for every remaining page.
  - Corrected `docs/northstar_gap_analysis/prototype_contract.md` so `prototype_cc.png` is no longer listed as a Command Center reference.
- Validation:
  - Rule hardening is documentation/manifest only so far; implementation is intentionally paused until remaining page audits are materialized.
- Exact next action:
  - Run true bit-by-bit audits for Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit Evidence, and Control Center against their manifest references.

### Checkpoint - Reference Manifest Corrections Continued

- Implemented:
  - Corrected Discover references to `prototype_discover1.png` and `prototype_discover2.png`.
  - Corrected CDE Registry app path to `/glossary-cdes?tab=cdes`.
  - Reclassified `prototype_stewardship2.png` as the checked-in CDE Registry screenshot despite its filename.
  - Removed `prototype_stewardship2.png` from the Stewardship visual reference set.
- Validation:
  - Confirmed `prototype_stewardship2.png` visibly shows the `Glossary & CDE Registry` page with the `CDE Registry` tab selected.
- Exact next action:
  - Re-run Discover and Stewardship audit against the corrected manifest, then merge all page findings into `full_page_audit.md`.

### Checkpoint - Full Page Audit Materialized

- Implemented:
  - Corrected the reference manifest app paths to the actual captured routes:
    `/command-center`, `/discover`, `/stewardship`, `/glossary-cdes`,
    `/glossary-cdes?tab=cdes`, `/lineage-atlas/{asset_fqn}`,
    `/audit-evidence`, and `/control-center`.
  - Merged subagent page audits into
    `docs/northstar_gap_analysis/full_page_audit.md` for Command Center,
    Discover, Stewardship, Glossary, CDE Registry, Lineage Atlas, Audit
    Evidence, Control Center, and shared cross-page gaps.
  - The tracker now lists 258 open page/shared gaps:
    Command Center 37, Discover 40, Stewardship 32, Glossary 31, CDE Registry
    28, Lineage Atlas 31, Audit Evidence 26, Control Center 23, shared 12.
- Validation:
  - Subagent reviewer inputs were incorporated for Discover, Stewardship,
    Glossary/CDE, Lineage/Audit, Control Center/shared shell, and the previous
    Command Center retraction.
  - This is audit materialization only; no parity claim is made.
- Risks:
  - The gap list is intentionally strict and blocking. It includes current visual
    drift, inert actions, missing interaction-state screenshots, and truth-shape
    gaps that must be closed or explicitly deferred before any page signoff.
- Exact next action:
  - Start implementation with shared shell/palette/navigation/AI and route-shape
    fixes, because those gaps affect every page and will reduce rework before
    page-specific passes.

### Checkpoint - Audit Contract Guard Started

- Trigger:
  - The previous false signoff was partly a process failure: reference mappings,
    open counts, and capture-health artifacts were allowed to drift from the
    actual page-by-page visual audit.
- Planned change:
  - Add a repository-local guard that checks the North Star manifest and full
    page audit ledger for missing references, stale `TBD` entries, count
    mismatches, and pages marked as complete while unchecked gaps remain.
- Validation plan:
  - Run the guard directly after creation and include it in subsequent tranche
    validation.

### Checkpoint - Audit Contract Guard Passed

- Implemented:
  - Added `scripts/check_northstar_audit_contract.py`.
  - The guard validates that the North Star reference manifest points to
    existing references, standalone visual routes have current screenshot
    patterns, the audit ledger has no `TBD` or `Audit pending` rows, and summary
    open-gap counts match the actual unchecked checklist items.
- Validation:
  - `python scripts/check_northstar_audit_contract.py` could not run because
    `python` is not on this macOS shell path.
  - `python3 scripts/check_northstar_audit_contract.py` -> passed.
- Exact next action:
  - Continue implementation while keeping this guard in the validation set so
    process drift is caught before any renewed signoff.

### Checkpoint - Audit Contract Guard Added To Frontend Scripts

- Implemented:
  - Added `northstar:audit-contract` to `frontend/package.json` so the guard can
    be run through the frontend validation surface.
- Validation:
  - `npm run northstar:audit-contract` from `frontend/` -> passed.
- Exact next action:
  - Continue shared/page implementation and then re-run the guard with page tests,
    capture, and live interaction checks.

### Checkpoint - Shared Shell North Star Tranche Started

- Trigger:
  - User requested a focused shared-shell pass while other page-specific work
    remains in flight. Ownership for this tranche is limited to the shared
    shell/topbar, Atlas AI panel/dock, global palette tokens, markdown
    rendering, disabled/loading semantics, and related tests.
- Inputs read:
  - `AGENTS.md`
  - `IMPLEMENTATION_STATUS.md`
  - `docs/northstar_gap_analysis/full_page_audit.md`
  - `docs/northstar_gap_analysis/reference_manifest.json`
  - `northstar/components/shell.jsx`
  - `northstar/styles/tokens.css`
  - `northstar/styles/atlas.css`
  - `.claude/skills/databricks-apps/SKILL.md`
- Planned scoped changes:
  - Bring shared dark palette tokens and global shell backgrounds closer to the
    checked-in `northstar/*` shell.
  - Tighten the topbar search shortcut into the prototype-style single `⌘K`
    key hint.
  - Improve floating Atlas AI grounding text, loading/readability, prompt
    grouping, resize affordance, and input placeholder.
  - Normalize common Genie/Markdown table answers so raw pipe-table syntax does
    not leak into the chat transcript.
- Validation plan:
  - Focused unit tests for `AppFrame`, shared shell primitives, `UserChip`,
    markdown rendering, and Atlas AI normalization.
  - `npm run typecheck`
  - `npm run lint -- --quiet`
  - `python3 scripts/check_northstar_audit_contract.py`
  - Scoped `git diff --check` for touched files.

### Checkpoint - Shared Shell Functional Controls Tranche Restarted

- Trigger:
  - Continue from the recovered checkpoint without resetting existing work.
  - Remaining blocking ledgers are still materially open: `full_page_audit.md`
    has 267 unchecked visual/page/shared rows and
    `functional_control_audit.md` has 75 unchecked functional-control rows.
- Scope for this checkpoint:
  - Shared controls that block every page: topbar search routing, workspace
    breadcrumb, notifications, help/profile menus, floating Atlas AI prompt/input
    states, markdown/evidence display, and evidence-routing semantics.
  - No page will be marked complete from this tranche; visual/page-specific rows
    remain open unless screenshot evidence explicitly proves otherwise.
- Validation plan:
  - Focused component tests for `AppFrame`, `GlobalHeader`, `TopbarSearch`,
    `UserChip`, and `useAtlasAiConversation`.
  - Local Playwright interaction capture with `GOVAT_PROTOTYPE_MOCK_API=1` to
    record shared control behavior across prototype routes.
  - `npm run northstar:audit-contract` after ledger updates.
  - Diff whitespace check on touched files.
- Current risks:
  - New subagent spawn is blocked by the active thread limit. Existing completed
    reviewer findings from Raman/Rawls remain blocking evidence and no signoff is
    implied.

### Checkpoint - Shared Shell Functional Controls Local Pass

- Implemented:
  - Converted the topbar search icon into an accessible mouse-submit button.
  - Changed topbar search submit behavior to search-first navigation: typed
    global searches now route to Discover with the query preserved instead of
    auto-opening the first direct asset result.
  - Added routed Atlas AI evidence chips for asset, stewardship, audit, and
    lineage evidence where a supported surface exists.
  - Added unit coverage for global search submit, Atlas AI evidence routing,
    answer normalization, markdown-table cleanup, and error transcript state.
  - Expanded the prototype capture harness with shared shell interactions for
    keyboard and mouse search, workspace breadcrumb, notifications, help, and
    profile menu.
  - Updated `functional_control_audit.md` only for rows backed by this evidence.
- Validation:
  - `npm run test -- src/components/AppFrame.test.jsx src/hooks/useAtlasAiConversation.test.jsx`
    -> passed (`20` tests).
  - `node --check frontend/scripts/atlas_prototype_current_capture.mjs` -> passed.
  - Local prototype-mock Playwright capture:
    `docs/northstar_visual_qa/prototype-current-shared-shell-functional-local/prototype-current-report.json`
    -> passed with `1` route capture, `6` interactions, `0` failures, `0` page
    errors, and `0` request failures.
  - `npm run northstar:audit-contract` -> passed.
  - Scoped `git diff --check` for touched shared shell files -> passed.
- Current audit state:
  - `functional_control_audit.md` now has `67` open functional rows:
    Command Center `6`, Discover `17`, Stewardship `9`, Glossary `7`, CDE
    Registry `5`, Lineage Atlas `7`, Audit Evidence `2`, Control Center `5`,
    Cross-Page Shared `9`.
  - `full_page_audit.md` is unchanged at `267` open visual/page/shared gaps.
- Risks:
  - Evidence is local `prototype_mock`, not live Databricks proof.
  - Atlas AI prompt-suggestion and UI error-state capture remain open in the
    cross-page ledger.
  - No page has signoff.
- Exact next action:
  - Continue with route-specific functional controls and then page-specific
    visual parity, starting with Discover because it still has the largest
    remaining functional open count and is a priority product surface.

### Checkpoint - Discover Functional Controls Tranche Started

- Trigger:
  - Discover remains the largest route-specific functional blocker with `17`
    open rows after the shared shell pass.
- Scope for this checkpoint:
  - Search valid/invalid/empty/loading behavior, facet count changes, clear
    filters, sort state, row favorite/kebab actions, selected preview tabs,
    Open Asset, Governance/Certify, preview sticky actions, and route-specific
    Atlas AI evidence behavior.
- Validation plan:
  - Inspect existing `DiscoveryWorkspace` controls and tests before editing.
  - Add/adjust focused component tests where the behavior is local to the
    component.
  - Extend `atlas_prototype_current_capture.mjs` Discover interaction specs to
    record each newly proven behavior.
  - Run focused Discover tests, local prototype-mock capture for Discover, audit
    contract, and scoped diff checks.
- Risks:
  - Backed mutations such as comments/access requests/certification must remain
    open unless the UI either persists auditable state or clearly renders a
    disabled/unavailable workflow.

### Checkpoint - Discover Functional Controls Implementation In Progress

- Planned edits before validation:
  - Make Discover favorites explicitly local in the UI/notice path so the row is
    not treated as a backed workflow claim.
  - Disable Discover preview Comment and Request access actions with visible
    unavailable copy because Discover does not currently create backed comments
    or access requests.
  - Expand the prototype-mock Discovery API to filter, sort, emit invalid-query
    states, and delay slow queries so Playwright can prove valid, invalid,
    empty, and loading search states.
  - Add Discover interaction specs for facets, clear filters, sort, row actions,
    preview tabs, Open Asset 360, Governance/Certify routing, sticky footer
    visibility, and Atlas AI recommendations.
- Validation still pending:
  - Focused Discover tests.
  - Discover-only local prototype-mock Playwright interaction capture.
  - `npm run northstar:audit-contract`.
  - Scoped diff whitespace check.
