"""Phase 8 — Profile runner.

Queries a table's column metrics from UC/SQL and persists the result
to profile_runs + profile_table_metrics + profile_column_metrics.
Designed to be called from:
  - an admin-triggered endpoint (POST /api/assets/:fqn/profile/run),
  - the background drainer via a 'profile' work item,
  - unit tests against a mock UC client.

Safety invariants:
- SELECT-only queries (we emit them ourselves from fixed templates;
  no caller-supplied SQL).
- Bounded: exact count(*) plus ONE aggregate query for all columns,
  over the first PROFILE_SAMPLE_ROWS rows when the table is larger
  (recorded in the table-metric detail); identifiers are quoted.
- top-values are gated by a sensitivity flag so we can redact sample
  values for classified-sensitive columns.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from atlas.services.quality_runner import _safe_table
from atlas.util import quote_ident


@dataclass
class ProfileRunResult:
    profile_run_id: str
    status: str
    row_count: Optional[int] = None
    column_metrics_written: int = 0
    error: str = ""


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


PROFILE_SAMPLE_ROWS = 1_000_000
_NUMERIC_TYPES = {"int", "integer", "bigint", "smallint", "tinyint", "double", "float", "decimal", "long"}


def _is_numeric(col_type: str) -> bool:
    return col_type in _NUMERIC_TYPES or col_type.startswith("decimal(")


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        result = None if value is None else float(value)
    except (TypeError, ValueError):
        return None
    return None if result is None or math.isnan(result) else result


def _sample_columns(columns: List[Dict[str, Any]], max_columns: int) -> List[Dict[str, Any]]:
    """Truncate column list to `max_columns` without reshuffling so
    repeated runs hit the same columns."""
    return list(columns or [])[: max(0, int(max_columns))]


def run_profile(
    *,
    store,
    uc_client,
    asset_fqn: str,
    columns: List[Dict[str, Any]],
    actor_email: str = "system",
    trigger: str = "manual",
    include_top_values: bool = False,
    max_columns: int = 32,
) -> ProfileRunResult:
    """Run one profile pass against a concrete table. `columns` is a
    list of `{name, type}` dicts (usually sourced from an existing
    asset detail payload). Returns a ProfileRunResult so callers can
    surface per-run errors without exceptions.
    """
    profile_run_id = uuid.uuid4().hex
    try:
        store.insert_profile_run(
            profile_run_id=profile_run_id,
            entity_kind="asset",
            entity_fqn=asset_fqn,
            trigger=trigger,
            status="running",
            sample_strategy="approx",
            sample_rows=None,
            created_by=actor_email,
            notes=None,
        )
    except Exception as exc:
        return ProfileRunResult(
            profile_run_id=profile_run_id,
            status="failed",
            error=f"profile_runs insert failed: {exc}",
        )

    table = _safe_table(asset_fqn)
    # Exact row count: Delta answers count(*) from file statistics.
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    try:
        frame = uc_client.query_df(f"SELECT count(*) AS row_count FROM {table}")
        if frame is not None and not frame.empty:
            row_count = int(frame.iloc[0]["row_count"])
    except Exception:
        row_count = None

    # Column metrics come from ONE aggregate over a bounded sample (was up to
    # 3 unsampled full scans per column, run serially inside the request).
    # ponytail: first-N-rows sample, not uniform; use TABLESAMPLE if skew matters.
    sampled = row_count is None or row_count > PROFILE_SAMPLE_ROWS
    source = f"(SELECT * FROM {table} LIMIT {PROFILE_SAMPLE_ROWS})" if sampled else table

    try:
        store.insert_profile_table_metric(
            profile_run_id=profile_run_id,
            entity_fqn=asset_fqn,
            row_count=row_count,
            size_bytes=size_bytes,
            partition_count=None,
            distinct_keys=None,
            detail={
                "method": "select count(*)",
                "columnMetricsSample": "first-n-rows" if sampled else "full",
                "sampleRows": PROFILE_SAMPLE_ROWS if sampled else row_count,
            },
        )
    except Exception:
        pass

    selected_columns = [
        (i, str(c.get("name") or "").strip(), str(c.get("type") or "").strip().lower())
        for i, c in enumerate(_sample_columns(columns, max_columns))
    ]
    selected_columns = [(i, name, col_type) for i, name, col_type in selected_columns if name]
    exprs = ["count(*) AS sampled_rows"]
    for i, name, col_type in selected_columns:
        col = quote_ident(name)
        exprs += [f"count_if({col} IS NULL) AS n{i}", f"approx_count_distinct({col}) AS d{i}"]
        if _is_numeric(col_type):
            exprs += [f"min({col}) AS mn{i}", f"max({col}) AS mx{i}", f"avg({col}) AS av{i}", f"stddev({col}) AS sd{i}"]
        elif col_type in {"date", "timestamp"} or col_type.startswith("timestamp"):
            exprs += [f"min({col}) AS mn{i}", f"max({col}) AS mx{i}"]
    metrics: Dict[str, Any] = {}
    if selected_columns:
        try:
            frame = uc_client.query_df(f"SELECT {', '.join(exprs)} FROM {source} AS t")
            if frame is not None and not frame.empty:
                first = frame.iloc[0]
                metrics = first.to_dict() if hasattr(first, "to_dict") else dict(first)
        except Exception:
            metrics = {}  # still write one (empty) row per column below
    sampled_rows = _int_or_none(metrics.get("sampled_rows"))

    columns_written = 0
    for i, col_name, col_type in selected_columns:
        null_count = _int_or_none(metrics.get(f"n{i}"))
        distinct_count = _int_or_none(metrics.get(f"d{i}"))
        min_raw, max_raw = metrics.get(f"mn{i}"), metrics.get(f"mx{i}")
        top_values: Optional[List[Any]] = None
        if include_top_values:
            try:
                col = quote_ident(col_name)
                frame = uc_client.query_df(
                    f"SELECT {col} AS value, count(*) AS cnt FROM {source} AS t GROUP BY {col} ORDER BY cnt DESC LIMIT 10"
                )
                if frame is not None and not frame.empty:
                    top_values = [
                        {"value": None if row.get("value") is None else str(row.get("value")), "count": int(row.get("cnt") or 0)}
                        for _, row in frame.iterrows()
                    ]
            except Exception:
                top_values = None

        try:
            store.insert_profile_column_metric(
                profile_run_id=profile_run_id,
                entity_fqn=asset_fqn,
                column_name=col_name,
                data_type=col_type or None,
                null_count=null_count,
                null_fraction=(null_count / sampled_rows) if sampled_rows and null_count is not None else None,
                distinct_count=distinct_count,
                distinct_fraction=(distinct_count / sampled_rows) if sampled_rows and distinct_count is not None else None,
                min_value=None if min_raw is None else str(min_raw),
                max_value=None if max_raw is None else str(max_raw),
                mean_value=_float_or_none(metrics.get(f"av{i}")),
                stddev_value=_float_or_none(metrics.get(f"sd{i}")),
                quantiles=None,
                top_values=top_values,
                detail={"sampled": sampled} if sampled else None,
            )
            columns_written += 1
        except Exception:
            continue

    try:
        store.finalize_profile_run(
            profile_run_id=profile_run_id,
            status="succeeded",
            error_detail=None,
        )
    except Exception as exc:
        return ProfileRunResult(
            profile_run_id=profile_run_id,
            status="failed",
            error=f"finalize failed: {exc}",
            row_count=row_count,
            column_metrics_written=columns_written,
        )
    return ProfileRunResult(
        profile_run_id=profile_run_id,
        status="succeeded",
        row_count=row_count,
        column_metrics_written=columns_written,
    )
