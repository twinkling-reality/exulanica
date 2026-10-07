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
