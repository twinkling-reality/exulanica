"""The creature route's own pieces, without a model: its request, its registration and its colours.

The body is the box figure of ``test_creature_rig.py``, written there from boxes, so registration is
held to a turn this file applies and not to the creature builder.
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from test_creature_rig import BONES, BOXES, CHAINS, _body, _box

from exulanica_appearance.creatures.colour import SWATCHES, flat_colours, swatches
from exulanica_appearance.creatures.register import (
    PROPORTION_RATIO,
    YAWS,
    RegistrationRefused,
    _turn,
    register,
)
from exulanica_appearance.creatures.request import REQUEST_PROFILE, RequestRefused, read_request

REQUEST = {
    "profile": REQUEST_PROFILE,
    "plan": {
        "key": "box_figure",
        "version": 1,
        "sha256": "a" * 64,
        "bones": [{"name": name, "parent": spec[0]} for name, spec in BONES.items()],
        "limbs": [
            {
                "key": chain["key"],
                "role": chain["role"],
                "side": "centre",
                "order": 0,
                "bones": chain["bones"],
            }
            for chain in CHAINS
        ],
    },
    "rest": {
        name: {
            "joint_mm": [round(value * 1000) for value in spec[1]],
            "end_mm": [round(value * 1000) for value in spec[2]],
            "radius_mm": round(spec[3] * 1000),
        }
        for name, spec in BONES.items()
    },
    "sketch": {"sha256": "b" * 64, "bytes": 1024},
    "appearance": "a squat figure of grey stone with a long back",
    "colours": {
        "body": {"word": "slate grey", "srgb": [90, 98, 110]},
        "belly": {"word": "bone white", "srgb": [226, 218, 200]},
        "accent": {"word": "rust", "srgb": [160, 70, 40]},
        "eyes": {"word": "amber", "srgb": [255, 176, 0]},
    },
}


def _raw(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")


def test_a_request_is_read_with_its_rest_pose_in_metres():
    request = read_request(_raw(REQUEST))
    assert request.bones[0] == "hips" and request.parents["hips"] is None
    assert request.joints["leg1Left2"] == pytest.approx((-0.10, 0.30, 0.28))
    assert request.radii["tail1"] == pytest.approx(0.04)
    assert request.colour_words["eyes"] == "amber"


def _changed(path: list, value: object) -> dict:
    document = copy.deepcopy(REQUEST)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value", "words"),
    [
        (["profile"], "exulanica.creature-look-request/v0", "profile"),
        (["appearance"], "a figure with 4 legs and a tail", "numeral"),
        (["plan", "bones", 1, "parent"], "tail2", "before it"),
        (["plan", "limbs", 0, "bones"], ["spine2", "spine1"], "parent to child"),
        (["rest", "hips", "joint_mm"], [0, -350.5, 650], "whole millimetres"),
        (["colours", "eyes", "srgb"], [255, 176, 300], "0 to 255"),
        (["sketch", "sha256"], "B" * 64, "sketch"),
    ],
)
def test_a_request_out_of_its_profile_is_refused_by_its_field(path, value, words):
    with pytest.raises(RequestRefused, match=words):
        read_request(_raw(_changed(path, value)))


def test_a_request_naming_someone_is_not_a_request():
    # Nothing in the profile holds who asked: an extra field is refused, whatever it holds.
    with pytest.raises(RequestRefused, match="exactly"):
        read_request(_raw(dict(REQUEST, workspace_id="w1")))


@pytest.fixture(scope="module")
def figure():
    positions, faces = _body(BOXES)
    sketch = np.concatenate([_box(low, high) for low, high in BOXES.values()])
    return positions, faces, sketch


@pytest.mark.parametrize("turned", [0, 90, 200, 311])
def test_registration_undoes_a_turn_and_a_scale_to_the_degree(figure, turned):
    positions, faces, sketch = figure
    moved = _turn(positions, turned) * 0.4 + np.array([0.3, -0.2, 0.1])
    registered = register(moved, faces, sketch)
    assert registered.yaw_degrees == (360 - turned) % 360
    # Fitted back onto the sketch's box: on the ground, the box's size on every axis.
    low, high = registered.positions.min(axis=0), registered.positions.max(axis=0)
    sketch_low, sketch_high = sketch.reshape(-1, 3).min(axis=0), sketch.reshape(-1, 3).max(axis=0)
    assert np.allclose(high - low, sketch_high - sketch_low, atol=1e-9)
    assert low[2] == pytest.approx(sketch_low[2])


def test_a_mesh_far_from_the_plans_proportions_is_refused_with_the_fit_it_refused(figure):
    positions, faces, sketch = figure
    stretched = positions * np.array([1.0, 1.0, 2.0])
    with pytest.raises(RegistrationRefused, match="sculpt_proportions_unfit") as refused:
        register(stretched, faces, sketch)
    # The refusal keeps its measures: the turn kept, every turn's score, and the three scales,
    # whose spread (the height drawn twice too tall) is what broke the rule.
    fit = refused.value.refused
    assert fit is not None and fit.yaw_degrees in fit.score_per_mille
    assert set(YAWS) <= set(fit.score_per_mille)
    height = fit.scale[2]
    assert height == min(fit.scale) and max(fit.scale) / height == pytest.approx(2.0, rel=0.1)
    assert max(fit.scale) / min(fit.scale) > PROPORTION_RATIO


def test_swatches_are_at_most_sixty_four_and_the_same_every_time():
    rng = np.random.default_rng(7)
    colours = rng.integers(0, 256, size=(5000, 3))
    first, second = swatches(colours), swatches(colours.copy())
    assert len(first) == SWATCHES and np.array_equal(first, second)
    # Two colours make two swatches, not sixty-four copies.
    assert len(swatches(np.array([[0, 0, 0], [255, 255, 255]] * 50))) == 2


def test_each_triangle_takes_one_swatch_near_its_own_colour():
    rng = np.random.default_rng(11)
    vertex_colours = rng.integers(0, 256, size=(300, 3)).astype(np.uint8)
    triangles = rng.integers(0, 300, size=(400, 3))
    flat, palette = flat_colours(vertex_colours, triangles)
    assert flat.shape == (400, 3)
    assert {tuple(colour) for colour in flat} <= {tuple(colour) for colour in palette}
    # A triangle whose three vertices share a colour that is itself a swatch keeps it exactly.
    same = np.full((1, 3), 0, dtype=np.int64)
    one = np.array([[40, 200, 90]] * 3 + [[250, 10, 10]] * 3, dtype=np.uint8)
    kept, _ = flat_colours(one, np.vstack([same, same + 3]))
    assert kept.tolist() == [[40, 200, 90], [250, 10, 10]]


def test_a_stray_fragment_is_dropped_and_the_body_kept():
    from exulanica_pieces.geometry.mesh import Mesh

    from exulanica_appearance.creatures.job import _main_parts

    body = _box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).reshape(-1, 3)
    crumb = _box((3.0, 3.0, 3.0), (3.05, 3.05, 3.05)).reshape(-1, 3)
    positions = np.concatenate([body, crumb])
    triangles = np.arange(len(positions)).reshape(-1, 3)
    # Share each box's corners, so each box is one part.
    unique, index = np.unique(positions, axis=0, return_inverse=True)
    mesh = Mesh(
        unique, index.reshape(-1).astype(np.int64)[triangles], np.zeros_like(unique, dtype=np.uint8)
    )
    kept, record = _main_parts(mesh)
    assert (record["parts"], record["parts_kept"]) == (2, 1)
    assert kept.positions.max() <= 1.0 and len(kept.triangles) == 12


def _drawn_one_by_one(triangles: np.ndarray, camera, size: int):
    """The rasteriser as it was written first, a triangle at a time in index order, replacing only
    a strictly nearer depth: the reference the all-at-once rasteriser is held to."""
    from exulanica_appearance.creatures.geometry import project

    projected = project(triangles, camera)
    flat = projected.reshape(-1, 3)
    low, high = flat[:, :2].min(axis=0), flat[:, :2].max(axis=0)
    centre = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2)
    scale = size * (1 - 2 * 0.08) / max(high[0] - low[0], high[1] - low[1], 1e-9)
    depth = np.full((size, size), np.nan)
    drawn = np.full((size, size), -1, dtype=np.int64)
    px = (projected[..., 0] - centre[0]) * scale + size / 2
    py = size / 2 - (projected[..., 1] - centre[1]) * scale
    pz = projected[..., 2]
    for index, ((x0, x1, x2), (y0, y1, y2), (z0, z1, z2)) in enumerate(
        zip(px, py, pz, strict=True)
    ):
        left, right = (
            int(max(np.floor(min(x0, x1, x2)), 0)),
            int(min(np.ceil(max(x0, x1, x2)), size - 1)),
        )
        top, bottom = (
            int(max(np.floor(min(y0, y1, y2)), 0)),
            int(min(np.ceil(max(y0, y1, y2)), size - 1)),
        )
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if left > right or top > bottom or abs(area) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(left, right + 1) + 0.5, np.arange(top, bottom + 1) + 0.5)
        w0 = ((x1 - xs) * (y2 - ys) - (x2 - xs) * (y1 - ys)) / area
        w1 = ((x2 - xs) * (y0 - ys) - (x0 - xs) * (y2 - ys)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        z = w0 * z0 + w1 * z1 + w2 * z2
        region = depth[top : bottom + 1, left : right + 1]
        nearer = inside & (np.isnan(region) | (z > region))
        region[nearer] = z[nearer]
        drawn[top : bottom + 1, left : right + 1][nearer] = index
    return depth, drawn


@pytest.mark.parametrize("case", ["small", "large", "level", "degenerate", "figure"])
def test_the_rasteriser_draws_what_drawing_one_triangle_at_a_time_draws(figure, case):
    from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, Camera, rasterise

    rng = np.random.default_rng(3)
    if case == "figure":
        positions, faces, _sketch = figure
        triangles = positions[faces]
    else:
        count, spread = {"small": (400, 0.05), "large": (60, 0.6)}.get(case, (200, 0.2))
        triangles = rng.uniform(-1, 1, size=(count, 1, 3)) + rng.normal(0, spread, (count, 3, 3))
    if case == "level":
        triangles[:, :, 2] = 0.25  # equal depths everywhere: the lower index keeps a pixel
    if case == "degenerate":
        triangles[::3, 2] = triangles[::3, 1]
    for camera, size in ((CONTROL_CAMERA, 96), (Camera(-35.0, 15.0), 128)):
        drawn = rasterise(triangles, camera, size)
        depth, index = _drawn_one_by_one(triangles, camera, size)
        assert np.array_equal(drawn.triangle, index)
        assert np.array_equal(drawn.depth, depth, equal_nan=True)
        assert (index >= 0).sum() > 0


def test_the_control_camera_sees_a_plan_from_its_front_left():
    from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, project

    # A plan faces +y with its left at -x: its head is nearer the camera than its tail, and its
    # left side nearer than its right ("toward" is larger nearer the camera).
    head, tail = np.array([0.0, 0.54, 1.08]), np.array([0.0, -0.55, 0.72])
    left, right = np.array([-0.15, 0.0, 0.65]), np.array([0.15, 0.0, 0.65])
    assert project(head, CONTROL_CAMERA)[2] > project(tail, CONTROL_CAMERA)[2]
    assert project(left, CONTROL_CAMERA)[2] > project(right, CONTROL_CAMERA)[2]


def test_a_sketch_s_structure_is_its_surface_in_trellis_s_frame_and_grid(figure):
    from exulanica_appearance.assets.backends.trellis import STRUCTURE_RESOLUTION, check_coords
    from exulanica_appearance.creatures.geometry import trellis_structure

    _positions, _faces, sketch = figure
    voxels = trellis_structure(sketch)
    assert voxels.dtype == np.int32 and voxels.shape[1] == 3
    assert len(np.unique(voxels, axis=0)) == len(voxels)
    check_coords(np.concatenate([np.zeros((len(voxels), 1), np.int32), voxels], axis=1))
    # The longest side (the figure's length, y) spans the grid; the box is centred on the others.
    low, high = voxels.min(axis=0), voxels.max(axis=0)
    assert (low[1], high[1]) == (0, STRUCTURE_RESOLUTION - 1)
    assert low[0] + high[0] in (
        STRUCTURE_RESOLUTION - 2,
        STRUCTURE_RESOLUTION - 1,
        STRUCTURE_RESOLUTION,
    )
    # TRELLIS's front is -Y and its up +Z: the head (+y, high) lies at low Y and high Z, and the
    # tail at high Y; the figure's left leg (-x) at high X.
    corners = sketch.reshape(-1, 3)
    span = float((corners.max(axis=0) - corners.min(axis=0)).max())
    middle = (corners.max(axis=0) + corners.min(axis=0)) / 2

    def voxel_of(point):
        turned = np.array([-point[0], -point[1], point[2]])
        middle_turned = np.array([-middle[0], -middle[1], middle[2]])
        return np.floor(((turned - middle_turned) / span + 0.5) * STRUCTURE_RESOLUTION).astype(int)

    held = {tuple(row) for row in voxels.tolist()}
    for triangle in sketch[:: max(len(sketch) // 50, 1)]:
        assert tuple(np.clip(voxel_of(triangle.mean(axis=0)), 0, 63)) in held
    head, tail = voxel_of(np.array([0.0, 0.66, 1.08])), voxel_of(np.array([0.0, -0.70, 0.72]))
    assert head[1] < tail[1] and head[2] > tail[2]
    assert voxel_of(np.array([-0.10, 0.30, 0.10]))[0] > voxel_of(np.array([0.10, 0.30, 0.10]))[0]


def test_triangles_whose_boxes_hold_no_pixel_centre_draw_nothing():
    # Tiny triangles between pixel centres: their boxes hold candidates, none inside. The thin
    # eel of the second trial's dry run met this at some turns, and the rasteriser failed.
    from exulanica_appearance.creatures.geometry import _draw

    px = np.array([[10.0, 10.2, 10.0], [20.1, 20.3, 20.1]])
    py = np.array([[10.0, 10.0, 10.2], [5.1, 5.1, 5.3]])
    pz = np.zeros((2, 3))
    depth, drawn = _draw(px, py, pz, 32)
    assert np.isnan(depth).all() and (drawn == -1).all()
