"""Integer value noise over axis grids: the only source of irregularity in a realized land.

Every value is an integer computed with integer arithmetic, so a land is the same in every process
and in every later replay. Lattice values are 16-bit, taken from SHA-256 of a seed and the lattice
point. Interpolation uses the quintic smoothstep in 16-bit fixed point.

Noise is always sampled on the world's own axes (east and north), never on rotated ones, so a
grid's x and y interpolation weights are computed once per column and once per row: a grid of
``n x m`` samples costs ``n + m`` weight computations. Every row of samples between the same two
lattice rows shares its interpolation along x, so that is made once for the pair and each sample is
then one interpolation along y. A point is a one-by-one grid, the same code path.
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
_ONE_SQUARED: Final = ONE * ONE


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
    """Value noise in [-32768, 32767] at every (x, y) of the grid, rows of ``ys``, row-major.

    Between lattice points ``a`` and ``b`` along x and ``c`` and ``d`` the next lattice row up,
    a sample is ``ab + (cd - ab) * wy`` with ``ab = a + (b - a) * wx`` and ``cd = c + (d - c) * wx``
    in fixed point: ``ab`` and ``cd`` for every column are made once for the rows' lattice row and
    kept while the next row of samples lies between the same two."""
    columns, rows = _axis(xs, wavelength), _axis(ys, wavelength)
    cells = {i for i, _ in columns} | {i + 1 for i, _ in columns}
    lattice: dict[int, dict[int, int]] = {}

    def lattice_row(j: int) -> dict[int, int]:
        """The 16-bit lattice values of row ``j`` at every cell the columns read."""
        row = lattice.get(j)
        if row is None:
            tail = j.to_bytes(8, "little", signed=True)
            row = lattice[j] = {
                i: int.from_bytes(
                    hashlib.sha256(seed + i.to_bytes(8, "little", signed=True) + tail).digest()[:2],
                    "little",
                )
                for i in cells
            }
        return row

    out: list[int] = []
    across: tuple[int, list[int], list[int]] | None = None
    for j, wy in rows:
        if across is None or across[0] != j:
            low, high = lattice_row(j), lattice_row(j + 1)
            across = (
                j,
                [low[i] * ONE + (low[i + 1] - low[i]) * wx for i, wx in columns],
                [high[i] * ONE + (high[i + 1] - high[i]) * wx for i, wx in columns],
            )
        _, ab, cd = across
        out.extend(
            [(a * ONE + (c - a) * wy) // _ONE_SQUARED - _HALF for a, c in zip(ab, cd, strict=True)]
        )
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
        if ridged:
            crests = [
                (low := _HALF - abs(value)) * low // _HALF * held // ONE
                for value, held in zip(values, weight, strict=True)
            ]
            weight = [min(ONE, crest * 2 * ONE // _HALF) for crest in crests]
            total = [sum_ + crest * amplitude for sum_, crest in zip(total, crests, strict=True)]
        else:
            total = [sum_ + value * amplitude for sum_, value in zip(total, values, strict=True)]
        norm += amplitude
        amplitude = amplitude * 1000 // (2100 if ridged else 2000)
        length = length * 1000 // 2030
    return [value // norm for value in total]
