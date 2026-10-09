"""Every SECURITY DEFINER function runs as a login-less owner that row-level security binds.

Migration 0161 hands every definer in the schema to ``exulanica_definer`` and gives that role the
table privileges the bodies need; ``exulanica-db`` refuses a deployment whose definers drifted
(:mod:`exulanica.db.definer_role`). Each test names a way that could be wrong: a definer left with
the migrating superuser, a privilege the bodies never use, a definer handed back by a later
migration or a restore and not noticed at deployment, or a role widened by hand and trusted.

The definers themselves run under that owner in every PostgreSQL test that calls one (the spending,
guest, tile, purge, saved-world, project and reference query retention suites); these tests hold
the ownership and the grants.
Every change they make to an owner or a role is made in a transaction they roll back, because the
schema is shared with the session's other tests and a role belongs to the whole server.
"""

from __future__ import annotations

import contextlib
import dataclasses
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
    MIGRATION_HAND_OVER,
    DefinerRoleUnsafe,
    assert_definer_role,
    definer_role_installed,
    hand_definers_to_owner,
    shipped_versions,
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
    # tg_thing_erasure_erases (0172) deletes a drafted creature's rows.
    "body_plan_version": {"SELECT", "DELETE"},
    "body_recipe_version": {"SELECT", "DELETE"},
    "door_redemption_refusal": {"SELECT", "DELETE"},
    "door_secret": {"SELECT", "DELETE"},
    "embedding": {"SELECT"},
    "look_version": {"SELECT", "DELETE"},
    "look_withdrawal": {"SELECT", "DELETE"},
    "material_bake": {"SELECT"},
    "material_recipe": {"SELECT"},
    "material_recipe_source": {"SELECT"},
    "person_derivative_dependency": {"SELECT"},
    # The erasure (0172) enqueues an erased creature's containers on its creature tombstone, and
    # a workspace tombstone its style pack files.
    "purge_job": {"INSERT"},
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
    "thing_kind_version": {"SELECT", "DELETE"},
    "tombstone": {"SELECT"},
    "tombstone_embedding_target": {"SELECT"},
    "world_project": {"SELECT", "UPDATE"},
    "world_project_item": {"SELECT", "UPDATE"},
    "world_project_item_revision": {"SELECT", "UPDATE"},
    "world_project_item_source": {"SELECT"},
    "world_project_share": {"SELECT", "UPDATE"},
    # reference_lookup_clear_queries reads a workspace's search records.
    "reference_lookup": {"SELECT"},
    "installation_style_pack_day": {"SELECT", "INSERT", "UPDATE"},
    "installation_style_pack_total": {"SELECT", "INSERT", "UPDATE"},
    "workspace_style_pack_attempt_day": {"SELECT", "INSERT", "UPDATE"},
    "workspace_style_pack_blob": {"SELECT"},
    "workspace_style_pack_file": {"SELECT", "UPDATE"},
    "workspace_style_pack_preparation": {"SELECT", "UPDATE"},
    "workspace_style_pack_publish_request": {"SELECT", "UPDATE"},
    "workspace_style_pack_version": {"SELECT", "UPDATE"},
}

