"""Intake CSV import: field map, normalization, validation, and the
POST /api/ai/intake/import contract (dry run writes nothing; commit is
steward/admin only, all-or-nothing, and audits every row)."""

from __future__ import annotations

import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from atlas.ai import intake
from test_ai_store import FakeGovernanceStore, FakeUC

GOOD_CSV = """Intake ID,Title,Status,Owner,Vendor,Model,Tier,Approval Date,Cost Center
INT-1,Claims <b>summarizer</b>,Approved,Owner@Example.com,Anthropic,claude-sonnet,high,2026-05-01,CC-9
INT-2,Denied bot,Denied,bob@example.com,OpenAI,gpt-4o,medium,,
"""


class FieldMapTests(unittest.TestCase):
    def test_field_map_loads_and_covers_required(self) -> None:
        fm = intake.load_field_map()
        required = {f.target for f in fm.fields if f.required}
        self.assertEqual(required, {"intake_id", "title", "state", "owner_email"})
        self.assertEqual(fm.state_map["in review"], "submitted")
        self.assertEqual(fm.source_to_target()["vendor"], "provider")


class ValidateCsvTests(unittest.TestCase):
    def test_valid_file_normalizes_and_sanitizes(self) -> None:
        report = intake.validate_csv(GOOD_CSV, ingest_run_id="csv-1")
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"], {"total": 2, "valid": 2, "invalid": 0})
        first, second = report["records"]
        self.assertEqual(first.state, "approved")
        self.assertEqual(second.state, "rejected")
        self.assertEqual(first.owner_email, "owner@example.com")
        self.assertEqual(first.provider, "Anthropic")
        self.assertEqual(first.title, "Claims &lt;b&gt;summarizer&lt;/b&gt;")
        self.assertEqual(first.approved_at.isoformat()[:10], "2026-05-01")
        self.assertEqual(first.attributes, {"cost_center": "CC-9"})
        self.assertEqual((first.ingest_source, first.source_system, first.ingest_run_id), ("csv", "csv", "csv-1"))

    def test_bad_rows_rejected_with_reasons(self) -> None:
        text = "intake_id,title,state,owner\nINT-1,A,approved,not-an-email\n,B,approved,b@x.com\nINT-3,C,maybe,c@x.com\nINT-4,D,approved,d@x.com\nint-4,E,approved,e@x.com\n"
        report = intake.validate_csv(text, ingest_run_id="csv-2")
        self.assertFalse(report["ok"])
        errors = {r["rowNumber"]: r["errors"] for r in report["results"]}
        self.assertIn("email", errors[2][0]["message"])
        self.assertEqual(errors[3][0]["field"], "intake_id")
        self.assertIn("unknown state", errors[4][0]["message"])
        self.assertEqual(errors[5], [])
        self.assertIn("duplicate of row 5", errors[6][0]["message"])
        self.assertEqual(report["summary"], {"total": 5, "valid": 1, "invalid": 4})

    def test_missing_required_column_and_empty(self) -> None:
        self.assertIn("state", intake.validate_csv("intake_id,title,owner\nX,Y,z@x.com\n", ingest_run_id="c")["parseErrors"][0]["message"])
        self.assertEqual(intake.validate_csv("   ", ingest_run_id="c")["parseErrors"][0]["message"], "CSV is empty.")

    def test_row_cap(self) -> None:
        rows = "".join(f"I{i},t,approved,a@b.co\n" for i in range(intake.MAX_ROWS_PER_REQUEST + 2))
        report = intake.validate_csv("intake_id,title,state,owner\n" + rows, ingest_run_id="c")
        self.assertEqual(report["rowCount"], intake.MAX_ROWS_PER_REQUEST)
        self.assertIn("row limit", report["parseErrors"][0]["message"])
        self.assertFalse(report["ok"])


def _fake_runtime(role: str, uc: FakeUC) -> ModuleType:
    module = ModuleType("runtime_app")

    def _ensure_can_approve(request):
        if role not in {"steward", "admin"}:
            raise HTTPException(status_code=403, detail="This action requires steward or admin permissions.")
        return "steward@example.com"

    module._ensure_live_runtime = lambda: None
    module._ensure_can_approve = _ensure_can_approve
    module._user_role_slug = lambda request: role
    module._ensure_governance_store = lambda: None
    module._store = lambda: FakeGovernanceStore(uc)
    return module


def _call(role: str, csv_text: str, mode: str, uc: FakeUC):
    from atlas.api import ai as ai_api

    request = SimpleNamespace(headers={"x-request-id": "req-1"}, state=SimpleNamespace(http_request_id="req-1"))
    with patch.dict(sys.modules, {"runtime_app": _fake_runtime(role, uc)}):
        return ai_api.api_ai_intake_import(ai_api.IntakeImportRequest(csvText=csv_text), request, mode=mode)


class IntakeImportApiTests(unittest.TestCase):
    def test_dry_run_writes_nothing(self) -> None:
        uc = FakeUC()
        response = _call("steward", GOOD_CSV, "dry_run", uc)
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertIsNone(body["committed"])
        self.assertNotIn("records", body)
        self.assertEqual(uc.executed, [])

    def test_commit_writes_and_audits_each_row(self) -> None:
        uc = FakeUC()
        response = _call("admin", GOOD_CSV, "commit", uc)
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["committed"], {"created": 2, "updated": 0, "unchanged": 0})
        audit = next(sql for sql in uc.executed if "metadata_audit_log" in sql)
        self.assertEqual(audit.count("'ai.intake.ingested'"), 2)
        self.assertIn("'import'", audit)
        self.assertIn("'req-1'", audit)
        self.assertTrue(any(sql.startswith("MERGE INTO `main`.`atlas`.`intake_records`") for sql in uc.executed))

    def test_commit_with_invalid_rows_is_rejected_whole(self) -> None:
        uc = FakeUC()
        response = _call("steward", GOOD_CSV + "INT-3,Bad,bogus,x@y.com\n", "commit", uc)
        self.assertEqual(response.status_code, 422)
        self.assertIn("Nothing was written", json.loads(response.body)["detail"])
        self.assertEqual(uc.executed, [])

    def test_role_gate(self) -> None:
        for role in ("reader", "writer"):
            with self.assertRaises(HTTPException) as ctx:
                _call(role, GOOD_CSV, "dry_run", FakeUC())
            self.assertEqual(ctx.exception.status_code, 403)

    def test_bad_mode(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _call("steward", GOOD_CSV, "yolo", FakeUC())
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
