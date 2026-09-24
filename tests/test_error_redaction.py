"""API error text must never carry the SDK's Config: host/client_id suffix."""

from __future__ import annotations

import unittest

from atlas.util import error_text, redact_error_text


class ErrorRedactionTests(unittest.TestCase):
    def test_config_suffix_removed(self) -> None:
        exc = RuntimeError(
            "PermissionDenied: no SELECT on t. Config: host=https://dbc-x.cloud.databricks.com, client_id=abc"
        )
        text = error_text(exc)
        self.assertEqual(text, "RuntimeError: PermissionDenied: no SELECT on t")
        self.assertNotIn("client_id", text)
        self.assertNotIn("dbc-x", text)

    def test_multiline_and_cap(self) -> None:
        self.assertEqual(redact_error_text("bad token\nConfig: host=x"), "bad token")
        self.assertLessEqual(len(error_text(ValueError("x" * 1000))), 320)

    def test_class_prefix_not_duplicated(self) -> None:
        self.assertEqual(error_text(ValueError("ValueError: boom")), "ValueError: boom")
        self.assertEqual(error_text(ValueError("")), "ValueError")


if __name__ == "__main__":
    unittest.main()
