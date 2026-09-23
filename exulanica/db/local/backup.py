"""Backups of a local database, and the proof that one restores.

A backup is three files in the database's ``backups/`` directory, named by the UTC time it was
taken and the reason::

    20260923T190051393667Z-stop.pgdump          pg_dump --format=custom --create
    20260923T190051393667Z-stop.json            the manifest
    20260923T190051393667Z-stop.pgdump.sha256   the digest, in the form `shasum -c` reads

**The manifest describes the dump exactly.** The dump is taken in a snapshot this module exports
from a read-only repeatable-read transaction, and the row counts, the applied migrations and the
roles are read in that same transaction. So a backup taken while the application writes still
has a manifest that matches its dump row for row, and :func:`verify_backup` can require equality
rather than closeness.

**The files appear in an order that never leaves a dump without its manifest.** The dump is
written under a ``.partial`` name and synced, its SHA-256 is computed, the manifest and the digest
file are written, and only then is the dump renamed to its final name.

**Roles are not in a dump.** ``pg_dump`` writes one database and its grants, and the grants name
roles that belong to the whole cluster. The manifest records every role the cluster has beyond
the bootstrap superuser, with its attributes and memberships but never a password, and a restore
creates them before ``pg_restore`` runs. The dump's objects are owned by the bootstrap superuser,
so a restore initialises its cluster with the same superuser name.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exulanica.db.local.cluster import Cluster, run, scratch_cluster, url
from exulanica.db.local.database import (
    LocalDatabase,
    applied_versions,
    server_identity,
    sync_directory,
    utc_now,
    write_private,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = [
    "MANIFEST_PROFILE",
    "Backup",
    "check_digest",
    "compare_with_manifest",
    "list_backups",
    "read_backup",
    "restore_database",
    "row_counts",
    "take_backup",
    "verify_backup",
]

#: The identity and version of a manifest's content.
MANIFEST_PROFILE: Final = "exulanica.local-database-backup/v1"

DUMP_SUFFIX: Final = ".pgdump"
MANIFEST_SUFFIX: Final = ".json"

#: A reason becomes part of a file name, so it is cut to this many of these characters.
_REASON_LENGTH: Final = 40
_REASON_CHARACTERS: Final = re.compile(r"[^a-z0-9-]+")

#: Read in blocks of this size when hashing, so a dump of any size needs one block of memory.
_HASH_BLOCK_BYTES: Final = 1 << 20

#: Each ``pg_roles`` attribute a backup records, and the keyword that restores it on or off.
ROLE_ATTRIBUTES: Final = {
    "rolsuper": ("superuser", "nosuperuser"),
    "rolinherit": ("inherit", "noinherit"),
    "rolcreaterole": ("createrole", "nocreaterole"),
    "rolcreatedb": ("createdb", "nocreatedb"),
    "rolcanlogin": ("login", "nologin"),
    "rolreplication": ("replication", "noreplication"),
    "rolbypassrls": ("bypassrls", "nobypassrls"),
}

#: The bootstrap superuser's object identifier, fixed by PostgreSQL (BOOTSTRAP_SUPERUSERID).
_BOOTSTRAP_ROLE_OID: Final = 10


@dataclass(frozen=True, slots=True)
class Backup:
    """A dump and the manifest that describes it."""

    dump: Path
    manifest: Mapping[str, Any]

    @property
    def sha256(self) -> str:
        return str(self.manifest["sha256"])

    @property
    def owner_role(self) -> str:
        return str(self.manifest["owner_role"])

    @property
    def database(self) -> str:
        return str(self.manifest["database"])

    @property
    def migrations(self) -> tuple[str, ...]:
        return tuple(self.manifest["migrations"])

    @property
    def row_counts(self) -> dict[str, int]:
        return {str(name): int(count) for name, count in self.manifest["row_counts"].items()}

    @property
    def server(self) -> Mapping[str, Any]:
        """The server run the dump was taken from, which may be a maintenance session's."""
        return self.manifest["server"]

    @property
    def service_port(self) -> int:
        """The port the database served the application on, whatever port the dump used."""
        return int(self.manifest["service_port"])

    def describe(self) -> str:
        last = self.migrations[-1] if self.migrations else "none"
        return (
            f"{self.dump} sha256 {self.sha256} ({self.manifest['bytes']} bytes; "
            f"{len(self.row_counts)} tables, {sum(self.row_counts.values())} rows; "
            f"last migration {last})"
        )


def _manifest_path(dump: Path) -> Path:
    return dump.with_suffix(MANIFEST_SUFFIX)


