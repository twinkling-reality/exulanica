"""A living session's limits and how its receipts are read back, without a database.

A session is two receipts of a society's playback history (``session_opened`` and
``session_closed``); these tests hold the limits a session may be opened with and the reading of
sessions from receipts, with receipts written by hand in their stored shape.
"""

from __future__ import annotations

import ast
import inspect
import uuid

import exulanica.world.society_control_repository as repository_module
import exulanica.world.society_sessions as sessions_module
import pytest
from exulanica.world.society_sessions import (
    SESSION_CLOSE_REASONS,
    SESSION_CLOSED_WORDS,
    SESSION_LIMIT_REASONS,
    SESSION_MAXIMA,
    SESSION_PROFILE,
    UNWORDED_CLOSE,
    SessionRefused,
    closed_words,
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


#: The repository's ways to close a session, and which argument of each names the reason.
_CLOSERS = {"_close_session": "reason", "_pause_for_session": 2, "_pause_error": 1}


def _closing_reasons(source: str) -> list[ast.expr]:
    """Every expression the source passes as a session's closing reason."""
    found: list[ast.expr] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", None))
        where = _CLOSERS.get(name)
        if isinstance(where, int) and len(node.args) > where:
            found.append(node.args[where])
        found += [
            keyword.value
            for keyword in node.keywords
            if keyword.arg == "closing_reason" or (where == "reason" and keyword.arg == "reason")
        ]
    found += [
        default
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
        for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if argument.arg == "closing_reason" and default is not None
    ]
    return found


def test_every_reason_a_session_closes_with_has_words_and_a_new_one_cannot_go_unworded() -> None:
    # One wording, for exactly the reasons a session closes with, each a plain sentence.
    assert set(SESSION_CLOSED_WORDS) == set(SESSION_CLOSE_REASONS)
    assert len(SESSION_CLOSE_REASONS) == len(set(SESSION_CLOSE_REASONS))
    for code, words in SESSION_CLOSED_WORDS.items():
        assert words.endswith(".") and "_" not in words and code not in words
    assert closed_words("session_minutes") == SESSION_CLOSED_WORDS["session_minutes"]
    assert closed_words("a_reason_nobody_worded") == UNWORDED_CLOSE
    # The repository names every closing reason it writes by a name this module words, never by a
    # bare string a test could not see; the reasons it passes on unnamed are its own parameters.
    reasons = _closing_reasons(inspect.getsource(repository_module))
    assert len(reasons) >= 6, "the reading finds the repository's closing calls"
    for reason in reasons:
        assert not isinstance(reason, ast.Constant), ast.unparse(reason)
        if isinstance(reason, ast.Name) and reason.id.isupper():
            assert getattr(sessions_module, reason.id) in SESSION_CLOSED_WORDS, reason.id
        else:
            assert isinstance(reason, ast.Name) and reason.id in {"reason", "closing_reason"}, (
                ast.unparse(reason)
            )
    # A limit closes a session by the reason the limit check answers: one of the limit reasons.
    returned = {
        node.value.value
        for node in ast.walk(ast.parse(inspect.getsource(sessions_module.limit_reached)))
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and node.value.value is not None
    }
    assert returned == set(SESSION_LIMIT_REASONS)


def test_a_closed_session_reads_with_its_reason_in_words() -> None:
    session = str(uuid.uuid4())
    opened = {"kind": "session_opened", "event_seq": 1, "session_id": session, "limits": LIMITS}
    closed = {
        "kind": "session_closed",
        "event_seq": 2,
        "session_id": session,
        "reason": "session_minutes",
        "closed_by": None,
        "end_tick": 3,
        "end_state_sha256": "a" * 64,
        "closed_at": "2026-10-14T00:00:00+00:00",
    }
    [read] = sessions_from([opened, closed])
    assert read["closed"]["words"] == SESSION_CLOSED_WORDS["session_minutes"]
    [unworded] = sessions_from([opened, {**closed, "reason": "a_reason_nobody_worded"}])
    assert unworded["closed"]["reason"] == "a_reason_nobody_worded"
    assert unworded["closed"]["words"] == UNWORDED_CLOSE
