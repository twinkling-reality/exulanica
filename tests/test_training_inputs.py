"""Database-grounded sample inputs; scripted reconstruction makes no GPU quality claim."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import uuid
from unittest.mock import patch

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.ingest.person_detectors import NoRegionDetector, StubRegionDetector
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world_package.package import PackageError
from exulanica.world_package.training_inputs import decimal_projection, validate_dataset_inputs
from PIL import Image

from conftest import write_photo
from test_person_masking_end_to_end import A_PERSON, _ingest
from test_scene_splat_pipeline import ScriptedTrainer, processor, queued
from test_world_package_dataset import sog_fixture, specimen


def _public_fixture_photo(*args, **kwargs):
    """Generate a metadata-free synthetic source BEFORE intake, never rewrite evidence."""
    path = write_photo(*args, **kwargs)
    with Image.open(path) as decoded:
        image = decoded.copy()
    image.info.clear()
    image.save(path, format="JPEG")
    return path


class _ExportableScriptedTrainer(ScriptedTrainer):
    """The scripted compressor emits a structurally valid synthetic SOG before publication."""

    def __call__(self, command, cwd):
        result = super().__call__(command, cwd)
        if command[0] != "exulanica-gsplat-scene-v1" and command[-1].endswith(".sog"):
            from pathlib import Path

            Path(command[-1]).write_bytes(sog_fixture())
        return result


def image_sample(repository, photo_dir, tmp_path, *, person=False):
    keep = {}
    with patch("test_person_masking_end_to_end.write_photo", _public_fixture_photo):
        capture_id, outcome = _ingest(
            repository,
            photo_dir,
            tmp_path,
            StubRegionDetector((A_PERSON,)) if person else NoRegionDetector(),
            keep,
        )
    assert outcome.error is None
    capture = repository.capture(capture_id)
    screening = repository.privacy_screening(keep["screening_id"])
    payload = (photo_dir / "a.jpg").read_bytes()
    material = {
        "material_id": str(capture_id),
        "capture_id": str(capture_id),
        "assets": [
            {
                "path": "assets/source.jpg",
                "role": "source_image",
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
        "people": [],
        "screening": {"decision": "approved", "receipt_sha256": screening.receipt_digest.hex()},
        "camera": {"status": "unavailable"},
        "calibration": {"status": "unavailable"},
        "metadata": {"source_sha256": capture.blob_id.hex},
        "provenance": {"notice": "SYNTHETIC TEST FIXTURE"},
        "split": "held_out",
        "rung": "4",
    }
    return {"assets/source.jpg": payload}, [material]


def scene_sample(repository, tmp_path):
    """A real database publication using explicitly scripted pose and trainer doubles."""
    with patch("test_scene_splat_pipeline.write_photo", _public_fixture_photo):
        store, captures, selected, config = queued(repository, tmp_path, frozen_split=True)
    claimed = repository.claim_reconstruction_scene(worker="training-export-test", lease_seconds=60)
    assert claimed is not None and claimed.job_id == selected.job_id
    result = processor(repository, store, tmp_path, _ExportableScriptedTrainer()).process(claimed)
    assert result.status == "succeeded", result.message
    rows = repository.connection.execute(
        "select artifact_id,kind,content_sha256 from artifact "
        "where workspace_id=%s and scene_id=%s",
        (repository.workspace_id, result.scene_id),
    ).fetchall()
    kinds = {row["kind"]: row for row in rows}
    files = {}
    extras = []
    for kind, path, role in (
        ("pose_receipt", "assets/pose.json", "sparse_geometry"),
        ("scene_splat_receipt", "assets/training.json", "provenance_receipt"),
        ("gaussian_splat_scene", "assets/trained.sog", "trained_geometry"),
    ):
        row = kinds[kind]
        payload = store.get(BlobId(bytes(row["content_sha256"])))
        files[path] = payload
        extras.append(
            {
                "path": path,
                "role": role,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "artifact_id": str(row["artifact_id"]),
            }
        )
    extras[-1]["receipt_path"] = "assets/training.json"
    pose = json.loads(files["assets/pose.json"])
    frames = {frame["capture_ref"]: frame for frame in pose["manifest"]["frames"]}
    cameras = {camera["image_name"]: camera for camera in pose["quality"]["cameras"]}
    materials = []
    for index, capture_id in enumerate(captures):
        capture = repository.capture(capture_id)
        screen = repository.latest_privacy_screening(capture_id)
        path = f"assets/source-{index}.jpg"
        payload = store.get(capture.blob_id)
        files[path] = payload
        camera = cameras[frames[str(capture_id)]["filename"]]
        materials.append(
            {
                "material_id": str(capture_id),
                "capture_id": str(capture_id),
                "assets": [{"path": path, "role": "source_image", "sha256": capture.blob_id.hex}],
                "people": [],
                "screening": {
                    "decision": "approved",
                    "receipt_sha256": screen.receipt_digest.hex(),
                },
                "camera": decimal_projection(
                    {
                        key: value
                        for key, value in camera.items()
                        if key not in {"calibration", "sparse_observations"}
                    }
                ),
                "calibration": decimal_projection(camera["calibration"]),
                "metadata": {"source_sha256": capture.blob_id.hex},
                "provenance": {
                    "scene_id": str(result.scene_id),
                    "job_id": str(selected.job_id),
                    "pose_path": "assets/pose.json",
                    "notice": "SCRIPTED SYNTHETIC FIXTURE",
                },
                "split": "held_out"
                if capture.blob_id.hex in config.heldout_source_sha256
                else "train",
                "rung": "3",
            }
        )
    materials[0]["assets"].extend(extras)
    return files, materials


def test_invented_screening_cannot_authorize_an_export(repository, photo_dir, tmp_path):
    files, materials = image_sample(repository, photo_dir, tmp_path)
    validate_dataset_inputs(repository, files, materials)
    materials[0]["screening"]["receipt_sha256"] = "f" * 64
    with pytest.raises(PackageError, match="eligible retained receipt"):
        validate_dataset_inputs(repository, files, materials)


@pytest.mark.parametrize("future_field", ["authorization", "screening"])
def test_future_screening_or_authorization_cannot_authorize_todays_export(
    repository, photo_dir, tmp_path, future_field
):
    from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption

    files, materials = image_sample(repository, photo_dir, tmp_path)
    now = dt.datetime.now(dt.UTC)
    future = now + dt.timedelta(days=1)
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=uuid.UUID(materials[0]["capture_id"]),
        actor=uuid.uuid4(),
        generator_manifest={"profile": "synthetic-future-authorization-test/v1"},
        authorization_scope={"purpose": "synthetic future receipt regression"},
        authorized_at=future if future_field == "authorization" else now,
    )
    screening = record_synthetic_exemption(
        repository,
        authorization_id=authorization.authorization_id,
        screened_at=future if future_field == "screening" else now,
    )
    materials[0]["screening"]["receipt_sha256"] = screening.receipt_digest.hex()
    with pytest.raises(PackageError, match="eligible retained receipt"):
        validate_dataset_inputs(repository, files, materials)


def test_omitting_a_detected_person_cannot_turn_a_source_into_training_material(
    repository, photo_dir, tmp_path
):
    files, materials = image_sample(repository, photo_dir, tmp_path, person=True)
    with pytest.raises(PackageError, match="retained region inventory"):
        validate_dataset_inputs(repository, files, materials)


def test_invented_subject_cannot_stand_in_for_the_retained_inventory(
    repository, photo_dir, tmp_path
):
    files, materials = image_sample(repository, photo_dir, tmp_path)
    materials[0]["people"] = [{"subject_id": str(uuid.uuid4()), "masked": False}]
    with pytest.raises(PackageError, match="retained region inventory"):
        validate_dataset_inputs(repository, files, materials)


def test_retained_scene_exports_exact_cameras_and_refuses_invented_calibration(
    repository, tmp_path
):
    files, materials = scene_sample(repository, tmp_path)
    validate_dataset_inputs(repository, files, materials)
    from exulanica.world_package.dataset import write_dataset_package
    from exulanica.world_package.package import verify_package

    sample = specimen()
    sample.update(files=files, materials=materials, receipts=sample["receipts"][:1])
    output = tmp_path / "sample-export"
    write_dataset_package(output, **sample)
    verify_package(output)
    changed = copy.deepcopy(materials)
    changed[0]["calibration"]["parameters"][0] = "99999"
    with pytest.raises(PackageError, match="differs from retained measurements"):
        validate_dataset_inputs(repository, files, changed)
    with pytest.raises(PackageError, match="every contributor"):
        validate_dataset_inputs(repository, files, materials[:-1])
    changed = copy.deepcopy(materials)
    changed[0]["split"] = "train"
    with pytest.raises(PackageError, match="frozen scene build"):
        validate_dataset_inputs(repository, files, changed)


def test_unknown_person_exports_only_the_current_receipt_bound_mask(
    repository, photo_dir, tmp_path
):
    files, materials = image_sample(repository, photo_dir, tmp_path, person=True)
    material = materials[0]
    capture_id = uuid.UUID(material["capture_id"])
    region = repository.current_person_regions(capture_ids=[capture_id])[capture_id][0]
    mask = repository.current_capture_artifacts(capture_ids=[capture_id], kind="masked_source")[
        capture_id
    ]
    receipt = repository.current_capture_artifacts(
        capture_ids=[capture_id], kind="masked_source_manifest"
    )[capture_id]
    material["people"] = [
        {
            "subject_id": f"unknown:{region.region_key.hex()}",
            "masked": True,
            "mask_receipt_sha256": receipt.content_sha256.hex(),
        }
    ]
    material["assets"][0].update(role="masked_image", sha256=mask.content_sha256.hex())
    original = files["assets/source.jpg"]
    files["assets/source.jpg"] = LocalContentAddressedStore(tmp_path / "blobs").get(
        BlobId(mask.content_sha256)
    )
    validate_dataset_inputs(repository, files, materials)
    files["assets/source.jpg"] = original
    with pytest.raises(PackageError, match="exact retained source or mask"):
        validate_dataset_inputs(repository, files, materials)
