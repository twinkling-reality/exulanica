"""A world made on a placed volume's top (site-plan composer version 7): a hamlet laid out on a sky
island's top land and graded there, kept as a receipt that reads back to the same records and
ground, drawn as ``exulanica.site-drawing/v6`` with its top, its people standing on the graded
heights, arriving to face the nearest open rim, and its landscape drawn round it as
``exulanica.landscape-drawing/v2``, the island capped by the graded top over the ground below;
refused by name where the kind or the site does not fit the top, and where a receipt's landscape and
composer disagree."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from exulanica.grammar.grammars.site.records import SiteExtentRecord, SiteStructureRecord
from exulanica.grammar.islands import make_island_volume, read_island_document
from exulanica.grammar.landform import land_rules, read_land_chunk
from exulanica.grammar.landscape import LandscapeRefused, landscape_rules, read_landscape_document
from exulanica.grammar.volumes import input_sha256, read_volume_sheet
from exulanica.world import site_on_top
from exulanica.world.composers import site_plan
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.kinds import worker
from exulanica.world.landscape_drawing import TOP_LANDSCAPE_DRAWING_PROFILE
from exulanica.world.site_drawing import TOP_DRAWING_PROFILE, site_drawing
from exulanica.world.site_land import site_land_of
from exulanica.world.site_on_top import ROCK_UNDER_MM, TopWorld
from exulanica.world.site_top import SITE_TOP_PROFILE, TOP_DATUM

from test_landscape_document import BAY
from test_site_land import kind
from test_sky_island import HIGH, HILL_TOP

WORLD = "world:generated:island"
STATION_MM = 4000
#: A single-lobed island 40 m across whose top is a gentle hill, weathered lightly.
ISLE = {
    **HIGH,
    "id": "isle",
    "lobes": 1,
    "rim_mm": 6000,
    "depth_mm": 30000,
    "erosion": {"amplitude_mm": 1200, "wavelength_mm": 9000, "octaves": 3, "ridged": "yes"},
    "strata": {**HIGH["strata"], "amplitude_mm": 700, "period_mm": 3000, "spread_mm": 800},
    "top": HILL_TOP,
}
ISLAND = make_island_volume(read_island_document(ISLE), b"island test").canonical()
#: The bay with the island floating 60 m up beyond its stacks, a 22 m hamlet laid out on its top.
LANDSCAPE = {
    **BAY,
    "volumes": [
        *BAY["volumes"],
        {"id": "isle", "volume": ISLAND, "at_mm": [70000, 60000, 60000]},
    ],
    "site": {"on": "isle", "at_mm": [-11000, -11000]},
}


def compose(name: str = "hamlet", **site: object) -> Any:
    found = kind(name)
    landscape = copy.deepcopy(LANDSCAPE)
    landscape["site"].update(site)
    return site_plan.compose_kind(
        found, found.values(found.presets[0][0]), WORLD, place_id="place:isle", landscape=landscape
    )


@pytest.fixture(scope="module")
def made() -> Any:
    return compose()


def ground_of(world: Any) -> TopWorld:
    ground = site_land_of(world.receipt, world.records, STATION_MM)
    assert isinstance(ground, TopWorld)
    return ground


def test_a_hamlet_is_made_on_the_islands_top_and_its_receipt_reads_back(made) -> None:
    receipt = made.receipt
    assert receipt["composer"] == {"key": "site-plan", "version": site_plan.TOP_COMPOSER_VERSION}
    # Its land is the island's top land, under the land rules volume rules 3 name for a top.
    assert receipt["land"] == ISLAND["top_land"]["land"]
    assert receipt["land_rules"] == land_rules(3)
    assert receipt["landscape_rules"] == landscape_rules()
    assert receipt["landscape"]["site"] == {"on": "isle", "at_mm": [-11000, -11000],
                                           "cut_fill_mm": 2000}  # fmt: skip
    site_plan.check_receipt(receipt)
    assert site_plan.records(receipt) == made.records
    # The spawn stands on the graded top at the arrival.
    east, north = receipt["arrival"]["position_mm"]
    (spawn,) = made.candidate.placement["destinations"]
    assert (spawn["x_mm"], spawn["y_mm"], spawn["z_mm"]) == (
        east,
        ground_of(made).height_at(east, north),
        -north,
    )
    assert made.candidate.composer_version == site_plan.TOP_COMPOSER_VERSION


def test_people_stand_on_the_graded_top_and_the_place_says_what_it_stands_above(made) -> None:
    ground = ground_of(made)
    nodes = made.place["nodes"]
    assert nodes and all(
        node["support_z_mm"] == ground.height_at(*node["position_mm"]) for node in nodes
    )
    # The hill under the site is graded, not flattened away: heights above the island's level 0.
    assert min(node["support_z_mm"] for node in nodes) > 0
    assert made.place["frame"]["datum"] == TOP_DATUM
    again = site_plan.society_place("place:isle", made.receipt, made.records)
    assert again == made.place


def test_the_drawing_stands_on_the_top_and_names_it_by_digest(made) -> None:
    drawing = site_drawing(
        world_id=WORLD, receipt=made.receipt, receipt_sha256=made.receipt_sha256,
        records=made.records,
    )  # fmt: skip
    ground = ground_of(made)
    assert drawing["profile"] == TOP_DRAWING_PROFILE and "land" not in drawing
    top = drawing["top"]
    assert top["top_sha256"] == ground.site.sha256
    assert top["landscape_sha256"] == made.receipt["landscape_sha256"]
    assert (top["placement"], top["offset_mm"], top["water"]) == ("isle", [-11000, -11000], [])
    east, north = made.receipt["arrival"]["position_mm"]
    assert drawing["arrival"]["positionMm"] == [east, north, ground.height_at(east, north)]
    assert drawing["arrival"]["facingMm"] == made.receipt["arrival"]["facing_mm"]
    # Every cell of the site is drawn as land: rock lies under all of it.
    near = ground.site.graded.near
    drawn = {
        (row, column) for row, first, last in top["rock_cells"] for column in range(first, last + 1)
    }
    extent = next(r for r in made.records if isinstance(r, SiteExtentRecord))
    site_cells = {
        ((y - near.y0) // 1000, (x - near.x0) // 1000)
        for y in range(0, extent.depth_mm, 1000)
        for x in range(0, extent.width_mm, 1000)
    }
    assert site_cells <= drawn
    # Beyond the rim of the round island the square's corners are not drawn.
    assert (0, 0) not in drawn and (near.ny - 2, near.nx - 2) not in drawn
    # The worker keeps the graded top with the drawing for the land route, and no chunks.
    kept = worker._drawn(WORLD, made.receipt, made.receipt_sha256, made.records)
    assert kept["land"]["chunks"] == {}
    assert kept["land"]["top"]["sha256"] == top["top_sha256"]
    assert SITE_TOP_PROFILE in kept["land"]["top"]["body"]


def test_a_person_arrives_outside_the_gate_facing_an_open_rim_away_from_the_site(made) -> None:
    ground = ground_of(made)
    extent = next(r for r in made.records if isinstance(r, SiteExtentRecord))
    east, north = made.receipt["arrival"]["position_mm"]
    # On the open top just outside the gate in the site's south edge, on rock.
    assert east == extent.entry_x_mm and -3_000 <= north <= -1_500, (east, north)
    at_east, at_north = ground.site.on.at_mm
    assert (
        ground.field.distance(
            east + at_east, north + at_north, ground.height_at(east, north) - ROCK_UNDER_MM
        )
        <= 0
    )
    # Facing away from the site, so its fence and buildings are behind.
    fx, fy = made.receipt["arrival"]["facing_mm"]
    assert fy < 0 and 990 <= abs(complex(fx, fy)) <= 1001
    buildings = [r for r in made.records if isinstance(r, SiteStructureRecord)]
    rim = None
    for distance in range(250, 40_000, 250):
        x, y = east + fx * distance // 1000, north + fy * distance // 1000
        assert not any(
            b.min_x_mm <= x <= b.max_x_mm and b.min_y_mm <= y <= b.max_y_mm for b in buildings
        ), (x, y)
        top = ground.height_at(x, y)
        if ground.field.distance(x + at_east, y + at_north, top - ROCK_UNDER_MM) > 0:
            rim = distance
            break
    # The rim lies ahead within reach, the sea below it.
    assert rim is not None and rim <= 25_500, rim


#: The bay's land with its sea to the south: every point beyond the extent's south edge is sea.
SEA_SOUTH = {
    **LANDSCAPE["land"],
    "features": [
        {"id": "bay", "kind": "shore", "side": "south", "distance_mm": 0, "beach_mm": 10000,
         "beach_top_mm": 2000, "sea_depth_mm": 18000, "wander_mm": 0},
    ],
}  # fmt: skip


def over_the_sea(*others: dict[str, Any]) -> dict[str, Any]:
    """The island 120 m out over the sea south of the bay, with ``others`` placed beside it."""
    return {
        **LANDSCAPE,
        "land": SEA_SOUTH,
        "volumes": [{"id": "isle", "volume": ISLAND, "at_mm": [64000, -120000, 60000]}, *others],
    }


def test_a_person_arrives_facing_another_island_over_the_rim_rather_than_open_sea() -> None:
    found = kind("hamlet")
    values = found.values(found.presets[0][0])

    def facing(landscape: dict[str, Any]) -> list[int]:
        made = site_plan.compose_kind(
            found, values, WORLD, place_id="place:isle", landscape=landscape
        )
        return made.receipt["arrival"]["facing_mm"]

    # Alone over the sea, every open rim looks at open sea: the nearest is taken.
    alone = facing(over_the_sea())
    # Another island 120 m east at the same height: among the open rims, the one facing it.
    beside = facing(
        over_the_sea({"id": "far_isle", "volume": ISLAND, "at_mm": [184000, -120000, 60000]})
    )
    assert beside == [1000, 0]
    assert alone != beside


def test_a_site_that_fills_its_top_to_the_rim_stands_its_arrival_in_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no room outside the gate, a person arrives in the gate's opening, still facing out.
    monkeypatch.setattr(site_on_top, "GATE_CLEAR_MM", ())
    world = compose()
    extent = next(r for r in world.records if isinstance(r, SiteExtentRecord))
    assert world.receipt["arrival"]["position_mm"] == [extent.entry_x_mm, 0]
    assert world.receipt["arrival"]["facing_mm"][1] < 0


def test_a_kind_whose_people_come_from_homes_off_the_site_is_refused() -> None:
    with pytest.raises(LandscapeRefused) as caught:
        compose("cafe")
    assert (caught.value.code, caught.value.path) == (
        "landscape_site_offsite_homes",
        "landscape.site",
    )
    assert "homes off the site" in caught.value.detail


@pytest.mark.parametrize(
    ("at_mm", "code"),
    [
        # 22 m from (8, 8) reaches 30 m east and north, past the 22 m half of the 44 m square.
        ([8000, 8000], "landscape_site_outside_top"),
        # Inside the square, but its south-west corner is past the round island's rim.
        ([-21000, -21000], "landscape_site_not_on_rock"),
    ],
)
def test_a_site_too_large_for_the_top_or_off_its_rock_is_refused_before_layout(
    at_mm: list[int], code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("no candidate is laid out")

    monkeypatch.setattr(site_plan, "compose_site", never)
    with pytest.raises(LandscapeRefused) as caught:
        compose(at_mm=at_mm)
    assert (caught.value.code, caught.value.path) == (code, "landscape.site")


def test_a_receipt_whose_landscape_and_composer_disagree_is_refused(made) -> None:
    receipt = copy.deepcopy(made.receipt)
    del receipt["landscape"]["site"]
    with pytest.raises(InvalidStructuralData, match="generated_world_landscape_changed"):
        site_plan.check_receipt(receipt)
    on_land = copy.deepcopy(made.receipt)
    on_land["composer"]["version"] = site_plan.LANDSCAPE_COMPOSER_VERSION
    with pytest.raises(InvalidStructuralData, match="generated_world_landscape_changed"):
        site_plan.check_receipt(on_land)


def test_a_part_edit_is_held_to_the_islands_rock(made, monkeypatch: pytest.MonkeyPatch) -> None:
    assert worker._graded(made.receipt, made.records, "part:any") is None
    # Asked for rock deeper than the island holds under its top, the same layout is refused by the
    # rock rule's code with the sentence a person reads.
    monkeypatch.setattr("exulanica.world.site_on_top.ROCK_UNDER_MM", 60_000)
    refused = worker._graded(made.receipt, made.records, "part:any")
    assert refused is not None
    assert (refused["code"], refused["where"]["landform_code"]) == (
        "landscape_site_not_on_rock",
        "landscape_site_not_on_rock",
    )
    assert refused["detail"] == "Not here: there would be no rock under the ground there."


@pytest.fixture(scope="module")
def landscape_drawn(made) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The site's drawing as the worker keeps it, and the landscape's drawing and documents."""
    drawn = worker._drawn(WORLD, made.receipt, made.receipt_sha256, made.records)
    job = worker.landscape_job(
        WORLD, made.receipt, made.receipt_sha256, drawn["sha256"], drawn["land"]["top"]
    )
    assert job["status"] == "done", job
    return drawn, json.loads(job["body"]), job


