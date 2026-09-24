# AI Governance Extension: Design

Status: **Draft v0.2, 2026-09-24. Verified against SDK 0.95 (2026-09-24); not yet reviewed.**

Phase 0 evidence and the rationale for each correction: `PHASE0_FINDINGS.md`.

This document was built from the Phase 0/1 implementation brief. It was
grounded in the current repo (migrations 1 to 18, `atlas/store.py`,
`atlas/services/metadata_audit.py`, the frontend provenance filter) and in the
SDK class definitions of the locally installed `databricks-sdk` **0.102.0**.
The app pins **0.95.0**, so Phase 0 re-verifies every SDK field named here
(checks V1 to V9 in section 15). Where this document and the pinned SDK
disagree, the SDK wins: update this file with a dated "Verified against SDK
0.95" note.

Items marked **[Decision needed]** are open choices for the product owner.
Items marked **[Proposed]** are the author's proposal, not an agreed spec.

---

## 1. Purpose and scope

Governance Atlas inventories Unity Catalog data assets. This extension makes
Atlas inventory **AI assets** and reconcile them against **declared intake
records**, so a steward can see:

- which AI assets exist on the platform (observed);
- which were declared and approved through intake (declared);
- where the two disagree (findings);
- the control posture of each asset (controls).

AI asset kinds in scope:

| Kind | `entity_kind` | Observed from |
|---|---|---|
| Registered model | `ai_model` | UC registered models |
| Model version | `ai_model_version` | UC model versions |
| Serving endpoint | `serving_endpoint` | Model Serving endpoints |
| External model | `external_model` | External served entities on endpoints |
| Agent | `agent` | Serving endpoints with task `agent/v1/*` (Phase 1; verified V6). Agent apps: Phase 2 |
| MCP server | `mcp_server` | UC connections classified as MCP (V4) |
| UC function tool | `uc_function_tool` | UC functions in allowlisted schemas |
| Intake record | `intake_record` | CSV import (Phase 1); ServiceNow (Phase 2) |

## 2. Principles

These restate `AGENTS.md` for this extension. They are acceptance criteria,
not aspirations.

1. **Truthfulness.** Nothing fabricated renders as live. A source that could
   not be read renders as unavailable or degraded, with the reason. An empty
   table means "observed nothing", never "failed to look".
2. **Provenance on every datum.** Each inventory row, finding, and control
   result carries source system, collector and version, run ID, and
   observed-at time.
3. **Fail-closed audit.** Every mutation writes `metadata_audit_log` and a
   `change_events` row (via `record_audit_log(..., fail_closed=True)`, which
   already emits the change event). If the audit write fails, the mutation
   fails.
4. **No enforcement.** Atlas reads posture. It never creates, modifies, or
   deletes endpoints, gateway config, permissions, policies, connections, or
   models. Phase 1 adds no platform writes at all.
5. **No payloads.** Never read inference table contents, prompts, or
   responses. Usage (Phase 2) comes only from aggregated system tables.
6. **No secrets persisted.** Config is stored only through allowlist
   serializers (section 8). At most the *name* of a secret reference is kept.
7. **Jobs collect; the app governs.** Collection and reconciliation run as
   Databricks jobs. The app never calls external APIs or collects
   in-process.
8. **Single writer per table.** See section 3.3.
9. **Feature flag.** Everything user-visible sits behind
   `ai_features_enabled` (default `false`). Migrations apply regardless and
   are harmless when unused.

## 3. Architecture

### 3.1 Components

```
Jobs (bundle resources)                  Governance schema (Delta)            App
dbx_ai_collector ──append──▶ ai_asset_observations ─┐
intake CSV import (app, steward) ─▶ intake_records ─┤
                                                   ├─▶ reconcile job ─▶ entity_registry / entity_aliases / entity_relationships
                                                   │                    reconciliation_findings
                                                   │                    ai_control_results
                                                   │                    reconciliation_runs
                                                   │                    change_events (+ metadata_audit_log)
/api/ai/* ◀── reads derived tables; writes steward decisions through store methods
/ai surface (Inventory, AI Asset 360, Findings, Intake)
```

### 3.2 Package layout

```
atlas/ai/models.py            dataclasses (Observation, IntakeRecord, Finding, ControlResult, ProbeResult, RunContext)
atlas/ai/redaction.py         allowlist serializers + credential scrubber
atlas/ai/probes.py            probe(fn) -> ProbeResult; never raises
atlas/ai/collectors/databricks.py
atlas/ai/intake.py            CSV parsing + YAML field map (shared with Phase 2 ServiceNow)
atlas/ai/reconcile.py         matching, finding rule registry, idempotent keys
atlas/ai/controls.py          control registry keyed by control ID
atlas/ai/store.py             AiStore: wraps the governance store (Delta or Lakebase dual-write)
atlas/ai/jobs/collect_databricks.py
atlas/ai/jobs/reconcile.py
atlas/ai/field_maps/intake_csv.yaml
atlas/api/ai.py               build_ai_router()
frontend/src/surfaces/ai/     (follows the existing surfaces/<area>/ convention)
scripts/seed_ai_sample_data.py
tests/test_ai_*.py            (flat, matching the existing tests/ convention)
```

