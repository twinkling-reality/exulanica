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
beyond, or lacks from, what the migrations the database records grant it
(:data:`GRANTS_BY_MIGRATION`, one entry per migration that grants or revokes): a later migration
that strips or recreates one of those tables, or a hand grant, would otherwise show only as a
refused call at runtime. ``exulanica-db`` runs it after every migration and
provisioning, :func:`~exulanica.db.migrate.verify_schema` at every process start, the installation's
maintenance pass each time, and a local restore after its load, so a database whose definers drifted
stops a deployment or a process start rather than a request.

:data:`MIGRATION_HAND_OVER` is 0161's own hand-over, kept here as it ran, and a test holds that the
migration carries the same text. :data:`HAND_OVER` is what a restore that loaded a dump without its
owners runs (:func:`hand_definers_to_owner`): the same loop behind a refusal of any routine a role
other than a superuser, the schema's owner or the definer owner owns.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.migrate import applied_migrations
from exulanica.migrations import migrations

__all__ = [
    "COLUMN_PRIVILEGES",
    "DEFINER_MIGRATION",
    "DEFINER_ROLE",
    "GRANTS_BY_MIGRATION",
    "HAND_OVER",
    "MIGRATION_HAND_OVER",
    "SPENDING_STEPS",
    "TABLE_PRIVILEGES",
    "DefinerGrants",
    "DefinerRoleUnsafe",
    "ExpectedGrants",
    "assert_definer_role",
    "definer_role_installed",
    "expected_grants",
    "hand_definers_to_owner",
    "shipped_versions",
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


@dataclass(frozen=True)
class DefinerGrants:
    """What one migration grants exulanica_definer, and what it takes back.

    ``tables``: table name to table-level privileges. ``columns``: table name to column name to
    privileges, for a body that may write one column of a table and nothing else of it.
    ``functions``: functions outside the definers that the owner may execute and PUBLIC may not.
    The ``revoked_`` fields are what a migration takes away from what earlier ones granted.
    """

    tables: Mapping[str, frozenset[str]] = field(default_factory=dict)
    columns: Mapping[str, Mapping[str, frozenset[str]]] = field(default_factory=dict)
    functions: frozenset[str] = frozenset()
    revoked_tables: Mapping[str, frozenset[str]] = field(default_factory=dict)
    revoked_columns: Mapping[str, Mapping[str, frozenset[str]]] = field(default_factory=dict)
    revoked_functions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ExpectedGrants:
    """What the owner holds on a database whose recorded migrations are given: the union of
    those migrations' :class:`DefinerGrants`, in version order, less what each took back."""

    tables: Mapping[str, frozenset[str]]
    columns: Mapping[str, Mapping[str, frozenset[str]]]
    functions: frozenset[str]


#: What each migration grants the owner, by its version. The definer migration's own entry is
#: what its bodies (the definers that exist when it runs) read and write, with a comment in the
#: migration naming the functions behind each line. A later migration that grants or revokes
#: anything to the owner adds its own entry, in the same package as its grants, so a database one
#: migration behind the code is held to the grants of the migrations it records, not the code's.
GRANTS_BY_MIGRATION: Final[Mapping[str, DefinerGrants]] = {
    DEFINER_MIGRATION: DefinerGrants(
        tables={
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
        },
        # The internal spending steps the spending definers call, which 0124 revoked from
        # PUBLIC.
        functions=frozenset(
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
        ),
    ),
    # The search query retention migration: reference_lookup_clear_queries reads a workspace's
    # search records and clears their query text, the one column it writes.
    "0168": DefinerGrants(
        tables={"reference_lookup": frozenset({"SELECT"})},
        columns={"reference_lookup": {"query": frozenset({"UPDATE"})}},
    ),
    # tg_thing_erasure_erases and tg_thing_store_erases_on_tombstone (0172) delete a drafted
    # creature's rows, and every creature's of an erased workspace, and the erasure enqueues its
    # looks' containers on its creature tombstone (INSERT alone: no conflict target). The erasure
    # and look_purge_is_authorized read tombstone under 0161's grant.
    "0172": DefinerGrants(
        tables={
            **{
                name: frozenset(("SELECT", "DELETE"))
                for name in (
                    "body_plan_version",
                    "body_recipe_version",
                    "look_version",
                    "look_withdrawal",
                    "thing_kind_version",
                )
            },
            "purge_job": frozenset(("INSERT",)),
        }
    ),
}


def expected_grants(applied: Iterable[str]) -> ExpectedGrants:
    """The owner's privileges on a database that records the migration versions ``applied``.

    The rules a migration's entry follows, as PostgreSQL applies its statements:

    1. Within one entry, its revocations apply before its grants, so an entry that revokes a
       privilege and grants it back in one migration expects it held.
    2. A table-level revocation also takes that privilege from every column of the table, as
       ``REVOKE ... ON <table>`` clears the column grants of that privilege.
    3. A migration that drops a listed table or function lists it in its ``revoked_`` fields,
       or the check expects a privilege on an object that no longer exists ("missing").
    4. A column privilege the same table holds at table level adds nothing, as in PostgreSQL, so
       it is not expected for the column alone.

    When listing what a body needs: ``INSERT ... ON CONFLICT (columns) DO NOTHING`` needs SELECT
    on the table as well as INSERT (with INSERT alone it is refused "permission denied for
    table"), while a bare ``ON CONFLICT DO NOTHING`` needs INSERT alone; a WHERE, RETURNING or
    FOR UPDATE reads, so it needs SELECT, and FOR UPDATE needs UPDATE too.
    """
    if isinstance(applied, str):
        raise TypeError("applied is a collection of migration versions, not one version")
    recorded = set(applied)
    tables: dict[str, set[str]] = {}
    columns: dict[str, dict[str, set[str]]] = {}
    functions: set[str] = set()
    for version in sorted(GRANTS_BY_MIGRATION):
        if version not in recorded:
            continue
        grants = GRANTS_BY_MIGRATION[version]
        for name, privileges in grants.revoked_tables.items():
            tables.setdefault(name, set()).difference_update(privileges)
            for held in columns.get(name, {}).values():
                held.difference_update(privileges)
        for name, by_column in grants.revoked_columns.items():
            for column, privileges in by_column.items():
                columns.setdefault(name, {}).setdefault(column, set()).difference_update(privileges)
        functions -= grants.revoked_functions
        for name, privileges in grants.tables.items():
            tables.setdefault(name, set()).update(privileges)
        for name, by_column in grants.columns.items():
            for column, privileges in by_column.items():
                columns.setdefault(name, {}).setdefault(column, set()).update(privileges)
        functions |= grants.functions
    for name, by_column in columns.items():
        for held in by_column.values():
            held.difference_update(tables.get(name, set()))
    return ExpectedGrants(
        tables={name: frozenset(held) for name, held in tables.items() if held},
        columns={
            name: {column: frozenset(held) for column, held in by_column.items() if held}
            for name, by_column in columns.items()
            if any(by_column.values())
        },
        functions=frozenset(functions),
    )


def shipped_versions() -> frozenset[str]:
    """Every migration version this code ships."""
    return frozenset(migration.version for migration in migrations())


_EVERY = expected_grants(GRANTS_BY_MIGRATION)

#: What the owner holds on a database that records every migration this code ships: views
#: derived from :data:`GRANTS_BY_MIGRATION`, for readers that want the whole set.
TABLE_PRIVILEGES: Final[Mapping[str, frozenset[str]]] = _EVERY.tables
COLUMN_PRIVILEGES: Final[Mapping[str, Mapping[str, frozenset[str]]]] = _EVERY.columns
SPENDING_STEPS: Final = _EVERY.functions

#: Every SECURITY DEFINER routine in the schema, found rather than listed, handed to the owner,
#: as migration 0161 ran it (its text, kept so a test holds the migration to it).
MIGRATION_HAND_OVER: Final = """do $owners$
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

#: The hand-over a restore runs again: only routines owned by a superuser (as a load without
#: owners leaves them), a member of the schema's owner, or the role itself; any other owner is
#: named and nothing is handed over, because a routine some other role planted would otherwise
#: gain every grant the definer owner holds.
HAND_OVER: Final = """do $owners$
declare
  f record;
  strangers text;
begin
  select string_agg(format('%s (owned by %s)', p.oid::regprocedure, o.rolname), ', '
                    order by p.oid::regprocedure::text)
    into strangers
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    join pg_roles o on o.oid = p.proowner
   where p.pronamespace = current_schema()::regnamespace and p.prosecdef
     and not o.rolsuper and o.rolname <> 'exulanica_definer'
     and not pg_has_role(o.oid, n.nspowner, 'MEMBER');
  if strangers is not null then
    raise exception 'not handed to exulanica_definer, owned by a role that is neither a '
                    'superuser, the schema''s owner nor the definer owner: %', strangers
      using errcode = '42501';
  end if;
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
    """The definer owner is wider or narrower than the recorded migrations made it, or a definer has
    another owner or search path."""


def definer_role_installed(connection: psycopg.Connection) -> bool:
    """Whether migration 0161 is recorded in the connection's schema. Asked by version, not by
    who owns the definers: a restore that handed every one of them back must still be checked."""
    return DEFINER_MIGRATION in applied_migrations(connection)


def hand_definers_to_owner(connection: psycopg.Connection) -> None:
    """Hand the schema's SECURITY DEFINER routines to the owner, for a restore that loaded a dump
    without owners, run by a superuser; :func:`assert_definer_role` follows. Unlike 0161's own
    loop (:data:`MIGRATION_HAND_OVER`), it first refuses any routine another role planted
    (:data:`HAND_OVER`)."""
    connection.execute(HAND_OVER)


def assert_definer_role(
    connection: psycopg.Connection,
    role: str = DEFINER_ROLE,
    *,
    applied: Iterable[str] | None = None,
) -> None:
    """Refuse a definer owner other than the one the recorded migrations made, each finding by
    name.

    Refused: no current schema; a missing role; any of LOGIN, SUPERUSER, BYPASSRLS, CREATEDB,
    CREATEROLE, REPLICATION or INHERIT; a membership in a role or a member of it; any object in
    this database or on the server it owns other than SECURITY DEFINER routines in this schema
    or another installation's (row-level security does not bind a table's owner); an explicit
    grant on a relation in a schema that is no installation; CREATE on the schema or the
    database; a default privilege naming it; a table privilege, column privilege, sequence
    privilege or function EXECUTE beyond what the migrations the database records grant it
    (:func:`expected_grants` over ``applied``, read from ``schema_migrations`` when not given),
    or one of those missing (an entry for a migration this code does not ship is never recorded,
    so it fails closed: its grants read beyond, its revocations missing); a SECURITY DEFINER
    routine in the schema owned by another role; any routine the role owns, wherever it is,
    executable by PUBLIC or whose search path does not put ``pg_catalog`` first and ``pg_temp``
    last; and another role, neither a superuser nor a member of the schema's owner, that can
    create in the schema, where it could plant an object a definer's search path would find.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        schema = cursor.execute("select current_schema() as name").fetchone()["name"]
        if schema is None:
            raise DefinerRoleUnsafe("no current schema; the definers are checked in one schema")
        expected = expected_grants(applied_migrations(connection) if applied is None else applied)
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
        # but SECURITY DEFINER routines in this schema or in another installation's schema in the
        # same database (one holding schema_migrations), which is checked as its own.
        rows = cursor.execute(
            "select pg_describe_object(d.classid, d.objid, d.objsubid) as name, "
            "(select n.nspname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where d.classid = 'pg_proc'::regclass and p.oid = d.objid and p.prosecdef) "
            "as definer_schema "
            "from pg_shdepend d "
            "where d.refclassid = 'pg_authid'::regclass and d.refobjid = %(oid)s "
            "and d.deptype = 'o' "
            "and d.dbid in (0, (select oid from pg_database where datname = current_database())) "
            "order by 1",
            {"oid": oid},
        ).fetchall()
        installations = _installations(
            cursor, {r["definer_schema"] for r in rows if r["definer_schema"]} - {schema}
        )
        owned = [
            r
            for r in rows
            if r["definer_schema"] is None
            or (r["definer_schema"] != schema and r["definer_schema"] not in installations)
        ]
        elsewhere = cursor.execute(
            "select format('%%s on %%I.%%I', a.privilege_type, n.nspname, c.relname) as name, "
            "n.nspname as schema from pg_class c join pg_namespace n on n.oid = c.relnamespace, "
            "lateral aclexplode(c.relacl) a "
            "where a.grantee = %(oid)s and n.nspname <> %(schema)s order by 1",
            {"oid": oid, "schema": schema},
        ).fetchall()
        outside = _installations(cursor, {r["schema"] for r in elsewhere})
        stray = [r["name"] for r in elsewhere if r["schema"] not in outside]
        if stray:
            raise DefinerRoleUnsafe(
                f"{role} holds grants outside any installation's schema: " + ", ".join(stray)
            )
        if owned:
            raise DefinerRoleUnsafe(
                f"{role} owns "
                + ", ".join(r["name"] for r in owned)
                + "; it owns SECURITY DEFINER routines in this schema or another installation's"
                + " and nothing else"
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
        _assert_privileges(cursor, role, schema, expected)
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


def _installations(cursor: psycopg.Cursor, schemas: Iterable[str]) -> frozenset[str]:
    """Which of ``schemas`` are installations: those holding a schema_migrations table, which
    each check as their own. Not whether it records the definer migration: a test harness applies
    every migration without recording any, and an installation the caller cannot read checks
    itself. A schema without one is not an installation; nothing of the owner's belongs there."""
    names = sorted(schemas)
    if not names:
        return frozenset()
    rows = cursor.execute(
        "select n.nspname as name from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = any(%s) and c.relname = 'schema_migrations' and c.relkind = 'r'",
        (names,),
    ).fetchall()
    return frozenset(row["name"] for row in rows)


def _assert_privileges(
    cursor: psycopg.Cursor, role: str, schema: str, expected: ExpectedGrants
) -> None:
    """The table, column, sequence and EXECUTE privileges equal ``expected`` exactly."""
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
    for name in sorted(set(columns) | set(expected.columns)):
        expected_columns = expected.columns.get(name, {})
        for column in sorted(set(columns.get(name, {})) | set(expected_columns)):
            found = columns.get(name, {}).get(column, set())
            wanted = set(expected_columns.get(column, frozenset()))
            if found - wanted:
                findings.append(f"{name}.{column} {'/'.join(sorted(found - wanted))} beyond")
            # The column privilege held for the whole table instead is more than the bodies' use,
            # not a missing grant.
            widened = (wanted - found) & whole.get(name, set())
            if widened:
                findings.append(
                    f"{name} {'/'.join(sorted(widened))} beyond its bodies' use "
                    f"(held for the whole table; only {column} is theirs)"
                )
            if wanted - found - widened:
                findings.append(
                    f"{name}.{column} {'/'.join(sorted(wanted - found - widened))} missing"
                )
    for name in sorted(set(held) | set(expected.tables)):
        table_wanted = expected.tables.get(name, frozenset())
        # A column grant is held through has_any_column_privilege too; it is the column map's.
        column_granted = {
            privilege for wanted in expected.columns.get(name, {}).values() for privilege in wanted
        }
        extra = held.get(name, set()) - table_wanted - column_granted
        missing = table_wanted - whole.get(name, set())
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
        f"{name} executable beyond its bodies' use"
        for name in sorted(executable - expected.functions)
    ]
    findings += [f"{name} not executable" for name in sorted(expected.functions - executable)]
    if findings:
        raise DefinerRoleUnsafe(
            f"{role}'s privileges differ from its migrations' grants: " + "; ".join(findings)
        )


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
        "where (p.pronamespace = %s::regnamespace or p.proowner = %s) and p.prosecdef "
        "and a.grantee = 0 and a.privilege_type = 'EXECUTE' order by 1",
        (schema, oid),
    ).fetchall()
    if public:
        raise DefinerRoleUnsafe(
            "SECURITY DEFINER functions PUBLIC may execute: "
            + ", ".join(r["signature"] for r in public)
        )
    unpinned = cursor.execute(
        "select p.oid::regprocedure::text signature from pg_proc p "
        "where (p.pronamespace = %s::regnamespace or p.proowner = %s) and p.prosecdef "
        "and not exists (select 1 from unnest(p.proconfig) c "
        "where c ~ '^search_path=pg_catalog,(.*,)? *pg_temp$') order by 1",
        (schema, oid),
    ).fetchall()
    if unpinned:
        raise DefinerRoleUnsafe(
            "SECURITY DEFINER functions whose search path does not put pg_catalog first and "
            "pg_temp last: " + ", ".join(r["signature"] for r in unpinned)
        )
