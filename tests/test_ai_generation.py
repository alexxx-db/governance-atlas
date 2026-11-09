from __future__ import annotations

import unittest
from types import SimpleNamespace

from axiom.config import AppConfig
from axiom.services import ai_generation


class FakeServingClient:
    def __init__(self, content: str):
        self._content = content
        self.calls = []
        self.serving_endpoints = SimpleNamespace(query=self._query)

    def _query(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


def _config(**overrides) -> AppConfig:
    data = {
        "warehouse_id": "w", "gov_catalog": "c", "gov_schema": "s",
        "ai_generation_endpoint": "databricks-claude-sonnet-4-6",
    }
    data.update(overrides)
    return AppConfig(**data)


class AiGenerationTests(unittest.TestCase):
    def test_provider_status_available_and_disabled(self) -> None:
        self.assertEqual(ai_generation.provider_status(_config())["state"], "available")
        self.assertEqual(
            ai_generation.provider_status(_config(ai_generation_endpoint=""))["state"], "unavailable"
        )

    def test_glossary_autofill_parses_json_fields(self) -> None:
        client = FakeServingClient(
            '{"definition": "Revenue recognized in a period.", "domain": "Finance", "acronymExpansion": ""}'
        )
        result = ai_generation.generate_fields(
            config=_config(), kind="glossaryTerm",
            context={"termName": "Net Revenue"}, client=client,
        )
        self.assertEqual(result["fields"]["definition"], "Revenue recognized in a period.")
        self.assertEqual(result["fields"]["domain"], "Finance")
        # Empty allowed field dropped so the UI fills selectively.
        self.assertNotIn("acronymExpansion", result["fields"])
        self.assertEqual(result["model"], "databricks-claude-sonnet-4-6")
        # The term name reached the prompt.
        sent = client.calls[0]["messages"][-1].content
        self.assertIn("Net Revenue", sent)

    def test_json_extracted_from_fenced_prose(self) -> None:
        client = FakeServingClient(
            'Sure!\n```json\n{"definition": "A customer identifier.", "domain": "Customer"}\n```\n'
        )
        result = ai_generation.generate_fields(
            config=_config(), kind="glossaryTerm", context={"termName": "Customer ID"}, client=client,
        )
        self.assertEqual(result["fields"]["domain"], "Customer")

    def test_unparseable_response_yields_warning_not_crash(self) -> None:
        client = FakeServingClient("I cannot help with that.")
        result = ai_generation.generate_fields(
            config=_config(), kind="glossaryTerm", context={"termName": "X"}, client=client,
        )
        self.assertEqual(result["fields"], {})
        self.assertTrue(result["warnings"])

    def test_unsupported_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            ai_generation.generate_fields(
                config=_config(), kind="nope", context={}, client=FakeServingClient("{}"),
            )

    def test_disabled_provider_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            ai_generation.generate_fields(
                config=_config(ai_generation_endpoint=""), kind="glossaryTerm",
                context={"termName": "X"}, client=FakeServingClient("{}"),
            )


if __name__ == "__main__":
    unittest.main()
