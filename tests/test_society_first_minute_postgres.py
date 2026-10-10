"""A society set playing runs its first minute at once, and never faster than its speed after.

PostgreSQL 18 evidence for the deadline a configuration saves (``playing_due_at``): one effective
interval after the society's last minute was advanced, by an automatic batch or by a manual step,
and never before now. Where a test holds the repository's clock, each expected deadline is
arithmetic on that clock, compared with the ``next_due_at`` the control stores.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import (
    BASE_TICK_INTERVAL_MAX_MS,
    DEFAULT_BASE_TICK_INTERVAL_MS,
    LeaseLost,
)

import test_society_runtime as helpers
from test_society_controls_postgres import authorizer, create
from tests_support_api import scratch_database

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres

#: The bases a person meets: the host default, and the longest a host may state, at which a
#: simulated minute at 1x waits the 60 seconds it simulates.
BASES = (DEFAULT_BASE_TICK_INTERVAL_MS, BASE_TICK_INTERVAL_MAX_MS)


def ms(milliseconds: int) -> dt.timedelta:
    return dt.timedelta(milliseconds=milliseconds)


def controls(w, base, connection=None):
    connection = connection or w["connection"]
    return SocietyControlRepository(
        connection,
        w["workspace"],
        world_id=w["version"].world_id,
        base_tick_interval_ms=base,
        input_authorizer=authorizer(w, connection),
    )


def read(w, base):
    return controls(w, base).read(w["binding"].version_id)


def configure(w, base, mode, speed=1):
    """Save the control at its current revision, as Play, Pause or a speed does."""
    return controls(w, base).configure(
        w["binding"].version_id,
        actor=w["session"].actor,
        base_revision=read(w, base)["revision"],
        mode=mode,
        speed=speed,
    )


def stored_due(w):
    """The deadline the control row holds, as the worker's claim query reads it."""
    return (
        w["connection"]
        .execute(
            "select next_due_at from world_society_control where workspace_id=%s",
            (w["workspace"],),
        )
        .fetchone()["next_due_at"]
    )


def take_claim(w, base):
    return SocietyControlRepository.claim_in_workspace(
        w["connection"],
        w["workspace"],
        input_authorizer=authorizer(w, w["connection"]),
        base_tick_interval_ms=base,
    )


def run_batch(w, base):
    """Claim the due society and run its batch, as one worker round does; the batch's receipt."""
    claim = take_claim(w, base)
    assert claim is not None
    return controls(w, base).execute(claim)["receipt"]


def step_by_hand(w, base):
    """One minute by the control's manual step, as Next minute does; the step's receipt."""
    repo = controls(w, base)
    control = read(w, base)
    return repo.manual_step(
        w["binding"].version_id,
        actor=w["session"].actor,
        base_revision=control["revision"],
        base_tick=control["current_tick"],
        base_state_sha256=control["state_sha256"],
    )["receipt"]


def minutes(receipt):
    return receipt["due_ticks"], receipt["executed_ticks"], receipt["skipped_due_ticks"]


def server_now(w):
    return w["connection"].execute("select clock_timestamp() as now").fetchone()["now"]


def worker_for(w, spine_schema, base):
    return SocietyControlWorker(
        scratch_database(spine_schema[1]),
        runtime=w["runtime"],
        workspaces=[w["workspace"]],
        base_tick_interval_ms=base,
    )


class HeldClock:
    """The repository's clock in the test's hands: it moves only when the test moves it."""

    def __init__(self, start: dt.datetime) -> None:
        self.now = start

    def add(self, milliseconds: int) -> dt.datetime:
        self.now += ms(milliseconds)
        return self.now


@pytest.fixture
def clock(runtime_world, monkeypatch):
    # Two days behind the server's clock, so that every deadline this clock sets, a day's pause
    # included, is one the claim query, which reads the server's own clock, finds due.
    start = (
        runtime_world["connection"]
        .execute("select clock_timestamp()-interval '2 days' as start")
        .fetchone()["start"]
    )
    held = HeldClock(start)
    monkeypatch.setattr(SocietyControlRepository, "_now", lambda _self: held.now)
    return held


def take_claim_on(clock, w, base):
    """A worker round on the held clock: the claim query's due test, made on that clock."""
    due = stored_due(w)
    return None if due is None or due > clock.now else take_claim(w, base)


