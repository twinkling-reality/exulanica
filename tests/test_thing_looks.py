"""Which look a thing may wear: a shipped look whose body plan is its kind's.

No database. Expected references come from the committed kind and look files, and each refusal
is named against a positive control that passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.documents import read_json
from exulanica.world.thing_looks import THING_LOOK_CODES, ThingLookRefused, check_crossing_look

ROOT = Path(__file__).resolve().parents[1]
KINDS = ROOT / "assets/catalogs/things/kinds"
LOOKS = ROOT / "assets/catalogs/things/looks"


def _kind(key: str, version: int = 1) -> dict:
    document = read_json(KINDS / f"{key}.v{version}.json")
    return {"kind": key, "version": version, "sha256": sha256_of_canonical(document).hex()}


def _look(key: str, version: int = 1) -> dict:
    document = read_json(LOOKS / f"{key}.v{version}.json")
    return {"look": key, "version": version, "sha256": sha256_of_canonical(document).hex()}


def test_a_visitor_may_wear_a_shipped_humanoid_look():
    worn = check_crossing_look(_kind("visitor"), _look("blocky-traveller"))
    assert worn.document() == _look("blocky-traveller")


@pytest.mark.parametrize(
    ("kind", "look", "code"),
    [
        (lambda: _kind("visitor"), lambda: _look("primitive-well"), "look_unfit"),
        (
            lambda: _kind("visitor"),
            lambda: {**_look("blocky-traveller"), "sha256": "e" * 64},
            "look_not_shipped",
        ),
        (
            lambda: _kind("visitor"),
            lambda: {**_look("blocky-traveller"), "version": 2},
            "look_not_shipped",
        ),
        (
            lambda: _kind("visitor"),
            lambda: {"look": "blocky-traveller", "version": 1},
            "look_not_shipped",
        ),
        (
            lambda: {**_kind("visitor"), "sha256": "e" * 64},
            lambda: _look("blocky-traveller"),
            "thing_kind_not_shipped",
        ),
        (lambda: {"kind": "visitor"}, lambda: _look("blocky-traveller"), "thing_kind_not_shipped"),
    ],
    ids=[
        "a-well-on-a-visitor",
        "another-digest",
        "a-version-not-shipped",
        "no-digest",
        "a-kind-at-another-digest",
        "a-kind-without-its-version",
    ],
)
def test_any_other_look_is_refused_by_name(kind, look, code):
    assert code in THING_LOOK_CODES
    with pytest.raises(ThingLookRefused) as refused:
        check_crossing_look(kind(), look())
    assert refused.value.code == code
