#!/usr/bin/env python3
"""Seed (or clean up) the AI governance sample scenario in the dev workspace.

Decision D1: only *real*, labeled sample objects, never fabricated
observation rows. Everything created carries a sample marker the collector
recognizes (endpoint tag ``atlas_sample_run_id`` or ``[atlas-sample:<run>]``
in the comment), and intake rows are written with ``provenance_class=sample``.
The scenario and its expected findings live in atlas/ai/sample.py
(verified by tests/test_ai_sample_scenario.py).

Creates (``--live``):
  - schema <catalog>.atlas_ai_samples
  - secret scope atlas-ai-sample with a placeholder (not a credential)
  - two external-model serving endpoints (no compute; never queried)
  - one HTTP connection flagged is_mcp_connection=true (placeholder host)
  - one UC SQL function (tool) tagged with an intake id
  - one registered model (no versions)
  - sample intake records in the governance schema

``--cleanup`` removes all of the above and purges sample rows from the AI
tables (audited). Without ``--live`` or ``--cleanup`` it prints the plan.

Usage (dev only):
  set -a; . ./.env.dev; set +a
  python scripts/seed_ai_sample_data.py --live
  python scripts/seed_ai_sample_data.py --cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atlas.ai import sample  # noqa: E402
from atlas.util import quote_ident, sql_literal  # noqa: E402


def _run_id() -> str:
    return f"ga-ai-sample-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:7]}"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Create the sample objects and intake rows.")
    mode.add_argument("--cleanup", action="store_true", help="Remove all sample objects and purge sample rows.")
    parser.add_argument("--profile", default=os.environ.get("ATLAS_PROFILE", "DEFAULT"))
    parser.add_argument("--catalog", default="main", help="Catalog for the sample schema (objects are created here).")
    parser.add_argument("--warehouse-id", default=os.environ.get("BUNDLE_VAR_warehouse_id") or os.environ.get("DATABRICKS_WAREHOUSE_ID") or "")
    parser.add_argument("--gov-catalog", default=os.environ.get("BUNDLE_VAR_gov_catalog") or os.environ.get("GOVAT_CATALOG") or "")
    parser.add_argument("--gov-schema", default=os.environ.get("BUNDLE_VAR_gov_schema") or os.environ.get("GOVAT_SCHEMA") or "")
    parser.add_argument("--run-id", default="", help="Sample run id (default: generated). --cleanup purges every sample run.")
    return parser.parse_args(argv)


def _client(profile: str) -> Any:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(profile=profile)


def _sql(w: Any, warehouse_id: str, statement: str) -> None:
    response = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=statement, wait_timeout="50s")
    state = str(getattr(getattr(response, "status", None), "state", ""))
    if "SUCCEEDED" not in state:
        error = getattr(getattr(response, "status", None), "error", None)
        raise RuntimeError(f"SQL failed ({state}): {getattr(error, 'message', '')}")


def _ai_store(args: argparse.Namespace) -> Any:
    if not (args.warehouse_id and args.gov_catalog and args.gov_schema):
        raise SystemExit("--warehouse-id, --gov-catalog, and --gov-schema are required (or source .env.dev).")
    os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", args.profile)
    from atlas.ai.store import AiStore
    from atlas.store import GovernanceStore
    from atlas.uc import UCSQLClient

    store = GovernanceStore(uc=UCSQLClient(warehouse_id=args.warehouse_id), catalog=args.gov_catalog, schema=args.gov_schema)
    store.ensure_tables()
    return AiStore(store)


def plan(args: argparse.Namespace, run_id: str) -> Dict[str, Any]:
    fq_schema = f"{args.catalog}.{sample.SCHEMA}"
    return {
        "runId": run_id,
        "schema": fq_schema,
        "secretScope": sample.SECRET_SCOPE,
        "endpoints": [e.name for e in sample.SCENARIO.endpoints],
        "mcpConnection": sample.SCENARIO.mcp_connection,
        "functionTool": f"{fq_schema}.{sample.SCENARIO.function_tool}",
        "registeredModel": f"{fq_schema}.{sample.SCENARIO.registered_model}",
        "intakes": [i.intake_id for i in sample.SCENARIO.intakes],
        "expectedFindings": sorted(f"{t}:{i or '-'}" for t, i in sample.EXPECTED_FINDINGS),
        "governanceSchema": f"{args.gov_catalog}.{args.gov_schema}",
        "notCreated": "Databricks-hosted serving endpoint (would start paid compute; observed organically in dev).",
    }


def seed(args: argparse.Namespace, run_id: str) -> Dict[str, Any]:
    from databricks.sdk.service import catalog as uc_catalog
    from databricks.sdk.service import serving

    w = _client(args.profile)
    owner = w.current_user.me().user_name
    created: Dict[str, Any] = {"runId": run_id, "owner": owner, "steps": []}
    fq = f"{quote_ident(args.catalog)}.{quote_ident(sample.SCHEMA)}"

    _sql(w, args.warehouse_id, f"CREATE SCHEMA IF NOT EXISTS {fq} COMMENT {sql_literal(sample.sample_comment(run_id, 'AI governance sample objects'))}")
    created["steps"].append("schema")

    if sample.SECRET_SCOPE not in {s.name for s in w.secrets.list_scopes()}:
        w.secrets.create_scope(scope=sample.SECRET_SCOPE)
    for provider in ("anthropic", "openai"):
        w.secrets.put_secret(scope=sample.SECRET_SCOPE, key=provider, string_value=sample.PLACEHOLDER_SECRET_VALUE)
    created["steps"].append("secret-scope (placeholder values)")

    for ep in sample.SCENARIO.endpoints:
        ref = f"{{{{secrets/{sample.SECRET_SCOPE}/{ep.provider}}}}}"
        provider_config = (
            {"anthropic_config": serving.AnthropicConfig(anthropic_api_key=ref)}
            if ep.provider == "anthropic"
            else {"openai_config": serving.OpenAiConfig(openai_api_key=ref)}
        )
        external = serving.ExternalModel(
            provider=serving.ExternalModelProvider(ep.provider), name=ep.model, task="llm/v1/chat", **provider_config
        )
        w.serving_endpoints.create(
            name=ep.name,
            config=serving.EndpointCoreConfigInput(served_entities=[serving.ServedEntityInput(name="model", external_model=external)]),
            tags=[
                serving.EndpointTag(key=sample.INTAKE_TAG_KEY, value=ep.intake_id),
                serving.EndpointTag(key=sample.TIER_TAG_KEY, value=ep.tier),
                serving.EndpointTag(key="atlas_sample_run_id", value=run_id),
            ],
            ai_gateway=serving.AiGatewayConfig(usage_tracking_config=serving.AiGatewayUsageTrackingConfig(enabled=True))
            if ep.usage_tracking
            else None,
        )
        created["steps"].append(f"endpoint {ep.name}")

    w.connections.create(
        name=sample.SCENARIO.mcp_connection,
        connection_type=uc_catalog.ConnectionType.HTTP,
        options={
            "host": "https://mcp.example.invalid",
            "port": "443",
            "base_path": "/mcp",
            "bearer_token": "not-a-real-token-atlas-sample",
            "is_mcp_connection": "true",
        },
        comment=sample.sample_comment(run_id, "Sample MCP server connection"),
    )
    created["steps"].append(f"connection {sample.SCENARIO.mcp_connection}")

    fn = f"{fq}.{quote_ident(sample.SCENARIO.function_tool)}"
    _sql(
        w,
        args.warehouse_id,
        f"CREATE OR REPLACE FUNCTION {fn}(claim_type STRING) RETURNS STRING "
        f"COMMENT {sql_literal(sample.sample_comment(run_id, 'Sample AI tool: claim policy lookup'))} "
        "RETURN concat('policy:', claim_type)",
    )
    tags = f"({sql_literal(sample.INTAKE_TAG_KEY)} = {sql_literal(sample.SCENARIO.function_intake_id)}, {sql_literal(sample.TIER_TAG_KEY)} = 'low')"
    try:
        _sql(w, args.warehouse_id, f"ALTER FUNCTION {fn} SET TAGS {tags}")
    except RuntimeError:
        # Older SQL surfaces only accept the SET TAG ON form.
        for key, value in ((sample.INTAKE_TAG_KEY, sample.SCENARIO.function_intake_id), (sample.TIER_TAG_KEY, "low")):
            _sql(w, args.warehouse_id, f"SET TAG ON FUNCTION {fn} {quote_ident(key)} = {sql_literal(value)}")
    created["steps"].append(f"function {sample.SCENARIO.function_tool} (tagged {sample.SCENARIO.function_intake_id})")

    w.registered_models.create(
        catalog_name=args.catalog,
        schema_name=sample.SCHEMA,
        name=sample.SCENARIO.registered_model,
        comment=sample.sample_comment(run_id, "Sample registered model with no intake"),
    )
    created["steps"].append(f"registered model {sample.SCENARIO.registered_model}")

    from atlas.ai.intake import load_field_map, map_row

    ai = _ai_store(args)
    records = []
    field_map = load_field_map()
    for index, row in enumerate(sample.intake_rows(owner), start=2):
        raw = {
            "intake_id": row["intake_id"], "title": row["title"], "state": row["state"], "owner": owner,
            "provider": row["provider"] or "", "model_family": row["model_family"] or "", "risk_tier": row["risk_tier"] or "",
            "platform": row["platform"], "approved_at": row["approved_at"].strftime("%Y-%m-%d") if row["approved_at"] else "",
        }
        result = map_row(raw, field_map, row_number=index, ingest_run_id=run_id, provenance_class="sample", sample_run_id=run_id)
        if not result.valid:
            raise RuntimeError(f"sample intake {row['intake_id']} invalid: {result.errors}")
        records.append(result.record)
    created["intakes"] = ai.upsert_intake_records(records, actor_email=owner, actor_role="system", source="system")
    created["steps"].append("intake records (provenance_class=sample)")
    return created


def cleanup(args: argparse.Namespace) -> Dict[str, Any]:
    w = _client(args.profile)
    actor = w.current_user.me().user_name
    report: Dict[str, Any] = {"removed": [], "errors": []}

    def attempt(label: str, fn) -> None:
        try:
            fn()
            report["removed"].append(label)
        except Exception as exc:  # noqa: BLE001 - keep cleaning; report what failed
            if "NOT_FOUND" in str(exc).upper() or "DOES NOT EXIST" in str(exc).upper():
                return
            report["errors"].append(f"{label}: {type(exc).__name__}: {str(exc).split(' Config:')[0][:200]}")

    for endpoint in w.serving_endpoints.list():
        if any(t.key == "atlas_sample_run_id" for t in (endpoint.tags or [])):
            attempt(f"endpoint {endpoint.name}", lambda name=endpoint.name: w.serving_endpoints.delete(name))
    attempt(f"connection {sample.SCENARIO.mcp_connection}", lambda: w.connections.delete(sample.SCENARIO.mcp_connection))
    attempt(
        f"registered model {sample.SCENARIO.registered_model}",
        lambda: w.registered_models.delete(f"{args.catalog}.{sample.SCHEMA}.{sample.SCENARIO.registered_model}"),
    )
    if args.warehouse_id:
        attempt(
            f"schema {args.catalog}.{sample.SCHEMA}",
            lambda: _sql(w, args.warehouse_id, f"DROP SCHEMA IF EXISTS {quote_ident(args.catalog)}.{quote_ident(sample.SCHEMA)} CASCADE"),
        )
    attempt(f"secret scope {sample.SECRET_SCOPE}", lambda: w.secrets.delete_scope(sample.SECRET_SCOPE))

    ai = _ai_store(args)
    frame = ai.uc.query_df(
        f"SELECT DISTINCT sample_run_id FROM {ai._fq('intake_records')} WHERE provenance_class = 'sample' "
        f"UNION SELECT DISTINCT sample_run_id FROM {ai._fq('ai_asset_observations')} WHERE provenance_class = 'sample'"
    )
    runs = sorted({str(r) for r in (frame["sample_run_id"].tolist() if frame is not None and not frame.empty else []) if r})
    report["purged"] = {run: ai.purge_sample(run, actor_email=actor) for run in runs}
    return report


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or _run_id()
    if args.cleanup:
        print(json.dumps(cleanup(args), indent=2, default=str))
        return 0
    if not args.live:
        print(json.dumps({"mode": "plan (pass --live to create)", **plan(args, run_id)}, indent=2))
        return 0
    print(json.dumps(seed(args, run_id), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
