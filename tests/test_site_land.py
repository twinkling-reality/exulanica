"""A site world laid out on land: terraces at their gates, paths within a kerb step per station,
ponds in their basins, the drawing standing on the graded land, and every land-less world as it
was."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SitePathRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)
from exulanica.grammar.landform import (
    CHUNK_PROFILE,
    LAND_RULES_VERSION,
    SERVED_LAND_RULES,
    LandformRefused,
    land_rules,
    read_land_chunk,
)
from exulanica.world.composers import site_plan
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.kinds import samples
from exulanica.world.kinds.document import read_kind
from exulanica.world.site_drawing import LAND_DRAWING_PROFILE, site_drawing, site_drawing_sha256
from exulanica.world.site_land import path_grade_permille, site_grading, site_land_of
from exulanica.world.society_engines import CREATES
from exulanica.world.society_living import LivingPlace, initial_living_society
from exulanica.world.society_place import STEP_LIMIT_MM

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
TILT = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 8000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30},
        {"id": "swell", "kind": "undulation", "amplitude_mm": 700, "wavelength_mm": 40000},
        {"id": "hill", "kind": "rise", "side": "north", "distance_mm": 30000, "height_mm": 20000},
        {"id": "sea", "kind": "shore", "side": "south", "distance_mm": 60000},
        {"id": "skyline", "kind": "range", "side": "north", "distance_mm": 2000000,
         "band_mm": 800000, "height_mm": 300000},
    ],
}  # fmt: skip


def kind(name: str):  # type: ignore[no-untyped-def]
    return read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8")))


def made(name: str, land: dict | None = TILT, world_id: str = "world:generated:land", **more):  # type: ignore[no-untyped-def]
    found = kind(name)
    return site_plan.compose_kind(
        found, found.values(found.presets[0][0]), world_id, place_id="place:land", land=land, **more
    )


def drawn(world):  # type: ignore[no-untyped-def]
    return site_drawing(
        world_id=world.receipt["world_id"],
        receipt=world.receipt,
        receipt_sha256=world.receipt_sha256,
        records=world.records,
    )


@pytest.mark.parametrize("name", ["site", "farm", "cafe"])
def test_a_world_made_without_land_is_the_level_world_it_always_was(name: str) -> None:
    found = kind(name)
    values = found.values(found.presets[0][0])
    level = site_plan.compose_kind(found, values, "world:generated:level", place_id="place:land")
    asked = made(name, land=None, world_id="world:generated:level")
    assert asked.receipt == level.receipt and asked.receipt_sha256 == level.receipt_sha256
    assert level.receipt["composer"]["version"] == 1
    assert not {"land", "land_sha256", "land_rules"} & set(level.receipt)
    drawing = drawn(level)
    assert drawing["profile"] == "exulanica.site-drawing/v1" and "land" not in drawing
    assert not any("drape" in slot for slot in drawing["slots"])
    assert drawing["arrival"]["positionMm"][2] == 0
    assert {node["support_z_mm"] for node in level.place["nodes"]} == {0}
    assert level.place["frame"]["datum"] == "site_local z, the level ground every site stands on"
    assert asked.place == level.place


@pytest.mark.parametrize("name", ["site", "farm", "cafe"])
def test_a_site_on_land_is_composer_five_and_regenerates_from_its_receipt(name: str) -> None:
    world = made(name)
    receipt = world.receipt
    assert receipt["composer"] == {"key": "site-plan", "version": 5}
    assert receipt["land_sha256"] == site_land_of(receipt, world.records, 4000).land.sha256
    regenerated = site_plan.records(receipt)
    assert regenerated == world.records
    assert site_plan.society_place("place:land", receipt, regenerated) == world.place
    first, second = drawn(world), drawn(world)
    assert first["profile"] == LAND_DRAWING_PROFILE
    assert site_drawing_sha256(first) == site_drawing_sha256(second)
    level = made(name, land=None)
    assert level.receipt["output_digest"] == receipt["output_digest"], "same layout, other ground"


def test_a_world_on_land_names_the_land_rules_that_made_it_and_other_rules_are_refused() -> None:
    world = made("site")
    assert world.receipt["land_rules"] == land_rules()
    assert world.receipt["land_rules"]["version"] == LAND_RULES_VERSION
    named = world.receipt["land_rules"]
    changed = [
        {**named, "version": LAND_RULES_VERSION + 1},
        {**named, "catalogs": {**named["catalogs"], "landform-value.v1": "0" * 64}},
        None,
    ]
    for rules in changed:
        receipt = copy.deepcopy(world.receipt)
        if rules is None:
            del receipt["land_rules"]
        else:
            receipt["land_rules"] = rules
        with pytest.raises(InvalidStructuralData, match=r"^generated_world_land_rules_changed: "):
            site_plan.records(receipt)
        with pytest.raises(InvalidStructuralData, match=r"^generated_world_land_rules_changed: "):
            site_land_of(receipt, world.records, 4000)
    level = made("site", land=None)
    named_on_level = {**copy.deepcopy(level.receipt), "land_rules": land_rules()}
    with pytest.raises(InvalidStructuralData, match=r"^generated_world_land_rules_changed: "):
        site_plan.records(named_on_level)


def test_a_world_named_by_land_rules_version_1_regenerates_byte_for_byte() -> None:
    """Land made before the cascade (rules version 1) is still served: the same receipt naming
    version 1 regenerates the same records, the same drawing and the same land as version 6, the
    drawing listing no retaining walls where version 6 lists them (version 7 eases the banks)."""
    world = made("site")
    first = copy.deepcopy(world.receipt)
    first["land_rules"] = land_rules(1)
    sixth = copy.deepcopy(world.receipt)
    sixth["land_rules"] = land_rules(6)
    assert first["land_rules"]["catalogs"] != world.receipt["land_rules"]["catalogs"]
    records = site_plan.records(first)
    assert records == world.records == site_plan.records(sixth)
    before, after = site_land_of(sixth, records, 4000), site_land_of(first, records, 4000)
    now = before.drawing_section()
    assert now.pop("walls"), "the site's terraces meet at levels a bank cannot join"
    assert after.drawing_section() == now
    assert [c.sha256 for c in after.chunks()] == [c.sha256 for c in before.chunks()]
    drawing = site_drawing(
        world_id=first["world_id"], receipt=first, receipt_sha256="b" * 64, records=records
    )
    named_sixth = site_drawing(
        world_id=first["world_id"], receipt=sixth, receipt_sha256="b" * 64, records=records
    )
    del named_sixth["land"]["walls"]
    assert site_drawing_sha256(drawing) == site_drawing_sha256(named_sixth)


#: Two zones, each with one pond, the first water area of its zone.
TWO_PONDS = (
    SiteExtentRecord("site:extent", "ponds", 48000, 60000, 4000, "fence", "ground", "grass",
                     24000, 4000, 1200, 200),
    SitePathRecord("site:path:0", 0, "spine", 22000, 0, 26000, 44000, ("footway",), "ground",
                   "gravel"),
    SiteZoneRecord("site:zone:0", 0, "yard", 4000, 8000, 20000, 24000, "east", "open", "ground",
                   "grass", 20000, 16000),
    SiteZoneRecord("site:zone:1", 1, "garden", 28000, 28000, 44000, 44000, "west", "open",
                   "ground", "grass", 28000, 36000),
    SiteAreaRecord("site:area:0", "site:zone:1", 0, "pond", 32000, 32000, 40000, 40000,
                   ("water",), "water", "pond", 32000, 36000),
    SiteAreaRecord("site:area:1", "site:zone:0", 0, "pond", 8000, 12000, 14000, 20000,
                   ("water",), "water", "pond", 14000, 16000),
)  # fmt: skip


def test_two_zones_first_ponds_have_their_own_ids_from_land_rules_4() -> None:
    """From land rules 4 a pond's id names its zone, so each zone's first pond has its own; under
    rules 1 to 3 both are ``pond 0``, as their drawings state. The plan is otherwise the same, its
    ponds carved in the same order."""
    plans = {
        version: site_grading(TWO_PONDS, 4000, rules_version=version)
        for version in SERVED_LAND_RULES
    }
    assert [basin.id for basin in plans[4].basins] == ["zone 1 pond 0", "zone 0 pond 0"]
    for version in (1, 2, 3):
        assert [basin.id for basin in plans[version].basins] == ["pond 0", "pond 0"]
        unnamed = tuple(replace(basin, id="") for basin in plans[version].basins)
        assert replace(plans[4], basins=unnamed) == replace(plans[version], basins=unnamed)
        assert tuple(replace(basin, id="") for basin in plans[4].basins) == unnamed
    stray = (*TWO_PONDS[:-1], replace(TWO_PONDS[-1], zone_identity="site:zone:9"))
    with pytest.raises(LandformRefused, match=r"site:area:1 lies in zone site:zone:9, which is"):
        site_grading(stray, 4000, rules_version=4)
    assert [b.id for b in site_grading(stray, 4000, rules_version=3).basins] == ["pond 0", "pond 0"]


def test_a_world_named_by_land_rules_3_keeps_its_pond_ids_and_rules_4_moves_no_height() -> None:
    """A world named by rules 3 regenerates byte for byte, its pond named by its area's number in
    its zone; the same receipt naming rules 4 names the pond by its zone too, on the same land."""
    world = made("farm")  # the farm's pond corner holds a pond
    third, fourth = copy.deepcopy(world.receipt), copy.deepcopy(world.receipt)
    third["land_rules"], fourth["land_rules"] = land_rules(3), land_rules(4)
    records = site_plan.records(third)
    assert records == site_plan.records(fourth) == world.records
    zones = {r.identity: r.ordinal for r in records if isinstance(r, SiteZoneRecord)}
    ponds = sorted(
        (r for r in records if isinstance(r, SiteAreaRecord) and "water" in r.roles),
        key=lambda area: area.ordinal,
    )
    assert ponds
    now, before = site_land_of(fourth, records, 4000), site_land_of(third, records, 4000)

    def named(graded) -> list[str]:  # type: ignore[no-untyped-def]
        return [body.id for body in graded.water if body.kind == "pond"]

    def unnamed(graded) -> dict:  # type: ignore[no-untyped-def,type-arg]
        section = graded.drawing_section()
        section["water"] = [
            {**body, "id": ""} if body["kind"] == "pond" else body for body in section["water"]
        ]
        return section

    assert named(before) == [f"pond {area.ordinal}" for area in ponds]
    assert named(now) == [f"zone {zones[a.zone_identity]} pond {a.ordinal}" for a in ponds]
    assert now.graded.near.heights == before.graded.near.heights
    assert unnamed(now) == unnamed(before), "the same land, chunks, backdrop and water levels"


def test_a_world_named_by_land_rules_5_regenerates_and_rules_6_grades_the_same_land() -> None:
    """A world named by rules 5 regenerates byte for byte, and the same receipt naming rules 6
    grades the very same land, walls and water: rules 6 holds a terrace in a wall only where its
    bank would cut or fill past the bound, which this world's never does."""
    world = made("site")
    fifth, sixth = copy.deepcopy(world.receipt), copy.deepcopy(world.receipt)
    fifth["land_rules"], sixth["land_rules"] = land_rules(5), land_rules(6)
    records = site_plan.records(fifth)
    assert records == site_plan.records(sixth) == world.records
    before, now = site_land_of(fifth, records, 4000), site_land_of(sixth, records, 4000)
    assert now.graded == before.graded
    assert now.drawing_section() == before.drawing_section()
    assert site_grading(records, 4000, rules_version=5).held_most_mm == 0
    assert site_grading(records, 4000, rules_version=6).held_most_mm == 3000


