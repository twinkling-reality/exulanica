"""``exulanica-local-db`` against real PostgreSQL 18 servers it starts itself.

Every test here drives the command the way a person does, through :func:`main`, on durable
clusters in this test's own files, and checks what is on disk and in the database afterwards:
that a backup restores to the row counts its manifest records, that a stop takes a backup and a
start never migrates, that an upgrade takes a backup before and after, that a failed rehearsal
leaves the real database untouched, that a migration without a fresh backup is refused, that a
restore refuses a location that holds anything and stops what it made when its copy is wrong, and
that a scratch copy of a world never outlives a run that was killed.

The servers need PostgreSQL 18's own binaries, not a database URL, so the tests run wherever the
suite may start private servers and skip, saying so, where it may not. Every cluster a test starts
is stopped when the test ends, and a watcher stops it if this process dies first.

Migration sets are varied by pointing :func:`exulanica.migrations.migration_directory` at a copy of
the package's own files: without its last file, to stand for a database behind the code, or with
one more that fails, to stand for a migration that would break it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from exulanica import migrations as migration_package
from exulanica.db.local import cluster
from exulanica.db.local.backup import (
    check_digest,
    list_backups,
    row_counts,
    take_backup,
    verify_backup,
)
from exulanica.db.local.database import LocalDatabase, applied_versions
from exulanica.db.local.locations import SCRATCH_DIRECTORY_NAME, base_for_scratch_servers
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.local.upgrade import migrate, rehearse
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import RUNTIME_ROLE
from exulanica.db.session import Database
from exulanica.env import env_get, env_name
from exulanica.migrations import migrations

from conftest import _test_postgres_helper
from test_local_database import Machine, _exited_process, cli, simulate_machine

pytestmark = pytest.mark.postgres

#: Rows a person made, written as the owner into tables the application writes: how many each.
PERSON_ROWS = {"public.account_workspace": 1, "public.intake_batch": 3, "public.place": 2}

#: How long a scratch copy's watcher may take to stop and remove it after its owner is killed:
#: one poll of ``WATCH_INTERVAL_SECONDS`` plus an immediate stop, with room for a loaded machine.
WATCHER_DEADLINE_SECONDS = 30


def _require_server_binaries() -> None:
    try:
        cluster.binaries()
    except LocalDatabaseRefused as missing:
        if env_get("TEST_POSTGRES"):
            pytest.fail(f"{env_name('TEST_POSTGRES')} is set: {missing.detail}")
        pytest.skip(
            f"no PostgreSQL {cluster.MINIMUM_MAJOR} server binaries were found, and these tests "
            "start servers of their own"
        )


@dataclass
class Servers:
    """The local databases a test made, so each is stopped when the test ends."""

    roots: list[Path]

    def track(self, root: Path) -> LocalDatabase:
        database = LocalDatabase.open(root)
        self.roots.append(database.root)
        _stop_when_this_process_exits(database)
        return database

    def stop_all(self) -> None:
        for root in self.roots:
            with contextlib.suppress(Exception):
                LocalDatabase(root).cluster.stop()


def _stop_when_this_process_exits(database: LocalDatabase) -> None:
    """A test process that is killed never reaches its teardown; this stops the server then."""
    pg_ctl = cluster.binaries().program("pg_ctl")
    watch = (
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 1; done; "
        f'"{pg_ctl}" -D "{database.data}" -m immediate -w stop >/dev/null 2>&1'
    )
    subprocess.run(
        ["/bin/sh", "-c", f"({watch}) </dev/null >/dev/null 2>&1 &"],
        env=cluster.environment(),
        start_new_session=True,
        check=True,
    )


@pytest.fixture(scope="module")
def module_machine(tmp_path_factory) -> Iterator[Machine]:
    _require_server_binaries()
    with pytest.MonkeyPatch.context() as patch:
        yield simulate_machine(tmp_path_factory.mktemp("local-database"), patch)


@pytest.fixture
def servers(module_machine) -> Iterator[Servers]:
    made = Servers(roots=[])
    yield made
    made.stop_all()


@contextlib.contextmanager
def migration_files(directory: Path, *, drop_last: int = 0, extra: dict[str, str] | None = None):
    """Point the migration set at a copy of the package's files, less or more than it holds."""
    real = list(migrations())
    kept = real[: len(real) - drop_last]
    directory.mkdir()
    for migration in kept:
        shutil.copyfile(migration.path, directory / migration.path.name)
    for name, text in (extra or {}).items():
        (directory / name).write_text(text, encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(migration_package, "migration_directory", lambda: directory)
        yield [migration.version for migration in kept]


def _init(servers: Servers, directory: Path) -> LocalDatabase:
    result = cli("init", "--directory", directory)
    assert result.status == 0, result.err
    return servers.track(directory)


def _write_person_rows(database: LocalDatabase) -> None:
    port = database.cluster.running_port()
    user, workspace = uuid.uuid4(), uuid.uuid4()
    with database.connect(port) as connection, connection.transaction():
        connection.execute(
            "insert into account_user (user_id, actor_id) values (%s, %s)", (user, uuid.uuid4())
        )
        connection.execute(
            "insert into account_workspace (workspace_id, owner_user_id) values (%s, %s)",
            (workspace, user),
        )
        for _ in range(PERSON_ROWS["public.intake_batch"]):
            connection.execute("insert into intake_batch (workspace_id) values (%s)", (workspace,))
        for _ in range(PERSON_ROWS["public.place"]):
            connection.execute("insert into place (workspace_id) values (%s)", (workspace,))


def _state(database: LocalDatabase) -> tuple[list[str], dict[str, int]]:
    with database.connect(database.cluster.running_port()) as connection:
        return applied_versions(connection), row_counts(connection)


def _scratch_left(machine: Machine) -> list[Path]:
    base = machine.temporary / SCRATCH_DIRECTORY_NAME
    return sorted(base.iterdir()) if base.is_dir() else []


@pytest.fixture(scope="module")
def world(module_machine, tmp_path_factory) -> Iterator[LocalDatabase]:
    """A person's world: migrated, with rows of their own, stopped, and so backed up once."""
    made = Servers(roots=[])
    try:
        database = _init(made, tmp_path_factory.mktemp("world") / "database")
        _write_person_rows(database)
        stopped = cli("stop", "--directory", database.root)
        assert stopped.status == 0, stopped.err
        yield database
    finally:
        made.stop_all()


def _only_backup(database: LocalDatabase, reason: str):
    found = [
        backup
        for backup in list_backups(database.backups)
        if backup.dump.name.endswith(f"-{reason}.pgdump")
    ]
    assert len(found) == 1, [backup.dump.name for backup in list_backups(database.backups)]
    return found[0]


# ---------------------------------------------------------------------------------------------


def test_the_local_command_runs_the_postgresql_the_test_servers_run(module_machine):
    helper = _test_postgres_helper()
    assert cluster.binaries().directory == helper.binaries()
    assert cluster.LOCALE == helper.LOCALE


def test_a_backup_restores_to_the_row_counts_its_manifest_records(
    world, module_machine, servers, tmp_path
):
    backup = _only_backup(world, "stop")
    for name, rows in PERSON_ROWS.items():
        assert backup.row_counts[name] == rows

    verified = cli("verify", "--directory", world.root)
    assert verified.status == 0, verified.err
    assert f"restorable: {backup.dump}" in verified.out
    assert _scratch_left(module_machine) == []

    restored_at = tmp_path / "restored"
    restored = cli("restore", "--directory", restored_at, backup.dump)
    assert restored.status == 0, restored.err
    copy = servers.track(restored_at)
    assert copy.cluster.running_port() == backup.service_port
    versions, counts = _state(copy)
    assert counts == backup.row_counts
    assert tuple(versions) == backup.migrations
    marker = copy.read_marker()
    assert (marker["created_by"], marker["restored_from"]["sha256"]) == ("restore", backup.sha256)
    with psycopg.connect(copy.role_url(copy.cluster.running_port(), RUNTIME_ROLE)) as runtime:
        assert runtime.execute("select current_user").fetchone() == (RUNTIME_ROLE,)


def _copy_backup(backup, directory: Path, *, one_more_place: bool = False) -> Path:
    """Copy a backup's dump and manifest, the manifest claiming one place more if asked."""
    copy = directory / backup.dump.name
    shutil.copyfile(backup.dump, copy)
    manifest = json.loads(backup.dump.with_suffix(".json").read_text())
    if one_more_place:
        manifest["row_counts"]["public.place"] += 1
    copy.with_suffix(".json").write_text(json.dumps(manifest))
    return copy


def test_verify_refuses_a_dump_whose_bytes_changed(world, module_machine, tmp_path):
    copy = _copy_backup(_only_backup(world, "stop"), tmp_path)
    damaged = bytearray(copy.read_bytes())
    damaged[len(damaged) // 2] ^= 0xFF
    copy.write_bytes(bytes(damaged))

    result = cli("verify", copy)

    assert result.status == 2
    assert "refused (digest-mismatch)" in result.err
    assert _scratch_left(module_machine) == []


def test_verify_refuses_a_backup_that_restores_other_counts_than_its_manifest(
    world, module_machine, tmp_path
):
    copy = _copy_backup(_only_backup(world, "stop"), tmp_path, one_more_place=True)

    result = cli("verify", copy)

    assert result.status == 2
    assert "refused (row-counts-differ)" in result.err
    assert "public.place: manifest 3, restored 2" in result.err
    assert _scratch_left(module_machine) == []


def test_a_restore_that_disagrees_with_its_manifest_fails_and_leaves_nothing_running(
    world, servers, tmp_path
):
    copy = _copy_backup(_only_backup(world, "stop"), tmp_path, one_more_place=True)
    target = tmp_path / "restored"

    result = cli("restore", "--directory", target, "--port", _free_port(), copy)
    restored = servers.track(target)

    assert result.status == 1
    assert "failed (restore-failed): row-counts-differ: " in result.err
    assert "public.place: manifest 3, restored 2" in result.err
    assert "remove it before trying again" in result.err
    assert not restored.cluster.running()


def test_a_restore_refuses_a_location_that_holds_anything(world, servers, tmp_path):
    backup = _only_backup(world, "stop")
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("mine")
    marker_before = world.marker.read_bytes()
    backups_before = sorted(path.name for path in world.backups.iterdir())

    into_files = cli("restore", "--directory", occupied, backup.dump)
    into_a_database = cli("restore", "--directory", world.root, backup.dump)

    for refused in (into_files, into_a_database):
        assert refused.status == 2
        assert "refused (existing-data)" in refused.err
    assert sorted(path.name for path in occupied.iterdir()) == ["notes.txt"]
    assert world.marker.read_bytes() == marker_before
    assert sorted(path.name for path in world.backups.iterdir()) == backups_before

    empty = tmp_path / "empty"
    empty.mkdir()
    accepted = cli("restore", "--directory", empty, "--port", _free_port(), backup.dump)
    assert accepted.status == 0, accepted.err
    servers.track(empty)


def test_stop_takes_a_backup_and_start_never_migrates(servers, tmp_path):
    with migration_files(tmp_path / "older-code", drop_last=1) as older:
        database = _init(servers, tmp_path / "database")
    pending = next(m.version for m in migrations() if m.version not in older)

    stopped = cli("stop", "--directory", database.root)
    assert stopped.status == 0, stopped.err
    backup = _only_backup(database, "stop")
    check_digest(backup)
    assert list(backup.migrations) == older
    assert not database.cluster.running()

    started = cli("start", "--directory", database.root)
    assert started.status == 0, started.err
    assert f"1 pending ({pending})" in started.out
    versions, _ = _state(database)
    assert versions == older


def test_an_upgrade_takes_a_backup_before_and_after(servers, module_machine, tmp_path):
    with migration_files(tmp_path / "older-code", drop_last=1) as older:
        database = _init(servers, tmp_path / "database")
    port = database.cluster.running_port()
    _write_person_rows(database)
    _, counts_before = _state(database)

    result = cli("upgrade", "--directory", database.root)

    assert result.status == 0, result.err
    before = _only_backup(database, "before-upgrade")
    after = _only_backup(database, "after-upgrade")
    for backup in (before, after):
        check_digest(backup)
    assert list(before.migrations) == older
    assert before.row_counts == counts_before
    assert after.migrations == tuple(m.version for m in migrations())
    assert database.cluster.running() and database.cluster.running_port() == port
    versions, counts_after = _state(database)
    assert tuple(versions) == after.migrations
    assert {name: counts_after[name] for name in PERSON_ROWS} == PERSON_ROWS
    verify_schema(Database(url=database.owner_url(port)))
    assert _scratch_left(module_machine) == []

    assert verify_backup(before) == before.row_counts


def test_a_failed_rehearsal_leaves_the_real_database_untouched(servers, module_machine, tmp_path):
    database = _init(servers, tmp_path / "database")
    port = database.cluster.running_port()
    _write_person_rows(database)
    versions_before, counts_before = _state(database)
    last = list(migrations())[-1].version
    failing = {
        f"{int(last) + 1:04d}_commits_a_table_then_fails.sql": (
            "begin;\ncreate table rehearsal_probe (id integer);\ncommit;\nselect 1 / 0;\n"
        )
    }

    with migration_files(tmp_path / "newer-code", extra=failing):
        result = cli("upgrade", "--directory", database.root)

    assert result.status == 2
    assert "refused (rehearsal-failed)" in result.err
    assert "division by zero" in result.err
    assert database.cluster.running() and database.cluster.running_port() == port
    versions_after, counts_after = _state(database)
    assert (versions_after, counts_after) == (versions_before, counts_before)
    with database.connect(port) as connection:
        probe = connection.execute("select to_regclass('public.rehearsal_probe') as probe")
        assert probe.fetchone() == {"probe": None}
    assert _only_backup(database, "before-upgrade").migrations == tuple(versions_before)
    assert not [b for b in list_backups(database.backups) if "after-upgrade" in b.dump.name]
    assert _scratch_left(module_machine) == []


def test_a_migration_without_a_fresh_backup_is_refused(servers, tmp_path):
    with migration_files(tmp_path / "older-code", drop_last=1) as older:
        database = _init(servers, tmp_path / "database")
    taken_while_serving = cli("backup", "--directory", database.root, "--reason", "earlier")
    assert taken_while_serving.status == 0, taken_while_serving.err
    earlier = _only_backup(database, "earlier")

    with database.maintenance() as session:
        stale = rehearse(earlier)
        assert stale.passed, stale.failure
        with pytest.raises(LocalDatabaseRefused) as refused:
            migrate(session, stale)
        assert refused.value.refusal is Refusal.NO_FRESH_BACKUP
        with database.connect(session.port) as connection:
            assert applied_versions(connection) == older

        fresh = rehearse(take_backup(database, session.port, "fresh"))
        applied, after = migrate(session, fresh)
    assert list(applied) == [m.version for m in migrations() if m.version not in older]
    assert after.migrations == tuple(m.version for m in migrations())


def test_an_upgrade_refuses_while_the_application_is_connected(servers, tmp_path):
    database = _init(servers, tmp_path / "database")
    port = database.cluster.running_port()
    backups_before = sorted(path.name for path in database.backups.iterdir())

    with psycopg.connect(database.role_url(port, RUNTIME_ROLE)) as application:
        result = cli("upgrade", "--directory", database.root)
        assert application.execute("select 1").fetchone() == (1,)

    assert result.status == 2
    assert "refused (in-use)" in result.err
    assert RUNTIME_ROLE in result.err
    assert database.cluster.running() and database.cluster.running_port() == port
    assert sorted(path.name for path in database.backups.iterdir()) == backups_before


def test_the_test_tooling_refuses_a_local_database_reached_through_a_link(servers, tmp_path):
    """The shape of the loss this command exists for: a test path that leads to real data."""
    database = _init(servers, tmp_path / "database")
    versions_before, counts_before = _state(database)
    helper = _test_postgres_helper()
    lane = helper.lane_server()
    lane.root.parent.mkdir(parents=True, exist_ok=True)
    lane.root.symlink_to(database.root, target_is_directory=True)

    with pytest.raises(RuntimeError, match="local database made by exulanica-local-db"):
        helper.serve(io.StringIO())

    assert _state(database) == (versions_before, counts_before)
    assert not (database.root / "port").exists()
    assert database.marker.is_file()


def _free_port() -> int:
    return cluster._free_port()


def test_a_scratch_copy_is_stopped_and_removed_when_its_owner_is_killed(module_machine):
    """A verify or rehearsal killed outright must not leave a running copy of a world behind."""
    owner = (
        "import os, signal\n"
        "from exulanica.db.local.cluster import bootstrap_user, scratch_cluster\n"
        "with scratch_cluster(owner=bootstrap_user()) as (copy, port):\n"
        "    print(copy.data.parent, port, flush=True)\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", owner],
        env={**os.environ, "TMPDIR": str(module_machine.temporary)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stderr is not None
    announced = child.stdout.readline().split()
    assert child.wait() == -signal.SIGKILL, child.stderr.read()
    root, port = Path(announced[0]), int(announced[1])
    assert root.is_relative_to(base_for_scratch_servers())

    deadline = time.monotonic() + WATCHER_DEADLINE_SECONDS
    while (root.exists() or not cluster.port_is_free(port)) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not root.exists()
    assert cluster.port_is_free(port)


def test_the_next_command_stops_a_copy_whose_owner_and_watcher_are_both_gone(module_machine):
    """What a restart that kills every process leaves: a running copy that nothing watches."""
    root = base_for_scratch_servers() / "left-by-a-restart"
    root.mkdir(parents=True)
    (root / cluster.OWNER_FILE).write_text(str(_exited_process()))
    orphan = cluster.Cluster(data=root / "data", log=root / "server.log")
    orphan.initialise(owner=cluster.bootstrap_user(), durable=False)
    port = orphan.start_on_a_free_port(cluster.SCRATCH_SETTINGS)
    try:
        result = cli("status", "--directory", module_machine.durable / "absent")

        assert "refused (not-a-local-database)" in result.err
        assert not root.exists()
        assert cluster.port_is_free(port)
    finally:
        if root.exists():
            orphan.stop(immediate_after_fast=True)
