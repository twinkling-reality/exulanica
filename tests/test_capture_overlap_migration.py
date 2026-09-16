"""Migration 0063, checked as a schema: row security, guard order, predicate shape, vocabulary.

``tests/test_place_recovery_state.py`` writes the offending rows as the runtime role and
requires refusals. This file reads the catalog and the migration text for the properties a
behavioural test cannot see from one row: that every new relation is under forced row security
with the workspace policy, that every guard asserts the workspace before it reads anything, that
the withdrawal predicate takes a fresh snapshot, and that no column that reaches a digest can
hold a float.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest
from exulanica.capture.recovery import BASES, RECOVERY_STATES
from exulanica.capture.verdict import Fault, PredictedCeiling
from exulanica.migrations import migrations
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection

MIGRATION = next(m for m in migrations() if m.version == "0063").sql
TABLES = ("place_record", "place_record_member", "place_record_state_event")


def _function_bodies(sql: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"create (?:or replace )?function (\w+)\([^)]*\)\s*returns trigger\s*"
            r"language plpgsql as \$fn\$(.*?)\$fn\$;",
            sql,
            re.S,
        )
    }


def test_every_guard_asserts_the_workspace_before_it_reads_anything():
    """RLS fails open for a guard; the assertion fails closed, so it comes first."""
    bodies = _function_bodies(MIGRATION)
    assert set(bodies) == {
        "tg_place_record_guard",
        "tg_place_record_complete",
        "tg_place_record_member_live",
        "tg_place_record_state_event_guard",
        "tg_place_record_state_event_applies",
        "tg_place_record_append_only",
    }
    for name, body in bodies.items():
        statements = body.split("begin", 1)[1].strip()
        if name == "tg_place_record_append_only":
            # Reads nothing and raises unconditionally, so there is no lookup to protect.
            assert statements.startswith("raise exception")
            continue
        assert statements.startswith("perform assert_workspace_context(new.workspace_id);"), name


def test_the_withdrawal_predicate_is_sql_volatile_and_fails_closed_on_no_members():
    match = re.search(
        r"create or replace function tombstone_blocks_place_record\(p_workspace uuid, "
        r"p_record uuid\)\s*returns boolean\s*language sql volatile as \$fn\$(.*?)\$fn\$;",
        MIGRATION,
        re.S,
    )
    assert match is not None
    body = match.group(1)
    assert "not exists (select 1 from place_record_member m" in body
    assert "tombstone_blocks_capture(p_workspace, m.capture_id)" in body
    assert "person_withdrawal_blocks_capture(p_workspace, m.capture_id)" in body


@pytest.mark.postgres
def test_no_column_of_the_new_tables_can_hold_a_float(spine_schema):
    """Read from the catalog rather than the file, so prose cannot pass or fail it."""
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        types = connection.execute(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema = current_schema() and table_name = any(%s)",
            (list(TABLES),),
        ).fetchall()
    finally:
        connection.close()
    assert {table for table, _, _ in types} == set(TABLES)
    inexact = [row for row in types if row[2] in ("real", "double precision", "numeric")]
    assert inexact == []


def test_the_migration_names_the_same_vocabularies_as_the_package():
    states = ", ".join(f"'{state}'" for state in RECOVERY_STATES)
    flat = re.sub(r"\s+", " ", MIGRATION)
    assert flat.count(f"in ({states})") == 3
    bases = ", ".join(f"'{basis}'" for basis in BASES)
    assert f"check (basis in ({bases}))" in flat
    ceilings = ", ".join(f"'{value}'" for value in get_args(PredictedCeiling))
    assert f"check (predicted_ceiling in ({ceilings}))" in flat
    faults = ", ".join(f"'{value}'" for value in get_args(Fault))
    assert f"check (verdict_fault in ({faults}))" in flat


@pytest.mark.postgres
def test_every_new_relation_is_forced_under_the_workspace_policy(spine_schema):
    """Read from pg_class and pg_policies, partitions included, as 0048's test reads them."""
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    connection.row_factory = dict_row
    try:
        rows = connection.execute(
            """
            select c.relname, c.relkind, c.relispartition, c.relrowsecurity,
                   c.relforcerowsecurity,
                   array_agg(p.policyname order by p.policyname)
                     filter (where p.policyname is not null) as policies,
                   array_agg(p.qual) filter (where p.policyname is not null) as quals,
                   array_agg(p.with_check) filter (where p.policyname is not null) as checks,
                   array_agg(t.tgname order by t.tgname)
                     filter (where t.tgname is not null and not t.tgisinternal) as triggers
              from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
              left join pg_policies p on p.schemaname = n.nspname and p.tablename = c.relname
              left join pg_trigger t on t.tgrelid = c.oid
             where n.nspname = current_schema()
               and (c.relname = any(%s)
                    or c.oid in (select i.inhrelid from pg_inherits i
                                  join pg_class parent on parent.oid = i.inhparent
                                 where parent.relname = any(%s)))
             group by c.relname, c.relkind, c.relispartition, c.relrowsecurity,
                      c.relforcerowsecurity
             order by c.relname
            """,
            (list(TABLES), list(TABLES)),
        ).fetchall()
    finally:
        connection.close()
    assert [row["relname"] for row in rows] == sorted(TABLES), "no partition is expected"
    for row in rows:
        assert row["relkind"] == "r" and not row["relispartition"], row["relname"]
        assert row["relrowsecurity"] and row["relforcerowsecurity"], row["relname"]
        assert set(row["policies"]) == {"ws_isolation"}, row["relname"]
        assert {q.replace(" ", "") for q in row["quals"]} == {
            "(workspace_id=current_workspace())"
        }, row["relname"]
        assert {q.replace(" ", "") for q in row["checks"]} == {
            "(workspace_id=current_workspace())"
        }, row["relname"]
    triggers = {row["relname"]: set(row["triggers"]) for row in rows}
    assert "tg_place_record_no_delete" in triggers["place_record"]
    assert "tg_place_record_guard" in triggers["place_record"]
    assert "tg_place_record_complete" in triggers["place_record"]
    assert "tg_place_record_member_append_only" in triggers["place_record_member"]
    assert "tg_place_record_state_event_append_only" in triggers["place_record_state_event"]


@pytest.mark.postgres
def test_a_session_that_never_declared_a_workspace_writes_nothing(spine_schema):
    """The guard's assertion, on a connection with no workspace context at all."""
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
            connection.execute(
                "insert into place_record (workspace_id, member_digest, member_count) "
                "values (gen_random_uuid(), %s, 1)",
                (bytes(32),),
            )
    finally:
        connection.close()
