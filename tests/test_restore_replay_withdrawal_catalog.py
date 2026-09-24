"""The withdrawal catalog a restore carries, held to the schema it describes.

``exulanica/deletion/withdrawals.v1.json`` names every withdrawal outside the tombstone table and
how a restore writes each again. These tests ask the migrated schema, not a list: every table or
column shaped like a withdrawal is either carried or excluded by name with a reason; migration
0107's seal guards exactly the catalog's tables; every kind is stated in the schema's own terms;
and every kind's statements run against it. The real restores are in
``tests/test_restore_replay_withdrawals.py``; the branches of a single write are held here.
"""

from __future__ import annotations

import re
import uuid

import pytest
from exulanica.deletion.withdrawals import (
    CATALOG,
    EXCLUSIONS,
    Carried,
    CarryRefused,
    read_withdrawals,
    reapply,
    stale_withdrawals,
)
from exulanica.ingest.person_review import create_subject, record_consent
from exulanica.models.manifest import Role

from test_purge import purged as purged
from test_search_entries_on_stop import ACCOUNT, _stop
from test_search_entries_on_stop import indexed as indexed

pytestmark = pytest.mark.postgres

#: A column named for a withdrawal: a person or the product ended the row it is on.
WITHDRAWAL_COLUMN = r"^(withdrawn|revoked|disabled|redacted|retracted)_(at|by)$"
#: A value naming a withdrawal, in a CHECK constraint or an enum label.
WITHDRAWAL_VALUE = r"(withdraw|revok|retract)"

_TABLES = {kind.table for kind in CATALOG}
_EXCLUDED = {exclusion.table for exclusion in EXCLUSIONS}


def _rows(connection, statement, *params):
    return connection.execute(statement, params).fetchall()


#: The schema's own tables: every base or partitioned table in it, and no partition of one.
_BASE_TABLES = (
    "select c.oid from pg_class c where c.relnamespace=%(schema)s::regnamespace "
    "and c.relkind in ('r','p') and not c.relispartition"
)


def _withdrawal_shaped(connection, schema) -> dict[str, set[str]]:
    """Every table the schema shapes like a withdrawal, and the columns that shape it.

    A column named for one; a CHECK admitting a value that names one; a column whose enum has a
    label that names one; a table named for one.
    """
    found: dict[str, set[str]] = {}
    shaped = {
        "column": (
            "select a.attrelid::regclass::text as t, a.attname as c from pg_attribute a "
            f"where a.attrelid in ({_BASE_TABLES}) and a.attnum > 0 and not a.attisdropped "
            "and a.attname ~ %(column)s"
        ),
        "check": (
            "select c.conrelid::regclass::text as t, null as c from pg_constraint c "
            f"where c.conrelid in ({_BASE_TABLES}) and c.contype = 'c' "
            "and pg_get_constraintdef(c.oid) ~* ('''[a-z_]*' || %(value)s || '[a-z_]*''')"
        ),
        "enum": (
            "select a.attrelid::regclass::text as t, a.attname as c from pg_attribute a "
            "join pg_enum e on e.enumtypid = a.atttypid "
            f"where a.attrelid in ({_BASE_TABLES}) and a.attnum > 0 and not a.attisdropped "
            "and e.enumlabel ~* %(value)s"
        ),
        "name": (
            "select c.oid::regclass::text as t, null as c from pg_class c "
            f"where c.oid in ({_BASE_TABLES}) and c.relname ~ 'withdrawal'"
        ),
    }
    parameters = {"schema": schema, "column": WITHDRAWAL_COLUMN, "value": WITHDRAWAL_VALUE}
    for statement in shaped.values():
        for row in connection.execute(statement, parameters).fetchall():
            columns = found.setdefault(row["t"].split(".")[-1], set())
            if row["c"] is not None:
                columns.add(row["c"])
    return found


