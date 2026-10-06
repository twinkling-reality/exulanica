"""A world generated from a recipe: made once, and read back through its receipt.

A person asks for a recipe (:mod:`exulanica.world.world_recipes`); the recipe's composer
(:mod:`exulanica.world.composers`) generates the world for a fresh identity, and
:func:`create_generated_authorities` registers it as a ``generated`` world and writes, in the
caller's transaction, the receipt (migration 0118), the structural snapshot that names it, the
default style, the authored version a saved entry opens, and one job per tile its baked tiles need
(``bake_generated_tile``, drained off the request by :mod:`exulanica.ingest.generated_tiles`).

**Reading a generated world** starts at its snapshot. The snapshot names its receipt by digest
(:func:`generation_receipt`), and the world's records are generated again from the receipt and
held to its output digest (:func:`town_records`): the records are never stored, so no copy of them
can drift from what the receipt says, and a world whose grammar or catalogs changed under it is
refused by name. :func:`town_records` is the one interface through which anything reads a
generated world's records, the society's ground and traffic alike; it keeps the few most recently
read worlds' records in memory, keyed by the receipt's digest, which is immutable.

**Its tiles** are found by the digest over each tile's bake inputs (:func:`generated_tiles`): a
tile is baked once, off the request, and a world whose tile is not yet baked says so rather than
drawing something else in its place.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.world.baked_tiles import current_bake
from exulanica.world.composers import (
    ComposedWorld,
    StatedExtent,
    composer_module,
    receipt_sha256,
)
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.models import StyleVersion
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.world_recipes import WorldRecipe, town_recipe, world_recipes
from exulanica.world.worlds import GENERATED, register_world

__all__ = [
    "BAKE_JOB_KIND",
    "GeneratedGround",
    "GeneratedRecords",
    "GeneratedTile",
    "compose_generated_world",
    "compose_specified_world",
    "create_generated_authorities",
    "generated_composer_keys",
    "generated_extent",
    "generated_ground",
    "generated_tiles",
    "generation_receipt",
    "states_records",
    "town_records",
    "unreadable_reason",
]

#: The job kind that bakes one tile of a generated world, off the request.
BAKE_JOB_KIND: Final = "bake_generated_tile"
#: How many generated worlds' records one process keeps in memory. Reading a world's records
#: generates them again (0.16 s for the small town on the development machine); the society's
#: host reads them on every edit and every authorization of a new input, so the worlds being
#: worked on are kept, and a world read again later is generated again.
_RECORDS_KEPT: Final = 4
#: The refusals a generated world's composer names first when its receipt no longer generates what
#: it recorded: the grammar or the catalogs changed under it, or the records came out otherwise.
#: Any other refusal to read a generated world is ``generated_world_unreadable``.
UNREADABLE_REASONS: Final = frozenset(
    {
        "generated_world_grammar_changed",
        "generated_world_catalogs_changed",
        "generated_world_output_changed",
    }
)


@dataclass(frozen=True, slots=True)
class GeneratedRecords:
    """A generated world's records, as its receipt generates them again."""

    world_id: str
    snapshot_id: uuid.UUID
    receipt_sha256: str
    receipt: Mapping[str, Any]
    records: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class GeneratedTile:
    """One tile of a generated world and where its bake stands."""

    tile_x: int
    tile_y: int
    #: The digest over the tile's bake inputs, the key its baked tile is stored under.
    tile_inputs_digest: str
    baked_tile_id: uuid.UUID | None
    #: ``baked`` when its current bake is stored and servable and its job is done, so both bakes
    #: agreed; ``baking`` until then, a first bake already stored included; ``failed`` when its
    #: current bake was found nondeterministic and is never served, or its job ended failed (the
    #: tessellator refused the tile, a publish was refused through every claim, or every claim was
    #: stranded).
    state: Literal["baked", "baking", "failed"]


_records_lock = threading.Lock()
_records_kept: OrderedDict[str, tuple[object, ...]] = OrderedDict()


def unreadable_reason(error: InvalidStructuralData) -> str:
    """The name a refusal to read a generated world carries: the composer's own when it names one of
    :data:`UNREADABLE_REASONS` first, else ``generated_world_unreadable``."""
    named = str(error).split(":", 1)[0].strip()
    return named if named in UNREADABLE_REASONS else "generated_world_unreadable"


def generated_composer_keys() -> frozenset[str]:
    """Every composer a recipe names: the composers whose snapshots are generated worlds."""
    return frozenset(recipe.composer_key for recipe in world_recipes())


def compose_generated_world(recipe: WorldRecipe, world_id: str) -> ComposedWorld:
    """The world a recipe makes for ``world_id``, before anything is written."""
    return composer_module(recipe.composer_key, recipe.composer_version).compose(recipe, world_id)


