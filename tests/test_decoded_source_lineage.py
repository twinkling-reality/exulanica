"""Synthetic HEIC lineage through real SQL, local model doubles and staged pose inputs."""

import copy
import dataclasses
import datetime as dt
import hashlib
import json
import math
import uuid

import psycopg
import pytest
from exulanica.corpus import decode
from exulanica.epistemics.source_images import decoded_receipt_for, normalized_image
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.decode import open_upright
from exulanica.ingest.personal_admission import HUMAN_ATTESTATION
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scene_selection import enqueue_exact_scene_reconstruction
from exulanica.ingest.source_inputs import decoded_source_declarations, verify_decoded_sources
from exulanica.ingest.stages import STAGES
from exulanica.ingest.stages import decoded_source as decoded_stage
from exulanica.reconstruction.depth import DepthPrediction
from exulanica.reconstruction.source_lineage import (
    decoded_receipt,
    verify_decoded_training_files,
)
from PIL import Image

from test_intake_upload import upload as upload
from test_personal_admission_route import post
from test_personal_heic import FIXTURE
from test_scene_reconstruction_pipeline import FakeColmap, _processor
from test_segmentation_stage import ScriptedSegmenter


def rotated_heic(turns):
    data = bytearray(FIXTURE.read_bytes())
    position = data.index(b"irot")
    assert data[position - 4 : position] == b"\0\0\0\x09"
    data[position + 4] = turns
    return bytes(data)


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_real_heif_container_orientation_is_applied_once(turns):
    with decode.open_sensor(FIXTURE.read_bytes()) as base:
        expected = base.rotate(90 * turns, expand=True)
    upright, facts = open_upright(rotated_heic(turns))
    assert upright.size == expected.size
    assert upright.tobytes() == expected.tobytes()
    assert facts.display_width == expected.width and facts.display_height == expected.height
    assert upright.getexif().get(274, 1) == 1


def test_actual_heic_is_bounded_before_pixel_load(monkeypatch):
    monkeypatch.setattr(decode, "MAX_PIXELS", 64 * 48 - 1)
    from pi_heif.as_plugin import HeifImageFile

    monkeypatch.setattr(HeifImageFile, "load", lambda _: pytest.fail("pixels decoded over budget"))
    with pytest.raises(Image.DecompressionBombError, match="pipeline's limit"):
        decode.open_sensor(FIXTURE.read_bytes())


def test_heic_frame_count_is_checked_before_pixel_load(monkeypatch):
    from pi_heif.as_plugin import HeifImageFile

    # Real container/open path, injected count only: this fixture contains one actual frame.
    monkeypatch.setattr(HeifImageFile, "n_frames", property(lambda _: 2))
    monkeypatch.setattr(HeifImageFile, "load", lambda _: pytest.fail("multiple frames decoded"))
    with pytest.raises(ValueError, match="2 frames"):
        decode.open_sensor(FIXTURE.read_bytes())


