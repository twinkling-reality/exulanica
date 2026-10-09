"""The generation worker's end of a batch and its workspace's tombstone never interleave.

The worker takes the workspace's lock (880024) before it writes a batch's end, as an ask and a
deletion take it. Each order is played at pause points, never by timing, as
``tests/test_piece_request_tombstone_order_postgres.py`` plays the ask:

* the tombstone first: it holds its transaction open after its insert; the batch's end is seen
  waiting for the workspace's lock, and when the tombstone commits the batch is gone (its rows
  erased), so the end writes nothing; the request the tombstone cancelled is then decided
  ``unknown`` so its reservation is still settled;
* the end first: it is paused right after taking the lock; the tombstone is refused 40001 at once
  (migration 0137), the end commits the request's end and its settlement, and the deletion sent
  again erases the batch and keeps the settlement.

The control runs first: with the worker's lock taken out, a tombstone written while a batch's end
is in progress is not refused, so the test can fail.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.generation import batches, store
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    generation_catalogs,
    plan_requests,
)
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.workspace_lock import lock_workspace

from test_tombstone_workspace_lock_postgres import REFUSAL, connection_in, waiting
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

LIBRARY = style_pack_library()


def _queued(connection: psycopg.Connection, workspace_id: uuid.UUID) -> uuid.UUID:
    pack = LIBRARY.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=LIBRARY)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    (made,), _ = store.create_piece_requests(
        connection,
        workspace_id,
        requested_by=uuid.uuid4(),
        world_id=FIXTURE_WORLD_ID,
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(planned[0].variants)],
    )
    now = dt.datetime.now(dt.UTC)
    batches.record_batch(
        connection,
        workspace_id,
        generation_session_id=uuid.uuid4(),
        job_raw=b'{"a job":"for the test"}',
        queued_at=now,
        not_after=now + dt.timedelta(hours=1),
        queued=[
            batches.QueuedReservation(
                piece_request_id=made.piece_request_id,
                reservation_id=uuid.uuid4(),
                authority_id=uuid.uuid4(),
                holder="worker:test",
            )
        ],
    )
    return made.piece_request_id


def _workspace_tombstone(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'workspace', %s, 'the person left')",
        (workspace_id, uuid.uuid4()),
    )


class EndInFlight:
    """A batch's end on a connection and thread of its own; its outcome is read by :meth:`finish`.
    With ``pause``, it waits on that event right after taking the workspace's lock."""

    def __init__(self, spine_schema, workspace_id, pause: threading.Event | None = None) -> None:
        self.error: BaseException | None = None
        self.paused = threading.Event()
        self.connection = connection_in(spine_schema, workspace_id)
        self.pid = self.connection.info.backend_pid
        [batch] = batches.batches_in_flight(self.connection, workspace_id)

        def end() -> None:
            try:
                batches.end_batch(
                    self.connection,
                    workspace_id,
                    batch,
                    state="expired",
                    ended_at=dt.datetime.now(dt.UTC),
                    settlements={
                        r.piece_request_id: ("not_sent", Decimal(0)) for r in batch.requests
                    },
                )
            except BaseException as exc:  # reported to the test's thread
                self.error = exc
            finally:
                self.connection.close()

        self.pause = pause
        self.thread = threading.Thread(target=end)
        self.thread.start()

    def finish(self) -> BaseException | None:
        if self.pause is not None:
            self.pause.set()
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "the batch's end never finished"
        return self.error


@pytest.fixture
def workspace(repository):
    registered_world(repository.connection, repository.workspace_id)
    request = _queued(repository.connection, repository.workspace_id)
    repository.connection.commit()
    return repository.workspace_id, request


def _pausing_lock(monkeypatch, pause: threading.Event, paused: threading.Event, *, real: bool):
    def lock(connection, workspace_id):
        if real:
            lock_workspace(connection, workspace_id)
        paused.set()
        assert pause.wait(timeout=30)

    monkeypatch.setattr(batches, "lock_workspace", lock)


def _end_first(spine_schema, workspace_id, monkeypatch, *, real_lock: bool):
    pause, paused = threading.Event(), threading.Event()
    _pausing_lock(monkeypatch, pause, paused, real=real_lock)
    ending = EndInFlight(spine_schema, workspace_id, pause)
    assert paused.wait(timeout=30)
    deleter = connection_in(spine_schema, workspace_id)
    try:
        try:
            _workspace_tombstone(deleter, workspace_id)
            refused = None
        except psycopg.Error as error:
            refused = error
        outcome = ending.finish()
        return refused, outcome
    finally:
        deleter.close()


def test_the_control_without_the_lock_lets_a_tombstone_through_a_batch_s_end(
    workspace, spine_schema, monkeypatch
) -> None:
    workspace_id, _ = workspace
    refused, _ = _end_first(spine_schema, workspace_id, monkeypatch, real_lock=False)
    assert refused is None


def test_a_tombstone_during_a_batch_s_end_is_refused_and_the_end_commits(
    workspace, spine_schema, monkeypatch
) -> None:
    workspace_id, request = workspace
    refused, outcome = _end_first(spine_schema, workspace_id, monkeypatch, real_lock=True)
    assert refused is not None and REFUSAL in str(refused), refused
    assert outcome is None, outcome
    monkeypatch.undo()
    observer = connection_in(spine_schema, workspace_id)
    try:
        _workspace_tombstone(observer, workspace_id)
        [row] = observer.execute(
            "select state, failure from piece_request where piece_request_id = %s", (request,)
        ).fetchall()
        assert (row["state"], row["failure"]) == ("failed", "session_ended")
        assert observer.execute("select count(*) as n from piece_batch").fetchone()["n"] == 0
        [settlement] = observer.execute("select basis from piece_settlement").fetchall()
        assert settlement["basis"] == "not_sent"
    finally:
        observer.close()


def test_a_batch_s_end_after_the_tombstone_waits_and_writes_nothing(
    workspace, spine_schema
) -> None:
    workspace_id, request = workspace
    deleter = connection_in(spine_schema, workspace_id)
    observer = connection_in(spine_schema, workspace_id)
    try:
        deleter.execute("begin")
        _workspace_tombstone(deleter, workspace_id)
        ending = EndInFlight(spine_schema, workspace_id)
        waiting(observer, ending.pid)
        deleter.execute("commit")
        outcome = ending.finish()
        assert isinstance(outcome, batches.BatchNotOpen), outcome
        [row] = observer.execute(
            "select state, failure from piece_request where piece_request_id = %s", (request,)
        ).fetchall()
        assert (row["state"], row["failure"]) == ("cancelled", "workspace_deleted")
        assert observer.execute("select count(*) as n from piece_settlement").fetchone()["n"] == 0
        # The worker's next pass decides it unknown: whether a session ran it is not known.
        assert batches.decide_cancelled(observer, workspace_id) == 1
        [settlement] = observer.execute("select basis, usd from piece_settlement").fetchall()
        assert (settlement["basis"], settlement["usd"]) == ("unknown", Decimal("0.06"))
    finally:
        deleter.close()
        observer.close()
