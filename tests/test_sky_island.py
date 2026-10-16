"""The sky island: its catalogs pinned, every value held to its bound and refused by path and code,
and the maker's volume admitted by the volume reader, the same for the same island and seed, and
shaped by its rules: level at 0, centred, no deeper than stated, narrowing below the slab; or, where
it states a top land, walked on that land, its rock left high enough for a site's fills."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.islands import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    LATER,
    PROFILE,
    IslandRefused,
    island_catalog,
    load_island_catalog,
    make_island_volume,
    read_island_document,
)
from exulanica.grammar.landform import read_land_document
from exulanica.grammar.volumes import (
    CATALOG_VERSION as VOLUME_CATALOG_VERSION,
)
from exulanica.grammar.volumes import (
    TOP_LAND_CELL_MM,
    TopHeights,
    TopLandSurface,
    VolumeDocument,
    VolumeField,
    read_volume_document,
    realize_top_land,
    volume_catalog,
    volume_tops,
)
from exulanica.grammar.volumes.sheets import SHEET_CELL_MM

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "islands"

#: Every shipped sky-island catalog, byte for byte. A catalog changes by a new file, never by an
#: edit, since an island's defaults are written in from it.
SHIPPED = {
    "sky-island-value.v1.json": "2e9f3bf90d036aff61941d8c7fc16ef873781446c0a0d41bb0bb02aabf8d397d",
    "sky-island-value.v2.json": "adb133d1ea6844a631d8d0e0e968026867b1feebcb06025daf7a0fbc81c93bee",
    "sky-island-value.v3.json": "26efb1101adff286a14161f78d6fb0896b8e3678928fdbf4d86f44804704f2b5",
}

#: About 40 m across, the widest the catalog admits, weathered and bedded as islands read well.
HIGH = {
    "profile": PROFILE,
    "id": "high_island",
    "radius_mm": 20000,
    "lobes": 3,
    "rim_mm": 11000,
    "depth_mm": 40000,
    "erosion": {"amplitude_mm": 2600, "wavelength_mm": 9000, "octaves": 3, "ridged": "yes"},
    "strata": {"amplitude_mm": 1100, "period_mm": 4500, "spread_mm": 2500,
               "relief_permille": 600, "offset_permille": 700, "tilt_mdeg": 4000,
               "toward_mdeg": 70000},
}  # fmt: skip
#: About 24 m across with a keel about 1.5 times its width deep, and thinner beds.
SMALL = {
    "profile": PROFILE,
    "id": "small_island",
    "radius_mm": 12000,
    "lobes": 2,
    "rim_mm": 6500,
    "depth_mm": 36000,
    "fingers": 3,
    "erosion": {"amplitude_mm": 1500, "wavelength_mm": 8000, "octaves": 4, "ridged": "yes"},
    "strata": {"amplitude_mm": 700, "period_mm": 2800, "spread_mm": 800,
               "relief_permille": 600, "offset_permille": 500, "tilt_mdeg": 5000,
               "toward_mdeg": 200000},
}  # fmt: skip
SEED = b"golden"
#: Each island's identity and the identity of the volume it makes under SEED.
GOLDEN = {
    "high_island": (
        "26fe025f3f60d3af88fcc482f8f31a59036ef01fbb636d18a34a7ea9dd3d65f7",
        "e2d8f37bd833371e1fa866c5651965758ac67cfff378e8a47a1cc3f05847d047",
    ),
    "small_island": (
        "3af69aa3d098c599b932498de9bb5ec1c0be3336d7425532514b5344efc2afdd",
        "1f8c21cf89bc1dcf4b1a523e0fbb72f71cf40201bbed3e4214963ea8d8354312",
    ),
}
UNDERSIDES = ("cone", "bowl", "spires")
#: The top as land: a round hill 2 m high over 40 m in the middle of the top, gentle enough to
#: walk all over, no noise in it.
HILL_TOP = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 0,
    "features": [{"id": "hill", "kind": "rise", "side": "centre", "width_mm": 40000,
                  "depth_mm": 40000, "height_mm": 2000, "roughness_permille": 0}],
}  # fmt: skip
#: The top as land falling below the top height: a dry hollow 2 m deep in the middle of the top.
HOLLOW_TOP = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 0,
    "features": [{"id": "hollow", "kind": "basin", "side": "centre", "radius_mm": 10000,
                  "depth_mm": 2000, "water": "dry"}],
}  # fmt: skip


def island(**values: object) -> dict:
    return {"profile": PROFILE, "id": "isle", "radius_mm": 20000, "rim_mm": 6000,
            "depth_mm": 30000, **values}  # fmt: skip


def refusal(raw: object) -> IslandRefused:
    with pytest.raises(IslandRefused) as caught:
        read_island_document(raw)
    return caught.value


def made(raw: dict, seed: bytes = SEED):
    return make_island_volume(read_island_document(raw), seed)


def test_the_shipped_catalog_is_never_edited():
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in CATALOGS.iterdir()
    }
    assert found == SHIPPED


def test_every_value_holds_its_default_and_every_word_is_a_volume_word():
    assert CATALOG_VERSIONS == (1, 2, 3)
    assert [island_catalog(version).volume_catalog_version for version in CATALOG_VERSIONS] == [
        2,
        3,
        3,
    ]
    catalog = island_catalog()
    assert (catalog.version, catalog.volume_catalog_version) == (3, 3)
    assert catalog.values["top"].words == ("level", "land")
    fill = catalog.values["top_fill_mm"]
    assert (fill.minimum, fill.maximum, fill.default, fill.required) == (0, 4000, 4000, False)
    # Every entry of the version before is kept as it was.
    second = island_catalog(2)
    assert {name: catalog.values[name] for name in second.values} == dict(second.values)
    own = volume_catalog(catalog.volume_catalog_version).values_of("volume")
    for name, bound in catalog.values.items():
        if bound.words:
            assert 0 <= bound.default < len(bound.words), name
            if name in own:
                assert set(bound.words) <= set(own[name].words), name
        else:
            assert bound.minimum <= bound.default <= bound.maximum, name
    assert catalog.values["underside"].words == UNDERSIDES


def test_a_catalog_bounding_another_owner_is_refused(tmp_path):
    shutil.copy(CATALOGS / "sky-island-value.v1.json", tmp_path)
    path = tmp_path / "sky-island-value.v1.json"
    document = json.loads(path.read_text())
    document["entries"][0]["owner"] = "volume"
    path.write_text(json.dumps(document))
    with pytest.raises(CatalogError, match="unknown owner"):
        load_island_catalog(tmp_path, version=1)
    with pytest.raises(CatalogError, match="versions"):
        load_island_catalog(version=4)


def test_a_stated_island_is_read_with_its_defaults_written_in():
    read = read_island_document(island())
    assert read.canonical() == {
        "profile": PROFILE,
        "id": "isle",
        "radius_mm": 20000,
        "lobes": 3,
        "rim_mm": 6000,
        "depth_mm": 30000,
        "underside": "cone",
        "fingers": 0,
        "look": "rock",
        "top_look": "grass",
        "walk": "tops",
        "erosion": {"amplitude_mm": 0, "wavelength_mm": 12000, "octaves": 3, "ridged": "no"},
        "strata": {"amplitude_mm": 0, "period_mm": 3000, "spread_mm": 0, "relief_permille": 0,
                   "offset_permille": 0, "tilt_mdeg": 0, "toward_mdeg": 0},
    }  # fmt: skip
    assert (read.catalog_version, read.volume_catalog_version) == (CATALOG_VERSION, 3)
    assert read.top is None
    assert read.sha256 == hashlib.sha256(read.canonical_bytes).hexdigest()
    assert read_island_document(read.canonical()).canonical_bytes == read.canonical_bytes


def test_reading_and_making_never_change_the_document_given():
    raw = copy.deepcopy(HIGH)
    make_island_volume(read_island_document(raw), SEED)
    assert raw == HIGH


_DELETE = object()


@pytest.mark.parametrize(
    ("change", "where", "code", "words"),
    [
        ({"profile": "exulanica.sky-island/v2"}, "profile", "island_invalid", "profile is"),
        ({"colour": "red"}, "", "island_invalid", "may have"),
        ({"id": "Sky Isle"}, "id", "island_invalid", "lowercase key"),
        ({"radius_mm": _DELETE}, "", "island_invalid", "has ["),
        ({"radius_mm": 7999}, "radius_mm", "island_invalid", "8000 to 20000"),
        ({"radius_mm": 20001}, "radius_mm", "island_invalid", "8000 to 20000"),
        ({"radius_mm": "20000"}, "radius_mm", "island_invalid", "whole number"),
        ({"radius_mm": True}, "radius_mm", "island_invalid", "whole number"),
        ({"lobes": 6}, "lobes", "island_invalid", "1 to 5"),
        ({"lobes": 0}, "lobes", "island_invalid", "1 to 5"),
        ({"rim_mm": 1999}, "rim_mm", "island_invalid", "2000 to 20000"),
        ({"depth_mm": 3999}, "depth_mm", "island_invalid", "4000 to 60000"),
        ({"underside": "dome"}, "underside", "island_invalid", "cone, bowl, spires"),
        ({"fingers": 5}, "fingers", "island_invalid", "0 to 4"),
        ({"look": "glass"}, "look", "island_invalid", "rock, wall"),
        ({"top_look": "snow"}, "top_look", "island_invalid", "grass, moss, rock, sand"),
        ({"walk": "all"}, "walk", "island_invalid", "tops, none"),
        ({"erosion": 3}, "erosion", "island_invalid", "an object"),
        ({"erosion": {"depth_mm": 3}}, "erosion", "island_invalid", "states no depth_mm"),
        ({"erosion": {"amplitude_mm": 9000}}, "erosion.amplitude_mm", "island_invalid",
         "0 to 8000"),
        ({"strata": {"amplitude_mm": 900, "period_mm": 3000, "spread_mm": 2001}},
         "strata.spread_mm", "island_invalid", "at least 1 m"),
        ({"radius_mm": 10000, "depth_mm": 30001}, "depth_mm", "island_too_deep",
         "three times the radius"),
        ({"radius_mm": 10000, "rim_mm": 10001}, "rim_mm", "island_rim_too_thick", "the radius"),
        ({"rim_mm": 15001}, "rim_mm", "island_rim_too_thick", "half the depth"),
        ({"top": {}}, "top", "island_invalid", "a land document has exactly"),
        ({"top": {**HILL_TOP, "ground_mm": "low"}}, "top.ground_mm", "island_invalid",
         "whole number"),
        ({"top_fill_mm": 1000}, "top_fill_mm", "island_invalid", "states no top"),
        ({"top": HILL_TOP, "top_fill_mm": 4001}, "top_fill_mm", "island_invalid", "0 to 4000"),
        ({"top": HILL_TOP, "top_fill_mm": -1}, "top_fill_mm", "island_invalid", "0 to 4000"),
        *[
            ({name: {}}, name, "island_later_version", "later version")
            for name in LATER
            if name not in ("top", "top_fill_mm")
        ],
    ],
)  # fmt: skip
def test_every_refusal_names_its_path_and_code(change, where, code, words):
    raw = island()
    for name, value in change.items():
        if value is _DELETE:
            del raw[name]
        else:
            raw[name] = value
    refused = refusal(raw)
    assert (refused.path, refused.code) == (where, code), refused
    assert words in refused.detail


def test_a_document_that_is_not_an_object_is_refused():
    assert refusal(["isle"]).code == "island_invalid"


def test_the_volume_is_admitted_by_the_volume_reader_under_the_newest_catalog():
    for raw in (HIGH, SMALL):
        volume = made(raw)
        assert volume.id == raw["id"]
        # Made under the volume catalog its island catalog names, it reads the same under the
        # newest.
        assert volume.catalog_version == island_catalog().volume_catalog_version
        again = read_volume_document(volume.canonical(), volume_catalog(VOLUME_CATALOG_VERSION))
        assert again.sha256 == volume.sha256
        caps = [part for part in volume.parts if part.op == "cap"]
        assert [part.values["height_mm"] for part in caps] == [0]
        assert volume.erosion == read_island_document(raw).erosion
        assert volume.strata == read_island_document(raw).strata


@pytest.mark.parametrize("underside", UNDERSIDES)
def test_every_island_at_every_size_makes_a_volume_within_the_part_limit(underside):
    most = volume_catalog().values_of("volume")["parts"].maximum
    sizes = (
        {"radius_mm": 8000, "rim_mm": 2000, "depth_mm": 4000},
        {"radius_mm": 8000, "rim_mm": 4000, "depth_mm": 24000},
        {"radius_mm": 20000, "rim_mm": 9000, "depth_mm": 30000},
        {"radius_mm": 20000, "rim_mm": 20000, "depth_mm": 60000},
    )
    for size in sizes:
        for lobes in (1, 5):
            for index in range(6):
                raw = island(underside=underside, lobes=lobes, fingers=4, **size)
                volume = made(raw, index.to_bytes(2, "big"))
                assert len(volume.parts) <= most
                assert read_volume_document(volume.canonical()).sha256 == volume.sha256


def test_every_word_makes_a_volume_that_carries_it():
    bounds = island_catalog().values
    for name in ("look", "top_look", "walk"):
        for word in bounds[name].words:
            volume = made(island(**{name: word}))
            assert getattr(volume, name) == word


def test_the_same_island_and_seed_make_the_same_volume_and_another_seed_another():
    assert made(HIGH).sha256 == made(copy.deepcopy(HIGH)).sha256
    assert made(HIGH, b"other").sha256 != made(HIGH).sha256
    # Each part draws from its own stream: a finger more moves no other part.
    fewer, more = made({**SMALL, "fingers": 2}), made(SMALL)
    assert [part for part in more.parts if not part.id.startswith("finger_")][:-1] == [
        part for part in fewer.parts if not part.id.startswith("finger_")
    ][:-1]


def test_the_golden_islands_and_their_volumes_are_pinned():
    for raw in (HIGH, SMALL):
        read = read_island_document(raw)
        assert (read.sha256, make_island_volume(read, SEED).sha256) == GOLDEN[raw["id"]]


def _solid(field: VolumeField, z: int, half: int, cell: int = 1000) -> list[tuple[int, int]]:
    """Every point of a level grid at height ``z`` within ``half`` of the axis that is rock."""
    count = 2 * half // cell + 1
    values = field.grid((-half, -half, z), cell, (count, count, 1))
    return [
        (-half + cell * (index % count), -half + cell * (index // count))
        for index, value in enumerate(values)
        if value < 0
    ]


def _reach(points: list[tuple[int, int]]) -> int:
    return max((integer_sqrt(x * x + y * y) for x, y in points), default=0)


@pytest.mark.parametrize("raw", [HIGH, SMALL], ids=["high", "small"])
def test_the_top_is_level_at_0_and_centred_and_nothing_hangs_below_the_depth(raw):
    field = VolumeField(made(raw), SEED)
    radius, depth = raw["radius_mm"], raw["depth_mm"]
    weathering = field.weathering_mm
    assert field.extent[1][2] == 0
    middle = radius // 3
    count = 2 * middle // 1000 + 1
    assert all(value < 0 for value in field.grid((-middle, -middle, -1), 1000, (count, count, 1)))
    half = radius + weathering + 3000
    top = _solid(field, -1000, half)
    for axis in (0, 1):
        low, high = min(point[axis] for point in top), max(point[axis] for point in top)
        assert abs(low + high) // 2 <= weathering + 1000, (axis, low, high)
    assert _reach(top) <= radius + weathering + 1000
    assert _solid(field, -depth - weathering - 1000, half) == []


@pytest.mark.parametrize("underside", UNDERSIDES)
@pytest.mark.parametrize("seed", [b"a", b"b"])
def test_the_underside_narrows_below_the_slab(underside, seed):
    """Unweathered, so what is measured is the parts: the rock's reach from the island's axis at
    each of five heights below the slab is never more than a cell and a half wider than above."""
    raw = island(radius_mm=20000, rim_mm=8000, depth_mm=40000, underside=underside, fingers=4)
    field = VolumeField(made(raw, seed), seed)
    rim, depth = raw["rim_mm"], raw["depth_mm"]
    reaches = [
        _reach(_solid(field, -rim - step * (depth - rim) // 6, raw["radius_mm"] + 2000))
        for step in range(1, 6)
    ]
    assert reaches[0] > 0
    for above, below in itertools.pairwise(reaches):
        assert below <= above + 1500, reaches


def test_the_narrowing_measure_sees_a_pot():
    """The control for the test above: a ball hung below the slab, wider than the keel round it,
    is measured widening downward."""
    raw = island(radius_mm=20000, rim_mm=8000, depth_mm=40000)
    canonical = made(raw, b"a").canonical()
    pot = {"id": "pot", "shape": "sphere", "at_mm": [0, 0, -30000], "radius_mm": 14000}
    canonical["parts"].insert(-1, pot)
    field = VolumeField(read_volume_document(canonical), b"a")
    reaches = [_reach(_solid(field, -8000 - step * 32000 // 6, 22000)) for step in (2, 4)]
    assert reaches[1] > reaches[0] + 1500, reaches


def _area(field: VolumeField, z: int, half: int = 14000, cell: int = 250) -> int:
    count = 2 * half // cell + 1
    return sum(1 for value in field.grid((-half, -half, z), cell, (count, count, 1)) if value < 0)


@pytest.mark.parametrize("seed", [b"preview", b"golden", b"a", b"b", b"c", b"d"])
def test_a_small_cone_ends_in_its_toe_without_a_knob(seed):
    """The parts alone (weathering set to none): over the lowest 10 m of rock, taken half a metre
    above the lowest rock and every metre above it, the cross-section never grows by more than 2 %
    from one level to the level a metre below, so the toe lies inside the keel's foot and nothing
    narrows into a neck above a wider end. A toe whose corners and offset reached past the keel's
    foot grew 3.6 % here on the small island under the seed b"preview", and drew a knob; the toe
    held inside the foot grows at most 0.7 % over these seeds."""
    bare = {"amplitude_mm": 0}
    raw = {**SMALL, "fingers": 0, "erosion": bare, "strata": bare}
    field = VolumeField(made(raw, seed), seed)
    low = field.extent[0][2]
    while _area(field, low) == 0:
        low += 100
    areas = [_area(field, low + 500 + 1000 * step) for step in range(11)]
    for lower, upper in itertools.pairwise(areas):
        assert lower * 1000 <= 1020 * upper, areas


def test_a_cone_hangs_its_keel_to_the_stated_depth():
    raw = island(radius_mm=12000, rim_mm=6000, depth_mm=36000)
    field = VolumeField(made(raw), SEED)
    assert _solid(field, -36000 + 1500, 14000)
    assert not _solid(field, -36000 - 1000, 14000)


def test_the_first_catalog_states_no_top_land_and_reads_every_other_value_as_the_second():
    with pytest.raises(IslandRefused) as caught:
        read_island_document({**HIGH, "top": HILL_TOP}, island_catalog(1))
    assert (caught.value.path, caught.value.code) == ("top", "island_later_version")
    first = read_island_document(HIGH, island_catalog(1))
    assert first.canonical_bytes == read_island_document(HIGH).canonical_bytes
    assert make_island_volume(first, SEED).sha256 == made(HIGH).sha256


def test_a_top_land_is_written_in_and_made_the_volumes_top_land_over_the_square_round_its_top():
    read = read_island_document({**HIGH, "top": HILL_TOP})
    assert read.top is not None
    assert read.canonical()["top"] == read_land_document(HILL_TOP).canonical()
    assert read_island_document(read.canonical()).canonical_bytes == read.canonical_bytes
    volume = make_island_volume(read, SEED)
    assert volume.top_land is not None
    assert volume.top_land.land.canonical() == read.top.canonical()
    assert [part for part in volume.parts if part.op == "cap"] == []
    # The square is whole 2 m and covers the level island's top: all the rock a metre under it.
    side = volume.top_land.side_mm
    level = VolumeField(made(HIGH), SEED)
    under = _solid(level, -1000, HIGH["radius_mm"] + level.weathering_mm + 3000)
    assert side % 2000 == 0 and max(max(abs(x), abs(y)) for x, y in under) <= side // 2
    assert read_volume_document(volume.canonical()).sha256 == volume.sha256


@pytest.mark.parametrize("top", [HILL_TOP, HOLLOW_TOP], ids=["hill", "hollow"])
def test_the_slab_reaches_above_the_lands_highest_point_and_its_base_below_the_lowest(top):
    raw = {**HIGH, "top": top}
    volume = made(raw)
    assert volume.top_land is not None
    surface = TopLandSurface(volume.top_land, volume.id)
    # The hill rises above the top height and the hollow falls below it.
    assert surface.highest > 1500 if top is HILL_TOP else surface.lowest < -1500
    (slab,) = [part for part in volume.parts if part.id == "slab"]
    base = slab.values["at_mm"][2]
    assert base <= surface.lowest - raw["rim_mm"]
    weathering = raw["erosion"]["amplitude_mm"] + raw["strata"]["amplitude_mm"]
    assert base + slab.values["height_mm"] > surface.highest + weathering
    # The rock reaches no higher than the land's highest point and no deeper than the stated
    # depth below its lowest.
    field = VolumeField(volume, SEED)
    assert field.extent[1][2] == surface.highest
    half = raw["radius_mm"] + field.weathering_mm + 3000
    assert _solid(field, surface.lowest - raw["depth_mm"] - field.weathering_mm - 1000, half) == []


def test_the_walked_top_is_the_land_never_above_it_and_within_a_quarter_of_its_blend_below():
    raw = {**HIGH, "top": HILL_TOP}
    volume = made(raw)
    assert volume.top_land is not None
    surface = TopLandSurface(volume.top_land, volume.id)
    field = VolumeField(volume, SEED)
    near = raw["radius_mm"] // 2
    corners: dict[tuple[int, int], int] = {}
    for sheet in volume_tops(field):
        x0, y0 = sheet.origin_mm
        for row, first, last in sheet.walkable:
            for column in range(first, last + 1):
                for dj in (0, 1):
                    for di in (0, 1):
                        x = x0 + (column + di) * SHEET_CELL_MM
                        y = y0 + (row + dj) * SHEET_CELL_MM
                        if abs(x) <= near and abs(y) <= near:
                            index = (row + dj) * sheet.columns + column + di
                            corners[(x, y)] = sheet.height_mm[index]
    # The middle of the top is walked: nearly every corner within half the radius of the axis.
    assert len(corners) >= (2 * near // SHEET_CELL_MM) ** 2 * 9 // 10
    quarter = volume.top_land.blend_mm // 4
    for (x, y), top in corners.items():
        land = surface.height(x, y)
        assert land - quarter - 1 <= top <= land, (x, y, top, land)
    # It climbs the hill as the land does: not a level top.
    lands = [surface.height(x, y) for x, y in corners]
    heights = corners.values()
    assert max(lands) - min(lands) > 500
    assert max(heights) - min(heights) >= max(lands) - min(lands) - quarter


#: Each island with a top, read against a catalog version, and the identities of the island and
#: of the volume it makes under SEED: version 2's held as version 3 came.
GOLDEN_TOPS = {
    ("high_island", 2): (
        "63c6e76dd2a3fe5421e75230a487dae81fe03b9227f907a2324f8838d1631d31",
        "ba1c5fde581feb9767ef063471ed1dd7c2de0e3ad4df807bb4ac0e949520ec0a",
    ),
    ("high_island", 3): (
        "da91915e210a29a60cec0b523cfe91b0e1fb3ef0cdc1793cc38adf390ffd6026",
        "284774e60806bb3910a094468d8dd54cb3f5a8e278c4414b2a74b4cb5f605325",
    ),
    ("small_island", 2): (
        "458a81aade2cb70887f09f946d7e5fc8ed7fdb5cd4ee49f78a0ef4cc816c5ccf",
        "a61cd54031f3cd200e698e6c12fbfd8a05d7c1725f94bb00be383b5d5f2fc56e",
    ),
    ("small_island", 3): (
        "932847635faf037292dcebc27ca3e97d7dda3dafed7ecbbb5b6246b3f0a1f6ce",
        "0c26d4350d5d1310349e64285e15bf9ac9a24e8686c03294727ea39b00a70247",
    ),
}
WITH_TOPS = {"high_island": {**HIGH, "top": HILL_TOP}, "small_island": {**SMALL, "top": HOLLOW_TOP}}


@pytest.mark.parametrize("key", sorted(GOLDEN_TOPS))
def test_the_golden_islands_with_a_top_and_their_volumes_are_pinned_at_each_catalog(key):
    name, version = key
    read = read_island_document(WITH_TOPS[name], island_catalog(version))
    assert (read.sha256, make_island_volume(read, SEED).sha256) == GOLDEN_TOPS[key]


def test_the_third_catalog_writes_in_a_fill_with_a_top_only():
    raw = WITH_TOPS["high_island"]
    read = read_island_document(raw)
    assert (read.catalog_version, read.top_fill_mm, read.canonical()["top_fill_mm"]) == (
        3,
        4000,
        4000,
    )
    assert read_island_document(read.canonical()).canonical_bytes == read.canonical_bytes
    level = read_island_document(HIGH)
    assert "top_fill_mm" not in level.canonical() and level.top_fill_mm == 0
    assert level.canonical_bytes == read_island_document(HIGH, island_catalog(2)).canonical_bytes
    assert made(HIGH).sha256 == GOLDEN["high_island"][1]
    with pytest.raises(IslandRefused) as caught:
        read_island_document({**raw, "top_fill_mm": 0}, island_catalog(2))
    assert (caught.value.path, caught.value.code) == ("top_fill_mm", "island_later_version")


def _filled(volume: VolumeDocument, fill: int, inner: int) -> tuple[TopHeights, dict]:
    """The volume's natural top with ``fill`` added at every lattice point within ``inner`` of its
    axis, as a site's grading fills a pad, and those points' filled heights."""
    assert volume.top_land is not None
    near = realize_top_land(volume.top_land, volume.id)
    half = volume.top_land.side_mm // 2
    heights, filled = [], {}
    for j in range(near.ny):
        for i in range(near.nx):
            x, y = i * TOP_LAND_CELL_MM - half, j * TOP_LAND_CELL_MM - half
            height = near.heights[j * near.nx + i]
            if abs(x) <= inner and abs(y) <= inner:
                height += fill
                filled[(x, y)] = height
            heights.append(height)
    return TopHeights(count=near.nx, heights=tuple(heights)), filled


def test_the_rock_reaches_a_full_fill_above_the_top_where_the_second_catalog_left_too_little():
    raw = WITH_TOPS["high_island"]
    third = made(raw)
    second = make_island_volume(read_island_document(raw, island_catalog(2)), SEED)
    given, filled = _filled(third, 4000, raw["radius_mm"] // 2)

    def reaching(volume: VolumeDocument) -> int:
        """How many filled points the rock reaches up to, capped by the filled heights."""
        field = VolumeField(volume, SEED, top=given)
        return sum(1 for (x, y), height in filled.items() if field.distance(x, y, height) <= 0)

    assert len(filled) > 400
    assert reaching(third) == len(filled)
    # The control: version 2's rock, weathered, falls short under a full fill at many points.
    assert reaching(second) < len(filled) * 9 // 10
    (slab,) = [part for part in third.parts if part.id == "slab"]
    surface = TopLandSurface(third.top_land, third.id)  # type: ignore[arg-type]
    weathering = raw["erosion"]["amplitude_mm"] + raw["strata"]["amplitude_mm"]
    top = slab.values["at_mm"][2] + slab.values["height_mm"]
    assert top > surface.highest + 4000 + weathering


def _rock_under_top(volume: VolumeDocument, half: int) -> int:
    """How many points of the 1 m lattice over a square ``half`` each way have rock a metre under
    the volume's top (its land, or level 0 where it states none)."""
    field = VolumeField(volume, SEED)
    surface = None if volume.top_land is None else TopLandSurface(volume.top_land, volume.id)
    return sum(
        1
        for y in range(-half, half + 1, 1000)
        for x in range(-half, half + 1, 1000)
        if field.distance(x, y, (0 if surface is None else surface.height(x, y)) - 1000) <= 0
    )


def test_the_third_catalogs_raised_top_keeps_the_outline_the_island_states():
    raw = WITH_TOPS["high_island"]
    third = made(raw)
    assert third.top_land is not None
    half = third.top_land.side_mm // 2
    level = _rock_under_top(made(HIGH), half)
    second = _rock_under_top(
        make_island_volume(read_island_document(raw, island_catalog(2)), SEED), half
    )
    kept = _rock_under_top(third, half)
    # Raised 4 m further for a fill, the slab still holds the level island's top a metre under
    # the land; version 2's, raised by the land's relief alone, leans less and holds less.
    assert kept * 100 >= level * 98
    assert kept > second
