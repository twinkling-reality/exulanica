"""Exact posed-image delivery bindings; identity pixel transforms only."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.corpus.decode import UNREADABLE, open_sensor
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time, image_source
from exulanica.graph.wire_numbers import decimal_string, decimal_strings
from exulanica.reconstruction.placement import recovered_camera_records
from exulanica.store.base import ContentAddressedStore

PROFILE = "exulanica.world-read-view/v1"


class ViewError(ValueError):
    """A named, controlled byte or pixel-space refusal."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ViewError(reason)


def image_facts(data: bytes, digest: str) -> dict[str, Any]:
    require(hashlib.sha256(data).hexdigest() == digest, "view_bytes_digest_mismatch")
    try:
        with open_sensor(data) as image:
            orientation = image.getexif().get(274, 1)
            require(orientation == 1, "pose_orientation_transform_unrecorded")
            media_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
                "TIFF": "image/tiff",
            }.get(image.format)
            require(media_type is not None, "view_media_type_unsupported")
            return {
                "sha256": digest,
                "byte_length": len(data),
                "media_type": media_type,
                "width": image.width,
                "height": image.height,
                "exif_orientation": 1,
            }
    except ViewError:
        raise
    except UNREADABLE as error:
        raise ViewError("view_image_unreadable") from error


def wire_camera(raw: dict[str, Any]) -> dict[str, Any]:
    calibration = raw["calibration"]
    return {
        "scene_from_camera_row_major": decimal_strings(raw["scene_from_camera_row_major"]),
        "projection": raw["projection"],
        "calibration": {
            **{key: calibration[key] for key in ("model", "width", "height")},
            **{key: decimal_string(calibration[key]) for key in ("fx", "fy", "cx", "cy")},
            "parameters": decimal_strings(calibration["parameters"]),
        },
    }


def check_pixels(facts: dict[str, Any], camera: dict[str, Any]) -> None:
    require(
        (facts["width"], facts["height"])
        == (camera["calibration"]["width"], camera["calibration"]["height"]),
        "camera_pixel_space_mismatch",
    )


def consent_binding(
    connection: psycopg.Connection, workspace: uuid.UUID, capture_id: uuid.UUID | str
) -> str:
    """Commit recorded inputs, leaving permission decisions to the shared policy."""
    rows = connection.execute(
        "select encode(r.region_digest,'hex') as region, "
        "array(select encode(c.consent_digest,'hex') from person_presentation_consent c "
        "where c.workspace_id=r.workspace_id and c.subject_id=r.subject_id "
        "and (c.region_key is null or c.region_key=r.region_key or c.decision='withdrawn') "
        "order by c.consent_digest) as receipts "
        "from person_region_current r where r.workspace_id=%s and r.capture_id=%s "
        "and r.action<>'deleted' order by r.region_key",
        (workspace, capture_id),
    ).fetchall()
    return sha256_of_canonical(rows).hex()


def recorded_consent_binding(capture: dict[str, Any]) -> str:
    return sha256_of_canonical(
        [
            {
                "region": region["region_sha256"],
                "receipts": sorted(receipt["sha256"] for receipt in region["receipts"]),
            }
            for region in sorted(capture["regions"], key=lambda r: r["region_key"])
        ]
    ).hex()


def current_binding(
    connection: psycopg.Connection, workspace: uuid.UUID, value: dict[str, Any], at: dt.datetime
) -> bool:
    return (
        image_source(connection, workspace, bytes.fromhex(value["source_sha256"]), at)
        == bytes.fromhex(value["sha256"])
        and consent_binding(connection, workspace, value["capture_id"])
        == value["consent_binding_sha256"]
    )


def views_current(
    connection: psycopg.Connection, workspace: uuid.UUID, envelope: dict[str, Any], at: dt.datetime
) -> bool:
    return all(
        current_binding(connection, workspace, view["photo_bytes"], at)
        for view in envelope["bundle"].get("views", [])
        if view.get("photo_bytes", {}).get("state") == "available"
    )


