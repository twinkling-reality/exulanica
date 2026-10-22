"""A volume's top land: read against the version 3 catalogs and refused by path, realized once per
field and capping the mass by its surface, so the walkable tops follow the land where it is no
steeper than 1 in 4; heights given for it, such as a site's graded top, cap the mass in its place
and are named by every realization; a version 3 volume with no top land is version 2's rock."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.grammar.landform import WorldFrame, land_heights
from exulanica.grammar.volumes import (
    EXACT_MM,
    PROFILE,
    TOP_LAND_CELL_MM,
    TopHeights,
    VolumeField,
    VolumeRefused,
    input_sha256,
    read_volume_document,
    realize_top_land,
    realize_volume,
    volume_catalog,
    volume_tops,
)
from exulanica.grammar.volumes import field as field_module
from exulanica.grammar.volumes.sheets import SHEET_CELL_MM

from test_volume_document import STACK
from test_volume_field import GRID, VARIED_STRATA

SEED = hashlib.sha256(b"exulanica volume top land test").digest()
SIDE = 60_000


def land(*features: dict, ground_mm: int = 0) -> dict:
    return {"profile": "exulanica.landform/v1", "ground_mm": ground_mm, "features": list(features)}


def hill(height_mm: int, width_mm: int) -> dict:
    """A smooth round hill in the middle of the square, no noise in it."""
    return {"id": "hill", "kind": "rise", "side": "centre", "width_mm": width_mm,
            "depth_mm": width_mm, "height_mm": height_mm, "roughness_permille": 0}  # fmt: skip


#: A gentle hill: 2 m over a 60 m footprint, at most about 1 in 7.
GENTLE = land(hill(2000, 60000))
#: A steep hill: 6 m over a 24 m footprint, steeper than 1 in 4 round its flanks.
STEEP = land(hill(6000, 24000))


def mesa(top: dict, **extra: object) -> dict:
    """A block 60 m square standing to 10 m, its top the stated land over the 60 m square."""
    return {
        "profile": PROFILE,
        "id": "mesa",
        "parts": [
            {"id": "body", "shape": "box", "at_mm": [0, 0, -20000],
             "size_mm": [SIDE, SIDE, 30000]},
        ],
        "top_land": {"land": top, "side_mm": SIDE, **extra},
    }  # fmt: skip


def mesa_field(top: dict, **extra: object) -> VolumeField:
    return VolumeField(read_volume_document(mesa(top, **extra)), SEED)


def land_at(top: dict, points: list[tuple[int, int]]) -> list[int]:
    """The land's heights at points of the volume's frame, realized apart from the field: the
    square's south-west corner is the land's origin. Neither hill has noise, so the frame's seed
    shapes nothing."""
    heights = []
    read = read_volume_document(mesa(top)).top_land
    assert read is not None
    frame = WorldFrame(width_mm=SIDE, depth_mm=SIDE, seed="0")
    for x, y in points:
        (height,) = land_heights(read.land, frame, [x + SIDE // 2], [y + SIDE // 2])
        heights.append(height)
    return heights


def walkable_cells(field: VolumeField) -> dict[tuple[int, int], list[int]]:
    """Every walkable cell of every top by its south-west corner, with its corners' tops."""
    cells = {}
    for sheet in volume_tops(field):
        x0, y0 = sheet.origin_mm
        for row, first, last in sheet.walkable:
            for column in range(first, last + 1):
                cells[(x0 + column * SHEET_CELL_MM, y0 + row * SHEET_CELL_MM)] = [
                    sheet.height_mm[(row + dj) * sheet.columns + column + di]
                    for dj in (0, 1)
                    for di in (0, 1)
                ]
    return cells


