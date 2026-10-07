"""The plan-guided rig on a body written here: boxes for a torso, four legs, a neck with a head and
a tail, and a skeleton through them, so the rig is held to geometry this file states and not to the
creature builder.

The positive control rigs that body and passes every check; each refusal changes one thing about
it. The heat equation's solver is held to a dense solve of the same system.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from exulanica_appearance.creatures.geometry import voxel_inside, voxel_surface
from exulanica_appearance.creatures.rig import (
    CHAIN_ROLES,
    LEAKED_SHARE,
    RigRefused,
    _laplacian,
    _solve,
    bone_heat,
    check_rig,
    fit_joints,
    inside_of,
)

#: Each box as (low corner, high corner), metres; x across (left is -x), y forward, z up.
BOXES = {
    "torso": ((-0.15, -0.40, 0.50), (0.15, 0.40, 0.80)),
    "leg1Left": ((-0.15, 0.25, 0.00), (-0.05, 0.35, 0.55)),
    "leg1Right": ((0.05, 0.25, 0.00), (0.15, 0.35, 0.55)),
    "leg2Left": ((-0.15, -0.35, 0.00), (-0.05, -0.25, 0.55)),
    "leg2Right": ((0.05, -0.35, 0.00), (0.15, -0.25, 0.55)),
    "neck": ((-0.06, 0.35, 0.75), (0.06, 0.50, 1.10)),
    "head": ((-0.07, 0.40, 1.00), (0.07, 0.68, 1.16)),
    "tail": ((-0.04, -0.72, 0.68), (0.04, -0.38, 0.76)),
}
#: Each bone: parent, joint, end and thickness at its joint.
BONES = {
    "hips": (None, (0.0, -0.35, 0.65), (0.0, -0.10, 0.65), 0.15),
    "spine1": ("hips", (0.0, -0.10, 0.65), (0.0, 0.15, 0.65), 0.15),
    "spine2": ("spine1", (0.0, 0.15, 0.65), (0.0, 0.38, 0.65), 0.15),
    "leg1Left1": ("spine2", (-0.10, 0.30, 0.55), (-0.10, 0.30, 0.28), 0.05),
    "leg1Left2": ("leg1Left1", (-0.10, 0.30, 0.28), (-0.10, 0.30, 0.03), 0.05),
    "leg1Right1": ("spine2", (0.10, 0.30, 0.55), (0.10, 0.30, 0.28), 0.05),
    "leg1Right2": ("leg1Right1", (0.10, 0.30, 0.28), (0.10, 0.30, 0.03), 0.05),
    "leg2Left1": ("hips", (-0.10, -0.30, 0.55), (-0.10, -0.30, 0.28), 0.05),
    "leg2Left2": ("leg2Left1", (-0.10, -0.30, 0.28), (-0.10, -0.30, 0.03), 0.05),
    "leg2Right1": ("hips", (0.10, -0.30, 0.55), (0.10, -0.30, 0.28), 0.05),
    "leg2Right2": ("leg2Right1", (0.10, -0.30, 0.28), (0.10, -0.30, 0.03), 0.05),
    "neck1": ("spine2", (0.0, 0.42, 0.76), (0.0, 0.45, 1.05), 0.06),
    "head1": ("neck1", (0.0, 0.45, 1.05), (0.0, 0.64, 1.08), 0.07),
    "tail1": ("hips", (0.0, -0.40, 0.72), (0.0, -0.55, 0.72), 0.04),
    "tail2": ("tail1", (0.0, -0.55, 0.72), (0.0, -0.70, 0.72), 0.04),
}
CHAINS = [
    {"key": "spine", "role": "spine", "bones": ["spine1", "spine2"]},
    {"key": "neck", "role": "neck", "bones": ["neck1"]},
    {"key": "tail", "role": "tail", "bones": ["tail1", "tail2"]},
    *(
        {
            "key": f"leg{pair}{side}",
            "role": "leg",
            "bones": [f"leg{pair}{side}1", f"leg{pair}{side}2"],
        }
        for pair in (1, 2)
        for side in ("Left", "Right")
    ),
]
NAMES = list(BONES)
PARENTS = {bone: spec[0] for bone, spec in BONES.items()}
JOINTS = {bone: np.array(spec[1]) for bone, spec in BONES.items()}
ENDS = {bone: np.array(spec[2]) for bone, spec in BONES.items()}
RADII = {bone: spec[3] for bone, spec in BONES.items()}
#: The body's largest extent: from the tail's tip to the nose.
SIZE = 0.72 + 0.68
VOXEL = 0.02


def _box(low: tuple[float, ...], high: tuple[float, ...]) -> np.ndarray:
    (x0, y0, z0), (x1, y1, z1) = low, high
    v = np.array(
        [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
         [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    )  # fmt: skip
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]  # fmt: skip
    return v[np.array(faces)]


def _body(
    boxes: dict[str, tuple[tuple[float, ...], tuple[float, ...]]],
) -> tuple[np.ndarray, np.ndarray]:
    """The boxes' union as one closed surface: filled on a grid, then its boundary faces."""
    triangles = np.concatenate([_box(low, high) for low, high in boxes.values()])
    grid, origin = voxel_inside(triangles, VOXEL / 2)
    return voxel_surface(grid, origin, VOXEL / 2)


