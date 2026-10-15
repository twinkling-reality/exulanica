"""Where a moved thing may stand: the world's edge, its ground and what blocks, read as its people
read them.

The rule (:mod:`exulanica.world.thing_landing`) is held here on small synthetic grounds, and its
named parts are held to the figures a site's and a town's society already walk round, so the
two cannot disagree.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.composers import site_plan
from exulanica.world.errors import ThingLandingRefused
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.kinds.document import read_kind
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind
from exulanica.world.society_authored_ground import WalkableArea, _height_above_plane
from exulanica.world.society_city_place import city_blocked_parts, city_obstructions
from exulanica.world.society_site_place import SiteSociety, site_blocked_boxes, site_blocked_parts
from exulanica.world.thing_landing import (
    LANDING_CODES,
    BlockedPart,
    LandingGround,
    blocking_things,
    footprint_half_extents,
    landing_refusal,
    rests_on_plane,
)
from exulanica.world.world_recipes import town_recipe

from kind_briefs import fixture_kind

QUARTER = 1_570_796
WELL = named_kind("well", 2)
#: A shipped being: held by its centre.
KNIGHT = named_kind("knight", 2)
AREA = WalkableArea("ground", 0, 0, 20_000, 20_000)
POND = BlockedPart("water", "duck pond", ((4_000, -4_000), (8_000, -4_000), (8_000, 0), (4_000, 0)))
BARN = BlockedPart(
    "structure", "barn", ((-8_000, 2_000), (-2_000, 2_000), (-2_000, 8_000), (-8_000, 8_000))
)


def _ground(*parts: BlockedPart, area: WalkableArea | None = AREA) -> LandingGround:
    return LandingGround("region:generated", area, rests_on_plane(0), parts)


def _thing(x: int, z: int, *, y: int = 0, yaw: int = 0, kind=WELL, thing_id="well") -> PlacedThing:
    return PlacedThing(
        thing_id,
        kind,
        "region:generated",
        Transform(x, y, z, yaw, 1000),
        ObjectOrigin("authored", "fictional"),
    )


def _refusal(ground: LandingGround, thing: PlacedThing, others=()) -> ThingLandingRefused | None:
    return landing_refusal(ground, thing, footprint_half_extents(thing), others)


def test_a_well_on_open_ground_lands():
    assert _refusal(_ground(POND, BARN), _thing(0, -10_000)) is None


def test_past_the_edge_is_refused_before_the_ground_is_asked():
    refused = _refusal(_ground(), _thing(19_500, 0, y=3_000))
    assert refused is not None
    assert (refused.code, str(refused)) == (
        "thing_landing_outside",
        "That spot is past the edge of this world.",
    )


@pytest.mark.parametrize(
    ("y", "words"),
    [
        # Standing above the ground: the ground there is lower.
        (1_500, "The ground there is 1.5 m lower. Choose a spot on the same level."),
        # Standing below it: the ground there is higher.
        (-400, "The ground there is 0.4 m higher. Choose a spot on the same level."),
    ],
)
def test_off_the_ground_says_how_far_the_ground_steps(y, words):
    refused = _refusal(_ground(), _thing(0, 0, y=y))
    assert refused is not None
    assert refused.code == "thing_landing_off_ground"
    assert refused.where == {"height_above_mm": y}
    assert str(refused) == words


def test_a_well_in_the_pond_is_refused_by_the_pond_s_own_name():
    refused = _refusal(_ground(POND), _thing(6_000, -2_000))
    assert refused is not None
    assert refused.code == "thing_landing_blocked"
    assert refused.where == {"part": "water", "label": "duck pond"}
    assert str(refused) == "That spot is in the duck pond."


def test_a_well_whose_edge_only_touches_the_pond_is_not_in_it():
    # The well is 1.6 m square: centred 800 mm west of the pond's west face, it touches it.
    assert _refusal(_ground(POND), _thing(3_200, -2_000)) is None
    assert _refusal(_ground(POND), _thing(3_201, -2_000)) is not None


def test_a_turn_can_carry_a_corner_into_a_building():
    # Unturned, the well's east face is 50 mm short of the barn's west face; a quarter of a
    # quarter turn swings a corner 330 mm further out, into the barn.
    beside = _thing(-8_850, 5_000)
    assert _refusal(_ground(BARN), beside) is None
    turned = _thing(-8_850, 5_000, yaw=QUARTER // 2)
    refused = _refusal(_ground(BARN), turned)
    assert refused is not None
    assert (refused.where, str(refused)) == (
        {"part": "structure", "label": "barn"},
        "That spot is inside the barn.",
    )


def test_a_being_is_held_by_its_centre():
    assert footprint_half_extents(_thing(0, 0, kind=KNIGHT)) is None
    inside = _refusal(_ground(BARN), _thing(-5_000, 5_000, kind=KNIGHT, thing_id="knight"))
    assert inside is not None and inside.where["part"] == "structure"
    on_the_wall_face = _thing(-2_000, 5_000, kind=KNIGHT, thing_id="knight")
    assert _refusal(_ground(BARN), on_the_wall_face) is None


def test_an_endless_ground_has_no_edge():
    assert _refusal(_ground(area=None), _thing(5_000_000, -9_000_000)) is None


def test_water_is_named_before_a_bench_it_also_meets():
    bench = BlockedPart(
        "thing", "bench", ((5_000, -1_000), (7_000, -1_000), (7_000, 1_000), (5_000, 1_000))
    )
    refused = _refusal(_ground(POND), _thing(6_000, -500), (bench,))
    assert refused is not None
    assert refused.where == {"part": "water", "label": "duck pond"}


def test_another_placed_object_blocks_and_a_being_or_the_moving_thing_does_not():
    bench = _thing(0, 0, kind=named_kind("bench", 2), thing_id="bench")
    knight = _thing(5_000, 0, kind=KNIGHT, thing_id="knight")
    removed = PlacedThing(
        "old-well",
        WELL,
        "region:generated",
        Transform(10_000, 0, 0, 0, 1000),
        ObjectOrigin("authored", "fictional"),
        removed=True,
    )
    well = _thing(0, 0)
    others = blocking_things((bench, knight, removed, well), "well")
    assert [(part.kind, part.label) for part in others] == [("thing", "bench")]
    refused = _refusal(_ground(), _thing(500, 0), others)
    assert refused is not None
    assert str(refused) == "It would stand on the bench."
    assert _refusal(_ground(), _thing(5_000, 3_000), others) is None
    assert _refusal(_ground(), _thing(10_000, 0), others) is None


def test_the_plane_rule_is_the_one_a_society_of_things_reads():
    ground = type("G", (), {"elevation_mm": 250})()
    society = _height_above_plane(ground)  # type: ignore[arg-type]
    mine = rests_on_plane(250)
    for y in (-1_000, 0, 249, 250, 251, 2_200):
        assert mine(_thing(0, 0, y=y)) == society(_thing(0, 0, y=y))


def test_every_refusal_code_is_a_stated_one():
    refusals = [
        _refusal(_ground(), _thing(30_000, 0)),
        _refusal(_ground(), _thing(0, 0, y=10)),
        _refusal(_ground(POND), _thing(6_000, -2_000)),
    ]
    assert {refusal.code for refusal in refusals if refusal is not None} == LANDING_CODES


def test_a_site_s_named_parts_are_the_boxes_its_people_walk_round():
    kind = read_kind(fixture_kind("farm"))
    world = site_plan.compose_kind(kind, kind.values(kind.presets[0][0]), "world:generated:landing")
    uses = SiteSociety.read(world.receipt["society"]).uses
    parts = site_blocked_parts(world.records, uses)
    assert [part["box"] for part in parts] == site_blocked_boxes(world.records)
    kinds = {part["part"] for part in parts}
    assert {"structure", "water"} <= kinds
    assert {"label": "duck pond", "part": "water"} in [
        {"label": part["label"], "part": part["part"]} for part in parts
    ]
    # Unnamed by its kind, a part is named by its key.
    unnamed = site_blocked_parts(world.records)
    assert [part["box"] for part in unnamed] == [part["box"] for part in parts]
    assert all(part["label"] for part in unnamed)


def test_a_town_s_named_parts_are_what_its_people_walk_round():
    composed = compose_generated_world(town_recipe("small_town"), "world:generated:landing-town")
    parts = city_blocked_parts(composed.records)
    obstructions = city_obstructions(composed.records)
    buildings = [part for part in parts if part[0] == "building"]
    low = [part for part in parts if part[0] in ("furniture", "tree")]
    assert buildings and low
    for _kind, _label, ring in buildings[:5] + low[:20]:
        xs = [corner[0] for corner in ring]
        ys = [corner[1] for corner in ring]
        centre = (int(sum(xs) / len(xs)), int(sum(ys) / len(ys)))
        assert not obstructions.stands(centre), (_kind, _label, centre)
    # Turned into the region's frame, a building's middle refuses a well by the building's kind.
    _kind, _label, ring = buildings[0]
    region_ring = tuple((x, -y) for x, y in ring)
    xs = [x for x, _ in region_ring]
    zs = [z for _, z in region_ring]
    ground = LandingGround(
        "region:generated",
        None,
        rests_on_plane(0),
        (BlockedPart("building", "building", region_ring),),
    )
    middle = _thing(
        int(sum(xs) / len(xs)), int(sum(zs) / len(zs)), thing_id=str(uuid.uuid4().hex[:8])
    )
    refused = landing_refusal(ground, middle, footprint_half_extents(middle))
    assert refused is not None and refused.where == {"part": "building", "label": "building"}
