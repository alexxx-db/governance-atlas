#!/usr/bin/env python3
"""Export the Axiom Genie Agent serialized_space as parsed JSON, optionally checking its SQL.

--validate runs every example and benchmark SQL statement on a SQL warehouse with the
curated axiom_ai views inlined as CTEs, so the SQL can be checked before the views or
the Genie Agent exist. It only reads data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from axiom.services import genie_space_config  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs" / "genie" / "axiom-genie-agent.json"


def write_payload(*, catalog: str, ai_schema: str, output: Path) -> Dict[str, Any]:
    payload = genie_space_config.serialized_space_payload(catalog=catalog, ai_schema=ai_schema)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def inline_views_sql(sql: str, *, catalog: str, store_schema: str, ai_schema: str) -> str:
    """Rewrite a query against the curated views into one that defines them as CTEs."""
    statements = {
        item["name"]: item["sql"]
        for item in genie_space_config.curated_view_statements(catalog=catalog, store_schema=store_schema, ai_schema=ai_schema)
    }

    def localize(text: str) -> str:
        for name in genie_space_config.curated_view_names():
            text = text.replace(genie_space_config._fq(catalog, ai_schema, name), name)
        return text

    ctes = []
    for name in genie_space_config.curated_view_names():
        body = statements[name].split("\nAS\n", 1)[1]
        ctes.append(f"{name} AS (\n{localize(body)}\n)")
    query = localize(sql).strip()
    if re.match(r"(?i)^WITH\s", query):
        return "WITH " + ",\n".join(ctes) + ",\n" + query[5:]
    return "WITH " + ",\n".join(ctes) + "\n" + query


def _run(client: Any, warehouse_id: str, sql: str) -> Dict[str, Any]:
    from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementState

    started = time.monotonic()
    response = client.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )
    while response.status and response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        response = client.statement_execution.get_statement(response.statement_id)
    state = response.status.state if response.status else None
    error = response.status.error.message if response.status and response.status.error else None
    rows = response.manifest.total_row_count if response.manifest else None
    return {
        "state": state.value if state else "UNKNOWN",
        "rows": rows,
        "error": error,
        "seconds": round(time.monotonic() - started, 1),
    }


def validate(payload: Dict[str, Any], *, profile: str, warehouse_id: str, catalog: str, store_schema: str, ai_schema: str, parallel: int) -> List[Dict[str, Any]]:
    from databricks.sdk import WorkspaceClient

    cases: Dict[str, List[str]] = {}
    for example in payload["instructions"]["example_question_sqls"]:
        cases.setdefault("\n".join(example["sql"]), []).append(example["question"][0])
    for benchmark in payload["benchmarks"]["questions"]:
        sql = "\n".join(benchmark["answer"][0]["content"])
        cases.setdefault(sql, []).append(benchmark["question"][0])

    client = WorkspaceClient(profile=profile)

    def check(item: tuple) -> Dict[str, Any]:
        sql, questions = item
        result = _run(client, warehouse_id, inline_views_sql(sql, catalog=catalog, store_schema=store_schema, ai_schema=ai_schema))
        return {"questions": sorted(set(questions)), **result}

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        return list(pool.map(check, cases.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", default="ops_governance")
    parser.add_argument("--store-schema", default="axiom_alex", help="Axiom governance store schema (only used by --validate)")
    parser.add_argument("--ai-schema", default=genie_space_config.DEFAULT_AI_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate", action="store_true", help="Run every example and benchmark SQL on a warehouse")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile for --validate")
    parser.add_argument("--warehouse-id", default=None, help="SQL warehouse for --validate")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--report", type=Path, default=None, help="Write --validate results as JSON")
    args = parser.parse_args()

    payload = write_payload(catalog=args.catalog, ai_schema=args.ai_schema, output=args.output)
    print(
        f"Wrote {args.output}: {len(payload['config']['sample_questions'])} sample questions, "
        f"{len(payload['instructions']['example_question_sqls'])} example SQLs, "
        f"{len(payload['instructions']['join_specs'])} joins, "
        f"{len(payload['benchmarks']['questions'])} benchmarks"
    )
    if not args.validate:
        return 0
    if not args.profile or not args.warehouse_id:
        parser.error("--validate requires --profile and --warehouse-id")

    results = validate(
        payload,
        profile=args.profile,
        warehouse_id=args.warehouse_id,
        catalog=args.catalog,
        store_schema=args.store_schema,
        ai_schema=args.ai_schema,
        parallel=args.parallel,
    )
    failed = [result for result in results if result["state"] != "SUCCEEDED"]
    for result in sorted(results, key=lambda item: item["questions"][0]):
        status = "ok  " if result["state"] == "SUCCEEDED" else "FAIL"
        print(f"{status} rows={result['rows']} {result['seconds']:>5}s  {result['questions'][0]}")
        if result["error"]:
            print(f"      {result['error'][:400]}")
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"{len(results) - len(failed)}/{len(results)} distinct SQL statements succeeded")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
