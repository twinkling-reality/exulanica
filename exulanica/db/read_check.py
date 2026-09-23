"""The final read check: whether something may be read or sent, decided once, at one instant.

Every path that hands something over (an asset's bytes, a photograph to a model, photographs to a
trainer, a trained artefact, a place's name) asks its question again at the last moment, inside
:func:`final_read_check`, and hands over only after the check has ended. The check is five steps on
the caller's connection, in this order, and each one is load-bearing:

1. **An idle connection, or a refusal.** The lock below is transaction-scoped. Taken inside a
   caller's open transaction it would be held until that transaction ends, across whatever the
   caller does next, the hand-over included. :class:`ConnectionNotIdle` is raised before anything
   is sent.
2. **A read-only transaction.** The check decides and writes nothing.
3. **The global asset read lock**, ``asset_read_lock()`` from migration 0041, exclusive and waited
   for. Every guarded write takes the same lock shared and without waiting, so a write already in
   flight is waited for and a write that begins while the check holds the lock is refused with
   40001 rather than committing unseen. The check takes no other lock, before or under this one:
   a writer may hold training, privacy or purge locks when it reaches the barrier, and a reader
   that waited on one of those while holding this lock would stop every guarded write in the
   database. Why the barrier is global rather than per workspace is stated in
   ``docs/asset-read-currency.md``.
4. **One evaluation instant**, read in its own statement after the lock. Under READ COMMITTED each
   statement sees what committed before it began, so the instant, and every read made at it, sees
   each write the check waited for.
5. **Release before anything leaves.** The transaction commits when the block ends, which releases
   the lock, and the caller hands over afterwards: a model call can take minutes and holds nothing.

A busy lock is waited for. A caller that will not wait passes ``wait=False`` or sets the session's
``lock_timeout``; either way a busy lock is refused with :class:`AssetReadLockBusy`, the read-only
transaction is rolled back, and nothing has been read.

``tests/test_final_read_check.py`` refuses a module that takes the lock inside a read-only
transaction by hand, and lists the modules that take it inside a writer's own transaction instead.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import psycopg
from psycopg.pq import TransactionStatus

__all__ = ["AssetReadLockBusy", "ConnectionNotIdle", "final_read_check"]

#: How a check that will not wait says so, for its own transaction only. PostgreSQL states
#: ``lock_timeout`` in whole milliseconds and reads zero as "wait for ever", so one millisecond is
#: the shortest wait it can be told. It holds until the check's transaction ends, so such a check
#: waits for no lock at all, the asset read lock included.
_WILL_NOT_WAIT: Final = "set local lock_timeout = '1ms'"


class ConnectionNotIdle(ValueError):
    """The connection is already inside a transaction, so the lock would outlive the check.

    A :class:`ValueError`, as this refusal has always been, carrying the caller's own sentence.
    """


class AssetReadLockBusy(psycopg.errors.LockNotAvailable):
    """The asset read lock was busy and the caller did not wait for it. Nothing was read.

    A :class:`~psycopg.errors.LockNotAvailable`, which is what a session ``lock_timeout`` raises
    here without this class, so a caller catching that catches this.
    """


@contextmanager
def final_read_check(
    connection: psycopg.Connection, *, not_idle: str, wait: bool = True
) -> Iterator[dt.datetime]:
    """Hold the global asset read lock in a read-only transaction; yield the evaluation instant.

    Read everything the decision needs inside the block, at the instant it yields, and nothing
    from the object store. Hand over only after the block has ended. ``not_idle`` is the sentence
    :class:`ConnectionNotIdle` carries, naming what the caller authorizes. ``wait=False`` refuses a
    busy lock with :class:`AssetReadLockBusy` instead of waiting for it. The connection returns
    rows by column name, as every connection the product opens does.
    """
    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise ConnectionNotIdle(not_idle)
    with connection.transaction():
        connection.execute("set transaction read only")
        if not wait:
            connection.execute(_WILL_NOT_WAIT)
        try:
            connection.execute("select asset_read_lock()")
        except psycopg.errors.LockNotAvailable as busy:
            raise AssetReadLockBusy(
                "the asset read lock is busy and this check does not wait for it"
            ) from busy
        yield connection.execute("select statement_timestamp() as at").fetchone()["at"]
