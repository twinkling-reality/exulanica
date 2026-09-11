"""Generated pixels through the real mask producer and shared SQL admission policy."""

from __future__ import annotations

import datetime as dt
import io
import os
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.canonical import canonical_json
from exulanica.consent.regions import Silhouette
from exulanica.env import env_get
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.masked_inputs import capture_mask_is_current
from exulanica.ingest.person_review import (
    create_subject,
    record_consent,
    record_region_edits,
    review_list,
)
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    admit_reconstruction_scene,
    authorize_personal_capture,
    record_human_screening,
    record_person_detection_screening,
)
from exulanica.ingest.spine.privacy import current_inputs
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.orchestration.demonstration import FrontierDemonstrationError, _authorized_screenings
from exulanica.orchestration.manifest import load_build_manifest
from exulanica.orchestration.preflight import inspect_database, run_frontier_preflight
from exulanica.store.local import LocalContentAddressedStore
from PIL import Image, ImageDraw
from psycopg.conninfo import make_conninfo

from test_frontier_manifest import _document

ACTOR = uuid.UUID("00000000-0000-4000-8000-000000000001")
KEY = b"a" * 32
OUTLINE = Silhouette(((0, 0), (500000, 0), (500000, 500000), (0, 500000)))


class Case:
    def __init__(self, repository, root):
        self.repo = repository
        self.root = root
        self.store = LocalContentAddressedStore(root / "data" / "blobs")
        self.pipeline = PhotoIngestPipeline(repository, self.store)
        photos = root / "photos"
        photos.mkdir(parents=True)
        image = Image.new("RGB", (160, 100), (30, 160, 200))
        ImageDraw.Draw(image).text((2, 70), "GENERATED TEST ONLY", fill="white")
        if root.name == "second":
            ImageDraw.Draw(image).rectangle((100, 0, 150, 30), fill="yellow")
        data = io.BytesIO()
        image.save(data, format="JPEG")
        self.data = data.getvalue()
        (photos / "a.jpg").write_bytes(self.data)
        intake = self.pipeline.ingest_intake(self.data, filename="a.jpg")
        assert intake.capture_id, intake.error
        self.capture = intake.capture_id
        self.auth = authorize_personal_capture(
            repository,
            capture_id=self.capture,
            actor=ACTOR,
            account_authority_basis="Operator generated these fixture bytes; no personal media",
            authorization_scope={"purpose": "generated screening currency rehearsal"},
            purpose="generated screening currency rehearsal",
        )
        self.detection = record_person_detection_screening(
            repository,
            authorization_id=self.auth.authorization_id,
            authorized_by=ACTOR,
            purpose="Find simulated sensitive regions in generated media",
        )
        self.subject = create_subject(repository, actor=ACTOR)

    def edit(self, action="add", *, outline=OUTLINE, subject=None, key=KEY):
        record_region_edits(
            self.repo,
            capture_id=self.capture,
            actor=ACTOR,
            edits=[
                {
                    "action": action,
                    "region_key": key.hex(),
                    "silhouette": outline.as_digest_input(),
                    "subject_id": subject,
                }
            ],
        )

    def consent(self, decision="granted", **kwargs):
        return record_consent(
            self.repo,
            subject_id=self.subject,
            actor=ACTOR,
            consent_scope="likeness",
            decision=decision,
            **kwargs,
        )

    def build(self):
        result = self.pipeline.ingest_derivatives(
            self.capture, privacy_screening_id=self.detection.screening_id
        )
        assert result.error is None, result.error
        return result

    def screen(self):
        return record_human_screening(
            self.repo,
            authorization_id=self.auth.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=review_list(self.repo, self.capture),
        )

    def allowed(self, screening):
        return self.repo.connection.execute(
            "select privacy_screening_allows_capture(%s,%s,%s) ok",
            (self.repo.workspace_id, self.capture, screening.screening_id),
        ).fetchone()["ok"]

    def mask(self):
        return self.repo.current_capture_artifacts(
            capture_ids=[self.capture], kind="masked_source"
        )[self.capture]

    def point(self, screening, mask=None):
        artifact_id = uuid.uuid4()
        self.repo.insert_artifact(
            artifact_id=artifact_id,
            kind="point_map",
            source_blob=self.repo.capture(self.capture).blob_id,
            stage_key="depth",
            stage_version=99,
            params_digest=b"p" * 32,
            input_digest=b"i" * 32,
            idempotency_key=str(uuid.uuid4()),
            content_sha256=b"d" * 32,
            storage_key="generated-point-map-placeholder",
            byte_size=1,
            produced_by_event=None,
            privacy_screening_id=screening.screening_id,
            read_source_sha256=mask.content_sha256 if mask else None,
        )

        return artifact_id

    def scene(self, screening):
        return admit_reconstruction_scene(
            self.repo,
            capture_ids=[self.capture],
            screening_ids=[screening.screening_id],
            admitted_at=dt.datetime.now(dt.UTC),
        )

    def frontier(self):
        from exulanica.migrations import migrations

        for migration in migrations():
            self.repo.connection.execute(
                "insert into schema_migrations(version,checksum) values (%s,%s) "
                "on conflict (version) do nothing",
                (migration.version, migration.checksum),
            )
        second = Case(self.repo, self.root / "second")
        second.screen()
        # A distinct generated capture supplies frontier's required second source.
        (self.root / "photos" / "b.jpg").write_bytes(second.data)
        doc = _document(self.root / "photos")
        doc["workspace_id"] = str(self.repo.workspace_id)
        doc["pipeline"]["depth"] = "moge"
        path = self.root / "frontier.json"
        path.write_bytes(canonical_json(doc))
        schema = self.repo.connection.execute("select current_schema() s").fetchone()["s"]
        # The database this schema lives in. The preflight itself still refuses any database but
        # the reference one, so off it this fails there, by name, instead of reading its schema.
        url = make_conninfo(env_get("TEST_DATABASE_URL"), options=f"-csearch_path={schema},public")
        return path, load_build_manifest(path), url


