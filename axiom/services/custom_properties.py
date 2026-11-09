"""Phase 8 — custom properties service.

Custom properties let admins declare typed, versioned metadata facets
(e.g. "Compliance Owner", "Retention Days", "PII Review Status") and
attach them to assets/columns/glossary terms. Every definition is
versioned so a rename/retype doesn't invalidate historical assignments.

Only a small set of type coercions are supported; validation happens at
the service boundary so routes stay thin and contract tests live near
the behavior.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from axiom.services import input_safety

SUPPORTED_TYPES = ("string", "number", "boolean", "date", "enum", "markdown")
SUPPORTED_ENTITY_KINDS = ("asset", "column", "glossary_term")
_PROPERTY_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    value: Any = None
    reason: str = ""


def new_id() -> str:
    return uuid.uuid4().hex


def _coerce_enum(value: Any, enum_values: Iterable[str]) -> ValidationResult:
    enum_list = [str(v) for v in enum_values]
    if value is None:
        return ValidationResult(ok=False, reason="Enum property requires a value.")
    text = str(value)
    if text not in enum_list:
        return ValidationResult(
            ok=False,
            reason=f"Value {text!r} is not in the allowed enum set {enum_list}.",
        )
    return ValidationResult(ok=True, value=text)


def _coerce_number(value: Any) -> ValidationResult:
    if value is None or value == "":
        return ValidationResult(ok=False, reason="Number property requires a value.")
    try:
        if isinstance(value, bool):
            raise TypeError("bool")
        return ValidationResult(ok=True, value=float(value))
    except (TypeError, ValueError):
        return ValidationResult(ok=False, reason=f"Value {value!r} is not a number.")


def _coerce_boolean(value: Any) -> ValidationResult:
    if isinstance(value, bool):
        return ValidationResult(ok=True, value=value)
    if value is None:
        return ValidationResult(ok=False, reason="Boolean property requires a value.")
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return ValidationResult(ok=True, value=True)
    if text in ("false", "0", "no", "off"):
        return ValidationResult(ok=True, value=False)
    return ValidationResult(ok=False, reason=f"Value {value!r} is not a boolean.")


def _coerce_date(value: Any) -> ValidationResult:
    if not value:
        return ValidationResult(ok=False, reason="Date property requires a value.")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(text.replace("Z", "+0000"), fmt)
            return ValidationResult(ok=True, value=parsed.strftime("%Y-%m-%d"))
        except ValueError:
            continue
    return ValidationResult(ok=False, reason=f"Value {value!r} is not an ISO date.")


def validate_value(
    data_type: str,
    value: Any,
    *,
    enum_values: Optional[Iterable[str]] = None,
    is_required: bool = False,
    is_multi: bool = False,
) -> ValidationResult:
    """Coerce+validate a single value (or list if is_multi) against a
    declared data_type. Returns the cleaned value."""
    if is_multi:
        if value is None:
            value = []
        if not isinstance(value, (list, tuple)):
            return ValidationResult(ok=False, reason="Multi-value property expects a list.")
        cleaned: List[Any] = []
        for item in value:
            inner = validate_value(
                data_type,
                item,
                enum_values=enum_values,
                is_required=is_required,
                is_multi=False,
            )
            if not inner.ok:
                return inner
            cleaned.append(inner.value)
        if is_required and not cleaned:
            return ValidationResult(ok=False, reason="This property is required.")
        return ValidationResult(ok=True, value=cleaned)

    if value in (None, ""):
        if is_required:
            return ValidationResult(ok=False, reason="This property is required.")
        return ValidationResult(ok=True, value=None)

    if data_type == "string":
        try:
            cleaned = input_safety.sanitize_plain_text(value, field="value", max_length=4000)
        except ValueError as exc:
            return ValidationResult(ok=False, reason=str(exc))
        return ValidationResult(ok=True, value=cleaned)
    if data_type == "markdown":
        try:
            cleaned = input_safety.sanitize_markdown(value, field="value", max_length=8000)
        except ValueError as exc:
            return ValidationResult(ok=False, reason=str(exc))
        return ValidationResult(ok=True, value=cleaned)
    if data_type == "number":
        return _coerce_number(value)
    if data_type == "boolean":
        return _coerce_boolean(value)
    if data_type == "date":
        return _coerce_date(value)
    if data_type == "enum":
        return _coerce_enum(value, enum_values or [])
    return ValidationResult(ok=False, reason=f"Unsupported data type {data_type!r}.")


def normalize_definition_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the shape of a definition payload and return a clean dict."""
    try:
        data_type = input_safety.sanitize_allowed(
            payload.get("dataType") or "",
            field="dataType",
            allowed=SUPPORTED_TYPES,
        )
    except ValueError:
        raise ValueError(
            f"Unsupported dataType {(payload.get('dataType') or '')!r}; expected one of {SUPPORTED_TYPES}."
        )
    try:
        entity_kind = input_safety.sanitize_allowed(
            payload.get("entityKind") or "",
            field="entityKind",
            allowed=SUPPORTED_ENTITY_KINDS,
        )
    except ValueError:
        raise ValueError(
            f"Unsupported entityKind {(payload.get('entityKind') or '')!r}; expected one of {SUPPORTED_ENTITY_KINDS}."
        )
    property_key = input_safety.sanitize_plain_text(
        payload.get("propertyKey") or "",
        field="propertyKey",
        max_length=128,
        allow_empty=False,
    )
    if not _PROPERTY_KEY_RE.match(property_key):
        raise ValueError("propertyKey must start with a letter and use only letters, numbers, underscore, dash, dot, or colon.")
    enum_values = payload.get("enumValues") or []
    if data_type == "enum":
        if not isinstance(enum_values, list) or not enum_values:
            raise ValueError("Enum properties must declare a non-empty enumValues list.")
    display_name = input_safety.sanitize_plain_text(
        payload.get("displayName") or property_key,
        field="displayName",
        max_length=256,
        allow_empty=False,
    )
    description_raw = payload.get("description")
    description = (
        input_safety.sanitize_markdown(description_raw, field="description", max_length=4000)
        if description_raw is not None
        else None
    )
    scope = input_safety.sanitize_json_value(payload.get("scope") or {}, field="scope", max_depth=4)
    return {
        "entityKind": entity_kind,
        "propertyKey": property_key,
        "displayName": display_name,
        "description": description,
        "dataType": data_type,
        "enumValues": [
            input_safety.sanitize_plain_text(v, field="enumValues", max_length=128, allow_empty=False)
            for v in enum_values
        ] if data_type == "enum" else [],
        "isRequired": bool(payload.get("isRequired")),
        "isMulti": bool(payload.get("isMulti")),
        "scope": scope,
    }


def definition_snapshot_json(definition: Dict[str, Any]) -> str:
    """Stable JSON snapshot used by custom_property_definition_versions."""
    return json.dumps(
        {
            "entityKind": definition.get("entityKind"),
            "propertyKey": definition.get("propertyKey"),
            "displayName": definition.get("displayName"),
            "description": definition.get("description"),
            "dataType": definition.get("dataType"),
            "enumValues": list(definition.get("enumValues") or []),
            "isRequired": bool(definition.get("isRequired")),
            "isMulti": bool(definition.get("isMulti")),
            "scope": definition.get("scope") or {},
        },
        sort_keys=True,
    )


def now_utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
