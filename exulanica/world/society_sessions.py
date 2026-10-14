"""A living session: one bounded stretch of a society's playback, opened and closed by receipts.

A session is two receipts of the society's playback history (``world_society_control_event``,
migration "a living session is opened and closed in the playback history"): ``session_opened``
records who opened it, its limits, and the tick and state digest it started from, and
``session_closed`` records why it closed, who closed it (none for the system), and the tick and
state digest it ended at. A session is open from its opening receipt until its closing one, and a
closed session is never open again: the next stretch is a new session. One session is open at a
time per society, held under the workspace lock every playback write takes.

So a session needs no table of its own: its receipts are erased, granted, scoped and ordered with
the rest of the playback history, and they interleave with the receipts of the minutes it played.

The limits are stored when a session opens and enforced by the playback worker
(``docs/synthetic-society-contract.md#living-sessions``).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.models.usage import usd_string
from exulanica.spending.status import UNRESOLVED_AFTER

_LOG = logging.getLogger(__name__)

#: The profile a session reads as.
SESSION_PROFILE: Final = "exulanica.society-session/v1"
SESSION_OPENED: Final = "session_opened"
SESSION_CLOSED: Final = "session_closed"
SESSION_KINDS: Final = (SESSION_OPENED, SESSION_CLOSED)

#: The figures every session states, and the most this installation lets one state.
SESSION_MAXIMA: Final[Mapping[str, Any]] = {
    "wall_seconds": 24 * 60 * 60,
    "minutes": 24 * 60,
    "decisions": 10_000,
    "usd": Decimal("100"),
    "calls": 10_000,
}
_COUNTS: Final = ("wall_seconds", "minutes", "decisions", "calls")
_USD: Final = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")


class SessionRefused(ValueError):
    """Why a session was not opened or stopped, by code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def session_limits(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The limits a session is opened with, each stated, positive and within ``SESSION_MAXIMA``.

    Counts are whole numbers; ``usd`` is a decimal string of at most eight decimal places, kept at
    the ledger's quantum. Refused ``invalid_session_limits`` otherwise.
    """

    def refuse(detail: str) -> SessionRefused:
        return SessionRefused("invalid_session_limits", detail)

    if not isinstance(raw, Mapping) or set(raw) != set(SESSION_MAXIMA):
        raise refuse(f"a session states exactly {', '.join(sorted(SESSION_MAXIMA))}")
    limits: dict[str, Any] = {}
    for key in _COUNTS:
        value = raw[key]
        if type(value) is not int or not 1 <= value <= SESSION_MAXIMA[key]:
            raise refuse(f"{key} is a whole number from 1 to {SESSION_MAXIMA[key]}")
        limits[key] = value
    usd = raw["usd"]
    if not isinstance(usd, str) or not _USD.match(usd):
        raise refuse("usd is a decimal string with at most eight decimal places")
    try:
        amount = Decimal(usd)
    except InvalidOperation:
        raise refuse("usd is a decimal string with at most eight decimal places") from None
    if not Decimal(0) < amount <= SESSION_MAXIMA["usd"]:
        raise refuse(f"usd is more than 0 and at most {SESSION_MAXIMA['usd']}")
    limits["usd"] = usd_string(amount)
    return limits


_OPENED_FIELDS: Final = (
    "request_id",
    "reason",
    "opened_by",
    "limits",
    "start_tick",
    "start_state_sha256",
    "opened_at",
    "ends_by",
)
_CLOSED_FIELDS: Final = (
    "reason",
    "closed_by",
    "end_tick",
    "end_state_sha256",
    "closed_at",
)


def _view(opened: Mapping[str, Any], closed: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "profile": SESSION_PROFILE,
        "session_id": opened["session_id"],
        "state": "open" if closed is None else "closed",
        "opened": {
            "event_seq": opened["event_seq"],
            **{key: opened.get(key) for key in _OPENED_FIELDS},
        },
        "closed": None
        if closed is None
        else {
            "event_seq": closed["event_seq"],
            **{key: closed[key] for key in _CLOSED_FIELDS},
            # Why it closed, in the one wording a page and a pull request read.
            "words": closed_words(closed["reason"]),
        },
    }


def sessions_from(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every session the receipts record, newest first, each open until its closing receipt.

    ``receipts`` are a society's playback receipts in any order; only session receipts are read.
    A history that closes a session it did not open, or opens one while another is open, is not
    one the repository writes, and is refused rather than read around.
    """
    ordered = sorted(
        (one for one in receipts if one.get("kind") in SESSION_KINDS),
        key=lambda one: one["event_seq"],
    )
    found: list[dict[str, Any]] = []
    open_one: Mapping[str, Any] | None = None
    for receipt in ordered:
        if receipt["kind"] == SESSION_OPENED:
            if open_one is not None:
                raise ValueError("a session opened while another was open")
            open_one = receipt
            continue
        if open_one is None or open_one["session_id"] != receipt["session_id"]:
            raise ValueError("a session closed that was not open")
        found.append(_view(open_one, receipt))
        open_one = None
    if open_one is not None:
        found.append(_view(open_one, None))
    return found[::-1]


#: The most decisions a session's read returns and measures, its latest: a read that does not
#: grow with a long session's people. The read states how many it counted.
SESSION_DECISIONS_READ: Final = 2000

#: Why a session closes at one of its limits, in the order they are checked before each minute.
SESSION_LIMIT_REASONS: Final = (
    "session_deadline",
    "session_minutes",
    "session_decisions",
    "session_spending_limit",
    "session_liability_unknown",
)
#: The limit the worker's reaper closes a session by, where no claim found it past its deadline.
SESSION_DEADLINE: Final = SESSION_LIMIT_REASONS[0]
#: A person ended the session: stopped it, or paused the world it played.
STOPPED_BY_PERSON: Final = "stopped_by_person"
PAUSED_BY_PERSON: Final = "paused_by_person"
#: The pauses the system makes for an error, each closing the open session by its own reason:
#: claims kept being lost, the world's source could not be read, or its state could not be used.
LEASE_RECOVERY_LIMIT: Final = "lease_recovery_limit"
SOURCE_UNAVAILABLE: Final = "source_unavailable"
INVALID_SOCIETY_STATE: Final = "invalid_society_state"
#: Every reason a session is closed with.
SESSION_CLOSE_REASONS: Final = (
    STOPPED_BY_PERSON,
    PAUSED_BY_PERSON,
    *SESSION_LIMIT_REASONS,
    LEASE_RECOVERY_LIMIT,
    SOURCE_UNAVAILABLE,
    INVALID_SOCIETY_STATE,
)

#: Why a session closed, in words, by its reason: the one wording a page and a project's pull
#: request read. Every reason in ``SESSION_CLOSE_REASONS`` has its words here, which a test holds.
SESSION_CLOSED_WORDS: Final[Mapping[str, str]] = {
    "stopped_by_person": "Someone stopped the session.",
    "paused_by_person": "Someone paused the world, which ended the session.",
    "session_deadline": "The session reached its time limit.",
    "session_minutes": "The session played all the minutes it was given.",
    "session_decisions": "The session used all the model decisions it was given.",
    "session_spending_limit": "The session's spending allowance ran out.",
    "session_liability_unknown": (
        "A model call's cost is not known yet, so the session stopped until it is settled."
    ),
    "lease_recovery_limit": "Playback stopped after it was interrupted too many times.",
    "source_unavailable": "Playback stopped because the world's source could not be read.",
    "invalid_society_state": "Playback stopped because the world's state could not be used.",
}
#: Said of a reason without words of its own. A session is never left open for want of words: it
#: closes, and the missing words are logged when it does.
UNWORDED_CLOSE: Final = "The session ended."


def closed_words(reason: str) -> str:
    """The words for why a session closed, or ``UNWORDED_CLOSE`` for a reason that has none."""
    return SESSION_CLOSED_WORDS.get(reason, UNWORDED_CLOSE)


#: A session's decisions: the receipts of the requests asked for its minutes, from ``start`` up to
#: ``end`` (none while open).
_SESSION_DECISIONS: Final = """
  from world_society_decision d
  join world_society_decision_request r using (workspace_id, society_id, request_id)
 where d.workspace_id = %(workspace)s and d.society_id = %(society)s
   and r.base_tick >= %(start)s and (%(end)s::bigint is null or r.base_tick < %(end)s)
"""
#: Of those, a model decision: a request asked of a model (a person playing a being, or an outside
#: program, names its kind in the request, as :func:`~exulanica.world.deciders.is_person_ask` and
#: :func:`~exulanica.world.deciders.is_external` read it; a model's names none).
_ASKED_A_MODEL: Final = (
    "coalesce(r.document->'provider_config'->>'kind', '') not in ('external', 'person')"
)
_DECISIONS: Final = (
    f"select count(*) filter (where {_ASKED_A_MODEL}) as decisions, "
    f"count(*) filter (where {_ASKED_A_MODEL} "
    "and d.document->>'reason' = 'spending_limit_reached') as refused, "
    "count(*) as total" + _SESSION_DECISIONS
)
_UNKNOWN: Final = """
select 1
  from spending_reservation v
  join spending_grant g on g.workspace_id = v.workspace_id and g.grant_id = v.bound_id
 where v.workspace_id = %s and v.state = 'unknown' and starts_with(g.bound_key, %s)
 limit 1
"""
#: Each bound a session's key names, with what it committed and what its reservations hold. A
#: dispatched attempt older than ``UNRESOLVED_AFTER`` is unresolved, as the workspace's spending
#: read says it.
_BOUNDS: Final = """
select g.grant_id, g.bound_key, g.ceiling_usd, g.max_calls, g.valid_until,
       gs.committed_usd, gs.committed_calls,
       exists (select 1 from spending_grant_revocation v
                where v.workspace_id = g.workspace_id and v.grant_id = g.grant_id) as closed,
       coalesce(sum(x.reserved_usd) filter (
         where x.state = 'admitted'
            or (x.state = 'dispatched' and x.dispatched_at > %(horizon)s)), 0) as in_flight_usd,
       count(x.reservation_id) filter (
         where x.state = 'unknown'
            or (x.state = 'dispatched' and x.dispatched_at <= %(horizon)s)) as unresolved_count,
       coalesce(sum(case when x.state = 'unknown' then x.settled_usd
                         when x.state = 'dispatched' and x.dispatched_at <= %(horizon)s
                         then x.reserved_usd end), 0) as unresolved_usd,
       coalesce(sum(x.settled_usd) filter (where x.state = 'settled'), 0) as known_usage_usd,
       coalesce(sum(x.settled_usd) filter (where x.state = 'reconciled'), 0) as reconciled_usd
  from spending_grant g
  join spending_grant_state gs on gs.workspace_id = g.workspace_id and gs.grant_id = g.grant_id
  left join spending_reservation x on x.workspace_id = g.workspace_id and x.bound_id = g.grant_id
 where g.workspace_id = %(workspace)s and g.parent_grant_id is not null
   and starts_with(g.bound_key, %(prefix)s)
 group by g.workspace_id, g.grant_id, g.bound_key, g.ceiling_usd, g.max_calls, g.valid_until,
          gs.committed_usd, gs.committed_calls
 order by g.bound_key
"""


def model_decisions(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    start_tick: int,
    end_tick: int | None = None,
) -> dict[str, int]:
    """How many model decisions a session asked (``decisions``), how many of them were refused
    because a spending bound had nothing left (``refused``), and how many decisions it holds of
    every decider (``total``): the receipts of the requests asked for its minutes, from
    ``start_tick`` up to ``end_tick`` (none while it is open). A request asked for a minute a
    closed session did not play belongs to the session that plays it. Counted in the database, so
    a read polled each second loads no receipt. Read on a connection scoped to the workspace."""
    row = (
        connection.cursor(row_factory=dict_row)
        .execute(
            _DECISIONS,
            {
                "workspace": workspace_id,
                "society": society_id,
                "start": start_tick,
                "end": end_tick,
            },
        )
        .fetchone()
    )
    assert row is not None
    return {key: int(row[key]) for key in ("decisions", "refused", "total")}


def decisions_left(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    opened: Mapping[str, Any],
) -> int:
    """How many model decisions the open session may still ask for."""
    used = model_decisions(connection, workspace_id, society_id, opened["start_tick"])
    return max(0, int(opened["limits"]["decisions"]) - used["decisions"])


def session_bounds(
    connection: psycopg.Connection, workspace_id: uuid.UUID, session_id: str, now: dt.datetime
) -> list[dict[str, Any]]:
    """Each provider's bound of a session, by provider: its ceiling and calls, what it committed
    (charged, holds included), what its reservations hold in flight, unresolved (an attempt that
    may have cost what is not known, until an operator reconciles it), settled at known usage and
    reconciled, and whether it is still ``open`` or ``closed``. Amounts are decimal strings at the
    ledger's eight places. Read on a connection scoped to the workspace."""
    prefix = f"living-session:{session_id}:"
    rows = (
        connection.cursor(row_factory=dict_row)
        .execute(
            _BOUNDS,
            {"workspace": workspace_id, "prefix": prefix, "horizon": now - UNRESOLVED_AFTER},
        )
        .fetchall()
    )
    return [
        {
            "provider": row["bound_key"].removeprefix(prefix),
            "bound_id": str(row["grant_id"]),
            "state": "closed" if row["closed"] else "open",
            "ceiling_usd": usd_string(row["ceiling_usd"]),
            "max_calls": row["max_calls"],
            "valid_until": row["valid_until"].isoformat(),
            "committed_usd": usd_string(row["committed_usd"]),
            "committed_calls": row["committed_calls"],
            "in_flight_usd": usd_string(row["in_flight_usd"]),
            "unresolved": {
                "count": int(row["unresolved_count"]),
                "usd": usd_string(row["unresolved_usd"]),
            },
            "known_usage_usd": usd_string(row["known_usage_usd"]),
            "reconciled_usd": usd_string(row["reconciled_usd"]),
        }
        for row in rows
    ]


def session_used(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society: Mapping[str, Any],
    view: Mapping[str, Any],
    now: dt.datetime,
    bounds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """What a session (``view``, as :func:`sessions_from` reads it) has used of each of its limits:
    wall seconds since it opened (until it closed), minutes played, model decisions asked, and
    usd and calls its bounds committed, with what is unresolved among them. An open session's
    minutes run to ``society``'s current tick; a closed one's to the tick it ended at.
    ``bounds`` is :func:`session_bounds` where the caller read it already."""
    opened, closed = view["opened"], view["closed"]
    since = dt.datetime.fromisoformat(opened["opened_at"])
    until = now if closed is None else dt.datetime.fromisoformat(closed["closed_at"])
    end_tick = None if closed is None else closed["end_tick"]
    if bounds is None:
        bounds = session_bounds(connection, workspace_id, view["session_id"], now)
    asked = model_decisions(
        connection, workspace_id, society["society_id"], opened["start_tick"], end_tick
    )
    return {
        "wall_seconds": max(0, int((until - since).total_seconds())),
        "minutes": (society["current_tick"] if end_tick is None else end_tick)
        - opened["start_tick"],
        "decisions": asked["decisions"],
        "usd": usd_string(sum((Decimal(one["committed_usd"]) for one in bounds), Decimal(0))),
        "calls": sum(int(one["committed_calls"]) for one in bounds),
        "unresolved": {
            "count": sum(int(one["unresolved"]["count"]) for one in bounds),
            "usd": usd_string(
                sum((Decimal(one["unresolved"]["usd"]) for one in bounds), Decimal(0))
            ),
        },
    }


def limit_reached(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society: Mapping[str, Any],
    opened: Mapping[str, Any],
    now: dt.datetime,
) -> str | None:
    """The first of ``SESSION_LIMIT_REASONS`` that holds for the open session ``opened`` of
    ``society`` (its row: ``society_id``, ``current_tick``) at ``now``, or None while none does.

    Its wall deadline passed; its minutes are played; its decisions are asked; a decision of it was
    refused because its bound (or the grant under it) had nothing left; or a call under its bound
    may have cost what is not known, which only an operator's reconciliation settles.
    """
    limits = opened["limits"]
    if now >= dt.datetime.fromisoformat(opened["ends_by"]):
        return "session_deadline"
    if society["current_tick"] - opened["start_tick"] >= int(limits["minutes"]):
        return "session_minutes"
    asked = model_decisions(connection, workspace_id, society["society_id"], opened["start_tick"])
    if asked["decisions"] >= int(limits["decisions"]):
        return "session_decisions"
    if asked["refused"]:
        return "session_spending_limit"
    prefix = f"living-session:{opened['session_id']}:"
    if connection.execute(_UNKNOWN, (workspace_id, prefix)).fetchone() is not None:
        return "session_liability_unknown"
    return None
