"""What a visitor may take home, as the door records it, against PostgreSQL.

Through the real routes, as a world's owner and as a bridge with a channel credential:

*   an arrival states that its visitor may carry things of the world out only where its grant lets
    things be carried out, and states nothing otherwise, so every other arrival keeps its bytes;
*   a visitor its player calls home through its bridge leaves by a departure that says so
    (``called_by`` ``player``), one its owner sends away by one that does not, and whichever of the
    two comes first is the visitor's one departure, the other answered as written even when both
    passed the check for it at the same moment;
*   end to end, a traveller crossing in under a world grant that lets things be carried out picks
    up the world's sword (its gate's mind, a scripted model, chooses so), its player calls it home,
    it takes the sword, and its bridge reads the sword as the game's own item.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from exulanica.door.crossings import Visits

import test_society_authored_world_postgres as helpers
import test_society_hands_postgres as hands
from society_seed_support import choose_society_seed
from test_door_crossing_rules_postgres import _crossings
from test_door_crossings_postgres import _arrive, _grant, _world
from test_door_crossings_postgres import crossings as crossings
from test_door_lines_postgres import _host, _minute
from test_door_postgres import OWNER, _hello
from test_door_postgres import door as door
from test_door_world_decides_postgres import _application, _hello_cursor, _opened, _read_from
from test_society_things_postgres import _make_society, _place, _step

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres


def _stored(world, thing_id: str, kind: str) -> dict[str, Any]:
    [crossing] = [
        row for row in _crossings(world) if str(row["thing_id"]) == thing_id and row["kind"] == kind
    ]
    return crossing["document"]


def test_an_arrival_states_the_right_to_carry_out_only_where_its_grant_gives_it(door, crossings):
    world, _society = _world(door)
    client = door["client"]
    _out, carrying = _grant(door, key="carry-out-yes", may_carry_out=True)
    _in, keeping = _grant(door, key="carry-out-no", may_carry_out=False)
    for channel in (carrying, keeping):
        assert _hello(door, channel).status_code == 200
    may = _arrive(client, carrying, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    may_not = _arrive(client, keeping, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    assert _stored(world, may, "arrival")["may_carry_out"] is True
    assert "may_carry_out" not in _stored(world, may_not, "arrival")


def test_a_visitor_its_player_calls_home_is_named_so_and_one_its_owner_sends_away_is_not(
    door, crossings
):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door, key="called-home", visitors_maximum=2)
    assert _hello(door, channel).status_code == 200
    called = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    sent = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    home = client.post("/door/channel/home", headers=channel, json={"thing_id": called})
    assert (home.status_code, home.json()["recorded"]) == (202, True)
    away = client.post(f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": sent})
    assert away.status_code == 202, away.text
    assert _stored(world, called, "departure")["called_by"] == "player"
    assert "called_by" not in _stored(world, sent, "departure")
    # The owner sending away the visitor its player already called home finds that departure.
    again = client.post(
        f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": called}
    )
    assert again.status_code == 202, again.text
    [departure] = [
        row
        for row in _crossings(world)
        if str(row["thing_id"]) == called and row["kind"] == "departure"
    ]
    assert departure["document"]["called_by"] == "player"


def test_a_send_away_and_a_call_home_at_once_find_the_one_departure_in_either_order(
    door, crossings, monkeypatch
):
    """The owner sends a visitor away as its player calls it home, and each request makes its reads
    before the other's departure commits: the second to write finds the first's under the same id,
    whoever called, and is answered as written, never refused."""
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door, key="home-at-once", visitors_maximum=2)
    assert _hello(door, channel).status_code == 200
    owner_first = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    player_first = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)

    def send_away(thing_id: str) -> Any:
        return client.post(
            f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
        )

    def call_home(thing_id: str) -> Any:
        return client.post("/door/channel/home", headers=channel, json={"thing_id": thing_id})

    assert send_away(owner_first).status_code == 202
    assert call_home(player_first).json()["recorded"] is True
    # Each second request read before the first one's departure committed: no departure written
    # yet, and its visitor still here.
    here = [uuid.UUID(owner_first), uuid.UUID(player_first)]
    monkeypatch.setattr(Visits, "departure_written", lambda self, thing_id, reason: False)
    monkeypatch.setattr(Visits, "present", lambda self: here)
    late_home = call_home(owner_first)
    assert (late_home.status_code, late_home.json().get("recorded")) == (202, False), late_home.text
    late_away = send_away(player_first)
    assert late_away.status_code == 202, late_away.text
    assert "called_by" not in _stored(world, owner_first, "departure")
    assert _stored(world, player_first, "departure")["called_by"] == "player"


def _sword(society: dict[str, Any]) -> dict[str, Any] | None:
    return next((t for t in society["state"]["things"] if t.get("placed_id") == "sword"), None)


# On the endless ground, with the seed the hands tests pick so the sword lies near the gate.
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_traveller_its_player_calls_home_takes_the_world_s_sword_to_its_game(
    door, crossings, monkeypatch
):
    world, client = door["world"], door["client"]
    choose_society_seed(client.app, hands.NEAR)
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "gate", "gate", 1, 0, 6_000)
    _place(client, world, "sword", "sword", 2, 1_000, 4_000)
    society = _make_society(client, world)
    with _application(door, monkeypatch) as (bridge, traveller):
        _grant_id, channel = _opened(
            bridge, door, "sword-goes-home", traveller=traveller, may_carry_out=True
        )
        cursor = _hello_cursor(bridge, channel)
        visitor = _arrive(bridge, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
        host, _manifest, _model_id = _host(door, hands._Hands())
        for _ in range(20):
            society = _minute(door, host, world, society)
            if (_sword(society) or {}).get("held_by") == visitor:
                break
        else:
            raise AssertionError("the traveller never picked the sword up in twenty minutes")
        sword = _sword(society)
        assert sword is not None
        home = bridge.post("/door/channel/home", headers=channel, json={"thing_id": visitor})
        assert (home.status_code, home.json()["recorded"]) == (202, True)
        society = _step(client, world, society)
        assert _sword(society) is None
        departed = []
        for _ in range(10):
            frames, cursor = _read_from(bridge, channel, cursor)
            departed += [f for f in frames if f["kind"] == "departed" and f["thing_id"] == visitor]
            if departed:
                break
        else:
            raise AssertionError("the bridge never read its traveller's departure")
    [frame] = departed
    assert frame["why"] == "sent_home"
    assert frame["carried"] == [
        {"thing_id": sword["id"], "kind": sword["kind"], "game_item": "test:sword"}
    ]
