"""The sea stack: a stack document read against its catalog and refused by path and code, made by
rule into a volume the volume reader admits, the same for the same stack and seed; its foot on the
sea floor, its top level, and little of its rock facing up just under the water."""

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
from exulanica.grammar.stacks import (
    CATALOG_VERSION,
    PROFILE,
    VOLUME_CATALOG_VERSION,
    SeaStackRefused,
    axis_point,
    load_sea_stack_catalog,
    make_sea_stack,
    read_sea_stack_document,
    sea_stack_catalog,
)
from exulanica.grammar.volumes import CATALOG_VERSION as NEWEST_VOLUME_CATALOG
from exulanica.grammar.volumes import (
    VolumeDocument,
    VolumeField,
    read_volume_document,
    realize_volume,
    volume_catalog,
)

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "stacks"

#: Every shipped sea stack catalog, byte for byte. A catalog changes by a new file
#: (``sea-stack-value.v2.json``), never by an edit, since a stack made under it names its values.
SHIPPED = {
    "sea-stack-value.v1.json": "090f431f23f9b380452b20a9f0f40fe7fe63d38c0ae688fd82ea3c5e19025716",
}

#: Beds varied every way, and ridged weathering: stacks with even beds read as rings, and stacks
#: with no beds as soft clay.
STRATA = {
    "amplitude_mm": 1000,
    "period_mm": 4500,
    "spread_mm": 2500,
    "relief_permille": 600,
    "offset_permille": 700,
    "tilt_mdeg": 3000,
    "toward_mdeg": 120000,
}
EROSION = {"amplitude_mm": 2500, "wavelength_mm": 14000, "octaves": 3, "ridged": "yes"}

#: The hand-made arch stack's sizes (trunk base radius 11 m, top 15 m, about 50 m from foot to
#: top, a shoulder and an arch), standing on an 18 m sea floor.
ARCH = {
    "profile": PROFILE, "id": "arch_stack", "height_mm": 41000, "foot_mm": 18000,
    "base_radius_mm": 11000, "top_radius_mm": 15000, "shoulders": 1,
    "arch": {"width_mm": 9000, "rise_mm": 3500, "floor_mm": 7000, "bearing_mdeg": 60000},
    "erosion": EROSION, "strata": STRATA,
}  # fmt: skip
#: A leaning, tapering stack with two shoulders and no passage.
PLAIN = {
    "profile": PROFILE, "id": "plain_stack", "height_mm": 48000, "foot_mm": 14000,
    "base_radius_mm": 12000, "top_radius_mm": 9500, "shoulders": 2,
    "lean": {"tilt_mdeg": 4000, "toward_mdeg": 200000}, "erosion": EROSION, "strata": STRATA,
}  # fmt: skip
#: The stacks' identities, with every default written in.
STACK_SHA256 = {
    "arch_stack": "b9dbb3fd66ffab272efcb1c770121d62129684d52c5b4064ad81b7aefa0c6914",
    "plain_stack": "13740593fa6c1174899b0b072162c1ad2933eb3364182f6ec9fcb1812cab5eda",
}
#: The volume each stack is made into under :data:`SEED`. A change to the maker that moves a part
#: moves these.
SEED = b"s3"
VOLUME_SHA256 = {
    "arch_stack": "5dd1564cf824bbef54bdc1b5ac50fa4fb0013ee21f8d00af0c3e4fb2c9229f98",
    "plain_stack": "3e869a7d6fd57f602010041ba4782338ede298400bef284f1c490bcdbe48c494",
}
#: sin(17 degrees) squared, per million: a face points up by more than 17 degrees where its
#: normal's up part squared is more than this share of its length squared.
UP_17_PER_MILLION = 85_479


def _made(raw: dict, seed: bytes = SEED) -> VolumeDocument:
    return make_sea_stack(read_sea_stack_document(raw), seed)


