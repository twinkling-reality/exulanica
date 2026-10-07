"""A sculpted look's own colours: what the model painted, cut to at most 64 swatches, one a triangle.

A creature carries its own colours, never a style pack's palette (packs dress look roles, not
bodies). Each triangle's colour is the mean of its three vertices' colours; the swatches are cut
from those means by median cut in sRGB: the box of colours with the widest channel range is split
at the median of that channel (the first such box and channel on a tie) until there are 64 boxes
or none can be split, and each swatch is its box's mean, rounded. A triangle then takes the swatch
nearest its mean in OKLab, as the generated pieces take theirs. Deterministic: the same colours
give the same swatches on any machine.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from exulanica_pieces.geometry.palette import nearest_swatch

__all__ = ["SWATCHES", "flat_colours", "swatches"]

SWATCHES: Final = 64


def swatches(colours: np.ndarray, count: int = SWATCHES) -> np.ndarray:
    """At most ``count`` swatches (K x 3, uint8) cut from ``colours`` (N x 3, 0 to 255)."""
    boxes = [np.asarray(colours, dtype=np.int64).reshape(-1, 3)]
    if len(boxes[0]) == 0:
        raise ValueError("no colours to cut swatches from")
    while len(boxes) < count:
        ranges = [
            int((box.max(axis=0) - box.min(axis=0)).max()) if len(box) > 1 else 0 for box in boxes
        ]
        widest = max(range(len(boxes)), key=lambda index: (ranges[index], -index))
        if ranges[widest] == 0:
            break
        box = boxes[widest]
        channel = int(np.argmax(box.max(axis=0) - box.min(axis=0)))
        order = np.argsort(box[:, channel], kind="stable")
        half = len(box) // 2
        boxes[widest : widest + 1] = [box[order[:half]], box[order[half:]]]
    return np.array([np.rint(box.mean(axis=0)) for box in boxes], dtype=np.uint8)


def flat_colours(
    colours: np.ndarray, triangles: np.ndarray, count: int = SWATCHES
) -> tuple[np.ndarray, np.ndarray]:
    """Each triangle's swatch (T x 3, uint8) and the swatches (K x 3), from vertex colours."""
    means = np.rint(np.asarray(colours, dtype=np.float64)[triangles].mean(axis=1)).astype(np.uint8)
    palette = swatches(means, count)
    return palette[nearest_swatch(means, palette.tolist())], palette
