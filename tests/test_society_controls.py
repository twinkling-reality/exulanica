"""Pure scheduling arithmetic and bounded host loop, not database evidence."""

import datetime as dt
import threading
import uuid

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.world.society_controls import ticks_due, validate_settings


def test_due_boundary_keeps_integer_clock_precision():
    due = dt.datetime(2026, 9, 13, tzinfo=dt.UTC)
    assert ticks_due(due - dt.timedelta(microseconds=1), due, 250) == 0
    assert ticks_due(due, due, 250) == 1
    assert ticks_due(due + dt.timedelta(microseconds=249999), due, 250) == 1
    assert ticks_due(due + dt.timedelta(milliseconds=250), due, 250) == 2
    assert ticks_due(due + dt.timedelta(days=40), due, 250) == 13_824_001


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