@pytest.fixture
def case(repository, tmp_path):
    return Case(repository, tmp_path)


def test_shared_stale_screening_end_to_end(repository, tmp_path, monkeypatch):
    root = Path(os.environ.get("EXULANICA_SCREENING_EVIDENCE_DIR", tmp_path))
    case = Case(repository, root)
    empty = case.screen()
    assert case.allowed(empty)
    assert not case.allowed(case.detection)
    case.edit()
    assert not case.allowed(empty)
    assert case.screen().eligibility_state == "blocked"
    case.build()
    first_mask = case.mask()
    first = case.screen()
    assert case.allowed(first)
    assert case.scene(first).eligibility_state == "eligible"
    case.point(first, first_mask)
    path, manifest, url = case.frontier()
    assert inspect_database(url, manifest)["screened_sources"] == 2
    assert _authorized_screenings(repository, manifest, vision=None, depth=object())
    monkeypatch.setenv("EXULANICA_DATABASE_URL", url)

    def preflight():
        result = run_frontier_preflight(
            manifest_path=path,
            photo_dir=root / "photos",
            data_dir=root / "data",
            output=root / "output",
            private_key=root / "not-supplied.pem",
        )
        return next(c for c in result["checks"] if c["check"] == "database_schema_and_screening")

    assert preflight()["status"] == "passed"
    original_receipt = repository.connection.execute(
        "select receipt_digest from reconstruction_privacy_screening where screening_id=%s",
        (first.screening_id,),
    ).fetchone()["receipt_digest"]
    case.edit("confirm", outline=Silhouette(((0, 0), (800000, 0), (800000, 500000), (0, 500000))))
    assert case.screen().eligibility_state == "blocked"
    assert not case.allowed(first), "stale SQL screening must be refused"
    assert not capture_mask_is_current(repository, case.capture), "obsolete mask must be refused"
    assert case.scene(first).eligibility_state == "blocked"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        case.point(first, first_mask)
    with pytest.raises(ValueError, match="screening"):
        inspect_database(url, manifest)
    with pytest.raises(FrontierDemonstrationError):
        _authorized_screenings(repository, manifest, vision=None, depth=object())
    assert preflight()["status"] == "failed"
    case.build()
    assert not case.allowed(first), "rebuild must not revive the old review"
    final = case.screen()
    assert case.allowed(final)
    with pytest.raises(psycopg.errors.CheckViolation, match="current masked"):
        case.point(final, first_mask)
    case.point(final, case.mask())
    assert case.scene(final).eligibility_state == "eligible"
    assert preflight()["status"] == "passed"
    assert not case.build().stages_run
    assert (
        repository.connection.execute(
            "select receipt_digest from reconstruction_privacy_screening where screening_id=%s",
            (first.screening_id,),
        ).fetchone()["receipt_digest"]
        == original_receipt
    )
    if "EXULANICA_SCREENING_EVIDENCE_DIR" in os.environ:
        (root / "scenario.json").write_bytes(
            canonical_json(
                {
                    "generated_media_only": True,
                    "model_calls": 0,
                    "depth_inference": False,
                    "point_map_payload": "placeholder; real SQL write boundary exercised",
                    "stale_sql_refused": True,
                    "stale_frontier_refused": True,
                    "stale_scene_blocked": True,
                    "stale_point_map_refused": True,
                    "rebuild_does_not_revive_review": True,
                    "rescreen_retry_succeeded": True,
                    "receipt_unchanged": True,
                    "full_preflight_signing_key": "not supplied",
                    "mask_sha256_before": first_mask.content_sha256.hex(),
                    "mask_sha256_after": case.mask().content_sha256.hex(),
                }
            )
        )


