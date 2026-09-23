"""Is another checkout editing these paths? Read-only: ask before moving or rewriting a file.

    python3 scripts/who_edits.py [--base main] [--packages DIR] <repository-relative path>...

A path is HELD when any of these is true, and FREE otherwise:

*   a linked worktree of this repository has it modified or untracked;
*   the branch a linked worktree has checked out holds a commit touching it that the base does not;
*   a change package lists it and the base still holds the package's preimage of it, so the package
    is waiting to be applied.

A change package is a directory holding ``preimage.sha256`` and ``postimage.sha256``, one
``<sha256|ABSENT|DELETED>  <path>`` line per touched path. The packages are read from the private
notes directory of the main checkout (``resolve_briefs_path`` in ``exulanica/env.py``) unless
``--packages`` names another. A package whose preimage and postimage both differ from the base is
stale: it cannot apply as it is, so it is printed as information and holds nothing.

IT READS AND NEVER WRITES. Every git command runs with ``--no-optional-locks``, because a plain
``git status`` may refresh another worktree's index and write it, and that can collide with the
owner's own git operation. It never runs git in a worktree under ``~/.codex``, which belongs to
another tool, and never counts the main checkout, which is where changes land rather than where
they are made. The worktrees it read and the ones it skipped are printed first, so an answer that
rests on nothing says so.

Exit 0 when every path is FREE, 1 when any is HELD, 2 when it cannot read the repository.
It runs with any python3 from 3.9, from any directory: it asks about the repository it is in.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exulanica.env import resolve_briefs_path  # noqa: E402

HELD = 1
UNREADABLE = 2


class Unreadable(RuntimeError):
    """The repository could not be read, so no answer about any path is given."""


#: Absent from the base, as the package manifests spell it.
ABSENT = "ABSENT"
#: The worktrees another tool keeps, which this never enters.
FOREIGN = Path.home() / ".codex"


def git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess:
    """One read-only git command in ``cwd``: no optional locks, so no index is written."""
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(cwd), *arguments],
        capture_output=True,
        check=False,
    )


@dataclass
class Worktrees:
    """The main checkout, the linked worktrees this reads, and those it skips with the reason."""

    main: Path
    read: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def worktrees(cwd: Path) -> Worktrees:
    """Every worktree of the repository ``cwd`` is in, sorted into read and skipped."""
    foreign = FOREIGN  # read when called, so a caller that moves it is obeyed
    listed = git("worktree", "list", "--porcelain", cwd=cwd)
    if listed.returncode != 0:
        raise Unreadable(f"{cwd} is not in a git repository")
    paths = [
        Path(line.split(" ", 1)[1])
        for line in listed.stdout.decode().splitlines()
        if line.startswith("worktree ")
    ]
    found = Worktrees(main=paths[0])
    for path in paths[1:]:
        if path == foreign or foreign in path.parents:
            found.skipped.append(f"{path} (another tool's worktree)")
        elif not path.is_dir():
            found.skipped.append(f"{path} (missing from disk)")
        else:
            found.read.append(path)
    return found


def base_digest(main: Path, base: str, target: str) -> str:
    """The SHA-256 of the base's copy of ``target``, or ABSENT."""
    shown = git("show", f"{base}:{target}", cwd=main)
    return hashlib.sha256(shown.stdout).hexdigest() if shown.returncode == 0 else ABSENT


def _image(manifest: Path, target: str) -> str | None:
    """The digest a package manifest records for ``target``, or None when it does not list it."""
    if not manifest.is_file():
        return None
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == target:
            return parts[0]
    return None


def holders(
    target: str, found: Worktrees, packages: Path | None, base: str
) -> tuple[list[str], list[str]]:
    """Who holds ``target``, and what is worth knowing that holds nothing."""
    held, notes = [], []
    for tree in found.read:
        if git("status", "--porcelain", "--", target, cwd=tree).stdout.strip():
            held.append(f"modified or untracked in {tree}")
        commits = git("log", "--format=%h", f"{base}..HEAD", "--", target, cwd=tree)
        if commits.stdout.strip():
            held.append(f"a commit {base} does not hold touches it in {tree}")
    if packages is not None and packages.is_dir():
        now = base_digest(found.main, base, target)
        for manifest in sorted(packages.glob("*/preimage.sha256")):
            package = manifest.parent
            before = _image(manifest, target)
            after = _image(package / "postimage.sha256", target)
            if before is None and after is None:
                continue
            if now == after:
                continue  # applied
            if now == before:
                held.append(f"change package {package.name} is waiting: {base} holds its preimage")
            else:
                notes.append(f"stale change package {package.name}: {base} holds neither image")
    return held, notes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", help="repository-relative paths to ask about")
    parser.add_argument("--base", default="main", help="the branch changes land on (main)")
    parser.add_argument("--packages", type=Path, help="the directory holding change packages")
    known = parser.parse_args(list(argv) if argv is not None else None)
    try:
        found = worktrees(ROOT)
    except Unreadable as refusal:
        print(f"who_edits: {refusal}", file=sys.stderr)
        return UNREADABLE
    packages = known.packages or resolve_briefs_path(root=found.main)
    print(f"who_edits: {len(found.read)} worktrees read against {known.base}; packages {packages}")
    for skipped in found.skipped:
        print(f"who_edits: skipped {skipped}")
    any_held = False
    for target in known.paths:
        held, notes = holders(target, found, packages, known.base)
        any_held = any_held or bool(held)
        print(("HELD  " if held else "FREE  ") + target)
        for line in held:
            print(f"      {line}")
        for line in notes:
            print(f"      (info) {line}")
    return HELD if any_held else 0


if __name__ == "__main__":
    raise SystemExit(main())
