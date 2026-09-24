"""Photographs of one procedural room with exact depth, for the standpoint join's tests.

A box room with boxes in it, ray-cast in numpy: every pixel's colour is a function of the 3D point
its ray hits, so two photographs of the same point agree wherever their cameras stand, and the
parallax between cameras that moved is real parallax. Texture is voxel noise at two cell sizes,
which gives COLMAP's SIFT corners to find. Each photograph also yields the depth-model estimate
the depth stage would have made of it, encoded by the depth stage's own ``encode_point_map`` from
an exact prediction, so the join reads the same container it reads in production.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import numpy as np
from exulanica.ingest.stages import stage
from exulanica.ingest.stages.depth import encode_point_map
from exulanica.reconstruction.depth import DepthPrediction
from PIL import Image

#: A photograph's size. Small, so a test renders in milliseconds, and still big enough for SIFT.
WIDTH = 320
HEIGHT = 240
#: Eye height of the standpoint, metres, inside a room whose floor is at y = 0.
EYE = (0.0, 1.6, 0.0)


@dataclass(frozen=True)
class Box:
    low: tuple[float, float, float]
    high: tuple[float, float, float]
    tint: tuple[float, float, float]


@dataclass(frozen=True)
class Room:
    """The room's inside faces and the boxes standing in it. +Y up, metres."""

    low: tuple[float, float, float] = (-4.0, 0.0, -5.0)
    high: tuple[float, float, float] = (4.0, 3.0, 5.0)
    boxes: tuple[Box, ...] = field(
        default=(
            Box((-1.6, 0.0, -3.4), (-0.6, 1.1, -2.6), (0.9, 0.6, 0.5)),
            Box((0.8, 0.0, -2.8), (1.6, 0.8, -2.1), (0.5, 0.8, 0.6)),
            Box((2.4, 0.0, -1.2), (3.2, 1.6, 0.2), (0.6, 0.6, 0.9)),
            Box((-3.5, 0.0, 0.5), (-2.6, 2.0, 1.8), (0.8, 0.8, 0.5)),
        )
    )


@dataclass(frozen=True)
class Camera:
    """A pinhole camera: where it stands, which way it faces, and its vertical field of view."""

    yaw_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    position: tuple[float, float, float] = EYE
    fov_y_deg: float = 60.0

    @property
    def rotation(self) -> np.ndarray:
        """World from camera, OPM axes: the camera looks down its own -Z with +Y up."""
        yaw, pitch, roll = (math.radians(v) for v in (self.yaw_deg, self.pitch_deg, self.roll_deg))
        ry = np.array(
            [[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]]
        )
        rx = np.array(
            [
                [1, 0, 0],
                [0, math.cos(pitch), -math.sin(pitch)],
                [0, math.sin(pitch), math.cos(pitch)],
            ]
        )
        rz = np.array(
            [[math.cos(roll), -math.sin(roll), 0], [math.sin(roll), math.cos(roll), 0], [0, 0, 1]]
        )
        return ry @ rx @ rz

    @property
    def focal(self) -> float:
        return (HEIGHT / 2) / math.tan(math.radians(self.fov_y_deg) / 2)


def _noise(points: np.ndarray, cell: float) -> np.ndarray:
    """A grey level per voxel of ``cell`` metres, from an integer hash of its coordinates."""
    index = np.floor(points / cell).astype(np.int64)
    h = index[:, 0] * 73856093 ^ index[:, 1] * 19349663 ^ index[:, 2] * 83492791
    h = (h ^ (h >> 13)) * 1274126177
    return ((h >> 8) & 0xFF).astype(np.float64) / 255.0


