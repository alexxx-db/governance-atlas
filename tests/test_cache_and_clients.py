from __future__ import annotations

import threading
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from axiom import bounded_cache, uc as uc_module
from axiom.bounded_cache import BoundedTTLCache
from axiom.services import ai_generation, genie, workspace_clients


class BoundedTTLCacheTests(unittest.TestCase):
    def test_evicts_least_recently_used_past_max_entries(self) -> None:
        cache = BoundedTTLCache(max_entries=2)
        cache["a"] = 1
        cache["b"] = 2
        self.assertEqual(cache.get("a"), 1)  # "a" is now most recent
        cache["c"] = 3
        self.assertEqual(sorted(cache.keys()), ["a", "c"])

    def test_entries_older_than_max_age_are_dropped(self) -> None:
        clock = [1000.0]
        with patch.object(bounded_cache.time, "monotonic", lambda: clock[0]):
            cache = BoundedTTLCache(max_entries=10, max_age_s=60)
            cache["old"] = 1
            clock[0] += 61
            self.assertIsNone(cache.get("old"))
            self.assertNotIn("old", cache)

    def test_sweep_removes_expired_entries_on_write(self) -> None:
        clock = [1000.0]
        with patch.object(bounded_cache.time, "monotonic", lambda: clock[0]):
            cache = BoundedTTLCache(max_entries=10, max_age_s=60)
            cache["old"] = 1
            clock[0] += 120
            cache["new"] = 2
            self.assertEqual(cache.keys(), ["new"])

    def test_dict_api_and_patch_dict_compatibility(self) -> None:
        cache = BoundedTTLCache(max_entries=10)
        cache["k"] = (1.0, "v")
        self.assertEqual(cache.pop("k"), (1.0, "v"))
        self.assertIsNone(cache.pop("k", None))
        with self.assertRaises(KeyError):
            cache.pop("k")
        with patch.dict(cache, {"x": 1}):
            self.assertEqual(cache["x"], 1)
        self.assertNotIn("x", cache)
        cache.update({"a": 1})
        cache.clear()
        self.assertEqual(len(cache), 0)

    def test_iteration_is_a_snapshot_under_concurrent_reads(self) -> None:
        cache = BoundedTTLCache(max_entries=500)
        for i in range(200):
            cache[f"k{i}"] = i
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                for i in range(200):
                    cache.get(f"k{i}")

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for _ in range(200):
                self.assertEqual(len([k for k in cache if k.startswith("k")]), 200)
        finally:
            stop.set()
            thread.join()

    def test_module_caches_are_bounded(self) -> None:
        from axiom.api import admin, cache as api_cache
        from axiom.services import assets, axiom_metrics, governance, lineage, live_metadata

        for mod_cache in (
            api_cache._TTL_CACHE,
            api_cache._OBO_CLIENT_CACHE,
            assets._TTL_CACHE,
            governance._TTL_CACHE,
            lineage._TTL_CACHE,
            live_metadata._TTL_CACHE,
            admin._TRUTH_CACHE,
            axiom_metrics._LINEAGE_FQN_CACHE,
        ):
            self.assertIsInstance(mod_cache, BoundedTTLCache)


class _Me:
    def __init__(self, user_id: str | None, fail: bool = False) -> None:
        self.user_id = user_id
        self.fail = fail
        self.calls = 0

    def me(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("scim unavailable")
        return SimpleNamespace(id=self.user_id, user_name=f"{self.user_id}@example.com")


def _obo_client(token: str, current_user: _Me) -> uc_module.UCSQLClient:
    client = uc_module.UCSQLClient.__new__(uc_module.UCSQLClient)
    client._user_access_token = token
    client.w = SimpleNamespace(current_user=current_user)
    return client


class ObOCacheScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        uc_module._OBO_PRINCIPALS.clear()

    def test_renewed_token_for_same_user_keeps_scope(self) -> None:
        alice = _Me("111")
        first = _obo_client("token-1", alice).cache_scope
        second = _obo_client("token-2", alice).cache_scope
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("obo-u-"))

    def test_different_users_get_different_scopes(self) -> None:
        alice = _obo_client("token-a", _Me("111")).cache_scope
        bob = _obo_client("token-b", _Me("222")).cache_scope
        self.assertNotEqual(alice, bob)

    def test_principal_resolved_once_per_token(self) -> None:
        alice = _Me("111")
        client = _obo_client("token-1", alice)
        for _ in range(5):
            client.cache_scope
        _obo_client("token-1", alice).cache_scope
        self.assertEqual(alice.calls, 1)

    def test_falls_back_to_token_hash_when_principal_unknown(self) -> None:
        first = _obo_client("token-1", _Me(None, fail=True)).cache_scope
        second = _obo_client("token-2", _Me(None, fail=True)).cache_scope
        self.assertTrue(first.startswith("obo-") and not first.startswith("obo-u-"))
        self.assertNotEqual(first, second)

    def test_app_principal_scope(self) -> None:
        client = uc_module.UCSQLClient.__new__(uc_module.UCSQLClient)
        client._user_access_token = None
        self.assertEqual(client.cache_scope, "app")


