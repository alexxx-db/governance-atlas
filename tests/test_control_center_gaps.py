"""Regression tests for the Control Center "incomplete product" gap fixes.

Covers:
- Integrations rows are real: SQL Warehouse from runtime diagnostics,
  Lakeflow Jobs from the jobs probe, and NO aspirational Model Serving /
  Incident management placeholders.
- Scheduled-job inventory uses the app-principal client (not the OBO
  client whose token lacks the `jobs` scope) and requests latest runs.
- Policy panel re-scope: byDomain rows surface real metadata coverage
  (coverageKind: "metadata") instead of a hard-coded None.
- recentAdminActivity survives internal bookkeeping noise (deep audit
  fetch + filter).
- Truth-check per-catalog zero rows are flagged empty-or-unauthorized and
  non-zero drift gets an explanatory warning without degrading state.
"""

from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.api import admin
from axiom.api import axiom as axiom_api
from axiom.services import axiom_metrics


def _assets_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "main.customer.customer_dim",
                "table_catalog": "main",
                "table_schema": "customer",
                "table_name": "customer_dim",
                "comment": "Customer dimension",
                "domain": "Customer",
                "tier": "Tier 1",
                "certification": "Certified",
                "sensitivity": "Confidential",
                "criticality": "Critical",
                "data_product": "Customer 360",
                "business_owner": "abarreto@shorecp.com",
            },
            {
                "fqn": "main.finance.revenue",
                "table_catalog": "main",
                "table_schema": "finance",
                "table_name": "revenue",
                "comment": "",
                "domain": "Finance",
                "tier": "",
                "certification": "Draft",
                "sensitivity": "",
                "criticality": "Medium",
                "data_product": "",
                "business_owner": "",
            },
        ]
    )


def _noisy_audit_df() -> pd.DataFrame:
    """15 internal bookkeeping rows (newest) followed by 3 real events.

    With the old shallow fetch (limit=10) the real rows never reached
    _recent_events; the deep fetch (limit=50) must surface them.
    """
    internal = [
        {
            "audit_id": f"AUD-NOISE-{index}",
            "entity_fqn": "",
            "action": "identity-directory-upserted",
            "status": "success",
            "detail": "mirror upkeep",
            "created_at": f"2026-07-19 10:{index:02d}:00",
            "actor_email": "app@shorecp.com",
        }
        for index in range(15)
    ]
    real = [
        {
            "audit_id": "AUD-REAL-1",
            "entity_fqn": "main.customer.customer_dim",
            "action": "asset-metadata-updated",
            "status": "success",
            "detail": "Owner changed",
            "created_at": "2026-07-18 09:00:00",
            "actor_email": "abarreto@shorecp.com",
        },
        {
            "audit_id": "AUD-REAL-2",
            "entity_fqn": "main.finance.revenue",
            "action": "certification-updated",
            "status": "success",
            "detail": "Certified",
            "created_at": "2026-07-17 09:00:00",
            "actor_email": "abarreto@shorecp.com",
        },
        {
            "audit_id": "AUD-REAL-3",
            "entity_fqn": "main.customer.customer_dim",
            "action": "policy-exception-detected",
            "status": "failed",
            "detail": "Review REQ-9",
            "created_at": "2026-07-16 09:00:00",
            "actor_email": "abarreto@shorecp.com",
        },
    ]
    return pd.DataFrame(internal + real)


class NoisyAuditStore:
    def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame()

    def list_metadata_audit(self, limit: int = 200, **_: object) -> pd.DataFrame:
        # Honor the caller's limit the way the real store does — this is
        # what made the shallow limit=10 fetch lose every real event.
        return _noisy_audit_df().head(limit)

    def list_roles(self) -> pd.DataFrame:
        return pd.DataFrame([{"role_name": "admin"}, {"role_name": "steward"}])

    def list_identity_directory_entries(self, active_only: bool = True) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"principal_type": "user"},
                {"principal_type": "user"},
                {"principal_type": "group"},
            ]
        )


def _admin_payload(jobs=None, runtime=None):
    return axiom_metrics.admin_control_center_payload(
        visible_assets=_assets_df(),
        store=NoisyAuditStore(),
        runtime=runtime
        or {
            "state": "live",
            "catalogCount": 7,
            "client": {"authMode": "oauth-m2m-env", "warehouseId": "wh-123", "host": "https://dbc.example.com"},
        },
        environment={"displayLabel": "Dev · emet.axiom"},
        actor_role="admin",
        ai_status={"state": "available", "provider": "genie", "spaceId": "space-1"},
        jobs=jobs,
    )