def admit(upload, count=1, *, mask=False):
    sources = [rotated_heic(i) for i in range(count)]
    response = upload.post([("files", (f"{i}.heic", data)) for i, data in enumerate(sources)])
    assert response.status_code == 202 and not response.json()["refused"], response.text
    now = dt.datetime.now(dt.UTC)
    body = {
        "operation": "detect",
        "purpose": "Synthetic HEIC lineage test",
        "authority": {
            "account_authority_basis": "Synthetic repository fixture authored for this test",
            "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
        },
        "recorded_at": now.isoformat(),
        "members": [
            {"capture_id": item["capture_id"], "sha256": item["blob_sha256"], "bytes": len(data)}
            for item, data in zip(response.json()["accepted"], sources, strict=True)
        ],
    }
    detected = post(upload, "/personal-admission", body)
    assert detected.status_code == 202, detected.text
    body.update(
        operation="review",
        reviewed_by_name="Synthetic fixture reviewer",
        attestation=HUMAN_ATTESTATION,
        recorded_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    for member in body["members"]:
        member["review"] = "confirmed-regions" if mask else "no-person"
        if mask:
            member["edits"] = [
                {
                    "action": "add",
                    "region_key": "a" * 64,
                    "silhouette": {
                        "kind": "polygon",
                        "points": [[0, 0], [500000, 0], [500000, 500000], [0, 500000]],
                    },
                }
            ]
    reviewed = post(upload, "/personal-admission", body)
    assert reviewed.status_code == 202, reviewed.text
    if mask:
        assert all(r["eligibility_state"] == "blocked" for r in reviewed.json()["receipts"])
        pipeline = PhotoIngestPipeline(upload.repository, upload.store)
        for receipt in detected.json()["receipts"]:
            result = pipeline.ingest_derivatives(
                uuid.UUID(receipt["capture_id"]),
                privacy_screening_id=uuid.UUID(receipt["screening_id"]),
            )
            assert result.error is None, result.error
        body["operation"] = "review"
        body["recorded_at"] = dt.datetime.now(dt.UTC).isoformat()
        for member in body["members"]:
            member["edits"] = []
        reviewed = post(upload, "/personal-admission", body)
        assert reviewed.status_code == 202, reviewed.text
    assert all(r["eligibility_state"] == "eligible" for r in reviewed.json()["receipts"])
    return sources, reviewed.json()["receipts"]


class PlaneDepth:
    model_id = "synthetic-heic-plane/v1"

    def __init__(self):
        self.images = []

    def predict(self, image):
        self.images.append(image.copy())
        width, height = image.size
        focal = height / (2 * math.tan(math.radians(60) / 2))
        points = []
        for y in range(height):
            for x in range(width):
                points.extend(
                    ((x + 0.5 - width / 2) / focal * 3, -(y + 0.5 - height / 2) / focal * 3, -3)
                )
        return DepthPrediction(
            width, height, points, bytes([1]) * (width * height), 60, False, self.model_id
        )


@pytest.mark.parametrize("masked", [False, True])
def test_depth_segmentation_and_pose_share_exact_persisted_pixels(upload, tmp_path, masked):
    sources, receipts = admit(upload, 3, mask=masked)
    depth, segmenter = PlaneDepth(), ScriptedSegmenter()
    pipeline = PhotoIngestPipeline(
        upload.repository, upload.store, depth=depth, segmenter=segmenter
    )
    captures = [uuid.UUID(r["capture_id"]) for r in receipts]
    for receipt in receipts:
        result = pipeline.ingest_derivatives(
            uuid.UUID(receipt["capture_id"]),
            privacy_screening_id=uuid.UUID(receipt["screening_id"]),
        )
        assert result.error is None, result.error
    selected = enqueue_exact_scene_reconstruction(
        upload.repository,
        captures,
        actor=uuid.UUID(int=1),
        purpose="Synthetic source alignment",
        authorized_at=dt.datetime.now(dt.UTC),
    )
    assert selected is not None
    claim = upload.repository.claim_reconstruction_scene(worker="HEIC-test", lease_seconds=60)
    processor = _processor(
        upload.repository, upload.store, tmp_path, FakeColmap(registered=3, camera_spacing=10)
    )
    manifest, staged = processor._manifest(claim)
    for i, (frame, scratch, original) in enumerate(
        zip(manifest.frames, staged, sources, strict=True)
    ):
        assert frame.sha256 == scratch.blob_id.hex
        assert frame.sha256 != hashlib.sha256(original).hexdigest()
        data = upload.store.get(scratch.blob_id)
        with decode.open_sensor(data) as pixels:
            assert pixels.format == ("JPEG" if masked else "PNG")
            assert pixels.tobytes() == depth.images[i].tobytes()
            assert pixels.tobytes() == segmenter.images[i].tobytes()
        [point] = upload.rows(
            "select read_source_sha256 from artifact "
            "where kind='point_map' and source_blob_sha256=%s",
            hashlib.sha256(original).digest(),
        )
        assert bytes(point["read_source_sha256"]).hex() == frame.sha256
    forged = copy.deepcopy(claim.build_inputs)
    forged["decoded_sources"][0]["receipt"]["record"]["pixel_grid"]["width"] += 1
    with pytest.raises(PrivacyAdmissionError, match="stale or forged"):
        verify_decoded_sources(upload.repository, dataclasses.replace(claim, build_inputs=forged))
    result = processor.process(claim)
    assert result.status == "succeeded", result
    from exulanica.graph.world_read import world_read_bundle
    from exulanica.graph.world_read_verification import verify_downloads

    envelope = world_read_bundle(
        upload.repository.connection, upload.repository.workspace_id, claim.scene_id, upload.store
    )
    assert envelope is not None
    points = envelope["bundle"]["recipient_evidence"]["record"]["point_maps"]
    assert len(points) == 3
    for point in points:
        assert point["lineage"]["mode"] == ("masked" if masked else "decoded")
        assert (
            point["lineage"]["decoded_source"]["record"]["source_sha256"]
            == point["lineage"]["source_sha256"]
        )
    downloads = {}
    for view in envelope["bundle"]["views"]:
        descriptor = view["photo_bytes"]
        assert descriptor["state"] == "available", descriptor
        response = upload.get(descriptor["fetch"])
        assert response.status_code == 200, response.text
        downloads[view["capture_id"]] = response.content
    verified = verify_downloads(
        envelope,
        downloads,
        at=dt.datetime.now(dt.UTC).isoformat(),
        expected_bundle_sha256=envelope["bundle_sha256"],
    )
    assert all(p["state"] == "available" for p in verified["point_lineage"].values())
    from exulanica.ingest.source_inputs import training_decoded_lineage
    from exulanica.reconstruction.gsplat_runner import read_manifest
    from exulanica.reconstruction.splat import verify_masked_training_sources

    from test_scene_splat_pipeline import request

    originals = tuple(hashlib.sha256(data).hexdigest() for data in sources)
    training = request(originals[:1])
    if masked:
        training = training.bind_masked_sources(
            [
                {
                    "capture_ref": f.capture_ref,
                    "source_sha256": original,
                    "masked_source_sha256": f.sha256,
                }
                for f, original in zip(manifest.frames, originals, strict=True)
            ],
            sources=originals,
        )
    training = training.bind_decoded_sources(
        training_decoded_lineage(claim.build_inputs["decoded_sources"]), sources=originals
    )
    frozen = training.manifest(manifest)
    assert frozen.heldout_original_source_sha256 == originals[:1]
    assert frozen.heldout_source_sha256 == (manifest.frames[0].sha256,)
    assert bool(frozen.masked_source_remap) is masked
    manifest_path = tmp_path / "training.json"
    manifest_path.write_text(json.dumps(frozen.as_payload()))
    assert read_manifest(manifest_path) == frozen
    images = tmp_path / "dataset/images"
    images.mkdir(parents=True)
    for item in staged:
        (images / item.filename).write_bytes(upload.store.get(item.blob_id))
    verify_masked_training_sources(frozen, images.parent)
    # A caller cannot relabel point-map input bytes as the original or as an unmasked PNG.
    forbidden = (
        bytes.fromhex(claim.build_inputs["decoded_sources"][0]["content_sha256"])
        if masked
        else hashlib.sha256(sources[0]).digest()
    )
    with pytest.raises(psycopg.errors.CheckViolation), upload.repository.connection.transaction():
        upload.repository.connection.execute(
            "update artifact set read_source_sha256=%s "
            "where kind='point_map' and source_blob_sha256=%s",
            (forbidden, hashlib.sha256(sources[0]).digest()),
        )
    from exulanica.ingest.scene_segments import publish_scene_segments

    [mask_row] = upload.rows(
        "select artifact_id,content_sha256 from artifact "
        "where kind='object_mask_list' and source_blob_sha256=%s",
        hashlib.sha256(sources[0]).digest(),
    )
    payload = json.loads(upload.store.get(BlobId(bytes(mask_row["content_sha256"]))))
    payload["source"]["display"]["w"] += 1
    from exulanica.canonical import canonical_json

    altered = upload.store.put_bytes(canonical_json(payload))
    upload.repository.connection.execute(
        "update artifact set content_sha256=%s,storage_key=%s,byte_size=%s where artifact_id=%s",
        (
            altered.blob_id.digest,
            upload.store.key_for(altered.blob_id),
            len(canonical_json(payload)),
            mask_row["artifact_id"],
        ),
    )
    refused = publish_scene_segments(upload.repository, upload.store, claim.scene_id)
    assert refused["action"] == "skipped" and "pixel grid" in refused["reason"], refused


def test_decoder_inventory_change_invalidates_normalized_and_mask_even_same_png(
    upload, monkeypatch
):
    sources, receipts = admit(upload, mask=True)
    original = hashlib.sha256(sources[0]).digest()
    connection, workspace = upload.repository.connection, upload.repository.workspace_id
    first = PhotoIngestPipeline(upload.repository, upload.store, depth=PlaneDepth())
    result = first.ingest_derivatives(
        uuid.UUID(receipts[0]["capture_id"]),
        privacy_screening_id=uuid.UUID(receipts[0]["screening_id"]),
    )
    assert result.error is None, result.error
    old_renditions = upload.rows("select artifact_id from artifact where stage_key='rendition'")
    old = normalized_image(connection, workspace, original)
    [mask] = upload.rows("select artifact_id from artifact where kind='masked_source'")
    [capture] = upload.rows("select capture_id from capture")
    spec = STAGES["decoded_source"]
    inventory = {**spec.params["decoder_inventory"], "libheif": "synthetic-changed-decoder"}
    monkeypatch.setitem(
        STAGES,
        "decoded_source",
        dataclasses.replace(spec, params={**spec.params, "decoder_inventory": inventory}),
    )
    monkeypatch.setattr(decoded_stage, "decoder_inventory", lambda: inventory)
    pipeline = PhotoIngestPipeline(upload.repository, upload.store)
    assert normalized_image(connection, workspace, original) is None
    assert (
        upload.rows(
            "select privacy_mask_matches(%s,%s,%s,privacy_inputs_at(%s,%s,now())) ok",
            workspace,
            capture["capture_id"],
            mask["artifact_id"],
            workspace,
            capture["capture_id"],
        )[0]["ok"]
        is False
    )
    result = pipeline.ingest_intake(sources[0], filename="same.heic")
    assert result.error is None, result.error
    new = normalized_image(connection, workspace, original)
    assert old.sha256 == new.sha256
    assert old.decoded["record_sha256"] != new.decoded["record_sha256"]
    assert (
        upload.rows(
            "select privacy_mask_matches(%s,%s,%s,privacy_inputs_at(%s,%s,now())) ok",
            workspace,
            capture["capture_id"],
            mask["artifact_id"],
            workspace,
            capture["capture_id"],
        )[0]["ok"]
        is False
    )
    with pytest.raises(ValueError, match="ambiguous"):
        decoded_receipt_for(connection, workspace, original, new.sha256)
    [point] = upload.rows("select artifact_id from artifact where kind='point_map'")
    assert (
        upload.rows("select asset_point_allows(%s,%s,now()) ok", workspace, point["artifact_id"])[
            0
        ]["ok"]
        is False
    )
    refreshed = pipeline.ingest_derivatives(capture["capture_id"])
    assert "rendition" in refreshed.stages_run
    assert (
        len(upload.rows("select artifact_id from artifact where stage_key='rendition'"))
        == len(old_renditions) + 1
    )


def test_receipt_is_immutable_and_offline_training_rejects_wrong_grid_and_original(
    upload, tmp_path
):
    sources, receipts = admit(upload)
    capture = uuid.UUID(receipts[0]["capture_id"])
    [declaration] = decoded_source_declarations(upload.repository, [capture])
    record = declaration["receipt"]["record"]
    path = tmp_path / "view.png"
    path.write_bytes(upload.store.get(BlobId.from_hex(declaration["content_sha256"])))
    lineage = ({"capture_ref": str(capture), "receipt": declaration["receipt"]},)
    verify_decoded_training_files(lineage, (), [path])
    altered = copy.deepcopy(record)
    altered["pixel_grid"]["width"] += 1
    with pytest.raises(ValueError, match="pixel grid"):
        verify_decoded_training_files(
            ({"capture_ref": str(capture), "receipt": decoded_receipt(altered)},), (), [path]
        )
    original = tmp_path / "original.heic"
    original.write_bytes(sources[0])
    with pytest.raises(ValueError, match="selected derivative"):
        verify_decoded_training_files(lineage, (), [path, original])
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="immutable"),
        upload.repository.connection.transaction(),
    ):
        upload.repository.connection.execute(
            "update decoded_source set receipt_record=receipt_record"
        )


