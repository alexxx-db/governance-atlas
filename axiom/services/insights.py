"""A9.5 — UC/Delta governance insights.

Computes a cross-inventory gap analysis over the visible-assets DataFrame
plus the recent quality_run_result ledger. Produces tile counts + per-lane
gap rows with evidence-linked remediation hrefs that point at the existing
governance workbench (no new routes / no new data collection).

Four lanes, all derived from signals the inventory + quality_runner
already track:

- **ownership**: rows with zero entries from `assets.owner_entries(row)`.
- **policy**: rows where sensitivity, certification, domain, and tier are
  all empty/"Unassigned". Missing-field list is surfaced in `gapReason`.
- **freshness**: rows with no recent freshness signal. We prefer the
  inventory column `last_observed_at` when present; when absent we fall
  back to "passed a `freshness`-keyed quality_run_result in the last 7
  days." If neither signal is present the row is reported with gapReason
  "No freshness signal available."
- **quality**: rows with at least one `quality_run_result.outcome in
  ("failed", "errored")` in the last 7 days. Evidence lists the failed
  case_id / outcome / detail so the remediation link can deep-link into
  the governance workbench with context.

Remediation hrefs target the existing `/governance` surface with query
params only (`?lane=<lane>&asset=<fqn>`), so this module doesn't invent
new endpoints or surfaces.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import pandas as pd

from axiom.services import assets as asset_service
from axiom.services.assets import normalize_str as _normalize_str


# Public lane keys the UI contract depends on.
LANE_OWNERSHIP = "ownership"
LANE_POLICY = "policy"
LANE_FRESHNESS = "freshness"
LANE_QUALITY = "quality"
LANES = (LANE_OWNERSHIP, LANE_POLICY, LANE_FRESHNESS, LANE_QUALITY)

# How far back a quality_run_result counts as "recent" for the quality
# incidents + fallback freshness lanes.
QUALITY_INCIDENT_WINDOW_DAYS = 7

# Policy-gap criteria: every one of these must be blank / "Unassigned"
# for a row to count as a policy gap. Keeping this list here so it is
# tested directly.
POLICY_FIELDS: tuple[tuple[str, str], ...] = (
    ("sensitivity", "sensitivity"),
    ("certification", "certification"),
    ("domain", "domain"),
    ("tier", "tier"),
)


def _is_blank(value: Any) -> bool:
    """Return True when a normalized value is either blank or the
    sentinel `"Unassigned"` string the inventory uses for unset policy
    fields."""

    normalized = _normalize_str(value)
    if not normalized:
        return True
    return normalized.lower() == "unassigned"


def _row_fqn(row: pd.Series) -> str:
    fqn = _normalize_str(row.get("fqn"))
    if fqn:
        return fqn
    catalog = _normalize_str(row.get("table_catalog"))
    schema = _normalize_str(row.get("table_schema"))
    table = _normalize_str(row.get("table_name"))
    parts = [p for p in (catalog, schema, table) if p]
    return ".".join(parts)


def _row_name(row: pd.Series) -> str:
    name = _normalize_str(row.get("table_name"))
    if name:
        return name
    fqn = _row_fqn(row)
    if "." in fqn:
        return fqn.split(".")[-1]
    return fqn


def _row_object_type(row: pd.Series) -> str:
    raw_type = row.get("table_type")
    raw_format = row.get("data_source_format")
    try:
        return asset_service.friendly_table_type(raw_type, raw_format)
    except Exception:
        return _normalize_str(raw_type) or "Asset"


def _policy_missing_fields(row: pd.Series) -> List[str]:
    missing: List[str] = []
    for field, label in POLICY_FIELDS:
        if _is_blank(row.get(field)):
            missing.append(label)
    return missing


def _ownership_missing(row: pd.Series) -> bool:
    try:
        owners = asset_service.owner_entries(row)
    except Exception:
        owners = []
    return not bool(owners)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = _normalize_str(value)
    if not text:
        return None
    # Support both "Z" and "+00:00" endings; also tolerate bare date/datetime.
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if parsed is None or pd.isna(parsed):
        return None
    try:
        return parsed.to_pydatetime()
    except Exception:
        return None


def _freshness_signal(row: pd.Series) -> Optional[datetime]:
    """Return the best freshness signal on `row`, if any.

    Currently looks at `last_observed_at` — the spec calls out that the
    column may not exist yet, in which case we fall back to the
    quality-run ledger join. Returning None from here means "inventory
    has no freshness signal for this row."
    """

    for field in ("last_observed_at", "lastObservedAt", "last_modified_at"):
        value = row.get(field) if field in row else None
        parsed = _parse_timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _quality_incidents_by_entity(
    quality_df: Optional[pd.DataFrame],
    *,
    now: Optional[datetime] = None,
    window_days: int = QUALITY_INCIDENT_WINDOW_DAYS,
) -> Dict[str, List[Dict[str, Any]]]:
    """Group failed / errored quality_run_result rows by entity_fqn.

    The quality_runner persists one row per case so we can aggregate
    here without duplicating ledger state. Older-than-window rows are
    dropped; empty/None frames are handled defensively.
    """

    if quality_df is None:
        return {}
    try:
        empty = bool(getattr(quality_df, "empty", True))
    except Exception:
        empty = True
    if empty:
        return {}

    reference = now or datetime.now(timezone.utc)
    window_start = reference - timedelta(days=int(window_days))
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for _, row in quality_df.iterrows():
        outcome = _normalize_str(row.get("outcome")).lower()
        if outcome not in {"failed", "errored"}:
            continue
        entity = _normalize_str(row.get("entity_fqn"))
        if not entity:
            continue
        ts = _parse_timestamp(row.get("executed_at"))
        if ts is None or ts < window_start:
            continue
        grouped.setdefault(entity, []).append(
            {
                "caseId": _normalize_str(row.get("case_id")),
                "runId": _normalize_str(row.get("run_id")),
                "outcome": outcome,
                "severity": _normalize_str(row.get("severity")) or "warn",
                "detail": _normalize_str(row.get("detail")),
                "executedAt": ts.isoformat().replace("+00:00", "Z"),
            }
        )
    return grouped


def _quality_freshness_pass_by_entity(
    quality_df: Optional[pd.DataFrame],
    *,
    now: Optional[datetime] = None,
    window_days: int = QUALITY_INCIDENT_WINDOW_DAYS,
) -> Dict[str, datetime]:
    """Map entity_fqn -> most recent freshness-case pass timestamp.

    Used as the fallback freshness signal when the inventory doesn't
    carry a `last_observed_at` column. Only `outcome == "passed"`
    results where the case_id contains `"freshness"` count.
    """

    if quality_df is None:
        return {}
    try:
        empty = bool(getattr(quality_df, "empty", True))
    except Exception:
        empty = True
    if empty:
        return {}

    reference = now or datetime.now(timezone.utc)
    window_start = reference - timedelta(days=int(window_days))
    best: Dict[str, datetime] = {}
    for _, row in quality_df.iterrows():
        outcome = _normalize_str(row.get("outcome")).lower()
        if outcome != "passed":
            continue
        case_id = _normalize_str(row.get("case_id")).lower()
        test_key = _normalize_str(row.get("test_key")).lower()
        # Two signals we treat as a freshness pass: case_id contains
        # "freshness" (naming convention used by operator suites) OR the
        # row carries a `test_key` column equal to "freshness" (if the
        # store projects test_key through).
        if "freshness" not in case_id and test_key != "freshness":
            continue
        entity = _normalize_str(row.get("entity_fqn"))
        if not entity:
            continue
        ts = _parse_timestamp(row.get("executed_at"))
        if ts is None or ts < window_start:
            continue
        existing = best.get(entity)
        if existing is None or ts > existing:
            best[entity] = ts
    return best


def _remediation_href(lane: str, asset_fqn: str) -> str:
    """Build the deep-link query-string href for a gap row.

    Intentionally a query-string-only URL against the existing
    `/governance` surface so we don't invent new routes. Callers can
    hand this straight to `<a href>` or `history.push`.
    """

    encoded = quote(asset_fqn, safe="")
    return f"/governance?lane={lane}&asset={encoded}"


_REMEDIATION_LABELS: Dict[str, Dict[str, str]] = {
    LANE_OWNERSHIP: {"label": "Assign owner", "action": "governance.requestOwner"},
    LANE_POLICY: {
        "label": "Approve classification",
        "action": "governance.approveClassification",
    },
    LANE_FRESHNESS: {"label": "Run profile", "action": "governance.runProfile"},
    LANE_QUALITY: {
        "label": "View quality incident",
        "action": "governance.viewQualityIncident",
    },
}


def _remediation(lane: str, asset_fqn: str) -> Dict[str, Any]:
    base = _REMEDIATION_LABELS.get(lane, {"label": "Open in Governance", "action": "governance.open"})
    return {
        "label": base["label"],
        "action": base["action"],
        "href": _remediation_href(lane, asset_fqn),
    }


def _gap_row(
    row: pd.Series,
    *,
    lane: str,
    reason: str,
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    asset_fqn = _row_fqn(row)
    return {
        "assetFqn": asset_fqn,
        "assetName": _row_name(row),
        "objectType": _row_object_type(row),
        "gapKind": lane,
        "gapReason": reason,
        "evidence": list(evidence or []),
        "remediation": _remediation(lane, asset_fqn),
    }


def compute_gap_analysis(
    inv_df: Optional[pd.DataFrame],
    quality_df: Optional[pd.DataFrame] = None,
    *,
    limit: int = 200,
    now: Optional[datetime] = None,
    freshness_window_days: int = QUALITY_INCIDENT_WINDOW_DAYS,
) -> Dict[str, Any]:
    """Compute the governance-insights envelope.

    Parameters
    ----------
    inv_df:
        The visible-assets DataFrame produced by
        `axiom.services.inventory.visible_assets`. An empty frame /
        `None` yields zero tiles and empty lanes (degraded but shaped).
    quality_df:
        Output of `store.list_quality_run_results(limit=...)`. Used for
        the quality-incidents lane and the freshness fallback.
    limit:
        Per-lane row cap. Tile counts reflect the TRUE dataset size, so
        a lane with 500 gaps reports `tiles.policyGaps == 500` even when
        `lanes.policy` is capped at `limit`.
    now / freshness_window_days:
        Exposed so tests can drive deterministic windowing.
    """

    reference_now = now or datetime.now(timezone.utc)
    lanes: Dict[str, List[Dict[str, Any]]] = {lane: [] for lane in LANES}
    tile_counts: Dict[str, int] = {
        "ownershipGaps": 0,
        "policyGaps": 0,
        "freshnessGaps": 0,
        "qualityIncidents": 0,
    }

    quality_by_entity = _quality_incidents_by_entity(
        quality_df,
        now=reference_now,
        window_days=freshness_window_days,
    )
    freshness_passes = _quality_freshness_pass_by_entity(
        quality_df,
        now=reference_now,
        window_days=freshness_window_days,
    )

    total_assets = 0
    inventory_has_freshness_column = False
    if inv_df is not None and not getattr(inv_df, "empty", True):
        try:
            columns_list = list(inv_df.columns)
        except Exception:
            columns_list = []
        inventory_has_freshness_column = any(
            column in columns_list
            for column in ("last_observed_at", "lastObservedAt", "last_modified_at")
        )
        for _, row in inv_df.iterrows():
            total_assets += 1
            asset_fqn = _row_fqn(row)
            if not asset_fqn:
                continue

            # ---- Ownership lane ----
            if _ownership_missing(row):
                tile_counts["ownershipGaps"] += 1
                if len(lanes[LANE_OWNERSHIP]) < limit:
                    lanes[LANE_OWNERSHIP].append(
                        _gap_row(
                            row,
                            lane=LANE_OWNERSHIP,
                            reason="No owners assigned",
                            evidence=[
                                {
                                    "kind": "ownerCount",
                                    "value": 0,
                                }
                            ],
                        )
                    )

            # ---- Policy lane ----
            missing_policy = _policy_missing_fields(row)
            if len(missing_policy) == len(POLICY_FIELDS):
                tile_counts["policyGaps"] += 1
                if len(lanes[LANE_POLICY]) < limit:
                    lanes[LANE_POLICY].append(
                        _gap_row(
                            row,
                            lane=LANE_POLICY,
                            reason=(
                                "Missing " + ", ".join(missing_policy)
                            ),
                            evidence=[
                                {
                                    "kind": "missingFields",
                                    "fields": list(missing_policy),
                                }
                            ],
                        )
                    )

            # ---- Freshness lane ----
            inventory_signal = _freshness_signal(row)
            fallback_pass = freshness_passes.get(asset_fqn)
            freshness_ok = False
            evidence_kind = "none"
            if inventory_signal is not None:
                freshness_ok = (reference_now - inventory_signal) <= timedelta(
                    days=int(freshness_window_days)
                )
                evidence_kind = "last_observed_at"
            elif fallback_pass is not None:
                freshness_ok = True  # already within window by construction
                evidence_kind = "quality_freshness_pass"
            if not freshness_ok:
                tile_counts["freshnessGaps"] += 1
                if len(lanes[LANE_FRESHNESS]) < limit:
                    if inventory_signal is not None:
                        reason = (
                            "Last observation is older than "
                            f"{freshness_window_days} days"
                        )
                        evidence = [
                            {
                                "kind": "last_observed_at",
                                "value": inventory_signal.isoformat().replace(
                                    "+00:00", "Z"
                                ),
                            }
                        ]
                    elif inventory_has_freshness_column:
                        reason = "No recent freshness signal"
                        evidence = [{"kind": "last_observed_at", "value": None}]
                    else:
                        reason = "No freshness signal available"
                        evidence = [{"kind": "none"}]
                    lanes[LANE_FRESHNESS].append(
                        _gap_row(
                            row,
                            lane=LANE_FRESHNESS,
                            reason=reason,
                            evidence=evidence,
                        )
                    )

            # ---- Quality lane ----
            incidents = quality_by_entity.get(asset_fqn) or []
            if incidents:
                tile_counts["qualityIncidents"] += 1
                if len(lanes[LANE_QUALITY]) < limit:
                    severities = {inc.get("severity") for inc in incidents}
                    outcomes = {inc.get("outcome") for inc in incidents}
                    reason_parts: List[str] = []
                    if "errored" in outcomes:
                        reason_parts.append(f"{sum(1 for i in incidents if i.get('outcome') == 'errored')} errored")
                    if "failed" in outcomes:
                        reason_parts.append(f"{sum(1 for i in incidents if i.get('outcome') == 'failed')} failed")
                    reason = (
                        "Quality incidents in the last "
                        f"{freshness_window_days} days: " + ", ".join(reason_parts)
                    )
                    lanes[LANE_QUALITY].append(
                        _gap_row(
                            row,
                            lane=LANE_QUALITY,
                            reason=reason,
                            evidence=incidents,
                        )
                    )

    tiles = dict(tile_counts)
    tiles["totalAssets"] = total_assets
    return {
        "tiles": tiles,
        "lanes": lanes,
    }


__all__ = [
    "LANES",
    "LANE_OWNERSHIP",
    "LANE_POLICY",
    "LANE_FRESHNESS",
    "LANE_QUALITY",
    "POLICY_FIELDS",
    "QUALITY_INCIDENT_WINDOW_DAYS",
    "compute_gap_analysis",
]
