"""A withdrawn training right destroys what the run produced, through the one purge machinery.

Migration 0080 built three quarters of a withdrawal and named the quarter it did not build: it
cancels the run, it refuses every further read of the artefact at the instant of the read, and it
binds which artefacts a destruction would have to reach. It does not enqueue destruction, because
0030's purge path needs a ``tombstone_id`` to hang a ``purge_job`` off and a right's withdrawal has
none. Migration 0082 is that quarter.

**This file's positive control is first and was written first, against a tree where no destruction
existed.** The failure this lane can produce is not "nothing is destroyed"; it is a purger that
reaches past what the withdrawal asked for, into an artefact whose own right still stands or into
another photograph's bytes, and erasure is the one operation with no recovery. So the control is
two-sided from the start: the legitimate grant, run and read still work end to end, AND a purge
pass over a workspace whose rights all stand destroys nothing while leaving the artefact readable.
The second half is what makes a later "destroyed 1" mean something, because a purger that never
ran and a purger that correctly refused report the same zero.

Everything runs against PostgreSQL through the real migrations, and the purger runs as the real
purge role rather than as the owner, because a superuser bypasses row-level security entirely and
that is the trap correction 7 in migration 0013 was written for.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

import psycopg
import pytest
from exulanica.db.roles import (
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.deletion.worker import PurgeWorker
from exulanica.env import env_get
from exulanica.evidence.blob import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import (
    artifact_training_sources,
    require_artifact_training_right,
    require_scene_training,
)
from exulanica.store.local import LocalContentAddressedStore

from conftest import photo_bytes
from test_personal_model_right import ACCOUNT, admit_personal
from test_scene_training_right import _grant, _queue, _scene_of

#: Suffixed for this file, because a role is a CLUSTER object: provisioning the deployment's own
#: role names here would leave a developer's live roles carrying whatever this file last chose.
#: A name of its own rather than ``test_purge.py``'s, so two files in one process never hand each
#: other a role whose password the other has just rotated.
_PURGE_ROLE = f"{PURGE_ROLE}_training"
_APP_ROLE = f"{RUNTIME_ROLE}_training"

#: Generated, never committed: ``provision_*_role`` issues ``alter role ... password``, and the
#: harness's "the database name must contain test" guard does not reach a cluster object.
_PURGE_PASSWORD = secrets.token_urlsafe(32)
_APP_PASSWORD = secrets.token_urlsafe(32)

#: What a rejected run leaves behind: the evaluation bundle, which carries rendered views of the
#: place and, whenever rectification changed the pixels, the frames the trainer read. Stand-in
#: bytes, because this lane runs no GPU and trains on no photograph.
EVALUATION_BYTES = b"scene_splat_evaluation bundle: renders and training/undistorted/images"


class Trained:
    """A workspace holding one personal photograph, a granted right, and what a run published."""

    def __init__(
        self,
        repository: IngestRepository,
        store: LocalContentAddressedStore,
        scratch: str,
        subject,
    ) -> None:
        self.repository = repository
        self.store = store
        self.scratch = scratch
        self.subject = subject
        self.workspace_id = repository.workspace_id

    def rows(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchall()

    def one(self, sql: str, *params):
        return self.repository.connection.execute(sql, params).fetchone()

    def database(self, *, role: str, password: str):
        import urllib.parse

        from exulanica.db.session import Database

        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        options = urllib.parse.quote(f"-csearch_path={self.scratch},public", safe="")
        url = f"{base}{'&' if '?' in base else '?'}options={options}"
        parsed = urllib.parse.urlsplit(url)
        netloc = f"{role}:{password}@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return Database(urllib.parse.urlunsplit(parsed._replace(netloc=netloc)))

    def owner_session(self, workspace_id: uuid.UUID):
        """An owner connection scoped to ``workspace_id``, for rows another workspace holds.

        ``artifact`` refuses a write whose workspace is not the session's, through
        ``assert_workspace_context``, so a stranger's row cannot be inserted on this test's own
        connection the way ``test_purge`` inserts a stranger's capture.
        """
        import urllib.parse

        from exulanica.db.session import Database

        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        options = urllib.parse.quote(f"-csearch_path={self.scratch},public", safe="")
        return Database(url=f"{base}{'&' if '?' in base else '?'}options={options}").session(
            workspace_id
        )

    def worker(self) -> PurgeWorker:
        return PurgeWorker(
            self.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.store,
            frozenset({self.workspace_id}),
            name="training-destruction-test",
        )

    def publish(self, scene_id: uuid.UUID, kind: str, content: bytes) -> tuple[uuid.UUID, BlobId]:
        """Publish one artefact of a finished run, with its bytes actually in the store.

        The bytes matter. ``test_scene_training_right`` publishes a fixed hash and never writes an
        object, which is enough for a gate that refuses a row; a destruction that reported success
        over an object still on disk is the one failure the purge package exists to prevent, and
        only the store can tell the difference.
        """
        put = self.store.put_bytes(content)
        artifact_id = self.one(
            "insert into artifact (artifact_id,workspace_id,kind,stage_key,stage_version,"
            "params_digest,input_digest,idempotency_key,scene_id,content_sha256,storage_key,"
            "byte_size) values (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s) returning artifact_id",
            uuid.uuid4(),
            self.workspace_id,
            kind,
            kind,
            bytes(32),
            bytes(32),
            f"{kind}:{uuid.uuid4()}",
            scene_id,
            put.blob_id.digest,
            self.store.key_for(put.blob_id),
            put.byte_size,
        )["artifact_id"]
        return artifact_id, put.blob_id


@pytest.fixture
def store(tmp_path) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(tmp_path / "blobs")


@pytest.fixture
def trained(repository, store, spine_schema) -> Trained:
    """One photograph, one right, one queued run, and the roles the purger needs."""
    _psycopg, scratch = spine_schema
    subject = admit_personal(repository, store, photo_bytes(), "my-flat.jpg")

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
    return Trained(repository, store, scratch, subject)


def _run_and_publish(trained: Trained, job_id: uuid.UUID | None = None):
    """Queue a training run the way a finished one goes, and publish its evaluation bundle."""
    if job_id is None:
        job_id = _queue(trained.subject)
    scene_id = _scene_of(trained.repository, job_id)
    artifact_id, blob_id = trained.publish(scene_id, "scene_splat_evaluation", EVALUATION_BYTES)
    return artifact_id, blob_id, job_id


# -- the positive control, written and watched pass before any destruction existed ----------------


def test_the_operator_can_train_read_and_keep_what_their_own_right_permits(trained):
    """Grant, run, publish, read. Every step under the right, none of them refused.

    A rule that refuses everything is indistinguishable from a rule that works, and the failure
    this lane can produce is making the operator's own reconstruction unreachable or destroying it
    while they still want it.
    """
    _grant(trained.subject)
    job_id = _queue(trained.subject)
    permitted = require_scene_training(trained.repository, job_id)
    assert [right.capture_id for right in permitted] == [trained.subject.capture_id]

    artifact_id, blob_id, _job_id = _run_and_publish(trained, job_id)
    assert trained.store.exists(blob_id), "the run's bytes are in the store before anything else"
    assert trained.store.get(blob_id) == EVALUATION_BYTES

    # The read is permitted, and it is permitted through the same final read check a withdrawal
    # would be seen by.
    assert require_artifact_training_right(trained.repository, artifact_id) is not None
    sources = artifact_training_sources(trained.repository, artifact_id)
    assert [(source.capture_id, source.current) for source in sources] == [
        (trained.subject.capture_id, True)
    ]


def test_a_purge_pass_destroys_nothing_while_the_right_stands(trained):
    """The other half of the control, and the half that gives a later "destroyed 1" its meaning.

    A purger that never ran and a purger that correctly refused report the same zero, so this
    proves the purger runs here: it connects as the real purge role, passes the cross-workspace
    visibility check, and returns an outcome with nothing blocked.
    """
    _grant(trained.subject)
    artifact_id, blob_id, _job_id = _run_and_publish(trained)

    outcome = trained.worker().drain()

    assert outcome.blocked is None, outcome.blocked
    assert outcome.role == _PURGE_ROLE, "the pass connected as the purge role, not as the owner"
    assert outcome.errors == []
    assert outcome.handled == 0, "a workspace with no tombstone had nothing to destroy"
    assert trained.store.exists(blob_id), "the trained bytes are still there"
    assert (
        trained.one("select purged_at from artifact where artifact_id=%s", artifact_id)["purged_at"]
        is None
    )
    assert require_artifact_training_right(trained.repository, artifact_id) is not None


def test_the_binding_records_what_a_destruction_would_have_to_reach(trained):
    """0080's binding is the record this lane reads, so the control checks it is there and exact."""
    right = _grant(trained.subject)
    artifact_id, _blob_id, _job_id = _run_and_publish(trained)

    bound = trained.rows(
        "select artifact_id,capture_id,right_id from scene_training_artifact "
        "where workspace_id=%s order by capture_id",
        trained.workspace_id,
    )
    assert [(row["artifact_id"], row["capture_id"], row["right_id"]) for row in bound] == [
        (artifact_id, trained.subject.capture_id, right.right_id)
    ]
    # The bytes the binding points at are the ones on disk, asked of the store rather than
    # inferred from the row.
    stored = trained.one("select content_sha256 from artifact where artifact_id=%s", artifact_id)[
        "content_sha256"
    ]
    assert bytes(stored) == hashlib.sha256(EVALUATION_BYTES).digest()
    assert trained.store.exists(BlobId(bytes(stored)))


