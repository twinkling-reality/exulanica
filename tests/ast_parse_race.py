"""``ast.parse`` with garbage collection held off, for test sessions on CPython 3.11 before 3.11.8.

Those releases keep the AST constructor's recursion depth in state the whole interpreter shares
(CPython gh-106905, fixed in 3.11.8). The constructor runs no Python code of its own, so a thread
inside it keeps the GIL, except when an allocation starts a garbage collection: the finalizers,
weakref callbacks and gc callbacks a collection runs are Python code, and the thread can hand the
GIL to another there. If that thread calls ``ast.parse`` too, it resets the shared depth, and the
first call raises ``SystemError: AST constructor recursion depth mismatch`` for a tree it built
correctly. On 3.11, formatting a traceback calls ``ast.parse`` for its caret lines, so any thread
that prints a traceback while a source-scanning test walks the package can fail that test.

With collection held off until the parse returns, the constructor runs no Python code, so no other
thread runs while it builds the tree. Nothing is caught or retried: a syntax error, and every
other error, is raised as the interpreter raises it. ``tests/conftest.py`` installs this on the
releases that have the race.
"""

from __future__ import annotations

import ast
import contextlib
import gc
import sys
import threading
from collections.abc import Callable
from typing import Any

#: The first 3.11 release whose AST constructor counts its recursion depth per call.
FIXED_IN = (3, 11, 8)

#: The message the race raises. A ``SystemError`` with any other message is not this race.
MISMATCH = "AST constructor recursion depth mismatch"

#: ``ast.parse`` as the interpreter defines it.
INTERPRETER_PARSE = ast.parse


def affected(version: tuple[int, ...] = sys.version_info[:3]) -> bool:
    """Whether ``version`` shares the depth between threads: 3.11 before 3.11.8."""
    return tuple(version[:2]) == (3, 11) and tuple(version[:3]) < FIXED_IN


def parse_without_collecting(*args: Any, **kwargs: Any) -> Any:
    """``ast.parse``, with garbage collection held off until it returns."""
    collecting = gc.isenabled()
    try:
        gc.disable()
        return INTERPRETER_PARSE(*args, **kwargs)
    finally:
        if collecting:
            gc.enable()


def install() -> None:
    """Give the session ``parse_without_collecting`` as ``ast.parse``, where the race exists."""
    if affected():
        ast.parse = parse_without_collecting


def contend(parses: int = 100, enough_failures: int = 5) -> dict[str, dict[str, int]]:
    """Parse a 300-line module under forced contention, with collection held off and without.

    Another thread parses all the while. A gc callback and a low threshold make collections
    inside the AST constructor frequent and make them run Python code, and a one-microsecond
    switch interval hands the GIL over at every chance. The interpreter's own parse stops at
    ``enough_failures``. This changes process-wide state, so run it in a process of its own.
    """
    source = "\n".join(f"value_{i} = [{i}, {{'k': ({i}, {i} + 1)}}]" for i in range(300))
    stop = threading.Event()
    elsewhere = [0]

    def parse_elsewhere() -> None:
        while not stop.is_set():
            with contextlib.suppress(SystemError):
                INTERPRETER_PARSE("x + 1")
            elsewhere[0] += 1

    def arm(parse: Callable[[str], Any], stop_at: int) -> dict[str, int]:
        done = failures = 0
        before = elsewhere[0]
        while done < parses and failures < stop_at:
            try:
                parse(source)
            except SystemError as error:
                if MISMATCH not in str(error):
                    raise
                failures += 1
            done += 1
        return {"parses": done, "failures": failures, "parses_elsewhere": elsewhere[0] - before}

    gc.callbacks.append(lambda phase, info: None)
    gc.set_threshold(100, 10, 10)
    sys.setswitchinterval(1e-6)
    thread = threading.Thread(target=parse_elsewhere, daemon=True)
    thread.start()
    try:
        return {
            "interpreter": arm(INTERPRETER_PARSE, enough_failures),
            "without_collecting": arm(parse_without_collecting, parses + 1),
        }
    finally:
        stop.set()
        thread.join()
