"""A sample town of a drafted specification: computed off the request's thread, bounded by a time
limit and a queue, kept by what it is made from, and counted from the town's own records."""

from __future__ import annotations

import functools
import multiprocessing
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from exulanica.world.specification_samples import (
    SampleWorker,
    compute_sample,
    sample_process_pool,
    sample_world_id,
)

SHA = "0" * 64


@pytest.fixture(autouse=True)
def _no_sample_process_outlives_its_test():
    """A sample process a test leaves running would hold the whole run open at exit (a pool's
    processes are joined then), so one is stopped here and the test fails by name instead."""
    yield
    left = [p for p in multiprocessing.active_children() if p.name.startswith("SpawnProcess")]
    if not _until(lambda: not any(p.is_alive() for p in left), 10.0):
        for process in left:
            process.terminate()
        pytest.fail(f"{len(left)} sample process(es) outlived the test")


def _counted_job(calls: list[tuple[str, dict[str, int], str]]):
    def job(preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
        calls.append((preset, values, world_id))
        return {
            "status": "sampled",
            "tiles": 2,
            "people": 40,
            "vehicles": 7,
            "streets": [{"key": "high_street", "label": "High street", "count": 1}],
            "premises": [{"key": "cafe", "label": "Cafe", "count": 3}],
            "buildings": 12,
        }

    return job


def test_one_proposal_samples_one_town_wherever_it_is_read() -> None:
    calls: list[Any] = []
    worker = SampleWorker(lambda: ThreadPoolExecutor(1), job=_counted_job(calls))
    try:
        first = worker.sample("small_town", {"block_length_mm": 90000}, SHA)
        again = worker.sample("small_town", {"block_length_mm": 90000}, SHA)
        other = worker.sample("small_town", {"block_length_mm": 100000}, SHA)
    finally:
        worker.close()
    assert first == again and first.status == "sampled" and first.people == 40
    assert other.status == "sampled"
    assert len(calls) == 2
    assert calls[0][2] == sample_world_id("small_town", {"block_length_mm": 90000}, SHA)
    assert calls[0][2] != calls[1][2]


def test_a_sample_past_its_time_limit_is_answered_in_words_and_kept_when_done() -> None:
    release = threading.Event()

    def slow(preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
        release.wait(5)
        return _counted_job([])(preset, values, world_id)

    worker = SampleWorker(lambda: ThreadPoolExecutor(1), job=slow, seconds=0.05)
    try:
        late = worker.sample("small_town", {}, SHA)
        assert late.status == "overran"
        assert (late.people, late.vehicles, late.streets) == (None, None, ())
        release.set()
        deadline = time.monotonic() + 5
        while worker.sample("small_town", {}, SHA).status == "overran":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert worker.sample("small_town", {}, SHA).people == 40
    finally:
        release.set()
        worker.close()


def test_past_the_waiting_bound_a_sample_is_busy_rather_than_queued() -> None:
    release = threading.Event()

    def held(preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
        release.wait(5)
        return _counted_job([])(preset, values, world_id)

    worker = SampleWorker(lambda: ThreadPoolExecutor(1), job=held, seconds=0.01, waiting=1)
    try:
        assert worker.sample("small_town", {"n": 1}, SHA).status == "overran"
        assert worker.sample("small_town", {"n": 2}, SHA).status == "overran"
        assert worker.sample("small_town", {"n": 3}, SHA).status == "busy"
    finally:
        release.set()
        worker.close()


def test_a_job_that_fails_is_unavailable_not_a_failed_request() -> None:
    def broken(preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
        raise RuntimeError("a defect")

    worker = SampleWorker(lambda: ThreadPoolExecutor(1), job=broken)
    try:
        assert worker.sample("small_town", {}, SHA).status == "unavailable"
    finally:
        worker.close()


def test_a_sample_counts_the_towns_own_records() -> None:
    """The real composer on the catalog's own preset, in this process."""
    sample = compute_sample("small_town", {}, sample_world_id("small_town", {}, SHA))

    assert sample["status"] == "sampled"
    assert sample["tiles"] >= 1 and sample["people"] > 0 and sample["buildings"] > 0
    assert {row["key"] for row in sample["streets"]} <= {
        "avenue",
        "high_street",
        "local_street",
        "narrow_street",
    }
    assert all(row["label"] and row["count"] > 0 for row in sample["premises"])
    assert ("vehicles" in sample) != ("vehicles_refused" in sample)


def test_a_specification_the_generator_refuses_is_a_refused_sample() -> None:
    sample = compute_sample("small_town", {"block_length_mm": 250000}, "world:sample:refused")

    assert sample["status"] == "refused"
    assert sample["refused"]
    assert "people" not in sample


def test_a_sample_is_computed_in_a_process_of_its_own() -> None:
    worker = SampleWorker(sample_process_pool)
    try:
        sample = worker.sample("small_town", {}, SHA)
    finally:
        worker.close()
    assert sample.status == "sampled" and sample.people and sample.people > 0


def _stuck(pidfile: str, preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
    """A sample whose process never finishes: it says which process it is, then waits."""
    Path(pidfile).write_text(f"{Path(pidfile).read_text()}{os.getpid()}\n")
    time.sleep(3600)
    return {}


def _dies_once(flag: str, preset: str, values: dict[str, int], world_id: str) -> dict[str, Any]:
    """A sample whose first process ends without an answer; a later one answers."""
    if not Path(flag).exists():
        Path(flag).write_text("died")
        os._exit(3)
    return {"status": "sampled", "tiles": 2, "people": 1, "buildings": 1}


def _gone(pid: int) -> bool:
    """Whether a process has ended (a zombie waiting to be reaped counts as ended)."""
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return state.stdout.strip() in ("", "Z") or state.stdout.strip().startswith("Z")


def _until(condition: Any, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def test_a_stuck_sample_is_let_go_so_later_ones_are_not_busy_for_ever(tmp_path) -> None:
    pidfile = tmp_path / "pids"
    pidfile.write_text("")
    now = [0.0]
    worker = SampleWorker(
        sample_process_pool,
        job=functools.partial(_stuck, str(pidfile)),
        seconds=0.2,
        waiting=0,
        stuck_seconds=30.0,
        clock=lambda: now[0],
    )
    try:
        assert worker.sample("small_town", {"n": 1}, SHA).status == "overran"
        assert _until(lambda: pidfile.read_text().strip() != "")
        first = int(pidfile.read_text().split()[0])
        # Its process still holds the queue: another sample is busy.
        assert worker.sample("small_town", {"n": 2}, SHA).status == "busy"
        # Past the bound, the stuck pool is replaced and its process stopped.
        now[0] = 31.0
        assert worker.sample("small_town", {"n": 3}, SHA).status == "overran"
        assert _until(lambda: _gone(first)), "the stuck process was not stopped"
        assert _until(lambda: len(pidfile.read_text().split()) == 2)
        second = int(pidfile.read_text().split()[1])
    finally:
        # Shutting down never waits on a stuck sample (it would wait an hour here), and stops it.
        worker.close()
    assert _until(lambda: _gone(second)), "close left the stuck process running"


def test_after_a_process_dies_the_next_sample_starts_another(tmp_path) -> None:
    flag = tmp_path / "died"
    worker = SampleWorker(
        sample_process_pool, job=functools.partial(_dies_once, str(flag)), seconds=20.0
    )
    try:
        assert worker.sample("small_town", {"n": 1}, SHA).status == "unavailable"
        assert flag.exists()
        # The broken pool is let go: the next sample is answered by a new process.
        assert worker.sample("small_town", {"n": 2}, SHA).status == "sampled"
    finally:
        worker.close()
