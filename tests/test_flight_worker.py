"""The flight's worker: whole episodes computed off the request's thread, and windows cut from them.

Most tests hand the episode cache a thread executor, which runs the same job in this process; the
tests marked as the real child run it in the spawned worker process a server uses, and kill it.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from exulanica.canonical import canonical_json
from exulanica.movement import flight as flight_module
from exulanica.movement.flight import FLIGHT_MODULE, FlightRefused, flight_input, flight_window
from exulanica.movement.flight_episodes import compute_episode, from_wire, window_of, wire
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world.flight_worker import FlightEpisodes, FlightWorkerUnavailable

from flight_support import DEVELOPMENT_SEEDS, seeded, square_flight, trees_flight

EPISODE = FLIGHT_MODULE.value("episode_steps")
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")
#: Windows of every shape a page or a tool may ask for: a whole minute from an episode's first
#: step, one ending on an episode's last step, one crossing into the next episode, short ones.
SHAPES = (
    (0, WINDOW),
    (EPISODE - WINDOW, WINDOW),
    (EPISODE - 1, 2),
    (EPISODE - 250, WINDOW),
    (EPISODE, WINDOW),
    (2 * EPISODE - 1, 1),
    (123, 7),
)


class CountingExecutor(ThreadPoolExecutor):
    """A thread executor that counts the episodes it is asked for."""

    def __init__(self) -> None:
        super().__init__(max_workers=1)
        self.asked: list[int] = []

    def submit(self, function, /, *arguments, **keywords):  # type: ignore[override]
        if function is compute_episode:
            self.asked.append(arguments[1])
        return super().submit(function, *arguments, **keywords)


def _threads() -> FlightEpisodes:
    return FlightEpisodes(lambda: ThreadPoolExecutor(max_workers=1))


def _digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


# -- windows cut from episodes are the windows computed cold ------------------------------------


@pytest.mark.parametrize(("from_step", "steps"), SHAPES, ids=[f"{a}+{b}" for a, b in SHAPES])
def test_a_window_cut_from_episodes_is_the_window_computed_cold(from_step, steps):
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[2])
    episodes = _threads()
    try:
        assert episodes.window(flight, from_step, steps) == flight_window(flight, from_step, steps)
    finally:
        episodes.close()


def test_a_late_flyer_is_named_in_the_window_cut_from_its_episode(monkeypatch):
    """Break homing: nobody goes home. The cut window names the same late flyers, at the same
    step, as the window computed cold, and the window after names none."""
    monkeypatch.setattr(flight_module, "_go_home", lambda flight, flyer_state: None)
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[3])
    episodes = _threads()
    try:
        cut = episodes.window(flight, EPISODE - 250, WINDOW)
        assert cut == flight_window(flight, EPISODE - 250, WINDOW)
        assert cut["late_home"] and {row["step"] for row in cut["late_home"]} == {EPISODE - 1}
        assert episodes.window(flight, EPISODE, WINDOW)["late_home"] == []
    finally:
        episodes.close()


def test_the_wire_form_rebuilds_the_input_and_refuses_one_it_does_not_match():
    flight = seeded(trees_flight(), DEVELOPMENT_SEEDS[1])
    data = pickle.loads(pickle.dumps(wire(flight)))
    assert from_wire(data).sha256 == flight.sha256
    cells = bytearray(data["cells"])
    cells[cells.index(0)] = 1
    with pytest.raises(ValueError, match="does not rebuild"):
        from_wire({**data, "cells": bytes(cells)})
    with pytest.raises(ValueError, match="does not rebuild"):
        from_wire({**data, "seed": DEVELOPMENT_SEEDS[0]})


def test_a_packed_episode_is_every_step_of_that_episode():
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[4])
    packed = compute_episode(wire(flight), 1)
    assert (packed.input_sha256, packed.episode) == (flight.sha256, 1)
    for start in range(EPISODE, 2 * EPISODE, WINDOW):
        assert window_of(flight, {1: packed}, start, WINDOW) == flight_window(flight, start, WINDOW)
    assert packed.byte_size == len(flight.flyers) * EPISODE * 10 * 4


def test_a_sample_outside_the_packed_range_is_refused_never_wrapped(monkeypatch):
    real = flight_module.window_from

    def far(flight, state, steps):
        window, last = real(flight, state, steps)
        window["flyers"][0]["position_mm"][0] = 2**31
        return window, last

    monkeypatch.setattr("exulanica.movement.flight_episodes.window_from", far)
    with pytest.raises(FlightRefused) as refused:
        compute_episode(wire(square_flight()), 0)
    assert refused.value.code == "flight_world_too_large"


def test_refusals_raised_in_the_worker_reach_the_server_as_themselves():
    for error in (
        FlightRefused("flight_world_too_large", "a detail"),
        MovementModuleNotConnected("exulanica-movement/flight/v1", "flight_not_connected"),
        FlightWorkerUnavailable("stopped"),
    ):
        again = pickle.loads(pickle.dumps(error))
        assert type(again) is type(error)
        assert (again.code, str(again)) == (error.code, str(error))


# -- episodes are computed once, kept, bounded and queued ahead ---------------------------------


def test_each_episode_is_computed_once_and_the_next_is_queued():
    made: list[CountingExecutor] = []

    def executor():
        made.append(CountingExecutor())
        return made[-1]

    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[5])
    episodes = FlightEpisodes(executor)
    try:
        for start in range(0, 2 * EPISODE, WINDOW):
            episodes.window(flight, start, WINDOW)
        made[0].shutdown(wait=True)
        assert made[0].asked == [0, 1, 2]
        assert [episode for _sha, episode in episodes.held()] == [0, 1, 2]
    finally:
        episodes.close()


def test_episodes_kept_are_bounded_least_recently_used_first():
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[6])
    pool = ThreadPoolExecutor(max_workers=1)
    episodes = FlightEpisodes(lambda: pool, limit=2)
    try:
        episodes.window(flight, 0, 1)
        episodes.window(flight, 2 * EPISODE, 1)
        pool.shutdown(wait=True)
        assert [episode for _sha, episode in episodes.held()] == [2, 3]
    finally:
        episodes.close()


def test_many_request_threads_share_the_episodes_safely():
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[7])
    cold = {start: flight_window(flight, start, WINDOW) for start in range(0, 2 * EPISODE, WINDOW)}
    counting = CountingExecutor()
    episodes = FlightEpisodes(lambda: counting)
    failures: list[BaseException] = []
    served: list[tuple[int, dict]] = []

    def ask(offset: int) -> None:
        try:
            for round_ in range(6):
                start = ((offset + round_) % len(cold)) * WINDOW
                served.append((start, episodes.window(flight, start, WINDOW)))
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=ask, args=(offset,)) for offset in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    episodes.close()
    assert failures == []
    assert all(window == cold[start] for start, window in served)
    assert sorted(counting.asked) == sorted(set(counting.asked)), "an episode was computed twice"


def test_a_read_whose_episode_is_late_is_refused_and_the_episode_kept_when_done():
    release = threading.Event()

    class Slow(ThreadPoolExecutor):
        def submit(self, function, /, *arguments, **keywords):  # type: ignore[override]
            def slowly():
                release.wait(10)
                return function(*arguments, **keywords)

            return super().submit(slowly)

    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[8])
    episodes = FlightEpisodes(lambda: Slow(max_workers=1), wait_seconds=0.05)
    try:
        with pytest.raises(FlightWorkerUnavailable) as refused:
            episodes.window(flight, 0, WINDOW)
        assert refused.value.code == "flight_worker_unavailable"
        release.set()
        deadline = time.monotonic() + 10
        while (flight.sha256, 0) not in episodes.held() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert episodes.window(flight, 0, WINDOW) == flight_window(flight, 0, WINDOW)
    finally:
        release.set()
        episodes.close()


def test_a_window_whose_episodes_are_kept_is_served_when_the_worker_cannot_queue_more():
    class Refusing(ThreadPoolExecutor):
        refusing = False

        def submit(self, function, /, *arguments, **keywords):  # type: ignore[override]
            if self.refusing:
                raise RuntimeError("cannot schedule new futures after shutdown")
            return super().submit(function, *arguments, **keywords)

    pool = Refusing(max_workers=1)
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[9])
    episodes = FlightEpisodes(lambda: pool)
    try:
        episodes.window(flight, 0, 1)
        deadline = time.monotonic() + 10
        while (flight.sha256, 1) not in episodes.held() and time.monotonic() < deadline:
            time.sleep(0.01)
        pool.refusing = True
        assert episodes.window(flight, EPISODE - 1, 2) == flight_window(flight, EPISODE - 1, 2)
        with pytest.raises(FlightWorkerUnavailable):
            episodes.window(flight, 2 * EPISODE, 1)
    finally:
        episodes.close()


class GatedExecutor(ThreadPoolExecutor):
    """A thread executor whose episodes wait until the test lets them go, recording the order in
    which the worker takes them."""

    def __init__(self) -> None:
        super().__init__(max_workers=1)
        self.gate = threading.Event()
        self.computed: list[tuple[str, int]] = []

    def submit(self, function, /, *arguments, **keywords):  # type: ignore[override]
        if function is not compute_episode:
            return super().submit(function, *arguments, **keywords)

        def gated():
            self.gate.wait(20)
            self.computed.append((arguments[0]["input_sha256"], arguments[1]))
            return function(*arguments, **keywords)

        return super().submit(gated)


def _until(condition, what: str) -> None:
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.005)


def _read(episodes, flight, from_step, steps, results, generation=None):
    def read() -> None:
        try:
            results.append(episodes.window(flight, from_step, steps, generation=generation))
        except FlightWorkerUnavailable as error:
            results.append(error)

    thread = threading.Thread(target=read)
    thread.start()
    return thread


def test_an_edit_drops_what_its_old_input_waits_for_and_keeps_none_of_it():
    """Two inputs of one world version, the second an edit later: the first's episode waiting
    ahead of need is dropped, the one being computed goes to the read waiting for it and is not
    kept, and a read of the old input after the edit is refused."""
    old = seeded(square_flight(), DEVELOPMENT_SEEDS[0])
    new = seeded(square_flight(), DEVELOPMENT_SEEDS[1])
    assert (old.world_id, old.version_id) == (new.world_id, new.version_id)
    pool = GatedExecutor()
    episodes = FlightEpisodes(lambda: pool)
    old_read, new_read = [], []
    try:
        first = _read(episodes, old, 0, WINDOW, old_read, generation=1)
        _until(lambda: episodes.waiting() == [((old.sha256, 1), 0)], "the old input's ahead")
        second = _read(episodes, new, 0, WINDOW, new_read, generation=2)
        _until(
            lambda: [key for key, _ in episodes.waiting()] == [(new.sha256, 0), (new.sha256, 1)],
            "the edit",
        )
        pool.gate.set()
        first.join()
        second.join()
        assert old_read == [flight_window(old, 0, WINDOW)]
        assert new_read == [flight_window(new, 0, WINDOW)]
        _until(lambda: len(pool.computed) == 3, "the next episode")
        assert pool.computed == [(old.sha256, 0), (new.sha256, 0), (new.sha256, 1)]
        assert all(sha == new.sha256 for sha, _ in episodes.held())
        with pytest.raises(FlightWorkerUnavailable, match="an edit has replaced"):
            episodes.window(old, 0, WINDOW, generation=1)
    finally:
        pool.gate.set()
        episodes.close()


def test_an_episode_a_read_waits_for_goes_before_work_ahead_of_need():
    one = seeded(square_flight(), DEVELOPMENT_SEEDS[2])
    base = trees_flight()
    other = flight_input(
        world_id=base.world_id,
        version_id="another-version",
        seed=base.seed,
        occupancy=base.occupancy,
        perches=base.perches,
        kinds=base.kinds,
        flyers=base.flyers,
        solids=base.solids,
        unplaced=base.unplaced,
    )
    pool = GatedExecutor()
    episodes = FlightEpisodes(lambda: pool)
    results: list = []
    try:
        first = _read(episodes, one, 0, WINDOW, results)
        _until(lambda: episodes.waiting() == [((one.sha256, 1), 0)], "the first read's ahead")
        second = _read(episodes, other, 0, WINDOW, results)
        _until(lambda: len(episodes.waiting()) == 3, "the second read")
        assert episodes.waiting() == [
            ((other.sha256, 0), 1),
            ((one.sha256, 1), 0),
            ((other.sha256, 1), 0),
        ]
        pool.gate.set()
        first.join()
        second.join()
        _until(lambda: len(pool.computed) == 4, "the work ahead")
        assert [key[1] for key in pool.computed[:2]] == [0, 0]
        assert pool.computed[1][0] == other.sha256
    finally:
        pool.gate.set()
        episodes.close()


def test_the_queue_is_bounded_and_work_ahead_of_need_gives_way_to_a_read():
    flights = [seeded(square_flight(), seed) for seed in DEVELOPMENT_SEEDS[3:7]]
    pool = GatedExecutor()
    episodes = FlightEpisodes(lambda: pool, queue_limit=2)
    results: list = []
    threads = []
    try:
        threads.append(_read(episodes, flights[0], 0, 1, results))
        _until(lambda: episodes.waiting() == [((flights[0].sha256, 1), 0)], "the first read")
        threads.append(_read(episodes, flights[1], 0, 1, results))
        _until(lambda: len(episodes.waiting()) == 2, "the second read")
        # The queue is full: nothing more is asked for ahead of need.
        assert episodes.waiting() == [((flights[1].sha256, 0), 1), ((flights[0].sha256, 1), 0)]
        threads.append(_read(episodes, flights[2], 0, 1, results))
        _until(lambda: (flights[2].sha256, 0) in dict(episodes.waiting()), "the third read")
        # A read's episode pushed out the work ahead of need.
        assert episodes.waiting() == [((flights[1].sha256, 0), 1), ((flights[2].sha256, 0), 1)]
        with pytest.raises(FlightWorkerUnavailable, match="2 episodes waiting"):
            episodes.window(flights[3], 0, 1)
    finally:
        pool.gate.set()
        for thread in threads:
            thread.join()
        episodes.close()
    assert sum(isinstance(result, dict) for result in results) == 3


def test_a_read_that_spans_two_episodes_waits_for_both_until_one_deadline(monkeypatch):
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[8])
    episodes = _threads()
    deadlines: list[float] = []
    real = episodes._wait_for

    def recorded(item, deadline):
        deadlines.append(deadline)
        return real(item, deadline)

    monkeypatch.setattr(episodes, "_wait_for", recorded)
    try:
        assert episodes.window(flight, EPISODE - 1, 2) == flight_window(flight, EPISODE - 1, 2)
    finally:
        episodes.close()
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]


def test_an_episode_whose_worker_broke_is_computed_again_by_the_next_read():
    from concurrent.futures.process import BrokenProcessPool

    class Broken(ThreadPoolExecutor):
        def submit(self, function, /, *arguments, **keywords):  # type: ignore[override]
            def broken():
                raise BrokenProcessPool("the worker died")

            return super().submit(broken)

    made: list[ThreadPoolExecutor] = []

    def executor():
        made.append(Broken(max_workers=1) if not made else ThreadPoolExecutor(max_workers=1))
        return made[-1]

    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[9])
    episodes = FlightEpisodes(executor)
    try:
        with pytest.raises(FlightWorkerUnavailable, match="stopped"):
            episodes.window(flight, 0, 1)
        _until(lambda: not episodes.waiting(), "the broken worker to let its queue go")
        assert episodes.window(flight, 0, 1) == flight_window(flight, 0, 1)
        assert len(made) == 2
    finally:
        episodes.close()


# -- the real child -----------------------------------------------------------------------------


def test_the_real_worker_computes_the_same_windows_imports_only_movement_and_restarts_when_killed():
    """The server's own executor: a spawned process. Its windows are the cold ones; it has loaded
    nothing of the server beyond the movement package; killed, the read that meets it is refused
    by name, and the next read starts another process that serves the same windows."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[10])
    episodes = FlightEpisodes()
    try:
        assert episodes.window(flight, 0, WINDOW) == flight_window(flight, 0, WINDOW)
        report = episodes.report()
        assert report["pid"] != os.getpid()
        # The packages, canonical JSON and the error types it raises: leaves that import nothing.
        allowed = {"exulanica", "exulanica.canonical", "exulanica.errors", "exulanica.movement"}
        loaded = set(report["modules"])
        assert "exulanica.movement.flight_episodes" in loaded
        assert {name for name in loaded if not name.startswith("exulanica.movement.")} <= allowed
        assert not {name.split(".")[1] for name in loaded if "." in name} & {"api", "db", "world"}

        os.kill(report["pid"], signal.SIGKILL)
        with pytest.raises(FlightWorkerUnavailable) as refused:
            # An episode nobody has asked for, so the read needs the dead worker.
            episodes.window(flight, 5 * EPISODE, WINDOW)
        assert refused.value.code == "flight_worker_unavailable"
        again = episodes.window(flight, 5 * EPISODE, WINDOW)
        assert again == flight_window(flight, 5 * EPISODE, WINDOW)
        assert episodes.report()["pid"] not in {report["pid"], os.getpid()}
    finally:
        episodes.close()


def test_the_real_worker_ends_when_the_process_that_started_it_is_killed(tmp_path):
    """A server killed outright cannot stop its worker; the worker notices its parent is gone and
    ends itself."""
    script = (
        "import sys, time\n"
        "from exulanica.world.flight_worker import FlightEpisodes\n"
        "episodes = FlightEpisodes()\n"
        "print(episodes.report()['pid'], flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        child = int(parent.stdout.readline())
        os.kill(child, 0)
        parent.kill()
        parent.wait(10)

        def gone() -> bool:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                return True
            return False

        try:
            _until(gone, "the orphaned worker to end")
        except AssertionError:
            # Failing, the test does not leave the worker it orphaned running.
            os.kill(child, signal.SIGKILL)
            raise
    finally:
        parent.kill()
