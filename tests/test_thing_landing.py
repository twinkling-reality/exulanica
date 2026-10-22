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
from exulanica.world.society_walking_surfaces import surface_height_above, surface_height_at
from exulanica.world.thing_landing import (
    LANDING_CODES,
    BlockedPart,
    LandingGround,
    blocking_things,
    footprint_half_extents,
    footprint_points,
    landing_refusal,
    plane_height,
    resting_height,
    rests_on_footprint,
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
        (-400, "The ground there is 40 cm higher. Choose a spot on the same level."),
        # Under a metre in whole centimetres rounded up, so a refused step never reads as one that
        # rests (200 mm and less), and from a metre in metres to one place rounded up.
        (-250, "The ground there is 25 cm higher. Choose a spot on the same level."),
        (201, "The ground there is 21 cm lower. Choose a spot on the same level."),
        (-999, "The ground there is 1.0 m higher. Choose a spot on the same level."),
        (1_201, "The ground there is 1.3 m lower. Choose a spot on the same level."),
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


class _Ground:
    """The one figure the walking surfaces' height rule reads of a society's ground: its plane."""

    elevation_mm = 0


# A footway 2 m wide whose kerb line rises from the road's 0 to the paving's 150 mm: a walking
# line from (0, 0) to (0, 2000) in the place's plan (east, north), and a second line on the paving.
_KERB = {
    "nodes": [
        {"node_id": "road", "support_z_mm": 0, "position_mm": [0, 0]},
        {"node_id": "kerb", "support_z_mm": 150, "position_mm": [0, 2_000]},
        {"node_id": "shop", "support_z_mm": 150, "position_mm": [6_000, 2_000]},
    ],
    "edges": [
        {"edge_id": "a", "from_node_id": "road", "to_node_id": "kerb"},
        {"edge_id": "b", "from_node_id": "kerb", "to_node_id": "shop"},
    ],
}


def test_a_thing_rests_at_the_walking_surface_s_own_height_where_it_stands():
    rest = surface_height_at(_KERB, _Ground())
    # On the paving's line, on the kerb's rise half way up, and at the road's end (south is -north).
    assert (rest((3_000, -2_000)), rest((0, -1_000)), rest((0, 0))) == (150, 75, 0)
    above = surface_height_above(_KERB, _Ground())
    # Posed at that height it rests; 300 mm over it, it stands 150 mm above the paving's.
    assert above(_thing(3_000, -2_000, y=150)) is None
    assert above(_thing(3_000, -2_000, y=450)) == 300


def test_a_plane_ground_rests_a_thing_at_its_elevation_everywhere():
    assert [plane_height(250)(point) for point in ((0, 0), (40_000, -9_000))] == [250, 250]
    assert rests_on_plane(250)(_thing(40_000, -9_000, y=250)) is None


def _step(point: tuple[int, int]) -> int:
    """A kerb along east-west at 1 m south: the road at 0 to its north, the paving 150 mm up to its
    south (south is the region's z)."""
    return 150 if point[1] > 1_000 else 0


def test_a_well_across_a_kerb_rests_on_the_paving_under_it_not_on_the_road():
    half = footprint_half_extents(_thing(0, 1_000))
    assert half is not None
    # Its centre on the kerb line: one side of its footprint is over the paving, so it rests there.
    across = _thing(0, 1_000)
    assert resting_height(_step, across) == 150
    assert _step((0, 1_000)) == 0
    # Wholly over the road it rests on the road, and the centre is one of its points.
    road = _thing(0, -2_000)
    assert resting_height(_step, road) == 0
    assert (0, -2_000) in footprint_points(road)
    # Turned a quarter, its corners turn with it.
    assert len(footprint_points(_thing(0, 0, yaw=1_570_796))) == 5
    # Posed at that height it rests; at the road's, it stands under the paving's edge.
    above = rests_on_footprint(_step, 0)
    assert above(_thing(0, 1_000, y=150)) is None
    assert above(_thing(0, 1_000, y=0)) == -150
    ground = LandingGround("region:generated", None, above, (), _step, rests_on_footprint=True)
    assert ground.resting_y(across) == 150
    centred = LandingGround("region:generated", None, above, (), _step)
    assert centred.resting_y(across) == 0
