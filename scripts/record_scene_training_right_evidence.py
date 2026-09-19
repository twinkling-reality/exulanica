"""Run the scene training right's acceptance and its falsification, and record what happened.

The break table in the record is PRODUCED by this script rather than retyped into it: each break is
applied alone to a committed tree, the WHOLE test file is run with no ``-k`` filter, and the tree is
restored with ``reset --hard`` plus ``clean`` with the restored state read back rather than assumed.

Three things here are deliberate and each is a fault this project has already paid for.

No ``-k`` filter anywhere. A filter that matches the CODE's vocabulary misses a test named after the
PROPERTY, and a lane nearly deleted a correct fix that way.

The pytest summary is parsed and the parse is ASSERTED to have found something before any number is
compared, because a run whose output changed shape reads as agreement.

The restored state is printed from ``git status`` rather than inferred from a command's exit code.
``checkout`` succeeding reports only that checkout had nothing to object to, and this repository has
recorded three separate ways that leaves the break standing.

Paths in the record are relative to the repository, never this machine's scratchpad.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exulanica.canonical import canonical_json  # noqa: E402

TESTS = "tests/test_scene_training_right.py"
SQL = "exulanica/migrations/0080_a_training_right_names_what_it_produces.sql"
MODULE = "exulanica/ingest/training_rights.py"

#: (what the break makes true, file, exact text, replacement). One break applied at a time.
BREAKS: list[tuple[str, str, str, str]] = [
    (
        "a personal photograph needs no right at all",
        SQL,
        "returns boolean language sql stable as $fn$\n  select coalesce(not (\n"
        "    p_workspace=current_workspace()",
        "returns boolean language sql stable as $fn$\n  select false and coalesce(not (\n"
        "    p_workspace=current_workspace()",
    ),
    (
        "a right's own term is never compared",
        SQL,
        "      and r.granted_at<=p_at and r.valid_until>p_at\n",
        "",
    ),
    ("a withdrawn right still allows", SQL, "      and r.withdrawn_at is null\n", ""),
    (
        "a right need not name this photograph",
        SQL,
        "    where r.workspace_id=p_workspace and r.right_id=p_right and r.capture_id=p_capture\n",
        "    where r.workspace_id=p_workspace and r.right_id=p_right\n",
    ),
    ("a right need not name this destination", SQL, "      and r.destination=p_destination\n", ""),
    (
        "a lapsed personal authority still allows",
        SQL,
        "      and a.authorized_at<=p_at and (a.valid_until is null or a.valid_until>p_at));",
        "      and a.authorized_at<=p_at);",
    ),
    (
        "nothing refuses the publication",
        SQL,
        "create trigger tg_scene_training_publication_right\nbefore insert on artifact\n"
        "for each row execute function tg_scene_training_publication_right();",
        "",
    ),
    (
        "nothing refuses the queued run",
        SQL,
        "create trigger tg_scene_training_member_right\n"
        "before insert on reconstruction_scene_job_member\n"
        "for each row execute function tg_scene_training_member_right();",
        "",
    ),
    (
        "an artefact is never bound to the right that permitted it",
        SQL,
        "create trigger tg_scene_training_artifact_binds\nafter insert on artifact\n"
        "for each row execute function tg_scene_training_artifact_binds();",
        "",
    ),
    (
        "the database accepts a loopback destination",
        SQL,
        "      or destination ~ "
        "'^rented-host:[a-z][a-z0-9_-]{0,31}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')",
        "      or destination ~ "
        "'^rented-host:[a-z][a-z0-9_-]{0,31}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$'"
        "\n      or destination ~ '^https?://localhost(:[1-9][0-9]{0,4})?$')",
    ),
    (
        "python accepts a loopback destination",
        MODULE,
        '    if host == "localhost" or host == "127.0.0.1" or host.startswith("127."):',
        "    if False:",
    ),
    (
        "a job need not say where the bytes go",
        SQL,
        "  if v_destination is null then\n",
        "  if false then\n",
    ),
]

SUMMARY = re.compile(r"(?:(\d+) failed, )?(\d+) passed")


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def file_record(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def restore() -> str:
    """Put the tree back and READ BACK what it actually looks like."""
    git("reset", "-q", "--hard", "HEAD")
    git("clean", "-qfd")
    status = git("status", "--porcelain")
    return status if status else "clean"


def suite() -> tuple[int, int, list[str]]:
    """Run the whole file. Returns (failed, passed, the names of the tests that failed)."""
    result = subprocess.run(
        [".venv/bin/python", "-m", "pytest", TESTS, "--tb=no", "-rf"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "EXULANICA_TEST_POSTGRES": "private"},
        check=False,
    )
    text = result.stdout + result.stderr
    match = SUMMARY.search(text)
    if match is None:
        raise SystemExit(f"no pytest summary to read; the run said:\n{text[-3000:]}")
    names = re.findall(r"^FAILED [^:]+::(\S+)", text, re.MULTILINE)
    return int(match.group(1) or 0), int(match.group(2)), names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise SystemExit("docs/evaluation is append-only; use a new path")
    if git("status", "--porcelain"):
        raise SystemExit("refusing to break a dirty tree; commit first")

    head = git("rev-parse", "HEAD")
    failed, passed, _ = suite()
    if failed:
        raise SystemExit(f"{failed} failed before any break; falsification would mean nothing")

    breaks = []
    for claim, relative, old, new in BREAKS:
        path = ROOT / relative
        text = path.read_text()
        if text.count(old) != 1:
            raise SystemExit(f"{claim!r}: break text appears {text.count(old)} times in {relative}")
        path.write_text(text.replace(old, new))
        broken_failed, broken_passed, names = suite()
        state = restore()
        print(f"{broken_failed:>2} failed | {claim}")
        breaks.append(
            {
                "makes_true": claim,
                "file": relative,
                "tests_failed": broken_failed,
                "tests_passed": broken_passed,
                "caught_by": names,
                "tree_after_restore": state,
            }
        )
        if state != "clean":
            raise SystemExit(f"tree not restored after {claim!r}: {state}")

    unnoticed = [entry["makes_true"] for entry in breaks if not entry["tests_failed"]]
    record = {
        "profile": "exulanica.scene-training-right/v1",
        "tested_head": head,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "acceptance": {
            "selector": TESTS,
            "passed": passed,
            "failed": failed,
            "database": "private per-worker PostgreSQL (EXULANICA_TEST_POSTGRES=private)",
        },
        "falsification": {
            "method": (
                "each break applied alone to a committed tree, the whole file run with no -k "
                "filter, the tree restored with reset --hard plus clean and the restored state "
                "read back from git status"
            ),
            "breaks": breaks,
            "breaks_caught": len(breaks) - len(unnoticed),
            "breaks_total": len(breaks),
            "breaks_not_caught": unnoticed,
        },
        "source_files": [
            file_record(ROOT / relative)
            for relative in (SQL, MODULE, TESTS, "scripts/record_scene_training_right_evidence.py")
        ],
        "limits": [
            "No GPU run, no remote host contacted, no personal photograph trained on.",
            "Withdrawal refuses every further read and records what a destruction must reach; it "
            "does not enqueue destruction, which reaches 0013 and 0015 purge invariants.",
            "The read refusal is enforced in Python under the final read check, not by the "
            "database: PostgreSQL cannot refuse a SELECT the way it refuses a write. What the "
            "database enforces is publication.",
            "Fixture photographs are generated test JPEGs; no real capture was used.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
            }
        )
    )
    print(json.dumps({"written": output.relative_to(ROOT).as_posix(), "unnoticed": unnoticed}))


if __name__ == "__main__":
    main()
