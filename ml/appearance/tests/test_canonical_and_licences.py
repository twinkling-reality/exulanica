"""Canonical JSON is strict, and only the licences section 6 of the licence matrix allows pass."""

from __future__ import annotations

import pytest

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical
from exulanica_appearance.licences import ALLOWED, licence_id


def test_canonical_bytes_sort_and_refuse_fractions():
    assert canonical_bytes({"b": 1, "a": [2, "x"]}) == b'{"a":[2,"x"],"b":1}'
    with pytest.raises(Refused, match="fraction"):
        canonical_bytes({"a": 1.5})


@pytest.mark.parametrize(
    "raw, words",
    [
        (b'{"a": 1}', "not canonical"),
        (b'{"a":1,"a":1}', "repeats"),
        (b'{"a":1.0}', "fraction"),
        (b"\xff", "not ASCII JSON"),
    ],
)
def test_parse_canonical_refuses_every_other_spelling(raw, words):
    with pytest.raises(Refused, match=words):
        parse_canonical(raw, "the record")


@pytest.mark.parametrize(
    "card, expected",
    [
        ({"license": "apache-2.0"}, "Apache-2.0"),
        ({"license": "mit"}, "MIT"),
        ({"license": "cc-by-4.0"}, "CC-BY-4.0"),
        (
            {
                "license": "other",
                "license_name": "openmdw1.1-license",
                "license_link": "https://openmdw.ai/license/1-1/",
            },
            "OpenMDW-1.1",
        ),
    ],
)
def test_allowed_licences(card, expected):
    assert licence_id(card) == expected
    assert expected in ALLOWED


@pytest.mark.parametrize(
    "card",
    [
        {"license": "other", "license_name": "nvidia-open-model-license"},
        {"license": "other", "license_name": "flux-non-commercial-license"},
        {"license": "openrail"},
        {"license": "openrail++"},
        {"license": "cc-by-nc-4.0"},
        {
            "license": "other",
            "license_name": "openmdw1.1-license",
            "license_link": "https://example.com/",
        },
        {},
    ],
)
def test_every_other_licence_is_refused(card):
    with pytest.raises(Refused, match="section 6"):
        licence_id(card)
