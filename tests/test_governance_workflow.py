from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from axiom.services import assets as asset_service
from axiom.services import governance as governance_service
from axiom.store import GovernanceStore


class FakeUC:
    def __init__(self, responses: list[tuple[str, pd.DataFrame]] | None = None) -> None:
        self.executed: list[str] = []
        self.queries: list[str] = []
        self.responses = responses or []
        self.warehouse_id = "warehouse-1"

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def query_df(self, sql: str):
        self.queries.append(sql)
        for pattern, frame in self.responses:
            if pattern in sql:
                return frame.copy()
        return pd.DataFrame()


class EmptyGovernanceSummaryStore:
    def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "request_id",
                "created_at",
                "created_by",
                "status",
                "uc_full_name",
                "new_comment",
                "review_note",
            ]
        )

    def list_glossary_terms(self, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame()

    def get_glossary_term(self, term_id: str) -> pd.Series | None:
        return None

    def list_glossary_reviewers(self) -> pd.DataFrame:
        return pd.DataFrame()

    def list_glossary_versions(self) -> pd.DataFrame:
        return pd.DataFrame()

    def list_glossary_term_links(self) -> pd.DataFrame:
        return pd.DataFrame()

    def list_activity_events(self, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame()

    def get_governance_queue_projection(self, scope_key: str) -> dict | None:
        return None

    def list_glossary_summary_projections(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_glossary_summary_projection(self, term_id: str) -> dict | None:
        return None


class GovernanceWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        governance_service.invalidate_governance_caches()
        asset_service.invalidate_asset_caches()

    def test_ensure_tables_bootstraps_projection_tables(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        store.ensure_tables()

        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS `main`.`axiom`.`governance_queue_projection`"
                in sql
                for sql in uc.executed
            )
        )
        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS `main`.`axiom`.`glossary_summary_projection`"
                in sql
                for sql in uc.executed
            )
        )

    def test_create_change_request_persists_threads_tasks_and_activity(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        request_id = store.create_change_request(
            created_by="writer@example.com",
            uc_full_name="main.sales.orders",
            new_comment="Update description: Add owner context",
            actor_role="writer",
        )

        self.assertTrue(request_id)
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`threads`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`thread_posts`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`tasks`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`activity_events`" in sql for sql in uc.executed))
        self.assertTrue(any("task-created" in sql for sql in uc.executed))
        self.assertFalse(any("INSERT INTO `main`.`axiom`.`change_requests`" in sql for sql in uc.executed))

    def test_workflow_identity_ensure_reuses_existing_actor_without_noop_write(self) -> None:
        uc = FakeUC(
            responses=[
                (
                    "FROM `main`.`axiom`.`identity_directory_entries`",
                    pd.DataFrame(
                        [
                            {
                                "entry_id": "entry-1",
                                "external_key": "writer@example.com",
                                "principal_type": "user",
                                "display_name": "Writer Example",
                                "email": "writer@example.com",
                                "is_active": True,
                                "source": "runtime_actor",
                                "attributes_json": None,
                                "synced_at": "2026-05-04T00:00:00Z",
                            }
                        ]
                    ),
                )
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        actor = store._ensure_actor_identity_entry("writer@example.com", actor_role="writer")

        self.assertEqual(actor["entryId"], "entry-1")
        self.assertEqual(uc.executed, [])

    def test_workflow_entity_reference_reuses_existing_registry_and_alias_without_noop_write(self) -> None:
        uc = FakeUC(
            responses=[
                (
                    "FROM `main`.`axiom`.`entity_registry`",
                    pd.DataFrame(
                        [
                            {
                                "entity_id": "entity-1",
                                "entity_kind": "asset",
                                "entity_fqn": "main.sales.orders",
                            }
                        ]
                    ),
                ),
                (
                    "FROM `main`.`axiom`.`entity_aliases`",
                    pd.DataFrame([{"alias_id": "alias-1"}]),
                ),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        entity = store._ensure_entity_registry_reference(
            "main.sales.orders",
            updated_by="writer@example.com",
            actor_role="writer",
        )

        self.assertEqual(entity["entityId"], "entity-1")
        self.assertEqual(uc.executed, [])

    def test_list_change_requests_reads_task_backed_workflow_rows(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description","note":"Add owner context"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`tasks` t", workflow_rows),
                ("FROM `main`.`axiom`.`change_requests`", pd.DataFrame()),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        requests_df = store.list_change_requests(status="pending", limit=10)

        self.assertFalse(requests_df.empty)
        self.assertEqual(requests_df.iloc[0]["request_id"], "task-123")
        self.assertEqual(requests_df.iloc[0]["status"], "pending")
        self.assertEqual(requests_df.iloc[0]["uc_full_name"], "main.sales.orders")
        self.assertIn("Update description", requests_df.iloc[0]["new_comment"])

    def test_list_change_requests_dedupes_mixed_workflow_and_legacy_rows(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description","note":"Add owner context"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        legacy_rows = pd.DataFrame(
            [
                {
                    "request_id": "task-123",
                    "created_at": "2026-04-14 21:59:00",
                    "created_by": "writer@example.com",
                    "status": "pending",
                    "uc_full_name": "main.sales.orders",
                    "new_comment": "Update description: Add owner context",
                    "review_note": "",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`tasks` t", workflow_rows),
                ("FROM `main`.`axiom`.`change_requests`", legacy_rows),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        requests_df = store.list_change_requests(status="pending", limit=10)

        self.assertEqual(len(requests_df.index), 1)
        self.assertEqual(requests_df.iloc[0]["request_id"], "task-123")

    def test_set_request_status_updates_task_rows_and_appends_activity(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description","note":"Add owner context"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`tasks` t", workflow_rows),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        store.set_request_status(
            request_id="task-123",
            status="approved",
            reviewed_by="steward@example.com",
            review_note="Looks good.",
            actor_role="steward",
        )

        self.assertTrue(any("UPDATE `main`.`axiom`.`tasks`" in sql for sql in uc.executed))
        self.assertTrue(any("UPDATE `main`.`axiom`.`threads`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`thread_posts`" in sql for sql in uc.executed))
        self.assertTrue(any("INSERT INTO `main`.`axiom`.`activity_events`" in sql for sql in uc.executed))
        self.assertTrue(any("task-status-updated" in sql for sql in uc.executed))
        self.assertFalse(any("UPDATE `main`.`axiom`.`change_requests`" in sql for sql in uc.executed))

    def test_set_request_status_resolved_closes_task_rows(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description","note":"Add owner context"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(responses=[("FROM `main`.`axiom`.`tasks` t", workflow_rows)])
        store = GovernanceStore(uc, "main", "axiom")

        store.set_request_status(
            request_id="task-123",
            status="resolved",
            reviewed_by="steward@example.com",
            review_note="Resolved from Stewardship Workbench.",
            actor_role="steward",
        )

        executed_sql = "\n".join(uc.executed)
        self.assertIn("status = 'resolved'", executed_sql)
        self.assertIn("resolution_code = 'approved'", executed_sql)
        self.assertIn("INSERT INTO `main`.`axiom`.`thread_posts`", executed_sql)
        self.assertIn("INSERT INTO `main`.`axiom`.`activity_events`", executed_sql)

    def test_set_request_status_applies_assignee_and_priority_triage(self) -> None:
        # Triage-only update: status stays "pending" (task stays open) while
        # assignee + priority land on the task row and the audit log records a
        # distinct task-triage-updated action.
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(responses=[("FROM `main`.`axiom`.`tasks` t", workflow_rows)])
        store = GovernanceStore(uc, "main", "axiom")

        store.set_request_status(
            request_id="task-123",
            status="pending",
            reviewed_by="steward@example.com",
            actor_role="steward",
            refresh_projection=False,
            assignee="steward@example.com",
            priority="p1",
        )

        executed_sql = "\n".join(uc.executed)
        self.assertIn("UPDATE `main`.`axiom`.`tasks`", executed_sql)
        self.assertIn("assignee_entry_id =", executed_sql)
        # Priority is stashed in requested_payload_json.requestedTags (the
        # tasks table has no priority column) so the workbench payload can
        # read it back through _request_record.
        self.assertIn('"priority": "p1"', executed_sql)
        self.assertIn("task-triage-updated", executed_sql)
        # No status transition happened, so this must NOT be recorded as a
        # status change.
        self.assertNotIn("task-status-updated", executed_sql)

    def test_set_request_status_status_change_carries_triage_in_same_audit_row(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-321",
                    "thread_id": "thread-321",
                    "entity_id": "entity-321",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": None,
                    "requested_payload_json": '{"title":"Update description","requestedTags":{"priority":"p3"}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-321",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(responses=[("FROM `main`.`axiom`.`tasks` t", workflow_rows)])
        store = GovernanceStore(uc, "main", "axiom")

        store.set_request_status(
            request_id="task-321",
            status="resolved",
            reviewed_by="steward@example.com",
            review_note="Resolved with new priority.",
            actor_role="steward",
            priority="p2",
        )

        executed_sql = "\n".join(uc.executed)
        self.assertIn("task-status-updated", executed_sql)
        self.assertIn('"priority": "p2"', executed_sql)
        self.assertNotIn("task-triage-updated", executed_sql)

    def test_governance_request_status_patch_validates_triage_fields(self) -> None:
        from pydantic import ValidationError

        from axiom.api.governance import GovernanceRequestStatusPatch

        patch = GovernanceRequestStatusPatch(
            status="Pending",
            assignee="Steward@Example.com",
            priority="P1",
        )
        self.assertEqual(patch.status, "pending")
        self.assertEqual(patch.assignee, "steward@example.com")
        self.assertEqual(patch.priority, "p1")

        # Empty triage fields are valid and mean "no change".
        empty = GovernanceRequestStatusPatch(status="resolved")
        self.assertEqual(empty.assignee, "")
        self.assertEqual(empty.priority, "")

        with self.assertRaises(ValidationError):
            GovernanceRequestStatusPatch(status="pending", priority="urgent")
        with self.assertRaises(ValidationError):
            GovernanceRequestStatusPatch(status="pending", assignee="not-an-email")

    def test_workflow_rows_surface_assignee_email_as_assigned_to(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-777",
                    "thread_id": "thread-777",
                    "entity_id": "entity-777",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": None,
                    "requested_payload_json": '{"title":"Update description","requestedTags":{"priority":"p1"}}',
                    "assignee_entry_id": "entry-steward",
                    "assignee_email": "steward@example.com",
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-777",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(responses=[("FROM `main`.`axiom`.`tasks` t", workflow_rows)])
        store = GovernanceStore(uc, "main", "axiom")

        frame = store.list_change_requests()

        self.assertEqual(len(frame.index), 1)
        row = frame.iloc[0].to_dict()
        self.assertEqual(row.get("assigned_to"), "steward@example.com")
        self.assertIn('"priority": "p1"', str(row.get("new_uc_tags_json")))

    def test_create_change_request_fans_out_owner_inbox_notification(self) -> None:
        owners_df = pd.DataFrame(
            [
                {
                    "owner_email": "owner@example.com",
                    "owner_type": "business",
                    "updated_at": "2026-04-14 22:00:00",
                    "updated_by": "admin@example.com",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`data_owners`", owners_df),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        store.create_change_request(
            created_by="writer@example.com",
            uc_full_name="main.sales.orders",
            new_comment="Update description: Add owner context",
            actor_role="writer",
        )

        self.assertTrue(any("MERGE INTO `main`.`axiom`.`notifications`" in sql for sql in uc.executed))
        self.assertTrue(any("MERGE INTO `main`.`axiom`.`notification_receipts`" in sql for sql in uc.executed))

    def test_set_request_status_fans_out_creator_inbox_notification(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Update description","note":"Add owner context"}',
                    "requested_payload_json": '{"title":"Update description","note":"Add owner context","fullComment":"Update description: Add owner context","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        thread_posts = pd.DataFrame(
            [
                {
                    "post_id": "post-1",
                    "thread_id": "thread-123",
                    "body_markdown": "Initial request",
                    "diff_json": "{}",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                    "created_at": "2026-04-14 22:00:00",
                    "edited_at": None,
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`tasks` t", workflow_rows),
                ("FROM `main`.`axiom`.`thread_posts` p", thread_posts),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        store.set_request_status(
            request_id="task-123",
            status="approved",
            reviewed_by="steward@example.com",
            review_note="Looks good.",
            actor_role="steward",
        )

        self.assertTrue(any("MERGE INTO `main`.`axiom`.`notifications`" in sql for sql in uc.executed))
        self.assertTrue(any("MERGE INTO `main`.`axiom`.`notification_receipts`" in sql for sql in uc.executed))

    def test_update_notification_receipt_marks_read_and_audits(self) -> None:
        receipt_df = pd.DataFrame(
            [
                {
                    "notification_id": "note-1",
                    "inbox_state": "new",
                    "seen_at": None,
                    "read_at": None,
                    "dismissed_at": None,
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`notification_receipts`", receipt_df),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        store.update_notification_receipt(
            notification_id="note-1",
            recipient_email="writer@example.com",
            action="read",
        )

        self.assertTrue(any("UPDATE `main`.`axiom`.`notification_receipts`" in sql for sql in uc.executed))
        self.assertTrue(any("notification-receipt-updated" in sql for sql in uc.executed))

    def test_governance_summary_does_not_fabricate_backlog_from_owner_gaps(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 0,
                    "pending_requests": 0,
                    "governance_status": "Needs Work",
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "",
                }
            ]
        )
        store = EmptyGovernanceSummaryStore()

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(FakeUC(), store, hidden_catalogs=set())

        self.assertEqual(payload["backlog"], [])

    def test_governance_summary_includes_actor_inbox_from_receipts(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 1,
                    "pending_requests": 0,
                    "governance_status": "Healthy",
                    "certification": "Certified",
                    "steward": "owner@example.com",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class InboxSummaryStore(EmptyGovernanceSummaryStore):
            def list_notifications(self, *, recipient_email: str, unread_only: bool = False, limit: int = 25) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "notification_id": "note-1",
                            "event_id": "event-1",
                            "payload_json": '{"title":"Task updated","detail":"Looks good.","status":"Approved","assetFqn":"main.sales.orders","createdBy":"steward@example.com"}',
                            "created_at": "2026-04-14 22:15:00",
                            "inbox_state": "new",
                        }
                    ]
                )

            def count_unread_notifications(self, *, recipient_email: str) -> int:
                return 1

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(),
                InboxSummaryStore(),
                actor_email="writer@example.com",
                hidden_catalogs=set(),
            )

        self.assertEqual(payload["inbox"]["state"], "live")
        self.assertEqual(payload["inbox"]["unreadCount"], 1)
        self.assertEqual(payload["inbox"]["items"][0]["notificationId"], "note-1")

    def test_governance_summary_prefers_queue_projection_for_counts(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 1,
                    "pending_requests": 1,
                    "governance_status": "Healthy",
                    "certification": "Certified",
                    "steward": "owner@example.com",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class QueueProjectionStore(EmptyGovernanceSummaryStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "task-1",
                            "created_at": "2026-04-14 22:00:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.orders",
                            "new_comment": "Assign owner: Add a business owner",
                            "review_note": "",
                        }
                    ]
                )

            def get_governance_queue_projection(self, scope_key: str) -> dict | None:
                if scope_key != "workspace:default":
                    return None
                return {
                    "scopeKey": scope_key,
                    "laneCounts": {"open-work": 2, "ownership": 5, "classification": 1, "trust": 0},
                    "openTaskCount": 8,
                    "observedAt": "2099-04-16 22:30:00",
                    "staleAfter": "2099-04-16 22:35:00",
                }

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(),
                QueueProjectionStore(),
                hidden_catalogs=set(),
            )

        open_requests_metric = next(
            metric["value"] for metric in payload["metrics"] if metric["label"] == "Open requests"
        )
        self.assertEqual(open_requests_metric, 8)
        self.assertEqual(payload["queue"]["source"], "projection")
        self.assertEqual(payload["queue"]["laneCounts"]["ownership"], 5)

    def test_governance_summary_ignores_stale_queue_projection(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 1,
                    "pending_requests": 1,
                    "governance_status": "Healthy",
                    "certification": "Certified",
                    "steward": "owner@example.com",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class StaleQueueProjectionStore(EmptyGovernanceSummaryStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "task-1",
                            "created_at": "2026-04-14 22:00:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.orders",
                            "new_comment": "Assign owner: Add a business owner",
                            "review_note": "",
                        }
                    ]
                )

            def get_governance_queue_projection(self, scope_key: str) -> dict | None:
                return {
                    "scopeKey": scope_key,
                    "laneCounts": {"open-work": 0, "ownership": 99, "classification": 0, "trust": 0},
                    "openTaskCount": 99,
                    "observedAt": "2026-04-10 22:00:00",
                    "staleAfter": "2026-04-10 22:01:00",
                }

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(),
                StaleQueueProjectionStore(),
                hidden_catalogs=set(),
            )

        open_requests_metric = next(
            metric["value"] for metric in payload["metrics"] if metric["label"] == "Open requests"
        )
        self.assertEqual(open_requests_metric, 1)
        self.assertEqual(payload["queue"]["source"], "live")

    def test_governance_summary_filters_hidden_backlog_assets_to_visible_inventory(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.visible_orders",
                    "table_name": "visible_orders",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "governance_status": "Needs Work",
                    "pending_requests": 1,
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class Store(EmptyGovernanceSummaryStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "visible-1",
                            "created_at": "2026-04-14 22:00:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.visible_orders",
                            "new_comment": "Refresh owner",
                            "review_note": "",
                        },
                        {
                            "request_id": "hidden-1",
                            "created_at": "2026-04-14 22:01:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.hidden_orders",
                            "new_comment": "Investigate lineage",
                            "review_note": "",
                        },
                    ]
                )

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(FakeUC(), Store(), hidden_catalogs=set())

        self.assertEqual([item["assetFqn"] for item in payload["backlog"]], ["main.sales.visible_orders"])
        open_requests_metric = next(
            item["value"] for item in payload["metrics"] if item.get("label") == "Open requests"
        )
        self.assertEqual(open_requests_metric, 1)

    def test_governance_summary_filters_hidden_activity_and_inbox_assets_to_visible_inventory(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.visible_orders",
                    "table_name": "visible_orders",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "governance_status": "Needs Work",
                    "pending_requests": 1,
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class Store(EmptyGovernanceSummaryStore):
            def list_activity_events(self, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "event_id": "visible-activity",
                            "event_type": "task_created",
                            "entity_fqn_snapshot": "main.sales.visible_orders",
                            "payload_json": '{"title":"Visible request","body":"Review visible asset"}',
                            "created_at": "2026-04-14 22:00:00",
                            "actor_email": "writer@example.com",
                        },
                        {
                            "event_id": "hidden-activity",
                            "event_type": "task_created",
                            "entity_fqn_snapshot": "main.sales.hidden_orders",
                            "payload_json": '{"title":"Hidden request","body":"Review hidden asset"}',
                            "created_at": "2026-04-14 22:01:00",
                            "actor_email": "writer@example.com",
                        },
                    ]
                )

            def list_notifications(self, *, recipient_email: str, unread_only: bool = False, limit: int = 25) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "notification_id": "visible-note",
                            "event_id": "visible-activity",
                            "payload_json": '{"title":"Visible request","detail":"Review visible asset","assetFqn":"main.sales.visible_orders","assetLabel":"visible_orders"}',
                            "created_at": "2026-04-14 22:02:00",
                            "inbox_state": "new",
                        },
                        {
                            "notification_id": "hidden-note",
                            "event_id": "hidden-activity",
                            "payload_json": '{"title":"Hidden request","detail":"Review hidden asset","assetFqn":"main.sales.hidden_orders","assetLabel":"hidden_orders"}',
                            "created_at": "2026-04-14 22:03:00",
                            "inbox_state": "new",
                        },
                    ]
                )

            def count_unread_notifications(self, *, recipient_email: str) -> int:
                return 2

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(),
                Store(),
                actor_email="writer@example.com",
                hidden_catalogs=set(),
            )

        self.assertEqual([item["assetFqn"] for item in payload["activity"]], ["main.sales.visible_orders"])
        self.assertEqual(payload["inbox"]["unreadCount"], 1)
        self.assertEqual(
            [item["assetFqn"] for item in payload["inbox"]["items"]],
            ["main.sales.visible_orders"],
        )

    def test_governance_summary_activity_rows_carry_backing_audit_ids(self) -> None:
        # Contract (cohesion follow-up 1): activity rows join to their
        # backing metadata_audit_log event via task_id == request_id and emit
        # displayAuditId ("AUD-"+first-8-hex) + auditEventId (full id) so the
        # client can deep-link to the Evidence page. Rows with no backing
        # event emit empty strings — never fabricated ids.
        from axiom.services.axiom_metrics import audit_display_id

        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.emet.run_history",
                    "table_name": "run_history",
                    "table_catalog": "main",
                    "table_schema": "emet",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "governance_status": "Needs Work",
                    "pending_requests": 1,
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "Ops",
                }
            ]
        )
        task_id = "596357596fa8474c865d9cf02488a167"

        class Store(EmptyGovernanceSummaryStore):
            def list_activity_events(self, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "event_id": "evt-comment",
                            "event_type": "comment_created",
                            "entity_fqn_snapshot": "main.emet.run_history",
                            "task_id": task_id,
                            "payload_json": '{"body":"Please review"}',
                            "created_at": "2026-05-05 02:51:37",
                            "actor_email": "abarreto@shorecp.com",
                        },
                        {
                            "event_id": "evt-created",
                            "event_type": "task_created",
                            "entity_fqn_snapshot": "main.emet.run_history",
                            "task_id": task_id,
                            "payload_json": '{"title":"Review run_history"}',
                            "created_at": "2026-05-05 02:51:38",
                            "actor_email": "abarreto@shorecp.com",
                        },
                        {
                            "event_id": "evt-triage",
                            "event_type": "task_state_changed",
                            "entity_fqn_snapshot": "main.emet.run_history",
                            "task_id": task_id,
                            "payload_json": '{"status":"open"}',
                            "created_at": "2026-07-21 14:59:35",
                            "actor_email": "abarreto@shorecp.com",
                        },
                        {
                            "event_id": "evt-orphan",
                            "event_type": "task_state_changed",
                            "entity_fqn_snapshot": "main.emet.run_history",
                            "task_id": "deadbeefdeadbeefdeadbeefdeadbeef",
                            "payload_json": '{"status":"open"}',
                            "created_at": "2026-07-21 15:10:00",
                            "actor_email": "abarreto@shorecp.com",
                        },
                    ]
                )

            def list_metadata_audit_for_requests(
                self, request_ids, *, limit: int = 500
            ) -> pd.DataFrame:
                assert task_id in list(request_ids)
                # Live-shaped rows (task 59635759… on the dev warehouse):
                # one creation row, two triage rows, one comment-only row.
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "fe36d39ce0a24b05a347f2d4864636e8",
                            "request_id": task_id,
                            "action": "task-created",
                            "created_at": "2026-05-05 02:51:41",
                        },
                        {
                            "audit_id": "45b263d718c6421db73003792af6c706",
                            "request_id": task_id,
                            "action": "task-triage-updated",
                            "created_at": "2026-07-21 14:59:37",
                        },
                        {
                            "audit_id": "4d36964d87bc48d595a439cd6220916c",
                            "request_id": task_id,
                            "action": "task-triage-updated",
                            "created_at": "2026-07-22 00:02:29",
                        },
                        {
                            "audit_id": "b1169eb8cf4e4735a3f666518bb58de7",
                            "request_id": task_id,
                            "action": "task-comment-added",
                            "created_at": "2026-07-22 00:05:24",
                        },
                    ]
                )

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(), Store(), hidden_catalogs=set()
            )

        by_event = {item["eventId"]: item for item in payload["activity"]}
        # Creation mutation: both its events bind to the task-created row.
        self.assertEqual(
            by_event["evt-created"]["auditEventId"],
            "fe36d39ce0a24b05a347f2d4864636e8",
        )
        self.assertEqual(by_event["evt-created"]["displayAuditId"], "AUD-FE36D39C")
        self.assertEqual(
            by_event["evt-comment"]["auditEventId"],
            "fe36d39ce0a24b05a347f2d4864636e8",
        )
        # Update mutation binds to ITS triage row (first at-or-after the
        # event timestamp), never the later 00:02:29 row.
        self.assertEqual(
            by_event["evt-triage"]["auditEventId"],
            "45b263d718c6421db73003792af6c706",
        )
        self.assertEqual(by_event["evt-triage"]["displayAuditId"], "AUD-45B263D7")
        # Derivation must match the Evidence page exactly.
        for item in payload["activity"]:
            if item["auditEventId"]:
                self.assertEqual(
                    item["displayAuditId"], audit_display_id(item["auditEventId"])
                )
        # No backing audit event → honest empty strings.
        self.assertEqual(by_event["evt-orphan"]["auditEventId"], "")
        self.assertEqual(by_event["evt-orphan"]["displayAuditId"], "")

    def test_governance_summary_activity_audit_ids_empty_without_request_index(self) -> None:
        # Stores without list_metadata_audit_for_requests (or with no task_id
        # on events) still serve the summary; the AUD fields are present but
        # empty so the frontend renders plain text.
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.visible_orders",
                    "table_name": "visible_orders",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "governance_status": "Needs Work",
                    "pending_requests": 0,
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class Store(EmptyGovernanceSummaryStore):
            def list_activity_events(self, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "event_id": "evt-1",
                            "event_type": "task_created",
                            "entity_fqn_snapshot": "main.sales.visible_orders",
                            "payload_json": '{"title":"Review"}',
                            "created_at": "2026-04-14 22:00:00",
                            "actor_email": "writer@example.com",
                        }
                    ]
                )

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(
                FakeUC(), Store(), hidden_catalogs=set()
            )

        self.assertEqual(len(payload["activity"]), 1)
        self.assertEqual(payload["activity"][0]["displayAuditId"], "")
        self.assertEqual(payload["activity"][0]["auditEventId"], "")

    def test_list_metadata_audit_for_requests_queries_by_request_id(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        result = store.list_metadata_audit_for_requests(
            ["596357596fa8474c865d9cf02488a167", "", "task-b"]
        )

        self.assertTrue(result.empty)
        query = uc.queries[-1]
        self.assertIn("`main`.`axiom`.`metadata_audit_log`", query)
        self.assertIn("request_id IN ('596357596fa8474c865d9cf02488a167', 'task-b')", query)
        self.assertIn("ORDER BY created_at ASC, audit_id ASC", query)

    def test_list_metadata_audit_for_requests_empty_ids_skip_query(self) -> None:
        uc = FakeUC()
        store = GovernanceStore(uc, "main", "axiom")

        result = store.list_metadata_audit_for_requests(["", None])

        self.assertTrue(result.empty)
        self.assertEqual(uc.queries, [])

    def test_governance_summary_ignores_queue_projection_when_pending_scope_is_mixed(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.visible_orders",
                    "table_name": "visible_orders",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "governance_status": "Needs Work",
                    "pending_requests": 1,
                    "certification": "",
                    "steward": "",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class Store(EmptyGovernanceSummaryStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "visible-1",
                            "created_at": "2026-04-14 22:00:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.visible_orders",
                            "new_comment": "Refresh owner",
                            "review_note": "",
                        },
                        {
                            "request_id": "hidden-1",
                            "created_at": "2026-04-14 22:01:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.hidden_orders",
                            "new_comment": "Investigate lineage",
                            "review_note": "",
                        },
                    ]
                )

            def get_governance_queue_projection(self, scope_key: str) -> dict | None:
                return {
                    "scopeKey": scope_key,
                    "laneCounts": {"open-work": 5, "ownership": 2, "classification": 1, "trust": 0},
                    "openTaskCount": 8,
                    "observedAt": "2099-04-16 22:30:00",
                    "staleAfter": "2099-04-16 22:35:00",
                }

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.governance_summary(FakeUC(), Store(), hidden_catalogs=set())

        self.assertEqual(payload["queue"]["source"], "live")
        self.assertEqual(payload["queue"]["laneCounts"]["ownership"], 1)
        open_requests_metric = next(
            item["value"] for item in payload["metrics"] if item.get("label") == "Open requests"
        )
        self.assertEqual(open_requests_metric, 1)

    def test_glossary_term_detail_filters_hidden_asset_links_to_visible_inventory(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.visible_orders",
                    "table_name": "visible_orders",
                    "table_catalog": "main",
                    "table_schema": "sales",
                    "table_type": "TABLE",
                    "data_source_format": "DELTA",
                    "comment": "Visible orders table",
                    "governance_status": "Needs Work",
                    "pending_requests": 0,
                    "domain": "Sales",
                    "tier": "Gold",
                    "certification": "",
                    "sensitivity": "",
                    "criticality": "",
                    "data_product": "",
                    "business_owner": "",
                }
            ]
        )

        class Store(EmptyGovernanceSummaryStore):
            def get_glossary_term(self, term_id: str) -> pd.Series | None:
                return pd.Series(
                    {
                        "term_id": "term-1",
                        "name": "Order",
                        "definition": "Order entity",
                        "status": "approved",
                    }
                )

            def list_glossary_term_links(self) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "term_id": "term-1",
                            "subject_type": "asset",
                            "subject_fqn": "main.sales.visible_orders",
                            "removed_at": None,
                            "resolution_state": "linked",
                        },
                        {
                            "term_id": "term-1",
                            "subject_type": "asset",
                            "subject_fqn": "main.sales.hidden_orders",
                            "removed_at": None,
                            "resolution_state": "linked",
                        },
                    ]
                )

            def get_glossary_summary_projection(self, term_id: str) -> dict | None:
                return {
                    "termId": term_id,
                    "assetCount": 2,
                    "reviewerCount": 0,
                    "childCount": 0,
                    "source": "projection",
                    "observedAt": "2099-04-16 22:30:00",
                    "staleAfter": "2099-04-16 22:35:00",
                }

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.glossary_term_detail(
                FakeUC(),
                Store(),
                term_id="term-1",
                hidden_catalogs=set(),
            )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["assets"], ["main.sales.visible_orders"])
        self.assertEqual(payload["assetCount"], 1)

    def test_governance_queue_projection_round_trip(self) -> None:
        projection_rows = pd.DataFrame(
            [
                {
                    "scope_key": "workspace:default",
                    "lane_counts_json": '{"open": 4, "blocked": 1}',
                    "open_task_count": 5,
                    "observed_at": "2026-04-14 22:20:00",
                    "stale_after": "2026-04-14 22:25:00",
                    "created_at": "2026-04-14 22:20:00",
                    "created_by": "system",
                    "updated_at": "2026-04-14 22:20:00",
                    "updated_by": "system",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`governance_queue_projection`", projection_rows),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        upserted = store.upsert_governance_queue_projection(
            scope_key="workspace:default",
            lane_counts={"open": 4, "blocked": 1},
            open_task_count=5,
            observed_at="2026-04-14 22:20:00",
            stale_after="2026-04-14 22:25:00",
            updated_by="system",
        )
        read_back = store.get_governance_queue_projection("workspace:default")

        self.assertTrue(
            any(
                "MERGE INTO `main`.`axiom`.`governance_queue_projection`" in sql
                for sql in uc.executed
            )
        )
        self.assertEqual(upserted["scopeKey"], "workspace:default")
        self.assertEqual(upserted["laneCounts"], {"open": 4, "blocked": 1})
        self.assertIsNotNone(read_back)
        self.assertEqual(read_back["scopeKey"], "workspace:default")
        self.assertEqual(read_back["laneCounts"], {"open": 4, "blocked": 1})
        self.assertEqual(read_back["openTaskCount"], 5)

    def test_refresh_governance_queue_projection_uses_pending_request_lanes(self) -> None:
        workflow_rows = pd.DataFrame(
            [
                {
                    "task_id": "task-123",
                    "thread_id": "thread-123",
                    "entity_id": "entity-123",
                    "entity_fqn_snapshot": "main.sales.orders",
                    "column_name": None,
                    "task_type": "description_change",
                    "diff_before_json": None,
                    "diff_after_json": '{"title":"Assign owner","note":"Add owner"}',
                    "requested_payload_json": '{"title":"Assign owner","note":"Add owner","fullComment":"Assign owner: Add owner","requestedTags":{}}',
                    "assignee_entry_id": None,
                    "assignee_email": None,
                    "reviewer_entry_id": None,
                    "reviewer_email": None,
                    "due_at": None,
                    "task_status": "open",
                    "resolution_code": None,
                    "resolved_payload_json": None,
                    "expected_version": 1,
                    "created_at": "2026-04-14 22:00:00",
                    "updated_at": "2026-04-14 22:00:00",
                    "thread_type": "task_request",
                    "thread_status": "open",
                    "created_by_entry_id": "entry-123",
                    "created_by_email": "writer@example.com",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`tasks` t", workflow_rows),
                ("FROM `main`.`axiom`.`change_requests`", pd.DataFrame()),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        projection = store.refresh_governance_queue_projection(updated_by="system")

        self.assertIsNotNone(projection)
        self.assertEqual(projection["openTaskCount"], 1)
        self.assertEqual(projection["laneCounts"]["ownership"], 1)
        self.assertTrue(
            any(
                "MERGE INTO `main`.`axiom`.`governance_queue_projection`" in sql
                for sql in uc.executed
            )
        )

    def test_glossary_summary_projection_round_trip(self) -> None:
        projection_rows = pd.DataFrame(
            [
                {
                    "term_id": "term-1",
                    "asset_count": 3,
                    "child_count": 2,
                    "reviewer_count": 1,
                    "observed_at": "2026-04-14 22:20:00",
                    "stale_after": "2026-04-14 22:25:00",
                    "created_at": "2026-04-14 22:20:00",
                    "created_by": "system",
                    "updated_at": "2026-04-14 22:20:00",
                    "updated_by": "system",
                }
            ]
        )
        uc = FakeUC(
            responses=[
                ("FROM `main`.`axiom`.`glossary_summary_projection`", projection_rows),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        upserted = store.upsert_glossary_summary_projection(
            term_id="term-1",
            asset_count=3,
            child_count=2,
            reviewer_count=1,
            observed_at="2026-04-14 22:20:00",
            stale_after="2026-04-14 22:25:00",
            updated_by="system",
        )
        read_back = store.get_glossary_summary_projection("term-1")

        self.assertTrue(
            any(
                "MERGE INTO `main`.`axiom`.`glossary_summary_projection`" in sql
                for sql in uc.executed
            )
        )
        self.assertEqual(upserted["termId"], "term-1")
        self.assertEqual(upserted["assetCount"], 3)
        self.assertIsNotNone(read_back)
        self.assertEqual(read_back["termId"], "term-1")
        self.assertEqual(read_back["assetCount"], 3)
        self.assertEqual(read_back["childCount"], 2)
        self.assertEqual(read_back["reviewerCount"], 1)

    def test_refresh_glossary_summary_projection_uses_live_link_and_reviewer_counts(self) -> None:
        glossary_terms_df = pd.DataFrame(
            [
                {
                    "term_id": "term-1",
                    "parent_term_id": None,
                    "name": "Customer Identifier",
                },
                {
                    "term_id": "term-2",
                    "parent_term_id": "term-1",
                    "name": "Customer Surrogate Key",
                },
            ]
        )
        glossary_reviewers_df = pd.DataFrame(
            [
                {"term_id": "term-1", "reviewer_email": "reviewer@example.com", "reviewer_role": "reviewer"},
                {"term_id": "term-1", "reviewer_email": "owner@example.com", "reviewer_role": "owner"},
            ]
        )
        glossary_links_df = pd.DataFrame(
            [
                {
                    "term_id": "term-1",
                    "subject_type": "asset",
                    "subject_fqn": "main.sales.orders",
                    "resolution_state": "linked",
                    "removed_at": None,
                },
                {
                    "term_id": "term-1",
                    "subject_type": "asset",
                    "subject_fqn": "main.sales.customers",
                    "resolution_state": "linked",
                    "removed_at": None,
                },
            ]
        )
        uc = FakeUC(
            responses=[
                ("SELECT term_id, glossary_id, name, definition, parent_term_id, domain, owner_email, status, is_mutually_exclusive, created_at, created_by, updated_at, updated_by FROM `main`.`axiom`.`glossary_terms` WHERE term_id = 'term-1' LIMIT 1", glossary_terms_df.head(1)),
                ("FROM `main`.`axiom`.`glossary_term_reviewers` WHERE term_id = 'term-1'", glossary_reviewers_df),
                ("SELECT term_id, glossary_id, name, definition, parent_term_id, domain, owner_email, status, is_mutually_exclusive, created_at, created_by, updated_at, updated_by FROM `main`.`axiom`.`glossary_terms`  ORDER BY lower(name) LIMIT 5000", glossary_terms_df),
                ("FROM `main`.`axiom`.`glossary_term_links`", glossary_links_df),
            ]
        )
        store = GovernanceStore(uc, "main", "axiom")

        projection = store.refresh_glossary_summary_projection(term_id="term-1", updated_by="system")

        self.assertIsNotNone(projection)
        self.assertEqual(projection["assetCount"], 2)
        self.assertEqual(projection["childCount"], 1)
        self.assertEqual(projection["reviewerCount"], 2)
        self.assertTrue(
            any(
                "MERGE INTO `main`.`axiom`.`glossary_summary_projection`" in sql
                for sql in uc.executed
            )
        )

    def test_glossary_term_detail_reads_dedicated_term_payload(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 1,
                    "pending_requests": 1,
                    "governance_status": "Healthy",
                    "certification": "Certified",
                    "steward": "owner@example.com",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class GlossaryDetailStore(EmptyGovernanceSummaryStore):
            def get_glossary_term(self, term_id: str) -> pd.Series | None:
                if term_id != "term-1":
                    return None
                return pd.Series(
                    {
                        "term_id": "term-1",
                        "name": "Customer Identifier",
                        "definition": "Stable customer grain identifier",
                        "domain": "Sales",
                        "owner_email": "owner@example.com",
                        "status": "approved",
                        "created_at": "2026-04-14 22:00:00",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-04-14 22:30:00",
                        "updated_by": "steward@example.com",
                    }
                )

            def list_glossary_reviewers(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "term_id": "term-1",
                            "reviewer_email": "reviewer@example.com",
                            "reviewer_role": "approver",
                            "created_at": "2026-04-14 22:05:00",
                            "created_by": "owner@example.com",
                            "updated_at": "2026-04-14 22:05:00",
                            "updated_by": "owner@example.com",
                        }
                    ]
                )

            def list_glossary_versions(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "version_id": "version-1",
                            "term_id": "term-1",
                            "version_number": 2,
                            "action": "updated",
                            "change_note": "Clarified identifier scope",
                            "name": "Customer Identifier",
                            "definition": "Stable customer grain identifier",
                            "domain": "Sales",
                            "owner_email": "owner@example.com",
                            "status": "approved",
                            "reviewer_snapshot_json": '[{"reviewerEmail":"reviewer@example.com","reviewerRole":"approver"}]',
                            "created_at": "2026-04-14 22:30:00",
                            "created_by": "steward@example.com",
                            "updated_at": "2026-04-14 22:30:00",
                            "updated_by": "steward@example.com",
                        }
                    ]
                )

            def list_glossary_term_links(self) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "link_id": "link-1",
                            "term_id": "term-1",
                            "term_name": "Customer Identifier",
                            "subject_type": "asset",
                            "subject_fqn": "main.sales.orders",
                            "column_name": None,
                            "is_primary": True,
                            "source": "manual",
                            "source_value": "Customer Identifier",
                            "resolution_state": "linked",
                            "created_at": "2026-04-14 22:10:00",
                            "created_by": "owner@example.com",
                            "updated_at": "2026-04-14 22:10:00",
                            "updated_by": "owner@example.com",
                            "removed_at": None,
                            "removed_by": None,
                        }
                    ]
                )

            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "task-1",
                            "created_at": "2026-04-14 22:40:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.orders",
                            "new_comment": "Glossary link request: Verify customer identifier",
                            "review_note": "",
                        }
                    ]
                )

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.glossary_term_detail(
                FakeUC(),
                GlossaryDetailStore(),
                term_id="term-1",
                hidden_catalogs=set(),
            )

        assert payload is not None
        self.assertEqual(payload["termId"], "term-1")
        self.assertEqual(payload["term"], "Customer Identifier")
        self.assertEqual(payload["ownerEmail"], "owner@example.com")
        self.assertEqual(payload["currentVersion"], "v2")
        self.assertEqual(payload["reviewerRoster"][0]["reviewerEmail"], "reviewer@example.com")
        self.assertEqual(payload["assetPreview"][0]["fqn"], "main.sales.orders")

    def test_glossary_term_detail_prefers_summary_projection_for_link_backed_counts(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "main.sales.orders",
                    "table_name": "orders",
                    "owner_count": 1,
                    "pending_requests": 1,
                    "governance_status": "Healthy",
                    "certification": "Certified",
                    "steward": "owner@example.com",
                    "sensitivity": "",
                    "domain": "Sales",
                }
            ]
        )

        class GlossaryProjectedDetailStore(EmptyGovernanceSummaryStore):
            def get_glossary_term(self, term_id: str) -> pd.Series | None:
                if term_id != "term-1":
                    return None
                return pd.Series(
                    {
                        "term_id": "term-1",
                        "name": "Customer Identifier",
                        "definition": "Stable customer grain identifier",
                        "domain": "Sales",
                        "owner_email": "owner@example.com",
                        "status": "approved",
                        "created_at": "2026-04-14 22:00:00",
                        "created_by": "owner@example.com",
                        "updated_at": "2026-04-14 22:30:00",
                        "updated_by": "owner@example.com",
                    }
                )

            def list_glossary_reviewers(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "term_id": "term-1",
                            "reviewer_email": "reviewer@example.com",
                            "reviewer_role": "reviewer",
                            "created_at": "2026-04-14 22:05:00",
                            "created_by": "owner@example.com",
                            "updated_at": "2026-04-14 22:05:00",
                            "updated_by": "owner@example.com",
                        }
                    ]
                )

            def list_glossary_versions(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame()

            def list_glossary_term_links(self) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "term_id": "term-1",
                            "subject_type": "asset",
                            "subject_fqn": "main.sales.orders",
                            "resolution_state": "linked",
                            "removed_at": None,
                        }
                    ]
                )

            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "task-1",
                            "created_at": "2026-04-14 22:10:00",
                            "created_by": "writer@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.orders",
                            "new_comment": "Update definition: Align term wording",
                            "review_note": "",
                        }
                    ]
                )

            def get_glossary_summary_projection(self, term_id: str) -> dict | None:
                if term_id != "term-1":
                    return None
                return {
                    "termId": "term-1",
                    "assetCount": 5,
                    "childCount": 2,
                    "reviewerCount": 3,
                    "observedAt": "2099-04-16 22:45:00",
                    "staleAfter": "2099-04-16 22:50:00",
                }

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.glossary_term_detail(
                FakeUC(),
                GlossaryProjectedDetailStore(),
                term_id="term-1",
                hidden_catalogs=set(),
            )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["assetCount"], 5)
        self.assertEqual(payload["childCount"], 2)
        self.assertEqual(payload["reviewerCount"], 3)
        self.assertEqual(payload["summarySource"], "projection")
        self.assertEqual(payload["pendingRequestCount"], 1)

    def test_glossary_term_detail_falls_back_to_list_glossary_terms_when_single_term_lookup_missing(self) -> None:
        inventory = pd.DataFrame()

        class LegacyGlossaryStore(EmptyGovernanceSummaryStore):
            def list_glossary_terms(self, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "term_id": "term-legacy",
                            "name": "Legacy Term",
                            "definition": "Recovered from list endpoint",
                            "domain": "Sales",
                            "owner_email": "owner@example.com",
                            "status": "approved",
                            "created_at": "2026-04-14 22:00:00",
                            "created_by": "owner@example.com",
                            "updated_at": "2026-04-14 22:30:00",
                            "updated_by": "owner@example.com",
                        }
                    ]
                )

            def list_glossary_reviewers(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame()

            def list_glossary_versions(self, term_id: str | None = None) -> pd.DataFrame:
                return pd.DataFrame()

            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame()

        with patch.object(asset_service, "visible_assets", return_value=inventory):
            payload = governance_service.glossary_term_detail(
                FakeUC(),
                LegacyGlossaryStore(),
                term_id="term-legacy",
                hidden_catalogs=set(),
            )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["termId"], "term-legacy")
        self.assertEqual(payload["term"], "Legacy Term")

    def test_glossary_term_detail_returns_none_for_missing_term(self) -> None:
        with patch.object(asset_service, "visible_assets", return_value=pd.DataFrame()):
            payload = governance_service.glossary_term_detail(
                FakeUC(),
                EmptyGovernanceSummaryStore(),
                term_id="missing-term",
                hidden_catalogs=set(),
            )

        self.assertIsNone(payload)

    def test_normalize_glossary_term_status_rejects_unknown_status(self) -> None:
        self.assertEqual(
            governance_service.normalize_glossary_term_status(" approved "),
            "approved",
        )
        with self.assertRaises(ValueError):
            governance_service.normalize_glossary_term_status("ready")

    def test_asset_activity_records_prefers_activity_events(self) -> None:
        class ActivityStore:
            def list_activity_events(self, *, entity_fqn: str | None = None, limit: int = 100) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "event_id": "event-1",
                            "event_type": "task_state_changed",
                            "entity_fqn_snapshot": entity_fqn,
                            "actor_email": "steward@example.com",
                            "actor_display_name": "",
                            "payload_json": '{"status":"resolved","resolutionCode":"approved","reviewNote":"Looks good."}',
                            "created_at": "2026-04-14 22:15:00",
                        }
                    ]
                )

            def list_change_requests(self, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "request_id": "legacy-1",
                            "created_at": "2026-04-14 21:00:00",
                            "created_by": "legacy@example.com",
                            "status": "pending",
                            "uc_full_name": "main.sales.orders",
                            "new_comment": "Legacy request",
                            "review_note": "",
                        }
                    ]
                )

        rows = asset_service.activity_records(ActivityStore(), "main.sales.orders", limit=10)

        self.assertEqual(rows[0]["title"], "Task updated")
        self.assertEqual(rows[0]["status"], "Approved")
        self.assertEqual(rows[0]["createdBy"], "steward@example.com")


