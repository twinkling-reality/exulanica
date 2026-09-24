"""Where ``exulanica-local-db`` refuses to keep a database, and where the test servers refuse one.

Nothing here starts PostgreSQL: every refusal below is decided before ``initdb`` would run, and
each test checks that nothing was written. The tests that run servers are in
``tests/test_local_database_postgres.py``.

Each test is given a machine of its own (:func:`machine`): ``TMPDIR`` points at a directory in
this test's files, which the product reads as the system temporary directory exactly as it does on
a person's machine, so the test servers' base directory and every durable directory stay inside
this test's files.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from exulanica.api.services import READONLY_DATABASE_URL_ENV
from exulanica.db.account_roles import ACCOUNT_ROLE
from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV
from exulanica.db.local import cluster, locations
from exulanica.db.local.cli import CONNECTIONS, main
from exulanica.db.local.cluster import OWNER_FILE
from exulanica.db.local.database import LocalDatabase
from exulanica.db.local.locations import (
    CONVENTIONAL_TEMPORARY_DIRECTORIES,
    LOCAL_DATABASE_MARKER,
    base_for_scratch_servers,
    base_for_test_servers,
    refuse_location,
)
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.db.roles import EXECUTOR_ROLE, PURGE_ROLE, RUNTIME_ROLE
from exulanica.db.session import DATABASE_URL_ENV
from exulanica.deletion.cli import PURGE_DATABASE_URL_ENV

from conftest import _test_postgres_helper


@dataclass(frozen=True)
class Machine:
    temporary: Path
    durable: Path


def simulate_machine(root: Path, patch: pytest.MonkeyPatch) -> Machine:
    """A machine whose system temporary directory is ``root/system-temporary``.

    The conventional ``/tmp`` and ``/var/tmp`` are left out of it, because on Linux pytest keeps
    its own files under ``/tmp``; ``test_the_conventional_temporary_directories_are_refused``
    checks them with nothing patched.
    """
    temporary = root / "system-temporary"
    temporary.mkdir()
    patch.setenv("TMPDIR", str(temporary))
    patch.setattr(tempfile, "tempdir", None)
    patch.setattr(locations, "CONVENTIONAL_TEMPORARY_DIRECTORIES", ())
    assert Path(tempfile.gettempdir()) == temporary
    durable = root / "durable"
    durable.mkdir()
    return Machine(temporary=temporary, durable=durable)


@pytest.fixture
def machine(tmp_path, monkeypatch) -> Machine:
    return simulate_machine(tmp_path, monkeypatch)


@dataclass(frozen=True)
class Result:
    status: int
    out: str
    err: str


def cli(*arguments: object) -> Result:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err):
        status = main([str(argument) for argument in arguments], out)
    return Result(status, out.getvalue(), err.getvalue())


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


# ---------------------------------------------------------------------------------------------
# The local command refuses disposable locations
# ---------------------------------------------------------------------------------------------


def test_a_database_inside_the_system_temporary_directory_is_refused_and_nothing_is_written(
    machine,
):
    target = machine.temporary / "my-world"

    result = cli("init", "--directory", target)

    assert result.status == 2
    assert "refused (temporary-directory)" in result.err
    assert not target.exists()
    assert _tree(machine.temporary) == []


def test_the_conventional_temporary_directories_are_refused():
    assert {Path("/tmp"), Path("/var/tmp")} <= set(CONVENTIONAL_TEMPORARY_DIRECTORIES)
    for conventional in CONVENTIONAL_TEMPORARY_DIRECTORIES:
        target = conventional / "exulanica-local-db-never-created"
        with pytest.raises(LocalDatabaseRefused) as refused:
            refuse_location(target)
        assert refused.value.refusal is Refusal.TEMPORARY_DIRECTORY
        assert not target.exists()


def test_a_database_under_the_test_servers_directory_is_refused_by_that_name(machine):
    """The test directory is inside the temporary one; its own refusal says more, so it wins."""
    target = base_for_test_servers() / "lane-exulanica-0123456789ab"

    result = cli("init", "--directory", target)

    assert result.status == 2
    assert "refused (test-server-directory)" in result.err
    assert not base_for_test_servers().exists()


def test_a_durable_directory_outside_both_is_accepted(machine):
    """The positive control: the same check lets a person's own directory through."""
    target = machine.durable / "my-world"

    assert refuse_location(target) == target.resolve()


