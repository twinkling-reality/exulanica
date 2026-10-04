"""A source-scanning test's ``ast.parse`` cannot lose the CPython 3.11 depth race.

The race and the remedy are described in ``tests/ast_parse_race.py``. The contended measurement
runs in a process of its own, because it changes the collector's threshold and the GIL's switch
interval for the whole process.
"""

from __future__ import annotations

import ast
import gc
import json
import subprocess
import sys
from pathlib import Path

import pytest

import ast_parse_race

TESTS = Path(__file__).resolve().parent


def test_a_parse_without_collecting_survives_the_race_the_interpreter_parse_loses():
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, ast_parse_race; print(json.dumps(ast_parse_race.contend()))",
        ],
        cwd=TESTS,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    result = json.loads(child.stdout)
    held, interpreter = result["without_collecting"], result["interpreter"]
    assert held["failures"] == 0, result
    assert held["parses"] == 100, result
    assert held["parses_elsewhere"] >= 100, result
    # The positive control: on a release with the race, the interpreter's own parse loses it under
    # the same contention. On a fixed release it cannot.
    assert (interpreter["failures"] > 0) == ast_parse_race.affected(), result


@pytest.mark.parametrize("collecting", [True, False], ids=["collecting", "held-off"])
def test_a_syntax_error_is_raised_and_the_collector_is_left_as_it_was(collecting):
    was = gc.isenabled()
    if collecting:
        gc.enable()
    else:
        gc.disable()
    try:
        with pytest.raises(SyntaxError):
            ast_parse_race.parse_without_collecting("def broken(:\n")
        assert gc.isenabled() is collecting
        assert isinstance(ast_parse_race.parse_without_collecting("x = 1"), ast.Module)
        assert gc.isenabled() is collecting
    finally:
        if was:
            gc.enable()
        else:
            gc.disable()


def test_the_session_parses_without_collecting_where_the_race_exists():
    assert ast_parse_race.affected((3, 11, 0))
    assert ast_parse_race.affected((3, 11, 7))
    assert not ast_parse_race.affected((3, 11, 8))
    assert not ast_parse_race.affected((3, 12, 0))
    installed = ast.parse is ast_parse_race.parse_without_collecting
    assert installed == ast_parse_race.affected()
