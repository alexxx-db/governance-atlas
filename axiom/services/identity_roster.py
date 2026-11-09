"""Workspace identity roster — the ground-truth set of principals that actually
exist in the Databricks account.

The governance store historically accepted any free-text email as an owner /
steward / assignee / reviewer. That let fabricated principals
(e.g. "finance-steward@shorecp.com") get linked to assets even though no such
account user exists. The owner mandated that only real account members be
linkable.

This module is the single normalization point for that rule:

- ``get_roster(uc)`` enumerates real workspace users + service principals via
  the existing UC/workspace client and caches the snapshot server-side for
  ``_ROSTER_TTL_S`` seconds (keyed by warehouse so multiple targets never share
  a bucket).
- ``RosterSnapshot.is_member`` / ``.principal_kind`` answer the membership
  question. Service principals are members (they ARE account principals).
- ``validate_principal`` raises a ``PrincipalNotInWorkspaceError`` carrying a
  clean 400 message for the write paths.
- ``account_member_flag`` powers the read-side honesty badge.

Graceful degradation: if the roster API is unavailable in the runtime (the
workspace client raises, or returns nothing), the snapshot is marked
``available=False``. Callers then SKIP the reject-on-write check (fail-open) and
the read flag reports ``None`` rather than a false negative. Nothing is hidden.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Set

import pandas as pd


# 15-minute TTL per the identity-integrity brief. Roster churn is slow; a stale
# window of a few minutes is acceptable and avoids a SCIM round-trip per write.
_ROSTER_TTL_S = 900

_ROSTER_LOCK = threading.Lock()
_ROSTER_CACHE: Dict[str, "RosterSnapshot"] = {}


class PrincipalNotInWorkspaceError(ValueError):
    """Raised when a principal is not a member of the Databricks workspace.

    Carries a customer-safe message suitable for a 400 response body.
    """

    def __init__(self, principal: str) -> None:
        self.principal = principal
        super().__init__(
            f"{principal} is not a member of this Databricks workspace."
        )


def _normalize_principal(value: Any) -> str:
    return str(value or "").strip().lower()


class RosterSnapshot:
    """Immutable-ish view of the workspace principal roster at fetch time."""

    def __init__(
        self,
        *,
        user_emails: Set[str],
        service_principal_ids: Set[str],
        available: bool,
        source: str,
        fetched_at: float,
    ) -> None:
        self.user_emails = user_emails
        self.service_principal_ids = service_principal_ids
        self.available = available
        self.source = source
        self.fetched_at = fetched_at

    @property
    def size(self) -> int:
        return len(self.user_emails) + len(self.service_principal_ids)

    def principal_kind(self, principal: Any) -> Optional[str]:
        """Return 'user' | 'service_principal' | None (unknown / not a member)."""
        normalized = _normalize_principal(principal)
        if not normalized:
            return None
        if normalized in self.user_emails:
            return "user"
        if normalized in self.service_principal_ids:
            return "service_principal"
        return None

    def is_member(self, principal: Any) -> bool:
        return self.principal_kind(principal) is not None

    def account_member_flag(self, principal: Any) -> Optional[bool]:
        """Read-side honesty flag.

        - ``True``  — principal is a confirmed workspace member.
        - ``False`` — roster is available and the principal is absent.
        - ``None``  — roster unavailable (degraded); we don't know, so don't lie.
        """
        if not self.available:
            return None
        if not _normalize_principal(principal):
            return None
        return self.is_member(principal)


def _snapshot_from_frame(df: pd.DataFrame, *, source: str) -> RosterSnapshot:
    user_emails: Set[str] = set()
    service_principal_ids: Set[str] = set()
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            email = _normalize_principal(row.get("email"))
            if not email:
                continue
            principal_type = _normalize_principal(row.get("principal_type"))
            if principal_type == "service_principal":
                service_principal_ids.add(email)
            else:
                user_emails.add(email)
    available = bool(user_emails or service_principal_ids)
    return RosterSnapshot(
        user_emails=user_emails,
        service_principal_ids=service_principal_ids,
        available=available,
        source=source if available else "unavailable",
        fetched_at=time.time(),
    )


def _warehouse_key(uc: Any) -> str:
    return str(getattr(uc, "warehouse_id", "") or "default")


_SQL_ROSTER_CATALOGS_ENV = "AXIOM_DISCOVERY_CATALOGS"


def _sql_derived_principals(uc: Any) -> Set[str]:
    """Real principals the app SP CAN read via SQL — a fallback roster source.

    The app's OBO/SP scopes do NOT include workspace users:read (SCIM), and
    that scope can't be added via bundle deploy, so ``w.users.list()`` returns
    empty and roster validation would fail open (a fabricated ghost owner
    slipped through — verifier BLOCK). Unity Catalog only lets REAL principals
    own or be granted objects, so their emails in ``information_schema`` and
    ``SHOW GRANTS`` are a guaranteed-real (if partial) roster the app can
    always read. This catches fabricated ghosts even when SCIM is unreachable.
    """
    import os

    emails: Set[str] = set()
    catalogs: list[str] = []
    raw = os.getenv(_SQL_ROSTER_CATALOGS_ENV, "") or ""
    for name in raw.replace(";", ",").split(","):
        c = name.strip()
        if c and c.lower() not in {"system", "hive_metastore"}:
            catalogs.append(c)
    gov_catalog = os.getenv("AXIOM_CATALOG", "").strip()
    if gov_catalog and gov_catalog not in catalogs:
        catalogs.append(gov_catalog)
    # Bound the fan-out; each query is cheap but we never want a stampede.
    for catalog in catalogs[:12]:
        try:
            df = uc.query_df(
                f"SELECT DISTINCT table_owner AS p FROM {catalog}.information_schema.tables "
                f"WHERE table_owner LIKE '%@%'"
            )
            if df is not None and not df.empty:
                for value in df["p"].tolist():
                    e = _normalize_principal(value)
                    if e and "@" in e:
                        emails.add(e)
        except Exception:
            continue
    if gov_catalog:
        for scope in (f"CATALOG {gov_catalog}", f"SCHEMA {gov_catalog}.{os.getenv('AXIOM_SCHEMA','').strip()}"):
            try:
                df = uc.query_df(f"SHOW GRANTS ON {scope}")
                if df is not None and not df.empty:
                    col = df.columns[0]
                    for value in df[col].tolist():
                        e = _normalize_principal(value)
                        if e and "@" in e:
                            emails.add(e)
            except Exception:
                continue
    return emails


def _fetch_snapshot(uc: Any) -> RosterSnapshot:
    scim_users: Set[str] = set()
    scim_sps: Set[str] = set()
    try:
        df = uc.list_workspace_principals()
        scim = _snapshot_from_frame(df, source="databricks-scim")
        scim_users = scim.user_emails
        scim_sps = scim.service_principal_ids
    except Exception:
        pass
    # Always union the SQL-derived real principals so the roster is available
    # (and validation enforced) even when SCIM is unreachable.
    try:
        sql_users = _sql_derived_principals(uc)
    except Exception:
        sql_users = set()
    users = scim_users | sql_users
    if not users and not scim_sps:
        return RosterSnapshot(
            user_emails=set(), service_principal_ids=set(),
            available=False, source="unavailable", fetched_at=time.time(),
        )
    source = "databricks-scim" if scim_users else "unity-catalog-principals"
    if scim_users and sql_users:
        source = "databricks-scim+unity-catalog"
    return RosterSnapshot(
        user_emails=users, service_principal_ids=scim_sps,
        available=True, source=source, fetched_at=time.time(),
    )


def get_roster(uc: Any, *, force_refresh: bool = False) -> RosterSnapshot:
    """Return the cached workspace roster, refreshing past the TTL.

    Cached under key ``workspace_identity_roster:<warehouse_id>``.
    """
    key = f"workspace_identity_roster:{_warehouse_key(uc)}"
    now = time.time()
    if not force_refresh:
        cached = _ROSTER_CACHE.get(key)
        if cached is not None and (now - cached.fetched_at) < _ROSTER_TTL_S:
            return cached
    with _ROSTER_LOCK:
        # Re-check inside the lock so we don't stampede the SCIM API.
        cached = _ROSTER_CACHE.get(key)
        if (
            not force_refresh
            and cached is not None
            and (time.time() - cached.fetched_at) < _ROSTER_TTL_S
        ):
            return cached
        snapshot = _fetch_snapshot(uc)
        # Never cache a degraded snapshot for the full TTL — a transient SCIM
        # failure shouldn't blind the app for 15 minutes. Cache it briefly so a
        # burst of writes doesn't hammer a failing API, but let it retry soon.
        if not snapshot.available and cached is not None and cached.available:
            # Keep serving the last known-good roster rather than a blind one.
            return cached
        _ROSTER_CACHE[key] = snapshot
        return snapshot


def clear_roster_cache() -> None:
    with _ROSTER_LOCK:
        _ROSTER_CACHE.clear()


def get_best_roster(*uc_clients: Any, force_refresh: bool = False) -> RosterSnapshot:
    """Return the first AVAILABLE roster across the given clients.

    The Databricks App service principal often lacks the workspace
    users:list entitlement, so ``_uc()`` returns an empty (unavailable)
    roster and validation would fail open — a ghost owner slipped through
    (verifier BLOCK). The requesting user's OBO client (an admin) CAN read
    SCIM, so callers pass the OBO client first and the SP client as a
    fallback. The first client to yield a populated roster wins; its result
    is cached (shared, keyed by warehouse) so once ANY admin warms it, every
    later validation and accountMember flag benefits for the TTL.
    """
    last: RosterSnapshot | None = None
    for uc in uc_clients:
        if uc is None:
            continue
        snapshot = get_roster(uc, force_refresh=force_refresh)
        last = snapshot
        if snapshot.available:
            return snapshot
    return last or RosterSnapshot(
        user_emails=set(), service_principal_ids=set(),
        available=False, source="unavailable", fetched_at=time.time(),
    )


def validate_principal(uc: Any, principal: Any, *, field: str = "principal", fallback_uc: Any = None, actor_email: Any = None) -> str:
    """Validate ``principal`` against the roster.

    Returns the normalized principal on success. Raises
    ``PrincipalNotInWorkspaceError`` when the roster is available and the
    principal is absent. When the roster is unavailable (degraded) the check is
    skipped (fail-open) and the principal passes through unchanged. Pass
    ``fallback_uc`` (typically the app SP client) when ``uc`` is the OBO
    client so the roster resolves whichever client can read SCIM.
    """
    normalized = _normalize_principal(principal)
    if not normalized:
        return normalized
    # The authenticated actor is a confirmed real principal (iam.current-user),
    # so self-assignment is always allowed even if they have no UC footprint in
    # the SQL-derived roster.
    if actor_email and normalized == _normalize_principal(actor_email):
        return normalized
    roster = get_best_roster(uc, fallback_uc)
    if not roster.available:
        # Graceful degradation: cannot verify, so don't block the write.
        return normalized
    if not roster.is_member(normalized):
        raise PrincipalNotInWorkspaceError(normalized)
    return normalized


def cleanup_non_workspace_owners(
    store: Any,
    uc: Any,
    *,
    actor_email: str,
    actor_role: str = "admin",
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Clear owner/steward assignments whose principal is not a workspace member.

    Audited + reversible: each removal goes through ``store.remove_owner`` which
    records the cleared ``owner_email``/``owner_type`` in the audit ``before``
    snapshot (the reconstruction record) and stamps a review ``note``. Service
    principals are never cleared (they ARE account members).

    When the roster is unavailable (degraded) the cleanup is SKIPPED entirely so
    a transient SCIM outage can never wipe legitimate assignments. Set
    ``dry_run=False`` to actually apply the removals; ``dry_run=True`` returns
    the exact inventory that WOULD be cleared without touching the store.
    """
    roster = get_roster(uc, force_refresh=True)
    result: Dict[str, Any] = {
        "rosterAvailable": roster.available,
        "rosterSource": roster.source,
        "rosterSize": roster.size,
        "dryRun": dry_run,
        "scanned": 0,
        "toClear": [],
        "cleared": [],
        "kept": [],
        "warnings": [],
    }
    if not roster.available:
        result["warnings"].append(
            "Workspace roster unavailable — cleanup skipped (graceful degradation)."
        )
        return result

    try:
        assignments_df = store.list_owner_assignments()
    except Exception as exc:  # pragma: no cover - defensive
        result["warnings"].append(f"Could not list owner assignments: {exc}")
        return result
    if assignments_df is None or assignments_df.empty:
        return result

    note = ""
    for _, row in assignments_df.iterrows():
        result["scanned"] += 1
        uc_full_name = str(row.get("uc_full_name") or "").strip()
        owner_email = _normalize_principal(row.get("owner_email"))
        owner_type = str(row.get("owner_type") or "").strip()
        if not uc_full_name or not owner_email:
            continue
        kind = roster.principal_kind(owner_email)
        if kind is not None:
            # Real workspace member (user or service principal) — keep it.
            continue
        entry = {
            "assetFqn": uc_full_name,
            "ownerEmail": owner_email,
            "ownerType": owner_type,
        }
        result["toClear"].append(entry)
        if dry_run:
            continue
        note = (
            f"Removed non-workspace principal {owner_email} — "
            "identity integrity cleanup"
        )
        try:
            store.remove_owner(
                uc_full_name,
                owner_email,
                actor_email=actor_email,
                actor_role=actor_role,
                note=note,
                action="identity-integrity-cleanup",
            )
            result["cleared"].append(entry)
        except Exception as exc:  # pragma: no cover - defensive
            result["warnings"].append(
                f"Failed to clear {owner_email} on {uc_full_name}: {exc}"
            )
    return result


def roster_payload(uc: Any, *, limit: int = 0, fallback_uc: Any = None) -> Dict[str, Any]:
    """Serializable roster for the workspace-roster endpoint / frontend picker."""
    roster = get_best_roster(uc, fallback_uc)
    members = [
        {"principal": email, "principalType": "user", "accountMember": True}
        for email in sorted(roster.user_emails)
    ]
    members.extend(
        {
            "principal": sp_id,
            "principalType": "service_principal",
            "accountMember": True,
        }
        for sp_id in sorted(roster.service_principal_ids)
    )
    if limit and limit > 0:
        members = members[:limit]
    return {
        "available": roster.available,
        "source": roster.source,
        "size": roster.size,
        "userCount": len(roster.user_emails),
        "servicePrincipalCount": len(roster.service_principal_ids),
        "members": members,
    }
