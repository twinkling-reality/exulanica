from __future__ import annotations

import hashlib
import json
import math
from array import array

import pytest
from exulanica.reconstruction.alignment import fit_point_map_scale
from exulanica.reconstruction.opm import Viewpoint, encode_opm
from exulanica.reconstruction.placement import (
    PointMapInput,
    build_placement_record,
    recovered_camera_records,
    validate_placement_record,
    validated_receipt_cameras,
)
from exulanica.reconstruction.pointmap import PointMap, Segment


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _geometry(scale: float = 2, centre: float = 0):
    positions = array("f")
    observations = []
    width, height = 32, 24
    focal = height / (2 * math.tan(math.radians(60) / 2))
    for y in range(height):
        for x in range(width):
            depth = 2 + x * 0.03 + y * 0.05
            cx = (x + 0.5 - width / 2) / focal * depth
            cy = (y + 0.5 - height / 2) / focal * depth
            positions.extend((cx, -cy, -depth))
            if x % 3 == 0 and y % 3 == 0:
                observations.append(
                    [
                        y * width + x,
                        (x + 0.5) * 10,
                        (y + 0.5) * 10,
                        cx * scale + centre,
                        cy * scale,
                        depth * scale,
                        0.2,
                        4,
                    ]
                )
    count = width * height
    points = PointMap(
        positions,
        bytearray([128, 128, 128, 255] * count),
        array("H", [0, 0] * count),
        [Segment(0, "unsegmented", "unknown")],
    )
    data = encode_opm(
        points,
        generator="numeric-alignment-test",
        viewpoint=Viewpoint(60, 4 / 3),
        source_size=(320, 240),
        model_size=(width, height),
        color_alpha="support",
        metric=False,
    )
    return data, observations


def _receipt() -> bytes:
    manifest = {
        "profile": "exulanica.colmap-pose-build/v1",
        "scene_ref": "scene-1",
        "code_revision": "a" * 40,
        "colmap_version": "pycolmap 4.2.0",
        "execution_image": "runtime@sha256:" + "b" * 64,
        "frames": [
            {
                "capture_ref": capture,
                "filename": f"{index:04d}.jpg",
                "sha256": character * 64,
                "capture_set": "group-1",
            }
            for index, (capture, character) in enumerate(
                (("capture-a", "1"), ("capture-b", "2"), ("capture-c", "3"))
            )
        ],
        "quality_thresholds": {
            "min_registered_fraction": None,
            "max_mean_reprojection_error_px": None,
            "min_camera_translation_units": None,
        },
        "metric_scale": None,
    }
    camera_convention = {
        "mapping": "camera_from_world",
        "camera_axes": {"right": "+X", "down": "+Y", "forward": "+Z"},
        "quaternion_order": "wxyz",
    }
    quality = {
        "source_count": 3,
        "registered_images": ["0000.jpg", "0002.jpg"],
        "cameras": [
            {
                "image_name": "0000.jpg",
                "convention": camera_convention,
                "quaternion_wxyz": [1, 0, 0, 0],
                "translation_xyz": [0, 0, 0],
                "camera_centre_xyz": [0, 0, 0],
                "image_size": [320, 240],
                "sparse_observations": _geometry()[1],
            },
            {
                "image_name": "0002.jpg",
                "convention": camera_convention,
                "quaternion_wxyz": [1, 0, 0, 0],
                "translation_xyz": [-2, 0, 0],
                "camera_centre_xyz": [2, 0, 0],
                "image_size": [320, 240],
                "sparse_observations": _geometry(4, 2)[1],
            },
        ],
        "registered_fraction": 2 / 3,
        "mean_reprojection_error_px": 0.4,
        "camera_translation_extent_units": 2,
        "connected_model": "0",
        "jointly_coregistered": False,
        "shared_metric_frame": False,
        "metric_scale_metres_per_unit": None,
        "artifact_inventory": [],
        "accepted": False,
        "fallback_rung": 3,
        "reasons": [
            "minimum registered-image fraction is unmeasured",
            "maximum mean reprojection error is unmeasured",
            "minimum recovered camera translation is unmeasured",
        ],
    }
    return (
        _canonical(
            {
                "profile": "exulanica.colmap-pose-receipt/v2",
                "manifest_digest": hashlib.sha256(_canonical(manifest)).hexdigest(),
                "manifest": manifest,
                "quality_digest": hashlib.sha256(_canonical(quality)).hexdigest(),
                "quality": quality,
            }
        )
        + b"\n"
    )


