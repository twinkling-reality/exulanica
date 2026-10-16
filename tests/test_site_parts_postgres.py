"""A person moves, turns and removes the parts a site world was made with, through the API.

On the fixture farm (a hand-written test kind): the parts read, a move and its preview, a refusal
in words, a removal refused for the people who live or work in a part, undo and redo, and what
follows a kept change: the drawing, the ground a placed thing lands on, and the society, which
takes the changed world as its next input and keeps stepping (a society of things and a living
town). Expected figures are read from the parts route and the drawing, never retyped.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.db.session import set_workspace
from exulanica.world import saved_entries
from exulanica.world.site_parts import QUARTER_TURNS
from exulanica.world.starter import create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id

from test_site_land_postgres import LAND
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
THINGS = "exulanica-society/v7"
LIVING = "exulanica-society/v5"
FARM = "world:generated:00000000-0000-4000-8000-00000000f0c2"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_farm_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)


def _farm(api, *, things: bool = True, land: dict | None = None) -> dict[str, Any]:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=things
    )
    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    document["origin"] = "uploaded"
    document["provenance"] = {"by": "a test creator"}
    assert api.post("/worlds/kinds", {"document": document}).status_code == 201
    made_world = api.post(
        "/worlds/kinds/fixture_farm/worlds",
        {"preset": "small_farm", "title": "A farm", **({} if land is None else {"land": land})},
    )
    assert made_world.status_code == 201, made_world.text
    return made_world.json()


def _path(entry: dict, tail: str = "", query: str = "") -> str:
    return (
        f"/world/versions/{entry['authored_version_id']}{tail}?world_id={entry['world_id']}{query}"
    )


def _base(api, entry: dict) -> str:
    read = api.get(_path(entry))
    assert read.status_code == 200, read.text
    return read.json()["state_sha256"]


def _parts(api, entry: dict) -> dict[str, dict[str, Any]]:
    read = api.get(_path(entry, "/parts"))
    assert read.status_code == 200, read.text
    return {part["part_key"]: part for part in read.json()["parts"]}


def _drawn(api, entry: dict, identity: str) -> dict[str, Any]:
    read = api.get(_path(entry, "/site"))
    assert read.status_code == 200, read.text
    return next(slot for slot in read.json()["slots"] if slot["identity"] == identity)


def _pose(east: int, north: int, turns: int = 0) -> dict[str, int]:
    return {"x_mm": east, "y_mm": 0, "z_mm": -north, "yaw_microradians": QUARTER_TURNS[turns]}


def _move(api, entry: dict, part: dict, east: int, north: int, turns: int = 0, *, preview=False):
    tail = f"/parts/{part['part_id']}/move" + ("/preview" if preview else "")
    return api.post(
        _path(entry, tail),
        {"base_state_sha256": _base(api, entry), "pose": _pose(east, north, turns)},
    )


def _society(api, entry: dict) -> dict[str, Any]:
    read = api.get(_path(entry, "/society", "&places=true"))
    assert read.status_code == 200, read.text
    return read.json()


def _step(api, entry: dict) -> dict[str, Any]:
    now = _society(api, entry)
    stepped = api.post(
        _path(entry, "/society/steps"),
        {"base_tick": now["current_tick"], "base_state_sha256": now["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return _society(api, entry)


def _door(document: Any, part_id: str) -> dict[str, Any] | None:
    """The walking node in front of a part's door, wherever an input states its nodes."""
    if isinstance(document, dict):
        if document.get("node_id") == f"door:{part_id}" and "position_mm" in document:
            return document
        found = (_door(value, part_id) for value in document.values())
    elif isinstance(document, list):
        found = (_door(value, part_id) for value in document)
    else:
        return None
    return next((node for node in found if node is not None), None)


def _consumed_input(api, entry: dict) -> dict[str, Any]:
    """The stored input the society's current state consumed, read from its table: no route
    serves an input itself."""
    now = _society(api, entry)
    connection = api.repository.connection
    set_workspace(connection, api.repository.workspace_id)
    row = connection.execute(
        "select document from world_society_input where society_id=%s and input_seq=%s",
        (now["society_id"], now["input_seq"]),
    ).fetchone()
    connection.commit()
    return row["document"]