def test_init_never_writes_over_existing_files(machine):
    occupied = machine.durable / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("mine")

    result = cli("init", "--directory", occupied)

    assert result.status == 2
    assert "refused (existing-data)" in result.err
    assert _tree(occupied) == ["notes.txt"]
    assert (occupied / "notes.txt").read_text() == "mine"


def test_a_directory_the_local_command_did_not_make_is_refused(machine):
    stranger = machine.durable / "stranger"
    (stranger / "data").mkdir(parents=True)
    (stranger / "data" / "PG_VERSION").write_text("18\n")

    result = cli("start", "--directory", stranger)

    assert result.status == 2
    assert "refused (not-a-local-database)" in result.err

    (stranger / "data" / LOCAL_DATABASE_MARKER).write_text(json.dumps({"profile": "other/v1"}))
    with pytest.raises(LocalDatabaseRefused) as refused:
        LocalDatabase.open(stranger)
    assert refused.value.refusal is Refusal.NOT_A_LOCAL_DATABASE


# ---------------------------------------------------------------------------------------------
# The test servers refuse a local database
# ---------------------------------------------------------------------------------------------


def _mark_as_local_database(server) -> None:
    server.data.mkdir(parents=True)
    (server.data / LOCAL_DATABASE_MARKER).write_text("{}")


def test_the_test_tooling_names_the_directory_the_local_command_refuses(machine):
    assert _test_postgres_helper().base_directory() == base_for_test_servers()


