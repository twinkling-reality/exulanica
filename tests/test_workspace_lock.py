"""The workspace lock seed: stated once, and every remaining restatement held to it.

``exulanica.world.workspace_lock`` owns the seed. Migrations restate it inside PostgreSQL functions
that cannot import Python, and modules written before the helper restate it too. This file fails on
a restatement anywhere else, on a listed module that has stopped restating it (so the list shrinks
as modules move onto the helper), and on a migration that locks a workspace with any other seed. What it cannot see is a restatement that got the number wrong in a module outside the
list: that is not the seed's value, so it reads as some other lock, which is why the helper, not
a copy, is the way a new module takes this lock.
"""

from __future__ import annotations

import ast
import pathlib
import re
import uuid

import pytest
from exulanica.world.workspace_lock import WORKSPACE_LOCK_SEED, lock_workspace

from pg_harness import open_scratch_connection

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Modules that restate the seed instead of calling ``lock_workspace``, with how many times. May
#: only shrink: moving a module onto the helper removes its line here.
RESTATING = {
    "exulanica/api/society_runtime.py": 1,
    "exulanica/selection/executor.py": 1,
    "exulanica/world/bootstrap.py": 1,
    "exulanica/world/character_appearance_repository.py": 1,
    "exulanica/world/interaction_repository.py": 1,
    "exulanica/world/repository.py": 2,
    "exulanica/world/saved_entries.py": 1,
    "exulanica/world/society_action_repository.py": 1,
    "exulanica/world/society_control_repository.py": 1,
    "exulanica/world/society_repository.py": 1,
    "exulanica/world/structure_repository.py": 1,
}

#: A workspace lock in SQL: the bare workspace id, with no prefix, hashed with a seed.
_SQL_WORKSPACE_LOCK = re.compile(r"hashtextextended\(\s*new\.workspace_id::text\s*,\s*(\d+)\s*\)")


def _restatements(tree: ast.AST) -> int:
    count = 0
    digits = str(WORKSPACE_LOCK_SEED)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if type(node.value) is int and node.value == WORKSPACE_LOCK_SEED:
                count += 1
            elif isinstance(node.value, str):
                count += len(re.findall(rf"(?<!\d){digits}(?!\d)", node.value))
    return count


def test_the_seed_is_restated_only_where_it_already_was():
    found = {}
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        if name == "exulanica/world/workspace_lock.py":
            continue
        count = _restatements(ast.parse(path.read_text(encoding="utf-8")))
        if count:
            found[name] = count
    assert found == RESTATING


def test_every_migration_that_locks_a_workspace_uses_the_seed():
    seeds = [
        int(seed)
        for path in sorted((ROOT / "exulanica" / "migrations").glob("[0-9]*.sql"))
        for seed in _SQL_WORKSPACE_LOCK.findall(path.read_text(encoding="utf-8"))
    ]
    assert seeds, "no migration locks a workspace: the pattern no longer matches"
    assert set(seeds) == {WORKSPACE_LOCK_SEED}


def test_the_helper_holds_the_lock_until_its_transaction_ends(spine_schema):
    psycopg_module, scratch = spine_schema
    holder = open_scratch_connection(psycopg_module, scratch)
    other = open_scratch_connection(psycopg_module, scratch)
    workspace_id = uuid.uuid4()

    def free() -> bool:
        # Both connections autocommit, so this try takes and releases the lock in one statement.
        return other.execute(
            "select pg_try_advisory_xact_lock(hashtextextended(%s::text,%s)) as taken",
            (workspace_id, WORKSPACE_LOCK_SEED),
        ).fetchone()[0]

    try:
        assert free()
        with holder.transaction():
            lock_workspace(holder, workspace_id)
            assert not free()
        assert free()
    finally:
        holder.close()
        other.close()


@pytest.mark.parametrize("value", [880_024, "hashtextextended(%s,880024)"])
def test_a_restatement_is_found_as_a_number_or_inside_sql(value):
    """The positive control for the scan above, on both shapes the product uses."""
    assert _restatements(ast.parse(f"x = {value!r}")) == 1
    assert _restatements(ast.parse("x = 8800240 + 1880024")) == 0