def test_a_gentle_hill_is_one_walkable_top_at_the_land_height_of_each_cell_corner():
    field = mesa_field(GENTLE)
    (sheet,) = volume_tops(field)
    cells = walkable_cells(field)
    # The block's top is the square: every cell of it but a rim cell where the box's edge is.
    assert len(cells) >= (SIDE // SHEET_CELL_MM - 2) ** 2
    corners = sorted(
        {
            (x + di * SHEET_CELL_MM, y + dj * SHEET_CELL_MM): heights[2 * dj + di]
            for (x, y), heights in cells.items()
            for dj in (0, 1)
            for di in (0, 1)
        }.items()
    )
    # Nothing weathers the block and its cut has no blend, so on the lattice the top is the land
    # exactly: the tolerance is 0 mm.
    expected = land_at(GENTLE, [point for point, _ in corners])
    assert [height for _, height in corners] == expected
    assert max(expected) - min(expected) > 1500  # the top climbs the hill, not a level
    assert sheet.surface == "top:0"


def test_a_flank_steeper_than_one_in_four_is_not_walked_and_the_gentler_land_is():
    field = mesa_field(STEEP)
    cells = walkable_cells(field)
    half = SIDE // 2
    steep = gentle = 0
    for y in range(-half, half, SHEET_CELL_MM):
        for x in range(-half, half, SHEET_CELL_MM):
            a, b, c, d = land_at(
                STEEP,
                [(x, y), (x + SHEET_CELL_MM, y), (x, y + SHEET_CELL_MM),
                 (x + SHEET_CELL_MM, y + SHEET_CELL_MM)],
            )  # fmt: skip
            climb = max(abs(a - b), abs(c - d), abs(a - c), abs(b - d))
            if climb > SHEET_CELL_MM // 4:
                steep += 1
                assert (x, y) not in cells, (x, y, climb)
            elif -half < x < half - SHEET_CELL_MM and -half < y < half - SHEET_CELL_MM:
                gentle += 1
                assert (x, y) in cells, (x, y, climb)
    assert steep > 100 and gentle > 1000


def test_the_land_is_realized_once_per_field_not_per_point(monkeypatch):
    calls = []
    realize = field_module.realize_region

    def counted(*args: object) -> object:
        calls.append(args)
        return realize(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(field_module, "realize_region", counted)
    field = mesa_field(GENTLE)
    assert len(calls) == 1
    for x in range(-20000, 20001, 5000):
        field.distance(x, -x, 1000)
    field.grid((-30000, -30000, -2000), 2000, (31, 31, 4))
    volume_tops(field)
    assert len(calls) == 1
    mesa_field(GENTLE)
    assert len(calls) == 2


def test_the_extent_stops_at_the_land_and_beyond_its_square_the_top_is_its_edge_level():
    # A block wider than its 20 m square: outside the square its top is the nearest edge's height.
    tilted = land({"id": "lean", "kind": "tilt", "side": "east", "grade_permille": 100,
                   "reach_mm": 20000}, ground_mm=3000)  # fmt: skip
    raw = mesa(tilted)
    raw["top_land"]["side_mm"] = 20000
    field = VolumeField(read_volume_document(raw), SEED)
    surface = field._top
    assert surface is not None
    assert field.extent[1][2] == surface.highest
    for y in (-25000, 0, 25000):
        assert surface.height(-29000, y) == surface.height(-10000, max(-10000, min(10000, y)))
        assert surface.height(29000, y) == surface.height(10000, max(-10000, min(10000, y)))
    assert surface.height(29000, 0) - surface.height(-29000, 0) == 2000
    assert field.distance(25000, 0, surface.height(10000, 0)) == 0


def test_between_lattice_points_the_surface_is_the_floor_of_the_bilinear_blend():
    surface = mesa_field(STEEP)._top
    assert surface is not None
    a, b = surface.height(3000, 2000), surface.height(4000, 2000)
    c, d = surface.height(3000, 3000), surface.height(4000, 3000)
    assert surface.height(3250, 2500) == (a * 750 * 500 + b * 250 * 500 + c * 750 * 500
                                          + d * 250 * 500) // 1_000_000  # fmt: skip


def test_culling_never_changes_a_value_near_the_surface_or_any_sign_under_a_top_land():
    raw = {**STACK, "strata": VARIED_STRATA, "top_land": {
        "land": land(hill(3000, 24000), {"id": "roll", "kind": "undulation", "amplitude_mm": 800,
                                        "wavelength_mm": 9000}, ground_mm=37000),
        "side_mm": 36000, "blend_mm": 2000}}  # fmt: skip
    document = read_volume_document(raw)
    culled, whole = VolumeField(document, SEED), VolumeField(document, SEED, whole=True)
    origin, counts = (-30000, -26000, -12000), (36, 34, 34)
    fast, reference = culled.grid(origin, 1700, counts), whole.grid(origin, 1700, counts)
    near = [index for index, value in enumerate(reference) if abs(value) < EXACT_MM]
    assert len(near) > 1000 and fast != reference
    assert all(fast[index] == reference[index] for index in near)
    assert all((value <= 0) == (exact <= 0) for value, exact in zip(fast, reference, strict=True))
    # Every solid point lies within the extent, whose top is the land's highest height.
    (lx, ly, lz), (hx, hy, hz) = culled.extent
    for index, value in enumerate(reference):
        if value <= 0:
            k, rest = divmod(index, counts[0] * counts[1])
            j, i = divmod(rest, counts[0])
            x, y, z = origin[0] + 1700 * i, origin[1] + 1700 * j, origin[2] + 1700 * k
            assert lx <= x <= hx and ly <= y <= hy and lz <= z <= hz


def test_a_version_3_volume_with_no_top_land_is_version_2_rock():
    raw = {**STACK, "strata": VARIED_STRATA}
    older = VolumeField(read_volume_document(raw, volume_catalog(2)), SEED)
    newer = VolumeField(read_volume_document(raw), SEED, rules=3)
    # Version 4 reads the same catalogs and is version 3's rock.
    newest = VolumeField(read_volume_document(raw), SEED)
    assert (older.rules, newer.rules, newest.rules) == (2, 3, 4)
    assert newer.document.canonical_bytes == older.document.canonical_bytes
    assert sha256_of_canonical(newer.grid(*GRID)) == sha256_of_canonical(older.grid(*GRID))
    assert sha256_of_canonical(newest.grid(*GRID)) == sha256_of_canonical(older.grid(*GRID))
    assert newer.extent == older.extent == newest.extent


def test_a_version_4_volume_with_a_top_land_is_version_3_rock_naming_4():
    """Volume rules 4 grade a site on a top by later land rules; the rock and its tops, the natural
    top land's realization included, are version 3's vertex for vertex."""
    document = read_volume_document(mesa(GENTLE))
    older, newer = VolumeField(document, SEED, rules=3), VolumeField(document, SEED)
    assert (older.rules, newer.rules) == (3, 4)
    was, now = realize_volume(older, 4000), realize_volume(newer, 4000)
    assert len(was) == len(now) > 0
    for before, after in zip(was, now, strict=True):
        assert (after.chunk, after.positions_mm, after.normals) == (
            before.chunk,
            before.positions_mm,
            before.normals,
        )
        assert (after.looks, after.vertex_looks, after.triangles) == (
            before.looks,
            before.vertex_looks,
            before.triangles,
        )
        assert (before.rules_version, after.rules_version) == (3, 4)
    assert [top.cells for top in volume_tops(newer)] == [top.cells for top in volume_tops(older)]


def test_the_top_land_is_written_into_the_canonical_document_with_its_defaults():
    read = read_volume_document(mesa(GENTLE))
    top = read.canonical()["top_land"]
    assert top["side_mm"] == SIDE and top["blend_mm"] == 0
    assert top["land"]["features"][0]["offset_mm"] == 0  # the land's own defaults written in
    again = read_volume_document(read.canonical())
    assert again.canonical_bytes == read.canonical_bytes and again.top_land == read.top_land


def _with(path: tuple, value: object) -> dict:
    raw = copy.deepcopy(mesa(GENTLE))
    target = raw
    for step in path[:-1]:
        target = target[step]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return raw


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "where", "words"),
    [
        (("top_land",), [SIDE], "top_land", "an object"),
        (("top_land", "land"), _DELETE, "top_land", "states land and"),
        (("top_land", "colour"), 1, "top_land", "states land and"),
        (("top_land", "side_mm"), _DELETE, "top_land.side_mm", "required"),
        (("top_land", "side_mm"), 1000, "top_land.side_mm", "2000 to 128000"),
        (("top_land", "side_mm"), 31000, "top_land.side_mm", "whole 2000 mm"),
        (("top_land", "blend_mm"), -1, "top_land.blend_mm", "0 to 30000"),
        (("top_land", "land", "profile"), "exulanica.landform/v2", "top_land.land.profile",
         "profile is"),
        (("top_land", "land", "ground_mm"), 50000, "top_land.land.ground_mm", "0 to 40000"),
        (("top_land", "land", "features", 0, "height_mm"), 100,
         "top_land.land.features[0].height_mm", "500 to 600000"),
        (("top_land", "land", "features", 0, "kind"), "crater", "top_land.land.features[0].kind",
         "crater"),
    ],
)  # fmt: skip
def test_a_bad_land_or_square_is_refused_by_its_path(path, value, where, words):
    with pytest.raises(VolumeRefused) as caught:
        read_volume_document(_with(path, value))
    assert (caught.value.path, caught.value.code) == (where, "volume_invalid")
    assert words in caught.value.detail


