"""A creature's made look: asked as a row, made by the operator's run, worn by its kind (0220).

``POST /things/creatures/{kind_sha256}/looks`` asks for a made look of a creature the workspace
keeps (:func:`ask_look`) and answers at once with the look job, queued; ``GET
/things/creatures/looks/{look_id}`` reads it as it goes (:func:`read_look`), for any member of the
workspace. A creature drafted from words alone has its made look asked as its draft keeps it, in the
draft owner's name (:func:`ask_on_keep`, from :mod:`exulanica.selection.creature_drafts`): a made
look is the default way a kept creature looks, its sketch worn until a run makes it and whenever the
fit refuses; the draft reads its creature's newest job (:func:`newest_look`). Nothing here spends:
the paid step is an operator's run, which takes the queued jobs of the workspaces it serves
(:func:`queued_looks`), writes each one's request from the creature's kept documents, marks them
staged under the run's id with the request's digest (:func:`stage_look`), and once its GPU job and
the fit on its own machine are done ends each one (:func:`end_look`): made, naming the look the
workspace now keeps by its document's digest, with the kind look appended so the creature wears it
wherever it is placed (:func:`wear_by_kind`); refused, by the fit's code; failed, by why; or
cancelled. A job moves forward once, and an ended one never changes (the migration refuses anything
else). Each end records the job's share of what the run cost.

:func:`kind_looks` reads the look each creature of a workspace wears by its kind: the newest kind
look whose look the workspace still keeps and has not withdrawn. A thing's own choice still comes
first (:mod:`exulanica.world.thing_looks`).

A job holds ids, digests, codes, times and a cost, and no word: the request a run writes carries the
creature's drafted appearance words and lives only in the run's folder and its GPU job. A
creature's erasure deletes its look jobs and kind looks, and a workspace tombstone every one of its
workspace's, in the migration's triggers. A job is asked under the workspace's lock and never once
the workspace's tombstone is written; at most one unfinished job per creature, and at most
:data:`MAX_OPEN_PER_ACTOR` unfinished and :data:`MAX_PER_ACTOR_HOUR` in an hour for one requester,
since each becomes paid work.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.errors import ExulanicaError, TombstonedError
from exulanica.world.thing_store import ThingStore, admitted_look_by_digest
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "END_STATUSES",
    "MAX_OPEN_PER_ACTOR",
    "MAX_PER_ACTOR_HOUR",
    "CreatureLook",
    "LookLimitReached",
    "LookNotAsked",
    "ask_look",
    "ask_on_keep",
    "end_look",
    "keeps_creature",
    "kind_looks",
    "newest_look",
    "queued_looks",
    "read_look",
    "stage_look",
    "wear_by_kind",
]

#: How a staged look job may end.
END_STATUSES: Final = ("made", "refused", "failed", "cancelled")
#: Unfinished look jobs one requester may have at once, and asks in an hour.
MAX_OPEN_PER_ACTOR: Final = 4
MAX_PER_ACTOR_HOUR: Final = 12
#: A requester's asks are counted under this advisory lock's key, beside the workspace's.
_REQUESTER_LOCK_SEED: Final = 880220
_COLUMNS: Final = (
    "look_id, requested_by, kind_sha256, status, run_id, request_sha256, look_sha256, "
    "refusal_code, failure, cost_usd, created_at, staged_at, finished_at"
)


class LookNotAsked(ExulanicaError):
    """The workspace keeps no creature of that kind, so no look of it can be asked."""


class LookLimitReached(ExulanicaError):
    """This requester has as many unfinished look jobs, or asks this hour, as one may."""


@dataclass(frozen=True, slots=True)
class CreatureLook:
    look_id: uuid.UUID
    requested_by: uuid.UUID
    kind_sha256: str
    status: str
    run_id: uuid.UUID | None
    request_sha256: str | None
    look_sha256: str | None
    refusal_code: str | None
    failure: str | None
    cost_usd: Decimal | None
    created_at: datetime
    staged_at: datetime | None
    finished_at: datetime | None

    @property
    def finished(self) -> bool:
        return self.finished_at is not None


def _look(row: Mapping[str, Any]) -> CreatureLook:
    return CreatureLook(**{name.strip(): row[name.strip()] for name in _COLUMNS.split(",")})


def keeps_creature(
    connection: psycopg.Connection, workspace_id: uuid.UUID, kind_sha256: str
) -> bool:
    """Whether the workspace keeps a creature of this kind: a being whose drafted plan it holds."""
    kind = ThingStore(connection, workspace_id, None).kind_by_digest(kind_sha256)
    return (
        kind is not None
        and kind.klass == "being"
        and kind.document.get("body", {}).get("plan_sha256") is not None
    )


def ask_look(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    kind_sha256: str,
    requested_by: uuid.UUID,
) -> CreatureLook:
    """A look job for the creature of ``kind_sha256``, queued; or the unfinished one already asked
    for it, as it stands.

    The workspace's lock is taken first, and a workspace being erased (a ``workspace`` tombstone)
    asks nothing more (:class:`TombstonedError`). A kind the workspace does not keep as a creature
    is :class:`LookNotAsked`; a requester at their limits, :class:`LookLimitReached`."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        if cursor.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace' limit 1",
            (workspace_id,),
        ).fetchone():
            raise TombstonedError(
                "tombstoned: the workspace has been deleted and asks nothing more"
            )
        if not keeps_creature(connection, workspace_id, kind_sha256):
            raise LookNotAsked("this workspace keeps no creature of that kind")
        waiting = cursor.execute(
            f"select {_COLUMNS} from creature_look where workspace_id=%s and kind_sha256=%s "
            "and status in ('queued', 'staged')",
            (workspace_id, kind_sha256),
        ).fetchone()
        if waiting is not None:
            return _look(waiting)
        cursor.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, %s))",
            (f"{workspace_id}:{requested_by}", _REQUESTER_LOCK_SEED),
        )
        counts = cursor.execute(
            "select count(*) filter (where finished_at is null) as open, "
            "count(*) filter (where created_at > now() - interval '1 hour') as hour "
            "from creature_look where workspace_id=%s and requested_by=%s",
            (workspace_id, requested_by),
        ).fetchone()
        assert counts is not None
        if counts["open"] >= MAX_OPEN_PER_ACTOR or counts["hour"] >= MAX_PER_ACTOR_HOUR:
            raise LookLimitReached("this requester has as many look jobs as one may")
        row = cursor.execute(
            "insert into creature_look (workspace_id, look_id, requested_by, kind_sha256) "
            f"values (%s, %s, %s, %s) returning {_COLUMNS}",
            (workspace_id, uuid.uuid4(), requested_by, kind_sha256),
        ).fetchone()
        assert row is not None
    return _look(row)


