"""Offline checks for recorded World Read evidence; no database or ambient clock."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.graph.world_read_evidence import (
    MASK_PROFILE,
    POSE_PROFILE,
    PROFILE,
    TRAINED_PROFILE,
    receipt_problem,
)


class EvidenceError(ValueError):
    """A named recipient check failed."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def instant(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "evaluation_requires_zoned_time")
    return result


def receipt(value: dict[str, Any], expected_profile: str) -> dict[str, Any] | None:
    require(value["state"] in {"available", "unavailable"}, "receipt_state_invalid")
    if value["state"] == "unavailable":
        require(isinstance(value.get("reason"), str), "receipt_unavailable_reason_missing")
        return None
    raw = value["json_utf8"].encode()
    require(hashlib.sha256(raw).hexdigest() == value["sha256"], "receipt_digest_mismatch")
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise EvidenceError("receipt_invalid_json") from None
    problem = receipt_problem(body, expected_profile)
    require(problem is None, problem or "receipt_unsupported_shape")
    return body


def presentation(region: dict[str, Any], at: dt.datetime) -> dict[str, Any]:
    held = {}
    records = []
    for item in region["receipts"]:
        require(item["state"] == "available", "consent_receipt_unavailable")
        record = item["record"]
        require(sha256_of_canonical(record).hex() == item["sha256"], "consent_digest_mismatch")
        require(
            record["profile"] == "exulanica.person-presentation-consent/v1",
            "consent_profile_mismatch",
        )
        require(record["subject_id"] == region["subject_id"], "consent_subject_mismatch")
        records.append(record)
    withdrawn = any(record["decision"] == "withdrawn" for record in records)
    for scope in ("presence", "naming", "likeness", "temporary_hide"):
        candidates = [
            r
            for r in records
            if r["consent_scope"] == scope
            and r["region_key"] in (None, region["region_key"])
            and instant(r["effective_at"]) <= at
            and (r["valid_until"] is None or at < instant(r["valid_until"]))
        ]
        keys = [(r["region_key"] is not None, r["sequence"]) for r in candidates]
        require(not keys or keys.count(max(keys)) == 1, "ambiguous_consent_sequence")
        winner = max(
            candidates, key=lambda r: (r["region_key"] is not None, r["sequence"]), default=None
        )
        held[scope] = bool(not withdrawn and winner and winner["decision"] == "granted")
    return {
        "region_key": region["region_key"],
        "scopes": held,
        "withdrawn": withdrawn,
        "masked": withdrawn or region["subject_id"] is None or not held["likeness"],
    }


def verify(envelope: dict[str, Any], *, at: str, expected_bundle_sha256: str) -> dict[str, Any]:
    """Return controlled failures for unsupported wire shapes, never interpreter exceptions."""
    try:
        return _verify(envelope, at=at, expected_bundle_sha256=expected_bundle_sha256)
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise EvidenceError("recipient_payload_malformed") from None


