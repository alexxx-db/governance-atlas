from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import os
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from atlas.services import assets as asset_service
from atlas.util import lineage_window_predicate, sql_literal


QUALITY_MONITORING_SOURCE = "system.data_quality_monitoring.table_results"
PROFILE_METRICS_SOURCE = "system.information_schema.tables"
LAKEFLOW_SOURCE = "system.lakeflow"
PIPELINE_EVENT_LOG_SOURCE = "event_log"


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    first_line = text.splitlines()[0].strip()
    return first_line[:500]


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(inner) for inner in value]
    return value


def _records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    rows: List[Dict[str, Any]] = []
    for _, row in frame.iterrows():
        rows.append({str(key): _json_safe(value) for key, value in row.to_dict().items()})
    return rows


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _obj_get(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


def _monitor_metric_table_names(uc: Any, asset_fqn: str) -> tuple[list[str], dict[str, Any], str]:
    if str(os.getenv("GOVAT_ENABLE_DATABRICKS_MONITOR_API", "")).strip().lower() not in {"1", "true", "yes"}:
        return (
            [],
            {},
            "Databricks profiling monitor API lookup is not enabled for this app deployment; using actor-visible metric-table discovery.",
        )
    workspace = getattr(uc, "w", None)
    tables_api = getattr(workspace, "tables", None)
    data_quality_api = getattr(workspace, "data_quality", None)
    if not tables_api or not data_quality_api:
        return [], {}, "Databricks data_quality monitor API is unavailable on this runtime client."
    try:
        table_obj = tables_api.get(full_name=asset_fqn)
        table_id = _obj_get(table_obj, "table_id")
        if not table_id:
            return [], {}, "Databricks table id was not returned for monitor lookup."
        monitor = data_quality_api.get_monitor(object_type="table", object_id=table_id)
        profiling = _obj_get(monitor, "data_profiling_config")
        if not profiling:
            return [], {"tableId": table_id, "configured": False}, "No Databricks data profiling monitor is configured for this table."
        profile_name = _obj_get(profiling, "profile_metrics_table_name")
        drift_name = _obj_get(profiling, "drift_metrics_table_name")
        names = [str(name).strip() for name in (profile_name, drift_name) if str(name or "").strip()]
        monitor_info = {
            "tableId": table_id,
            "configured": True,
            "monitorVersion": _obj_get(profiling, "monitor_version"),
            "status": str(_obj_get(profiling, "status") or "").strip(),
            "profileMetricsTableName": profile_name,
            "driftMetricsTableName": drift_name,
            "dashboardId": _obj_get(profiling, "dashboard_id"),
            "warehouseId": _obj_get(profiling, "warehouse_id") or _obj_get(profiling, "effective_warehouse_id"),
            "latestMonitorFailureMessage": _obj_get(profiling, "latest_monitor_failure_message"),
        }
        return names, monitor_info, ""
    except Exception as exc:
        return [], {}, _safe_error(exc)


def _state_for_rows(rows: Sequence[Dict[str, Any]], *, empty: str = "empty") -> str:
    return "available" if rows else empty


def _unavailable(source: str, warning: str) -> Dict[str, Any]:
    return {
        "state": "unavailable",
        "source": source,
        "rows": [],
        "warnings": [warning] if warning else [],
    }


def quality_monitoring_payload(uc: Any, asset_fqn: str, *, limit: int = 8) -> Dict[str, Any]:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    query = f"""
SELECT
  event_time,
  catalog_name,
  schema_name,
  table_name,
  status,
  freshness.status AS freshness_status,
  freshness.commit_freshness.status AS commit_freshness_status,
  freshness.commit_freshness.last_value AS last_commit_time,
  freshness.commit_freshness.predicted_value AS predicted_commit_time,
  completeness.status AS completeness_status,
  completeness.total_row_count.status AS total_row_count_status,
  completeness.total_row_count.last_value AS total_row_count,
  completeness.total_row_count.min_predicted_value AS min_predicted_row_count,
  completeness.total_row_count.max_predicted_value AS max_predicted_row_count,
  completeness.daily_row_count.status AS daily_row_count_status,
  completeness.daily_row_count.last_value AS daily_row_count,
  downstream_impact.impact_level AS downstream_impact_level,
  downstream_impact.num_downstream_tables AS downstream_table_count,
  downstream_impact.num_queries_on_affected_tables AS downstream_query_count,
  root_cause_analysis.upstream_jobs AS upstream_jobs
FROM system.data_quality_monitoring.table_results
WHERE catalog_name = {sql_literal(catalog)}
  AND schema_name = {sql_literal(schema)}
  AND table_name = {sql_literal(table)}
ORDER BY event_time DESC
LIMIT {max(1, min(int(limit), 25))}
"""
    try:
        rows = _records(uc.query_df(query, timeout_s=6))
    except TypeError:
        try:
            rows = _records(uc.query_df(query))
        except Exception as exc:
            return {
                **_unavailable(QUALITY_MONITORING_SOURCE, _safe_error(exc)),
                "summary": {
                    "healthStatus": "Unavailable",
                    "latestEventTime": None,
                    "freshnessStatus": "Unavailable",
                    "completenessStatus": "Unavailable",
                },
            }
    except Exception as exc:
        return {
            **_unavailable(QUALITY_MONITORING_SOURCE, _safe_error(exc)),
            "summary": {
                "healthStatus": "Unavailable",
                "latestEventTime": None,
                "freshnessStatus": "Unavailable",
                "completenessStatus": "Unavailable",
            },
        }
    latest = rows[0] if rows else {}
    summary = {
        "healthStatus": latest.get("status") or ("Not monitored" if not rows else "Unknown"),
        "latestEventTime": latest.get("event_time"),
        "freshnessStatus": latest.get("freshness_status") or "Unavailable",
        "completenessStatus": latest.get("completeness_status") or "Unavailable",
        "downstreamImpactLevel": _as_int(latest.get("downstream_impact_level")),
        "downstreamTableCount": _as_int(latest.get("downstream_table_count")),
        "downstreamQueryCount": _as_int(latest.get("downstream_query_count")),
        "upstreamJobCount": len(latest.get("upstream_jobs") or []) if isinstance(latest.get("upstream_jobs"), list) else None,
    }
    warnings = [] if rows else ["No Databricks data quality monitoring result rows were returned for this table."]
    return {
        "state": _state_for_rows(rows),
        "source": QUALITY_MONITORING_SOURCE,
        "rows": rows,
        "summary": summary,
        "warnings": warnings,
    }


def profile_metric_tables_payload(uc: Any, asset_fqn: str) -> Dict[str, Any]:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    monitor_names, monitor_info, monitor_warning = _monitor_metric_table_names(uc, asset_fqn)
    profile_table = f"{table}_profile_metrics".lower()
    drift_table = f"{table}_drift_metrics".lower()
    predicates: List[str] = []
    for table_name in monitor_names:
        try:
            metric_catalog, metric_schema, metric_table = asset_service.split_uc_name(table_name)
        except ValueError:
            continue
        predicates.append(
            "("
            f"table_catalog = {sql_literal(metric_catalog)} "
            f"AND table_schema = {sql_literal(metric_schema)} "
            f"AND table_name = {sql_literal(metric_table)}"
            ")"
        )
    if not predicates:
        predicates.append(
            "("
            f"table_catalog = {sql_literal(catalog)} "
            f"AND table_schema = {sql_literal(schema)} "
            f"AND lower(table_name) IN ({sql_literal(profile_table)}, {sql_literal(drift_table)})"
            ")"
        )
    query = f"""
SELECT
  table_catalog,
  table_schema,
  table_name,
  table_type,
  table_owner,
  created,
  last_altered
FROM system.information_schema.tables
WHERE {" OR ".join(predicates)}
ORDER BY table_name
LIMIT 10
"""
    try:
            rows = _records(uc.query_df(query, timeout_s=6))
    except TypeError:
        try:
            rows = _records(uc.query_df(query))
        except Exception as exc:
            return _unavailable(PROFILE_METRICS_SOURCE, _safe_error(exc))
    except Exception as exc:
        return _unavailable(PROFILE_METRICS_SOURCE, _safe_error(exc))
    configured_monitor = bool(monitor_info.get("configured") is True)
    discovered_by_monitor = configured_monitor or bool(monitor_names)
    state = "available" if rows or discovered_by_monitor else "empty"
    warnings = []
    if monitor_warning:
        warnings.append(monitor_warning)
    if not rows and not discovered_by_monitor:
        warnings.append(
            "No Databricks profile/drift metric tables matching the documented default names were found in this asset schema."
        )
    if configured_monitor and not rows:
        warnings.append(
            "A Databricks data profiling monitor was found, but its metric tables were not visible through system.information_schema for this actor."
        )
    return {
        "state": state,
        "source": PROFILE_METRICS_SOURCE,
        "rows": rows,
        "monitor": monitor_info,
        "summary": {
            "profileMetricTables": sum(
                1
                for row in rows
                if str(row.get("table_name") or "").lower() == profile_table
                or str(row.get("table_name") or "").lower() == str(monitor_info.get("profileMetricsTableName") or "").rsplit(".", 1)[-1].lower()
            ),
            "driftMetricTables": sum(
                1
                for row in rows
                if str(row.get("table_name") or "").lower() == drift_table
                or str(row.get("table_name") or "").lower() == str(monitor_info.get("driftMetricsTableName") or "").rsplit(".", 1)[-1].lower()
            ),
            "checkedSchema": f"{catalog}.{schema}",
            "lookupMethod": "data_quality.get_monitor" if discovered_by_monitor else "default-name-discovery",
        },
        "warnings": warnings,
    }


def lakeflow_payload(uc: Any, asset_fqn: str, *, limit: int = 12) -> Dict[str, Any]:
    catalog, schema, table = asset_service.split_uc_name(asset_fqn)
    relation_predicate = f"""
(
  source_table_catalog = {sql_literal(catalog)}
  AND source_table_schema = {sql_literal(schema)}
  AND source_table_name = {sql_literal(table)}
) OR (
  target_table_catalog = {sql_literal(catalog)}
  AND target_table_schema = {sql_literal(schema)}
  AND target_table_name = {sql_literal(table)}
)
"""
    workload_lineage_query = f"""
SELECT
  lower(CAST(entity_type AS STRING)) AS entity_type,
  CAST(entity_id AS STRING) AS workload_id,
  CAST(entity_run_id AS STRING) AS run_id,
  CAST(statement_id AS STRING) AS statement_id,
  max(event_time) AS last_lineage_event,
  count(*) AS lineage_event_count
FROM system.access.table_lineage
WHERE {lineage_window_predicate()}
  AND ({relation_predicate})
  AND lower(CAST(entity_type AS STRING)) IN ('job', 'workflow', 'pipeline', 'dlt_pipeline', 'lakeflow_pipeline')
  AND entity_id IS NOT NULL
GROUP BY ALL
ORDER BY last_lineage_event DESC
LIMIT {max(1, min(int(limit), 25))}
"""
    warnings: List[str] = []
    try:
        workloads = _records(uc.query_df(workload_lineage_query, timeout_s=6))
    except TypeError:
        try:
            workloads = _records(uc.query_df(workload_lineage_query))
        except Exception as exc:
            workloads = []
            warnings.append(f"Lakeflow workload lineage unavailable: {_safe_error(exc)}")
    except Exception as exc:
        workloads = []
        warnings.append(f"Lakeflow workload lineage unavailable: {_safe_error(exc)}")
    jobs = [
        {**row, "job_id": row.get("workload_id")}
        for row in workloads
        if str(row.get("entity_type") or "").lower() in {"job", "workflow"}
    ]
    pipelines = [
        {**row, "pipeline_id": row.get("workload_id"), "update_id": row.get("run_id")}
        for row in workloads
        if str(row.get("entity_type") or "").lower() in {"pipeline", "dlt_pipeline", "lakeflow_pipeline"}
    ]
    if jobs:
        job_ids = sorted({str(row.get("job_id") or "").strip() for row in jobs if row.get("job_id")})
        run_ids = sorted({str(row.get("run_id") or "").strip() for row in jobs if row.get("run_id")})
        run_predicate = ""
        task_run_predicate = ""
        if run_ids:
            run_predicate = "AND CAST(run_id AS STRING) IN (" + ", ".join(sql_literal(value) for value in run_ids) + ")"
            task_run_predicate = (
                "AND CAST(job_run_id AS STRING) IN (" + ", ".join(sql_literal(value) for value in run_ids) + ")"
            )
        job_enrichment_query = f"""
WITH latest_jobs AS (
  SELECT
    workspace_id,
    CAST(job_id AS STRING) AS job_id,
    name AS job_name,
    run_as_user_name,
    creator_user_name,
    trigger_type,
    change_time,
    ROW_NUMBER() OVER (PARTITION BY workspace_id, job_id ORDER BY change_time DESC) AS rn
  FROM system.lakeflow.jobs
  WHERE CAST(job_id AS STRING) IN ({", ".join(sql_literal(value) for value in job_ids)})
  QUALIFY rn = 1
),
task_rollup AS (
  SELECT
    CAST(job_id AS STRING) AS job_id,
    CAST(job_run_id AS STRING) AS run_id,
    count(DISTINCT CAST(run_id AS STRING)) AS task_run_count,
    sum(CASE WHEN result_state IS NOT NULL AND upper(result_state) NOT IN ('SUCCESS', 'SUCCEEDED') THEN 1 ELSE 0 END) AS non_success_task_runs
  FROM system.lakeflow.job_task_run_timeline
  WHERE CAST(job_id AS STRING) IN ({", ".join(sql_literal(value) for value in job_ids)})
    {task_run_predicate}
  GROUP BY ALL
)
SELECT
  jr.workspace_id,
  CAST(jr.job_id AS STRING) AS job_id,
  CAST(jr.run_id AS STRING) AS run_id,
  lj.job_name,
  lj.run_as_user_name,
  lj.creator_user_name,
  coalesce(jr.trigger_type, lj.trigger_type) AS trigger_type,
  jr.result_state,
  jr.run_type,
  jr.period_start_time,
  jr.period_end_time,
  jr.run_duration_seconds,
  tr.task_run_count,
  tr.non_success_task_runs
FROM system.lakeflow.job_run_timeline jr
LEFT JOIN latest_jobs lj
  ON lj.workspace_id = jr.workspace_id
 AND lj.job_id = CAST(jr.job_id AS STRING)
LEFT JOIN task_rollup tr
  ON tr.job_id = CAST(jr.job_id AS STRING)
 AND tr.run_id = CAST(jr.run_id AS STRING)
WHERE CAST(jr.job_id AS STRING) IN ({", ".join(sql_literal(value) for value in job_ids)})
  {run_predicate}
ORDER BY jr.period_start_time DESC
LIMIT {max(1, min(int(limit), 25))}
"""
        try:
            job_rows = _records(uc.query_df(job_enrichment_query, timeout_s=6))
        except TypeError:
            try:
                job_rows = _records(uc.query_df(job_enrichment_query))
            except Exception as exc:
                job_rows = []
                warnings.append(f"Lakeflow job run enrichment unavailable: {_safe_error(exc)}")
        except Exception as exc:
            job_rows = []
            warnings.append(f"Lakeflow job run enrichment unavailable: {_safe_error(exc)}")
        jobs_by_key = {
            (str(row.get("job_id") or ""), str(row.get("run_id") or "")): row for row in job_rows
        }
        jobs_by_job = {str(row.get("job_id") or ""): row for row in job_rows}
        jobs = [
            {
                **row,
                **(
                    jobs_by_key.get((str(row.get("job_id") or ""), str(row.get("run_id") or "")))
                    or jobs_by_job.get(str(row.get("job_id") or ""))
                    or {}
                ),
            }
            for row in jobs
        ]
    if pipelines:
        pipeline_ids = sorted({str(row.get("pipeline_id") or "").strip() for row in pipelines if row.get("pipeline_id")})
        update_ids = sorted({str(row.get("update_id") or "").strip() for row in pipelines if row.get("update_id")})
        update_predicate = ""
        if update_ids:
            update_predicate = "AND CAST(update_id AS STRING) IN (" + ", ".join(sql_literal(value) for value in update_ids) + ")"
        enrichment_query = f"""
SELECT
  workspace_id,
  CAST(pipeline_id AS STRING) AS pipeline_id,
  CAST(update_id AS STRING) AS update_id,
  result_state,
  trigger_type,
  update_type,
  run_as_user_name,
  period_start_time,
  period_end_time,
  refresh_selection,
  full_refresh_selection
FROM system.lakeflow.pipeline_update_timeline
WHERE CAST(pipeline_id AS STRING) IN ({", ".join(sql_literal(value) for value in pipeline_ids)})
  {update_predicate}
ORDER BY period_start_time DESC
LIMIT {max(1, min(int(limit), 25))}
"""
        try:
            update_rows = _records(uc.query_df(enrichment_query, timeout_s=6))
        except TypeError:
            try:
                update_rows = _records(uc.query_df(enrichment_query))
            except Exception as exc:
                update_rows = []
                warnings.append(f"Lakeflow pipeline update enrichment unavailable: {_safe_error(exc)}")
        except Exception as exc:
            update_rows = []
            warnings.append(f"Lakeflow pipeline update enrichment unavailable: {_safe_error(exc)}")
        updates_by_key = {
            (str(row.get("pipeline_id") or ""), str(row.get("update_id") or "")): row for row in update_rows
        }
        updates_by_pipeline = {str(row.get("pipeline_id") or ""): row for row in update_rows}
        pipelines = [
            {
                **row,
                **(
                    updates_by_key.get((str(row.get("pipeline_id") or ""), str(row.get("update_id") or "")))
                    or updates_by_pipeline.get(str(row.get("pipeline_id") or ""))
                    or {}
                ),
            }
            for row in pipelines
        ]
    state = "available" if jobs or pipelines else ("unavailable" if warnings else "empty")
    return {
        "state": state,
        "source": LAKEFLOW_SOURCE,
        "jobs": jobs,
        "pipelines": pipelines,
        "summary": {
            "jobRunCount": len(jobs),
            "pipelineUpdateCount": len(pipelines),
            "failedJobRuns": sum(1 for row in jobs if str(row.get("result_state") or "").upper() not in {"", "SUCCESS", "SUCCEEDED"}),
            "failedPipelineUpdates": sum(1 for row in pipelines if str(row.get("result_state") or "").upper() not in {"", "SUCCESS", "SUCCEEDED"}),
        },
        "warnings": warnings if warnings else ([] if jobs or pipelines else ["No Lakeflow job or pipeline rows were joinable from this asset's Unity Catalog lineage."]),
    }


def pipeline_event_log_payload(
    uc: Any,
    pipeline_ids: Iterable[str],
    *,
    limit_per_pipeline: int = 5,
) -> Dict[str, Any]:
    clean_ids: List[str] = []
    for pipeline_id in pipeline_ids:
        text = str(pipeline_id or "").strip()
        if text and text not in clean_ids:
            clean_ids.append(text)
    clean_ids = clean_ids[:3]
    if not clean_ids:
        return {
            "state": "empty",
            "source": PIPELINE_EVENT_LOG_SOURCE,
            "rows": [],
            "warnings": ["No pipeline ids were returned from Unity Catalog lineage for event_log lookup."],
        }
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for pipeline_id in clean_ids:
        query = f"""
SELECT
  {sql_literal(pipeline_id)} AS pipeline_id,
  timestamp,
  level,
  event_type,
  message,
  CAST(details:flow_progress.data_quality.expectations AS STRING) AS expectations,
  CAST(details:flow_progress.data_quality.dropped_records AS STRING) AS dropped_records,
  CAST(details:update_progress.state AS STRING) AS update_state
FROM event_log({sql_literal(pipeline_id)})
WHERE event_type IN ('flow_progress', 'update_progress')
ORDER BY timestamp DESC
LIMIT {max(1, min(int(limit_per_pipeline), 10))}
"""
        try:
            rows.extend(_records(uc.query_df(query, timeout_s=6)))
        except TypeError:
            try:
                rows.extend(_records(uc.query_df(query)))
            except Exception as exc:
                warnings.append(f"{pipeline_id}: {_safe_error(exc)}")
        except Exception as exc:
            warnings.append(f"{pipeline_id}: {_safe_error(exc)}")
    return {
        "state": "available" if rows else ("unavailable" if warnings else "empty"),
        "source": PIPELINE_EVENT_LOG_SOURCE,
        "rows": rows,
        "warnings": warnings if warnings else ([] if rows else ["No pipeline event-log rows returned."]),
    }


def asset_databricks_evidence_payload(uc: Any, asset_fqn: str) -> Dict[str, Any]:
    normalized = asset_service.normalize_str(asset_fqn)
    with ThreadPoolExecutor(max_workers=3) as pool:
        quality_future = pool.submit(quality_monitoring_payload, uc, normalized)
        profile_future = pool.submit(profile_metric_tables_payload, uc, normalized)
        lakeflow_future = pool.submit(lakeflow_payload, uc, normalized)
        quality = quality_future.result()
        profile = profile_future.result()
        lakeflow = lakeflow_future.result()
    pipeline_ids = [row.get("pipeline_id") for row in lakeflow.get("pipelines") or []]
    pipeline_events = pipeline_event_log_payload(uc, pipeline_ids)
    return {
        "assetFqn": normalized,
        "qualityMonitoring": quality,
        "profileMetrics": profile,
        "lakeflow": lakeflow,
        "pipelineEvents": pipeline_events,
        "provenance": [
            QUALITY_MONITORING_SOURCE,
            PROFILE_METRICS_SOURCE,
            "system.access.table_lineage",
            "system.lakeflow.jobs",
            "system.lakeflow.job_run_timeline",
            "system.lakeflow.job_task_run_timeline",
            "system.lakeflow.pipeline_update_timeline",
            PIPELINE_EVENT_LOG_SOURCE,
        ],
    }
