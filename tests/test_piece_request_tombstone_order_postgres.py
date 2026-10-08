"""An ask for pieces and its workspace's tombstone never interleave: no request stays open.

The store takes the workspace's lock (880024) before it writes. Each order is played at pause
points, never by timing, as ``tests/test_tombstone_workspace_lock_postgres.py`` plays them:

* the tombstone first: it holds its transaction open after its insert; the ask is seen waiting for
  the workspace's lock, and when the tombstone commits the ask is refused as tombstoned;
* the ask first: it is paused right after taking the lock; the tombstone is refused 40001 at once
  (migration 0137), the ask commits its request, and the deletion sent again cancels it.

The control runs first: with the store's lock taken out, the tombstone-first order leaves a
``requested`` row in the deleted workspace, so the test can fail.
"""

from __future__ import annotations

import threading
import uuid

import psycopg
import pytest
from exulanica.errors import TombstonedError
from exulanica.generation import store
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


def _ask(connection: psycopg.Connection, workspace_id: uuid.UUID):
    pack = LIBRARY.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=LIBRARY)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    return store.create_piece_requests(
        connection,
        workspace_id,
        requested_by=uuid.uuid4(),
        world_id=FIXTURE_WORLD_ID,
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(planned[0].variants)],
    )


def _workspace_tombstone(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'workspace', %s, 'the person left')",
        (workspace_id, uuid.uuid4()),
    )


def _requested(observer: psycopg.Connection, workspace_id: uuid.UUID) -> int:
    return observer.execute(
        "select count(*) as n from piece_request where workspace_id = %s and state = 'requested'",
        (workspace_id,),
    ).fetchone()["n"]


class AskInFlight:
    """An ask on a connection and thread of its own; its outcome is read by :meth:`finish`."""

    def __init__(self, spine_schema, workspace_id) -> None:
        self.error: BaseException | None = None
        self.connection = connection_in(spine_schema, workspace_id)
        self.pid = self.connection.info.backend_pid

        def ask() -> None:
            try:
                _ask(self.connection, workspace_id)
            except BaseException as exc:  # reported to the test's thread
                self.error = exc
            finally:
                self.connection.close()

        self.thread = threading.Thread(target=ask)
        self.thread.start()

    def finish(self) -> BaseException | None:
        self.thread.join(timeout=30)
        assert not self.thread.is_alive(), "the ask never finished"
        return self.error


@pytest.fixture
def workspace(repository):
    registered_world(repository.connection, repository.workspace_id)
    repository.connection.commit()
    return repository.workspace_id


def _tombstone_first(spine_schema, workspace_id, *, expect_wait: bool) -> BaseException | None:
    deleter = connection_in(spine_schema, workspace_id)
    observer = connection_in(spine_schema, workspace_id)
    try:
        deleter.execute("begin")
        _workspace_tombstone(deleter, workspace_id)
        asking = AskInFlight(spine_schema, workspace_id)
        if expect_wait:
            waiting(observer, asking.pid)
        else:
            asking.thread.join(timeout=30)
        deleter.execute("commit")
        return asking.finish()
    finally:
        deleter.close()
        observer.close()


def test_the_control_without_the_lock_leaves_a_request_in_a_deleted_workspace(
    workspace, spine_schema, monkeypatch
) -> None:
    monkeypatch.setattr(store, "lock_workspace", lambda connection, workspace_id: None)
    outcome = _tombstone_first(spine_schema, workspace, expect_wait=False)
    assert outcome is None, outcome
    observer = connection_in(spine_schema, workspace)
    try:
        assert _requested(observer, workspace) == 1
    finally:
        observer.close()


def test_an_ask_after_the_tombstone_waits_and_is_refused(workspace, spine_schema) -> None:
    outcome = _tombstone_first(spine_schema, workspace, expect_wait=True)
    assert isinstance(outcome, TombstonedError), outcome
    observer = connection_in(spine_schema, workspace)
    try:
        assert _requested(observer, workspace) == 0
    finally:
        observer.close()


def test_a_tombstone_during_an_ask_is_refused_and_sent_again_cancels_it(
    workspace, spine_schema, monkeypatch
) -> None:
    held, release = threading.Event(), threading.Event()

    def paused(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        lock_workspace(connection, workspace_id)
        held.set()
        assert release.wait(timeout=30)

    monkeypatch.setattr(store, "lock_workspace", paused)
    deleter = connection_in(spine_schema, workspace)
    observer = connection_in(spine_schema, workspace)
    try:
        deleter.execute("set lock_timeout = '5s'")
        asking = AskInFlight(spine_schema, workspace)
        assert held.wait(timeout=30)
        with pytest.raises(psycopg.errors.SerializationFailure, match=REFUSAL):
            _workspace_tombstone(deleter, workspace)
        release.set()
        assert asking.finish() is None
        assert _requested(observer, workspace) == 1
        _workspace_tombstone(deleter, workspace)
        assert _requested(observer, workspace) == 0
        [row] = observer.execute(
            "select state, failure from piece_request where workspace_id = %s",
            (workspace,),
        ).fetchall()
        assert (row["state"], row["failure"]) == ("cancelled", "workspace_deleted")
    finally:
        release.set()
        deleter.close()
        observer.close()
