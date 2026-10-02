"""A comparison started from the application: its start, and the claim a host holds to play it.

A world's owner starts a comparison from the application (``POST /world/versions/{version_id}/
society/comparisons``): the route defines it, reserves every run and records its start here, in one
transaction. A host's comparison worker then claims the start, as the playback worker claims a
playing society (:class:`~exulanica.world.society_control_repository.SocietyControlRepository`):
the oldest unfinished start of a workspace whose lease is free or has run out, under the
workspace's advisory lock and with ``skip locked``, leased for the control's ``LEASE_SECONDS``. The
host renews the lease before each run and after each simulated minute
(:meth:`SocietyComparisonStarts.renew`), so a host that stops lets its lease run out and the next
claim takes the start over; that claim closes what the stopped host left, each run with receipts
and no outcome as failed ``interrupted`` (the runner's own rule), and plays the rest. A claim that
takes over a lease that ran out says so, and what it presumes the stopped host spent without
recording it is kept on the start (:meth:`SocietyComparisonStarts.presume`), so every later claim
deducts it too. Claims in a row that finish no run are counted, and one past
``MAX_CLAIM_ATTEMPTS`` closes the start instead; a run given an outcome sets the count back in the
transaction that records it (:meth:`SocietyComparisonStarts.ran`), as playback sets its own back
with each minute it records, so a host that stops after finishing runs, however it stops, never
counts as one that finished none.

A start records who started it, the bound its asks may spend and the most calls they may make, and
how many runs it planned; migration 0119 keeps those as they were written, allows one unfinished
start per world and deletes none. Every statement names the world, or selects it where a claim
considers every world of a workspace. Nothing here asks a model or plays a minute.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.session import set_workspace
from exulanica.models.usage import USD_QUANTUM
from exulanica.world.society_controls import LEASE_SECONDS, MAX_CLAIM_ATTEMPTS

__all__ = [
    "START_STATES",
    "START_TABLES",
    "ComparisonClaim",
    "ComparisonRunning",
    "SocietyComparisonStarts",
    "StartConflict",
    "start_document",
    "start_state",
]

#: The start table of each kind of comparison a host plays by this claim: a society comparison of
#: who decides for a world's people (migration 0119), and a signal comparison of a town's lights
#: (migration 0132). Both have the same columns, guard and claim, and each claim takes its own
#: workspace lock.
START_TABLES: Final = {"society": "society_comparison_start", "signal": "signal_comparison_start"}
_CLAIM_LOCKS: Final = {"society": 880119, "signal": 880132}

#: Where a start stands, as a reader is told: waiting for a host to claim it, being played by one,
#: finished with every run's outcome, or closed by a host before every run was played.
START_STATES: Final = (
    "waiting",
    "running",
    "finished",
    "closed",
)


class ComparisonRunning(ValueError):
    """The world already has a comparison started from the application and not finished."""

    def __init__(self, comparison_id: uuid.UUID) -> None:
        super().__init__(f"comparison {comparison_id} of this world has not finished")
        self.comparison_id = comparison_id


class StartConflict(ValueError):
    """A comparison id already names a start with another bound, plan or requester."""


@dataclass(frozen=True, slots=True)
class ComparisonClaim:
    """A host's claim of one start: what it may spend, and the lease it holds."""

    workspace_id: uuid.UUID
    world_id: str
    comparison_id: uuid.UUID
    requested_by: uuid.UUID
    bound_usd: Decimal
    bound_calls: int
    token: uuid.UUID
    #: How many claims in a row before this one finished no run.
    attempts_before: int
    #: Whether this claim took the start over from a host whose lease ran out, which may have been
    #: asking a minute it never recorded.
    took_over: bool
    #: What claims before this one presumed hosts spent and never recorded.
    presumed_usd: Decimal
    #: The kind of comparison claimed, a key of :data:`START_TABLES`.
    kind: str = "society"


