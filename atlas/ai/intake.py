"""Intake CSV parsing, normalization, and validation (DESIGN.md 7.3).

Columns map to intake fields through ``field_maps/intake_csv.yaml``, the same
schema the Phase 2 ServiceNow collector will use, so the mapping logic here
(``load_field_map``, ``map_row``) is source-agnostic.

Validation is pure: nothing is written here. The API's dry run returns this
report unchanged, and commit writes only when every row is valid.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml

from atlas.ai.models import INTAKE_STATES, PROVENANCE_ORGANIC, IntakeRecord
from atlas.services import input_safety
from atlas.services.bulk_import import MAX_ROWS_PER_REQUEST

DEFAULT_FIELD_MAP = Path(__file__).parent / "field_maps" / "intake_csv.yaml"
MAX_ATTRIBUTES = 20
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def canon(name: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(name or "").strip().lower())


@dataclass(frozen=True)
class FieldSpec:
    target: str
    sources: tuple
    required: bool = False
    type: str = "text"
    max_length: int = 512


@dataclass(frozen=True)
class FieldMap:
    fields: tuple
    state_map: Dict[str, str]

    def source_to_target(self) -> Dict[str, str]:
        return {canon(src): spec.target for spec in self.fields for src in spec.sources}


@lru_cache(maxsize=4)
def load_field_map(path: str = str(DEFAULT_FIELD_MAP)) -> FieldMap:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    specs = []
    for target, spec in (raw.get("fields") or {}).items():
        spec = spec or {}
        specs.append(
            FieldSpec(
                target=str(target),
                sources=tuple(str(s) for s in (spec.get("sources") or [target])),
                required=bool(spec.get("required", False)),
                type=str(spec.get("type", "text")),
                max_length=int(spec.get("max_length", 512)),
            )
        )
    state_map: Dict[str, str] = {}
    for state, aliases in (raw.get("state_map") or {}).items():
        if state not in INTAKE_STATES:
            raise ValueError(f"field map state {state!r} is not one of {INTAKE_STATES}")
        for alias in aliases or []:
            state_map[str(alias).strip().lower()] = state
        state_map[state] = state
    return FieldMap(fields=tuple(specs), state_map=state_map)


def _parse_date(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("must be a date (YYYY-MM-DD)") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class RowResult:
    row_number: int
    intake_id: str
    errors: List[Dict[str, str]] = field(default_factory=list)
    record: Optional[IntakeRecord] = None

    @property
    def valid(self) -> bool:
        return not self.errors and self.record is not None

    def to_dict(self) -> Dict[str, Any]:
        preview = None
        if self.record is not None:
            preview = {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in self.record.hash_fields().items()
            }
        return {
            "rowNumber": self.row_number,
            "intakeId": self.intake_id,
            "status": "valid" if self.valid else "invalid",
            "errors": self.errors,
            "record": preview,
        }


def map_row(
    raw: Mapping[str, Any],
    field_map: FieldMap,
    *,
    row_number: int,
    ingest_run_id: str,
    source_system: str = "csv",
    provenance_class: str = PROVENANCE_ORGANIC,
    sample_run_id: Optional[str] = None,
) -> RowResult:
    """Map + normalize + validate one source row. Never raises."""
    lookup = field_map.source_to_target()
    values: Dict[str, str] = {}
    attributes: Dict[str, str] = {}
    for column, value in raw.items():
        text = "" if value is None else str(value)
        target = lookup.get(canon(column))
        if target:
            if text.strip() and target not in values:
                values[target] = text
        elif text.strip() and len(attributes) < MAX_ATTRIBUTES and canon(column):
            try:
                attributes[canon(column)[:64]] = input_safety.sanitize_plain_text(text, field=canon(column), max_length=512)
            except ValueError:
                continue

    result = RowResult(row_number=row_number, intake_id=values.get("intake_id", "").strip())
    cleaned: Dict[str, Any] = {}
    for spec in field_map.fields:
        text = values.get(spec.target, "")
        if not text.strip():
            if spec.required:
                result.errors.append({"field": spec.target, "message": f"{spec.target} is required."})
            continue
        try:
            if spec.type == "state":
                state = field_map.state_map.get(text.strip().lower())
                if not state:
                    raise ValueError(f"unknown state {text.strip()!r}; expected one of {', '.join(INTAKE_STATES)}")
                cleaned[spec.target] = state
            elif spec.type == "email":
                email = text.strip().lower()
                if not _EMAIL_RE.match(email) or len(email) > 254:
                    raise ValueError("must be an email address")
                cleaned[spec.target] = email
            elif spec.type == "date":
                cleaned[spec.target] = _parse_date(text)
            else:
                cleaned[spec.target] = input_safety.sanitize_plain_text(text, field=spec.target, max_length=spec.max_length)
        except ValueError as exc:
            result.errors.append({"field": spec.target, "message": str(exc)})

    if result.errors:
        return result
    result.intake_id = cleaned["intake_id"]
    result.record = IntakeRecord(
        intake_id=cleaned["intake_id"],
        title=cleaned["title"],
        state=cleaned["state"],
        owner_email=cleaned["owner_email"],
        source_system=source_system,
        ingest_source=source_system,
        ingest_run_id=ingest_run_id,
        business_unit=cleaned.get("business_unit"),
        risk_tier=cleaned.get("risk_tier"),
        platform=cleaned.get("platform"),
        provider=cleaned.get("provider"),
        model_family=cleaned.get("model_family"),
        intended_use=cleaned.get("intended_use"),
        approved_at=cleaned.get("approved_at"),
        review_due_at=cleaned.get("review_due_at"),
        source_record_id=cleaned.get("source_record_id"),
        attributes=attributes,
        provenance_class=provenance_class,
        sample_run_id=sample_run_id,
    )
    return result


def validate_csv(
    text: str,
    *,
    ingest_run_id: str,
    field_map: Optional[FieldMap] = None,
    provenance_class: str = PROVENANCE_ORGANIC,
    sample_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse and validate a whole CSV. Returns the dry-run report:
    ``{ok, headers, rowCount, results, summary, parseErrors, records}``,
    where ``records`` holds the valid IntakeRecords (not serialized)."""
    field_map = field_map or load_field_map()
    body = (text or "").lstrip("﻿")
    report: Dict[str, Any] = {"ok": False, "headers": [], "rowCount": 0, "results": [], "parseErrors": [], "records": []}
    if not body.strip():
        report["parseErrors"].append({"row": 0, "message": "CSV is empty."})
        report["summary"] = {"total": 0, "valid": 0, "invalid": 0}
        return report
    reader = csv.DictReader(io.StringIO(body))
    headers = list(reader.fieldnames or [])
    report["headers"] = headers
    mapped = set(field_map.source_to_target().get(canon(h)) for h in headers) - {None}
    missing = [spec.target for spec in field_map.fields if spec.required and spec.target not in mapped]
    if missing:
        report["parseErrors"].append({"row": 1, "message": f"Missing required column(s): {', '.join(missing)}."})
        report["summary"] = {"total": 0, "valid": 0, "invalid": 0}
        return report

    seen: Dict[str, int] = {}
    results: List[RowResult] = []
    for index, raw in enumerate(reader, start=2):
        if len(results) >= MAX_ROWS_PER_REQUEST:
            report["parseErrors"].append({"row": index, "message": f"CSV exceeds the {MAX_ROWS_PER_REQUEST}-row limit."})
            break
        if not any(str(v or "").strip() for v in raw.values()):
            continue
        row = map_row(
            raw, field_map, row_number=index, ingest_run_id=ingest_run_id,
            provenance_class=provenance_class, sample_run_id=sample_run_id,
        )
        if row.valid:
            key = row.record.intake_id.lower()
            if key in seen:
                row.errors.append({"field": "intake_id", "message": f"duplicate of row {seen[key]}"})
                row.record = None
            else:
                seen[key] = index
        results.append(row)

    valid = [r for r in results if r.valid]
    report["rowCount"] = len(results)
    report["results"] = [r.to_dict() for r in results]
    report["summary"] = {"total": len(results), "valid": len(valid), "invalid": len(results) - len(valid)}
    report["records"] = [r.record for r in valid]
    report["ok"] = bool(results) and not report["parseErrors"] and len(valid) == len(results)
    return report
