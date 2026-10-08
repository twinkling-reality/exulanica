"""What the definer owner is expected to hold, from the migrations a database records, without a
database: the order an entry's revocations and grants apply in, and a table revocation clearing
that privilege's column grants (exulanica.db.definer_role.expected_grants)."""

from __future__ import annotations

import pytest
from exulanica.db import definer_role
from exulanica.db.definer_role import DefinerGrants, expected_grants


@pytest.fixture
def entries(monkeypatch):
    def use(grants: dict[str, DefinerGrants]) -> None:
        monkeypatch.setattr(definer_role, "GRANTS_BY_MIGRATION", grants)

    return use


def test_an_entrys_revocations_apply_before_its_grants(entries):
    """A migration that revokes all on a table and grants SELECT back expects SELECT held."""
    entries(
        {
            "0001": DefinerGrants(tables={"t": frozenset({"SELECT", "UPDATE"})}),
            "0002": DefinerGrants(
                revoked_tables={"t": frozenset({"SELECT", "UPDATE"})},
                tables={"t": frozenset({"SELECT"})},
            ),
        }
    )
    assert expected_grants(["0001", "0002"]).tables == {"t": frozenset({"SELECT"})}


def test_a_table_revocation_clears_that_privileges_column_grants(entries):
    entries(
        {
            "0001": DefinerGrants(columns={"t": {"c": frozenset({"UPDATE", "SELECT"})}}),
            "0002": DefinerGrants(revoked_tables={"t": frozenset({"UPDATE"})}),
        }
    )
    assert expected_grants(["0001"]).columns == {"t": {"c": frozenset({"UPDATE", "SELECT"})}}
    assert expected_grants(["0001", "0002"]).columns == {"t": {"c": frozenset({"SELECT"})}}


def test_a_revoked_column_and_function_leave_the_expectation(entries):
    entries(
        {
            "0001": DefinerGrants(
                columns={"t": {"c": frozenset({"UPDATE"})}}, functions=frozenset({"f"})
            ),
            "0002": DefinerGrants(
                revoked_columns={"t": {"c": frozenset({"UPDATE"})}},
                revoked_functions=frozenset({"f"}),
            ),
        }
    )
    behind = expected_grants(["0001"])
    assert (behind.columns, behind.functions) == ({"t": {"c": frozenset({"UPDATE"})}}, {"f"})
    head = expected_grants(["0001", "0002"])
    assert (head.columns, head.functions) == ({}, frozenset())


def test_one_version_given_as_a_string_is_refused():
    with pytest.raises(TypeError):
        expected_grants("0161")
