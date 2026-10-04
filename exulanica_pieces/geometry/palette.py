"""The nearest palette swatch to a model's colour, in OKLab (Björn Ottosson, 2020).

Distance in OKLab follows what a person sees better than distance in sRGB; a tie goes to the swatch
listed first.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from exulanica_pieces.canonical import Refused

__all__ = ["nearest_swatch"]


def _oklab(srgb8: np.ndarray) -> np.ndarray:
    """OKLab coordinates of 8-bit sRGB colours, shape (n, 3)."""
    v = srgb8.astype(np.float64) / 255.0
    linear = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    m1 = np.array(
        [
            [0.4122214708, 0.5363325363, 0.0514459929],
            [0.2119034982, 0.6806995451, 0.1073969566],
            [0.0883024619, 0.2817188376, 0.6299787005],
        ]
    )
    m2 = np.array(
        [
            [0.2104542553, 0.7936177850, -0.0040720468],
            [1.9779984951, -2.4285922050, 0.4505937099],
            [0.0259040371, 0.7827717662, -0.8086757660],
        ]
    )
    return np.cbrt(linear @ m1.T) @ m2.T


def nearest_swatch(colours: np.ndarray, palette: Sequence[Sequence[int]]) -> np.ndarray:
    """For each 8-bit sRGB colour (n, 3), the index of the nearest palette swatch in OKLab."""
    if len(palette) == 0:
        raise Refused("a palette holds at least one swatch")
    swatches = _oklab(np.asarray(palette, dtype=np.int64))
    points = _oklab(np.asarray(colours, dtype=np.int64).reshape(-1, 3))
    distances = ((points[:, None, :] - swatches[None, :, :]) ** 2).sum(axis=2)
    # argmin returns the first of equal minima: a tie goes to the swatch listed first.
    return np.argmin(distances, axis=1)
