"""Reconstruction reads the masked photograph, and refuses when it cannot prove it did.

"Mask before, not only after" is the design note's second principle and the one with the most ways
to be quietly false. Masking a source is a claim about what the trainer saw; if the worker silently
fell back to the original when a derivative was missing, every receipt would still say the person
was hidden and the person would be in the geometry. So the failure path is tested as carefully as
the success path, and the fallback that would be convenient here does not exist.

The other thing pinned is subtler and cost a real bug elsewhere in this file's history: a member's
blob id is used both by the reconstruction path and by the deletion path, and only the first may be
rebound. A purge looking for the masked derivative would leave the original on disk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.masked_inputs import (
    apply_masked_sources,
    masked_source_declarations,
    verify_masked_sources,
)
from exulanica.ingest.spine.artifacts import CaptureArtifactRow
from exulanica.ingest.spine.reconstruction_jobs import ClaimedSceneJob, SceneJobMember

CAPTURE_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
CAPTURE_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
ARTIFACT_A = uuid.UUID("aaaaaaaa-1111-1111-1111-111111111111")
ORIGINAL_A = BlobId(bytes([1]) * 32)
MASKED_A = BlobId(bytes([9]) * 32)
ORIGINAL_B = BlobId(bytes([2]) * 32)


@dataclass
class FakeRepository:
    """Only the two lookups this module uses. A real repository needs PostgreSQL."""

    connection = None
    workspace_id = uuid.UUID(int=1)

    current: dict[uuid.UUID, CaptureArtifactRow]
    exact: dict[uuid.UUID, CaptureArtifactRow]

    def current_capture_artifacts(self, *, capture_ids, kind):
        assert kind == "masked_source"
        return {c: r for c, r in self.current.items() if c in capture_ids}

    def exact_capture_artifacts(self, *, artifact_ids_by_capture, kind):
        assert kind == "masked_source"
        return {c: r for c, r in self.exact.items() if c in artifact_ids_by_capture}


@pytest.fixture(autouse=True)
def currency_policy_double(monkeypatch):
    """These shape tests use a repository double; SQL currency has real-database tests."""
    monkeypatch.setattr("exulanica.ingest.masked_inputs.WorkspaceScope", lambda *args: None)
    monkeypatch.setattr("exulanica.ingest.masked_inputs.mask_is_current", lambda *args: True)
    monkeypatch.setattr("exulanica.ingest.masked_inputs.current_inputs", lambda *args: {})


def _row(capture_id, artifact_id, digest):
    return CaptureArtifactRow(
        capture_id=capture_id,
        artifact_id=artifact_id,
        content_sha256=digest.digest,
        storage_key="sha-256/09/09/" + digest.hex,
        byte_size=1024,
        privacy_screening_id=None,
    )


def _job(build_inputs, members=None):
    return ClaimedSceneJob(
        job_id=uuid.uuid4(),
        scene_id=uuid.uuid4(),
        member_digest=b"\x00" * 32,
        selection_policy={},
        selection_policy_digest=b"\x00" * 32,
        build_inputs=build_inputs,
        build_input_digest=b"\x00" * 32,
        privacy_admission_id=uuid.uuid4(),
        privacy_admission_digest=b"\x00" * 32,
        members=members
        or (
            SceneJobMember(CAPTURE_A, 0, ORIGINAL_A, "image/jpeg"),
            SceneJobMember(CAPTURE_B, 1, ORIGINAL_B, "image/jpeg"),
        ),
        attempts=1,
        claim_token=uuid.uuid4(),
        scratch_key=None,
        reclaimed=False,
    )


def _declared():
    return {
        "masked_sources": [
            {
                "capture_ref": str(CAPTURE_A),
                "artifact_ref": str(ARTIFACT_A),
                "content_sha256": MASKED_A.hex,
                "media_type": "image/png",
                "stage_version": 1,
                "stage_params_sha256": "00" * 32,
            }
        ]
    }


def test_a_scene_with_nobody_hidden_declares_no_masked_sources():
    """So a corpus with no people in it produces the build input digest it always did."""
    repository = FakeRepository(current={}, exact={})
    assert masked_source_declarations(repository, [CAPTURE_A, CAPTURE_B]) == []


def test_a_hidden_person_puts_the_derivative_digest_in_the_build_inputs():
    repository = FakeRepository(
        current={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, MASKED_A)}, exact={}
    )
    declared = masked_source_declarations(repository, [CAPTURE_A, CAPTURE_B])
    assert len(declared) == 1
    assert declared[0]["capture_ref"] == str(CAPTURE_A)
    assert declared[0]["content_sha256"] == MASKED_A.hex


def test_the_declaration_carries_a_media_type():
    """The staged filename's extension comes from it; a mislabelled file reaches COLMAP."""
    repository = FakeRepository(
        current={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, MASKED_A)}, exact={}
    )
    assert masked_source_declarations(repository, [CAPTURE_A])[0]["media_type"]