def ask_on_keep(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    kind_sha256: str,
    requested_by: uuid.UUID,
) -> CreatureLook | None:
    """The look job of a creature its draft has just kept, asked for the draft's owner as
    :func:`ask_look` asks one; None, with nothing asked, when the owner is at their limits, the
    workspace is being erased or the creature was erased since. The creature stays kept either way
    and wears its sketch, and its owner may still ask for its look later."""
    try:
        return ask_look(
            connection, workspace_id, kind_sha256=kind_sha256, requested_by=requested_by
        )
    except (LookLimitReached, LookNotAsked, TombstonedError):
        return None


def newest_look(
    connection: psycopg.Connection, workspace_id: uuid.UUID, kind_sha256: str
) -> CreatureLook | None:
    """The creature's newest look job, finished or not; None when none was asked or its creature
    was erased (its jobs went with it)."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from creature_look where workspace_id=%s and kind_sha256=%s "
            "order by created_at desc, look_id desc limit 1",
            (workspace_id, kind_sha256),
        ).fetchone()
    return None if row is None else _look(row)


def read_look(
    connection: psycopg.Connection, workspace_id: uuid.UUID, look_id: uuid.UUID
) -> CreatureLook | None:
    """The look job, for any member of its workspace: it is the creature's, holds no word, and is
    answered to whoever asks again for that creature while it waits. One erased with its creature,
    or another workspace's, is None."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from creature_look where workspace_id=%s and look_id=%s",
            (workspace_id, look_id),
        ).fetchone()
    return None if row is None else _look(row)


def queued_looks(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, limit: int
) -> list[CreatureLook]:
    """The workspace's queued look jobs, oldest first, at most ``limit``: what a run may stage."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select {_COLUMNS} from creature_look where workspace_id=%s and status='queued' "
            "order by created_at, look_id limit %s",
            (workspace_id, limit),
        ).fetchall()
    return [_look(row) for row in rows]


def stage_look(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    look_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    request_sha256: str,
) -> bool:
    """Mark a queued look job staged under ``run_id`` with the digest of the request the run wrote.
    False, with nothing changed, when the job is no longer queued or no longer exists (cancelled,
    or erased with its creature or its workspace)."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "update creature_look set status='staged', run_id=%s, request_sha256=%s, "
            "staged_at=statement_timestamp() "
            "where workspace_id=%s and look_id=%s and status='queued'",
            (run_id, request_sha256, workspace_id, look_id),
        )
        return cursor.rowcount == 1


