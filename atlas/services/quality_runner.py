"""Phase 10 — Quality runner.

Executes quality test cases against a concrete asset, emits one
quality_run + per-case quality_run_result rows. Reuses the Phase 10
SQL guard (atlas.services.quality) for any custom_sql cases so
nothing can slip past the SELECT-only / single-statement /
target-must-be-referenced / budget check.

Built-in test types supported end-to-end:
  - row_count: row count is within [min, max] inclusive
  - freshness: max(watermark_column) is within `max_age_seconds`
  - null_count: null count in column is <= threshold
  - null_fraction: null fraction in column is <= threshold
  - unique: distinct count == total count (no duplicates)
  - accepted_values: every value is in the accepted set
  - regex: every non-null value matches the pattern
  - min_max: column min >= min_threshold AND max <= max_threshold
  - schema_column_presence: column exists with given data type
  - custom_sql: caller-supplied SELECT must return a single numeric
    value that is compared with `op` to `threshold`

Result rows are written via store.insert_quality_run_result so the
Phase 10 /api/assets/:fqn/quality surface picks them up.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from atlas.services import quality as quality_service
from atlas.util import quote_ident, quote_uc_3part, sql_literal


def _safe_table(entity_fqn: str) -> str:
    """Return a backtick-quoted 3-part table reference for `entity_fqn`.

    Built-in evaluators previously spliced the raw FQN straight after FROM,
    so a crafted columnName/FQN could inject SQL. Quote every identifier.
    Falls back to whole-string identifier quoting if the FQN is not 3-part
    (the caller already validated openability upstream).
    """
    parts = [p for p in str(entity_fqn).split(".") if p]
    if len(parts) == 3:
        return quote_uc_3part(parts[0], parts[1], parts[2])
    return quote_ident(str(entity_fqn))


def _safe_col(column_name: str) -> str:
    """Backtick-quote a column identifier, escaping embedded backticks."""
    return quote_ident(str(column_name))


@dataclass
class TestCaseSpec:
    case_id: str
    test_key: str
    entity_fqn: str
    parameters: Dict[str, Any]
    severity: str = "warn"
    column_name: Optional[str] = None


@dataclass
class CaseOutcome:
    case_id: str
    outcome: str
    metric_value: Optional[float] = None
    threshold_value: Optional[float] = None
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


def _scalar(frame) -> Optional[float]:
    if frame is None or getattr(frame, "empty", True):
        return None
    row = frame.iloc[0].to_dict() if hasattr(frame.iloc[0], "to_dict") else dict(frame.iloc[0])
    for v in row.values():
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return None


def _first_col(frame) -> Any:
    if frame is None or getattr(frame, "empty", True):
        return None
    row = frame.iloc[0].to_dict() if hasattr(frame.iloc[0], "to_dict") else dict(frame.iloc[0])
    for v in row.values():
        return v
    return None


def _row_count(uc, entity_fqn: str) -> Optional[int]:
    try:
        frame = uc.query_df(f"SELECT count(*) AS c FROM {_safe_table(entity_fqn)}")
    except Exception:
        return None
    val = _scalar(frame)
    return None if val is None else int(val)


def _eval_row_count(uc, spec: TestCaseSpec) -> CaseOutcome:
    params = spec.parameters or {}
    min_rows = params.get("minRows")
    max_rows = params.get("maxRows")
    count = _row_count(uc, spec.entity_fqn)
    if count is None:
        return CaseOutcome(spec.case_id, "errored", detail="count(*) failed")
    if min_rows is not None and count < int(min_rows):
        return CaseOutcome(spec.case_id, "failed", metric_value=count, threshold_value=float(min_rows),
                           detail=f"row count {count} below minimum {min_rows}")
    if max_rows is not None and count > int(max_rows):
        return CaseOutcome(spec.case_id, "failed", metric_value=count, threshold_value=float(max_rows),
                           detail=f"row count {count} above maximum {max_rows}")
    return CaseOutcome(spec.case_id, "passed", metric_value=count)


def _eval_null_count(uc, spec: TestCaseSpec, fraction: bool = False) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    threshold = spec.parameters.get("threshold")
    try:
        frame = uc.query_df(
            f"SELECT sum(CASE WHEN {_safe_col(spec.column_name)} IS NULL THEN 1 ELSE 0 END) AS nulls, count(*) AS total FROM {_safe_table(spec.entity_fqn)}"
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    if frame is None or frame.empty:
        return CaseOutcome(spec.case_id, "errored", detail="empty result")
    row = frame.iloc[0].to_dict() if hasattr(frame.iloc[0], "to_dict") else dict(frame.iloc[0])
    nulls = int(row.get("nulls") or 0)
    total = int(row.get("total") or 0)
    metric = (nulls / total) if fraction and total > 0 else float(nulls)
    if threshold is None:
        return CaseOutcome(spec.case_id, "passed", metric_value=metric)
    thresh = float(threshold)
    outcome = "passed" if metric <= thresh else "failed"
    return CaseOutcome(
        spec.case_id,
        outcome,
        metric_value=metric,
        threshold_value=thresh,
        detail=f"nulls={nulls} total={total}",
    )


def _eval_unique(uc, spec: TestCaseSpec) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    try:
        frame = uc.query_df(
            f"SELECT count(*) AS total, count(DISTINCT {_safe_col(spec.column_name)}) AS distinct_count FROM {_safe_table(spec.entity_fqn)}"
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    if frame is None or frame.empty:
        return CaseOutcome(spec.case_id, "errored", detail="empty result")
    row = frame.iloc[0].to_dict() if hasattr(frame.iloc[0], "to_dict") else dict(frame.iloc[0])
    total = int(row.get("total") or 0)
    distinct_count = int(row.get("distinct_count") or 0)
    return CaseOutcome(
        spec.case_id,
        "passed" if total == distinct_count else "failed",
        metric_value=float(total - distinct_count),
        threshold_value=0.0,
        detail=f"total={total} distinct={distinct_count}",
    )


def _eval_accepted_values(uc, spec: TestCaseSpec) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    accepted = spec.parameters.get("accepted") or []
    if not accepted:
        return CaseOutcome(spec.case_id, "errored", detail="accepted list required")
    literals = ", ".join(sql_literal(str(v)) for v in accepted)
    try:
        frame = uc.query_df(
            f"""SELECT count(*) AS violating FROM {_safe_table(spec.entity_fqn)}
