"""The skeleton fit on a model written here: a round torso, two short legs with feet, two arms, a
head and a tail, as ellipsoids and capsules whose proportions are not the plan's (the plan's legs
are long), so the fit is held to geometry this file states and not to any 3D model.

The positive control lays every chain in its limb and passes the rig's checks for a fitted
skeleton; the same model turned, scaled and moved gives the same skeleton; each refusal and each
fallback changes one thing about it. The inside is held to a hollow shell with an opening, the
shape a model made from a picture can come back as.
"""

from __future__ import annotations

import numpy as np
import pytest

from exulanica_appearance.creatures.embed import (
    EmbedRefused,
    EmbedSettings,
    curve_skeleton,
    embed,
    solid_inside,
)
from exulanica_appearance.creatures.geometry import voxel_surface
from exulanica_appearance.creatures.rig import bone_heat, check_rig

#: The model as shapes, metres; x across (left is -x), y forward, z up. Each is an ellipsoid
#: (centre, radii) or a capsule (one end, the other, radius).
ELLIPSOIDS = {
    "torso": ((0.0, 0.0, 0.42), (0.20, 0.25, 0.25)),
    "head": ((0.0, 0.04, 0.78), (0.12, 0.12, 0.12)),
}
CAPSULES = {
    "legLeft": ((-0.10, 0.0, 0.25), (-0.10, 0.02, 0.03), 0.035),
    "footLeft": ((-0.10, 0.0, 0.025), (-0.10, 0.14, 0.025), 0.025),
    "legRight": ((0.10, 0.0, 0.25), (0.10, 0.02, 0.03), 0.035),
    "footRight": ((0.10, 0.0, 0.025), (0.10, 0.14, 0.025), 0.025),
    "armLeft": ((-0.15, 0.0, 0.52), (-0.38, 0.0, 0.50), 0.035),
    "armRight": ((0.15, 0.0, 0.52), (0.38, 0.0, 0.50), 0.035),
    "tail": ((0.0, -0.20, 0.40), (0.0, -0.46, 0.45), 0.03),
}
#: The plan: each bone's parent, joint and end (metres), as a drafted upright body states them.
BONES = {
    "hips": (None, (0.0, 0.0, 0.42), (0.0, 0.0, 0.52)),
    "spine1": ("hips", (0.0, 0.0, 0.52), (0.0, 0.0, 0.62)),
    "spine2": ("spine1", (0.0, 0.0, 0.62), (0.0, 0.0, 0.72)),
    "head1": ("spine2", (0.0, 0.0, 0.72), (0.0, 0.06, 0.90)),
    "tail1": ("hips", (0.0, -0.05, 0.42), (0.0, -0.40, 0.30)),
    "leg1Left1": ("hips", (-0.09, 0.0, 0.42), (-0.09, 0.01, 0.25)),
    "leg1Left2": ("leg1Left1", (-0.09, 0.01, 0.25), (-0.10, 0.0, 0.08)),
    "leg1Left3": ("leg1Left2", (-0.10, 0.0, 0.08), (-0.10, 0.12, 0.0)),
    "leg1Right1": ("hips", (0.09, 0.0, 0.42), (0.09, 0.01, 0.25)),
    "leg1Right2": ("leg1Right1", (0.09, 0.01, 0.25), (0.10, 0.0, 0.08)),
    "leg1Right3": ("leg1Right2", (0.10, 0.0, 0.08), (0.10, 0.12, 0.0)),
    "arm1Left1": ("spine2", (-0.13, 0.0, 0.66), (-0.27, 0.0, 0.66)),
    "arm1Left2": ("arm1Left1", (-0.27, 0.0, 0.66), (-0.40, 0.0, 0.66)),
    "arm1Right1": ("spine2", (0.13, 0.0, 0.66), (0.27, 0.0, 0.66)),
    "arm1Right2": ("arm1Right1", (0.27, 0.0, 0.66), (0.40, 0.0, 0.66)),
}
CHAINS = [
    {"key": "spine", "role": "spine", "side": "centre", "order": 0, "bones": ["spine1", "spine2"]},
    {"key": "tail", "role": "tail", "side": "centre", "order": 0, "bones": ["tail1"]},
    *(
        {
            "key": f"leg1{side}",
            "role": "leg",
            "side": side.lower(),
            "order": 0,
            "bones": [f"leg1{side}1", f"leg1{side}2", f"leg1{side}3"],
        }
        for side in ("Left", "Right")
    ),
    *(
        {
            "key": f"arm1{side}",
            "role": "arm",
            "side": side.lower(),
            "order": 0,
            "bones": [f"arm1{side}1", f"arm1{side}2"],
        }
        for side in ("Left", "Right")
    ),
]
NAMES = tuple(BONES)
PARENTS = {bone: spec[0] for bone, spec in BONES.items()}
JOINTS = {bone: np.array(spec[1]) for bone, spec in BONES.items()}
ENDS = {bone: np.array(spec[2]) for bone, spec in BONES.items()}
HEIGHT = 0.90
#: A coarser grid than a job's keeps the tests quick; the limbs are four voxels across on it.
SETTINGS = EmbedSettings(grid=64)
SURFACE_VOXEL = 0.01