#: Single columns the owner may reach beyond its table privileges: the search query that
#: reference_lookup_clear_queries clears.
COLUMN_PRIVILEGES: dict[str, dict[str, set[str]]] = {"reference_lookup": {"query": {"UPDATE"}}}

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
            "look_purge_is_authorized(uuid,uuid,text)",
            "material_bake_purge_is_authorized(uuid,uuid,bytea)",
            "reference_lookup_clear_queries(uuid)",
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
            "tg_thing_erasure_erases()",
            "tg_thing_store_erases_on_tombstone()",
            "tg_tombstone_withdraws_project_context()",
            "tg_world_project_item_erases_on_withdrawal()",
            "tg_world_project_withdraws_its_items()",
            "workspace_asset_purge_is_authorized(uuid,uuid,text)",
            "style_pack_attempt(integer,integer)",
            "style_pack_installation_bytes_admit(bigint,bigint)",
            "tg_installation_style_pack_total()",
            "tg_workspace_style_pack_purge_on_tombstone()",
            "workspace_style_pack_purge_is_authorized(uuid,uuid,text)",
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
    # The harness applies every migration without recording them; exulanica-db records each,
    # asks for this one before it checks the owner, and expects the grants of those recorded.
    for version in sorted(shipped_versions()):
        connection.execute(
            "insert into schema_migrations (version, checksum) values (%s, %s) "
            "on conflict (version) do nothing",
            (version, b"recorded"),
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
    # 0044, 0066, 0090, 0107, 0124, 0126, 0127, 0139, 0144, 0149 (door_prune, whose body 0157
    # replaced), 0155 and the search query retention migration (reference_lookup_clear_queries)
    # define 23, the migration that erases a drafted creature whole three more, and the migration
    # that keeps a workspace's own style packs five more: these 31. A create or replace that drops
    # SECURITY DEFINER leaves this set, so it fails here.
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


def _held(admin) -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    """What the owner holds on this schema's relations: each table's table-level privileges, and
    each column's privileges the table level does not already give (a column grant of a privilege
    the table holds adds nothing, so it is not counted)."""
    tables: dict[str, set[str]] = {}
    for row in admin.execute(
        "select c.relname, p.privilege from pg_class c, "
        "unnest(array['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) "
        "as p(privilege) "
        "where c.relnamespace = current_schema()::regnamespace "
        "and c.relkind in ('r', 'p', 'v', 'm', 'f') "
        "and has_table_privilege(%s, c.oid, p.privilege)",
        (DEFINER_ROLE,),
    ).fetchall():
        tables.setdefault(row["relname"], set()).add(row["privilege"])
    columns: dict[str, dict[str, set[str]]] = {}
    for row in admin.execute(
        "select c.relname, a.attname, p.privilege from pg_class c "
        "join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped, "
        "unnest(array['SELECT','INSERT','UPDATE','REFERENCES']) as p(privilege) "
        "where c.relnamespace = current_schema()::regnamespace "
        "and c.relkind in ('r', 'p', 'v', 'm', 'f') "
        "and has_column_privilege(%s, c.oid, a.attnum, p.privilege) "
        "and not has_table_privilege(%s, c.oid, p.privilege)",
        (DEFINER_ROLE, DEFINER_ROLE),
    ).fetchall():
        columns.setdefault(row["relname"], {}).setdefault(row["attname"], set()).add(
            row["privilege"]
        )
    return tables, columns


def test_the_held_view_counts_a_column_grant_as_the_column_alone(admin, monkeypatch):
    """A synthetic entry with a column grant: the view shows it under its column, not as a
    privilege on the table, and agrees with the deployment check. A column grant of a privilege
    the table already holds (SELECT of embedding.embedding_id, beside SELECT on embedding) is not
    a column of its own."""
    import dataclasses

    base = definer_role.GRANTS_BY_MIGRATION[DEFINER_MIGRATION]
    with_column = dataclasses.replace(
        base, columns={"embedding": {"embedding_id": frozenset({"UPDATE"})}}
    )
    monkeypatch.setattr(
        definer_role,
        "GRANTS_BY_MIGRATION",
        {**definer_role.GRANTS_BY_MIGRATION, DEFINER_MIGRATION: with_column},
    )
    role = sql.Identifier(DEFINER_ROLE)
    admin.execute(sql.SQL("grant update (embedding_id) on embedding to {}").format(role))
    assert_definer_role(admin)
    tables, columns = _held(admin)
    assert tables == TABLE_PRIVILEGES
    assert columns == {**COLUMN_PRIVILEGES, "embedding": {"embedding_id": {"UPDATE"}}}
    assert "SELECT" in TABLE_PRIVILEGES["embedding"]
    admin.execute(sql.SQL("grant select (embedding_id) on embedding to {}").format(role))
    assert _held(admin) == (
        TABLE_PRIVILEGES,
        {**COLUMN_PRIVILEGES, "embedding": {"embedding_id": {"UPDATE"}}},
    )


def test_a_column_grant_beside_its_tables_grant_of_the_same_privilege_passes(admin, monkeypatch):
    """An entry listing SELECT of embedding.embedding_id beside the table's SELECT on embedding,
    and both granted: nothing beyond, nothing missing."""
    import dataclasses

    base = definer_role.GRANTS_BY_MIGRATION[DEFINER_MIGRATION]
    assert "SELECT" in base.tables["embedding"]
    monkeypatch.setattr(
        definer_role,
        "GRANTS_BY_MIGRATION",
        {
            **definer_role.GRANTS_BY_MIGRATION,
            DEFINER_MIGRATION: dataclasses.replace(
                base, columns={"embedding": {"embedding_id": frozenset({"SELECT"})}}
            ),
        },
    )
    admin.execute(
        sql.SQL("grant select (embedding_id) on embedding to {}").format(
            sql.Identifier(DEFINER_ROLE)
        )
    )
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
    # A partition is read through its parent and holds nothing of its own.
    assert _held(admin) == (TABLE_PRIVILEGES, COLUMN_PRIVILEGES)
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
    """The migration's own loop is kept as it ran; a restore runs the same hand-over behind a
    refusal of routines no trusted role owns."""
    assert MIGRATION_HAND_OVER in MIGRATION.read_text(encoding="utf-8")
    loop = MIGRATION_HAND_OVER.split("begin\n", 1)[1].split("end $owners$;")[0]
    assert loop.strip() in HAND_OVER
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
    import dataclasses

    base = definer_role.GRANTS_BY_MIGRATION[DEFINER_MIGRATION]
    with_column = dataclasses.replace(
        base, columns={"embedding": {"embedding_id": frozenset({"UPDATE"})}}
    )
    monkeypatch.setattr(
        definer_role,
        "GRANTS_BY_MIGRATION",
        {**definer_role.GRANTS_BY_MIGRATION, DEFINER_MIGRATION: with_column},
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"embedding\.embedding_id UPDATE missing"):
        assert_definer_role(admin)
    # Held for the whole table instead: more than the bodies' use, said so.
    admin.execute("savepoint whole_table")
    admin.execute(sql.SQL("grant update on embedding to {}").format(sql.Identifier(DEFINER_ROLE)))
    with pytest.raises(DefinerRoleUnsafe, match=r"embedding UPDATE beyond .*whole table"):
        assert_definer_role(admin)
    admin.execute("rollback to savepoint whole_table")
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


LATER, LATEST = "9998", "9999"


@pytest.fixture
def later_migrations(monkeypatch):
    """Two later migrations this code ships, which the fixture's database does not record until a
    test does. The first grants SELECT on capture and UPDATE of embedding.embedding_id, and takes
    back SELECT on tombstone and EXECUTE on spending__charge. The second takes back that column
    grant, and revokes and grants back SELECT on capture in one migration."""
    grants = {
        **definer_role.GRANTS_BY_MIGRATION,
        LATER: definer_role.DefinerGrants(
            tables={"capture": frozenset({"SELECT"})},
            columns={"embedding": {"embedding_id": frozenset({"UPDATE"})}},
            revoked_tables={"tombstone": frozenset({"SELECT"})},
            revoked_functions=frozenset({"spending__charge"}),
        ),
        LATEST: definer_role.DefinerGrants(
            tables={"capture": frozenset({"SELECT"})},
            revoked_tables={"capture": frozenset({"SELECT"})},
            revoked_columns={"embedding": {"embedding_id": frozenset({"UPDATE"})}},
        ),
    }
    monkeypatch.setattr(definer_role, "GRANTS_BY_MIGRATION", grants)


def _record(admin, *versions: str) -> None:
    for version in versions:
        admin.execute(
            "insert into schema_migrations (version, checksum) values (%s, %s) "
            "on conflict (version) do nothing",
            (version, b"later"),
        )


def _charge(admin) -> str:
    (row,) = admin.execute(
        "select p.oid::regprocedure::text s from pg_proc p "
        "where p.pronamespace = current_schema()::regnamespace and p.proname = 'spending__charge'"
    ).fetchall()
    return row["s"]


def _production_callers(admin, monkeypatch):
    """The process-start check and a maintenance pass, as each reads the database's records."""
    from exulanica.db import migrate
    from exulanica.orchestration.installation.maintenance import Maintenance

    @contextlib.contextmanager
    def unscoped():
        yield admin

    database = SimpleNamespace(unscoped=unscoped)
    monkeypatch.setattr(migrate, "verify_applied", lambda applied: None)

    def start() -> None:
        migrate.verify_schema(database)

    def maintenance() -> list[str]:
        status: dict = {"failures": []}
        Maintenance._check_definer(SimpleNamespace(_database=database), status)
        return status["failures"]

    return start, maintenance


def test_a_database_behind_the_code_is_held_to_the_grants_it_records(
    admin, later_migrations, monkeypatch
):
    start, maintenance = _production_callers(admin, monkeypatch)
    role = sql.Identifier(DEFINER_ROLE)
    # Neither later migration recorded: their grants are not expected, everywhere it is checked.
    assert_definer_role(admin)
    start()
    assert maintenance() == []
    # The first recorded but not applied: its grants missing, its revocations not made.
    _record(admin, LATER)
    with pytest.raises(DefinerRoleUnsafe) as refused:
        assert_definer_role(admin)
    for finding in (
        "capture SELECT missing",
        "embedding.embedding_id UPDATE missing",
        "tombstone SELECT beyond",
        "spending__charge executable beyond",
    ):
        assert finding in str(refused.value), finding
    with pytest.raises(DefinerRoleUnsafe):
        start()
    assert maintenance() == ["definer_role_unsafe"]
    # Applied: each as the first says, the revoked function and column included.
    admin.execute(sql.SQL("grant select on capture to {}").format(role))
    admin.execute(sql.SQL("grant update (embedding_id) on embedding to {}").format(role))
    admin.execute(sql.SQL("revoke select on tombstone from {}").format(role))
    admin.execute(
        sql.SQL("revoke execute on function {} from {}").format(sql.SQL(_charge(admin)), role)
    )
    assert_definer_role(admin)
    start()
    # The second recorded: the column grant it takes back is now beyond, and the capture SELECT
    # it revoked and granted back in one migration is still expected.
    _record(admin, LATEST)
    with pytest.raises(DefinerRoleUnsafe, match=r"embedding\.embedding_id UPDATE beyond"):
        assert_definer_role(admin)
    admin.execute(sql.SQL("revoke update (embedding_id) on embedding from {}").format(role))
    assert_definer_role(admin)
    # The caller may name what is applied instead of the records.
    with pytest.raises(DefinerRoleUnsafe, match="capture SELECT beyond"):
        assert_definer_role(admin, applied=[DEFINER_MIGRATION])


def _overloads(admin, name: str) -> list[str]:
    return [
        row["s"]
        for row in admin.execute(
            "select p.oid::regprocedure::text s from pg_proc p "
            "where p.pronamespace = current_schema()::regnamespace and p.proname = %s",
            (name,),
        ).fetchall()
    ]


def _move_owner(admin, held: definer_role.ExpectedGrants, wanted: definer_role.ExpectedGrants):
    """Grant and revoke on the owner what takes it from ``held`` to ``wanted``: table revocations
    first (they also clear that privilege's column grants), then every grant, then the column and
    function revocations."""
    role = sql.Identifier(DEFINER_ROLE)

    def privileges(names) -> sql.Composable:
        return sql.SQL(", ").join(sql.SQL(name) for name in sorted(names))

    for table, has in held.tables.items():
        if gone := has - wanted.tables.get(table, frozenset()):
            admin.execute(
                sql.SQL("revoke {} on {} from {}").format(
                    privileges(gone), sql.Identifier(table), role
                )
            )
    for table, wants in wanted.tables.items():
        admin.execute(
            sql.SQL("grant {} on {} to {}").format(privileges(wants), sql.Identifier(table), role)
        )
    for table, by_column in wanted.columns.items():
        for column, wants in by_column.items():
            for privilege in sorted(wants):
                admin.execute(
                    sql.SQL("grant {} ({}) on {} to {}").format(
                        sql.SQL(privilege), sql.Identifier(column), sql.Identifier(table), role
                    )
                )
    for table, by_column in held.columns.items():
        for column, has in by_column.items():
            for privilege in sorted(has - wanted.columns.get(table, {}).get(column, frozenset())):
                admin.execute(
                    sql.SQL("revoke {} ({}) on {} from {}").format(
                        sql.SQL(privilege), sql.Identifier(column), sql.Identifier(table), role
                    )
                )
    for name in sorted(wanted.functions | held.functions):
        verb = "grant" if name in wanted.functions else "revoke"
        for signature in _overloads(admin, name):
            admin.execute(
                sql.SQL(
                    "grant execute on function {} to {}"
                    if verb == "grant"
                    else "revoke execute on function {} from {}"
                ).format(sql.SQL(signature), role)
            )


def _newest_entry_passes_until_recorded(admin, monkeypatch, tmp_path) -> None:
    """The drop_last case for whatever entry the newest shipped migration has: the harness really
    applied it, so what it grants or takes back is first undone on the owner, as if it had not run.
    Its entry is then given one more grant (SELECT on capture), so recording it must refuse."""
    import shutil

    from exulanica import migrations as migrations_module

    shipped = shipped_versions()
    newest = max(shipped)
    without = definer_role.expected_grants(shipped - {newest})
    _move_owner(admin, definer_role.expected_grants(shipped), without)
    assert "SELECT" not in without.tables.get("capture", frozenset())
    trimmed = tmp_path / "migrations"
    trimmed.mkdir()
    for path in migrations_module.migration_directory().glob("*.sql"):
        if not path.name.startswith(newest + "_"):
            shutil.copy2(path, trimmed / path.name)
    real = definer_role.GRANTS_BY_MIGRATION.get(newest, definer_role.DefinerGrants())
    grants = {
        **definer_role.GRANTS_BY_MIGRATION,
        newest: dataclasses.replace(
            real,
            tables={
                **real.tables,
                "capture": real.tables.get("capture", frozenset()) | {"SELECT"},
            },
        ),
    }
    monkeypatch.setattr(definer_role, "GRANTS_BY_MIGRATION", grants)
    monkeypatch.setattr(migrations_module, "migration_directory", lambda: trimmed)
    admin.execute("delete from schema_migrations where version = %s", (newest,))
    start, _maintenance = _production_callers(admin, monkeypatch)
    assert_definer_role(admin)
    start()
    _record(admin, newest)
    # SELECT alone, or beside what the newest entry itself grants on capture.
    with pytest.raises(DefinerRoleUnsafe, match=r"capture (\w+/)*SELECT(/\w+)* missing"):
        assert_definer_role(admin)


def test_an_entry_for_the_newest_migration_a_database_has_not_applied_passes_until_recorded(
    admin, monkeypatch, tmp_path
):
    """The drop_last case: code that ships one more migration than the database records, whose
    entry grants the owner something. The migration directory is left without the newest file, as
    the one-behind tests do; the check reads the database's records alone, so it passes, and once
    the newest version is recorded it refuses the grant as missing. The newest migration's own
    entry, whatever it holds, is undone first (_newest_entry_passes_until_recorded)."""
    _newest_entry_passes_until_recorded(admin, monkeypatch, tmp_path)


def test_the_newest_entry_is_undone_whatever_kind_of_grant_it_holds(admin, monkeypatch, tmp_path):
    """The same case when the newest migration's entry holds every kind: a table, a column and a
    function granted, and a table, a column and a function taken back (the column one granted by
    the migration before it). Each is made on the database first, as the migrations would."""
    shipped = shipped_versions()
    newest, previous = sorted(shipped)[-1], sorted(shipped)[-2]
    admin.execute(
        "create function a_later_step() returns int language sql "
        "set search_path = pg_catalog, pg_temp as 'select 1'"
    )
    admin.execute("revoke all on function a_later_step() from public")
    real = definer_role.GRANTS_BY_MIGRATION
    before_previous = real.get(previous, definer_role.DefinerGrants())
    before_newest = real.get(newest, definer_role.DefinerGrants())
    every_kind = {
        **real,
        previous: dataclasses.replace(
            before_previous,
            columns={
                **before_previous.columns,
                "embedding": {"embedding_id": frozenset({"UPDATE"})},
            },
        ),
        newest: dataclasses.replace(
            before_newest,
            tables={**before_newest.tables, "capture": frozenset({"INSERT"})},
            columns={**before_newest.columns, "embedding": {"embedding_id": frozenset({"INSERT"})}},
            functions=before_newest.functions | {"a_later_step"},
            revoked_tables={**before_newest.revoked_tables, "tombstone": frozenset({"SELECT"})},
            revoked_columns={
                **before_newest.revoked_columns,
                "embedding": {"embedding_id": frozenset({"UPDATE"})},
            },
            revoked_functions=before_newest.revoked_functions | {"spending__charge"},
        ),
    }
    held = definer_role.expected_grants(shipped)
    monkeypatch.setattr(definer_role, "GRANTS_BY_MIGRATION", every_kind)
    _move_owner(admin, held, definer_role.expected_grants(shipped))
    assert_definer_role(admin)
    _newest_entry_passes_until_recorded(admin, monkeypatch, tmp_path)
    # Undone means each kind went back: the revoked ones held again, the granted ones gone.
    with pytest.raises(DefinerRoleUnsafe) as refused:
        assert_definer_role(admin)
    for finding in (
        "capture INSERT/SELECT missing",
        "embedding.embedding_id INSERT missing",
        "embedding.embedding_id UPDATE beyond",
        "tombstone SELECT beyond",
        "spending__charge executable beyond",
        "a_later_step not executable",
    ):
        assert finding in str(refused.value), (finding, str(refused.value))


def test_every_listed_migration_is_one_the_code_ships():
    assert set(definer_role.GRANTS_BY_MIGRATION) <= shipped_versions()
    assert DEFINER_MIGRATION in definer_role.GRANTS_BY_MIGRATION


def test_a_restores_hand_over_refuses_a_definer_another_role_planted(admin):
    """A routine owned by a role that is neither a superuser, the schema's owner nor the definer
    owner is named and nothing is handed over: it would otherwise gain every grant the owner
    holds."""
    planter = "definer_planter_" + uuid.uuid4().hex[:10]
    admin.execute(sql.SQL("create role {} nologin").format(sql.Identifier(planter)))
    admin.execute(
        "create function a_planted_definer() returns int language sql security definer "
        "set search_path = pg_catalog, pg_temp as 'select 1'"
    )
    admin.execute(
        sql.SQL("alter function a_planted_definer() owner to {}").format(sql.Identifier(planter))
    )
    admin.execute("alter function spending_authority_facts() owner to current_user")
    admin.execute("savepoint before_hand_over")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match=r"a_planted_definer\(\)"):
        hand_definers_to_owner(admin)
    admin.execute("rollback to savepoint before_hand_over")
    # Nothing was handed over: the superuser's routine still waits for its owner.
    (owner,) = admin.execute(
        "select pg_get_userbyid(proowner) as owner from pg_proc "
        "where oid = 'spending_authority_facts()'::regprocedure"
    ).fetchall()
    assert owner["owner"] != DEFINER_ROLE
    # Without the planted routine, the superuser's is handed over.
    admin.execute("drop function a_planted_definer()")
    hand_definers_to_owner(admin)
    assert_definer_role(admin)


