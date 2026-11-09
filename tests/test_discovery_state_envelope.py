"""Audit A1.2 coverage: the /api/discovery/search envelope exposes a
fine-grained `discoveryState` vocabulary alongside the existing `state`
field so the frontend can render truthful empty states (no_visible_assets,
filters_exclude_all / no_results, unavailable, live).

The tests drive two layers:
  1) `resolve_discovery_state` as a pure function (state machine).
  2) `api_discovery_search` end-to-end with mocked inventory + payload so
     we can verify the envelope shape, preserved `state`, and new
     `discoveryState` field the audit requires.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.api import discovery as discovery_module


def _request(headers=None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {})


class ResolveDiscoveryStatePureTests(unittest.TestCase):
    """Pure-function coverage of the four audit vocabulary states."""

    def test_runtime_not_live_returns_unavailable(self) -> None:
        resolved = discovery_module.resolve_discovery_state(
            runtime_state="unavailable",
            result_count=0,
            visible_assets_count=0,
            filters_applied=False,
        )
        self.assertEqual(resolved["discoveryState"], "unavailable")
        self.assertIn("unavailable", resolved["discoveryStateReason"].lower())

    def test_no_filters_and_zero_visible_assets_returns_no_visible_assets(self) -> None:
        resolved = discovery_module.resolve_discovery_state(
            runtime_state="live",
            result_count=0,
            visible_assets_count=0,
            filters_applied=False,
        )
        self.assertEqual(resolved["discoveryState"], "no_visible_assets")

    def test_filters_applied_with_zero_results_returns_filters_exclude_all(self) -> None:
        resolved = discovery_module.resolve_discovery_state(
            runtime_state="live",
            result_count=0,
            visible_assets_count=42,
            filters_applied=True,
        )
        self.assertEqual(resolved["discoveryState"], "filters_exclude_all")
        # Alias kept so audit-vocabulary consumers matching `no_results`
        # also see the envelope classify this case correctly.
        self.assertEqual(resolved.get("discoveryStateAlias"), "no_results")

    def test_positive_result_count_returns_live(self) -> None:
        resolved = discovery_module.resolve_discovery_state(
            runtime_state="live",
            result_count=5,
            visible_assets_count=42,
            filters_applied=True,
        )
        self.assertEqual(resolved["discoveryState"], "live")
        self.assertEqual(resolved["discoveryStateReason"], "")


class AnyFilterAppliedTests(unittest.TestCase):
    def test_plain_query_does_not_count_as_filter(self) -> None:
        # D2 semantics change: the query text is reported separately
        # (query_present) so a zero-result search with no chips resolves to
        # `no_matches` instead of blaming filters the user never set.
        self.assertFalse(
            discovery_module._any_filter_applied(
                query="orders",
                views=None,
                types=None,
                catalogs=None,
                domains=None,
                tiers=None,
                certifications=None,
                sensitivities=None,
            )
        )

    def test_cde_only_counts_as_filter(self) -> None:
        self.assertTrue(
            discovery_module._any_filter_applied(
                query="",
                views=None,
                types=None,
                catalogs=None,
                domains=None,
                tiers=None,
                certifications=None,
                sensitivities=None,
                cde_only=True,
            )
        )

    def test_business_criticalities_count_as_filter(self) -> None:
        self.assertTrue(
            discovery_module._any_filter_applied(
                query="",
                views=None,
                types=None,
                catalogs=None,
                domains=None,
                tiers=None,
                certifications=None,
                sensitivities=None,
                business_criticalities=["Critical"],
            )
        )

    def test_empty_query_and_empty_groups_is_unfiltered(self) -> None:
        self.assertFalse(
            discovery_module._any_filter_applied(
                query="",
                views=[],
                types=[],
                catalogs=[],
                domains=[],
                tiers=[],
                certifications=[],
                sensitivities=[],
            )
        )

    def test_group_with_blank_values_is_unfiltered(self) -> None:
        self.assertFalse(
            discovery_module._any_filter_applied(
                query="  ",
                views=["", "   "],
                types=None,
                catalogs=None,
                domains=None,
                tiers=None,
                certifications=None,
                sensitivities=None,
            )
        )

    def test_any_non_blank_group_value_counts(self) -> None:
        self.assertTrue(
            discovery_module._any_filter_applied(
                query="",
                views=None,
                types=None,
                catalogs=None,
                domains=["Finance"],
                tiers=None,
                certifications=None,
                sensitivities=None,
            )
        )


def _payload(count: int, assets=None) -> dict:
    return {
        "assets": assets or [],
        "count": count,
        "facets": {},
        "queryState": {
            "state": "empty" if not assets else "valid",
            "message": "",
            "syntaxHint": "",
            "supportedFields": [],
            "clauseChips": [],
        },
        "selection": {"primaryAssetFqn": "", "reason": "none"},
    }


class DiscoverySearchEnvelopeTests(unittest.TestCase):
    """End-to-end: the endpoint attaches `discoveryState` to `meta` while
    preserving the existing `state` field and all other meta keys."""

    def _invoke(
        self,
        *,
        payload_count: int,
        visible_assets: int,
        query: str = "",
        domains=None,
        runtime_state: str = "live",
    ):
        inventory_df = pd.DataFrame(index=range(visible_assets))
        with patch.object(
            discovery_module, "_request_auth_mode", return_value="app-principal-only"
        ):
            # Patch the runtime helpers the endpoint imports lazily. The
            # `from runtime_app import ...` line inside the endpoint resolves
            # names from the runtime_app module object at call time, so we
            # patch them there.
            import runtime_app

            with patch.object(
                runtime_app, "_ensure_live_runtime", return_value=None
            ), patch.object(
                runtime_app,
                "_discovery_search_payload",
                return_value=_payload(payload_count),
            ), patch.object(
                runtime_app,
                "_uc_runtime_status",
                return_value={"state": runtime_state, "message": ""},
            ), patch.object(
                runtime_app, "_visible_assets", return_value=inventory_df
            ):
                response = discovery_module.api_discovery_search(
                    request=_request(),
                    query=query,
                    domains=domains,
                )
        body = json.loads(response.body.decode("utf-8"))
        return response, body

    def test_envelope_preserves_state_and_exposes_live_discovery_state(self) -> None:
        response, body = self._invoke(
            payload_count=3, visible_assets=42, query="", domains=None
        )
        self.assertEqual(response.status_code, 200)
        meta = body["meta"]
        # Existing contract untouched.
        self.assertIn(meta["state"], {"available", "degraded"})
        # New audit vocabulary field.
        self.assertEqual(meta["discoveryState"], "live")
        self.assertEqual(meta["discoveryStateReason"], "")
        self.assertEqual(meta["visibleAssetCount"], 42)

    def test_envelope_flags_no_visible_assets_when_inventory_is_empty(self) -> None:
        _, body = self._invoke(payload_count=0, visible_assets=0)
        meta = body["meta"]
        self.assertEqual(meta["discoveryState"], "no_visible_assets")
        self.assertIn("visible assets", meta["discoveryStateReason"].lower())

    def test_envelope_flags_no_matches_when_only_query_applied(self) -> None:
        # D2: a zero-result QUERY with no filter chips must report
        # `no_matches` — the old filters_exclude_all state blamed filters
        # the user never set. The no_results alias is preserved.
        _, body = self._invoke(
            payload_count=0, visible_assets=42, query="orders", domains=None
        )
        meta = body["meta"]
        self.assertEqual(meta["discoveryState"], "no_matches")
        self.assertEqual(meta.get("discoveryStateAlias"), "no_results")

    def test_envelope_flags_filters_exclude_all_when_chips_applied(self) -> None:
        _, body = self._invoke(
            payload_count=0, visible_assets=42, query="", domains=["Finance"]
        )
        meta = body["meta"]
        self.assertEqual(meta["discoveryState"], "filters_exclude_all")
        self.assertEqual(meta.get("discoveryStateAlias"), "no_results")

    def test_envelope_flags_unavailable_when_runtime_not_live(self) -> None:
        # Bypass _ensure_live_runtime (which would otherwise 503 before we
        # reach the envelope branch) and force _uc_runtime_status to report
        # a non-live state so the endpoint's resolver sees it.
        _, body = self._invoke(
            payload_count=0,
            visible_assets=0,
            runtime_state="unavailable",
        )
        meta = body["meta"]
        self.assertEqual(meta["discoveryState"], "unavailable")
        self.assertIn("runtime", meta["discoveryStateReason"].lower())


if __name__ == "__main__":
    unittest.main()
