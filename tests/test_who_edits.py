"""The who-is-editing check: what holds a path, what it skips, and that it writes no index.

Every repository here is built in ``tmp_path``: a main checkout, a linked worktree on its own
branch, a worktree standing in for another tool's under a stand-in home, and a directory of change
packages.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import who_edits  # noqa: E402

#: Every write here must be one this test makes, so git's own configuration cannot add one.
_GIT = ["git", "-c", "commit.gpgsign=false", "-c", "core.fsmonitor=false"]


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        [*_GIT, "-C", str(cwd), *arguments], check=True, capture_output=True, text=True
    ).stdout


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _index(worktree: Path) -> Path:
    """The index file git keeps for a linked worktree, inside the main checkout's git directory."""
    found = _git(worktree, "rev-parse", "--path-format=absolute", "--git-path", "index")
    return Path(found.strip())


def _state(index: Path) -> tuple[int, str]:
    return index.stat().st_mtime_ns, _digest(index.read_bytes())


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A main checkout with a lane worktree, a foreign worktree and three change packages."""
    main = tmp_path / "main"
    main.mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(main))
    _git(main, "config", "user.email", "who@local")
    _git(main, "config", "user.name", "Who")
    for name in ("edited.txt", "committed.txt", "foreign.txt", "pending.txt", "applied.txt"):
        (main / name).write_text(f"{name} on main\n")
    _git(main, "add", ".")
    _git(main, "commit", "-qm", "one")

    lane = tmp_path / "lane"
    _git(main, "worktree", "add", "-q", "-b", "lane/one", str(lane))
    (lane / "edited.txt").write_text("edited in the lane\n")
    (lane / "committed.txt").write_text("committed in the lane\n")
    _git(lane, "commit", "-qm", "lane work", "--", "committed.txt")

    home = tmp_path / "home"
    foreign = home / ".codex" / "worktrees" / "tool"
    _git(main, "worktree", "add", "-q", "--detach", str(foreign))
    (foreign / "foreign.txt").write_text("another tool's edit\n")
    monkeypatch.setattr(who_edits, "FOREIGN", home / ".codex")
    monkeypatch.setattr(who_edits, "ROOT", main)

    packages = tmp_path / "packages"
    on_main = {name: _digest((main / name).read_bytes()) for name in ("pending.txt", "applied.txt")}
    for package, name, before, after in (
        ("waiting-delta", "pending.txt", on_main["pending.txt"], _digest(b"its postimage\n")),
        ("landed-delta", "applied.txt", _digest(b"its preimage\n"), on_main["applied.txt"]),
        ("stale-delta", "pending.txt", _digest(b"an old base\n"), _digest(b"an old change\n")),
    ):
        (packages / package).mkdir(parents=True)
        (packages / package / "preimage.sha256").write_text(f"{before}  {name}\n")
        (packages / package / "postimage.sha256").write_text(f"{after}  {name}\n")
    return main, lane, foreign, packages


def test_each_kind_of_holder_is_named_and_another_tools_worktree_is_never_read(repository, capsys):
    _main, lane, foreign, packages = repository
    targets = ["edited.txt", "committed.txt", "foreign.txt", "pending.txt", "applied.txt"]
    assert who_edits.main([*targets, "--packages", str(packages)]) == who_edits.HELD
    printed = capsys.readouterr().out
    assert "who_edits: 1 worktrees read against main" in printed
    assert f"who_edits: skipped {foreign} (another tool's worktree)" in printed
    assert f"HELD  edited.txt\n      modified or untracked in {lane}\n" in printed
    assert f"HELD  committed.txt\n      a commit main does not hold touches it in {lane}\n" in (
        printed
    )
    assert "FREE  foreign.txt\n" in printed
    assert "HELD  pending.txt\n      change package waiting-delta is waiting" in printed
    assert "(info) stale change package stale-delta: main holds neither image" in printed
    assert "FREE  applied.txt\n" in printed


def test_a_path_nobody_holds_is_free_and_the_answer_is_zero(repository, capsys):
    _main, _lane, _foreign, packages = repository
    assert who_edits.main(["applied.txt", "--packages", str(packages)]) == 0
    assert "FREE  applied.txt" in capsys.readouterr().out


def test_asking_writes_no_index_where_a_plain_status_would(repository):
    """The read-only claim, with the control that shows the measurement can see a write.

    A file whose timestamp moves while its bytes do not is what makes ``git status`` refresh an
    index and write it back. Asking about that file leaves the lane's index as it was; a plain
    ``git status`` in the same state then rewrites it, which is the write the flag prevents.
    """
    _main, lane, _foreign, packages = repository
    index = _index(lane)
    edited = lane / "committed.txt"
    later = edited.stat().st_mtime_ns + 5_000_000_000
    os.utime(edited, ns=(later, later))
    before = _state(index)
    who_edits.main(["committed.txt", "edited.txt", "--packages", str(packages)])
    assert _state(index) == before
    _git(lane, "status", "--porcelain")
    assert _state(index) != before, "plain git status wrote nothing, so this measured nothing"


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(who_edits, "ROOT", tmp_path)
    assert who_edits.main(["anything.txt"]) == who_edits.UNREADABLE
    assert "is not in a git repository" in capsys.readouterr().err
