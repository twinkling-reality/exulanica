"""The PostgreSQL processes behind a local database: its durable cluster and scratch copies.

A :class:`Cluster` is one PostgreSQL data directory and its server log, driven through the
PostgreSQL 18 binaries with ``initdb`` and ``pg_ctl``. Two kinds are made here:

*   **Durable.** A personal install's own cluster. ``fsync``, ``full_page_writes`` and
    ``synchronous_commit`` are left at PostgreSQL's defaults, which is what survives a crash or a
    power cut, and ``initdb`` syncs what it writes. Nothing in this module turns durability off
    for it.
*   **Scratch.** A copy a backup is restored into so it can be verified or rehearsed on, under
    :func:`~exulanica.db.local.locations.base_for_scratch_servers`, and deleted when the step
    ends. Durability protects against a machine crash and a scratch copy is deleted either way,
    so it runs the way the test servers in ``scripts/test_postgres.py`` do.

Every cluster listens on the loopback interface only, over TCP, with no socket file: it is never
reachable from another machine, and no socket path can exceed the 103 bytes macOS allows. It
trusts every connection from this computer, as a default Homebrew install does, so it is not a
boundary between the people who log in to one computer.
"""

from __future__ import annotations

import contextlib
import functools
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from exulanica.db.local.locations import LOCAL_DATABASE_MARKER, base_for_scratch_servers
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.env import env_name

__all__ = [
    "LOCALE",
    "MINIMUM_MAJOR",
    "OWNER_FILE",
    "POSTGRES_BIN_ENV",
    "Binaries",
    "Cluster",
    "binaries",
    "bootstrap_user",
    "port_is_free",
    "scratch_cluster",
    "sweep_scratch",
]

#: ``uuidv7()``, which the schema calls, is a PostgreSQL 18 built-in.
MINIMUM_MAJOR: Final = 18

#: The locale every cluster here and every test server is initialised with, the one the shared
#: reference server on port 5433 uses, so a result on any of them means what it means on the others.
#: It fixes the collation of every database, and with it text ordering. ``scripts/test_postgres.py``
#: reads it from here.
LOCALE: Final = "en_US.UTF-8"

#: Where to find the binaries when they are in none of the usual places.
POSTGRES_BIN_ENV: Final = env_name("POSTGRES_BIN")

#: Checked after ``EXULANICA_POSTGRES_BIN`` and before ``PATH``: Homebrew on Apple silicon and on
#: Intel, then Debian and Ubuntu.
KNOWN_BINARY_DIRECTORIES: Final = (
    Path("/opt/homebrew/opt/postgresql@18/bin"),
    Path("/usr/local/opt/postgresql@18/bin"),
    Path("/usr/lib/postgresql/18/bin"),
)

#: Written into every cluster's ``postgresql.conf`` by ``initdb``: loopback TCP only, no socket.
LISTEN_SETTINGS: Final = {"listen_addresses": "localhost", "unix_socket_directories": ""}

#: For a scratch copy only, and for the reason the test servers give: these protect against a
#: machine crash, and a scratch copy is deleted whether or not one happens.
SCRATCH_SETTINGS: Final = {"fsync": "off", "full_page_writes": "off"}

#: How long ``pg_ctl`` waits for a server to accept connections. A durable cluster that stopped
#: uncleanly replays its write-ahead log first, and ``pg_ctl``'s own default is 60 seconds.
START_TIMEOUT_SECONDS: Final = 120
STOP_TIMEOUT_SECONDS: Final = 60

#: Tries at binding a port this module chose. Another process can take a free port between the
#: choice and the bind; each try draws a new one, so a second collision needs a second race.
PORT_ATTEMPTS: Final = 5

#: Draws of an ephemeral port before giving up. A port free on the IPv4 loopback and held on the
#: IPv6 one is drawn again, because ``localhost`` listens on both.
_PORT_DRAWS: Final = 100

#: How often a scratch copy's watcher asks whether the process that owns it still runs, which is
#: how long a copy can outlive an owner that was killed outright.
WATCH_INTERVAL_SECONDS: Final = 1

#: The file in a scratch copy's directory naming the process that owns it.
OWNER_FILE: Final = "owner.pid"


@dataclass(frozen=True, slots=True)
class Binaries:
    """One PostgreSQL installation's server and client programs."""

    directory: Path
    major: int
    version: str

    def program(self, name: str) -> str:
        return str(self.directory / name)


def binaries() -> Binaries:
    """PostgreSQL 18 or newer: ``EXULANICA_POSTGRES_BIN``, the known places, then ``PATH``."""
    return _binaries(os.environ.get(POSTGRES_BIN_ENV))


