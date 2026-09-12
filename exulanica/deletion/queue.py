"""One claimed purge job, and the three ways it can end.

The queue is filled by a trigger in the tombstone's own transaction, not by this module and not
by any caller: migration 0013 section 5 says why. What is here is the reading half.

**Nothing here is terminal except ``done``, and that took two corrections to get right.**

``skipped`` was the first: a job whose bytes something else still holds has not failed and is not
done, and terminal ``skipped`` set ``tombstone.purge_completed_at`` while the photograph was
still on disk, because the unique constraint refused a second row for the same target and the
completion check ignored it.

``failed`` was the second, and it was the same defect left standing one column over. Measured
with a store whose delete raised once, a transient outage: two jobs went to ``failed``, three
later passes with a healthy store did nothing at all, the bytes a user deleted stayed on disk for
ever, the tombstone never completed, and re-enqueueing the same target raised `UniqueViolation`.
The only recovery was writing a second tombstone for the same capture, which no interface offers.
It is now re-claimable, bounded by :data:`MAX_ATTEMPTS` so a permanently broken target reports
rather than spins.

**And ``running`` is reclaimed here, on a timestamp, which the derivative queue may not do.**
Both queues reclaim now; the shapes differ and the difference is what a re-run costs. Every step
here is idempotent and cheap: the advisory lock serialises two purgers on one object, ``purge``
returns False when the object is already absent, ``mark_purged`` is a conditional UPDATE, and the
predicate is re-asked before anything is destroyed. So a second worker taking a row a live purger
is still working on does the safe thing by construction, and ``attempted_at`` alone is a good
enough signal. A derivative job's expensive step is a paid model call with a per-request nonce
and no caching, so a reclaim of a LIVE claimant there costs money and can produce two terminal
events for one batch; that queue therefore carries a lease the claimant renews and a token every
write of its own is conditional on. Same defect, two costs, two shapes, and
:mod:`exulanica.ingest.derivative_queue` is where the other one is explained.

What a stranded row leaves without this is worse than "work not done": measured, a crash between
the store unlink and the COMMIT leaves the bytes gone, the ``blob`` row saying they are live, and
a ``storage_key`` pointing at an object that is not there, which is the exact inverse of what
0001's stub design exists to produce.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Final

import psycopg

from exulanica.db.roles import PURGE_CROSS_WORKSPACE_TABLES

__all__ = [
    "CROSS_WORKSPACE_POLICY",
    "DESTROYABLE_KINDS",
    "MAX_ATTEMPTS",
    "RETRY_AFTER",
    "PurgeTarget",
    "Visibility",
    "claim_purge",
    "finish_purge",
    "is_purge_complete",
    "mark_purged",
    "read_visibility",
]

#: How long a job waits before it is tried again, whether it was skipped, failed, or stranded in
#: ``running`` by a worker that died. Long enough that a blob another live capture holds is not
#: re-examined every second, short enough that a deletion completes within an hour of the last
#: thing releasing it.
RETRY_AFTER: Final = dt.timedelta(minutes=15)

#: How many times a job may be CLAIMED before it stops being re-claimed. Claimed, not failed, and
#: the distinction is the correction: :func:`claim_purge` increments ``attempts`` on every claim
#: including one that ends ``skipped``, and a skipped job's next attempt is NOT identical to its
#: last. It was deferred because another live capture, possibly in another workspace, still holds
#: those exact bytes, and that is a fact about the world which changes when that capture is
#: deleted. So the bound is on how many times this queue will look at a job, not on how many
#: times a target has broken.
#:
#: **The comment was corrected and the behaviour was left, which is the choice worth stating.**
#: Not charging a deferral would mean a blob some other workspace keeps for ever is re-examined
#: every fifteen minutes for ever, which is the spin this bound exists to stop. Charging it means
#: a long-held blob can use its eight looks and stop being examined while its tombstone is still
#: incomplete, and the reason that is acceptable is that it is VISIBLE:
#: :func:`exulanica.deletion.worker._exhausted` counts every non-``done`` job at the bound,
#: deferrals included, and `exulanica-purge` prints "job(s) have used every attempt and will not be
#: retried". A bound that is reported is a decision; the same bound, unreported, would be the
#: silent incompletion corrections 3 and 13 were both about.
MAX_ATTEMPTS: Final = 8

#: The kinds this worker knows how to destroy. Blob and artifact targets name stored object
#: hashes. Embedding targets name a database row that only the purge role may delete.
DESTROYABLE_KINDS: Final = ("blob", "artifact", "embedding")


#: The policy `provision_purge_role` creates. Named here as well as there because this module is
#: what checks for it, and a name spelled twice with no pin is a check that goes quiet.
CROSS_WORKSPACE_POLICY: Final = "purge_sees_every_holder_of_these_bytes"


@dataclass(frozen=True, slots=True)
class Visibility:
    """Which role is connected, and whether it can see the whole of the destroy question.

    ``blob`` is not workspace-scoped, so "does anything still hold these bytes" is a question
    about every workspace, and a session that can see one answers it wrongly in the direction
    that destroys somebody else's photograph. Which role is connected is therefore not
    configuration detail, it is the difference between a correct purge and a silent one.
    """

    role: str
    sees_every_workspace: bool

    @property
    def refusal(self) -> str | None:
        """Why this connection must not destroy anything, or None when it may."""
        if self.sees_every_workspace:
            return None
        named = ", ".join(f"`{table}`" for table in PURGE_CROSS_WORKSPACE_TABLES)
        return (
            f"connected as {self.role!r}, which has no cross-workspace read of {named}. `blob` "
            "is shared between workspaces, so this connection would answer \"does anything still "
            "hold these bytes\" about its own workspace only and destroy objects another one is "
            "using. Point EXULANICA_PURGE_DATABASE_URL at the `exulanica_purge` role that "
            "`exulanica-db` provisions"
        )


def read_visibility(connection: psycopg.Connection) -> Visibility:
    """Ask the database who is connected and what it can see, rather than trusting a variable.

    ``EXULANICA_PURGE_DATABASE_URL`` is a name. Nothing about it says which role is behind it, and
    a deployment that pointed it at the writer used to get a silent, narrowed purge: measured,
    one destroyed object, zero skipped, a tombstone recorded complete, and another workspace's
    live photograph gone. The docstring said this was reported and nothing reported it.

    **The table list is taken from the grant rather than written out here**, because the question
    is whether the role can see the whole of what ``purge_releases_bytes`` reads, and that grew a
    relation in migration 0024. A list spelled twice would go on reporting a full view over a
    table the predicate had started reading through a narrowed one, which is the same failure as
    correction 7 with nothing loud about it.
    """
    tables = list(PURGE_CROSS_WORKSPACE_TABLES)
    row = connection.execute(
        "select current_user as role, "
        "  (select count(distinct tablename) from pg_policies "
        "    where policyname = %s and tablename = any(%s) "
        "      and current_user = any(roles)) as tables",
        (CROSS_WORKSPACE_POLICY, tables),
    ).fetchone()
    assert row is not None
    return Visibility(
        role=str(row["role"]), sees_every_workspace=int(row["tables"]) == len(tables)
    )


@dataclass(frozen=True, slots=True)
class PurgeTarget:
    """One stored object a tombstone asked to have destroyed."""

    purge_id: uuid.UUID
    tombstone_id: uuid.UUID
    workspace_id: uuid.UUID
    #: ``blob`` and ``artifact`` name stored bytes. ``embedding`` names one sensitive vector row.
    target_kind: str
    #: A lowercase content hash for stored bytes, or an embedding UUID. Never a storage path.
    target_ref: str
    attempts: int
    #: What the store was told when it was told to destroy this. Every field is mandatory on
    #: PurgeAuthorization, and they come from the tombstone row rather than from a caller.
    requested_by: uuid.UUID
    reason: str | None


def claim_purge(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> PurgeTarget | None:
    """Take the next job for this workspace, or None when there is nothing to do.

    Picks up ``queued`` immediately, and ``skipped``, ``failed`` and ``running`` once they have
    gone quiet for :data:`RETRY_AFTER`, up to :data:`MAX_ATTEMPTS`. Never-attempted first, then
    oldest attempt, so a fresh deletion is never queued behind a blob something else has been
    holding for a week.

    ``running`` is in that list, and the module docstring says why a timestamp is enough to
    reclaim it here and why the derivative queue needs a lease and a token for the same job.
    ``done`` is the only terminal state.

    **The reclaim arm is not served by ``purge_job_queue_idx``**, which migration 0013 left
    partial on ``state in ('queued', 'skipped')``. Measured with ``enable_seqscan`` off: the plan
    is a bitmap scan on the unique constraint's index with the state test as a filter. That is a
    cost rather than a defect at this queue's size, and it is said here rather than left for
    somebody to infer from the index definition that the predicate is covered.
    """
    row = connection.execute(
        "update purge_job set state = 'running', attempts = attempts + 1, "
        "  attempted_at = now(), last_error = null "
        "where purge_id = ("
        "  select pj.purge_id from purge_job pj "
        "   where pj.workspace_id = %s "
        "     and pj.target_kind = any(%s) "
        "     and (pj.target_kind <> 'embedding' or "
        "       caption_vector_purge_is_authorized(pj.workspace_id, pj.tombstone_id, "
        "                                          pj.target_ref::uuid)) "
        "     and pj.attempts < %s "
        "     and (pj.state = 'queued' "
        "          or (pj.state in ('skipped', 'failed', 'running') "
        "              and (pj.attempted_at is null or pj.attempted_at < now() - %s))) "
        "   order by pj.attempted_at nulls first, pj.created_at "
        "   for update skip locked limit 1) "
        "returning purge_id, tombstone_id, workspace_id, target_kind, target_ref, attempts",
        (workspace_id, list(DESTROYABLE_KINDS), MAX_ATTEMPTS, RETRY_AFTER),
    ).fetchone()
    if row is None:
        return None
    tombstone = connection.execute(
        "select requested_by, reason from tombstone where tombstone_id = %s and workspace_id = %s",
        (row["tombstone_id"], workspace_id),
    ).fetchone()
    # The tombstone is what authorises the destruction and it is read here rather than carried on
    # the job, so a job cannot outlive the authorisation that produced it. `purge_job.tombstone_id`
    # is a NOT NULL foreign key, so this is a fact about the row rather than a branch that runs.
    assert tombstone is not None, f"purge job {row['purge_id']} names no tombstone"
    return PurgeTarget(
        purge_id=row["purge_id"],
        tombstone_id=row["tombstone_id"],
        workspace_id=row["workspace_id"],
        target_kind=row["target_kind"],
        target_ref=row["target_ref"],
        attempts=row["attempts"],
        requested_by=tombstone["requested_by"],
        reason=tombstone["reason"],
    )


def finish_purge(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    purge_id: uuid.UUID,
    state: str,
    error: str | None = None,
) -> None:
    """Close a claimed job as one of the three things that can have happened.

    ``done`` means the bytes are gone. ``skipped`` means something else still holds them and this
    will be asked again. ``failed`` means the attempt broke. Collapsing the middle one into
    either of the others is how ``purge_completed_at`` gets written over a photograph that is
    still there.
    """
    if state not in ("done", "skipped", "failed"):
        raise ValueError(f"a claimed purge job cannot be closed as {state!r}")
    connection.execute(
        "update purge_job set state = %s, last_error = %s, "
        "  completed_at = case when %s = 'done' then now() else null end "
        "where purge_id = %s and workspace_id = %s",
        (state, error, state, purge_id, workspace_id),
    )


def mark_purged(connection: psycopg.Connection, target: PurgeTarget) -> None:
    """Record that the bytes are gone, **after** they are gone.

    The order is the whole of it. The store is not in this transaction, so a row marked purged
    before the object is destroyed is a row that lies when the process dies in between, and it
    lies in the direction that stops anything ever trying again. Destroyed first, recorded
    second: a crash in that window leaves the bytes gone and the row still saying they are live,
    which is the recoverable direction, and it is recovered by :func:`claim_purge` taking the
    stranded ``running`` row back after :data:`RETRY_AFTER`. ``purge`` then returns False because
    the object is already absent, which is why erasure is idempotent.

    **This sentence used to claim the row was re-claimed while the same module said no row ever
    was.** It was not, and the window left a ``blob`` row with ``purged_at`` null and a
    ``storage_key`` pointing at an object that had been removed: a citation resolving to "here it
    is" and then raising, instead of to "the user deleted this". The reclaim above is what makes
    the sentence true.

    ``storage_key`` is cleared with the same statement. 0001 keeps the stub row so a citation
    into deleted content resolves to "the user deleted this" rather than to nothing; a stub still
    pointing at an object key would be pointing at something that is not there.
    """
    if target.target_kind == "blob":
        connection.execute(
            "update blob set purged_at = now(), storage_key = null "
            "where blob_sha256 = decode(%s, 'hex') and purged_at is null",
            (target.target_ref,),
        )
        return
    connection.execute(
        "update artifact set purged_at = now(), storage_key = null "
        "where workspace_id = %s and content_sha256 = decode(%s, 'hex') and purged_at is null",
        (target.workspace_id, target.target_ref),
    )


def is_purge_complete(
    connection: psycopg.Connection, tombstone_id: uuid.UUID
) -> bool:
    """Did the deletion happen, rather than did the queue go quiet. Correction 4."""
    row = connection.execute(
        "select tombstone_purge_is_complete(%s) as complete", (tombstone_id,)
    ).fetchone()
    assert row is not None
    return bool(row["complete"])
