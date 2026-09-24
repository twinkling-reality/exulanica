"""The standpoint join on photographs whose geometry is known exactly.

Every photograph here is a render of one procedural room (``standpoint_fixtures``), so the true
rotation, translation and depth of every pixel are known, and COLMAP's real SIFT runs on real
pixels. The tolerances are set from the room's own sampling: at 320 pixels across a 75 degree
field one pixel is 0.235 degrees, and a feature is located to a fraction of that.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import uuid
from typing import ClassVar

import pytest

#: numpy and scipy arrive with the `reconstruction` extra, which a plain `uv sync` does not install,
#: and the join and its fixtures import both; unguarded, one import stops the whole collection.
pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
pytest.importorskip(
    "scipy", reason="scipy is absent; install it with `uv sync --extra reconstruction`"
)

import numpy as np
from exulanica.canonical import sha256_of_canonical
from exulanica.ingest.stages import stage
from exulanica.reconstruction.standpoint import (
    StandpointExclusion,
    StandpointInput,
    StandpointPolicy,
    join_standpoint,
)
from exulanica.reconstruction.standpoint_features import PycolmapSift
from exulanica.reconstruction.standpoint_record import (
    PARTS_PER_BILLION,
    member_refusal,
    parse_standpoint_record,
    scene_from_opm_row_major,
)

from standpoint_fixtures import HEIGHT, WIDTH, Box, Camera, Room, focal_35mm, photograph, render

#: A fifth of a degree: under one pixel of this room's photographs. The join refines each stated
#: focal length from the overlaps, to a few tenths of a percent on photographs this small, which
#: moves a direction near a frame's edge by up to a tenth of a degree; what that buys is a turn
#: that stays right when a phone's stated focal length is a few percent off, which a fixed one
#: does not (docs/evaluation, the standpoint join's record).
ROTATION_TOLERANCE_DEG = 0.2

SPEC = stage("scene_standpoint")
POLICY = StandpointPolicy.from_params(SPEC.params)


@pytest.fixture(scope="module")
def extractor() -> PycolmapSift:
    return PycolmapSift(
        max_features=POLICY.max_features,
        peak_threshold=POLICY.peak_threshold,
        threads=POLICY.feature_threads,
    )


def _join(extractor, cameras, *, room=None, focals=None, estimated=None, excluded=(), rooms=None):
    room = room or Room()
    # A phone states its lens: every photograph here does, unless the test says otherwise.
    focals = [focal_35mm(camera) for camera in cameras] if focals is None else focals
    inputs = []
    for ordinal, camera in enumerate(cameras):
        if ordinal in {item.ordinal for item in excluded}:
            continue
        image, point_map = photograph(
            (rooms or {}).get(ordinal, room),
            camera,
            estimated_fov_y_deg=None if estimated is None else estimated[ordinal],
        )
        inputs.append(
            StandpointInput(
                ordinal=ordinal,
                member_ref=str(uuid.uuid5(uuid.NAMESPACE_URL, f"member-{ordinal}")),
                point_map_artifact_ref=str(uuid.uuid5(uuid.NAMESPACE_URL, f"map-{ordinal}")),
                point_map=point_map,
                image=image,
                image_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                exif_focal_35mm=focals[ordinal],
            )
        )
    record = join_standpoint(
        scene_ref="00000000-0000-4000-8000-000000000001",
        inputs=inputs,
        excluded=excluded,
        policy=POLICY,
        policy_sha256=sha256_of_canonical(SPEC.params).hex(),
        stage_version=SPEC.version,
        extractor=extractor,
    )
    return record


def _relative_error_deg(record, cameras, a, b) -> float:
    arranged = {member.ordinal: member for member in record.arrangement.members}
    rot_a = np.array(arranged[a].scene_from_camera_ppb).reshape(3, 3) / PARTS_PER_BILLION
    rot_b = np.array(arranged[b].scene_from_camera_ppb).reshape(3, 3) / PARTS_PER_BILLION
    estimated = rot_a.T @ rot_b
    true = cameras[a].rotation.T @ cameras[b].rotation
    residual = estimated.T @ true
    skew = np.array(
        [
            residual[2, 1] - residual[1, 2],
            residual[0, 2] - residual[2, 0],
            residual[1, 0] - residual[0, 1],
        ]
    )
    return math.degrees(math.atan2(np.linalg.norm(skew) / 2, (np.trace(residual) - 1) / 2))


def test_photographs_turned_on_one_spot_are_joined_with_their_true_rotations(extractor):
    cameras = [Camera(0, 0), Camera(-35, 5), Camera(-65, -3)]
    record = _join(extractor, cameras)

    assert record.refusal is None
    assert [member.outcome for member in record.members] == ["joined"] * 3
    for a, b in ((0, 1), (1, 2), (0, 2)):
        assert _relative_error_deg(record, cameras, a, b) < ROTATION_TOLERANCE_DEG
    # The room's depth is exact and the cameras share a centre, so every overlap agrees.
    assert record.arrangement.scale_solve["max_residual_ppm"] < 20_000
    joined = [pair for pair in record.pairs if pair.outcome == "joined"]
    assert joined and all(abs(value) <= 30 for pair in joined for value in pair.translation_mm), (
        "a set taken from one point estimates no movement beyond a few centimetres"
    )
    # Parsed back exactly, as the graph will read it.
    assert parse_standpoint_record(record.to_bytes()).to_bytes() == record.to_bytes()


def test_the_arrangement_stands_level_and_faces_the_first_photograph(extractor):
    cameras = [Camera(20, 8), Camera(-15, 2), Camera(-50, 6)]
    record = _join(extractor, cameras)
    arranged = {member.ordinal: member for member in record.arrangement.members}
    reference = np.array(arranged[0].scene_from_camera_ppb).reshape(3, 3) / PARTS_PER_BILLION
    # Up in the reference camera's frame, estimated and true.
    estimated_up = reference.T @ np.array([0.0, 1.0, 0.0])
    true_up = cameras[0].rotation.T @ np.array([0.0, 1.0, 0.0])
    assert math.degrees(math.acos(np.clip(estimated_up @ true_up, -1, 1))) < 0.5
    forward = reference @ np.array([0.0, 0.0, -1.0])
    assert abs(forward[0]) < 1e-6, "the reference photograph faces the scene's -Z"
    assert record.arrangement.up["method"] == "camera-horizontal-axes"


def test_the_same_photographs_give_the_same_bytes(extractor):
    cameras = [Camera(0, 0), Camera(-35, 4)]
    assert _join(extractor, cameras).to_bytes() == _join(extractor, cameras).to_bytes()


def test_photographs_taken_metres_apart_are_refused_as_moved(extractor):
    # Two steps sideways, turned a little to keep the same boxes in view: overlapping, and not
    # from one standpoint.
    cameras = [Camera(0, 0), Camera(-12, 0, position=(1.8, 1.6, 0.4))]
    record = _join(extractor, cameras)
    pair = record.pairs[0]
    assert pair.outcome == "moved_between_photographs", pair
    assert record.refusal == "nothing_joined"
    assert member_refusal(record, 1) == "moved_between_photographs"


def _misregistration_deg(record, cameras, a, b) -> tuple[float, float]:
    """How far apart the arrangement draws true points both photographs see, and the least any turn
    alone could leave: the 90th percentiles of each, in degrees, over photograph ``a``'s pixels.

    From one standpoint a turn is all the arrangement can apply, so a camera that moved leaves
    parallax no turn removes; the join is as good as it can be when it leaves no more than that.
    """
    _rgb, ranges = render(Room(), cameras[a])
    columns, rows = np.meshgrid(np.arange(WIDTH) + 0.5, np.arange(HEIGHT) + 0.5)
    focal = cameras[a].focal
    rays = np.stack(
        [(columns - WIDTH / 2) / focal, -(rows - HEIGHT / 2) / focal, -np.ones_like(columns)], -1
    ).reshape(-1, 3)
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    world = np.array(cameras[a].position) + (rays @ cameras[a].rotation.T) * ranges.reshape(-1, 1)
    seen = (world - np.array(cameras[b].position)) @ cameras[b].rotation
    ahead = -seen[:, 2] > 0.05
    x = cameras[b].focal * seen[:, 0] / np.where(ahead, -seen[:, 2], 1) + WIDTH / 2
    y = -cameras[b].focal * seen[:, 1] / np.where(ahead, -seen[:, 2], 1) + HEIGHT / 2
    inside = ahead & (x >= 0) & (x < WIDTH) & (y >= 0) & (y < HEIGHT)
    from_a, from_b = rays[inside], seen[inside] / np.linalg.norm(seen[inside], axis=1)[:, None]
    arranged = {member.ordinal: member for member in record.arrangement.members}
    rot = {
        k: np.array(arranged[k].scene_from_camera_ppb).reshape(3, 3) / PARTS_PER_BILLION
        for k in (a, b)
    }

    def angles(u, v):
        return np.degrees(np.arctan2(np.linalg.norm(np.cross(u, v), axis=1), np.sum(u * v, 1)))

    drawn = angles(from_a @ rot[a].T, from_b @ rot[b].T)
    u, _s, vt = np.linalg.svd(from_b.T @ from_a)
    best = vt.T @ np.diag([1.0, 1.0, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    floor = angles(from_a, from_b @ best.T)
    return float(np.percentile(drawn, 90)), float(np.percentile(floor, 90))


def test_a_hand_held_turn_of_a_few_centimetres_is_still_one_standpoint(extractor):
    cameras = [Camera(0, 0), Camera(-35, 3, position=(0.08, 1.62, -0.05))]
    record = _join(extractor, cameras)
    assert record.pairs[0].outcome == "joined"
    # The camera's own turn is not what is drawn: eight centimetres at two metres is about two
    # degrees of parallax, which the turn that lines the photographs up absorbs where it can.
    drawn, floor = _misregistration_deg(record, cameras, 0, 1)
    assert floor > 0.2, "the movement makes parallax, or this test measures nothing"
    assert drawn < floor + ROTATION_TOLERANCE_DEG


def test_photographs_that_share_nothing_are_refused_for_overlap(extractor):
    record = _join(extractor, [Camera(0, 0), Camera(180, 0)])
    assert record.pairs[0].outcome == "insufficient_overlap"
    assert record.refusal == "nothing_joined"
    assert record.arrangement is None
    assert [list(component) for component in record.components] == [[0], [1]]


class _OneLocationTwice:
    """Four features a photograph, two of them at one location in each, the way SIFT returns a
    point that has two dominant orientations: in the first photograph features 0 and 1 coincide,
    in the second 2 and 3, so whichever photograph a pair treats as its target, two distinct
    matches share a bearing there."""

    identity: ClassVar[dict[str, str]] = {"contract": "test-one-location-twice"}

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, gray):
        height, width = gray.shape
        self.calls += 1
        centre, corner = (width / 2, height / 2), (12.0, 12.0)
        if self.calls == 1:
            xy = [centre, centre, corner, (width - 12.0, height - 12.0)]
        else:
            xy = [centre, (width / 2 + 40.0, height / 2), corner, corner]
        return np.array(xy, dtype=np.float64), np.eye(4, 128, dtype=np.float32)


def test_two_matches_that_share_a_bearing_are_not_taken_for_a_rotation():
    record = _join(_OneLocationTwice(), [Camera(0, 0), Camera(-20, 0)])
    assert [pair.outcome for pair in record.pairs] == ["insufficient_overlap"]


def test_a_box_that_appears_between_photographs_is_refused_as_a_changed_scene(extractor):
    base = Room()
    changed = dataclasses.replace(
        base, boxes=(*base.boxes, Box((-0.9, 0.0, -2.6), (0.3, 1.5, -1.9), (0.9, 0.9, 0.3)))
    )
    cameras = [Camera(0, 0), Camera(-30, 0)]
    record = _join(extractor, cameras, room=base, rooms={1: changed})
    pair = record.pairs[0]
    assert pair.outcome == "scene_changed", pair
    assert pair.changed_ppm is not None and pair.changed_ppm > POLICY.max_changed_fraction * 1e6
    # The same pair without the change joins, which is what makes the refusal about the box.
    assert _join(extractor, cameras, room=base).pairs[0].outcome == "joined"


def test_a_stated_focal_length_re_projects_the_depth_model_and_none_keeps_a_photograph_apart(
    extractor,
):
    cameras = [Camera(0, 0), Camera(-35, 4), Camera(-68, -2)]
    # The depth model estimated each field of view 6 percent too wide, as it does on real photos.
    estimated = [camera.fov_y_deg * 1.06 for camera in cameras]
    with_exif = _join(
        extractor, cameras, estimated=estimated, focals=[focal_35mm(c) for c in cameras]
    )
    stated = [focal_35mm(c) for c in cameras]
    without = _join(extractor, cameras, estimated=estimated, focals=[*stated[:2], None])
    for member in with_exif.members:
        assert member.reading.intrinsics.source == "exif-35mm-equivalent"
        # The depth model's focal over the photograph's: a wider estimate is a shorter focal, so
        # its points are pulled in onto the photograph's own, narrower rays.
        assert member.reading.intrinsics.lateral_scale == pytest.approx(
            math.tan(math.radians(cameras[member.ordinal].fov_y_deg / 2))
            / math.tan(math.radians(estimated[member.ordinal] / 2)),
            rel=0.01,
        )
    for a, b in ((0, 1), (1, 2)):
        assert _relative_error_deg(with_exif, cameras, a, b) < ROTATION_TOLERANCE_DEG
    # Where one photograph states no focal length, it is kept apart by name before anything is
    # matched, and the others join without it.
    assert [m.outcome for m in without.members] == ["joined", "joined", "focal_length_unstated"]
    assert without.members[2].reading is None
    assert all(2 not in (pair.a, pair.b) for pair in without.pairs)
    assert member_refusal(without, 2) == "focal_length_unstated"
    assert [list(component) for component in without.components] == [[0, 1], [2]]


def test_a_focal_length_stated_a_few_percent_off_is_refined_from_the_overlaps(extractor):
    cameras = [Camera(0, 0), Camera(-30, 4), Camera(-60, -2)]
    stated = [focal_35mm(camera) for camera in cameras]
    # A phone rounds its 35 mm equivalent to whole millimetres; this one also states a lens 3
    # percent longer than it is.
    stated[1] *= 1.03
    record = _join(extractor, cameras, focals=stated)
    member = record.member(1).reading.intrinsics
    assert member.stated_focal_micropixels / member.focal_micropixels == pytest.approx(
        1.03, abs=0.01
    )
    for a, b in ((0, 1), (1, 2)):
        assert _relative_error_deg(record, cameras, a, b) < ROTATION_TOLERANCE_DEG


def test_a_member_without_permission_is_recorded_with_nothing_read(extractor):
    cameras = [Camera(0, 0), Camera(-35, 0), Camera(-65, 0)]
    withheld = StandpointExclusion(ordinal=1, member_ref=str(uuid.uuid5(uuid.NAMESPACE_URL, "x")))
    record = _join(extractor, cameras, excluded=(withheld,))
    member = record.member(1)
    assert member.outcome == "not_permitted"
    assert member.reading is None and member.point_map_artifact_ref is None
    assert all(1 not in (pair.a, pair.b) for pair in record.pairs)
    assert member_refusal(record, 1) == "not_permitted"


def test_an_unreadable_point_map_is_named_and_joins_nothing(extractor):
    cameras = [Camera(0, 0), Camera(-35, 0)]
    record = _join(extractor, cameras)
    image, _ = photograph(Room(), cameras[1])
    broken = join_standpoint(
        scene_ref="00000000-0000-4000-8000-000000000002",
        inputs=[
            StandpointInput(
                ordinal=0,
                member_ref=record.members[0].member_ref,
                point_map_artifact_ref=record.members[0].point_map_artifact_ref,
                point_map=b"OPM1 not a point map",
                image=image,
                image_sha256="0" * 64,
                # States no focal length either: the unreadable estimate is what it is named for.
                exif_focal_35mm=None,
            ),
            StandpointInput(
                ordinal=1,
                member_ref=record.members[1].member_ref,
                point_map_artifact_ref=record.members[1].point_map_artifact_ref,
                point_map=photograph(Room(), cameras[1])[1],
                image=image,
                image_sha256="1" * 64,
                exif_focal_35mm=focal_35mm(cameras[1]),
            ),
        ],
        policy=POLICY,
        policy_sha256=sha256_of_canonical(SPEC.params).hex(),
        stage_version=SPEC.version,
        extractor=extractor,
    )
    assert broken.member(0).outcome == "point_map_unreadable"
    assert broken.member(0).reading is None
    assert broken.member(1).outcome == "not_joined"
    assert broken.refusal == "nothing_joined"


def test_the_renderer_transform_puts_each_photograph_on_its_measured_rays(extractor):
    cameras = [Camera(0, 0), Camera(-35, 5)]
    record = _join(extractor, cameras)
    for arranged in record.arrangement.members:
        matrix = np.array(scene_from_opm_row_major(arranged)).reshape(4, 4)
        rotation = np.array(arranged.scene_from_camera_ppb).reshape(3, 3) / PARTS_PER_BILLION
        # A point straight ahead of the camera at 5 m lands 5 m out along the camera's axis,
        # scaled by the member's depth scale.
        ahead = matrix @ np.array([0.0, 0.0, -5.0, 1.0])
        expected = rotation @ np.array([0.0, 0.0, -5.0]) * arranged.depth_scale_ppm / 1e6
        assert np.allclose(ahead[:3], expected, atol=1e-6)
