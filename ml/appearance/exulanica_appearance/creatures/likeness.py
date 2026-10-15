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

__all__ = [
    "MARGIN",
    "MATCH_BOUND",
    "MATCH_SPREAD",
    "PITCHES",
    "SIZE",
    "ColourMatch",
    "Likeness",
    "colour_match",
    "framed_cutout",
    "likeness",
    "match_to_picture",
    "oklab_to_srgb",
]

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
#: How far the colour match may move the model's mean colour, in OKLab units: lightness, then each
#: colour axis. A picture's colours carry its light and a model's are meant to be its own, so the
#: match brings the model toward the picture's overall colour without copying its shading; the
#: bound keeps a dark or tinted picture (a dusk scene, a coloured backdrop seen through a cut-out's
#: edge) from repainting the model.
MATCH_BOUND: Final = (0.25, 0.08, 0.08)
#: How far the match may stretch or squeeze the spread of a channel, either way.
MATCH_SPREAD: Final = 2.0


@dataclass(frozen=True)
class Likeness:
    yaw_degrees: int
    pitch_degrees: int
    outline_overlap_per_mille: int
    #: None where the two outlines share no pixel.
    colour_difference_milli: int | None
    picture_mean_srgb: tuple[int, int, int] | None
    model_mean_srgb: tuple[int, int, int] | None


@dataclass(frozen=True)
class ColourMatch:
    """A move of colours in OKLab, channel by channel: each value goes ``(v - centre) * scale +
    centre + shift``, with the model's own mean as the centre."""

    centre: tuple[float, float, float]
    scale: tuple[float, float, float]
    shift: tuple[float, float, float]

    def apply(self, srgb8: np.ndarray) -> np.ndarray:
        """Colours (N x 3, 8-bit sRGB) moved by the match, as 8-bit sRGB."""
        lab = _oklab(np.asarray(srgb8, dtype=np.uint8).reshape(-1, 3))
        centre = np.asarray(self.centre)
        moved = (lab - centre) * np.asarray(self.scale) + centre + np.asarray(self.shift)
        return oklab_to_srgb(moved).reshape(np.shape(srgb8))


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """8-bit sRGB of OKLab coordinates (N x 3), clipped to the sRGB gamut; the inverse of
    ``exulanica_pieces.geometry.palette._oklab`` (Ottosson's published inverse)."""
    lab = np.asarray(lab, dtype=np.float64)
    lms = (
        lab
        @ np.array(
            [
                [1.0, 1.0, 1.0],
                [0.3963377774, -0.1055613458, -0.0894841775],
                [0.2158037573, -0.0638541728, -1.2914855480],
            ]
        )
    ) ** 3
    linear = lms @ np.array(
        [
            [4.0767416621, -1.2684380046, -0.0041960863],
            [-3.3077115913, 2.6097574011, -0.7034186147],
            [0.2309699292, -0.3413193965, 1.7076147010],
        ]
    )
    linear = np.clip(linear, 0.0, 1.0)
    encoded = np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.clip(np.rint(encoded * 255.0), 0, 255).astype(np.uint8)


def colour_match(
    model_srgb: np.ndarray,
    picture_srgb: np.ndarray,
    *,
    bound: tuple[float, float, float] = MATCH_BOUND,
    spread: float = MATCH_SPREAD,
) -> ColourMatch:
    """The move that brings the model's colours (N x 3) toward the picture's at the same pixels:
    each OKLab channel's mean and spread matched, the mean's move held within ``bound`` and the
    spread's change within ``spread`` either way."""
    model = _oklab(np.asarray(model_srgb, dtype=np.uint8).reshape(-1, 3))
    picture = _oklab(np.asarray(picture_srgb, dtype=np.uint8).reshape(-1, 3))
    model_mean, picture_mean = model.mean(axis=0), picture.mean(axis=0)
    model_spread, picture_spread = model.std(axis=0), picture.std(axis=0)
    scale = np.where(
        model_spread > 1e-9,
        np.clip(picture_spread / np.maximum(model_spread, 1e-9), 1 / spread, spread),
        1.0,
    )
    shift = np.clip(picture_mean - model_mean, -np.asarray(bound), np.asarray(bound))
    return ColourMatch(
        centre=tuple(float(v) for v in model_mean),
        scale=tuple(float(v) for v in scale),
        shift=tuple(float(v) for v in shift),
    )


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


def _measure(
    positions: np.ndarray,
    triangles: np.ndarray,
    triangle_colours: np.ndarray,
    cutout_rgba: np.ndarray,
    *,
    size: int,
    margin: float,
    pitches: Sequence[float],
) -> tuple[Likeness, np.ndarray, np.ndarray]:
    """The likeness, and the model's and the picture's colours at the pixels both cover."""
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
        empty = np.zeros((0, 3), dtype=np.uint8)
        return Likeness(int(yaw), round(float(pitch)), overlap, None, None, None), empty, empty
    model = colours[view.triangle[both]]
    seen = picture[both]
    return _scored(int(yaw), round(float(pitch)), overlap, model, seen), model, seen


def _scored(yaw: int, pitch: int, overlap: int, model: np.ndarray, seen: np.ndarray) -> Likeness:
    difference = float(np.linalg.norm(_oklab(model) - _oklab(seen), axis=1).mean())

    def mean(values: np.ndarray) -> tuple[int, int, int]:
        red, green, blue = (int(v) for v in np.rint(values.mean(axis=0)))
        return red, green, blue

    return Likeness(
        yaw_degrees=yaw,
        pitch_degrees=pitch,
        outline_overlap_per_mille=overlap,
        colour_difference_milli=round(1000 * difference),
        picture_mean_srgb=mean(seen),
        model_mean_srgb=mean(model),
    )


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
    return _measure(
        positions,
        triangles,
        triangle_colours,
        cutout_rgba,
        size=size,
        margin=margin,
        pitches=pitches,
    )[0]


def match_to_picture(
    positions: np.ndarray,
    triangles: np.ndarray,
    triangle_colours: np.ndarray,
    cutout_rgba: np.ndarray,
    *,
    bound: tuple[float, float, float] = MATCH_BOUND,
    spread: float = MATCH_SPREAD,
) -> tuple[np.ndarray, ColourMatch | None, Likeness, Likeness]:
    """The model's triangle colours moved toward its picture's (:func:`colour_match`, from the
    pixels both cover at the best-matching view), the match, and the likeness before and after,
    the after measured at the same view. With no pixel in common, or when the match brings the
    colours no closer, the colours stay as they are and the match is None."""
    before, model, seen = _measure(
        positions,
        triangles,
        triangle_colours,
        cutout_rgba,
        size=SIZE,
        margin=MARGIN,
        pitches=PITCHES,
    )
    if not len(model):
        return np.asarray(triangle_colours, dtype=np.uint8), None, before, before
    match = colour_match(model, seen, bound=bound, spread=spread)
    after = _scored(
        before.yaw_degrees,
        before.pitch_degrees,
        before.outline_overlap_per_mille,
        match.apply(model),
        seen,
    )
    if after.colour_difference_milli is None or (
        before.colour_difference_milli is not None
        and after.colour_difference_milli >= before.colour_difference_milli
    ):
        # A match that brings the colours no closer (a model already its picture's colour, where
        # the round trip through OKLab only rounds) is not kept.
        return np.asarray(triangle_colours, dtype=np.uint8), None, before, before
    return match.apply(np.asarray(triangle_colours, dtype=np.uint8)), match, before, after