def compose_specified_world(
    preset: str, values: Mapping[str, object] | None, world_id: str
) -> ComposedWorld:
    """The world ``preset`` makes with ``values`` in place of its own for ``world_id``: its
    receipt, its structure and its records, generated and nothing written.

    What ``POST /worlds/generated`` makes before its transaction, through the same gate
    (:func:`~exulanica.world.world_recipes.town_recipe`), so a caller may show a world before a
    person asks for it. Refused as the gate and the composer refuse, by name.
    """
    return compose_generated_world(town_recipe(preset, values), world_id)


def create_generated_authorities(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    title: str,
    recipe: WorldRecipe,
    composed: ComposedWorld,
) -> tuple[uuid.UUID, StyleVersion, uuid.UUID]:
    """Register the world, then write its receipt, snapshot, style, version and bake jobs.

    All inside the caller's transaction. ``composed`` is what :func:`compose_generated_world`
    made for this world, generated before the transaction so no lock is held while it runs. The
    registration comes first because every world table names a registered world.
    """
    world_id = str(composed.receipt["world_id"])
    register_world(
        connection,
        workspace_id,
        world_id=world_id,
        kind=GENERATED,
        created_by=actor,
        reason=f"generated from world recipe {recipe.key}",
    )
    if receipt_sha256(composed.receipt) != composed.receipt_sha256:
        raise InvalidStructuralData("a generated world's receipt does not match its digest")
    connection.execute(
        "insert into world_generation_receipt "
        "(workspace_id,world_id,receipt_sha256,receipt,created_by) values (%s,%s,%s,%s,%s)",
        (workspace_id, world_id, composed.receipt_sha256, Jsonb(dict(composed.receipt)), actor),
    )
    structures = WorldStructureRepository(connection, workspace_id, world_id=world_id)
    preview = structures.preview(composed.candidate, proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=actor,
    )
    style = WorldStyleRepository(connection, workspace_id, world_id=world_id).current()
    version = WorldObjectRepository(connection, workspace_id, world_id=world_id).create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title=title,
        style_version_id=style.version_id,
        created_by=actor,
    )
    # A tile whose bake is already stored under the stage this installation runs, by the digest
    # over its inputs (the columns its key is derived from, migration 0144), is the same bytes this
    # world's tile would bake to: it queues no job, and the tile reads baked at once, as a world
    # with no job for a tile is read (generated_tiles). A bake of another stage is not read, so a
    # stage change rebakes. A tile stored with a fault the owner has not cleared still queues one,
    # whose job then fails as every bake of it does.
    composer = composed.receipt["composer"]
    inputs = {
        (int(tile_x), int(tile_y)): digest
        for (tile_x, tile_y), digest in composer_module(
            composer["key"], composer["version"]
        ).tile_inputs(composed.receipt)
    }
    for tile_x, tile_y in composed.receipt["tiles"]:
        stored = current_bake(connection, inputs[(int(tile_x), int(tile_y))])
        if stored is not None and stored.servable:
            continue
        connection.execute(
            "insert into job (workspace_id,kind,payload) values (%s,%s,%s)",
            (
                workspace_id,
                BAKE_JOB_KIND,
                Jsonb(
                    {
                        "world_id": world_id,
                        "snapshot_id": str(snapshot.snapshot_id),
                        "receipt_sha256": composed.receipt_sha256,
                        "tile": [tile_x, tile_y],
                    }
                ),
            ),
        )
    return snapshot.snapshot_id, style, version.version_id


