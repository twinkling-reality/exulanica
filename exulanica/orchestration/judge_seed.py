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
    holds. Its property is that it is BYTE VERIFIED: every row file and every blob is re-hashed
    against the manifest before it is loaded and the landed state is counted after, and a
    mismatch raises rather than warns.
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
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.canonical import canonical_json
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import grant_workspace_partition
from exulanica.errors import ExulanicaError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "GLOBAL_TABLES",
    "INSTANCE_TABLES",
    "JUDGE_ROLE",
    "JUDGE_WRITE_TABLES",
    "REACHED_TABLES",
    "SEED_FORMAT_VERSION",
    "SeedManifest",
    "SeedRefused",
    "classify_tables",
    "export_seed",
    "iter_row_tables",
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

#: Bumped when the layout changes in a way an older reader would misread. A restore refuses a
#: version it was not written for rather than reading it optimistically.
SEED_FORMAT_VERSION: Final = 1

#: The role the judge deployment's API connects as. Not ``exulanica_app``: the point of the
#: deployment is that it cannot write a source row or a deletion marker even if a route tried,
#: and a database role is the only place that can be true rather than merely intended.
JUDGE_ROLE: Final = "exulanica_judge"


class SeedRefused(ExulanicaError):
    """The archive, the schema, or the destination is not in a state this can proceed from."""


# ---------------------------------------------------------------------------------------------
# What the archive carries, and what it deliberately does not
# ---------------------------------------------------------------------------------------------

