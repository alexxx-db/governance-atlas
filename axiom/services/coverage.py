"""Admin coverage dashboard.

Computes per-tier + per-domain metadata completeness over the
discovery inventory. A "required" field set is configurable per
request; each asset contributes 1 if every required field is
populated, else 0. The drilldown returns up to `limit` non-compliant
assets for any (tier, domain, missingField) slice.

This is an in-memory aggregate over the already-cached discovery
index — fine for demo scale. For a 50k-table catalog the right move
is a warehouse-side SQL push-down joining `information_schema.tags`;
the service shape stays identical when that swap happens.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from axiom.services import assets as asset_service
from axiom.services.live_metadata import HIDDEN_CATALOGS

DEFAULT_REQUIRED_FIELDS = (
    "owner",
    "domain",
    "tier",
    "business_criticality",
    "sensitivity",
    "description",
)

_PLACEHOLDER_VALUES = {"unassigned", "—", "", "none"}
_DESCRIPTION_PLACEHOLDER = "No description has been captured for this asset yet."


def _field_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() not in _PLACEHOLDER_VALUES


def _description_present(value: Any) -> bool:
    if not _field_present(value):
        return False
    return str(value).strip() != _DESCRIPTION_PLACEHOLDER


def _has_owner(asset: Dict[str, Any]) -> bool:
    owners = asset.get("owners")
    if isinstance(owners, list):
        for entry in owners:
            if isinstance(entry, dict):
                email = str(entry.get("email") or entry.get("ownerEmail") or "").strip()
                name = str(entry.get("name") or entry.get("displayName") or "").strip()
                if email or name:
                    return True
            elif str(entry or "").strip():
                return True
    return False


FIELD_ACCESSORS = {
    "owner": _has_owner,
    "domain": lambda asset: _field_present(asset.get("domain")),
    "tier": lambda asset: _field_present(asset.get("tier")),
    "certification": lambda asset: _field_present(asset.get("certification")),
    "sensitivity": lambda asset: _field_present(asset.get("sensitivity")),
    "criticality": lambda asset: _field_present(asset.get("criticality")),
    "business_criticality": lambda asset: _field_present(
        asset.get("businessCriticality") or asset.get("business_criticality")
    ),
    "description": lambda asset: _description_present(asset.get("description")),
    "cde": lambda asset: bool(asset.get("isCde")),
}


def _select_fields(selected: Optional[Sequence[str]]) -> tuple[str, ...]:
    if not selected:
        return DEFAULT_REQUIRED_FIELDS
    normalized = tuple(
        str(field or "").strip().lower()
        for field in selected
        if str(field or "").strip().lower() in FIELD_ACCESSORS
    )
    return normalized or DEFAULT_REQUIRED_FIELDS


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


def coverage_aggregate(
    inventory_or_uc,
    store=None,
    *,
    required_fields: Optional[Sequence[str]] = None,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> Dict[str, Any]:
    """Return overall + per-tier + per-domain + per-field coverage."""
    index_entries = asset_service.cached_discovery_index(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )
    fields = _select_fields(required_fields)
    total = 0
    compliant = 0
    by_tier: Dict[str, Dict[str, Any]] = {}
    by_domain: Dict[str, Dict[str, Any]] = {}
    by_field: Dict[str, Dict[str, int]] = {
        field: {"total": 0, "present": 0} for field in fields
    }

    for entry in index_entries:
        asset = entry.get("asset") if isinstance(entry, dict) else None
        if not isinstance(asset, dict):
            continue
        total += 1
        tier = str(asset.get("tier") or "Unassigned").strip() or "Unassigned"
        domain = str(asset.get("domain") or "Unassigned").strip() or "Unassigned"
        tier_bucket = by_tier.setdefault(
            tier, {"total": 0, "compliant": 0, "missingByField": {}}
        )
        domain_bucket = by_domain.setdefault(
            domain, {"total": 0, "compliant": 0, "missingByField": {}}
        )
        tier_bucket["total"] += 1
        domain_bucket["total"] += 1
        row_ok = True
        for field in fields:
            present = bool(FIELD_ACCESSORS[field](asset))
            by_field[field]["total"] += 1
            if present:
                by_field[field]["present"] += 1
            else:
                row_ok = False
                tier_bucket["missingByField"][field] = (
                    tier_bucket["missingByField"].get(field, 0) + 1
                )
                domain_bucket["missingByField"][field] = (
                    domain_bucket["missingByField"].get(field, 0) + 1
                )
        if row_ok:
            compliant += 1
            tier_bucket["compliant"] += 1
            domain_bucket["compliant"] += 1

    by_tier_out = [
        {
            "tier": tier,
            "total": bucket["total"],
            "compliant": bucket["compliant"],
            "compliancePct": _pct(bucket["compliant"], bucket["total"]),
            "missingByField": bucket["missingByField"],
        }
        for tier, bucket in sorted(by_tier.items(), key=lambda kv: kv[0].lower())
    ]
    by_domain_out = [
        {
            "domain": domain,
            "total": bucket["total"],
            "compliant": bucket["compliant"],
            "compliancePct": _pct(bucket["compliant"], bucket["total"]),
            "missingByField": bucket["missingByField"],
        }
        for domain, bucket in sorted(by_domain.items(), key=lambda kv: kv[0].lower())
    ]
    by_field_out = [
        {
            "field": field,
            "total": stats["total"],
            "present": stats["present"],
            "missing": stats["total"] - stats["present"],
            "coveragePct": _pct(stats["present"], stats["total"]),
        }
        for field, stats in by_field.items()
    ]

    return {
        "overall": {
            "total": total,
            "compliant": compliant,
            "compliancePct": _pct(compliant, total),
        },
        "requiredFields": list(fields),
        "byField": by_field_out,
        "byTier": by_tier_out,
        "byDomain": by_domain_out,
    }


def coverage_drilldown(
    inventory_or_uc,
    store=None,
    *,
    required_fields: Optional[Sequence[str]] = None,
    tier: Optional[str] = None,
    domain: Optional[str] = None,
    missing_field: Optional[str] = None,
    limit: int = 200,
    hidden_catalogs: Sequence[str] = HIDDEN_CATALOGS,
) -> Dict[str, Any]:
    """List up to `limit` non-compliant assets matching the filter."""
    safe_limit = max(1, min(int(limit or 200), 500))
    fields = _select_fields(required_fields)
    target_field = str(missing_field or "").strip().lower() or None
    if target_field and target_field not in FIELD_ACCESSORS:
        target_field = None

    index_entries = asset_service.cached_discovery_index(
        inventory_or_uc,
        store,
        hidden_catalogs=hidden_catalogs,
    )
    matched: List[Dict[str, Any]] = []
    for entry in index_entries:
        asset = entry.get("asset") if isinstance(entry, dict) else None
        if not isinstance(asset, dict):
            continue
        if tier and str(asset.get("tier") or "Unassigned").strip() != tier:
            continue
        if domain and str(asset.get("domain") or "Unassigned").strip() != domain:
            continue
        missing_fields = [
            field for field in fields if not FIELD_ACCESSORS[field](asset)
        ]
        if not missing_fields:
            continue
        if target_field and target_field not in missing_fields:
            continue
        matched.append(
            {
                "fqn": str(asset.get("fqn") or ""),
                "name": str(asset.get("name") or ""),
                "catalog": str(asset.get("catalog") or ""),
                "schema": str(asset.get("schema") or ""),
                "domain": str(asset.get("domain") or "Unassigned"),
                "tier": str(asset.get("tier") or "Unassigned"),
                "businessCriticality": str(
                    asset.get("businessCriticality")
                    or asset.get("business_criticality")
                    or "Unassigned"
                ),
                "missingFields": missing_fields,
            }
        )
        if len(matched) >= safe_limit:
            break

    return {
        "items": matched,
        "limit": safe_limit,
        "requiredFields": list(fields),
    }
