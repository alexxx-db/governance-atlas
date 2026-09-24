# AI Governance Extension: Runbook

Operating the Phase 1 AI governance extension: setup, running collection and
reconciliation, reading run availability, importing intake, triaging
findings, and cleaning up sample data. Design: `DESIGN.md`. Evidence for the
SDK behavior referenced here: `PHASE0_FINDINGS.md`.

## 1. Setup

### Bundle variables

Set them as `BUNDLE_VAR_<name>` in `.env.<target>` (template: `.env.example`)
or as GitHub Environment variables for CI deploys.

| Variable | Purpose | Default |
|---|---|---|
| `ai_features_enabled` | Registers `/api/ai` and shows the AI Governance rail entry | `false` |
| `ai_intake_tag_key` | Tag on AI assets naming the intake ID (match rule M1) | `edw_intake_id` |
| `ai_tier_tag_key` | Tag holding the risk tier (control AIC-03) | `ai_risk_tier` |
| `ai_catalog_allowlist` | Catalogs whose registered models are collected; empty means `discovery_catalogs` (both empty means every visible catalog) | empty |
| `ai_tool_schema_allowlist` | `catalog.schema` entries whose UC functions are AI tools | empty (source reported as not configured) |
| `ai_intake_grace_days` | Days an approved intake may go unobserved before `registered_not_found` | `30` |
| `ai_collector_sp` | Service principal the job runs as in staging/prod (required there) | empty |
| `ai_job_schedule_pause_status` | `PAUSED` or `UNPAUSED` for the daily schedule | `PAUSED` |

The feature flag defaults to off. With it off, migrations 19 to 22 still
apply and the tables stay empty.

### Identity and grants

- **Dev:** the job runs as the deploying user (no `run_as`). It sees whatever
  that user can see. No permissions are changed (PHASE0 decision D7).
- **Staging/prod:** the job runs as `ai_collector_sp`. `bundle validate` fails
  if it is unset. Grant it:
  - `USE CATALOG`, `USE SCHEMA`, and `BROWSE` (or `EXECUTE`) on the models in
    the catalogs in `ai_catalog_allowlist`, so aliases are readable;
  - `USE CATALOG`/`USE SCHEMA` on the schemas in `ai_tool_schema_allowlist`;
  - `CAN_VIEW` (or `CAN_QUERY`) on the serving endpoints to inventory;
  - `SELECT` and `MODIFY` on the governance schema tables, plus `CAN_USE` on
    the SQL warehouse passed to the job.
- Endpoint `CAN_MANAGE` is **not** needed. It does not expose provider
  credentials (the serving API never returns them), so AIC-09 reports
  `unknown` regardless.

## 2. Running collection and reconciliation

The job `atlas-ai-collect-and-reconcile` has two tasks: `collect_databricks`
then `reconcile`. Both share one run ID, `dbx-<job run id>`.

```bash
set -a; . ./.env.dev; set +a
databricks bundle run atlas_ai_collect_and_reconcile -t dev --profile "$ATLAS_PROFILE"
```

What each task does:

1. **collect_databricks** starts a `reconciliation_runs` row
   (`status='collecting'`), probes and collects every source, appends
   redacted observations, and records per-source availability in
   `sources_json`. The status becomes `reconciling`.
2. **reconcile** matches observations to intake, writes registry state,
   relationships, findings, and control results, then marks the run
   `succeeded`. A failure marks it `failed` with a reason; readers keep
   showing the last succeeded run.

The job refuses to overlap (`max_concurrent_runs: 1`).

### Reading run availability

In the app, the AI Governance page subtitle names the last completed run.
When any source was unavailable or degraded, or a later run failed, a
"Data availability is limited" banner lists each cause.

Directly:

```sql
SELECT run_id, status, sources_json, counts_json, failure_reason, started_at, finished_at
FROM <gov_catalog>.<gov_schema>.reconciliation_runs
ORDER BY started_at DESC LIMIT 5;
```

Source states:

