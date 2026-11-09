from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd


class RuntimePatcher:
    def __init__(self, store, *, role: str = "steward", openable: bool = True) -> None:
        self.store = store
        self.role = role
        self.openable = openable
        self.previous = None

    def __enter__(self):
        self.previous = sys.modules.get("runtime_app")
        module = types.ModuleType("runtime_app")
        module._ensure_live_runtime = lambda: None
        module._ensure_governance_store = lambda: None
        module._store = lambda: self.store
        module._user_role_slug = lambda _request: self.role
        module._asset_is_openable = lambda _asset_fqn, _request: self.openable
        module._http_request_id = lambda _request: "http-rid-123"
        module._asset_detail_payload = lambda asset_fqn, **_kwargs: {
            "fqn": asset_fqn,
            "columns": [{"name": "id", "type": "int"}],
        }
        module._uc_for_request = lambda _request: SimpleNamespace(query_df=lambda _sql: pd.DataFrame([{"row_count": 7}]))
        sys.modules["runtime_app"] = module
        return module

    def __exit__(self, *_exc):
        if self.previous is None:
            sys.modules.pop("runtime_app", None)
        else:
            sys.modules["runtime_app"] = self.previous


class AuditStore:
    def __init__(self) -> None:
        self.audit_calls = []
        self.event_calls = []
        self.version_calls = []

    def append_metadata_audit_log(self, **kwargs):
        self.audit_calls.append(kwargs)
        return "audit-1"

    def append_change_event(self, **kwargs):
        self.event_calls.append(kwargs)
        return "event-1"

    def append_entity_version(self, **kwargs):
        self.version_calls.append(kwargs)
        return "version-1"


class FailingAuditMixin:
    def append_metadata_audit_log(self, **_kwargs):
        raise RuntimeError("audit unavailable")


class OwnerStore:
    def __init__(self) -> None:
        self.removed = []
        self.upserted = []

    def get_owners(self, _asset_fqn):
        return pd.DataFrame(
            [{"owner_email": "old@example.com", "owner_type": "business", "updated_at": None, "updated_by": None}]
        )

    def remove_owner(self, *args, **kwargs):
        self.removed.append((args, kwargs))

    def upsert_owner(self, *args, **kwargs):
        self.upserted.append((args, kwargs))


class CustomPropertyStore(AuditStore):
    def __init__(self) -> None:
        super().__init__()
        self.assignment_written = False
        self.assignment_reads = 0

    def list_custom_property_definitions(self, **_kwargs):
        return pd.DataFrame(
            [
                {
                    "definition_id": "def-1",
                    "entity_kind": "asset",
                    "property_key": "piiReviewStatus",
                    "display_name": "PII Review Status",
                    "description": "",
                    "data_type": "markdown",
                    "enum_values_json": None,
                    "is_required": False,
                    "is_multi": False,
                    "scope_json": None,
                    "state": "active",
                }
            ]
        )

    def list_custom_property_assignments(self, **kwargs):
        self.assignment_reads += 1
        if not self.assignment_written:
            return pd.DataFrame(
                [
                    {
                        "assignment_id": "old",
                        "definition_id": "def-1",
                        "definition_version": 1,
                        "entity_kind": "asset",
                        "entity_fqn": kwargs.get("entity_fqn"),
                        "column_name": kwargs.get("column_name"),
                        "value_json": json.dumps("old"),
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "assignment_id": "new",
                    "definition_id": "def-1",
                    "definition_version": 1,
                    "entity_kind": "asset",
                    "entity_fqn": kwargs.get("entity_fqn"),
                    "column_name": kwargs.get("column_name"),
                    "value_json": json.dumps("new"),
                }
            ]
        )

    def upsert_custom_property_assignment(self, **_kwargs):
        self.assignment_written = True


class FailingAuditCustomPropertyStore(FailingAuditMixin, CustomPropertyStore):
    pass


class OperationalStore(AuditStore):
    def __init__(self) -> None:
        super().__init__()
        self.latest_profile = {"profile_run_id": "previous"}
        self.profile_reads = 0
        self.quality_run_reads = 0
        self.quality_result_reads = 0

    def latest_profile_run_for_entity(self, _asset_fqn):
        self.profile_reads += 1
        return self.latest_profile

    def list_quality_runs(self, **_kwargs):
        self.quality_run_reads += 1
        return pd.DataFrame()

    def list_quality_run_results(self, **_kwargs):
        self.quality_result_reads += 1
        return pd.DataFrame()


