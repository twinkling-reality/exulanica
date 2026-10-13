"""Registering the worlds a test writes into, the way the product's creation paths do.

Every world table names a registered world (migration 0099), so a test that writes structure,
style, authored or interaction rows for a world registers it first, exactly as an authored starter
or a composition of personal sources does in the product. Not loaded by the application.

``FIXTURE_WORLD_ID`` is the world the synthetic structural candidates in
``world_structure_fixtures`` are written for. It is fixture data: the product resolves worlds
from the registry and never names this id, which ``tests/test_world_identity_inventory.py``
holds, and ``tests/test_two_worlds_stay_apart.py`` runs two worlds with minted ids so nothing
passes because of this value.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Final

from exulanica.world.worlds import PERSONAL_SOURCE, register_world
from psycopg.rows import tuple_row

__all__ = [
    "FIXTURE_WORLD_ID",
    "fixture_workspace",
    "historical_world_fixture_schema",
    "registered_world",
]

#: The world id the synthetic candidates and older fixtures are written for.
FIXTURE_WORLD_ID: Final = "atlas:default"


def registered_world(
    connection,
    workspace_id: uuid.UUID,
    world_id: str = FIXTURE_WORLD_ID,
    *,
    kind: str = PERSONAL_SOURCE,
    actor: uuid.UUID | None = None,
) -> str:
    """Register ``world_id`` in the workspace (or find it registered) and return it."""
    return register_world(
        connection,
        workspace_id,
        world_id=world_id,
        kind=kind,
        created_by=actor or uuid.uuid4(),
        reason="test fixture",
    ).world_id


@contextmanager
def fixture_workspace(connection, workspace_id):
    """Build a foreign fixture under its own authority, then restore the caller's context."""
    with connection.cursor(row_factory=tuple_row) as cursor:
        previous = cursor.execute(
            "select current_setting('exulanica.workspace_id', true)"
        ).fetchone()[0]
        cursor.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace_id),)
        )
        try:
            yield
        finally:
            cursor.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (previous or "",)
            )


@contextmanager
def historical_world_fixture_schema(connection, *, support=False, erasure=True, kinds=False):
    """Let current fixture builders read empty future state, restoring the historical schema.

    Use only around fixture construction or a post-upgrade read, never across the migration
    being proved. These views hold no erasures and support fields are null: historical worlds
    had neither. The exit checks ensure no compatibility relation or column reaches a migration.
    """
    views = []
    columns = []
    with connection.cursor(row_factory=tuple_row) as cursor:
        if erasure:
            views.append(
                (
                    "world_erasure",
                    "null::uuid as workspace_id, null::text as world_id, "
                    "null::timestamptz as made_at, null::integer as tiles",
                )
            )
        if kinds:
            views.append(
                (
                    "world_kind_erasure",
                    "null::uuid as workspace_id, "
                    "null::text as kind_key_sha256, null::integer as version, "
                    "null::text as document_sha256",
                )
            )
        for name, fields in views:
            assert cursor.execute("select to_regclass(%s)", (name,)).fetchone()[0] is None
            cursor.execute(f"create view {name} as select {fields} where false")
        if support:
            for name, type_ in (
                ("support_snapshot_id", "uuid"),
                ("support_receipt_sha256", "bytea"),
                ("support_network_sha256", "bytea"),
                ("support_surface_id", "text"),
            ):
                assert (
                    cursor.execute(
                        "select 1 from information_schema.columns "
                        "where table_schema=current_schema() "
                        "and table_name='world_alternate_thing' and column_name=%s",
                        (name,),
                    ).fetchone()
                    is None
                )
                cursor.execute(f"alter table world_alternate_thing add column {name} {type_}")
                columns.append(name)
        connection.commit()
        try:
            yield
        finally:
            for name in columns:
                assert (
                    cursor.execute(
                        f"select 1 from world_alternate_thing where {name} is not null"
                    ).fetchone()
                    is None
                )
                cursor.execute(f"alter table world_alternate_thing drop column {name}")
            for name, _ in views:
                cursor.execute(f"drop view {name}")
                assert cursor.execute("select to_regclass(%s)", (name,)).fetchone()[0] is None
            for name in columns:
                assert (
                    cursor.execute(
                        "select 1 from information_schema.columns "
                        "where table_schema=current_schema() "
                        "and table_name='world_alternate_thing' and column_name=%s",
                        (name,),
                    ).fetchone()
                    is None
                )
            connection.commit()