def _box(low: tuple[float, ...], high: tuple[float, ...]) -> np.ndarray:
    (x0, y0, z0), (x1, y1, z1) = low, high
    v = np.array(
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    )  # fmt: skip
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]  # fmt: skip
    return v[np.array(faces)]


def _model(capsules=CAPSULES, ellipsoids=ELLIPSOIDS) -> tuple[np.ndarray, np.ndarray]:
    """The shapes' union as one closed surface: filled on a grid, then its boundary faces."""
    voxel = SURFACE_VOXEL
    origin = np.array([-0.5, -0.6, -0.05])
    shape = (100, 110, 100)
    centres = origin + (np.indices(shape).reshape(3, -1).T + 0.5) * voxel
    filled = np.zeros(len(centres), dtype=bool)
    for centre, radii in ellipsoids.values():
        filled |= (((centres - centre) / radii) ** 2).sum(axis=1) <= 1.0
    for start, end, radius in capsules.values():
        start, end = np.asarray(start), np.asarray(end)
        t = np.clip((centres - start) @ (end - start) / ((end - start) @ (end - start)), 0.0, 1.0)
        filled |= np.linalg.norm(centres - (start + t[:, None] * (end - start)), axis=1) <= radius
    return voxel_surface(filled.reshape(shape), origin, voxel)


def _embed(positions, faces):
    return embed(
        positions,
        faces,
        bones=NAMES,
        parents=PARENTS,
        chains=CHAINS,
        joints=JOINTS,
        ends=ENDS,
        height=HEIGHT,
        settings=SETTINGS,
    )


def _turned(points: np.ndarray, degrees: float) -> np.ndarray:
    angle = np.radians(degrees)
    cos, sin = np.cos(angle), np.sin(angle)
    return np.stack(
        [
            cos * points[:, 0] - sin * points[:, 1],
            sin * points[:, 0] + cos * points[:, 1],
            points[:, 2],
        ],
        axis=1,
    )


@pytest.fixture(scope="module")
def model():
    return _model()


@pytest.fixture(scope="module")
def fitted(model):
    return _embed(*model)


def _laid_in_its_own_limbs(fitted) -> None:
    assert all(index is not None for index in fitted.matched.values())
    assert fitted.still == ()
    inside = fitted.inside
    assert inside.holds(np.stack(list(fitted.joints.values()))).all()
    for side, sign in (("Left", -1), ("Right", 1)):
        # The plan's long leg is laid down the model's short one, from below the torso to the toe.
        hip, toe = fitted.joints[f"leg1{side}1"], fitted.ends[f"leg1{side}3"]
        assert hip[2] < 0.25 and np.sign(hip[0]) == sign
        assert toe[2] < 0.05 and toe[1] > 0.06 and np.sign(toe[0]) == sign
        # The arm starts where it leaves the torso and ends in its hand.
        shoulder, hand = fitted.joints[f"arm1{side}1"], fitted.ends[f"arm1{side}2"]
        assert abs(shoulder[0]) > 0.15 and 0.33 < abs(hand[0]) < 0.42
        assert 0.44 < hand[2] < 0.56
    assert fitted.ends["head1"][2] > 0.75
    assert fitted.ends["tail1"][1] < -0.30


def test_every_chain_is_laid_in_its_own_limb(fitted):
    _laid_in_its_own_limbs(fitted)


def test_the_fitted_skeleton_skins_and_passes_the_rig_checks(model, fitted):
    positions = fitted.place(model[0])
    assert np.allclose(positions, fitted.positions)
    indices, weights = bone_heat(
        positions, model[1], NAMES, fitted.joints, fitted.ends, fitted.inside
    )
    checks = check_rig(
        positions=positions,
        indices=indices,
        weights=weights,
        bones=NAMES,
        parents=PARENTS,
        plan_joints=JOINTS,
        joints=fitted.joints,
        ends=fitted.ends,
        chains=CHAINS,
        inside=fitted.inside,
        size=float(np.ptp(positions, axis=0).max()),
        fitted=True,
    )
    assert max(checks.leaked_share.values()) <= 0.03


def test_the_same_model_turned_scaled_and_moved_gives_the_same_skeleton(model, fitted):
    positions, faces = model
    moved = _turned(positions, 130.0) * 2.5 + np.array([3.0, -7.0, 1.0])
    again = _embed(moved, faces)
    _laid_in_its_own_limbs(again)
    # Each limb ends where it did: within four voxels of the grid the turned model falls on, as the
    # far point of a rounded end can move across it by up to its radius. A round head's far point
    # is anywhere on its crown, so it is held only to its crown above.
    for leaf in ("tail1", "leg1Left3", "leg1Right3", "arm1Left2", "arm1Right2"):
        assert np.linalg.norm(again.ends[leaf] - fitted.ends[leaf]) < 4 * again.inside.voxel, leaf


