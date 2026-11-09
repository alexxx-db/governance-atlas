from __future__ import annotations

import unittest

import pandas as pd

from axiom.store import GovernanceStore


class FakeUC:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.queries: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def query_df(self, sql: str):
        self.queries.append(sql)
        return pd.DataFrame()


class IdentityRegistryTests(unittest.TestCase):
    def test_identity_directory_upsert_merges_and_audits(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        payload = store.upsert_identity_directory_entry(
            external_key="alice@example.com",
            principal_type="user",
            display_name="Alice Example",
            email="alice@example.com",
            source="databricks",
            attributes={"team": "analytics"},
            updated_by="ops@example.com",
        )

        self.assertEqual(payload["externalKey"], "alice@example.com")
        self.assertEqual(payload["principalType"], "user")
        self.assertTrue(
            any("MERGE INTO `main`.`axiom`.`identity_directory_entries`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("INSERT INTO `main`.`axiom`.`metadata_audit_log`" in sql for sql in uc.executed)
        )
        self.assertTrue(any("identity-directory-upserted" in sql for sql in uc.executed))

    def test_entity_registry_and_aliases_are_durable(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        entity_payload = store.upsert_entity_registry(
            entity_id="entity-123",
            entity_kind="table",
            entity_fqn="main.sales.orders",
            source_system="uc",
            source_entity_id="uc-456",
            reconciliation_state="matched",
            reconciliation_confidence=0.9,
            updated_by="ops@example.com",
        )
        alias_payload = store.upsert_entity_alias(
            entity_id="entity-123",
            alias_value="main.sales.orders_old",
            alias_type="fqn",
            source="reconciliation",
            updated_by="ops@example.com",
        )

        self.assertEqual(entity_payload["entityId"], "entity-123")
        self.assertEqual(alias_payload["aliasValue"], "main.sales.orders_old")
        self.assertTrue(any("MERGE INTO `main`.`axiom`.`entity_registry`" in sql for sql in uc.executed))
        self.assertTrue(any("DELETE FROM `main`.`axiom`.`entity_aliases`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`entity_aliases`" in sql for sql in uc.executed))

    def test_registry_read_helpers_apply_expected_filters(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        store.list_identity_directory_entries("user", active_only=True)
        store.list_entity_registry("table")
        store.list_entity_aliases("entity-123", "fqn")

        self.assertTrue(
            any("lower(principal_type) = 'user'" in sql and "COALESCE(is_active, TRUE) = TRUE" in sql for sql in uc.queries)
        )
        self.assertTrue(any("lower(entity_kind) = 'table'" in sql for sql in uc.queries))
        self.assertTrue(
            any("entity_id = 'entity-123'" in sql and "lower(alias_type) = 'fqn'" in sql for sql in uc.queries)
        )


if __name__ == "__main__":
    unittest.main()
