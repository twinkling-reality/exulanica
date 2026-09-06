"""A digest-bound placement record for posed OPM point maps.

The point map stays a per-photograph OPM/2 artifact in its source-camera frame. This record is
the separate scene-level fact that places those unchanged bytes. It consumes the raw COLMAP
``camera_from_world`` pose from the durable pose receipt and emits ``scene_from_opm`` matrices.

Coordinate conversion is explicit. COLMAP camera coordinates are +X right, +Y down and +Z
forward. OPM is +X right, +Y up and -Z forward. ``diag(1, -1, -1)`` maps OPM into COLMAP camera
coordinates, then the inverse recovered camera pose maps into the scale-ambiguous COLMAP world.
The scene therefore remains non-metric. The current producer fits numeric scale
from actual COLMAP tracks to OPM samples, withholding members without a consistent fit.
Agreement between reconstructions never establishes physical scale.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from exulanica.reconstruction.alignment import ALIGNMENT_POLICY, fit_point_map_scale

__all__ = [
    "PLACEMENT_PROFILE",
    "ExcludedPlacementMember",
    "PlacedPointMap",
    "PlacementRecord",
    "PointMapInput",
    "build_placement_record",
    "recovered_camera_records",
    "validate_placement_record",
]

PLACEMENT_PROFILE: Final = "exulanica.posed-point-map-placement/v2"
_POSE_PROFILE: Final = "exulanica.colmap-pose-receipt/v2"

#: Read from the shared alignment policy rather than repeated, so the reader's cap and the
#: producer's cap cannot drift apart. `pose.py` truncates each image's retained observations to
#: this; a receipt carrying more is malformed under this reader.
_MAX_SPARSE_OBSERVATIONS: Final = int(ALIGNMENT_POLICY["max_sparse_observations_per_image"])


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be lowercase SHA-256 hex")


@dataclass(frozen=True, slots=True)
class PointMapInput:
    capture_ref: str
    artifact_ref: str
    content_sha256: str
    content: bytes | None = None

    def __post_init__(self) -> None:
        if not self.capture_ref or not self.artifact_ref:
            raise ValueError("point-map capture and artifact references are required")
        _require_digest(self.content_sha256, "point-map content digest")
        if self.content is not None and _digest(self.content) != self.content_sha256:
            raise ValueError("point-map bytes disagree with their content digest")

    def as_payload(self) -> dict[str, str]:
        return {
            "capture_ref": self.capture_ref,
            "artifact_ref": self.artifact_ref,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class PlacedPointMap:
    capture_ref: str
    point_map_artifact_ref: str
    point_map_content_sha256: str
    scene_from_opm: tuple[float, ...]
    local_units_to_scene_units: float
    alignment: dict[str, object]
    scale_status: Literal["colmap-correspondence-fit"] = "colmap-correspondence-fit"

    def as_payload(self) -> dict[str, object]:
        return {
            "capture_ref": self.capture_ref,
            "point_map_artifact_ref": self.point_map_artifact_ref,
            "point_map_content_sha256": self.point_map_content_sha256,
            "scene_from_opm_row_major": list(self.scene_from_opm),
            "local_units_to_scene_units": self.local_units_to_scene_units,
            "scale_status": self.scale_status,
            "alignment": self.alignment,
        }


@dataclass(frozen=True, slots=True)
class ExcludedPlacementMember:
    capture_ref: str
    registered: bool
    reason: Literal[
        "pose-not-registered",
        "point-map-unavailable",
        "alignment-unavailable",
        "alignment-insufficient-correspondences",
        "alignment-inconsistent",
    ]
    alignment: dict[str, object] | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "capture_ref": self.capture_ref,
            "registered": self.registered,
            "reason": self.reason,
            "alignment": self.alignment,
        }


@dataclass(frozen=True, slots=True)
class PlacementRecord:
    scene_ref: str
    pose_receipt_sha256: str
    pose_manifest_sha256: str
    member_capture_refs: tuple[str, ...]
    placed: tuple[PlacedPointMap, ...]
    excluded: tuple[ExcludedPlacementMember, ...]
    input_sha256: str
    point_map_inputs: tuple[PointMapInput, ...]

    def payload(self) -> dict[str, object]:
        return {
            "profile": PLACEMENT_PROFILE,
            "scene_ref": self.scene_ref,
            "pose_receipt_sha256": self.pose_receipt_sha256,
            "pose_manifest_sha256": self.pose_manifest_sha256,
            "coordinate_convention": {
                "transform": "scene_from_opm",
                "matrix_layout": "row-major-4x4",
                "opm_axes": {"right": "+X", "up": "+Y", "forward": "-Z"},
                "scene_frame": "selected COLMAP world",
                "scene_units": "scale-ambiguous COLMAP reconstruction units",
                "metric": False,
            },
            "scale_policy": {
                **ALIGNMENT_POLICY,
                "physically_validated": False,
                "reason": "COLMAP/monocular agreement does not establish physical scale.",
            },
            "point_map_inputs": [item.as_payload() for item in self.point_map_inputs],
            "member_capture_refs": list(self.member_capture_refs),
            "placed": [member.as_payload() for member in self.placed],
            "excluded": [member.as_payload() for member in self.excluded],
            "input_sha256": self.input_sha256,
        }

    @property
    def payload_sha256(self) -> str:
        return _digest(_canonical(self.payload()))

    def as_payload(self) -> dict[str, object]:
        return {
            "profile": "exulanica.posed-point-map-placement-envelope/v1",
            "payload_sha256": self.payload_sha256,
            "placement": self.payload(),
        }

    def to_bytes(self) -> bytes:
        return _canonical(self.as_payload()) + b"\n"


@dataclass(frozen=True, slots=True)
class _PoseCamera:
    image_name: str
    quaternion_wxyz: tuple[float, float, float, float]
    translation_xyz: tuple[float, float, float]
    image_size: tuple[int, int] | None
    sparse_observations: tuple[tuple[float, ...], ...]
    calibration: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class _PoseReceipt:
    manifest_digest: str
    frames: tuple[tuple[str, str], ...]
    registered_images: tuple[str, ...]
    cameras: tuple[_PoseCamera, ...]


def _numbers(value: object, length: int, field: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{field} must contain {length} numbers")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
            raise ValueError(f"{field} must contain {length} finite numbers")
        result.append(float(item))
    return tuple(result)


def _calibration(raw: object, size: tuple[int, int] | None) -> dict[str, object] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("model"), str) or size is None:
        raise ValueError("camera calibration is malformed")
    model = raw["model"]
    shared = {
        "SIMPLE_PINHOLE": 3,
        "SIMPLE_RADIAL": 4,
        "RADIAL": 5,
        "SIMPLE_RADIAL_FISHEYE": 4,
        "RADIAL_FISHEYE": 5,
    }
    separate = {
        "PINHOLE": 4,
        "OPENCV": 8,
        "FULL_OPENCV": 12,
        "OPENCV_FISHEYE": 8,
        "FOV": 5,
        "THIN_PRISM_FISHEYE": 12,
    }
    count = (shared | separate).get(model)
    if count is None:
        return None  # Unknown models cannot silently acquire a guessed projection.
    values = _numbers(raw.get("parameters"), count, "camera calibration parameters")
    fx, fy, cx, cy = (values[0], values[0], values[1], values[2]) if model in shared else values[:4]
    if fx <= 0 or fy <= 0:
        raise ValueError("camera calibration focal lengths must be positive")
    return {
        "model": model,
        "width": size[0],
        "height": size[1],
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "parameters": list(values),
    }


def _read_pose_receipt(data: bytes) -> _PoseReceipt:
    try:
        receipt = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("the pose receipt is not canonical JSON") from error
    if not isinstance(receipt, dict) or receipt.get("profile") != _POSE_PROFILE:
        raise ValueError("the pose receipt profile is unsupported")
    manifest = receipt.get("manifest")
    quality = receipt.get("quality")
    if not isinstance(manifest, dict) or not isinstance(quality, dict):
        raise ValueError("the pose receipt must carry its manifest and quality")
    manifest_digest = receipt.get("manifest_digest")
    quality_digest = receipt.get("quality_digest")
    if not isinstance(manifest_digest, str) or _digest(_canonical(manifest)) != manifest_digest:
        raise ValueError("the pose manifest disagrees with its digest")
    if not isinstance(quality_digest, str) or _digest(_canonical(quality)) != quality_digest:
        raise ValueError("the pose quality disagrees with its digest")

    raw_frames = manifest.get("frames")
    if not isinstance(raw_frames, list):
        raise ValueError("the pose manifest has no frame list")
    frames: list[tuple[str, str]] = []
    for raw in raw_frames:
        if not isinstance(raw, dict):
            raise ValueError("a pose frame is not an object")
        capture_ref, filename = raw.get("capture_ref"), raw.get("filename")
        if not isinstance(capture_ref, str) or not capture_ref:
            raise ValueError("a pose frame has no capture reference")
        if not isinstance(filename, str) or not filename:
            raise ValueError("a pose frame has no filename")
        frames.append((capture_ref, filename))
    if len({capture for capture, _ in frames}) != len(frames) or len(
        {filename for _, filename in frames}
    ) != len(frames):
        raise ValueError("the pose manifest contains duplicate members")

    registered = quality.get("registered_images")
    raw_cameras = quality.get("cameras")
    if not isinstance(registered, list) or any(not isinstance(name, str) for name in registered):
        raise ValueError("the pose quality has an invalid registered-image list")
    if not isinstance(raw_cameras, list):
        raise ValueError("the pose quality has no camera list")
    cameras: list[_PoseCamera] = []
    for raw in raw_cameras:
        if not isinstance(raw, dict) or not isinstance(raw.get("image_name"), str):
            raise ValueError("a recovered camera is malformed")
        convention = raw.get("convention")
        if not isinstance(convention, dict) or convention.get("mapping") != "camera_from_world":
            raise ValueError("a recovered camera uses an unsupported convention")
        quaternion = _numbers(raw.get("quaternion_wxyz"), 4, "camera quaternion")
        norm = math.sqrt(sum(component * component for component in quaternion))
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-7):
            raise ValueError("a recovered camera quaternion is not unit length")
        raw_size = raw.get("image_size")
        size = None
        if raw_size is not None:
            if (
                not isinstance(raw_size, list)
                or len(raw_size) != 2
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value <= 0
                    for value in raw_size
                )
            ):
                raise ValueError("camera image dimensions are malformed")
            size = (raw_size[0], raw_size[1])
        raw_observations = raw.get("sparse_observations", [])
        if (
            not isinstance(raw_observations, list)
            or len(raw_observations) > _MAX_SPARSE_OBSERVATIONS
        ):
            raise ValueError("camera sparse observations are malformed")
        observations = tuple(_numbers(item, 8, "sparse observation") for item in raw_observations)
        if len({item[0] for item in observations}) != len(observations):
            raise ValueError("camera sparse observations contain duplicate points")
        cameras.append(
            _PoseCamera(
                image_name=raw["image_name"],
                image_size=size,
                sparse_observations=observations,
                calibration=_calibration(raw.get("calibration"), size),
                quaternion_wxyz=quaternion,  # type: ignore[arg-type]
                translation_xyz=_numbers(raw.get("translation_xyz"), 3, "camera translation"),  # type: ignore[arg-type]
            )
        )
    registered_names = tuple(registered)
    camera_names = tuple(camera.image_name for camera in cameras)
    if len(set(registered_names)) != len(registered_names) or set(camera_names) != set(
        registered_names
    ):
        raise ValueError("registered images and recovered cameras disagree")
    if not set(registered_names).issubset({filename for _, filename in frames}):
        raise ValueError("the pose receipt registered an image outside its manifest")
    return _PoseReceipt(
        manifest_digest=manifest_digest,
        frames=tuple(frames),
        registered_images=registered_names,
        cameras=tuple(cameras),
    )


def _scene_from_opm(camera: _PoseCamera, scale: float) -> tuple[float, ...]:
    qw, qx, qy, qz = camera.quaternion_wxyz
    rotation = (
        (1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)),
        (2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)),
        (2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)),
    )
    axis = (1.0, -1.0, -1.0)
    linear = tuple(
        tuple(
            scale * rotation[camera_axis][world_axis] * axis[local_axis]
            for local_axis, camera_axis in enumerate(range(3))
        )
        for world_axis in range(3)
    )
    centre = tuple(
        -sum(
            rotation[camera_axis][world_axis] * camera.translation_xyz[camera_axis]
            for camera_axis in range(3)
        )
        for world_axis in range(3)
    )
    return (
        linear[0][0],
        linear[0][1],
        linear[0][2],
        centre[0],
        linear[1][0],
        linear[1][1],
        linear[1][2],
        centre[1],
        linear[2][0],
        linear[2][1],
        linear[2][2],
        centre[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )


def sparse_observation_records(pose_receipt: bytes) -> dict[str, object]:
    """Group the retained COLMAP tracks by 3D point, so a surface can name what photographed it.

    This is the recorded answer to "which photographs observed this point", and it is recorded
    rather than inferred: COLMAP's ``point_id`` is global across every image in the selected model,
    so grouping the retained observations by it reconstructs the actual multi-view track. The
    alternative, reprojecting a clicked world point into each recovered camera and ranking by
    visibility, is a geometric guess about what a camera could have seen. These are different
    claims and only one of them is provenance.

    Two limits travel with the answer because a consumer that did not know them would overstate it.

    ``retained_per_image`` is 4096: the pose stage keeps a bounded, hash-ordered sample of each
    image's observations rather than all of them, so the observations held for a point are a subset
    of the images that saw it. ``track_length`` is COLMAP's full count, read from ``points3D.txt``
    before any truncation, so the difference between it and the number of observations returned is
    exactly what was dropped. A viewer told "3 photographs" for a point with a track length of 40
    would be misled by omission, which is why both numbers are here and neither is optional.

    Returns ``{}`` for an unaccepted receipt, matching :func:`recovered_camera_records`: an
    unaccepted pose has no delivered cameras to attach an observation to.
    """
    receipt = _read_pose_receipt(pose_receipt)
    if json.loads(pose_receipt)["quality"].get("accepted") is not True:
        return {}
    captures = {filename: capture for capture, filename in receipt.frames}

    points: dict[int, dict[str, object]] = {}
    for camera in receipt.cameras:
        capture_ref = captures.get(camera.image_name)
        if capture_ref is None:
            raise ValueError("a recovered camera names an image outside the pose manifest")
        for row in camera.sparse_observations:
            point_id = int(row[0])
            world = (row[3], row[4], row[5])
            track_length = int(row[7])
            existing = points.get(point_id)
            if existing is None:
                points[point_id] = {
                    "point_id": point_id,
                    "world_xyz": list(world),
                    "track_length": track_length,
                    "observations": [],
                }
                existing = points[point_id]
            elif existing["world_xyz"] != list(world) or existing["track_length"] != track_length:
                # Two images reporting different world coordinates or track lengths for one point
                # id means the receipt does not describe a single consistent model, and picking a
                # winner would publish a coordinate no camera actually agreed on.
                raise ValueError(
                    f"sparse point {point_id} disagrees with itself across recovered cameras"
                )
            observations = existing["observations"]
            assert isinstance(observations, list)
            observations.append(
                {
                    "capture_ref": capture_ref,
                    "image_name": camera.image_name,
                    "x": row[1],
                    "y": row[2],
                    "reprojection_error_px": row[6],
                }
            )

    for entry in points.values():
        observations = entry["observations"]
        assert isinstance(observations, list)
        observations.sort(key=lambda item: str(item["capture_ref"]))
        # What is held, beside what actually exists. The gap is the truncation, stated per point
        # rather than as a footnote a caller can skip.
        entry["observations_retained"] = len(observations)

    return {
        "retained_per_image": _MAX_SPARSE_OBSERVATIONS,
        "points": [points[key] for key in sorted(points)],
    }


def recovered_camera_records(pose_receipt: bytes) -> dict[str, dict[str, object]]:
    """Expose calibrated accepted poses independently of point-map delivery or fitted scale."""
    receipt = _read_pose_receipt(pose_receipt)
    if json.loads(pose_receipt)["quality"].get("accepted") is not True:
        return {}
    captures = {filename: capture for capture, filename in receipt.frames}
    return {
        captures[camera.image_name]: {
            "scene_from_camera_row_major": list(_scene_from_opm(camera, 1.0)),
            "calibration": camera.calibration,
            "projection": (
                "pinhole"
                if camera.calibration["model"] in {"PINHOLE", "SIMPLE_PINHOLE"}
                else "pinhole-approximation"
            ),
        }
        for camera in receipt.cameras
        if camera.calibration is not None
    }


def _input_digest(
    scene_ref: str,
    pose_receipt_sha256: str,
    member_capture_refs: Sequence[str],
    point_maps: Sequence[PointMapInput],
) -> str:
    return _digest(
        _canonical(
            {
                "scene_ref": scene_ref,
                "pose_receipt_sha256": pose_receipt_sha256,
                "member_capture_refs": list(member_capture_refs),
                "point_maps": [member.as_payload() for member in point_maps],
            }
        )
    )


def build_placement_record(
    *,
    scene_ref: str,
    pose_receipt: bytes,
    member_capture_refs: Sequence[str],
    point_maps: Mapping[str, PointMapInput],
) -> PlacementRecord:
    """Build one complete placement or exclusion outcome for every declared scene member."""
    if not scene_ref:
        raise ValueError("scene_ref is required")
    members = tuple(member_capture_refs)
    if not members or len(set(members)) != len(members):
        raise ValueError("scene members must be non-empty and duplicate free")
    if set(point_maps) - set(members):
        raise ValueError("a point-map input names a capture outside the scene")
    for capture_ref, point_map in point_maps.items():
        if point_map.capture_ref != capture_ref:
            raise ValueError("a point-map input is filed under another capture")

    receipt = _read_pose_receipt(pose_receipt)
    if {capture for capture, _ in receipt.frames} != set(members):
        raise ValueError("the placement member set differs from the pose manifest")
    filename_by_capture = dict(receipt.frames)
    camera_by_name = {camera.image_name: camera for camera in receipt.cameras}
    registered = set(receipt.registered_images)
    placed: list[PlacedPointMap] = []
    excluded: list[ExcludedPlacementMember] = []
    for capture_ref in members:
        filename = filename_by_capture[capture_ref]
        if filename not in registered:
            excluded.append(ExcludedPlacementMember(capture_ref, False, "pose-not-registered"))
            continue
        point_map = point_maps.get(capture_ref)
        if point_map is None:
            excluded.append(ExcludedPlacementMember(capture_ref, True, "point-map-unavailable"))
            continue
        camera = camera_by_name.get(filename)
        if camera is None:
            raise ValueError("a registered pose has no recovered camera")
        alignment = fit_point_map_scale(
            point_map.content,
            image_size=camera.image_size,
            observations=camera.sparse_observations,
            quaternion_wxyz=camera.quaternion_wxyz,
            translation_xyz=camera.translation_xyz,
        )
        if alignment.scale is None:
            assert alignment.reason is not None
            excluded.append(
                ExcludedPlacementMember(capture_ref, True, alignment.reason, alignment.diagnostics)
            )
            continue
        placed.append(
            PlacedPointMap(
                capture_ref=capture_ref,
                point_map_artifact_ref=point_map.artifact_ref,
                point_map_content_sha256=point_map.content_sha256,
                scene_from_opm=_scene_from_opm(camera, alignment.scale),
                local_units_to_scene_units=alignment.scale,
                alignment=alignment.diagnostics,
            )
        )
    pose_digest = _digest(pose_receipt)
    inputs = tuple(
        PointMapInput(item.capture_ref, item.artifact_ref, item.content_sha256)
        for capture in members
        if (item := point_maps.get(capture)) is not None
    )
    return PlacementRecord(
        scene_ref=scene_ref,
        pose_receipt_sha256=pose_digest,
        pose_manifest_sha256=receipt.manifest_digest,
        member_capture_refs=members,
        placed=tuple(placed),
        excluded=tuple(excluded),
        input_sha256=_input_digest(scene_ref, pose_digest, members, inputs),
        point_map_inputs=inputs,
    )


def _validate_matrix(member: PlacedPointMap) -> None:
    matrix = member.scene_from_opm
    if len(matrix) != 16 or not all(math.isfinite(value) for value in matrix):
        raise ValueError("placement transforms must be finite 4x4 matrices")
    if matrix[12:] != (0.0, 0.0, 0.0, 1.0):
        raise ValueError("placement transforms must be affine row-major matrices")
    scale = member.local_units_to_scene_units
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("placement scale must be finite and positive")
    rotation = tuple(
        tuple(matrix[row * 4 + column] / scale for column in range(3)) for row in range(3)
    )
    for left in range(3):
        for right in range(3):
            dot = sum(rotation[row][left] * rotation[row][right] for row in range(3))
            expected = 1.0 if left == right else 0.0
            if not math.isclose(dot, expected, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("placement rotation is not orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isclose(determinant, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError("placement rotation must be proper, without reflection")


def _record_from_payload(value: object) -> PlacementRecord:
    if not isinstance(value, dict) or value.get("profile") != PLACEMENT_PROFILE:
        raise ValueError("the placement format version is unsupported")
    raw_members = value.get("member_capture_refs")
    raw_placed = value.get("placed")
    raw_excluded = value.get("excluded")
    if not isinstance(raw_members, list) or any(not isinstance(item, str) for item in raw_members):
        raise ValueError("the placement member list is malformed")
    if not isinstance(raw_placed, list) or not isinstance(raw_excluded, list):
        raise ValueError("the placement outcomes are malformed")
    placed: list[PlacedPointMap] = []
    for raw in raw_placed:
        if not isinstance(raw, dict):
            raise ValueError("a placed member is malformed")
        matrix = _numbers(raw.get("scene_from_opm_row_major"), 16, "placement transform")
        scale = raw.get("local_units_to_scene_units")
        if isinstance(scale, bool) or not isinstance(scale, int | float):
            raise ValueError("placement scale must be numeric")
        if raw.get("scale_status") != "colmap-correspondence-fit":
            raise ValueError("the placement scale status is unsupported")
        if not isinstance(raw.get("alignment"), dict):
            raise ValueError("the placement alignment diagnostics are malformed")
        placed.append(
            PlacedPointMap(
                capture_ref=str(raw.get("capture_ref", "")),
                point_map_artifact_ref=str(raw.get("point_map_artifact_ref", "")),
                point_map_content_sha256=str(raw.get("point_map_content_sha256", "")),
                scene_from_opm=matrix,
                local_units_to_scene_units=float(scale),
                alignment=raw["alignment"],
            )
        )
    excluded: list[ExcludedPlacementMember] = []
    for raw in raw_excluded:
        if not isinstance(raw, dict) or raw.get("registered") not in (True, False):
            raise ValueError("an excluded member is malformed")
        reason = raw.get("reason")
        if reason not in (
            "pose-not-registered",
            "point-map-unavailable",
            "alignment-unavailable",
            "alignment-insufficient-correspondences",
            "alignment-inconsistent",
        ):
            raise ValueError("an excluded member has an unsupported reason")
        excluded.append(
            ExcludedPlacementMember(
                capture_ref=str(raw.get("capture_ref", "")),
                registered=raw["registered"],
                reason=reason,
                alignment=raw.get("alignment"),
            )
        )
    raw_inputs = value.get("point_map_inputs")
    if not isinstance(raw_inputs, list):
        raise ValueError("the placement point-map input bindings are malformed")
    inputs = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise ValueError("the placement point-map input binding is malformed")
        inputs.append(
            PointMapInput(
                str(item.get("capture_ref", "")),
                str(item.get("artifact_ref", "")),
                str(item.get("content_sha256", "")),
            )
        )
    record = PlacementRecord(
        scene_ref=str(value.get("scene_ref", "")),
        pose_receipt_sha256=str(value.get("pose_receipt_sha256", "")),
        pose_manifest_sha256=str(value.get("pose_manifest_sha256", "")),
        member_capture_refs=tuple(raw_members),
        placed=tuple(placed),
        excluded=tuple(excluded),
        input_sha256=str(value.get("input_sha256", "")),
        point_map_inputs=tuple(inputs),
    )
    _require_digest(record.pose_receipt_sha256, "pose receipt digest")
    _require_digest(record.pose_manifest_sha256, "pose manifest digest")
    _require_digest(record.input_sha256, "placement input digest")
    return record


def validate_placement_record(
    data: bytes,
    *,
    expected_scene_ref: str,
    pose_receipt: bytes,
    member_capture_refs: Sequence[str],
    point_maps: Mapping[str, PointMapInput],
    allow_unavailable_bytes: bool = False,
) -> PlacementRecord:
    """Refuse malformed, pose-inconsistent, digest-disagreeing or stale placement bytes."""
    try:
        envelope = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("the placement record is not JSON") from error
    if (
        not isinstance(envelope, dict)
        or envelope.get("profile") != "exulanica.posed-point-map-placement-envelope/v1"
    ):
        raise ValueError("the placement envelope version is unsupported")
    payload = envelope.get("placement")
    payload_digest = envelope.get("payload_sha256")
    if not isinstance(payload_digest, str) or _digest(_canonical(payload)) != payload_digest:
        raise ValueError("the placement payload disagrees with its digest")
    record = _record_from_payload(payload)
    if record.scene_ref != expected_scene_ref:
        raise ValueError("the placement names another scene")
    members = tuple(record.member_capture_refs)
    if not members or len(set(members)) != len(members):
        raise ValueError("the placement contains missing or duplicate members")
    outcomes = [member.capture_ref for member in record.placed] + [
        member.capture_ref for member in record.excluded
    ]
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(members):
        raise ValueError("every scene member needs exactly one placement outcome")
    for member in record.placed:
        _require_digest(member.point_map_content_sha256, "point-map content digest")
        _validate_matrix(member)

    expected = build_placement_record(
        scene_ref=expected_scene_ref,
        pose_receipt=pose_receipt,
        member_capture_refs=member_capture_refs,
        point_maps=point_maps,
    )
    comparison = payload
    if allow_unavailable_bytes:
        # Graph delivery may lose an object after publication. Revalidate every available
        # member and erase unavailable members' geometry before returning anything renderable.
        # Their exact artifact row/digest bindings and the complete outcome set still verify.
        unavailable = {key for key, item in point_maps.items() if item.content is None}
        if unavailable:
            comparison = dict(payload)
            comparison["placed"] = [
                item for item in payload["placed"] if item["capture_ref"] not in unavailable
            ]
            exclusions = {
                item["capture_ref"]: item
                for item in payload["excluded"]
                if item["capture_ref"] not in unavailable
            }
            exclusions.update(
                {
                    item.capture_ref: item.as_payload()
                    for item in expected.excluded
                    if item.capture_ref in unavailable
                }
            )
            comparison["excluded"] = [
                exclusions[key] for key in expected.member_capture_refs if key in exclusions
            ]
    if comparison != expected.payload():
        raise ValueError("the placement is inconsistent with its pose receipt or current inputs")
    return expected