class ControlCenterIntegrationsTests(unittest.TestCase):
    def test_sql_warehouse_row_reflects_live_runtime(self) -> None:
        payload = _admin_payload(jobs=[{"id": "1", "name": "Nightly sweep"}])
        rows = {row["key"]: row for row in payload["integrations"]}
        self.assertIn("sqlWarehouse", rows)
        self.assertEqual(rows["sqlWarehouse"]["state"], "connected")
        self.assertIn("wh-123", rows["sqlWarehouse"]["subtitle"])

    def test_sql_warehouse_row_unavailable_without_live_binding(self) -> None:
        payload = _admin_payload(runtime={"state": "degraded", "client": {}})
        rows = {row["key"]: row for row in payload["integrations"]}
        self.assertNotEqual(rows["sqlWarehouse"]["state"], "connected")
        self.assertTrue(rows["sqlWarehouse"]["reason"])

    def test_lakeflow_jobs_row_backed_by_jobs_probe(self) -> None:
        payload = _admin_payload(jobs=[{"id": "1", "name": "A"}, {"id": "2", "name": "B"}])
        rows = {row["key"]: row for row in payload["integrations"]}
        self.assertEqual(rows["lakeflowJobs"]["state"], "connected")
        self.assertIn("2 jobs", rows["lakeflowJobs"]["subtitle"])

        empty = _admin_payload(jobs=[])
        empty_rows = {row["key"]: row for row in empty["integrations"]}
        self.assertEqual(empty_rows["lakeflowJobs"]["state"], "unavailable")
        self.assertTrue(empty_rows["lakeflowJobs"]["reason"])

    def test_no_aspirational_integration_rows(self) -> None:
        payload = _admin_payload()
        keys = {row["key"] for row in payload["integrations"]}
        labels = " ".join(row["label"] for row in payload["integrations"])
        self.assertNotIn("modelServing", keys)
        self.assertNotIn("incidentManagement", keys)
        self.assertNotIn("Model Serving", labels)
        self.assertNotIn("Incident management", labels)
        # Existing consumers address rows by index — order is preserved.
        self.assertEqual(payload["integrations"][2]["key"], "aiCopilot")
        self.assertEqual(payload["integrations"][3]["key"], "notifications")


class ControlCenterPolicyTests(unittest.TestCase):
    def test_by_domain_rows_surface_real_metadata_coverage(self) -> None:
        payload = _admin_payload()
        by_domain = payload["policyRequirements"]["byDomain"]
        self.assertTrue(by_domain)
        for row in by_domain:
            self.assertEqual(row["coverage"], row["metadataCoverage"])
            self.assertIsNotNone(row["coverage"])
            self.assertEqual(row["coverageKind"], "metadata")
            self.assertEqual(row["state"], "available")
            self.assertIn("Metadata coverage", row["reason"])

    def test_unconsumed_all_null_compliance_block_pruned(self) -> None:
        payload = _admin_payload()
        self.assertNotIn("compliance", payload["policyRequirements"])
        # bulkImport is intentionally retained: existing consumers assert it.
        self.assertIn("bulkImport", payload)


class ControlCenterActivityTests(unittest.TestCase):
    def test_recent_activity_survives_internal_bookkeeping_noise(self) -> None:
        payload = _admin_payload()
        activity = payload["recentAdminActivity"]
        self.assertTrue(activity, "real governance events must survive noise filtering")
        titles = " ".join(event["title"] for event in activity)
        self.assertNotIn("Identity Directory", titles)
        ids = {event["id"] for event in activity}
        self.assertIn("AUD-REAL-1", ids)
        self.assertIn("AUD-REAL-3", ids)


class _FakeRuns:
    def __init__(self):
        self.calls = []

    def __call__(self, job_id=None, limit=None):
        self.calls.append((job_id, limit))
        return iter(
            [
                SimpleNamespace(
                    state=SimpleNamespace(result_state="SUCCESS", life_cycle_state="TERMINATED"),
                    start_time=1752900000000,
                    end_time=None,
                )
            ]
        )


