from __future__ import annotations

import pytest

from axiom.store import GovernanceStore


class _QueryForbiddenUc:
    def query_df(self, *_args, **_kwargs):
        raise AssertionError("configured admins should not require a role-table query")


def test_configured_admin_role_does_not_block_on_role_table_query() -> None:
    store = GovernanceStore(
        uc=_QueryForbiddenUc(),
        catalog="main",
        schema="axiom",
    )

    assert store.get_role("abarreto@shorecp.com", admin_emails=["abarreto@shorecp.com"]) == "admin"


def test_reader_role_uses_role_table_when_not_configured_admin() -> None:
    store = GovernanceStore(
        uc=_QueryForbiddenUc(),
        catalog="main",
        schema="axiom",
    )

    with pytest.raises(AssertionError):
        store.get_role("reader@shorecp.com", admin_emails=["abarreto@shorecp.com"])
