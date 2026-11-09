from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _env_names(entries: list[dict]) -> set[str]:
    return {str(entry["name"]) for entry in entries or []}


class AppEnvDriftTests(unittest.TestCase):
    def test_app_yaml_and_bundle_declare_the_same_env_vars(self) -> None:
        app_env = _env_names(yaml.safe_load((ROOT / "app.yaml").read_text())["env"])
        bundle = yaml.safe_load((ROOT / "databricks.yml").read_text())
        bundle_env = _env_names(bundle["resources"]["apps"]["axiom"]["config"]["env"])
        self.assertEqual(sorted(app_env - bundle_env), [], "only in app.yaml")
        self.assertEqual(sorted(bundle_env - app_env), [], "only in databricks.yml")


if __name__ == "__main__":
    unittest.main()
