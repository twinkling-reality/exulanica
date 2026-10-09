"""A person playing a being follows another, against PostgreSQL as a deployment stores it.

Through the real routes: a society of things made now records the follow module; the being a person
plays is offered to follow the knight beside it on its turn; the answer is taken when its minute
comes, the minute records that it began to follow (an event kind the store admits since the follow
migration), its state names whom it follows, and its next turn offers to stop.
"""

from __future__ import annotations

import time

import pytest
from exulanica.abilities.registry import FOLLOW_KEEPING_NEAR
from exulanica.world.society_controls import LEASE_SECONDS

import test_outside_deciders_postgres as outside
import test_society_play_postgres as play
import test_society_stay_requests_api as stays
from test_society_person_decisions_postgres import _claim, _services
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_played_being_follows_another_from_its_turn_and_its_minute_records_it(app):
    world, client = app
    services = _services(client)
    snapshot, knight = play._knight_society(world, client, beside=True)
    assert FOLLOW_KEEPING_NEAR in snapshot["state"]["modules"]
    [other] = [p["id"] for p in snapshot["state"]["inhabitants"] if p["placed_id"] == "knight-2"]
    assert play._start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    path = f"{society}/play/{knight}"
    turn = client.get(path + "/turn", headers=OWNER, params=scope).json()
    [follow] = [o for o in turn["options"] if o["kind"] == "follow"]
    assert (follow["being_id"], follow["takes_line"]) == (other, False)
    assert follow["label"].startswith("follow knight 2")
    body = {"base_tick": turn["base_tick"], "label": follow["label"]}
    assert play._post(client, path + "/answer", scope, body).status_code == 202
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    snapshot = stays._step(world, client, snapshot)
    [began] = [e for e in outside._events(client, world, "followed") if e["subject_id"] == knight]
    assert (began["document"]["reason"], began["document"]["thing"]["with"]) == (
        "chose_to_follow",
        other,
    )
    [person] = [p for p in snapshot["state"]["inhabitants"] if p["id"] == knight]
    assert person["following"]["being"] == other
    turn = client.get(path + "/turn", headers=OWNER, params=scope).json()
    [stop] = [o for o in turn["options"] if o["kind"] == "stop_following"]
    assert stop["being_id"] == other and stop["label"].startswith("stop following knight 2")
