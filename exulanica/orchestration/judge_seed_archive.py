"""A judge seed archive as files: its manifest, what the manifest names, and the checks of both.

An archive is a directory: ``manifest.json`` and the digest of it in ``manifest.sha256``, one row
file per carried table under ``rows/``, and the objects it carries under ``blobs/`` and ``tiles/``
at their store keys. :class:`SeedManifest` is what a restore needs to know and what a verification
compares against, including the registry digest a destination's migrations are held to.
:func:`read_manifest` refuses a format other than :data:`SEED_FORMAT_VERSION`, :func:`verify_seed`
re-hashes the archive against its manifest and :func:`verify_restored` checks what a restore
landed. :class:`SeedRefused` is the refusal every part of the seed raises.

:mod:`exulanica.orchestration.judge_seed` writes an archive and
:mod:`exulanica.orchestration.judge_seed_restore` loads one.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql

from exulanica.canonical import canonical_json
from exulanica.db.registries import REGISTRY_TABLES
from exulanica.errors import ExulanicaError
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

#: Bumped when the layout changes in a way an older reader would misread. A restore refuses a
#: version it was not written for rather than reading it optimistically.
SEED_FORMAT_VERSION: Final = 2

#: Why each earlier format is refused, by its version. A version absent here and not
#: :data:`SEED_FORMAT_VERSION` is refused as one this build was not written for.
_EARLIER_FORMATS: Final[Mapping[int, str]] = {
    1: (
        "format 1 carries no baked tiles and its registry digest covers the global baked_tile "
        "table, so a source that has baked any tile is refused by the digest and a generated "
        "world it holds would read as baking for ever on a stack that runs no bake worker. "
        "Export the workspace again with this build"
    ),
}


class SeedRefused(ExulanicaError):
    """The archive, the schema, or the destination is not in a state this can proceed from."""


#: How much of a row file or an archived object is read at once: one mebibyte, so a file is
#: streamed through a digest or a COPY rather than held whole.
_CHUNK_BYTES: Final = 1 << 20

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
    #: The containers of the carried ``baked_tile`` rows, from the tile store, as
    #: ``{store key: {"sha256": str, "bytes": int}}``. A judge stack runs no bake worker, so a
    #: tile whose bytes the seed did not carry could never be served there.
    tiles: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

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
            "tiles": {key: dict(value) for key, value in sorted(self.tiles.items())},
            "totals": {
                "row_files": len(self.rows),
                "rows": sum(int(value["rows"]) for value in self.rows.values()),
                "blobs": len(self.blobs),
                "blob_bytes": sum(int(value["bytes"]) for value in self.blobs.values()),
                "absent": len(self.absent),
                "tiles": len(self.tiles),
                "tile_bytes": sum(int(value["bytes"]) for value in self.tiles.values()),
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
                tiles=dict(value["tiles"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SeedRefused(
                f"the manifest is not a seed manifest this version reads: {exc}"
            ) from exc


def _registry_digest(connection: psycopg.Connection) -> str:
    """One digest over every migration-provided registry, in a fixed order.

    Compared rather than carried. If the destination's migrations produced a different reviewed
    asset list from the source's, an authored object in the archive names bytes the destination
    resolves differently, and that has to be a refusal rather than a picture nobody can explain.

    Over :data:`~exulanica.db.registries.REGISTRY_TABLES` and nothing else. A global table that
    something other than a migration writes differs between a stack that has used it and a fresh
    one by construction: with ``baked_tile`` hashed here, every seed exported after a town was
    made was refused by a fresh destination.
    """
    parts: list[dict[str, Any]] = []
    for table in sorted(REGISTRY_TABLES):
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


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
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

    A path reaches the local backend and nothing else: the S3-compatible backend has no path, so
    reading through the interface is what lets a seed move between the two.
    """
    try:
        return store.get(_blob_id(key))
    except OSError as exc:
        raise SeedRefused(f"the store does not hold {key}: {exc}") from exc


def _key_for(digest: str) -> str:
    return f"sha-256/{digest[:2]}/{digest[2:4]}/{digest}"


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
    document = json.loads(payload)
    _refuse_other_formats(document)
    return SeedManifest.from_json(document)


