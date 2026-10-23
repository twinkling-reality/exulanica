"""A made town's tiles as a version with changes to its buildings draws them: its workspace's alone.

A made town's tiles are baked once from public inputs and shared (migration 0072,
:func:`~exulanica.world.generated_worlds.generated_tiles`). A version whose buildings a person
removed or stood taller or lower (:mod:`exulanica.world.town_parts`) draws some tiles otherwise,
and a tile carrying a person's change is not public, so it is baked for the version's workspace,
kept in ``world_version_baked_tile`` and its bytes in the workspace's own ``version-tiles``
namespace (migration 0219).

**Which tiles change** (:func:`changed_tiles`) is read from the tiles themselves: the town's tile
documents are made from its records with the version's changes and without them, and a tile whose
document differs is changed. A change is felt beyond its own building (a removed building's
neighbour shows a wall where it had a party wall, and that neighbour may lie in a tile whose halo
does not reach the removed building), so no list of the buildings a tile carries says it. A tile
whose document is the same draws the public bake.

**A changed tile's key** folds every change of the version, in identity order, into the tile
record's edit delta digest (:func:`changes_fold`), the field the tile key reserves for edits
(:mod:`exulanica.grammar.grammars.city.tile`). The changes are state, not a log: the same changes
give the same key however many undos led there, and a bake is shared by every version of the
workspace with the same changes.

**Baking** is the tile worker's (:mod:`exulanica.ingest.generated_tiles`):
:func:`queue_version_bakes` queues one ``bake_version_tile`` job for each changed tile not yet
stored, naming the version, the tile, its inputs digest and the fold, and never the changes,
which live in the version alone and are erased with it. The worker reads them from the version,
records the bytes in the namespace's inventory as the runtime role and puts them, both under the
purger's lock for those bytes, and publishes the bake through ``record_version_baked_tile``, which
writes only for that claimed job.

**Serving** (:func:`serve_version_tile`) reads a stored bake of the session's workspace, its bytes
from the workspace's namespace, holds them to the row's digest and checks the row again under the
final read check, as a public tile is served
(:class:`~exulanica.world.baked_tiles.BakedTileRepository`).

A world's erasure and its workspace's take the rows and the bytes (migration 0219).
"""

from __future__ import annotations

import dataclasses
import hashlib
import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.db.read_check import final_read_check
from exulanica.errors import BlobNotFoundError
from exulanica.evidence.blob import BlobId
from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city.generation.massing import BuildingChange
from exulanica.grammar.grammars.city.generation.tiles import edit_delta_digest
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.store.base import ContentAddressedStore
from exulanica.world.baked_tiles import BakedTileFaulted, TileBytesMissing, UnknownBakedTile
from exulanica.world.composers import composer_module
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import (
    GeneratedTile,
    hold_bake_queue,
    states_records,
    town_records,
    town_records_with,
)
from exulanica.world.object_repository import WorldObjectRepository

__all__ = [
    "VERSION_BAKE_JOB_KIND",
    "ChangedTile",
    "VersionBakedTile",
    "changed_tiles",
    "changes_fold",
    "changes_payload",
    "folded",
    "forget_changed_tiles",
    "queue_version_bakes",
    "serve_version_tile",
    "stored_version_bake",
    "version_changes",
    "version_tile_states",
]

#: The job kind that bakes one tile of a version with changes to its buildings, off the request.
VERSION_BAKE_JOB_KIND: Final = "bake_version_tile"
#: How many towns' changed tiles one process keeps in memory, by receipt and changes. Finding them
#: makes every tile document twice (0.2 s each for the small town on the development machine);
#: the entry of a changed town is read on every listing.
_KEPT: Final = 8

_lock = threading.Lock()
_kept: OrderedDict[str, tuple[ChangedTile, ...]] = OrderedDict()
_epoch = 0


