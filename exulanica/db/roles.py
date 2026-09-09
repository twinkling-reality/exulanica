"""The runtime role, and the privileges that make row-level security mean anything.

Migration 0001 says, in the comment above its RLS section: "The query executor connects as a
role that owns nothing and does not hold BYPASSRLS. An executor connecting as the table owner
makes every policy here silently inert, which is the failure this comment exists to prevent."

That role did not exist. Everything, including the whole test suite, connected as the database
owner, who on a default installation is also a superuser, and a superuser bypasses row-level
security entirely. Every policy in the schema was inert and the tests that appeared to prove
workspace isolation were proving the trigger guards instead, which fire for superusers too. The
distinction is not academic: the trigger guards refuse a WRITE that names the wrong workspace,
while RLS is what stops a READ of another workspace's rows, and nothing was testing the second.

So this module creates the role and grants it exactly what it needs:

*   **No DELETE for the runtime.** Deletion is a tombstone plus a purge job. The purger alone may
    delete embedding rows, because retaining a person vector as a stub retains the derivative.
*   **SELECT only on ``predicate``.** This is defect R3. ``allows_kind`` is what stops a model
    filing a name, and ``writes_a_name`` is what stops a new vocabulary row escaping the rule
    by being spelled differently. A runtime role that can UPDATE that table can disarm both,
    and the vocabulary is global rather than workspace-scoped, so one workspace could disarm it
    for every workspace. It is a lookup table the application reads and an administrator edits.
*   **SELECT only on ``schema_migrations``.** The application verifies its schema at boot; it
    does not record migrations.
*   **SELECT only on the world style and interaction registries.** Profile and capability
    registration is a reviewed migration/code change. A runtime process may propose registered
    values; it cannot register its own renderer or interaction vocabulary.
*   **No ownership and no BYPASSRLS**, which is the whole point.

Every statement here is built with :mod:`psycopg.sql` rather than an f-string. Role names,
schema names and passwords all reach DDL, and DDL takes no bound parameters, so the choice is
between a composer that quotes correctly and a hand-rolled validator that has to be right.
"""

from __future__ import annotations

from typing import Final

import psycopg
from psycopg import sql

from exulanica.errors import ExulanicaError

__all__ = [
    "EXECUTOR_ROLE",
    "PURGE_CROSS_WORKSPACE_TABLES",
    "PURGE_ROLE",
    "READ_ONLY_TABLES",
    "RUNTIME_ROLE",
    "RuntimeRoleUnsafe",
    "assert_runtime_role",
    "grant_workspace_partition",
    "provision_purge_role",
    "provision_runtime_role",
]

#: The role the write path connects as: identity decisions, annotations, ingest. Owns nothing.
RUNTIME_ROLE: Final = "exulanica_app"

#: The role the deterministic Selection executor connects as. Named in
#: architecture-overview.md section 5.2, which specifies a non-owner role without BYPASSRLS for
#: exactly this step. It holds SELECT and nothing else, so the step of the pipeline that runs a
#: plan derived from model output cannot write whatever happens above it.
EXECUTOR_ROLE: Final = "exulanica_ro"

#: The role the object-store purger connects as. It exists for one privilege nothing else may
#: have, and the privilege is a READ: see :func:`provision_purge_role`.
PURGE_ROLE: Final = "exulanica_purge"

#: Tables the runtime may read and may not write. See the module docstring for why each.
READ_ONLY_TABLES: Final = (
    "restore_control",
    "restore_replay_receipt",
    "interaction_capability_registry",
    "predicate",
    "schema_migrations",
    "world_art_profile_parameter",
    "world_art_profile_registry",
    "world_art_profile_module",
    "world_style_capability_registry",
    "world_style_module_capability",
    "world_style_module_registry",
    "world_object_behaviour_registry",
    "world_reviewed_asset",
)

#: The vocabulary is administered, not generated. Without revoking this the role could insert a
#: predicate row even though it cannot update one.
_ADMIN_ONLY_SEQUENCES: Final = ("predicate_predicate_id_seq",)

