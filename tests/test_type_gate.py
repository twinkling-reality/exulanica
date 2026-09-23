"""The union-attr gate: what it counts, what it refuses, and the tree held to its baseline.

``scripts/type_gate.py`` runs the mypy the uv archive cache holds, counts one error code per file
and fails when a count rises. The last test runs it over this package. Where no mypy is cached it
skips, saying so, and the backend runner refuses that skip because its manifest does not name it,
so a machine that loses the checker fails loudly instead of passing quietly.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import type_gate as gate  # noqa: E402

#: Real lines of mypy's output, including the trap a text search falls into: the note that an
#: ignore comment names ``union-attr`` mentions the code and is not an error of it. MEASURED
#: 2026-09-23 at e9dee3c2: grep counted 45 lines naming the code, and 5 of them were such notes.
_OUTPUT = "\n".join(
    (
        'exulanica/a.py:12: error: Item "None" of "Ground | None" has no attribute'
        ' "half_width_mm"  [union-attr]',
        'exulanica/a.py:40: error: Item "str" of "str | int" has no attribute "bit_length"'
        "  [union-attr]",
        'exulanica/a.py:41: error: No overload variant of "execute" matches argument types "str"'
        "  [call-overload]",
        'exulanica/b.py:7:9: error: Item "None" of "Path | None" has no attribute "name"'
        "  [union-attr]",
        'exulanica/c.py:710: note: Error code "attr-defined" not covered by'
        ' "type: ignore[union-attr]" comment',
        "Found 4 errors in 2 files (checked 3 source files)",
    )
)


def test_only_errors_of_the_code_are_counted_and_a_note_naming_it_is_not():
    measured = gate.parse(_OUTPUT)
    assert measured.checked == 3
    assert len(measured.errors) == 4
    assert measured.counts() == {"exulanica/a.py": 2, "exulanica/b.py": 1}
    assert measured.counts("call-overload") == {"exulanica/a.py": 1}


def test_a_clean_run_is_a_measurement_and_a_crash_is_not():
    assert gate.parse("Success: no issues found in 7 source files\n").counts() == {}
    with pytest.raises(gate.CannotCheck, match="did not finish with its summary"):
        gate.parse("Traceback (most recent call last):\n  ImportError: cannot import mypy\n")
    with pytest.raises(gate.CannotCheck, match="did not finish with its summary"):
        gate.parse("")


def test_a_rise_in_one_file_fails_even_when_another_file_fell_by_as_much():
    baseline = {"exulanica/a.py": 2, "exulanica/b.py": 1}
    assert gate.compare(baseline, baseline) == ([], [])
    rises, falls = gate.compare({"exulanica/a.py": 1, "exulanica/b.py": 2}, baseline)
    assert rises == ["exulanica/b.py: 2, baseline 1"]
    assert falls == ["exulanica/a.py: 1, baseline 2"]
    rises, _ = gate.compare({**baseline, "exulanica/new.py": 1}, baseline)
    assert rises == ["exulanica/new.py: 1, baseline 0", "total: 4, baseline 3"]
    rises, falls = gate.compare({"exulanica/a.py": 2}, baseline)
    assert rises == []
    assert falls == ["exulanica/b.py: 0, baseline 1", "total: 2, baseline 3"]


def _wheel(archive: Path, entry: str, name: str, version: str, tag: str, requires=()) -> Path:
    info = archive / entry / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "WHEEL").write_text(f"Wheel-Version: 1.0\nTag: {tag}\n")
    lines = [f"Name: {name}", f"Version: {version}", *(f"Requires-Dist: {r}" for r in requires)]
    (info / "METADATA").write_text("\n".join(lines) + "\n")
    return archive / entry


def test_the_checker_is_assembled_from_the_cache_by_what_its_metadata_requires(tmp_path):
    requires = (
        "dependency>=1.0",
        'only-for-an-extra; extra == "reports"',
        'only-for-old-pythons; python_version < "3.0"',
        "not-in-the-cache>=1",
    )
    mypy = _wheel(tmp_path, "a", "mypy", "9.9.9", "py3-none-any", requires)
    old = _wheel(tmp_path, "b", "dependency", "0.9", "py3-none-any")
    new = _wheel(tmp_path, "c", "dependency", "1.2", "py3-none-any")
    _wheel(tmp_path, "d", "only-for-an-extra", "1.0", "py3-none-any")
    checker = gate.find_checker(tmp_path)
    assert (checker.version, checker.python, checker.path) == ("9.9.9", sys.executable, (mypy, new))
    assert old not in checker.path
    with pytest.raises(gate.CheckerAbsent, match=re.escape("holds no mypy 1.0, only 9.9.9")):
        gate.find_checker(tmp_path, "1.0")


def test_a_checker_built_for_an_interpreter_this_machine_lacks_is_absent(tmp_path):
    _wheel(tmp_path, "a", "mypy", "9.9.9", "cp399-cp399-macosx_11_0_arm64")
    lacking = re.escape("built for cp399, and no python3.99 is on PATH")
    with pytest.raises(gate.CheckerAbsent, match=lacking):
        gate.find_checker(tmp_path)
    with pytest.raises(gate.CheckerAbsent, match="holds no mypy, only no version of it"):
        gate.find_checker(tmp_path / "empty")


def test_a_baseline_measured_another_way_is_refused_rather_than_compared(tmp_path):
    good = {
        "profile": gate.BASELINE_PROFILE,
        "code": gate.CODE,
        "checker": {"mypy": "2.3.1", "target": gate.TARGET, "arguments": list(gate.ARGUMENTS)},
        "counts": {},
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(good))
    assert gate.read_baseline(path) == good
    for changed in (
        {"profile": "exulanica.type-gate-baseline/v0"},
        {"code": "attr-defined"},
        {"checker": {**good["checker"], "arguments": ["--strict"]}},
    ):
        path.write_text(json.dumps({**good, **changed}))
        with pytest.raises(gate.CannotCheck):
            gate.read_baseline(path)


def test_no_file_in_the_package_has_more_union_attr_errors_than_its_baseline():
    """The gate itself, over this package, with the mypy version the baseline names.

    A skip here means no such mypy is cached on this machine. Any other refusal, a checker that
    cannot see the control's one error or a mypy that crashed, fails: it is a broken gate, not a
    missing tool.
    """
    baseline = gate.read_baseline(ROOT / gate.BASELINE)
    try:
        checker, measured = gate.measure(ROOT, baseline["checker"]["mypy"])
    except gate.CheckerAbsent as absent:
        pytest.skip(f"the union-attr gate cannot run on this machine: {absent}")
    assert measured.checked > 0
    rises, falls = gate.compare(measured.counts(), baseline["counts"])
    assert rises == [], (
        f"mypy {checker.version} reports more {gate.CODE} errors than {gate.BASELINE} allows:\n  "
        + "\n  ".join(rises)
    )
    if falls:
        # A fall passes. It is reported where every suite run shows its warnings, so the baseline
        # can be lowered by whoever sees it rather than left with room for a new error.
        warnings.warn(
            f"{gate.CODE} errors fell below {gate.BASELINE}; lower it with "
            "`uv run python scripts/type_gate.py --write-baseline`:\n  " + "\n  ".join(falls),
            stacklevel=1,
        )


def test_a_checker_that_cannot_see_the_code_is_refused_before_it_measures(monkeypatch):
    """The control's own break check: the same mypy, told to hide the code, is refused."""
    version = gate.read_baseline(ROOT / gate.BASELINE)["checker"]["mypy"]
    try:
        checker = gate.find_checker(gate.uv_archive(), version)
    except gate.CheckerAbsent as absent:
        pytest.skip(f"the union-attr gate cannot run on this machine: {absent}")
    gate.control(checker)
    monkeypatch.setattr(gate, "ARGUMENTS", (*gate.ARGUMENTS, "--disable-error-code", gate.CODE))
    with pytest.raises(gate.CannotCheck, match="did not report the one union-attr error"):
        gate.control(checker)