@pytest.mark.parametrize("kind", ["expired", "future", "region-precedence", "unknown"])
def test_producer_consent_currency(case, kind):
    now = dt.datetime.now(dt.UTC)
    subject = case.subject if kind != "unknown" else None
    case.edit(subject=subject)
    if kind == "expired":
        case.consent(
            effective_at=now - dt.timedelta(days=2), valid_until=now - dt.timedelta(days=1)
        )
    elif kind == "future":
        case.consent(effective_at=now + dt.timedelta(days=1))
    elif kind == "region-precedence":
        case.consent("revoked", region_key=KEY, effective_at=now - dt.timedelta(days=1))
        case.consent(effective_at=now)
    assert region_state_for_capture(case.repo, case.capture).any_masked
    assert case.screen().eligibility_state == "blocked"
    assert "masked_source" in case.build().stages_run
    screened = case.screen()
    assert case.allowed(screened)
    case.point(screened, case.mask())


def test_expiry_without_write_requires_rebuild_and_rescreen(case):
    case.edit(subject=case.subject)
    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=2)
    case.consent(valid_until=deadline)
    first = case.screen()
    assert case.allowed(first)
    case.build()
    assert not region_state_for_capture(case.repo, case.capture).any_masked
    # Wait only for this actual clock boundary, not a fake time or a consent write.
    time.sleep(max(0, (deadline - dt.datetime.now(dt.UTC)).total_seconds()) + 0.02)
    assert not case.allowed(first)
    assert region_state_for_capture(case.repo, case.capture).any_masked
    assert "masked_source" in case.build().stages_run
    final = case.screen()
    assert case.allowed(final)
    case.point(final, case.mask())


def test_consent_change_withdrawal_and_region_delete(case):
    case.edit(subject=case.subject)
    case.build()
    first = case.screen()
    case.consent()
    assert not case.allowed(first)
    shown = case.screen()
    assert case.allowed(shown)
    # A named old mask is checked even when the source now requires no mask.
    with pytest.raises(psycopg.errors.CheckViolation):
        case.point(shown, case.mask())
    case.edit("delete", subject=case.subject)
    assert not case.allowed(shown)
    empty = case.screen()
    assert case.allowed(empty)
    case.edit(subject=case.subject)
    assert not case.allowed(empty)
    case.consent("withdrawn")
    case.build()
    assert region_state_for_capture(case.repo, case.capture).resolved[KEY].state == "withdrawn"
    assert not case.allowed(case.screen())


