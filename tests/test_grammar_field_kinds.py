"""Every field kind the grammar declares is checked, and the list of kinds comes from the grammar.

:data:`exulanica.grammar.shapes.FIELD_KINDS` names the field kinds a record may declare, and
:func:`~exulanica.grammar.shapes.validate_record` dispatches over them by hand in ``_check_field``
and ``_check_sequence``. A kind added to that tuple without a branch falls through to the nested
record case, so no existing test would notice: the kind would simply never be validated.

So the coverage here is read from ``FIELD_KINDS`` rather than listed. The cases below supply, per
kind, a value that holds and a value of the wrong shape, and a kind with no case FAILS rather than
being skipped, because a table in this file may not decide which kinds get tested.

Each case asserts both directions, and the second one is why: if a kind's branch were deleted, its
wrong value would still be refused, by the sequence branch complaining that it is not a tuple. It
is the value that HOLDS being refused that shows a branch has gone.

What this proves: every declared kind is dispatched somewhere, and a value of the wrong shape is
refused. It does not prove any kind's checks are complete. The texture set id is taken from the
published manifest rather than typed here, so this file states no set of its own.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.grammar import shapes
from exulanica.grammar.errors import InvalidRecordError, InvalidSeedError
from exulanica.grammar.geometry import Extent
from exulanica.grammar.shapes import EXTENT_SHAPE, FIELD_KINDS, FieldShape, RecordShape
from exulanica.grammar.textures import read_texture_manifest

_IDENTITY = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/field-kinds"))
_HEX64 = "9" * 64
_RING = ((0, 0), (1_000, 0), (1_000, 1_000), (0, 1_000))
_EXTENT = Extent(0, 0, 0, 1_000, 1_000, 1_000)


def _published_set_id() -> str:
    """One set id from the manifest, so a valid id is read from the tree and not invented."""
    published = sorted(read_texture_manifest())
    assert published, "the texture manifest published nothing, so this case proves nothing"
    return published[0]


#: Per field kind: the field, a value that holds, and a value of the wrong shape.
CASES: dict[str, tuple[FieldShape, object, object]] = {
    "integer": (shapes.integer("value", 0, 10), 5, 11),
    "key": (shapes.key("value"), "some_key", "Some_Key"),
    "choice": (shapes.choice("value", ("first", "second")), "first", "third"),
    "text": (shapes.text("value"), "some words", " padded "),
    "identity": (shapes.identity("value"), _IDENTITY, "not-a-uuid"),
    "hex64": (shapes.hex64("value"), _HEX64, _HEX64[:-1]),
    "seed": (shapes.seed("value"), _HEX64, _HEX64[:-1]),
    "texture_set_id": (shapes.texture_set_id("value"), None, "Not A Set Id"),
    # A float never reaches the scalar branch: canonical form refuses it first. A bool does.
    "scalar": (shapes.scalar("value"), 5, True),
    "integers": (shapes.integers("value", 0, 10, count_minimum=1), (1, 2), (1, 11)),
    "keys": (shapes.keys("value", count_minimum=1), ("some_key",), ("Some_Key",)),
    "choices": (
        shapes.choices("value", ("first", "second"), count_minimum=1),
        ("first",),
        ("third",),
    ),
    "identities": (shapes.identities("value", count_minimum=1), (_IDENTITY,), ("not-a-uuid",)),
    "texts": (FieldShape("value", "texts", count_minimum=1), ("some words",), (" padded ",)),
    "points": (shapes.points("value", 2), ((0, 0), (1_000, 0)), ((0, 0, 0),)),
    "ring": (shapes.ring("value"), _RING, _RING[:2]),
    "rings": (shapes.rings("value"), (_RING,), (_RING[:2],)),
    "record": (shapes.record("value", EXTENT_SHAPE), _EXTENT, 5),
    "records": (shapes.records("value", EXTENT_SHAPE, count_minimum=1), (_EXTENT,), (5,)),
}


def _one_field_shape(field_shape: FieldShape) -> RecordShape:
    """A record of exactly this one field, so validation reaches the field and nothing else."""
    record_type = dataclasses.make_dataclass(
        "OneField", [("value", object)], frozen=True, slots=True
    )
    return RecordShape(record_type, (field_shape,))


@pytest.mark.parametrize("kind", FIELD_KINDS)
def test_every_declared_field_kind_holds_a_good_value_and_refuses_a_bad_one(kind):
    assert kind in CASES, (
        f"field kind {kind!r} is declared in FIELD_KINDS and has no case here. Add one: a kind "
        "with no case is a kind nothing validates."
    )
    field_shape, holds, refused = CASES[kind]
    assert field_shape.kind == kind, (field_shape.kind, kind)
    if kind == "texture_set_id":
        holds = _published_set_id()
    shape = _one_field_shape(field_shape)
    # A branch that has gone missing shows up here: the good value stops validating.
    validate = shapes.validate_record
    validate(shape.record_type(holds), shape)
    with pytest.raises((InvalidRecordError, InvalidSeedError)):
        validate(shape.record_type(refused), shape)


def test_the_cases_cover_the_declared_kinds_and_nothing_else():
    """A case for a kind the grammar does not declare would be testing a branch nobody can reach."""
    assert sorted(CASES) == sorted(FIELD_KINDS)
