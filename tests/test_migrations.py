from __future__ import annotations

import re
import unittest

from atlas import migrations


class FakeColumn:
    def __init__(self, values):
        self._values = list(values)

    def tolist(self):
        return list(self._values)


class FakeFrame:
    def __init__(self, values):
        self._values = list(values)
        self.empty = not self._values

    def __getitem__(self, key):
        if key != "version":
            raise KeyError(key)
        return FakeColumn(self._values)


class FakeUC:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self._applied_versions: set[int] = set()

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        if "INSERT INTO `main`.`atlas`.`schema_migrations`" not in sql:
            return
        match = re.search(r"VALUES \(\s*(\d+),", sql)
        if match:
            self._applied_versions.add(int(match.group(1)))

    def query_df(self, sql: str):
        if "schema_migrations" not in sql:
            return FakeFrame([])
        return FakeFrame(sorted(self._applied_versions))


class MigrationTests(unittest.TestCase):
    def test_apply_migrations_creates_schema_migration_table_and_marks_baseline(self) -> None:
        uc = FakeUC()

        applied = migrations.apply_migrations(uc, "main", "atlas")

        self.assertEqual(applied, list(range(1, 23)))
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`schema_migrations`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("metadata_audit_log" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("glossary_term_links" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("identity_directory_entries" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("entity_registry" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("entity_aliases" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`threads`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`thread_posts`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`tasks`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`activity_events`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`notifications`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`notification_receipts`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`notification_preferences`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`governance_queue_projection`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`glossary_summary_projection`" in sql for sql in uc.executed)
        )
        # Phase 5 Tranche A tables landed in migration v8.
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`change_events`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`entity_versions`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`entity_relationships`" in sql for sql in uc.executed)
        )
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`identity_directory_memberships`" in sql for sql in uc.executed)
        )
        # Phase 4 Tranche 2 / Phase 12 — export_jobs landed in migration v9.
        self.assertTrue(
            any("CREATE TABLE IF NOT EXISTS `main`.`atlas`.`export_jobs`" in sql for sql in uc.executed)
        )
        # Phase 12 — background_work queue + dead letters landed in migration v10.
        for table in (
            "background_work_items",
            "background_work_runs",
            "background_dead_letters",
        ):
            self.assertTrue(
                any(f"CREATE TABLE IF NOT EXISTS `main`.`atlas`.`{table}`" in sql for sql in uc.executed),
                f"expected {table} create statement",
            )
        # Phase 8 — custom properties + profile tables landed in migration v11.
        for table in (
            "custom_property_definitions",
            "custom_property_definition_versions",
            "custom_property_assignments",
            "profile_runs",
            "profile_table_metrics",
            "profile_column_metrics",
        ):
            self.assertTrue(
                any(f"CREATE TABLE IF NOT EXISTS `main`.`atlas`.`{table}`" in sql for sql in uc.executed),
                f"expected {table} create statement",
            )
        # Phase 10 — quality core tables landed in migration v12.
        for table in (
            "quality_test_definitions",
            "quality_test_definition_versions",
            "quality_suites",
            "quality_test_cases",
            "quality_runs",
            "quality_run_results",
            "quality_alerts",
        ):
            self.assertTrue(
                any(f"CREATE TABLE IF NOT EXISTS `main`.`atlas`.`{table}`" in sql for sql in uc.executed),
                f"expected {table} create statement",
            )
        # Phase 11 — breadth + scale tables landed in migration v13.
        for table in (
            "classifications",
            "classification_terms",
            "domains",
            "data_products",
            "data_product_members",
            "logical_column_groups",
            "logical_column_group_members",
            "metrics",
            "contracts",
        ):
            self.assertTrue(
                any(f"CREATE TABLE IF NOT EXISTS `main`.`atlas`.`{table}`" in sql for sql in uc.executed),
                f"expected {table} create statement",
            )
        # Phase A9.4 — classification_recommendations landed in migration v15.
        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS `main`.`atlas`.`classification_recommendations`" in sql
                for sql in uc.executed
            ),
            "expected classification_recommendations create statement",
        )
        # F7 — tenant_branding landed in migration v16.
        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS `main`.`atlas`.`tenant_branding`" in sql
                for sql in uc.executed
            ),
            "expected tenant_branding create statement",
        )
        self.assertEqual(
            uc._applied_versions,
            set(range(1, 23)),
        )

    def test_apply_migrations_is_idempotent(self) -> None:
        uc = FakeUC()
        migrations.apply_migrations(uc, "main", "atlas")
        executed_after_first_run = len(uc.executed)

        applied = migrations.apply_migrations(uc, "main", "atlas")

        self.assertEqual(applied, [])
        # Idempotent replay re-runs `ensure_schema_migrations_table`
        # (CREATE SCHEMA + CREATE TABLE) twice (from apply_migrations +
        # applied_versions), which is the only execute() traffic.
        self.assertEqual(executed_after_first_run + 4, len(uc.executed))

    def test_ai_extension_migrations_resolve_placeholders(self) -> None:
        uc = FakeUC()
        migrations.apply_migrations(uc, "main", "atlas")
        for table in (
            "ai_asset_observations",
            "intake_records",
            "intake_records_history",
            "reconciliation_runs",
            "reconciliation_findings",
            "ai_control_results",
        ):
            self.assertTrue(
                any(f"CREATE TABLE IF NOT EXISTS `main`.`atlas`.`{table}`" in sql for sql in uc.executed),
                table,
            )
        # No unresolved {placeholder} survives formatting.
        self.assertFalse([sql for sql in uc.executed if re.search(r"\{[a-z_]+\}", sql)])

    def test_ai_extension_versions_are_19_to_22_in_order(self) -> None:
        versions = [m.version for m in migrations.DEFAULT_MIGRATIONS]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(versions[-4:], [19, 20, 21, 22])
        self.assertEqual(len(versions), len(set(versions)))


if __name__ == "__main__":
    unittest.main()
