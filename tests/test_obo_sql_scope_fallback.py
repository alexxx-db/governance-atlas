"""Regression test locking the OBO → app-principal fallback for the Databricks
``sql`` scope error.

The failure mode this test pins was reported by the operator on 2026-04-19:
stewards intermittently saw a "Discovery search is unavailable" banner with
a raw SDK envelope containing ``403 Forbidden — Invalid scope, required
scopes: sql``. It happens when a user signed into the app before the
``sql`` OBO scope was granted — their token lacks the scope, the warehouse
rejects it, and the SDK surfaces the rejection as an opaque parse error.

Retrying on the app principal would serve one principal's view of Unity
Catalog to every user, so :class:`runtime_app._UserScopedUC` turns the scope
error into an explicit re-authorize 403 and never touches the app principal.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from atlas import uc as uc_module

# Import lazily inside tests to avoid pulling in the entire FastAPI app
# at module-import time (runtime_app imports lots of side-effecting
# runtime wiring we don't need here).


class MissingSqlScopeDetectorTests(unittest.TestCase):
    def test_detects_canonical_scope_error_text(self) -> None:
        err = RuntimeError(
            "POST /api/2.0/sql/statements — 403 Forbidden — "
            "Invalid scope, required scopes: sql"
        )
        self.assertTrue(uc_module.is_missing_sql_scope_error(err))

    def test_detects_alternative_phrasing(self) -> None:
        err = RuntimeError("403: required scopes: sql (user token)")
        self.assertTrue(uc_module.is_missing_sql_scope_error(err))

    def test_ignores_unrelated_errors(self) -> None:
        self.assertFalse(
            uc_module.is_missing_sql_scope_error(RuntimeError("TABLE_OR_VIEW_NOT_FOUND"))
        )
        self.assertFalse(
            uc_module.is_missing_sql_scope_error(RuntimeError("Insufficient permissions"))
        )
        self.assertFalse(uc_module.is_missing_sql_scope_error(None))


class UserScopedClientTests(unittest.TestCase):
    def setUp(self) -> None:
        import runtime_app  # noqa: WPS433

        self.runtime_app = runtime_app

    def test_scope_error_becomes_reauth_403_without_app_principal(self) -> None:
        primary = MagicMock(name="obo-client")
        primary.list_tables.side_effect = RuntimeError(
            "POST /api/2.0/sql/statements — 403 Forbidden — Invalid scope, required scopes: sql"
        )
        primary.set_table_comment.side_effect = primary.list_tables.side_effect
        wrapper = self.runtime_app._UserScopedUC(primary)

        for call in (lambda: wrapper.list_tables("cat"), lambda: wrapper.set_table_comment("c", "s", "t", "d")):
            with self.assertRaises(self.runtime_app.HTTPException) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("sign back in", ctx.exception.detail)

    def test_unrelated_errors_propagate_unchanged(self) -> None:
        primary = MagicMock(name="obo-client")
        primary.list_tables.side_effect = RuntimeError("TABLE_OR_VIEW_NOT_FOUND: foo")
        wrapper = self.runtime_app._UserScopedUC(primary)
        with self.assertRaisesRegex(RuntimeError, "TABLE_OR_VIEW_NOT_FOUND"):
            wrapper.list_tables("cat")

    def test_success_passes_through(self) -> None:
        primary = MagicMock(name="obo-client")
        primary.list_tables.return_value = ["t"]
        primary.cache_scope = "obo-abc"
        wrapper = self.runtime_app._UserScopedUC(primary)
        self.assertEqual(wrapper.list_tables("cat"), ["t"])
        self.assertEqual(wrapper.cache_scope, "obo-abc")


class SqlLiteralEscapingTests(unittest.TestCase):
    def test_backslash_cannot_break_out_of_literal(self) -> None:
        from atlas.util import sql_literal

        # `\'` must not become an escaped quote that lets `''` close the literal.
        self.assertEqual(sql_literal("x\\' OR 1=1 --"), "'x\\\\'' OR 1=1 --'")
        self.assertEqual(sql_literal("a\\d+"), "'a\\\\d+'")
        self.assertEqual(sql_literal("it's"), "'it''s'")
        self.assertEqual(sql_literal(None), "NULL")


if __name__ == "__main__":
    unittest.main()
