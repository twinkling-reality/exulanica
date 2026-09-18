"""The two-phase suite runner: which tests need the reference copy, and where each phase runs.

These are the statements the repository has to carry, because until 2026-09-17 they lived in one
machine's untracked wrapper: a fresh clone had three tests that failed for a reason nothing in the
tree explained.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_backend_suite as runner  # noqa: E402

#: Provenance is read out of git, so where there is no git there is nothing here to state.
NEEDS_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="provenance is read from git")

#: The gate phase 2 exists to exercise, and the tests that reach it.
REFERENCE_COPY_TESTS = {
    "tests/test_frontier_demonstration.py::"
    "test_frontier_demonstration_names_the_capture_only_and_source_first_fallbacks",
    "tests/test_frontier_preflight.py::"
    "test_preflight_checks_real_schema_without_ingesting_or_creating_outputs",
    "tests/test_screening_currency.py::test_shared_stale_screening_end_to_end",
}


def test_the_marker_selects_exactly_the_tests_that_need_the_pinned_endpoint():
    """Asked of pytest's own collection, not of a list written down twice.

    A fourth test acquiring the marker, or one of these losing it, changes what phase 2 runs, and
    this is where that shows up.
    """
    # No -q here: this project already passes one in addopts, and a second switches the output
    # from node ids to per-file counts, which would make this test read an empty set as agreement.
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-m", runner.REFERENCE_MARKER],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    selected = {line.strip() for line in collected.stdout.splitlines() if "::" in line}
    assert selected == REFERENCE_COPY_TESTS


def test_each_phase_runs_where_its_tests_can_pass():
    """Phase 1 on a private server per worker, phase 2 on the copy the gate pins."""
    parallel = runner.phase_environment(private_servers=True, copy_url=runner.DEFAULT_COPY_URL)
    assert parallel["EXULANICA_TEST_POSTGRES"] == "private"
    assert "EXULANICA_TEST_DATABASE_URL" not in parallel
    serial = runner.phase_environment(private_servers=False, copy_url=runner.DEFAULT_COPY_URL)
    assert serial["EXULANICA_TEST_DATABASE_URL"] == runner.DEFAULT_COPY_URL
    assert "EXULANICA_TEST_POSTGRES" not in serial
    for environment in (parallel, serial):
        assert environment["EXULANICA_REFERENCE_DATABASE_URL"] == runner.DEFAULT_COPY_URL
        assert environment["EXULANICA_REQUIRE_POSTGRES"] == "1"


def test_the_plan_names_both_phases_and_gives_phase_two_its_own_record(capsys):
    assert runner.main(["--plan", "--jobs", "4", "--junitxml=/tmp/suite.xml", "-rf"]) == 0
    header, first, second = capsys.readouterr().out.splitlines()
    assert header.startswith("run_backend_suite: collected at ")
    assert first == "phase 1: pytest -n 4 -m not reference_copy --junitxml=/tmp/suite.xml -rf"
    assert second == (
        "phase 2: pytest -m reference_copy -rf --junitxml=/tmp/suite-reference.xml "
        f"against {runner.DEFAULT_COPY_URL}"
    )


def test_running_without_the_copy_says_which_gate_goes_unexercised(capsys):
    assert runner.main(["--plan", "--without-reference-copy"]) == 0
    printed = capsys.readouterr().out
    assert "phase 2: not run" in printed
    assert runner.REFERENCE_MARKER in printed


def _repository(at: Path) -> Path:
    """A repository with one commit on a named branch, so a test states the tree it reads."""
    at.mkdir(parents=True)
    git = ["git", "-C", str(at), "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(at)], check=True)
    subprocess.run([*git, "config", "user.email", "suite@local"], check=True)
    subprocess.run([*git, "config", "user.name", "Suite"], check=True)
    (at / "kept.py").write_text("one = 1\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "one"], check=True)
    return at


@NEEDS_GIT
def test_the_header_names_the_commit_and_branch_a_clean_run_collected_at(tmp_path, monkeypatch):
    """A log that cannot name its tree can be read against any tree, which is how it goes wrong.

    On 2026-09-18 a lane reported two green suites as verified on a tree neither had run on. Nothing
    in either output was false; there was nothing in it that could disagree, because this header
    printed the pytest arguments and no more.
    """
    repository = _repository(tmp_path / "repo")
    monkeypatch.setattr(runner, "ROOT", repository)
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert runner.tree_identity() == (
        f"run_backend_suite: collected at {commit} on trunk, tree clean"
    )


@NEEDS_GIT
def test_an_untracked_test_file_makes_a_run_not_the_commit_it_names(tmp_path, monkeypatch):
    """What dirty means, and the two readings that fix it, taken a moment apart in one repository.
     pytest collects an untracked test file exactly as it collects a tracked one, so a run over one
    is not a run of the commit named. An ignored file is the other side of that sentence: it cannot
    be collected, and the scratch containers a lane leaves everywhere must not make a run read as
    stale. Neither reading can pass by describing the format alone, because the other contradicts
    it.
    """
    repository = _repository(tmp_path / "repo")
    monkeypatch.setattr(runner, "ROOT", repository)
    git = ["git", "-C", str(repository), "-c", "commit.gpgsign=false"]
    (repository / ".gitignore").write_text("scratch/\n")
    subprocess.run([*git, "add", ".gitignore"], check=True)
    subprocess.run([*git, "commit", "-qm", "ignore scratch"], check=True)

    (repository / "scratch").mkdir()
    (repository / "scratch" / "tile.owd").write_text("bytes")
    assert runner.tree_identity().endswith(", tree clean")

    (repository / "test_late_arrival.py").write_text("def test_x():\n    pass\n")
    dirty = runner.tree_identity()
    assert "so this run is not that commit: test_late_arrival.py" in dirty
    assert "1 path differs" in dirty


@NEEDS_GIT
def test_a_detached_head_is_named_rather_than_refused(tmp_path, monkeypatch):
    """The runner is used from detached checkouts, where there is a commit and no branch."""
    repository = _repository(tmp_path / "repo")
    monkeypatch.setattr(runner, "ROOT", repository)
    subprocess.run(["git", "-C", str(repository), "checkout", "-q", "--detach"], check=True)
    assert runner.tree_identity().endswith(", detached, tree clean")


@NEEDS_GIT
def test_a_tree_git_cannot_name_a_commit_in_does_not_stop_the_suite(tmp_path, monkeypatch):
    """A repository before its first commit: git answers, and has no commit to answer with."""
    subprocess.run(["git", "init", "-q", str(tmp_path / "fresh")], check=True)
    monkeypatch.setattr(runner, "ROOT", tmp_path / "fresh")
    assert runner.tree_identity() == (
        "run_backend_suite: collected at an unknown commit, because git did not name one"
    )


def test_no_git_at_all_says_so_rather_than_refusing_to_start(monkeypatch):
    """A fresh clone or a slim container may have no git, and provenance must never cost a run.

    Trading the measurement for a line about the measurement would be a worse bargain than the one
    this header exists to fix.
    """
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    assert runner.tree_identity() == (
        "run_backend_suite: collected at an unknown commit, because git is not on the path"
    )
