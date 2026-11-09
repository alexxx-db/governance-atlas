from __future__ import annotations

import ast
import unittest
from pathlib import Path

from axiom.services import capabilities as capability_service


class ExportCapabilityTests(unittest.TestCase):
    """G2 — export is available exactly under OBO/per-user authorization
    (the endpoint enforces the same actor-scoped contract server-side)."""

    def _caps(self, *, per_user_authorization: bool):
        return capability_service.bootstrap_capabilities(
            actor_role="reader",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            per_user_authorization=per_user_authorization,
        )

    def test_export_available_under_obo(self):
        export = self._caps(per_user_authorization=True)["exportAllowed"]
        self.assertTrue(export["available"])
        self.assertEqual(export["state"], "available")

    def test_export_unavailable_without_obo_and_reason_is_honest(self):
        export = self._caps(per_user_authorization=False)["exportAllowed"]
        self.assertFalse(export["available"])
        self.assertEqual(export["state"], "unavailable")
        # No longer the stale "not implemented" reason.
        self.assertNotIn("not implemented", export["reason"].lower())
        self.assertIn("per-user authorization", export["reason"].lower())


class CapabilityPayloadTests(unittest.TestCase):
    def test_live_writer_capabilities_are_truthful(self) -> None:
        payload = capability_service.bootstrap_capabilities(
            actor_role="writer",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=12,
            available_catalog_count=4,
            observed_catalog_count=2,
        )

        self.assertEqual(payload["governanceWrite"]["state"], "available")
        self.assertTrue(payload["governanceWrite"]["available"])
        self.assertEqual(payload["governanceApproval"]["state"], "unavailable")
        self.assertFalse(payload["governanceApproval"]["available"])
        self.assertEqual(payload["systemInventoryRead"]["state"], "available")
        self.assertTrue(payload["systemInventoryRead"]["available"])
        self.assertEqual(payload["tableLineage"]["state"], "available")
        self.assertTrue(payload["tableLineage"]["available"])
        self.assertEqual(payload["columnLineage"]["state"], "available")
        self.assertTrue(payload["columnLineage"]["available"])
        self.assertEqual(
            payload["tableLineage"]["visibilityScope"], "workspace-app-principal"
        )
        self.assertTrue(payload["tableLineage"]["workspaceScoped"])
        self.assertFalse(payload["tableLineage"]["actorScoped"])
        self.assertEqual(payload["qualityRunEligibility"]["state"], "unavailable")
        self.assertEqual(payload["exportAllowed"]["state"], "unavailable")
        self.assertEqual(payload["manualLineageOverrides"]["state"], "unavailable")

    def test_degraded_store_and_empty_inventory_surface_degraded_states(self) -> None:
        payload = capability_service.bootstrap_capabilities(
            actor_role="reader",
            authenticated=False,
            runtime_state="live",
            store_state="degraded",
            store_message="Governance store unavailable.",
            visible_asset_count=0,
            available_catalog_count=3,
            observed_catalog_count=0,
            boot_message="Workspace connected, but no visible assets were returned yet.",
        )

        self.assertEqual(payload["governanceWrite"]["state"], "degraded")
        self.assertEqual(payload["governanceApproval"]["state"], "degraded")
        self.assertEqual(payload["systemInventoryRead"]["state"], "degraded")
        self.assertTrue(payload["systemInventoryRead"]["available"])
        self.assertEqual(payload["tableLineage"]["state"], "unknown")
        self.assertEqual(payload["columnLineage"]["state"], "unknown")
        self.assertEqual(payload["workloadVisibility"]["state"], "unknown")

    def test_visible_inventory_keeps_lineage_surface_open_without_observed_edges(self) -> None:
        payload = capability_service.bootstrap_capabilities(
            actor_role="reader",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=12,
            available_catalog_count=2,
            observed_catalog_count=0,
        )

        self.assertEqual(payload["tableLineage"]["state"], "available")
        self.assertTrue(payload["tableLineage"]["available"])
        self.assertIn("empty graph", payload["tableLineage"]["reason"])
        self.assertEqual(payload["columnLineage"]["state"], "available")
        self.assertTrue(payload["columnLineage"]["available"])

    def test_runtime_unavailable_marks_runtime_scoped_capabilities_unavailable(
        self,
    ) -> None:
        payload = capability_service.bootstrap_capabilities(
            actor_role="admin",
            authenticated=True,
            runtime_state="unavailable",
            runtime_message="Warehouse is down.",
            store_state="skipped",
        )

        for key in [
            "governanceWrite",
            "governanceApproval",
            "systemInventoryRead",
            "tableLineage",
            "columnLineage",
            "workloadVisibility",
            "qualityRunEligibility",
            "exportAllowed",
            "manualLineageOverrides",
        ]:
            self.assertEqual(payload[key]["state"], "unavailable", key)
            self.assertFalse(payload[key]["available"], key)

    def test_per_user_authorization_flips_auth_mode_without_overclaiming_reads(
        self,
    ) -> None:
        payload = capability_service.bootstrap_capabilities(
            actor_role="writer",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=5,
            available_catalog_count=2,
            observed_catalog_count=1,
            per_user_authorization=True,
        )

        self.assertEqual(
            payload["systemInventoryRead"]["productMode"],
            capability_service.OBO_AVAILABLE_MODE,
        )
        self.assertEqual(
            payload["systemInventoryRead"]["visibilityScope"],
            capability_service.WORKSPACE_APP_PRINCIPAL_VISIBILITY,
        )
        self.assertTrue(payload["systemInventoryRead"]["workspaceScoped"])
        self.assertFalse(payload["systemInventoryRead"]["actorScoped"])
        self.assertEqual(
            payload["systemInventoryRead"]["source"], "unity-catalog-app-principal"
        )

    def test_claim_actor_scoped_reads_requires_per_user_authorization(self) -> None:
        no_obo = capability_service.bootstrap_capabilities(
            actor_role="writer",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=5,
            available_catalog_count=2,
            observed_catalog_count=1,
            per_user_authorization=False,
            claim_actor_scoped_reads=True,
        )
        self.assertFalse(no_obo["systemInventoryRead"]["actorScoped"])

        with_obo = capability_service.bootstrap_capabilities(
            actor_role="writer",
            authenticated=True,
            runtime_state="live",
            store_state="live",
            visible_asset_count=5,
            available_catalog_count=2,
            observed_catalog_count=1,
            per_user_authorization=True,
            claim_actor_scoped_reads=True,
        )
        self.assertTrue(with_obo["systemInventoryRead"]["actorScoped"])
        self.assertEqual(
            with_obo["systemInventoryRead"]["source"], "unity-catalog-actor"
        )


