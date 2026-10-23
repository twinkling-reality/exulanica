"""A draft worker's loop outlives a workspace listing that fails.

The kind and world draft workers each list the workspaces to serve at the start of every pass.
A listing that raises (an account read gone wrong) is logged by its class and costs that pass
only; the thread lists again on the next pass and goes on serving. No database: each worker's
``run_once`` is replaced by one that records the workspace it was asked to serve.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterable

import pytest
from exulanica.api.kind_draft_worker import KindDraftWorker
from exulanica.api.world_draft_worker import WorldDraftWorker


def _kind(listing: Callable[[], Iterable[uuid.UUID]]) -> KindDraftWorker:
    return KindDraftWorker(
        None,  # type: ignore[arg-type]
        client=None,
        spending=None,
        holder=None,  # type: ignore[arg-type]
        policy_for=lambda _workspace: None,
        workspaces=listing,
    )


def _world(listing: Callable[[], Iterable[uuid.UUID]]) -> WorldDraftWorker:
    return WorldDraftWorker(
        None,  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
        spending=None,
        holder=None,  # type: ignore[arg-type]
        store=None,
        policy_for=lambda _workspace: None,
        workspaces=listing,
    )


@pytest.mark.parametrize("make", [_kind, _world], ids=["kind-drafts", "world-drafts"])
def test_a_listing_that_fails_costs_one_pass_and_the_worker_goes_on(make, caplog):
    workspace = uuid.uuid4()
    listings = []

    def listing() -> list[uuid.UUID]:
        listings.append(workspace)
        if len(listings) == 1:
            raise RuntimeError("the account database did not answer")
        return [workspace]

    worker = make(listing)
    served = threading.Event()
    stop = threading.Event()

    def run_once(workspace_id: uuid.UUID) -> bool:
        assert workspace_id == workspace
        served.set()
        stop.set()
        return False

    worker.run_once = run_once  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
        thread.start()
        # The first pass's listing raised; the second listed the workspace and served it.
        assert served.wait(10), "the worker stopped after a listing that failed"
        thread.join(10)
    assert not thread.is_alive(), "the worker did not stop on its stop event"
    assert len(listings) == 2
    assert "RuntimeError" in caplog.text