def test_cross_workspace_and_legacy_receipts(case):
    screening = case.screen()
    assert case.allowed(screening)
    assert not case.repo.connection.execute(
        "select privacy_screening_allows_capture(%s,%s,%s) ok",
        (uuid.uuid4(), case.capture, screening.screening_id),
    ).fetchone()["ok"]
    # Insert a correctly digested historical receipt with no current-input binding.
    from exulanica.canonical import sha256_of_canonical
    from exulanica.evidence.blob import BlobId

    row = case.repo.connection.execute(
        "select * from reconstruction_privacy_screening where screening_id=%s",
        (screening.screening_id,),
    ).fetchone()
    record = dict(row["receipt_record"])
    del record["privacy_inputs"]
    legacy = case.repo.insert_privacy_screening(
        screening_id=uuid.uuid4(),
        authorization_id=case.auth.authorization_id,
        capture_id=case.capture,
        source_sha256=BlobId(bytes(row["source_sha256"])),
        screening_method="human_review",
        human_review_required=True,
        reviewed_by=ACTOR,
        sensitive_regions=[],
        eligibility_state="eligible",
        blocking_reasons=[],
        policy_version=row["policy_version"],
        policy_params_digest=bytes(row["policy_params_digest"]),
        authorization_scope=row["authorization_scope"],
        screened_at=row["screened_at"],
        valid_until=None,
        receipt_record=record,
        receipt_canonical=canonical_json(record),
        receipt_digest=sha256_of_canonical(record),
    )
    assert not case.allowed(legacy)
    assert case.allowed(screening)


def test_policy_waits_for_region_commit_and_refreshes_snapshot(ingest_spine, tmp_path):
    repo, open_another = ingest_spine
    case = Case(repo, tmp_path)
    first = case.screen()
    other = open_another()
    results = []
    entered = threading.Event()

    def check():
        entered.set()
        results.append(other.privacy_screening_allows(case.capture, first.screening_id))

    with repo.connection.transaction():
        case.edit()
        worker = threading.Thread(target=check)
        worker.start()
        assert entered.wait(1)
        time.sleep(0.05)
        assert worker.is_alive(), "shared predicate must wait for the privacy writer"
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results == [False]


def test_policy_rejects_repeatable_read_snapshot(case):
    with case.repo.connection.transaction():
        case.repo.connection.execute("set transaction isolation level repeatable read")
        with pytest.raises(psycopg.errors.SerializationFailure, match="read committed"):
            current_inputs(
                WorkspaceScope(case.repo.connection, case.repo.workspace_id), case.capture
            )


def test_input_digest_guard(case):
    case.edit()
    case.build()
    assert capture_mask_is_current(case.repo, case.capture)
    case.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    assert not capture_mask_is_current(case.repo, case.capture), (
        "obsolete mask input digest accepted"
    )


def test_review_must_bind_an_existing_mask(case):
    from exulanica.ingest.privacy import _record_screening

    case.edit()
    # Exercise a lower-level caller claiming eligible before a mask exists. The immutable
    # receipt cannot acquire a mask binding merely because a worker finishes later.
    premature = _record_screening(
        case.repo,
        authorization=case.auth,
        method="human_review",
        reviewed_by=ACTOR,
        sensitive_regions=review_list(case.repo, case.capture),
        eligibility_state="eligible",
        blocking_reasons=[],
        screened_at=None,
        valid_until=None,
    )
    assert not case.allowed(premature)
    case.build()
    assert not case.allowed(premature), "a mask built later must not activate an unbound review"
    assert case.allowed(case.screen())


def test_mask_lineage_and_geometry_updates(case):
    case.edit()
    case.build()
    mask = case.mask()
    first = case.screen()
    point = case.point(first, mask)
    with pytest.raises(psycopg.errors.CheckViolation, match="lineage is immutable"):
        case.repo.connection.execute(
            "update artifact set input_digest=%s where artifact_id=%s",
            (b"x" * 32, mask.artifact_id),
        )
    case.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    case.build()
    final = case.screen()
    with pytest.raises(psycopg.errors.CheckViolation, match="current masked"):
        case.repo.connection.execute(
            "update artifact set privacy_screening_id=%s where artifact_id=%s",
            (final.screening_id, point),
        )
    # Historical bytes can still be erased when they no longer authorize new work.
    case.repo.connection.execute(
        "update artifact set content_sha256=null where artifact_id=%s", (point,)
    )


def test_one_explicit_instant_controls_all_consent_scopes(case):
    case.edit(subject=case.subject)
    boundary = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    case.consent(valid_until=boundary)
    before = case.repo.connection.execute(
        "select privacy_inputs_at(%s,%s,%s) inputs",
        (case.repo.workspace_id, case.capture, boundary - dt.timedelta(microseconds=1)),
    ).fetchone()["inputs"]
    after = case.repo.connection.execute(
        "select privacy_inputs_at(%s,%s,%s) inputs",
        (case.repo.workspace_id, case.capture, boundary),
    ).fetchone()["inputs"]
    assert before["regions"][0]["state"] == "shown"
    assert after["regions"][0]["state"] == "unknown"


