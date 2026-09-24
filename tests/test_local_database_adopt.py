"""``exulanica-local-db adopt`` against real PostgreSQL 18 clusters this command did not mark.

A cluster to adopt is made the way the command's own tests make a world, and then made to look
like one another tool left: its marker and its empty ``backups/`` removed, its port removed from
its settings, and last started with that port on its command line, as a launcher starts it. Each
test adopts a copy of that data directory, so a test can change its copy without touching the
next one's.

What is held here:

*   **A copy with rows keeps every row.** Adopting backs up, proves the backup restores, records
    the port the cluster serves on and writes the marker, and afterwards the cluster holds the
    same rows, the same migrations and the same system identifier, and its authentication and
    main configuration files hold the same bytes. A running cluster is adopted where it runs and
    is never restarted.
*   **Each refusal, by name, before anything is written.** No marker, no ``backups/``, and the
    cluster's files as they were.
*   **A backup that fails verification leaves no marker**, and does not record the port either.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from exulanica.db.local import adopt as adopt_module
from exulanica.db.local import cluster
from exulanica.db.local.backup import list_backups, read_backup, take_backup
from exulanica.db.local.database import LocalDatabase, applied_versions, server_identity
from exulanica.db.local.locations import LOCAL_DATABASE_MARKER, base_for_test_servers
from exulanica.migrations import migrations
from psycopg.rows import dict_row

from test_local_database import Machine, cli, simulate_machine
from test_local_database_postgres import (
    Servers,
    _init_trusted,
    _require_server_binaries,
    _state,
    _stop_when_this_process_exits,
    _write_person_rows,
    migration_files,
)

pytestmark = pytest.mark.postgres

#: How the tool that made the cluster to adopt starts it: loopback only, no socket, and its port
#: given on the command line rather than kept in the cluster's own settings.
ANOTHER_TOOLS_SETTINGS = {"listen_addresses": "localhost", "unix_socket_directories": ""}

#: The files adopting may never write: authentication and the main configuration.
UNTOUCHED = ("pg_hba.conf", "pg_ident.conf", "postgresql.conf")

#: How long a reloaded setting may take to reach a new session: the postmaster applies a reload
#: when it handles the signal, with room for a loaded machine.
RELOAD_SECONDS = 10


@dataclass(frozen=True)
class World:
    """A stopped cluster with a person's rows, as another tool leaves one, and what it holds."""

    root: Path
    port: int
    versions: tuple[str, ...]
    counts: dict[str, int]
    identifier: str


@pytest.fixture(scope="module")
def machine(tmp_path_factory) -> Iterator[Machine]:
    _require_server_binaries()
    with pytest.MonkeyPatch.context() as patch:
        yield simulate_machine(tmp_path_factory.mktemp("adopt"), patch)


@pytest.fixture
def servers(machine) -> Iterator[Servers]:
    made = Servers(roots=[])
    yield made
    made.stop_all()


def _start_as_another_tool(database: LocalDatabase, port: int) -> None:
    database.cluster.start(port, ANOTHER_TOOLS_SETTINGS)
    _stop_when_this_process_exits(database)


def _unmarked_world(servers: Servers, directory: Path) -> World:
    """A world the command made, then left the way a cluster another tool made looks: one that
    trusts every connection from this computer, as adopting requires."""
    database = _init_trusted(servers, directory)
    _write_person_rows(database)
    port = database.cluster.running_port()
    with database.connect(port) as connection:
        connection.execute("alter system reset port")
        identifier = server_identity(connection)["system_identifier"]
    versions, counts = _state(database)
    database.cluster.stop()
    database.marker.unlink()
    database.backups.rmdir()
    _start_as_another_tool(database, port)
    database.cluster.stop()
    return World(database.root, port, tuple(versions), counts, identifier)


@pytest.fixture(scope="module")
def world(machine, tmp_path_factory) -> Iterator[World]:
    made = Servers(roots=[])
    try:
        yield _unmarked_world(made, tmp_path_factory.mktemp("world") / "database")
    finally:
        made.stop_all()


def _copy(world: World, servers: Servers, directory: Path) -> LocalDatabase:
    """A copy of the world's directory, stopped, stopped again when the test ends."""
    shutil.copytree(world.root, directory, symlinks=True)
    servers.roots.append(directory)
    return LocalDatabase(directory)


def _files(database: LocalDatabase) -> dict[str, bytes]:
    return {name: (database.data / name).read_bytes() for name in UNTOUCHED}


