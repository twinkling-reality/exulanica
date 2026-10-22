"""The volume field is one pure integer function of a document and a seed: its turns, noise and
golden values pinned under every served rules version, the same in a child interpreter, the same on
a grid as point by point, and culled without changing any value near a surface or any sign; its
beds vary as their strata say and never past the amplitude."""

from __future__ import annotations

import hashlib
import itertools
import math
import os
import subprocess
import sys
from decimal import Decimal, getcontext
from pathlib import Path

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.volumes import (
    EXACT_MM,
    PROFILE,
    SERVED_VOLUME_RULES,
    TURN_ONE,
    Noise3,
    VolumeField,
    VolumeRefused,
    read_volume_document,
    sin_cos,
    turn_matrix,
    volume_catalog,
)
from exulanica.grammar.volumes.turns import PI_SCALED

from test_volume_document import STACK

ROOT = Path(__file__).resolve().parents[1]
SEED = hashlib.sha256(b"exulanica volume field test").digest()

#: Fixed points of the stack: the open sea arch, deep inside, beside it, on its capped top, above
#: it, and under the overhang.
POINTS = [
    (0, 0, 0),
    (0, 0, 20000),
    (20000, 0, 20000),
    (0, 0, 41000),
    (0, 0, 60000),
    (0, 0, 500),
    (14500, 0, 38000),
    (-15000, 7000, 14000),
]
#: The golden field under each served volume rules version (:func:`golden_field`): the stack's
#: values at the points, and the digest of its values on a 2 m grid through it. A change that moves
#: one is a new version.
GOLDEN = {
    1: {
        "points": [3482, -14725, 5300, 0, 19000, 2616, -727, 2816],
        "grid": "8e0bd0eb6f3f87d3f164402319c12031f4d5ebed7bb8aeddc5883d19245ece95",
    },
    2: {
        "points": [3734, -15233, 5447, 0, 19000, 2955, -909, 2641],
        "grid": "2b052a791c9bc43930312da772dd0e565efdff5d28ac0bafb2cc28f90a93e63e",
    },
    3: {
        "points": [3734, -15233, 5447, 898, 19898, 2955, -1, 2641],
        "grid": "98e9aa48cbcde417924f9ae7a745190a513ceb0c8c1c951d931c76871db10fc2",
    },
}
#: Version 4 is version 3's rock: only the land rules its top land is graded by differ.
GOLDEN[4] = GOLDEN[3]
#: Beds varied every way version 2 states: thickness, relief, a side and a lean.
VARIED_STRATA = {
    "amplitude_mm": 900,
    "period_mm": 4500,
    "spread_mm": 2500,
    "relief_permille": 600,
    "offset_permille": 700,
    "tilt_mdeg": 3000,
    "toward_mdeg": 120000,
}
GRID = ((-24000, -24000, -10000), 2000, (25, 25, 28))
#: A top land for the stack under version 3: a rough hill and a roll over a 40 m square, its ground
#: below the stack's cap, so the stack's top follows the land.
TOP_LAND = {
    "land": {
        "profile": "exulanica.landform/v1",
        "ground_mm": 38000,
        "features": [
            {"id": "hill", "kind": "rise", "side": "centre", "width_mm": 24000,
             "depth_mm": 20000, "height_mm": 2500},
            {"id": "roll", "kind": "undulation", "amplitude_mm": 600, "wavelength_mm": 9000},
        ],
    },
    "side_mm": 40000,
    "blend_mm": 600,
}  # fmt: skip

