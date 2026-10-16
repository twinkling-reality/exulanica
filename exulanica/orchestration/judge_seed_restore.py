"""Restoring a fresh stack to a judge seed, and returning a used stack to it.

:func:`restore_seed` and :func:`reset_to_seed` read an archive as
:mod:`exulanica.orchestration.judge_seed_archive` describes it, and both refuse a database that
holds any workspace but the seed's. A restore places the archive's objects in the stores and loads
its rows; a reset loads the rows again and writes no store. Each copies the row files in with the
schema's own triggers off for the load (:func:`_without_user_triggers`).
:mod:`exulanica.orchestration.judge_seed` writes the archive.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import grant_workspace_partition
from exulanica.orchestration.judge_seed_archive import (
    _CHUNK_BYTES,
    SeedManifest,
    SeedRefused,
    _blob_id,
    _registry_digest,
    _row_files,
    read_manifest,
    verify_restored,
    verify_seed,
)
from exulanica.store.base import ContentAddressedStore

#: Tables a reset may not empty, because migration 0013 put a BEFORE TRUNCATE guard on them.
#:
#: Nothing else in the schema guards TRUNCATE. The judge role holds no grant on either, and a
#: workspace that has deleted nothing carries no rows for them, so the ordinary case never
#: reaches this. A seed that DOES carry rows for them is refused rather than worked around.
_TRUNCATE_GUARDED: Final = ("purge_job", "tombstone")

#: The carried table a reset merges rather than truncates: its rows are global, each keyed by its
#: bake's inputs, so emptying it would empty tiles that belong to no workspace
#: (:func:`reset_to_seed`). Staged in :data:`_STAGED_BAKED_TILE` for the comparison.
_MERGED_TABLE: Final = "baked_tile"
#: The carried table a reset neither truncates nor loads: the installation's index of kept
#: generated pieces, which no deletion erases (contract: generated pieces). An export refuses a
#: workspace holding generated outputs, whose bytes a seed does not carry, so its file is empty.
_KEPT_TABLE: Final = "generated_piece"
_STAGED_BAKED_TILE: Final = "seed_baked_tile"


def _without_user_triggers(connection: psycopg.Connection, tables: Sequence[str]) -> Iterator[None]:
    """Turn the schema's own guards off for the duration of a bulk load, then back on.

    **This is the one place the restore steps around a rule the runtime obeys, so it is worth
    being exact about which rule and why.** The guards are written for INCREMENTAL writes and
    several of them are correct only in the presence of rows a bulk load has not reached yet.
    ``tg_tombstone_guard_assertion`` is the clearest case: it calls ``tombstone_blocks_scene``,
    which answers TRUE for a scene with no membership rows, so every assertion about a scene is
    refused until ``reconstruction_scene_member`` has loaded. Ordering cannot fix that in
    general, because ``assertion.subject_ref`` is a JSONB pointer with no foreign key for a
    topological sort to see.

    A second reason, and it would bite even if the ordering worked: a trigger that maintains a
    derived row would insert one the archive is also carrying, and the load would then collide
    with itself.

    **What stays on.** Foreign keys, which are deferred to COMMIT rather than disabled, so an
    archive that is internally inconsistent still fails. Row-level security, which is not a
    trigger: the workspace setting is set for the load, so PostgreSQL refuses a row belonging to
    another workspace even here. Check constraints, not-null, uniqueness.

    **What attests to the rows instead.** The manifest's per-file digests, verified before the
    load and counted after. These rows passed the guards when they were first written; this is a
    copy of that outcome, not a new set of writes claiming to be one.

    ``disable trigger user`` rather than ``session_replication_role``: the latter needs superuser
    and would switch off the foreign keys too.
    """
    for table in tables:
        connection.execute(
            sql.SQL("alter table {} disable trigger user").format(sql.Identifier(table))
        )
    try:
        yield
    finally:
        # The deferred foreign keys are checked HERE, before the guards come back, and the order
        # is forced rather than incidental: `alter table ... enable trigger` refuses a table with
        # pending trigger events, so re-enabling first fails with "cannot ALTER TABLE because it
        # has pending trigger events". Making the checks immediate runs them, which both empties
        # the queue and is the point at which an inconsistent archive fails.
        connection.execute("set constraints all immediate")
        for table in tables:
            connection.execute(
                sql.SQL("alter table {} enable trigger user").format(sql.Identifier(table))
            )


def _copy_in(
    connection: psycopg.Connection,
    archive: Path,
    manifest: SeedManifest,
    files: Sequence[tuple[str, str]],
) -> None:
    """Load each row file, naming the columns the manifest recorded.

    Named rather than positional, so an archive still loads into a schema a later migration has
    added a column to, and so a column order that changed is a refusal from PostgreSQL rather
    than a silent shift of every value one place to the left.
    """
    with contextlib.contextmanager(_without_user_triggers)(
        connection, [table for _, table in files]
    ):
        for name, table in files:
            columns = [str(value) for value in manifest.rows[name]["columns"]]
            _copy_file_in(connection, table, columns, archive / "rows" / name)


def _copy_file_in(
    connection: psycopg.Connection, table: str, columns: Sequence[str], path: Path
) -> None:
    """COPY one row file into ``table``, naming ``columns``."""
    statement = sql.SQL("copy {} ({}) from stdin").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    with connection.cursor().copy(statement) as copy, path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            copy.write(chunk)


def _load_rows(connection: psycopg.Connection, archive: Path, manifest: SeedManifest) -> None:
    """COPY every row file in, in one transaction, with the workspace guard satisfied.

    The workspace setting is set rather than bypassed. Every workspace-keyed table is under FORCE
    row-level security whose policy is ``workspace_id = current_workspace()``, and with no
    ``with check`` clause of its own that policy governs the INSERT too, so a COPY without this
    setting inserts nothing and reports no error. Setting it means the database refuses a row
    belonging to another workspace during the load, which is a second check on the export filter
    rather than a way around it.

    Foreign keys are deferred to the end of the transaction rather than disabled, so a cycle in
    the schema costs nothing and a genuinely inconsistent archive still fails at COMMIT.
    """
    with connection.transaction():
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, true)", (str(manifest.workspace_id),)
        )
        connection.execute("set constraints all deferred")
        _copy_in(connection, archive, manifest, _row_files(manifest))


def _load_blobs(
    directory: Path, store: ContentAddressedStore, recorded_objects: Mapping[str, Mapping[str, Any]]
) -> int:
    """Place the archive's objects under ``directory`` in the store, skipping any already there.

    Content addressed, so an object already at that key IS the object and putting it again would
    be work with no effect. Written through ``put_bytes``, which is what gives the file the
    store's layout and its 0444 mode; copying the archive's file into place directly would leave
    a writable object at a key that promises immutability. The blobs go to the blob store and the
    baked tiles' containers to the tile store, by the same path.
    """
    written = 0
    for key, recorded in sorted(recorded_objects.items()):
        blob_id = _blob_id(key)
        if store.exists(blob_id):
            continue
        payload = (directory / key).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != recorded["sha256"] or len(payload) != recorded["bytes"]:
            raise SeedRefused(
                f"the archive's {key} hashes to {digest} at {len(payload)} bytes; the manifest "
                f"says {recorded['sha256']} at {recorded['bytes']} bytes"
            )
        result = store.put_bytes(payload)
        if store.key_for(result.blob_id) != key:
            raise SeedRefused(f"the store placed {key} at {store.key_for(result.blob_id)} instead")
        written += 1
    return written


def _assert_only_this_workspace(
    connection: psycopg.Connection, workspace_id: uuid.UUID, consequence: str
) -> None:
    """Refuse a database holding any workspace other than the seed's.

    Both the restore and the reset need this and for related reasons. A reset TRUNCATES, which
    ignores the workspace policy and would empty a stranger's rows. A restore counts whole tables
    in :func:`verify_restored`, so a second workspace's rows would make every count disagree with
    the manifest and produce a confusing failure after a load that actually worked.

    A judge stack holds exactly one workspace. This is what makes that a checked property rather
    than an assumption written in a comment.
    """
    intruders = connection.execute(
        "select distinct workspace_id from capture where workspace_id <> %s",
        (str(workspace_id),),
    ).fetchall()
    if intruders:
        names = ", ".join(str(row["workspace_id"]) for row in intruders)
        raise SeedRefused(
            f"this database holds captures for {names} as well as the seed's {workspace_id}. "
            + consequence
        )


def _refuse_kept_rows(manifest: SeedManifest, files: list[tuple[str, str]]) -> None:
    """Refuse an archive whose manifest says it carries rows of :data:`_KEPT_TABLE`. An export
    refuses a workspace holding generated outputs, so its file is empty; one written while an export
    ran could travel, and neither a restore nor a reset loads the index of pieces whose bytes the
    seed does not carry."""
    kept = [name for name, table in files if table == _KEPT_TABLE]
    if any(int(manifest.rows[name]["rows"]) > 0 for name in kept):
        raise SeedRefused(
            f"the archive carries rows for {_KEPT_TABLE}, the installation's index of generated "
            "pieces, which a reset never empties and an export never fills"
        )


def restore_seed(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    archive: Path,
    tiles: ContentAddressedStore | None = None,
    verify: bool = True,
) -> SeedManifest:
    """Bring a freshly migrated, empty database and store to what ``archive`` holds.

    ``connection`` is administrative: the same principal that ran the migrations, because the
    load writes tables no runtime role may write and creates the workspace's embedding partition.
    ``tiles`` is the destination's tile store, required when the archive carries baked tiles.

    The order is not negotiable. The registry digest is compared BEFORE anything is written,
    because a mismatch means this archive's authored objects name bytes this schema resolves
    differently and there is nothing to gain from a half load. The partition is created before
    the rows, because ``embedding`` has nowhere to put a row without it. The baked tiles' bytes
    are placed before the rows, as the bake itself places them, so no ``baked_tile`` row ever
    names bytes the tile store does not hold. ``baked_tile`` is loaded before
    ``workspace_baked_tile``, whose foreign key names it, because the load order is topological.
    """
    manifest = verify_seed(archive) if verify else read_manifest(archive)
    _refuse_kept_rows(manifest, _row_files(manifest))
    if manifest.tiles and tiles is None:
        raise SeedRefused(
            f"the archive carries {len(manifest.tiles)} baked tile(s) and no tile store was "
            "given to place them in"
        )

    actual_registry = _registry_digest(connection)
    if actual_registry != manifest.registry_digest:
        raise SeedRefused(
            "the destination's migration-provided registries differ from the ones this archive "
            f"was exported against (destination {actual_registry}, archive "
            f"{manifest.registry_digest}). An authored object would resolve to different bytes."
        )

    occupied = connection.execute(
        "select count(*) as n from capture where workspace_id = %s", (str(manifest.workspace_id),)
    ).fetchone()
    if occupied is not None and int(occupied["n"]) > 0:
        raise SeedRefused(
            f"workspace {manifest.workspace_id} already holds captures in this database. Use "
            "reset_to_seed to return a used stack to the archive."
        )
    _assert_only_this_workspace(
        connection,
        manifest.workspace_id,
        "The landed row counts are compared against the manifest over whole tables, so a second "
        "workspace here would make every count disagree after a load that worked.",
    )

    provision_workspace(connection, manifest.workspace_id)
    grant_workspace_partition(connection, f"embedding_ws_{manifest.workspace_id.hex}")
    if tiles is not None:
        _load_blobs(archive / "tiles", tiles, manifest.tiles)
    _load_rows(connection, archive, manifest)
    _load_blobs(archive / "blobs", store, manifest.blobs)
    if verify:
        verify_restored(connection, store, manifest, tiles=tiles)
    return manifest


def reset_to_seed(
    connection: psycopg.Connection,
    *,
    archive: Path,
    tiles: ContentAddressedStore | None = None,
    verify: bool = True,
) -> SeedManifest:
    """Return a used stack to the archive's rows. The store is not touched.

    **The store is not touched, and that is a decision rather than an optimisation.** Keys are
    content addressed, and a reset that deleted them would be deleting the evidence every
    citation in the workspace resolves to. ``docs/demo-integrity.md`` section 2.2 said so before
    there was code to say it in. Neither store is written: ``tiles`` is only read, to refuse a
    reset whose baked tiles' bytes the tile store does not hold, before anything changes.

    **``baked_tile`` is merged, not truncated.** Its rows are global and each is keyed by its
    bake's inputs, so a row the stack already holds under an archived key is kept when it is
    identical to the archive's, an archived row the stack lacks is inserted, and a row that
    differs in any carried column, or claims the same bake of the same tile under another key,
    refuses the reset by name. Truncating it would empty tiles that belong to no workspace.

    **Truncates rather than deletes, because DELETE does not work here.** Thirty-eight tables in
    this schema carry an append-only or no-delete trigger, including every one a judge can write:
    ``world_alternate_version``, ``world_alternate_version_edit``, ``world_style_version`` and
    the audit tables. A reset built on DELETE would be refused by the triggers that make the
    history append-only, and a reset that disabled them would be disabling the property they
    exist to hold. TRUNCATE is not a DELETE and does not fire them.

    **TRUNCATE ignores row-level security, so it empties every workspace in this database.** That
    is correct for a judge stack, which holds exactly one, and it is checked rather than assumed.
    Never point this at a database holding more than the seed.
    """
    manifest = verify_seed(archive) if verify else read_manifest(archive)
    files = _row_files(manifest)

    _assert_only_this_workspace(
        connection,
        manifest.workspace_id,
        "A reset truncates, which ignores the workspace policy, so it is refused here rather "
        "than emptying somebody else's workspace.",
    )
    carried = [
        table
        for name, table in files
        if table in _TRUNCATE_GUARDED and int(manifest.rows[name]["rows"]) > 0
    ]
    if carried:
        raise SeedRefused(
            f"the archive carries rows for {', '.join(sorted(carried))}, which migration 0013 "
            "guards against TRUNCATE. A seed holding deletion state cannot be reset by this path."
        )
    _require_tile_bytes(tiles, manifest)

    _refuse_kept_rows(manifest, files)
    merged = [(name, table) for name, table in files if table == _MERGED_TABLE]
    keep = [
        (name, table)
        for name, table in files
        if table not in _TRUNCATE_GUARDED and table not in (_MERGED_TABLE, _KEPT_TABLE)
    ]
    with connection.transaction():
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, true)", (str(manifest.workspace_id),)
        )
        for name, _table in merged:
            _merge_baked_tiles(connection, archive, manifest, name)
        connection.execute(
            sql.SQL("truncate {} cascade").format(
                sql.SQL(", ").join(sql.Identifier(table) for _, table in keep)
            )
        )
        connection.execute("set constraints all deferred")
        _copy_in(connection, archive, manifest, keep)
    return manifest


def _require_tile_bytes(tiles: ContentAddressedStore | None, manifest: SeedManifest) -> None:
    """Refuse a reset whose baked tiles' bytes the tile store does not hold, reading nothing.

    A reset writes no store, so a tile row it inserts could only be served if the bytes are
    already there, as a restore of the same archive leaves them.
    """
    if not manifest.tiles:
        return
    if tiles is None:
        raise SeedRefused(
            f"the archive carries {len(manifest.tiles)} baked tile(s) and no tile store was "
            "given to check their bytes in"
        )
    missing = [
        key
        for key, recorded in sorted(manifest.tiles.items())
        if not tiles.exists(_blob_id(key)) or tiles.size(_blob_id(key)) != int(recorded["bytes"])
    ]
    if missing:
        raise SeedRefused(
            f"the tile store does not hold {len(missing)} of the archive's baked tiles, first "
            f"{missing[:5]}. A reset writes no store; restore the archive into a fresh stack."
        )


def _merge_baked_tiles(
    connection: psycopg.Connection, archive: Path, manifest: SeedManifest, name: str
) -> None:
    """Keep an identical ``baked_tile`` row, insert a missing one, refuse a different one by name.

    The archive's rows are staged in a temporary table and compared column by column over every
    column the archive carries, timestamps included, because ``baked_at`` is what decides which
    of one tile's bakes is current. A stack row claiming the same bake of the same tile under
    another key (migration 0077's uniqueness) counts as different. Inserted rows are copies of
    rows that passed the bake's guard when they were written, so the guard is off for the insert
    exactly as it is for a restore's COPY (:func:`_without_user_triggers`).
    """
    columns = [str(value) for value in manifest.rows[name]["columns"]]
    listed = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    connection.execute(
        sql.SQL("create temporary table {} (like baked_tile) on commit drop").format(
            sql.Identifier(_STAGED_BAKED_TILE)
        )
    )
    _copy_file_in(connection, _STAGED_BAKED_TILE, columns, archive / "rows" / name)

    differing = connection.execute(
        sql.SQL(
            "select distinct s.baked_tile_id from {staged} s join baked_tile b"
            "  on b.baked_tile_id = s.baked_tile_id"
            "  or (b.stage_version, b.stage_params_sha256, b.tile_inputs_digest)"
            "   = (s.stage_version, s.stage_params_sha256, s.tile_inputs_digest)"
            " where row({staged_columns}) is distinct from row({held_columns})"
            " order by s.baked_tile_id"
        ).format(
            staged=sql.Identifier(_STAGED_BAKED_TILE),
            staged_columns=sql.SQL(", ").join(sql.Identifier("s", column) for column in columns),
            held_columns=sql.SQL(", ").join(sql.Identifier("b", column) for column in columns),
        )
    ).fetchall()
    if differing:
        names = ", ".join(str(row["baked_tile_id"]) for row in differing)
        raise SeedRefused(
            f"this stack holds baked tile rows that differ from the archive's: {names}. A baked "
            "tile is what it was baked as, so the reset keeps neither and changes nothing."
        )
    with contextlib.contextmanager(_without_user_triggers)(connection, [_MERGED_TABLE]):
        connection.execute(
            sql.SQL(
                "insert into baked_tile ({listed}) select {listed} from {staged} s"
                " where not exists (select 1 from baked_tile b"
                "  where b.baked_tile_id = s.baked_tile_id)"
            ).format(listed=listed, staged=sql.Identifier(_STAGED_BAKED_TILE))
        )
    # Dropped here as well as on commit: inside a caller's longer transaction the reset's own is a
    # savepoint, and a second reset before that caller commits would find the table still there.
    connection.execute(sql.SQL("drop table {}").format(sql.Identifier(_STAGED_BAKED_TILE)))
