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

import hashlib
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
from exulanica.grammar.grammars.city.land import footway_surface_at, footway_top_at
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


def _bakes(made: Any, directory: Path) -> list[tuple[tuple[int, int], bytes]]:
    """Every tile of a made town, baked by the tessellator's own command line: its place and its
    container."""
    if not TSX.exists():
        pytest.skip(
            f"the web toolchain is not installed ({TSX} is missing); run pnpm install in web/"
        )
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    containers = []
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
        containers.append(((document.tile.tile_x, document.tile.tile_y), output.read_bytes()))
    return containers


@pytest.fixture(scope="module")
def baked(tmp_path_factory) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Every tile of the town, baked: its header and its triangles by projection."""
    return [
        _read(container) | {"tile": place}
        for place, container in _bakes(_town(), tmp_path_factory.mktemp("bake-on-land"))
    ]


#: The level small town on this file's world id, each tile's container digest by its place: what a
#: level town bakes to. The rules for a town on land (a footway's ramp into a mitred corner) leave
#: it alone; a street one tile owns takes its ground from the other tile's terrain across the seam,
#: as on land; and its two tiles share records over their seam.
LEVEL_TOWN_TILES = {
    (0, 0): "f33eb4f0df0a8b77fcbf0498a51dea44b9594ddb1deb7a9290156b023141d495",
    (1, 0): "dfa248a51b9dd966efa22f0976a8328b67a4573e3e41d56bba05c23f670faa64",
}


def test_a_level_town_bakes_byte_for_byte_as_it_did(tmp_path: Path) -> None:
    made = compose_generated_world(town_recipe("small_town"), WORLD)
    digests = {
        place: hashlib.sha256(container).hexdigest() for place, container in _bakes(made, tmp_path)
    }
    assert digests == LEVEL_TOWN_TILES


#: A level small town one of whose streets, owned by tile (1, 0), crosses the seam into tile (0, 0).
LEVEL_SEAM_WORLD = "world:generated:brown-0"
#: The kinds that draw a street's surfaces.
STREET_KINDS = frozenset({"city.street_segment", "city.curb_edge", "city.junction"})


def _plan_height(triangle: list[list[int]], x: float, y: float) -> float | None:
    """The height of ``triangle``'s plane over plan point ``(x, y)``, or None outside it."""
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if area <= 0:
        return None
    wa = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / area
    wb = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / area
    wc = 1 - wa - wb
    if min(wa, wb, wc) < -1e-9:
        return None
    return wa * az + wb * bz + wc * cz


