from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from axiom.services import databricks_evidence


class FakeUC:
    def __init__(self, frames: dict[str, pd.DataFrame] | None = None, failures: dict[str, Exception] | None = None):
        self.frames = frames or {}
        self.failures = failures or {}
        self.queries: list[str] = []
        self.w = SimpleNamespace(tables=None, data_quality=None)

    def query_df(self, statement: str, **_kwargs):
        self.queries.append(statement)
        for marker, exc in self.failures.items():
            if marker in statement:
                raise exc
        for marker, frame in self.frames.items():
            if marker in statement:
                return frame
        return pd.DataFrame()


def test_quality_monitoring_payload_uses_system_table_without_synthetic_zeroes() -> None:
    uc = FakeUC(
        {
            "system.data_quality_monitoring.table_results": pd.DataFrame(
                [
                    {
                        "event_time": pd.Timestamp("2026-05-05T01:02:03Z"),
                        "status": "Healthy",
                        "freshness_status": "Healthy",
                        "completeness_status": "Healthy",
                        "downstream_impact_level": "2",
                        "downstream_table_count": "7",
                        "downstream_query_count": "34",
                        "upstream_jobs": [{"job_id": "123"}],
                    }
                ]
            )
        }
    )

    payload = databricks_evidence.quality_monitoring_payload(uc, "main.sales.orders")

    assert payload["state"] == "available"
    assert payload["source"] == "system.data_quality_monitoring.table_results"
    assert payload["summary"]["healthStatus"] == "Healthy"
    assert payload["summary"]["downstreamTableCount"] == 7
    assert payload["summary"]["upstreamJobCount"] == 1
    assert "catalog_name = 'main'" in uc.queries[0]
    assert "schema_name = 'sales'" in uc.queries[0]
    assert "table_name = 'orders'" in uc.queries[0]


def test_quality_monitoring_empty_is_not_reported_as_healthy_zero() -> None:
    payload = databricks_evidence.quality_monitoring_payload(FakeUC(), "main.sales.orders")

    assert payload["state"] == "empty"
    assert payload["summary"]["healthStatus"] == "Not monitored"
    assert payload["summary"]["downstreamTableCount"] is None
    assert payload["rows"] == []
    assert "No Databricks data quality monitoring result rows" in payload["warnings"][0]


def test_lakeflow_payload_keeps_partial_job_evidence_when_pipeline_table_denied() -> None:
    uc = FakeUC(
        frames={
            "lower(CAST(entity_type AS STRING)) IN ('job', 'workflow', 'pipeline', 'dlt_pipeline', 'lakeflow_pipeline')": pd.DataFrame(
                [
                    {
                        "entity_type": "job",
                        "workload_id": "557",
                        "run_id": "999",
                        "last_lineage_event": "2026-05-05T01:00:00Z",
                        "lineage_event_count": 3,
                    },
                    {
                        "entity_type": "pipeline",
                        "workload_id": "pipe-1",
                        "run_id": "update-1",
                        "last_lineage_event": "2026-05-05T01:00:00Z",
                        "lineage_event_count": 2,
                    }
                ]
            ),
            "system.lakeflow.job_run_timeline": pd.DataFrame(
                [
                    {
                        "entity_type": "job",
                        "job_id": "557",
                        "run_id": "999",
                        "job_name": "daily mortgage refresh",
                        "result_state": "SUCCESS",
                        "last_lineage_event": "2026-05-05T01:00:00Z",
                    }
                ]
            ),
        },
        failures={"system.lakeflow.pipeline_update_timeline": RuntimeError("INSUFFICIENT_PERMISSIONS")},
    )

    payload = databricks_evidence.lakeflow_payload(uc, "main.sales.orders")

    assert payload["state"] == "available"
    assert payload["summary"]["jobRunCount"] == 1
    assert payload["summary"]["pipelineUpdateCount"] == 1
    assert payload["jobs"][0]["job_name"] == "daily mortgage refresh"
    assert payload["pipelines"][0]["pipeline_id"] == "pipe-1"
    assert "pipeline update enrichment unavailable" in payload["warnings"][0].lower()


def test_lakeflow_payload_does_not_probe_pipeline_update_table_without_pipeline_lineage() -> None:
    uc = FakeUC()

    payload = databricks_evidence.lakeflow_payload(uc, "main.sales.orders")

    assert payload["state"] == "empty"
    assert payload["jobs"] == []
    assert payload["pipelines"] == []
    assert not any("system.lakeflow.pipeline_update_timeline" in query for query in uc.queries)


def test_profile_metric_payload_prefers_monitor_table_names_when_available(monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_ENABLE_DATABRICKS_MONITOR_API", "true")

    class Tables:
        def get(self, *, full_name: str):
            assert full_name == "main.sales.orders"
            return SimpleNamespace(table_id="table-1")

    class DataQuality:
        def get_monitor(self, *, object_type: str, object_id: str):
            assert object_type == "table"
            assert object_id == "table-1"
            return SimpleNamespace(
                data_profiling_config=SimpleNamespace(
                    profile_metrics_table_name="monitoring.out.orders_profile_metrics",
                    drift_metrics_table_name="monitoring.out.orders_drift_metrics",
                    monitor_version=3,
                    status="ACTIVE",
                )
            )

    uc = FakeUC(
        {
            "system.information_schema.tables": pd.DataFrame(
                [
                    {
                        "table_catalog": "monitoring",
                        "table_schema": "out",
                        "table_name": "orders_profile_metrics",
                        "table_type": "MANAGED",
                    }
                ]
            )
        }
    )
    uc.w = SimpleNamespace(tables=Tables(), data_quality=DataQuality())

    payload = databricks_evidence.profile_metric_tables_payload(uc, "main.sales.orders")

    assert payload["state"] == "available"
    assert payload["summary"]["lookupMethod"] == "data_quality.get_monitor"
    assert payload["monitor"]["monitorVersion"] == 3
    assert "table_catalog = 'monitoring'" in uc.queries[0]


def test_profile_metric_payload_skips_monitor_api_by_default() -> None:
    class ExplodingTables:
        def get(self, **_kwargs):
            raise AssertionError("monitor API should not be called by default")

    uc = FakeUC()
    uc.w = SimpleNamespace(tables=ExplodingTables(), data_quality=object())

    payload = databricks_evidence.profile_metric_tables_payload(uc, "main.sales.orders")

    assert payload["state"] == "empty"
    assert payload["summary"]["lookupMethod"] == "default-name-discovery"
    assert "not enabled" in payload["warnings"][0]


def test_profile_metric_payload_does_not_mark_table_id_only_monitor_available(monkeypatch) -> None:
    monkeypatch.setenv("AXIOM_ENABLE_DATABRICKS_MONITOR_API", "true")

    class Tables:
        def get(self, *, full_name: str):
            return SimpleNamespace(table_id="table-1")

    class DataQuality:
        def get_monitor(self, *, object_type: str, object_id: str):
            return SimpleNamespace(data_profiling_config=None)

    uc = FakeUC()
    uc.w = SimpleNamespace(tables=Tables(), data_quality=DataQuality())

    payload = databricks_evidence.profile_metric_tables_payload(uc, "main.sales.orders")

    assert payload["state"] == "empty"
    assert payload["monitor"]["configured"] is False
    assert payload["summary"]["lookupMethod"] == "default-name-discovery"
