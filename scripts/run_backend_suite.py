"""Run the backend suite in its two phases, and say what the second one is for.

    uv run python scripts/run_backend_suite.py [--jobs 6] [pytest arguments]

PHASE 1 runs everything except the reference copy tests, in parallel, each worker on its own
private PostgreSQL server.

PHASE 2 runs the reference copy tests, serially, against the pinned local copy.

A reference copy test is one marked ``reference_copy``. Those tests exercise the frontier preflight,
which is the privacy gate on the command that reads retained personal data, and the gate pins its
endpoint twice: once in the connection string (exulanica/db/reference_target.py) and once by asking
the server its own ``inet_server_port()`` and ``current_database()``
(exulanica/orchestration/preflight.py). A private server necessarily listens on a random port, so
under the parallel runner the runner and the gate contradict each other and the gate refuses. That is
the gate working. It is also why these tests failed on every run from the introduction of private
servers until 2026-09-17, and why they must run against the copy instead of being deselected and
forgotten. The frontier dry run carries the marker too: it creates, migrates and drops a scratch
schema of its own in the copy, and while it lacked the marker it did so in phase 1, beside the
parallel workers, where nothing listed the copy's schemas around it.

The copy is irreplaceable: it has no structural snapshot. This script never writes to it. The
harness creates one scratch schema there, applies the migrations into it and drops it in a finally,
so a failing test still drops it and only a killed process leaves one behind; this script lists the
schemas before and after phase 2 and refuses to be quiet if that set changed.

Without a copy to run against, pass --without-reference-copy. It runs phase 1 alone and says which
gate went unexercised, because a suite that omits this one silently is the state this script exists
to end.

EVERY SKIP IS PRINTED WITH ITS REASON, and a run fails on a skip that tests/expected_skips.toml does
not accept. A skipped test did not run, and on 2026-09-22 a skip hid five real failures on main for
five hours behind green runs, because a count of skips is a number nobody compares. So each phase's
skips are read back from its junit file, matched against the entries by pytest's own junit naming,
and a new skip is a line somebody adds to that file in a diff rather than a number that drifted.
Without --junitxml the runner writes one to a temporary directory so the check still happens.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# pytest's own function for turning a node id into a junit classname and name. Imported rather than
# restated, so the names this script matches are the names pytest wrote.
from _pytest.junitxml import mangle_test_address

#: The tests that need the pinned endpoint, named by their own marker rather than by a list here.
REFERENCE_MARKER = "reference_copy"
#: The one local copy of retained data these tests may be pointed at.
DEFAULT_COPY_URL = "postgresql://localhost:5433/exulanica_inspect_test"
#: Exit codes of this script itself, distinct from pytest's.
CANNOT_CHECK = 70
LEFT_BEHIND = 75
UNNAMED_SKIP = 76
ROOT = Path(__file__).resolve().parents[1]
#: How long to wait for git before giving up on provenance: a header never holds up the suite.
GIT_TIMEOUT_SECONDS = 5
#: How many differing paths the header names before it stops counting them out.
NAMED_DIFFERENCES = 3
#: The skips a run may report, each with the reason pytest gives for it, relative to ROOT. The
#: file says why.
EXPECTED_SKIPS = "tests/expected_skips.toml"
#: The one layout of that file this runner reads; any other is refused rather than guessed at.
EXPECTED_SKIPS_PROFILE = "exulanica.expected-skips/v1"
#: The message pytest's junit writer gives a module it skipped while collecting it.
COLLECTION_SKIPPED = "collection skipped"


def _git(*arguments: str) -> str | None:
    """One git command's output verbatim, or None when git cannot answer.

    VERBATIM MATTERS: porcelain output carries its status in the first two columns, so stripping the
    output here would eat the first path's opening character, which it did before this said so.

    It never raises and never waits long, because every caller is decorating a run rather than
    deciding one, and it cannot say WHY git failed: a missing repository, a repository with no
    commit yet and a git that hung all arrive here as the same None.
    """
    try:
        finished = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    return finished.stdout


def tree_identity() -> str:
    """WHICH TREE THIS RUN COLLECTED AT, as one line, so a log cannot be read against another one.

    This log used to say nothing whatever about the code it ran. So a count taken minutes before a
    rebase read exactly like one taken after it, and on 2026-09-18 a lane reported both of its suites
    as verified on a tree they had never run on. Nothing in the output was wrong; there was simply
    nothing in it that could disagree. Compare a skip count, which is a sentence about the run and
    says "12 skipped" out loud the moment a database name is misspelt. An instrument that is silent
    by construction is the worse half of that pair, and the only cure is to print the thing.

    DIRTY MEANS the working tree differs from the commit it names in any file git is not told to
    ignore, tracked or untracked alike, because pytest collects an untracked test file exactly as it
    collects a tracked one and a run over it is not a run of that commit.

    WHAT IT DOES NOT DO is judge whether the difference mattered. It names the paths so a reader can,
    and a header that ruled on its own relevance would be the same overreach one level down.

    It answers on a detached head, in a worktree, in a fresh clone with no git at all, and when git
    hangs. The runner is used in all of those, and a suite that refused to start because provenance
    was unavailable would have traded the measurement for a line about it.
    """
    if shutil.which("git") is None:
        return "run_backend_suite: collected at an unknown commit, because git is not on the path"
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return "run_backend_suite: collected at an unknown commit, because git did not name one"
    short = commit.strip()
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    named = None if branch is None else branch.strip()
    where = f"{short}, detached" if named in (None, "HEAD") else f"{short} on {named}"
    # --no-optional-locks so reading provenance never takes the index lock from a concurrent lane.
    differences = _git("--no-optional-locks", "status", "--porcelain")
    if differences is None:
        return f"run_backend_suite: collected at {where}, and whether its tree is clean is unknown"
    paths = [line[3:] for line in differences.splitlines()]
    if not paths:
        return f"run_backend_suite: collected at {where}, tree clean"
    shown = ", ".join(paths[:NAMED_DIFFERENCES])
    remaining = len(paths) - NAMED_DIFFERENCES
    if remaining > 0:
        shown = f"{shown} and {remaining} more"
    counted = "1 path differs" if len(paths) == 1 else f"{len(paths)} paths differ"
    return (
        f"run_backend_suite: collected at {where}, but {counted} from it, so this run is not that "
        f"commit: {shown}"
    )


def phase_environment(*, private_servers: bool, copy_url: str) -> dict[str, str]:
    """The environment each phase runs in, as the difference from this process."""
    environment = dict(os.environ)
    environment["EXULANICA_REQUIRE_POSTGRES"] = "1"
    environment["EXULANICA_REFERENCE_DATABASE_URL"] = copy_url
    if private_servers:
        environment.pop("EXULANICA_TEST_DATABASE_URL", None)
        environment["EXULANICA_TEST_POSTGRES"] = "private"
    else:
        environment.pop("EXULANICA_TEST_POSTGRES", None)
        environment["EXULANICA_TEST_DATABASE_URL"] = copy_url
    return environment


def _without_junit(arguments: Sequence[str]) -> tuple[str | None, list[str]]:
    """The junit path among pytest arguments, the last one as pytest reads it, and the rest."""
    rest: list[str] = []
    junit: str | None = None
    expecting = False
    for argument in arguments:
        if expecting:
            junit, expecting = argument, False
        elif argument.startswith("--junitxml="):
            junit = argument.split("=", 1)[1]
        elif argument == "--junitxml":
            expecting = True
        else:
            rest.append(argument)
    return junit, rest


def split_junit(arguments: Sequence[str]) -> tuple[list[str], list[str]]:
    """Phase 1 keeps a caller's junit path; phase 2 writes a sibling, so neither overwrites it."""
    junit, phase_two = _without_junit(arguments)
    if junit is not None:
        phase_two.append(f"--junitxml={reference_junit(junit)}")
    return list(arguments), phase_two