def test_the_test_servers_state_no_postgresql_location_or_locale_of_their_own():
    """Where PostgreSQL is and the locale it runs in are stated once, in the product module.

    ``scripts/test_postgres.py`` reads both from ``exulanica.db.local.cluster``, so a test server
    and a person's local database cannot come to run different installations or orderings.
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "test_postgres.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "exulanica.db.local.cluster"
        for alias in node.names
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    stated_by_the_product = {cluster.LOCALE, *map(str, cluster.KNOWN_BINARY_DIRECTORIES)}

    assert {"LOCALE", "binaries"} <= imported
    assert not literals & stated_by_the_product


def test_the_restore_replay_test_finds_the_postgresql_client_through_the_product():
    """``tests/test_restore_replay.py`` asks the product for ``pg_dump`` and ``psql``."""
    replay = Path(__file__).resolve().parent / "test_restore_replay.py"
    tree = ast.parse(replay.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "exulanica.db.local.cluster"
        for alias in node.names
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "client_program" in imported
    assert not literals & set(map(str, cluster.KNOWN_BINARY_DIRECTORIES))


def _program(directory: Path, name: str, version: str) -> Path:
    """A stand-in for a PostgreSQL program that reports ``version``."""
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / name
    program.write_text(f"#!/bin/sh\necho '{name} (PostgreSQL) {version}'\n")
    program.chmod(0o755)
    return program


def _only_these_places(monkeypatch, configured: Path, on_path: Path) -> None:
    monkeypatch.setenv(cluster.POSTGRES_BIN_ENV, str(configured))
    monkeypatch.setenv("PATH", str(on_path))
    monkeypatch.setattr(cluster, "KNOWN_BINARY_DIRECTORIES", ())


def test_a_client_program_is_found_where_the_server_is_and_an_older_one_is_passed_over(
    tmp_path, monkeypatch
):
    configured, on_path = tmp_path / "configured", tmp_path / "on-path"
    _program(configured, "pg_dump", "16.4")
    newer = _program(on_path, "pg_dump", "18.6")
    _only_these_places(monkeypatch, configured, on_path)

    assert cluster.client_program("pg_dump") == str(newer)


def test_no_client_program_new_enough_is_refused_naming_what_was_checked(tmp_path, monkeypatch):
    configured, on_path = tmp_path / "configured", tmp_path / "on-path"
    older = _program(configured, "psql", "16.4")
    on_path.mkdir()
    _only_these_places(monkeypatch, configured, on_path)

    with pytest.raises(LocalDatabaseRefused) as refused:
        cluster.client_program("psql")

    assert refused.value.refusal is Refusal.POSTGRES_MISSING
    assert f"{older}: psql (PostgreSQL) 16.4" in refused.value.detail


def test_serve_and_start_refuse_a_data_directory_the_local_command_made(machine):
    helper = _test_postgres_helper()
    server = helper.lane_server()
    assert server.root.is_relative_to(machine.temporary)
    _mark_as_local_database(server)

    with pytest.raises(RuntimeError, match="local database made by exulanica-local-db"):
        helper.serve(io.StringIO())
    with pytest.raises(RuntimeError, match="local database made by exulanica-local-db"):
        server.start()

    assert _tree(server.root) == ["data", f"data/{LOCAL_DATABASE_MARKER}"]
    unmarked = helper.Server(machine.temporary / "unmarked")
    helper.refuse_local_database(unmarked)


def _exited_process() -> int:
    child = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    child.wait()
    return child.pid


def test_sweep_never_deletes_a_local_database(machine):
    helper = _test_postgres_helper()
    marked = helper.Server(helper.base_directory() / "worker-gw0-1-aaaaaa")
    unmarked = helper.Server(helper.base_directory() / "worker-gw1-2-bbbbbb")
    _mark_as_local_database(marked)
    unmarked.data.mkdir(parents=True)
    for server in (marked, unmarked):
        (server.root / "owner.pid").write_text(str(_exited_process()))

    removed = helper.sweep()

    assert removed == [unmarked.root]
    assert not unmarked.root.exists()
    assert (marked.data / LOCAL_DATABASE_MARKER).is_file()


# ---------------------------------------------------------------------------------------------
# What the command prints is what the application reads
# ---------------------------------------------------------------------------------------------


def test_the_connections_printed_are_the_variables_and_roles_the_application_reads():
    assert dict(CONNECTIONS) == {
        DATABASE_URL_ENV: RUNTIME_ROLE,
        READONLY_DATABASE_URL_ENV: EXECUTOR_ROLE,
        PURGE_DATABASE_URL_ENV: PURGE_ROLE,
        ACCOUNT_DATABASE_URL_ENV: ACCOUNT_ROLE,
    }


# ---------------------------------------------------------------------------------------------
# A scratch copy of a world never outlives a run that was killed
# ---------------------------------------------------------------------------------------------


def _scratch_copy(name: str, owner: int, *, marked: bool = False) -> Path:
    root = base_for_scratch_servers() / name
    (root / "data").mkdir(parents=True)
    (root / OWNER_FILE).write_text(str(owner))
    if marked:
        (root / "data" / LOCAL_DATABASE_MARKER).write_text("{}")
    return root


def test_every_command_first_removes_scratch_copies_whose_owner_has_exited(machine):
    """A copy that a killed verify or upgrade left behind goes at the next command of any kind."""
    orphan = _scratch_copy("orphan", _exited_process())
    in_use = _scratch_copy("in-use", os.getpid())
    marked = _scratch_copy("marked", _exited_process(), marked=True)

    result = cli("status", "--directory", machine.durable / "absent")

    assert "refused (not-a-local-database)" in result.err
    assert not orphan.exists()
    assert in_use.is_dir()
    assert marked.is_dir()