def _fake_job(job_id: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        created_time=1752800000000,
        settings=SimpleNamespace(
            name=name,
            schedule=SimpleNamespace(
                quartz_cron_expression="0 0 3 * * ?",
                timezone_id="UTC",
                pause_status=None,
            ),
        ),
    )


class JobInventoryTests(unittest.TestCase):
    def test_none_client_degrades_to_empty_inventory(self) -> None:
        self.assertEqual(axiom_api._databricks_job_inventory(None), [])

    def test_inventory_includes_latest_run_status(self) -> None:
        runs = _FakeRuns()
        jobs_api = SimpleNamespace(
            list=lambda limit=None: iter([_fake_job(11, "Nightly sweep"), _fake_job(12, "Lineage collector")]),
            list_runs=runs,
        )
        client = SimpleNamespace(w=SimpleNamespace(jobs=jobs_api))
        rows = axiom_api._databricks_job_inventory(
            client,
            limit=12,
            include_latest_runs=True,
            workspace_host="https://dbc.example.com",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "Success")
        self.assertEqual(rows[0]["url"], "https://dbc.example.com/jobs/11")
        self.assertEqual(len(runs.calls), 2)
        # Run timestamps must carry the year — "Aug 25, 23:47" from a 2025
        # epoch read as current-year data in the Control Center.
        self.assertIn("2025", rows[0]["lastRun"])

    def test_never_run_manual_job_has_empty_last_run_and_manual_status(self) -> None:
        # Regression: never-run jobs rendered their CREATION time under
        # "Last run" and manual jobs (no schedule) were labeled "Scheduled".
        manual_job = SimpleNamespace(
            job_id=31,
            created_time=1756165620000,  # 2025-08-25 — must NOT leak into lastRun
            settings=SimpleNamespace(name="[RUNNER] pixels", schedule=None),
        )
        no_runs = SimpleNamespace(
            list=lambda limit=None: iter([manual_job]),
            list_runs=lambda job_id=None, limit=None: iter([]),
        )
        client = SimpleNamespace(w=SimpleNamespace(jobs=no_runs))
        rows = axiom_api._databricks_job_inventory(
            client,
            limit=12,
            include_latest_runs=True,
            workspace_host="https://dbc.example.com",
        )
        self.assertEqual(len(rows), 1)
        # Empty lastRun lets the UI render its honest "Not yet run" state.
        self.assertEqual(rows[0]["lastRun"], "")
        self.assertEqual(rows[0]["status"], "Manual")
        # nextRun is only populated from a real known schedule fire time —
        # the Jobs list API exposes none, so it must be empty (never invented).
        self.assertEqual(rows[0]["nextRun"], "")

    def test_never_run_scheduled_job_keeps_scheduled_status_but_empty_last_run(self) -> None:
        scheduled_job = _fake_job(41, "Nightly sweep")
        jobs_api = SimpleNamespace(
            list=lambda limit=None: iter([scheduled_job]),
            list_runs=lambda job_id=None, limit=None: iter([]),
        )
        client = SimpleNamespace(w=SimpleNamespace(jobs=jobs_api))
        rows = axiom_api._databricks_job_inventory(
            client,
            limit=12,
            include_latest_runs=True,
            workspace_host="https://dbc.example.com",
        )
        self.assertEqual(rows[0]["status"], "Scheduled")
        self.assertEqual(rows[0]["lastRun"], "")

    def test_control_center_endpoint_uses_app_principal_client_for_jobs(self) -> None:
        import runtime_app

        cfg = SimpleNamespace(
            deploy_target="Dev",
            environment_label="",
            gov_catalog="emet",
            gov_schema="axiom",
            warehouse_id="wh-1",
            workspace_host="https://dbc.example.com",
        )
        jobs_api = SimpleNamespace(
            list=lambda limit=None: iter([_fake_job(21, "UC metadata sweeper")]),
            list_runs=_FakeRuns(),
        )
        app_principal_client = SimpleNamespace(w=SimpleNamespace(jobs=jobs_api))

        def _fail_obo(request):  # pragma: no cover — assertion trap
            raise AssertionError("jobs inventory must not use the OBO client")

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "admin",
            _config=lambda: cfg,
            _visible_assets=lambda request: _assets_df(),
            _store_for_read=lambda: NoisyAuditStore(),
            _uc=lambda: app_principal_client,
            _uc_for_request=_fail_obo,
            _uc_runtime_status_fast=lambda background=False: {
                "state": "live",
                "client": {"authMode": "oauth-m2m-env", "warehouseId": "wh-1"},
            },
        ), patch.object(
            axiom_api.genie_service,
            "provider_status",
            return_value={"state": "available", "provider": "genie", "spaceId": "space-1"},
        ):
            request = SimpleNamespace(headers={}, state=SimpleNamespace())
            # refresh=1 takes the synchronous load path (no SWR warm thread).
            response = axiom_api.api_admin_control_center(request, refresh="1")

        self.assertEqual(response.status_code, 200)
        import json

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["jobsState"], "available")
        self.assertEqual(payload["jobs"][0]["name"], "UC metadata sweeper")
        self.assertEqual(payload["jobs"][0]["status"], "Success")


