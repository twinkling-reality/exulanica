"""Canonical JSON and the one rounding rule, both of which feed digests.

Everything in this module exists because a digest input must serialise the same way forever,
on every machine, in every language that later reads an Exulanica package. Two rules do the
work:

1.  **No floats, anywhere, ever, in a digest input.** IEEE 754 has no canonical decimal
    rendering that every JSON writer agrees on, so a float in a digest input is a latent
    cross-language mismatch. Callers quantise to integers first (see
    ``exulanica.evidence.region`` for how normalised coordinates become integers).
2.  **One rounding rule for quantising a measured value**, ``round_half_down``, used by the
    coordinate quantisation in ``exulanica.evidence.region`` and by the EXIF GPS and altitude
    conversions, implemented in exact integer arithmetic.

    ``ceil_div`` is the second and last rule, and it exists for a different job. Placing a tick
    on the nanosecond axis is not quantising a measurement, it is choosing a boundary, and the
    requirement there is that the choice is **invertible**: ``ticks_from_ns`` floors, so only a
    boundary at or after the true instant lands back on the tick it came from. Rounding to
    nearest looks more accurate and loses the sample. See ADR-0015 and the module docstring of
    ``exulanica.evidence.timebase``.

The canonical form is a strict subset of RFC 8785 (JCS): sorted keys, no insignificant
whitespace, UTF-8. Because floats are rejected outright, the only place this could diverge
from JCS is string escaping, and Python's ``json`` module already emits the same short escapes
that ECMAScript ``JSON.stringify`` does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.errors import CanonicalisationError

__all__ = [
    "canonical_json",
    "ceil_div",
    "round_half_down",
    "sha256_digest",
    "sha256_of_canonical",
]


def _check(value: Any, path: str) -> None:
    """Reject anything that cannot be serialised deterministically."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalisationError(
            f"float at {path}: floats may never enter a digest input. Quantise to an integer "
            "first, so the serialisation is identical on every implementation."
        )
    if isinstance(value, Mapping):
        for key, sub in value.items():
            if not isinstance(key, str):
                raise CanonicalisationError(f"non-string key at {path}: {key!r}")
            _check(sub, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for i, sub in enumerate(value):
            _check(sub, f"{path}[{i}]")
        return
    raise CanonicalisationError(f"unsupported type {type(value).__name__} at {path}")


def canonical_json(value: Any) -> bytes:
    """Serialise ``value`` to canonical UTF-8 JSON bytes, or refuse.

    Keys are sorted, separators carry no whitespace, and non-ASCII characters are emitted
    literally as UTF-8 rather than escaped, matching JCS.
    """
    _check(value, "$")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_of_canonical(value: Any) -> bytes:
    """SHA-256 over the canonical JSON encoding of ``value``. Returns 32 raw bytes."""
    return hashlib.sha256(canonical_json(value)).digest()


def sha256_digest(data: bytes) -> bytes:
    """SHA-256 over raw bytes. Returns 32 raw bytes."""
    return hashlib.sha256(data).digest()


def round_half_down(numerator: int, denominator: int) -> int:
    """Round ``numerator / denominator`` to the nearest integer, ties toward zero.

    This is the frozen rounding rule named in the spine contract as ``round_half_down``. The
    name is taken to mean what ``decimal.ROUND_HALF_DOWN`` and Java's ``RoundingMode.HALF_DOWN``
    mean, namely ties resolve toward zero. See the note in the module docstring of
    ``exulanica.evidence.timebase``: the contract names the rule but does not define it, and the
    two plausible readings differ only on exact halves for negative values.

    Implemented in integer arithmetic. Using floats here would silently lose precision at
    int64 nanosecond magnitudes, which is the exact failure the rational anchor exists to avoid.
    """
    if denominator == 0:
        raise ZeroDivisionError("round_half_down: denominator is zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    quotient, remainder = divmod(numerator, denominator)  # floor division; 0 <= remainder < d
    twice = 2 * remainder
    if twice > denominator:
        quotient += 1
    elif twice == denominator and quotient < 0:
        # Exactly .5 below zero: floor already went away from zero, so step back toward it.
        quotient += 1
    return quotient


def ceil_div(numerator: int, denominator: int) -> int:
    """Round ``numerator / denominator`` up, toward positive infinity. Exact integer arithmetic.

    This is the boundary rule, not a rounding rule for measurements: see the module docstring.
    Ceiling rather than nearest is what makes ``ns_from_ticks`` invertible under the flooring
    ``ticks_from_ns``, and toward positive infinity rather than away from zero is what makes it
    invertible for negative times too, which occur whenever a container's ``start_pts`` is later
    than track zero.
    """
    if denominator == 0:
        raise ZeroDivisionError("ceil_div: denominator is zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    return -((-numerator) // denominator)
