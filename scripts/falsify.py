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
property is pinned somewhere other than where it is claimed.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_pytest(tests: list[str], arguments: list[str]) -> tuple[str, int]:
    """Run pytest over `tests` and hand back its output and exit code."""
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-m", "pytest", *tests, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr, result.returncode


def _selected(output: str) -> int:
    """How many tests pytest actually ran, from its own final summary line.

    THE NUMBER THIS FILE EXISTS FOR. A selection of zero exits 5 and prints "no tests ran", which
    reads as a clean run to anything that only looks at whether something failed.

    Read off the LAST line carrying counts, so a traceback quoting these words cannot inflate it.
    It must not look for pytest's "=" banner: THIS PROJECT ALREADY PASSES -q IN ADDOPTS, so the
    summary arrives undecorated as "35 passed in 5.87s", and the first version of this function
    returned 0 for every run and reported a real falsification as having asked nothing. "deselected"
    is deliberately not one of the words counted.
    """
    counted = 0
    for line in output.splitlines():
        found = re.findall(r"(\d+) (passed|failed|errors?|xfailed|xpassed)\b", line)
        if found:
            counted = sum(int(number) for number, _ in found)
    return counted


def _failed_by(output: str, name: str) -> bool:
    """Did the test that CLAIMS this property fail, as opposed to some other test failing?"""
    tail = output.split("short test summary info")[-1]
    return any(line.startswith("FAILED") and name in line for line in tail.splitlines())


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
    try:
        path.write_text(text.replace(case["old"], case["new"]))
        output, code = _run_pytest(case["tests"], arguments)
    finally:
        path.write_bytes(original)
    restored = _digest(path)
    selected = _selected(output)
    expected_failed = _failed_by(output, case["expect"])
    if selected == 0:
        verdict = "ASKED NOTHING: no test was selected"
    elif code == 0:
        verdict = f"NOTHING NOTICED over {selected} tests, so the harness is the first suspect"
    elif expected_failed:
        verdict = f"REFUSED by {case['expect']}, of {selected} selected"
    else:
        verdict = f"refused, but NOT by {case['expect']}, of {selected} selected"
    return {
        "name": case["name"],
        "verdict": verdict,
        "selected": selected,
        "exit": code,
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
