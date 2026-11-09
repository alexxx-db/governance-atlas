"""Input normalization and sanitization for user-authored Axiom text.

These helpers are deliberately small and dependency-free. The app mostly renders
text through React, which escapes by default, but persisted governance text can
also feed audit history, Genie context, and future markdown renderers. Store it
in a conservative shape at the API boundary.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, List


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BIDI_CONTROL_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_DANGEROUS_URI_RE = re.compile(r"\]\(\s*(?:javascript|vbscript|data):", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TAG_KEY_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _BIDI_CONTROL_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines).strip()


def sanitize_plain_text(
    value: Any,
    *,
    field: str = "value",
    max_length: int = 512,
    allow_empty: bool = True,
) -> str:
    text = normalize_text(value).replace("\n", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    _validate_text(text, field=field, max_length=max_length, allow_empty=allow_empty)
    return html.escape(text, quote=False)


def sanitize_markdown(
    value: Any,
    *,
    field: str = "value",
    max_length: int = 4000,
    allow_empty: bool = True,
) -> str:
    text = normalize_text(value)
    _validate_text(text, field=field, max_length=max_length, allow_empty=allow_empty)
    if _DANGEROUS_URI_RE.search(text):
        raise ValueError(f"{field} contains an unsupported link target.")
    # Preserve markdown punctuation while neutralizing raw HTML/script payloads.
    return html.escape(text, quote=False)


def sanitize_email(value: Any, *, field: str = "email", allow_empty: bool = True) -> str:
    email = sanitize_plain_text(value, field=field, max_length=254, allow_empty=allow_empty).lower()
    if email and not _EMAIL_RE.match(email):
        raise ValueError(f"{field} must be a valid email address.")
    return email


def sanitize_tag_map(value: Any, *, field: str = "tags", max_items: int = 50) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object.")
    if len(value) > max_items:
        raise ValueError(f"{field} may contain at most {max_items} entries.")
    sanitized: Dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = sanitize_plain_text(raw_key, field=f"{field} key", max_length=128, allow_empty=False)
        if not _TAG_KEY_RE.match(key):
            raise ValueError(f"{field} key contains unsupported characters: {key}.")
        tag_value = sanitize_plain_text(raw_value, field=f"{field}.{key}", max_length=512, allow_empty=True)
        if tag_value:
            sanitized[key] = tag_value
    return sanitized


def sanitize_json_value(
    value: Any,
    *,
    field: str = "value",
    max_depth: int = 4,
    max_items: int = 100,
    max_string_length: int = 4000,
) -> Any:
    """Return a JSON-serializable value with user-authored strings cleaned.

    Custom property scopes and values can be nested, but they should never carry
    raw HTML, control characters, or arbitrarily large payloads into audit,
    version history, or Genie context.
    """
    if max_depth < 0:
        raise ValueError(f"{field} is nested too deeply.")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_markdown(value, field=field, max_length=max_string_length)
    if isinstance(value, dict):
        if len(value) > max_items:
            raise ValueError(f"{field} may contain at most {max_items} entries.")
        cleaned: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = sanitize_plain_text(raw_key, field=f"{field} key", max_length=128, allow_empty=False)
            if not _TAG_KEY_RE.match(key):
                raise ValueError(f"{field} key contains unsupported characters: {key}.")
            cleaned[key] = sanitize_json_value(
                raw_value,
                field=f"{field}.{key}",
                max_depth=max_depth - 1,
                max_items=max_items,
                max_string_length=max_string_length,
            )
        return cleaned
    if isinstance(value, (list, tuple)):
        if len(value) > max_items:
            raise ValueError(f"{field} may contain at most {max_items} entries.")
        return [
            sanitize_json_value(
                item,
                field=f"{field}[{index}]",
                max_depth=max_depth - 1,
                max_items=max_items,
                max_string_length=max_string_length,
            )
            for index, item in enumerate(value)
        ]
    return sanitize_plain_text(value, field=field, max_length=max_string_length)


def sanitize_reviewer_entries(value: Any, *, field: str = "reviewers", max_items: int = 50) -> List[Dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list.")
    if len(value) > max_items:
        raise ValueError(f"{field} may contain at most {max_items} reviewers.")
    reviewers: List[Dict[str, str]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            email = sanitize_email(item, field=f"{field}[{index}]", allow_empty=False)
            reviewers.append({"reviewerEmail": email})
            continue
        if not isinstance(item, dict):
            raise ValueError(f"{field}[{index}] must be a reviewer object.")
        email = sanitize_email(
            item.get("reviewerEmail") or item.get("email"),
            field=f"{field}[{index}].reviewerEmail",
            allow_empty=False,
        )
        role = sanitize_plain_text(item.get("role") or "reviewer", field=f"{field}[{index}].role", max_length=64)
        state = sanitize_plain_text(item.get("state") or "active", field=f"{field}[{index}].state", max_length=64)
        reviewers.append({"reviewerEmail": email, "role": role or "reviewer", "state": state or "active"})
    return reviewers


def sanitize_allowed(value: Any, *, field: str, allowed: Iterable[str], default: str = "") -> str:
    normalized = sanitize_plain_text(value, field=field, max_length=64, allow_empty=not bool(default)).lower()
    if not normalized and default:
        normalized = default
    allowed_set = {str(item).lower() for item in allowed}
    if normalized not in allowed_set:
        raise ValueError(f"{field} must be one of {', '.join(sorted(allowed_set))}.")
    return normalized


def _validate_text(text: str, *, field: str, max_length: int, allow_empty: bool) -> None:
    if not allow_empty and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > max_length:
        raise ValueError(f"{field} may not exceed {max_length} characters.")
