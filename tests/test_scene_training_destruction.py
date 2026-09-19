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
