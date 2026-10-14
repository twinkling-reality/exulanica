"""A society read says which authored edit its newest minute took in.

The read's places (``?places=true``) are copied from the one input the society's current state
consumed; they also state that input's ``authored_state``, the version's edit and digest it was
composed from. An edit made since is queued as the next input and not yet taken in, so the read
keeps naming the earlier edit until a step consumes it. A page compares it with the version's own
edit log to know which things the minute it draws has not seen yet.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import saved_entries

from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
V7 = "exulanica-society/v7"
FARM = "world:generated:00000000-0000-4000-8000-00000000f0c1"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_farm_on_every_run(monkeypatch):
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: FARM)


def _farm(api) -> dict[str, Any]:
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    document["origin"] = "uploaded"
    document["provenance"] = {"by": "a test creator"}
    assert api.post("/worlds/kinds", {"document": document}).status_code == 201
    made_world = api.post(
        "/worlds/kinds/fixture_farm/worlds", {"preset": "small_farm", "title": "A farm"}
    )
    assert made_world.status_code == 201, made_world.text
    return made_world.json()


def _path(entry: dict, tail: str = "", query: str = "") -> str:
    return (
        f"/world/versions/{entry['authored_version_id']}{tail}?world_id={entry['world_id']}{query}"
    )


def _version(api, entry: dict) -> dict:
    read = api.get(_path(entry))
    assert read.status_code == 200, read.text
    return read.json()


def _society(api, entry: dict) -> dict:
    read = api.get(_path(entry, "/society", "&places=true"))
    assert read.status_code == 200, read.text
    return read.json()


def _well_at(api, entry: dict, east_mm: int, south_mm: int, *, move: bool) -> dict:
    pose = {"x_mm": east_mm, "y_mm": 0, "z_mm": south_mm, "yaw_microradians": 0}
    base = _version(api, entry)["state_sha256"]
    if move:
        answer = api.post(
            _path(entry, "/things/well/move"), {"base_state_sha256": base, "pose": pose}
        )
        assert answer.status_code == 200, answer.text
    else:
        answer = api.post(
            _path(entry, "/things"),
            {
                "base_state_sha256": base,
                "thing_id": "well",
                "kind": {"kind": "well", "version": 2},
                "region_id": "region:generated",
                "pose": pose,
                "origin_role": "fictional",
            },
        )
        assert answer.status_code == 201, answer.text
    return answer.json()


def test_the_read_names_the_edit_its_minute_took_in_until_a_step_takes_a_later_one(made):
    api = made
    entry = _farm(api)
    east, _height, south = entry["generated_site"]["arrival_mm"]
    placed = _well_at(api, entry, east + 3_000, south, move=False)
    created = api.post(_path(entry, "/society"), {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text

    first = _society(api, entry)
    assert first["places"]["authored_state"] == {
        "edit_seq": placed["edit_seq"],
        "delta_sha256": placed["state_sha256"],
    }

    moved = _well_at(api, entry, east + 5_000, south, move=True)
    assert moved["edit_seq"] == placed["edit_seq"] + 1
    queued = _society(api, entry)
    # The move is queued, not taken in: the minute drawn is still the one before it.
    assert queued["current_tick"] == first["current_tick"]
    assert queued["places"]["authored_state"]["edit_seq"] == placed["edit_seq"]

    stepped = api.post(
        _path(entry, "/society/steps"),
        {"base_tick": queued["current_tick"], "base_state_sha256": queued["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    taken = _society(api, entry)
    assert taken["places"]["authored_state"] == {
        "edit_seq": moved["edit_seq"],
        "delta_sha256": moved["state_sha256"],
    }