def _snapshot(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> Mapping[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select composer_key,composer_version,topology,placement from "
            "world_structure_snapshot where workspace_id=%s and world_id=%s and snapshot_id=%s",
            (workspace_id, world_id, snapshot_id),
        ).fetchone()
    if row is None:
        raise UnknownWorldResource("no such structural snapshot")
    if row["composer_key"] not in generated_composer_keys():
        raise InvalidStructuralData(f"world {world_id!r} was not generated from a recipe")
    return row


def states_records(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> bool:
    """Whether a world's snapshot states records: whether a recipe's composer composed it, so its
    records are read through :func:`town_records`. A world of any other kind is composed from its
    person's objects and photographs, and states none."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select composer_key from world_structure_snapshot where workspace_id=%s and "
            "world_id=%s and snapshot_id=%s",
            (workspace_id, world_id, snapshot_id),
        ).fetchone()
    if row is None:
        raise UnknownWorldResource("no such structural snapshot")
    return str(row["composer_key"]) in generated_composer_keys()


def generation_receipt(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> tuple[str, Mapping[str, Any]]:
    """The receipt a generated world's snapshot names, with its digest, held to that digest."""
    snapshot = _snapshot(connection, workspace_id, world_id, snapshot_id)
    module = composer_module(snapshot["composer_key"], snapshot["composer_version"])
    digest = module.receipt_digest_of(snapshot["topology"])
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select receipt from world_generation_receipt where workspace_id=%s and world_id=%s "
            "and receipt_sha256=%s",
            (workspace_id, world_id, digest),
        ).fetchone()
    if row is None:
        raise InvalidStructuralData("a generated world's snapshot names a receipt it does not hold")
    if receipt_sha256(row["receipt"]) != digest:
        raise InvalidStructuralData("a generated world's receipt does not match its digest")
    return digest, MappingProxyType(dict(row["receipt"]))


def generated_extent(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> StatedExtent:
    """The region, extent and spawn a generated world's snapshot states."""
    snapshot = _snapshot(connection, workspace_id, world_id, snapshot_id)
    module = composer_module(snapshot["composer_key"], snapshot["composer_version"])
    stated: StatedExtent = module.stated_extent(snapshot["topology"], snapshot["placement"])
    return stated


def town_records(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> GeneratedRecords:
    """A generated world's records, generated again from the receipt its snapshot names.

    The one interface through which a generated world's records are read. The records are held
    to the receipt's output digest, and a world whose grammar or catalogs no longer generate it
    is refused by name (``InvalidStructuralData``).
    """
    digest, receipt = generation_receipt(connection, workspace_id, world_id, snapshot_id)
    with _records_lock:
        records = _records_kept.get(digest)
        if records is not None:
            _records_kept.move_to_end(digest)
    if records is None:
        composer = receipt["composer"]
        records = composer_module(composer["key"], composer["version"]).records(receipt)
        with _records_lock:
            _records_kept[digest] = records
            while len(_records_kept) > _RECORDS_KEPT:
                _records_kept.popitem(last=False)
    return GeneratedRecords(world_id, snapshot_id, digest, receipt, records)


def generated_tiles(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> tuple[GeneratedTile, ...]:
    """Every tile a generated world covers, with its baked tile where one is stored."""
    _, receipt = generation_receipt(connection, workspace_id, world_id, snapshot_id)
    composer = receipt["composer"]
    tiles = composer_module(composer["key"], composer["version"]).tile_inputs(receipt)
    found = []
    for (tile_x, tile_y), inputs in tiles:
        bake = current_bake(connection, inputs)
        with connection.cursor(row_factory=dict_row) as cursor:
            job = cursor.execute(
                "select state from job where workspace_id=%s and kind=%s "
                "and payload->>'world_id'=%s and payload->'tile'=%s "
                "order by created_at desc, job_id desc limit 1",
                (workspace_id, BAKE_JOB_KIND, world_id, Jsonb([tile_x, tile_y])),
            ).fetchone()
        ended = None if job is None else str(job["state"])
        state: Literal["baked", "baking", "failed"]
        if bake is not None and bake.cleared:
            # The owner's recorded decision to serve the stored first bake (migration 0144): the
            # job that failed on the fault no longer fails the world.
            state = "baked"
        elif (bake is not None and bake.state != "baked") or ended in ("failed", "cancelled"):
            state = "failed"
        elif bake is not None and ended in (None, "done"):
            # A world with no job for the tile (one restored without its queue) is drawn from its
            # stored bake; otherwise the job's end says both bakes agreed.
            state = "baked"
        else:
            state = "baking"
        found.append(
            GeneratedTile(
                tile_x=tile_x,
                tile_y=tile_y,
                tile_inputs_digest=inputs,
                baked_tile_id=None if bake is None or state == "baking" else bake.baked_tile_id,
                state=state,
            )
        )
    return tuple(found)


@dataclass(frozen=True, slots=True)
class GeneratedGround:
    """What a saved entry says to draw of a generated world: its recipe, its region, where a
    person arrives in the region's frame (east, height, south) and each tile with its bake."""

    recipe_key: str
    recipe_label: str
    region_id: str
    arrival_mm: tuple[int, int, int]
    #: The way a person arriving faces, as a plan vector in the region's frame: east, then south.
    arrival_facing_mm: tuple[int, int]
    tiles: tuple[GeneratedTile, ...]
    #: The specification schema the receipt names (``world-specification.v<N>``) and every
    #: adjustable value the world was made with, the preset's with the asker's in place, as the
    #: receipt records them. Both None for a world of a version 1 recipe, which named a whole
    #: specification file and recorded no values.
    specification: str | None = None
    values: Mapping[str, int | str] | None = None


def generated_ground(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> GeneratedGround:
    """The drawing a saved entry of a generated world declares."""
    _, receipt = generation_receipt(connection, workspace_id, world_id, snapshot_id)
    extent = generated_extent(connection, workspace_id, world_id, snapshot_id)
    recipe = receipt["recipe"]
    key = recipe["key"]
    label = next((preset.label for preset in world_recipes() if preset.key == key), key)
    values = recipe.get("values")
    return GeneratedGround(
        recipe_key=key,
        recipe_label=label,
        region_id=extent.region_id,
        arrival_mm=extent.arrival_mm,
        # The receipt's facing is a city frame vector (east, north); the region states south.
        arrival_facing_mm=(
            receipt["arrival"]["facing_mm"][0],
            -receipt["arrival"]["facing_mm"][1],
        ),
        tiles=generated_tiles(connection, workspace_id, world_id, snapshot_id),
        specification=None if values is None else recipe["specification"],
        values=None if values is None else MappingProxyType(dict(sorted(values.items()))),
    )
