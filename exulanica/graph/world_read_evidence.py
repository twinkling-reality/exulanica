"""Clock-free owning-workspace evidence from persisted records, never current masks."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.store import ContentAddressedStore

PROFILE = "exulanica.world-read-recipient-evidence/v1"


def unavailable(reason: str) -> dict[str, Any]:
    return {"state": "unavailable", "reason": reason}


def _hex(value: bytes | None) -> str | None:
    return None if value is None else bytes(value).hex()


def _receipt(store: ContentAddressedStore | None, digest: bytes | None) -> dict[str, Any]:
    if store is None or digest is None:
        return unavailable("receipt_bytes_missing")
    try:
        payload = store.get(BlobId(bytes(digest)))
        # Preserve exact persisted bytes, including noncanonical numeric encodings, without
        # introducing floats into the outer record or changing the receipt's original digest.
        json.loads(payload)
        return {"state": "available", "sha256": _hex(digest), "json_utf8": payload.decode()}
    except (BlobNotFoundError, IntegrityError, ValueError, UnicodeError):
        return unavailable("receipt_bytes_missing_or_corrupt")


def recorded_evidence(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    capture_ids: list[uuid.UUID],
    store: ContentAddressedStore | None,
) -> dict[str, Any]:
    captures = []
    for capture_id in sorted(capture_ids, key=str):
        source = connection.execute(
            "select blob_sha256 from capture where workspace_id=%s and capture_id=%s",
            (workspace, capture_id),
        ).fetchone()
        regions = connection.execute(
            "select encode(region_key,'hex') as region_key,subject_id,"
            "encode(region_digest,'hex') as region_sha256,action,silhouette "
            "from person_region_current where workspace_id=%s and capture_id=%s "
            "and action<>'deleted' order by region_key",
            (workspace, capture_id),
        ).fetchall()
        people = []
        for region in regions:
            receipts = []
            if region["subject_id"] is not None:
                rows = connection.execute(
                    "select consent_record,consent_canonical,consent_digest,subject_id,region_key,"
                    "consent_scope,decision,sequence,actor_id,actor_role,effective_at,valid_until "
                    "from person_presentation_consent where workspace_id=%s and subject_id=%s "
                    "and (region_key is null or region_key=decode(%s,'hex') "
                    "or decision='withdrawn') order by consent_digest",
                    (workspace, region["subject_id"], region["region_key"]),
                ).fetchall()
                for row in rows:
                    raw = bytes(row["consent_canonical"])
                    if hashlib.sha256(raw).digest() != bytes(row["consent_digest"]):
                        receipts.append(unavailable("consent_receipt_corrupt"))
                    elif not _consent_columns_match(row):
                        receipts.append(unavailable("consent_columns_disagree_with_receipt"))
                    else:
                        receipts.append(
                            {
                                "state": "available",
                                "sha256": _hex(row["consent_digest"]),
                                "record": row["consent_record"],
                            }
                        )
            people.append(
                {
                    **region,
                    "subject_id": str(region["subject_id"]) if region["subject_id"] else None,
                    "receipts": receipts,
                }
            )
        captures.append(
            {
                "capture_id": str(capture_id),
                "source_sha256": _hex(source["blob_sha256"]) if source else None,
                "photo_bytes": unavailable("posed_photo_bytes_not_served"),
                "regions": people,
            }
        )
    job = connection.execute(
        "select j.job_id,j.build_inputs,j.pose_receipt_artifact_id from reconstruction_scene s "
        "join reconstruction_scene_job j on j.workspace_id=s.workspace_id "
        "and j.job_id=s.current_job_id where s.workspace_id=%s and s.scene_id=%s",
        (workspace, scene_id),
    ).fetchone()
    points = []
    if job:
        for point in job["build_inputs"].get("point_maps", []):
            row = connection.execute(
                "select content_sha256,source_blob_sha256,read_source_sha256,privacy_screening_id "
                "from artifact "
                "where workspace_id=%s and artifact_id=%s and kind='point_map'",
                (workspace, point["artifact_ref"]),
            ).fetchone()
            item = {
                "kind": "point_map",
                "artifact_id": point["artifact_ref"],
                "capture_id": point["capture_ref"],
                "content_sha256": point["content_sha256"],
            }
            if row is None:
                item["lineage"] = unavailable("point_artifact_missing")
            elif _hex(row["content_sha256"]) != point["content_sha256"]:
                item["lineage"] = unavailable("output_to_build_mismatch")
            else:
                original = _hex(row["source_blob_sha256"])
                read = _hex(row["read_source_sha256"]) or original
                lineage = {
                    "state": "available",
                    "source_sha256": original,
                    "read_sha256": read,
                    "mode": "original" if read == original else "masked",
                }
                if read != original:
                    # Search retained manifests by their actual content, never a current key.
                    candidates = connection.execute(
                        "select content_sha256 from artifact where workspace_id=%s "
                        "and source_blob_sha256=%s and kind='masked_source_manifest' "
                        "order by content_sha256",
                        (workspace, row["source_blob_sha256"]),
                    ).fetchall()
                    matches = []
                    for candidate in candidates:
                        receipt = _receipt(store, candidate["content_sha256"])
                        if receipt["state"] == "available":
                            body = json.loads(receipt["json_utf8"])
                            if (
                                body.get("masked_sha256") == read
                                and body.get("source_sha256") == original
                                and body.get("capture_id") == point["capture_ref"]
                            ):
                                matches.append(receipt)
                    lineage["mask_manifest"] = (
                        matches[0]
                        if len(matches) == 1
                        else unavailable("exact_mask_manifest_missing_or_ambiguous")
                    )
                if read != original:
                    lineage["mask_build"] = _mask_build(
                        connection, workspace, row["privacy_screening_id"], original, read
                    )
                item["lineage"] = lineage
            points.append(item)
    pose = unavailable("scene_build_manifest_missing")
    if job:
        row = connection.execute(
            "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
            (workspace, job["pose_receipt_artifact_id"]),
        ).fetchone()
        if row:
            pose = _receipt(store, row["content_sha256"])
    trained = []
    rows = connection.execute(
        "select artifact_id,content_sha256 from artifact where workspace_id=%s "
        "and scene_id=%s and kind='scene_splat_receipt' order by artifact_id",
        (workspace, scene_id),
    ).fetchall()
    for row in rows:
        trained.append(_receipt(store, row["content_sha256"]))
    record = {
        "scene_id": str(scene_id),
        "job_id": str(job["job_id"]) if job else None,
        "captures": captures,
        "point_maps": points,
        "pose_receipt": pose,
        "trained_publications": trained,
        "training_permission": unavailable("separate_training_contract_not_supplied"),
        "authority": unavailable("actor_role_is_not_authenticated_authority"),
    }
    return {
        "profile": PROFILE,
        "record": record,
        "evidence_sha256": sha256_of_canonical(record).hex(),
    }


def _consent_columns_match(row: dict[str, Any]) -> bool:
    record = row["consent_record"]
    fields = {
        "profile",
        "subject_id",
        "region_key",
        "consent_scope",
        "decision",
        "sequence",
        "actor_id",
        "actor_role",
        "effective_at",
        "valid_until",
    }
    if set(record) != fields:
        return False
    for key in ("consent_scope", "decision", "sequence", "actor_role"):
        if record[key] != row[key]:
            return False
    for key in ("subject_id", "actor_id"):
        if record[key] != str(row[key]):
            return False
    if record["region_key"] != _hex(row["region_key"]):
        return False
    try:
        for key in ("effective_at", "valid_until"):
            encoded = (
                dt.datetime.fromisoformat(record[key].replace("Z", "+00:00"))
                if record[key]
                else None
            )
            if encoded != row[key]:
                return False
    except (TypeError, ValueError):
        return False
    return True


def _mask_build(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    screening_id: uuid.UUID,
    original: str,
    read: str,
) -> dict[str, Any]:
    """Use the point's own screening, never a later matching-looking review or mask.

    This is a projection of an immutable persisted build snapshot. No resolver or clock runs.
    Private authorization scope and free-text review material are not part of the projection.
    """
    screening = connection.execute(
        "select receipt_record from reconstruction_privacy_screening "
        "where workspace_id=%s and screening_id=%s",
        (workspace, screening_id),
    ).fetchone()
    if screening is None or not screening["receipt_record"].get("privacy_inputs"):
        return unavailable("legacy_mask_build_snapshot_missing")
    record = screening["receipt_record"]
    masks = [m for m in record.get("mask_artifacts", []) if m.get("content_sha256") == read]
    if len(masks) != 1:
        return unavailable("screening_does_not_bind_exact_mask")
    mask = connection.execute(
        "select input_digest,content_sha256,source_blob_sha256,stage_key,"
        "stage_version,params_digest "
        "from artifact where workspace_id=%s and artifact_id=%s and kind='masked_source'",
        (workspace, masks[0]["artifact_id"]),
    ).fetchone()
    if (
        mask is None
        or _hex(mask["content_sha256"]) != read
        or _hex(mask["source_blob_sha256"]) != original
    ):
        return unavailable("recorded_mask_artifact_mismatch")
    # Intake versions may coexist. Export every candidate digest; the verifier requires exactly
    # one digest that reproduces the mask's persisted input commitment.
    intakes = connection.execute(
        "select distinct content_sha256 from artifact where workspace_id=%s "
        "and source_blob_sha256=decode(%s,'hex') and stage_key='intake' "
        "and content_sha256 is not null order by content_sha256",
        (workspace, original),
    ).fetchall()
    inputs = record["privacy_inputs"]
    return {
        "state": "available",
        "screening_id": str(screening_id),
        "mask_artifact_id": masks[0]["artifact_id"],
        "input_sha256": _hex(mask["input_digest"]),
        "stage_key": mask["stage_key"],
        "stage_version": mask["stage_version"],
        "params_sha256": _hex(mask["params_digest"]),
        "intake_sha256": [_hex(i["content_sha256"]) for i in intakes],
        "capture_id": inputs["capture_id"],
        "source_sha256": inputs["source_sha256"],
        "regions": [
            {
                key: r[key]
                for key in ("region_key", "silhouette", "state", "name_permitted", "subject_id")
            }
            for r in inputs["regions"]
        ],
    }
