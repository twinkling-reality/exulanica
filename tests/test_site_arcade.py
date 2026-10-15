"""A building whose ground storey people walk through: an arcade along its front, the covered walk
behind it and the door at the walk's back, made, walked, drawn, regenerated and moved.

The world is the hand-written farm fixture (``tests/fixtures/world-kinds``) with an arcade stated on
its farmhouse and its barn. Positions are read from the records it makes, never retyped. A world
without an arcade is held to its old digests by ``tests/test_site_pinned.py``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.grammars.site import check_site_records
from exulanica.grammar.grammars.site.records import (
    SiteLoggiaRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
)
from exulanica.world.composers.site_plan import (
    ComposedWorld,
    compose_kind,
    records,
    society_place,
)
from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY, load_arcade_catalog
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.samples import SiteRefused, first_unreached
from exulanica.world.site_drawing import site_drawing
from exulanica.world.site_parts import PartChange, apply_changes

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
#: The arcades stated on the farm fixture's two buildings. The farmhouse is made deeper than the
#: fixture's, so its rooms and their beds fit behind its covered walk.
ARCADES = {"farmhouse": {"bays": 3, "depth_mm": 2000}, "barn": {"bays": 4, "depth_mm": 3000}}


def _farm(**changes: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    document = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    for part in document["parts"]:
        if part["key"] in ARCADES:
            part["arcade"] = dict(ARCADES[part["key"]])
        if part["key"] == "farmhouse":
            part["depth_mm"] = {"from": 10000, "to": 12000}
        if part["key"] in changes:
            changes[part["key"]](part)
    return document


def _compose(document: dict[str, Any], world_id: str) -> ComposedWorld:
    kind = read_kind(document)
    return compose_kind(kind, kind.values(kind.presets[0][0]), world_id, place_id="place:test")


@pytest.fixture(scope="module", name="farm")
def _arcaded_farm() -> ComposedWorld:
    return _compose(_farm(), "world:generated:arcade-test")


def _structures(world: ComposedWorld) -> list[SiteStructureRecord]:
    return [r for r in world.records if isinstance(r, SiteStructureRecord)]


def _front(world: ComposedWorld, structure: SiteStructureRecord) -> SiteWallRecord:
    return next(
        r
        for r in world.records
        if isinstance(r, SiteWallRecord)
        and r.owner_identity == structure.identity
        and any(opening.kind == "arch" for opening in r.openings)
    )


def _walk(records: Any, structure: str) -> SiteLoggiaRecord:
    return next(
        r for r in records if isinstance(r, SiteLoggiaRecord) and r.structure_identity == structure
    )


def _arches(wall: SiteWallRecord) -> list[tuple[int, int]]:
    """Each arch of a wall as the stretch of the site's axis along the wall it spans."""
    along_x = wall.start_y_mm == wall.end_y_mm
    start = wall.start_x_mm if along_x else wall.start_y_mm
    return [
        (start + o.offset_mm, start + o.offset_mm + o.width_mm)
        for o in wall.openings
        if o.kind == "arch"
    ]


def _inside(rect: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= rect[0] and outer[1] <= rect[1] and rect[2] <= outer[2] and rect[3] <= outer[3]
    )


def _rect(record: Any) -> tuple[int, int, int, int]:
    return (record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm)