#: Broad blends, a deep tilt and two caps: what the culling margin has to cover.
BROAD = {
    "profile": PROFILE,
    "id": "broad",
    "erosion": {"amplitude_mm": 8000, "wavelength_mm": 9000, "octaves": 4},
    "strata": {"amplitude_mm": 2000, "period_mm": 5000},
    "parts": [
        {"id": "core", "shape": "box", "size_mm": [30000, 20000, 30000], "round_mm": 4000},
        {"id": "lobe", "shape": "sphere", "at_mm": [22000, 0, 18000], "radius_mm": 8000,
         "blend_mm": 30000},
        {"id": "horn", "shape": "column", "at_mm": [-12000, 4000, 20000], "height_mm": 30000,
         "base_radius_mm": 6000, "top_radius_mm": 1000, "round_mm": 500, "blend_mm": 12000,
         "tilt_mdeg": 60000, "toward_mdeg": 300000, "yaw_mdeg": 45000},
        {"id": "bore", "shape": "sphere", "op": "carve", "at_mm": [0, -9000, 12000],
         "radius_mm": 7000, "blend_mm": 9000},
        {"id": "gate", "shape": "arch", "at_mm": [5000, 0, 0], "width_mm": 6000, "spring_mm": 3000,
         "depth_mm": 26000, "blend_mm": 2000},
        {"id": "high", "shape": "cap", "height_mm": 36000, "blend_mm": 3000},
        {"id": "low", "shape": "cap", "height_mm": 33000, "blend_mm": 6000},
    ],
}  # fmt: skip


def stack_field(*, whole: bool = False) -> VolumeField:
    return VolumeField(read_volume_document(STACK), SEED, whole=whole)


def golden_field(version: int) -> VolumeField:
    """The stack under rules ``version``: as stated under version 1, its beds varied under 2, and
    its top a land from 3."""
    raw = STACK if version == 1 else {**STACK, "strata": VARIED_STRATA}
    if version >= 3:
        raw = {**raw, "top_land": TOP_LAND}
    document = read_volume_document(raw, volume_catalog(SERVED_VOLUME_RULES[version]))
    return VolumeField(document, SEED, rules=version)


def test_pi_is_the_floor_of_pi_at_two_to_the_sixty_second():
    getcontext().prec = 60
    pi = Decimal("3.14159265358979323846264338327950288419716939937510582097494459")
    assert int(pi * (1 << 62)) == PI_SCALED


def test_sine_and_cosine_are_pinned_exact_at_the_quarters_and_hold_their_symmetries():
    assert sin_cos(0) == (0, TURN_ONE)
    assert sin_cos(90_000) == (TURN_ONE, 0)
    assert sin_cos(180_000) == (0, -TURN_ONE)
    assert sin_cos(-90_000) == sin_cos(270_000) == (-TURN_ONE, 0)
    assert sin_cos(30_000) == (536_870_912, 929_887_697)
    assert sin_cos(45_000) == (759_250_125, 759_250_125)
    for mdeg in (1, 7_500, 30_000, 44_999, 61_234, 123_456, 359_999):
        sine, cosine = sin_cos(mdeg)
        radians = math.radians(mdeg / 1000)
        assert abs(sine - math.sin(radians) * TURN_ONE) <= 1, mdeg
        assert abs(cosine - math.cos(radians) * TURN_ONE) <= 1, mdeg
        assert sin_cos(mdeg + 90_000) == (cosine, -sine), mdeg
        assert sin_cos(-mdeg) == (-sine, cosine), mdeg


def test_a_part_turns_counterclockwise_and_leans_toward_its_bearing():
    assert turn_matrix(0, 0, 123_000) is None
    turn = turn_matrix(90_000, 0, 0)
    assert turn is not None
    east = tuple(turn[row][0] for row in range(3))
    assert east == (0, TURN_ONE, 0)  # east turns to north
    lean = turn_matrix(0, 30_000, 90_000)
    assert lean is not None
    up = tuple(lean[row][2] for row in range(3))
    sine, cosine = sin_cos(30_000)
    assert abs(up[0] - sine) <= 1 and up[1] == 0 and abs(up[2] - cosine) <= 1  # leans east