`atlas/ai/store.py` holds `AiStore`, which wraps whichever governance store
the caller holds rather than being a mixin on `GovernanceStore`. Registry and
alias writes reach the Lakebase mirror only through `DualWriteGovernanceStore`,
so a mixin calling `self.upsert_entity_registry` on the Delta store would skip
the mirror. (Revised in Phase 1 Step 4; was a mixin proposal.)

Fail-closed ordering: every `AiStore` mutation writes its audit row and change
event **before** the mutation. If they fail, the mutation never runs. If the
mutation then fails, a second audit and event pair with status `failed`
records it.

### 3.3 Write ownership

| Table | Writer | Notes |
|---|---|---|
| `ai_asset_observations` | collector jobs | Append-only |
| `intake_records`, `intake_records_history` | app (steward import); Phase 2 ServiceNow collector | Upsert + history append |
| `reconciliation_runs` | reconcile job | Collector also records probe results into the run it starts |
| `reconciliation_findings` | reconcile job (derived fields); app (steward fields only) | See 5.4 |
| `ai_control_results` | reconcile job | Per-run rows |
| `entity_registry` AI rows | reconcile job | App never writes AI registry rows |
| `entity_aliases`, `entity_relationships` for AI | reconcile job; app for steward confirmations | Confirmations use `authority_source='override'` |

Steward decisions are durable inputs the job respects: suppressions persist,
and confirmations become aliases that match as M2 on the next run.

### 3.4 Run lifecycle

1. Job task `collect_databricks` starts a `reconciliation_runs` row
   (`status='collecting'`), runs probes, collects, redacts, appends
   observations tagged with `run_id`, and records per-source probe results
   in `sources_json`.
2. Job task `reconcile` reads the latest observation per
   `(source_system, source_entity_id)` plus all intake records, computes
   matches, findings, and controls, then writes with MERGE.
3. The run is marked `succeeded` last. The app reads control results only
   from the **latest succeeded run**, so a failed run never shows partial
   derived state. Findings are idempotent MERGEs keyed on `finding_id`, so
   re-running a failed run converges.

Delta has no multi-table transactions. "Succeeded run is the commit marker"
is the consistency model. **[Proposed]**

## 4. Data model

### 4.1 Identifiers

| Kind | `source_entity_id` | Rationale |
|---|---|---|
| `serving_endpoint` | endpoint `id` (fallback: `name`) | Stable across renames |
| `external_model` | `<endpoint id>/<served entity name>` | Served entities have no global ID |
| `ai_model` | model `full_name` | UC three-part name |
| `ai_model_version` | `<full_name>@<version>` | |
| `mcp_server` | connection `full_name` or `name` | |
| `uc_function_tool` | function `full_name` | |
| `agent` | endpoint id or app name (Phase 2) | |
| `intake_record` | `intake_id` | |

`entity_id` in `entity_registry` for AI assets is
`sha256("ai|" + entity_kind + "|" + source_system + "|" + source_entity_id)[:32]`,
so it is deterministic across runs. **[Proposed]**

`content_hash` is SHA-256 over canonical JSON (sorted keys, no whitespace) of
the normalized, redacted fields, excluding volatile fields (timestamps,
ETags, state, scaling counters).

### 4.2 DDL (migrations 19 to 22)

Follows the existing `Migration` pattern and `{placeholder}` table names.
Every table carries provenance and sample markers.

**Migration 19: `ai_asset_observations`**

```sql
CREATE TABLE IF NOT EXISTS {ai_asset_observations_table} (
    observation_id          STRING NOT NULL,
    run_id                  STRING NOT NULL,
    source_system           STRING NOT NULL COMMENT 'databricks | servicenow | aws | ... (open-ended)',
    collector               STRING NOT NULL COMMENT 'e.g. dbx_ai_collector',
    collector_version       STRING NOT NULL,
    entity_kind             STRING NOT NULL,
    source_entity_id        STRING NOT NULL,
    parent_source_entity_id STRING,
    display_name            STRING,
    platform                STRING COMMENT 'databricks | external',
    provider                STRING COMMENT 'external model provider, e.g. openai, anthropic',
    model_family            STRING,
    owner                   STRING,
    tags_json               STRING,
    config_json             STRING COMMENT 'redacted via atlas/ai/redaction.py allowlists only',
    relationships_json      STRING COMMENT 'observed edges, e.g. serves',
    content_hash            STRING NOT NULL,
    probe_state             STRING COMMENT 'available | degraded',
    provenance_class        STRING NOT NULL COMMENT 'organic | sample',
    sample_run_id           STRING,
    observed_at             TIMESTAMP NOT NULL,
    recorded_at             TIMESTAMP NOT NULL
) USING DELTA
```

