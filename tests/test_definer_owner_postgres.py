"""Every SECURITY DEFINER function runs as a login-less owner that row-level security binds.

Migration 0161 hands every definer in the schema to ``exulanica_definer`` and gives that role the
table privileges the bodies need; ``exulanica-db`` refuses a deployment whose definers drifted
(:mod:`exulanica.db.definer_role`). Each test names a way that could be wrong: a definer left with
the migrating superuser, a privilege the bodies never use, a definer handed back by a later
migration or a restore and not noticed at deployment, or a role widened by hand and trusted.

The definers themselves run under that owner in every PostgreSQL test that calls one (the spending,
guest, tile, purge, saved-world and project suites); these tests hold the ownership and the grants.
Every change they make to an owner or a role is made in a transaction they roll back, because the
schema is shared with the session's other tests and a role belongs to the whole server.
"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.db import cli, definer_role
from exulanica.db.definer_role import (
    DEFINER_MIGRATION,
    DEFINER_ROLE,
    HAND_OVER,
    DefinerRoleUnsafe,
    assert_definer_role,
    definer_role_installed,
)
from exulanica.db.migrate import MigrationReport
from psycopg import sql
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

MIGRATION = next(
    (Path(__file__).parents[1] / "exulanica" / "migrations").glob(f"{DEFINER_MIGRATION}_*.sql")
)

#: What the owner may do to each table, read from the bodies (the migration's comments name them).
TABLE_PRIVILEGES = {
    "baked_tile": {"SELECT", "INSERT", "UPDATE"},
    "baked_tile_stage": {"SELECT"},
    "door_redemption_refusal": {"SELECT", "DELETE"},
    "door_secret": {"SELECT", "DELETE"},
    "embedding": {"SELECT"},
    "material_bake": {"SELECT"},
    "material_recipe": {"SELECT"},
    "material_recipe_source": {"SELECT"},
    "person_derivative_dependency": {"SELECT"},
    "restore_control": {"SELECT"},
    "saved_world_source_attachment_operation": {"SELECT"},
    "saved_world_source_current_membership": {"SELECT", "INSERT", "UPDATE"},
    "spending_authority": {"SELECT"},
    "spending_authority_revocation": {"SELECT"},
    "spending_authority_state": {"SELECT", "UPDATE"},
    "spending_authority_term": {"SELECT"},
    "spending_event": {"INSERT"},
    "spending_grant": {"SELECT", "INSERT"},
    "spending_grant_revocation": {"SELECT", "INSERT"},
    "spending_grant_state": {"SELECT", "INSERT", "UPDATE"},
    "spending_guest_policy": {"SELECT", "UPDATE"},
    "spending_guest_policy_day": {"SELECT", "INSERT", "UPDATE"},
    "spending_reservation": {"SELECT", "INSERT", "UPDATE"},
    "tombstone": {"SELECT"},
    "tombstone_embedding_target": {"SELECT"},
    "world_project": {"SELECT", "UPDATE"},
    "world_project_item": {"SELECT", "UPDATE"},
    "world_project_item_revision": {"SELECT", "UPDATE"},
    "world_project_item_source": {"SELECT"},
    "world_project_share": {"SELECT", "UPDATE"},
}

#: Single columns the owner may reach beyond its table privileges: none today.
COLUMN_PRIVILEGES: dict[str, dict[str, set[str]]] = {}

#: Every SECURITY DEFINER function, and its search path with the schema written as {schema}:
#: door_prune and record_baked_tile_bake qualify every name and keep pg_catalog, pg_temp; 0161
#: re-pins the rest pg_catalog first.
DEFINERS = {
    signature: path
    for path, signatures in {
        "pg_catalog, pg_temp": (
            "door_prune(integer)",
            "record_baked_tile_bake(uuid,integer,bytea,bytea,bytea,jsonb,bytea,bytea,integer,"
            "integer,integer,integer,integer,bytea,bigint,bytea,bigint,bytea,bytea,jsonb)",
        ),
        "pg_catalog, {schema}, pg_temp": (
            "caption_vector_purge_is_authorized(uuid,uuid,uuid)",
            "caption_vector_purge_is_complete(uuid,uuid)",
            "material_bake_purge_is_authorized(uuid,uuid,bytea)",
            "spending_admit(uuid,uuid,text,uuid,text,text,text,numeric,text,jsonb)",
            "spending_authority_facts()",
            "spending_close_bound(uuid,uuid,text,text)",
            "spending_dispatch(uuid,uuid,text,jsonb)",
            "spending_grant_guest(uuid,text,uuid,text,jsonb)",
            "spending_guest_policy_authority(text)",
            "spending_open_bound(uuid,text,text,numeric,integer,timestamp with time zone,text,"
            "text)",
            "spending_settle(uuid,uuid,text,text,numeric,integer,integer,jsonb)",
            "tg_companion_answers_withdraw_project_items()",
            "tg_saved_world_source_attachment_moves_membership()",
            "tg_saved_world_source_detach_moves_membership()",
            "tg_sealed_checkpoint_refuses_withdrawals()",
            "tg_spending_event_ends_guest_policies()",
            "tg_tombstone_withdraws_project_context()",
            "tg_world_project_item_erases_on_withdrawal()",
            "tg_world_project_withdraws_its_items()",
            "workspace_asset_purge_is_authorized(uuid,uuid,text)",
        ),
    }.items()
    for signature in signatures
}

#: The internal steps the spending definers call; 0124 revoked them from PUBLIC.
SPENDING_STEPS = {
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


@pytest.fixture
def admin(spine_schema):
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.autocommit = False
    connection.row_factory = dict_row
    # The harness applies the migrations without recording them; exulanica-db records each, and
    # asks for this one before it checks the owner.
    connection.execute(
        "insert into schema_migrations (version, checksum) values (%s, %s) "
        "on conflict (version) do nothing",
        (DEFINER_MIGRATION, b"recorded"),
    )
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _definers(admin) -> dict[str, str]:
    return {
        row["signature"]: row["owner"]
        for row in admin.execute(
            "select p.oid::regprocedure::text signature, pg_get_userbyid(p.proowner) owner "
            "from pg_proc p where p.pronamespace = current_schema()::regnamespace "
            "and p.prosecdef"
        ).fetchall()
    }


def test_every_definer_belongs_to_the_login_less_owner_and_the_check_passes(admin):
    definers = _definers(admin)
    # 0044, 0066, 0090, 0107, 0124, 0126, 0127, 0139, 0144, 0149 and 0155 define these 22. A
    # create or replace that drops SECURITY DEFINER leaves this set, so it fails here.
    assert set(definers) == set(DEFINERS), definers
    assert {owner for owner in definers.values()} == {DEFINER_ROLE}, definers
    schema = admin.execute("select current_schema() s").fetchone()["s"]
    paths = {
        row["signature"]: row["config"]
        for row in admin.execute(
            "select p.oid::regprocedure::text signature, p.proconfig config from pg_proc p "
            "where p.pronamespace = current_schema()::regnamespace and p.prosecdef"
        ).fetchall()
    }
    assert paths == {
        signature: [f"search_path={path.format(schema=schema)}"]
        for signature, path in DEFINERS.items()
    }
    role = admin.execute(
        "select rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
        "rolreplication, rolinherit from pg_roles where rolname = %s",
        (DEFINER_ROLE,),
    ).fetchone()
    assert role is not None and not any(role.values()), role
    assert definer_role_installed(admin)
    assert_definer_role(admin)


def test_the_owner_holds_the_privileges_its_bodies_use_and_nothing_else(admin):
    # This file's literal is read from the bodies apart from the module's; the deployment check
    # refuses by the module's, so the two must agree as well as match the database.
    assert {name: set(held) for name, held in definer_role.TABLE_PRIVILEGES.items()} == (
        TABLE_PRIVILEGES
    )
    assert set(definer_role.SPENDING_STEPS) == SPENDING_STEPS
    assert {
        table: {column: set(held) for column, held in columns.items()}
        for table, columns in definer_role.COLUMN_PRIVILEGES.items()
    } == COLUMN_PRIVILEGES
    held: dict[str, set[str]] = {}
    for row in admin.execute(
        "select c.relname, p.privilege from pg_class c, "
        "unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) "
        "as p(privilege) "
        "where c.relnamespace = current_schema()::regnamespace "
        "and c.relkind in ('r', 'p', 'v', 'm', 'f') "
        "and (has_table_privilege(%s, c.oid, p.privilege) "
        "or (p.privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES') "
        "and has_any_column_privilege(%s, c.oid, p.privilege)))",
        (DEFINER_ROLE, DEFINER_ROLE),
    ).fetchall():
        held.setdefault(row["relname"], set()).add(row["privilege"])
    # A partition is read through its parent and holds nothing of its own.
    assert held == TABLE_PRIVILEGES
    sequences = admin.execute(
        "select c.relname from pg_class c where c.relnamespace = current_schema()::regnamespace "
        "and case when c.relkind = 'S' "
        "then has_sequence_privilege(%s, c.oid, 'USAGE,SELECT,UPDATE') else false end",
        (DEFINER_ROLE,),
    ).fetchall()
    assert sequences == []
    # Functions anyone may call are not the owner's grant; those revoked from PUBLIC are.
    executable = {
        row["proname"]
        for row in admin.execute(
            "select p.proname from pg_proc p "
            "where p.pronamespace = current_schema()::regnamespace and not p.prosecdef "
            "and has_function_privilege(%s, p.oid, 'EXECUTE') "
            "and not has_function_privilege('public', p.oid, 'EXECUTE')",
            (DEFINER_ROLE,),
        ).fetchall()
    }
    assert executable == SPENDING_STEPS
    assert not admin.execute(
        "select has_schema_privilege(%s, current_schema(), 'CREATE') allowed", (DEFINER_ROLE,)
    ).fetchone()["allowed"]


def test_a_definer_handed_back_to_the_migrating_role_is_refused_by_name(admin):
    signature = "spending_grant_guest(uuid,text,uuid,text,jsonb)"
    admin.execute(f"alter function {signature} owner to current_user")
    with pytest.raises(DefinerRoleUnsafe, match=r"spending_grant_guest\(uuid,text"):
        assert_definer_role(admin)
    # Every definer handed back, as a restore without owners would leave them: still asked.
    for definer in _definers(admin):
        admin.execute(f"alter function {definer} owner to current_user")
    assert definer_role_installed(admin)
    with pytest.raises(DefinerRoleUnsafe, match="not owned by exulanica_definer"):
        assert_definer_role(admin)


def test_a_new_definer_the_migrating_role_creates_is_refused(admin):
    admin.execute(
        "create function a_definer_left_behind() returns int language sql security definer "
        "set search_path = pg_catalog, pg_temp as 'select 1'"
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"a_definer_left_behind\(\)"):
        assert_definer_role(admin)


def test_the_migration_hands_the_definers_over_by_the_text_a_restore_runs():
    """A restore without owners runs :data:`HAND_OVER` again; it is the migration's own loop."""
    assert HAND_OVER in MIGRATION.read_text(encoding="utf-8")
    assert "alter routine %s owner to exulanica_definer" in HAND_OVER