def test_noise_is_bounded_pinned_and_the_same_on_axes_as_at_a_point():
    plain = Noise3(b"noise", 10_000, 3, ridged=False)
    ridged = Noise3(b"noise", 10_000, 3, ridged=True)
    coordinates = range(-30_000, 30_000, 2_917)
    xs, ys, zs = plain.axis(coordinates), plain.axis(coordinates), plain.axis(coordinates)
    for noise in (plain, ridged):
        axis = noise.axis(coordinates)
        for i, x in enumerate(coordinates):
            for j, y in enumerate(coordinates):
                value = noise.sample(axis[i], axis[j], axis[(i + j) % len(axis)])
                assert -32_768 <= value <= 32_768
                assert value == noise.point(x, y, coordinates[(i + j) % len(axis)])
    assert [plain.sample(xs[i], ys[i], zs[-1 - i]) for i in range(4)] == [6679, -6452, -3212, 8951]
    assert [ridged.point(1_000 * i, -700 * i, 333 * i) for i in range(4)] == [
        -514,
        -884,
        -2598,
        -6096,
    ]


def test_each_shape_puts_its_surface_where_its_values_say():
    def field(*parts: dict) -> VolumeField:
        raw = {"profile": PROFILE, "id": "probe", "parts": list(parts)}
        return VolumeField(read_volume_document(raw), SEED)

    ball = field({"id": "ball", "shape": "sphere", "at_mm": [0, 0, 5000], "radius_mm": 4000})
    assert ball.distance(0, 0, 5000) == -4000
    assert ball.distance(4000, 0, 5000) == 0
    assert ball.distance(0, 0, 12000) == 3000
    slab = field({"id": "slab", "shape": "box", "size_mm": [10000, 6000, 3000]})
    assert slab.distance(0, 0, 3000) == 0 and slab.distance(5000, 0, 1500) == 0
    assert slab.distance(0, 0, 1500) == -1500 and slab.distance(8000, 7000, 1500) == 5000
    stack = field(
        {"id": "stack", "shape": "column", "height_mm": 20000, "base_radius_mm": 4000,
         "top_radius_mm": 9000}
    )  # fmt: skip
    assert stack.distance(4000, 0, 0) == 0 and stack.distance(9000, 0, 20000) == 0
    assert stack.distance(7000, 0, 1000) > 0 and stack.distance(7000, 0, 19000) < 0  # overhangs
    limb = field(
        {"id": "limb", "shape": "capsule", "to_mm": [10000, 0, 0], "radius_mm": 2000,
         "to_radius_mm": 0}
    )  # fmt: skip
    assert limb.distance(0, 2000, 0) == 0 and limb.distance(10000, 0, 0) == 0
    assert limb.distance(5000, 0, 1000) == 0
    gate = field(
        {"id": "mass", "shape": "box", "size_mm": [20000, 8000, 12000]},
        {"id": "gate", "shape": "arch", "width_mm": 4000, "spring_mm": 3000, "depth_mm": 20000},
    )
    assert gate.distance(0, 0, 1000) > 0 and gate.distance(0, 0, 4900) > 0  # open to the head
    assert gate.distance(0, 0, 5100) < 0 and gate.distance(3000, 0, 1000) < 0
    assert gate.distance(2000, 0, 1000) == 0
    capped = field(
        {"id": "ball", "shape": "sphere", "at_mm": [0, 0, 5000], "radius_mm": 4000},
        {"id": "level", "shape": "cap", "height_mm": 6000},
    )
    assert capped.distance(0, 0, 6000) == 0 and capped.distance(1000, 500, 6000) == 0


def test_the_golden_field_is_pinned_for_every_served_rules_version():
    assert set(GOLDEN) == set(SERVED_VOLUME_RULES)
    for version, golden in GOLDEN.items():
        field = golden_field(version)
        assert field.rules == version
        assert [field.distance(*point) for point in POINTS] == golden["points"], version
        assert sha256_of_canonical(field.grid(*GRID)).hex() == golden["grid"], version
    # Beds stated plainly under the newest rules are version 1's rock.
    assert sha256_of_canonical(stack_field().grid(*GRID)).hex() == GOLDEN[1]["grid"]


def test_a_field_is_evaluated_by_the_rules_that_read_its_catalog():
    older = read_volume_document(STACK, volume_catalog(1))
    assert VolumeField(older, SEED).rules == 1
    assert stack_field().rules == max(SERVED_VOLUME_RULES)
    with pytest.raises(VolumeRefused) as caught:
        VolumeField(older, SEED, rules=2)
    assert caught.value.code == "volume_rules_changed"