def _rig(boxes=BOXES):
    positions, faces = _body(boxes)
    inside = inside_of(positions, faces, VOXEL)
    joints, ends = fit_joints(JOINTS, ENDS, CHAINS, RADII, inside)
    indices, weights = bone_heat(positions, faces, NAMES, joints, ends, inside)
    return positions, faces, inside, joints, ends, indices, weights


def _check(positions, inside, joints, ends, indices, weights):
    return check_rig(
        positions=positions,
        indices=indices,
        weights=weights,
        bones=NAMES,
        parents=PARENTS,
        plan_joints=JOINTS,
        joints=joints,
        ends=ends,
        chains=CHAINS,
        inside=inside,
        size=SIZE,
    )


@pytest.fixture(scope="module")
def rigged():
    return _rig()


def test_the_body_written_here_rigs_and_passes_every_check(rigged):
    positions, _faces, inside, joints, ends, indices, weights = rigged
    checks = _check(positions, inside, joints, ends, indices, weights)
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert max(checks.leaked_share.values()) <= 0.03
    # Every vertex of a leg's box below the torso moves with that leg's bones and no other's.
    for key in ("leg1Left", "leg1Right", "leg2Left", "leg2Right"):
        (x0, y0, _z0), (x1, y1, _z1) = BOXES[key]
        own = (
            (positions[:, 0] >= x0) & (positions[:, 0] <= x1)
            & (positions[:, 1] >= y0) & (positions[:, 1] <= y1)
            & (positions[:, 2] < 0.40)
        )  # fmt: skip
        assert own.sum() > 50
        mine = [NAMES.index(f"{key}1"), NAMES.index(f"{key}2")]
        on_leg = np.where(np.isin(indices[own], mine), weights[own], 0.0).sum(axis=1)
        assert on_leg.min() > 0.95, key


def test_joints_move_into_the_middle_of_their_limb_and_no_further(rigged):
    _positions, _faces, _inside, joints, _ends, _indices, _weights = rigged
    # The knee was placed at the leg box's centre line; centring keeps it there within a voxel.
    assert np.linalg.norm(joints["leg1Left2"] - JOINTS["leg1Left2"]) <= VOXEL
    # A chain's first joint keeps its place: it lies inside already.
    assert np.array_equal(joints["leg1Left1"], JOINTS["leg1Left1"])


def test_two_legs_fused_by_a_web_are_refused_as_one_dragging_the_other():
    webbed = dict(BOXES, web=((-0.10, 0.27, 0.12), (0.10, 0.33, 0.40)))
    positions, _faces, inside, joints, ends, indices, weights = _rig(webbed)
    with pytest.raises(RigRefused, match="rig_limb_drags_body") as refused:
        _check(positions, inside, joints, ends, indices, weights)
    # The refusal carries every measure, and the chain it names is recorded past the bound.
    checks = refused.value.checks
    assert set(checks.joint_moved_m) == set(checks.inside_share) == set(NAMES)
    assert set(checks.leaked_share) == {
        chain["key"] for chain in CHAINS if chain["role"] in CHAIN_ROLES
    }
    swung = refused.value.detail.split()[1]
    assert checks.leaked_share[swung] > LEAKED_SHARE


def test_a_leg_the_mesh_lacks_is_refused_where_its_joints_cannot_lie():
    lacking = {key: box for key, box in BOXES.items() if key != "leg2Right"}
    positions, _faces, inside, joints, ends, indices, weights = _rig(lacking)
    with pytest.raises(RigRefused, match="rig_joint_far_from_plan|rig_bone_outside"):
        _check(positions, inside, joints, ends, indices, weights)


def test_a_joint_outside_the_body_is_refused(rigged):
    positions, _faces, inside, joints, ends, indices, weights = rigged
    moved = dict(joints, leg1Left2=joints["leg1Left2"] + np.array([-0.3, 0.0, 0.0]))
    with pytest.raises(RigRefused, match="rig_joint_outside"):
        _check(positions, inside, moved, ends, indices, weights)


def test_weights_that_leave_a_limb_bone_nothing_are_refused(rigged):
    positions, _faces, inside, joints, ends, _indices, weights = rigged
    rooted = np.zeros((len(positions), 4), dtype=np.int64)
    whole = np.zeros_like(weights)
    whole[:, 0] = 1.0
    with pytest.raises(RigRefused, match="rig_bone_moves_nothing"):
        _check(positions, inside, joints, ends, rooted, whole)


def test_the_heat_solver_without_scipy_agrees_with_a_dense_solve(monkeypatch):
    positions, faces = _body({"torso": BOXES["torso"], "leg": BOXES["leg1Left"]})
    rows, columns, weights, area = _laplacian(positions, faces)
    degree = np.zeros(len(positions))
    np.add.at(degree, rows, weights)
    heat = area / 0.05**2
    diagonal = degree + heat
    right = np.stack([np.where(positions[:, 2] < 0.3, heat, 0.0), heat * 0.5], axis=1)
    dense = np.diag(diagonal)
    np.subtract.at(dense, (rows, columns), weights)
    expected = np.linalg.solve(dense, right)
    monkeypatch.setitem(sys.modules, "scipy", None)
    assert np.abs(_solve(rows, columns, weights, diagonal, right) - expected).max() < 1e-6