@dataclass(frozen=True, slots=True)
class ChangedTile:
    """A tile a version's changes alter: where it is, and the key its bake is stored under."""

    tile_x: int
    tile_y: int
    #: The digest over the tile's bake inputs with the changes folded in, its bake's key.
    tile_inputs_digest: str
    #: The fold of the version's changes the tile record carries (:func:`changes_fold`).
    edit_delta_digest: str


@dataclass(frozen=True, slots=True)
class VersionBakedTile:
    """One stored bake of a version's changed tile, as the session's workspace holds it."""

    baked_tile_id: uuid.UUID
    world_id: str
    tile_x: int
    tile_y: int
    tile_inputs_digest: str
    container_sha256: str
    container_bytes: int
    state: str

    @property
    def servable(self) -> bool:
        """Baked and agreed with itself. A fault is never cleared for a workspace's own bake: the
        version's tile is baked again once the bake is deterministic again."""
        return self.state == "baked"


def forget_changed_tiles(digests: frozenset[str]) -> None:
    """Evict removed worlds' changed tiles in this process, as their records are
    (:func:`~exulanica.world.generated_worlds.forget_generated_records`)."""
    global _epoch
    with _lock:
        _epoch += 1
        for key in list(_kept):
            if key.split(":", 1)[0] in digests:
                del _kept[key]


def version_changes(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    version_id: uuid.UUID,
) -> dict[str, BuildingChange]:
    """A version's changes to a made town's buildings, by building identity; none for a world
    whose records no recipe's composer states (a site world's parts are drawn from its site)."""
    from exulanica.world.town_parts import building_changes

    if not states_records(connection, workspace_id, world_id, snapshot_id):
        return {}
    repository = WorldObjectRepository(connection, workspace_id, world_id=world_id)
    return building_changes(repository.part_changes(version_id))


def changes_payload(changes: Mapping[str, BuildingChange]) -> dict[str, dict[str, Any]]:
    """A version's changes to its buildings as a job names them, by identity."""
    return {
        identity: {"removed": change.removed, "storeys": change.storeys}
        for identity, change in sorted(changes.items())
    }


def changes_fold(changes: Mapping[str, BuildingChange]) -> str:
    """The edit delta digest a changed tile's record carries: the city grammar's fold
    (:func:`~exulanica.grammar.grammars.city.generation.tiles.edit_delta_digest`) over each change's
    digest in identity order, the digest of its identity, removal and storeys."""
    return edit_delta_digest(
        [
            sha256_of_canonical({"identity": identity, **fields})
            for identity, fields in changes_payload(changes).items()
        ]
    )


def folded(document: Any, fold: str) -> Any:
    """A tile document with ``fold`` as its tile record's edit delta digest: what a version's
    changed tile is baked from and keyed by."""
    return dataclasses.replace(
        document, tile=dataclasses.replace(document.tile, edit_delta_digest=fold)
    )


def changed_tiles(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    changes: Mapping[str, BuildingChange],
) -> tuple[ChangedTile, ...]:
    """The tiles of a made town whose documents a version's changes alter, each with the key its
    bake is stored under, in the receipt's order; none with no changes. Refused by name
    (``InvalidStructuralData``) when the town's grammar refuses the changes or their documents."""
    if not changes:
        return ()
    base = town_records(connection, workspace_id, world_id, snapshot_id)
    fold = changes_fold(changes)
    key = f"{base.receipt_sha256}:{fold}"
    with _lock:
        epoch = _epoch
        found = _kept.get(key)
        if found is not None:
            _kept.move_to_end(key)
    if found is None:
        composer = base.receipt["composer"]
        module = composer_module(composer["key"], composer["version"])
        try:
            changed = town_records_with(connection, workspace_id, world_id, snapshot_id, changes)
            before = module.tile_documents(base.receipt, base.records)
            after = module.tile_documents(base.receipt, changed.records)
        except GrammarError as exc:
            raise InvalidStructuralData(
                f"generated_world_unreadable: the town's grammar refuses its changes: {exc}"
            ) from exc
        found = tuple(
            ChangedTile(
                tile_x=document.tile.tile_x,
                tile_y=document.tile.tile_y,
                tile_inputs_digest=tile_inputs_digest(folded(document, fold).tile),
                edit_delta_digest=fold,
            )
            for unedited, document in zip(before, after, strict=True)
            if module.tile_document_bytes(unedited) != module.tile_document_bytes(document)
        )
        with _lock:
            if epoch == _epoch:
                _kept[key] = found
                while len(_kept) > _KEPT:
                    _kept.popitem(last=False)
    return found


