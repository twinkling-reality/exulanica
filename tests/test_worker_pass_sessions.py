"""A worker's pass holds one database session at a time, however many workspaces it visits.

The preparation and material bake workers once opened a session for every workspace at the start
of a pass and held them all until it ended: with a few hundred account workspaces that is most of
PostgreSQL's connections every slow scan. Each drain here runs over stand-ins for the database and
the work, counting sessions open at once, and still serves every claim in turn."""

from __future__ import annotations

import contextlib
import threading
import uuid
from types import SimpleNamespace

import pytest
from exulanica.world.asset_preparation import AssetPreparationWorker
from exulanica.world.material_bakes import MaterialBakeWorker

WORKSPACES = [uuid.UUID(int=n) for n in range(1, 6)]
CLAIMS_EACH = 2


class _Database:
    def __init__(self) -> None:
        self.open = 0
        self.most = 0

    @contextlib.contextmanager
    def session(self, workspace_id):
        self.open += 1
        self.most = max(self.most, self.open)
        try:
            yield SimpleNamespace(workspace=workspace_id)
        finally:
            self.open -= 1


@pytest.mark.parametrize(
    ("worker_class", "serve"),
    [(AssetPreparationWorker, "_prepare_one"), (MaterialBakeWorker, "_bake_one")],
)
def test_a_pass_holds_one_session_at_a_time_and_serves_every_claim(worker_class, serve):
    database = _Database()
    worker = worker_class.__new__(worker_class)
    left = {workspace: CLAIMS_EACH for workspace in WORKSPACES}
    served: list[uuid.UUID] = []
    worker._database = database
    worker._workspaces = frozenset(WORKSPACES)
    worker._workspace_source = None
    worker._limit = 100
    worker._stop = threading.Event()
    worker._expire_exhausted = lambda connection, workspace_id: 0

    def claim(connection, workspace_id):
        assert connection.workspace == workspace_id
        if left[workspace_id] == 0:
            return None
        left[workspace_id] -= 1
        return object()

    def one(connection, workspace_id, claimed, outcome):
        assert database.open == 1
        served.append(workspace_id)
        outcome.failed += 1  # any count the pass's limit reads

    worker._claim = claim
    setattr(worker, serve, one)
    outcome = worker.drain()
    assert database.most == 1
    assert sorted(served) == sorted(WORKSPACES * CLAIMS_EACH)
    # In turn: the first round serves each workspace once before any is served twice.
    assert served[: len(WORKSPACES)] == sorted(WORKSPACES)
    assert outcome.errors == []
