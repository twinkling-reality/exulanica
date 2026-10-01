"""Who may read and write migration 0124's spending tables, from the moment it is applied.

A provisioner's default privileges give the runtime INSERT and UPDATE on every table a later
migration creates, and the read-only role SELECT. With a write on a spending table the runtime
could put back an allowance it spent, so the migration takes those back itself rather than leaving
them until the next provisioning. An authority's committed total is every workspace's spending
together and the ledger's sequence counts every workspace's steps, so neither role reads the
authority tables or the ledger: a workspace learns an authority's state, and no amount, from
``spending_authority_facts``.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.roles import (
    SPENDING_ADMIN_TABLES,
    SPENDING_RUNTIME_FUNCTIONS,
    SPENDING_TABLES,
    provision_runtime_role,
)
from exulanica.migrations import migrations
from exulanica.spending.status import authority_states, workspace_status
from psycopg import sql
from psycopg.rows import dict_row

import pg_harness
from spending_support import MESSAGES, ROLE, WorkspacePolicy, bench, spending_client

__all__ = ["bench"]

pytestmark = pytest.mark.postgres

MIGRATION = next(migration for migration in migrations() if migration.version == "0124")


def _held(connection: psycopg.Connection, role: str, table: str) -> dict[str, bool]:
    row = connection.execute(
        "select has_table_privilege(%(role)s, %(table)s, 'SELECT') as select, "
        "has_table_privilege(%(role)s, %(table)s, 'INSERT') as insert, "
        "has_table_privilege(%(role)s, %(table)s, 'UPDATE') as update, "
        "has_table_privilege(%(role)s, %(table)s, 'DELETE') as delete",
        {"role": role, "table": table},
    ).fetchone()
    assert row is not None
    return dict(row)


def _executes(connection: psycopg.Connection, role: str, function: str) -> bool:
    row = connection.execute(
        "select has_function_privilege(%s, %s, 'EXECUTE') as ok", (role, function)
    ).fetchone()
    assert row is not None
    return bool(row["ok"])


def test_the_migration_takes_back_what_a_provisioner_granted_before_it(monkeypatch):
    everything = list(migrations())
    roles = {
        f"spending_app_{uuid.uuid4().hex[:12]}": False,
        f"spending_ro_{uuid.uuid4().hex[:12]}": True,
    }
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0124")
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            admin.row_factory = dict_row
            try:
                for role, read_only in roles.items():
                    provision_runtime_role(admin, role=role, read_only=read_only)
                admin.commit()
                admin.execute(MIGRATION.sql)
                for role in roles:
                    for table in (*SPENDING_TABLES, *SPENDING_ADMIN_TABLES):
                        held = _held(admin, role, table)
                        assert not (held["insert"] or held["update"] or held["delete"]), (
                            role,
                            table,
                            held,
                        )
                        if table in SPENDING_ADMIN_TABLES:
                            assert not held["select"], (role, table)
                # Provisioning again grants the reads it means and nothing more.
                for role, read_only in roles.items():
                    provision_runtime_role(admin, role=role, read_only=read_only)
                    for table in SPENDING_TABLES:
                        assert _held(admin, role, table) == {
                            "select": True,
                            "insert": False,
                            "update": False,
                            "delete": False,
                        }, (role, table)
                    for table in SPENDING_ADMIN_TABLES:
                        assert not any(_held(admin, role, table).values()), (role, table)
                    assert _executes(admin, role, "spending_authority_facts()")
                    for name, arguments in SPENDING_RUNTIME_FUNCTIONS:
                        assert _executes(admin, role, f"{name}({arguments})") is not read_only
            finally:
                admin.rollback()
                for role in roles:
                    if admin.execute(
                        "select 1 from pg_roles where rolname = %s", (role,)
                    ).fetchone():
                        admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                        admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
                admin.commit()


def test_the_runtime_reads_its_own_spending_and_no_authority_total_or_ledger(bench):
    authority = bench.issue()
    workspace = uuid.uuid4()
    bench.grant(authority, workspace)
    spending_client(bench.durable()).with_policy(WorkspacePolicy(workspace)).chat(
        ROLE, MESSAGES, prompt_version="spending-privileges", use_cache=False
    )
    for table in SPENDING_ADMIN_TABLES:
        with (
            bench.runtime.session(workspace) as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            connection.execute(sql.SQL("select * from {}").format(sql.Identifier(table)))
    with bench.runtime.session(workspace) as connection:
        facts = connection.execute("select * from spending_authority_facts()").fetchall()
    (fact,) = facts
    assert fact["authority_id"] == authority
    # What it states of an authority: its state, never an amount.
    assert set(fact) == {
        "authority_id",
        "provider",
        "witnessed",
        "epoch",
        "valid_until",
        "suspended_reason",
        "revoked",
        "exhausted",
        "created_at",
    }
    (entry,) = workspace_status(bench.runtime, workspace)["providers"]
    assert (entry["grant"]["state"], entry["authority_state"]) == ("active", "active")
    (state,) = authority_states(bench.runtime)
    assert (state["authority_id"], state["state"]) == (str(authority), "active")


MIGRATION_0133 = next(migration for migration in migrations() if migration.version == "0133")


def test_the_later_strip_takes_back_what_was_passed_on_and_maintain(monkeypatch):
    """Migration 0133 strips the spending tables again with CASCADE, so a write a grantee passed on
    with its grant option goes with it rather than failing the migration, and with MAINTAIN, which
    lets a holder lock the workspace tables."""
    everything = list(migrations())
    holder, passed, keeper = (
        f"spending_{kind}_{uuid.uuid4().hex[:10]}" for kind in ("h", "p", "k")
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < "0133")
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            admin.row_factory = dict_row
            scratch = admin.execute("select current_schema() as s").fetchone()["s"]
            try:
                for role in (holder, passed, keeper):
                    admin.execute(sql.SQL("create role {}").format(sql.Identifier(role)))
                    admin.execute(
                        sql.SQL("grant usage on schema {} to {}").format(
                            sql.Identifier(scratch), sql.Identifier(role)
                        )
                    )
                admin.execute(
                    sql.SQL("grant insert on spending_reservation to {} with grant option").format(
                        sql.Identifier(holder)
                    )
                )
                admin.execute(sql.SQL("set role {}").format(sql.Identifier(holder)))
                admin.execute(
                    sql.SQL("grant insert on spending_reservation to {}").format(
                        sql.Identifier(passed)
                    )
                )
                admin.execute("reset role")
                admin.execute(
                    sql.SQL("grant maintain on spending_reservation, spending_event to {}").format(
                        sql.Identifier(keeper)
                    )
                )
                admin.commit()
                admin.execute(MIGRATION_0133.sql)
                for role in (holder, passed, keeper):
                    for privilege in ("INSERT", "MAINTAIN"):
                        for table in ("spending_reservation", "spending_event"):
                            held = admin.execute(
                                "select has_table_privilege(%s, %s, %s) as held",
                                (role, table, privilege),
                            ).fetchone()["held"]
                            assert held is False, (role, table, privilege)
            finally:
                admin.rollback()
                for role in (passed, keeper, holder):
                    if admin.execute(
                        "select 1 from pg_roles where rolname = %s", (role,)
                    ).fetchone():
                        admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                        admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
                admin.commit()
