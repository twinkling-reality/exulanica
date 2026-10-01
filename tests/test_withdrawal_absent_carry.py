"""A withdrawal whose end the installation makes again after a restore is carried when absent.

The character catalogs job publishes from the image on every start, so a catalog withdrawn after
the backup would be published and served again: its catalog entry says ``"absent": "carry"``, and
replay writes the withdrawal row whether or not the backup holds the publication. These tests use
a fixture pair of tables in the shared test schema, so they hold for any kind that declares it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import pytest
from exulanica.deletion import withdrawals
from exulanica.deletion.withdrawals import (
    Carried,
    Condition,
    Ends,
    WithdrawalKind,
    open_withdrawals,
    reapply,
)
from exulanica.orchestration.restore import WRITERS

from test_purge import purged as purged

_KIND = WithdrawalKind(
    kind="fixture_carried",
    table="fixture_withdrawal",
    shape="event",
    identity=("digest",),
    columns=(),
    withdrawn=Condition(column="withdrawn_at", is_="not null"),
    carried_when=(),
    workspace=None,
    ends=Ends("fixture_publication", ("digest",)),
    order=None,
    carry_absent=True,
)
_ROW = {"digest": "ab" * 32, "withdrawn_at": "2026-10-01T12:00:00+00:00"}


@pytest.fixture
def fixture_tables(purged, monkeypatch):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        connection.execute("create table fixture_publication (digest text primary key)")
        connection.execute(
            "create table fixture_withdrawal (digest text primary key, "
            "withdrawn_at timestamptz not null)"
        )
    monkeypatch.setitem(withdrawals._BY_KIND, _KIND.kind, _KIND)
    try:
        yield purged
    finally:
        # The schema is the session's: a table left here is one every later test would see.
        with purged.database().unscoped() as connection:
            connection.execute(f'set search_path to "{purged.scratch}", public')
            connection.execute("drop table fixture_withdrawal, fixture_publication")


def _with(purged, action):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        return action(connection)


def test_the_catalog_allows_carry_only_for_an_event_kind_ending_another_table(tmp_path):
    document = json.loads(withdrawals.CATALOG_PATH.read_text(encoding="utf-8"))
    column = next(entry for entry in document["kinds"] if entry["shape"] == "column")
    for entry, wrong in ((column, "carry"), (document["kinds"][0], "write")):
        changed = json.loads(json.dumps(document))
        target = next(e for e in changed["kinds"] if e["kind"] == entry["kind"])
        target["absent"] = wrong
        path = tmp_path / f"{entry['kind']}-{wrong}.json"
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match=r"absent|carries"):
            withdrawals._load(path)


def test_an_absent_end_is_carried_and_then_honoured(fixture_tables):
    carried = Carried(_KIND.kind, dict(_ROW))
    # Before replay the row is missing: open, whatever the end.
    assert _with(fixture_tables, lambda c: open_withdrawals(c, [carried])) == [
        (_KIND.kind, carried.row)
    ]
    assert _with(fixture_tables, lambda c: reapply(c, carried, WRITERS)) == "carried"
    held = _with(
        fixture_tables,
        lambda c: c.execute("select digest, withdrawn_at from fixture_withdrawal").fetchall(),
    )
    assert [(row["digest"], row["withdrawn_at"]) for row in held] == [
        (_ROW["digest"], dt.datetime.fromisoformat(_ROW["withdrawn_at"]))
    ]
    assert _with(fixture_tables, lambda c: open_withdrawals(c, [carried])) == []
    # The installation publishes the same end again afterwards: the withdrawal stands.
    _with(
        fixture_tables,
        lambda c: c.execute("insert into fixture_publication values (%s)", (_ROW["digest"],)),
    )
    assert _with(fixture_tables, lambda c: open_withdrawals(c, [carried])) == []
    assert _with(fixture_tables, lambda c: reapply(c, carried, WRITERS)) == "present"


def test_without_carry_an_absent_end_writes_nothing(fixture_tables, monkeypatch):
    plain = dataclasses.replace(_KIND, carry_absent=False)
    monkeypatch.setitem(withdrawals._BY_KIND, plain.kind, plain)
    carried = Carried(plain.kind, dict(_ROW))
    assert _with(fixture_tables, lambda c: reapply(c, carried, WRITERS)) == "absent"
    assert _with(fixture_tables, lambda c: open_withdrawals(c, [carried])) == []
    count = _with(
        fixture_tables,
        lambda c: c.execute("select count(*) as n from fixture_withdrawal").fetchone()["n"],
    )
    assert count == 0
