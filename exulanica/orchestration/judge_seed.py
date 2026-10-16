"""One workspace, sealed into an archive a fresh stack can be brought up from, and verified.

**What this is for.** A judge, a reviewer, or anybody else who has to see the product working is
given a deployment that starts from a known state, can be walked, asked and edited, and can be
returned to that state in seconds. This module produces the artifact that state comes from, puts
it back, and provisions the one database role that makes "and nothing else" true.

**Why it lives in :mod:`exulanica.orchestration`.** The import contract in ``pyproject.toml`` is
exhaustive and layered. A seed has to reach ``exulanica.db`` and ``exulanica.store``, which are
siblings and cannot reach each other, and it has to reach ``exulanica.world`` to compose the
structural snapshot a sandbox version branches from. ``orchestration`` is the only layer above
all three, and its stated role already fits: "an executable acceptance path rather than reusable
domain logic", imported by nothing. A module under ``exulanica.deletion`` would sit low enough
for the first two and could not reach the third.

**The four operations, and the one property each has to have.**

*   :func:`export_seed` writes an archive. Its property is that it is COMPLETE and NARROW at once:
    every row and every byte the named workspace needs, and no row belonging to another
    workspace. Neither half is legible by reading the code, so both are enforced by it: the
    classification is exhaustive over the live schema and a table nobody classified fails the
    export rather than being silently dropped from every seed thereafter.
*   :func:`restore_seed` brings a freshly migrated, empty database and store to what the archive
    holds. Its property is that it is BYTE VERIFIED: every row file, every blob and every baked
    tile's bytes are re-hashed against the manifest before they are loaded and the landed state
    is counted after, and a mismatch raises rather than warns.
*   :func:`reset_to_seed` returns a used stack to the archive. Its property is that it NEVER
    TOUCHES THE STORE. Keys are content addressed, a reset that deleted them would be deleting
    the evidence every citation resolves to, and ``docs/demo-integrity.md`` section 2.2 decided
    that before there was code to decide it in.
*   :func:`provision_judge_role` creates the role the judge deployment's API connects as. Its
    property is that writability is an ALLOWLIST, so a table a later migration adds arrives
    readable and not writable without anybody remembering to come back here.

**What the archive is not.** It is not a backup, it is not a World Memory Package, and it
substitutes for neither. It carries no signature, so it proves integrity against its own manifest
and nothing else: whoever can rewrite the archive can rewrite the manifest with it. It is an
operational convenience for a workspace whose content is already published, and the moment it
carries one that is not, it needs the package path instead.

**Where the parts live.** This module classifies the schema, writes the archive and opens the
sandbox a judge edits. The archive's manifest and its checks are
:mod:`exulanica.orchestration.judge_seed_archive`'s, the restore and the reset
:mod:`exulanica.orchestration.judge_seed_restore`'s, and the judge role and its token
:mod:`exulanica.orchestration.judge_seed_role`'s. Every name in ``__all__`` is importable from
here.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.db.registries import REGISTRY_TABLES
from exulanica.orchestration.judge_seed_archive import SEED_FORMAT_VERSION as SEED_FORMAT_VERSION
from exulanica.orchestration.judge_seed_archive import SeedManifest as SeedManifest
from exulanica.orchestration.judge_seed_archive import SeedRefused as SeedRefused
from exulanica.orchestration.judge_seed_archive import (
    _blob_id,
    _digest_file,
    _key_for,
    _read_key,
    _registry_digest,
    _write_manifest,
)
from exulanica.orchestration.judge_seed_archive import iter_row_tables as iter_row_tables
from exulanica.orchestration.judge_seed_archive import read_manifest as read_manifest
from exulanica.orchestration.judge_seed_archive import verify_restored as verify_restored
from exulanica.orchestration.judge_seed_archive import verify_seed as verify_seed
from exulanica.orchestration.judge_seed_restore import reset_to_seed as reset_to_seed
from exulanica.orchestration.judge_seed_restore import restore_seed as restore_seed
from exulanica.orchestration.judge_seed_role import (
    JUDGE_INSERT_ONLY_TABLES as JUDGE_INSERT_ONLY_TABLES,
)
from exulanica.orchestration.judge_seed_role import JUDGE_PERMISSIONS as JUDGE_PERMISSIONS
from exulanica.orchestration.judge_seed_role import JUDGE_ROLE as JUDGE_ROLE
from exulanica.orchestration.judge_seed_role import JUDGE_WRITE_TABLES as JUDGE_WRITE_TABLES
from exulanica.orchestration.judge_seed_role import (
    judge_grant_mismatches as judge_grant_mismatches,
)
from exulanica.orchestration.judge_seed_role import judge_grants as judge_grants
from exulanica.orchestration.judge_seed_role import mint_judge_token as mint_judge_token
from exulanica.orchestration.judge_seed_role import provision_judge_role as provision_judge_role
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "GLOBAL_TABLES",
    "INSTANCE_TABLES",
    "JUDGE_INSERT_ONLY_TABLES",
    "JUDGE_PERMISSIONS",
    "JUDGE_ROLE",
    "JUDGE_WRITE_TABLES",
    "REACHED_TABLES",
    "SEED_FORMAT_VERSION",
    "WORKSPACE_ROW_PREDICATES",
    "SeedManifest",
    "SeedRefused",
    "classify_tables",
    "export_seed",
    "iter_row_tables",
    "judge_grant_mismatches",
    "judge_grants",
    "mint_judge_token",
    "prepare_sandbox_world",
    "provision_judge_role",
    "read_manifest",
    "reset_to_seed",
    "restore_seed",
    "verify_restored",
    "verify_seed",
]


# ---------------------------------------------------------------------------------------------
# What the archive carries, and what it deliberately does not
# ---------------------------------------------------------------------------------------------

#: Tables with no ``workspace_id`` that migrations fill, and that this archive therefore omits.
#:
#: Every registry is one: reviewed art profiles, capability vocabularies, the predicate list, the
#: reviewed object assets and texture pins, all named once in
#: :data:`exulanica.db.registries.REGISTRY_TABLES`. ``exulanica-db`` recreates them from the
#: migration that inserted them, so carrying them would let a restore install a vocabulary that
#: disagrees with the schema it is installing into. The manifest records a digest over their
#: contents instead, and :func:`restore_seed` compares it before writing anything, which turns a
#: disagreement into a refusal rather than into an object that resolves to different bytes.
#:
#: ``tests/conftest.py`` preserves the same registries across its per-test truncation, for the
#: same reason: emptying them empties the vocabulary and every later insert is then refused by a
#: guard doing its job. The harness also keeps ``schema_migrations`` and ``stage_registry``.
#:
#: ``baked_tile`` has no ``workspace_id`` either and is not one of these: a bake writes it, never a
#: migration, so a fresh stack holds none of its rows. It is carried, narrowed to the tiles this
#: workspace reaches, in :data:`REACHED_TABLES`.
GLOBAL_TABLES: Final[Mapping[str, str]] = {
    **REGISTRY_TABLES,
}

#: Tables that belong to a deployment rather than to a workspace, and must not cross.
#:
#: ``schema_migrations`` is the destination's own record of what it applied; carrying the
#: source's would make a restored database claim a history it never ran.
#:
#: ``restore_control`` and ``restore_replay_receipt`` are the deletion-checkpoint machinery in
#: :mod:`exulanica.deletion.restore`. ``verify_restore`` refuses traffic while ``restore_control``
#: is not complete, so an archive carrying a sealed row from the machine it was exported on would
#: produce a judge stack that starts, passes its health check, and refuses every request.
INSTANCE_TABLES: Final[Mapping[str, str]] = {
    # Account identity, login and browser-session state belong to the deployment's authentication
    # boundary. A workspace seed must not carry credentials, identities or account relationships,
    # even for rows that also name the exported workspace.
    "account_browser_session": "per-deployment browser authentication state",
    "account_identity": "per-deployment external identity binding",
    "account_login_attempt": "per-deployment OIDC login state",
    "account_membership": "per-deployment account authorization relationship",
    "account_user": "per-deployment account identity",
    "account_workspace": "per-deployment account-owned workspace registry",
    "account_guest_entry": "per-deployment guest entry that made a guest's account",
    "account_guest_day": "per-deployment count of a day's guest entries",
    "account_creator_grant_event": "per-deployment operator's grants of who may upload",
    # Cross-workspace match calibration, keyed on `predicate_id` and accumulated by whichever
    # deployment ran the matcher. Carrying one deployment's empirical bins into another would be
    # importing a confidence curve measured on a corpus the destination does not hold.
    "calibration": "cross-workspace matcher calibration, accumulated per deployment",
    "restore_control": "per-deployment deletion checkpoint state, not workspace content",
    "restore_replay_receipt": "per-deployment deletion checkpoint state, not workspace content",
    "schema_migrations": "the destination records what it applied, not what the source did",
    "world_reviewed_asset_import": "host-admin reviewed import provenance, not workspace content",
    # Money is the deployment's own decision. A seed that carried a grant would grant money on
    # import, and one that carried a ledger would hand the destination another installation's
    # spending, so no spending row travels in a seed, even one that names the workspace.
    "spending_authority": "per-deployment spending authority an operator issued",
    "spending_authority_term": "per-deployment spending authority terms",
    "spending_authority_state": "per-deployment spending ledger state",
    "spending_authority_revocation": "per-deployment spending authority revocation",
    "spending_grant": "per-deployment spending grant, never granted by an import",
    "spending_grant_state": "per-deployment spending committed by a grant",
    "spending_grant_revocation": "per-deployment spending grant revocation",
    "spending_reservation": "per-deployment spending reservation and settlement",
    "spending_event": "per-deployment spending ledger",
    "spending_guest_policy": "per-deployment figures a guest workspace is granted",
    "spending_guest_policy_day": "per-deployment count of a guest policy's grants in a day",
    # Migration 0173: the installation's style pack upload attempts in a day and its retained style
    # pack bytes, each a count of this deployment's own and nothing of a workspace's content.
    "installation_style_pack_day": "per-deployment count of a day's style pack upload attempts",
    "installation_style_pack_total": "per-deployment total of retained style pack bytes",
    # The host publishes its character catalogs; a destination publishes its own, and a saved look
    # it cannot resolve there reads as unavailable rather than borrowing the source's catalog.
    "character_catalog_publication": "host-admin character catalog publication, per deployment",
    "character_catalog_withdrawal": "host-admin character catalog withdrawal, per deployment",
    "generation_session": "the operator's register of GPU sessions, per deployment",
    # A piece request's settlement of its spending reservation: money, which no seed carries.
    "piece_settlement": "per-deployment settlement of a piece request's spending reservation",
    # The bake stage a deployment runs is stated by its own migrations, as its schema is; an
    # owner's decision to serve a faulted tile is about that deployment's bakes (migration 0144).
    "baked_tile_stage": "the bake stage the destination's own migrations state",
    "baked_tile_fault_clearance": "host-owner decision on this deployment's faulted bakes",
    # The door's secrets open a deployment's grants to the bridges it admits; a seed never carries
    # a credential, even a digest of one. A destination issues its own.
    "door_secret": "per-deployment door credentials, never carried by an import",
    "door_redemption_refusal": "per-deployment record of a bridge's refused invite redemptions",
}

#: Workspace tables carried narrower than the whole workspace, with the exact predicate.
#:
#: ``piece_request``: only ended requests. The export refuses a workspace holding an open request
#: before it copies anything, but it copies on a connection that sees each statement's own
#: snapshot, so a request asked between that refusal and the copy would otherwise be carried
#: open, and a destination's generation worker would make pieces nobody asked it for.
#: ``piece_batch``: only ended batches, for the same reason: a batch queued in that window would
#: travel queued without its requests, and a destination worker would never end it.
WORKSPACE_ROW_PREDICATES: Final[Mapping[str, str]] = {
    "piece_request": (
        "t.workspace_id = %(workspace_id)s and t.state not in ('requested', 'queued')"
    ),
    "piece_batch": "t.workspace_id = %(workspace_id)s and t.state <> 'queued'",
}

#: Tables with no ``workspace_id`` that nevertheless hold this workspace's rows, with the exact
#: predicate that selects them.
#:
#: **This is the half of the export filter a naive implementation gets wrong, in both
#: directions.** Filtering on ``workspace_id`` alone silently DROPS ``media_track``,
#: ``clock_anchor`` and ``pipeline_event``, and silently CARRIES every other workspace's ``blob``
#: rows. The first failure is quiet, because the restored stack works until something asks for a
#: track. The second is not quiet at all: it is another workspace's content inside an archive
#: that says it holds one.
#:
#: ``%(workspace_id)s`` is a bound parameter. None of this is ever formatted into SQL as text.
#: ``%(baked_tile_ids)s`` is bound too: the baked tiles :func:`_reached_baked_tiles` finds in
#: Python, because a generated world names its tiles through its receipt rather than in a column.
REACHED_TABLES: Final[Mapping[str, str]] = {
    "blob": (
        "t.blob_sha256 in ("
        "  select c.blob_sha256 from capture c where c.workspace_id = %(workspace_id)s)"
    ),
    "baked_tile": "t.baked_tile_id = any(%(baked_tile_ids)s::uuid[])",
    # The installation's index of kept generated pieces: catalog content with no workspace_id,
    # written by the generation worker, never by a migration, so a fresh stack holds none. Carried
    # narrowed to the pieces this workspace's outputs name, which each output's foreign key needs.
    "generated_piece": (
        "(t.cache_key, t.variant) in ("
        "  select o.cache_key, o.variant from piece_output o"
        "   where o.workspace_id = %(workspace_id)s)"
    ),
    "media_track": (
        "t.blob_sha256 in ("
        "  select c.blob_sha256 from capture c where c.workspace_id = %(workspace_id)s)"
    ),
    "clock_anchor": (
        "t.track_id in (select m.track_id from media_track m where m.blob_sha256 in ("
        "  select c.blob_sha256 from capture c where c.workspace_id = %(workspace_id)s))"
    ),
    "anchor_resolution": (
        "t.span_id in ("
        "  select s.span_id from evidence_span s where s.workspace_id = %(workspace_id)s)"
    ),
    "pipeline_event": (
        "t.run_id in ("
        "  select p.run_id from pipeline_run p where p.workspace_id = %(workspace_id)s)"
    ),
    # The pipeline stage catalogue. NOT migration-provided, although it looks like the other
    # registries: the ingest pipeline registers a stage the first time it runs one, so a freshly
    # migrated database holds none and the source holds one row per stage its runs touched.
    # `artifact.stage_key` and `pipeline_event.stage_key` name these by value rather than by
    # foreign key, so omitting them loses no row to a constraint and instead produces a restored
    # stack whose artifacts cite stages nothing can describe. Carried, and narrowed to the stages
    # this workspace's own rows name.
    #
    # Found by the registry digest refusing a restore, which is what that check is for.
    "stage_definition": (
        "(t.stage_key, t.stage_version) in ("
        "  select a.stage_key, a.stage_version from artifact a"
        "   where a.workspace_id = %(workspace_id)s and a.stage_key is not null"
        "  union"
        "  select e.stage_key, e.stage_version from pipeline_event e"
        "   join pipeline_run p on p.run_id = e.run_id"
        "   where p.workspace_id = %(workspace_id)s and e.stage_key is not null)"
    ),
    "stage_registry": (
        "t.stage_key in ("
        "  select a.stage_key from artifact a"
        "   where a.workspace_id = %(workspace_id)s and a.stage_key is not null"
        "  union"
        "  select e.stage_key from pipeline_event e"
        "   join pipeline_run p on p.run_id = e.run_id"
        "   where p.workspace_id = %(workspace_id)s and e.stage_key is not null)"
    ),
    "consent_record": (
        # `tenant_id` is the workspace under migration 0001's original column name. Isolation
        # compares that column to current_workspace() (`exulanica.workspace_id`). The seed still
        # filters on the column so a copy cannot pull another workspace's consent rows even if
        # a later policy rewrite is incomplete. The historical `orimera.tenant_id` setting is
        # not the session identity.
        "t.tenant_id = %(workspace_id)s"
    ),
}


# ---------------------------------------------------------------------------------------------
# Classification, exhaustive over the live schema
# ---------------------------------------------------------------------------------------------


def classify_tables(connection: psycopg.Connection) -> dict[str, tuple[str, ...]]:
    """Put every base table in the current schema into exactly one bucket, or refuse.

    Buckets are ``workspace`` (filtered on ``workspace_id``), ``reached`` (filtered by an explicit
    predicate in :data:`REACHED_TABLES`), ``global`` (migration-provided, not carried),
    ``instance`` (per-deployment, not carried) and ``partition`` (per-workspace embedding
    partitions, created by :func:`provision_workspace` rather than loaded).

    **Exhaustive on purpose, and this is the whole safety argument for the export.** A migration
    that adds a table nobody thought about here does not quietly fall out of every seed from then
    on. It fails the next export, and the failure names the table.
    """
    rows = connection.execute(
        "select c.relname as name, c.relispartition as is_partition,"
        "       exists ("
        "         select 1 from pg_attribute a"
        "          where a.attrelid = c.oid and a.attname = 'workspace_id' and a.attnum > 0"
        "            and not a.attisdropped"
        "       ) as has_workspace"
        "  from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = current_schema() and c.relkind in ('r', 'p')"
        " order by c.relname"
    ).fetchall()

    buckets: dict[str, list[str]] = {
        "workspace": [],
        "reached": [],
        "global": [],
        "instance": [],
        "partition": [],
    }
    unclassified: list[str] = []
    for row in rows:
        name = row["name"]
        if row["is_partition"]:
            buckets["partition"].append(name)
        elif name in INSTANCE_TABLES:
            buckets["instance"].append(name)
        elif name in GLOBAL_TABLES:
            buckets["global"].append(name)
        elif name in REACHED_TABLES:
            buckets["reached"].append(name)
        elif row["has_workspace"]:
            buckets["workspace"].append(name)
        else:
            unclassified.append(name)

    if unclassified:
        raise SeedRefused(
            "these tables carry no workspace_id and are in no bucket, so a seed cannot say "
            "whether they hold this workspace's content or the deployment's: "
            f"{', '.join(sorted(unclassified))}. Add each to GLOBAL_TABLES, INSTANCE_TABLES or "
            "REACHED_TABLES in exulanica/orchestration/judge_seed.py, with the reason."
        )
    named = set(GLOBAL_TABLES) | set(INSTANCE_TABLES) | set(REACHED_TABLES)
    missing = named - {name for values in buckets.values() for name in values}
    if missing:
        raise SeedRefused(
            "these tables are classified in exulanica/orchestration/judge_seed.py but are absent "
            f"from the schema, so the classification is stale: {', '.join(sorted(missing))}"
        )
    return {key: tuple(value) for key, value in buckets.items()}


def _load_order(connection: psycopg.Connection, tables: Sequence[str]) -> list[str]:
    """Sort ``tables`` so a referenced row is written before the row referencing it.

    Cycles are neither an error nor resolved here. Foreign keys are deferred to the end of the
    load transaction, so an order that is right except inside a cycle is right enough; the sort
    exists to make a partial failure legible, not to make the load possible.
    """
    wanted = set(tables)
    edges = connection.execute(
        "select con.conrelid::regclass::text as child,"
        "       con.confrelid::regclass::text as parent"
        "  from pg_constraint con"
        "  join pg_class c on c.oid = con.conrelid"
        "  join pg_namespace n on n.oid = c.relnamespace"
        " where con.contype = 'f' and n.nspname = current_schema()"
    ).fetchall()

    def bare(value: str) -> str:
        return value.split(".")[-1].strip('"')

    parents: dict[str, set[str]] = {name: set() for name in wanted}
    for row in edges:
        child, parent = bare(row["child"]), bare(row["parent"])
        if child in wanted and parent in wanted and child != parent:
            parents[child].add(parent)

    ordered: list[str] = []
    placed: set[str] = set()
    remaining = sorted(wanted)
    while remaining:
        ready = [name for name in remaining if parents[name] <= placed]
        if not ready:
            ordered.extend(remaining)
            break
        ordered.extend(ready)
        placed.update(ready)
        remaining = [name for name in remaining if name not in placed]
    return ordered


def _loadable_columns(connection: psycopg.Connection, table: str) -> list[str]:
    """The columns a COPY can both write and read back, in attribute order.

    Generated columns are excluded, and that is not a refinement. ``blob.ni_uri`` is
    ``generated always as ... stored``: ``select *`` emits it and ``copy ... from stdin`` refuses
    it, so an archive built from ``*`` exports a column the restore cannot accept and fails on
    the first table. Recording the list in the manifest also means a later migration adding a
    column does not invalidate an archive written before it.
    """
    rows = connection.execute(
        "select a.attname as name from pg_attribute a"
        "  join pg_class c on c.oid = a.attrelid"
        "  join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = current_schema() and c.relname = %s"
        "   and a.attnum > 0 and not a.attisdropped and a.attgenerated = ''"
        " order by a.attnum",
        (table,),
    ).fetchall()
    return [row["name"] for row in rows]


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def _reviewed_asset_keys(connection: psycopg.Connection) -> set[str]:
    """The reviewed object assets, which the API also writes into the store at startup.

    ``exulanica.api.app`` calls ``seed_reviewed_assets(services.store)`` in its lifespan, so a
    restored stack fills these itself and an archive missing them still works. They are carried
    anyway, because they total about two kilobytes and an archive that holds everything the
    workspace resolves is easier to reason about than one with a footnote. The only consequence
    of their being optional is that a source store lacking them does not fail the export.
    """
    keys: set[str] = set()
    for row in connection.execute(
        "select content_sha256, licence_sha256 from world_reviewed_asset"
    ).fetchall():
        for digest in (row["content_sha256"], row["licence_sha256"]):
            keys.add(_key_for(str(digest)))
    return keys


def _referenced_keys(connection: psycopg.Connection, workspace_id: uuid.UUID) -> dict[str, str]:
    """Every store key a restored stack for this workspace will ask for.

    Three sources, and the third is the one that is easy to miss. Originals arrive through
    ``blob``, derivatives through ``artifact``, and the reviewed object assets a judge can place
    arrive through ``world_reviewed_asset``, which is a GLOBAL registry with no ``workspace_id``
    at all. A key set built from workspace rows alone restores a stack whose object catalogue
    lists three objects and where placing any of them fails on missing bytes.
    """
    keys: dict[str, str] = {}
    parameters = {"workspace_id": str(workspace_id)}

    for row in connection.execute(
        "select distinct b.storage_key from blob b"
        " where b.storage_key is not null and b.purged_at is null"
        "   and b.blob_sha256 in ("
        "     select c.blob_sha256 from capture c where c.workspace_id = %(workspace_id)s)",
        parameters,
    ).fetchall():
        keys[row["storage_key"]] = "blob"

    for row in connection.execute(
        "select distinct a.storage_key from artifact a"
        " where a.workspace_id = %(workspace_id)s and a.storage_key is not null"
        "   and a.purged_at is null",
        parameters,
    ).fetchall():
        keys.setdefault(row["storage_key"], "artifact")

    for key in _reviewed_asset_keys(connection):
        keys.setdefault(key, "world_reviewed_asset")
    return keys


def _reached_baked_tiles(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> list[uuid.UUID]:
    """The baked tiles this workspace reaches, which are the ``baked_tile`` rows a seed carries.

    Two sources. The delivery ledger names every tile the workspace was served. A generated world
    names its tiles through its receipt, by the digest over each tile's bake inputs, and no column
    holds that link, so it is read the way the product reads it:
    :func:`~exulanica.world.generated_worlds.generated_tiles` for each of the world's
    recipe-composed snapshots, and :func:`~exulanica.world.baked_tiles.current_bake` for each
    tile, whatever its job's state, so a bake stored before its job ended travels too. Only the
    current bake of a generated tile is carried; it stays current in the destination, because it
    is the most recently published of the rows the archive holds for that tile.

    A generated world whose receipt no longer reads is refused by name rather than skipped: the
    seed could not say which tiles it reaches.
    """
    from exulanica.world.baked_tiles import current_bake
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.generated_worlds import generated_tiles, states_records
    from exulanica.world.worlds import GENERATED, workspace_worlds

    reached = {
        row["baked_tile_id"]
        for row in connection.execute(
            "select baked_tile_id from workspace_baked_tile where workspace_id = %s",
            (workspace_id,),
        ).fetchall()
    }
    for world in workspace_worlds(connection, workspace_id):
        if world.kind != GENERATED:
            continue
        snapshots = connection.execute(
            "select snapshot_id from world_structure_snapshot"
            " where workspace_id = %s and world_id = %s order by snapshot_id",
            (workspace_id, world.world_id),
        ).fetchall()
        for snapshot in snapshots:
            snapshot_id = snapshot["snapshot_id"]
            if not states_records(connection, workspace_id, world.world_id, snapshot_id):
                continue
            try:
                tiles = generated_tiles(connection, workspace_id, world.world_id, snapshot_id)
            except InvalidStructuralData as exc:
                raise SeedRefused(
                    f"generated world {world.world_id} cannot be read ({exc}), so a seed cannot "
                    "say which baked tiles it reaches"
                ) from exc
            for tile in tiles:
                bake = current_bake(connection, tile.tile_inputs_digest)
                if bake is not None:
                    reached.add(bake.baked_tile_id)
    return sorted(reached)


def _export_tiles(
    connection: psycopg.Connection,
    tiles: ContentAddressedStore,
    reached: Sequence[uuid.UUID],
    directory: Path,
) -> dict[str, dict[str, Any]]:
    """Copy each reached tile's container from the tile store into ``directory``, re-hashed.

    Keyed by the row's ``container_sha256``, which is how the tile store names the bytes. A row
    whose bytes the source store does not hold is refused whatever ``allow_absent`` says: a judge
    stack runs no bake worker, so a tile carried without its bytes is one it can never serve.
    """
    carried: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        "select baked_tile_id, container_sha256, container_bytes from baked_tile"
        " where baked_tile_id = any(%s::uuid[]) order by baked_tile_id",
        (list(reached),),
    ).fetchall():
        digest = bytes(row["container_sha256"]).hex()
        key = _key_for(digest)
        if key in carried:
            continue
        if not tiles.exists(_blob_id(key)):
            raise SeedRefused(
                f"baked tile {row['baked_tile_id']} names {key} and the source tile store does "
                "not hold it. A judge stack runs no bake worker, so the seed cannot carry the "
                "tile without its bytes."
            )
        payload = _read_key(tiles, key)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != digest or len(payload) != int(row["container_bytes"]):
            raise SeedRefused(
                f"the tile store's bytes for {key} hash to {actual} at {len(payload)} bytes; "
                f"baked tile {row['baked_tile_id']} records {digest} at "
                f"{row['container_bytes']} bytes"
            )
        target = directory / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        carried[key] = {"sha256": actual, "bytes": len(payload)}
    return carried


def _refuse_private_bakes(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """A workspace holding its own material bakes cannot be seeded.

    Those bytes are under ``LicenseRef-Exulanica-Workspace-Private`` (migration 0066): they stay
    in the workspace they were baked for, and a seed is a copy made to be handed to somebody else.
    Their rows alone would restore as bakes whose bytes are missing, so the export refuses rather
    than carrying half of them.
    """
    present = connection.execute("select to_regclass('material_bake') is not null as present")
    if not present.fetchone()["present"]:
        return
    held = connection.execute(
        "select count(*) as n from material_bake "
        "where workspace_id = %s and content_sha256 is not null and purged_at is null",
        (workspace_id,),
    ).fetchone()
    if held["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['n']} material bake(s) under "
            "LicenseRef-Exulanica-Workspace-Private, which never leave their workspace; a seed "
            "cannot carry them"
        )


def _refuse_private_workspace_assets(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> None:
    """A workspace holding its own admitted assets cannot be seeded.

    An admission is used in its own workspace's worlds and nowhere else (migration 0126), and its
    bytes live in that workspace's own namespace, outside the content store a seed copies from.
    Their rows alone would restore as assets whose bytes are missing, so the export refuses, as it
    does for a private material bake.
    """
    present = connection.execute(
        "select to_regclass('workspace_asset_blob') is not null as present"
    )
    if not present.fetchone()["present"]:
        return
    held = connection.execute(
        "select count(*) as n from workspace_asset_blob "
        "where workspace_id = %s and purged_at is null",
        (workspace_id,),
    ).fetchone()
    if held["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['n']} workspace asset object(s), which are "
            "used only in that workspace's worlds and never leave it; a seed cannot carry them"
        )


def _refuse_held_things(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """A workspace holding its own looks, thing kinds, kept web pictures or a changed town's
    tiles cannot be seeded.

    A look's container lives in its workspace's own ``looks`` namespace
    (:mod:`exulanica.world.thing_store`), outside the content store a seed copies from, and a look
    may be private, restricted or share-alike, which a seed handed to somebody else would carry
    with no rights check; a drafted kind holds words drafted from a person's. Their rows alone
    would restore as looks whose bytes are missing, so the export refuses, as it does for a
    workspace's own admitted assets; and so it does while the looks namespace still holds a
    container the purge has not destroyed (migration 0172's inventory, ``look_object``). A kept web
    picture (migration 0215) is a stranger's photograph kept for one person's private world, so a
    workspace that keeps one, or whose web pictures namespace still holds bytes, is refused too, as
    is one whose version tiles namespace holds a changed town's tiles (migration 0219), which live
    outside the content store a seed copies from.
    """
    present = connection.execute(
        "select to_regclass('look_version') is not null as looks, "
        "to_regclass('look_object') is not null as objects, "
        "to_regclass('web_picture_object') is not null as pictures, "
        "to_regclass('world_version_tile_object') is not null as tiles"
    ).fetchone()
    for held, table, words in (
        (
            "pictures",
            "web_picture_object",
            "keeps pictures from the web for its own private worlds",
        ),
        ("tiles", "world_version_tile_object", "holds tiles of towns its people changed"),
    ):
        if (
            present[held]
            and connection.execute(
                f"select exists (select 1 from {table} where workspace_id = %(w)s "
                "and purged_at is null) as held",
                {"w": workspace_id},
            ).fetchone()["held"]
        ):
            raise SeedRefused(f"workspace {workspace_id} {words}; a seed cannot carry them")
    if not present["looks"]:
        return
    # A schema between the store and its inventory holds looks and no inventory to count.
    objects = (
        "(select count(*) from look_object where workspace_id = %(w)s and purged_at is null)"
        if present["objects"]
        else "0"
    )
    held = connection.execute(
        "select (select count(*) from look_version where workspace_id = %(w)s) as looks, "
        "(select count(*) from thing_kind_version where workspace_id = %(w)s) as kinds, "
        f"{objects} as objects",
        {"w": workspace_id},
    ).fetchone()
    if held["looks"] or held["kinds"] or held["objects"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['looks']} look(s), {held['kinds']} thing "
            f"kind(s) and {held['objects']} looks container(s) of its own, kept only in that "
            "workspace with the containers its own looks namespace holds; a seed cannot carry them"
        )


def _refuse_private_workspace_style_packs(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> None:
    """A workspace holding any style pack version of its own cannot be seeded, files or none.

    A workspace's style pack is worn in its own worlds and nowhere else (migration 0173), and its
    files live in that workspace's own namespace, outside the content store a seed copies from, so
    its rows alone would restore as packs whose files are missing. Refused as an asset is.
    """
    present = connection.execute(
        "select to_regclass('workspace_style_pack_version') is not null as present"
    )
    if not present.fetchone()["present"]:
        return
    held = connection.execute(
        "select count(*) as n from workspace_style_pack_version where workspace_id = %s",
        (workspace_id,),
    ).fetchone()
    if held["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['n']} style pack version(s), which are worn "
            "only in that workspace's worlds and never leave it; a seed cannot carry them"
        )


def _refuse_open_piece_requests(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """A workspace holding piece requests still open cannot be seeded.

    An open request is a standing ask for GPU time: restored elsewhere, the destination's generation
    worker would make pieces its workspace never asked for there, under the destination's own
    allowance. Ended requests, their batches and outputs hold catalog keys, digests and numbers
    only, and are carried; an open one is refused until it ends or its asker cancels it.
    """
    present = connection.execute("select to_regclass('piece_request') is not null as present")
    if not present.fetchone()["present"]:
        return
    held = connection.execute(
        "select count(*) as n from piece_request where workspace_id = %s "
        "and state in ('requested', 'queued')",
        (workspace_id,),
    ).fetchone()
    if held["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['n']} open piece request(s), standing asks for "
            "GPU time a seed would hand to another deployment; cancel them or let them end first"
        )


def _refuse_unfinished_creature_drafts(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> None:
    """A workspace with a creature draft still queued or running cannot be seeded.

    Until a draft ends, its job holds the person's words
    (:mod:`exulanica.selection.creature_drafts`), and a seed would carry them, and the job, to
    another server, where a worker could play it. An ended draft holds no word, and is carried as it
    is.
    """
    # The words live in the job, so the job is asked: a creature job queued or running.
    open_drafts = connection.execute(
        "select count(*) as n from job where workspace_id = %s and kind = 'creature_draft' "
        "and state in ('queued', 'running')",
        (workspace_id,),
    ).fetchone()
    if open_drafts["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} has {open_drafts['n']} creature draft(s) still queued or "
            "running, whose jobs hold the words they were asked with; a seed cannot carry them, so "
            "let them end first"
        )


def _refuse_generated_outputs(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """A workspace holding outputs of generated pieces cannot be seeded: the pieces' bytes live in
    the shared generated-pieces namespace, which a seed does not carry, so a destination would hold
    index rows and outputs for pieces it cannot serve."""
    present = connection.execute("select to_regclass('piece_output') is not null as present")
    if not present.fetchone()["present"]:
        return
    held = connection.execute(
        "select count(*) as n from piece_output where workspace_id = %s", (workspace_id,)
    ).fetchone()
    if held["n"]:
        raise SeedRefused(
            f"workspace {workspace_id} holds {held['n']} generated piece output(s), whose bytes "
            "live in the shared generated-pieces store a seed does not carry"
        )


def export_seed(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    workspace_id: uuid.UUID,
    destination: Path,
    created_at: str,
    allow_absent: bool = False,
    tiles: ContentAddressedStore | None = None,
) -> SeedManifest:
    """Write one workspace and exactly the bytes it references into ``destination``.

    ``connection`` reads the source and may be any role that can see the whole workspace.
    ``created_at`` is supplied rather than read from a clock, so a caller can produce the same
    archive twice and diff the two.

    ``tiles`` is the source's tile store. The baked tiles the workspace reaches (its generated
    worlds' tiles and the tiles it was served) are carried with their bytes, so a workspace that
    reaches any is refused without one rather than exported with tiles nothing could serve.

    ``allow_absent`` governs the one judgement call in the export. By default a row that
    references bytes the source store does not hold FAILS the export, because "complete" is the
    property this artifact is for. A source with a genuine gap, such as a derivative whose bytes
    were never materialised, is exported only when the caller says so, and every such key is
    written into the manifest's ``absent`` map with the table that referenced it. The restored
    stack is then missing exactly what the source was missing, and the manifest says which.

    Refuses a destination that already holds an archive: overwriting one in place would leave a
    half-written manifest describing a directory that no longer matches it.
    """
    if (destination / "manifest.json").exists():
        raise SeedRefused(f"{destination} already holds a seed archive; write to a new directory")
    _refuse_private_bakes(connection, workspace_id)
    _refuse_private_workspace_assets(connection, workspace_id)
    _refuse_held_things(connection, workspace_id)
    _refuse_private_workspace_style_packs(connection, workspace_id)
    _refuse_open_piece_requests(connection, workspace_id)
    _refuse_unfinished_creature_drafts(connection, workspace_id)
    _refuse_generated_outputs(connection, workspace_id)

    buckets = classify_tables(connection)
    exported = list(buckets["workspace"]) + list(buckets["reached"])
    order = _load_order(connection, exported)
    reached_tiles = _reached_baked_tiles(connection, workspace_id)
    if reached_tiles and tiles is None:
        raise SeedRefused(
            f"workspace {workspace_id} reaches {len(reached_tiles)} baked tile(s) and no tile "
            "store was given, so the seed cannot carry their bytes"
        )

    rows_dir = destination / "rows"
    rows_dir.mkdir(parents=True, exist_ok=True)
    parameters = {"workspace_id": str(workspace_id), "baked_tile_ids": reached_tiles}
    manifest_rows: dict[str, dict[str, Any]] = {}

    for position, table in enumerate(order):
        columns = _loadable_columns(connection, table)
        predicate = REACHED_TABLES.get(
            table, WORKSPACE_ROW_PREDICATES.get(table, "t.workspace_id = %(workspace_id)s")
        )
        query = sql.SQL("copy (select {} from {} t where {}) to stdout").format(
            sql.SQL(", ").join(sql.Identifier("t", name) for name in columns),
            sql.Identifier(table),
            sql.SQL(predicate),
        )
        path = rows_dir / f"{position:03d}_{table}.copy"
        count = 0
        with path.open("wb") as stream, connection.cursor().copy(query, parameters) as copy:
            for chunk in copy:
                data = bytes(chunk)
                count += data.count(b"\n")
                stream.write(data)
        digest, size = _digest_file(path)
        manifest_rows[path.name] = {
            "table": table,
            "columns": columns,
            "rows": count,
            "sha256": digest,
            "bytes": size,
        }

    blobs_dir = destination / "blobs"
    manifest_blobs: dict[str, dict[str, Any]] = {}
    manifest_absent: dict[str, dict[str, Any]] = {}
    optional = _reviewed_asset_keys(connection)
    referenced = _referenced_keys(connection, workspace_id)
    for key in sorted(referenced):
        blob_id = _blob_id(key)
        if not store.exists(blob_id):
            if key in optional:
                # The API writes these at startup. Refusing an export over bytes the destination
                # creates for itself would be refusing over nothing.
                continue
            if not allow_absent:
                raise SeedRefused(
                    f"{referenced[key]} references {key} and the source store does not hold it. "
                    "Pass allow_absent to export the gap as a recorded absence instead."
                )
            manifest_absent[key] = {"referenced_by": referenced[key]}
            continue
        payload = _read_key(store, key)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != blob_id.hex:
            raise SeedRefused(
                f"the store's bytes for {key} hash to {actual}; the key is not content addressed "
                "and an archive carrying it would be carrying a lie"
            )
        target = blobs_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        manifest_blobs[key] = {"sha256": actual, "bytes": len(payload)}

    manifest_tiles = (
        _export_tiles(connection, tiles, reached_tiles, destination / "tiles")
        if tiles is not None
        else {}
    )

    schema_version = connection.execute(
        "select max(version) as version from schema_migrations"
    ).fetchone()

    manifest = SeedManifest(
        seed_format_version=SEED_FORMAT_VERSION,
        workspace_id=workspace_id,
        schema_version=str(schema_version["version"]) if schema_version else "",
        created_at=created_at,
        rows=manifest_rows,
        blobs=manifest_blobs,
        registry_digest=_registry_digest(connection),
        absent=manifest_absent,
        tiles=manifest_tiles,
    )
    _write_manifest(destination, manifest)
    return manifest


# ---------------------------------------------------------------------------------------------
# The structural plane a sandbox version branches from
# ---------------------------------------------------------------------------------------------


def prepare_sandbox_world(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    title: str = "Judge sandbox",
) -> dict[str, Any]:
    """Open the sandbox through the same source-preserving path as the product route, and save
    the entry a judge opens it by.

    The sandbox branches from the seeded workspace's personal-source world, which the registry
    names; a seed whose workspace holds none, or several, is refused by name.

    The page opens a workspace's saved entry and, finding none, makes an authored starter, which
    writes ``world_identity``, a table the judge role may not write. So the entry is saved here, as
    the page saves one for a personal-source world (``createFromPersonalSources`` in
    ``web/packages/app/src/world-entry-api.ts``): the bootstrapped version, the world's current
    style version and ``source_kind`` personal, created by ``actor``. A world holds at most one
    entry, so a second run returns the one it holds rather than adding another, and an entry a
    judge could not open is refused by name.

    Returns the bootstrap report with ``entry`` (``created`` or ``reused``) and ``entry_id``.
    """
    from exulanica.world.bootstrap import bootstrap_world
    from exulanica.world.repository import WorldStyleRepository
    from exulanica.world.saved_entries import SavedWorldEntryRepository
    from exulanica.world.worlds import resolve_personal_source_world

    world_id = resolve_personal_source_world(connection, workspace_id)
    styles = WorldStyleRepository(connection, workspace_id, world_id=world_id)
    # Read before the bootstrap, as the page reads it; opening a version leaves the style alone.
    style_version_id = styles.current().version_id
    opened = bootstrap_world(
        connection,
        workspace_id=workspace_id,
        actor=actor,
        title=title,
        world_id=world_id,
        base_topology_digest=styles.current_topology_digest(),
    )
    entries = SavedWorldEntryRepository(connection, workspace_id)
    saved = next((entry for entry in entries.entries() if entry.world_id == world_id), None)
    state = "reused"
    if saved is None:
        saved = entries.create(
            world_id=world_id,
            title=title,
            authored_version_id=uuid.UUID(opened["version_id"]),
            style_version_id=style_version_id,
            created_by=actor,
            source_kind="personal",
        )
        state = "created"
    if saved.availability != "available":
        raise SeedRefused(
            f"world {world_id}'s saved entry {saved.entry_id} is unavailable "
            f"({saved.unavailable_reason}), so a judge could not open it"
        )
    return {**opened, "entry": state, "entry_id": str(saved.entry_id)}