def _shallow_up_permille(volume: VolumeDocument, seed: bytes) -> int:
    """Of the surface realized at the 2 m cell whose triangles' centroids lie in the top 3 m below
    level 0, the share by area, per thousand, whose normals point up by more than 17 degrees."""
    up = total = 0
    for chunk in realize_volume(VolumeField(volume, seed), 2000):
        p, triangles = chunk.positions_mm, chunk.triangles
        for n in range(0, len(triangles), 3):
            a, b, c = (3 * triangles[n + corner] for corner in range(3))
            if not -9000 <= p[a + 2] + p[b + 2] + p[c + 2] < 0:
                continue
            ux, uy, uz = p[b] - p[a], p[b + 1] - p[a + 1], p[b + 2] - p[a + 2]
            vx, vy, vz = p[c] - p[a], p[c + 1] - p[a + 1], p[c + 2] - p[a + 2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            squared = nx * nx + ny * ny + nz * nz
            area = integer_sqrt(squared)
            total += area
            if nz > 0 and nz * nz * 1_000_000 > squared * UP_17_PER_MILLION:
                up += area
    assert total, "the stack has surface in the top 3 m of water"
    return up * 1000 // total


def test_the_shipped_catalog_is_pinned_and_reads():
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in CATALOGS.iterdir()
    }
    assert found == SHIPPED
    catalog = sea_stack_catalog()
    assert catalog.version == CATALOG_VERSION == 1
    assert sorted(catalog.values_of("arch")) == ["bearing_mdeg", "floor_mm", "rise_mm", "width_mm"]
    # A stack's volume is read against the newest volume catalog, whose strata vary the beds.
    assert VOLUME_CATALOG_VERSION == NEWEST_VOLUME_CATALOG


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entries: entries[0].update(owner="trunk", key="trunk_height_mm"), "unknown owner"),
        (lambda entries: entries[0].update(key="stack_tall_mm"), "keyed by its owner"),
        (lambda entries: entries.pop(4), "does not bound stack_shoulders"),
        (lambda entries: entries[5].update(words=["rock", "glass"]), "names glass"),
    ],
)
def test_a_catalog_breaking_its_rules_is_refused_at_loading(tmp_path, change, message):
    copied = tmp_path / "sea-stack-value.v1.json"
    shutil.copy(CATALOGS / "sea-stack-value.v1.json", copied)
    document = json.loads(copied.read_text())
    change(document["entries"])
    copied.write_text(json.dumps(document))
    with pytest.raises(CatalogError, match=message):
        load_sea_stack_catalog(tmp_path)


@pytest.mark.parametrize("raw", [ARCH, PLAIN], ids=["arch", "plain"])
def test_a_stack_is_read_with_its_defaults_written_in(raw):
    stack = read_sea_stack_document(raw)
    canonical = stack.canonical()
    assert stack.sha256 == hashlib.sha256(stack.canonical_bytes).hexdigest()
    assert stack.sha256 == STACK_SHA256[raw["id"]]
    assert (canonical["look"], canonical["top_look"], canonical["walk"]) == (
        "rock",
        "grass",
        "none",
    )
    # Its sections carry every value the volume catalog bounds, as a volume's do.
    bounds = volume_catalog(VOLUME_CATALOG_VERSION)
    assert set(canonical["strata"]) == set(bounds.values_of("strata"))
    assert set(canonical["erosion"]) == set(bounds.values_of("erosion"))
    # Read again from its canonical form, it is the same stack.
    assert read_sea_stack_document(canonical).sha256 == stack.sha256


def _with(raw: dict, path: tuple, value: object) -> dict:
    changed = copy.deepcopy(raw)
    target = changed
    for key in path[:-1]:
        target = target[key]
    if value is _ABSENT:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return changed


_ABSENT = object()


@pytest.mark.parametrize(
    ("path", "value", "where", "code"),
    [
        (("profile",), "exulanica.volume/v1", "profile", "stack_invalid"),
        (("id",), "Arch Stack", "id", "stack_invalid"),
        (("words",), "a stack", "", "stack_invalid"),
        (("height_mm",), _ABSENT, "height_mm", "stack_invalid"),
        (("height_mm",), 150001, "height_mm", "stack_invalid"),
        (("foot_mm",), 1999, "foot_mm", "stack_invalid"),
        (("base_radius_mm",), 11000.0, "base_radius_mm", "stack_invalid"),
        (("shoulders",), 5, "shoulders", "stack_invalid"),
        (("look",), "wall", "look", "stack_invalid"),
        (("top_look",), "snow", "top_look", "stack_invalid"),
        (("walk",), "top", "walk", "stack_invalid"),
        (("lean",), "none", "lean", "stack_invalid"),
        (("lean",), {"tilt_mdeg": 10001}, "lean.tilt_mdeg", "stack_invalid"),
        (("lean",), {"yaw_mdeg": 0}, "lean", "stack_invalid"),
        (("arch",), "yes", "arch", "stack_invalid"),
        (("arch", "width_mm"), _ABSENT, "arch.width_mm", "stack_invalid"),
        (("arch", "floor_mm"), 5999, "arch.floor_mm", "stack_invalid"),
        (("arch", "bearing_mdeg"), 180000, "arch.bearing_mdeg", "stack_invalid"),
        (("erosion", "amplitude_mm"), 8001, "erosion.amplitude_mm", "stack_invalid"),
        (("strata", "datum_mm"), 0, "strata", "stack_invalid"),
        (("strata", "spread_mm"), 3501, "strata.spread_mm", "stack_invalid"),
        (("top_radius_mm",), 22001, "top_radius_mm", "stack_invalid"),
        (("base_radius_mm",), 30000, "top_radius_mm", "stack_flank_faces_up"),
        (("arch", "width_mm"), 11800, "arch.width_mm", "stack_arch_too_wide"),
        (("arch", "rise_mm"), 32001, "arch.rise_mm", "stack_arch_too_high"),
        (("foot_mm",), 13499, "foot_mm", "stack_arch_below_foot"),
    ],
)
def test_a_stack_breaking_a_bound_or_a_rule_is_refused_by_path_and_code(path, value, where, code):
    with pytest.raises(SeaStackRefused) as refused:
        read_sea_stack_document(_with(ARCH, path, value))
    assert (refused.value.path, refused.value.code) == (where, code)


