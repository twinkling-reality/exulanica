"""The city grammar's street surface (:mod:`exulanica.grammar.grammars.city.surface`) answers the
height the page stands a person on.

``tests/fixtures/city-surface-table.json`` is the page's own walk surface (each tile's
``nav_envelope`` read by atlas-react's ``composedSupport``), sampled over the street surfaces of
tess's conformance tile and tile (0, 0) of a small town, written by
``web/packages/atlas-react/test/write-city-surface-table.ts``. Every answer, from a kerb top, a
footway or a carriageway, is held to it within the rounding of one millimetre. Where this version
states no surface (a corner's footway wedge) the answer is None, and how many rows that is on
each tile is pinned, so a rule that stops answering fails here.

Run as a script with a path, it writes the small town's tile (0, 0) document the table was made
from: ``PYTHONPATH=. .venv/bin/python tests/test_city_surface.py <path>``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final

import pytest
from exulanica.grammar.grammars.city import surface
from exulanica.grammar.grammars.city.document import read_tile_document
from exulanica.grammar.grammars.city.streets import CrossingRecord, CurbEdgeRecord
from exulanica.grammar.grammars.city.surface import (
    CARRIAGEWAY,
    FOOTWAY,
    KERB_TOP,
    city_surface_reading,
    city_surface_z_at,
)

ROOT: Final = Path(__file__).resolve().parents[1]
TABLE: Final = ROOT / "tests" / "fixtures" / "city-surface-table.json"
#: How far, in micrometres, an answer may be from the page's height: half a millimetre of the
#: answer's own rounding and one millimetre of the tessellator's floored placement of a point.
WITHIN_UM: Final = 1_500
#: Rows each tile's surface answers None for (a corner's footway wedge), by drawing kind.
UNSTATED: Final = {
    "conformance": {"city.curb_edge": 61},
    "small_town": {"city.curb_edge": 94},
}


def town_document_bytes(world_id: str, tile: tuple[int, int]) -> bytes:
    """The small town ``world_id`` makes, tile ``tile``'s document bytes: what the tile worker
    bakes for it."""
    from exulanica.world.composers.city_grammar_town import tile_document_bytes, tile_documents
    from exulanica.world.generated_worlds import compose_specified_world

    world = compose_specified_world("small_town", None, world_id)
    for document in tile_documents(world.receipt, world.records):
        if (document.tile.tile_x, document.tile.tile_y) == tile:
            return tile_document_bytes(document)
    raise LookupError(f"the small town has no tile {tile}")


def _table() -> dict[str, Any]:
    return json.loads(TABLE.read_text())


def _tile(name: str) -> dict[str, Any]:
    return next(tile for tile in _table()["tiles"] if tile["name"] == name)


def _records(name: str) -> list[object]:
    tile = _tile(name)
    if name == "conformance":
        data = (ROOT / "web" / tile["document"]).read_bytes()
    else:
        town = tile["town"]
        data = town_document_bytes(town["world_id"], tuple(town["tile"]))
    assert hashlib.sha256(data).hexdigest() == tile["document_sha256"]
    document = read_tile_document(data)
    return [record for grammar in document.grammars for record in (*grammar.owned, *grammar.halo)]


@pytest.fixture(scope="module")
def conformance() -> list[object]:
    return _records("conformance")


@pytest.mark.parametrize("name", ["conformance", "small_town"])
def test_every_answer_is_the_height_the_page_stands_a_person_on(name: str) -> None:
    reading = city_surface_reading(_records(name))
    unstated: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    for x, y, page_um, kind in _tile(name)["rows"]:
        answer = reading((x, y))
        if answer is None:
            unstated[kind] += 1
            continue
        height, rule = answer
        rules[rule] += 1
        assert abs(height * 1_000 - page_um) <= WITHIN_UM, (name, x, y, rule, height, page_um)
    assert dict(unstated) == UNSTATED[name]
    assert rules[KERB_TOP] and rules[FOOTWAY] and rules[CARRIAGEWAY]


def test_a_point_off_every_street_has_no_street_surface(conformance: list[object]) -> None:
    surface = city_surface_z_at(conformance)
    assert surface((0, 0)) is None
    assert surface((10**9, 10**9)) is None


def test_a_crossing_answers_the_carriageway_it_is_drawn_on(conformance: list[object]) -> None:
    reading = city_surface_reading(conformance)
    crossings = [record for record in conformance if isinstance(record, CrossingRecord)]
    assert crossings
    for crossing in crossings:
        (x0, y0, _z0), (x1, y1, _z1) = crossing.line_mm
        middle = ((x0 + x1) // 2, (y0 + y1) // 2)
        answer = reading(middle)
        assert answer is not None and answer[1] == CARRIAGEWAY


def test_the_kerb_line_stands_on_the_kerb_top_not_the_gutter(conformance: list[object]) -> None:
    # Where the kerb face stands, the carriageway's gutter and the kerb top are both over the
    # point, and a person is on the higher.
    reading = city_surface_reading(conformance)
    curbs = [record for record in conformance if isinstance(record, CurbEdgeRecord)]
    assert curbs
    for curb in curbs:
        (x0, y0, z0), (x1, y1, z1) = curb.kerb_line_mm[0], curb.kerb_line_mm[-1]
        assert z0 == z1 and (x0 == x1 or y0 == y1), (
            "the fixture's kerbs are level and run along an axis"
        )
        assert reading(((x0 + x1) // 2, (y0 + y1) // 2)) == (z0 + curb.kerb_height_mm, KERB_TOP)


def test_a_footway_rises_by_its_crossfall_from_the_kerb_top(conformance: list[object]) -> None:
    reading = city_surface_reading(conformance)
    curb = next(
        record
        for record in conformance
        if isinstance(record, CurbEdgeRecord) and record.footway_crossfall_millionths
    )
    (x0, y0, z0), (x1, y1, _z1) = curb.kerb_line_mm[0], curb.kerb_line_mm[-1]
    # A point a third of the way along, at the kerb top and at the frontage line, out on the
    # face side (left of a left curb's direction, right of a right one's).
    dx, dy = x1 - x0, y1 - y0
    unit = (-dy, dx) if curb.side == "left" else (dy, -dx)
    length = max(abs(unit[0]), abs(unit[1]))
    along = (x0 + dx // 3, y0 + dy // 3)

    def out(distance: int) -> tuple[int, int]:
        return (along[0] + unit[0] * distance // length, along[1] + unit[1] * distance // length)

    assert abs(dx) == 0 or abs(dy) == 0, "the fixture's curbs run along an axis"
    top = reading(out(curb.kerb_width_mm // 2))
    frontage = reading(out(curb.kerb_width_mm + curb.footway_width_mm))
    assert top == (z0 + curb.kerb_height_mm, KERB_TOP)
    rise = curb.footway_width_mm * curb.footway_crossfall_millionths // 10**6
    assert frontage == (z0 + curb.kerb_height_mm + rise, FOOTWAY)


if __name__ == "__main__":
    Path(sys.argv[1]).write_bytes(town_document_bytes("city-surface-table", (0, 0)))


@pytest.mark.parametrize("name", ["conformance", "small_town"])
def test_a_read_asks_only_its_cells_pieces_and_answers_as_asking_every_piece(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reading's cell index changes no answer: over each table tile, on a grid, on both sides
    of every cell edge and at every corner of its triangles (where a footway meets a kerb top at
    the same height, so the earlier piece answers), an indexed read answers as a read whose one
    cell holds every piece, the surface and the height both."""
    records = _records(name)
    corners: list[tuple[int, int]] = []
    triangle_height = surface._triangle_height

    def kept(triangle: Any) -> Any:
        corners.extend((x, y) for x, y, _ in triangle)
        return triangle_height(triangle)

    with monkeypatch.context() as patched:
        patched.setattr(surface, "_triangle_height", kept)
        indexed = surface.city_surface_reading(records)
    rows = _tile(name)["rows"]
    low_x, high_x = min(row[0] for row in rows) - 2_000, max(row[0] for row in rows) + 2_000
    low_y, high_y = min(row[1] for row in rows) - 2_000, max(row[1] for row in rows) + 2_000
    cell = surface._CELL_MM
    grid = [(x, y) for x in range(low_x, high_x, 3_001) for y in range(low_y, high_y, 3_001)]
    edges = [
        point
        for edge in range(low_x // cell * cell, high_x, cell)
        for y in range(low_y, high_y, 9_001)
        for point in ((edge - 1, y), (edge, y), (y, edge - 1), (y, edge))
    ]
    points = [*grid, *edges, *((row[0], row[1]) for row in rows), *sorted(set(corners))]
    answers = [indexed(point) for point in points]
    with monkeypatch.context() as patched:
        patched.setattr(surface, "_CELL_MM", 10**12)
        every = surface.city_surface_reading(records)
        expected = [every(point) for point in points]
    assert sum(answer is not None for answer in expected) > len(points) // 10
    assert answers == expected


def test_where_a_footway_meets_its_kerb_top_at_one_height_the_kerb_top_answers(
    conformance: list[object],
) -> None:
    """Of pieces answering one height, the one listed first answers: at a corner of a footway's
    triangles on the conformance tile, where the footway starts at its kerb top's height, the kerb
    top answers."""
    assert city_surface_reading(conformance)((20_000, 35_050)) == (55, KERB_TOP)
