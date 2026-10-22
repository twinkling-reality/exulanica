"""A thing placed on a sky island's top (site-plan composer version 7): the kind worker states the
top with the place it makes (``exulanica.top-ground/v1``), read as
:class:`~exulanica.world.site_top_ground.TopGround`. A placing stands anywhere on the top's land
out to its rim, where a person walks, and rests on the graded top the page draws, the site
included, on the highest of it under its footprint; across a bank's step within the step a thing
rests across it lands, and beyond that it is told how much higher the ground is; past the rim it
is past the world's edge, and in the top's own water it is in the water."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from exulanica.grammar.grammars.site.records import SiteExtentRecord
from exulanica.world.composers import site_plan
from exulanica.world.kinds import worker
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind
from exulanica.world.site_drawing import site_drawing
from exulanica.world.site_top_ground import (
    TOP_GROUND_PROFILE,
    TopGround,
    top_ground_document,
    top_landing,
)
from exulanica.world.society_authored_ground import WalkableArea
from exulanica.world.society_walking_surfaces import RESTS_ON_SURFACE_MM, rests_on_surface
from exulanica.world.thing_landing import (
    LandingGround,
    footprint_half_extents,
    footprint_points,
    landing_refusal,
)

from test_site_land import FIXTURES, kind
from test_site_on_island import LANDSCAPE, WORLD, compose, ground_of

WELL = named_kind("well", 2)


@pytest.fixture(scope="module")
def hamlet() -> Any:
    return compose()


@pytest.fixture(scope="module")
def top(hamlet) -> dict[str, Any]:
    return worker._placed(worker.site_ground_place_id(), hamlet.receipt, hamlet.records)["top"]


def _arrival(hamlet) -> tuple[int, int]:
    """The arrival, a point of the region (east and south), on the open top outside the gate."""
    east, north = hamlet.receipt["arrival"]["position_mm"]
    return east, -north


def _area(hamlet) -> WalkableArea:
    """The site's rectangle, as a site world's ground states its walkable area (without the walking
    clearance the society adds past its edges, so the open top begins at the site's own edge)."""
    extent = next(r for r in hamlet.records if isinstance(r, SiteExtentRecord))
    half_x, half_z = extent.width_mm // 2, extent.depth_mm // 2
    return WalkableArea("ground", half_x, -half_z, half_x, half_z)


def _well(point: tuple[int, int], y: int) -> PlacedThing:
    return PlacedThing(
        "well",
        WELL,
        "region:generated",
        Transform(point[0], y, point[1], 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )


def _landing(hamlet, ground: TopGround) -> LandingGround:
    """A site world's landing on a top as ``thing_landing_source`` makes it."""
    return top_landing(ground, "region:generated", _area(hamlet), ())


def _refusal(landing: LandingGround, thing: PlacedThing):
    return landing_refusal(landing, thing, footprint_half_extents(thing))


def _step(ground: TopGround, point: tuple[int, int]) -> int:
    """How much higher the graded top stands under a well's footprint at ``point`` than at its
    centre, where the page stands it."""
    return max(ground.height_at(p) for p in footprint_points(_well(point, 0))) - ground.height_at(
        point
    )


def test_the_place_of_a_site_on_a_top_states_the_top_its_drawing_draws(hamlet, top) -> None:
    assert top == top_ground_document(ground_of(hamlet))
    assert top["profile"] == TOP_GROUND_PROFILE
    # The graded top the land route serves, and the cells the drawing draws as land.
    assert top["top"] == ground_of(hamlet).site.document()
    drawing = site_drawing(
        world_id=WORLD, receipt=hamlet.receipt, receipt_sha256=hamlet.receipt_sha256,
        records=hamlet.records,
    )  # fmt: skip
    assert top["rock_cells"] == drawing["top"]["rock_cells"]
    # The place is the one the society walks, unchanged by the top beside it.
    placed = worker._placed(worker.site_ground_place_id(), hamlet.receipt, hamlet.records)
    assert placed["place"] == site_plan.society_place(
        worker.site_ground_place_id(), hamlet.receipt, hamlet.records
    )


def test_the_place_kept_with_a_world_made_on_a_top_states_its_top() -> None:
    """The place a world's making keeps is the place job's answer, its top included, so a placing
    asked first after the making reads the open top."""
    document = json.loads((FIXTURES / "fixture-hamlet.json").read_text(encoding="utf-8"))
    found = kind("hamlet")
    made = worker.compose_job(
        "w", document, found.values(found.presets[0][0]), WORLD, None, None, LANDSCAPE
    )
    assert made["status"] == "done"
    composed = made["composed"]
    assert "top" in made["placed"]
    assert made["placed"] == worker._placed(
        made["place_id"], composed.receipt, tuple(composed.records)
    )


def test_a_site_on_level_ground_states_no_top() -> None:
    found = kind("hamlet")
    flat = site_plan.compose_kind(
        found, found.values(found.presets[0][0]), WORLD, place_id="place:flat"
    )
    placed = worker._placed(worker.site_ground_place_id(), flat.receipt, flat.records)
    assert placed["status"] == "done" and "top" not in placed


def test_the_open_top_reads_as_land_to_its_rim_at_the_graded_tops_height(hamlet, top) -> None:
    ground = TopGround.read(top)
    graded = ground_of(hamlet)
    arrival = _arrival(hamlet)
    assert ground.reads(arrival) == "land"
    # The graded top's height, off the site and on it, in the region's frame.
    for point in (arrival, (1_000, -1_000), (11_000, -11_000)):
        assert ground.height_at(point) == graded.height_at(point[0], -point[1])
    # The square's corners lie past the round island's rim.
    near = graded.site.graded.near
    assert ground.reads((near.x0 + 500, -(near.y0 + 500))) is None
    # Walking from the arrival the way it faces meets the rim, past which nothing is land.
    fx, fy = hamlet.receipt["arrival"]["facing_mm"]
    reads = [
        ground.reads((arrival[0] + fx * step // 1000, arrival[1] - fy * step // 1000))
        for step in range(0, 40_000, 250)
    ]
    rim = reads.index(None)
    assert rim > 0 and set(reads[:rim]) == {"land"}


def test_a_placing_by_the_arrival_lands_on_the_top_and_past_the_rim_is_refused(hamlet, top) -> None:
    ground = TopGround.read(top)
    arrival = _arrival(hamlet)
    height = ground.height_at(arrival)
    # Held to the site's rectangle alone, the grass by the arrival is past the edge.
    without = _refusal(
        LandingGround("region:generated", _area(hamlet), rests_on_surface(ground.height_at), ()),
        _well(arrival, height),
    )
    assert without is not None and without.code == "thing_landing_outside"
    landing = _landing(hamlet, ground)
    assert _refusal(landing, _well(arrival, height)) is None
    lifted = _refusal(landing, _well(arrival, height + 1_000))
    assert lifted is not None and lifted.code == "thing_landing_off_ground"
    near = ground_of(hamlet).site.graded.near
    corner = (near.x0 + 1_500, -(near.y0 + 1_500))
    past = _refusal(landing, _well(corner, ground.height_at(corner)))
    assert past is not None
    assert (past.code, str(past)) == (
        "thing_landing_outside",
        "That spot is past the edge of this world.",
    )


def test_across_a_bank_a_thing_rests_on_the_highest_of_the_top_under_it(hamlet, top) -> None:
    """The page stands a thing on the graded top at its centre; the landing rests it on the highest
    of the top under its footprint, the site included, so no foot of it sinks into the bank: within
    the step a thing rests across it lands there, and beyond it the words say how much higher."""
    ground = TopGround.read(top)
    landing = _landing(hamlet, ground)
    points = [(x, -north) for x in range(500, 22_000, 500) for north in range(500, 22_000, 500)]
    within = next(p for p in points if 50 <= _step(ground, p) <= RESTS_ON_SURFACE_MM)
    beyond = next(p for p in points if _step(ground, p) > RESTS_ON_SURFACE_MM + 50)
    posed = _well(within, ground.height_at(within))
    assert _refusal(landing, posed) is None
    assert landing.rest_height is not None and landing.rest_height(within) == ground.height_at(
        within
    )
    assert landing.resting_y(posed) == ground.height_at(within) + _step(ground, within)
    refused = _refusal(landing, _well(beyond, ground.height_at(beyond)))
    assert refused is not None and refused.code == "thing_landing_off_ground"
    assert refused.where == {"height_above_mm": -_step(ground, beyond)}
    assert str(refused).endswith("m higher. Choose a spot on the same level.")


def test_the_tops_own_water_refuses_a_placing_as_water(hamlet, top) -> None:
    arrival = _arrival(hamlet)
    plain = TopGround.read(top)
    height = plain.height_at(arrival)
    wet = copy.deepcopy(top)
    wet["top"]["water"] = [
        {"id": "pool", "kind": "lake", "level_mm": height + 500,
         "centre_mm": [arrival[0], -arrival[1]], "radius_mm": 4_000},
    ]  # fmt: skip
    ground = TopGround.read(wet)
    assert ground.reads(arrival) == "water"
    refused = _refusal(_landing(hamlet, ground), _well(arrival, height))
    assert refused is not None
    assert (refused.code, refused.where, str(refused)) == (
        "thing_landing_blocked",
        {"part": "water", "label": ""},
        "That spot is in the water.",
    )
    # Water below the graded top stands over nothing there.
    dry = copy.deepcopy(wet)
    dry["top"]["water"][0]["level_mm"] = height - 500
    assert TopGround.read(dry).reads(arrival) == "land"


def test_a_top_ground_of_another_profile_is_refused(top) -> None:
    with pytest.raises(ValueError, match="top-ground/v1"):
        TopGround.read({**top, "profile": "exulanica.top-ground/v0"})
