"""Seats in the world object catalog: where a resting person is drawn, and what is refused.

A seat is declared once per row in version 2 and its height is derived from the parts under it.
Version 2 is version 1 with seats: the same meshes and the same society rows, so the reviewed
rows migration 0105 pinned and every registry digest stay where they are.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable
from typing import Any

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.assets import reviewed_asset_of
from exulanica.world.object_catalog import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
    SEATED_ACTIVITY,
    SIDES,
    PartsRecipe,
    load_world_object_catalog,
    world_object_catalog,
)
from exulanica.world.society_composition import REVIEWED_REACH_MM, reviewed_assignment


def _document(version: int = CATALOG_VERSION) -> dict[str, Any]:
    return json.loads((CATALOG_DIRECTORY / f"world-object.v{version}.json").read_text())


def _entry(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(entry for entry in document["entries"] if entry["key"] == key)


def _load(tmp_path: pathlib.Path, document: dict[str, Any], version: int = CATALOG_VERSION):
    for number in range(1, CATALOG_VERSION + 1):
        name = f"world-object.v{number}.json"
        (tmp_path / name).write_bytes((CATALOG_DIRECTORY / name).read_bytes())
    (tmp_path / f"world-object.v{version}.json").write_text(json.dumps(document))
    return load_world_object_catalog(tmp_path, version)


def test_every_resting_place_of_a_kind_with_rows_has_a_seat_on_a_box_top():
    """Each seat lies on the level top of a box part of its own kind, at that top's height."""
    seated = 0
    for kind in world_object_catalog().kinds:
        use = kind.use
        if use.seats is None:
            assert use.rows is None, kind.key
            continue
        assert len(use.seats) == len(use.places or ()) == len(use.facing or ()), kind.key
        if use.affordance != SEATED_ACTIVITY:
            assert set(use.seats) <= {None}, kind.key
            continue
        assert isinstance(kind.recipe, PartsRecipe)
        for seat in use.seats:
            assert seat is not None, kind.key
            x, y, z = seat.position_mm
            assert seat.faces in SIDES
            tops = [
                part.form
                for part in kind.recipe.parts
                if part.form.shape == "box"
                and part.form.offset_z_mm + part.form.size_z_mm == z
                and 2 * abs(x - part.form.offset_x_mm) <= part.form.size_x_mm
                and 2 * abs(y - part.form.offset_y_mm) <= part.form.size_y_mm
            ]
            assert tops, (kind.key, seat)
            seated += 1
    # Three bench seats, two chairs and four places on the planter's ledge.
    assert seated == 9


def test_the_published_seats_are_the_seat_parts_the_recipes_draw():
    """The heights come from the parts: the bench and planter tops at 480, the chairs at 450."""
    kinds = world_object_catalog().by_key()
    heights = {
        key: {seat.position_mm[2] for seat in kinds[key].use.seats or () if seat is not None}
        for key in ("bench", "cafe_table", "seating_planter")
    }
    assert heights == {"bench": {480}, "cafe_table": {450}, "seating_planter": {480}}
    chairs = [seat for seat in kinds["cafe_table"].use.seats or () if seat is not None]
    # The front place's person takes the chair at -x and faces the table, and the back place's
    # person the chair at +x.
    assert [(s.position_mm[0] < 0, s.faces) for s in chairs] == [(True, "+x"), (False, "-x")]


def test_a_row_keeps_its_spacing_on_its_seats():
    bench = world_object_catalog().by_key()["bench"].use
    assert [seat.position_mm[0] for seat in bench.seats or () if seat] == [
        x for x, _ in bench.places or ()
    ]


def test_a_person_standing_at_a_place_faces_across_its_side_toward_the_kind():
    kinds = world_object_catalog().by_key()
    assert kinds["market_stall"].use.facing == ("-y", "-y")
    assert kinds["planter_tree"].use.facing == ("-y", "-x", "+y", "+x")


def test_version_2_is_version_1_with_seats_the_same_meshes_and_society_rows():
    """If this fails, seats moved a mesh or a registry row, and 0105 or a society digest with it."""
    earlier = load_world_object_catalog(version=1)
    current = world_object_catalog()
    assert current.version == 2
    assert [kind.key for kind in earlier.kinds] == [kind.key for kind in current.kinds]
    for old, new in zip(earlier.kinds, current.kinds, strict=True):
        assert (old.asset_key, old.title, old.summary, old.recipe, old.dimensions_mm) == (
            new.asset_key,
            new.title,
            new.summary,
            new.recipe,
            new.dimensions_mm,
        ), new.key
        assert (old.materials, old.licence) == (new.materials, new.licence), new.key
        # Every declaration a measurement cites says what it said; a seat point has its own.
        assert {k: v for k, v in new.declared.items() if k != "seat_point"} == dict(old.declared)
        assert old.use.places == new.use.places, new.key
        assert reviewed_assignment(old, REVIEWED_REACH_MM) == reviewed_assignment(
            new, REVIEWED_REACH_MM
        ), new.key
        assert reviewed_asset_of(old).content_sha256 == reviewed_asset_of(new).content_sha256
        assert old.use.seats is None or set(old.use.seats) <= {None}, old.key


def _set(key: str, path: list[Any], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(document: dict[str, Any]) -> None:
        target: Any = _entry(document, key)
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value

    return mutate


def _seat_on_the_stall(document: dict[str, Any]) -> None:
    entry = _entry(document, "market_stall")
    entry["use"]["places"][0]["seat"] = {
        "x_mm": 0,
        "y_mm": 0,
        "faces": "+y",
        "source": "declared/seat_point",
    }
    entry["declared"]["seat_point"] = "A seat at a counter people visit."


SEAT_REFUSALS: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    (
        "a seat over no part",
        _set("bench", ["use", "places", 0, "seat", "y_mm"], 400),
        "no part lies under the seat",
    ),
    (
        "a seat on a round top",
        _set("cafe_table", ["use", "places", 0, "seat", "x_mm"], 0),
        "lies on a prism",
    ),
    (
        "a seat facing a side the part frame does not have",
        _set("bench", ["use", "places", 0, "seat", "faces"], "up"),
        "faces is one of",
    ),
    (
        "a seat citing a declaration the kind lacks",
        _set("bench", ["use", "places", 0, "seat", "source"], "declared/nothing"),
        "does not declare",
    ),
    ("a seat at a kind people visit", _seat_on_the_stall, "a seat is where a resting person sits"),
    (
        "a row with no seat field",
        _set("market_stall", ["use", "places"], [{"side": "+y", "count": 2}]),
        "exactly",
    ),
]


def test_the_published_file_loads_through_the_path_the_seat_refusals_take(tmp_path):
    """Positive control: an unchanged copy loads, so each refusal below is its own mutation's."""
    assert _load(tmp_path, _document()).sha256 == world_object_catalog().sha256


@pytest.mark.parametrize(
    ("mutate", "match"),
    [(m, s) for _, m, s in SEAT_REFUSALS],
    ids=[name for name, _, _ in SEAT_REFUSALS],
)
def test_the_loader_refuses_a_seat_by_name(tmp_path, mutate, match):
    document = _document()
    mutate(document)
    with pytest.raises(CatalogError, match=match):
        _load(tmp_path, document)


def test_version_1_admits_no_seat(tmp_path):
    document = _document(1)
    _entry(document, "bench")["use"]["places"][0]["seat"] = None
    with pytest.raises(CatalogError, match="exactly"):
        _load(tmp_path, document, 1)
