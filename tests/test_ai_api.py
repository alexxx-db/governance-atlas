"""/api/ai contract tests (DESIGN.md 9): role gates, malformed ids, honest
availability (degraded or unavailable, never an authoritative empty),
reader/steward config exposure, and fail-closed audit on every mutation."""

from __future__ import annotations

import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI, HTTPException

from atlas.ai import models
from atlas.ai.store import AiStore
from atlas.api import ai as ai_api
from test_ai_store import FakeGovernanceStore, FakeUC

EP_ID = models.ai_entity_id("serving_endpoint", "databricks", "ep1")
EXT_ID = models.ai_entity_id("external_model", "databricks", "ep1/claude")
FINDING_ID = "a" * 64


def _obs(kind: str, sid: str, **kw: Any) -> Dict[str, Any]:
    return {
        "entity_kind": kind, "source_system": "databricks", "source_entity_id": sid,
        "display_name": kw.get("name", sid), "owner": "owner@example.com", "platform": kw.get("platform", "databricks"),
        "provider": kw.get("provider"), "model_family": kw.get("model_family"), "tags_json": kw.get("tags", {}),
        "config_json": kw.get("config", {"ai_gateway": {"usage_tracking_config": {"enabled": True}}}),
        "relationships_json": [], "parent_source_entity_id": kw.get("parent"), "provenance_class": "organic",
        "sample_run_id": None, "run_id": "run-2", "collector": "dbx_ai_collector", "collector_version": "1.0.0",
        "observed_at": "2026-09-24T06:00:00+00:00",
    }


class FakeAi:
    def __init__(self, *, runs: List[Dict[str, Any]], succeeded: Dict[str, Any] | None) -> None:
        self.runs, self.succeeded = runs, succeeded

    def list_runs(self, limit=20):
        return self.runs[:limit]

    def latest_succeeded_run(self):
        return self.succeeded

    def observations_for_run(self, run_id):
        return [
            _obs("serving_endpoint", "ep1", name="chat-claude", tags={"ai_risk_tier": "high"}),
            _obs("external_model", "ep1/claude", parent="ep1", provider="anthropic", model_family="claude", platform="external",
                 config={"credentials": {"observable": False}, "provider": "anthropic"}),
            _obs("mcp_server", "conn1", name="docs-mcp"),
        ]

    def ai_registry_rows(self):
        return {EP_ID: {"reconciliation_state": "matched", "reconciliation_confidence": 1.0}}

    def open_findings_by_entity(self):
        return {EP_ID: 2}

    def list_control_results(self, run_id, entity_id=None):
        rows = [
            {"entity_id": EP_ID, "entity_kind": "serving_endpoint", "control_id": "AIC-04", "status": "pass", "signal_source": "serving_endpoints", "evidence_json": {}, "run_id": run_id},
            {"entity_id": EXT_ID, "entity_kind": "external_model", "control_id": "AIC-09", "status": "unknown", "signal_source": "serving_endpoints", "evidence_json": {"reason": "credential configuration is not exposed by the serving API"}, "run_id": run_id},
        ]
        return [r for r in rows if entity_id in (None, r["entity_id"])]

    def finding_counts(self):
        return [
            {"finding_type": "found_not_registered", "severity": "high", "state": "open", "n": 3},
            {"finding_type": "rejected_but_running", "severity": "critical", "state": "open", "n": 1},
            {"finding_type": "ambiguous_match", "severity": "low", "state": "acknowledged", "n": 2},
            {"finding_type": "found_not_registered", "severity": "high", "state": "suppressed", "n": 5},
        ]

    def list_findings(self, **kwargs):
        return []

    def count_findings(self, **kwargs):
        return 0

    def list_intake_records(self):
        return [{"intake_id": "INT-1", "title": "Claims", "state": "approved", "owner_email": "owner@example.com", "provider": "openai", "risk_tier": "high", "source_system": "csv", "ingest_source": "csv", "ingest_run_id": "csv-1"}]

    def list_relationships(self, entity_id=None, kinds=()):
        rel = {"relationship_kind": "declares", "source_entity_id": "intake:INT-1", "target_entity_id": EP_ID, "authority_source": "registry"}
        return [rel] if entity_id in (None, EP_ID) else []

    def not_found_intake_ids(self):
        return set()

    def list_entity_events(self, ids, limit=50):
        return [{"event_id": "e1", "event_type": "ai.registry.state_changed", "actor_email": "collector", "source": "system", "status": "emitted", "request_id": None, "occurred_at": "2026-09-24", "before_json": {}, "after_json": {"reconciliationState": "matched"}}]


