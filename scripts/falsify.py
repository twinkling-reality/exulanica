"""Break the code on purpose and refuse to believe a green result.

WHY THIS EXISTS, measured 2026-09-18 in one evening of this lane:

  * a break that reversed a comparison PASSED every test, because the fixture's values made the
    right answer and the wrong answer the same number;
  * a break that changed how a path resolves PASSED every test, because the ``-k`` expression
    selected tests named after the CODE and the test that mattered was named after the PROPERTY.

Both runs were real: the tree was committed, the break was applied, pytest ran and reported success.
Neither run asked anything. A falsification that reports "no test noticed" is only evidence when it
can also show WHICH tests it put the question to, so this refuses to report a passing break without
naming the tests it selected and refusing a selection of none.

It does not use ``git`` to restore. The original bytes are held and written back, then the digest is
compared with the one taken before the edit, because a restore that cannot prove it restored is the
fault this file is about. Anything the break itself created on disk is NOT cleaned up: the final
check names it instead, so a dirty tree is reported rather than silently removed.

Usage:

    python scripts/falsify.py cases.json [-- pytest arguments]

where ``cases.json`` is a list of objects:

    {"name": "a drop counted as a step up",
     "file": "scripts/capture_visual_gate.mjs",
     "old": "the exact text to replace, which must occur exactly once",
     "new": "what to put there instead",
     "tests": ["tests/test_visual_gate_targets.py"],
     "expect": "test_a_drop_is_not_a_step_up"}

``expect`` is the test that CLAIMS the property the break removes. The case passes only when that
test fails; another test failing instead is reported as a different finding, because it means the
property is pinned somewhere other than where it is claimed. It is compared BY IDENTITY, against the
last segment of the failing node id with any parametrisation stripped, because matching a name as a
SUBSTRING would let ``test_x_at_the_end`` answer for ``test_x`` and the central verdict would read
true while being false.

THE LIMIT THIS CANNOT CLOSE, and the next reader will assume otherwise. ``tests`` is a SELECTION,
chosen by whoever wrote the case. A verdict of "nothing noticed" means NOTHING IN THE FILES NAMED
HERE claims the property; it does NOT mean nothing in the repository does. The tool cannot tell those
apart and does not try, which is why that verdict names the harness as the first suspect rather than
declaring the property untested.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_pytest(tests: list[str], arguments: list[str], report: Path) -> dict:
    """Run pytest over `tests` and read WHAT IT DID from the plugin's own report, not from its text.

    A missing report is a REFUSAL and never a fallback to parsing the summary. A fallback that
    activates silently is the whole fault this file exists to remove: it would turn "the plugin did
    not load" into a number that looks like a measurement.
    """
    environment = dict(os.environ)
    environment["FALSIFY_REPORT"] = str(report)
    environment["PYTHONPATH"] = str(ROOT / "scripts") + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "pytest", "-p", "falsify_plugin", *tests, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )
    if not report.exists():
        return {"collected": None, "failed": [], "exitstatus": result.returncode,
                "unreadable": (result.stdout + result.stderr)[-400:]}
    read = json.loads(report.read_text())
    read["exitstatus"] = result.returncode
    return read


def _claimed_by(failed: list[str], name: str) -> bool:
    """Did the test that CLAIMS this property fail, compared BY IDENTITY and not by resemblance?

    A node id is ``file::test_name`` with an optional ``[parameters]`` tail. Matching with ``in``
    would let ``test_a_drop_is_not_a_step_up_at_the_end`` answer for
    ``test_a_drop_is_not_a_step_up``, and this tool's central verdict, that the property is pinned
    where it is claimed, would read true while being false. That is the same fault as reaching into
    a shared list by position: addressing by something that RESEMBLES identity.
    """
    for nodeid in failed:
        last = nodeid.split("::")[-1]
        if last.split("[")[0] == name:
            return True
    return False


def falsify(case: dict, arguments: list[str]) -> dict:
    """Apply one break, ask the tests about it, put the file back, and report what happened."""
    path = ROOT / case["file"]
    original = path.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    text = original.decode("utf8")
    found = text.count(case["old"])
    if found != 1:
        # Nothing was written, so the file is untouched by definition: saying otherwise would raise
        # an alarm about a restore that never had to happen.
        return {
            "name": case["name"], "verdict": f"ANCHOR NOT UNIQUE: {found} occurrences",
            "selected": 0, "exit": None, "restored": True,
        }
    with TemporaryDirectory() as scratch:
        report = Path(scratch) / "falsify-report.json"
        try:
            path.write_text(text.replace(case["old"], case["new"]))
            ran = _run_pytest(case["tests"], arguments, report)
        finally:
            path.write_bytes(original)
    restored = _digest(path)
    selected = ran["collected"]
    if selected is None:
        verdict = "UNREADABLE: the plugin wrote no report, so this run measured nothing"
    elif selected == 0:
        verdict = "ASKED NOTHING: no test was selected"
    elif ran["exitstatus"] == 0:
        verdict = f"NOTHING NOTICED over {selected} tests, so the harness is the first suspect"
    elif _claimed_by(ran["failed"], case["expect"]):
        verdict = f"REFUSED by {case['expect']}, of {selected} selected"
    else:
        verdict = (f"refused, but NOT by {case['expect']}, of {selected} selected"
                   f" (by {', '.join(ran['failed']) or 'nothing named'})")
    return {
        "name": case["name"],
        "verdict": verdict,
        "selected": selected,
        "exit": ran["exitstatus"],
        "restored": restored == before,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    spec = Path(argv[0])
    arguments = argv[2:] if len(argv) > 1 and argv[1] == "--" else []
    cases = json.loads(spec.read_text())
    results = [falsify(case, arguments) for case in cases]
    worst = 0
    for result in results:
        print(f"{result['verdict']}\n  {result['name']}")
        if not result.get("restored", False):
            print("  THE FILE WAS NOT RESTORED to the bytes it had before this case")
            worst = 1
        if not result["verdict"].startswith("REFUSED"):
            worst = 1
    dirty = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    print(f"tree after: {dirty if dirty else '(clean)'}")
    if dirty:
        worst = 1
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
