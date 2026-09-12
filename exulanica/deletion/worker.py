"""The worker that destroys bytes. The order it does things in is the whole of it.

Per job, and none of these may be reordered:

1.  **Take the advisory lock**, keyed on the target's content hash, so two purgers never work on
    one object. ``purge_lock_object`` raises rather than silently taking no lock, which is
    correction 1: the lock was absent on exactly the rows it was added for.
2.  **Ask whether the bytes may go**, inside the same transaction and after the lock, so the
    answer cannot go stale between asking and acting. ``purge_releases_bytes`` raises on a NULL
    hash rather than answering "yes", which is correction 2: it failed OPEN.
3.  **Destroy the object**, through the separately authorised purger, which cannot be
    constructed without naming the tombstone, the actor and the reason. Those come off the
    tombstone row.
4.  **Confirm it is gone**, by asking the store. A purge that reported success over an object
    still on disk is the one failure this whole package exists to prevent, and the store is the
    only thing that can answer.
5.  **Record it**, and only then. The store is not in the transaction, so a row marked purged
    before the object is destroyed lies when the process dies in between, and lies in the
    direction that stops anything trying again.

**A job whose bytes something still holds is ``skipped``, and skipped comes back.** That is
correction 3. It is not a failure: another live capture, in this workspace or another, is using
those exact bytes, and the right thing is to ask again later.

**What this can delete from the database.** The purge role has DELETE on ``embedding`` only.
Person withdrawal must remove the vector itself, and a soft marker would retain the sensitive
derivative. Stored objects still use the content-addressed purge path and keep their stub rows.

**The cross-workspace read is a privilege of the role, not of this code, and this asks.**
``provision_purge_role`` grants ``exulanica_purge`` a permissive SELECT policy on ``capture`` and
``artifact``, because ``blob`` is shared between workspaces and a purger that could only see its
own would destroy another tenant's photograph. ``EXULANICA_PURGE_DATABASE_URL`` is only a name, so
:func:`exulanica.deletion.queue.read_visibility` asks the database which role is connected and
whether that policy applies to it, and this refuses to destroy anything when it does not.
Measured with the writer's URL in that variable: one object destroyed, zero skipped, the
tombstone recorded complete, and another workspace's live photograph gone, with nothing in the
outcome naming the role or the narrowed view.

**The advisory lock is taken by BOTH sides, and only one of them used to take it.**
``purge_lock_object`` serialises purger against purger. It did not serialise a purger against an
ingest, and measured: workspace A's purger asks whether the bytes may go, workspace B commits a
live capture of the same bytes in the window, and the purger destroys an object B is using, along
the deduplication path where B writes no bytes at all because they were already there.
``IngestRepository.lock_stored_object`` is the other side.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Final

import psycopg

from exulanica.db.session import Database
from exulanica.deletion import queue
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore, PurgeAuthorization, privileged_purger

__all__ = ["PurgeOutcome", "PurgeWorker"]

#: How often an idle purger asks again. Deletion is not latency-sensitive: a tombstone is
#: authoritative from the moment it commits, every guard refuses on it immediately, and this is
#: only the bytes catching up.
_POLL_SECONDS: Final = 30.0


@dataclass
class PurgeOutcome:
    """What one pass destroyed, what it deferred, and what broke."""

    destroyed: int = 0
    already_absent: int = 0
    skipped: int = 0
    failed: int = 0
    completed_tombstones: list[uuid.UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: The role this pass connected as, read from the database rather than inferred from a
    #: connection string. Recorded on every outcome, because "which role destroyed these bytes"
    #: is the first question anybody asks afterwards.
    role: str | None = None
    #: Why this pass destroyed nothing, or None when it was allowed to. Set when the connected
    #: role cannot see the whole destroy question.
    blocked: str | None = None

    #: Jobs that have used every attempt and are no longer claimed. Counted rather than
    #: retried, so a permanently broken target is visible instead of hidden behind its own noise.
    exhausted: int = 0

    @property
    def handled(self) -> int:
        return self.destroyed + self.already_absent + self.skipped + self.failed


class PurgeWorker:
    """Drains ``purge_job`` for a fixed set of workspaces."""

    def __init__(
        self,
        database: Database,
        store: ContentAddressedStore,
        workspaces: frozenset[uuid.UUID],
        *,
        name: str = "purge",
        poll_seconds: float = _POLL_SECONDS,
        limit_per_pass: int = 500,
        require_cross_workspace_view: bool = True,
    ) -> None:
        self._database = database
        self._store = store
        self._workspaces = workspaces
        self._name = name
        self._poll_seconds = poll_seconds
        self._limit = limit_per_pass
        self._require_cross_workspace_view = require_cross_workspace_view
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._failed_passes = 0

    # -- driving it ---------------------------------------------------------------------

    def drain(self) -> PurgeOutcome:
        """Destroy everything claimable right now, then return.

        Bounded per pass, because a workspace tombstone enqueues one job per stored object and a
        loop with no bound is a pass that never ends and a stop that never takes effect. What is
        left is still queued and the next pass takes it.
        """
        outcome = PurgeOutcome()
        for workspace_id in sorted(self._workspaces):
            with self._database.session(workspace_id) as connection:
                visibility = queue.read_visibility(connection)
                outcome.role = visibility.role
                # **Asked, not assumed.** The connection string is a name; this is the database
                # saying which role is behind it and whether that role can see the whole of the
                # question. Refusing rather than warning, because a narrowed purge is silent:
                # measured, it destroys an object another workspace holds, records the tombstone
                # complete, and reports one success.
                if self._require_cross_workspace_view and visibility.refusal is not None:
                    outcome.blocked = visibility.refusal
                    return outcome
                while outcome.handled < self._limit and not self._stop.is_set():
                    if not self._purge_one(connection, workspace_id, outcome):
                        break
                outcome.exhausted += _exhausted(connection, workspace_id)
        return outcome

    def start(self) -> None:
        """Run the loop on a daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def _loop(self) -> None:
        """Poll until asked to stop, and survive anything one pass throws.

        The same guard the derivative worker has and for the same measured reason: without it a
        single ``OperationalError`` at connect ends the thread in silence, ``start()`` is a no-op
        afterwards, and deletion stops happening while nothing says so. For a purger that failure
        is worse than for an ingest, because what stops happening is erasure the user asked for.
        """
        while not self._stop.is_set():
            try:
                self.drain()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._failed_passes += 1
            self._stop.wait(self._poll_seconds)

    @property
    def alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def failed_passes(self) -> int:
        return self._failed_passes

    # -- one object ---------------------------------------------------------------------

    def _purge_one(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, outcome: PurgeOutcome
    ) -> bool:
        """Claim, decide, destroy, confirm, record. Returns False when the queue is empty."""
        target = queue.claim_purge(connection, workspace_id)
        if target is None:
            return False
        try:
            self._destroy(connection, target, outcome)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            outcome.failed += 1
            outcome.errors.append(f"{target.target_kind} {target.target_ref[:12]}: {message}")
            queue.finish_purge(
                connection,
                workspace_id,
                purge_id=target.purge_id,
                state="failed",
                error=message[:2000],
            )
        self._record_completion(connection, target, outcome)
        return True

    def _destroy(
        self, connection: psycopg.Connection, target: queue.PurgeTarget, outcome: PurgeOutcome
    ) -> None:
        if target.target_kind == "embedding":
            with connection.transaction():
                authorized = connection.execute(
                    "select caption_vector_purge_is_authorized(%s,%s,%s) as allowed",
                    (target.workspace_id, target.tombstone_id, uuid.UUID(target.target_ref)),
                ).fetchone()
                if authorized is None or not authorized["allowed"]:
                    raise ValueError("the tombstone does not authorize this vector purge")
                deleted = connection.execute(
                    "delete from embedding where workspace_id = %s and embedding_id = %s",
                    (target.workspace_id, uuid.UUID(target.target_ref)),
                )
                if deleted.rowcount:
                    outcome.destroyed += 1
                else:
                    outcome.already_absent += 1
                queue.finish_purge(
                    connection, target.workspace_id, purge_id=target.purge_id, state="done"
                )
            return
        blob_id = BlobId.from_hex(target.target_ref)
        # The lock and the question share one transaction, so nothing can start holding these
        # bytes between the answer and the destruction. The lock is released at commit, which is
        # after the row is marked, which is after the object is gone.
        with connection.transaction():
            connection.execute("select purge_lock_object(%s)", (target.target_ref,))
            row = connection.execute(
                "select case when %s = 'artifact' and exists ("
                "  select 1 from tombstone where tombstone_id=%s and scope='entity') "
                "then person_withdrawal_releases_artifact(%s,decode(%s,'hex')) "
                "else purge_releases_bytes(decode(%s,'hex')) end as releases",
                (
                    target.target_kind,
                    target.tombstone_id,
                    target.tombstone_id,
                    target.target_ref,
                    target.target_ref,
                ),
            ).fetchone()
            assert row is not None
            if not row["releases"]:
                outcome.skipped += 1
                queue.finish_purge(
                    connection,
                    target.workspace_id,
                    purge_id=target.purge_id,
                    state="skipped",
                    error="something live still holds these bytes",
                )
                return

            purger = privileged_purger(
                self._store,
                PurgeAuthorization(
                    tombstone_id=str(target.tombstone_id),
                    actor=str(target.requested_by),
                    reason=target.reason or "a tombstone asked for these bytes to be destroyed",
                ),
            )
            destroyed = purger.purge(blob_id)
            # Asked of the store, not inferred from the return value. `purge` returns False when
            # the object was already absent, which is the ordinary resumed-job case and is not a
            # failure; what would be a failure is reporting success over an object still there,
            # and the store is the only thing that can tell the difference.
            if self._store.exists(blob_id):
                raise RuntimeError(
                    f"the store still holds {target.target_ref[:12]} after it was purged"
                )
            if destroyed:
                outcome.destroyed += 1
            else:
                outcome.already_absent += 1
            queue.mark_purged(connection, target)
            queue.finish_purge(
                connection, target.workspace_id, purge_id=target.purge_id, state="done"
            )

    @staticmethod
    def _record_completion(
        connection: psycopg.Connection, target: queue.PurgeTarget, outcome: PurgeOutcome
    ) -> None:
        """Write ``purge_completed_at`` only when the deletion actually happened.

        Correction 4. The check asks whether every row this tombstone named is marked purged, not
        whether the queue is empty, so a skipped job or a failed one keeps the tombstone open.
        """
        if not queue.is_purge_complete(connection, target.tombstone_id):
            return
        updated = connection.execute(
            "update tombstone set purge_completed_at = now() "
            "where tombstone_id = %s and workspace_id = %s and purge_completed_at is null",
            (target.tombstone_id, target.workspace_id),
        )
        if updated.rowcount:
            outcome.completed_tombstones.append(target.tombstone_id)


def _exhausted(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    """Jobs no pass will claim again, because they have used every attempt."""
    row = connection.execute(
        "select count(*) as n from purge_job "
        "where workspace_id = %s and state <> 'done' and attempts >= %s",
        (workspace_id, queue.MAX_ATTEMPTS),
    ).fetchone()
    assert row is not None
    return int(row["n"])
