"""No GPU trains on a person's own photographs without a right, and withdrawal reaches the splat.

Migration 0073 governs which model may RECEIVE a photograph. That works because showing bytes to a
model is transient: withdraw, and the next read is refused. Training is not transient. You cannot
un-train weights, and a splat trained on somebody's photographs of their home is a reconstruction
of their home that persists after the photographs are gone. These tests hold migration 0080 to the
sentence it was written for: no training run over a personal photograph is queued, and nothing it
produces is published, unless a current unwithdrawn right names that photograph and where the bytes
go, checked at the moment of the run rather than at the moment of the request.

THE POSITIVE CONTROL IS FIRST IN THIS FILE AND WAS WRITTEN FIRST, before any refusal existed. A
right that refuses everything is indistinguishable from a right that works until the day it refuses
something legitimate, and the gate this lane builds is one whose failure mode is making the
operator's own photographs unusable by the operator.

Everything runs against PostgreSQL through the real migrations.
"""

from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import pytest
from exulanica.canonical import canonical_json, sha256_digest
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.scene import scene_member_digest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    admit_reconstruction_scene,
    authorize_personal_capture,
    authorize_synthetic_capture,
    record_synthetic_exemption,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import (
    LOCAL_PROCESS,
    TrainingRightRefused,
    artifact_training_sources,
    canonical_training_destination,
    grant_training_right,
    rented_host,
    require_artifact_training_right,
    require_scene_training,
    training_right,
    training_rights_for_capture,
    withdraw_training_right,
)
from exulanica.store.local import LocalContentAddressedStore
from psycopg.types.json import Jsonb

from conftest import photo_bytes
from test_personal_model_right import ACCOUNT, PURPOSE, SOMEBODY_ELSE, admit_personal

#: The reference compute this right was written for: a rented L40S, named as a rented machine
#: rather than as the localhost its tunnel presents it at.
GPU = rented_host("brev", "l40s-reference")
OTHER_GPU = rented_host("brev", "l40s-somewhere-else")
TRAINING_PURPOSE = "Train a splat of my own flat so I can walk through it"


@pytest.fixture
def store(tmp_path) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(tmp_path / "blobs")


def _now(repository: IngestRepository) -> dt.datetime:
    return repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]


def _grant(subject, *, destination: str = GPU, capture_id=None, valid_until=None, granted_at=None):
    return grant_training_right(
        subject.repository,
        capture_id=capture_id or subject.capture_id,
        authorization_id=subject.authorization_id,
        destination=destination,
        granted_by=ACCOUNT,
        purpose=TRAINING_PURPOSE,
        granted_at=granted_at,
        valid_until=valid_until or _now(subject.repository) + dt.timedelta(minutes=30),
    )


def _build_inputs(destination: str | None = GPU) -> dict:
    """What a job states about the run it will make. A training job declares splat_training."""
    inputs: dict = {
        "profile": "exulanica.reconstruction-scene-build-input/manual-v0",
        "point_maps": [],
        "splat_training": {"profile": "exulanica.scene-splat-request/test-v0"},
    }
    if destination is not None:
        inputs["scene_training_destination"] = destination
    return inputs


def _queue(subject, *, destination: str | None = GPU, subjects=None):
    """Queue a training job over these photographs, or raise what the database raised.

    ``subjects`` are whole admitted photographs rather than capture ids, because each one carries
    its OWN eligible screening and the 0029 admission refuses a member screened under another
    source. Passing one screening for two captures makes this refuse for a reason that has nothing
    to do with training rights.
    """
    repository = subject.repository
    members = list(subjects or [subject])
    capture_ids = [member.capture_id for member in members]
    screenings = [member.review_id for member in members]
    admission = admit_reconstruction_scene(
        repository, capture_ids=capture_ids, screening_ids=screenings
    )
    assert admission.eligibility_state == "eligible", admission.blocking_reasons
    job_id, inserted = repository.enqueue_reconstruction_scene(
        capture_ids=capture_ids,
        selection_policy={"profile": "exulanica.training-right-test/v1"},
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
        build_inputs=_build_inputs(destination),
    )
    assert inserted is True
    _register(repository, job_id, capture_ids)
    return job_id