@pytest.mark.parametrize("varied", [False, True], ids=["plain", "varied"])
def test_a_grid_is_the_field_point_by_point(varied):
    field = golden_field(2) if varied else stack_field()
    (x0, y0, z0), cell, (nx, ny, nz) = (-20000, -13000, 30000), 1500, (9, 7, 6)
    grid = field.grid((x0, y0, z0), cell, (nx, ny, nz))
    points = [
        field.distance(x0 + cell * i, y0 + cell * j, z0 + cell * k)
        for k in range(nz)
        for j in range(ny)
        for i in range(nx)
    ]
    assert grid == points


@pytest.mark.parametrize(
    ("raw", "origin", "counts"),
    [
        (STACK, (-30000, -26000, -12000), (36, 34, 34)),
        (BROAD, (-36000, -24000, -6000), (48, 29, 30)),
        (
            {**BROAD, "strata": {"amplitude_mm": 2000, "period_mm": 5000, "spread_mm": 4000,
                                 "relief_permille": 1000, "offset_permille": 1000,
                                 "tilt_mdeg": 15000, "toward_mdeg": 45000}},
            (-36000, -24000, -6000),
            (48, 29, 30),
        ),
    ],
    ids=["stack", "broad", "broad_varied"],
)  # fmt: skip
def test_culling_never_changes_a_value_near_a_surface_or_any_sign(raw, origin, counts):
    """On a 1.7 m grid through the whole mass and a margin around it: the grown bounds reach
    far beyond any surface, so a grid over them would only add samples no part reaches."""
    document = read_volume_document(raw)
    culled, whole = VolumeField(document, SEED), VolumeField(document, SEED, whole=True)
    fast, reference = culled.grid(origin, 1700, counts), whole.grid(origin, 1700, counts)
    near = [index for index, value in enumerate(reference) if abs(value) < EXACT_MM]
    assert len(near) > 1000  # the grid crosses the surface many times
    assert fast != reference  # and the culling skipped work somewhere, so this compares something
    assert all(fast[index] == reference[index] for index in near)
    assert all(
        abs(value) >= EXACT_MM
        for value, exact in zip(fast, reference, strict=True)
        if value != exact
    )
    assert all((value <= 0) == (exact <= 0) for value, exact in zip(fast, reference, strict=True))


