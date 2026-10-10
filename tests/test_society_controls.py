"""Pure scheduling arithmetic and bounded host loop, not database evidence."""

import datetime as dt
import threading
import uuid

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.world.society_controls import playing_due_at, ticks_due, validate_settings


def test_due_boundary_keeps_integer_clock_precision():
    due = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    assert ticks_due(due - dt.timedelta(microseconds=1), due, 250) == 0
    assert ticks_due(due, due, 250) == 1
    assert ticks_due(due + dt.timedelta(microseconds=249999), due, 250) == 1
    assert ticks_due(due + dt.timedelta(milliseconds=250), due, 250) == 2
    assert ticks_due(due + dt.timedelta(days=40), due, 250) == 13_824_001


def test_a_society_set_playing_is_due_an_interval_after_its_last_minute_and_never_before_now():
    # The last minute: an automatic batch's completion, or a manual step's record.
    batch = dt.datetime(2026, 9, 13, 12, 0, 0, 123456, tzinfo=dt.UTC)
    one = dt.timedelta(microseconds=1)
    # Never advanced: at once, whatever the interval.
    assert playing_due_at(batch, None, 60000) == batch
    # Inside the interval after the batch: when that interval ends, to the microsecond.
    for since in (dt.timedelta(0), dt.timedelta(seconds=1), dt.timedelta(seconds=30)):
        assert playing_due_at(batch + since, batch, 60000) == dt.datetime(
            2026, 9, 13, 12, 1, 0, 123456, tzinfo=dt.UTC
        )
    assert playing_due_at(batch + dt.timedelta(seconds=60) - one, batch, 60000) == (
        batch + dt.timedelta(seconds=60)
    )
    # The interval over, by nothing or by a day: now, and the minute it is then owed is one.
    for since in (dt.timedelta(seconds=60), dt.timedelta(seconds=60) + one, dt.timedelta(days=1)):
        due = playing_due_at(batch + since, batch, 60000)
        assert due == batch + since
        assert ticks_due(batch + since, due, 60000) == 1
    # Another speed is another interval from the same batch: 8 s at 1x, 2 s at 4x.
    at = batch + dt.timedelta(milliseconds=1500)
    assert playing_due_at(at, batch, 8000) == batch + dt.timedelta(seconds=8)
    assert playing_due_at(at, batch, 2000) == batch + dt.timedelta(seconds=2)
    assert playing_due_at(at + dt.timedelta(seconds=1), batch, 2000) == at + dt.timedelta(seconds=1)
    # The same instants read in another time zone are the same instants.
    east = dt.timezone(dt.timedelta(hours=-4))
    assert playing_due_at(at.astimezone(east), batch, 8000) == batch + dt.timedelta(seconds=8)


@pytest.mark.parametrize(
    "mode,speed,interval",
    [
        ("playing", True, 1000),
        ("playing", 3, 1000),
        ("playing", 1, 999),
        ("playing", 1, 1001),
        ("playing", 1, 60004),
        ("unknown", 1, 1000),
    ],
)
def test_unsupported_timing_is_rejected(mode, speed, interval):
    with pytest.raises(ValueError):
        validate_settings(mode, speed, interval)


def test_host_loop_considers_each_workspace_once_per_round(monkeypatch):
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    worker = SocietyControlWorker(None, runtime=None, workspaces=[second, first, first])
    calls = []
    stop = threading.Event()

    def run_once(workspace):
        calls.append(workspace)
        if workspace == second:
            stop.set()
        return {"receipt": {"executed_ticks": 3}}

    monkeypatch.setattr(worker, "run_once", run_once)
    worker.run(stop)
    assert calls == [first, second]
    with pytest.raises(ValueError, match="not configured"):
        SocietyControlWorker(None, runtime=None, workspaces=[]).run_once(first)
