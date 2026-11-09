"""Unit tests for the role-resolution path that gates the admin surface.

Covers three behaviors that were untested after commits f6eb282, 21467cd,
0e72ed7 landed:

1. `_NullGovernanceStore.get_role` honors `admin_emails` — declared admins
   stay admin even when the governance store is not live.

2. `_user_role_slug` happy path preserves the table's role. An email
   listed in `AXIOM_ADMIN_EMAILS` does NOT get re-promoted to admin if
   the `user_roles` table has a demotion row for them (e.g., `"reader"`).

3. `_user_role_slug` exception path honors `admin_emails` as a safety
   net when the governance store raises.
"""
from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


def _stub_identity_module() -> None:
    """Stub axiom.api.identity so runtime_app imports cleanly in tests."""
    if "axiom.api.identity" in sys.modules:
        return
    module = ModuleType("axiom.api.identity")

    def _user_email(request):
        if request is None:
            return "unknown"
        headers = getattr(request, "headers", None) or {}
        email = (
            headers.get("x-forwarded-email")
            or headers.get("x-forwarded-preferred-username")
            or ""
        )
        return (email or "").strip().lower() or "unknown"

    module._user_email = _user_email
    module._request_auth_mode = lambda _request: "app-principal"
    module._request_read_visibility_scope = lambda _request: "app-principal"
    module._request_obo_token = lambda _request: ""
    sys.modules["axiom.api.identity"] = module


def _load_runtime_module():
    import runtime_app  # noqa: F401 — import for side effects

    return runtime_app


class NullGovernanceStoreRoleTests(unittest.TestCase):
    def setUp(self) -> None:
        _stub_identity_module()

    def test_null_store_promotes_listed_admin(self) -> None:
        runtime_app = _load_runtime_module()
        store = runtime_app._NullGovernanceStore()
        role = store.get_role(
            "admin@example.com", admin_emails=["admin@example.com"]
        )
        self.assertEqual(role, "admin")

    def test_null_store_case_insensitive_match(self) -> None:
        runtime_app = _load_runtime_module()
        store = runtime_app._NullGovernanceStore()
        role = store.get_role(
            "ADMIN@Example.COM", admin_emails=["admin@example.com"]
        )
        self.assertEqual(role, "admin")

    def test_null_store_defaults_to_reader_when_not_listed(self) -> None:
        runtime_app = _load_runtime_module()
        store = runtime_app._NullGovernanceStore()
        role = store.get_role(
            "someone@example.com", admin_emails=["admin@example.com"]
        )
        self.assertEqual(role, "reader")

    def test_null_store_ignores_empty_admin_list(self) -> None:
        runtime_app = _load_runtime_module()
        store = runtime_app._NullGovernanceStore()
        self.assertEqual(store.get_role("admin@example.com"), "reader")
        self.assertEqual(
            store.get_role("admin@example.com", admin_emails=[]), "reader"
        )
        self.assertEqual(
            store.get_role("admin@example.com", admin_emails=[""]), "reader"
        )


class UserRoleSlugTests(unittest.TestCase):
    def setUp(self) -> None:
        _stub_identity_module()

    def _request(self, email: str):
        return SimpleNamespace(headers={"x-forwarded-email": email})

    def test_returns_reader_for_unknown_email(self) -> None:
        runtime_app = _load_runtime_module()
        role = runtime_app._user_role_slug(self._request(""))
        self.assertEqual(role, "reader")

    def test_happy_path_preserves_demoted_reader_even_if_in_admin_emails(
        self,
    ) -> None:
        """Regression test: an email in AXIOM_ADMIN_EMAILS that has a
        non-admin row in user_roles MUST keep the table's role. The
        admin_emails fallback is a rescue hatch, not an override."""
        runtime_app = _load_runtime_module()

        class _FakeStore:
            def get_role(self, email, admin_emails=None):
                return "reader"

        with patch.object(runtime_app, "_store_for_read", return_value=_FakeStore()):
            with patch.object(
                runtime_app,
                "_config",
                return_value=SimpleNamespace(
                    admin_emails=["demoted@example.com"]
                ),
            ):
                role = runtime_app._user_role_slug(
                    self._request("demoted@example.com")
                )
        self.assertEqual(role, "reader")

    def test_exception_path_promotes_listed_admin(self) -> None:
        runtime_app = _load_runtime_module()

        class _RaisingStore:
            def get_role(self, email, admin_emails=None):
                raise RuntimeError("warehouse unreachable")

        with patch.object(runtime_app, "_store_for_read", return_value=_RaisingStore()):
            with patch.object(
                runtime_app,
                "_config",
                return_value=SimpleNamespace(
                    admin_emails=["rescued@example.com"]
                ),
            ):
                role = runtime_app._user_role_slug(
                    self._request("rescued@example.com")
                )
        self.assertEqual(role, "admin")

    def test_exception_path_defaults_to_reader_if_not_listed(self) -> None:
        runtime_app = _load_runtime_module()

        class _RaisingStore:
            def get_role(self, email, admin_emails=None):
                raise RuntimeError("warehouse unreachable")

        with patch.object(runtime_app, "_store_for_read", return_value=_RaisingStore()):
            with patch.object(
                runtime_app,
                "_config",
                return_value=SimpleNamespace(
                    admin_emails=["other@example.com"]
                ),
            ):
                role = runtime_app._user_role_slug(
                    self._request("random@example.com")
                )
        self.assertEqual(role, "reader")


if __name__ == "__main__":
    unittest.main()