def test_worker_refuses_missing_or_obsolete_mask_declaration(case):
    from dataclasses import replace

    from exulanica.ingest.masked_inputs import masked_source_declarations, verify_masked_sources
    from exulanica.ingest.spine.reconstruction_jobs import SceneJobMember

    from test_masked_scene_inputs import _job

    member = SceneJobMember(case.capture, 0, case.repo.capture(case.capture).blob_id, "image/jpeg")
    job = replace(_job({}, members=(member,)), build_inputs={})
    assert verify_masked_sources(case.repo, job) == {}
    case.edit()
    case.build()
    with pytest.raises(PrivacyAdmissionError, match="require a declared"):
        verify_masked_sources(case.repo, job)
    declared = masked_source_declarations(case.repo, [case.capture])
    job = replace(job, build_inputs={"masked_sources": declared})
    assert verify_masked_sources(case.repo, job)
    case.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    with pytest.raises(PrivacyAdmissionError, match="stale"):
        verify_masked_sources(case.repo, job)


def test_receipt_input_binding_guard(case):
    case.edit()
    case.build()
    first = case.screen()
    assert case.allowed(first)
    # A new review input with identical effective pixels can reuse its mask, but the earlier
    # review must not silently attest to the new edit receipt.
    case.edit("confirm")
    assert capture_mask_is_current(case.repo, case.capture)
    assert not case.allowed(first), "changed review inputs reused a historical screening"
    assert case.allowed(case.screen())


def test_expiry_is_rechecked_after_waiting_for_privacy_lock(ingest_spine, tmp_path):
    repo, open_another = ingest_spine
    case = Case(repo, tmp_path)
    case.edit(subject=case.subject)
    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=2)
    case.consent(valid_until=deadline)
    screening = case.screen()
    other = open_another()
    results = []
    entered = threading.Event()

    def check():
        entered.set()
        results.append(other.privacy_screening_allows(case.capture, screening.screening_id))

    with repo.connection.transaction():
        repo.connection.execute("select privacy_currency_lock(%s)", (repo.workspace_id,))
        worker = threading.Thread(target=check)
        worker.start()
        assert entered.wait(1)
        time.sleep(max(0, (deadline - dt.datetime.now(dt.UTC)).total_seconds()) + 0.02)
        assert worker.is_alive()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results == [False]


def test_concurrent_subject_writers_refuse_duplicate_allocation(
    ingest_spine, tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from exulanica.ingest.repository import IngestRepository

    repo, open_another = ingest_spine
    case = Case(repo, tmp_path)
    writers = [open_another(), open_another()]
    barrier = threading.Barrier(2)
    original = IngestRepository.next_person_consent_sequence

    def allocated(self, **kwargs):
        sequence = original(self, **kwargs)
        barrier.wait(timeout=5)
        return sequence

    monkeypatch.setattr(IngestRepository, "next_person_consent_sequence", allocated)
    when = dt.datetime.now(dt.UTC)

    def write(pair):
        writer, decision = pair
        try:
            record_consent(
                writer,
                subject_id=case.subject,
                actor=ACTOR,
                consent_scope="likeness",
                decision=decision,
                effective_at=when,
            )
            return "committed"
        except psycopg.errors.SerializationFailure:
            return "retry"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, zip(writers, ["granted", "revoked"], strict=True)))
    assert sorted(results) == ["committed", "retry"], "duplicate subject-wide sequence was accepted"
    monkeypatch.setattr(IngestRepository, "next_person_consent_sequence", original)
    case.consent("revoked", effective_at=when + dt.timedelta(microseconds=1))
    rows = repo.connection.execute(
        "select sequence from person_presentation_consent where subject_id=%s order by sequence",
        (case.subject,),
    ).fetchall()
    assert [row["sequence"] for row in rows] == [0, 1]
    # An exact stored receipt can still be replayed with its original ID/content.
    row = repo.connection.execute(
        "select * from person_presentation_consent where subject_id=%s and sequence=0",
        (case.subject,),
    ).fetchone()
    repo.insert_person_consent(
        **{
            key: row[key]
            for key in (
                "consent_id",
                "subject_id",
                "region_key",
                "consent_scope",
                "decision",
                "sequence",
                "actor_id",
                "actor_role",
                "effective_at",
                "valid_until",
                "consent_record",
                "consent_canonical",
                "consent_digest",
            )
        }
    )


