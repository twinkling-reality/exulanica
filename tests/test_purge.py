"""The object-store purge, and the seven corrections its design needed.

R18's other half. Migration 0011 stopped a derivative of tombstoned bytes being created at all;
this is what removes the ones written before the tombstone arrived.

**Every test here is about a way this could destroy the wrong thing or claim it destroyed
something it did not.** That is the shape of the risk: a purger that refuses too much leaves
files on a disk, and a purger that refuses too little takes a photograph somebody still has. The
second is not recoverable and is why the predicates raise rather than answer when they cannot
see enough to be sure.

Six of the corrections came off the defect register. The seventh, that the destroy predicate
cannot see another tenant's live capture and answers "destroy", was found by running the design
against a real database as a real role, and one of the tests below is that measurement.
"""

from __future__ import annotations

import datetime as dt
import secrets
import threading
import uuid

import psycopg
import pytest
from exulanica.db.roles import (
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.deletion import queue
from exulanica.deletion.worker import PurgeWorker
from exulanica.env import env_get
from exulanica.evidence.blob import BlobId
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.store.local import LocalContentAddressedStore

from conftest import CountingVisionModel, write_photo

#: Suffixed, because **a role is a CLUSTER object** and the harness's "the database name must
#: contain test" guard does not reach one. Provisioning the deployment's own role names here
#: would leave the developer's live `exulanica_app` and `exulanica_purge`
#: carrying whatever this file last chose, in the same cluster the `exulanica`
#: database uses.
_PURGE_ROLE = f"{PURGE_ROLE}_suite"
_APP_ROLE = f"{RUNTIME_ROLE}_suite"

# **Generated, never committed.** `provision_runtime_role` and `provision_purge_role` issue
# `alter role ... password`, and a role is a CLUSTER object: the harness's "the database name must
# contain test" guard does not reach it. With constants here, every run of this file left the
# developer's live `exulanica_app` and `exulanica_purge` roles authenticating
# with two strings sitting
# in a public repository. Measured against `pg_authid` by recomputing the SCRAM verifier: they
# matched. One process, one pair of secrets, and nothing to read afterwards.
_PURGE_PASSWORD = secrets.token_urlsafe(32)
_APP_PASSWORD = secrets.token_urlsafe(32)


class Purged:
    """A workspace with one ingested photograph, a store, and the roles the purger needs."""

    def __init__(self, repository, store, scratch, psycopg_module, tmp_path) -> None:
        self.repository = repository
        self.store = store
        self.scratch = scratch
        self._psycopg = psycopg_module
        self.tmp_path = tmp_path
        self.workspace_id = repository.workspace_id

    def rows(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchall()

    def database(self, *, role: str | None = None, password: str | None = None):
        """A Database pointed at the scratch schema, optionally as a non-owner role."""
        import urllib.parse

        from exulanica.db.session import Database

        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        options = urllib.parse.quote(f"-csearch_path={self.scratch},public", safe="")
        url = f"{base}{'&' if '?' in base else '?'}options={options}"
        if role is not None:
            parsed = urllib.parse.urlsplit(url)
            netloc = f"{role}:{password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            url = urllib.parse.urlunsplit(parsed._replace(netloc=netloc))
        return Database(url=url)

    def worker(self, *, as_purge_role: bool = True) -> PurgeWorker:
        database = (
            self.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)
            if as_purge_role
            else self.database()
        )
        return PurgeWorker(
            database, self.store, frozenset({self.workspace_id}), name="test-purge"
        )

    def tombstone_the_capture(self, capture_id: uuid.UUID) -> uuid.UUID:
        """Delete a capture the way the product does, which is one call and nothing else.

        **This helper used to run ``update capture set deleted_at = now()`` first, and that line
        was the defect.** Nothing in ``orimera/`` ever wrote that column, so the helper was
        supplying a production step the shipping code did not have, and every test below passed
        against a flow that did not exist. Measured with the line removed and before migration
        0015: three jobs queued, zero destroyed, three skipped for ever, and the tombstone never
        completed. The soft delete is now the tombstone trigger's work, in the tombstone's own
        transaction, so this is the whole of a deletion.
        """
        return self.repository.insert_tombstone(
            scope="capture",
            capture_id=capture_id,
            requested_by=uuid.uuid4(),
            reason="the user deleted this photograph",
        )


@pytest.fixture
def purged(tmp_path, photo_dir, repository, spine_schema):
    psycopg_module, scratch = spine_schema
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    outcome = pipeline.ingest_file(write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None, outcome.error

    import urllib.parse

    from exulanica.db.session import Database

    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    owner = Database(url=f"{base}{'&' if '?' in base else '?'}options={options}")
    with owner.unscoped() as connection:
        connection.execute(f"set search_path to {scratch}, public")
        provision_runtime_role(connection, role=_APP_ROLE, password=_APP_PASSWORD)
        provision_purge_role(connection, role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    return Purged(repository, store, scratch, psycopg_module, tmp_path)


# -- the queue is filled by the tombstone, in the tombstone's transaction ---------------------


def test_writing_a_tombstone_queues_every_object_it_asked_to_have_destroyed(purged):
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    tombstone_id = purged.tombstone_the_capture(capture_id)

    jobs = purged.rows(
        "select target_kind, target_ref, state from purge_job where tombstone_id = %s "
        "order by target_kind, target_ref",
        tombstone_id,
    )
    kinds = [job["target_kind"] for job in jobs]
    assert kinds.count("blob") == 1, jobs
    assert kinds.count("artifact") >= 2, "intake, rendition and vision each wrote an object"
    assert {job["state"] for job in jobs} == {"queued"}
    # A hash, never a path. A queue row carrying a storage key would be a second opinion about
    # where an object lives, and the one that is wrong is the one that leaves bytes behind.
    for job in jobs:
        assert len(job["target_ref"]) == 64
        bytes.fromhex(job["target_ref"])


def test_a_scope_that_names_no_bytes_queues_nothing(purged):
    """An interval redaction removes a moment, not a photograph.

    Section 6.4: an artifact overlapping a redacted interval is marked ``needs_repair`` and
    regenerated, rather than destroyed, because refusing the whole derivative would delete more
    than the user asked to delete. So there is nothing here for the purger, and the queue says so
    by being empty rather than by holding jobs that always defer.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    tombstone_id = purged.repository.insert_tombstone(
        scope="interval",
        capture_id=capture_id,
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=uuid.uuid4(),
        reason="the user redacted a moment",
    )
    assert purged.rows(
        "select purge_id from purge_job where tombstone_id = %s", tombstone_id
    ) == []


# -- the whole path --------------------------------------------------------------------------


def test_the_purger_destroys_the_bytes_and_records_that_it_did(purged):
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    stored = [
        BlobId(bytes(row["blob_sha256"]))
        for row in purged.rows("select blob_sha256 from blob")
    ]
    stored += [
        BlobId(bytes(row["content_sha256"]))
        for row in purged.rows(
            "select content_sha256 from artifact where content_sha256 is not null"
        )
    ]
    assert all(purged.store.exists(blob) for blob in stored)

    tombstone_id = purged.tombstone_the_capture(capture_id)
    outcome = purged.worker().drain()

    assert outcome.failed == 0, outcome.errors
    assert outcome.skipped == 0
    assert outcome.destroyed >= 4
    for blob in stored:
        assert not purged.store.exists(blob), f"{blob.hex[:12]} is still on disk"

    assert {row["state"] for row in purged.rows("select state from purge_job")} == {"done"}
    # The stub survives the bytes: 0001 keeps it so a citation into deleted content resolves to
    # "the user deleted this" rather than to nothing at all.
    for row in purged.rows("select purged_at, storage_key from blob"):
        assert row["purged_at"] is not None
        assert row["storage_key"] is None
    for row in purged.rows("select purged_at from artifact"):
        assert row["purged_at"] is not None
    assert tombstone_id in outcome.completed_tombstones
    assert purged.rows(
        "select purge_completed_at from tombstone where tombstone_id = %s", tombstone_id
    )[0]["purge_completed_at"] is not None


def test_running_the_purge_twice_destroys_nothing_a_second_time(purged):
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    purged.tombstone_the_capture(capture_id)
    first = purged.worker().drain()
    second = purged.worker().drain()
    assert first.destroyed >= 4
    assert second.handled == 0, "a drained queue produced work"


# -- correction 7: the other tenant ----------------------------------------------------------


def test_the_purger_does_not_destroy_bytes_another_workspace_still_holds(purged):
    """The measurement that found correction 7, kept as the test that holds it.

    ``blob`` is not workspace-scoped: two workspaces that ingest the same photograph share one
    row and one object, and 0001 says so. ``capture`` is under FORCE row-level security, so a
    session scoped to one workspace cannot see another's, and the destroy predicate is only as
    truthful as the caller can see. Measured as the runtime role before the purge role existed:
    the predicate answered "destroy" while the other workspace's capture was live.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    stranger = uuid.uuid4()
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (stranger, blob.digest),
    )

    purged.tombstone_the_capture(capture_id)
    outcome = purged.worker().drain()

    assert purged.store.exists(blob), (
        "the original bytes were destroyed while another workspace still holds a live capture "
        "of them, which breaks every citation that workspace has"
    )
    assert outcome.skipped >= 1
    assert {
        row["state"] for row in purged.rows("select state from purge_job where target_kind='blob'")
    } == {"skipped"}
    # And the tombstone is NOT recorded as purged, because it is not.
    assert purged.rows("select purge_completed_at from tombstone")[0]["purge_completed_at"] is None


def test_a_purger_that_cannot_see_the_other_tenant_would_destroy_those_bytes(purged):
    """The same situation, asked of the role that cannot see the answer.

    This is the measurement rather than a second guarantee: it asserts that the predicate is only
    as truthful as the caller, which is why ``provision_purge_role`` exists and why the worker
    connects as that role. Without it the fix above reads as belt and braces instead of as the
    one thing standing between a shared blob and another tenant's photographs.
    """
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (uuid.uuid4(), blob.digest),
    )
    purged.repository.insert_tombstone(
        scope="capture",
        capture_id=purged.rows("select capture_id from capture where workspace_id = %s",
                               purged.workspace_id)[0]["capture_id"],
        requested_by=uuid.uuid4(),
    )
    answers = {}
    for role, password in ((_APP_ROLE, _APP_PASSWORD), (_PURGE_ROLE, _PURGE_PASSWORD)):
        with purged.database(role=role, password=password).session(purged.workspace_id) as c:
            answers[role] = c.execute(
                "select purge_releases_bytes(%s) as releases", (blob.digest,)
            ).fetchone()["releases"]
    assert answers[_APP_ROLE] is True, (
        "the runtime role's view of this question changed; the point of the purge role was that "
        "this one is wrong"
    )
    assert answers[_PURGE_ROLE] is False


# -- what an adversarial review measured, one test each ---------------------------------------


def test_the_whole_deletion_is_one_call_through_the_product(purged):
    """The finding that mattered most: nothing in `orimera/` ever wrote `capture.deleted_at`.

    `purge_releases_bytes` decides liveness from that column, `insert_tombstone` wrote a row and
    nothing else, and the test helper supplied the missing step. So the suite was green against a
    flow that did not exist, and through the product every job deferred for ever. Migration 0015
    makes the soft delete the tombstone trigger's work, in the tombstone's own transaction.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    purged.repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )
    assert purged.rows("select deleted_at from capture")[0]["deleted_at"] is not None, (
        "the tombstone did not mark the capture it deletes, so nothing will ever release its "
        "bytes"
    )
    assert purged.worker().drain().destroyed >= 4


def test_an_ingest_waits_for_a_purge_of_the_same_object(purged, photo_dir):
    """The lock has two sides and only one of them used to take it.

    Measured without the ingest side: workspace A's purger asks whether the bytes may go,
    workspace B commits a live capture of the same bytes inside the window, and the purger
    destroys an object B is using. B has no tombstone and has deleted nothing. The natural path
    there is deduplication, where B's ingest writes no bytes at all because the object was
    already present, so the collision is not even detected.

    A REAL ingest is run here rather than a bare call to the lock helper, because the property is
    that the intake stage takes it. A test that took the lock itself would pass with the call
    site removed, which is what a first version of this test did.
    """
    from conftest import photo_bytes

    data = photo_bytes(when="2026:08:29 09:00:00")
    blob = BlobId.of_bytes(data)
    held = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def purger_holds() -> None:
        with purged.database().session(purged.workspace_id) as connection, (
            connection.transaction()
        ):
            connection.execute("select purge_lock_object(%s)", (blob.hex,))
            held.set()
            release.wait(20)

    def ingest() -> None:
        with purged.database().session(purged.workspace_id) as connection:
            pipeline = PhotoIngestPipeline(
                IngestRepository(connection, purged.workspace_id), purged.store
            )
            pipeline.ingest_intake(data, filename="held.jpg")
        finished.set()

    holder = threading.Thread(target=purger_holds)
    ingester = threading.Thread(target=ingest)
    holder.start()
    try:
        assert held.wait(20), "the purger never took the lock"
        ingester.start()
        assert not finished.wait(1.0), (
            "the ingest committed a capture while a purge of the same object was in flight"
        )
    finally:
        release.set()
        holder.join()
    assert finished.wait(20), "the ingest never completed after the purge released the lock"
    ingester.join()
    assert purged.rows(
        "select capture_id from capture where blob_sha256 = %s", blob.digest
    ), "the ingest waited and then did not write"


def test_a_purger_that_cannot_see_across_workspaces_refuses_to_destroy_anything(purged):
    """`EXULANICA_PURGE_DATABASE_URL` is a name and nothing used to check the role behind it.

    Measured with the writer's URL in that variable: one object destroyed, zero skipped, the
    tombstone recorded complete, another workspace's live photograph gone, and nothing in the
    outcome naming the role or the narrowed view.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    purged.tombstone_the_capture(capture_id)

    outcome = purged.worker(as_purge_role=False).drain()
    assert outcome.blocked is not None, "a narrowed purger destroyed bytes and said nothing"
    assert outcome.destroyed == 0
    assert purged.store.exists(blob)
    assert "cross-workspace" in outcome.blocked
    assert outcome.role is not None and outcome.role != _PURGE_ROLE

    # And the right role is allowed through, or the check above would pass on a worker that
    # refused everybody.
    allowed = purged.worker().drain()
    assert allowed.blocked is None
    assert allowed.role == _PURGE_ROLE
    assert allowed.destroyed >= 1


def test_a_job_that_failed_on_a_transient_outage_is_tried_again(purged, monkeypatch):
    """`failed` was terminal, for exactly the reason correction 3 fixed `skipped`.

    Measured with a store whose delete raised once: two jobs went to `failed`, three later passes
    with a healthy store did nothing at all, the bytes stayed on disk for ever, the tombstone
    never completed, and re-enqueueing the same target raised a unique violation. The only
    recovery was a second tombstone for the same capture, which no interface offers.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    purged.tombstone_the_capture(capture_id)

    class Unreachable:
        """A purger that cannot reach the store. What a transient outage looks like."""

        def purge(self, blob_id):
            raise OSError("the object store is unreachable")

    monkeypatch.setattr(
        LocalContentAddressedStore,
        "_privileged_purger",
        lambda self, authorization: Unreachable(),
    )
    first = purged.worker().drain()
    assert first.failed >= 1 and first.destroyed == 0, first
    assert "failed" in {row["state"] for row in purged.rows("select state from purge_job")}

    # A second pass with the store still broken and no cooldown elapsed changes nothing, which
    # is what the cooldown is for.
    assert purged.worker().drain().handled == 0

    monkeypatch.undo()
    monkeypatch.setattr(queue, "RETRY_AFTER", dt.timedelta(0))
    second = purged.worker().drain()
    assert second.failed == 0, second.errors
    assert second.destroyed >= 1
    assert {row["state"] for row in purged.rows("select state from purge_job")} == {"done"}


def test_a_job_stranded_in_running_is_taken_back(purged, monkeypatch):
    """A crash between the store unlink and the commit leaves a row that lies.

    The bytes are gone, the `blob` row says they are live, and its `storage_key` points at an
    object that is not there: a citation resolving to "here it is" and then raising, instead of
    to "the user deleted this". Reclaiming is safe HERE, and the queue's docstring says why: the
    lock serialises two purgers, `purge` returns False when the object is already absent, and
    the predicate is re-asked before anything is destroyed.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    purged.tombstone_the_capture(capture_id)
    claimed = queue.claim_purge(purged.repository.connection, purged.workspace_id)
    assert claimed is not None
    assert purged.rows(
        "select state from purge_job where purge_id = %s", claimed.purge_id
    )[0]["state"] == "running"

    monkeypatch.setattr(queue, "RETRY_AFTER", dt.timedelta(0))
    outcome = purged.worker().drain()
    assert outcome.handled >= 4, "the stranded row was invisible to every later pass"
    assert {row["state"] for row in purged.rows("select state from purge_job")} == {"done"}


def test_a_workspace_tombstone_is_not_complete_while_the_workspace_has_bytes(purged):
    """The enqueue is a snapshot and a workspace scope's object set is not closed at insert time.

    Measured before this: a capture inserted after the tombstone is accepted by the database, its
    bytes were never enqueued, the one queued job drained, and `purge_completed_at` was set with
    two objects belonging to the workspace still on disk.
    """
    tombstone_id = purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the user closed their account"
    )
    later = BlobId.of_bytes(b"a photograph that arrived after the tombstone")
    purged.repository.upsert_blob(
        later, byte_size=1, media_type="image/jpeg", storage_key=purged.store.key_for(later)
    )
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (purged.workspace_id, later.digest),
    )
    purged.worker().drain()
    assert queue.is_purge_complete(purged.repository.connection, tombstone_id) is False
    assert purged.rows(
        "select purge_completed_at from tombstone where tombstone_id = %s", tombstone_id
    )[0]["purge_completed_at"] is None


