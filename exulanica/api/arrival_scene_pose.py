"""A scene's displayed region-local opening pose under the v1 presentation contract.

Only authenticated, digest-checked OPM bytes enter this reader. An absent member is omitted in
the same order as the browser geometry loader. Callers separately bind the scene to a retained
job and finish with the asset authorization check before serving a pin.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from exulanica.graph.payload import ReconstructionSceneMemberRow, ReconstructionSceneRow
from exulanica.reconstruction.validation import validate_opm
from exulanica.world.arrival_display_frame import (
    CameraSample,
    Vec3,
    colmap_camera_sample,
    opm_camera_sample,
    scene_display_frame,
    transformed_box_corners,
)


@dataclass(frozen=True, slots=True)
class _Map:
    viewpoint: Vec3
    bounds: tuple[Vec3, Vec3]
    fov_y: float
    aspect: float
    positions: tuple[Vec3, ...]


def _opm(data: bytes, *, positions: bool = False) -> _Map:
    validate_opm(data)
    header = json.loads(data[8 : 8 + int.from_bytes(data[4:8], "little")])
    points: tuple[Vec3, ...] = ()
    if positions:
        section = next(s for s in header["sections"] if s["name"] == "position")
        count = header["pointCount"]
        stride = max(1, count // 4096)
        points = tuple(
            struct.unpack_from("<fff", data, section["byteOffset"] + index * 12)
            for index in range(0, count, stride)
        )
    return _Map(
        tuple(header["viewpoint"]["position"]),
        (tuple(header["bounds"]["min"]), tuple(header["bounds"]["max"])),
        header["viewpoint"]["fovYDeg"],
        header["viewpoint"]["aspect"],
        points,
    )


def standalone_opm_footprint(data: bytes) -> float:
    """The legacy map sets island size; its opening still uses the fallback camera."""
    minimum, maximum = _opm(data).bounds
    return max(math.hypot(x, z) for x in (minimum[0], maximum[0]) for z in (minimum[2], maximum[2]))


def _point(matrix: Sequence[float], point: Vec3) -> Vec3:
    return tuple(
        sum(matrix[row * 4 + col] * point[col] for col in range(3)) + matrix[row * 4 + 3]
        for row in range(3)
    )  # type: ignore[return-value]


def _fan(maps: Sequence[_Map]) -> list[tuple[float, ...] | None]:
    widths = [
        math.degrees(2 * math.atan(math.tan(math.radians(value.fov_y) / 2) * value.aspect))
        for value in maps
    ]
    fitted = 0
    sweep = 0.0
    for width in widths:
        next_sweep = sweep + (6 if fitted else 0) + width
        if next_sweep > 330:
            break
        sweep = next_sweep
        fitted += 1
    offset = 0.0
    matrices: list[tuple[float, ...] | None] = []
    for index, value in enumerate(maps):
        if index >= fitted:
            matrices.append(None)
            continue
        width = widths[index]
        yaw = math.radians(sweep / 2 - offset - width / 2)
        offset += width + 6
        c, s = math.cos(yaw), math.sin(yaw)
        x, y, z = value.viewpoint
        matrices.append(
            (
                c,
                0,
                s,
                -(c * x + s * z),
                0,
                1,
                0,
                -y,
                -s,
                0,
                c,
                -(-s * x + c * z),
                0,
                0,
                0,
                1,
            )
        )
    return matrices


def scene_arrival_pose(
    scene: ReconstructionSceneRow,
    map_bytes: Callable[[str], bytes | None],
    trained_bytes: Callable[[str], bytes | None],
) -> tuple[Vec3, Vec3] | None:
    """Follow geometry-api.ts and reconstructionsOf for one chosen scene."""
    cameras = [
        colmap_camera_sample(member.recovered_camera.scene_from_camera_row_major)
        for member in scene.members
        if member.recovered_camera is not None
        and member.registered
        and scene.receipt_state == "available"
        and scene.pose_receipt_sha256 is not None
    ]
    placed: list[tuple[_Map, Sequence[float]]] = []
    for member in scene.members:
        placement = member.placement
        if placement is None or placement.state != "available" or placement.reference is None:
            continue
        if placement.container not in (None, "opm/2"):
            continue
        payload = map_bytes(str(placement.artifact_id))
        if payload is None:
            continue
        try:
            placed.append((_opm(payload), placement.scene_from_opm_row_major))
        except ValueError:
            continue

    joined = scene.standpoint is not None and scene.standpoint.state == "joined"
    standing = joined and not cameras
    if not any(member.placement is not None for member in scene.members):
        unposed: list[tuple[ReconstructionSceneMemberRow, _Map]] = []
        for member in sorted(scene.members, key=lambda value: value.ordinal):
            unposed_map = member.unposed_point_map
            if (
                unposed_map is None
                or unposed_map.state != "available"
                or unposed_map.reference is None
            ):
                continue
            if unposed_map.container not in (None, "opm/2"):
                continue
            payload = map_bytes(str(unposed_map.artifact_id))
            if payload is not None:
                try:
                    unposed.append((member, _opm(payload, positions=standing)))
                except ValueError:
                    continue
        fan = [] if joined else _fan([value for _, value in unposed])
        for index, (member, value) in enumerate(unposed):
            matrix = (
                (
                    None
                    if member.standpoint_placement is None
                    else member.standpoint_placement.scene_from_opm_row_major
                )
                if joined
                else fan[index]
            )
            if matrix is not None:
                placed.append((value, matrix))

    trained = scene.trained_geometry
    trained_drawn = (
        trained is not None
        and trained.state == "available"
        and trained.reference is not None
        and trained.container == "sog/1"
        and trained_bytes(str(trained.artifact_id)) is not None
    )
    samples: list[CameraSample] = cameras or [
        CameraSample(
            opm_camera_sample(matrix, value.viewpoint).position,
            opm_camera_sample(matrix, value.viewpoint).forward,
            (0, 1, 0) if standing else opm_camera_sample(matrix, value.viewpoint).up,
        )
        for value, matrix in placed
    ]
    corners = [
        point
        for value, matrix in placed
        for point in (
            [_point(matrix, sample) for sample in value.positions]
            if standing
            else transformed_box_corners(value.bounds, matrix)
        )
    ]
    if trained_drawn and trained is not None:
        corners.extend(
            transformed_box_corners(
                (tuple(trained.bounds["min"]), tuple(trained.bounds["max"])),
                trained.scene_from_asset_row_major,
            )
        )
    frame = scene_display_frame(samples, corners)
    if placed:
        value, matrix = placed[0]
        source = opm_camera_sample(matrix, value.viewpoint)
        return frame.point(source.position), frame.direction(source.forward)
    if trained_drawn and cameras:
        return frame.point(cameras[0].position), frame.direction(cameras[0].forward)
    return None
