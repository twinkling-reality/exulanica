"""The role a generated-tile worker publishes baked tiles as: one function, and nothing else.

A baked tile is global: every workspace whose world covers it is served the same row and bytes
(migration 0072). Migration 0138 makes ``record_baked_tile_bake`` run with its owner's rights and
revokes it from PUBLIC; this module provisions ``exulanica_tiles``, the one role granted EXECUTE on
it, and checks a connection is that role before a worker publishes through it.

*   **EXECUTE on ``record_baked_tile_bake`` and USAGE on the schema.** No table, sequence or other
    function privilege, so a stolen credential can publish a bake and do nothing else: it cannot
    read a workspace's rows, alter a stored tile (the function only stores, answers ``identical``
    or marks a fault) or call another SECURITY DEFINER function.
*   **No superuser, BYPASSRLS, CREATEDB, CREATEROLE, replication or INHERIT, and no membership in
    any role.** A membership would lend it a writer's privileges; any it holds is revoked.
*   **Every privilege it holds is revoked first**, so a grant made by hand does not survive the
    next provisioning.

The runtime role (``exulanica_app``), the read-only role and every other role provisioned beside
it hold no EXECUTE on the function; :func:`tile_publishers` names every role that does, so a test
or an operator can see that it is this one alone.
"""

from __future__ import annotations

from typing import Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exulanica.db.roles import _ROLE_LOCK_KEY

__all__ = [
    "PUBLISH_FUNCTION",
    "TILES_ROLE",
    "TilesRoleUnsafe",
    "assert_tiles_role",
    "provision_tiles_role",
    "publish_function_installed",
    "tile_publishers",
]

TILES_ROLE: Final = "exulanica_tiles"

#: The one function the role may execute, by name and argument types (migration 0138).
PUBLISH_FUNCTION: Final = (
    "record_baked_tile_bake",
    "uuid,integer,bytea,bytea,bytea,jsonb,bytea,bytea,integer,integer,integer,integer,integer,"
    "bytea,bigint,bytea,bigint,bytea,bytea,jsonb",
)


class TilesRoleUnsafe(RuntimeError):
    """The connection is not the narrow tile publisher role this module provisions."""


def _signature(connection: psycopg.Connection) -> sql.Composable:
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    schema = row["current_schema"] if isinstance(row, dict) else row[0]
    name, arguments = PUBLISH_FUNCTION
    return sql.SQL("{}.{}({})").format(
        sql.Identifier(schema), sql.Identifier(name), sql.SQL(arguments)
    )


def provision_tiles_role(
    connection: psycopg.Connection, *, role: str = TILES_ROLE, password: str | None = None
) -> None:
    """Create or narrow ``role`` to EXECUTE on the publish function alone. Idempotent.

    Run by ``exulanica-db`` as the owner after the migrations, as every other role is. Below
    migration 0138 the function is not yet its owner's to lend, so nothing is granted.
    """
    role_name = sql.Identifier(role)
    row = connection.execute("select current_schema()").fetchone()
    assert row is not None
    schema = sql.Identifier(row["current_schema"] if isinstance(row, dict) else row[0])
    attributes = sql.SQL(
        "login nosuperuser nobypassrls nocreatedb nocreaterole noreplication noinherit"
    )
    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(%s)", (_ROLE_LOCK_KEY,))
        exists = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
        verb = sql.SQL("alter") if exists is not None else sql.SQL("create")
        connection.execute(sql.SQL("{} role {} {}").format(verb, role_name, attributes))
        if password is not None:
            connection.execute(
                sql.SQL("alter role {} password {}").format(role_name, sql.Literal(password))
            )
        for held in connection.execute(
            "select r.rolname from pg_auth_members m join pg_roles r on r.oid = m.roleid "
            "join pg_roles me on me.oid = m.member where me.rolname = %s",
            (role,),
        ).fetchall():
            name = held["rolname"] if isinstance(held, dict) else held[0]
            connection.execute(sql.SQL("revoke {} from {}").format(sql.Identifier(name), role_name))
        for kind in (sql.SQL("tables"), sql.SQL("sequences"), sql.SQL("functions")):
            connection.execute(
                sql.SQL("revoke all on all {} in schema {} from {}").format(kind, schema, role_name)
            )
        connection.execute(sql.SQL("grant usage on schema {} to {}").format(schema, role_name))
        connection.execute(sql.SQL("revoke create on schema {} from {}").format(schema, role_name))
        if publish_function_installed(connection):
            connection.execute(
                sql.SQL("grant execute on function {} to {}").format(
                    _signature(connection), role_name
                )
            )


