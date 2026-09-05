"""Compare two fresh CPU pose runs over one generated synthetic source manifest.

Run with the pose extra installed:
    uv run python scripts/measure_pose_recomputation.py --out /tmp/pose-comparison

The output directory must be new. No database, model endpoint or personal media is used.
This compares bytes and records disagreement; it never turns the deterministic flag into proof.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.evaluation.synthetic_multiview import generate_synthetic_multiview
from exulanica.ingest.stages import stage
from exulanica.reconstruction.pose import PoseBuildManifest, SourceFrame, run_colmap_pose_job
from exulanica.reconstruction.pycolmap_executor import (
    PYCOLMAP_EXECUTABLE, PycolmapExecutor, pycolmap_version,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    fixture = generate_synthetic_multiview(args.out / "source")
    runtime = {
        "python": platform.python_version(), "system": platform.system(),
        "machine": platform.machine(),
        "packages": {name: importlib.metadata.version(name)
                     for name in ("pycolmap", "numpy", "pillow")},
        "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
    }
    runtime_digest = hashlib.sha256(canonical_json(runtime)).hexdigest()
    policy = stage("scene_pose").params
    manifest = PoseBuildManifest(
        scene_ref="synthetic-recomputation-room",
        code_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        colmap_version=pycolmap_version(),
        # The controller requires a digest-labelled execution identity. This is explicitly a
        # local runtime fingerprint, not a claim that a container image was built or executed.
        execution_image=f"local-runtime@sha256:{runtime_digest}",
        frames=tuple(SourceFrame(
            capture_ref=f"synthetic-{index}", filename=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), capture_set="synthetic-room",
        ) for index, path in enumerate(sorted(fixture.image_directory.glob("*.jpg")))),
        min_registered_fraction=policy["min_registered_fraction_millionths"] / 1_000_000,
        max_mean_reprojection_error_px=policy["max_mean_reprojection_error_micropixels"] / 1_000_000,
        min_camera_translation_units=policy["min_camera_translation_microunits"] / 1_000_000,
    )
    runs = []
    for index in range(2):
        result = run_colmap_pose_job(
            manifest, source_dir=fixture.image_directory, jobs_root=args.out / f"run-{index}",
            executable=PYCOLMAP_EXECUTABLE, executor=PycolmapExecutor(),
        )
        if result.status != "completed" or result.reused:
            raise RuntimeError(f"fresh pose run did not complete: {result.failure_reason}")
        data = (result.job_directory / "receipt.json").read_bytes()
        receipt = json.loads(data)
        if len(receipt["quality"]["registered_images"]) < 3:
            raise RuntimeError("pose comparison requires at least three recovered cameras")
        runs.append({
            "receipt_sha256": hashlib.sha256(data).hexdigest(),
            "quality_sha256": receipt["quality_digest"],
            "registered_images": receipt["quality"]["registered_images"],
            "accepted": receipt["quality"]["accepted"],
            "reused": result.reused,
        })
    record = {
        "profile": "exulanica.pose-recomputation-comparison/v1",
        "corpus_class": "synthetic", "source_manifest_sha256": fixture.source_manifest_digest,
        "camera_manifest_sha256": fixture.camera_manifest_digest,
        "pose_manifest_sha256": manifest.digest, "runtime": runtime, "runs": runs,
        "receipt_bytes_identical": runs[0]["receipt_sha256"] == runs[1]["receipt_sha256"],
        "quality_bytes_identical": runs[0]["quality_sha256"] == runs[1]["quality_sha256"],
        "limitations": [
            "Two fresh runs on one machine; no cross-machine reproducibility claim.",
            "Local runtime fingerprint is not a container image or production execution.",
            "No vision/depth output, metric scale, corridor or real-world quality was measured.",
        ],
    }
    envelope = {"profile": "exulanica.digest-bound-record/v1", "record": record,
                "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest()}
    (args.out / "comparison.json").write_text(json.dumps(envelope, indent=2) + "\n")
    print(json.dumps(envelope, indent=2))


if __name__ == "__main__":
    main()
