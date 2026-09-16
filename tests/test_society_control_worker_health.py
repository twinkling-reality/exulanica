"""Pure thread-health evidence; no database, lease or service is started."""

import logging
import threading
import uuid

import pytest
from exulanica.api.society_control_worker import SocietyControlWorker


class BoundedStop:
    def __init__(self, rounds: int) -> None:
        self.rounds = rounds
        self.completed = 0

    def is_set(self) -> bool:
        return self.completed >= self.rounds

    def wait(self, _seconds: float) -> bool:
        self.completed += 1
        return self.is_set()


def worker() -> SocietyControlWorker:
    return SocietyControlWorker(None, runtime=None, workspaces=[uuid.UUID(int=1)])


def test_failed_round_is_counted_without_exposing_exception_text(monkeypatch, caplog):
    playback = worker()

    def fail(_workspace):
        raise RuntimeError("provider-secret-that-must-not-escape")

    monkeypatch.setattr(playback, "_run_authorized_once", fail)
    with caplog.at_level(logging.ERROR):
        playback.run(BoundedStop(1))

    assert playback.health == {
        "failed_rounds": 1,
        "last_round_failed": True,
    }
    assert "provider-secret-that-must-not-escape" not in caplog.text


def test_full_successful_round_clears_error_and_retains_failure_count(monkeypatch):
    playback = worker()
    attempts = 0

    def recover(_workspace):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first round fails")
        return None

    monkeypatch.setattr(playback, "_run_authorized_once", recover)
    playback.run(BoundedStop(2))

    assert playback.health == {
        "failed_rounds": 1,
        "last_round_failed": False,
    }


def test_health_snapshot_is_a_copy_and_safe_during_reads(monkeypatch):
    playback = worker()
    entered = threading.Event()
    release = threading.Event()

    def blocked(_workspace):
        entered.set()
        assert release.wait(2)
        return None

    monkeypatch.setattr(playback, "_run_authorized_once", blocked)
    thread = threading.Thread(target=playback.run, args=(BoundedStop(1),))
    thread.start()
    assert entered.wait(2)
    initial = playback.health
    initial["failed_rounds"] = 99
    assert playback.health == {
        "failed_rounds": 0,
        "last_round_failed": False,
    }
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert playback.health["last_round_failed"] is False


def test_interrupted_partial_round_does_not_replace_completed_health(monkeypatch):
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    playback = SocietyControlWorker(None, runtime=None, workspaces=[first, second])
    stop = threading.Event()

    def interrupted(workspace):
        stop.set()
        if workspace == first:
            raise RuntimeError("failure before the round completed")
        raise AssertionError("the stopped round must not visit another workspace")

    monkeypatch.setattr(playback, "_run_authorized_once", interrupted)
    playback.run(stop)

    assert playback.health == {
        "failed_rounds": 0,
        "last_round_failed": False,
    }


def test_each_bounded_round_uses_a_fresh_dynamic_workspace_snapshot(monkeypatch):
    first, second = uuid.UUID(int=1), uuid.UUID(int=2)
    snapshots = iter((frozenset({first}), frozenset({second})))
    playback = SocietyControlWorker(
        None, runtime=None, workspaces=(), workspace_source=lambda: next(snapshots)
    )
    attempted = []
    monkeypatch.setattr(
        playback, "_run_authorized_once", lambda workspace: attempted.append(workspace)
    )

    playback.run(BoundedStop(2))

    assert attempted == [first, second]
    assert playback.workspaces == (second,)


def test_direct_playback_does_not_treat_the_last_health_snapshot_as_authority(monkeypatch):
    workspace = uuid.uuid4()
    snapshots = iter((frozenset({workspace}), frozenset()))
    playback = SocietyControlWorker(
        None, runtime=None, workspaces=(), workspace_source=lambda: next(snapshots)
    )
    assert playback._workspace_snapshot() == (workspace,)
    monkeypatch.setattr(
        playback,
        "_run_authorized_once",
        lambda _workspace: (_ for _ in ()).throw(AssertionError("stale authority was used")),
    )

    with pytest.raises(ValueError, match="not configured"):
        playback.run_once(workspace)


def test_discovery_failure_is_fail_closed_and_recovers_without_logging_details(caplog):
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("account-role-secret-that-must-not-escape")
        return ()

    playback = SocietyControlWorker(None, runtime=None, workspaces=(), workspace_source=discover)
    with caplog.at_level(logging.ERROR):
        playback.run(BoundedStop(2))

    assert playback.health == {"failed_rounds": 1, "last_round_failed": False}
    assert "account-role-secret-that-must-not-escape" not in caplog.text
