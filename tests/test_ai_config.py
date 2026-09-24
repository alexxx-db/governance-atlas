"""AI governance extension config + feature flag (DESIGN.md section 12).

The flag defaults to off; when off, no /api/ai route may exist on the app."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI

from atlas.config import AppConfig, ai_features_enabled_from_env

_BASE_ENV = {"DATABRICKS_WAREHOUSE_ID": "wh", "GOVAT_CATALOG": "main", "GOVAT_SCHEMA": "atlas"}


def _config(**extra: str) -> AppConfig:
    with patch.dict(os.environ, {**_BASE_ENV, **extra}, clear=True):
        return AppConfig.from_env()


class AiConfigTests(unittest.TestCase):
    def test_defaults_are_safe(self) -> None:
        cfg = _config()
        self.assertFalse(cfg.ai_features_enabled)
        self.assertEqual(cfg.ai_intake_tag_key, "edw_intake_id")
        self.assertEqual(cfg.ai_tier_tag_key, "ai_risk_tier")
        self.assertEqual(cfg.ai_catalog_allowlist, [])
        self.assertEqual(cfg.ai_tool_schema_allowlist, [])
        self.assertEqual(cfg.ai_intake_grace_days, 30)

    def test_env_overrides_and_parsing(self) -> None:
        cfg = _config(
            GOVAT_AI_FEATURES_ENABLED="true",
            GOVAT_AI_INTAKE_TAG_KEY="intake_ref",
            GOVAT_AI_TIER_TAG_KEY="tier",
            GOVAT_AI_CATALOG_ALLOWLIST="main, ml_prod ,",
            GOVAT_AI_TOOL_SCHEMA_ALLOWLIST="main.tools",
            GOVAT_AI_INTAKE_GRACE_DAYS="-4",
        )
        self.assertTrue(cfg.ai_features_enabled)
        self.assertEqual(cfg.ai_intake_tag_key, "intake_ref")
        self.assertEqual(cfg.ai_tier_tag_key, "tier")
        self.assertEqual(cfg.ai_catalog_allowlist, ["main", "ml_prod"])
        self.assertEqual(cfg.ai_tool_schema_allowlist, ["main.tools"])
        self.assertEqual(cfg.ai_intake_grace_days, 0)

    def test_not_configured_sentinel_falls_back_to_default(self) -> None:
        cfg = _config(GOVAT_AI_INTAKE_TAG_KEY="not-configured", GOVAT_AI_CATALOG_ALLOWLIST="not-configured")
        self.assertEqual(cfg.ai_intake_tag_key, "edw_intake_id")
        self.assertEqual(cfg.ai_catalog_allowlist, [])

    def test_flag_helper_reads_env_without_full_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ai_features_enabled_from_env())
        with patch.dict(os.environ, {"GOVAT_AI_FEATURES_ENABLED": "1"}, clear=True):
            self.assertTrue(ai_features_enabled_from_env())


class AiRouteGateTests(unittest.TestCase):
    def test_flag_off_registers_nothing(self) -> None:
        import runtime_app

        target = FastAPI()
        self.assertFalse(runtime_app._register_ai_router(target, False))
        self.assertFalse([r for r in target.routes if getattr(r, "path", "").startswith("/api/ai")])

    def test_default_app_has_no_ai_routes(self) -> None:
        import runtime_app

        if ai_features_enabled_from_env():
            self.skipTest("GOVAT_AI_FEATURES_ENABLED is set in this environment")
        paths = [getattr(r, "path", "") for r in runtime_app.app.routes]
        self.assertFalse([p for p in paths if p.startswith("/api/ai")])


if __name__ == "__main__":
    unittest.main()
