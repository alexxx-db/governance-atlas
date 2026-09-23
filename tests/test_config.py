from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from atlas.config import AppConfig, _normalize_workspace_host

ROOT = os.path.dirname(os.path.dirname(__file__))


class WorkspaceHostNormalizationTests(unittest.TestCase):
    def test_schemeless_host_gets_https(self) -> None:
        # The dead "Open" job run-link: a schemeless DATABRICKS_HOST built a
        # relative deep link that 404'd against the app origin.
        self.assertEqual(
            _normalize_workspace_host("dbc-3aa503a9.cloud.databricks.com"),
            "https://dbc-3aa503a9.cloud.databricks.com",
        )

    def test_scheme_and_trailing_slash_are_respected(self) -> None:
        self.assertEqual(
            _normalize_workspace_host("https://dbc.example.com/"),
            "https://dbc.example.com",
        )
        self.assertEqual(_normalize_workspace_host("http://localhost:8080"), "http://localhost:8080")

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(_normalize_workspace_host(""), "")
        self.assertEqual(_normalize_workspace_host("   "), "")

    def test_from_env_normalizes_schemeless_host(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "dbc-xyz.cloud.databricks.com",
                "DATABRICKS_WAREHOUSE_ID": "warehouse-1",
                "GOVAT_CATALOG": "main",
                "GOVAT_SCHEMA": "atlas",
            },
            clear=True,
        ):
            config = AppConfig.from_env()
        self.assertEqual(config.workspace_host, "https://dbc-xyz.cloud.databricks.com")


class AppConfigTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "DATABRICKS_WAREHOUSE_ID": "warehouse-1",
            "GOVAT_CATALOG": "main",
            "GOVAT_SCHEMA": "atlas",
        },
        clear=True,
    )
    def test_from_env_uses_safe_optional_defaults(self) -> None:
        config = AppConfig.from_env()

        self.assertEqual(config.build_id, "")
        self.assertTrue(config.diagnostics_enabled)
        self.assertEqual(config.slow_request_ms, 1500)
        self.assertEqual(config.atlas_ai_provider, "local")
        self.assertEqual(config.genie_space_id, "")
        self.assertFalse(config.atlas_ai_require_benchmark)
        self.assertFalse(config.lakebase_enabled)
        self.assertEqual(config.lakebase_endpoint_name, "")
        self.assertEqual(config.lakebase_schema, "atlas_app")

    @patch.dict(
        os.environ,
        {
            "DATABRICKS_WAREHOUSE_ID": "warehouse-1",
            "GOVAT_CATALOG": "main",
            "GOVAT_SCHEMA": "atlas",
            "GOVAT_BUILD_ID": "build-123",
            "GOVAT_DIAGNOSTICS_ENABLED": "false",
            "GOVAT_SLOW_REQUEST_MS": "2400",
        },
        clear=True,
    )
    def test_from_env_reads_optional_diagnostics_settings(self) -> None:
        config = AppConfig.from_env()

        self.assertEqual(config.build_id, "build-123")
        self.assertFalse(config.diagnostics_enabled)
        self.assertEqual(config.slow_request_ms, 2400)

    @patch.dict(
        os.environ,
        {
            "DATABRICKS_WAREHOUSE_ID": "warehouse-1",
            "GOVAT_CATALOG": "main",
            "GOVAT_SCHEMA": "atlas",
            "GOVAT_BUILD_ID": "build-456",
            "GOVAT_DIAGNOSTICS_ENABLED": "false",
            "GOVAT_SLOW_REQUEST_MS": "3100",
        },
        clear=True,
    )
    def test_from_env_reads_govat_runtime_settings(self) -> None:
        config = AppConfig.from_env()

        self.assertEqual(config.gov_catalog, "main")
        self.assertEqual(config.gov_schema, "atlas")
        self.assertEqual(config.build_id, "build-456")
        self.assertFalse(config.diagnostics_enabled)
        self.assertEqual(config.slow_request_ms, 3100)

    @patch.dict(
        os.environ,
        {
            "DATABRICKS_WAREHOUSE_ID": "warehouse-1",
            "GOVAT_CATALOG": "preferred",
            "GOVAT_SCHEMA": "atlas",
        },
        clear=True,
    )
    def test_from_env_uses_govat_catalog_and_schema(self) -> None:
        config = AppConfig.from_env()

        self.assertEqual(config.gov_catalog, "preferred")
        self.assertEqual(config.gov_schema, "atlas")

    def test_source_app_yaml_keeps_genie_and_lakebase_optional(self) -> None:
        content = open(os.path.join(ROOT, "app.yaml"), encoding="utf-8").read()

        self.assertIn("name: GOVAT_CATALOG\n    value: \"main\"", content)
        self.assertIn("name: GOVAT_ADMIN_EMAILS\n    value: \"\"", content)
        self.assertIn("name: GOVAT_ATLAS_AI_PROVIDER\n    value: \"local\"", content)
        self.assertIn("name: GOVAT_GENIE_SPACE_ID\n    value: \"not-configured\"", content)
        self.assertIn("name: GOVAT_ATLAS_AI_REQUIRE_BENCHMARK\n    value: \"false\"", content)
        self.assertIn("name: GOVAT_LAKEBASE_ENABLED\n    value: \"false\"", content)
        self.assertIn("name: GOVAT_LAKEBASE_ENDPOINT_NAME\n    value: \"not-configured\"", content)
        self.assertNotIn("skyler@entrada.ai", content)
        self.assertNotIn('value: "datapact"', content)
        self.assertNotIn("01f1406a11221afa985d3fe64c9fbea1", content)
        self.assertNotIn("projects/governance-atlas-state/branches/production", content)

    def test_bundle_commits_no_workspace_specific_values(self) -> None:
        content = open(os.path.join(ROOT, "databricks.yml"), encoding="utf-8").read()

        # dev still binds the optional resources, fed only by BUNDLE_VAR_*.
        self.assertIn("atlas-genie-space", content)
        self.assertIn("atlas-lakebase", content)
        self.assertIn("space_id: ${var.genie_space_id}", content)
        self.assertIn("name: ${var.ai_generation_endpoint}", content)
        self.assertNotIn("profile: DEFAULT", content)
        for literal in (
            "@entrada.ai",
            "01f1406a11221afa985d3fe64c9fbea1",
            "governance-atlas-state",
            "da02d15a9490650b",
            "finance_prod",
            "gov_catalog: datapact",
        ):
            self.assertNotIn(literal, content)

if __name__ == "__main__":
    unittest.main()