def _digest_path(dump: Path) -> Path:
    return dump.with_name(dump.name + ".sha256")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def row_counts(connection: psycopg.Connection[Any]) -> dict[str, int]:
    """Rows in every table a dump carries data for, keyed ``schema.table``.

    Partitions are counted through their parent, and a table an extension owns is left out,
    because ``pg_dump`` restores it from the extension rather than from the dump. Row security is
    turned off for the count, so a role it would filter gets an error rather than a smaller number.
    """
    connection.execute("set row_security = off")
    tables = connection.execute(
        "select n.nspname as schema_name, c.relname as table_name "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where c.relkind in ('r', 'p') and not c.relispartition "
        "and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname !~ '^pg_' "
        "and not exists (select 1 from pg_depend d where d.classid = 'pg_class'::regclass "
        "and d.objid = c.oid and d.deptype = 'e') "
        "order by 1, 2"
    ).fetchall()
    counts: dict[str, int] = {}
    for table in tables:
        counted = connection.execute(
            sql.SQL("select count(*) as rows from {}.{}").format(
                sql.Identifier(table["schema_name"]), sql.Identifier(table["table_name"])
            )
        ).fetchone()
        assert counted is not None
        counts[f"{table['schema_name']}.{table['table_name']}"] = int(counted["rows"])
    return counts