**Migration 20: `intake_records`, `intake_records_history`**

```sql
CREATE TABLE IF NOT EXISTS {intake_records_table} (
    intake_id          STRING NOT NULL,
    title              STRING NOT NULL,
    state              STRING NOT NULL COMMENT 'draft | submitted | approved | rejected | retired',
    owner_email        STRING NOT NULL,
    business_unit      STRING,
    risk_tier          STRING,
    platform           STRING,
    provider           STRING,
    model_family       STRING,
    intended_use       STRING,
    approved_at        TIMESTAMP,
    review_due_at      TIMESTAMP,
    source_system      STRING NOT NULL COMMENT 'csv | servicenow',
    source_record_id   STRING,
    ingest_source      STRING NOT NULL COMMENT 'csv | servicenow',
    ingest_run_id      STRING NOT NULL,
    attributes_json    STRING COMMENT 'mapped extra fields from the field map',
    content_hash       STRING NOT NULL,
    provenance_class   STRING NOT NULL COMMENT 'organic | sample',
    sample_run_id      STRING,
    created_at         TIMESTAMP,
    created_by         STRING,
    updated_at         TIMESTAMP,
    updated_by         STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS {intake_records_history_table} (
    history_id     STRING NOT NULL,
    intake_id      STRING NOT NULL,
    change_kind    STRING NOT NULL COMMENT 'created | updated | unchanged',
    before_json    STRING,
    after_json     STRING,
    ingest_source  STRING NOT NULL,
    ingest_run_id  STRING NOT NULL,
    recorded_at    TIMESTAMP NOT NULL,
    recorded_by    STRING
) USING DELTA
```

**Migration 21: `reconciliation_runs`, `reconciliation_findings`**

```sql
CREATE TABLE IF NOT EXISTS {reconciliation_runs_table} (
    run_id            STRING NOT NULL,
    job_run_id        STRING,
    status            STRING NOT NULL COMMENT 'collecting | reconciling | succeeded | failed',
    rule_set_version  STRING,
    sources_json      STRING COMMENT 'per-source ProbeResult: state, reason, sampled_at',
    counts_json       STRING COMMENT 'opened/updated/resolved by finding type; observations by kind',
    failure_reason    STRING,
    triggered_by      STRING,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP
) USING DELTA;

CREATE TABLE IF NOT EXISTS {reconciliation_findings_table} (
    finding_id          STRING NOT NULL COMMENT 'sha256(type|entity_id|intake_id|rule_id)',
    finding_type        STRING NOT NULL,
    rule_id             STRING NOT NULL,
    severity            STRING NOT NULL COMMENT 'critical | high | medium | low',
    state               STRING NOT NULL COMMENT 'open | acknowledged | resolved | suppressed',
    entity_id           STRING,
    entity_kind         STRING,
    intake_id           STRING,
    match_rule          STRING COMMENT 'M1 | M2 | M3 | M4',
    match_score         DOUBLE,
    evidence_json       STRING,
    first_seen_run_id   STRING NOT NULL,
    last_run_id         STRING NOT NULL,
    first_seen_at       TIMESTAMP NOT NULL,
    last_seen_at        TIMESTAMP NOT NULL,
    assignee_email      STRING,
    task_id             STRING,
    resolution_note     STRING,
    suppression_reason  STRING,
    resolved_by         STRING COMMENT 'steward email | system',
    resolved_at         TIMESTAMP,
    state_changed_by    STRING,
    state_changed_at    TIMESTAMP,
    provenance_class    STRING NOT NULL,
    sample_run_id       STRING
) USING DELTA
```

**Migration 22: `ai_control_results`**

```sql
CREATE TABLE IF NOT EXISTS {ai_control_results_table} (
    result_id        STRING NOT NULL,
    run_id           STRING NOT NULL,
    entity_id        STRING NOT NULL,
    entity_kind      STRING NOT NULL,
    control_id       STRING NOT NULL COMMENT 'AIC-01 ...',
    control_version  STRING NOT NULL,
    status           STRING NOT NULL COMMENT 'pass | fail | not_applicable | unknown',
    signal_source    STRING COMMENT 'where the signal came from, or why it was not observable',
    evidence_json    STRING,
    observed_at      TIMESTAMP NOT NULL,
    provenance_class STRING NOT NULL,
    sample_run_id    STRING
) USING DELTA
```

