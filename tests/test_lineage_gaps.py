"""Regression tests for the lineage "incomplete product" gap fixes.

Covers:
  L4 — cold-cache initial profile renders the focus as a LOADING state
       (never "Lineage Reference / Metadata unavailable"), and resolves
       identity for free when the visible inventory is already cached.
  L9 — non-openable (restricted / lineage-only) nodes emit a single clear
       permission-honest foot line instead of two stacked "Metadata …
       unavailable" variants.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import pandas as pd

from axiom.services import assets as asset_service
from axiom.services import lineage as lineage_service
from axiom.services import live_metadata as metadata_service


class FakeUC:
    def __init__(self, warehouse_id: str = "warehouse-gaps") -> None:
        self.warehouse_id = warehouse_id
        self.cache_scope = "gaps@example.com"

    def query_df(self, *_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("initial lineage profile must not run SQL")


def _visible_inventory_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "finance_prod.curated.revenue_daily",
                "table_catalog": "finance_prod",
                "table_schema": "curated",
                "table_name": "revenue_daily",
                "table_type": "TABLE",
                "data_source_format": "DELTA",
                "comment": "Daily revenue rollup",
                "certification": "Certified",
                "domain": "Finance",
                "tier": "Gold",
                "sensitivity": "Confidential",
                "governance_status": "Approved",
            }
        ]
    )


class RestrictedFootTests(unittest.TestCase):
    """L9 — one clear line for non-openable nodes."""

    def test_non_openable_node_emits_single_clear_foot_line(self) -> None:
        empty_inventory = pd.DataFrame(columns=["fqn"])
        row = pd.Series(
            {
                "fqn": "main.hidden.secret_table",
                "table_catalog": "main",
                "table_schema": "hidden",
                "table_name": "secret_table",
                "table_type": "",
                "data_source_format": "",
                "comment": "",
            }
        )
        with patch(
            "axiom.services.lineage.asset_service.inventory_row",
            return_value=row,
        ):
            node = lineage_service.graph_node_for_asset(
                FakeUC(),
                object(),
                "main.hidden.secret_table",
                "source",
                0,
                0,
                kicker="Upstream",
                visible_inventory=empty_inventory,
            )
        self.assertEqual(node["foot"], ["Not visible to your account"])
        self.assertNotIn("Metadata record unavailable", node["foot"])
        self.assertNotIn("Metadata unavailable", node["foot"])
        self.assertFalse(node["details"]["isOpenable"])

    def test_non_openable_node_collapses_caller_supplied_unavailable_foot(self) -> None:
        empty_inventory = pd.DataFrame(columns=["fqn"])
        row = pd.Series({"fqn": "main.hidden.other", "table_type": ""})
        with patch(
            "axiom.services.lineage.asset_service.inventory_row",
            return_value=row,
        ):
            node = lineage_service.graph_node_for_asset(
                FakeUC(),
                object(),
                "main.hidden.other",
                "target",
                0,
                0,
                kicker="Downstream",
                foot=["Metadata unavailable"],
                visible_inventory=empty_inventory,
            )
        # Even a caller-supplied "Metadata unavailable" foot must not stack
        # with a second unavailable line.
        self.assertEqual(node["foot"], ["Not visible to your account"])


class InitialProfileFocusTests(unittest.TestCase):
    """L4 — cold-cache initial profile focus is loading, not unavailable."""

    def setUp(self) -> None:
        lineage_service._TTL_CACHE.clear()

    def test_cold_cache_focus_renders_loading_not_unavailable(self) -> None:
        with patch(
            "axiom.services.lineage._peek_cached_visible_inventory",
            return_value=None,
        ):
            graph = lineage_service.build_initial_data_graph(
                FakeUC(),
                object(),
                "finance_prod.curated.revenue_daily",
            )
        focus = graph["nodes"][0]
        self.assertEqual(focus["kicker"], "Focus")
        self.assertEqual(focus["foot"], ["Loading metadata…"])
        self.assertNotEqual(focus["kind"], "Lineage Reference")
        details = focus["details"]
        self.assertEqual(details["openabilityState"], "loading")
        self.assertEqual(details["resolutionState"], "loading")
        # The user navigated here — never block clicks on an unresolved
        # identity (bootstrap-pessimism rule from CLAUDE.md).
        self.assertTrue(details["isOpenable"])
        for line in focus["foot"]:
            self.assertNotIn("unavailable", line.lower())

    def test_warm_inventory_focus_resolves_identity_without_scans(self) -> None:
        inventory = _visible_inventory_frame()
        with patch(
            "axiom.services.lineage._peek_cached_visible_inventory",
            return_value=inventory,
        ):
            graph = lineage_service.build_initial_data_graph(
                FakeUC(),
                object(),
                "finance_prod.curated.revenue_daily",
            )
        focus = graph["nodes"][0]
        self.assertEqual(focus["label"], "revenue_daily")
        self.assertEqual(focus["kind"], "Delta Table")
        self.assertTrue(focus["details"]["isOpenable"])
        self.assertEqual(focus["details"]["openabilityState"], "verified")
        self.assertEqual(focus["foot"], ["Certified"])
        self.assertEqual(focus["details"]["sensitivity"], "Confidential")

    def test_peek_reads_warm_assets_inventory_cache_without_loading(self) -> None:
        uc = FakeUC()
        inventory = _visible_inventory_frame()
        key = f"inventory:{asset_service._warehouse_key(uc)}"
        original = asset_service._TTL_CACHE.get(key)
        asset_service._TTL_CACHE[key] = (time.time(), inventory)
        try:
            peeked = lineage_service._peek_cached_visible_inventory(uc)
        finally:
            if original is None:
                asset_service._TTL_CACHE.pop(key, None)
            else:
                asset_service._TTL_CACHE[key] = original
        self.assertIsNotNone(peeked)
        self.assertIn(
            "finance_prod.curated.revenue_daily",
            list(peeked["fqn"]),
        )

    def test_peek_returns_none_when_no_cache_is_warm(self) -> None:
        uc = FakeUC()
        assets_key = f"inventory:{asset_service._warehouse_key(uc)}"
        metadata_key = f"asset_inventory:{metadata_service._warehouse_key(uc)}"
        original_assets = asset_service._TTL_CACHE.pop(assets_key, None)
        original_metadata = metadata_service._TTL_CACHE.pop(metadata_key, None)
        try:
            self.assertIsNone(lineage_service._peek_cached_visible_inventory(uc))
        finally:
            if original_assets is not None:
                asset_service._TTL_CACHE[assets_key] = original_assets
            if original_metadata is not None:
                metadata_service._TTL_CACHE[metadata_key] = original_metadata


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
