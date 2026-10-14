"""A living session's limits and how its receipts are read back, without a database.

A session is two receipts of a society's playback history (``session_opened`` and
``session_closed``); these tests hold the limits a session may be opened with and the reading of
sessions from receipts, with receipts written by hand in their stored shape.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.society_sessions import (
    SESSION_MAXIMA,
    SESSION_PROFILE,
    SessionRefused,
    session_limits,
    sessions_from,
)

LIMITS = {"wall_seconds": 600, "minutes": 30, "decisions": 10, "usd": "0.25", "calls": 100}


def test_limits_are_every_figure_positive_and_within_the_installation_s_maxima() -> None:
    assert session_limits(LIMITS) == {**LIMITS, "usd": "0.25000000"}
    assert session_limits({**LIMITS, "usd": "1"})["usd"] == "1.00000000"
    for wrong in (
        {k: v for k, v in LIMITS.items() if k != "decisions"},
        {**LIMITS, "extra": 1},
        {**LIMITS, "minutes": 0},
        {**LIMITS, "calls": True},
        {**LIMITS, "wall_seconds": 1.5},
        {**LIMITS, "wall_seconds": SESSION_MAXIMA["wall_seconds"] + 1},
        {**LIMITS, "usd": "0"},
        {**LIMITS, "usd": "-1"},
        {**LIMITS, "usd": "0.000000001"},
        {**LIMITS, "usd": 0.25},
        {**LIMITS, "usd": "1e-3"},
        {**LIMITS, "usd": str(SESSION_MAXIMA["usd"] + 1)},
    ):
        with pytest.raises(SessionRefused) as refused:
            session_limits(wrong)
        assert refused.value.code == "invalid_session_limits"


def _opened(seq: int, session: str, **more: object) -> dict:
    return {
        "kind": "session_opened",
        "event_seq": seq,
        "session_id": session,
        "request_id": str(uuid.uuid4()),
        "opened_by": "a" * 8,
        "limits": {**LIMITS, "usd": "0.25000000"},
        "start_tick": 3,
        "start_state_sha256": "1" * 64,
        "opened_at": "2026-10-14T00:00:00Z",
        "ends_by": "2026-10-14T00:10:00Z",
        **more,
    }


def _closed(seq: int, session: str, reason: str = "stopped_by_person") -> dict:
    return {
        "kind": "session_closed",
        "event_seq": seq,
        "session_id": session,
        "reason": reason,
        "closed_by": None,
        "end_tick": 9,
        "end_state_sha256": "2" * 64,
        "closed_at": "2026-10-14T00:05:00Z",
    }


def test_sessions_are_read_from_their_receipts_newest_first_open_until_closed() -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    receipts = [
        {"kind": "configured", "event_seq": 1},
        _opened(2, first),
        {"kind": "advanced", "event_seq": 3},
        _closed(4, first, "paused_by_person"),
        _opened(5, second),
    ]
    found = sessions_from(receipts)
    assert [(one["session_id"], one["state"]) for one in found] == [
        (second, "open"),
        (first, "closed"),
    ]
    assert found[0]["profile"] == SESSION_PROFILE and found[0]["closed"] is None
    assert found[1]["closed"]["reason"] == "paused_by_person"
    assert found[1]["opened"]["start_tick"] == 3 and found[1]["closed"]["end_tick"] == 9


def test_a_history_that_closes_what_it_never_opened_or_opens_twice_is_refused() -> None:
    one, other = str(uuid.uuid4()), str(uuid.uuid4())
    for broken in (
        [_closed(1, one)],
        [_opened(1, one), _opened(2, other)],
        [_opened(1, one), _closed(2, other)],
        [_opened(1, one), _closed(2, one), _closed(3, one)],
    ):
        with pytest.raises(ValueError):
            sessions_from(broken)
