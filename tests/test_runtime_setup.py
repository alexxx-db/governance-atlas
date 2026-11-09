from __future__ import annotations

import unittest

from axiom.services import runtime_setup


class RuntimeSetupPayloadTests(unittest.TestCase):
    def test_live_runtime_payload_surfaces_read_only_setup_truth(self) -> None:
        payload = runtime_setup.setup_payload(
            runtime_status={
                "state": "live",
                "message": "",
                "client": {
                    "authMode": "oauth-m2m-env",
                    "authType": "oauth-m2m",
                    "hostPresent": True,
                },
            },
            store_status={"state": "live", "message": ""},
            capabilities={
                "systemInventoryRead": {
                    "state": "available",
                    "available": True,
                    "reason": "",
                },
                "tableLineage": {"state": "available", "available": True, "reason": ""},
                "workloadVisibility": {
                    "state": "unknown",
                    "available": False,
                    "reason": "Operational query and workload visibility is preview/admin-governed.",
                },
                "exportAllowed": {
                    "state": "unavailable",
                    "available": False,
                    "reason": "Authenticated export endpoints are not implemented in the live runtime yet.",
                },
            },
            warehouse_id="wh-123",
            gov_catalog="main",
            gov_schema="gov",
            authenticated=True,
            actor_role="admin",
            diagnostics_enabled=True,
        )

        self.assertIn("observedAt", payload)
        self.assertIn("staleAfter", payload)
        self.assertEqual(payload["auth"]["mode"], "app-principal-only")
        self.assertEqual(payload["auth"]["visibilityScope"], "workspace-app-principal")
        self.assertFalse(payload["auth"]["perUserAuthorization"]["implemented"])
        self.assertEqual(payload["summary"]["availableCount"], 7)
        self.assertEqual(payload["summary"]["degradedCount"], 1)
        self.assertEqual(payload["summary"]["unavailableCount"], 4)
        self.assertEqual(payload["summary"]["unknownCount"], 1)
        self.assertEqual(payload["readiness"]["state"], "attention_required")
        self.assertTrue(payload["readiness"]["canRerun"])
        # OBO-deferred checks (per_user_authorization, table_lineage, column_lineage,
        # workload_visibility, export_delivery, identity_forwarding) no longer drive the
        # top-line readiness nextStep; the first real operational attention key does.
        self.assertEqual(payload["readiness"]["nextStep"], "background_work_plane")
        self.assertEqual(payload["readiness"]["blockedBy"], [])
        self.assertIn("workload_visibility", payload["readiness"]["attentionBy"])
        claim_surfaces = {
            item["surface"] for item in payload["readiness"]["claimNarrowing"]
        }
        self.assertIn("Queries, usage, and workloads", claim_surfaces)
        self.assertIn("Actor-scoped protected reads", claim_surfaces)
        self.assertIn("Workspace-scoped metadata reads", claim_surfaces)
        self.assertIn("Discovery and detail export", claim_surfaces)

        workspace_access = payload["workspaceAccess"]
        self.assertEqual(workspace_access["mode"], "app-principal-only")
        self.assertEqual(workspace_access["visibilityScope"], "workspace-app-principal")
        self.assertTrue(workspace_access["canUseDiscovery"])
        self.assertTrue(workspace_access["canUseEntityMetadata"])
        self.assertTrue(workspace_access["canWriteGovernance"])
        self.assertFalse(workspace_access["canUseAssetPreview"])
        # Lineage is now available in app-principal mode when the table_lineage capability
        # is wired; only the visibility scope stays workspace-app-principal.
        self.assertTrue(workspace_access["canUseLineage"])
        self.assertFalse(workspace_access["canUseQueryHistory"])
        self.assertEqual(
            workspace_access["queryHistorySharingPath"]["state"], "unavailable"
        )
        self.assertEqual(
            workspace_access["queryHistorySharingPath"]["acceptedPaths"],
            [
                "actor-scoped OBO",
                "validated dynamic-view plane",
                "warehouse CAN VIEW plus downstream visibility rules",
            ],
        )
        self.assertFalse(workspace_access["canExport"])
        self.assertFalse(workspace_access["canRunBackgroundWork"])
        self.assertFalse(workspace_access["canUseClassificationRecommendations"])
        self.assertEqual(workspace_access["transactionMode"]["state"], "degraded")
        self.assertNotIn(
            "Discovery and entity inventory", workspace_access["blockedSurfaces"]
        )
        self.assertIn(
            "Asset preview and sample data", workspace_access["blockedSurfaces"]
        )
        self.assertNotIn(
            "Lineage graph and drawer", workspace_access["blockedSurfaces"]
        )
        self.assertIn(
            "Queries, usage, and workloads", workspace_access["blockedSurfaces"]
        )
        self.assertIn(
            "Discovery and detail export", workspace_access["blockedSurfaces"]
        )
        self.assertIn("Background work runner", workspace_access["blockedSurfaces"])
        self.assertIn(
            "Classification recommendations", workspace_access["blockedSurfaces"]
        )
        self.assertEqual(
            [item["key"] for item in workspace_access["gates"]],
            [
                "discovery_inventory",
                "governance_writes",
                "asset_preview",
                "table_lineage",
                "workload_visibility",
                "export_delivery",
                "background_work_plane",
                "classification_recommendations",
                "transaction_mode",
            ],
        )
        self.assertEqual(workspace_access["gates"][0]["state"], "available")
        self.assertEqual(workspace_access["gates"][2]["state"], "unavailable")
        self.assertEqual(workspace_access["gates"][3]["state"], "available")
        self.assertEqual(workspace_access["gates"][4]["state"], "unavailable")
        self.assertEqual(workspace_access["gates"][5]["state"], "unavailable")
        self.assertEqual(
            workspace_access["gates"][4]["blockedSurfaces"],
            ["Queries, usage, and workloads"],
        )
        self.assertIn("remediation", workspace_access["gates"][5])
        surface_policies = {
            item["key"]: item for item in workspace_access["surfacePolicies"]
        }
        self.assertTrue(surface_policies["discovery"]["allowed"])
        self.assertFalse(surface_policies["asset_preview"]["allowed"])
        self.assertTrue(surface_policies["lineage"]["allowed"])

        checks = {item["key"]: item for item in payload["checks"]}
        self.assertEqual(checks["warehouse_runtime"]["state"], "available")
        self.assertEqual(checks["governance_store"]["state"], "available")
        self.assertEqual(checks["identity_forwarding"]["state"], "available")
        self.assertEqual(checks["app_service_principal"]["state"], "available")
        self.assertEqual(checks["per_user_authorization"]["state"], "unavailable")
        self.assertEqual(checks["system_inventory"]["state"], "available")
        self.assertEqual(checks["table_lineage"]["state"], "available")
        self.assertEqual(checks["workload_visibility"]["state"], "unknown")
        self.assertEqual(
            checks["workload_visibility"]["safeSharingPath"]["state"], "unavailable"
        )
        self.assertEqual(
            checks["workload_visibility"]["safeSharingPath"]["acceptedPaths"],
            [
                "actor-scoped OBO",
                "validated dynamic-view plane",
                "warehouse CAN VIEW plus downstream visibility rules",
            ],
        )
        self.assertEqual(checks["export_delivery"]["state"], "unavailable")
        self.assertEqual(checks["background_work_plane"]["state"], "unavailable")
        self.assertEqual(checks["transaction_mode"]["state"], "degraded")
        self.assertEqual(
            checks["classification_recommendations"]["state"], "unavailable"
        )
        self.assertEqual(
            checks["app_service_principal"]["label"],
            "App service-principal reachability and permissions",
        )
        self.assertEqual(
            checks["background_work_plane"]["label"], "Background work runner"
        )
        self.assertEqual(
            checks["export_delivery"]["label"], "Export delivery prerequisites"
        )
        self.assertEqual(checks["transaction_mode"]["label"], "Transaction eligibility")
        self.assertEqual(
            checks["classification_recommendations"]["label"],
            "Classification recommendation source eligibility",
        )
        self.assertIn("remediation", checks["classification_recommendations"])
        self.assertIn("evidence", checks["warehouse_runtime"])

        sequence = payload["setupSequence"]
        self.assertEqual(
            [item["key"] for item in sequence],
            [
                "environment_config",
                "runtime_probe",
                "store_probe",
                "app_service_principal_probe",
                "identity_probe",
                "capability_inventory",
                "rollout_controls",
            ],
        )
        self.assertTrue(all(item["rerunnable"] for item in sequence))
        self.assertIn("runtime_probe", sequence[0]["unlocks"])
        self.assertIn("workspace_setup_diagnostics", sequence[-1]["unlocks"])

        flags = {item["key"]: item for item in payload["featureFlags"]}
        self.assertGreaterEqual(len(flags), 6)
        self.assertEqual(flags["workspace_setup_diagnostics"]["state"], "available")
        self.assertTrue(flags["workspace_setup_diagnostics"]["enabled"])
        self.assertIn("summary", flags["workspace_setup_diagnostics"])
        self.assertIn("reason", flags["workspace_setup_diagnostics"])
        self.assertEqual(
            flags["workspace_setup_diagnostics"]["scope"],
            "shell diagnostics + bootstrap-unavailable fallback",
        )
        self.assertIn("rolloutPolicy", flags["workspace_setup_diagnostics"])
        self.assertIn("rationale", flags["workspace_setup_diagnostics"])
        self.assertEqual(
            flags["per_user_authorization"]["disabledReason"],
            "Actor-scoped protected reads stay disabled until Databricks user authorization / OBO is real.",
        )
        self.assertIn("unavailableReason", flags["per_user_authorization"])
        self.assertIn("disabledReason", flags["query_history_surface"])
        self.assertEqual(flags["query_history_surface"]["state"], "unknown")
        self.assertIn("summary", flags["query_history_surface"])
        self.assertIn("reason", flags["query_history_surface"])
        self.assertEqual(
            flags["query_history_surface"]["safeSharingPath"]["state"], "unavailable"
        )
        self.assertEqual(flags["background_work_plane"]["state"], "unavailable")
        self.assertIn("unavailableReason", flags["background_work_plane"])
        self.assertEqual(flags["transaction_fallback_mode"]["state"], "degraded")
        self.assertEqual(flags["transaction_fallback_mode"]["enabled"], True)
        self.assertIn("summary", flags["transaction_fallback_mode"])
        self.assertIn("removalTicket", flags["workspace_setup_diagnostics"])

    def test_missing_identity_and_config_surface_degraded_and_unavailable_checks(
        self,
    ) -> None:
        payload = runtime_setup.setup_payload(
            runtime_status={"state": "unavailable", "message": "Warehouse is down."},
            store_status={"state": "skipped", "message": "Store probe skipped."},
            capabilities={},
            warehouse_id="",
            gov_catalog="",
            gov_schema="",
            authenticated=False,
            actor_role="reader",
            diagnostics_enabled=False,
        )

        checks = {item["key"]: item for item in payload["checks"]}
        self.assertEqual(checks["warehouse_runtime"]["state"], "unavailable")
        self.assertEqual(checks["governance_store"]["state"], "unknown")
        self.assertEqual(checks["governance_config"]["state"], "unavailable")
        self.assertEqual(checks["identity_forwarding"]["state"], "degraded")
        self.assertEqual(checks["app_service_principal"]["state"], "unavailable")
        self.assertEqual(payload["auth"]["mode"], "no-identity")
        self.assertEqual(payload["auth"]["visibilityScope"], "anonymous-app-principal")
        self.assertEqual(payload["readiness"]["state"], "blocked")
        self.assertEqual(payload["readiness"]["nextStep"], "governance_config")
        self.assertIn("governance_config", payload["readiness"]["blockedBy"])
        self.assertIn("warehouse_runtime", payload["readiness"]["blockedBy"])
        self.assertIn("app_service_principal", payload["readiness"]["blockedBy"])
        self.assertIn("workload_visibility", payload["readiness"]["attentionBy"])
        claim_surfaces = {
            item["surface"] for item in payload["readiness"]["claimNarrowing"]
        }
        self.assertIn(
            "App service-principal reachability and permissions", claim_surfaces
        )
        self.assertIn("Workspace-scoped metadata reads", claim_surfaces)

        workspace_access = payload["workspaceAccess"]
        self.assertEqual(workspace_access["mode"], "no-identity")
        self.assertEqual(workspace_access["visibilityScope"], "anonymous-app-principal")
        self.assertFalse(workspace_access["canUseDiscovery"])
        self.assertFalse(workspace_access["canUseEntityMetadata"])
        self.assertFalse(workspace_access["canWriteGovernance"])
        self.assertFalse(workspace_access["canUseAssetPreview"])
        self.assertFalse(workspace_access["canUseLineage"])
        self.assertFalse(workspace_access["canUseQueryHistory"])
        self.assertEqual(
            workspace_access["queryHistorySharingPath"]["state"], "unavailable"
        )
        self.assertFalse(workspace_access["canExport"])
        self.assertFalse(workspace_access["canRunBackgroundWork"])
        self.assertFalse(workspace_access["canUseClassificationRecommendations"])
        self.assertEqual(workspace_access["transactionMode"]["state"], "degraded")
        self.assertIn("Governance writes", workspace_access["blockedSurfaces"])
        self.assertIn(
            "Asset preview and sample data", workspace_access["blockedSurfaces"]
        )
        self.assertIn("Lineage graph and drawer", workspace_access["blockedSurfaces"])
        self.assertIn(
            "Queries, usage, and workloads", workspace_access["blockedSurfaces"]
        )
        self.assertIn(
            "Discovery and detail export", workspace_access["blockedSurfaces"]
        )
        self.assertIn("Background work runner", workspace_access["blockedSurfaces"])
        self.assertIn(
            "Classification recommendations", workspace_access["blockedSurfaces"]
        )
        self.assertEqual(workspace_access["gates"][0]["key"], "discovery_inventory")
        self.assertFalse(payload["featureFlags"][0]["enabled"])
        self.assertEqual(
            payload["featureFlags"][0]["key"], "workspace_setup_diagnostics"
        )
        self.assertEqual(payload["featureFlags"][0]["state"], "unavailable")
        self.assertIn("disabledReason", payload["featureFlags"][0])
        self.assertIn("unavailableReason", payload["featureFlags"][0])


    def test_per_user_authorization_flag_flips_auth_mode_to_obo_available(self) -> None:
        payload = runtime_setup.setup_payload(
            runtime_status={"state": "live", "message": ""},
            store_status={"state": "live", "message": ""},
            capabilities={
                "systemInventoryRead": {
                    "state": "available",
                    "available": True,
                    "reason": "",
                },
            },
            warehouse_id="wh-123",
            gov_catalog="main",
            gov_schema="gov",
            authenticated=True,
            actor_role="reader",
            diagnostics_enabled=True,
            per_user_authorization=True,
        )
        self.assertEqual(payload["auth"]["mode"], "obo-available")
        self.assertEqual(payload["workspaceAccess"]["mode"], "obo-available")
        self.assertTrue(payload["auth"]["perUserAuthorization"]["implemented"])
        self.assertEqual(payload["auth"]["perUserAuthorization"]["state"], "available")


if __name__ == "__main__":
    unittest.main()