Reserved, not created in Phase 1: **23** `ai_usage_daily` (Phase 2 usage and
spend), **24** `mcp_reviews` (Phase 2 MCP review workflow).

`entity_registry.reconciliation_state` gains the value `pending_intake`. That
is a comment-level change only; no DDL.

### 4.3 Reuse of existing tables

- `entity_registry`: one row per AI asset (`entity_kind` from section 1,
  `source_system`, `source_entity_id`, `reconciliation_state`,
  `reconciliation_confidence`, `observed_at`).
- `entity_aliases`: `alias_type='external_id'` with `source` in
  `intake_id | servicenow_sys_id`.
- `entity_relationships`: `relationship_kind` in `serves` (observed,
  `authority_source='registry'`), `declares` (intake to asset,
  `authority_source='registry'` or `'override'`).
- `tasks`: finding assignment links to the existing tasks table where
  stewardship already does so.
- Lakebase mirror: `entity_registry` writes go through the existing
  dual-write path so the mirror stays consistent.

## 5. Reconciliation

### 5.1 Matching

| Rule | Condition | Confidence |
|---|---|---|
| M1 | Observed tag `<intake_tag_key>` equals `intake_id` | 1.00 |
| M2 | Existing alias (`intake_id` or `servicenow_sys_id`) from a steward confirmation | 1.00 |
| M3 | Same owner, name similarity >= 0.85, and same platform or provider | 0.70 to 0.90 |
| M4 | Phase 2 (fuzzy cross-source); extension point only | |

M3 score **[Proposed]**:
`0.70 + 0.20 * (similarity - 0.85) / 0.15`, clamped to `[0.70, 0.90]`.
Similarity is `difflib.SequenceMatcher` ratio over normalized names
(lowercased, `[_\-\s.]` collapsed).

Thresholds: `>= 0.90` matched, `0.50 to < 0.90` ambiguous, `< 0.50`
unmatched. Rules evaluate in order M2, M1, M3; the first hit wins.

### 5.2 Finding rules (Phase 1)

Rules live in a registry (`RULES: dict[rule_id, Rule]`), not hard-coded
branches, so Phase 2+ rules slot in.

| Type | Rule ID | Condition |
|---|---|---|
| `found_not_registered` | `R-FNR-01` | Observed asset, no match |
| `rejected_but_running` | `R-RBR-01` | Matched to an intake with state `rejected` |
| `registered_not_found` | `R-RNF-01` | Approved intake older than `grace_days` (default 30) with no match |
| `found_different` | `R-FDF-01` | Matched, but provider or model family differs, tier tag differs from intake tier, or owner changed |
| `ambiguous_match` | `R-AMB-01` | Best score in the ambiguous range |

Reserved for Phase 2: `stale_observation` (`R-STL-01`).

Units and children (Phase 1 Step 7): external models and model versions
inherit their parent endpoint's or model's match. Findings are raised on the
parent, so a shadow endpoint serving an external model is one `high`
`found_not_registered`, not two findings. `found_different` compares the
children's provider and model family. An approved intake that is the best
candidate of an ambiguous asset is not also reported `registered_not_found`.
`registered_not_found` is raised and auto-resolved only when both core
sources (serving endpoints, registered models) were fully available that
run, and auto-resolution skips kinds whose source was unavailable or degraded.
M1 matches also write an informational alias with `source='intake_tag'`;
only steward confirmations (`source='intake_id'`) count as M2, so removing the
tag later still un-matches the asset.

### 5.3 Severity

| Type | Severity |
|---|---|
| `rejected_but_running` | critical |
| `found_not_registered` | high for `external_model`, `agent`, `mcp_server`; medium otherwise |
| `found_different` | high if provider or model family differs; medium if tier differs; low if only owner changed |
| `registered_not_found` | medium |
| `ambiguous_match` | low |
| `stale_observation` (Phase 2) | low |

**[Proposed]**

### 5.4 Idempotency and lifecycle

- `finding_id = sha256(f"{finding_type}|{entity_id or ''}|{intake_id or ''}|{rule_id}")`.
- Re-runs MERGE on `finding_id`: update `last_seen_at`, `last_run_id`,
  `evidence_json`, `severity`, `match_score`. Never overwrite steward
  fields (`state` when `suppressed` or `acknowledged`, `assignee_email`,
  `task_id`, `resolution_note`, `suppression_reason`).
- A condition that no longer holds auto-resolves (`state='resolved'`,
  `resolved_by='system'`), **except** suppressed findings, which stay
  suppressed.
