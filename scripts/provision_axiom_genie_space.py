#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from axiom.services import genie_space_config


def _obj_get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _state_name(response: Any) -> str:
    status = _obj_get(response, "status")
    state = _obj_get(status, "state")
    value = getattr(state, "value", state)
    return str(value or "").upper()


def _error_message(response: Any) -> str:
    status = _obj_get(response, "status")
    error = _obj_get(status, "error")
    if not error:
        return ""
    as_dict = getattr(error, "as_dict", None)
    if callable(as_dict):
        try:
            return json.dumps(as_dict(), sort_keys=True)
        except Exception:
            pass
    return str(error)


def execute_sql(w: WorkspaceClient, *, warehouse_id: str, statement: str, timeout_seconds: int = 180) -> Dict[str, Any]:
    response = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="30s",
    )
    statement_id = _obj_get(response, "statement_id")
    deadline = time.time() + timeout_seconds
    while _state_name(response) in {"PENDING", "RUNNING"} and time.time() < deadline:
        time.sleep(2)
        response = w.statement_execution.get_statement(statement_id)
    state = _state_name(response)
    if state not in {"SUCCEEDED"}:
        raise RuntimeError(f"SQL statement failed with state={state}: {_error_message(response)}")
    return {"statementId": statement_id, "state": state}


def find_space_id(w: WorkspaceClient, title: str) -> str:
    title_norm = title.strip().lower()
    page_token = None
    while True:
        response = w.genie.list_spaces(page_size=100, page_token=page_token)
        for space in _obj_get(response, "spaces", []) or []:
            if str(_obj_get(space, "title") or "").strip().lower() == title_norm:
                return str(_obj_get(space, "space_id") or "")
        page_token = _obj_get(response, "next_page_token")
        if not page_token:
            return ""


def provision(args: argparse.Namespace) -> Dict[str, Any]:
    w = WorkspaceClient(profile=args.profile if args.profile else None)
    view_results = []
    for item in genie_space_config.curated_view_statements(
        catalog=args.catalog,
        store_schema=args.store_schema,
        ai_schema=args.ai_schema,
    ):
        try:
            result = execute_sql(w, warehouse_id=args.warehouse_id, statement=item["sql"])
            view_results.append({"name": item["name"], **result})
        except Exception as exc:
            fallback_sql = item.get("fallback_sql")
            if not fallback_sql or item.get("required"):
                raise
            result = execute_sql(w, warehouse_id=args.warehouse_id, statement=fallback_sql)
            view_results.append(
                {
                    "name": item["name"],
                    **result,
                    "fallback": True,
                    "fallbackReason": f"{exc.__class__.__name__}: {exc}",
                }
            )

    serialized = genie_space_config.serialized_space(catalog=args.catalog, ai_schema=args.ai_schema)
    space_id = args.space_id or find_space_id(w, args.title)
    if space_id:
        space = w.genie.update_space(
            space_id,
            title=args.title,
            description=args.description,
            warehouse_id=args.warehouse_id,
            serialized_space=serialized,
        )
        operation = "updated"
    else:
        try:
            w.workspace.mkdirs(args.parent_path)
        except Exception:
            pass
        space = w.genie.create_space(
            warehouse_id=args.warehouse_id,
            serialized_space=serialized,
            title=args.title,
            description=args.description,
            parent_path=args.parent_path,
        )
        operation = "created"

    payload = {
        "operation": operation,
        "spaceId": str(_obj_get(space, "space_id") or space_id),
        "title": str(_obj_get(space, "title") or args.title),
        "warehouseId": args.warehouse_id,
        "catalog": args.catalog,
        "storeSchema": args.store_schema,
        "aiSchema": args.ai_schema,
        "views": view_results,
        "serializedSpaceBytes": len(serialized.encode("utf-8")),
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision the Axiom Genie space and curated UC views.")
    parser.add_argument("--profile", default="DEFAULT")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", default="emet")
    parser.add_argument("--store-schema", default="axiom")
    parser.add_argument("--ai-schema", default=genie_space_config.DEFAULT_AI_SCHEMA)
    parser.add_argument("--space-id", default="")
    parser.add_argument("--title", default=genie_space_config.DEFAULT_SPACE_TITLE)
    parser.add_argument("--description", default=genie_space_config.DEFAULT_DESCRIPTION)
    parser.add_argument("--parent-path", default=genie_space_config.DEFAULT_PARENT_PATH)
    parser.add_argument("--output", default="docs/genie/provision-latest.json")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(provision(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
