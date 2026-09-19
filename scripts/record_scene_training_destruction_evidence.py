"""Run the training destruction's acceptance and its falsification, and record what happened.

The break table in the record is PRODUCED by this script rather than retyped into it, and the
breaking is done by :mod:`scripts.falsify` rather than by a loop of this file's own. That is the
difference from ``record_scene_training_right_evidence.py``, which predates the tool and carries its
own restore: one tool that refuses to report a pass on a selection of zero, holds the original bytes
rather than trusting ``git`` to put them back, and compares the refusing test BY IDENTITY, is better
than a second copy of the same care.

**Three breaks in the first run of this table were NOT caught, and the tests moved rather than the
breaks.** A destroy question that answered for a tombstone of any scope, a cascade that reached
every photograph rather than the one its tombstone names, and a cascade that ran for a tombstone of
any scope all passed nineteen tests. Each was invisible for the same reason: the test that should
have claimed the property asked it in a situation where another clause made the right answer and the
wrong answer the same. The three tests that now pin them are named in the table below.

**The call sites are broken, not the callees**, for the first three cases. Deleting a trigger's
``create trigger`` statement leaves its function intact and asks whether anything reaches it;
breaking the function body asks only whether the body is right. Four guards in one lane on
2026-09-18 were proved correct with nothing proving they were reached.

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
sys.path.insert(0, str(ROOT / "scripts"))
from exulanica.canonical import canonical_json  # noqa: E402
from falsify import falsify  # noqa: E402

TESTS = ["tests/test_scene_training_destruction.py"]
SQL = "exulanica/migrations/0082_a_withdrawn_training_right_destroys_what_it_produced.sql"
WORKER = "exulanica/deletion/worker.py"
QUEUE = "exulanica/deletion/queue.py"
ROLES = "exulanica/db/roles.py"

#: The predecessor this work continues. v1 of this record named the right itself; v2 names v1,
#: because v1 bound a test file digest that moved when one over-specific assertion was replaced.
PREDECESSOR = "docs/evaluation/2026-09-19-scene-training-destruction.json"

#: One break each, applied alone to a committed tree, with the test that CLAIMS the property it
#: removes. ``expect`` is compared by identity by the tool, so a neighbouring test failing instead
#: is reported as a different finding rather than as success.
BREAKS: list[dict] = [
    {
        "name": "CALL SITE: the withdrawal never writes a tombstone (trigger not created)",
        "file": SQL,
        "old": "create trigger tg_scene_training_right_withdrawn_erases\n"
        "  after update on scene_training_right\n"
        "  for each row execute function tg_scene_training_right_withdrawn_erases();\n",
        "new": "-- the call site is gone; the function above is untouched\n",
        "tests": TESTS,
        "expect": "test_a_withdrawal_destroys_what_the_run_produced",
    },
    {
        "name": "CALL SITE: the tombstone never enqueues (cascade trigger not created)",
        "file": SQL,
        "old": "create trigger tg_scene_training_tombstone_cascade\n"
        "  after insert on tombstone\n"
        "  for each row execute function tg_scene_training_tombstone_cascade();\n",
        "new": "-- the call site is gone; the function above is untouched\n",
        "tests": TESTS,
        "expect": "test_a_withdrawal_destroys_what_the_run_produced",
    },
    {
        "name": "CALL SITE: the worker never asks the training question (dispatch entry removed)",
        "file": WORKER,
        "old": '    "scene_training": (\n'
        "        \"scene_training_withdrawal_releases_artifact(%(tombstone)s,decode(%(ref)s,'hex'))\"\n"
        "    ),\n",
        "new": "",
        "tests": TESTS,
        "expect": "test_a_withdrawal_destroys_what_the_run_produced",
    },
    {
        "name": "the destroy question always says yes",
        "file": SQL,
        "old": "  return\n    not exists (select 1 from capture c\n"
        "                 where c.blob_sha256 = p_bytes and c.deleted_at is null)",
        "new": "  return true or\n    not exists (select 1 from capture c\n"
        "                 where c.blob_sha256 = p_bytes and c.deleted_at is null)",
        "tests": TESTS,
        "expect": "test_a_withdrawal_does_not_destroy_bytes_a_standing_right_holds",
    },
    {
        "name": "the destroy question treats every holder as doomed",
        "file": SQL,
        "old": "            where b.workspace_id = a.workspace_id\n"
        "              and b.artifact_id = a.artifact_id\n"
        "              and r.withdrawn_at is not null));",
        "new": "            where b.workspace_id = a.workspace_id\n"
        "              and b.artifact_id = a.artifact_id));",
        "tests": TESTS,
        "expect": "test_a_withdrawal_does_not_destroy_bytes_a_standing_right_holds",
    },
    {
        "name": "the destroy question answers for a tombstone of any scope",
        "file": SQL,
        "old": "   where t.tombstone_id = p_tombstone and t.scope::text = 'scene_training';",
        "new": "   where t.tombstone_id = p_tombstone;",
        "tests": TESTS,
        "expect": "test_the_destroy_question_refuses_rather_than_answering_yes",
    },
    {
        "name": "the destroy question answers rather than raising on a hash nobody named",
        "file": SQL,
        "old": "    raise exception 'a training withdrawal was asked to release an absent content "
        "hash'\n      using errcode = 'null_value_not_allowed',\n"
        "            hint = 'Bytes nobody can name are bytes this cannot decide about.';",
        "new": "    return true;",
        "tests": TESTS,
        "expect": "test_the_destroy_question_refuses_rather_than_answering_yes",
    },
    {
        "name": "the cascade reaches every photograph, not the one the tombstone names",
        "file": SQL,
        "old": "   where b.workspace_id = new.workspace_id\n"
        "     and b.capture_id = new.capture_id\n"
        "     and r.withdrawn_at is not null",
        "new": "   where b.workspace_id = new.workspace_id\n     and r.withdrawn_at is not null",
        "tests": TESTS,
        "expect": "test_each_withdrawal_enqueues_only_its_own_photograph_s_reconstruction",
    },
    {
        "name": "the cascade enqueues bindings whose right still stands",
        "file": SQL,
        "old": "     and b.capture_id = new.capture_id\n     and r.withdrawn_at is not null\n"
        "     and a.content_sha256 is not null",
        "new": "     and b.capture_id = new.capture_id\n     and a.content_sha256 is not null",
        "tests": TESTS,
        "expect": "test_a_withdrawal_reaches_only_what_the_withdrawn_right_produced",
    },
    {
        "name": "the cascade runs for a tombstone of any scope",
        "file": SQL,
        "old": "  if new.scope::text <> 'scene_training' then\n    return new;\n  end if;",
        "new": "  if false then\n    return new;\n  end if;",
        "tests": TESTS,
        "expect": "test_an_interval_redaction_enqueues_no_reconstruction",
    },
    {
        "name": "the cascade enqueues an artefact whose bytes are already destroyed",
        "file": SQL,
        "old": "     and a.content_sha256 is not null\n     and a.purged_at is null\n  on conflict",
        "new": "     and a.content_sha256 is not null\n  on conflict",
        "tests": TESTS,
        "expect": "test_a_withdrawal_after_the_bytes_are_already_gone_enqueues_nothing",
    },
    {
        "name": "the tombstone names no photograph",
        "file": SQL,
        "old": "  values (new.workspace_id, 'scene_training', new.capture_id, new.withdrawn_by, "
        "new.withdrawn_at,",
        "new": "  values (new.workspace_id, 'scene_training', null, new.withdrawn_by, "
        "new.withdrawn_at,",
        "tests": TESTS,
        "expect": "test_a_withdrawal_destroys_what_the_run_produced",
    },
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


def suite() -> tuple[int, int]:
    """Run the whole file, with no ``-k`` filter, and refuse to read a summary that is not there."""
    result = subprocess.run(
        [".venv/bin/python", "-m", "pytest", *TESTS, "--tb=no", "-rf"],
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
    return int(match.group(1) or 0), int(match.group(2))


def predecessor_binding() -> dict:
    document = json.loads((ROOT / PREDECESSOR).read_bytes())
    return {
        "path": PREDECESSOR,
        "record_sha256": hashlib.sha256(canonical_json(document["record"])).hexdigest(),
        "why": (
            "v1 of this record, taken before one assertion in the test file was replaced: it "
            "pinned which of two missing grants an unprovisioned purge role hits first, which "
            "turned out to depend on whether an offline restore replay had run in the same "
            "process. v1 itself names the right whose withdrawal stopped at a refusal."
        ),
    }


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
    failed, passed = suite()
    if failed:
        raise SystemExit(f"{failed} failed before any break; falsification would mean nothing")

    os.environ["EXULANICA_TEST_POSTGRES"] = "private"
    breaks = []
    for case in BREAKS:
        result = falsify(case, [])
        print(f"{result['verdict']}\n  {result['name']}")
        if not result["restored"]:
            raise SystemExit(f"{case['name']!r}: the file was NOT restored")
        breaks.append(
            {
                "makes_true": case["name"],
                "file": case["file"],
                "claimed_by": case["expect"],
                "verdict": result["verdict"],
                "tests_asked": result["asked"],
                "refused": result["verdict"].startswith("REFUSED"),
                "tree_after_restore": "clean" if result["restored"] else "NOT RESTORED",
            }
        )
    unnoticed = [entry["makes_true"] for entry in breaks if not entry["refused"]]
    dirty = git("status", "--porcelain")
    if dirty:
        raise SystemExit(f"the tree is dirty after the breaks: {dirty}")

    record = {
        "profile": "exulanica.scene-training-destruction/v1",
        "tested_head": head,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "predecessor_record": predecessor_binding(),
        "acceptance": {
            "selectors": TESTS,
            "passed": passed,
            "failed": failed,
            "database": "private per-worker PostgreSQL (EXULANICA_TEST_POSTGRES=private)",
        },
        "falsification": {
            "method": (
                "scripts/falsify.py, one break at a time against a committed tree, the whole file "
                "run with no -k filter, the original bytes written back and the restore proved by "
                "digest, and the refusing test compared by identity against the test that claims "
                "the property"
            ),
            "breaks": breaks,
            "breaks_caught": len(breaks) - len(unnoticed),
            "breaks_total": len(breaks),
            "breaks_not_caught": unnoticed,
            "breaks_that_moved_the_tests": [
                "the destroy question answers for a tombstone of any scope",
                "the cascade reaches every photograph, not the one the tombstone names",
                "the cascade runs for a tombstone of any scope",
            ],
        },
        "source_files": [
            file_record(ROOT / relative)
            for relative in (
                SQL,
                WORKER,
                QUEUE,
                ROLES,
                *TESTS,
                "scripts/record_scene_training_destruction_evidence.py",
            )
        ],
        "what_this_does_not_solve": [
            "WHEN TRAINED BYTES ARE SHARED ACROSS WORKSPACES, A WITHDRAWAL MAY NEVER DESTROY "
            "ANYTHING. The purge role reads the binding and the withdrawal flag within one "
            "workspace only, so another workspace's artefact holding the same content hash cannot "
            "be shown to be withdrawn and blocks the destruction. That is the safe direction and a "
            "deliberate default, and it does not defer, it blocks permanently: nothing observes "
            "the other workspace's own later withdrawal. Whether a second holder's withdrawal "
            "should release the bytes, and by what mechanism, is an unanswered policy question. "
            "Measured, not inferred: the job skips and the only cross-workspace policy on the "
            "three tables the question reads is on artifact.",
            "A purge role provisioned before migration 0082 goes on draining every other tombstone "
            "and fails only a training-withdrawal job, with 'permission denied for function "
            "scene_training_withdrawal_releases_artifact', until it is re-provisioned in the "
            "ordinary migrations-then-roles order. Loud and local rather than closed and global, "
            "and measured with the grants revoked rather than reasoned from the grant shape.",
            "Two rights over one photograph, withdrawn separately, enqueue one object twice. That "
            "is a choice: a second job for one object is idempotent, and a uniqueness constraint "
            "collapsing them would make one tombstone's completion depend on another's job.",
            "A withdrawal whose right produced nothing still writes a tombstone, which then has no "
            "purge job and never records a purge completion. An entity tombstone over a person "
            "with no derivatives already behaves that way.",
        ],
        "limits": [
            "No GPU run, no remote host contacted, no download, no personal photograph trained on.",
            "Fixture photographs are generated test JPEGs and the published bundles are stand-in "
            "bytes; no real capture and no real trained artefact was destroyed.",
            "Destruction is not synchronous and cannot be: the purger is a separate process that "
            "correctly skips bytes another live capture still holds, so 0080's immediate read "
            "refusal remains what covers the interval before the bytes go.",
            "The cross-workspace half of the destroy question is measured with an artefact that "
            "carries no training binding at all. A second workspace whose own right stands was not "
            "built, because that needs a second workspace's captures and authorities; the "
            "mechanism is the same and the policy absence is measured directly.",
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
