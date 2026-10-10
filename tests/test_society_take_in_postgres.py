"""A living town's people take in what was placed after they came, as a deployment stores it.

One request ends the version's living society by the erasure a person's own erasing uses and makes
a society of things on the same version, in one transaction. The people after are the people
before, read from the living society's stored state and first input before the request; a refusal
of the making leaves the living society and writes no tombstone; each refusal is named."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.api import society_making
from exulanica.api.society_opening import opening_setting
from exulanica.api.society_runtime import UnavailableSocietyInput

from test_society_made_world import made as imported_made  # noqa: F401
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    V3,
    V7,
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
    _step,
)

pytestmark = pytest.mark.postgres

V5 = "exulanica-society/v5"


def _held(api, entry: dict) -> dict:
    """What the database holds of the version's society and of erasures in the workspace."""
    with api.database.session(api.repository.workspace_id) as connection:
        society = connection.execute(
            "select society_id::text, engine_version, state_sha256, current_tick "
            "from world_society where workspace_id=%s and world_id=%s and version_id=%s",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()
        counts = connection.execute(
            "select (select count(*) from society_erasure where workspace_id=%s) as erasures, "
            "(select count(*) from tombstone where workspace_id=%s and scope::text='society') "
            "as tombstones",
            (api.repository.workspace_id, api.repository.workspace_id),
        ).fetchone()
        first = connection.execute(
            "select i.document from world_society_input i join world_society s using "
            "(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()
    return {
        "society": None if society is None else dict(society),
        "erasures": counts["erasures"],
        "tombstones": counts["tombstones"],
        "first_input": None if first is None else first["document"],
    }


def _offered(api, entry: dict) -> tuple[str, str | None]:
    """What the version's capability read says of taking newcomers in: its state and its code."""
    document = api.get(
        f"/world/versions/{entry['authored_version_id']}/capabilities?world_id={entry['world_id']}"
    ).json()
    [row] = [
        row
        for row in document["operations"]
        if row["operation"] == "POST /world/versions/{version_id}/society/take-in"
    ]
    assert row["requires"] == ["deletion.write", "world.write"] and row["writes"] is True
    return row["state"], row["code"]


def _town(api, title: str) -> tuple[dict, str, str]:
    made_town = api.post("/worlds/generated", {"recipe": "small_town", "title": title})
    assert made_town.status_code == 201, made_town.text
    entry = made_town.json()
    root = f"/world/versions/{entry['authored_version_id']}/society"
    scope = f"?world_id={entry['world_id']}"
    return entry, f"{root}{scope}", f"{root}/take-in{scope}"


def test_a_living_town_s_people_take_a_knight_in_and_stay_who_they_are(made):
    api = made
    _offering_things(api)
    entry, society, take_in = _town(api, "A town that takes a knight in")
    # Nobody lives here yet: nothing to take anybody in.
    nobody = api.post(take_in, {})
    assert (nobody.status_code, nobody.json()["code"]) == (404, "society_unavailable")
    # The capability read says of each state what the route itself answers there.
    assert _offered(api, entry) == ("unavailable", "society_unavailable")
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    for _ in range(2):
        body = _step(api, entry, body)
    before = _held(api, entry)
    assert before["society"]["engine_version"] == V5 and before["erasures"] == 0
    # Nothing is placed: the engine table gives this version no society of things.
    nothing = api.post(take_in, {})
    assert (nothing.status_code, nothing.json()["code"]) == (409, "nothing_to_take_in")
    assert _held(api, entry) == before
    assert _offered(api, entry) == ("unavailable", "nothing_to_take_in")
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    # The living town's people as the database holds them before the request.
    place = before["first_input"]["living"]["place"]
    subject = {d["destination_id"]: d["subject_id"] for d in place["destinations"]}
    residents = body["state"]["inhabitants"]
    assert _offered(api, entry) == ("available", None)

    taken = api.post(take_in, {})
    assert taken.status_code in (200, 201), taken.text
    after = taken.json()
    assert after["profile"] == V7
    state = after["state"]
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    [knight] = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
    assert knight["placed_id"] == "knight" and "resident" not in knight
    premises = state["people"]["premises"]
    assert len(villagers) == len(residents) > 0
    working = 0
    for villager, resident in zip(villagers, residents, strict=True):
        assert (villager["id"], villager["ordinal"]) == (resident["id"], resident["ordinal"])
        stated = villager["resident"]
        assert (
            premises[stated["home"]["premises"]]["subject_id"]
            == (subject[resident["home"]["destination_id"]])
        )
        assert stated["role"] == {
            "key": resident["role"]["key"],
            "label": resident["role"]["label"],
        }
        if resident["work"] is None:
            assert stated["job"] is None
        else:
            working += 1
            assert (
                premises[stated["job"]["premises"]]["subject_id"]
                == (subject[resident["work"]["destination_id"]])
            )
            assert (stated["job"]["shift"]["start_minute"], stated["job"]["shift"]["minutes"]) == (
                resident["work"]["shift_start_minute"],
                resident["work"]["shift_minutes"],
            )
    assert working > 0
    held = _held(api, entry)
    # One society on the version, under the same identity, on the engine of things; the living
    # one erased once, under one society tombstone; the new first input the things composition.
    assert held["society"]["society_id"] == before["society"]["society_id"]
    assert held["society"]["engine_version"] == V7 and held["society"]["current_tick"] == 0
    assert (held["erasures"], held["tombstones"]) == (1, 1)
    assert held["first_input"]["profile"] == V3
    # They live on, and the stored minutes replay.
    for _ in range(2):
        after = _step(api, entry, after)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True
    # Taken in already: asked again, nothing is erased.
    again = api.post(take_in, {})
    assert (again.status_code, again.json()["code"]) == (409, "society_takes_in_already")
    assert _held(api, entry)["erasures"] == 1
    assert _offered(api, entry) == ("unsupported", "society_takes_in_already")


def test_the_people_taken_in_are_opened_awake_after_the_transaction_and_not_inside_it(
    made, monkeypatch
):
    api = made
    _offering_things(api)
    # As a deployment opens a society: the policy in force, with seconds that do not run out here.
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services,
        society_opening=dataclasses.replace(opening_setting("on"), seconds_maximum=3600),
    )
    entry, society, take_in = _town(api, "A town that wakes when it takes a knight in")
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    # Every minute the opening advances is advanced with no transaction open on the request's
    # connection: the take-in's own transaction, and its workspace lock, are behind it.
    seen = []
    advance = society_making.open_awake

    def watched(repository, version_id, snapshot, opening, **keywords):
        seen.append((repository.connection.info.transaction_status.name, snapshot["current_tick"]))
        return advance(repository, version_id, snapshot, opening, **keywords)

    monkeypatch.setattr(society_making, "open_awake", watched)
    taken = api.post(take_in, {})
    assert taken.status_code in (200, 201), taken.text
    after = taken.json()
    assert seen == [("IDLE", 0)]
    # Born idle at minute 0, it is answered at the minute half its beings are doing something.
    beings = after["state"]["inhabitants"]
    assert after["profile"] == V7 and after["current_tick"] >= 1
    assert 2 * sum(being["action"]["kind"] != "idle" for being in beings) >= len(beings)
    held = _held(api, entry)
    assert held["society"]["current_tick"] == after["current_tick"]
    assert held["society"]["state_sha256"] == after["state_sha256"]
    assert (held["erasures"], held["tombstones"]) == (1, 1)
    replayed = api.get(
        f"/world/versions/{entry['authored_version_id']}/society/replay?world_id={entry['world_id']}"
    )
    assert replayed.status_code == 200 and replayed.json()["replay_verified"] is True


def test_a_host_that_offers_no_society_of_things_offers_no_taking_in(made):
    api = made
    entry, society, take_in = _town(api, "A town on a host with no society of things")
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    before = _held(api, entry)
    assert _offered(api, entry) == ("unavailable", "nothing_to_take_in")
    refused = api.post(take_in, {})
    assert (refused.status_code, refused.json()["code"]) == (409, "nothing_to_take_in")
    assert _held(api, entry) == before


def test_a_making_that_refuses_leaves_the_living_town_and_writes_no_tombstone(made, monkeypatch):
    api = made
    _offering_things(api)
    entry, society, take_in = _town(api, "A town whose taking in is refused")
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    before = _held(api, entry)

    def refuse(*_args, **_kwargs):
        # After the erasure, inside the request's transaction, as a making that cannot compose.
        raise UnavailableSocietyInput("the making was refused")

    monkeypatch.setattr(society_making, "make_society", refuse)
    refused = api.post(take_in, {})
    assert (refused.status_code, refused.json()["code"]) == (424, "unavailable_society_input")
    assert _held(api, entry) == before
    assert before["society"]["engine_version"] == V5 and before["tombstones"] == 0
    # The living town still plays.
    body = api.get(society).json()
    assert _step(api, entry, body)["current_tick"] == body["current_tick"] + 1


def test_an_installation_sealed_for_a_restore_takes_nobody_in_and_erases_nothing(made):
    api = made
    _offering_things(api)
    entry, society, take_in = _town(api, "A town on a sealed installation")
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    before = _held(api, entry)
    owner = api.repository.connection
    owner.execute(
        "insert into restore_control (checkpoint_id, checkpoint_sha256, state) "
        "values (%s, %s, 'sealed')",
        (uuid.uuid4(), "a" * 64),
    )
    owner.commit()
    try:
        refused = api.post(take_in, {})
        assert (refused.status_code, refused.json()["code"]) == (409, "restore_sealed")
    finally:
        owner.execute("delete from restore_control")
        owner.commit()
    assert _held(api, entry) == before
    assert before["society"]["engine_version"] == V5 and before["tombstones"] == 0