def test_outside_its_bounds_a_volume_is_empty():
    field = stack_field()
    (lx, ly, lz), (hx, hy, hz) = field.bounds
    for x in (lx - 1, hx + 1):
        for y in (ly, (ly + hy) // 2, hy):
            for z in (lz, (lz + hz) // 2, hz):
                assert field.distance(x, y, z) > 0


_REPLAY = """
import hashlib, sys
import exulanica
from exulanica.canonical import sha256_of_canonical
sys.path.insert(0, sys.argv[1])
from test_volume_field import GRID, golden_field
field = golden_field(int(sys.argv[2]))
print(exulanica.__file__)
print(sha256_of_canonical(field.grid(*GRID)).hex())
"""


@pytest.mark.parametrize("version", sorted(SERVED_VOLUME_RULES))
@pytest.mark.parametrize("hash_seed", ["1", "4294967295"])
def test_the_field_replays_byte_for_byte_in_a_child_interpreter(hash_seed, version):
    result = subprocess.run(
        [sys.executable, "-c", _REPLAY, str(ROOT / "tests"), str(version)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module_path, digest = result.stdout.split()
    # A child that imported another checkout's package would measure the wrong code.
    assert Path(module_path).resolve().is_relative_to(ROOT), module_path
    assert digest == GOLDEN[version]["grid"]


#: A tall block with level faces, unweathered: on its east face the field is its beds alone.
FACE_X = 20000


def bedded(**strata: int) -> VolumeField:
    raw = {
        "profile": PROFILE,
        "id": "bedded",
        "strata": {"amplitude_mm": 1000, "period_mm": 4000, **strata},
        "parts": [
            {"id": "block", "shape": "box", "at_mm": [0, 0, -40000],
             "size_mm": [2 * FACE_X, 2 * FACE_X, 80000]},
        ],
    }  # fmt: skip
    return VolumeField(read_volume_document(raw), SEED)


def joins(field: VolumeField, x: int, y: int = 0) -> list[int]:
    """The heights on a face where a bed meets the next: where the beds cut back the furthest."""
    values = [field.distance(x, y, z) for z in range(-30000, 30000)]
    deepest = max(values)
    return [z - 30000 for z, value in enumerate(values) if value == deepest]


def test_varied_beds_alternate_thicker_and_thinner_and_none_is_under_a_metre():
    field = bedded(spread_mm=2500)
    heights = joins(field, FACE_X)
    beds = [high - low for low, high in itertools.pairwise(heights)]
    assert len(beds) >= 10
    assert all(1500 <= bed <= 6500 and bed != 4000 for bed in beds)
    assert all((first > 4000) != (second > 4000) for first, second in itertools.pairwise(beds))
    plain = joins(bedded(), FACE_X)
    assert {high - low for low, high in itertools.pairwise(plain)} == {4000}


def test_varied_beds_stand_out_unequally():
    values = [bedded(relief_permille=1000).distance(FACE_X, 0, z) for z in range(-30000, 30000, 50)]
    proudest = [min(values[start : start + 80]) for start in range(0, len(values), 80)]
    assert len(set(proudest)) > 5
    plain = [bedded().distance(FACE_X, 0, z) for z in range(-30000, 30000, 50)]
    assert {min(plain[start : start + 80]) for start in range(0, len(plain), 80)} == {-1000}


def test_beds_varied_every_way_never_pass_the_amplitude():
    field = bedded(spread_mm=3000, relief_permille=1000, offset_permille=1000, tilt_mdeg=15000,
                   toward_mdeg=30000)  # fmt: skip
    faces = [(FACE_X, 0), (-FACE_X, 0), (0, FACE_X), (0, -FACE_X)]
    values = [field.distance(x, y, z) for x, y in faces for z in range(-30000, 30000, 37)]
    assert min(values) == -1000 and max(values) == 1000


def test_offset_beds_stand_proud_on_one_side_and_recessed_on_the_other():
    field = bedded(offset_permille=1000)
    east = [field.distance(FACE_X, 0, z) for z in range(-30000, 30000, 250)]
    west = [field.distance(-FACE_X, 0, z) for z in range(-30000, 30000, 250)]
    differing = sum(1 for one, other in zip(east, west, strict=True) if one != other)
    assert differing > len(east) // 2
    assert all(-1000 <= value <= 1000 for value in east + west)


def test_tilted_beds_lean_toward_their_bearing():
    toward_east = bedded(tilt_mdeg=10000, toward_mdeg=90000)
    east, west = joins(toward_east, FACE_X), joins(toward_east, -FACE_X)
    sine, cosine = sin_cos(10000)
    drop = 2 * FACE_X * sine // cosine
    matched = [low for low in west if low - drop > -29000]
    assert len(matched) >= 10
    assert all(min(abs(low - drop - high) for high in east) <= 3 for low in matched)
    level = bedded()
    assert joins(level, FACE_X) == joins(level, -FACE_X)


def test_varied_beds_fade_to_plain_beds_toward_the_foot_of_the_volume():
    """A recessed bed never pinches a narrow foot: relief and offset fade out over the lowest
    quarter of the volume's height."""
    varied, plain = bedded(relief_permille=1000, offset_permille=1000), bedded()

    def departure(heights: range) -> int:
        return max(
            abs(varied.distance(FACE_X, 0, z) - plain.distance(FACE_X, 0, z)) for z in heights
        )

    foot, upper = departure(range(-40000, -38000, 20)), departure(range(0, 30000, 20))
    assert upper > 1000
    assert foot * 4 < upper