def test_an_earlier_catalog_states_no_top_land():
    for version in (1, 2):
        with pytest.raises(VolumeRefused) as caught:
            read_volume_document(mesa(GENTLE), volume_catalog(version))
        assert caught.value.path == "top_land"
        assert "catalog version 3 or later" in caught.value.detail


def test_a_land_the_realizer_refuses_is_refused_by_its_path_when_the_field_is_made():
    # 40 m of ground and a 30 m hill rise past the 64 m the land is held to about level 0.
    document = read_volume_document(mesa(land(hill(30000, 40000), ground_mm=40000)))
    with pytest.raises(VolumeRefused) as caught:
        VolumeField(document, SEED)
    assert caught.value.path == "top_land.land"
    assert "64000 mm" in caught.value.detail


def graded(top: dict, change: Callable[[int, int, int], int]) -> TopHeights:
    """The mesa's natural top with each lattice height changed by ``change(x, y, height)``, its
    point in the volume's frame: a top graded as a site's grading grades it."""
    read = read_volume_document(mesa(top)).top_land
    assert read is not None
    near = realize_top_land(read, "mesa")
    half = SIDE // 2
    return TopHeights(
        count=near.nx,
        heights=tuple(
            change(
                i * TOP_LAND_CELL_MM - half,
                j * TOP_LAND_CELL_MM - half,
                near.heights[j * near.nx + i],
            )
            for j in range(near.ny)
            for i in range(near.nx)
        ),
    )