def _auto_conf(database: LocalDatabase) -> bytes:
    return (database.data / "postgresql.auto.conf").read_bytes()


def _assert_nothing_written(database: LocalDatabase, files: dict[str, bytes], auto: bytes) -> None:
    assert not (database.data / LOCAL_DATABASE_MARKER).exists()
    assert not database.backups.exists()
    assert _files(database) == files
    assert _auto_conf(database) == auto


def _applied_without_a_marker(port: int) -> tuple[str, ...]:
    """The migrations a cluster with no marker records, read as its bootstrap superuser."""
    owner = cluster.url(port, cluster.bootstrap_user(), "exulanica", passfile=None)
    with psycopg.connect(owner, autocommit=True, row_factory=dict_row) as connection:
        return tuple(applied_versions(connection))


def _eventually_shows(owner_url: str, setting: str, value: str) -> bool:
    """Whether a new session sees ``setting`` at ``value`` once a reload has been signalled."""
    deadline = time.monotonic() + RELOAD_SECONDS
    while time.monotonic() < deadline:
        with psycopg.connect(owner_url, autocommit=True) as connection:
            if connection.execute(f"show {setting}").fetchone() == (value,):
                return True
        time.sleep(0.05)
    return False


def _adopt(database: LocalDatabase, *extra: object):
    return cli("adopt", "--directory", database.root, *extra)


def _refused(result, name: str) -> None:
    assert result.status == 2, (result.out, result.err)
    assert f"refused ({name})" in result.err


# -- a copy with rows keeps every row ----------------------------------------------------------


def test_adopting_a_copy_with_rows_keeps_every_row_and_marks_it_last(world, servers, tmp_path):
    database = _copy(world, servers, tmp_path / "database")
    files = _files(database)
    assert database.cluster.configured_port() != world.port

    result = _adopt(database)

    assert result.status == 0, result.err
    assert f"serves on port {world.port} (the port it was last started on)" in result.out
    (backup,) = list_backups(database.backups)
    assert backup.dump.name.endswith("-adopt.pgdump")
    assert backup.row_counts == world.counts
    assert backup.migrations == world.versions
    assert backup.service_port == world.port
    marker = LocalDatabase.open(database.root).read_marker()
    assert (marker["created_by"], marker["owner_role"], marker["database"]) == (
        "adopt",
        cluster.bootstrap_user(),
        "exulanica",
    )
    assert marker["adopted"] == {
        "backup": backup.dump.name,
        "sha256": backup.sha256,
        "taken_at": backup.manifest["taken_at"],
        "service_port": world.port,
    }
    # Stopped as it was found; its authentication and main configuration as they were; and the
    # port it serves on now in its own settings, which is where `start` reads it.
    assert not database.cluster.running()
    assert _files(database) == files
    assert database.cluster.configured_port() == world.port

    started = cli("start", "--directory", database.root)
    assert started.status == 0, started.err
    assert database.cluster.running_port() == world.port
    assert "none pending" in started.out
    versions, counts = _state(database)
    assert (tuple(versions), counts) == (world.versions, world.counts)
    with database.connect(world.port) as connection:
        assert server_identity(connection)["system_identifier"] == world.identifier
    # Nothing moved or copied: the directory holds what it held, and the backups beside it.
    assert sorted(path.name for path in database.root.iterdir()) == [
        "backups",
        "data",
        "server.log",
    ]


def test_a_running_cluster_is_adopted_where_it_runs_and_never_restarted(world, servers, tmp_path):
    database = _copy(world, servers, tmp_path / "database")
    _start_as_another_tool(database, world.port)
    postmaster = (database.data / "postmaster.pid").read_text().splitlines()[0]

    result = _adopt(database)

    assert result.status == 0, result.err
    assert f"reached on port {world.port} (running on it)" in result.out
    assert database.cluster.running()
    assert (database.data / "postmaster.pid").read_text().splitlines()[0] == postmaster
    versions, counts = _state(database)
    assert (tuple(versions), counts) == (world.versions, world.counts)
    assert LocalDatabase.open(database.root).read_marker()["created_by"] == "adopt"
    assert database.cluster.configured_port() == world.port


# -- each refusal, before anything is written ----------------------------------------------------


def _stranger(root: Path, version: str = "18") -> LocalDatabase:
    """A directory that looks like a cluster to the checks made before any server starts."""
    (root / "data").mkdir(parents=True)
    (root / "data" / "PG_VERSION").write_text(f"{version}\n")
    (root / "data" / "postgresql.auto.conf").write_text("")
    for name in UNTOUCHED:
        (root / "data" / name).write_text(f"# {name}\n")
    return LocalDatabase(root)


