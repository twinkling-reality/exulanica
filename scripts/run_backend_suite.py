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
forgotten.

The copy is irreplaceable: it has no structural snapshot. This script never writes to it. The
harness creates one scratch schema there, applies the migrations into it and drops it in a finally,
so a failing test still drops it and only a killed process leaves one behind; this script lists the
schemas before and after phase 2 and refuses to be quiet if that set changed.

Without a copy to run against, pass --without-reference-copy. It runs phase 1 alone and says which
gate went unexercised, because a suite that omits this one silently is the state this script exists
to end.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

#: The tests that need the pinned endpoint, named by their own marker rather than by a list here.
REFERENCE_MARKER = "reference_copy"
#: The one local copy of retained data these tests may be pointed at.
DEFAULT_COPY_URL = "postgresql://localhost:5433/exulanica_inspect_test"
#: Exit codes of this script itself, distinct from pytest's.
CANNOT_CHECK = 70
LEFT_BEHIND = 75
ROOT = Path(__file__).resolve().parents[1]
#: How long to wait for git before giving up on provenance: a header never holds up the suite.
GIT_TIMEOUT_SECONDS = 5
#: How many differing paths the header names before it stops counting them out.
NAMED_DIFFERENCES = 3


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


def split_junit(arguments: Sequence[str]) -> tuple[list[str], list[str]]:
    """Phase 1 keeps a caller's junit path; phase 2 writes a sibling, so neither overwrites it."""
    phase_two: list[str] = []
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
            phase_two.append(argument)
    if junit is not None:
        path = Path(junit)
        sibling = path.with_name(f"{path.stem}-reference{path.suffix}")
        phase_two.append(f"--junitxml={sibling}")
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
    copy_url = known.reference_copy
    phase_one_extra, phase_two_extra = split_junit(extra)
    phase_one = ["-n", known.jobs, "-m", f"not {REFERENCE_MARKER}", *phase_one_extra]
    phase_two = ["-m", REFERENCE_MARKER, *phase_two_extra]

    if known.plan:
        print(f"phase 1: pytest {' '.join(phase_one)}")
        if known.without_reference_copy:
            print(f"phase 2: not run; tests marked {REFERENCE_MARKER} go unexercised")
        else:
            print(f"phase 2: pytest {' '.join(phase_two)} against {copy_url}")
        return 0

    print("run_backend_suite: phase 1 of 2, parallel, each worker on a private server", flush=True)
    first = run(phase_one, phase_environment(private_servers=True, copy_url=copy_url))
    print(f"run_backend_suite: phase 1 finished with exit {first}", flush=True)

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