def _register(repository: IngestRepository, job_id: uuid.UUID, capture_ids: list) -> None:
    """Claim the job and record its scene, which is what a finished run does before publishing.

    Members go in before any artefact names their scene: ``tombstone_blocks_scene`` fails closed on
    an empty membership, so a scene nobody registered can publish nothing at all.
    """
    assert repository.claim_reconstruction_scene(worker="training-right-test", lease_seconds=60)
    repository.insert_completed_reconstruction_scene(
        scene_id=_scene_of(repository, job_id),
        member_digest=scene_member_digest(capture_ids),
        scene_members=[(capture_id, True) for capture_id in capture_ids],
        job_id=job_id,
    )


def _scene_of(repository: IngestRepository, job_id: uuid.UUID) -> uuid.UUID:
    return repository.connection.execute(
        "select scene_id from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()["scene_id"]


def _publish(repository: IngestRepository, scene_id: uuid.UUID, kind: str) -> uuid.UUID:
    """Publish one artefact against a scene, the way a finished training run does."""
    return repository.connection.execute(
        "insert into artifact (artifact_id,workspace_id,kind,stage_key,stage_version,"
        "params_digest,input_digest,idempotency_key,scene_id,content_sha256,byte_size) "
        "values (%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s) returning artifact_id",
        (
            uuid.uuid4(),
            repository.workspace_id,
            kind,
            kind,
            bytes(32),
            bytes(32),
            f"{kind}:{uuid.uuid4()}",
            scene_id,
            bytes(32),
            1,
        ),
    ).fetchone()["artifact_id"]


def _job(repository: IngestRepository, job_id: uuid.UUID):
    return repository.connection.execute(
        "select status,failure_class,failure_message,claim_token,lease_expires_at "
        "from reconstruction_scene_job where workspace_id=%s and job_id=%s",
        (repository.workspace_id, job_id),
    ).fetchone()


def _queue_refusal(subject, **kwargs) -> str:
    # CheckViolation, not IntegrityConstraintViolation: psycopg makes them siblings under
    # IntegrityError, so naming the wrong one here would let the gate's refusal escape as a test
    # error and read as a broken gate.
    with (
        pytest.raises(psycopg.errors.CheckViolation) as refused,
        subject.repository.connection.transaction(),
    ):
        _queue(subject, **kwargs)
    return str(refused.value)


# -- the positive control, written and watched pass before any refusal existed ---------------------


def test_the_operator_can_train_on_their_own_photographs(repository, store):
    """THE CONTROL. A photograph its owner authorized, screened and granted a training right over,
    trains at the destination that right names, publishes, and the artefact records what it came
    from. Every refusal below is worthless if this one does not hold."""
    subject = admit_personal(repository, store, photo_bytes(), "my-flat.jpg")
    right = _grant(subject)

    job_id = _queue(subject)
    permitted = require_scene_training(repository, job_id)
    assert [row.right_id for row in permitted] == [right.right_id]
    assert [row.destination for row in permitted] == [GPU]

    scene_id = _scene_of(repository, job_id)
    artifact_id = _publish(repository, scene_id, "scene_splat_delivery")

    sources = artifact_training_sources(repository, artifact_id)
    assert [source.capture_id for source in sources] == [subject.capture_id]
    assert [source.right_id for source in sources] == [right.right_id]
    assert [source.current for source in sources] == [True]
    # And the artefact reads, which is the other half of the control: the gate permits as well as
    # refusing, and a later test asserts this same call raises once the right is withdrawn.
    assert require_artifact_training_right(repository, artifact_id) is not None


def test_a_right_is_recorded_once_and_reported_as_current(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "again.jpg")
    now = _now(repository)
    until = now + dt.timedelta(minutes=30)
    right = _grant(subject, granted_at=now, valid_until=until)
    # The IDENTICAL grant, its instant included. Two grants a second apart are two different
    # records and therefore two rights, which is why the docstring says identical and not same.
    assert _grant(subject, granted_at=now, valid_until=until).right_id == right.right_id
    stored = training_right(repository, right.right_id)
    assert stored is not None and stored.operation == "scene_training"
    assert [(row.right_id, current) for row, current in training_rights_for_capture(
        repository, subject.capture_id
    )] == [(right.right_id, True)]
    assert len(training_rights_for_capture(repository, subject.capture_id)) == 1
    assert stored.as_reference()["destination"] == GPU
    assert "purpose" not in stored.as_reference()


# -- the refusals ----------------------------------------------------------------------------------


def test_a_capture_with_no_training_right_is_refused(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "ungranted.jpg")
    assert "no training right" in _queue_refusal(subject)


def test_a_right_whose_window_has_passed_is_refused(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "expired.jpg")
    now = _now(repository)
    _grant(
        subject,
        granted_at=now - dt.timedelta(minutes=20),
        valid_until=now - dt.timedelta(minutes=10),
    )
    assert "has expired" in _queue_refusal(subject)


def test_a_withdrawn_right_is_refused_and_stays_withdrawn(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "withdrawn.jpg")
    right = _grant(subject)
    ended = withdraw_training_right(
        repository, right_id=right.right_id, withdrawn_by=ACCOUNT
    )
    assert ended.withdrawn_at is not None
    assert "was withdrawn" in _queue_refusal(subject)
    # Final. Withdrawing again keeps the first withdrawal's actor and instant.
    again = withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=SOMEBODY_ELSE)
    assert (again.withdrawn_at, again.withdrawn_by) == (ended.withdrawn_at, ended.withdrawn_by)


