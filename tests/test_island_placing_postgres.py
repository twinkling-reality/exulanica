"""A thing placed on the shipped island hamlet's open top through the normal route: the grass by
the arrival takes it, resting on the highest of the graded top under it as the place's preview
said, and its society of things reads it resting there, not off the ground;
past the island's rim it is refused as past the world's edge and nothing is written
(``exulanica/world/site_top_ground.py``)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from test_society_made_world import made as imported_made  # noqa: F401
from test_support_placement_society_postgres import latest_input

pytestmark = pytest.mark.postgres

WELL = {"kind": "well", "version": 2}
THINGS = "exulanica-society/v7"


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _island(api) -> dict[str, Any]:
    """The shipped island hamlet, made as Create a world's card makes it."""
    listed = {kind["kind"]: kind for kind in api.get("/worlds/kinds").json()["kinds"]}
    card = listed["island_hamlet"]
    made = api.post(
        "/worlds/kinds/island_hamlet/worlds",
        {"version": card["version"], "preset": card["presets"][0]["key"], "title": card["label"]},
    )
    assert made.status_code == 201, made.text
    return dict(made.json())


def _path(entry: dict, tail: str = "") -> str:
    return f"/world/versions/{entry['authored_version_id']}{tail}?world_id={entry['world_id']}"


def _base(api, entry: dict) -> str:
    read = api.get(_path(entry))
    assert read.status_code == 200, read.text
    return str(read.json()["state_sha256"])


def _placing(api, entry: dict, thing_id: str, pose: dict[str, int], *, preview: bool = False):
    return api.post(
        _path(entry, "/things" + ("/preview" if preview else "")),
        {
            "base_state_sha256": _base(api, entry),
            "thing_id": thing_id,
            "kind": WELL,
            "region_id": "region:generated",
            "pose": pose,
            "origin_role": "fictional",
        },
    )


def _beside_the_arrival(entry: dict, east_mm: int) -> dict[str, int]:
    """A pose on the open top beside where a person arrives, outside the hamlet's gate, at the
    height a person stands there."""
    east, height, south = entry["generated_site"]["arrival_mm"]
    return {"x_mm": east + east_mm, "y_mm": height, "z_mm": south, "yaw_microradians": 0}


def test_a_well_by_the_arrival_lands_on_the_islands_top_as_its_preview_said(made):
    api = made
    entry = _island(api)
    pose = _beside_the_arrival(entry, 0)
    verdict = _placing(api, entry, "well", pose, preview=True)
    assert verdict.status_code == 200, verdict.text
    assert verdict.json()["availability"] == "ready"
    # Asked where a person stands, it rests on the highest of the island's top under its
    # footprint, within the step a thing rests across, and is placed there as the page places it.
    landing = verdict.json()["landing"]
    assert landing["checked"] is True
    assert 0 <= landing["rest_y_mm"] - pose["y_mm"] <= 200
    placed = _placing(api, entry, "well", {**pose, "y_mm": landing["rest_y_mm"]})
    assert placed.status_code == 201, placed.text


def test_past_the_islands_rim_a_placing_is_past_the_edge_and_nothing_is_written(made):
    api = made
    entry = _island(api)
    before = _base(api, entry)
    east, height, south = entry["generated_site"]["arrival_mm"]
    # Thirty metres south of the arrival, which stands outside the gate in the site's south edge,
    # is past the rim of an island some forty metres across.
    refused = _placing(
        api,
        entry,
        "well",
        {"x_mm": east, "y_mm": height, "z_mm": south + 30_000, "yaw_microradians": 0},
    )
    assert refused.status_code == 422, refused.text
    assert (refused.json()["code"], refused.json()["detail"]) == (
        "thing_landing_outside",
        "That spot is past the edge of this world.",
    )
    assert _base(api, entry) == before


def test_the_society_of_things_reads_a_well_by_the_arrival_resting_on_the_top(made):
    """The hamlet's walking lines stand on its paving, above the open top round it: read by its
    nearest line, a well on the grass by the arrival would stand below the ground."""
    api = made
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    entry = _island(api)
    placed = _placing(api, entry, "well", _beside_the_arrival(entry, 1_000))
    assert placed.status_code == 201, placed.text
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": THINGS}
    )
    assert created.status_code in (200, 201), created.text
    things = latest_input(api, entry)["things"]
    (well,) = [thing for thing in things if thing["placed_id"] == "well"]
    assert "height_mm" not in well