def test_the_purge_role_cannot_reopen_the_leak_0011_closed(purged):
    """Its UPDATE is column by column, and a full-table grant bought two escalations.

    `tombstone_blocks_derivative` filters `effective_at <= clock_timestamp()`, so a role that
    could push that column a year out could make every tombstone stop blocking. And
    `purge_job.target_ref` decides which object a claimed job destroys. Neither table carries an
    UPDATE trigger, so the grant was the only thing standing there.
    """
    with purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD).session(
        purged.workspace_id
    ) as connection:
        for statement in (
            "update tombstone set effective_at = now() + interval '1 year'",
            "update tombstone set requested_by = gen_random_uuid()",
            "update purge_job set target_ref = 'deadbeef'",
            "update purge_job set tombstone_id = gen_random_uuid()",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
            connection.execute("rollback")
        # And the two it legitimately needs.
        connection.execute("update tombstone set purge_completed_at = now()")
        connection.execute("update purge_job set state = 'skipped', last_error = 'x'")


def test_a_kind_this_worker_cannot_destroy_is_never_claimed(purged):
    """An embedding job without an entity dependency is not destructive authority.

    The worker handles embedding rows, but only when the queue row is bound through a durable
    dependency to the entity tombstone that authorized it. A manually inserted target under a
    capture tombstone stays unclaimed.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    tombstone_id = purged.tombstone_the_capture(capture_id)
    purged.repository.connection.execute(
        "insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref) "
        "values (%s, %s, 'embedding', %s)",
        (tombstone_id, purged.workspace_id, str(uuid.uuid4())),
    )
    outcome = purged.worker().drain()
    assert outcome.failed == 0, outcome.errors
    assert purged.rows(
        "select state from purge_job where target_kind = 'embedding'"
    )[0]["state"] == "queued"


# -- corrections 1 and 2: neither predicate may fail open ------------------------------------


def test_the_lock_refuses_a_target_nobody_named(purged):
    with pytest.raises(psycopg.errors.NullValueNotAllowed):
        purged.repository.connection.execute("select purge_lock_object(null)")


def test_the_destroy_predicate_refuses_rather_than_answering_yes(purged):
    """Correction 2, and the direction matters more than the raise.

    Both `not exists` clauses are vacuously true for NULL, because `= NULL` is never true, so the
    predicate answered "destroy these bytes" for bytes nobody could name. It fails closed now,
    and closed means an exception, because there is no safe boolean to return.
    """
    with pytest.raises(psycopg.errors.NullValueNotAllowed):
        purged.repository.connection.execute("select purge_releases_bytes(null)")


# -- correction 3: skipped is not terminal ----------------------------------------------------


def test_a_skipped_job_is_claimed_again_once_nothing_holds_its_bytes(purged, monkeypatch):
    """Terminal `skipped` set `purge_completed_at` over a photograph still on disk."""
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    stranger = uuid.uuid4()
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (stranger, blob.digest),
    )
    purged.tombstone_the_capture(capture_id)
    assert purged.worker().drain().skipped >= 1
    assert purged.store.exists(blob)

    # The other workspace deletes its copy, so nothing holds the bytes any more.
    purged.repository.connection.execute(
        "update capture set deleted_at = now() where workspace_id = %s", (stranger,)
    )
    # A skipped job waits before it is retried, so a permanently held blob does not spin. Without
    # `attempted_at` there was nothing to wait on and nothing to order by.
    monkeypatch.setattr(queue, "RETRY_AFTER", __import__("datetime").timedelta(0))
    second = purged.worker().drain()
    assert second.destroyed >= 1
    assert not purged.store.exists(blob)
    assert {row["state"] for row in purged.rows("select state from purge_job")} == {"done"}


def test_a_skipped_job_is_not_retried_before_its_cooldown(purged):
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (uuid.uuid4(), blob.digest),
    )
    purged.tombstone_the_capture(capture_id)
    purged.worker().drain()
    attempts = purged.rows(
        "select attempts from purge_job where target_kind = 'blob'"
    )[0]["attempts"]
    purged.worker().drain()
    assert (
        purged.rows("select attempts from purge_job where target_kind = 'blob'")[0]["attempts"]
        == attempts
    ), "a blob something else holds was re-examined immediately, which is a spin"


def test_a_deferred_job_spends_an_attempt_and_is_reported_once_it_has_spent_them_all(
    purged, monkeypatch
):
    """`MAX_ATTEMPTS` bounds CLAIMS, not failures, and a deferral is a claim.

    The comment above it used to say a target that fails this many times will not succeed on the
    next identical attempt. A deferred job's next attempt is not identical: it was deferred
    because another live capture, possibly in another workspace, holds those exact bytes, and
    that changes when the other capture is deleted. So the bound can be reached by a job that
    never broke, and what makes that acceptable rather than a silent incompletion is that the
    count is reported. This holds both halves.
    """
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    # A second workspace holds the same bytes for the whole of this test, so every pass defers.
    purged.repository.connection.execute(
        "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
        (uuid.uuid4(), blob.digest),
    )
    purged.tombstone_the_capture(capture_id)
    monkeypatch.setattr(queue, "RETRY_AFTER", dt.timedelta(0))

    seen = []
    for _ in range(queue.MAX_ATTEMPTS + 2):
        outcome = purged.worker().drain()
        seen.append(outcome.skipped)
    row = purged.rows(
        "select state, attempts from purge_job where target_kind = 'blob'"
    )[0]
    assert row["state"] == "skipped", "nothing here failed; the bytes are still held"
    assert row["attempts"] == queue.MAX_ATTEMPTS, (
        "a deferral has to spend an attempt, or a permanently held blob is re-examined for ever"
    )
    assert seen[-1] == 0, "the job at the bound was claimed again"

    assert purged.worker().drain().exhausted == 1, (
        "a job that has used every attempt while never failing is invisible, and its tombstone "
        "is incomplete with nothing saying so"
    )
    assert purged.store.exists(blob), "the bytes are still held, which is why it kept deferring"


# -- correction 4: completion asks whether the deletion happened ------------------------------


def test_a_tombstone_is_not_complete_while_one_of_its_objects_is_still_there(purged):
    """"The queue is empty" and "the bytes are gone" are different statements."""
    capture_id = purged.rows("select capture_id from capture")[0]["capture_id"]
    tombstone_id = purged.tombstone_the_capture(capture_id)
    purged.worker().drain()
    assert purged.rows(
        "select purge_completed_at from tombstone where tombstone_id = %s", tombstone_id
    )[0]["purge_completed_at"] is not None

    # Now put one of them back the way a lost UPDATE would: the queue still says done.
    purged.repository.connection.execute("update blob set purged_at = null")
    assert (
        queue.is_purge_complete(purged.repository.connection, tombstone_id) is False
    ), "completion was read off the queue rather than off the rows the queue named"


# -- correction 6: append-only by policy, and what that does and does not mean ----------------


def test_neither_the_tombstone_table_nor_its_queue_can_be_truncated(purged):
    for table in ("tombstone", "purge_job"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            purged.repository.connection.execute(f"truncate {table} cascade")
        purged.repository.connection.execute("rollback")


def test_the_truncate_refusal_is_policy_and_not_a_guarantee(purged):
    """Invariant 10. The word is "append-only by policy" and this is why.

    The table owner can disable the trigger, and no trigger can stop that. Saying "DELETE-proof"
    or "tamper-proof" would be claiming something the platform does not provide, which is the
    overclaim invariant 10 exists to forbid. What the trigger stops is the ordinary accident.
    """
    connection = purged.repository.connection
    connection.execute("alter table purge_job disable trigger tg_purge_job_no_truncate")
    try:
        connection.execute("truncate purge_job cascade")
    finally:
        connection.execute("alter table purge_job enable trigger tg_purge_job_no_truncate")


def test_no_runtime_role_can_delete_a_tombstone_or_its_queue(purged):
    """Neither runtime role deletes audit rows; the purger's sole row DELETE is embedding."""
    for role, password in ((_APP_ROLE, _APP_PASSWORD), (_PURGE_ROLE, _PURGE_PASSWORD)):
        with purged.database(role=role, password=password).session(purged.workspace_id) as c:
            for table in ("tombstone", "purge_job", "capture", "artifact", "blob"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(f"delete from {table}")
                c.execute("rollback")


def test_the_purge_role_reads_hashes_across_workspaces_and_nothing_else(purged):
    """The cross-workspace read is narrow, and narrow is what makes it acceptable.

    A policy cannot restrict columns; a grant can. The role is given identifiers, content hashes
    and deletion markers, so it can answer "does anything still hold these bytes" and cannot read
    what camera took the photograph or when.
    """
    with purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD).session(
        purged.workspace_id
    ) as c:
        c.execute("select capture_id, blob_sha256, deleted_at from capture")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select device_id from capture")
        c.execute("rollback")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select idempotency_key from artifact")
        c.execute("rollback")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into capture (workspace_id, blob_sha256) values (%s, %s)",
                      (purged.workspace_id, b"\x00" * 32))
