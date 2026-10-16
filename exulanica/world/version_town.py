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

Nobody is rehomed by a change: a town's head count is fixed when its society is made, the people
already housed keep their homes, and a taller building's new homes stay empty. Whether a building
someone lives or works in may be removed or lowered is decided where the change is made, not here.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TypeAlias

import psycopg

from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import GeneratedRecords, town_records_with
from exulanica.world.site_parts import PartChangeRefused
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.version_tiles import changes_fold, version_changes

__all__ = ["TownKey", "composed_town_key", "town_key", "version_town_records"]

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
