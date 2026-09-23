"""``exulanica-local-db``: the database of a personal install, on the person's own computer.

A command of its own rather than a subcommand of ``exulanica-db``, because the two answer
different questions. ``exulanica-db`` brings a database it is given a URL for, on any host, to the
schema and roles this code expects, in the one correct order, and takes no arguments so there is
no second way to ask. This command owns a PostgreSQL cluster on this machine: where its files
live, starting and stopping it, backing it up, proving a backup restores, restoring one, and
upgrading it. It runs ``exulanica-db``'s provisioning as one step of ``init`` and ``upgrade``.

Every command names the directory it works on, and nothing has a default location. See
:mod:`exulanica.db.local` for the rules, and ``docs/development-setup.md`` for a walk-through.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, NoReturn, TextIO

import psycopg
from psycopg import sql

from exulanica.db.account_roles import ACCOUNT_ROLE
from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV
from exulanica.db.local.backup import (
    Backup,
    check_digest,
    compare_with_manifest,
    list_backups,
    read_backup,
    restore_database,
    take_backup,
    verify_backup,
)
from exulanica.db.local.cluster import (
    binaries,
    bootstrap_user,
    port_is_free,
    sweep_scratch,
    url,
)
from exulanica.db.local.database import DATABASE_NAME, LocalDatabase, schema_state
from exulanica.db.local.locations import (
    base_for_scratch_servers,
    refuse_existing_data,
    refuse_location,
)
from exulanica.db.local.refusals import FAILURES, LocalDatabaseRefused, Refusal
from exulanica.db.local.upgrade import migrate_and_provision, upgrade
from exulanica.db.roles import EXECUTOR_ROLE, PURGE_ROLE, RUNTIME_ROLE
from exulanica.db.session import DATABASE_URL_ENV
from exulanica.env import env_name

__all__ = ["CONNECTIONS", "main"]

#: The connections the application reads, and the provisioned role each is made as. The two
#: names read above this package are restated here; ``tests/test_local_database.py`` holds them
#: equal to ``exulanica.api.services`` and ``exulanica.deletion.cli``.
CONNECTIONS: Final = (
    (DATABASE_URL_ENV, RUNTIME_ROLE),
    (env_name("READONLY_DATABASE_URL"), EXECUTOR_ROLE),
    (env_name("PURGE_DATABASE_URL"), PURGE_ROLE),
    (ACCOUNT_DATABASE_URL_ENV, ACCOUNT_ROLE),
)

#: What a backup taken by ``backup`` without ``--reason`` is named by.
ON_REQUEST: Final = "on-request"

#: TCP port numbers, which ``0`` is not: PostgreSQL refuses to listen on it.
_PORTS: Final = range(1, 65536)

Handler = Callable[[argparse.Namespace, TextIO], None]


def _connections(database: LocalDatabase, port: int, stream: TextIO) -> None:
    for name, role in CONNECTIONS:
        print(f"export {name}={database.role_url(port, role)}", file=stream)
    print(
        f"owner (migrations and provisioning only; the API refuses it): {database.owner_url(port)}",
        file=stream,
    )


def _keep_port(database: LocalDatabase, port: int) -> None:
    """Record ``port`` in the cluster's own settings, so every later start uses it."""
    with psycopg.connect(url(port, database.owner, "postgres"), autocommit=True) as connection:
        connection.execute(sql.SQL("alter system set port = {}").format(sql.Literal(port)))


def _stop_after_failure(database: LocalDatabase, error: BaseException, step: Refusal) -> NoReturn:
    """Stop a cluster whose creation failed part way, and say what its directory holds.

    Once the directory exists the command has attempted ``step``, so whatever stopped it is
    reported as that step's failure, carrying the name of the refusal behind it if there was one.
    """
    with contextlib.suppress(LocalDatabaseRefused):
        database.cluster.stop()
    if isinstance(error, LocalDatabaseRefused) and error.refusal in FAILURES:
        refusal, reason = error.refusal, error.detail
    elif isinstance(error, LocalDatabaseRefused):
        refusal, reason = step, f"{error.refusal.value}: {error.detail}"
    else:
        refusal, reason = step, f"{type(error).__name__}: {error}"
    raise LocalDatabaseRefused(
        refusal,
        f"{reason}\n{database.root} holds the incomplete result and nothing uses it; "
        "remove it before trying again.",
    ) from error


