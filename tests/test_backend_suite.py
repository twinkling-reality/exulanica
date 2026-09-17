"""The two-phase suite runner: which tests need the reference copy, and where each phase runs.

These are the statements the repository has to carry, because until 2026-09-17 they lived in one
machine's untracked wrapper: a fresh clone had three tests that failed for a reason nothing in the
tree explained.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_backend_suite as runner  # noqa: E402

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
    first, second = capsys.readouterr().out.splitlines()
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