def test_the_withdrawal_that_exists_today_refuses_the_read_and_destroys_nothing(trained):
    """What 0080 does today, measured here so 0082's change is a change against a known state.

    This is the boundary the last lane stopped at, written as a test rather than as a sentence, so
    that the day destruction lands the diff shows which half moved.
    """
    from exulanica.ingest.training_rights import TrainingRightRefused, withdraw_training_right

    right = _grant(trained.subject)
    artifact_id, blob_id, _job_id = _run_and_publish(trained)
    withdraw_training_right(trained.repository, right_id=right.right_id, withdrawn_by=ACCOUNT)

    with pytest.raises(TrainingRightRefused) as refused:
        require_artifact_training_right(trained.repository, artifact_id)
    assert refused.value.reason == "withdrawn"
    assert trained.store.exists(blob_id), "the refusal is a refusal to read, not a destruction"


# -- what 0082 adds: the withdrawal destroys ------------------------------------------------------


def _withdraw(trained: Trained, right_id: uuid.UUID):
    from exulanica.ingest.training_rights import withdraw_training_right

    return withdraw_training_right(trained.repository, right_id=right_id, withdrawn_by=ACCOUNT)


def _tombstones(trained: Trained):
    return trained.rows(
        "select tombstone_id,scope::text as scope,capture_id,requested_by,effective_at,reason,"
        "purge_completed_at from tombstone where workspace_id=%s order by requested_at",
        trained.workspace_id,
    )


