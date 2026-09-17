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
