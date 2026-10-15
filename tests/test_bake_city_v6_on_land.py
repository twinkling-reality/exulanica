"""A town laid on its land, baked by the tessellator through its own command line.

City grammar version 6 writes street lines that bend in height at their junctions' mouths, lots
level at their own grades and terrain graded for them. These tests make a small town on hilly land
with the town composer's version 3, bake every tile it covers, and hold what the tessellator makes
of it: every street, curb and junction the tile owns is drawn; the steps round lots at other
heights than their footways and their neighbours are drawn by the terrain, upright, in what is
drawn and never in what is walked, and every one is closed: wherever two lots at other grades share
an edge, and wherever a footway stands above or below the lot behind it, the step stands whole
from the lower height to the higher; and a person on a footway beside a lot standing above it is
walked at the footway's height, not lifted toward the lot.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from functools import cache
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.grammars.city.document import document_bytes
from exulanica.grammar.grammars.city.land import footway_top_at
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord
from exulanica.grammar.landform import land_recipes
from exulanica.world.composers import city_grammar_town as town
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.world_recipes import town_recipe

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TSX = WEB / "node_modules" / ".bin" / "tsx"
CLI = WEB / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
WORLD = "world:generated:bake-on-land"
#: Bakes carry a footway beside a lot this much higher before the walk beside it is sampled.
RAISED_MM = 200
#: Two lots' edges this near each other across are read as one edge the lots share, so lots that
#: miss each other by a millimetre are named, where a step between them would be left out unseen.
NEAR_MM = 50
#: How far a drawn step may stop short of the height it closes. The footway's top is read here as
#: the walking graph reads it (`footway_top_at`: the kerb line's height rounded half away from
#: zero), the tessellator draws the kerb line's floored heights, and a step's foot runs straight
#: between whole millimetres: the readings differ by less than 2 mm, and a slit a step leaves is
#: wider.
ROUNDING_MM = 2


@cache
def _town():  # type: ignore[no-untyped-def]
    [upland] = [recipe for recipe in land_recipes() if recipe.key == "upland"]
    return compose_generated_world(
        town.on_land(town_recipe("small_town"), dict(upland.land)), WORLD
    )


@pytest.fixture(scope="module")
def baked(tmp_path_factory) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Every tile of the town, baked: its header and its triangles by projection."""
    if not TSX.exists():
        pytest.skip(
            f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/"
        )
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    made = _town()
    directory = tmp_path_factory.mktemp("bake-on-land")
    tiles = []
    for document in town.tile_documents(made.receipt, made.records):
        name = f"tile-{document.tile.tile_x}-{document.tile.tile_y}"
        source, output = directory / f"{name}.json", directory / f"{name}.owd"
        source.write_bytes(document_bytes(document))
        subprocess.run(
            [str(TSX), str(CLI), "bake", str(source), str(output)],
            cwd=WEB,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
        )
        tiles.append(
            _read(output.read_bytes()) | {"tile": (document.tile.tile_x, document.tile.tile_y)}
        )
    return tiles


def _read(container: bytes) -> dict[str, Any]:
    assert container[:4] == b"OWD3"
    (length,) = struct.unpack_from("<I", container, 4)
    header = json.loads(container[8 : 8 + length])
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}
    triangles: dict[str, list[list[list[int]]]] = {}
    for projection in header["projections"]:
        name = projection["name"]
        position, index = sections[(name, "position_mm")], sections[(name, "index")]
        offsets = struct.unpack_from(
            f"<{position['byte_length'] // 4}i", container, position["byte_offset"]
        )
        corners = struct.unpack_from(
            f"<{index['byte_length'] // 4}I", container, index["byte_offset"]
        )
        origin = projection["origin_mm"]
        triangles[name] = [
            [[offsets[corners[t * 3 + c] * 3 + a] + origin[a] for a in range(3)] for c in range(3)]
            for t in range(projection["triangle_count"])
        ]
    return {"header": header, "triangles": triangles}


def _entries(tile: dict[str, Any], projection: str) -> list[tuple[str, dict[str, Any]]]:
    header = tile["header"]
    [found] = [p for p in header["projections"] if p["name"] == projection]
    return [(header["records"][e["record"]]["kind"], e) for e in found["entries"]]