def test_stale_or_missing_claimed_review_inputs_do_not_authorize(case):
    case.edit()
    case.build()
    original = review_list(case.repo, case.capture)
    minimal = [{"region_key": original[0]["region_key"], "state": original[0]["state"]}]
    receipt = record_human_screening(
        case.repo,
        authorization_id=case.auth.authorization_id,
        reviewed_by=ACTOR,
        sensitive_regions=minimal,
    )
    assert receipt.eligibility_state == "eligible"  # Historical caller outcome, not permission.
    assert not case.allowed(receipt), "missing claimed review fields must not be synthesized"
    case.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    case.build()
    stale = record_human_screening(
        case.repo,
        authorization_id=case.auth.authorization_id,
        reviewed_by=ACTOR,
        sensitive_regions=original,
    )
    assert not case.allowed(stale), "old review outline must not bind fresh inputs"
    assert case.allowed(case.screen())


def test_subject_consent_serializes_across_captures(ingest_spine, tmp_path):
    repo, open_another = ingest_spine
    first = Case(repo, tmp_path / "first")
    second = Case(repo, tmp_path / "second")
    first.edit(subject=first.subject)
    second.edit(subject=first.subject)
    first.build()
    second.build()
    screening = second.screen()
    other = open_another()
    results = []
    entered = threading.Event()

    def check():
        entered.set()
        results.append(other.privacy_screening_allows(second.capture, screening.screening_id))

    with repo.connection.transaction():
        first.consent()
        worker = threading.Thread(target=check)
        worker.start()
        assert entered.wait(1)
        time.sleep(0.05)
        assert worker.is_alive()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results == [False]


def test_actual_personal_command_preserves_review_inputs(case, tmp_path):
    import json
    import subprocess
    import sys

    from exulanica.migrations import migrations

    from pg_harness import apply_migration
    from test_personal_admission_command import document

    root = (
        Path(os.environ["EXULANICA_SCREENING_EVIDENCE_DIR"]) / "command"
        if "EXULANICA_SCREENING_EVIDENCE_DIR" in os.environ
        else tmp_path / "command"
    )
    root = root.resolve()
    photos = root / "photos"
    photos.mkdir(parents=True)
    (photos / "a.jpg").write_bytes(case.data)
    doc = document(case.data)
    doc["source"]["path"] = "a.jpg"
    schema = "exulanica_personal_currency_" + uuid.uuid4().hex
    calls = []
    # The command pins its own database, so pointing that one constant at the configured one is
    # what lets this run anywhere the schema above actually exists. Everything else is the real
    # command in its own process: its argument parsing, its refusals and its exit codes. The URL
    # travels in the environment the child already inherits rather than in argv, which is recorded.
    entry = (
        "from exulanica.env import env_get; "
        "from exulanica.ingest import personal_admission_command as command; "
        "command.DATABASE_URL = env_get('TEST_DATABASE_URL'); "
        "raise SystemExit(command.main())"
    )
    with psycopg.connect(env_get("TEST_DATABASE_URL")) as owner:
        apply_migration(owner, schema)
        try:
            for migration in migrations():
                owner.execute(
                    "insert into schema_migrations(version,checksum) values (%s,%s)",
                    (migration.version, migration.checksum),
                )
            owner.commit()

            def run(operation, *, expected=0, **changes):
                doc.update(
                    operation=operation,
                    recorded_at=dt.datetime.now(dt.UTC).isoformat(),
                    review="not-reviewed",
                    edits=[],
                )
                doc.update(changes)
                path = root / f"{len(calls):02d}-{operation}.json"
                path.write_bytes(canonical_json(doc))
                argv = [
                    sys.executable,
                    "-c",
                    entry,
                    "--schema",
                    schema,
                    "--manifest",
                    str(path),
                    "--photo-dir",
                    str(photos),
                    "--data-dir",
                    str(root / "data"),
                ]
                result = subprocess.run(argv, capture_output=True, text=True, check=False)
                payload = json.loads(result.stdout)
                assert result.returncode == expected, payload
                calls.append(
                    {
                        "argv": [s.replace(str(Path.cwd()), "<worktree>") for s in argv],
                        "exit_code": result.returncode,
                        "response": payload,
                    }
                )
                return payload.get("result")

            admitted = run("admit")
            doc["source"]["capture_id"] = admitted["capture_id"]
            doc["authorization_id"] = admitted["authorization_id"]
            detection = run("detect")
            doc["screening_id"] = detection["screening_id"]
            assert (
                run(
                    "review",
                    review="confirmed-regions",
                    edits=[
                        {
                            "action": "add",
                            "region_key": KEY.hex(),
                            "silhouette": OUTLINE.as_digest_input(),
                        }
                    ],
                )["eligibility_state"]
                == "blocked"
            )
            run("mask")
            final = run("rescreen", review="confirmed-regions")
            assert final["eligibility_state"] == "eligible"
            doc["screening_id"] = final["screening_id"]
            run("geometry-check")
            assert (
                run(
                    "review",
                    review="confirmed-regions",
                    edits=[
                        {
                            "action": "confirm",
                            "region_key": KEY.hex(),
                            "silhouette": Silhouette(
                                ((0, 0), (900000, 0), (900000, 500000), (0, 500000))
                            ).as_digest_input(),
                        }
                    ],
                )["eligibility_state"]
                == "blocked"
            )
            run("geometry-check", expected=1)
            doc["screening_id"] = detection["screening_id"]
            run("mask")
            final = run("rescreen", review="confirmed-regions")
            doc["screening_id"] = final["screening_id"]
            run("geometry-check")
            if "EXULANICA_SCREENING_EVIDENCE_DIR" in os.environ:
                (root / "commands.json").write_bytes(canonical_json({"calls": calls}))
        finally:
            owner.rollback()
            owner.execute(
                psycopg.sql.SQL("drop schema {} cascade").format(psycopg.sql.Identifier(schema))
            )
            owner.commit()


