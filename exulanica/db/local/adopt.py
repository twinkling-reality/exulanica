"""Adopting a durable PostgreSQL cluster that ``exulanica-local-db`` did not create.

``exulanica-local-db adopt --directory <dir>`` brings a cluster that already exists under the
command, so that ``start``, ``stop``, ``status``, ``backup``, ``verify`` and ``upgrade`` work on it
as on one ``init`` made. The command recognises its own clusters by the marker inside the data
directory (:mod:`~exulanica.db.local.locations`), and adopting is writing that marker, so it is
written last, once a backup of the cluster is proven to restore:

1.  **Checks, before anything is written.** Each refuses by name. ``<dir>`` and its ``data/`` are
    outside the system temporary directory and the test servers' base directory; ``data/`` is a
    PostgreSQL data directory without a marker, made by the same major version as the binaries,
    and it and ``<dir>`` belong to the account running the command. The cluster is then reached,
    on the port it runs on or, when it is stopped, on a private port nothing is configured to use.
    A server running with ``fsync`` or ``full_page_writes`` off, which is how the test servers
    run, is refused, and so is a cluster whose own settings turn either off. The owner role must
    be the cluster's bootstrap superuser, connecting without a password over the loopback
    interface as the command connects to every local database; the database must exist; and it
    must record every migration this code has, with the same bytes, and none this code lacks.
2.  **A backup in the command's own format** (:func:`~exulanica.db.local.backup.take_backup`),
    into ``<dir>/backups``.
3.  **Proof that it restores** (:func:`~exulanica.db.local.backup.verify_backup`): its digest,
    then a restore into a scratch server compared with its manifest.
4.  **The port**, recorded with ``ALTER SYSTEM`` when the cluster's own settings do not already
    name the one it serves on, which is where ``init`` and ``restore`` record theirs and where
    ``start`` reads it.
5.  **The marker**, naming the backup that proved the adoption.

A refusal or a failure at any step leaves no marker. Until step 4 nothing of the cluster's own
has changed, and a backup taken in step 2 stays in ``<dir>/backups`` whatever happens after it, as
every backup does.

**What adopting never does.** It never migrates, never changes authentication (``pg_hba.conf``,
roles and passwords are read and never written) and never moves or copies the data directory. A
running server stays running on its port; a stopped one is started only on the private port and
is stopped again.

**The layout.** The command keeps a database as ``<dir>/data``, ``<dir>/backups`` and
``<dir>/server.log``, and every command derives all three from ``<dir>``. So ``--directory`` names
the directory that holds the existing data directory, and the command's backups begin in
``<dir>/backups``. Backups another tool took elsewhere stay where they are and remain that tool's:
this command cannot verify or restore a dump without its own manifest, the backups it lists are
the ones it wrote, and moving them would take files from under the tool that still writes there.
"""

from __future__ import annotations

import itertools
import json
import os
import pwd
import shlex
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exulanica.db.local.backup import _BOOTSTRAP_ROLE_OID, take_backup, verify_backup
from exulanica.db.local.cluster import POSTGRES_BIN_ENV, Cluster, binaries, url
from exulanica.db.local.database import (
    MARKER_PROFILE,
    LocalDatabase,
    schema_state,
    utc_now,
    write_private,
)
from exulanica.db.local.locations import LOCAL_DATABASE_MARKER, refuse_location
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = ["ADOPT", "DURABILITY_SETTINGS", "adopt"]

#: What an adoption's backup is named by, and what its marker says created it.
ADOPT: Final = "adopt"

#: The settings whose ``off`` makes a server disposable: how the test servers and the scratch
#: copies run, and what a local database never does.
DURABILITY_SETTINGS: Final = ("fsync", "full_page_writes")

#: How PostgreSQL spells a boolean setting that is off, in any case.
_OFF: Final = frozenset({"off", "false", "no", "0"})

#: A database every cluster has and none drops, to connect to before the named one is known to
#: exist, so that a missing database and a refused role are told apart.
_ALWAYS_PRESENT: Final = "template1"


@dataclass(frozen=True, slots=True)
class _Adopting(LocalDatabase):
    """A cluster during its adoption, before its marker exists.

    Every command reads a local database's owner role and database name from its marker, and
    until the adoption's backup is proven there is none, so the marker it will write stands in.
    """

    marker_to_write: Mapping[str, Any]

    def read_marker(self) -> dict[str, Any]:
        return dict(self.marker_to_write)


def _this_account() -> int:
    """The operating-system account this command runs as."""
    return os.geteuid()


def _account_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return f"uid {uid}"


def _refuse_other_owner(*paths: Path) -> None:
    account = _this_account()
    for path in paths:
        owner = path.stat().st_uid
        if owner != account:
            raise LocalDatabaseRefused(
                Refusal.OTHER_OWNER,
                f"{path} belongs to {_account_name(owner)}, and this command runs as "
                f"{_account_name(account)}. Adopt it as the account that owns it.",
            )


