"""Ground an image sample in retained inputs before signing declarations about it.

Recovered scene geometry requires every contributor, its exact current pose receipt and the
frozen training split. A scene id alone does not establish which pixels produced geometry.
An unavailable camera is stated explicitly instead of invented from image dimensions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.ingest.person_receipts import masked_source_manifest
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import idempotency_key, input_digest_of, stage
from exulanica.ingest.stages.intake import key_for as intake_key_for
from exulanica.ingest.stages.masked_source import masked_source_key
from exulanica.world_package.package import PackageError


def validate_dataset_inputs(
    repository: IngestRepository,
    files: Mapping[str, bytes],
    materials: Sequence[Mapping[str, Any]],
) -> None:
    """Refuse declarations that disagree with live, workspace-scoped source receipts.

    Must run in the export transaction: the caller holds the database boundary through signing
    and recording the export. Training grants are checked by the separate training resolver.
    """
    try:
        for material in materials:
            _validate_material(repository, files, material)
        _validate_scenes(repository, files, materials)
    except PackageError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PackageError(f"training input declaration is malformed: {error}") from error


def _validate_material(
    repository: IngestRepository, files: Mapping[str, bytes], material: Mapping[str, Any]
) -> None:
    capture_id = uuid.UUID(material["capture_id"])
    capture = repository.capture(capture_id)
    live = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s and capture_id=%s "
        "and deleted_at is null and not tombstone_blocks_capture(workspace_id,capture_id)",
        (repository.workspace_id, capture_id),
    ).fetchone()
    if capture is None or live is None:
        raise PackageError("training input capture is missing or withdrawn")
    # The reconstruction gate checks expiry but permits future-dated screening and authority.
    # Export cannot turn tomorrow's receipt into permission today. Statement time is after the
    # caller acquired its source lock, unlike the transaction timestamp from before a wait.
    screening = repository.connection.execute(
        "select s.sensitive_regions,s.screening_method from reconstruction_privacy_screening s "
        "join capture_reconstruction_authorization a on a.workspace_id=s.workspace_id "
        "and a.authorization_id=s.authorization_id "
        "where s.workspace_id=%s and s.capture_id=%s and s.source_sha256=%s "
        "and s.receipt_digest=%s and s.screened_at<=statement_timestamp() "
        "and a.authorized_at<=statement_timestamp() "
        "and privacy_screening_allows_capture(s.workspace_id,s.capture_id,s.screening_id)",
        (
            repository.workspace_id,
            capture_id,
            capture.blob_id.digest,
            bytes.fromhex(material["screening"]["receipt_sha256"]),
        ),
    ).fetchone()
    if screening is None or material["screening"]["decision"] != "approved":
        raise PackageError("training input screening is not an eligible retained receipt")
    state = region_state_for_capture(repository, capture_id)
    for key, resolved in state.resolved.items():
        database = repository.connection.execute(
            "select person_region_is_masked(%s,%s,%s) as masked",
            (repository.workspace_id, state.subjects[key], key),
        ).fetchone()
        if database is None or database["masked"] != resolved.masked:
            raise PackageError("training mask policy disagrees with the current database decision")
    # An unknown region has a stable identifier, but it is never someone who can grant consent.
    subjects: dict[str, list[bytes]] = {}
    for key, subject in state.subjects.items():
        subjects.setdefault(str(subject) if subject else f"unknown:{key.hex()}", []).append(key)
    people = material["people"]
    if len(people) != len(subjects) or {p["subject_id"] for p in people} != set(subjects):
        raise PackageError("training input people disagree with the retained region inventory")
    for region in screening["sensitive_regions"]:
        if not isinstance(region, dict) or region.get("region_key") not in {
            key.hex() for key in state.outlines
        }:
            raise PackageError("training screening names a person absent from retained regions")
    scene = material["provenance"].get("scene_id")
    if not scene and (
        material["camera"] != {"status": "unavailable"}
        or material["calibration"] != {"status": "unavailable"}
    ):
        raise PackageError(
            "recovered cameras require a scene projection; unavailable must be explicit"
        )
    if material["metadata"].get("source_sha256") != capture.blob_id.hex:
        raise PackageError("training metadata does not bind the exact capture source")
    if not scene and material["rung"] != "4":
        raise PackageError("image-only training samples must declare photographic rung 4")
    masked = any(person["masked"] for person in people)
    if state.any_masked and not masked:
        raise PackageError("training input exposes a person the presentation policy masks")
    expected = capture.blob_id.digest
    receipt_digest = None
    if masked:
        intake = repository.find_artifact(intake_key_for(capture.blob_id))
        if intake is None or intake.content_sha256 is None:
            raise PackageError("training mask has no retained intake")
        key = masked_source_key(
            intake_sha256=intake.content_sha256,
            capture_id=capture_id,
            blob_id=capture.blob_id,
            regions=state.outlines,
            resolved=state.resolved,
        )
        artifact = repository.find_artifact(key)
        if artifact is None or artifact.content_sha256 is None:
            raise PackageError("training mask is missing or no longer current")
        expected = artifact.content_sha256
        spec = stage("masked_source")
        _, _, _, receipt_digest = masked_source_manifest(
            workspace_id=repository.workspace_id,
            capture_id=capture_id,
            source_sha256=capture.blob_id.hex,
            masked_sha256=expected.hex(),
            stage_version=spec.version,
            dilation_millionths=int(spec.params["dilation_millionths"]),
            masks=[
                (key, state.subjects[key], resolved.state)
                for key, resolved in state.resolved.items()
                if resolved.masked
            ],
        )
        manifest = repository.find_artifact(
            idempotency_key(
                capture.blob_id, stage("masked_source_manifest"), input_digest_of([expected])
            )
        )
        if manifest is None or manifest.content_sha256 != receipt_digest:
            raise PackageError("training mask has no exact retained manifest")
    for person in people:
        keys = subjects[person["subject_id"]]
        actual_masked = all(state.resolved[key].masked for key in keys)
        if person["masked"] != actual_masked:
            raise PackageError("training person masking declaration disagrees with retained masks")
        if actual_masked and person.get("mask_receipt_sha256") != receipt_digest.hex():
            raise PackageError("training mask receipt differs from the retained manifest")
    assets = [
        asset for asset in material["assets"] if asset["role"] in {"source_image", "masked_image"}
    ]
    if not scene and len(assets) != len(material["assets"]):
        raise PackageError("geometry requires an exact retained scene projection")
    if len(assets) != 1:
        raise PackageError("image-only training sample requires exactly one image asset")
    asset = assets[0]
    if asset["role"] != ("masked_image" if masked else "source_image"):
        raise PackageError("training input cannot include original pixels or unproven geometry")
    payload = files[asset["path"]]
    if hashlib.sha256(payload).digest() != expected or asset["sha256"] != expected.hex():
        raise PackageError("training image differs from the exact retained source or mask")


def decimal_projection(value: Any) -> Any:
    """Make camera declarations canonical without rounding away a recovered measurement."""
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, dict):
        return {key: decimal_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimal_projection(item) for item in value]
    return value


def _validate_scenes(
    repository: IngestRepository, files: Mapping[str, bytes], materials: Sequence[Mapping[str, Any]]
) -> None:
    groups = {}
    for material in materials:
        scene_id = material["provenance"].get("scene_id")
        if scene_id:
            groups.setdefault(scene_id, []).append(material)
    for scene_id, members in groups.items():
        provenance = members[0]["provenance"]
        job_id = uuid.UUID(provenance["job_id"])
        row = repository.connection.execute(
            "select j.pose_receipt_artifact_id,j.build_inputs,a.object_value->>'rung' as rung "
            "from reconstruction_scene s "
            "join reconstruction_scene_job j on j.workspace_id=s.workspace_id "
            "and j.job_id=s.current_job_id "
            "join assertion a on a.workspace_id=j.workspace_id "
            "and a.assertion_id=j.rung_assertion_id "
            "where s.workspace_id=%s and s.scene_id=%s "
            "and j.job_id=%s and not tombstone_blocks_scene(s.workspace_id,s.scene_id)",
            (repository.workspace_id, uuid.UUID(scene_id), job_id),
        ).fetchone()
        if row is None:
            raise PackageError("training scene is withdrawn or is not the current retained job")
        captures = repository.connection.execute(
            "select capture_id from reconstruction_scene_job_member "
            "where workspace_id=%s and job_id=%s",
            (repository.workspace_id, job_id),
        ).fetchall()
        if {str(item["capture_id"]) for item in captures} != {m["capture_id"] for m in members}:
            raise PackageError(
                "training scene must include every contributor for consent validation"
            )
        assets = [asset for material in members for asset in material["assets"]]
        pose_path = provenance["pose_path"]
        pose_assets = [asset for asset in assets if asset["path"] == pose_path]
        if len(pose_assets) != 1 or pose_assets[0]["role"] != "sparse_geometry":
            raise PackageError("training scene requires the exact sparse pose receipt")
        pose_asset = pose_assets[0]
        if uuid.UUID(pose_asset["artifact_id"]) != row["pose_receipt_artifact_id"]:
            raise PackageError("training cameras do not name the current pose artifact")
        pose = _artifact_json(repository, files, scene_id, pose_asset, "pose_receipt")
        if pose["profile"] != "exulanica.colmap-pose-receipt/v2":
            raise PackageError("training camera receipt profile is unsupported")
        frames = {frame["capture_ref"]: frame for frame in pose["manifest"]["frames"]}
        if set(frames) != {material["capture_id"] for material in members}:
            raise PackageError("training pose receipt contributor inventory disagrees")
        masked = {
            item["capture_ref"]: item["content_sha256"]
            for item in row["build_inputs"].get("masked_sources", [])
        }
        cameras = {camera["image_name"]: camera for camera in pose["quality"]["cameras"]}
        for material in members:
            if material["rung"] != row["rung"]:
                raise PackageError("training scene rung differs from the retained assertion")
            if any(
                material["provenance"].get(key) != provenance[key]
                for key in ("scene_id", "job_id", "pose_path")
            ):
                raise PackageError("training scene members disagree about their exact job")
            frame = frames[material["capture_id"]]
            image = next(
                asset
                for asset in material["assets"]
                if asset["role"] in {"source_image", "masked_image"}
            )
            expected_source = masked.get(
                material["capture_id"], material["metadata"]["source_sha256"]
            )
            if frame["sha256"] != image["sha256"] or expected_source != image["sha256"]:
                raise PackageError(
                    "training geometry read different pixels from the consented export"
                )
            training = row["build_inputs"].get("splat_training")
            if training:
                heldout = training["heldout_source_sha256"]
                expected_split = "held_out" if frame["sha256"] in heldout else "train"
                if material["split"] != expected_split:
                    raise PackageError("training split differs from the frozen scene build")
            camera = cameras.get(frame["filename"])
            if camera is None or camera["calibration"] is None:
                raise PackageError("training scene has no recovered calibrated camera for a member")
            expected_camera = {
                key: value
                for key, value in camera.items()
                if key not in {"calibration", "sparse_observations"}
            }
            if material["camera"] != decimal_projection(expected_camera) or material[
                "calibration"
            ] != decimal_projection(camera["calibration"]):
                raise PackageError(
                    "training camera or calibration differs from retained measurements"
                )
        # Sparse observations live inside the exact pose receipt. Other sparse files cannot
        # acquire its provenance merely by sharing a scene id.
        for asset in assets:
            if asset["role"] == "sparse_geometry" and asset["path"] != pose_path:
                raise PackageError("unbound sparse geometry is not a retained pose receipt")
            if asset["role"] == "trained_geometry":
                _validate_trained(repository, files, scene_id, pose_asset, asset, assets, members)
            if asset["role"] == "provenance_receipt" and not any(
                item["role"] == "trained_geometry" and item.get("receipt_path") == asset["path"]
                for item in assets
            ):
                raise PackageError("unreferenced scene receipt may expose unconsented contributors")


def _artifact_json(
    repository: IngestRepository,
    files: Mapping[str, bytes],
    scene_id: str,
    asset: Mapping[str, Any],
    kind: str,
) -> dict[str, Any]:
    _artifact_bytes(repository, files, scene_id, asset, kind)
    return json.loads(files[asset["path"]])


def _artifact_bytes(
    repository: IngestRepository,
    files: Mapping[str, bytes],
    scene_id: str,
    asset: Mapping[str, Any],
    kind: str,
) -> None:
    row = repository.connection.execute(
        "select content_sha256,byte_size from artifact where workspace_id=%s "
        "and artifact_id=%s and scene_id=%s and kind=%s and purged_at is null "
        "and not needs_repair and not person_withdrawal_blocks_artifact(workspace_id,artifact_id)",
        (repository.workspace_id, uuid.UUID(asset["artifact_id"]), uuid.UUID(scene_id), kind),
    ).fetchone()
    payload = files[asset["path"]]
    digest = hashlib.sha256(payload).digest()
    if (
        row is None
        or bytes(row["content_sha256"]) != digest
        or row["byte_size"] != len(payload)
        or asset["sha256"] != digest.hex()
    ):
        raise PackageError("training geometry bytes are not the exact retained artifact")


def _validate_trained(
    repository: IngestRepository,
    files: Mapping[str, bytes],
    scene_id: str,
    pose_asset: Mapping[str, Any],
    asset: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    members: Sequence[Mapping[str, Any]],
) -> None:
    _artifact_bytes(repository, files, scene_id, asset, "gaussian_splat_scene")
    receipt_path = asset["receipt_path"]
    receipts = [item for item in assets if item["path"] == receipt_path]
    if len(receipts) != 1 or receipts[0]["role"] != "provenance_receipt":
        raise PackageError("trained geometry requires its exact publication receipt")
    receipt = _artifact_json(repository, files, scene_id, receipts[0], "scene_splat_receipt")
    sources = {
        item["sha256"] for item in assets if item["role"] in {"source_image", "masked_image"}
    }
    heldout = {
        item["sha256"]
        for material in members
        if material["split"] == "held_out"
        for item in material["assets"]
        if item["role"] in {"source_image", "masked_image"}
    }
    if (
        receipt["profile"] != "exulanica.scene-splat-publication/v1"
        or set(receipt["manifest"]["source_sha256"]) != sources
        or set(receipt["manifest"]["parameters"]["heldout_source_sha256"]) != heldout
        or receipt["quality"]["accepted"] is not True
    ):
        raise PackageError(
            "trained publication disagrees with the exported sources or frozen split"
        )
    if (
        receipt["pose_receipt_sha256"] != pose_asset["sha256"]
        or receipt["delivery"]["artifact_id"] != asset["artifact_id"]
        or receipt["delivery"]["content_sha256"] != asset["sha256"]
    ):
        raise PackageError(
            "trained geometry publication does not bind the current pose and delivery"
        )
