"""A playback round's claims, one workspace after another or several at once.

``EXULANICA_PLAYBACK_WORKERS`` absent is 1: the round runs each claim in turn on the playback
thread, exactly as before the setting existed. More runs that many claims at once on a pool, each
pool thread holding the round's workspace snapshot as its authority, so one workspace's slow model
answers do not hold another's minute. These tests run the worker's own loop with the claim itself
stubbed: the database is not needed to show who runs which claim, on which thread, with which
authority.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from exulanica.api import society_control_worker as worker_module
from exulanica.api.services import SocietySettingRefused, _playback_workers
from exulanica.api.society_control_worker import SocietyControlWorker

WORKSPACES = tuple(uuid.UUID(int=n) for n in (1, 2, 3, 4))


def _worker(workers: int) -> SocietyControlWorker:
    return SocietyControlWorker(
        None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        workspaces=WORKSPACES,
        workers=workers,
    )


def _one_round(worker: SocietyControlWorker, claim) -> None:
    """Run the worker's loop for one round: the stub stops it after the last workspace."""
    stop, seen = threading.Event(), []
    lock = threading.Lock()

    def stubbed(workspace: uuid.UUID):
        try:
            return claim(workspace)
        finally:
            with lock:
                seen.append(workspace)
                if len(seen) == len(WORKSPACES):
                    stop.set()

    worker._run_authorized_once = stubbed  # type: ignore[method-assign]
    runner = threading.Thread(target=worker.run, args=(stop,), kwargs={"poll_seconds": 0.05})
    runner.start()
    runner.join(timeout=30)
    assert not runner.is_alive(), "the round did not end"


def test_one_worker_is_the_turn_by_turn_round_on_the_playback_thread(monkeypatch):
    def no_pool(*args, **kwargs):
        raise AssertionError("a round with one worker builds no pool")

    monkeypatch.setattr(worker_module, "ThreadPoolExecutor", no_pool)
    worker = _worker(1)
    calls: list[tuple[uuid.UUID, str, frozenset | None]] = []

    def claim(workspace):
        calls.append(
            (
                workspace,
                threading.current_thread().name,
                getattr(worker._round_authority, "workspaces", None),
            )
        )

    _one_round(worker, claim)
    assert [workspace for workspace, _, _ in calls] == sorted(WORKSPACES, key=str)
    assert len({thread for _, thread, _ in calls}) == 1
    assert {authority for _, _, authority in calls} == {frozenset(WORKSPACES)}
    assert worker.health["last_round_failed"] is False


def test_several_workers_run_claims_at_once_each_with_the_rounds_authority():
    worker = _worker(4)
    # All four claims must be under way together before any may finish.
    together = threading.Barrier(4, timeout=10)
    calls: list[tuple[str, frozenset | None]] = []
    lock = threading.Lock()

    def claim(workspace):
        together.wait()
        with lock:
            calls.append(
                (
                    threading.current_thread().name,
                    getattr(worker._round_authority, "workspaces", None),
                )
            )

    _one_round(worker, claim)
    assert len({thread for thread, _ in calls}) == 4
    assert {authority for _, authority in calls} == {frozenset(WORKSPACES)}
    # The pool threads leave no authority behind on the playback thread.
    assert getattr(worker._round_authority, "workspaces", None) is None


def test_a_failing_claim_fails_the_round_and_the_others_still_run():
    worker = _worker(2)
    ran: list[uuid.UUID] = []
    lock = threading.Lock()

    def claim(workspace):
        if workspace == WORKSPACES[1]:
            raise RuntimeError("a claim failed")
        with lock:
            ran.append(workspace)

    _one_round(worker, claim)
    assert set(ran) == set(WORKSPACES) - {WORKSPACES[1]}
    assert worker.health["last_round_failed"] is True


def test_the_setting_is_one_when_absent_and_refused_outside_one_to_eight():
    assert _playback_workers(None) == _playback_workers("") == 1
    assert _playback_workers("4") == 4
    for refused in ("0", "9", "two", "-1", "1.5"):
        with pytest.raises(SocietySettingRefused) as named:
            _playback_workers(refused)
        assert named.value.code == "playback_workers_out_of_bounds"
    with pytest.raises(ValueError):
        _worker(0)


def test_a_pool_that_fails_records_a_failed_round_and_playback_goes_on(monkeypatch):
    """The pool itself failing (no thread to start) is a failed round, as a claim's failure is,
    not the end of playback until a restart."""

    class Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(worker_module, "ThreadPoolExecutor", Broken)
    worker = _worker(2)
    stop = threading.Event()
    runner = threading.Thread(target=worker.run, args=(stop,), kwargs={"poll_seconds": 0.05})
    runner.start()
    try:
        for _ in range(200):
            if worker.health["failed_rounds"] >= 2:
                break
            threading.Event().wait(0.05)
        assert worker.health["failed_rounds"] >= 2, "playback stopped after the pool failed"
        assert runner.is_alive()
        assert worker.health["last_round_failed"] is True
    finally:
        stop.set()
        runner.join(timeout=10)


def test_one_pool_serves_every_round_and_ends_with_playback(monkeypatch):
    built: list[object] = []
    real = worker_module.ThreadPoolExecutor

    def counted(*args, **kwargs):
        pool = real(*args, **kwargs)
        built.append(pool)
        return pool

    monkeypatch.setattr(worker_module, "ThreadPoolExecutor", counted)
    worker = _worker(2)
    claims: list[uuid.UUID] = []
    worker._run_authorized_once = claims.append  # type: ignore[method-assign]
    stop = threading.Event()
    runner = threading.Thread(target=worker.run, args=(stop,), kwargs={"poll_seconds": 0.05})
    runner.start()
    try:
        for _ in range(200):
            if len(claims) >= 3 * len(WORKSPACES):
                break
            threading.Event().wait(0.05)
        assert len(claims) >= 3 * len(WORKSPACES), "three rounds did not run"
    finally:
        stop.set()
        runner.join(timeout=10)
    assert len(built) == 1, "a pool per round"
    assert worker._pool is None
    with pytest.raises(RuntimeError):
        built[0].submit(lambda: None)  # shut down with playback
