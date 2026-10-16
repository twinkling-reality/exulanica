"""Bringing a local database's schema up to this code's, only when asked, and never blind.

``exulanica-local-db upgrade`` is the one path to a newer schema: starting the server never
migrates it. Inside one maintenance session (the server on a private port, so this command is its
only client) it:

1.  refuses a database that records a migration this code does not have or has with other bytes;
2.  stops the server, copies its data directory file by file into ``file-backups/`` beside it,
    checks the copy holds as many files and bytes, and starts it again on a private port (unless
    asked not to: a database too large to hold twice);
3.  takes a backup, the way back;
4.  rehearses: restores that backup into a scratch server, checks the copy against the backup's
    manifest, and applies the pending migrations and the role provisioning there, followed by the
    schema check the API runs at boot;
5.  migrates the real database only after a rehearsal of that same fresh backup passed, and
    refuses otherwise (:func:`migrate`);
6.  gives a password to any role the application connects as that provisioning created and the
    password file lacks, when the database asks for passwords;
7.  takes a second backup of the migrated database.

A rehearsal that fails leaves the real database exactly as it was, because nothing but the
scratch copy has been written. A migration that fails after its rehearsal passed leaves the
server stopped rather than serving a database between two versions, and names the backup that
holds it as it was.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TextIO

import psycopg
from psycopg.rows import dict_row

from exulanica.db.cli import provision
from exulanica.db.local.backup import (
    Backup,
    check_digest,
    compare_with_manifest,
    restore_database,
    row_counts,
    take_backup,
)
from exulanica.db.local.cluster import scratch_cluster
from exulanica.db.local.database import (
    APPLICATION_ROLES,
    LocalDatabase,
    MaintenanceSession,
    applied_versions,
    schema_state,
    server_identity,
)
from exulanica.db.local.files import PRIVATE_DIRECTORY_MODE
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.migrate import applied_migrations, verify_schema
from exulanica.db.session import DATABASE_URL_ENV, Database

__all__ = [
    "AFTER_UPGRADE",
    "BEFORE_UPGRADE",
    "FILE_BACKUPS",
    "FileBackup",
    "Rehearsal",
    "copy_stopped_data",
    "migrate",
    "migrate_and_provision",
    "rehearse",
    "require_fresh",
    "upgrade",
]

#: The reasons an upgrade's two backups are named by.
BEFORE_UPGRADE: Final = "before-upgrade"
AFTER_UPGRADE: Final = "after-upgrade"

#: Where an upgrade keeps the file copies of the stopped data it takes, beside ``data/``. Nothing
#: deletes one, as nothing deletes a backup.
FILE_BACKUPS: Final = "file-backups"

#: The parts of a server's identity that must be equal for a backup to be this session's.
_SESSION_IDENTITY: Final = ("system_identifier", "started_at", "port")


@contextlib.contextmanager
def _owner_url_for_provisioning(owner_url: str) -> Iterator[None]:
    """``exulanica-db`` reads its connection from the environment, as a deployment runs it."""
    previous = os.environ.get(DATABASE_URL_ENV)
    os.environ[DATABASE_URL_ENV] = owner_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(DATABASE_URL_ENV, None)
        else:
            os.environ[DATABASE_URL_ENV] = previous


@dataclass(frozen=True, slots=True)
class FileBackup:
    """A file copy of a stopped data directory, and what both held when it was checked."""

    path: Path
    files: int
    size: int

    def describe(self) -> str:
        return f"{self.path}: {self.files} files, {self.size} bytes, as the stopped data holds"


def _files_and_bytes(directory: Path) -> tuple[int, int]:
    """How many files ``directory`` holds below it and their bytes, links counted as themselves."""
    files = size = 0
    for parent, _, names in os.walk(directory):
        for name in names:
            files += 1
            size += (Path(parent) / name).lstat().st_size
    return files, size


def copy_stopped_data(session: MaintenanceSession, reason: str = BEFORE_UPGRADE) -> FileBackup:
    """Stop the session's server, copy its data directory into ``file-backups/``, check the copy
    holds as many files and bytes as the data, and start the server again on a private port, which
    the session then names. The copy is taken with nothing writing the files, so it is the database
    as it stood, beside the dump the upgrade takes next; a copy that fails or differs is refused
    before anything is migrated."""
    database = session.database
    cluster = database.cluster
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = database.root / FILE_BACKUPS / f"{stamp}-{reason}"
    cluster.stop()
    try:
        (database.root / FILE_BACKUPS).mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
        target.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        copy = target / database.data.name
        shutil.copytree(database.data, copy, symlinks=True)
        held, copied = _files_and_bytes(database.data), _files_and_bytes(copy)
    except OSError as error:
        raise LocalDatabaseRefused(
            Refusal.FILE_BACKUP_INCOMPLETE,
            f"copying {database.data} to {target} failed ({error}); nothing was migrated",
        ) from error
    finally:
        port = cluster.start_on_a_free_port()
        with database.connect(port) as connection:
            session.port, session.identity = port, server_identity(connection)
    if copied != held:
        raise LocalDatabaseRefused(
            Refusal.FILE_BACKUP_INCOMPLETE,
            f"{target} holds {copied[0]} files and {copied[1]} bytes; the stopped data held "
            f"{held[0]} and {held[1]}. Nothing was migrated",
        )
    return FileBackup(path=target, files=copied[0], size=copied[1])


def migrate_and_provision(owner_url: str) -> tuple[str, ...]:
    """Run ``exulanica-db`` as the owner, then the schema check the API runs at boot.

    The same principal applies the migrations and provisions the roles, which is what keeps
    default privileges covering every table a migration adds (see :mod:`exulanica.db.cli`).
    Returns the versions this call applied.
    """
    database = Database(url=owner_url)
    with database.unscoped() as connection:
        before = set(applied_migrations(connection))
    with _owner_url_for_provisioning(owner_url):
        provision(io.StringIO())
    verify_schema(database)
    with database.unscoped() as connection:
        after = set(applied_migrations(connection))
    return tuple(sorted(after - before))


@dataclass(frozen=True, slots=True)
class Rehearsal:
    """What applying the pending migrations to a copy of ``backup`` did."""

    backup: Backup
    applied: tuple[str, ...] = ()
    changed_counts: Mapping[str, tuple[int | None, int | None]] = field(default_factory=dict)
    failure: str | None = None

    @property
    def passed(self) -> bool:
        return self.failure is None

    def describe(self) -> str:
        if not self.passed:
            return f"rehearsal on a copy of {self.backup.dump.name} FAILED: {self.failure}"
        changed = (
            ", ".join(
                f"{name} {before} -> {after}"
                for name, (before, after) in sorted(self.changed_counts.items())
            )
            or "none"
        )
        return (
            f"rehearsal on a copy of {self.backup.dump.name}: applied "
            f"{', '.join(self.applied) or 'nothing'}; the boot schema check passed; "
            f"tables whose row count changed: {changed}"
        )


def rehearse(backup: Backup) -> Rehearsal:
    """Apply this code's pending migrations to a scratch copy of ``backup``, never the original.

    The copy is checked against the backup's manifest before anything is applied to it, so a
    rehearsal also proves the way back. Any failure applying the migrations is the rehearsal's
    finding and is returned; a backup that does not restore faithfully is a refusal.
    """
    check_digest(backup)
    with scratch_cluster(owner=backup.owner_role) as (cluster, port):
        restore_database(cluster, port, backup)
        copy_url = cluster.url(port, backup.owner_role, backup.database)
        with psycopg.connect(copy_url, autocommit=True, row_factory=dict_row) as connection:
            before = compare_with_manifest(connection, backup)
        try:
            applied = migrate_and_provision(copy_url)
        except Exception as error:
            return Rehearsal(backup=backup, failure=f"{type(error).__name__}: {error}")
        with psycopg.connect(copy_url, autocommit=True, row_factory=dict_row) as connection:
            after = row_counts(connection)
    changed = {
        name: (before.get(name), after.get(name))
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }
    return Rehearsal(backup=backup, applied=applied, changed_counts=changed)


def require_fresh(session: MaintenanceSession, backup: Backup) -> None:
    """Refuse ``backup`` unless it was taken in ``session`` and nothing has changed since.

    Inside a maintenance session this command is the server's only client, so a backup taken by
    the same server run, on the session's private port, holds what the database holds now.
    """
    taken_by = {key: backup.server.get(key) for key in _SESSION_IDENTITY}
    running = {key: session.identity.get(key) for key in _SESSION_IDENTITY}
    if taken_by != running:
        raise LocalDatabaseRefused(
            Refusal.NO_FRESH_BACKUP,
            f"{backup.dump.name} was taken by the server run started {taken_by['started_at']} "
            f"on port {taken_by['port']}, not by this maintenance session (started "
            f"{running['started_at']} on port {running['port']}). A migration needs a backup "
            "that nothing could have written after.",
        )
    check_digest(backup)
    with session.database.connect(session.port) as connection:
        recorded = tuple(applied_versions(connection))
    if recorded != backup.migrations:
        raise LocalDatabaseRefused(
            Refusal.NO_FRESH_BACKUP,
            f"the database's migrations changed after {backup.dump.name} was taken",
        )


def migrate(session: MaintenanceSession, rehearsal: Rehearsal) -> tuple[tuple[str, ...], Backup]:
    """Migrate the real database after a passing rehearsal of a fresh backup, then back it up."""
    if not rehearsal.passed:
        raise LocalDatabaseRefused(
            Refusal.REHEARSAL_FAILED,
            f"{rehearsal.describe()}. The database was not touched; "
            f"{rehearsal.backup.dump} holds it as it is.",
        )
    require_fresh(session, rehearsal.backup)
    session.leave_stopped = True
    try:
        applied = migrate_and_provision(session.owner_url)
        session.database.give_passwords(session.port, APPLICATION_ROLES)
    except Exception as error:
        raise LocalDatabaseRefused(
            Refusal.MIGRATION_FAILED,
            f"{type(error).__name__}: {error}. The rehearsal passed and the real migration did "
            "not, so the database may be between versions, and the server is left stopped. "
            f"{rehearsal.backup.dump} holds it as it was: restore it into an empty directory "
            "with `exulanica-local-db restore`.",
        ) from error
    after = take_backup(session.database, session.port, AFTER_UPGRADE)
    session.leave_stopped = False
    return applied, after


def upgrade(database: LocalDatabase, stream: TextIO, *, file_backup: bool = True) -> None:
    """Copy the stopped data, back up, rehearse, migrate and back up again, or say the schema is
    already current. ``file_backup`` off skips the copy, for a database too large to hold twice."""
    with database.maintenance() as session:
        with database.connect(session.port) as connection:
            state = schema_state(connection)
        if state.drift:
            raise LocalDatabaseRefused(Refusal.SCHEMA_DRIFT, state.drift)
        if not state.pending:
            print(f"schema: {state.describe()}; nothing to upgrade", file=stream)
            return
        print(f"pending: {', '.join(state.pending)}", file=stream)
        if file_backup:
            copied = copy_stopped_data(session)
            print(f"file backup before upgrade: {copied.describe()}", file=stream)
        before = take_backup(database, session.port, BEFORE_UPGRADE)
        print(f"backup before upgrade: {before.describe()}", file=stream)
        rehearsal = rehearse(before)
        print(rehearsal.describe(), file=stream)
        applied, after = migrate(session, rehearsal)
        print(f"migrated: applied {', '.join(applied)}", file=stream)
        print(f"backup after upgrade: {after.describe()}", file=stream)
