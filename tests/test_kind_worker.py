"""The kind worker: kind checks, world composition, site drawings and landscape drawings off the
request's thread, bounded.

Each test hands the worker a thread pool and a job of its own, so what is tested is the worker's
bounds (kept results, a time limit, one waiting request per job, waiting bounds in all and per
workspace, failure and stuck jobs, and its lock never held while the pool is), not the generation;
the generation the real jobs run is tested through the routes in test_world_kinds_postgres.py.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from exulanica.world.kinds import worker as worker_module
from exulanica.world.kinds.worker import (
    Kept,
    KindWorker,
    KindWorkWaiting,
    check_job,
    compose_job,
    drawing_job,
    landscape_job,
    landscape_key,
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
    # A request waits out the jobs before its own, so the one queued is asked aside.
    with ThreadPoolExecutor(1) as asking:
        two = asking.submit(worker.run, "two", 5.0, _held(release), workspace="b")
        _until(lambda: "two" in worker._running)
        busy = worker.run("three", 0.01, _held(release), workspace="c")
        assert (busy.status, busy.reason) == ("busy", "")
        release.set()
        assert two.result(5).status == "done"


def test_a_workspace_past_its_own_bound_is_busy_while_another_is_served() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1), waiting=8, per_workspace=2)
    assert worker.run("a1", 0.01, _held(release), workspace="a").status == "overran"
    with ThreadPoolExecutor(2) as asking:
        a2 = asking.submit(worker.run, "a2", 5.0, _held(release), workspace="a")
        _until(lambda: "a2" in worker._running)
        # A job counts until it finishes, whoever stopped waiting for it.
        mine = worker.run("a3", 0.01, _held(release), workspace="a")
        assert (mine.status, mine.reason) == ("busy", "workspace")
        assert "This workspace" in str(KindWorkWaiting("busy", reason="workspace"))
        b1 = asking.submit(worker.run, "b1", 5.0, _held(release), workspace="b")
        _until(lambda: "b1" in worker._running)
        release.set()
        assert (a2.result(5).status, b1.result(5).status) == ("done", "done")


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


def test_time_queued_behind_another_job_never_refuses_a_job_within_its_own_limit() -> None:
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    assert worker.run("first", 0.01, _held(release), workspace="a").status == "overran"
    # The first job holds the process for a second; the next, limited to a fifth of that, waits it
    # out and is answered within its own limit once the process starts it.
    timer = threading.Timer(1.0, release.set)
    timer.start()
    started = time.monotonic()
    second = worker.run("second", 0.2, _held(_released()), workspace="b")
    assert second.status == "done"
    assert time.monotonic() - started >= 0.9
    timer.join()


def test_a_request_waiting_behind_a_stuck_job_lets_it_go_rather_than_waiting_for_ever() -> None:
    now = [0.0]
    release = threading.Event()
    worker = KindWorker(lambda: ThreadPoolExecutor(1), stuck_seconds=10.0, clock=lambda: now[0])
    assert worker.run("stuck", 0.01, _held(release), workspace="a").status == "overran"
    timer = threading.Timer(0.5, lambda: now.__setitem__(0, 11.0))
    timer.start()
    started = time.monotonic()
    # Waiting behind it, the request finds it stuck and lets its process go, its own job with it.
    behind = worker.run("behind", 5.0, _held(_released()), workspace="b")
    assert behind.status == "unavailable"
    assert time.monotonic() - started < 3.0
    assert worker._running == {}
    release.set()


def test_work_that_yields_is_ended_by_a_persons_job_and_skipped_while_one_runs() -> None:
    pools: list[Executor] = []

    def pool() -> Executor:
        pools.append(ThreadPoolExecutor(1))
        return pools[-1]

    worker = KindWorker(pool)
    warming = threading.Event()
    warm = worker.run("warm", 0.0, _held(warming), workspace="installation", yields=True)
    assert warm.status == "overran"
    # A person's job asked while only the yielding work runs is not queued behind it: that work's
    # process is ended and the job runs at once in a new one.
    started = time.monotonic()
    assert worker.run("mine", 1.0, _held(_released()), workspace="w").status == "done"
    assert time.monotonic() - started < 1.0
    assert len(pools) == 2 and worker._running == {}
    # Work that yields, asked while a person's job runs, is skipped and never run.
    theirs = threading.Event()
    assert worker.run("theirs", 0.01, _held(theirs), workspace="w").status == "overran"
    ran: list[str] = []

    def warmed() -> dict[str, str]:
        ran.append("warm")
        return {"status": "done"}

    skipped = worker.run("warm", 0.0, warmed, workspace="installation", yields=True)
    assert (skipped.status, skipped.reason) == ("busy", "yields")
    theirs.set()
    warming.set()
    _until(lambda: not worker._running)
    assert ran == []
    worker.close()


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


def test_discarded_pool_cannot_overwrite_a_replacement_jobs_kept_answer():
    pools = [_PoolWithItsOwnLock(), _PoolWithItsOwnLock()]
    worker = KindWorker(lambda: pools.pop(0))
    kept = Kept(4)
    assert worker.run("same", 0.001, lambda: {}, workspace="w", kept=kept).status == "overran"
    old = worker._executor
    worker._discard(old)
    assert worker.run("same", 0.001, lambda: {}, workspace="w", kept=kept).status == "overran"
    new = worker._executor
    new.futures[0].set_result({"answer": "new"})
    old.futures[0].set_result({"answer": "private obsolete answer"})
    assert kept.get("same") == {"answer": "new"}
    worker.close()


def test_closed_worker_never_keeps_a_late_result():
    pool = _PoolWithItsOwnLock()
    worker = KindWorker(lambda: pool)
    kept = Kept(4)
    assert worker.run("secret", 0.001, lambda: {}, workspace="w", kept=kept).status == "overran"
    worker.close()
    pool.futures[0].set_result({"answer": "private"})
    assert kept.get("secret") is None


def test_erased_receipts_drop_their_caches_and_late_compositions_only(monkeypatch):
    pool = _PoolWithItsOwnLock()
    worker = KindWorker(lambda: pool)
    monkeypatch.setattr(worker_module, "_worker", worker)
    composer = worker_module.WorkerComposer("ours")
    erased = "a" * 64
    other = "b" * 64
    erased_key = worker_module.drawing_key("ours", erased)
    other_key = worker_module.drawing_key("ours", other)
    foreign_key = worker_module.drawing_key("theirs", erased)
    town_key = worker_module.town_land_key("ours", erased)
    for key in (erased_key, other_key, foreign_key, town_key):
        worker.drawings.put(key, {"body": key})
    # A landscape drawing, and the one drawn for the world with its parts changed, go with it.
    landscapes = [landscape_key("ours", erased), landscape_key("ours", erased, "c" * 64)]
    kept_landscapes = [landscape_key("ours", other), landscape_key("theirs", erased)]
    for key in (*landscapes, *kept_landscapes):
        worker.landscapes.put(key, {"body": key})
    place = worker_module.place_key("ours", erased, "place:1")
    worker.places.put(place, {"place": "private"})
    composer.drawn = (erased_key, {"body": "private late composition"})
    running_key = worker_module.place_key("ours", erased, "place:2")
    assert (
        worker.run(running_key, 0.001, lambda: {}, workspace="ours", kept=worker.places).status
        == "overran"
    )
    worker.forget_receipts("ours", frozenset({erased}))
    composer.keep()
    pool.futures[0].set_result({"place": "private late result"})
    assert worker.drawings.get(erased_key) is None
    assert worker.drawings.get(town_key) is None
    assert worker.places.get(place) is None
    assert worker.places.get(running_key) is None
    assert worker.drawings.get(other_key) == {"body": other_key}
    assert worker.drawings.get(foreign_key) == {"body": foreign_key}
    assert [worker.landscapes.get(key) for key in landscapes] == [None, None]
    assert [worker.landscapes.get(key) for key in kept_landscapes] == [
        {"body": key} for key in kept_landscapes
    ]
    worker.close()


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


LAND = {
    "profile": "exulanica.landform/v1",
    "ground_mm": 8000,
    "features": [{"id": "tilt", "kind": "tilt", "side": "north", "grade_permille": 30}],
}


def test_a_world_on_land_is_drawn_with_its_chunks_and_backdrop_and_a_refused_land_is_answered():
    farm = json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))
    world_id = "world:generated:worker-land"
    composed = compose_job("w", farm, {"width_mm": 96_000, "barns": 1}, world_id, None, LAND)
    assert composed["status"] == "done"
    made = composed["composed"]
    assert made.receipt["composer"] == {"key": "site-plan", "version": 5}
    drawing = json.loads(composed["body"])
    assert drawing["profile"] == "exulanica.site-drawing/v5"
    land = composed["land"]
    assert {f"{c['chunk'][0]},{c['chunk'][1]}" for c in drawing["land"]["chunks"]} == set(
        land["chunks"]
    )
    assert land["backdrop"]["sha256"] == drawing["land"]["backdrop_sha256"]
    # The drawing job, from the receipt alone, makes the same drawing and land.
    worker_module._records.clear()
    drawn = drawing_job("w", world_id, dict(made.receipt), made.receipt_sha256)
    assert (drawn["body"], drawn["sha256"], drawn["land"]) == (
        composed["body"],
        composed["sha256"],
        composed["land"],
    )
    # A land the catalog refuses is answered by name, never as unavailable work.
    refused = compose_job(
        "w", farm, {"width_mm": 96_000, "barns": 1}, world_id, None, {**LAND, "ground_mm": -1}
    )
    assert refused == {
        "status": "land_refused",
        "code": "landform_invalid",
        "detail": "land states -1, outside 0 to 40000",
        "path": "ground_mm",
    }


def test_a_town_on_land_s_land_names_by_digest_every_chunk_and_the_backdrop_it_is_given_with():
    from exulanica.grammar.landform import land_recipes
    from exulanica.world.composers import city_grammar_town as town
    from exulanica.world.generated_worlds import compose_generated_world
    from exulanica.world.world_recipes import town_recipe

    [coast] = [recipe for recipe in land_recipes() if recipe.key == "coast"]
    world_id = "world:generated:worker-town-land"
    on_land = town.on_land(town_recipe("small_town"), dict(coast.land))
    made = compose_generated_world(on_land, world_id)
    answer = worker_module.town_land_job(world_id, dict(made.receipt), made.receipt_sha256)
    assert answer["status"] == "done"
    section = json.loads(answer["body"])
    assert section["profile"] == worker_module.TOWN_LAND_PROFILE
    assert (section["world_id"], section["receipt_sha256"]) == (world_id, made.receipt_sha256)
    assert hashlib.sha256(answer["body"]).hexdigest() == answer["sha256"]
    land = answer["land"]
    named = {f"{c['chunk'][0]},{c['chunk'][1]}": c["sha256"] for c in section["land"]["chunks"]}
    assert named == {key: chunk["sha256"] for key, chunk in land["chunks"].items()}
    assert section["land"]["backdrop_sha256"] == land["backdrop"]["sha256"]
    for document in (*land["chunks"].values(), land["backdrop"]):
        assert hashlib.sha256(document["body"].encode("utf-8")).hexdigest() == document["sha256"]
    # A town on level ground states no land, and its receipt is refused by name.
    level = compose_generated_world(town_recipe("small_town"), world_id)
    refused = worker_module.town_land_job(world_id, dict(level.receipt), level.receipt_sha256)
    assert refused["status"] == "refused"
    assert refused["detail"].startswith("generated_world_land_changed")


@pytest.fixture(scope="module")
def on_a_landscape() -> tuple[dict[str, Any], int]:
    """The test farm made by the compose job on a landscape (a stack in the sea off its south
    edge), and how many of the stack's levels the making realized."""
    from exulanica.grammar.landscape import compose as volumes

    from test_landscape_world import WORLD, bay, compose
    from test_site_land import TILT, kind

    farm = kind("farm")
    realized: list[int] = []
    realize = volumes.realize_volume

    def counted(*args: Any) -> Any:
        realized.append(1)
        return realize(*args)

    landscape = bay(compose(land=TILT))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(volumes, "realize_volume", counted)
        composed = compose_job(
            "w", dict(farm.document), farm.values(farm.presets[0][0]), WORLD, None, None, landscape
        )
    return composed, len(realized)


