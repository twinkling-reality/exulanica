"""A made town as a version's changes to its buildings leave it, read by the version's society and
by the landing for its placed things.

A made town's records are generated again from its receipt (:func:`~exulanica.world.
generated_worlds.town_records`). A version whose buildings a person removed or stood taller or
lower (:mod:`exulanica.world.town_parts`) reads the records the city grammar generates with those
changes (:func:`~exulanica.world.generated_worlds.town_records_with`), so its people walk, and its
things land, in the changed town: a removed building's premises and base ring are gone, and a
taller or lower one stands its own massing.

A town read is kept under :data:`TownKey`, the world, the snapshot and the fold of the version's
changes (:func:`~exulanica.world.version_tiles.changes_fold`). The fold is None for a version with
no changes, which reads the town exactly as it was made, so two versions with different changes
never share a read, and the same changes give the same key however many undos led there.

A taller building adds homes to the town and takes none from its neighbours: the changed town's
place is made with the town's records as made (:func:`made_town_records`), so every premises the
changes leave alone houses the people it housed as made, and a changed one the places its new
floor holds at the made town's density
(:func:`~exulanica.world.society_city_place.place_from_city_records`). Nobody is rehomed by a
change: a society over a changed town is given the made town's head count
(:func:`~exulanica.world.society_walking_surfaces.town_head_count`), the people already housed
keep their homes, and a taller building's new homes stay empty. Whether a building someone lives
or works in may be removed or lowered is decided where the change is made, not here.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TypeAlias

import psycopg

from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import GeneratedRecords, town_records, town_records_with
from exulanica.world.site_parts import PartChangeRefused
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.version_tiles import changes_fold, version_changes

__all__ = [
    "TownKey",
    "composed_town_key",
    "made_town_records",
    "town_and_made",
    "town_key",
    "version_town_records",
]

#: A town read's key: the world, its snapshot, and the fold of the version's changes to its
#: buildings, None with none.
TownKey: TypeAlias = tuple[str, uuid.UUID, str | None]


def town_key(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    version_id: uuid.UUID,
) -> tuple[TownKey | None, Mapping[str, BuildingChange]]:
    """The key a version's town read is kept under, and the version's changes to the town's
    buildings (:func:`~exulanica.world.version_tiles.version_changes`): none for a world whose
    records no recipe's composer states. Rows only, so it is read under the asset read lock as
    before it. ``(None, {})`` where the version holds a change the town does not take (a building
    moved), which :func:`composed_town_key` refuses by name."""
    try:
        changes = version_changes(connection, workspace_id, world_id, snapshot_id, version_id)
    except (InvalidStructuralData, PartChangeRefused):
        return None, {}
    return (world_id, snapshot_id, changes_fold(changes) if changes else None), changes


def composed_town_key(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    version_id: uuid.UUID,
) -> TownKey:
    """:func:`town_key` as the society's input is composed under the asset read lock, a change
    the town does not take refused as the input is: ``UnavailableSocietyInput``, by name."""
    try:
        changes = version_changes(connection, workspace_id, world_id, snapshot_id, version_id)
    except PartChangeRefused as exc:
        raise UnavailableSocietyInput(
            f"the world's records are unreadable: {exc.code}: {exc}"
        ) from exc
    except InvalidStructuralData as exc:
        raise UnavailableSocietyInput(f"the world's records are unreadable: {exc}") from exc
    return (world_id, snapshot_id, changes_fold(changes) if changes else None)


def version_town_records(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    changes: Mapping[str, BuildingChange],
) -> GeneratedRecords:
    """A made town's records with ``changes`` to its buildings (:func:`~exulanica.world.
    generated_worlds.town_records_with`), its records as made with none. A world whose grammar or
    catalogs no longer generate it, or refuse the changes, is refused by name
    (``InvalidStructuralData``)."""
    try:
        return town_records_with(connection, workspace_id, world_id, snapshot_id, changes)
    except GrammarError as exc:
        raise InvalidStructuralData(
            f"generated_world_unreadable: the town's grammar refuses its changes: {exc}"
        ) from exc


def made_town_records(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    changes: Mapping[str, BuildingChange],
) -> tuple[object, ...] | None:
    """A made town's records as made, generated again from its receipt (:func:`~exulanica.world.
    generated_worlds.town_records`, kept by the receipt's digest), where ``changes`` change its
    buildings: what the changed town's homes and head count are read against. None with no
    changes, whose town is read exactly as it was made."""
    if not changes:
        return None
    return tuple(town_records(connection, workspace_id, world_id, snapshot_id).records)


def town_and_made(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    changes: Mapping[str, BuildingChange],
) -> tuple[GeneratedRecords, tuple[object, ...] | None]:
    """A made town's records with ``changes`` (:func:`version_town_records`) and its records as
    made where there are any (:func:`made_town_records`), refused alike by name."""
    scope = (connection, workspace_id, world_id, snapshot_id)
    return version_town_records(*scope, changes), made_town_records(*scope, changes)
