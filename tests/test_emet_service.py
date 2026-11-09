from __future__ import annotations

import types
import unittest
from unittest.mock import patch

import pandas as pd

from axiom.config import AppConfig
from axiom.services import capabilities as capability_service
from axiom.services import emet as d
from axiom.services import genie as genie_service


def _cfg(**overrides) -> AppConfig:
    base = dict(
        warehouse_id="w",
        gov_catalog="main",
        gov_schema="axiom",
        emet_catalog="main",
        emet_schema="emet",
        workspace_host="https://example.cloud.databricks.com",
    )
    base.update(overrides)
    return AppConfig(**base)


class FakeUC:
    """A UCSQLClient stand-in whose query_df routes by substring match."""

    def __init__(self, tables=None, w=None):
        self.tables = tables or {}
        self.w = w
        self.queries = []

    def query_df(self, statement, timeout_s=30, **_kw):
        self.queries.append(statement)
        for key, value in self.tables.items():
            if key in statement:
                if isinstance(value, Exception):
                    raise value
                return value
        return pd.DataFrame()


def _surface_row(**overrides):
    row = {
        "manifest_key": "primary",
        "installation_id": "inst-1",
        "catalog_name": "main",
        "schema_name": "emet",
        "workspace_state": "READY",
        "dashboard_id": "dash-1",
        "dashboard_url": "/dashboardsv3/dash-1/published",
        "genie_space_id": "space-1",
        "genie_url": "/genie/rooms/space-1",
        "genie_status": "READY",
        "status_reason": None,
        "manifest_updated_at": "2026-06-15T18:17:18Z",
        "active_job_count": "16",
        "latest_portfolio_snapshot_ts": "2026-07-09T18:39:37Z",
        "latest_portfolio_run_count": "16",
        "dashboard_registered": "true",
        "genie_ready": "true",
        "shared_surface_status": "COHERENT",
        "shared_surface_reason": "ok",
        "installed_version": "3.0.10",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class _NoAppPrincipal(unittest.TestCase):
    """Stub the app-principal fallback client so resolver/status tests never
    touch the network — resolution is exercised only through the FakeUC client
    (or falls back to the manifest id when none is provided)."""

    def setUp(self):
        p = patch.object(d, "_app_principal_client", return_value=None)
        p.start()
        self.addCleanup(p.stop)


class DetectionTests(_NoAppPrincipal):
    def test_disabled_config_reports_disabled(self):
        status = d.status(_cfg(emet_enabled=False), FakeUC())
        self.assertEqual(status["state"], "disabled")
        self.assertFalse(status["detected"])

    def test_absent_when_no_catalog_and_no_pointer(self):
        # No config catalog and a client with no workspace pointer -> absent.
        status = d.status(_cfg(emet_catalog=""), FakeUC(w=None))
        self.assertEqual(status["state"], "absent")
        self.assertFalse(status["detected"])

    def test_available_maps_ready_state(self):
        uc = FakeUC({"portfolio_surface_status": _surface_row()})
        status = d.status(_cfg(), uc)
        self.assertEqual(status["state"], "available")
        self.assertTrue(status["detected"])
        self.assertEqual(status["version"], "3.0.10")
        self.assertEqual(status["dashboardId"], "dash-1")
        self.assertEqual(status["genieSpaceId"], "space-1")
        self.assertEqual(status["activeJobCount"], 16)

    def test_drifted_shared_surface_degrades_a_ready_install(self):
        uc = FakeUC(
            {"portfolio_surface_status": _surface_row(shared_surface_status="DRIFTED", shared_surface_reason="dashboard missing")}
        )
        status = d.status(_cfg(), uc)
        self.assertEqual(status["state"], "degraded")
        self.assertIn("dashboard", status["message"].lower())

    def test_failed_workspace_state_is_unavailable(self):
        uc = FakeUC({"portfolio_surface_status": _surface_row(workspace_state="FAILED", status_reason="init failed")})
        status = d.status(_cfg(), uc)
        self.assertEqual(status["state"], "unavailable")

    def test_missing_table_error_reads_as_absent_not_error(self):
        uc = FakeUC({"portfolio_surface_status": RuntimeError("TABLE_OR_VIEW_NOT_FOUND: portfolio_surface_status does not exist")})
        status = d.status(_cfg(), uc)
        self.assertEqual(status["state"], "absent")

    def test_transient_error_is_unavailable(self):
        uc = FakeUC({"portfolio_surface_status": RuntimeError("connection reset by peer")})
        status = d.status(_cfg(), uc)
        self.assertEqual(status["state"], "unavailable")

    def test_shell_integration_status_is_non_authoritative(self):
        uc = FakeUC({"portfolio_surface_status": _surface_row()})
        status = d.shell_integration_status(_cfg(), uc)
        self.assertFalse(status["authoritative"])
        self.assertEqual(status["surface"], "emet")


class LiveSurfaceResolutionTests(_NoAppPrincipal):
    """The manifest's dashboard/genie ids can be stale; GA must resolve the LIVE
    resource by name and only fall back to the manifest id."""

    def _client_with_live_surfaces(self):
        dash = types.SimpleNamespace(
            dashboard_id="live-dash", display_name=d.DASHBOARD_NAME, lifecycle_state="LifecycleState.ACTIVE"
        )
        trashed = types.SimpleNamespace(
            dashboard_id="dead-dash", display_name=d.DASHBOARD_NAME, lifecycle_state="LifecycleState.TRASHED"
        )
        space = types.SimpleNamespace(space_id="live-space", title=d.GENIE_ROOM_NAME)

        class FakeLakeview:
            def list(self, page_size=100):
                return iter([trashed, dash])

        class FakeGenie:
            def list_spaces(self, page_token=None):
                return types.SimpleNamespace(spaces=[space], next_page_token="")

        return types.SimpleNamespace(lakeview=FakeLakeview(), genie=FakeGenie())

    def test_prefers_live_active_dashboard_over_stale_manifest(self):
        uc = FakeUC(w=self._client_with_live_surfaces())
        self.assertEqual(d.resolve_dashboard_id(uc, "stale-manifest-id"), "live-dash")

    def test_prefers_live_genie_space_over_stale_manifest(self):
        uc = FakeUC(w=self._client_with_live_surfaces())
        self.assertEqual(d.resolve_genie_space_id(uc, "stale-manifest-id"), "live-space")

    def test_falls_back_to_manifest_when_no_client(self):
        uc = FakeUC(w=None)
        self.assertEqual(d.resolve_dashboard_id(uc, "manifest-dash"), "manifest-dash")
        self.assertEqual(d.resolve_genie_space_id(uc, "manifest-space"), "manifest-space")

    def test_status_urls_built_from_resolved_ids(self):
        client = self._client_with_live_surfaces()
        uc = FakeUC({"portfolio_surface_status": _surface_row(dashboard_id="stale", genie_space_id="stale")}, w=client)
        status = d.status(_cfg(), uc)
        self.assertEqual(status["dashboardId"], "live-dash")
        self.assertEqual(status["dashboardUrl"], "/dashboardsv3/live-dash/published")
        self.assertEqual(status["genieSpaceId"], "live-space")
        self.assertEqual(status["genieUrl"], "/genie/rooms/live-space")


class InstallResolutionTests(unittest.TestCase):
    def test_config_catalog_wins(self):
        install = d.resolve_install(_cfg(emet_catalog="prod", emet_schema="emet"), FakeUC())
        self.assertEqual((install.catalog, install.schema, install.source), ("prod", "emet", "config"))

    def test_fqn_rejects_injection(self):
        install = d.Install(catalog="main", schema="emet", source="config")
        self.assertEqual(install.fqn("run_checks"), "`main`.`emet`.`run_checks`")
        with self.assertRaises(ValueError):
            d.Install(catalog="main; DROP", schema="emet", source="x").fqn("t")


class OverviewTests(unittest.TestCase):
    def _uc(self):
        latest = pd.DataFrame(
            [
                {
                    "run_id": "100", "job_id": "1", "job_name": "Job A", "normalized_job_name": "job a",
                    "job_start_ts": "2026-07-09T00:00:00Z", "job_run_label": "latest",
                    "trust_score": "44.44", "total_validations": "5", "failed_validations": "2",
                    "successful_validations": "3", "success_rate_percent": "60",
                    "critical_failures": "2", "potential_impact_usd": "1000", "realized_impact_usd": "500",
                    "avg_expected_sla_hours": "4", "priority_weight_sum": "20", "successful_priority_weight_sum": "9",
                },
                {
                    "run_id": "200", "job_id": "2", "job_name": "Job B", "normalized_job_name": "job b",
                    "job_start_ts": "2026-07-09T00:00:00Z", "job_run_label": "latest",
                    "trust_score": "100", "total_validations": "10", "failed_validations": "0",
                    "successful_validations": "10", "success_rate_percent": "100",
                    "critical_failures": "0", "potential_impact_usd": "0", "realized_impact_usd": "0",
                    "avg_expected_sla_hours": "1", "priority_weight_sum": "30", "successful_priority_weight_sum": "30",
                },
            ]
        )
        registry = pd.DataFrame(
            [
                {"display_job_name": "Job A", "normalized_job_name": "job a", "execution_job_id": "11",
                 "job_state": "ACTIVE", "execution_warehouse": "w", "last_run_id": "100", "created_by": "me", "updated_at": "t"},
                {"display_job_name": "Job B", "normalized_job_name": "job b", "execution_job_id": "12",
                 "job_state": "ACTIVE", "execution_warehouse": "w", "last_run_id": "200", "created_by": "me", "updated_at": "t"},
            ]
        )
        compare = pd.DataFrame(
            [
                {"normalized_job_name": "job a", "trust_score_delta": "-5", "success_rate_delta": "-10",
                 "failed_validations_delta": "1", "critical_failures_delta": "1", "cutover_blockers_delta": "1",
                 "latest_cutover_blockers": "2", "previous_cutover_blockers": "1", "new_regressions": "1",
                 "healed_validations": "0", "persistent_failures": "1", "previous_run_id": "99", "previous_trust_score": "49"},
            ]
        )
        fixfirst = pd.DataFrame(
            [
                {"job_name": "Job A", "normalized_job_name": "job a", "run_id": "100", "task_key": "t1",
                 "business_priority": "CRITICAL", "business_domain": "Fin", "business_owner": "o",
                 "primary_failure_mode": "Hash mismatch", "failed_check_count": "2", "cutover_blocker": "true",
                 "sla_breached": "false", "hours_over_sla": "0", "estimated_impact_usd": "500",
                 "realized_impact_usd": "500", "failure_streak": "3", "fix_first_rank": "1"},
            ]
        )
        return FakeUC(
            {
                "job_registry_active": registry,
                "portfolio_latest_runs": latest,
                "portfolio_compare_latest_vs_previous": compare,
                "portfolio_fix_first": fixfirst,
            }
        )

    def test_rollup_trust_is_weighted_not_averaged(self):
        ov = d.overview(_cfg(), self._uc())
        self.assertTrue(ov["detected"])
        self.assertEqual(len(ov["jobs"]), 2)
        # Weighted: (9+30)/(20+30)*100 = 78.0 — NOT the naive mean of 44.44/100 (72.2).
        self.assertEqual(ov["rollup"]["trustScore"], 78.0)
        self.assertEqual(ov["rollup"]["failingJobCount"], 1)
        self.assertEqual(ov["rollup"]["criticalFailures"], 2)
        self.assertEqual(ov["rollup"]["cutoverBlockers"], 2)

    def test_jobs_merge_latest_and_delta(self):
        ov = d.overview(_cfg(), self._uc())
        job_a = next(j for j in ov["jobs"] if j["normalizedJobName"] == "job a")
        self.assertEqual(job_a["executionJobId"], 11)
        self.assertEqual(job_a["trustScore"], 44.44)
        self.assertEqual(job_a["trustScoreDelta"], -5.0)
        self.assertEqual(job_a["cutoverBlockers"], 2)
        self.assertTrue(job_a["hasRun"])
        self.assertEqual(len(ov["fixFirst"]), 1)
        self.assertEqual(ov["fixFirst"][0]["primaryFailureMode"], "Hash mismatch")

    def test_not_detected_returns_empty_shape(self):
        ov = d.overview(_cfg(emet_catalog=""), FakeUC(w=None))
        self.assertFalse(ov["detected"])
        self.assertEqual(ov["jobs"], [])
        self.assertIsNone(ov["rollup"]["trustScore"])


class RunStatusTests(unittest.TestCase):
    def test_internal_error_with_all_tasks_success_is_success(self):
        self.assertEqual(d._effective_status("INTERNAL_ERROR", "FAILED", ["SUCCESS", "SUCCESS"]), "success")

    def test_running_lifecycle(self):
        self.assertEqual(d._effective_status("RUNNING", "", []), "running")
        self.assertEqual(d._effective_status("PENDING", "", []), "running")

    def test_terminated_success(self):
        self.assertEqual(d._effective_status("TERMINATED", "SUCCESS", ["SUCCESS"]), "success")

    def test_genuine_failure(self):
        self.assertEqual(d._effective_status("TERMINATED", "FAILED", ["FAILED", "SUCCESS"]), "failed")

    def test_extract_run_id_from_response(self):
        waiter = types.SimpleNamespace(response=types.SimpleNamespace(run_id=777), run_id=None)
        self.assertEqual(d._extract_run_id(waiter), 777)

    def test_extract_run_id_from_bind(self):
        # No run_id attribute and no response — extraction falls back to bind().
        waiter = types.SimpleNamespace(response=None, bind=lambda: {"run_id": "888"})
        self.assertEqual(d._extract_run_id(waiter), 888)


class TriggerTests(unittest.TestCase):
    def test_trigger_uses_obo_client_and_extracts_run_id(self):
        calls = {}

        class FakeJobs:
            def run_now(self, **kwargs):
                calls.update(kwargs)
                return types.SimpleNamespace(run_id=555, response=None)

        uc = FakeUC(w=types.SimpleNamespace(jobs=FakeJobs()))
        result = d.trigger_run(_cfg(), uc, execution_job_id=11, idempotency_token="tok-1")
        self.assertEqual(calls["job_id"], 11)
        self.assertEqual(calls["idempotency_token"], "tok-1")
        self.assertEqual(result["runId"], 555)
        self.assertEqual(result["jobId"], 11)
        self.assertIn("/jobs/11/runs/555", result["runPageUrl"])


class GenieOverrideTests(unittest.TestCase):
    def test_start_genie_honors_space_override_without_ax_provider(self):
        recorded = {}

        class FakeGenie:
            def start_conversation(self, space_id, content):
                recorded["space_id"] = space_id
                recorded["content"] = content
                return types.SimpleNamespace(
                    response=types.SimpleNamespace(
                        conversation_id="c1",
                        message_id="m1",
                        message=types.SimpleNamespace(status="SUBMITTED"),
                    ),
                    bind=lambda: {"conversation_id": "c1", "message_id": "m1"},
                )

        class FakeW:
            genie = FakeGenie()

        # GA's own Genie is NOT configured (provider defaults to "local"); the
        # override must still work.
        out = genie_service.start_genie(
            config=_cfg(), question="How is trust trending?", client=FakeW(), space_id="dp-space-9"
        )
        self.assertEqual(recorded["space_id"], "dp-space-9")
        self.assertEqual(out["conversationId"], "c1")
        self.assertEqual(out["messageId"], "m1")


class CapabilityFlagTests(unittest.TestCase):
    def test_emet_flag_reflects_detection_state(self):
        available = capability_service.bootstrap_capabilities(
            actor_role="reader", authenticated=True, runtime_state="live", store_state="live",
            emet_state="available", emet_reason="ok",
        )
        self.assertTrue(available["emet"]["available"])
        self.assertEqual(available["emet"]["state"], "available")

        absent = capability_service.bootstrap_capabilities(
            actor_role="reader", authenticated=True, runtime_state="live", store_state="live",
            emet_state="absent", emet_reason="not installed",
        )
        self.assertFalse(absent["emet"]["available"])
        self.assertEqual(absent["emet"]["state"], "unavailable")

        unknown = capability_service.bootstrap_capabilities(
            actor_role="reader", authenticated=True, runtime_state="live", store_state="live",
        )
        self.assertEqual(unknown["emet"]["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
