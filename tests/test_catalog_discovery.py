from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from axiom.services import live_metadata
from axiom.uc import UCSQLClient


class FakeCatalogUC:
    warehouse_id = "wh-discovery-test"

    def list_catalogs(self) -> pd.DataFrame:
        return pd.DataFrame({"catalog": ["ops_governance", "scp_snowflake", "lakebase_db", "shared_in", "system"]})

    def list_catalog_types(self) -> dict[str, str]:
        return {
            "ops_governance": "MANAGED_CATALOG",
            "scp_snowflake": "FOREIGN_CATALOG",
            "lakebase_db": "MANAGED_ONLINE_CATALOG",
            "shared_in": "DELTASHARING_CATALOG",
            "system": "SYSTEM_CATALOG",
        }


class CatalogDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        live_metadata._TTL_CACHE.clear()

    def tearDown(self) -> None:
        live_metadata._TTL_CACHE.clear()

    def test_all_catalogs_skips_federated_online_and_shared(self) -> None:
        self.assertEqual(live_metadata.cached_catalogs(FakeCatalogUC()), ["ops_governance"])

    def test_skipped_types_are_configurable(self) -> None:
        with patch.dict("os.environ", {"AXIOM_DISCOVERY_SKIP_CATALOG_TYPES": ""}):
            catalogs = live_metadata.cached_catalogs(FakeCatalogUC())
        self.assertIn("scp_snowflake", catalogs)


class EmptyInformationSchemaTests(unittest.TestCase):
    def _uc(self, frame: pd.DataFrame) -> tuple[UCSQLClient, list[str]]:
        uc = UCSQLClient.__new__(UCSQLClient)
        statements: list[str] = []

        def query_df(statement: str, **_: object) -> pd.DataFrame:
            statements.append(statement)
            return frame

        uc.query_df = query_df  # type: ignore[method-assign]
        return uc, statements

    def test_empty_catalog_inventory_does_not_requery_system_schema(self) -> None:
        uc, statements = self._uc(pd.DataFrame())
        self.assertTrue(uc.get_catalog_table_inventory("empty_catalog").empty)
        self.assertEqual(len(statements), 1)
        self.assertNotIn("system.information_schema", statements[0])

    def test_empty_catalog_tags_do_not_requery_system_schema(self) -> None:
        uc, statements = self._uc(pd.DataFrame())
        self.assertTrue(uc.get_catalog_table_tags("empty_catalog").empty)
        self.assertEqual(len(statements), 1)


class BulkInformationSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        from axiom.services import assets

        self.assets = assets
        assets._TTL_CACHE.clear()

    def tearDown(self) -> None:
        self.assets._TTL_CACHE.clear()

    def test_bulk_metadata_splits_one_pass_by_catalog(self) -> None:
        calls: list[list[str]] = []

        class BulkUC:
            warehouse_id = "wh-bulk-test"

            def get_information_schema_bulk(self, catalogs: list[str]):
                calls.append(catalogs)
                tables = pd.DataFrame(
                    [
                        {"table_catalog": "a", "table_schema": "s", "table_name": "t1", "table_type": "MANAGED",
                         "data_source_format": "DELTA", "comment": "", "last_altered": "2026-01-02T03:04:05Z",
                         "table_owner": "owner@x"},
                        {"table_catalog": "b", "table_schema": "s", "table_name": "t2", "table_type": "VIEW",
                         "data_source_format": "", "comment": "c", "last_altered": None, "table_owner": ""},
                    ]
                )
                tags = pd.DataFrame(
                    [{"table_catalog": "a", "table_schema": "s", "table_name": "t1", "tag_name": "domain", "tag_value": "ops"}]
                )
                return tables, tags

        result = self.assets._bulk_catalog_metadata(BulkUC(), ["a", "b", "empty"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(result["a"][0]["table_name"]), ["t1"])
        self.assertEqual(list(result["a"][1]["tag_value"]), ["ops"])
        self.assertEqual(result["a"][2]["a.s.t1"]["table_owner"], "owner@x")
        self.assertTrue(result["b"][1].empty)
        self.assertTrue(result["empty"][0].empty)

    def test_bulk_failure_falls_back_to_per_catalog_scan(self) -> None:
        class FailingUC:
            warehouse_id = "wh-bulk-fail"

            def get_information_schema_bulk(self, catalogs: list[str]):
                raise RuntimeError("system catalog unavailable")

        self.assertIsNone(self.assets._bulk_catalog_metadata(FailingUC(), ["a", "b"]))


if __name__ == "__main__":
    unittest.main()
