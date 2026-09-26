"""Integer vectors and turns: the arithmetic flight runs on, identical on every machine.

A flight is replayed by recomputing it, so every value it holds is an integer and every operation
on one is exact integer arithmetic: millimetres, millimetres a second, milliseconds. There is no
float and no library sine anywhere a digest can see, because a sine's last bit is the host's
choice, and a flight that differs by a millimetre in one step differs everywhere after it.

- Division truncates toward zero (:func:`tdiv`), so a vector and its negation scale to a vector
  and its negation, and a steering force pointing west is exactly the mirror of one pointing east.
- A length is :func:`math.isqrt` of the squared length, the floor of the true length.
- A turn by a yaw in microradians uses :func:`turn`, a sine and cosine computed as fixed-point
  integers by a Taylor series: the same bits everywhere, within 2**-40 of the true values.
"""

from __future__ import annotations

import math
from typing import Final

__all__ = [
    "ONE",
    "Vector",
    "add",
    "ceil_div",
    "clamp_length",
    "cross_y",
    "dot",
    "length",
    "scale_to",
    "sub",
    "tdiv",
    "turn",
    "turned",
]

Vector = tuple[int, int, int]

#: Fixed-point one for :func:`turn`: sines and cosines are integers over this.
ONE: Final = 1 << 40
#: Pi over :data:`ONE`, from its first thirty decimal digits; the error is far below 2**-40.
_PI: Final = 3_141_592_653_589_793_238_462_643_383_279 * ONE // 10**30
_MICRO: Final = 1_000_000


def tdiv(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` truncated toward zero; ``denominator`` is positive."""
    if numerator >= 0:
        return numerator // denominator
    return -(-numerator // denominator)


def ceil_div(numerator: int, denominator: int) -> int:
    """``numerator / denominator`` rounded up; ``denominator`` is positive."""
    return -(-numerator // denominator)


def add(a: Vector, b: Vector) -> Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vector, b: Vector) -> Vector:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a: Vector, b: Vector) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross_y(a: Vector, b: Vector) -> int:
    """The vertical component of ``a x b``: positive when ``b`` points to the left of ``a``,
    counter-clockwise seen from above, in the region's frame (``x`` east, ``y`` up, ``z`` south)."""
    return a[2] * b[0] - a[0] * b[2]


def length(v: Vector) -> int:
    return math.isqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def scale_to(v: Vector, magnitude: int) -> Vector:
    """``v`` scaled to ``magnitude``, component by component truncated; zero stays zero."""
    size = length(v)
    if size == 0:
        return (0, 0, 0)
    return (
        tdiv(v[0] * magnitude, size),
        tdiv(v[1] * magnitude, size),
        tdiv(v[2] * magnitude, size),
    )


def clamp_length(v: Vector, maximum: int) -> Vector:
    """``v`` unchanged when no longer than ``maximum``, else scaled to it."""
    return v if length(v) <= maximum else scale_to(v, maximum)


def turn(yaw_microradians: int) -> tuple[int, int]:
    """``(cos, sin)`` of the yaw, each an integer over :data:`ONE`.

    The angle is reduced to ``[-pi, pi]`` in fixed point and each series summed until its terms
    vanish; every term is truncated toward zero, so the sums stop and the bits never depend on the
    machine.
    """
    x = yaw_microradians * ONE // _MICRO
    x %= 2 * _PI
    if x > _PI:
        x -= 2 * _PI
    square = x * x // ONE
    sine = term = x
    n = 1
    while term:
        term = tdiv(tdiv(-term * square, ONE), (n + 1) * (n + 2))
        sine += term
        n += 2
    cosine = term = ONE
    n = 0
    while term:
        term = tdiv(tdiv(-term * square, ONE), (n + 1) * (n + 2))
        cosine += term
        n += 2
    return cosine, sine


def turned(dx: int, dz: int, cosine: int, sine: int) -> tuple[int, int]:
    """A plan offset turned by a yaw, as fractions over :data:`ONE` (numerators returned).

    The same turn the society's footprints take (``society_composition.footprint_ring``): an
    object's own ``x`` axis goes to ``(cos, -sin)`` and its ``z`` axis to ``(sin, cos)`` in the
    region's frame. The caller rounds the numerators the way its use needs, outward for a bound.
    """
    return (dx * cosine + dz * sine, -dx * sine + dz * cosine)
