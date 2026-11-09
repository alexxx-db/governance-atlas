#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from axiom.config import AppConfig
from axiom.services import genie as genie_service
from axiom.services import genie_space_config

CERTIFIED_VALUES = {"certified", "approved", "gold", "trusted", "yes", "true"}
SENTINEL_IDENTIFIERS = {"unavailable", "none", "no_data", "n/a", "not_applicable"}
SENTINEL_IDENTIFIER_COLUMNS = {
    "asset_fqn",
    "source_asset_fqn",
    "target_asset_fqn",
    "work_id",
    "audit_id",
    "term_id",
}
SENTINEL_DETAIL_COLUMNS = {"detail", "message", "status"}
SENTINEL_FALLBACK_SQL_RE = re.compile(
    r"union\s+all\s+select[\s\S]{0,240}['\"]?(unavailable|none|no_data|n/a|not_applicable)['\"]?",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _result_rows(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in evidence:
        raw_rows = item.get("resultRows")
        if isinstance(raw_rows, list):
            rows.extend(row for row in raw_rows if isinstance(row, dict))
    return rows


def _row_text(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _is_sentinel_no_result_row(row: Dict[str, Any]) -> bool:
    identifier_values = {
        _row_text(row, key).lower()
        for key in SENTINEL_IDENTIFIER_COLUMNS
        if _row_text(row, key)
    }
    if not identifier_values.intersection(SENTINEL_IDENTIFIERS):
        return False
    non_identifier_values = [
        str(value).strip()
        for key, value in row.items()
        if key not in SENTINEL_IDENTIFIER_COLUMNS
        and key not in SENTINEL_DETAIL_COLUMNS
        and value is not None
        and str(value).strip()
    ]
    if non_identifier_values:
        return False
    detail = _row_text(row, *SENTINEL_DETAIL_COLUMNS).lower()
    return (
        not detail
        or "no data" in detail
        or "no quality issues" in detail
        or "not available" in detail
        or "unavailable" in detail
    )


def _generated_sqls(evidence: List[Dict[str, Any]]) -> List[str]:
    return [
        str(item.get("sql") or "")
        for item in evidence
        if isinstance(item, dict) and str(item.get("sql") or "").strip()
    ]


def _has_sentinel_fallback_sql(evidence: List[Dict[str, Any]]) -> bool:
    return any(SENTINEL_FALLBACK_SQL_RE.search(sql) for sql in _generated_sqls(evidence))


def _has_sentinel_strip_warning(payload: Dict[str, Any]) -> bool:
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    return any("sentinel no-result" in str(warning).lower() for warning in warnings)


def _evaluate(
    payload: Dict[str, Any],
    must_have_any: List[str],
    *,
    question: str,
    catalog: str,
    store_schema: str,
    ai_schema: str,
) -> Dict[str, Any]:
    answer = str(payload.get("answer") or "").strip()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    haystack = json.dumps(payload, default=str).lower()
    keyword_hit = any(token.lower() in haystack for token in must_have_any)
    row_count = 0
    for item in evidence:
        try:
            row_count += int(item.get("rowCount") or item.get("totalRowCount") or 0)
        except Exception:
            pass
    negative_conflict = row_count > 0 and any(
        phrase in answer.lower()[:260]
        for phrase in ["there are no", "no results", "no rows", "none found", "not found", "no data"]
    )
    rows = _result_rows(evidence)
    sentinel_row_returned = any(_is_sentinel_no_result_row(row) for row in rows)
    sentinel_sql_returned = _has_sentinel_fallback_sql(evidence)
    sentinel_strip_warning = _has_sentinel_strip_warning(payload)
    internal_prefixes = tuple(
        prefix.lower()
        for prefix in [
            f"{catalog}.{store_schema}.",
            f"{catalog}.{ai_schema}.",
            f"{catalog}.governance_hub.",
        ]
        if prefix
    )
    leaked_internal_asset = any(
        any(_row_text(row, key).lower().startswith(internal_prefixes) for key in ("asset_fqn", "source_asset_fqn", "target_asset_fqn"))
        for row in rows
    )
    leaked_internal_answer = any(prefix in answer.lower() for prefix in internal_prefixes)
    certified_value_leak = False
    if "not certified" in question.lower():
        certified_value_leak = any(
            _row_text(row, "certification").lower() in CERTIFIED_VALUES
            for row in rows
        )
    passed = (
        bool(answer)
        and bool(evidence)
        and keyword_hit
        and not negative_conflict
        and not leaked_internal_asset
        and not leaked_internal_answer
        and not certified_value_leak
        and not sentinel_row_returned
        and not sentinel_sql_returned
        and not sentinel_strip_warning
    )
    failures = []
    if not answer:
        failures.append("missing_answer")
    if not evidence:
        failures.append("missing_query_evidence")
    if not keyword_hit:
        failures.append("missing_expected_domain_terms")
    if negative_conflict:
        failures.append("answer_conflicts_with_query_row_count")
    if leaked_internal_asset or leaked_internal_answer:
        failures.append("internal_control_plane_asset_leaked")
    if certified_value_leak:
        failures.append("certified_asset_returned_for_not_certified_question")
    if sentinel_row_returned or sentinel_strip_warning:
        failures.append("synthetic_no_result_row_returned")
    if sentinel_sql_returned:
        failures.append("synthetic_no_result_sql_returned")
    return {
        "passed": passed,
        "failures": failures,
        "evidenceCount": len(evidence),
        "totalRowCount": row_count,
        "answerLength": len(answer),
        "confidence": payload.get("confidence"),
        "conversationId": payload.get("conversationId"),
        "messageId": payload.get("messageId"),
    }


def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    client = WorkspaceClient(profile=args.profile if args.profile else None)
    config = AppConfig(
        warehouse_id=args.warehouse_id,
        gov_catalog=args.catalog,
        gov_schema=args.store_schema,
        workspace_host=args.workspace_host,
        genie_space_id=args.space_id,
        genie_space_title=args.title,
        axiom_ai_provider="genie",
        axiom_ai_require_benchmark=True,
    )
    cases = genie_space_config.benchmark_suite()
    results = []
    for case in cases:
        question = str(case["question"])
        try:
            payload = genie_service.ask_genie(config=config, question=question, client=client)
            evaluation = _evaluate(
                payload,
                list(case.get("must_have_any") or []),
                question=question,
                catalog=args.catalog,
                store_schema=args.store_schema,
                ai_schema=args.ai_schema,
            )
            results.append(
                {
                    "id": case["id"],
                    "question": question,
                    "passed": evaluation["passed"],
                    "evaluation": evaluation,
                    "warnings": payload.get("warnings") or [],
                    "answerPreview": str(payload.get("answer") or "")[:700],
                    "evidence": payload.get("evidence") or [],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": case["id"],
                    "question": question,
                    "passed": False,
                    "evaluation": {
                        "failures": ["exception"],
                        "errorType": exc.__class__.__name__,
                        "error": str(exc),
                    },
                }
            )
            if args.fail_fast:
                break

    passed_count = sum(1 for result in results if result.get("passed"))
    payload = {
        "generatedAt": _now_iso(),
        "spaceId": args.space_id,
        "title": args.title,
        "catalog": args.catalog,
        "storeSchema": args.store_schema,
        "aiSchema": args.ai_schema,
        "passCount": passed_count,
        "caseCount": len(results),
        "passed": passed_count == len(cases) and len(results) == len(cases),
        "results": results,
        "acceptance": "All benchmark questions must return a non-empty answer, Genie query evidence, expected governance-domain terms, no internal control-plane asset leakage, no certified assets in not-certified answers, and no synthetic no-result fallback SQL or sentinel evidence rows.",
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the Axiom Genie space.")
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--catalog", default="emet")
    parser.add_argument("--store-schema", default="axiom")
    parser.add_argument("--ai-schema", default=genie_space_config.DEFAULT_AI_SCHEMA)
    parser.add_argument("--title", default=genie_space_config.DEFAULT_SPACE_TITLE)
    parser.add_argument("--workspace-host", default="")
    parser.add_argument("--output", default="docs/genie/benchmark-latest.json")
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args()


def main() -> None:
    payload = run_benchmark(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not payload.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
