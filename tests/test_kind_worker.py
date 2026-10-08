"""The kind worker: kind checks, world composition and site drawings off the request's thread,
bounded.

Each test hands the worker a thread pool and a job of its own, so what is tested is the worker's
bounds (kept results, a time limit, one waiting request per job, waiting bounds in all and per
workspace, failure and stuck jobs, and its lock never held while the pool is), not the generation;
the generation the real jobs run is tested through the routes in test_world_kinds_postgres.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from exulanica.world.kinds import worker as worker_module
from exulanica.world.kinds.worker import (
    Kept,
    KindWorker,
    KindWorkWaiting,
    check_job,
    compose_job,
    drawing_job,
    place_job,
    site_ground_place_id,
)

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"


def _held(release: threading.Event) -> Any:
    def held() -> dict[str, str]:
        release.wait(5)
        return {"status": "done"}

    return held


def test_a_kept_job_asked_twice_runs_once_and_is_read_from_what_was_kept() -> None:
    calls: list[int] = []

    def job(value: int) -> dict[str, int]:
        calls.append(value)
        return {"status": "done", "value": value}

    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    kept = Kept(4)
    first = worker.run("a", 5.0, job, 1, workspace="w", kept=kept)
    second = worker.run("a", 5.0, job, 1, workspace="w", kept=kept)
    assert (first.status, second.status) == ("done", "done")
    assert first.value == second.value == {"status": "done", "value": 1}
    assert calls == [1]


def test_a_job_not_kept_runs_again_when_asked_again() -> None:
    calls: list[int] = []

    def job() -> dict[str, str]:
        calls.append(1)
        return {"status": "done"}

    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    worker.run("composed", 5.0, job, workspace="w")
    worker.run("composed", 5.0, job, workspace="w")
    assert calls == [1, 1]


def test_a_job_past_its_limit_overruns_in_words_and_is_kept_when_it_finishes() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    kept = Kept(4)
    assert worker.run("slow", 0.05, _held(release), workspace="w", kept=kept).status == "overran"
    assert "Ask again shortly" in str(KindWorkWaiting("overran"))
    assert KindWorkWaiting("overran").retry_seconds == 2
    release.set()
    for _ in range(100):
        if kept.get("slow") is not None:
            break
        threading.Event().wait(0.02)
    # Asking again reads the finished job without running it.
    again = worker.run("slow", 5.0, lambda: {"status": "other"}, workspace="w", kept=kept)
    assert (again.status, again.value) == ("done", {"status": "done"})


def test_a_second_request_for_a_running_job_is_answered_at_once() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    first: list[str] = []
    asking = threading.Thread(
        target=lambda: first.append(worker.run("one", 5.0, _held(release), workspace="w").status)
    )
    asking.start()
    for _ in range(100):
        if worker._running:
            break
        threading.Event().wait(0.01)
    # The job runs and one request waits for it; the next is not held for it.
    timer = threading.Timer(2.0, release.set)
    timer.start()
    assert worker.run("one", 5.0, _held(release), workspace="other").status == "overran"
    assert not release.is_set()
    release.set()
    timer.cancel()
    asking.join(5)
    assert first == ["done"]


def test_past_the_waiting_bound_a_job_is_busy_rather_than_queued() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1), waiting=1, per_workspace=8)
    assert worker.run("one", 0.01, _held(release), workspace="a").status == "overran"
    assert worker.run("two", 0.01, _held(release), workspace="b").status == "overran"
    busy = worker.run("three", 0.01, _held(release), workspace="c")
    assert (busy.status, busy.reason) == ("busy", "")
    release.set()


def test_a_workspace_past_its_own_bound_is_busy_while_another_is_served() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1), waiting=8, per_workspace=2)
    assert worker.run("a1", 0.01, _held(release), workspace="a").status == "overran"
    assert worker.run("a2", 0.01, _held(release), workspace="a").status == "overran"
    # A job counts until it finishes, whoever stopped waiting for it.
    mine = worker.run("a3", 0.01, _held(release), workspace="a")
    assert (mine.status, mine.reason) == ("busy", "workspace")
    assert "This workspace" in str(KindWorkWaiting("busy", reason="workspace"))
    assert worker.run("b1", 0.01, _held(release), workspace="b").status == "overran"
    release.set()


def test_a_job_that_fails_is_unavailable_not_a_failed_request() -> None:
    def broken() -> dict[str, str]:
        raise RuntimeError("a defect")

    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    assert worker.run("broken", 5.0, broken, workspace="w").status == "unavailable"


def test_a_stuck_job_is_let_go_at_any_request_so_later_ones_are_not_busy_for_ever() -> None:
    now = [0.0]
    release = threading.Event()
    worker = KindWorker(
        lambda: ThreadPoolExecutor(1), waiting=0, stuck_seconds=10.0, clock=lambda: now[0]
    )
    kept = Kept(4)
    kept.put("read", {"status": "done"})
    assert worker.run("stuck", 0.01, _held(release), workspace="a").status == "overran"
    assert worker.run("next", 0.01, _held(release), workspace="b").status == "busy"
    now[0] = 11.0
    # A request that starts nothing (it reads a kept job) still lets the stuck job's pool go.
    assert worker.run("read", 0.01, _held(release), workspace="c", kept=kept).status == "done"
    assert worker._running == {}
    assert worker.run("next", 0.01, _held(release), workspace="b").status == "overran"
    release.set()


class _PoolWithItsOwnLock(Executor):
    """A pool that takes a lock of its own to submit, while another thread holding that lock runs a
    finished job's callbacks, as CPython 3.12 runs them under a broken pool's shutdown lock."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.submitting = threading.Event()
        self.futures: list[Future[dict[str, Any]]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[dict[str, Any]]:
        self.submitting.set()
        with self.lock:
            future: Future[dict[str, Any]] = Future()
            self.futures.append(future)
            return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self.lock:
            pass


def test_nothing_is_handed_to_the_pool_while_the_workers_own_lock_is_held() -> None:
    pool = _PoolWithItsOwnLock()
    worker = KindWorker(lambda: pool, waiting=8, per_workspace=8)
    assert worker.run("first", 0.01, _held(threading.Event()), workspace="a").status == "overran"
    pool.submitting.clear()
    callbacks_ran = threading.Event()

    def pool_thread() -> None:
        # Holding the pool's lock, it ends the first job, whose callback takes the worker's lock.
        with pool.lock:
            pool.submitting.wait(5)
            pool.futures[0].set_exception(RuntimeError("the pool broke"))
            callbacks_ran.set()

    holder = threading.Thread(target=pool_thread, daemon=True)
    holder.start()
    second: list[str] = []
    asking = threading.Thread(
        target=lambda: second.append(
            worker.run("second", 0.01, _held(threading.Event()), workspace="b").status
        ),
        daemon=True,
    )
    asking.start()
    asking.join(5)
    holder.join(5)
    # Had the worker held its lock while submitting, both threads would still wait on each other.
    assert not asking.is_alive() and not holder.is_alive()
    assert callbacks_ran.is_set() and second == ["overran"]
    assert "first" not in worker._running


def test_the_jobs_answer_a_check_a_world_and_its_drawing_as_plain_data() -> None:
    farm = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    checked = check_job(farm)
    assert checked["status"] == "done" and checked["report"]["verdict"] == "passed"
    closed = json.loads(json.dumps(farm))
    closed["zones"][0]["access"] = "closed"
    refused = check_job(closed)
    assert (refused["status"], refused["code"]) == ("refused", "kind_unreachable")
    world_id = "world:generated:worker-test"
    composed = compose_job("w", farm, {"width_mm": 96_000, "barns": 1}, world_id)
    assert composed["status"] == "done"
    made = composed["composed"]
    assert made.receipt["kind"]["kind"] == "fixture_farm"
    # The drawing and the place read later, from the receipt alone, are the ones made with the
    # world: the place its checks built, named as its society's ground names it.
    worker_module._records.clear()
    drawn = drawing_job("w", world_id, dict(made.receipt), made.receipt_sha256)
    assert drawn["status"] == "done"
    assert (drawn["body"], drawn["sha256"]) == (composed["body"], composed["sha256"])
    assert json.loads(drawn["body"])["profile"] == "exulanica.site-drawing/v1"
    worker_module._records.clear()
    placed = place_job("w", dict(made.receipt), made.receipt_sha256, composed["place_id"])
    assert placed == composed["placed"]
    assert placed["place"]["place_id"] == site_ground_place_id()
    # Another workspace's records are its own, generated again rather than read across.
    assert set(worker_module._records) == {f"w:{made.receipt_sha256}"}


def test_a_worker_process_that_dies_answers_unavailable_and_the_next_job_starts_a_new_one():
    # The real spawned process the server uses: its job is a long sleep, and it is killed while the
    # request waits.
    worker = KindWorker(waiting=4, per_workspace=4)
    outcome: list[Any] = []
    try:
        asking = threading.Thread(
            target=lambda: outcome.append(worker.run("long", 60.0, time.sleep, 30, workspace="w")),
            daemon=True,
        )
        asking.start()
        processes: list[Any] = []
        for _ in range(400):
            running = worker._running.get("long")
            pool = worker._executor
            processes = list((getattr(pool, "_processes", None) or {}).values())
            future = None if running is None else running.future
            if future is not None and processes and future.running():
                break
            time.sleep(0.05)
        assert processes, "the worker process did not start"
        for process in processes:
            process.terminate()
        asking.join(30)
        assert [answer.status for answer in outcome] == ["unavailable"]
        again = worker.run("pid", 60.0, os.getpid, workspace="w")
        assert again.status == "done" and again.value not in (None, os.getpid())
    finally:
        worker.close()


class _PoolThatCannotStart(Executor):
    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[dict[str, Any]]:
        raise OSError("cannot start the worker process")


def test_a_pool_that_cannot_take_a_job_leaves_no_job_behind_and_the_next_is_served():
    pools: list[Executor] = [_PoolThatCannotStart(), ThreadPoolExecutor(1)]
    worker = KindWorker(lambda: pools.pop(0), waiting=0, per_workspace=1)
    assert worker.run("first", 5.0, lambda: {"status": "done"}, workspace="w").status == (
        "unavailable"
    )
    # Nothing counts against the queue or the workspace, and the next job starts a new pool.
    assert worker._running == {}
    assert worker.run("second", 5.0, lambda: {"status": "done"}, workspace="w").status == "done"


class _NodesLowered:
    """The kind catalogs with the walking graph's bound lowered, everything else as they are."""

    def __init__(self, catalogs: Any, nodes: int) -> None:
        self._catalogs = catalogs
        self._nodes = nodes

    def __getattr__(self, name: str) -> Any:
        return getattr(self._catalogs, name)

    def bound(self, key: str) -> tuple[int, int]:
        return (1, self._nodes) if key == "walking_nodes" else self._catalogs.bound(key)


def test_a_place_whose_walking_graph_outgrows_its_bound_is_refused_by_name(monkeypatch) -> None:
    from exulanica.world.composers import site_plan
    from exulanica.world.kinds.catalogs import load_kind_catalogs

    farm = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    world_id = "world:generated:graph-test"
    composed = compose_job("w", farm, {"width_mm": 96_000, "barns": 1}, world_id)
    made = composed["composed"]
    nodes = len(composed["placed"]["place"]["nodes"])
    # At the bound the checks held it to, the place is made; one place under its size, refused.
    monkeypatch.setattr(
        site_plan, "load_kind_catalogs", lambda: _NodesLowered(load_kind_catalogs(), nodes)
    )
    placed = place_job("w", dict(made.receipt), made.receipt_sha256, site_ground_place_id())
    assert placed["status"] == "done"
    monkeypatch.setattr(
        site_plan, "load_kind_catalogs", lambda: _NodesLowered(load_kind_catalogs(), nodes - 1)
    )
    refused = place_job("w", dict(made.receipt), made.receipt_sha256, site_ground_place_id())
    assert (refused["status"], refused["code"]) == ("refused", "kind_graph_over_budget")
    assert refused["detail"].startswith("kind_graph_over_budget: ")


def test_a_closed_worker_answers_unavailable_and_starts_no_process(monkeypatch) -> None:
    made: list[int] = []

    def pool() -> Executor:
        made.append(1)
        return ThreadPoolExecutor(1)

    worker = KindWorker(pool)
    assert worker.run("a", 5.0, _held(_released()), workspace="w").status == "done"
    worker.close()
    closed = worker.run("b", 5.0, _held(_released()), workspace="w")
    assert (closed.status, closed.reason) == ("unavailable", "closed")
    assert made == [1]
    # The server's own worker is replaced as it closes: a caller holding the closed one starts
    # nothing, and the next server in the process has a worker that starts its own pool.
    monkeypatch.setattr(worker_module, "_worker", KindWorker(pool))
    monkeypatch.setattr(worker_module, "KindWorker", lambda: KindWorker(pool))
    held = worker_module.kind_worker()
    worker_module.close_kind_worker()
    assert held.run("c", 5.0, _held(_released()), workspace="w").status == "unavailable"
    fresh = worker_module.kind_worker()
    assert fresh is not held
    assert fresh.run("d", 5.0, _held(_released()), workspace="w").status == "done"
    fresh.close()


def _released() -> threading.Event:
    release = threading.Event()
    release.set()
    return release