def _jobs(trained: Trained):
    return trained.rows(
        "select purge_id,tombstone_id,target_kind,target_ref,state,last_error from purge_job "
        "where workspace_id=%s order by created_at",
        trained.workspace_id,
    )


def test_a_withdrawal_destroys_what_the_run_produced(trained):
    """The whole point of the lane: the bytes go, asked of the store rather than of a row.

    Before 0082 this ended at a refusal to read. The artefact is the evaluation bundle, which is
    published on every run INCLUDING one the quality gate rejects, and which carries the frames
    the trainer read whenever rectification changed the pixels.
    """
    right = _grant(trained.subject)
    artifact_id, blob_id, _job_id = _run_and_publish(trained)
    assert trained.store.exists(blob_id)

    _withdraw(trained, right.right_id)

    tombstones = _tombstones(trained)
    assert [row["scope"] for row in tombstones] == ["scene_training"]
    assert tombstones[0]["capture_id"] == trained.subject.capture_id
    assert tombstones[0]["requested_by"] == ACCOUNT
    jobs = _jobs(trained)
    assert [(row["target_kind"], row["target_ref"]) for row in jobs] == [("artifact", blob_id.hex)]

    outcome = trained.worker().drain()

    assert outcome.errors == [], outcome.errors
    assert outcome.skipped == 0
    assert outcome.destroyed == 1
    assert not trained.store.exists(blob_id), "the trained bytes are still on disk"
    assert (
        trained.one("select purged_at,storage_key from artifact where artifact_id=%s", artifact_id)[
            "purged_at"
        ]
        is not None
    )
    assert tombstones[0]["tombstone_id"] in outcome.completed_tombstones
    assert _tombstones(trained)[0]["purge_completed_at"] is not None


