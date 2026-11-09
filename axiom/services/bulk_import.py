"""Bulk CSV metadata import.

CSV columns: `fqn, description, domain, tier, certification,
sensitivity, criticality, business_criticality, data_product,
is_cde, cde_rationale, tags`. Only `fqn` is required. `tags` is a
semicolon-separated list of `k=v` pairs. `is_cde` is true/false.

The commit endpoint invokes `_apply_asset_metadata` per row, so every
row flows through the same approval gate individual edits use. A
writer who accidentally reaches this endpoint would see all rows
queued; the endpoint is explicitly restricted to stewards + admins.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Callable, Dict, List, Optional

from axiom.services.live_metadata import BUSINESS_CRITICALITY_VALUES

SUPPORTED_COLUMNS = (
    "fqn",
    "description",
    "domain",
    "tier",
    "certification",
    "sensitivity",
    "criticality",
    "business_criticality",
    "data_product",
    "owner",
    "tags",
    "is_cde",
    "cde_rationale",
)

MAX_ROWS_PER_REQUEST = 5000


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _canon_column(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_").replace("-", "_")


def _parse_bool(value: str) -> Optional[bool]:
    text = _normalize(value).lower()
    if not text:
        return None
    if text in ("true", "yes", "y", "1", "t"):
        return True
    if text in ("false", "no", "n", "0", "f"):
        return False
    return None


def _parse_tag_list(raw: str) -> Dict[str, str]:
    """Parse a `k=v;k2=v2` string into a dict. Whitespace tolerated."""
    out: Dict[str, str] = {}
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = _normalize(key)
        value = _normalize(value)
        if key and value:
            out[key] = value
    return out


def parse_csv(text: str) -> Dict[str, Any]:
    """Parse raw CSV text. Returns `{rows, errors, headers}`. Unknown
    columns pass through verbatim (reported later if unused)."""
    text = text or ""
    if not text.strip():
        return {"rows": [], "errors": [{"row": 0, "message": "CSV is empty."}], "headers": []}
    # Strip BOM if present (utf-8-sig sometimes leaks through).
    if text.startswith("﻿"):
        text = text[1:]
    buf = io.StringIO(text)
    reader = csv.reader(buf)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return {
            "rows": [],
            "errors": [{"row": 0, "message": "CSV has no header row."}],
            "headers": [],
        }

    canonical_headers = [_canon_column(h) for h in raw_headers]
    if "fqn" not in canonical_headers:
        return {
            "rows": [],
            "errors": [{"row": 0, "message": "CSV must include an `fqn` column."}],
            "headers": raw_headers,
        }

    rows: List[Dict[str, str]] = []
    errors: List[Dict[str, Any]] = []
    for index, raw in enumerate(reader, start=2):  # row 1 was header
        if len(rows) >= MAX_ROWS_PER_REQUEST:
            errors.append(
                {
                    "row": index,
                    "message": (
                        f"Row cap exceeded ({MAX_ROWS_PER_REQUEST}). Split the file "
                        "and retry."
                    ),
                }
            )
            break
        if not any(_normalize(cell) for cell in raw):
            continue
        row_dict: Dict[str, str] = {}
        for col_index, header in enumerate(canonical_headers):
            value = raw[col_index] if col_index < len(raw) else ""
            row_dict[header] = _normalize(value)
        rows.append(row_dict)

    return {"rows": rows, "errors": errors, "headers": raw_headers}


def validate_rows(
    rows: List[Dict[str, str]],
    *,
    asset_exists: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    """Validate each parsed row. Returns `{results, summary}`.

    Each result row carries the `patch` dict matching
    `AssetMetadataPatch`, a list of `errors` (hard blockers) and
    `warnings` (soft signals like an FQN the catalog doesn't recognize).
    """
    results: List[Dict[str, Any]] = []
    valid = invalid = empty = 0
    for index, row in enumerate(rows):
        errors: List[str] = []
        warnings: List[str] = []
        fqn = _normalize(row.get("fqn"))
        if not fqn:
            errors.append("fqn is required.")
        elif len(fqn.split(".")) != 3:
            errors.append("fqn must be catalog.schema.table.")
        elif asset_exists is not None and not asset_exists(fqn):
            warnings.append("fqn was not found in the current catalog scope.")

        biz_crit = _normalize(row.get("business_criticality"))
        if biz_crit and biz_crit not in BUSINESS_CRITICALITY_VALUES:
            errors.append(
                "business_criticality must be one of: "
                + ", ".join(BUSINESS_CRITICALITY_VALUES)
            )

        is_cde_raw = row.get("is_cde") or ""
        is_cde = _parse_bool(is_cde_raw)
        if is_cde_raw and is_cde is None:
            errors.append("is_cde must be true or false when provided.")

        patch: Dict[str, Any] = {}
        description = _normalize(row.get("description"))
        if description:
            patch["description"] = description
        for csv_key, patch_key in (
            ("domain", "domain"),
            ("tier", "tier"),
            ("certification", "certification"),
            ("sensitivity", "sensitivity"),
            ("criticality", "criticality"),
            ("data_product", "dataProduct"),
        ):
            value = _normalize(row.get(csv_key))
            if value:
                patch[patch_key] = value
        if biz_crit:
            patch["businessCriticality"] = biz_crit
        if is_cde is not None:
            patch["isCde"] = is_cde
            rationale = _normalize(row.get("cde_rationale"))
            if rationale:
                patch["cdeRationale"] = rationale
        tags_raw = _normalize(row.get("tags"))
        if tags_raw:
            parsed_tags = _parse_tag_list(tags_raw)
            if not parsed_tags:
                errors.append(
                    "tags could not be parsed as semicolon-separated key=value pairs."
                )
            else:
                patch["freeformTags"] = parsed_tags

        if not patch and not errors:
            warnings.append("No field changes specified — row will be skipped at commit.")
            empty += 1
        if errors:
            invalid += 1
        elif patch:
            valid += 1

        results.append(
            {
                "row": index + 1,
                "fqn": fqn,
                "patch": patch,
                "errors": errors,
                "warnings": warnings,
            }
        )

    return {
        "results": results,
        "summary": {
            "total": len(rows),
            "valid": valid,
            "invalid": invalid,
            "empty": empty,
        },
    }


def apply_rows(
    results: List[Dict[str, Any]],
    *,
    apply_one: Callable[[str, Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """Commit valid rows. `apply_one(fqn, patch)` should perform the
    real mutation (routing through the approval gate) and return an
    envelope dict — the bulk logic inspects `response["approval"]` to
    separate applied-vs-queued outcomes."""
    applied = queued = failed = 0
    outcomes: List[Dict[str, Any]] = []
    for result in results:
        if result.get("errors") or not result.get("patch"):
            outcomes.append({**result, "outcome": "skipped"})
            continue
        try:
            response = apply_one(result["fqn"], result["patch"])
        except Exception as exc:  # noqa: BLE001
            failed += 1
            outcomes.append({**result, "outcome": "failed", "error": str(exc)})
            continue
        approval_status = ""
        if isinstance(response, dict):
            approval = response.get("approval") if isinstance(response.get("approval"), dict) else None
            if approval:
                approval_status = str(approval.get("status") or "").strip().lower()
        if approval_status == "pending":
            queued += 1
            outcomes.append(
                {
                    **result,
                    "outcome": "queued",
                    "requestId": str(
                        (response or {}).get("approval", {}).get("requestId") or ""
                    ),
                }
            )
        else:
            applied += 1
            outcomes.append({**result, "outcome": "applied"})
    return {
        "outcomes": outcomes,
        "summary": {
            "applied": applied,
            "queued": queued,
            "failed": failed,
            "skipped": len(results) - applied - queued - failed,
        },
    }