def schemas(copy_url: str) -> list[str] | None:
    """The schema names in the copy, read only, or None when they cannot be read."""
    try:
        import psycopg
    except ImportError:
        print("run_backend_suite: psycopg is needed to check the reference copy", file=sys.stderr)
        return None
    try:
        with psycopg.connect(copy_url, connect_timeout=5) as connection:
            connection.execute("set transaction read only")
            rows = connection.execute(
                "select nspname from pg_namespace "
                "where nspname not like 'pg\\_%' and nspname <> 'information_schema' order by 1"
            ).fetchall()
    except psycopg.Error as error:
        print(f"run_backend_suite: cannot read the reference copy: {error}", file=sys.stderr)
        return None
    return [row[0] for row in rows]


def run(arguments: Sequence[str], environment: dict[str, str]) -> int:
    print(f"run_backend_suite: pytest {' '.join(arguments)}", flush=True)
    return subprocess.call([sys.executable, "-m", "pytest", *arguments], cwd=ROOT, env=environment)


class ManifestRefused(ValueError):
    """The expected-skips file is not one this runner can read; the message says what is wrong."""


@dataclass(frozen=True)
class ExpectedSkip:
    """A skip the runner accepts: the test, the reason pytest reports, and where it applies."""

    test: str
    reason: str
    #: A repository-relative path whose absence is the reason for the skip. In a tree that holds
    #: it the skip is not accepted. None accepts the skip in every tree.
    only_without: str | None = None