WHERE {_safe_col(spec.column_name)} IS NOT NULL AND {_safe_col(spec.column_name)} NOT IN ({literals})"""
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    violating = _scalar(frame)
    if violating is None:
        return CaseOutcome(spec.case_id, "errored", detail="empty result")
    return CaseOutcome(
        spec.case_id,
        "passed" if violating == 0 else "failed",
        metric_value=float(violating),
        threshold_value=0.0,
        detail=f"{int(violating)} value(s) outside accepted set",
    )


def _eval_regex(uc, spec: TestCaseSpec) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    pattern = spec.parameters.get("pattern")
    if not pattern:
        return CaseOutcome(spec.case_id, "errored", detail="pattern required")
    # sql_literal also escapes backslashes, so a pattern like `\d` reaches the
    # regex engine intact instead of being unescaped to `d` by the SQL parser.
    safe_pattern = sql_literal(str(pattern))
    try:
        frame = uc.query_df(
            f"""SELECT count(*) AS violating FROM {_safe_table(spec.entity_fqn)}
WHERE {_safe_col(spec.column_name)} IS NOT NULL AND NOT rlike(cast({_safe_col(spec.column_name)} AS STRING), {safe_pattern})"""
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    violating = _scalar(frame)
    if violating is None:
        return CaseOutcome(spec.case_id, "errored", detail="empty result")
    return CaseOutcome(
        spec.case_id,
        "passed" if violating == 0 else "failed",
        metric_value=float(violating),
        threshold_value=0.0,
        detail=f"{int(violating)} value(s) failed regex /{pattern}/",
    )


def _eval_min_max(uc, spec: TestCaseSpec) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    min_threshold = spec.parameters.get("minThreshold")
    max_threshold = spec.parameters.get("maxThreshold")
    try:
        frame = uc.query_df(
            f"SELECT min({_safe_col(spec.column_name)}) AS min_v, max({_safe_col(spec.column_name)}) AS max_v FROM {_safe_table(spec.entity_fqn)}"
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    if frame is None or frame.empty:
        return CaseOutcome(spec.case_id, "errored", detail="empty result")
    row = frame.iloc[0].to_dict() if hasattr(frame.iloc[0], "to_dict") else dict(frame.iloc[0])
    try:
        min_v = float(row.get("min_v"))
        max_v = float(row.get("max_v"))
    except Exception:
        return CaseOutcome(spec.case_id, "errored", detail="non-numeric min/max")
    failures: List[str] = []
    if min_threshold is not None and min_v < float(min_threshold):
        failures.append(f"min {min_v} < {min_threshold}")
    if max_threshold is not None and max_v > float(max_threshold):
        failures.append(f"max {max_v} > {max_threshold}")
    return CaseOutcome(
        spec.case_id,
        "passed" if not failures else "failed",
        metric_value=max_v,
        threshold_value=None if max_threshold is None else float(max_threshold),
        detail="; ".join(failures) if failures else "",
    )


def _eval_freshness(uc, spec: TestCaseSpec) -> CaseOutcome:
    column = spec.column_name or spec.parameters.get("watermarkColumn")
    if not column:
        return CaseOutcome(spec.case_id, "errored", detail="watermarkColumn required")
    max_age = spec.parameters.get("maxAgeSeconds")
    try:
        frame = uc.query_df(
            f"SELECT unix_timestamp(max({_safe_col(column)})) AS max_ts FROM {_safe_table(spec.entity_fqn)}"
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    ts = _scalar(frame)
    if ts is None:
        return CaseOutcome(spec.case_id, "errored", detail="no watermark available")
    age = datetime.now(timezone.utc).timestamp() - ts
    if max_age is None:
        return CaseOutcome(spec.case_id, "passed", metric_value=age)
    thresh = float(max_age)
    return CaseOutcome(
        spec.case_id,
        "passed" if age <= thresh else "failed",
        metric_value=age,
        threshold_value=thresh,
        detail=f"watermark age {int(age)}s vs budget {int(thresh)}s",
    )


def _eval_custom_sql(uc, spec: TestCaseSpec) -> CaseOutcome:
    sql = spec.parameters.get("sql")
    if not sql:
        return CaseOutcome(spec.case_id, "errored", detail="sql required")
    validation = quality_service.validate_custom_sql(
        sql,
        target_entity_fqn=spec.entity_fqn,
        allowed_comparisons=spec.parameters.get("allowedComparisons") or (),
    )
    if not validation.ok:
        return CaseOutcome(spec.case_id, "errored", detail=f"guard rejected: {validation.reason}")
    budget = quality_service.check_budgets(
        row_budget=spec.parameters.get("rowBudget"),
        byte_budget=spec.parameters.get("byteBudget"),
        time_budget_ms=spec.parameters.get("timeBudgetMs"),
    )
    if not budget.ok:
        return CaseOutcome(spec.case_id, "errored", detail=f"budget: {budget.reason}")
    time_budget_ms = spec.parameters.get("timeBudgetMs")
    try:
        frame = uc.query_df(
            validation.normalized,
            timeout_s=max(5, int(time_budget_ms) // 1000) if time_budget_ms else 30,
        )
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    value = _scalar(frame)
    if value is None:
        return CaseOutcome(spec.case_id, "errored", detail="custom SQL returned non-numeric")
    op = str(spec.parameters.get("op") or "<=").strip()
    threshold = spec.parameters.get("threshold")
    if threshold is None:
        return CaseOutcome(spec.case_id, "passed", metric_value=value)
    t = float(threshold)
    ok = (
        (op == "<=" and value <= t)
        or (op == ">=" and value >= t)
        or (op == "<" and value < t)
        or (op == ">" and value > t)
        or (op == "==" and value == t)
        or (op == "!=" and value != t)
    )
    return CaseOutcome(
        spec.case_id,
        "passed" if ok else "failed",
        metric_value=value,
        threshold_value=t,
        detail=f"{value} {op} {t} == {ok}",
    )


def _eval_schema_column_presence(uc, spec: TestCaseSpec) -> CaseOutcome:
    if not spec.column_name:
        return CaseOutcome(spec.case_id, "errored", detail="column_name required")
    expected_type = spec.parameters.get("expectedDataType")
    try:
        frame = uc.query_df(f"DESCRIBE TABLE {_safe_table(spec.entity_fqn)}")
    except Exception as exc:
        return CaseOutcome(spec.case_id, "errored", detail=str(exc))
    if frame is None or frame.empty:
        return CaseOutcome(spec.case_id, "errored", detail="describe empty")
    found_type: Optional[str] = None
    for _, raw in frame.iterrows():
        row = raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)
        col = str(row.get("col_name") or row.get("column_name") or "").strip()
        if col.lower() == spec.column_name.lower():
            found_type = str(row.get("data_type") or "").strip().lower()
            break
    if found_type is None:
        return CaseOutcome(spec.case_id, "failed", detail=f"column {spec.column_name} missing")
    if expected_type and expected_type.lower() not in found_type:
        return CaseOutcome(
            spec.case_id,
            "failed",
            detail=f"column {spec.column_name} is {found_type}, expected {expected_type}",
        )
    return CaseOutcome(spec.case_id, "passed", detail=f"column {spec.column_name} has type {found_type}")


EVALUATORS: Dict[str, Callable[[Any, TestCaseSpec], CaseOutcome]] = {
    "row_count": _eval_row_count,
    "null_count": lambda uc, spec: _eval_null_count(uc, spec, fraction=False),
    "null_fraction": lambda uc, spec: _eval_null_count(uc, spec, fraction=True),
    "unique": _eval_unique,
    "accepted_values": _eval_accepted_values,
    "regex": _eval_regex,
    "min_max": _eval_min_max,
    "freshness": _eval_freshness,
    "custom_sql": _eval_custom_sql,
    "schema_column_presence": _eval_schema_column_presence,
}


@dataclass
class QualityRunResult:
    run_id: str
    status: str
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0


# The suite runs inside an HTTP request behind the ~60s Apps proxy timeout.
SUITE_TIME_CAP_S = 45


class _BudgetedUC:
    """Gives every evaluator query only the suite's remaining time, so the
    statement is cancelled (uc.query_df) instead of running past the request."""

    def __init__(self, uc, deadline: float) -> None:
        self._uc = uc
        self._deadline = deadline

    def query_df(self, statement: str, **kwargs):
        remaining = self._deadline - time.monotonic()
        if remaining < 5:
            raise TimeoutError("quality suite time budget exhausted")
        kwargs["timeout_s"] = int(min(remaining, kwargs.get("timeout_s") or remaining))
        return self._uc.query_df(statement, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._uc, name)


def run_quality_suite(
    *,
    store,
    uc_client,
    cases: List[TestCaseSpec],
    suite_id: Optional[str] = None,
    trigger: str = "manual",
    actor_email: str = "system",
    row_budget: int = quality_service.MAX_ROW_BUDGET,
    byte_budget: int = quality_service.MAX_BYTE_BUDGET,
    time_budget_ms: int = quality_service.MAX_TIME_BUDGET_MS,
) -> QualityRunResult:
    """Execute `cases` against `uc_client`, persist the run + per-case
    results via `store`. Returns an aggregate summary."""
    run_id = uuid.uuid4().hex
    summary = {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}
    try:
        store.insert_quality_run(
            run_id=run_id,
            suite_id=suite_id,
            trigger=trigger,
            status="running",
            row_budget=row_budget,
            byte_budget=byte_budget,
            time_budget_ms=time_budget_ms,
            summary=None,
            created_by=actor_email,
        )
    except Exception as exc:
        return QualityRunResult(run_id=run_id, status="failed")

    budget_s = min(max(1, int(time_budget_ms or 0)) / 1000.0, SUITE_TIME_CAP_S)
    budgeted_uc = _BudgetedUC(uc_client, time.monotonic() + budget_s)
    for spec in cases:
        evaluator = EVALUATORS.get(spec.test_key)
        if not evaluator:
            outcome = CaseOutcome(spec.case_id, "skipped", detail=f"unknown test key {spec.test_key}")
        else:
            try:
                outcome = evaluator(budgeted_uc, spec)
            except Exception as exc:
                outcome = CaseOutcome(spec.case_id, "errored", detail=str(exc))
        summary[outcome.outcome] = summary.get(outcome.outcome, 0) + 1
        try:
            store.insert_quality_run_result(
                result_id=uuid.uuid4().hex,
                run_id=run_id,
                case_id=spec.case_id,
                entity_fqn=spec.entity_fqn,
                column_name=spec.column_name,
                outcome=outcome.outcome,
                severity=spec.severity,
                metric_value=outcome.metric_value,
                threshold_value=outcome.threshold_value,
                evidence=outcome.evidence or None,
                statement_id=None,
                row_bytes_scanned=None,
                detail=outcome.detail,
            )
        except Exception:
            continue

    final_status = "succeeded" if summary["failed"] == 0 and summary["errored"] == 0 else "partial"
    try:
        finalize = getattr(store, "finalize_quality_run")
        finalize(
            run_id=run_id,
            status=final_status,
            summary=summary,
            error_detail=None,
        )
    except Exception:
        return QualityRunResult(
            run_id=run_id,
            status="failed",
            passed=summary["passed"],
            failed=summary["failed"],
            errored=summary["errored"],
            skipped=summary["skipped"],
        )
    return QualityRunResult(
        run_id=run_id,
        status=final_status,
        passed=summary["passed"],
        failed=summary["failed"],
        errored=summary["errored"],
        skipped=summary["skipped"],
    )
