"""A society of things' people are offered only models that answer a choice that takes a line.

The manifest says Nemotron 3.5 Lightning is not offered for lines. Through the routes, against
PostgreSQL: a society of things' models read does not list it, and choosing it for one of its
people is refused by name, while the other offered models are listed and may be chosen.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
QWEN = "Qwen/Qwen3-235B-A22B-Instruct-2507"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_of_things_offers_no_model_that_does_not_answer_a_line(app):
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    snapshot = things_api._make_society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    listed = {model["model_id"] for model in read.json()["models"]}
    assert LIGHTNING not in listed and QWEN in listed

    def choose(model_id):
        return client.post(
            society + "/models",
            headers=OWNER,
            params=scope,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "people": [knight["id"]],
                "model": {"provider": "nebius_token_factory", "model_id": model_id},
            },
        )

    refused = choose(LIGHTNING)
    assert (refused.status_code, refused.json()["code"]) == (422, "model_not_askable")
    # Whatever contract a caller records under, the role's own among them (as a scene's dressing
    # does), a model is checked under the one the society's engine asks by.
    role, version = person_role(), world["binding"].version_id
    with (
        decisions._services(client).database.session(world["workspace"]) as connection,
        pytest.raises(ModelChoiceRefused) as refused_here,
    ):
        SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_choice(
            version,
            role,
            request_id=uuid.uuid4(),
            subjects=[knight["id"]],
            model={"provider": "nebius_token_factory", "model_id": LIGHTNING},
            chosen_by=world["session"].actor,
            manifest=load_manifest(),
            contract=role.contract(),
        )
    assert refused_here.value.code == "model_not_askable"
    # The positive control: a model that answers a line is chosen.
    chosen = choose(QWEN)
    assert chosen.status_code in (200, 201), chosen.text