class _FakeUC:
    def __init__(self, results):
        self._results = results

    def query_df(self, sql, **_kwargs):
        for needle, df in self._results.items():
            if needle in sql:
                return df
        return pd.DataFrame()


class TruthCheckGapTests(unittest.TestCase):
    def setUp(self) -> None:
        admin._TRUTH_CACHE.clear()

    def _payload(self, *, tables_df, schemas_df, inventory_df, visible_df, catalogs="emet,ghost"):
        fake_uc = _FakeUC(
            {
                "system.information_schema.catalogs": pd.DataFrame([{"catalog_count": 7}]),
                "system.information_schema.schemata": schemas_df,
                "system.information_schema.tables": tables_df,
            }
        )
        fake_runtime_app = ModuleType("runtime_app")
        fake_runtime_app._uc = lambda: fake_uc
        fake_runtime_app._store = lambda: None
        fake_runtime_app._user_role_slug = lambda _request: "admin"

        from axiom.services import assets as real_assets

        with patch.dict(sys.modules, {"runtime_app": fake_runtime_app}), patch.dict(
            "os.environ", {"AXIOM_DISCOVERY_CATALOGS": catalogs}, clear=False
        ), patch.object(
            real_assets, "inventory", lambda *_a, **_k: inventory_df
        ), patch.object(
            real_assets, "visible_assets", lambda _df, **_k: visible_df
        ):
            return admin._build_truth_check_payload()

    def test_all_zero_catalog_flagged_empty_or_unauthorized(self) -> None:
        payload = self._payload(
            tables_df=pd.DataFrame([{"catalog": "emet", "table_count": 5}]),
            schemas_df=pd.DataFrame([{"catalog": "emet", "schema_count": 2}]),
            inventory_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
            visible_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
        )
        rows = {entry["catalog"]: entry for entry in payload["data"]["metastore"]["perCatalog"]}
        self.assertEqual(rows["ghost"]["state"], "empty-or-unauthorized")
        self.assertIn("app principal", rows["ghost"]["stateReason"])
        self.assertEqual(rows["emet"]["state"], "populated")
        self.assertEqual(rows["emet"]["stateReason"], "")

    def test_drift_gets_explanatory_warning_without_degrading_state(self) -> None:
        payload = self._payload(
            tables_df=pd.DataFrame([{"catalog": "emet", "table_count": 8}]),
            schemas_df=pd.DataFrame([{"catalog": "emet", "schema_count": 2}]),
            inventory_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
            visible_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
            catalogs="emet",
        )
        self.assertEqual(payload["data"]["drift"]["inventoryDelta"], 3)
        warnings = payload["data"]["drift"]["warnings"]
        self.assertTrue(any("3 metastore table" in warning for warning in warnings))
        self.assertTrue(any("stale inventory cache" in warning for warning in warnings))
        # Drift is explanation, not failure: state stays available.
        self.assertEqual(payload["meta"]["state"], "available")

    def test_zero_drift_emits_no_drift_warning(self) -> None:
        payload = self._payload(
            tables_df=pd.DataFrame([{"catalog": "emet", "table_count": 5}]),
            schemas_df=pd.DataFrame([{"catalog": "emet", "schema_count": 2}]),
            inventory_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
            visible_df=pd.DataFrame([{"table_catalog": "emet"} for _ in range(5)]),
            catalogs="emet",
        )
        self.assertEqual(payload["data"]["drift"]["inventoryDelta"], 0)
        self.assertEqual(payload["data"]["drift"]["warnings"], [])


if __name__ == "__main__":
    unittest.main()
