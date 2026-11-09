from __future__ import annotations

import unittest

from axiom.services import custom_properties as cp_service


class ValidateValueTests(unittest.TestCase):
    def test_required_string_accepted(self) -> None:
        r = cp_service.validate_value("string", "hello", is_required=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.value, "hello")

    def test_required_string_rejects_empty(self) -> None:
        r = cp_service.validate_value("string", "", is_required=True)
        self.assertFalse(r.ok)

    def test_number_coerces_string(self) -> None:
        r = cp_service.validate_value("number", "3.14")
        self.assertTrue(r.ok)
        self.assertEqual(r.value, 3.14)

    def test_number_rejects_non_numeric(self) -> None:
        r = cp_service.validate_value("number", "abc")
        self.assertFalse(r.ok)

    def test_boolean_accepts_truthy_strings(self) -> None:
        self.assertTrue(cp_service.validate_value("boolean", "yes").value)
        self.assertFalse(cp_service.validate_value("boolean", "No").value)

    def test_date_normalizes_iso(self) -> None:
        r = cp_service.validate_value("date", "2026-04-18")
        self.assertTrue(r.ok)
        self.assertEqual(r.value, "2026-04-18")

    def test_date_rejects_garbage(self) -> None:
        self.assertFalse(cp_service.validate_value("date", "not-a-date").ok)

    def test_enum_rejects_out_of_set(self) -> None:
        r = cp_service.validate_value("enum", "gold", enum_values=["bronze", "silver"])
        self.assertFalse(r.ok)
        self.assertIn("allowed enum set", r.reason)

    def test_multi_validates_each_entry(self) -> None:
        r = cp_service.validate_value("number", [1, "2.5", 3], is_multi=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.value, [1.0, 2.5, 3.0])

    def test_multi_rejects_non_list(self) -> None:
        r = cp_service.validate_value("number", "not-a-list", is_multi=True)
        self.assertFalse(r.ok)

    def test_optional_empty_value_passes_through(self) -> None:
        r = cp_service.validate_value("string", "", is_required=False)
        self.assertTrue(r.ok)
        self.assertIsNone(r.value)


class NormalizeDefinitionTests(unittest.TestCase):
    def test_rejects_unsupported_type(self) -> None:
        with self.assertRaises(ValueError):
            cp_service.normalize_definition_payload(
                {"entityKind": "asset", "propertyKey": "foo", "dataType": "timestamp"}
            )

    def test_rejects_unsupported_entity_kind(self) -> None:
        with self.assertRaises(ValueError):
            cp_service.normalize_definition_payload(
                {"entityKind": "dashboard", "propertyKey": "foo", "dataType": "string"}
            )

    def test_enum_requires_non_empty_values(self) -> None:
        with self.assertRaises(ValueError):
            cp_service.normalize_definition_payload(
                {
                    "entityKind": "asset",
                    "propertyKey": "tier",
                    "dataType": "enum",
                    "enumValues": [],
                }
            )

    def test_normalizes_payload(self) -> None:
        normalized = cp_service.normalize_definition_payload(
            {
                "entityKind": "asset",
                "propertyKey": "retention",
                "dataType": "number",
                "displayName": "Retention (days)",
            }
        )
        self.assertEqual(normalized["entityKind"], "asset")
        self.assertEqual(normalized["propertyKey"], "retention")
        self.assertEqual(normalized["dataType"], "number")
        self.assertEqual(normalized["enumValues"], [])


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_stable_json(self) -> None:
        snap = cp_service.definition_snapshot_json(
            {
                "entityKind": "asset",
                "propertyKey": "retention",
                "displayName": "Retention",
                "description": None,
                "dataType": "number",
                "enumValues": [],
                "isRequired": True,
                "isMulti": False,
                "scope": {},
            }
        )
        self.assertTrue(snap.startswith("{"))
        self.assertIn('"dataType": "number"', snap)
        self.assertIn('"isRequired": true', snap)


if __name__ == "__main__":
    unittest.main()