def _landscape_of(composed: dict[str, Any]) -> tuple[str, dict[str, Any], str, str]:
    """What the landscape job is handed for a composed world: its world, its receipt and digest,
    and its site drawing's digest."""
    from test_landscape_world import WORLD

    made = composed["composed"]
    return WORLD, dict(made.receipt), made.receipt_sha256, composed["sha256"]


def test_a_site_on_a_landscape_is_made_without_its_volumes_and_its_landscape_drawn_by_its_own_job(
    on_a_landscape: tuple[dict[str, Any], int],
) -> None:
    from exulanica.world.landscape_drawing import (
        LANDSCAPE_DRAWING_PROFILE,
        landscape_drawing_sha256,
    )

    composed, realized = on_a_landscape
    assert composed["status"] == "done"
    assert composed["composed"].receipt["composer"] == {"key": "site-plan", "version": 6}
    # The making keeps the site's drawing, its land and its society's place, and realizes no
    # volume: its landscape's drawing is not made with it.
    assert composed["land"] and composed["placed"]["status"] == "done"
    assert "landscape" not in composed and realized == 0
    world_id, receipt, receipt_sha256, site_sha256 = _landscape_of(composed)
    drawn = landscape_job(world_id, receipt, receipt_sha256, site_sha256)
    assert drawn["status"] == "done"
    drawing = json.loads(drawn["body"])
    assert drawing["profile"] == LANDSCAPE_DRAWING_PROFILE
    assert (drawing["receipt_sha256"], drawing["site_drawing_sha256"]) == (
        receipt_sha256,
        site_sha256,
    )
    assert drawn["sha256"] == landscape_drawing_sha256(drawing)
    (stack,) = drawing["volumes"]
    assert {named["sha256"] for named in stack["chunks"]} == set(drawn["chunks"])
    assert {named["sha256"] for named in stack["tops"]} == set(drawn["tops"])
    # A receipt whose landscape no longer reads is refused by name, never unavailable work.
    changed = copy.deepcopy(receipt)
    changed["landscape_sha256"] = "0" * 64
    refused = landscape_job(world_id, changed, receipt_sha256, site_sha256)
    assert refused["status"] == "refused"
    assert refused["detail"].startswith("generated_world_landscape_changed")


