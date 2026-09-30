"""A dead traffic process does not poison subsequent catalog or replay jobs."""

import time
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import exulanica.api.traffic_signal_controller as controller_module
import pytest
from exulanica.api.traffic_signal_controller import TrafficSignalController
from exulanica.world.traffic_signal_repository import SignalChoiceRefused


class Pool:
    def __init__(self, result=None, *, broken=False):
        self.result = result
        self.broken = broken
        self.terminated = False

    def submit(self, _function, *_args):
        future = Future()
        if self.broken:
            future.set_exception(BrokenProcessPool("worker exited"))
        else:
            future.set_result(self.result)
        return future

    def terminate_workers(self):
        self.terminated = True

    def shutdown(self, **_kwargs):
        self.terminated = True


def _controller():
    return TrafficSignalController(None, None, (), lambda _workspace: None)


def test_a_broken_owned_worker_is_replaced_for_the_next_pure_job(monkeypatch):
    first, second = Pool(broken=True), Pool("rebuilt")
    pools = iter((first, second))
    monkeypatch.setattr(controller_module, "worker_pool", lambda _initializer: next(pools))
    controller = _controller()
    assert controller._worker(str, "input") == "rebuilt"
    assert first.terminated
    assert controller._worker(str, "again") == "rebuilt"
    controller.close()


def test_two_broken_workers_end_in_a_named_refusal(monkeypatch):
    first, second = Pool(broken=True), Pool(broken=True)
    pools = iter((first, second))
    monkeypatch.setattr(controller_module, "worker_pool", lambda _initializer: next(pools))
    controller = _controller()
    with pytest.raises(SignalChoiceRefused, match="traffic_worker_unavailable"):
        controller._worker(str, "input")
    assert first.terminated and second.terminated
    controller.close()


def test_a_real_timeout_reaps_both_owned_replacement_workers(monkeypatch):
    monkeypatch.setattr(controller_module, "_PROBE_SECONDS", 0.2)
    retired = []
    original = TrafficSignalController._retire_pool

    def inspect_retirement(self, pool):
        retired.extend((getattr(pool, "_processes", None) or {}).values())
        original(self, pool)

    monkeypatch.setattr(TrafficSignalController, "_retire_pool", inspect_retirement)
    controller = _controller()
    try:
        with pytest.raises(SignalChoiceRefused, match="traffic_worker_unavailable"):
            controller._worker(time.sleep, 5)
    finally:
        controller.close()
    assert len(retired) == 2
    assert all(process.exitcode is not None and not process.is_alive() for process in retired)


def test_close_reaps_an_owned_worker_with_a_running_job():
    controller = _controller()
    pool = controller._process()
    pool.submit(time.sleep, 5)
    processes = tuple((getattr(pool, "_processes", None) or {}).values())
    assert len(processes) == 1
    started = time.monotonic()
    controller.close()
    assert time.monotonic() - started < 2
    assert all(process.exitcode is not None and not process.is_alive() for process in processes)
