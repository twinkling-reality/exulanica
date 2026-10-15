"""A town laid on its land, baked by the tessellator through its own command line.

City grammar version 6 writes street lines that bend in height at their junctions' mouths, lots
level at their own grades and terrain graded for them. These tests make a small town on hilly land
with the town composer's version 3, bake every tile it covers, and hold what the tessellator makes
of it: every street, curb and junction the tile owns is drawn; the steps round lots at other
heights than their footways and their neighbours are drawn by the terrain, upright, in what is
drawn and never in what is walked; and a person on a footway beside a lot standing above it is
walked at the footway's height, not lifted toward the lot.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from functools import cache
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