def _maps() -> dict[str, PointMapInput]:
    data, _ = _geometry()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "capture-a": PointMapInput("capture-a", "artifact-a", digest, data),
        "capture-c": PointMapInput("capture-c", "artifact-c", digest, data),
    }


def _record():
    return build_placement_record(
        scene_ref="scene-1",
        pose_receipt=_receipt(),
        member_capture_refs=("capture-a", "capture-b", "capture-c"),
        point_maps=_maps(),
    )


def _rewrite(data: bytes, change) -> bytes:
    envelope = json.loads(data)
    change(envelope["placement"])
    envelope["payload_sha256"] = hashlib.sha256(_canonical(envelope["placement"])).hexdigest()
    return _canonical(envelope) + b"\n"


def test_placement_is_deterministic_and_keeps_exact_member_order():
    first = _record()
    second = _record()
    assert first.to_bytes() == second.to_bytes()
    assert first.member_capture_refs == ("capture-a", "capture-b", "capture-c")
    assert [member.capture_ref for member in first.placed] == ["capture-a", "capture-c"]
    assert first.excluded[0].as_payload() == {
        "capture_ref": "capture-b",
        "registered": False,
        "reason": "pose-not-registered",
        "alignment": None,
    }


def test_transform_converts_opm_axes_and_places_the_recovered_camera():
    first, second = _record().placed
    assert first.scene_from_opm == pytest.approx(
        (
            2,
            0,
            0,
            0,
            0,
            -2,
            0,
            0,
            0,
            0,
            -2,
            0,
            0,
            0,
            0,
            1,
        )
    )
    assert second.scene_from_opm[3:12:4] == (2, 0, 0)
    assert second.local_units_to_scene_units == pytest.approx(4)
    assert second.scale_status == "colmap-correspondence-fit"
    assert _record().payload()["scale_policy"]["physically_validated"] is False


def test_validation_accepts_only_the_record_current_inputs_reproduce():
    record = _record()
    assert (
        validate_placement_record(
            record.to_bytes(),
            expected_scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=_maps(),
        )
        == record
    )


def test_changed_point_map_digest_makes_the_placement_stale():
    changed = _maps()
    changed["capture-c"] = PointMapInput("capture-c", "artifact-c", "d" * 64)
    with pytest.raises(ValueError, match="current inputs"):
        validate_placement_record(
            _record().to_bytes(),
            expected_scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=changed,
        )


def test_duplicate_or_missing_member_outcomes_are_refused():
    duplicate = _rewrite(
        _record().to_bytes(),
        lambda payload: payload["excluded"].append(payload["excluded"][0]),
    )
    with pytest.raises(ValueError, match="exactly one"):
        validate_placement_record(
            duplicate,
            expected_scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=_maps(),
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["placed"][0].__setitem__(
                "scene_from_opm_row_major", [1, 0, 0, 0] * 4
            ),
            "affine",
        ),
        (
            lambda payload: payload["placed"][0].__setitem__(
                "scene_from_opm_row_major", [2, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
            ),
            "orthonormal",
        ),
        (
            lambda payload: payload.__setitem__(
                "profile", "exulanica.posed-point-map-placement/v1"
            ),
            "version",
        ),
    ],
)
def test_invalid_transform_and_format_versions_are_refused(mutate, message):
    damaged = _rewrite(_record().to_bytes(), mutate)
    with pytest.raises(ValueError, match=message):
        validate_placement_record(
            damaged,
            expected_scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=_maps(),
        )


def test_a_point_map_from_outside_the_scene_is_refused():
    point_maps = _maps()
    point_maps["capture-x"] = PointMapInput("capture-x", "artifact-x", "e" * 64)
    with pytest.raises(ValueError, match="outside the scene"):
        build_placement_record(
            scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=point_maps,
        )


def test_no_correspondences_excludes_geometry_instead_of_assuming_identity():
    receipt = json.loads(_receipt())
    for camera in receipt["quality"]["cameras"]:
        camera["sparse_observations"] = []
    receipt["quality_digest"] = hashlib.sha256(_canonical(receipt["quality"])).hexdigest()
    record = build_placement_record(
        scene_ref="scene-1",
        pose_receipt=_canonical(receipt),
        member_capture_refs=("capture-a", "capture-b", "capture-c"),
        point_maps=_maps(),
    )
    assert not record.placed
    assert record.excluded[0].reason == "alignment-unavailable"


def test_point_map_digest_verifies_actual_fitting_bytes():
    with pytest.raises(ValueError, match="content digest"):
        PointMapInput("capture-a", "artifact-a", "a" * 64, _geometry()[0])


