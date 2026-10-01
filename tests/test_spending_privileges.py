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