def test_every_withdrawal_shaped_table_is_carried_or_excluded_by_name(repository, spine_schema):
    _, schema = spine_schema
    found = _withdrawal_shaped(repository.connection, schema)
    assert found, "the positive control: the schema has withdrawals to find"
    assert {"personal_model_right", "place_name_right_event", "retraction"} <= set(found)
    uncovered = sorted(set(found) - _TABLES - _EXCLUDED)
    assert uncovered == [], (
        f"carry these in withdrawals.v1.json or exclude them by name: {uncovered}"
    )
    for kind in CATALOG:
        if kind.shape == "event":
            continue  # an event kind carries its whole row
        named = {*kind.columns, kind.withdrawn.column, *(c.column for c in kind.carried_when)}
        assert found.get(kind.table, set()) <= named, (kind.kind, found.get(kind.table))
    tables = {
        row["relname"]
        for row in _rows(
            repository.connection,
            "select relname from pg_class "
            "where relnamespace=%s::regnamespace and relkind in ('r','p')",
            schema,
        )
    }
    assert tables >= _TABLES | _EXCLUDED, "every name in the catalog is a table"
    assert _TABLES.isdisjoint(_EXCLUDED)


def test_the_seal_guards_exactly_the_tables_the_catalog_names(repository, spine_schema):
    _, schema = spine_schema
    guarded = {
        row["t"].split(".")[-1]: row["definition"]
        for row in _rows(
            repository.connection,
            "select tgrelid::regclass::text as t, pg_get_triggerdef(oid) as definition "
            "from pg_trigger where tgname = 'tg_sealed_checkpoint_refuses_withdrawals' "
            "and tgrelid in (select oid from pg_class where relnamespace=%s::regnamespace)",
            schema,
        )
    }
    assert set(guarded) == _TABLES
    # Its owner's rights, because the account role that writes sessions cannot read
    # restore_control; so its path is pinned and nobody may call it outside a trigger.
    [function] = _rows(
        repository.connection,
        "select p.prosecdef as definer, p.proconfig as config, exists (select 1 from "
        "aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a where a.grantee = 0 "
        "and a.privilege_type = 'EXECUTE') as public_may_call from pg_proc p "
        "where p.proname = 'tg_sealed_checkpoint_refuses_withdrawals' "
        "and p.pronamespace = %s::regnamespace",
        schema,
    )
    assert function["definer"] and not function["public_may_call"], function
    assert any(str(item).startswith("search_path=") for item in function["config"]), function
    for kind in CATALOG:
        definition = guarded[kind.table]
        if kind.shape == "event":
            assert re.search(r"\bBEFORE INSERT ON\b", definition), definition
        else:
            columns = re.search(r"BEFORE UPDATE OF (.+?) ON", definition)
            assert columns, definition
            assert {c.strip() for c in columns.group(1).split(",")} == set(kind.columns)


def test_every_kind_is_stated_in_the_schemas_own_terms(repository, spine_schema):
    _, schema = spine_schema
    connection = repository.connection
    columns = {
        (row["t"], row["c"]): row["type"]
        for row in _rows(
            connection,
            "select table_name as t, column_name as c, udt_name as type "
            "from information_schema.columns where table_schema=%s",
            schema,
        )
    }
    unique = {
        (row["t"], tuple(sorted(row["columns"])))
        for row in _rows(
            connection,
            "select i.indrelid::regclass::text as t, array_agg(a.attname::text) as columns "
            "from pg_index i join pg_attribute a "
            "on a.attrelid=i.indrelid and a.attnum=any(i.indkey) "
            "where i.indisunique and i.indrelid in "
            "(select oid from pg_class where relnamespace=%s::regnamespace) "
            "group by i.indexrelid, i.indrelid",
            schema,
        )
    }
    unique = {(table.split(".")[-1], key) for table, key in unique}
    for kind in CATALOG:
        named = [
            *kind.identity,
            *kind.columns,
            kind.withdrawn.column,
            *(c.column for c in kind.carried_when),
            *((kind.order,) if kind.order else ()),
        ]
        missing = [c for c in named if (kind.table, c) not in columns]
        assert missing == [], (kind.kind, missing)
        assert (kind.table, tuple(sorted(kind.identity))) in unique, (kind.kind, kind.identity)
        if kind.ends is not None:
            assert all((kind.ends.table, c) in columns for c in kind.ends.columns), kind.kind
            assert all((kind.table, c) in columns for c in kind.ends.columns), kind.kind
        for condition in (kind.withdrawn, *kind.carried_when):
            for value in condition.in_ or ():
                admitted = _rows(
                    connection,
                    "select exists (select 1 from pg_constraint c where c.conrelid=%s::regclass "
                    "and pg_get_constraintdef(c.oid) like %s) or exists (select 1 from pg_enum e "
                    "join pg_attribute a on a.atttypid=e.enumtypid where a.attrelid=%s::regclass "
                    "and a.attname=%s and e.enumlabel=%s) as admitted",
                    kind.table,
                    f"%'{value}'%",
                    kind.table,
                    condition.column,
                    value,
                )[0]["admitted"]
                assert admitted, (kind.kind, condition.column, value)