@pytest.mark.parametrize("profile", [THINGS, LIVING])
def test_a_society_keeps_stepping_after_a_made_building_moves(made, profile):
    api = made
    entry = _farm(api, things=profile == THINGS)
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": profile}
    )
    assert created.status_code in (200, 201), created.text
    before = _step(api, entry)
    barn = _parts(api, entry)["barn"]
    door_before = _door(_consumed_input(api, entry), barn["part_id"])
    assert door_before is not None
    east, north = barn["centre_mm"]

    moved = _move(api, entry, barn, east - 3_000, north)
    assert moved.status_code == 200, moved.text
    # An override stating no storeys reads as it always did.
    (override,) = (
        o for o in moved.json()["element_overrides"] if o["element_id"] == f"part:{barn['part_id']}"
    )
    assert "storeys" not in override

    # The world as it stands draws the barn three metres west of where it was made.
    slot = _drawn(api, entry, barn["part_id"])
    assert slot["positionMm"][:2] == [east - 3_000, north]
    # The society takes the changed world as its next input, available, and keeps stepping.
    after = before
    for _minute in range(3):
        after = _step(api, entry)
    assert after["current_tick"] == before["current_tick"] + 3
    assert after["places"]["authored_state"]["edit_seq"] == moved.json()["edit_seq"]
    assert len(after["state"]["inhabitants"]) == len(before["state"]["inhabitants"])
    consumed = _consumed_input(api, entry)
    assert consumed["availability"] == "available", consumed["unavailable_reason"]
    # Its people walk the world as it now stands: the barn's door is three metres west.
    door_after = _door(consumed, barn["part_id"])
    assert door_after is not None
    assert door_after["position_mm"][0] == door_before["position_mm"][0] - 3_000
    assert door_after["position_mm"][1:] == door_before["position_mm"][1:]


def _place_well(api, entry: dict, east: int, north: int):
    return api.post(
        _path(entry, "/things"),
        {
            "base_state_sha256": _base(api, entry),
            "thing_id": f"well-{east}-{north}",
            "kind": {"kind": "well", "version": 2},
            "region_id": "region:generated",
            "pose": {"x_mm": east, "y_mm": 0, "z_mm": -north, "yaw_microradians": 0},
            "origin_role": "fictional",
        },
    )


def test_a_move_is_previewed_refused_in_words_turned_undone_and_redone(made):
    api = made
    entry = _farm(api)
    parts = _parts(api, entry)
    barn, house, bench = parts["barn"], parts["farmhouse"], parts["bench"]

    onto = _move(api, entry, bench, *house["centre_mm"], preview=True)
    assert onto.status_code == 200, onto.text
    verdict = onto.json()
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == "part_blocked"
    assert verdict["blocked_detail"] == f"Not here: it would stand on the {house['label']}."
    assert verdict["landing"]["where"]["blocked_by"] == house["part_id"]
    refused = _move(api, entry, bench, *house["centre_mm"])
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "part_blocked"
    assert refused.json()["detail"] == verdict["blocked_detail"]

    east, north = barn["centre_mm"]
    made_slot = _drawn(api, entry, barn["part_id"])
    # A half turn about its own centre keeps the barn's footprint, which the world was made with
    # clear: its door faces the other way.
    ready = _move(api, entry, barn, east, north, 2, preview=True)
    assert ready.json()["availability"] == "ready", ready.text
    assert ready.json()["would_change"]["kind"] == "move_part"
    turned = _move(api, entry, barn, east, north, 2)
    assert turned.status_code == 200, turned.text
    assert _parts(api, entry)["barn"]["size_mm"] == barn["size_mm"]
    assert _drawn(api, entry, barn["part_id"]) != made_slot

    undone = api.post(_path(entry, "/things/undo"), {"base_state_sha256": _base(api, entry)})
    assert undone.status_code == 200, undone.text
    assert _drawn(api, entry, barn["part_id"]) == made_slot
    redone = api.post(_path(entry, "/things/redo"), {"base_state_sha256": _base(api, entry)})
    assert redone.status_code == 200, redone.text
    assert _drawn(api, entry, barn["part_id"]) != made_slot


def test_a_part_people_live_or_work_in_is_not_removed_and_its_refusal_names_them(made):
    api = made
    entry = _farm(api)
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": THINGS}
    )
    assert created.status_code in (200, 201), created.text
    society = _step(api, entry)
    parts = _parts(api, entry)
    house, bench = parts["farmhouse"], parts["bench"]
    residents = [
        person["display_name"]
        for person in society["state"]["inhabitants"]
        if person.get("resident")
        and society["state"]["people"]["premises"][person["resident"]["home"]["premises"]][
            "subject_id"
        ]
        == f"site.structure:{house['part_id']}"
    ]
    assert residents

    path = f"/parts/{house['part_id']}/remove"
    verdict = api.post(
        _path(entry, path + "/preview"), {"base_state_sha256": _base(api, entry)}
    ).json()
    assert verdict["blocked_reason"] == "part_houses_people"
    refused = api.post(_path(entry, path), {"base_state_sha256": _base(api, entry)})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "part_houses_people"
    assert residents[0] in refused.json()["detail"]
    assert refused.json()["detail"].endswith(f"The {house['label']} can be moved instead.")

    removed = api.post(
        _path(entry, f"/parts/{bench['part_id']}/remove"), {"base_state_sha256": _base(api, entry)}
    )
    assert removed.status_code == 200, removed.text
    assert bench["part_id"] not in {part["part_id"] for part in _parts(api, entry).values()}
    drawn = api.get(_path(entry, "/site")).json()
    assert bench["part_id"] not in {slot["identity"] for slot in drawn["slots"]}
    again = _move(api, entry, bench, *bench["centre_mm"])
    assert again.status_code == 409, again.text
    assert _step(api, entry)["current_tick"] == society["current_tick"] + 1


