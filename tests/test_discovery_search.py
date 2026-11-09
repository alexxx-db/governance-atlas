from __future__ import annotations

import json
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from axiom.services import assets

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_runtime_api_openapi_snapshot.py"


def _load_snapshot_script():
    spec = importlib.util.spec_from_file_location(
        "generate_runtime_api_openapi_snapshot",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load runtime API snapshot script.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_script = _load_snapshot_script()
runtime_app = snapshot_script.runtime_app


def _inventory_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "main.finance.orders",
                "table_name": "orders",
                "table_catalog": "main",
                "table_schema": "finance",
                "table_type": "MANAGED",
                "data_source_format": "delta",
                "comment": "Orders fact table",
                "governance_score": 91,
                "domain": "Finance",
                "tier": "Gold",
                "certification": "Certified",
                "sensitivity": "Internal",
                "criticality": "Tier 1",
                "data_product": "Revenue 360",
                "pending_requests": 1,
                "business_owner": "Mia Chen",
                "tags": {"quality": "trusted"},
                "glossaryTerms": ["Order"],
            },
            {
                "fqn": "main.finance.invoices",
                "table_name": "invoices",
                "table_catalog": "main",
                "table_schema": "finance",
                "table_type": "MANAGED",
                "data_source_format": "delta",
                "comment": "Invoice fact table",
                "governance_score": 88,
                "domain": "Finance",
                "tier": "Silver",
                "certification": "Certified",
                "sensitivity": "Internal",
                "criticality": "Tier 2",
                "data_product": "Revenue 360",
                "pending_requests": 0,
                "business_owner": "Mia Chen",
                "tags": {"quality": "trusted"},
                "glossaryTerms": ["Invoice"],
            },
            {
                "fqn": "main.support.tickets",
                "table_name": "tickets",
                "table_catalog": "main",
                "table_schema": "support",
                "table_type": "MANAGED",
                "data_source_format": "delta",
                "comment": "Support ticket backlog",
                "governance_score": 63,
                "domain": "Support",
                "tier": "Bronze",
                "certification": "Unassigned",
                "sensitivity": "Restricted",
                "criticality": "Tier 3",
                "data_product": "Service Ops",
                "pending_requests": 3,
                "business_owner": "Lina Park",
                "tags": {"quality": "observed"},
                "glossaryTerms": ["Ticket"],
            },
        ]
    )