def test_an_arcade_opens_the_front_in_equal_arches_onto_a_covered_walk_with_the_door_behind(
    farm: ComposedWorld,
) -> None:
    catalog = load_arcade_catalog()
    for structure in _structures(farm):
        arcade = ARCADES[structure.part_key]
        front = _front(farm, structure)
        arches = _arches(front)
        assert [o.kind for o in front.openings] == ["arch"] * arcade["bays"]
        assert len({end - start for start, end in arches}) == 1
        assert arches[0][1] - arches[0][0] >= catalog.bound("least_opening_mm")[0]
        assert all(b[0] - a[1] >= catalog.bound("pier_mm")[0] for a, b in pairwise(arches))
        walk = _walk(farm.records, structure.identity)
        assert walk.bays == arcade["bays"]
        assert _inside(_rect(walk), _rect(structure))
        depth = (
            walk.max_y_mm - walk.min_y_mm
            if structure.door_facing in ("north", "south")
            else walk.max_x_mm - walk.min_x_mm
        )
        assert depth == arcade["depth_mm"]
        # The door is on the walk's back edge, in a wall of the structure's own.
        back = {
            "south": walk.max_y_mm,
            "north": walk.min_y_mm,
            "west": walk.max_x_mm,
            "east": walk.min_x_mm,
        }[structure.door_facing]
        door_across = (
            structure.door_y_mm
            if structure.door_facing in ("north", "south")
            else structure.door_x_mm
        )
        assert door_across == back
        along_x = front.start_y_mm == front.end_y_mm
        entrances = [
            r
            for r in farm.records
            if isinstance(r, SiteWallRecord)
            and r.owner_identity == structure.identity
            and (r.start_y_mm == r.end_y_mm) == along_x
            and any(o.kind == "door" for o in r.openings)
        ]
        assert len(entrances) == 1
        line = entrances[0].start_y_mm if along_x else entrances[0].start_x_mm
        assert abs(line - back) == entrances[0].thickness_mm // 2
        # Its rooms stand behind the walk, none under it.
        for room in farm.records:
            if isinstance(room, SiteRoomRecord) and room.structure_identity == structure.identity:
                assert not (
                    room.min_x_mm < walk.max_x_mm
                    and walk.min_x_mm < room.max_x_mm
                    and room.min_y_mm < walk.max_y_mm
                    and walk.min_y_mm < room.max_y_mm
                )


def _crossings(place: Any, wall: SiteWallRecord) -> list[int]:
    """Where each walking edge crosses a wall's line, along the wall."""
    along_x = wall.start_y_mm == wall.end_y_mm
    line = wall.start_y_mm if along_x else wall.start_x_mm
    low, high = (wall.start_x_mm, wall.end_x_mm) if along_x else (wall.start_y_mm, wall.end_y_mm)
    at = {node["node_id"]: node["position_mm"] for node in place["nodes"]}
    found = []
    for edge in place["edges"]:
        a, b = at[edge["from_node_id"]], at[edge["to_node_id"]]
        a_across, b_across = (a[1], b[1]) if along_x else (a[0], b[0])
        if (a_across - line) * (b_across - line) >= 0:
            continue
        a_along, b_along = (a[0], b[0]) if along_x else (a[1], b[1])
        crossing = a_along + (b_along - a_along) * (line - a_across) / (b_across - a_across)
        if low <= crossing <= high:
            found.append(round(crossing))
    return found


def test_people_walk_through_every_arch_to_the_door_and_through_no_pier(
    farm: ComposedWorld,
) -> None:
    place = farm.place
    assert place is not None
    assert first_unreached(place) is None
    at = {node["node_id"]: node["position_mm"] for node in place["nodes"]}
    for structure in _structures(farm):
        arches = _arches(_front(farm, structure))
        crossings = _crossings(place, _front(farm, structure))
        assert crossings
        assert all(any(a <= c <= b for a, b in arches) for c in crossings)
        assert all(any(a <= c <= b for c in crossings) for a, b in arches)
        # The way in is from the covered walk.
        door = next(
            d for d in place["destinations"] if d["subject_id"].endswith(structure.identity)
        )
        x, y = at[door["node_id"]]
        walk = _walk(farm.records, structure.identity)
        assert walk.min_x_mm < x < walk.max_x_mm and walk.min_y_mm < y < walk.max_y_mm


