"""Declared parameters and recipe/representation provenance refuse coercion and drift."""

import uuid
from typing import get_args

import pytest
from exulanica.world.character_appearance import CharacterSubject, Parameter, validate_recipe

from character_appearance_fixtures import family, recipe

#: Per declared parameter kind: its declaration, a value that holds, and one that does not.
PARAMETER_CASES = {
    "integer": (
        dict(key="height", kind="integer", minimum=145, maximum=205, default=175),
        150,
        206,
    ),
    "choice": (
        dict(key="clothing", kind="choice", choices=["shirt", "coat"], default="shirt"),
        "coat",
        "undeclared",
    ),
    "color": (dict(key="color", kind="color", default="#eeeeee"), "#402080", "#FFFFFF"),
}


@pytest.mark.parametrize("kind", get_args(Parameter.model_fields["kind"].annotation))
def test_every_declared_parameter_kind_has_rules_of_its_own(kind):
    """The kinds come from the annotation, so a kind added there without rules fails here.

    Parameter.validate_value used to check integer, then choice, then treat everything else as a
    colour, so a fourth kind would have been rejected for not being hex. The coverage is read
    from the Literal rather than listed, and a kind with no case below fails rather than being
    skipped.
    """
    assert kind in PARAMETER_CASES, (
        f"parameter kind {kind!r} is declared and has no case here. Add one: a kind with no case "
        "is a kind whose rules nothing exercises."
    )
    declaration, holds, refused = PARAMETER_CASES[kind]
    parameter = Parameter(**declaration)
    parameter.validate_value(holds)
    with pytest.raises(ValueError):
        parameter.validate_value(refused)


def test_a_parameter_kind_with_no_rules_says_so_instead_of_naming_hex_digits():
    """Reached by bypassing the annotation, because that is the only way in until somebody adds a
    kind. What it pins is the message: the next person is sent to the missing rules, not to a
    colour they never wrote."""
    parameter = Parameter.model_construct(key="gradient", kind="gradient", default="#402080")
    with pytest.raises(ValueError, match="no rules here"):
        parameter.validate_value("#402080")


@pytest.mark.parametrize(
    "change",
    [
        {"height": True},
        {"height": "175"},
        {"height": 206},
        {"height": float("nan")},
        {"clothing": "undeclared"},
        {"color": "red"},
        {"color": "#FFFFFF"},
        {"extra": 1},
    ],
)
def test_invalid_or_undeclared_values_are_not_coerced(change):
    definition = family()
    params = {**recipe(definition).parameters, **change}
    with pytest.raises(ValueError):
        validate_recipe(
            recipe(definition, parameters=params),
            definition,
            CharacterSubject(kind="avatar", subject_id=uuid.uuid4()),
        )


def test_family_revision_and_representation_are_exact():
    definition = family()
    subject = CharacterSubject(kind="avatar", subject_id=uuid.uuid4())
    for value in [
        recipe(definition, family_sha256="3" * 64),
        recipe(definition, representation_id="invented"),
    ]:
        with pytest.raises(ValueError):
            validate_recipe(value, definition, subject)
    assert family(family_revision="2").sha256 != definition.sha256
    assert validate_recipe(recipe(definition), definition, subject) is None


def test_observed_people_and_incomplete_subjects_are_outside_this_boundary():
    for values in [
        dict(kind="observed-person", subject_id=uuid.uuid4()),
        dict(kind="synthetic-inhabitant", subject_id=uuid.uuid4()),
        dict(kind="avatar", subject_id=uuid.uuid4(), society_id=uuid.uuid4()),
    ]:
        with pytest.raises(ValueError):
            CharacterSubject.model_validate(values)
