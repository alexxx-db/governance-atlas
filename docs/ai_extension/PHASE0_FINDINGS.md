# AI Governance Extension: Phase 0 Findings

Date: 2026-09-24. Branch: `feat/ai-governance`.

Environment:

- SDK verified: `databricks-sdk==0.95.0` (the app's pin), installed in a local
  `.venv` (gitignored). Source paths below are relative to
  `.venv/lib/python3.13/site-packages/databricks/sdk/service/`.
- Interpreter: Python 3.13.2 locally (Databricks Apps run 3.11; the SDK is pure
  Python, so class definitions don't differ by interpreter).
- Loose pins in `requirements.txt` resolved to `pandas==3.0.6`,
  `fastapi==0.141.1`, `uvicorn==0.53.0`, `psycopg==3.3.6`.
- Live checks: read-only calls against the dev workspace with profile
  `DEFAULT` (identity: the deploying user). Outputs below are counts and
  field shapes only; no config values or secrets were printed.

## Summary

No stop condition was hit:

- V2 passes.
- Baseline tests are green.
- The DESIGN.md corrections are field-level plus two scope notes (agents
  observable in Phase 1; model tags not observable). There is no architecture
  change.

Two items limit Phase 1 fidelity and are recorded as risks:

- Governed tags on registered models are not readable through any API
  (see V1).
- Provider credential fields are withheld for this caller, so AIC-09 will
  report `unknown` unless the collector principal can see more (see V2).

## V1 to V9

| # | Result | Evidence | Chosen approach |
|---|---|---|---|
| V1 | **Partial** | See the V1 notes below | Phase 1 fallback per the brief |
| V2 | **Pass** | See the V2 notes below | Discover via `list()`; call `get()` only for AIC-09 |
| V3 | **Pass** | See the V3 notes below | AIC-04 and AIC-06 read these fields |
| V4 | **Pass, better than expected** | See the V4 notes below | Classify MCP by `options.is_mcp_connection == "true"` |
| V5 | **Pass** | See the V5 notes below | **[Decision needed]** apps adapter scope in Phase 1 |
| V6 | **Unavailable** | See the V6 notes below | Probe stub that reports `unavailable` |
| V7 | **Pass** | See the V7 notes below | Use the functions API; tags from `routine_tags` |
| V8 | **Hard-coded kinds found** | See the V8 notes below | Additive changes |
| V9 | **Pass** | See the V9 notes below | Serverless job, as validated |

**V1: registered models, versions, aliases, tags.**

- `catalog.py:8492` `RegisteredModelInfo` has `aliases`, `owner`, and
  `full_name`.
- `catalog.py:6387` `ModelVersionInfo` has `aliases`, `run_id`, `source`,
  `status`, and `version`, and **no tags field**.
- `catalog.py:12154` the `EntityTagAssignmentsAPI.list` entity types are
  **catalogs, schemas, tables, columns, volumes only**.
- `system.information_schema` has `catalog_tags`, `schema_tags`, `table_tags`,
  `column_tags`, `volume_tags`, and `routine_tags`. There is **no model tag
  view**.
- Live: 159 registered models visible.
  - `list()` returns no aliases.
  - `get(full_name, include_aliases=True)` does: 25 readable, 4 with aliases,
    11 permission-denied (`USE CATALOG`).
- Chosen approach:
  - Read aliases via per-model `get(include_aliases=True)`, bounded by
    `ai_catalog_allowlist`.
  - A per-model permission failure makes that model's observation `degraded`
    with a reason.
  - Model tier and intake tags are **not observable**. Models match via
    serving endpoint tags (the M1 path through a `serves` edge), M2, or M3.
    AIC-03 on models returns `unknown`.

**V2: external model served entities and endpoint tags.**

- `serving.py:4477` `ServingEndpointsAPI.list()` returns `ServingEndpoint`
  (`serving.py:3389`: `ai_gateway`, `config`, `id`, `name`, `tags`, `task`).
- `serving.py:1252` the summary config has `served_entities`, typed
  `ServedEntitySpec` (`serving.py:2913`: `entity_name`, `entity_version`,
  `external_model`, `foundation_model`, `name`).
- `serving.py:1502` `ExternalModel` has `provider`, `name`, `task`, and
  per-provider `*_config` objects.
- The provider configs hold key **and `*_plaintext` fields**:
  - `serving.py:1948` `OpenAiConfig.openai_api_key_plaintext` and
    `microsoft_entra_client_secret_plaintext`;
  - `serving.py:503` `AnthropicConfig.anthropic_api_key_plaintext`.
- `serving.py:2718` `ServedEntityOutput.environment_vars` is present.
- Live:
  - 91 endpoints. Tasks: 56 `llm/v1/chat`, 24 none, 8 `agent/v1/responses`,
    3 `llm/v1/embeddings`.
  - 1 external served entity (provider Anthropic).
  - 26 endpoints carry tags.
  - `list()` omits provider config. `get()` returns `anthropic_config` with
    **all fields empty** for this caller.
- Chosen approach:
  - Discover everything through `list()`.
  - Call `get()` only to evaluate AIC-09.
  - AIC-09 is `unknown` when no credential field is observable; re-test with
    the collector service principal.

**V3: AI Gateway configuration.**

- `serving.py:68` `AiGatewayConfig` has `fallback_config`, `guardrails`,
  `inference_table_config`, `rate_limits`, and `usage_tracking_config`.
- `serving.py:379` `usage_tracking_config.enabled`.
- `serving.py:251` `inference_table_config.enabled`, `catalog_name`, and
  `schema_name`.
- `serving.py:305` rate limits; `serving.py:131` guardrail parameters (`pii`,
  `safety`, `invalid_keywords`, `valid_topics`).
- Live: 27 endpoints have `ai_gateway` in `list()`. 27 have usage tracking
  config, 25 have inference table config.
- AIC-04 and AIC-06 read these fields. An endpoint without an `ai_gateway`
  block evaluates `fail`, because the gateway feature is observable and absent.
  It is `unknown` only when the probe itself failed.

**V4: connections and MCP.**

- `catalog.py:1625` `ConnectionInfo` has `connection_type`, `options`,
  `owner`, `full_name`, and `url`.
- The `ConnectionType` enum has **no MCP value**.
- Live (raw REST): types `HTTP` 9, `MANAGED_POSTGRESQL` 7, `SQLSERVER` 2.
  - HTTP option keys include **`is_mcp_connection`**, with values `true` 3,
    `false` 4, and absent 2.
  - `MANAGED_POSTGRESQL` is **not in the 0.95 enum**, so the SDK deserializes it
    as `None`.
- Chosen approach:
  - Classify MCP servers by `connection_type == "HTTP"` and
    `options.is_mcp_connection == "true"`. No name convention is needed.
  - Read connection types from the raw string so newer types aren't lost.
  - Store only allowlisted option keys: `host`, `base_path`, `port`,
    `is_mcp_connection`, `auth_scheme`. **Never** `client_id`,
    `token_endpoint`, or other OAuth fields.

**V5: apps.**

- `apps.py:31` `App` has `resources`, `service_principal_client_id`,
  `effective_user_api_scopes`, and `app_status`.
- Live: 30 apps. Resource kinds: `sql_warehouse` 17, `serving_endpoint` 12,
  `secret` 9, `job` 7, `postgres` 5, `genie_space` 4, `database` 2,
  `experiment` 1.
- **[Decision needed]** Two options for Phase 1:
  - (a) Skip apps in Phase 1 (they aren't needed for the demo segments).
  - (b) Observe apps with a `serving_endpoint` resource only as `uses` edges
    to endpoints, with no new kind.
- Recommendation: (a). Defer to Phase 2 with agent apps.

**V6: AI asset registry API.**

- `agentbricks.py:194` `AgentBricksAPI` covers only custom LLM
  create/get/update/delete/optimize, with **no list**.
- `marketplace.py:49` `ASSET_TYPE_MCP` is a Marketplace listing type, not a
  governed registry.
- There is no agent or MCP securable API in 0.95.
- Chosen approach: a probe stub reporting `unavailable` ("no AI asset
  registry API in databricks-sdk 0.95").
- **Scope note:** agents *are* observable today. Serving endpoints with task
  `agent/v1/*` (8 live) become `agent` observations.

**V7: functions for tool schemas.**

- `catalog.py:4418` `FunctionInfo`; `catalog.py:12983`
  `FunctionsAPI.list(catalog_name, schema_name)`.
- Live: `main.default` has 1 function.
- Chosen approach: use the functions API over `ai_tool_schema_allowlist`.
  Tags come from `information_schema.routine_tags`; the fallback is
  `information_schema.routines`.

**V8: hard-coded entity kinds.**

- Backend:
  - `atlas/services/custom_properties.py:25`
    `SUPPORTED_ENTITY_KINDS = ("asset", "column", "glossary_term")`.
  - `atlas/api/catalog.py:284` requires an FQN only for `asset` and `column`,
    so AI kinds don't hit it.
- Frontend:
  - `components/system/refs.js`: `hrefForRef` and `defaultRefLabel` switch on
    `asset`, `column`, `term`, `cde`, `owner`, `request`, `event`, `quality`,
    `domain`, `catalog`, `lineage`, each with a `default`.
  - `components/system/icons.jsx` `KIND_ICONS`: `asset`, `column`, `term`.
- Chosen approach, all additive:
  - Extend `SUPPORTED_ENTITY_KINDS`.
  - Add AI kinds to `refs.js`, linking to `/ai/assets/{id}`.
  - Add AI kinds to `KIND_ICONS`.
  - `components/system/` is shared: changes are additive only, and the
    existing tests must stay green.

**V9: job declaration.**

- The bundle schema (CLI v1.14.1) supports:
  - `jobs.JobEnvironment` (`environment_key`, `spec`);
  - `compute.Environment` (`environment_version`, `dependencies`);
  - `jobs.SparkPythonTask` (`python_file`, `parameters`);
  - `jobs.JobRunAs` (`service_principal_name`).
- Validated a throwaway bundle copy in the scratchpad (repo untouched), with
  `bundle validate -t dev`:
  - two tasks `collect_databricks` → `reconcile`;
  - `environment_version: "2"`, `databricks-sdk==0.95.0`;
  - a paused schedule.
  - Development mode prefixed the job name `[dev alex_barreto]`.
- Chosen approach:
  - Serverless job with that environment.
  - Tasks run the entry scripts from the bundle's synced files
    (`${workspace.file_path}/atlas/ai/jobs/*.py`).
  - Tasks receive the warehouse ID and governance catalog and schema as
    parameters.
  - `run_as` is used only when `ai_collector_sp` is set.

## Baseline tests

| Suite | Command | Result |
|---|---|---|
| Backend (CI runner) | `.venv/bin/python -m unittest discover -s tests` | 742 run, **OK** |
| Backend | `.venv/bin/python -m pytest -q tests` | **751 passed**, 1 warning (Starlette `TestClient` deprecation) |
| Frontend | `npm run test` (vitest) | 73 files, **706 passed** |

Nothing is failing in areas Phase 1 touches.

## Reused-component risks

From the reopened ledgers:

- `docs/northstar_gap_analysis/full_page_audit.md`: 90 unchecked items.
- `functional_control_audit.md`: 16.
- `reopened_2026_05_02_visual_functional_audit.md`: 127.

| Component or pattern | Known open issue | Impact on `/ai` |
|---|---|---|
| `Drawer` (peek/selected) | full_page_audit:227-229: header density, tab spacing, and sticky actions differ from the reference; an AI panel can obscure drawer content | Findings evidence drawer inherits the layout; keep the AI dock closed on `/ai` or test overlap |
| Degraded banner (`StatusBanner`) | full_page_audit:230: degraded state renders a large pale banner that breaks the dark palette | The source-unavailable banner is a core Phase 1 requirement; must use `--ga-*` tokens; check on the live app |
| `DataTable` | full_page_audit:320: columns truncate at 1440x900 and 1280x720 (asset names, owners) | AI inventory has long FQNs and endpoint names; check truncation with titles |
| Row actions | functional_control_audit:390: row actions can end in local status text instead of a real resource or a disabled state | Finding actions must call real APIs or be visibly disabled with a reason |
| Mutation controls | functional_control_audit:286: governance mutations lack disposable live proof | Phase 1 walk-through must exercise suppress, confirm, and resolve on sample findings only |
| Asset 360 cards | reopened audit:176-180: trend, domain, and coverage cards render unavailable states with provenance gaps | AI Asset 360 must render provenance chips per datum, not reuse those cards as-is |

Not fixed (out of scope), noted only.

## Other discrepancies found

- `IMPLEMENTATION_STATUS.md` names `full_page_audit.md` as the active source
  of truth; it exists under `docs/northstar_gap_analysis/`.
- `AGENTS.md` is gitignored on purpose (`.gitignore` `AGENT*`); it stays a local operating contract.
- The frontend fail-closed filter (`nonAuthoritativeEvidence.js`) rejects
  source values `seed`, `mock`, `fixture`, `prototype`, and more. AI sample
  data must avoid them (DESIGN.md 10.1, decision D1 still open).

## DESIGN.md corrections

Applied in `DESIGN.md` under "Verified against SDK 0.95 (2026-09-24)":

1. The collector discovers endpoints with `list()`. `get()` is used only for
   AIC-09, because `list()` omits provider configs.
2. Agents are observable in Phase 1 from serving endpoints with task
   `agent/v1/*` (`entity_kind='agent'`), not deferred to Phase 2.
3. Registered model and model version tags are not observable. AIC-03 on
   models is `unknown`, and model matching relies on endpoint tags via
   `serves`, M2, or M3.
4. MCP classification uses `options.is_mcp_connection == "true"` on `HTTP`
   connections.
5. The redaction allowlist must explicitly exclude every `*_plaintext`,
   `*_api_key`, `*_client_secret`, and `environment_vars` field. AIC-09 is
   `unknown` when credential fields are withheld by the API.
6. Connection types are read as raw strings (for example
   `MANAGED_POSTGRESQL`, which is absent from the 0.95 enum).

## Decisions (resolved 2026-09-24)

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Synthetic observations vs real labeled sample objects (DESIGN 10.1) | **Yes:** real sample objects only |
| D6 | Apps adapter in Phase 1 (V5) | **Yes:** skip; Phase 2 |
| D7 | Collector principal grants: `USE CATALOG`/`USE SCHEMA` on allowlisted catalogs and `CAN_MANAGE` (or equivalent) on endpoints, to make AIC-09 observable | **Yes:** grant in dev, record in `RUNBOOK.md` |

## D7 follow-up (2026-09-24)

- **Endpoint manage rights would not make AIC-09 observable.** For the one
  external model endpoint, the verifying caller holds `CAN_MANAGE`
  (`ServingEndpointDetailed.permission_level`), and the raw REST response
  (`GET /api/2.0/serving-endpoints/<name>`) returns
  `external_model.anthropic_config` as `{}`. The serving API withholds
  credential fields from every caller.
- AIC-09 is therefore structurally `unknown` from the serving API. Its
  evidence reads: "credential configuration is not exposed by the serving API".
- No endpoint `CAN_MANAGE` grants will be made; they would add privilege for
  no signal.
- Catalog access: service principals are members of `account users`, which
  already hold `USE_CATALOG`/`USE_SCHEMA`/`SELECT` on `main`, where the
  sample models live. The verifying user cannot grant on other catalogs (for
  example `demos`, `datapact`); models there show as `degraded`.
- **Collector identity in dev (decided 2026-09-24):** no `run_as` in dev. The
  job runs as the deploying user, sees all endpoints, and changes no
  permissions. Staging and prod run as a dedicated service principal through
  `ai_collector_sp` (deployed only from CI). Because a dev run is attributed to
  a person, dev collector audit rows carry that user as actor with
  `source='system'`.

## Phase 1 corrections from live job runs (2026-09-24)

The first live collector runs surfaced two facts the Phase 0 probes missed:

- **V1:** `registered_models.list(catalog_name=...)` without `schema_name` is
  rejected ("Cannot have an empty schema if the catalog is set"). The
  collector now enumerates `schemas.list(catalog)` and lists models per
  schema. Phase 0 only listed models with no arguments.
- **V7:** `information_schema.routine_tags` is listed in the schema, but a
  query is rejected ("ROUTINE_TAGS is not supported by Information Schema"),
  at both `system.` and catalog level. **UC function tags are not
  observable.** Tools carry no tags, AIC-03 reports `unknown` for them, and
  tools match by M3 or steward confirmation. The sample scenario's tool
  intake is titled after the function so it demonstrates an M3 match.

Operational fixes from the same runs:

- Serverless tasks run under IPython, which reports `SystemExit(0)` and a
  missing `__file__` as failures. The entry points now take `--repo-root`
  and return normally on success.
- A retried task reused the run ID and appended duplicate observations. Run
  starts are now a MERGE, the collector clears the run's observations before
  appending (audited), and tasks set `max_retries: 0`.