def test_the_drawing_states_each_arcade_and_the_visitor_walks_through_its_arches(
    farm: ComposedWorld,
) -> None:
    drawing = site_drawing(
        world_id="world:generated:arcade-test",
        receipt=farm.receipt,
        receipt_sha256=farm.receipt_sha256,
        records=farm.records,
    )
    slots = {slot["identity"]: slot for slot in drawing["slots"]}
    for structure in _structures(farm):
        arcade = ARCADES[structure.part_key]
        own = slots[structure.identity]
        assert (own["arcadeBays"], own["loggiaDepthMm"]) == (arcade["bays"], arcade["depth_mm"])
        front = _front(farm, structure)
        assert not any(i.startswith(f"{front.identity}:door") for i in slots)
        along_x = front.start_y_mm == front.end_y_mm
        line = front.start_y_mm if along_x else front.start_x_mm
        for a, b in _arches(front):
            for x0, y0, x1, y1 in drawing["walk"]["blockersMm"]:
                low, high, near, far = (x0, x1, y0, y1) if along_x else (y0, y1, x0, x1)
                assert not (near <= line <= far and low < b and a < high)
    others = [
        s for s in drawing["slots"] if s["identity"] not in {r.identity for r in _structures(farm)}
    ]
    assert not any("arcadeBays" in s or "loggiaDepthMm" in s for s in others)


def test_an_arcaded_world_regenerates_from_its_receipt_which_names_the_arcade_catalog(
    farm: ComposedWorld,
) -> None:
    assert records(farm.receipt) == farm.records
    stated = (CATALOG_DIRECTORY / "structure-arcade.v1.json").read_bytes()
    assert farm.receipt["catalogs"]["structure-arcade"] == hashlib.sha256(stated).hexdigest()
    plain = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    assert "structure-arcade" not in _compose(plain, "world:generated:plain").receipt["catalogs"]


def test_a_moved_or_removed_arcaded_building_takes_its_covered_walk_with_it(
    farm: ComposedWorld,
) -> None:
    barn = next(s for s in _structures(farm) if s.part_key == "barn")
    centre = ((barn.min_x_mm + barn.max_x_mm) // 2, (barn.min_y_mm + barn.max_y_mm) // 2)
    turned = apply_changes(farm.records, [PartChange(barn.identity, False, centre, 2)])
    check_site_records(turned, root_identity=farm.receipt["subject_identity"])
    moved = next(r for r in turned if getattr(r, "identity", None) == barn.identity)
    assert _inside(_rect(_walk(turned, barn.identity)), _rect(moved))
    removed = apply_changes(farm.records, [PartChange(barn.identity, True)])
    check_site_records(removed, root_identity=farm.receipt["subject_identity"])
    assert not any(
        isinstance(r, SiteLoggiaRecord) and r.structure_identity == barn.identity for r in removed
    )
    assert first_unreached(society_place("place:test", farm.receipt, removed)) is None


def _set(**figures: Any) -> Callable[[dict[str, Any]], None]:
    def change(part: dict[str, Any]) -> None:
        for key, value in figures.items():
            if value is None:
                part.pop(key, None)
            else:
                part[key] = value

    return change


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (_set(roles=[], rooms=[]), "kind_role_unmet"),
        (_set(storey_height_mm=2600), "kind_out_of_bounds"),
        (_set(arcade={"bays": 3, "depth_mm": 2250}), "kind_out_of_bounds"),
        (_set(arcade={"bays": 25, "depth_mm": 2000}), "kind_out_of_bounds"),
        (_set(arcade={"bays": 3, "depth_mm": 2000, "height_mm": 3000}), "kind_document_invalid"),
    ],
    ids=[
        "no door to lead to",
        "storey under an arch",
        "depth off the module",
        "too many bays",
        "an unknown key",
    ],
)
def test_the_kind_refuses_an_arcade_it_cannot_lay_out_by_name(
    change: Callable[[dict[str, Any]], None], code: str
) -> None:
    with pytest.raises(KindRefused) as refused:
        read_kind(_farm(farmhouse=change))
    assert refused.value.code == code


def test_a_front_too_short_for_its_bays_is_refused_with_its_figures() -> None:
    with pytest.raises(SiteRefused) as refused:
        _compose(_farm(farmhouse=_set(arcade={"bays": 8, "depth_mm": 2000})), "world:generated:x")
    least = load_arcade_catalog().bound("least_opening_mm")[0]
    assert "8 arches would each be" in str(refused.value)
    assert f"under {least} mm" in str(refused.value)