SUCCEEDED = {
    "run_id": "run-2", "status": "succeeded", "counts_json": {"units": 2},
    "sources_json": {
        "serving_endpoints": {"state": "available", "reason": ""},
        "registered_models": {"state": "degraded", "reason": "3 model(s) unreadable"},
    },
}


def _runtime(role: str, email: str = "user@example.com") -> ModuleType:
    module = ModuleType("runtime_app")

    def _ensure_can_approve(request):
        if role not in {"steward", "admin"}:
            raise HTTPException(status_code=403, detail="This action requires steward or admin permissions.")
        return email

    module._ensure_live_runtime = lambda: None
    module._ensure_can_approve = _ensure_can_approve
    module._user_role_slug = lambda request: role
    module._config = lambda: SimpleNamespace(ai_tier_tag_key="ai_risk_tier")
    return module


def _request() -> Any:
    return SimpleNamespace(headers={}, state=SimpleNamespace(http_request_id="req-7"))


def _body(response) -> Dict[str, Any]:
    return json.loads(response.body)


def _inventory(**overrides: Any):
    args = dict(kind="", provider="", platform="", tier="", state="", hasOpenFindings=None, q="", sort="findings", limit=50, offset=0)
    args.update(overrides)
    return ai_api.api_ai_inventory(_request(), **args)


def api_paths(app: FastAPI) -> Dict[str, set]:
    """Paths from the OpenAPI schema: FastAPI >= 0.13x keeps included routers
    as _IncludedRouter entries without .path, so app.routes can't be trusted."""
    return {path: set(ops) for path, ops in app.openapi().get("paths", {}).items()}