_COLUMNS: Final = (
    "baked_tile_id, world_id, tile_x, tile_y, tile_inputs_digest, container_sha256, "
    "container_bytes, state"
)
#: The bake stage this installation runs (migration 0144): a version's bake is found by its inputs
#: under it, as a public one is.
_CURRENT_STAGE: Final = (
    "(stage_version, stage_params_sha256) in (select s.stage_version, s.stage_params_sha256 "
    "from baked_tile_stage s where s.retired_at is null)"
)


def _row(row: Mapping[str, Any]) -> VersionBakedTile:
    return VersionBakedTile(
        baked_tile_id=row["baked_tile_id"],
        world_id=str(row["world_id"]),
        tile_x=int(row["tile_x"]),
        tile_y=int(row["tile_y"]),
        tile_inputs_digest=bytes(row["tile_inputs_digest"]).hex(),
        container_sha256=bytes(row["container_sha256"]).hex(),
        container_bytes=int(row["container_bytes"]),
        state=str(row["state"]),
    )


def stored_version_bake(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, tile_inputs_digest: str
) -> VersionBakedTile | None:
    """The world's bake of the changed tile whose inputs have this digest under the stage this
    installation runs, or None."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from world_version_baked_tile where workspace_id = %s "
            f"and world_id = %s and tile_inputs_digest = %s and {_CURRENT_STAGE}",
            (workspace_id, world_id, bytes.fromhex(tile_inputs_digest)),
        ).fetchone()
    return None if row is None else _row(row)


def _latest_job(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, tile: ChangedTile
) -> str | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select state from job where workspace_id=%s and kind=%s "
            "and payload->>'world_id'=%s and payload->>'tile_inputs_digest'=%s "
            "order by created_at desc, job_id desc limit 1",
            (workspace_id, VERSION_BAKE_JOB_KIND, world_id, tile.tile_inputs_digest),
        ).fetchone()
    return None if row is None else str(row["state"])


def version_tile_states(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    tiles: Sequence[ChangedTile],
) -> dict[tuple[int, int], GeneratedTile]:
    """Where each changed tile's bake stands, by coordinate, read as a public tile's is:
    ``baked`` when its bake is stored and agreed with itself and its job is done (or none was
    queued), ``failed`` when its bake was found nondeterministic or its job ended failed or
    cancelled, ``baking`` until then."""
    found = {}
    for tile in tiles:
        bake = stored_version_bake(connection, workspace_id, world_id, tile.tile_inputs_digest)
        ended = _latest_job(connection, workspace_id, world_id, tile)
        state: Literal["baked", "baking", "failed"]
        if (bake is not None and not bake.servable) or ended in ("failed", "cancelled"):
            state = "failed"
        elif bake is not None and ended in (None, "done"):
            state = "baked"
        else:
            state = "baking"
        found[(tile.tile_x, tile.tile_y)] = GeneratedTile(
            tile_x=tile.tile_x,
            tile_y=tile.tile_y,
            tile_inputs_digest=tile.tile_inputs_digest,
            baked_tile_id=None if bake is None or state == "baking" else bake.baked_tile_id,
            state=state,
        )
    return found


def queue_version_bakes(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    version_id: uuid.UUID,
    changes: Mapping[str, BuildingChange],
) -> tuple[ChangedTile, ...]:
    """Queue a ``bake_version_tile`` job for each tile the version's changes alter whose bake is
    not stored and not already queued or running, in the caller's transaction, and return the
    tiles queued. A tile stored with a fault queues one again, whose job fails as every bake of it
    does until the bake is deterministic again; so does a tile whose latest job ended failed or
    cancelled beside a servable stored bake, which reads failed until a job of its own ends done
    (:func:`version_tile_states`). It checks and queues under the world's bake queue lock
    (:func:`~exulanica.world.generated_worlds.hold_bake_queue`), as a public tile's queue does."""
    if not changes:
        return ()
    base = town_records(connection, workspace_id, world_id, snapshot_id)
    queued = []
    with connection.transaction():
        hold_bake_queue(connection, workspace_id, world_id)
        for tile in changed_tiles(connection, workspace_id, world_id, snapshot_id, changes):
            stored = stored_version_bake(
                connection, workspace_id, world_id, tile.tile_inputs_digest
            )
            ended = _latest_job(connection, workspace_id, world_id, tile)
            if ended in ("queued", "running"):
                continue
            if stored is not None and stored.servable and ended not in ("failed", "cancelled"):
                continue
            connection.execute(
                "insert into job (workspace_id,kind,payload) values (%s,%s,%s)",
                (
                    workspace_id,
                    VERSION_BAKE_JOB_KIND,
                    Jsonb(
                        {
                            "world_id": world_id,
                            "snapshot_id": str(snapshot_id),
                            "receipt_sha256": base.receipt_sha256,
                            "version_id": str(version_id),
                            "tile": [tile.tile_x, tile.tile_y],
                            "tile_inputs_digest": tile.tile_inputs_digest,
                            "edit_delta_digest": tile.edit_delta_digest,
                        }
                    ),
                ),
            )
            queued.append(tile)
    return tuple(queued)


