"""Durable normal draft identity, claim fencing and person quotas under provisioned roles."""

import datetime as dt
import uuid

import psycopg
import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.world.world_draft_contract import DEFINITION_PROFILE
from exulanica.world.world_draft_jobs import WorldDraftRefused, WorldDraftRepository, terms_sha256

from conftest import scratch_role_database
from test_world_draft_offer import inputs, operation_sheet

pytestmark = pytest.mark.postgres


@pytest.fixture
def draft_db(spine_schema):
    _psycopg, scratch = spine_schema
    from tests_support_api import scratch_database

    owner = scratch_database(scratch)
    with owner.unscoped() as connection:
        provision_runtime_role(connection, role="world_draft_jobs_tests")
    return scratch_role_database(scratch, "world_draft_jobs_tests")


def definition():
    manifest, prices, _at, wire = inputs()
    now = dt.datetime.now(dt.UTC)
    quote = operation_sheet(manifest, prices, {p: now for p, _m in prices}, wire, now=now)
    return dict(
        profile=DEFINITION_PROFILE, quote=quote, manifest_sha256="a" * 64, deadline_seconds=600
    )


def submit(repo, actor, key, words="a small town", maximum=12):
    return repo.submit(
        actor=actor,
        request_id=key,
        description=words,
        terms_sha256=terms_sha256(words, None, None),
        definition=definition(),
        guest=False,
        starts_maximum=maximum,
    )


def test_same_request_returns_one_identity_changed_terms_and_foreign_actor_are_refused(draft_db):
    workspace, actor, key = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with draft_db.session(workspace) as connection:
        repo = WorldDraftRepository(connection, workspace)
        ident = submit(repo, actor, key)
        assert submit(repo, actor, key) == ident
        assert repo.get(actor, ident)["description"] == "a small town"
        with pytest.raises(WorldDraftRefused, match="key_reused"):
            submit(repo, actor, key, words="another place")
        with pytest.raises(WorldDraftRefused, match="unknown"):
            repo.get(uuid.uuid4(), ident)
    with (
        draft_db.session(uuid.uuid4()) as connection,
        pytest.raises(WorldDraftRefused, match="unknown"),
    ):
        WorldDraftRepository(connection, uuid.uuid4()).get(actor, ident)


def test_person_quota_survives_another_process_and_workspace_without_reading_foreign_rows(draft_db):
    actor = uuid.uuid4()
    with draft_db.session(uuid.uuid4()) as connection:
        submit(
            WorldDraftRepository(
                connection,
                connection.execute("select current_workspace() as w").fetchone()["w"],
            ),
            actor,
            uuid.uuid4(),
            maximum=1,
        )
    workspace = uuid.uuid4()
    with draft_db.session(workspace) as connection:
        repo = WorldDraftRepository(connection, workspace)
        assert (
            repo.allowance(actor, 1)["left"] == 0
        )  # only this actor's aggregate crosses workspaces
        with pytest.raises(WorldDraftRefused, match="kind_draft_limit"):
            submit(repo, actor, uuid.uuid4(), maximum=1)
        assert connection.execute("select count(*) as n from job").fetchone()["n"] == 0


def test_actor_wide_native_kind_count_is_consumed_with_durable_starts(draft_db):
    actor = uuid.uuid4()
    for _ in range(2):
        workspace = uuid.uuid4()
        with draft_db.session(workspace) as connection:
            repo = WorldDraftRepository(connection, workspace)
            made = submit(repo, actor, uuid.uuid4(), maximum=4)
            repo.end_unstarted(actor, made, "private_fixture_refusal")
    from exulanica.world.kind_draft_jobs import KindDraftRepository

    for _ in range(2):
        workspace = uuid.uuid4()
        with draft_db.session(workspace) as connection:
            KindDraftRepository(connection, workspace).submit(
                actor=actor,
                description="a kind",
                guest=False,
                starts_maximum=4,
                workspace_maximum=1,
                deadline_seconds=600,
                manifest_sha256="a" * 64,
                prompt_version="private-fixture",
            )
    workspace = uuid.uuid4()
    with draft_db.session(workspace) as connection:
        repo = WorldDraftRepository(connection, workspace)
        with pytest.raises(WorldDraftRefused, match="kind_draft_limit"):
            repo.submit(
                actor=actor,
                request_id=uuid.uuid4(),
                description="a small town",
                terms_sha256=terms_sha256("a small town", None, None),
                definition=definition(),
                guest=False,
                starts_maximum=4,
            )
        assert connection.execute("select count(*) as n from job").fetchone()["n"] == 0


