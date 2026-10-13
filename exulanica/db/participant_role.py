"""A participant connection can SELECT explicit world projections and cannot mutate anything."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exulanica.db.session import Database

PARTICIPANT_ROLE = "exulanica_participant"
PARTICIPANT_COLUMNS = {
    "participant_world": (
        "version_id",
        "world_id",
        "source_snapshot_id",
        "edit_seq",
        "state_sha256",
        "kind",
    ),
    "participant_objects": (
        "object_id",
        "asset_sha256",
        "region_id",
        "x_mm",
        "y_mm",
        "z_mm",
        "yaw_microradians",
        "scale_milli",
    ),
    "participant_things": (
        "thing_id",
        "kind_source",
        "kind",
        "kind_version",
        "kind_sha256",
        "region_id",
        "x_mm",
        "y_mm",
        "z_mm",
        "yaw_microradians",
    ),
    "participant_society": (
        "society_id",
        "engine_version",
        "current_tick",
        "tick_seconds",
        "state",
        "state_sha256",
    ),
    "participant_clock": ("mode", "speed", "base_tick_interval_ms", "next_due_at"),
    "participant_choices": ("choice_seq", "document"),
}
PARTICIPANT_VIEWS = frozenset(PARTICIPANT_COLUMNS)


def assert_participant_role(connection: psycopg.Connection) -> None:
    """Check the exact relation privileges, role attributes and schema write boundary."""
    with connection.cursor(row_factory=dict_row) as cursor:
        role = cursor.execute(
            "select oid,rolsuper,rolcanlogin,rolinherit,rolbypassrls,rolcreatedb,rolcreaterole,"
            "rolreplication from pg_roles where rolname=%s",
            (PARTICIPANT_ROLE,),
        ).fetchone()
        if role is None or any(value for key, value in role.items() if key != "oid"):
            raise ValueError("participant role attributes are unsafe or absent")
        if cursor.execute(
            "select 1 from pg_auth_members where member=%s", (role["oid"],)
        ).fetchone():
            raise ValueError("participant role inherits another authority")
        if cursor.execute(
            "select has_schema_privilege(%s,current_schema(),'CREATE') as may_create",
            (PARTICIPANT_ROLE,),
        ).fetchone()["may_create"]:
            raise ValueError("participant role can change its read boundary")
        rows = cursor.execute(
            "select c.relname,p.privilege from pg_class c cross join "
            "unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE',"
            "'REFERENCES','TRIGGER','MAINTAIN']) "
            "p(privilege) where c.relnamespace=current_schema()::regnamespace "
            "and c.relkind in ('r','p','v','m','f') "
            "and has_table_privilege(%s,c.oid,p.privilege)",
            (PARTICIPANT_ROLE,),
        ).fetchall()
        if {(r["relname"], r["privilege"]) for r in rows} != {
            (name, "SELECT") for name in PARTICIPANT_VIEWS
        }:
            raise ValueError(
                "participant role relation privileges differ from its closed projection"
            )
        columns = cursor.execute(
            "select c.relname,a.attname from pg_class c join pg_attribute a on a.attrelid=c.oid "
            "where c.relnamespace=current_schema()::regnamespace and c.relname=any(%s) "
            "and a.attnum>0 and not a.attisdropped order by c.relname,a.attnum",
            (sorted(PARTICIPANT_VIEWS),),
        ).fetchall()
        observed = {
            name: tuple(c["attname"] for c in columns if c["relname"] == name)
            for name in PARTICIPANT_VIEWS
        }
        if observed != PARTICIPANT_COLUMNS:
            raise ValueError("participant projection columns differ from their closed contract")
        extra_columns = cursor.execute(
            "select 1 from pg_class c join pg_attribute a on a.attrelid=c.oid "
            "cross join unnest(array['SELECT','INSERT','UPDATE','REFERENCES']) p(privilege) "
            "where c.relnamespace=current_schema()::regnamespace and a.attnum>0 and "
            "not a.attisdropped "
            "and c.relkind in ('r','p','v','m','f') "
            "and has_column_privilege(%s,c.oid,a.attnum,p.privilege) "
            "and not has_table_privilege(%s,c.oid,p.privilege) limit 1",
            (PARTICIPANT_ROLE, PARTICIPANT_ROLE),
        ).fetchone()
        if extra_columns:
            raise ValueError("participant role has an undeclared column grant")
        if cursor.execute(
            "select 1 from pg_default_acl d, lateral aclexplode(d.defaclacl) a "
            "where a.grantee=%s or d.defaclrole=%s limit 1",
            (role["oid"], role["oid"]),
        ).fetchone():
            raise ValueError("participant role receives default privileges")
        views = cursor.execute(
            "select relname,reloptions from pg_class where "
            "relnamespace=current_schema()::regnamespace "
            "and relname=any(%s) and relkind='v'",
            (sorted(PARTICIPANT_VIEWS),),
        ).fetchall()
        if len(views) != len(PARTICIPANT_VIEWS) or any(
            "security_barrier=true" not in (v["reloptions"] or []) for v in views
        ):
            raise ValueError("participant projections lack their security barriers")


def grant_participant_membership(connection: psycopg.Connection, runtime_role: str) -> None:
    """Provisioning may grant explicit SET ROLE; ordinary privileges do not inherit it."""
    if connection.execute(
        "select 1 from pg_roles where rolname=%s", (PARTICIPANT_ROLE,)
    ).fetchone():
        connection.execute(
            sql.SQL("grant {} to {} with inherit false").format(
                sql.Identifier(PARTICIPANT_ROLE), sql.Identifier(runtime_role)
            )
        )


@contextmanager
def participant_connection(
    database: Database, *, workspace_id: UUID, grant_id: UUID, principal_sha256: str
) -> Iterator[psycopg.Connection]:
    """Fresh read-only transaction, with no residual context or owner connection exposed."""
    with database.session(workspace_id) as connection, connection.transaction():
        connection.execute("set transaction isolation level repeatable read, read only")
        connection.execute(sql.SQL("set local role {}").format(sql.Identifier(PARTICIPANT_ROLE)))
        connection.execute(
            "select set_config('exulanica.participant_grant',%s,true)", (str(grant_id),)
        )
        connection.execute(
            "select set_config('exulanica.participant_principal',%s,true)", (principal_sha256,)
        )
        yield connection