def _verify(envelope: dict[str, Any], *, at: str, expected_bundle_sha256: str) -> dict[str, Any]:
    """Check an exact trusted envelope and evaluate recorded permissions at a caller's time."""
    time = instant(at)
    canonical_json(envelope)  # Reject floats throughout the outer wire contract.
    bundle = envelope["bundle"]
    require(envelope["bundle_sha256"] == expected_bundle_sha256, "unexpected_bundle_digest")
    require(sha256_of_canonical(bundle).hex() == expected_bundle_sha256, "bundle_digest_mismatch")
    expected_keys = sorted(
        set(bundle)
        - {"generated", "scene", "views", "geometry", "rungs", "recorded_keys", "recorded_sha256"}
    )
    require(
        bundle["recorded_keys"] == expected_keys
        and bundle.get("recorded_digest_profile") == "exulanica.world-read-recorded/v2",
        "recorded_recipe_mismatch",
    )
    require(
        sha256_of_canonical({key: bundle[key] for key in bundle["recorded_keys"]}).hex()
        == bundle["recorded_sha256"],
        "recorded_digest_mismatch",
    )
    if "unresolved" in bundle:
        require(
            bundle["addressing"]["by"] == "place_at_time"
            and bundle["addressing"]["scene_id"] is None
            and not any(
                key in bundle for key in ("scene", "views", "geometry", "recipient_evidence")
            ),
            "unresolved_address_mismatch",
        )
        return {
            "evaluated_at": at,
            "state": "unavailable",
            "reason": bundle["unresolved"]["state"],
            "release": "internal_only",
        }
    evidence = bundle.get("recipient_evidence")
    require(evidence is not None, "recipient_evidence_missing")
    require(evidence["profile"] == PROFILE, "evidence_profile_mismatch")
    record = evidence["record"]
    require(
        sha256_of_canonical(record).hex() == evidence["evidence_sha256"], "evidence_digest_mismatch"
    )
    require(bundle["release"]["state"] == "internal_only", "release_must_remain_internal_only")
    require(record["scene_id"] == bundle["scene"]["scene_id"], "evidence_scene_mismatch")
    captures = {c["capture_id"]: c for c in record["captures"]}
    require(len(captures) == len(record["captures"]), "duplicate_capture")
    require(
        set(captures) == {v["capture_id"] for v in bundle["views"]}, "capture_inventory_mismatch"
    )
    evaluated = {}
    for key, capture in captures.items():
        require(
            len(capture["regions"])
            == bundle["consent"]["per_capture"][key]["recorded_person_count"],
            "person_inventory_mismatch",
        )
        evaluated[key] = [presentation(r, time) for r in capture["regions"]]
    pose = receipt(record["pose_receipt"], POSE_PROFILE)
    frames = {}
    if pose is not None:
        manifest = pose["manifest"]
        require(manifest["scene_ref"] == record["scene_id"], "pose_scene_mismatch")
        # These original producer receipts use compact JSON, including floats, not canonical_json.
        raw = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        require(
            hashlib.sha256(raw).hexdigest() == pose["manifest_digest"], "pose_manifest_mismatch"
        )
        frames = {f["capture_ref"]: f["sha256"] for f in manifest["frames"]}
        require(set(frames) == set(captures), "pose_contributor_mismatch")
    lineage = {}
    for point in record["point_maps"]:
        key = point["capture_id"]
        require(key in captures, "point_capture_mismatch")
        source = point["lineage"]
        status = {"state": "unavailable", "reason": source.get("reason", "pose_manifest_missing")}
        if source["state"] == "available":
            require(
                source["source_sha256"] == captures[key]["source_sha256"], "point_source_mismatch"
            )
            if frames:
                require(source["read_sha256"] == frames[key], "point_pose_source_mismatch")
                status = {"state": "available"}
            if source["mode"] == "masked":
                mask = receipt(source["mask_manifest"], MASK_PROFILE)
                if mask is None:
                    status = dict(source["mask_manifest"])
                else:
                    require(
                        mask["profile"] == "exulanica.masked-source-manifest/v1"
                        and mask["masked_sha256"] == source["read_sha256"]
                        and mask["source_sha256"] == source["source_sha256"]
                        and mask["capture_id"] == key,
                        "mask_source_mismatch",
                    )
                    build = source["mask_build"]
                    if build["state"] != "available":
                        status = {"state": "unavailable", "reason": build["reason"]}
                    else:
                        check_mask_build(build, mask, captures[key])
                    masked_keys = {m["region_key"] for m in mask["masks"]}
                    require(
                        all(r["region_key"] in masked_keys for r in evaluated[key] if r["masked"]),
                        "stale_derivative_lineage",
                    )
            else:
                require(
                    source["mode"] == "original"
                    and source["read_sha256"] == source["source_sha256"],
                    "original_source_mismatch",
                )
                if any(r["masked"] for r in evaluated[key]):
                    status = {
                        "state": "unavailable",
                        "reason": "recorded_original_requires_mask_at_evaluation",
                    }
        require(point["artifact_id"] not in lineage, "duplicate_point_artifact")
        lineage[point["artifact_id"]] = status
    publications = [receipt(r, TRAINED_PROFILE) for r in record["trained_publications"]]
    for geometry in bundle["geometry"]:
        if geometry["kind"] == "point_map":
            matches = [
                p for p in record["point_maps"] if p["artifact_id"] == geometry["artifact_id"]
            ]
            if not matches and geometry.get("source_lineage") == {
                "state": "unavailable",
                "reason": "frozen_point_binding_missing",
            }:
                lineage[geometry["artifact_id"]] = geometry["source_lineage"]
                continue
            require(len(matches) == 1, "geometry_lineage_missing")
            require(
                matches[0]["content_sha256"] == geometry["content_sha256"]
                and matches[0]["capture_id"] == geometry["capture_id"],
                "geometry_output_mismatch",
            )
        elif geometry["kind"] == "trained_geometry":
            matches = [
                p
                for p in publications
                if p is not None
                and p.get("delivery", {}).get("artifact_id") == geometry["artifact_id"]
            ]
            require(len(matches) == 1, "trained_publication_missing_or_ambiguous")
            publication = matches[0]
            manifest = publication["manifest"]
            original_manifest = json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
            require(
                publication.get("profile") == "exulanica.scene-splat-publication/v1"
                and publication.get("scene_ref") == record["scene_id"]
                and publication.get("quality", {}).get("accepted") is True,
                "trained_publication_invalid",
            )
            require(
                hashlib.sha256(original_manifest).hexdigest() == publication["manifest_digest"]
                and pose is not None
                and manifest["pose_manifest_digest"] == pose["manifest_digest"],
                "trained_manifest_mismatch",
            )
            require(
                publication["delivery"]["content_sha256"] == geometry["content_sha256"],
                "trained_output_mismatch",
            )
            require(
                publication["pose_receipt_sha256"] == record["pose_receipt"]["sha256"]
                and publication["manifest"]["source_sha256"] == list(frames.values()),
                "trained_source_mismatch",
            )
    return {
        "evaluated_at": at,
        "evidence_sha256": evidence["evidence_sha256"],
        "release": "internal_only",
        "people": evaluated,
        "point_lineage": lineage,
        "later_withdrawals": "not_discoverable_offline",
    }


