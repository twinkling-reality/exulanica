"""What each surface looks like in a picture, measured per identity with no model.

For every identity the structure names, over the pixels the structure says show it: how many there
are, the mean colour, the spread of luminance (a flat colour reads near 0, lived-in grime and
texture above it), and the density of picture edges away from any geometry edge (see ``edges``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.metrics.edges import TOLERANCE_PX, dilate, luminance

__all__ = ["region_measurements"]


def region_measurements(
    rgb: NDArray[np.uint8],
    identity: NDArray[np.uint16],
    exact_bits: NDArray[np.uint8],
    detected: NDArray[np.bool_],
    legend: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    lum = luminance(rgb)
    away = ~dilate(exact_bits > 0, TOLERANCE_PX)
    out = []
    for entry in legend:
        mask = identity == entry["identity"]
        count = int(mask.sum())
        if count == 0:
            continue
        interior = mask & away
        interior_count = int(interior.sum())
        colour = rgb[mask].astype(np.float64).mean(axis=0)
        out.append(
            {
                "identity": entry["identity"],
                "interior_edge_ppm": 0
                if interior_count == 0
                else (int((detected & interior).sum()) * 1_000_000 + interior_count // 2)
                // interior_count,
                "luminance_spread_milli": int(np.rint(lum[mask].std() * 1000)),
                "mean_rgb_milli": [int(np.rint(value * 1000)) for value in colour],
                "pixels": count,
                "surface": entry["surface"],
            }
        )
    return out
