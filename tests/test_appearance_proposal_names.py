"""An appearance proposal's words carry the request's placeholder map, as an answer's do.

The classifier and the drafter are sent the utterance with each saved name no right can release
replaced by a placeholder, ``[person A]``, ``[place A]``, so a drafted proposal speaks of the
people and places in it by placeholder. The proposal returns the request's one record of which
entity each placeholder stands for, and the browser restores the name from the account holder's
own data, exactly as it does for a remembered or a fresh answer. A person's saved name never
reaches a hosted model on this path, with or without a right granted for every entity.

The model is scripted throughout. Nothing here spends credits.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.composer_rights import photograph_text_right
from exulanica.api.services import Services
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.selection.proposal import propose_appearance
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport
from test_companion_person_link import _every_entity
from test_companion_saved_names import PERSON, PLACE, named
from test_selection_proposal import current_reference, draft, reply
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

__all__ = ["named"]

SOURCE = uuid.UUID(int=41)
UTTERANCE = f"make the light warmer where {PERSON} stands outside {PLACE}"
SPOKEN = "The light will sit warmer where [person A] stands outside [place A]."


@pytest.fixture
def world(named):
    """The named photograph as the one evidence slot of the world the proposal is asked in."""
    repository, store, session, entities = named
    span = repository.connection.execute(
        "select span_id from evidence_span where workspace_id=%s order by span_id limit 1",
        (repository.workspace_id,),
    ).fetchone()["span_id"]
    registered_world(repository.connection, repository.workspace_id, FIXTURE_WORLD_ID)
    WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    ).register_topology(
        TopologyContract(
            "proposal-names-topology",
            ("region-a",),
            (
                TopologySourceSlot(
                    source_id=SOURCE,
                    slot_key="slot-00",
                    region_id="region-a",
                    evidence_span_id=span,
                    missing_reason=None,
                ),
            ),
            world_id=FIXTURE_WORLD_ID,
        )
    )
    return repository, store, session, entities


def _propose(repository, session, replies, *, released=None):
    transport = FakeTransport(list(replies))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
    ).with_policy(
        WorkspaceRequestPolicy(
            repository.workspace_id,
            connection=borrowing(repository.connection),
            photograph_right=photograph_text_right,
            released_places=no_place_released if released is None else released,
        )
    )
    outcome = propose_appearance(
        repository.connection,
        client,
        UTTERANCE,
        session,
        current=current_reference(),
        world_id=FIXTURE_WORLD_ID,
        # The world's evidence is its topology, which needs no stored bytes to be citable.
        store=None,
    )
    return outcome, [json.dumps(request["payload"]) for request in transport.requests]


def _asked(body: str) -> str:
    """The user message of one request: what it was asked, apart from its instructions.

    Read alone because a system message may quote a placeholder as an example of its own.
    """
    messages = json.loads(body)["messages"]
    return "\n".join(m["content"] for m in messages if m["role"] == "user")


def _drafted(**overrides):
    return [
        reply({"kind": "appearance"}),
        reply(draft(references=[str(SOURCE)], spoken=SPOKEN, **overrides)),
    ]


def _person_leaks(bodies: list[str]) -> list[str]:
    lowered = " ".join(" ".join(bodies).lower().split())
    return [part for part in PERSON.lower().split() if part in lowered]


def test_a_drafted_proposal_carries_whom_its_placeholders_stand_for(world):
    repository, _, session, entities = world
    outcome, bodies = _propose(repository, session, _drafted())

    assert outcome.proposal is not None, outcome.refusal
    assert outcome.proposal.spoken == SPOKEN
    assert dict(outcome.names) == {
        "[person A]": entities["person"],
        "[place A]": entities["place"],
    }
    assert len(bodies) == 2
    assert not _person_leaks(bodies)
    assert PLACE.lower() not in " ".join(bodies).lower()


def test_a_refused_proposal_carries_the_map_its_detail_is_written_in(world):
    """The not_in_catalogue detail is the drafter's own words, placeholders and all."""
    repository, _, session, entities = world
    outcome, _ = _propose(
        repository, session, _drafted(impossible="a mural of [person A] on [place A]")
    )

    assert outcome.refusal is not None and outcome.refusal.code.value == "not_in_catalogue"
    assert "[person A]" in outcome.refusal.detail
    assert dict(outcome.names)["[person A]"] == entities["person"]


def test_no_saved_name_of_a_person_leaves_on_the_proposal_path_with_every_right_granted(world):
    """Every entity released, as though a right existed for each: the person's name still stays.

    The positive control is the place: released, its saved name reaches the drafter, so the
    resolver did release what it was given and the person's placeholder is not an accident.
    """
    repository, _, session, entities = world
    outcome, bodies = _propose(repository, session, _drafted(), released=_every_entity(repository))

    assert len(bodies) == 2
    assert PLACE in _asked(bodies[1]), "positive control: the released place is written by name"
    assert "[person A]" in _asked(bodies[1])
    assert not _person_leaks(bodies), f"sent: {_person_leaks(bodies)}"
    assert dict(outcome.names)["[person A]"] == entities["person"]


def test_no_saved_name_of_a_person_leaves_on_the_proposal_path_with_no_right_granted(world):
    repository, _, session, _ = world
    _, bodies = _propose(repository, session, _drafted())

    assert len(bodies) == 2
    assert not _person_leaks(bodies), f"sent: {_person_leaks(bodies)}"
    assert "[person A]" in _asked(bodies[1])
    assert "[place A]" in _asked(bodies[1])


TOKEN = "proposal-names-owner-token-long-enough-for-tests"


@pytest.fixture
def route(world, spine_schema, monkeypatch):
    """``POST /selection/appearance`` over the named world, as the browser calls it."""
    repository, store, session, entities = world
    _psycopg, scratch = spine_schema
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(session.actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    transport = FakeTransport(_drafted())
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
    )
    with TestClient(create_app(services, verify=False)) as http:
        yield http, transport, entities


def test_the_route_returns_the_map_with_the_proposal(route):
    """``AppearanceView.names``, as ``AnswerView.names`` is for an answer."""
    http, transport, entities = route

    response = http.post(
        "/selection/appearance",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"world_id": FIXTURE_WORLD_ID},
        json={"utterance": UTTERANCE},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal"]["spoken"] == SPOKEN
    assert body["names"] == {
        "[person A]": str(entities["person"]),
        "[place A]": str(entities["place"]),
    }
    assert not _person_leaks([json.dumps(r["payload"]) for r in transport.requests])
