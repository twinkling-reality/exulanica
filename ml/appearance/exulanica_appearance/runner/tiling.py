"""Seamless tiling for transformer image models, as a schedule anyone can recompute.

A transformer image model has no convolution padding to make periodic, so a tile it paints has a seam
wherever its token grid ends. The method here moves the seam every denoising step: before step ``i``
the latent grid, and the control latents with it, are rolled by an offset derived from the seed and
the step, the model predicts on the rolled grid, and the prediction is rolled back. No position is
the edge of the grid for more than one step, so nothing learns an edge there. The VAE, which is
convolutional, encodes and decodes with the input wrap-padded by ``WRAP_MARGIN_PX`` and the result
cropped, so its receptive field sees the neighbouring tile instead of zeros.

Offsets are whole tokens (a transformer patch), so every roll keeps patch alignment. The schedule is
pure arithmetic over sha256, so a generation record's seed and grid say exactly which offsets ran.
"""

from __future__ import annotations

import hashlib
from typing import Final

import numpy as np
from numpy.typing import NDArray

__all__ = ["WRAP_MARGIN_PX", "roll_grid", "shift_for_step", "unroll_grid", "wrap_crop", "wrap_pad"]

#: 64 px of the neighbouring tile on each side: eight latent pixels, more than the receptive field
#: a latent pixel's decode reaches in these VAEs' upsampling stages, and a whole number of tokens.
WRAP_MARGIN_PX: Final = 64


def shift_for_step(seed: int, step: int, rows: int, columns: int) -> tuple[int, int]:
    """The (row, column) roll in tokens before step ``step``, for a grid of ``rows`` by ``columns``."""
    digest = hashlib.sha256(
        f"exulanica.appearance-tiling/v1:{seed}:{step}".encode("ascii")
    ).digest()
    return int.from_bytes(digest[:4], "big") % rows, int.from_bytes(digest[4:8], "big") % columns


def roll_grid(grid: NDArray[np.generic], shift: tuple[int, int]) -> NDArray[np.generic]:
    """Roll the first two axes of a (rows, columns, ...) grid by ``shift``."""
    return np.roll(grid, shift, axis=(0, 1))


def unroll_grid(grid: NDArray[np.generic], shift: tuple[int, int]) -> NDArray[np.generic]:
    return np.roll(grid, (-shift[0], -shift[1]), axis=(0, 1))


def wrap_pad(image: NDArray[np.generic], margin: int) -> NDArray[np.generic]:
    """Pad the first two axes by ``margin`` with the opposite edges, as a torus would."""
    return np.pad(
        image, [(margin, margin), (margin, margin)] + [(0, 0)] * (image.ndim - 2), mode="wrap"
    )


def wrap_crop(image: NDArray[np.generic], margin: int) -> NDArray[np.generic]:
    return image[margin:-margin, margin:-margin] if margin else image