def test_the_landscape_is_drawn_round_the_site_with_the_islands_graded_top(
    made, landscape_drawn
) -> None:
    drawn, drawing, job = landscape_drawn
    assert drawing["profile"] == TOP_LANDSCAPE_DRAWING_PROFILE
    assert drawing["site_drawing_sha256"] == drawn["sha256"]
    assert drawing["top_sha256"] == json.loads(drawn["body"])["top"]["top_sha256"]
    assert drawing["land_sha256"] == made.receipt["land_sha256"]
    # The site's south-west corner, in the landscape's frame: the island's origin and the site's
    # corner on its top, the island unturned.
    assert drawing["site_frame"] == {"placement": "isle", "at_mm": [59000, 49000, 60000],
                                     "yaw_mdeg": 0}  # fmt: skip
    ground = ground_of(made)
    isle = next(volume for volume in drawing["volumes"] if volume["id"] == "isle")
    assert isle["input_sha256"] == input_sha256(ground.field)
    # The island's walked top is the graded top under the site, within a quarter of its blend.
    east, north = ground.site.on.at_mm
    extent = next(r for r in made.records if isinstance(r, SiteExtentRecord))
    blend = ISLAND["top_land"]["blend_mm"]
    compared = 0
    for top in isle["tops"]:
        sheet = read_volume_sheet(json.loads(job["tops"][top["sha256"]]), top["sha256"])
        x0, y0 = sheet.origin_mm
        for row, first, last in sheet.walkable:
            for column in range(first, last + 1):
                x, y = x0 + column * 1000 - east, y0 + row * 1000 - north
                if 0 <= x <= extent.width_mm and 0 <= y <= extent.depth_mm:
                    height = sheet.height_mm[row * sheet.columns + column]
                    graded = ground.height_at(x, y)
                    assert graded - blend // 4 - 1 <= height <= graded, (x, y, height, graded)
                    compared += 1
    # Most of the site is walked on the island's own top; the banks between its terraces, steeper
    # than 1 in 4, are not.
    assert compared >= (extent.width_mm // 1000) * (extent.depth_mm // 1000) * 3 // 4


def test_the_ground_below_the_island_is_drawn_and_served_by_digest(landscape_drawn) -> None:
    _, drawing, job = landscape_drawn
    ground = drawing["ground"]
    assert ground["land_sha256"] == read_landscape_document(LANDSCAPE).land.sha256
    assert ground["chunk_mm"] == 128_000 and len(ground["chunks"]) >= 4
    named = [chunk["sha256"] for chunk in ground["chunks"]] + [ground["backdrop_sha256"]]
    assert sorted(job["ground"]) == sorted(named)
    for chunk in ground["chunks"]:
        read = read_land_chunk(json.loads(job["ground"][chunk["sha256"]]), chunk["sha256"])
        assert [read.chunk_x, read.chunk_y] == chunk["chunk"]


def test_a_landscape_drawing_without_the_sites_kept_top_or_with_another_is_refused(
    made, landscape_drawn
) -> None:
    drawn, _, _ = landscape_drawn
    for top in (None, {**drawn["land"]["top"], "sha256": "0" * 64}):
        refused = worker.landscape_job(
            WORLD, made.receipt, made.receipt_sha256, drawn["sha256"], top
        )
        assert refused["status"] == "refused"
        assert "generated_world_unreadable" in refused["detail"]
