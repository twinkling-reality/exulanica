"""A site laid out on a volume's top land: the natural top the volume caps its rock by, moved into
the site's frame and graded as land is, so every zone is a level pad and every walking edge stays
within a step; the cut and fill held to the site's bound; a site off the square or a top with a sea
refused by name; and a site laid out on no top the level site it always was."""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest
from exulanica.grammar.grammars.site.records import SiteExtentRecord, SitePathRecord, SiteZoneRecord
from exulanica.grammar.landform import LandformRefused, read_land_document, water_bodies
from exulanica.grammar.volumes import TopLand, TopLandSurface, top_land_frame
from exulanica.grammar.volumes.rules import TOP_LAND_RULES, VOLUME_RULES_VERSION
from exulanica.world.kinds import samples
from exulanica.world.site_land import path_grade_permille
from exulanica.world.site_top import SITE_TOP_PROFILE, OnTop, site_top
from exulanica.world.society_place import STEP_LIMIT_MM

from test_site_land import kind

WORLD = "world:generated:top"
STATION_MM = 4000
SIDE_MM = 40000
#: The land rules the newest volume rules realize and grade a top land under.
TOP_RULES = TOP_LAND_RULES[VOLUME_RULES_VERSION]


def land(*features: dict) -> dict:
    return {"profile": "exulanica.landform/v1", "ground_mm": 0, "features": list(features)}