def test_a_model_with_a_leg_missing_is_refused_by_the_chain_it_lacks():
    lacking = {key: shape for key, shape in CAPSULES.items() if not key.endswith("Right")}
    lacking.update(armRight=CAPSULES["armRight"])
    with pytest.raises(EmbedRefused, match="rig_chain_not_found") as refused:
        _embed(*_model(lacking))
    assert refused.value.measures["missing"] == ["leg1Right"]


def test_arms_the_model_lacks_are_kept_inside_and_still():
    armless = {key: shape for key, shape in CAPSULES.items() if not key.startswith("arm")}
    fitted = _embed(*_model(armless))
    assert fitted.still == ("arm1Left1", "arm1Left2", "arm1Right1", "arm1Right2")
    assert fitted.matched["arm1Left2"] is None and fitted.matched["leg1Left3"] is not None
    for bone in fitted.still:
        joint, end = fitted.joints[bone], fitted.ends[bone]
        samples = joint + (end - joint) * (np.arange(9)[:, None] / 8)
        assert fitted.inside.holds(samples).all(), bone


def test_a_bump_is_not_a_limb(model):
    # A bump standing out three centimetres from a body ninety tall: less than its share.
    bumped = dict(ELLIPSOIDS, bump=((0.15, 0.12, 0.30), (0.03, 0.03, 0.03)))
    plain = curve_skeleton(model[0], model[1], SETTINGS)
    with_bump = curve_skeleton(*_model(CAPSULES, bumped), SETTINGS)
    # The bump adds no limb end: the same ends as without it, none of them on the bump.
    assert len(with_bump.leaves) == len(plain.leaves) >= 7
    assert not (np.linalg.norm(with_bump.tips[:, :2] - [0.18, 0.12], axis=1) < 0.05).any()


def _holed_square(z: float, size: float, hole: float) -> np.ndarray:
    """The square of half-side ``size`` at height ``z`` with a square hole of half-side ``hole``
    in its middle, as triangles."""
    o, i = size, hole
    quads = [
        ((-o, -o), (o, -o), (i, -i), (-i, -i)),
        ((o, -o), (o, o), (i, i), (i, -i)),
        ((o, o), (-o, o), (-i, i), (i, i)),
        ((-o, o), (-o, -o), (-i, -i), (-i, i)),
    ]
    triangles = []
    for a, b, c, d in quads:
        a3, b3, c3, d3 = ((x, y, z) for x, y in (a, b, c, d))
        triangles += [(a3, b3, c3), (a3, c3, d3)]
    return np.array(triangles, dtype=np.float64)


def test_a_hollow_shell_with_an_opening_is_filled_and_a_narrow_gap_is_not():
    # A box with thick walls and a hollow inside, open to the outside through a hole four
    # centimetres across in its roof, as a model made from a picture can come back.
    outer, inner, hole = 0.30, 0.25, 0.02
    # Each box without its top (its third and fourth triangles), where the holed roofs go.
    walls = np.delete(_box((-outer, -outer, 0.0), (outer, outer, 0.60)), [2, 3], axis=0)
    hollow = np.delete(_box((-inner, -inner, 0.05), (inner, inner, 0.55)), [2, 3], axis=0)
    tube = []
    corners = [(-hole, -hole), (hole, -hole), (hole, hole), (-hole, hole)]
    for k in range(4):
        (x0, y0), (x1, y1) = corners[k], corners[(k + 1) % 4]
        tube += [
            ((x0, y0, 0.55), (x1, y1, 0.55), (x1, y1, 0.60)),
            ((x0, y0, 0.55), (x1, y1, 0.60), (x0, y0, 0.60)),
        ]
    cup = np.concatenate(
        [
            walls,
            hollow,
            _holed_square(0.60, outer, hole),
            _holed_square(0.55, inner, hole),
            np.array(tube),
        ]
    )
    # Two boxes side by side with a gap of two voxels between them.
    voxel = 0.02
    pair = np.concatenate(
        [_box((0.8, -0.1, 0.0), (1.0, 0.1, 0.2)), _box((1.04, -0.1, 0.0), (1.24, 0.1, 0.2))]
    )
    grid, origin = solid_inside(np.concatenate([cup, pair]), voxel)

    def held(point):
        return bool(grid[tuple(np.floor((np.asarray(point) - origin) / voxel).astype(int))])

    assert held((0.0, 0.0, 0.30))
    assert held((0.2, 0.2, 0.10))
    assert not held((0.0, 0.0, 0.70))
    assert held((0.9, 0.0, 0.1)) and held((1.14, 0.0, 0.1))
    assert not held((1.02, 0.0, 0.1))