def check_mask_build(
    build: dict[str, Any],
    manifest: dict[str, Any],
    capture: dict[str, Any],
) -> None:
    """Reproduce the persisted mask input commitment from its historical screening projection."""
    require(
        build["source_sha256"] == capture["source_sha256"]
        and build["capture_id"] == capture["capture_id"],
        "mask_build_source_mismatch",
    )
    regions = sorted(build["regions"], key=lambda r: r["region_key"])
    require(len({r["region_key"] for r in regions}) == len(regions), "duplicate_mask_region")
    region_digest = sha256_of_canonical(
        {
            "profile": "exulanica.person-region-set/v1",
            "capture_id": capture["capture_id"],
            "source_sha256": capture["source_sha256"],
            "regions": [
                {"region_key": r["region_key"], "silhouette": r["silhouette"]} for r in regions
            ],
        }
    ).hex()
    state_digest = sha256_of_canonical(
        {
            "profile": "exulanica.person-consent-state/v1",
            "capture_id": capture["capture_id"],
            "source_sha256": capture["source_sha256"],
            "states": [
                {
                    "region_key": r["region_key"],
                    "state": r["state"],
                    "masked": r["state"] in ("unknown", "present", "withdrawn"),
                    "name_permitted": r["name_permitted"],
                }
                for r in regions
            ],
        }
    ).hex()
    matches = [
        digest
        for digest in build["intake_sha256"]
        if sha256_of_canonical(sorted([digest, region_digest, state_digest])).hex()
        == build["input_sha256"]
    ]
    require(len(matches) == 1, "mask_input_commitment_mismatch")
    require(
        build["stage_key"] == "masked_source"
        and build["stage_version"] == manifest["stage_version"],
        "mask_stage_mismatch",
    )
    require(
        manifest["fill"] == "neutral-flat" and manifest["generative_fill"] is False,
        "mask_fill_mismatch",
    )
    current = {r["region_key"]: r["silhouette"] for r in capture["regions"]}
    historical = {r["region_key"]: r["silhouette"] for r in regions}
    require(current == historical, "stale_derivative_lineage")