def _other_schema(admin, *, installation: bool) -> str:
    """A second schema in the same database: another installation (it holds schema_migrations),
    or a schema that is not one."""
    name = "definer_other_schema_" + uuid.uuid4().hex[:8]
    admin.execute(sql.SQL("create schema {}").format(sql.Identifier(name)))
    if installation:
        admin.execute(
            sql.SQL("create table {}.schema_migrations (version text, checksum bytea)").format(
                sql.Identifier(name)
            )
        )
        admin.execute(
            sql.SQL("insert into {}.schema_migrations values (%s, 'x')").format(
                sql.Identifier(name)
            ),
            (DEFINER_MIGRATION,),
        )
    return name


def _definer_in(admin, name: str, path: str, *, public: bool = False) -> None:
    admin.execute(
        sql.SQL(
            "create function {}.elsewhere() returns int language sql security definer "
            "set search_path = " + path + " as 'select 1'"
        ).format(sql.Identifier(name))
    )
    if not public:
        admin.execute(
            sql.SQL("revoke all on function {}.elsewhere() from public").format(
                sql.Identifier(name)
            )
        )
    admin.execute(
        sql.SQL("alter function {}.elsewhere() owner to {}").format(
            sql.Identifier(name), sql.Identifier(DEFINER_ROLE)
        )
    )


