"""Pictures of a sculpted look for the people judging it: four sides at rest and two poses.

Drawn on the CPU by the creature route's own rasteriser, each triangle in its own colour, lit by one
light from above and in front plus a quarter of ambient, from both sides (a generated mesh's
winding is not trusted for this). A pose turns every limb chain about its first joint, the way the
deformation check does: a stride (legs and arms forward on one side and back on the other, by the
chain's order and side as the gait phases them, wings raised, the tail and neck swung a little)
and its opposite, moved by linear blending as the product's drawing will move them.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from typing import Any, Final

import numpy as np

from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, Camera, rasterise
from exulanica_appearance.creatures.rig import _rotation, linear_blend

__all__ = ["REST_YAWS", "pose", "render", "sheet_row", "views"]

#: The four sides a look is drawn from at rest: the control camera's yaw and every quarter turn.
REST_YAWS: Final = (-35.0, 55.0, 145.0, 235.0)
#: Degrees each chain turns in a stride: by role, positive forward or up.
_STRIDE: Final = {"leg": 25.0, "arm": 20.0, "wing": 35.0, "tail": 12.0, "neck": 8.0, "fin": 15.0}
_LIGHT: Final = np.array([-0.35, -0.45, 0.82]) / np.linalg.norm([-0.35, -0.45, 0.82])
_AMBIENT: Final = 0.25


def render(
    positions: np.ndarray,
    triangles: np.ndarray,
    colours: np.ndarray,
    camera: Camera,
    size: int,
    *,
    background: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    """A picture (size x size x 3, uint8) of triangles in their colours (T x 3, sRGB)."""
    corners = np.asarray(positions, dtype=np.float64)[np.asarray(triangles)]
    drawn = rasterise(corners, camera, size)
    normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(normal, axis=1)
    normal = normal / np.where(length > 0, length, 1.0)[:, None]
    shade = _AMBIENT + (1 - _AMBIENT) * np.abs(normal @ _LIGHT)
    picture = np.empty((size, size, 3), dtype=np.uint8)
    picture[...] = background
    shown = drawn.triangle >= 0
    lit = (
        np.asarray(colours, dtype=np.float64)[drawn.triangle[shown]]
        * shade[drawn.triangle[shown], None]
    )
    picture[shown] = np.clip(np.rint(lit), 0, 255).astype(np.uint8)
    return picture


def pose(
    positions: np.ndarray,
    indices: np.ndarray,
    weights: np.ndarray,
    bones: Sequence[str],
    parents: Mapping[str, str | None],
    joints: Mapping[str, np.ndarray],
    ends: Mapping[str, np.ndarray],
    chains: Sequence[Mapping[str, Any]],
    phase: int,
) -> np.ndarray:
    """The mesh in a stride (``phase`` 1) or its opposite (``phase`` -1)."""
    children: dict[str, list[str]] = {bone: [] for bone in bones}
    for bone in bones:
        parent = parents[bone]
        if parent is not None:
            children[parent].append(bone)
    transforms: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for chain in chains:
        degrees = _STRIDE.get(str(chain["role"]))
        if degrees is None:
            continue
        root = str(chain["bones"][0])
        if chain["role"] in ("leg", "arm"):
            # Alternate pairs, and the two sides of a pair against each other, as a gait does.
            sign = (1 if int(chain["order"]) % 2 == 0 else -1) * (
                -1 if chain["side"] == "right" else 1
            )
        else:
            sign = 1
        pivot = np.asarray(joints[root], dtype=np.float64)
        axis = np.cross(np.asarray(ends[root], dtype=np.float64) - pivot, [0.0, 0.0, 1.0])
        if np.linalg.norm(axis) < 1e-9:
            axis = np.array([1.0, 0.0, 0.0])
        rotation = _rotation(axis, degrees * sign * phase)
        stack = [root]
        while stack:
            bone = stack.pop()
            if bone in transforms:
                continue
            transforms[bone] = (rotation, pivot - rotation @ pivot)
            stack.extend(children[bone])
    return linear_blend(positions, indices, weights, bones, transforms)


def views(
    positions: np.ndarray,
    triangles: np.ndarray,
    colours: np.ndarray,
    posed: Sequence[np.ndarray],
    size: int,
) -> list[np.ndarray]:
    """Four rest views and one view of each pose, from the control camera's height."""
    pictures = [
        render(positions, triangles, colours, Camera(yaw, CONTROL_CAMERA.pitch_deg), size)
        for yaw in REST_YAWS
    ]
    pictures += [render(moved, triangles, colours, CONTROL_CAMERA, size) for moved in posed]
    return pictures


def sheet_row(pictures: Sequence[np.ndarray], label: str, size: int) -> bytes:
    """One row of a contact sheet: the pictures side by side at ``size`` px, the label above."""
    from PIL import Image, ImageDraw

    band = 18
    row = Image.new("RGB", (size * len(pictures), size + band), (255, 255, 255))
    for index, picture in enumerate(pictures):
        tile = (
            Image.fromarray(picture).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        )
        row.paste(tile, (index * size, band))
    ImageDraw.Draw(row).text((4, 3), label, fill=(0, 0, 0))
    buffer = io.BytesIO()
    row.save(buffer, format="PNG")
    return buffer.getvalue()
