from __future__ import annotations

import os
import re
from typing import Iterable, Mapping

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_literal(value: str | None) -> str:
    """Return a SQL string literal with safe escaping.

    Databricks SQL treats ``\\`` as an escape character inside string
    literals, so doubling ``'`` alone is injectable: ``x\\' OR 1=1 --``
    turns ``\\'`` into an escaped quote and the doubled ``'`` closes the
    literal. Escape backslashes first, then quotes.
    """
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def quote_ident(identifier: str) -> str:
    """Quote a Unity Catalog identifier using backticks."""
    safe = identifier.replace("`", "``")
    return f"`{safe}`"


def quote_uc_3part(catalog: str, schema: str, name: str) -> str:
    return f"{quote_ident(catalog)}.{quote_ident(schema)}.{quote_ident(name)}"


def lineage_window_predicate() -> str:
    """``event_date`` bound for system.access.*_lineage reads.

    Without it every lineage query scans the tables' full retention.
    GOVAT_LINEAGE_LOOKBACK_DAYS (default 365, the system tables' free
    retention) sets the window; lower it to cut scan cost, at the price of
    hiding edges whose last lineage event is older than the window.
    """
    try:
        days = int(os.getenv("GOVAT_LINEAGE_LOOKBACK_DAYS", "365"))
    except ValueError:
        days = 365
    return f"event_date >= date_sub(current_date(), {max(1, days)})"


_CONFIG_SUFFIX_RE = re.compile(r"[ .]*\bConfig:.*$", re.MULTILINE)


def redact_error_text(text: str) -> str:
    """Strip the Databricks SDK's "Config: host=..., client_id=..." suffix
    (workspace/client identifiers) from an error message before it reaches
    a browser. Callers log the full exception server-side."""
    return _CONFIG_SUFFIX_RE.sub("", str(text or "")).strip()


def error_text(exc: BaseException | None, limit: int = 300) -> str:
    """"Class: first line of message", redacted and length-capped: the one
    format for exception text returned in API responses."""
    if exc is None:
        return ""
    name = exc.__class__.__name__
    lines = redact_error_text(str(exc)).splitlines()
    message = lines[0][:limit] if lines else ""
    if not message:
        return name
    return message if message.startswith(f"{name}:") else f"{name}: {message}"
