"""Shared runtime caches for the Axiom API.

Holds module-level TTL caches plus a threading lock so mutations remain safe
under FastAPI's default threaded worker. Pure container: no dependencies on
AppConfig or UCSQLClient.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable, Dict, Tuple

from axiom.bounded_cache import BoundedTTLCache


_CACHE_LOCK = threading.Lock()

_TTL_CACHE: Dict[str, Tuple[float, Any]] = BoundedTTLCache()

_OBO_CLIENT_TTL_SECONDS = 120
_OBO_CLIENT_MAX_ENTRIES = 32
_OBO_CLIENT_CACHE: Dict[str, Tuple[float, Any]] = BoundedTTLCache(
    max_entries=_OBO_CLIENT_MAX_ENTRIES, max_age_s=_OBO_CLIENT_TTL_SECONDS
)


def _obo_token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _ttl_value(key: str, ttl_s: int, loader: Callable[[], Any]) -> Any:
    now = time.time()
    cached = _TTL_CACHE.get(key)
    if cached and now - cached[0] < ttl_s:
        return cached[1]
    value = loader()
    # Stamp COMPLETION time, not call time: a loader slower than its TTL would
    # otherwise write an already-expired entry, and endpoints whose warm loaders
    # exceed the TTL (taxonomy 90s, audit evidence 30s, control-center 45s on a
    # cold warehouse) stayed in state=loading forever on the live app.
    with _CACHE_LOCK:
        _TTL_CACHE[key] = (time.time(), value)
    return value


def _ttl_fresh_value(key: str, ttl_s: int) -> Any:
    cached = _TTL_CACHE.get(key)
    if cached and time.time() - cached[0] < ttl_s:
        return cached[1]
    return None


def _ttl_stale_value(key: str) -> Any:
    """Return the cached value regardless of freshness, or None if never cached.

    Supports stale-while-revalidate: route handlers serve the last good payload
    while a background warm rebuilds it, instead of regressing to an empty
    loading envelope every time the TTL lapses.
    """
    cached = _TTL_CACHE.get(key)
    return cached[1] if cached else None


def _ttl_cache_pop(key: str) -> None:
    with _CACHE_LOCK:
        _TTL_CACHE.pop(key, None)


def _invalidate_cache_prefix(prefix: str) -> None:
    with _CACHE_LOCK:
        for key in list(_TTL_CACHE.keys()):
            if key.startswith(prefix):
                _TTL_CACHE.pop(key, None)
