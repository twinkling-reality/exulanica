"""Bringing a local database's schema up to this code's, only when asked, and never blind.

``exulanica-local-db upgrade`` is the one path to a newer schema: starting the server never
migrates it. Inside one maintenance session (the server on a private port, so this command is its
only client) it:

1.  refuses a database that records a migration this code does not have or has with other bytes;
2.  takes a backup, the way back;
3.  rehearses: restores that backup into a scratch server, checks the copy against the backup's
    manifest, and applies the pending migrations and the role provisioning there, followed by the
    schema check the API runs at boot;
4.  migrates the real database only after a rehearsal of that same fresh backup passed, and
    refuses otherwise (:func:`migrate`);
5.  takes a second backup of the migrated database.

A rehearsal that fails leaves the real database exactly as it was, because nothing but the
scratch copy has been written. A migration that fails after its rehearsal passed leaves the
server stopped rather than serving a database between two versions, and names the backup that
holds it as it was.
"""

from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
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
from exulanica.db.local.cluster import scratch_cluster, url
from exulanica.db.local.database import (
    LocalDatabase,
    MaintenanceSession,
    applied_versions,
    schema_state,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.migrate import applied_migrations, verify_schema
from exulanica.db.session import DATABASE_URL_ENV, Database

__all__ = [
    "AFTER_UPGRADE",
    "BEFORE_UPGRADE",
    "Rehearsal",
    "migrate",
    "migrate_and_provision",
    "rehearse",
    "require_fresh",
    "upgrade",
]

#: The reasons an upgrade's two backups are named by.
BEFORE_UPGRADE: Final = "before-upgrade"
AFTER_UPGRADE: Final = "after-upgrade"

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
        copy_url = url(port, backup.owner_role, backup.database)
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


def upgrade(database: LocalDatabase, stream: TextIO) -> None:
    """Back up, rehearse, migrate and back up again, or say the schema is already current."""
    with database.maintenance() as session:
        with database.connect(session.port) as connection:
            state = schema_state(connection)
        if state.drift:
            raise LocalDatabaseRefused(Refusal.SCHEMA_DRIFT, state.drift)
        if not state.pending:
            print(f"schema: {state.describe()}; nothing to upgrade", file=stream)
            return
        print(f"pending: {', '.join(state.pending)}", file=stream)
        before = take_backup(database, session.port, BEFORE_UPGRADE)
        print(f"backup before upgrade: {before.describe()}", file=stream)
        rehearsal = rehearse(before)
        print(rehearsal.describe(), file=stream)
        applied, after = migrate(session, rehearsal)
        print(f"migrated: applied {', '.join(applied)}", file=stream)
        print(f"backup after upgrade: {after.describe()}", file=stream)
