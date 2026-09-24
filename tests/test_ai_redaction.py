"""Adversarial redaction tests (DESIGN.md section 8).

The assertion that matters: no credential-shaped value survives
serialization, whatever shape the input takes."""

from __future__ import annotations

import json
import unittest

from atlas.ai import redaction

SECRETS = (
    "sk-live-0123456789abcdefghijkl",
    "sk-ant-api03-abcdefghijklmnop",
    "dapi" + "0123456789abcdef" * 2,
    "dose" + "0123456789abcdef0123456789",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl",
    "Bearer abc.def.ghi",
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "xoxb-1234567890-abcdefghij",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
    "hunter2-plaintext-password",
)


def _dump(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)


class RedactionTests(unittest.TestCase):
    def assertNoSecrets(self, value) -> None:
        blob = _dump(value)
        for secret in SECRETS:
            self.assertNotIn(secret, blob)

    def test_unlisted_fields_are_dropped_not_masked(self) -> None:
        out = redaction.redact(
            "served_entity",
            {
                "name": "chat",
                "entity_name": "anthropic",
                "environment_vars": {"OPENAI_API_KEY": SECRETS[0], "HARMLESS": "x"},
                "instance_profile_arn": "arn:aws:iam::1:role/x",
                "external_model": {
                    "provider": "anthropic",
                    "name": "claude",
                    "anthropic_config": {"anthropic_api_key_plaintext": SECRETS[1]},
                },
            },
        )
        self.assertEqual(out, {"name": "chat", "entity_name": "anthropic", "external_model": {"provider": "anthropic", "name": "claude"}})
        self.assertNoSecrets(out)

    def test_nested_lists_and_unexpected_shapes(self) -> None:
        out = redaction.redact(
            "serving_endpoint",
            {
                "name": "ep",
                "task": {"unexpected": "object"},  # scalar slot given an object: dropped
                "ai_gateway": {
                    "usage_tracking_config": {"enabled": True, "token": SECRETS[4]},
                    "rate_limits": [
                        {"calls": 10, "tokens": 1000, "scope": "user", "authorization": SECRETS[5]},
                        "not-a-dict",
                    ],
                    "guardrails": {"input": {"safety": True, "invalid_keywords": ["secret project"]}},
                },
                "headers": {"Authorization": SECRETS[5]},
            },
        )
        self.assertEqual(out["name"], "ep")
        self.assertNotIn("task", out)
        self.assertEqual(out["ai_gateway"]["usage_tracking_config"], {"enabled": True})
        self.assertEqual(out["ai_gateway"]["rate_limits"], [{"calls": 10, "tokens": 1000, "scope": "user"}])
        self.assertEqual(out["ai_gateway"]["guardrails"], {"input": {"safety": True}})
        self.assertNotIn("headers", out)
        self.assertNoSecrets(out)

    def test_credential_shaped_values_dropped_even_in_allowlisted_fields(self) -> None:
        for secret in SECRETS[:-1]:
            out = redaction.redact("registered_model", {"full_name": "m.s.x", "comment": secret, "owner": "a@b.c"})
            self.assertNotIn("comment", out, secret)
            self.assertEqual(out["full_name"], "m.s.x")

    def test_scrubber_second_line_of_defense(self) -> None:
        dirty = {
            "api_key": SECRETS[0],
            "Client-Secret": SECRETS[2],
            "nested": [{"password": SECRETS[10], "ok": 1}, {"auth_token": SECRETS[4]}],
            "private_key_pem": SECRETS[9],
            "tokens": 5,
            "note": SECRETS[6],
            "safe": "value",
        }
        out = redaction.scrub(dirty)
        self.assertEqual(out, {"nested": [{"ok": 1}, {}], "tokens": 5, "safe": "value"})
        self.assertNoSecrets(out)

    def test_secret_references_kept_as_reference_only(self) -> None:
        out = redaction.scrub({"anthropic_api_key": "{{secrets/ai-scope/anthropic}}", "list": ["{{ secrets/s/k }}"]})
        self.assertEqual(out, {"anthropic_api_key": {"secret_ref": "ai-scope/anthropic"}, "list": [{"secret_ref": "s/k"}]})
        self.assertIsNone(redaction.secret_ref("{{secrets/only-scope}}"))
        self.assertIsNone(redaction.secret_ref("secrets/s/k"))

    def test_connection_url_and_oauth_options_dropped(self) -> None:
        out = redaction.redact(
            "connection",
            {
                "name": "mcp1",
                "connection_type": "HTTP",
                "url": "https://user:pw@host/path?token=abc",
                "options": {
                    "host": "mcp.example.com",
                    "is_mcp_connection": "true",
                    "client_id": "cid",
                    "client_secret": SECRETS[2],
                    "token_endpoint": "https://idp/token",
                },
            },
        )
        self.assertEqual(out, {"name": "mcp1", "connection_type": "HTTP", "options": {"host": "mcp.example.com", "is_mcp_connection": "true"}})

    def test_embedded_keys_and_host_userinfo_removed(self) -> None:
        out = redaction.redact(
            "registered_model",
            {"full_name": "m.s.x", "comment": "rotate key sk-proj-abcdefghijklmnopqrstuv soon", "owner": "a@b.c"},
        )
        self.assertNotIn("comment", out)
        self.assertEqual(redaction.redact("registered_model", {"full_name": "a.b.c", "comment": "ask-the-team about tasks"})["comment"], "ask-the-team about tasks")
        conn = redaction.redact("connection", {"name": "c", "options": {"host": "https://user:pass@h.example.com/mcp"}})
        self.assertEqual(conn["options"]["host"], "https://h.example.com/mcp")
        self.assertEqual(redaction.strip_userinfo("admin:pw@db.internal"), "db.internal")

    def test_function_body_never_serialized(self) -> None:
        out = redaction.redact("uc_function", {"full_name": "a.b.f", "routine_definition": f"return '{SECRETS[0]}'"})
        self.assertEqual(out, {"full_name": "a.b.f"})

    def test_unknown_object_type_fails_closed(self) -> None:
        self.assertEqual(redaction.redact("mystery", {"name": "x"}), {})
        self.assertEqual(redaction.redact("connection", "not a mapping"), {})  # type: ignore[arg-type]

    def test_summarize_credentials(self) -> None:
        self.assertEqual(
            redaction.summarize_credentials({}),
            {"observable": False, "secret_refs": [], "plaintext_fields": []},
        )
        # The dev workspace returns every credential field empty (PHASE0 D7).
        self.assertFalse(redaction.summarize_credentials({"anthropic_api_key": None})["observable"])
        summary = redaction.summarize_credentials(
            {
                "openai_api_key": "{{secrets/s/openai}}",
                "openai_api_key_plaintext": SECRETS[0],
                "microsoft_entra_client_secret_plaintext": SECRETS[10],
                "openai_api_base": "https://api.example.com",
            }
        )
        self.assertTrue(summary["observable"])
        self.assertEqual(summary["secret_refs"], [{"field": "openai_api_key", "secret_ref": "s/openai"}])
        self.assertEqual(sorted(summary["plaintext_fields"]), ["microsoft_entra_client_secret_plaintext", "openai_api_key_plaintext"])
        self.assertNoSecrets(summary)


if __name__ == "__main__":
    unittest.main()