def test_concurrent_actor_admission_across_workspaces_keeps_one_durable_start(draft_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    actor = uuid.uuid4()
    start = Barrier(4)

    def attempt(_):
        workspace = uuid.uuid4()
        with draft_db.session(workspace) as connection:
            start.wait(timeout=10)
            try:
                submit(WorldDraftRepository(connection, workspace), actor, uuid.uuid4(), maximum=1)
            except WorldDraftRefused as failure:
                assert failure.code == "kind_draft_limit"
                assert connection.execute("select 1 from job").fetchall() == []
                return "refused"
            return "accepted"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("accepted") == 1


#: A deletion written while another transaction holds its workspace's lock (migration 0137).
BUSY = "workspace in use; retry the deletion"


def write_deletion(connection, workspace, actor):
    """A capture's deletion, as one statement on its own connection: the tombstone migration
    0137 refuses at once, 40001, while another transaction holds the workspace's lock."""
    connection.execute(
        "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
        "values (%s, 'capture', %s, %s, 'world draft claim fixture')",
        (workspace, uuid.uuid4(), actor),
    )


def test_an_idle_claim_takes_no_workspace_lock_so_a_deletion_is_not_refused_for_it(draft_db):
    """The worker polls every workspace it watches twice a second. A poll that finds nothing to
    claim is an observation, not a mutation: it holds no workspace lock, so a deletion written
    while it is open is not refused "workspace in use", as the kind draft queue already holds."""
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with draft_db.session(workspace) as polling, draft_db.session(workspace) as deleting:
        with polling.transaction():
            assert WorldDraftRepository(polling, workspace).claim() is None
            # The poll's transaction is still open: a lock it took would still be held.
            write_deletion(deleting, workspace, actor)
        assert (
            deleting.execute(
                "select count(*) as n from tombstone where workspace_id=%s", (workspace,)
            ).fetchone()["n"]
            == 1
        )


def test_a_claim_with_work_still_takes_the_workspace_lock_before_the_job(draft_db):
    """The control: a claim that finds a job takes the workspace's lock first, as every writer
    does, so a deletion meeting it is refused and sent again rather than racing the claim."""
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with draft_db.session(workspace) as polling, draft_db.session(workspace) as deleting:
        repo = WorldDraftRepository(polling, workspace)
        ident = submit(repo, actor, uuid.uuid4())
        for provider in {p["provider"] for p in definition()["quote"]["providers"]}:
            repo.attach_bound(actor, ident, provider, uuid.uuid4())
        repo.enqueue(actor, ident)
        with polling.transaction():
            claimed = repo.claim()
            assert claimed is not None and claimed.draft_id == ident
            with pytest.raises(psycopg.errors.SerializationFailure, match=BUSY):
                write_deletion(deleting, workspace, actor)
        write_deletion(deleting, workspace, actor)


def test_two_claims_racing_for_one_job_give_it_to_exactly_one(draft_db):
    """Two workers claim the same workspace at once: the job goes to one of them, and the other
    finds nothing to claim."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with draft_db.session(workspace) as connection:
        repo = WorldDraftRepository(connection, workspace)
        ident = submit(repo, actor, uuid.uuid4())
        for provider in {p["provider"] for p in definition()["quote"]["providers"]}:
            repo.attach_bound(actor, ident, provider, uuid.uuid4())
        repo.enqueue(actor, ident)
    start = Barrier(2)

    def claim(_):
        with draft_db.session(workspace) as connection:
            start.wait(timeout=10)
            return WorldDraftRepository(connection, workspace).claim()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))
    won = [one for one in claims if one is not None]
    assert len(won) == 1 and won[0].draft_id == ident
