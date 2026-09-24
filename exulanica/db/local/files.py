"""Writing a file that may hold a person's world or a password: private, and in one step.

A reader sees the old content or the new, never part of either: the content goes to a sibling
under a ``.partial`` name, is synced, and is renamed over the target, and the rename is synced in
its directory. :mod:`~exulanica.db.local.passwords` sits below the rest of the package and writes
through this module, which is why it is not part of :mod:`~exulanica.db.local.database`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

__all__ = [
    "PRIVATE_DIRECTORY_MODE",
    "PRIVATE_FILE_MODE",
    "sync_directory",
    "write_atomically",
    "write_private",
]

#: Files this command writes can hold a person's world or a password; only their account may
#: read them. libpq ignores a password file that grants group or world any access.
PRIVATE_FILE_MODE: Final = 0o600
PRIVATE_DIRECTORY_MODE: Final = 0o700


def write_atomically(target: Path, content: bytes, *, mode: int) -> None:
    """Replace ``target`` with ``content``, created with ``mode``, in one step."""
    partial = target.with_name(target.name + ".partial")
    with open(partial, "wb") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(target)
    sync_directory(target.parent)


def write_private(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` in one step, readable only by this account."""
    write_atomically(target, content.encode("utf-8"), mode=PRIVATE_FILE_MODE)


def sync_directory(directory: Path) -> None:
    """Make a rename in ``directory`` durable, as a file's own fsync does not."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
