"""Integer value noise in three dimensions: the weathering on a volume's faces.

The land's noise (:mod:`exulanica.grammar.landform.noise`) in one more axis, with the same
arithmetic. Lattice values are 16-bit, taken from SHA-256 of a seed, the octave and the lattice
point; interpolation is trilinear with the quintic smoothstep in 16-bit fixed point, and the one
division comes last, so a value is exact. Each octave halves the amplitude and divides the
wavelength by 2.03, and reads its own lattice (the octave is in the hash).

Noise is sampled on the volume's own axes, so a grid's interpolation weights are computed once per
coordinate of each axis (:meth:`Noise3.axis`) and a sample reads them; a point is a grid of one, the
same arithmetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final, TypeAlias

__all__ = ["HALF", "ONE", "AxisWeights", "Noise3"]

#: Fixed-point one.
ONE: Final = 1 << 16
#: Noise lies in [-HALF, HALF].
HALF: Final = 32_768
_ONE_TO_THE_FOURTH: Final = ONE * ONE * ONE * ONE
_ONE_CUBED: Final = ONE * ONE * ONE

#: One coordinate's lattice cell and weight at each octave.
AxisWeights: TypeAlias = tuple[tuple[int, int], ...]


def _fade(t: int) -> int:
    """Quintic smoothstep of ``t`` in [0, ONE), exact."""
    t3 = t * t * t
    return (6 * t3 * t * t - 15 * t3 * t * ONE + 10 * t3 * ONE * ONE) // _ONE_TO_THE_FOURTH


class Noise3:
    """Fractal value noise in three dimensions on one lattice seed, signed in [-HALF, HALF].

    Plain noise is the amplitude-weighted mean of its octaves. Ridged noise weights each finer
    octave by the coarser crest beneath it, as the land's ridged noise does, and is mapped to the
    same signed range, crests high.
    """

    __slots__ = ("_lattice", "_seed", "amplitudes", "norm", "ridged", "wavelengths")

    def __init__(self, seed: bytes, wavelength: int, octaves: int, *, ridged: bool) -> None:
        self._seed = seed
        self.ridged = ridged
        lengths, amplitudes, length, amplitude = [], [], wavelength, 1000
        for _ in range(octaves):
            lengths.append(max(1, length))
            amplitudes.append(amplitude)
            amplitude = amplitude * 1000 // (2100 if ridged else 2000)
            length = length * 1000 // 2030
        self.wavelengths: tuple[int, ...] = tuple(lengths)
        self.amplitudes: tuple[int, ...] = tuple(amplitudes)
        self.norm = sum(amplitudes)
        self._lattice: dict[tuple[int, int, int, int], int] = {}

    def axis(self, values: Sequence[int]) -> list[AxisWeights]:
        """Each coordinate's cell and weight at every octave."""
        out = []
        for value in values:
            weights = []
            for length in self.wavelengths:
                cell, rest = divmod(value, length)
                weights.append((cell, _fade(rest * ONE // length)))
            out.append(tuple(weights))
        return out

    def _at(self, octave: int, i: int, j: int, k: int) -> int:
        key = (octave, i, j, k)
        value = self._lattice.get(key)
        if value is None:
            digest = hashlib.sha256(
                self._seed
                + octave.to_bytes(1, "little")
                + i.to_bytes(8, "little", signed=True)
                + j.to_bytes(8, "little", signed=True)
                + k.to_bytes(8, "little", signed=True)
            ).digest()
            value = self._lattice[key] = int.from_bytes(digest[:2], "little") - HALF
        return value

    def _octave(
        self, octave: int, x: tuple[int, int], y: tuple[int, int], z: tuple[int, int]
    ) -> int:
        (i, wx), (j, wy), (k, wz) = x, y, z
        at = self._at
        c000, c100 = at(octave, i, j, k), at(octave, i + 1, j, k)
        c010, c110 = at(octave, i, j + 1, k), at(octave, i + 1, j + 1, k)
        c001, c101 = at(octave, i, j, k + 1), at(octave, i + 1, j, k + 1)
        c011, c111 = at(octave, i, j + 1, k + 1), at(octave, i + 1, j + 1, k + 1)
        x00 = c000 * ONE + (c100 - c000) * wx
        x10 = c010 * ONE + (c110 - c010) * wx
        x01 = c001 * ONE + (c101 - c001) * wx
        x11 = c011 * ONE + (c111 - c011) * wx
        y0 = x00 * ONE + (x10 - x00) * wy
        y1 = x01 * ONE + (x11 - x01) * wy
        return (y0 * ONE + (y1 - y0) * wz) // _ONE_CUBED

    def sample(self, x: AxisWeights, y: AxisWeights, z: AxisWeights) -> int:
        """The noise at one point, from its three coordinates' weights."""
        total = 0
        if not self.ridged:
            for octave, amplitude in enumerate(self.amplitudes):
                total += self._octave(octave, x[octave], y[octave], z[octave]) * amplitude
            return total // self.norm
        weight = ONE
        for octave, amplitude in enumerate(self.amplitudes):
            crest = HALF - abs(self._octave(octave, x[octave], y[octave], z[octave]))
            crest = crest * crest // HALF * weight // ONE
            weight = min(ONE, crest * 2 * ONE // HALF)
            total += crest * amplitude
        return 2 * (total // self.norm) - HALF

    def point(self, x: int, y: int, z: int) -> int:
        """The noise at one point: a grid of one."""
        (ax,), (ay,), (az,) = self.axis((x,)), self.axis((y,)), self.axis((z,))
        return self.sample(ax, ay, az)