def _ran(*_: object) -> dict[str, str]:
    return {"status": "refused", "detail": "ran"}


def test_a_landscape_past_its_limit_is_kept_and_read_again_by_its_own_workspace_alone(
    on_a_landscape: tuple[dict[str, Any], int],
) -> None:
    args = _landscape_of(on_a_landscape[0])
    receipt_sha256 = args[2]
    worker = KindWorker(lambda: ThreadPoolExecutor(1))
    key = landscape_key("w", receipt_sha256)
    released = threading.Event()

    def held(*job: Any) -> dict[str, Any]:
        # Past its limit by waiting, not by being slow: a landscape this process already realized
        # draws again at once.
        released.wait(30)
        return landscape_job(*job)

    try:
        first = worker.run(key, 0.0001, held, *args, workspace="w", kept=worker.landscapes)
        assert first.status == "overran"
        released.set()
        for _ in range(1200):
            if worker.landscapes.get(key) is not None:
                break
            time.sleep(0.05)
        # Asking again reads the finished drawing, byte for byte, and draws nothing.
        again = worker.run(key, 5.0, _ran, workspace="w", kept=worker.landscapes)
        assert again.status == "done" and again.value == landscape_job(*args)
        # Another workspace reads none of it: its own job runs.
        theirs = landscape_key("x", receipt_sha256)
        other = worker.run(theirs, 5.0, _ran, workspace="x", kept=worker.landscapes)
        assert other.value == {"status": "refused", "detail": "ran"}
        # The world's drawing is kept apart and is not the landscape's.
        assert worker.drawings.get(worker_module.drawing_key("w", receipt_sha256)) is None
    finally:
        worker.close()


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