@dataclass(frozen=True)
class Skip:
    """A skip one phase reported, as its junit file records it."""

    #: (classname, name), exactly as pytest wrote them, which is what an entry is matched on.
    identity: tuple[str, str]
    #: The node id, for people: it is what an entry in the manifest is written as.
    test: str
    #: "skip", or "xfail" for an expected failure, which junit files record as skipped too.
    kind: str
    reason: str


def junit_identity(test: str) -> tuple[str, str]:
    """The (classname, name) pytest's junit writer gives the test with this node id."""
    names = mangle_test_address(test)
    return ".".join(names[:-1]), names[-1]


def expected_skips(path: Path | None = None) -> dict[str, ExpectedSkip]:
    """The accepted skips by node id, or a refusal that names what is wrong with the file."""
    path = ROOT / EXPECTED_SKIPS if path is None else path
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ManifestRefused(f"{path} cannot be read: {error}") from error
    if document.get("profile") != EXPECTED_SKIPS_PROFILE:
        raise ManifestRefused(
            f"{path} has profile {document.get('profile')!r}; this runner reads "
            f"{EXPECTED_SKIPS_PROFILE} and no other"
        )
    if unknown := sorted(set(document) - {"profile", "skip"}):
        raise ManifestRefused(f"{path} has keys this runner does not read: {', '.join(unknown)}")
    accepted: dict[str, ExpectedSkip] = {}
    for position, entry in enumerate(document.get("skip", []), start=1):
        where = f"{path}, skip {position}"
        if not isinstance(entry, dict):
            raise ManifestRefused(f"{where} is not a table")
        if unknown := sorted(set(entry) - {"test", "reason", "only_without"}):
            raise ManifestRefused(f"{where} has fields this runner does not read: {unknown}")
        test, reason = entry.get("test"), entry.get("reason")
        # A node id names a test, or a whole module for a module skipped while it was collected.
        if not isinstance(test, str) or not ("::" in test or test.endswith(".py")):
            raise ManifestRefused(f"{where} names no test node id")
        if not isinstance(reason, str) or not reason:
            raise ManifestRefused(f"{where} gives no reason for skipping {test}")
        only_without = entry.get("only_without")
        if only_without is not None and (
            not isinstance(only_without, str)
            or not only_without
            or Path(only_without).is_absolute()
            or ".." in Path(only_without).parts
        ):
            raise ManifestRefused(
                f"{where} only_without must be a path inside the repository, not {only_without!r}"
            )
        if test in accepted:
            raise ManifestRefused(f"{where} names {test}, which an earlier entry names")
        accepted[test] = ExpectedSkip(test, reason, only_without)
    return accepted


