"""A stub model with no torch and no weights, for dry runs and tests of the whole pipeline.

It stands in for a model so the runner's bookkeeping runs end to end on the Mac: staged inputs,
weights verification, the tiling schedule, generation records, measurements and the results
manifest. It denoises a small latent grid, rolling it and the downsampled conditioning by the
tiling schedule's offset before each step and back after, then upsamples and smooths with the
neighbouring tile as padding. Its pictures are a stand-in, never a look, and prove nothing about
how a real model tiles: the seam check on real outputs does that.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.runner.tiling import roll_grid, shift_for_step, unroll_grid, wrap_crop

__all__ = ["StubBackend"]

TOKEN_PX = 16


def _smooth_zero_padded(grid: NDArray[np.float64]) -> NDArray[np.float64]:
    padded = np.pad(grid, [(1, 1), (1, 1), (0, 0)], mode="constant")
    total = np.zeros_like(grid)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            total += padded[dy : dy + grid.shape[0], dx : dx + grid.shape[1]]
    return total / 9


def _fit(pixels: NDArray[np.uint8], height: int, width: int) -> NDArray[np.uint8]:
    """The conditioning picture at the sampler's size, as the real pipelines' preprocessing does it."""
    if pixels.shape[0] == height and pixels.shape[1] == width:
        return pixels
    rows = np.minimum((np.arange(height) * pixels.shape[0]) // height, pixels.shape[0] - 1)
    columns = np.minimum((np.arange(width) * pixels.shape[1]) // width, pixels.shape[1] - 1)
    return np.ascontiguousarray(pixels[rows[:, None], columns[None, :]])


def _blur_zero_padded(image: NDArray[np.float64], size: int) -> NDArray[np.float64]:
    """A box blur of ``size`` pixels with zeros beyond the edges, separable, by cumulative sums."""
    out = image
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        # One leading zero for the prefix sum, then the kernel's reach on each side.
        pad[axis] = (size // 2 + 1, size - size // 2 - 1)
        summed = np.cumsum(np.pad(out, pad, mode="constant"), axis=axis)
        length = summed.shape[axis]
        upper = np.take(summed, range(size, length), axis=axis)
        lower = np.take(summed, range(length - size), axis=axis)
        out = (upper - lower) / size
    return out


class StubBackend:
    name = "stub"

    def __init__(self, candidate: Mapping[str, Any]) -> None:
        self.candidate = candidate

    def runtime(self) -> dict[str, Any]:
        return {
            "cuda": "none: stub backend",
            "driver": "none: stub backend",
            "hardware": "stub backend on the operator's Mac, no GPU",
            "libraries": [{"name": "numpy", "version": np.__version__}],
        }

    def generate(
        self, *, prompt: str, conditioning: NDArray[np.uint8], seed: int, sampler: Mapping[str, Any]
    ) -> NDArray[np.uint8]:
        width, height, steps = sampler["width"], sampler["height"], sampler["steps"]
        rows, columns = height // TOKEN_PX, width // TOKEN_PX
        rng = np.random.default_rng(
            seed ^ int.from_bytes(hashlib.sha256(prompt.encode("ascii")).digest()[:4], "big")
        )
        grid = rng.standard_normal((rows, columns, 3))
        fitted = _fit(conditioning, height, width)
        control = (
            fitted.astype(np.float64)
            .reshape(rows, TOKEN_PX, columns, TOKEN_PX, 3)
            .mean(axis=(1, 3))
            / 255
        )
        tiling = sampler["tiling"] != "none"
        for step in range(steps):
            shift = shift_for_step(seed, step, rows, columns) if tiling else (0, 0)
            rolled, rolled_control = roll_grid(grid, shift), roll_grid(control, shift)
            prediction = _smooth_zero_padded(rolled) * 0.9 + rolled_control * 0.1
            grid = unroll_grid(prediction, shift)
        upsampled = np.repeat(np.repeat(grid, TOKEN_PX, axis=0), TOKEN_PX, axis=1)
        margin = sampler["wrap_margin_px"]
        padded = np.pad(upsampled, [(margin, margin), (margin, margin), (0, 0)], mode="wrap")
        decoded = wrap_crop(_blur_zero_padded(padded, TOKEN_PX), margin)
        low, high = decoded.min(), decoded.max()
        shade = (decoded - low) / (high - low if high > low else 1)
        relief = fitted.astype(np.float64) / 255
        colour = np.array([150.0, 70.0, 50.0]) * (0.55 + 0.45 * shade) * (0.7 + 0.3 * relief)
        return np.clip(np.rint(colour), 0, 255).astype(np.uint8)
