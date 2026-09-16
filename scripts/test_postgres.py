"""Private PostgreSQL 18 servers: one per test process, and one per worktree for the API.

A whole server, not a schema and not a database, because each smaller unit shares something a
parallel run collides on. Measured 2026-09-16 against the shared server on port 5433:

*   **A schema shares advisory locks.** Migration 0041's ``asset_read_lock()`` held in one
    throwaway schema made a guarded ``insert into blob`` in another schema of the same database
    fail at once with "asset delivery in progress; retry mutation". Advisory locks are scoped to
    the database.
*   **A database shares roles.** The same insert in a second database succeeded, but
    ``provision_runtime_role`` run 40 times from each of two databases on one server failed 40
    times in 80 with "tuple concurrently updated" or a duplicate ``pg_authid`` key. Roles are
    cluster-wide, and the lock ``provision_runtime_role`` takes is a database-scoped advisory lock.
*   **A server shares checkpoints.** A ``DROP DATABASE`` waited over six minutes on
    ``CheckpointDone`` while other worktrees ran their suites on the same server.

A private server costs about a second (initdb 0.5 s, start 0.15 s, stop 0.13 s, 26 MB resident),
so every test process initialises a fresh one and deletes it at exit. Nothing is shared between
two processes except the disk.

The suite uses this through ``tests/conftest.py``::

    EXULANICA_TEST_POSTGRES=private uv run pytest -n 6

For running the API against a database of its own, one server per worktree persists between
commands, and the application connects as the non-owner runtime role, never as the superuser::

    uv run python scripts/test_postgres.py serve    # start, migrate, provision roles, print URLs
    uv run python scripts/test_postgres.py status
    uv run python scripts/test_postgres.py stop
    uv run python scripts/test_postgres.py sweep    # remove test servers whose process has exited

The binaries are PostgreSQL 18, found the way ``tests/test_restore_replay.py`` finds them:
``EXULANICA_POSTGRES_BIN`` first, then the Homebrew and Debian locations, then ``PATH``. An
older server is refused rather than used, because the schema needs ``uuidv7()``.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Created in ``public`` of every database this makes, as the bootstrap superuser, before any
#: test or migration runs. pgvector is not a trusted extension, so a non-superuser could not.
EXTENSIONS = ("vector", "pgcrypto", "pg_trgm", "btree_gist")

#: Matches the shared 5433 server, so a result here means what it means there. The locale
#: decides text ordering, and the collation of every database is fixed when initdb runs.
LOCALE = "en_US.UTF-8"

#: Server settings. The first two match 5433 explicitly rather than trusting initdb's probe.
#: ``fsync`` and ``full_page_writes`` are durability against a machine crash, for a cluster that
#: is deleted when the process exits; no query sees them, and turning them off keeps parallel
#: servers from queuing on the disk the way the shared server's checkpoints did.
SETTINGS = {
    "max_connections": "100",
    "shared_buffers": "128MB",
    "fsync": "off",
    "full_page_writes": "off",
    "listen_addresses": "localhost",
    # TCP only. A socket path under $TMPDIR is longer than the 103 bytes macOS allows.
    "unix_socket_directories": "",
}

_MINIMUM_MAJOR = 18
_OWNER_FILE = "owner.pid"


def base_directory() -> Path:
    """Every server this module makes lives under here, so ``sweep`` can find all of them."""
    return Path(tempfile.gettempdir()) / "exulanica-test-postgres"


@functools.cache
def binaries() -> Path:
    """The directory holding PostgreSQL 18's ``initdb``, ``pg_ctl`` and ``postgres``."""
    configured = os.environ.get("EXULANICA_POSTGRES_BIN")
    candidates = [Path(configured)] if configured else []
    candidates += [
        Path("/opt/homebrew/opt/postgresql@18/bin"),
        Path("/usr/local/opt/postgresql@18/bin"),
        Path("/usr/lib/postgresql/18/bin"),
    ]
    located = shutil.which("postgres")
    if located:
        candidates.append(Path(located).parent)
    seen = []
    for directory in candidates:
        if not (directory / "initdb").is_file() or not (directory / "pg_ctl").is_file():
            continue
        version = subprocess.run(
            [str(directory / "postgres"), "--version"], capture_output=True, text=True, check=False
        ).stdout
        seen.append(f"{directory}: {version.strip() or 'unreadable'}")
        found = re.search(r"\(PostgreSQL\) (\d+)", version)
        if found and int(found.group(1)) >= _MINIMUM_MAJOR:
            return directory
    raise RuntimeError(
        f"no PostgreSQL {_MINIMUM_MAJOR} server binaries found; set EXULANICA_POSTGRES_BIN. "
        f"Checked: {'; '.join(seen) or 'nothing with initdb and pg_ctl'}"
    )


