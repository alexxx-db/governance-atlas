from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from atlas.api import atlas as atlas_api
from atlas.api.cache import _invalidate_cache_prefix


def _request(headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, state=SimpleNamespace())


def _response_json(response) -> dict:
    if hasattr(response, "body"):
        return json.loads(response.body.decode("utf-8"))
    return response.content


def _visible_assets() -> pd.DataFrame:
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
                "business_owner": "skyler@entrada.ai",
            }
        ]
    )


class FakeStore:
    def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "request_id": "REQ-1",
                    "created_at": "2026-04-24 01:00:00",
                    "created_by": "skyler@entrada.ai",
                    "status": "pending",
                    "uc_full_name": "main.customer.customer_dim",
                    "new_comment": "Assign owner",
                }
            ]
        )

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
                    "actor_email": "skyler@entrada.ai",
                }
            ]
        )

    def get_change_request(self, request_id: str):
        if request_id != "REQ-1":
            return None
        return SimpleNamespace(
            request_id="REQ-1",
            created_at="2026-04-24 01:00:00",
            created_by="skyler@entrada.ai",
            status="pending",
            uc_full_name="main.customer.customer_dim",
            new_comment="Assign owner",
            new_uc_tags={"business_owner": "skyler@entrada.ai"},
            reviewed_at=None,
            reviewed_by=None,
            review_note=None,
        )

    def list_classifications(self) -> pd.DataFrame:
        return pd.DataFrame([{"classification_id": "class-1", "display_name": "PII"}])

    def list_domains(self) -> pd.DataFrame:
        return pd.DataFrame([{"domain_id": "customer", "display_name": "Customer"}])

    def list_data_products(self) -> pd.DataFrame:
        return pd.DataFrame([{"data_product_id": "customer-360", "display_name": "Customer 360"}])

    def list_logical_column_groups(self) -> pd.DataFrame:
        return pd.DataFrame([{"group_id": "customer-ids", "display_name": "Customer IDs"}])

    def list_glossary_terms(self, limit: int = 200) -> pd.DataFrame:
        return pd.DataFrame(
            [{"term_id": "raw-term", "name": "Raw Term", "definition": "Raw glossary row"}]
        )

    def list_roles(self) -> pd.DataFrame:
        return pd.DataFrame([{"email": "admin@example.com", "role": "admin"}])

    def list_identity_directory_entries(
        self,
        principal_type: str | None = None,
        *,
        active_only: bool = False,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"entry_id": "u1", "principal_type": "user", "email": "admin@example.com", "is_active": True},
                {"entry_id": "g1", "principal_type": "group", "email": "", "is_active": True},
            ]
        )


class FailingRequestStore(FakeStore):
    def list_change_requests(self, status: str | None = None, limit: int = 200) -> pd.DataFrame:
        raise RuntimeError("request table unavailable")


class ActorUc:
    def runtime_context(self) -> dict[str, str]:
        return {"authMode": "obo-forwarded-token"}


