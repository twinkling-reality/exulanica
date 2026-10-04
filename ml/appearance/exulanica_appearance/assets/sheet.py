"""A contact sheet of pieces, each seen from four sides, for a person to judge.

The pieces are read back from their GLB files (this writer's own layout: one primitive, float
positions and normals, ``COLOR_0`` as the table's 16-bit linear values) and drawn by a small
depth-buffered rasteriser in numpy with one sun and a sky term, so no renderer and no renderer
licence enters. It shows shape, proportion and palette; it is not the page's renderer and says
nothing about how the page will light a piece.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

__all__ = ["draw_sheet", "read_piece"]

_VIEW = 240
_SUN = np.array([0.45, 0.8, 0.4]) / np.linalg.norm([0.45, 0.8, 0.4])
_BACKGROUND = (226, 228, 232)


def read_piece(glb: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Positions (n, 3), linear colours in 0..1 (n, 3) and triangles (m, 3) of one written piece."""
    json_length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + json_length])
    binary = glb[20 + json_length + 8 :]
    attributes = document["meshes"][0]["primitives"][0]
    accessors = document["accessors"]

    def array(index: int, dtype: str, width: int) -> np.ndarray:
        accessor = accessors[index]
        view = document["bufferViews"][accessor["bufferView"]]
        return np.frombuffer(
            binary, dtype=dtype, count=accessor["count"] * width, offset=view["byteOffset"]
        ).reshape(-1, width)

    positions = array(attributes["attributes"]["POSITION"], "<f4", 3).astype(np.float64)
    colours = array(attributes["attributes"]["COLOR_0"], "<u2", 4)[:, :3].astype(np.float64) / 65535
    index_type = "<u2" if accessors[attributes["indices"]]["componentType"] == 5123 else "<u4"
    triangles = array(attributes["indices"], index_type, 1).reshape(-1, 3).astype(np.int64)
    return positions, colours, triangles


def _to_srgb8(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0, 1)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.rint(srgb * 255).astype(np.uint8)


def _draw(
    positions: np.ndarray, colours: np.ndarray, triangles: np.ndarray, yaw_degrees: float
) -> Image.Image:
    yaw = np.radians(yaw_degrees)
    # Positive pitch tips the view so the camera looks down from 20 degrees above the horizon.
    pitch = np.radians(20)
    rotate_y = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
    rotate_x = np.array(
        [[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]]
    )
    view = positions @ (rotate_x @ rotate_y).T
    low, high = view.min(axis=0), view.max(axis=0)
    scale = 0.86 * _VIEW / max(high[0] - low[0], high[1] - low[1])
    centre = (low + high) / 2
    screen = np.empty_like(view)
    screen[:, 0] = (view[:, 0] - centre[0]) * scale + _VIEW / 2
    screen[:, 1] = _VIEW / 2 - (view[:, 1] - centre[1]) * scale
    screen[:, 2] = view[:, 2]
    world_normals = np.cross(
        positions[triangles[:, 1]] - positions[triangles[:, 0]],
        positions[triangles[:, 2]] - positions[triangles[:, 0]],
    )
    world_normals /= np.maximum(np.linalg.norm(world_normals, axis=1, keepdims=True), 1e-12)
    light = 0.35 + 0.65 * np.clip(world_normals @ _SUN, 0, 1)
    shade = colours[triangles].mean(axis=1) * light[:, None]
    image = np.tile(np.array(_BACKGROUND, dtype=np.uint8), (_VIEW, _VIEW, 1))
    depth = np.full((_VIEW, _VIEW), -np.inf)
    rgb = _to_srgb8(shade)
    for number, triangle in enumerate(triangles):
        a, b, c = screen[triangle]
        x0 = max(int(np.floor(min(a[0], b[0], c[0]))), 0)
        x1 = min(int(np.ceil(max(a[0], b[0], c[0]))), _VIEW - 1)
        y0 = max(int(np.floor(min(a[1], b[1], c[1]))), 0)
        y1 = min(int(np.ceil(max(a[1], b[1], c[1]))), _VIEW - 1)
        if x1 < x0 or y1 < y0:
            continue
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(area) < 1e-9:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((b[0] - xs) * (c[1] - ys) - (b[1] - ys) * (c[0] - xs)) / area
        w1 = ((c[0] - xs) * (a[1] - ys) - (c[1] - ys) * (a[0] - xs)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        z = w0 * a[2] + w1 * b[2] + w2 * c[2]
        region = depth[y0 : y1 + 1, x0 : x1 + 1]
        nearer = inside & (z > region)
        region[nearer] = z[nearer]
        image[y0 : y1 + 1, x0 : x1 + 1][nearer] = rgb[number]
    return Image.fromarray(image)


def draw_sheet(pieces: Sequence[tuple[str, bytes]], out: Path) -> None:
    """One row per piece: its label, then front, right, back and left at a three-quarter height."""
    label_width = 220
    sheet = Image.new(
        "RGB", (label_width + 4 * _VIEW, max(len(pieces), 1) * _VIEW), (255, 255, 255)
    )
    pen = ImageDraw.Draw(sheet)
    for row, (label, glb) in enumerate(pieces):
        positions, colours, triangles = read_piece(glb)
        for column, yaw in enumerate((30, 120, 210, 300)):
            sheet.paste(
                _draw(positions, colours, triangles, yaw),
                (label_width + column * _VIEW, row * _VIEW),
            )
        for line, text in enumerate(label.split("\n")):
            pen.text((10, row * _VIEW + 12 + 16 * line), text, fill=(20, 20, 20))
    sheet.save(out)