#: A value of each column type, for a row whose identity nobody holds.
_SYNTHETIC = {
    "uuid": lambda: str(uuid.uuid4()),
    "text": lambda: "held by nobody",
    "bytea": lambda: "\\x00",
    "int4": lambda: 0,
    "int8": lambda: 0,
    "timestamptz": lambda: "2000-01-01T00:00:00+00:00",
    "jsonb": lambda: {},
    "bool": lambda: False,
}


def test_every_kinds_statements_run_against_the_schema(repository, spine_schema):
    _, schema = spine_schema
    connection = repository.connection
    types = {
        (row["t"], row["c"]): (row["type"], row["kind"])
        for row in _rows(
            connection,
            "select c.table_name as t, c.column_name as c, c.udt_name as type, "
            "ty.typtype as kind from information_schema.columns c join pg_type ty "
            "on ty.typname=c.udt_name where c.table_schema=%s",
            schema,
        )
    }
    assert read_withdrawals(connection) == []
    assert stale_withdrawals(connection, []) == []
    for kind in CATALOG:
        row = {}
        for (table, column), (type_name, type_kind) in types.items():
            if table != kind.table:
                continue
            if type_kind == "e":
                row[column] = _rows(
                    connection,
                    "select enumlabel from pg_enum where enumtypid=%s::regtype "
                    "order by enumsortorder limit 1",
                    type_name,
                )[0]["enumlabel"]
            elif type_name in _SYNTHETIC:
                row[column] = _SYNTHETIC[type_name]()
        with connection.transaction(force_rollback=True):
            assert reapply(connection, Carried(kind.kind, row)) == "absent", kind.kind


# -- one write's branches ---------------------------------------------------------------------


def _right_row(fixture, right_id) -> dict:
    [row] = fixture.rows(
        "select workspace_id, right_id, withdrawn_at, withdrawn_by from personal_model_right "
        "where right_id=%s",
        right_id,
    )
    return {key: str(value) for key, value in row.items()}


def test_a_column_write_that_finds_another_withdrawal_than_the_checkpoints_refuses(indexed):
    fixture = indexed.fixture
    [right] = indexed.rights[Role.VISION][:1]
    _stop(fixture, right.right_id)
    held = _right_row(fixture, right.right_id)
    connection = fixture.repository.connection

    assert reapply(connection, Carried("model_right", held)) == "present"
    with pytest.raises(CarryRefused, match="another withdrawal than the checkpoint records"):
        reapply(
            connection, Carried("model_right", {**held, "withdrawn_at": "2099-01-01T00:00:00Z"})
        )


def test_an_event_write_finds_it_present_differing_already_ended_or_absent(purged):
    connection = purged.repository.connection
    subject = create_subject(purged.repository, actor=ACCOUNT)
    for decision in ("granted", "withdrawn"):
        record_consent(
            purged.repository,
            subject_id=subject,
            actor=ACCOUNT,
            consent_scope="likeness",
            decision=decision,
        )
    [withdrawal] = purged.rows(
        "select to_jsonb(c) as row from person_presentation_consent c "
        "where subject_id=%s and decision='withdrawn'",
        subject,
    )
    row = withdrawal["row"]

    assert reapply(connection, Carried("presentation_consent", row)) == "present"
    with pytest.raises(CarryRefused, match="differs from the withdrawal the checkpoint records"):
        reapply(connection, Carried("presentation_consent", {**row, "actor_id": str(uuid.uuid4())}))
    later = {**row, "consent_id": str(uuid.uuid4()), "sequence": row["sequence"] + 2}
    assert reapply(connection, Carried("presentation_consent", later)) == "already"
    nobody = {**later, "subject_id": str(uuid.uuid4())}
    assert reapply(connection, Carried("presentation_consent", nobody)) == "absent"


def test_a_carried_withdrawal_of_a_kind_the_catalog_does_not_name_is_refused(purged):
    with pytest.raises(CarryRefused, match="unknown kind 'rumour'"):
        reapply(purged.repository.connection, Carried("rumour", {}))
