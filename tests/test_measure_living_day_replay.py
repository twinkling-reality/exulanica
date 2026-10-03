"""The living town's day measurement plays a day hour by hour, seals each hour as a host seals it,
reads every hour as the run route reads one and the day as the day route does, and fits its line
on each point's dearest read.

A small town's day of two hours stands in for the day here, so the test plays in seconds; the
measurement itself reads the protocol's day.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.world.society_catalogs import comparison_catalogs_for_engine
from exulanica.world.society_comparison import HOUR_TICKS
from exulanica.world.society_living import LIVING_TOWN_PROFILE

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_living_day_replay as measure

CATALOGS = comparison_catalogs_for_engine(LIVING_TOWN_PROFILE, "day")


@pytest.fixture(name="world", scope="module")
def _world():
    return measure.hour_line.compose("small_town", 0)


@pytest.mark.parametrize(
    ("timed", "dearest"),
    [
        ((100, 300, 200), {"p95": 300, "from": "hour", "hour": 1}),
        ((100, 300, 500), {"p95": 500, "from": "day", "hour": 1}),
    ],
    ids=["an-hour", "the-day"],
)
def test_a_point_reads_every_hour_and_the_day_and_keeps_the_dearest(
    world, monkeypatch, timed, dearest
):
    # Every read is made once, as measured, and timed as stated: the first hour, the second, then
    # the day, so which read is the dearest is the test's to say.
    stated = iter(timed)

    def reads(action, repeats):
        body = action()
        wall_us = next(stated)
        return body, {"min": wall_us, "median": wall_us, "p95": wall_us, "max": wall_us}

    monkeypatch.setattr(measure, "_reads", reads)
    found = measure.point(world, 4, 1, 2 * HOUR_TICKS, CATALOGS)
    assert [hour["hour"] for hour in found["hours"]] == [0, 1]
    # The second hour starts from the state the first sealed, read from its stored bytes.
    assert found["hours"][0]["state_bytes"] == 0 < found["hours"][1]["state_bytes"]
    assert found["read_wall_us"] == dearest
    assert found["day_body_bytes"] > 0
    assert (found["population"], found["decided"]) == (world["population"], 4)


def test_an_hour_that_does_not_replay_to_its_seal_stops_the_measurement(world, monkeypatch):
    monkeypatch.setattr(measure, "hour_events_sha256", lambda _played: "f" * 64)
    with pytest.raises(SystemExit, match="does not replay to what it sealed"):
        measure.point(world, 0, 1, HOUR_TICKS, CATALOGS)


def test_the_bound_a_day_line_derives_reads_the_days_pair_budget():
    line = {
        "replay_fixed_ms": 25,
        "replay_per_person_us": 10_000,
        "replay_per_decided_person_us": 1_000,
        "replay_per_decided_pair_us": 100,
    }
    derived = measure._derived(line, [38, 52], CATALOGS)
    assert derived["pair_replay_budget_ms"] == measure.protocol_value(
        CATALOGS, "pair_replay_budget_ms"
    )
    assert derived["run_budget_us"] == derived["pair_replay_budget_ms"] * 1000 // 2
    assert [found["population"] for found in derived["decided_most"]] == [38, 52, 128]


def test_a_run_is_gated_unless_it_is_a_smoke_run_and_a_smoke_record_is_discarded():
    low = measure.IDLE_BEFORE_PERCENT - 1
    assert measure.refusal(low, smoke=False).startswith("refused")
    assert measure.refusal(measure.IDLE_BEFORE_PERCENT, smoke=False) is None
    assert measure.refusal(low, smoke=True) is None
    assert measure.refusal(None, smoke=False) is None
    least = Decimal(str(measure.IDLE_MEAN_PERCENT))
    assert measure.discarded(least - 1, smoke=False) is True
    assert measure.discarded(least, smoke=False) is False
    assert measure.discarded(None, smoke=False) is False
    assert measure.discarded(least + 20, smoke=True) is True


class _Phases:
    """The run's phases recorded in the order they happen, every play, sample and read a fake."""

    def __init__(self, monkeypatch, idle: list[float | None]) -> None:
        self.events: list[str] = []
        self.idle = list(idle)
        monkeypatch.setattr(measure, "play_day", self.play)
        monkeypatch.setattr(measure, "read_day", self.read)
        monkeypatch.setattr(measure, "idle_share", self.sample)
        monkeypatch.setattr(measure, "settled", self.settle)
        monkeypatch.setattr(measure, "load_average", lambda: "load")

    def play(self, world, count, window, catalogs):
        self.events.append("play")
        return (world, count)

    def read(self, day, repeats):
        self.events.append("read")
        world, count = day
        return {
            "graph": world["world_id"],
            "population": world["population"],
            "decided": count,
            "read_wall_us": {"p95": 1},
        }

    def sample(self):
        self.events.append("idle")
        return self.idle.pop(0)

    def settle(self):
        self.events.append("settle")
        return 1.0


#: A town of five, whose points decide for nobody, everybody and a group of four.
TOWN = {"world_id": "world:generated:measured-0", "population": 5}


def _run(**changes):
    arguments = {"repeats": 1, "window": HOUR_TICKS, "catalogs": CATALOGS, "smoke": False}
    return measure.run([TOWN], **(arguments | changes))


def test_the_gate_is_applied_before_the_reads_and_not_before_the_play(monkeypatch):
    phases = _Phases(monkeypatch, [80.0, 75.0])
    measured = _run()
    # Every day is played before the machine is sampled; each read waits for the load first.
    assert phases.events == ["play"] * 3 + ["idle"] + ["settle", "read"] * 3 + ["idle"]
    assert measured["refused"] is None and len(measured["points"]) == 3
    assert measured["phases"]["play"]["gated"] is False
    assert measured["phases"]["gate"]["gated"] is True
    assert measured["phases"]["reads"]["gated"] is True


@pytest.mark.parametrize(("after", "discard"), [(40.0, False), (10.0, True)])
def test_discard_is_computed_over_the_reads_alone(monkeypatch, after, discard):
    phases = _Phases(monkeypatch, [80.0, after])
    measured = _run()
    reads = measured["phases"]["reads"]
    assert (reads["idle_percent_before"], reads["idle_percent_after"]) == ("80.0", str(after))
    assert measured["discard"] is discard
    assert phases.events.count("idle") == 2


def test_a_smoke_run_waits_for_no_gate_and_is_discarded(monkeypatch):
    # The gate would refuse the first sample, and the mean, 52.5, would not discard the record:
    # what admits the reads and discards the record is the smoke run alone.
    phases = _Phases(monkeypatch, [5.0, 100.0])
    measured = _run(smoke=True)
    assert "settle" not in phases.events and measured["refused"] is None
    assert measured["discard"] is True
    assert measured["phases"]["gate"]["gated"] is False


def test_the_gate_is_waited_for_and_a_spent_wait_reads_nothing(monkeypatch):
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    shares = iter([60.0, 65.0, 75.0])
    found = measure.wait_for_idle(
        smoke=False,
        wait_seconds=100,
        poll_seconds=20,
        idle=lambda: next(shares),
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert found == (75.0, 40, None)
    phases = _Phases(monkeypatch, [50.0] * 100)
    measured = _run(wait_seconds=0)
    assert measured["refused"].startswith("refused") and measured["points"] == []
    assert "read" not in phases.events and measured["discard"] is True
