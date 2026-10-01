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
so a restore initialises its cluster with the same superuser name. Neither file holds a password,
so a backup never carries one: a restore gives the roles new passwords, in its own password file.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from exulanica.db.load_functions import pin_loading_functions
from exulanica.db.local.cluster import Cluster, run, scratch_cluster
from exulanica.db.local.database import (
    LocalDatabase,
    applied_versions,
    server_identity,
    utc_now,
)
from exulanica.db.local.files import sync_directory, write_private
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = [
    "MANIFEST_PROFILE",
    "Backup",
    "check_digest",
    "compare_with_manifest",
    "dump_database",
    "list_backups",
    "manifest_sha256",
    "read_backup",
    "restore_database",
    "restore_database_at",
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


def manifest_sha256(backup: Backup) -> str:
    """The SHA-256 of the manifest file beside the dump: what a backup set binds of it, since a
    restore acts on its roles, memberships and counts."""
    return sha256_of(_manifest_path(backup.dump))


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


@contextlib.contextmanager
def _passwordless(*urls: str) -> Iterator[list[str]]:
    """``urls`` with any password moved into one private password file libpq reads.

    A program's arguments are visible to every process on the host, and a password in
    ``--dbname`` is a password on display for as long as the dump or restore runs. Each URL that
    carries one becomes a connection string naming a temporary 0600 file instead; the file is
    removed when the block ends. URLs without a password are passed through unchanged.
    """
    rewritten: list[str] = []
    folder = Path(tempfile.mkdtemp(prefix="exulanica-pass-"))
    try:
        for index, url in enumerate(urls):
            parameters = conninfo_to_dict(url)
            password = parameters.pop("password", None)
            if password is None:
                rewritten.append(url)
                continue
            # Any host and port: libpq looks a Unix socket up as localhost, and a file of its own
            # for each URL serves only this invocation, so nothing else can match it.
            user = str(parameters.get("user", "*"))
            line = ":".join(
                f.replace("\\", "\\\\").replace(":", "\\:") for f in (user, str(password))
            )
            passfile = folder / f"pgpass-{index}"
            descriptor = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"*:*:*:{line}\n")
            rewritten.append(make_conninfo("", **parameters, passfile=str(passfile)))
        yield rewritten
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _file_name(reason: str) -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    slug = _REASON_CHARACTERS.sub("-", reason.lower()).strip("-")[:_REASON_LENGTH] or "manual"
    return f"{stamp}-{slug}{DUMP_SUFFIX}"


def take_backup(
    database: LocalDatabase, port: int, reason: str, *, service_port: int | None = None
) -> Backup:
    """Dump the database the server on ``port`` holds, with its digest and manifest.

    ``service_port`` is the port the database serves the application on, recorded so a restore
    can serve on it too. It is the cluster's configured port unless the caller states it: an
    adoption backs up before it records the port in the cluster's settings, so it says which.
    """
    return dump_database(
        database.owner_url(port),
        database.backups,
        reason,
        database_name=database.database_name,
        service_port=(
            service_port if service_port is not None else database.cluster.configured_port()
        ),
    )