def _upright(triangle: list[list[int]]) -> bool:
    (ax, ay, _), (bx, by, _), (cx, cy, _) = triangle
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) == 0


def test_every_street_curb_and_junction_a_tile_owns_is_drawn(baked):
    assert len(baked) == 2
    for tile in baked:
        for kind, entry in _entries(tile, "render_batch"):
            if kind in ("city.street_segment", "city.curb_edge", "city.junction"):
                assert entry["state"] in ("drawn", "halo"), (tile["tile"], kind, entry)


def test_the_steps_are_the_terrains_upright_and_drawn_but_never_walked(baked):
    steps = 0
    for tile in baked:
        for kind, entry in _entries(tile, "render_batch"):
            if kind == "city.terrain" and entry["state"] == "drawn":
                upright = [s for s in entry["surfaces"] if s["orientation"] == "vertical"]
                assert [s["role"] for s in upright] in ([], ["terrain"])
                steps += sum(s["triangle_count"] for s in upright)
        # Nothing walked stands upright: no step reaches the walking surface.
        assert not any(_upright(triangle) for triangle in tile["triangles"]["nav_envelope"])
    assert steps > 0, "a town on hilly land draws no step"


def _steps(tile: dict[str, Any]) -> list[list[list[int]]]:
    """The terrain's upright triangles in a tile's drawing: its steps."""
    triangles = tile["triangles"]["render_batch"]
    return [
        triangles[index]
        for kind, entry in _entries(tile, "render_batch")
        if kind == "city.terrain" and entry["state"] == "drawn"
        for surface in entry["surfaces"]
        if surface["orientation"] == "vertical"
        for index in range(
            surface["first_triangle"], surface["first_triangle"] + surface["triangle_count"]
        )
    ]


def _reach(triangle: list[list[int]], axis: int, place: int) -> tuple[float, float] | None:
    """The heights an upright triangle spans at ``place`` along ``axis``, or None off its run."""
    heights: list[float] = []
    for one, other in ((0, 1), (1, 2), (2, 0)):
        a, b = triangle[one], triangle[other]
        if a[axis] == b[axis]:
            if a[axis] == place:
                heights += [a[2], b[2]]
        elif min(a[axis], b[axis]) <= place <= max(a[axis], b[axis]):
            heights.append(a[2] + (b[2] - a[2]) * (place - a[axis]) / (b[axis] - a[axis]))
    return (min(heights), max(heights)) if heights else None


def _closed(
    steps: list[list[list[int]]], axis: int, across: int, place: int, low: int, high: int
) -> bool:
    """Whether the steps standing on the line where the other coordinate is ``across`` close the
    height from ``low`` to ``high`` at ``place`` along it, to the millimetres the readings round
    (:data:`ROUNDING_MM`)."""
    reaches = sorted(
        reach
        for triangle in steps
        if all(corner[1 - axis] == across for corner in triangle)
        and (reach := _reach(triangle, axis, place)) is not None
    )
    top: float = low
    for bottom, head in reaches:
        if bottom > top + 1:
            break
        top = max(top, head)
    return top >= high - ROUNDING_MM


