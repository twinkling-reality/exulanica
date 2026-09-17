"""Tiling texture sets, measured with no model: seams, repetition, module periods, texel pitch, cost.

- **Seam ratio** per map and axis: the mean absolute difference across the wrap (last column to
  first, last row to first) over the mean of the two neighbour differences beside it (first to
  second, second-last to last). The neighbours sit at almost the same phase of any periodic
  pattern, so a smooth seamless tile reads about 1; a fine pattern crossing the wrap at its steepest
  can read up to about 2 (the eight published sets, seamless by construction, read 0.29 to 1.77 per
  map), and a tile painted with no wrap reads far above that. Compare against that range, never
  against 1 alone. Where the neighbours are exactly flat, a flat wrap reads 1 and a wrap that steps
  reads ``FLAT_STEP_SEAM_PPM``, so a step on a flat tile is a seam rather than nothing.
- **Low-frequency share**: the share of luminance variance at 4 cycles per tile or fewer. Large
  blotches are what the eye recognises when a tile repeats across a wide shopfront, so a higher
  share predicts visible repetition. The operator still looks at the 4 by 4 composites.
- **Dominant cycles** along u and v: the strongest period of the row-mean and column-mean profiles,
  in cycles per tile. For a set built on a module (brick courses, paving joints) it must equal the
  recipe's count, so a model that paints appearance on a recipe's relief can be held to it.
- **Texel pitch** in micrometres per texel, against the texture lane's resolution rule.
- **Decoded bytes**: what lane 16's binding uploads, RGBA8 with a full mip chain, per map.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.metrics.edges import luminance

__all__ = [
    "LOW_FREQUENCY_CYCLES",
    "decoded_bytes",
    "dominant_cycles",
    "low_frequency_share_ppm",
    "seam_ratio_ppm",
    "texel_pitch_um",
]

#: What a seam reads where the neighbours beside the wrap are exactly flat and the wrap is not: 1000.
FLAT_STEP_SEAM_PPM: Final = 1_000_000_000
#: Features a quarter of a tile or larger: at a 2 m tile, 500 mm blotches, which read across a street.
LOW_FREQUENCY_CYCLES: Final = 4


def seam_ratio_ppm(pixels: NDArray[np.uint8]) -> dict[str, int]:
    values = pixels.astype(np.int64)
    out = {}
    for axis, name in ((1, "u"), (0, "v")):
        first = values.take(0, axis=axis)
        second = values.take(1, axis=axis)
        before_last = values.take(-2, axis=axis)
        last = values.take(-1, axis=axis)
        beside = (np.abs(second - first).mean() + np.abs(last - before_last).mean()) / 2
        wrap = np.abs(first - last).mean()
        if beside > 0:
            out[name] = int(np.rint(wrap / beside * 1_000_000))
        else:
            # Flat beside the wrap: seamless if the wrap is flat too, and a stated 1000 if it steps.
            out[name] = 1_000_000 if wrap == 0 else FLAT_STEP_SEAM_PPM
    return out


def low_frequency_share_ppm(pixels: NDArray[np.uint8]) -> int:
    lum = (
        luminance(pixels)
        if pixels.ndim == 3 and pixels.shape[2] >= 3
        else pixels[..., 0].astype(np.float64)
    )
    centred = lum - lum.mean()
    power = np.abs(np.fft.fft2(centred)) ** 2
    ku = np.abs(np.fft.fftfreq(lum.shape[1]) * lum.shape[1])
    kv = np.abs(np.fft.fftfreq(lum.shape[0]) * lum.shape[0])
    low = (kv[:, None] <= LOW_FREQUENCY_CYCLES) & (ku[None, :] <= LOW_FREQUENCY_CYCLES)
    total = power.sum()
    return 0 if total == 0 else int(np.rint(power[low].sum() / total * 1_000_000))


def dominant_cycles(pixels: NDArray[np.uint8]) -> dict[str, int]:
    lum = (
        luminance(pixels)
        if pixels.ndim == 3 and pixels.shape[2] >= 3
        else pixels[..., 0].astype(np.float64)
    )
    out = {}
    for axis, name in ((0, "u"), (1, "v")):
        profile = lum.mean(axis=axis)
        spectrum = np.abs(np.fft.rfft(profile - profile.mean()))
        spectrum[0] = 0
        out[name] = int(np.argmax(spectrum))
    return out


def texel_pitch_um(extent_mm: int, texels: int) -> int:
    return (extent_mm * 1000 + texels // 2) // texels


def decoded_bytes(width: int, height: int, maps: int) -> int:
    total = 0
    w, h = width, height
    while True:
        total += 4 * w * h
        if w == 1 and h == 1:
            break
        w, h = max(1, w // 2), max(1, h // 2)
    return total * maps
