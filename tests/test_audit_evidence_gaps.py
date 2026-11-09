"""Regression tests for the Audit Evidence "incomplete product" gap fixes.

Covers: SQL-side internal-action exclusion (feed starvation), the 90d window,
lastEventAt guidance for empty ranges, backed policy-violation and
access-review summaries, the field-whitelisted before/after diff, synthesized
details, and real source-table provenance.
"""

from __future__ import annotations

import json
import unittest

import pandas as pd

from axiom.services import axiom_metrics
from axiom.store import GovernanceStore


def _ts(days_ago: float) -> str:
    return (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days_ago)).isoformat()


def _audit_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class RecordingUC:
    """Captures SQL passed to query_df so tests can assert on the WHERE clause."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def query_df(self, sql: str) -> pd.DataFrame:
        self.queries.append(sql)
        return pd.DataFrame()


class StoreSqlExclusionTests(unittest.TestCase):
    def _store(self) -> tuple[GovernanceStore, RecordingUC]:
        uc = RecordingUC()
        return GovernanceStore(uc, "main", "governance"), uc

    def test_exclude_internal_pushes_not_like_clauses_into_sql(self) -> None:
        store, uc = self._store()
        store.list_metadata_audit(exclude_internal=True, limit=25)
        sql = uc.queries[-1]
        self.assertIn("NOT LIKE '%identity%directory%'", sql)
        self.assertIn("NOT LIKE '%entity%registry%'", sql)
        self.assertIn("NOT LIKE '%entity%alias%'", sql)
        self.assertIn("NOT LIKE '%notification%'", sql)
        self.assertIn("NOT LIKE '%projection%'", sql)
        self.assertIn("NOT LIKE '%mirror%'", sql)
        # Both action and entity_type are guarded (identity_directory_entry
        # rows carry the marker in entity_type, not action).
        self.assertIn("LOWER(COALESCE(action, ''))", sql)
        self.assertIn("LOWER(COALESCE(entity_type, ''))", sql)
        self.assertIn("LIMIT 25", sql)

    def test_default_call_keeps_unfiltered_query(self) -> None:
        store, uc = self._store()
        store.list_metadata_audit(limit=10)
        self.assertNotIn("NOT LIKE", uc.queries[-1])

    def test_payload_requests_sql_side_exclusion(self) -> None:
        captured: dict = {}

        class CapturingStore:
            def list_metadata_audit(self, **kwargs: object) -> pd.DataFrame:
                captured.update(kwargs)
                return pd.DataFrame()

        axiom_metrics.audit_evidence_payload(store=CapturingStore(), limit=40)
        self.assertIs(captured.get("exclude_internal"), True)
        self.assertEqual(captured.get("limit"), 40)


class AuditWindowTests(unittest.TestCase):
    def test_90d_range_is_a_real_window(self) -> None:
        self.assertEqual(axiom_metrics._audit_window_start("90d"), pd.Timedelta(days=90))

    def test_90d_range_filters_out_older_rows(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": "AUD-NEW",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(5),
                        },
                        {
                            "audit_id": "AUD-OLD",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(200),
                        },
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), date_range="90d", limit=25)
        self.assertEqual(payload["summary"]["totalChanges"], 1)


class EmptyRangeGuidanceTests(unittest.TestCase):
    def test_last_event_at_is_reported_even_when_range_is_empty(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": "AUD-1",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(10),
                        }
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), date_range="24h", limit=25)
        self.assertEqual(payload["summary"]["totalChanges"], 0)
        self.assertTrue(payload["summary"]["lastEventAt"])
        # Sanity: the timestamp parses back to roughly 10 days ago.
        newest = pd.to_datetime(payload["summary"]["lastEventAt"], utc=True)
        age_days = (pd.Timestamp.now(tz="UTC") - newest).days
        self.assertGreaterEqual(age_days, 9)
        self.assertLessEqual(age_days, 11)


class SummarySemanticsTests(unittest.TestCase):
    def test_policy_violations_counts_exceptions_and_policy_failures(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": "AUD-1",
                            "entity_fqn": "main.risk.policy",
                            "action": "policy-exception-detected",
                            "status": "success",
                            "created_at": _ts(0.1),
                        },
                        {
                            "audit_id": "AUD-2",
                            "entity_fqn": "main.risk.policy",
                            "action": "policy update",
                            "status": "failed",
                            "created_at": _ts(0.2),
                        },
                        {
                            "audit_id": "AUD-3",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "policy tag applied",
                            "status": "success",
                            "detail": "Routine policy tag refresh",
                            "created_at": _ts(0.3),
                        },
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        # AUD-3 is a benign policy change: counted in policyChanges but not a violation.
        self.assertEqual(payload["summary"]["policyViolations"], 2)
        self.assertEqual(payload["summary"]["policyChanges"], 3)

    def test_access_reviews_backed_by_change_request_state(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {"request_id": "REQ-1", "status": "pending", "created_at": _ts(1)},
                        {"request_id": "REQ-2", "status": "open", "created_at": _ts(2)},
                        {"request_id": "REQ-3", "status": "approved", "created_at": _ts(3)},
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        # Renamed tile: these are governance change requests, not access
        # reviews. Open + resolved both come from the same ledger, and the
        # label ships in the payload so the UI cannot mislabel the tile.
        requests_block = payload["summary"]["governanceRequests"]
        self.assertEqual(requests_block["label"], "Governance requests")
        self.assertEqual(requests_block["open"], 2)
        self.assertEqual(requests_block["resolved"], 1)
        self.assertEqual(requests_block["source"], "governance change requests")
        self.assertNotIn("accessReviewsOpen", payload["summary"])

    def test_access_reviews_stay_unavailable_without_change_request_source(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        self.assertIsNone(payload["summary"]["governanceRequests"]["open"])
        self.assertIsNone(payload["summary"]["governanceRequests"]["resolved"])
        # A real store that terminally lacks the ledger keeps its reason as
        # the source line — that IS the honest terminal state.
        self.assertEqual(
            payload["summary"]["governanceRequests"]["state"], "unavailable"
        )
        self.assertTrue(payload["summary"]["governanceRequests"]["source"])

    def test_hydration_store_none_reports_loading_not_reason_string(self) -> None:
        # Regression: during app hydration the endpoint serves
        # audit_evidence_payload(store=None) while the real payload warms in
        # the background. The tile leaked "list_change_requests is not
        # available on the governance store." as its SOURCE line. Transient
        # hydration must present as loading with no diagnostic sentence.
        payload = axiom_metrics.audit_evidence_payload(store=None, limit=25)
        requests_block = payload["summary"]["governanceRequests"]
        self.assertIsNone(requests_block["open"])
        self.assertEqual(requests_block["state"], "loading")
        self.assertEqual(requests_block["source"], "")
        self.assertNotIn("is not available", str(requests_block))

    def test_source_table_reports_real_fqn(self) -> None:
        class AuditStore:
            catalog = "main"
            schema = "governance"

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        self.assertEqual(payload["summary"]["sourceTable"], "main.governance.metadata_audit_log")

    def test_source_table_empty_without_store_identity(self) -> None:
        payload = axiom_metrics.audit_evidence_payload(store=None, limit=25)
        self.assertEqual(payload["summary"]["sourceTable"], "")


class DiffWhitelistTests(unittest.TestCase):
    def _payload_for(self, before: dict | None, after: dict | None, detail: str = "Owner changed"):
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                row = {
                    "audit_id": "AUD-1",
                    "entity_fqn": "main.customer.customer_dim",
                    "action": "metadata updated",
                    "status": "success",
                    "detail": detail,
                    "created_at": _ts(0.1),
                }
                if before is not None:
                    row["before_json"] = json.dumps(before)
                if after is not None:
                    row["after_json"] = json.dumps(after)
                return _audit_frame([row])

        return axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)

    def test_safe_fields_survive_and_internal_keys_are_dropped(self) -> None:
        payload = self._payload_for(
            {"owner": "old.owner@shorecp.com", "actor_entry_id": "entry-123", "row_hash": "abc", "created_at": _ts(4)},
            {"owner": "abarreto@shorecp.com", "actor_entry_id": "entry-456", "row_hash": "def", "created_at": _ts(0.1)},
        )
        event = payload["events"][0]
        self.assertEqual(event["diffState"], "available")
        before = json.loads(event["before_json"])
        after = json.loads(event["after_json"])
        self.assertEqual(before["owner"], "old.owner@shorecp.com")
        self.assertEqual(after["owner"], "abarreto@shorecp.com")
        for blocked in ("actor_entry_id", "row_hash", "created_at"):
            self.assertNotIn(blocked, before)
            self.assertNotIn(blocked, after)
        # The evidence block mirrors the selected event's whitelisted diff.
        self.assertEqual(payload["evidence"]["before"], event["before_json"])
        self.assertEqual(payload["evidence"]["after"], event["after_json"])

    def test_rows_with_only_internal_keys_stay_redacted(self) -> None:
        payload = self._payload_for(
            {"actor_entry_id": "entry-123"},
            {"actor_entry_id": "entry-456"},
        )
        event = payload["events"][0]
        self.assertEqual(event["diffState"], "redacted")
        self.assertEqual(event["before_json"], "")
        self.assertEqual(event["after_json"], "")
        self.assertTrue(event["diffReason"])

    def test_rows_without_payloads_are_unavailable_not_redacted(self) -> None:
        payload = self._payload_for(None, None)
        event = payload["events"][0]
        self.assertEqual(event["diffState"], "unavailable")
        # Rows that never carried a payload simply omit/blank the field.
        self.assertEqual(event.get("before_json", ""), "")


class DetailSynthesisTests(unittest.TestCase):
    def test_missing_detail_is_synthesized_from_action_and_target(self) -> None:
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": "AUD-1",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "task-created",
                            "status": "success",
                            "detail": None,
                            "created_at": _ts(0.1),
                        },
                        {
                            "audit_id": "AUD-2",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(0.2),
                        },
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        by_id = {event["audit_id"]: event for event in payload["events"]}
        self.assertEqual(by_id["AUD-1"]["display_detail"], "Task Created for main.customer.customer_dim")
        # Rows with a real detail keep it; nothing synthesized on top.
        self.assertNotIn("display_detail", by_id["AUD-2"])


class StableAuditIdTests(unittest.TestCase):
    """A1 — display IDs derive from the real event UUID, never a row's position."""

    def test_display_id_is_first_8_hex_of_the_event_uuid(self) -> None:
        self.assertEqual(
            axiom_metrics.audit_display_id("2f8a41c6-9b7d-4e21-a5c3-000011112222"),
            "AUD-2F8A41C6",
        )

    def test_human_aud_ids_pass_through_verbatim(self) -> None:
        self.assertEqual(axiom_metrics.audit_display_id("AUD-1"), "AUD-1")

    def test_non_hex_ids_hash_stably(self) -> None:
        first = axiom_metrics.audit_display_id("zz-strange-id")
        second = axiom_metrics.audit_display_id("zz-strange-id")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("AUD-"))

    def test_payload_ids_do_not_change_when_the_window_changes(self) -> None:
        rows = [
            {
                "audit_id": f"0000000{index}-9b7d-4e21-a5c3-00001111222{index}",
                "entity_fqn": "main.customer.customer_dim",
                "action": "metadata updated",
                "status": "success",
                "detail": "Owner changed",
                "created_at": _ts(0.1 * (index + 1)),
            }
            for index in range(3)
        ]

        class AuditStore:
            def __init__(self, keep: int) -> None:
                self.keep = keep

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(rows[: self.keep])

        full = axiom_metrics.audit_evidence_payload(store=AuditStore(3), limit=25)
        narrowed = axiom_metrics.audit_evidence_payload(store=AuditStore(1), limit=25)
        # The first event keeps the same display ID no matter how many other
        # rows the current filter window happens to contain.
        self.assertEqual(
            full["events"][0]["displayAuditId"],
            narrowed["events"][0]["displayAuditId"],
        )
        self.assertEqual(full["events"][0]["displayAuditId"], "AUD-00000000")
        # The full backing UUID stays in the payload for cross-surface joins.
        self.assertEqual(
            full["events"][0]["auditEventId"],
            "00000000-9b7d-4e21-a5c3-000011112220",
        )


