"""The final read check is stated once, in :mod:`exulanica.db.read_check`, and reached from there.

Two halves. First the helper's own refusals, against PostgreSQL: a connection inside a transaction
is refused in the caller's words before anything is sent, and a busy lock is refused rather than
waited for when the caller will not wait, whether it tells the helper or sets its session's lock
timeout. What each caller does under the check is held in
``tests/test_final_read_check_callers.py``.

Then the ratchet, in the style of ``tests/test_workspace_lock.py``. A module that takes
``asset_read_lock()`` inside a read-only transaction by hand fails, and so does a module that
restates the key the lock takes. Taking the lock inside a writer's own transaction is a different
act, and the modules that do it are listed with their reasons and counts; the list may only shrink.
What the scan cannot see is SQL assembled from fragments that never spell the function's name,
which is why the helper, not a copy, is the way a module makes the check.
"""

from __future__ import annotations

import ast
import datetime as dt
import pathlib
import re
from collections.abc import Iterator

import psycopg
import pytest
from exulanica.db import read_check
from exulanica.db.read_check import AssetReadLockBusy, ConnectionNotIdle, final_read_check
from psycopg.pq import TransactionStatus

from test_final_read_check_callers import OPENING, WILL_NOT_WAIT, Recording

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = "exulanica/db/read_check.py"
MIGRATION = ROOT / "exulanica/migrations/0041_guard_asset_reads_with_current_permission.sql"

#: Modules that take ``asset_read_lock()`` by hand, with how many times. Each takes it inside a
#: writer's own transaction, not as a final read check. May only shrink.
IN_A_WRITERS_TRANSACTION = {
    # An authored edit asks its source authority again under the lock, inside the edit's own
    # transaction, after the edit's rows are written and immediately before it commits.
    "exulanica/world/environment_source_authority.py": 1,
    "exulanica/world/point_map_source_authority.py": 1,
    # A society input is recorded in its writer's transaction, under the workspace lock first and
    # the asset read lock second, the order every writer that takes both keeps.
    "exulanica/api/society_runtime.py": 2,
}

#: The sentence the helper's refusal carries in these tests.
NOT_IDLE = "a test read is checked only on an idle connection"

#: A bound on every statement while another connection holds the lock, so that a check which waits
#: when told not to fails with QueryCanceled instead of hanging the run.
HANG_GUARD = "5s"

_TAKES_THE_LOCK = re.compile(r"\basset_read_lock\b")
_READ_ONLY = re.compile(r"\bread\s+only\b", re.IGNORECASE)


def _lock_key() -> int:
    """The advisory key ``asset_read_lock()`` takes, read from the migration that defines it."""
    text = MIGRATION.read_text(encoding="utf-8")
    body = re.search(r"create function asset_read_lock\(\).*?\$fn\$(.*?)\$fn\$", text, re.DOTALL)
    assert body is not None, "migration 0041 no longer defines asset_read_lock() this way"
    (key,) = re.findall(r"pg_advisory_xact_lock\((\d+)\)", body.group(1))
    return int(key)


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _code_strings(tree: ast.AST) -> list[str]:
    """Every string a module states in its code. Docstrings are prose and may name the lock."""
    prose = _docstrings(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]


def _takes_the_lock(tree: ast.AST) -> int:
    return sum(len(_TAKES_THE_LOCK.findall(text)) for text in _code_strings(tree))


def _reads_only(tree: ast.AST) -> bool:
    """Whether a module makes a transaction read only, in SQL or through psycopg's attribute."""
    return any(_READ_ONLY.search(text) for text in _code_strings(tree)) or any(
        (isinstance(node, ast.Attribute) and node.attr == "read_only")
        or (isinstance(node, ast.keyword) and node.arg == "read_only")
        for node in ast.walk(tree)
    )


def _states_the_key(tree: ast.AST, key: int) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if type(node.value) is int and node.value == key:
                count += 1
            elif isinstance(node.value, str):
                count += len(re.findall(rf"(?<!\d){key}(?!\d)", node.value))
    return count


def _modules() -> Iterator[tuple[str, ast.AST]]:
    """Every module of the package but the helper, parsed."""
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        if name != HELPER:
            yield name, ast.parse(path.read_text(encoding="utf-8"))


def _lock_timeout(connection: psycopg.Connection) -> str:
    return connection.execute("show lock_timeout").fetchone()["lock_timeout"]


# -- the helper's refusals -------------------------------------------------------------------------


def test_a_connection_inside_a_transaction_is_refused_before_anything_is_sent(ingest_spine):
    connection = ingest_spine[0].connection
    recording = Recording(connection)
    with (
        connection.transaction(),
        pytest.raises(ConnectionNotIdle) as refused,
        final_read_check(recording, not_idle=NOT_IDLE),
    ):
        pytest.fail("the check ran inside the caller's transaction")
    # A ValueError, as every caller's refusal has been, in the caller's own words.
    assert isinstance(refused.value, ValueError)
    assert str(refused.value) == NOT_IDLE
    assert recording.statements == []


