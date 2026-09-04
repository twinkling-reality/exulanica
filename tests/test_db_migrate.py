"""Applying migrations to a real server, which is what every process does at startup.

``tests/pg_harness.py`` applies the files directly, because what it needs is a schema. This
covers the other path, :func:`exulanica.db.apply_pending`, which is the one the command line and
anything else with a ``Database`` actually calls, and which additionally has to decide what is
already applied and record what it applied.

The distinction matters in one specific way that has already bitten: a fully migrated schema
whose ``schema_migrations`` table is empty is indistinguishable, to this function, from an empty
database, so it tries 0001 again and dies on ``type "assertion_kind" already exists``. That is
the correct direction to fail in, and it is why the CLI fixture in ``conftest.py`` records what
the harness applied rather than letting the two disagree.
"""

from __future__ import annotations

import urllib.parse
import uuid

import psycopg
import pytest
from exulanica.db import Database, applied_migrations, apply_pending, verify_schema
from exulanica.db.roles import provision_runtime_role
from exulanica.env import env_get, env_name
from exulanica.migrations import migrations

pytestmark = pytest.mark.postgres


@pytest.fixture
def empty_schema():
    """A brand new, empty schema, and a ``Database`` whose connections land in it.

    Not the harness's migrated schema: the whole point here is to watch the migration run.
    """
    url = env_get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(f"set {env_name('TEST_DATABASE_URL')} to a scratch PostgreSQL database")
    name = f"exulanica_migrate_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f'create schema "{name}"')
        options = urllib.parse.quote(f"-csearch_path={name},public", safe="")
        scoped = f"{url}{'&' if '?' in url else '?'}options={options}"
        try:
            yield Database(url=scoped), name
        finally:
            admin.execute(f'drop schema "{name}" cascade')


def test_apply_pending_applies_every_migration_and_records_what_it_applied(empty_schema):
    database, _name = empty_schema
    report = apply_pending(database)

    assert report.applied == tuple(m.version for m in migrations())
    assert report.already_present == ()
    assert report.changed

    with database.unscoped() as connection:
        recorded = applied_migrations(connection)
        assert recorded == {m.version: m.checksum for m in migrations()}
        tables = connection.execute(
            "select count(*) as n from information_schema.tables where table_schema = "
            "current_schema()"
        ).fetchone()
        assert tables["n"] >= 30


def test_an_empty_schema_does_not_inherit_a_fallback_schema_migration_ledger():
    """Extension lookup may fall through the search path; the deployment ledger may not."""
    url = env_get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(f"set {env_name('TEST_DATABASE_URL')} to a scratch PostgreSQL database")
    suffix = uuid.uuid4().hex[:12]
    primary = f"exulanica_migrate_primary_{suffix}"
    fallback = f"exulanica_migrate_fallback_{suffix}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f'create schema "{primary}"')
        admin.execute(f'create schema "{fallback}"')
        admin.execute(
            f'create table "{fallback}".schema_migrations '
            "(version text primary key, checksum bytea not null)"
        )
        admin.execute(
            f'insert into "{fallback}".schema_migrations (version, checksum) '
            "values ('decoy', decode(repeat('00', 32), 'hex'))"
        )
        options = urllib.parse.quote(
            f"-csearch_path={primary},{fallback},public", safe=""
        )
        scoped = f"{url}{'&' if '?' in url else '?'}options={options}"
        try:
            with Database(url=scoped).unscoped() as connection:
                assert applied_migrations(connection) == {}
        finally:
            admin.execute(f'drop schema "{primary}" cascade')
            admin.execute(f'drop schema "{fallback}" cascade')


def test_a_second_apply_is_a_no_op_rather_than_an_error(empty_schema):
    """Startup runs this every time. A migration that reapplies itself is a crash loop."""
    database, _name = empty_schema
    apply_pending(database)
    second = apply_pending(database)

    assert second.applied == ()
    assert second.already_present == tuple(m.version for m in migrations())
    assert not second.changed


def test_a_migration_edited_after_it_was_applied_refuses_to_start(empty_schema):
    """The drift check. Two deployments claiming one version with different tables is a fault
    that surfaces as a wrong answer rather than as an error, so it is caught at boot."""
    database, _name = empty_schema
    apply_pending(database)
    verify_schema(database)  # clean

    with database.unscoped() as connection:
        connection.execute(
            "update schema_migrations set checksum = %s where version = '0001'", (b"\x00" * 32,)
        )
        connection.commit()
    with pytest.raises(RuntimeError, match="checksum drift"):
        verify_schema(database)
    with pytest.raises(RuntimeError, match="checksum drift"):
        apply_pending(database)


def test_verify_schema_is_satisfied_by_a_database_that_has_had_nothing_applied(empty_schema):
    """An empty database is pending, not drifted. Refusing it would make first boot impossible."""
    database, _name = empty_schema
    verify_schema(database)


@pytest.mark.parametrize("read_only", [False, True], ids=["writer", "executor"])
def test_provisioning_a_role_twice_is_a_no_op_and_strips_bypassrls(empty_schema, read_only):
    """Deployment calls this on every start, and an existing role may have been created by hand
    with BYPASSRLS, which would make every policy in the schema inert without any symptom.

    Under a throwaway role name rather than RUNTIME_ROLE or EXECUTOR_ROLE. Roles are
    cluster-global: granting BYPASSRLS to the real one, even for a moment, would disarm the
    isolation another test process is checking at that instant, and the failure would look like
    a defect in row-level security rather than in this test.
    """
    database, _name = empty_schema
    role = f"exulanica_probe_{uuid.uuid4().hex[:10]}"
    apply_pending(database)
    with database.unscoped() as connection:
        provision_runtime_role(connection, role=role, read_only=read_only)
        connection.execute(f'alter role "{role}" bypassrls')
        connection.commit()
        assert connection.execute(
            "select rolbypassrls from pg_roles where rolname = %s", (role,)
        ).fetchone()["rolbypassrls"]

        provision_runtime_role(connection, role=role, read_only=read_only)
        assert not connection.execute(
            "select rolbypassrls from pg_roles where rolname = %s", (role,)
        ).fetchone()["rolbypassrls"]
        connection.execute(f'drop owned by "{role}"')
        connection.execute(f'drop role "{role}"')
        connection.commit()