def test_a_right_naming_a_different_capture_is_refused(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "mine.jpg")
    other = admit_personal(repository, store, photo_bytes(size=(120, 80)), "theirs.jpg")
    _grant(other)
    assert "no training right" in _queue_refusal(subject)


def test_a_right_naming_a_different_destination_is_refused(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "elsewhere.jpg")
    _grant(subject, destination=OTHER_GPU)
    assert "name another destination" in _queue_refusal(subject)


def test_a_right_under_a_lapsed_personal_authority_is_refused(repository, store):
    """The right's own window is open; the authority under which it was granted has closed.

    The authority is written already closed rather than updated shut, because
    ``capture_reconstruction_authorization`` is append-only. And it is a SECOND authority over the
    same photograph, so the screening the scene admission reads is still the live one: if the
    screening lapsed too, the 0029 admission would refuse first and this test would be measuring
    that guard instead of this one.
    """
    subject = admit_personal(repository, store, photo_bytes(), "lapsed.jpg")
    now = _now(repository)
    closed = authorize_personal_capture(
        repository,
        capture_id=subject.capture_id,
        actor=ACCOUNT,
        account_authority_basis="I took this photograph, and then my authority ran out",
        authorization_scope={"purpose": PURPOSE, "window": "closed"},
        purpose=PURPOSE,
        authorized_at=now - dt.timedelta(hours=2),
        valid_until=now - dt.timedelta(minutes=30),
    )
    right = grant_training_right(
        repository,
        capture_id=subject.capture_id,
        authorization_id=closed.authorization_id,
        destination=GPU,
        granted_by=ACCOUNT,
        purpose=TRAINING_PURPOSE,
        granted_at=now - dt.timedelta(hours=1),
        valid_until=now + dt.timedelta(hours=6),
    )
    assert right.valid_until > now and right.withdrawn_at is None
    assert "is not current" in _queue_refusal(subject)


def test_a_job_that_does_not_say_where_the_bytes_go_is_refused(repository, store):
    """A right names a destination, so a run that states none can never be matched to one."""
    subject = admit_personal(repository, store, photo_bytes(), "silent.jpg")
    _grant(subject)
    assert "must state where the bytes go" in _queue_refusal(subject, destination=None)


def test_one_ungranted_photograph_refuses_the_whole_scene(repository, store):
    """A set is trained together, so every member needs its own right, not a majority of them."""
    granted = admit_personal(repository, store, photo_bytes(), "granted.jpg")
    ungranted = admit_personal(repository, store, photo_bytes(size=(120, 80)), "ungranted.jpg")
    _grant(granted)
    assert "no training right" in _queue_refusal(granted, subjects=[granted, ungranted])


# -- the moment the check is made ------------------------------------------------------------------


def test_a_withdrawal_during_the_run_stops_the_publication(repository, store):
    """A training run takes hours. THIS is what a withdrawal landing mid run does: the run spends
    its GPU seconds and then cannot publish, so nothing derived from the photographs persists."""
    subject = admit_personal(repository, store, photo_bytes(), "midrun.jpg")
    right = _grant(subject)
    job_id = _queue(subject)
    scene_id = _scene_of(repository, job_id)
    # The run starts: the right is current and the trainer is permitted to read.
    assert require_scene_training(repository, job_id)

    withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=ACCOUNT)

    with (
        pytest.raises(psycopg.errors.CheckViolation, match="may not be published"),
        repository.connection.transaction(),
    ):
        _publish(repository, scene_id, "scene_splat_delivery")
    assert repository.connection.execute(
        "select count(*) as n from artifact where workspace_id=%s and scene_id=%s",
        (repository.workspace_id, scene_id),
    ).fetchone()["n"] == 0