def _refuse_other_formats(document: Any) -> None:
    """Refuse a manifest of any format but this build's, naming the format and why.

    Checked before the manifest is read as this format's, so an earlier archive is refused for
    what it is rather than for a field it never had.
    """
    try:
        version = int(document["seed_format_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SeedRefused(f"the manifest states no seed format version: {exc!r}") from exc
    if version == SEED_FORMAT_VERSION:
        return
    reason = _EARLIER_FORMATS.get(version)
    if reason is not None:
        raise SeedRefused(
            f"the archive is seed format {version} and this build reads "
            f"{SEED_FORMAT_VERSION}: {reason}"
        )
    raise SeedRefused(
        f"the archive is seed format {version} and this build reads {SEED_FORMAT_VERSION}, a "
        "format it was not written for and does not read optimistically"
    )


def _row_files(manifest: SeedManifest) -> list[tuple[str, str]]:
    """The manifest's row files in load order, as ``(file name, table)``."""
    ordered: list[tuple[int, str, str]] = []
    for name, recorded in manifest.rows.items():
        match = _ROW_FILE.match(name)
        if match is None:
            raise SeedRefused(f"the manifest names a row file this format cannot read: {name}")
        ordered.append((int(match.group(1)), name, str(recorded["table"])))
    return [(name, table) for _, name, table in sorted(ordered)]


def iter_row_tables(manifest: SeedManifest) -> Iterator[str]:
    """Every table the archive carries, in load order. Used by tests and by the CLI's report."""
    for _, table in _row_files(manifest):
        yield table


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

    _verify_archived(archive / "blobs", manifest.blobs)
    overlap = set(manifest.absent) & set(manifest.blobs)
    if overlap:
        raise SeedRefused(
            "the manifest records these keys as both carried and absent, so it disagrees with "
            f"itself about what the archive holds: {sorted(overlap)[:5]}"
        )
    _verify_archived(archive / "tiles", manifest.tiles)
    return manifest


def _verify_archived(directory: Path, recorded: Mapping[str, Mapping[str, Any]]) -> None:
    """The store objects under ``directory`` are exactly ``recorded``, each at its digest."""
    found = (
        {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
        if directory.is_dir()
        else set()
    )
    if found != set(recorded):
        raise SeedRefused(
            f"the archive's {directory.name} do not match the manifest: unexpected "
            f"{sorted(found - set(recorded))[:5]}, missing {sorted(set(recorded) - found)[:5]}"
        )
    for key, value in recorded.items():
        digest, size = _digest_file(directory / key)
        if digest != value["sha256"] or size != value["bytes"]:
            raise SeedRefused(
                f"{directory.name}/{key} hashes to {digest} at {size} bytes; the manifest says "
                f"{value['sha256']} at {value['bytes']} bytes"
            )


def verify_restored(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    manifest: SeedManifest,
    *,
    tiles: ContentAddressedStore | None = None,
) -> None:
    """Check the LANDED state, which is a different question from checking the archive.

    :func:`verify_seed` proves the archive is the archive. This proves the destination now holds
    it: every blob is in the store and every baked tile's bytes in ``tiles`` at their recorded
    digests, and every table holds the recorded row count. A restore that reported success while
    a COPY silently wrote nothing is what this catches.
    """
    for key in manifest.absent:
        if store.exists(_blob_id(key)):
            raise SeedRefused(
                f"the manifest records {key} as absent from the source, and the destination "
                "store holds it. The restored stack would not be the state the seed describes."
            )
    _verify_landed(store, manifest.blobs, "store")
    if manifest.tiles:
        if tiles is None:
            raise SeedRefused(
                f"the manifest carries {len(manifest.tiles)} baked tile(s) and no tile store was "
                "given to check them in"
            )
        _verify_landed(tiles, manifest.tiles, "tile store")
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


def _verify_landed(
    store: ContentAddressedStore, recorded: Mapping[str, Mapping[str, Any]], name: str
) -> None:
    """Every recorded object is in ``store`` at its recorded digest and size."""
    for key, value in recorded.items():
        payload = _read_key(store, key)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != value["sha256"] or len(payload) != value["bytes"]:
            raise SeedRefused(
                f"the restored {name}'s {key} hashes to {digest} at {len(payload)} bytes; the "
                f"manifest says {value['sha256']} at {value['bytes']} bytes"
            )
