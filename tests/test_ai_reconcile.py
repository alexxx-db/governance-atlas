"""Reconciliation rules, table-driven (DESIGN.md sections 5 and 6)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from atlas.ai import controls, models, reconcile

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ALL_AVAILABLE = {name: {"state": "available"} for name in ("serving_endpoints", "registered_models", "mcp_connections", "uc_function_tools")}


def obs(kind: str, sid: str, **kw: Any) -> Dict[str, Any]:
    row = {
        "entity_kind": kind,
        "source_system": "databricks",
        "source_entity_id": sid,
        "display_name": kw.pop("name", sid),
        "owner": kw.pop("owner", "owner@example.com"),
        "platform": kw.pop("platform", "databricks"),
        "provider": kw.pop("provider", None),
        "model_family": kw.pop("model_family", None),
        "tags_json": kw.pop("tags", {}),
        "config_json": kw.pop("config", {}),
        "relationships_json": kw.pop("relationships", []),
        "parent_source_entity_id": kw.pop("parent", None),
        "provenance_class": "organic",
        "run_id": "run-1",
        "collector": "dbx_ai_collector",
        "collector_version": "1.0.0",
        "observed_at": NOW.isoformat(),
    }
    row.update(kw)
    return row


def intake(intake_id: str, **kw: Any) -> Dict[str, Any]:
    row = {
        "intake_id": intake_id,
        "title": kw.pop("title", "Claims summarizer"),
        "state": kw.pop("state", "approved"),
        "owner_email": kw.pop("owner", "owner@example.com"),
        "provider": kw.pop("provider", None),
        "platform": kw.pop("platform", "databricks"),
        "model_family": kw.pop("model_family", None),
        "risk_tier": kw.pop("tier", None),
        "approved_at": kw.pop("approved_at", (NOW - timedelta(days=60)).isoformat()),
    }
    row.update(kw)
    return row


def run(observations: List[Dict[str, Any]], intakes: List[Dict[str, Any]], **kw: Any) -> reconcile.ReconcileResult:
    return reconcile.reconcile(
        observations,
        intakes,
        aliases=kw.pop("aliases", {}),
        active_findings=kw.pop("active", []),
        sources=kw.pop("sources", ALL_AVAILABLE),
        intake_tag_key="edw_intake_id",
        tier_tag_key="ai_risk_tier",
        grace_days=kw.pop("grace_days", 30),
        now=NOW,
    )


def types(result: reconcile.ReconcileResult) -> List[str]:
    return sorted(f.finding_type for f in result.findings)


class MatchingTests(unittest.TestCase):
    def test_m1_tag_match(self) -> None:
        res = run([obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-1"})], [intake("INT-1")])
        state = res.units[0]
        self.assertEqual((state.match.rule, state.match.score, state.match.state), ("M1", 1.0, "matched"))
        self.assertEqual(state.reconciliation_state, "matched")
        self.assertEqual(res.declares[0][0], "INT-1")

    def test_m2_alias_wins_over_tag(self) -> None:
        o = obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-1"})
        eid = models.ai_entity_id("serving_endpoint", "databricks", "ep1")
        res = run([o], [intake("INT-1"), intake("INT-2", title="other")], aliases={eid: "INT-2"})
        self.assertEqual((res.units[0].match.rule, res.units[0].match.intake_id), ("M2", "INT-2"))

    def test_m3_boundaries(self) -> None:
        cases = [
            ("claims summarizer", "Claims summarizer", "matched", 0.90),  # exact normalized name
            ("claims-summarizr", "Claims summarizer", "ambiguous", None),  # >= 0.85, < 1.0
            ("fraud scorer", "Claims summarizer", "unmatched", 0.0),  # below 0.85
        ]
        for name, title, expected, score in cases:
            res = run([obs("serving_endpoint", "ep1", name=name)], [intake("INT-1", title=title)])
            match = res.units[0].match
            self.assertEqual(match.state, expected, name)
            if score is not None:
                self.assertEqual(match.score, score, name)
            if expected == "ambiguous":
                self.assertTrue(0.70 <= match.score < 0.90)

    def test_m3_score_function(self) -> None:
        self.assertEqual(reconcile.m3_score(0.85), 0.70)
        self.assertEqual(reconcile.m3_score(1.0), 0.90)
        self.assertAlmostEqual(reconcile.m3_score(0.925), 0.80, places=4)

    def test_m3_requires_owner_and_platform_or_provider(self) -> None:
        res = run([obs("serving_endpoint", "ep1", name="claims summarizer", owner="x@example.com")], [intake("INT-1")])
        self.assertEqual(res.units[0].match.state, "unmatched")
        res = run([obs("serving_endpoint", "ep1", name="claims summarizer", platform="external")], [intake("INT-1", platform="aws")])
        self.assertEqual(res.units[0].match.state, "unmatched")

    def test_tied_m3_candidates_are_ambiguous(self) -> None:
        res = run([obs("serving_endpoint", "ep1", name="claims summarizer")], [intake("INT-1"), intake("INT-2")])
        self.assertEqual(res.units[0].match.state, "ambiguous")


class FindingRuleTests(unittest.TestCase):
    def test_found_not_registered_severity(self) -> None:
        ep = obs("serving_endpoint", "ep1", relationships=[{"kind": "serves", "target_kind": "external_model", "target_source_entity_id": "ep1/c"}])
        ext = obs("external_model", "ep1/c", parent="ep1", provider="anthropic", platform="external")
        res = run([ep, ext], [])
        self.assertEqual(types(res), ["found_not_registered"])  # one finding, on the parent
        self.assertEqual(res.findings[0].severity, "high")
        res = run([obs("ai_model", "main.ml.m")], [])
        self.assertEqual(res.findings[0].severity, "medium")

    def test_rejected_but_running(self) -> None:
        res = run([obs("agent", "a1", tags={"edw_intake_id": "INT-9"})], [intake("INT-9", state="rejected")])
        self.assertIn("rejected_but_running", types(res))
        self.assertEqual(next(f for f in res.findings if f.finding_type == "rejected_but_running").severity, "critical")

    def test_registered_not_found_grace_and_availability(self) -> None:
        old = intake("INT-5", approved_at=(NOW - timedelta(days=31)).isoformat())
        new = intake("INT-6", approved_at=(NOW - timedelta(days=5)).isoformat())
        res = run([], [old, new])
        self.assertEqual([(f.finding_type, f.intake_id) for f in res.findings], [("registered_not_found", "INT-5")])
        degraded = {**ALL_AVAILABLE, "registered_models": {"state": "degraded"}}
        self.assertEqual(run([], [old], sources=degraded).findings, [])

    def test_found_different(self) -> None:
        ep = obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-1", "ai_risk_tier": "high"})
        ext = obs("external_model", "ep1/c", parent="ep1", provider="openai", model_family="gpt-4o", platform="external")
        res = run([ep, ext], [intake("INT-1", provider="anthropic", model_family="claude", tier="high")])
        finding = next(f for f in res.findings if f.finding_type == "found_different")
        self.assertEqual(finding.severity, "high")
        self.assertEqual({d["field"] for d in finding.evidence["differences"]}, {"provider", "model_family"})
        tier_only = run([obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-1", "ai_risk_tier": "low"})], [intake("INT-1", tier="high")])
        self.assertEqual(next(f for f in tier_only.findings if f.finding_type == "found_different").severity, "medium")

    def test_ambiguous_match_finding_and_rnf_suppressed(self) -> None:
        res = run([obs("serving_endpoint", "ep1", name="claims-summarizr")], [intake("INT-1")])
        self.assertEqual(types(res), ["ambiguous_match"])  # the candidate intake is not "not found"
        self.assertEqual(res.findings[0].evidence["candidates"][0]["intakeId"], "INT-1")

    def test_evidence_carries_provenance(self) -> None:
        f = run([obs("mcp_server", "conn1")], []).findings[0]
        self.assertEqual(f.evidence["provenance"]["runId"], "run-1")
        self.assertEqual(f.evidence["provenance"]["collector"], "dbx_ai_collector")


class LifecycleTests(unittest.TestCase):
    def test_idempotent_finding_ids(self) -> None:
        inputs = ([obs("mcp_server", "c1"), obs("agent", "a1", tags={"edw_intake_id": "INT-2"})], [intake("INT-2", state="rejected")])
        first = sorted(f.finding_id for f in run(*inputs).findings)
        second = sorted(f.finding_id for f in run(*inputs).findings)
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_auto_resolve_and_blind_sources(self) -> None:
        stale = [
            {"finding_id": "gone-endpoint", "finding_type": "found_not_registered", "entity_kind": "serving_endpoint"},
            {"finding_id": "gone-model", "finding_type": "found_not_registered", "entity_kind": "ai_model"},
            {"finding_id": "old-rnf", "finding_type": "registered_not_found", "entity_kind": None},
        ]
        res = run([], [], active=stale)
        self.assertEqual(sorted(res.resolve_ids), ["gone-endpoint", "gone-model", "old-rnf"])
        blind = {**ALL_AVAILABLE, "registered_models": {"state": "unavailable"}}
        res = run([], [], active=stale, sources=blind)
        self.assertEqual(res.resolve_ids, ["gone-endpoint"])  # models unseen, core not available

    def test_confirmation_becomes_deterministic_next_run(self) -> None:
        o = obs("serving_endpoint", "ep1", name="claims-summarizr")
        first = run([o], [intake("INT-1")])
        self.assertEqual(first.units[0].match.state, "ambiguous")
        eid = first.units[0].asset.entity_id
        second = run([o], [intake("INT-1")], aliases={eid: "INT-1"}, active=[{"finding_id": f.finding_id, "finding_type": f.finding_type, "entity_kind": f.entity_kind} for f in first.findings])
        self.assertEqual((second.units[0].match.rule, second.units[0].match.state), ("M2", "matched"))
        self.assertEqual(second.findings, [])
        self.assertEqual(sorted(second.resolve_ids), sorted(f.finding_id for f in first.findings))

    def test_children_inherit_registry_state(self) -> None:
        res = run(
            [obs("ai_model", "main.ml.m", tags={}), obs("ai_model_version", "main.ml.m@1", parent="main.ml.m")],
            [],
        )
        states = {a.entity_kind: s for a, s, _ in res.registry}
        self.assertEqual(states, {"ai_model": "orphaned", "ai_model_version": "orphaned"})

    def test_pending_intake_state(self) -> None:
        res = run([obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-3"})], [intake("INT-3", state="submitted")])
        self.assertEqual(res.units[0].reconciliation_state, "pending_intake")


class ControlTests(unittest.TestCase):
    def _ctx(self, kind: str, **kw: Any) -> controls.AssetContext:
        return controls.AssetContext(
            entity_id="e1", entity_kind=kind, tags=kw.get("tags", {}), config=kw.get("config", {}),
            match_state=kw.get("match_state", "unmatched"), intake=kw.get("intake"),
        )

    def _status(self, control_id: str, ctx: controls.AssetContext) -> Any:
        outcome = controls.CONTROLS[control_id](ctx, {"tier_tag_key": "ai_risk_tier"})
        return outcome.status if outcome else None

    def test_aic_table(self) -> None:
        gw_on = {"ai_gateway": {"usage_tracking_config": {"enabled": True}, "inference_table_config": {"enabled": True}}}
        cases = [
            ("AIC-01", self._ctx("serving_endpoint", match_state="matched", intake={"state": "approved"}), "pass"),
            ("AIC-01", self._ctx("serving_endpoint", match_state="matched", intake={"state": "rejected"}), "fail"),
            ("AIC-01", self._ctx("serving_endpoint", match_state="ambiguous"), "unknown"),
            ("AIC-01", self._ctx("serving_endpoint"), "fail"),
            ("AIC-01", self._ctx("external_model"), None),
            ("AIC-03", self._ctx("serving_endpoint", tags={"ai_risk_tier": "high"}, intake={"risk_tier": "HIGH"}), "pass"),
            ("AIC-03", self._ctx("serving_endpoint", tags={"ai_risk_tier": "low"}, intake={"risk_tier": "high"}), "fail"),
            ("AIC-03", self._ctx("serving_endpoint"), "fail"),
            ("AIC-03", self._ctx("ai_model"), "unknown"),
            ("AIC-04", self._ctx("serving_endpoint", config=gw_on), "pass"),
            ("AIC-04", self._ctx("agent"), "fail"),
            ("AIC-04", self._ctx("mcp_server"), None),
            ("AIC-06", self._ctx("serving_endpoint", config={"ai_gateway": {"inference_table_config": {"enabled": False}}}), "fail"),
            ("AIC-09", self._ctx("external_model", config={"credentials": {"observable": False}}), "unknown"),
            ("AIC-09", self._ctx("external_model", config={"credentials": {"observable": True, "plaintext_fields": ["x_plaintext"]}}), "fail"),
            ("AIC-09", self._ctx("external_model", config={"credentials": {"observable": True, "secret_refs": [{"field": "k", "secret_ref": "s/k"}], "plaintext_fields": []}}), "pass"),
        ]
        for control_id, ctx, expected in cases:
            self.assertEqual(self._status(control_id, ctx), expected, f"{control_id} {ctx}")

    def test_unknown_reason_names_the_source(self) -> None:
        outcome = controls.CONTROLS["AIC-09"](self._ctx("external_model"), {})
        self.assertEqual(outcome.signal_source, "serving_endpoints")
        self.assertIn("not exposed", outcome.evidence["reason"])

    def test_posture_excludes_unknowns(self) -> None:
        R = lambda status: models.ControlResult("e", "k", "AIC", "1", status, "s")  # noqa: E731
        self.assertEqual(controls.posture([R("unknown"), R("unknown")]), "unknown")
        self.assertEqual(controls.posture([R("pass"), R("unknown")]), "strong")
        self.assertEqual(controls.posture([R("pass"), R("fail"), R("unknown"), R("unknown")]), "partial")
        self.assertEqual(controls.posture([R("fail"), R("fail"), R("pass")]), "weak")

    def test_reconcile_emits_controls_for_children(self) -> None:
        ep = obs("serving_endpoint", "ep1", config={"ai_gateway": {"usage_tracking_config": {"enabled": True}}})
        ext = obs("external_model", "ep1/c", parent="ep1", config={"credentials": {"observable": False}})
        res = run([ep, ext], [])
        by = {(r.entity_kind, r.control_id): r.status for r in res.controls}
        self.assertEqual(by[("external_model", "AIC-09")], "unknown")
        self.assertEqual(by[("serving_endpoint", "AIC-04")], "pass")
        self.assertNotIn(("external_model", "AIC-04"), by)


if __name__ == "__main__":
    unittest.main()


class JobWriteTests(unittest.TestCase):
    """write_result: a steady-state re-run writes no registry rows or
    relationships, but still merges findings (advancing last_seen_at)."""

    def test_second_run_is_cheap_and_idempotent(self) -> None:
        import pandas as pd

        from atlas.ai.jobs.reconcile import write_result
        from atlas.ai.store import AiStore, relationship_id_for
        from test_ai_store import FakeGovernanceStore, FakeUC

        result = run([obs("serving_endpoint", "ep1", tags={"edw_intake_id": "INT-1"}), obs("mcp_server", "c1")], [intake("INT-1")])

        class Gov(FakeGovernanceStore):
            def list_entity_aliases(self, alias_type=None):
                return pd.DataFrame()

        uc = FakeUC()
        gov = Gov(uc)
        counts = write_result(AiStore(gov), result, run_id="run-1", actor="collector", prior_states={})
        self.assertEqual(counts["registryWrites"], 2)
        self.assertEqual(len(gov.registry_calls), 2)
        self.assertEqual(gov.alias_calls[0]["source"], "intake_tag")

        ep = next(s.asset for s in result.units if s.asset.entity_kind == "serving_endpoint")
        rel = pd.DataFrame([{"relationship_id": relationship_id_for("declares", "intake:INT-1", ep.entity_id)}])
        uc2 = FakeUC(frames={"FROM `main`.`atlas`.`entity_relationships`": rel})
        gov2 = Gov(uc2)
        prior = {a.entity_id: s for a, s, _ in result.registry}
        counts2 = write_result(AiStore(gov2), result, run_id="run-2", actor="collector", prior_states=prior)
        self.assertEqual(counts2["registryWrites"], 0)
        self.assertFalse([sql for sql in uc2.executed if sql.startswith("MERGE INTO `main`.`atlas`.`entity_relationships`")])
        self.assertTrue(any(sql.startswith("MERGE INTO `main`.`atlas`.`reconciliation_findings`") for sql in uc2.executed))


class SampleProvenanceTests(unittest.TestCase):
    def test_controls_inherit_asset_provenance(self) -> None:
        o = obs("serving_endpoint", "ep1", provenance_class="sample", sample_run_id="ga-ai-1")
        res = run([o], [])
        self.assertTrue(res.controls)
        self.assertTrue(all(c.provenance_class == "sample" and c.sample_run_id == "ga-ai-1" for c in res.controls))
