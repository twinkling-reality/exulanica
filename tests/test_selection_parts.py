"""The parts ``--part K/N`` splits a selection into, so that N jobs run it once between them.

Continuous integration runs phase 1 of the backend suite in parts, each on a runner of its own.
That is only the same suite if every test lands in exactly one part, whichever job collected it, so
a test's part is a digest of its node id and nothing else. What is held here: the parts cover a
selection exactly once, they come out near equal, and the option ``tests/conftest.py`` adds keeps
the right tests when pytest itself collects them.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from conftest import chosen_part, part_of

ROOT = Path(__file__).resolve().parents[1]

#: The file collected for real below: this one, whose tests need no database.
PROBE = str(Path(__file__).resolve().relative_to(ROOT))


@pytest.mark.parametrize("parts", [1, 2, 3, 4])
def test_every_test_is_in_exactly_one_part_and_the_parts_are_near_equal(parts):
    nodeids = [f"tests/test_probe.py::test_{number}" for number in range(6000)]
    counted = Counter(part_of(nodeid, parts) for nodeid in nodeids)
    assert sorted(counted) == list(range(1, parts + 1))
    assert sum(counted.values()) == len(nodeids)
    assert max(counted.values()) - min(counted.values()) < 0.1 * len(nodeids) / parts


def test_each_parametrized_case_is_a_test_of_its_own():
    """The node id is the whole key, so the cases of one function spread over the parts."""
    cases = {part_of(f"tests/test_api.py::test_x[{case}]", 3) for case in range(30)}
    assert cases == {1, 2, 3}


@pytest.mark.parametrize("written", ["0/3", "4/3", "3", "1/0", "a/3", "1/3/1", " 1/3", "-1/3"])
def test_a_part_that_names_no_part_of_n_is_refused(written):
    with pytest.raises(pytest.UsageError, match="--part takes K/N"):
        chosen_part(written)


def test_one_of_one_and_the_last_part_are_accepted():
    assert chosen_part("1/1") == (1, 1)
    assert chosen_part("3/3") == (3, 3)


def _collected(*arguments: str) -> list[str]:
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            PROBE,
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # 5 is pytest's exit for a run that collected nothing, which a part of a few tests may be.
    assert finished.returncode in (0, 5), finished.stdout + finished.stderr
    return [line.strip() for line in finished.stdout.splitlines() if "::" in line]


def test_pytests_own_collection_puts_each_test_in_the_part_its_node_id_names():
    """The option itself, through conftest's collection hook: the parts partition the file."""
    everything = _collected()
    assert len(everything) > 3, "the probe file has too few tests to split"
    parts = {part: _collected("--part", f"{part}/3") for part in (1, 2, 3)}
    assert sorted(nodeid for found in parts.values() for nodeid in found) == sorted(everything)
    for part, found in parts.items():
        assert all(part_of(nodeid, 3) == part for nodeid in found), part