def test_the_photograph_survives_what_was_trained_from_it(trained):
    """The sentence the scope has to make true, tested rather than asserted in a comment.

    A capture tombstone would have soft-deleted the photograph and queued its original bytes. This
    one erases outputs and spares its subject, because withdrawing permission to train is not
    asking for your photograph back.
    """
    right = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)
    original = BlobId(
        bytes(
            trained.one(
                "select blob_sha256 from capture where capture_id=%s", trained.subject.capture_id
            )["blob_sha256"]
        )
    )

    _withdraw(trained, right.right_id)
    outcome = trained.worker().drain()

    assert outcome.destroyed == 1
    assert not trained.store.exists(blob_id), "what the run produced"
    assert trained.store.exists(original), "the photograph itself"
    capture = trained.one(
        "select deleted_at from capture where capture_id=%s", trained.subject.capture_id
    )
    assert capture["deleted_at"] is None
    assert (
        trained.one("select purged_at from blob where blob_sha256=%s", original.digest)["purged_at"]
        is None
    )


def test_a_withdrawal_does_not_destroy_bytes_a_standing_right_holds(trained):
    """The negative control, and without it the destroy predicate could be `true`.

    Two photographs whose runs published IDENTICAL bytes, so one content hash and two artefacts.
    One right is withdrawn and the other stands. The bytes must stay, because the artefact whose
    right still stands is a reason to keep them, and the account holder can still open it.
    """
    from exulanica.ingest.training_rights import require_artifact_training_right

    mine = trained.subject
    theirs = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "other.jpg"
    )
    right = _grant(mine)
    _grant(theirs)
    my_artifact, blob_id, _my_job = _run_and_publish(trained)
    their_job = _queue(theirs, subjects=[theirs])
    their_artifact, their_blob = trained.publish(
        _scene_of(trained.repository, their_job), "scene_splat_evaluation", EVALUATION_BYTES
    )
    assert their_blob.hex == blob_id.hex, "the two runs published one content hash"

    _withdraw(trained, right.right_id)
    outcome = trained.worker().drain()

    assert outcome.destroyed == 0
    assert outcome.skipped == 1
    assert trained.store.exists(blob_id), "bytes a standing right still holds were destroyed"
    assert [row["state"] for row in _jobs(trained)] == ["skipped"]
    assert _jobs(trained)[0]["last_error"] == "something live still holds these bytes"
    assert (
        trained.one("select purged_at from artifact where artifact_id=%s", their_artifact)[
            "purged_at"
        ]
        is None
    )
    # And the artefact whose right stands is still readable, which is the half a reader cares
    # about: the refusal above is not a quiet loss of somebody else's reconstruction.
    assert require_artifact_training_right(trained.repository, their_artifact) is not None
    # The withdrawn one is refused for reading all the same, by 0080, bytes or no bytes.
    assert (
        trained.one(
            "select scene_training_artifact_withdrawn(%s,%s,clock_timestamp()) as withdrawn",
            trained.workspace_id,
            my_artifact,
        )["withdrawn"]
        is True
    )


def test_a_withdrawal_leaves_another_photograph_s_reconstruction_alone(trained):
    """The cascade names ONE capture, so a withdrawal is not a workspace-wide erasure."""
    mine = trained.subject
    theirs = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "other.jpg"
    )
    right = _grant(mine)
    _grant(theirs)
    _mine_artifact, my_blob, _my_job = _run_and_publish(trained)
    their_job = _queue(theirs, subjects=[theirs])
    their_artifact, their_blob = trained.publish(
        _scene_of(trained.repository, their_job),
        "scene_splat_evaluation",
        b"a different run over a different photograph",
    )

    _withdraw(trained, right.right_id)
    outcome = trained.worker().drain()

    assert outcome.destroyed == 1
    assert not trained.store.exists(my_blob)
    assert trained.store.exists(their_blob), "another photograph's reconstruction was destroyed"
    assert (
        trained.one("select purged_at from artifact where artifact_id=%s", their_artifact)[
            "purged_at"
        ]
        is None
    )
    assert [row["target_ref"] for row in _jobs(trained)] == [my_blob.hex]


# -- the predictions, written before they were measured --------------------------------------------