def _node_id(classname: str, name: str) -> str:
    """The node id a junit case came from, found by asking which dotted prefix is a module here.

    pytest joins the module path and any class names with dots, so where the module ends is
    whichever prefix names a file. A case no file accounts for is shown as junit wrote it.
    """
    parts = classname.split(".") if classname else []
    for cut in range(len(parts), 0, -1):
        module = "/".join(parts[:cut]) + ".py"
        if (ROOT / module).is_file():
            return "::".join([module, *parts[cut:], name])
    if not classname:
        # A module skipped while it was collected: its case carries the module as its name.
        module = name.replace(".", "/") + ".py"
        if (ROOT / module).is_file():
            return module
    return f"{classname}::{name}" if classname else name


def _collection_skip_reason(details: str) -> str:
    """The reason inside a collection skip, which junit files keep only as the report's repr."""
    try:
        location = ast.literal_eval(details)
    except (ValueError, SyntaxError):
        return details
    if isinstance(location, tuple) and len(location) == 3 and isinstance(location[2], str):
        return location[2].removeprefix("Skipped: ")
    return details


def junit_skips(junit: Path) -> list[Skip]:
    """Every skipped case in one junit file, with the reason pytest recorded for it."""
    skips = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        for skipped in case.findall("skipped"):
            classname, name = case.get("classname", ""), case.get("name", "")
            reason = skipped.get("message", "")
            if reason == COLLECTION_SKIPPED:
                reason = _collection_skip_reason(skipped.text or "")
            kind = "xfail" if skipped.get("type") == "pytest.xfail" else "skip"
            skips.append(Skip((classname, name), _node_id(classname, name), kind, reason))
    return skips


def refused_skips(
    skips: Iterable[Skip], accepted: Mapping[str, ExpectedSkip], root: Path
) -> list[tuple[Skip, str]]:
    """Each skip no entry accepts, with the reason it is refused."""
    by_identity = {junit_identity(entry.test): entry for entry in accepted.values()}
    refused = []
    for skip in skips:
        entry = by_identity.get(skip.identity)
        if entry is None:
            refused.append((skip, "no entry names this test"))
        elif entry.reason != skip.reason:
            refused.append((skip, f"its entry accepts another reason: {entry.reason}"))
        elif entry.only_without is not None and (root / entry.only_without).exists():
            refused.append(
                (skip, f"its entry accepts it only without {entry.only_without}, which is here")
            )
    return refused


def _shown(skip: Skip) -> str:
    kind = "" if skip.kind == "skip" else f" ({skip.kind})"
    return f"  {skip.test}{kind}: {skip.reason}"


def check_skips(phase: str, junit: Path, accepted: Mapping[str, ExpectedSkip], code: int) -> int:
    """Print every skip a phase reported with its reason, and fail on one the manifest refuses.

    A failing exit code from pytest stays the exit code: a failure outranks a skip, and both are
    printed. A junit file that cannot be read is a run whose skips nobody checked, so it cannot
    exit zero either.
    """
    try:
        skips = junit_skips(junit)
    except (OSError, ET.ParseError) as error:
        print(
            f"run_backend_suite: the skips of {phase} could not be read from {junit}, so nothing "
            f"checked them against {EXPECTED_SKIPS}: {error}",
            flush=True,
        )
        return code or CANNOT_CHECK
    refused = refused_skips(skips, accepted, ROOT)
    if not skips:
        print(f"run_backend_suite: {phase} skipped no test", flush=True)
        return code
    counted = "1 test" if len(skips) == 1 else f"{len(skips)} tests"
    verdict = (
        f"and {EXPECTED_SKIPS} accepts every one"
        if not refused
        else f"and {EXPECTED_SKIPS} does not accept {len(refused)} of them"
    )
    print(f"run_backend_suite: {phase} skipped {counted}, {verdict}:")
    for skip in skips:
        print(_shown(skip))
    if not refused:
        sys.stdout.flush()
        return code
    print(
        "run_backend_suite: these did not run, and nothing decided that they need not, so this "
        "run is not the pass it reports:"
    )
    for skip, why in refused:
        print(f"{_shown(skip)}\n    refused: {why}")
    print(
        f"run_backend_suite: a skip that is intended is an entry in {EXPECTED_SKIPS}, with the "
        "reason pytest reports; any other is a finding",
        flush=True,
    )
    return code or UNNAMED_SKIP


