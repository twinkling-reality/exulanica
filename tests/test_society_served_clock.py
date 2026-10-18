"""A society of things that keeps no clock of its own is served one beside its state.

The time of day is the day its people start at, as its first input's people frame states it
(``day.start_minute_of_day``), plus the state's minute: the minute of the day and the day, counted
from 0, as a resident day keeps its own clock. Nothing of it is stored, so the state and its digest
are served as they are. The reads here are synthetic: the repository's read is asked over a fake
connection that answers the first input's start minute, or nothing.
"""

from __future__ import annotations

from typing import Any

from exulanica.world.society import served_clock, served_snapshot
from exulanica.world.society_repository_reads import PEOPLE_DAY_START_SQL, SocietyReads

THINGS = "exulanica-society/v7"
PURPOSEFUL = "exulanica-society/v2"


def test_the_clock_is_the_start_of_the_day_plus_the_minute_and_wraps_into_the_next_day():
    assert served_clock(360, 0) == {"start_minute_of_day": 360, "minute_of_day": 360, "day": 0}
    assert served_clock(360, 1079) == {"start_minute_of_day": 360, "minute_of_day": 1439, "day": 0}
    assert served_clock(360, 1080) == {"start_minute_of_day": 360, "minute_of_day": 0, "day": 1}
    assert served_clock(0, 2 * 1440 + 7) == {"start_minute_of_day": 0, "minute_of_day": 7, "day": 2}


class _Answer:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class _Connection:
    """Answers the first input's start minute, and counts what it was asked."""

    def __init__(self, start: Any) -> None:
        self.start = start
        self.asked: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, parameters: tuple[Any, ...]) -> _Answer:
        self.asked.append((sql, parameters))
        return _Answer(None if self.start is _NO_INPUT else {"start": self.start})


_NO_INPUT = object()


class _Reads(SocietyReads):
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.workspace_id = "workspace"


def _row(profile: str = THINGS, *, tick: int = 47, clock: dict[str, int] | None = None) -> dict:
    state: dict[str, Any] = {"profile": profile, "tick": tick, "inhabitants": []}
    if clock is not None:
        state["clock"] = clock
    return {
        "engine_version": profile,
        "society_id": "society",
        "current_tick": tick,
        "state": state,
    }


def test_a_society_of_things_is_served_the_clock_its_first_inputs_people_start_their_day_at():
    connection = _Connection(360)
    assert _Reads(connection)._served_clock(_row()) == served_clock(360, 47)
    # One read of that one value of the first input, and nothing else of it.
    assert connection.asked == [(PEOPLE_DAY_START_SQL, ("workspace", "society"))]
    assert "input_seq=1" in PEOPLE_DAY_START_SQL
    assert "document->'people'->'day'->'start_minute_of_day'" in PEOPLE_DAY_START_SQL


def test_none_where_the_first_input_carries_no_people_or_the_state_keeps_its_own_or_not_of_things():
    for start in (None, _NO_INPUT, "360", 360.0):
        assert _Reads(_Connection(start))._served_clock(_row()) is None
    own = served_clock(300, 47)
    asked = _Connection(360)
    assert _Reads(asked)._served_clock(_row(clock=own)) is None
    assert _Reads(asked)._served_clock(_row(PURPOSEFUL)) is None
    assert asked.asked == []


def test_the_clock_is_served_beside_the_state_and_the_state_is_served_as_it_is():
    state = {"profile": THINGS, "tick": 47, "inhabitants": []}
    snapshot = {"seed": "a" * 64, "state": state, "state_sha256": "b" * 64}
    served = served_snapshot(snapshot | {"clock": served_clock(360, 47)})
    assert served["clock"] == {"start_minute_of_day": 360, "minute_of_day": 407, "day": 0}
    assert served["state"] == state and "clock" not in served["state"]
    assert served["state_sha256"] == "b" * 64
    assert "clock" not in served_snapshot(snapshot)
