"""A thing placed on the shipped island hamlet's open top through the normal route: the grass by
the arrival takes it, resting on the highest of the graded top under it as the place's preview
said, and its society of things reads it resting there, not off the ground, across a bank too,
where it reads a thing by the highest of the top under its footprint as the placing does;
past the island's rim it is refused as past the world's edge and nothing is written
(``exulanica/world/site_top_ground.py``)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.generated_worlds import generation_receipt
from exulanica.world.kinds import worker
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, ThingPlacement, named_kind
from exulanica.world.site_top_ground import TopGround
from exulanica.world.society_walking_surfaces import RESTS_ON_SURFACE_MM
from exulanica.world.thing_landing import footprint_points

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


def _across_a_bank(api, entry: dict) -> list[tuple[int, int, int, int]]:
    """Points of the island's site, east and south, where a well's footprint spans a step of the
    graded top beyond the step a thing rests across, with the top's height at the well's centre and
    the highest under it, read from the top the kind worker states with the island's place."""
    with api.database.session(api.repository.workspace_id) as connection:
        _, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    records = tuple(site_plan.records(receipt))
    top = TopGround.read(worker._placed(worker.site_ground_place_id(), receipt, records)["top"])
    found = []
    for east in range(1_000, 22_000, 500):
        for north in range(1_000, 22_000, 500):
            well = PlacedThing(
                "well",
                named_kind("well", 2),
                "region:generated",
                Transform(east, 0, -north, 0, 1000),
                ObjectOrigin("authored", "fictional"),
            )
            centre = top.height_at((east, -north))
            highest = max(top.height_at(point) for point in footprint_points(well))
            if RESTS_ON_SURFACE_MM + 20 < highest - centre < 3 * RESTS_ON_SURFACE_MM:
                found.append((east, -north, centre, highest))
    return found


def _stand(api, entry: dict, thing_id: str, east: int, south: int, height: int) -> None:
    """A well stood at a height the placing would not answer, as a writer not held to the ground's
    rule may still stand one: the society reads it as it stands."""
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"]
        )
        version = objects.version(uuid.UUID(entry["authored_version_id"]))
        objects.add_thing(
            version.version_id,
            ThingPlacement(
                thing_id=thing_id,
                kind=named_kind("well", 2),
                region_id="region:generated",
                transform=Transform(east, height, south, 0, 1000),
                origin=ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=version.state_sha256,
            actor=api.actor,
            landing=None,
        )


def test_the_society_of_things_reads_a_well_across_a_bank_by_the_highest_ground_under_it(made):
    """A well the placing rests on the highest of the top under its footprint is read resting
    there, though the top at its centre is more than the resting step lower; one stood at its
    centre's height is read off the ground, which shows the reading is the footprint's."""
    api = made
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services, societies_of_things=True
    )
    entry = _island(api)
    banks = _across_a_bank(api, entry)
    placed = None
    for east, south, centre, highest in banks:
        pose = {"x_mm": east, "y_mm": highest, "z_mm": south, "yaw_microradians": 0}
        if _placing(api, entry, "well", pose).status_code == 201:
            placed = (east, south, centre, highest)
            break
    assert placed is not None, f"no bank of {len(banks)} took a well"
    # The control: a second well across another bank, stood at its centre's height.
    others = [bank for bank in banks if abs(bank[0] - placed[0]) + abs(bank[1] - placed[1]) > 4_000]
    east, south, centre, _highest = others[0]
    _stand(api, entry, "well-at-its-centre", east, south, centre)
    created = api.post(
        _path(entry, "/society"), {"region_id": "region:generated", "profile": THINGS}
    )
    assert created.status_code in (200, 201), created.text
    things = {thing["placed_id"]: thing for thing in latest_input(api, entry)["things"]}
    assert "height_mm" not in things["well"]
    assert things["well-at-its-centre"]["height_mm"] < -RESTS_ON_SURFACE_MM