def dump_database(
    url: str,
    directory: Path,
    reason: str,
    *,
    database_name: str,
    service_port: int,
    exclude_table_data: tuple[str, ...] = (),
) -> Backup:
    """Dump the database ``url`` reaches into ``directory``, with its digest and manifest.

    The connection needs to read every row and every role, which the owner can and so can an
    installation's read-only backup role. The manifest names the database's owner, which owns
    every object the dump creates, whoever took it.

    ``exclude_table_data`` names tables, in any schema, whose definitions are dumped and whose rows
    are not; the manifest records them and counts them as empty, which is what a restore holds.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    dump = directory / _file_name(reason)
    partial = dump.with_name(dump.name + ".partial")
    if dump.exists() or partial.exists():
        raise LocalDatabaseRefused(Refusal.BACKUP_FAILED, f"{dump} already exists")
    with psycopg.connect(url, row_factory=dict_row) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        exported = connection.execute(
            "select pg_export_snapshot() as snapshot, transaction_timestamp() as taken_in"
        ).fetchone()
        assert exported is not None
        try:
            with _passwordless(url) as (dbname,):
                run(
                    "pg_dump",
                    "--format=custom",
                    "--create",
                    "--no-password",
                    f"--snapshot={exported['snapshot']}",
                    *(f"--exclude-table-data=*.{table}" for table in exclude_table_data),
                    f"--file={partial}",
                    f"--dbname={dbname}",
                    refusal=Refusal.BACKUP_FAILED,
                )
            counts = {
                name: 0 if name.rsplit(".", 1)[-1] in exclude_table_data else count
                for name, count in row_counts(connection).items()
            }
            versions = applied_versions(connection)
            # The schema those versions were read from: a deployment may live in a schema other
            # than public, and a restored copy is read without the dumping connection's path.
            schema_row = connection.execute("select current_schema() as name").fetchone()
            assert schema_row is not None
            roles = _roles(connection)
            memberships = _memberships(connection)
            identity = server_identity(connection)
            owner = connection.execute(
                "select pg_get_userbyid(datdba) as owner from pg_database "
                "where datname = current_database()"
            ).fetchone()
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
        "snapshot_taken_in": exported["taken_in"].astimezone(dt.UTC).isoformat(),
        "reason": reason,
        "database": database_name,
        "owner_role": owner["owner"],
        "server": identity,
        "service_port": service_port,
        "migrations": versions,
        "migrations_schema": schema_row["name"],
        "row_counts": counts,
        "excluded_table_data": sorted(exclude_table_data),
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


def _create_roles(
    connection: psycopg.Connection[Any], backup: Backup, *, keep_existing: bool = False
) -> None:
    """The backup's roles and memberships. With ``keep_existing``, a role the server already has is
    left as it is: roles belong to the whole server, and a restore beside a set-aside database on
    the same server finds them, to be reprovisioned afterwards."""
    present = (
        {
            row["rolname"] if isinstance(row, dict) else row[0]
            for row in connection.execute("select rolname from pg_roles").fetchall()
        }
        if keep_existing
        else set()
    )
    for role in backup.manifest["roles"]:
        if role["name"] in present:
            continue
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
        if membership["member"] in present:
            # The server's own memberships stand: re-granting the backup's would bring back one
            # revoked after it, and reprovisioning sets the application roles' own.
            continue
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
    """Load ``backup`` into the running, empty ``cluster``: its roles, its schema, then its rows.

    The cluster must have been initialised with the backup's owner as its bootstrap superuser,
    because the dump names that role as the owner of everything in it.

    The schema and the rows are two runs of ``pg_restore`` with one step between them: every
    function the rows' constraints will run that resolves names through the path is given a path
    of its own (:mod:`exulanica.db.load_functions`), because ``pg_restore`` loads rows under an
    empty path. A dump taken before migration 0106 holds ``privacy_canonical`` without one, and
    without this step its first model right stops the restore. A newer dump has none to pin.
    """
    restore_database_at(
        cluster.url(port, backup.owner_role, "postgres"),
        cluster.url(port, backup.owner_role, backup.database),
        backup,
    )


def restore_database_at(
    maintenance_url: str, restored_url: str, backup: Backup, *, keep_existing_roles: bool = False
) -> None:
    """Load ``backup`` into the empty server ``maintenance_url`` reaches, as its owner role.

    ``restored_url`` names the database the dump creates there. The server's connecting role must
    be the backup's owner and a superuser, because the dump names that role as the owner of
    everything in it and its roles are created before its rows. ``keep_existing_roles`` keeps
    roles the server already has, for a restore onto a server that still holds a set-aside copy.
    """
    try:
        with psycopg.connect(maintenance_url, autocommit=True, row_factory=dict_row) as connection:
            _create_roles(connection, backup, keep_existing=keep_existing_roles)
    except psycopg.Error as error:
        raise LocalDatabaseRefused(
            Refusal.RESTORE_FAILED, f"creating the roles {backup.dump.name} needs failed: {error}"
        ) from error
    with _passwordless(maintenance_url) as (maintenance,):
        run(
            "pg_restore",
            "--create",
            "--exit-on-error",
            "--no-password",
            "--section=pre-data",
            f"--dbname={maintenance}",
            str(backup.dump),
            refusal=Refusal.RESTORE_FAILED,
        )
    try:
        with psycopg.connect(restored_url, autocommit=True) as connection:
            pin_loading_functions(connection)
    except psycopg.Error as error:
        raise LocalDatabaseRefused(
            Refusal.RESTORE_FAILED,
            f"giving the functions {backup.dump.name} loads rows with a path failed: {error}",
        ) from error
    with _passwordless(restored_url) as (restored,):
        run(
            "pg_restore",
            "--exit-on-error",
            "--no-password",
            "--section=data",
            "--section=post-data",
            f"--dbname={restored}",
            str(backup.dump),
            refusal=Refusal.RESTORE_FAILED,
        )


def _versions_in(connection: psycopg.Connection[Any], schema: str | None) -> tuple[str, ...]:
    """The migration versions recorded in ``schema``, the one the dump read them from, or in the
    connection's own schema for a manifest that names none. The connection's path is restored."""
    if schema is None:
        return tuple(applied_versions(connection))
    cursor = connection.cursor(row_factory=dict_row)
    previous = cursor.execute("select current_setting('search_path') as path").fetchone()
    assert previous is not None
    path = sql.SQL("{}, public").format(sql.Identifier(schema)).as_string(connection)
    cursor.execute("select set_config('search_path', %s, false)", (path,))
    try:
        return tuple(applied_versions(connection))
    finally:
        cursor.execute("select set_config('search_path', %s, false)", (previous["path"],))


def compare_with_manifest(connection: psycopg.Connection[Any], backup: Backup) -> dict[str, int]:
    """The restored copy's row counts, when they and its migrations equal the manifest's."""
    counts = row_counts(connection)
    versions = _versions_in(connection, backup.manifest.get("migrations_schema"))
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
        restored = cluster.url(port, backup.owner_role, backup.database)
        with psycopg.connect(restored, autocommit=True, row_factory=dict_row) as connection:
            return compare_with_manifest(connection, backup)