def _until(condition: Any) -> None:
    for _ in range(250):
        if condition():
            return
        threading.Event().wait(0.02)
    raise AssertionError("never came to pass")


def test_a_personal_install_warms_the_settings_ground_unless_set_off_and_other_values_are_refused(
    tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    from exulanica.api.instance_settings import SocietySettingRefused, _warm_setting_grounds
    from exulanica.api.services import build_services

    spelled = (None, "", "  ", "on", "off")
    assert [_warm_setting_grounds(value, personal=True) for value in spelled] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert [_warm_setting_grounds(value, personal=False) for value in spelled] == [
        False,
        False,
        False,
        True,
        False,
    ]
    monkeypatch.setattr(
        "exulanica.api.services.load_account_runtime", lambda _: SimpleNamespace(guest=None)
    )
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    personal = {**environ, "EXULANICA_PERSONAL_INSTALL": "on"}
    assert build_services(environ).warm_setting_grounds is False
    assert build_services(personal).warm_setting_grounds is True
    off = {**personal, "EXULANICA_WARM_SETTING_GROUNDS": "off"}
    assert build_services(off).warm_setting_grounds is False
    # Any other value stops startup by name.
    with pytest.raises(SocietySettingRefused) as caught:
        build_services({**personal, "EXULANICA_WARM_SETTING_GROUNDS": "soon"})
    assert caught.value.code == "warm_setting_grounds_not_boolean"


def test_after_the_settings_ground_is_warmed_a_world_made_on_its_setting_realizes_no_ground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from exulanica.grammar.landscape import (
        LANDSCAPE_RULES_VERSION,
        read_landscape_document,
        starting_setting,
    )
    from exulanica.world import landscape_drawing as drawing_module
    from exulanica.world.kinds.library import shipped_kinds, starter_landscape

    # Stand-ins for realizing, which takes seconds: what is counted is each ground realized, in a
    # memo of the test's own.
    realized: list[str] = []

    def near(_land: Any, frame: Any) -> Any:
        realized.append(frame.seed)
        return SimpleNamespace(chunks=list)

    backdrop = SimpleNamespace(sha256="0" * 64, document=dict)
    monkeypatch.setattr(drawing_module, "realize_near", near)
    monkeypatch.setattr(drawing_module, "realize_backdrop", lambda *_: backdrop)
    monkeypatch.setattr(drawing_module, "water_bodies", lambda *_: [])
    monkeypatch.setattr(drawing_module, "_grounds", {})
    warmed = drawing_module.warm_setting_grounds()
    assert warmed["status"] == "done"
    assert warmed["warmed"] and len(realized) == len(warmed["warmed"])
    # Each kind that starts on the setting held last is drawn over the ground the warming realized.
    starters = [
        kind
        for kind in shipped_kinds()
        if (setting := starting_setting(kind.kind, kind.version)) is not None
        and setting.key == warmed["warmed"][-1]
    ]
    assert starters
    for kind in starters:
        landscape = read_landscape_document(starter_landscape(kind))
        drawing_module._ground(f"world:generated:{kind.kind}", landscape, LANDSCAPE_RULES_VERSION)
    assert len(realized) == len(warmed["warmed"])


@pytest.mark.parametrize("warm", [True, False])
def test_an_instance_asks_the_kind_worker_once_to_warm_the_settings_ground_and_never_waits(
    monkeypatch, tmp_path, warm: bool
) -> None:
    import asyncio
    from types import SimpleNamespace

    from exulanica.api.app import _lifespan
    from exulanica.world.landscape_drawing import warm_setting_grounds

    from test_account_control_integration import services

    release, asked_once = threading.Event(), threading.Event()
    asked: list[tuple[Any, ...]] = []

    class Worker:
        def run(
            self, key: str, seconds: float, job: Any, *args: Any, workspace: str, yields: bool
        ) -> None:
            # Released once startup is through: a startup that waited on the job would hold it.
            asked.append((key, seconds, job, args, workspace, yields, release.wait(5)))
            asked_once.set()

    monkeypatch.setattr("exulanica.api.app.kind_worker", Worker)
    monkeypatch.setattr("exulanica.api.app.verify_restore", lambda *_: None)
    monkeypatch.setattr("exulanica.api.app.seed_reviewed_assets", lambda *_: None)
    configured = services(tmp_path, warm_setting_grounds=warm)
    app = SimpleNamespace(state=SimpleNamespace(services=configured, verify_schema_at_boot=False))

    async def scenario() -> None:
        context = _lifespan(app)
        await context.__aenter__()
        release.set()
        await asyncio.to_thread(asked_once.wait, 5 if warm else 0.2)
        await context.__aexit__(None, None, None)

    asyncio.run(scenario())
    # Asked once, as work that yields to a person's, and not waited on.
    job = ("installation:warm-setting-grounds", 0.0, warm_setting_grounds, (), "installation")
    assert asked == ([(*job, True, True)] if warm else [])
