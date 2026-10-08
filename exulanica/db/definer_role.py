"""The role every SECURITY DEFINER function runs as: login-less, unprivileged, and the only owner.

Migration 0161 creates ``exulanica_definer`` and hands it every SECURITY DEFINER function in the
schema, so a definer body runs with that role's table grants and under row-level security rather
than as the superuser that applies migrations. Nothing keeps it that way by itself:

*   a later migration that drops a definer and creates it again, or creates a new one, makes the
    migrating role its owner;
*   a restore that loads a dump without its owners does the same to all of them; and
*   a role is the server's, so an administrator can give it LOGIN, a superuser attribute or a
    membership on a server this code never sees.

:func:`assert_definer_role` refuses each of these by name, and any privilege the role holds
beyond the set its bodies use or lacks from it (:data:`TABLE_PRIVILEGES`, :data:`SPENDING_STEPS`):
a later migration that strips or recreates one of those tables, or a hand grant, would otherwise
show only as a refused call at runtime. ``exulanica-db`` runs it after every migration and
provisioning, :func:`~exulanica.db.migrate.verify_schema` at every process start, the installation's
maintenance pass each time, and a local restore after its load, so a database whose definers drifted
stops a deployment or a process start rather than a request.

:data:`HAND_OVER` is 0161's own hand-over, kept here once: a restore that loaded a dump without
its owners runs it again (:func:`hand_definers_to_owner`), and a test holds that the migration
carries the same text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.migrate import applied_migrations

__all__ = [
    "COLUMN_PRIVILEGES",
    "DEFINER_MIGRATION",
    "DEFINER_ROLE",
    "HAND_OVER",
    "SPENDING_STEPS",
    "TABLE_PRIVILEGES",
    "DefinerRoleUnsafe",
    "assert_definer_role",
    "definer_role_installed",
    "hand_definers_to_owner",
]

DEFINER_ROLE: Final = "exulanica_definer"

#: The migration that creates the role and hands it the definers.
DEFINER_MIGRATION: Final = "0161"

#: Each attribute the role must not hold, and how a refusal names it.
_ATTRIBUTES: Final = {
    "rolcanlogin": "can log in",
    "rolsuper": "is a superuser",
    "rolbypassrls": "bypasses row-level security",
    "rolcreatedb": "can create databases",
    "rolcreaterole": "can create roles",
    "rolreplication": "can replicate",
    "rolinherit": "inherits",
}

#: What the owner may do to each table: what the definer bodies, and the triggers their writes
#: fire, read and write. Migration 0161 grants exactly this, with a comment naming the functions
#: behind each line; a relation absent here may be reached in no way, column grants included.
TABLE_PRIVILEGES: Final[Mapping[str, frozenset[str]]] = {
    name: frozenset(privileges)
    for name, privileges in {
        "baked_tile": ("SELECT", "INSERT", "UPDATE"),
        "baked_tile_stage": ("SELECT",),
        "door_redemption_refusal": ("SELECT", "DELETE"),
        "door_secret": ("SELECT", "DELETE"),
        "embedding": ("SELECT",),
        "material_bake": ("SELECT",),
        "material_recipe": ("SELECT",),
        "material_recipe_source": ("SELECT",),
        "person_derivative_dependency": ("SELECT",),
        "restore_control": ("SELECT",),
        "saved_world_source_attachment_operation": ("SELECT",),
        "saved_world_source_current_membership": ("SELECT", "INSERT", "UPDATE"),
        "spending_authority": ("SELECT",),
        "spending_authority_revocation": ("SELECT",),
        "spending_authority_state": ("SELECT", "UPDATE"),
        "spending_authority_term": ("SELECT",),
        "spending_event": ("INSERT",),
        "spending_grant": ("SELECT", "INSERT"),
        "spending_grant_revocation": ("SELECT", "INSERT"),
        "spending_grant_state": ("SELECT", "INSERT", "UPDATE"),
        "spending_guest_policy": ("SELECT", "UPDATE"),
        "spending_guest_policy_day": ("SELECT", "INSERT", "UPDATE"),
        "spending_reservation": ("SELECT", "INSERT", "UPDATE"),
        "tombstone": ("SELECT",),
        "tombstone_embedding_target": ("SELECT",),
        "world_project": ("SELECT", "UPDATE"),
        "world_project_item": ("SELECT", "UPDATE"),
        "world_project_item_revision": ("SELECT", "UPDATE"),
        "world_project_item_source": ("SELECT",),
        "world_project_share": ("SELECT", "UPDATE"),
    }.items()
}

#: What the owner may do to single columns, beyond its table-level privileges: table name to
#: column name to privileges, for a body that may write one column of a table and nothing else
#: of it. Checked exactly: a column grant missing, or one on a column not named here, is refused.
COLUMN_PRIVILEGES: Final[Mapping[str, Mapping[str, frozenset[str]]]] = {}

#: The internal spending steps the spending definers call, which 0124 revoked from PUBLIC: the
#: only functions outside the definers themselves that the owner may execute and PUBLIC may not.
SPENDING_STEPS: Final = frozenset(
    {
        "spending__append",
        "spending__charge",
        "spending__live_grant",
        "spending__refusal",
        "spending__refusal_without_grant",
        "spending__release_stale",
        "spending__verdict",
        "spending__witness",
        "spending__witness_authority",
        "spending__witness_position",
    }
)

#: Every SECURITY DEFINER routine in the schema, found rather than listed, handed to the owner.
#: Migration 0161 runs this text; a restore without owners runs it again.
HAND_OVER: Final = """do $owners$
declare
  f record;