def end_look(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    look_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    status: str,
    look_sha256: str | None = None,
    refusal_code: str | None = None,
    failure: str | None = None,
    cost_usd: Decimal | None = None,
) -> CreatureLook | None:
    """End a look job staged under ``run_id``: made with the look's digest, refused with the fit's
    code, failed or cancelled with why, with its share of the run's cost. Run inside the caller's
    transaction, so a made look is admitted and its job ended together; the workspace's lock is
    taken first and held to the caller's commit. None, with nothing changed, when the job is not
    staged under this run (erased since, or ended already): the caller then keeps nothing for it."""
    if status not in END_STATUSES:
        raise ValueError(f"a look job ends {', '.join(END_STATUSES)}")
    # The workspace's lock before the job's row, the order a creature's erasure takes them (its
    # lock, then its trigger's delete of the row), so the two never wait on each other in a cycle;
    # wear_by_kind taking it again in the same transaction costs nothing.
    lock_workspace(connection, workspace_id)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "update creature_look set status=%s, look_sha256=%s, refusal_code=%s, failure=%s, "
            "cost_usd=%s, finished_at=statement_timestamp() "
            "where workspace_id=%s and look_id=%s and run_id=%s and status='staged' "
            f"returning {_COLUMNS}",
            (status, look_sha256, refusal_code, failure, cost_usd, workspace_id, look_id, run_id),
        ).fetchone()
    return None if row is None else _look(row)


def wear_by_kind(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    kind_sha256: str,
    look_sha256: str,
    chosen_by: uuid.UUID,
    look_id: uuid.UUID | None = None,
) -> int:
    """Append the look the creature of ``kind_sha256`` wears wherever it is placed; its choice id.
    The look must be one the workspace keeps, drawn on the creature's own plan, and the kind a
    creature it keeps.

    The workspace's lock is taken first and held to the end of the transaction, as an erasure of
    the creature and a workspace tombstone take it, so neither commits between the check and the
    row: an erasure that comes after finds the row and deletes it. Inside the caller's transaction
    (a run ends a job and its creature starts wearing the look together) the lock is the caller's
    until it commits. A workspace being erased wears nothing more (:class:`TombstonedError`)."""
    with connection.transaction(), connection.cursor(row_factory=dict_row) as cursor:
        lock_workspace(connection, workspace_id)
        if cursor.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace' limit 1",
            (workspace_id,),
        ).fetchone():
            raise TombstonedError(
                "tombstoned: the workspace has been deleted and wears nothing more"
            )
        if not keeps_creature(connection, workspace_id, kind_sha256):
            raise LookNotAsked("this workspace keeps no creature of that kind")
        look = admitted_look_by_digest(connection, workspace_id, look_sha256)
        if look is None:
            raise LookNotAsked("this workspace keeps no such look")
        kind = ThingStore(connection, workspace_id, None).kind_by_digest(kind_sha256)
        # A kind wears only a look drawn on its own plan, as every reader of the row holds it to.
        if kind is None or look.body_plan != kind.plan:
            raise LookNotAsked("the look is not drawn on that creature's plan")
        row = cursor.execute(
            "insert into kind_look (workspace_id, kind_sha256, look_sha256, look_id, chosen_by) "
            "values (%s, %s, %s, %s, %s) returning choice_id",
            (workspace_id, kind_sha256, look_sha256, look_id, chosen_by),
        ).fetchone()
    assert row is not None
    return int(row["choice_id"])


def kind_looks(connection: psycopg.Connection, workspace_id: uuid.UUID) -> dict[str, Any]:
    """The look each creature of the workspace wears by its kind, kind digest to the admitted look
    (:class:`~exulanica.things.looks.Look`): the newest kind look whose look the workspace still
    keeps and has not withdrawn, the one before it where it no longer does."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "select kind_sha256, look_sha256 from kind_look where workspace_id=%s "
            "order by kind_sha256, choice_id desc",
            (workspace_id,),
        ).fetchall()
    worn: dict[str, Any] = {}
    for row in rows:
        if row["kind_sha256"] in worn:
            continue
        look = admitted_look_by_digest(connection, workspace_id, row["look_sha256"])
        if look is not None:
            worn[row["kind_sha256"]] = look
    return worn