def _init(arguments: argparse.Namespace, stream: TextIO) -> None:
    target = refuse_location(arguments.directory)
    refuse_existing_data(target)
    if arguments.port is not None and not port_is_free(arguments.port):
        raise LocalDatabaseRefused(Refusal.PORT_IN_USE, f"port {arguments.port} is in use")
    database = LocalDatabase.create(
        target, owner=bootstrap_user(), database_name=DATABASE_NAME, created_by="init"
    )
    cluster = database.cluster
    try:
        port = cluster.start(arguments.port) if arguments.port else cluster.start_on_a_free_port()
        _keep_port(database, port)
        with psycopg.connect(url(port, database.owner, "postgres"), autocommit=True) as created:
            created.execute(sql.SQL("create database {}").format(sql.Identifier(DATABASE_NAME)))
    except (LocalDatabaseRefused, psycopg.Error) as error:
        _stop_after_failure(database, error, Refusal.SERVER_FAILED)
    try:
        applied = migrate_and_provision(database.owner_url(port))
    except Exception as error:
        _stop_after_failure(database, error, Refusal.MIGRATION_FAILED)
    print(
        f"initialised {database.root} with PostgreSQL {binaries().version}, durability at "
        f"PostgreSQL's defaults; running on port {port}",
        file=stream,
    )
    print(f"schema: applied {len(applied)} migrations, last {applied[-1]}", file=stream)
    _connections(database, port, stream)


def _start(arguments: argparse.Namespace, stream: TextIO) -> None:
    database = LocalDatabase.open(arguments.directory)
    cluster = database.cluster
    if cluster.running():
        print(f"already running: {database.root} on port {cluster.running_port()}", file=stream)
    else:
        cluster.start()
        print(f"started {database.root} on port {cluster.running_port()}", file=stream)
    port = cluster.running_port()
    with database.connect(port) as connection:
        print(f"schema: {schema_state(connection).describe()}", file=stream)
    _connections(database, port, stream)


def _stop(arguments: argparse.Namespace, stream: TextIO) -> None:
    database = LocalDatabase.open(arguments.directory)
    cluster = database.cluster
    if not cluster.running():
        print(f"not running: {database.root}", file=stream)
        return
    cluster.stop()
    print(f"stopped {database.root}; taking the backup a stop takes", file=stream)
    with database.maintenance() as session:
        backup = take_backup(database, session.port, "stop")
    print(f"backup: {backup.describe()}", file=stream)


def _status(arguments: argparse.Namespace, stream: TextIO) -> None:
    database = LocalDatabase.open(arguments.directory)
    marker = database.read_marker()
    cluster = database.cluster
    print(
        f"local database {database.root} (created by {marker['created_by']} "
        f"{marker['created_at']}; owner role {marker['owner_role']})",
        file=stream,
    )
    backups = list_backups(database.backups)
    size = sum(backup.dump.stat().st_size for backup in backups)
    newest = f"; newest {backups[-1].dump.name}" if backups else ""
    if cluster.running():
        port = cluster.running_port()
        print(f"server: running on port {port}", file=stream)
        with database.connect(port) as connection:
            print(f"schema: {schema_state(connection).describe()}", file=stream)
    else:
        print(
            f"server: stopped; starts on port {cluster.configured_port()}; schema not read",
            file=stream,
        )
    print(f"backups: {len(backups)} in {database.backups}, {size} bytes{newest}", file=stream)
    if cluster.running():
        _connections(database, cluster.running_port(), stream)


def _backup(arguments: argparse.Namespace, stream: TextIO) -> None:
    database = LocalDatabase.open(arguments.directory)
    cluster = database.cluster
    if cluster.running():
        backup = take_backup(database, cluster.running_port(), arguments.reason)
    else:
        with database.maintenance() as session:
            backup = take_backup(database, session.port, arguments.reason)
    print(f"backup: {backup.describe()}", file=stream)


def _verify(arguments: argparse.Namespace, stream: TextIO) -> None:
    backup: Backup
    if arguments.dump is not None:
        backup = read_backup(arguments.dump)
    elif arguments.directory is not None:
        database = LocalDatabase.open(arguments.directory)
        backups = list_backups(database.backups)
        if not backups:
            raise LocalDatabaseRefused(Refusal.NO_BACKUP, f"{database.backups} holds no backup")
        backup = backups[-1]
    else:
        raise LocalDatabaseRefused(
            Refusal.NO_BACKUP, "name a dump, or a local database whose newest backup to verify"
        )
    counts = verify_backup(backup)
    print(
        f"restorable: {backup.dump}: sha256 matches; a scratch restore holds "
        f"{len(counts)} tables and {sum(counts.values())} rows, and its row counts and "
        "migrations equal its manifest",
        file=stream,
    )