#: The tops a site is laid out on: level, a swell 1.5 m high every 20 m, and a tilt of 12 percent
#: rising to the north, each over a 40 m square.
LEVEL = land()
SWELL = land({"id": "swell", "kind": "undulation", "amplitude_mm": 1500, "wavelength_mm": 20000})
TILT = land({"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 120})


def on_top(raw: dict, at_mm: tuple[int, int] = (-8000, -10000), cut_fill_mm: int = 2000) -> OnTop:
    top = TopLand(land=read_land_document(raw), side_mm=SIDE_MM, blend_mm=0)
    return OnTop(
        top=top, volume_id="isle", at_mm=at_mm, cut_fill_mm=cut_fill_mm, rules_version=TOP_RULES
    )


def composed(top: OnTop | None):  # type: ignore[no-untyped-def]
    found = kind("cafe")
    return samples.compose_site(found, found.values(found.presets[0][0]), WORLD, top=top)


@pytest.fixture(scope="module")
def level_world():  # type: ignore[no-untyped-def]
    return composed(None)


@pytest.fixture(scope="module", params=["swell", "tilt"])
def top_world(request):  # type: ignore[no-untyped-def]
    on = on_top({"swell": SWELL, "tilt": TILT}[request.param])
    world = composed(on)
    return on, world, site_top(on, world.records, STATION_MM)


def test_the_cafe_fits_the_square_these_tests_place_it_in(level_world) -> None:
    extent = next(r for r in level_world.records if isinstance(r, SiteExtentRecord))
    assert extent.width_mm <= 16000 and extent.depth_mm <= 20000


def test_a_site_on_a_level_top_is_the_level_site_standing_at_the_top_height(level_world) -> None:
    world = composed(on_top(LEVEL))
    assert world.records == level_world.records
    assert world.output_digest == level_world.output_digest
    assert {node["support_z_mm"] for node in world.place["nodes"]} == {0}


def test_every_zone_is_a_level_pad_and_every_walking_edge_stays_within_a_step(top_world) -> None:
    _, world, graded = top_world
    near = graded.graded.near
    paths = [r for r in world.records if isinstance(r, SitePathRecord)]
    kept = [body.rect_mm for body in graded.water if body.kind == "pond"] + [
        (p.min_x_mm, p.min_y_mm, p.max_x_mm, p.max_y_mm) for p in paths
    ]
    zones = [r for r in world.records if isinstance(r, SiteZoneRecord)]
    for zone in zones:
        others = [(z.min_x_mm, z.min_y_mm, z.max_x_mm, z.max_y_mm) for z in zones if z is not zone]
        heights = {
            near.at(x, y)
            for x in range(-(-zone.min_x_mm // 1000) * 1000, zone.max_x_mm + 1, 1000)
            for y in range(-(-zone.min_y_mm // 1000) * 1000, zone.max_y_mm + 1, 1000)
            if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in kept + others)
        }
        assert len(heights) == 1, (zone.zone_key, sorted(heights))
    heights = {n["node_id"]: n["support_z_mm"] for n in world.place["nodes"]}
    # Eased banks (land rules 7) round a zone's edge, so the nodes there stand nearer its level: the
    # swell's spread is 294 mm under land rules 3 and 236 under 7.
    assert max(heights.values()) - min(heights.values()) > 200, "the site follows its top"
    for edge in world.place["edges"]:
        if edge["kind"] in ("crossing", "premises_access"):
            continue
        assert abs(heights[edge["from_node_id"]] - heights[edge["to_node_id"]]) <= STEP_LIMIT_MM
    for node in world.place["nodes"]:
        assert node["support_z_mm"] == graded.height_at(*node["position_mm"])


def test_a_path_climbs_no_more_than_one_step_over_its_longest_station(top_world) -> None:
    _, world, graded = top_world
    for path in (r for r in world.records if isinstance(r, SitePathRecord)):
        grade = path_grade_permille(path, STATION_MM)
        along_y = (path.max_y_mm - path.min_y_mm) >= (path.max_x_mm - path.min_x_mm)
        across = (path.min_x_mm + path.max_x_mm) if along_y else (path.min_y_mm + path.max_y_mm)
        middle = across // 2 // 1000 * 1000
        low, high = (path.min_y_mm, path.max_y_mm) if along_y else (path.min_x_mm, path.max_x_mm)
        stations = range(-(-low // 1000) * 1000, high + 1, 1000)
        profile = [
            graded.graded.near.at(*((middle, s) if along_y else (s, middle))) for s in stations
        ]
        assert max(abs(b - a) for a, b in pairwise(profile)) <= grade


def test_the_natural_top_is_the_one_the_volume_caps_its_rock_by(top_world) -> None:
    """Far from the site the grading leaves the top as it is: there the graded top is the volume's
    surface at the same point of the volume's frame, lattice point by lattice point."""
    on, _, graded = top_world
    surface = TopLandSurface(on.top, on.volume_id)
    near, (east, north) = graded.graded.near, on.at_mm
    half = SIDE_MM // 2
    corners = [(-half, -half), (half, -half), (-half, half), (half, half), (-half, 0)]
    for x, y in corners:
        assert near.at(x - east, y - north) == surface.height(x, y), (x, y)
    assert near.domain_mm == (-half - east, -half - north, half - east, half - north)


def test_cut_and_fill_stay_within_the_sites_bound_and_a_tighter_bound_is_refused(
    top_world,
) -> None:
    on, world, graded = top_world
    report = graded.graded.report
    assert max(report["max_cut_mm"], report["max_fill_mm"]) <= on.cut_fill_mm
    tight = dataclasses.replace(on, cut_fill_mm=100)
    with pytest.raises(LandformRefused) as caught:
        site_top(tight, world.records, STATION_MM)
    assert caught.value.code == "landform_cut_too_deep"
    assert "the bound is 100 mm" in caught.value.detail


def test_a_layout_the_top_cannot_take_is_refused_for_every_candidate() -> None:
    with pytest.raises(samples.SiteRefused) as caught:
        composed(on_top(TILT, cut_fill_mm=100))
    assert all(
        "its land cannot take this layout" in refused["refusal"]
        for refused in caught.value.refusals
    )


@pytest.mark.parametrize(
    "at_mm",
    [(-20000, -9999), (-8500, -10000), (-19000, -21000), (20000, -10000)],
)
def test_a_site_off_the_square_or_its_lattice_is_refused_by_name(level_world, at_mm) -> None:
    with pytest.raises(LandformRefused) as caught:
        site_top(on_top(LEVEL, at_mm=at_mm), level_world.records, STATION_MM)
    assert caught.value.code == "landscape_site_outside_top"


def test_a_top_with_a_shore_is_refused_and_its_lake_is_moved_into_the_sites_frame(
    level_world,
) -> None:
    shore = {**land({"id": "sea", "kind": "shore", "side": "south"}), "ground_mm": 3000}
    with pytest.raises(LandformRefused) as caught:
        site_top(on_top(shore), level_world.records, STATION_MM)
    assert caught.value.code == "landscape_site_top_has_sea"
    lake = {"id": "mere", "kind": "basin", "side": "north_east", "distance_mm": 6000,
            "radius_mm": 4000, "depth_mm": 1500, "water": "fill"}  # fmt: skip
    on = on_top(land(lake), at_mm=(-8000, -18000))
    graded = site_top(on, level_world.records, STATION_MM)
    (own,) = water_bodies(on.top.land, top_land_frame(on.top, on.volume_id))
    (moved,) = [body for body in graded.water if body.kind == "lake"]
    half = SIDE_MM // 2
    assert moved.centre_mm == (
        own.centre_mm[0] - half - on.at_mm[0],
        own.centre_mm[1] - half - on.at_mm[1],
    )
    assert moved.level_mm == own.level_mm


def test_the_graded_top_document_is_pinned(top_world) -> None:
    on, _, graded = top_world
    document = graded.document()
    near = graded.graded.near
    assert document["profile"] == SITE_TOP_PROFILE
    assert (document["origin_mm"], document["columns"], document["rows"]) == (
        [near.x0, near.y0],
        SIDE_MM // 1000 + 1,
        SIDE_MM // 1000 + 1,
    )
    assert len(document["height_mm"]) == document["columns"] * document["rows"]
    name = "swell" if on.top.land.features[0].kind == "undulation" else "tilt"
    assert graded.sha256 == GOLDEN[TOP_RULES][name], (name, graded.sha256)


@pytest.mark.parametrize("name", ["swell", "tilt"])
def test_a_top_graded_by_land_rules_3_is_the_same_top(name: str) -> None:
    """A world made under volume rules 3 keeps the top land rules 3 graded for it."""
    on = dataclasses.replace(on_top({"swell": SWELL, "tilt": TILT}[name]), rules_version=3)
    world = composed(on)
    assert site_top(on, world.records, STATION_MM).sha256 == GOLDEN[3][name]


#: Each graded top's document digest under the land rules a volume rules version names for a top,
#: for the cafe's first preset on WORLD.
GOLDEN = {
    3: {
        "swell": "035d388b804e111166d525072620ff19c6f6dcd6f3522d7d913120d992f5ebe3",
        "tilt": "385bbdda0fb917c6bdd98707227431ba335e633601dc1edc9b38a9c421ddbce1",
    },
    7: {
        "swell": "3f23aa49892261752a61cf36949c873dd1f0a0b0ccf83f70539b76236e1b6d00",
        "tilt": "15a504f2ded689fe890ccde5e38f0cef5c4fb4acee5fc62271712f6bd7fb5e32",
    },
}
