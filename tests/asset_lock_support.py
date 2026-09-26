"""Store reads made while a session holds the global asset read lock, recorded for a test.

A writer that takes the lock inside its transaction (``lock_asset_reads_until_commit``) holds it
until the commit and reads nothing from the object store until then, as a reader's final check
reads nothing while it holds the lock (``docs/asset-read-currency.md``). The recorder wraps a
store's reads and records each one made while ``pg_locks`` shows the lock held exclusively in the
test's own database, and, apart, each made while its shared side is held: a write to a table the
lock guards takes that side until its commit, and every exclusive request waits behind it. Every
test using it runs one request at a time against its own database server, so the holder is the
request under test. Whether the recorder sees a read under the lock
at all is :func:`planted_read_is_recorded`'s question, asked before an empty record is trusted.
"""

from __future__ import annotations

import re
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import exulanica
import psycopg
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.evidence.blob import BlobId

#: The store's reads. ``put`` writes, and a write is not what the rule is about.
READS = ("get", "open", "exists", "size")
#: Where a read the test itself made is said to come from.
FROM_THE_TEST = "the test"
#: The product package's own directory. A frame is the product's when its file is under it, whatever
#: the checkout is called: a checkout named ``exulanica`` puts every path under ``/exulanica/``.
_PACKAGE = Path(exulanica.__file__).resolve().parent


@dataclass
class StoreReads:
    """Each store read, as (method, the product functions that asked, innermost first): every
    one, and those made while the lock was held."""

    every: list[tuple[str, str]] = field(default_factory=list)
    under_the_lock: list[tuple[str, str]] = field(default_factory=list)
    #: Reads made while a transaction held the lock's shared side, the side a guarded write takes.
    while_shared: list[tuple[str, str]] = field(default_factory=list)


def _lock_key(connection) -> int:
    """The advisory key ``asset_read_lock()`` takes, read from the function (migration 0041)."""
    [source] = connection.execute(
        "select prosrc from pg_proc where proname = 'asset_read_lock' "
        "and pronamespace = current_schema()::regnamespace"
    ).fetchall()
    [key] = re.findall(r"pg_advisory_xact_lock\((\d+)\)", source["prosrc"])
    return int(key)


def _asked_by() -> str:
    """The product functions on the stack, innermost first, each as ``path:function``."""
    chain = [
        f"{path.relative_to(_PACKAGE).as_posix()}:{frame.name}"
        for frame in reversed(traceback.extract_stack()[:-2])
        if (path := Path(frame.filename).resolve()).is_relative_to(_PACKAGE)
    ]
    return " < ".join(chain) if chain else FROM_THE_TEST


def record_store_reads(connection, store, monkeypatch) -> StoreReads:
    """Wrap ``store``'s reads; ``connection`` is a session of the test's own, for ``pg_locks``."""
    key = _lock_key(connection)
    held = (
        "select count(*) filter (where mode = 'ExclusiveLock') as n,"
        "count(*) filter (where mode = 'ShareLock') as shared "
        "from pg_locks where locktype = 'advisory' and classid = 0 "
        "and objid = %s and objsubid = 1 and granted "
        "and database = (select oid from pg_database where datname = current_database())"
    )
    reads = StoreReads()
    for name in READS:
        original = getattr(store, name)

        def reading(blob_id, _name=name, _original=original):
            call = (_name, _asked_by())
            reads.every.append(call)
            holders = connection.execute(held, (key,)).fetchone()
            if holders["n"]:
                reads.under_the_lock.append(call)
            if holders["shared"]:
                reads.while_shared.append(call)
            return _original(blob_id)

        monkeypatch.setattr(store, name, reading)
    return reads


def planted_read_is_recorded(
    database, workspace_id: uuid.UUID, store, reads: StoreReads, digest: str
) -> None:
    """Positive control: a read made while a transaction holds the lock is recorded as under it,
    and the same read once that transaction has committed is not. The record starts empty after.
    """
    assert reads == StoreReads(), "the control runs before anything else is recorded"
    with database.session(workspace_id) as connection, connection.transaction():
        lock_asset_reads_until_commit(connection, outside="the planted read takes it in a write")
        store.exists(BlobId.from_hex(digest))
    assert reads.under_the_lock == [("exists", FROM_THE_TEST)], reads.under_the_lock
    store.exists(BlobId.from_hex(digest))
    assert reads.under_the_lock == [("exists", FROM_THE_TEST)], "after the commit is not under it"
    assert reads.every == [("exists", FROM_THE_TEST)] * 2
    assert reads.while_shared == []
    reads.every.clear()
    reads.under_the_lock.clear()


def planted_shared_read_is_recorded(
    database, workspace_id: uuid.UUID, store, reads: StoreReads, digest: str
) -> None:
    """Positive control for the shared side: a read made after a write to a guarded table (a
    ``place`` row, whose mutation guard takes the shared side) and before that write ends is
    recorded as made while the shared side is held. The write is rolled back; the record starts
    empty after."""
    assert reads == StoreReads(), "the control runs before anything else is recorded"
    with database.session(workspace_id) as connection, connection.transaction():
        connection.execute(
            "insert into place(workspace_id,place_id) values(%s,%s)", (workspace_id, uuid.uuid4())
        )
        store.exists(BlobId.from_hex(digest))
        raise psycopg.Rollback()
    assert reads.while_shared == [("exists", FROM_THE_TEST)], reads.while_shared
    assert reads.under_the_lock == []
    reads.every.clear()
    reads.while_shared.clear()


def recorded_store_reads(
    connection,
    database,
    workspace_id: uuid.UUID,
    store,
    monkeypatch,
    *,
    planted: str,
    shared: bool = False,
) -> StoreReads:
    """:func:`record_store_reads`, trusted only once the planted control on ``planted``, a digest
    the store holds, has shown a read under a held lock is recorded; with ``shared``, also once
    :func:`planted_shared_read_is_recorded` has shown the same for the shared side."""
    reads = record_store_reads(connection, store, monkeypatch)
    planted_read_is_recorded(database, workspace_id, store, reads, planted)
    if shared:
        planted_shared_read_is_recorded(database, workspace_id, store, reads, planted)
    return reads