if __name__ == "__main__":
    unittest.main()


class GovernanceSummaryStaleWhileRevalidateTests(unittest.TestCase):
    """G1 (perf) — an expired governance TTL entry serves the stale value
    immediately and rebuilds in the background, instead of blocking the
    request thread on the 20-33s multi-query summary rebuild."""

    def setUp(self) -> None:
        governance_service._TTL_CACHE.clear()
        with governance_service._TTL_REFRESH_LOCK:
            governance_service._TTL_REFRESHING.clear()

    def test_expired_entry_serves_stale_and_refreshes_in_background(self) -> None:
        import threading
        import time as _time

        refreshed = threading.Event()

        def loader():
            refreshed.set()
            return "fresh-value"

        # Seed an entry that is already past its TTL.
        governance_service._TTL_CACHE["swr-test"] = (_time.time() - 999, "stale-value")

        started = _time.time()
        value = governance_service._ttl_value("swr-test", 300, loader)
        elapsed = _time.time() - started

        # The caller gets the stale value instantly (never blocks on loader).
        self.assertEqual(value, "stale-value")
        self.assertLess(elapsed, 0.5)
        # ...and the background refresh replaces it shortly after.
        self.assertTrue(refreshed.wait(timeout=5))
        for _ in range(50):
            if governance_service._TTL_CACHE["swr-test"][1] == "fresh-value":
                break
            _time.sleep(0.05)
        self.assertEqual(governance_service._TTL_CACHE["swr-test"][1], "fresh-value")

    def test_cold_key_still_builds_synchronously(self) -> None:
        value = governance_service._ttl_value("swr-cold", 300, lambda: "built")
        self.assertEqual(value, "built")
