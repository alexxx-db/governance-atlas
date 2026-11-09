"""Regression tests for the cold-metadata latency fixes:

- The header/schema fan-out warms independent Unity Catalog round trips
  concurrently (was serialized, the dominant ~5-7s cold-header cost).
- The estate pre-warmer skips already-fresh assets (resumable + cheap) and
  guards against a thundering herd (one sweep per scope at a time).
- Asset-detail payloads stamp a build-time observedAt so the longer, honest
  cache TTL never fabricates freshness.
"""

from __future__ import annotations

import threading
import time
import unittest

import pandas as pd

from axiom.services import assets as assets_service
from axiom.services import live_metadata


class ConcurrencyRecordingUc:
    """Records max concurrent in-flight calls so a serial vs parallel fan-out
    is observable without depending on wall-clock timing."""

    def __init__(self, scope: str = "obo-a", per_call_s: float = 0.15) -> None:
        self.warehouse_id = "wh-test"
        self.cache_scope = scope
        self._per_call_s = per_call_s
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_concurrent = 0

    def _enter(self):
        with self._lock:
            self._inflight += 1
            self.max_concurrent = max(self.max_concurrent, self._inflight)

    def _leave(self):
        with self._lock:
            self._inflight -= 1

    def _work(self, frame: pd.DataFrame) -> pd.DataFrame:
        self._enter()
        try:
            time.sleep(self._per_call_s)
            return frame
        finally:
            self._leave()

    def get_table_detail(self, c, s, t):
        return self._work(pd.DataFrame([{"numRows": 1}]))

    def get_table_history(self, c, s, t):
        return self._work(pd.DataFrame())

    def get_information_schema_table_metadata(self, c, s, t):
        return self._work(pd.DataFrame())

    def get_table_comment(self, c, s, t):
        self._enter()
        try:
            time.sleep(self._per_call_s)
            return "desc"
        finally:
            self._leave()

    def get_table_columns(self, c, s, t):
        return self._work(pd.DataFrame())

    def get_table_column_tags(self, c, s, t):
        return self._work(pd.DataFrame())

    def get_table_constraints(self, c, s, t):
        return self._work(pd.DataFrame())


