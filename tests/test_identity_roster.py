from __future__ import annotations

import os
import unittest

import pandas as pd

from axiom.services import identity_roster


def _roster_frame():
    return pd.DataFrame(
        [
            {"email": "abarreto@shorecp.com", "display_name": "Skyler", "principal_type": "user"},
            {"email": "trey@shorecp.com", "display_name": "Trey", "principal_type": "user"},
            {
                "email": "6cc86299-0000-0000-0000-000000000000",
                "display_name": "axiom app",
                "principal_type": "service_principal",
            },
        ]
    )


class RosterUC:
    """Fake UC exposing list_workspace_principals for the roster fetch."""

    def __init__(self, frame=None, *, raises=False, warehouse_id="wh-test"):
        self._frame = frame if frame is not None else _roster_frame()
        self._raises = raises
        self.warehouse_id = warehouse_id
        self.calls = 0

    def list_workspace_principals(self):
        self.calls += 1
        if self._raises:
            raise RuntimeError("SCIM unavailable")
        return self._frame


class FakeOwnerStore:
    def __init__(self, rows):
        self._rows = rows
        self.removed = []

    def list_owner_assignments(self):
        return pd.DataFrame(self._rows)

    def remove_owner(self, uc_full_name, owner_email, **kwargs):
        self.removed.append((uc_full_name, owner_email, kwargs))


class RosterMembershipTests(unittest.TestCase):
    def setUp(self):
        identity_roster.clear_roster_cache()

    def test_user_and_service_principal_are_members(self):
        roster = identity_roster.get_roster(RosterUC())
        self.assertTrue(roster.available)
        self.assertEqual(roster.size, 3)
        self.assertTrue(roster.is_member("abarreto@shorecp.com"))
        self.assertEqual(roster.principal_kind("abarreto@shorecp.com"), "user")
        self.assertEqual(
            roster.principal_kind("6cc86299-0000-0000-0000-000000000000"),
            "service_principal",
        )

    def test_non_member_is_absent(self):
        roster = identity_roster.get_roster(RosterUC())
        self.assertFalse(roster.is_member("finance-steward@shorecp.com"))
        self.assertIs(roster.account_member_flag("finance-steward@shorecp.com"), False)
        self.assertIs(roster.account_member_flag("abarreto@shorecp.com"), True)

    def test_degraded_roster_is_unavailable_and_flag_is_none(self):
        roster = identity_roster.get_roster(RosterUC(raises=True))
        self.assertFalse(roster.available)
        self.assertEqual(roster.size, 0)
        # Honesty: unknown, not a false negative.
        self.assertIsNone(roster.account_member_flag("anyone@shorecp.com"))

    def test_roster_is_cached_within_ttl(self):
        uc = RosterUC()
        identity_roster.get_roster(uc)
        identity_roster.get_roster(uc)
        self.assertEqual(uc.calls, 1)


class ValidatePrincipalTests(unittest.TestCase):
    def setUp(self):
        identity_roster.clear_roster_cache()

    def test_accept_member(self):
        self.assertEqual(
            identity_roster.validate_principal(RosterUC(), "trey@shorecp.com"),
            "trey@shorecp.com",
        )

    def test_reject_non_member(self):
        with self.assertRaises(identity_roster.PrincipalNotInWorkspaceError) as ctx:
            identity_roster.validate_principal(RosterUC(), "sales-steward@shorecp.com")
        self.assertIn(
            "sales-steward@shorecp.com is not a member of this Databricks workspace",
            str(ctx.exception),
        )

    def test_empty_principal_passes_through(self):
        self.assertEqual(identity_roster.validate_principal(RosterUC(), ""), "")

    def test_degraded_roster_fails_open(self):
        # Roster unavailable -> validation is skipped, principal passes.
        self.assertEqual(
            identity_roster.validate_principal(
                RosterUC(raises=True), "fabricated@shorecp.com"
            ),
            "fabricated@shorecp.com",
        )


