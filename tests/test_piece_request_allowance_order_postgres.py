"""Two concurrent asks are weighed against the allowance one after the other, never both at once.

The store weighs an ask's new requests under the workspace's lock (880024), after its lookups. The
order is played at pause points, never by timing, as ``tests/test_piece_request_tombstone_order_
postgres.py`` plays it: the first ask is paused inside its weighing, having passed it; the second
is seen waiting for the workspace's lock; when the first commits, the second is weighed beside the
first's open request and refused. The allowance here covers either ask alone, not both.

The control runs first: with the store's lock taken out, the second ask is weighed while the first
is still paused, passes, and both requests are made, so the test can fail.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest
from exulanica.generation import store
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    generation_catalogs,
    plan_requests,
)
from exulanica.world.style_pack_library import style_pack_library

from test_tombstone_workspace_lock_postgres import connection_in, waiting
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

LIBRARY = style_pack_library()
COMPUTE = generation_catalogs().compute.for_provider(GPU_PROVIDER)


def _plan(kind: str):
    pack = LIBRARY.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    [planned] = plan_requests([(kind, 1)], look, library=LIBRARY)
    return look, planned, COMPUTE.worst_case_usd(planned.variants)


class Ask:
    """An ask on a connection and thread of its own, weighed against ``available``; when ``pause``
    is given it stops inside its weighing, having passed it, until the test lets it go."""

    def __init__(self, spine_schema, workspace_id, kind: str, available: Decimal, pause=None):
        self.error: BaseException | None = None
        self.connection = connection_in(spine_schema, workspace_id)
        self.pid = self.connection.info.backend_pid
        look, planned, worst = _plan(kind)

        def weigh(_connection, worst_case: Decimal, held: Decimal) -> None:
            if available - held < worst_case:
                raise store.PieceAllowanceRefused(f"{worst_case} over {available - held}")
            if pause is not None:
                pause[0].set()
                assert pause[1].wait(timeout=30), "the test never let the ask go"

        def ask() -> None:
            try:
                store.create_piece_requests(
                    self.connection,
                    workspace_id,
                    requested_by=uuid.uuid4(),
                    world_id=FIXTURE_WORLD_ID,
                    look=look,
                    planned=[planned],
                    worst_cases=[worst],
                    weigh=weigh,
                )
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


def _two_asks(spine_schema, workspace_id, *, expect_wait: bool) -> tuple:
    (_, _, well), (_, _, gate) = _plan("well"), _plan("gate")
    available = max(well, gate)
    assert well + gate > available, "the allowance must cover either ask alone, not both"
    weighed, go = threading.Event(), threading.Event()
    observer = connection_in(spine_schema, workspace_id)
    try:
        first = Ask(spine_schema, workspace_id, "well", available, pause=(weighed, go))
        assert weighed.wait(timeout=30), "the first ask was never weighed"
        second = Ask(spine_schema, workspace_id, "gate", available)
        if expect_wait:
            waiting(observer, second.pid)
        else:
            second.thread.join(timeout=30)
        go.set()
        outcomes = (first.finish(), second.finish())
        made = observer.execute(
            "select kind_key from piece_request where workspace_id = %s order by kind_key",
            (workspace_id,),
        ).fetchall()
        return outcomes, [row["kind_key"] for row in made]
    finally:
        go.set()
        observer.close()


def test_the_control_without_the_lock_weighs_both_at_once(
    spine_schema, workspace, monkeypatch
) -> None:
    monkeypatch.setattr(store, "lock_workspace", lambda _connection, _workspace_id: None)
    outcomes, made = _two_asks(spine_schema, workspace, expect_wait=False)
    assert outcomes == (None, None)
    assert made == ["gate", "well"]


def test_the_second_ask_waits_and_is_weighed_beside_the_first(spine_schema, workspace) -> None:
    (first, second), made = _two_asks(spine_schema, workspace, expect_wait=True)
    assert first is None
    assert isinstance(second, store.PieceAllowanceRefused)
    assert made == ["well"]
