"""A person's own photograph reaches a model only under a right that names the model and where.

A screening receipt says whether a photograph may be looked at or built from and names no model,
so until migration 0073 a receipt recorded for one model let every other one, local or hosted,
receive the same bytes. These tests hold the replacement to its sentence: no byte of a personal
photograph reaches a model unless a current, unwithdrawn right names that model and that
destination, checked at the moment of the read, and refused when absent.

Every refusal has its own test, and every path that hands bytes to a model has a test that the
model, or the transport under it, was never called. Asserting the error alone would pass for a
gate that raised after the request had gone.

Everything runs against PostgreSQL through the real migrations. Row-level security is exercised as
the non-owner role ``exulanica_app``, because the harness's owner connection bypasses it.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import types
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from exulanica.canonical import canonical_json, sha256_digest
from exulanica.db.roles import provision_runtime_role
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest import derivative_queue
from exulanica.ingest import model_rights as rights_module
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.model_rights import (
    LOCAL_PROCESS,
    ModelHandoff,
    ModelIdentity,
    ModelRightRefused,
    egress_origin,
    grant_model_right,
    model_rights_for_capture,
    require_model_right,
    withdraw_model_right,
)
from exulanica.ingest.person_detectors import RecordedObservationDetector
from exulanica.ingest.personal_admission import role_handoff
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    authorize_benchmark_capture,
    authorize_personal_capture,
    authorize_synthetic_capture,
    record_human_screening,
    record_person_detection_screening,
    record_synthetic_exemption,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import depth as depth_stage
from exulanica.ingest.stages import vision as vision_stage
from exulanica.ingest.stages.person_regions import reads_pixels
from exulanica.ingest.stages.segmentation import SEGMENTER_CONTRACT, Detections
from exulanica.ingest.stages.segmentation import model_handoff as segmentation_handoff
from exulanica.ingest.vision import NebiusVisionModel
from exulanica.ingest.worker import DerivativeWorker
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import PROVIDER, Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.reconstruction.moge import MoGeDepthModel
from exulanica.reconstruction.testing import FlatDepthModel
from exulanica.store.local import LocalContentAddressedStore
from psycopg.types.json import Jsonb

from conftest import CountingVisionModel, photo_bytes, scratch_role_database
from model_fakes import FakeTransport, chat_body
from pg_harness import open_scratch_connection
from test_intake_upload import upload as upload
from test_personal_admission_route import HostedVisionDouble, batch, post
from test_vision_contract import VALID as VALID_OBSERVATION
from tests_support_api import scratch_database

ACCOUNT = uuid.UUID("0b8e3f55-3c1e-4d8a-9b61-5f2a7c9e1d02")
SOMEBODY_ELSE = uuid.UUID("6f1d2c3b-4a59-4e87-8d76-1c2b3a4d5e6f")
PURPOSE = "Describe my own photographs so I can find them later"
MIGRATION = (
    Path(__file__).resolve().parents[1] / "exulanica/migrations/0073_personal_model_right.sql"
)

HOSTED = ModelHandoff.hosted(load_manifest(), Role.VISION)
DEPTH_DOUBLE = ModelIdentity.local("depth", "test/plane-depth", "1" * 40)
SEGMENTER = ModelIdentity.local("object_segmentation", "test/segmenter", "3" * 40)
DETECTOR = ModelIdentity.local("open_vocabulary_detection", "test/detector", "4" * 40)


# -- doubles --------------------------------------------------------------------------------------


class CountingDepth(FlatDepthModel):
    """The flat depth double, counting forward passes and stating the hand-over it was given."""

    def __init__(self, handoff: ModelHandoff | None) -> None:
        super().__init__()
        self.model_handoff = handoff
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        return super().predict(image)


@dataclasses.dataclass
class CountingSegmenter:
    """A local segmenter that finds nothing, and counts every time it is shown pixels."""

    detect_calls: int = 0
    segment_calls: int = 0

    @property
    def identity(self):
        return {
            "contract": SEGMENTER_CONTRACT,
            "segmenter": {
                "repo_id": SEGMENTER.model_id,
                "revision": SEGMENTER.revision,
                "license": "mit",
            },
            "detector": {
                "repo_id": DETECTOR.model_id,
                "revision": DETECTOR.revision,
                "license": "mit",
            },
            "detector_fallback": None,
            "library": {"torch": "test", "transformers": "test"},
        }

    @property
    def device(self):
        return "cpu"

    def detect(self, image, policy):
        self.detect_calls += 1
        return Detections(
            boxes=(), model=DETECTOR.ref, models_tried=(DETECTOR.ref,), fallback_used=False
        )

    def segment(self, image, boxes, policy):
        self.segment_calls += 1
        return []


class PixelReadingDetector:
    """A person detector that would look at the photograph it is handed."""

    model_id = "test/pixel-person-detector"
    requires_observation = False

    def __init__(self, handoff: ModelHandoff | None = None) -> None:
        self.calls = 0
        if handoff is not None:
            self.model_handoff = handoff

    def detect(self, image, context):
        self.calls += 1
        return ()


# -- setup ----------------------------------------------------------------------------------------


@dataclasses.dataclass
class Personal:
    repository: IngestRepository
    store: LocalContentAddressedStore
    capture_id: uuid.UUID
    authorization_id: uuid.UUID
    detection_id: uuid.UUID
    review_id: uuid.UUID | None


def _now(repository: IngestRepository) -> dt.datetime:
    return repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]


def admit_personal(
    repository: IngestRepository,
    store: LocalContentAddressedStore,
    data: bytes,
    name: str,
    *,
    reviewed: bool = True,
) -> Personal:
    """A photograph its account holder uploaded and authorized as personal, then screened.

    Always a detection receipt; also an eligible human review unless ``reviewed`` is false.
    """
    intake = PhotoIngestPipeline(repository, store).ingest_intake(data, filename=name)
    assert intake.capture_id is not None, intake.error
    now = _now(repository)
    authorization = authorize_personal_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACCOUNT,
        account_authority_basis="I took this photograph",
        authorization_scope={"purpose": PURPOSE},
        purpose=PURPOSE,
        authorized_at=now - dt.timedelta(hours=1),
        valid_until=now + dt.timedelta(hours=1),
    )
    detection = record_person_detection_screening(
        repository,
        authorization_id=authorization.authorization_id,
        authorized_by=ACCOUNT,
        purpose=PURPOSE,
        valid_until=now + dt.timedelta(hours=1),
    )
    review = None
    if reviewed:
        review = record_human_screening(
            repository,
            authorization_id=authorization.authorization_id,
            reviewed_by=ACCOUNT,
            sensitive_regions=[],
            valid_until=now + dt.timedelta(hours=1),
        )
        assert review.eligibility_state == "eligible"
    return Personal(
        repository,
        store,
        intake.capture_id,
        authorization.authorization_id,
        detection.screening_id,
        None if review is None else review.screening_id,
    )


@pytest.fixture
def store(tmp_path) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(tmp_path / "blobs")


@pytest.fixture
def personal(repository, store) -> Personal:
    return admit_personal(repository, store, photo_bytes(), "mine.jpg")


def grant(
    subject: Personal,
    identity: ModelIdentity,
    destination: str,
    *,
    granted_at: dt.datetime | None = None,
    valid_until: dt.datetime | None = None,
    capture_id: uuid.UUID | None = None,
):
    now = _now(subject.repository)
    return grant_model_right(
        subject.repository,
        capture_id=capture_id or subject.capture_id,
        authorization_id=subject.authorization_id,
        identity=identity,
        destination=destination,
        granted_by=ACCOUNT,
        purpose=PURPOSE,
        granted_at=granted_at,
        valid_until=valid_until or now + dt.timedelta(minutes=30),
    )


def grant_all(subject: Personal, handoff: ModelHandoff) -> list:
    return [grant(subject, identity, handoff.destination) for identity in handoff.identities]


def refusal(subject: Personal, handoff: ModelHandoff | None, *, screening=None) -> str:
    with pytest.raises(ModelRightRefused) as refused:
        require_model_right(
            subject.repository,
            subject.capture_id,
            screening or subject.detection_id,
            handoff,
        )
    assert isinstance(refused.value, PrivacyAdmissionError)
    return refused.value.reason


def stage_reason(repository: IngestRepository, run_id: uuid.UUID, stage: str) -> str:
    row = repository.connection.execute(
        "select error_message from pipeline_event where run_id=%s and stage_key=%s "
        "and type='stage_unavailable'",
        (run_id, stage),
    ).fetchone()
    assert row is not None, f"{stage} recorded no unavailable event"
    return row["error_message"]


def rows(repository: IngestRepository, sql: str) -> list:
    return repository.connection.execute(sql).fetchall()


# -- what a hand-over is --------------------------------------------------------------------------


def test_a_hosted_hand_over_names_the_whole_chain_at_the_exact_egress_origin():
    manifest = load_manifest()
    binding = manifest[Role.VISION]
    assert [identity.model_id for identity in HOSTED.identities] == [
        spec.model_id for spec in binding.chain
    ]
    assert len(HOSTED.identities) == 2, "the vision role declares a fallback"
    assert all(identity.provider == PROVIDER for identity in HOSTED.identities)
    assert all(identity.revision is None for identity in HOSTED.identities)
    assert HOSTED.destination == egress_origin(manifest.base_url)
    assert HOSTED.destination == "https://api.tokenfactory.nebius.com"


def test_a_destination_is_spelled_the_way_the_egress_allowlist_spells_it():
    assert egress_origin("https://example.org:443/v1?x=1") == "https://example.org"
    assert egress_origin("https://example.org:8443") == "https://example.org:8443"
    assert egress_origin("http://localhost:8080/models") == "http://localhost:8080"
    for refused in (
        "http://example.org",
        "https://127.0.0.1",
        "https://user@example.org",
        "ftp://example.org",
        "https://example",
        "local",
    ):
        with pytest.raises(ValueError):
            egress_origin(refused)


def test_an_identity_or_hand_over_that_cannot_be_named_is_refused():
    with pytest.raises(ValueError, match="full commit"):
        ModelIdentity(provider="local", role="depth", model_id="test/depth", revision=None)
    with pytest.raises(ValueError, match="revision"):
        ModelIdentity.local("depth", "test/depth", "main")
    with pytest.raises(ValueError, match="identifier"):
        ModelIdentity(provider=PROVIDER, role="vision", model_id="has space", revision=None)
    with pytest.raises(ValueError, match="local checkpoints"):
        ModelHandoff(identities=HOSTED.identities, destination=LOCAL_PROCESS)
    with pytest.raises(ValueError, match="at least one"):
        ModelHandoff(identities=(), destination=LOCAL_PROCESS)
    with pytest.raises(ValueError, match="once"):
        ModelHandoff(identities=(DEPTH_DOUBLE, DEPTH_DOUBLE), destination=LOCAL_PROCESS)


def test_each_stage_states_the_hand_over_its_model_makes(manifest, transport):
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=10),
    )
    assert NebiusVisionModel(client).model_handoff == HOSTED
    assert vision_stage.model_handoff(NebiusVisionModel(client)) == HOSTED
    assert vision_stage.model_handoff(CountingVisionModel()) is None
    assert vision_stage.model_handoff(HostedVisionDouble()) == HOSTED

    moge = object.__new__(MoGeDepthModel)
    moge._model_id = f"Ruicheng/moge-2-vitl@{'5' * 40}"
    assert depth_stage.model_handoff(moge) == ModelHandoff.local(
        ModelIdentity.local("depth", "Ruicheng/moge-2-vitl", "5" * 40)
    )
    unpinned = object.__new__(MoGeDepthModel)
    unpinned._model_id = "Ruicheng/moge-2-vitl"
    assert depth_stage.model_handoff(unpinned) is None
    assert depth_stage.model_handoff(FlatDepthModel()) is None

    segmenter = CountingSegmenter()
    assert segmentation_handoff(segmenter, detecting=False) == ModelHandoff.local(SEGMENTER)
    assert segmentation_handoff(segmenter, detecting=True) == ModelHandoff.local(
        SEGMENTER, DETECTOR
    )


def test_a_manifest_role_resolves_to_its_models_and_depth_is_not_one():
    assert role_handoff("vision") == HOSTED
    local = role_handoff("open_vocabulary_detection")
    assert local.destination == LOCAL_PROCESS
    assert len(local.identities) == 2
    assert all(identity.revision for identity in local.identities)
    with pytest.raises(ValueError, match="states no model role"):
        role_handoff("depth")


def test_the_migration_grants_nobody_anything():
    """Captures screened before 0073 have no right, and the migration invents none."""
    text = MIGRATION.read_text(encoding="utf-8").lower()
    assert "insert into" not in text
    assert "update personal_model_right" not in text


# -- the refusals, one each -----------------------------------------------------------------------


def test_a_right_for_every_model_in_the_chain_permits_the_hand_over(personal):
    granted = grant_all(personal, HOSTED)
    decision = require_model_right(
        personal.repository, personal.capture_id, personal.detection_id, HOSTED
    )
    assert decision.required is True
    assert [row.right_id for row in decision.rights] == [row.right_id for row in granted]
    assert [row.identity for row in decision.rights] == list(HOSTED.identities)


def test_a_screening_receipt_alone_is_not_a_model_right(personal):
    """Both receipts this capture holds are current, and neither names a model."""
    assert refusal(personal, HOSTED) == "missing"
    assert refusal(personal, HOSTED, screening=personal.review_id) == "missing"


def test_a_model_that_cannot_state_itself_is_refused(personal):
    grant_all(personal, HOSTED)
    assert refusal(personal, None) == "undeclared"


def test_an_expired_right_is_refused(personal):
    now = _now(personal.repository)
    for identity in HOSTED.identities:
        grant(
            personal,
            identity,
            HOSTED.destination,
            granted_at=now - dt.timedelta(minutes=30),
            valid_until=now - dt.timedelta(minutes=1),
        )
    assert refusal(personal, HOSTED) == "expired"


def test_a_withdrawn_right_is_refused_and_stays_withdrawn(personal):
    granted = grant_all(personal, HOSTED)
    right_id = granted[0].right_id
    withdrawn = withdraw_model_right(
        personal.repository, right_id=right_id, withdrawn_by=SOMEBODY_ELSE
    )
    assert withdrawn.withdrawn_at is not None
    assert withdrawn.withdrawn_by == SOMEBODY_ELSE
    assert refusal(personal, HOSTED) == "withdrawn"
    again = withdraw_model_right(personal.repository, right_id=right_id, withdrawn_by=ACCOUNT)
    assert (again.withdrawn_at, again.withdrawn_by) == (withdrawn.withdrawn_at, SOMEBODY_ELSE)
    with pytest.raises(psycopg.errors.CheckViolation, match="one final withdrawal"):
        personal.repository.connection.execute(
            "update personal_model_right set withdrawn_at=null,withdrawn_by=null where right_id=%s",
            (right_id,),
        )


def test_a_right_naming_another_model_is_refused(personal):
    other = ModelIdentity(provider=PROVIDER, role="vision", model_id="another/model", revision=None)
    grant(personal, other, HOSTED.destination)
    assert refusal(personal, HOSTED) == "other_model"


def test_a_right_for_the_primary_alone_does_not_cover_the_fallback(personal):
    grant(personal, HOSTED.identities[0], HOSTED.destination)
    assert refusal(personal, HOSTED) == "other_model"


def test_a_right_naming_another_revision_is_refused(personal):
    grant(personal, ModelIdentity.local("depth", "test/plane-depth", "2" * 40), LOCAL_PROCESS)
    with pytest.raises(ModelRightRefused, match="another revision") as refused:
        require_model_right(
            personal.repository,
            personal.capture_id,
            personal.review_id,
            ModelHandoff.local(DEPTH_DOUBLE),
        )
    assert refused.value.reason == "other_model"


def test_a_right_naming_another_destination_is_refused(personal):
    for identity in HOSTED.identities:
        grant(personal, identity, "https://models.example.org")
    assert refusal(personal, HOSTED) == "other_destination"
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    served = ModelHandoff(identities=(DEPTH_DOUBLE,), destination="http://localhost:8080")
    assert refusal(personal, served, screening=personal.review_id) == "other_destination"


def test_a_right_for_another_capture_is_refused(personal, repository, store):
    second = admit_personal(repository, store, photo_bytes(when="2026:08:27 11:00:00"), "b.jpg")
    grant_all(personal, HOSTED)
    assert refusal(second, HOSTED) == "missing"
    assert model_rights_for_capture(repository, second.capture_id) == []
    with pytest.raises(PrivacyAdmissionError, match="account holder"):
        grant(personal, HOSTED.identities[0], HOSTED.destination, capture_id=second.capture_id)


def test_a_right_in_another_workspace_is_invisible_and_refused(personal, spine_schema, store):
    psycopg_module, scratch = spine_schema
    provision_runtime_role(personal.repository.connection)
    app = scratch_role_database(scratch, "exulanica_app")
    granted = grant_all(personal, HOSTED)
    identity = HOSTED.identities[0]
    workspace = personal.repository.workspace_id
    other_workspace = uuid.uuid4()
    # The same bytes, uploaded and screened in another workspace by the same account holder.
    owner = open_scratch_connection(psycopg_module, scratch)
    try:
        elsewhere = admit_personal(
            IngestRepository(owner, other_workspace), store, photo_bytes(), "mine.jpg"
        )
    finally:
        owner.close()
    with app.session(other_workspace) as connection:
        visible = connection.execute("select count(*) as n from personal_model_right").fetchone()
        assert visible["n"] == 0
        allowed = connection.execute(
            "select personal_model_right_allows(%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()) as ok",
            (
                workspace,
                granted[0].right_id,
                personal.capture_id,
                identity.provider,
                identity.role,
                identity.model_id,
                identity.revision,
                HOSTED.destination,
            ),
        ).fetchone()["ok"]
        assert allowed is False
        updated = connection.execute(
            "update personal_model_right set withdrawn_at=clock_timestamp(),withdrawn_by=%s "
            "where workspace_id=%s returning right_id",
            (ACCOUNT, workspace),
        ).fetchall()
        assert updated == []
        stolen = connection.execute(
            "select receipt_record from personal_model_right where right_id=%s",
            (granted[0].right_id,),
        ).fetchall()
        assert stolen == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "insert into personal_model_right (workspace_id,right_id,capture_id,"
                "source_sha256,authorization_id,operation,model_provider,model_role,model_id,"
                "model_revision,destination,purpose,granted_by,granted_at,valid_until,"
                "receipt_record,receipt_canonical,receipt_sha256) values "
                "(%s,%s,%s,%s,%s,'model_processing','local','depth','x/y',%s,%s,'p',%s,"
                "now(),now()+interval '1 hour','{}','{}',%s)",
                (
                    workspace,
                    uuid.uuid4(),
                    personal.capture_id,
                    b"\x00" * 32,
                    personal.authorization_id,
                    "1" * 40,
                    LOCAL_PROCESS,
                    ACCOUNT,
                    b"\x00" * 32,
                ),
            )
        seen = dataclasses.replace(
            elsewhere, repository=IngestRepository(connection, other_workspace)
        )
        assert refusal(seen, HOSTED) == "missing"
    # And in its own workspace the right still holds, as the runtime role sees it.
    with app.session(workspace) as connection:
        mine = IngestRepository(connection, workspace)
        decision = require_model_right(mine, personal.capture_id, personal.detection_id, HOSTED)
        assert len(decision.rights) == len(HOSTED.identities)


# -- the screening still has to hold --------------------------------------------------------------


def test_a_right_does_not_stand_in_for_a_screening(personal, repository, store):
    grant_all(personal, HOSTED)
    other = admit_personal(repository, store, photo_bytes(when="2026:08:27 12:00:00"), "c.jpg")
    with pytest.raises(PrivacyAdmissionError, match="missing for the exact capture"):
        require_model_right(repository, personal.capture_id, other.detection_id, HOSTED)
    now = _now(repository)
    lapsed = record_person_detection_screening(
        repository,
        authorization_id=personal.authorization_id,
        authorized_by=ACCOUNT,
        purpose=PURPOSE,
        screened_at=now - dt.timedelta(minutes=10),
        valid_until=now - dt.timedelta(minutes=1),
    )
    with pytest.raises(PrivacyAdmissionError, match="no current receipt") as refused:
        require_model_right(repository, personal.capture_id, lapsed.screening_id, HOSTED)
    assert not isinstance(refused.value, ModelRightRefused)


def test_a_detection_receipt_with_a_right_still_builds_no_geometry(personal):
    """The right is for the model; the geometry question stays with the geometry receipt."""
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    depth = CountingDepth(ModelHandoff.local(DEPTH_DOUBLE))
    pipeline = PhotoIngestPipeline(personal.repository, personal.store, depth=depth)
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.detection_id
    )
    assert outcome.error is not None and "blocked" in outcome.error
    assert depth.calls == 0


# -- who needs a right ----------------------------------------------------------------------------


def test_synthetic_media_needs_no_right_and_keeps_working(repository, store):
    pipeline = PhotoIngestPipeline(repository, store)
    intake = pipeline.ingest_intake(photo_bytes(), filename="synthetic.jpg")
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACCOUNT,
        generator_manifest={"profile": "exulanica.synthetic-test-corpus/v1"},
        authorization_scope={"purpose": "model right test"},
    )
    exemption = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    decision = require_model_right(repository, intake.capture_id, exemption.screening_id, None)
    assert decision.required is False
    assert decision.rights == ()
    vision = CountingVisionModel()
    outcome = PhotoIngestPipeline(repository, store, vision=vision).ingest_derivatives(
        intake.capture_id, privacy_screening_id=exemption.screening_id
    )
    assert outcome.error is None
    assert vision.calls == 1


def _benchmark(repository: IngestRepository, store: LocalContentAddressedStore, digest: str):
    intake = PhotoIngestPipeline(repository, store).ingest_intake(photo_bytes(), filename="b.jpg")
    authorization = authorize_benchmark_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACCOUNT,
        official_source_url="https://example.invalid/dataset",
        retrieval_date="2026-09-16",
        license_document_sha256=digest * 64,
        permitted_use="model right test",
        authorization_scope={"purpose": "model right test"},
    )
    screening = record_person_detection_screening(
        repository,
        authorization_id=authorization.authorization_id,
        authorized_by=ACCOUNT,
        purpose="find the people in this photograph so they can be hidden",
    )
    return intake.capture_id, authorization, screening


def _claim_as_personal(repository: IngestRepository, capture_id: uuid.UUID) -> None:
    now = _now(repository)
    authorize_personal_capture(
        repository,
        capture_id=capture_id,
        actor=ACCOUNT,
        account_authority_basis="This is also my own photograph",
        authorization_scope={"purpose": PURPOSE},
        purpose=PURPOSE,
        authorized_at=now - dt.timedelta(minutes=1),
        valid_until=now + dt.timedelta(hours=1),
    )


def test_a_capture_anybody_claimed_as_personal_stays_personal(repository, store):
    """A benchmark receipt does not exempt bytes an account holder has also authorized."""
    capture_id, benchmark, screening = _benchmark(repository, store, "c")
    exempt = require_model_right(repository, capture_id, screening.screening_id, None)
    assert exempt.required is False
    _claim_as_personal(repository, capture_id)
    with pytest.raises(ModelRightRefused) as refused:
        require_model_right(repository, capture_id, screening.screening_id, HOSTED)
    assert refused.value.reason == "missing"
    with pytest.raises(PrivacyAdmissionError, match="personal authority"):
        grant_model_right(
            repository,
            capture_id=capture_id,
            authorization_id=benchmark.authorization_id,
            identity=HOSTED.identities[0],
            destination=HOSTED.destination,
            granted_by=ACCOUNT,
            purpose=PURPOSE,
            valid_until=_now(repository) + dt.timedelta(minutes=10),
        )


def test_bytes_once_authorized_as_personal_stay_personal_after_a_re_import(personal, store):
    """Deleting a capture and uploading the same bytes again does not launder them as benchmark."""
    repository = personal.repository
    repository.connection.execute(
        "update capture set deleted_at=clock_timestamp() where capture_id=%s",
        (personal.capture_id,),
    )
    repository.insert_tombstone(
        scope="capture", capture_id=personal.capture_id, requested_by=ACCOUNT, reason="test"
    )
    capture_id, _, screening = _benchmark(repository, store, "f")
    assert capture_id != personal.capture_id
    assert repository.capture(capture_id).blob_id == repository.capture(personal.capture_id).blob_id
    decision = "select personal_model_right_required(%s,%s,%s) as required"
    arguments = (repository.workspace_id, capture_id, screening.screening_id)
    assert repository.connection.execute(decision, arguments).fetchone()["required"] is True
    with pytest.raises(ModelRightRefused) as refused:
        require_model_right(repository, capture_id, screening.screening_id, HOSTED)
    assert refused.value.reason == "missing"


def test_a_look_alike_hand_over_states_nothing(personal):
    """Only a real hand-over naming at least one model can be matched to a right."""
    grant_all(personal, HOSTED)

    class Unchecked(ModelHandoff):
        def __post_init__(self):
            pass

    for pretender in (
        Unchecked(identities=(), destination=HOSTED.destination),
        types.SimpleNamespace(identities=(), destination=HOSTED.destination),
        types.SimpleNamespace(identities=HOSTED.identities, destination=HOSTED.destination),
    ):
        assert refusal(personal, pretender) == "undeclared"


def test_a_session_that_names_no_workspace_is_never_exempt(repository, store):
    """The owner connection bypasses row-level security, so only the predicate itself decides."""
    capture_id, _, screening = _benchmark(repository, store, "e")
    connection, workspace = repository.connection, repository.workspace_id
    question = "select personal_model_right_required(%s,%s,%s) as required"
    arguments = (workspace, capture_id, screening.screening_id)
    assert connection.execute(question, arguments).fetchone()["required"] is False
    connection.execute("select set_config('exulanica.workspace_id', '', false)")
    try:
        assert connection.execute(question, arguments).fetchone()["required"] is True
    finally:
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
    assert connection.execute(question, arguments).fetchone()["required"] is False


# -- the recheck at the moment of the read --------------------------------------------------------


def test_a_right_withdrawn_after_it_was_resolved_is_refused_at_the_read(
    personal, ingest_spine, monkeypatch
):
    grant_all(personal, HOSTED)
    _, open_another = ingest_spine
    elsewhere = open_another()
    resolve = rights_module._candidate

    def withdrawn_as_it_resolves(repository, capture_id, identity, destination):
        right_id = resolve(repository, capture_id, identity, destination)
        withdraw_model_right(elsewhere, right_id=right_id, withdrawn_by=ACCOUNT)
        return right_id

    monkeypatch.setattr(rights_module, "_candidate", withdrawn_as_it_resolves)
    assert refusal(personal, HOSTED) == "withdrawn"


def test_a_capture_claimed_as_personal_after_resolution_is_refused_at_the_read(
    repository, store, ingest_spine, monkeypatch
):
    capture_id, _, screening = _benchmark(repository, store, "d")
    _, open_another = ingest_spine
    elsewhere = open_another()
    resolve = rights_module._candidate

    def claimed_as_it_resolves(repository, capture, identity, destination):
        _claim_as_personal(elsewhere, capture)
        return resolve(repository, capture, identity, destination)

    monkeypatch.setattr(rights_module, "_candidate", claimed_as_it_resolves)
    with pytest.raises(ModelRightRefused) as refused:
        require_model_right(repository, capture_id, screening.screening_id, HOSTED)
    assert refused.value.reason == "missing"


def test_a_withdrawal_cannot_commit_while_a_final_read_check_holds_the_lock(personal, ingest_spine):
    granted = grant_all(personal, HOSTED)
    _, open_another = ingest_spine
    reader = open_another().connection
    with reader.transaction():
        reader.execute("select asset_read_lock()")
        with pytest.raises(psycopg.errors.SerializationFailure, match="asset delivery"):
            withdraw_model_right(
                personal.repository, right_id=granted[0].right_id, withdrawn_by=ACCOUNT
            )
    withdrawn = withdraw_model_right(
        personal.repository, right_id=granted[0].right_id, withdrawn_by=ACCOUNT
    )
    assert withdrawn.withdrawn_at is not None


# -- the database keeps the record honest ---------------------------------------------------------


def test_a_grant_is_recorded_once_and_digest_bound(personal):
    now = _now(personal.repository)
    until = now + dt.timedelta(minutes=5)
    first = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS, granted_at=now, valid_until=until)
    again = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS, granted_at=now, valid_until=until)
    assert again.right_id == first.right_id
    assert len(model_rights_for_capture(personal.repository, personal.capture_id)) == 1
    row = personal.repository.connection.execute(
        "select receipt_record,receipt_canonical,receipt_sha256 from personal_model_right "
        "where right_id=%s",
        (first.right_id,),
    ).fetchone()
    record = row["receipt_record"]
    assert record["model"] == DEPTH_DOUBLE.as_record()
    assert record["destination"] == LOCAL_PROCESS
    assert record["operation"] == "model_processing"
    assert record["capture_id"] == str(personal.capture_id)
    assert record["authorization"]["authorization_id"] == str(personal.authorization_id)
    assert record["granted_by"] == str(ACCOUNT)
    assert json.loads(bytes(row["receipt_canonical"])) == record
    assert bytes(row["receipt_sha256"]) == first.receipt_sha256


def test_the_database_refuses_a_right_nobody_with_authority_granted(personal):
    connection = personal.repository.connection
    good = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    stored = connection.execute(
        "select * from personal_model_right where right_id=%s", (good.right_id,)
    ).fetchone()

    def insert(**changes):
        values = {**stored, "right_id": uuid.uuid4(), **changes}
        columns = [key for key in values if key not in {"withdrawn_at", "withdrawn_by"}]
        parameters = [
            Jsonb(values[column]) if column == "receipt_record" else values[column]
            for column in columns
        ]
        with connection.transaction():
            connection.execute(
                f"insert into personal_model_right ({','.join(columns)}) "
                f"values ({','.join(['%s'] * len(columns))})",
                parameters,
            )

    with pytest.raises(psycopg.errors.CheckViolation, match="account holder"):
        insert(granted_by=SOMEBODY_ELSE)
    elsewhere = "https://models.example.org"
    tampered = {**stored["receipt_record"], "destination": elsewhere}
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(destination=elsewhere, receipt_record=tampered)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(model_provider=PROVIDER)
    with pytest.raises(psycopg.errors.CheckViolation, match="granted now"):
        insert(
            granted_at=stored["granted_at"] + dt.timedelta(minutes=10),
            valid_until=stored["valid_until"] + dt.timedelta(minutes=10),
        )


def test_a_right_is_never_deleted_or_rewritten(personal):
    good = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    connection = personal.repository.connection
    with pytest.raises(psycopg.errors.CheckViolation, match="never deleted"):
        connection.execute("delete from personal_model_right where right_id=%s", (good.right_id,))
    with pytest.raises(psycopg.errors.CheckViolation, match="one final withdrawal"):
        connection.execute(
            "update personal_model_right set valid_until=valid_until+interval '1 day' "
            "where right_id=%s",
            (good.right_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="one final withdrawal"):
        connection.execute(
            "update personal_model_right set withdrawn_at=clock_timestamp()+interval '1 day',"
            "withdrawn_by=%s where right_id=%s",
            (ACCOUNT, good.right_id),
        )


def _bypass_triggers_and_insert(connection, row, **changes):
    """Insert a copy of ``row`` with its receipt rebuilt, triggers off, so only CHECKs decide."""
    values = {**row, "right_id": uuid.uuid4(), **changes}
    record = {**row["receipt_record"]}
    if "destination" in changes:
        record["destination"] = changes["destination"]
    if "purpose" in changes:
        record["purpose"] = changes["purpose"]
    values["receipt_record"] = record
    values["receipt_canonical"] = canonical_json(record)
    values["receipt_sha256"] = sha256_digest(values["receipt_canonical"])
    columns = [key for key in values if key not in {"withdrawn_at", "withdrawn_by"}]
    connection.execute(
        f"insert into personal_model_right ({','.join(columns)}) "
        f"values ({','.join(['%s'] * len(columns))})",
        [Jsonb(values[c]) if c == "receipt_record" else values[c] for c in columns],
    )


def test_the_database_holds_one_spelling_of_each_destination(personal):
    """The CHECK itself, with the triggers switched off in a transaction that never commits."""
    connection = personal.repository.connection
    good = grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    row = connection.execute(
        "select * from personal_model_right where right_id=%s", (good.right_id,)
    ).fetchone()
    accepted = (
        "local-process",
        "https://api.tokenfactory.nebius.com",
        "https://models.example.org:8443",
        "https://localhost",
        "http://localhost:8080",
        "https://cdn.0xbeef.example.org",
    )
    refused = (
        "https://models.example.org:443",
        "https://models.example.org:0443",
        "https://models.example.org:0",
        "https://models.example.org:65536",
        "http://localhost:80",
        "https://localhost:443",
        "http://models.example.org",
        "https://127.0.0.1",
        "https://127.1",
        "https://127.0x1",
        "https://0x7f.0x1",
        "https://models",
        "https://Models.example.org",
        "https://" + "a" * 60 + "." + ".".join(["b" * 60] * 4) + ".org",
    )
    for destination in accepted:
        assert destination == LOCAL_PROCESS or egress_origin(destination) == destination
    with connection.transaction():
        connection.execute("alter table personal_model_right disable trigger user")
        for index, destination in enumerate(accepted):
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
            assert violated.value.diag.constraint_name == "personal_model_right_destination_check"
        with (
            pytest.raises(psycopg.errors.CheckViolation) as violated,
            connection.transaction(),
        ):
            _bypass_triggers_and_insert(connection, row, purpose="bell\x07ringing")
        assert violated.value.diag.constraint_name == "personal_model_right_purpose_check"
        raise psycopg.Rollback()
    assert len(model_rights_for_capture(personal.repository, personal.capture_id)) == 1
    assert (
        connection.execute(
            "select count(*) as n from pg_trigger where tgrelid='personal_model_right'::regclass "
            "and not tgisinternal and tgenabled='O'"
        ).fetchone()["n"]
        == 4
    )


def test_a_purpose_in_any_script_survives_the_receipt_check(personal):
    """Python's canonical JSON and the database's must agree byte for byte on free text."""
    purpose = 'Grand-m\u00e8re\u2019s "brick" wall \\ \u5bb6 \U0001f9f1 line\u2028sep \u00a0kept'
    right = grant_model_right(
        personal.repository,
        capture_id=str(personal.capture_id).upper(),
        authorization_id=str(personal.authorization_id).replace("-", ""),
        identity=DEPTH_DOUBLE,
        destination=LOCAL_PROCESS,
        granted_by=ACCOUNT,
        purpose=purpose,
        valid_until=_now(personal.repository) + dt.timedelta(minutes=5),
    )
    row = personal.repository.connection.execute(
        "select purpose,receipt_canonical,receipt_record from personal_model_right "
        "where right_id=%s",
        (right.right_id,),
    ).fetchone()
    assert row["purpose"] == purpose.strip()
    assert bytes(row["receipt_canonical"]) == canonical_json(row["receipt_record"])
    assert row["receipt_record"]["capture_id"] == str(personal.capture_id)


def test_a_grant_is_checked_before_it_is_written(personal):
    now = _now(personal.repository)
    later = now + dt.timedelta(minutes=5)
    with pytest.raises(ValueError, match="local checkpoint"):
        grant(personal, HOSTED.identities[0], LOCAL_PROCESS)
    with pytest.raises(ValueError, match="end after"):
        grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS, granted_at=now, valid_until=now)
    with pytest.raises(PrivacyAdmissionError, match="not current"):
        grant(
            personal,
            DEPTH_DOUBLE,
            LOCAL_PROCESS,
            granted_at=now - dt.timedelta(hours=2),
            valid_until=later,
        )
    for granted_by, purpose, refused in (
        (SOMEBODY_ELSE, PURPOSE, "account holder"),
        (ACCOUNT, "   ", "why"),
        (ACCOUNT, "line\nbreak", "printable"),
    ):
        with pytest.raises((PrivacyAdmissionError, ValueError), match=refused):
            grant_model_right(
                personal.repository,
                capture_id=personal.capture_id,
                authorization_id=personal.authorization_id,
                identity=DEPTH_DOUBLE,
                destination=LOCAL_PROCESS,
                granted_by=granted_by,
                purpose=purpose,
                valid_until=later,
            )
    assert model_rights_for_capture(personal.repository, personal.capture_id) == []


# -- every wired path refuses before a byte leaves ------------------------------------------------


def _hosted_client(transport: FakeTransport) -> NebiusVisionModel:
    return NebiusVisionModel(
        ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=10),
        )
    )


def test_the_hosted_vision_stage_sends_no_request_without_a_right(personal):
    transport = FakeTransport()
    pipeline = PhotoIngestPipeline(
        personal.repository, personal.store, vision=_hosted_client(transport)
    )
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.detection_id
    )
    assert outcome.error is None
    assert transport.requests == []
    assert "vision" in outcome.stages_unavailable
    assert "model right" in stage_reason(personal.repository, outcome.run_id, "vision")
    assert (
        rows(personal.repository, "select artifact_id from artifact where stage_key='vision'") == []
    )


def test_the_hosted_vision_stage_sends_one_request_to_the_named_origin_with_a_right(personal):
    transport = FakeTransport()
    transport.default = HttpResponse(
        status_code=200,
        text=json.dumps(
            chat_body(json.dumps(VALID_OBSERVATION), model=HOSTED.identities[0].model_id)
        ),
    )
    grant_all(personal, HOSTED)
    pipeline = PhotoIngestPipeline(
        personal.repository, personal.store, vision=_hosted_client(transport)
    )
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.detection_id
    )
    assert outcome.error is None, outcome.error
    assert "vision" in outcome.stages_run
    assert len(transport.requests) == 1
    assert egress_origin(transport.requests[0]["url"]) == HOSTED.destination
    assert transport.models_called == [HOSTED.identities[0].model_id]


def test_the_depth_stage_never_predicts_without_a_right(personal):
    depth = CountingDepth(ModelHandoff.local(DEPTH_DOUBLE))
    pipeline = PhotoIngestPipeline(personal.repository, personal.store, depth=depth)
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.review_id
    )
    assert outcome.error is None, outcome.error
    assert depth.calls == 0
    assert "depth" in outcome.stages_unavailable
    assert "model right" in stage_reason(personal.repository, outcome.run_id, "depth")
    point_maps = "select artifact_id from artifact where kind='point_map'"
    assert rows(personal.repository, point_maps) == []

    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.review_id
    )
    assert outcome.error is None, outcome.error
    assert depth.calls == 1
    assert len(rows(personal.repository, point_maps)) == 1


def test_a_depth_model_that_states_nothing_never_predicts(personal):
    grant(personal, DEPTH_DOUBLE, LOCAL_PROCESS)
    depth = CountingDepth(None)
    pipeline = PhotoIngestPipeline(personal.repository, personal.store, depth=depth)
    outcome = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.review_id
    )
    assert depth.calls == 0
    assert "does not state" in stage_reason(personal.repository, outcome.run_id, "depth")


def test_the_segmentation_stage_reads_no_pixels_without_a_right_for_each_checkpoint(personal):
    segmenter = CountingSegmenter()
    pipeline = PhotoIngestPipeline(personal.repository, personal.store, segmenter=segmenter)

    def run():
        return pipeline.ingest_derivatives(
            personal.capture_id, privacy_screening_id=personal.review_id
        )

    outcome = run()
    assert outcome.error is None, outcome.error
    assert (segmenter.detect_calls, segmenter.segment_calls) == (0, 0)
    assert "segmentation" in outcome.stages_unavailable

    grant(personal, SEGMENTER, LOCAL_PROCESS)
    outcome = run()
    assert segmenter.detect_calls == 0, "the detector reads the pixels too and has no right"
    assert "segmentation" in outcome.stages_unavailable

    grant(personal, DETECTOR, LOCAL_PROCESS)
    outcome = run()
    assert outcome.error is None, outcome.error
    assert segmenter.detect_calls == 1
    assert "segmentation" in outcome.stages_run


def _queue(subject: Personal) -> None:
    batch_row = IntakeBatch.open(subject.repository, label="model right test")
    batch_row.declare_size(1)
    derivative_queue.enqueue(
        subject.repository.connection,
        subject.repository.workspace_id,
        batch_id=batch_row.batch_id,
        capture_ids=[subject.capture_id],
    )


def _drain(subject: Personal, scratch: str, **models):
    return DerivativeWorker(
        scratch_database(scratch),
        subject.store,
        frozenset({subject.repository.workspace_id}),
        name="model-right-test",
        **models,
    ).drain()


def test_the_worker_sends_a_detection_pass_to_no_model_without_a_right(
    repository, store, spine_schema
):
    """The shipped detect flow: a detection receipt alone no longer sends anything anywhere."""
    _, scratch = spine_schema
    subject = admit_personal(repository, store, photo_bytes(), "mine.jpg", reviewed=False)
    vision = HostedVisionDouble()
    detector = PixelReadingDetector()
    _queue(subject)
    outcomes = _drain(subject, scratch, vision=vision, detector=detector)
    assert vision.calls == 0
    assert detector.calls == 0
    assert outcomes[0].errors == []
    reasons = {
        row["stage_key"]: row["error_message"]
        for row in repository.connection.execute(
            "select e.stage_key, e.error_message from pipeline_event e "
            "join pipeline_run r on r.run_id=e.run_id "
            "where r.capture_id=%s and e.type='stage_unavailable'",
            (subject.capture_id,),
        ).fetchall()
    }
    assert "no personal model right" in reasons["vision"]
    assert "does not state which model" in reasons["person_regions"]


def test_the_worker_hands_each_model_only_what_its_right_names(personal, spine_schema):
    _, scratch = spine_schema
    detector_identity = ModelIdentity.local("person_detector", "test/pixel-person", "6" * 40)
    grant_all(personal, HOSTED)
    grant(personal, detector_identity, LOCAL_PROCESS)
    vision = HostedVisionDouble()
    detector = PixelReadingDetector(ModelHandoff.local(detector_identity))
    _queue(personal)
    outcomes = _drain(personal, scratch, vision=vision, detector=detector)
    assert outcomes[0].errors == []
    assert vision.calls == 1
    assert detector.calls == 1


def test_only_a_detector_that_discards_the_image_is_ungated():
    """Exact types, so a subclass of a blind detector that reads the pixels is still gated."""

    class Curious(RecordedObservationDetector):
        pass

    assert reads_pixels(RecordedObservationDetector()) is False
    assert reads_pixels(PixelReadingDetector()) is True
    assert reads_pixels(Curious()) is True


def test_a_directly_built_pipeline_gates_its_person_detector(personal):
    """No worker in between: the person-region stage asks for the right itself."""
    identity = ModelIdentity.local("person_detector", "test/pixel-person", "6" * 40)
    detector = PixelReadingDetector(ModelHandoff.local(identity))
    pipeline = PhotoIngestPipeline(personal.repository, personal.store, detector=detector)

    unscreened = pipeline.ingest_derivatives(personal.capture_id)
    assert unscreened.error is None, unscreened.error
    assert detector.calls == 0
    assert "person_regions" in unscreened.stages_unavailable
    assert "no privacy screening" in stage_reason(
        personal.repository, unscreened.run_id, "person_regions"
    )

    refused = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.detection_id
    )
    assert detector.calls == 0
    assert "person_regions" in refused.stages_unavailable
    assert "no model right lets" in stage_reason(
        personal.repository, refused.run_id, "person_regions"
    )

    grant(personal, identity, LOCAL_PROCESS)
    allowed = pipeline.ingest_derivatives(
        personal.capture_id, privacy_screening_id=personal.detection_id
    )
    assert allowed.error is None, allowed.error
    assert detector.calls == 1
    assert "person_regions" in allowed.stages_run


# -- the ordinary API path ------------------------------------------------------------------------


def _vision_rights(body):
    return [{"role": "vision", "valid_until": body["authority"]["valid_until"]}]


def test_an_admission_that_names_no_model_sends_nothing(upload):
    body = batch(upload)
    body["model_rights"] = []
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    assert all(receipt["model_right_ids"] == [] for receipt in response.json()["receipts"])
    upload.drain(screened=False)
    assert isinstance(upload.vision, HostedVisionDouble)
    assert upload.vision.calls == 0
    assert upload.rows("select right_id from personal_model_right") == []


def test_an_admission_that_names_the_vision_role_grants_each_model_it_can_reach(upload):
    body = batch(upload)
    body["model_rights"] = _vision_rights(body)
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    for receipt in response.json()["receipts"]:
        granted = receipt["model_rights"]
        assert [right["model"] for right in granted] == [
            identity.as_record() for identity in HOSTED.identities
        ]
        assert {right["destination"] for right in granted} == {HOSTED.destination}
        assert all("purpose" not in right for right in granted)
    recorded = upload.rows("select right_id from personal_model_right")
    assert len(recorded) == len(body["members"]) * len(HOSTED.identities)
    upload.drain(screened=False)
    assert upload.vision.calls == len(body["members"])


def test_an_admission_refuses_a_right_it_cannot_name_before_writing_anything(upload):
    body = batch(upload)
    for requested in (
        [{"role": "depth", "valid_until": body["authority"]["valid_until"]}],
        [{"role": "vision", "valid_until": "2099-01-01T00:00:00+00:00"}],
        _vision_rights(body) * 2,
    ):
        body["model_rights"] = requested
        response = post(upload, "/personal-admission", body)
        assert response.status_code == 409, response.text
    assert upload.rows("select * from capture_reconstruction_authorization") == []
    assert upload.rows("select * from personal_model_right") == []


def test_a_replayed_admission_reports_whether_each_right_is_still_current(upload):
    body = batch(upload, count=1)
    body["model_rights"] = _vision_rights(body)
    body["request_id"] = str(uuid.uuid4())
    first = post(upload, "/personal-admission", body)
    assert first.status_code == 202, first.text
    receipt = first.json()["receipts"][0]
    assert [right["state"] for right in receipt["model_rights"]] == ["current", "current"]
    withdraw_model_right(
        upload.repository,
        right_id=uuid.UUID(receipt["model_right_ids"][0]),
        withdrawn_by=uuid.uuid4(),
    )
    replayed = post(upload, "/personal-admission", body).json()["receipts"][0]
    assert replayed["model_right_ids"] == receipt["model_right_ids"]
    assert [right["state"] for right in replayed["model_rights"]] == ["ended", "current"]
    status = upload.get("/personal-admission").json()
    source = next(s for s in status["sources"] if s["capture_id"] == receipt["capture_id"])
    assert sorted(right["state"] for right in source["model_rights"]) == ["current", "ended"]