- A **system**-resolved finding whose condition returns reopens
  (`state='open'`). A steward resolution stands even if the condition still
  holds; accepting a known condition is what suppress is for. (Clarified in
  Phase 1 Step 4.)
- Steward actions: acknowledge, assign, resolve (note required), suppress
  (reason required), confirm match (writes a `declares` relationship with
  `authority_source='override'` plus the alias; M2 on the next run).

## 6. Controls

Controls are registered by ID (`CONTROLS: dict[control_id, Control]`). A
control returns `pass | fail | not_applicable | unknown`. **Unknown** whenever
the signal was not observable (probe unavailable, field absent, insufficient
permission). Posture excludes unknowns from the denominator and reports the
unknown count separately.

| ID | Control | Applies to | Phase |
|---|---|---|---|
| AIC-01 | Linked to an approved intake | all observed kinds | 1 |
| AIC-02 | Accountable owner resolves in the identity directory | all | 2 |
| AIC-03 | Risk tier tag present and equal to the intake tier | endpoints (models: always `unknown`, tags not observable, V1) | 1 |
| AIC-04 | AI Gateway usage tracking enabled | serving endpoints | 1 |
| AIC-05 | Rate limits configured | serving endpoints | 2 |
| AIC-06 | Inference table logging enabled (config only; contents never read) | serving endpoints | 1 |
| AIC-07 | Guardrails configured | serving endpoints | 2 |
| AIC-08 | Endpoint permissions least-privilege | serving endpoints | 2 |
| AIC-09 | External provider credentials use a secret reference, not plaintext. **Always `unknown` from the serving API**: it returns provider configs with no credential fields even to `CAN_MANAGE` (PHASE0_FINDINGS D7 follow-up). Kept as a registered control so a future signal source can evaluate it | external models | 1 |
| AIC-10 | Model version has a governed alias and a source run | model versions | 2 |
| AIC-11 | Evaluation evidence exists (MLflow) | models, agents | 3 |
| AIC-12 | Evaluation is fresh | models, agents | 3 |
| AIC-13 | Provider model not deprecated | external models | 2 |
| AIC-14 | MCP server reviewed | MCP servers | 2 |
| AIC-15 | UC function tool has owner and description | UC function tools | 2 |

**[Proposed]** control definitions.

Posture bands (per asset): `strong` (all applicable known controls pass),
`partial` (some fail), `weak` (majority fail), `unknown` (no known results).

## 7. Collectors and intake

### 7.1 Databricks collector (`dbx_ai_collector`)

Runs as the collector service principal inside a job. Uses the SDK via
`WorkspaceClient()` with the job's identity and writes through store methods
on the SQL warehouse (same `UCSQLClient` path as the app), so SQL escaping and
audit conventions are shared.

| Adapter | SDK surface (verify in Phase 0) | Emits |
|---|---|---|
| Serving endpoints | `serving_endpoints.list()` → `ServingEndpoint` (`id`, `name`, `tags`, `task`, `ai_gateway`, `config.served_entities: ServedEntitySpec`); `get()` only for AIC-09 (list omits provider configs) | `serving_endpoint` (or `agent` when task is `agent/v1/*`); one `external_model` per served entity with `external_model` set; `serves` edges |
| Registered models | `registered_models.list`, `model_versions.list` → `RegisteredModelInfo`, `ModelVersionInfo` (`aliases`) | `ai_model`, `ai_model_version` |
| Model aliases | `registered_models.get(full_name, include_aliases=True)` per model, bounded by the catalog allowlist (V1). Model tags are **not observable** (the tag API and `information_schema` cover catalogs, schemas, tables, columns, volumes, routines only) | aliases on model observations; per-model permission failure = `degraded` |
| Connections | `connections.list` → `ConnectionInfo`; read `connection_type` as a raw string (newer types such as `MANAGED_POSTGRESQL` deserialize to `None` in 0.95) | `mcp_server` when `connection_type == 'HTTP'` and `options.is_mcp_connection == 'true'` (V4) |
| UC functions | `functions.list` in allowlisted schemas → `FunctionInfo` | `uc_function_tool` |
| Apps | `apps.list` works (V5) | Deferred to Phase 2 (decision D6) |
| AI asset registry API | only if V6 finds one; else probe stub reporting `unavailable` | |

Verified against SDK 0.95 (2026-09-24), see `PHASE0_FINDINGS.md`:

- `ServedEntityOutput` has `external_model`, `foundation_model`,
  `entity_name`, `entity_version`, **`environment_vars`** (may contain
  secrets; never stored).
- `ExternalModel` has `provider`, `name`, `task`, and per-provider config
  objects (`openai_config`, `anthropic_config`, ...) that can hold plaintext
  keys or secret references.
