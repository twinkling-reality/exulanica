"""Withdrawing one place-name chain: exactly one place, model and destination, and only a grant.

``withdraw_place_name`` stops every model of a role; ``withdraw_place_name_chain`` stops one chain,
which is what a restore needs when a grant made after the backup leaves the carried withdrawal
unable to follow the chain the backup holds. These hold the function itself, as the runtime role;
the restore that uses it is in ``tests/test_restore_replay_withdrawals.py``.
"""

from __future__ import annotations

import pytest
from exulanica.consent.place_name_rights import withdraw_place_name_chain
from exulanica.db.roles import provision_runtime_role

from conftest import scratch_role_database
from test_place_name_rights import PLANNER, _events, _grant, _released, _state
from test_place_name_rights import named as named

pytestmark = pytest.mark.postgres

ROLE = "structured_extraction"
RUNTIME = "exulanica_place_name_chain_suite"


def _withdraw_one(named, spine_schema, identity) -> bool:
    repository, _, _, actor, entities = named
    _, schema = spine_schema
    provision_runtime_role(repository.connection, role=RUNTIME)
    with scratch_role_database(schema, RUNTIME).session(repository.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
        return withdraw_place_name_chain(
            connection,
            repository.workspace_id,
            entity_id=entities["place"],
            identity=identity,
            destination=PLANNER.destination,
            actor=actor,
        )


def _chain(named, identity) -> list[str]:
    return [
        event["event"]
        for event in _events(named)
        if event["model_id"] == identity.model_id and event["model_role"] == ROLE
    ]


def test_withdrawing_one_chain_withdraws_that_model_only(named, spine_schema):
    _grant(named, ROLE)
    first, *others = PLANNER.identities
    assert others, "the positive control: the planner's chain names more than one model"

    assert _withdraw_one(named, spine_schema, first) is True
    assert _chain(named, first) == ["granted", "withdrawn"]
    for other in others:
        assert _chain(named, other) == ["granted"], "every other chain still stands"
    assert _state(named, ROLE) != "allowed", "a use needs its whole chain"


def test_a_chain_that_ends_withdrawn_or_does_not_exist_records_nothing(named, spine_schema):
    first = PLANNER.identities[0]
    assert _withdraw_one(named, spine_schema, first) is False, "no chain yet"
    assert _chain(named, first) == []

    _grant(named, ROLE)
    assert _withdraw_one(named, spine_schema, first) is True
    assert _withdraw_one(named, spine_schema, first) is False, "already withdrawn"
    assert _chain(named, first) == ["granted", "withdrawn"]
    assert _released(named, PLANNER) == frozenset()


def test_a_chain_of_a_model_the_place_was_never_granted_to_records_nothing(named, spine_schema):
    _grant(named, ROLE)
    stranger = type(PLANNER.identities[0])(
        provider="local", role=ROLE, model_id="never-granted", revision="0" * 40
    )
    assert _withdraw_one(named, spine_schema, stranger) is False
    assert all(event["model_id"] != "never-granted" for event in _events(named))
