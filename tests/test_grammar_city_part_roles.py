"""A street tree's parts take the trunk and canopy roles; every other object's take object roles.

Roles 25 (``canopy``) and 26 (``trunk``) were appended so bark and foliage can be dressed apart
from each other and from furniture metal. The codes themselves are pinned with every other code in
``tests/test_grammar_subjects.py``; this file holds who may use them.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.grammar.errors import CatalogError, InvalidRecordError
from exulanica.grammar.grammars.city.catalogs import form_parts_field
from exulanica.grammar.grammars.city.common import SURFACE_ROLE_CODES
from exulanica.grammar.grammars.city.massing import ROOFTOP_SHAPE
from exulanica.grammar.grammars.city.material import SURFACE_ROLE_OWNERS
from exulanica.grammar.grammars.city.streetlife import FURNITURE_SHAPE, TREE_SHAPE
from exulanica.grammar.shapes import validate_record

from city_v2_fixture import builder

FIXTURE = builder()


def test_the_tree_roles_are_appended_after_every_earlier_code():
    assert (SURFACE_ROLE_CODES["canopy"], SURFACE_ROLE_CODES["trunk"]) == (25, 26)
    assert (
        max(code for role, code in SURFACE_ROLE_CODES.items() if role not in {"canopy", "trunk"})
        == 24
    )


def test_only_a_street_tree_owns_a_trunk_or_a_canopy_and_a_tree_owns_no_object_role():
    assert SURFACE_ROLE_OWNERS["canopy"] == SURFACE_ROLE_OWNERS["trunk"] == ("city.street_tree",)
    for role in ("object_primary", "object_secondary", "object_tertiary"):
        assert "city.street_tree" not in SURFACE_ROLE_OWNERS[role]


def test_the_fixture_tree_has_a_trunk_and_a_canopy():
    [tree] = FIXTURE.trees
    assert [part.surface_role for part in tree.parts] == ["trunk", "canopy"]
    validate_record(tree, TREE_SHAPE)


def test_a_tree_part_with_an_object_role_is_refused():
    [tree] = FIXTURE.trees
    trunk, canopy = tree.parts
    changed = dataclasses.replace(
        tree, parts=(dataclasses.replace(trunk, surface_role="object_primary"), canopy)
    )
    with pytest.raises(InvalidRecordError, match="a street tree's part 0"):
        validate_record(changed, TREE_SHAPE)


@pytest.mark.parametrize("role", ["trunk", "canopy"])
def test_furniture_and_rooftop_parts_with_a_tree_role_are_refused(role):
    bench = FIXTURE.furniture[0]
    first, *rest = bench.parts
    with pytest.raises(InvalidRecordError, match="an item of furniture's part 0"):
        validate_record(
            dataclasses.replace(
                bench, parts=(dataclasses.replace(first, surface_role=role), *rest)
            ),
            FURNITURE_SHAPE,
        )
    tank = FIXTURE.rooftops[1]
    first, *rest = tank.parts
    with pytest.raises(InvalidRecordError, match="a rooftop object's part 0"):
        validate_record(
            dataclasses.replace(tank, parts=(dataclasses.replace(first, surface_role=role), *rest)),
            ROOFTOP_SHAPE,
        )


def test_a_catalog_part_with_a_tree_role_is_refused():
    part = {
        "shape": "box",
        "surface_role": "canopy",
        "offset_x_mm": 0,
        "offset_y_mm": 0,
        "offset_z_mm": 0,
        "size_x_mm": 100,
        "size_y_mm": 100,
        "size_z_mm": 100,
        "top_scale_millionths": 1_000_000,
        "segments": 4,
        "rings": 1,
    }
    with pytest.raises(CatalogError, match="takes an object role"):
        form_parts_field("parts", [part])
    assert form_parts_field("parts", [{**part, "surface_role": "object_primary"}])