def _start_options(data: Path) -> dict[str, str]:
    """The settings the cluster was last started with, from the command line PostgreSQL records.

    ``postmaster.opts`` is rewritten at every start, so for a running server these are the
    settings it runs with beyond its own configuration files, and for a stopped one, the last.
    """
    try:
        words = shlex.split((data / "postmaster.opts").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    options: dict[str, str] = {}
    for flag, value in itertools.pairwise(words):
        if flag == "-p":
            options["port"] = value
        elif flag == "-c" and "=" in value:
            name, setting = value.split("=", 1)
            options[name.lower()] = setting
    for word in words:
        if word.startswith("--") and "=" in word:
            name, setting = word.removeprefix("--").split("=", 1)
            options[name.lower().replace("-", "_")] = setting
    return options


def _service_port(cluster: Cluster, stated: int | None) -> tuple[int, str]:
    """The port the cluster serves the application on, and where that was read.

    Read before the cluster is reached, because starting it on a private port rewrites the command
    line PostgreSQL records.
    """
    if stated is not None:
        return stated, "given with --port"
    if cluster.running():
        return cluster.running_port(), "the port it runs on"
    last = _start_options(cluster.data).get("port", "")
    if last.isdigit():
        return int(last), "the port it was last started on"
    return cluster.configured_port(), "the port its settings name"


@contextmanager
def _reached(cluster: Cluster) -> Iterator[tuple[int, bool]]:
    """The port the adoption talks to the cluster on, and whether the cluster was running.

    A running server is used where it runs and left running. A stopped one is started on a port
    chosen here, which nothing is configured to use, and stopped again when the block ends.
    """
    if cluster.running():
        yield cluster.running_port(), True
        return
    port = cluster.start_on_a_free_port()
    try:
        yield port, False
    finally:
        cluster.stop()


def _owner_connection(port: int, owner: str, database: str, data: Path) -> psycopg.Connection:
    try:
        return psycopg.connect(url(port, owner, database), autocommit=True, row_factory=dict_row)
    except psycopg.OperationalError as error:
        reason = " ".join(str(error).split())
        raise LocalDatabaseRefused(
            Refusal.OWNER_ROLE,
            f"exulanica-local-db connects to every local database as its bootstrap superuser, "
            f"without a password, over the loopback interface, and the server on {data} refused "
            f"{owner}: {reason}. Adopting never changes authentication: name the cluster's "
            "bootstrap superuser with --owner-role, or adopt a cluster that admits it.",
        ) from error


def _refuse_a_test_server(data: Path, off: list[str]) -> None:
    if off:
        raise LocalDatabaseRefused(
            Refusal.TEST_SERVER_RUNNING,
            f"the server running on {data} has {', '.join(off)} off, which is how the test "
            "servers run: a crash can corrupt it, and the test tooling migrates and deletes what "
            "it runs. Stop it, and adopt the cluster only once nothing runs it that way.",
        )


def _refuse_what_the_server_says(
    connection: psycopg.Connection, *, data: Path, owner: str, database: str, running: bool
) -> None:
    """The checks only the server can answer: durability, the owner role and the database."""
    off = [
        name
        for name in DURABILITY_SETTINGS
        if connection.execute("select current_setting(%s) as value", (name,)).fetchone()["value"]
        in _OFF
    ]
    if running:
        _refuse_a_test_server(data, off)
    if off:
        raise LocalDatabaseRefused(
            Refusal.DURABILITY_OFF,
            f"the settings of {data} turn {', '.join(off)} off. A local database keeps "
            "PostgreSQL's durable defaults, and adopting never changes a cluster's settings: turn "
            f"{' and '.join(off)} back on first.",
        )
    bootstrap = connection.execute(
        "select rolname from pg_roles where oid = %s", (_BOOTSTRAP_ROLE_OID,)
    ).fetchone()["rolname"]
    if bootstrap != owner:
        raise LocalDatabaseRefused(
            Refusal.OWNER_ROLE,
            f"{owner} is not the bootstrap superuser of {data}, which is {bootstrap}. A backup "
            "names the bootstrap superuser as the owner of everything in it, and a restore "
            f"recreates it: adopt with --owner-role {bootstrap}.",
        )
    exists = connection.execute(
        "select 1 from pg_database where datname = %s", (database,)
    ).fetchone()
    if exists is None:
        held = [
            row["datname"]
            for row in connection.execute(
                "select datname from pg_database where not datistemplate order by datname"
            ).fetchall()
        ]
        raise LocalDatabaseRefused(
            Refusal.NO_SUCH_DATABASE,
            f"{data} holds no database {database}; it holds {', '.join(held)}. Name the one "
            "that holds the schema with --database.",
        )


def _keep_port(candidate: LocalDatabase, port: int, serves_on: int) -> bool:
    """Record ``serves_on`` in the cluster's own settings unless they already name it."""
    if candidate.cluster.configured_port() == serves_on:
        return False
    with _owner_connection(port, candidate.owner, _ALWAYS_PRESENT, candidate.data) as connection:
        connection.execute(sql.SQL("alter system set port = {}").format(sql.Literal(serves_on)))
    return True


def adopt(
    directory: Path,
    *,
    database_name: str,
    owner: str,
    port: int | None,
    stream: TextIO,
) -> LocalDatabase:
    """Check, back up, prove the backup, keep the port, then mark the cluster in ``directory``."""
    root = refuse_location(directory)
    data = root / "data"
    refuse_location(data)
    if not (data / "PG_VERSION").is_file():
        raise LocalDatabaseRefused(
            Refusal.NO_DATA_DIRECTORY,
            f"{data} is not a PostgreSQL data directory: it holds no PG_VERSION. Name the "
            "directory that holds the cluster's data/ with --directory.",
        )
    if (data / LOCAL_DATABASE_MARKER).exists():
        raise LocalDatabaseRefused(
            Refusal.ALREADY_A_LOCAL_DATABASE,
            f"{data} already carries {LOCAL_DATABASE_MARKER}; use the other commands on "
            f"{root} as they are.",
        )
    _refuse_other_owner(root, data.resolve())
    candidate = _Adopting(
        root,
        marker_to_write={
            "profile": MARKER_PROFILE,
            "created_by": ADOPT,
            "owner_role": owner,
            "database": database_name,
            "postgres": binaries().version,
            "restored_from": None,
        },
    )
    cluster = candidate.cluster
    try:
        major = cluster.major()
    except ValueError as error:
        raise LocalDatabaseRefused(
            Refusal.NO_DATA_DIRECTORY, f"{data / 'PG_VERSION'} names no version: {error}"
        ) from error
    if major != binaries().major:
        raise LocalDatabaseRefused(
            Refusal.SERVER_VERSION,
            f"{data} was made by PostgreSQL {major} and the binaries found are "
            f"{binaries().version} in {binaries().directory}; set {POSTGRES_BIN_ENV} to the "
            f"PostgreSQL {major} binaries. Adopting never upgrades a cluster.",
        )
    if cluster.running():
        started_with = _start_options(data)
        _refuse_a_test_server(
            data,
            [name for name in DURABILITY_SETTINGS if started_with.get(name, "").lower() in _OFF],
        )
    serves_on, source = _service_port(cluster, port)
    with _reached(cluster) as (at, running):
        with _owner_connection(at, owner, _ALWAYS_PRESENT, data) as connection:
            _refuse_what_the_server_says(
                connection, data=data, owner=owner, database=database_name, running=running
            )
        with _owner_connection(at, owner, database_name, data) as connection:
            state = schema_state(connection)
        if state.drift:
            raise LocalDatabaseRefused(Refusal.SCHEMA_DRIFT, state.drift)
        if state.pending:
            raise LocalDatabaseRefused(
                Refusal.MIGRATIONS_MISSING,
                f"{database_name} lacks {len(state.pending)} migrations this code expects "
                f"({', '.join(state.pending)}). Adopting never migrates: adopt it with the code "
                "that last migrated it, then run `exulanica-local-db upgrade`.",
            )
        reached = "running on it" if running else "started on it for this step and stopped after"
        print(
            f"adopting {root}: PostgreSQL {major} data directory {data}, owned by "
            f"{_account_name(_this_account())}; reached on port {at} ({reached}); serves on "
            f"port {serves_on} ({source})",
            file=stream,
        )
        print(f"schema: {state.describe()}", file=stream)
        backup = take_backup(candidate, at, ADOPT, service_port=serves_on)
        print(f"backup: {backup.describe()}", file=stream)
        counts = verify_backup(backup)
        print(
            f"restorable: sha256 matches; a scratch restore holds {len(counts)} tables and "
            f"{sum(counts.values())} rows, and its row counts and migrations equal its manifest",
            file=stream,
        )
        if _keep_port(candidate, at, serves_on):
            print(f"port: recorded {serves_on} in the cluster's own settings", file=stream)
        write_private(
            candidate.marker,
            json.dumps(
                {
                    **candidate.marker_to_write,
                    "created_at": utc_now(),
                    "adopted": {
                        "backup": backup.dump.name,
                        "sha256": backup.sha256,
                        "taken_at": backup.manifest["taken_at"],
                        "service_port": serves_on,
                    },
                },
                indent=1,
                sort_keys=True,
            )
            + "\n",
        )
    print(
        f"adopted: {candidate.marker} names {backup.dump.name}; run the other commands with "
        f"--directory {root}",
        file=stream,
    )
    return LocalDatabase.open(root)