def _edges(ring: tuple[tuple[int, int], ...]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    return [(ring[index], ring[(index + 1) % len(ring)]) for index in range(len(ring))]


def _inside(low: int, high: int) -> list[int]:
    """Seven places spread evenly inside ``low`` to ``high``."""
    return [low + (high - low) * step // 8 for step in range(1, 8)]


def test_every_step_between_lots_and_at_a_frontage_is_closed_by_the_terrain(baked):
    """Wherever two lots at other grades share an edge, and wherever a footway stands above or
    below the lot behind it, the terrain draws the step whole: at seven places along it, and on a
    frontage at every point of its kerb line beside it too, where the footway bends and a step
    missing a cut stands furthest from it, from the lower height to the higher. A step a tile
    leaves out (beyond its patch's heights, or at a tile's edge) leaves a place open, and lots whose
    shared edge misses by a millimetre are named."""
    made = _town()
    steps = [triangle for tile in baked for triangle in _steps(tile)]
    lots = [r for r in made.records if isinstance(r, ParcelRecord)]
    curbs = {c.identity: c for c in made.records if isinstance(c, CurbEdgeRecord)}
    shared = 0
    for index, one in enumerate(lots):
        for other in lots[index + 1 :]:
            if one.grade_elevation_mm == other.grade_elevation_mm:
                continue
            low, high = sorted((one.grade_elevation_mm, other.grade_elevation_mm))
            for (a, b), (c, d) in product(_edges(one.boundary_mm), _edges(other.boundary_mm)):
                for axis in (0, 1):
                    if a[1 - axis] != b[1 - axis] or c[1 - axis] != d[1 - axis]:
                        continue
                    if abs(a[1 - axis] - c[1 - axis]) > NEAR_MM:
                        continue
                    start = max(min(a[axis], b[axis]), min(c[axis], d[axis]))
                    end = min(max(a[axis], b[axis]), max(c[axis], d[axis]))
                    if end <= start:
                        continue
                    shared += 1
                    assert a[1 - axis] == c[1 - axis], (one.identity, other.identity, "miss")
                    for place in _inside(start, end):
                        assert _closed(steps, axis, a[1 - axis], place, low, high), (
                            one.identity,
                            other.identity,
                            place,
                        )
    fronted = 0
    for lot in lots:
        for frontage in lot.frontages:
            a, b = _edges(lot.boundary_mm)[frontage.edge_ordinal]
            axis = 0 if a[1] == b[1] else 1
            start, end = sorted((a[axis], b[axis]))
            line = curbs[frontage.curb_identity].kerb_line_mm
            bends = [point[axis] for point in line if start < point[axis] < end]
            for place in sorted({*_inside(start, end), *bends}):
                point = (place, a[1]) if axis == 0 else (a[0], place)
                footway = footway_top_at(curbs[frontage.curb_identity], point)
                if footway == lot.grade_elevation_mm:
                    continue
                fronted += 1
                low, high = sorted((footway, lot.grade_elevation_mm))
                assert _closed(steps, axis, a[1 - axis], place, low, high), (
                    lot.identity,
                    frontage.edge_ordinal,
                    place,
                    footway,
                    lot.grade_elevation_mm,
                )
    assert shared > 0, "no two lots at other grades share an edge"
    assert fronted > 0, "no footway stands off its lot's grade"


def test_a_footway_beside_a_lot_above_it_is_walked_at_its_own_height(baked):
    made = _town()
    curbs = {c.identity: c for c in made.records if isinstance(c, CurbEdgeRecord)}
    walked = 0
    for tile in baked:
        tx, ty = tile["tile"]
        nav = tile["triangles"]["nav_envelope"]
        for lot in (r for r in made.records if isinstance(r, ParcelRecord)):
            ring = list(lot.boundary_mm)
            for frontage in lot.frontages:
                curb = curbs[frontage.curb_identity]
                a, b = ring[frontage.edge_ordinal], ring[(frontage.edge_ordinal + 1) % len(ring)]
                middle = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
                if not (tx * TILE_SIZE_MM < middle[0] < (tx + 1) * TILE_SIZE_MM):
                    continue
                if not (ty * TILE_SIZE_MM < middle[1] < (ty + 1) * TILE_SIZE_MM):
                    continue
                back = footway_top_at(curb, middle)
                if lot.grade_elevation_mm - back < RAISED_MM:
                    continue
                # Half a metre in front of the back edge, toward the kerb, on the footway.
                inward = (-(b[1] - a[1]), b[0] - a[0])
                length = max(abs(inward[0]), abs(inward[1]))
                point = (
                    middle[0] - inward[0] * 500 // length,
                    middle[1] - inward[1] * 500 // length,
                )
                heights = [z for z in (_height_at(t, point) for t in nav) if z is not None]
                if not heights:
                    continue
                walked += 1
                assert max(heights) <= back, (lot.identity, point, max(heights), back)
                assert max(heights) < lot.grade_elevation_mm - RAISED_MM // 2
    assert walked > 0, "no footway beside a raised lot was sampled"


def _height_at(triangle: list[list[int]], point: tuple[int, int]) -> float | None:
    """The height of a non-upright triangle at a plan point inside it, or None."""
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if area == 0:
        return None
    x, y = point
    u = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / area
    v = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / area
    w = 1 - u - v
    if min(u, v, w) < 0:
        return None
    return u * az + v * bz + w * cz
