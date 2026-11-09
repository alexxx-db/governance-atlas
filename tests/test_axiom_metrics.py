from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import pandas as pd

from axiom.services import axiom_metrics


def _assets_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fqn": "main.customer.customer_dim",
                "table_catalog": "main",
                "table_schema": "customer",
                "table_name": "customer_dim",
                "comment": "Customer dimension",
                "domain": "Customer",
                "tier": "Tier 1",
                "certification": "Certified",
                "sensitivity": "Confidential",
                "criticality": "Critical",
                "data_product": "Customer 360",
                "business_owner": "abarreto@shorecp.com",
            },
            {
                "fqn": "main.finance.revenue",
                "table_catalog": "main",
                "table_schema": "finance",
                "table_name": "revenue",
                "comment": "",
                "domain": "Finance",
                "tier": "",
                "certification": "Draft",
                "sensitivity": "",
                "criticality": "Medium",
                "data_product": "",
                "business_owner": "",
            },
        ]
    )


class FakeStore:
    def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        rows = pd.DataFrame(
            [
                {
                    "request_id": "REQ-1",
                    "created_at": "2026-04-24 01:00:00",
                    "created_by": "abarreto@shorecp.com",
                    "status": "pending",
                    "uc_full_name": "main.customer.customer_dim",
                    "new_comment": "Policy exception review",
                }
            ]
        )
        if status:
            return rows[rows["status"].eq(status)].copy()
        return rows

    def list_metadata_audit(self, **_: object) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "audit_id": "AUD-1",
                    "entity_fqn": "main.customer.customer_dim",
                    "action": "metadata updated",
                    "status": "success",
                    "detail": "Owner changed",
                    "created_at": "2026-04-24 01:05:00",
                    "actor_email": "abarreto@shorecp.com",
                }
            ]
        )

    def list_glossary_terms(self, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame(
            [{"term_id": "term-1", "name": "Customer ID", "definition": "Customer key"}]
        )

    def list_classifications(self) -> pd.DataFrame:
        return pd.DataFrame([{"classification_id": "class-1", "display_name": "PII"}])

    def list_domains(self) -> pd.DataFrame:
        return pd.DataFrame([{"domain_id": "customer", "display_name": "Customer"}])

    def list_data_products(self) -> pd.DataFrame:
        return pd.DataFrame([{"data_product_id": "customer-360", "display_name": "Customer 360"}])

    def list_roles(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"email": "abarreto@shorecp.com", "role": "admin"},
                {"email": "steward@shorecp.com", "role": "steward"},
            ]
        )

    def list_identity_directory_entries(
        self,
        principal_type: str | None = None,
        *,
        active_only: bool = False,
    ) -> pd.DataFrame:
        rows = pd.DataFrame(
            [
                {"entry_id": "u1", "principal_type": "user", "email": "abarreto@shorecp.com", "is_active": True},
                {"entry_id": "u2", "principal_type": "user", "email": "steward@shorecp.com", "is_active": True},
                {"entry_id": "g1", "principal_type": "group", "email": "", "is_active": True},
                {"entry_id": "sp1", "principal_type": "service_principal", "email": "", "is_active": True},
            ]
        )
        if principal_type:
            rows = rows[rows["principal_type"].eq(principal_type)].copy()
        if active_only:
            rows = rows[rows["is_active"].eq(True)].copy()
        return rows


@dataclass(frozen=True)
class ChangeRequest:
    request_id: str
    created_at: str
    created_by: str
    status: str
    uc_full_name: str
    new_comment: str
    new_uc_tags: dict[str, str]
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None


class DetailStore(FakeStore):
    def get_change_request(self, request_id: str) -> ChangeRequest | None:
        if request_id != "REQ-1":
            return None
        return ChangeRequest(
            request_id="REQ-1",
            created_at="2026-04-24 01:00:00",
            created_by="abarreto@shorecp.com",
            status="pending",
            uc_full_name="main.customer.customer_dim",
            new_comment="description: Curated customer dimension",
            new_uc_tags={"domain": "Customer", "certification": "Certified"},
        )


class OwnershipGroundingHelpersTests(unittest.TestCase):
    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"fqn": "finance_prod.bronze.charges_raw", "domain": "Finance", "uc_owner": "abarreto@shorecp.com"},
                {"fqn": "finance_prod.bronze.orders_raw", "domain": "Finance"},
                {"fqn": "finance_prod.gold.revenue", "domain": "Finance", "business_owner": "cfo@shorecp.com"},
                {"fqn": "main.customer.customer_dim", "domain": "Customer", "steward": "dm@shorecp.com"},
            ]
        )

    def test_known_domains_distinct_nonempty(self) -> None:
        domains = axiom_metrics.known_domains(self._frame())
        self.assertIn("Finance", domains)
        self.assertIn("Customer", domains)

    def test_ownership_gap_metrics_match_dashboard_predicate(self) -> None:
        metrics = axiom_metrics.ownership_gap_metrics(visible_assets=self._frame())
        self.assertEqual(metrics["totalAssets"], 4)
        self.assertEqual(metrics["totalOwnerless"], 2)
        self.assertEqual(metrics["byDomain"]["Finance"], {"total": 3, "ownerless": 2})
        self.assertEqual(metrics["byDomain"]["Customer"], {"total": 1, "ownerless": 0})

    def test_asset_ownership_reports_uc_owner_and_governance_gap(self) -> None:
        own = axiom_metrics.asset_ownership(visible_assets=self._frame(), fqn="finance_prod.bronze.charges_raw")
        self.assertTrue(own["found"])
        self.assertEqual(own["ucOwner"], "abarreto@shorecp.com")
        self.assertEqual(own["businessOwners"], [])
        self.assertEqual(own["stewards"], [])

    def test_asset_ownership_missing_asset(self) -> None:
        own = axiom_metrics.asset_ownership(visible_assets=self._frame(), fqn="nope.nope.nope")
        self.assertFalse(own["found"])

    @staticmethod
    def _scoped() -> pd.DataFrame:
        return pd.DataFrame([
            {"fqn": "a", "domain": "Finance", "tier": "Tier 1", "sensitivity": "PII", "certification": "Certified", "criticality": "Critical"},
            {"fqn": "b", "domain": "Finance", "tier": "Tier 1", "certification": "Draft", "criticality": "Critical"},
            {"fqn": "c", "domain": "Customer", "tier": "Tier 2", "sensitivity": "PII", "certification": "Certified"},
        ])

    def test_known_facet_values(self) -> None:
        facets = axiom_metrics.known_facet_values(self._scoped())
        self.assertIn("Finance", facets["domains"])
        self.assertIn("Tier 1", facets["tiers"])
        self.assertIn("PII", facets["sensitivities"])

    def test_scoped_asset_count_predicates(self) -> None:
        df = self._scoped()
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df, domains=["Finance"], certified=True), 1)
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df, domains=["Finance"], certified=False), 1)
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df, tiers=["Tier 1"]), 2)
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df, sensitivities=["PII"]), 2)
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df, domains=["Finance"], critical=True), 2)
        self.assertEqual(axiom_metrics.scoped_asset_count(visible_assets=df), 3)