def test_rehashed_physical_scale_claim_is_refused():
    damaged = _rewrite(
        _record().to_bytes(),
        lambda payload: payload["scale_policy"].__setitem__("physically_validated", True),
    )
    with pytest.raises(ValueError, match="current inputs"):
        validate_placement_record(
            damaged,
            expected_scene_ref="scene-1",
            pose_receipt=_receipt(),
            member_capture_refs=("capture-a", "capture-b", "capture-c"),
            point_maps=_maps(),
        )


@pytest.mark.parametrize("damage", ["too-few", "concentrated", "inconsistent"])
def test_sparse_or_inconsistent_alignment_never_places_identity_geometry(damage):
    data, rows = _geometry()
    if damage == "too-few":
        rows = rows[:12]
    elif damage == "concentrated":
        rows = [row for row in rows if row[1] < 80]
    else:
        rows = [[*row[:3], row[3] * 8, row[4], row[5], *row[6:]] for row in rows]
    result = fit_point_map_scale(
        data,
        image_size=(320, 240),
        observations=rows,
        quaternion_wxyz=(1, 0, 0, 0),
        translation_xyz=(0, 0, 0),
    )
    assert result.scale is None
    assert result.reason == (
        "alignment-inconsistent"
        if damage == "inconsistent"
        else "alignment-insufficient-correspondences"
    )


def test_robust_scale_tolerates_minority_outliers_without_a_metric_claim():
    data, rows = _geometry(3.5)
    for index, row in enumerate(rows):
        if index % 7 == 0:
            row[3:6] = [value * 5 for value in row[3:6]]
    result = fit_point_map_scale(
        data,
        image_size=(320, 240),
        observations=rows,
        quaternion_wxyz=(1, 0, 0, 0),
        translation_xyz=(0, 0, 0),
    )
    assert result.scale == pytest.approx(3.5)
    assert result.diagnostics["validation_samples"] >= 6
    assert result.diagnostics["physically_validated"] is False


def test_missing_map_removes_only_that_members_geometry_during_delivery():
    maps = _maps()
    current = maps["capture-c"]
    maps["capture-c"] = PointMapInput(
        current.capture_ref, current.artifact_ref, current.content_sha256
    )
    record = validate_placement_record(
        _record().to_bytes(),
        expected_scene_ref="scene-1",
        pose_receipt=_receipt(),
        member_capture_refs=("capture-a", "capture-b", "capture-c"),
        point_maps=maps,
        allow_unavailable_bytes=True,
    )
    assert [item.capture_ref for item in record.placed] == ["capture-a"]
    assert record.excluded[-1].reason == "alignment-unavailable"


def test_scale_fit_uses_recovered_rotation_and_translation():
    data, rows = _geometry(2.75)
    # camera_from_world: 90 degrees about Z and a translated centre.
    translated = []
    for row in rows:
        cx, cy, cz = row[3:6]
        translated.append([*row[:3], cy - 2, 1 - cx, cz - 3, *row[6:]])
    result = fit_point_map_scale(
        data,
        image_size=(320, 240),
        observations=translated,
        quaternion_wxyz=(math.sqrt(0.5), 0, 0, math.sqrt(0.5)),
        translation_xyz=(1, 2, 3),
    )
    assert result.scale == pytest.approx(2.75)


def test_nonphysical_scalar_is_applied_once_and_leaves_the_camera_centre_fixed():
    placed = _record().placed[1]
    matrix = placed.scene_from_opm
    assert (matrix[3], matrix[7], matrix[11]) == (2, 0, 0)
    # Raw OPM camera-forward point at z=-3 maps to world z=12 under scale 4.
    assert matrix[10] * -3 + matrix[11] == pytest.approx(12)


def test_alignment_holdout_is_not_used_to_fit_and_can_reject_a_perfect_training_fit():
    data, rows = _geometry()
    # The declared fifth fold is fixed by model-image sample location before fitting.
    ordered = sorted(
        rows,
        key=lambda row: hashlib.sha256(
            repr((int(row[1] / 10), int(row[2] / 10))).encode()
        ).digest(),
    )
    for row in ordered[::5]:
        row[3:6] = [value * 8 for value in row[3:6]]
    result = fit_point_map_scale(
        data,
        image_size=(320, 240),
        observations=rows,
        quaternion_wxyz=(1, 0, 0, 0),
        translation_xyz=(0, 0, 0),
    )
    assert result.diagnostics["training_inlier_fraction"] == 1
    assert result.diagnostics["validation_inlier_fraction"] == 0
    assert result.scale is None and result.reason == "alignment-inconsistent"


