"""Turns in whole numbers: sine and cosine of an angle in millidegrees, and the matrix a part is
placed by.

Every value is an integer computed with integer arithmetic, so a turned part is the same in every
process. An angle is reduced to its octant, its remainder (at most 45 degrees) is taken to radians
at 2^62 by :data:`PI_SCALED`, and sine and cosine are summed by their Taylor series to well below
one unit at 2^62, then rounded to :data:`TURN_ONE`. Octant symmetries give the rest, so turns a
quarter apart are exact negations and swaps of each other.

A part's matrix turns it counterclockwise by its yaw seen from above, then leans it by its tilt
toward a compass bearing (clockwise from north): its up axis then points toward that bearing,
``tilt`` from upright. Entries are at :data:`TURN_ONE`; a point is taken into a part's own frame
by the transpose.
"""

from __future__ import annotations

import functools
from typing import Final, TypeAlias

__all__ = ["PI_SCALED", "TURN_ONE", "Turn", "sin_cos", "turn_matrix"]

#: The scale of a turned value: one is 2^30.
TURN_ONE: Final = 1 << 30
_SCALE_BITS: Final = 62
#: The floor of pi times 2^62.
PI_SCALED: Final = 14_488_038_916_154_245_684
_FULL: Final = 360_000
_OCTANT: Final = 45_000

Turn: TypeAlias = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]


def _taylor(x: int) -> tuple[int, int]:
    """Sine and cosine of ``x`` radians at 2^62, for 0 <= x <= pi / 4, at 2^62."""
    one = 1 << _SCALE_BITS
    x2 = x * x >> _SCALE_BITS
    sin_term, cos_term = x, one
    sin_sum, cos_sum = x, one
    for k in range(1, 16):
        sin_term = -((sin_term * x2) >> _SCALE_BITS) // ((2 * k) * (2 * k + 1))
        cos_term = -((cos_term * x2) >> _SCALE_BITS) // ((2 * k - 1) * (2 * k))
        sin_sum += sin_term
        cos_sum += cos_term
    return sin_sum, cos_sum


def _rounded(value: int) -> int:
    shift = _SCALE_BITS - 30
    return (value + (1 << (shift - 1))) >> shift


@functools.lru_cache(maxsize=8192)
def sin_cos(mdeg: int) -> tuple[int, int]:
    """Sine and cosine of an angle in whole millidegrees, at :data:`TURN_ONE`."""
    angle = mdeg % _FULL
    octant, rest = divmod(angle, _OCTANT)
    if octant % 2:
        rest = _OCTANT - rest
    sine, cosine = _taylor(rest * PI_SCALED // 180_000)
    if octant % 2:
        sine, cosine = cosine, sine
    quadrant = octant // 2
    if quadrant == 1:
        sine, cosine = cosine, -sine
    elif quadrant == 2:
        sine, cosine = -sine, -cosine
    elif quadrant == 3:
        sine, cosine = -cosine, sine
    return _rounded(sine), _rounded(cosine)


@functools.lru_cache(maxsize=4096)
def turn_matrix(yaw_mdeg: int, tilt_mdeg: int, toward_mdeg: int) -> Turn | None:
    """The matrix taking a part's own axes to the volume's frame, at :data:`TURN_ONE`, or None
    for a part neither turned nor leaned."""
    if yaw_mdeg % _FULL == 0 and tilt_mdeg % _FULL == 0:
        return None
    one = TURN_ONE
    sy, cy = sin_cos(yaw_mdeg)
    yaw = ((cy, -sy, 0), (sy, cy, 0), (0, 0, one))
    if tilt_mdeg % _FULL == 0:
        return yaw
    st, ct = sin_cos(tilt_mdeg)
    sb, cb = sin_cos(toward_mdeg)
    # The lean turns about the level axis up x (east sin b, north cos b), which is (-cos b, sin b):
    # Rodrigues' form c I + s [a]x + (1 - c) a a^T, every term at one cubed before it is divided.
    axis = (-cb, sb, 0)
    cross = ((0, 0, sb), (0, 0, cb), (-sb, -cb, 0))
    lean = tuple(
        tuple(
            (
                (ct * one * one if row == column else 0)
                + st * cross[row][column] * one
                + (one - ct) * axis[row] * axis[column]
            )
            // (one * one)
            for column in range(3)
        )
        for row in range(3)
    )
    return tuple(  # type: ignore[return-value]
        tuple(sum(lean[row][k] * yaw[k][column] for k in range(3)) // one for column in range(3))
        for row in range(3)
    )
