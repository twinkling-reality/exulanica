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

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from exulanica.models.usage import usd_string

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
            **{key: opened[key] for key in _OPENED_FIELDS},
        },
        "closed": None
        if closed is None
        else {"event_seq": closed["event_seq"], **{key: closed[key] for key in _CLOSED_FIELDS}},
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
