"""Regression tests for the bootstrap inventory cache scoping fix.

Prior to commit (pending) the inventory bootstrap summary accidentally passed
its normalized_scope string as the `request` argument to visible_assets(),
which sent the string through _request_cache_scope() and collapsed every
caller into the same "unknown|app-principal-only" bucket. OBO- and
app-principal-scoped inventory reads would then silently share a cache.

These tests lock in the fix: calling bootstrap_inventory_summary() with two
distinct cache scopes must produce two distinct inner runtime_inventory
cache keys.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from axiom.api import cache as api_cache
from axiom.services import inventory as inventory_service


class BootstrapInventoryCacheScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        with api_cache._CACHE_LOCK:
            api_cache._TTL_CACHE.clear()

    def _runtime_deps_stub(self):
        hidden = tuple()

        def request_cache_scope(request):
            # The fix shouldn't route the scope through here at all; if it
            # does we return a sentinel so the test can detect the regression.
            return "REGRESSION:request_cache_scope_was_called"

        def store_for_read():
            return object()

        def uc_for_request(_request):
            return object()

        return hidden, request_cache_scope, store_for_read, uc_for_request

    def test_bootstrap_inventory_summary_scopes_inner_cache_per_auth(self) -> None:
        load_calls: list[str] = []
        empty_frame = pd.DataFrame(
            columns=[
                "table_catalog",
                "table_schema",
                "table_name",
                "table_type",
                "data_source_format",
                "governance_status",
                "certification",
                "domain",
                "tier",
                "sensitivity",
            ],
        )

        def fake_visible_assets(_uc, _store, **kwargs):
            load_calls.append("visible_assets")
            return empty_frame

        def fake_inventory_catalogs(_uc, **kwargs):
            return []

        def fake_lineage_observed_catalogs(_uc, **kwargs):
            return []

        with patch.object(inventory_service, "_runtime_deps", self._runtime_deps_stub), \
             patch("axiom.services.assets.visible_assets", side_effect=fake_visible_assets), \
             patch(
                 "axiom.services.assets.inventory_catalogs",
                 side_effect=fake_inventory_catalogs,
             ), \
             patch(
                 "axiom.services.assets.lineage_observed_catalogs",
                 side_effect=fake_lineage_observed_catalogs,
             ):
            inventory_service.bootstrap_inventory_summary("alice@example.com|obo-available")
            inventory_service.bootstrap_inventory_summary("bob@example.com|app-principal-only")

        with api_cache._CACHE_LOCK:
            cache_keys = sorted(api_cache._TTL_CACHE.keys())

        # Round 14 OBO cache isolation: the bootstrap path runs with
        # request=None (no OBO token) so it always loads SP-only data.
        # Keying that data under the raw OBO scope used to poison the
        # discovery cache; the fix suffixes the bootstrap key so the
        # SP snapshot lives on its own bucket. Both alice (OBO) and
        # bob (app-principal) must land under the suffixed key and
        # must never share a bucket with a live OBO discovery query.
        alice_boot_key = (
            "runtime_inventory:alice@example.com|obo-available|bootstrap-app-principal"
        )
        bob_boot_key = (
            "runtime_inventory:bob@example.com|app-principal-only|bootstrap-app-principal"
        )
        regression_key = "runtime_inventory:REGRESSION:request_cache_scope_was_called"
        poisoning_key = "runtime_inventory:alice@example.com|obo-available"

        self.assertIn(alice_boot_key, cache_keys)
        self.assertIn(bob_boot_key, cache_keys)
        self.assertNotIn(
            regression_key,
            cache_keys,
            msg=(
                "bootstrap_inventory_summary still routes its scope through "
                "request_cache_scope — OBO and app-principal reads would share a bucket."
            ),
        )
        self.assertNotIn(
            poisoning_key,
            cache_keys,
            msg=(
                "bootstrap_inventory_summary wrote SP-only data under the raw "
                "OBO discovery cache key. Discovery search would serve SP-narrowed "
                "results to OBO-authenticated users for a full TTL window. "
                "Suffix the bootstrap cache key with |bootstrap-app-principal."
            ),
        )


class VisibleAssetsShortTTLEmptyTests(unittest.TestCase):
    """Regression tests for the short-TTL-on-empty guard on the outer
    per-actor `runtime_inventory:<scope>` cache.

    Without the guard, a single empty fetch during warehouse warm-up / SP
    grant wipe traps every subsequent request at "Showing 0 of 0 assets"
    for the full 5-minute TTL, even after the inner cache has recovered.
    """

    def setUp(self) -> None:
        with api_cache._CACHE_LOCK:
            api_cache._TTL_CACHE.clear()

    def _runtime_deps_stub(self):
        hidden = tuple()

        def request_cache_scope(_request):
            return "alice@example.com|obo-available"

        def store_for_read():
            return object()

        def uc_for_request(_request):
            return object()

        return hidden, request_cache_scope, store_for_read, uc_for_request

    def _fake_columns(self):
        return [
            "table_catalog",
            "table_schema",
            "table_name",
            "table_type",
            "data_source_format",
            "fqn",
        ]

    def test_empty_inventory_is_cached_for_only_15s(self) -> None:
        call_count = {"n": 0}
        empty = pd.DataFrame(columns=self._fake_columns())

        def fake_visible(_uc, _store, **kwargs):
            call_count["n"] += 1
            return empty

        with patch.object(
            inventory_service, "_runtime_deps", self._runtime_deps_stub
        ), patch(
            "axiom.services.assets.visible_assets", side_effect=fake_visible
        ):
            # First call: populates the cache with the empty frame.
            inventory_service.visible_assets(None)
            # Second call within 15s: must hit cache (no new fetch).
            inventory_service.visible_assets(None)
            self.assertEqual(call_count["n"], 1)

            # Simulate the cache entry aging past 15s. The guard must
            # re-fetch instead of serving the stale empty for 5 minutes.
            key = "runtime_inventory:alice@example.com|obo-available"
            old_ts, payload = api_cache._TTL_CACHE[key]
            api_cache._TTL_CACHE[key] = (old_ts - 30.0, payload)

            inventory_service.visible_assets(None)
            self.assertEqual(
                call_count["n"],
                2,
                msg=(
                    "Empty inventory was served from cache past the 15s "
                    "short-TTL window. The per-actor cache must re-fetch "
                    "promptly after an empty result so Discovery self-heals "
                    "when the warehouse / SP grants recover."
                ),
            )

    def test_populated_inventory_still_caches_for_5min(self) -> None:
        call_count = {"n": 0}
        populated = pd.DataFrame(
            [
                {
                    "table_catalog": "prod",
                    "table_schema": "silver",
                    "table_name": "orders",
                    "table_type": "MANAGED",
                    "data_source_format": "DELTA",
                    "fqn": "prod.silver.orders",
                }
            ]
        )

        def fake_visible(_uc, _store, **kwargs):
            call_count["n"] += 1
            return populated

        with patch.object(
            inventory_service, "_runtime_deps", self._runtime_deps_stub
        ), patch(
            "axiom.services.assets.visible_assets", side_effect=fake_visible
        ):
            inventory_service.visible_assets(None)
            # Simulate aging to 60s (well past the 15s empty window, well
            # under the 5min populated window). Populated results must
            # remain cached.
            key = "runtime_inventory:alice@example.com|obo-available"
            old_ts, payload = api_cache._TTL_CACHE[key]
            api_cache._TTL_CACHE[key] = (old_ts - 60.0, payload)

            inventory_service.visible_assets(None)
            self.assertEqual(
                call_count["n"],
                1,
                msg="Populated inventory must still hit the full 5-minute TTL.",
            )


if __name__ == "__main__":
    unittest.main()
