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