def render(room: Room, camera: Camera) -> tuple[np.ndarray, np.ndarray]:
    """``(rgb, ranges)``: the photograph, and each pixel's distance from the camera centre."""
    columns, rows = np.meshgrid(np.arange(WIDTH) + 0.5, np.arange(HEIGHT) + 0.5)
    rays = np.stack(
        [
            (columns - WIDTH / 2) / camera.focal,
            -(rows - HEIGHT / 2) / camera.focal,
            -np.ones_like(columns),
        ],
        -1,
    ).reshape(-1, 3)
    rays /= np.linalg.norm(rays, axis=1, keepdims=True)
    directions = rays @ camera.rotation.T
    origin = np.array(camera.position)
    with np.errstate(divide="ignore", invalid="ignore"):
        inverse = 1.0 / directions
        # Inside the room: the nearest wall is the smallest positive exit distance.
        low = (np.array(room.low) - origin) * inverse
        high = (np.array(room.high) - origin) * inverse
        exits = np.max(np.stack([low, high]), axis=0)
        distance = np.min(np.where(exits > 0, exits, np.inf), axis=1)
        normal_axis = np.argmin(np.where(exits > 0, exits, np.inf), axis=1)
        tint = np.tile(np.array([0.85, 0.82, 0.78]), (len(rays), 1))
        for box in room.boxes:
            near = (np.array(box.low) - origin) * inverse
            far = (np.array(box.high) - origin) * inverse
            enter = np.max(np.minimum(near, far), axis=1)
            leave = np.min(np.maximum(near, far), axis=1)
            hit = (enter <= leave) & (enter > 1e-6) & (enter < distance)
            distance = np.where(hit, enter, distance)
            normal_axis = np.where(hit, np.argmax(np.minimum(near, far), axis=1), normal_axis)
            tint[hit] = box.tint
    points = origin + directions * distance[:, None]
    grey = 0.55 * _noise(points, 0.21) + 0.45 * _noise(points + 0.37, 0.061)
    shade = np.array([0.72, 1.0, 0.85])[normal_axis]
    rgb = np.clip(tint * (0.25 + 0.75 * grey)[:, None] * shade[:, None], 0, 1)
    image = (rgb.reshape(HEIGHT, WIDTH, 3) * 255).round().astype(np.uint8)
    return image, distance.reshape(HEIGHT, WIDTH)


class ExactDepth:
    """A depth model that returns the room's true geometry, with a field of view it is told."""

    def __init__(self, ranges: np.ndarray, fov_y_deg: float) -> None:
        self._ranges = ranges
        self._fov = fov_y_deg

    @property
    def model_id(self) -> str:
        return "standpoint-test/exact-depth@" + "0" * 40

    def predict(self, image: Image.Image) -> DepthPrediction:
        focal = (HEIGHT / 2) / math.tan(math.radians(self._fov) / 2)
        columns, rows = np.meshgrid(np.arange(WIDTH) + 0.5, np.arange(HEIGHT) + 0.5)
        rays = np.stack(
            [(columns - WIDTH / 2) / focal, -(rows - HEIGHT / 2) / focal, -np.ones_like(columns)],
            -1,
        )
        rays /= np.linalg.norm(rays, axis=2, keepdims=True)
        points = rays * self._ranges[..., None]
        return DepthPrediction(
            width=WIDTH,
            height=HEIGHT,
            points=points.reshape(-1).astype(np.float64).tolist(),
            valid=bytes([1]) * (WIDTH * HEIGHT),
            fov_y_degrees=self._fov,
            metric=True,
            model_id=self.model_id,
        )


def photograph(
    room: Room, camera: Camera, *, estimated_fov_y_deg: float | None = None
) -> tuple[Image.Image, bytes]:
    """One photograph and the point map the depth stage would make of it.

    ``estimated_fov_y_deg`` is the field of view the depth model is taken to have estimated; by
    default the true one. The depth itself is exact either way, so what a wrong estimate changes is
    only the sideways extent of the unprojected points, which is what EXIF corrects.
    """
    rgb, ranges = render(room, camera)
    image = Image.fromarray(rgb)
    fov = camera.fov_y_deg if estimated_fov_y_deg is None else estimated_fov_y_deg
    _prediction, _decision, payload = encode_point_map(
        ExactDepth(ranges, fov), image, stage("depth")
    )
    return image, payload


def jpeg_bytes(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=95)
    return out.getvalue()


def fov_y_for_focal_35mm(focal_mm: float) -> float:
    """The vertical field of view at which this module's photographs state exactly ``focal_mm``.

    EXIF holds FocalLengthIn35mmFilm in whole millimetres, so a camera meant to state its focal
    length without rounding is built at one of these.
    """
    half_diagonal_px = math.hypot(WIDTH, HEIGHT) / 2
    focal_px = focal_mm * half_diagonal_px / (math.hypot(36.0, 24.0) / 2)
    return math.degrees(2 * math.atan((HEIGHT / 2) / focal_px))


def focal_35mm(camera: Camera) -> float:
    """The FocalLengthIn35mmFilm a phone would write for this camera."""
    half_diagonal_px = math.hypot(WIDTH, HEIGHT) / 2
    return math.hypot(36.0, 24.0) / 2 * camera.focal / half_diagonal_px
