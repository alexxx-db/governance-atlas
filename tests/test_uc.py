from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from axiom import uc


class UnityCatalogImportCompatibilityTests(unittest.TestCase):
    def test_workspace_client_resolution_fails_at_runtime_not_module_import(self) -> None:
        databricks_pkg = types.ModuleType("databricks")
        databricks_pkg.__path__ = []
        sdk_module = types.ModuleType("databricks.sdk")

        with patch.dict(
            sys.modules,
            {
                "databricks": databricks_pkg,
                "databricks.sdk": sdk_module,
            },
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "databricks-sdk with WorkspaceClient support is required",
            ):
                uc._workspace_client_class()


if __name__ == "__main__":
    unittest.main()
