"""Domain model invariants and the never-raises probe contract."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from atlas.ai import models, probes


class ModelTests(unittest.TestCase):
    def _obs(self, **overrides) -> models.Observation:
        base = dict(
            run_id="run-1",
            source_system="databricks",
            collector="dbx_ai_collector",
            collector_version="1",
            entity_kind=models.SERVING_ENDPOINT,
            source_entity_id="ep-1",
            observed_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
            display_name="chat",
            tags={"a": "1", "b": "2"},
        )
        base.update(overrides)
        return models.Observation(**base)

    def test_entity_id_is_deterministic_and_kind_scoped(self) -> None:
        self.assertEqual(self._obs().entity_id, self._obs(run_id="run-2").entity_id)
        self.assertNotEqual(self._obs().entity_id, self._obs(entity_kind=models.AGENT).entity_id)
        self.assertEqual(len(self._obs().entity_id), 32)

    def test_content_hash_ignores_run_and_time_but_tracks_content(self) -> None:
        first = self._obs()
        rerun = self._obs(run_id="run-2", observed_at=datetime(2027, 1, 1, tzinfo=timezone.utc), tags={"b": "2", "a": "1"})
        changed = self._obs(tags={"a": "1", "b": "3"})
        self.assertEqual(first.content_hash, rerun.content_hash)
        self.assertNotEqual(first.content_hash, changed.content_hash)

    def test_finding_id_is_idempotency_key(self) -> None:
        a = models.finding_id_for("found_not_registered", "e1", None, "R-FNR-01")
        self.assertEqual(a, models.finding_id_for("found_not_registered", "e1", None, "R-FNR-01"))
        self.assertNotEqual(a, models.finding_id_for("found_not_registered", "e1", "INT-1", "R-FNR-01"))

    def test_entity_kinds(self) -> None:
        self.assertIn(models.INTAKE_RECORD, models.ENTITY_KINDS)
        self.assertNotIn(models.INTAKE_RECORD, models.OBSERVED_KINDS)


class ProbeTests(unittest.TestCase):
    def test_success(self) -> None:
        result, value = probes.probe("serving_endpoints", lambda: [1, 2])
        self.assertEqual((result.ok, result.state, result.reason, value), (True, "available", "", [1, 2]))

    def test_exception_becomes_unavailable_with_sanitized_reason(self) -> None:
        def boom():
            raise PermissionError(
                "User does not have USE CATALOG on Catalog 'x'. Config: host=https://dbc-1.cloud.databricks.com, client_id=abc"
            )

        result, value = probes.probe("registered_models", boom)
        self.assertFalse(result.ok)
        self.assertEqual(result.state, "unavailable")
        self.assertIsNone(value)
        self.assertIn("USE CATALOG", result.reason)
        self.assertNotIn("client_id", result.reason)
        self.assertNotIn("dbc-1", result.reason)

    def test_degraded_keeps_partial_value(self) -> None:
        def partial():
            raise probes.Degraded("3 models unreadable (permission denied)", value=["m1"])

        result, value = probes.probe("registered_models", partial)
        self.assertTrue(result.ok)
        self.assertEqual(result.state, "degraded")
        self.assertEqual(result.reason, "3 models unreadable (permission denied)")
        self.assertEqual(value, ["m1"])

    def test_unavailable_helper(self) -> None:
        result = probes.unavailable("ai_asset_registry", "no API in databricks-sdk 0.95")
        self.assertEqual((result.ok, result.state), (False, "unavailable"))


if __name__ == "__main__":
    unittest.main()
