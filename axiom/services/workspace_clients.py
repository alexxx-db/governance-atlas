"""Process-wide reuse of Databricks ``WorkspaceClient`` instances.

Building a client resolves auth (and, for the app principal, an OAuth M2M
token exchange on first call), so constructing one per Genie / AI / Lakebase
call adds a round trip each time. Clients are keyed by purpose plus a hash of
the forwarded user token ("app" for the service principal), so OBO clients are
never shared across users.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Callable

from axiom.bounded_cache import BoundedTTLCache


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


_CLIENTS = BoundedTTLCache(
    max_entries=max(4, _env_int("AXIOM_WORKSPACE_CLIENT_MAX_ENTRIES", 128)),
    max_age_s=max(60, _env_int("AXIOM_WORKSPACE_CLIENT_TTL_S", 3000)),
)


def cached_workspace_client(
    purpose: str,
    user_access_token: str,
    client_class: Any,
    build: Callable[[], Any],
) -> Any:
    token = (user_access_token or "").strip()
    principal = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else "app"
    # The class is part of the key (and held in the value) so a patched or
    # reloaded WorkspaceClient never receives a client built by another class.
    key = (purpose, principal, id(client_class))
    cached = _CLIENTS.get(key)
    if cached is not None and cached[0] is client_class:
        return cached[1]
    client = build()
    _CLIENTS[key] = (client_class, client)
    return client


def clear_workspace_clients() -> None:
    _CLIENTS.clear()
