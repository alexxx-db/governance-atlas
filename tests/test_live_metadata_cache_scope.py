"""Regression tests: per-table live-metadata caches must be partitioned by
acting credentials, not just warehouse.

Prior to this fix, cache keys were `{kind}:{warehouse_id}:{catalog}:{schema}:{table}`.
Sample rows, columns, table detail, and lineage fetched under one user's OBO
permissions were served to every other user on the same warehouse.
"""

from __future__ import annotations

import unittest

import pandas as pd

from axiom.services import assets as assets_service
from axiom.services import live_metadata
from axiom.uc import UCSQLClient


class FakeUc:
    def __init__(self, scope: str, sample: pd.DataFrame) -> None:
        self.warehouse_id = "wh-shared"
        self.cache_scope = scope
        self._sample = sample
        self.sample_calls = 0

    def get_table_sample(self, catalog, schema, table, limit=15):
        self.sample_calls += 1
        return self._sample


class LiveMetadataCacheScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        live_metadata._TTL_CACHE.clear()
        assets_service._TTL_CACHE.clear()

    def test_sample_rows_do_not_leak_across_cache_scopes(self) -> None:
        alice = FakeUc("obo-alice", pd.DataFrame([{"ssn": "alice-visible"}]))
        bob = FakeUc("obo-bob", pd.DataFrame([{"ssn": "bob-visible"}]))

        first = live_metadata.cached_sample_rows(alice, "cat", "sch", "tbl")
        second = live_metadata.cached_sample_rows(bob, "cat", "sch", "tbl")

        self.assertEqual(first.iloc[0]["ssn"], "alice-visible")
        self.assertEqual(second.iloc[0]["ssn"], "bob-visible")
        self.assertEqual(bob.sample_calls, 1)  # must not be served from alice's entry

    def test_same_scope_still_shares_cache(self) -> None:
        one = FakeUc("obo-alice", pd.DataFrame([{"v": 1}]))
        two = FakeUc("obo-alice", pd.DataFrame([{"v": 2}]))

        live_metadata.cached_sample_rows(one, "cat", "sch", "tbl")
        result = live_metadata.cached_sample_rows(two, "cat", "sch", "tbl")

        self.assertEqual(result.iloc[0]["v"], 1)
        self.assertEqual(two.sample_calls, 0)

    def test_assets_warehouse_key_includes_scope(self) -> None:
        self.assertEqual(
            assets_service._warehouse_key(FakeUc("obo-alice", pd.DataFrame())),
            "wh-shared:obo-alice",
        )
        self.assertEqual(
            live_metadata._warehouse_key(FakeUc("app", pd.DataFrame())),
            "wh-shared:app",
        )

    def test_clients_without_cache_scope_fall_back_to_app_partition(self) -> None:
        class Bare:
            warehouse_id = "wh-shared"

        self.assertEqual(live_metadata._warehouse_key(Bare()), "wh-shared:app")


class UcClientCacheScopeTests(unittest.TestCase):
    def _client(self, token: str | None) -> UCSQLClient:
        client = object.__new__(UCSQLClient)
        client._user_access_token = token
        return client

    def test_obo_clients_get_token_hashed_scope(self) -> None:
        a = self._client("token-a").cache_scope
        b = self._client("token-b").cache_scope
        self.assertTrue(a.startswith("obo-"))
        self.assertTrue(b.startswith("obo-"))
        self.assertNotEqual(a, b)
        self.assertEqual(a, self._client("token-a").cache_scope)

    def test_app_principal_scope_is_stable(self) -> None:
        self.assertEqual(self._client(None).cache_scope, "app")


if __name__ == "__main__":
    unittest.main()
