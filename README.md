# Axiom

Axiom is a Databricks-native metadata workspace built on Unity Catalog.
The product goal is Axiom branding with OpenMetadata-class workflow depth
across discovery, entity detail, lineage, governance, tasks, and quality.

The authoritative reconstruction spec lives in
[docs/RECONSTRUCTION_PLAN.md](docs/RECONSTRUCTION_PLAN.md).

## Supported Runtime

The only supported app runtime path is:

```text
app.yaml -> run_app.py -> runtime_app.py -> frontend/dist generated at package time
```

`runtime_app.py` is the single backend runtime module behind the Axiom
launcher.

There is no legacy Streamlit mode and no OpenMetadata bridge in the supported product.

## Product Direction

- Prioritize `Discovery`, `Lineage`, and `Governance`
- Stay asset-centric and search-first
- Match OpenMetadata-class workflow completeness and enterprise polish without cloning its branding
- Prefer truthful live metadata and audited control-plane state over synthetic UI affordances
- Preserve portability and low-friction deployment across Databricks workspaces

## Architecture

```text
Databricks App
  -> run_app.py
  -> backend runtime in runtime_app.py
  -> axiom/uc.py (internal compatibility package)
  -> axiom/store.py
  -> axiom/services/*
  -> React frontend built to frontend/dist
```

Axiom reads live Unity Catalog and Databricks system metadata directly and
stores governance workflow state in Delta tables inside the configured governance schema.

## Local Development

### Backend prerequisites

- Python 3.11+
- dependencies from `requirements.txt`

### Frontend prerequisites

- Node 20+
- npm

### Run locally

```bash
pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python run_app.py
```

The launcher requires a built frontend bundle at `frontend/dist/index.html`.

## Deployment

The repo is deployed as a Databricks App through Databricks Asset Bundles.

```bash
databricks auth login --host https://<workspace>.cloud.databricks.com
python scripts/prepare_bundle.py \
  --output /tmp/axiom_bundle \
  --target dev \
  --profile DEFAULT \
  --var="warehouse_id=<warehouse-id>"
cd /tmp/axiom_bundle
databricks bundle deploy --profile DEFAULT -t dev --var="warehouse_id=<warehouse-id>"
USER_NAME=$(databricks current-user me --profile DEFAULT -o json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')
cat > /tmp/axiom-app-deploy.json <<JSON
{
  "source_code_path": "/Workspace/Users/${USER_NAME}/.bundle/axiom/dev/files",
  "mode": "SNAPSHOT"
}
JSON
databricks apps start axiom --profile DEFAULT --timeout 20m
databricks apps deploy axiom \
  --profile DEFAULT \
  --json @/tmp/axiom-app-deploy.json \
  --timeout 20m
```

`prepare_bundle.py --target <name>` calls `databricks bundle validate -o json
-t <name>` against the source repository, reads
`resources.apps.axiom.config.env` from the result, and writes the resolved
entries into `<output>/app.yaml`. This step is required because the
`databricks_app` Terraform resource exposes no `config`/`env` attribute, so
the env vars defined per target in `databricks.yml` would otherwise be
silently dropped at `databricks bundle deploy` time and the Databricks Apps
runtime would fall back to the conservative source defaults in `app.yaml`.
The Apps deploy JSON above intentionally omits `env_vars`: the
`AppDeployment` schema does not accept it, and env vars are read by the
runtime from the packaged `app.yaml`.

### Packaging contract

- `frontend/dist` is built in CI or a predeploy packaging step
- `frontend/dist/axiom-build-manifest.json` proves the bundle matches the current frontend source tree; the filename is retained as a frontend-build compatibility artifact
- `frontend/dist` is not source-controlled
- the Databricks bundle is deployed from a clean packaged directory that includes the built frontend output
- the runtime does not build frontend assets on startup

## Configuration

### Required

- `DATABRICKS_WAREHOUSE_ID`

### Runtime configuration

- `AXIOM_CATALOG`
- `AXIOM_SCHEMA`
- `AXIOM_ADMIN_EMAILS`

These are injected explicitly per deployment target from `databricks.yml`.
Source defaults remain neutral and must not encode personal emails or
production-only settings.

`app.yaml` is intentionally portable source config: it defaults to
`main.axiom`, no bootstrap admin, local Axiom AI fallback, and Lakebase disabled.
Real installs should override `AXIOM_CATALOG`, `AXIOM_SCHEMA`, and
`AXIOM_ADMIN_EMAILS` per workspace. Genie and Lakebase are optional resources:
leave `AXIOM_AI_PROVIDER=local` and `AXIOM_LAKEBASE_ENABLED=false` for a
minimal install, or bind a curated Genie space plus Lakebase branch/database in
the bundle target. No workspace-specific value is committed: every target reads
its values from `BUNDLE_VAR_<name>` environment variables. Copy `.env.example` to
`.env.<target>` (gitignored), fill it in, and `set -a; . ./.env.<target>; set +a`
before `prepare_bundle.py` / `bundle deploy`. The `dev` target also binds Genie,
model serving and Lakebase, so those variables are required there.

## Governance Tables

Axiom currently persists governance state in Delta tables under
`<AXIOM_CATALOG>.<AXIOM_SCHEMA>`.

- `user_roles`
- `glossary_terms`
- `glossary_term_reviewers`
- `glossary_term_versions`
- `data_owners`
- `change_requests`

Additional workflow, migration, lineage-override, and quality tables will be introduced
through versioned migrations rather than ad hoc schema drift.

## CI / CD Expectations

The deployment workflow is expected to:

- build and lint the frontend in a clean checkout
- run backend and migration checks
- assemble a clean bundle directory
- validate and deploy the bundle from that packaged directory

## License

Apache-2.0
