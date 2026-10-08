"""A test reads the clock when it runs, never when its module is imported.

A serial run imports every module first and reaches a module's last test hours later (main's
serial run takes over three hours). An instant read at import, such as a grant's end an hour
ahead, has passed by then: a gate's choice ended before its test asked who it decides for, so
the test failed in the serial run and passed in every shorter parallel part. So no test module
reads the clock in a statement run at import: a module or class body, a default argument or a
decorator. A test or fixture reads it in its own body.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
#: The calls that read a clock, by the name they are called through.
CLOCK_READS = frozenset(
    {"now", "utcnow", "today", "time", "time_ns", "monotonic", "monotonic_ns", "perf_counter"}
)
#: The modules or classes a clock is read through.
CLOCKS = frozenset({"datetime", "date", "time"})


def _reads_the_clock(node: ast.AST) -> bool:
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        named = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
        if call.func.attr in CLOCK_READS and named in CLOCKS:
            return True
    return False


def _run_at_import(tree: ast.Module) -> list[ast.AST]:
    """The statements and expressions of a module evaluated when it is imported."""
    found: list[ast.AST] = []

    def body(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                found.extend(statement.decorator_list)
                found.extend(statement.args.defaults)
                found.extend(d for d in statement.args.kw_defaults if d is not None)
            elif isinstance(statement, ast.ClassDef):
                found.extend(statement.decorator_list)
                body(statement.body)
            else:
                found.append(statement)

    body(tree.body)
    return found


def clock_reads_at_import(source: str) -> list[int]:
    """The lines of ``source`` that read the clock when the module is imported."""
    return sorted(
        {node.lineno for node in _run_at_import(ast.parse(source)) if _reads_the_clock(node)}
    )


def test_no_test_module_reads_the_clock_when_it_is_imported():
    found = {
        str(path.relative_to(TESTS)): lines
        for path in sorted(TESTS.rglob("*.py"))
        if (lines := clock_reads_at_import(path.read_text(encoding="utf-8")))
    }
    assert found == {}, f"read the clock in the test, not at import: {found}"


def test_the_guard_finds_an_instant_read_at_import_and_passes_one_read_in_a_test():
    at_import = """
from datetime import UTC, datetime, timedelta
import time

ENDS = datetime.now(UTC) + timedelta(hours=1)

class Fixture:
    started = time.monotonic()

def ends(at=datetime.now(UTC)):
    return at
"""
    assert clock_reads_at_import(at_import) == [5, 8, 10]
    in_the_test = """
from datetime import UTC, datetime, timedelta

def _an_hour_from_now():
    return datetime.now(UTC) + timedelta(hours=1)

def test_ends():
    assert _an_hour_from_now() > datetime.now(UTC)
"""
    assert clock_reads_at_import(in_the_test) == []
