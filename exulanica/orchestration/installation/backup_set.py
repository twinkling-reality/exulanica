"""A backup set: one database dump, the stored bytes it needs, and the withdrawals that postdate it.

``exulanica.installation-backup/v1`` is written in an order that never leaves a usable-looking set
incomplete, each step verified before the next:

1. **The database**, dumped in one exported snapshot by
   :func:`exulanica.db.local.backup.dump_database` as the read-only backup role, after refusing
   any table that role cannot read.
2. **The stored bytes**, copied key for key into the backup store: every object in every
   namespace, each re-derived from its bytes as it is written, so a damaged source is refused
   rather than copied. The store is append-only, so a later set copies only what is new, and the
   set records the sorted list of keys it holds.
3. **A withdrawal export** taken after the dump's snapshot, so it holds every tombstone and
   withdrawal the dump holds and more: an export older than its backup would be refused by the
   replay anyway, and this refuses it first.
4. **The manifest**, last, digest-bound. A directory without it is not a backup set.

Nothing here restores: :mod:`exulanica.orchestration.installation.recovery` does, and
:func:`verify_backup_set` proves a set restores by loading it into a scratch server.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json
from exulanica.db.local.backup import (
    Backup,
    check_digest,
    dump_database,
    manifest_sha256,
    read_backup,
    verify_backup,
)
from exulanica.db.local.files import write_private
from exulanica.db.roles import BACKUP_ROLE, backup_role_gaps
from exulanica.db.session import Database
from exulanica.deletion.restore import export_withdrawals
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore

__all__ = [
    "BACKUP_SET_PROFILE",
    "EPHEMERAL_TABLES",
    "BackupSet",
    "BackupSetRefused",
    "Namespace",
    "check_bindings",
    "read_backup_set",
    "take_backup_set",
    "verify_backup_set",
]

BACKUP_SET_PROFILE: Final = "exulanica.installation-backup/v1"
#: Sign-in state a backup set carries the definition of and never the rows: pending logins hold a
#: plaintext nonce and verifier, and browser sessions a plaintext CSRF token (migration 0058).
#: Restoring either is useless, so a restored installation asks everyone to sign in again.
EPHEMERAL_TABLES: Final = ("account_login_attempt", "account_browser_session")
_MANIFEST: Final = "backup-set.json"
_KEYS: Final = "keys.txt"


class BackupSetRefused(RuntimeError):
    """A backup set that was not made, or does not prove itself, and why, by name."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Namespace:
    """One namespace of stored bytes: its name in the set, where it is, and where it is copied."""

    name: str
    source: ContentAddressedStore
    target: ContentAddressedStore


@dataclass(frozen=True, slots=True)
class BackupSet:
    directory: Path
    manifest: Mapping[str, Any]

    @property
    def sha256(self) -> str:
        return str(self.manifest["record_sha256"])

    @property
    def database(self) -> Backup:
        return read_backup(self.directory / self.manifest["record"]["database"]["dump"])


def _copy(namespace: Namespace) -> list[str]:
    """Copy every object ``namespace`` holds that its target lacks; return every key it holds."""
    keys = []
    for blob_id in namespace.source.iter_blob_ids():
        if not namespace.target.exists(blob_id):
            with namespace.source.open(blob_id) as stream:
                written = namespace.target.put_stream(stream).blob_id
            if written != blob_id:
                raise BackupSetRefused(
                    "store_object_corrupt",
                    f"{namespace.name}: an object's bytes do not hash to its key",
                )
        keys.append(f"{namespace.name}/{blob_id.hex}")
    return keys


