"""Integer value noise over axis grids: the only source of irregularity in a realized land.

Every value is an integer computed with integer arithmetic, so a land is the same in every process
and in every later replay. Lattice values are 16-bit, taken from SHA-256 of a seed and the lattice
point. Interpolation uses the quintic smoothstep in 16-bit fixed point.

Noise is always sampled on the world's own axes (east and north), never on rotated ones, so a
grid's x and y interpolation weights are computed once per column and once per row: a grid of
``n x m`` samples costs ``n + m`` weight computations and four lattice reads per sample. A point is
a one-by-one grid, the same code path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final

__all__ = ["ONE", "fbm_grid", "smooth", "value_grid"]

#: Fixed-point one.
ONE: Final = 1 << 16
_HALF: Final = 32_768


def smooth(t: int) -> int:
    """Smoothstep of ``t`` in fixed point, clamped to [0, ONE]."""
    t = max(0, min(ONE, t))
    return (3 * t * t * ONE - 2 * t * t * t) // (ONE * ONE)


_ONE_TO_THE_FOURTH: Final = ONE * ONE * ONE * ONE


def _fade(t: int) -> int:
    """Quintic smoothstep of ``t`` in [0, ONE), exact."""
    t3 = t * t * t
    return (6 * t3 * t * t - 15 * t3 * t * ONE + 10 * t3 * ONE * ONE) // _ONE_TO_THE_FOURTH


def _axis(values: Sequence[int], wavelength: int) -> list[tuple[int, int]]:
    out = []
    for value in values:
        cell, rest = divmod(value, wavelength)
        out.append((cell, _fade(rest * ONE // wavelength)))
    return out


def value_grid(seed: bytes, xs: Sequence[int], ys: Sequence[int], wavelength: int) -> list[int]:
    """Value noise in [-32768, 32767] at every (x, y) of the grid, rows of ``ys``, row-major."""
    lattice: dict[tuple[int, int], int] = {}

    def at(i: int, j: int) -> int:
        value = lattice.get((i, j))
        if value is None:
            digest = hashlib.sha256(
                seed + i.to_bytes(8, "little", signed=True) + j.to_bytes(8, "little", signed=True)
            ).digest()
            value = lattice[(i, j)] = int.from_bytes(digest[:2], "little")
        return value

    columns, rows = _axis(xs, wavelength), _axis(ys, wavelength)
    out = []
    for j, wy in rows:
        for i, wx in columns:
            a, b, c, d = at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1)
            ab = a * ONE + (b - a) * wx
            cd = c * ONE + (d - c) * wx
            out.append((ab * ONE + (cd - ab) * wy) // (ONE * ONE) - _HALF)
    return out


def fbm_grid(
    seed: bytes,
    xs: Sequence[int],
    ys: Sequence[int],
    wavelength: int,
    octaves: int,
    *,
    ridged: bool = False,
) -> list[int]:
    """Fractal sums of value noise. Plain: [-32768, 32767]. Ridged: [0, 32768], crests high.

    Each octave halves the amplitude (ridged: a little faster) and divides the wavelength by 2.03,
    offset so octaves never share a lattice. Ridged octaves weight each finer octave by the coarser
    crest beneath it, so crests stay sharp and flanks erode.
    """
    total = [0] * (len(xs) * len(ys))
    weight = [ONE] * len(total)
    norm, amplitude, length = 0, 1000, wavelength
    for octave in range(octaves):
        shifted_x = [x + octave * 7_919_000 for x in xs]
        shifted_y = [y - octave * 6_271_000 for y in ys]
        values = value_grid(seed + bytes([octave]), shifted_x, shifted_y, max(1, length))
        for k, value in enumerate(values):
            if ridged:
                crest = _HALF - abs(value)
                crest = crest * crest // _HALF * weight[k] // ONE
                weight[k] = min(ONE, crest * 2 * ONE // _HALF)
                total[k] += crest * amplitude
            else:
                total[k] += value * amplitude
        norm += amplitude
        amplitude = amplitude * 1000 // (2100 if ridged else 2000)
        length = length * 1000 // 2030
    return [value // norm for value in total]
