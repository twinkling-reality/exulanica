"""Do a picture's edges fall where the structure's edges are? Measured with no model.

A picture's edges are found by a fixed rule (Sobel gradient of luminance, thinned along the
gradient, kept above ``EDGE_STEP_LEVELS``) and compared with the structure's exact ``edges`` layer:

- **recall**: the share of exact geometry edge pixels with a picture edge within ``TOLERANCE_PX``.
  A frame that dissolves a kerb or a door reveal loses recall.
- **precision**: the share of picture edges within ``TOLERANCE_PX`` of a geometry edge. Texture
  (brick joints, paving) lowers it for any look, so it is compared before against after, never read
  alone.
- **interior edge density** per identity (``regions``): picture edges farther than
  ``TOLERANCE_PX`` from any geometry edge, over the pixels of that surface that are. A window
  painted onto a blank wall raises it.

The same rule measures the procedural look and every generated look, so the numbers compare.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "EDGE_STEP_LEVELS",
    "TOLERANCE_PX",
    "dilate",
    "edge_agreement",
    "image_edges",
    "luminance",
]

#: A step of 16 of 255 luminance levels across neighbouring pixels: plainly visible at 1440 by 900,
#: and above the procedural look's fine grain on flat render. Fixed, so every look is measured alike.
EDGE_STEP_LEVELS: Final = 16
#: Two pixels: the exact edge lies between two pixels, and a generated frame may shift a line by one.
TOLERANCE_PX: Final = 2


def luminance(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Rec. 709 weights over the stored sRGB bytes (not linear light): what a person sees as contrast."""
    pixels = rgb.astype(np.float64)
    return 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]


def image_edges(rgb: NDArray[np.uint8]) -> NDArray[np.bool_]:
    lum = np.pad(luminance(rgb), 1, mode="edge")
    gx = (
        (lum[:-2, 2:] - lum[:-2, :-2])
        + 2 * (lum[1:-1, 2:] - lum[1:-1, :-2])
        + (lum[2:, 2:] - lum[2:, :-2])
    ) / 4
    gy = (
        (lum[2:, :-2] - lum[:-2, :-2])
        + 2 * (lum[2:, 1:-1] - lum[:-2, 1:-1])
        + (lum[2:, 2:] - lum[:-2, 2:])
    ) / 4
    magnitude = np.hypot(gx, gy)
    padded = np.pad(magnitude, 1, mode="constant")
    centre = padded[1:-1, 1:-1]
    angle = np.mod(np.degrees(np.arctan2(gy, gx)), 180.0)
    horizontal = (angle < 22.5) | (angle >= 157.5)
    diagonal = (angle >= 22.5) & (angle < 67.5)
    vertical = (angle >= 67.5) & (angle < 112.5)
    anti = (angle >= 112.5) & (angle < 157.5)
    keep = np.zeros(magnitude.shape, dtype=bool)
    for mask, before, after in (
        (horizontal, padded[1:-1, :-2], padded[1:-1, 2:]),
        (vertical, padded[:-2, 1:-1], padded[2:, 1:-1]),
        (diagonal, padded[:-2, :-2], padded[2:, 2:]),
        (anti, padded[:-2, 2:], padded[2:, :-2]),
    ):
        keep |= mask & (centre >= before) & (centre > after)
    return keep & (magnitude >= EDGE_STEP_LEVELS)


def dilate(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
    """Chebyshev dilation by ``radius`` pixels, separable, with nothing beyond the border."""
    out = mask.copy()
    for axis in (0, 1):
        grown = out.copy()
        for shift in range(1, radius + 1):
            forward = np.zeros_like(out)
            backward = np.zeros_like(out)
            if axis == 0:
                forward[shift:] = out[:-shift]
                backward[:-shift] = out[shift:]
            else:
                forward[:, shift:] = out[:, :-shift]
                backward[:, :-shift] = out[:, shift:]
            grown |= forward | backward
        out = grown
    return out


def _ppm(numerator: int, denominator: int) -> int:
    return 0 if denominator == 0 else (numerator * 1_000_000 + denominator // 2) // denominator


def edge_agreement(detected: NDArray[np.bool_], exact_bits: NDArray[np.uint8]) -> dict[str, int]:
    """Recall, precision and their harmonic mean, in parts per million, the image border excluded."""
    inner = np.zeros(detected.shape, dtype=bool)
    inner[1:-1, 1:-1] = True
    exact = (exact_bits > 0) & inner
    found = detected & inner
    near_found = dilate(found, TOLERANCE_PX)
    near_exact = dilate(exact, TOLERANCE_PX)
    recalled = int((exact & near_found).sum())
    precise = int((found & near_exact).sum())
    recall = _ppm(recalled, int(exact.sum()))
    precision = _ppm(precise, int(found.sum()))
    f = (
        0
        if recall + precision == 0
        else (2 * recall * precision + (recall + precision) // 2) // (recall + precision)
    )
    return {
        "exact_edge_pixels": int(exact.sum()),
        "f_ppm": f,
        "picture_edge_pixels": int(found.sum()),
        "precision_ppm": precision,
        "recall_ppm": recall,
    }
