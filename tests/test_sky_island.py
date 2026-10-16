"""The sky island: its catalog pinned, every value held to its bound and refused by path and code,
and the maker's volume admitted by the volume reader, the same for the same island and seed, and
shaped by its rules: level at 0, centred, no deeper than stated, narrowing below the slab."""

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
    LATER,
    PROFILE,
    IslandRefused,
    island_catalog,
    load_island_catalog,
    make_island_volume,
    read_island_document,
)
from exulanica.grammar.volumes import (
    CATALOG_VERSION as VOLUME_CATALOG_VERSION,
)
from exulanica.grammar.volumes import (
    VolumeField,
    read_volume_document,
    volume_catalog,
)

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "islands"

#: Every shipped sky-island catalog, byte for byte. A catalog changes by a new file, never by an
#: edit, since an island's defaults are written in from it.
SHIPPED = {
    "sky-island-value.v1.json": "2e9f3bf90d036aff61941d8c7fc16ef873781446c0a0d41bb0bb02aabf8d397d",
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
    catalog = island_catalog()
    assert (catalog.version, catalog.volume_catalog_version) == (1, 2)
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
        load_island_catalog(tmp_path)
    with pytest.raises(CatalogError, match="versions"):
        load_island_catalog(version=2)


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
    assert (read.catalog_version, read.volume_catalog_version) == (CATALOG_VERSION, 2)
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
        *[
            ({name: {}}, name, "island_later_version", "later version")
            for name in LATER
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
        assert volume.catalog_version == VOLUME_CATALOG_VERSION
        again = read_volume_document(volume.canonical())
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
