"""The v1 arrival projection of a reconstructed camera into its displayed region frame.

This is the presentation similarity in atlas-core/display-frame.ts. It does not place regions
in the Atlas or assign metric meaning to reconstruction units. The server needs the resulting
region-local pose to keep a saved society's clearance aligned with its first frame.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class CameraSample:
    position: Vec3
    forward: Vec3
    up: Vec3


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    rotation: tuple[float, ...]
    scale: float
    translation: Vec3

    def point(self, value: Vec3) -> Vec3:
        turned = _rotate(self.rotation, value)
        return tuple(self.scale * turned[i] + self.translation[i] for i in range(3))  # type: ignore[return-value]

    def direction(self, value: Vec3) -> Vec3:
        return _unit(_rotate(self.rotation, value))


IDENTITY = DisplayFrame((1, 0, 0, 0, 1, 0, 0, 0, 1), 1, (0, 0, 0))


def _length(value: Vec3) -> float:
    return math.hypot(*value)


def _unit(value: Vec3) -> Vec3:
    length = _length(value)
    return (0, 0, 0) if length < 1e-12 else tuple(v / length for v in value)  # type: ignore[return-value]


def _mean(values: Sequence[Vec3]) -> Vec3:
    count = max(len(values), 1)
    return tuple(sum(value[i] for value in values) / count for i in range(3))  # type: ignore[return-value]


def _dot(left: Vec3, right: Vec3) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(left: Vec3, right: Vec3) -> Vec3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _rotate(matrix: Sequence[float], value: Vec3) -> Vec3:
    return tuple(sum(matrix[row * 3 + col] * value[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _rotation_to_up(up: Vec3) -> tuple[float, ...]:
    axis = _cross(up, (0, 1, 0))
    sine = _length(axis)
    cosine = up[1]
    if sine < 1e-9:
        return IDENTITY.rotation if cosine > 0 else (1, 0, 0, 0, -1, 0, 0, 0, -1)
    x, y, z = _unit(axis)
    t = 1 - cosine
    return (
        t * x * x + cosine,
        t * x * y - sine * z,
        t * x * z + sine * y,
        t * x * y + sine * z,
        t * y * y + cosine,
        t * y * z - sine * x,
        t * x * z - sine * y,
        t * y * z + sine * x,
        t * z * z + cosine,
    )


def _solve3(matrix: Sequence[float], right: Vec3) -> Vec3 | None:
    a = matrix
    det = (
        a[0] * (a[4] * a[8] - a[5] * a[7])
        - a[1] * (a[3] * a[8] - a[5] * a[6])
        + a[2] * (a[3] * a[7] - a[4] * a[6])
    )
    if not math.isfinite(det) or abs(det) < 1e-9:
        return None
    inverse = (
        (a[4] * a[8] - a[5] * a[7]) / det,
        (a[2] * a[7] - a[1] * a[8]) / det,
        (a[1] * a[5] - a[2] * a[4]) / det,
        (a[5] * a[6] - a[3] * a[8]) / det,
        (a[0] * a[8] - a[2] * a[6]) / det,
        (a[2] * a[3] - a[0] * a[5]) / det,
        (a[3] * a[7] - a[4] * a[6]) / det,
        (a[1] * a[6] - a[0] * a[7]) / det,
        (a[0] * a[4] - a[1] * a[3]) / det,
    )
    return _rotate(inverse, right)


def _convergence(cameras: Sequence[CameraSample]) -> Vec3:
    matrix = [0.0] * 9
    right = [0.0] * 3
    for camera in cameras:
        forward = _unit(camera.forward)
        projector = tuple(
            (1.0 if row == col else 0.0) - forward[row] * forward[col]
            for row in range(3)
            for col in range(3)
        )
        for index, value in enumerate(projector):
            matrix[index] += value
        projected = _rotate(projector, camera.position)
        for index, value in enumerate(projected):
            right[index] += value
    solved = _solve3(matrix, tuple(right))
    centroid = _mean([camera.position for camera in cameras])
    if solved is None:
        return centroid
    ahead = sum(
        _dot(_unit(camera.forward), tuple(solved[i] - camera.position[i] for i in range(3))) > 0
        for camera in cameras
    )
    return solved if ahead * 2 >= len(cameras) else centroid


def _quantile(values: Sequence[float], fraction: float) -> float:
    sorted_values = sorted(values)
    return (
        sorted_values[min(len(values) - 1, max(0, math.floor(fraction * (len(values) - 1))))]
        if values
        else 0
    )


def scene_display_frame(
    cameras: Sequence[CameraSample], bound_corners: Sequence[Vec3]
) -> DisplayFrame:
    """Match the browser's v1 similarity, including its degenerate-camera fallback."""
    if not cameras or not all(
        all(
            math.isfinite(v)
            for vector in (camera.position, camera.forward, camera.up)
            for v in vector
        )
        and _length(camera.forward) > 1e-9
        and _length(camera.up) > 1e-9
        for camera in cameras
    ):
        return IDENTITY
    mean_up = _mean([_unit(camera.up) for camera in cameras])
    mean_forward = _mean([_unit(camera.forward) for camera in cameras])
    if _length(mean_up) >= 0.5:
        up = _unit(mean_up)
    elif _length(mean_forward) >= 0.5:
        up = _unit(tuple(-v for v in mean_forward))
    else:
        up = (0, 1, 0)
    rotation = _rotation_to_up(up)
    focus = _rotate(rotation, _convergence(cameras))
    rotated_cameras = [_rotate(rotation, camera.position) for camera in cameras]
    corners = [
        _rotate(rotation, corner) for corner in bound_corners if all(map(math.isfinite, corner))
    ]
    heights = [point[1] for point in (corners or rotated_cameras)]
    ground = min(_quantile(heights, 0.05), focus[1])
    positive_heights = [point[1] - ground for point in rotated_cameras if point[1] - ground > 1e-9]
    median = _quantile(positive_heights, 0.5)
    scale = min(100, max(0.01, 1.6 / median)) if median > 0 else 1
    return DisplayFrame(rotation, scale, (-scale * focus[0], -scale * ground, -scale * focus[2]))


def colmap_camera_sample(matrix: Sequence[float]) -> CameraSample:
    return CameraSample(
        (matrix[3], matrix[7], matrix[11]),
        _unit((matrix[2], matrix[6], matrix[10])),
        _unit((-matrix[1], -matrix[5], -matrix[9])),
    )


def opm_camera_sample(matrix: Sequence[float], viewpoint: Vec3) -> CameraSample:
    x, y, z = viewpoint
    return CameraSample(
        tuple(
            sum(matrix[row * 4 + col] * value for col, value in enumerate((x, y, z)))
            + matrix[row * 4 + 3]
            for row in range(3)
        ),  # type: ignore[arg-type]
        _unit((-matrix[2], -matrix[6], -matrix[10])),
        _unit((matrix[1], matrix[5], matrix[9])),
    )


def transformed_box_corners(bounds: tuple[Vec3, Vec3], matrix: Sequence[float]) -> list[Vec3]:
    return [
        tuple(
            sum(matrix[row * 4 + col] * value for col, value in enumerate((x, y, z)))
            + matrix[row * 4 + 3]
            for row in range(3)
        )  # type: ignore[list-item]
        for x in (bounds[0][0], bounds[1][0])
        for y in (bounds[0][1], bounds[1][1])
        for z in (bounds[0][2], bounds[1][2])
    ]