class AtlasApiTests(unittest.TestCase):
    def setUp(self) -> None:
        _invalidate_cache_prefix("atlas_command_center_payload:")
        _invalidate_cache_prefix("atlas_governance_workbench_payload:")
        _invalidate_cache_prefix("atlas_governance_request_detail_payload:")
        _invalidate_cache_prefix("atlas_insights_dashboard_payload:")
        _invalidate_cache_prefix("atlas_cde_dashboard_payload:")
        _invalidate_cache_prefix("atlas_cde_detail_payload:")
        _invalidate_cache_prefix("atlas_audit_evidence_payload:")
        _invalidate_cache_prefix("atlas_taxonomy_overview:")
        _invalidate_cache_prefix("atlas_ai_recommendations:")

    def test_router_registers_all_phase5_routes(self) -> None:
        router = atlas_api.build_atlas_router()
        paths = {route.path for route in router.routes}
        self.assertIn("/api/atlas/command-center", paths)
        self.assertIn("/api/atlas/assets/{asset_fqn:path}/360", paths)
        self.assertIn("/api/atlas/governance/workbench", paths)
        self.assertIn("/api/atlas/governance/requests/{request_id}", paths)
        self.assertIn("/api/atlas/insights", paths)
        self.assertIn("/api/atlas/taxonomy/overview", paths)
        self.assertIn("/api/atlas/cde", paths)
        self.assertIn("/api/atlas/cde/{cde_id:path}", paths)
        self.assertIn("/api/atlas/audit/evidence", paths)
        self.assertIn("/api/atlas/admin/control-center", paths)

    def test_ai_router_registers_evidence_endpoints(self) -> None:
        router = atlas_api.build_atlas_ai_router()
        paths = {route.path for route in router.routes}
        self.assertEqual(
            {
                "/api/atlas-ai/recommendations", "/api/atlas-ai/message",
                "/api/atlas-ai/autofill", "/api/atlas-ai/chat",
            },
            paths,
        )

    def test_command_center_returns_meta_without_fallback_markers(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _uc_runtime_status_fast=lambda background=True: {"state": "live", "message": ""},
            _fast_bootstrap_inventory_summary=lambda _scope, **_kwargs: {"visibleAssets": 1},
            _uc_for_request=lambda request: ActorUc(),
            _visible_assets=lambda request: _visible_assets(),
            _store_for_read=lambda: FakeStore(),
            _request_cache_scope=lambda request: "test-actor",
        ):
            response = atlas_api.api_command_center(_request(), refresh="1")

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["estate"]["visibleAssetCount"], 1)
        self.assertEqual(payload["meta"]["source"], "unity-catalog-inventory+governance-store")
        self.assertNotIn("oboScopeFallback", payload["meta"])
        self.assertNotIn("oboFallbackReason", payload["meta"])

    def test_command_center_preserves_store_source_warnings(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _uc_runtime_status_fast=lambda background=True: {"state": "live", "message": ""},
            _fast_bootstrap_inventory_summary=lambda _scope, **_kwargs: {"visibleAssets": 1},
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
            _visible_assets=lambda request: _visible_assets(),
            _store_for_read=lambda: FailingRequestStore(),
            _request_cache_scope=lambda request: "test-actor",
        ):
            response = atlas_api.api_command_center(_request(), refresh="1")

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertIsNone(payload["estate"]["openRequests"])
        self.assertEqual(payload["kpis"][3]["key"], "openStewardship")
        self.assertEqual(payload["kpis"][3]["state"], "unavailable")
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertFalse(payload["authoritative"])
        self.assertTrue(
            any("list_change_requests failed" in warning for warning in payload["meta"]["warnings"])
        )

    def test_command_center_returns_loading_envelope_while_runtime_warms(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _uc_runtime_status_fast=lambda background=True: {
                "state": "loading",
                "message": "Warehouse is warming.",
            },
        ):
            response = atlas_api.api_command_center(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertFalse(payload["authoritative"])
        self.assertEqual(payload["meta"]["state"], "loading")
        self.assertEqual(payload["estate"]["visibleAssetCount"], None)
        self.assertIn("Warehouse is warming", payload["meta"]["warnings"][0])

    def test_taxonomy_overview_returns_enriched_wrapped_contract(self) -> None:
        import runtime_app

        enriched_terms = [
            {
                "termId": "customer-id",
                "term": "Customer Identifier",
                "definition": "Business-approved identifier.",
                "ownerEmail": "customer.owner@entrada.ai",
                "assetCount": 1,
            }
        ]

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
            _store_for_read=lambda: FakeStore(),
        ), patch.object(
            atlas_api.governance_service,
            "glossary_terms",
            return_value=enriched_terms,
        ):
            response = atlas_api.api_taxonomy_overview(_request(), refresh="1")

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["source"], "governance-store+unity-catalog-inventory")
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertEqual(payload["meta"]["capabilities"]["glossaryEnriched"], True)
        self.assertEqual(payload["summary"]["termCount"], 1)
        self.assertEqual(payload["glossaryTerms"][0]["termId"], "customer-id")
        self.assertEqual(payload["classifications"][0]["classification_id"], "class-1")

    def test_cde_dashboard_and_detail_preserve_truthful_degraded_source(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _cached_visible_assets=lambda request: _visible_assets(),
            _visible_assets=lambda request: _visible_assets(),
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
        ):
            dashboard_response = atlas_api.api_cde_dashboard(_request())
            detail_response = atlas_api.api_cde_detail("main.customer.customer_dim", _request())

        self.assertEqual(dashboard_response.status_code, 200)
        dashboard = _response_json(dashboard_response)
        self.assertEqual(dashboard["meta"]["source"], "unity-catalog-inventory+governance-store")
        self.assertNotIn("quality-runner", dashboard["meta"]["source"])
        self.assertEqual(dashboard["meta"]["state"], "degraded")
        self.assertFalse(dashboard["meta"]["capabilities"]["controlCoverage"])
        # Honest rename: sensitivity labels are labels, not protection.
        self.assertEqual(dashboard["summary"]["sensitivityLabeledCdes"], 1)
        self.assertNotIn("protectedCdes", dashboard["summary"])
        self.assertEqual(dashboard["summary"]["sensitiveCandidates"], 1)

        self.assertEqual(detail_response.status_code, 200)
        detail = _response_json(detail_response)
        self.assertEqual(detail["meta"]["source"], "unity-catalog-inventory+governance-store")
        self.assertNotIn("quality-runner", detail["meta"]["source"])
        self.assertEqual(detail["lineageSnapshot"]["state"], "unavailable")
        self.assertEqual(detail["controls"][0]["state"], "unavailable")
        self.assertIsNone(detail["controls"][0]["coverage"])

    def test_audit_evidence_is_steward_admin_gated(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "viewer",
            _store_for_read=lambda: FakeStore(),
        ):
            with self.assertRaises(atlas_api.HTTPException) as ctx:
                atlas_api.api_audit_evidence(_request())

        self.assertEqual(ctx.exception.status_code, 403)

    def test_audit_evidence_returns_truthful_source_and_arrays(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "steward",
            _store_for_read=lambda: FakeStore(),
            _visible_assets=lambda request: _visible_assets(),
        ):
            response = atlas_api.api_audit_evidence(_request(), audit_id="AUD-1", limit=25)

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["source"], "governance-store+metadata-audit-log")
        self.assertNotIn("change-events", payload["meta"]["source"])
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertTrue(payload["authoritative"])
        self.assertEqual(payload["selectedEvent"]["audit_id"], "AUD-1")
        self.assertIsInstance(payload["events"], list)
        self.assertIsInstance(payload["evidence"]["approvalChain"], list)
        self.assertIsInstance(payload["evidence"]["artifacts"], list)
        self.assertEqual(payload["summary"]["rowScope"], "visible-assets")
        self.assertEqual(payload["meta"]["capabilities"]["rowLevelSecurity"], "visible-assets-only")
        self.assertEqual(payload["meta"]["capabilities"]["actorIdentityExposure"], "steward-admin-gated")

    def test_audit_evidence_filters_rows_to_visible_assets(self) -> None:
        import runtime_app

        class MixedAuditStore(FakeStore):
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
                            "actor_email": "visible.steward@entrada.ai",
                        },
                        {
                            "audit_id": "AUD-HIDDEN",
                            "entity_fqn": "restricted.payroll.salary_raw",
                            "action": "grant changed",
                            "status": "success",
                            "detail": "Privilege changed",
                            "created_at": "2026-04-24 01:06:00",
                            "actor_email": "hidden.admin@entrada.ai",
                        },
                    ]
                )

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "steward",
            _store_for_read=lambda: MixedAuditStore(),
            _visible_assets=lambda request: _visible_assets(),
        ):
            response = atlas_api.api_audit_evidence(_request(), limit=25, refresh="1")

        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["audit_id"] for row in payload["events"]], ["AUD-1"])
        self.assertEqual(payload["summary"]["hiddenRowsExcluded"], 1)
        self.assertNotIn("hidden.admin@entrada.ai", json.dumps(payload))

    def test_audit_evidence_fails_closed_when_visibility_scope_unavailable(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "steward",
            _store_for_read=lambda: FakeStore(),
            _visible_assets=lambda request: (_ for _ in ()).throw(RuntimeError("inventory unavailable")),
        ):
            response = atlas_api.api_audit_evidence(_request(), limit=25, refresh="1")

        payload = _response_json(response)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["authoritative"])
        self.assertEqual(payload["meta"]["capabilities"]["rowLevelSecurity"], "fail-closed-visible-assets")
        self.assertIn("unscoped actor identities", payload["detail"])

    def test_admin_control_center_is_admin_gated(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "steward",
        ):
            with self.assertRaises(atlas_api.HTTPException) as ctx:
                atlas_api.api_admin_control_center(_request())

        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_control_center_returns_curated_source_and_sections(self) -> None:
        import runtime_app

        cfg = SimpleNamespace(
            deploy_target="Dev",
            environment_label="",
            gov_catalog="datapact",
            gov_schema="atlas",
            warehouse_id="wh-1",
            workspace_host="dbc.example.cloud.databricks.com",
        )

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "admin",
            _config=lambda: cfg,
            _visible_assets=lambda request: _visible_assets(),
            _store_for_read=lambda: FakeStore(),
            _uc_runtime_status_fast=lambda background=False: {
                "state": "live",
                "client": {"authMode": "oauth-m2m-env", "clientSecretPresent": True},
            },
        ), patch.object(
            atlas_api.genie_service,
            "provider_status",
            return_value={"state": "available", "provider": "genie", "spaceId": "space-1"},
        ):
            response = atlas_api.api_admin_control_center(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["source"], "runtime-diagnostics+governance-store")
        self.assertNotIn("background-runner", payload["meta"]["source"])
        self.assertEqual(payload["environment"]["displayLabel"], "Dev · datapact.atlas")
        self.assertEqual(payload["role"]["label"], "Platform Admin")
        self.assertIn("policyRequirements", payload)
        self.assertEqual(payload["bulkImport"]["state"], "unavailable")
        notifications = next(item for item in payload["integrations"] if item["key"] == "notifications")
        self.assertEqual(notifications["state"], "unavailable")
        self.assertIn("Notification delivery health", notifications["reason"])
        self.assertIn("access", payload)
        self.assertNotIn("clientSecretPresent", payload["system"])

    def test_asset_360_checks_visibility_before_detail_payload(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _asset_visibility_record=lambda asset_fqn, request: {
                "exists": True,
                "visible": False,
                "openable": False,
                "visibilityState": "hidden",
            },
        ):
            response = atlas_api.api_asset_360("main.hidden.table", _request())

        self.assertEqual(response.status_code, 404)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["capabilities"]["visibilityState"], "hidden")

    def test_asset_360_payload_omits_operational_without_obo(self) -> None:
        import runtime_app

        detail_sections: list[list[str]] = []

        def detail_payload(asset_fqn, request=None, sections=None):
            detail_sections.append(list(sections or []))
            return {
                "fqn": asset_fqn,
                "name": "customer_dim",
                "owners": [{"name": "skyler@entrada.ai", "title": "Business Owner"}],
                "columns": [{"name": "customer_id"}],
                "activity": [],
                "metadataAudit": [],
                "relatedAssets": [],
                "operationalContext": {"producers": [], "consumers": []},
                "usage": {},
            }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _asset_visibility_record=lambda asset_fqn, request: {
                "exists": True,
                "visible": True,
                "openable": True,
                "visibilityState": "visible",
            },
            _asset_detail_payload=detail_payload,
            _uc_for_request=lambda request: SimpleNamespace(warehouse_id="test"),
            _store_for_read=lambda: FakeStore(),
            _request_cache_scope=lambda request: "test-scope",
            _direct_uc_metadata_writes_enabled=lambda request: False,
        ):
            response = atlas_api.api_asset_360("main.customer.customer_dim", _request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(detail_sections, [])
        self.assertNotIn("operational", payload["meta"]["capabilities"]["requestedSections"])
        self.assertEqual(payload["meta"]["state"], "loading")
        self.assertTrue(payload["meta"]["capabilities"]["hydrating"])
        self.assertEqual(payload["asset"]["fqn"], "main.customer.customer_dim")

    def test_governance_request_detail_404_for_missing_request(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _store_for_read=lambda: FakeStore(),
        ):
            response = atlas_api.api_governance_request_detail("REQ-MISSING", _request())

        self.assertEqual(response.status_code, 404)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["source"], "governance-store")

    def test_atlas_ai_without_genie_fails_closed_instead_of_local_recommendations(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _visible_assets=lambda request: _visible_assets(),
            _store_for_read=lambda: FakeStore(),
        ):
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-email": "skyler@entrada.ai"}),
                atlas_api.AtlasAiQuestion(question="Draft a launch announcement"),
            )

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["intent"], "unavailable")
        self.assertEqual(payload["provider"], "unavailable")
        self.assertEqual(payload["evidence"], [])
        self.assertEqual(payload["recommendations"], [])
        self.assertEqual(payload["confidence"], "unavailable")
        self.assertEqual(payload["meta"]["state"], "unavailable")
        self.assertEqual(payload["meta"]["source"], "runtime-configuration+databricks-genie")
        self.assertFalse(payload["authoritative"])
        self.assertNotIn("local-evidence", payload["meta"]["source"])
        self.assertTrue(any("configured Databricks Genie space" in warning for warning in payload["meta"]["warnings"]))

    def test_atlas_ai_without_obo_uses_backed_workspace_metadata_not_mock_values(self) -> None:
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        visible_assets = pd.DataFrame(
            [
                {
                    "fqn": "main.customer.customer_profile",
                    "domain": "Customer",
                    "tier": "Tier 1",
                    "certification": "Trusted",
                    "criticality": "Critical",
                    "owners_summary": "customer-steward@example.com",
                    "governance_status": "Needs Work",
                }
            ]
        )

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _config=lambda: config,
            _visible_assets=lambda request: visible_assets,
        ):
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-email": "skyler@entrada.ai"}),
                atlas_api.AtlasAiQuestion(question="Which critical assets are not certified?"),
            )

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["provider"], "governance-atlas-live-metadata")
        self.assertEqual(payload["meta"]["source"], "unity-catalog-inventory+governance-store+databricks-genie-status")
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertFalse(payload["authoritative"])
        self.assertEqual(payload["evidence"][0]["assetFqn"], "main.customer.customer_profile")
        self.assertEqual(payload["evidence"][0]["source"], "unity-catalog-inventory+governance-store")
        self.assertIn("Workspace-scoped governed evidence", payload["answer"])
        self.assertTrue(payload["meta"]["capabilities"]["evidenceBacked"])
        self.assertTrue(any("not a Databricks Genie/OBO answer" in warning for warning in payload["meta"]["warnings"]))

    def test_atlas_ai_uses_genie_when_configured_with_forwarded_token(self) -> None:
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        genie_payload = {
            "question": "Which assets are missing stewardship?",
            "intent": "genie",
            "answer": "Two assets are missing owners.",
            "recommendations": [],
            "evidence": [
                {
                    "type": "genie_query",
                    "statementId": "stmt-1",
                    "sql": "SELECT asset_fqn FROM datapact.atlas_ai.atlas_ai_assets_current",
                }
            ],
            "confidence": "genie-grounded",
            "provider": "genie",
            "providerState": {
                "provider": "genie",
                "state": "available",
                "spaceId": "space-1",
                "benchmarkState": "required",
            },
            "warnings": [],
        }

        started = {
            "conversationId": "conv-1", "messageId": "msg-1", "status": "SUBMITTED",
            "stage": "Submitted to Genie", "providerState": genie_payload["providerState"],
        }
        # POST no longer blocks — it starts the conversation and returns a
        # pending handle; the finalized answer comes from the poll endpoint.
        with patch.multiple(
            runtime_app, _ensure_live_runtime=lambda: None, _config=lambda: config,
        ), patch.object(atlas_api.genie_service, "start_genie", return_value=started) as start_genie:
            pending = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo-token-1"}),
                atlas_api.AtlasAiQuestion(question="Which assets are missing stewardship?"),
            )
        start_genie.assert_called_once()
        pending_payload = _response_json(pending)
        self.assertEqual(pending_payload["intent"], "genie-pending")
        self.assertEqual(pending_payload["conversationId"], "conv-1")
        self.assertEqual(pending_payload["meta"]["state"], "pending")

        poll_result = {"status": "COMPLETED", "stage": "Done", "done": True, "payload": genie_payload}
        with patch.multiple(
            runtime_app, _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: _visible_assets(), _store=lambda: FakeStore(),
            _uc=lambda: None, _uc_for_request=lambda request: None,
        ), patch.object(atlas_api.genie_service, "poll_genie", return_value=poll_result) as poll_genie:
            response = atlas_api.api_atlas_ai_message(
                _request({"x-forwarded-access-token": "obo-token-1"}),
                atlas_api.AtlasAiPoll(conversationId="conv-1", messageId="msg-1",
                                      question="Which assets are missing stewardship?"),
            )
        poll_genie.assert_called_once()
        payload = _response_json(response)
        self.assertEqual(payload["provider"], "genie")
        self.assertEqual(payload["meta"]["source"], "databricks-genie")
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertEqual(payload["meta"]["capabilities"]["spaceId"], "space-1")
        self.assertTrue(payload["authoritative"])

    def _poll_done(self, config, genie_payload, question):
        import runtime_app

        poll_result = {"status": "COMPLETED", "stage": "Done", "done": True, "payload": genie_payload}
        with patch.multiple(
            runtime_app, _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: _visible_assets(), _store=lambda: FakeStore(),
            _uc=lambda: None, _uc_for_request=lambda request: None,
        ), patch.object(atlas_api.genie_service, "poll_genie", return_value=poll_result):
            return atlas_api.api_atlas_ai_message(
                _request({"x-forwarded-access-token": "obo-token-1"}),
                atlas_api.AtlasAiPoll(conversationId="c", messageId="m", question=question),
            )

    def test_atlas_ai_derives_actions_from_genie_query_rows(self) -> None:
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        genie_payload = {
            "question": "Recommend priority governance work",
            "intent": "genie",
            "answer": "Genie returned governed priority rows.",
            "recommendations": [],
            "evidence": [
                {
                    "type": "genie_query",
                    "statementId": "stmt-1",
                    "resultRows": [
                        {
                            "asset_fqn": "datapact.enterprise.customer_stewardship_queue",
                            "domain": "Customer",
                            "owner_count": "2",
                            "open_work_count": "1",
                        }
                    ],
                }
            ],
            "confidence": "genie-grounded",
            "provider": "genie",
            "providerState": {
                "provider": "genie",
                "state": "available",
                "spaceId": "space-1",
            },
            "warnings": [],
        }

        response = self._poll_done(config, genie_payload, "Recommend priority governance work")
        payload = _response_json(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["provider"], "genie")
        self.assertEqual(payload["recommendations"][0]["title"], "Review customer_stewardship_queue")
        self.assertEqual(payload["recommendations"][0]["evidence"][0]["id"], "datapact.enterprise.customer_stewardship_queue")
        self.assertTrue(payload["authoritative"])
        self.assertFalse(any("not substituted" in warning for warning in payload["meta"]["warnings"]))

    def test_atlas_ai_does_not_substitute_local_recommendations_for_empty_genie_answer(self) -> None:
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        genie_payload = {
            "question": "Recommend priority governance work",
            "intent": "genie",
            "answer": "",
            "recommendations": [],
            "evidence": [],
            "confidence": "unavailable",
            "provider": "genie",
            "providerState": {
                "provider": "genie",
                "state": "available",
                "spaceId": "space-1",
            },
            "warnings": [],
        }

        with patch.object(
            atlas_api.atlas_metrics, "build_ai_recommendations",
            return_value={"recommendations": [{"title": "Local fallback"}]},
        ) as build_local:
            response = self._poll_done(config, genie_payload, "Recommend priority governance work")

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        build_local.assert_not_called()
        self.assertEqual(payload["provider"], "genie")
        self.assertEqual(payload["recommendations"], [])
        self.assertEqual(payload["meta"]["source"], "databricks-genie")
        self.assertEqual(payload["meta"]["state"], "degraded")
        self.assertFalse(payload["authoritative"])
        self.assertTrue(any("not substituted" in warning for warning in payload["meta"]["warnings"]))

    def test_atlas_ai_grounds_estate_count_on_canonical_metrics(self) -> None:
        """Genie snapshot drift must never override the canonical UI number.

        Genie reports 31 certified; the visible estate has 1 strictly-certified
        asset. Atlas AI must answer the canonical figure and warn about the drift.
        """
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        genie_payload = {
            "question": "How many certified assets do we have?",
            "intent": "genie",
            "answer": "There are **31 certified assets**.",
            "recommendations": [],
            "evidence": [
                {
                    "type": "genie_query",
                    "statementId": "stmt-1",
                    "sql": "SELECT COUNT(*) FROM x WHERE is_certified = TRUE",
                    "resultRows": [{"certified_asset_count": "31"}],
                }
            ],
            "confidence": "genie-grounded",
            "provider": "genie",
            "providerState": {"provider": "genie", "state": "available", "spaceId": "space-1"},
            "warnings": [],
        }

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _config=lambda: config,
            _visible_assets=lambda request: _visible_assets(),
            _store_for_read=lambda request=None: FakeStore(),
        ), patch.object(atlas_api.genie_service, "ask_genie", return_value=genie_payload):
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo-token-1"}),
                atlas_api.AtlasAiQuestion(question="How many certified assets do we have?"),
            )

        payload = _response_json(response)
        self.assertIn("1 certified asset", payload["answer"])
        self.assertNotIn("31 certified", payload["answer"])
        self.assertEqual(payload["confidence"], "canonical-grounded")
        # Grounding now short-circuits BEFORE Genie (so estate answers are
        # correct even when Genie is down), so there is no Genie number to
        # diverge from — the canonical answer + confidence is the contract.
        self.assertEqual(payload["intent"], "governed-grounding")
        self.assertEqual(payload["evidence"][0]["metric"], "certifiedAssets")

    def test_atlas_ai_injects_page_context_into_genie_prompt(self) -> None:
        """Per-asset context must reach Genie so 'this asset' binds to a real FQN."""
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="genie",
            genie_space_id="space-1",
            genie_space_title="Governance Atlas Metadata Room",
            atlas_ai_require_benchmark=True,
            workspace_host="https://example.cloud.databricks.com",
        )
        genie_payload = {
            "question": "Who owns this asset?",
            "intent": "genie",
            "answer": "Owned by skyler@entrada.ai.",
            "recommendations": [],
            "evidence": [{"type": "genie_query", "statementId": "s", "sql": "SELECT 1"}],
            "confidence": "genie-grounded",
            "provider": "genie",
            "providerState": {"provider": "genie", "state": "available", "spaceId": "space-1"},
            "warnings": [],
        }

        started = {
            "conversationId": "c", "messageId": "m", "status": "SUBMITTED",
            "stage": "Submitted to Genie", "providerState": genie_payload["providerState"],
        }
        # _visible_assets=None so the ownership/scoped/estate grounders decline
        # and the question reaches Genie — the augmented prompt now goes to
        # start_genie (the non-blocking start), not the removed blocking call.
        with patch.multiple(
            runtime_app, _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: None, _uc=lambda: None, _uc_for_request=lambda request: None,
        ), patch.object(atlas_api.genie_service, "start_genie", return_value=started) as start_genie:
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo-token-1"}),
                atlas_api.AtlasAiQuestion(
                    question="Who owns this asset?",
                    context=atlas_api.AtlasAiContext(
                        surface="assets", assetFqn="finance_prod.curated.revenue_daily"
                    ),
                ),
            )

        self.assertEqual(response.status_code, 200)
        prompt = start_genie.call_args.kwargs["question"]
        self.assertIn("finance_prod.curated.revenue_daily", prompt)
        self.assertIn("this asset", prompt.lower())
        # The user-facing question is preserved, not the augmented prompt.
        self.assertEqual(_response_json(response)["question"], "Who owns this asset?")

    # --- Ownership grounding (fix #1 + #2) -------------------------------

    @staticmethod
    def _ownership_frame() -> pd.DataFrame:
        # Finance: 3 assets, 2 ownerless (charges_raw has a UC owner but no
        # governance owner; orders_raw has neither); Customer: 1 owned.
        # Global: 4 assets total, 2 ownerless.
        return pd.DataFrame(
            [
                {"fqn": "finance_prod.bronze.charges_raw", "domain": "Finance",
                 "uc_owner": "skyler@entrada.ai"},
                {"fqn": "finance_prod.bronze.orders_raw", "domain": "Finance"},
                {"fqn": "finance_prod.gold.revenue_recognition", "domain": "Finance",
                 "business_owner": "cfo@entrada.ai"},
                {"fqn": "main.customer.customer_dim", "domain": "Customer",
                 "business_owner": "skyler@entrada.ai"},
            ]
        )

    @staticmethod
    def _scoped_frame() -> pd.DataFrame:
        return pd.DataFrame([
            {"fqn": "finance_prod.gold.a", "domain": "Finance", "tier": "Tier 1",
             "sensitivity": "PII", "certification": "Certified", "criticality": "Critical"},
            {"fqn": "finance_prod.gold.b", "domain": "Finance", "tier": "Tier 1",
             "certification": "Draft", "criticality": "Critical"},
            {"fqn": "main.customer.c", "domain": "Customer", "tier": "Tier 2",
             "sensitivity": "PII", "certification": "Certified"},
        ])

    def _ask_with_frame(self, question, frame, context=None):
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="local", genie_space_id="", genie_space_title="",
            atlas_ai_require_benchmark=False, workspace_host="https://example.cloud.databricks.com",
        )
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: frame, _store=lambda: FakeStore(),
            _store_for_read=lambda request=None: FakeStore(),
        ), patch.object(atlas_api.genie_service, "ask_genie") as ask_genie:
            kwargs = {"question": question}
            if context is not None:
                kwargs["context"] = context
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo"}),
                atlas_api.AtlasAiQuestion(**kwargs),
            )
        return _response_json(response), ask_genie

    def test_scoped_count_certified_in_domain(self) -> None:
        # "how many certified assets in Finance?" → 1 (a is Certified; b is Draft).
        payload, ask_genie = self._ask_with_frame(
            "How many certified assets in the Finance domain?", self._scoped_frame())
        self.assertEqual(payload["intent"], "governed-grounding")
        self.assertIn("1", payload["answer"])
        self.assertIn("certified", payload["answer"].lower())
        self.assertIn("Finance", payload["answer"])
        self.assertEqual(payload["evidence"][0]["metric"], "scopedAssetCount")
        ask_genie.assert_not_called()

    def test_scoped_count_by_tier_value(self) -> None:
        payload, _ = self._ask_with_frame("How many assets are in the Tier 1 tier?", self._scoped_frame())
        self.assertEqual(payload["intent"], "governed-grounding")
        self.assertIn("2", payload["answer"])  # a + b
        self.assertIn("Tier 1", payload["answer"])

    def test_scoped_count_by_sensitivity_value(self) -> None:
        payload, _ = self._ask_with_frame("How many PII assets do we have?", self._scoped_frame())
        self.assertEqual(payload["intent"], "governed-grounding")
        self.assertIn("2", payload["answer"])  # a + c
        self.assertIn("PII", payload["answer"])

    def test_global_certified_count_stays_estate_not_scoped(self) -> None:
        # No subset scope → estate metric (certifiedAssets), NOT scoped-count.
        payload, _ = self._ask_with_frame("How many certified assets are there?", self._scoped_frame())
        self.assertEqual(payload["evidence"][0]["metric"], "certifiedAssets")

    def test_scoped_count_uncertified_phrasings_not_inverted(self) -> None:
        # Review F1: negation/pending phrasings must count UNCERTIFIED (1), never
        # fall through to the certified count. Answer must say "uncertified".
        for q in (
            "How many not yet certified assets in the Finance domain?",
            "How many Finance domain assets need certification?",
            "How many pending certification assets in the Finance domain?",
            "How many decertified assets in the Finance domain?",
        ):
            payload, _ = self._ask_with_frame(q, self._scoped_frame())
            self.assertIn("uncertified", payload["answer"].lower(), q)
            self.assertIn("1", payload["answer"], q)

    def test_scoped_count_criticality_word_does_not_filter_critical(self) -> None:
        # Review F3: "critically"/"criticality" must NOT set the is_critical
        # filter (word-boundary). The answer must not claim "business-critical".
        payload, _ = self._ask_with_frame(
            "How many critically important assets in the Finance domain?", self._scoped_frame())
        self.assertNotIn("business-critical", payload["answer"].lower())

    def test_compound_owner_facet_question_declines(self) -> None:
        # Review F4: "certified assets without an owner in Finance" must NOT be
        # answered as a plain ownerless count (which drops "certified"). With
        # Genie unconfigured it declines — key: not a governed-grounding answer.
        payload, _ = self._ask_with_frame(
            "How many certified assets without an owner in the Finance domain?", self._scoped_frame())
        self.assertNotEqual(payload.get("intent"), "governed-grounding")

    def test_unmappable_classification_declines_not_dropped(self) -> None:
        # Live-caught: the estate tags Confidential/Restricted, not "PII". A PII
        # question must NOT return the estate total (no-domain) or drop PII and
        # count all domain assets — it must decline to Genie.
        frame = pd.DataFrame([
            {"fqn": "a", "domain": "Finance", "sensitivity": "Confidential"},
            {"fqn": "b", "domain": "Finance", "sensitivity": "Restricted"},
            {"fqn": "c", "domain": "Customer", "sensitivity": "Confidential"},
        ])
        for q in ("How many PII assets do we have?", "How many PII assets in the Finance domain?"):
            payload, _ = self._ask_with_frame(q, frame)
            self.assertNotEqual(payload.get("intent"), "governed-grounding", q)

    def test_real_sensitivity_value_still_grounds(self) -> None:
        # A sensitivity value that DOES exist still grounds (Confidential → 2).
        frame = pd.DataFrame([
            {"fqn": "a", "domain": "Finance", "sensitivity": "Confidential"},
            {"fqn": "b", "domain": "Finance", "sensitivity": "Restricted"},
            {"fqn": "c", "domain": "Customer", "sensitivity": "Confidential"},
        ])
        payload, _ = self._ask_with_frame("How many Confidential assets are there?", frame)
        self.assertEqual(payload["evidence"][0]["metric"], "scopedAssetCount")
        self.assertIn("2", payload["answer"])

    def test_common_sensitivity_word_does_not_false_trigger(self) -> None:
        # Review F2: a question that merely contains "internal" must not be
        # answered as an Internal-sensitivity subset stamped canonical.
        frame = pd.DataFrame([
            {"fqn": "a", "domain": "Ops", "sensitivity": "Internal"},
            {"fqn": "b", "domain": "Ops", "sensitivity": "Confidential"},
        ])
        payload, _ = self._ask_with_frame("How many assets are for internal use?", frame)
        self.assertNotEqual(payload.get("evidence", [{}])[0].get("metric"), "scopedAssetCount")

    def _ask_grounded(self, question, context=None):
        """Call the endpoint with ownership grounding active (Genie unconfigured
        is fine — grounding short-circuits before the Genie branch)."""
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="local", genie_space_id="", genie_space_title="",
            atlas_ai_require_benchmark=False, workspace_host="https://example.cloud.databricks.com",
        )
        frame = self._ownership_frame()
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _config=lambda: config,
            _visible_assets=lambda request: frame,
            _store=lambda: FakeStore(),
            _store_for_read=lambda request=None: FakeStore(),
        ), patch.object(atlas_api.genie_service, "ask_genie") as ask_genie:
            kwargs = {"question": question}
            if context is not None:
                kwargs["context"] = context
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo"}),
                atlas_api.AtlasAiQuestion(**kwargs),
            )
        return _response_json(response), ask_genie

    def test_domain_scoped_ownerless_count_not_global_total(self) -> None:
        # Fix #1 + #2: must answer "2 of 3 Finance" — NOT the global total (4)
        # stamped canonical, which was the confidently-wrong behaviour.
        payload, ask_genie = self._ask_grounded(
            "How many assets in the Finance domain do not have an owner?"
        )
        self.assertIn("2", payload["answer"])
        self.assertIn("Finance", payload["answer"])
        self.assertNotIn("estate", payload["answer"].lower())
        self.assertEqual(payload["confidence"], "canonical-grounded")
        self.assertEqual(payload["intent"], "governed-grounding")
        ask_genie.assert_not_called()

    def test_domain_superlative_ownerless_matches_dashboard(self) -> None:
        # Fix #2: "which domain has the most assets without an owner?" must name
        # Finance (2), not drift to a different domain via Genie.
        payload, ask_genie = self._ask_grounded(
            "Which domain has the most assets without an owner?"
        )
        self.assertIn("Finance", payload["answer"])
        self.assertIn("2", payload["answer"])
        self.assertEqual(payload["intent"], "governed-grounding")
        ask_genie.assert_not_called()

    def test_per_asset_ownership_reports_uc_owner_and_governance_gap(self) -> None:
        # Fix #2: an asset with a UC owner but no governance owner must report
        # BOTH — the AI said "no owner" before while the asset page showed the
        # UC owner (the app-contradiction defect).
        payload, ask_genie = self._ask_grounded(
            "Who owns this asset?",
            context=atlas_api.AtlasAiContext(surface="assets", assetFqn="finance_prod.bronze.charges_raw"),
        )
        self.assertIn("skyler@entrada.ai", payload["answer"])
        self.assertIn("no assigned governance owner", payload["answer"].lower())
        self.assertEqual(payload["intent"], "governed-grounding")
        ask_genie.assert_not_called()

    def test_global_ownerless_count_is_not_total_assets(self) -> None:
        # Fix #1: "how many assets have no owner?" used to return totalAssets (4);
        # must return the ownerless count (2).
        payload, ask_genie = self._ask_grounded("How many assets have no owner?")
        self.assertIn("2", payload["answer"])
        self.assertNotIn("4 ", payload["answer"])  # not the total-asset count
        ask_genie.assert_not_called()

    def test_page_scope_resolves_here_to_filtered_domain(self) -> None:
        # Fix #3: "how many assets here lack an owner?" while filtered to the
        # Finance domain must resolve "here" to Finance (2), not the estate.
        payload, ask_genie = self._ask_grounded(
            "How many assets here do not have an owner?",
            context=atlas_api.AtlasAiContext(surface="discovery", scope={"domain": ["Finance"]}),
        )
        self.assertIn("2", payload["answer"])
        self.assertIn("Finance", payload["answer"])
        ask_genie.assert_not_called()

    def test_steward_phrased_gap_not_global_total(self) -> None:
        # Review BLOCKER 1: "missing a steward" used to slip the token list and
        # return the global estate total. Must be grounded on the gap count (2).
        payload, ask_genie = self._ask_grounded("How many assets are missing a steward?")
        self.assertIn("2", payload["answer"])
        self.assertNotIn("4 ", payload["answer"])
        ask_genie.assert_not_called()

    def test_negation_phrased_gap_not_global_total(self) -> None:
        # Review F1: "not owned" / "aren't assigned an owner" negation phrasings
        # used to slip both gates and return the global estate total as canonical.
        for question in ("How many assets are not owned?", "How many assets aren't assigned an owner?"):
            payload, ask_genie = self._ask_grounded(question)
            self.assertIn("2", payload["answer"], question)
            self.assertNotIn("in the current estate", payload["answer"].lower(), question)
            ask_genie.assert_not_called()

    def test_technical_owner_only_asset_is_not_ownerless(self) -> None:
        # Review BLOCKER 2: an asset whose only governance owner is a TECHNICAL
        # owner must not be reported "no owner" (the dashboard counts it owned).
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="local", genie_space_id="", genie_space_title="",
            atlas_ai_require_benchmark=False, workspace_host="https://example.cloud.databricks.com",
        )
        frame = pd.DataFrame([
            {"fqn": "main.finance.ledger", "domain": "Finance", "technical_owner": "alice@entrada.ai"},
        ])
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: frame, _store=lambda: FakeStore(),
            _store_for_read=lambda request=None: FakeStore(),
        ), patch.object(atlas_api.genie_service, "ask_genie") as ask_genie:
            response = atlas_api.api_atlas_ai_recommendations(
                _request({"x-forwarded-access-token": "obo"}),
                atlas_api.AtlasAiQuestion(
                    question="Who owns main.finance.ledger?",
                    context=atlas_api.AtlasAiContext(surface="assets", assetFqn="main.finance.ledger"),
                ),
            )
        payload = _response_json(response)
        self.assertIn("alice@entrada.ai", payload["answer"])
        self.assertNotIn("no owner is recorded", payload["answer"].lower())
        ask_genie.assert_not_called()

    def test_tier_scoped_question_declines_estate_grounding(self) -> None:
        # Review BLOCKER 3: a tier-scoped question must NOT return the estate
        # total stamped canonical. With Genie unconfigured it declines to the
        # unavailable path — the key is it is NOT governed-grounding here.
        payload, _ = self._ask_grounded("How many assets are in the Gold tier?")
        self.assertNotEqual(payload.get("intent"), "governed-grounding")

    def test_superlative_tie_break_matches_dashboard_name_ascending(self) -> None:
        # Review Issue 5: on an ownerless tie, "most" must pick the same domain
        # the dashboard's top stewardship card does (name ascending), i.e. Alpha.
        import runtime_app

        config = SimpleNamespace(
            atlas_ai_provider="local", genie_space_id="", genie_space_title="",
            atlas_ai_require_benchmark=False, workspace_host="https://example.cloud.databricks.com",
        )
        frame = pd.DataFrame([
            {"fqn": "z.a.one", "domain": "Zeta"},
            {"fqn": "z.a.two", "domain": "Zeta"},
            {"fqn": "a.a.one", "domain": "Alpha"},
            {"fqn": "a.a.two", "domain": "Alpha"},
        ])
        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None, _config=lambda: config,
            _visible_assets=lambda request: frame, _store=lambda: FakeStore(),
            _store_for_read=lambda request=None: FakeStore(),
        ):
            response = atlas_api.api_atlas_ai_recommendations(
                _request({}),
                atlas_api.AtlasAiQuestion(question="Which domain has the most assets without an owner?"),
            )
        answer = _response_json(response)["answer"]
        self.assertIn("Alpha", answer.split(".")[0])  # named as the top domain

    def test_collection_question_on_asset_page_not_answered_about_current_asset(self) -> None:
        # Review Issue 4: "who owns our most critical tables?" on an asset page
        # must not be hijacked into a single-asset answer.
        payload, _ = self._ask_grounded(
            "Who owns our most critical tables?",
            context=atlas_api.AtlasAiContext(surface="assets", assetFqn="finance_prod.bronze.charges_raw"),
        )
        self.assertNotIn("charges_raw", payload["answer"])

    def test_overlong_scope_value_does_not_reject_request(self) -> None:
        # Review Issue 7: a >128-char scope value must be truncated, not 422.
        ctx = atlas_api.AtlasAiContext(surface="discovery", scope={"query": "x" * 400})
        self.assertLessEqual(len(ctx.scope["query"]), 128)

    def test_scope_summary_and_preamble(self) -> None:
        # The active facet scope reaches the Genie prompt preamble.
        ctx = atlas_api.AtlasAiContext(
            surface="discovery", scope={"domain": ["Finance"], "owner": "__unassigned__"}
        )
        preamble = atlas_api._ai_context_preamble(ctx)
        self.assertIn("domain Finance", preamble)
        self.assertIn("owner unassigned", preamble)