def descriptor(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    view: dict[str, Any],
    evidence: dict[str, Any],
    store: ContentAddressedStore | None,
) -> dict[str, Any]:
    """Project bytes only when current selection equals the exact persisted pose source."""
    identity = {"profile": PROFILE, "state": "unavailable"}
    if view["camera"] is None or not view["registered"]:
        return {**identity, "reason": "view_not_registered_or_calibrated"}
    if store is None:
        return {**identity, "reason": "view_store_unavailable"}
    try:
        record = evidence["record"]
        capture = next(c for c in record["captures"] if c["capture_id"] == view["capture_id"])
        pose = record["pose_receipt"]
        require(pose["state"] == "available", "pose_binding_unavailable")
        pose_bytes = pose["json_utf8"].encode()
        require(hashlib.sha256(pose_bytes).hexdigest() == pose["sha256"], "pose_digest_mismatch")
        cameras = recovered_camera_records(pose_bytes)
        require(view["capture_id"] in cameras, "view_not_registered_or_calibrated")
        require(wire_camera(cameras[view["capture_id"]]) == view["camera"], "view_camera_mismatch")
        frames = json.loads(pose_bytes)["manifest"]["frames"]
        frame = next(f for f in frames if f["capture_ref"] == view["capture_id"])
        original = capture["source_sha256"]
        points = [p for p in record["point_maps"] if p["capture_id"] == view["capture_id"]]
        require(len(points) == 1, "frozen_point_binding_missing")
        lineage = points[0]["lineage"]
        require(
            lineage["state"] == "available"
            and lineage["source_sha256"] == original
            and lineage["read_sha256"] == frame["sha256"],
            "view_source_lineage_unavailable",
        )
        if lineage["mode"] == "masked":
            require(
                lineage["mask_manifest"]["state"] == "available"
                and lineage["mask_build"]["state"] == "available",
                "view_mask_lineage_unavailable",
            )
        selected = image_source(
            connection, workspace, bytes.fromhex(original), evaluation_time(connection)
        )
        identity.update(
            source_sha256=original,
            pose_input_sha256=frame["sha256"],
            selected_sha256=selected.hex() if selected else None,
        )
        require(selected is not None, "current_viewer_image_unavailable")
        require(selected.hex() == frame["sha256"], "viewer_pose_transform_unrecorded")
        span = connection.execute(
            "select span_id from evidence_span where workspace_id=%s and blob_sha256=%s "
            "and track_key='img' and region is null order by span_id limit 1",
            (workspace, bytes.fromhex(original)),
        ).fetchone()
        require(span is not None, "view_evidence_span_missing")
        facts = image_facts(store.get(BlobId(selected)), selected.hex())
        check_pixels(facts, view["camera"])
        body = {
            "profile": PROFILE,
            "state": "available",
            **facts,
            "scene_id": str(scene_id),
            "capture_id": view["capture_id"],
            "span_id": str(span["span_id"]),
            "source_sha256": original,
            "pose_input_sha256": frame["sha256"],
            "pose_receipt_sha256": pose["sha256"],
            "recorded_evidence_sha256": evidence["evidence_sha256"],
            "consent_binding_sha256": consent_binding(connection, workspace, view["capture_id"]),
            "kind": "original" if original == selected.hex() else "masked",
            "pixel_transform": "identity_no_crop_no_resize_no_orientation",
            "camera": view["camera"],
        }
        binding = sha256_of_canonical(body).hex()
        return {**body, "binding_sha256": binding, "fetch": fetch_reference(body, binding)}
    except ViewError as error:
        return {**identity, "reason": str(error)}
    except (BlobNotFoundError, IntegrityError):
        return {**identity, "reason": "view_bytes_missing_or_corrupt"}
    except (KeyError, TypeError, ValueError, StopIteration):
        return {**identity, "reason": "view_binding_unavailable"}


def fetch_reference(body: dict[str, Any], binding: str) -> str:
    return (
        f"/evidence/{body['span_id']}/masked?view_scene={body['scene_id']}"
        f"&view_capture={body['capture_id']}&view_binding={binding}"
    )