def test_deleted_heic_cannot_be_selected_or_reprocessed(upload):
    _sources, receipts = admit(upload)
    capture = uuid.UUID(receipts[0]["capture_id"])
    upload.repository.connection.execute(
        "update capture set deleted_at=now() where capture_id=%s", (capture,)
    )
    [span] = upload.rows("select span_id from evidence_span where region is null")
    assert upload.get(f"/evidence/{span['span_id']}/masked").status_code == 409
    with pytest.raises(PrivacyAdmissionError, match="absent or deleted"):
        decoded_source_declarations(upload.repository, [capture])
    pipeline = PhotoIngestPipeline(upload.repository, upload.store)
    result = pipeline.ingest_derivatives(capture)
    assert result.tombstoned


def test_legacy_masked_depth_and_segmentation_versions_require_rebuild(upload, monkeypatch):
    """Exercise cache versions with local doubles; no claim to replay a historical model."""
    _sources, receipts = admit(upload, mask=True)
    capture = uuid.UUID(receipts[0]["capture_id"])
    screening = uuid.UUID(receipts[0]["screening_id"])
    depth, segmenter = PlaneDepth(), ScriptedSegmenter()
    with monkeypatch.context() as legacy:
        for key in ("depth", "segmentation"):
            legacy.setitem(STAGES, key, dataclasses.replace(STAGES[key], version=1))
        pipeline = PhotoIngestPipeline(
            upload.repository, upload.store, depth=depth, segmenter=segmenter
        )
        result = pipeline.ingest_derivatives(capture, privacy_screening_id=screening)
        assert result.error is None, result.error
    from exulanica.graph.reconstruction_scenes import _SEGMENT_OBJECT_MASKS
    from exulanica.ingest.scene_segments import _OBJECT_MASKS

    connection, workspace = upload.repository.connection, upload.repository.workspace_id
    [old] = upload.rows("select artifact_id from artifact where kind='point_map'")
    assert (
        upload.rows("select asset_point_allows(%s,%s,now()) ok", workspace, old["artifact_id"])[0][
            "ok"
        ]
        is False
    )
    for query in (_OBJECT_MASKS, _SEGMENT_OBJECT_MASKS):
        assert (
            connection.execute(query, (workspace, [capture], "object_mask_list")).fetchall() == []
        )
    pipeline = PhotoIngestPipeline(
        upload.repository, upload.store, depth=depth, segmenter=segmenter
    )
    result = pipeline.ingest_derivatives(capture, privacy_screening_id=screening)
    assert result.error is None, result.error
    assert {"depth", "segmentation"} <= set(result.stages_run)
    assert len(depth.images) == 2 and len(segmenter.images) == 2
    for query in (_OBJECT_MASKS, _SEGMENT_OBJECT_MASKS):
        assert (
            len(connection.execute(query, (workspace, [capture], "object_mask_list")).fetchall())
            == 1
        )
