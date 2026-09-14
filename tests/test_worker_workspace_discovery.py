"""Dynamic derivative scope without an account import or retained authority cache."""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager

import pytest
from exulanica.ingest import derivative_queue
from exulanica.ingest import worker as worker_module
from exulanica.ingest.worker import DerivativeWorker, JobOutcome


def test_derivative_snapshots_union_static_scope_and_drop_removed_dynamic_scope():
    configured, first, second = (uuid.uuid4() for _ in range(3))
    snapshots = iter((frozenset({first}), frozenset({second})))
    worker = DerivativeWorker(
        None,
        None,
        frozenset({configured}),
        workspace_source=lambda: next(snapshots),
    )

    assert worker._workspace_snapshot() == frozenset({configured, first})
    assert worker._workspace_snapshot() == frozenset({configured, second})
    assert worker.workspace_count == 2


def test_derivative_discovery_rejects_non_uuid_authority():
    worker = DerivativeWorker(
        None, None, frozenset(), workspace_source=lambda: ("not-a-workspace",)
    )
    with pytest.raises(TypeError, match="must return UUIDs"):
        worker._workspace_snapshot()
    assert worker.workspace_count == 0


def test_busy_derivative_scope_is_refreshed_before_another_job(monkeypatch):
    workspace = uuid.uuid4()
    current = {workspace}
    snapshots = 0

    def discover():
        nonlocal snapshots
        snapshots += 1
        return frozenset(current)

    class Database:
        @contextmanager
        def session(self, _workspace):
            yield object()

    monkeypatch.setattr(
        worker_module,
        "IngestRepository",
        lambda _connection, scoped: type("Repository", (), {"workspace_id": scoped})(),
    )
    worker = DerivativeWorker(Database(), None, frozenset(), workspace_source=discover)
    claims = 0

    def claim(_connection, _repository):
        nonlocal claims
        claims += 1
        current.clear()
        return JobOutcome(job_id=uuid.uuid4(), batch_id=uuid.uuid4())

    monkeypatch.setattr(worker, "_claim_one", claim)

    assert len(worker.drain()) == 1
    assert claims == 1
    assert snapshots == 2


def test_derivative_discovery_failure_recovers_and_shutdown_does_not_rediscover():
    recovered = threading.Event()
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("account store unavailable")
        recovered.set()
        return ()

    worker = DerivativeWorker(
        None,
        None,
        frozenset(),
        workspace_source=discover,
        poll_seconds=0.05,
    )
    worker.start()
    assert recovered.wait(1)
    before_stop = calls
    assert worker.stop(timeout=1)
    assert calls == before_stop
    assert worker.failed_passes == 1


def test_shutdown_lifecycle_uses_only_static_host_scope(monkeypatch):
    configured, discovered = uuid.uuid4(), uuid.uuid4()
    visited = []

    class Database:
        @contextmanager
        def session(self, workspace):
            visited.append(workspace)
            yield object()

    monkeypatch.setattr(derivative_queue, "record_worker_event", lambda *args, **kwargs: None)
    worker = DerivativeWorker(
        Database(),
        None,
        frozenset({configured}),
        workspace_source=lambda: frozenset({discovered}),
    )
    worker._workspace_snapshot()

    worker._record_worker_lifecycle("worker_stopped")

    assert visited == [configured]
