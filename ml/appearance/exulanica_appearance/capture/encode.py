"""Conditioning pictures derived from exact structure layers.

A structure-conditioned model is given pictures, not layers. Each encoding here is a fixed function
of one structure record's layers plus the constants below, and a generation record names each
picture by the sha256 of its raw RGB bytes and of the file the model read, with these constants
and their reasons. PNG is written for the model and for people; its bytes depend on the deflate
build, so a picture's identity is its raw pixels.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from exulanica_appearance.capture.raster import NORMAL_SCALE, Camera

__all__ = [
    "ENCODINGS",
    "depth_range",
    "edge_lines",
    "identity_colours",
    "inverse_depth",
    "normal_camera",
    "write_png",
]

ENCODINGS: Final = {
    "depth": {
        "name": "inverse-depth-v2",
        "reason": "inverse depth normalised between the nearest and farthest hit over the frames "
        "conditioned together (one pose, or every frame of a camera path), near white and far "
        "black: the relative disparity depth controls were trained on, with one range for a whole "
        "path so its frames do not flicker",
    },
    "segmentation": {
        "name": "identity-hue-v1",
        "reason": "one flat, fully saturated colour per surface identity, hues stepped by the golden "
        "angle from the identity's index so neighbouring identities never share a hue; Cosmos trained "
        "on arbitrary per-object colours, so a colour carries no meaning and the material is named in "
        "the prompt",
    },
    "edge": {
        "name": "geometry-edges-v1",
        "reason": "white where the structure's edges layer marks any bit, on black: exact "
        "geometry edges, never a Canny pass over a render, which would copy the procedural "
        "texture's joints into the structure",
    },
    "normal": {
        "name": "camera-normal-v1",
        "reason": "the world normal in camera axes (x right, y up, z toward the camera) mapped "
        "from -1..1 to 0..255, the convention normal controls read; black where nothing is hit",
    },
}


def depth_range(depths: Sequence[NDArray[np.uint32]]) -> tuple[int, int]:
    """The nearest and farthest hit, in micrometres, over frames conditioned together."""
    hits = [depth[depth > 0] for depth in depths]
    hits = [h for h in hits if h.size]
    if not hits:
        return 1, 2
    return int(min(h.min() for h in hits)), int(max(h.max() for h in hits))


def inverse_depth(depth_um: NDArray[np.uint32], near_um: int, far_um: int) -> NDArray[np.uint8]:
    found = depth_um > 0
    inverse = np.divide(1.0, depth_um.astype(np.float64), out=np.zeros(depth_um.shape), where=found)
    low = 1.0 / far_um
    high = 1.0 / near_um
    value = (
        np.clip((inverse - low) / (high - low), 0.0, 1.0) if high > low else np.ones(depth_um.shape)
    )
    grey = np.where(found, np.rint(value * 255), 0).astype(np.uint8)
    return np.repeat(grey[..., None], 3, axis=-1)


def _hue(index: int) -> tuple[int, int, int]:
    """Fully saturated, full value, hue = index times the golden angle (137.5 degrees)."""
    hue = (index * 137.50776405003785) % 360.0
    sector = int(hue // 60)
    fraction = hue / 60 - sector
    rising = round(255 * fraction)
    falling = 255 - rising
    return [
        (255, rising, 0),
        (falling, 255, 0),
        (0, 255, rising),
        (0, falling, 255),
        (rising, 0, 255),
        (255, 0, falling),
    ][sector % 6]


def identity_colours(identity: NDArray[np.uint16], count: int) -> NDArray[np.uint8]:
    palette = np.zeros((count + 1, 3), dtype=np.uint8)
    for index in range(1, count + 1):
        palette[index] = _hue(index)
    return palette[identity]


def edge_lines(edges: NDArray[np.uint8]) -> NDArray[np.uint8]:
    white = np.where(edges > 0, 255, 0).astype(np.uint8)
    return np.repeat(white[..., None], 3, axis=-1)


def normal_camera(normal: NDArray[np.int16], camera: Camera) -> NDArray[np.uint8]:
    right, up, forward = camera.basis()
    n = normal.astype(np.float64) / NORMAL_SCALE
    found = np.any(normal != 0, axis=-1)
    axes = (right, up, -forward)
    out = np.zeros(normal.shape, dtype=np.uint8)
    for index, axis in enumerate(axes):
        component = n[..., 0] * axis[0] + n[..., 1] * axis[1] + n[..., 2] * axis[2]
        out[..., index] = np.where(found, np.rint((component * 0.5 + 0.5) * 255), 0).astype(
            np.uint8
        )
    return out


def write_png(path: Path, pixels: NDArray[np.uint8]) -> tuple[str, str]:
    """Write ``pixels`` as a PNG; return the sha256 of the raw RGB bytes and of the file."""
    raw = np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, mode="RGB").save(path, format="PNG")
    return hashlib.sha256(raw).hexdigest(), hashlib.sha256(path.read_bytes()).hexdigest()