class CleanupTests(unittest.TestCase):
    def setUp(self):
        identity_roster.clear_roster_cache()

    def _rows(self):
        return [
            {"uc_full_name": "cat.sch.real", "owner_email": "abarreto@shorecp.com", "owner_type": "business"},
            {"uc_full_name": "cat.sch.fake", "owner_email": "finance-steward@shorecp.com", "owner_type": "business"},
            {
                "uc_full_name": "cat.sch.sp",
                "owner_email": "6cc86299-0000-0000-0000-000000000000",
                "owner_type": "technical",
            },
        ]

    def test_dry_run_lists_only_non_members(self):
        store = FakeOwnerStore(self._rows())
        result = identity_roster.cleanup_non_workspace_owners(
            store, RosterUC(), actor_email="admin@shorecp.com", dry_run=True
        )
        self.assertEqual(result["scanned"], 3)
        self.assertEqual(len(result["toClear"]), 1)
        self.assertEqual(result["toClear"][0]["ownerEmail"], "finance-steward@shorecp.com")
        self.assertEqual(store.removed, [])  # dry run touches nothing

    def test_apply_clears_non_members_keeps_user_and_sp(self):
        store = FakeOwnerStore(self._rows())
        result = identity_roster.cleanup_non_workspace_owners(
            store, RosterUC(), actor_email="admin@shorecp.com", dry_run=False
        )
        self.assertEqual(len(result["cleared"]), 1)
        self.assertEqual(len(store.removed), 1)
        fqn, email, kwargs = store.removed[0]
        self.assertEqual(email, "finance-steward@shorecp.com")
        self.assertIn("identity integrity cleanup", kwargs.get("note", ""))
        self.assertEqual(kwargs.get("action"), "identity-integrity-cleanup")

    def test_degraded_roster_skips_cleanup(self):
        store = FakeOwnerStore(self._rows())
        result = identity_roster.cleanup_non_workspace_owners(
            store, RosterUC(raises=True), actor_email="admin@shorecp.com", dry_run=False
        )
        self.assertFalse(result["rosterAvailable"])
        self.assertEqual(store.removed, [])
        self.assertTrue(result["warnings"])


class AnnotateAndPayloadTests(unittest.TestCase):
    def setUp(self):
        identity_roster.clear_roster_cache()

    def test_roster_payload_shape(self):
        payload = identity_roster.roster_payload(RosterUC())
        self.assertTrue(payload["available"])
        self.assertEqual(payload["userCount"], 2)
        self.assertEqual(payload["servicePrincipalCount"], 1)
        self.assertEqual(payload["size"], 3)
        self.assertTrue(all(m["accountMember"] for m in payload["members"]))

    def test_annotate_account_member_flags(self):
        from axiom.services import assets as asset_service

        entries = [
            {"name": "abarreto@shorecp.com", "email": "abarreto@shorecp.com"},
            {"name": "finance-steward@shorecp.com", "email": "finance-steward@shorecp.com"},
        ]
        asset_service.annotate_account_member(RosterUC(), entries)
        self.assertIs(entries[0]["accountMember"], True)
        self.assertIs(entries[1]["accountMember"], False)


if __name__ == "__main__":
    unittest.main()


class SqlDerivedRosterTests(unittest.TestCase):
    """When SCIM is unreachable (app SP lacks users:read), the roster falls back
    to real UC principals the app CAN read via SQL, so validation still rejects
    fabricated ghosts instead of failing open."""

    class _SqlOnlyUC:
        # SCIM empty (raises), but query_df returns real UC table owners.
        warehouse_id = "wh-sql"

        def list_workspace_principals(self):
            raise RuntimeError("users:list not permitted")

        def query_df(self, sql):
            import pandas as pd
            if "information_schema.tables" in sql:
                return pd.DataFrame({"p": ["abarreto@shorecp.com", "real.user@shorecp.com"]})
            if "SHOW GRANTS" in sql:
                return pd.DataFrame({"Principal": ["krzysztof@shorecp.com"]})
            return pd.DataFrame()

    def setUp(self):
        identity_roster.clear_roster_cache()
        os.environ["AXIOM_DISCOVERY_CATALOGS"] = "finance_prod,emet"
        os.environ["AXIOM_CATALOG"] = "emet"
        os.environ["AXIOM_SCHEMA"] = "axiom"

    def test_sql_roster_available_without_scim(self):
        r = identity_roster.get_roster(self._SqlOnlyUC(), force_refresh=True)
        self.assertTrue(r.available)
        self.assertIn("abarreto@shorecp.com", r.user_emails)
        self.assertIn("krzysztof@shorecp.com", r.user_emails)

    def test_ghost_rejected_via_sql_roster(self):
        with self.assertRaises(identity_roster.PrincipalNotInWorkspaceError):
            identity_roster.validate_principal(
                self._SqlOnlyUC(), "ghost.nonmember@shorecp.com", field="ownerEmail"
            )

    def test_real_uc_owner_accepted_via_sql_roster(self):
        self.assertEqual(
            identity_roster.validate_principal(self._SqlOnlyUC(), "real.user@shorecp.com"),
            "real.user@shorecp.com",
        )

    def test_actor_always_allowed_even_if_absent(self):
        # A real authenticated actor with no UC footprint is never rejected.
        self.assertEqual(
            identity_roster.validate_principal(
                self._SqlOnlyUC(), "brand.new@shorecp.com",
                actor_email="brand.new@shorecp.com",
            ),
            "brand.new@shorecp.com",
        )