def test_a_passage_whose_round_head_outgrows_its_floor_and_rise_is_too_wide():
    wide = _with(_with(ARCH, ("base_radius_mm",), 20000), ("top_radius_mm",), 20000)
    wide["arch"] = {"width_mm": 16000, "rise_mm": 1500, "floor_mm": 6000}
    with pytest.raises(SeaStackRefused) as refused:
        read_sea_stack_document(wide)
    assert (refused.value.path, refused.value.code) == ("arch.width_mm", "stack_arch_too_wide")
    # The flank rule counts the lean: this taper alone passes, leaned 10 degrees it does not.
    tapered = _with(PLAIN, ("top_radius_mm",), 7000)
    read_sea_stack_document(_with(tapered, ("lean",), {}))
    with pytest.raises(SeaStackRefused) as refused:
        read_sea_stack_document(_with(tapered, ("lean",), {"tilt_mdeg": 10000}))
    assert (refused.value.path, refused.value.code) == ("top_radius_mm", "stack_flank_faces_up")


def test_anything_but_an_object_is_refused():
    with pytest.raises(SeaStackRefused) as refused:
        read_sea_stack_document([ARCH])
    assert (refused.value.path, refused.value.code) == ("", "stack_invalid")


def _corners() -> list[dict]:
    """Stacks at the corners of the catalog's bounds that its rules admit."""
    stacks = []
    for height, foot, base, top_share, shoulders, tilt, arched in itertools.product(
        (6000, 150000), (2000, 64000), (3000, 60000), (500, 1000, 2000), (0, 4), (0, 10000),
        (False, True),
    ):  # fmt: skip
        raw = {
            "profile": PROFILE, "id": "corner", "height_mm": height, "foot_mm": foot,
            "base_radius_mm": base, "top_radius_mm": max(2000, base * top_share // 1000),
            "shoulders": shoulders, "lean": {"tilt_mdeg": tilt, "toward_mdeg": 359999},
            "erosion": {"amplitude_mm": 8000}, "strata": STRATA,
        }  # fmt: skip
        if arched:
            raw["arch"] = {"width_mm": 3000, "rise_mm": 1500, "floor_mm": 6000}
        try:
            read_sea_stack_document(raw)
        except SeaStackRefused:
            continue
        stacks.append(raw)
    return stacks


def test_every_admitted_stack_makes_a_volume_the_newest_volume_catalog_admits():
    corners = _corners()
    assert len(corners) > 40
    for raw in [ARCH, PLAIN, *corners]:
        stack = read_sea_stack_document(raw)
        volume = make_sea_stack(stack, SEED)
        again = read_volume_document(volume.canonical())
        assert again.sha256 == volume.sha256
        assert again.catalog_version == NEWEST_VOLUME_CATALOG
        assert volume.id == stack.id
        assert len(volume.parts) <= volume_catalog().values_of("volume")["parts"].maximum
        assert (volume.look, volume.top_look, volume.walk) == (
            stack.look,
            stack.top_look,
            stack.walk,
        )
        assert dict(volume.erosion) == dict(stack.erosion)
        assert dict(volume.strata) == dict(stack.strata)


def test_the_same_stack_and_seed_make_the_same_volume():
    for raw in (ARCH, PLAIN):
        assert _made(raw).sha256 == _made(copy.deepcopy(raw)).sha256 == VOLUME_SHA256[raw["id"]]
        # The seed draws its shoulders, so another seed makes another volume.
        assert _made(raw, b"another").sha256 != VOLUME_SHA256[raw["id"]]
    # A stack without shoulders draws nothing.
    bare = _with(ARCH, ("shoulders",), 0)
    assert _made(bare).sha256 == _made(bare, b"another").sha256


@pytest.mark.parametrize("raw", [ARCH, PLAIN], ids=["arch", "plain"])
def test_its_foot_reaches_the_sea_floor_and_its_top_is_level(raw):
    stack = read_sea_stack_document(raw)
    field = VolumeField(make_sea_stack(stack, SEED), SEED)
    for above in (0, 1, 500):
        assert field.distance(*axis_point(stack, -stack.foot_mm + above)) <= 0
    # Level at its height on its axis and halfway out to its top's rim: solid at the height, air
    # a millimetre above it.
    x, y, z = axis_point(stack, stack.height_mm)
    for dx, dy in ((0, 0), (stack.top_radius_mm // 2, 0), (0, -stack.top_radius_mm // 2)):
        assert field.distance(x + dx, y + dy, z) <= 0 < field.distance(x + dx, y + dy, z + 1)
    assert field.extent[1][2] == stack.height_mm


@pytest.mark.parametrize("raw", [ARCH, PLAIN], ids=["arch", "plain"])
def test_little_of_its_rock_faces_up_just_under_the_water(raw):
    assert _shallow_up_permille(_made(raw), SEED) < 150