class AxiomMetricsTests(unittest.TestCase):
    def test_command_center_payload_counts_visible_assets_without_fake_deltas(self) -> None:
        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=FakeStore(),
        )

        self.assertEqual(payload["estate"]["visibleAssetCount"], 2)
        self.assertEqual(payload["estate"]["catalogCount"], 1)
        self.assertEqual(payload["kpis"][0]["key"], "governedAssets")
        self.assertEqual(payload["kpis"][0]["value"], 2)
        self.assertEqual(payload["kpis"][1]["value"], 1)
        self.assertNotIn("delta", payload["kpis"][0])
        open_kpi = next(item for item in payload["kpis"] if item["key"] == "openStewardship")
        self.assertIn("delta", open_kpi)
        self.assertGreaterEqual(len(open_kpi["sparkline"]), 2)
        policy_kpi = next(item for item in payload["kpis"] if item["key"] == "policyExceptions")
        self.assertIn("delta", policy_kpi)
        self.assertGreaterEqual(len(policy_kpi["sparkline"]), 2)
        self.assertEqual(payload["governance"]["openRequests"], 1)
        self.assertEqual(payload["governance"]["policyExceptions"], 1)
        # Posture is now a documented composite (see POSTURE_FORMULA), so a
        # populated estate produces a real score with the formula attached.
        self.assertIsNotNone(payload["posture"]["overall"])
        self.assertEqual(payload["posture"]["state"], "available")
        self.assertEqual(payload["posture"]["formula"], axiom_metrics.POSTURE_FORMULA)
        self.assertEqual(payload["topDomains"][0]["domain"], "Customer")
        self.assertEqual(payload["catalogHealth"][0]["catalog"], "main")
        self.assertEqual(payload["catalogHealth"][0]["assetCount"], 2)
        self.assertEqual(payload["meta"]["primaryCatalog"], "main")
        self.assertEqual(payload["recentEvents"][0]["priority"], "")

    @patch.dict(os.environ, {"AXIOM_CATALOG": "emet"})
    def test_command_center_catalog_health_uses_full_inventory_not_recent_slice(self) -> None:
        visible_assets = pd.DataFrame(
            [
                {
                    "fqn": "emet.enterprise_metadata_ops.customer_profile_coverage",
                    "table_catalog": "emet",
                    "domain": "Customer",
                    "certification": "Certified",
                    "sensitivity": "Confidential",
                    "criticality": "Critical",
                    "business_owner": "customer-steward@shorecp.com",
                },
                {
                    "fqn": "customer_360.gold.customer_profile",
                    "table_catalog": "customer_360",
                    "domain": "Customer",
                    "certification": "Certified",
                    "sensitivity": "Confidential",
                    "criticality": "Critical",
                    "business_owner": "customer-steward@shorecp.com",
                },
                *[
                    {
                        "fqn": f"finance_prod.gold.revenue_{idx}",
                        "table_catalog": "finance_prod",
                        "domain": "Finance",
                        "certification": "Certified",
                        "sensitivity": "Confidential",
                        "criticality": "Critical",
                        "business_owner": "finance-steward@shorecp.com",
                    }
                    for idx in range(3)
                ],
            ]
        )

        payload = axiom_metrics.command_center_payload(
            visible_assets=visible_assets,
            store=FakeStore(),
        )

        self.assertEqual(payload["catalogHealth"][0]["catalog"], "finance_prod")
        self.assertEqual(payload["catalogHealth"][0]["assetCount"], 3)
        self.assertEqual(payload["meta"]["primaryCatalog"], "finance_prod")
        self.assertEqual(
            [row["catalog"] for row in payload["catalogHealth"]],
            ["finance_prod", "customer_360", "emet"],
        )

    def test_recent_events_derive_high_priority_from_audit_evidence(self) -> None:
        class PriorityStore(FakeStore):
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "AUD-CRIT",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "policy-exception-detected",
                            "status": "failed",
                            "detail": "Critical policy exception detected from governed audit evidence.",
                            "created_at": "2026-04-24 01:05:00",
                            "actor_email": "abarreto@shorecp.com",
                        }
                    ]
                )

        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=PriorityStore(),
        )

        self.assertEqual(payload["recentEvents"][0]["priority"], "high")
        self.assertEqual(payload["recentEvents"][0]["severity"], "high")
        self.assertEqual(payload["recentEvents"][0]["tone"], "bad")
        self.assertEqual(payload["recentEvents"][0]["title"], "Policy Exception Detected")

    def test_command_center_payload_rejects_internal_seed_rows(self) -> None:
        class SeededStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "GOV-HOME-EVIDENCE-request-01",
                            "created_at": "2026-04-24 01:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Policy exception review: Review ax-taxonomy-term-customer-segment.",
                        }
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "GOV-HOME-EVIDENCE-audit-01",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "policy-exception-detected",
                            "source": "home-evidence-plane",
                            "status": "failed",
                            "detail": "Review GOV-HOME-EVIDENCE-request-01 for ax-taxonomy-term-customer-segment.",
                            "request_id": "GOV-HOME-EVIDENCE-request-01",
                            "created_at": "2026-04-24 01:05:00",
                            "actor_email": "abarreto@shorecp.com",
                        }
                    ]
                )

        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=SeededStore(),
        )
        serialized = json.dumps(payload)

        self.assertEqual(payload["governance"]["pendingRequests"], [])
        self.assertEqual(payload["recentEvents"], [])
        self.assertEqual(payload["dataQuality"]["nonAuthoritativeRowsExcluded"], 2)
        self.assertNotIn("GOV-HOME-EVIDENCE", serialized)
        self.assertNotIn("ax-taxonomy-term", serialized)
        self.assertNotIn("home-evidence-plane", serialized)

    def test_command_center_audit_readiness_uses_documented_formula(self) -> None:
        # Audit readiness is now computed from asset metadata dimensions
        # (documented + owned + classified), so it stays available even when
        # the audit log itself has no rows — but only with visible assets.
        class NoAuditStore(FakeStore):
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=NoAuditStore(),
        )

        audit_kpi = next(item for item in payload["kpis"] if item["key"] == "auditReadiness")
        self.assertIsNotNone(audit_kpi["value"])
        self.assertEqual(audit_kpi["state"], "available")
        self.assertEqual(audit_kpi["formula"], axiom_metrics.AUDIT_READINESS_FORMULA)

        empty_payload = axiom_metrics.command_center_payload(
            visible_assets=pd.DataFrame(),
            store=NoAuditStore(),
        )
        empty_kpi = next(item for item in empty_payload["kpis"] if item["key"] == "auditReadiness")
        self.assertIsNone(empty_kpi["value"])
        self.assertEqual(empty_kpi["state"], "unavailable")

    def test_command_center_marks_unsupported_zero_signals_unavailable(self) -> None:
        class NoPolicySignalStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                return pd.DataFrame()

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame()

        payload = axiom_metrics.command_center_payload(
            visible_assets=pd.DataFrame(),
            store=NoPolicySignalStore(),
        )

        coverage_kpi = next(item for item in payload["kpis"] if item["key"] == "metadataCoverage")
        certified_critical_kpi = next(item for item in payload["kpis"] if item["key"] == "certifiedCriticalAssets")
        policy_kpi = next(item for item in payload["kpis"] if item["key"] == "policyExceptions")
        self.assertIsNone(coverage_kpi["value"])
        self.assertEqual(coverage_kpi["state"], "unavailable")
        self.assertIsNone(certified_critical_kpi["value"])
        self.assertEqual(certified_critical_kpi["state"], "unavailable")
        # The request/audit sources responded (with zero rows), so zero policy
        # exceptions is a real, backed answer — not an unavailable signal.
        self.assertEqual(policy_kpi["value"], 0)
        self.assertEqual(policy_kpi["state"], "available")
        self.assertIn("No policy exceptions recorded", policy_kpi["reason"])

    def test_command_center_payload_replaces_nan_with_json_safe_nulls(self) -> None:
        payload = axiom_metrics.command_center_payload(
            visible_assets=pd.DataFrame(
                [
                    {
                        "fqn": "main.nan.asset",
                        "table_catalog": "main",
                        "table_schema": "nan",
                        "table_name": "asset",
                        "comment": float("nan"),
                        "domain": float("nan"),
                        "tier": float("nan"),
                        "certification": float("nan"),
                        "sensitivity": float("nan"),
                        "criticality": float("nan"),
                        "data_product": float("nan"),
                    }
                ]
            ),
            store=FakeStore(),
        )

        encoded = json.dumps(payload, allow_nan=False)
        self.assertNotIn("NaN", encoded)
        self.assertEqual(payload["topDomains"][0]["domain"], "Unassigned")

    def test_command_center_payload_replaces_timestamps_with_json_safe_strings(self) -> None:
        class TimestampStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "REQ-TS",
                            "created_at": pd.Timestamp("2026-04-24T01:00:00Z"),
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Timestamp-backed request",
                        }
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "AUD-TS",
                            "entity_fqn": "main.customer.customer_dim",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Timestamp-backed audit row",
                            "created_at": pd.Timestamp("2026-04-24T01:05:00Z"),
                            "actor_email": "abarreto@shorecp.com",
                        }
                    ]
                )

        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=TimestampStore(),
        )

        encoded = json.dumps(payload, allow_nan=False)
        self.assertIn("2026-04-24T01:00:00+00:00", encoded)
        self.assertEqual(
            payload["governance"]["pendingRequests"][0]["created_at"],
            "2026-04-24T01:00:00+00:00",
        )

    def test_certified_critical_assets_zero_requires_source_signals(self) -> None:
        payload = axiom_metrics.command_center_payload(
            visible_assets=pd.DataFrame(
                [
                    {
                        "fqn": "main.raw.events",
                        "table_catalog": "main",
                        "table_schema": "raw",
                        "table_name": "events",
                    }
                ]
            ),
            store=FakeStore(),
        )

        kpi = next(item for item in payload["kpis"] if item["key"] == "certifiedCriticalAssets")
        self.assertIsNone(kpi["value"])
        self.assertEqual(kpi["state"], "unavailable")

    def test_open_stewardship_unavailable_when_store_read_fails(self) -> None:
        class FailingRequestStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                raise RuntimeError("store offline")

        payload = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=FailingRequestStore(),
        )

        kpi = next(item for item in payload["kpis"] if item["key"] == "openStewardship")
        self.assertIsNone(kpi["value"])
        self.assertEqual(kpi["state"], "unavailable")
        self.assertIsNone(payload["governance"]["openRequests"])
        self.assertTrue(payload["meta"]["warnings"])

    def test_audit_evidence_payload_preserves_backed_events_without_fake_artifacts(self) -> None:
        class AuditStore(FakeStore):
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "AUD-1",
                            "entity_fqn": "main.customer.customer_dim",
                            "entity_type": "table",
                            "action": "metadata updated",
                            "status": "success",
                            "detail": "Owner changed",
                            "created_at": "2026-04-24 01:05:00",
                            "actor_email": "abarreto@shorecp.com",
                            "request_id": "REQ-1",
                            "before_json": "{\"owner\":\"old.owner@shorecp.com\"}",
                            "after_json": "{\"owner\":\"abarreto@shorecp.com\"}",
                        },
                        {
                            "audit_id": "AUD-2",
                            "entity_fqn": "main.risk.policy_exception",
                            "entity_type": "policy",
                            "action": "policy exception failed",
                            "status": "failed",
                            "detail": "Policy exception failed.",
                            "created_at": "2026-04-24 02:05:00",
                            "actor_email": "steward@shorecp.com",
                        },
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), audit_id="AUD-2", limit=25)

        self.assertEqual(payload["summary"]["totalChanges"], 2)
        self.assertEqual(payload["summary"]["policyChanges"], 1)
        self.assertEqual(payload["summary"]["failedActions"], 1)
        self.assertEqual(payload["summary"]["approvals"], 0)
        self.assertEqual(payload["summary"]["rowScope"], "governance audit log")
        self.assertEqual(payload["summary"]["hiddenRowsExcluded"], 0)
        self.assertEqual(payload["selectedEvent"]["audit_id"], "AUD-2")
        self.assertEqual(len(payload["events"]), 2)
        self.assertEqual(payload["evidence"]["approvalChain"], [])
        self.assertEqual(payload["evidence"]["artifacts"], [])
        self.assertIn("before", payload["evidence"])

        scoped = axiom_metrics.audit_evidence_payload(
            store=AuditStore(),
            audit_id="AUD-2",
            limit=25,
            visible_asset_fqns=["main.customer.customer_dim"],
        )

        self.assertEqual(scoped["summary"]["totalChanges"], 1)
        self.assertEqual(scoped["summary"]["rowScope"], "visible-assets")
        self.assertEqual(scoped["summary"]["hiddenRowsExcluded"], 1)
        self.assertIsNone(scoped["selectedEvent"])
        self.assertIn("after", payload["evidence"])

    def test_audit_evidence_payload_rejects_internal_seed_and_identity_rows(self) -> None:
        class AuditStore(FakeStore):
            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "INTERNAL-1",
                            "entity_type": "identity_directory_entry",
                            "entity_id": "abarreto@shorecp.com",
                            "action": "identity-directory-upserted",
                            "source": "store",
                            "status": "success",
                            "after_json": "{\"entryId\":\"abc\"}",
                            "created_at": "2026-04-24 01:00:00",
                            "actor_email": "abarreto@shorecp.com",
                        },
                        {
                            "audit_id": "GOV-HOME-EVIDENCE-audit-01",
                            "entity_fqn": "main.customer.customer_dim",
                            "entity_type": "asset",
                            "action": "policy-exception-detected",
                            "source": "home-evidence-plane",
                            "status": "failed",
                            "detail": "Review GOV-HOME-EVIDENCE-request-01",
                            "request_id": "GOV-HOME-EVIDENCE-request-01",
                            "before_json": "{\"request_id\":\"GOV-HOME-EVIDENCE-request-01\"}",
                            "after_json": "{\"audit_id\":\"GOV-HOME-EVIDENCE-audit-01\"}",
                            "created_at": "2026-04-24 01:05:00",
                            "actor_email": "abarreto@shorecp.com",
                        },
                    ]
                )

        payload = axiom_metrics.audit_evidence_payload(store=AuditStore(), limit=25)
        serialized = json.dumps(payload)

        self.assertEqual(payload["summary"]["totalChanges"], 0)
        self.assertEqual(payload["summary"]["hiddenRowsExcluded"], 2)
        self.assertEqual(payload["events"], [])
        self.assertIsNone(payload["selectedEvent"])
        self.assertNotIn("GOV-HOME-EVIDENCE", serialized)
        self.assertNotIn("identity-directory-upserted", serialized)
        self.assertIsNone(payload["evidence"])

    def test_admin_control_center_preserves_unbacked_admin_values_as_unavailable(self) -> None:
        payload = axiom_metrics.admin_control_center_payload(
            visible_assets=_assets_df(),
            store=FakeStore(),
            runtime={
                "state": "live",
                "catalogCount": 2,
                "client": {
                    "authMode": "oauth-m2m-env",
                    "clientSecretPresent": True,
                    "warehouseId": "wh-1",
                },
            },
            environment={"displayLabel": "Dev · emet.axiom"},
            actor_role="admin",
            ai_status={"state": "available", "provider": "genie", "spaceId": "space-1"},
        )

        self.assertEqual(payload["environment"]["displayLabel"], "Dev · emet.axiom")
        self.assertEqual(payload["role"]["label"], "Platform Admin")
        self.assertEqual(payload["policyRequirements"]["cards"][0]["key"], "totalPolicies")
        self.assertIsNone(payload["policyRequirements"]["cards"][0]["value"])
        self.assertEqual(payload["policyRequirements"]["cards"][0]["state"], "unavailable")
        self.assertFalse(payload["policyRequirements"]["capabilities"]["policyLibrary"])
        self.assertEqual(payload["bulkImport"]["state"], "unavailable")
        self.assertFalse(payload["bulkImport"]["reportAvailable"])
        self.assertEqual(payload["access"]["users"]["value"], 2)
        self.assertEqual(payload["access"]["roles"]["value"], 2)
        self.assertEqual(payload["access"]["groups"]["value"], 1)
        self.assertIsNone(payload["access"]["sso"]["value"])
        self.assertEqual(payload["access"]["sso"]["state"], "unavailable")
        self.assertEqual(payload["runtimeSummary"]["authMode"], "oauth-m2m-env")
        self.assertNotIn("clientSecretPresent", payload["system"])
        self.assertEqual(payload["integrations"][2]["key"], "aiCopilot")
        self.assertEqual(payload["integrations"][2]["state"], "connected")
        self.assertEqual(payload["integrations"][3]["key"], "notifications")
        self.assertEqual(payload["integrations"][3]["state"], "unavailable")
        self.assertIn("Notification delivery health", payload["integrations"][3]["reason"])

    def test_governance_request_detail_builds_diff_from_real_request(self) -> None:
        payload = axiom_metrics.governance_request_detail_payload(
            store=DetailStore(),
            request_id="REQ-1",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["requestId"], "REQ-1")
        self.assertEqual(payload["assetFqn"], "main.customer.customer_dim")
        fields = {row["field"] for row in payload["diff"]["rows"]}
        self.assertIn("domain", fields)
        self.assertIn("certification", fields)
        self.assertEqual(payload["comments"], [])
        self.assertEqual(payload["commentsState"], "unavailable")
        self.assertEqual(payload["evidence"], [])
        self.assertEqual(payload["evidenceState"], "unavailable")

    def test_governance_request_detail_carries_audit_trail_and_comment_audit_ids(self) -> None:
        # Contract (cohesion follow-up 1): the request detail joins to the
        # audit events whose request_id matches this request and exposes
        # auditTrail plus per-comment displayAuditId/auditEventId so the
        # mini-hub can render AUD evidence chips that deep-link to Evidence.
        class AuditTrailStore(FakeStore):
            def get_change_request(self, request_id: str) -> ChangeRequest | None:
                if request_id != "596357596fa8474c865d9cf02488a167":
                    return None
                return ChangeRequest(
                    request_id="596357596fa8474c865d9cf02488a167",
                    created_at="2026-05-05 02:51:38",
                    created_by="abarreto@shorecp.com",
                    status="pending",
                    uc_full_name="main.emet.run_history",
                    new_comment="description: Run history quality triage",
                    new_uc_tags={"domain": "Ops"},
                    reviewed_at="2026-07-22 00:05:24",
                    reviewed_by="abarreto@shorecp.com",
                    review_note="Reassigned for triage",
                )

            def list_metadata_audit_for_requests(
                self, request_ids, *, limit: int = 500
            ) -> pd.DataFrame:
                assert list(request_ids) == ["596357596fa8474c865d9cf02488a167"]
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "fe36d39ce0a24b05a347f2d4864636e8",
                            "request_id": "596357596fa8474c865d9cf02488a167",
                            "action": "task-created",
                            "detail": "",
                            "created_at": "2026-05-05 02:51:41",
                            "actor_email": "abarreto@shorecp.com",
                        },
                        {
                            "audit_id": "b1169eb8cf4e4735a3f666518bb58de7",
                            "request_id": "596357596fa8474c865d9cf02488a167",
                            "action": "task-comment-added",
                            "detail": "Reassigned for triage",
                            "created_at": "2026-07-22 00:05:24",
                            "actor_email": "abarreto@shorecp.com",
                        },
                    ]
                )

        payload = axiom_metrics.governance_request_detail_payload(
            store=AuditTrailStore(),
            request_id="596357596fa8474c865d9cf02488a167",
        )

        self.assertIsNotNone(payload)
        trail = payload["auditTrail"]
        self.assertEqual(
            [entry["auditEventId"] for entry in trail],
            ["fe36d39ce0a24b05a347f2d4864636e8", "b1169eb8cf4e4735a3f666518bb58de7"],
        )
        self.assertEqual(
            [entry["displayAuditId"] for entry in trail],
            ["AUD-FE36D39C", "AUD-B1169EB8"],
        )
        self.assertEqual(trail[0]["action"], "task-created")
        self.assertTrue(trail[0]["createdAt"].endswith("Z"))
        # Derivation matches the Evidence page exactly.
        for entry in trail:
            self.assertEqual(
                entry["displayAuditId"],
                axiom_metrics.audit_display_id(entry["auditEventId"]),
            )
        # The audit-backed comments carry the same chip fields; the review
        # note maps (by exact detail content) to its audit row.
        by_kind = {}
        for comment in payload["comments"]:
            by_kind.setdefault(comment["kind"], []).append(comment)
        self.assertEqual(
            by_kind["review-note"][0]["auditEventId"],
            "b1169eb8cf4e4735a3f666518bb58de7",
        )
        self.assertEqual(by_kind["review-note"][0]["displayAuditId"], "AUD-B1169EB8")
        audit_comment_ids = {comment["auditEventId"] for comment in by_kind["audit"]}
        self.assertIn("b1169eb8cf4e4735a3f666518bb58de7", audit_comment_ids)
        for comment in by_kind["audit"]:
            self.assertTrue(comment["displayAuditId"].startswith("AUD-"))

    def test_governance_request_detail_audit_trail_empty_without_audit_history(self) -> None:
        # No audit rows for the request → empty trail and empty chip fields
        # on the review-note comment; nothing fabricated.
        class NoAuditStore(DetailStore):
            def list_metadata_audit_for_requests(
                self, request_ids, *, limit: int = 500
            ) -> pd.DataFrame:
                return pd.DataFrame()

        payload = axiom_metrics.governance_request_detail_payload(
            store=NoAuditStore(),
            request_id="REQ-1",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["auditTrail"], [])
        self.assertEqual(payload["comments"], [])

    def test_governance_workbench_selected_request_includes_audit_trail(self) -> None:
        payload = axiom_metrics.governance_workbench_payload(store=FakeStore())

        self.assertIsNotNone(payload["selectedRequest"])
        self.assertIn("auditTrail", payload["selectedRequest"])
        self.assertIsInstance(payload["selectedRequest"]["auditTrail"], list)

    def test_governance_workbench_exposes_open_requests_only(self) -> None:
        class MixedStatusStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "REQ-CLOSED",
                            "created_at": "2026-04-24 03:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "approved",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Resolve policy exception: already approved",
                        },
                        {
                            "request_id": "REQ-OPEN",
                            "created_at": "2026-04-24 02:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Assign owner: needs review",
                        },
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

        payload = axiom_metrics.governance_workbench_payload(store=MixedStatusStore())

        self.assertEqual([row["requestId"] for row in payload["requests"]], ["REQ-OPEN"])
        self.assertEqual(payload["selectedRequest"]["requestId"], "REQ-OPEN")
        self.assertEqual(payload["requests"][0]["type"], "")
        pending_kpi = next(item for item in payload["metrics"] if item["key"] == "pendingApprovals")
        policy_kpi = next(item for item in payload["metrics"] if item["key"] == "policyExceptions")
        self.assertEqual(pending_kpi["value"], 1)
        self.assertEqual(policy_kpi["value"], 0)

    def test_governance_workbench_reports_out_of_scope_open_requests(self) -> None:
        # S3: the workbench shows ALL open requests; when given the visible
        # estate it must also say how many target assets sit outside it so the
        # 40-vs-21 split reads as scoping, not contradiction.
        class TwoAssetStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "REQ-VISIBLE",
                            "created_at": "2026-04-24 01:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Assign owner: needs review",
                        },
                        {
                            "request_id": "REQ-HIDDEN-TARGET",
                            "created_at": "2026-04-24 02:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "emet.ops.run_history",
                            "new_comment": "Cleanup: dedupe tasks",
                        },
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

        payload = axiom_metrics.governance_workbench_payload(
            store=TwoAssetStore(),
            visible_asset_fqns=["main.customer.customer_dim"],
        )

        scope = payload["openRequestScope"]
        self.assertEqual(scope["totalOpen"], 2)
        self.assertEqual(scope["visibleOpenCount"], 1)
        self.assertEqual(scope["outOfScopeOpenCount"], 1)
        self.assertEqual(scope["outOfScopeAssetCount"], 1)
        self.assertIn("outside the visible estate", scope["caption"])
        # All open requests still ship — the scope block captions, it never
        # hides the out-of-estate queue from the workbench.
        self.assertEqual(len(payload["requests"]), 2)

    def test_governance_workbench_omits_scope_split_without_visibility(self) -> None:
        payload = axiom_metrics.governance_workbench_payload(store=FakeStore())
        scope = payload["openRequestScope"]
        self.assertEqual(scope["scope"], "all-requests")
        # No fabricated 0s when the visible estate is unknown.
        self.assertNotIn("outOfScopeOpenCount", scope)

    def test_governance_workbench_rejects_seed_and_prototype_request_rows(self) -> None:
        class SeededRequestStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "ax-home-seed-request-1",
                            "created_at": "2026-04-24 01:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "source": "home-evidence-plane",
                            "new_comment": "Validation sample owner check",
                        },
                        {
                            "request_id": "REQ-LIVE",
                            "created_at": "2026-04-24 02:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "source": "governance-store",
                            "new_comment": "Assign owner: needs review",
                        },
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

        payload = axiom_metrics.governance_workbench_payload(store=SeededRequestStore())
        serialized = json.dumps(payload)

        self.assertEqual([row["requestId"] for row in payload["requests"]], ["REQ-LIVE"])
        self.assertEqual(payload["meta"]["nonAuthoritativeRowsExcluded"], 1)
        self.assertNotIn("ax-home-seed", serialized)
        self.assertNotIn("home-evidence-plane", serialized)

    def test_governance_request_detail_rejects_customer_safe_seed_request(self) -> None:
        class SeededDetailStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "GOV-HOME-EVIDENCE-request-01",
                            "created_at": "2026-04-24 01:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "pending",
                            "uc_full_name": "main.customer.customer_dim",
                            "new_comment": "Assign owner: needs review",
                        }
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

            def get_change_request(self, request_id: str) -> ChangeRequest | None:
                if request_id != "GOV-HOME-EVIDENCE-request-01":
                    return None
                return ChangeRequest(
                    request_id="GOV-HOME-EVIDENCE-request-01",
                    created_at="2026-04-24 01:00:00",
                    created_by="abarreto@shorecp.com",
                    status="pending",
                    uc_full_name="main.customer.customer_dim",
                    new_comment="Assign owner: needs review",
                    new_uc_tags={"domain": "Customer"},
                )

        payload = axiom_metrics.governance_request_detail_payload(
            store=SeededDetailStore(),
            request_id="GOV-01",
        )
        serialized = json.dumps(payload)

        self.assertIsNone(payload)
        self.assertEqual(serialized, "null")

    def test_cde_payload_uses_visible_metadata_and_marks_controls_unavailable(self) -> None:
        payload = axiom_metrics.cde_dashboard_payload(visible_assets=_assets_df())

        self.assertEqual(payload["summary"]["totalCdes"], 1)
        # Honest rename: a sensitivity label is not a protection control, so
        # the count ships as sensitivityLabeledCdes (customer_dim carries
        # sensitivity=Confidential in this fixture). `protectedCdes` must be
        # gone — the payload may never claim protection from a label.
        self.assertEqual(payload["summary"]["sensitivityLabeledCdes"], 1)
        self.assertNotIn("protectedCdes", payload["summary"])
        self.assertEqual(payload["summary"]["sensitiveCandidates"], 1)
        # Groups are domain summaries referencing item ids — they no longer
        # double-list full item payloads (clients read rows from `items` only).
        self.assertEqual(payload["groups"][0]["domain"], "Customer")
        self.assertEqual(payload["groups"][0]["count"], 1)
        self.assertNotIn("items", payload["groups"][0])
        self.assertEqual(payload["groups"][0]["itemIds"], [payload["items"][0]["id"]])
        self.assertIsNone(payload["items"][0]["controlCoverage"])
        self.assertEqual(payload["items"][0]["controlState"], "unavailable")
        # Status now reflects the asset's real certification instead of
        # conflating missing control evidence with overall health.
        self.assertEqual(payload["items"][0]["status"], "Certified")
        self.assertIsNone(payload["items"][0]["linkedPolicies"])
        self.assertEqual(payload["items"][0]["linkedPolicyState"], "unavailable")

    def test_cde_detail_preserves_unavailable_control_and_lineage_contract(self) -> None:
        payload = axiom_metrics.cde_detail_payload(
            visible_assets=_assets_df(),
            cde_id="main.customer.customer_dim",
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["assetFqn"], "main.customer.customer_dim")
        self.assertEqual(payload["lineageSnapshot"]["state"], "unavailable")
        self.assertGreaterEqual(len(payload["controls"]), 5)
        self.assertTrue(all(control["state"] == "unavailable" for control in payload["controls"]))
        self.assertTrue(all(control["coverage"] is None for control in payload["controls"]))
        self.assertEqual(payload["linkedAssets"][0]["assetFqn"], "main.customer.customer_dim")
        self.assertEqual(payload["activity"], [])

    def test_taxonomy_overview_prefers_enriched_glossary_terms(self) -> None:
        enriched = [
            {
                "termId": "customer-id",
                "term": "Customer Identifier",
                "definition": "Business-approved identifier.",
                "ownerEmail": "customer.owner@shorecp.com",
                "reviewers": ["customer.steward@shorecp.com"],
                "assetCount": 1,
            }
        ]

        payload = axiom_metrics.taxonomy_overview_payload(
            store=FakeStore(),
            glossary_terms=enriched,
        )

        self.assertEqual(payload["summary"]["termCount"], 1)
        self.assertEqual(payload["glossaryTerms"][0]["termId"], "customer-id")
        self.assertEqual(payload["glossaryTerms"][0]["assetCount"], 1)
        self.assertEqual(payload["classifications"][0]["classification_id"], "class-1")

    def test_taxonomy_overview_preserves_real_ax_taxonomy_term_ids(self) -> None:
        # Persona-audit fix: real persisted glossary ids ("ax-taxonomy-term-*")
        # were being blanked by the generic non-authoritative-marker scrub, so
        # 19/20 terms shipped termId "" and the hierarchy panel had no joinable
        # parent/child structure. Identifiers must survive; prose is still
        # sanitized.
        enriched = [
            {
                "termId": "ax-taxonomy-term-net-revenue",
                "parentTermId": "ax-taxonomy-term-revenue",
                "term": "Net Revenue",
                "definition": "Recognized revenue net of adjustments.",
                "assetCount": 2,
            },
            {
                "termId": "ax-taxonomy-term-revenue",
                "parentTermId": "",
                "term": "Revenue",
                "definition": "Prototype mock definition should be scrubbed.",
                "assetCount": 0,
            },
        ]

        payload = axiom_metrics.taxonomy_overview_payload(
            store=FakeStore(),
            glossary_terms=enriched,
        )

        terms = {row["termId"]: row for row in payload["glossaryTerms"]}
        self.assertIn("ax-taxonomy-term-net-revenue", terms)
        self.assertEqual(
            terms["ax-taxonomy-term-net-revenue"]["parentTermId"],
            "ax-taxonomy-term-revenue",
        )
        # Prose containing genuine non-authoritative markers is still scrubbed.
        self.assertEqual(terms["ax-taxonomy-term-revenue"]["definition"], "")

    def test_insights_formula_weights_sum_to_one(self) -> None:
        payload = axiom_metrics.insights_dashboard_payload(
            visible_assets=_assets_df(),
            store=FakeStore(),
        )

        weights = [item["weight"] for item in payload["scoring"]["maturityFormula"]]
        self.assertAlmostEqual(sum(weights), 1.0)
        self.assertIn("metadataCoverage", payload["scoring"]["availableSignals"])
        self.assertNotIn("policyCompliance", payload["scoring"]["availableSignals"])
        self.assertNotIn("auditReadiness", payload["scoring"]["availableSignals"])
        policy_kpi = next(item for item in payload["kpis"] if item["key"] == "policyCompliance")
        self.assertIsNone(policy_kpi["value"])
        self.assertEqual(policy_kpi["state"], "unavailable")
        exception_kpi = next(item for item in payload["kpis"] if item["key"] == "criticalExceptions")
        self.assertEqual(exception_kpi["value"], 1)
        self.assertEqual(exception_kpi["state"], "degraded")
        self.assertFalse(payload["signalAvailability"]["quality"])
        self.assertFalse(payload["signalAvailability"]["auditReadiness"])
        self.assertFalse(payload["signalAvailability"]["policyCompliance"])
        self.assertGreaterEqual(len(payload["metadataCoverageHeatmap"]), 1)
        self.assertGreaterEqual(len(payload["certificationCoverageByTier"]), 1)
        self.assertGreaterEqual(len(payload["riskHeatmap"]), 1)
        self.assertTrue(
            any(row["label"] == "Tier 1 - Business Critical" for row in payload["certificationCoverageByTier"])
        )
        # Every risk cell and tier row carries the exact criticality-facet
        # values that reproduce it, so the UI can link the number to the assets
        # behind it (Discovery's criticality facet matches over criticality/tier).
        for cell in payload["riskHeatmap"]:
            self.assertIn("filterValues", cell)
            self.assertTrue(all(isinstance(value, str) and value for value in cell["filterValues"]))
        for row in payload["certificationCoverageByTier"]:
            self.assertIn("filterValues", row)
            self.assertTrue(all(isinstance(value, str) and value for value in row["filterValues"]))
        tier1 = next(
            row for row in payload["certificationCoverageByTier"] if row["label"] == "Tier 1 - Business Critical"
        )
        self.assertTrue(tier1["filterValues"], "Tier 1 row must expose facet values to drill into")

    def test_insights_quality_availability_tracks_score_not_raw_rows(self) -> None:
        # Intended behavior changed: insights_dashboard_payload now derives
        # quality_health from the SAME _quality_sla_signal pass-rate the
        # Command Center publishes (it was previously hardcoded None, which
        # made Insights claim "Quality health score is unavailable" while the
        # Command Center showed a real SLA). Evaluated rows => available score.
        class QualityRowsOnlyStore(FakeStore):
            def list_quality_run_results(self, limit: int = 1000) -> pd.DataFrame:
                return pd.DataFrame([{"asset_fqn": "main.customer.customer_dim", "outcome": "passed"}])

        payload = axiom_metrics.insights_dashboard_payload(
            visible_assets=_assets_df(),
            store=QualityRowsOnlyStore(),
        )

        self.assertTrue(payload["signalAvailability"]["quality"])
        self.assertTrue(payload["signalAvailability"]["qualityRowsAvailable"])
        self.assertIn("qualityHealth", payload["scoring"]["availableSignals"])

    def test_insights_quality_unavailable_when_rows_have_no_evaluated_outcomes(self) -> None:
        # The spirit of the original test still holds: raw row presence alone
        # is not availability. Rows without evaluated outcomes (e.g. skipped)
        # produce no pass rate, so the signal stays honestly unavailable.
        class SkippedOnlyStore(FakeStore):
            def list_quality_run_results(self, limit: int = 1000) -> pd.DataFrame:
                return pd.DataFrame([{"asset_fqn": "main.customer.customer_dim", "outcome": "skipped"}])

        payload = axiom_metrics.insights_dashboard_payload(
            visible_assets=_assets_df(),
            store=SkippedOnlyStore(),
        )

        self.assertFalse(payload["signalAvailability"]["quality"])
        self.assertTrue(payload["signalAvailability"]["qualityRowsAvailable"])
        self.assertNotIn("qualityHealth", payload["scoring"]["availableSignals"])

    def test_policy_exceptions_ignore_resolved_requests_and_asset_fqn_substrings(self) -> None:
        # Regression: Insights said "Critical Policy Exceptions 2" while the
        # Command Center said 0. The two counted rows were RESOLVED change
        # requests whose target FQNs merely contain "exception"
        # (risk_policy_exception_register / finance_exception_review). Closed
        # requests are not open exposures, and an asset's NAME is not an
        # exception signal.
        class ResolvedExceptionFqnStore(FakeStore):
            def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
                rows = pd.DataFrame(
                    [
                        {
                            "request_id": "REQ-A",
                            "created_at": "2026-04-24 01:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "approved",
                            "uc_full_name": "main.risk.risk_policy_exception_register",
                            "new_comment": "Certify table",
                        },
                        {
                            "request_id": "REQ-B",
                            "created_at": "2026-04-24 02:00:00",
                            "created_by": "abarreto@shorecp.com",
                            "status": "rejected",
                            "uc_full_name": "main.finance.finance_exception_review",
                            "new_comment": "Grant policy exception for quarterly load",
                        },
                    ]
                )
                if status:
                    return rows[rows["status"].eq(status)].copy()
                return rows

            def list_metadata_audit(self, **_: object) -> pd.DataFrame:
                return pd.DataFrame(
                    [
                        {
                            "audit_id": "AUD-X",
                            "entity_fqn": "main.risk.risk_policy_exception_register",
                            "action": "change-request-status-updated",
                            "status": "success",
                            "detail": "Approved",
                            "created_at": "2026-04-24 03:00:00",
                            "actor_email": "abarreto@shorecp.com",
                        }
                    ]
                )

        insights = axiom_metrics.insights_dashboard_payload(
            visible_assets=_assets_df(),
            store=ResolvedExceptionFqnStore(),
        )
        exception_kpi = next(item for item in insights["kpis"] if item["key"] == "criticalExceptions")
        self.assertEqual(exception_kpi["value"], 0)
        self.assertEqual(exception_kpi["state"], "available")

        # Same-store parity with the Command Center signal: both must say 0.
        command = axiom_metrics.command_center_payload(
            visible_assets=_assets_df(),
            store=ResolvedExceptionFqnStore(),
        )
        self.assertEqual(command["governance"]["policyExceptions"], 0)

    def test_policy_exceptions_still_count_open_requests_by_their_own_text(self) -> None:
        # An OPEN request that itself asks for a policy exception remains a
        # live exposure and must keep counting.
        count = axiom_metrics._policy_exception_count(
            [
                {
                    "request_id": "REQ-OPEN",
                    "status": "pending",
                    "new_comment": "Policy exception requested for PII export",
                }
            ],
            [],
        )
        self.assertEqual(count, 1)

    def test_ai_recommendations_route_certification_questions_to_certification_evidence(self) -> None:
        assets = _assets_df().copy()
        assets.loc[1, "criticality"] = "Critical"

        payload = axiom_metrics.build_ai_recommendations(
            visible_assets=assets,
            store=FakeStore(),
            question="Which critical assets are not certified?",
        )

        self.assertEqual(payload["intent"], "certification")
        self.assertEqual(payload["evidence"][0]["metric"], "criticalCertification")
        self.assertIn("main.finance.revenue", payload["answer"])

    def test_ai_recommendations_route_recent_change_questions_to_audit_evidence(self) -> None:
        payload = axiom_metrics.build_ai_recommendations(
            visible_assets=_assets_df(),
            store=FakeStore(),
            question="What changed in governance metadata recently?",
        )

        self.assertEqual(payload["intent"], "changes")
        self.assertEqual(payload["evidence"][0]["type"], "audit")
        self.assertIn("Metadata updated", payload["answer"])

    def test_ai_recommendations_priority_combines_multiple_evidence_backed_signals(self) -> None:
        assets = _assets_df().copy()
        assets.loc[1, "criticality"] = "Critical"

        payload = axiom_metrics.build_ai_recommendations(
            visible_assets=assets,
            store=FakeStore(),
            question="Recommend the next governed assets and governance priorities for Discovery.",
        )

        self.assertEqual(payload["intent"], "priority")
        self.assertGreaterEqual(len(payload["recommendations"]), 3)
        metrics = {evidence["metric"] for evidence in payload["evidence"]}
        self.assertIn("metadataCoverage", metrics)
        self.assertIn("criticalCertification", metrics)
        self.assertIn("assetsWithoutOwner", metrics)

    def test_ai_recommendations_reject_unsupported_freeform_questions(self) -> None:
        payload = axiom_metrics.build_ai_recommendations(
            visible_assets=_assets_df(),
            store=FakeStore(),
            question="Draft a launch announcement",
        )

        self.assertEqual(payload["intent"], "unsupported")
        self.assertEqual(payload["confidence"], "low")
        self.assertEqual(payload["evidence"], [])
        self.assertIn("currently supports", payload["answer"])


if __name__ == "__main__":
    unittest.main()