| Source | `available` | `degraded` | `unavailable` |
|---|---|---|---|
| `serving_endpoints` | listed | credential posture unreadable for some endpoints | listing failed |
| `registered_models` | all readable | some models permission-denied (partial) | listing failed |
| `mcp_connections` | listed | | listing failed |
| `uc_function_tools` | listed | | failed, or no tool schemas configured |
| `ai_asset_registry` | | | always: no such API in SDK 0.95 (agents come from `agent/*` endpoints) |

`registered_not_found` is raised and auto-resolved only when both
`serving_endpoints` and `registered_models` were `available`. Findings for
kinds whose source was not `available` are never auto-resolved that run.

## 3. Importing intake

AI Governance, then Intake, then **Import CSV** (stewards and admins only).

1. Upload or paste the CSV. Required columns: intake ID, title, state, owner
   (accepted spellings are in `atlas/ai/field_maps/intake_csv.yaml`).
2. **Validate (dry run)**. Nothing is written. The per-row report lists every
   error.
3. **Commit**, then confirm. The commit is all-or-nothing: any invalid row
   rejects the whole file. Each committed row writes one
   `ai.intake.ingested` audit row and change event (`source='import'`,
   `ingest_source='csv'`).

States map to `draft | submitted | approved | rejected | retired` (for example
"Denied" becomes `rejected`, "In review" becomes `submitted`).

## 4. Triaging findings

AI Governance, then Findings (stewards and admins). Findings are grouped by
type, most severe first. Open one to see its evidence: reason, match rule and
score, candidate intakes, declared-versus-observed differences, and where it
was observed.

| Action | Effect | Next run |
|---|---|---|
| Acknowledge | `state='acknowledged'` | Keeps updating evidence; auto-resolves if the condition clears |
| Assign | Sets the assignee email | Unchanged (task linking is not in Phase 1) |
| Resolve (note required) | `state='resolved'`, `resolved_by=<you>` | A steward resolution stands even if the condition holds |
| Suppress (reason required) | `state='suppressed'` | Stays suppressed; never auto-resolved or reopened |
| Confirm match (intake required) | Override `declares` relationship, intake alias, finding resolved | The asset matches by rule M2 (deterministic) |

Every action writes its audit row and change event **before** the change. If
the audit write fails, nothing changes. The events appear on the Evidence
page and in the asset's History tab.

## 5. Sample data (dev only)

`scripts/seed_ai_sample_data.py` creates real, labeled sample objects
(decision D1): two external-model endpoints (placeholder secret references,
never queried), one MCP-flagged HTTP connection with a placeholder host, one
tagged UC function tool, one registered model, and sample intake records. It
does not create a Databricks-hosted endpoint, because that would start paid
compute. The expected findings are asserted by
`tests/test_ai_sample_scenario.py`.

```bash
set -a; . ./.env.dev; set +a
python scripts/seed_ai_sample_data.py            # print the plan
python scripts/seed_ai_sample_data.py --live     # create
# add main.atlas_ai_samples to BUNDLE_VAR_ai_tool_schema_allowlist, redeploy, run the job twice
python scripts/seed_ai_sample_data.py --cleanup  # remove objects and purge sample rows
```

Sample rows carry `provenance_class='sample'` and `sample_run_id`, and render
with a **Sample** badge. `--cleanup` deletes the tagged endpoints, the
connection, the model, the sample schema, and the secret scope. It then purges
every sample run's rows from the AI tables through `AiStore.purge_sample`,
which is audited.

## 6. Stress validation

```bash
python scripts/run_synthetic_stress_validation.py --scenario ai                  # plan only
python scripts/run_synthetic_stress_validation.py --scenario ai --live \
  --profile DEFAULT --warehouse-id "$BUNDLE_VAR_warehouse_id" --catalog main
```

This builds a run-scoped schema `atlas_ga_stress_<run>` with the full
governance model and runs three reconciliations of synthetic sample rows. It
checks idempotency, suppression persistence, the confirmation becoming M2,
audit/event pairing, and no organic leaks, then drops the schema and verifies
zero leftovers. Synthetic observations exist only in this throwaway schema,
never in the schema the app reads.
