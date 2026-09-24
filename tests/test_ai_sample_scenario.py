"""The seed scenario produces exactly its intended findings: built from the
observations the collector would emit for the seeded objects, run through the
pure reconciliation code. Nothing is created here."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from atlas.ai import models, reconcile, sample

OWNER = "seed-owner@example.com"
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ALL = {s: {"state": "available"} for s in ("serving_endpoints", "registered_models", "mcp_connections", "uc_function_tools")}


def _obs(kind, sid, **kw):
    row = {"entity_kind": kind, "source_system": "databricks", "source_entity_id": sid, "owner": OWNER,
           "platform": kw.pop("platform", "databricks"), "provenance_class": "sample", "sample_run_id": "ga-ai-sample-1",
           "run_id": "run-1", "collector": "dbx_ai_collector", "collector_version": "1.0.0", "observed_at": NOW.isoformat()}
    row.update(kw)
    return row


def seeded_observations():
    rows = []
    for ep in sample.SCENARIO.endpoints:
        tags = {sample.INTAKE_TAG_KEY: ep.intake_id, sample.TIER_TAG_KEY: ep.tier}
        rows.append(_obs("serving_endpoint", ep.name, display_name=ep.name, platform="external", provider=ep.provider, tags_json=tags,
                         relationships_json=[{"kind": "serves", "target_kind": "external_model", "target_source_entity_id": f"{ep.name}/model"}]))
        rows.append(_obs("external_model", f"{ep.name}/model", parent_source_entity_id=ep.name, platform="external",
                         provider=ep.provider, model_family=ep.model, tags_json=tags))
    rows.append(_obs("mcp_server", f"{sample.SCENARIO.mcp_connection}", display_name=sample.SCENARIO.mcp_connection))
    rows.append(_obs("uc_function_tool", f"main.{sample.SCHEMA}.{sample.SCENARIO.function_tool}",
                     display_name=f"main.{sample.SCHEMA}.{sample.SCENARIO.function_tool}",
                     tags_json={sample.INTAKE_TAG_KEY: sample.SCENARIO.function_intake_id, sample.TIER_TAG_KEY: "low"}))
    rows.append(_obs("ai_model", f"main.{sample.SCHEMA}.{sample.SCENARIO.registered_model}",
                     display_name=f"main.{sample.SCHEMA}.{sample.SCENARIO.registered_model}"))
    return rows


class SampleScenarioTests(unittest.TestCase):
    def test_each_case_produces_its_finding(self) -> None:
        result = reconcile.reconcile(
            seeded_observations(), sample.intake_rows(OWNER, now=NOW), aliases={}, active_findings=[], sources=ALL,
            intake_tag_key=sample.INTAKE_TAG_KEY, tier_tag_key=sample.TIER_TAG_KEY, grace_days=30, now=NOW,
        )
        got = {(f.finding_type, f.intake_id) for f in result.findings}
        self.assertEqual(got, sample.EXPECTED_FINDINGS)
        states = {s.asset.source_entity_id: s.match.state for s in result.units}
        self.assertEqual(states[f"main.{sample.SCHEMA}.{sample.SCENARIO.function_tool}"], "matched")
        self.assertEqual(states[sample.SCENARIO.mcp_connection], "ambiguous")
        # Every finding carries sample provenance from its observation or intake.
        self.assertTrue(all(f.evidence.get("provenance") for f in result.findings))

    def test_no_real_secret_in_scenario(self) -> None:
        self.assertTrue(sample.PLACEHOLDER_SECRET_VALUE.startswith("not-a-real-key"))


if __name__ == "__main__":
    unittest.main()