def test_a_placed_thing_lands_on_the_world_as_it_stands_after_a_part_moves(made):
    api = made
    entry = _farm(api)
    barn = _parts(api, entry)["barn"]
    east, north = barn["centre_mm"]
    refused = _place_well(api, entry, east, north)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "thing_landing_blocked"

    moved = _move(api, entry, barn, 15_000, 95_000)
    assert moved.status_code == 200, moved.text
    assert _place_well(api, entry, east, north).status_code == 201
    there = _place_well(api, entry, 15_000, 95_000)
    assert there.status_code == 422, there.text
    assert there.json()["where"]["label"] == barn["label"]


def test_a_world_not_made_from_a_kind_has_no_parts(made):
    api = made
    connection = api.repository.connection
    set_workspace(connection, api.repository.workspace_id)
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection,
            workspace_id=api.repository.workspace_id,
            actor=api.actor,
            title="A starter",
            world_id=world_id,
        )
    unmade = api.get(f"/world/versions/{version_id}/parts?world_id={world_id}")
    assert unmade.status_code == 422, unmade.text
    assert unmade.json()["code"] == "parts_not_served"


def test_on_land_a_moved_building_is_drawn_on_the_land_graded_for_the_changed_layout(made):
    api = made
    entry = _farm(api, land=LAND)
    barn = _parts(api, entry)["barn"]
    east, north = barn["centre_mm"]
    made_drawing = api.get(_path(entry, "/site")).json()
    assert made_drawing["profile"].endswith("/v5")

    moved = _move(api, entry, barn, east - 3_000, north)
    assert moved.status_code == 200, moved.text
    # A building stands on its zone's graded pad: moving it leaves every chunk as it was made.
    after_barn = api.get(_path(entry, "/site")).json()
    assert after_barn["land"]["chunks"] == made_drawing["land"]["chunks"]
    pond = _parts(api, entry)["pond"]
    pond_east, pond_north = pond["centre_mm"]
    dug = _move(api, entry, pond, pond_east - 2_000, pond_north)
    assert dug.status_code == 200, dug.text
    drawing = api.get(_path(entry, "/site")).json()
    slot = next(s for s in drawing["slots"] if s["identity"] == barn["part_id"])
    assert slot["positionMm"][:2] == [east - 3_000, north]
    # The pond's basin moved, so the land was graded again: its chunks are not the made ones. The
    # backdrop is the natural land, never graded, so it is not asked to change.
    assert drawing["land"]["chunks"] != made_drawing["land"]["chunks"]
    # Every chunk and the backdrop are served by the digests the changed drawing names.
    for chunk in drawing["land"]["chunks"]:
        x, y = chunk["chunk"]
        served = api.get(_path(entry, f"/land/chunks/{x}/{y}"))
        assert served.status_code == 200, served.text
        assert served.headers["etag"] == f'"{chunk["sha256"]}"'
    backdrop = api.get(_path(entry, "/land/backdrop"))
    assert backdrop.headers["etag"] == f'"{drawing["land"]["backdrop_sha256"]}"'


def _storeys(api, entry: dict, part: dict, storeys: int, *, preview: bool = False):
    tail = f"/parts/{part['part_id']}/storeys" + ("/preview" if preview else "")
    return api.post(
        _path(entry, tail), {"base_state_sha256": _base(api, entry), "storeys": storeys}
    )


