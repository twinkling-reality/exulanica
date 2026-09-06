"""The one encoding every measured number leaves this package under.

Written after a review found the encoder wrong in both directions at once: it claimed to refuse a
non-finite value and silently encoded NaN as the string "NaN", while an ordinary large coordinate
raised an ArithmeticError that no caller's guard caught and that reached the HTTP layer as a 500.
"""

from __future__ import annotations

import math

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.graph.wire_numbers import (
    MAX_INTEGER_DIGITS,
    NUMBER_DECIMALS,
    decimal_string,
    decimal_strings,
)


def test_a_measurement_encodes_to_a_fixed_grid():
    assert decimal_string(1.5) == "1." + "5".ljust(NUMBER_DECIMALS, "0")
    assert decimal_string(-1.25) == "-1.25" + "0" * (NUMBER_DECIMALS - 2)
    assert len(decimal_string(3.0).split(".")[1]) == NUMBER_DECIMALS


def test_the_result_always_survives_canonical_json():
    """The whole reason the encoding exists: a float may never enter a digest input."""
    canonical_json({"values": decimal_strings([1.5, -0.25, 1e-9, 1e15])})


def test_a_non_finite_measurement_is_refused_rather_than_encoded():
    """NaN was the silent one, and it is the dangerous one.

    Infinity raised, loudly if wrongly typed. NaN did not: it encoded to the string "NaN" and rode
    into a digest-bound payload beside real measurements, where nothing downstream would ever look
    at it again.
    """
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(CanonicalisationError, match="not finite"):
            decimal_string(value)
    assert not math.isfinite(float("nan"))


def test_a_coordinate_too_large_to_encode_is_refused_rather_than_crashing():
    """The refusal must be catchable, which an ArithmeticError from the decimal context is not."""
    largest = 10.0 ** (MAX_INTEGER_DIGITS - 1)
    assert decimal_string(largest).startswith("1000000000000000")
    for value in (10.0**MAX_INTEGER_DIGITS, -1e30, 1e300):
        with pytest.raises(CanonicalisationError, match="integer digits"):
            decimal_string(value)


def test_the_two_zeros_encode_to_the_same_string():
    """IEEE 754 has two zeros; a digest must not.

    A transform component that came out as -0.0 rather than 0.0 is the same measurement, and two
    strings for it would give a recipient two digests for one geometry.
    """
    assert decimal_string(0.0) == decimal_string(-0.0)
    assert not decimal_string(-0.0).startswith("-")


def test_the_encoding_is_a_grid_and_does_not_claim_a_round_trip():
    """Stated so nobody later reads the fixed precision as lossless.

    A value below half the grid step quantises to zero. That is correct for this purpose and it is
    not a round trip, and the module says so rather than implying otherwise.
    """
    assert decimal_string(1e-15) == decimal_string(0.0)
    assert float(decimal_string(1e-15)) != 1e-15