def take_backup_set(
    *,
    backup_url: str,
    directory: Path,
    namespaces: Iterable[Namespace],
    custody: Path,
    restore_state_path: Path | None,
    backup_domains: Iterable[Path],
    identity: Mapping[str, Any],
    service_port: int = 5432,
    role: str = BACKUP_ROLE,
) -> BackupSet:
    """Take one verified-in-order backup set into a fresh subdirectory of ``directory``.

    ``backup_url`` reaches the database as the backup role; ``namespaces`` pair each store with its
    backup copy; ``custody`` receives the withdrawal export and must lie outside ``backup_domains``,
    which name the database's and the content store's backup locations. ``identity`` is what the
    installation states about itself (profile, image digests, code revision), recorded verbatim.
    """
    database = Database(backup_url)
    with database.unscoped() as connection:
        gaps = backup_role_gaps(connection, role)
    if gaps:
        raise BackupSetRefused(
            "backup_role_incomplete",
            f"{role} cannot read, or could write, {', '.join(gaps)}; run exulanica-db",
        )
    started = dt.datetime.now(dt.UTC)
    target = directory / started.strftime("%Y%m%dT%H%M%S%fZ")
    target.mkdir(mode=0o700, parents=True)
    try:
        dump = dump_database(
            backup_url,
            target,
            "backup-set",
            database_name=_database_name(backup_url),
            service_port=service_port,
            exclude_table_data=EPHEMERAL_TABLES,
        )
        keys: list[str] = []
        for namespace in namespaces:
            keys.extend(_copy(namespace))
        keys.sort()
        key_text = "".join(f"{key}\n" for key in keys)
        write_private(target / _KEYS, key_text)
        export, export_sha256 = export_withdrawals(
            database,
            custody,
            restore_state_path=restore_state_path,
            backup_domains=[*backup_domains, directory],
        )
        covered = json.loads(export.read_bytes())["record"]["covered_through"]
        taken_in = dump.manifest["snapshot_taken_in"]
        if dt.datetime.fromisoformat(covered) < dt.datetime.fromisoformat(taken_in):
            raise BackupSetRefused(
                "export_older_than_dump", "the withdrawal export does not cover the dump's snapshot"
            )
        record = {
            "profile": BACKUP_SET_PROFILE,
            "started_at": started.isoformat(),
            "identity": dict(identity),
            "database": {
                "dump": dump.dump.name,
                "sha256": dump.sha256,
                "manifest_sha256": manifest_sha256(dump),
                "snapshot_taken_in": taken_in,
                "migrations": list(dump.migrations),
                "tables": len(dump.row_counts),
                "rows": sum(dump.row_counts.values()),
            },
            "store": {
                "keys": len(keys),
                "keys_sha256": hashlib.sha256(key_text.encode()).hexdigest(),
            },
            "withdrawal_export": {
                "file": export.name,
                "sha256": export_sha256,
                "covered_through": covered,
            },
        }
        envelope = {
            "profile": "exulanica.digest-bound-record/v1",
            "record": record,
            "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
        }
        write_private(target / _MANIFEST, json.dumps(envelope, indent=1, sort_keys=True) + "\n")

    except BaseException:
        # A set without its manifest is not a set; leave nothing that looks like one.
        shutil.rmtree(target, ignore_errors=True)
        raise
    return BackupSet(directory=target, manifest=envelope)


def _database_name(url: str) -> str:
    with psycopg.connect(url) as connection:
        row = connection.execute("select current_database()").fetchone()
    assert row is not None
    return str(row[0])


def read_backup_set(directory: Path) -> BackupSet:
    """A backup set whose manifest is present and whose digest matches, or a refusal."""
    try:
        envelope = json.loads((directory / _MANIFEST).read_bytes())
    except (OSError, ValueError) as exc:
        raise BackupSetRefused("backup_set_incomplete", f"{directory} has no manifest") from exc
    record = envelope.get("record") if isinstance(envelope, dict) else None
    if (
        not isinstance(record, dict)
        or record.get("profile") != BACKUP_SET_PROFILE
        or envelope.get("record_sha256") != hashlib.sha256(canonical_json(record)).hexdigest()
    ):
        raise BackupSetRefused("backup_set_invalid", f"{directory} manifest does not verify")
    return BackupSet(directory=directory, manifest=envelope)


def check_bindings(backup_set: BackupSet) -> None:
    """The set's record binds its dump and the dump's manifest: refuse a set whose dump or manifest
    is another than the one it was taken with."""
    database = backup_set.manifest["record"]["database"]
    dump = backup_set.database
    if database.get("sha256") != dump.sha256 or database.get("manifest_sha256") != manifest_sha256(
        dump
    ):
        raise BackupSetRefused(
            "backup_set_invalid", "the dump or its manifest is not the one the set records"
        )
    check_digest(dump)


def verify_backup_set(
    directory: Path,
    stores: Mapping[str, ContentAddressedStore] | Callable[[str], ContentAddressedStore | None],
    *,
    erased: Collection[str] = (),
) -> dict[str, Any]:
    """Prove a set restores: its dump into a scratch server, its keys and every object's digest.

    ``stores`` are the backup copies by namespace name. Every key the set lists must be present
    and its bytes must hash to it, except those whose digest is in ``erased``: bytes a completed,
    tombstone-authorised purge destroyed in the backup copy too, which a restore's replay would
    destroy again. The dump must restore to exactly its manifest's row counts.
    """
    backup_set = read_backup_set(directory)
    record = backup_set.manifest["record"]
    key_text = (directory / _KEYS).read_text()
    if hashlib.sha256(key_text.encode()).hexdigest() != record["store"]["keys_sha256"]:
        raise BackupSetRefused("backup_set_invalid", "the key list does not match its manifest")
    check_bindings(backup_set)
    checked = withheld = 0
    for line in key_text.splitlines():
        name, _, hexdigest = line.rpartition("/")
        store = stores.get(name) if isinstance(stores, Mapping) else stores(name)
        if store is None:
            raise BackupSetRefused("backup_store_missing", f"no backup store for {name}")
        blob_id = BlobId.from_hex(hexdigest)
        if hexdigest in erased and not store.exists(blob_id):
            withheld += 1
            continue
        digest = hashlib.sha256()
        try:
            with store.open(blob_id) as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
        except (FileNotFoundError, KeyError) as exc:
            raise BackupSetRefused("backup_object_missing", f"{name}/{hexdigest}") from exc
        if digest.hexdigest() != hexdigest:
            raise BackupSetRefused("backup_object_corrupt", f"{name}/{hexdigest}")
        checked += 1
    counts = verify_backup(backup_set.database)
    return {
        "objects": checked,
        "erased_objects": withheld,
        "tables": len(counts),
        "rows": sum(counts.values()),
    }