def test_a_building_stands_taller_and_lower_within_its_bound_and_a_move_keeps_it(made):
    api = made
    entry = _farm(api)
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": THINGS}
    )
    assert created.status_code in (200, 201), created.text
    before = _step(api, entry)
    read = api.get(_path(entry, "/parts")).json()
    most = read["storeys_most"]
    barn = next(part for part in read["parts"] if part["part_key"] == "barn")
    made_slot = _drawn(api, entry, barn["part_id"])
    made_height = made_slot["boxMm"][2]
    taller = barn["storeys"] + 1

    ready = _storeys(api, entry, barn, taller, preview=True)
    assert ready.json()["availability"] == "ready", ready.text
    assert ready.json()["would_change"]["kind"] == "part_storeys"
    kept = _storeys(api, entry, barn, taller)
    assert kept.status_code == 200, kept.text
    (override,) = (
        o for o in kept.json()["element_overrides"] if o["element_id"] == f"part:{barn['part_id']}"
    )
    assert override["storeys"] == taller and override["transform"] is None
    assert _parts(api, entry)["barn"]["storeys"] == taller
    slot = _drawn(api, entry, barn["part_id"])
    assert slot["boxMm"][2] == made_height * taller // barn["storeys"]
    assert slot["positionMm"] == made_slot["positionMm"]

    over = _storeys(api, entry, barn, most + 1)
    assert over.status_code == 422, over.text
    assert over.json()["code"] == "part_storeys_refused"
    assert over.json()["detail"] == (
        f"Not taller: buildings in this world have at most {most} storeys."
    )
    # A move keeps the storeys the version states for the building.
    east, north = barn["centre_mm"]
    moved = _move(api, entry, barn, east - 3_000, north)
    assert moved.status_code == 200, moved.text
    assert _parts(api, entry)["barn"]["storeys"] == taller
    # The society keeps stepping, its input available.
    after = _step(api, entry)
    assert after["current_tick"] == before["current_tick"] + 1
    assert _consumed_input(api, entry)["availability"] == "available"

    for _change in range(2):
        undone = api.post(_path(entry, "/things/undo"), {"base_state_sha256": _base(api, entry)})
        assert undone.status_code == 200, undone.text
    assert _parts(api, entry)["barn"]["storeys"] == barn["storeys"]
    assert _drawn(api, entry, barn["part_id"]) == made_slot


def test_a_storeys_change_alone_gives_the_society_the_same_walking_place(made):
    api = made
    entry = _farm(api)
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": THINGS}
    )
    assert created.status_code in (200, 201), created.text
    _step(api, entry)
    made_input = _consumed_input(api, entry)
    barn = _parts(api, entry)["barn"]
    kept = _storeys(api, entry, barn, barn["storeys"] + 1)
    assert kept.status_code == 200, kept.text
    _step(api, entry)
    taken = _consumed_input(api, entry)
    assert taken["availability"] == "available"
    # The change is taken in as the next input (the records the place digests changed) ...
    assert taken["authored_state"]["edit_seq"] == kept.json()["edit_seq"]
    # ... and only the ground storey is walked: the people's nodes and edges are the made ones.
    assert taken["navigation"]["nodes"] == made_input["navigation"]["nodes"]
    assert taken["navigation"]["edges"] == made_input["navigation"]["edges"]


def test_a_part_s_changes_hold_on_a_version_branched_from_the_made_one(made):
    """A version branched from the made world's own takes each part change through the same routes
    (a move, a turn, a storeys change, a removal), and the version it was branched from keeps its
    parts as they were made: the path a project's part changes are applied by."""
    api = made
    entry = _farm(api)
    made_parts = _parts(api, entry)
    branched = api.post(
        f"/world/versions?world_id={entry['world_id']}",
        {"title": "A branch", "parent_version_id": entry["authored_version_id"]},
    )
    assert branched.status_code == 201, branched.text
    branch = {**entry, "authored_version_id": branched.json()["version_id"]}
    assert _parts(api, branch) == made_parts
    barn, bench = made_parts["barn"], made_parts["bench"]
    east, north = barn["centre_mm"]
    made_slot = _drawn(api, branch, barn["part_id"])

    moved = _move(api, branch, barn, east - 3_000, north)
    assert moved.status_code == 200, moved.text
    turned = _move(api, branch, barn, east - 3_000, north, 2)
    assert turned.status_code == 200, turned.text
    taller = _storeys(api, branch, barn, barn["storeys"] + 1)
    assert taller.status_code == 200, taller.text
    removed = api.post(
        _path(branch, f"/parts/{bench['part_id']}/remove"),
        {"base_state_sha256": _base(api, branch)},
    )
    assert removed.status_code == 200, removed.text

    parts = _parts(api, branch)
    assert parts["barn"]["centre_mm"] == [east - 3_000, north]
    assert parts["barn"]["storeys"] == barn["storeys"] + 1
    assert bench["part_id"] not in {part["part_id"] for part in parts.values()}
    slot = _drawn(api, branch, barn["part_id"])
    assert slot["positionMm"] != made_slot["positionMm"] and slot != made_slot
    overrides = {o["element_id"]: o for o in removed.json()["element_overrides"]}
    override = overrides[f"part:{barn['part_id']}"]
    assert override["storeys"] == barn["storeys"] + 1 and override["transform"] is not None
    # The version it was branched from is as it was made.
    assert _parts(api, entry) == made_parts
    assert _drawn(api, entry, barn["part_id"]) == made_slot