def _roles(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    columns = sql.SQL(", ").join(sql.Identifier(name) for name in ROLE_ATTRIBUTES)
    rows = connection.execute(
        sql.SQL(
            "select rolname, {}, rolconnlimit from pg_roles "
            "where rolname !~ '^pg_' and oid <> {} order by rolname"
        ).format(columns, sql.Literal(_BOOTSTRAP_ROLE_OID))
    ).fetchall()
    return [
        {
            "name": row["rolname"],
            **{name: bool(row[name]) for name in ROLE_ATTRIBUTES},
            "connection_limit": int(row["rolconnlimit"]),
        }
        for row in rows
    ]


def _memberships(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    rows = connection.execute(
        "select granted.rolname as role_name, member.rolname as member_name, "
        "m.admin_option, m.inherit_option, m.set_option "
        "from pg_auth_members m "
        "join pg_roles granted on granted.oid = m.roleid "
        "join pg_roles member on member.oid = m.member "
        "where member.rolname !~ '^pg_' and member.oid <> %s "
        "order by 1, 2",
        (_BOOTSTRAP_ROLE_OID,),
    ).fetchall()
    return [
        {
            "role": row["role_name"],
            "member": row["member_name"],
            "admin": bool(row["admin_option"]),
            "inherit": bool(row["inherit_option"]),
            "set": bool(row["set_option"]),
        }
        for row in rows
    ]


def _file_name(reason: str) -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    slug = _REASON_CHARACTERS.sub("-", reason.lower()).strip("-")[:_REASON_LENGTH] or "manual"
    return f"{stamp}-{slug}{DUMP_SUFFIX}"


def take_backup(database: LocalDatabase, port: int, reason: str) -> Backup:
    """Dump the database the server on ``port`` holds, with its digest and manifest."""
    database.backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    dump = database.backups / _file_name(reason)
    partial = dump.with_name(dump.name + ".partial")
    if dump.exists() or partial.exists():
        raise LocalDatabaseRefused(Refusal.BACKUP_FAILED, f"{dump} already exists")
    owner_url = database.owner_url(port)
    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        exported = connection.execute("select pg_export_snapshot() as snapshot").fetchone()
        assert exported is not None
        try:
            run(
                "pg_dump",
                "--format=custom",
                "--create",
                "--no-password",
                f"--snapshot={exported['snapshot']}",
                f"--file={partial}",
                f"--dbname={owner_url}",
                refusal=Refusal.BACKUP_FAILED,
            )
            counts = row_counts(connection)
            versions = applied_versions(connection)
            roles = _roles(connection)
            memberships = _memberships(connection)
            identity = server_identity(connection)
            owner = connection.execute("select current_user as owner").fetchone()
            assert owner is not None
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        finally:
            connection.rollback()
    os.chmod(partial, 0o600)
    with partial.open("rb") as handle:
        os.fsync(handle.fileno())
    digest = sha256_of(partial)
    manifest = {
        "profile": MANIFEST_PROFILE,
        "dump": dump.name,
        "sha256": digest,
        "bytes": partial.stat().st_size,
        "taken_at": utc_now(),
        "reason": reason,
        "database": database.database_name,
        "owner_role": owner["owner"],
        "server": identity,
        "service_port": database.cluster.configured_port(),
        "migrations": versions,
        "row_counts": counts,
        "roles": roles,
        "memberships": memberships,
    }
    write_private(_manifest_path(dump), json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    write_private(_digest_path(dump), f"{digest}  {dump.name}\n")
    partial.replace(dump)
    sync_directory(dump.parent)
    return Backup(dump=dump, manifest=manifest)


def read_backup(dump: Path) -> Backup:
    """The backup whose dump is ``dump``, or a refusal naming what is missing or wrong."""
    dump = dump.expanduser().resolve()
    manifest_path = _manifest_path(dump)
    if not dump.is_file():
        raise LocalDatabaseRefused(Refusal.BACKUP_UNREADABLE, f"{dump} does not exist")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LocalDatabaseRefused(
            Refusal.BACKUP_UNREADABLE,
            f"{dump} has no readable manifest at {manifest_path}: {error}. Without one there is "
            "no digest to check it against and no row counts to prove a restore by.",
        ) from error
    if not isinstance(manifest, dict) or manifest.get("profile") != MANIFEST_PROFILE:
        raise LocalDatabaseRefused(
            Refusal.BACKUP_UNREADABLE, f"{manifest_path} is not a {MANIFEST_PROFILE} manifest"
        )
    if manifest.get("dump") != dump.name:
        raise LocalDatabaseRefused(
            Refusal.BACKUP_UNREADABLE,
            f"{manifest_path} describes {manifest.get('dump')}, not {dump.name}",
        )
    return Backup(dump=dump, manifest=manifest)


def list_backups(directory: Path) -> list[Backup]:
    """Every readable backup in ``directory``, oldest first; the names sort by time taken."""
    if not directory.is_dir():
        return []
    found = []
    for dump in sorted(directory.glob(f"*{DUMP_SUFFIX}")):
        try:
            found.append(read_backup(dump))
        except LocalDatabaseRefused:
            continue
    return found


def check_digest(backup: Backup) -> None:
    actual = sha256_of(backup.dump)
    if actual != backup.sha256:
        raise LocalDatabaseRefused(
            Refusal.DIGEST_MISMATCH,
            f"{backup.dump} hashes to {actual}, and its manifest recorded {backup.sha256}; the "
            "file changed after it was written",
        )


def _create_roles(connection: psycopg.Connection[Any], backup: Backup) -> None:
    for role in backup.manifest["roles"]:
        keywords = [
            sql.SQL(on if role[name] else off) for name, (on, off) in ROLE_ATTRIBUTES.items()
        ]
        connection.execute(
            sql.SQL("create role {} with {} connection limit {}").format(
                sql.Identifier(role["name"]),
                sql.SQL(" ").join(keywords),
                sql.Literal(role["connection_limit"]),
            )
        )
    for membership in backup.manifest["memberships"]:
        connection.execute(
            sql.SQL("grant {} to {} with admin {}, inherit {}, set {}").format(
                sql.Identifier(membership["role"]),
                sql.Identifier(membership["member"]),
                sql.Literal(membership["admin"]),
                sql.Literal(membership["inherit"]),
                sql.Literal(membership["set"]),
            )
        )


def restore_database(cluster: Cluster, port: int, backup: Backup) -> None:
    """Load ``backup`` into the running, empty ``cluster``: its roles, then its database.

    The cluster must have been initialised with the backup's owner as its bootstrap superuser,
    because the dump names that role as the owner of everything in it.
    """
    maintenance_url = url(port, backup.owner_role, "postgres")
    try:
        with psycopg.connect(maintenance_url, autocommit=True, row_factory=dict_row) as connection:
            _create_roles(connection, backup)
    except psycopg.Error as error:
        raise LocalDatabaseRefused(
            Refusal.RESTORE_FAILED, f"creating the roles {backup.dump.name} needs failed: {error}"
        ) from error
    run(
        "pg_restore",
        "--create",
        "--exit-on-error",
        "--no-password",
        f"--dbname={maintenance_url}",
        str(backup.dump),
        refusal=Refusal.RESTORE_FAILED,
    )


def compare_with_manifest(connection: psycopg.Connection[Any], backup: Backup) -> dict[str, int]:
    """The restored copy's row counts, when they and its migrations equal the manifest's."""
    counts = row_counts(connection)
    versions = tuple(applied_versions(connection))
    expected = backup.row_counts
    names = sorted(set(counts) | set(expected))
    differ = [name for name in names if counts.get(name) != expected.get(name)]
    problems = [
        f"{name}: manifest {expected.get(name, 'absent')}, restored {counts.get(name, 'absent')}"
        for name in differ
    ]
    if versions != backup.migrations:
        problems.append(
            f"migrations: manifest has {len(backup.migrations)}, restored copy has {len(versions)}"
        )
    if problems:
        raise LocalDatabaseRefused(
            Refusal.ROW_COUNTS_DIFFER,
            f"a restore of {backup.dump.name} does not match its manifest: " + "; ".join(problems),
        )
    return counts


def verify_backup(backup: Backup) -> dict[str, int]:
    """Prove ``backup`` restores: its digest, then a scratch restore compared with its manifest."""
    check_digest(backup)
    with scratch_cluster(owner=backup.owner_role) as (cluster, port):
        restore_database(cluster, port, backup)
        restored = url(port, backup.owner_role, backup.database)
        with psycopg.connect(restored, autocommit=True, row_factory=dict_row) as connection:
            return compare_with_manifest(connection, backup)