#: What the purger may read, and it reads it across every workspace. Identifiers, content
#: hashes and deletion markers: enough to answer "does anything still hold these bytes" and
#: nothing else. A policy cannot restrict columns, so this grant is what does.
#:
#: ``reconstruction_scene_member`` is here because migration 0024 gave ``purge_releases_bytes``
#: a third clause that reads it, and a purger blind to another workspace's membership answers
#: that clause about its own workspace alone.
#:
#: **The direction it fails in is the opposite of correction 7's, and saying so is the point.**
#: Blindness over ``capture`` DESTROYED another tenant's photograph, which is why that grant
#: exists. Blindness here does the reverse: the clause asks whether any member of a scene holding
#: these bytes is deleted, and a purger that sees no membership rows finds no deleted member,
#: concludes the artifact still holds them, and refuses. That is the safe direction, so this
#: grant is not preventing a leak. It is preventing a permanent stall: two workspaces holding one
#: scene artifact's bytes would each refuse for ever, each blind to the other's deletion, and a
#: deletion the user asked for would never complete while ``tombstone_purge_is_complete`` went on
#: reporting it incomplete. A deletion that silently never finishes is still a deletion that did
#: not happen.
#:
#: **This dict names columns, so it depends on the schema being current.** ``grant select
#: (scene_id) on artifact`` fails outright against a database before migration 0024, rather than
#: granting less than it says. That is the right direction and it is already the order
#: ``exulanica-db provision`` runs in: migrations, then roles, which is what its own description
#: says it does.
_PURGE_READS: Final = {
    "capture": ("capture_id", "workspace_id", "blob_sha256", "deleted_at"),
    "artifact": (
        "artifact_id",
        "workspace_id",
        "content_sha256",
        "source_blob_sha256",
        "scene_id",
        "storage_key",
        "purged_at",
    ),
    "reconstruction_scene_member": ("workspace_id", "scene_id", "capture_id"),
    "person_derivative_dependency": (
        "workspace_id",
        "entity_id",
        "target_kind",
        "target_id",
    ),
}

#: The tables :data:`_PURGE_READS` gives the cross-workspace policy to, in a public form, because
#: :func:`exulanica.deletion.queue.read_visibility` has to ask the database whether the connected
#: role actually holds that policy on all of them. Derived rather than repeated: a table added
#: above and forgotten there would leave the visibility check reporting a full view over a
#: relation the purger reads through a narrowed one, which is the silent half of correction 7.
PURGE_CROSS_WORKSPACE_TABLES: Final = tuple(sorted(_PURGE_READS))

#: Read as well, and with no policy beside it: `blob` is not workspace-scoped and carries no
#: row-level security at all, so the column grant is the whole of the restriction here. It is
#: kept out of _PURGE_READS because that dict drives the cross-workspace policy, and a policy on
#: a table with row-level security disabled would be a statement nothing enforces.
_PURGE_UNSCOPED_READS: Final = {
    "blob": ("blob_sha256", "byte_size", "storage_key", "purged_at"),
}

#: What the purger may write, and it writes only inside its own workspace, because ws_isolation
#: still applies to UPDATE. Marking bytes gone, and nothing else. `blob` carries no policy
#: because it is not workspace-scoped; the columns are the whole restriction there.
_PURGE_WRITES: Final = {
    "artifact": ("purged_at", "storage_key"),
    "blob": ("purged_at", "storage_key"),
}

#: What the purger may write on the queue and on the tombstone. Exactly the columns the worker
#: sets and no others: not `effective_at`, which decides whether a tombstone blocks a derivative
#: at all, not `target_ref`, which decides which object a claimed job destroys, and not
#: `requested_by`, which is who asked.
_PURGE_QUEUE_WRITES: Final = {
    "purge_job": ("state", "attempts", "attempted_at", "last_error", "completed_at"),
    "tombstone": ("purge_completed_at",),
}

#: The permissive SELECT policy that gives the purge role its cross-workspace view. Named so it
#: is legible in `\d capture` rather than being an anonymous second policy nobody expected.
_CROSS_WORKSPACE_POLICY: Final = "purge_sees_every_holder_of_these_bytes"

#: The same key migration 0001 takes. Roles are cluster-global objects and `create role` and
#: `alter role` both write pg_authid, so two deployments starting at once get "tuple
#: concurrently updated" rather than one of them waiting. Observed with four test processes
#: against one database, which is what a CI runner is.
_ROLE_LOCK_KEY: Final = 119_622_309


class RuntimeRoleUnsafe(ExulanicaError):
    """The process connected as an owner, superuser, or BYPASSRLS role."""


