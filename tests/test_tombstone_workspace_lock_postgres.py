"""A tombstone never waits for its workspace's lock (migration 0137).

A tombstone holds migration 0041's asset read barrier on its shared side from its first BEFORE
trigger, and 0020's structural invalidation then takes its workspace's lock. A transaction that
reads assets as it writes takes the two the other way round, the workspace's lock and then the
barrier's exclusive side, so a tombstone written between a reader's two locks waited for the
reader while the reader waited for it, until PostgreSQL ended one of them (40P01). Each test plays
that interleaving at pause points, never by timing: the reader holds its workspace's lock, the
tombstone is written and seen waiting or refused, and only then does the reader ask for the
barrier.

* Each test runs its control first, with 0137's refusal planted out of the trigger: the same
  interleaving ends in a deadlock, so the test can fail.
* With the refusal, the tombstone is refused 40001 at once and nothing of it is written, the
  reader takes the barrier and commits, and the deletion sent again is written.
* A transaction that already holds its workspace's lock writes a tombstone.
* The reader of the last test is a society's minute stepped by hand
  (``SocietyRepository.advance``), paused in ``SocietyRuntime._read_ahead``: after the minute's
  workspace lock, before its asset read lock.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
import pytest
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import set_workspace
from exulanica.world.workspace_lock import lock_workspace
from psycopg.rows import dict_row

import test_society_runtime as helpers
from pg_harness import open_scratch_connection

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres

#: Migration 0137's trigger function and the refusal it raises.
TRIGGER = "tg_a_tombstone_never_waits_for_its_workspace_s_lock()"
REFUSAL = "workspace in use; retry the deletion"
_REASON = "a deletion written while its workspace's lock is held"


def connection_in(spine_schema, workspace_id: uuid.UUID) -> psycopg.Connection:
    """An autocommitting connection of its own into the migrated schema, in ``workspace_id``."""
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.row_factory = dict_row
    set_workspace(connection, workspace_id)
    return connection


def write_tombstone(connection: psycopg.Connection, workspace_id: uuid.UUID, actor: uuid.UUID):
    """A capture's deletion, as one statement: its own transaction on an autocommitting
    connection, or a statement of the caller's open one."""
    connection.execute(
        "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
        "values (%s, 'capture', %s, %s, %s)",
        (workspace_id, uuid.uuid4(), actor, _REASON),
    )