def test_a_withdrawal_cancels_the_run_it_was_granted_for(repository, store):
    """A withdrawal does not only refuse what comes back. It ENDS THE RUN.

    Without this the photographs still reach the trainer: a job queued while the right stood is
    claimed later, its bytes are staged and handed over, and only the publication is refused. The
    bytes would already have gone to the GPU, which is the thing the standing instruction is about.

    The job's state before the withdrawal is asserted, not assumed. The trigger only touches
    queued, running and failed, so a test over a job in some other state would pass while measuring
    nothing.
    """
    subject = admit_personal(repository, store, photo_bytes(), "cancelled.jpg")
    right = _grant(subject)
    job_id = _queue(subject)
    before = _job(repository, job_id)
    assert before["status"] in ("queued", "running"), before["status"]

    withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=ACCOUNT)

    after = _job(repository, job_id)
    assert after["status"] == "cancelled"
    assert after["failure_class"] == "training_right_withdrawn"
    assert "withdrawn" in after["failure_message"]
    assert after["claim_token"] is None and after["lease_expires_at"] is None


def test_a_withdrawal_leaves_another_scene_alone(repository, store):
    """The control for the test above: cancelling every training job would also pass it."""
    mine = admit_personal(repository, store, photo_bytes(), "mine.jpg")
    theirs = admit_personal(repository, store, photo_bytes(size=(120, 80)), "theirs.jpg")
    right = _grant(mine)
    _grant(theirs)
    my_job = _queue(mine)
    their_job = _queue(theirs, subjects=[theirs])

    withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=ACCOUNT)

    assert _job(repository, my_job)["status"] == "cancelled"
    assert _job(repository, their_job)["status"] != "cancelled"


def test_the_evaluation_bundle_of_a_rejected_run_is_refused_too(repository, store):
    """A rejected run publishes no delivery and still publishes an evaluation bundle carrying
    rendered views of the scene, so the gate cannot be about the weights alone."""
    subject = admit_personal(repository, store, photo_bytes(), "rejected.jpg")
    right = _grant(subject)
    job_id = _queue(subject)
    scene_id = _scene_of(repository, job_id)
    withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=ACCOUNT)
    for kind in ("scene_splat_evaluation", "scene_splat_training", "scene_pose_receipt"):
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            repository.connection.transaction(),
        ):
            _publish(repository, scene_id, kind)


def test_a_withdrawal_refuses_every_further_read_of_what_was_trained(repository, store):
    """What withdrawal DOES to an artefact that already exists. It cannot un-train it, so every
    further read is refused from the instant the withdrawal commits, and the binding says which
    photograph stopped it."""
    subject = admit_personal(repository, store, photo_bytes(), "already-trained.jpg")
    right = _grant(subject)
    job_id = _queue(subject)
    artifact_id = _publish(repository, _scene_of(repository, job_id), "scene_splat_delivery")
    assert require_artifact_training_right(repository, artifact_id) is not None

    withdraw_training_right(repository, right_id=right.right_id, withdrawn_by=ACCOUNT)

    with pytest.raises(TrainingRightRefused) as refused:
        require_artifact_training_right(repository, artifact_id)
    assert refused.value.reason == "withdrawn"
    assert refused.value.capture_id == subject.capture_id
    assert isinstance(refused.value, PrivacyAdmissionError)
    # The record survives the withdrawal, which is what makes the destruction addressable.
    sources = artifact_training_sources(repository, artifact_id)
    assert [(source.capture_id, source.current) for source in sources] == [
        (subject.capture_id, False)
    ]


# -- the destination may not lie about where the bytes went ----------------------------------------


def test_a_tunnelled_gpu_is_not_spelled_localhost():
    """The reference compute is a rented VM reached over a tunnel, so localhost is exactly how it
    presents itself, and a right recording that would state the bytes never left this machine."""
    for spelling in ("http://localhost:8080", "https://localhost"):
        with pytest.raises(ValueError, match="loopback"):
            canonical_training_destination(spelling)
    # A dotted-quad never reaches that check: the egress allowlist refuses an address before this
    # function looks at the host. Named separately so a later reader knows WHICH guard fires, and
    # so removing one of the two cannot pass because the other happens to catch it.
    with pytest.raises(ValueError, match="names an address"):
        canonical_training_destination("https://127.0.0.1:8080")
    assert canonical_training_destination(LOCAL_PROCESS) == LOCAL_PROCESS
    assert canonical_training_destination(GPU) == GPU