def assert_runtime_role(connection: psycopg.Connection) -> None:
    """Refuse a runtime connection for which FORCE row-level security is not a boundary.

    The exact role name is not the guarantee; owning nothing, lacking superuser and lacking
    BYPASSRLS are. This permits certificate- or environment-specific role names while refusing
    the bootstrap owner the old composition handed to both the API and worker.
    """
    row = connection.execute(
        "select current_user as role_name, r.rolsuper, r.rolbypassrls, "
        "exists ("
        "  select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "   where n.nspname = current_schema() and c.relrowsecurity "
        "     and c.relowner = r.oid"
        ") as owns_rls_table "
        "from pg_roles r where r.rolname = current_user"
    ).fetchone()
    if row is None:
        raise RuntimeRoleUnsafe("the current database role is absent from pg_roles")
    unsafe = [
        name
        for name, active in (
            ("SUPERUSER", row["rolsuper"]),
            ("BYPASSRLS", row["rolbypassrls"]),
            ("owner of a row-level-security table", row["owns_rls_table"]),
        )
        if active
    ]
    if unsafe:
        raise RuntimeRoleUnsafe(
            f"database role {row['role_name']} is {' and '.join(unsafe)}. The API and derivative "
            f"worker must connect as a non-owner role without BYPASSRLS; use {RUNTIME_ROLE}."
        )


def provision_runtime_role(
    connection: psycopg.Connection,
    *,
    role: str = RUNTIME_ROLE,
    password: str | None = None,
    read_only: bool = False,
) -> None:
    """Create ``role`` if it is absent and give it exactly the privileges it needs.

    Idempotent, so it is safe to call at every deployment. Called by an administrative
    connection, never by the runtime itself: a role that can grant itself privileges is not
    constrained by them.

    ``password`` is set only when supplied. A deployment that authenticates by certificate or
    by peer has no password to set, and a function that invented one would be creating a
    credential nobody asked for.

    ``read_only`` provisions the Selection executor role: SELECT and nothing else, on every
    table including the vocabulary.
    """
    writes = sql.SQL("select") if read_only else sql.SQL("select, insert, update")
    role_name = sql.Identifier(role)
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    # Tolerates both row factories: an administrative connection may be anything the caller had.
    schema = sql.Identifier(row["current_schema"] if isinstance(row, dict) else row[0])

    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (_ROLE_LOCK_KEY,))
        exists = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
        if exists is None:
            connection.execute(sql.SQL("create role {} login nobypassrls").format(role_name))
        else:
            # An existing role may have been created with BYPASSRLS by hand. Saying so on every
            # deployment is cheaper than discovering it from a cross-workspace read.
            connection.execute(sql.SQL("alter role {} nobypassrls").format(role_name))
        if password is not None:
            connection.execute(
                sql.SQL("alter role {} password {}").format(role_name, sql.Literal(password))
            )

        connection.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role_name))
        connection.execute(
            sql.SQL("grant {} on all tables in schema {} to {}").format(writes, schema, role_name)
        )
        if not read_only:
            connection.execute(
                sql.SQL("grant usage, select on all sequences in schema {} to {}").format(
                    schema, role_name
                )
            )
            for table in READ_ONLY_TABLES:
                connection.execute(
                    sql.SQL("revoke insert, update on {} from {}").format(
                        sql.Identifier(table), role_name
                    )
                )
            for sequence in _ADMIN_ONLY_SEQUENCES:
                connection.execute(
                    sql.SQL("revoke usage, select on sequence {} from {}").format(
                        sql.Identifier(sequence), role_name
                    )
                )
        # Per-workspace embedding partitions are created after this runs, by
        # provision_workspace. Default privileges cover the ones created later by this same
        # administrative role; grant_workspace_partition covers them explicitly, because a
        # default privilege that does not apply is silent and an explicit grant is not.
        connection.execute(
            sql.SQL("alter default privileges in schema {} grant {} on tables to {}").format(
                schema, writes, role_name
            )
        )