class ExportStore(AuditStore):
    catalog = "emet"
    schema = "axiom"

    def __init__(self) -> None:
        super().__init__()
        self.sql = []
        self.uc = SimpleNamespace(execute=self.sql.append)

    def _fq(self, table: str) -> str:
        return f"`emet`.`axiom`.`{table}`"


class BackendWriteAuditContractsTests(unittest.TestCase):
    def request(self):
        return SimpleNamespace(headers={"x-forwarded-email": "writer@example.com", "x-forwarded-access-token": "token"})

    def test_owner_patch_propagates_http_request_id_to_store_writes(self) -> None:
        from axiom.services import governance

        store = OwnerStore()
        governance.patch_asset_owners(
            store,
            asset_fqn="emet.axiom.customer_dim",
            owner_assignments=[{"ownerEmail": "new@example.com", "ownerType": "steward"}],
            updated_by="writer@example.com",
            actor_role="steward",
            request_id="http-rid-123",
        )

        self.assertEqual(store.removed[0][1]["request_id"], "http-rid-123")
        self.assertEqual(store.upserted[0][1]["request_id"], "http-rid-123")

    def test_custom_property_assignment_audit_has_request_id_and_snapshots(self) -> None:
        from axiom.api import catalog

        store = CustomPropertyStore()
        with RuntimePatcher(store):
            response = catalog.api_upsert_custom_property_assignment(
                catalog.CustomPropertyAssignmentPayload(
                    definitionId="def-1",
                    value="<b>new</b>",
                    entityFqn="emet.axiom.customer_dim",
                ),
                self.request(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(store.audit_calls), 1)
        audit = store.audit_calls[0]
        self.assertEqual(audit["request_id"], "http-rid-123")
        self.assertEqual(audit["actor_role"], "steward")
        self.assertTrue(audit["before_json"])
        self.assertEqual(audit["after_json"]["value"], "&lt;b&gt;new&lt;/b&gt;")
        self.assertTrue(store.assignment_written)

    def test_custom_property_assignment_audit_failure_blocks_write(self) -> None:
        from axiom.api import catalog

        store = FailingAuditCustomPropertyStore()
        with RuntimePatcher(store):
            with self.assertRaises(RuntimeError):
                catalog.api_upsert_custom_property_assignment(
                    catalog.CustomPropertyAssignmentPayload(
                        definitionId="def-1",
                        value="new",
                        entityFqn="emet.axiom.customer_dim",
                    ),
                    self.request(),
                )

        self.assertFalse(store.assignment_written)

    def test_custom_property_read_requires_open_asset_before_store_read(self) -> None:
        from fastapi import HTTPException
        from axiom.api import catalog

        store = CustomPropertyStore()
        with RuntimePatcher(store, openable=False):
            with self.assertRaises(HTTPException) as ctx:
                catalog.api_asset_custom_properties("emet.axiom.customer_dim", self.request())

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(store.assignment_reads, 0)

    def test_profile_route_emits_audit_with_request_id(self) -> None:
        from axiom.api import catalog

        store = OperationalStore()
        result = SimpleNamespace(
            profile_run_id="profile-1",
            status="succeeded",
            row_count=7,
            column_metrics_written=1,
            error="",
        )
        with RuntimePatcher(store), patch("axiom.services.profile_runner.run_profile", return_value=result):
            response = catalog.api_run_asset_profile("emet.axiom.customer_dim", self.request())

        self.assertEqual(response.status_code, 200)
        audit = store.audit_calls[0]
        self.assertEqual(audit["entity_type"], "profile_run")
        self.assertEqual(audit["request_id"], "http-rid-123")
        self.assertEqual(audit["before_json"]["latestProfileRun"]["profile_run_id"], "previous")
        self.assertEqual(audit["after_json"]["profileRunId"], "profile-1")

    def test_profile_write_requires_open_asset_before_profile_run(self) -> None:
        from fastapi import HTTPException
        from axiom.api import catalog

        store = OperationalStore()
        with RuntimePatcher(store, openable=False), patch(
            "axiom.services.profile_runner.run_profile",
        ) as run_profile:
            with self.assertRaises(HTTPException) as ctx:
                catalog.api_run_asset_profile("emet.axiom.customer_dim", self.request())

        self.assertEqual(ctx.exception.status_code, 404)
        run_profile.assert_not_called()
        self.assertEqual(store.profile_reads, 0)
        self.assertFalse(store.audit_calls)

    def test_profile_read_requires_open_asset_before_store_read(self) -> None:
        from fastapi import HTTPException
        from axiom.api import catalog

        store = OperationalStore()
        with RuntimePatcher(store, openable=False):
            with self.assertRaises(HTTPException) as ctx:
                catalog.api_asset_profile("emet.axiom.customer_dim", self.request())

        self.assertEqual(ctx.exception.status_code, 404)

    def test_quality_route_requires_open_asset_and_emits_audit(self) -> None:
        from axiom.api import catalog

        store = OperationalStore()
        result = SimpleNamespace(run_id="quality-1", status="succeeded", passed=1, failed=0, errored=0, skipped=0)
        payload = catalog.QualityRunInlineRequest(
            assetFqn="emet.axiom.customer_dim",
            cases=[{"testKey": "row_count", "parameters": {"minRows": 1}}],
        )
        with RuntimePatcher(store), patch("axiom.services.quality_runner.run_quality_suite", return_value=result):
            response = catalog.api_run_asset_quality(payload, self.request())

        self.assertEqual(response.status_code, 200)
        audit = store.audit_calls[0]
        self.assertEqual(audit["entity_type"], "quality_run")
        self.assertEqual(audit["request_id"], "http-rid-123")
        self.assertEqual(audit["after_json"]["runId"], "quality-1")

    def test_quality_reads_require_open_asset_before_store_read(self) -> None:
        import json

        from fastapi import HTTPException
        from axiom.api import catalog

        store = OperationalStore()
        with RuntimePatcher(store, openable=False):
            # Per-asset quality is an availability probe: invisible assets get
            # an honest 200 "unavailable" envelope (a 404 spammed the browser
            # console for out-of-scope lineage neighbors) — but the store must
            # STILL never be read for an asset the actor cannot open.
            asset_response = catalog.api_asset_quality("emet.axiom.customer_dim", self.request())
            with self.assertRaises(HTTPException) as list_ctx:
                catalog.api_list_quality_runs(self.request(), entityFqn="emet.axiom.customer_dim")

        self.assertEqual(asset_response.status_code, 200)
        asset_payload = json.loads(asset_response.body)
        self.assertEqual(asset_payload["data"]["state"], "unavailable")
        self.assertEqual(asset_payload["data"]["runs"], [])
        self.assertEqual(list_ctx.exception.status_code, 404)
        self.assertEqual(store.quality_result_reads, 0)
        self.assertEqual(store.quality_run_reads, 0)

    def test_quality_custom_sql_validation_requires_open_asset(self) -> None:
        from fastapi import HTTPException
        from axiom.api import catalog

        payload = catalog.QualityCustomSqlRequest(
            targetEntityFqn="emet.axiom.customer_dim",
            sql="SELECT COUNT(*) FROM emet.axiom.customer_dim",
        )
        with RuntimePatcher(OperationalStore(), openable=False):
            with self.assertRaises(HTTPException) as ctx:
                catalog.api_quality_validate_custom_sql(payload, self.request())

        self.assertEqual(ctx.exception.status_code, 404)

    def test_export_job_persistence_audits_sync_exports_fail_closed(self) -> None:
        from axiom.api import export as export_api

        store = ExportStore()
        requested_at = datetime.now(timezone.utc)
        with RuntimePatcher(store, role="reader"):
            export_api._persist_export_job(
                request=self.request(),
                job_id="export-1",
                asset_fqns=["emet.axiom.customer_dim"],
                actor_email="reader@example.com",
                actor_role="reader",
                filter_snapshot="{}",
                status="ready",
                requested_at=requested_at,
                token_captured_at=requested_at,
                row_count=1,
                byte_count=25,
                mode="sync",
                fail_closed=True,
            )

        self.assertTrue(any("export_jobs" in sql for sql in store.sql))
        audit = store.audit_calls[0]
        self.assertEqual(audit["entity_type"], "export_job")
        self.assertEqual(audit["request_id"], "http-rid-123")
        self.assertEqual(audit["after_json"]["mode"], "sync")


if __name__ == "__main__":
    unittest.main()
