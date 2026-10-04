"""The git tree id of a directory, computed without git, so a fetched archive can be held to a commit.

A GitHub archive of a commit has no ``.git``; its bytes are not promised to stay the same, but its
files are the commit's tree. Hashing that tree the way git does (a blob per file, a tree per
directory, entries sorted as git sorts them) and comparing with the tree id the commit names proves
the files are exactly the commit's. A submodule is not in an archive; it is a gitlink entry whose
commit the caller states.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from pathlib import Path

__all__ = ["blob_id", "tree_id"]


def blob_id(data: bytes) -> bytes:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).digest()


def _sort_key(name: str, is_tree: bool) -> bytes:
    # Git compares a tree's name as if it ended in "/".
    return name.encode("utf-8") + (b"/" if is_tree else b"")


def tree_id(directory: Path, gitlinks: Mapping[str, str] | None = None) -> str:
    """The 40-hex tree id of ``directory``; ``gitlinks`` maps a relative path to its commit."""
    tree = _tree(directory, directory, dict(gitlinks or {}))
    if tree is None:
        raise ValueError(f"{directory} holds nothing git would record")
    return tree.hex()


def _tree(root: Path, directory: Path, gitlinks: dict[str, str]) -> bytes | None:
    """A directory's tree id, or None for a directory with nothing git would record."""
    entries: list[tuple[bytes, bytes]] = []
    for name in os.listdir(directory):
        if name == ".git":
            continue
        path = directory / name
        relative = path.relative_to(root).as_posix()
        if relative in gitlinks:
            entries.append(
                (
                    _sort_key(name, False),
                    b"160000 " + name.encode() + b"\x00" + bytes.fromhex(gitlinks[relative]),
                )
            )
            continue
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            target = os.readlink(path).encode()
            entries.append(
                (_sort_key(name, False), b"120000 " + name.encode() + b"\x00" + blob_id(target))
            )
        elif stat.S_ISDIR(mode):
            child = _tree(root, path, gitlinks)
            if child is None:
                continue
            entries.append((_sort_key(name, True), b"40000 " + name.encode() + b"\x00" + child))
        else:
            kind = b"100755" if mode & stat.S_IXUSR else b"100644"
            entries.append(
                (
                    _sort_key(name, False),
                    kind + b" " + name.encode() + b"\x00" + blob_id(path.read_bytes()),
                )
            )
    if not entries:
        return None
    body = b"".join(entry for _, entry in sorted(entries))
    return hashlib.sha1(b"tree %d\x00" % len(body) + body).digest()
