"""The key a version's town read is kept under (``exulanica/world/version_town.py``): the world,
its snapshot and the fold of the version's changes to the town's buildings, None with none.

Pure: the version's changes are stood in for the rows they are read from.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.world import version_town
from exulanica.world.site_parts import PartChangeRefused
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.version_tiles import changes_fold

WORKSPACE = uuid.UUID("00000000-0000-4000-8000-000000000001")
SNAPSHOT = uuid.UUID("00000000-0000-4000-8000-000000000002")
VERSION = uuid.UUID("00000000-0000-4000-8000-000000000003")
WORLD = "world:generated:00000000-0000-4000-8000-000000000004"


def _key(monkeypatch, changes):
    monkeypatch.setattr(version_town, "version_changes", lambda *args: changes)
    return version_town.town_key(None, WORKSPACE, WORLD, SNAPSHOT, VERSION)


def test_a_version_with_no_changes_is_keyed_as_the_town_alone(monkeypatch):
    assert _key(monkeypatch, {}) == ((WORLD, SNAPSHOT, None), {})


def test_versions_with_different_changes_never_share_a_key(monkeypatch):
    removed = {"building:a": BuildingChange(removed=True)}
    taller = {"building:a": BuildingChange(storeys=4)}
    lower = {"building:a": BuildingChange(storeys=2)}
    keys = {_key(monkeypatch, changes)[0] for changes in ({}, removed, taller, lower)}
    assert len(keys) == 4
    assert _key(monkeypatch, removed)[0] == (WORLD, SNAPSHOT, changes_fold(removed))


def test_the_same_changes_give_the_same_key_in_any_order(monkeypatch):
    first = {"building:a": BuildingChange(removed=True), "building:b": BuildingChange(storeys=3)}
    second = dict(reversed(list(first.items())))
    assert _key(monkeypatch, first)[0] == _key(monkeypatch, second)[0]


def test_a_change_the_town_does_not_take_is_refused_by_name_where_the_input_is_composed(
    monkeypatch,
):
    def moved(*args):
        raise PartChangeRefused(
            "part_not_changeable", {"part_id": "building:a"}, "A town's building is not moved."
        )

    monkeypatch.setattr(version_town, "version_changes", moved)
    assert version_town.town_key(None, WORKSPACE, WORLD, SNAPSHOT, VERSION) == (None, {})
    with pytest.raises(UnavailableSocietyInput, match="part_not_changeable"):
        version_town.composed_town_key(None, WORKSPACE, WORLD, SNAPSHOT, VERSION)