begin
  for f in
    select p.oid::regprocedure as signature
      from pg_proc p
     where p.pronamespace = current_schema()::regnamespace and p.prosecdef
  loop
    execute format('alter routine %s owner to exulanica_definer', f.signature);
  end loop;
end $owners$;"""

_TABLE_PRIVILEGES_ALL: Final = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
#: The privileges a column can carry; a column grant reaches the table as far as it goes.
_COLUMN_PRIVILEGES: Final = ("SELECT", "INSERT", "UPDATE", "REFERENCES")


class DefinerRoleUnsafe(RuntimeError):
    """The definer owner is wider or narrower than migration 0161 made it, or a definer has
    another owner or search path."""


def definer_role_installed(connection: psycopg.Connection) -> bool:
    """Whether migration 0161 is recorded in the connection's schema. Asked by version, not by
    who owns the definers: a restore that handed every one of them back must still be checked."""
    return DEFINER_MIGRATION in applied_migrations(connection)


def hand_definers_to_owner(connection: psycopg.Connection) -> None:
    """Hand every SECURITY DEFINER routine in the schema to the owner, as 0161 did. For a restore
    that loaded a dump without owners, run by a superuser; :func:`assert_definer_role` follows."""
    connection.execute(HAND_OVER)


def assert_definer_role(connection: psycopg.Connection, role: str = DEFINER_ROLE) -> None:
    """Refuse a definer owner other than the one migration 0161 made, each finding by name.

    Refused: no current schema; a missing role; any of LOGIN, SUPERUSER, BYPASSRLS, CREATEDB,
    CREATEROLE, REPLICATION or INHERIT; a membership in a role or a member of it; any object in
    this database or on the server it owns other than SECURITY DEFINER routines (row-level
    security does not bind a table's owner); CREATE on the schema or the database; a default
    privilege naming it; a table privilege, column privilege, sequence privilege or function
    EXECUTE beyond :data:`TABLE_PRIVILEGES` and :data:`SPENDING_STEPS`, or one of those missing;
    a SECURITY DEFINER routine owned by another role, executable by PUBLIC, or whose search path
    does not put ``pg_catalog`` first and ``pg_temp`` last; and another role, neither a
    superuser nor a member of the schema's owner, that can create in the schema, where it could
    plant an object a definer's search path would find.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        schema = cursor.execute("select current_schema() as name").fetchone()["name"]
        if schema is None:
            raise DefinerRoleUnsafe("no current schema; the definers are checked in one schema")
        row = cursor.execute(
            "select oid, " + ", ".join(_ATTRIBUTES) + " from pg_roles where rolname = %s", (role,)
        ).fetchone()
        if row is None:
            raise DefinerRoleUnsafe(f"{role} does not exist; the definers have no narrow owner")
        oid = row["oid"]
        wider = [said for attribute, said in _ATTRIBUTES.items() if row[attribute]]
        wider += [
            f"is a member of {r['name']}"
            for r in cursor.execute(
                "select g.rolname name from pg_auth_members m "
                "join pg_roles g on g.oid = m.roleid where m.member = %s order by 1",
                (oid,),
            ).fetchall()
        ]
        wider += [
            f"is granted to {r['name']}"
            for r in cursor.execute(
                "select g.rolname name from pg_auth_members m "
                "join pg_roles g on g.oid = m.member where m.roleid = %s order by 1",
                (oid,),
            ).fetchall()
        ]
        if wider:
            raise DefinerRoleUnsafe(f"{role} " + ", ".join(wider))
        # Everything it owns in this database and on the server, as the catalog records owners,
        # but SECURITY DEFINER routines: those are its whole purpose, in this schema and in any
        # other installation's schema in the same database, which is checked as its own.
        owned = cursor.execute(
            "select pg_describe_object(d.classid, d.objid, d.objsubid) name from pg_shdepend d "
            "where d.refclassid = 'pg_authid'::regclass and d.refobjid = %(oid)s "
            "and d.deptype = 'o' "
            "and d.dbid in (0, (select oid from pg_database where datname = current_database())) "
            "and not (d.classid = 'pg_proc'::regclass and exists (select 1 from pg_proc p "
            "where p.oid = d.objid and p.prosecdef)) "
            "order by 1",
            {"oid": oid},
        ).fetchall()
        if owned:
            raise DefinerRoleUnsafe(
                f"{role} owns "
                + ", ".join(r["name"] for r in owned)
                + "; it owns the schema's SECURITY DEFINER routines and nothing else"
            )
        creates = cursor.execute(
            "select has_schema_privilege(%(role)s, %(schema)s, 'CREATE') in_schema, "
            "has_database_privilege(%(role)s, current_database(), 'CREATE') in_database",
            {"role": role, "schema": schema},
        ).fetchone()
        if creates["in_schema"] or creates["in_database"]:
            raise DefinerRoleUnsafe(
                f"{role} can create "
                + ("schema objects" if creates["in_schema"] else "schemas in this database")
            )
        defaults = cursor.execute(
            "select 1 from pg_default_acl d where d.defaclrole = %(oid)s or exists "
            "(select 1 from aclexplode(d.defaclacl) a where a.grantee = %(oid)s) limit 1",
            {"oid": oid},
        ).fetchone()
        if defaults:
            raise DefinerRoleUnsafe(f"{role} is named by a default privilege")
        _assert_privileges(cursor, role, schema)
        _assert_definers(cursor, oid, role, schema)
        planters = cursor.execute(
            "select r.rolname name from pg_roles r, pg_namespace n "
            "where n.nspname = %s and not r.rolsuper "
            "and not pg_has_role(r.oid, n.nspowner, 'MEMBER') "
            "and has_schema_privilege(r.oid, n.oid, 'CREATE') order by 1",
            (schema,),
        ).fetchall()
        if planters:
            raise DefinerRoleUnsafe(
                "roles other than the schema's owner can create in it, where a definer's search "
                "path would find what they made: " + ", ".join(r["name"] for r in planters)
            )


def _assert_privileges(cursor: psycopg.Cursor, role: str, schema: str) -> None:
    """The table, column, sequence and EXECUTE privileges equal the expected set exactly."""
    held: dict[str, set[str]] = {}
    for row in cursor.execute(
        "select c.relname, p.privilege from pg_class c, unnest(%(table)s::text[]) p(privilege) "
        "where c.relnamespace = %(schema)s::regnamespace and c.relkind in ('r','p','v','m','f') "
        "and (has_table_privilege(%(role)s, c.oid, p.privilege) or (p.privilege = any(%(column)s) "
        "and has_any_column_privilege(%(role)s, c.oid, p.privilege)))",
        {
            "table": list(_TABLE_PRIVILEGES_ALL),
            "column": list(_COLUMN_PRIVILEGES),
            "schema": schema,
            "role": role,
        },
    ).fetchall():
        held.setdefault(row["relname"], set()).add(row["privilege"])
    columns: dict[str, dict[str, set[str]]] = {}
    for row in cursor.execute(
        "select c.relname, a.attname, p.privilege from pg_class c "
        "join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped, "
        "unnest(%(column)s::text[]) p(privilege) "
        "where c.relnamespace = %(schema)s::regnamespace and c.relkind in ('r','p','v','m','f') "
        "and has_column_privilege(%(role)s, c.oid, a.attnum, p.privilege) "
        "and not has_table_privilege(%(role)s, c.oid, p.privilege)",
        {"column": list(_COLUMN_PRIVILEGES), "schema": schema, "role": role},
    ).fetchall():
        columns.setdefault(row["relname"], {}).setdefault(row["attname"], set()).add(
            row["privilege"]
        )
    whole: dict[str, set[str]] = {}
    for row in cursor.execute(
        "select c.relname, p.privilege from pg_class c, unnest(%(table)s::text[]) p(privilege) "
        "where c.relnamespace = %(schema)s::regnamespace and c.relkind in ('r','p','v','m','f') "
        "and has_table_privilege(%(role)s, c.oid, p.privilege)",
        {"table": list(_TABLE_PRIVILEGES_ALL), "schema": schema, "role": role},
    ).fetchall():
        whole.setdefault(row["relname"], set()).add(row["privilege"])
    findings = []
    for name in sorted(set(columns) | set(COLUMN_PRIVILEGES)):
        expected_columns = COLUMN_PRIVILEGES.get(name, {})
        for column in sorted(set(columns.get(name, {})) | set(expected_columns)):
            found = columns.get(name, {}).get(column, set())
            wanted = set(expected_columns.get(column, frozenset()))
            if found - wanted:
                findings.append(f"{name}.{column} {'/'.join(sorted(found - wanted))} beyond")
            if wanted - found:
                findings.append(f"{name}.{column} {'/'.join(sorted(wanted - found))} missing")
    for name in sorted(set(held) | set(TABLE_PRIVILEGES)):
        expected = TABLE_PRIVILEGES.get(name, frozenset())
        # A column grant is held through has_any_column_privilege too; it is the column map's.
        column_granted = {
            privilege for wanted in COLUMN_PRIVILEGES.get(name, {}).values() for privilege in wanted
        }
        extra = held.get(name, set()) - expected - column_granted
        missing = expected - whole.get(name, set())
        if extra:
            findings.append(f"{name} {'/'.join(sorted(extra))} beyond its bodies' use")
        if missing:
            findings.append(f"{name} {'/'.join(sorted(missing))} missing")
    sequences = cursor.execute(
        "select c.relname from pg_class c where c.relnamespace = %s::regnamespace "
        "and c.relkind = 'S' and (has_sequence_privilege(%s, c.oid, 'USAGE') "
        "or has_sequence_privilege(%s, c.oid, 'SELECT') "
        "or has_sequence_privilege(%s, c.oid, 'UPDATE')) order by 1",
        (schema, role, role, role),
    ).fetchall()
    findings += [f"sequence {r['relname']} reachable" for r in sequences]
    executable = {
        r["proname"]
        for r in cursor.execute(
            "select p.proname from pg_proc p where p.pronamespace = %s::regnamespace "
            "and not p.prosecdef and has_function_privilege(%s, p.oid, 'EXECUTE') "
            "and not has_function_privilege('public', p.oid, 'EXECUTE')",
            (schema, role),
        ).fetchall()
    }
    findings += [
        f"{name} executable beyond its bodies' use" for name in sorted(executable - SPENDING_STEPS)
    ]
    findings += [f"{name} not executable" for name in sorted(SPENDING_STEPS - executable)]
    if findings:
        raise DefinerRoleUnsafe(f"{role}'s privileges differ from 0161's: " + "; ".join(findings))


def _assert_definers(cursor: psycopg.Cursor, oid: int, role: str, schema: str) -> None:
    """Every SECURITY DEFINER routine is the role's, not PUBLIC's to call, and pinned."""
    others = cursor.execute(
        "select p.oid::regprocedure::text signature, pg_get_userbyid(p.proowner) owner "
        "from pg_proc p where p.pronamespace = %s::regnamespace and p.prosecdef "
        "and p.proowner <> %s order by 1",
        (schema, oid),
    ).fetchall()
    if others:
        raise DefinerRoleUnsafe(
            "SECURITY DEFINER functions not owned by "
            + role
            + ": "
            + ", ".join(f"{r['signature']} (owned by {r['owner']})" for r in others)
        )
    # A null ACL is the default, which lets PUBLIC execute; grantee 0 is PUBLIC.
    public = cursor.execute(
        "select p.oid::regprocedure::text signature from pg_proc p, "
        "lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
        "where p.pronamespace = %s::regnamespace and p.prosecdef and a.grantee = 0 "
        "and a.privilege_type = 'EXECUTE' order by 1",
        (schema,),
    ).fetchall()
    if public:
        raise DefinerRoleUnsafe(
            "SECURITY DEFINER functions PUBLIC may execute: "
            + ", ".join(r["signature"] for r in public)
        )
    unpinned = cursor.execute(
        "select p.oid::regprocedure::text signature from pg_proc p "
        "where p.pronamespace = %s::regnamespace and p.prosecdef and not exists ("
        "select 1 from unnest(p.proconfig) c where c ~ '^search_path=pg_catalog,(.*,)? *pg_temp$')"
        " order by 1",
        (schema,),
    ).fetchall()
    if unpinned:
        raise DefinerRoleUnsafe(
            "SECURITY DEFINER functions whose search path does not put pg_catalog first and "
            "pg_temp last: " + ", ".join(r["signature"] for r in unpinned)
        )
