"""One local database directory: its cluster, its backups and the marker that names it.

The directory a person states holds everything, and nothing outside it is written::

    <directory>/
      data/                               the PostgreSQL data directory
        exulanica-local-database.json     the marker (LOCAL_DATABASE_MARKER)
      backups/                            one .pgdump, .json and .pgdump.sha256 per backup
      passwords.pgpass                    each role's password (PASSWORD_FILE_NAME), mode 0600
      server.log

The marker lives inside the data directory rather than beside it so that it travels with the
data: a link or a copy of ``data/`` alone still carries it, and ``scripts/test_postgres.py``
still refuses it. PostgreSQL ignores a file it does not know in that directory.

The marker states how the server admits connections (:class:`Authentication`); a marker of the
first profile, which did not say, was only ever written for a cluster that trusts them. The
passwords stay outside ``data/`` and outside every backup: a copy of the data or a dump carries
no password, and a restore gives the roles new ones (:mod:`~exulanica.db.local.passwords`).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.account_roles import ACCOUNT_ROLE
from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV
from exulanica.db.local.cluster import Cluster, binaries
from exulanica.db.local.files import PRIVATE_DIRECTORY_MODE, write_private
from exulanica.db.local.locations import (
    LOCAL_DATABASE_MARKER,
    refuse_existing_data,
    refuse_location,
)
from exulanica.db.local.passwords import (
    PASSWORD_FILE_NAME,
    Authentication,
    give_password,
    new_password,
    read_passwords,
    refuse_exposed,
    write_passwords,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.migrate import applied_migrations
from exulanica.db.roles import EXECUTOR_ROLE, PURGE_ROLE, RUNTIME_ROLE
from exulanica.db.session import DATABASE_URL_ENV
from exulanica.env import env_name
from exulanica.migrations import migrations, verify_applied

__all__ = [
    "APPLICATION_ROLES",
    "CONNECTIONS",
    "DATABASE_NAME",
    "MARKER_PROFILE",
    "LocalDatabase",
    "MaintenanceSession",
    "SchemaState",
    "applied_versions",
    "schema_state",
    "server_identity",
    "utc_now",
]

#: The identity and version of the marker's content. The second profile states the cluster's
#: authentication; the first, which a cluster made or adopted before it may still carry, did not,
#: and every such cluster trusts its connections.
MARKER_PROFILE: Final = "exulanica.local-database/v2"
_FIRST_MARKER_PROFILE: Final = "exulanica.local-database/v1"
_READABLE_MARKER_PROFILES: Final = (MARKER_PROFILE, _FIRST_MARKER_PROFILE)

#: The database a new local cluster holds the schema in.
DATABASE_NAME: Final = "exulanica"

#: The connections the application reads, and the provisioned role each is made as. The two
#: names read above this package are restated here; ``tests/test_local_database.py`` holds them
#: equal to ``exulanica.api.services`` and ``exulanica.deletion.cli``.
CONNECTIONS: Final = (
    (DATABASE_URL_ENV, RUNTIME_ROLE),
    (env_name("READONLY_DATABASE_URL"), EXECUTOR_ROLE),
    (env_name("PURGE_DATABASE_URL"), PURGE_ROLE),
    (ACCOUNT_DATABASE_URL_ENV, ACCOUNT_ROLE),
)

#: The roles the application logs in as, each of which a password-protected cluster gives a
#: password beside the bootstrap superuser's.
APPLICATION_ROLES: Final = tuple(role for _, role in CONNECTIONS)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def applied_versions(connection: psycopg.Connection[Any]) -> list[str]:
    """Every migration version the database records, in order; empty before migration 0001."""
    return sorted(applied_migrations(connection))


def server_identity(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    """Which server run this connection reached: its cluster, its start time and its port.

    Two readings are the same server run only when all three agree, which is how a backup is
    shown to come from the maintenance session a migration runs in.
    """
    row = connection.execute(
        "select (select system_identifier from pg_control_system())::text as system_identifier, "
        "to_char(pg_postmaster_start_time() at time zone 'UTC', "
        '\'YYYY-MM-DD"T"HH24:MI:SS.US"Z"\') as started_at, '
        "current_setting('port')::integer as port, "
        "current_setting('server_version') as version"
    ).fetchone()
    assert row is not None
    return dict(row)


@dataclass(frozen=True, slots=True)
class SchemaState:
    """How a database's recorded migrations compare with this code's."""

    applied: tuple[str, ...]
    pending: tuple[str, ...]
    drift: str | None

    def describe(self) -> str:
        last = self.applied[-1] if self.applied else "none"
        if self.drift:
            return f"{len(self.applied)} migrations applied, last {last}; DRIFT: {self.drift}"
        waiting = (
            f"{len(self.pending)} pending ({', '.join(self.pending)}); "
            "run `exulanica-local-db upgrade` to apply them"
            if self.pending
            else "none pending"
        )
        return f"{len(self.applied)} migrations applied, last {last}; {waiting}"


def schema_state(connection: psycopg.Connection[Any]) -> SchemaState:
    recorded = applied_migrations(connection)
    drift = None
    try:
        verify_applied(recorded)
    except RuntimeError as error:
        drift = " ".join(str(error).split())
    pending = tuple(m.version for m in migrations() if m.version not in recorded)
    return SchemaState(applied=tuple(sorted(recorded)), pending=pending, drift=drift)


@dataclass(slots=True)
class MaintenanceSession:
    """The server running on a port nothing else is configured to use.

    ``leave_stopped`` is set while the database is between two states, so that a session which
    ends there does not put the server back in front of the application.
    """

    database: LocalDatabase
    port: int
    identity: Mapping[str, Any]
    leave_stopped: bool = False

    @property
    def owner_url(self) -> str:
        return self.database.owner_url(self.port)


@dataclass(frozen=True, slots=True)
class LocalDatabase:
    """The local database whose files are all under ``root``."""

    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def marker(self) -> Path:
        return self.data / LOCAL_DATABASE_MARKER

    @property
    def passfile(self) -> Path:
        return self.root / PASSWORD_FILE_NAME

    @property
    def cluster(self) -> Cluster:
        """The cluster, with its password file whenever one exists.

        A URL names the file whenever it exists, whatever the marker says: a server that trusts
        its connections ignores a password, so this reaches a cluster in either state, including
        one whose change to passwords stopped part way.
        """
        return Cluster(
            data=self.data,
            log=self.root / "server.log",
            passfile=self.passfile if self.passfile.is_file() else None,
        )

    @classmethod
    def open(cls, directory: Path) -> LocalDatabase:
        """The local database in ``directory``, or a refusal if this command did not make it, or
        if the passwords it asks for are missing or exposed."""
        database = cls(directory.expanduser().resolve())
        authentication = database.authentication
        if database.passfile.exists():
            refuse_exposed(database.passfile)
        elif authentication is Authentication.SCRAM:
            raise LocalDatabaseRefused(
                Refusal.PASSWORD_FILE_MISSING,
                f"{database.root} asks every connection for a password and "
                f"{database.passfile} is gone, so nothing can connect. Restore it from wherever "
                "it was copied to; otherwise restore a backup into a new directory, which gives "
                "every role a new password.",
            )
        return database

    @classmethod
    def create(
        cls,
        directory: Path,
        *,
        owner: str,
        database_name: str,
        created_by: str,
        authentication: Authentication,
        restored_from: Mapping[str, Any] | None = None,
    ) -> LocalDatabase:
        """Initialise a durable, empty cluster in ``directory`` and mark it as a local database.

        The location is refused here as well as by the caller, immediately before ``initdb``,
        so no path reaches a new cluster without passing both checks. A cluster that asks for
        passwords has its password file, holding the bootstrap superuser's, before ``initdb``
        runs; :meth:`give_passwords` adds the other roles' once they exist.
        """
        root = refuse_location(directory)
        refuse_existing_data(root)
        root.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        os.chmod(root, PRIVATE_DIRECTORY_MODE)
        database = cls(root)
        if authentication is Authentication.SCRAM:
            write_passwords(database.passfile, {owner: new_password()})
        database.cluster.initialise(owner=owner, durable=True, authentication=authentication)
        write_private(
            database.marker,
            json.dumps(
                {
                    "profile": MARKER_PROFILE,
                    "created_at": utc_now(),
                    "created_by": created_by,
                    "authentication": authentication.value,
                    "owner_role": owner,
                    "database": database_name,
                    "postgres": binaries().version,
                    "restored_from": dict(restored_from) if restored_from else None,
                },
                indent=1,
                sort_keys=True,
            )
            + "\n",
        )
        database.backups.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        return database

    def read_marker(self) -> dict[str, Any]:
        if not self.marker.is_file():
            raise LocalDatabaseRefused(
                Refusal.NOT_A_LOCAL_DATABASE,
                f"{self.root} holds no data directory exulanica-local-db created: there is no "
                f"{self.marker}. Create one with `exulanica-local-db init`, restore a backup "
                "into an empty directory with `exulanica-local-db restore`, or take on an "
                "existing cluster with `exulanica-local-db adopt`.",
            )
        try:
            marker = json.loads(self.marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise LocalDatabaseRefused(
                Refusal.NOT_A_LOCAL_DATABASE, f"{self.marker} cannot be read: {error}"
            ) from error
        if not isinstance(marker, dict) or marker.get("profile") not in _READABLE_MARKER_PROFILES:
            raise LocalDatabaseRefused(
                Refusal.NOT_A_LOCAL_DATABASE,
                f"{self.marker} is not a {' or '.join(_READABLE_MARKER_PROFILES)} marker",
            )
        return marker

    @property
    def owner(self) -> str:
        return str(self.read_marker()["owner_role"])

    @property
    def database_name(self) -> str:
        return str(self.read_marker()["database"])

    @property
    def authentication(self) -> Authentication:
        """How the server admits connections, as the marker states it."""
        marker = self.read_marker()
        if marker["profile"] == _FIRST_MARKER_PROFILE:
            return Authentication.TRUST
        try:
            return Authentication(marker["authentication"])
        except (KeyError, ValueError) as error:
            raise LocalDatabaseRefused(
                Refusal.NOT_A_LOCAL_DATABASE,
                f"{self.marker} names no authentication this command knows: "
                f"{marker.get('authentication')!r}; it knows "
                f"{', '.join(method.value for method in Authentication)}",
            ) from error

    def owner_url(self, port: int) -> str:
        return self.cluster.url(port, self.owner, self.database_name)

    def role_url(self, port: int, role: str) -> str:
        return self.cluster.url(port, role, self.database_name)

    def give_passwords(self, port: int, roles: Iterable[str]) -> tuple[str, ...]:
        """Give each of ``roles`` the password file lacks a password: the file first, then the role.

        Only a cluster that asks for passwords has any to give. Written in that order, a role
        never holds a password the file does not.
        """
        if self.authentication is not Authentication.SCRAM:
            return ()
        held = read_passwords(self.passfile)
        missing = tuple(role for role in roles if role not in held)
        if not missing:
            return ()
        write_passwords(self.passfile, {**held, **{role: new_password() for role in missing}})
        written = read_passwords(self.passfile)
        with self.connect(port) as connection:
            for role in missing:
                give_password(connection, role, written[role])
        return missing

    def connect(self, port: int) -> psycopg.Connection[Any]:
        """An owner connection in autocommit, with dictionary rows as everywhere in the spine."""
        return psycopg.connect(self.owner_url(port), autocommit=True, row_factory=dict_row)

    def other_sessions(self, port: int) -> list[str]:
        """Every other client connected to this database, as ``role (application)``."""
        with self.connect(port) as connection:
            rows = connection.execute(
                "select usename, application_name from pg_stat_activity "
                "where datname = current_database() and pid <> pg_backend_pid() "
                "and backend_type = 'client backend' order by pid"
            ).fetchall()
        return [
            f"{row['usename']} ({row['application_name'] or 'no application name'})" for row in rows
        ]

    @contextlib.contextmanager
    def maintenance(self) -> Iterator[MaintenanceSession]:
        """Run the server on a private port for the length of one operation.

        A server running for the application is stopped first, and only when no other client
        is connected to it, then started again when the session ends unless the session left
        the database between states. Nothing configured anywhere names the private port, so for
        the whole session this command is the only client, and a backup taken inside it holds
        exactly what the database holds until something inside the session changes it.
        """
        cluster = self.cluster
        was_running = cluster.running()
        if was_running:
            others = self.other_sessions(cluster.running_port())
            if others:
                raise LocalDatabaseRefused(
                    Refusal.IN_USE,
                    f"{len(others)} other connections to {self.database_name}: "
                    f"{', '.join(others)}. Stop the API and the workers first; this step "
                    "restarts the server and must be the only client while it runs.",
                )
            cluster.stop()
        try:
            port = cluster.start_on_a_free_port()
        except BaseException:
            if was_running:
                cluster.start()
            raise
        session: MaintenanceSession | None = None
        try:
            with self.connect(port) as connection:
                session = MaintenanceSession(
                    database=self, port=port, identity=server_identity(connection)
                )
            yield session
        finally:
            cluster.stop()
            if was_running and not (session is not None and session.leave_stopped):
                cluster.start()