def test_the_photograph_can_be_granted_again_and_trained_again(trained):
    """P-extra. The tombstone is inert for everything except the erasure it asked for.

    A capture tombstone blocks every later derivative of its photograph, which is right for a
    deletion and would be wrong here: somebody who withdrew a right for one destination and later
    changes their mind has not lost the use of their own photograph. A scene is identified by its
    member set, so the second run is the same scene and this publishes a second artefact against
    it, which is what a re-run does.
    """
    from exulanica.ingest.privacy import admit_reconstruction_scene

    first = _grant(trained.subject)
    _artifact, blob_id, job_id = _run_and_publish(trained)
    scene_id = _scene_of(trained.repository, job_id)
    _withdraw(trained, first.right_id)
    assert trained.worker().drain().destroyed == 1
    assert not trained.store.exists(blob_id)

    second = _grant(trained.subject)
    assert second.right_id != first.right_id
    admission = admit_reconstruction_scene(
        trained.repository,
        capture_ids=[trained.subject.capture_id],
        screening_ids=[trained.subject.review_id],
    )
    assert admission.eligibility_state == "eligible", admission.blocking_reasons
    new_artifact, new_blob = trained.publish(
        scene_id, "scene_splat_evaluation", b"a second run's bundle"
    )
    assert require_artifact_training_right(trained.repository, new_artifact) is not None
    assert trained.store.exists(new_blob)


def test_two_withdrawals_over_one_scene_queue_the_same_object_twice(trained):
    """P4, and the duplicate is a choice rather than an oversight.

    A scene trained from two photographs binds once per photograph, so each account holder's
    withdrawal reaches the same artefact. The tombstone's subject is a capture and it has no column
    for a right, so the second withdrawal enqueues what the first one did if that purge has not
    finished. One object is destroyed once and the second job finds it already absent. A uniqueness
    constraint collapsing the two would make one tombstone's completion depend on another
    tombstone's job, which is worse than a duplicate.
    """
    mine = trained.subject
    also = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "also.jpg"
    )
    first = _grant(mine)
    second = _grant(also)
    job_id = _queue(mine, subjects=[mine, also])
    artifact_id, blob_id = trained.publish(
        _scene_of(trained.repository, job_id), "scene_splat_evaluation", EVALUATION_BYTES
    )
    assert (
        len(
            trained.rows(
                "select capture_id from scene_training_artifact where artifact_id=%s", artifact_id
            )
        )
        == 2
    ), "one artefact, two photographs, two bindings"

    _withdraw(trained, first.right_id)
    assert [row["target_ref"] for row in _jobs(trained)] == [blob_id.hex]
    _withdraw(trained, second.right_id)

    jobs = _jobs(trained)
    assert [row["target_ref"] for row in jobs] == [blob_id.hex, blob_id.hex]
    assert len({row["tombstone_id"] for row in jobs}) == 2

    outcome = trained.worker().drain()

    assert outcome.errors == []
    assert outcome.destroyed == 1, "the object is destroyed once"
    assert outcome.already_absent == 1, "and the duplicate finds it already gone"
    assert not trained.store.exists(blob_id)
    assert {row["state"] for row in _jobs(trained)} == {"done"}


def test_the_same_bytes_in_another_workspace_block_the_destruction_permanently(trained):
    """P5, measured rather than chosen, and the answer is worse than "deferred".

    The purge role reads `artifact` across workspaces, because `blob` is shared and the destroy
    question is about every holder. It does NOT read `scene_training_artifact` across workspaces,
    so another workspace's artefact holding these bytes cannot be shown to be withdrawn and is a
    reason to keep them. That is the safe direction. It is also permanent: nothing here can ever
    observe the other workspace's own withdrawal, so this job skips until it has spent every
    attempt and is then reported exhausted.
    """
    right = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)
    stranger = uuid.uuid4()
    original = trained.one(
        "select blob_sha256 from capture where capture_id=%s", trained.subject.capture_id
    )["blob_sha256"]
    with trained.owner_session(stranger) as connection:
        connection.execute(
            "insert into artifact (artifact_id,workspace_id,kind,source_blob_sha256,stage_key,"
            "stage_version,params_digest,input_digest,idempotency_key,content_sha256,byte_size) "
            "values (%s,%s,'scene_splat_evaluation',%s,'scene_splat_evaluation',1,%s,%s,%s,%s,%s)",
            (
                uuid.uuid4(),
                stranger,
                original,
                bytes(32),
                bytes(32),
                f"stranger:{uuid.uuid4()}",
                blob_id.digest,
                1,
            ),
        )

    _withdraw(trained, right.right_id)
    outcome = trained.worker().drain()

    assert outcome.destroyed == 0
    assert outcome.skipped == 1
    assert trained.store.exists(blob_id)
    # The mechanism, asked of the database rather than inferred from the outcome: there is no
    # cross-workspace policy on either table the destroy question reads about withdrawal.
    policies = trained.rows(
        "select tablename from pg_policies where tablename = any(%s) "
        "and policyname='purge_sees_every_holder_of_these_bytes'",
        ["artifact", "scene_training_artifact", "scene_training_right"],
    )
    assert [row["tablename"] for row in policies] == ["artifact"]


