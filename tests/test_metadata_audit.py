from __future__ import annotations

import sys
import types
import unittest
from typing import Any, Dict, List


class FakeStore:
    """Minimal store double exposing append_metadata_audit_log,
    append_change_event, and append_entity_version so we can verify
    that record_audit_log triple-writes to metadata_audit_log + the
    change_events stream + entity_versions."""

    def __init__(self) -> None:
        self.audit_calls: List[Dict[str, Any]] = []
        self.event_calls: List[Dict[str, Any]] = []
        self.version_calls: List[Dict[str, Any]] = []
        self.raise_on_audit = False
        self.raise_on_event = False
        self.raise_on_version = False

    def append_metadata_audit_log(self, **kwargs) -> str:
        if self.raise_on_audit:
            raise RuntimeError("audit store down")
        self.audit_calls.append(kwargs)
        return "audit-id-1"

    def append_change_event(self, **kwargs) -> str:
        if self.raise_on_event:
            raise RuntimeError("event store down")
        self.event_calls.append(kwargs)
        return "event-id-1"

    def append_entity_version(self, **kwargs) -> str:
        if self.raise_on_version:
            raise RuntimeError("version store down")
        self.version_calls.append(kwargs)
        return "version-id-1"


def _install_fake_runtime_app(store: FakeStore) -> None:
    module = types.ModuleType("runtime_app")
    module._store = lambda: store
    sys.modules["runtime_app"] = module


class RecordAuditLogChangeEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_runtime_app = sys.modules.get("runtime_app")

    def tearDown(self) -> None:
        if self._saved_runtime_app is None:
            sys.modules.pop("runtime_app", None)
        else:
            sys.modules["runtime_app"] = self._saved_runtime_app

    def test_dual_writes_to_audit_and_change_event_on_success(self) -> None:
        store = FakeStore()
        _install_fake_runtime_app(store)
        from axiom.services.metadata_audit import record_audit_log

        record_audit_log(
            entity_type="asset",
            action="description.updated",
            actor_email="abarreto@shorecp.com",
            actor_role="steward",
            entity_fqn="main.gov.orders",
            before={"description": "old"},
            after={"description": "new"},
        )
        self.assertEqual(len(store.audit_calls), 1)
        self.assertEqual(len(store.event_calls), 1)
        event = store.event_calls[0]
        self.assertEqual(event["event_type"], "asset.description.updated")
        self.assertEqual(event["entity_kind"], "asset")
        self.assertEqual(event["entity_fqn"], "main.gov.orders")
        self.assertEqual(event["status"], "emitted")
        # Phase 5 entity_versions writer also fired
        self.assertEqual(len(store.version_calls), 1)
        version = store.version_calls[0]
        self.assertEqual(version["entity_kind"], "asset")
        self.assertEqual(version["entity_fqn"], "main.gov.orders")
        self.assertEqual(version["snapshot"], {"description": "new"})
        self.assertEqual(version["change_event_id"], "event-id-1")

    def test_entity_version_skipped_when_after_is_none(self) -> None:
        store = FakeStore()
        _install_fake_runtime_app(store)
        from axiom.services.metadata_audit import record_audit_log

        record_audit_log(
            entity_type="asset",
            action="deleted",
            actor_email="abarreto@shorecp.com",
            actor_role="admin",
            entity_fqn="main.gov.gone",
            before={"description": "had one"},
            after=None,
        )
        self.assertEqual(len(store.audit_calls), 1)
        self.assertEqual(len(store.event_calls), 1)
        self.assertEqual(len(store.version_calls), 0)

    def test_change_event_emitted_even_if_audit_write_fails(self) -> None:
        store = FakeStore()
        store.raise_on_audit = True
        _install_fake_runtime_app(store)
        from axiom.services.metadata_audit import record_audit_log

        record_audit_log(
            entity_type="column",
            action="tags.updated",
            actor_email="alice@example.com",
            actor_role="owner",
            entity_fqn="main.gov.orders",
            column_name="customer_id",
        )
        self.assertEqual(store.audit_calls, [])
        self.assertEqual(len(store.event_calls), 1)
        self.assertEqual(store.event_calls[0]["event_type"], "column.tags.updated")

    def test_record_audit_log_is_best_effort_on_event_failure(self) -> None:
        store = FakeStore()
        store.raise_on_event = True
        _install_fake_runtime_app(store)
        from axiom.services.metadata_audit import record_audit_log

        try:
            record_audit_log(
                entity_type="asset",
                action="owner.assigned",
                actor_email="a@b",
                actor_role="admin",
                entity_fqn="main.gov.x",
            )
        except Exception as exc:
            self.fail(f"record_audit_log should swallow event errors, got {exc!r}")
        self.assertEqual(len(store.audit_calls), 1)


if __name__ == "__main__":
    unittest.main()