def serve_version_tile(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    workspace_id: uuid.UUID,
    world_id: str,
    baked_tile_id: uuid.UUID,
) -> tuple[VersionBakedTile, bytes]:
    """A stored bake of the world and its bytes from its workspace's namespace,
    held to the row's digest, then the row checked again under the final read check, so a bake
    that stopped being servable while it was read is refused. ``connection`` must be idle. Never
    charged: a version's tiles are its world's, bounded as the world's public tiles are."""
    tile = _servable(connection, workspace_id, world_id, baked_tile_id)
    try:
        data = store.get(BlobId(bytes.fromhex(tile.container_sha256)))
    except BlobNotFoundError as error:
        raise TileBytesMissing(
            f"version tile {baked_tile_id} is recorded and its bytes are not in the store"
        ) from error
    if hashlib.sha256(data).hexdigest() != tile.container_sha256 or len(data) != (
        tile.container_bytes
    ):
        raise TileBytesMissing(f"version tile {baked_tile_id}'s bytes are not what it records")
    with final_read_check(
        connection, not_idle="a version's tile is served only on an idle connection"
    ):
        current = _read(connection, workspace_id, world_id, baked_tile_id)
    if current is None:
        raise UnknownBakedTile(f"version tile {baked_tile_id} stopped being stored")
    if not current.servable or current.container_sha256 != tile.container_sha256:
        raise BakedTileFaulted(
            f"version tile {baked_tile_id} stopped being servable while it was read"
        )
    return tile, data


def _read(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, baked_tile_id: uuid.UUID
) -> VersionBakedTile | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from world_version_baked_tile "
            "where workspace_id = %s and world_id = %s and baked_tile_id = %s",
            (workspace_id, world_id, baked_tile_id),
        ).fetchone()
    return None if row is None else _row(row)


def _servable(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, baked_tile_id: uuid.UUID
) -> VersionBakedTile:
    tile = _read(connection, workspace_id, world_id, baked_tile_id)
    if tile is None:
        raise UnknownBakedTile(f"no version tile {baked_tile_id} is stored for this world")
    if not tile.servable:
        raise BakedTileFaulted(
            f"version tile {baked_tile_id} baked twice into different containers and is not served"
        )
    return tile