def test_no_terrain_stands_over_a_street_a_level_town_draws_across_its_seam(tmp_path: Path) -> None:
    """A street one tile owns is a halo record in the tile beside it, and takes its ground from that
    tile's terrain as it does in a town on land. The page stands a person on the highest surface
    over a point, so terrain left under a carriageway, level at the town's ground while the
    carriageway's camber falls below it, is the ground they would walk and see."""
    made = compose_generated_world(town_recipe("small_town"), LEVEL_SEAM_WORLD)
    terrain: list[list[list[int]]] = []
    streets: list[list[list[int]]] = []
    for _place, container in _bakes(made, tmp_path):
        tile = _read(container)
        triangles = tile["triangles"]["nav_envelope"]
        for kind, entry in _entries(tile, "nav_envelope"):
            if entry["state"] != "drawn":
                continue
            drawn = triangles[
                entry["first_triangle"] : entry["first_triangle"] + entry["triangle_count"]
            ]
            if kind == "city.terrain":
                terrain += drawn
            elif kind in STREET_KINDS:
                streets += drawn
    assert terrain and streets
    cells: dict[tuple[int, int], list[int]] = {}
    for index, triangle in enumerate(terrain):
        xs, ys = [p[0] for p in triangle], [p[1] for p in triangle]
        for cx in range(min(xs) // 4000, max(xs) // 4000 + 1):
            for cy in range(min(ys) // 4000, max(ys) // 4000 + 1):
                cells.setdefault((cx, cy), []).append(index)
    over = []
    for street in streets:
        x = sum(p[0] for p in street) / 3
        y = sum(p[1] for p in street) / 3
        under = _plan_height(street, x, y)
        if under is None:
            continue
        for index in cells.get((int(x) // 4000, int(y) // 4000), []):
            above = _plan_height(terrain[index], x, y)
            if above is not None and above > under + 1:
                over.append((round(x), round(y), round(under), round(above)))
    assert over == [], f"terrain stands over {len(over)} street triangles, first {over[:3]}"


def _read(container: bytes) -> dict[str, Any]:
    assert container[:4] == b"OWD3"
    (length,) = struct.unpack_from("<I", container, 4)
    header = json.loads(container[8 : 8 + length])
    sections = {(s["projection"], s["name"]): s for s in header["sections"]}
    triangles: dict[str, list[list[list[int]]]] = {}
    indices: dict[str, list[tuple[int, ...]]] = {}
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
        indices[name] = [corners[t * 3 : t * 3 + 3] for t in range(projection["triangle_count"])]
    return {"header": header, "triangles": triangles, "indices": indices}


def _entries(tile: dict[str, Any], projection: str) -> list[tuple[str, dict[str, Any]]]:
    header = tile["header"]
    [found] = [p for p in header["projections"] if p["name"] == projection]
    return [(header["records"][e["record"]]["kind"], e) for e in found["entries"]]


def test_no_drawn_surface_has_a_corner_its_faces_turn_away_from_each_other(baked):
    # A renderer's normal at a corner is the sum of its triangles' facings over their surface: where
    # they face exactly opposite ways it is nothing, the tile is refused and the town does not open.
    for tile in baked:
        triangles, indices = tile["triangles"]["render_batch"], tile["indices"]["render_batch"]
        for kind, entry in _entries(tile, "render_batch"):
            for surface in entry.get("surfaces", []):
                first, count = surface["first_triangle"], surface["triangle_count"]
                sums: dict[int, list[float]] = {}
                for triangle in range(first, first + count):
                    facing = _unit_normal(triangles[triangle])
                    for corner in indices[triangle]:
                        total = sums.setdefault(corner, [0.0, 0.0, 0.0])
                        for axis in range(3):
                            total[axis] += facing[axis]
                for corner, total in sums.items():
                    assert sum(value * value for value in total) > 1e-12, (
                        tile["tile"],
                        kind,
                        surface["role"],
                        surface["orientation"],
                        corner,
                    )


def _unit_normal(triangle: list[list[int]]) -> tuple[float, float, float]:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    u, v = (bx - ax, by - ay, bz - az), (cx - ax, cy - ay, cz - az)
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    size = sum(value * value for value in n) ** 0.5
    return (0.0, 0.0, 0.0) if size == 0 else (n[0] / size, n[1] / size, n[2] / size)


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


#: How far along its kerb line, every so often, a footway is sampled for the walk along it.
STATION_MM = 2000


def _ramp_mm(curb: CurbEdgeRecord, crossing: CurbEdgeRecord, radius: int) -> int:
    """How far from its kerb line's end a footway ramps into the corner there: twice as far as the
    mitre's frontage corner stands back from that end, where the corner mitres; none where it
    does not."""
    reach = curb.kerb_width_mm + curb.footway_width_mm
    other = crossing.kerb_width_mm + crossing.footway_width_mm
    if radius == 0 or (reach < radius and other < radius):
        return 0
    return 2 * max(0, other - radius)


def test_a_footway_is_walked_at_its_own_height_along_its_whole_length(baked):
    """Every curb's footway, sampled across its middle along its kerb line, outside the ramps into
    its mitred corners: no tile walks anything there above the footway's height as the walking
    graph reads it (``footway_surface_at``), and the tile that draws the footway walks it at that
    height, both to :data:`ROUNDING_MM`. A footway over a tile seam is drawn whole by the tile that
    owns it, and the other tile's terrain yields to it."""
    made = _town()
    curbs = {c.identity: c for c in made.records if isinstance(c, CurbEdgeRecord)}
    approached = {after: curb for curb in curbs.values() for after in curb.next_curb_identity}
    owner: dict[str, tuple[int, int]] = {}
    for tile in baked:
        for kind, entry in _entries(tile, "nav_envelope"):
            identity = tile["header"]["records"][entry["record"]].get("identity")
            if kind == "city.curb_edge" and entry["state"] == "drawn":
                owner[identity] = tile["tile"]
    tiles = {tile["tile"]: tile["triangles"]["nav_envelope"] for tile in baked}
    sampled = 0
    for curb in curbs.values():
        (x0, y0, _), (x1, y1, _) = curb.kerb_line_mm[0], curb.kerb_line_mm[-1]
        axis = 0 if y0 == y1 else 1
        start, end = (x0, x1) if axis == 0 else (y0, y1)
        forward = 1 if end > start else -1
        # Left of the line's own direction for a left curb, right of it for a right curb.
        left = (0, forward) if axis == 0 else (-forward, 0)
        out = left if curb.side == "left" else (-left[0], -left[1])
        # The corner at the walk's end is the curb's own, at its walk's start its predecessor's.
        ends: dict[int, int] = {}
        follower = curbs.get(curb.next_curb_identity[0]) if curb.next_curb_identity else None
        before = approached.get(curb.identity)
        walk_end, walk_start = (end, start) if curb.side == "left" else (start, end)
        if follower is not None:
            ends[walk_end] = _ramp_mm(curb, follower, curb.corner_radius_mm)
        if before is not None:
            ends[walk_start] = _ramp_mm(curb, before, before.corner_radius_mm)
        middle = curb.kerb_width_mm + curb.footway_width_mm // 2
        for along in range(min(start, end), max(start, end) + 1, STATION_MM):
            if any(abs(along - at) <= ramp for at, ramp in ends.items()):
                continue
            on_line = (along, y0) if axis == 0 else (x0, along)
            point = (on_line[0] + out[0] * middle, on_line[1] + out[1] * middle)
            stated = footway_surface_at(curb, point)
            here = (point[0] // TILE_SIZE_MM, point[1] // TILE_SIZE_MM)
            for key, nav in tiles.items():
                heights = [z for z in (_height_at(t, point) for t in nav) if z is not None]
                assert max(heights, default=stated) <= stated + ROUNDING_MM, (
                    curb.identity,
                    point,
                    key,
                    here,
                    max(heights),
                    stated,
                )
            drawn_by = tiles[owner[curb.identity]]
            walked = [z for z in (_height_at(t, point) for t in drawn_by) if z is not None]
            if walked:
                sampled += 1
                assert any(abs(z - stated) <= ROUNDING_MM for z in walked), (
                    curb.identity,
                    point,
                    walked,
                    stated,
                )
    assert sampled > 0, "no footway was sampled"


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


def test_a_town_of_three_tiles_bakes_every_tile_beside_the_corners_it_does_not_carry(tmp_path):
    """A market town on land covers three tiles, and a street the middle tile owns turns rounded
    corners into curbs an edge tile does not carry. The edge tile takes that street's ground as a
    halo and leaves its corners to the middle tile, rather than refusing the whole tile."""
    [upland] = [recipe for recipe in land_recipes() if recipe.key == "upland"]
    made = compose_generated_world(
        town.on_land(town_recipe("market_town"), dict(upland.land)), WORLD
    )
    corners_elsewhere = 0
    for document in town.tile_documents(made.receipt, made.records):
        carried = {r.identity for g in document.grammars for r in (*g.owned, *g.halo)}
        corners_elsewhere += sum(
            1
            for g in document.grammars
            for r in g.halo
            if isinstance(r, CurbEdgeRecord)
            and r.corner_radius_mm > 0
            and any(follower not in carried for follower in r.next_curb_identity)
        )
    assert corners_elsewhere > 0, "no halo curb turns a corner into a curb its tile does not carry"
    baked = [_read(container) for _place, container in _bakes(made, tmp_path)]
    assert len(baked) == 3
    for tile in baked:
        for kind, entry in _entries(tile, "render_batch"):
            if kind in ("city.street_segment", "city.curb_edge", "city.junction"):
                assert entry["state"] in ("drawn", "halo"), (kind, entry)