@pytest.mark.parametrize("change", ["delete", "likeness"])
def test_scene_selection_omits_unneeded_historical_masks(case, change):
    from exulanica.ingest.masked_inputs import masked_source_declarations

    case.edit(subject=case.subject)
    case.build()
    first = case.screen()
    assert masked_source_declarations(case.repo, [case.capture])
    if change == "delete":
        case.edit("delete", subject=case.subject)
    else:
        case.consent()
    assert not case.allowed(first)
    assert masked_source_declarations(case.repo, [case.capture]) == []
    fresh = case.screen()
    assert case.allowed(fresh)
    assert case.scene(fresh).eligibility_state == "eligible"
    case.point(fresh)


def test_scene_selection_handles_mixed_members_and_missing_required_mask(case):
    from exulanica.ingest.masked_inputs import masked_source_declarations

    second = Case(case.repo, case.root / "second")
    case.edit()
    with pytest.raises(PrivacyAdmissionError, match="required current masked source is missing"):
        masked_source_declarations(case.repo, [case.capture, second.capture])
    case.build()
    declarations = masked_source_declarations(case.repo, [case.capture, second.capture])
    assert [item["capture_ref"] for item in declarations] == [str(case.capture)]
    assert masked_source_declarations(case.repo, [second.capture]) == []


def test_scene_selection_finds_current_lineage_among_obsolete_candidates(case):
    from exulanica.ingest.masked_inputs import masked_source_declarations

    case.edit()
    case.build()
    old = case.mask()
    case.edit("confirm", outline=Silhouette(((0, 0), (900000, 0), (900000, 500000), (0, 500000))))
    case.build()
    current = case.mask()
    # Make the obsolete candidate sort newest without relabeling its immutable input lineage.
    case.repo.connection.execute(
        "update artifact set created_at=clock_timestamp()+interval '1 day' where artifact_id=%s",
        (old.artifact_id,),
    )
    assert case.mask().artifact_id == old.artifact_id
    declarations = masked_source_declarations(case.repo, [case.capture])
    assert declarations[0]["artifact_ref"] == str(current.artifact_id)
    assert declarations[0]["content_sha256"] == current.content_sha256.hex()