def _restore(arguments: argparse.Namespace, stream: TextIO) -> None:
    target = refuse_location(arguments.directory)
    refuse_existing_data(target)
    backup = read_backup(arguments.dump)
    check_digest(backup)
    port = arguments.port if arguments.port is not None else backup.service_port
    if not port_is_free(port):
        raise LocalDatabaseRefused(
            Refusal.PORT_IN_USE,
            f"port {port} is in use; pass --port to restore onto another one",
        )
    database = LocalDatabase.create(
        target,
        owner=backup.owner_role,
        database_name=backup.database,
        created_by="restore",
        restored_from={
            "dump": backup.dump.name,
            "sha256": backup.sha256,
            "taken_at": backup.manifest["taken_at"],
        },
    )
    try:
        database.cluster.start(port)
        _keep_port(database, port)
        restore_database(database.cluster, port, backup)
        with database.connect(port) as connection:
            connection.execute("analyze")
            counts = compare_with_manifest(connection, backup)
            state = schema_state(connection)
    except (LocalDatabaseRefused, psycopg.Error) as error:
        _stop_after_failure(database, error, Refusal.RESTORE_FAILED)
    print(
        f"restored {backup.dump.name} into {database.root}, running on port {port}: "
        f"{len(counts)} tables and {sum(counts.values())} rows, equal to its manifest",
        file=stream,
    )
    print(f"schema: {state.describe()}", file=stream)
    _connections(database, port, stream)


def _upgrade(arguments: argparse.Namespace, stream: TextIO) -> None:
    upgrade(LocalDatabase.open(arguments.directory), stream)


def _port(text: str) -> int:
    port = int(text)
    if port not in _PORTS:
        raise argparse.ArgumentTypeError(
            f"{port} is not a TCP port ({_PORTS.start} to {_PORTS[-1]})"
        )
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exulanica-local-db",
        description=(
            "A durable PostgreSQL database for a personal install: create it, start and stop "
            "it, back it up, prove a backup restores, restore one, and upgrade its schema."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, summary: str, handler: Handler) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=summary, description=summary)
        sub.set_defaults(handler=handler)
        return sub

    def directory(sub: argparse.ArgumentParser, *, required: bool = True) -> None:
        sub.add_argument(
            "--directory",
            type=Path,
            required=required,
            help="The local database's directory. Never inside a temporary directory.",
        )

    init = command(
        "init",
        "Create a durable cluster in an empty or absent directory, migrate it and start it.",
        _init,
    )
    directory(init)
    init.add_argument("--port", type=_port, help="The port to serve on; a free one otherwise.")

    directory(command("start", "Start the server. Never migrates.", _start))
    directory(command("stop", "Stop the server, then take a backup of what it holds.", _stop))
    directory(command("status", "Say whether it runs, its schema, and its backups.", _status))

    backup = command("backup", "Take a backup now, with its SHA-256 and manifest.", _backup)
    directory(backup)
    backup.add_argument("--reason", default=ON_REQUEST, help="Part of the backup's file name.")

    verify = command(
        "verify",
        "Restore a backup into a scratch server and compare it with its manifest.",
        _verify,
    )
    directory(verify, required=False)
    verify.add_argument(
        "dump", nargs="?", type=Path, help="A .pgdump; the newest in --directory otherwise."
    )

    restore = command(
        "restore", "Restore a backup into a new local database in an empty directory.", _restore
    )
    directory(restore)
    restore.add_argument("dump", type=Path, help="The .pgdump, with its manifest beside it.")
    restore.add_argument(
        "--port",
        type=_port,
        help="The port to serve on; the one the backed-up database used otherwise.",
    )

    directory(
        command(
            "upgrade",
            "Back up, rehearse the pending migrations on a scratch copy, migrate, back up again.",
            _upgrade,
        )
    )
    return parser


def main(argv: list[str] | None = None, stream: Any = None) -> int:
    arguments = build_parser().parse_args(argv)
    handler: Handler = arguments.handler
    # A scratch copy left by a run that was killed together with its watcher goes at the next
    # command of any kind, not only at the next verify or upgrade.
    sweep_scratch(base_for_scratch_servers())
    try:
        handler(arguments, stream or sys.stdout)
    except LocalDatabaseRefused as stopped:
        kind = "failed" if stopped.refusal in FAILURES else "refused"
        print(f"{kind} ({stopped.refusal.value}): {stopped.detail}", file=sys.stderr)
        return stopped.exit_status
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