class MetadataPrewarmTests(unittest.TestCase):
    def setUp(self) -> None:
        live_metadata._TTL_CACHE.clear()
        assets_service._TTL_CACHE.clear()

    def test_prefetch_asset_header_runs_round_trips_concurrently(self) -> None:
        uc = ConcurrencyRecordingUc()
        live_metadata.prefetch_asset_header(uc, "cat", "sch", "tbl")
        # Four independent header round trips must overlap (serial would be 1).
        self.assertGreaterEqual(uc.max_concurrent, 2)

    def test_gather_parallel_returns_results_in_order(self) -> None:
        out = live_metadata.gather_parallel(
            (lambda: "a", lambda: "b", lambda: "c"), max_workers=3
        )
        self.assertEqual(out, ["a", "b", "c"])

    def test_gather_parallel_swallows_failures_as_none(self) -> None:
        def boom():
            raise RuntimeError("nope")

        out = live_metadata.gather_parallel((lambda: "ok", boom), max_workers=2)
        self.assertEqual(out, ["ok", None])

    def test_prefetch_populates_cache_so_reads_are_free(self) -> None:
        uc = ConcurrencyRecordingUc()
        live_metadata.prefetch_asset_header(uc, "cat", "sch", "tbl")
        before = uc.max_concurrent
        # Subsequent cached reads must hit the warm cache — no new round trips.
        live_metadata.cached_table_detail(uc, "cat", "sch", "tbl")
        live_metadata.cached_table_history(uc, "cat", "sch", "tbl")
        self.assertTrue(
            live_metadata.header_cache_is_fresh(uc, "cat", "sch", "tbl")
        )
        self.assertEqual(uc.max_concurrent, before)

    def test_estate_warmer_skips_already_fresh_assets(self) -> None:
        uc = ConcurrencyRecordingUc()
        # Pre-warm one asset's detail cache, then run the estate sweep over two.
        live_metadata.cached_table_detail(uc, "cat", "sch", "warm")
        counters = live_metadata.warm_estate_headers(
            uc,
            ["cat.sch.warm", "cat.sch.cold"],
            scope_key=live_metadata._warehouse_key(uc),
            max_assets=50,
        )
        self.assertEqual(counters["skippedFresh"], 1)
        self.assertEqual(counters["queued"], 1)

    def test_estate_warmer_ignores_malformed_fqns(self) -> None:
        uc = ConcurrencyRecordingUc()
        counters = live_metadata.warm_estate_headers(
            uc, ["not-a-fqn", "a.b"], scope_key="s", max_assets=50
        )
        self.assertEqual(counters["queued"], 0)

    def test_header_cache_fresh_false_when_cold(self) -> None:
        uc = ConcurrencyRecordingUc()
        self.assertFalse(
            live_metadata.header_cache_is_fresh(uc, "cat", "sch", "never")
        )

    def test_asset_detail_ttls_are_honest_and_extended(self) -> None:
        # Fresh window is longer than the legacy 300s (payloads now carry
        # observedAt), and stale-while-revalidate sits above it.
        self.assertGreater(assets_service.ASSET_DETAIL_FRESH_TTL_S, 300)
        self.assertGreater(
            assets_service.ASSET_DETAIL_STALE_TTL_S,
            assets_service.ASSET_DETAIL_FRESH_TTL_S,
        )
        # Empty/no-signal payloads keep the short self-healing window.
        self.assertLessEqual(assets_service.ASSET_DETAIL_EMPTY_TTL_S, 30)

    def test_now_iso_and_iso_after_are_utc_zulu(self) -> None:
        now = assets_service._now_iso()
        later = assets_service._iso_after(assets_service.ASSET_DETAIL_FRESH_TTL_S)
        self.assertTrue(now.endswith("Z"))
        self.assertTrue(later.endswith("Z"))
        self.assertLess(now, later)

    def _inventory(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "fqn": "cat.sch.tbl",
                    "table_catalog": "cat",
                    "table_schema": "sch",
                    "table_name": "tbl",
                    "table_type": "MANAGED",
                    "data_source_format": "DELTA",
                    "comment": "Backed table",
                    "governance_score": 70,
                    "governance_status": "Operational",
                }
            ]
        )

    def test_asset_detail_stamps_observed_at(self) -> None:
        uc = ConcurrencyRecordingUc()
        payload = assets_service.asset_detail_payload(
            uc, self._inventory(), "cat.sch.tbl", sections=["header"]
        )
        self.assertTrue(str(payload.get("metadataObservedAt", "")).endswith("Z"))
        self.assertTrue(str(payload.get("metadataStaleAfter", "")).endswith("Z"))

    def test_asset_detail_serves_stale_while_revalidating(self) -> None:
        uc = ConcurrencyRecordingUc()
        inv = self._inventory()
        first = assets_service.asset_detail_payload(
            uc, inv, "cat.sch.tbl", sections=["header"]
        )
        self.assertTrue(assets_service.asset_payload_has_live_signals(first))
        # Age the cache entry past the fresh window but inside the stale window.
        key = next(
            k for k in assets_service._TTL_CACHE if k.startswith("asset_detail:")
        )
        _, cached_payload = assets_service._TTL_CACHE[key]
        assets_service._TTL_CACHE[key] = (
            time.time() - (assets_service.ASSET_DETAIL_FRESH_TTL_S + 5),
            cached_payload,
        )
        # A re-hit must return immediately with the stale (honest) body and
        # kick a background rebuild rather than blocking on a cold load.
        second = assets_service.asset_detail_payload(
            uc, inv, "cat.sch.tbl", sections=["header"]
        )
        self.assertEqual(
            second.get("metadataObservedAt"), first.get("metadataObservedAt")
        )
        # Let the background revalidation finish, then confirm the cache
        # refreshed to a newer observation.
        deadline = time.time() + 5
        while time.time() < deadline:
            _, latest = assets_service._TTL_CACHE[key]
            if latest.get("metadataObservedAt") != first.get("metadataObservedAt"):
                break
            time.sleep(0.05)
        _, latest = assets_service._TTL_CACHE[key]
        self.assertGreaterEqual(
            latest.get("metadataObservedAt"), first.get("metadataObservedAt")
        )


if __name__ == "__main__":
    unittest.main()