@pytest.mark.parametrize(
    ("where", "name"),
    [("temporary", "temporary-directory"), ("test servers", "test-server-directory")],
)
def test_a_cluster_somewhere_disposable_is_refused(machine, where, name):
    base = machine.temporary if where == "temporary" else base_for_test_servers()
    database = _stranger(base / "left-behind")
    files, auto = _files(database), _auto_conf(database)

    _refused(_adopt(database), name)
    _assert_nothing_written(database, files, auto)


def test_a_directory_without_a_data_directory_is_refused(machine):
    root = machine.durable / "no-data"
    root.mkdir()

    _refused(_adopt(LocalDatabase(root)), "no-data-directory")
    assert sorted(path.name for path in root.iterdir()) == []


def test_a_cluster_that_already_carries_the_marker_is_refused(machine):
    database = _stranger(machine.durable / "marked")
    (database.data / LOCAL_DATABASE_MARKER).write_text("{}")
    files, auto = _files(database), _auto_conf(database)

    _refused(_adopt(database), "already-a-local-database")
    assert (database.data / LOCAL_DATABASE_MARKER).read_text() == "{}"
    assert not database.backups.exists()
    assert (_files(database), _auto_conf(database)) == (files, auto)


def test_a_cluster_another_account_owns_is_refused(machine, monkeypatch):
    database = _stranger(machine.durable / "not-mine")
    files, auto = _files(database), _auto_conf(database)
    monkeypatch.setattr(adopt_module, "_this_account", lambda: os.geteuid() + 1)

    _refused(_adopt(database), "other-owner")
    _assert_nothing_written(database, files, auto)


@pytest.mark.parametrize("running", [False, True])
def test_a_cluster_another_postgresql_major_made_is_refused(machine, running):
    """Stopped or running: a server of another major is refused before anything connects to it.

    A second PostgreSQL installation cannot be assumed here, so the running one is a process that
    ``pg_ctl status`` takes for its postmaster, listening on nothing. Only a refusal decided from
    the data directory, before any connection, can name the version rather than the role.
    """
    database = _stranger(
        machine.durable / f"older-{'running' if running else 'stopped'}",
        version=str(cluster.binaries().major - 1),
    )
    files, auto = _files(database), _auto_conf(database)
    stand_in = None
    if running:
        stand_in = subprocess.Popen(["/bin/sleep", "60"])
        (database.data / "postmaster.pid").write_text(
            f"{stand_in.pid}\n{database.data}\n0\n{cluster._free_port()}\n\nlocalhost\n"
        )
    try:
        assert database.cluster.running() is running
        _refused(_adopt(database), "server-version")
    finally:
        if stand_in is not None:
            stand_in.kill()
            stand_in.wait()
    _assert_nothing_written(database, files, auto)


def test_a_running_test_server_is_refused_and_left_running(world, servers, tmp_path):
    database = _copy(world, servers, tmp_path / "database")
    database.cluster.start(world.port, cluster.SCRATCH_SETTINGS)
    _stop_when_this_process_exits(database)
    files, auto = _files(database), _auto_conf(database)

    _refused(_adopt(database), "test-server-running")
    # Read from how it was started, before any connection: a role it would refuse changes nothing.
    _refused(_adopt(database, "--owner-role", "nobody_by_this_name"), "test-server-running")
    _assert_nothing_written(database, files, auto)
    assert database.cluster.running()


def test_a_server_running_with_durability_off_by_its_settings_is_refused(world, servers, tmp_path):
    """Started without test settings, and running as a test server does all the same."""
    database = _copy(world, servers, tmp_path / "database")
    port = cluster._free_port()
    database.cluster.start(port)
    _stop_when_this_process_exits(database)
    owner = cluster.url(port, cluster.bootstrap_user(), "postgres", passfile=None)
    with psycopg.connect(owner, autocommit=True) as connection:
        connection.execute("alter system set fsync = off")
        connection.execute("select pg_reload_conf()")
    assert _eventually_shows(owner, "fsync", "off")
    files, auto = _files(database), _auto_conf(database)

    _refused(_adopt(database), "test-server-running")
    _assert_nothing_written(database, files, auto)
    assert database.cluster.running()