def start_state(row: Mapping[str, Any] | None, now: dt.datetime) -> str | None:
    """Where a start stands (``START_STATES``), or None for a comparison nobody started from the
    application; a lease that ran out is waiting for the next claim."""
    if row is None:
        return None
    if row["finished_at"] is not None:
        return "finished" if row["closed_reason"] is None else "closed"
    if row["lease_token"] is not None and row["lease_expires_at"] > now:
        return "running"
    return "waiting"


def start_document(
    row: Mapping[str, Any],
    spent_usd: Decimal,
    now: dt.datetime,
    cancellation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A start as the reads serve it: the bound its owner stated, what its asks spent by their
    receipts and what hosts that stopped were presumed to have spent unrecorded, where it stands,
    why a host closed it, when it was started, and when it was cancelled, if it was
    (:mod:`exulanica.world.comparison_facts`). A start whose cancellation a host has not yet acted
    on still reads running; it closes with the reason ``comparison_cancelled``."""
    return {
        "bound_usd": format(row["bound_usd"], "f"),
        "spent_usd": format(spent_usd.quantize(USD_QUANTUM), "f"),
        "presumed_usd": format(row["presumed_usd"], "f"),
        "state": start_state(row, now),
        "closed_reason": row["closed_reason"],
        "runs_planned": row["runs_planned"],
        "started_at": row["created_at"].isoformat(),
        "finished_at": None if row["finished_at"] is None else row["finished_at"].isoformat(),
        "cancel": None
        if cancellation is None
        else {"requested_at": cancellation["requested_at"].isoformat()},
    }


class SocietyComparisonStarts:
    """Record, read and claim the comparisons started from the application in one workspace."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, kind: str = "society"
    ) -> None:
        if kind not in START_TABLES:
            raise ValueError(f"no kind of comparison {kind!r}")
        self.connection, self.workspace_id, self.kind = connection, workspace_id, kind
        #: This kind's start table, from the closed mapping above, never from a caller's text.
        self.table = START_TABLES[kind]
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    def now(self) -> dt.datetime:
        return self.connection.execute("select clock_timestamp() as now").fetchone()["now"]

    # -- a start ---------------------------------------------------------------------------------

    def record(
        self,
        world_id: str,
        comparison_id: uuid.UUID,
        *,
        requested_by: uuid.UUID,
        bound_usd: Decimal,
        bound_calls: int,
        runs_planned: int,
    ) -> dict[str, Any]:
        """Record a start, or find the same one recorded before: the same id with another bound,
        plan or requester is a :class:`StartConflict`, and a world whose other start has not
        finished is a :class:`ComparisonRunning`."""
        try:
            with self.connection.transaction():
                self.connection.execute(
                    f"insert into {self.table}(workspace_id,world_id,comparison_id,"
                    "requested_by,bound_usd,bound_calls,runs_planned) values(%s,%s,%s,%s,%s,%s,%s) "
                    "on conflict (workspace_id,comparison_id) do nothing",
                    (
                        self.workspace_id,
                        world_id,
                        comparison_id,
                        requested_by,
                        bound_usd,
                        bound_calls,
                        runs_planned,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name != f"{self.table}_one_unfinished_per_world":
                raise
            running = self.unfinished(world_id)
            raise ComparisonRunning(
                comparison_id if running is None else running["comparison_id"]
            ) from exc
        row = self.read(world_id, [comparison_id]).get(comparison_id)
        if row is None or (
            row["requested_by"],
            row["bound_usd"],
            row["bound_calls"],
            row["runs_planned"],
        ) != (requested_by, bound_usd, bound_calls, runs_planned):
            raise StartConflict("the comparison id already names another start")
        return row

    def read(
        self, world_id: str, comparison_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """The starts of these comparisons of the world, by comparison id; a comparison nobody
        started from the application has none."""
        rows = self.connection.execute(
            f"select * from {self.table} where workspace_id=%s and world_id=%s "
            "and comparison_id=any(%s)",
            (self.workspace_id, world_id, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: row for row in rows}

    def lock(self, world_id: str, comparison_id: uuid.UUID) -> dict[str, Any] | None:
        """The comparison's start, locked for the caller's open transaction so no host claims it
        meanwhile (a claim skips a locked start), or None for a comparison nobody started from
        the application."""
        return self.connection.execute(
            f"select * from {self.table} where workspace_id=%s and world_id=%s "
            "and comparison_id=%s for update",
            (self.workspace_id, world_id, comparison_id),
        ).fetchone()

    def close_unclaimed(
        self, world_id: str, comparison_id: uuid.UUID, *, closed_reason: str, presumed_usd: Decimal
    ) -> bool:
        """Finish a start no host holds a live lease on, closed by ``closed_reason``, keeping
        ``presumed_usd`` more as spent and unrecorded: what a host whose lease ran out may have
        been asking. Say whether it was still unfinished. Asked by a cancellation, in the
        transaction that locked the start (:meth:`lock`)."""
        changed = self.connection.execute(
            f"update {self.table} set presumed_usd=presumed_usd+%s,"
            "lease_token=null,claimed_at=null,lease_expires_at=null,"
            "finished_at=clock_timestamp(),closed_reason=%s "
            "where workspace_id=%s and world_id=%s and comparison_id=%s and finished_at is null "
            "and (lease_token is null or lease_expires_at<=clock_timestamp())",
            (presumed_usd, closed_reason, self.workspace_id, world_id, comparison_id),
        ).rowcount
        return changed == 1

    def unfinished(self, world_id: str) -> dict[str, Any] | None:
        """The world's start that has not finished, or None."""
        return self.connection.execute(
            f"select * from {self.table} where workspace_id=%s and world_id=%s "
            "and finished_at is null",
            (self.workspace_id, world_id),
        ).fetchone()

    # -- a host's claim --------------------------------------------------------------------------

    def claim(self) -> ComparisonClaim | None:
        """Lease the workspace's oldest unfinished start whose lease is free or ran out, whichever
        world holds it, or None when there is none or another host is claiming in the workspace.
        The claim counts one attempt more; a run given an outcome sets the count back
        (:meth:`ran`). A start whose lease token is still set was held by a host whose lease ran
        out, so this claim takes it over."""
        with self.connection.transaction():
            locked = self.connection.execute(
                "select pg_try_advisory_xact_lock(hashtextextended(%s,%s)) as held",
                (str(self.workspace_id), _CLAIM_LOCKS[self.kind]),
            ).fetchone()["held"]
            if not locked:
                return None
            row = self.connection.execute(
                "select workspace_id,world_id,comparison_id,requested_by,bound_usd,bound_calls,"
                f"claim_attempts,lease_token,presumed_usd from {self.table} "
                "where workspace_id=%s "
                "and finished_at is null "
                "and (lease_token is null or lease_expires_at<=clock_timestamp()) "
                "order by created_at,comparison_id for update skip locked limit 1",
                (self.workspace_id,),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4()
            self.connection.execute(
                f"update {self.table} set lease_token=%s,claimed_at=clock_timestamp(),"
                "lease_expires_at=clock_timestamp()+make_interval(secs=>%s),"
                "claim_attempts=claim_attempts+1 "
                "where workspace_id=%s and world_id=%s and comparison_id=%s",
                (token, LEASE_SECONDS, self.workspace_id, row["world_id"], row["comparison_id"]),
            )
            return ComparisonClaim(
                workspace_id=self.workspace_id,
                world_id=row["world_id"],
                comparison_id=row["comparison_id"],
                requested_by=row["requested_by"],
                bound_usd=row["bound_usd"],
                bound_calls=row["bound_calls"],
                token=token,
                attempts_before=row["claim_attempts"],
                took_over=row["lease_token"] is not None,
                presumed_usd=row["presumed_usd"],
                kind=self.kind,
            )

    def _held(self, claim: ComparisonClaim, statement: str, values: tuple[Any, ...]) -> bool:
        """Run ``statement``, an update of the start ``claim`` holds whose last conditions are the
        claim's own, and say whether the host still held it: its lease the claim's and not run
        out, and the start not finished."""
        with self.connection.transaction():
            changed = self.connection.execute(
                statement,
                (*values, claim.workspace_id, claim.world_id, claim.comparison_id, claim.token),
            ).rowcount
        return changed == 1

    def holds(self, claim: ComparisonClaim) -> bool:
        """Whether the host still holds ``claim``, read in the caller's open transaction and kept
        from changing until it ends: its lease the claim's and not run out, and the start not
        finished. The start is locked, so no claim takes it over and no cancel closes it before the
        caller's transaction ends, and a write the host makes in that transaction is one it made
        while it held the start (a claim skips a locked start). The lock is the row's update lock,
        never a share a later update of the same transaction would have to raise: two runs a host
        plays at once each take it in turn, and the transaction that seals an hour also sets the
        start's claim count back (:meth:`ran`)."""
        return (
            self.connection.execute(
                f"select 1 from {self.table} where workspace_id=%s and world_id=%s "
                "and comparison_id=%s and lease_token=%s and lease_expires_at>clock_timestamp() "
                "and finished_at is null for update",
                (claim.workspace_id, claim.world_id, claim.comparison_id, claim.token),
            ).fetchone()
            is not None
        )

    def renew(self, claim: ComparisonClaim) -> bool:
        """Extend the claim's lease by ``LEASE_SECONDS`` from now; False once the host no longer
        holds it, its lease having run out or been taken over."""
        return self._held(
            claim,
            f"update {self.table} "
            "set lease_expires_at=clock_timestamp()+make_interval(secs=>%s) "
            "where workspace_id=%s and world_id=%s and comparison_id=%s and lease_token=%s "
            "and lease_expires_at>clock_timestamp() and finished_at is null",
            (LEASE_SECONDS,),
        )

    def presume(self, claim: ComparisonClaim, usd: Decimal) -> bool:
        """Keep ``usd`` on the start as spent and unrecorded, beside what earlier claims presumed:
        the most the minutes a host whose lease ran out may have been asking can have cost."""
        return self._held(
            claim,
            f"update {self.table} set presumed_usd=presumed_usd+%s "
            "where workspace_id=%s and world_id=%s and comparison_id=%s and lease_token=%s "
            "and lease_expires_at>clock_timestamp() and finished_at is null",
            (usd,),
        )

    @staticmethod
    def ran(
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        world_id: str,
        comparison_id: uuid.UUID,
        kind: str = "society",
    ) -> None:
        """A run of the start was given an outcome, in the caller's transaction on
        ``connection``: the count of claims in a row that finished no run is set back, whichever
        host recorded the outcome and whether or not its lease still holds."""
        connection.execute(
            f"update {START_TABLES[kind]} set claim_attempts=0 where workspace_id=%s "
            "and world_id=%s and comparison_id=%s and finished_at is null",
            (workspace_id, world_id, comparison_id),
        )

    def release(self, claim: ComparisonClaim) -> bool:
        """Give the lease up without finishing, as a host that is stopping does, so the next
        claim need not wait for it to run out."""
        return self._held(
            claim,
            f"update {self.table} "
            "set lease_token=null,claimed_at=null,lease_expires_at=null "
            "where workspace_id=%s and world_id=%s and comparison_id=%s and lease_token=%s "
            "and lease_expires_at>clock_timestamp() and finished_at is null",
            (),
        )

    def finish(self, claim: ComparisonClaim, *, closed_reason: str | None = None) -> bool:
        """Every run has an outcome, or the start was closed by ``closed_reason``: the start is
        finished, and its lease let go."""
        return self._held(
            claim,
            f"update {self.table} "
            "set lease_token=null,claimed_at=null,lease_expires_at=null,"
            "finished_at=clock_timestamp(),closed_reason=%s "
            "where workspace_id=%s and world_id=%s and comparison_id=%s and lease_token=%s "
            "and lease_expires_at>clock_timestamp() and finished_at is null",
            (closed_reason,),
        )

    @staticmethod
    def attempts_spent(claim: ComparisonClaim) -> bool:
        """Whether the claims before this one, in a row, finished no run as often as a claim is
        tried (the control's ``MAX_CLAIM_ATTEMPTS``): this claim closes the start."""
        return claim.attempts_before >= MAX_CLAIM_ATTEMPTS