def _environment() -> dict[str, str]:
    # A postmaster started without LC_ALL on macOS refuses with "postmaster became
    # multithreaded during startup". The PG variables would redirect initdb or pg_ctl.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    environment["LC_ALL"] = LOCALE
    return environment


def _free_port() -> int:
    """A port free on both loopback families, because ``localhost`` listens on both."""
    for _ in range(100):
        with socket.socket(socket.AF_INET) as four:
            four.bind(("127.0.0.1", 0))
            port = four.getsockname()[1]
        try:
            with socket.socket(socket.AF_INET6) as six:
                six.bind(("::1", port))
        except OSError:
            continue
        return port
    raise RuntimeError("no free loopback port")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class Server:
    """One initialised cluster under ``root``. ``root/data`` is the data directory."""

    root: Path
    port: int = 0

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def log(self) -> Path:
        return self.root / "server.log"

    def url(self, database: str, user: str | None = None) -> str:
        who = f"{user}@" if user else ""
        return f"postgresql://{who}localhost:{self.port}/{database}"

    def _pg_ctl(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(binaries() / "pg_ctl"), "-D", str(self.data), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=_environment(),
        )

    def initialise(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                str(binaries() / "initdb"),
                "-D",
                str(self.data),
                "--auth=trust",
                "--encoding=UTF8",
                f"--locale={LOCALE}",
                "--no-sync",
                "--no-instructions",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_environment(),
        )
        if completed.returncode != 0:
            raise RuntimeError(f"initdb failed in {self.data}:\n{completed.stderr}")

    def running(self) -> bool:
        return self._pg_ctl("status").returncode == 0

    def start(self, port: int | None = None) -> None:
        """Start on ``port``, or on a free one, retrying when another process takes it first."""
        attempts = [port] if port else [None] * 5
        failure = ""
        for wanted in attempts:
            self.port = wanted or _free_port()
            options = " ".join(
                f"-c {key}={value}" if value else f"-c {key}=''" for key, value in SETTINGS.items()
            )
            completed = self._pg_ctl(
                "start", "-w", "-t", "120", "-l", str(self.log), "-o", f"-p {self.port} {options}"
            )
            if completed.returncode == 0:
                (self.root / "port").write_text(str(self.port))
                return
            failure = completed.stderr + self.log.read_text(errors="replace")[-2000:]
        raise RuntimeError(f"PostgreSQL did not start in {self.data}:\n{failure}")

    def stop(self) -> None:
        if not self.data.is_dir() or not (self.data / "postmaster.pid").exists():
            return
        if self._pg_ctl("stop", "-w", "-t", "60", "-m", "fast").returncode != 0:
            self._pg_ctl("stop", "-w", "-t", "60", "-m", "immediate")

    def create_database(self, name: str) -> str:
        """Create ``name`` with the required extensions, and return its superuser URL."""
        import psycopg
        from psycopg import sql

        with psycopg.connect(self.url("postgres"), autocommit=True) as connection:
            exists = connection.execute(
                "select 1 from pg_database where datname = %s", (name,)
            ).fetchone()
            if exists is None:
                connection.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        url = self.url(name)
        with psycopg.connect(url, autocommit=True) as connection:
            for extension in EXTENSIONS:
                connection.execute(
                    sql.SQL("create extension if not exists {} with schema public").format(
                        sql.Identifier(extension)
                    )
                )
        return url


# ---------------------------------------------------------------------------------------------
# One server per test process
# ---------------------------------------------------------------------------------------------


def start_test_server(label: str) -> tuple[Server, str]:
    """Initialise and start a server owned by this process; return it and its test database URL.

    The database name contains "test" because ``tests/pg_harness.py`` refuses any other.
    """
    sweep()
    token = f"{label}-{os.getpid()}-{secrets.token_hex(3)}"
    server = Server(base_directory() / f"worker-{token}")
    server.root.mkdir(parents=True)
    (server.root / _OWNER_FILE).write_text(str(os.getpid()))
    try:
        server.initialise()
        server.start()
        _watch_owner(server, os.getpid())
        url = server.create_database(f"exulanica_{label}_test")
    except BaseException:
        remove_test_server(server)
        raise
    return server, url