def test_a_rented_host_names_its_provider_and_instance():
    assert rented_host("brev", "l40s-reference") == "rented-host:brev/l40s-reference"
    for provider, instance in (("", "x"), ("Brev", "x"), ("brev", ""), ("brev", "a b")):
        with pytest.raises(ValueError):
            rented_host(provider, instance)


def _bypass_triggers_and_insert(connection, row, **changes):
    """Insert a copy of ``row`` with its receipt rebuilt, triggers off, so only CHECKs decide."""
    values = {**row, "right_id": uuid.uuid4(), **changes}
    record = {**row["receipt_record"]}
    for field in ("destination", "purpose"):
        if field in changes:
            record[field] = changes[field]
    values["receipt_record"] = record
    values["receipt_canonical"] = canonical_json(record)
    values["receipt_sha256"] = sha256_digest(values["receipt_canonical"])
    columns = [key for key in values if key not in {"withdrawn_at", "withdrawn_by"}]
    connection.execute(
        f"insert into scene_training_right ({','.join(columns)}) "
        f"values ({','.join(['%s'] * len(columns))})",
        [Jsonb(values[c]) if c == "receipt_record" else values[c] for c in columns],
    )


def test_the_database_holds_one_spelling_of_each_destination(repository, store):
    """The destination CHECK itself, with the triggers off in a transaction that never commits.

    IT ASSERTS THE CONSTRAINT'S NAME, and that is the whole point of this version. The first one
    inserted a hand-made row and asserted only CheckViolation, which the profile CHECK raises
    first, so it passed whether or not the destination was refused at all. MEASURED: with the
    loopback alternative added back to the destination CHECK, that weaker test still passed all 21.
    """
    subject = admit_personal(repository, store, photo_bytes(), "direct.jpg")
    connection = repository.connection
    good = _grant(subject, destination=LOCAL_PROCESS)
    row = connection.execute(
        "select * from scene_training_right where right_id=%s", (good.right_id,)
    ).fetchone()
    refused = (
        "http://localhost:8080",
        "https://localhost",
        "http://models.example.org",
        "rented-host:Brev/l40s",
        "rented-host:brev",
        "https://models.example.org:443",
        "local-process ",
    )
    with connection.transaction():
        connection.execute("alter table scene_training_right disable trigger user")
        for index, destination in enumerate((LOCAL_PROCESS, GPU, "https://models.example.org")):
            with connection.transaction():
                _bypass_triggers_and_insert(
                    connection, row, destination=destination, purpose=f"accepted {index}"
                )
        for destination in refused:
            with (
                pytest.raises(psycopg.errors.CheckViolation) as violated,
                connection.transaction(),
            ):
                _bypass_triggers_and_insert(connection, row, destination=destination)
            assert violated.value.diag.constraint_name == "scene_training_right_destination_check"
        raise psycopg.Rollback()
    assert len(training_rights_for_capture(repository, subject.capture_id)) == 1


def test_a_right_does_not_allow_another_photograph(repository, store):
    """scene_training_right_allows compares the photograph, and this is what holds THAT line.

    The queue path filters by capture in ``scene_training_right_current`` as well, so removing the
    term from ``allows`` alone changes nothing any queue test can see. MEASURED: that break passed
    all 21 tests. This one asks ``allows`` directly, with its own positive control beside it.
    """
    subject = admit_personal(repository, store, photo_bytes(), "mine.jpg")
    other = admit_personal(repository, store, photo_bytes(size=(120, 80)), "theirs.jpg")
    right = _grant(subject)
    question = "select scene_training_right_allows(%s,%s,%s,%s,clock_timestamp()) as ok"
    allows = repository.connection.execute(
        question, (repository.workspace_id, right.right_id, subject.capture_id, GPU)
    ).fetchone()["ok"]
    refuses = repository.connection.execute(
        question, (repository.workspace_id, right.right_id, other.capture_id, GPU)
    ).fetchone()["ok"]
    assert (allows, refuses) == (True, False)


# -- what needs no right ---------------------------------------------------------------------------


