"""Declared parameters and recipe/representation provenance refuse coercion and drift."""

import uuid

import pytest
from exulanica.world.character_appearance import CharacterSubject, validate_recipe

from character_appearance_fixtures import family, recipe


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
