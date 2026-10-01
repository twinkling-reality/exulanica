"""Migration 0129 adds a declared recovery's window to the restore receipt and changes no receipt.

A receipt certifies a restore that already happened, so the migration that widens the table must
leave every existing receipt exactly as it was, with its new columns null, and a receipt that
states a window must state all of it.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.env import env_get
from exulanica.migrations import migrations

from pg_harness import ensure_extensions, require_target

_VERSION = "0129"


@pytest.fixture
def before_0129():
    url = env_get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("needs a scratch PostgreSQL")
    scratch = f"exulanica_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url) as connection:
        require_target(connection)
        ensure_extensions(connection)
        cursor = connection.cursor()
        cursor.execute(f'create schema "{scratch}"')
        cursor.execute(f'set search_path to "{scratch}", public')
        later = [migration for migration in migrations() if migration.version >= _VERSION]
        assert [migration.version for migration in later][:1] == [_VERSION]
        for migration in migrations():
            if migration.version < _VERSION:
                cursor.execute(migration.sql)
        try:
            yield connection, later[0]
        finally:
            connection.rollback()
            connection.execute(f'drop schema "{scratch}" cascade')
            connection.commit()


def test_existing_receipts_are_untouched_and_a_window_is_whole(before_0129):
    connection, migration = before_0129
    restore_id, checkpoint_id = uuid.uuid4(), uuid.uuid4()
    connection.execute(
        "insert into restore_replay_receipt "
        "(restore_id,checkpoint_id,checkpoint_sha256,tombstone_count) values (%s,%s,%s,3)",
        (restore_id, checkpoint_id, "a" * 64),
    )
    connection.commit()
    before = connection.execute(
        "select restore_id,checkpoint_id,checkpoint_sha256,tombstone_count,completed_at "
        "from restore_replay_receipt"
    ).fetchall()
    connection.cursor().execute(migration.sql)
    after = connection.execute(
        "select restore_id,checkpoint_id,checkpoint_sha256,tombstone_count,completed_at,"
        "recovery_mode,covered_through,incident_at,loss_window_microseconds,"
        "max_export_lag_microseconds from restore_replay_receipt"
    ).fetchall()
    assert [row[:5] for row in after] == before
    assert after[0][5:] == (None, None, None, None, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "insert into restore_replay_receipt (restore_id,checkpoint_id,checkpoint_sha256,"
            "tombstone_count,recovery_mode) values (%s,%s,%s,0,'declared')",
            (uuid.uuid4(), uuid.uuid4(), "b" * 64),
        )
    connection.rollback()
    columns = (
        "recovery_mode",
        "covered_through",
        "incident_at",
        "loss_window_microseconds",
        "max_export_lag_microseconds",
    )
    whole = ("declared", "2026-09-30T12:00:00Z", "2026-09-30T12:00:30Z", 30_000_000, 600_000_000)
    half_stated = [
        # Each shape a check whose terms can be null would pass.
        dict(zip(columns, whole, strict=True)) | {"incident_at": None},
        dict(zip(columns, whole, strict=True)) | {"max_export_lag_microseconds": None},
        dict(zip(columns, whole, strict=True)) | {"recovery_mode": None},
        dict(zip(columns, whole, strict=True)) | {"incident_at": "2026-09-30T11:59:59Z"},
        # A window that is not incident_at minus covered_through, within the bound.
        dict(zip(columns, whole, strict=True)) | {"loss_window_microseconds": 1},
    ]
    for values in half_stated:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into restore_replay_receipt (restore_id,checkpoint_id,checkpoint_sha256,"
                "tombstone_count," + ",".join(columns) + ") values (%s,%s,%s,0,%s,%s,%s,%s,%s)",
                (uuid.uuid4(), uuid.uuid4(), "c" * 64, *(values[c] for c in columns)),
            )
        connection.rollback()
    connection.execute(
        "insert into restore_replay_receipt (restore_id,checkpoint_id,checkpoint_sha256,"
        "tombstone_count," + ",".join(columns) + ") values (%s,%s,%s,0,%s,%s,%s,%s,%s)",
        (uuid.uuid4(), uuid.uuid4(), "d" * 64, *whole),
    )
    connection.rollback()
