"""Unit tests for the pure parts of the export service.

The decision function is the core safety gate — it enforces the plan's
"no raw OBO token, fail closed on stale auth" contract. Anything that
consumes the export API must ship evaluate_export_request + csv building
tests so the safety rules can't silently drift.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from axiom.services import export as export_service


class EvaluateExportRequestTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)

    def test_blocks_non_actor_scoped_callers(self) -> None:
        decision = export_service.evaluate_export_request(
            actor_scoped=False,
            token_captured_at=self._now(),
            asset_count=3,
            sync=True,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "failed")
        self.assertIn("OBO", decision.reason)

    def test_blocks_empty_asset_list(self) -> None:
        decision = export_service.evaluate_export_request(
            actor_scoped=True,
            token_captured_at=self._now(),
            asset_count=0,
            sync=True,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertIn("at least one asset", decision.reason)

    def test_blocks_sync_over_limit(self) -> None:
        decision = export_service.evaluate_export_request(
            actor_scoped=True,
            token_captured_at=self._now(),
            asset_count=export_service.SYNC_EXPORT_MAX_ROWS + 1,
            sync=True,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertIn("Sync exports are capped", decision.reason)

    def test_stale_auth_when_token_captured_too_long_ago(self) -> None:
        now = self._now()
        captured = now - timedelta(minutes=56)
        decision = export_service.evaluate_export_request(
            actor_scoped=True,
            token_captured_at=captured,
            asset_count=3,
            sync=True,
            now=now,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "stale_auth")
        self.assertIn("Re-run the export", decision.reason)

    def test_allows_fresh_actor_scoped_sync_under_cap(self) -> None:
        now = self._now()
        captured = now - timedelta(minutes=2)
        decision = export_service.evaluate_export_request(
            actor_scoped=True,
            token_captured_at=captured,
            asset_count=5,
            sync=True,
            now=now,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "materializing")

    def test_accepts_none_token_captured_at_as_fresh(self) -> None:
        """Callers that can't record capture time (batched re-exports) still
        need to run — the request-path OBO token itself is validated by
        Databricks at query time."""
        decision = export_service.evaluate_export_request(
            actor_scoped=True,
            token_captured_at=None,
            asset_count=5,
            sync=True,
            now=self._now(),
        )
        self.assertTrue(decision.allowed)


class BuildCsvTests(unittest.TestCase):
    def test_builds_csv_with_header_row(self) -> None:
        rows = [
            {"fqn": "main.sales.orders", "owner": "alice"},
            {"fqn": "main.sales.customers", "owner": "bob"},
        ]
        csv_text = export_service.build_csv(rows, ["fqn", "owner"])
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0], "fqn,owner")
        self.assertIn("main.sales.orders,alice", lines[1])

    def test_coerces_none_and_collections_safely(self) -> None:
        rows = [
            {"fqn": "main.sales.orders", "owners": ["alice", "bob"], "meta": None},
        ]
        csv_text = export_service.build_csv(rows, ["fqn", "owners", "meta"])
        line = csv_text.strip().splitlines()[-1]
        self.assertIn("alice, bob", line)
        self.assertTrue(line.endswith(","))

    def test_nested_dict_cells_round_trip_as_json(self) -> None:
        rows = [{"tags": {"domain": "sales", "tier": "gold"}}]
        csv_text = export_service.build_csv(rows, ["tags"])
        self.assertIn('"{""domain"": ""sales"", ""tier"": ""gold""}"', csv_text)


class SnapshotTests(unittest.TestCase):
    def test_filter_snapshot_is_stable_json(self) -> None:
        snapshot = export_service.build_filter_snapshot(
            asset_fqns=["main.sales.orders"],
            actor_email="alice@example.com",
            visibility_scope="obo-available",
            format="csv",
            requested_at=datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertIn('"assetFqns": ["main.sales.orders"]', snapshot)
        self.assertIn('"actorEmail": "alice@example.com"', snapshot)
        self.assertIn('"visibilityScope": "obo-available"', snapshot)


class EvaluateDownloadRequestTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)

    def test_blocks_non_obo_download(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=False,
            actor_email="a@b",
            requester_email="a@b",
            status="ready",
            expires_at=None,
            token_captured_at=None,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "failed")

    def test_blocks_wrong_requester(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=True,
            actor_email="alice@b",
            requester_email="bob@b",
            status="ready",
            expires_at=None,
            token_captured_at=None,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "forbidden")

    def test_blocks_not_ready_status(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=True,
            actor_email="a@b",
            requester_email="a@b",
            status="materializing",
            expires_at=None,
            token_captured_at=None,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "materializing")

    def test_blocks_expired_artifact(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=True,
            actor_email="a@b",
            requester_email="a@b",
            status="ready",
            expires_at=self._now() - timedelta(minutes=1),
            token_captured_at=None,
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "expired")

    def test_blocks_stale_auth_on_download(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=True,
            actor_email="a@b",
            requester_email="a@b",
            status="ready",
            expires_at=self._now() + timedelta(hours=1),
            token_captured_at=self._now() - timedelta(minutes=56),
            now=self._now(),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "stale_auth")

    def test_allows_fresh_ready_same_requester(self) -> None:
        decision = export_service.evaluate_download_request(
            actor_scoped=True,
            actor_email="a@b",
            requester_email="A@B",  # email match is case-insensitive
            status="ready",
            expires_at=self._now() + timedelta(hours=1),
            token_captured_at=self._now() - timedelta(minutes=10),
            now=self._now(),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "ready")


if __name__ == "__main__":
    unittest.main()
