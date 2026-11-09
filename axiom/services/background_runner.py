"""Phase 12 — background work item runner.

Minimal in-process runner that drains a small batch of queued work
items. Designed to be driven from:
  - an explicit admin-triggered endpoint (`/api/admin/background/run-batch`),
  - a future cron trigger inside the Databricks app,
  - unit tests exercising the materialization path without a real queue.

This module is intentionally small — the full async-export runner
belongs in a background thread with backoff, dead-letter routing,
and lock leases. For now it captures the state-machine contract so
the endpoints, tests, and future runner can share one implementation.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


RUNNER_CLAIM_TTL_SECONDS = 600
MAX_ATTEMPTS_DEFAULT = 3


@dataclass
class WorkItemResult:
    work_id: str
    status: str
    detail: str = ""
    result: Optional[Dict[str, Any]] = None


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def drain_queued_batch(
    *,
    store,
    handler: Callable[[Dict[str, Any]], WorkItemResult],
    max_items: int = 5,
    runner_id: Optional[str] = None,
) -> List[WorkItemResult]:
    """Claim up to `max_items` queued work items and hand them to the
    provided `handler`. Each item is marked running → succeeded / failed
    with one audit row in background_work_runs. Handlers MUST be
    idempotent — a work item that handler-succeeds but then crashes
    before we flip status is safe to re-run."""
    from axiom.util import sql_literal

    runner = runner_id or f"runner-{uuid.uuid4().hex[:8]}"
    # Pull up to max_items queued rows. Delta doesn't support
    # SELECT-FOR-UPDATE; we rely on the optimistic-update pattern:
    # read -> UPDATE ... WHERE status='queued' AND claimed_at IS NULL,
    # then only items we actually claimed land in our batch.
    claim_ts = _now_ts()
    frame = store.uc.query_df(
        f"""SELECT work_id, work_kind, payload_json, actor_email, actor_role,
    token_captured_at, attempt_count, max_attempts
FROM {store._fq('background_work_items')}
WHERE status = 'queued' AND claimed_at IS NULL
ORDER BY priority DESC, scheduled_for ASC, work_id ASC
LIMIT {int(max_items)}"""
    )
    if frame is None or frame.empty:
        return []

    results: List[WorkItemResult] = []
    for _, raw_row in frame.iterrows():
        row = raw_row.to_dict() if hasattr(raw_row, "to_dict") else dict(raw_row)
        work_id = row.get("work_id")
        attempt_count = int(row.get("attempt_count") or 0)
        max_attempts = int(row.get("max_attempts") or MAX_ATTEMPTS_DEFAULT)

        # Optimistic claim — only transition rows still in queued.
        try:
            store.uc.execute(
                f"""UPDATE {store._fq('background_work_items')}
SET status = 'running',
    claimed_at = timestamp({sql_literal(claim_ts)}),
    claimed_by = {sql_literal(runner)},
    started_at = timestamp({sql_literal(claim_ts)}),
    attempt_count = {attempt_count + 1}
WHERE work_id = {sql_literal(work_id)} AND status = 'queued' AND claimed_at IS NULL"""
            )
        except Exception as exc:
            results.append(WorkItemResult(work_id=str(work_id), status="failed", detail=f"claim failed: {exc}"))
            continue

        started_at = _now_ts()
        run_id = uuid.uuid4().hex
        try:
            store.uc.execute(
                f"""INSERT INTO {store._fq('background_work_runs')} (
    run_id, work_id, attempt_number, status, started_at, finished_at,
    error_detail, stats_json
) VALUES (
    {sql_literal(run_id)},
    {sql_literal(work_id)},
    {attempt_count + 1},
    {sql_literal('started')},
    timestamp({sql_literal(started_at)}),
    NULL, NULL, NULL
)"""
            )
        except Exception:
            pass

        # Decode payload for the handler.
        payload: Dict[str, Any] = {}
        raw_payload = row.get("payload_json")
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except Exception:
                payload = {}
        handler_input = {**row, "payload": payload}

        try:
            outcome = handler(handler_input)
        except Exception as exc:
            outcome = WorkItemResult(work_id=str(work_id), status="failed", detail=str(exc))

        finished_at = _now_ts()
        final_status = outcome.status
        if final_status not in ("succeeded", "failed", "cancelled"):
            final_status = "failed"
        if final_status == "failed" and attempt_count + 1 < max_attempts:
            # Retry — back to queued, leave attempt_count incremented.
            next_status_sql = "'queued'"
            claimed_clear = True
        else:
            next_status_sql = sql_literal(final_status)
            claimed_clear = False

        try:
            if claimed_clear:
                store.uc.execute(
                    f"""UPDATE {store._fq('background_work_items')}
SET status = {next_status_sql},
    claimed_at = NULL,
    claimed_by = NULL,
    finished_at = timestamp({sql_literal(finished_at)}),
    last_error = {sql_literal(outcome.detail or None)},
    updated_at = timestamp({sql_literal(finished_at)})
WHERE work_id = {sql_literal(work_id)}"""
                )
            else:
                result_json = json.dumps(outcome.result, sort_keys=True) if outcome.result else None
                store.uc.execute(
                    f"""UPDATE {store._fq('background_work_items')}
SET status = {next_status_sql},
    finished_at = timestamp({sql_literal(finished_at)}),
    last_error = {sql_literal(outcome.detail or None)},
    result_json = {sql_literal(result_json)},
    updated_at = timestamp({sql_literal(finished_at)})
WHERE work_id = {sql_literal(work_id)}"""
                )
            store.uc.execute(
                f"""UPDATE {store._fq('background_work_runs')}
SET status = {sql_literal(final_status if not claimed_clear else 'failed')},
    finished_at = timestamp({sql_literal(finished_at)}),
    error_detail = {sql_literal(outcome.detail or None)}
WHERE run_id = {sql_literal(run_id)}"""
            )
            if final_status == "failed" and not claimed_clear:
                # Route to dead-letters so an operator can inspect.
                dl_id = uuid.uuid4().hex
                store.uc.execute(
                    f"""INSERT INTO {store._fq('background_dead_letters')} (
    dead_letter_id, work_id, work_kind, payload_json, error_detail,
    recorded_at, retried_at, resolution
) VALUES (
    {sql_literal(dl_id)},
    {sql_literal(work_id)},
    {sql_literal(row.get('work_kind'))},
    {sql_literal(raw_payload)},
    {sql_literal(outcome.detail or None)},
    timestamp({sql_literal(finished_at)}),
    NULL,
    {sql_literal('pending')}
)"""
                )
        except Exception:
            pass

        results.append(outcome)
    return results