def pad(x: int, y: int, height: int) -> int:
    """A level pad 3.5 m up across the middle 16 m, filled above the 2 m hill, and a metre cut
    along the west edge."""
    if abs(x) <= 8000 and abs(y) <= 8000:
        return 3500
    return height - 1000 if x <= -20000 else height


def test_given_heights_cap_the_rock_in_place_of_the_land_and_the_walked_top_is_them():
    given = graded(GENTLE, pad)
    field = VolumeField(read_volume_document(mesa(GENTLE)), SEED, top=given)
    half, count = SIDE // 2, given.count
    corners = {
        (x + di * SHEET_CELL_MM, y + dj * SHEET_CELL_MM): heights[2 * dj + di]
        for (x, y), heights in walkable_cells(field).items()
        for dj in (0, 1)
        for di in (0, 1)
    }
    assert len(corners) >= (SIDE // SHEET_CELL_MM - 2) ** 2
    # Nothing weathers the block and its cut has no blend: on the lattice the top is the given
    # heights exactly, the pad and the cut included.
    for (x, y), height in corners.items():
        assert height == given.heights[(y + half) // 1000 * count + (x + half) // 1000], (x, y)
    assert {corners[(x, y)] for x in range(-8000, 8001, 1000) for y in (-8000, 0, 8000)} == {3500}
    assert corners[(-25000, 0)] == land_at(GENTLE, [(-25000, 0)])[0] - 1000
    # The extent stops at the given heights' highest, above the land's own.
    assert field.extent[1][2] == max(given.heights) == 3500
    assert mesa_field(GENTLE).extent[1][2] < 2100


def test_given_heights_are_named_by_every_chunk_and_sheet_and_a_field_given_none_names_none():
    document = read_volume_document(mesa(GENTLE))
    natural = VolumeField(document, SEED)
    own = VolumeField(document, SEED, top=graded(GENTLE, lambda x, y, height: height))
    capped = VolumeField(document, SEED, top=graded(GENTLE, pad))
    # A field capped by its own land names what it named before heights could be given.
    assert (
        input_sha256(natural)
        == hashlib.sha256(
            canonical_json(
                {"volume_sha256": document.sha256, "seed": SEED.hex(), "volume_rules": 4}
            )
        ).hexdigest()
    )
    assert len({input_sha256(field) for field in (natural, own, capped)}) == 3
    # The land's own heights, given, cap the rock exactly as the land does.
    grid = ((-31000, -31000, -3000), 2000, (32, 32, 5))
    assert own.grid(*grid) == natural.grid(*grid)
    assert capped.grid(*grid) != natural.grid(*grid)
    chunks = realize_volume(capped, 4000)
    assert chunks and {chunk.input_sha256 for chunk in chunks} == {input_sha256(capped)}
    assert {sheet.input_sha256 for sheet in volume_tops(capped)} == {input_sha256(capped)}


def test_given_heights_off_the_squares_lattice_or_for_a_volume_with_no_top_land_are_refused():
    document = read_volume_document(mesa(GENTLE))
    given = graded(GENTLE, pad)
    fewer = given.count - 1
    for wrong in (
        TopHeights(count=fewer, heights=given.heights[: fewer * fewer]),
        TopHeights(count=given.count, heights=given.heights[:-1]),
    ):
        with pytest.raises(VolumeRefused) as caught:
            VolumeField(document, SEED, top=wrong)
        assert (caught.value.path, caught.value.code) == ("top_land", "volume_top_heights_invalid")
    with pytest.raises(VolumeRefused) as caught:
        VolumeField(read_volume_document(STACK), SEED, top=given)
    assert (caught.value.path, caught.value.code) == ("top_land", "volume_top_heights_invalid")
