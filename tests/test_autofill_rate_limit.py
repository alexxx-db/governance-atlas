"""AI autofill is billed to the app's serving endpoint: cap calls per user."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from axiom.api import axiom as axiom_api


class AutofillRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        axiom_api._AUTOFILL_CALLS.clear()

    def test_limit_per_user(self) -> None:
        for _ in range(axiom_api._AUTOFILL_MAX_CALLS):
            axiom_api._enforce_autofill_rate_limit("a@example.com")
        with self.assertRaises(HTTPException) as ctx:
            axiom_api._enforce_autofill_rate_limit("a@example.com")
        self.assertEqual(ctx.exception.status_code, 429)
        # Another user has their own budget.
        axiom_api._enforce_autofill_rate_limit("b@example.com")


if __name__ == "__main__":
    unittest.main()