def publish_function_installed(connection: psycopg.Connection) -> bool:
    """Whether the schema holds the publish function as its owner's to lend (migration 0138 or
    later): a database provisioned below 0138 has nothing to grant and nothing to check."""
    row = connection.execute(
        "select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = current_schema() and p.proname = %s and p.prosecdef",
        (PUBLISH_FUNCTION[0],),
    ).fetchone()
    return row is not None


def tile_publishers(connection: psycopg.Connection) -> list[str]:
    """Every role that may execute the publish function, PUBLIC included as ``public``, sorted."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select case when a.grantee = 0 then 'public' else pg_get_userbyid(a.grantee) end name "
            "from pg_proc p join pg_namespace n on n.oid = p.pronamespace, "
            "lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
            "where n.nspname = current_schema() and p.proname = %s "
            "and a.privilege_type = 'EXECUTE' and a.grantee <> p.proowner",
            (PUBLISH_FUNCTION[0],),
        ).fetchall()
    return sorted({row["name"] for row in rows})


def assert_tiles_role(connection: psycopg.Connection, role: str | None = None) -> None:
    """Refuse a tile publisher wider than the narrow role: the connection's own user, or ``role``
    by name (as ``exulanica-db`` checks the role it just provisioned).

    The owner, a superuser or a BYPASSRLS role, a member of any role, a role that can create in
    the schema, reach any table or sequence, or execute any other SECURITY DEFINER function, is
    refused by name. So is a role that cannot execute the publish function.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        if role is None:
            role = cursor.execute("select current_user name").fetchone()["name"]
        row = cursor.execute(
            "select oid, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, "
            "rolinherit from pg_roles where rolname = %s",
            (role,),
        ).fetchone()
        flags = ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb", "rolreplication")
        if row is None or any(row[k] for k in flags) or row["rolinherit"]:
            raise TilesRoleUnsafe(f"{role} is not a nonprivileged NOINHERIT role")
        if cursor.execute(
            "select 1 from pg_auth_members where member = %s limit 1", (row["oid"],)
        ).fetchone():
            raise TilesRoleUnsafe(f"{role} is a member of another role")
        if (
            cursor.execute(
                "select 1 from pg_class where relowner = %s limit 1", (row["oid"],)
            ).fetchone()
            or cursor.execute(
                "select 1 from pg_proc where proowner = %s limit 1", (row["oid"],)
            ).fetchone()
        ):
            raise TilesRoleUnsafe(f"{role} owns schema objects; the owner never publishes here")
        if cursor.execute(
            "select has_schema_privilege(%s, current_schema(), 'CREATE') allowed", (role,)
        ).fetchone()["allowed"]:
            raise TilesRoleUnsafe(f"{role} can create schema objects")
        if cursor.execute(
            "select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and ("
            "(c.relkind in ('r','p','v','m','f') and (has_table_privilege(%(role)s, c.oid, "
            "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') "
            "or has_any_column_privilege(%(role)s, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))) "
            "or (c.relkind = 'S' and has_sequence_privilege(%(role)s, c.oid, "
            "'SELECT,USAGE,UPDATE'))) limit 1",
            {"role": role},
        ).fetchone():
            raise TilesRoleUnsafe(f"{role} can reach a table or sequence")
        others = cursor.execute(
            "select p.oid::regprocedure::text signature from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = current_schema() and p.prosecdef and p.proname <> %s "
            "and has_function_privilege(%s, p.oid, 'EXECUTE') order by 1",
            (PUBLISH_FUNCTION[0], role),
        ).fetchall()
        if others:
            raise TilesRoleUnsafe(
                f"{role} can execute other privileged functions: "
                + ", ".join(r["signature"] for r in others)
            )
        allowed = cursor.execute(
            "select coalesce(bool_or(has_function_privilege(%s, p.oid, 'EXECUTE') "
            "and p.prosecdef), false) ok from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = current_schema() and p.proname = %s",
            (role, PUBLISH_FUNCTION[0]),
        ).fetchone()["ok"]
        if not allowed:
            raise TilesRoleUnsafe(f"{role} cannot execute {PUBLISH_FUNCTION[0]}")
