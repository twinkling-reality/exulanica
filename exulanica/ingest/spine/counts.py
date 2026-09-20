"""How many rows are in one table, and which rows that number is counting.

**This count is not workspace-scoped, and the name says so.** :func:`rows_in_schema` counts
rows in this connection's schema. Three measured facts hold that reading:

*   Four of the thirteen countable tables have no ``workspace_id`` column at all: ``blob``,
    ``media_track``, ``clock_anchor`` and ``pipeline_event``. A workspace-scoped count of them
    is not something the schema can express.
*   The other nine are under FORCE row-level security, which a **superuser bypasses**. Measured
    on a scratch schema: two workspaces each wrote one capture, and the count returned 2 for
    both of them.
*   Every caller is a test, and every test connects as the owner, who is a superuser. So the
    schema-wide number is the number in the only context that asks for it. No CLI calls this
    function.

The honest statement is therefore the name: these are the rows in the table in this connection's
schema. A connection that did not bypass row-level security would see fewer, and there is no
such caller; if one ever appears it should ask a scoped question with a scoped name rather than
reinterpret this one. ``test_a_row_count_is_schema_wide_and_not_workspace_scoped`` holds the
sentence above to what the database actually does.
"""

from __future__ import annotations

from typing import Final

from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = ["rows_in_schema"]

#: The tables this may report on. Not user input, and not a general escape hatch: the name is
#: interpolated into SQL, so the allowlist is the only thing standing between this and an
#: injection. ``test_only_an_allowlisted_table_can_be_counted`` is what keeps that true.
_COUNTABLE: Final = frozenset(
    {
        "artifact",
        "assertion",
        "blob",
        "capture",
        "clock_anchor",
        "derived_artifact",
        "entity",
        "entity_link",
        "evidence_span",
        "media_track",
        "occurrence",
        "pipeline_event",
        "pipeline_run",
    }
)


def rows_in_schema(scope: WorkspaceScope, table: str) -> int:
    """Every row of ``table`` this connection can see, which for a superuser is all of them.

    Takes a scope like everything else in this package, because a scope is how a connection is
    reached here. It does not read ``scope.workspace_id``, and that is the point of the name.
    """
    if table not in _COUNTABLE:
        raise ValueError(f"not a countable table: {table!r}")
    row = scope.connection.execute(f"select count(*) as n from {table}").fetchone()
    assert row is not None
    return int(row["n"])