def test_a_withdrawal_after_the_bytes_are_already_gone_enqueues_nothing(trained):
    """P3. The cascade filters an artefact already marked purged, so a late withdrawal is quiet."""
    first = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)
    _withdraw(trained, first.right_id)
    assert trained.worker().drain().destroyed == 1

    second = _grant(trained.subject, destination="local-process")
    _withdraw(trained, second.right_id)

    assert len(_tombstones(trained)) == 2
    assert [row["target_ref"] for row in _jobs(trained)] == [blob_id.hex], (
        "the second withdrawal enqueued an artefact whose bytes were already destroyed"
    )
    outcome = trained.worker().drain()
    assert outcome.handled == 0
    assert not trained.store.exists(blob_id)


def test_the_erasure_request_is_written_in_the_withdrawal_s_own_transaction(trained):
    """P2's half that can be measured without two connections: it is one transaction, not two.

    A withdrawal that rolls back leaves no tombstone and no queued destruction, because the
    tombstone is written by a trigger on the withdrawing UPDATE rather than by a later step. The
    other half of P2, that a withdrawal cannot commit while a final read check holds the asset read
    lock, is 0080's `tg_asset_read_mutation` and is tested where that trigger lives.
    """
    right = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)

    with (
        pytest.raises(RuntimeError, match="rolled back on purpose"),
        trained.repository.connection.transaction(),
    ):
        _withdraw(trained, right.right_id)
        assert len(_tombstones(trained)) == 1, "written inside the transaction"
        raise RuntimeError("rolled back on purpose")

    assert _tombstones(trained) == []
    assert _jobs(trained) == []
    assert trained.store.exists(blob_id)
    assert (
        trained.one(
            "select withdrawn_at from scene_training_right where right_id=%s", right.right_id
        )["withdrawn_at"]
        is None
    )


def test_a_purge_role_provisioned_before_this_migration_fails_loudly_and_locally(trained):
    """The operational consequence, measured rather than reasoned from the grant shape.

    The two reads the destroy question needs go in ``_PURGE_WORKSPACE_READS`` rather than in
    ``_PURGE_READS``. The second would have moved ``PURGE_CROSS_WORKSPACE_TABLES``, which
    ``read_visibility`` requires in full, so every purge role provisioned before this migration
    would have refused to destroy ANYTHING until re-provisioned. This is the measurement that the
    first choice is loud and local instead: an old role goes on draining every other tombstone, and
    only the training-withdrawal job fails.
    """
    right = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)
    original = BlobId(
        bytes(
            trained.one(
                "select blob_sha256 from capture where capture_id=%s", trained.subject.capture_id
            )["blob_sha256"]
        )
    )
    with trained.owner_session(trained.workspace_id) as connection:
        connection.execute(f"set search_path to {trained.scratch}, public")
        for table in ("scene_training_artifact", "scene_training_right"):
            connection.execute(f"revoke select on {table} from {_PURGE_ROLE}")
        connection.execute(
            "revoke execute on function scene_training_withdrawal_releases_artifact(uuid,bytea) "
            f"from {_PURGE_ROLE}"
        )

    _withdraw(trained, right.right_id)
    second = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "deleted.jpg"
    )
    trained.repository.insert_tombstone(
        scope="capture",
        capture_id=second.capture_id,
        requested_by=ACCOUNT,
        reason="the user deleted this photograph",
    )
    outcome = trained.worker().drain()

    assert outcome.blocked is None, "the pass was not refused as a whole"
    assert outcome.destroyed >= 1, "the ordinary capture tombstone still drained"
    assert outcome.failed == 1, outcome.errors
    assert len(outcome.errors) == 1
    assert (
        "permission denied for function scene_training_withdrawal_releases_artifact"
        in (outcome.errors[0])
    ), outcome.errors
    # EXACTLY the training job failed. This assertion is the one that caught the first design:
    # with the three questions in one SQL `case`, every artifact job of the capture deletion
    # failed too, because EXECUTE is checked on every function in an expression rather than on
    # the arm that runs.
    assert [
        row["target_ref"]
        for row in trained.rows(
            "select target_ref from purge_job where workspace_id=%s and state='failed'",
            trained.workspace_id,
        )
    ] == [blob_id.hex]
    assert trained.store.exists(blob_id), "the training withdrawal destroyed nothing"
    assert trained.store.exists(original), "and it did not reach this photograph either"


