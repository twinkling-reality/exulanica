"""Execute scene-publication mutations in an isolated copy and one serialized test database.

The default runs pure controls only. --database-controls additionally needs exclusive use of
the repository's permitted disposable database. No production checkout files are mutated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exulanica.evaluation.reference_inputs import envelope

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_scene_splat_pipeline.py"
TRAINING = "exulanica/ingest/scene_splat.py"
PROCESSOR = "exulanica/ingest/scene_reconstruction.py"
GEOMETRY = "exulanica/graph/scene_geometry.py"
PURE_SELECTOR = (
    "request_roundtrips or admitted_split or dataset_copy or trained_bounds or unconfirmed "
    "or evaluation_bundle or cancellation_check_failure or recovered_camera_keeps"
)
CONTROLS = [
    (
        "retained_evaluation_companions_bind_runtime",
        TRAINING,
        'if runtime.get("profile") == "exulanica.gsplat-scene-runner/v1" or digest is not None:',
        "if False:",
        "test_evaluation_bundle_refuses_missing_or_changed_runtime_bound_companions",
        False,
    ),
    (
        "training_outputs_bind_exact_point_map_build",
        PROCESSOR,
        "training_input = input_digest_of(\n            [bytes.fromhex(manifest.digest), claimed.build_input_digest, claimed.job_id.bytes]\n        )",
        "training_input = bytes.fromhex(manifest.digest)",
        "test_changed_point_map_build_gets_new_training_artifacts_with_the_same_training_config",
        True,
    ),
    (
        "independent_recovered_camera_is_unscaled",
        "exulanica/reconstruction/placement.py",
        '"scene_from_camera_row_major": list(_scene_from_opm(camera, 1.0)),',
        '"scene_from_camera_row_major": list(_scene_from_opm(camera, 2.0)),',
        "tests/test_reconstruction_placement.py::test_recovered_camera_keeps_calibrated_projection_and_unscaled_renderer_pose",
        False,
    ),
    (
        "independent_camera_survives_missing_point_maps",
        "exulanica/graph/reconstruction_scenes.py",
        "exclusion_reason=excluded[capture_ref],\n                    recovered_camera=recovered_camera,",
        "exclusion_reason=excluded[capture_ref],\n                    recovered_camera=None,",
        "test_trained_scene_keeps_recovered_camera_when_all_point_map_bytes_are_missing",
        True,
    ),
    (
        "authorization_check_error_still_stops_the_worker",
        TRAINING,
        "except Exception as error:\n                        check_error = error",
        "except Exception:\n                        raise",
        "test_cancellation_check_failure_stops_the_live_subprocess_before_propagating",
        False,
    ),
    (
        "exact_dataset_bytes",
        TRAINING,
        "(source / relative).read_bytes() != destination_file.read_bytes()",
        "False",
        "test_dataset_copy_resumes_missing_files_but_refuses_changed_bytes",
        False,
    ),
    (
        "explicit_integer_compute_rate",
        TRAINING,
        "isinstance(value, bool) or not isinstance(value, int) or value < 0",
        "value < 0",
        "test_training_request_roundtrips_without_implicit_spending_or_split_changes",
        False,
    ),
    (
        "complete_prior_training_split",
        TRAINING,
        "or set(training) != set(sources) - set(heldout)",
        "or False",
        "test_admitted_split_requires_the_complete_identical_manifest",
        False,
    ),
    (
        "cleanup_marker_blocks_sweeping",
        "exulanica/ingest/reconstruction_scratch.py",
        'if any(target.rglob("container-cleanup-required.json")):',
        "if False:",
        "test_unconfirmed_container_cleanup_marker_protects_even_abandoned_scratch",
        False,
    ),
    (
        "unconfirmed_container_exit_is_not_success",
        TRAINING,
        "if forced or result.returncode == 76:",
        "if forced:",
        "test_unconfirmed_exit_retains_a_cleanup_guard_even_if_launcher_did_not_write_it",
        False,
    ),
    (
        "gaussian_bounds_verify_actual_bytes",
        TRAINING,
        "if len(payload) != count * stride:",
        "if False:",
        "test_trained_bounds_are_derived_from_actual_gaussian_bytes",
        False,
    ),
    (
        "retained_evaluation_pixel_digest",
        TRAINING,
        "relative in expected and hashlib.sha256(data).hexdigest() != expected[relative]",
        "False",
        "test_private_evaluation_bundle_retains_verified_pixels_and_excludes_scratch",
        False,
    ),
    (
        "damaged_point_map_preserves_healthy_scene_members",
        "exulanica/graph/reconstruction_scenes.py",
        "allow_unavailable_bytes=True,",
        "allow_unavailable_bytes=False,",
        "tests/test_scene_reconstruction_pipeline.py::test_graph_withholds_a_missing_alignment_input_but_preserves_healthy_members",
        True,
    ),
    (
        "training_is_a_causal_gate_input",
        PROCESSOR,
        "*(artifact.content_id.digest for artifact, _ in extras),",
        "",
        "test_changed_training_config_has_a_new_gate_and_unpublished_bytes_stay_hidden",
        True,
    ),
    (
        "only_current_published_geometry_is_served",
        GEOMETRY,
        "current is None or current.artifact_id != artifact_id",
        "current is None",
        "test_changed_training_config_has_a_new_gate_and_unpublished_bytes_stay_hidden",
        True,
    ),
    (
        "preemption_does_not_consume_failure_budget",
        "exulanica/ingest/spine/reconstruction_jobs.py",
        "attempts=greatest(0,attempts-1)",
        "attempts=attempts",
        "test_four_graceful_preemptions_keep_the_same_job_and_checkpoint_eligible",
        True,
    ),
    (
        "completed_training_survives_store_retry",
        PROCESSOR,
        'claimed.build_inputs.get("splat_training") is None\n                or claimed.attempts >= MAX_SCENE_CLAIMS',
        "True",
        "test_storage_retry_reuses_completed_training_instead_of_retraining",
        True,
    ),
    (
        "admitted_heldout_split_cannot_drift",
        TRAINING,
        "or set(heldout) != set(self.heldout_source_sha256)",
        "or False",
        "test_training_request_cannot_replace_the_previously_admitted_evaluation_split",
        True,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-controls", action="store_true")
    args = parser.parse_args()
    selected = [control for control in CONTROLS if args.database_controls or not control[-1]]
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    env.update(PYTHONDONTWRITEBYTECODE="1")
    if args.database_controls:
        env["EXULANICA_TEST_DATABASE_URL"] = "postgresql://localhost:5433/exulanica_spine_test"
    else:
        # A selected pure test unexpectedly requesting DB must fail, never use ambient config.
        env["EXULANICA_TEST_DATABASE_URL"] = "postgresql://invalid:1/no_database_allowed"
    output_root = ROOT / ".exulanica/reference-baseline"
    output_root.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="exulanica-scene-controls-") as directory:
        work = Path(directory)
        for name in ("exulanica", "tests"):
            shutil.copytree(ROOT / name, work / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        env["PYTHONPATH"] = str(work)

        def run(selector: str | None):
            command = [sys.executable, "-m", "pytest", "-q", TEST]
            if selector and "::" in selector:
                command[-1] = selector
            elif selector:
                command.append("tests/test_reconstruction_placement.py")
                command += ["-k", selector]
            elif args.database_controls:
                command.append("tests/test_reconstruction_placement.py")
                command.append("tests/test_scene_reconstruction_pipeline.py")
            return subprocess.run(
                command, cwd=work, env=env, capture_output=True, text=True, check=False
            )

        baseline = run(None if args.database_controls else PURE_SELECTOR)
        (output_root / "scene-controls-baseline.log").write_text(baseline.stdout + baseline.stderr)
        if baseline.returncode:
            print(baseline.stdout + baseline.stderr)
            return baseline.returncode
        for name, filename, old, new, selector, _db in selected:
            path = work / filename
            original = path.read_text()
            if original.count(old) != 1:
                raise ValueError(f"mutation {name} needs exactly one target")
            path.write_text(original.replace(old, new, 1))
            try:
                result = run(selector)
            finally:
                path.write_text(original)
            output = result.stdout + result.stderr
            (output_root / f"scene-control-{name}.log").write_text(output)
            expected_test = selector if "::" in selector else f"{TEST}::{selector}"
            killed = result.returncode == 1 and f"FAILED {expected_test}" in output
            records.append(
                {
                    "mutation": name,
                    "production_file": filename,
                    "replace": old,
                    "with": new,
                    "test_selector": selector,
                    "returncode": result.returncode,
                    "killed": killed,
                    "observed_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                }
            )
            print(name, "killed" if killed else "SURVIVED/ERROR", flush=True)
        restored = run(None if args.database_controls else PURE_SELECTOR)
        (output_root / "scene-controls-restored.log").write_text(restored.stdout + restored.stderr)
    record = {
        "profile": "exulanica.scene-publication-negative-controls/v1",
        "fixture_notice": "Numeric synthetic OPM/COLMAP and named scripted trainer; no CUDA run.",
        "database_controls": args.database_controls,
        "baseline_returncode": baseline.returncode,
        "restored_returncode": restored.returncode,
        "controls": records,
    }
    destination = output_root / (
        "scene-publication-controls.json"
        if args.database_controls
        else "scene-publication-pure-controls.json"
    )
    destination.write_text(json.dumps(envelope(record), indent=2, sort_keys=True) + "\n")
    print(destination)
    return 0 if all(item["killed"] for item in records) and restored.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
