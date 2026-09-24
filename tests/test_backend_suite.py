"""The two-phase suite runner: which tests need the reference copy, and where each phase runs.

These are the statements the repository has to carry. An untracked wrapper on one machine left
a fresh clone with three tests that failed for a reason nothing in the tree explained.
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

#: The gate phase 2 exists to exercise, the tests that reach it, and the dry run that writes a
#: scratch schema into the copy, which must not run beside phase 1's parallel workers.
REFERENCE_COPY_TESTS = {
    "tests/test_frontier_demonstration.py::"
    "test_frontier_demonstration_names_the_capture_only_and_source_first_fallbacks",
    "tests/test_frontier_dry_run.py::"
    "test_dry_run_keeps_public_and_sources_and_emits_three_verifiable_packages",
    "tests/test_frontier_dry_run.py::test_failed_rehearsal_drops_only_its_owned_schema",
    "tests/test_frontier_preflight.py::"
    "test_preflight_checks_real_schema_without_ingesting_or_creating_outputs",
    "tests/test_screening_currency.py::test_shared_stale_screening_end_to_end",
}


def test_the_marker_selects_exactly_the_tests_that_need_the_pinned_endpoint():
    """Asked of pytest's own collection, not of a list written down twice.

    Another test acquiring the marker, or one of these losing it, changes what phase 2 runs, and
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
    header, first, second, skips = capsys.readouterr().out.splitlines()
    assert header.startswith("run_backend_suite: collected at ")
    assert first == "phase 1: pytest -n 4 -m not reference_copy --junitxml=/tmp/suite.xml -rf"
    assert second == (
        "phase 2: pytest -m reference_copy -rf --junitxml=/tmp/suite-reference.xml "
        f"against {runner.DEFAULT_COPY_URL}"
    )
    assert skips == (
        f"skips: each phase's are checked against the {len(runner.expected_skips())} tests and "
        f"{len(runner.expected_causes())} causes in {runner.EXPECTED_SKIPS}"
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


# -- skips are data -----------------------------------------------------------------------------

#: A module that skips in every way this suite does: in a test body, by a mark, one case of a
#: parametrised test (with a slash in its id, as the judge-words cases have), inside a class, and
#: as an expected failure, which junit files record as skipped too.
_PROBE = """
import pytest


def test_passes():
    pass


def test_skipped_in_the_body():
    pytest.skip("the body said so")


@pytest.mark.skip(reason="a mark said so")
def test_skipped_by_a_mark():
    pass


@pytest.mark.parametrize(
    "case", [pytest.param("a/b.json", marks=pytest.mark.skip(reason="one case"), id="a/b.json")]
)
def test_parametrised(case):
    pass


class TestGrouped:
    def test_inside_a_class(self):
        pytest.skip("a method said so")


@pytest.mark.xfail(reason="known and expected")
def test_expected_to_fail():
    assert False
"""

#: And a module skipped while it is collected, which junit records under the module's name.
_PROBE_MODULE = 'import pytest\n\npytest.skip("the whole module", allow_module_level=True)\n'

#: What pytest's own junit writer reports for the probe, as (node id, kind, reason).
_PROBE_SKIPS = {
    ("test_probe.py::test_skipped_in_the_body", "skip", "the body said so"),
    ("test_probe.py::test_skipped_by_a_mark", "skip", "a mark said so"),
    ("test_probe.py::test_parametrised[a/b.json]", "skip", "one case"),
    ("test_probe.py::TestGrouped::test_inside_a_class", "skip", "a method said so"),
    ("test_probe.py::test_expected_to_fail", "xfail", "known and expected"),
    ("test_probe_module.py", "skip", "the whole module"),
}


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """A directory holding the probe and the junit file pytest itself wrote for it.

    Written by pytest rather than by hand, because the check has to read what pytest writes, and a
    fixture typed from memory of the format would test the memory.
    """
    root = tmp_path_factory.mktemp("probe")
    (root / "test_probe.py").write_text(_PROBE)
    (root / "test_probe_module.py").write_text(_PROBE_MODULE)
    junit = root / "suite.xml"
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
            "test_probe.py",
            "test_probe_module.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
    return root, junit


def _accepting(skips, **changes) -> dict[str, runner.ExpectedSkip]:
    """A manifest that accepts each skip for the reason it was reported, with fields changed."""
    return {skip.test: runner.ExpectedSkip(skip.test, skip.reason, **changes) for skip in skips}


def test_each_skip_and_its_reason_are_read_from_the_file_pytest_writes(probe, monkeypatch):
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    assert {(skip.test, skip.kind, skip.reason) for skip in skips} == _PROBE_SKIPS
    # And an entry written as a node id is matched on the name pytest wrote for it.
    for skip in skips:
        if "::" in skip.test:
            assert runner.junit_identity(skip.test) == skip.identity


def test_a_run_that_skipped_a_test_nobody_accepted_fails_although_every_test_passed(
    probe, monkeypatch, capsys
):
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    accepted = _accepting(skips)
    assert runner.check_skips("phase 1", junit, accepted, 0) == 0
    printed = capsys.readouterr().out
    verdict = f"phase 1 skipped {len(skips)} tests, and {runner.EXPECTED_SKIPS} accepts every one:"
    assert verdict in printed
    for test, _kind, reason in _PROBE_SKIPS:
        assert test in printed and reason in printed

    del accepted["test_probe.py::test_skipped_by_a_mark"]
    assert runner.check_skips("phase 1", junit, accepted, 0) == runner.UNNAMED_SKIP
    printed = capsys.readouterr().out
    assert "does not accept 1 of them" in printed
    assert (
        "  test_probe.py::test_skipped_by_a_mark: a mark said so\n"
        "    refused: no entry names this test"
    ) in printed
    # A failure outranks a skip: pytest's code is kept, and the skip is still printed.
    assert runner.check_skips("phase 1", junit, accepted, 1) == 1
    assert "refused: no entry names this test" in capsys.readouterr().out


def test_a_named_test_skipped_for_another_reason_is_not_the_skip_that_was_accepted(
    probe, monkeypatch
):
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    accepted = _accepting(skips)
    body = "test_probe.py::test_skipped_in_the_body"
    accepted[body] = runner.ExpectedSkip(body, "the corpus has not been generated")
    refused = runner.refused_skips(skips, accepted, root)
    assert [(skip.test, why) for skip, why in refused] == [
        (
            body,
            "its entry accepts another reason: the corpus has not been generated, and no cause "
            "names its reason",
        )
    ]


def test_a_skip_accepted_only_without_a_path_is_refused_in_a_tree_that_has_it(
    probe, monkeypatch, tmp_path
):
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    accepted = _accepting(skips, only_without="private/words")
    assert runner.refused_skips(skips, accepted, tmp_path) == []
    (tmp_path / "private" / "words").mkdir(parents=True)
    refused = runner.refused_skips(skips, accepted, tmp_path)
    assert {skip.test for skip, _ in refused} == {test for test, _, _ in _PROBE_SKIPS}
    assert {why for _, why in refused} == {
        "its entry accepts it only without private/words, which is here, and no cause names "
        "its reason"
    }


def test_a_junit_file_that_cannot_be_read_is_a_run_whose_skips_nobody_checked(tmp_path, capsys):
    assert runner.check_skips("phase 1", tmp_path / "absent.xml", {}, 0) == runner.CANNOT_CHECK
    (tmp_path / "cut-off.xml").write_text("<testsuites><testsuite>")
    assert runner.check_skips("phase 2", tmp_path / "cut-off.xml", {}, 0) == runner.CANNOT_CHECK
    assert "nothing checked them" in capsys.readouterr().out


def test_the_run_checks_the_skips_of_the_phase_it_ran(probe, monkeypatch, tmp_path, capsys):
    """The wiring: main reads the junit file the phase wrote, and adds one when none was given."""
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    accepted = _accepting(runner.junit_skips(junit))
    del accepted["test_probe.py::TestGrouped::test_inside_a_class"]
    monkeypatch.setattr(runner, "expected_skips", lambda: accepted)
    monkeypatch.setattr(runner, "expected_causes", lambda: {})
    written = []

    def phase(arguments, environment):
        target = runner._without_junit(arguments)[0]
        written.append(target)
        Path(target).write_bytes(junit.read_bytes())
        return 0

    monkeypatch.setattr(runner, "run", phase)
    given = tmp_path / "suite.xml"
    assert runner.main(["--without-reference-copy", f"--junitxml={given}"]) == runner.UNNAMED_SKIP
    assert written == [str(given)]
    assert runner.main(["--without-reference-copy"]) == runner.UNNAMED_SKIP
    assert written[1] is not None and written[1] != str(given)
    assert "the skips are read from" in capsys.readouterr().out


def test_a_manifest_that_cannot_be_read_stops_the_run_before_any_phase(monkeypatch, capsys):
    def refuse():
        raise runner.ManifestRefused("the manifest is unreadable")

    monkeypatch.setattr(runner, "expected_skips", refuse)
    monkeypatch.setattr(runner, "run", lambda *a: pytest.fail("a phase ran"))
    assert runner.main(["--without-reference-copy"]) == runner.CANNOT_CHECK
    assert "no phase was run, because the manifest is unreadable" in capsys.readouterr().out


_HEADER = f'profile = "{runner.EXPECTED_SKIPS_PROFILE}"\n'
_ENTRY = '[[skip]]\ntest = "tests/test_a.py::test_b"\nreason = "why"\n'
_CAUSE = '[[cause]]\nreason = "the thing is absent"\n'


@pytest.mark.parametrize(
    "text, refusal",
    [
        ('profile = "exulanica.expected-skips/v0"\n', "this runner reads"),
        (_HEADER + "skips = []\n", "keys this runner does not read: skips"),
        (_HEADER + '[[skip]]\ntest = "tests/test_a.py::test_b"\n', "gives no reason"),
        (_HEADER + '[[skip]]\ntest = "test_b"\nreason = "why"\n', "names no test node id"),
        (_HEADER + _ENTRY + _ENTRY, "which an earlier entry names"),
        (_HEADER + _ENTRY + 'why = "x"\n', "fields this runner does not read"),
        (_HEADER + _ENTRY + 'only_without = "/private"\n', "only_without must be a path inside"),
        (_HEADER + _ENTRY + 'only_without = "../private"\n', "only_without must be a path inside"),
        ("profile = \n", "cannot be read"),
    ],
)
def test_a_manifest_this_runner_cannot_read_is_refused_by_name(tmp_path, text, refusal):
    manifest = tmp_path / "expected_skips.toml"
    manifest.write_text(text)
    with pytest.raises(runner.ManifestRefused, match=refusal):
        runner.expected_skips(manifest)


@pytest.mark.parametrize(
    "text, refusal",
    [
        (_HEADER + _CAUSE, "states no absence to check"),
        (_HEADER + _CAUSE + 'only_without = "/private"\n', "only_without must be a path inside"),
        (_HEADER + _CAUSE + 'only_without_extra = "gpu"\n', "does not declare: gpu"),
        (_HEADER + _CAUSE + "only_without_extra = [1]\n", "only_without_extra must name extras"),
        (_HEADER + _CAUSE + 'only_without = "x"\nwhy = "y"\n', "fields this runner does not read"),
        (
            _HEADER + (_CAUSE + 'only_without = "x"\n') * 2,
            "a reason an earlier cause names",
        ),
        (_HEADER + '[[cause]]\nonly_without = "x"\n', "gives no reason"),
        (_HEADER + _CAUSE + 'only_in_ci = "yes"\n', "only_in_ci must be true or false"),
        (_HEADER + _CAUSE + "only_in_ci = false\n", "states no absence to check"),
    ],
)
def test_a_cause_this_runner_cannot_hold_to_an_absence_is_refused_by_name(tmp_path, text, refusal):
    """A cause always names what must be absent: a path, extras pyproject declares, or
    continuous integration's machine."""
    manifest = tmp_path / "expected_skips.toml"
    manifest.write_text(text)
    with pytest.raises(runner.ManifestRefused, match=refusal):
        runner.expected_causes(manifest)


def test_a_cause_accepts_its_reason_from_any_test_where_the_path_it_names_is_absent(
    probe, monkeypatch, tmp_path
):
    """No entry names these tests; one cause per reason accepts them all, and only in a tree
    without the path, because in a tree that has it the tests had what they skipped for."""
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    causes = {
        skip.reason: runner.ExpectedCause(skip.reason, only_without="private/words")
        for skip in skips
    }
    assert runner.refused_skips(skips, {}, tmp_path, causes) == []
    (tmp_path / "private" / "words").mkdir(parents=True)
    refused = runner.refused_skips(skips, {}, tmp_path, causes)
    assert {skip.test for skip, _ in refused} == {test for test, _, _ in _PROBE_SKIPS}
    assert {why for _, why in refused} == {
        "its cause is accepted only without private/words, which is here"
    }


def test_a_cause_standing_for_an_extra_holds_only_where_the_extra_is_not_installed(
    probe, monkeypatch
):
    """Read from pyproject.toml's own declaration and the installed distributions: an extra
    whose requirement nothing installed is absent, one whose requirements are all installed is
    not, and an environment marker that does not apply is not a requirement at all."""
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(
        runner,
        "declared_extras",
        lambda: {
            "absent": ["exulanica-no-such-distribution>=1"],
            "present": ["pytest>=8", "exulanica-no-such-distribution; sys_platform == 'nowhere'"],
        },
    )
    assert runner.extra_installed("present") and not runner.extra_installed("absent")
    skips = runner.junit_skips(junit)
    for extras, refused in (
        (("absent",), 0),
        (("present",), len(skips)),
        (("absent", "present"), 0),
    ):
        causes = {
            skip.reason: runner.ExpectedCause(skip.reason, only_without_extra=extras)
            for skip in skips
        }
        assert len(runner.refused_skips(skips, {}, root, causes)) == refused, extras


def test_a_cause_of_continuous_integrations_machine_holds_only_where_github_actions_runs(
    probe, monkeypatch, tmp_path
):
    """A server binary or a cached checker is absent from the machine, not the tree, so the tree
    cannot show it. Every machine that runs the runner has them, so such a reason is accepted
    only where GitHub Actions says the run is its own, and refused anywhere else."""
    manifest = tmp_path / "expected_skips.toml"
    manifest.write_text(_HEADER + _CAUSE + "only_in_ci = true\n")
    assert runner.expected_causes(manifest) == {
        "the thing is absent": runner.ExpectedCause("the thing is absent", only_in_ci=True)
    }
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    skips = runner.junit_skips(junit)
    causes = {skip.reason: runner.ExpectedCause(skip.reason, only_in_ci=True) for skip in skips}
    monkeypatch.setenv(runner.CONTINUOUS_INTEGRATION, "true")
    assert runner.refused_skips(skips, {}, root, causes) == []
    for elsewhere in ("false", ""):
        monkeypatch.setenv(runner.CONTINUOUS_INTEGRATION, elsewhere)
        assert len(runner.refused_skips(skips, {}, root, causes)) == len(skips), elsewhere
    monkeypatch.delenv(runner.CONTINUOUS_INTEGRATION)
    refused = runner.refused_skips(skips, {}, root, causes)
    assert {skip.test for skip, _ in refused} == {test for test, _, _ in _PROBE_SKIPS}
    assert {why for _, why in refused} == {
        "its cause is accepted only in continuous integration, and GITHUB_ACTIONS is not true here"
    }


def test_a_reason_naming_the_checkout_is_read_with_the_checkout_written_as_its_name(
    tmp_path, monkeypatch
):
    """A skip naming a path inside the checkout reads the same in every checkout."""
    reason = f"the web toolchain is not installed ({tmp_path}/web/node_modules/.bin)"
    skip = runner.Skip(("tests.test_x", "test_y"), "tests/test_x.py::test_y", "skip", reason)
    written = "the web toolchain is not installed ({checkout}/web/node_modules/.bin)"
    assert runner.normalised(reason, tmp_path) == written
    causes = {written: runner.ExpectedCause(written, only_without="web/node_modules")}
    assert runner.refused_skips([skip], {}, tmp_path, causes) == []


def test_check_skips_holds_a_run_it_did_not_start_to_the_manifest(probe, monkeypatch, capsys):
    """The entry point continuous integration uses: no phase runs, and a skip neither an entry
    nor a cause names fails the check with the exit a phase's check gives, naming the test."""
    root, junit = probe
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "run", lambda *a: pytest.fail("a phase ran"))
    skips = runner.junit_skips(junit)
    accepted = _accepting(skips)
    monkeypatch.setattr(runner, "expected_skips", lambda: accepted)
    monkeypatch.setattr(runner, "expected_causes", lambda: {})
    assert runner.main(["--check-skips", str(junit)]) == 0
    assert "and tests/expected_skips.toml accepts every one" in capsys.readouterr().out

    planted = "test_probe.py::test_skipped_in_the_body"
    del accepted[planted]
    assert runner.main(["--check-skips", str(junit)]) == runner.UNNAMED_SKIP
    printed = capsys.readouterr().out
    assert (
        f"  {planted}: the body said so\n"
        "    refused: no entry names this test, and no cause names its reason"
    ) in printed


def test_every_accepted_skip_names_a_test_pytest_collects():
    """An entry for a test that is gone accepts nothing until another test is given its id.

    Asked of pytest's collection, the way the reference marker test above asks it. No -q, for the
    reason given there.
    """
    accepted = runner.expected_skips()
    assert accepted, f"{runner.EXPECTED_SKIPS} accepts no skip, so this check has nothing to check"
    tests = sorted(test for test in accepted if "::" in test)
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert {line.strip() for line in collected.stdout.splitlines() if "::" in line} == set(tests)
    modules = sorted(test for test in accepted if "::" not in test)
    assert [module for module in modules if not (ROOT / module).is_file()] == []


def test_each_entry_is_matched_by_the_name_pytest_writes_for_it():
    """Brackets, slashes and dots in a parametrised id survive the trip into junit and back."""
    for test in runner.expected_skips():
        assert runner._node_id(*runner.junit_identity(test)) == test
