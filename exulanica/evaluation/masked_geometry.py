"""Read-only retrospective evaluation of retained Gaussian delivery geometry.

This measures today's recorded person regions against an existing delivery. It cannot infer
which masks were used during historical training, or prove a detector found every person.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.evaluation.reference_inputs import envelope
from exulanica.ingest.masked_geometry import GaussianView, count_masked_gaussians
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.repository import IngestRepository

DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
ROOT = Path(__file__).resolve().parents[2]


def _blob(root: Path, digest: str) -> bytes:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid content digest")
    data = (root / "sha-256" / digest[:2] / digest[2:4] / digest).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("retained content digest does not verify")
    return data


def predecessor(path: Path) -> dict[str, str]:
    relative = path.resolve().relative_to(ROOT).as_posix()
    document = json.loads(path.read_bytes())
    if document != envelope(document["record"]):
        raise ValueError("predecessor envelope does not verify")
    return {"path": relative, "record_sha256": document["record_sha256"]}


def camera_view(camera: dict, state: Any) -> GaussianView:
    calibration = camera["calibration"]
    model, parameters = calibration["model"], calibration["parameters"]
    if model in {"SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"}:
        focal = (parameters[0], parameters[0])
        principal = tuple(parameters[1:3])
    elif model in {"PINHOLE", "OPENCV", "OPENCV_FISHEYE", "FULL_OPENCV"}:
        focal, principal = tuple(parameters[:2]), tuple(parameters[2:4])
    else:
        raise ValueError(f"unsupported camera calibration: {model}")
    size = tuple(camera["image_size"])
    quaternion = tuple(camera["quaternion_wxyz"])
    translation = tuple(camera["translation_xyz"])
    if (
        len(size) != 2
        or min(size) <= 0
        or len(quaternion) != 4
        or len(translation) != 3
        or len(focal) != 2
        or len(principal) != 2
        or min(focal) <= 0
        or not all(math.isfinite(v) for v in (*quaternion, *translation, *focal, *principal))
        or not math.isclose(sum(v * v for v in quaternion), 1, abs_tol=1e-5)
    ):
        raise ValueError("invalid recovered camera")
    return GaussianView(
        image_name=camera["image_name"],
        quaternion_wxyz=quaternion,
        translation_xyz=translation,
        image_size=size,
        focal_xy=focal,
        principal_xy=principal,
        masked=tuple(v for k, v in state.outlines.items() if state.resolved[k].masked),
        confirmed=tuple(v for k, v in state.outlines.items() if state.subjects[k] is not None),
        projection="exact" if model in {"PINHOLE", "SIMPLE_PINHOLE"} else "pinhole-approximation",
    )


def evaluate_ply(ply: bytes, views: list[GaussianView]) -> dict:
    """Keep the geometry result in the evaluation bundle, including its empty-region coverage."""
    if not views or len({v.image_name for v in views}) != len(views):
        raise ValueError("evaluation requires unique recovered camera membership")
    # Radial source cameras use a wider declared margin. This is still an approximation, not
    # calibrated distortion inversion, and cannot certify that all boundary points are covered.
    margin = 20_000 if any(v.projection != "exact" for v in views) else 10_000
    return {
        "profile": "exulanica.retrospective-geometry-evaluation/v1",
        "masked_geometry": count_masked_gaussians(ply=ply, views=views, margin_ppm=margin),
        "recorded_masked_regions": sum(len(v.masked) for v in views),
        "recorded_confirmed_regions": sum(len(v.confirmed) for v in views),
        "region_basis": "current database snapshot; historical training masks unavailable",
        "privacy_verdict": "not established by this retrospective count",
    }


def _decode_sog(data: bytes) -> tuple[bytes, dict]:
    compressor = ROOT / "deploy/gsplat/compressor"
    package = compressor / "node_modules/@playcanvas/splat-transform"
    installed = json.loads((package / "package.json").read_bytes())
    wanted = json.loads((compressor / "package.json").read_bytes())["dependencies"]
    if installed["version"] != wanted["@playcanvas/splat-transform"]:
        raise ValueError("installed decoder differs from the locked compressor")
    with tempfile.TemporaryDirectory(prefix="exulanica-geometry-") as scratch:
        source, output = Path(scratch) / "scene.sog", Path(scratch) / "decoded.ply"
        source.write_bytes(data)
        result = subprocess.run(
            ["node", str(package / "bin/cli.mjs"), "--gpu", "cpu", str(source), str(output)],
            capture_output=True,
            check=True,
            timeout=300,
        )
        ply = output.read_bytes()
    return ply, {
        "name": "@playcanvas/splat-transform",
        "version": installed["version"],
        "decoder_source_sha256": hashlib.sha256(
            (package / "dist/index.mjs").read_bytes()
        ).hexdigest(),
        "package_lock_sha256": hashlib.sha256(
            (compressor / "package-lock.json").read_bytes()
        ).hexdigest(),
        "decoded_ply_sha256": hashlib.sha256(ply).hexdigest(),
        "execution_log": (result.stdout + result.stderr)
        .decode(errors="replace")
        .replace(scratch, "<scratch>"),
        "geometry_basis": "decoded quantized SOG delivery, not original training PLY",
        "gpu": "cpu",
    }


def code_provenance() -> dict:
    files = (
        "exulanica/evaluation/masked_geometry.py",
        "exulanica/ingest/masked_geometry.py",
        "exulanica/ingest/person_state.py",
        "exulanica/consent/states.py",
    )
    return {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "executed_files_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files
        },
    }


def measure(workspace: uuid.UUID, artifact: uuid.UUID, blobs: Path) -> dict:
    """Read a repeatable, database-enforced read-only snapshot; never run training or admission."""
    code = code_provenance()
    with psycopg.connect(
        DATABASE,
        row_factory=dict_row,
        options=(
            "-c default_transaction_read_only=on -c default_transaction_isolation=repeatable\\ read"
        ),
    ) as connection:
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, true)", (str(workspace),)
        )
        row = connection.execute(
            "select artifact_id, scene_id, kind, content_sha256, byte_size from artifact "
            "where workspace_id=%s and artifact_id=%s and purged_at is null and not needs_repair",
            (workspace, artifact),
        ).fetchone()
        if row is None or row["kind"] != "gaussian_splat_scene":
            raise ValueError("selected artifact is not an available Gaussian scene")
        digest = bytes(row["content_sha256"]).hex()
        data = _blob(blobs, digest)
        if len(data) != row["byte_size"]:
            raise ValueError("delivery byte size differs from artifact")
        candidates = connection.execute(
            "select content_sha256 from artifact where workspace_id=%s and scene_id=%s "
            "and kind='scene_splat_receipt' and purged_at is null and not needs_repair",
            (workspace, row["scene_id"]),
        ).fetchall()
        matches = []
        for candidate in candidates:
            receipt_digest = bytes(candidate["content_sha256"]).hex()
            receipt = json.loads(_blob(blobs, receipt_digest))
            delivery = receipt.get("delivery")
            if (
                delivery
                and delivery.get("artifact_id") == str(artifact)
                and delivery.get("content_sha256") == digest
            ):
                matches.append((receipt_digest, receipt))
        if len(matches) != 1:
            raise ValueError("delivery requires one exact publication receipt")
        receipt_digest, receipt = matches[0]
        pose_digest = receipt["pose_receipt_sha256"]
        pose = json.loads(_blob(blobs, pose_digest))
        if pose["manifest_digest"] != receipt["manifest"]["pose_manifest_digest"]:
            raise ValueError("publication and pose manifest disagree")
        frames = {frame["filename"]: frame for frame in pose["manifest"]["frames"]}
        cameras = pose["quality"]["cameras"]
        names = [camera["image_name"] for camera in cameras]
        if set(names) != set(pose["quality"]["registered_images"]) or len(names) != len(set(names)):
            raise ValueError("pose camera membership differs from registered images")
        if not set(names) <= set(frames):
            raise ValueError("registered camera lacks a source manifest member")
        if len(frames) != len(pose["manifest"]["frames"]):
            raise ValueError("pose manifest repeats source filenames")
        capture_rows = connection.execute(
            "select capture_id, blob_sha256 from capture where workspace_id=%s "
            "and capture_id = any(%s)",
            (workspace, [uuid.UUID(frame["capture_ref"]) for frame in frames.values()]),
        ).fetchall()
        sources = {
            str(item["capture_id"]): bytes(item["blob_sha256"]).hex() for item in capture_rows
        }
        if any(sources.get(frame["capture_ref"]) != frame["sha256"] for frame in frames.values()):
            raise ValueError("pose member is absent or its source differs in this workspace")
        repository = IngestRepository(connection, workspace)
        views, regions = [], []
        for camera in cameras:
            frame = frames[camera["image_name"]]
            state = region_state_for_capture(repository, uuid.UUID(frame["capture_ref"]))
            views.append(camera_view(camera, state))
            regions.append(
                {
                    "image_name": camera["image_name"],
                    "capture_id": frame["capture_ref"],
                    "regions": [
                        {
                            "region_key": key.hex(),
                            "outline": outline.as_digest_input(),
                            "masked": state.resolved[key].masked,
                            "confirmed": state.subjects[key] is not None,
                        }
                        for key, outline in sorted(state.outlines.items())
                    ],
                }
            )
        evaluation_digest = receipt["evaluation"]["content_sha256"]
        with zipfile.ZipFile(io.BytesIO(_blob(blobs, evaluation_digest))) as archive:
            metrics_digest = hashlib.sha256(archive.read("metrics.json")).hexdigest()
        observed = connection.execute("select transaction_timestamp() as at").fetchone()["at"]
        readonly = connection.execute("show transaction_read_only").fetchone()[
            "transaction_read_only"
        ]
    ply, decoder = _decode_sog(data)
    return {
        "code": code,
        "observed_at": observed.isoformat(),
        "workspace_id": str(workspace),
        "scene_id": str(row["scene_id"]),
        "artifact_id": str(artifact),
        "artifact_sha256": digest,
        "publication_receipt_sha256": receipt_digest,
        "pose_receipt_sha256": pose_digest,
        "retained_evaluation_bundle_sha256": evaluation_digest,
        "retained_metrics_sha256": metrics_digest,
        "database_read_only": readonly == "on",
        "region_snapshot": regions,
        "region_snapshot_sha256": hashlib.sha256(canonical_json(regions)).hexdigest(),
        "decoder": decoder,
        "evaluation_bundle": evaluate_ply(ply, views),
        "limitations": [
            "No COLMAP, CUDA training, hosted model, or photograph screening was executed.",
            "Counts cover recorded current regions in recovered cameras only; "
            "unrecorded people are not assessed.",
            "Distorted cameras use a pinhole approximation with a 20000 ppm margin, "
            "not exact distortion inversion.",
            "The retained training evaluation ZIP remains immutable; "
            "this is a new retrospective bundle.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--artifact", type=uuid.UUID, required=True)
    parser.add_argument("--blobs", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    binding = predecessor(args.predecessor)
    record = measure(args.workspace, args.artifact, args.blobs)
    record["predecessor_record"] = binding
    record["completed_at"] = dt.datetime.now(dt.UTC).isoformat()
    document = envelope(record)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")
    print(json.dumps(record["evaluation_bundle"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