@pytest.mark.parametrize(
    ("widened", "said"),
    [
        ("alter role {role} login", "can log in"),
        ("alter role {role} superuser", "is a superuser"),
        ("alter role {role} bypassrls", "bypasses row-level security"),
        ("alter role {role} createdb", "can create databases"),
        ("alter role {role} createrole", "can create roles"),
        ("alter role {role} replication", "can replicate"),
        ("alter role {role} inherit", "inherits"),
        ("grant {role} to {other}", "is granted to"),
        ("grant {other} to {role}", "is a member of"),
    ],
)
def test_a_widened_owner_is_refused_by_the_check_and_by_the_migration(admin, widened, said):
    """Widened inside this transaction only: the role is the server's, and the rollback undoes
    it before any other test's transaction can see it."""
    other = "definer_other_" + uuid.uuid4().hex[:10]
    admin.execute(sql.SQL("create role {} nologin").format(sql.Identifier(other)))
    admin.execute(
        sql.SQL(widened).format(role=sql.Identifier(DEFINER_ROLE), other=sql.Identifier(other))
    )
    with pytest.raises(DefinerRoleUnsafe, match=said):
        assert_definer_role(admin)
    admin.execute("savepoint before_migration")
    # The migration finds the role and refuses it rather than narrowing it. Its own transaction
    # and lock are left out: this test's transaction holds the change, and other sessions'
    # migrations must not wait on the lock while it does.
    body = MIGRATION.read_text(encoding="utf-8")
    for statement in ("\nbegin;\n", "\nselect pg_advisory_xact_lock(119622309);\n", "\ncommit;\n"):
        assert statement in body, statement
        body = body.replace(statement, "\n", 1)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match=said):
        admin.execute(body)
    admin.execute("rollback to savepoint before_migration")


