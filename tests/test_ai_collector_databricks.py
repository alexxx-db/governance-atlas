"""dbx_ai_collector adapters, built from real databricks-sdk 0.95 dataclasses
(no network). A renamed SDK field fails here, not in production."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

from databricks.sdk.service import catalog, serving

from atlas.ai import models
from atlas.ai.collectors import databricks as dbx

SECRET_VALUE = "sk-live-0123456789abcdefghijkl"


def _ctx() -> models.RunContext:
    return models.RunContext(
        run_id="run-1",
        collector=dbx.COLLECTOR,
        collector_version=dbx.COLLECTOR_VERSION,
        source_system=dbx.SOURCE_SYSTEM,
        started_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )


def _external_endpoint(**overrides: Any) -> serving.ServingEndpoint:
    base = dict(
        id="ep-ext-1",
        name="chat-claude",
        task="llm/v1/chat",
        creator="owner@example.com",
        tags=[serving.EndpointTag(key="edw_intake_id", value="INT-100"), serving.EndpointTag(key="ai_risk_tier", value="high")],
        config=serving.EndpointCoreConfigSummary(
            served_entities=[
                serving.ServedEntitySpec(
                    name="claude",
                    external_model=serving.ExternalModel(
                        provider=serving.ExternalModelProvider.ANTHROPIC, name="claude-sonnet", task="llm/v1/chat"
                    ),
                )
            ]
        ),
        ai_gateway=serving.AiGatewayConfig(
            usage_tracking_config=serving.AiGatewayUsageTrackingConfig(enabled=True),
            inference_table_config=serving.AiGatewayInferenceTableConfig(enabled=False),
            rate_limits=[
                serving.AiGatewayRateLimit(
                    calls=100, key=serving.AiGatewayRateLimitKey.USER, renewal_period=serving.AiGatewayRateLimitRenewalPeriod.MINUTE
                )
            ],
        ),
    )
    base.update(overrides)
    return serving.ServingEndpoint(**base)


def _detail(credential: Dict[str, Any]) -> serving.ServingEndpointDetailed:
    return serving.ServingEndpointDetailed(
        name="chat-claude",
        config=serving.EndpointCoreConfigOutput(
            served_entities=[
                serving.ServedEntityOutput(
                    name="claude",
                    environment_vars={"OPENAI_API_KEY": SECRET_VALUE},
                    external_model=serving.ExternalModel(
                        provider=serving.ExternalModelProvider.ANTHROPIC,
                        name="claude-sonnet",
                        task="llm/v1/chat",
                        anthropic_config=serving.AnthropicConfig(**credential),
                    ),
                )
            ]
        ),
    )


class FakeWorkspace:
    def __init__(
        self,
        endpoints: List[Any] | None = None,
        detail: Any = None,
        models_by_catalog: Dict[str | None, List[Any]] | None = None,
        model_detail: Dict[str, Any] | None = None,
        versions: Dict[str, List[Any]] | None = None,
        connections: List[Dict[str, Any]] | None = None,
        functions: Dict[tuple, List[Any]] | None = None,
        fail_endpoints: bool = False,
    ) -> None:
        self.calls: List[tuple] = []
        ws = self

        class _Endpoints:
            def list(self):
                if fail_endpoints:
                    raise PermissionError("403 PERMISSION_DENIED. Config: host=https://dbc-9.cloud.databricks.com, client_id=zzz")
                return list(endpoints or [])

            def get(self, name):
                ws.calls.append(("endpoint.get", name))
                return detail

        class _Models:
            def list(self, catalog_name=None):
                ws.calls.append(("models.list", catalog_name))
                return list((models_by_catalog or {}).get(catalog_name, []))

            def get(self, full_name, include_aliases=None):
                value = (model_detail or {}).get(full_name)
                if isinstance(value, Exception):
                    raise value
                return value

        class _Versions:
            def list(self, full_name, max_results=None):
                return list((versions or {}).get(full_name, []))

        class _Functions:
            def list(self, catalog_name, schema_name):
                ws.calls.append(("functions.list", catalog_name, schema_name))
                return list((functions or {}).get((catalog_name, schema_name), []))

        class _Api:
            def do(self, method, path, query=None):
                return {"connections": list(connections or [])}

        self.serving_endpoints = _Endpoints()
        self.registered_models = _Models()
        self.model_versions = _Versions()
        self.functions = _Functions()
        self.api_client = _Api()


class ServingEndpointAdapterTests(unittest.TestCase):
    def test_external_model_endpoint(self) -> None:
        w = FakeWorkspace(endpoints=[_external_endpoint()], detail=_detail({"anthropic_api_key": "{{secrets/ai/anthropic}}"}))
        obs = dbx.collect_serving_endpoints(w, _ctx())
        by_kind = {o.entity_kind: o for o in obs}
        endpoint, external = by_kind[models.SERVING_ENDPOINT], by_kind[models.EXTERNAL_MODEL]
        self.assertEqual(endpoint.source_entity_id, "ep-ext-1")
        self.assertEqual(endpoint.platform, "external")
        self.assertEqual(endpoint.tags["edw_intake_id"], "INT-100")
        self.assertEqual(endpoint.relationships[0], {"kind": "serves", "target_kind": "external_model", "target_source_entity_id": "ep-ext-1/claude"})
        self.assertEqual(endpoint.config["ai_gateway"]["usage_tracking_config"], {"enabled": True})
        self.assertEqual(endpoint.config["ai_gateway"]["rate_limits"], [{"calls": 100, "renewal_period": "minute", "scope": "user"}])
        self.assertEqual(external.source_entity_id, "ep-ext-1/claude")
        self.assertEqual((external.provider, external.model_family), ("anthropic", "claude-sonnet"))
        self.assertEqual(external.parent_source_entity_id, "ep-ext-1")
        self.assertEqual(external.config["credentials"], {"observable": True, "secret_refs": [{"field": "anthropic_api_key", "secret_ref": "ai/anthropic"}], "plaintext_fields": []})
        blob = json.dumps([o.config for o in obs])
        self.assertNotIn(SECRET_VALUE, blob)
        self.assertNotIn("environment_vars", blob)

    def test_withheld_credentials_are_not_observable(self) -> None:
        # The dev workspace returns anthropic_config with every field empty (PHASE0 D7).
        w = FakeWorkspace(endpoints=[_external_endpoint()], detail=_detail({}))
        external = [o for o in dbx.collect_serving_endpoints(w, _ctx()) if o.entity_kind == models.EXTERNAL_MODEL][0]
        self.assertFalse(external.config["credentials"]["observable"])

    def test_plaintext_key_recorded_by_name_only(self) -> None:
        w = FakeWorkspace(endpoints=[_external_endpoint()], detail=_detail({"anthropic_api_key_plaintext": SECRET_VALUE}))
        external = [o for o in dbx.collect_serving_endpoints(w, _ctx()) if o.entity_kind == models.EXTERNAL_MODEL][0]
        self.assertEqual(external.config["credentials"]["plaintext_fields"], ["anthropic_api_key_plaintext"])
        self.assertNotIn(SECRET_VALUE, json.dumps(external.config))

    def test_endpoint_without_gateway_config(self) -> None:
        plain = serving.ServingEndpoint(
            id="ep-2", name="fm", task="llm/v1/chat",
            config=serving.EndpointCoreConfigSummary(
                served_entities=[serving.ServedEntitySpec(name="fm", entity_name="main.ml.clf", entity_version="3")]
            ),
        )
        obs = dbx.collect_serving_endpoints(FakeWorkspace(endpoints=[plain]), _ctx())
        self.assertEqual(len(obs), 1)
        self.assertNotIn("ai_gateway", obs[0].config)
        self.assertEqual(obs[0].platform, "databricks")
        self.assertEqual(obs[0].relationships[0]["target_source_entity_id"], "main.ml.clf@3")

    def test_agent_endpoint_kind(self) -> None:
        agent = serving.ServingEndpoint(id="ep-3", name="support-agent", task="agent/v1/responses")
        obs = dbx.collect_serving_endpoints(FakeWorkspace(endpoints=[agent]), _ctx())
        self.assertEqual(obs[0].entity_kind, models.AGENT)

    def test_sample_marker_from_tag(self) -> None:
        tagged = _external_endpoint(tags=[serving.EndpointTag(key=dbx.SAMPLE_TAG_KEY, value="ga-ai-sample-1")])
        obs = dbx.collect_serving_endpoints(FakeWorkspace(endpoints=[tagged], detail=_detail({})), _ctx())
        self.assertTrue(all(o.provenance_class == "sample" and o.sample_run_id == "ga-ai-sample-1" for o in obs))

    def test_content_hash_stable_across_runs(self) -> None:
        w = FakeWorkspace(endpoints=[_external_endpoint()], detail=_detail({}))
        first = {o.source_entity_id: o.content_hash for o in dbx.collect_serving_endpoints(w, _ctx())}
        second_ctx = models.RunContext(**{**_ctx().__dict__, "run_id": "run-2"})
        second = {o.source_entity_id: o.content_hash for o in dbx.collect_serving_endpoints(w, second_ctx)}
        self.assertEqual(first, second)


class OtherAdapterTests(unittest.TestCase):
    def test_models_respect_catalog_allowlist_and_aliases(self) -> None:
        listed = catalog.RegisteredModelInfo(full_name="main.ml.fraud", owner="ds@example.com")
        detail = catalog.RegisteredModelInfo(
            full_name="main.ml.fraud", owner="ds@example.com", comment="fraud model",
            aliases=[catalog.RegisteredModelAlias(alias_name="champion", version_num=2)],
        )
        versions = [catalog.ModelVersionInfo(version=1), catalog.ModelVersionInfo(version=2, run_id="r2")]
        w = FakeWorkspace(
            models_by_catalog={"main": [listed], "other": [catalog.RegisteredModelInfo(full_name="other.x.y")]},
            model_detail={"main.ml.fraud": detail},
            versions={"main.ml.fraud": versions},
        )
        obs = dbx.collect_registered_models(w, _ctx(), catalogs=["main"])
        self.assertEqual([c for c in w.calls if c[0] == "models.list"], [("models.list", "main")])
        kinds = sorted((o.entity_kind, o.source_entity_id) for o in obs)
        self.assertEqual(kinds, [("ai_model", "main.ml.fraud"), ("ai_model_version", "main.ml.fraud@1"), ("ai_model_version", "main.ml.fraud@2")])
        v2 = next(o for o in obs if o.source_entity_id == "main.ml.fraud@2")
        self.assertEqual(v2.config["aliases"], [{"alias_name": "champion", "version_num": 2}])

    def test_model_permission_failure_degrades_with_partial(self) -> None:
        w = FakeWorkspace(
            models_by_catalog={None: [catalog.RegisteredModelInfo(full_name="a.b.ok"), catalog.RegisteredModelInfo(full_name="a.b.denied")]},
            model_detail={"a.b.ok": catalog.RegisteredModelInfo(full_name="a.b.ok"), "a.b.denied": PermissionError("no USE CATALOG")},
        )
        from atlas.ai.probes import probe

        result, value = probe("registered_models", lambda: dbx.collect_registered_models(w, _ctx(), catalogs=[]))
        self.assertEqual(result.state, "degraded")
        self.assertIn("1 model(s) unreadable", result.reason)
        self.assertEqual([o.source_entity_id for o in value], ["a.b.ok"])

    def test_only_http_connections_flagged_mcp(self) -> None:
        connections = [
            {"name": "mcp1", "connection_type": "HTTP", "options": {"is_mcp_connection": "true", "host": "mcp.example.com", "client_secret": SECRET_VALUE}, "comment": "[atlas-sample:ga-ai-1]"},
            {"name": "http_plain", "connection_type": "HTTP", "options": {"is_mcp_connection": "false"}},
            {"name": "pg", "connection_type": "MANAGED_POSTGRESQL", "options": {}},
        ]
        obs = dbx.collect_mcp_connections(FakeWorkspace(connections=connections), _ctx())
        self.assertEqual([o.source_entity_id for o in obs], ["mcp1"])
        self.assertEqual(obs[0].sample_run_id, "ga-ai-1")
        self.assertNotIn(SECRET_VALUE, json.dumps(obs[0].config))

    def test_functions_only_in_allowlisted_schemas(self) -> None:
        fn = catalog.FunctionInfo(full_name="main.tools.lookup", name="lookup", owner="a@b.c", routine_definition=f"'{SECRET_VALUE}'")
        w = FakeWorkspace(functions={("main", "tools"): [fn]})
        obs = dbx.collect_uc_function_tools(
            w, _ctx(), schemas=["main.tools", "bad-entry"], routine_tags=lambda c, s: {"lookup": {"ai_risk_tier": "low"}}
        )
        self.assertEqual([c for c in w.calls if c[0] == "functions.list"], [("functions.list", "main", "tools")])
        self.assertEqual(obs[0].tags, {"ai_risk_tier": "low"})
        self.assertNotIn(SECRET_VALUE, json.dumps(obs[0].config))


class CollectOrchestrationTests(unittest.TestCase):
    def test_probe_failure_isolated_and_reasons_redacted(self) -> None:
        w = FakeWorkspace(fail_endpoints=True, connections=[{"name": "m", "connection_type": "HTTP", "options": {"is_mcp_connection": "true"}}])
        observations, sources = dbx.collect(w, _ctx(), catalogs=[], tool_schemas=[])
        self.assertEqual(sources["serving_endpoints"].state, "unavailable")
        self.assertNotIn("client_id", sources["serving_endpoints"].reason)
        self.assertEqual(sources["mcp_connections"].state, "available")
        self.assertEqual(sources["uc_function_tools"].state, "unavailable")
        self.assertIn("no tool schemas configured", sources["uc_function_tools"].reason.lower())
        self.assertEqual(sources["ai_asset_registry"].state, "unavailable")
        self.assertEqual([o.entity_kind for o in observations], [models.MCP_SERVER])


if __name__ == "__main__":
    unittest.main()
