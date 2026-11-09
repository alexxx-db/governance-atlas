"""Canonical business-concept predicates shared by every surface.

The 2026-07 persona audits proved the app was running multiple conflicting
definitions of the same business concept (CDE count 49 vs 0, "certified"
44/45/46/47, coverage 95.5%/100%/0%) because each service module grew its own
predicate. This module is the single source of truth. Rules:

- Every endpoint that says "CDE" MUST call ``is_cde_asset``.
- Every endpoint that says "certified" MUST call ``is_certified`` (strict) —
  Trusted/Approved/Gold/Draft are never silently folded into "certified".
- Do NOT define sibling predicates in service modules; import from here so the
  numbers can never drift again.

This module must stay dependency-free (stdlib only) so any service can import
it without circular-import risk.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# Audit F4: match a standalone "cde" token only. `\b` treats "_" as a word char,
# so "cde_registry" / "cder" do NOT match (they are not CDEs); "cde", "a cde
# field", "tag:CDE" do. Replaces a bare `" cde"` substring that false-matched
# control-plane tables like `cde_registry`.
_CDE_TOKEN_RE = re.compile(r"\bcde\b", re.IGNORECASE)

# Tag values that mark an asset as business-critical (Tier 1 / Critical).
CRITICALITY_VALUES = {
    "critical",
    "high",
    "tier 1",
    "tier1",
    "tier-1",
    "p0",
    "p1",
}

# Strict certification: only an explicit "Certified" label counts. The audit
# found four different "certified" totals because some paths also counted
# Trusted/Approved/Gold; those states get their own facets instead.
CERTIFIED_STRICT_VALUES = {"certified"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN guard
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("none", "nan") else text


def _lower(value: Any) -> str:
    return _text(value).lower()


def _row_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        try:
            value = row.get(key)
        except AttributeError:
            return None
        if _text(value):
            return value
    return None


def _coerce_bool(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return _lower(value) in ("true", "1", "yes", "y", "t")


def is_critical(row: Mapping[str, Any]) -> bool:
    """Business-critical asset: criticality/tier tag in CRITICALITY_VALUES."""
    return _lower(
        _row_value(row, "criticality", "business_criticality", "businessCriticality", "tier")
    ) in CRITICALITY_VALUES


def is_certified(row: Mapping[str, Any]) -> bool:
    """Strictly certified: certification label == "Certified" only."""
    return _lower(_row_value(row, "certification", "certificationStatus")) in CERTIFIED_STRICT_VALUES


def is_cde_asset(row: Mapping[str, Any]) -> bool:
    """Canonical CDE predicate — criticality-derived plus explicit flags.

    An asset is a Critical Data Element iff ANY of:
    - an explicit boolean flag (``isCde`` / ``cde`` field, or a ``cde`` /
      ``is_cde`` entry in a tags mapping), or
    - its text metadata mentions "critical data element" or a standalone
      "cde" token, or
    - it is business-critical per :func:`is_critical`.

    UI copy must describe this as "criticality-derived", never "tag-governed"
    alone. Works over both inventory-row mappings and asset payload dicts.
    """
    if _coerce_bool(row.get("isCde")) or _coerce_bool(row.get("cde")):
        return True
    tags = row.get("tags")
    if isinstance(tags, Mapping) and (
        _coerce_bool(tags.get("cde")) or _coerce_bool(tags.get("is_cde"))
    ):
        return True
    tokens = []
    for key in (
        "fqn",
        "table_name",
        "comment",
        "description",
        "criticality",
        "business_criticality",
        "businessCriticality",
        "tags",
        "tagLabels",
        "glossaryTerms",
    ):
        value = row.get(key)
        if isinstance(value, (dict, list, tuple, set)):
            tokens.append(str(value))
        else:
            tokens.append(_text(value))
    haystack = " ".join(tokens).lower()
    return (
        "critical data element" in haystack
        or bool(_CDE_TOKEN_RE.search(haystack))
        or is_critical(row)
    )
