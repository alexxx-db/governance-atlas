"""Tenant branding (F7 — white-label palette).

Reads/writes the single-row `tenant_branding` table. Callers get a
normalized dict regardless of whether the row exists — absent fields
collapse to empty strings so frontend code can fall back to hard-coded
defaults without null-safety dances.

The service validates inputs strictly: hex colors must be 6-digit,
logo URLs must be http(s) or `data:image/`, and the display name
caps at 80 characters. Invalid input raises ValueError; the API
layer should surface that as HTTP 400.
"""
from __future__ import annotations

import re
from typing import Any, Dict

HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_PATTERN = re.compile(r"^(https?://|data:image/)", re.IGNORECASE)
MAX_LOGO_URL_LENGTH = 2048
MAX_ORG_DISPLAY_NAME_LENGTH = 80


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validate_hex(value: str, *, label: str) -> str:
    cleaned = _normalize(value)
    if not cleaned:
        return ""
    if not HEX_COLOR_PATTERN.match(cleaned):
        raise ValueError(
            f"{label} must be a 6-digit hex color like #5B43EE (got {cleaned!r})."
        )
    return cleaned


def _validate_url(value: str, *, label: str) -> str:
    cleaned = _normalize(value)
    if not cleaned:
        return ""
    if len(cleaned) > MAX_LOGO_URL_LENGTH:
        raise ValueError(
            f"{label} exceeds {MAX_LOGO_URL_LENGTH} characters; reduce the URL "
            "or host the image separately."
        )
    if not URL_PATTERN.match(cleaned):
        raise ValueError(
            f"{label} must start with https:// (preferred), http://, or data:image/."
        )
    return cleaned


def get_branding(store: Any) -> Dict[str, Any]:
    """Return the normalized branding dict — always shaped, never None."""
    raw = store.get_tenant_branding() if store is not None else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "primaryColor": _normalize(raw.get("primaryColor")),
        "accentColor": _normalize(raw.get("accentColor")),
        "logoUrl": _normalize(raw.get("logoUrl")),
        "orgDisplayName": _normalize(raw.get("orgDisplayName")),
        "updatedAt": _normalize(raw.get("updatedAt")),
        "updatedBy": _normalize(raw.get("updatedBy")),
    }


def set_branding(
    store: Any,
    *,
    primary_color: str = "",
    accent_color: str = "",
    logo_url: str = "",
    org_display_name: str = "",
    updated_by: str = "",
) -> Dict[str, Any]:
    """Persist a validated branding update. Returns the post-save
    normalized dict so the caller can echo it back."""
    primary = _validate_hex(primary_color, label="primaryColor")
    accent = _validate_hex(accent_color, label="accentColor")
    logo = _validate_url(logo_url, label="logoUrl")
    name = _normalize(org_display_name)
    if len(name) > MAX_ORG_DISPLAY_NAME_LENGTH:
        raise ValueError(
            f"orgDisplayName must be {MAX_ORG_DISPLAY_NAME_LENGTH} characters or fewer."
        )
    store.upsert_tenant_branding(
        primary_color=primary,
        accent_color=accent,
        logo_url=logo,
        org_display_name=name,
        updated_by=_normalize(updated_by),
    )
    return get_branding(store)