def test_a_site_stands_beside_a_cascade_and_its_drawing_lists_the_pools_and_falls() -> None:
    falls = {"id": "falls", "kind": "cascade", "side": "south", "offset_mm": -70_000,
             "from_mm": -140_000, "to_mm": 90_000}  # fmt: skip
    land = {**TILT, "features": [*TILT["features"], falls]}
    world = made("farm", land=land)
    assert world.receipt["land_rules"] == land_rules()
    assert site_plan.records(world.receipt) == world.records
    water = drawn(world)["land"]["water"]
    kinds = [body["kind"] for body in water if body["id"].startswith("falls")]
    assert kinds and kinds[0] == "pool" and "fall" in kinds
    assert all(body["level_mm"] > body["bottom_mm"] for body in water if body["kind"] == "fall")


def test_every_zone_is_a_level_terrace_and_every_walking_edge_stays_within_a_step() -> None:
    world = made("farm")
    graded = site_land_of(world.receipt, world.records, 4000)
    near = graded.graded.near
    # A zone's cells under a pond, or shared with its path (the path keeps its grade), excepted.
    kept = [body.rect_mm for body in graded.water if body.kind == "pond"] + [
        (p.min_x_mm, p.min_y_mm, p.max_x_mm, p.max_y_mm)
        for p in world.records
        if isinstance(p, SitePathRecord)
    ]
    zones = [r for r in world.records if isinstance(r, SiteZoneRecord)]
    for zone in zones:
        # A row two zones share belongs to the one graded first.
        others = [(z.min_x_mm, z.min_y_mm, z.max_x_mm, z.max_y_mm) for z in zones if z is not zone]
        heights = {
            near.at(x, y)
            for x in range(-(-zone.min_x_mm // 1000) * 1000, zone.max_x_mm + 1, 1000)
            for y in range(-(-zone.min_y_mm // 1000) * 1000, zone.max_y_mm + 1, 1000)
            if not any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in kept + others)
        }
        assert len(heights) == 1, (zone.zone_key, sorted(heights))
    levels = {graded.height_at(*n["position_mm"]) for n in world.place["nodes"]}
    assert max(levels) - min(levels) > 500, "the terraces stand at different heights"
    heights = {n["node_id"]: n["support_z_mm"] for n in world.place["nodes"]}
    for edge in world.place["edges"]:
        if edge["kind"] in ("crossing", "premises_access"):
            continue
        assert abs(heights[edge["from_node_id"]] - heights[edge["to_node_id"]]) <= STEP_LIMIT_MM
    assert world.place["frame"]["datum"] == "site_local z, above the land's datum, the sea's level"


def test_a_path_climbs_no_more_than_one_step_over_its_longest_station() -> None:
    world = made("site")
    graded = site_land_of(world.receipt, world.records, 4000)
    for path in (r for r in world.records if isinstance(r, SitePathRecord)):
        grade = path_grade_permille(path, 4000)
        assert grade * 4000 // 1000 <= STEP_LIMIT_MM
        along_y = (path.max_y_mm - path.min_y_mm) >= (path.max_x_mm - path.min_x_mm)
        middle = (
            (
                (path.min_x_mm + path.max_x_mm) // 2
                if along_y
                else (path.min_y_mm + path.max_y_mm) // 2
            )
            // 1000
            * 1000
        )
        stations = range(-(-(path.min_y_mm if along_y else path.min_x_mm) // 1000) * 1000,
                         (path.max_y_mm if along_y else path.max_x_mm) + 1, 1000)  # fmt: skip
        profile = [
            graded.graded.near.at(*((middle, s) if along_y else (s, middle))) for s in stations
        ]
        assert max(abs(b - a) for a, b in pairwise(profile)) <= grade


def test_the_drawing_stands_on_the_land_and_names_it_by_digest() -> None:
    world = made("farm")
    drawing = drawn(world)
    graded = site_land_of(world.receipt, world.records, 4000)
    land = drawing["land"]
    assert land["land_sha256"] == world.receipt["land_sha256"]
    assert [c["sha256"] for c in land["chunks"]] == [c.sha256 for c in graded.chunks()]
    assert land["backdrop_sha256"] == graded.backdrop.sha256
    documents = graded.documents()
    for chunk in land["chunks"]:
        key = f"{chunk['chunk'][0]},{chunk['chunk'][1]}"
        body = json.loads(documents["chunks"][key]["body"])
        assert body["profile"] == CHUNK_PROFILE
        assert read_land_chunk(body, chunk["sha256"]).chunk_x == chunk["chunk"][0]
    east, north, up = drawing["arrival"]["positionMm"]
    assert up == graded.height_at(east, north) > 0
    level = drawn(made("farm", land=None))
    for on_land, flat in zip(drawing["slots"], level["slots"], strict=True):
        assert on_land["identity"] == flat["identity"] and on_land["boxMm"] == flat["boxMm"]
        x, y, z = flat["positionMm"]
        if on_land["lookRole"].startswith("water."):
            continue
        assert on_land["positionMm"] == [x, y, graded.height_at(x, y) + z]
    draped = {s["identity"] for s in drawing["slots"] if s.get("drape")}
    assert draped == _ground_and_boundaries(world, drawing)


def _ground_and_boundaries(world, drawing) -> set[str]:  # type: ignore[no-untyped-def]
    """The slots a land drawing drapes: the site's ground, its zones, paths and dry areas, and every
    piece of a wall that belongs to no building."""
    covering = {
        r.identity
        for r in world.records
        if isinstance(r, SiteZoneRecord | SitePathRecord)
        or (isinstance(r, SiteAreaRecord) and "water" not in r.roles)
    }
    walls = {r.identity for r in world.records if isinstance(r, SiteWallRecord)}
    extent = next(r for r in world.records if isinstance(r, SiteExtentRecord))
    return {
        s["identity"]
        for s in drawing["slots"]
        if s["identity"] in covering | {f"{extent.identity}:ground"}
        or (s["identity"].partition(":")[0] in walls and "structure" not in s)
    }


def _leaves_level(graded, slot) -> int:  # type: ignore[no-untyped-def]
    """How far the land under a slot's footprint corners leaves the land under its base's centre."""
    x, y, _ = slot["positionMm"]
    width, depth, _ = slot["boxMm"]
    if slot["yawQuarterTurns"] % 2:
        width, depth = depth, width
    centre = graded.height_at(x, y)
    return max(
        abs(graded.height_at(x + dx * width // 2, y + dy * depth // 2) - centre)
        for dx in (-1, 1)
        for dy in (-1, 1)
    )


@pytest.mark.parametrize("name", ["site", "farm", "cafe"])
@pytest.mark.parametrize("grade", [30, 60])
def test_what_the_land_leaves_level_is_draped_and_the_rest_stands_level(
    name: str, grade: int
) -> None:
    """A terrace is level only inside its edges, where it meets sloping paths and terraces at other
    levels: a zone's corners, and a fence along its edge, leave its level, so they are drawn on the
    land. A building, its rooms and walls, and a fixture stand where the land is level."""
    land = copy.deepcopy(TILT)
    land["features"][0]["grade_permille"] = grade
    world = made(name, land=land)
    drawing = drawn(world)
    graded = site_land_of(world.receipt, world.records, 4000)
    draped = [s for s in drawing["slots"] if s.get("drape")]
    assert {s["identity"] for s in draped} == _ground_and_boundaries(world, drawing)
    assert max(_leaves_level(graded, s) for s in draped) > 300, "the land leaves a terrace's level"
    for slot in drawing["slots"]:
        if slot.get("drape") or slot["lookRole"].startswith("water."):
            continue
        assert _leaves_level(graded, slot) <= 50, (slot["identity"], slot["lookRole"])


def test_a_building_on_land_states_its_storey_height_as_on_level_ground() -> None:
    world = made("farm")
    storeys = {
        record.identity: record.storey_height_mm
        for record in world.records
        if isinstance(record, SiteStructureRecord)
    }
    drawing = drawn(world)
    assert drawing["profile"] == LAND_DRAWING_PROFILE
    stated = {s["identity"]: s["storeyHeightMm"] for s in drawing["slots"] if "storeyHeightMm" in s}
    assert storeys and stated == storeys


def test_a_pond_stands_in_its_basin_at_its_level() -> None:
    world = made("farm")  # the farm's pond corner holds a pond
    graded = site_land_of(world.receipt, world.records, 4000)
    ponds = [body for body in graded.water if body.kind == "pond"]
    assert ponds
    drawing = drawn(world)
    for pond in ponds:
        x0, y0, x1, y1 = pond.rect_mm
        floor = min(
            h for x, y, h in graded.graded.near.samples() if x0 <= x <= x1 and y0 <= y <= y1
        )
        assert floor < pond.level_mm - 1000
        water = [s for s in drawing["slots"] if s["lookRole"].startswith("water.")]
        assert any(s["positionMm"][2] == pond.level_mm for s in water)


def test_a_land_document_the_catalog_refuses_is_refused_before_any_layout() -> None:
    bad = copy.deepcopy(TILT)
    bad["features"][2]["height_mm"] = 700000
    with pytest.raises(LandformRefused) as caught:
        made("site", land=bad)
    assert caught.value.code == "landform_invalid" and caught.value.path == "features[2].height_mm"


def test_land_with_a_support_declaration_is_not_served() -> None:
    with pytest.raises(LandformRefused) as caught:
        made("farm", support={"profile": "anything"})
    assert caught.value.code == "landform_not_served"


def test_a_layout_the_land_cannot_take_is_refused_and_the_next_candidate_is_tried(
    monkeypatch,
) -> None:
    real = samples.site_land
    calls: list[int] = []

    def first_refused(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise LandformRefused(
                "the path to zone 1 would cut 9000 mm", code="landform_cut_too_deep"
            )
        return real(*args, **kwargs)

    monkeypatch.setattr(samples, "site_land", first_refused)
    world = made("site")
    assert world.receipt["candidate"] == 1
    [refused] = world.receipt["refused_candidates"]
    assert refused["candidate"] == 0 and refused["code"] == "kind_generation_refused"
    assert "its land cannot take this layout" in refused["refusal"] and "9000" in refused["refusal"]


def test_people_live_on_terraces_and_every_one_walks_to_work() -> None:
    """DAY's rule: homes and workplaces on different terraces, joined by a graded path, and the
    living society is made (no inhabitant cut off from its workplace)."""
    steep = copy.deepcopy(TILT)
    steep["features"][0]["grade_permille"] = 60  # steeper than a path: the track cuts and fills
    world = made("farm", land=steep)
    routine = site_plan.receipt_routine(world.receipt)
    place = LivingPlace(world.place, routine)
    heights = {n["node_id"]: n["support_z_mm"] for n in world.place["nodes"]}
    destinations = world.place["destinations"]
    homes = {d["node_id"] for d in destinations if d["resident_capacity"]}
    work = {d["node_id"] for d in destinations if d["staff_capacity"]}
    assert homes and work
    levels = {heights[n] for n in homes | work}
    assert max(levels) - min(levels) > 500, "homes and work stand on different terraces"
    state = initial_living_society(
        uuid.UUID("00000000-0000-4000-8000-00000000a001"),
        "c" * 64,
        place,
        routine,
        branch_id="branch",
        profile=CREATES["town"],
    )
    workers = [p for p in state["inhabitants"] if p.get("work")]
    assert workers, "someone on the farm works"