def test_recovered_camera_keeps_calibrated_projection_and_unscaled_renderer_pose():
    value = json.loads(_receipt())
    quality = value["quality"]
    quality["accepted"] = True
    camera = quality["cameras"][0]
    camera["quaternion_wxyz"] = [math.sqrt(0.5), 0, math.sqrt(0.5), 0]
    camera["translation_xyz"] = [-1, -2, -3]
    camera["calibration"] = {"model": "PINHOLE", "parameters": [300, 280, 151, 119]}
    quality["cameras"][1]["calibration"] = {
        "model": "SIMPLE_RADIAL",
        "parameters": [260, 160, 120, 0.03],
    }
    value["quality_digest"] = hashlib.sha256(_canonical(quality)).hexdigest()
    cameras = recovered_camera_records(_canonical(value))
    assert set(cameras) == {"capture-a", "capture-c"}
    recovered = cameras["capture-a"]
    assert recovered["scene_from_camera_row_major"] == pytest.approx(
        [0, 0, 1, -3, 0, -1, 0, 2, 1, 0, 0, 1, 0, 0, 0, 1]
    )
    assert recovered["calibration"] == {
        "model": "PINHOLE",
        "width": 320,
        "height": 240,
        "fx": 300,
        "fy": 280,
        "cx": 151,
        "cy": 119,
        "parameters": [300, 280, 151, 119],
    }
    assert recovered["projection"] == "pinhole"
    assert cameras["capture-c"]["projection"] == "pinhole-approximation"
    assert cameras["capture-c"]["calibration"]["fx"] == 260
    quality["accepted"] = False
    value["quality_digest"] = hashlib.sha256(_canonical(quality)).hexdigest()
    assert recovered_camera_records(_canonical(value)) == {}


def _calibrated_receipt() -> dict:
    value = json.loads(_receipt())
    quality = value["quality"]
    quality["accepted"] = True
    quality["cameras"][0]["quaternion_wxyz"] = [math.sqrt(0.5), 0, math.sqrt(0.5), 0]
    quality["cameras"][0]["translation_xyz"] = [-1, -2, -3]
    quality["cameras"][0]["calibration"] = {"model": "PINHOLE", "parameters": [300, 280, 151, 119]}
    quality["cameras"][1]["calibration"] = {
        "model": "SIMPLE_RADIAL",
        "parameters": [260, 160, 120, 0.03],
    }
    value["quality_digest"] = hashlib.sha256(_canonical(quality)).hexdigest()
    return value


def test_the_light_camera_reader_agrees_with_the_full_one_field_for_field():
    """The scene segment lift reads cameras without the sparse observations, which are about 99.9
    per cent of a real receipt. It must resolve every pose and calibration exactly as the reader
    that validates the whole receipt does, because the two share the code that checks them."""
    value = _calibrated_receipt()
    data = _canonical(value)
    light = validated_receipt_cameras(data)
    full = recovered_camera_records(data)
    assert set(light) == set(full) == {"capture-a", "capture-c"}
    for capture, record in light.items():
        assert record["calibration"] == full[capture]["calibration"]
        assert record["projection"] == full[capture]["projection"]
        [camera] = [
            item
            for item in value["quality"]["cameras"]
            if item["image_name"] == record["image_name"]
        ]
        assert record["quaternion_wxyz"] == [float(v) for v in camera["quaternion_wxyz"]]
        assert record["translation_xyz"] == [float(v) for v in camera["translation_xyz"]]
    assert light["capture-a"]["image_name"] == "0000.jpg"

    value["quality"]["accepted"] = False
    assert validated_receipt_cameras(_canonical(value)) == {}


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda quality: quality["cameras"][0].update(quaternion_wxyz=[1, 1, 0, 0]), "unit length"),
        (lambda quality: quality["cameras"][0].update(convention={"mapping": "x"}), "convention"),
        (lambda quality: quality["cameras"][1].update(image_size=[0, 240]), "dimensions"),
        (lambda quality: quality.update(registered_images=["0000.jpg"]), "disagree"),
    ],
)
def test_the_light_camera_reader_refuses_what_the_full_one_refuses(damage, message):
    value = _calibrated_receipt()
    damage(value["quality"])
    value["quality_digest"] = hashlib.sha256(_canonical(value["quality"])).hexdigest()
    with pytest.raises(ValueError, match=message):
        recovered_camera_records(_canonical(value))
    with pytest.raises(ValueError, match=message):
        validated_receipt_cameras(_canonical(value))
