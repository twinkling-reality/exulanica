"""How closely a model keeps the picture it was made from: its outline and its colour, measured.

The picture's cut-out is framed as the creature route's rasteriser frames a view: its outline's box
centred, the box's longer side filling the picture less a margin each side. The model is drawn by
that rasteriser with the same framing, turned about the vertical every ten degrees at three tilts,
and the three best turns are refined to the degree. At the best turn this records the outline
overlap (intersection over union, per mille) and, over the pixels both cover, the mean OKLab
distance between the picture's colour and the colour of the model's triangle drawn there (in
thousandths), with each one's mean colour.

A measurement for the record and for bars set on development rows, never a verdict by itself: the
picture is a perspective view and the model is drawn orthographically, so a perfect copy reads
below 1000, and the picture's colours carry its light where the model's triangles are unlit. A model
made from the picture faces whichever way the 3D model put it, so the turn is searched, not assumed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from exulanica_pieces.geometry.palette import _oklab

from exulanica_appearance.creatures.geometry import Camera, Drawn, rasterise

__all__ = ["MARGIN", "PITCHES", "SIZE", "Likeness", "framed_cutout", "likeness"]

#: The side of the compared views, pixels.
SIZE: Final = 160
#: The margin each side of a framed view, as a share of its side.
MARGIN: Final = 0.08
#: The tilts tried, degrees down from level.
PITCHES: Final = (5.0, 15.0, 25.0)
#: The turns tried first, degrees; the REFINED best are each refined to the degree within REFINE.
YAWS: Final = tuple(range(0, 360, 10))
REFINED: Final = 3
REFINE: Final = 5


@dataclass(frozen=True)
class Likeness:
    yaw_degrees: int
    pitch_degrees: int
    outline_overlap_per_mille: int
    #: None where the two outlines share no pixel.
    colour_difference_milli: int | None
    picture_mean_srgb: tuple[int, int, int] | None
    model_mean_srgb: tuple[int, int, int] | None


def framed_cutout(
    rgba: np.ndarray, size: int = SIZE, margin: float = MARGIN
) -> tuple[np.ndarray, np.ndarray]:
    """A cut-out's outline (alpha at least half) and its colours (size x size x 3), framed as the
    rasteriser frames a view. An empty cut-out gives an empty outline."""
    from PIL import Image

    rgba = np.asarray(rgba, dtype=np.uint8)
    shown = rgba[..., 3] >= 128
    rows, columns = np.flatnonzero(shown.any(axis=1)), np.flatnonzero(shown.any(axis=0))
    if not len(rows):
        return np.zeros((size, size), dtype=bool), np.zeros((size, size, 3), dtype=np.uint8)
    top, bottom, left, right = rows[0], rows[-1] + 1, columns[0], columns[-1] + 1
    side = max(bottom - top, right - left) / (1 - 2 * margin)
    middle_y, middle_x = (top + bottom) / 2, (left + right) / 2
    box = tuple(
        round(float(value))
        for value in (
            middle_x - side / 2,
            middle_y - side / 2,
            middle_x + side / 2,
            middle_y + side / 2,
        )
    )
    framed = np.asarray(
        Image.fromarray(rgba).crop(box).resize((size, size), Image.Resampling.BILINEAR)
    )
    return framed[..., 3] >= 128, framed[..., :3]


def _overlap(a: np.ndarray, b: np.ndarray) -> int:
    union = int((a | b).sum())
    return 0 if union == 0 else 1000 * int((a & b).sum()) // union


def likeness(
    positions: np.ndarray,
    triangles: np.ndarray,
    triangle_colours: np.ndarray,
    cutout_rgba: np.ndarray,
    *,
    size: int = SIZE,
    margin: float = MARGIN,
    pitches: Sequence[float] = PITCHES,
) -> Likeness:
    """A model (slot frame, z up; T triangles each with an sRGB colour) against its picture's
    cut-out (H x W x 4, uint8)."""
    corners = np.asarray(positions, dtype=np.float64)[np.asarray(triangles)]
    colours = np.asarray(triangle_colours, dtype=np.uint8)
    target, picture = framed_cutout(cutout_rgba, size, margin)

    def drawn(yaw: float, pitch: float) -> Drawn:
        return rasterise(corners, Camera(yaw, pitch), size, margin=margin)

    def score(yaw: float, pitch: float) -> int:
        return _overlap(drawn(yaw, pitch).mask, target)

    coarse = sorted(
        ((score(float(yaw), pitch), -yaw, pitch) for yaw in YAWS for pitch in pitches),
        reverse=True,
    )[:REFINED]
    best = max(
        (score(float((-negative + step) % 360), pitch), -((-negative + step) % 360), pitch)
        for _score, negative, pitch in coarse
        for step in range(-REFINE, REFINE + 1)
    )
    overlap, yaw, pitch = best[0], -best[1], best[2]
    view = drawn(float(yaw), pitch)
    both = view.mask & target
    if not both.any():
        return Likeness(int(yaw), round(float(pitch)), overlap, None, None, None)
    model = colours[view.triangle[both]]
    seen = picture[both]
    difference = float(np.linalg.norm(_oklab(model) - _oklab(seen), axis=1).mean())

    def mean(values: np.ndarray) -> tuple[int, int, int]:
        red, green, blue = (int(v) for v in np.rint(values.mean(axis=0)))
        return red, green, blue

    return Likeness(
        yaw_degrees=int(yaw),
        pitch_degrees=round(float(pitch)),
        outline_overlap_per_mille=overlap,
        colour_difference_milli=round(1000 * difference),
        picture_mean_srgb=mean(seen),
        model_mean_srgb=mean(model),
    )
