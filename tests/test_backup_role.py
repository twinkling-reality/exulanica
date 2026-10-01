"""The backup role reads every row after the whole migration chain and can write nothing.

Unattended maintenance dumps the database and exports withdrawals as this role, so that the
process that runs without anyone watching never holds the owner. Each property here is one the
owner would otherwise have been trusted with.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid

import psycopg
import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import backup_role_gaps, provision_backup_role
from exulanica.deletion.restore import checkpoint, export_withdrawals
from psycopg import sql

from test_purge import purged as purged
from test_restore_replay import _capture, _postgres_tool, _restore

_ROLE = "exulanica_backup_test"
_PASSWORD = "backup-role-test-" + uuid.uuid4().hex


def _provision(purged) -> None:
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)


def _backup_database(purged):
    return purged.database(role=_ROLE, password=_PASSWORD)


def _gaps(purged) -> list[str]:
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        return backup_role_gaps(connection, _ROLE)


def _counts(purged) -> dict[str, int]:
    tables = [
        row["tablename"]
        for row in purged.rows(
            "select tablename from pg_tables where schemaname=%s", purged.scratch
        )
    ]
    return {
        table: purged.rows(f'select count(*) as n from "{purged.scratch}"."{table}"')[0]["n"]
        for table in sorted(tables)
    }


def test_the_role_is_exactly_what_the_contract_says(purged):
    _provision(purged)
    role = purged.rows(
        "select rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolinherit, rolbypassrls, "
        "rolcanlogin, rolconfig from pg_roles where rolname=%s",
        _ROLE,
    )[0]
    assert role["rolbypassrls"] and role["rolcanlogin"]
    assert not any(
        role[flag]
        for flag in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolinherit")
    )
    assert "default_transaction_read_only=on" in role["rolconfig"]
    # A membership granted by hand does not survive the next deployment.
    with purged.database().unscoped() as connection:
        connection.execute(sql.SQL("grant pg_write_all_data to {}").format(sql.Identifier(_ROLE)))
    _provision(purged)
    held = purged.rows(
        "select 1 from pg_auth_members m join pg_roles r on r.oid=m.member where r.rolname=%s",
        _ROLE,
    )
    assert held == []


def test_it_reads_every_table_and_a_new_ungranted_table_is_named(purged):
    _provision(purged)
    assert _gaps(purged) == []
    tables = purged.rows(
        "select count(*) as n from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname=%s and c.relkind in ('r','p')",
        purged.scratch,
    )[0]["n"]
    assert tables > 100
    added = f'"{purged.scratch}".added_after_provisioning'
    with purged.database().unscoped() as connection:
        connection.execute(f"create table {added} (x int)")
    # A table the provisioning owner creates is readable by default privilege; one without the
    # grant, as one another role created would be, is named.
    assert _gaps(purged) == []
    with purged.database().unscoped() as connection:
        connection.execute(f'revoke select on {added} from "{_ROLE}"')
    try:
        _refuses_the_added_table(purged)
    finally:
        # The schema is the session's: a table left here is one every later test would see.
        with purged.database().unscoped() as connection:
            connection.execute(f"drop table {added}")
    assert _gaps(purged) == []


def _refuses_the_added_table(purged) -> None:
    assert _gaps(purged) == ["added_after_provisioning"]
    # And a dump that reached it anyway fails loudly rather than leaving it out.
    completed = subprocess.run(
        [
            _postgres_tool("pg_dump"),
            "--dbname",
            _backup_database(purged).url,
            "--schema",
            purged.scratch,
            "--no-owner",
            "--file",
            "/dev/null",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0 and "permission denied" in completed.stderr
    _provision(purged)
    assert _gaps(purged) == []


def test_a_column_or_sequence_write_grant_is_named(purged):
    _provision(purged)
    table = f'"{purged.scratch}".granted_a_column'
    sequence = f'"{purged.scratch}".granted_a_sequence'
    with purged.database().unscoped() as connection:
        connection.execute(f"create table {table} (x int)")
        connection.execute(f"create sequence {sequence}")
    try:
        assert _gaps(purged) == []
        with purged.database().unscoped() as connection:
            connection.execute(f'grant update (x) on {table} to "{_ROLE}"')
            connection.execute(f'grant usage on sequence {sequence} to "{_ROLE}"')
        assert sorted(_gaps(purged)) == ["granted_a_column", "granted_a_sequence"]
    finally:
        with purged.database().unscoped() as connection:
            connection.execute(f"drop table {table}")
            connection.execute(f"drop sequence {sequence}")
    assert _gaps(purged) == []


def test_a_large_object_is_reported(purged):
    _provision(purged)
    oid = purged.rows("select lo_from_bytea(0, 'x'::bytea) as oid")[0]["oid"]
    try:
        assert _gaps(purged) == ["large objects"]
    finally:
        purged.rows("select lo_unlink(%s) as done", oid)
    assert _gaps(purged) == []


def test_a_new_workspace_partition_is_readable_when_it_is_made(purged, monkeypatch):
    _provision(purged)
    # This test's role stands in for the deployment's, whose name is a cluster object.
    monkeypatch.setattr("exulanica.db.roles.BACKUP_ROLE", _ROLE)
    workspace = uuid.uuid4()
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_workspace(connection, workspace)
    assert f"embedding_ws_{workspace.hex}" in {
        row["tablename"]
        for row in purged.rows(
            "select tablename from pg_tables where schemaname=%s", purged.scratch
        )
    }
    assert _gaps(purged) == []


def test_it_writes_nothing_even_when_it_asks_to(purged):
    _provision(purged)
    with _backup_database(purged).session(purged.workspace_id) as connection:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by) values (%s,'workspace',%s)",
                (purged.workspace_id, uuid.uuid4()),
            )
        connection.execute("set default_transaction_read_only = off")
        for statement in (
            "insert into tombstone(workspace_id,scope,requested_by) "
            f"values ('{purged.workspace_id}','workspace','{uuid.uuid4()}')",
            "update restore_control set state='sealed'",
            "delete from capture",
            "truncate purge_job",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)


def test_it_cannot_execute_any_security_definer_function(purged):
    _provision(purged)
    definers = purged.rows(
        "select p.oid::regprocedure::text as name, has_function_privilege(%s, p.oid, 'EXECUTE') "
        "as allowed from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
        "where n.nspname=%s and p.prosecdef order by 1",
        _ROLE,
        purged.scratch,
    )
    assert definers, "the schema defines SECURITY DEFINER functions"
    assert [row["name"] for row in definers if row["allowed"]] == []


def test_a_dump_taken_as_the_role_restores_to_identical_counts(purged, tmp_path):
    _provision(purged)
    purged.tombstone_the_capture(_capture(purged))
    before = _counts(purged)
    dump = tmp_path / "as-backup-role.sql"
    completed = subprocess.run(
        [
            _postgres_tool("pg_dump"),
            "--dbname",
            _backup_database(purged).url,
            "--schema",
            purged.scratch,
            "--no-owner",
            "--file",
            str(dump),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    blobs = tmp_path / "blobs-at-backup"
    shutil.copytree(purged.store.root, blobs)
    _restore(purged, dump, blobs)
    assert _counts(purged) == before


def test_an_export_as_the_role_equals_the_checkpoint_record(purged, tmp_path):
    import json

    _provision(purged)
    purged.tombstone_the_capture(_capture(purged))
    export, _ = export_withdrawals(
        _backup_database(purged),
        tmp_path / "custody",
        restore_state_path=None,
        backup_domains=(purged.store.root,),
    )
    sealed = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), sealed)
    exported = json.loads(export.read_bytes())["record"]
    record = json.loads(sealed.read_bytes())["record"]
    for key in ("tombstones", "withdrawals", "withdrawal_catalog"):
        assert exported[key] == record[key], key
    assert exported["tombstones"]