@pytest.mark.parametrize("base", BASES)
def test_a_society_never_advanced_is_due_the_moment_it_is_set_playing(runtime_world, clock, base):
    w = runtime_world
    create(w)
    played = configure(w, base, "playing")
    assert played["last_batch_execution"] is None
    assert stored_due(w) == clock.now
    assert dt.datetime.fromisoformat(played["next_due_at"]) == clock.now
    assert minutes(run_batch(w, base)) == (1, 1, 0)
    # From there the batch leaves the deadline one interval on, as it always has.
    assert stored_due(w) == clock.now + ms(base)


@pytest.mark.parametrize("base", BASES)
def test_played_again_inside_the_interval_after_a_batch_waits_out_that_interval(
    runtime_world, clock, base
):
    w = runtime_world
    create(w)
    configure(w, base, "playing")
    batch_at = clock.now
    run_batch(w, base)
    left_by_the_batch = batch_at + ms(base)
    assert stored_due(w) == left_by_the_batch
    # A second after the minute, half an interval after it, a millisecond before the interval ends.
    for since_batch in (1000, base // 2, base - 1):
        clock.now = batch_at + ms(since_batch)
        assert configure(w, base, "paused")["next_due_at"] is None
        assert stored_due(w) is None
        played = configure(w, base, "playing")
        assert stored_due(w) == left_by_the_batch, since_batch
        assert dt.datetime.fromisoformat(played["next_due_at"]) == left_by_the_batch
        assert take_claim_on(clock, w, base) is None
    receipt = controls(w, base).events(w["binding"].version_id, limit=1)[0]
    assert receipt["kind"] == "configured"
    assert dt.datetime.fromisoformat(receipt["next_due_at"]) == left_by_the_batch


@pytest.mark.parametrize("base", BASES)
def test_played_an_interval_or_more_after_a_batch_is_due_at_once_and_owes_one_minute(
    runtime_world, clock, base
):
    w = runtime_world
    create(w)
    configure(w, base, "playing")
    batch_at = clock.now
    run_batch(w, base)
    # Exactly an interval after the minute, a millisecond past it, and after a day stood paused.
    for since_batch in (base, base + 1, 86_400_000):
        configure(w, base, "paused")
        clock.now = batch_at + ms(since_batch)
        configure(w, base, "playing")
        assert stored_due(w) == clock.now, since_batch
    # The day paused is no debt: the batch owes the one minute, and runs it.
    receipt = run_batch(w, base)
    assert minutes(receipt) == (1, 1, 0)
    assert receipt["tick_to"] == 2
    assert stored_due(w) == clock.now + ms(base)


def test_another_speed_while_playing_times_the_next_batch_from_the_last_one(runtime_world, clock):
    w = runtime_world
    base = 8000  # 1x waits 8,000 ms after a batch, 2x 4,000 ms, 4x 2,000 ms.
    create(w)
    configure(w, base, "playing")
    batch_at = clock.now
    run_batch(w, base)
    # Milliseconds since the batch when a speed is chosen, the speed, and when the next batch is
    # then due, in milliseconds since the batch.
    for since_batch, speed, due in (
        (1000, 4, 2000),  # Up: the 4x wait from the batch, not from the press.
        (1500, 1, 8000),  # Down again: the 1x wait from the batch, whatever was pressed between.
        (1500, 2, 4000),
        (3000, 4, 3000),  # The 4x wait is already over: at once.
        (3000, 2, 4000),
        (5000, 1, 8000),
        (9000, 4, 9000),
        (9000, 1, 9000),  # And the 1x wait is over as well.
    ):
        clock.now = batch_at + ms(since_batch)
        played = configure(w, base, "playing", speed)
        assert played["tick_interval_ms"] == {1: 8000, 2: 4000, 4: 2000}[speed]
        assert stored_due(w) == batch_at + ms(due), (since_batch, speed)


def pressed_every_500_ms(w, clock, base, press, presses=40):
    """Twenty seconds of one press every 500 ms, a worker round before each; the batches run, as
    (milliseconds since the first, the speed it ran at, the minutes it ran)."""
    started = clock.now
    batches = []

    def worker_round():
        claim = take_claim_on(clock, w, base)
        if claim is not None:
            receipt = controls(w, base).execute(claim)["receipt"]
            batches.append(((clock.now - started) // ms(1), receipt["speed"], minutes(receipt)))

    worker_round()
    for count in range(1, presses + 1):
        clock.add(500)
        worker_round()
        press(count)
    return batches


def test_pausing_and_playing_without_rest_runs_no_batch_sooner_than_the_speed_waits(
    runtime_world, clock
):
    w = runtime_world
    base = 8000
    create(w)
    configure(w, base, "playing")
    batches = pressed_every_500_ms(
        w, clock, base, lambda count: configure(w, base, "paused" if count % 2 else "playing")
    )
    # Pause on the odd presses, Play on the even ones. The first batch runs at once. Its 8,000 ms
    # wait ends on a press that plays, so the round 500 ms later runs the second, and that batch's
    # wait ends on a round that finds the world playing: 8,500 ms and 8,000 ms apart, never less.
    assert batches == [(0, 1, (1, 1, 0)), (8500, 1, (1, 1, 0)), (16500, 1, (1, 1, 0))]
    assert read(w, base)["current_tick"] == 3


def test_flipping_the_speed_without_rest_runs_no_batch_sooner_than_the_fastest_speed_waits(
    runtime_world, clock
):
    w = runtime_world
    base = 8000
    create(w)
    configure(w, base, "playing")
    batches = pressed_every_500_ms(
        w, clock, base, lambda count: configure(w, base, "playing", 4 if count % 2 else 1)
    )
    # 4x on the odd presses, 1x on the even ones. A round finds 4x chosen whenever the 4x wait
    # ends, so a batch runs every 2,000 ms: the pace 4x allows, each batch one minute, none sooner.
    assert batches == [(since, 4 if since else 1, (1, 1, 0)) for since in range(0, 20001, 2000)]


@pytest.mark.parametrize("base", BASES)
def test_played_inside_the_interval_after_a_minute_stepped_by_hand_waits_out_that_interval(
    runtime_world, clock, base
):
    w = runtime_world
    create(w)
    stepped_at = clock.now
    assert step_by_hand(w, base)["kind"] == "manual_step"
    # No batch has run: the step is the last minute. A second after it, half an interval after
    # it, a millisecond before the interval ends.
    for since_step in (1000, base // 2, base - 1):
        clock.now = stepped_at + ms(since_step)
        played = configure(w, base, "playing")
        assert played["last_batch_execution"] is None
        assert stored_due(w) == stepped_at + ms(base), since_step
        assert take_claim_on(clock, w, base) is None
        configure(w, base, "paused")
    assert read(w, base)["current_tick"] == 1


@pytest.mark.parametrize("base", BASES)
def test_played_an_interval_or_more_after_a_minute_stepped_by_hand_is_due_at_once(
    runtime_world, clock, base
):
    w = runtime_world
    create(w)
    stepped_at = clock.now
    step_by_hand(w, base)
    # Exactly an interval after the step, a millisecond past it, and after a day stood paused.
    for since_step in (base, base + 1, 86_400_000):
        clock.now = stepped_at + ms(since_step)
        configure(w, base, "playing")
        assert stored_due(w) == clock.now, since_step
        configure(w, base, "paused")
    configure(w, base, "playing")
    receipt = run_batch(w, base)
    assert minutes(receipt) == (1, 1, 0) and receipt["tick_to"] == 2


def test_the_last_minute_is_the_newer_of_the_last_batch_and_the_last_step(runtime_world, clock):
    w = runtime_world
    base = 8000  # 1x waits 8,000 ms after a minute, 4x 2,000 ms.
    create(w)
    configure(w, base, "playing")
    batch_at = clock.now
    run_batch(w, base)
    # A step after the batch: the step is the last minute, at any speed chosen after it.
    clock.add(1000)
    configure(w, base, "paused")
    clock.add(2000)
    stepped_at = clock.now
    step_by_hand(w, base)
    clock.add(1000)
    configure(w, base, "playing", 4)
    assert stored_due(w) == stepped_at + ms(2000)
    configure(w, base, "playing", 1)
    assert stored_due(w) == stepped_at + ms(8000)
    assert stepped_at + ms(8000) == batch_at + ms(11_000)
    # A batch after the step: the batch is the last minute again.
    clock.now = stepped_at + ms(8000)
    second_batch_at = clock.now
    receipt = run_batch(w, base)
    assert minutes(receipt) == (1, 1, 0) and receipt["tick_to"] == 3
    clock.add(1000)
    configure(w, base, "paused")
    configure(w, base, "playing")
    assert stored_due(w) == second_batch_at + ms(8000)


def test_play_right_after_a_minute_stepped_by_hand_runs_no_minute_before_its_interval_ends(
    runtime_world, spine_schema
):
    """On the server's own clock, with the real worker, at a base of 60 s."""
    w = runtime_world
    base = 60_000
    create(w)
    worker = worker_for(w, spine_schema, base)
    stepped = dt.datetime.fromisoformat(step_by_hand(w, base)["recorded_at"])
    configure(w, base, "playing")
    assert stored_due(w) == stepped + ms(60_000)
    assert worker.run_once(w["workspace"]) is None
    assert read(w, base)["current_tick"] == 1
    assert server_now(w) < stepped + ms(60_000)


def test_a_claim_cancelled_by_pause_and_play_commits_nothing_and_the_minute_is_claimed_again(
    runtime_world, clock
):
    w = runtime_world
    base = 8000
    create(w)
    configure(w, base, "playing")
    cancelled = take_claim(w, base)
    clock.add(500)
    configure(w, base, "paused")
    configure(w, base, "playing")
    # No batch completed, so the minute is still due at once; the claim taken before is void.
    assert stored_due(w) == clock.now
    with pytest.raises(LeaseLost):
        controls(w, base).execute(cancelled)
    assert read(w, base)["current_tick"] == 0
    receipt = run_batch(w, base)
    assert minutes(receipt) == (1, 1, 0) and receipt["tick_to"] == 1


@pytest.mark.parametrize("base", BASES)
def test_the_worker_advances_a_society_as_soon_as_it_is_set_playing(
    runtime_world, spine_schema, base
):
    """On the server's own clock, with nothing made overdue by hand."""
    w = runtime_world
    create(w)
    worker = worker_for(w, spine_schema, base)
    assert worker.run_once(w["workspace"]) is None
    configure(w, base, "playing")
    result = worker.run_once(w["workspace"])
    assert result is not None
    receipt = result["receipt"]
    assert receipt["kind"] == "advanced" and minutes(receipt) == (1, 1, 0)
    assert result["control"]["current_tick"] == 1
    # The wait before the second minute starts when the first completes.
    assert dt.datetime.fromisoformat(result["control"]["next_due_at"]) == (
        dt.datetime.fromisoformat(receipt["completed_at"]) + ms(base)
    )
    assert worker.run_once(w["workspace"]) is None


def test_pausing_and_playing_ten_times_inside_one_interval_adds_no_minute(
    runtime_world, spine_schema
):
    """On the server's own clock, with the real worker, at a base of 60 s so that the presses fall
    inside one interval. Each premise, that the server's clock is still inside the wait, is held."""
    w = runtime_world
    base = 60_000
    create(w)
    worker = worker_for(w, spine_schema, base)
    configure(w, base, "playing")
    first = worker.run_once(w["workspace"])["receipt"]
    assert minutes(first) == (1, 1, 0)
    completed = dt.datetime.fromisoformat(first["completed_at"])
    # Other speeds at once after the minute add none: 4x still waits 15 s, 2x 30 s, 1x 60 s.
    for speed, wait in ((4, 15_000), (2, 30_000), (1, 60_000)):
        configure(w, base, "playing", speed)
        assert stored_due(w) == completed + ms(wait)
        assert worker.run_once(w["workspace"]) is None
        assert server_now(w) < completed + ms(wait)
    for _ in range(10):
        configure(w, base, "paused")
        assert worker.run_once(w["workspace"]) is None
        configure(w, base, "playing")
        assert stored_due(w) == completed + ms(60_000)
        assert worker.run_once(w["workspace"]) is None
    assert server_now(w) < completed + ms(60_000)
    control = read(w, base)
    assert control["current_tick"] == 1 and control["revision"] == 24
    kinds = [event["kind"] for event in controls(w, base).events(w["binding"].version_id)]
    assert kinds.count("advanced") == 1 and kinds.count("configured") == 24


@pytest.mark.parametrize("base", BASES)
def test_the_first_minute_after_play_comes_in_seconds_not_after_an_interval(
    runtime_world, spine_schema, base
):
    """The worker's own loop at its own poll. A sample of the wait a person meets, held only to
    less than three quarters of the interval; not a hardware-independent latency assertion."""
    w = runtime_world
    create(w)
    worker = worker_for(w, spine_schema, base)
    stop = threading.Event()
    loop = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    limit_seconds = 0.75 * base / 1000

    def tick():
        return (
            w["connection"]
            .execute(
                "select current_tick from world_society where workspace_id=%s", (w["workspace"],)
            )
            .fetchone()["current_tick"]
        )

    loop.start()
    try:
        pressed = time.monotonic()
        configure(w, base, "playing")
        while tick() == 0 and time.monotonic() - pressed < limit_seconds:
            time.sleep(0.02)
        waited = time.monotonic() - pressed
    finally:
        stop.set()
        loop.join(timeout=60)
    assert tick() >= 1 and waited < limit_seconds
    sample = {
        "base_tick_interval_ms": base,
        "speed": 1,
        "seconds_from_play_to_first_minute": round(waited, 3),
        "scope": "configure, the worker's 0.25 s poll, claim, one tick, receipt commit; no model",
    }
    print("FIRST_MINUTE_AFTER_PLAY " + json.dumps(sample, sort_keys=True))