class StructuredDiscoverySearchTests(unittest.TestCase):
    def test_visible_assets_excludes_run_scoped_synthetic_validation_assets(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "emet.enterprise_metadata_ops.customer_profile_coverage",
                    "table_catalog": "emet",
                    "table_schema": "enterprise_metadata_ops",
                    "table_name": "customer_profile_coverage",
                    "tags": {},
                },
                {
                    "fqn": "emet.axiom_ax_stress_20260502120000_deadbee.workflow_entities",
                    "table_catalog": "emet",
                    "table_schema": "axiom_ax_stress_20260502120000_deadbee",
                    "table_name": "workflow_entities",
                    "tags": {},
                },
                {
                    "fqn": "emet.ops.validation_events",
                    "table_catalog": "emet",
                    "table_schema": "ops",
                    "table_name": "validation_events",
                    "tags": {
                        "axiom.exclude_from_organic_evidence": "true",
                    },
                },
            ]
        )

        visible = assets.visible_assets(inventory)

        self.assertEqual(
            visible["fqn"].tolist(),
            ["emet.enterprise_metadata_ops.customer_profile_coverage"],
        )

    def test_visible_assets_excludes_control_plane_schemas(self) -> None:
        inventory = pd.DataFrame(
            [
                {
                    "fqn": "emet.enterprise_metadata_ops.customer_profile_coverage",
                    "table_catalog": "emet",
                    "table_schema": "enterprise_metadata_ops",
                    "table_name": "customer_profile_coverage",
                    "tags": {},
                },
                {
                    "fqn": "emet.axiom_demo.customer_profile_coverage",
                    "table_catalog": "emet",
                    "table_schema": "axiom_demo",
                    "table_name": "customer_profile_coverage",
                    "tags": {},
                },
                {
                    "fqn": "emet.axiom.change_requests",
                    "table_catalog": "emet",
                    "table_schema": "axiom",
                    "table_name": "change_requests",
                    "tags": {},
                },
                {
                    "fqn": "emet.governance_hub.metadata_audit",
                    "table_catalog": "emet",
                    "table_schema": "governance_hub",
                    "table_name": "metadata_audit",
                    "tags": {},
                },
                {
                    "fqn": "emet.axiom_ai.axiom_ai_assets_current",
                    "table_catalog": "emet",
                    "table_schema": "axiom_ai",
                    "table_name": "axiom_ai_assets_current",
                    "tags": {},
                },
            ]
        )

        with patch.dict("os.environ", {"AXIOM_CATALOG": "emet", "AXIOM_SCHEMA": "axiom"}):
            visible = assets.visible_assets(inventory)

        self.assertEqual(
            visible["fqn"].tolist(),
            ["emet.enterprise_metadata_ops.customer_profile_coverage"],
        )

    def test_asset_payload_hides_internal_governance_tags(self) -> None:
        payload = assets.base_asset_payload(
            pd.Series(
                {
                    "fqn": "emet.axiom_demo.customer_profile_coverage",
                    "table_catalog": "emet",
                    "table_schema": "axiom_demo",
                    "table_name": "customer_profile_coverage",
                    "tags": {
                        "domain": "Customer",
                        "axiom_evidence_source": "home-northstar",
                        "axiom.exclude_from_organic_evidence": "false",
                    },
                    "domain": "Customer",
                }
            )
        )

        self.assertEqual(payload["tags"], {"domain": "Customer"})
        self.assertNotIn("axiom_evidence_source=home-northstar", payload["tagLabels"])

    def test_hidden_schema_deep_links_are_marked_hidden_before_exact_identity(self) -> None:
        with patch.dict("os.environ", {"AXIOM_CATALOG": "emet", "AXIOM_SCHEMA": "axiom"}):
            self.assertTrue(assets.asset_fqn_is_hidden("emet.axiom.change_requests"))
            self.assertTrue(assets.asset_fqn_is_hidden("emet.axiom_ai.axiom_ai_assets_current"))
            self.assertTrue(
                assets.asset_fqn_is_hidden("emet.axiom_demo.customer_profile_coverage")
            )
            self.assertFalse(
                assets.asset_fqn_is_hidden("emet.enterprise_metadata_ops.customer_profile_coverage")
            )

    def test_structured_query_supports_grouped_boolean_field_terms(self) -> None:
        payload = assets.discovery_search_payload(
            _inventory_df(),
            query='domain:Finance AND (name:orders OR name:invoices)',
            query_mode="structured",
            sort_by="Best match",
        )

        self.assertEqual(payload["queryState"]["state"], "valid")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            [asset["fqn"] for asset in payload["assets"]],
            ["main.finance.orders", "main.finance.invoices"],
        )

    def test_structured_query_supports_grouped_field_selectors_and_phrases(self) -> None:
        payload = assets.discovery_search_payload(
            _inventory_df(),
            query='domain:(Finance OR Support) AND description:"Orders fact table"',
            query_mode="structured",
            sort_by="Best match",
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["assets"][0]["fqn"], "main.finance.orders")

    def test_structured_query_exposes_removable_clause_chips_for_top_level_and_queries(self) -> None:
        payload = assets.discovery_search_payload(
            _inventory_df(),
            query='owner:"Mia Chen" AND domain:(Finance OR Support)',
            query_mode="structured",
            sort_by="Best match",
        )

        self.assertEqual(
            payload["queryState"]["clauseChips"],
            [
                {
                    "label": 'owner:"Mia Chen"',
                    "expression": 'owner:"Mia Chen"',
                    "nextQuery": "domain:(Finance OR Support)",
                    "removable": True,
                },
                {
                    "label": "domain:(Finance OR Support)",
                    "expression": "domain:(Finance OR Support)",
                    "nextQuery": 'owner:"Mia Chen"',
                    "removable": True,
                },
            ],
        )

    def test_structured_query_rejects_unknown_fields_without_widening_scope(self) -> None:
        with self.assertRaises(assets.DiscoveryQuerySyntaxError) as captured:
            assets.discovery_search_payload(
                _inventory_df(),
                query="workspace:main OR orders",
                query_mode="structured",
            )

        self.assertIn("Unknown discovery field `workspace`.", str(captured.exception))

    def test_structured_query_rejects_unbalanced_parentheses(self) -> None:
        with self.assertRaises(assets.DiscoveryQuerySyntaxError) as captured:
            assets.discovery_search_payload(
                _inventory_df(),
                query="domain:Finance AND (orders OR invoices",
                query_mode="structured",
            )

        self.assertIn("Missing closing parenthesis", str(captured.exception))

    def test_plain_query_mode_keeps_free_text_semantics(self) -> None:
        payload = assets.discovery_search_payload(
            _inventory_df(),
            query="Orders fact",
            query_mode="plain",
        )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["assets"][0]["fqn"], "main.finance.orders")