def test_exulanica_db_stops_a_deployment_whose_definer_drifted(admin, monkeypatch):
    """The provisioning command checks the definers after its roles, as it checks the tile role:
    the migration and role steps stand still here and the check runs against this schema."""
    admin.execute("alter function spending_authority_facts() owner to current_user")

    @contextlib.contextmanager
    def unscoped():
        yield admin

    report = MigrationReport(applied=(), already_present=())
    monkeypatch.setattr(cli, "apply_pending", lambda database: report)
    for step in (
        "provision_runtime_role",
        "provision_purge_role",
        "provision_account_role",
        "provision_backup_role",
        "provision_tiles_role",
        "assert_tiles_role",
    ):
        monkeypatch.setattr(cli, step, lambda *args, **kwargs: None)
    with pytest.raises(DefinerRoleUnsafe, match=r"spending_authority_facts\(\)"):
        cli.provision_database(SimpleNamespace(unscoped=unscoped), stream=None)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        # Reach beyond the bodies' use, each kind a deployment would otherwise trust.
        ("grant delete on spending_event to {role}", r"spending_event DELETE beyond"),
        ("grant update (embedding_id) on embedding to {role}", r"embedding UPDATE beyond"),
        ("grant select on capture to {role}", r"capture SELECT beyond"),
        ("grant execute on function spending__genesis to {role}", "spending__genesis executable"),
        # A grant the bodies need, stripped by a later migration or by hand.
        ("revoke update on baked_tile from {role}", "baked_tile UPDATE missing"),
        ("revoke execute on function spending__charge from {role}", "spending__charge not exec"),
        # Ownership and creation.
        (
            "create table owned_by_the_definer (x int); "
            "alter table owned_by_the_definer owner to {role}",
            "owns table owned_by_the_definer",
        ),
        ("grant create on schema {schema} to {role}", "can create schema objects"),
        ("grant create on database {database} to {role}", "can create schemas in this database"),
        (
            "alter default privileges for role {role} grant select on tables to public",
            "owns default privileges",
        ),
        (
            "alter default privileges grant select on tables to {role}",
            "named by a default privilege",
        ),
        # The definers themselves.
        (
            "grant execute on function spending_authority_facts() to public",
            "PUBLIC may execute: spending_authority_facts()",
        ),
        (
            "alter function door_prune(integer) set search_path = {schema}, pg_catalog, pg_temp",
            r"search path does not put pg_catalog first.*door_prune\(integer\)",
        ),
        (
            "alter function door_prune(integer) reset search_path",
            r"search path does not put pg_catalog first.*door_prune\(integer\)",
        ),
        # Anyone else able to plant an object a definer's search path finds.
        (
            "create role {other} nologin; grant create on schema {schema} to {other}",
            "can create in it.*{other}",
        ),
    ],
)
def test_each_drift_the_deployment_check_refuses(admin, change, said):
    """Each made inside this transaction only, and named by the refusal."""
    other = "definer_other_" + uuid.uuid4().hex[:10]
    names = admin.execute("select current_schema() s, current_database() d").fetchone()
    values = {
        "role": sql.Identifier(DEFINER_ROLE),
        "other": sql.Identifier(other),
        "schema": sql.Identifier(names["s"]),
        "database": sql.Identifier(names["d"]),
    }
    assert_definer_role(admin)
    for statement in change.split("; "):
        if "spending__genesis" in statement:
            (signature,) = admin.execute(
                "select p.oid::regprocedure::text s from pg_proc p "
                "where p.pronamespace = current_schema()::regnamespace "
                "and p.proname = 'spending__genesis'"
            ).fetchall()
            statement = statement.replace("spending__genesis", signature["s"])
        if "spending__charge" in statement:
            (signature,) = admin.execute(
                "select p.oid::regprocedure::text s from pg_proc p "
                "where p.pronamespace = current_schema()::regnamespace "
                "and p.proname = 'spending__charge'"
            ).fetchall()
            statement = statement.replace("spending__charge", signature["s"])
        admin.execute(sql.SQL(statement).format(**values))
    with pytest.raises(DefinerRoleUnsafe, match=said.format(other=other)):
        assert_definer_role(admin)


