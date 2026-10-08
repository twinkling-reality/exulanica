"""A traveller carries a world's sword home, through the decision host and against PostgreSQL.

The application connects as a provisioned runtime role. A saved world's society of things has a
gate and a sword its author placed beside it. A traveller crosses in under a grant that lets things
be carried out, decided for by the world: the gate's mind, a scripted model that picks the sword up
when it may. Called home by its player, it takes the sword: the departure names it with its
placement, the sword is gone from the society and stays gone while the author's placement stands,
and replay regenerates the history from what was stored, asking no model.
"""

from __future__ import annotations

import dataclasses
import time
import uuid

import pytest
from exulanica.world.crossings import register_crossing_stream
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_contract import decision_contract, person_role

import test_society_hands_postgres as hands
import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
import things_society_support as things_support
from society_seed_support import choose_society_seed
from test_society_saved_world_api import OWNER, routes
from test_traveller_choices_postgres import _an_hour_from_now, _repository

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
#: A society seed, chosen so the minutes here are the same in every run (the routine moves the
#: world's people, and a world's own seed differs between runs).
SEED = hands.NEAR


def _sword(snapshot):
    return next((t for t in snapshot["state"]["things"] if t["placed_id"] == "sword"), None)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_traveller_called_home_by_its_player_carries_the_world_s_sword_out(app):
    world, client = app
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    choose_society_seed(client.app, SEED)
    services = decisions._services(client)
    stream = things_support.MemoryCrossings()
    register_crossing_stream(stream)
    scope, _, society = routes(world)
    try:
        things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
        things_api._place(client, world, "gate", "gate", 1, 0, 6_000)
        things_api._place(client, world, "sword", "sword", 2, 1_000, 4_000)
        snapshot = things_api._make_society(client, world)
        society_id = uuid.UUID(snapshot["society_id"])
        traveller = things_support.reference("traveller", 1)
        stream.hand(
            society_id,
            things_support.arrival(1, kind=traveller, decided_by="world", may_carry_out=True),
        )
        snapshot = stays._step(world, client, snapshot)
        [visitor] = [p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "crossed"]
        assert visitor["crossing"]["may_carry_out"] is True
        manifest, model_id = decisions._offered()
        model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
        with services.database.session(world["workspace"]) as connection:
            _repository(connection, world).record_traveller_choice(
                world["binding"].version_id,
                person_role(),
                request_id=uuid.uuid4(),
                grant_id=things_support.GRANT,
                model=model,
                chosen_by=world["session"].actor,
                manifest=manifest,
                contract=decision_contract(),
                ends_at=_an_hour_from_now(),
            )
        transport = hands._Hands()
        host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
        for _ in range(20):
            assert host.before_minute(
                decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
            )
            snapshot = stays._step(world, client, snapshot)
            if (_sword(snapshot) or {}).get("held_by") == visitor["id"]:
                break
        else:
            raise AssertionError("the traveller never picked the sword up in twenty minutes")
        sword = _sword(snapshot)
        stream.hand(society_id, things_support.departure(visitor["id"], 1, called_by="player"))
        snapshot = stays._step(world, client, snapshot)
        events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
        [gone] = [e for e in events if e["event_kind"] == "thing_departed"]
        assert (gone["document"]["reason"], gone["document"]["thing"]["called_by"]) == (
            "sent_home",
            "player",
        )
        assert gone["document"]["thing"]["carried"] == [
            {"id": sword["id"], "kind": sword["kind"], "placed_id": "sword"}
        ]
        assert _sword(snapshot) is None
        assert [entry["placed_id"] for entry in snapshot["state"]["carried_out"]] == ["sword"]
        # The author's placement still stands, so later minutes never put the sword back.
        for _ in range(2):
            snapshot = stays._step(world, client, snapshot)
            assert _sword(snapshot) is None
        asked = transport.call_count
        replayed = client.get(society + "/replay", headers=OWNER, params=scope)
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["replay_verified"] is True
        assert transport.call_count == asked
    finally:
        register_crossing_stream(None)
