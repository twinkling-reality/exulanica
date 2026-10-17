"""A society of things names its invented people by two-part names without numbers.

A new society of things records the identity catalog's second version in its first input, and its
people are named by first and last names drawn by its seed without repeats
(``exulanica.world.society_identity``). A society made before records none and keeps the first
version's names, a number after each, so its genesis and replay are as they were. A kind's beings
keep their kind's naming.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.world.society_catalogs import LEGACY_IDENTITY_CATALOG, legacy_identity
from exulanica.world.society_identity import (
    IDENTITY_FIELD,
    check_identity,
    drawn_names,
    identity_record,
)
from exulanica.world.society_planner import input_sha256, validate_society_input
from exulanica.world.society_things import initial_things_society, validate_things_state

from things_society_support import SEED, SOCIETY, compose, thing

CATALOG = (
    Path(__file__).resolve().parents[1] / "assets/catalogs/society/society-legacy-identity.v2.json"
)
KNIGHT = thing("knight", "knight", 2, 3_000, 3_000)
#: The first names the shared test seed draws, pinned so a change to the draw or the lists is seen.
FIRST_DRAWN = ["Cyra Gale", "Faye Quill", "Juno Brook", "Ivo Hollis", "Cleo Joss", "Gia Vale"]


def resealed(document: dict, **changes: object) -> dict:
    """``document`` with ``changes`` (a value of None removes the field), sealed again."""
    sealed = {k: v for k, v in document.items() if k != "document_sha256"}
    for key, value in changes.items():
        if value is None:
            sealed.pop(key, None)
        else:
            sealed[key] = value
    sealed["document_sha256"] = input_sha256(sealed)
    return sealed


def _society(document: dict, population: int = 8) -> dict:
    return initial_things_society(SOCIETY, SEED, document, population=population)


def test_the_second_version_holds_forty_by_forty_names_with_reasons_and_serves_no_profile():
    entries = json.loads(CATALOG.read_text())["entries"]
    first = [e["text"] for e in entries if e["kind"] == "first_name"]
    last = [e["text"] for e in entries if e["kind"] == "last_name"]
    assert (len(first), len(set(first)), len(last), len(set(last))) == (40, 40, 40, 40)
    assert {e["kind"] for e in entries} == {"first_name", "last_name"}
    assert all(len(e["reason"].split()) > 20 for e in entries)
    # The profiles that name people by ordinal keep the first version.
    for profile in ("exulanica-society/v1", "exulanica-society/v2", "exulanica-society/v3"):
        assert len(legacy_identity(profile).first_names) == 8


def test_a_new_society_of_things_records_its_identity_and_names_its_people_without_numbers():
    document = compose([KNIGHT])
    assert document[IDENTITY_FIELD] == {"catalog": LEGACY_IDENTITY_CATALOG, "version": 2}
    state = _society(document)
    people = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    names = [p["display_name"] for p in people]
    assert names[:6] == FIRST_DRAWN
    assert names == drawn_names(SEED, len(names))
    assert all(part.isalpha() for name in names for part in name.split())
    assert len(set(names)) == len(names)
    assert state[IDENTITY_FIELD] == identity_record()
    # The knight the author placed keeps its kind's name.
    assert [p["display_name"] for p in state["inhabitants"] if p["came_by"] != "populated"] == [
        "Knight"
    ]


def test_the_draw_is_the_seed_s_own_and_repeats_no_pair_within_every_pair():
    names = drawn_names(SEED, 1600)
    assert len(set(names)) == 1600
    assert drawn_names(SEED, 10) == names[:10]
    assert drawn_names("8" * 64, 10) != names[:10]
    # Past every pair the draw starts again.
    assert len(set(drawn_names(SEED, 1601))) == 1600


def test_a_society_made_before_keeps_the_first_versions_numbered_names():
    before = resealed(compose([KNIGHT]), **{IDENTITY_FIELD: None})
    assert IDENTITY_FIELD not in before
    state = _society(before)
    names = [p["display_name"] for p in state["inhabitants"] if p["came_by"] == "populated"]
    assert names[:3] == ["Ari Ash 1", "Bela Ash 2", "Cleo Ash 3"]
    assert IDENTITY_FIELD not in state


@pytest.mark.parametrize(
    "record",
    [
        {"catalog": LEGACY_IDENTITY_CATALOG, "version": 1},
        {"catalog": "another-catalog", "version": 2},
        {"catalog": LEGACY_IDENTITY_CATALOG, "version": 2, "extra": True},
        "society-legacy-identity",
    ],
)
def test_an_identity_out_of_shape_is_refused_by_name(record):
    with pytest.raises(ValueError, match="identity"):
        check_identity(record)
    with pytest.raises(ValueError):
        validate_society_input(resealed(compose([KNIGHT]), **{IDENTITY_FIELD: record}))


def test_only_a_first_input_records_an_identity():
    later = resealed(compose([KNIGHT], input_seq=2), **{IDENTITY_FIELD: identity_record()})
    with pytest.raises(ValueError, match="first input"):
        validate_society_input(later)


def test_a_state_holding_an_identity_out_of_shape_is_refused():
    state = _society(compose([KNIGHT]))
    validate_things_state(state)
    earlier = {"catalog": LEGACY_IDENTITY_CATALOG, "version": 1}
    with pytest.raises(ValueError, match="identity"):
        validate_things_state({**state, IDENTITY_FIELD: earlier})
