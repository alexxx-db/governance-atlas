from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from axiom.api import axiom as axiom_api
from axiom.api import assets as assets_api
from axiom.api import classification as classification_api
from axiom.api import governance as governance_api


class JsonRequest:
    def __init__(self, payload: dict, request_id: str = "sanitize-request-id") -> None:
        self._payload = payload
        self.headers = {"X-AXIOM-Client-Request-ID": request_id}
        self.state = SimpleNamespace(http_request_id=request_id)
        self.url = SimpleNamespace(path="/api/governance/requests")

    async def json(self) -> dict:
        return self._payload


class SanitizationContractTests(unittest.TestCase):
    def test_asset_description_escapes_raw_html_and_strips_controls(self) -> None:
        payload = assets_api.AssetDescriptionPatch(description="<script>alert(1)</script>\x00")

        self.assertEqual(payload.description, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_tag_payload_rejects_unsupported_key_characters(self) -> None:
        with self.assertRaises(ValidationError):
            assets_api.AssetTagsPatch(tags={"bad key!": "value"})

    def test_glossary_definition_rejects_javascript_markdown_links(self) -> None:
        with self.assertRaises(ValidationError):
            governance_api.GlossaryTermUpsert(
                name="Customer Identifier",
                definition="[click](javascript:alert(1))",
            )

    def test_governance_status_review_note_is_sanitized(self) -> None:
        payload = governance_api.GovernanceRequestStatusPatch(
            status="approved",
            reviewNote="Looks good <img src=x onerror=alert(1)>",
        )

        self.assertIn("&lt;img", payload.reviewNote)
        self.assertNotIn("<img", payload.reviewNote)

    def test_classification_review_note_is_sanitized(self) -> None:
        payload = classification_api.ClassificationReviewPayload(
            decision="rejected",
            note="<b>false positive</b>",
        )

        self.assertEqual(payload.note, "&lt;b&gt;false positive&lt;/b&gt;")

    def test_axiom_ai_question_strips_controls(self) -> None:
        payload = axiom_api.AxiomAiQuestion(question="Which assets?\x00\u202e")

        self.assertEqual(payload.question, "Which assets?")

    def test_governance_request_route_persists_sanitized_title_and_note(self) -> None:
        captured: dict = {}

        class Store:
            def create_change_request(self, **kwargs):
                captured.update(kwargs)
                return "REQ-SAFE"

        request = JsonRequest(
            {
                "assetFqn": "main.customer.customer_dim",
                "title": "Review <script>owner</script>",
                "note": "Add <b>business owner</b>\x00",
            }
        )

        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _ensure_can_mutate=lambda _request: "writer@example.com",
            _user_role_slug=lambda _request: "writer",
            _store=lambda: Store(),
            _asset_is_openable=lambda *_args, **_kwargs: True,
            _asset_detail_payload=lambda *_args, **_kwargs: {"fqn": "main.customer.customer_dim"},
            _governance_summary=lambda _request: {"backlog": []},
        ):
            response = asyncio.run(governance_api.api_governance_create_request(request))

        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;script&gt;owner&lt;/script&gt;", captured["new_comment"])
        self.assertIn("&lt;b&gt;business owner&lt;/b&gt;", captured["new_comment"])
        self.assertNotIn("<script>", captured["new_comment"])
        self.assertNotIn("\x00", captured["new_comment"])

    def test_governance_request_fast_response_omits_heavy_refetch(self) -> None:
        class Store:
            def create_change_request(self, **_kwargs):
                return "REQ-FAST"

        request = JsonRequest(
            {
                "assetFqn": "main.customer.customer_dim",
                "title": "Lineage impact review",
                "note": "Review downstream dependencies.",
            }
        )

        import runtime_app

        with patch.multiple(
            runtime_app,
            _ensure_live_runtime=lambda: None,
            _ensure_can_mutate=lambda _request: "writer@example.com",
            _user_role_slug=lambda _request: "writer",
            _store=lambda: Store(),
            _asset_is_openable=lambda *_args, **_kwargs: True,
            _asset_detail_payload=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("asset refetch called")),
            _governance_summary=lambda _request: (_ for _ in ()).throw(AssertionError("summary refetch called")),
        ):
            response = asyncio.run(governance_api.api_governance_create_request(request, fast=True))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.body.decode("utf-8")),
            {
                "ok": True,
                "requestId": "REQ-FAST",
                "assetFqn": "main.customer.customer_dim",
            },
        )


if __name__ == "__main__":
    unittest.main()