class _FakeWorkspaceClient:
    instances: list = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        _FakeWorkspaceClient.instances.append(self)


class _FakeConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class WorkspaceClientReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        workspace_clients.clear_workspace_clients()
        _FakeWorkspaceClient.instances = []

    def tearDown(self) -> None:
        workspace_clients.clear_workspace_clients()

    def test_genie_clients_reused_per_token_and_app(self) -> None:
        cfg = SimpleNamespace(workspace_host="https://example.cloud.databricks.com")
        with patch("databricks.sdk.WorkspaceClient", _FakeWorkspaceClient):
            a1 = genie._workspace_client(cfg, user_access_token="tok-a")
            a2 = genie._workspace_client(cfg, user_access_token="tok-a")
            b = genie._workspace_client(cfg, user_access_token="tok-b")
            app1 = genie._workspace_client(cfg)
            app2 = genie._workspace_client(cfg)
        self.assertIs(a1, a2)
        self.assertIsNot(a1, b)
        self.assertIs(app1, app2)
        self.assertIsNot(app1, a1)
        self.assertEqual(len(_FakeWorkspaceClient.instances), 3)

    def test_patched_client_class_is_never_served_a_stale_client(self) -> None:
        cfg = SimpleNamespace(workspace_host="")

        class Other(_FakeWorkspaceClient):
            pass

        with patch("databricks.sdk.WorkspaceClient", _FakeWorkspaceClient):
            first = genie._workspace_client(cfg)
        with patch("databricks.sdk.WorkspaceClient", Other):
            second = genie._workspace_client(cfg)
        self.assertIsInstance(second, Other)
        self.assertIsNot(first, second)

    def test_ai_client_sets_http_and_retry_timeouts(self) -> None:
        cfg = SimpleNamespace(workspace_host="https://example.cloud.databricks.com")
        with patch("databricks.sdk.WorkspaceClient", _FakeWorkspaceClient), patch(
            "databricks.sdk.config.Config", _FakeConfig
        ), patch.dict("os.environ", {"AXIOM_AI_HTTP_TIMEOUT_S": "25"}):
            client = ai_generation._workspace_client(cfg, user_access_token="tok")
            again = ai_generation._workspace_client(cfg, user_access_token="tok")
        self.assertIs(client, again)
        config_kwargs = client.kwargs["config"].kwargs
        self.assertEqual(config_kwargs["http_timeout_seconds"], 25)
        self.assertEqual(config_kwargs["retry_timeout_seconds"], 60)
        self.assertEqual(config_kwargs["token"], "tok")


class GenieWaitTimeoutTests(unittest.TestCase):
    def test_blocking_genie_call_is_bounded(self) -> None:
        captured = {}

        class _Genie:
            def start_conversation_and_wait(self, **kwargs):
                captured.update(kwargs)
                raise TimeoutError("timed out")

        client = SimpleNamespace(genie=_Genie())
        cfg = SimpleNamespace()
        with patch.object(
            genie, "provider_status", return_value={"state": "available", "spaceId": "s1"}
        ), patch.dict("os.environ", {"AXIOM_GENIE_WAIT_TIMEOUT_S": "45"}):
            with self.assertRaises(TimeoutError):
                genie.ask_genie(config=cfg, question="how many tables?", client=client)
        self.assertEqual(captured["timeout"], timedelta(seconds=45))


if __name__ == "__main__":
    unittest.main()