def test_a_missing_role_and_a_missing_schema_are_refused(admin):
    with pytest.raises(DefinerRoleUnsafe, match="does not exist"):
        assert_definer_role(admin, role="no_such_definer_" + uuid.uuid4().hex[:8])
    admin.execute("set local search_path = ''")
    with pytest.raises(DefinerRoleUnsafe, match="no current schema"):
        assert_definer_role(admin)


def test_a_process_start_and_a_maintenance_pass_refuse_a_drifted_definer(admin, monkeypatch):
    """Between deployments the check runs where a process starts serving (verify_schema) and in
    every unattended maintenance pass, which reports it by code rather than stopping."""
    from exulanica.db import migrate
    from exulanica.orchestration.installation.maintenance import Maintenance

    @contextlib.contextmanager
    def unscoped():
        yield admin

    database = SimpleNamespace(unscoped=unscoped)
    # The harness records 0161 with a stand-in checksum; the recorded-checksum check is not
    # what is asked here.
    monkeypatch.setattr(migrate, "verify_applied", lambda applied: None)
    migrate.verify_schema(database)
    status: dict = {"failures": []}
    Maintenance._check_definer(SimpleNamespace(_database=database), status)
    assert status == {"failures": []}

    admin.execute("alter function spending_authority_facts() owner to current_user")
    with pytest.raises(DefinerRoleUnsafe, match=r"spending_authority_facts\(\)"):
        migrate.verify_schema(database)
    Maintenance._check_definer(SimpleNamespace(_database=database), status)
    assert status["failures"] == ["definer_role_unsafe"]
    assert "spending_authority_facts()" in status["detail"]["definer_role_unsafe"]


def test_a_column_the_set_names_is_held_exactly(admin, monkeypatch):
    """A body that writes one column of a table is granted that column alone: the check refuses
    the column grant missing, and accepts it once made."""
    monkeypatch.setattr(
        definer_role, "COLUMN_PRIVILEGES", {"embedding": {"embedding_id": frozenset({"UPDATE"})}}
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"embedding\.embedding_id UPDATE missing"):
        assert_definer_role(admin)
    admin.execute(
        sql.SQL("grant update (embedding_id) on embedding to {}").format(
            sql.Identifier(DEFINER_ROLE)
        )
    )
    assert_definer_role(admin)
    # A second column beyond the one named is refused.
    admin.execute(
        sql.SQL("grant update (workspace_id) on embedding to {}").format(
            sql.Identifier(DEFINER_ROLE)
        )
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"embedding\.workspace_id UPDATE beyond"):
        assert_definer_role(admin)