def _age_cache_prefix(prefix: str, seconds: float = 3600) -> None:
    """Backdate cached entries so the fresh-TTL check misses but stale data remains."""
    from atlas.api import cache as cache_module

    with cache_module._CACHE_LOCK:
        for key, (ts, value) in list(cache_module._TTL_CACHE.items()):
            if key.startswith(prefix):
                cache_module._TTL_CACHE[key] = (ts - seconds, value)


def _raise_visible_assets(request) -> pd.DataFrame:
    raise RuntimeError("synchronous rebuild must not run while stale data exists")


class StaleWhileRevalidateTests(unittest.TestCase):
    """TTL expiry must serve the last good payload, never an empty loading envelope.

    Regression: dashboards flip-flopped available -> loading -> available on every
    cache expiry, blanking KPIs for live users (observed on /api/atlas/command-center).
    """

    def setUp(self) -> None:
        _invalidate_cache_prefix("atlas_command_center_payload:")
        _invalidate_cache_prefix("atlas_taxonomy_overview:")
        _invalidate_cache_prefix("atlas_audit_evidence_payload:")
        _invalidate_cache_prefix("atlas_admin_control_center_payload:")
        _invalidate_cache_prefix("runtime_inventory:")

    def test_ttl_stale_value_returns_expired_entries(self) -> None:
        from atlas.api.cache import _ttl_stale_value, _ttl_value

        _ttl_value("swr-test-key", 45, lambda: {"v": 1})
        _age_cache_prefix("swr-test-key")
        self.assertEqual(_ttl_stale_value("swr-test-key"), {"v": 1})
        self.assertIsNone(_ttl_stale_value("swr-test-missing"))

    def test_ttl_value_stamps_completion_time_for_slow_loaders(self) -> None:
        """A loader slower than its TTL must still produce a fresh entry.

        Regression: entries were stamped with the pre-load timestamp, so any
        loader slower than its TTL wrote an already-expired entry and the
        endpoint stayed in state=loading forever (observed live on taxonomy,
        audit evidence, and control-center).
        """
        from unittest.mock import patch as mock_patch

        from atlas.api import cache as cache_module

        clock = {"now": 1000.0}

        def fake_time() -> float:
            return clock["now"]

        def slow_loader() -> dict:
            clock["now"] += 40  # slower than the 30s TTL
            return {"v": "slow"}

        with mock_patch.object(cache_module.time, "time", fake_time):
            cache_module._ttl_value("swr-slow-key", 30, slow_loader)
            self.assertEqual(
                cache_module._ttl_fresh_value("swr-slow-key", 30), {"v": "slow"}
            )

    def _command_center_mocks(self, visible_assets_fn):
        import runtime_app

        return patch.multiple(
            runtime_app,
            _uc_runtime_status_fast=lambda background=True: {"state": "live", "message": ""},
            _fast_bootstrap_inventory_summary=lambda _scope, **_kwargs: {"visibleAssets": 1},
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
            _visible_assets=visible_assets_fn,
            _store_for_read=lambda: FakeStore(),
            _request_cache_scope=lambda request: "swr-actor",
        )

    def test_command_center_serves_stale_payload_after_ttl_expiry(self) -> None:
        with self._command_center_mocks(lambda request: _visible_assets()):
            warm = atlas_api.api_command_center(_request(), refresh="1")
        self.assertEqual(_response_json(warm)["estate"]["visibleAssetCount"], 1)

        _age_cache_prefix("atlas_command_center_payload:")
        with self._command_center_mocks(_raise_visible_assets):
            response = atlas_api.api_command_center(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertNotEqual(payload["meta"]["state"], "loading")
        self.assertEqual(payload["estate"]["visibleAssetCount"], 1)

    def test_taxonomy_overview_serves_stale_payload_after_ttl_expiry(self) -> None:
        import runtime_app

        live_mocks = dict(
            _ensure_live_runtime=lambda: None,
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
        )
        with patch.multiple(
            runtime_app, **live_mocks, _store_for_read=lambda: FakeStore()
        ), patch.object(atlas_api.governance_service, "glossary_terms", return_value=[]):
            warm = atlas_api.api_taxonomy_overview(_request(), refresh="1")
        self.assertEqual(_response_json(warm)["meta"]["state"], "available")

        def _raise_store():
            raise RuntimeError("synchronous rebuild must not run while stale data exists")

        _age_cache_prefix("atlas_taxonomy_overview:")
        with patch.multiple(runtime_app, **live_mocks, _store_for_read=_raise_store):
            response = atlas_api.api_taxonomy_overview(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertNotEqual(payload["meta"]["state"], "loading")
        self.assertEqual(payload["classifications"][0]["classification_id"], "class-1")

    def test_audit_evidence_serves_stale_payload_after_ttl_expiry(self) -> None:
        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _user_role_slug=lambda request: "steward",
            _store_for_read=lambda: FakeStore(),
            _visible_assets=lambda request: _visible_assets(),
        ):
            warm = atlas_api.api_audit_evidence(_request(), limit=25, refresh="1")
        self.assertIsInstance(_response_json(warm)["events"], list)

        _age_cache_prefix("atlas_audit_evidence_payload:")
        # Pre-mark the key as warming so no background thread spawns; the raising
        # _visible_assets mock would otherwise poison the cache mid-test.
        cache_key = atlas_api._route_cache_key(
            "atlas_audit_evidence_payload",
            atlas_api._request_scope_key(_request()),
            None,
            None,
            25,
        )
        with atlas_api._AUDIT_EVIDENCE_WARMING_LOCK:
            atlas_api._AUDIT_EVIDENCE_WARMING.add(cache_key)
        try:
            with patch.multiple(
                runtime_app,
                _ensure_live_runtime=lambda: None,
                _user_role_slug=lambda request: "steward",
                _store_for_read=lambda: FakeStore(),
                _visible_assets=_raise_visible_assets,
            ):
                response = atlas_api.api_audit_evidence(_request(), limit=25)
        finally:
            with atlas_api._AUDIT_EVIDENCE_WARMING_LOCK:
                atlas_api._AUDIT_EVIDENCE_WARMING.discard(cache_key)

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertNotEqual(payload["meta"]["state"], "loading")
        self.assertIsInstance(payload["events"], list)
        self.assertNotIn("hydrating", payload["meta"].get("capabilities", {}))

    def _admin_control_mocks(self, visible_assets_fn):
        import runtime_app

        cfg = SimpleNamespace(
            deploy_target="Dev",
            environment_label="Dev - DEFAULT",
            gov_catalog="datapact",
            gov_schema="atlas",
            warehouse_id="wh-1",
            workspace_host="example.cloud.databricks.com",
        )
        return patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _config=lambda: cfg,
            _user_role_slug=lambda request: "admin",
            _fast_bootstrap_inventory_summary=lambda _scope, **_kwargs: {"visibleAssets": 1},
            _request_cache_scope=lambda request: "swr-actor",
            _uc_runtime_status_fast=lambda background=True: {"state": "live", "message": ""},
            _uc_for_request=lambda request: SimpleNamespace(runtime_context=lambda: {}),
            _visible_assets=visible_assets_fn,
            _store_for_read=lambda: FakeStore(),
        )

    def test_admin_control_center_serves_stale_payload_after_ttl_expiry(self) -> None:
        with self._admin_control_mocks(lambda request: _visible_assets()), patch.object(
            atlas_api.genie_service, "provider_status", lambda _cfg: {"state": "available"}
        ), patch.object(atlas_api, "_databricks_job_inventory", lambda *_a, **_k: []):
            warm = atlas_api.api_admin_control_center(_request(), refresh="1")
        self.assertEqual(_response_json(warm)["meta"]["state"], "available")

        _age_cache_prefix("atlas_admin_control_center_payload:")
        with self._admin_control_mocks(_raise_visible_assets), patch.object(
            atlas_api.genie_service, "provider_status", lambda _cfg: {"state": "available"}
        ), patch.object(atlas_api, "_databricks_job_inventory", lambda *_a, **_k: []):
            response = atlas_api.api_admin_control_center(_request())

        self.assertEqual(response.status_code, 200)
        payload = _response_json(response)
        self.assertEqual(payload["meta"]["state"], "available")
        self.assertTrue(payload["meta"]["capabilities"].get("refreshing"))


if __name__ == "__main__":
    unittest.main()