def provision_purge_role(
    connection: psycopg.Connection, *, role: str = PURGE_ROLE, password: str | None = None
) -> None:
    """Create the purger's role, and give it the one privilege nothing else may have.

    **The privilege is a cross-workspace READ, and it is here because the alternative is silent
    cross-tenant data loss.** ``blob`` is not workspace-scoped: two workspaces that ingest the
    same photograph share one row and one object in the store, and migration 0001 says so and
    names reference counting as the eventual fix. The purger has to ask "does anything still hold
    these exact bytes" before it destroys them, and under row-level security a session scoped to
    one workspace cannot see another's captures. Measured, as the runtime role, on a probe
    database: workspace A deletes its capture, workspace B still holds a live capture of the same
    bytes, and ``purge_releases_bytes`` answers **true**. Destroying them there breaks B's
    citations and nothing reports it.

    So this role gets a permissive ``for select using (true)`` policy on ``capture`` and
    ``artifact``, and gets it narrowly:

    *   **SELECT only.** Its UPDATE is still filtered by ``ws_isolation``, so it may mark rows
        purged only in the workspace it is scoped to. It reads across tenants and writes within
        one, which is the asymmetry the question actually needs.
    *   **Column by column.** A policy cannot restrict columns; a grant can. It is given the
        identifiers, the hashes and the deletion markers, and not ``device_id``, not
        ``started_at``, and not an artifact's ``idempotency_key``.
    *   **DELETE on ``embedding`` only.** A person vector has no harmless stub form. Stored byte
        erasure still runs through ``exulanica.store.privileged_purger`` and every other table
        remains outside the role's DELETE authority.
    *   **And its UPDATE on the queue and the tombstone is column by column too.** It was not,
        and a review measured what a full-table grant bought: this role could push a tombstone's
        ``effective_at`` a year out, which reopens the leak 0011 closed, and could set
        ``purge_completed_at`` over a photograph still on disk. Neither table carries an UPDATE
        trigger, so the grant was the only thing standing there.

    Idempotent, like :func:`provision_runtime_role`, and safe to call at every deployment.

    ``role`` is a parameter for the same reason it is one there: **a role is a CLUSTER object**,
    so a test suite that provisioned the deployment's own role names would be reaching outside
    every database-scoped guard the harness has, and would leave the developer's live roles
    carrying whatever password the last test run chose. The tests provision suffixed names.
    """
    role_name = sql.Identifier(role)
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    schema = sql.Identifier(row["current_schema"] if isinstance(row, dict) else row[0])

    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (_ROLE_LOCK_KEY,))
        exists = connection.execute(
            "select 1 from pg_roles where rolname = %s", (role,)
        ).fetchone()
        if exists is None:
            connection.execute(sql.SQL("create role {} login nobypassrls").format(role_name))
        else:
            connection.execute(sql.SQL("alter role {} nobypassrls").format(role_name))
        if password is not None:
            connection.execute(
                sql.SQL("alter role {} password {}").format(role_name, sql.Literal(password))
            )

        connection.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role_name))
        for table, columns in (*_PURGE_READS.items(), *_PURGE_UNSCOPED_READS.items()):
            connection.execute(
                sql.SQL("grant select ({}) on {} to {}").format(
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.Identifier(table),
                    role_name,
                )
            )
        connection.execute(sql.SQL("grant select, delete on embedding to {}").format(role_name))
        for table, columns in _PURGE_WRITES.items():
            connection.execute(
                sql.SQL("grant update ({}) on {} to {}").format(
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.Identifier(table),
                    role_name,
                )
            )
        # The queue and the record it drains. Read whole, write COLUMN BY COLUMN, and the
        # difference is not tidiness. Measured with a full-table grant, as this role and nothing
        # else: `update tombstone set effective_at = now() + interval '1 year'` was ALLOWED, and
        # `tombstone_blocks_derivative` filters `effective_at <= clock_timestamp()`, so the
        # least-privileged role in the system could reopen the leak 0011 closed. `update
        # purge_job set state='done'` plus the `blob` grant it legitimately holds was a complete
        # route to `purge_completed_at` over a photograph still on disk, which is the second of
        # the two outcomes this whole package exists to prevent. Neither table carries an UPDATE
        # trigger, so nothing else was in the way.
        for table in ("purge_job", "tombstone"):
            connection.execute(
                sql.SQL("grant select on {} to {}").format(sql.Identifier(table), role_name)
            )
        for table, columns in _PURGE_QUEUE_WRITES.items():
            connection.execute(
                sql.SQL("grant update ({}) on {} to {}").format(
                    sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                    sql.Identifier(table),
                    role_name,
                )
            )
        for table in _PURGE_READS:
            connection.execute(
                sql.SQL("drop policy if exists {} on {}").format(
                    sql.Identifier(_CROSS_WORKSPACE_POLICY), sql.Identifier(table)
                )
            )
            connection.execute(
                sql.SQL("create policy {} on {} for select to {} using (true)").format(
                    sql.Identifier(_CROSS_WORKSPACE_POLICY),
                    sql.Identifier(table),
                    role_name,
                )
            )

def grant_workspace_partition(connection: psycopg.Connection, partition: str) -> None:
    """Give both runtime roles access to one per-workspace partition, if they exist.

    Access, not exemption: the partition carries its own ``ws_isolation`` policy, so this grants
    the right to run a query that the policy then filters. A deployment that has not provisioned
    the roles yet is not an error here; it is the ordinary state of a development database.
    """
    for role, privileges in (
        (RUNTIME_ROLE, sql.SQL("select, insert, update")),
        (EXECUTOR_ROLE, sql.SQL("select")),
    ):
        present = connection.execute(
            "select 1 from pg_roles where rolname = %s", (role,)
        ).fetchone()
        if present is None:
            continue
        connection.execute(
            sql.SQL("grant {} on {} to {}").format(
                privileges, sql.Identifier(partition), sql.Identifier(role)
            )
        )