def _watch_owner(server: Server, owner: int) -> None:
    """Stop and delete ``server`` when ``owner`` exits, however it exits.

    A worker that aborts (exit 134 after torch meets pycolmap) or is killed never runs its own
    cleanup, and its postmaster would otherwise keep running until the next ``sweep``.
    """
    watch = (
        f"while kill -0 {owner} 2>/dev/null; do sleep 1; done; "
        f'"{binaries() / "pg_ctl"}" -D "{server.data}" -m immediate -w stop >/dev/null 2>&1; '
        f'rm -rf "{server.root}"'
    )
    # The outer shell backgrounds the watcher and exits at once, so nothing is left for this
    # process to reap and no ResourceWarning joins the suite's warning summary.
    subprocess.run(
        ["/bin/sh", "-c", f"({watch}) </dev/null >/dev/null 2>&1 &"],
        env=_environment(),
        start_new_session=True,
        check=True,
    )


def remove_test_server(server: Server) -> None:
    server.stop()
    shutil.rmtree(server.root, ignore_errors=True)


def sweep() -> list[Path]:
    """Stop and delete every test server whose owning process has exited.

    A worker killed outright never reaches its own cleanup. Only ``worker-*`` directories are
    candidates, and only when the process that wrote ``owner.pid`` is gone, so a sweep started
    by one worktree never touches a server another worktree's live run is using.
    """
    removed = []
    base = base_directory()
    if not base.is_dir():
        return removed
    for root in sorted(base.glob("worker-*")):
        try:
            owner = int((root / _OWNER_FILE).read_text())
        except (OSError, ValueError):
            continue
        if _alive(owner):
            continue
        server = Server(root)
        with contextlib.suppress(Exception):
            server.stop()
        shutil.rmtree(root, ignore_errors=True)
        removed.append(root)
    return removed


# ---------------------------------------------------------------------------------------------
# One server per worktree, for the API
# ---------------------------------------------------------------------------------------------

LANE_DATABASE = "exulanica"


def lane_server(worktree: Path = ROOT) -> Server:
    key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:12]
    server = Server(base_directory() / f"lane-{worktree.name}-{key}")
    port_file = server.root / "port"
    if port_file.is_file():
        server.port = int(port_file.read_text())
    return server


def serve(stream=sys.stdout) -> int:
    """Start this worktree's server, migrate it, provision the runtime roles, print the URLs."""
    import psycopg
    from psycopg.rows import dict_row

    from exulanica.db.cli import provision
    from exulanica.db.roles import RUNTIME_ROLE, assert_runtime_role

    server = lane_server()
    if not server.data.is_dir():
        server.initialise()
    if not server.running():
        server.start(server.port or None)
    owner = server.create_database(LANE_DATABASE)

    # exulanica-db, run exactly as the setup guide says: as the bootstrap owner that also
    # applies the migrations, so default privileges cover every table a migration adds.
    previous = os.environ.get("EXULANICA_DATABASE_URL")
    os.environ["EXULANICA_DATABASE_URL"] = owner
    try:
        provision(stream)
    finally:
        if previous is None:
            os.environ.pop("EXULANICA_DATABASE_URL", None)
        else:
            os.environ["EXULANICA_DATABASE_URL"] = previous

    runtime = server.url(LANE_DATABASE, RUNTIME_ROLE)
    with psycopg.connect(runtime, row_factory=dict_row) as connection:
        assert_runtime_role(connection)
        who = connection.execute("select session_user, current_user").fetchone()
    print(f"runtime role check: {who['session_user']} is not an owner, superuser or BYPASSRLS",
          file=stream)
    print(f"server   {server.data} on port {server.port}", file=stream)
    print(f"owner    {owner}   (migrations and provisioning only)", file=stream)
    print(f"export EXULANICA_DATABASE_URL={runtime}", file=stream)
    print(f"export EXULANICA_READONLY_DATABASE_URL={server.url(LANE_DATABASE, 'exulanica_ro')}",
          file=stream)
    print(f"export EXULANICA_PURGE_DATABASE_URL={server.url(LANE_DATABASE, 'exulanica_purge')}",
          file=stream)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("serve", "status", "stop", "sweep"))
    command = parser.parse_args(argv).command
    if command == "serve":
        return serve()
    if command == "sweep":
        for root in sweep():
            print(f"removed {root}")
        return 0
    server = lane_server()
    if command == "stop":
        server.stop()
        print(f"stopped {server.data}")
        return 0
    state = "running" if server.data.is_dir() and server.running() else "stopped"
    print(f"{state}  {server.data}  port {server.port or '-'}")
    workers = sorted(base_directory().glob("worker-*")) if base_directory().is_dir() else []
    print(f"test servers on this machine: {len(workers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
