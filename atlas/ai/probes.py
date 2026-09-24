"""Capability probes (DESIGN.md 7.2).

Every collector adapter runs behind ``probe``. A probe never raises: an error
becomes ``state='unavailable'`` with a sanitized reason, so the run record can
tell a steward *why* a source is missing instead of rendering an empty table
that would read as "observed nothing".
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple, TypeVar

from atlas.ai.models import (
    PROBE_AVAILABLE,
    PROBE_DEGRADED,
    PROBE_NOT_CONFIGURED,
    PROBE_NOT_SUPPORTED,
    PROBE_UNAVAILABLE,
    ProbeResult,
    utc_now,
)
from atlas.util import error_text, redact_error_text

T = TypeVar("T")


class Degraded(Exception):
    """Raised by an adapter that produced a partial result: some objects were
    unreadable (for example permission-denied models). Carries the partial
    value so the run keeps what it did observe."""

    def __init__(self, reason: str, value: object = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.value = value


def probe(source: str, fn: Callable[[], T]) -> Tuple[ProbeResult, Optional[T]]:
    sampled_at = utc_now().isoformat()
    try:
        value = fn()
    except Degraded as partial:
        return ProbeResult(source, True, PROBE_DEGRADED, redact_error_text(partial.reason)[:500], sampled_at), partial.value  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 - the contract is "never raises"
        return ProbeResult(source, False, PROBE_UNAVAILABLE, error_text(exc)[:500], sampled_at), None
    return ProbeResult(source, True, PROBE_AVAILABLE, "", sampled_at), value


def not_supported(source: str, reason: str) -> ProbeResult:
    """No API exists for this source in the pinned SDK (a permanent gap)."""
    return ProbeResult(source, False, PROBE_NOT_SUPPORTED, reason, utc_now().isoformat())


def not_configured(source: str, reason: str) -> ProbeResult:
    """The operator has not enabled this source (for example an empty allowlist)."""
    return ProbeResult(source, False, PROBE_NOT_CONFIGURED, reason, utc_now().isoformat())


def unavailable(source: str, reason: str) -> ProbeResult:
    """A source known to be unreadable without calling it (for example no API
    exists in the pinned SDK, PHASE0_FINDINGS V6)."""
    return ProbeResult(source, False, PROBE_UNAVAILABLE, reason, utc_now().isoformat())