@functools.cache
def _binaries(configured: str | None) -> Binaries:
    candidates = [Path(configured)] if configured else []
    candidates += KNOWN_BINARY_DIRECTORIES
    located = shutil.which("postgres")
    if located:
        candidates.append(Path(located).parent)
    seen = []
    for directory in candidates:
        if not all((directory / name).is_file() for name in ("initdb", "pg_ctl", "postgres")):
            continue
        reported = subprocess.run(
            [str(directory / "postgres"), "--version"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        seen.append(f"{directory}: {reported or 'unreadable'}")
        found = re.search(r"\(PostgreSQL\) (\d+)(\.\d+)?", reported)
        if found and int(found.group(1)) >= MINIMUM_MAJOR:
            version = found.group(1) + (found.group(2) or "")
            return Binaries(directory=directory, major=int(found.group(1)), version=version)
    raise LocalDatabaseRefused(
        Refusal.POSTGRES_MISSING,
        f"no PostgreSQL {MINIMUM_MAJOR} server binaries found; install PostgreSQL "
        f"{MINIMUM_MAJOR} with pgvector or set {POSTGRES_BIN_ENV}. "
        f"Checked: {'; '.join(seen) or 'nothing with initdb, pg_ctl and postgres'}",
    )


def environment() -> dict[str, str]:
    """This process's environment, without the variables that would redirect a PostgreSQL tool.

    ``LC_ALL`` is set because a postmaster started without it on macOS refuses with "postmaster
    became multithreaded during startup".
    """
    cleaned = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    cleaned["LC_ALL"] = LOCALE
    return cleaned


def bootstrap_user() -> str:
    """The operating-system account running this process, which ``initdb`` names by default."""
    return pwd.getpwuid(os.geteuid()).pw_name


def run(program: str, *arguments: str, refusal: Refusal) -> subprocess.CompletedProcess[str]:
    """Run one PostgreSQL program to completion, or stop with ``refusal`` and its own words."""
    completed = subprocess.run(
        [binaries().program(program), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment(),
    )
    if completed.returncode != 0:
        raise LocalDatabaseRefused(
            refusal,
            f"{program} exited {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}",
        )
    return completed


def port_is_free(port: int) -> bool:
    """Whether ``port`` can be bound on both loopback families, as ``localhost`` listens on both."""
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((address, port))
            except OSError:
                return False
    return True


def _free_port() -> int:
    for _ in range(_PORT_DRAWS):
        with socket.socket(socket.AF_INET) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        if port_is_free(port):
            return port
    raise LocalDatabaseRefused(Refusal.PORT_IN_USE, "no free loopback port")


@dataclass(frozen=True, slots=True)
class Cluster:
    """One PostgreSQL data directory and the log its server writes."""

    data: Path
    log: Path

    def initialise(self, *, owner: str, durable: bool) -> None:
        """``initdb``, with ``owner`` as the bootstrap superuser, into an empty directory."""
        arguments = [
            "-D",
            str(self.data),
            f"--username={owner}",
            "--auth=trust",
            "--encoding=UTF8",
            f"--locale={LOCALE}",
            "--no-instructions",
        ]
        for name, value in LISTEN_SETTINGS.items():
            arguments += ["--set", f"{name}={value}"]
        if not durable:
            arguments.append("--no-sync")
        run("initdb", *arguments, refusal=Refusal.SERVER_FAILED)

    def major(self) -> int:
        """The PostgreSQL major version that made this data directory."""
        return int((self.data / "PG_VERSION").read_text().strip())

    def running(self) -> bool:
        if not (self.data / "postmaster.pid").is_file():
            return False
        status = subprocess.run(
            [binaries().program("pg_ctl"), "-D", str(self.data), "status"],
            capture_output=True,
            text=True,
            check=False,
            env=environment(),
        )
        return status.returncode == 0

    def running_port(self) -> int:
        """The port the running server listens on: the fourth line of ``postmaster.pid``."""
        return int((self.data / "postmaster.pid").read_text().splitlines()[3])

    def configured_port(self) -> int:
        """The port this cluster starts on by default, as PostgreSQL itself reads its settings."""
        shown = run("postgres", "-D", str(self.data), "-C", "port", refusal=Refusal.SERVER_FAILED)
        return int(shown.stdout.strip())

    def start(self, port: int | None = None, settings: Mapping[str, str] | None = None) -> int:
        """Start on ``port``, or on the configured port; return the port it listens on."""
        if self.major() != binaries().major:
            raise LocalDatabaseRefused(
                Refusal.SERVER_VERSION,
                f"{self.data} was made by PostgreSQL {self.major()} and the binaries found are "
                f"{binaries().version} in {binaries().directory}; set {POSTGRES_BIN_ENV} to the "
                f"PostgreSQL {self.major()} binaries, or back up and restore to change version",
            )
        wanted = port if port is not None else self.configured_port()
        if not port_is_free(wanted):
            raise LocalDatabaseRefused(
                Refusal.PORT_IN_USE,
                f"port {wanted} is held by another process, so {self.data} cannot start on it",
            )
        options = [f"-p {wanted}"]
        options += [f"-c {name}={value}" for name, value in (settings or {}).items()]
        started = subprocess.run(
            [
                binaries().program("pg_ctl"),
                "-D",
                str(self.data),
                "-l",
                str(self.log),
                "-w",
                "-t",
                str(START_TIMEOUT_SECONDS),
                "-o",
                " ".join(options),
                "start",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment(),
        )
        if started.returncode != 0:
            tail = self.log.read_text(errors="replace")[-2000:] if self.log.is_file() else ""
            raise LocalDatabaseRefused(
                Refusal.SERVER_FAILED,
                f"PostgreSQL did not start in {self.data}: {started.stderr.strip()}\n{tail}",
            )
        return wanted

    def start_on_a_free_port(self, settings: Mapping[str, str] | None = None) -> int:
        """Start on a port chosen here, drawing again if another process takes it first."""
        failure: LocalDatabaseRefused | None = None
        for _ in range(PORT_ATTEMPTS):
            try:
                return self.start(_free_port(), settings)
            except LocalDatabaseRefused as error:
                if error.refusal not in (Refusal.PORT_IN_USE, Refusal.SERVER_FAILED):
                    raise
                failure = error
        assert failure is not None
        raise failure

    def stop(self, *, immediate_after_fast: bool = False) -> None:
        """Stop the server if it runs. A fast stop rolls back open transactions and checkpoints.

        ``immediate_after_fast`` is for scratch copies only: an immediate stop skips the
        checkpoint and needs recovery at the next start, which a copy about to be deleted never
        has.
        """
        if not self.running():
            return
        stopped = subprocess.run(
            [
                binaries().program("pg_ctl"),
                "-D",
                str(self.data),
                "-w",
                "-t",
                str(STOP_TIMEOUT_SECONDS),
                "-m",
                "fast",
                "stop",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment(),
        )
        if stopped.returncode == 0:
            return
        if immediate_after_fast:
            subprocess.run(
                [binaries().program("pg_ctl"), "-D", str(self.data), "-m", "immediate", "stop"],
                capture_output=True,
                check=False,
                env=environment(),
            )
            return
        raise LocalDatabaseRefused(
            Refusal.SERVER_FAILED, f"PostgreSQL did not stop in {self.data}: {stopped.stderr}"
        )


def url(port: int, user: str, database: str) -> str:
    return f"postgresql://{user}@localhost:{port}/{database}"


@contextlib.contextmanager
def scratch_cluster(owner: str) -> Iterator[tuple[Cluster, int]]:
    """A running scratch cluster owned by ``owner``, deleted when the block ends.

    It may hold a copy of somebody's world, so its directory is private to this account. A
    watcher stops and deletes it when this process exits, however it exits; and should the
    watcher be killed with it, the next command sweeps it (:func:`sweep_scratch`).
    """
    base = base_for_scratch_servers()
    sweep_scratch(base)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{os.getpid()}-", dir=base))
    (root / OWNER_FILE).write_text(str(os.getpid()))
    cluster = Cluster(data=root / "data", log=root / "server.log")
    try:
        _remove_when_this_process_exits(root, cluster)
        cluster.initialise(owner=owner, durable=False)
        port = cluster.start_on_a_free_port(SCRATCH_SETTINGS)
        yield cluster, port
    finally:
        with contextlib.suppress(Exception):
            cluster.stop(immediate_after_fast=True)
        shutil.rmtree(root, ignore_errors=True)


def _remove_when_this_process_exits(root: Path, cluster: Cluster) -> None:
    """Start a watcher that stops and deletes a scratch copy once this process has exited.

    A process killed outright never reaches its own cleanup. The watcher runs in a session of
    its own, only ever names this copy's directory, and exits as soon as the copy is removed the
    ordinary way. ``scripts/test_postgres.py`` watches its test servers the same way.
    """
    pg_ctl = shlex.quote(binaries().program("pg_ctl"))
    data, directory = shlex.quote(str(cluster.data)), shlex.quote(str(root))
    watch = (
        f"while kill -0 {os.getpid()} 2>/dev/null && [ -d {directory} ]; "
        f"do sleep {WATCH_INTERVAL_SECONDS}; done; "
        f"if [ -d {directory} ]; then "
        f"{pg_ctl} -D {data} -m immediate -w stop >/dev/null 2>&1; rm -rf {directory}; fi"
    )
    # The outer shell backgrounds the watcher and exits at once, so nothing is left to reap.
    subprocess.run(
        ["/bin/sh", "-c", f"({watch}) </dev/null >/dev/null 2>&1 &"],
        env=environment(),
        start_new_session=True,
        check=True,
    )


def sweep_scratch(base: Path) -> list[Path]:
    """Stop and delete every scratch cluster whose owning process has exited.

    Only a directory holding an owner file is a candidate, and never one holding a local
    database's marker, whatever put it there.
    """
    removed: list[Path] = []
    if not base.is_dir():
        return removed
    for root in sorted(base.iterdir()):
        try:
            owner = int((root / OWNER_FILE).read_text())
        except (OSError, ValueError):
            continue
        if _alive(owner) or (root / "data" / LOCAL_DATABASE_MARKER).exists():
            continue
        with contextlib.suppress(Exception):
            Cluster(data=root / "data", log=root / "server.log").stop(immediate_after_fast=True)
        shutil.rmtree(root, ignore_errors=True)
        removed.append(root)
    return removed


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