def reference_junit(junit: str) -> Path:
    """Where phase 2 writes its junit file: a sibling of phase 1's, so neither overwrites it."""
    path = Path(junit)
    return path.with_name(f"{path.stem}-reference{path.suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--jobs", default="6", help="xdist workers for phase 1")
    parser.add_argument(
        "--reference-copy", default=DEFAULT_COPY_URL, help="the pinned copy phase 2 runs against"
    )
    parser.add_argument(
        "--without-reference-copy",
        action="store_true",
        help="run phase 1 only, and say which gate goes unexercised",
    )
    parser.add_argument("--plan", action="store_true", help="print what each phase would run")
    known, extra = parser.parse_known_args(list(argv) if argv is not None else None)
    print(tree_identity(), flush=True)
    try:
        accepted = expected_skips()
    except ManifestRefused as refusal:
        print(f"run_backend_suite: no phase was run, because {refusal}", flush=True)
        return CANNOT_CHECK
    copy_url = known.reference_copy
    junit, _ = _without_junit(extra)
    if junit is None and not known.plan:
        junit = str(Path(tempfile.mkdtemp(prefix="run_backend_suite-")) / "suite.xml")
        extra = [*extra, f"--junitxml={junit}"]
        print(
            f"run_backend_suite: no --junitxml was given, so the skips are read from {junit}",
            flush=True,
        )
    phase_one_extra, phase_two_extra = split_junit(extra)
    phase_one = ["-n", known.jobs, "-m", f"not {REFERENCE_MARKER}", *phase_one_extra]
    phase_two = ["-m", REFERENCE_MARKER, *phase_two_extra]

    if known.plan:
        print(f"phase 1: pytest {' '.join(phase_one)}")
        if known.without_reference_copy:
            print(f"phase 2: not run; tests marked {REFERENCE_MARKER} go unexercised")
        else:
            print(f"phase 2: pytest {' '.join(phase_two)} against {copy_url}")
        print(f"skips: each phase's are checked against the {len(accepted)} in {EXPECTED_SKIPS}")
        return 0
    assert junit is not None

    print("run_backend_suite: phase 1 of 2, parallel, each worker on a private server", flush=True)
    first = run(phase_one, phase_environment(private_servers=True, copy_url=copy_url))
    print(f"run_backend_suite: phase 1 finished with exit {first}", flush=True)
    first = check_skips("phase 1", Path(junit), accepted, first)

    if known.without_reference_copy:
        print(
            f"run_backend_suite: phase 2 was not run, so every test marked {REFERENCE_MARKER} went "
            "unexercised, and the frontier preflight gate with them",
            flush=True,
        )
        return first

    print(f"run_backend_suite: phase 2 of 2, serially against {copy_url}", flush=True)
    before = schemas(copy_url)
    if before is None:
        print(
            "run_backend_suite: phase 2 did not run, because the copy could not be read", flush=True
        )
        return first or CANNOT_CHECK

    second = run(phase_two, phase_environment(private_servers=False, copy_url=copy_url))
    if second == 5:
        print(
            "run_backend_suite: phase 2 selected no test, because this run was narrowed", flush=True
        )
        second = 0
    second = check_skips("phase 2", reference_junit(junit), accepted, second)
    after = schemas(copy_url)
    if after is None:
        print("run_backend_suite: could not re-read the copy after phase 2", flush=True)
        second = second or CANNOT_CHECK
    elif after != before:
        print("run_backend_suite: phase 2 changed the schemas of the copy, which it must not.")
        print(f"run_backend_suite: before: {' '.join(before)}")
        print(f"run_backend_suite: after:  {' '.join(after)}")
        print(
            "run_backend_suite: a killed run leaves its scratch schema behind; check that no "
            "connection is using the new one, then drop it by hand",
            flush=True,
        )
        second = second or LEFT_BEHIND
    else:
        print("run_backend_suite: phase 2 left the copy with the schemas it found", flush=True)
    print(f"run_backend_suite: phase 2 finished with exit {second}", flush=True)
    return first or second


if __name__ == "__main__":
    raise SystemExit(main())
