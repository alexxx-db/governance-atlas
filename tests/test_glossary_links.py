from __future__ import annotations

import unittest

from axiom.services import assets


class FakeRow:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


class FakeFrame:
    def __init__(self, rows):
        self._rows = [FakeRow(row) for row in rows]
        self.empty = not self._rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row

    def head(self, limit):
        return FakeFrame([row._values for row in self._rows[:limit]])


class GlossaryLinkTests(unittest.TestCase):
    def test_base_asset_payload_prefers_link_projection_and_exposes_data_product(self) -> None:
        payload = assets.base_asset_payload(
            FakeRow(
                {
                    "fqn": "main.sales.customers",
                    "table_name": "customers",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "MANAGED",
                    "data_source_format": "delta",
                    "comment": "Customer master",
                    "governance_score": 87,
                    "domain": "Sales",
                    "tier": "Gold",
                    "certification": "Certified",
                    "sensitivity": "Internal",
                    "criticality": "Tier 1",
                    "data_product": "Revenue 360",
                    "pending_requests": 2,
                    "tags": {"domain": "Sales"},
                    "glossaryLinks": [
                        {
                            "term": "Customer Identifier",
                            "termId": "term-123",
                            "source": "manual",
                        }
                    ],
                    "glossaryTerms": ["Customer Identifier"],
                    "glossary_term": "Legacy Tag Term",
                }
            )
        )

        self.assertEqual(payload["glossaryTerm"], "Customer Identifier")
        self.assertEqual(payload["dataProduct"], "Revenue 360")
        self.assertEqual(payload["data_product"], "Revenue 360")

    def test_column_records_prefers_linked_glossary_terms_over_tags(self) -> None:
        columns_df = FakeFrame(
            [
                {
                    "column_name": "customer_id",
                    "data_type": "string",
                    "comment": "Customer identifier",
                }
            ]
        )
        tags_df = FakeFrame(
            [
                {
                    "column_name": "customer_id",
                    "tag_name": "glossary_term",
                    "tag_value": "Legacy Tag Term",
                }
            ]
        )
        term_lookup = {
            "term-123": {
                "termId": "term-123",
                "name": "Customer Identifier",
            }
        }
        links_df = FakeFrame(
            [
                {
                    "link_id": "link-1",
                    "term_id": "term-123",
                    "subject_type": "column",
                    "subject_fqn": "main.sales.customers",
                    "column_name": "customer_id",
                    "is_primary": True,
                    "source": "manual",
                    "source_value": "Customer Identifier",
                    "resolution_state": "linked",
                    "created_at": "2026-04-14 12:00:00",
                    "created_by": "tester@example.com",
                    "updated_at": "2026-04-14 12:00:00",
                    "updated_by": "tester@example.com",
                    "removed_at": None,
                    "removed_by": None,
                }
            ]
        )

        rows = assets.column_records(
            columns_df,
            column_tags_df=tags_df,
            column_links_df=links_df,
            term_lookup=term_lookup,
            subject_fqn="main.sales.customers",
        )

        self.assertEqual(rows[0]["glossaryTerm"], "Customer Identifier")
        self.assertEqual(rows[0]["glossaryTerms"], ["Customer Identifier"])
        self.assertEqual(rows[0]["glossaryLinks"][0]["termId"], "term-123")

    def test_glossary_link_lookup_groups_links_by_subject(self) -> None:
        links_df = FakeFrame(
            [
                {
                    "link_id": "link-1",
                    "term_id": "term-123",
                    "subject_type": "asset",
                    "subject_fqn": "main.sales.customers",
                    "column_name": "",
                    "is_primary": True,
                    "source": "manual",
                    "source_value": "Customer Identifier",
                    "resolution_state": "linked",
                    "created_at": "2026-04-14 12:00:00",
                    "created_by": "tester@example.com",
                    "updated_at": "2026-04-14 12:00:00",
                    "updated_by": "tester@example.com",
                    "removed_at": None,
                    "removed_by": None,
                }
            ]
        )
        term_lookup = {
            "term-123": {
                "termId": "term-123",
                "name": "Customer Identifier",
            }
        }

        lookup = assets.glossary_link_lookup(links_df, term_lookup)

        self.assertIn("asset:main.sales.customers:", lookup)
        self.assertEqual(lookup["asset:main.sales.customers:"][0]["term"], "Customer Identifier")

    def test_metadata_audit_records_reads_log_surface_when_available(self) -> None:
        class FakeAuditStore:
            def list_metadata_audit_log(self, **_kwargs):
                return FakeFrame(
                    [
                        {
                            "audit_id": "audit-1",
                            "action": "description-updated",
                            "entity_type": "asset",
                            "entity_id": "main.sales.customers",
                            "column_name": "",
                            "status": "success",
                            "detail": "Updated description",
                            "actor_email": "tester@example.com",
                            "actor_role": "writer",
                            "created_at": "2026-04-14 12:00:00",
                            "created_by": "tester@example.com",
                            "before_json": "{\"description\": \"old\"}",
                            "after_json": "{\"description\": \"new\"}",
                            "request_id": "",
                            "source": "api",
                        }
                    ]
                )

        rows = assets.metadata_audit_records(FakeAuditStore(), "main.sales.customers")

        self.assertEqual(rows[0]["id"], "audit-1")
        self.assertEqual(rows[0]["action"], "description-updated")
        self.assertEqual(rows[0]["actorEmail"], "tester@example.com")


if __name__ == "__main__":
    unittest.main()