class RuntimeCapabilityWiringTests(unittest.TestCase):
    def test_runtime_surfaces_thread_capability_payload_helper(self) -> None:
        runtime_source = Path("axiom/api/runtime.py").read_text(encoding="utf-8")
        runtime_tree = ast.parse(runtime_source, filename="axiom/api/runtime.py")

        runtime_status_node = next(
            item
            for item in runtime_tree.body
            if isinstance(item, ast.FunctionDef)
            and item.name == "_api_runtime_status_response"
        )
        runtime_status_segment = (
            ast.get_source_segment(runtime_source, runtime_status_node) or ""
        )
        self.assertIn('"capabilities"', runtime_status_segment)
        self.assertIn("_capabilities_payload(", runtime_status_segment)

        app_source = Path("runtime_app.py").read_text(encoding="utf-8")
        app_tree = ast.parse(app_source, filename="runtime_app.py")

        shell_node = next(
            item
            for item in app_tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "_shell_payload"
        )
        shell_segment = ast.get_source_segment(app_source, shell_node) or ""
        self.assertIn('"capabilities"', shell_segment)
        self.assertIn("capability_service.bootstrap_capabilities(", shell_segment)

        unavailable_node = next(
            item
            for item in app_tree.body
            if isinstance(item, ast.FunctionDef)
            and item.name == "_bootstrap_unavailable_payload"
        )
        unavailable_segment = ast.get_source_segment(app_source, unavailable_node) or ""
        self.assertIn("_shell_payload(", unavailable_segment)


if __name__ == "__main__":
    unittest.main()
