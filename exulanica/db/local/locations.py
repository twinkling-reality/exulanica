"""Where a local database may live, and the marker that says a directory is one.

Two kinds of directory are refused, by resolved path, before anything is written:

*   **The test servers' base directory.** ``scripts/test_postgres.py`` creates every test server
    under it, runs them with durability off, migrates its per-worktree server on every start, and
    its ``sweep`` deletes servers whose owner has exited. The base is named here, once, and the
    test tooling reads it from here, so the refusal and the location cannot drift apart.
*   **A temporary directory.** The temporary directory this process is given (``TMPDIR`` or the
    platform default, as :func:`tempfile.gettempdir` resolves it) and the conventional ``/tmp``
    and ``/var/tmp``. A temporary directory is disposable by definition: the operating system may
    clear it, and cleanup tools and people remove what they find there.

The marker is the other half of keeping the two apart. :mod:`exulanica.db.local` writes it into
every data directory it creates, and ``scripts/test_postgres.py`` refuses to serve, start or sweep
a data directory that holds one. So a durable database reached through a link or a copy under the
test directory is refused rather than served the way a test server is.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final

from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal

__all__ = [
    "CONVENTIONAL_TEMPORARY_DIRECTORIES",
    "LOCAL_DATABASE_MARKER",
    "SCRATCH_DIRECTORY_NAME",
    "TEST_SERVER_DIRECTORY_NAME",
    "base_for_scratch_servers",
    "base_for_test_servers",
    "refuse_existing_data",
    "refuse_location",
    "temporary_directories",
]

#: The directory, inside the system temporary directory, that holds every test server.
#: ``.noindex`` keeps Spotlight from indexing the relation files a parallel run rewrites.
TEST_SERVER_DIRECTORY_NAME: Final = "exulanica-test-postgres.noindex"

#: The directory, inside the system temporary directory, that holds the scratch servers this
#: command restores a backup into to verify or rehearse it. Each is deleted when its step ends.
SCRATCH_DIRECTORY_NAME: Final = "exulanica-local-db-scratch.noindex"

#: The file this command writes into every PostgreSQL data directory it creates.
LOCAL_DATABASE_MARKER: Final = "exulanica-local-database.json"

#: Temporary directories by convention on every POSIX system, whatever ``TMPDIR`` says.
CONVENTIONAL_TEMPORARY_DIRECTORIES: Final = (Path("/tmp"), Path("/var/tmp"))


def base_for_test_servers() -> Path:
    """The base directory ``scripts/test_postgres.py`` keeps every test server under."""
    return Path(tempfile.gettempdir()) / TEST_SERVER_DIRECTORY_NAME


def base_for_scratch_servers() -> Path:
    return Path(tempfile.gettempdir()) / SCRATCH_DIRECTORY_NAME


def temporary_directories() -> tuple[Path, ...]:
    """Every directory a data directory may not be inside, read when asked, never cached."""
    return (Path(tempfile.gettempdir()), *CONVENTIONAL_TEMPORARY_DIRECTORIES)


def refuse_location(directory: Path) -> Path:
    """Return ``directory`` resolved, or refuse it for being somewhere disposable.

    The test directory is checked first because it sits inside the temporary directory and its
    refusal says more: the files there are deleted by the test tooling itself.
    """
    resolved = directory.expanduser().resolve()
    test_base = base_for_test_servers().resolve()
    if resolved.is_relative_to(test_base):
        raise LocalDatabaseRefused(
            Refusal.TEST_SERVER_DIRECTORY,
            f"{resolved} is under {test_base}, where scripts/test_postgres.py keeps disposable "
            "test servers: it runs them without fsync, migrates them on every start and sweeps "
            "them away. Choose a directory outside it.",
        )
    for temporary in temporary_directories():
        root = temporary.resolve()
        if resolved.is_relative_to(root):
            raise LocalDatabaseRefused(
                Refusal.TEMPORARY_DIRECTORY,
                f"{resolved} is inside the temporary directory {root}, which the system and "
                "cleanup tools may empty. Choose a directory you would back up, such as one in "
                "your home directory.",
            )
    return resolved


def refuse_existing_data(directory: Path) -> None:
    """Refuse a location that holds anything: a new data directory is only ever created."""
    if directory.is_symlink() or directory.is_file():
        raise LocalDatabaseRefused(
            Refusal.EXISTING_DATA, f"{directory} exists and is not an empty directory"
        )
    if directory.is_dir() and any(directory.iterdir()):
        held = sorted(entry.name for entry in directory.iterdir())
        shown = ", ".join(held[:5]) + (f" and {len(held) - 5} more" if len(held) > 5 else "")
        raise LocalDatabaseRefused(
            Refusal.EXISTING_DATA,
            f"{directory} already holds {shown}. Nothing is written over existing data; give "
            "an empty or absent directory.",
        )
