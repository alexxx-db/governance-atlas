"""AI autofill is billed to the app's serving endpoint: cap calls per user."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from atlas.api import atlas as atlas_api


class AutofillRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        atlas_api._AUTOFILL_CALLS.clear()

    def test_limit_per_user(self) -> None:
        for _ in range(atlas_api._AUTOFILL_MAX_CALLS):
            atlas_api._enforce_autofill_rate_limit("a@example.com")
        with self.assertRaises(HTTPException) as ctx:
            atlas_api._enforce_autofill_rate_limit("a@example.com")
        self.assertEqual(ctx.exception.status_code, 429)
        # Another user has their own budget.
        atlas_api._enforce_autofill_rate_limit("b@example.com")


if __name__ == "__main__":
    unittest.main()
