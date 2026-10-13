"""Idle durable polling must not contend with unrelated workspace deletion."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.kind_draft_jobs import KindDraftRepository
from exulanica.world.workspace_lock import WORKSPACE_LOCK_SEED

from spending_support import bench as bench
from test_kind_draft_durability_postgres import submit_kind

pytestmark = pytest.mark.postgres


def workspace_lock_is_free(connection, workspace):
    return connection.execute(
        "select pg_try_advisory_xact_lock(hashtextextended(%s::text,%s)) as free",
        (workspace, WORKSPACE_LOCK_SEED),
    ).fetchone()["free"]


@pytest.mark.parametrize("action", ["claim", "expire"])
def test_empty_poll_leaves_workspace_lock_available_to_deletion(bench, action):
    workspace = uuid.uuid4()
    # Keep the poll's surrounding transaction open so an unnecessary lock cannot hide by
    # being released before the assertion. An idle pass must not acquire it at all.
    with (
        bench.runtime.session(workspace) as polling,
        bench.runtime.session(workspace) as deleting,
        polling.transaction(),
        deleting.transaction(),
    ):
        result = getattr(KindDraftRepository(polling, workspace), action)()
        assert result is None
        assert workspace_lock_is_free(deleting, workspace)


def test_model_disabled_poll_leaves_fresh_queued_work_and_workspace_unlocked(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with bench.runtime.session(workspace) as connection:
        ident = submit_kind(KindDraftRepository(connection, workspace), actor)
    with (
        bench.runtime.session(workspace) as polling,
        bench.runtime.session(workspace) as deleting,
        polling.transaction(),
        deleting.transaction(),
    ):
        repo = KindDraftRepository(polling, workspace)
        assert repo.claim(expired_only=True) is None
        assert workspace_lock_is_free(deleting, workspace)
        assert repo.get(actor, ident)["state"] == "queued"


def test_eligible_claim_still_holds_the_workspace_publication_fence(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with bench.runtime.session(workspace) as connection:
        submit_kind(KindDraftRepository(connection, workspace), actor)
    with (
        bench.runtime.session(workspace) as polling,
        bench.runtime.session(workspace) as deleting,
        polling.transaction(),
        deleting.transaction(),
    ):
        claimed = KindDraftRepository(polling, workspace).claim()
        assert claimed is not None
        assert not workspace_lock_is_free(deleting, workspace)
