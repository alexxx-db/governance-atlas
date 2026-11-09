"""Size- and age-bounded dict for module-level caches.

Cache keys include per-user scopes and per-table names, so a plain dict grows
for the life of the process. ``BoundedTTLCache`` is a drop-in ``dict``
replacement that evicts least-recently-used entries past ``max_entries`` and
drops entries older than ``max_age_s`` (an upper bound well above any
caller TTL; callers still apply their own freshness checks).
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Iterator, List, Optional, Tuple


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


DEFAULT_MAX_ENTRIES = max(16, _env_int("AXIOM_CACHE_MAX_ENTRIES", 1024))
DEFAULT_MAX_AGE_S = max(60, _env_int("AXIOM_CACHE_MAX_AGE_S", 86400))
_SWEEP_INTERVAL_S = 60.0

_MISSING = object()


class BoundedTTLCache(OrderedDict):
    def __init__(
        self,
        *args: Any,
        max_entries: Optional[int] = None,
        max_age_s: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        self._lock = threading.RLock()
        self._stamps: Dict[Any, float] = {}
        self._last_sweep = time.monotonic()
        self.max_entries = max(1, int(max_entries or DEFAULT_MAX_ENTRIES))
        self.max_age_s = float(max_age_s or DEFAULT_MAX_AGE_S)
        super().__init__()
        self.update(*args, **kwargs)

    def _expired(self, key: Any, now: float) -> bool:
        stamp = self._stamps.get(key)
        return stamp is not None and now - stamp > self.max_age_s

    def _drop(self, key: Any) -> None:
        self._stamps.pop(key, None)
        OrderedDict.pop(self, key, None)

    def _evict(self, now: float) -> None:
        if now - self._last_sweep >= _SWEEP_INTERVAL_S:
            self._last_sweep = now
            for key in [k for k, t in self._stamps.items() if now - t > self.max_age_s]:
                self._drop(key)
        while OrderedDict.__len__(self) > self.max_entries:
            key, _ = OrderedDict.popitem(self, last=False)
            self._stamps.pop(key, None)

    def __setitem__(self, key: Any, value: Any) -> None:
        with self._lock:
            now = time.monotonic()
            OrderedDict.__setitem__(self, key, value)
            OrderedDict.move_to_end(self, key)
            self._stamps[key] = now
            self._evict(now)

    def __getitem__(self, key: Any) -> Any:
        with self._lock:
            if self._expired(key, time.monotonic()):
                self._drop(key)
                raise KeyError(key)
            value = OrderedDict.__getitem__(self, key)
            OrderedDict.move_to_end(self, key)
            return value

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        with self._lock:
            if not OrderedDict.__contains__(self, key):
                return False
            if self._expired(key, time.monotonic()):
                self._drop(key)
                return False
            return True

    def __delitem__(self, key: Any) -> None:
        with self._lock:
            OrderedDict.__delitem__(self, key)
            self._stamps.pop(key, None)

    def pop(self, key: Any, default: Any = _MISSING) -> Any:
        with self._lock:
            self._stamps.pop(key, None)
            if default is _MISSING:
                return OrderedDict.pop(self, key)
            return OrderedDict.pop(self, key, default)

    def popitem(self, last: bool = True) -> Tuple[Any, Any]:
        with self._lock:
            key, value = OrderedDict.popitem(self, last=last)
            self._stamps.pop(key, None)
            return key, value

    def setdefault(self, key: Any, default: Any = None) -> Any:
        with self._lock:
            value = self.get(key, _MISSING)
            if value is _MISSING:
                self[key] = default
                return default
            return value

    def update(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            for key, value in dict(*args, **kwargs).items():
                self[key] = value

    def clear(self) -> None:
        with self._lock:
            OrderedDict.clear(self)
            self._stamps.clear()

    # Snapshots: readers reorder entries (LRU), so live iteration from another
    # thread could raise "mutated during iteration".
    def __iter__(self) -> Iterator[Any]:
        with self._lock:
            return iter(list(OrderedDict.keys(self)))

    def keys(self) -> List[Any]:  # type: ignore[override]
        with self._lock:
            return list(OrderedDict.keys(self))

    def values(self) -> List[Any]:  # type: ignore[override]
        with self._lock:
            return list(OrderedDict.values(self))

    def items(self) -> List[Tuple[Any, Any]]:  # type: ignore[override]
        with self._lock:
            return list(OrderedDict.items(self))

    def copy(self) -> "BoundedTTLCache":
        with self._lock:
            return BoundedTTLCache(
                OrderedDict.items(self),
                max_entries=self.max_entries,
                max_age_s=self.max_age_s,
            )

    def __reduce__(self):  # pragma: no cover - not pickled in practice
        return (dict, (dict(OrderedDict.items(self)),))