class WindowTruncationTests(unittest.TestCase):
    """A3 — when the raw fetch fills the limit, the payload must say so."""

    def _store(self, count: int):
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": f"AUD-{index}",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(0.01 * (index + 1)),
                        }
                        for index in range(count)
                    ]
                )

        return AuditStore()

    def test_full_window_reports_truncation(self) -> None:
        payload = axiom_metrics.audit_evidence_payload(store=self._store(5), limit=5)
        self.assertTrue(payload["summary"]["windowTruncated"])
        self.assertEqual(payload["summary"]["fetchedRows"], 5)
        self.assertEqual(payload["summary"]["fetchLimit"], 5)

    def test_partial_window_is_not_truncated(self) -> None:
        payload = axiom_metrics.audit_evidence_payload(store=self._store(3), limit=25)
        self.assertFalse(payload["summary"]["windowTruncated"])
        self.assertEqual(payload["summary"]["fetchedRows"], 3)


class ExclusionReconciliationTests(unittest.TestCase):
    """A2 — exclusion captions must reconcile: every count is computed on the
    same in-range, in-scope population, split by reason."""

    def _store(self):
        class AuditStore:
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return _audit_frame(
                    [
                        {
                            "audit_id": "AUD-KEEP",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": _ts(0.1),
                        },
                        {
                            # Internal bookkeeping row INSIDE the 24h range.
                            "audit_id": "AUD-INTERNAL",
                            "entity_type": "identity_directory_entry",
                            "action": "identity-directory-upserted",
                            "status": "success",
                            "created_at": _ts(0.2),
                        },
                        {
                            # Internal row OUTSIDE the 24h range: must not
                            # count against the 24h caption.
                            "audit_id": "AUD-INTERNAL-OLD",
                            "entity_type": "identity_directory_entry",
                            "action": "identity-directory-upserted",
                            "status": "success",
                            "created_at": _ts(30),
                        },
                        {
                            # Non-authoritative mock row inside the range.
                            "audit_id": "AUD-MOCK",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "prototype seed refresh",
                            "source": "mock-api",
                            "status": "success",
                            "created_at": _ts(0.3),
                        },
                    ]
                )

        return AuditStore()

    def test_counts_are_range_scoped_and_split_by_reason(self) -> None:
        day = axiom_metrics.audit_evidence_payload(store=self._store(), date_range="24h", limit=25)
        self.assertEqual(day["summary"]["totalChanges"], 1)
        self.assertEqual(day["summary"]["internalRowsExcluded"], 1)
        self.assertEqual(day["summary"]["nonAuthoritativeRowsExcluded"], 1)
        # hiddenRowsExcluded is the same population's total exclusions.
        self.assertEqual(day["summary"]["hiddenRowsExcluded"], 2)

        quarter = axiom_metrics.audit_evidence_payload(store=self._store(), date_range="90d", limit=25)
        self.assertEqual(quarter["summary"]["internalRowsExcluded"], 2)
        self.assertEqual(quarter["summary"]["nonAuthoritativeRowsExcluded"], 1)
        # The 24h counts are a subset of the 90d counts — captions reconcile.
        self.assertLessEqual(
            day["summary"]["internalRowsExcluded"],
            quarter["summary"]["internalRowsExcluded"],
        )


