"""Dedicated account grants do not inherit workspace, sequence or private function access."""

import uuid

import psycopg
import pytest
from exulanica.db.account_roles import (
    ACCOUNT_TABLES,
    AccountRoleUnsafe,
    assert_account_role,
    revoke_account_access,
)
from exulanica.db.roles import provision_runtime_role
from psycopg import sql
from psycopg.rows import dict_row

from account_fixtures import account_role as account_role

pytestmark = pytest.mark.postgres


def test_auth_role_is_narrow_and_non_owner(account_role):
    with psycopg.connect(account_role, row_factory=dict_row) as connection:
        assert_account_role(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("select * from capture")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "select caption_vector_purge_is_complete(%s,%s)", (uuid.uuid4(), uuid.uuid4())
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("select * from predicate_predicate_id_seq")


def test_app_and_read_grants_require_explicit_account_exclusion(repository):
    connection = repository.connection
    for readonly in (False, True):
        role = "account_excluded_" + uuid.uuid4().hex[:16]
        try:
            connection.execute("begin")
            provision_runtime_role(connection, role=role, read_only=readonly)
            assert not connection.execute(
                "select has_table_privilege(%s,'account_user','SELECT') ok", (role,)
            ).fetchone()["ok"]
            # Even a separately granted column must be removed, not hidden by table REVOKE.
            connection.execute(
                sql.SQL("grant select(actor_id) on account_user to {}").format(sql.Identifier(role))
            )
            revoke_account_access(connection, role=role)
            for table in ACCOUNT_TABLES:
                assert not connection.execute(
                    "select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE') ok",
                    (role, table),
                ).fetchone()["ok"]
                assert not connection.execute(
                    "select has_any_column_privilege(%s,%s,'SELECT,INSERT,UPDATE,REFERENCES') ok",
                    (role, table),
                ).fetchone()["ok"]
        finally:
            connection.rollback()


def test_role_checker_refuses_superuser_and_privilege_expansion(repository, account_role):
    from psycopg.conninfo import conninfo_to_dict

    role = conninfo_to_dict(account_role)["user"]
    admin = repository.connection
    with pytest.raises(AccountRoleUnsafe):
        assert_account_role(admin)
    for command in (
        sql.SQL("grant select on capture to {}").format(sql.Identifier(role)),
        sql.SQL("grant usage on sequence predicate_predicate_id_seq to {}").format(
            sql.Identifier(role)
        ),
        sql.SQL(
            "grant execute on function caption_vector_purge_is_complete(uuid,uuid) to {}"
        ).format(sql.Identifier(role)),
        sql.SQL("grant select on account_user to public"),
    ):
        try:
            admin.execute("begin")
            admin.execute(command)
            with pytest.raises(AccountRoleUnsafe):
                assert_account_role(admin, role=role)
        finally:
            admin.rollback()


def test_migration_strips_preexisting_default_grants(monkeypatch):
    from exulanica.migrations import migrations

    import pg_harness

    all_migrations = list(migrations())
    roles = ["accounts_upgrade_" + uuid.uuid4().hex[:12] for _ in range(2)]
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in all_migrations if m.version < "0058")
        )
        with pg_harness.migrated_schema() as (_, admin):
            admin.row_factory = dict_row
            try:
                for role, read_only in zip(roles, (False, True), strict=True):
                    provision_runtime_role(admin, role=role, read_only=read_only)
                    # The unconditional shared hook must also work before account tables exist.
                    revoke_account_access(admin, role=role)
                admin.commit()
                admin.execute(next(m.sql for m in all_migrations if m.version == "0058"))
                for role, read_only in zip(roles, (False, True), strict=True):
                    for table in ACCOUNT_TABLES:
                        assert not admin.execute(
                            "select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE') ok",
                            (role, table),
                        ).fetchone()["ok"]
                    # Reprovisioning the same role must not reopen account tables.
                    provision_runtime_role(admin, role=role, read_only=read_only)
                    for table in ACCOUNT_TABLES:
                        assert not admin.execute(
                            "select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE') ok",
                            (role, table),
                        ).fetchone()["ok"]
                    assert admin.execute(
                        "select has_function_privilege(%s,"
                        "'caption_vector_purge_is_complete(uuid,uuid)','EXECUTE') ok",
                        (role,),
                    ).fetchone()["ok"]
            finally:
                admin.rollback()
                for role in roles:
                    if admin.execute("select 1 from pg_roles where rolname=%s", (role,)).fetchone():
                        admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                        admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
                admin.commit()
