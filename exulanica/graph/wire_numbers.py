"""One encoding for every measured number that leaves this package, and why it is a string.

``exulanica.canonical`` refuses floats in a digest input outright: IEEE 754 has no canonical
decimal rendering that every JSON writer agrees on, so a float in a digest input is a latent
cross-language mismatch. Anything digest-bound that carries a transform, a focal length or a pixel
coordinate therefore has to encode it some other way, and the repository's existing answer is a
fixed-precision decimal string (see ``exulanica.evaluation.synthetic_multiview``).

This module holds that encoding once, so the World Read bundle and the observation graph cannot
drift into two spellings of the same number and hand a recipient two digests for one fact.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Final

from exulanica.errors import CanonicalisationError

__all__ = [
    "MAX_INTEGER_DIGITS",
    "NUMBER_DECIMALS",
    "NUMBER_ENCODING",
    "decimal_string",
    "decimal_strings",
]

#: Twelve fractional digits, stated in every payload that uses it because a recipient recomputing a
#: digest needs the format rather than a guess at it.
#:
#: This is a fixed grid, not a round trip. A value smaller than 5e-13 quantises to zero and a value
#: between grid points loses the difference, so ``float(decimal_string(x)) == x`` does not hold in
#: general and is not claimed. What the grid does give is the property digests actually need: one
#: value always produces one string, on every platform and in every language.
NUMBER_DECIMALS: Final = 12

NUMBER_ENCODING: Final = (
    f"every measured number is a decimal string with exactly {NUMBER_DECIMALS} fractional digits; "
    "canonical JSON admits no floats, because no two implementations agree on how to render one"
)


#: Integer digits this encoding admits. The default decimal context carries 28 significant digits
#: and twelve of them are spent on the fractional part, so sixteen is the exact limit rather than a
#: chosen one. MEASURED 2026-09-06: ``Decimal(1e15).quantize(...)`` succeeds and ``Decimal(1e16)``
#: raises ``InvalidOperation``.
MAX_INTEGER_DIGITS: Final = 28 - NUMBER_DECIMALS

_LIMIT: Final = 10**MAX_INTEGER_DIGITS


def decimal_string(value: float) -> str:
    """One float as a fixed-precision decimal string, or a refusal that says which value.

    Via :class:`~decimal.Decimal` rather than ``f"{value:.12f}"`` for one reason: the format
    specifier renders a value that overflows fixed notation as a long run of digits whose exact
    text depends on the platform's repr, which would silently break the cross-implementation digest
    claim.

    **Both guards below were added after review, and the original code was wrong in both
    directions.** It claimed to "refuse a non-finite value outright"; in fact
    ``Decimal(float("nan")).quantize(...)`` does not raise, so a NaN in a transform was encoded as
    the string ``"NaN"`` and carried into a digest-bound payload as though it were a measurement.
    Infinity and any magnitude at or above ``10**16`` did raise, but as
    :class:`~decimal.InvalidOperation`, which derives from ``ArithmeticError`` rather than
    ``ValueError``, so no caller's guard caught it and an unreadable receipt became a 500 instead of
    the honest refusal every reader here is built to give.

    Both now raise :class:`~exulanica.errors.CanonicalisationError`, which is what the rest of this
    system already raises when a value cannot enter a digest, and which callers can catch.
    """
    if not math.isfinite(value):
        raise CanonicalisationError(
            f"{value!r} is not finite and cannot be encoded as a measurement. A non-finite "
            "transform or coordinate is a defect upstream, not a number to write into a digest."
        )
    if abs(value) >= _LIMIT:
        raise CanonicalisationError(
            f"{value!r} needs more than {MAX_INTEGER_DIGITS} integer digits, which this encoding "
            f"cannot represent at {NUMBER_DECIMALS} fractional digits. A coordinate this large is "
            "a degenerate reconstruction rather than a place."
        )
    try:
        quantised = Decimal(value).quantize(Decimal(1).scaleb(-NUMBER_DECIMALS))
    except InvalidOperation as error:  # pragma: no cover - the guards above cover every known case
        raise CanonicalisationError(f"{value!r} cannot be quantised: {error}") from error
    if quantised.is_zero():
        # IEEE 754 has two zeros and Decimal preserves the sign of both, so a transform component
        # that is -0.0 rather than 0.0 would produce a different string, a different digest, and a
        # recipient who could not reproduce it from a value they would call equal. The two zeros
        # are the same measurement.
        quantised = abs(quantised)
    return f"{quantised:f}"


def decimal_strings(values: list[float]) -> list[str]:
    return [decimal_string(value) for value in values]
