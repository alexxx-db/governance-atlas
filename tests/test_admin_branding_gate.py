"""Guards for the admin branding endpoint gates (commits 21467cd +
the admin-only tightening that followed).

The write endpoint PUT /api/admin/branding has always been admin-only.
After 2026-04-23 the GET is also admin-only, with three layers of
defense in sequence:
  1. _ensure_live_runtime() — runtime availability.
  2. _ensure_can_mutate() — rejects reader role with 403.
  3. Explicit admin check — rejects writer/steward with 403.

These tests pin the behavior so a future "oops" widening gets caught.
"""
from __future__ import annotations

import sys
import unittest
import unittest.mock
from types import ModuleType, SimpleNamespace


def _load_admin_module():
    try:
        from axiom.api import admin as module

        return module
    except ModuleNotFoundError as exc:
        if exc.name not in {"fastapi", "fastapi.responses"}:
            raise

    fastapi = ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _APIRouter:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def add_api_route(self, *args, **kwargs):
            return None

        def __getattr__(self, name):
            if name in {"get", "post", "put", "patch", "delete"}:
                def decorator(*args, **kwargs):
                    def wrap(func):
                        self.routes.append((name.upper(), args[0] if args else "", func))
                        return func

                    return wrap

                return decorator
            raise AttributeError(name)

    class _Request:
        pass

    fastapi.APIRouter = _APIRouter
    fastapi.HTTPException = _HTTPException
    fastapi.Request = _Request

    responses = ModuleType("fastapi.responses")

    class _JSONResponse:
        def __init__(self, content=None, status_code=200):
            self.content = content
            self.status_code = status_code

    responses.JSONResponse = _JSONResponse

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses

    from axiom.api import admin as module  # type: ignore

    return module


admin = _load_admin_module()


def _find_route(router, method: str, path: str):
    for route in router.routes:
        # Stub router stores tuples (method, path, func).
        if isinstance(route, tuple):
            route_method, route_path, func = route
            if route_method == method and route_path == path:
                return func
            continue
        # Real fastapi router stores APIRoute objects.
        route_methods = getattr(route, "methods", set()) or set()
        route_path = getattr(route, "path", "")
        if method in route_methods and route_path == path:
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


def _fake_runtime(
    role: str,
    *,
    raise_on_mutate: bool = False,
) -> ModuleType:
    """Construct an in-memory runtime_app stand-in that the endpoint
    route's lazy imports can pull from."""
    from fastapi import HTTPException

    module = ModuleType("runtime_app")

    def _ensure_live_runtime():
        return None

    def _ensure_can_mutate(request):
        if role == "reader" or raise_on_mutate:
            raise HTTPException(
                status_code=403, detail="reader cannot mutate"
            )
        return "fake@example.com"

    def _user_role_slug(request):
        return role

    def _ensure_governance_store():
        return None

    class _FakeStore:
        def get_tenant_branding(self):
            return {
                "primaryColor": "",
                "accentColor": "",
                "logoUrl": "",
                "orgDisplayName": "",
                "updatedAt": "",
                "updatedBy": "",
            }

    module._ensure_live_runtime = _ensure_live_runtime
    module._ensure_can_mutate = _ensure_can_mutate
    module._user_role_slug = _user_role_slug
    module._ensure_governance_store = _ensure_governance_store
    module._store = lambda: _FakeStore()
    return module


class BrandingGetGateTests(unittest.TestCase):
    def setUp(self) -> None:
        router = admin.build_admin_router()
        try:
            self.endpoint = _find_route(router, "GET", "/api/admin/branding")
        except AssertionError:
            self.endpoint = _find_route(router, "GET", "/branding")

    def _call_as(self, role: str):
        from fastapi import HTTPException

        fake_runtime = _fake_runtime(role)
        # Swap axiom.services.branding so no real DB call is attempted.
        fake_branding = ModuleType("axiom.services.branding")
        fake_branding.get_branding = lambda store: store.get_tenant_branding()
        with unittest.mock.patch.dict(
            sys.modules,
            {
                "runtime_app": fake_runtime,
                "axiom.services.branding": fake_branding,
            },
        ):
            try:
                return self.endpoint(SimpleNamespace(headers={}))
            except HTTPException as exc:
                return exc

    def test_reader_gets_403_via_ensure_can_mutate(self) -> None:
        from fastapi import HTTPException

        result = self._call_as("reader")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 403)

    def test_writer_gets_403_via_explicit_admin_check(self) -> None:
        from fastapi import HTTPException

        result = self._call_as("writer")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 403)
        self.assertIn("admin", str(result.detail).lower())

    def test_steward_gets_403_admin_only_read(self) -> None:
        from fastapi import HTTPException

        result = self._call_as("steward")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 403)

    def test_admin_gets_200_payload(self) -> None:
        result = self._call_as("admin")
        # JSONResponse in the fastapi stub is a simple object with
        # .content + .status_code; under real fastapi, .status_code
        # defaults to 200 too.
        self.assertEqual(getattr(result, "status_code", 200), 200)
        payload = getattr(result, "content", result.body if hasattr(result, "body") else None)
        # With real fastapi, .body is bytes; unwrap via .content when the stub is used.
        if isinstance(payload, dict):
            self.assertIn("branding", payload)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401 — needed for patch.dict

    unittest.main()
