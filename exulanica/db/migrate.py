"""Applying migration files to a server, and recording what was applied.

``exulanica.migrations`` knows what the files are and what they hash to. This module is the half
that talks to a database: it reads ``schema_migrations``, applies whatever is pending, and
records the checksum of each file it applied so that :func:`exulanica.migrations.verify_applied`
has something to compare against later.

Three properties, each of which is a decision rather than an accident:

*   **Bootstrapping is explicit.** ``schema_migrations`` is created by migration 0001, so the
    first read of it happens before it exists. An undefined-table error is treated as "nothing
    has been applied", and only that error.
*   **Each file is applied exactly as it is on disk.** No substitutions, no string rewriting.
    A file that will not run here is a file that will not run in production either, and the
    only useful thing to do about that is to fail.
*   **Recording is a separate statement after the file commits.** A migration carries its own
    ``commit;``, so the bookkeeping row cannot ride inside the same transaction. The window
    between them is the one failure mode this leaves open: a crash there applies a migration
    without recording it, and the next run tries to reapply it and fails loudly on an object
    that already exists. Loud is the right direction; recording first would instead let a
    partially applied schema look complete.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from psycopg import sql

from exulanica.db.roles import grant_workspace_partition
from exulanica.db.session import Database
from exulanica.migrations import Migration, migrations, verify_applied

__all__ = [
    "MigrationReport",
    "applied_migrations",
    "apply_pending",
    "provision_workspace",
    "verify_schema",
]

#: The same advisory lock migration 0001 takes for its extension statements. Holding it around
#: the whole apply means two workers starting at once serialise instead of both applying 0001.
_MIGRATION_LOCK_KEY = 119_622_309


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """What one call to :func:`apply_pending` did."""

    applied: tuple[str, ...]
    already_present: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def applied_migrations(connection: psycopg.Connection) -> dict[str, bytes]:
    """``{version: checksum}`` from this connection's schema, or ``{}`` before it exists.

    The table is schema-qualified deliberately. A connection may put ``public`` after an isolated
    deployment schema so PostgreSQL extensions remain visible. An unqualified lookup would then
    fall through to a different deployment's ``public.schema_migrations`` when the first schema
    is empty, making a fresh database look fully migrated or drifted.
    """
    schema = _current_schema(connection)
    try:
        with connection.transaction():
            rows = connection.execute(
                sql.SQL("select version, checksum from {}.schema_migrations").format(
                    sql.Identifier(schema)
                )
            ).fetchall()
    except psycopg.errors.UndefinedTable:
        return {}
    return {row["version"]: bytes(row["checksum"]) for row in rows}


def _current_schema(connection: psycopg.Connection) -> str:
    row = connection.execute("select current_schema() as schema_name").fetchone()
    schema = None if row is None else row["schema_name"]
    if not isinstance(schema, str) or not schema:
        raise RuntimeError("migration connection has no current schema")
    return schema


def verify_schema(database: Database) -> None:
    """Raise if the database records a migration the package no longer has, or has altered.

    Called at boot by anything that is about to serve queries. An edited migration is a silent
    schema fork: two deployments claim the same version and have different tables, and the
    difference surfaces much later as a wrong answer rather than as an error.
    """
    with database.unscoped() as connection:
        verify_applied(applied_migrations(connection))


def apply_pending(database: Database) -> MigrationReport:
    """Apply every migration the database does not have, in version order."""
    applied: list[str] = []
    present: list[str] = []
    with database.unscoped() as connection:
        with connection.transaction():
            connection.execute("select pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_KEY,))
            known = applied_migrations(connection)
            verify_applied(known)
            pending = [m for m in migrations() if m.version not in known]
            present = [m.version for m in migrations() if m.version in known]
        for migration in pending:
            _apply_one(connection, migration)
            applied.append(migration.version)
    return MigrationReport(applied=tuple(applied), already_present=tuple(present))


def _apply_one(connection: psycopg.Connection, migration: Migration) -> None:
    """Run one migration file verbatim, then record it.

    The file is not wrapped in a transaction here: it carries its own ``begin;`` and ``commit;``
    and nesting one inside another would make the outer rollback a lie.
    """
    connection.execute(migration.sql)
    with connection.transaction():
        connection.execute(
            sql.SQL(
                "insert into {}.schema_migrations (version, checksum) values (%s, %s) "
                "on conflict (version) do nothing"
            ).format(sql.Identifier(_current_schema(connection))),
            (migration.version, migration.checksum),
        )


def provision_workspace(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """Create the per-workspace partition of ``embedding``, with its own row-level security.

    ``embedding`` is partitioned by list on ``workspace_id`` so tenancy is a partition prune
    rather than a post-scan filter. A workspace with no partition cannot hold an embedding at
    all, and the error it gets is "no partition of relation embedding found", which reads as a
    schema fault rather than as the provisioning step it is.

    **The policy on the partition is not optional and is not inherited.** Migration 0001 enables
    FORCE row-level security on the parent, and a query through the parent is filtered by the
    parent's policy. A query naming the PARTITION directly is filtered by the partition's own
    policies, and a partition created without any is readable by every workspace. Verified by
    probe: with the three statements below removed, a session scoped to workspace B counts 0
    rows through ``embedding`` and 1 row through ``embedding_ws_<a>``. That is a cross-tenant
    read of exactly the table the privacy analysis is about, reachable by spelling the table
    name differently.
    """
    partition = f"embedding_ws_{workspace_id.hex}"
    name = sql.Identifier(partition)
    with connection.transaction():
        connection.execute(
            sql.SQL("create table if not exists {} partition of embedding for values in ({})")
            .format(name, sql.Literal(workspace_id))
        )
        connection.execute(
            sql.SQL("create index if not exists {} on {} (family, ref_type, ref_id)").format(
                sql.Identifier(f"{partition}_ref_idx"), name
            )
        )
        connection.execute(sql.SQL("alter table {} enable row level security").format(name))
        connection.execute(sql.SQL("alter table {} force  row level security").format(name))
        # PostgreSQL has no `create policy if not exists`, and re-provisioning an existing
        # workspace has to be a no-op rather than an error.
        exists = connection.execute(
            "select 1 from pg_policies where schemaname = current_schema() "
            "and tablename = %s and policyname = 'ws_isolation'",
            (partition,),
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL(
                    "create policy ws_isolation on {} "
                    "using (workspace_id = current_workspace()) "
                    "with check (workspace_id = current_workspace())"
                ).format(name)
            )
        grant_workspace_partition(connection, partition)
