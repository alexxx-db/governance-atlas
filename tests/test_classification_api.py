from __future__ import annotations

import asyncio
import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from axiom.api import classification as classification_api
from axiom.services import classification as classification_service


class FakeStore:
    def __init__(self) -> None:
        self.records: Dict[str, Dict[str, Any]] = {}
        self.audit_events: List[Dict[str, Any]] = []

    def upsert_classification_recommendation(
        self,
        record: Dict[str, Any],
        *,
        actor_email: Optional[str] = None,
    ) -> str:
        rec_id = record.get("recommendation_id") or f"auto-{len(self.records)}"
        snapshot = dict(record)
        snapshot["recommendation_id"] = rec_id
        snapshot.setdefault("status", "pending")
        snapshot.setdefault("sample_redacted", True)
        self.records[rec_id] = snapshot
        return rec_id

    def list_classification_recommendations(
        self,
        *,
        status: Optional[str] = None,
        asset_fqn: Optional[str] = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        rows = []
        for rec in self.records.values():
            if status and str(rec.get("status") or "").lower() != status.lower():
                continue
            if asset_fqn and rec.get("asset_fqn") != asset_fqn:
                continue
            rows.append(rec)
        return pd.DataFrame(rows)

    def get_classification_recommendation(
        self, recommendation_id: str
    ) -> Optional[Dict[str, Any]]:
        rec = self.records.get(recommendation_id)
        return dict(rec) if rec else None

    def set_classification_recommendation_status(
        self,
        recommendation_id: str,
        *,
        status: str,
        reviewer: str,
        review_note: Optional[str] = None,
    ) -> None:
        rec = self.records.get(recommendation_id)
        if not rec:
            return
        rec["status"] = status
        rec["reviewed_by"] = reviewer
        rec["review_note"] = review_note

    def append_metadata_audit(self, **kwargs: Any) -> str:
        self.audit_events.append(kwargs)
        return f"audit-{len(self.audit_events)}"


class FakeUC:
    def __init__(self, columns: Optional[List[Dict[str, Any]]] = None) -> None:
        self.column_tag_writes: List[Dict[str, Any]] = []
        self.column_reads = 0
        self._columns = columns or []

    def get_table_columns(self, catalog: str, schema: str, table: str) -> pd.DataFrame:
        self.column_reads += 1
        return pd.DataFrame(self._columns) if self._columns else pd.DataFrame()

    def get_column_tags(
        self, catalog: str, schema: str, table: str, column: str
    ) -> pd.DataFrame:
        return pd.DataFrame()

    def set_column_tags(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        tags: Dict[str, str],
        *,
        table_type: Optional[str] = None,
    ) -> None:
        self.column_tag_writes.append({"column": column, "tags": dict(tags)})


_UNSET = object()
_RUNTIME_STUB_ATTRS = (
    "_ensure_live_runtime",
    "_ensure_governance_store",
    "_store",
    "_ensure_can_approve",
    "_ensure_can_mutate",
    "_http_request_id",
    "_user_role_slug",
    "_uc_for_request",
    "_asset_is_openable",
)


def _install_fake_runtime_app(
    store: FakeStore,
    uc: FakeUC,
    *,
    openable: bool = True,
    openable_assets: Optional[set[str]] = None,
):
    """Patch ``runtime_app`` with test stubs and return a restore thunk.

    We avoid replacing the whole module in ``sys.modules`` because that
    corrupts other test modules that imported the real ``runtime_app`` during
    collection. Instead we mutate the existing module's attributes and
    record the prior values so tearDown can restore them verbatim.
    """
    module = sys.modules.get("runtime_app")
    created_module = False
    if module is None:
        module = ModuleType("runtime_app")
        sys.modules["runtime_app"] = module
        created_module = True

    snapshot: Dict[str, Any] = {
        name: getattr(module, name, _UNSET) for name in _RUNTIME_STUB_ATTRS
    }
    module._ensure_live_runtime = lambda: None  # type: ignore[attr-defined]
    module._ensure_governance_store = lambda: store  # type: ignore[attr-defined]
    module._store = lambda: store  # type: ignore[attr-defined]
    module._ensure_can_approve = lambda request: "alice@test.co"  # type: ignore[attr-defined]
    module._ensure_can_mutate = lambda request: "alice@test.co"  # type: ignore[attr-defined]
    module._http_request_id = lambda request: "test-request-id"  # type: ignore[attr-defined]
    module._user_role_slug = lambda request: "steward"  # type: ignore[attr-defined]
    module._uc_for_request = lambda request: uc  # type: ignore[attr-defined]
    if openable_assets is not None:
        module._asset_is_openable = lambda asset_fqn, request: asset_fqn in openable_assets  # type: ignore[attr-defined]
    else:
        module._asset_is_openable = lambda asset_fqn, request: openable  # type: ignore[attr-defined]

    def _restore() -> None:
        if created_module:
            sys.modules.pop("runtime_app", None)
            return
        for name, previous in snapshot.items():
            if previous is _UNSET:
                if hasattr(module, name):
                    delattr(module, name)
            else:
                setattr(module, name, previous)

    return _restore


def _parse_response(response) -> Dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


class ListEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.uc = FakeUC()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc)

    def tearDown(self) -> None:
        self._restore_runtime()

    def test_list_pending_returns_empty(self) -> None:
        response = classification_api.api_list_classification_recommendations(
            request=SimpleNamespace(headers={}), status="pending"
        )
        payload = _parse_response(response)
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["pendingCount"], 0)
        self.assertEqual(payload["recommendations"], [])

    def test_list_returns_seeded_records(self) -> None:
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "pending",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )
        response = classification_api.api_list_classification_recommendations(
            request=SimpleNamespace(headers={}), status="pending"
        )
        payload = _parse_response(response)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["pendingCount"], 1)
        self.assertEqual(payload["recommendations"][0]["recommendationId"], "r1")

    def test_list_normalizes_nan_nullable_fields_before_json_response(self) -> None:
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r-nan",
                "asset_fqn": "main.sales.customers",
                "column_name": "email",
                "status": "pending",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": float("nan"),
                "suggested_tier": float("nan"),
                "suggested_certification": float("nan"),
                "reviewed_by": float("nan"),
            }
        )

        response = classification_api.api_list_classification_recommendations(
            request=SimpleNamespace(headers={}), status="pending"
        )
        payload = _parse_response(response)

        record = payload["recommendations"][0]
        self.assertEqual(record["recommendationId"], "r-nan")
        self.assertEqual(record["suggestedTier"], "")
        self.assertEqual(record["suggestedCertification"], "")
        self.assertEqual(record["reviewedBy"], "")
        self.assertIs(record["sampleRedacted"], True)

    def test_list_with_asset_filter_requires_open_asset(self) -> None:
        from fastapi import HTTPException

        self._restore_runtime()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc, openable=False)
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "pending",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )

        with self.assertRaises(HTTPException) as ctx:
            classification_api.api_list_classification_recommendations(
                request=SimpleNamespace(headers={}),
                status="pending",
                asset_fqn="main.sales.customers",
            )

        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_without_asset_filter_hides_non_openable_records(self) -> None:
        self._restore_runtime()
        self._restore_runtime = _install_fake_runtime_app(
            self.store,
            self.uc,
            openable_assets={"main.sales.visible_customers"},
        )
        for rec_id, asset_fqn in (
            ("visible", "main.sales.visible_customers"),
            ("hidden", "main.sales.hidden_customers"),
        ):
            self.store.upsert_classification_recommendation(
                {
                    "recommendation_id": rec_id,
                    "asset_fqn": asset_fqn,
                    "column_name": "ssn",
                    "status": "pending",
                    "evidence_json": "[]",
                    "sample_values_json": "",
                    "remediation_suggestions_json": "[]",
                    "sample_redacted": True,
                }
            )

        response = classification_api.api_list_classification_recommendations(
            request=SimpleNamespace(headers={}), status="all"
        )

        payload = _parse_response(response)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["recommendations"][0]["recommendationId"], "visible")

    def test_list_all_aliases_no_filter(self) -> None:
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "approved",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )
        response = classification_api.api_list_classification_recommendations(
            request=SimpleNamespace(headers={}), status="all"
        )
        payload = _parse_response(response)
        self.assertEqual(payload["count"], 1)


class GetEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.uc = FakeUC()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc)

    def tearDown(self) -> None:
        self._restore_runtime()

    def test_get_found(self) -> None:
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "pending",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )
        response = classification_api.api_get_classification_recommendation(
            "r1", request=SimpleNamespace(headers={})
        )
        payload = _parse_response(response)
        self.assertEqual(payload["recommendation"]["recommendationId"], "r1")

    def test_get_missing_raises_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            classification_api.api_get_classification_recommendation(
                "missing", request=SimpleNamespace(headers={})
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_hidden_asset_recommendation_returns_404(self) -> None:
        from fastapi import HTTPException

        self._restore_runtime()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc, openable=False)
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "pending",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )

        with self.assertRaises(HTTPException) as ctx:
            classification_api.api_get_classification_recommendation(
                "r1", request=SimpleNamespace(headers={})
            )

        self.assertEqual(ctx.exception.status_code, 404)


class ReviewEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.uc = FakeUC()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc)
        self.store.upsert_classification_recommendation(
            {
                "recommendation_id": "r1",
                "asset_fqn": "main.sales.customers",
                "column_name": "ssn",
                "status": "pending",
                "suggested_sensitivity": "restricted",
                "suggested_tier": "pii",
                "suggested_certification": "classified",
                "evidence_json": "[]",
                "sample_values_json": "",
                "remediation_suggestions_json": "[]",
                "sample_redacted": True,
            }
        )

    def tearDown(self) -> None:
        self._restore_runtime()

    def test_approve_transitions_and_writes_tag(self) -> None:
        payload_model = classification_api.ClassificationReviewPayload(
            decision="approved", note="looks good"
        )
        response = asyncio.run(
            classification_api.api_review_classification_recommendation(
                "r1", payload_model, request=SimpleNamespace(headers={})
            )
        )
        body = _parse_response(response)
        self.assertTrue(body["ok"])
        self.assertEqual(body["recommendation"]["status"], "approved")
        self.assertTrue(self.uc.column_tag_writes)

    def test_invalid_decision_returns_400(self) -> None:
        from fastapi import HTTPException

        payload_model = classification_api.ClassificationReviewPayload.model_construct(
            decision="maybe", note=""
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_review_classification_recommendation(
                    "r1", payload_model, request=SimpleNamespace(headers={})
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_invalid_decision_route_returns_400_not_422(self) -> None:
        app = FastAPI()
        app.include_router(classification_api.build_classification_router())
        client = TestClient(app)

        response = client.post(
            "/api/classification-recommendations/r1/review",
            json={"decision": "maybe", "note": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("decision must be one of", response.text)

    def test_writer_role_cannot_review_recommendation(self) -> None:
        from fastapi import HTTPException
        import runtime_app

        runtime_app._ensure_can_approve = lambda request: (_ for _ in ()).throw(  # type: ignore[attr-defined]
            HTTPException(status_code=403, detail="This action requires steward or admin permissions.")
        )
        payload_model = classification_api.ClassificationReviewPayload(
            decision="approved", note="looks good"
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_review_classification_recommendation(
                    "r1", payload_model, request=SimpleNamespace(headers={})
                )
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_review_audit_includes_http_request_id_and_reviewer_role(self) -> None:
        payload_model = classification_api.ClassificationReviewPayload(
            decision="rejected", note="false positive"
        )
        response = asyncio.run(
            classification_api.api_review_classification_recommendation(
                "r1", payload_model, request=SimpleNamespace(headers={})
            )
        )

        body = _parse_response(response)
        self.assertTrue(body["ok"])
        self.assertEqual(self.store.audit_events[-1]["request_id"], "test-request-id")
        self.assertEqual(self.store.audit_events[-1]["actor_role"], "steward")

    def test_missing_recommendation_returns_404(self) -> None:
        from fastapi import HTTPException

        payload_model = classification_api.ClassificationReviewPayload(
            decision="approved", note=""
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_review_classification_recommendation(
                    "missing", payload_model, request=SimpleNamespace(headers={})
                )
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_review_hidden_asset_recommendation_returns_404_without_writes(self) -> None:
        from fastapi import HTTPException

        self._restore_runtime()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc, openable=False)
        payload_model = classification_api.ClassificationReviewPayload(
            decision="approved", note="looks good"
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_review_classification_recommendation(
                    "r1", payload_model, request=SimpleNamespace(headers={})
                )
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertFalse(self.uc.column_tag_writes)
        self.assertFalse(self.store.audit_events)


class ScanEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore()
        self.uc = FakeUC(
            columns=[
                {"column_name": "ssn", "comment": ""},
                {"column_name": "contact_email", "comment": "GDPR-sensitive email"},
                {"column_name": "created_at", "comment": ""},
            ]
        )
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc)

    def tearDown(self) -> None:
        self._restore_runtime()

    def test_scan_generates_recommendations(self) -> None:
        response = asyncio.run(
            classification_api.api_scan_classification_recommendations(
                asset_fqn="main.sales.customers", request=SimpleNamespace(headers={})
            )
        )
        payload = _parse_response(response)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["scanned"], 3)
        self.assertGreaterEqual(payload["generated"], 2)
        # Audit rows recorded for each persisted recommendation.
        self.assertGreaterEqual(
            sum(
                1
                for ev in self.store.audit_events
                if ev["action"] == "classification_recommended"
            ),
            2,
        )

    def test_scan_rejects_invalid_fqn(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_scan_classification_recommendations(
                    asset_fqn="not_a_fqn", request=SimpleNamespace(headers={})
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_scan_requires_open_asset_before_uc_enumeration(self) -> None:
        from fastapi import HTTPException

        self._restore_runtime()
        self._restore_runtime = _install_fake_runtime_app(self.store, self.uc, openable=False)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                classification_api.api_scan_classification_recommendations(
                    asset_fqn="main.sales.customers", request=SimpleNamespace(headers={})
                )
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.uc.column_reads, 0)


class RouterShapeTests(unittest.TestCase):
    def test_router_exposes_expected_routes(self) -> None:
        router = classification_api.build_classification_router()
        paths = {route.path for route in router.routes}
        self.assertIn("/api/classification-recommendations", paths)
        self.assertIn(
            "/api/classification-recommendations/{recommendation_id}", paths
        )
        self.assertIn(
            "/api/classification-recommendations/{recommendation_id}/review", paths
        )
        self.assertIn(
            "/api/classification-recommendations/scan/{asset_fqn:path}", paths
        )


if __name__ == "__main__":
    unittest.main()