def verify_view(view: dict[str, Any], record: dict[str, Any], data: bytes | None) -> dict[str, Any]:
    """Verify a single descriptor against exact retained pose evidence and downloaded bytes."""
    try:
        value = view.get("photo_bytes")
        if "photo_bytes" not in view:
            return {"state": "unavailable", "reason": "legacy_view_binding_missing"}
        require(
            isinstance(value, dict) and value.get("profile") == PROFILE, "view_descriptor_malformed"
        )
        if value.get("state") == "unavailable":
            require(
                isinstance(value.get("reason"), str) and bool(value["reason"]),
                "view_descriptor_malformed",
            )
            return {"state": "unavailable", "reason": value["reason"]}
        require(value.get("state") == "available", "view_descriptor_malformed")
        keys = {
            "profile",
            "state",
            "sha256",
            "byte_length",
            "media_type",
            "width",
            "height",
            "exif_orientation",
            "scene_id",
            "capture_id",
            "span_id",
            "source_sha256",
            "pose_input_sha256",
            "pose_receipt_sha256",
            "recorded_evidence_sha256",
            "consent_binding_sha256",
            "kind",
            "pixel_transform",
            "camera",
        }
        require(set(value) == keys | {"binding_sha256", "fetch"}, "view_descriptor_malformed")
        body = {key: value[key] for key in keys}
        require(
            sha256_of_canonical(body).hex() == value["binding_sha256"],
            "view_binding_digest_mismatch",
        )
        require(
            value["fetch"] == fetch_reference(body, value["binding_sha256"]), "view_fetch_mismatch"
        )
        for key in ("span_id", "scene_id", "capture_id"):
            require(str(uuid.UUID(value[key])) == value[key], "view_descriptor_malformed")
        require(
            value["pixel_transform"] == "identity_no_crop_no_resize_no_orientation",
            "view_transform_unsupported",
        )
        require(
            value["capture_id"] == view["capture_id"]
            and view["registered"] is True
            and value["scene_id"] == record["scene_id"],
            "view_identity_mismatch",
        )
        require(
            sha256_of_canonical(record).hex() == value["recorded_evidence_sha256"],
            "view_recorded_evidence_mismatch",
        )
        pose = record["pose_receipt"]
        require(
            pose["state"] == "available" and pose["sha256"] == value["pose_receipt_sha256"],
            "view_pose_binding_mismatch",
        )
        raw = pose["json_utf8"].encode()
        require(hashlib.sha256(raw).hexdigest() == pose["sha256"], "pose_digest_mismatch")
        cameras = recovered_camera_records(raw)
        require(
            value["camera"] == view["camera"] == wire_camera(cameras[view["capture_id"]]),
            "view_camera_mismatch",
        )
        frame = next(
            f
            for f in json.loads(raw)["manifest"]["frames"]
            if f["capture_ref"] == view["capture_id"]
        )
        capture = next(c for c in record["captures"] if c["capture_id"] == view["capture_id"])
        require(
            recorded_consent_binding(capture) == value["consent_binding_sha256"],
            "view_consent_binding_mismatch",
        )
        require(
            value["source_sha256"] == capture["source_sha256"]
            and value["sha256"] == value["pose_input_sha256"] == frame["sha256"],
            "view_source_lineage_mismatch",
        )
        require(
            value["kind"]
            == ("original" if value["sha256"] == value["source_sha256"] else "masked"),
            "view_kind_mismatch",
        )
        require(data is not None, "downloaded_view_missing")
        facts = image_facts(data, value["sha256"])
        require(
            all(
                type(value[key]) is type(item) and value[key] == item for key, item in facts.items()
            ),
            "view_decoded_metadata_mismatch",
        )
        check_pixels(facts, value["camera"])
        return {
            "state": "verified",
            "sha256": value["sha256"],
            "kind": value["kind"],
            "width": facts["width"],
            "height": facts["height"],
        }
    except ViewError:
        raise
    except (KeyError, TypeError, ValueError, StopIteration) as error:
        raise ViewError("view_descriptor_malformed") from error