class ReadRouteTests(unittest.TestCase):
    def _with(self, fake: Any, role: str = "reader"):
        return patch.multiple(ai_api, _ai_store=lambda: fake), patch.dict(sys.modules, {"runtime_app": _runtime(role)})

    def test_no_run_is_unavailable_not_zero(self) -> None:
        a, b = self._with(FakeAi(runs=[], succeeded=None))
        with a, b:
            body = _body(ai_api.api_ai_summary(_request()))
            inv = _body(_inventory())
        self.assertEqual(body["meta"]["state"], "unavailable")
        self.assertIn("No AI reconciliation run has completed yet", body["meta"]["unavailableReason"])
        self.assertIsNone(body["summary"]["assetCount"])
        self.assertIsNone(body["summary"]["shadowAi"])
        self.assertIsNone(inv["total"])
        self.assertEqual(inv["items"], [])

    def test_degraded_source_is_degraded_with_named_reason(self) -> None:
        a, b = self._with(FakeAi(runs=[{"run_id": "run-3", "status": "failed", "failure_reason": "boom"}], succeeded=SUCCEEDED))
        with a, b:
            body = _body(ai_api.api_ai_summary(_request()))
        self.assertEqual(body["meta"]["state"], "degraded")
        self.assertTrue(body["authoritative"])  # real observed data, just incomplete
        warnings = " | ".join(body["meta"]["warnings"])
        self.assertIn("registered_models was degraded", warnings)
        self.assertIn("Latest run run-3 failed (boom)", warnings)
        summary = body["summary"]
        self.assertEqual(summary["assetCount"], 3)
        self.assertEqual(summary["shadowAi"], 4)  # open found_not_registered + rejected_but_running
        self.assertEqual(summary["ambiguousMatches"], 2)
        self.assertEqual(summary["findings"]["open"], 6)  # suppressed excluded

    def test_inventory_filters_sort_pagination_provenance(self) -> None:
        a, b = self._with(FakeAi(runs=[SUCCEEDED], succeeded={**SUCCEEDED, "sources_json": {"serving_endpoints": {"state": "available"}}}))
        with a, b:
            body = _body(_inventory(limit=2))
            ext = _body(_inventory(kind="external_model", sort="name"))
        self.assertEqual(body["meta"]["state"], "available")
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["entityId"], EP_ID)  # most open findings first
        self.assertEqual(body["items"][0]["tier"], "high")
        self.assertEqual(body["items"][0]["provenance"]["runId"], "run-2")
        self.assertEqual(body["items"][0]["provenance"]["collector"], "dbx_ai_collector")
        self.assertEqual([i["entityKind"] for i in ext["items"]], ["external_model"])

    def test_bad_sort_and_malformed_ids(self) -> None:
        a, b = self._with(FakeAi(runs=[], succeeded=None), role="steward")
        with a, b:
            for call in (
                lambda: _inventory(sort="evil"),
                lambda: ai_api.api_ai_asset("not-an-id", _request()),
                lambda: ai_api.api_ai_asset_controls("'; DROP", _request()),
                lambda: ai_api.api_ai_finding_patch("abc", ai_api.FindingPatch(action="acknowledge"), _request()),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    call()
                self.assertEqual(ctx.exception.status_code, 400)

    def test_asset_detail_reader_vs_steward_config(self) -> None:
        fake = FakeAi(runs=[SUCCEEDED], succeeded=SUCCEEDED)
        a, b = self._with(fake, role="reader")
        with a, b:
            reader = _body(ai_api.api_ai_asset(EP_ID, _request()))["asset"]
        a, b = self._with(fake, role="steward")
        with a, b:
            steward = _body(ai_api.api_ai_asset(EP_ID, _request()))["asset"]
        self.assertNotIn("config", reader)
        self.assertIn("config", steward)
        self.assertEqual(reader["declared"]["intakeId"], "INT-1")
        provider = next(d for d in reader["diff"] if d["field"] == "provider")
        self.assertEqual(provider["declared"], "openai")
        self.assertEqual(reader["history"][0]["eventType"], "ai.registry.state_changed")
        self.assertEqual(reader["controls"][0]["title"], "AI Gateway usage tracking enabled")
        # The endpoint's model family comes from its served model.
        family = next(d for d in reader["diff"] if d["field"] == "model_family")
        self.assertEqual(family["observed"], "claude")

    def test_readers_never_receive_findings_on_asset_360(self) -> None:
        fake = FakeAi(runs=[SUCCEEDED], succeeded=SUCCEEDED)
        fake.list_findings = lambda **kw: [{"finding_id": "f" * 64, "finding_type": "found_different", "assignee_email": "x@y.z", "suppression_reason": "secret reason", "match_score": "0.9"}]
        a, b = self._with(fake, role="reader")
        with a, b:
            reader = _body(ai_api.api_ai_asset(EP_ID, _request()))["asset"]
        a, b = self._with(fake, role="steward")
        with a, b:
            steward = _body(ai_api.api_ai_asset(EP_ID, _request()))["asset"]
        self.assertIsNone(reader["findings"])
        self.assertNotIn("secret reason", json.dumps(reader))
        self.assertEqual(steward["findings"][0]["matchScore"], 0.9)  # number, not "0.9"
        self.assertIsInstance(steward["confidence"], float)

    def test_external_model_controls_show_unknown_with_reason(self) -> None:
        a, b = self._with(FakeAi(runs=[SUCCEEDED], succeeded=SUCCEEDED))
        with a, b:
            body = _body(ai_api.api_ai_asset_controls(EXT_ID, _request()))
        self.assertEqual(body["controls"][0]["status"], "unknown")
        self.assertIn("not exposed", body["controls"][0]["evidence"]["reason"])

    def test_missing_asset_404(self) -> None:
        a, b = self._with(FakeAi(runs=[SUCCEEDED], succeeded=SUCCEEDED))
        with a, b:
            with self.assertRaises(HTTPException) as ctx:
                ai_api.api_ai_asset("b" * 32, _request())
        self.assertEqual(ctx.exception.status_code, 404)

    def test_findings_are_steward_only(self) -> None:
        a, b = self._with(FakeAi(runs=[], succeeded=None), role="reader")
        with a, b:
            with self.assertRaises(HTTPException) as ctx:
                ai_api.api_ai_findings(_request())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_intake_link_status(self) -> None:
        a, b = self._with(FakeAi(runs=[SUCCEEDED], succeeded=SUCCEEDED))
        with a, b:
            body = _body(ai_api.api_ai_intake(_request()))
        self.assertEqual(body["items"][0]["linkStatus"], "linked")
        self.assertEqual(body["items"][0]["provenance"]["ingestSource"], "csv")


class AvailabilityNotesTests(unittest.TestCase):
    def test_known_gaps_are_notes_not_degradation(self) -> None:
        from atlas.ai import views

        run = {**SUCCEEDED, "sources_json": {
            "serving_endpoints": {"state": "available"},
            "registered_models": {"state": "available"},
            "ai_asset_registry": {"state": "not_supported", "reason": "No AI asset registry API"},
            "uc_function_tools": {"state": "not_configured", "reason": "No tool schemas configured"},
        }}
        avail = views.availability(FakeAi(runs=[run], succeeded=run))
        self.assertEqual(avail["state"], "available")
        self.assertEqual(avail["warnings"], [])
        self.assertEqual(len(avail["notes"]), 2)
        self.assertIn("not supported", avail["notes"][0])


class MutationRouteTests(unittest.TestCase):
    def _real_store(self, **uc_kwargs: Any):
        finding = pd.DataFrame([{"finding_id": FINDING_ID, "finding_type": "ambiguous_match", "state": "open", "entity_id": EP_ID, "entity_kind": "serving_endpoint"}])
        intake = pd.DataFrame([{"intake_id": "INT-1", "title": "t"}])
        uc = FakeUC(frames={"WHERE finding_id IN": finding, "FROM `main`.`atlas`.`intake_records` ORDER BY": intake}, **uc_kwargs)
        return uc, AiStore(FakeGovernanceStore(uc))

    def _call(self, fn, store, role="steward"):
        with patch.multiple(ai_api, _ai_store=lambda: store), patch.dict(sys.modules, {"runtime_app": _runtime(role, "steward@example.com")}):
            return fn()

    def test_patch_role_gate_and_validation(self) -> None:
        uc, store = self._real_store()
        with self.assertRaises(HTTPException) as ctx:
            self._call(lambda: ai_api.api_ai_finding_patch(FINDING_ID, ai_api.FindingPatch(action="acknowledge"), _request()), store, role="writer")
        self.assertEqual(ctx.exception.status_code, 403)
        for payload in (ai_api.FindingPatch(action="suppress"), ai_api.FindingPatch(action="resolve"), ai_api.FindingPatch(action="assign", assigneeEmail="nope"), ai_api.FindingPatch(action="explode")):
            with self.assertRaises(HTTPException) as ctx:
                self._call(lambda: ai_api.api_ai_finding_patch(FINDING_ID, payload, _request()), store)
            self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(uc.executed, [])

    def test_patch_audits_with_request_id(self) -> None:
        uc, store = self._real_store()
        response = self._call(lambda: ai_api.api_ai_finding_patch(FINDING_ID, ai_api.FindingPatch(action="suppress", reason="Known pilot <b>x</b>"), _request()), store)
        self.assertEqual(_body(response)["finding"]["state"], "suppressed")
        self.assertTrue(any("'ai.finding.updated'" in sql and "'req-7'" in sql and "'steward@example.com'" in sql for sql in uc.executed))
        self.assertTrue(any("&lt;b&gt;" in sql for sql in uc.executed if sql.startswith("UPDATE")))

    def test_patch_audit_failure_blocks_update(self) -> None:
        uc, store = self._real_store(fail_on="metadata_audit_log")
        with self.assertRaises(RuntimeError):
            self._call(lambda: ai_api.api_ai_finding_patch(FINDING_ID, ai_api.FindingPatch(action="acknowledge"), _request()), store)
        self.assertFalse([sql for sql in uc.executed if sql.startswith("UPDATE")])

    def test_confirm_match(self) -> None:
        uc, store = self._real_store()
        with self.assertRaises(HTTPException) as ctx:
            self._call(lambda: ai_api.api_ai_finding_confirm_match(FINDING_ID, ai_api.ConfirmMatchRequest(intakeId="INT-404"), _request()), store)
        self.assertEqual(ctx.exception.status_code, 400)
        response = self._call(lambda: ai_api.api_ai_finding_confirm_match(FINDING_ID, ai_api.ConfirmMatchRequest(intakeId="INT-1", note="checked"), _request()), store)
        self.assertEqual(_body(response)["finding"]["state"], "resolved")
        self.assertTrue(any("'ai.finding.match_confirmed'" in sql for sql in uc.executed))
        self.assertTrue(any("entity_relationships" in sql and "'override'" in sql for sql in uc.executed))

    def test_confirm_match_audit_failure_writes_nothing(self) -> None:
        uc, store = self._real_store(fail_on="metadata_audit_log")
        with self.assertRaises(RuntimeError):
            self._call(lambda: ai_api.api_ai_finding_confirm_match(FINDING_ID, ai_api.ConfirmMatchRequest(intakeId="INT-1"), _request()), store)
        self.assertFalse([sql for sql in uc.executed if "entity_relationships" in sql or sql.startswith("UPDATE")])

    def test_concurrent_change_returns_409_and_confirm_writes_no_link(self) -> None:
        conflict = {"SET state_changed_by": pd.DataFrame([{"num_affected_rows": 0}])}
        for call in (
            lambda: ai_api.api_ai_finding_patch(FINDING_ID, ai_api.FindingPatch(action="acknowledge"), _request()),
            lambda: ai_api.api_ai_finding_confirm_match(FINDING_ID, ai_api.ConfirmMatchRequest(intakeId="INT-1"), _request()),
        ):
            uc, store = self._real_store()
            uc.frames.update(conflict)
            with self.assertRaises(HTTPException) as ctx:
                self._call(call, store)
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertFalse([sql for sql in uc.executed if "entity_relationships" in sql and sql.startswith("MERGE")])

    def test_confirm_only_for_matchable_findings(self) -> None:
        finding = pd.DataFrame([{"finding_id": FINDING_ID, "finding_type": "rejected_but_running", "state": "open", "entity_id": EP_ID}])
        uc = FakeUC(frames={"WHERE finding_id IN": finding})
        with self.assertRaises(HTTPException) as ctx:
            self._call(lambda: ai_api.api_ai_finding_confirm_match(FINDING_ID, ai_api.ConfirmMatchRequest(intakeId="INT-1"), _request()), AiStore(FakeGovernanceStore(uc)))
        self.assertEqual(ctx.exception.status_code, 409)


class RegistrationTests(unittest.TestCase):
    def test_flag_on_registers_all_routes(self) -> None:
        import runtime_app

        target = FastAPI()
        self.assertTrue(runtime_app._register_ai_router(target, True))
        paths = {p: ops for p, ops in api_paths(target).items() if p.startswith("/api/ai")}
        self.assertEqual(sum(len(ops) for ops in paths.values()), 10)
        self.assertEqual(paths["/api/ai/findings/{finding_id}"], {"patch"})
        self.assertEqual(paths["/api/ai/intake/import"], {"post"})


if __name__ == "__main__":
    unittest.main()
