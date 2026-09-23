"""Guards for the G3 role-assignment endpoints (GET/PUT /api/admin/roles).

Both are admin-only with the same three-layer defense the branding routes use:
  1. _ensure_live_runtime()
  2. _ensure_can_mutate() — rejects reader with 403
  3. explicit admin check — rejects writer/steward with 403
Plus PUT validation of email + assignable role.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from types import ModuleType, SimpleNamespace

import pandas as pd

from test_admin_branding_gate import _find_route, _load_admin_module

admin = _load_admin_module()


def _fake_runtime(role: str, *, captured: dict | None = None) -> ModuleType:
    from fastapi import HTTPException

    module = ModuleType("runtime_app")

    def _ensure_live_runtime():
        return None

    def _ensure_can_mutate(request):
        if role == "reader":
            raise HTTPException(status_code=403, detail="reader cannot mutate")
        return "admin@example.com"

    def _user_role_slug(request):
        return role

    def _ensure_governance_store():
        return None

    class _FakeStore:
        def list_roles(self):
            return pd.DataFrame(
                [{"email": "steward@example.com", "role": "steward", "updated_at": "t", "updated_by": "admin@example.com"}]
            )

        def upsert_role(self, email, role, updated_by):
            if captured is not None:
                captured.update({"email": email, "role": role, "updated_by": updated_by})

    module._ensure_live_runtime = _ensure_live_runtime
    module._ensure_can_mutate = _ensure_can_mutate
    module._user_role_slug = _user_role_slug
    module._ensure_governance_store = _ensure_governance_store
    module._store = lambda: _FakeStore()
    module._config = lambda: SimpleNamespace(admin_emails=["boss@example.com"])
    return module


class RolesGetGateTests(unittest.TestCase):
    def setUp(self) -> None:
        router = admin.build_admin_router()
        try:
            self.endpoint = _find_route(router, "GET", "/api/admin/roles")
        except AssertionError:
            self.endpoint = _find_route(router, "GET", "/roles")

    def _call_as(self, role: str):
        from fastapi import HTTPException

        with unittest.mock.patch.dict(sys.modules, {"runtime_app": _fake_runtime(role)}):
            try:
                return self.endpoint(SimpleNamespace(headers={}))
            except HTTPException as exc:
                return exc

    def test_reader_403(self):
        from fastapi import HTTPException

        self.assertEqual(getattr(self._call_as("reader"), "status_code", None), 403)
        self.assertIsInstance(self._call_as("reader"), HTTPException)

    def test_writer_403_admin_only(self):
        self.assertEqual(self._call_as("writer").status_code, 403)

    def test_steward_403_admin_only(self):
        self.assertEqual(self._call_as("steward").status_code, 403)

    def test_admin_lists_roles_including_bootstrap_admin(self):
        result = self._call_as("admin")
        payload = getattr(result, "content", None)
        if isinstance(payload, dict):
            emails = {entry["email"] for entry in payload["roles"]}
            self.assertIn("steward@example.com", emails)
            self.assertIn("boss@example.com", emails)  # bootstrap admin surfaced
            self.assertIn("reader", payload["assignableRoles"])


class RolesPutGateTests(unittest.TestCase):
    def setUp(self) -> None:
        router = admin.build_admin_router()
        try:
            self.endpoint = _find_route(router, "PUT", "/api/admin/roles")
        except AssertionError:
            self.endpoint = _find_route(router, "PUT", "/roles")

    def _call_as(self, role: str, email: str, role_value: str, captured=None):
        from fastapi import HTTPException

        payload = admin.RolePatch(email=email, role=role_value)
        with unittest.mock.patch.dict(sys.modules, {"runtime_app": _fake_runtime(role, captured=captured)}):
            try:
                return self.endpoint(payload, SimpleNamespace(headers={}))
            except HTTPException as exc:
                return exc

    def test_non_admin_forbidden(self):
        self.assertEqual(self._call_as("steward", "u@e.ai", "writer").status_code, 403)

    def test_admin_assigns_valid_role(self):
        captured = {}
        result = self._call_as("admin", "New.User@Example.AI", "steward", captured=captured)
        self.assertEqual(getattr(result, "status_code", 200), 200)
        self.assertEqual(captured["email"], "new.user@example.ai")  # normalized
        self.assertEqual(captured["role"], "steward")

    def test_invalid_role_rejected(self):
        self.assertEqual(self._call_as("admin", "u@e.ai", "superuser").status_code, 400)

    def test_bad_email_rejected(self):
        self.assertEqual(self._call_as("admin", "not-an-email", "reader").status_code, 400)


if __name__ == "__main__":
    unittest.main()
