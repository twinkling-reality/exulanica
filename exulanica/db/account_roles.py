"""Administrative grants for the account store, independent of workspace runtime roles.

No runtime path provisions a role. Authentication tables must be excluded from the generic
workspace-role grants; callers reapply revoke_account_access after those existing grants.
"""

from __future__ import annotations

from typing import Final

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ACCOUNT_ROLE: Final = "exulanica_accounts"

ACCOUNT_TABLES = (
    "account_user",
    "account_identity",
    "account_workspace",
    "account_membership",
    "account_login_attempt",
    "account_browser_session",
)


class AccountRoleUnsafe(ValueError):
    """The account connection can exceed the authentication boundary."""


def revoke_account_access(connection: psycopg.Connection, *, role: str) -> None:
    """Root's workspace-role hook, after generic grants. Also remove explicit column grants."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select n.nspname schema_name,c.relname,a.attname from pg_class c "
            "join pg_namespace n on n.oid=c.relnamespace "
            "join pg_attribute a on a.attrelid=c.oid where n.nspname=current_schema() "
            "and c.relname=any(%s) and a.attnum>0 and not a.attisdropped",
            (list(ACCOUNT_TABLES),),
        ).fetchall()
        for row in rows:
            cursor.execute(
                sql.SQL(
                    "revoke select({}),insert({}),update({}),references({}) on {} from {}"
                ).format(
                    *([sql.Identifier(row["attname"])] * 4),
                    sql.Identifier(row["schema_name"], row["relname"]),
                    sql.Identifier(role),
                )
            )
        for schema_name, table in sorted({(row["schema_name"], row["relname"]) for row in rows}):
            cursor.execute(
                sql.SQL("revoke all privileges on table {} from {}").format(
                    sql.Identifier(schema_name, table), sql.Identifier(role)
                )
            )


def assert_account_role(connection: psycopg.Connection, *, role: str | None = None) -> None:
    with connection.cursor(row_factory=dict_row) as cursor:
        role = role or cursor.execute("select current_user name").fetchone()["name"]
        row = cursor.execute(
            "select oid,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication,rolinherit "
            "from pg_roles where rolname=%s",
            (role,),
        ).fetchone()
        if row is None or any(
            row[k]
            for k in (
                "rolsuper",
                "rolbypassrls",
                "rolcreaterole",
                "rolcreatedb",
                "rolreplication",
                "rolinherit",
            )
        ):
            raise AccountRoleUnsafe("account role must be a nonprivileged NOINHERIT role")
        if cursor.execute(
            "select 1 from pg_auth_members where roleid=%s or member=%s limit 1",
            (row["oid"], row["oid"]),
        ).fetchone():
            raise AccountRoleUnsafe("account role must not have role memberships or members")
        if cursor.execute(
            "select 1 from pg_class where relowner=%s limit 1", (row["oid"],)
        ).fetchone():
            raise AccountRoleUnsafe("account role must not own tables, sequences or views")
        if cursor.execute(
            "select has_schema_privilege(%s,current_schema(),'CREATE') allowed", (role,)
        ).fetchone()["allowed"]:
            raise AccountRoleUnsafe("account role cannot create schema objects")
        rows = cursor.execute(
            "select c.oid,c.relname,c.relkind,"
            "has_table_privilege(%s,c.oid,"
            "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') any_access,"
            "has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES') column_access "
            "from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname=current_schema() and c.relkind in ('r','p','v','m','f')",
            (role, role),
        ).fetchall()
        if {r["relname"] for r in rows if r["relname"] in ACCOUNT_TABLES} != set(ACCOUNT_TABLES):
            raise AccountRoleUnsafe("account schema is incomplete")
        for table in rows:
            if table["relname"] not in ACCOUNT_TABLES and (
                table["any_access"] or table["column_access"]
            ):
                raise AccountRoleUnsafe("account role can access application tables")
            if table["relname"] in ACCOUNT_TABLES:
                for privilege in ("SELECT", "INSERT", "UPDATE"):
                    if not cursor.execute(
                        "select has_table_privilege(%s,%s,%s) ok", (role, table["oid"], privilege)
                    ).fetchone()["ok"]:
                        raise AccountRoleUnsafe("account role lacks a required table grant")
                if cursor.execute(
                    "select has_table_privilege(%s,%s,'DELETE,TRUNCATE,REFERENCES,TRIGGER') ok",
                    (role, table["oid"]),
                ).fetchone()["ok"]:
                    raise AccountRoleUnsafe("account role has excessive account-table privileges")
        if cursor.execute(
            "select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname=current_schema() and case when c.relkind='S' then "
            "has_sequence_privilege(%s,c.oid,'SELECT,USAGE,UPDATE') else false end limit 1",
            (role,),
        ).fetchone():
            raise AccountRoleUnsafe("account role must have no application sequence access")
        if cursor.execute(
            "select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
            "where n.nspname=current_schema() and (p.prosecdef or p.proname like 'tg_account_%%') "
            "and has_function_privilege(%s,p.oid,'EXECUTE') limit 1",
            (role,),
        ).fetchone():
            raise AccountRoleUnsafe("account role can execute privileged application functions")
        if cursor.execute(
            "select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace,"
            "lateral aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
            "where n.nspname=current_schema() and c.relname=any(%s) and a.grantee=0 limit 1",
            (list(ACCOUNT_TABLES),),
        ).fetchone():
            raise AccountRoleUnsafe("account tables must not grant PUBLIC access")


def provision_account_role(
    connection: psycopg.Connection, *, role: str = ACCOUNT_ROLE, password: str | None = None
) -> None:
    """Explicit administration only; supply existing peer/certificate or chosen password auth."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("select pg_advisory_xact_lock(119622358)")
        if cursor.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone() is None:
            cursor.execute(
                sql.SQL(
                    "create role {} login noinherit nosuperuser nocreatedb "
                    "nocreaterole noreplication nobypassrls"
                ).format(sql.Identifier(role))
            )
        if password is not None:
            cursor.execute(
                sql.SQL("alter role {} password {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        schema = cursor.execute("select current_schema() name").fetchone()["name"]
        cursor.execute(
            sql.SQL("grant usage on schema {} to {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        for table in ACCOUNT_TABLES:
            cursor.execute(
                sql.SQL("grant select,insert,update on table {}.{} to {}").format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)
                )
            )
        assert_account_role(connection, role=role)
