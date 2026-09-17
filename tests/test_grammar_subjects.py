"""Subject identity: one uuid5 rule, pinned by known answers, and blind to the seed and version.

    identity = uuid5(SUBJECT_NAMESPACE, canonical_json([
        "exulanica.grammar.subject/v1", grammar_id, root_identity,
        subject_kind, owner_identity, ordinal,
    ]))

*   The namespace is the uuid5 of a fixed ``.invalid`` URL, and its value is written here.
*   Known answers are written here too, so a change to the preimage that a formula re-derived in
    the test would share still fails.
*   An identity must survive regeneration, so neither the seed nor the grammar version is an
    input: the function has no such parameter, two stage contexts with different seeds derive the
    same identity, and the fixture's identities all check under a different seed.
*   The codes that stand in for an ordinal are append-only, and they are written out here.
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.contract import StageContext
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.city import CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.common import SIDE_CODES, SURFACE_ROLE_CODES
from exulanica.grammar.grammars.city.facade import FACADE_TIER_STRIDE
from exulanica.grammar.records import MAX_SAFE_INTEGER
from exulanica.grammar.shapes import check_identities
from exulanica.grammar.subjects import SUBJECT_NAMESPACE, SUBJECT_RULE, subject_identity

from city_v2_fixture import builder

ROOT_IDENTITY = "0e3b7f2a-5c1d-5a4b-8e6f-1a2b3c4d5e6f"
FIXTURE = builder()


def _identity(**changes: object) -> str:
    parts: dict[str, object] = {
        "grammar_id": "city",
        "root_identity": ROOT_IDENTITY,
        "subject_kind": "building",
        "owner_identity": ROOT_IDENTITY,
        "ordinal": 7,
    }
    parts.update(changes)
    return subject_identity(**parts)  # type: ignore[arg-type]


def test_the_namespace_is_the_uuid5_of_its_url_and_is_pinned():
    assert (
        uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/grammar/subject")
        == SUBJECT_NAMESPACE
    )
    assert str(SUBJECT_NAMESPACE) == "4b584f26-18fb-5f96-93f8-e540a406a700"
    assert SUBJECT_RULE == "exulanica.grammar.subject/v1"


def test_an_identity_is_the_uuid5_of_the_canonical_tuple():
    preimage = canonical_json(
        [SUBJECT_RULE, "city", ROOT_IDENTITY, "building", ROOT_IDENTITY, 7]
    ).decode("utf-8")
    assert _identity() == str(uuid.uuid5(SUBJECT_NAMESPACE, preimage))


def test_known_answers_are_pinned():
    assert _identity() == "8605c268-826c-5061-8527-c048b2199813"
    city = "7bd1a98c-5e69-5356-aa4f-d617c4611c55"
    assert city == FIXTURE.CITY
    district = subject_identity(
        grammar_id="city",
        root_identity=city,
        subject_kind="district",
        owner_identity=city,
        ordinal=0,
    )
    assert district == "03bc2f50-30db-5ca2-99c6-e313151750ef" == FIXTURE.DISTRICT


def test_the_rule_takes_neither_a_seed_nor_a_grammar_version():
    assert list(inspect.signature(subject_identity).parameters) == [
        "grammar_id",
        "root_identity",
        "subject_kind",
        "owner_identity",
        "ordinal",
    ]


def test_two_seeds_derive_the_same_identity_through_a_stage_context():
    def context(seed: str) -> StageContext:
        return StageContext(
            seed=seed,
            grammar_id="city",
            stage_id="massing",
            parameters={},
            prior=(),
            subject_identity=ROOT_IDENTITY,
        )

    first = context("0" * 64).identity("building", ROOT_IDENTITY, 7)
    second = context("f" * 64).identity("building", ROOT_IDENTITY, 7)
    assert first == second == _identity()


def test_the_fixture_identities_hold_under_another_seed_and_grammar_version():
    """The fixture's records state a seed and a grammar version; identities read neither."""
    records = [
        dataclasses.replace(record, seed="f" * 64, grammar_version=3)
        if hasattr(record, "seed")
        else record
        for record in FIXTURE.build_document().grammars[0].records()
    ]
    check_identities(records, CITY_SHAPES_BY_TYPE, grammar_id="city", root_identity=FIXTURE.CITY)
    with pytest.raises(InvalidRecordError, match="is not the identity its rule derives"):
        check_identities(
            records, CITY_SHAPES_BY_TYPE, grammar_id="city", root_identity=ROOT_IDENTITY
        )


@pytest.mark.parametrize(
    "change",
    [
        {"grammar_id": "box"},
        {"root_identity": "1e3b7f2a-5c1d-5a4b-8e6f-1a2b3c4d5e6f"},
        {"subject_kind": "parcel"},
        {"owner_identity": "1e3b7f2a-5c1d-5a4b-8e6f-1a2b3c4d5e6f"},
        {"ordinal": 8},
    ],
    ids=lambda change: next(iter(change)),
)
def test_every_part_of_the_tuple_moves_the_identity(change):
    assert _identity(**change) != _identity()


@pytest.mark.parametrize(
    "change",
    [
        {"grammar_id": "City"},
        {"grammar_id": ""},
        {"root_identity": "0E3B7F2A-5C1D-5A4B-8E6F-1A2B3C4D5E6F"},
        {"root_identity": "not-a-uuid"},
        {"subject_kind": "street node"},
        {"owner_identity": 7},
        {"ordinal": -1},
        {"ordinal": True},
        {"ordinal": "7"},
        {"ordinal": MAX_SAFE_INTEGER + 1},
    ],
    ids=lambda change: f"{next(iter(change))}={next(iter(change.values()))!r}",
)
def test_a_malformed_part_is_refused(change):
    with pytest.raises(InvalidRecordError):
        _identity(**change)


def test_the_codes_that_stand_in_for_an_ordinal_are_append_only_and_written_out():
    assert SIDE_CODES == {"left": 0, "right": 1}
    assert SURFACE_ROLE_CODES == {
        "wall": 1,
        "ground_band": 2,
        "stall_riser": 3,
        "fascia": 4,
        "shopfront_frame": 5,
        "glazing": 6,
        "door": 7,
        "trim": 8,
        "party_wall_scar": 9,
        "roof": 10,
        "parapet": 11,
        "awning": 12,
        "carriageway": 13,
        "gutter": 14,
        "kerb": 15,
        "footway": 16,
        "crossing": 17,
        "marking": 18,
        "lot": 19,
        "terrain": 20,
        "object_primary": 21,
        "object_secondary": 22,
        "object_tertiary": 23,
        "tree_pit": 24,
        "canopy": 25,
        "trunk": 26,
    }
    assert FACADE_TIER_STRIDE == 1_000_000


def test_every_subject_record_kind_derives_its_identity_by_the_rule():
    """Every kind with an ``identity`` field declares a rule; only the tile record has neither."""
    without = sorted(shape.kind for shape in CITY_SHAPES_BY_TYPE.values() if shape.identity is None)
    assert without == ["city.tile"]
    kinds = {
        shape.identity.subject_kind for shape in CITY_SHAPES_BY_TYPE.values() if shape.identity
    }
    assert len(kinds) == 26