def test_a_withdrawn_artefact_is_still_refused_once_its_bytes_are_gone(trained):
    """Destruction does not replace the refusal, and the refusal does not become an error.

    0080's refusal covers the interval between a withdrawal committing and a purge completing,
    which is of unbounded and sometimes infinite length. After the purge it still has to answer,
    because the row survives the bytes: 0001 keeps the stub so a citation into deleted content
    resolves to "this was removed" rather than to nothing.
    """
    from exulanica.ingest.training_rights import TrainingRightRefused

    right = _grant(trained.subject)
    artifact_id, blob_id, _job_id = _run_and_publish(trained)
    _withdraw(trained, right.right_id)
    assert trained.worker().drain().destroyed == 1
    assert not trained.store.exists(blob_id)

    with pytest.raises(TrainingRightRefused) as refused:
        require_artifact_training_right(trained.repository, artifact_id)
    assert refused.value.reason == "withdrawn"
    sources = artifact_training_sources(trained.repository, artifact_id)
    assert [(source.capture_id, source.current) for source in sources] == [
        (trained.subject.capture_id, False)
    ]
    row = trained.one(
        "select purged_at,storage_key,content_sha256 from artifact where artifact_id=%s",
        artifact_id,
    )
    assert row["purged_at"] is not None
    assert row["storage_key"] is None
    assert bytes(row["content_sha256"]) == blob_id.digest, "the stub still names what it held"


def test_a_withdrawal_reaches_only_what_the_withdrawn_right_produced(trained):
    """One photograph, two destinations, two runs: withdrawing one does not erase the other.

    A person who lets their photograph be trained locally and on a rented machine, and then takes
    the rented one back, has not asked for the local reconstruction to be destroyed. The cascade
    reads the binding's own right rather than treating a tombstone over a capture as a statement
    about everything ever trained from it.

    Two SCENES, because a scene is identified by its member set and the binding trigger picks one
    right per capture per scene. This is the only shape in which a capture can carry a standing
    binding and a withdrawn one at once.
    """
    from test_scene_training_right import GPU, OTHER_GPU

    mine = trained.subject
    also = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "also.jpg"
    )
    standing = _grant(mine, destination=GPU)
    withdrawn = _grant(mine, destination=OTHER_GPU)
    _grant(also, destination=OTHER_GPU)
    alone = _queue(mine, destination=GPU)
    kept_artifact, kept_blob = trained.publish(
        _scene_of(trained.repository, alone), "scene_splat_evaluation", b"trained at the first"
    )
    together = _queue(mine, subjects=[mine, also], destination=OTHER_GPU)
    gone_artifact, gone_blob = trained.publish(
        _scene_of(trained.repository, together), "scene_splat_evaluation", b"trained at the second"
    )
    assert {
        (row["artifact_id"], row["right_id"])
        for row in trained.rows(
            "select artifact_id,right_id from scene_training_artifact where capture_id=%s",
            mine.capture_id,
        )
    } == {(kept_artifact, standing.right_id), (gone_artifact, withdrawn.right_id)}

    _withdraw(trained, withdrawn.right_id)
    outcome = trained.worker().drain()

    assert [row["target_ref"] for row in _jobs(trained)] == [gone_blob.hex]
    assert outcome.destroyed == 1
    assert not trained.store.exists(gone_blob)
    assert trained.store.exists(kept_blob), "the run the standing right permitted was destroyed"
    assert require_artifact_training_right(trained.repository, kept_artifact) is not None


