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

from decimal import Decimal
from typing import Final

__all__ = ["NUMBER_DECIMALS", "NUMBER_ENCODING", "decimal_string", "decimal_strings"]

#: Twelve fractional digits. Comfortably beyond float64's roughly fifteen significant decimal
#: digits at the magnitudes here (normalised scene units and pixel coordinates), so the string
#: round-trips to the same double, and stated in every payload that uses it because a recipient
#: recomputing a digest needs the format rather than a guess at it.
NUMBER_DECIMALS: Final = 12

NUMBER_ENCODING: Final = (
    f"every measured number is a decimal string with exactly {NUMBER_DECIMALS} fractional digits; "
    "canonical JSON admits no floats, because no two implementations agree on how to render one"
)


def decimal_string(value: float) -> str:
    """One float as a fixed-precision decimal string.

    Via :class:`~decimal.Decimal` rather than ``f"{value:.12f}"`` for one reason: the format
    specifier renders a value that overflows fixed notation, such as a corrupt transform carrying
    ``1e30``, as thirty digits and a point, which is a different string on a platform with a
    different repr and would silently break the cross-implementation digest claim. ``Decimal``
    quantises exactly and refuses a non-finite value outright, which is the correct failure: a NaN
    in a transform is a bug upstream, not a number to encode.
    """
    quantised = Decimal(value).quantize(Decimal(1).scaleb(-NUMBER_DECIMALS))
    return f"{quantised:f}"


def decimal_strings(values: list[float]) -> list[str]:
    return [decimal_string(value) for value in values]
