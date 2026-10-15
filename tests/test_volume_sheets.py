"""Where people can stand on a volume: a capped top is level, a dome's steep flanks and the foot of
a taller wall are left out, separate tops are separate surfaces in a fixed order, scenery has none,
and a sheet is pinned and read back only as the sheet its digest names."""

from __future__ import annotations

import copy

import pytest
from exulanica.grammar.volumes import (
    PROFILE,
    VolumeField,
    VolumeRefused,
    VolumeSheet,
    read_volume_document,
    read_volume_sheet,
    volume_tops,
)
from exulanica.grammar.volumes.sheets import CLEAR_MM, SHEET_CELL_MM

from test_volume_document import STACK
from test_volume_field import SEED

#: The stack's walkable tops under volume rules version 1. A change that moves a top is a new
#: rules version.
GOLDEN_TOPS = {
    "cells": [696, 2],
    "digests": [
        "57541eaf8aebccb7a0959584f6b1802b1d6ca73dfcc02c741977a7024b2ae0af",
        "47364b18e46a7752870f58d9b173241a09900d5686b3b40ef13bd49f237e6f85",
    ],
}


def field_of(*parts: dict, **top: object) -> VolumeField:
    raw = {"profile": PROFILE, "id": "probe", **top, "parts": list(parts)}
    return VolumeField(read_volume_document(raw), SEED)


def walkable_corners(sheet: VolumeSheet) -> set[tuple[int, int, int]]:
    """Every corner of a walkable cell: its position and its top."""
    corners = set()
    x0, y0 = sheet.origin_mm
    for row, first, last in sheet.walkable:
        for column in range(first, last + 1):
            for dj in (0, 1):
                for di in (0, 1):
                    i, j = column + di, row + dj
                    height = sheet.height_mm[j * sheet.columns + i]
                    corners.add((x0 + i * SHEET_CELL_MM, y0 + j * SHEET_CELL_MM, height))
    return corners


def test_a_capped_column_is_one_level_top_at_its_cap():
    field = field_of(
        {"id": "drum", "shape": "column", "height_mm": 30000, "base_radius_mm": 10000,
         "top_radius_mm": 10000},
        {"id": "level", "shape": "cap", "height_mm": 25000},
    )  # fmt: skip
    (sheet,) = volume_tops(field)
    assert sheet.surface == "top:0"
    corners = walkable_corners(sheet)
    assert {height for _, _, height in corners} == {25000}
    assert all(x * x + y * y <= 10000 * 10000 for x, y, _ in corners)
    assert 250 <= sheet.cells <= 314  # the cells wholly inside a 10 m circle


def test_a_dome_is_walked_only_where_it_is_no_steeper_than_one_in_four():
    field = field_of({"id": "dome", "shape": "sphere", "radius_mm": 10000})
    (sheet,) = volume_tops(field)
    corners = walkable_corners(sheet)
    # A sphere is 1 in 4 where the distance from its axis is a quarter of its radius over the
    # square root of 1 and 1/16: about 2.43 m here; a cell's corners lie within a cell of it.
    assert sheet.cells >= 4
    assert all(x * x + y * y <= 3500 * 3500 for x, y, _ in corners)


def test_two_tops_are_two_surfaces_and_the_foot_of_a_taller_wall_is_left_out():
    # A slab 2 m high to x = 5 m, and a wall 10 m high standing on it from x = 4.5 m: the wall's
    # face lies between lattice points, so the cell next to it is level and only headroom can
    # leave it out.
    field = field_of(
        {"id": "slab", "shape": "box", "at_mm": [-10000, 0, 0], "size_mm": [30000, 20000, 2000]},
        {"id": "wall", "shape": "box", "at_mm": [5500, 0, 0], "size_mm": [2000, 20000, 10000]},
    )  # fmt: skip
    slab, wall = volume_tops(field)
    assert (slab.surface, wall.surface) == ("top:0", "top:1")
    assert {height for _, _, height in walkable_corners(slab)} == {2000}
    assert {height for _, _, height in walkable_corners(wall)} == {10000}
    # A head 1.2 m above the slab is clear of the wall's face at x = 4.5 m only a metre away, so
    # the lattice point at x = 4 m is not walked, though the cell from 3 m to 4 m is level.
    face = 4500
    assert max(x for x, _, _ in walkable_corners(slab)) == 3000
    assert max(x for x, _, _ in walkable_corners(slab)) <= face - CLEAR_MM


def test_scenery_has_no_tops():
    field = field_of({"id": "ball", "shape": "sphere", "radius_mm": 8000}, walk="none")
    assert volume_tops(field) == ()


def test_the_stack_tops_are_pinned():
    field = VolumeField(read_volume_document(STACK), SEED)
    sheets = volume_tops(field)
    assert [sheet.cells for sheet in sheets] == GOLDEN_TOPS["cells"]
    assert [sheet.sha256 for sheet in sheets] == GOLDEN_TOPS["digests"]


@pytest.fixture(scope="module")
def sheet() -> VolumeSheet:
    field = field_of({"id": "dome", "shape": "sphere", "radius_mm": 10000})
    return volume_tops(field)[0]


def test_a_sheet_reads_back_only_as_the_sheet_its_digest_names(sheet):
    assert read_volume_sheet(copy.deepcopy(sheet.document()), sheet.sha256) == sheet
    with pytest.raises(VolumeRefused) as caught:
        read_volume_sheet(sheet.document(), "0" * 64)
    assert caught.value.code == "volume_digest_mismatch"


@pytest.mark.parametrize(
    ("name", "value", "path", "code"),
    [
        ("profile", "exulanica.volume-sheet/v2", "profile", "volume_invalid"),
        ("rules_version", 2, "rules_version", "volume_rules_changed"),
        ("surface", "top:01", "surface", "volume_invalid"),
        ("surface", "bottom:0", "surface", "volume_invalid"),
        ("cell_mm", 500, "cell_mm", "volume_invalid"),
        ("origin_mm", [0], "origin_mm", "volume_invalid"),
        ("columns", 1, "columns", "volume_invalid"),
        ("height_mm", lambda h: h[:-1], "height_mm", "volume_invalid"),
        ("height_mm", lambda h: [0.5, *h[1:]], "height_mm", "volume_invalid"),
        ("walkable", [], "walkable", "volume_invalid"),
        ("walkable", lambda w: [[99, 0, 0]], "walkable[0]", "volume_invalid"),
        ("walkable", lambda w: [[0, 2, 1]], "walkable[0]", "volume_invalid"),
    ],
)  # fmt: skip
def test_a_sheet_that_breaks_its_profile_is_refused_by_path(sheet, name, value, path, code):
    document = copy.deepcopy(sheet.document())
    document[name] = value(document[name]) if callable(value) else value
    with pytest.raises(VolumeRefused) as caught:
        read_volume_sheet(document)
    assert (caught.value.path, caught.value.code) == (path, code)


def test_a_run_that_repeats_or_touches_the_one_before_it_is_refused(sheet):
    runs = sheet.document()["walkable"]
    row, first, last = runs[-1]
    for extra in ([row, first, last], [row, last + 1, last + 1]):
        document = copy.deepcopy(sheet.document())
        document["walkable"] = [*runs, extra]
        with pytest.raises(VolumeRefused) as caught:
            read_volume_sheet(document)
        assert caught.value.path == f"walkable[{len(runs)}]"