class DiscoverySemanticsAndTypoToleranceTests(unittest.TestCase):
    """Persona-audit fixes D1/D4/D5/D6/D7/D9 — canonical semantics + typo
    tolerance in the plain discovery search path."""

    def test_misspelled_query_returns_near_matches_with_did_you_mean(self) -> None:
        # D1: "invoces" (edit distance 1 from "invoices") must surface the
        # real asset via the near-match pass and set didYouMean.
        payload = assets.discovery_search_payload(_inventory_df(), query="invoces")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertIn(
            "main.finance.invoices",
            [asset["fqn"] for asset in payload["assets"]],
        )
        self.assertEqual(payload["didYouMean"], "invoices")
        self.assertTrue(payload["queryState"]["nearMatch"])

    def test_unknown_query_yields_zero_results_and_no_suggestion(self) -> None:
        # Never promise a rewrite that has no real matches.
        payload = assets.discovery_search_payload(
            _inventory_df(), query="zzzqqqxxyy"
        )
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["didYouMean"], "")
        self.assertFalse(payload["queryState"]["nearMatch"])

    def test_exact_query_does_not_trigger_near_match(self) -> None:
        payload = assets.discovery_search_payload(_inventory_df(), query="orders")
        self.assertEqual(payload["didYouMean"], "")
        self.assertFalse(payload["queryState"]["nearMatch"])

    def test_structured_mode_bare_typo_still_gets_did_you_mean(self) -> None:
        # Regression: the Discover UI sends EVERY search as
        # queryMode=structured, so gating didYouMean on plain mode left the
        # suggestion permanently empty in the live product ("custmer" -> 0
        # results, no rewrite). A structured AST with no field selectors is
        # semantically plain text and gets the same typo tolerance.
        payload = assets.discovery_search_payload(
            _inventory_df(), query="invoces", query_mode="structured"
        )
        self.assertEqual(payload["didYouMean"], "invoices")
        self.assertIn(
            "main.finance.invoices",
            [asset["fqn"] for asset in payload["assets"]],
        )
        self.assertTrue(payload["queryState"]["nearMatch"])

    def test_structured_field_scoped_typo_keeps_exact_semantics(self) -> None:
        # Field-scoped queries must never be fuzzily rewritten — owner:invoces
        # means exactly that, and zero results is the honest answer.
        payload = assets.discovery_search_payload(
            _inventory_df(), query="owner:invoces", query_mode="structured"
        )
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["didYouMean"], "")

    def test_suggest_discovery_query_corrects_single_token_misspellings(self) -> None:
        # Unit-level guarantees for the two live-verified misspellings.
        entries = [
            {"haystack": "customer profile gold customer 360", "asset": {}, "fields": {}},
            {"haystack": "payments daily finance curated", "asset": {}, "fields": {}},
        ]
        self.assertEqual(assets.suggest_discovery_query("custmer", entries), "customer")
        self.assertEqual(assets.suggest_discovery_query("paymnts", entries), "payments")

    def test_owner_search_matches_uc_table_owner_and_summary(self) -> None:
        # Regression: owner:"<uc owner email>" returned 0 results because the
        # owner search field only indexed local steward/business owner names.
        # The UC table_owner (authoritative) and the assignment roll-up
        # (owners_summary) must both be searchable.
        frame = _inventory_df()
        frame["uc_owner"] = ["abarreto@shorecp.com", "", ""]
        frame["owners_summary"] = ["", "steward@shorecp.com", ""]

        by_uc_owner = assets.discovery_search_payload(
            frame, query='owner:"abarreto@shorecp.com"', query_mode="structured"
        )
        self.assertEqual(
            [asset["fqn"] for asset in by_uc_owner["assets"]],
            ["main.finance.orders"],
        )

        by_summary = assets.discovery_search_payload(
            frame, query='owner:"steward@shorecp.com"', query_mode="structured"
        )
        self.assertEqual(
            [asset["fqn"] for asset in by_summary["assets"]],
            ["main.finance.invoices"],
        )

        # Local owner names keep working.
        by_name = assets.discovery_search_payload(
            frame, query='owner:"Lina Park"', query_mode="structured"
        )
        self.assertEqual(
            [asset["fqn"] for asset in by_name["assets"]],
            ["main.support.tickets"],
        )

    def test_domain_facet_emits_every_domain_bucket(self) -> None:
        # The API must ship ALL domain values (plus Unassigned) — any cap
        # belongs to no layer. Chips summing below the All total is a defect.
        frame = _inventory_df()
        payload = assets.discovery_search_payload(frame)
        domain_rows = payload["facets"]["domains"]
        values = [row["value"] for row in domain_rows]
        self.assertEqual(values[0], "All domains")
        for expected in ("Finance", "Support", "Unassigned"):
            self.assertIn(expected, values)
        self.assertEqual(
            sum(row["count"] for row in domain_rows[1:]),
            domain_rows[0]["count"],
        )

    def test_certified_view_is_strict(self) -> None:
        # D6: only certification == "Certified" counts; Draft/Trusted and
        # Unassigned are excluded from the Certified view.
        frame = _inventory_df()
        frame.loc[frame["fqn"] == "main.finance.invoices", "certification"] = "Draft"
        payload = assets.discovery_search_payload(frame, views=["Certified"])
        self.assertEqual(
            [asset["fqn"] for asset in payload["assets"]],
            ["main.finance.orders"],
        )

    def test_business_criticality_filter_matches_criticality_tag(self) -> None:
        # D4: the filter reads the same field set semantics.is_critical uses,
        # so `Tier 1` (criticality axis) matches even though the explicit
        # businessCriticality enum field is unassigned.
        payload = assets.discovery_search_payload(
            _inventory_df(), business_criticalities=["Tier 1"]
        )
        self.assertEqual(
            [asset["fqn"] for asset in payload["assets"]],
            ["main.finance.orders"],
        )

    def test_cde_only_uses_canonical_criticality_derived_predicate(self) -> None:
        # D4/D5: cdeOnly resolves through semantics.is_cde_asset — the
        # Tier 1 / Critical assets count as CDEs without an explicit tag,
        # and the per-asset isCde flag agrees.
        payload = assets.discovery_search_payload(_inventory_df(), cde_only=True)
        fqns = [asset["fqn"] for asset in payload["assets"]]
        self.assertIn("main.finance.orders", fqns)  # criticality: Tier 1
        self.assertNotIn("main.support.tickets", fqns)  # Tier 3 — not a CDE
        for asset in payload["assets"]:
            self.assertTrue(asset["isCde"])

    def test_facet_counts_include_unassigned_and_sum_to_total(self) -> None:
        # D7: every facet carries an Unassigned bucket so chip sums equal
        # the "All" total.
        payload = assets.discovery_search_payload(_inventory_df())
        for facet_name in ("certifications", "domains", "tiers", "sensitivities"):
            rows = payload["facets"][facet_name]
            all_row = rows[0]
            self.assertEqual(
                sum(row["count"] for row in rows[1:]),
                all_row["count"],
                f"facet {facet_name} does not reconcile",
            )
            self.assertIn("Unassigned", [row["value"] for row in rows])

    def test_governance_score_sort_breaks_ties_with_fewer_open_requests(self) -> None:
        # D9: openRequests is a quality-NEGATIVE tiebreaker — fewer open
        # requests ranks higher when scores tie.
        frame = _inventory_df()
        frame["governance_score"] = 100
        payload = assets.discovery_search_payload(frame, sort_by="Governance score")
        open_requests = [asset["openRequests"] for asset in payload["assets"]]
        self.assertEqual(open_requests, sorted(open_requests))

    def test_recently_updated_sort_orders_newest_first(self) -> None:
        frame = _inventory_df()
        frame["last_altered"] = [
            "2026-07-01T00:00:00",
            "2026-07-15T00:00:00",
            "2026-07-10T00:00:00",
        ]
        payload = assets.discovery_search_payload(frame, sort_by="Recently updated")
        self.assertEqual(
            [asset["fqn"] for asset in payload["assets"]],
            [
                "main.finance.invoices",
                "main.support.tickets",
                "main.finance.orders",
            ],
        )

    def test_legacy_trust_score_sort_label_still_accepted(self) -> None:
        # The runtime now advertises "Governance score", but stale clients
        # sending "Trust score" must not silently fall back to best-match.
        renamed = assets.discovery_search_payload(
            _inventory_df(), sort_by="Governance score"
        )
        legacy = assets.discovery_search_payload(
            _inventory_df(), sort_by="Trust score"
        )
        self.assertEqual(
            [asset["fqn"] for asset in renamed["assets"]],
            [asset["fqn"] for asset in legacy["assets"]],
        )


class DiscoverySearchEndpointTests(unittest.TestCase):
    def test_api_discovery_search_returns_invalid_query_payload_for_structured_errors(self) -> None:
        with patch.object(runtime_app, "_ensure_live_runtime", return_value=None), patch.object(
            runtime_app,
            "_discovery_search_payload",
            side_effect=assets.DiscoveryQuerySyntaxError("Unknown discovery field `workspace`."),
        ):
            response = runtime_app.api_discovery_search(
                request=SimpleNamespace(headers={}),
                query="workspace:main",
                query_mode="structured",
            )

        self.assertEqual(response.status_code, 400)
        if hasattr(response, "body"):
            payload = json.loads(response.body.decode("utf-8"))
        else:
            payload = response.content
        self.assertEqual(payload["detail"], "Unknown discovery field `workspace`.")
        self.assertEqual(payload["invalidQuery"]["state"], "invalid")
        self.assertIn("supportedFields", payload["invalidQuery"])


if __name__ == "__main__":
    unittest.main()