def test_a_cluster_whose_settings_turn_durability_off_is_refused(world, servers, tmp_path):
    database = _copy(world, servers, tmp_path / "database")
    port = cluster._free_port()
    database.cluster.start(port)
    with psycopg.connect(
        cluster.url(port, cluster.bootstrap_user(), "postgres", passfile=None)
    ) as connection:
        connection.autocommit = True
        connection.execute("alter system set fsync = off")
    database.cluster.stop()
    files, auto = _files(database), _auto_conf(database)

    _refused(_adopt(database), "durability-off")
    _assert_nothing_written(database, files, auto)
    assert not database.cluster.running()


def test_an_owner_role_that_cannot_connect_or_is_not_the_bootstrap_superuser_is_refused(
    world, servers, tmp_path
):
    database = _copy(world, servers, tmp_path / "database")
    port = cluster._free_port()
    database.cluster.start(port)
    with psycopg.connect(
        cluster.url(port, cluster.bootstrap_user(), "postgres", passfile=None)
    ) as connection:
        connection.autocommit = True
        connection.execute("create role another_superuser superuser login")
    database.cluster.stop()
    files, auto = _files(database), _auto_conf(database)

    absent = _adopt(database, "--owner-role", "nobody_by_this_name")
    another = _adopt(database, "--owner-role", "another_superuser")

    _refused(absent, "owner-role")
    assert "nobody_by_this_name" in absent.err
    _refused(another, "owner-role")
    assert f"which is {cluster.bootstrap_user()}" in another.err
    _assert_nothing_written(database, files, auto)


def test_a_database_the_cluster_does_not_hold_is_refused(world, servers, tmp_path):
    database = _copy(world, servers, tmp_path / "database")
    files, auto = _files(database), _auto_conf(database)

    result = _adopt(database, "--database", "elsewhere")

    _refused(result, "no-such-database")
    assert "exulanica" in result.err
    _assert_nothing_written(database, files, auto)


def test_a_database_behind_this_code_is_refused_and_never_migrated(servers, machine, tmp_path):
    with migration_files(tmp_path / "older-code", drop_last=1):
        behind = _unmarked_world(servers, tmp_path / "database")
    database = LocalDatabase(behind.root)
    files, auto = _files(database), _auto_conf(database)
    missing = [m.version for m in migrations() if m.version not in behind.versions]

    result = _adopt(database)

    _refused(result, "migrations-missing")
    assert ", ".join(missing) in result.err
    _assert_nothing_written(database, files, auto)
    database.cluster.start(behind.port)
    assert _applied_without_a_marker(behind.port) == behind.versions


def test_a_database_ahead_of_this_code_is_refused_as_drift(servers, machine, tmp_path):
    last = list(migrations())[-1].version
    later = {f"{int(last) + 1:04d}_a_later_table.sql": "create table adopt_later (id integer);\n"}
    with migration_files(tmp_path / "newer-code", extra=later):
        ahead = _unmarked_world(servers, tmp_path / "database")
    database = LocalDatabase(ahead.root)
    files, auto = _files(database), _auto_conf(database)

    result = _adopt(database)

    _refused(result, "schema-drift")
    assert f"{int(last) + 1:04d}" in result.err
    _assert_nothing_written(database, files, auto)


# -- a backup that fails verification leaves no marker ---------------------------------------


def _damaged_in_the_dump(backup) -> None:
    damaged = bytearray(backup.dump.read_bytes())
    damaged[len(damaged) // 2] ^= 0xFF
    backup.dump.write_bytes(bytes(damaged))


def _damaged_in_the_manifest(backup) -> None:
    manifest_path = backup.dump.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text())
    manifest["row_counts"]["public.place"] += 1
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    ("damage", "name"),
    [(_damaged_in_the_dump, "digest-mismatch"), (_damaged_in_the_manifest, "row-counts-differ")],
)
def test_a_backup_that_fails_verification_leaves_no_marker(
    world, servers, tmp_path, monkeypatch, damage, name
):
    database = _copy(world, servers, tmp_path / "database")
    files, auto = _files(database), _auto_conf(database)

    def taken_then_damaged(*arguments, **keywords):
        backup = take_backup(*arguments, **keywords)
        damage(backup)
        return read_backup(backup.dump)

    monkeypatch.setattr(adopt_module, "take_backup", taken_then_damaged)

    result = _adopt(database)

    _refused(result, name)
    assert not (database.data / LOCAL_DATABASE_MARKER).exists()
    # Nothing of the cluster's own changed, the port included; the backup it took stays.
    assert (_files(database), _auto_conf(database)) == (files, auto)
    (dump,) = database.backups.glob("*.pgdump")
    assert dump.name.endswith("-adopt.pgdump")
    assert not database.cluster.running()