def test_a_synthetic_scene_needs_no_training_right(repository, store, tmp_path):
    """Deny by default is about personal photographs. Synthetic and benchmark sources keep working,
    and this test is what stops the gate being tightened into uselessness."""
    intake = PhotoIngestPipeline(repository, store).ingest_intake(
        photo_bytes(), filename="generated.jpg"
    )
    capture = intake.capture_id
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=capture,
        actor=ACCOUNT,
        generator_manifest={"profile": "exulanica.synthetic-multiview/v1", "notice": "SYNTHETIC"},
        authorization_scope={"purpose": "training right test"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    admission = admit_reconstruction_scene(
        repository, capture_ids=[capture], screening_ids=[screening.screening_id]
    )
    assert admission.eligibility_state == "eligible", admission.blocking_reasons
    job_id, inserted = repository.enqueue_reconstruction_scene(
        capture_ids=[capture],
        selection_policy={"profile": "exulanica.training-right-test/v1"},
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
        build_inputs=_build_inputs(None),
    )
    assert inserted is True
    _register(repository, job_id, [capture])
    assert require_scene_training(repository, job_id) == ()
    artifact_id = _publish(repository, _scene_of(repository, job_id), "scene_splat_delivery")
    assert artifact_training_sources(repository, artifact_id) == ()
    assert require_artifact_training_right(repository, artifact_id) is not None


def test_a_pose_only_job_is_not_a_training_run(repository, store):
    """The gate reads the job's own declaration. A job that never says it will train is governed by
    the 0029 admission alone, and this right adds nothing to it."""
    subject = admit_personal(repository, store, photo_bytes(), "pose-only.jpg")
    admission = admit_reconstruction_scene(
        repository, capture_ids=[subject.capture_id], screening_ids=[subject.review_id]
    )
    job_id, inserted = repository.enqueue_reconstruction_scene(
        capture_ids=[subject.capture_id],
        selection_policy={"profile": "exulanica.training-right-test/pose"},
        privacy_admission_id=admission.admission_id,
        privacy_admission_digest=admission.admission_digest,
        build_inputs={"profile": "exulanica.pose-only/v0", "point_maps": []},
    )
    assert inserted is True
    _register(repository, job_id, [subject.capture_id])
    assert require_scene_training(repository, job_id) == ()
    artifact_id = _publish(repository, _scene_of(repository, job_id), "scene_pose_receipt")
    assert artifact_training_sources(repository, artifact_id) == ()


# -- the record cannot be rewritten ----------------------------------------------------------------


def test_a_right_is_never_deleted_or_rewritten(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "immutable.jpg")
    right = _grant(subject)
    connection = repository.connection
    for statement, parameters in (
        ("delete from scene_training_right where right_id=%s", (right.right_id,)),
        (
            "update scene_training_right set destination=%s where right_id=%s",
            (OTHER_GPU, right.right_id),
        ),
        (
            "update scene_training_right set valid_until=valid_until+interval '1 day' "
            "where right_id=%s",
            (right.right_id,),
        ),
    ):
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            connection.transaction(),
        ):
            connection.execute(statement, parameters)


def test_a_binding_is_never_rewritten_or_removed(repository, store):
    """A binding a caller could delete is a reconstruction that can be orphaned from its right."""
    subject = admit_personal(repository, store, photo_bytes(), "bound.jpg")
    _grant(subject)
    job_id = _queue(subject)
    artifact_id = _publish(repository, _scene_of(repository, job_id), "scene_splat_delivery")
    connection = repository.connection
    for statement in (
        "delete from scene_training_artifact where artifact_id=%s",
        "update scene_training_artifact set capture_id=capture_id where artifact_id=%s",
    ):
        with (
            pytest.raises(psycopg.errors.IntegrityConstraintViolation),
            connection.transaction(),
        ):
            connection.execute(statement, (artifact_id,))


def test_the_database_refuses_a_right_nobody_with_authority_granted(repository, store):
    subject = admit_personal(repository, store, photo_bytes(), "impostor.jpg")
    with pytest.raises(PrivacyAdmissionError, match="account holder"):
        grant_training_right(
            repository,
            capture_id=subject.capture_id,
            authorization_id=subject.authorization_id,
            destination=GPU,
            granted_by=SOMEBODY_ELSE,
            purpose=TRAINING_PURPOSE,
            valid_until=_now(repository) + dt.timedelta(minutes=30),
        )
    assert training_rights_for_capture(repository, subject.capture_id) == []
