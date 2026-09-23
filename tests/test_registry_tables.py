"""The registry tables are named once, and every place that acts on them sees all of them.

``exulanica.db.registries.REGISTRY_TABLES`` names the reviewed vocabularies that migrations fill
and no workspace owns. Provisioning keeps the runtime from writing them, a workspace seed carries a
digest of them instead of their rows, and the test harness keeps them across its per-test
truncation. Before there was one name for the set, each of those three held its own list, and the
lists had drifted by three names while a docstring called them the same set.
"""

from __future__ import annotations

from exulanica.db.registries import REGISTRY_TABLES
from exulanica.db.roles import READ_ONLY_TABLES
from exulanica.orchestration.judge_seed import GLOBAL_TABLES
from psycopg import sql

import conftest


def test_each_place_that_acts_on_the_registries_names_every_one():
    """A place that stopped deriving its list from the one mapping would drop a table here."""
    assert REGISTRY_TABLES, "no registry is named, so every check below would pass on nothing"
    assert set(REGISTRY_TABLES) <= set(READ_ONLY_TABLES)
    assert {name: GLOBAL_TABLES[name] for name in REGISTRY_TABLES if name in GLOBAL_TABLES} == dict(
        REGISTRY_TABLES
    )
    assert set(REGISTRY_TABLES) <= conftest._PRESERVED_TABLES


def test_every_registry_is_global_filled_by_the_migrations_and_kept_across_tests(repository):
    """What the name claims, read from a migrated schema after the harness has truncated it.

    ``repository`` is handed out after the per-test truncation, so a registry the harness failed
    to preserve arrives empty here, and so does one no migration fills.
    """
    connection = repository.connection
    workspace_scoped = []
    empty = []
    for table in sorted(REGISTRY_TABLES):
        scoped = connection.execute(
            "select exists (select 1 from information_schema.columns"
            " where table_schema = current_schema() and table_name = %s"
            " and column_name = 'workspace_id') as scoped",
            (table,),
        ).fetchone()["scoped"]
        if scoped:
            workspace_scoped.append(table)
        rows = connection.execute(
            sql.SQL("select count(*) as n from {}").format(sql.Identifier(table))
        ).fetchone()["n"]
        if rows == 0:
            empty.append(table)
    assert workspace_scoped == [], f"a registry carries a workspace: {workspace_scoped}"
    assert empty == [], f"these registries are empty after the harness truncated: {empty}"
