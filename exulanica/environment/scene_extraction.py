"""Reusable, explicitly partial samples selected from an existing lifted scene segment.

This is candidate preparation, never admission. The live entry point uses the existing scene
read policy; the pure builder validates the existing segment and placement formats. It preserves
source sample addresses and scene units. Voxel membership is an interpreted coarse selection,
not a new object mask, recovered hidden surface, physical scale, collision or ownership grant.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from exulanica.canonical import canonical_json
from exulanica.evidence.blob import BlobId
from exulanica.graph import reconstruction_scenes as scene_reader
from exulanica.graph.asset_read_policy import (
    evaluation_time,
    final_check,
    scene_allowed,
    scene_inputs,
)
from exulanica.ingest.scene_segments import (
    _evenly,
    _opm_positions,
    _placed,
    _voxels,
    validate_scene_segments,
)
from exulanica.reconstruction.placement import PointMapInput, validate_placement_record
from exulanica.reconstruction.validation import validate_opm
from exulanica.store.base import ContentAddressedStore

PROFILE = "exulanica.scene-surface-candidate/v1"
PRODUCER = "scene-segment-point-selection/1"
MAX_RECEIPT_BYTES = 128 * 1024 * 1024
MAX_MAP_BYTES = 16 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ExtractionPolicy:
    max_source_maps: int = 4
    samples_per_map: int = 25000

    def __post_init__(self) -> None:
        for value, upper in ((self.max_source_maps, 8), (self.samples_per_map, 25000)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("extraction policy exceeds its bounded sample budget")

    def payload(self) -> dict[str, int]:
        return {"max_source_maps": self.max_source_maps, "samples_per_map": self.samples_per_map}


_DEFAULT_POLICY = ExtractionPolicy()


@dataclass(frozen=True)
class SurfaceCandidate:
    manifest: bytes
    points_ply: bytes


def _verified(store: ContentAddressedStore, sha: str, limit: int) -> bytes:
    blob = BlobId.from_hex(sha)
    if store.size(blob) > limit:
        raise ValueError("input exceeds candidate preparation byte budget")
    data = store.get(blob)
    if len(data) > limit or digest(data) != sha:
        raise ValueError("source bytes disagree with their binding")
    return data


def _selection(payload: dict[str, Any], segment_id: str) -> tuple[dict[str, Any], int]:
    matches = [s for s in payload["segments"] if s["segment_id"] == segment_id]
    if len(matches) != 1 or matches[0]["kind"] != "object":
        raise ValueError(
            "one existing object segment is required; person extraction is unsupported"
        )
    segment = matches[0]
    if payload["grid"].get("frame") != "scene":
        raise ValueError("selection must use the original scene frame")
    voxel = payload["grid"]["voxel_size_microunits"]
    if type(voxel) is not int or voxel <= 0:
        raise ValueError("invalid scene voxel size")
    cells = segment["voxels"]
    if (
        not cells
        or len(cells) > 1000000
        or any(
            not isinstance(c, list)
            or len(c) != 3
            or any(type(v) is not int or abs(v) > 10**12 for v in c)
            for c in cells
        )
        or len({tuple(c) for c in cells}) != len(cells)
    ):
        raise ValueError("invalid occupied voxel selection")
    return segment, voxel


def _chosen_inputs(
    payload: dict[str, Any], segment: dict[str, Any], policy: ExtractionPolicy
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources = set(segment["point_map_sources"])
    eligible = sorted(
        (r for r in payload["bindings"]["point_map_inputs"] if r["content_sha256"] in sources),
        key=lambda r: (r["capture_ref"], r["artifact_ref"]),
    )
    if not eligible:
        raise ValueError(
            "segment has no retained point-map samples; Gaussian-only extraction unsupported"
        )
    # Even spread over deterministic capture-reference order; not a claim of camera coverage.
    chosen = [eligible[int(i)] for i in _evenly(len(eligible), policy.max_source_maps)]
    return eligible, chosen


def build_surface_candidate(
    *,
    workspace_ref: str,
    scene_ref: str,
    segment_id: str,
    segments_data: bytes,
    pose_data: bytes,
    placement_data: bytes,
    gate_sha256: str,
    source_maps: dict[str, bytes],
    policy: ExtractionPolicy = _DEFAULT_POLICY,
) -> SurfaceCandidate:
    """Pure producer over supplied bytes. Its result carries no live authorization or admission."""
    import numpy as np

    raw = json.loads(segments_data)["segments"]
    members = raw["bindings"]["member_capture_refs"]
    payload = validate_scene_segments(
        segments_data,
        expected_scene_ref=scene_ref,
        pose_receipt_sha256=digest(pose_data),
        placement_receipt_sha256=digest(placement_data),
        gate_receipt_sha256=gate_sha256,
        member_capture_refs=members,
    )
    segment, voxel = _selection(payload, segment_id)
    eligible, chosen = _chosen_inputs(payload, segment, policy)
    if set(source_maps) != {s["content_sha256"] for s in chosen}:
        raise ValueError("exact selected source maps are required, including every dependency")
    if any(len(b) > MAX_MAP_BYTES for b in source_maps.values()):
        raise ValueError("point-map byte budget exceeded")
    inputs = {
        r["capture_ref"]: PointMapInput(**r, content=source_maps.get(r["content_sha256"]))
        for r in payload["bindings"]["point_map_inputs"]
    }
    if len(inputs) != len(payload["bindings"]["point_map_inputs"]):
        raise ValueError("duplicate point-map capture input")
    placement = validate_placement_record(
        placement_data,
        expected_scene_ref=scene_ref,
        pose_receipt=pose_data,
        member_capture_refs=members,
        point_maps=inputs,
        allow_unavailable_bytes=True,
    )
    placed = {r.capture_ref: r for r in placement.placed}
    occupied = {tuple(c) for c in segment["voxels"]}
    dtype = np.dtype(
        [
            ("x", "<f8"),
            ("y", "<f8"),
            ("z", "<f8"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
            ("source_index", "<u4"),
            ("sample_index", "<u4"),
        ]
    )
    chunks, reports = [], []
    for source_index, source in enumerate(chosen):
        if source["capture_ref"] not in placed:
            raise ValueError("selected source has no validated scene placement")
        data = source_maps[source["content_sha256"]]
        integrity = validate_opm(data)
        indices = _evenly(integrity.point_count, policy.samples_per_map)
        points = _placed(
            placed[source["capture_ref"]].scene_from_opm, _opm_positions(data)[indices]
        )
        if not np.isfinite(points).all() or np.abs(points).max(initial=0) * 1e6 / voxel > 10**12:
            raise ValueError("transformed samples exceed finite voxel coordinates")
        keep = np.fromiter((tuple(c) in occupied for c in _voxels(points, voxel)), dtype=bool)
        header = json.loads(data[8 : 8 + int.from_bytes(data[4:8], "little")])
        color = next(s for s in header["sections"] if s["name"] == "color")
        colors = np.frombuffer(
            data, dtype="u1", count=integrity.point_count * 4, offset=color["byteOffset"]
        ).reshape(-1, 4)
        selected = points[keep]
        rows = np.zeros(len(selected), dtype=dtype)
        for i, name in enumerate(("x", "y", "z")):
            rows[name] = selected[:, i]
        for i, name in enumerate(("red", "green", "blue")):
            rows[name] = colors[indices[keep], i]
        rows["source_index"], rows["sample_index"] = source_index, indices[keep]
        chunks.append(rows)
        reports.append(
            {
                **source,
                "input_points": integrity.point_count,
                "sampled_points": len(indices),
                "selected_points": len(selected),
                "source_color_alpha": integrity.color_alpha,
                "scene_from_opm_float64_hex_row_major": [
                    v.hex() for v in placed[source["capture_ref"]].scene_from_opm
                ],
            }
        )
    points = np.concatenate(chunks)
    if not len(points):
        raise ValueError("bounded source samples do not intersect the selected segment")
    properties = ["property double " + n for n in ("x", "y", "z")]
    properties += ["property uchar " + n for n in ("red", "green", "blue")]
    properties += ["property uint source_index", "property uint sample_index"]
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            "comment partial scene surface candidate",
            f"element vertex {len(points)}",
            *properties,
            "end_header",
            "",
        ]
    ).encode()
    ply = header + points.tobytes()
    manifest = {
        "profile": PROFILE,
        "producer": PRODUCER,
        "status": "candidate-not-admitted",
        "workspace_ref": workspace_ref,
        "subject": {
            "kind": "scene_segment",
            "scene_ref": scene_ref,
            "segment_id": segment_id,
            "segments_sha256": digest(segments_data),
        },
        "origin": {
            "class": "derived-reconstruction-surface",
            "source_scene_ref": scene_ref,
            "bindings": payload["bindings"],
            "source_frames": [
                {"capture_ref": f["capture_ref"], "source_sha256": f["sha256"]}
                for f in json.loads(pose_data)["manifest"]["frames"]
            ],
        },
        "frame": {
            "name": "scene",
            "units": "nonmetric-scene-units",
            "metric_scale": False,
            "axes": "unchanged COLMAP scene frame; gravity orientation not established",
            "placement": "source scene transforms applied exactly once; no recentering",
        },
        "selection": {
            "label": segment["label"],
            "status": "interpreted-voxel-membership",
            "voxel_size_microunits": voxel,
            "occupied_voxels": len(occupied),
            "support_votes": segment["votes"],
            "regions": segment["regions"],
            "eligible_source_maps": len(eligible),
            "selected_sources": reports,
        },
        "recipe": {
            "method": PRODUCER,
            "policy": policy.payload(),
            "deterministic": True,
            "seed": None,
            "ordering": "capture ref, then original sample index",
        },
        "geometry": {
            "file": "surface.ply",
            "sha256": digest(ply),
            "byte_size": len(ply),
            "points": len(points),
            "bounds_microunits": {
                k: [
                    math.floor(points[a].min() * 1e6)
                    if k == "min"
                    else math.ceil(points[a].max() * 1e6)
                    for a in ("x", "y", "z")
                ]
                for k in ("min", "max")
            },
        },
        "uncertainty": [
            "Input points are estimated surfaces, not ground-truth measurements.",
            "Coarse voxel membership can include neighbouring surfaces; "
            "this does not repeat semantic voting.",
            "Bounded sampling can omit visible surfaces. Unobserved sides and gaps remain absent.",
            "No watertightness, material seams, physical scale, collision or navigability.",
        ],
        "permitted_uses": ["private candidate inspection subject to current source authorization"],
        "withdrawal_dependencies": {
            "scene_ref": scene_ref,
            "segments_sha256": digest(segments_data),
            "source_bindings": payload["bindings"],
        },
        "admission": {
            "authorized_for_publication": False,
            "required": [
                "current source rights and exact dependency checks",
                "geometry and visible-quality review",
                "explicit destination placement and supported uses",
                "authenticated delivery and withdrawal propagation",
            ],
        },
    }
    manifest["document_sha256"] = digest(canonical_json(manifest))
    return SurfaceCandidate(canonical_json(manifest) + b"\n", ply)


def prepare_current_surface(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    workspace: uuid.UUID,
    scene: uuid.UUID,
    segment_id: str,
    policy: ExtractionPolicy = _DEFAULT_POLICY,
) -> SurfaceCandidate:
    """Read and validate current source state, buffer candidate, then repeat permission checks.

    Caller supplies an idle workspace-scoped connection. This writes neither DB nor storage.
    Persisting/exporting or serving the returned candidate needs the separate admission contract.
    """
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        read = scene_reader.scene_segments_read(connection, workspace, scene, store)
        buffered = scene_inputs(connection, workspace, scene, store)
        at = evaluation_time(connection)
        if (
            read is None
            or read.state != "available"
            or not scene_allowed(connection, workspace, scene, buffered, at)
        ):
            raise ValueError("current authorized scene segments are unavailable")
        if not scene_reader.scene_segments_artifacts_live(connection, workspace, read, at):
            raise ValueError("segment dependencies are unavailable")
        if not any(s["segment_id"] == segment_id and s["kind"] == "object" for s in read.segments):
            raise ValueError("selected object segment is unavailable")
        data = _verified(store, read.content_sha256, MAX_RECEIPT_BYTES)
        payload = json.loads(data)["segments"]
        segment, _ = _selection(payload, segment_id)
        _, chosen = _chosen_inputs(payload, segment, policy)
        maps = {
            r["content_sha256"]: _verified(store, r["content_sha256"], MAX_MAP_BYTES)
            for r in chosen
        }
        candidate = build_surface_candidate(
            workspace_ref=str(workspace),
            scene_ref=str(scene),
            segment_id=segment_id,
            segments_data=data,
            pose_data=_verified(store, read.pose_receipt_sha256, MAX_RECEIPT_BYTES),
            placement_data=_verified(store, read.placement_receipt_sha256, MAX_RECEIPT_BYTES),
            gate_sha256=read.gate_receipt_sha256,
            source_maps=maps,
            policy=policy,
        )
        bound_masks = sorted(
            (x["capture_ref"], x["artifact_ref"], x["content_sha256"])
            for x in payload["bindings"]["object_mask_inputs"]
        )
    with final_check(connection) as at:
        if not scene_allowed(
            connection, workspace, scene, buffered, at
        ) or not scene_reader.scene_segments_artifacts_live(connection, workspace, read, at):
            raise ValueError("source authorization or dependencies changed during extraction")
        # Reuse the reader's exact latest-mask query without any store I/O under the final lock.
        current_masks = connection.execute(
            scene_reader._SEGMENT_OBJECT_MASKS,
            (
                workspace,
                [uuid.UUID(m) for m in payload["bindings"]["member_capture_refs"]],
                scene_reader.OBJECT_MASK_KIND,
            ),
        ).fetchall()
        if (
            sorted(
                (str(m["capture_id"]), str(m["artifact_id"]), bytes(m["content_sha256"]).hex())
                for m in current_masks
            )
            != bound_masks
        ):
            raise ValueError("object mask interpretation changed during extraction")
    return candidate