def test_a_busy_lock_is_refused_when_the_caller_will_not_wait(ingest_spine):
    repository, open_another = ingest_spine
    holder = open_another()
    before = _lock_timeout(repository.connection)
    recording = Recording(repository.connection)
    repository.connection.execute(f"set statement_timeout = '{HANG_GUARD}'")
    try:
        with holder.connection.transaction():
            holder.connection.execute(OPENING[2])
            with (
                pytest.raises(AssetReadLockBusy) as busy,
                final_read_check(recording, not_idle=NOT_IDLE, wait=False),
            ):
                pytest.fail("the check read under a lock it did not hold")
    finally:
        repository.connection.execute("reset statement_timeout")
    # A LockNotAvailable, so a caller that catches what a session lock timeout raises catches it.
    assert isinstance(busy.value, psycopg.errors.LockNotAvailable)
    assert recording.statements == [*OPENING[:2], read_check._WILL_NOT_WAIT, OPENING[2], "ROLLBACK"]
    assert repository.connection.info.transaction_status == TransactionStatus.IDLE
    # The check's own timeout ended with its transaction.
    assert _lock_timeout(repository.connection) == before


def test_a_check_that_will_not_wait_reads_as_usual_when_the_lock_is_free(ingest_spine):
    connection = ingest_spine[0].connection
    before = _lock_timeout(connection)
    recording = Recording(connection)
    with final_read_check(recording, not_idle=NOT_IDLE, wait=False) as at:
        during = _lock_timeout(connection)
    assert recording.statements == [*OPENING[:2], read_check._WILL_NOT_WAIT, *OPENING[2:], "COMMIT"]
    assert during != before and _lock_timeout(connection) == before
    assert isinstance(at, dt.datetime) and at.utcoffset() is not None


def test_a_session_that_will_not_wait_is_given_the_same_refusal(ingest_spine):
    repository, open_another = ingest_spine
    holder = open_another()
    repository.connection.execute(f"set lock_timeout = '{WILL_NOT_WAIT}'")
    try:
        with holder.connection.transaction():
            holder.connection.execute(OPENING[2])
            with (
                pytest.raises(AssetReadLockBusy),
                final_read_check(repository.connection, not_idle=NOT_IDLE),
            ):
                pytest.fail("the check read under a lock it did not hold")
    finally:
        repository.connection.execute("reset lock_timeout")
    assert repository.connection.info.transaction_status == TransactionStatus.IDLE


# -- the ratchet -----------------------------------------------------------------------------------


def test_only_a_writers_own_transaction_takes_the_lock_by_hand():
    found = {name: count for name, tree in _modules() if (count := _takes_the_lock(tree))}
    assert found == IN_A_WRITERS_TRANSACTION


def test_no_module_takes_the_lock_inside_a_read_only_transaction_by_hand():
    by_hand = [name for name, tree in _modules() if _takes_the_lock(tree) and _reads_only(tree)]
    assert by_hand == []


def test_no_module_restates_the_locks_key():
    key = _lock_key()
    assert {name: n for name, tree in _modules() if (n := _states_the_key(tree, key))} == {}


def test_the_helper_is_what_the_scan_would_refuse_anywhere_else():
    """The positive control on real code: the helper makes both statements the ratchet looks for."""
    tree = ast.parse((ROOT / HELPER).read_text(encoding="utf-8"))
    assert _takes_the_lock(tree) == 1
    assert _reads_only(tree)


_BY_HAND = '''
def check(connection):
    """Prose may name asset_read_lock() and a read only transaction."""
    with connection.transaction():
        connection.execute("set transaction read only")
        connection.execute("select asset_read_lock()")
'''


@pytest.mark.parametrize(
    ("source", "takes", "reads_only"),
    [
        (_BY_HAND, 1, True),
        ("connection.read_only = True", 0, True),
        ("x = 'select pg_advisory_xact_lock(1)'", 0, False),
        ('"""Only a docstring names asset_read_lock() in a read only transaction."""', 0, False),
    ],
)
def test_the_scan_finds_a_lock_taken_by_hand_and_ignores_prose(source, takes, reads_only):
    tree = ast.parse(source)
    assert _takes_the_lock(tree) == takes
    assert _reads_only(tree) is reads_only


def test_a_restated_key_is_found_as_a_number_or_inside_sql():
    key = _lock_key()
    assert _states_the_key(ast.parse(f"x = {key}"), key) == 1
    assert _states_the_key(ast.parse(f"x = 'select pg_advisory_xact_lock({key})'"), key) == 1
    assert _states_the_key(ast.parse(f"x = {key * 10 + 1}"), key) == 0
