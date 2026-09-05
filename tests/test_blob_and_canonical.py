"""Content addressing and the digest canonicalisation it feeds."""

from __future__ import annotations

import io

import pytest
from exulanica.canonical import canonical_json, ceil_div, round_half_down, sha256_of_canonical
from exulanica.errors import CanonicalisationError, InvalidAddressError
from exulanica.evidence import BlobId


def test_ni_uri_round_trips():
    blob = BlobId.of_bytes(b"a photograph")
    assert BlobId.from_ni_uri(blob.ni_uri) == blob
    assert BlobId.from_hex(blob.hex) == blob
    assert blob.ni_uri.startswith("ni:///sha-256;")
    assert "=" not in blob.ni_uri  # RFC 6920 base64url is unpadded


def test_streaming_hash_matches_in_memory_hash():
    payload = b"x" * (3 * (1 << 20) + 17)  # spans several read chunks
    assert BlobId.of_stream(io.BytesIO(payload)) == BlobId.of_bytes(payload)


def test_blob_ids_are_ordered_by_digest():
    ids = [BlobId.of_bytes(bytes([i])) for i in range(8)]
    assert sorted(ids) == sorted(ids, key=lambda b: b.digest)


def test_a_short_or_wrong_digest_is_refused():
    with pytest.raises(InvalidAddressError):
        BlobId(b"\x00" * 31)
    with pytest.raises(InvalidAddressError):
        BlobId.from_hex("not a digest")
    with pytest.raises(InvalidAddressError):
        BlobId.from_ni_uri("ni:///sha-512;" + "A" * 43)


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == b'{"a":[1,{"c":3,"d":2}],"b":1}'


def test_canonical_json_refuses_floats_anywhere():
    """A float in a digest input has no canonical rendering, so it may not enter one.

    This is the guard that keeps span digests reproducible in a language that is not Python.
    """
    with pytest.raises(CanonicalisationError):
        canonical_json({"x": 0.1})
    with pytest.raises(CanonicalisationError):
        canonical_json({"region": {"rect": [0.1, 0.2]}})
    with pytest.raises(CanonicalisationError):
        sha256_of_canonical({"nested": {"deep": {"value": 1e9}}})


def test_canonical_json_keeps_integers_and_unicode_exact():
    expected = '{"n":4611686018427387904,"s":"café"}'.encode()
    assert canonical_json({"n": 2**62, "s": "café"}) == expected


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (1, 2, 0),  # +0.5 ties toward zero
        (-1, 2, 0),  # -0.5 ties toward zero
        (3, 2, 1),  # +1.5 ties toward zero
        (-3, 2, -1),  # -1.5 ties toward zero
        (8, 5, 2),  # 1.6 rounds up
        (-8, 5, -2),  # -1.6 rounds away from zero, because it is nearer
        (7, 1, 7),
        (0, 5, 0),
    ],
)
def test_round_half_down_is_ties_toward_zero(numerator, denominator, expected):
    assert round_half_down(numerator, denominator) == expected


def test_round_half_down_is_exact_at_int64_magnitudes():
    """Float arithmetic loses this; the rounding rule must not."""
    huge = 9_223_372_036_854_775_807
    assert round_half_down(huge * 2 + 1, 2) == huge


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (1, 2, 1),  # up, not to nearest
        (-1, 2, 0),  # toward positive infinity, not away from zero
        (3, 2, 2),
        (-3, 2, -1),
        (4, 2, 2),  # exact values are untouched
        (-4, 2, -2),
        (0, 5, 0),
        (1, -2, 0),  # a negative denominator is normalised, not a second behaviour
    ],
)
def test_ceil_div_rounds_toward_positive_infinity(numerator, denominator, expected):
    """Toward positive infinity, not away from zero.

    ``ticks_from_ns`` floors toward negative infinity, so its inverse has to round the same
    direction to compose. Rounding away from zero would make the tick round trip exact for
    positive times and lose a sample for negative ones, which is the harder bug to notice
    because negative t_ns only appears when a container carries an edit list.
    """
    assert ceil_div(numerator, denominator) == expected


def test_ceil_div_is_exact_at_int64_magnitudes():
    huge = 9_223_372_036_854_775_807
    assert ceil_div(huge * 2 - 1, 2) == huge
    assert ceil_div(huge * 2 + 1, 2) == huge + 1