def test_reconstruction_reads_the_masked_derivative_not_the_original():
    repository = FakeRepository(
        current={}, exact={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, MASKED_A)}
    )
    rebound = apply_masked_sources(repository, _job(_declared()))
    by_capture = {member.capture_id: member for member in rebound.members}
    assert by_capture[CAPTURE_A].blob_id == MASKED_A
    assert by_capture[CAPTURE_A].media_type == "image/png"


def test_a_member_with_nobody_hidden_still_reads_its_original():
    repository = FakeRepository(
        current={}, exact={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, MASKED_A)}
    )
    rebound = apply_masked_sources(repository, _job(_declared()))
    by_capture = {member.capture_id: member for member in rebound.members}
    assert by_capture[CAPTURE_B].blob_id == ORIGINAL_B


def test_the_original_job_is_left_intact_for_the_deletion_boundary():
    """A purge that looked for the derivative would leave the original on disk."""
    repository = FakeRepository(
        current={}, exact={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, MASKED_A)}
    )
    job = _job(_declared())
    apply_masked_sources(repository, job)
    assert {member.blob_id for member in job.members} == {ORIGINAL_A, ORIGINAL_B}


def test_a_missing_derivative_stops_the_job_rather_than_falling_back():
    """The fallback that would be convenient here is how a hidden person gets reconstructed."""
    repository = FakeRepository(current={}, exact={})
    with pytest.raises(PrivacyAdmissionError, match="refusing rather than reconstructing"):
        apply_masked_sources(repository, _job(_declared()))


def test_a_derivative_whose_bytes_changed_since_admission_is_refused():
    """The current derivative may reflect a consent decision made after this job was queued."""
    other = BlobId(bytes([7]) * 32)
    repository = FakeRepository(current={}, exact={CAPTURE_A: _row(CAPTURE_A, ARTIFACT_A, other)})
    with pytest.raises(PrivacyAdmissionError, match="not the bytes this job"):
        apply_masked_sources(repository, _job(_declared()))


def test_a_mask_naming_a_capture_outside_the_scene_is_refused():
    repository = FakeRepository(current={}, exact={})
    stranger = _declared()
    stranger["masked_sources"][0]["capture_ref"] = str(uuid.uuid4())
    with pytest.raises(PrivacyAdmissionError, match="outside this scene"):
        verify_masked_sources(repository, _job(stranger))


def test_an_incomplete_declaration_is_refused():
    repository = FakeRepository(current={}, exact={})
    broken = {"masked_sources": [{"capture_ref": str(CAPTURE_A)}]}
    with pytest.raises(PrivacyAdmissionError, match="incomplete"):
        verify_masked_sources(repository, _job(broken))


def test_a_declaration_that_is_not_a_list_is_refused():
    repository = FakeRepository(current={}, exact={})
    with pytest.raises(PrivacyAdmissionError, match="not a list"):
        verify_masked_sources(repository, _job({"masked_sources": {"a": 1}}))


def test_a_job_with_no_declaration_is_returned_unchanged():
    repository = FakeRepository(current={}, exact={})
    job = _job({"profile": "exulanica.reconstruction-scene-build-input/v1"})
    assert apply_masked_sources(repository, job) is job