def written(connection: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    return connection.execute(
        "select count(*) as n from tombstone where workspace_id=%s and reason=%s",
        (workspace_id, _REASON),
    ).fetchone()["n"]


def waiting(observer: psycopg.Connection, pid: int, seconds: float = 10.0) -> None:
    """Return once backend ``pid`` waits for a lock, or fail: a pause point, not a timing."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = observer.execute(
            "select wait_event_type from pg_stat_activity where pid=%s", (pid,)
        ).fetchone()
        if row is not None and row["wait_event_type"] == "Lock":
            return
        time.sleep(0.02)
    raise AssertionError(f"backend {pid} never waited for a lock")


@contextmanager
def refusal_planted_out(owner: psycopg.Connection) -> Iterator[None]:
    """0137's trigger with its refusal taken out, as the schema was before it, and put back."""
    original = owner.execute(
        "select pg_get_functiondef(%s::regprocedure) as body", (TRIGGER,)
    ).fetchone()["body"]
    planted = re.sub(
        r"if not pg_try_advisory_xact_lock.*?end if;", "null;", original, count=1, flags=re.S
    )
    assert planted != original
    owner.execute(planted)
    try:
        yield
    finally:
        owner.execute(original)


class DeletionInFlight:
    """A tombstone written on a connection and thread of its own, returned once it waits."""

    def __init__(self, spine_schema, workspace_id, actor, observer) -> None:
        self.error: BaseException | None = None
        deleter = connection_in(spine_schema, workspace_id)
        pid = deleter.info.backend_pid

        def delete() -> None:
            try:
                write_tombstone(deleter, workspace_id, actor)
            except BaseException as exc:  # reported to the test's thread
                self.error = exc
            finally:
                deleter.close()

        self.thread = threading.Thread(target=delete)
        self.thread.start()
        waiting(observer, pid)

    def finish(self) -> BaseException | None:
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "the deletion never finished"
        return self.error


def deadlocks(*outcomes: BaseException | None) -> int:
    return sum(isinstance(outcome, psycopg.errors.DeadlockDetected) for outcome in outcomes)


def test_a_tombstone_is_refused_rather_than_wait_for_a_workspace_lock_another_transaction_holds(
    repository, spine_schema
):
    workspace, actor = repository.workspace_id, uuid.uuid4()
    reader = connection_in(spine_schema, workspace)
    observer = connection_in(spine_schema, workspace)
    try:
        # The control: the tombstone takes the barrier's shared side, waits for the workspace
        # lock the reader holds, and the reader's exclusive request closes the cycle.
        with refusal_planted_out(repository.connection):
            reader.execute("begin")
            lock_workspace(reader, workspace)
            deletion = DeletionInFlight(spine_schema, workspace, actor, observer)
            try:
                reader.execute("select asset_read_lock()")
                reader.execute("commit")
                read = None
            except psycopg.errors.DeadlockDetected as exc:
                read = exc
                reader.execute("rollback")
            assert deadlocks(read, deletion.finish()) == 1, (read, deletion.error)

        before = written(observer, workspace)
        deleter = connection_in(spine_schema, workspace)
        try:
            # A wait would end in 55P03 here rather than hang the test.
            deleter.execute("set lock_timeout = '5s'")
            reader.execute("begin")
            lock_workspace(reader, workspace)
            with pytest.raises(psycopg.errors.SerializationFailure, match=REFUSAL):
                write_tombstone(deleter, workspace, actor)
            assert written(observer, workspace) == before
            reader.execute("set local lock_timeout = '5s'")
            reader.execute("select asset_read_lock()")
            reader.execute("commit")
            write_tombstone(deleter, workspace, actor)
            assert written(observer, workspace) == before + 1
        finally:
            deleter.close()
    finally:
        reader.close()
        observer.close()


def test_a_transaction_holding_its_workspace_lock_writes_a_tombstone(repository, spine_schema):
    workspace, actor = repository.workspace_id, uuid.uuid4()
    writer = connection_in(spine_schema, workspace)
    try:
        before = written(writer, workspace)
        writer.execute("begin")
        lock_workspace(writer, workspace)
        write_tombstone(writer, workspace, actor)
        writer.execute("commit")
        assert written(writer, workspace) == before + 1
    finally:
        writer.close()


def test_a_minute_stepped_by_hand_meets_a_tombstone_between_its_two_locks(
    runtime_world, spine_schema, monkeypatch
):
    w = runtime_world
    workspace, actor, version = w["workspace"], w["session"].actor, w["binding"].version_id
    helpers.create(w)
    observer = connection_in(spine_schema, workspace)
    paused: list[Callable[[], None]] = []
    read_ahead = SocietyRuntime._read_ahead

    def pausing(self, *args, **kwargs):
        # The minute holds its workspace's lock here and has not asked for the barrier yet.
        if paused:
            paused.pop()()
        return read_ahead(self, *args, **kwargs)

    monkeypatch.setattr(SocietyRuntime, "_read_ahead", pausing)
    try:
        # The control: the minute's asset read lock closes the cycle with the waiting tombstone.
        with refusal_planted_out(w["connection"]):
            flight: list[DeletionInFlight] = []
            current = helpers.society(w).snapshot(version)
            paused.append(
                lambda: flight.append(DeletionInFlight(spine_schema, workspace, actor, observer))
            )
            try:
                helpers.society(w).advance(
                    version,
                    base_tick=current["current_tick"],
                    base_state_sha256=current["state_sha256"],
                )
                stepped = None
            except psycopg.errors.DeadlockDetected as exc:
                stepped = exc
            assert deadlocks(stepped, flight[0].finish()) == 1, (stepped, flight[0].error)

        refused: list[BaseException] = []

        def refuse() -> None:
            deleter = connection_in(spine_schema, workspace)
            try:
                deleter.execute("set lock_timeout = '5s'")
                write_tombstone(deleter, workspace, actor)
            except psycopg.Error as exc:
                refused.append(exc)
            finally:
                deleter.close()

        current = helpers.society(w).snapshot(version)
        before = written(observer, workspace)
        paused.append(refuse)
        after = helpers.society(w).advance(
            version, base_tick=current["current_tick"], base_state_sha256=current["state_sha256"]
        )
        assert [type(exc) for exc in refused] == [psycopg.errors.SerializationFailure], refused
        assert refused[0].diag.message_primary == REFUSAL
        assert after["current_tick"] == current["current_tick"] + 1
        assert written(observer, workspace) == before
    finally:
        observer.close()