def test_the_destroy_question_refuses_rather_than_answering_yes(trained):
    """Asked about bytes nobody can name, it raises. The same shape as 0013's correction 2.

    Every clause is an ``exists`` over an equality, and ``= NULL`` is never true, so every one of
    them is vacuously satisfied for NULL and the answer would be "destroy these bytes" for exactly
    the rows whose content hash was never recorded.
    """
    right = _grant(trained.subject)
    _artifact_id, _blob_id, _job_id = _run_and_publish(trained)
    _withdraw(trained, right.right_id)
    tombstone_id = _tombstones(trained)[0]["tombstone_id"]

    with pytest.raises(psycopg.errors.NullValueNotAllowed) as refused:
        trained.one(
            "select scene_training_withdrawal_releases_artifact(%s,null) as releases", tombstone_id
        )
    assert "absent content hash" in str(refused.value)
    # A tombstone nobody wrote is not an authority.
    assert (
        trained.one(
            "select scene_training_withdrawal_releases_artifact(%s,%s) as releases",
            uuid.uuid4(),
            bytes(32),
        )["releases"]
        is False
    )
    # Nor is a tombstone of another scope, and this is the half a break got past first: with the
    # scope test removed, a random id still answers false because there is no row at all, so only
    # a REAL tombstone of a different scope asks the question that clause is there for.
    second = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "deleted.jpg"
    )
    deletion = trained.repository.insert_tombstone(
        scope="capture", capture_id=second.capture_id, requested_by=ACCOUNT
    )
    assert (
        trained.one(
            "select scene_training_withdrawal_releases_artifact(%s,%s) as releases",
            deletion,
            bytes(32),
        )["releases"]
        is False
    )


def test_each_withdrawal_enqueues_only_its_own_photograph_s_reconstruction(trained):
    """A tombstone names what IT asked to have destroyed, and completes on its own work.

    Two photographs, two runs, two withdrawals. Without the cascade's capture test the second
    tombstone would enqueue the first's artefact as well, because that right is withdrawn too. The
    jobs are idempotent and the bytes would still go, so this is not about the bytes: it is
    ``tombstone_purge_is_complete``, which is asked per tombstone, and a tombstone carrying another
    tombstone's objects is one whose completion waits on somebody else's work.
    """
    mine = trained.subject
    also = admit_personal(
        trained.repository, trained.store, photo_bytes(size=(120, 80)), "also.jpg"
    )
    first = _grant(mine)
    second = _grant(also)
    _my_artifact, my_blob, _my_job = _run_and_publish(trained)
    their_job = _queue(also, subjects=[also])
    _their_artifact, their_blob = trained.publish(
        _scene_of(trained.repository, their_job), "scene_splat_evaluation", b"the other run"
    )

    _withdraw(trained, first.right_id)
    _withdraw(trained, second.right_id)

    by_tombstone: dict = {}
    for row in _jobs(trained):
        by_tombstone.setdefault(row["tombstone_id"], []).append(row["target_ref"])
    assert sorted(by_tombstone.values()) == sorted([[my_blob.hex], [their_blob.hex]]), by_tombstone

    outcome = trained.worker().drain()

    assert outcome.destroyed == 2
    assert len(outcome.completed_tombstones) == 2, "each tombstone completed on its own work"


def test_an_interval_redaction_enqueues_no_reconstruction(trained):
    """A redaction removes a moment, not a photograph, and not what was trained from one.

    0013's scope paragraph says an interval tombstone queues nothing at all, and ``test_purge``
    holds that for the general enqueue. This holds it for the training cascade, which runs on the
    same insert and has to decline the same way.
    """
    right = _grant(trained.subject)
    _artifact_id, blob_id, _job_id = _run_and_publish(trained)
    _withdraw(trained, right.right_id)
    withdrawal = _tombstones(trained)[0]["tombstone_id"]

    redaction = trained.repository.insert_tombstone(
        scope="interval",
        capture_id=trained.subject.capture_id,
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=ACCOUNT,
        reason="the user redacted a moment",
    )

    assert {row["tombstone_id"] for row in _jobs(trained)} == {withdrawal}
    assert [row["target_ref"] for row in _jobs(trained)] == [blob_id.hex]
    assert trained.rows("select purge_id from purge_job where tombstone_id=%s", redaction) == []
