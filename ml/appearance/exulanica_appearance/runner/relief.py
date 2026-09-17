"""Conditioning pictures from a texture set's own relief: the recipe's structure, never a photograph.

A published or draft procedural set holds its exact relief as a height map (the recipe's courses,
units, joints and chips, periodic by construction). Track A paints colour on that relief, so the
model is conditioned on pictures derived from it by fixed rules:

- ``depth``: the height map itself, high relief white, the convention depth controls read, since a
  raised brick face is nearer the camera than its recessed joint;
- ``edge``: white where the height changes by at least ``EDGE_STEP_LEVELS`` of the map's 255 to a
  neighbour on the torus, so joint and chip outlines are exact and wrap across the tile;
- ``gray``: the procedural base colour's Rec. 709 luminance, a named variant that also hands the
  model the recipe's colour layout.

Each picture is a function of the pinned container's bytes and these constants, and is named in a
generation record by its pixels' sha256 with the container's sha256 as its source.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = ["EDGE_STEP_LEVELS", "RELIEF_ENCODINGS", "relief_depth", "relief_edges", "relief_gray"]

#: 24 of 255 height levels: at the brick set's 12 mm range, a 1.1 mm step, which a joint arris makes
#: and a face's grain does not.
EDGE_STEP_LEVELS: Final = 24

RELIEF_ENCODINGS: Final = {
    "depth": {
        "name": "relief-height-v1",
        "reason": "the recipe's exact height map as grey, raised relief white, which is the near-is-white convention depth controls were trained on",
    },
    "edge": {
        "name": "relief-steps-v1",
        "reason": "white where height steps by 24 of 255 levels or more to a torus neighbour: the recipe's joint and chip outlines, exact and wrapping across the tile",
    },
    "gray": {
        "name": "procedural-luminance-v1",
        "reason": "the procedural base colour's Rec. 709 luminance, a named variant that hands the model the recipe's colour layout as well as its relief",
    },
}


def _rgb(grey: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return np.repeat(grey[..., None], 3, axis=-1)


def relief_depth(height: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return _rgb(np.ascontiguousarray(height[..., 0]))


def relief_edges(height: NDArray[np.uint8]) -> NDArray[np.uint8]:
    values = height[..., 0].astype(np.int16)
    step = np.zeros(values.shape, dtype=bool)
    for axis in (0, 1):
        difference = np.abs(np.roll(values, -1, axis=axis) - values)
        step |= difference >= EDGE_STEP_LEVELS
    return _rgb(np.where(step, 255, 0).astype(np.uint8))


def relief_gray(base_color: NDArray[np.uint8]) -> NDArray[np.uint8]:
    pixels = base_color.astype(np.float64)
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    return _rgb(np.rint(lum).astype(np.uint8))