class AuditEventsRouteScopeTests(unittest.TestCase):
    """A5 — /api/audit/events applies the same visibility scoping and field
    whitelist as the Audit Evidence browser, and scrubs pandas-NaN leakage."""

    def _rows(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "audit_id": "2f8a41c6-9b7d-4e21-a5c3-000011112222",
                    "entity_type": "asset",
                    "entity_id": "internal-entity-id",
                    "entity_fqn": "main.customer.customer_dim",
                    "column_name": None,
                    "action": "metadata updated",
                    "source": "store",
                    "status": "success",
                    "before_json": json.dumps({"owner": "old@shorecp.com", "uc_full_name": "main.customer.customer_dim"}),
                    "after_json": json.dumps({"owner": "new@shorecp.com"}),
                    "actor_email": "abarreto@shorecp.com",
                    "actor_role": "admin",
                    "detail": "Owner changed",
                    "created_at": "2026-07-01 12:00:00",
                    "reviewed_by": "nan",
                    "uc_full_name": "main.customer.customer_dim",
                    "new_uc_tags_json": "{\"secret\":true}",
                },
                {
                    "audit_id": "aaaa41c6-9b7d-4e21-a5c3-000011119999",
                    "entity_type": "asset",
                    "entity_fqn": "restricted.payroll.salary_raw",
                    "action": "grant changed",
                    "status": "success",
                    "actor_email": "hidden.admin@shorecp.com",
                    "detail": "Privilege changed",
                    "created_at": "2026-07-01 13:00:00",
                },
            ]
        )

    def _call(self, visible_frame, rows: pd.DataFrame):
        import runtime_app
        from types import SimpleNamespace
        from unittest.mock import patch

        from axiom.api import catalog as catalog_api

        class EventsStore:
            def list_audit_events(self, **_: object) -> pd.DataFrame:
                return rows

        request = SimpleNamespace(headers={}, state=SimpleNamespace())
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _ensure_governance_store=lambda: None,
            _store=lambda: EventsStore(),
            _user_role_slug=lambda request: "steward",
            _visible_assets=(
                visible_frame
                if callable(visible_frame)
                else (lambda request: visible_frame)
            ),
        ):
            return catalog_api.api_audit_events(request)

    def test_rows_are_scoped_whitelisted_and_nan_scrubbed(self) -> None:
        visible = pd.DataFrame([{"fqn": "main.customer.customer_dim"}])
        response = self._call(visible, self._rows())
        payload = json.loads(response.body.decode("utf-8"))
        rows = payload["data"]
        serialized = json.dumps(payload)

        # Visibility scope: the out-of-scope asset's event is gone.
        self.assertEqual(len(rows), 1)
        self.assertNotIn("hidden.admin@shorecp.com", serialized)
        self.assertEqual(payload["meta"]["hiddenRowsExcluded"], 1)
        self.assertEqual(payload["meta"]["rowScope"], "visible-assets")

        row = rows[0]
        # Field whitelist: raw internal store fields never leave the API.
        for blocked in ("uc_full_name", "new_uc_tags_json", "entity_id", "reviewed_by"):
            self.assertNotIn(blocked, row)
        # NaN-string leakage is scrubbed everywhere in the payload.
        self.assertNotIn('"nan"', serialized)
        # Stable ID contract shared with the Audit Evidence browser.
        self.assertEqual(row["displayAuditId"], "AUD-2F8A41C6")
        self.assertEqual(row["audit_id"], "2f8a41c6-9b7d-4e21-a5c3-000011112222")
        # Diff is the whitelist-redacted object form; internal keys dropped.
        self.assertEqual(row["after"], {"owner": "new@shorecp.com"})
        self.assertNotIn("uc_full_name", json.dumps(row["before"]))
        # Timestamps are explicit-UTC ISO with Z.
        self.assertTrue(row["created_at"].endswith("Z"))

    def test_fails_closed_when_visibility_scope_unavailable(self) -> None:
        from fastapi import HTTPException

        def _raise(request):
            raise RuntimeError("inventory unavailable")

        with self.assertRaises(HTTPException) as ctx:
            self._call(_raise, self._rows())
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