- `AiGatewayConfig` has `usage_tracking_config.enabled`,
  `inference_table_config.enabled`, `rate_limits`, `guardrails`,
  `fallback_config`.
- `ModelVersionInfo` has **no tags field**, and no API or `information_schema` view exposes registered model tags.
- Provider configs carry `*_plaintext` fields (for example `openai_api_key_plaintext`, `anthropic_api_key_plaintext`, `microsoft_entra_client_secret_plaintext`). The allowlist must never include them. For the verifying caller, `get()` returned the provider config with every field empty.
- `ConnectionType` has **no MCP value**, but HTTP connections carry the option
  `is_mcp_connection` (V4). No naming convention is needed.

### 7.2 Probes

`probe(fn) -> ProbeResult(ok, state, reason, sampled_at)` never raises. Each
adapter runs behind a probe; the probe result is recorded per source in
`reconciliation_runs.sources_json`. A failed probe means the source is
`unavailable` with a sanitized reason (`atlas.util.error_text`), and the UI
shows a banner. Findings that depend on an unavailable source are not
auto-resolved during that run.

### 7.3 Intake CSV import

- Parse the CSV and map columns through `atlas/ai/field_maps/intake_csv.yaml`,
  the same schema the Phase 2 ServiceNow collector uses.
- Normalize state to `draft | submitted | approved | rejected | retired`.
- Required: `intake_id`, `title`, `state`, `owner`.
- `POST /api/ai/intake/import?mode=dry_run|commit`, steward and admin only,
  row cap `bulk_import.MAX_ROWS_PER_REQUEST` (5000).
- Commit writes `intake_records` + history, one audit event per row
  (`ai.intake.ingested`, `source='import'`), `ingest_source='csv'`.

## 8. Redaction and secrets

- **Allowlist first.** Each object type has an explicit field allowlist.
  Fields not on it are dropped, not masked.
- **Scrubber second.** A recursive scrubber drops any key matching (case
  insensitive) `key, token, secret, password, credential, api_key, private,
  bearer, authorization`, and any value that looks like a credential
  (`sk-...`, `dapi...`, JWT-shaped strings, `Bearer ...`).
- **Secret references.** A value matching the Databricks secret reference
  syntax `{{secrets/<scope>/<key>}}` is kept only as
  `{"secret_ref": "<scope>/<key>"}`. This is what AIC-09 evaluates.
- `environment_vars` on served entities are never stored, not even key
  names. **[Proposed]**
- Redacted `config_json` is returned only to steward and above.

## 9. API (`atlas/api/ai.py`)

Registered only when `ai_features_enabled` is true. Uses the existing response
envelope (provenance, availability, `authoritative`).

| Endpoint | Role | Notes |
|---|---|---|
| `GET /api/ai/summary` | reader+ | Counts by kind; open findings by type and severity; posture bands; latest run with per-source availability |
| `GET /api/ai/inventory` | reader+ | Filters: kind, provider, platform, tier, reconciliation state, has open findings; pagination; sort |
| `GET /api/ai/assets/{entity_id}` | reader+ | Declared vs observed with field diff; relationships; controls; history |
| `GET /api/ai/assets/{entity_id}/controls` | reader+ | |
| `GET /api/ai/findings` | steward+ | Filters and pagination |
| `PATCH /api/ai/findings/{finding_id}` | steward+ | acknowledge, assign, resolve, suppress; audited |
| `POST /api/ai/findings/{finding_id}/confirm-match` | steward+ | Override relationship + alias; resolves finding |
| `GET /api/ai/intake` | reader+ | With link status |
| `POST /api/ai/intake/import` | steward+ | Section 7.3 |
| `GET /api/ai/reconciliation/runs` | reader+ | |

Reads come only from the governance tables. An unavailable source yields a
`degraded` envelope, never an empty authoritative one.

Implemented (Phase 1 Step 8): envelopes use source `governance-store:ai`, a
trusted live source for the frontend provenance filter, so degraded views
render as degraded rather than hidden. Every view reflects the latest
**succeeded** run. With no succeeded run, counts are `null` and the state is
`unavailable`; a failed later run or a non-available source makes the state
`degraded` with one warning per cause. Assigning a finding sets
`assignee_email` only: the existing task creation
(`create_workflow_request`) models asset description and tag change requests,
not AI findings, so `task_id` stays reserved until a finding task type exists.
The OpenAPI snapshot is generated with the flag off (the default contract),
so it does not list `/api/ai`.

## 10. UI (`/ai` surface)

Rail entry "AI Governance", hidden when the flag is off. Built from the
existing system components (`PageShell`, `DataTable`, `FilterBar`, `Drawer`,
`StatTile`, `TabStrip`, `SectionCard`, `EntityChip`, `Badge`) and
`useAtlasQuery` with the `statusContract.js` states.