#: Tables with no ``workspace_id`` that migrations fill, and that this archive therefore omits.
#:
#: Every one is a registry: reviewed art profiles, capability vocabularies, the predicate list,
#: the stage catalogue, the reviewed object assets. ``exulanica-db`` recreates them from the
#: migration that inserted them, so carrying them would let a restore install a vocabulary that
#: disagrees with the schema it is installing into. The manifest records a digest over their
#: contents instead, and :func:`restore_seed` compares it before writing anything, which turns a
#: disagreement into a refusal rather than into an object that resolves to different bytes.
#:
#: This is the same set ``tests/conftest.py`` preserves across its per-test truncation, and for
#: the same reason: emptying them empties the vocabulary and every later insert is then refused
#: by a guard doing its job.
GLOBAL_TABLES: Final[Mapping[str, str]] = {
    "interaction_capability_registry": "migration-provided interaction vocabulary",
    "predicate": "migration-provided predicate vocabulary",
    "world_art_profile_module": "migration-provided reviewed art profile",
    "world_art_profile_parameter": "migration-provided reviewed art profile",
    "world_art_profile_registry": "migration-provided reviewed art profile",
    "world_object_behaviour_registry": "migration-provided reviewed object behaviours",
    "world_reviewed_asset": "migration-provided reviewed object assets",
    "world_style_capability_registry": "migration-provided style capability vocabulary",
    "world_style_module_capability": "migration-provided style capability vocabulary",
    "world_style_module_registry": "migration-provided style capability vocabulary",
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
    # Cross-workspace match calibration, keyed on `predicate_id` and accumulated by whichever
    # deployment ran the matcher. Carrying one deployment's empirical bins into another would be
    # importing a confidence curve measured on a corpus the destination does not hold.
    "calibration": "cross-workspace matcher calibration, accumulated per deployment",
    "restore_control": "per-deployment deletion checkpoint state, not workspace content",
    "restore_replay_receipt": "per-deployment deletion checkpoint state, not workspace content",
    "schema_migrations": "the destination records what it applied, not what the source did",
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
REACHED_TABLES: Final[Mapping[str, str]] = {
    "blob": (
        "t.blob_sha256 in ("
        "  select c.blob_sha256 from capture c where c.workspace_id = %(workspace_id)s)"
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
        # `tenant_id` is the workspace under migration 0001's original name, and its policy still
        # reads the `orimera.tenant_id` setting rather than the `exulanica.workspace_id` one.
        # Filtering on the column rather than relying on the policy is what makes that difference
        # harmless here.
        "t.tenant_id = %(workspace_id)s"
    ),
}

#: Tables the judge role may write, and nothing else in the schema.
#:
#: Derived from the routes a judge is given rather than from a category: create a sandbox version
#: and edit the objects in it, preview and apply an appearance, and let the Companion record what
#: it was asked and answered. Everything absent is readable and not writable.
#:
#: ``capture``, ``intake_batch``, ``artifact``, ``blob``, ``entity_link``, ``identity_event``,
#: ``person_subject``, ``person_withdrawal_receipt``, ``tombstone`` and ``purge_job`` are what
#: this is about, and they are absent because absence is the grant.
JUDGE_WRITE_TABLES: Final[tuple[str, ...]] = (
    # A sandbox version and the authored objects inside it.
    "world_alternate_version",
    "world_alternate_version_edit",
    "world_alternate_object",
    "world_alternate_element_override",
    # Appearance: preview, apply, discard, rollback, and the audit row each leaves behind.
    "world_style_proposal",
    "world_style_preview",
    "world_style_version",
    "world_style_state",
    "world_style_audit_event",
    "world_region_style_version",
    # Asking the Companion, and what it remembers across a reload.
    "companion_answer",
    "companion_answer_citation",
    "companion_escape",
)

#: Tables a reset may not empty, because migration 0013 put a BEFORE TRUNCATE guard on them.
#:
#: Nothing else in the schema guards TRUNCATE. The judge role holds no grant on either, and a
#: workspace that has deleted nothing carries no rows for them, so the ordinary case never
#: reaches this. A seed that DOES carry rows for them is refused rather than worked around.
_TRUNCATE_GUARDED: Final = ("purge_job", "tombstone")

#: The advisory key :func:`provision_judge_role` holds while it writes ``pg_authid``. The same
#: reasoning as ``exulanica.db.roles._ROLE_LOCK_KEY`` and deliberately a different value, so a
#: judge provision and a runtime provision serialise rather than deadlock.
_JUDGE_ROLE_LOCK_KEY: Final = 119_622_351

#: A row file is ``<order>_<table>.copy``. The order is the topological position, so a directory
#: listing IS the load order and a reader can see the dependency shape without running anything.
_ROW_FILE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.copy$")

#: Store keys are ``sha-256/<first two hex>/<next two hex>/<full digest>``. A manifest is an
#: input, so anything else is refused rather than joined onto a path.
_STORE_KEY = re.compile(r"^sha-256/[0-9a-f]{2}/[0-9a-f]{2}/([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class SeedManifest:
    """Everything a restore needs to know, and everything a verification compares against."""

    seed_format_version: int
    workspace_id: uuid.UUID
    schema_version: str
    created_at: str
    #: ``{file name: {"table": str, "rows": int, "sha256": str, "bytes": int}}``.
    rows: Mapping[str, Mapping[str, Any]]
    #: ``{store key: {"sha256": str, "bytes": int}}``.
    blobs: Mapping[str, Mapping[str, Any]]
    #: One digest over every migration-provided registry this archive expects to find.
    registry_digest: str
    #: Keys a row references that the SOURCE store does not hold, as
    #: ``{store key: {"referenced_by": str}}``. Recorded rather than hidden: a restored stack is
    #: then missing exactly what the source was missing, and the manifest says which, instead of
    #: the archive quietly promising bytes nobody has. Only ever non-empty when the export was
    #: asked for it.
    absent: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "seed_format_version": self.seed_format_version,
            "workspace_id": str(self.workspace_id),
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "registry_digest": self.registry_digest,
            "rows": {name: dict(value) for name, value in sorted(self.rows.items())},
            "blobs": {key: dict(value) for key, value in sorted(self.blobs.items())},
            "absent": {key: dict(value) for key, value in sorted(self.absent.items())},
            "totals": {
                "row_files": len(self.rows),
                "rows": sum(int(value["rows"]) for value in self.rows.values()),
                "blobs": len(self.blobs),
                "blob_bytes": sum(int(value["bytes"]) for value in self.blobs.values()),
                "absent": len(self.absent),
            },
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> SeedManifest:
        try:
            return cls(
                seed_format_version=int(value["seed_format_version"]),
                workspace_id=uuid.UUID(str(value["workspace_id"])),
                schema_version=str(value["schema_version"]),
                created_at=str(value["created_at"]),
                rows=dict(value["rows"]),
                blobs=dict(value["blobs"]),
                registry_digest=str(value["registry_digest"]),
                absent=dict(value.get("absent") or {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SeedRefused(
                f"the manifest is not a seed manifest this version reads: {exc}"
            ) from exc


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


def _registry_digest(connection: psycopg.Connection) -> str:
    """One digest over every migration-provided registry, in a fixed order.

    Compared rather than carried. If the destination's migrations produced a different reviewed
    asset list from the source's, an authored object in the archive names bytes the destination
    resolves differently, and that has to be a refusal rather than a picture nobody can explain.
    """
    parts: list[dict[str, Any]] = []
    for table in sorted(GLOBAL_TABLES):
        # Timestamps are dropped, and that is the difference between a digest that means
        # something and one that never matches. `world_reviewed_asset.reviewed_at` defaults to
        # `now()`, so two correctly migrated schemas disagree on it by construction: the value
        # records when the migration ran on that machine, not what the registry says. The
        # vocabulary is what is being compared, so the vocabulary is what is hashed.
        volatile = [
            row["column_name"]
            for row in connection.execute(
                "select column_name from information_schema.columns"
                " where table_schema = current_schema() and table_name = %s"
                "   and data_type like 'timestamp%%'"
                " order by column_name",
                (table,),
            ).fetchall()
        ]
        # Rendered by PostgreSQL rather than by Python, and the reason is `step_value`, a real in
        # `world_art_profile_parameter`. `canonical_json` refuses a float outright, which is the
        # right rule for a digest input: two implementations need not agree on how one is
        # spelled. jsonb's own text form is one implementation's spelling, and comparing a
        # registry against itself across two schemas on one server is exactly the case where
        # that is enough.
        rows = connection.execute(
            sql.SQL("select (to_jsonb(t.*) - %s::text[])::text as row from {} t").format(
                sql.Identifier(table)
            ),
            (volatile,),
        ).fetchall()
        parts.append(
            {"table": table, "rows": sorted(row["row"] for row in rows), "dropped": volatile}
        )
    return hashlib.sha256(canonical_json(parts)).hexdigest()


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


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _blob_id(key: str) -> BlobId:
    """The blob id a store key names, or a refusal.

    A manifest is an input. Turning its keys into paths by concatenation is how a manifest gets
    to name ``../../etc``, so the pattern is matched first and the id is built from the digest it
    captured rather than from the string as given.
    """
    match = _STORE_KEY.match(key)
    if match is None:
        raise SeedRefused(f"{key!r} is not a sha-256 store key")
    return BlobId.from_hex(match.group(1))


def _read_key(store: ContentAddressedStore, key: str) -> bytes:
    """Read one object through the store's interface rather than through a path.

    ``LocalContentAddressedStore`` is the only backend today and it writes its files 0444, so
    reaching around it to a path would work, and would also be the line that has to change on the
    day a second backend exists.
    """
    try:
        return store.get(_blob_id(key))
    except OSError as exc:
        raise SeedRefused(f"the store does not hold {key}: {exc}") from exc


def _key_for(digest: str) -> str:
    return f"sha-256/{digest[:2]}/{digest[2:4]}/{digest}"


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


def export_seed(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    workspace_id: uuid.UUID,
    destination: Path,
    created_at: str,
    allow_absent: bool = False,
) -> SeedManifest:
    """Write one workspace and exactly the bytes it references into ``destination``.

    ``connection`` reads the source and may be any role that can see the whole workspace.
    ``created_at`` is supplied rather than read from a clock, so a caller can produce the same
    archive twice and diff the two.

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

    buckets = classify_tables(connection)
    exported = list(buckets["workspace"]) + list(buckets["reached"])
    order = _load_order(connection, exported)

    rows_dir = destination / "rows"
    rows_dir.mkdir(parents=True, exist_ok=True)
    parameters = {"workspace_id": str(workspace_id)}
    manifest_rows: dict[str, dict[str, Any]] = {}

    for position, table in enumerate(order):
        columns = _loadable_columns(connection, table)
        predicate = REACHED_TABLES.get(table, "t.workspace_id = %(workspace_id)s")
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
    )
    _write_manifest(destination, manifest)
    return manifest


def _write_manifest(destination: Path, manifest: SeedManifest) -> None:
    """Write the manifest and, beside it, the digest of the manifest itself.

    The manifest attests to every other file, so nothing attests to the manifest. A second file
    holding its digest is not a signature and does not pretend to be one. It is what makes "the
    archive I verified is the archive I restored" checkable by a person with ``shasum``.
    """
    payload = canonical_json(manifest.to_json())
    (destination / "manifest.json").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (destination / "manifest.sha256").write_text(f"{digest}  manifest.json\n", encoding="utf-8")


def read_manifest(archive: Path) -> SeedManifest:
    """Read the manifest after checking it against its own recorded digest."""
    path = archive / "manifest.json"
    try:
        payload = path.read_bytes()
        recorded = (archive / "manifest.sha256").read_text(encoding="utf-8").split()[0]
    except OSError as exc:
        raise SeedRefused(f"{archive} is not a seed archive: {exc}") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != recorded:
        raise SeedRefused(f"manifest.json hashes to {actual}, and manifest.sha256 says {recorded}")
    manifest = SeedManifest.from_json(json.loads(payload))
    if manifest.seed_format_version != SEED_FORMAT_VERSION:
        raise SeedRefused(
            f"the archive is seed format {manifest.seed_format_version} and this build reads "
            f"{SEED_FORMAT_VERSION}"
        )
    return manifest


# ---------------------------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------------------------


def verify_seed(archive: Path, manifest: SeedManifest | None = None) -> SeedManifest:
    """Re-hash every file in ``archive`` and compare it against the manifest, both directions.

    A file whose digest differs is a corrupted archive. A file the manifest does not mention is
    an archive somebody added to, which is the same problem arriving from the other side.
    """
    manifest = read_manifest(archive) if manifest is None else manifest

    rows_dir = archive / "rows"
    present = {path.name for path in rows_dir.glob("*.copy")} if rows_dir.is_dir() else set()
    if present != set(manifest.rows):
        raise SeedRefused(
            "the archive's row files do not match the manifest: unexpected "
            f"{sorted(present - set(manifest.rows))}, missing "
            f"{sorted(set(manifest.rows) - present)}"
        )
    for name, recorded in manifest.rows.items():
        digest, size = _digest_file(rows_dir / name)
        if digest != recorded["sha256"] or size != recorded["bytes"]:
            raise SeedRefused(
                f"{name} hashes to {digest} at {size} bytes; the manifest says "
                f"{recorded['sha256']} at {recorded['bytes']} bytes"
            )

    blobs_dir = archive / "blobs"
    found = (
        {str(path.relative_to(blobs_dir)) for path in blobs_dir.rglob("*") if path.is_file()}
        if blobs_dir.is_dir()
        else set()
    )
    if found != set(manifest.blobs):
        raise SeedRefused(
            "the archive's blobs do not match the manifest: unexpected "
            f"{sorted(found - set(manifest.blobs))[:5]}, missing "
            f"{sorted(set(manifest.blobs) - found)[:5]}"
        )
    overlap = set(manifest.absent) & set(manifest.blobs)
    if overlap:
        raise SeedRefused(
            "the manifest records these keys as both carried and absent, so it disagrees with "
            f"itself about what the archive holds: {sorted(overlap)[:5]}"
        )
    for key, recorded in manifest.blobs.items():
        digest, size = _digest_file(blobs_dir / key)
        if digest != recorded["sha256"] or size != recorded["bytes"]:
            raise SeedRefused(
                f"{key} hashes to {digest} at {size} bytes; the manifest says "
                f"{recorded['sha256']} at {recorded['bytes']} bytes"
            )
    return manifest


def verify_restored(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    manifest: SeedManifest,
) -> None:
    """Check the LANDED state, which is a different question from checking the archive.

    :func:`verify_seed` proves the archive is the archive. This proves the destination now holds
    it: every blob is in the store at its recorded digest, and every table holds the recorded row
    count. A restore that reported success while a COPY silently wrote nothing is what this
    catches.
    """
    for key in manifest.absent:
        if store.exists(_blob_id(key)):
            raise SeedRefused(
                f"the manifest records {key} as absent from the source, and the destination "
                "store holds it. The restored stack would not be the state the seed describes."
            )
    for key, recorded in manifest.blobs.items():
        payload = _read_key(store, key)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != recorded["sha256"] or len(payload) != recorded["bytes"]:
            raise SeedRefused(
                f"the restored store's {key} hashes to {digest} at {len(payload)} bytes; the "
                f"manifest says {recorded['sha256']} at {recorded['bytes']} bytes"
            )
    for _name, recorded in sorted(manifest.rows.items()):
        table = str(recorded["table"])
        landed = connection.execute(
            sql.SQL("select count(*) as n from {}").format(sql.Identifier(table))
        ).fetchone()
        if landed is None or int(landed["n"]) != int(recorded["rows"]):
            found = "none" if landed is None else landed["n"]
            raise SeedRefused(
                f"{table} holds {found} rows after the restore and the manifest recorded "
                f"{recorded['rows']}"
            )


# ---------------------------------------------------------------------------------------------
# Restore and reset
# ---------------------------------------------------------------------------------------------


def _row_files(manifest: SeedManifest) -> list[tuple[str, str]]:
    """The manifest's row files in load order, as ``(file name, table)``."""
    ordered: list[tuple[int, str, str]] = []
    for name, recorded in manifest.rows.items():
        match = _ROW_FILE.match(name)
        if match is None:
            raise SeedRefused(f"the manifest names a row file this format cannot read: {name}")
        ordered.append((int(match.group(1)), name, str(recorded["table"])))
    return [(name, table) for _, name, table in sorted(ordered)]


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
            path = archive / "rows" / name
            statement = sql.SQL("copy {} ({}) from stdin").format(
                sql.Identifier(table),
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            )
            with connection.cursor().copy(statement) as copy, path.open("rb") as stream:
                while chunk := stream.read(1 << 20):
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


def _load_blobs(archive: Path, store: ContentAddressedStore, manifest: SeedManifest) -> int:
    """Place the archive's blobs in the store, skipping any already there.

    Content addressed, so an object already at that key IS the object and putting it again would
    be work with no effect. Written through ``put_bytes``, which is what gives the file the
    store's layout and its 0444 mode; copying the archive's file into place directly would leave
    a writable object at a key that promises immutability.
    """
    written = 0
    for key, recorded in sorted(manifest.blobs.items()):
        blob_id = _blob_id(key)
        if store.exists(blob_id):
            continue
        payload = (archive / "blobs" / key).read_bytes()
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


def restore_seed(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    archive: Path,
    verify: bool = True,
) -> SeedManifest:
    """Bring a freshly migrated, empty database and store to what ``archive`` holds.

    ``connection`` is administrative: the same principal that ran the migrations, because the
    load writes tables no runtime role may write and creates the workspace's embedding partition.

    The order is not negotiable. The registry digest is compared BEFORE anything is written,
    because a mismatch means this archive's authored objects name bytes this schema resolves
    differently and there is nothing to gain from a half load. The partition is created before
    the rows, because ``embedding`` has nowhere to put a row without it.
    """
    manifest = verify_seed(archive) if verify else read_manifest(archive)

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
    _load_rows(connection, archive, manifest)
    _load_blobs(archive, store, manifest)
    if verify:
        verify_restored(connection, store, manifest)
    return manifest


def reset_to_seed(
    connection: psycopg.Connection,
    *,
    archive: Path,
    verify: bool = True,
) -> SeedManifest:
    """Return a used stack to the archive's rows. The store is not touched.

    **The store is not touched, and that is a decision rather than an optimisation.** Keys are
    content addressed, and a reset that deleted them would be deleting the evidence every
    citation in the workspace resolves to. ``docs/demo-integrity.md`` section 2.2 said so before
    there was code to say it in.

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

    keep = [(name, table) for name, table in files if table not in _TRUNCATE_GUARDED]
    with connection.transaction():
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, true)", (str(manifest.workspace_id),)
        )
        connection.execute(
            sql.SQL("truncate {} cascade").format(
                sql.SQL(", ").join(sql.Identifier(table) for _, table in keep)
            )
        )
        connection.execute("set constraints all deferred")
        _copy_in(connection, archive, manifest, keep)
    return manifest


# ---------------------------------------------------------------------------------------------
# The judge role, and the token that reaches it
# ---------------------------------------------------------------------------------------------


def provision_judge_role(
    connection: psycopg.Connection,
    *,
    role: str = JUDGE_ROLE,
    password: str | None = None,
) -> None:
    """Create the role a judge deployment's API connects as, and grant it exactly two things.

    **SELECT on everything, INSERT and UPDATE on** :data:`JUDGE_WRITE_TABLES` **and nothing
    else.** Not "revoke the dangerous ones": the grant is an allowlist, so a table a later
    migration adds arrives readable and not writable without anybody remembering to come back
    here. That is the direction this has to fail in.

    **No DELETE anywhere, for the same reason** ``exulanica_app`` **has none.** Deletion in this
    system is a tombstone and a purge job, both of them writes to tables absent from the
    allowlist, so the judge cannot reach erasure through the front door either.

    ``nobypassrls`` and no ownership, so the workspace policy is a boundary for this role rather
    than a decoration. The same advisory-lock discipline as
    :func:`exulanica.db.roles.provision_runtime_role`, because roles are cluster-global and two
    stacks starting at once otherwise collide in ``pg_authid``.

    Idempotent, and re-running it after a migration is how the allowlist reaches a new table.
    """
    role_name = sql.Identifier(role)
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    schema = sql.Identifier(row["current_schema"] if isinstance(row, dict) else row[0])

    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (_JUDGE_ROLE_LOCK_KEY,))
        exists = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
        if exists is None:
            connection.execute(sql.SQL("create role {} login nobypassrls").format(role_name))
        else:
            connection.execute(sql.SQL("alter role {} nobypassrls").format(role_name))
        if password is not None:
            connection.execute(
                sql.SQL("alter role {} password {}").format(role_name, sql.Literal(password))
            )

        connection.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role_name))
        # Start from nothing every time, so removing a table from the allowlist actually removes
        # the grant rather than leaving one an earlier run made.
        connection.execute(
            sql.SQL("revoke all on all tables in schema {} from {}").format(schema, role_name)
        )
        connection.execute(
            sql.SQL("grant select on all tables in schema {} to {}").format(schema, role_name)
        )
        for table in JUDGE_WRITE_TABLES:
            present = connection.execute(
                "select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = current_schema() and c.relname = %s"
                "   and c.relkind in ('r', 'p')",
                (table,),
            ).fetchone()
            if present is None:
                raise SeedRefused(
                    f"the judge write allowlist names {table}, which is not in this schema"
                )
            connection.execute(
                sql.SQL("grant insert, update on {} to {}").format(sql.Identifier(table), role_name)
            )
        connection.execute(
            sql.SQL("grant usage, select on all sequences in schema {} to {}").format(
                schema, role_name
            )
        )
        # Partitions created later by provision_workspace, and any table a later migration adds,
        # arrive readable. Writability is never a default.
        connection.execute(
            sql.SQL("alter default privileges in schema {} grant select on tables to {}").format(
                schema, role_name
            )
        )


def judge_grants(connection: psycopg.Connection, *, role: str = JUDGE_ROLE) -> dict[str, set[str]]:
    """What ``role`` may actually do, read back from the live catalog.

    Read back rather than recorded. A test comparing the allowlist against itself would pass on a
    database where not one of those statements ran.
    """
    rows = connection.execute(
        "select c.relname as name, p.privilege_type as privilege"
        "  from pg_class c"
        "  join pg_namespace n on n.oid = c.relnamespace"
        "  cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) p"
        "  join pg_roles r on r.oid = p.grantee"
        " where n.nspname = current_schema() and c.relkind in ('r', 'p') and r.rolname = %s",
        (role,),
    ).fetchall()
    grants: dict[str, set[str]] = {}
    for row in rows:
        grants.setdefault(row["name"], set()).add(row["privilege"])
    return grants


def mint_judge_token(*, workspace_id: uuid.UUID, actor: uuid.UUID, token: str) -> dict[str, Any]:
    """Build the one-entry token directory a judge deployment serves.

    The token value is supplied rather than generated here, so the caller owns where the entropy
    came from and this stays testable without a random source. It is checked against the same
    32-character floor :func:`exulanica.api.authorisation.load_token_directory` enforces, because
    a token minted here and refused there is a deployment that starts and accepts nobody.

    ``may_include_proposals`` is false. A judge is shown what the system has confirmed rather
    than what it has guessed, and the Selection plan must not be able to widen that.
    """
    if len(token) < 32:
        raise SeedRefused(
            "a bearer token shorter than 32 characters is refused by the API at load time, so "
            "minting one here would produce a deployment that cannot start"
        )
    return {
        token: {
            "workspace_id": str(workspace_id),
            "actor": str(actor),
            "may_include_proposals": False,
        }
    }


def iter_row_tables(manifest: SeedManifest) -> Iterator[str]:
    """Every table the archive carries, in load order. Used by tests and by the CLI's report."""
    for _, table in _row_files(manifest):
        yield table


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
    """Compose the structural plane and open one sandbox version, so a judge can place an object.

    **Why this is needed at all.** ``POST /world/versions`` requires a ``source_snapshot_id`` and
    refuses one that is not in ``world_structure_snapshot``; ``add_object`` validates the object's
    ``region_id`` against ``world_structure_snapshot_region``. No HTTP route creates either. The
    browser client has no create-version control and reports "this world has no alternate version
    yet, so there is nowhere to add an object" when it finds none. So a workspace with a topology
    contract and no structural snapshot offers a judge a world that can be walked and asked, and
    an object surface that is dead. This closes that gap once, before the export, so the seed
    carries a world that is complete for every capability the judge token grants.

    **What it composes, and what it does not claim.** One region per row already in
    ``world_topology_region``, one element per region owned by that region, and one destination
    per region, with each element's evidence pointing at an evidence span the region's own source
    slots already name. It asserts NO new temporal, metric, reconstruction or semantic fact about
    any photograph: it lifts the authored source composition into the structural plane so the
    plane exists. It goes through ``WorldStructureRepository.preview`` and ``apply``, the reviewed
    writer, so every validator the product runs on a structural change runs on this one.

    The placement is a plain row of regions ten metres apart. There is no measured geometry here
    and this does not pretend there is; a rung is a property of a region and this changes none.
    """
    from exulanica.world import (
        DEFAULT_WORLD_ID,
        SpatialCandidate,
        WorldObjectRepository,
        WorldStructureRepository,
    )

    regions = [
        str(row["region_id"])
        for row in connection.execute(
            "select region_id from world_topology_region"
            " where workspace_id = %s and world_id = %s order by region_id",
            (str(workspace_id), DEFAULT_WORLD_ID),
        ).fetchall()
    ]
    if not regions:
        raise SeedRefused(
            f"workspace {workspace_id} has no topology region, so there is no world to give a "
            "structural plane. Compose the source slots first."
        )

    spans = {
        str(row["region_id"]): row["evidence_span_id"]
        for row in connection.execute(
            "select distinct on (region_id) region_id, evidence_span_id"
            "  from world_topology_source"
            " where workspace_id = %s and evidence_span_id is not null"
            " order by region_id, evidence_span_id",
            (str(workspace_id),),
        ).fetchall()
    }

    elements: list[dict[str, Any]] = []
    destinations: list[dict[str, Any]] = []
    placements: list[dict[str, Any]] = []
    destination_placements: list[dict[str, Any]] = []
    for ordinal, region in enumerate(regions):
        element_id = f"element:{region}:root"
        destination_id = f"destination:{region}"
        span = spans.get(region)
        elements.append(
            {
                "element_id": element_id,
                "owner": {"kind": "region", "id": region},
                "module": {
                    "key": "region.evidence-cards",
                    "version": 1,
                    "requested_key": "region.evidence-cards",
                },
                "lineage": {
                    "recipe_key": "region.rung-3",
                    "recipe_version": 1,
                    "slot_key": "root",
                },
                "collision": {"kind": "circle", "radius_mm": 1_000},
                "evidence": (
                    {"kind": "span", "span_id": str(span)}
                    if span is not None
                    else {"kind": "missing", "reason": "this region names no authorised source"}
                ),
                "attachment": None,
                "streaming_key": "world-asset:region.evidence-cards@1",
            }
        )
        destinations.append(
            {"destination_id": destination_id, "region_id": region, "required": True}
        )
        placements.append(
            {
                "element_id": element_id,
                "x_mm": ordinal * 10_000,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
        )
        destination_placements.append(
            {"destination_id": destination_id, "x_mm": ordinal * 10_000, "y_mm": 1_600, "z_mm": 0}
        )

    edges = [
        {
            "from": f"destination:{regions[index]}",
            "to": f"destination:{regions[index + 1]}",
            "kind": "field",
            "max_slope_millidegrees": 0,
        }
        for index in range(len(regions) - 1)
    ]

    topology = {
        "schema_version": 1,
        "world_id": DEFAULT_WORLD_ID,
        "regions": [{"region_id": region} for region in regions],
        "elements": elements,
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": destinations,
            "edges": edges,
        },
        "dependencies": [],
    }
    layout = {
        "schema_version": 1,
        "layout_version": 1,
        "regions": [
            {"region_id": region, "creation_ordinal": ordinal}
            for ordinal, region in enumerate(regions)
        ],
    }
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": placements,
        "destinations": destination_placements,
    }
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [{"neighborhood_id": "neighborhood:0", "region_ids": list(regions)}],
    }

    # Both digests name what the composition was conditioned on. They are computed over the rows
    # this workspace actually holds rather than over a label, so a world composed from a changed
    # graph or a changed set of derivatives is a different snapshot and says so.
    graph_sha256 = _plane_digest(
        connection,
        "select capture_id, blob_sha256 from capture"
        " where workspace_id = %s and deleted_at is null order by capture_id",
        workspace_id,
    )
    reconstruction_sha256 = _plane_digest(
        connection,
        "select artifact_id, kind, content_sha256 from artifact"
        " where workspace_id = %s and purged_at is null order by artifact_id",
        workspace_id,
    )

    structures = WorldStructureRepository(connection, workspace_id)
    current = structures.current()
    if current is None:
        preview = structures.preview(
            SpatialCandidate(
                graph_sha256,
                reconstruction_sha256,
                topology,
                layout,
                placement,
                neighborhood,
            ),
            proposed_by=actor,
        )
        snapshot = structures.apply(
            preview.preview_id,
            base_snapshot_id=preview.base_snapshot_id,
            base_graph_sha256=preview.base_graph_sha256,
            base_reconstruction_sha256=preview.base_reconstruction_sha256,
            committed_by=actor,
        )
        composed = "applied"
    else:
        snapshot = current
        composed = "reused"

    objects = WorldObjectRepository(connection, workspace_id)
    existing = objects.versions()
    if existing:
        version = existing[0]
        opened = "reused"
    else:
        version = objects.create_version(
            source_snapshot_id=snapshot.snapshot_id, title=title, created_by=actor
        )
        opened = "created"
    return {
        "snapshot": composed,
        "snapshot_id": str(snapshot.snapshot_id),
        "regions": regions,
        "version": opened,
        "version_id": str(version.version_id),
        "state_sha256": version.state_sha256,
    }


def _plane_digest(connection: psycopg.Connection, statement: str, workspace_id: uuid.UUID) -> str:
    """A digest over one durable plane, rendered by PostgreSQL for the reason above."""
    rows = connection.execute(statement, (str(workspace_id),)).fetchall()
    return hashlib.sha256(
        canonical_json([{key: str(value) for key, value in row.items()} for row in rows])
    ).hexdigest()
