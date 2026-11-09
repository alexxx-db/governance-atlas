"""Pure request-identity helpers for the Axiom API.

Reads forwarded Databricks identity/authorization headers — does not touch the
governance store, UC client, or AppConfig. Role resolution that requires the
store stays in runtime_app.py.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request

from axiom.services import capabilities as capability_service


def _request_obo_token(request: Optional[Request]) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    raw = getter("x-forwarded-access-token") or getter("X-Forwarded-Access-Token") or ""
    return raw.strip()


def _user_email(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    headers = getattr(request, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return "unknown"
    email = (
        getter("x-forwarded-email") or getter("x-forwarded-preferred-username") or ""
    )
    return email.strip().lower() or "unknown"


def _user_display_name(request: Optional[Request]) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", None) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    display_value = (
        getter("x-forwarded-display-name")
        or getter("x-forwarded-name")
        or ""
    )
    if str(display_value or "").strip():
        return str(display_value).strip()

    preferred_username = (
        getter("x-forwarded-preferred-username")
        or getter("x-forwarded-email")
        or ""
    )
    if str(preferred_username or "").strip():
        return str(preferred_username).strip()

    forwarded_user = str(getter("x-forwarded-user") or "").strip()
    if forwarded_user and not forwarded_user.isdigit():
        return forwarded_user
    return ""


def _request_auth_mode(request: Optional[Request]) -> str:
    return capability_service.runtime_auth_mode(
        authenticated=_user_email(request) != "unknown"
        if request is not None
        else False,
        per_user_authorization=bool(_request_obo_token(request)),
    )


def _request_read_visibility_scope(request: Optional[Request]) -> str:
    return capability_service.runtime_visibility_scope(_request_auth_mode(request))