- **Inventory:** tiles (AI assets; shadow AI = open `found_not_registered` +
  `rejected_but_running`; ambiguous matches; posture coverage) and a table.
- **AI Asset 360:** Overview (declared vs observed side by side, differences
  highlighted, provenance chips), Controls (with "Unknown: signal not
  observable from <source>"), History. Relationship graph and usage tabs
  show "Available in a later release"; no placeholder content.
- **Findings:** queue grouped by type and severity; evidence drawer with
  match scores and diff; actions with confirmation and required reasons.
- **Intake:** table with link status; import dialog with dry-run preview.
- A source marked unavailable in the latest run shows a banner naming the
  source and reason. Counts never show zero when data is unavailable.

### 10.1 Sample data and the frontend provenance filter

`frontend/src/lib/nonAuthoritativeEvidence.js` fails closed on source values
such as `seed`, `mock`, `fixture`, and `prototype`, and on
`authoritative=false` without a trusted live source. AI rows must therefore:

- never use those words as `source`, `provider`, or `kind` values;
- express sample status through `provenance_class='sample'` and
  `sample_run_id`, rendered as an explicit "Sample" badge.

**Decided 2026-09-24, D1: real labeled sample objects only (option 1).** Original question: The brief allows writing
"equivalent observation rows marked as sample" when a real object (for
example an external model endpoint) cannot be created safely in dev. Such
rows describe objects that do not exist. Options:

1. Create real sample objects only (for example an external model endpoint
   whose key is a secret reference to a non-functional placeholder). Every
   observation is then a true observation of a real, labeled sample object.
   **Recommended.**
2. Allow synthetic rows, served with `authoritative=false`. The existing
   filter will hide them from customer-facing paths, so they cannot support
   the demo walk-through.
3. Allow synthetic rows only in a run-scoped stress schema (as
   `run_synthetic_stress_validation.py` does), never in the governance schema
   the app reads.

## 11. Phases

**Phase 0: verification and readiness.** V1 to V9 (section 15), baseline
tests, reused-component risk review, `PHASE0_FINDINGS.md`.

**Phase 1: demo slice.** Config and flag; migrations 19 to 22; models,
redaction, probes; store methods; Databricks collector job; intake CSV
import; reconciliation (M1 to M3, five finding types, AIC-01/03/04/06/09);
API; `/ai` surface; sample data and stress scenarios; runbook. Done when a
reviewer can walk the "AI inventory view" and "Findings" demo segments in the
dev app and every datum traces to an observation or intake row.

**Phase 2: pilot.** ServiceNow inbound (Table API through a UC HTTP
connection, same field map) and write-back consumer (`change_event_consumers`
with `consumer_kind='integration'`, offsets, idempotent PATCH, dead letters,
dry-run); usage and spend (migration 23); full control set and posture
scoring; MCP review workflow (migration 24, `thread_type='mcp_review'`); M4
and stale observations; relationship graph (lineage canvas v2); Genie views;
Command Center tiles; admin "run now" through the Jobs API.

**Phase 3.** AWS collector through a UC service credential (Bedrock,
SageMaker); AWS cost by intake tag; MLflow evaluation linkage
(AIC-11/12); deprecation alerts.

**Phase 4.** `ai_external_findings` landing contract for external evidence
pipelines; Snowflake, SaaS, and Palantir usage federation.

Phase 1 must not require schema rewrites for these: `source_system` is
open-ended, the field-map loader is shared, finding rules and controls are
registries, and event types are reserved now (section 14).

## 12. Configuration

Bundle variables → packaged `app.yaml` env (via `prepare_bundle.py --target`)
→ `atlas/config.py`. Values come from `BUNDLE_VAR_*`, never committed
workspace-specific values (see `AGENTS.md`).

| Bundle variable | Env var | Default |
|---|---|---|
| `ai_features_enabled` | `GOVAT_AI_FEATURES_ENABLED` | `false` |
| `ai_intake_tag_key` | `GOVAT_AI_INTAKE_TAG_KEY` | `edw_intake_id` (code name: `intake_tag_key`) |
| `ai_tier_tag_key` | `GOVAT_AI_TIER_TAG_KEY` | `ai_risk_tier` |
| `ai_catalog_allowlist` | `GOVAT_AI_CATALOG_ALLOWLIST` | empty (use `discovery_catalogs`) |
| `ai_tool_schema_allowlist` | `GOVAT_AI_TOOL_SCHEMA_ALLOWLIST` | empty |
| `ai_collector_sp` | (job `run_as` only) | empty |
| `ai_intake_grace_days` | `GOVAT_AI_INTAKE_GRACE_DAYS` | `30` **[Proposed]** |

Job resource `atlas_ai_collect_and_reconcile`: task `collect_databricks`, then
`reconcile`; `run_as` the collector service principal when set; schedule
paused in dev; serverless compute with an environment pinning
`databricks-sdk==0.95.0` (confirm in V9). Tasks run the entry scripts from the
bundle's synced files and need the warehouse ID and governance catalog and
schema as parameters.

## 13. Testing and verification

- Unit: no network. SDK adapters are tested with real SDK dataclass
  instances. Table-driven tests for every match rule, threshold boundary,
  finding type, control (including unknown), idempotency, auto-resolve,
  suppression persistence, and confirmation-to-M2.
- Redaction: adversarial fixtures (nesting, lists, unexpected fields,
  key-shaped values, headers); assert no credential-shaped value survives.
- API: contract tests, role gates, malformed IDs, degraded-not-empty,
  audit fail-closed on every PATCH and POST; regenerate the OpenAPI snapshot.
- Frontend: Vitest for loading, empty-but-observed, degraded, and
  unavailable states; action flows; role-based hiding.
- Live: the `CLAUDE.md` protocol, including independent subagent sign-off.

## 14. Event types

Reserved now; Phase 1 emits the first seven.

| Event type | Emitted when |
|---|---|
| `ai.intake.ingested` | Intake row committed |
| `ai.registry.state_changed` | AI registry `reconciliation_state` changes |
| `ai.finding.opened` | New finding, or resolved finding reopens |
| `ai.finding.updated` | Finding evidence or steward fields change |
| `ai.finding.resolved` | Steward or system resolution |
| `ai.finding.match_confirmed` | Steward confirm-match |
| `ai.controls.posture_changed` | Asset posture band changes |
| `ai.observation.appended` | One per collector append batch (not per row) |
| `ai.findings.merged` | One per reconciliation MERGE batch (keeps last_seen updates audited) |
| `ai.registry.relationship_upserted` | `serves` / `declares` relationship written |
| `ai.controls.results_recorded` | Control results written for a run |
| `ai.run.started`, `ai.run.updated`, `ai.run.finished` | Reconciliation run lifecycle |
| `ai.usage.aggregated` | Reserved, Phase 2 |
| `ai.mcp_review.updated` | Reserved, Phase 2 |
| `ai.writeback.sent` | Reserved, Phase 2 ServiceNow |

System actors use the collector service principal identity with
`source='system'`.

## 15. Phase 0 verification items

| # | Question | Where | If unavailable |
|---|---|---|---|
| V1 | List registered models and versions with aliases; read governed tags | `service/catalog.py`; entity tag assignment API; `system.information_schema` tag views | Endpoint tags plus steward confirmation |
| V2 | Served entity fields for external models; endpoint tags | `service/serving.py` | **Stop.** Must exist |
| V3 | Gateway config fields | `service/serving.py` AI gateway classes | Controls report unknown |
| V4 | Connection type and options; MCP identifiable? | `ConnectionInfo`, `ConnectionType` | Name convention plus allowlist |
| V5 | Apps list fields for agent and MCP detection | `service/apps.py` | Skip apps in Phase 1 |
| V6 | Newer AI asset registry API (agents, MCP as securables) | search SDK for agent, mcp, ai_asset | Probe stub reporting unavailable |
| V7 | Functions listing for tool schemas | `functions` API | `information_schema.routines` |
| V8 | Hard-coded entity kinds beyond `SUPPORTED_ENTITY_KINDS` | grep backend and frontend | Plan the changes |
| V9 | Job declaration (compute, environment, run_as) | `databricks.yml`; bundle docs | Serverless job with a requirements environment |

## 16. Open decisions

| ID | Question | Recommendation |
|---|---|---|
| D1 | Synthetic observations for objects that can't be created in dev (10.1) | **Decided 2026-09-24:** real labeled sample objects only |
| D2 | `atlas/ai/store.py` mixin vs extending `atlas/store.py` | **Revised (Phase 1):** composition wrapper, so the Lakebase mirror runs |
| D3 | M3 scoring function and severity table (5.1, 5.3) | As proposed, then review with stewards |
| D4 | AIC definitions beyond the Phase 1 subset (6) | Treat as placeholders until Phase 2 scoping |
| D5 | Collector writes through the SQL warehouse (shared store) vs Spark | Warehouse, for shared escaping and audit code |
| D6 | Apps adapter in Phase 1 (V5 passed) | **Decided 2026-09-24:** skip; Phase 2 |
| D7 | Collector identity and grants | **Decided 2026-09-24:** dev runs as the deploying user (no `run_as`, no permission changes); staging/prod run as `ai_collector_sp`. No endpoint manage grants (they don't expose credentials, see AIC-09) |