def test_another_installations_definer_is_its_own_but_must_still_be_pinned_and_private(admin):
    name = _other_schema(admin, installation=True)
    _definer_in(admin, name, "pg_catalog, pg_temp")
    # Another installation's definer, pinned and not PUBLIC's: checked as its own, so it passes.
    assert_definer_role(admin)
    admin.execute("savepoint pinned")
    admin.execute(
        sql.SQL("alter function {}.elsewhere() set search_path = {}, pg_catalog, pg_temp").format(
            sql.Identifier(name), sql.Identifier(name)
        )
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"does not put pg_catalog first.*elsewhere"):
        assert_definer_role(admin)
    admin.execute("rollback to savepoint pinned")
    admin.execute(
        sql.SQL("grant execute on function {}.elsewhere() to public").format(sql.Identifier(name))
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"PUBLIC may execute.*elsewhere"):
        assert_definer_role(admin)


def test_a_definer_or_a_grant_in_a_schema_that_is_no_installation_is_refused(admin):
    name = _other_schema(admin, installation=False)
    admin.execute("savepoint plain")
    _definer_in(admin, name, "pg_catalog, pg_temp")
    with pytest.raises(DefinerRoleUnsafe, match=r"owns function .*elsewhere"):
        assert_definer_role(admin)
    admin.execute("rollback to savepoint plain")
    admin.execute(sql.SQL("create table {}.kept (x int)").format(sql.Identifier(name)))
    admin.execute(
        sql.SQL("grant select on {}.kept to {}").format(
            sql.Identifier(name), sql.Identifier(DEFINER_ROLE)
        )
    )
    with pytest.raises(DefinerRoleUnsafe, match=r"grants outside any installation.*kept"):
        assert_definer_role(admin)
